from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from ..bot import KookBot
from ..cards import build_status_cards
from ..context import CommandContext
from ..export_utils import build_product_keys_workbook, build_recharge_cards_workbook
from ..permissions import Role
from ..store_service import NotFoundError, StoreError


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

        await ctx.reply_t(
            "store.add_keys.success",
            product_id=result["product_id"],
            count=result["count"],
            price=result["price"],
        )

    @bot.command(
        "import_file",
        description="Import sellable keys from a txt or csv attachment.",
        usage="/import_file <product_id> <price>",
        required_role=Role.ADMIN,
    )
    async def import_file_command(ctx: CommandContext) -> None:
        if len(ctx.args) < 2:
            await ctx.reply_t("store.import_file.usage")
            return

        attachment = _pick_import_attachment(ctx.attachments)
        if attachment is None:
            await ctx.reply_t("store.import_file.missing_attachment")
            return

        product_id = ctx.args[0].strip()
        try:
            price = int(ctx.args[1])
        except ValueError:
            await ctx.reply_t("common.price_integer")
            return

        if not _is_supported_import_attachment(attachment):
            await ctx.reply_t("store.import_file.invalid_attachment", file_name=attachment.get("name") or "unknown")
            return

        attachment_url = attachment.get("url", "").strip()
        if not attachment_url:
            await ctx.reply_t("store.import_file.invalid_attachment", file_name=attachment.get("name") or "unknown")
            return

        try:
            raw_bytes = await ctx.bot.download_attachment_bytes(attachment_url)
        except Exception:
            await ctx.reply_t("store.import_file.download_failed")
            return

        key_contents = _decode_import_file(raw_bytes).splitlines()
        try:
            result = ctx.bot.store.import_keys(ctx.author_id, product_id, price, key_contents)
        except (StoreError, NotFoundError) as exc:
            await ctx.reply_error(exc)
            return

        await ctx.reply_t(
            "store.import_file.success",
            product_id=result["product_id"],
            parsed_total=result["parsed_total"],
            inserted_count=result["inserted_count"],
            skipped_duplicates=result["skipped_duplicates"],
        )


def _split_key_batch(raw_text: str) -> list[str]:
    normalized = raw_text.replace("\\n", "\n")
    if "\n" in normalized:
        return [line.strip() for line in normalized.splitlines() if line.strip()]
    if "||" in normalized:
        return [line.strip() for line in normalized.split("||") if line.strip()]
    return [normalized.strip()] if normalized.strip() else []


def _pick_import_attachment(attachments: Iterable[dict[str, str]]) -> dict[str, str] | None:
    for attachment in attachments:
        if _is_supported_import_attachment(attachment):
            return attachment
    for attachment in attachments:
        return attachment
    return None


def _is_supported_import_attachment(attachment: dict[str, str]) -> bool:
    name = attachment.get("name", "").lower()
    url = attachment.get("url", "").lower()
    file_type = attachment.get("file_type", "").lower()
    return (
        name.endswith(".txt")
        or name.endswith(".csv")
        or url.endswith(".txt")
        or url.endswith(".csv")
        or file_type in {"txt", "csv", "text/plain", "text/csv"}
    )


def _decode_import_file(raw_bytes: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="replace")


def _build_export_filename(prefix: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{timestamp}.xlsx"


def _normalize_export_name(raw: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in raw.strip())
    return safe[:32] or "data"
