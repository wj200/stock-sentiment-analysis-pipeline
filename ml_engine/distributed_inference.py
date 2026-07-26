"""Distributed FinBERT inference over Ray actors, with a Spark pandas-UDF path.

Two entry points are provided:

- `RayInferencePool`: a pool of Ray actors, each holding one loaded FinBERT
  model, used for ad-hoc/batch scoring of a list of texts (e.g. from a
  Kafka poll loop or a notebook).
- `score_dataframe_with_spark`: a PySpark `mapInPandas` transform that scores
  an entire Spark DataFrame of raw sentiment records in parallel across
  executors, used by `data_pipeline/spark_streaming.py`.
"""
import logging
from typing import Iterator, List

import pandas as pd
import ray
from pyspark.sql import DataFrame
from pyspark.sql.types import (
    DoubleType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from config import settings
from ml_engine.finbert_model import FinBertSentimentModel

logger = logging.getLogger(__name__)

SCORED_SCHEMA = StructType(
    [
        StructField("id", StringType(), False),
        StructField("ticker", StringType(), False),
        StructField("timestamp", TimestampType(), False),
        StructField("source", StringType(), False),
        StructField("text", StringType(), False),
        StructField("positive", DoubleType(), False),
        StructField("neutral", DoubleType(), False),
        StructField("negative", DoubleType(), False),
        StructField("sentiment_score", DoubleType(), False),
    ]
)


@ray.remote
class _FinBertActor:
    def __init__(self):
        self.model = FinBertSentimentModel()

    def score(self, texts: List[str]) -> List[dict]:
        results = self.model.predict_batch(texts)
        return [
            {
                "positive": r.positive,
                "neutral": r.neutral,
                "negative": r.negative,
                "sentiment_score": r.sentiment_score,
            }
            for r in results
        ]


class RayInferencePool:
    """Round-robins batches of text across N Ray actors, each with a loaded model."""

    def __init__(self, num_actors: int = settings.RAY_NUM_INFERENCE_ACTORS, ray_address: str | None = None):
        if not ray.is_initialized():
            try:
                ray.init(address=ray_address or settings.RAY_ADDRESS, ignore_reinit_error=True)
            except ConnectionError:
                logger.warning("No running Ray cluster found at '%s', starting a local one.", settings.RAY_ADDRESS)
                ray.init(ignore_reinit_error=True)

        self.actors = [_FinBertActor.remote() for _ in range(num_actors)]

    def score_texts(self, texts: List[str], batch_size: int = settings.FINBERT_BATCH_SIZE) -> List[dict]:
        if not texts:
            return []

        batches = [texts[i : i + batch_size] for i in range(0, len(texts), batch_size)]
        futures = [self.actors[i % len(self.actors)].score.remote(batch) for i, batch in enumerate(batches)]
        batch_results = ray.get(futures)

        flattened: List[dict] = []
        for batch_result in batch_results:
            flattened.extend(batch_result)
        return flattened

    def shutdown(self) -> None:
        ray.shutdown()


def _score_partition(pdf_iter: Iterator[pd.DataFrame]) -> Iterator[pd.DataFrame]:
    """Runs inside each Spark executor process; loads one FinBERT model per partition."""
    model = FinBertSentimentModel()
    for pdf in pdf_iter:
        if pdf.empty:
            yield pdf.assign(positive=[], neutral=[], negative=[], sentiment_score=[])
            continue
        results = model.predict_batch(pdf["text"].tolist())
        pdf = pdf.copy()
        pdf["positive"] = [r.positive for r in results]
        pdf["neutral"] = [r.neutral for r in results]
        pdf["negative"] = [r.negative for r in results]
        pdf["sentiment_score"] = [r.sentiment_score for r in results]
        yield pdf


def score_dataframe_with_spark(raw_df: DataFrame) -> DataFrame:
    """Scores a Spark DataFrame with columns (id, ticker, timestamp, source, text).

    Uses `mapInPandas` so each executor loads FinBERT exactly once per
    partition batch rather than once per row, which is what makes this
    tractable at streaming-microbatch scale.
    """
    return raw_df.mapInPandas(_score_partition, schema=SCORED_SCHEMA)
