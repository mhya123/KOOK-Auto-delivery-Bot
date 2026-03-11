from __future__ import annotations

import asyncio
import secrets
import shlex
import time
from json import dumps as json_dumps
from pathlib import Path
from typing import Any

from aiohttp import ClientSession

from .bot_imports import BotImportMixin, PendingImportUpload
from .bot_transport import BotTransportMixin
from .cards import build_command_log_cards as make_command_log_cards
from .command_loader import CommandLoader
from .commands import CommandRegistry
from .config import Settings
from .context import CommandContext, MessageEvent
from .database import Database
from .gateway import KookGateway
from .i18n import Translator
from .kook_http import KookHttpClient
from .logging_utils import get_logger
from .payment_gateway import MxlgPaymentGateway
from .permissions import PermissionService, Role, role_allows
from .store_service import StoreService

logger = get_logger("kook_bot.bot")


class KookBot(BotTransportMixin, BotImportMixin):
    # 核心协调器：这里只保留启动、依赖装配、权限判断和命令分发。
    # 发送消息能力拆到 BotTransportMixin，导入流程拆到 BotImportMixin。
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        project_root = Path(__file__).resolve().parents[2]
        self.commands = CommandRegistry()
        self.database = Database(settings)
        self.permissions = PermissionService(self.database, settings.super_admin_ids)
        self.store = StoreService(self.database, self.permissions, settings)
        self.payment_gateway = MxlgPaymentGateway(settings)
        self.command_loader = CommandLoader(self)
        self.translator = Translator(settings.locale, project_root / settings.locale_dir)
        self._http: KookHttpClient | None = None
        self._session: ClientSession | None = None
        self._import_web_runner: Any | None = None
        self._pending_import_uploads: dict[str, PendingImportUpload] = {}

    def command(self, name: str, **kwargs):
        return self.commands.command(name, **kwargs)

    def _log_command_activity(self, message: str, *args: object) -> None:
        if self.settings.log_commands:
            logger.info(message, *args)

    def _log_command_status(self, message: str, *args: object) -> None:
        if self.settings.log_command_status:
            logger.info(message, *args)

    def _log_import(self, message: str, *args: object) -> None:
        if self.settings.log_imports:
            logger.info(message, *args)

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
                    "recharge_card_format=%r recharge_card_random_length=%s "
                    "payment_enabled=%s payment_api_base_url=%s payment_base_url=%s "
                    "log_http=%s log_events=%s log_commands=%s log_command_status=%s log_imports=%s locale=%s locale_dir=%s "
                    "admin_command_channel_id=%s log_channel_id=%s import_web_enabled=%s import_web_host=%s "
                    "import_web_port=%s import_web_base_url=%s import_web_ttl_seconds=%s "
                    "log_to_file=%s log_dir=%s log_file=%s log_max_bytes=%s log_backup_count=%s"
                ),
                self.settings.command_prefix,
                self.settings.api_base_url,
                self.settings.db_backend,
                self.settings.super_admin_ids,
                self.settings.log_level.upper(),
                self.settings.recharge_card_format,
                self.settings.recharge_card_random_length,
                self.settings.payment_enabled,
                self.settings.payment_api_base_url,
                self.payment_gateway.public_base_url,
                self.settings.log_http,
                self.settings.log_events,
                self.settings.log_commands,
                self.settings.log_command_status,
                self.settings.log_imports,
                self.settings.locale,
                self.settings.locale_dir,
                self.settings.admin_command_channel_id,
                self.settings.log_channel_id,
                self.settings.import_web_enabled,
                self.settings.import_web_host,
                self.settings.import_web_port,
                self.settings.import_web_base_url,
                self.settings.import_web_ttl_seconds,
                self.settings.log_to_file,
                self.settings.log_dir,
                self.settings.log_file,
                self.settings.log_max_bytes,
                self.settings.log_backup_count,
            )
            self.store.ensure_initialized()
            self.command_loader.load(force=True)
            if self.settings.import_web_enabled or self.settings.payment_enabled:
                await self._start_import_web_server()
            try:
                await gateway.run_forever()
            except asyncio.CancelledError:
                logger.info("shutdown requested")
                raise
            finally:
                await self._stop_import_web_server()
                self._session = None

    def run(self) -> None:
        try:
            asyncio.run(self.start())
        except KeyboardInterrupt:
            logger.info("stopped by user")

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

    async def create_payment_order(self, user_id: str, *, amount: int, pay_type: str) -> dict[str, object]:
        order_no = f"PAY{int(time.time())}{secrets.randbelow(1000000):06d}"
        result = self.payment_gateway.create_order(
            order_no=order_no,
            pay_type=pay_type,
            amount=amount,
            product_name=f"Balance Recharge {amount}",
        )
        self.store.create_payment_order(
            user_id,
            amount=amount,
            pay_type=pay_type,
            order_no=order_no,
            create_payload=result,
        )
        result["order_no"] = order_no
        result["submit_url"] = f"{self.payment_gateway.public_base_url}/payment/submit/{order_no}"
        return result

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

    async def _dispatch_message(self, event: MessageEvent) -> None:
        # 命令模块支持热加载，每次收到消息时先检查文件变更。
        self.command_loader.load()
        if self.settings.log_events:
            logger.debug("event received %s", event.log_summary)

        self._clear_expired_import_uploads()
        prefix = self.settings.command_prefix

        if event.is_bot:
            if self.settings.log_events:
                logger.debug("event ignored is_bot=%s msg_id=%s", event.is_bot, event.msg_id)
            return

        if event.attachments and not ((event.is_text or event.is_button_click) and event.content.startswith(prefix)):
            handled = await self._handle_pending_import_upload(event)
            if handled:
                return

        if event.author_id in self._pending_import_uploads and not (event.is_text or event.is_button_click):
            content_preview = event.content.replace("\n", "\\n")
            if len(content_preview) > 200:
                content_preview = f"{content_preview[:197]}..."
            self._log_import(
                "import pending event ignored author_id=%s msg_id=%s message_type=%s attachment_count=%s raw_keys=%s content_preview=%r",
                event.author_id,
                event.msg_id,
                event.message_type,
                len(event.attachments),
                sorted((event.raw_event.get("extra") or {}).keys()),
                content_preview,
            )

        if not (event.is_text or event.is_button_click):
            if self.settings.log_events:
                logger.debug(
                    "event ignored is_text=%s is_button_click=%s msg_id=%s",
                    event.is_text,
                    event.is_button_click,
                    event.msg_id,
                )
            return

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
