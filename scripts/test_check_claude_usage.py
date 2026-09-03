#!/usr/bin/env python3
"""Assert-based self-check for check_claude_usage.py's text parser.

No subprocess/network calls -- exercises parse_usage_text() against fixed
sample text captured from a real `/usage` run. Run directly:
python scripts/test_check_claude_usage.py
"""

import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "check_claude_usage", Path(__file__).parent / "check_claude_usage.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

SAMPLE = """You are currently using your subscription to power your Claude Code usage

Current session: 8% used · resets Sep 2, 7:29pm (Asia/Tokyo)
Current week (all models): 13% used · resets Sep 5, 2:59am (Asia/Tokyo)
Current week (Fable): 0% used

What's contributing to your limits usage?
"""


def test_parses_session_and_weeks():
    result = mod.parse_usage_text(SAMPLE)
    assert result["ok"] is True
    assert result["session"] == {"percent": 8, "resets": "Sep 2, 7:29pm (Asia/Tokyo)"}
    assert result["weeks"] == [
        {"label": "all models", "percent": 13, "resets": "Sep 5, 2:59am (Asia/Tokyo)"},
        {"label": "Fable", "percent": 0, "resets": None},
    ]
    assert result["max_percent"] == 13
    assert "checked_at" in result


def test_decode_first_json_ignores_trailing_hook_noise():
    noisy = '{"result": "ok"}\n.\n..\nsome-stray-hook-output\n'
    assert mod._decode_first_json(noisy) == {"result": "ok"}


def test_decode_first_json_raises_when_no_json():
    try:
        mod._decode_first_json("no json here at all")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError when no JSON object present")


def test_rejects_unexpected_text():
    try:
        mod.parse_usage_text("Total cost: $0.0000\nTotal duration (API): 0s\n")
    except ValueError:
        pass
    else:
        raise AssertionError(
            "expected ValueError for non-usage text (e.g. --bare fallback)"
        )


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all tests passed")
    sys.exit(0)
