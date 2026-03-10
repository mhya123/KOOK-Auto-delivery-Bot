from __future__ import annotations

from datetime import datetime

from ..bot import KookBot
from ..cards import build_fact_cards, build_status_cards
from ..context import CommandContext
from ..store_service import NotFoundError, StoreError


def register(bot: KookBot) -> None:
    @bot.command(
        "balance",
        description="Show your current balance.",
        usage="/balance",
        aliases=("profile",),
    )
    async def balance_command(ctx: CommandContext) -> None:
        try:
            profile = ctx.bot.store.get_profile(ctx.author_id)
        except (StoreError, NotFoundError) as exc:
            await ctx.reply_error(exc)
            return

        created_at = datetime.fromtimestamp(int(profile["created_at"])).strftime("%Y-%m-%d %H:%M:%S")
        role_name = ctx.t(f"role.{profile['role']}")
        await ctx.reply_card(
            build_fact_cards(
                ctx.t("profile.title"),
                [
                    (ctx.t("profile.field.user_id"), str(profile["user_id"])),
                    (ctx.t("profile.field.role"), role_name),
                    (ctx.t("profile.field.balance"), str(profile["balance"])),
                    (ctx.t("profile.field.created_at"), created_at),
                ],
                theme="primary",
            )
        )

    @bot.command(
        "recharge",
        description="Redeem a recharge card and add balance.",
        usage="/recharge <card_code>",
    )
    async def recharge_command(ctx: CommandContext) -> None:
        if not ctx.args:
            await ctx.reply_warning_t("recharge.usage")
            return

        card_code = ctx.args[0].strip()
        try:
            result = ctx.bot.store.recharge(ctx.author_id, card_code)
        except StoreError as exc:
            await ctx.reply_error(exc)
            return

        await ctx.reply_card(
            build_status_cards(
                ctx.t("recharge.title"),
                body=ctx.t("recharge.success", amount=result["amount"], balance_after=result["balance_after"]),
                facts=[
                    (ctx.t("recharge.field.amount"), str(result["amount"])),
                    (ctx.t("recharge.field.balance_after"), str(result["balance_after"])),
                ],
                theme="success",
            )
        )
