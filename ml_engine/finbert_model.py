"""FinBERT (yiyanghkust/finbert-tone) model loading and single/batch inference."""
import logging
from dataclasses import dataclass
from typing import List

import torch
import torch.nn.functional as F
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from config import settings

logger = logging.getLogger(__name__)

# yiyanghkust/finbert-tone label order: 0=neutral, 1=positive, 2=negative
_LABEL_ORDER = ("neutral", "positive", "negative")


@dataclass
class SentimentResult:
    text: str
    positive: float
    neutral: float
    negative: float

    @property
    def sentiment_score(self) -> float:
        """Net sentiment score: P(positive) - P(negative), in [-1, 1]."""
        return self.positive - self.negative


class FinBertSentimentModel:
    """Thin, device-aware wrapper around the FinBERT tone-classification model.

    Designed to be instantiated once per worker (Ray actor / Spark executor)
    since model + tokenizer loading is the expensive part of inference.
    """

    def __init__(
        self,
        model_name: str = settings.FINBERT_MODEL_NAME,
        max_length: int = settings.FINBERT_MAX_LENGTH,
        device: str | None = None,
    ):
        self.model_name = model_name
        self.max_length = max_length
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")

        logger.info("Loading FinBERT model '%s' on device=%s", model_name, self.device)
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name)
        self.model.to(self.device)
        self.model.eval()

    @torch.inference_mode()
    def predict_batch(self, texts: List[str]) -> List[SentimentResult]:
        if not texts:
            return []

        inputs = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=self.max_length,
            return_tensors="pt",
        ).to(self.device)

        logits = self.model(**inputs).logits
        probs = F.softmax(logits, dim=-1).cpu().numpy()

        results = []
        for text, row in zip(texts, probs):
            scores = dict(zip(_LABEL_ORDER, row.tolist()))
            results.append(
                SentimentResult(
                    text=text,
                    positive=scores["positive"],
                    neutral=scores["neutral"],
                    negative=scores["negative"],
                )
            )
        return results

    def predict(self, text: str) -> SentimentResult:
        return self.predict_batch([text])[0]


_singleton: FinBertSentimentModel | None = None


def get_shared_model() -> FinBertSentimentModel:
    """Process-local singleton so batch jobs and UDFs don't reload weights per call."""
    global _singleton
    if _singleton is None:
        _singleton = FinBertSentimentModel()
    return _singleton
