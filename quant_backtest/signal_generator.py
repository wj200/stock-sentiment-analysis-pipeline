"""Turns aligned sentiment+price data into rolling sentiment features and trade signals."""
import logging

import numpy as np
import pandas as pd

from config import settings

logger = logging.getLogger(__name__)


def add_rolling_sentiment(aligned_df: pd.DataFrame, windows: dict[str, str] = settings.ROLLING_WINDOWS) -> pd.DataFrame:
    """Adds rolling-mean sentiment columns (`sentiment_roll_<label>`) per ticker.

    Rolling windows are computed on already point-in-time-safe `avg_sentiment`
    bars (see `data_pipeline.data_alignment`), so no additional lookahead is
    introduced here — a rolling window ending at row `t` only uses rows <= t.
    """
    df = aligned_df.sort_values(["ticker", "timestamp"]).copy()

    for label, freq in windows.items():
        col = f"sentiment_roll_{label}"
        df[col] = (
            df.groupby("ticker")
            .apply(
                lambda g: g.set_index("timestamp")["avg_sentiment"]
                .rolling(freq, min_periods=1)
                .mean()
            )
            .reset_index(level=0, drop=True)
            .values
        )
    return df


def generate_signals(
    df: pd.DataFrame,
    signal_window_label: str = "1h",
    entry_threshold: float = settings.ENTRY_SENTIMENT_THRESHOLD,
    exit_threshold: float = settings.EXIT_SENTIMENT_THRESHOLD,
) -> pd.DataFrame:
    """Adds boolean `entry_signal` / `exit_signal` columns.

    Entry: rolling sentiment crosses above `entry_threshold`.
    Exit: rolling sentiment dips below `exit_threshold`.
    Crossing (not just "is above") is used so vectorbt sees discrete
    transition events rather than a signal that stays true for many bars.
    """
    roll_col = f"sentiment_roll_{signal_window_label}"
    if roll_col not in df.columns:
        raise ValueError(f"Missing rolling sentiment column '{roll_col}'; call add_rolling_sentiment first.")

    df = df.sort_values(["ticker", "timestamp"]).copy()

    def _signals_for_ticker(group: pd.DataFrame) -> pd.DataFrame:
        sentiment = group[roll_col]
        prev_sentiment = sentiment.shift(1)

        entry = (sentiment > entry_threshold) & (prev_sentiment <= entry_threshold)
        exit_ = (sentiment < exit_threshold) & (prev_sentiment >= exit_threshold)

        group = group.copy()
        group["entry_signal"] = entry.fillna(False)
        group["exit_signal"] = exit_.fillna(False)
        return group

    return df.groupby("ticker", group_keys=False).apply(_signals_for_ticker)


def add_sentiment_zscore(
    df: pd.DataFrame,
    window: str = settings.SENTIMENT_Z_WINDOW,
) -> pd.DataFrame:
    """Adds a `sentiment_z` column: how anomalous each bar's sentiment is vs. its
    own trailing baseline (milestone A4).

    The baseline (rolling mean/std of `avg_sentiment`) is computed over `window`
    and then **shifted by one bar**, so a bar at time t is compared only to
    sentiment strictly before t — the current value never contributes to the
    distribution it is judged against, and there is no lookahead.
    """
    df = df.sort_values(["ticker", "timestamp"]).copy()

    def _per_ticker(group: pd.DataFrame) -> pd.DataFrame:
        group = group.copy()
        series = group.set_index("timestamp")["avg_sentiment"]
        roll = series.rolling(window, min_periods=3)
        baseline_mean = roll.mean().shift(1)
        baseline_std = roll.std(ddof=0).shift(1).replace(0.0, np.nan)
        z = (series - baseline_mean) / baseline_std
        group["sentiment_z"] = z.to_numpy()
        return group

    df = df.groupby("ticker", group_keys=False).apply(_per_ticker)
    return df


def generate_zscore_signals(
    df: pd.DataFrame,
    z_threshold: float = settings.SENTIMENT_Z_THRESHOLD,
    min_posts: int = settings.SENTIMENT_Z_MIN_POSTS,
) -> pd.DataFrame:
    """Adds boolean z-score alert columns.

    A bar fires when its sentiment is `z_threshold` sigma away from its trailing
    baseline AND the window carried at least `min_posts` posts (so a single
    stray post on a quiet name can't trip it). This adapts per ticker and reacts
    to *changes* in sentiment, not absolute levels — the "beyond a threshold"
    leading indicator in the brief.
    """
    df = df.copy()
    if "sentiment_z" not in df.columns:
        raise ValueError("Missing 'sentiment_z'; call add_sentiment_zscore first.")

    enough = df["post_count"] >= min_posts if "post_count" in df.columns else True
    z = df["sentiment_z"]
    df["zscore_bullish"] = ((z >= z_threshold) & enough).fillna(False)
    df["zscore_bearish"] = ((z <= -z_threshold) & enough).fillna(False)
    df["zscore_alert"] = df["zscore_bullish"] | df["zscore_bearish"]
    return df


def build_signal_frame(aligned_df: pd.DataFrame, signal_window_label: str = "1h") -> pd.DataFrame:
    """End-to-end: aligned data -> rolling sentiment -> entry/exit + z-score signals."""
    with_rolling = add_rolling_sentiment(aligned_df)
    with_signals = generate_signals(with_rolling, signal_window_label=signal_window_label)
    with_z = add_sentiment_zscore(with_signals)
    return generate_zscore_signals(with_z)
