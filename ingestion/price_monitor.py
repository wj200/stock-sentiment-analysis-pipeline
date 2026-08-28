"""Feature 2: extended-hours price-move monitor -> Kafka `stock-price-alerts`.

Polls real quotes for the tracked universe (keyless yfinance by default, Alpaca
when keyed), runs the pure `evaluate_move` detector, and emits one alert per
significant pre/post-market move. Detection is deterministic and model-free, so
it fires whether or not the news API or LLM is available; the dispatcher attaches
the grounded explanation and fans out to watchers.

De-dup key is (ticker, session, direction, ET-date) so a move is announced once
per session; the downstream dispatcher de-dups again before sending.
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone

from config import settings
from ingestion.kafka_utils import build_producer, delivery_report, ensure_topics, serialize
from ingestion.sources.base import bounded_seen
from market.quotes import ET, MarketQuotes, evaluate_move

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def poll_once(producer, quotes: MarketQuotes, seen: bounded_seen, topic: str,
              tickers=None, now: datetime | None = None) -> int:
    tickers = tickers or settings.TICKERS
    now = now or datetime.now(timezone.utc)
    et_date = now.astimezone(ET).date().isoformat()
    emitted = 0
    for ticker in tickers:
        snap = quotes.snapshot(ticker)
        if snap is None:
            continue
        alert = evaluate_move(ticker, snap.last, snap.prev_close, snap.recent_returns, now=now)
        if alert is None:
            continue
        key = f"{alert.ticker}:{alert.session}:{alert.direction}:{et_date}"
        if key in seen:
            continue
        seen.add(key)
        payload = {
            "ticker": alert.ticker, "pct_move": alert.pct_move, "direction": alert.direction,
            "ret_z": alert.ret_z, "session": alert.session, "ref_price": alert.ref_price,
            "last": alert.last, "ts": alert.ts,
        }
        producer.produce(topic, key=alert.ticker.encode("utf-8"),
                         value=serialize(payload), callback=delivery_report)
        emitted += 1
        logger.info("PRICE ALERT %s %+.2f%% (%s, z=%.2f)",
                    alert.ticker, alert.pct_move, alert.session, alert.ret_z)
    producer.poll(0)
    producer.flush(10)
    return emitted


def run(poll_seconds: int = 60, once: bool = False,
        topic: str = settings.KAFKA_TOPIC_PRICE_ALERTS,
        bootstrap_servers: str = settings.KAFKA_BOOTSTRAP_SERVERS) -> None:
    settings.ensure_data_dirs()
    ensure_topics(bootstrap_servers=bootstrap_servers)
    quotes = MarketQuotes()
    producer = build_producer(bootstrap_servers=bootstrap_servers)
    seen = bounded_seen(maxlen=10_000)
    logger.info("Price monitor started (provider=%s, universe=%s)", quotes.provider, settings.TICKERS)
    try:
        while True:
            n = poll_once(producer, quotes, seen, topic)
            if n:
                logger.info("Emitted %d price alert(s) this cycle", n)
            if once:
                break
            time.sleep(poll_seconds)
    except KeyboardInterrupt:
        logger.info("Price monitor interrupted.")
    finally:
        producer.flush(10)


def main() -> None:
    p = argparse.ArgumentParser(description="Extended-hours price-move monitor -> Kafka")
    p.add_argument("--poll", type=int, default=60)
    p.add_argument("--once", action="store_true")
    args = p.parse_args()
    run(poll_seconds=args.poll, once=args.once)


if __name__ == "__main__":
    main()
