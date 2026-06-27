
from __future__ import annotations

from pathlib import Path

from app.telegram_bot.search_bot import TelegramSearchBot
from app.telegram_bot.config import ConfigStore
from app.telegram_bot.metrics import Metrics
from app.telegram_bot.push_bot import TelegramPushBot

DATA_DIR = Path(__file__).resolve().parents[2] / "uploads" / "telegram_bot"
DATA_DIR.mkdir(parents=True, exist_ok=True)

store = ConfigStore(DATA_DIR / "config.json")
metrics = Metrics(DATA_DIR / "metrics.json")
search_bot = TelegramSearchBot(store, metrics)
push_bot = TelegramPushBot(store, metrics)


def bot_status() -> dict:
    return {
        "bot_running": search_bot.running(),
        "push_bot_running": push_bot.running(),
    }


def start_configured_bots() -> None:
    cfg = store.get()
    if cfg.bot_enabled and cfg.telegram_bot_token:
        search_bot.start_background()
    if cfg.push_enabled and cfg.push_bot_token and cfg.push_chat_id:
        push_bot.start_background()


async def stop_bots() -> None:
    await search_bot.stop()
    await push_bot.stop()
