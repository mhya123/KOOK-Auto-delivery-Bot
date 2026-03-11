from __future__ import annotations

import secrets
import time
from datetime import datetime

from ..bot import KookBot
from ..cards import build_command_button, build_status_cards
from ..context import CommandContext
from ..export_utils import build_product_keys_workbook, build_recharge_cards_workbook
from ..logging_utils import get_logger
from ..permissions import Role
from ..store_service import NotFoundError, StoreError

logger = get_logger("kook_bot.store_admin")
DELETE_ALL_KEYS_CONFIRM_TTL_SECONDS = 60


def register(bot: KookBot) -> None:
    @bot.command(
        "gen_card",
        description="Generate recharge cards.",
        usage="/gen_card <amount> <count>",
        required_role=Role.ADMIN,
    )
    async def gen_card_command(ctx: CommandContext) -> None:
        if len(ctx.args) < 2:
            await ctx.reply_warning_t("store.gen_card.usage")
            return

        try:
            amount = int(ctx.args[0])
            count = int(ctx.args[1])
            cards = ctx.bot.store.generate_cards(ctx.author_id, amount, count)
        except (ValueError, StoreError) as exc:
            if isinstance(exc, ValueError):
                await ctx.reply_error(StoreError("error.amount_count_positive"))
            else:
                await ctx.reply_error(exc)
            return

        preview = "\n".join(cards[:10])
        suffix = ""
        if len(cards) > 10:
            suffix = ctx.t("store.gen_card.more_suffix", remaining=len(cards) - 10)
        await ctx.reply_card(
            build_status_cards(
                ctx.t("store.gen_card.title"),
                body=ctx.t("store.gen_card.success", count=len(cards), preview=preview, suffix=suffix),
                facts=[
                    (ctx.t("store.gen_card.field.count"), str(len(cards))),
                ],
                theme="success",
            )
        )

    @bot.command(
        "export_cards",
        description="Export recharge cards to your DM as an Excel file.",
        usage="/export_cards [all]",
        required_role=Role.ADMIN,
    )
    async def export_cards_command(ctx: CommandContext) -> None:
        include_used = bool(ctx.args and ctx.args[0].strip().lower() == "all")
        rows = ctx.bot.store.export_recharge_cards(include_used=include_used)
        if not rows:
            await ctx.reply_t("store.export_cards.empty")
            return

        filename = _build_export_filename("recharge_cards")
        workbook_bytes = build_recharge_cards_workbook(rows)
        await ctx.bot.send_private_file(
            ctx.author_id,
            filename,
            workbook_bytes,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        await ctx.reply_t("store.export_cards.success", count=len(rows))

    @bot.command(
        "export_keys",
        description="Export product keys to your DM as an Excel file.",
        usage="/export_keys <product_id|all>",
        required_role=Role.ADMIN,
    )
    async def export_keys_command(ctx: CommandContext) -> None:
        if not ctx.args:
            await ctx.reply_t("store.export_keys.usage")
            return

        product_id = ctx.args[0].strip()
        try:
            grouped_rows = ctx.bot.store.export_product_keys(product_id)
        except (StoreError, NotFoundError) as exc:
            await ctx.reply_error(exc)
            return

        if not grouped_rows:
            await ctx.reply_t("store.export_keys.empty")
            return

        workbook_bytes = build_product_keys_workbook(grouped_rows)
        filename = _build_export_filename(f"product_keys_{_normalize_export_name(product_id)}")
        await ctx.bot.send_private_file(
            ctx.author_id,
            filename,
            workbook_bytes,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        total_count = sum(len(rows) for rows in grouped_rows.values())
        await ctx.reply_t(
            "store.export_keys.success",
            sheet_count=len(grouped_rows),
            count=total_count,
        )

    @bot.command(
        "del_card",
        description="Delete a recharge card by code.",
        usage="/del_card <card_code>",
        required_role=Role.ADMIN,
    )
    async def delete_card_command(ctx: CommandContext) -> None:
        if not ctx.args:
            await ctx.reply_t("store.del_card.usage")
            return

        deleted = ctx.bot.store.delete_card(ctx.args[0].strip())
        if not deleted:
            await ctx.reply_t("common.card_not_found")
            return
        await ctx.reply_t("common.card_deleted")

    @bot.command(
        "add_product",
        description="Create a new product.",
        usage='/add_product "<name>" "<description>"',
        required_role=Role.ADMIN,
    )
    async def add_product_command(ctx: CommandContext) -> None:
        if len(ctx.args) < 2:
            await ctx.reply_warning_t("store.add_product.usage")
            return

        name = ctx.args[0].strip()
        description = " ".join(ctx.args[1:]).strip()
        try:
            product = ctx.bot.store.add_product(ctx.author_id, name, description)
        except StoreError as exc:
            await ctx.reply_error(exc)
            return

        await ctx.reply_card(
            build_status_cards(
                ctx.t("store.add_product.title"),
                body=ctx.t("store.add_product.success", id=product["id"], name=product["name"]),
                facts=[
                    (ctx.t("store.add_product.field.id"), str(product["id"])),
                    (ctx.t("store.add_product.field.name"), str(product["name"])),
                    (ctx.t("store.add_product.field.description"), str(product["description"])),
                ],
                theme="success",
            )
        )

    @bot.command(
        "add_key",
        description="Add a sellable key to a product.",
        usage='/add_key <product_id> <price> "<key_content>"',
        required_role=Role.ADMIN,
    )
    async def add_key_command(ctx: CommandContext) -> None:
        if len(ctx.args) < 3:
            await ctx.reply_t("store.add_key.usage")
            return

        product_id = ctx.args[0].strip()
        try:
            price = int(ctx.args[1])
        except ValueError:
            await ctx.reply_t("common.price_integer")
            return

        key_content = " ".join(ctx.args[2:]).strip()
        try:
            result = ctx.bot.store.add_key(ctx.author_id, product_id, price, key_content)
        except (StoreError, NotFoundError) as exc:
            await ctx.reply_error(exc)
            return

        await ctx.bot.notify_restock_subscribers(result)

        await ctx.reply_t(
            "store.add_key.success",
            product_id=result["product_id"],
            key_id=result["key_id"],
            price=result["price"],
        )

    @bot.command(
        "add_keys",
        description="Batch add sellable keys to a product.",
        usage='/add_keys <product_id> <price> "<key1\\nkey2\\nkey3>"',
        required_role=Role.ADMIN,
    )
    async def add_keys_command(ctx: CommandContext) -> None:
        if len(ctx.args) < 3:
            await ctx.reply_t("store.add_keys.usage")
            return

        product_id = ctx.args[0].strip()
        try:
            price = int(ctx.args[1])
        except ValueError:
            await ctx.reply_t("common.price_integer")
            return

        raw_text = " ".join(ctx.args[2:]).strip()
        key_contents = _split_key_batch(raw_text)
        try:
            result = ctx.bot.store.add_keys(ctx.author_id, product_id, price, key_contents)
        except (StoreError, NotFoundError) as exc:
            await ctx.reply_error(exc)
            return

        await ctx.bot.notify_restock_subscribers(result)

        await ctx.reply_t(
            "store.add_keys.success",
            product_id=result["product_id"],
            count=result["count"],
            price=result["price"],
            skipped_duplicates=result.get("skipped_duplicates", 0),
        )

    @bot.command(
        "import_file",
        description="Import sellable keys from a txt or csv attachment.",
        usage="/import_file <product_id> <price> [attachment|web]",
        required_role=Role.ADMIN,
    )
    async def import_file_command(ctx: CommandContext) -> None:
        if len(ctx.args) < 2:
            await ctx.reply_warning_t("store.import_file.usage")
            return

        product_id = ctx.args[0].strip()
        try:
            price = int(ctx.args[1])
        except ValueError:
            await ctx.reply_t("common.price_integer")
            return

        mode = ctx.args[2].strip().lower() if len(ctx.args) >= 3 else "attachment"
        if mode in {"file", "attachment", "channel"}:
            pending = ctx.bot.start_pending_import_upload(ctx.event, product_id, price, mode="attachment", ttl_seconds=30)
            body_key = "store.import_file.pending_replaced" if pending.status == "replaced" else "store.import_file.pending_started"
            await ctx.reply_card(
                build_status_cards(
                    ctx.t("store.import_file.pending_title"),
                    body=ctx.t(body_key, seconds=30),
                    facts=[
                        (ctx.t("store.import_file.field.product_id"), product_id),
                        (ctx.t("store.import_file.field.price"), str(price)),
                        (ctx.t("store.import_file.field.expires"), "30s"),
                        (ctx.t("store.import_file.field.mode"), "attachment"),
                    ],
                    theme="warning",
                )
            )
            return

        if mode in {"web", "portal", "url"}:
            if not ctx.bot.import_web_available():
                await ctx.reply_warning_t("store.import_file.web_disabled")
                return

            pending = ctx.bot.start_pending_import_upload(
                ctx.event,
                product_id,
                price,
                mode="web",
                ttl_seconds=ctx.bot.settings.import_web_ttl_seconds,
            )
            upload_url = ctx.bot.build_import_upload_url(pending.upload_id)
            try:
                await ctx.bot.send_direct_card(
                    build_status_cards(
                        ctx.t("store.import_file.web_dm_title"),
                        body=ctx.t(
                            "store.import_file.web_dm_body",
                            url=upload_url,
                            password=pending.password,
                            seconds=ctx.bot.settings.import_web_ttl_seconds,
                        ),
                        facts=[
                            (ctx.t("store.import_file.field.product_id"), product_id),
                            (ctx.t("store.import_file.field.price"), str(price)),
                            (ctx.t("store.import_file.field.mode"), "web"),
                        ],
                        theme="warning",
                    ),
                    target_id=ctx.author_id,
                )
            except Exception:
                logger.exception("failed to send import web dm author_id=%s", ctx.author_id)
                ctx.bot.cancel_pending_import_upload(ctx.author_id)
                await ctx.reply_error(StoreError("store.import_file.web_dm_failed"))
                return

            body_key = "store.import_file.web_pending_replaced" if pending.status == "replaced" else "store.import_file.web_pending_started"
            await ctx.reply_card(
                build_status_cards(
                    ctx.t("store.import_file.web_pending_title"),
                    body=ctx.t(body_key),
                    facts=[
                        (ctx.t("store.import_file.field.product_id"), product_id),
                        (ctx.t("store.import_file.field.price"), str(price)),
                        (ctx.t("store.import_file.field.expires"), str(ctx.bot.settings.import_web_ttl_seconds)),
                        (ctx.t("store.import_file.field.mode"), "web"),
                    ],
                    theme="warning",
                )
            )
            return

        await ctx.reply_warning_t("store.import_file.invalid_mode")

    @bot.command(
        "cancel_import",
        description="Cancel the pending import upload.",
        usage="/cancel_import",
        required_role=Role.ADMIN,
        aliases=("cancelupload",),
    )
    async def cancel_import_command(ctx: CommandContext) -> None:
        cancelled = ctx.bot.cancel_pending_import_upload(ctx.author_id)
        if not cancelled:
            await ctx.reply_warning_t("store.import_file.cancel_empty")
            return
        await ctx.reply_card(
            build_status_cards(
                ctx.t("store.import_file.cancel_title"),
                body=ctx.t("store.import_file.cancel_success"),
                theme="success",
            )
        )

    @bot.command(
        "refund",
        description="Refund a sold key and mark it as void.",
        usage='/refund <user_id> "<key_content>"',
        required_role=Role.ADMIN,
    )
    async def refund_command(ctx: CommandContext) -> None:
        if len(ctx.args) < 2:
            await ctx.reply_warning_t("store.refund.usage")
            return

        target_user_id = ctx.args[0].strip()
        key_content = " ".join(ctx.args[1:]).strip()
        try:
            result = ctx.bot.store.refund_product_key(ctx.author_id, target_user_id, key_content)
        except (StoreError, NotFoundError) as exc:
            await ctx.reply_error(exc)
            return

        try:
            await ctx.bot.send_direct_card(
                build_status_cards(
                    ctx.t("store.refund.dm_title"),
                    body=ctx.t(
                        "store.refund.dm",
                        refund_amount=result["refund_amount"],
                        balance_after=result["balance_after"],
                        product_name=result["product_name"],
                    ),
                    theme="warning",
                ),
                target_id=target_user_id,
            )
        except Exception:
            logger.exception("failed to send refund dm target_user_id=%s", target_user_id)
        await ctx.reply_card(
            build_status_cards(
                ctx.t("store.refund.title"),
                body=ctx.t(
                    "store.refund.success",
                    user_id=result["user_id"],
                    refund_amount=result["refund_amount"],
                ),
                facts=[
                    (ctx.t("store.refund.field.user_id"), str(result["user_id"])),
                    (ctx.t("store.refund.field.product_name"), str(result["product_name"])),
                    (ctx.t("store.refund.field.refund_amount"), str(result["refund_amount"])),
                    (ctx.t("store.refund.field.balance_after"), str(result["balance_after"])),
                ],
                theme="success",
            )
        )

    @bot.command(
        "del_keys",
        description="Delete all keys for a product after confirmation.",
        usage="/del_keys <product_id>",
        required_role=Role.ADMIN,
    )
    async def delete_all_keys_command(ctx: CommandContext) -> None:
        if not ctx.args:
            await ctx.reply_warning_t("store.del_keys.usage")
            return

        product_id = ctx.args[0].strip()
        try:
            stats = ctx.bot.store.get_product_key_stats(product_id)
        except (StoreError, NotFoundError) as exc:
            await ctx.reply_error(exc)
            return

        token = secrets.token_hex(3).upper()
        confirmations = _get_delete_key_confirmations(ctx.bot)
        confirmations[ctx.author_id] = {
            "product_id": str(stats["product_id"]),
            "token": token,
            "expires_at": int(time.time()) + DELETE_ALL_KEYS_CONFIRM_TTL_SECONDS,
        }
        await ctx.reply_card(
            build_status_cards(
                ctx.t("store.del_keys.confirm_title"),
                body=ctx.t(
                    "store.del_keys.confirm_body",
                    product_id=stats["product_id"],
                    product_name=stats["product_name"],
                    seconds=DELETE_ALL_KEYS_CONFIRM_TTL_SECONDS,
                ),
                facts=[
                    (ctx.t("store.del_keys.field.total"), str(stats["total_count"])),
                    (ctx.t("store.del_keys.field.available"), str(stats["available_count"])),
                    (ctx.t("store.del_keys.field.sold"), str(stats["sold_count"])),
                    (ctx.t("store.del_keys.field.void"), str(stats["void_count"])),
                    (ctx.t("store.del_keys.field.token"), token),
                ],
                theme="warning",
                actions=[
                    build_command_button(
                        ctx.t("store.del_keys.confirm_button"),
                        f"{ctx.bot.settings.command_prefix}confirm_del_keys {stats['product_id']} {token}",
                        theme="danger",
                    ),
                    build_command_button(
                        ctx.t("store.del_keys.cancel_button"),
                        f"{ctx.bot.settings.command_prefix}cancel_del_keys {stats['product_id']}",
                        theme="secondary",
                    ),
                ],
            )
        )

    @bot.command(
        "confirm_del_keys",
        description="Confirm deleting all keys for a product.",
        usage="/confirm_del_keys <product_id> <token>",
        required_role=Role.ADMIN,
    )
    async def confirm_delete_all_keys_command(ctx: CommandContext) -> None:
        if len(ctx.args) < 2:
            await ctx.reply_warning_t("store.del_keys.confirm_usage")
            return

        product_id = ctx.args[0].strip()
        token = ctx.args[1].strip().upper()
        confirmations = _get_delete_key_confirmations(ctx.bot)
        pending = confirmations.get(ctx.author_id)
        if pending is None:
            await ctx.reply_warning_t("store.del_keys.no_pending")
            return
        if int(pending.get("expires_at", 0)) <= int(time.time()):
            confirmations.pop(ctx.author_id, None)
            await ctx.reply_warning_t("store.del_keys.expired")
            return
        if str(pending.get("product_id")) != product_id or str(pending.get("token")) != token:
            await ctx.reply_warning_t("store.del_keys.token_invalid")
            return

        try:
            result = ctx.bot.store.delete_all_product_keys(ctx.author_id, product_id)
        except (StoreError, NotFoundError) as exc:
            await ctx.reply_error(exc)
            return
        finally:
            confirmations.pop(ctx.author_id, None)

        await ctx.reply_card(
            build_status_cards(
                ctx.t("store.del_keys.success_title"),
                body=ctx.t(
                    "store.del_keys.success_body",
                    product_id=result["product_id"],
                    product_name=result["product_name"],
                    count=result["deleted_count"],
                ),
                facts=[
                    (ctx.t("store.del_keys.field.deleted"), str(result["deleted_count"])),
                    (ctx.t("store.del_keys.field.available"), str(result["available_count"])),
                    (ctx.t("store.del_keys.field.sold"), str(result["sold_count"])),
                    (ctx.t("store.del_keys.field.void"), str(result["void_count"])),
                ],
                theme="success",
            )
        )

    @bot.command(
        "cancel_del_keys",
        description="Cancel deleting all keys for a product.",
        usage="/cancel_del_keys <product_id>",
        required_role=Role.ADMIN,
    )
    async def cancel_delete_all_keys_command(ctx: CommandContext) -> None:
        confirmations = _get_delete_key_confirmations(ctx.bot)
        pending = confirmations.get(ctx.author_id)
        if pending is None:
            await ctx.reply_warning_t("store.del_keys.no_pending")
            return

        if ctx.args and str(pending.get("product_id")) != ctx.args[0].strip():
            await ctx.reply_warning_t("store.del_keys.token_invalid")
            return

        confirmations.pop(ctx.author_id, None)
        await ctx.reply_card(
            build_status_cards(
                ctx.t("store.del_keys.cancel_title"),
                body=ctx.t("store.del_keys.cancel_success"),
                theme="success",
            )
        )


def _split_key_batch(raw_text: str) -> list[str]:
    normalized = raw_text.replace("\\n", "\n")
    if "\n" in normalized:
        return [line.strip() for line in normalized.splitlines() if line.strip()]
    if "||" in normalized:
        return [line.strip() for line in normalized.split("||") if line.strip()]
    return [normalized.strip()] if normalized.strip() else []


def _build_export_filename(prefix: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{timestamp}.xlsx"


def _normalize_export_name(raw: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in raw.strip())
    return safe[:32] or "data"


def _get_delete_key_confirmations(bot: KookBot) -> dict[str, dict[str, object]]:
    store = getattr(bot, "_pending_delete_key_confirmations", None)
    if isinstance(store, dict):
        return store
    store = {}
    setattr(bot, "_pending_delete_key_confirmations", store)
    return store
