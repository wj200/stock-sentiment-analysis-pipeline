"""Central configuration for the stock sentiment pipeline.

All values are overridable via environment variables so the same code runs
unmodified on a laptop (bare processes) or inside docker-compose (service
hostnames instead of localhost).
"""
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.getenv("DATA_ROOT", PROJECT_ROOT / "data"))
DELTA_ROOT = Path(os.getenv("DELTA_ROOT", DATA_ROOT / "delta"))
CHECKPOINT_ROOT = Path(os.getenv("CHECKPOINT_ROOT", DATA_ROOT / "checkpoints"))

RAW_SENTIMENT_TABLE = str(DELTA_ROOT / "raw_sentiment")
SCORED_SENTIMENT_TABLE = str(DELTA_ROOT / "scored_sentiment")
MARKET_PRICES_TABLE = str(DELTA_ROOT / "market_prices")
ALIGNED_TABLE = str(DELTA_ROOT / "aligned_sentiment_price")
PRICE_ALERTS_TABLE = str(DELTA_ROOT / "price_alerts")      # Feature 2 audit
MACRO_EVENTS_TABLE = str(DELTA_ROOT / "macro_events")      # Feature 3 audit

# ---------------------------------------------------------------------------
# Kafka
# ---------------------------------------------------------------------------
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC_RAW_SENTIMENT = os.getenv("KAFKA_TOPIC_RAW_SENTIMENT", "stock-raw-sentiment")
KAFKA_TOPIC_SCORED_SENTIMENT = os.getenv("KAFKA_TOPIC_SCORED_SENTIMENT", "stock-scored-sentiment")
KAFKA_TOPIC_PRICE_ALERTS = os.getenv("KAFKA_TOPIC_PRICE_ALERTS", "stock-price-alerts")
KAFKA_TOPIC_MACRO_EVENTS = os.getenv("KAFKA_TOPIC_MACRO_EVENTS", "macro-events")
KAFKA_CONSUMER_GROUP = os.getenv("KAFKA_CONSUMER_GROUP", "sentiment-pipeline")

# ---------------------------------------------------------------------------
# Universe / tickers
# ---------------------------------------------------------------------------
TICKERS = [t.strip().upper() for t in os.getenv("TICKERS", "AAPL,NVDA,TSLA,MSFT").split(",") if t.strip()]

# Canonical source labels that can appear on a raw_sentiment record's `source`
# field. These are REAL ingestion channels (no synthetic generator).
SOURCES = ["rss", "reddit", "finnhub_news"]

# ---------------------------------------------------------------------------
# Ingestion (Feature 1) — which real sources to pull from
# ---------------------------------------------------------------------------
# Comma-separated subset of SOURCES. `rss` is keyless; the others need creds.
INGEST_SOURCES = [s.strip() for s in os.getenv("INGEST_SOURCES", "rss").split(",") if s.strip()]
INGEST_POLL_SECONDS = int(os.getenv("INGEST_POLL_SECONDS", "60"))

# Reddit (PRAW) — optional; enables the 'reddit' source when all three are set.
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "sentinel-sentiment-bot/1.0")
REDDIT_SUBREDDITS = [s.strip() for s in os.getenv(
    "REDDIT_SUBREDDITS", "wallstreetbets,stocks,investing,StockMarket").split(",") if s.strip()]

# Finnhub — company news (Feature 2 retrieval) + economic calendar (Feature 3).
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")

# FRED — macro series + release calendar (Feature 3).
FRED_API_KEY = os.getenv("FRED_API_KEY", "")

# ---------------------------------------------------------------------------
# ML model
# ---------------------------------------------------------------------------
FINBERT_MODEL_NAME = os.getenv("FINBERT_MODEL_NAME", "yiyanghkust/finbert-tone")
FINBERT_MAX_LENGTH = int(os.getenv("FINBERT_MAX_LENGTH", "128"))
FINBERT_BATCH_SIZE = int(os.getenv("FINBERT_BATCH_SIZE", "32"))

# ---------------------------------------------------------------------------
# Ray
# ---------------------------------------------------------------------------
RAY_ADDRESS = os.getenv("RAY_ADDRESS", "auto")
RAY_NUM_INFERENCE_ACTORS = int(os.getenv("RAY_NUM_INFERENCE_ACTORS", "2"))

# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------
MARKET_DATA_PROVIDER = os.getenv("MARKET_DATA_PROVIDER", "yfinance")  # or "alpaca"
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_API_SECRET = os.getenv("ALPACA_API_SECRET", "")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
ALPACA_DATA_FEED = os.getenv("ALPACA_DATA_FEED", "iex")  # free tier: iex; paid: sip

# ---------------------------------------------------------------------------
# Signal / backtest parameters
# ---------------------------------------------------------------------------
ROLLING_WINDOWS = {
    "15m": "15min",
    "1h": "1h",
    "4h": "4h",
    "24h": "24h",
}
ENTRY_SENTIMENT_THRESHOLD = float(os.getenv("ENTRY_SENTIMENT_THRESHOLD", "0.4"))
EXIT_SENTIMENT_THRESHOLD = float(os.getenv("EXIT_SENTIMENT_THRESHOLD", "-0.2"))
BACKTEST_INITIAL_CASH = float(os.getenv("BACKTEST_INITIAL_CASH", "100000"))
BACKTEST_FEES = float(os.getenv("BACKTEST_FEES", "0.001"))

