# Deploying Sentinel

Sentinel is a **single-host Docker Compose stack**. Because the Telegram bot runs
in **long-polling** mode, you need **no public URL, domain, TLS, or inbound ports** —
only a machine with Docker and outbound internet access.

The stack is stateful and multi-container (Kafka + Zookeeper, a Spark/FinBERT
streaming scorer, the ingestion producer, two market-event monitors, the alert
dispatcher, the bot, and an optional dashboard), so it does **not** fit a
one-container PaaS. Deploy it on a VM (or, at scale, Kubernetes — see the
blueprint §14). All durable state lives under `./data` (the Delta lake, Spark
checkpoints, and the bot's JSON state).

---

## 1. Requirements

| Item | Minimum | Notes |
|---|---|---|
| CPU / RAM | **4 vCPU / 8 GB** | Spark (JVM) + FinBERT/torch (CPU inference) are the drivers. |
| Disk | **20–30 GB** | Image (~a few GB) + Delta lake growth. |
| OS | Ubuntu 22.04 / Debian 12 | Any Docker host works; the provision script targets apt. |
| Network | **outbound HTTPS** | Telegram, HuggingFace (first-run model download), Finnhub/FRED/Alpaca, Anthropic. No inbound needed. |
| Ports | none required | Only the optional dashboard exposes `8501`. |

---

## 2. One-shot install (recommended)

On a fresh Ubuntu/Debian VM:

```bash
curl -fsSL https://raw.githubusercontent.com/wj200/stock-sentiment-analysis-pipeline/claude/telegram-financial-alerts-pdf-tmwzcx/scripts/provision.sh -o provision.sh
bash provision.sh
```

The script installs Docker + the Compose plugin, clones the repo, and creates
`.env` from the template. The **first run stops after creating `.env`** so you can
fill in your keys — edit it, then run `bash provision.sh` again to build and start.

> Prefer to do it by hand? Follow steps 3–6 below.

---

## 3. Install Docker (manual)

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER" && newgrp docker   # run docker without sudo
sudo systemctl enable docker                       # so it starts at boot
```

## 4. Clone

```bash
git clone -b claude/telegram-financial-alerts-pdf-tmwzcx \
  https://github.com/wj200/stock-sentiment-analysis-pipeline.git
cd stock-sentiment-analysis-pipeline
```

## 5. Configure `.env`

```bash
cp .env.example .env
nano .env
```

| Env var | Needed for | Notes |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | **required** | from @BotFather |
| `FINNHUB_API_KEY` | Feature 2 "why" + Finnhub ingestion | free tier |
| `FRED_API_KEY` | Feature 3 macro | free |
| `ALPACA_API_KEY` / `ALPACA_API_SECRET` | Feature 2 real-time quotes | else keyless yfinance is used automatically |
| `ANTHROPIC_API_KEY` | Feature 2/3 explanations | without it, alerts still fire but degrade to the raw top headline |
| `REDDIT_CLIENT_ID/SECRET/USER_AGENT` | optional Reddit ingestion | RSS works with no key |
| `INGEST_SOURCES` | which sources are active | default `rss`; e.g. `rss,reddit,finnhub_news` |
| `MARKET_DATA_PROVIDER` | `yfinance` (keyless) or `alpaca` | |

`.env` is gitignored — never commit real keys.

## 6. Launch

```bash
docker compose up -d --build
```

First build is slow (torch + Spark); on first run the scorer downloads FinBERT
(~440 MB) from HuggingFace and the Spark-Kafka connector jar — allow a few minutes.

## 7. Verify

```bash
docker compose run --rm telegram-bot python -m ops.health --probe
docker compose logs -f telegram-bot alert-dispatcher
```

Then message your bot: `/start`, `/subscribe`, `/watch NVDA`, `/why NVDA`,
`/macro on`, `/validate`.

---

## Operating

```bash
docker compose ps                       # service status
docker compose logs -f <service>        # tail logs (journald-style)
docker compose up -d --build            # apply an update after `git pull`
docker compose down                     # stop (keeps ./data)
docker compose down -v                  # stop AND delete Kafka/ZK volumes (NOT ./data)
```

- **Back up `./data`.** It holds the Delta lake, Spark checkpoints, and bot state.
  Do **not** delete `data/checkpoints/` — the stream would lose its position and
  reprocess from scratch.
- **Single replica only.** The scheduler and JSON state are in-process; never scale
  the bot/monitors past one instance (you'd double-fire reminders and alerts).
- **Secrets rotation.** Rotate any key that has ever left a secure channel.

---

## Run at boot

The Compose services already carry `restart: unless-stopped`, so **if the Docker
daemon is enabled at boot** (`sudo systemctl enable docker`) the whole stack comes
back automatically after a reboot or crash. For most deployments that is enough.

If you'd rather manage the stack as a **first-class system service** (so
`systemctl start/stop/status sentinel` controls the whole Compose project and its
logs flow to journald), install this unit — replace the paths/user:

```ini
# /etc/systemd/system/sentinel.service
[Unit]
Description=Sentinel stock sentiment & market-event bot (docker compose)
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/ubuntu/stock-sentiment-analysis-pipeline
ExecStart=/usr/bin/docker compose up -d --build
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now sentinel     # start now and on every boot
sudo systemctl status sentinel
```

---

## Dashboard (optional)

The Streamlit dashboard is builder-facing and the only service that opens a port
(`8501`). Don't expose it publicly — reach it over an SSH tunnel:

```bash
ssh -L 8501:localhost:8501 user@<vm-ip>     # then open http://localhost:8501
```

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Bot doesn't reply | Check `TELEGRAM_BOT_TOKEN`; `docker compose logs telegram-bot`. |
| No sentiment data | Producer + Spark need a minute; confirm `kafka-producer` and `ml-inference-spark` are healthy. |
| Scorer stuck on first boot | It's downloading FinBERT from HuggingFace — check outbound network. |
| OOM / container killed | Give the VM ≥8 GB; Spark + torch are memory-hungry. |
| `/why` returns raw headline only | `ANTHROPIC_API_KEY` not set (expected degrade), or `FINNHUB_API_KEY` missing. |
| Macro/price alerts silent | `macro-monitor` needs `FRED_API_KEY`; price alerts only fire in pre/post-market sessions. |
| `ops.health` shows Kafka FAIL | Broker not up yet, or `KAFKA_BOOTSTRAP_SERVERS` wrong. |

## Scaling beyond one host

See the blueprint §14: move the scheduler out of process first, then multi-broker
Kafka (RF≥3), GPU/quantised FinBERT, Postgres/Redis bot state, and Kubernetes.
