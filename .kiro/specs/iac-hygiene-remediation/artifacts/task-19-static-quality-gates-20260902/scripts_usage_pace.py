#!/usr/bin/env python3
"""Compute Claude Code usage pace against an "80% right at session reset" target.

Policy: the 5-hour session window is the thing that actually stops work (429
at 100%). 80% is a safety margin below that hard cap, not a target to
maximize -- the ideal trajectory spends the session window evenly and lands
near 80% right as it resets. Too fast and work stalls before reset; too slow
and throughput is left on the table. The weekly window is informational only
(it recovers on its own as long as sessions are paced correctly) and no
longer drives the up/down decision.

Output (stdout, single-line JSON):
  {"ok": true, "checked_at": "...", "action": "hold",
   "week": {...}, "session": {..., "warming_up": false, "hours_to_80": 2.3,
             "will_stall_before_reset": true},
   "lanes": {"current": 4, "recommended": 3},
   "usage": {<raw check_claude_usage.py output>}}
  {"ok": false, "error": "..."}

Exit codes: 0 = pace computed; 1 = could not be determined (upstream fetch
failed, or a reset string didn't parse -- never silently treated as 0).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TIMEOUT_SECONDS = 25
TARGET_PERCENT = 80.0
WEEK_HOURS = 168.0
SESSION_HOURS = 5.0
TOKYO = ZoneInfo("Asia/Tokyo")

# Action thresholds, in target-line percentage points (rationale in the report,
# not restated here -- it's a judgment call, not a hidden constraint).
UP_THRESHOLD = -5.0
DOWN_THRESHOLD = 5.0

# Below this much elapsed session time, or without enough history to fit a
# trend line, the rate is noise (a single %-point at 10min elapsed swings
# pt/h wildly) -- force "hold" rather than act on it.
WARMUP_HOURS = 0.2
MIN_HISTORY_POINTS = 3
MIN_HISTORY_SPAN_HOURS = 0.15
MAX_HISTORY_SAMPLES = 100

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_RESET_RE = re.compile(
    r"^([A-Za-z]{3,})\s+(\d{1,2}),\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*\(Asia/Tokyo\)$",
    re.IGNORECASE,
)


def parse_reset(reset_str: str, now: datetime) -> datetime:
    """Parse a "Sep 5, 3am (Asia/Tokyo)" reset string into an absolute UTC
    datetime, resolving the missing year to the nearest future occurrence
    relative to `now` (must be timezone-aware).

    Raises ValueError on any unrecognized format -- callers must not
    swallow this into a default of 0.
    """
    if not reset_str:
        raise ValueError("reset string is empty/None")
    m = _RESET_RE.match(reset_str.strip())
    if not m:
        raise ValueError(f"unrecognized reset format: {reset_str!r}")
    mon_str, day_str, hour_str, minute_str, ampm = m.groups()
    month = _MONTHS.get(mon_str[:3].lower())
    if month is None:
        raise ValueError(f"unrecognized month in reset string: {reset_str!r}")
    hour = int(hour_str) % 12
    if ampm.lower() == "pm":
        hour += 12

    now_tokyo = now.astimezone(TOKYO)
    candidate = now_tokyo.replace(
        month=month, day=int(day_str), hour=hour,
        minute=int(minute_str) if minute_str else 0,
        second=0, microsecond=0,
    )
    if candidate <= now_tokyo:
        candidate = candidate.replace(year=candidate.year + 1)
    return candidate.astimezone(timezone.utc)


def linear_regression_slope(points: list[tuple[float, float]]) -> float | None:
    """Least-squares slope of (x, y) points, or None if underdetermined
    (fewer than 2 points, or all x equal)."""
    n = len(points)
    if n < 2:
        return None
    sum_x = sum(p[0] for p in points)
    sum_y = sum(p[1] for p in points)
    sum_xy = sum(p[0] * p[1] for p in points)
    sum_xx = sum(p[0] * p[0] for p in points)
    denom = n * sum_xx - sum_x * sum_x
    if abs(denom) < 1e-9:
        return None
    return (n * sum_xy - sum_x * sum_y) / denom


ROLLOVER_TOLERANCE_HOURS = 0.1  # 6 minutes

def update_history(history: list[dict], sample: dict, max_keep: int = MAX_HISTORY_SAMPLES) -> list[dict]:
    """Append `sample` ({"ts", "elapsed_hours", "percent", "reset"}) to
    `history`, dropping everything older than the current session once a
    rollover is detected.

    Rollover is detected via a drop in elapsed_hours, NOT via the raw
    `reset` string changing: /usage's displayed reset time jitters by
    about a minute between polls (it re-renders "resets in Xh Ym" each
    call, rounded), so comparing strings treats nearly every tick as a
    new session and wipes history constantly. elapsed_hours only moves
    backward across a real reset.
    """
    if history and sample["elapsed_hours"] < history[-1]["elapsed_hours"] - ROLLOVER_TOLERANCE_HOURS:
        history = []
    return (history + [sample])[-max_keep:]


def smoothed_session_rate(
    history: list[dict],
    min_points: int = MIN_HISTORY_POINTS,
    min_span_hours: float = MIN_HISTORY_SPAN_HOURS,
) -> tuple[float | None, int, float]:
    """Regression-smoothed pt/h slope over the current session's samples.

    Returns (rate_or_None, n_points, span_hours). None when there isn't
    enough history yet to trust a trend over single-sample noise.
    """
    points = [(h["elapsed_hours"], h["percent"]) for h in history]
    n = len(points)
    span = (max(p[0] for p in points) - min(p[0] for p in points)) if n >= 2 else 0.0
    if n < min_points or span < min_span_hours:
        return None, n, span
    return linear_regression_slope(points), n, span


def compute_window_pace(
    actual_percent: float, reset_dt: datetime, now: datetime, window_hours: float,
    rate_override: float | None = None,
) -> dict:
    """Pace metrics for one usage window (weekly or session).

    `rate_override`, when given, replaces the raw single-sample current_rate
    (e.g. a history-smoothed slope) for the current_rate/required_rate/
    speedup/hours_to_80 calculations -- target_percent and delta don't
    depend on rate and are always computed from the raw elapsed ratio.
    """
    window_start = reset_dt - timedelta(hours=window_hours)
    elapsed_h = (now - window_start).total_seconds() / 3600.0
    remaining_h = (reset_dt - now).total_seconds() / 3600.0
    elapsed_ratio = elapsed_h / window_hours

    target_percent = TARGET_PERCENT * elapsed_ratio
    delta = actual_percent - target_percent

    if rate_override is not None:
        current_rate = rate_override
    else:
        current_rate = actual_percent / elapsed_h if elapsed_h > 0 else None
    required_rate = (TARGET_PERCENT - actual_percent) / remaining_h if remaining_h > 0 else None
    speedup = required_rate / current_rate if current_rate else None

    hours_to_80 = None
    if current_rate is not None and current_rate > 0:
        hours_to_80 = (TARGET_PERCENT - actual_percent) / current_rate
    will_stall_before_reset = hours_to_80 is not None and hours_to_80 < remaining_h

    return {
        "elapsed_hours": round(elapsed_h, 2),
        "remaining_hours": round(remaining_h, 2),
        "elapsed_ratio": round(elapsed_ratio, 4),
        "actual_percent": actual_percent,
        "target_percent": round(target_percent, 2),
        "delta": round(delta, 2),
        "current_rate_pt_per_h": round(current_rate, 4) if current_rate is not None else None,
        "required_rate_pt_per_h": round(required_rate, 4) if required_rate is not None else None,
        "speedup": round(speedup, 3) if speedup is not None else None,
        "hours_to_80": round(hours_to_80, 2) if hours_to_80 is not None else None,
        "will_stall_before_reset": will_stall_before_reset,
    }


def decide_action(session: dict, warming_up: bool) -> str:
    """up/hold/down driven by the session window alone. The weekly window is
    reference-only: a lagging week is not license to exceed the session's
    own 80%-at-reset trajectory (that pace is exactly what recovers the
    week over time)."""
    if warming_up:
        return "hold"
    if session["delta"] > DOWN_THRESHOLD:
        return "down"
    if session["delta"] < UP_THRESHOLD:
        return "up"
    return "hold"


def recommend_lanes(current_lanes: int | None, speedup: float | None) -> int | None:
    """Scale current parallelism by the same ratio the rate needs to move
    (required_rate / current_rate), rounded and floored at 1 lane."""
    if current_lanes is None or speedup is None:
        return None
    return max(1, round(current_lanes * speedup))


def compute_pace(
    usage: dict, now: datetime,
    history: list[dict] | None = None, current_lanes: int | None = None,
) -> tuple[dict, list[dict]]:
    """Pure pace computation. Returns (result, updated_history) -- the
    caller is responsible for persisting updated_history if it wants
    smoothing to work across runs."""
    history = history or []

    if not usage.get("ok"):
        return {"ok": False, "error": usage.get("error", "upstream usage fetch failed")}, history

    weeks = {w["label"]: w for w in usage.get("weeks", [])}
    week_raw = weeks.get("all models")
    if week_raw is None:
        return {"ok": False, "error": "no 'all models' entry in weeks"}, history
    session_raw = usage.get("session")
    if session_raw is None:
        return {"ok": False, "error": "no session entry in usage"}, history

    try:
        week_reset = parse_reset(week_raw["resets"], now)
        session_reset = parse_reset(session_raw["resets"], now)
    except ValueError as e:
        return {"ok": False, "error": f"reset parse failure: {e}"}, history

    session_window_start = session_reset - timedelta(hours=SESSION_HOURS)
    session_elapsed_h = (now - session_window_start).total_seconds() / 3600.0

    sample = {
        "ts": now.isoformat(timespec="seconds"),
        "elapsed_hours": round(session_elapsed_h, 4),
        "percent": session_raw["percent"],
        "reset": session_raw["resets"],
    }
    new_history = update_history(history, sample)
    rate, n_points, span_hours = smoothed_session_rate(new_history)

    warming_up = session_elapsed_h < WARMUP_HOURS or rate is None

    session = compute_window_pace(session_raw["percent"], session_reset, now, SESSION_HOURS, rate_override=rate)
    session["resets"] = session_raw["resets"]
    session["warming_up"] = warming_up
    session["rate_smoothed"] = rate is not None
    session["history_points"] = n_points
    session["history_span_hours"] = round(span_hours, 2)

    week = compute_window_pace(week_raw["percent"], week_reset, now, WEEK_HOURS)
    week["resets"] = week_raw["resets"]

    action = decide_action(session, warming_up)
    lanes = {"current": current_lanes, "recommended": recommend_lanes(current_lanes, session["speedup"])}

    result = {
        "ok": True,
        "checked_at": now.isoformat(timespec="seconds"),
        "action": action,
        "week": week,
        "session": session,
        "lanes": lanes,
        "usage": usage,
    }
    return result, new_history


def fetch_usage() -> dict:
    script = Path(__file__).parent / "check_claude_usage.py"
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"check_claude_usage.py did not respond within {TIMEOUT_SECONDS}s"}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"could not parse check_claude_usage.py output: {e}"}


def load_history(path: str) -> list[dict]:
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_history(path: str, history: list[dict]) -> None:
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(history, f)
    os.replace(tmp, path)


def read_lanes(path: str) -> int | None:
    try:
        return int(Path(path).read_text().strip())
    except (OSError, ValueError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-file", default=None, help="path to persist session sample history (JSON array)")
    parser.add_argument("--lanes-file", default=None, help="path to a text file containing the current lane count")
    parser.add_argument("--lanes", type=int, default=None, help="explicit current lane count, overrides --lanes-file")
    args = parser.parse_args()

    usage = fetch_usage()
    history = load_history(args.history_file) if args.history_file else []
    current_lanes = args.lanes if args.lanes is not None else (read_lanes(args.lanes_file) if args.lanes_file else None)

    result, new_history = compute_pace(usage, datetime.now(timezone.utc), history, current_lanes)

    if args.history_file:
        save_history(args.history_file, new_history)

    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
