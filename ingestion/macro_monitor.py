"""Feature 3: US macro release monitor -> Kafka `macro-events`.

Polls FRED for the curated high-impact series (settings.MACRO_SERIES). When a
series posts a new observation (a new latest date vs. what we last saw), it emits
one market-wide event with actual / prior / (best-effort) consensus / surprise.
The dispatcher explains it and broadcasts to macro opt-in chats.

Requires FRED_API_KEY. Consensus is pulled best-effort from the Finnhub economic
calendar when FINNHUB_API_KEY is set; otherwise the event carries actual-vs-prior
only (surprise = None), which the explainer handles.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import date, datetime, timezone

from config import settings
from ingestion.kafka_utils import build_producer, delivery_report, ensure_topics, serialize

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_STATE_PATH = settings.DATA_ROOT / "macro_monitor_state.json"


def _is_new(latest_iso: str | None, last_seen_iso: str | None) -> bool:
    """A release is new if we've never seen this series, or its latest date advanced."""
    if not latest_iso:
        return False
    if not last_seen_iso:
        return True
    return latest_iso > last_seen_iso


def _load_state() -> dict:
    if _STATE_PATH.exists():
        try:
            return json.loads(_STATE_PATH.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _save_state(state: dict) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, indent=2))


class FredSource:
    def __init__(self, api_key: str):
        from fredapi import Fred  # lazy import

        self.fred = Fred(api_key=api_key)

    def latest_two(self, series_id: str):
        """Return (latest_date_iso, latest_value, prior_value) or None."""
        series = self.fred.get_series(series_id).dropna()
        if series.empty:
            return None
        latest_date = series.index[-1].date().isoformat()
        latest_val = float(series.iloc[-1])
        prior_val = float(series.iloc[-2]) if len(series) >= 2 else None
        return latest_date, latest_val, prior_val


def _finnhub_consensus(label: str) -> float | None:
    """Best-effort consensus from the Finnhub economic calendar (keyword match)."""
    if not settings.finnhub_enabled():
        return None
    try:
        import finnhub

        client = finnhub.Client(api_key=settings.FINNHUB_API_KEY)
        today = date.today().isoformat()
        cal = client.economic_calendar(_from=today, to=today).get("economicCalendar", [])
        key = label.split("(")[0].strip().lower()
        for ev in cal:
            if key and key in (ev.get("event", "").lower()):
                est = ev.get("estimate")
                return float(est) if est not in (None, "") else None
    except Exception as exc:  # noqa: BLE001 - consensus is optional
        logger.warning("Finnhub consensus lookup failed for %s: %s", label, exc)
    return None


def poll_once(producer, fred: FredSource, state: dict, topic: str) -> int:
    emitted = 0
    for series_id, label in settings.MACRO_SERIES.items():
        try:
            latest = fred.latest_two(series_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("FRED fetch failed for %s: %s", series_id, exc)
            continue
        if latest is None:
            continue
        latest_date, actual, prior = latest
        if not _is_new(latest_date, state.get(series_id)):
            continue

        consensus = _finnhub_consensus(label)
        surprise = (actual - consensus) if consensus is not None else None
        payload = {
            "series": series_id, "label": label, "actual": actual, "consensus": consensus,
            "prior": prior, "surprise": surprise, "observation_date": latest_date,
            "release_time": datetime.now(timezone.utc).isoformat(),
        }
        producer.produce(topic, key=series_id.encode("utf-8"),
                         value=serialize(payload), callback=delivery_report)
        state[series_id] = latest_date
        emitted += 1
        logger.info("MACRO EVENT %s actual=%s prior=%s consensus=%s", label, actual, prior, consensus)
    producer.poll(0)
    producer.flush(10)
    if emitted:
        _save_state(state)
    return emitted


def run(poll_seconds: int = settings.MACRO_POLL_SECONDS, once: bool = False,
        topic: str = settings.KAFKA_TOPIC_MACRO_EVENTS,
        bootstrap_servers: str = settings.KAFKA_BOOTSTRAP_SERVERS) -> None:
    if not settings.fred_enabled():
        raise SystemExit("FRED_API_KEY is required for the macro monitor. See .env.example.")
    settings.ensure_data_dirs()
    ensure_topics(bootstrap_servers=bootstrap_servers)
    fred = FredSource(settings.FRED_API_KEY)
    producer = build_producer(bootstrap_servers=bootstrap_servers)
    state = _load_state()
    logger.info("Macro monitor started (series=%s)", list(settings.MACRO_SERIES))
    try:
        while True:
            n = poll_once(producer, fred, state, topic)
            if n:
                logger.info("Emitted %d macro event(s) this cycle", n)
            if once:
                break
            time.sleep(poll_seconds)
    except KeyboardInterrupt:
        logger.info("Macro monitor interrupted.")
    finally:
        producer.flush(10)


def main() -> None:
    p = argparse.ArgumentParser(description="US macro release monitor -> Kafka")
    p.add_argument("--poll", type=int, default=settings.MACRO_POLL_SECONDS)
    p.add_argument("--once", action="store_true")
    args = p.parse_args()
    run(poll_seconds=args.poll, once=args.once)


if __name__ == "__main__":
    main()
