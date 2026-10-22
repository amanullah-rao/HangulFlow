import sys

import pytest

from hangulflow import presence
from hangulflow.presence import AWAY, FULLSCREEN, LOCKED, away_reason


def test_present_when_active():
    assert away_reason(locked=False, fullscreen=False, idle_seconds=10) is None


def test_reasons_in_priority_order():
    assert away_reason(locked=True, fullscreen=True, idle_seconds=9999) == LOCKED
    assert away_reason(locked=False, fullscreen=True, idle_seconds=9999) == FULLSCREEN
    assert away_reason(locked=False, fullscreen=False, idle_seconds=300) == AWAY
    assert away_reason(locked=False, fullscreen=False, idle_seconds=299) is None


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 probes")
def test_win32_probes_return_sane_values():
    assert presence.idle_seconds() >= 0
    assert isinstance(presence.is_locked(), bool)
    assert isinstance(presence.is_fullscreen_app_running(), bool)
    assert presence.current_away_reason() in (None, LOCKED, FULLSCREEN, AWAY)
