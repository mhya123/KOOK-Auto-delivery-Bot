from __future__ import annotations

import asyncio
import json
import shlex
from pathlib import Path
from typing import Any

from aiohttp import ClientSession

from .cards import build_command_log_cards as make_command_log_cards
from .cards import build_text_cards as make_text_cards
from .command_loader import CommandLoader
from .commands import CommandRegistry
from .config import Settings
from .context import CommandContext, MessageEvent
from .database import Database
from .gateway import KookGateway
from .http import KookHttpClient
from .i18n import Translator
from .logging_utils import get_logger
from .permissions import PermissionService, Role, role_allows
from .store_service import StoreService

logger = get_logger("kook_bot.bot")


class KookBot:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        project_root = Path(__file__).resolve().parents[2]
        self.commands = CommandRegistry()
        self.database = Database(settings)
        self.permissions = PermissionService(self.database, settings.super_admin_ids)
        self.store = StoreService(self.database, self.permissions)
        self.command_loader = CommandLoader(self)
        self.translator = Translator(settings.locale, project_root / settings.locale_dir)
        self._http: KookHttpClient | None = None
        self._session: ClientSession | None = None

    def command(self, name: str, **kwargs):
        return self.commands.command(name, **kwargs)

    def _log_command_activity(self, message: str, *args: object) -> None:
        if self.settings.log_commands:
            logger.info(message, *args)

    def _log_command_status(self, message: str, *args: object) -> None:
        if self.settings.log_command_status:
            logger.info(message, *args)

    def build_text_cards(
        self,
        content: str,
        *,
        theme: str = "primary",
        title: str | None = None,
    ) -> list[dict[str, Any]]:
        # 普通文本回复统一包装成卡片，避免命令层重复拼装。
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
            cards.append(
                {
                    "type": "card",
                    "theme": theme if index == 0 else "secondary",
                    "size": "lg",
                    "modules": modules,
                }
            )
        return cards

    async def start(self) -> None:
        async with ClientSession() as session:
            self._session = session
            self._http = KookHttpClient(
                session,
                self.settings.token,
                self.settings.api_base_url,
                log_http=self.settings.log_http,
            )
            gateway = KookGateway(
                session=session,
                http=self._http,
                event_callback=self._dispatch_message,
                compress=self.settings.gateway_compress,
                log_events=self.settings.log_events,
            )
            logger.info(
                (
                    "starting prefix=%r api_base_url=%s db_backend=%s super_admin_ids=%s log_level=%s "
                    "log_http=%s log_events=%s log_commands=%s log_command_status=%s locale=%s locale_dir=%s "
                    "admin_command_channel_id=%s log_channel_id=%s "
                    "log_to_file=%s log_dir=%s log_file=%s log_max_bytes=%s log_backup_count=%s"
                ),
                self.settings.command_prefix,
                self.settings.api_base_url,
                self.settings.db_backend,
                self.settings.super_admin_ids,
                self.settings.log_level.upper(),
                self.settings.log_http,
                self.settings.log_events,
                self.settings.log_commands,
                self.settings.log_command_status,
                self.settings.locale,
                self.settings.locale_dir,
                self.settings.admin_command_channel_id,
                self.settings.log_channel_id,
                self.settings.log_to_file,
                self.settings.log_dir,
                self.settings.log_file,
                self.settings.log_max_bytes,
                self.settings.log_backup_count,
            )
            self.store.ensure_initialized()
            self.command_loader.load(force=True)
            try:
                await gateway.run_forever()
            except asyncio.CancelledError:
                logger.info("shutdown requested")
                raise
            finally:
                self._session = None

    def run(self) -> None:
        try:
            asyncio.run(self.start())
        except KeyboardInterrupt:
            logger.info("stopped by user")

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

    async def reply_to_event(self, event: MessageEvent, content: str) -> dict[str, Any]:
        return await self.reply_card_to_event(
            event,
            make_text_cards(content),
        )

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

    async def reply_card_to_event(self, event: MessageEvent, cards: list[dict[str, Any]]) -> dict[str, Any]:
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
        """导出卡密和购买发货都可能很长，这里自动按长度切分私信。"""
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

    def get_role(self, user_id: str) -> str:
        return self.permissions.get_role(user_id)

    def t(self, key: str, **params: object) -> str:
        params.setdefault("prefix", self.settings.command_prefix)
        return self.translator.translate(key, **params)

    def _requires_admin_channel(self, spec) -> bool:
        return spec.required_role in {Role.ADMIN, Role.SUPER_ADMIN}

    def _is_admin_channel(self, event: MessageEvent) -> bool:
        channel_id = self.settings.admin_command_channel_id.strip()
        if not channel_id:
            return True
        return not event.is_direct and event.target_id == channel_id

    async def _send_command_log(
        self,
        event: MessageEvent,
        command_name: str,
        args: list[str],
        *,
        status: str,
        detail: str = "",
    ) -> None:
        await self.send_log_card(
            make_command_log_cards(
                prefix=self.settings.command_prefix,
                event=event,
                author_role=self.get_role(event.author_id),
                command_name=command_name,
                args=args,
                status=status,
                detail=detail,
            )
        )

    def _build_command_log_cards(
        self,
        event: MessageEvent,
        command_name: str,
        args: list[str],
        *,
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
        command_text = sanitize(f"{self.settings.command_prefix}{command_name}", limit=80)
        source_channel = event.target_id if not event.is_direct else f"DM:{event.author_id}"
        role_name = self.get_role(event.author_id)
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
                        f"**role**: `{role_name}`\n"
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

    async def _dispatch_message(self, event: MessageEvent) -> None:
        self.command_loader.load()
        if self.settings.log_events:
            logger.debug("event received %s", event.log_summary)

        if not event.is_text or event.is_bot:
            if self.settings.log_events:
                logger.debug(
                    "event ignored is_text=%s is_bot=%s msg_id=%s",
                    event.is_text,
                    event.is_bot,
                    event.msg_id,
                )
            return

        prefix = self.settings.command_prefix
        if not event.content.startswith(prefix):
            if self.settings.log_events:
                logger.debug("command ignored missing prefix prefix=%r msg_id=%s", prefix, event.msg_id)
            return

        command_line = event.content[len(prefix) :].strip()
        if not command_line:
            logger.debug("command ignored empty command msg_id=%s", event.msg_id)
            return

        try:
            parts = shlex.split(command_line)
        except ValueError:
            await self._send_command_log(
                event,
                command_name="invalid",
                args=[],
                status="rejected",
                detail="invalid_syntax",
            )
            await self.reply_to_event(event, self.t("common.invalid_syntax"))
            return

        if not parts:
            await self._send_command_log(
                event,
                command_name="invalid",
                args=[],
                status="rejected",
                detail="empty_command",
            )
            await self.reply_to_event(event, self.t("common.invalid_syntax"))
            return

        command_name = parts[0].lower()
        args = parts[1:]
        self._log_command_activity(
            "command received name=%r args=%s author_id=%s channel_type=%s target_id=%s msg_id=%s",
            command_name,
            args,
            event.author_id,
            event.channel_type,
            event.target_id,
            event.msg_id,
        )
        spec = self.commands.get(command_name)
        if spec is None:
            self._log_command_activity(
                "command unknown name=%r available=%s msg_id=%s",
                command_name,
                self.commands.names(),
                event.msg_id,
            )
            await self._send_command_log(
                event,
                command_name,
                args,
                status="rejected",
                detail="unknown_command",
            )
            await self.reply_to_event(event, self.t("common.unknown_command"))
            return

        author_role = self.get_role(event.author_id)
        if not role_allows(author_role, spec.required_role):
            await self._send_command_log(
                event,
                command_name,
                args,
                status="rejected",
                detail="permission_denied",
            )
            await self.reply_to_event(event, self.t("common.permission_denied"))
            return

        if self._requires_admin_channel(spec) and not self._is_admin_channel(event):
            await self.reply_to_event(
                event,
                self.t("common.admin_channel_only", channel_id=self.settings.admin_command_channel_id),
            )
            await self._send_command_log(
                event,
                command_name,
                args,
                status="rejected",
                detail="invalid_channel",
            )
            return

        context = CommandContext(
            bot=self,
            event=event,
            command_name=command_name,
            args=args,
        )
        try:
            await spec.handler(context)
            self._log_command_status("command finished name=%r msg_id=%s", command_name, event.msg_id)
            await self._send_command_log(event, command_name, args, status="success")
        except Exception:
            logger.exception("command failed name=%r msg_id=%s", command_name, event.msg_id)
            await self._send_command_log(
                event,
                command_name,
                args,
                status="failed",
                detail="handler_exception",
            )
            await self.reply_to_event(event, self.t("common.command_failed"))
            return
