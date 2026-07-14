#!/usr/bin/env bash
# Smoke test for fieldscore: score the bundled invoice example end to end,
# check every CLI subcommand, exit codes, and the --fail-under gate.
# Self-contained: pure stdlib, no network, idempotent (works from a clean tree).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
if [ -x "$ROOT/.venv/bin/python" ]; then
  PYTHON="$ROOT/.venv/bin/python"
fi

# The package has zero runtime dependencies, so running from src/ needs no install.
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/fieldscore-smoke.XXXXXX")"
trap 'rm -rf "$WORKDIR"' EXIT

fail() { echo "SMOKE FAIL: $1" >&2; exit 1; }

GOLD="$ROOT/examples/gold.jsonl"
PRED="$ROOT/examples/pred.jsonl"
CONFIG="$ROOT/examples/fields.json"

echo "[smoke] python: $("$PYTHON" --version 2>&1)"

# 1. score: the default table must contain per-field rows and both averages.
score_out="$("$PYTHON" -m fieldscore score "$GOLD" "$PRED" --config "$CONFIG")" \
  || fail "score exited non-zero"
echo "$score_out" | sed 's/^/[score] /'
echo "$score_out" | grep -q "micro avg" || fail "table missing micro avg"
echo "$score_out" | grep -q "macro avg" || fail "table missing macro avg"
echo "$score_out" | grep -Eq "^total +money +5 +5 +4" \
  || fail "total row should be 4 of 5 correct (the ¥5,000 error must count)"
echo "$score_out" | grep -Eq "^date +date +5 +5 +5" \
  || fail "date row should be 5 of 5 correct across formats"

# 2. score --format json: machine output carries the same numbers.
"$PYTHON" -m fieldscore score "$GOLD" "$PRED" --config "$CONFIG" \
  --format json > "$WORKDIR/report.json" || fail "json score exited non-zero"
"$PYTHON" - "$WORKDIR/report.json" <<'PY' || fail "json report numbers are wrong"
import json, sys
payload = json.load(open(sys.argv[1]))
assert payload["fields"]["total"]["correct"] == 4, payload["fields"]["total"]
assert payload["fields"]["date"]["f1"] == 1.0
assert payload["records"]["scored"] == 5
assert 0.85 < payload["micro"]["f1"] < 1.0
PY

# 3. --fail-under: a high bar must trip exit code 1, a low bar must pass.
set +e
"$PYTHON" -m fieldscore score "$GOLD" "$PRED" --config "$CONFIG" \
  --fail-under 0.99 >/dev/null 2>"$WORKDIR/gate.err"
gate_rc=$?
set -e
[ "$gate_rc" -eq 1 ] || fail "--fail-under 0.99 should exit 1, got $gate_rc"
grep -q "FAIL" "$WORKDIR/gate.err" || fail "gate failure not reported on stderr"
"$PYTHON" -m fieldscore score "$GOLD" "$PRED" --config "$CONFIG" \
  --fail-under 0.5 >/dev/null || fail "--fail-under 0.5 should pass"

# 4. explain: mismatches are grouped by record with the judging comparator.
explain_out="$("$PYTHON" -m fieldscore explain "$GOLD" "$PRED" --config "$CONFIG")"
echo "$explain_out" | sed 's/^/[explain] /'
echo "$explain_out" | grep -q "record inv-004" || fail "explain missing record inv-004"
echo "$explain_out" | grep -q "spurious" || fail "explain missing the spurious tag"
echo "$explain_out" | grep -q "\[money\]" || fail "explain missing comparator type"

# 5. infer: the generated config is valid JSON with sensible types.
"$PYTHON" -m fieldscore infer "$GOLD" --id-field invoice_id \
  > "$WORKDIR/inferred.json" || fail "infer exited non-zero"
"$PYTHON" - "$WORKDIR/inferred.json" <<'PY' || fail "inferred config is wrong"
import json, sys
config = json.load(open(sys.argv[1]))
assert config["id_field"] == "invoice_id"
assert config["fields"]["date"]["type"] == "date"
assert config["fields"]["total"]["type"] == "money"
assert config["fields"]["line_items[].sku"]["type"] == "string"
PY

# 6. The inferred config must itself be usable for scoring.
"$PYTHON" -m fieldscore score "$GOLD" "$PRED" --config "$WORKDIR/inferred.json" \
  --id-field invoice_id >/dev/null || fail "scoring with inferred config failed"

# 7. --version agrees with the package version; bad input exits 2.
version_out="$("$PYTHON" -m fieldscore --version)"
pkg_version="$("$PYTHON" -c 'import fieldscore; print(fieldscore.__version__)')"
[ "$version_out" = "fieldscore $pkg_version" ] \
  || fail "--version mismatch: '$version_out' vs package '$pkg_version'"
set +e
"$PYTHON" -m fieldscore score "$GOLD" "$WORKDIR/does-not-exist.jsonl" \
  >/dev/null 2>&1
bad_rc=$?
set -e
[ "$bad_rc" -eq 2 ] || fail "missing input should exit 2, got $bad_rc"

echo "SMOKE OK"
