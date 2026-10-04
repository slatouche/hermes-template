#!/bin/bash
# The one test command every bot runs. Prints one PASS line, or only what failed (the tail of the output),
# so test runs stay small in a bot's context. Exit code = the suite's.
#
#   scripts/run-tests.sh [extra args passed to the test command]
#
# The project's own command goes in TEST_CMD below. Left empty, it guesses from the repo
# (pytest, unittest, npm test, cargo test, go test, make test). Set it once the project's test command is known.
TEST_CMD=""

cd "$(dirname "$0")/.." || exit 2
if [ -z "$TEST_CMD" ]; then
  if [ -f pytest.ini ] || [ -f conftest.py ] || grep -qs '\[tool.pytest' pyproject.toml; then
    TEST_CMD="python3 -m pytest -q"
  elif [ -d tests ] && ls tests/test_*.py >/dev/null 2>&1; then
    TEST_CMD="/usr/bin/python3 -m unittest discover -s tests"
  elif [ -f package.json ] && grep -q '"test"' package.json; then TEST_CMD="npm test --silent"
  elif [ -f Cargo.toml ]; then TEST_CMD="cargo test -q"
  elif [ -f go.mod ]; then TEST_CMD="go test ./..."
  elif grep -qs '^test:' Makefile; then TEST_CMD="make -s test"
  else echo "run-tests: no test command found; set TEST_CMD in scripts/run-tests.sh"; exit 2; fi
fi
OUT="$(mktemp)"; trap 'rm -f "$OUT"' EXIT
START=$(date +%s)
bash -c "$TEST_CMD $*" >"$OUT" 2>&1; RC=$?
SECS=$(( $(date +%s) - START ))
if [ $RC -eq 0 ]; then
  SUMMARY="$(grep -E '^(Ran [0-9]+ tests?|[0-9]+ passed|test result:|Tests: |ok )' "$OUT" | tail -1)"
  echo "PASS ($SECS s): $TEST_CMD${SUMMARY:+ — $SUMMARY}"
else
  echo "FAIL (exit $RC, $SECS s): $TEST_CMD"
  grep -nE '(FAIL|ERROR|Error|error\[|AssertionError|Traceback|failed|panicked)' "$OUT" | head -30
  echo "--- last 40 lines ---"
  tail -40 "$OUT"
fi
exit $RC
