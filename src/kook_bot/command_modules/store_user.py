from __future__ import annotations

from ..bot import KookBot
from ..cards import build_action_group, build_command_button, build_fact_cards, build_status_cards, build_text_cards
from ..context import CommandContext
from ..store_service import InsufficientBalanceError, NotFoundError, OutOfStockError, StoreError

MAX_PRODUCT_CARDS = 5
PRODUCTS_PER_CARD = 2


def register(bot: KookBot) -> None:
    @bot.command(
        "products",
        description="List all products and stock.",
        usage="/products",
        aliases=("list_products",),
    )
    async def products_command(ctx: CommandContext) -> None:
        products = ctx.bot.store.list_products()
        if not products:
            await ctx.reply_t("common.no_products")
            return

        await ctx.reply_card(_build_product_cards(ctx, products))

    @bot.command(
        "subscribe",
        description="Subscribe to restock notifications for an out-of-stock product.",
        usage="/subscribe <product_id>",
    )
    async def subscribe_command(ctx: CommandContext) -> None:
        if not ctx.args:
            await ctx.reply_warning_t("store.subscribe.usage")
            return

        product_id = ctx.args[0].strip()
        try:
            result = ctx.bot.store.subscribe_product(ctx.author_id, product_id)
        except (StoreError, NotFoundError) as exc:
            await ctx.reply_error(exc)
            return

        await ctx.reply_card(
            build_status_cards(
                ctx.t("store.subscribe.title"),
                body=ctx.t(
                    "store.subscribe.success",
                    product_id=result["product_id"],
                    product_name=result["product_name"],
                ),
                theme="success",
                actions=[
                    build_command_button(ctx.t("button.products"), f"{ctx.bot.settings.command_prefix}products", theme="primary"),
                    build_command_button(
                        ctx.t("button.unsubscribe"),
                        f"{ctx.bot.settings.command_prefix}unsubscribe {result['product_id']}",
                        theme="secondary",
                    ),
                ],
            )
        )

    @bot.command(
        "unsubscribe",
        description="Cancel the restock notification subscription for a product.",
        usage="/unsubscribe <product_id>",
    )
    async def unsubscribe_command(ctx: CommandContext) -> None:
        if not ctx.args:
            await ctx.reply_warning_t("store.unsubscribe.usage")
            return

        product_id = ctx.args[0].strip()
        try:
            result = ctx.bot.store.unsubscribe_product(ctx.author_id, product_id)
        except (StoreError, NotFoundError) as exc:
            await ctx.reply_error(exc)
            return

        await ctx.reply_card(
            build_status_cards(
                ctx.t("store.unsubscribe.title"),
                body=ctx.t(
                    "store.unsubscribe.success",
                    product_id=result["product_id"],
                    product_name=result["product_name"],
                ),
                theme="success",
                actions=[
                    build_command_button(ctx.t("button.products"), f"{ctx.bot.settings.command_prefix}products", theme="primary"),
                    build_command_button(
                        ctx.t("button.subscribe"),
                        f"{ctx.bot.settings.command_prefix}subscribe {result['product_id']}",
                        theme="warning",
                    ),
                ],
            )
        )

    @bot.command(
        "buy",
        description="Buy one or more product keys and receive them in DM.",
        usage="/buy <product_id> [quantity]",
    )
    async def buy_command(ctx: CommandContext) -> None:
        if not ctx.args:
            await ctx.reply_t("store.buy.usage")
            return

        product_id = ctx.args[0].strip()
        quantity = 1
        if len(ctx.args) >= 2:
            try:
                quantity = int(ctx.args[1])
            except ValueError:
                await ctx.reply_t("common.quantity_integer")
                return

        try:
            result = ctx.bot.store.buy_product(ctx.author_id, product_id, quantity=quantity)
        except (StoreError, NotFoundError, OutOfStockError, InsufficientBalanceError) as exc:
            await ctx.reply_error(exc)
            return

        key_lines = [
            ctx.t("store.buy.key_item", index=index, key_content=key_content)
            for index, key_content in enumerate(result["key_contents"], start=1)
        ]
        await ctx.bot.send_direct_card(
            build_text_cards(
                "\n".join(
                    [
                        ctx.t(
                            "store.buy.dm",
                            product_name=result["product_name"],
                            quantity=result["quantity"],
                            total_price=result["total_price"],
                        ),
                        "",
                        *key_lines,
                    ]
                ),
                title=ctx.t("store.buy.dm_title"),
                theme="success",
            ),
            target_id=ctx.author_id,
        )
        await ctx.reply_card(
            build_fact_cards(
                ctx.t("store.buy.summary_title"),
                [
                    (ctx.t("store.buy.field.product_id"), str(result["product_id"])),
                    (ctx.t("store.buy.field.product_name"), str(result["product_name"])),
                    (ctx.t("store.buy.field.quantity"), str(result["quantity"])),
                    (ctx.t("store.buy.field.total_price"), str(result["total_price"])),
                    (ctx.t("store.buy.field.balance_after"), str(result["balance_after"])),
                ],
                theme="success",
                footer=ctx.t("store.buy.success_footer"),
                actions=[
                    build_command_button(ctx.t("button.products"), f"{ctx.bot.settings.command_prefix}products", theme="primary"),
                    build_command_button(ctx.t("button.balance"), f"{ctx.bot.settings.command_prefix}balance", theme="success"),
                ],
            )
        )


