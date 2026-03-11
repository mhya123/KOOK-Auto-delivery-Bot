from __future__ import annotations

from ..bot import KookBot
from ..cards import build_command_button, build_status_cards
from ..context import CommandContext
from ..permissions import Role
from ..runtime_settings import RuntimeSettingError
from ..store_service import StoreError

SETTINGS_PAGE_GENERAL = 1
SETTINGS_PAGE_PAYMENT = 2
SETTINGS_PAGE_LOGGING = 3
SETTINGS_PAGE_TOTAL = 3


def register(bot: KookBot) -> None:
    access_check = lambda current_bot, user_id: current_bot.can_manage_runtime_settings(user_id)

    @bot.command(
        "settings",
        description="Open the admin runtime settings panel.",
        usage="/settings [page]",
        required_role=Role.ADMIN,
        access_check=access_check,
    )
    async def settings_command(ctx: CommandContext) -> None:
        page = _parse_page(ctx.args[0]) if ctx.args else SETTINGS_PAGE_GENERAL
        await ctx.reply_card(_build_settings_cards(ctx, page))

    @bot.command(
        "settings_apply",
        usage="/settings_apply <page> <action> [value...]",
        required_role=Role.ADMIN,
        hidden=True,
        access_check=access_check,
    )
    async def settings_apply_command(ctx: CommandContext) -> None:
        if len(ctx.args) < 2:
            await ctx.reply_warning_t("settings.invalid_action")
            return

        page = _parse_page(ctx.args[0])
        action = ctx.args[1].strip().lower()
        values = ctx.args[2:]
        try:
            if action == "locale":
                if not values:
                    raise RuntimeSettingError("settings.invalid_action")
                ctx.bot.runtime_settings.set_locale(values[0])
                notice = ctx.t("settings.notice.saved", item=ctx.t("settings.item.locale"))
            elif action == "payment_enabled":
                if not values:
                    raise RuntimeSettingError("settings.invalid_action")
                ctx.bot.runtime_settings.set_payment_enabled(_parse_bool_value(values[0]))
                notice = ctx.t("settings.notice.saved", item=ctx.t("settings.item.payment_enabled"))
            elif action == "custom_amount_enabled":
                if not values:
                    raise RuntimeSettingError("settings.invalid_action")
                ctx.bot.runtime_settings.set_payment_custom_amount_enabled(_parse_bool_value(values[0]))
                notice = ctx.t("settings.notice.saved", item=ctx.t("settings.item.custom_amount_enabled"))
            elif action == "pay_preset":
                if not values:
                    raise RuntimeSettingError("settings.invalid_action")
                amounts = [int(item) for item in values[0].split(",") if item.strip()]
                ctx.bot.store.replace_payment_amounts(ctx.author_id, amounts)
                notice = ctx.t("settings.notice.saved", item=ctx.t("settings.item.payment_amounts"))
            elif action == "admin_channel":
                if not values:
                    raise RuntimeSettingError("settings.invalid_action")
                channel_value = _resolve_channel_value(ctx, values[0])
                ctx.bot.runtime_settings.set_admin_channel_id(channel_value)
                notice = ctx.t("settings.notice.saved", item=ctx.t("settings.item.admin_channel"))
            elif action == "log_channel":
                if not values:
                    raise RuntimeSettingError("settings.invalid_action")
                channel_value = _resolve_channel_value(ctx, values[0])
                ctx.bot.runtime_settings.set_log_channel_id(channel_value)
                notice = ctx.t("settings.notice.saved", item=ctx.t("settings.item.log_channel"))
            elif action == "log_flag":
                if len(values) < 2:
                    raise RuntimeSettingError("settings.invalid_action")
                ctx.bot.runtime_settings.set_log_flag(values[0], _parse_bool_value(values[1]))
                notice = ctx.t("settings.notice.saved", item=_log_flag_label(ctx, values[0]))
            elif action == "card_format":
                if not values:
                    raise RuntimeSettingError("settings.invalid_action")
                ctx.bot.runtime_settings.set_recharge_card_format(" ".join(values))
                notice = ctx.t("settings.notice.saved", item=ctx.t("settings.item.card_format"))
            elif action == "card_length":
                if not values:
                    raise RuntimeSettingError("settings.invalid_action")
                ctx.bot.runtime_settings.set_recharge_card_random_length(int(values[0]))
                notice = ctx.t("settings.notice.saved", item=ctx.t("settings.item.card_length"))
            else:
                raise RuntimeSettingError("settings.invalid_action")
        except (RuntimeSettingError, StoreError, ValueError) as exc:
            if isinstance(exc, ValueError):
                await ctx.reply_warning_t("settings.invalid_action")
            else:
                await ctx.reply_error(exc)
            return

        await ctx.reply_card(_build_settings_cards(ctx, page, notice=notice))

    @bot.command(
        "set_locale",
        description="Set the bot locale at runtime.",
        usage="/set_locale <locale>",
        required_role=Role.ADMIN,
        access_check=access_check,
    )
    async def set_locale_command(ctx: CommandContext) -> None:
        if not ctx.args:
            await ctx.reply_warning_t("settings.set_locale_usage")
            return
        try:
            ctx.bot.runtime_settings.set_locale(ctx.args[0])
        except RuntimeSettingError as exc:
            await ctx.reply_error(exc)
            return
        await ctx.reply_card(_build_settings_cards(ctx, SETTINGS_PAGE_GENERAL, notice=ctx.t("settings.notice.saved", item=ctx.t("settings.item.locale"))))

    @bot.command(
        "set_admin_channel",
        description="Set the admin command channel at runtime.",
        usage="/set_admin_channel <channel_id|current|off>",
        required_role=Role.ADMIN,
        access_check=access_check,
    )
    async def set_admin_channel_command(ctx: CommandContext) -> None:
        if not ctx.args:
            await ctx.reply_warning_t("settings.set_admin_channel_usage")
            return
        try:
            ctx.bot.runtime_settings.set_admin_channel_id(_resolve_channel_value(ctx, ctx.args[0]))
        except RuntimeSettingError as exc:
            await ctx.reply_error(exc)
            return
        await ctx.reply_card(_build_settings_cards(ctx, SETTINGS_PAGE_GENERAL, notice=ctx.t("settings.notice.saved", item=ctx.t("settings.item.admin_channel"))))

    @bot.command(
        "set_log_channel",
        description="Set the log push channel at runtime.",
        usage="/set_log_channel <channel_id|current|off>",
        required_role=Role.ADMIN,
        access_check=access_check,
    )
    async def set_log_channel_command(ctx: CommandContext) -> None:
        if not ctx.args:
            await ctx.reply_warning_t("settings.set_log_channel_usage")
            return
        try:
            ctx.bot.runtime_settings.set_log_channel_id(_resolve_channel_value(ctx, ctx.args[0]))
        except RuntimeSettingError as exc:
            await ctx.reply_error(exc)
            return
        await ctx.reply_card(_build_settings_cards(ctx, SETTINGS_PAGE_GENERAL, notice=ctx.t("settings.notice.saved", item=ctx.t("settings.item.log_channel"))))

    @bot.command(
        "set_custom_amount_range",
        description="Set the custom payment amount range at runtime.",
        usage="/set_custom_amount_range <min> <max>",
        required_role=Role.ADMIN,
        access_check=access_check,
    )
    async def set_custom_amount_range_command(ctx: CommandContext) -> None:
        if len(ctx.args) < 2:
            await ctx.reply_warning_t("settings.set_custom_amount_range_usage")
            return
        try:
            minimum = int(ctx.args[0])
            maximum = int(ctx.args[1])
            ctx.bot.runtime_settings.set_payment_custom_amount_range(minimum, maximum)
        except (RuntimeSettingError, ValueError) as exc:
            if isinstance(exc, ValueError):
                await ctx.reply_error(RuntimeSettingError("error.runtime.custom_amount_range_invalid"))
            else:
                await ctx.reply_error(exc)
            return
        await ctx.reply_card(_build_settings_cards(ctx, SETTINGS_PAGE_PAYMENT, notice=ctx.t("settings.notice.saved", item=ctx.t("settings.item.custom_amount_range"))))

    @bot.command(
        "set_card_format",
        description="Set the recharge card template at runtime.",
        usage='/set_card_format "<template>"',
        required_role=Role.ADMIN,
        access_check=access_check,
    )
    async def set_card_format_command(ctx: CommandContext) -> None:
        if not ctx.args:
            await ctx.reply_warning_t("settings.set_card_format_usage")
            return
        try:
            ctx.bot.runtime_settings.set_recharge_card_format(" ".join(ctx.args))
        except RuntimeSettingError as exc:
            await ctx.reply_error(exc)
            return
        await ctx.reply_card(_build_settings_cards(ctx, SETTINGS_PAGE_LOGGING, notice=ctx.t("settings.notice.saved", item=ctx.t("settings.item.card_format"))))

    @bot.command(
        "set_card_length",
        description="Set the recharge card random length at runtime.",
        usage="/set_card_length <length>",
        required_role=Role.ADMIN,
        access_check=access_check,
    )
    async def set_card_length_command(ctx: CommandContext) -> None:
        if not ctx.args:
            await ctx.reply_warning_t("settings.set_card_length_usage")
            return
        try:
            ctx.bot.runtime_settings.set_recharge_card_random_length(int(ctx.args[0]))
        except (RuntimeSettingError, ValueError) as exc:
            if isinstance(exc, ValueError):
                await ctx.reply_error(RuntimeSettingError("error.runtime.card_length_invalid"))
            else:
                await ctx.reply_error(exc)
            return
        await ctx.reply_card(_build_settings_cards(ctx, SETTINGS_PAGE_LOGGING, notice=ctx.t("settings.notice.saved", item=ctx.t("settings.item.card_length"))))

    @bot.command(
        "set_card_alphabet",
        description="Set the recharge card random alphabet at runtime.",
        usage='/set_card_alphabet "<alphabet>"',
        required_role=Role.ADMIN,
        access_check=access_check,
    )
    async def set_card_alphabet_command(ctx: CommandContext) -> None:
        if not ctx.args:
            await ctx.reply_warning_t("settings.set_card_alphabet_usage")
            return
        try:
            ctx.bot.runtime_settings.set_recharge_card_alphabet(" ".join(ctx.args))
        except RuntimeSettingError as exc:
            await ctx.reply_error(exc)
            return
        await ctx.reply_card(_build_settings_cards(ctx, SETTINGS_PAGE_LOGGING, notice=ctx.t("settings.notice.saved", item=ctx.t("settings.item.card_alphabet"))))


