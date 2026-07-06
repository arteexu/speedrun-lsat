#!/usr/bin/env python3
# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Generate original LSAT items with a LLM until the deck reaches a target size.

This is the "generate -> verify -> keep" loop. Each draft must clear a stack of
gates before it is appended to ``seed_deck.json``; anything that fails is dropped
and a replacement is generated:

  1. structural   - 5 choices, exactly one correct, real runner-up + rationale,
                    non-empty stimulus/question
  2. taxonomy     - every schema id and choice trap resolves in the taxonomy
  3. solver       - an independent, answer-key-hidden cold solve agrees with the
                    credited answer and reports a single defensible answer
                    (speedrun.ai.solver_verify) -- runs in the worker threads
  4. dedup        - token-similarity below threshold vs the existing deck AND the
                    items accepted so far this run -- runs single-threaded in the
                    collector so all items stay unique
  5. card-checker - the pre-set keyword cutoff ship gate (spec 7f,
                    speedrun.ai.card_checker.CardCheckGate). ON by default; an item
                    below the cutoff is blocked before it is written, and the run
                    reports the three counts (correct_useful / wrong /
                    correct_bad_teaching). Disable with ``--no-card-checker``.

Generation + solving are network-bound, so drafts are produced concurrently with
a thread pool (``--workers``); the collector thread does dedup, the card-checker
gate, id assignment and incremental saves.

Composition is rebalanced toward a realistic LSAT mix using the taxonomy's
exam_weights rather than copying the deck's current flaw-heavy distribution.

Usage (needs AI enabled + an OpenAI key resolvable via SPEEDRUN_AI_SETTINGS_PATH,
ANKI_BASE, or OPENAI_API_KEY):
    PYTHONPATH=out/pylib:$PWD out/pyenv/bin/python -m speedrun.tools.generate_to_target \
        --target 500 --workers 10 --report docs/speedrun/generation_report.json
    ... --smoke 6            # tiny run for wiring checks
    ... --deck /tmp/x.json   # write to a copy instead of the real deck
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path

from speedrun.ai.card_checker import PASSING_CUTOFF, CardCheckGate
from speedrun.ai.client import LLMClient, OpenAILLMClient
from speedrun.ai.solver_verify import solve_item, _extract_json_obj
from speedrun.tools.assign_units import assign_all, build_manifest, validate_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]
TAXONOMY = REPO_ROOT / "speedrun" / "taxonomy" / "lsat_taxonomy.json"
SEED = REPO_ROOT / "speedrun" / "data" / "seed_deck.json"

_WORD = re.compile(r"[a-z]{4,}")
DEDUP_THRESHOLD = 0.55
_rand_lock = threading.Lock()

# LR stem types that pair a natural flaw schema; the rest carry only their qt id.
_FLAW_PAIRED = {
    "qt.flaw", "qt.weaken", "qt.strengthen", "qt.evaluate",
    "qt.necessary_assumption", "qt.sufficient_assumption",
    "qt.parallel_flaw", "qt.method_of_reasoning",
}
_DEFAULT_FLAW_FOR = {
    "qt.necessary_assumption": "flaw.gap.unwarranted_assumption",
    "qt.sufficient_assumption": "flaw.gap.unwarranted_assumption",
    "qt.weaken": "flaw.causal.correlation_causation",
    "qt.strengthen": "flaw.causal.correlation_causation",
    "qt.evaluate": "flaw.causal.correlation_causation",
    "qt.method_of_reasoning": "flaw.structure.comparison",
}


@dataclass
class Tally:
    generated: int = 0
    accepted: int = 0
    rejects: Counter = field(default_factory=Counter)
    solver_calls: int = 0
    gen_calls: int = 0

    def as_dict(self) -> dict:
        return {
            "generated_drafts": self.generated,
            "accepted": self.accepted,
            "rejects": dict(self.rejects),
            "solver_calls": self.solver_calls,
            "generation_calls": self.gen_calls,
        }


# ----------------------------------------------------------------------------- taxonomy


