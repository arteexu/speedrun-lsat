set windows-shell := ["pwsh", "-NoLogo", "-NoProfileLoadTime", "-Command"]

mod release

# Show available commands
default:
    @just --list

# Build the project
build:
    {{ ninja }} pylib qt

# Build and run Anki in development mode
run *args:
    {{ run_script }} {{ args }}

# Build and run Anki in optimized (release) mode
run-optimized *args:
    {{ if os() == "windows" { "$env:RELEASE='1'; .\\run.bat" } else { "RELEASE=1 ./run" } }} {{ args }}

# Watch web sources and rebuild/reload Anki's web stack on change (macOS/Linux)
web-watch:
    ./tools/web-watch

# Rebuild and reload Anki's web stack without restarting (macOS/Linux)
rebuild-web:
    ./tools/rebuild-web

# Build wheels (needed for some platforms)
wheels:
    {{ ninja }} wheels

# Build and run all checks (lint + test) - lets ninja handle dependencies
check:
    {{ ninja }} pylib qt check

# Run all tests (Rust, Python, TypeScript). Pass --coverage to enforce coverage, and --html to include HTML reports.
[arg("coverage", long="coverage", value="--coverage")]
[arg("html", long="html", value="--html")]
test coverage='' html='':
    just {{ if coverage == "--coverage" { "coverage " + html } else { "_test" } }}

# Run coverage for all test stacks. Pass --html to also generate HTML reports.
[arg("html", long="html", value="--html")]
coverage html='':
    just _coverage-rust {{ html }}
    just _coverage-py {{ html }}
    just _coverage-ts {{ html }}

# Run Rust tests. Pass --coverage to enforce Rust coverage, and --html to include an HTML report.
[arg("coverage", long="coverage", value="--coverage")]
[arg("html", long="html", value="--html")]
test-rust coverage='' html='':
    just {{ if coverage == "--coverage" { "_coverage-rust " + html } else { "_test-rust" } }}

# Run Python tests (pylib + qt). Pass --coverage to enforce coverage, and --html to include HTML reports.
[arg("coverage", long="coverage", value="--coverage")]
[arg("html", long="html", value="--html")]
test-py coverage='' html='':
    just {{ if coverage == "--coverage" { "_coverage-py " + html } else { "_test-py" } }}

# Run TypeScript/Svelte Vitest tests. Pass --coverage to enforce coverage, and --html to include an HTML report.
[arg("coverage", long="coverage", value="--coverage")]
[arg("html", long="html", value="--html")]
test-ts coverage='' html='':
    just {{ if coverage == "--coverage" { "_coverage-ts " + html } else { "_test-ts" } }}

# Run Playwright end-to-end tests. Pass --ui to open the interactive UI.
[arg("ui", long="ui", value="--ui")]
test-e2e ui='': _install-playwright-browsers
    {{ ninja }} pyenv ts:generated pylib qt
    {{ playwright_env }} {{ yarn }} test:e2e {{ ui }}

[private]
_test:
    {{ ninja }} check:rust_test check:pytest check:vitest

[private]
_test-rust:
    {{ ninja }} check:rust_test

[private]
_test-py:
    {{ ninja }} check:pytest

[private]
_test-ts:
    {{ ninja }} check:vitest

[private]
_coverage-rust html='':
    {{ if os_family() == "windows" { "tools\\coverage\\coverage-rust" } else { "tools/coverage/coverage-rust" } }} {{ html }}

[private]
_coverage-py html='':
    {{ ninja }} pylib qt
    just _coverage-py-pylib {{ html }}
    just _coverage-py-qt {{ html }}

[private]
_coverage-py-pylib html='':
    {{ if os_family() == "windows" { "tools\\coverage\\coverage-py" } else { "tools/coverage/coverage-py" } }} pylib {{ html }}

[private]
_coverage-py-qt html='':
    {{ if os_family() == "windows" { "tools\\coverage\\coverage-py" } else { "tools/coverage/coverage-py" } }} qt {{ html }}

