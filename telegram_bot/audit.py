"""Append-only JSONL audit of every dispatched market-event alert (B6 / C5).

Kept Spark-free so the dispatcher stays light: one line per fired alert under
data/audit/. A batch loader can materialize these into the price_alerts /
macro_events Delta tables (settings.PRICE_ALERTS_TABLE / MACRO_EVENTS_TABLE) for
analytics; the JSONL is the durable source of truth for "what did we send".
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone

from config import settings

logger = logging.getLogger(__name__)

_AUDIT_DIR = settings.DATA_ROOT / "audit"
_lock = threading.Lock()


def _append(name: str, record: dict) -> None:
    record = {"logged_at": datetime.now(timezone.utc).isoformat(), **record}
    path = _AUDIT_DIR / f"{name}.jsonl"
    with _lock:
        _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")


def record_price_alert(alert: dict, explanation_text: str, grounded: bool, recipients: int) -> None:
    _append("price_alerts", {
        **alert,
        "explanation": explanation_text,
        "grounded": grounded,
        "recipients": recipients,
    })


def record_macro_event(event: dict, explanation_text: str, grounded: bool, recipients: int) -> None:
    _append("macro_events", {
        **event,
        "explanation": explanation_text,
        "grounded": grounded,
        "recipients": recipients,
    })
