"""A4: rolling z-score sentiment anomaly signal.

Key property under test: the signal reacts to a *change* in sentiment versus a
ticker's own trailing baseline, and does NOT fire on a high-but-flat level.
"""
import numpy as np
import pandas as pd

from quant_backtest.signal_generator import add_sentiment_zscore, generate_zscore_signals


def _frame(ticker, values, post_count=10, start="2024-01-01 09:30", freq="15min"):
    ts = pd.date_range(start=start, periods=len(values), freq=freq, tz="UTC")
    return pd.DataFrame(
        {
            "ticker": ticker,
            "timestamp": ts,
            "avg_sentiment": values,
            "post_count": post_count,
        }
    )


def _run(df, z_threshold=2.0, min_posts=5):
    return generate_zscore_signals(
        add_sentiment_zscore(df, window="2h"),
        z_threshold=z_threshold,
        min_posts=min_posts,
    )


def test_spike_fires_bullish():
    rng = np.random.default_rng(0)
    baseline = list(rng.normal(0.0, 0.02, 12))
    values = baseline + [0.85]  # sharp jump vs a low, mildly-noisy baseline
    out = _run(_frame("NVDA", values))
    assert bool(out.iloc[-1]["zscore_bullish"]) is True
    assert bool(out.iloc[-1]["zscore_alert"]) is True
    # the spike is unambiguously the dominant anomaly in the series
    assert out.iloc[-1]["sentiment_z"] == out["sentiment_z"].max()
    assert out.iloc[-1]["sentiment_z"] > 5.0


def test_sharp_drop_fires_bearish():
    rng = np.random.default_rng(1)
    baseline = list(rng.normal(0.0, 0.02, 12))
    values = baseline + [-0.85]
    out = _run(_frame("NVDA", values))
    assert bool(out.iloc[-1]["zscore_bearish"]) is True


def test_high_but_flat_level_does_not_fire():
    # Constant high sentiment => zero baseline variance => no anomaly, no alert.
    out = _run(_frame("AAPL", [0.6] * 14))
    assert out["zscore_alert"].sum() == 0


def test_min_posts_gate_blocks_thin_windows():
    rng = np.random.default_rng(2)
    values = list(rng.normal(0.0, 0.02, 12)) + [0.85]
    out = _run(_frame("TSLA", values, post_count=2), min_posts=5)
    assert out["zscore_alert"].sum() == 0


def test_no_lookahead_first_bars_are_nan():
    out = _run(_frame("MSFT", [0.1, 0.2, 0.3, 0.4, 0.5]))
    # first bar can never have a trailing baseline
    assert pd.isna(out.iloc[0]["sentiment_z"])
    assert bool(out.iloc[0]["zscore_alert"]) is False
