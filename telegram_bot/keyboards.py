"""Inline keyboard builders for ticker and rolling-window selection."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import settings

TICKER_CALLBACK_PREFIX = "ticker:"
WINDOW_CALLBACK_PREFIX = "window:"


def ticker_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(f"${ticker}", callback_data=f"{TICKER_CALLBACK_PREFIX}{ticker}")
        for ticker in settings.TICKERS
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


def window_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(label, callback_data=f"{WINDOW_CALLBACK_PREFIX}{label}")
        for label in settings.ROLLING_WINDOWS.keys()
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)
