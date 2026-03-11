from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_dotenv_path() -> Path:
    return get_project_root() / ".env"


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


def _env_int_map(name: str, default: dict[str, int] | None = None) -> dict[str, int]:
    raw = os.getenv(name, "").strip()
    mapping = dict(default or {})
    if not raw:
        return mapping

    for item in raw.split(","):
        pair = item.strip()
        if not pair or ":" not in pair:
            continue
        key, value = pair.split(":", 1)
        normalized_key = key.strip().lower()
        if not normalized_key:
            continue
        try:
            mapping[normalized_key] = max(0, int(value.strip()))
        except ValueError:
            continue
    return mapping


def _load_dotenv() -> None:
    dotenv_path = get_dotenv_path()
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


def set_dotenv_value(key: str, value: str) -> None:
    dotenv_path = get_dotenv_path()
    if dotenv_path.exists():
        lines = dotenv_path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    replaced = False
    updated_lines: list[str] = []
    for raw_line in lines:
        stripped = raw_line.lstrip()
        if stripped.startswith(f"{key}="):
            indent = raw_line[: len(raw_line) - len(stripped)]
            updated_lines.append(f"{indent}{key}={value}")
            replaced = True
            continue
        updated_lines.append(raw_line)

    if not replaced:
        if updated_lines and updated_lines[-1].strip():
            updated_lines.append("")
        updated_lines.append(f"{key}={value}")

    payload = "\n".join(updated_lines)
    if payload:
        payload += "\n"
    dotenv_path.write_text(payload, encoding="utf-8")