def _build_settings_cards(
    ctx: CommandContext,
    page: int,
    *,
    notice: str = "",
) -> list[dict[str, object]]:
    current_page = max(SETTINGS_PAGE_GENERAL, min(SETTINGS_PAGE_TOTAL, page))
    if current_page == SETTINGS_PAGE_PAYMENT:
        return _build_payment_settings_cards(ctx, notice=notice)
    if current_page == SETTINGS_PAGE_LOGGING:
        return _build_logging_settings_cards(ctx, notice=notice)
    return _build_general_settings_cards(ctx, notice=notice)


def _build_general_settings_cards(ctx: CommandContext, *, notice: str) -> list[dict[str, object]]:
    body_lines = []
    if notice:
        body_lines.append(f"**{notice}**")
        body_lines.append("")
    body_lines.extend(
        [
            ctx.t("settings.general.body"),
            "",
            f"`{ctx.bot.settings.command_prefix}set_locale <locale>`",
            f"`{ctx.bot.settings.command_prefix}set_admin_channel <channel_id|current|off>`",
            f"`{ctx.bot.settings.command_prefix}set_log_channel <channel_id|current|off>`",
        ]
    )
    locales = ", ".join(ctx.bot.translator.available_locales()) or "-"
    return build_status_cards(
        ctx.t("settings.general.title"),
        body="\n".join(body_lines),
        facts=[
            (ctx.t("settings.field.page"), _page_label(ctx, SETTINGS_PAGE_GENERAL)),
            (ctx.t("settings.item.locale"), str(ctx.bot.settings.locale)),
            (ctx.t("settings.field.available_locales"), locales),
            (ctx.t("settings.item.admin_channel"), _display_channel_value(ctx.bot.settings.admin_command_channel_id, ctx)),
            (ctx.t("settings.item.log_channel"), _display_channel_value(ctx.bot.settings.log_channel_id, ctx)),
        ],
        theme="primary",
        actions=_navigation_buttons(ctx, SETTINGS_PAGE_GENERAL)
        + [
            build_command_button(ctx.t("settings.button.locale_zh"), f"{ctx.bot.settings.command_prefix}settings_apply 1 locale zh-CN", theme="primary"),
            build_command_button(ctx.t("settings.button.locale_en"), f"{ctx.bot.settings.command_prefix}settings_apply 1 locale en-US", theme="secondary"),
            build_command_button(ctx.t("settings.button.admin_channel_current"), f"{ctx.bot.settings.command_prefix}settings_apply 1 admin_channel current", theme="warning"),
            build_command_button(ctx.t("settings.button.admin_channel_off"), f"{ctx.bot.settings.command_prefix}settings_apply 1 admin_channel off", theme="secondary"),
            build_command_button(ctx.t("settings.button.log_channel_current"), f"{ctx.bot.settings.command_prefix}settings_apply 1 log_channel current", theme="warning"),
            build_command_button(ctx.t("settings.button.log_channel_off"), f"{ctx.bot.settings.command_prefix}settings_apply 1 log_channel off", theme="secondary"),
        ],
    )