def _build_product_cards(ctx: CommandContext, products: list[dict[str, object]]) -> list[dict[str, object]]:
    cards: list[dict[str, object]] = []
    visible_products = products[: MAX_PRODUCT_CARDS * PRODUCTS_PER_CARD]

    for start in range(0, len(visible_products), PRODUCTS_PER_CARD):
        page = visible_products[start : start + PRODUCTS_PER_CARD]
        modules: list[dict[str, object]] = []

        if start == 0:
            modules.append(
                {
                    "type": "header",
                    "text": {
                        "type": "plain-text",
                        "content": ctx.t("store.products.title"),
                    },
                }
            )
            modules.append(
                {
                    "type": "section",
                    "text": {
                        "type": "kmarkdown",
                        "content": ctx.t("store.products.summary", count=len(products)),
                    },
                }
            )
            modules.append({"type": "divider"})

        for index, product in enumerate(page):
            product_id = int(product["id"])
            stock = int(product["stock"])
            description = str(product.get("description") or "-")
            price = str(product.get("price") or "-")
            status_key = "store.products.status_out_of_stock" if stock <= 0 else "store.products.status_in_stock"
            modules.append(
                {
                    "type": "section",
                    "text": {
                        "type": "kmarkdown",
                        "content": ctx.t(
                            "store.products.card_body",
                            product_id=product_id,
                            name=product.get("name", ""),
                            price=price,
                            stock=stock,
                            status=ctx.t(status_key, stock=stock),
                            description=description,
                        ),
                    },
                }
            )
            modules.append(build_action_group(_build_product_buttons(ctx, product_id, stock)))
            modules.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "plain-text",
                            "content": _build_product_tip(ctx, stock),
                        }
                    ],
                }
            )
            if index != len(page) - 1:
                modules.append({"type": "divider"})

        if start + PRODUCTS_PER_CARD >= len(visible_products) and len(products) > len(visible_products):
            modules.append({"type": "divider"})
            modules.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "plain-text",
                            "content": ctx.t(
                                "store.products.truncated",
                                shown=len(visible_products),
                                total=len(products),
                            ),
                        }
                    ],
                }
            )

        cards.append(
            {
                "type": "card",
                "theme": "secondary" if start else "primary",
                "size": "lg",
                "modules": modules,
            }
        )

    return cards


def _build_product_buttons(ctx: CommandContext, product_id: int, stock: int) -> list[dict[str, object]]:
    prefix = ctx.bot.settings.command_prefix
    buttons: list[dict[str, object]] = []
    if stock > 0:
        buttons.append(
            build_command_button(
                ctx.t("button.buy_now"),
                f"{prefix}buy {product_id}",
                theme="success",
            )
        )
        if stock > 1:
            quantity = min(stock, 10)
            buttons.append(
                build_command_button(
                    ctx.t("button.buy_quantity", quantity=quantity),
                    f"{prefix}buy {product_id} {quantity}",
                    theme="primary",
                )
            )
    else:
        buttons.append(
            build_command_button(
                ctx.t("button.subscribe"),
                f"{prefix}subscribe {product_id}",
                theme="warning",
            )
        )
    return buttons


def _build_product_tip(ctx: CommandContext, stock: int) -> str:
    if stock > 1:
        quantity = min(stock, 10)
        return ctx.t("store.products.tip_in_stock", quantity=quantity)
    if stock == 1:
        return ctx.t("store.products.tip_single_stock")
    return ctx.t("store.products.tip_out_of_stock")
