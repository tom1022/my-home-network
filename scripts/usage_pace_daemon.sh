#!/usr/bin/env bash
# Runs usage_pace.py on a fixed interval, atomically overwriting a single
# status file each time (never appends -- readers must always see exactly
# one JSON line, the latest). Self-terminates after MAX_ITERATIONS so a
# forgotten daemon doesn't run forever.
#
# Also maintains, alongside STATUS_FILE:
#   <status>_history.json  -- session sample history (for rate smoothing)
#   usage_pace_lanes.txt   -- current parallel-lane count, written by the
#                             controller (e.g. `echo 4 > .../usage_pace_lanes.txt`)
#                             to drive the "recommended lanes" field.
#
# Usage: usage_pace_daemon.sh <status_file> <pid_file> [interval_seconds] [max_iterations]
set -euo pipefail

STATUS_FILE="$1"
PID_FILE="$2"
INTERVAL="${3:-300}"
MAX_ITERATIONS="${4:-288}"  # 288 * 5min = 24h

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATUS_DIR="$(dirname "$STATUS_FILE")"
HISTORY_FILE="${STATUS_FILE%.json}_history.json"
LANES_FILE="$STATUS_DIR/usage_pace_lanes.txt"

mkdir -p "$STATUS_DIR"
echo $$ > "$PID_FILE"

i=0
while [ "$i" -lt "$MAX_ITERATIONS" ]; do
  tmp="${STATUS_FILE}.tmp.$$"
  if python3 "$SCRIPT_DIR/usage_pace.py" --history-file "$HISTORY_FILE" --lanes-file "$LANES_FILE" > "$tmp" 2>/dev/null; then
    mv -f "$tmp" "$STATUS_FILE"
  else
    rm -f "$tmp"
  fi
  i=$((i + 1))
  [ "$i" -lt "$MAX_ITERATIONS" ] && sleep "$INTERVAL"
done

rm -f "$PID_FILE"
