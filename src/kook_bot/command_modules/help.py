from __future__ import annotations

from ..bot import KookBot
from ..commands import CommandSpec
from ..context import CommandContext

CARD_COMMANDS_PER_PAGE = 6
MAX_HELP_CARDS = 5


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
    role_name = ctx.t(f"role.{ctx.author_role}")
    meta_text = ctx.t(
        "help.meta",
        role=role_name,
        prefix=ctx.bot.settings.command_prefix,
        count=len(commands),
    )
    cards: list[dict[str, object]] = []
    page_size = CARD_COMMANDS_PER_PAGE
    if commands:
        minimum_page_size = (len(commands) + MAX_HELP_CARDS - 1) // MAX_HELP_CARDS
        page_size = max(CARD_COMMANDS_PER_PAGE, minimum_page_size)

    for index in range(0, len(commands), page_size):
        page_commands = commands[index : index + page_size]
        modules: list[dict[str, object]] = []

        if index == 0:
            modules.append(
                {
                    "type": "header",
                    "text": {
                        "type": "plain-text",
                        "content": ctx.t("help.title"),
                    },
                }
            )
            modules.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "plain-text",
                            "content": meta_text,
                        }
                    ],
                }
            )
            modules.append({"type": "divider"})

        for position, spec in enumerate(page_commands):
            modules.append(
                {
                    "type": "section",
                    "text": {
                        "type": "kmarkdown",
                        "content": _build_command_text(ctx, spec),
                    },
                }
            )
            if position != len(page_commands) - 1:
                modules.append({"type": "divider"})

        cards.append(
            {
                "type": "card",
                "theme": "primary" if index == 0 else "secondary",
                "size": "lg",
                "modules": modules,
            }
        )

    if not cards:
        cards.append(
            {
                "type": "card",
                "theme": "warning",
                "size": "lg",
                "modules": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain-text",
                            "content": ctx.t("help.title"),
                        },
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "plain-text",
                                "content": meta_text,
                            }
                        ],
                    },
                ],
            }
        )
    return cards


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

    return f"**{prefix}{spec.name}**\n`{usage_text}`\n{description_text}"
