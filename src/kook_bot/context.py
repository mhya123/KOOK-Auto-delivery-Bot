from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .cards import build_status_cards
from .logging_utils import get_logger
from .permissions import Role

logger = get_logger("kook_bot.command")


@dataclass(slots=True)
class MessageEvent:
    channel_type: str
    message_type: int
    target_id: str
    author_id: str
    chat_code: str
    guild_id: str
    content: str
    msg_id: str
    raw_event: dict
    author: dict

    @classmethod
    def from_payload(cls, payload: dict) -> "MessageEvent":
        extra = payload.get("extra") or {}
        author = extra.get("author") or {}
        kmarkdown = extra.get("kmarkdown") or {}
        content = str(payload.get("content", ""))
        if int(payload.get("type", 0)) == 9:
            content = str(kmarkdown.get("raw_content", content))
        return cls(
            channel_type=str(payload.get("channel_type", "")),
            message_type=int(payload.get("type", 0)),
            target_id=str(payload.get("target_id", "")),
            author_id=str(payload.get("author_id", "")),
            chat_code=str(payload.get("chat_code") or extra.get("chat_code") or ""),
            guild_id=str(extra.get("guild_id") or ""),
            content=content,
            msg_id=str(payload.get("msg_id", "")),
            raw_event=payload,
            author=author,
        )

    @property
    def is_text(self) -> bool:
        return self.message_type in {1, 9}

    @property
    def is_bot(self) -> bool:
        return bool(self.author.get("bot"))

    @property
    def is_direct(self) -> bool:
        return self.channel_type.upper() == "PERSON"

    @property
    def log_summary(self) -> str:
        safe_content = self.content.replace("\n", "\\n")
        if len(safe_content) > 120:
            safe_content = f"{safe_content[:117]}..."
        return (
            f"type={self.message_type} channel_type={self.channel_type} "
            f"target_id={self.target_id} author_id={self.author_id} "
            f"chat_code={self.chat_code} guild_id={self.guild_id} "
            f"msg_id={self.msg_id} content={safe_content!r}"
        )

    @property
    def attachments(self) -> tuple[dict[str, str], ...]:
        extra = self.raw_event.get("extra") or {}
        raw_attachments = extra.get("attachments")
        items: list[dict[str, str]] = []

        if isinstance(raw_attachments, dict):
            raw_items = [raw_attachments]
        elif isinstance(raw_attachments, list):
            raw_items = [item for item in raw_attachments if isinstance(item, dict)]
        else:
            raw_items = []

        for item in raw_items:
            items.append(
                {
                    "type": str(item.get("type", "")),
                    "name": str(item.get("name", "")),
                    "url": str(item.get("url", "")),
                    "file_type": str(item.get("file_type", "")),
                }
            )

        # KOOK 的文件类消息不一定把附件放在 extra.attachments 里，
        # 有些事件本身就是一个文件消息，这里补一个兜底提取。
        if not items and self.message_type in {2, 3, 4, 8}:
            content_url = str(self.raw_event.get("content", "")).strip()
            attachment_name = str(extra.get("name") or extra.get("file_name") or payload_name_from_url(content_url))
            attachment_type = str(extra.get("type", ""))
            attachment_file_type = str(extra.get("file_type") or suffix_from_name(attachment_name))
            if content_url:
                items.append(
                    {
                        "type": attachment_type,
                        "name": attachment_name,
                        "url": content_url,
                        "file_type": attachment_file_type,
                    }
                )

        # 某些 KOOK 客户端会把上传文件包装成卡片消息，文件链接藏在 content JSON 里。
        if not items and self.message_type == 10:
            items.extend(extract_card_attachments(self.raw_event.get("content", "")))
        return tuple(items)


def payload_name_from_url(url: str) -> str:
    if not url:
        return ""
    normalized = url.split("?", 1)[0].rstrip("/")
    if "/" not in normalized:
        return normalized
    return normalized.rsplit("/", 1)[-1]