[private]
_coverage-ts html='':
    {{ ninja }} node_modules ts:generated
    {{ if os_family() == "windows" { "tools\\coverage\\coverage-ts" } else { "tools/coverage/coverage-ts" } }} {{ html }}

[private]
_install-playwright-browsers:
    {{ ninja }} node_modules
    {{ playwright_env }} {{ yarn }} playwright install chromium

# Check formatting (fast, no build needed)
fmt:
    {{ ninja }} check:format

# Fix formatting
fix-fmt:
    {{ ninja }} format

# Run linting and type checking (requires build outputs)
lint:
    {{ ninja }} \
        check:clippy \
        check:mypy \
        check:ruff \
        check:eslint \
        check:svelte \
        check:typescript

# Fix auto-fixable lint issues (ruff + eslint)
fix-lint:
    {{ ninja }} fix:ruff fix:eslint

# Run minilints (copyright, contributors, licenses)
minilints:
    {{ ninja }} check:minilints

# Fix minilints (update licenses.json)
fix-minilints:
    {{ ninja }} fix:minilints

# Sync translation files
ftl-sync:
    {{ ninja }} ftl-sync

# Deprecate translation strings
ftl-deprecate:
    {{ ninja }} ftl-deprecate

# Build documentation site
docs:
    {{ uv }} run --group docs sphinx-build -b html docs out/docs/html
    @echo "Docs built at out/docs/html/index.html"

# Build and serve documentation site
docs-serve:
    {{ uv }} run --group docs sphinx-autobuild docs out/docs/html --host 127.0.0.1 --port 8000

# Build Rust API docs
docs-rust:
    cargo doc --open

# Dispatch CI workflow on a given branch or tag
ci branch:
    gh workflow run ci.yml --ref {{ branch }}

# Run Complexipy in regression-only mode
complexipy-diff:
    {{ ninja }} check:complexipy-diff

# Remove build outputs from out/ (pass keep-env to keep node_modules/pyenv); macOS/Linux
clean *args:
    ./tools/clean {{ args }}

# Speedrun LSAT benchmarks (p50/p95/worst for key scoring actions)
bench:
    PYTHONPATH=out/pylib {{ if os() == "windows" { "out\\pyenv\\Scripts\\python" } else { "out/pyenv/bin/python" } }} speedrun/tools/bench.py

