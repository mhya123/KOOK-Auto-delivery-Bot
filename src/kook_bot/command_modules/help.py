from __future__ import annotations

from math import ceil

from ..bot import KookBot
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
MIN_COMMANDS_PER_CARD = 3
MAX_COMMANDS_PER_CARD = 8


def register(bot: KookBot) -> None:
    @bot.command(
        "help",
        description="Show all available commands.",
        usage="/help",
        aliases=("commands",),
    )
    async def help_command(ctx: CommandContext) -> None:
        visible_commands = ctx.bot.commands.visible_commands(ctx.author_role)
        await ctx.reply_card(_build_help_cards(ctx, visible_commands))


def _build_help_cards(ctx: CommandContext, commands: tuple[CommandSpec, ...]) -> list[dict[str, object]]:
    grouped = _group_commands(commands)
    cards: list[dict[str, object]] = []
    commands_per_card = _pick_commands_per_card(grouped)
    first_card = True

    for role in ROLE_ORDER:
        role_commands = grouped.get(role, ())
        if not role_commands:
            continue
        cards.extend(
            _build_role_cards(
                ctx,
                role,
                role_commands,
                commands_per_card=commands_per_card,
                include_overview=first_card,
                total_commands=len(commands),
                grouped=grouped,
            )
        )
        first_card = False

    return cards[:MAX_HELP_CARDS] or [_build_empty_help_card(ctx)]


def _pick_commands_per_card(grouped: dict[str, tuple[CommandSpec, ...]]) -> int:
    total_commands = sum(len(items) for items in grouped.values())
    if total_commands <= 0:
        return MIN_COMMANDS_PER_CARD

    for size in range(MIN_COMMANDS_PER_CARD, MAX_COMMANDS_PER_CARD + 1):
        card_count = sum(ceil(len(items) / size) for items in grouped.values() if items)
        if card_count <= MAX_HELP_CARDS:
            return size
    return MAX_COMMANDS_PER_CARD


def _build_role_cards(
    ctx: CommandContext,
    role: str,
    commands: tuple[CommandSpec, ...],
    *,
    commands_per_card: int,
    include_overview: bool,
    total_commands: int,
    grouped: dict[str, tuple[CommandSpec, ...]],
) -> list[dict[str, object]]:
    cards: list[dict[str, object]] = []
    title = ctx.t("help.section_title", role=ctx.t(f"role.{role}"), count=len(commands))
    theme = ROLE_THEMES.get(role, "secondary")

    for start in range(0, len(commands), commands_per_card):
        page = commands[start : start + commands_per_card]
        modules: list[dict[str, object]] = []

        if include_overview and start == 0:
            modules.extend(_build_overview_modules(ctx, total_commands, grouped))
            modules.append({"type": "divider"})

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

        include_overview = False

    return cards


def _build_overview_modules(
    ctx: CommandContext,
    total_commands: int,
    grouped: dict[str, tuple[CommandSpec, ...]],
) -> list[dict[str, object]]:
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
    overview_lines.extend(["", ctx.t("help.footer")])

    return [
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
    ]


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
