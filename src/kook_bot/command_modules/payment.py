from __future__ import annotations

from ..bot import KookBot
from ..cards import build_action_group, build_command_button, build_link_button, build_status_cards
from ..context import CommandContext
from ..payment_gateway import PaymentGatewayError
from ..store_service import StoreError

SUPPORTED_PAYMENT_TYPES = ("alipay", "qqpay", "wxpay")
PAYMENT_AMOUNT_CARDS_PER_PAGE = 4


def register(bot: KookBot) -> None:
    @bot.command(
        "pay",
        description="Create a recharge payment order.",
        usage="/pay <amount> <method>",
        aliases=("recharge_pay",),
    )
    async def pay_command(ctx: CommandContext) -> None:
        amounts = ctx.bot.store.list_payment_amounts()
        if not ctx.bot.payment_gateway.is_configured():
            await ctx.reply_error(StoreError("error.payment_not_enabled"))
            return
        if not amounts and not ctx.bot.settings.payment_allow_custom_amount:
            await ctx.reply_error(StoreError("error.payment_amounts_unconfigured"))
            return

        if len(ctx.args) < 2:
            await ctx.reply_card(_build_payment_guide_cards(ctx, amounts))
            return

        try:
            amount = int(ctx.args[0])
        except ValueError:
            await ctx.reply_error(StoreError("error.payment_amount_integer"))
            return

        pay_type = ctx.args[1].strip().lower()
        if pay_type not in SUPPORTED_PAYMENT_TYPES:
            await ctx.reply_error(StoreError("error.payment_type_invalid"))
            return

        if not ctx.bot.store.is_payment_amount_allowed(amount, amounts):
            await ctx.reply_error(StoreError("error.payment_amount_not_allowed"))
            return

        try:
            result = await ctx.bot.create_payment_order(ctx.author_id, amount=amount, pay_type=pay_type)
        except (StoreError, PaymentGatewayError) as exc:
            if isinstance(exc, PaymentGatewayError):
                await ctx.reply_error(StoreError("error.payment_gateway_failed", message=str(exc)))
            else:
                await ctx.reply_error(exc)
            return

        order_cards = _build_payment_order_cards(ctx, result)
        if ctx.event.is_direct:
            await ctx.reply_card(order_cards)
            return

        try:
            await ctx.bot.send_direct_card(order_cards, target_id=ctx.author_id)
        except Exception:
            await ctx.reply_error(StoreError("error.payment_dm_failed"))
            return

        await ctx.reply_card(_build_payment_dm_notice_cards(ctx, result))

    @bot.command(
        "pay_amounts",
        description="Show available recharge amounts and payment methods.",
        usage="/pay_amounts",
    )
    async def pay_amounts_command(ctx: CommandContext) -> None:
        amounts = ctx.bot.store.list_payment_amounts()
        page = 1
        if ctx.args:
            try:
                page = max(1, int(ctx.args[0]))
            except ValueError:
                page = 1
        await ctx.reply_card(_build_payment_guide_cards(ctx, amounts, page=page))


