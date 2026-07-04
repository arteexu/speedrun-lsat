# AI notes — what we built, why, what we skipped (+ the proof numbers)

A short, demo-ready note on the AI in **Speedrun LSAT**. The longer engineering
write-up is [`docs/speedrun/ai.md`](ai.md); the feature→origin map is
[`docs/speedrun/TRACEABILITY.md`](TRACEABILITY.md). This file adds the concrete,
copy-pasteable **proof numbers** and the commands to reproduce them.

All commands assume the repo built once (`out/pylib`, `out/pyenv`). Prefix:

```bash
export PYTHONPATH=out/pylib
PY=out/pyenv/bin/python
```

---

## What we built (and why)

The AI targets the **reasoning layer**, never the score. It is **off by default**
(`SPEEDRUN_AI_OFF=1`) and every surface has a deterministic, grounded fallback so
the product is fully useful with no key.

| Piece | File | Why |
|-------|------|-----|
| Grounded AI **tutor** (chat over ONE problem) | [`speedrun/ai/tutor.py`](../../speedrun/ai/tutor.py) | Answers "why is this right/wrong, what flaw, how to split the final two" from the item's own stimulus, choices, trap tags, schema, and two-answer fork — no outside facts. Offline answerer when AI is off. |
| **Study recommender** | [`speedrun/ai/recommender.py`](../../speedrun/ai/recommender.py) | Turns the three scores + weakest schemas into a next-step plan; AI adds an explained plan only when it returns a named source. |
| Contrasting-pair **reasoning compare** | [`speedrun/ai/pair_compare.py`](../../speedrun/ai/pair_compare.py) | Compares the student's reasoning path to the credited one on the answered item; grounded in that item alone. |
| **RC commentator** | [`speedrun/rc_commentator.py`](../../speedrun/rc_commentator.py) | Extractive/grounded passage read; generative only when enabled, and told to quote the passage and separate reported views from the author's. |
| Pluggable **LLM client** | [`speedrun/ai/client.py`](../../speedrun/ai/client.py) | One seam: real OpenAI-compatible HTTP, plus stub + scripted clients so CI never touches the network. Every response carries a named `source`. |
| **Off switch / config + settings** | [`speedrun/ai/config.py`](../../speedrun/ai/config.py), [`speedrun/ai/settings.py`](../../speedrun/ai/settings.py) | `SPEEDRUN_AI_OFF` (env) overrides the device-local setting; default OFF. |
| **Traceability + injection guard** | [`speedrun/ai/guard.py`](../../speedrun/ai/guard.py) | Source enforcement + prompt-injection sanitization of untrusted source text. |
| **Card generator + checker** | [`speedrun/ai/card_generator.py`](../../speedrun/ai/card_generator.py), [`speedrun/ai/card_checker.py`](../../speedrun/ai/card_checker.py) | Generate items from one named source; block sub-cutoff/wrong cards before students see them. |
| **Evals** | [`speedrun/eval/ai_eval.py`](../../speedrun/eval/ai_eval.py), [`speedrun/eval/grounding_eval.py`](../../speedrun/eval/grounding_eval.py) | Held-out accuracy/wrong-rate with a cutoff; side-by-side vs keyword/vector. |

**Why these choices:** the LSAT is a *transfer* problem, so AI is spent on
reasoning help and content QA, not on producing the number. Grounding (one named
source, quote-the-passage, grade-against-the-rationale) is the main defense
against hallucination.

## What we intentionally skipped
- **On-device / local LLM** — offline-first is handled by the deterministic
  grounded fallbacks; a bundled local model isn't worth the size/complexity now.
- **Fine-tuning a custom model** — a general model + grounding + a pre-ship
  checker is enough for this content.
- **A full RAG vector index** — the corpus (taxonomy + one primer) is tiny;
  stdlib TF-IDF is the right-sized retrieval.
- **AI anywhere near the scores** — deliberately never; the three scores are
  computed only from the revlog/FSRS (honesty rule).

---

## The 5 requirements → proof

