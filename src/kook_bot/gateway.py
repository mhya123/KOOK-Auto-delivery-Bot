from __future__ import annotations

import asyncio
import json
import random
import time
import zlib
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import ClientSession, WSMsgType

from .context import MessageEvent
from .kook_http import KookHttpClient
from .logging_utils import get_logger

logger = get_logger("kook_bot.gateway")


class ReconnectRequested(RuntimeError):
    pass


class KookGateway:
    def __init__(
        self,
        *,
        session: ClientSession,
        http: KookHttpClient,
        event_callback: Callable[[MessageEvent], Awaitable[None]],
        compress: int = 0,
        log_events: bool = False,
    ) -> None:
        self._session = session
        self._http = http
        self._event_callback = event_callback
        self._compress = compress
        self._log_events = log_events
        self._session_id: str | None = None
        self._sn = 0
        self._last_pong_at = time.monotonic()
        self._pong_event = asyncio.Event()

    async def run_forever(self) -> None:
        retry_delay = 2
        while True:
            try:
                gateway_url = await self._http.get_gateway_url(self._compress)
                logger.info("connecting url=%s", gateway_url)
                await self._run_connection(gateway_url)
                retry_delay = 2
            except asyncio.CancelledError:
                logger.info("gateway shutdown requested")
                raise
            except Exception as exc:
                logger.warning("disconnected: %s", exc)
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)

    async def _run_connection(self, gateway_url: str) -> None:
        # KOOK uses application-level heartbeats via signal packets, so disable
        # aiohttp's websocket heartbeat instead of setting it to 0.
        async with self._session.ws_connect(gateway_url, heartbeat=None) as ws:
            hello_msg = await ws.receive(timeout=6)
            hello_payload = self._decode_message(hello_msg)
            self._handle_hello(hello_payload)

            ping_task = asyncio.create_task(self._ping_loop(ws))
            loop_error: BaseException | None = None
            try:
                async for message in ws:
                    payload = self._decode_message(message)
                    await self._handle_payload(payload)
            except Exception as exc:
                loop_error = exc
                raise
            finally:
                ping_task.cancel()
                ping_results = await asyncio.gather(ping_task, return_exceptions=True)
                ping_error = ping_results[0] if ping_results else None
                if loop_error is None and isinstance(ping_error, BaseException) and not isinstance(
                    ping_error, asyncio.CancelledError
                ):
                    raise ping_error

    def _handle_hello(self, payload: dict[str, Any]) -> None:
        if payload.get("s") != 1:
            raise RuntimeError(f"Expected hello packet, got: {payload}")

        data = payload.get("d") or {}
        if data.get("code") != 0:
            raise RuntimeError(f"KOOK hello failed: {data}")

        self._session_id = str(data["session_id"])
        self._last_pong_at = time.monotonic()
        self._pong_event.set()
        logger.info("connected session_id=%s", self._session_id)

    async def _handle_payload(self, payload: dict[str, Any]) -> None:
        signal = payload.get("s")
        if self._log_events:
            logger.debug("payload signal=%s sn=%s raw=%s", signal, payload.get("sn"), payload)
        if signal == 0:
            sn = payload.get("sn")
            if isinstance(sn, int):
                self._sn = sn
            event = MessageEvent.from_payload(payload.get("d") or {})
            await self._event_callback(event)
            return

        if signal == 3:
            self._last_pong_at = time.monotonic()
            self._pong_event.set()
            return

        if signal == 5:
            self._sn = 0
            self._session_id = None
            reason = payload.get("d") or {}
            raise ReconnectRequested(f"Gateway requested reconnect: {reason}")

        if signal == 6:
            logger.info("resume acknowledged")
            return

    async def _ping_loop(self, ws) -> None:
        while True:
            await asyncio.sleep(30 + random.randint(-5, 5))
            self._pong_event.clear()
            logger.debug("ping sn=%s", self._sn)
            await ws.send_json({"s": 2, "sn": self._sn})
            sent_at = time.monotonic()
            try:
                await asyncio.wait_for(self._pong_event.wait(), timeout=6)
            except asyncio.TimeoutError as exc:
                await ws.close()
                raise TimeoutError(f"KOOK gateway heartbeat timed out after ping sn={self._sn}.") from exc

            if self._last_pong_at < sent_at:
                await ws.close()
                raise TimeoutError(f"KOOK gateway heartbeat timestamp stale after ping sn={self._sn}.")

            logger.debug("pong sn=%s", self._sn)

    def _decode_message(self, message) -> dict[str, Any]:
        if message.type == WSMsgType.TEXT:
            return json.loads(message.data)

        if message.type == WSMsgType.BINARY:
            raw = bytes(message.data)
            try:
                decoded = zlib.decompress(raw)
            except zlib.error:
                decoded = raw
            return json.loads(decoded.decode("utf-8"))

        if message.type == WSMsgType.CLOSE:
            raise RuntimeError(f"WebSocket close frame received: close_code={message.data!r}, extra={message.extra!r}")

        if message.type == WSMsgType.CLOSED:
            raise RuntimeError("WebSocket closed.")

        if message.type == WSMsgType.ERROR:
            raise RuntimeError(f"WebSocket error: {self._format_ws_error(message)}")

        raise RuntimeError(f"Unsupported WebSocket message type: {message.type}")

    @staticmethod
    def _format_ws_error(message) -> str:
        parts: list[str] = []
        if getattr(message, "data", None) is not None:
            parts.append(f"data={message.data!r}")
        if getattr(message, "extra", None) is not None:
            parts.append(f"extra={message.extra!r}")
        return ", ".join(parts) if parts else "unknown websocket error"