def load_taxonomy() -> dict:
    tax = json.loads(TAXONOMY.read_text(encoding="utf-8"))
    tax["_by_id"] = {s["id"]: s for s in tax["schemas"]}
    return tax


def valid_ids(tax: dict) -> set[str]:
    return set(tax["_by_id"].keys())


def lr_qt_schemas(tax: dict) -> list[dict]:
    return [s for s in tax["schemas"] if s["axis"] == "question_type"]


def rc_schemas(tax: dict) -> list[dict]:
    return [s for s in tax["schemas"] if s["axis"] == "rc_structure"]


def flaw_ids(tax: dict) -> list[str]:
    return [s["id"] for s in tax["schemas"] if s["axis"] == "flaw"]


def lr_trap_ids(tax: dict) -> list[str]:
    return [s["id"] for s in tax["schemas"]
            if s["axis"] == "trap" and not s["id"].startswith("trap.rc.")]


def rc_trap_ids(tax: dict) -> list[str]:
    general = {"trap.out_of_scope", "trap.too_strong_extreme", "trap.half_right",
               "trap.premise_restatement", "trap.right_answer_wrong_question"}
    return [s["id"] for s in tax["schemas"]
            if s["axis"] == "trap" and (s["id"].startswith("trap.rc.") or s["id"] in general)]


# ----------------------------------------------------------------------------- text/dedup


