"""Structured Streaming job: Kafka (`stock-raw-sentiment`) -> FinBERT -> Delta Lake.

Each micro-batch is:
  1. parsed from Kafka's raw JSON value into the raw sentiment schema,
  2. persisted verbatim to the `raw_sentiment` Delta table (full audit trail),
  3. scored in parallel with FinBERT via a pandas UDF (`mapInPandas`), and
  4. merged into the `scored_sentiment` Delta table keyed on record `id`.

`mapInPandas` is not supported directly on a streaming DataFrame, so scoring
happens inside `foreachBatch`, where each micro-batch is a plain static
DataFrame.
"""
import argparse
import logging

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

from config import settings
from data_pipeline.delta_writer import get_spark, upsert_scored_sentiment, write_raw_sentiment
from ml_engine.distributed_inference import score_dataframe_with_spark

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

RAW_KAFKA_VALUE_SCHEMA = StructType(
    [
        StructField("id", StringType(), False),
        StructField("ticker", StringType(), False),
        StructField("timestamp", StringType(), False),
        StructField("source", StringType(), False),
        StructField("text", StringType(), False),
    ]
)


def read_kafka_stream(spark: SparkSession, topic: str, bootstrap_servers: str) -> DataFrame:
    raw = (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", bootstrap_servers)
        .option("subscribe", topic)
        .option("startingOffsets", "latest")
        .option("failOnDataLoss", "false")
        .load()
    )

    parsed = raw.select(
        F.from_json(F.col("value").cast("string"), RAW_KAFKA_VALUE_SCHEMA).alias("payload")
    ).select("payload.*")

    return parsed.withColumn("timestamp", F.to_timestamp("timestamp"))


def process_batch(batch_df: DataFrame, batch_id: int, spark: SparkSession) -> None:
    if batch_df.rdd.isEmpty():
        logger.info("Batch %d is empty, skipping.", batch_id)
        return

    batch_df = batch_df.dropDuplicates(["id"]).cache()
    row_count = batch_df.count()
    logger.info("Batch %d: processing %d raw sentiment records", batch_id, row_count)

    write_raw_sentiment(batch_df)

    scored_df = score_dataframe_with_spark(batch_df)
    upsert_scored_sentiment(spark, scored_df)

    batch_df.unpersist()


def run(topic: str = settings.KAFKA_TOPIC_RAW_SENTIMENT, bootstrap_servers: str = settings.KAFKA_BOOTSTRAP_SERVERS) -> None:
    settings.ensure_data_dirs()
    spark = get_spark("spark-streaming-sentiment", with_kafka=True)
    stream_df = read_kafka_stream(spark, topic, bootstrap_servers)

    query = (
        stream_df.writeStream.foreachBatch(lambda df, batch_id: process_batch(df, batch_id, spark))
        .option("checkpointLocation", str(settings.CHECKPOINT_ROOT / "raw_sentiment_stream"))
        .trigger(processingTime="30 seconds")
        .start()
    )

    logger.info("Streaming query started, awaiting termination...")
    query.awaitTermination()


def main() -> None:
    parser = argparse.ArgumentParser(description="Kafka -> FinBERT -> Delta Lake streaming job")
    parser.add_argument("--topic", type=str, default=settings.KAFKA_TOPIC_RAW_SENTIMENT)
    parser.add_argument("--bootstrap-servers", type=str, default=settings.KAFKA_BOOTSTRAP_SERVERS)
    args = parser.parse_args()
    run(topic=args.topic, bootstrap_servers=args.bootstrap_servers)


if __name__ == "__main__":
    main()
