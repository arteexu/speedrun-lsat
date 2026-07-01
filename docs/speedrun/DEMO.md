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
3. Confirm 41 cards imported into "LSAT Speedrun" (auto-backup of collection first).

## 2. Study session (2 min)

1. **Tools → LSAT Speedrun → Study now** (or select the LSAT Speedrun deck).
2. Study 5–10 cards — post-review toast shows schema, latency vs budget, FSRS R.
3. Optional: enable **Show reviewer sidebar** for session stats.
4. **Schema drill (weakest)** queues cards from your weakest N schemas.

## 3. Three-score dashboard (3 min)

1. **Tools → LSAT Speedrun → Dashboard** (Ctrl+Shift+L)
2. Point out:
   - **Daily goal** — progress bar + streak from revlog
   - **Memory / Performance / Readiness** — each with range + give-up rule
   - **Progress timeline**, **mastery map**, **wrong-answer patterns**, **latency histogram**
   - **Readiness trajectory** (abstains until enough data)
3. Menu badge shows live M · P · R summary.
4. Fresh profile: all scores abstain with honest reasons.

## 4. CLI suite (2 min)

```bash
PYTHONPATH=out/pylib out/pyenv/bin/python speedrun/tools/speedrun_cli.py health --base .ankidata
PYTHONPATH=out/pylib out/pyenv/bin/python speedrun/tools/speedrun_cli.py drill --base .ankidata
PYTHONPATH=out/pylib out/pyenv/bin/python speedrun/tools/speedrun_cli.py export --base .ankidata --out /tmp/speedrun.html
PYTHONPATH=out/pylib out/pyenv/bin/python -m pytest pylib/tests/test_speedrun_*.py -q
```

Subcommands: `dashboard`, `drill`, `export`, `coverage`, `calibrate`, `transfer-gap`, `health`, `gaps`, `pretest`.

## 5. Config & settings

- Edit `speedrun/config.json` — latency budgets, daily goal, interleaving toggle, section filter.
- **Tools → LSAT Speedrun → Settings** shows current config.
- Schema documented in `docs/speedrun/CONFIG_SCHEMA.md`.

## 6. Evaluation harnesses (2 min)

```bash
PYTHONPATH=out/pylib out/pyenv/bin/python -c "
from speedrun.eval.transfer_gap import transfer_gap_report
from speedrun.eval.interleaving_experiment import run_experiment
print(run_experiment().format_report())
"
```

Show `docs/speedrun/RESULTS.md` for honest numbers.

## 7. iOS engine proof (1 min)

```bash
bash ios/run-tests.sh                  # XCFramework + rslib-ffi tests
```

Open `ios/App/ContentView.swift` in Xcode — daily goal, three scores, weakest schemas, study button.

## Talking points

- **Real Rust change**: schema-weighted queue in `rslib`, same on desktop + iOS.
- **Honesty rule**: scores abstain when data insufficient — never fake numbers.
- **41-card seed deck** with paraphrase fields for transfer-gap testing.
- **AI off by default**; app still scores all three.
- **What's not done**: two-way sync, full iOS review UI, human interleaving study.
