"""Live ingestion producer: real news/forum posts -> Kafka `stock-raw-sentiment`.

Pulls ONLY from real data sources (no synthetic/generated content):
  - rss           keyless financial-news RSS (Google News / Yahoo) — always available
  - reddit        PRAW over configured subreddits — needs Reddit app credentials
  - finnhub_news  per-ticker company news — needs FINNHUB_API_KEY

Which sources are active is controlled by INGEST_SOURCES (+ the relevant
credentials). Each poll cycle fetches from every active source, de-duplicates
against items already published this run, and produces the new posts keyed by
ticker so Kafka preserves per-ticker ordering. Downstream, Spark
`dropDuplicates(["id"])` + Delta MERGE make replays idempotent.
"""
from __future__ import annotations

import argparse
import logging
import time

from config import settings
from ingestion.kafka_utils import build_producer, delivery_report, ensure_topics, serialize
from ingestion.sources.base import Source, bounded_seen
from ingestion.sources.finnhub_news import FinnhubNewsSource
from ingestion.sources.rss_source import RSSSource

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def build_sources() -> list[Source]:
    """Instantiate the active, credentialed real sources; log what is skipped."""
    active = settings.INGEST_SOURCES
    sources: list[Source] = []

    if "rss" in active:
        sources.append(RSSSource(settings.TICKERS))

    if "reddit" in active:
        if settings.reddit_enabled():
            from ingestion.sources.reddit_source import RedditSource

            sources.append(
                RedditSource(
                    tickers=settings.TICKERS,
                    subreddits=settings.REDDIT_SUBREDDITS,
                    client_id=settings.REDDIT_CLIENT_ID,
                    client_secret=settings.REDDIT_CLIENT_SECRET,
                    user_agent=settings.REDDIT_USER_AGENT,
                )
            )
        else:
            logger.warning(
                "INGEST_SOURCES requests 'reddit' but Reddit credentials are missing "
                "(set REDDIT_CLIENT_ID/SECRET/USER_AGENT). Skipping Reddit."
            )

    if "finnhub_news" in active:
        if settings.finnhub_enabled():
            sources.append(FinnhubNewsSource(settings.TICKERS, settings.FINNHUB_API_KEY))
        else:
            logger.warning(
                "INGEST_SOURCES requests 'finnhub_news' but FINNHUB_API_KEY is missing. "
                "Skipping Finnhub news."
            )

    return sources


def poll_once(producer, sources: list[Source], seen: bounded_seen, topic: str) -> int:
    published = 0
    for src in sources:
        try:
            batch = src.fetch()
        except Exception:  # noqa: BLE001 - a source failing must not stop the loop
            logger.exception("Source %s failed this cycle", getattr(src, "name", src))
            continue
        for post in seen.filter_new(batch):
            producer.produce(
                topic,
                key=post.ticker.encode("utf-8"),
                value=serialize(post.to_payload()),
                callback=delivery_report,
            )
            published += 1
        producer.poll(0)
    producer.flush(15)
    return published


def run(
    poll_seconds: int = settings.INGEST_POLL_SECONDS,
    once: bool = False,
    topic: str = settings.KAFKA_TOPIC_RAW_SENTIMENT,
    bootstrap_servers: str = settings.KAFKA_BOOTSTRAP_SERVERS,
) -> None:
    settings.ensure_data_dirs()
    ensure_topics(bootstrap_servers=bootstrap_servers)

    sources = build_sources()
    if not sources:
        raise SystemExit(
            "No ingestion sources are active. Set INGEST_SOURCES (and any required "
            "credentials) — see .env.example. 'rss' works with no credentials."
        )
    logger.info("Active ingestion sources: %s", [s.name for s in sources])

    producer = build_producer(bootstrap_servers=bootstrap_servers)
    seen = bounded_seen()
    total = 0
    try:
        while True:
            n = poll_once(producer, sources, seen, topic)
            total += n
            logger.info("Poll cycle published %d new posts (total=%d) to %s", n, total, topic)
            if once:
                break
            time.sleep(poll_seconds)
    except KeyboardInterrupt:
        logger.info("Producer interrupted by user.")
    finally:
        producer.flush(15)
        for s in sources:
            s.close()
        logger.info("Producer stopped, total published=%d", total)


def main() -> None:
    parser = argparse.ArgumentParser(description="Real news/forum -> Kafka ingestion producer")
    parser.add_argument("--poll", type=int, default=settings.INGEST_POLL_SECONDS,
                        help="seconds between poll cycles")
    parser.add_argument("--once", action="store_true", help="run a single poll cycle and exit")
    parser.add_argument("--topic", type=str, default=settings.KAFKA_TOPIC_RAW_SENTIMENT)
    parser.add_argument("--bootstrap-servers", type=str, default=settings.KAFKA_BOOTSTRAP_SERVERS)
    args = parser.parse_args()
    run(poll_seconds=args.poll, once=args.once, topic=args.topic,
        bootstrap_servers=args.bootstrap_servers)


if __name__ == "__main__":
    main()
