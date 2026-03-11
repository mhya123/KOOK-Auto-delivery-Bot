from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _env_csv(name: str, default: str = "") -> tuple[str, ...]:
    raw = os.getenv(name, default)
    values = [item.strip() for item in raw.split(",")]
    return tuple(item for item in values if item)


def _load_dotenv() -> None:
    project_root = Path(__file__).resolve().parents[2]
    dotenv_path = project_root / ".env"
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


@dataclass(slots=True)
class Settings:
    token: str
    command_prefix: str = "/"
    locale: str = "en-US"
    locale_dir: str = "locales"
    admin_command_channel_id: str = "4760888878941680"
    log_channel_id: str = "4760888878941680"
    api_base_url: str = "https://www.kookapp.cn/api/v3"
    gateway_compress: int = 0
    super_admin_ids: tuple[str, ...] = ("2744428583",)
    db_backend: str = "sqlite"
    sqlite_path: str = "data/kook-bot.db"
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "kook_bot"
    log_level: str = "INFO"
    log_http: bool = False
    log_events: bool = False
    log_commands: bool = False
    log_command_status: bool = False
    log_imports: bool = False
    import_web_enabled: bool = False
    import_web_host: str = "127.0.0.1"
    import_web_port: int = 18080
    import_web_base_url: str = "http://127.0.0.1:18080"
    import_web_ttl_seconds: int = 600
    log_to_file: bool = True
    log_dir: str = "logs"
    log_file: str = "kook-bot.log"
    log_max_bytes: int = 5 * 1024 * 1024
    log_backup_count: int = 7

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        token = os.getenv("KOOK_BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("Missing KOOK_BOT_TOKEN environment variable.")
        if not token.startswith("Bot "):
            token = f"Bot {token}"

        prefix = os.getenv("KOOK_COMMAND_PREFIX", "/").strip() or "/"
        log_level = os.getenv("KOOK_LOG_LEVEL", "INFO").strip() or "INFO"
        return cls(
            token=token,
            command_prefix=prefix,
            locale=os.getenv("KOOK_LOCALE", "en-US").strip() or "en-US",
            locale_dir=os.getenv("KOOK_LOCALE_DIR", "locales").strip() or "locales",
            admin_command_channel_id=os.getenv("KOOK_ADMIN_COMMAND_CHANNEL_ID", "4760888878941680").strip(),
            log_channel_id=os.getenv("KOOK_LOG_CHANNEL_ID", "4760888878941680").strip(),
            super_admin_ids=_env_csv("KOOK_SUPER_ADMIN_IDS", "2744428583"),
            db_backend=(os.getenv("KOOK_DB_BACKEND", "sqlite").strip() or "sqlite").lower(),
            sqlite_path=os.getenv("KOOK_SQLITE_PATH", "data/kook-bot.db").strip() or "data/kook-bot.db",
            mysql_host=os.getenv("KOOK_MYSQL_HOST", "127.0.0.1").strip() or "127.0.0.1",
            mysql_port=_env_int("KOOK_MYSQL_PORT", 3306),
            mysql_user=os.getenv("KOOK_MYSQL_USER", "root").strip() or "root",
            mysql_password=os.getenv("KOOK_MYSQL_PASSWORD", ""),
            mysql_database=os.getenv("KOOK_MYSQL_DATABASE", "kook_bot").strip() or "kook_bot",
            log_level=log_level,
            log_http=_env_bool("KOOK_LOG_HTTP"),
            log_events=_env_bool("KOOK_LOG_EVENTS"),
            log_commands=_env_bool("KOOK_LOG_COMMANDS"),
            log_command_status=_env_bool("KOOK_LOG_COMMAND_STATUS"),
            log_imports=_env_bool("KOOK_LOG_IMPORTS"),
            import_web_enabled=_env_bool("KOOK_IMPORT_WEB_ENABLED"),
            import_web_host=os.getenv("KOOK_IMPORT_WEB_HOST", "127.0.0.1").strip() or "127.0.0.1",
            import_web_port=_env_int("KOOK_IMPORT_WEB_PORT", 18080),
            import_web_base_url=os.getenv("KOOK_IMPORT_WEB_BASE_URL", "http://127.0.0.1:18080").strip()
            or "http://127.0.0.1:18080",
            import_web_ttl_seconds=max(30, _env_int("KOOK_IMPORT_WEB_TTL_SECONDS", 600)),
            log_to_file=_env_bool("KOOK_LOG_TO_FILE", default=True),
            log_dir=os.getenv("KOOK_LOG_DIR", "logs").strip() or "logs",
            log_file=os.getenv("KOOK_LOG_FILE", "kook-bot.log").strip() or "kook-bot.log",
            log_max_bytes=max(1024, _env_int("KOOK_LOG_MAX_BYTES", 5 * 1024 * 1024)),
            log_backup_count=max(1, _env_int("KOOK_LOG_BACKUP_COUNT", 7)),
        )
