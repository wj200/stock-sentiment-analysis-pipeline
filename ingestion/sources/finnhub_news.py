"""Real per-ticker company news via Finnhub (requires FINNHUB_API_KEY).

Also the retrieval source the Feature 2 price-move explainer reuses; here it is
used purely as an ingestion feed for sentiment scoring.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from ingestion.sources.base import Post, Source, clean_text, epoch_to_iso, make_id

logger = logging.getLogger(__name__)


class FinnhubNewsSource(Source):
    name = "finnhub_news"

    def __init__(self, tickers: list[str], api_key: str, lookback_days: int = 2,
                 max_per_ticker: int = 25):
        import finnhub  # lazy import

        self.tickers = [t.upper() for t in tickers]
        self.lookback_days = lookback_days
        self.max_per_ticker = max_per_ticker
        self.client = finnhub.Client(api_key=api_key)

    @retry(reraise=True, stop=stop_after_attempt(3),
           wait=wait_exponential_jitter(initial=1, max=10))
    def _company_news(self, ticker: str, frm: str, to: str):
        return self.client.company_news(ticker, _from=frm, to=to)

    def fetch(self) -> list[Post]:
        to = date.today()
        frm = to - timedelta(days=self.lookback_days)
        posts: list[Post] = []
        for ticker in self.tickers:
            try:
                items = self._company_news(ticker, frm.isoformat(), to.isoformat())
            except Exception as exc:  # noqa: BLE001
                logger.warning("Finnhub news error for %s: %s", ticker, exc)
                continue
            for it in (items or [])[: self.max_per_ticker]:
                headline = clean_text(it.get("headline"), max_len=400)
                if not headline:
                    continue
                summary = clean_text(it.get("summary"), max_len=1200)
                text = f"{headline}. {summary}".strip(". ") if summary else headline
                posts.append(
                    Post(
                        id=make_id("finnhub", it.get("id") or it.get("url"), ticker),
                        ticker=ticker,
                        timestamp=epoch_to_iso(it.get("datetime")),
                        source="finnhub_news",
                        text=text,
                    )
                )
        logger.info("Finnhub: fetched %d news items across %d tickers", len(posts), len(self.tickers))
        return posts
