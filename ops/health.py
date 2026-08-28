"""H2: dependency health check — run before a demo.

    python -m ops.health            # config + Kafka + data paths
    python -m ops.health --probe    # also make one live call per configured API

Prints a green/red table and exits non-zero if a REQUIRED dependency is missing
(the Telegram token and Kafka). Everything else is optional — the app degrades
without it — so a missing key is reported as a warning, not a failure.
"""
from __future__ import annotations

import argparse
import sys

from config import settings

OK, WARN, FAIL = "OK  ✓", "WARN ·", "FAIL ✗"


def _kafka_reachable(timeout: float = 5.0) -> tuple[bool, str]:
    try:
        from confluent_kafka.admin import AdminClient

        md = AdminClient({"bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS}).list_topics(timeout=timeout)
        return True, f"{len(md.topics)} topics @ {settings.KAFKA_BOOTSTRAP_SERVERS}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{settings.KAFKA_BOOTSTRAP_SERVERS}: {exc}"


def _http_ok(url: str, timeout: float = 10.0, headers: dict | None = None) -> tuple[bool, str]:
    import requests

    try:
        r = requests.get(url, timeout=timeout, headers=headers or {})
        return r.status_code == 200, f"HTTP {r.status_code}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:60]


def gather(probe: bool = False) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []

    # Required
    tok_ok = settings.telegram_enabled()
    rows.append(("Telegram token", OK if tok_ok else FAIL, "set" if tok_ok else "TELEGRAM_BOT_TOKEN missing"))
    k_ok, k_detail = _kafka_reachable()
    rows.append(("Kafka broker", OK if k_ok else FAIL, k_detail))

    # Data paths
    dpath = settings.DELTA_ROOT
    rows.append(("Delta root", OK if dpath.parent.exists() else WARN, str(dpath)))

    # Optional capabilities (feature degrades if absent)
    for label, enabled, var in [
        ("Ingestion: RSS", True, "keyless"),
        ("Ingestion: Reddit", settings.reddit_enabled(), "REDDIT_CLIENT_ID/SECRET/USER_AGENT"),
        ("News/Finnhub", settings.finnhub_enabled(), "FINNHUB_API_KEY"),
        ("Macro/FRED", settings.fred_enabled(), "FRED_API_KEY"),
        ("Market/Alpaca", settings.alpaca_enabled(), "ALPACA_API_KEY/SECRET (else yfinance)"),
        ("LLM explainer", settings.llm_enabled(), "ANTHROPIC_API_KEY"),
    ]:
        rows.append((label, OK if enabled else WARN, "enabled" if enabled else f"off — {var}"))

    if probe:
        if tok_ok:
            ok, d = _http_ok(f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getMe")
            rows.append(("  probe Telegram", OK if ok else FAIL, d))
        if settings.finnhub_enabled():
            ok, d = _http_ok(f"https://finnhub.io/api/v1/quote?symbol=AAPL&token={settings.FINNHUB_API_KEY}")
            rows.append(("  probe Finnhub", OK if ok else FAIL, d))
        if settings.fred_enabled():
            ok, d = _http_ok(
                f"https://api.stlouisfed.org/fred/series?series_id=FEDFUNDS&file_type=json&api_key={settings.FRED_API_KEY}"
            )
            rows.append(("  probe FRED", OK if ok else FAIL, d))
        if settings.alpaca_enabled():
            ok, d = _http_ok(
                f"{settings.ALPACA_BASE_URL}/v2/clock",
                headers={"APCA-API-KEY-ID": settings.ALPACA_API_KEY,
                         "APCA-API-SECRET-KEY": settings.ALPACA_API_SECRET},
            )
            rows.append(("  probe Alpaca", OK if ok else FAIL, d))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Sentinel dependency health check")
    ap.add_argument("--probe", action="store_true", help="make one live call per configured API")
    args = ap.parse_args()

    rows = gather(probe=args.probe)
    width = max(len(r[0]) for r in rows)
    print("\nSentinel health check")
    print("-" * (width + 30))
    for name, status, detail in rows:
        print(f"{name.ljust(width)}  {status:8}  {detail}")
    failed = [r for r in rows if r[1] == FAIL]
    print("-" * (width + 30))
    print(f"{'FAILED' if failed else 'READY'}: {len(failed)} required check(s) failing\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
