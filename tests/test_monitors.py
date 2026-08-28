"""Feature 2/3 monitors: price-move emission/de-dup + macro new-release detection."""
from datetime import datetime

from ingestion.macro_monitor import _is_new
from ingestion.price_monitor import poll_once
from ingestion.sources.base import bounded_seen
from market.quotes import ET, Snapshot


class FakeProducer:
    def __init__(self):
        self.produced = []

    def produce(self, topic, key, value, callback=None):
        self.produced.append((topic, key, value))

    def poll(self, _):
        pass

    def flush(self, _):
        pass


class FakeQuotes:
    provider = "yfinance"

    def __init__(self, snap):
        self._snap = snap

    def snapshot(self, ticker):
        return self._snap


def test_price_monitor_emits_once_then_dedups():
    snap = Snapshot("NVDA", last=94.0, prev_close=100.0, recent_returns=[0.0] * 10)  # -6%
    prod, seen = FakeProducer(), bounded_seen()
    now = datetime(2024, 7, 15, 8, 0, tzinfo=ET)  # Mon pre-market
    assert poll_once(prod, FakeQuotes(snap), seen, "t", tickers=["NVDA"], now=now) == 1
    assert len(prod.produced) == 1
    # same session/direction/date => no re-emit
    assert poll_once(prod, FakeQuotes(snap), seen, "t", tickers=["NVDA"], now=now) == 0
    assert len(prod.produced) == 1


def test_price_monitor_silent_in_regular_hours():
    snap = Snapshot("NVDA", last=90.0, prev_close=100.0, recent_returns=[0.0] * 10)
    prod, seen = FakeProducer(), bounded_seen()
    now = datetime(2024, 7, 15, 10, 0, tzinfo=ET)  # regular session
    assert poll_once(prod, FakeQuotes(snap), seen, "t", tickers=["NVDA"], now=now) == 0


def test_macro_is_new():
    assert _is_new(None, None) is False
    assert _is_new("2024-07-01", None) is True          # first time we see the series
    assert _is_new("2024-08-01", "2024-07-01") is True  # new observation date
    assert _is_new("2024-07-01", "2024-07-01") is False  # same release, already seen
    assert _is_new("2024-06-01", "2024-07-01") is False  # stale (shouldn't happen)
