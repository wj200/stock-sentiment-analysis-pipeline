"""Keyless, real financial-news RSS ingestion (no credentials required).

Default feed is Google News, queried per ticker, which is a real, public,
credential-free news aggregator. Each RSS entry becomes one Post tagged with
the ticker whose query produced it, so no downstream extraction is needed for
this source. A per-ticker Yahoo Finance headline feed is included as an
alternate/secondary template.
"""
from __future__ import annotations

import logging
from urllib.parse import quote_plus

import feedparser
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from ingestion.sources.base import Post, Source, clean_text, make_id, struct_time_to_iso

logger = logging.getLogger(__name__)

# Real, keyless feeds. {q} = URL-encoded query, {ticker} = raw symbol.
GOOGLE_NEWS = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
YAHOO_HEADLINE = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"

DEFAULT_FEEDS = (GOOGLE_NEWS,)


class RSSSource(Source):
    name = "rss"

    def __init__(
        self,
        tickers: list[str],
        feeds: tuple[str, ...] = DEFAULT_FEEDS,
        query_suffix: str = "stock",
        max_per_ticker: int = 25,
    ):
        self.tickers = [t.upper() for t in tickers]
        self.feeds = feeds
        self.query_suffix = query_suffix
        self.max_per_ticker = max_per_ticker

    @retry(reraise=True, stop=stop_after_attempt(3),
           wait=wait_exponential_jitter(initial=1, max=10))
    def _parse(self, url: str):
        # feedparser fetches over HTTP; a bozo (malformed) feed still returns
        # whatever entries it could parse, so we only retry on a hard failure.
        parsed = feedparser.parse(url)
        if getattr(parsed, "status", 200) >= 400:
            raise RuntimeError(f"RSS fetch failed: {url} -> HTTP {parsed.status}")
        return parsed

    def _feed_url(self, template: str, ticker: str) -> str:
        query = f'"{ticker}" {self.query_suffix}'.strip()
        return template.format(q=quote_plus(query), ticker=ticker)

    def fetch(self) -> list[Post]:
        posts: list[Post] = []
        for ticker in self.tickers:
            for template in self.feeds:
                url = self._feed_url(template, ticker)
                try:
                    parsed = self._parse(url)
                except Exception as exc:  # noqa: BLE001 - one feed failing must not kill the batch
                    logger.warning("RSS fetch error for %s (%s): %s", ticker, url, exc)
                    continue
                for entry in parsed.entries[: self.max_per_ticker]:
                    title = clean_text(entry.get("title"), max_len=400)
                    if not title:
                        continue
                    summary = clean_text(entry.get("summary"), max_len=1200)
                    text = f"{title}. {summary}".strip(". ") if summary else title
                    guid = entry.get("id") or entry.get("link") or title
                    posts.append(
                        Post(
                            id=make_id("rss", ticker, guid),
                            ticker=ticker,
                            timestamp=struct_time_to_iso(entry.get("published_parsed")),
                            source="rss",
                            text=text,
                        )
                    )
        logger.info("RSS: fetched %d items across %d tickers", len(posts), len(self.tickers))
        return posts
