"""Aligns aggregated sentiment with historical OHLCV bars, point-in-time safe.

Two responsibilities:
  1. `fetch_market_data`: pull OHLCV bars from yfinance (default) or Alpaca.
  2. `align_sentiment_with_price`: aggregate raw/scored sentiment into fixed
     windows (default 15m) and `merge_asof` them onto price bars using
     `direction="backward", allow_exact_matches=False` — i.e. a price bar at
     time `t` may only see sentiment strictly *before* `t`. This is the
     standard point-in-time guard against lookahead bias: a bar's decision
     signal cannot depend on information that arrived at or after that bar.

The merge is done in Pandas (via `toPandas()`) since aligned research
datasets for a handful of tickers comfortably fit in memory; the raw/scored
sentiment itself still lives at full fidelity in Delta Lake.
"""
import logging
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf
from pyspark.sql import DataFrame as SparkDataFrame

from config import settings

logger = logging.getLogger(__name__)


def fetch_market_data(
    tickers: list[str] = settings.TICKERS,
    period: str = "60d",
    interval: str = "15m",
    provider: str = settings.MARKET_DATA_PROVIDER,
) -> pd.DataFrame:
    """Returns a long-format OHLCV DataFrame: [ticker, timestamp, open, high, low, close, volume]."""
    if provider == "alpaca":
        return _fetch_market_data_alpaca(tickers, period, interval)
    return _fetch_market_data_yfinance(tickers, period, interval)


def _fetch_market_data_yfinance(tickers: list[str], period: str, interval: str) -> pd.DataFrame:
    frames = []
    for ticker in tickers:
        hist = yf.Ticker(ticker).history(period=period, interval=interval)
        if hist.empty:
            logger.warning("No yfinance data returned for %s", ticker)
            continue
        hist = hist.reset_index().rename(
            columns={
                "Date": "timestamp",
                "Datetime": "timestamp",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
        )
        hist["ticker"] = ticker
        hist["timestamp"] = pd.to_datetime(hist["timestamp"], utc=True)
        frames.append(hist[["ticker", "timestamp", "open", "high", "low", "close", "volume"]])

    if not frames:
        return pd.DataFrame(columns=["ticker", "timestamp", "open", "high", "low", "close", "volume"])
    return pd.concat(frames, ignore_index=True).sort_values(["ticker", "timestamp"])


def _fetch_market_data_alpaca(tickers: list[str], period: str, interval: str) -> pd.DataFrame:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    client = StockHistoricalDataClient(settings.ALPACA_API_KEY, settings.ALPACA_API_SECRET)
    days = int(period.rstrip("d")) if period.endswith("d") else 60
    start = datetime.utcnow() - timedelta(days=days)

    timeframe_map = {"15m": TimeFrame.Minute, "1h": TimeFrame.Hour, "1d": TimeFrame.Day}
    request = StockBarsRequest(
        symbol_or_symbols=tickers,
        timeframe=timeframe_map.get(interval, TimeFrame.Minute),
        start=start,
    )
    bars = client.get_stock_bars(request).df.reset_index()
    bars = bars.rename(columns={"symbol": "ticker"})
    bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True)
    return bars[["ticker", "timestamp", "open", "high", "low", "close", "volume"]]


def aggregate_sentiment(scored_sentiment: pd.DataFrame, window: str = "15min") -> pd.DataFrame:
    """Buckets scored sentiment into fixed windows per ticker.

    Returns [ticker, timestamp (window right edge), avg_sentiment, post_count,
    avg_positive, avg_negative] where `timestamp` marks when the aggregate
    became fully known (the window's close), which is the value later used
    as the point-in-time cutoff during the price join.
    """
    df = scored_sentiment.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    grouped = (
        df.set_index("timestamp")
        .groupby("ticker")
        .resample(window)
        .agg(
            avg_sentiment=("sentiment_score", "mean"),
            post_count=("sentiment_score", "count"),
            avg_positive=("positive", "mean"),
            avg_negative=("negative", "mean"),
        )
        .reset_index()
    )
    # `resample` labels bins by their left edge; shift to the right edge so the
    # aggregate's timestamp reflects when the window's data was fully observed.
    freq_offset = pd.tseries.frequencies.to_offset(window)
    grouped["timestamp"] = grouped["timestamp"] + freq_offset
    return grouped.dropna(subset=["post_count"]).query("post_count > 0")


def align_sentiment_with_price(
    scored_sentiment: pd.DataFrame,
    market_prices: pd.DataFrame,
    window: str = "15min",
) -> pd.DataFrame:
    """Point-in-time join: each price bar sees only sentiment fully known before it opens."""
    sentiment_agg = aggregate_sentiment(scored_sentiment, window=window)

    aligned_frames = []
    for ticker in market_prices["ticker"].unique():
        price_slice = market_prices[market_prices["ticker"] == ticker].sort_values("timestamp")
        sentiment_slice = sentiment_agg[sentiment_agg["ticker"] == ticker].sort_values("timestamp")

        if sentiment_slice.empty:
            merged = price_slice.copy()
            for col in ("avg_sentiment", "post_count", "avg_positive", "avg_negative"):
                merged[col] = pd.NA
        else:
            merged = pd.merge_asof(
                price_slice,
                sentiment_slice.drop(columns=["ticker"]),
                on="timestamp",
                direction="backward",
                allow_exact_matches=False,  # strictly-before only: no lookahead
            )
        aligned_frames.append(merged)

    result = pd.concat(aligned_frames, ignore_index=True)
    result["avg_sentiment"] = result["avg_sentiment"].fillna(0.0)
    result["post_count"] = result["post_count"].fillna(0).astype(int)
    return result.sort_values(["ticker", "timestamp"]).reset_index(drop=True)


def align_from_spark(scored_sentiment_df: SparkDataFrame, market_prices_pdf: pd.DataFrame, window: str = "15min") -> pd.DataFrame:
    """Convenience wrapper: takes a Spark DataFrame (e.g. read from Delta) and a Pandas price frame."""
    return align_sentiment_with_price(scored_sentiment_df.toPandas(), market_prices_pdf, window=window)