### 1. Note on what AI we built / why / skipped
This file + [`ai.md`](ai.md). **PASS.**

### 2. Every AI output traces back to a named source
An AI response is shown **only** when `LLMResponse.ok` is true — which now
requires non-empty text **and a non-blank `source`** that isn't a `stub`/error
marker. All surfaces (tutor, recommender, pair-compare, RC commentator, card
checker/generator, reasoning evaluator) gate on this; untrusted source text is
injection-sanitized before it enters a prompt.

- Code: [`speedrun/ai/client.py`](../../speedrun/ai/client.py) `LLMResponse.ok`,
  [`speedrun/ai/guard.py`](../../speedrun/ai/guard.py) `has_named_source` /
  `require_source` / `sanitize_source_text`.
- Tests: `test_llmresponse_ok_requires_text_and_named_source`,
  `test_source_enforcement_guard`, `test_sanitize_strips_injection_lines`
  (in `pylib/tests/test_speedrun_ai.py`).

### 3. Eval that runs before students see anything (offline, deterministic)

```bash
$PY -m speedrun.eval.grounding_eval      # exit code != 0 blocks a release
```

| method | accuracy | wrong-rate | mean F1 |
|--------|---------:|-----------:|--------:|
| keyword | 30% | 70% | 0.230 |
| vector | 30% | 70% | 0.240 |
| **grounded** | **50%** | **50%** | **0.305** |

Held-out: 10 test items / 40 Q&A corpus (deterministic every-5th split).
Correct at token-F1 ≥ **0.3**; accuracy cutoff **0.4**; grounded must also beat
both baselines. **GATE PASSED** (grounded 50% ≥ 40% and > both). Exits non-zero
on failure, so it gates in CI. **PASS.**

The LLM-**generation** eval ([`ai_eval.py`](../../speedrun/eval/ai_eval.py),
cutoff 0.6) needs a key; run offline it honestly reports the generative column at
**0% / 100%** and the gate **fails** — proof the gate refuses to ship an
unconfigured/broken model:

```bash
$PY -m speedrun.eval.ai_eval             # offline: AI 0% -> GATE FAILED (exit 1)
```

With a real (or scripted) model it reaches 100% and passes — asserted by
`test_ai_eval_gate_passes_when_ai_answers_correctly`.

### 4. Side-by-side: our approach beats a simpler method
Same command/table as #3. The **grounded** method (retrieve from the *named
source of truth* — the schema taxonomy) beats both **keyword** (Jaccard) and
**vector** (TF-IDF) search over a Q&A bank, on accuracy, wrong-rate, and mean F1.
The edge comes from *what it grounds in* — an authoritative named source — which
is exactly the tutor's advantage over bare search, and the reason the LLM path is
required to keep a named source. **PASS.**

### 5. The app still scores with AI switched off

```bash
SPEEDRUN_AI_OFF=1 $PY speedrun/tools/offline_test.py
```

With `SPEEDRUN_AI_OFF=1` (`ai_enabled()` → `False`), all three scores compute
from the revlog/FSRS (they never import `speedrun.ai`):

| score | value |
|-------|-------|
| Memory | 100% |
| Performance | 99% |
| Readiness | 170 (range 160–180, medium confidence) |

- Code: [`speedrun/scoring/{memory,performance,readiness}.py`](../../speedrun/scoring).
- Test: `test_three_scores_compute_with_ai_off` (`pylib/tests/test_speedrun_ai.py`). **PASS.**

---

## Reproduce everything

```bash
export PYTHONPATH=out/pylib:pylib:.
PY=out/pyenv/bin/python

$PY -m speedrun.eval.grounding_eval                 # #3/#4 offline gate + side-by-side
$PY -m speedrun.eval.ai_eval                        # #3 generation gate (offline: fails honestly)
SPEEDRUN_AI_OFF=1 $PY speedrun/tools/offline_test.py   # #5 scores with AI off
$PY -m pytest pylib/tests/test_speedrun_ai.py -q    # #2 traceability + eval tests
```
