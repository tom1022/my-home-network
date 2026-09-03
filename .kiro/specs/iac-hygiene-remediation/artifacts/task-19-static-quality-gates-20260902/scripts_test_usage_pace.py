#!/usr/bin/env python3
"""Assert-based self-check for usage_pace.py's pure logic (reset parsing,
window pace math, history smoothing, action decision, lane recommendation).
No subprocess/claude calls -- `now` and history are always passed in
explicitly so results are deterministic. Run directly:
python scripts/test_usage_pace.py
"""
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "usage_pace", Path(__file__).parent / "usage_pace.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_parse_reset_resolves_near_future_year():
    now = datetime(2026, 9, 2, 6, 0, 0, tzinfo=timezone.utc)  # 2026-09-02 15:00 JST
    dt = mod.parse_reset("Sep 5, 3am (Asia/Tokyo)", now)
    assert dt.tzinfo is not None
    jst = dt.astimezone(mod.TOKYO)
    assert (jst.year, jst.month, jst.day, jst.hour, jst.minute) == (2026, 9, 5, 3, 0)


def test_parse_reset_wraps_to_next_year_when_in_the_past_this_year():
    now = datetime(2026, 12, 30, 0, 0, 0, tzinfo=timezone.utc)
    dt = mod.parse_reset("Jan 2, 3am (Asia/Tokyo)", now)
    jst = dt.astimezone(mod.TOKYO)
    assert jst.year == 2027


def test_parse_reset_pm_and_minutes():
    now = datetime(2026, 9, 2, 0, 0, 0, tzinfo=timezone.utc)
    dt = mod.parse_reset("Sep 2, 7:30pm (Asia/Tokyo)", now)
    jst = dt.astimezone(mod.TOKYO)
    assert (jst.hour, jst.minute) == (19, 30)


def test_parse_reset_rejects_garbage():
    try:
        mod.parse_reset("not a date", datetime.now(timezone.utc))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for unparseable reset string")


def test_parse_reset_rejects_none():
    try:
        mod.parse_reset(None, datetime.now(timezone.utc))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for None reset string")


def test_compute_window_pace_on_target():
    # Exactly half the 168h week elapsed, exactly 40% used == right on the 80% line.
    now = datetime(2026, 9, 2, 0, 0, 0, tzinfo=timezone.utc)
    reset = now + timedelta(hours=84)
    pace = mod.compute_window_pace(40.0, reset, now, mod.WEEK_HOURS)
    assert abs(pace["elapsed_ratio"] - 0.5) < 1e-6
    assert abs(pace["target_percent"] - 40.0) < 1e-6
    assert abs(pace["delta"]) < 1e-6
    assert abs(pace["speedup"] - 1.0) < 1e-6
    assert abs(pace["hours_to_80"] - 84.0) < 1e-6
    assert pace["will_stall_before_reset"] is False  # lands exactly at reset, not before


def test_compute_window_pace_behind_needs_speedup():
    now = datetime(2026, 9, 2, 0, 0, 0, tzinfo=timezone.utc)
    reset = now + timedelta(hours=84)
    pace = mod.compute_window_pace(10.0, reset, now, mod.WEEK_HOURS)
    assert pace["delta"] < 0
    assert pace["speedup"] > 1.0


def test_compute_window_pace_current_rate_none_at_window_start():
    now = datetime(2026, 9, 2, 0, 0, 0, tzinfo=timezone.utc)
    reset = now + timedelta(hours=168)
    pace = mod.compute_window_pace(0.0, reset, now, mod.WEEK_HOURS)
    assert pace["current_rate_pt_per_h"] is None
    assert pace["speedup"] is None
    assert pace["hours_to_80"] is None
    assert pace["will_stall_before_reset"] is False


def test_compute_window_pace_will_stall_before_reset():
    # 1h elapsed of a 5h session, already at 40% -> way too fast, hits 80%
    # long before the remaining 4h are up.
    now = datetime(2026, 9, 2, 1, 0, 0, tzinfo=timezone.utc)
    reset = now + timedelta(hours=4)
    pace = mod.compute_window_pace(40.0, reset, now - timedelta(hours=1), mod.SESSION_HOURS)
    # actual_percent/elapsed_h uses elapsed from window_start=reset-5h to `now` param;
    # recompute with correct now to keep elapsed_h=1.
    pace = mod.compute_window_pace(40.0, reset, now, mod.SESSION_HOURS)
    assert pace["hours_to_80"] is not None
    assert pace["hours_to_80"] < pace["remaining_hours"]
    assert pace["will_stall_before_reset"] is True


