from __future__ import annotations

from ..bot import KookBot
from ..cards import build_fact_cards, build_text_cards
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

        product_lines = [ctx.t("store.products.item", **product) for product in products]
        await ctx.reply_card(
            build_text_cards(
                "\n".join(product_lines),
                title=ctx.t("store.products.title"),
                theme="secondary",
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
