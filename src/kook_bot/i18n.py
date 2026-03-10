from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .logging_utils import get_logger

logger = get_logger("kook_bot.i18n")

LOCALE_ALIASES = {
    "en": "en-US",
    "en-us": "en-US",
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
}


@dataclass(slots=True)
class Translator:
    locale: str
    locales_dir: Path
    fallback_locale: str = "en-US"
    _catalog_cache: dict[str, dict[str, str]] = field(default_factory=dict, init=False)
    _mtime_cache: dict[str, int] = field(default_factory=dict, init=False)
    _missing_locale_logged: set[str] = field(default_factory=set, init=False)

    def translate(self, key: str, **params: object) -> str:
        locale = self._normalize_locale(self.locale)
        fallback_locale = self._normalize_locale(self.fallback_locale)

        template = self._load_catalog(locale).get(key)
        if template is None and locale != fallback_locale:
            template = self._load_catalog(fallback_locale).get(key)
        if template is None:
            template = key

        try:
            return template.format(**params)
        except Exception:
            return template

    def available_locales(self) -> tuple[str, ...]:
        if not self.locales_dir.exists():
            return ()
        locales = {
            path.stem
            for path in self.locales_dir.glob("*.json")
            if path.is_file()
        }
        return tuple(sorted(locales))

    def _load_catalog(self, locale: str) -> dict[str, str]:
        path = self.locales_dir / f"{locale}.json"
        if not path.exists():
            if locale not in self._missing_locale_logged:
                logger.warning("locale file not found locale=%s path=%s", locale, path)
                self._missing_locale_logged.add(locale)
            return {}

        try:
            mtime_ns = path.stat().st_mtime_ns
        except OSError:
            return {}

        cached_mtime = self._mtime_cache.get(locale)
        if cached_mtime == mtime_ns:
            return self._catalog_cache.get(locale, {})

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("failed to load locale file locale=%s path=%s", locale, path)
            return self._catalog_cache.get(locale, {})

        if not isinstance(raw, dict):
            logger.warning("locale file root must be an object locale=%s path=%s", locale, path)
            return self._catalog_cache.get(locale, {})

        catalog = {
            str(key): str(value)
            for key, value in raw.items()
            if isinstance(key, str) and isinstance(value, str)
        }
        self._catalog_cache[locale] = catalog
        self._mtime_cache[locale] = mtime_ns
        return catalog

    @staticmethod
    def _normalize_locale(locale: str) -> str:
        normalized = locale.strip().lower()
        return LOCALE_ALIASES.get(normalized, locale.strip() or "en-US")