def suffix_from_name(name: str) -> str:
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].lower()


def extract_card_attachments(content: object) -> list[dict[str, str]]:
    if not isinstance(content, str) or not content.strip():
        return []

    try:
        payload = json.loads(content)
    except ValueError:
        return []

    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    stack: list[object] = [payload]

    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            url_candidates = [
                current.get("url"),
                current.get("src"),
                current.get("value"),
            ]
            attachment_name = str(
                current.get("name")
                or current.get("title")
                or current.get("file_name")
                or current.get("text")
                or ""
            ).strip()
            attachment_type = str(current.get("type", "")).strip()
            for candidate in url_candidates:
                if not isinstance(candidate, str):
                    continue
                url = candidate.strip()
                if not url or url in seen_urls or not is_supported_file_url(url):
                    continue
                seen_urls.add(url)
                inferred_name = attachment_name or payload_name_from_url(url)
                results.append(
                    {
                        "type": attachment_type,
                        "name": inferred_name,
                        "url": url,
                        "file_type": suffix_from_name(inferred_name) or suffix_from_name(payload_name_from_url(url)),
                    }
                )
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return results


def is_supported_file_url(url: str) -> bool:
    lower_url = url.lower()
    return lower_url.endswith(".txt") or lower_url.endswith(".csv") or ".txt?" in lower_url or ".csv?" in lower_url


@dataclass(slots=True)
class CommandContext:
    bot: "KookBot"
    event: MessageEvent
    command_name: str
    args: list[str]

    async def reply(self, content: str) -> None:
        if self.bot.settings.log_command_status:
            logger.info(
                "reply command=%s channel_type=%s target_id=%s content=%r",
                self.command_name,
                self.event.channel_type,
                self.event.target_id,
                content,
            )
        await self.bot.reply_to_event(self.event, content)

    async def reply_t(self, key: str, **params: object) -> None:
        await self.reply(self.t(key, **params))

    async def reply_success_t(self, key: str, **params: object) -> None:
        await self.reply_card(
            build_status_cards(
                self.t("common.status.success_title"),
                body=self.t(key, **params),
                theme="success",
            )
        )

    async def reply_warning_t(self, key: str, **params: object) -> None:
        await self.reply_card(
            build_status_cards(
                self.t("common.status.warning_title"),
                body=self.t(key, **params),
                theme="warning",
            )
        )

    async def reply_card(self, cards: list[dict[str, object]]) -> None:
        if self.bot.settings.log_command_status:
            logger.info(
                "reply card command=%s channel_type=%s target_id=%s card_count=%s",
                self.command_name,
                self.event.channel_type,
                self.event.target_id,
                len(cards),
            )
        await self.bot.reply_card_to_event(self.event, cards)

    async def reply_error(self, error: Exception) -> None:
        message_key = getattr(error, "message_key", None)
        message_params = getattr(error, "message_params", {})
        if message_key:
            await self.reply_card(
                build_status_cards(
                    self.t("common.status.error_title"),
                    body=self.t(str(message_key), **dict(message_params)),
                    theme="danger",
                )
            )
            return
        await self.reply_card(
            build_status_cards(
                self.t("common.status.error_title"),
                body=str(error),
                theme="danger",
            )
        )

    def t(self, key: str, **params: object) -> str:
        return self.bot.t(key, **params)

    @property
    def author_id(self) -> str:
        return self.event.author_id

    @property
    def author_role(self) -> str:
        return self.bot.get_role(self.event.author_id)

    def is_super_admin(self) -> bool:
        return self.author_role == Role.SUPER_ADMIN

    def is_admin(self) -> bool:
        return self.author_role in {Role.SUPER_ADMIN, Role.ADMIN}

    @property
    def attachments(self) -> tuple[dict[str, str], ...]:
        return self.event.attachments


if TYPE_CHECKING:
    from .bot import KookBot
