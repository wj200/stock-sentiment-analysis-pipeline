"""A6: signal validation report — keeps the 'leading indicator' claim honest.

Runs the sentiment-crossing strategy vs. buy-and-hold for every ticker and
assembles a per-ticker report (total return, Sharpe, drawdown, and the delta
vs. benchmark). Intended to run on a schedule (weekly) and/or on demand via the
bot's /validate command, so the headline feature is always shown with its own
out-of-sample P&L, not asserted.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import pandas as pd

from config import settings

logger = logging.getLogger(__name__)

_REPORT_PATH = settings.DATA_ROOT / "validation_report.json"


def _summarize(res) -> dict:
    """Per-ticker strategy-vs-benchmark summary. Reads only plain attrs, so this
    is decoupled from vectorbt (which backtester imports) and unit-testable."""
    def _r(x):
        return round(x, 3) if pd.notna(x) else None

    total = _r(res.total_return_pct)
    bench = _r(res.benchmark_total_return_pct)
    return {
        "ticker": res.ticker,
        "total_return_pct": total,
        "sharpe_ratio": _r(res.sharpe_ratio),
        "max_drawdown_pct": _r(res.max_drawdown_pct),
        "benchmark_total_return_pct": bench,
        "benchmark_sharpe_ratio": _r(res.benchmark_sharpe_ratio),
        "beat_benchmark_pp": round(total - bench, 3) if None not in (total, bench) else None,
    }


def build_report(results: dict) -> dict:
    """Assemble a report dict from {ticker: BacktestResult}. Pure/formatting only."""
    tickers = [_summarize(res) for res in results.values()]
    tickers.sort(key=lambda r: (r["beat_benchmark_pp"] is not None, r["beat_benchmark_pp"] or 0),
                 reverse=True)
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "tickers": tickers}


def run_validation(signal_df: pd.DataFrame, write: bool = True) -> dict:
    """Backtest every ticker in `signal_df` and build (and optionally persist) the report."""
    from quant_backtest.backtester import run_all

    report = build_report(run_all(signal_df))
    if write:
        _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _REPORT_PATH.write_text(json.dumps(report, indent=2, default=str))
        logger.info("Wrote validation report for %d tickers to %s",
                    len(report["tickers"]), _REPORT_PATH)
    return report


def load_latest_report() -> dict | None:
    if _REPORT_PATH.exists():
        try:
            return json.loads(_REPORT_PATH.read_text())
        except json.JSONDecodeError:
            return None
    return None
