#!/usr/bin/env python3
"""Read Claude Code's current plan-usage percentage non-interactively.

`claude -p "/usage" --output-format json` runs the /usage slash command in
print mode: this is a local status readout, not a model turn (total_cost_usd
is always 0, no tokens are spent), so it's safe to poll repeatedly. It starts
a fresh, throwaway session distinct from any interactive session, so it never
touches a terminal the user (or a parent orchestrator) already has open.

Note --bare must NOT be used here: it skips the account/plan lookup that
/usage needs and silently falls back to a session-cost-only report with no
percentages.

Output (stdout, JSON):
  {"ok": true, "checked_at": "...", "max_percent": 13,
   "session": {"percent": 8, "resets": "Sep 2, 7:29pm (Asia/Tokyo)"},
   "weeks": [{"label": "all models", "percent": 13, "resets": "..."},
             {"label": "Fable", "percent": 0, "resets": null}]}
  {"ok": false, "error": "..."}

Exit codes: 0 = usage read successfully (including a genuine 0%); 1 = could
not be determined (timeout, non-zero exit, unparseable output) -- never
conflate this with a 0% reading.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone

TIMEOUT_SECONDS = 20

_SESSION_RE = re.compile(r"Current session:\s*(\d+)%\s*used(?:\s*\S\s*resets\s*(.+))?")
_WEEK_RE = re.compile(
    r"Current week \(([^)]+)\):\s*(\d+)%\s*used(?:\s*\S\s*resets\s*(.+))?"
)


def parse_usage_text(text: str) -> dict:
    """Extract session/week percentages from /usage's rendered text.

    Raises ValueError if no "Current session" line is found (i.e. the output
    isn't the plan-usage report we expect -- e.g. the --bare fallback).
    """
    session = None
    weeks = []
    for line in text.splitlines():
        m = _SESSION_RE.search(line)
        if m:
            session = {"percent": int(m.group(1)), "resets": m.group(2)}
            continue
        m = _WEEK_RE.search(line)
        if m:
            weeks.append(
                {"label": m.group(1), "percent": int(m.group(2)), "resets": m.group(3)}
            )

    if session is None:
        raise ValueError("no 'Current session' line found in /usage output")

    percents = [session["percent"]] + [w["percent"] for w in weeks]
    return {
        "ok": True,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "max_percent": max(percents),
        "session": session,
        "weeks": weeks,
    }


def _decode_first_json(text: str) -> dict:
    """Decode the first JSON object in text, ignoring anything after it.

    claude runs SessionStart-type hooks in the background even in print
    mode; they occasionally flush stray output to the same stdout fd after
    the JSON result line, racily. Raises ValueError if no JSON object is
    found at all.
    """
    start = text.find("{")
    if start == -1:
        raise ValueError(f"no JSON object found in output: {text.strip()[:200]!r}")
    envelope, _end = json.JSONDecoder().raw_decode(text, start)
    return envelope


def fetch_usage() -> dict:
    try:
        proc = subprocess.run(
            ["claude", "-p", "/usage", "--output-format", "json"],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": f"claude did not respond within {TIMEOUT_SECONDS}s",
        }
    except FileNotFoundError:
        return {"ok": False, "error": "claude CLI not found on PATH"}

    if proc.returncode != 0:
        return {
            "ok": False,
            "error": f"claude exited {proc.returncode}: {proc.stderr.strip()[:500]}",
        }

    try:
        envelope = _decode_first_json(proc.stdout)
    except (ValueError, json.JSONDecodeError) as e:
        return {"ok": False, "error": f"could not parse claude's JSON output: {e}"}

    result_text = envelope.get("result", "")
    try:
        return parse_usage_text(result_text)
    except ValueError as e:
        return {"ok": False, "error": str(e)}


def main() -> int:
    usage = fetch_usage()
    print(json.dumps(usage, ensure_ascii=False))
    return 0 if usage.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
