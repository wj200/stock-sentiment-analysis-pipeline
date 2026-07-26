"""Turns aligned sentiment+price data into rolling sentiment features and trade signals."""
import logging

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


def build_signal_frame(aligned_df: pd.DataFrame, signal_window_label: str = "1h") -> pd.DataFrame:
    """End-to-end: aligned data -> rolling sentiment -> entry/exit signals."""
    with_rolling = add_rolling_sentiment(aligned_df)
    return generate_signals(with_rolling, signal_window_label=signal_window_label)
