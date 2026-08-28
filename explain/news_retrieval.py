"""Retrieve recent, real headlines for a ticker (Finnhub company news).

This is the grounding source for the Feature 2 price-move explainer: the LLM is
only allowed to explain a move from these retrieved items. If retrieval is empty
or Finnhub is not configured, the explainer says "no clear catalyst yet" rather
than inventing one.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NewsItem:
    title: str
    source: str
    url: str
    published: str  # ISO-8601 UTC


class NewsRetriever:
    def __init__(self, api_key: str):
        import finnhub  # lazy import

        self.client = finnhub.Client(api_key=api_key)

    @retry(reraise=True, stop=stop_after_attempt(3),
           wait=wait_exponential_jitter(initial=1, max=8))
    def _company_news(self, ticker: str, frm: str, to: str):
        return self.client.company_news(ticker, _from=frm, to=to)

    def recent(
        self,
        ticker: str,
        lookback_hours: int = settings.NEWS_LOOKBACK_HOURS,
        top_n: int = settings.NEWS_TOP_N,
    ) -> list[NewsItem]:
        to = date.today()
        frm = to - timedelta(days=max(1, lookback_hours // 24 + 1))
        try:
            items = self._company_news(ticker, frm.isoformat(), to.isoformat())
        except Exception as exc:  # noqa: BLE001 - empty retrieval degrades gracefully upstream
            logger.warning("News retrieval failed for %s: %s", ticker, exc)
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        out: list[NewsItem] = []
        seen: set[str] = set()
        for it in items or []:
            headline = (it.get("headline") or "").strip()
            if not headline or headline.lower() in seen:
                continue
            ts = it.get("datetime")
            published_dt = (
                datetime.fromtimestamp(ts, tz=timezone.utc) if ts else datetime.now(timezone.utc)
            )
            if published_dt < cutoff:
                continue
            seen.add(headline.lower())
            out.append(
                NewsItem(
                    title=headline[:300],
                    source=(it.get("source") or "news").strip()[:60],
                    url=(it.get("url") or "").strip(),
                    published=published_dt.isoformat(),
                )
            )
        out.sort(key=lambda n: n.published, reverse=True)
        return out[:top_n]


def get_retriever() -> NewsRetriever | None:
    if settings.finnhub_enabled():
        return NewsRetriever(settings.FINNHUB_API_KEY)
    logger.info("News retrieval disabled (no FINNHUB_API_KEY); price-move explanations degrade.")
    return None
