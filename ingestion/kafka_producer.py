"""Simulated live stream of ticker-tagged forum/news posts published to Kafka.

Mimics the shape of real WallStreetBets submissions and financial news wires
closely enough to exercise the full pipeline (ingestion -> Spark -> Delta ->
FinBERT -> backtest -> dashboard) without requiring live Reddit/News API
credentials. Swap `_generate_post` for a real Reddit/RSS client when ready.
"""
import argparse
import logging
import random
import time
import uuid
from datetime import datetime, timezone

from config import settings
from ingestion.kafka_utils import build_producer, delivery_report, ensure_topics, serialize

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_BULLISH_TEMPLATES = [
    "{ticker} just smashed earnings expectations, guidance looks incredible for next quarter.",
    "Loading up on {ticker} calls, the technical breakout above resistance is undeniable.",
    "{ticker} announced a massive buyback program, insiders are clearly confident.",
    "Analysts upgrading {ticker} price target again, momentum is unreal right now.",
    "{ticker} margins expanding faster than the street modeled, this is a screaming buy.",
    "Institutional accumulation in {ticker} is off the charts this week, bullish af.",
]

_BEARISH_TEMPLATES = [
    "{ticker} missed on revenue and cut full-year guidance, this is ugly.",
    "Dumping my {ticker} position, the debt load is starting to look unsustainable.",
    "{ticker} facing a regulatory probe, expect the stock to bleed for weeks.",
    "Insider selling at {ticker} just spiked, red flag for anyone still holding.",
    "{ticker} guidance cut is a disaster, downgrading my price target hard.",
    "Short interest building in {ticker}, the chart is breaking down badly.",
]

_NEUTRAL_TEMPLATES = [
    "{ticker} trading roughly in line with sector peers ahead of tomorrow's print.",
    "Not much news on {ticker} today, holding steady near the 50-day average.",
    "{ticker} management reiterated prior guidance on the investor call, no surprises.",
    "Volume in {ticker} is thin today, waiting for more catalysts before adding.",
    "{ticker} options market pricing in a modest move around next week's event.",
]

_TEMPLATE_BUCKETS = (
    ("bullish", _BULLISH_TEMPLATES),
    ("bearish", _BEARISH_TEMPLATES),
    ("neutral", _NEUTRAL_TEMPLATES),
)


def _generate_post(tickers: list[str]) -> dict:
    ticker = random.choice(tickers)
    _, templates = random.choice(_TEMPLATE_BUCKETS)
    text = random.choice(templates).format(ticker=ticker)
    return {
        "id": str(uuid.uuid4()),
        "ticker": ticker,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": random.choice(settings.SOURCES),
        "text": text,
    }


def run(rate_per_sec: float, max_messages: int | None, topic: str, bootstrap_servers: str) -> None:
    ensure_topics(bootstrap_servers=bootstrap_servers)
    producer = build_producer(bootstrap_servers=bootstrap_servers)

    sent = 0
    interval = 1.0 / rate_per_sec if rate_per_sec > 0 else 0
    try:
        while max_messages is None or sent < max_messages:
            payload = _generate_post(settings.TICKERS)
            producer.produce(
                topic,
                key=payload["ticker"].encode("utf-8"),
                value=serialize(payload),
                callback=delivery_report,
            )
            producer.poll(0)
            sent += 1
            if sent % 50 == 0:
                logger.info("Produced %d messages to %s", sent, topic)
            if interval:
                time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("Producer interrupted by user.")
    finally:
        producer.flush(10)
        logger.info("Flushed producer, total sent=%d", sent)


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulated stock news/forum Kafka producer")
    parser.add_argument("--rate", type=float, default=5.0, help="messages per second")
    parser.add_argument("--max-messages", type=int, default=None, help="stop after N messages")
    parser.add_argument("--topic", type=str, default=settings.KAFKA_TOPIC_RAW_SENTIMENT)
    parser.add_argument("--bootstrap-servers", type=str, default=settings.KAFKA_BOOTSTRAP_SERVERS)
    args = parser.parse_args()

    run(
        rate_per_sec=args.rate,
        max_messages=args.max_messages,
        topic=args.topic,
        bootstrap_servers=args.bootstrap_servers,
    )


if __name__ == "__main__":
    main()
