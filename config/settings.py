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

# ---------------------------------------------------------------------------
# Kafka
# ---------------------------------------------------------------------------
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC_RAW_SENTIMENT = os.getenv("KAFKA_TOPIC_RAW_SENTIMENT", "stock-raw-sentiment")
KAFKA_TOPIC_SCORED_SENTIMENT = os.getenv("KAFKA_TOPIC_SCORED_SENTIMENT", "stock-scored-sentiment")
KAFKA_CONSUMER_GROUP = os.getenv("KAFKA_CONSUMER_GROUP", "sentiment-pipeline")

# ---------------------------------------------------------------------------
# Universe / tickers
# ---------------------------------------------------------------------------
TICKERS = os.getenv("TICKERS", "AAPL,NVDA,TSLA,MSFT").split(",")
SOURCES = ["reddit", "news", "twitter"]

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
