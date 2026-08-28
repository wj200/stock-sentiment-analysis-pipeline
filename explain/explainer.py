"""Orchestrates retrieval -> grounded generation -> validation -> degrade.

Never fabricates: no sources -> "no catalyst"; no LLM / LLM error / guardrail
rejection -> a non-LLM summary built from the retrieved headlines/numbers.
`grounded` records whether the returned text came from a validated LLM answer.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field

from config import settings
from explain import prompts
from explain.llm_provider import LLMProvider, model_for
from explain.news_retrieval import NewsItem, NewsRetriever

logger = logging.getLogger(__name__)


@dataclass
class Explanation:
    text: str
    sources: list[NewsItem] = field(default_factory=list)
    grounded: bool = False  # True only if a validated LLM answer produced `text`

    def source_line(self) -> str:
        if not self.sources:
            return ""
        return " ".join(f"[{i}] {s.source}" for i, s in enumerate(self.sources, start=1))


class _TTLCache:
    def __init__(self, ttl: int):
        self.ttl = ttl
        self._d: dict[str, tuple[float, Explanation]] = {}
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            hit = self._d.get(key)
            if hit and (time.monotonic() - hit[0]) < self.ttl:
                return hit[1]
        return None

    def put(self, key: str, val: Explanation):
        with self._lock:
            self._d[key] = (time.monotonic(), val)


_cache = _TTLCache(settings.LLM_CACHE_SECONDS)


def _sources_key(items: list[NewsItem]) -> str:
    h = hashlib.sha1("|".join(i.url or i.title for i in items).encode("utf-8")).hexdigest()[:12]
    return h


def _degraded_from_items(items: list[NewsItem]) -> Explanation:
    if not items:
        return Explanation(text=prompts.NO_CATALYST, sources=[], grounded=False)
    top = items[0]
    return Explanation(text=f"Top headline: {top.title} ({top.source}).", sources=items[:2], grounded=False)


def explain_price_move(
    ticker: str,
    pct: float,
    session: str,
    *,
    retriever: NewsRetriever | None,
    provider: LLMProvider | None,
) -> Explanation:
    items = retriever.recent(ticker) if retriever else []
    cache_key = f"price:{ticker}:{session}:{_sources_key(items)}"
    cached = _cache.get(cache_key)
    if cached:
        return cached

    if not items:
        result = Explanation(text=prompts.NO_CATALYST, sources=[], grounded=False)
        _cache.put(cache_key, result)
        return result

    if provider is None:
        return _degraded_from_items(items)  # not cached: LLM may appear later

    system, user = prompts.build_price_prompt(ticker, pct, session, items)
    try:
        text = provider.complete(system, user, model=model_for("price"),
                                 max_tokens=settings.LLM_MAX_WORDS * 6)
    except Exception as exc:  # noqa: BLE001 - degrade, never surface an error to users
        logger.warning("Price explain LLM error for %s: %s", ticker, exc)
        return _degraded_from_items(items)

    ok, reason = prompts.validate(text, had_sources=True)
    if not ok:
        logger.warning("Price explanation rejected (%s) for %s; degrading.", reason, ticker)
        return _degraded_from_items(items)

    result = Explanation(text=text, sources=items, grounded=True)
    _cache.put(cache_key, result)
    return result


def explain_macro(
    label: str,
    actual,
    consensus,
    prior,
    surprise,
    *,
    items: list[NewsItem] | None = None,
    provider: LLMProvider | None,
) -> Explanation:
    items = items or []
    cache_key = f"macro:{label}:{actual}:{consensus}:{prior}"
    cached = _cache.get(cache_key)
    if cached:
        return cached

    factual = (
        f"{label}: actual {actual}"
        + (f", consensus {consensus}" if consensus is not None else "")
        + f", prior {prior}."
    )

    if provider is None:
        return Explanation(text=factual, sources=items[:2], grounded=False)

    system, user = prompts.build_macro_prompt(label, actual, consensus, prior, surprise, items)
    try:
        text = provider.complete(system, user, model=model_for("macro"),
                                 max_tokens=settings.LLM_MAX_WORDS * 6)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Macro explain LLM error for %s: %s", label, exc)
        return Explanation(text=factual, sources=items[:2], grounded=False)

    ok, reason = prompts.validate(text, had_sources=bool(items))
    if not ok:
        logger.warning("Macro explanation rejected (%s) for %s; degrading.", reason, label)
        return Explanation(text=factual, sources=items[:2], grounded=False)

    result = Explanation(text=text, sources=items, grounded=True)
    _cache.put(cache_key, result)
    return result