def _build_payment_guide_cards(ctx: CommandContext, amounts: list[int], *, page: int = 1) -> list[dict[str, object]]:
    prefix = ctx.bot.settings.command_prefix
    custom_enabled = ctx.bot.settings.payment_allow_custom_amount
    custom_min = min(ctx.bot.settings.payment_custom_amount_min, ctx.bot.settings.payment_custom_amount_max)
    custom_max = max(ctx.bot.settings.payment_custom_amount_min, ctx.bot.settings.payment_custom_amount_max)
    total_pages = max(1, (len(amounts) + PAYMENT_AMOUNT_CARDS_PER_PAGE - 1) // PAYMENT_AMOUNT_CARDS_PER_PAGE)
    current_page = min(max(1, page), total_pages)
    start = (current_page - 1) * PAYMENT_AMOUNT_CARDS_PER_PAGE
    visible_amounts = amounts[start : start + PAYMENT_AMOUNT_CARDS_PER_PAGE]
    nav_buttons: list[dict[str, object]] = []
    if current_page > 1:
        nav_buttons.append(
            build_command_button(
                ctx.t("payment.guide.prev_page"),
                f"{prefix}pay_amounts {current_page - 1}",
                theme="secondary",
            )
        )
    if current_page < total_pages:
        nav_buttons.append(
            build_command_button(
                ctx.t("payment.guide.next_page"),
                f"{prefix}pay_amounts {current_page + 1}",
                theme="primary",
            )
        )
    cards: list[dict[str, object]] = [
        {
            "type": "card",
            "theme": "primary",
            "size": "lg",
            "modules": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain-text",
                        "content": ctx.t("payment.guide.title"),
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "kmarkdown",
                        "content": ctx.t("payment.guide.intro"),
                    },
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "kmarkdown",
                        "content": (
                            f"**{ctx.t('payment.field.amounts')}**\n"
                            f"{', '.join(str(amount) for amount in amounts) if amounts else ctx.t('payment.amounts_unset')}\n\n"
                            f"**{ctx.t('payment.field.custom_amount')}**\n"
                            f"{ctx.t('payment.custom_amount.enabled', minimum=custom_min, maximum=custom_max) if custom_enabled else ctx.t('payment.custom_amount.disabled')}\n\n"
                            f"**{ctx.t('payment.field.methods')}**\n"
                            f"{', '.join(SUPPORTED_PAYMENT_TYPES)}\n\n"
                            f"**{ctx.t('payment.field.usage')}**\n"
                            f"`{ctx.t('payment.guide.usage', prefix=prefix)}`\n\n"
                            f"**{ctx.t('payment.guide.page')}**\n"
                            f"{current_page}/{total_pages}"
                        ),
                    },
                },
                {"type": "divider"},
                build_action_group(nav_buttons or [build_command_button(ctx.t("button.help"), f"{prefix}help", theme="secondary")]),
            ],
        }
    ]

    for amount in visible_amounts:
        cards.append(
            {
                "type": "card",
                "theme": "secondary",
                "size": "lg",
                "modules": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain-text",
                            "content": ctx.t("payment.amount_card.title", amount=amount),
                        },
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "kmarkdown",
                            "content": ctx.t("payment.amount_card.body", amount=amount),
                        },
                    },
                    {"type": "divider"},
                    build_action_group(
                        [
                            build_command_button(ctx.t("button.pay.alipay"), f"{prefix}pay {amount} alipay", theme="primary"),
                            build_command_button(ctx.t("button.pay.qqpay"), f"{prefix}pay {amount} qqpay", theme="warning"),
                            build_command_button(ctx.t("button.pay.wxpay"), f"{prefix}pay {amount} wxpay", theme="success"),
                        ]
                    ),
                ],
            }
        )
    return cards[:5]


def _build_payment_order_cards(ctx: CommandContext, result: dict[str, object]) -> list[dict[str, object]]:
    submit_url = str(result.get("submit_url") or "").strip()
    body_lines = [
        ctx.t("payment.created.body", amount=result.get("money", ""), pay_type=result.get("type", ""), order_no=result.get("order_no", "")),
    ]
    if submit_url:
        body_lines.append(ctx.t("payment.created.pay_url", pay_url=submit_url))

    facts = [
        (ctx.t("payment.field.amount"), str(result.get("money", ""))),
        (ctx.t("payment.field.method"), str(result.get("type", ""))),
        (ctx.t("payment.field.order_no"), str(result.get("order_no", ""))),
    ]
    if submit_url:
        facts.append((ctx.t("payment.field.pay_url"), submit_url))

    return build_status_cards(
        ctx.t("payment.created.title"),
        body="\n".join(body_lines),
        facts=facts,
        theme="success",
        footer=ctx.t("payment.created.footer"),
        actions=[
            build_link_button(ctx.t("button.open_payment"), submit_url, theme="success"),
            build_command_button(ctx.t("button.pay_amounts"), f"{ctx.bot.settings.command_prefix}pay_amounts", theme="secondary"),
        ]
        if submit_url
        else [
            build_command_button(ctx.t("button.pay_amounts"), f"{ctx.bot.settings.command_prefix}pay_amounts", theme="secondary"),
        ],
    )


def _build_payment_dm_notice_cards(ctx: CommandContext, result: dict[str, object]) -> list[dict[str, object]]:
    return build_status_cards(
        ctx.t("payment.created.notice_title"),
        body=ctx.t("payment.created.notice_body"),
        facts=[
            (ctx.t("payment.field.amount"), str(result.get("money", ""))),
            (ctx.t("payment.field.method"), str(result.get("type", ""))),
            (ctx.t("payment.field.order_no"), str(result.get("order_no", ""))),
        ],
        theme="success",
        actions=[
            build_command_button(ctx.t("button.pay_amounts"), f"{ctx.bot.settings.command_prefix}pay_amounts", theme="secondary"),
        ],
    )
