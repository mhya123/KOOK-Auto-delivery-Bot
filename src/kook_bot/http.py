from __future__ import annotations

import json
from typing import Any

from aiohttp import ClientSession, FormData

from .logging_utils import get_logger

logger = get_logger("kook_bot.http")


class KookApiError(RuntimeError):
    pass


class KookHttpClient:
    def __init__(self, session: ClientSession, token: str, base_url: str, *, log_http: bool = False) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._log_http = log_http
        self._headers = {
            "Authorization": token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def get_gateway_url(self, compress: int = 0) -> str:
        payload = await self._request("GET", "/gateway/index", params={"compress": compress})
        url = payload.get("url")
        if not url:
            raise KookApiError("Gateway URL missing from KOOK response.")
        return str(url)

    async def create_channel_message(
        self,
        channel_id: str,
        content: str,
        *,
        message_type: int = 9,
        reply_msg_id: str | None = None,
    ) -> dict[str, Any]:
        data = {
            "target_id": channel_id,
            "content": content,
            "type": message_type,
        }
        if reply_msg_id:
            data["reply_msg_id"] = reply_msg_id
        return await self._request("POST", "/message/create", json=data)

    async def create_direct_message(
        self,
        content: str,
        *,
        target_id: str | None = None,
        chat_code: str | None = None,
        message_type: int = 9,
        reply_msg_id: str | None = None,
    ) -> dict[str, Any]:
        data = {
            "content": content,
            "type": message_type,
        }
        if target_id:
            data["target_id"] = target_id
        if chat_code:
            data["chat_code"] = chat_code
        if not target_id and not chat_code:
            raise KookApiError("Direct message requires target_id or chat_code.")
        if reply_msg_id:
            data["reply_msg_id"] = reply_msg_id
        return await self._request("POST", "/direct-message/create", json=data)

    async def upload_asset(
        self,
        filename: str,
        content_bytes: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> str:
        form = FormData()
        form.add_field(
            "file",
            content_bytes,
            filename=filename,
            content_type=content_type,
        )
        payload = await self._request("POST", "/asset/create", data=form)
        url = payload.get("url")
        if not url:
            raise KookApiError("Asset upload response missing url.")
        return str(url)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        data: Any = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        if self._log_http:
            logger.debug("request method=%s path=%s params=%s json=%s data=%s", method, path, params, json, type(data).__name__)
        headers = dict(self._headers)
        if data is not None:
            headers.pop("Content-Type", None)
        async with self._session.request(
            method,
            url,
            params=params,
            json=json,
            data=data,
            headers=headers,
        ) as response:
            raw_text = await response.text()
            if self._log_http:
                logger.debug(
                    "response method=%s path=%s status=%s body=%s",
                    method,
                    path,
                    response.status,
                    raw_text,
                )
            response.raise_for_status()
            try:
                payload = json_module_loads(raw_text)
            except ValueError as exc:
                raise KookApiError(
                    f"KOOK API returned non-JSON response: status={response.status}, body={raw_text}"
                ) from exc

        code = payload.get("code")
        if code != 0:
            message = payload.get("message", "Unknown KOOK API error.")
            raise KookApiError(f"KOOK API request failed: code={code}, message={message}")

        data = payload.get("data")
        if not isinstance(data, dict):
            return {"value": data}
        return data


def json_module_loads(raw_text: str) -> dict[str, Any]:
    payload = json.loads(raw_text)
    if not isinstance(payload, dict):
        raise ValueError("JSON payload is not an object.")
    return payload
