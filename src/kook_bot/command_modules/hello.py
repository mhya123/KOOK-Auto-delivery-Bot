from __future__ import annotations

from ..bot import KookBot
from ..context import CommandContext


def register(bot: KookBot) -> None:
    @bot.command(
        "hello",
        description="Reply with a simple hello world message.",
        usage="/hello",
    )
    async def hello_command(ctx: CommandContext) -> None:
        await ctx.reply_t("hello.response")
