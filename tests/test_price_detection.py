"""Feature 2 detection: session logic + evaluate_move (pure, no network)."""
from datetime import datetime

from market.quotes import ET, evaluate_move, session_for


def _et(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ET)


def test_session_for_windows():
    assert session_for(_et(2024, 7, 15, 8, 0)) == "pre"       # Mon 08:00 ET
    assert session_for(_et(2024, 7, 15, 10, 0)) == "regular"  # Mon 10:00 ET
    assert session_for(_et(2024, 7, 15, 17, 0)) == "post"     # Mon 17:00 ET
    assert session_for(_et(2024, 7, 15, 21, 0)) == "closed"   # Mon 21:00 ET
    assert session_for(_et(2024, 7, 13, 10, 0)) == "closed"   # Saturday


def test_big_pct_move_fires_in_premarket():
    a = evaluate_move("NVDA", last=94.0, ref_price=100.0, recent_returns=[0.0] * 10,
                      now=_et(2024, 7, 15, 8, 0))
    assert a is not None
    assert a.direction == "down"
    assert a.pct_move == -6.0
    assert a.session == "pre"


def test_small_move_does_not_fire():
    a = evaluate_move("NVDA", last=100.2, ref_price=100.0, recent_returns=[0.0005] * 10,
                      now=_et(2024, 7, 15, 8, 0))
    assert a is None


def test_regular_session_excluded_by_default():
    a = evaluate_move("NVDA", last=90.0, ref_price=100.0, recent_returns=[0.0] * 10,
                      now=_et(2024, 7, 15, 10, 0))  # regular hours
    assert a is None


def test_zscore_return_spike_fires_even_on_small_pct():
    base = [0.001, -0.001, 0.002, -0.002, 0.001, -0.001, 0.0015, -0.0015, 0.001]
    returns = base + [0.05]  # sharp last-bar return vs a quiet baseline
    a = evaluate_move("NVDA", last=100.1, ref_price=100.0, recent_returns=returns,
                      now=_et(2024, 7, 15, 8, 0))
    assert a is not None
    assert abs(a.ret_z) >= 2.5


def test_bad_ref_price_returns_none():
    assert evaluate_move("NVDA", last=100.0, ref_price=0.0, recent_returns=[0.1] * 10,
                         now=_et(2024, 7, 15, 8, 0)) is None
