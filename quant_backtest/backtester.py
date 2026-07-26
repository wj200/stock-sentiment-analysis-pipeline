"""Vectorbt-powered backtest engine for sentiment-driven entry/exit signals."""
import logging
from dataclasses import dataclass

import pandas as pd
import vectorbt as vbt

from config import settings

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    ticker: str
    total_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    benchmark_total_return_pct: float
    benchmark_sharpe_ratio: float
    cumulative_returns: pd.Series
    benchmark_cumulative_returns: pd.Series
    portfolio: vbt.Portfolio
    benchmark_portfolio: vbt.Portfolio


def run_backtest(
    signal_df: pd.DataFrame,
    ticker: str,
    init_cash: float = settings.BACKTEST_INITIAL_CASH,
    fees: float = settings.BACKTEST_FEES,
) -> BacktestResult:
    """Runs a sentiment-signal strategy backtest for a single ticker vs. buy & hold.

    `signal_df` must contain rows for one or many tickers with columns
    [ticker, timestamp, close, entry_signal, exit_signal].
    """
    ticker_df = signal_df[signal_df["ticker"] == ticker].sort_values("timestamp").set_index("timestamp")

    if ticker_df.empty:
        raise ValueError(f"No signal data found for ticker '{ticker}'")

    close = ticker_df["close"]
    entries = ticker_df["entry_signal"].astype(bool)
    exits = ticker_df["exit_signal"].astype(bool)

    portfolio = vbt.Portfolio.from_signals(
        close=close,
        entries=entries,
        exits=exits,
        init_cash=init_cash,
        fees=fees,
        freq=_infer_freq(ticker_df.index),
    )

    benchmark_portfolio = vbt.Portfolio.from_holding(
        close=close,
        init_cash=init_cash,
        freq=_infer_freq(ticker_df.index),
    )

    return BacktestResult(
        ticker=ticker,
        total_return_pct=portfolio.total_return() * 100,
        sharpe_ratio=portfolio.sharpe_ratio(),
        max_drawdown_pct=portfolio.max_drawdown() * 100,
        benchmark_total_return_pct=benchmark_portfolio.total_return() * 100,
        benchmark_sharpe_ratio=benchmark_portfolio.sharpe_ratio(),
        cumulative_returns=portfolio.cumulative_returns(),
        benchmark_cumulative_returns=benchmark_portfolio.cumulative_returns(),
        portfolio=portfolio,
        benchmark_portfolio=benchmark_portfolio,
    )


def _infer_freq(index: pd.DatetimeIndex) -> str:
    inferred = pd.infer_freq(index)
    if inferred:
        return inferred
    if len(index) > 1:
        median_delta = pd.Series(index).diff().median()
        return median_delta
    return "15min"


def summarize(result: BacktestResult) -> dict:
    return {
        "ticker": result.ticker,
        "total_return_pct": round(result.total_return_pct, 3),
        "sharpe_ratio": round(result.sharpe_ratio, 3) if pd.notna(result.sharpe_ratio) else None,
        "max_drawdown_pct": round(result.max_drawdown_pct, 3),
        "benchmark_total_return_pct": round(result.benchmark_total_return_pct, 3),
        "benchmark_sharpe_ratio": round(result.benchmark_sharpe_ratio, 3) if pd.notna(result.benchmark_sharpe_ratio) else None,
    }


def run_all(signal_df: pd.DataFrame, tickers: list[str] | None = None) -> dict[str, BacktestResult]:
    tickers = tickers or sorted(signal_df["ticker"].unique())
    results = {}
    for ticker in tickers:
        try:
            results[ticker] = run_backtest(signal_df, ticker)
        except ValueError as exc:
            logger.warning("Skipping %s: %s", ticker, exc)
    return results
