from __future__ import annotations

import json
from typing import Any

from .cards import build_text_cards as make_text_cards
from .logging_utils import get_logger

logger = get_logger("kook_bot.bot")


class BotTransportMixin:
    # 所有对 KOOK 的发送能力都集中在这里，避免 bot.py 混入大量传输细节。
    async def send_channel_message(
        self,
        channel_id: str,
        content: str,
        *,
        message_type: int = 9,
        reply_msg_id: str | None = None,
    ) -> dict[str, Any]:
        if self._http is None:
            raise RuntimeError("Bot HTTP client has not been initialized.")
        self._log_command_status(
            "sending channel message channel_id=%s reply_msg_id=%s content=%r",
            channel_id,
            reply_msg_id,
            content,
        )
        result = await self._http.create_channel_message(
            channel_id,
            content,
            message_type=message_type,
            reply_msg_id=reply_msg_id,
        )
        self._log_command_status("channel message sent result=%s", result)
        return result

    async def send_direct_message(
        self,
        content: str,
        *,
        target_id: str | None = None,
        chat_code: str | None = None,
        message_type: int = 9,
        reply_msg_id: str | None = None,
    ) -> dict[str, Any]:
        if self._http is None:
            raise RuntimeError("Bot HTTP client has not been initialized.")
        self._log_command_status(
            "sending direct message target_id=%s chat_code=%s reply_msg_id=%s content=%r",
            target_id,
            chat_code,
            reply_msg_id,
            content,
        )
        result = await self._http.create_direct_message(
            content,
            target_id=target_id,
            chat_code=chat_code,
            message_type=message_type,
            reply_msg_id=reply_msg_id,
        )
        self._log_command_status("direct message sent result=%s", result)
        return result

    async def reply_to_event(self, event, content: str) -> dict[str, Any]:
        return await self.reply_card_to_event(event, make_text_cards(content))

    async def send_private_message(self, user_id: str, content: str) -> dict[str, Any]:
        return await self.send_direct_card(make_text_cards(content), target_id=user_id)

    async def send_dm_message(self, user_id: str, content: str) -> dict[str, Any]:
        return await self.send_private_message(user_id, content)

    async def send_group_message(self, channel_id: str, content: str) -> dict[str, Any]:
        return await self.send_channel_card(channel_id, make_text_cards(content))

    async def send_channel_card(
        self,
        channel_id: str,
        cards: list[dict[str, Any]],
        *,
        reply_msg_id: str | None = None,
    ) -> dict[str, Any]:
        return await self.send_channel_message(
            channel_id,
            json.dumps(cards, ensure_ascii=False),
            message_type=10,
            reply_msg_id=reply_msg_id,
        )

    async def send_direct_card(
        self,
        cards: list[dict[str, Any]],
        *,
        target_id: str | None = None,
        chat_code: str | None = None,
        reply_msg_id: str | None = None,
    ) -> dict[str, Any]:
        return await self.send_direct_message(
            json.dumps(cards, ensure_ascii=False),
            target_id=target_id,
            chat_code=chat_code,
            message_type=10,
            reply_msg_id=reply_msg_id,
        )

    async def reply_card_to_event(self, event, cards: list[dict[str, Any]]) -> dict[str, Any]:
        if event.is_direct:
            return await self.send_direct_card(
                cards,
                target_id=event.author_id,
                chat_code=event.chat_code or None,
                reply_msg_id=event.msg_id,
            )
        return await self.send_channel_card(
            event.target_id,
            cards,
            reply_msg_id=event.msg_id,
        )

    async def send_log_message(self, content: str) -> None:
        channel_id = self.settings.log_channel_id.strip()
        if not channel_id:
            return
        try:
            await self.send_channel_card(channel_id, make_text_cards(content, theme="secondary"))
        except Exception:
            logger.exception("failed to send log message channel_id=%s", channel_id)

    async def send_log_card(self, cards: list[dict[str, Any]]) -> None:
        channel_id = self.settings.log_channel_id.strip()
        if not channel_id:
            return
        try:
            await self.send_channel_card(channel_id, cards)
        except Exception:
            logger.exception("failed to send log card channel_id=%s", channel_id)

    async def upload_file(
        self,
        filename: str,
        content_bytes: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> str:
        if self._http is None:
            raise RuntimeError("Bot HTTP client has not been initialized.")
        return await self._http.upload_asset(filename, content_bytes, content_type=content_type)

    async def send_private_file(
        self,
        user_id: str,
        filename: str,
        content_bytes: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> dict[str, Any]:
        asset_url = await self.upload_file(filename, content_bytes, content_type=content_type)
        return await self.send_direct_message(asset_url, target_id=user_id, message_type=4)

    async def download_attachment_bytes(self, url: str) -> bytes:
        if self._session is None:
            raise RuntimeError("Bot session has not been initialized.")
        async with self._session.get(url) as response:
            response.raise_for_status()
            return await response.read()

    async def send_private_text_chunks(self, user_id: str, text: str, *, max_length: int = 1800) -> None:
        remaining_lines = text.splitlines() or [text]
        current_chunk: list[str] = []
        current_length = 0

        for line in remaining_lines:
            line_length = len(line) + 1
            if current_chunk and current_length + line_length > max_length:
                await self.send_private_message(user_id, "\n".join(current_chunk))
                current_chunk = []
                current_length = 0
            current_chunk.append(line)
            current_length += line_length

        if current_chunk:
            await self.send_private_message(user_id, "\n".join(current_chunk))
