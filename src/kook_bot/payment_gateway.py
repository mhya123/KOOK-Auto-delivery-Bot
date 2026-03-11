from __future__ import annotations

import hashlib
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin, urlparse

from .config import Settings


class PaymentGatewayError(RuntimeError):
    pass


class MxlgPaymentGateway:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def is_configured(self) -> bool:
        return bool(
            self.settings.payment_enabled
            and self.settings.payment_pid
            and self.settings.payment_key
            and self._is_valid_http_url(self.public_base_url)
            and self._is_valid_http_url(self.settings.payment_api_base_url)
        )

    @property
    def public_base_url(self) -> str:
        return (self.settings.payment_base_url or self.settings.import_web_base_url).rstrip("/")

    @property
    def notify_url(self) -> str:
        return f"{self.public_base_url}{self.settings.payment_notify_path}"

    @property
    def return_url(self) -> str:
        return f"{self.public_base_url}{self.settings.payment_return_path}"

    @property
    def submit_url(self) -> str:
        return urljoin(f"{self.settings.payment_api_base_url.rstrip('/')}/", "submit.php")

    def create_order(
        self,
        *,
        order_no: str,
        pay_type: str,
        amount: int,
        product_name: str,
    ) -> dict[str, Any]:
        self.validate_config()
        money = f"{Decimal(amount):.2f}"
        payload = {
            "pid": self.settings.payment_pid,
            "type": pay_type,
            "out_trade_no": order_no,
            "notify_url": self.notify_url,
            "return_url": self.return_url,
            "name": product_name,
            "money": money,
            "sitename": self.settings.payment_sitename,
            "sign_type": "MD5",
        }
        payload["sign"] = self.sign(payload)
        payload["gateway_url"] = self.submit_url
        return payload

    def validate_config(self) -> None:
        if not self.settings.payment_enabled:
            raise PaymentGatewayError("payment is disabled")
        if not self.settings.payment_pid:
            raise PaymentGatewayError("payment pid is empty")
        if not self.settings.payment_key:
            raise PaymentGatewayError("payment key is empty")
        if not self._is_valid_http_url(self.settings.payment_api_base_url):
            raise PaymentGatewayError("payment api base url must start with http:// or https://")
        if not self._is_valid_http_url(self.public_base_url):
            raise PaymentGatewayError("payment base url must be a valid public http:// or https:// url")
        if not self._is_valid_http_url(self.notify_url):
            raise PaymentGatewayError("payment notify url is invalid")
        if not self._is_valid_http_url(self.return_url):
            raise PaymentGatewayError("payment return url is invalid")

    def sign(self, params: dict[str, Any]) -> str:
        sign_payload = self._build_sign_payload(params)
        digest = hashlib.md5(f"{sign_payload}{self.settings.payment_key}".encode("utf-8")).hexdigest()
        return digest

    def verify_callback(self, params: dict[str, str]) -> bool:
        incoming_sign = str(params.get("sign", "")).strip().lower()
        if not incoming_sign:
            return False
        expected = self.sign(params).lower()
        return incoming_sign == expected

    @staticmethod
    def parse_amount(value: str) -> int:
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise PaymentGatewayError("invalid callback amount") from exc
        return int(decimal_value.quantize(Decimal("1")))

    @staticmethod
    def _build_sign_payload(params: dict[str, Any]) -> str:
        filtered: list[tuple[str, str]] = []
        for key, value in params.items():
            if key in {"sign", "sign_type", "gateway_url"}:
                continue
            if value is None:
                continue
            text = str(value).strip()
            if not text:
                continue
            filtered.append((key, text))
        filtered.sort(key=lambda item: item[0])
        return "&".join(f"{key}={value}" for key, value in filtered)

    @staticmethod
    def _is_valid_http_url(value: str) -> bool:
        text = (value or "").strip()
        if not text:
            return False
        parsed = urlparse(text)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
