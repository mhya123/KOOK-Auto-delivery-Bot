from __future__ import annotations

from .bot import KookBot
from .config import Settings
from .logging_utils import configure_logging


def create_bot() -> KookBot:
    settings = Settings.from_env()
    configure_logging(settings)
    return KookBot(settings)


def main() -> None:
    bot = create_bot()
    bot.run()
