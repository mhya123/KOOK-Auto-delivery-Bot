from __future__ import annotations

from ..bot import KookBot
from ..cards import build_status_cards
from ..context import CommandContext
from ..permissions import Role
from ..store_service import StoreError


def register(bot: KookBot) -> None:
    @bot.command(
        "set_pay_amounts",
        description="Set allowed recharge amounts.",
        usage="/set_pay_amounts <amount1> <amount2> ...",
        required_role=Role.ADMIN,
    )
    async def set_pay_amounts_command(ctx: CommandContext) -> None:
        if not ctx.args:
            await ctx.reply_warning_t("payment.admin.set_amounts_usage")
            return

        try:
            amounts = [int(item) for item in ctx.args]
        except ValueError:
            await ctx.reply_error(StoreError("error.payment_amount_integer"))
            return

        try:
            normalized = ctx.bot.store.replace_payment_amounts(ctx.author_id, amounts)
        except StoreError as exc:
            await ctx.reply_error(exc)
            return

        await ctx.reply_card(
            build_status_cards(
                ctx.t("payment.admin.set_amounts_title"),
                body=ctx.t("payment.admin.set_amounts_success", amounts=", ".join(str(item) for item in normalized)),
                facts=[(ctx.t("payment.field.amounts"), ", ".join(str(item) for item in normalized))],
                theme="success",
            )
        )