def test_compute_window_pace_rate_override_used_for_rate_fields_only():
    now = datetime(2026, 9, 2, 1, 0, 0, tzinfo=timezone.utc)
    reset = now + timedelta(hours=4)
    raw = mod.compute_window_pace(20.0, reset, now, mod.SESSION_HOURS)
    smoothed = mod.compute_window_pace(20.0, reset, now, mod.SESSION_HOURS, rate_override=5.0)
    # target/delta are rate-independent -> unchanged
    assert raw["target_percent"] == smoothed["target_percent"]
    assert raw["delta"] == smoothed["delta"]
    # rate-derived fields follow the override
    assert smoothed["current_rate_pt_per_h"] == 5.0
    assert smoothed["current_rate_pt_per_h"] != raw["current_rate_pt_per_h"]


def test_linear_regression_slope_basic():
    # y = 2x + 1 exactly -> slope 2
    pts = [(0.0, 1.0), (1.0, 3.0), (2.0, 5.0), (3.0, 7.0)]
    assert abs(mod.linear_regression_slope(pts) - 2.0) < 1e-9


def test_linear_regression_slope_needs_two_points():
    assert mod.linear_regression_slope([(1.0, 1.0)]) is None
    assert mod.linear_regression_slope([]) is None


def test_linear_regression_slope_none_when_all_x_equal():
    assert mod.linear_regression_slope([(1.0, 5.0), (1.0, 9.0)]) is None


def test_update_history_appends_within_same_session():
    h = [{"elapsed_hours": 0.0, "percent": 0, "reset": "Sep 2, 7pm (Asia/Tokyo)"}]
    sample = {"elapsed_hours": 0.5, "percent": 5, "reset": "Sep 2, 7pm (Asia/Tokyo)"}
    new_h = mod.update_history(h, sample)
    assert len(new_h) == 2
    assert new_h[-1] == sample


def test_update_history_resets_when_elapsed_hours_drops():
    h = [{"elapsed_hours": 4.9, "percent": 78, "reset": "Sep 2, 7pm (Asia/Tokyo)"}]
    sample = {"elapsed_hours": 0.02, "percent": 0, "reset": "Sep 3, 12am (Asia/Tokyo)"}
    new_h = mod.update_history(h, sample)
    assert new_h == [sample]  # old session's samples dropped, not carried over


def test_update_history_ignores_reset_string_jitter():
    # /usage's displayed reset time can wobble by ~1 minute between polls
    # (rounding) even within the same session -- elapsed_hours barely
    # moves, so this must NOT be treated as a rollover.
    h = [{"elapsed_hours": 1.0, "percent": 20, "reset": "Sep 2, 7:30pm (Asia/Tokyo)"}]
    sample = {"elapsed_hours": 1.08, "percent": 22, "reset": "Sep 2, 7:29pm (Asia/Tokyo)"}
    new_h = mod.update_history(h, sample)
    assert len(new_h) == 2  # appended, not wiped, despite the reset string changing


def test_update_history_caps_length():
    h = [{"elapsed_hours": float(i), "percent": i, "reset": "r"} for i in range(5)]
    sample = {"elapsed_hours": 5.0, "percent": 5, "reset": "r"}
    new_h = mod.update_history(h, sample, max_keep=3)
    assert len(new_h) == 3
    assert new_h[-1] == sample


def test_smoothed_session_rate_insufficient_history():
    h = [{"elapsed_hours": 0.0, "percent": 0}, {"elapsed_hours": 0.05, "percent": 1}]
    rate, n, span = mod.smoothed_session_rate(h)
    assert rate is None  # only 2 points, below MIN_HISTORY_POINTS
    assert n == 2


def test_smoothed_session_rate_enough_history():
    h = [
        {"elapsed_hours": 0.0, "percent": 0},
        {"elapsed_hours": 0.5, "percent": 10},
        {"elapsed_hours": 1.0, "percent": 20},
    ]
    rate, n, span = mod.smoothed_session_rate(h)
    assert rate is not None
    assert abs(rate - 20.0) < 1e-6
    assert n == 3


