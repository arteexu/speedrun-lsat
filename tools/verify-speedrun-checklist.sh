#!/usr/bin/env bash
# One command that produces the machine-checkable proof for the Speedrun LSAT
# grading checklist: commit hash + every automated test the checklist asks for.
#
# The human-only proofs (screen recordings of the clean build, the clean-machine
# install, and a phone review session) are listed at the end -- this script
# tells you exactly what to record and the command each recording should show.
#
# Usage:
#   tools/verify-speedrun-checklist.sh            # desktop + engine checks
#   RUN_IOS=1 tools/verify-speedrun-checklist.sh  # also run the iOS simulator tests
set -uo pipefail
cd "$(dirname "$0")/.."

PY="PYTHONPATH=out/pylib out/pyenv/bin/python"
pass=0; fail=0
run() {
  local name="$1"; shift
  echo "──▶ $name"
  if eval "$@"; then echo "   ✅ PASS: $name"; pass=$((pass+1));
  else echo "   ❌ FAIL: $name"; fail=$((fail+1)); fi
  echo
}

echo "=================================================================="
echo " Speedrun LSAT — checklist verification"
echo " commit:  $(git rev-parse HEAD)"
echo " branch:  $(git rev-parse --abbrev-ref HEAD)"
echo " date:    $(date)"
echo "=================================================================="
echo

run "Rust change: 3+ unit tests for the schema-weighted queue" \
    "cargo test -p anki schema_weighted 2>&1 | tail -8"

run "Rust FFI: open the exam deck + schema-weighted queue over the C bridge" \
    "cargo test -p rslib-ffi 2>&1 | tail -8"

run "Python→Rust: FFI test calling the schema-weighted queue" \
    "$PY -m pytest pylib/tests/test_schema_weighted_queue.py -q 2>&1 | tail -4"

run "Review loop on the exam deck (load → schema queue → answer → state change)" \
    "$PY -m pytest pylib/tests/test_speedrun_review_session.py -q 2>&1 | tail -4"

run "Memory model: honest score (range + give-up) + guardrail" \
    "$PY -m pytest pylib/tests/test_speedrun_memory.py pylib/tests/test_speedrun_guardrail.py -q 2>&1 | tail -4"

run "Installer: speedrun package is installable + data bundled" \
    "$PY -m pytest pylib/tests/test_speedrun_packaging.py -q 2>&1 | tail -4"

run "Full Speedrun Python suite" \
    "$PY -m pytest pylib/tests/test_speedrun_*.py -q 2>&1 | tail -6"

if [[ "${RUN_IOS:-0}" == "1" ]]; then
  run "iOS (simulator): load exam deck + review pass on the shared engine" \
      "cd ios/AnkiKit && xcodebuild test -scheme AnkiKit \
        -destination 'platform=iOS Simulator,name=iPhone 17,OS=26.5' 2>&1 | tail -14; cd -"
fi

echo "=================================================================="
echo " Automated result: $pass passed, $fail failed"
echo "=================================================================="
cat <<'EOF'

Human-recorded proofs still to capture (hit record, run the command):
  1. Clean-build recording:   ./run   (from a fresh `git clean -xdf` checkout)
  2. Test-results recording:  tools/verify-speedrun-checklist.sh   (this script)
  3. Clean-machine install:   see docs/speedrun/INSTALL.md (Path A wheels in a
                              fresh venv on a machine with no source checkout)
  4. Phone review session:    open ios/App/SpeedrunLSAT.xcodeproj in Xcode, Run
                              on a simulator/device, tap "Study the exam deck".
                              (xcodegen generate in ios/App first if needed.)

Commit hash to cite: run `git rev-parse HEAD`.
EOF
[[ "$fail" == "0" ]]
