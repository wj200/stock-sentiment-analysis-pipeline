"""Entrypoint: registers handlers and starts the Telegram bot in polling mode.

Run with: python -m telegram_bot.bot
Requires TELEGRAM_BOT_TOKEN to be set (get one from @BotFather).
"""
import logging

from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from config import settings
from telegram_bot import handlers
from telegram_bot.alerts import check_and_send_alerts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def build_application() -> Application:
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. Create a bot with @BotFather and set the "
            "TELEGRAM_BOT_TOKEN environment variable (see .env.example)."
        )

    settings.ensure_data_dirs()
    application = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", handlers.start_command))
    application.add_handler(CommandHandler("help", handlers.help_command))
    application.add_handler(CommandHandler("status", handlers.status_command))
    application.add_handler(CommandHandler("refresh", handlers.refresh_command))
    application.add_handler(CommandHandler("ticker", handlers.ticker_command))
    application.add_handler(CommandHandler("window", handlers.window_command))
    application.add_handler(CommandHandler("price", handlers.price_command))
    application.add_handler(CommandHandler("backtest", handlers.backtest_command))
    application.add_handler(CommandHandler("posts", handlers.posts_command))
    application.add_handler(CommandHandler("subscribe", handlers.subscribe_command))
    application.add_handler(CommandHandler("unsubscribe", handlers.unsubscribe_command))
    application.add_handler(CommandHandler("watch", handlers.watch_command))
    application.add_handler(CommandHandler("unwatch", handlers.unwatch_command))
    application.add_handler(CommandHandler("macro", handlers.macro_command))
    application.add_handler(CommandHandler("why", handlers.why_command))
    application.add_handler(CallbackQueryHandler(handlers.callback_query_handler))

    application.job_queue.run_repeating(
        check_and_send_alerts,
        interval=settings.TELEGRAM_ALERT_POLL_SECONDS,
        first=settings.TELEGRAM_ALERT_POLL_SECONDS,
    )

    return application


def main() -> None:
    application = build_application()
    logger.info("Starting Telegram bot polling loop...")
    application.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
