"""Push alerts on sentiment entry/exit crossings — the one thing a passive dashboard can't do.

Runs as a periodic `JobQueue` job: for every subscribed chat, looks at the
most recent bar for that chat's chosen ticker/window and pushes a message if
it's a fresh (not-yet-alerted) entry or exit crossing.
"""
import logging

from telegram.ext import ContextTypes

from config import settings
from telegram_bot import data_service
from telegram_bot.state import store

logger = logging.getLogger(__name__)


async def check_and_send_alerts(context: ContextTypes.DEFAULT_TYPE) -> None:
    for chat_id in store.subscribed_chat_ids():
        state = store.get(chat_id)
        try:
            await _check_chat(context, chat_id, state.ticker, state.window)
        except Exception:  # noqa: BLE001 - one chat's failure shouldn't kill the alert loop
            logger.exception("Failed to check alerts for chat_id=%s ticker=%s", chat_id, state.ticker)


async def _check_chat(context: ContextTypes.DEFAULT_TYPE, chat_id: int, ticker: str, window_label: str) -> None:
    signal_df = data_service.load_signal_frame(window_label)
    if signal_df.empty:
        return

    ticker_df = signal_df[signal_df["ticker"] == ticker].sort_values("timestamp")
    if ticker_df.empty:
        return

    latest = ticker_df.iloc[-1]
    latest_ts = latest["timestamp"].isoformat()

    state = store.get(chat_id)
    if state.last_alert.get(ticker) == latest_ts:
        return  # already alerted on this bar

    if latest["entry_signal"]:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"🟢 <b>${ticker}</b> entry signal: rolling sentiment crossed above "
                f"{settings.ENTRY_SENTIMENT_THRESHOLD:+.1f} as of {latest_ts}."
            ),
            parse_mode="HTML",
        )
        store.set_last_alert(chat_id, ticker, latest_ts)
    elif latest["exit_signal"]:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"🔴 <b>${ticker}</b> exit signal: rolling sentiment dropped below "
                f"{settings.EXIT_SENTIMENT_THRESHOLD:+.1f} as of {latest_ts}."
            ),
            parse_mode="HTML",
        )
        store.set_last_alert(chat_id, ticker, latest_ts)
