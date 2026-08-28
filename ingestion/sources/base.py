"""Shared types and helpers for real ingestion sources."""
from __future__ import annotations

import hashlib
import html
import re
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Iterable

# raw_sentiment schema fields, in order (see ingestion/kafka_utils.py).
RAW_FIELDS = ("id", "ticker", "timestamp", "source", "text")

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class Post:
    """One real, ticker-tagged text record ready to publish to Kafka."""

    id: str
    ticker: str
    timestamp: str  # ISO-8601 UTC
    source: str  # one of settings.SOURCES
    text: str

    def to_payload(self) -> dict:
        return asdict(self)


def make_id(*parts: object) -> str:
    """Stable content id so re-fetching the same item is idempotent downstream."""
    raw = "|".join(str(p) for p in parts if p is not None)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def epoch_to_iso(epoch: float | int | None) -> str:
    if not epoch:
        return now_utc_iso()
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()


def struct_time_to_iso(st) -> str:
    """Convert a feedparser time.struct_time (UTC) to ISO-8601, or now()."""
    if not st:
        return now_utc_iso()
    import calendar

    return datetime.fromtimestamp(calendar.timegm(st), tz=timezone.utc).isoformat()


def clean_text(raw: str | None, max_len: int = 2000) -> str:
    """Strip HTML tags, unescape entities, collapse whitespace, cap length."""
    if not raw:
        return ""
    text = html.unescape(_TAG_RE.sub(" ", raw))
    text = _WS_RE.sub(" ", text).strip()
    return text[:max_len]


class Source(ABC):
    """A real data source that returns a batch of Posts per fetch() call."""

    name: str = "source"

    @abstractmethod
    def fetch(self) -> list[Post]:
        """Pull the latest items. Must never fabricate data; return [] on no data."""

    def close(self) -> None:  # pragma: no cover - optional hook
        pass


class bounded_seen:
    """A bounded de-dup set: remembers the last `maxlen` ids seen this process.

    The durable idempotency guard is the downstream Delta MERGE on `id`; this
    only avoids re-publishing the same item to Kafka on every poll cycle.
    """

    def __init__(self, maxlen: int = 100_000):
        self._order: deque[str] = deque(maxlen=maxlen)
        self._set: set[str] = set()

    def __contains__(self, item: str) -> bool:
        return item in self._set

    def add(self, item: str) -> None:
        if item in self._set:
            return
        if len(self._order) == self._order.maxlen:
            evicted = self._order.popleft()
            self._set.discard(evicted)
        self._order.append(item)
        self._set.add(item)

    def filter_new(self, posts: Iterable[Post]) -> list[Post]:
        out: list[Post] = []
        for p in posts:
            if p.id in self:
                continue
            self.add(p.id)
            out.append(p)
        return out
