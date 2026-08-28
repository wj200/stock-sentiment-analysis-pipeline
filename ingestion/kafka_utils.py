"""Kafka topic definitions, (de)serialization helpers, and admin utilities."""
import json
import logging
from typing import Any, Dict, Optional

from confluent_kafka import Consumer, KafkaError, Producer
from confluent_kafka.admin import AdminClient, NewTopic

from config import settings

logger = logging.getLogger(__name__)

RAW_SENTIMENT_SCHEMA_FIELDS = ("id", "ticker", "timestamp", "source", "text")
SCORED_SENTIMENT_SCHEMA_FIELDS = RAW_SENTIMENT_SCHEMA_FIELDS + (
    "positive",
    "neutral",
    "negative",
    "sentiment_score",
)


def ensure_topics(
    bootstrap_servers: str = settings.KAFKA_BOOTSTRAP_SERVERS,
    num_partitions: int = 3,
    replication_factor: int = 1,
) -> None:
    """Idempotently create the topics this pipeline depends on."""
    admin = AdminClient({"bootstrap.servers": bootstrap_servers})
    existing = admin.list_topics(timeout=10).topics.keys()

    topics_to_create = [
        NewTopic(name, num_partitions=num_partitions, replication_factor=replication_factor)
        for name in (
            settings.KAFKA_TOPIC_RAW_SENTIMENT,
            settings.KAFKA_TOPIC_SCORED_SENTIMENT,
            settings.KAFKA_TOPIC_PRICE_ALERTS,
            settings.KAFKA_TOPIC_MACRO_EVENTS,
        )
        if name not in existing
    ]

    if not topics_to_create:
        logger.info("All required Kafka topics already exist.")
        return

    futures = admin.create_topics(topics_to_create)
    for topic, future in futures.items():
        try:
            future.result()
            logger.info("Created topic %s", topic)
        except Exception as exc:  # noqa: BLE001 - surface any admin error with context
            logger.warning("Could not create topic %s: %s", topic, exc)


def serialize(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, default=str).encode("utf-8")


def deserialize(raw: bytes) -> Dict[str, Any]:
    return json.loads(raw.decode("utf-8"))


def validate_raw_sentiment(payload: Dict[str, Any]) -> bool:
    return all(field in payload for field in RAW_SENTIMENT_SCHEMA_FIELDS)


def build_producer(bootstrap_servers: str = settings.KAFKA_BOOTSTRAP_SERVERS) -> Producer:
    return Producer(
        {
            "bootstrap.servers": bootstrap_servers,
            "acks": "all",
            "retries": 5,
            "linger.ms": 50,
            "compression.type": "snappy",
        }
    )


def build_consumer(
    group_id: str = settings.KAFKA_CONSUMER_GROUP,
    bootstrap_servers: str = settings.KAFKA_BOOTSTRAP_SERVERS,
    auto_offset_reset: str = "earliest",
) -> Consumer:
    return Consumer(
        {
            "bootstrap.servers": bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": auto_offset_reset,
            "enable.auto.commit": True,
        }
    )


def delivery_report(err: Optional[KafkaError], msg) -> None:
    if err is not None:
        logger.error("Delivery failed for record %s: %s", msg.key(), err)
    else:
        logger.debug("Record delivered to %s [%s] @ %s", msg.topic(), msg.partition(), msg.offset())
