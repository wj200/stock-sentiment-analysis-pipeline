"""Shared 'why is it moving' service: real quote -> grounded explanation.

Builds the market-quote client, the news retriever, and the LLM provider once
(lazily), and reuses them for both the on-demand /why command and the price
dispatcher. Heavy imports (yfinance/anthropic/finnhub) are deferred to first use
so importing this module is cheap and side-effect-free.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_built = False
_quotes = None
_retriever = None
_provider = None


def _ensure_built():
    global _built, _quotes, _retriever, _provider
    if _built:
        return
    with _lock:
        if _built:
            return
        from explain import get_provider, get_retriever
        from market.quotes import MarketQuotes

        _quotes = MarketQuotes()
        _retriever = get_retriever()
        _provider = get_provider()
        _built = True
        logger.info(
            "explain_service ready (quotes=%s, news=%s, llm=%s)",
            _quotes.provider, _retriever is not None, _provider is not None,
        )


@dataclass
class WhyResult:
    ticker: str
    pct: float
    session: str
    ref_price: float
    last: float
    explanation: "object"  # explain.explainer.Explanation


def why(ticker: str) -> WhyResult | None:
    """Fetch the latest real move for `ticker` and explain it (grounded)."""
    from datetime import datetime, timezone

    from explain.explainer import explain_price_move
    from market.quotes import session_for

    _ensure_built()
    snap = _quotes.snapshot(ticker)
    if snap is None or not snap.prev_close:
        return None
    pct = (snap.last - snap.prev_close) / snap.prev_close * 100.0
    session = session_for(datetime.now(timezone.utc))
    if session == "closed":
        session = "latest"
    exp = explain_price_move(ticker, pct, session, retriever=_retriever, provider=_provider)
    return WhyResult(ticker.upper(), round(pct, 2), session, snap.prev_close, snap.last, exp)
