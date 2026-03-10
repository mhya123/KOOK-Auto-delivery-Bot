from __future__ import annotations

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
        return tuple(items)


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
