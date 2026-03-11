from __future__ import annotations

from typing import Any, Iterable


def build_command_button(text: str, command: str, *, theme: str = "primary") -> dict[str, Any]:
    return {
        "type": "button",
        "theme": theme,
        "click": "return-val",
        "value": command,
        "text": {
            "type": "plain-text",
            "content": text,
        },
    }


def build_link_button(text: str, url: str, *, theme: str = "primary") -> dict[str, Any]:
    return {
        "type": "button",
        "theme": theme,
        "click": "link",
        "value": url,
        "text": {
            "type": "plain-text",
            "content": text,
        },
    }


def build_action_group(buttons: Iterable[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "action-group",
        "elements": [button for button in buttons],
    }


def build_action_groups(buttons: Iterable[dict[str, Any]], *, chunk_size: int = 4) -> list[dict[str, Any]]:
    items = [button for button in buttons]
    if not items:
        return []

    groups: list[dict[str, Any]] = []
    for start in range(0, len(items), max(1, chunk_size)):
        groups.append(build_action_group(items[start : start + max(1, chunk_size)]))
    return groups


def build_text_cards(
    content: str,
    *,
    theme: str = "primary",
    title: str | None = None,
    actions: Iterable[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    # 统一处理文本分片，避免回复过长导致卡片发送失败。
    lines = content.splitlines() or [content]
    chunks: list[str] = []
    current_lines: list[str] = []
    current_length = 0

    for line in lines:
        normalized_line = line or " "
        line_length = len(normalized_line) + 1
        if current_lines and current_length + line_length > 1500:
            chunks.append("\n".join(current_lines))
            current_lines = []
            current_length = 0
        current_lines.append(normalized_line)
        current_length += line_length

    if current_lines:
        chunks.append("\n".join(current_lines))
    if not chunks:
        chunks.append(" ")

    cards: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        modules: list[dict[str, Any]] = []
        if title and index == 0:
            modules.append(
                {
                    "type": "header",
                    "text": {
                        "type": "plain-text",
                        "content": title,
                    },
                }
            )
            modules.append({"type": "divider"})
        modules.append(
            {
                "type": "section",
                "text": {
                    "type": "kmarkdown",
                    "content": chunk,
                },
            }
        )
        action_items = list(actions or [])
        if action_items and index == 0:
            modules.append({"type": "divider"})
            modules.extend(build_action_groups(action_items))
        cards.append(
            {
                "type": "card",
                "theme": theme if index == 0 else "secondary",
                "size": "lg",
                "modules": modules,
            }
        )
    return cards


def build_fact_cards(
    title: str,
    facts: Iterable[tuple[str, str]],
    *,
    theme: str = "primary",
    footer: str | None = None,
    facts_per_card: int = 6,
    actions: Iterable[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    fact_items = list(facts)
    if not fact_items:
        return build_text_cards(" ", theme=theme, title=title)

    cards: list[dict[str, Any]] = []
    action_items = list(actions or [])
    for start in range(0, len(fact_items), facts_per_card):
        page = fact_items[start : start + facts_per_card]
        modules: list[dict[str, Any]] = []
        if start == 0:
            modules.append(
                {
                    "type": "header",
                    "text": {
                        "type": "plain-text",
                        "content": title,
                    },
                }
            )
            modules.append({"type": "divider"})

        for index, (label, value) in enumerate(page):
            safe_value = value or "-"
            modules.append(
                {
                    "type": "section",
                    "text": {
                        "type": "kmarkdown",
                        "content": f"**{label}**\n{safe_value}",
                    },
                }
            )
            if index != len(page) - 1:
                modules.append({"type": "divider"})

        if footer and start + facts_per_card >= len(fact_items):
            modules.append({"type": "divider"})
            modules.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "plain-text",
                            "content": footer,
                        }
                    ],
                }
            )

        if action_items and start == 0:
            modules.append({"type": "divider"})
            modules.extend(build_action_groups(action_items))

        cards.append(
            {
                "type": "card",
                "theme": theme if start == 0 else "secondary",
                "size": "lg",
                "modules": modules,
            }
        )
    return cards


def build_status_cards(
    title: str,
    *,
    body: str = "",
    facts: Iterable[tuple[str, str]] | None = None,
    theme: str = "primary",
    footer: str | None = None,
    actions: Iterable[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    fact_items = list(facts or [])
    modules: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain-text",
                "content": title,
            },
        }
    ]

    if body:
        modules.append({"type": "divider"})
        modules.append(
            {
                "type": "section",
                "text": {
                    "type": "kmarkdown",
                    "content": body,
                },
            }
        )

    if fact_items:
        modules.append({"type": "divider"})
        for index, (label, value) in enumerate(fact_items):
            modules.append(
                {
                    "type": "section",
                    "text": {
                        "type": "kmarkdown",
                        "content": f"**{label}**\n{value or '-'}",
                    },
                }
            )
            if index != len(fact_items) - 1:
                modules.append({"type": "divider"})

    if footer:
        modules.append({"type": "divider"})
        modules.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "plain-text",
                        "content": footer,
                    }
                ],
            }
        )

    action_items = list(actions or [])
    if action_items:
        modules.append({"type": "divider"})
        modules.extend(build_action_groups(action_items))

    return [
        {
            "type": "card",
            "theme": theme,
            "size": "lg",
            "modules": modules,
        }
    ]


def build_command_log_cards(
    *,
    prefix: str,
    event,
    author_role: str,
    command_name: str,
    args: list[str],
    status: str,
    detail: str = "",
) -> list[dict[str, Any]]:
    def sanitize(value: str, *, limit: int = 160) -> str:
        safe = value.replace("`", "'").replace("\n", "\\n")
        if len(safe) > limit:
            return f"{safe[: limit - 3]}..."
        return safe

    status_theme = {
        "success": "success",
        "failed": "danger",
        "rejected": "warning",
    }.get(status, "secondary")
    status_label = status.upper()
    args_text = sanitize(" ".join(args).strip() or "-")
    command_text = sanitize(f"{prefix}{command_name}", limit=80)
    source_channel = event.target_id if not event.is_direct else f"DM:{event.author_id}"
    raw_content = sanitize(event.content)
    nickname = sanitize(str(event.author.get("nickname") or ""), limit=80)
    username = sanitize(str(event.author.get("username") or ""), limit=80)
    identify_num = sanitize(str(event.author.get("identify_num") or ""), limit=16)
    display_name = nickname or "-"
    account_name = username or "-"
    if username and identify_num:
        account_name = f"{username}#{identify_num}"

    modules: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain-text",
                "content": f"[COMMAND LOG] {status_label} {command_text}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "kmarkdown",
                "content": (
                    f"**author_id**: `{event.author_id}`\n"
                    f"**nickname**: `{display_name}`\n"
                    f"**username**: `{account_name}`\n"
                    f"**role**: `{author_role}`\n"
                    f"**source**: `{source_channel}`\n"
                    f"**msg_id**: `{event.msg_id}`"
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "kmarkdown",
                "content": (
                    f"**command**: `{command_text}`\n"
                    f"**args**: `{args_text}`\n"
                    f"**content**: `{raw_content}`"
                ),
            },
        },
    ]
    if detail:
        modules.extend(
            [
                {"type": "divider"},
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "plain-text",
                            "content": f"detail: {detail}",
                        }
                    ],
                },
            ]
        )

    return [
        {
            "type": "card",
            "theme": status_theme,
            "size": "lg",
            "modules": modules,
        }
    ]