def _build_payment_settings_cards(ctx: CommandContext, *, notice: str) -> list[dict[str, object]]:
    amounts = ctx.bot.store.list_payment_amounts()
    body_lines = []
    if notice:
        body_lines.append(f"**{notice}**")
        body_lines.append("")
    body_lines.extend(
        [
            ctx.t("settings.payment.body"),
            "",
            f"`{ctx.bot.settings.command_prefix}set_pay_amounts <amount1> <amount2> ...`",
            f"`{ctx.bot.settings.command_prefix}set_custom_amount_range <min> <max>`",
        ]
    )
    return build_status_cards(
        ctx.t("settings.payment.title"),
        body="\n".join(body_lines),
        facts=[
            (ctx.t("settings.field.page"), _page_label(ctx, SETTINGS_PAGE_PAYMENT)),
            (ctx.t("settings.item.payment_enabled"), _bool_label(ctx, ctx.bot.settings.payment_enabled)),
            (ctx.t("settings.item.payment_amounts"), ", ".join(str(item) for item in amounts) or ctx.t("settings.value.unset")),
            (ctx.t("settings.item.custom_amount_enabled"), _bool_label(ctx, ctx.bot.settings.payment_allow_custom_amount)),
            (
                ctx.t("settings.item.custom_amount_range"),
                f"{ctx.bot.settings.payment_custom_amount_min} - {ctx.bot.settings.payment_custom_amount_max}",
            ),
        ],
        theme="warning",
        actions=_navigation_buttons(ctx, SETTINGS_PAGE_PAYMENT)
        + [
            build_command_button(ctx.t("settings.button.payment_on"), f"{ctx.bot.settings.command_prefix}settings_apply 2 payment_enabled on", theme="success"),
            build_command_button(ctx.t("settings.button.payment_off"), f"{ctx.bot.settings.command_prefix}settings_apply 2 payment_enabled off", theme="secondary"),
            build_command_button(ctx.t("settings.button.custom_amount_on"), f"{ctx.bot.settings.command_prefix}settings_apply 2 custom_amount_enabled on", theme="success"),
            build_command_button(ctx.t("settings.button.custom_amount_off"), f"{ctx.bot.settings.command_prefix}settings_apply 2 custom_amount_enabled off", theme="secondary"),
            build_command_button(ctx.t("settings.button.pay_preset_basic"), f"{ctx.bot.settings.command_prefix}settings_apply 2 pay_preset 5,10,20,50", theme="primary"),
            build_command_button(ctx.t("settings.button.pay_preset_full"), f"{ctx.bot.settings.command_prefix}settings_apply 2 pay_preset 5,10,20,50,80,100,200", theme="primary"),
        ],
    )


