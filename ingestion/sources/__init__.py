"""Real ingestion sources for the sentiment pipeline.

Every source yields `Post` records in the raw_sentiment schema
(id, ticker, timestamp, source, text) pulled from a REAL provider — there is
no synthetic/generated data anywhere in this package.

Sources:
  - RSSSource        keyless financial-news RSS (Google News / Yahoo). No credentials.
  - RedditSource     PRAW over configured subreddits. Requires Reddit app credentials.
  - FinnhubNewsSource company news per ticker. Requires FINNHUB_API_KEY.
"""
from ingestion.sources.base import Post, Source, bounded_seen, clean_text, make_id, now_utc_iso

__all__ = ["Post", "Source", "make_id", "now_utc_iso", "clean_text", "bounded_seen"]
