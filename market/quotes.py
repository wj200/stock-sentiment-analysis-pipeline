"""Real market quotes + pure price-move detection (Feature 2).

Detection (`evaluate_move`, `session_for`) is pure and unit-tested with no
network. Fetching (`MarketQuotes`) uses yfinance by default (real, keyless,
supports pre/post-market via prepost=True) and Alpaca when credentials are set.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from config import settings

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


def session_for(dt: datetime) -> str:
    """US equity session for a UTC datetime: pre | regular | post | closed."""
    et = dt.astimezone(ET)
    if et.weekday() >= 5:  # Sat/Sun
        return "closed"
    t = et.time()
    if time(4, 0) <= t < time(9, 30):
        return "pre"
    if time(9, 30) <= t < time(16, 0):
        return "regular"
    if time(16, 0) <= t < time(20, 0):
        return "post"
    return "closed"


def _zscore(returns: list[float]) -> float:
    """z-score of the most recent return vs the earlier returns in the window."""
    if len(returns) < 5:
        return 0.0
    import statistics

    latest = returns[-1]
    base = returns[:-1]
    mean = statistics.fmean(base)
    sd = statistics.pstdev(base)
    if sd == 0:
        return 0.0
    return (latest - mean) / sd


@dataclass
class MoveAlert:
    ticker: str
    pct_move: float
    direction: str  # "up" | "down"
    ret_z: float
    session: str
    ref_price: float
    last: float
    ts: str


def evaluate_move(
    ticker: str,
    last: float,
    ref_price: float,
    recent_returns: list[float],
    *,
    now: datetime | None = None,
    pct_threshold: float = settings.PRICE_MOVE_PCT,
    z_threshold: float = settings.PRICE_MOVE_Z,
    sessions: tuple[str, ...] = ("pre", "post"),
) -> MoveAlert | None:
    """Return a MoveAlert if the move is significant this session, else None.

    Fires when |pct move vs ref| >= pct_threshold OR |return z-score| >= z_threshold,
    but only during the configured sessions (pre/post by default).
    """
    now = now or datetime.now(timezone.utc)
    session = session_for(now)
    if session not in sessions:
        return None
    if not ref_price or ref_price <= 0 or last <= 0:
        return None

    pct = (last - ref_price) / ref_price * 100.0
    z = _zscore(recent_returns)
    if abs(pct) < pct_threshold and abs(z) < z_threshold:
        return None

    return MoveAlert(
        ticker=ticker.upper(),
        pct_move=round(pct, 2),
        direction="up" if pct >= 0 else "down",
        ret_z=round(z, 2),
        session=session,
        ref_price=round(ref_price, 4),
        last=round(last, 4),
        ts=now.isoformat(),
    )


@dataclass
class Snapshot:
    ticker: str
    last: float
    prev_close: float
    recent_returns: list[float]


class MarketQuotes:
    """Fetches real quotes. provider: 'yfinance' (keyless) or 'alpaca' (keyed)."""

    def __init__(self, provider: str = settings.MARKET_DATA_PROVIDER):
        self.provider = provider if provider != "alpaca" or settings.alpaca_enabled() else "yfinance"
        if provider == "alpaca" and not settings.alpaca_enabled():
            logger.warning("Alpaca requested but keys missing; falling back to yfinance.")

    def snapshot(self, ticker: str) -> Snapshot | None:
        if self.provider == "alpaca":
            return self._snapshot_alpaca(ticker)
        return self._snapshot_yfinance(ticker)

    def _snapshot_yfinance(self, ticker: str) -> Snapshot | None:
        import yfinance as yf

        try:
            tk = yf.Ticker(ticker)
            # 1-minute bars including pre/post so we have a live-ish last price
            intraday = tk.history(period="1d", interval="1m", prepost=True)
            if intraday.empty:
                return None
            last = float(intraday["Close"].iloc[-1])
            returns = intraday["Close"].pct_change().dropna().tail(settings.PRICE_Z_LOOKBACK)
            recent = [float(x) for x in returns.tolist()]
            # prior regular-session close = last close of the previous day
            daily = tk.history(period="5d", interval="1d", prepost=False)
            prev_close = float(daily["Close"].iloc[-2]) if len(daily) >= 2 else float(daily["Close"].iloc[-1])
            return Snapshot(ticker.upper(), last, prev_close, recent)
        except Exception as exc:  # noqa: BLE001
            logger.warning("yfinance snapshot failed for %s: %s", ticker, exc)
            return None

    def _snapshot_alpaca(self, ticker: str) -> Snapshot | None:
        try:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests import StockBarsRequest, StockLatestTradeRequest
            from alpaca.data.timeframe import TimeFrame

            client = StockHistoricalDataClient(settings.ALPACA_API_KEY, settings.ALPACA_API_SECRET)
            latest = client.get_stock_latest_trade(
                StockLatestTradeRequest(symbol_or_symbols=ticker, feed=settings.ALPACA_DATA_FEED)
            )
            last = float(latest[ticker].price)
            bars = client.get_stock_bars(
                StockBarsRequest(symbol_or_symbols=ticker, timeframe=TimeFrame.Minute,
                                 limit=settings.PRICE_Z_LOOKBACK + 1, feed=settings.ALPACA_DATA_FEED)
            ).df
            closes = bars["close"].astype(float)
            recent = closes.pct_change().dropna().tolist()
            prev_close = float(closes.iloc[0])
            return Snapshot(ticker.upper(), last, prev_close, recent)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Alpaca snapshot failed for %s: %s", ticker, exc)
            return None