def _build_logging_settings_cards(ctx: CommandContext, *, notice: str) -> list[dict[str, object]]:
    body_lines = []
    if notice:
        body_lines.append(f"**{notice}**")
        body_lines.append("")
    body_lines.extend(
        [
            ctx.t("settings.logging.body"),
            "",
            f"`{ctx.bot.settings.command_prefix}set_card_format \"<template>\"`",
            f"`{ctx.bot.settings.command_prefix}set_card_length <length>`",
            f"`{ctx.bot.settings.command_prefix}set_card_alphabet \"<alphabet>\"`",
        ]
    )
    return build_status_cards(
        ctx.t("settings.logging.title"),
        body="\n".join(body_lines),
        facts=[
            (ctx.t("settings.field.page"), _page_label(ctx, SETTINGS_PAGE_LOGGING)),
            (ctx.t("settings.item.log_http"), _bool_label(ctx, ctx.bot.settings.log_http)),
            (ctx.t("settings.item.log_events"), _bool_label(ctx, ctx.bot.settings.log_events)),
            (ctx.t("settings.item.log_commands"), _bool_label(ctx, ctx.bot.settings.log_commands)),
            (ctx.t("settings.item.log_command_status"), _bool_label(ctx, ctx.bot.settings.log_command_status)),
            (ctx.t("settings.item.log_imports"), _bool_label(ctx, ctx.bot.settings.log_imports)),
            (ctx.t("settings.item.log_to_file"), _bool_label(ctx, ctx.bot.settings.log_to_file)),
            (ctx.t("settings.item.card_format"), str(ctx.bot.settings.recharge_card_format)),
            (ctx.t("settings.item.card_length"), str(ctx.bot.settings.recharge_card_random_length)),
            (ctx.t("settings.item.card_alphabet"), _short_text(ctx.bot.settings.recharge_card_alphabet)),
        ],
        theme="secondary",
        actions=_navigation_buttons(ctx, SETTINGS_PAGE_LOGGING)
        + [
            _log_toggle_button(ctx, "http", ctx.bot.settings.log_http),
            _log_toggle_button(ctx, "events", ctx.bot.settings.log_events),
            _log_toggle_button(ctx, "commands", ctx.bot.settings.log_commands),
            _log_toggle_button(ctx, "command_status", ctx.bot.settings.log_command_status),
            _log_toggle_button(ctx, "imports", ctx.bot.settings.log_imports),
            _log_toggle_button(ctx, "to_file", ctx.bot.settings.log_to_file),
            build_command_button(ctx.t("settings.button.card_format_default"), f"{ctx.bot.settings.command_prefix}settings_apply 3 card_format RC-{{random}}", theme="primary"),
            build_command_button(ctx.t("settings.button.card_format_timestamp"), f"{ctx.bot.settings.command_prefix}settings_apply 3 card_format RC-{{timestamp}}-{{random}}", theme="primary"),
            build_command_button(ctx.t("settings.button.card_length_8"), f"{ctx.bot.settings.command_prefix}settings_apply 3 card_length 8", theme="warning"),
            build_command_button(ctx.t("settings.button.card_length_16"), f"{ctx.bot.settings.command_prefix}settings_apply 3 card_length 16", theme="warning"),
            build_command_button(ctx.t("settings.button.card_length_24"), f"{ctx.bot.settings.command_prefix}settings_apply 3 card_length 24", theme="warning"),
        ],
    )