def test_decide_action_ignores_week_uses_session_only():
    assert mod.decide_action({"delta": -20.0}, warming_up=False) == "up"
    assert mod.decide_action({"delta": 20.0}, warming_up=False) == "down"
    assert mod.decide_action({"delta": 0.0}, warming_up=False) == "hold"


def test_decide_action_warming_up_forces_hold():
    # Even a huge delta must not trigger up/down while warming up.
    assert mod.decide_action({"delta": 50.0}, warming_up=True) == "hold"
    assert mod.decide_action({"delta": -50.0}, warming_up=True) == "hold"


def test_recommend_lanes_scales_by_speedup():
    assert mod.recommend_lanes(4, 0.5) == 2
    assert mod.recommend_lanes(4, 1.0) == 4
    assert mod.recommend_lanes(1, 0.1) == 1  # floored at 1, never recommend zero lanes


def test_recommend_lanes_none_when_inputs_missing():
    assert mod.recommend_lanes(None, 1.5) is None
    assert mod.recommend_lanes(4, None) is None


def test_compute_pace_propagates_upstream_failure():
    result, history = mod.compute_pace({"ok": False, "error": "boom"}, datetime.now(timezone.utc))
    assert result["ok"] is False
    assert "boom" in result["error"]
    assert history == []


def test_compute_pace_warms_up_on_first_sample():
    now = datetime(2026, 9, 2, 6, 0, 0, tzinfo=timezone.utc)
    usage = {
        "ok": True,
        "session": {"percent": 10, "resets": "Sep 2, 7:30pm (Asia/Tokyo)"},
        "weeks": [{"label": "all models", "percent": 14, "resets": "Sep 5, 3am (Asia/Tokyo)"}],
    }
    result, history = mod.compute_pace(usage, now, history=[], current_lanes=4)
    assert result["ok"] is True
    assert result["session"]["warming_up"] is True  # single sample, no trend yet
    assert result["action"] == "hold"
    assert len(history) == 1


def test_compute_pace_builds_up_history_and_recommends_lanes():
    reset = "Sep 2, 8:57pm (Asia/Tokyo)"
    usage = {
        "ok": True,
        "session": {"percent": 23, "resets": reset},
        "weeks": [{"label": "all models", "percent": 20, "resets": "Sep 5, 3am (Asia/Tokyo)"}],
    }
    now = datetime(2026, 9, 2, 8, 0, 0, tzinfo=timezone.utc)
    history = [
        {"ts": "x", "elapsed_hours": 0.0, "percent": 0, "reset": reset},
        {"ts": "x", "elapsed_hours": 0.35, "percent": 8, "reset": reset},
        {"ts": "x", "elapsed_hours": 0.70, "percent": 16, "reset": reset},
    ]
    result, new_history = mod.compute_pace(usage, now, history, current_lanes=4)
    assert result["ok"] is True
    assert result["session"]["warming_up"] is False
    assert result["session"]["rate_smoothed"] is True
    assert result["session"]["will_stall_before_reset"] is True  # running hot, per the scenario
    assert result["action"] == "down"
    assert result["lanes"]["current"] == 4
    assert result["lanes"]["recommended"] < 4  # told to throttle
    assert len(new_history) == 4


def test_compute_pace_missing_all_models_week():
    result, history = mod.compute_pace(
        {"ok": True, "session": {"percent": 1, "resets": "Sep 2, 7pm (Asia/Tokyo)"}, "weeks": []},
        datetime.now(timezone.utc),
    )
    assert result["ok"] is False


def test_load_save_history_roundtrip(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = f"{d}/history.json"
        assert mod.load_history(p) == []  # missing file -> empty, not an error
        mod.save_history(p, [{"a": 1}])
        assert mod.load_history(p) == [{"a": 1}]


def test_read_lanes(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = f"{d}/lanes.txt"
        assert mod.read_lanes(p) is None  # missing file
        Path(p).write_text("5\n")
        assert mod.read_lanes(p) == 5
        Path(p).write_text("not a number")
        assert mod.read_lanes(p) is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all tests passed")
    sys.exit(0)