# Rolling z-score sentiment anomaly (Feature 1, milestone A4): fire when a
# ticker's short-window sentiment is `Z_THRESHOLD` sigma above/below its own
# recent baseline, with at least `Z_MIN_POSTS` posts in the window.
SENTIMENT_Z_WINDOW = os.getenv("SENTIMENT_Z_WINDOW", "2h")
SENTIMENT_Z_THRESHOLD = float(os.getenv("SENTIMENT_Z_THRESHOLD", "2.0"))
SENTIMENT_Z_MIN_POSTS = int(os.getenv("SENTIMENT_Z_MIN_POSTS", "5"))

# ---------------------------------------------------------------------------
# Price-move detection (Feature 2)
# ---------------------------------------------------------------------------
PRICE_MOVE_PCT = float(os.getenv("PRICE_MOVE_PCT", "3.0"))       # % vs prior close
PRICE_MOVE_Z = float(os.getenv("PRICE_MOVE_Z", "2.5"))          # OR return z-score
PRICE_Z_LOOKBACK = int(os.getenv("PRICE_Z_LOOKBACK", "30"))     # bars for the z baseline
PRICE_STALE_SECONDS = int(os.getenv("PRICE_STALE_SECONDS", "120"))
NEWS_LOOKBACK_HOURS = int(os.getenv("NEWS_LOOKBACK_HOURS", "24"))
NEWS_TOP_N = int(os.getenv("NEWS_TOP_N", "5"))

# ---------------------------------------------------------------------------
# Macro releases to track (Feature 3) — curated, high-impact FRED series.
# ---------------------------------------------------------------------------
# series_id -> human label. Kept small and high-signal on purpose.
MACRO_SERIES = {
    "FEDFUNDS": "Federal Funds Rate",
    "CPIAUCSL": "CPI (All Urban Consumers)",
    "PCEPI": "PCE Price Index",
    "UNRATE": "Unemployment Rate",
    "PAYEMS": "Non-farm Payrolls",
    "GDPC1": "Real GDP",
}
MACRO_POLL_SECONDS = int(os.getenv("MACRO_POLL_SECONDS", "900"))  # 15 min

# ---------------------------------------------------------------------------
# LLM explanation layer (Features 2 & 3) — events only, never per-post.
# ---------------------------------------------------------------------------
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# Model IDs are resolved in explain/llm_provider.py; overridable here.
LLM_MODEL = os.getenv("LLM_MODEL", "")
LLM_MAX_WORDS = int(os.getenv("LLM_MAX_WORDS", "60"))
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
LLM_CACHE_SECONDS = int(os.getenv("LLM_CACHE_SECONDS", "300"))

# ---------------------------------------------------------------------------
# Streamlit
# ---------------------------------------------------------------------------
STREAMLIT_REFRESH_SECONDS = int(os.getenv("STREAMLIT_REFRESH_SECONDS", "30"))

# ---------------------------------------------------------------------------
# Telegram bot
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_DEFAULT_TICKER = os.getenv("TELEGRAM_DEFAULT_TICKER", TICKERS[0])
TELEGRAM_DEFAULT_WINDOW = os.getenv("TELEGRAM_DEFAULT_WINDOW", "1h")
TELEGRAM_DATA_CACHE_SECONDS = int(os.getenv("TELEGRAM_DATA_CACHE_SECONDS", "30"))
TELEGRAM_ALERT_POLL_SECONDS = int(os.getenv("TELEGRAM_ALERT_POLL_SECONDS", "60"))
TELEGRAM_STATE_FILE = Path(os.getenv("TELEGRAM_STATE_FILE", DATA_ROOT / "telegram_bot_state.json"))


def ensure_data_dirs() -> None:
    for path in (DATA_ROOT, DELTA_ROOT, CHECKPOINT_ROOT):
        path.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Feature-availability predicates — used to gate real sources on credentials
# and to tell the operator, at startup, exactly what is missing.
# ---------------------------------------------------------------------------
def reddit_enabled() -> bool:
    return bool(REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET and REDDIT_USER_AGENT)


def finnhub_enabled() -> bool:
    return bool(FINNHUB_API_KEY)


def fred_enabled() -> bool:
    return bool(FRED_API_KEY)


def alpaca_enabled() -> bool:
    return bool(ALPACA_API_KEY and ALPACA_API_SECRET)


def llm_enabled() -> bool:
    return bool(ANTHROPIC_API_KEY) if LLM_PROVIDER == "anthropic" else False


def telegram_enabled() -> bool:
    return bool(TELEGRAM_BOT_TOKEN)


def missing_credentials(active_sources: list | None = None) -> dict[str, str]:
    """Maps a missing capability -> the env var(s) that would enable it.

    `active_sources` defaults to INGEST_SOURCES so we only flag ingestion
    sources the operator actually asked for.
    """
    active_sources = active_sources if active_sources is not None else INGEST_SOURCES
    missing: dict[str, str] = {}
    if "reddit" in active_sources and not reddit_enabled():
        missing["reddit ingestion"] = "REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT"
    if "finnhub_news" in active_sources and not finnhub_enabled():
        missing["finnhub news ingestion"] = "FINNHUB_API_KEY"
    return missing