def _navigation_buttons(ctx: CommandContext, current_page: int) -> list[dict[str, object]]:
    prefix = ctx.bot.settings.command_prefix
    pages = [
        (SETTINGS_PAGE_GENERAL, ctx.t("settings.button.nav_general"), "primary"),
        (SETTINGS_PAGE_PAYMENT, ctx.t("settings.button.nav_payment"), "warning"),
        (SETTINGS_PAGE_LOGGING, ctx.t("settings.button.nav_logging"), "secondary"),
    ]
    buttons: list[dict[str, object]] = []
    for page_number, label, theme in pages:
        buttons.append(
            build_command_button(
                label,
                f"{prefix}settings {page_number}",
                theme=theme if page_number != current_page else "success",
            )
        )
    return buttons


def _log_toggle_button(ctx: CommandContext, flag_name: str, current_value: bool) -> dict[str, object]:
    next_value = "off" if current_value else "on"
    return build_command_button(
        ctx.t("settings.button.log_toggle", name=_log_flag_label(ctx, flag_name), value=ctx.t(f"settings.value.{next_value}")),
        f"{ctx.bot.settings.command_prefix}settings_apply 3 log_flag {flag_name} {next_value}",
        theme="secondary" if current_value else "success",
    )


def _resolve_channel_value(ctx: CommandContext, raw_value: str) -> str:
    normalized = raw_value.strip().lower()
    if normalized == "current":
        if ctx.event.is_direct or not ctx.event.target_id:
            raise RuntimeSettingError("error.runtime.current_channel_required")
        return ctx.event.target_id
    return raw_value