@dataclass(slots=True)
class Settings:
    token: str
    command_prefix: str = "/"
    recharge_card_format: str = "RC-{random}"
    recharge_card_random_length: int = 16
    recharge_card_alphabet: str = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    payment_enabled: bool = False
    payment_api_base_url: str = "https://pay.XXXX.cn"
    payment_pid: str = ""
    payment_key: str = ""
    payment_sitename: str = "KOOK Auto-delivery Bot"
    payment_base_url: str = ""
    payment_notify_path: str = "/payment/notify"
    payment_return_path: str = "/payment/return"
    payment_allow_custom_amount: bool = False
    payment_custom_amount_min: int = 1
    payment_custom_amount_max: int = 100000
    locale: str = "en-US"
    locale_dir: str = "locales"
    admin_command_channel_id: str = "4760888878941680"
    log_channel_id: str = "4760888878941680"
    api_base_url: str = "https://www.kookapp.cn/api/v3"
    gateway_compress: int = 0
    gateway_ping_interval_seconds: int = 30
    gateway_ping_jitter_seconds: int = 5
    gateway_pong_timeout_seconds: int = 12
    gateway_max_missed_pongs: int = 2
    super_admin_ids: tuple[str, ...] = ("2744428583",)
    runtime_config_admin_ids: tuple[str, ...] = ("2744428583",)
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
    user_command_cooldown_enabled: bool = True
    user_command_cooldown_seconds: int = 3
    user_command_cooldown_overrides: dict[str, int] = field(
        default_factory=lambda: {
            "help": 2,
            "pay_amounts": 2,
            "products": 2,
            "buy": 5,
            "recharge": 5,
            "pay": 8,
        }
    )
    import_web_enabled: bool = False
    import_web_host: str = "127.0.0.1"
    import_web_port: int = 18080
    import_web_base_url: str = "http://127.0.0.1:18080"
    import_web_ttl_seconds: int = 600
    import_web_max_body_mb: int = 10
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
        super_admin_ids = _env_csv("KOOK_SUPER_ADMIN_IDS", "2744428583")
        runtime_config_admin_ids = _env_csv("KOOK_RUNTIME_CONFIG_ADMIN_IDS", ",".join(super_admin_ids))
        return cls(
            token=token,
            command_prefix=prefix,
            recharge_card_format=os.getenv("KOOK_RECHARGE_CARD_FORMAT", "RC-{random}").strip() or "RC-{random}",
            recharge_card_random_length=max(4, _env_int("KOOK_RECHARGE_CARD_RANDOM_LENGTH", 16)),
            recharge_card_alphabet=(
                os.getenv("KOOK_RECHARGE_CARD_ALPHABET", "ABCDEFGHJKLMNPQRSTUVWXYZ23456789").strip()
                or "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
            ),
            payment_enabled=_env_bool("KOOK_PAYMENT_ENABLED"),
            payment_api_base_url=os.getenv("KOOK_PAYMENT_API_BASE_URL", "https://pay.mxlg.cn").strip() or "https://pay.mxlg.cn",
            payment_pid=os.getenv("KOOK_PAYMENT_PID", "").strip(),
            payment_key=os.getenv("KOOK_PAYMENT_KEY", "").strip(),
            payment_sitename=os.getenv("KOOK_PAYMENT_SITENAME", "KOOK Auto-delivery Bot").strip() or "KOOK Auto-delivery Bot",
            payment_base_url=os.getenv("KOOK_PAYMENT_BASE_URL", "").strip(),
            payment_notify_path=os.getenv("KOOK_PAYMENT_NOTIFY_PATH", "/payment/notify").strip() or "/payment/notify",
            payment_return_path=os.getenv("KOOK_PAYMENT_RETURN_PATH", "/payment/return").strip() or "/payment/return",
            payment_allow_custom_amount=_env_bool("KOOK_PAYMENT_ALLOW_CUSTOM_AMOUNT"),
            payment_custom_amount_min=max(1, _env_int("KOOK_PAYMENT_CUSTOM_AMOUNT_MIN", 1)),
            payment_custom_amount_max=max(1, _env_int("KOOK_PAYMENT_CUSTOM_AMOUNT_MAX", 100000)),
            locale=os.getenv("KOOK_LOCALE", "en-US").strip() or "en-US",
            locale_dir=os.getenv("KOOK_LOCALE_DIR", "locales").strip() or "locales",
            admin_command_channel_id=os.getenv("KOOK_ADMIN_COMMAND_CHANNEL_ID", "4760888878941680").strip(),
            log_channel_id=os.getenv("KOOK_LOG_CHANNEL_ID", "4760888878941680").strip(),
            gateway_ping_interval_seconds=max(10, _env_int("KOOK_GATEWAY_PING_INTERVAL_SECONDS", 30)),
            gateway_ping_jitter_seconds=max(0, _env_int("KOOK_GATEWAY_PING_JITTER_SECONDS", 5)),
            gateway_pong_timeout_seconds=max(3, _env_int("KOOK_GATEWAY_PONG_TIMEOUT_SECONDS", 12)),
            gateway_max_missed_pongs=max(1, _env_int("KOOK_GATEWAY_MAX_MISSED_PONGS", 2)),
            super_admin_ids=super_admin_ids,
            runtime_config_admin_ids=runtime_config_admin_ids or super_admin_ids,
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
            user_command_cooldown_enabled=_env_bool("KOOK_USER_COMMAND_COOLDOWN_ENABLED", default=True),
            user_command_cooldown_seconds=max(0, _env_int("KOOK_USER_COMMAND_COOLDOWN_SECONDS", 3)),
            user_command_cooldown_overrides=_env_int_map(
                "KOOK_USER_COMMAND_COOLDOWN_OVERRIDES",
                {
                    "help": 2,
                    "pay_amounts": 2,
                    "products": 2,
                    "buy": 5,
                    "recharge": 5,
                    "pay": 8,
                },
            ),
            import_web_enabled=_env_bool("KOOK_IMPORT_WEB_ENABLED"),
            import_web_host=os.getenv("KOOK_IMPORT_WEB_HOST", "127.0.0.1").strip() or "127.0.0.1",
            import_web_port=_env_int("KOOK_IMPORT_WEB_PORT", 18080),
            import_web_base_url=os.getenv("KOOK_IMPORT_WEB_BASE_URL", "http://127.0.0.1:18080").strip()
            or "http://127.0.0.1:18080",
            import_web_ttl_seconds=max(30, _env_int("KOOK_IMPORT_WEB_TTL_SECONDS", 600)),
            import_web_max_body_mb=max(1, _env_int("KOOK_IMPORT_WEB_MAX_BODY_MB", 10)),
            log_to_file=_env_bool("KOOK_LOG_TO_FILE", default=True),
            log_dir=os.getenv("KOOK_LOG_DIR", "logs").strip() or "logs",
            log_file=os.getenv("KOOK_LOG_FILE", "kook-bot.log").strip() or "kook-bot.log",
            log_max_bytes=max(1024, _env_int("KOOK_LOG_MAX_BYTES", 5 * 1024 * 1024)),
            log_backup_count=max(1, _env_int("KOOK_LOG_BACKUP_COUNT", 7)),
        )
