# Sentinel — Stock Sentiment & Market-Event Telegram Bot

One Telegram chat over a real-time streaming data platform. Three features, each
grounded in **real data** and honest about what it doesn't know:

1. **Social/news sentiment leading indicator** — Kafka ingests real posts (keyless
   RSS + optional Reddit/Finnhub), Spark scores each with **FinBERT**, lands them
   in **Delta Lake**, and (point-in-time-safe) turns sentiment into a
   backtested crossing/z-score signal. Alerts on `/subscribe`.
2. **Pre/post-market price-move + "why"** — a monitor watches extended-hours
   quotes (yfinance keyless / Alpaca), and a **retrieval-grounded LLM explainer**
   answers *why* a `/watch`ed ticker moved, cited from real headlines — or says
   "no clear catalyst yet". `/why` runs it on demand.
3. **US macro release + "why"** — a FRED-driven monitor detects key releases
   (Fed, CPI, PCE, jobs, GDP), computes the surprise, and broadcasts a grounded
   explanation to `/macro on` chats.

> **Not financial advice.** Sentinel reports data and explains events; it never
> recommends a trade. This is enforced structurally (see the blueprint §16), not
> just by a footer.

The full design is in **[`docs/sentinel-telegram-bot-blueprint.pdf`](docs/sentinel-telegram-bot-blueprint.pdf)**
(source in `docs/blueprint/`). Section 13 tracks each feature's milestones.

## Architecture

```
real sources ─▶ Kafka ─▶ Spark Structured Streaming ─▶ Delta Lake ─▶ align/signal/backtest
   (RSS/Reddit/Finnhub)        (FinBERT scoring)                          │
price monitor ─▶ stock-price-alerts ┐                                     ▼
macro monitor ─▶ macro-events ──────┴─▶ dispatcher ─(explain)─▶ Telegram bot ◀─ commands
```

## Quickstart (Docker)

```bash
cp .env.example .env          # then fill in the keys you have (see below)
docker compose up --build
```

Services: `zookeeper`, `kafka`, `kafka-producer` (real ingestion),
`ml-inference-spark` (FinBERT), `telegram-bot`, `price-monitor`, `macro-monitor`,
`alert-dispatcher`, `dashboard` (Streamlit on :8501).

Check dependencies before a demo:

```bash
python -m ops.health --probe   # config + Kafka + one live call per configured API
```

## Credentials

| Capability | Env var(s) | Needed for |
|---|---|---|
| Run the bot | `TELEGRAM_BOT_TOKEN` | everything (get from @BotFather) |
| RSS ingestion | *(none)* | Feature 1 baseline — real, keyless |
| Reddit ingestion | `REDDIT_CLIENT_ID/SECRET/USER_AGENT` | richer Feature 1 |
| News explanations | `FINNHUB_API_KEY` | Feature 2 "why", Finnhub ingestion |
| Extended-hours (real-time) | `ALPACA_API_KEY/SECRET` | Feature 2 (else keyless yfinance) |
| Macro data | `FRED_API_KEY` | Feature 3 |
| LLM explanations | `ANTHROPIC_API_KEY` | Features 2 & 3 narrative (degrades to raw headlines without it) |

`INGEST_SOURCES` selects active sources (default `rss`). See `.env.example` for
all knobs. Secrets live in `.env` (gitignored) — never commit them.

## Bot commands

`/ticker` `/window` `/price` `/backtest` `/validate` `/posts` `/subscribe` ·
`/watch SYM` `/unwatch SYM` `/why [SYM]` `/macro on|off` · `/status` `/refresh`

## Tests

```bash
pip install -r requirements.txt
pytest -q                      # logic/unit tests (no network)
```

## Layout

```
ingestion/   real sources + Kafka producer + price/macro monitors
data_pipeline/  Spark streaming, Delta writers, point-in-time alignment
ml_engine/   FinBERT model + distributed inference
quant_backtest/ signals (crossing + z-score) + vectorbt backtest + validation
explain/     retrieval + LLM provider + grounded prompts + explainer
market/      real quotes + pure move detection
telegram_bot/ bot, handlers, dispatcher, state, audit, charts
ops/         health check
dashboard/   Streamlit
docs/        the blueprint
```
