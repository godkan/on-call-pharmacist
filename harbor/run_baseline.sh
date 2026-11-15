#!/bin/bash
# Run a scripted policy through Harbor's oracle on one task, without editing the task.
#
#   bash harbor/run_baseline.sh t1-seed0 careful_pharmacist   # reference run, score 1.00
#   bash harbor/run_baseline.sh t1-seed0 do_nothing           # do-nothing baseline, score 0.00
#   bash harbor/run_baseline.sh t1-seed0 stop_early           # stop-early baseline, below the threshold
#
# Copies harbor/tasks/<task> to a temporary directory, sets [solution] env PHARMACY_POLICY there and
# runs `harbor run -a oracle` on the copy. Extra arguments are passed to harbor (e.g. -o jobs).
# Needs Docker and the harbor CLI (`uvx --from harbor harbor` is used if `harbor` is not installed).
set -euo pipefail
TASK=${1:?usage: run_baseline.sh <task, e.g. t1-seed0> <careful_pharmacist|do_nothing|stop_early>}
POLICY=${2:?usage: run_baseline.sh <task> <policy>}
shift 2
case "$POLICY" in careful_pharmacist|do_nothing|stop_early|reactive_pharmacist|sop_checklist|central_only) ;;
  *) echo "unknown policy $POLICY" >&2; exit 2 ;; esac
HERE=$(cd "$(dirname "$0")" && pwd)
SRC="$HERE/tasks/$TASK"
[ -d "$SRC" ] || { echo "no task $SRC" >&2; exit 2; }
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cp -R "$SRC" "$TMP/$TASK-$POLICY"
sed -i.bak "s/PHARMACY_POLICY = \"[a-z_]*\"/PHARMACY_POLICY = \"$POLICY\"/" "$TMP/$TASK-$POLICY/task.toml"
rm -f "$TMP/$TASK-$POLICY/task.toml.bak"
grep -q "PHARMACY_POLICY = \"$POLICY\"" "$TMP/$TASK-$POLICY/task.toml"
if command -v harbor >/dev/null 2>&1; then H=(harbor); else H=(uvx --from harbor harbor); fi
"${H[@]}" run -p "$TMP/$TASK-$POLICY" -a oracle --job-name "$TASK-$POLICY-$(date +%s)" "$@"
