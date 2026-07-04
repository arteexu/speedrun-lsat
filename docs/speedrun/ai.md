# AI in Speedrun LSAT — what we built, why, and what we skipped

AI is **off by default** (`SPEEDRUN_AI_OFF=1`) and every score works with it off.
Turn it on with `SPEEDRUN_AI_OFF=0` and `OPENAI_API_KEY=...` (optionally
`OPENAI_MODEL`, `OPENAI_BASE_URL`).

## What we built

| Piece | File | Why |
|-------|------|-----|
| Pluggable LLM client (real OpenAI-compatible HTTP; stub + scripted for tests) | [speedrun/ai/client.py](../../speedrun/ai/client.py) | One seam for all model calls; CI never touches the network |
| Card generator from one named source | [speedrun/ai/card_generator.py](../../speedrun/ai/card_generator.py) | Generate practice items from [lr_flaws_primer.md](../../speedrun/data/sources/lr_flaws_primer.md); every item stamped with `source` + `source_model` |
| Card checker + blocking gate | [speedrun/ai/card_checker.py](../../speedrun/ai/card_checker.py) | Keyword topicality + optional LLM correctness veto; `block_failing` keeps sub-cutoff cards away from students |
| Pre-ship eval + baselines | [speedrun/eval/ai_eval.py](../../speedrun/eval/ai_eval.py), [speedrun/ai/baseline.py](../../speedrun/ai/baseline.py) | Accuracy + wrong-answer rate on a held-out gold split vs a stated cutoff; side-by-side AI vs keyword vs TF-IDF vector |
| Reasoning evaluator | [speedrun/ai/reasoning_evaluator.py](../../speedrun/ai/reasoning_evaluator.py) | LLM grades a student explanation grounded in the fork rationale; offline heuristic fallback |
| AI Tutor (chat) | [speedrun/ai/tutor.py](../../speedrun/ai/tutor.py) | Grounded chat over ONE problem: answers why a choice is right/wrong, the flaw tested, and the two-answer fork. Deterministic offline answerer when AI is off; source-enforced + injection-sanitized when on. Never feeds the scores |
| RC commentator | [speedrun/rc_commentator.py](../../speedrun/rc_commentator.py) | Passage help; grounded/extractive offline path |
| Safety helpers | [speedrun/ai/guard.py](../../speedrun/ai/guard.py) | Prompt-injection sanitization of source text; source-enforcement (`resp.ok`) before any AI output is shown |
| Leakage check | [speedrun/eval/leakage_check.py](../../speedrun/eval/leakage_check.py) | Confirms gold vs training/generated do not overlap |

## Why these choices
- **Retrieval, not memorization** (BrainLift): AI targets the *reasoning* layer — checking correctness, grading explanations, generating fresh transfer items — never the scores.
- **Honesty rule**: AI output is shown only with a named `source`; the three scores are computed entirely from the revlog/FSRS and never import `speedrun.ai`.
- **Grounding**: generation is confined to one named source; RC/answers quote the passage; reasoning grades against the item's own rationale.

## How the checks run (before students see anything)
```bash
SPEEDRUN_AI_OFF=0 OPENAI_API_KEY=sk-... \
  PYTHONPATH=out/pylib out/pyenv/bin/python speedrun/tools/speedrun_cli.py ai-eval
```
Reports per-method accuracy + wrong-answer rate; the gate passes only when the AI
clears the accuracy cutoff (`ACCURACY_CUTOFF`) AND beats both baselines. Generated
cards must pass `block_failing` (cutoff `PASSING_CUTOFF`) before use.

## What we skipped (and why)
- **Fine-tuning / custom models** — a general model + grounding + checking is enough for this content; not worth the cost/complexity now.
- **Full RAG index** — the corpus (taxonomy + one source) is small; TF-IDF retrieval is the right-sized baseline.
- **AI-authored scores** — deliberately never; scores stay deterministic and engine-derived (honesty rule).
- **In-app generative RC on by default** — stays opt-in behind the off switch.

## Off-switch guarantee
`test_three_scores_compute_with_ai_off` asserts memory/performance/readiness all
compute with `SPEEDRUN_AI_OFF=1`. All AI unit tests use the scripted client, so CI
runs fully offline.

> Real eval numbers require a key and are recorded in
> [RESULTS.md](RESULTS.md) after a live run; with AI off the harness reports the
> baseline-only numbers and the gate fails honestly.
