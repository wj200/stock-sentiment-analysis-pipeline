"""Real Reddit ingestion via PRAW (requires Reddit app credentials).

Read-only mode: a "script" app's client id + secret is enough to read public
subreddits; no user login is needed. New submissions from the configured
subreddits are scanned for tickers in the tracked universe, producing one Post
per (submission x matched ticker).
"""
from __future__ import annotations

import logging

from ingestion.sources.base import Post, Source, clean_text, epoch_to_iso, make_id
from ingestion.sources.ticker_extract import extract_tickers

logger = logging.getLogger(__name__)


class RedditSource(Source):
    name = "reddit"

    def __init__(
        self,
        tickers: list[str],
        subreddits: list[str],
        client_id: str,
        client_secret: str,
        user_agent: str,
        limit_per_sub: int = 60,
    ):
        import praw  # imported lazily so the package imports without praw installed

        self.tickers = [t.upper() for t in tickers]
        self.subreddits = subreddits
        self.limit_per_sub = limit_per_sub
        self.reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
            check_for_async=False,
        )
        self.reddit.read_only = True

    def fetch(self) -> list[Post]:
        posts: list[Post] = []
        for sub in self.subreddits:
            try:
                submissions = self.reddit.subreddit(sub).new(limit=self.limit_per_sub)
                for s in submissions:
                    body = f"{s.title}. {getattr(s, 'selftext', '') or ''}"
                    text = clean_text(body, max_len=2000)
                    tickers = extract_tickers(text, self.tickers)
                    for tk in tickers:
                        posts.append(
                            Post(
                                id=make_id("reddit", s.id, tk),
                                ticker=tk,
                                timestamp=epoch_to_iso(getattr(s, "created_utc", None)),
                                source="reddit",
                                text=text,
                            )
                        )
            except Exception as exc:  # noqa: BLE001 - one subreddit failing must not kill the batch
                logger.warning("Reddit fetch error for r/%s: %s", sub, exc)
                continue
        logger.info("Reddit: produced %d ticker-tagged posts from %d subreddits",
                    len(posts), len(self.subreddits))
        return posts
