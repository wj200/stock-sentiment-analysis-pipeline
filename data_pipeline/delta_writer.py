"""Delta Lake schema enforcement, partitioning, and upsert helpers.

All writers here are idempotent w.r.t. the `id` primary key (for sentiment
records) or `(ticker, timestamp)` (for market bars) via `MERGE`, so replaying
a Kafka partition or re-running a backfill never produces duplicate rows.
"""
import logging

from delta import configure_spark_with_delta_pip
from delta.tables import DeltaTable
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from config import settings

logger = logging.getLogger(__name__)

KAFKA_SQL_PACKAGE = "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.1"


def get_spark(app_name: str = "stock-sentiment-pipeline", with_kafka: bool = False) -> SparkSession:
    """Builds (or fetches) a SparkSession configured with the Delta Lake extension.

    `with_kafka=True` additionally pulls in the Spark Structured Streaming
    Kafka source connector, needed only by `data_pipeline/spark_streaming.py`.
    """
    builder = (
        SparkSession.builder.appName(app_name)
        .config("spark.sql.session.timeZone", "UTC")
    )
    if with_kafka:
        builder = builder.config("spark.jars.packages", KAFKA_SQL_PACKAGE)

    spark = configure_spark_with_delta_pip(builder).getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    return spark


def _with_date_partition(df: DataFrame, timestamp_col: str = "timestamp") -> DataFrame:
    return df.withColumn("date", F.to_date(F.col(timestamp_col)))


def write_raw_sentiment(df: DataFrame, table_path: str = settings.RAW_SENTIMENT_TABLE) -> None:
    """Appends raw (unscored) sentiment records, partitioned by date/ticker."""
    df = _with_date_partition(df)
    (
        df.write.format("delta")
        .mode("append")
        .partitionBy("date", "ticker")
        .option("mergeSchema", "true")
        .save(table_path)
    )
    logger.info("Wrote %d raw sentiment rows to %s", df.count(), table_path)


def upsert_scored_sentiment(spark: SparkSession, df: DataFrame, table_path: str = settings.SCORED_SENTIMENT_TABLE) -> None:
    """Merges FinBERT-scored sentiment rows into Delta, keyed on `id`."""
    df = _with_date_partition(df)

    if not DeltaTable.isDeltaTable(spark, table_path):
        (
            df.write.format("delta")
            .mode("overwrite")
            .partitionBy("date", "ticker")
            .save(table_path)
        )
        logger.info("Initialized scored sentiment Delta table at %s", table_path)
        return

    target = DeltaTable.forPath(spark, table_path)
    (
        target.alias("t")
        .merge(df.alias("s"), "t.id = s.id")
        .whenMatchedUpdateAll()
        .whenNotMatchedInsertAll()
        .execute()
    )
    logger.info("Merged %d scored sentiment rows into %s", df.count(), table_path)


def upsert_market_prices(spark: SparkSession, df: DataFrame, table_path: str = settings.MARKET_PRICES_TABLE) -> None:
    """Merges OHLCV bars into Delta, keyed on (ticker, timestamp)."""
    df = _with_date_partition(df)

    if not DeltaTable.isDeltaTable(spark, table_path):
        (
            df.write.format("delta")
            .mode("overwrite")
            .partitionBy("date", "ticker")
            .save(table_path)
        )
        logger.info("Initialized market prices Delta table at %s", table_path)
        return

    target = DeltaTable.forPath(spark, table_path)
    (
        target.alias("t")
        .merge(df.alias("s"), "t.ticker = s.ticker AND t.timestamp = s.timestamp")
        .whenMatchedUpdateAll()
        .whenNotMatchedInsertAll()
        .execute()
    )
    logger.info("Merged %d market price rows into %s", df.count(), table_path)


def read_table(spark: SparkSession, table_path: str) -> DataFrame:
    return spark.read.format("delta").load(table_path)


def optimize_table(spark: SparkSession, table_path: str, zorder_cols: list[str] | None = None) -> None:
    """Compacts small files produced by frequent micro-batch appends."""
    if not DeltaTable.isDeltaTable(spark, table_path):
        logger.warning("Skipping OPTIMIZE: %s is not a Delta table yet.", table_path)
        return

    table = DeltaTable.forPath(spark, table_path)
    if zorder_cols:
        cols = ", ".join(zorder_cols)
        spark.sql(f"OPTIMIZE delta.`{table_path}` ZORDER BY ({cols})")
    else:
        table.optimize().executeCompaction()
    logger.info("Optimized Delta table at %s", table_path)
