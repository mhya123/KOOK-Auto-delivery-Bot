from __future__ import annotations

from math import ceil

from ..bot import KookBot
from ..cards import build_action_groups, build_command_button
from ..commands import CommandSpec
from ..context import CommandContext
from ..permissions import Role

ROLE_ORDER = (Role.USER, Role.ADMIN, Role.SUPER_ADMIN)
ROLE_THEMES = {
    Role.USER: "primary",
    Role.ADMIN: "warning",
    Role.SUPER_ADMIN: "danger",
}
MAX_HELP_CARDS = 5
HELP_COMMANDS_PER_PAGE = 8
HELP_COMMANDS_PER_CARD = 4


def register(bot: KookBot) -> None:
    @bot.command(
        "help",
        description="Show all available commands.",
        usage="/help",
        aliases=("commands",),
    )
    async def help_command(ctx: CommandContext) -> None:
        visible_commands = ctx.bot.commands.visible_commands(ctx.author_role, bot=ctx.bot, user_id=ctx.author_id)
        page = 1
        if ctx.args:
            try:
                page = max(1, int(ctx.args[0]))
            except ValueError:
                page = 1
        await ctx.reply_card(_build_help_cards(ctx, visible_commands, page=page))


def _build_help_cards(ctx: CommandContext, commands: tuple[CommandSpec, ...], *, page: int) -> list[dict[str, object]]:
    grouped = _group_commands(commands)
    total_pages = max(1, ceil(len(commands) / HELP_COMMANDS_PER_PAGE)) if commands else 1
    current_page = min(max(1, page), total_pages)
    start = (current_page - 1) * HELP_COMMANDS_PER_PAGE
    visible_commands = commands[start : start + HELP_COMMANDS_PER_PAGE]
    visible_grouped = _group_commands(visible_commands)
    cards: list[dict[str, object]] = []

    cards.append(_build_overview_card(ctx, len(commands), grouped, current_page=current_page, total_pages=total_pages))

    for role in ROLE_ORDER:
        role_commands = visible_grouped.get(role, ())
        if not role_commands:
            continue
        cards.extend(
            _build_role_cards(
                ctx,
                role,
                role_commands,
                commands_per_card=HELP_COMMANDS_PER_CARD,
            )
        )

    return cards[:MAX_HELP_CARDS] or [_build_empty_help_card(ctx)]


def _build_role_cards(
    ctx: CommandContext,
    role: str,
    commands: tuple[CommandSpec, ...],
    *,
    commands_per_card: int,
) -> list[dict[str, object]]:
    cards: list[dict[str, object]] = []
    title = ctx.t("help.section_title", role=ctx.t(f"role.{role}"), count=len(commands))
    theme = ROLE_THEMES.get(role, "secondary")

    for start in range(0, len(commands), commands_per_card):
        page = commands[start : start + commands_per_card]
        modules: list[dict[str, object]] = []

        modules.append(
            {
                "type": "header",
                "text": {
                    "type": "plain-text",
                    "content": title if start == 0 else ctx.t("help.section_continue", role=ctx.t(f"role.{role}")),
                },
            }
        )
        modules.append({"type": "divider"})

        for index, spec in enumerate(page):
            modules.append(
                {
                    "type": "section",
                    "text": {
                        "type": "kmarkdown",
                        "content": _build_command_text(ctx, spec),
                    },
                }
            )
            if index != len(page) - 1:
                modules.append({"type": "divider"})

        cards.append(
            {
                "type": "card",
                "theme": theme if start == 0 else "secondary",
                "size": "lg",
                "modules": modules,
            }
        )

    return cards


def _build_overview_card(
    ctx: CommandContext,
    total_commands: int,
    grouped: dict[str, tuple[CommandSpec, ...]],
    *,
    current_page: int,
    total_pages: int,
) -> dict[str, object]:
    role_name = ctx.t(f"role.{ctx.author_role}")
    group_lines = [
        ctx.t(
            "help.section_summary",
            role=ctx.t(f"role.{role}"),
            count=len(grouped.get(role, ())),
        )
        for role in ROLE_ORDER
        if grouped.get(role)
    ]
    overview_lines = [
        ctx.t("help.meta", role=role_name, prefix=ctx.bot.settings.command_prefix, count=total_commands),
        "",
        ctx.t("help.intro"),
    ]
    if group_lines:
        overview_lines.extend(["", *group_lines])
    overview_lines.extend(["", ctx.t("help.page", current=current_page, total=total_pages), "", ctx.t("help.footer")])

    modules: list[dict[str, object]] = [
        {
            "type": "header",
            "text": {
                "type": "plain-text",
                "content": ctx.t("help.title"),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "kmarkdown",
                "content": "\n".join(overview_lines),
            },
        },
        {"type": "divider"},
    ]
    modules.extend(build_action_groups(_build_overview_buttons(ctx, current_page=current_page, total_pages=total_pages)))

    return {
        "type": "card",
        "theme": "primary",
        "size": "lg",
        "modules": modules,
    }


def _build_empty_help_card(ctx: CommandContext) -> dict[str, object]:
    return {
        "type": "card",
        "theme": "secondary",
        "size": "lg",
        "modules": [
            {
                "type": "header",
                "text": {
                    "type": "plain-text",
                    "content": ctx.t("help.title"),
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "kmarkdown",
                    "content": ctx.t("help.empty_description"),
                },
            },
        ],
    }


def _group_commands(commands: tuple[CommandSpec, ...]) -> dict[str, tuple[CommandSpec, ...]]:
    grouped: dict[str, list[CommandSpec]] = {role: [] for role in ROLE_ORDER}
    for spec in commands:
        grouped.setdefault(spec.required_role, []).append(spec)
    return {role: tuple(grouped.get(role, [])) for role in ROLE_ORDER}


def _build_overview_buttons(ctx: CommandContext, *, current_page: int, total_pages: int) -> list[dict[str, object]]:
    prefix = ctx.bot.settings.command_prefix
    buttons: list[dict[str, object]] = [
        build_command_button(ctx.t("button.products"), f"{prefix}products", theme="primary"),
        build_command_button(ctx.t("button.balance"), f"{prefix}balance", theme="success"),
        build_command_button(ctx.t("button.pay_amounts"), f"{prefix}pay_amounts", theme="warning"),
        build_command_button(ctx.t("button.myrole"), f"{prefix}myrole", theme="secondary"),
    ]
    if current_page > 1:
        buttons.append(
            build_command_button(ctx.t("help.prev_page"), f"{prefix}help {current_page - 1}", theme="secondary")
        )
    if current_page < total_pages:
        buttons.append(
            build_command_button(ctx.t("help.next_page"), f"{prefix}help {current_page + 1}", theme="primary")
        )
    return buttons


def _build_command_text(ctx: CommandContext, spec: CommandSpec) -> str:
    description_key = f"command.{spec.name}.description"
    translated_description = ctx.t(description_key)
    description_text = translated_description if translated_description != description_key else spec.description
    if not description_text:
        description_text = ctx.t("help.empty_description")

    usage_text = spec.usage
    prefix = ctx.bot.settings.command_prefix
    if usage_text.startswith("/"):
        usage_text = f"{prefix}{usage_text[1:]}"

    lines = [
        f"**{prefix}{spec.name}**",
        description_text,
        f"**{ctx.t('help.usage_label')}** `{usage_text}`",
    ]
    if spec.aliases:
        alias_text = ", ".join(f"{prefix}{alias}" for alias in spec.aliases)
        lines.append(f"**{ctx.t('help.aliases_label')}** {alias_text}")
    return "\n".join(lines)