# Speedrun LSAT — run every reproducible PRD test/eval (7a–7h + rest) in sequence with labeled headers (macOS/Linux)
demo-tests:
    #!/usr/bin/env bash
    set -uo pipefail
    cd "{{ justfile_directory() }}"
    export PYTHONPATH="out/pylib:$PWD"
    unset SPEEDRUN_AI_SETTINGS_PATH || true
    PY="out/pyenv/bin/python"
    n=0
    step() { n=$((n+1)); printf '\n\033[1;36m========== [%02d] %s ==========\033[0m\n' "$n" "$1"; }
    ok()   { printf '\033[1;32m✓ %s\033[0m\n' "$1"; }
    warn() { printf '\033[1;33m! %s\033[0m\n' "$1"; }

    step "7a · Rust schema-weighted queue unit tests"
    cargo test -p anki schema_weighted 2>&1 | tail -6 || warn "cargo schema_weighted failed"
    step "7a · Rust three-score / give-up math tests"
    cargo test -p anki speedrun_scores 2>&1 | tail -4 || warn "cargo speedrun_scores failed"
    step "7a · Python-over-RPC test (calls the Rust queue from Python)"
    $PY -m pytest pylib/tests/test_schema_weighted_queue.py -q 2>&1 | tail -4 || warn "rpc test failed"

    step "7h · One-command 50k benchmark (p50/p95/worst vs §18)"
    $PY -m speedrun.tools.bench --target 50000 2>&1 | tail -18 || warn "bench failed"

    step "7b · Two-way sync (10+10, none lost/double, conflict winner)"
    $PY speedrun/tools/sync_test.py 2>&1 | tail -14 || warn "sync_test failed"

    step "7c · Coverage map + give-up abstain"
    $PY -m pytest pylib/tests/test_speedrun_readiness.py pylib/tests/test_speedrun_guardrail.py -q -k "coverage or abstain or section or give_up" 2>&1 | tail -5 || warn "coverage/give-up tests failed"

    step "7d · Paraphrase / transfer gap (recall vs reworded)"
    $PY -m pytest pylib/tests/test_speedrun_transfer.py -q 2>&1 | tail -5 || warn "transfer tests failed"

    step "7e · Leakage check — clean run"
    $PY speedrun/tools/speedrun_cli.py leakage-check 2>&1 | tail -6 || warn "leakage-check failed"
    step "7e · Leakage check — gate bites (expect non-zero exit)"
    $PY speedrun/tools/speedrun_cli.py leakage-check --threshold 0.0 2>&1 | tail -4 && warn "expected the gate to bite" || ok "gate correctly rejected (non-zero exit)"

    step "7f · AI card check (3 counts vs pre-set cutoff; blocks failures)"
    if [ -f .ankidata/speedrun_ai_settings.json ]; then
        SPEEDRUN_AI_SETTINGS_PATH="$PWD/.ankidata/speedrun_ai_settings.json" $PY -m speedrun.eval.card_check_run 2>&1 | tail -16 || warn "card_check_run failed"
    else
        warn "7f needs AI settings at .ankidata/speedrun_ai_settings.json for live generation; offline path generates 0 cards"
    fi

    step "7g · Crash / durability (≥20 kill-mid-review cycles, zero corruption)"
    $PY -m speedrun.tools.crash_test 2>&1 | tail -3 || warn "crash_test failed"
    step "7g · Offline / AI-off still scores"
    $PY -m speedrun.tools.offline_test 2>&1 | tail -6 || warn "offline_test failed"

    step "AI beats baseline · deterministic grounded eval (no key)"
    $PY -m speedrun.eval.grounding_eval 2>&1 | tail -10 || warn "grounding_eval failed"

    step "Interleaving 3-build experiment (§15; seeded, honest null)"
    $PY -m speedrun.eval.interleaving_experiment 2>&1 | tail -10 || warn "interleaving failed"

    step "Memory calibration (held-out; §10.1)"
    $PY -m pytest pylib/tests/test_speedrun_calibration.py -q 2>&1 | tail -4 || warn "calibration tests failed"

    step "Full deterministic suite"
    $PY -m pytest pylib/tests/ -k "speedrun or schema" -q 2>&1 | tail -4 || warn "suite has failures (2 expected if a demo profile is seeded — config.json relaxed to 0.73)"

    printf '\n\033[1;36m========== demo-tests complete ==========\033[0m\n'
    warn "If a demo profile is seeded, the full suite shows 2 known config-relax failures; run 'seed_demo_stats.py --clear' or 'git checkout HEAD -- speedrun/config.json' for the clean 402 passed."

# Helpers to get the right commands for the platform

ninja := if os() == "windows" { "tools\\ninja" } else { "./ninja" }
run_script := if os() == "windows" { ".\\run.bat" } else { "./run" }
playwright_env := if os() == "windows" { "set PLAYWRIGHT_BROWSERS_PATH=out\\playwright-browsers&&" } else { "PLAYWRIGHT_BROWSERS_PATH=out/playwright-browsers" }
yarn := if os() == "windows" { "out\\extracted\\node\\yarn.cmd" } else { "out/extracted/node/bin/yarn" }
uv := env("UV_BINARY", if os() == "windows" { "out\\extracted\\uv\\uv" } else { "out/extracted/uv/uv" })
export UV_PROJECT_ENVIRONMENT := if os() == "windows" { "out\\pyenv" } else { "out/pyenv" }