def _parse_bool_value(raw_value: str) -> bool:
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on", "enable", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disable", "disabled"}:
        return False
    raise RuntimeSettingError("settings.invalid_action")


def _parse_page(raw_value: str) -> int:
    normalized = raw_value.strip().lower()
    aliases = {
        "1": SETTINGS_PAGE_GENERAL,
        "general": SETTINGS_PAGE_GENERAL,
        "base": SETTINGS_PAGE_GENERAL,
        "2": SETTINGS_PAGE_PAYMENT,
        "payment": SETTINGS_PAGE_PAYMENT,
        "pay": SETTINGS_PAGE_PAYMENT,
        "3": SETTINGS_PAGE_LOGGING,
        "logging": SETTINGS_PAGE_LOGGING,
        "logs": SETTINGS_PAGE_LOGGING,
    }
    return aliases.get(normalized, SETTINGS_PAGE_GENERAL)


def _page_label(ctx: CommandContext, current_page: int) -> str:
    return f"{current_page}/{SETTINGS_PAGE_TOTAL}"


def _bool_label(ctx: CommandContext, value: bool) -> str:
    return ctx.t("settings.value.on") if value else ctx.t("settings.value.off")


def _display_channel_value(channel_id: str, ctx: CommandContext) -> str:
    return channel_id or ctx.t("settings.value.unset")


def _short_text(value: str, *, limit: int = 32) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text or "-"
    return f"{text[: limit - 3]}..."


def _log_flag_label(ctx: CommandContext, flag_name: str) -> str:
    mapping = {
        "http": ctx.t("settings.item.log_http"),
        "events": ctx.t("settings.item.log_events"),
        "commands": ctx.t("settings.item.log_commands"),
        "command_status": ctx.t("settings.item.log_command_status"),
        "imports": ctx.t("settings.item.log_imports"),
        "to_file": ctx.t("settings.item.log_to_file"),
    }
    return mapping.get(flag_name.strip().lower(), flag_name)
