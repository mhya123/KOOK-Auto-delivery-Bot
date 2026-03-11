from __future__ import annotations

from ..bot import KookBot
from ..cards import build_fact_cards, build_status_cards, build_text_cards
from ..context import CommandContext
from ..store_service import InsufficientBalanceError, NotFoundError, OutOfStockError, StoreError


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

        product_lines = []
        for product in products:
            status_key = "store.products.status_out_of_stock" if int(product["stock"]) == 0 else "store.products.status_in_stock"
            product_lines.append(
                ctx.t(
                    "store.products.item",
                    **product,
                    status=ctx.t(status_key, stock=product["stock"]),
                )
            )
        await ctx.reply_card(
            build_text_cards(
                "\n".join(product_lines),
                title=ctx.t("store.products.title"),
                theme="secondary",
            )
        )

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
            )
        )
