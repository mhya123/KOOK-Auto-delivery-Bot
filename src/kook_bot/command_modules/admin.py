from __future__ import annotations

import re

from ..bot import KookBot
from ..context import CommandContext
from ..permissions import PermissionDenied, Role

USER_ID_PATTERN = re.compile(r"\d+")


def register(bot: KookBot) -> None:
    @bot.command(
        "addadmin",
        description="Grant admin role to a user.",
        usage="/addadmin <user_id>",
        required_role=Role.SUPER_ADMIN,
    )
    async def add_admin_command(ctx: CommandContext) -> None:
        if not ctx.args:
            await ctx.reply_t("admin.addadmin.usage")
            return

        target_user_id = _extract_user_id(ctx.args[0])
        if not target_user_id:
            await ctx.reply_t("common.invalid_user_id")
            return

        try:
            ctx.bot.permissions.add_admin(ctx.author_id, target_user_id)
        except PermissionDenied:
            await ctx.reply_t("admin.addadmin.denied")
            return

        await ctx.reply_t("admin.addadmin.success", user_id=target_user_id)

    @bot.command(
        "myrole",
        description="Show your current permission role.",
        usage="/myrole",
    )
    async def my_role_command(ctx: CommandContext) -> None:
        role_name = ctx.t(f"role.{ctx.author_role}")
        await ctx.reply_t("admin.myrole", role=role_name)


def _extract_user_id(raw: str) -> str | None:
    if raw.isdigit():
        return raw
    match = USER_ID_PATTERN.search(raw)
    return match.group(0) if match else None