def _tokens(item: dict) -> set[str]:
    # Dedup on question + choices, plus the LR stimulus. The RC ``passage`` is
    # deliberately excluded: several questions legitimately share one passage, so
    # including it would flag q2/q3 of a set as near-duplicates of q1.
    parts = [item.get("question", ""), item.get("stimulus", "")]
    for c in item.get("choices", []):
        parts.append(c.get("text", ""))
    return set(_WORD.findall(" ".join(parts).lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def is_duplicate(item: dict, existing_tokens: list[set[str]], threshold: float) -> bool:
    toks = _tokens(item)
    return any(_jaccard(toks, other) >= threshold for other in existing_tokens)


# ----------------------------------------------------------------------------- validation


def structural_ok(item: dict) -> str | None:
    choices = item.get("choices", [])
    if len(choices) != 5:
        return f"expected 5 choices, got {len(choices)}"
    ids = [str(c.get("id")) for c in choices]
    if sorted(ids) != ["A", "B", "C", "D", "E"]:
        return "choice ids not A-E"
    n_correct = sum(1 for c in choices if c.get("correct"))
    if n_correct != 1:
        return f"exactly one correct required, got {n_correct}"
    stem = item.get("stimulus") or item.get("passage")
    if not stem or not str(stem).strip():
        return "empty stimulus/passage"
    if not str(item.get("question", "")).strip():
        return "empty question"
    fork = item.get("two_answer_fork") or {}
    ru = str(fork.get("runner_up", "")).strip().upper()
    if ru not in {"A", "B", "C", "D", "E"}:
        return "runner_up missing/invalid"
    credited = next((str(c["id"]) for c in choices if c.get("correct")), None)
    if ru == credited:
        return "runner_up equals credited answer"
    if len(str(fork.get("why_runner_up_wrong", "")).strip()) < 15:
        return "why_runner_up_wrong too short"
    return None


def taxonomy_ok(item: dict, valid: set[str]) -> str | None:
    for sid in item.get("schemas", []):
        if sid not in valid:
            return f"unknown schema id {sid}"
    for c in item.get("choices", []):
        trap = c.get("trap")
        if trap and trap not in valid:
            return f"unknown trap id {trap}"
    return None


# ----------------------------------------------------------------------------- prompts


def build_lr_prompt(stem: dict, flaw_hint: str | None, difficulty: int,
                    allowed_traps: list[str]) -> str:
    traps = ", ".join(allowed_traps)
    flaw_line = (f"The argument should center on this reasoning issue: {flaw_hint}.\n"
                 if flaw_hint else "")
    return (
        "Write ONE original LSAT Logical Reasoning practice item. It must be your "
        "own invention: do NOT reproduce, paraphrase, or adapt any real, published, "
        "or copyrighted LSAT question. Use everyday, concrete subject matter.\n\n"
        f"Task type: {stem['name']} - {stem['description']}\n"
        f"Target difficulty (1 easy .. 4 hard): {difficulty}\n"
        f"{flaw_line}"
        "Exactly five choices A-E; exactly one is correct. Each WRONG choice must be "
        "a realistic distractor tagged with one trap id from this list:\n"
        f"  {traps}\n"
        "Include a two_answer_fork: the most tempting wrong choice (runner_up, a "
        "letter that is NOT the correct one) and a one-sentence why_runner_up_wrong "
        "that teaches the distinction.\n\n"
        "Return ONLY a JSON object, no prose, no code fences:\n"
        '{"stimulus":"...","question":"...","choices":[{"id":"A","text":"...",'
        '"correct":true,"trap":null},{"id":"B","text":"...","correct":false,'
        '"trap":"trap.out_of_scope"}, ... E],'
        '"two_answer_fork":{"runner_up":"B","why_runner_up_wrong":"..."}}'
    )


def build_rc_prompt(passage_schemas: list[dict], allowed_traps: list[str], k: int) -> str:
    traps = ", ".join(allowed_traps)
    tasks = "\n".join(f"  {i+1}. {s['name']} - {s['description']}"
                      for i, s in enumerate(passage_schemas))
    return (
        "Write ONE original LSAT Reading Comprehension passage plus "
        f"{k} questions. It must be your own invention: do NOT reproduce, "
        "paraphrase, or adapt any real, published, or copyrighted passage or "
        "question. The passage should be ~140-200 words, academic in tone "
        "(humanities, social science, natural science, or law).\n\n"
        f"Write exactly {k} questions, one for each of these targets in order:\n"
        f"{tasks}\n\n"
        "Each question has exactly five choices A-E, exactly one correct. Each "
        "wrong choice is tagged with one trap id from this list:\n"
        f"  {traps}\n"
        "Each question includes a two_answer_fork (runner_up letter that is NOT "
        "correct, and a one-sentence why_runner_up_wrong).\n\n"
        "Return ONLY a JSON object, no prose, no code fences:\n"
        '{"passage":"...","questions":[{"question":"...","choices":[{"id":"A",'
        '"text":"...","correct":true,"trap":null}, ... E],'
        '"two_answer_fork":{"runner_up":"B","why_runner_up_wrong":"..."}}]}'
    )


# ----------------------------------------------------------------------------- id allocation


def _max_suffix(items: list[dict], prefix: str) -> int:
    hi = 0
    pat = re.compile(rf"^{re.escape(prefix)}-(\d+)")
    for it in items:
        m = pat.match(str(it.get("id", "")))
        if m:
            hi = max(hi, int(m.group(1)))
    return hi


# ----------------------------------------------------------------------------- composition


def plan_lr(n_lr: int, qt: list[dict]) -> list[dict]:
    total_w = sum(s["exam_weight"] for s in qt)
    plan: list[dict] = []
    for s in qt:
        for _ in range(round(n_lr * s["exam_weight"] / total_w)):
            plan.append(s)
    random.shuffle(plan)
    return plan


def plan_rc(n_rc: int, rc: list[dict], k: int) -> list[list[dict]]:
    total_w = sum(s["exam_weight"] for s in rc)
    pool: list[dict] = []
    for s in rc:
        for _ in range(max(1, round(n_rc * s["exam_weight"] / total_w))):
            pool.append(s)
    random.shuffle(pool)
    return [pool[i : i + k] for i in range(0, len(pool), k) if pool[i : i + k]]


# ----------------------------------------------------------------------------- generation


def _difficulty() -> int:
    with _rand_lock:
        return random.choices([1, 2, 3, 4], weights=[1, 3, 4, 2])[0]


def _pick_flaw(stem_id: str, tax: dict) -> str:
    if stem_id in _DEFAULT_FLAW_FOR:
        return _DEFAULT_FLAW_FOR[stem_id]
    with _rand_lock:
        return random.choice(flaw_ids(tax))


def make_lr_item(stem: dict, tax: dict, gen: LLMClient) -> dict | None:
    if stem["id"] in _FLAW_PAIRED:
        flaw = _pick_flaw(stem["id"], tax)
        schemas = [flaw, stem["id"]]
        flaw_hint = tax["_by_id"][flaw]["description"]
    else:
        schemas = [stem["id"]]
        flaw_hint = None
    difficulty = _difficulty()
    resp = gen.complete(build_lr_prompt(stem, flaw_hint, difficulty, lr_trap_ids(tax)),
                        max_tokens=900)
    if not resp.ok:
        return None
    obj = _extract_json_obj(resp.text)
    if not obj:
        return None
    obj.update({"section": "LR", "stem_type": stem["id"], "schemas": schemas,
                "difficulty": difficulty, "source": "generated:llm",
                "source_model": resp.source})
    return obj


def make_rc_set(schemas_for_set: list[dict], tax: dict, gen: LLMClient) -> list[dict] | None:
    resp = gen.complete(build_rc_prompt(schemas_for_set, rc_trap_ids(tax), len(schemas_for_set)),
                        max_tokens=1800)
    if not resp.ok:
        return None
    obj = _extract_json_obj(resp.text)
    if not obj or not obj.get("passage") or not isinstance(obj.get("questions"), list):
        return None
    passage = str(obj["passage"]).strip()
    items: list[dict] = []
    for i, q in enumerate(obj["questions"]):
        if not isinstance(q, dict):
            continue
        sc = schemas_for_set[i] if i < len(schemas_for_set) else schemas_for_set[-1]
        items.append({
            "section": "RC", "stem_type": sc["id"], "schemas": [sc["id"]],
            "difficulty": _difficulty(), "source": "generated:llm",
            "source_model": resp.source, "passage": passage,
            "question": q.get("question", ""), "choices": q.get("choices", []),
            "two_answer_fork": q.get("two_answer_fork", {}),
        })
    return items or None


def repair_traps(item: dict, valid: set[str]) -> None:
    """Coerce model-invented trap ids to something valid, in place. Traps are
    advisory distractor labels, so an unknown one should not discard an otherwise
    sound item: normalize a bare name (``out_of_scope`` -> ``trap.out_of_scope``)
    when possible, else drop it (``None``). The credited answer + solver gate are
    what actually guarantee correctness."""
    for c in item.get("choices", []):
        t = c.get("trap")
        if not t or t in valid:
            continue
        prefixed = t if str(t).startswith("trap.") else f"trap.{t}"
        c["trap"] = prefixed if prefixed in valid else None


def ensure_runner_trap(item: dict) -> None:
    """Guarantee the runner-up distractor carries a nameable trap (Insight 8 / the
    contrasting-pair fork trainer requires it). If trap-repair dropped the model's
    label, fall back to ``trap.half_right`` -- definitionally apt for the "most
    tempting, partly-plausible" second-best answer."""
    ru = str((item.get("two_answer_fork") or {}).get("runner_up", "")).strip().upper()
    for c in item.get("choices", []):
        if str(c.get("id")) == ru and not c.get("correct") and not c.get("trap"):
            c["trap"] = "trap.half_right"


def precheck(item: dict, valid: set[str], solver: LLMClient, use_solver: bool) -> str:
    """All gates except dedup (which needs shared state). Returns a reason code;
    'ok' means the item passed and is ready for dedup + acceptance."""
    err = structural_ok(item)
    if err:
        return "structural"
    repair_traps(item, valid)
    ensure_runner_trap(item)
    if taxonomy_ok(item, valid):
        return "taxonomy"
    if use_solver:
        res = solve_item(item, solver)
        if not res.passed:
            if res.chosen and res.credited and res.chosen != res.credited:
                return "solver_mismatch"
            if res.single_best is False:
                return "solver_ambiguous"
            return "solver_other"
    return "ok"


# ----------------------------------------------------------------------------- workers


def task_lr(stem, tax, valid, gen, solver, use_solver):
    item = make_lr_item(stem, tax, gen)
    if not item:
        return ("gen_empty_or_unparseable", None, 1, 0)
    reason = precheck(item, valid, solver, use_solver)
    return (reason, item if reason == "ok" else None, 1, 1 if use_solver else 0)


def task_rc(schemas_for_set, tax, valid, gen, solver, use_solver):
    built = make_rc_set(schemas_for_set, tax, gen)
    if not built:
        return ("gen_empty_or_unparseable", None, 0, 0)
    kept, solver_calls = [], 0
    for it in built:
        reason = precheck(it, valid, solver, use_solver)
        if use_solver:
            solver_calls += 1
        if reason == "ok":
            kept.append(it)
    return ("ok" if kept else "rc_all_failed", kept, len(built), solver_calls)


def write_deck(data: dict, path: Path) -> None:
    assign_all(data["items"], overwrite=False)
    data["units"] = build_manifest(data["items"])
    validate_manifest(data["items"], data["units"])
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ----------------------------------------------------------------------------- main


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", type=int, default=500)
    ap.add_argument("--rc-share", type=float, default=0.20)
    ap.add_argument("--rc-per-passage", type=int, default=3)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--threshold", type=float, default=DEDUP_THRESHOLD)
    ap.add_argument("--smoke", type=int, default=0, help="if >0, only add this many items")
    ap.add_argument("--no-solver", action="store_true")
    ap.add_argument("--no-card-checker", action="store_true",
                    help="disable the pre-set keyword card-checker ship gate (spec 7f); "
                         "the gate is ON by default")
    ap.add_argument("--checker-cutoff", type=float, default=PASSING_CUTOFF,
                    help="passing cutoff for the card-checker gate")
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--save-every", type=int, default=15)
    ap.add_argument("--max-attempts", type=int, default=0, help="0 = auto (6x needed + 40)")
    ap.add_argument("--deck", type=Path, default=SEED)
    ap.add_argument("--report", type=Path,
                    default=REPO_ROOT / "docs" / "speedrun" / "generation_report.json")
    args = ap.parse_args(argv)

    deck_path = args.deck
    random.seed(args.seed)
    tax = load_taxonomy()
    tax_valid = valid_ids(tax)
    data = json.loads(deck_path.read_text(encoding="utf-8"))
    items = data["items"]
    start_count = len(items)

    need = args.smoke if args.smoke else max(0, args.target - start_count)
    if need == 0:
        print(f"Deck already has {start_count} items (>= target {args.target}).")
        return 0

    n_rc = round(need * args.rc_share)
    n_lr = need - n_rc
    print(f"Deck has {start_count} items; need {need} more (~{n_lr} LR, ~{n_rc} RC) "
          f"to reach ~{args.target}. workers={args.workers} solver={not args.no_solver}",
          flush=True)

    seen_tokens = [_tokens(it) for it in items]
    tally = Tally()
    gen = OpenAILLMClient(temperature=0.9)
    solver = OpenAILLMClient(temperature=0.0)
    use_solver = not args.no_solver
    # Card-checker ship gate (spec 7f): ON by default. Keyword-only (deterministic,
    # offline) so it never adds network cost or nondeterminism to the run.
    card_gate = None if args.no_card_checker else CardCheckGate(cutoff=args.checker_cutoff)
    lr_num = _max_suffix(items, "lr")
    rc_num = _max_suffix(items, "rc")
    max_attempts = args.max_attempts or (need * 6 + 40)
    t0 = time.time()
    accepted_since_save = 0

    def maybe_save(force: bool = False) -> None:
        nonlocal accepted_since_save
        if accepted_since_save and (force or accepted_since_save >= args.save_every):
            write_deck(data, deck_path)
            print(f"  ...saved: deck={len(items)} accepted={tally.accepted} "
                  f"attempts={tally.gen_calls} t={time.time()-t0:.0f}s "
                  f"rejects={dict(tally.rejects)}", flush=True)
            accepted_since_save = 0

    # ---- LR phase (concurrent) ----
    lr_specs = plan_lr(n_lr, lr_qt_schemas(tax))
    lr_cycle = itertools.cycle(lr_specs) if lr_specs else None
    if lr_cycle:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            inflight = {ex.submit(task_lr, next(lr_cycle), tax, tax_valid, gen, solver, use_solver)
                        for _ in range(min(args.workers * 2, n_lr * 2 or 2))}
            lr_accepted = 0
            while inflight and lr_accepted < n_lr and tally.gen_calls < max_attempts:
                done, inflight = wait(inflight, return_when=FIRST_COMPLETED)
                for fut in done:
                    reason, item, gen_c, solv_c = fut.result()
                    tally.gen_calls += gen_c
                    tally.generated += gen_c
                    tally.solver_calls += solv_c
                    if reason == "ok" and item is not None:
                        if is_duplicate(item, seen_tokens, args.threshold):
                            tally.rejects["duplicate"] += 1
                        elif card_gate is not None and not card_gate.check(item).passed:
                            tally.rejects["card_checker"] += 1
                        else:
                            lr_num += 1
                            item["id"] = f"lr-{lr_num:04d}"
                            items.append(item)
                            seen_tokens.append(_tokens(item))
                            tally.accepted += 1
                            lr_accepted += 1
                            accepted_since_save += 1
                            maybe_save()
                    else:
                        tally.rejects[reason] += 1
                    if lr_accepted < n_lr and tally.gen_calls < max_attempts:
                        inflight.add(ex.submit(task_lr, next(lr_cycle), tax, tax_valid,
                                               gen, solver, use_solver))
    maybe_save(force=True)

    # ---- RC phase (concurrent; whole sets) ----
    rc_sets = plan_rc(n_rc, rc_schemas(tax), args.rc_per_passage)
    if rc_sets:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(task_rc, s, tax, tax_valid, gen, solver, use_solver): s
                    for s in rc_sets}
            for fut in list(futs):
                if tally.gen_calls >= max_attempts:
                    break
                reason, built, gen_c, solv_c = fut.result()
                tally.gen_calls += 1
                tally.generated += gen_c
                tally.solver_calls += solv_c
                if reason != "ok" or not built:
                    tally.rejects[reason] += 1
                    continue
                rc_num += 1
                pid = f"rc-{rc_num:04d}"
                qn = 0
                for it in built:
                    if is_duplicate(it, seen_tokens, args.threshold):
                        tally.rejects["duplicate"] += 1
                        continue
                    if card_gate is not None and not card_gate.check(it).passed:
                        tally.rejects["card_checker"] += 1
                        continue
                    qn += 1
                    it["passage_id"] = pid
                    it["id"] = f"{pid}-q{qn}"
                    items.append(it)
                    seen_tokens.append(_tokens(it))
                    tally.accepted += 1
                    accepted_since_save += 1
                maybe_save()
    maybe_save(force=True)

    elapsed = time.time() - t0
    dist = Counter(it["stem_type"] for it in items)
    sect = Counter(it["section"] for it in items)
    report = {
        "target": args.target, "start_count": start_count, "final_count": len(items),
        "added": len(items) - start_count, "elapsed_seconds": round(elapsed, 1),
        "tally": tally.as_dict(),
        "section_distribution": dict(sect),
        "stem_type_distribution": dict(sorted(dist.items(), key=lambda kv: -kv[1])),
        "dedup_threshold": args.threshold, "solver_gate": use_solver,
        "card_checker_gate": card_gate is not None,
        "card_checker": card_gate.tally.to_dict() if card_gate is not None else None,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nDone in {elapsed:.0f}s. Deck: {start_count} -> {len(items)} "
          f"(+{len(items)-start_count}). Report: {args.report}", flush=True)
    print(f"Accepted {tally.accepted} of {tally.generated} drafts; "
          f"rejects: {dict(tally.rejects)}", flush=True)
    if card_gate is not None:
        t = card_gate.tally
        print(f"Card-checker gate (cutoff {t.cutoff}): checked={t.n_checked} "
              f"passed={t.n_passed} blocked={t.n_blocked} | "
              f"correct_useful={t.correct_useful} wrong={t.wrong} "
              f"correct_bad_teaching={t.correct_bad_teaching}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
