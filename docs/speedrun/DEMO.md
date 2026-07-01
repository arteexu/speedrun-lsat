# Speedrun LSAT — Demo Script

~10 minute walkthrough for graders / stakeholders.

## Setup (before demo)

```bash
cd ~/dev/speedrun-lsat
./run                                    # desktop app (first run builds ~5 min)
```

Or if already built:

```bash
./run --profile .ankidata              # use dev profile
```

## 1. Import seed deck (30 sec)

1. Open Anki desktop (Speedrun fork).
2. **Tools → LSAT Speedrun → Import Seed Deck**
3. Confirm 11 cards imported into "LSAT Speedrun — seed".

## 2. Study session (2 min)

1. Select the LSAT Speedrun deck.
2. Study 5–10 cards — answer Good/Bad, note latency is recorded.
3. Optional: **Tools → LSAT Speedrun → Schema-Weighted Queue Preview** to show
   Rust ordering (weak + high-weight schemas first).

## 3. Three-score dashboard (3 min)

1. **Tools → LSAT Speedrun → Dashboard**
2. Point out three separate scores:
   - **Memory** — FSRS recall with range (live after reviews)
   - **Performance** — latency-adjusted transfer from revlog
   - **Readiness** — projected 120–180 (abstains until 200 attempts + 50% coverage)
3. Show give-up rule: import fresh profile, dashboard says "No score" with reason.
4. Show schema-weighted queue preview at bottom.

## 4. CLI reports (2 min)

```bash
PYTHONPATH=out/pylib out/pyenv/bin/python speedrun/tools/memory_report.py --base .ankidata
PYTHONPATH=out/pylib out/pyenv/bin/python -m pytest pylib/tests/test_speedrun_*.py -q
just bench
```

## 5. Evaluation harnesses (2 min)

```bash
PYTHONPATH=out/pylib out/pyenv/bin/python -c "
from speedrun.eval.transfer_gap import transfer_gap_report
from speedrun.eval.interleaving_experiment import run_experiment
from speedrun.ai.card_checker import check_seed_deck
print(run_experiment().format_report())
print(check_seed_deck())
"
```

Show `docs/speedrun/RESULTS.md` for honest numbers.

## 6. iOS engine proof (1 min)

```bash
bash ios/run-tests.sh                  # XCFramework + rslib-ffi tests
```

Optional: open `ios/AnkiKit` in Xcode, run on simulator — build hash on screen.

## Talking points

- **Real Rust change**: schema-weighted queue in `rslib`, same on desktop + iOS.
- **Honesty rule**: scores abstain when data insufficient — never fake numbers.
- **AI off by default**: `SPEEDRUN_AI_OFF=1`; app still scores all three.
- **What's not done**: two-way sync, iOS review UI, human interleaving study.
