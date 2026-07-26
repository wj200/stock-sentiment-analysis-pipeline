"""Cached data access layer shared by all Telegram bot handlers.

Wraps the same Delta Lake / alignment / signal / backtest modules the
Streamlit dashboard uses, behind a small TTL cache so a burst of commands in
a chat doesn't re-trigger a Spark read or a yfinance call per keystroke.
"""
import logging
import threading
import time
from typing import Callable, TypeVar

import pandas as pd

from config import settings
from data_pipeline.data_alignment import align_sentiment_with_price, fetch_market_data
from data_pipeline.delta_writer import get_spark, read_table
from quant_backtest.backtester import BacktestResult, run_backtest
from quant_backtest.signal_generator import build_signal_frame

logger = logging.getLogger(__name__)

T = TypeVar("T")

WINDOW_TO_YF_INTERVAL = {"15m": "15m", "1h": "1h", "4h": "1h", "24h": "1d"}


class _TTLCache:
    """Minimal thread-safe TTL cache, standing in for Streamlit's `st.cache_data`."""

    def __init__(self, ttl_seconds: int):
        self.ttl_seconds = ttl_seconds
        self._store: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()

    def get_or_compute(self, key: str, compute: Callable[[], T]) -> T:
        now = time.monotonic()
        with self._lock:
            cached = self._store.get(key)
            if cached is not None and (now - cached[0]) < self.ttl_seconds:
                return cached[1]

        value = compute()
        with self._lock:
            self._store[key] = (now, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


_cache = _TTLCache(ttl_seconds=settings.TELEGRAM_DATA_CACHE_SECONDS)
_spark = None
_spark_lock = threading.Lock()


def _get_spark():
    global _spark
    if _spark is None:
        with _spark_lock:
            if _spark is None:
                _spark = get_spark("telegram-bot")
    return _spark


def refresh() -> None:
    """Drops all cached data; next request re-reads Delta/yfinance."""
    _cache.clear()


def load_scored_sentiment() -> pd.DataFrame:
    def _compute() -> pd.DataFrame:
        try:
            df = read_table(_get_spark(), settings.SCORED_SENTIMENT_TABLE).toPandas()
        except Exception as exc:  # noqa: BLE001 - table may not exist yet
            logger.warning("Could not read scored sentiment table: %s", exc)
            return pd.DataFrame(
                columns=["id", "ticker", "timestamp", "source", "text", "positive", "neutral", "negative", "sentiment_score"]
            )
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df

    return _cache.get_or_compute("scored_sentiment", _compute)


def load_market_prices(window_label: str) -> pd.DataFrame:
    interval = WINDOW_TO_YF_INTERVAL[window_label]

    def _compute() -> pd.DataFrame:
        return fetch_market_data(settings.TICKERS, period="60d", interval=interval)

    return _cache.get_or_compute(f"market_prices:{interval}", _compute)


def load_signal_frame(window_label: str) -> pd.DataFrame:
    def _compute() -> pd.DataFrame:
        scored_df = load_scored_sentiment()
        market_df = load_market_prices(window_label)
        if scored_df.empty or market_df.empty:
            return pd.DataFrame()
        aligned_df = align_sentiment_with_price(scored_df, market_df, window=settings.ROLLING_WINDOWS["15m"])
        return build_signal_frame(aligned_df, signal_window_label=window_label)

    return _cache.get_or_compute(f"signal_frame:{window_label}", _compute)


def get_backtest_result(ticker: str, window_label: str) -> BacktestResult | None:
    signal_df = load_signal_frame(window_label)
    if signal_df.empty or ticker not in signal_df["ticker"].unique():
        return None

    def _compute() -> BacktestResult:
        return run_backtest(signal_df, ticker)

    return _cache.get_or_compute(f"backtest:{ticker}:{window_label}", _compute)


def get_recent_posts(ticker: str, limit: int = 10) -> pd.DataFrame:
    scored_df = load_scored_sentiment()
    if scored_df.empty:
        return scored_df
    return (
        scored_df[scored_df["ticker"] == ticker]
        .sort_values("timestamp", ascending=False)
        .head(limit)[["timestamp", "source", "text", "sentiment_score"]]
    )
