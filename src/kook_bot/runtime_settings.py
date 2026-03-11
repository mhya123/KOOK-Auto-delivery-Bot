from __future__ import annotations

import time
from dataclasses import dataclass

from .config import Settings, set_dotenv_value
from .i18n import Translator


class RuntimeSettingError(RuntimeError):
    def __init__(self, message_key: str, **message_params: object) -> None:
        self.message_key = message_key
        self.message_params = message_params
        super().__init__(message_key)


@dataclass(slots=True)
class RuntimeSettingsManager:
    settings: Settings
    translator: Translator

    def set_locale(self, locale: str) -> str:
        normalized = locale.strip()
        available = set(self.translator.available_locales())
        if normalized not in available:
            raise RuntimeSettingError("error.runtime.locale_invalid", locale=normalized or "-")
        self.settings.locale = normalized
        self.translator.locale = normalized
        set_dotenv_value("KOOK_LOCALE", normalized)
        return normalized

    def set_payment_enabled(self, enabled: bool) -> bool:
        return self._set_bool("payment_enabled", "KOOK_PAYMENT_ENABLED", enabled)

    def set_payment_custom_amount_enabled(self, enabled: bool) -> bool:
        return self._set_bool("payment_allow_custom_amount", "KOOK_PAYMENT_ALLOW_CUSTOM_AMOUNT", enabled)

    def set_log_flag(self, flag_name: str, enabled: bool) -> bool:
        mapping = {
            "http": ("log_http", "KOOK_LOG_HTTP"),
            "events": ("log_events", "KOOK_LOG_EVENTS"),
            "commands": ("log_commands", "KOOK_LOG_COMMANDS"),
            "command_status": ("log_command_status", "KOOK_LOG_COMMAND_STATUS"),
            "imports": ("log_imports", "KOOK_LOG_IMPORTS"),
            "to_file": ("log_to_file", "KOOK_LOG_TO_FILE"),
        }
        spec = mapping.get(flag_name.strip().lower())
        if spec is None:
            raise RuntimeSettingError("error.runtime.log_flag_invalid", flag=flag_name)
        return self._set_bool(spec[0], spec[1], enabled)

    def set_admin_channel_id(self, channel_id: str) -> str:
        normalized = self._normalize_channel_value(channel_id)
        self.settings.admin_command_channel_id = normalized
        set_dotenv_value("KOOK_ADMIN_COMMAND_CHANNEL_ID", normalized)
        return normalized

    def set_log_channel_id(self, channel_id: str) -> str:
        normalized = self._normalize_channel_value(channel_id)
        self.settings.log_channel_id = normalized
        set_dotenv_value("KOOK_LOG_CHANNEL_ID", normalized)
        return normalized

    def set_payment_custom_amount_range(self, minimum: int, maximum: int) -> tuple[int, int]:
        if minimum <= 0 or maximum <= 0:
            raise RuntimeSettingError("error.runtime.custom_amount_range_invalid")
        self.settings.payment_custom_amount_min = int(minimum)
        self.settings.payment_custom_amount_max = int(maximum)
        set_dotenv_value("KOOK_PAYMENT_CUSTOM_AMOUNT_MIN", str(int(minimum)))
        set_dotenv_value("KOOK_PAYMENT_CUSTOM_AMOUNT_MAX", str(int(maximum)))
        return int(minimum), int(maximum)

    def set_recharge_card_format(self, template: str) -> str:
        normalized = template.strip()
        if not normalized:
            raise RuntimeSettingError("error.runtime.card_format_invalid")
        try:
            normalized.format(random="TESTCODE", timestamp=int(time.time()))
        except Exception as exc:
            raise RuntimeSettingError("error.runtime.card_format_invalid") from exc
        self.settings.recharge_card_format = normalized
        set_dotenv_value("KOOK_RECHARGE_CARD_FORMAT", normalized)
        return normalized

    def set_recharge_card_random_length(self, length: int) -> int:
        normalized = int(length)
        if normalized < 4:
            raise RuntimeSettingError("error.runtime.card_length_invalid")
        self.settings.recharge_card_random_length = normalized
        set_dotenv_value("KOOK_RECHARGE_CARD_RANDOM_LENGTH", str(normalized))
        return normalized

    def set_recharge_card_alphabet(self, alphabet: str) -> str:
        normalized = alphabet.strip()
        if not normalized:
            raise RuntimeSettingError("error.runtime.card_alphabet_invalid")
        self.settings.recharge_card_alphabet = normalized
        set_dotenv_value("KOOK_RECHARGE_CARD_ALPHABET", normalized)
        return normalized

    def _set_bool(self, attr_name: str, env_name: str, enabled: bool) -> bool:
        setattr(self.settings, attr_name, bool(enabled))
        set_dotenv_value(env_name, "true" if enabled else "false")
        return bool(enabled)

    def _normalize_channel_value(self, raw_value: str) -> str:
        normalized = raw_value.strip()
        if normalized.lower() in {"", "off", "none", "disable"}:
            return ""
        if not normalized.isdigit():
            raise RuntimeSettingError("error.runtime.channel_invalid", channel_id=normalized or "-")
        return normalized
