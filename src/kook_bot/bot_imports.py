from __future__ import annotations

import html
import ipaddress
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from aiohttp import web
from aiohttp.web_exceptions import HTTPRequestEntityTooLarge

from .cards import build_status_cards
from .context import MessageEvent
from .logging_utils import get_logger
from .payment_gateway import PaymentGatewayError
from .permissions import Role, role_allows
from .store_service import StoreError

logger = get_logger("kook_bot.bot")


@dataclass(slots=True)
class PendingImportUpload:
    # 记录一次待上传的导入会话，便于做 30 秒时限、上传人校验和网页上传。
    user_id: str
    product_id: str
    price: int
    mode: str
    channel_type: str
    target_id: str
    chat_code: str
    upload_id: str
    password: str
    expires_at: int
    status: str


class BotImportMixin:
    # 导入相关的状态机统一收口在这里，避免命令分发层继续膨胀。
    async def _start_import_web_server(self) -> None:
        if self._import_web_runner is not None:
            return

        app = web.Application(client_max_size=self.settings.import_web_max_body_mb * 1024 * 1024)
        routes: list[web.RouteDef] = []
        if self.settings.import_web_enabled:
            routes.extend(
                [
                    web.get("/import/{upload_id}", self._handle_import_web_page),
                    web.post("/import/{upload_id}", self._handle_import_web_submit),
                ]
            )
        if self.settings.payment_enabled:
            routes.extend(
                [
                    web.get("/payment/submit/{order_no}", self._handle_payment_submit_page),
                    web.get(self.settings.payment_notify_path, self._handle_payment_notify),
                    web.get(self.settings.payment_return_path, self._handle_payment_return),
                ]
            )
        app.add_routes(routes)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host=self.settings.import_web_host, port=self.settings.import_web_port)
        await site.start()
        self._import_web_runner = runner
        self._warn_import_web_binding()
        logger.info(
            "internal web server listening host=%s port=%s import_base_url=%s payment_base_url=%s",
            self.settings.import_web_host,
            self.settings.import_web_port,
            self.settings.import_web_base_url,
            self.payment_gateway.public_base_url,
        )

    async def _stop_import_web_server(self) -> None:
        if self._import_web_runner is None:
            return
        await self._import_web_runner.cleanup()
        self._import_web_runner = None

    def _warn_import_web_binding(self) -> None:
        host = (self.settings.import_web_host or "").strip().lower()
        if host not in {"127.0.0.1", "localhost", "::1"}:
            return

        parsed = urlparse(self.payment_gateway.public_base_url or self.settings.import_web_base_url)
        base_host = (parsed.hostname or "").strip().lower()
        if base_host in {"127.0.0.1", "localhost", "::1"}:
            logger.warning(
                "internal web server is bound to loopback host=%s and base_url=%s, external users will not be able to access it",
                self.settings.import_web_host,
                self.payment_gateway.public_base_url or self.settings.import_web_base_url,
            )
            return

        try:
            if ipaddress.ip_address(base_host).is_loopback:
                logger.warning(
                    "internal web server is bound to loopback host=%s and base_url=%s, external users will not be able to access it",
                    self.settings.import_web_host,
                    self.payment_gateway.public_base_url or self.settings.import_web_base_url,
                )
                return
        except ValueError:
            pass

        logger.warning(
            "internal web server is bound to loopback host=%s but base_url=%s looks external, this mismatch will block public access; use KOOK_IMPORT_WEB_HOST=0.0.0.0",
            self.settings.import_web_host,
            self.payment_gateway.public_base_url or self.settings.import_web_base_url,
        )

    async def _handle_payment_notify(self, request: web.Request) -> web.Response:
        params = {str(key): str(value) for key, value in request.query.items()}
        order_no = params.get("out_trade_no", "")
        self._log_import("payment notify received order_no=%s remote=%s", order_no, request.remote)

        if not self.payment_gateway.verify_callback(params):
            logger.warning("payment notify rejected reason=bad_sign order_no=%s", order_no)
            return web.Response(text="fail", status=400)

        if params.get("trade_status") != "TRADE_SUCCESS":
            logger.warning("payment notify rejected reason=bad_status order_no=%s status=%s", order_no, params.get("trade_status"))
            return web.Response(text="fail", status=400)

        try:
            result = self.store.complete_payment_order(
                order_no=order_no,
                trade_no=params.get("trade_no", ""),
                amount=self.payment_gateway.parse_amount(params.get("money", "0")),
                pay_type=params.get("type", ""),
                notify_payload=params,
            )
        except (StoreError, PaymentGatewayError):
            logger.exception("payment notify failed order_no=%s", order_no)
            return web.Response(text="fail", status=400)

        if result is None:
            logger.warning("payment notify rejected reason=order_not_found order_no=%s", order_no)
            return web.Response(text="fail", status=404)

        if not bool(result.get("already_paid")):
            await self._notify_payment_success(result)
        return web.Response(text="success")

    async def _handle_payment_submit_page(self, request: web.Request) -> web.Response:
        order_no = request.match_info.get("order_no", "")
        payload = self.store.get_payment_submit_payload(order_no)
        if payload is None:
            return web.Response(
                text=self._render_payment_result_page(self.t("payment.submit.not_found")),
                content_type="text/html",
                status=404,
            )

        gateway_url = str(payload.get("gateway_url", "")).strip()
        if not gateway_url:
            return web.Response(
                text=self._render_payment_result_page(self.t("payment.submit.invalid")),
                content_type="text/html",
                status=400,
            )

        return web.Response(
            text=self._render_payment_submit_page(gateway_url, payload),
            content_type="text/html",
        )

    async def _handle_payment_return(self, request: web.Request) -> web.Response:
        params = {str(key): str(value) for key, value in request.query.items()}
        order_no = params.get("out_trade_no", "")
        if not self.payment_gateway.verify_callback(params):
            return web.Response(
                text=self._render_payment_result_page(self.t("payment.return.invalid_sign")),
                content_type="text/html",
                status=400,
            )

        if params.get("trade_status") != "TRADE_SUCCESS":
            return web.Response(
                text=self._render_payment_result_page(self.t("payment.return.failed")),
                content_type="text/html",
                status=400,
            )

        order = self.store.get_payment_order(order_no)
        amount_text = params.get("money", "0")
        body = self.t("payment.return.success", order_no=order_no, amount=amount_text)
        if order is not None and str(order.get("status", "")) != "paid":
            try:
                result = self.store.complete_payment_order(
                    order_no=order_no,
                    trade_no=params.get("trade_no", ""),
                    amount=self.payment_gateway.parse_amount(params.get("money", "0")),
                    pay_type=params.get("type", ""),
                    notify_payload=params,
                )
                if result is not None and not bool(result.get("already_paid")):
                    await self._notify_payment_success(result)
            except (StoreError, PaymentGatewayError):
                logger.exception("payment return processing failed order_no=%s", order_no)

        return web.Response(
            text=self._render_payment_result_page(body),
            content_type="text/html",
        )

    def _render_payment_result_page(self, message: str) -> str:
        safe_message = html.escape(message)
        return (
            f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(self.t('payment.return.page_title'))}</title>"
            "<style>body{font-family:Segoe UI,Arial,sans-serif;max-width:640px;margin:40px auto;padding:0 16px;color:#1f2937;}"
            ".box{padding:20px;background:#f3f4f6;border-radius:10px;}</style></head><body>"
            f"<h1>{html.escape(self.t('payment.return.page_title'))}</h1>"
            f"<div class='box'><p>{safe_message}</p></div></body></html>"
        )

    def _render_payment_submit_page(self, gateway_url: str, payload: dict[str, str]) -> str:
        inputs: list[str] = []
        for key, value in payload.items():
            if key == "gateway_url":
                continue
            inputs.append(
                f"<input type='hidden' name='{html.escape(key)}' value='{html.escape(value)}' />"
            )
        return (
            f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(self.t('payment.submit.page_title'))}</title>"
            "<style>body{font-family:Segoe UI,Arial,sans-serif;max-width:640px;margin:40px auto;padding:0 16px;color:#1f2937;}"
            ".box{padding:20px;background:#f3f4f6;border-radius:10px;}"
            "button{display:inline-block;margin-top:16px;padding:12px 18px;background:#0f766e;color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:14px;}"
            "button:hover{background:#115e59;}</style></head>"
            f"<body onload='document.getElementById(\"pay-form\").submit()'>"
            f"<h1>{html.escape(self.t('payment.submit.page_title'))}</h1>"
            f"<div class='box'><p>{html.escape(self.t('payment.submit.redirecting'))}</p></div>"
            f"<form id='pay-form' method='post' action='{html.escape(gateway_url)}'>"
            f"{''.join(inputs)}"
            f"<button type='submit'>{html.escape(self.t('payment.submit.manual_button'))}</button>"
            "</form></body></html>"
        )

    async def _notify_payment_success(self, result: dict[str, object]) -> None:
        cards = build_status_cards(
            self.t("payment.notify.title"),
            body=self.t(
                "payment.notify.body",
                amount=result["amount"],
                balance_after=result["balance_after"],
                order_no=result["order_no"],
            ),
            facts=[
                (self.t("payment.field.amount"), str(result["amount"])),
                (self.t("payment.field.balance_after"), str(result["balance_after"])),
                (self.t("payment.field.order_no"), str(result["order_no"])),
            ],
            theme="success",
        )
        try:
            await self.send_direct_card(cards, target_id=str(result["user_id"]))
        except Exception:
            logger.exception("failed to send payment success notice user_id=%s", result["user_id"])

    async def _handle_import_web_page(self, request: web.Request) -> web.Response:
        upload_id = request.match_info.get("upload_id", "")
        self._log_import("import web page request upload_id=%s remote=%s", upload_id, request.remote)
        session = self._find_pending_import_upload_by_id(upload_id)
        if session is None:
            return web.Response(
                text=self._render_import_web_page(self.t("web.import.session_missing")),
                content_type="text/html",
            )
        if session.mode != "web":
            return web.Response(
                text=self._render_import_web_page(self.t("web.import.mode_mismatch")),
                content_type="text/html",
            )
        if session.expires_at <= int(time.time()):
            self._pending_import_uploads.pop(session.user_id, None)
            return web.Response(
                text=self._render_import_web_page(self.t("web.import.expired")),
                content_type="text/html",
            )

        expires_in = max(0, session.expires_at - int(time.time()))
        return web.Response(
            text=self._render_import_web_page(
                self.t("web.import.page_intro"),
                upload_id=session.upload_id,
                product_id=session.product_id,
                price=session.price,
                expires_in=expires_in,
            ),
            content_type="text/html",
        )

    async def _handle_import_web_submit(self, request: web.Request) -> web.Response:
        upload_id = request.match_info.get("upload_id", "")
        self._log_import("import web submit upload_id=%s remote=%s", upload_id, request.remote)
        session = self._find_pending_import_upload_by_id(upload_id)
        if session is None:
            return web.Response(
                text=self._render_import_web_page(self.t("web.import.session_missing")),
                content_type="text/html",
            )
        if session.mode != "web":
            return web.Response(
                text=self._render_import_web_page(self.t("web.import.mode_mismatch")),
                content_type="text/html",
            )
        if session.expires_at <= int(time.time()):
            self._pending_import_uploads.pop(session.user_id, None)
            return web.Response(
                text=self._render_import_web_page(self.t("web.import.expired")),
                content_type="text/html",
            )

        try:
            post_data = await request.post()
        except HTTPRequestEntityTooLarge:
            self._log_import(
                "import web rejected upload_id=%s reason=body_too_large limit_mb=%s",
                upload_id,
                self.settings.import_web_max_body_mb,
            )
            return web.Response(
                text=self._render_import_web_page(
                    self.t("web.import.body_too_large", max_mb=self.settings.import_web_max_body_mb),
                    upload_id=session.upload_id,
                    product_id=session.product_id,
                    price=session.price,
                ),
                content_type="text/html",
                status=413,
            )
        password = str(post_data.get("password", "")).strip()
        uploaded_file = post_data.get("file")
        if password != session.password:
            self._log_import("import web rejected upload_id=%s reason=bad_password", upload_id)
            return web.Response(
                text=self._render_import_web_page(
                    self.t("web.import.bad_password"),
                    upload_id=session.upload_id,
                    product_id=session.product_id,
                    price=session.price,
                ),
                content_type="text/html",
                status=403,
            )
        if uploaded_file is None or not hasattr(uploaded_file, "file"):
            return web.Response(
                text=self._render_import_web_page(self.t("web.import.choose_file")),
                content_type="text/html",
                status=400,
            )

        filename = str(getattr(uploaded_file, "filename", "") or "").strip()
        if not self._is_supported_import_attachment({"name": filename, "url": "", "file_type": ""}):
            self._log_import("import web rejected upload_id=%s reason=invalid_file_name filename=%s", upload_id, filename)
            return web.Response(
                text=self._render_import_web_page(self.t("web.import.unsupported_file")),
                content_type="text/html",
                status=400,
            )

        raw_bytes = uploaded_file.file.read()
        if not isinstance(raw_bytes, bytes) or not raw_bytes:
            self._log_import("import web rejected upload_id=%s reason=empty_file filename=%s", upload_id, filename)
            return web.Response(
                text=self._render_import_web_page(self.t("web.import.empty_file")),
                content_type="text/html",
                status=400,
            )

        try:
            result = await self._process_import_bytes(session, raw_bytes, source_name=filename or "upload.txt", source_kind="web")
        except StoreError as exc:
            return web.Response(
                text=self._render_import_web_page(
                    self.t(
                        "web.import.failed",
                        reason=self.t(exc.message_key, **dict(exc.message_params)),
                    ),
                    upload_id=session.upload_id,
                    product_id=session.product_id,
                    price=session.price,
                ),
                content_type="text/html",
                status=400,
            )

        await self._notify_web_import_success(session, result)

        return web.Response(
            text=self._render_import_web_page(
                self.t(
                    "web.import.success",
                    product_id=result["product_id"],
                    parsed_total=result["parsed_total"],
                    inserted_count=result["inserted_count"],
                    skipped_duplicates=result["skipped_duplicates"],
                ),
                upload_id=session.upload_id,
                product_id=session.product_id,
                price=session.price,
            ),
            content_type="text/html",
        )

    def start_pending_import_upload(
        self,
        event: MessageEvent,
        product_id: str,
        price: int,
        *,
        mode: str = "attachment",
        ttl_seconds: int = 30,
    ) -> PendingImportUpload:
        now = int(time.time())
        self._clear_expired_import_uploads(now)
        status = "created"
        if event.author_id in self._pending_import_uploads:
            status = "replaced"
        pending = PendingImportUpload(
            user_id=event.author_id,
            product_id=product_id,
            price=price,
            mode=mode,
            channel_type=event.channel_type,
            target_id=event.target_id,
            chat_code=event.chat_code,
            upload_id=secrets.token_urlsafe(18),
            password=secrets.token_hex(4).upper(),
            expires_at=now + ttl_seconds,
            status=status,
        )
        self._pending_import_uploads[event.author_id] = pending
        self._log_import(
            "import pending %s author_id=%s product_id=%s price=%s mode=%s channel_type=%s target_id=%s chat_code=%s upload_id=%s expires_at=%s",
            status,
            event.author_id,
            product_id,
            price,
            mode,
            event.channel_type,
            event.target_id,
            event.chat_code,
            pending.upload_id,
            now + ttl_seconds,
        )
        return pending

    def cancel_pending_import_upload(self, user_id: str) -> bool:
        cancelled = self._pending_import_uploads.pop(user_id, None) is not None
        self._log_import("import pending cancel author_id=%s cancelled=%s", user_id, cancelled)
        return cancelled

    def import_web_available(self) -> bool:
        return self.settings.import_web_enabled and bool(self.settings.import_web_base_url.strip())

    def build_import_upload_url(self, upload_id: str) -> str:
        base_url = self.settings.import_web_base_url.rstrip("/")
        return f"{base_url}/import/{upload_id}"

    async def notify_restock_subscribers(self, result: dict[str, object]) -> None:
        await self._notify_restock_subscribers(result)

    def _find_pending_import_upload_by_id(self, upload_id: str) -> PendingImportUpload | None:
        for session in self._pending_import_uploads.values():
            if session.upload_id == upload_id:
                return session
        return None

    def _render_import_web_page(
        self,
        message: str,
        *,
        upload_id: str = "",
        product_id: str = "",
        price: int | str = "",
        expires_in: int | None = None,
    ) -> str:
        safe_message = html.escape(message)
        safe_upload_id = html.escape(upload_id)
        safe_product_id = html.escape(str(product_id))
        safe_price = html.escape(str(price))
        expires_line = ""
        if expires_in is not None:
            expires_line = (
                f"<p>{html.escape(self.t('web.import.expires_in_label'))}: "
                f"<strong>{html.escape(str(expires_in))}</strong> {html.escape(self.t('web.import.seconds_unit'))}</p>"
            )
        meta_parts: list[str] = []
        if upload_id:
            meta_parts.append(
                f"<p>{html.escape(self.t('web.import.upload_id_label'))}: <strong>{safe_upload_id}</strong></p>"
            )
        if product_id != "":
            meta_parts.append(
                f"<p>{html.escape(self.t('web.import.product_id_label'))}: <strong>{safe_product_id}</strong></p>"
            )
        if price != "":
            meta_parts.append(
                f"<p>{html.escape(self.t('web.import.price_label'))}: <strong>{safe_price}</strong></p>"
            )
        if expires_line:
            meta_parts.append(expires_line)

        meta_block = ""
        if meta_parts:
            meta_block = f"<div class='meta'>{''.join(meta_parts)}</div>"

        form = ""
        if upload_id:
            form = (
                "<form method='post' enctype='multipart/form-data'>"
                f"<label>{html.escape(self.t('web.import.password_label'))}</label>"
                "<input type='password' name='password' required />"
                f"<label>{html.escape(self.t('web.import.file_label'))}</label>"
                "<input type='file' name='file' accept='.txt,.csv,text/plain,text/csv' required />"
                f"<button type='submit'>{html.escape(self.t('web.import.submit_button'))}</button>"
                "</form>"
            )
        return (
            f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(self.t('web.import.page_title'))}</title>"
            "<style>body{font-family:Segoe UI,Arial,sans-serif;max-width:640px;margin:40px auto;padding:0 16px;color:#1f2937;}"
            "input,button{display:block;width:100%;margin-top:8px;margin-bottom:16px;padding:10px;font-size:14px;}"
            "button{background:#0f766e;color:#fff;border:none;border-radius:6px;cursor:pointer;}"
            ".meta{padding:12px 16px;background:#f3f4f6;border-radius:8px;margin:16px 0;}</style></head><body>"
            f"<h1>{html.escape(self.t('web.import.page_header'))}</h1>"
            f"<p>{safe_message}</p>"
            f"{meta_block}"
            f"{form}</body></html>"
        )

    async def _process_import_bytes(
        self,
        session: PendingImportUpload,
        raw_bytes: bytes,
        *,
        source_name: str,
        source_kind: str,
    ) -> dict[str, Any]:
        self._log_import(
            "import bytes processing author_id=%s product_id=%s mode=%s source_kind=%s source_name=%s bytes=%s",
            session.user_id,
            session.product_id,
            session.mode,
            source_kind,
            source_name,
            len(raw_bytes),
        )
        decoded_text = self._decode_import_file(raw_bytes)
        key_contents = decoded_text.splitlines()
        self._log_import(
            "import decode success author_id=%s product_id=%s lines=%s preview=%r",
            session.user_id,
            session.product_id,
            len(key_contents),
            key_contents[:3],
        )
        result = self.store.import_keys(
            session.user_id,
            session.product_id,
            session.price,
            key_contents,
        )
        self._pending_import_uploads.pop(session.user_id, None)
        self._log_import(
            "import store success author_id=%s product_id=%s parsed_total=%s inserted_count=%s skipped_duplicates=%s restock_notify_count=%s source_kind=%s",
            session.user_id,
            result["product_id"],
            result["parsed_total"],
            result["inserted_count"],
            result["skipped_duplicates"],
            len(result.get("restock_user_ids", [])) if isinstance(result.get("restock_user_ids"), list) else 0,
            source_kind,
        )
        await self._notify_restock_subscribers(result)
        return result

    async def _notify_web_import_success(
        self,
        session: PendingImportUpload,
        result: dict[str, Any],
    ) -> None:
        cards = build_status_cards(
            self.t("web.import.notify_title"),
            body=self.t(
                "web.import.notify_body",
                product_id=result["product_id"],
                parsed_total=result["parsed_total"],
                inserted_count=result["inserted_count"],
                skipped_duplicates=result["skipped_duplicates"],
            ),
            facts=[
                (self.t("store.import_file.field.product_id"), str(result["product_id"])),
                (self.t("store.import_file.field.price"), str(session.price)),
                (self.t("store.import_file.field.inserted_count"), str(result["inserted_count"])),
            ],
            theme="success",
        )
        try:
            await self.send_direct_card(cards, target_id=session.user_id)
            self._log_import(
                "import web notify success author_id=%s product_id=%s inserted_count=%s",
                session.user_id,
                result["product_id"],
                result["inserted_count"],
            )
        except Exception:
            logger.exception(
                "import web notify failed author_id=%s product_id=%s",
                session.user_id,
                result.get("product_id", ""),
            )

    def _clear_expired_import_uploads(self, now: int | None = None) -> None:
        current_time = now or int(time.time())
        expired_user_ids = [
            user_id
            for user_id, session in self._pending_import_uploads.items()
            if session.expires_at <= current_time
        ]
        for user_id in expired_user_ids:
            self._log_import(
                "import pending expired author_id=%s product_id=%s target_id=%s expired_at=%s now=%s",
                user_id,
                self._pending_import_uploads[user_id].product_id,
                self._pending_import_uploads[user_id].target_id,
                self._pending_import_uploads[user_id].expires_at,
                current_time,
            )
            self._pending_import_uploads.pop(user_id, None)

    async def _handle_pending_import_upload(self, event: MessageEvent) -> bool:
        self._log_import(
            "import upload received author_id=%s channel_type=%s target_id=%s chat_code=%s attachment_count=%s attachment_names=%s msg_id=%s",
            event.author_id,
            event.channel_type,
            event.target_id,
            event.chat_code,
            len(event.attachments),
            [attachment.get("name", "") for attachment in event.attachments],
            event.msg_id,
        )
        if not role_allows(self.get_role(event.author_id), Role.ADMIN):
            self._log_import("import upload ignored author_id=%s reason=not_admin", event.author_id)
            return False

        session = self._pending_import_uploads.get(event.author_id)
        if session is None:
            attachment = self._pick_import_attachment(event.attachments)
            if attachment is None:
                self._log_import("import upload ignored author_id=%s reason=no_pending_and_no_supported_attachment", event.author_id)
                return False
            self._log_import(
                "import upload rejected author_id=%s reason=no_pending attachment_name=%s",
                event.author_id,
                attachment.get("name", ""),
            )
            await self.reply_card_to_event(
                event,
                build_status_cards(
                    self.t("common.status.warning_title"),
                    body=self.t("store.import_file.no_pending_upload"),
                    theme="warning",
                ),
            )
            return True

        if session.expires_at <= int(time.time()):
            self._pending_import_uploads.pop(event.author_id, None)
            self._log_import(
                "import upload rejected author_id=%s reason=expired product_id=%s expired_at=%s",
                event.author_id,
                session.product_id,
                session.expires_at,
            )
            await self.reply_card_to_event(
                event,
                build_status_cards(
                    self.t("common.status.warning_title"),
                    body=self.t("store.import_file.expired"),
                    theme="warning",
                ),
            )
            return True

        if session.mode != "attachment":
            self._log_import(
                "import upload rejected author_id=%s reason=mode_mismatch session_mode=%s",
                event.author_id,
                session.mode,
            )
            await self.reply_card_to_event(
                event,
                build_status_cards(
                    self.t("common.status.warning_title"),
                    body=self.t("store.import_file.mode_mismatch_web"),
                    theme="warning",
                ),
            )
            return True

        if not self._matches_pending_import_upload(session, event):
            self._log_import(
                "import upload rejected author_id=%s reason=wrong_channel expected_channel_type=%s actual_channel_type=%s expected_target_id=%s actual_target_id=%s expected_chat_code=%s actual_chat_code=%s",
                event.author_id,
                session.channel_type,
                event.channel_type,
                session.target_id,
                event.target_id,
                session.chat_code,
                event.chat_code,
            )
            await self.reply_card_to_event(
                event,
                build_status_cards(
                    self.t("common.status.warning_title"),
                    body=self.t("store.import_file.wrong_channel"),
                    theme="warning",
                ),
            )
            return True

        attachment = self._pick_import_attachment(event.attachments)
        if attachment is None:
            first_attachment = event.attachments[0] if event.attachments else {"name": "unknown"}
            self._log_import(
                "import upload rejected author_id=%s reason=no_supported_attachment attachment_names=%s",
                event.author_id,
                [item.get("name", "") for item in event.attachments],
            )
            await self.reply_card_to_event(
                event,
                build_status_cards(
                    self.t("common.status.warning_title"),
                    body=self.t("store.import_file.invalid_attachment", file_name=first_attachment.get("name") or "unknown"),
                    theme="warning",
                ),
            )
            return True

        if not self._is_supported_import_attachment(attachment):
            self._log_import(
                "import upload rejected author_id=%s reason=unsupported_attachment attachment_name=%s file_type=%s url=%s",
                event.author_id,
                attachment.get("name", ""),
                attachment.get("file_type", ""),
                attachment.get("url", ""),
            )
            await self.reply_card_to_event(
                event,
                build_status_cards(
                    self.t("common.status.warning_title"),
                    body=self.t("store.import_file.invalid_attachment", file_name=attachment.get("name") or "unknown"),
                    theme="warning",
                ),
            )
            return True

        attachment_url = attachment.get("url", "").strip()
        if not attachment_url:
            self._log_import(
                "import upload rejected author_id=%s reason=empty_attachment_url attachment_name=%s",
                event.author_id,
                attachment.get("name", ""),
            )
            await self.reply_card_to_event(
                event,
                build_status_cards(
                    self.t("common.status.warning_title"),
                    body=self.t("store.import_file.invalid_attachment", file_name=attachment.get("name") or "unknown"),
                    theme="warning",
                ),
            )
            return True

        try:
            self._log_import(
                "import download start author_id=%s product_id=%s attachment_name=%s url=%s",
                event.author_id,
                session.product_id,
                attachment.get("name", ""),
                attachment_url,
            )
            raw_bytes = await self.download_attachment_bytes(attachment_url)
            self._log_import(
                "import download success author_id=%s product_id=%s bytes=%s attachment_name=%s",
                event.author_id,
                session.product_id,
                len(raw_bytes),
                attachment.get("name", ""),
            )
        except Exception:
            logger.exception(
                "import download failed author_id=%s product_id=%s attachment_name=%s url=%s",
                event.author_id,
                session.product_id,
                attachment.get("name", ""),
                attachment_url,
            )
            await self.reply_card_to_event(
                event,
                build_status_cards(
                    self.t("common.status.error_title"),
                    body=self.t("store.import_file.download_failed"),
                    theme="danger",
                ),
            )
            return True

        try:
            result = await self._process_import_bytes(
                session,
                raw_bytes,
                source_name=attachment.get("name", "") or "attachment.txt",
                source_kind="attachment",
            )
        except StoreError as exc:
            self._log_import(
                "import store rejected author_id=%s product_id=%s message_key=%s params=%s",
                session.user_id,
                session.product_id,
                exc.message_key,
                exc.message_params,
            )
            await self.reply_card_to_event(
                event,
                build_status_cards(
                    self.t("common.status.error_title"),
                    body=self.t(exc.message_key, **dict(exc.message_params)),
                    theme="danger",
                ),
            )
            return True

        await self.reply_card_to_event(
            event,
            build_status_cards(
                self.t("common.status.success_title"),
                body=self.t(
                    "store.import_file.success",
                    product_id=result["product_id"],
                    parsed_total=result["parsed_total"],
                    inserted_count=result["inserted_count"],
                    skipped_duplicates=result["skipped_duplicates"],
                ),
                facts=[
                    (self.t("store.import_file.field.product_id"), str(result["product_id"])),
                    (self.t("store.import_file.field.price"), str(session.price)),
                    (self.t("store.import_file.field.inserted_count"), str(result["inserted_count"])),
                ],
                theme="success",
            ),
        )
        return True

    def _matches_pending_import_upload(self, session: PendingImportUpload, event: MessageEvent) -> bool:
        if session.channel_type != event.channel_type:
            return False
        if event.is_direct:
            return session.chat_code == event.chat_code or session.user_id == event.author_id
        return session.target_id == event.target_id

    async def _notify_restock_subscribers(self, result: dict[str, object]) -> None:
        user_ids = result.get("restock_user_ids")
        if not isinstance(user_ids, list) or not user_ids:
            self._log_import(
                "restock notify skipped product_id=%s reason=no_subscribers",
                result.get("product_id", ""),
            )
            return

        self._log_import(
            "restock notify start product_id=%s subscriber_count=%s",
            result.get("product_id", ""),
            len(user_ids),
        )
        cards = build_status_cards(
            self.t("store.restock_notify.title"),
            body=self.t(
                "store.restock_notify.body",
                product_id=result.get("product_id", ""),
                product_name=result.get("product_name", ""),
            ),
            theme="warning",
        )
        delivered_user_ids: list[str] = []
        for user_id in user_ids:
            try:
                await self.send_direct_card(cards, target_id=str(user_id))
                delivered_user_ids.append(str(user_id))
                self._log_import(
                    "restock notify sent product_id=%s user_id=%s",
                    result.get("product_id", ""),
                    user_id,
                )
            except Exception:
                logger.exception("failed to send restock notification user_id=%s", user_id)
        if delivered_user_ids:
            cleared_count = self.store.clear_product_subscriptions(int(result.get("product_id", 0) or 0), delivered_user_ids)
            self._log_import(
                "restock notify cleanup product_id=%s cleared_count=%s",
                result.get("product_id", ""),
                cleared_count,
            )

    def _pick_import_attachment(self, attachments: tuple[dict[str, str], ...]) -> dict[str, str] | None:
        for attachment in attachments:
            if self._is_supported_import_attachment(attachment):
                return attachment
        return None

    def _is_supported_import_attachment(self, attachment: dict[str, str]) -> bool:
        name = attachment.get("name", "").lower()
        url = attachment.get("url", "").lower()
        file_type = attachment.get("file_type", "").lower()
        return (
            name.endswith(".txt")
            or name.endswith(".csv")
            or url.endswith(".txt")
            or url.endswith(".csv")
            or file_type in {"txt", "csv", "text/plain", "text/csv"}
        )

    def _decode_import_file(self, raw_bytes: bytes) -> str:
        for encoding in ("utf-8-sig", "utf-8", "gbk"):
            try:
                return raw_bytes.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw_bytes.decode("utf-8", errors="replace")
