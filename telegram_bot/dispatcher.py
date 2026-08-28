"""Feature 2/3 alert dispatcher: Kafka alert topics -> grounded Telegram messages.

Consumes `stock-price-alerts` and `macro-events`, de-dups each event on its
natural key BEFORE the (costly) explain step, attaches a retrieval-grounded
explanation, and fans out — price alerts only to that ticker's watchers, macro
events to all macro opt-ins. Every send carries the not-advice disclaimer and is
throttled to respect Telegram limits; every fired alert is written to the JSONL
audit. One recipient's failure never stops the fan-out.
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from telegram import Bot
from telegram.constants import ParseMode

from config import settings
from explain import get_provider, get_retriever
from explain.explainer import explain_macro, explain_price_move
from ingestion.kafka_utils import build_consumer, deserialize
from ingestion.sources.base import bounded_seen
from telegram_bot import audit
from telegram_bot.messages import format_macro, format_price_move
from telegram_bot.state import store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SEND_THROTTLE_SECONDS = 1.0


class Dispatcher:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.retriever = get_retriever()
        self.provider = get_provider()
        self.seen = bounded_seen(maxlen=50_000)

    async def _send_all(self, chat_ids: list[int], text: str) -> int:
        sent = 0
        for chat_id in chat_ids:
            try:
                await self.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
                sent += 1
            except Exception as exc:  # noqa: BLE001 - one blocked chat must not stop the rest
                logger.warning("Send to %s failed: %s", chat_id, exc)
            await asyncio.sleep(SEND_THROTTLE_SECONDS)
        return sent

    async def handle_price(self, p: dict) -> None:
        ticker = p["ticker"]
        key = f"price:{ticker}:{p.get('session')}:{p.get('direction')}:{str(p.get('ts'))[:10]}"
        if key in self.seen:
            return
        self.seen.add(key)

        recipients = store.watchers_for(ticker)
        if not recipients:
            return  # nobody watching; skip the LLM call entirely
        exp = await asyncio.to_thread(
            explain_price_move, ticker, float(p["pct_move"]), p.get("session", "latest"),
            retriever=self.retriever, provider=self.provider,
        )
        msg = format_price_move(ticker, float(p["pct_move"]), p.get("session", "latest"),
                                float(p["ref_price"]), float(p["last"]), exp)
        sent = await self._send_all(recipients, msg)
        audit.record_price_alert(p, exp.text, exp.grounded, sent)
        logger.info("Dispatched price alert %s to %d watcher(s)", ticker, sent)

    async def handle_macro(self, p: dict) -> None:
        key = f"macro:{p.get('series')}:{p.get('observation_date')}"
        if key in self.seen:
            return
        self.seen.add(key)

        recipients = store.macro_opt_in_chat_ids()
        if not recipients:
            return
        exp = await asyncio.to_thread(
            explain_macro, p.get("label", p.get("series")), p.get("actual"),
            p.get("consensus"), p.get("prior"), p.get("surprise"), provider=self.provider,
        )
        msg = format_macro(p.get("label", p.get("series")), p.get("actual"),
                           p.get("consensus"), p.get("prior"), exp)
        sent = await self._send_all(recipients, msg)
        audit.record_macro_event(p, exp.text, exp.grounded, sent)
        logger.info("Dispatched macro event %s to %d chat(s)", p.get("series"), sent)


async def run() -> None:
    if not settings.telegram_enabled():
        raise SystemExit("TELEGRAM_BOT_TOKEN is required for the dispatcher.")
    settings.ensure_data_dirs()
    consumer = build_consumer(group_id="alert-dispatcher")
    consumer.subscribe([settings.KAFKA_TOPIC_PRICE_ALERTS, settings.KAFKA_TOPIC_MACRO_EVENTS])

    async with Bot(settings.TELEGRAM_BOT_TOKEN) as bot:
        disp = Dispatcher(bot)
        logger.info("Dispatcher started (news=%s, llm=%s)",
                    disp.retriever is not None, disp.provider is not None)
        try:
            while True:
                msg = await asyncio.to_thread(consumer.poll, 1.0)
                if msg is None:
                    continue
                if msg.error():
                    logger.warning("Kafka error: %s", msg.error())
                    continue
                try:
                    payload = deserialize(msg.value())
                    if msg.topic() == settings.KAFKA_TOPIC_PRICE_ALERTS:
                        await disp.handle_price(payload)
                    elif msg.topic() == settings.KAFKA_TOPIC_MACRO_EVENTS:
                        await disp.handle_macro(payload)
                except Exception:  # noqa: BLE001 - a bad message must not kill the loop
                    logger.exception("Failed to handle message from %s", msg.topic())
        except KeyboardInterrupt:
            logger.info("Dispatcher interrupted.")
        finally:
            consumer.close()


def main() -> None:
    argparse.ArgumentParser(description="Kafka alert dispatcher -> Telegram").parse_args()
    asyncio.run(run())


if __name__ == "__main__":
    main()
