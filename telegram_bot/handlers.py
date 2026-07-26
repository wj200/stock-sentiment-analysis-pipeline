"""Telegram command and callback-query handlers.

Mirrors the three things the Streamlit dashboard showed per ticker (price +
sentiment chart, strategy-vs-benchmark backtest chart, recent posts table),
plus push-style `/subscribe` alerts that a passive web dashboard can't do.
"""
import html
import logging

from telegram import Update
from telegram.ext import ContextTypes

from config import settings
from telegram_bot import data_service
from telegram_bot.keyboards import (
    TICKER_CALLBACK_PREFIX,
    WINDOW_CALLBACK_PREFIX,
    ticker_keyboard,
    window_keyboard,
)
from telegram_bot.charts import backtest_chart, price_sentiment_chart
from telegram_bot.state import store

logger = logging.getLogger(__name__)

_WELCOME = (
    "📈 <b>Stock Sentiment Bot</b>\n\n"
    "I track FinBERT-scored sentiment from news/forum posts alongside price "
    "action and a sentiment-crossing backtest.\n\n"
    "<b>Commands</b>\n"
    "/ticker - pick a ticker\n"
    "/window - pick a rolling sentiment window\n"
    "/price - price + sentiment chart\n"
    "/backtest - strategy vs. buy &amp; hold\n"
    "/posts - recent scored posts\n"
    "/subscribe - get alerted on entry/exit crossings\n"
    "/unsubscribe - stop alerts\n"
    "/status - show your current settings\n"
    "/refresh - force-reload underlying data"
)


def _sentiment_emoji(score: float) -> str:
    if score > 0.2:
        return "🟢"
    if score < -0.2:
        return "🔴"
    return "🟡"


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store.get(update.effective_chat.id)  # materialize defaults
    await update.message.reply_html(_WELCOME)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(_WELCOME)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = store.get(update.effective_chat.id)
    await update.message.reply_html(
        f"Ticker: <b>${state.ticker}</b>\n"
        f"Window: <b>{state.window}</b>\n"
        f"Alerts: <b>{'on' if state.subscribed else 'off'}</b>"
    )


async def refresh_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data_service.refresh()
    await update.message.reply_text("Cache cleared, next command will reload from Delta Lake / yfinance.")


async def ticker_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.args:
        requested = context.args[0].upper().lstrip("$")
        if requested not in settings.TICKERS:
            await update.message.reply_text(
                f"Unknown ticker '{requested}'. Known tickers: {', '.join(settings.TICKERS)}"
            )
            return
        store.update(update.effective_chat.id, ticker=requested)
        await update.message.reply_text(f"Ticker set to ${requested}.")
        return

    await update.message.reply_text("Pick a ticker:", reply_markup=ticker_keyboard())


async def window_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.args:
        requested = context.args[0].lower()
        if requested not in settings.ROLLING_WINDOWS:
            await update.message.reply_text(
                f"Unknown window '{requested}'. Choices: {', '.join(settings.ROLLING_WINDOWS.keys())}"
            )
            return
        store.update(update.effective_chat.id, window=requested)
        await update.message.reply_text(f"Rolling window set to {requested}.")
        return

    await update.message.reply_text("Pick a rolling sentiment window:", reply_markup=window_keyboard())


async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = store.get(update.effective_chat.id)
    await _send_price_chart(update, state.ticker, state.window)


async def backtest_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = store.get(update.effective_chat.id)
    await _send_backtest_chart(update, state.ticker, state.window)


async def posts_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = store.get(update.effective_chat.id)
    posts = data_service.get_recent_posts(state.ticker, limit=10)
    if posts.empty:
        await update.message.reply_text(f"No scored posts for ${state.ticker} yet.")
        return

    lines = [f"<b>Recent posts for ${state.ticker}</b>"]
    for _, row in posts.iterrows():
        emoji = _sentiment_emoji(row["sentiment_score"])
        ts = row["timestamp"].strftime("%Y-%m-%d %H:%M UTC")
        text = html.escape(str(row["text"]))[:200]
        lines.append(f"{emoji} <i>{ts}</i> ({html.escape(str(row['source']))}): {text}")
    await update.message.reply_html("\n\n".join(lines))


async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store.update(update.effective_chat.id, subscribed=True)
    await update.message.reply_text(
        "Subscribed. I'll ping you here when your ticker's rolling sentiment crosses the "
        f"entry (>{settings.ENTRY_SENTIMENT_THRESHOLD:+.1f}) or exit (<{settings.EXIT_SENTIMENT_THRESHOLD:+.1f}) threshold."
    )


async def unsubscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store.update(update.effective_chat.id, subscribed=False)
    await update.message.reply_text("Unsubscribed from sentiment alerts.")


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id

    if query.data.startswith(TICKER_CALLBACK_PREFIX):
        ticker = query.data.removeprefix(TICKER_CALLBACK_PREFIX)
        store.update(chat_id, ticker=ticker)
        await query.edit_message_text(f"Ticker set to ${ticker}. Sending price chart...")
        state = store.get(chat_id)
        await _send_price_chart(update, ticker, state.window, via_callback=True)

    elif query.data.startswith(WINDOW_CALLBACK_PREFIX):
        window_label = query.data.removeprefix(WINDOW_CALLBACK_PREFIX)
        store.update(chat_id, window=window_label)
        await query.edit_message_text(f"Rolling window set to {window_label}. Sending price chart...")
        state = store.get(chat_id)
        await _send_price_chart(update, state.ticker, window_label, via_callback=True)


async def _send_price_chart(update: Update, ticker: str, window_label: str, via_callback: bool = False) -> None:
    chat = update.effective_chat
    signal_df = data_service.load_signal_frame(window_label)
    if signal_df.empty:
        await chat.send_message(
            "No aligned sentiment/price data yet. Make sure the producer and Spark "
            "streaming job are running, then try /refresh."
        )
        return

    image = price_sentiment_chart(signal_df, ticker, window_label)
    if image is None:
        await chat.send_message(f"No data available for ${ticker} yet.")
        return
    await chat.send_photo(photo=image, caption=f"${ticker} price vs. {window_label} rolling sentiment")


async def _send_backtest_chart(update: Update, ticker: str, window_label: str) -> None:
    chat = update.effective_chat
    result = data_service.get_backtest_result(ticker, window_label)
    if result is None:
        await chat.send_message(f"Not enough data yet to backtest ${ticker}.")
        return

    image = backtest_chart(result)
    stats_text = (
        f"<b>${ticker} backtest ({window_label} window)</b>\n"
        f"Total return: <b>{result.total_return_pct:.2f}%</b> "
        f"(buy &amp; hold: {result.benchmark_total_return_pct:.2f}%)\n"
        f"Sharpe ratio: <b>{result.sharpe_ratio:.2f}</b>\n"
        f"Max drawdown: <b>{result.max_drawdown_pct:.2f}%</b>"
    )
    await chat.send_photo(photo=image, caption=stats_text, parse_mode="HTML")
