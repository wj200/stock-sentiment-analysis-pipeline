"""Per-chat preferences (ticker, rolling window, alert subscription) persisted to disk.

A plain JSON file (guarded by a lock) is enough here — chat count is small
and writes are infrequent (only on `/ticker`, `/window`, `/subscribe`,
`/unsubscribe`, or when an alert fires) — and it survives bot restarts
without needing a database service in docker-compose.
"""
import json
import logging
import threading
from dataclasses import asdict, dataclass, field

from config import settings

logger = logging.getLogger(__name__)


@dataclass
class ChatState:
    ticker: str = settings.TELEGRAM_DEFAULT_TICKER
    window: str = settings.TELEGRAM_DEFAULT_WINDOW
    subscribed: bool = False
    # ticker -> last alerted signal ISO timestamp, so `/subscribe` never re-fires on the same crossing
    last_alert: dict = field(default_factory=dict)


class StateStore:
    def __init__(self, path=settings.TELEGRAM_STATE_FILE):
        self.path = path
        self._lock = threading.Lock()
        self._chats: dict[str, ChatState] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
            self._chats = {chat_id: ChatState(**data) for chat_id, data in raw.items()}
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Could not parse Telegram bot state file %s: %s", self.path, exc)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        serializable = {chat_id: asdict(state) for chat_id, state in self._chats.items()}
        self.path.write_text(json.dumps(serializable, indent=2))

    def get(self, chat_id: int) -> ChatState:
        key = str(chat_id)
        with self._lock:
            if key not in self._chats:
                self._chats[key] = ChatState()
                self._save()
            return self._chats[key]

    def update(self, chat_id: int, **kwargs) -> ChatState:
        key = str(chat_id)
        with self._lock:
            state = self._chats.setdefault(key, ChatState())
            for field_name, value in kwargs.items():
                setattr(state, field_name, value)
            self._save()
            return state

    def set_last_alert(self, chat_id: int, ticker: str, alert_timestamp: str) -> None:
        key = str(chat_id)
        with self._lock:
            state = self._chats.setdefault(key, ChatState())
            state.last_alert[ticker] = alert_timestamp
            self._save()

    def subscribed_chat_ids(self) -> list[int]:
        with self._lock:
            return [int(chat_id) for chat_id, state in self._chats.items() if state.subscribed]


store = StateStore()
