from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any

from .config import Settings
from .logging_utils import get_logger

logger = get_logger("kook_bot.database")

SQLITE_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS user_roles (
        user_id TEXT PRIMARY KEY,
        role TEXT NOT NULL,
        updated_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        balance INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recharge_cards (
        code TEXT PRIMARY KEY,
        amount INTEGER NOT NULL,
        is_used INTEGER NOT NULL DEFAULT 0,
        used_by TEXT,
        used_at INTEGER,
        created_by TEXT,
        created_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL,
        created_by TEXT,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS product_keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        key_content TEXT NOT NULL,
        price INTEGER NOT NULL,
        is_sold INTEGER NOT NULL DEFAULT 0,
        sold_to TEXT,
        sold_at INTEGER,
        created_by TEXT,
        created_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        amount INTEGER NOT NULL,
        balance_after INTEGER NOT NULL,
        reference TEXT,
        created_at INTEGER NOT NULL
    )
    """,
)

MYSQL_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS user_roles (
        user_id VARCHAR(32) PRIMARY KEY,
        role VARCHAR(32) NOT NULL,
        updated_at BIGINT NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id VARCHAR(32) PRIMARY KEY,
        balance BIGINT NOT NULL DEFAULT 0,
        created_at BIGINT NOT NULL,
        updated_at BIGINT NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS recharge_cards (
        code VARCHAR(64) PRIMARY KEY,
        amount BIGINT NOT NULL,
        is_used TINYINT NOT NULL DEFAULT 0,
        used_by VARCHAR(32),
        used_at BIGINT,
        created_by VARCHAR(32),
        created_at BIGINT NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS products (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        name VARCHAR(128) NOT NULL UNIQUE,
        description TEXT NOT NULL,
        created_by VARCHAR(32),
        created_at BIGINT NOT NULL,
        updated_at BIGINT NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS product_keys (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        product_id BIGINT NOT NULL,
        key_content TEXT NOT NULL,
        price BIGINT NOT NULL,
        is_sold TINYINT NOT NULL DEFAULT 0,
        sold_to VARCHAR(32),
        sold_at BIGINT,
        created_by VARCHAR(32),
        created_at BIGINT NOT NULL,
        INDEX idx_product_keys_product_id (product_id),
        INDEX idx_product_keys_is_sold (is_sold)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS transactions (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        user_id VARCHAR(32) NOT NULL,
        kind VARCHAR(32) NOT NULL,
        amount BIGINT NOT NULL,
        balance_after BIGINT NOT NULL,
        reference VARCHAR(128),
        created_at BIGINT NOT NULL,
        INDEX idx_transactions_user_id (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
)


class DatabaseError(RuntimeError):
    pass


class DatabaseSession:
    # 统一封装 sqlite/mysql 两种游标接口，业务层只使用这一层。
    def __init__(self, database: "Database", connection: Any, cursor: Any) -> None:
        self._database = database
        self._connection = connection
        self._cursor = cursor

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        self._cursor.execute(self._database.adapt_sql(sql), params)
        return self._cursor

    def executemany(self, sql: str, seq_params: list[tuple[Any, ...]]) -> Any:
        self._cursor.executemany(self._database.adapt_sql(sql), seq_params)
        return self._cursor

    def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        cursor = self.execute(sql, params)
        row = cursor.fetchone()
        return self._database.normalize_row(row)

    def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        cursor = self.execute(sql, params)
        rows = cursor.fetchall()
        return [self._database.normalize_row(row) for row in rows]

    @property
    def lastrowid(self) -> int:
        return int(getattr(self._cursor, "lastrowid", 0) or 0)


class Database:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._backend = settings.db_backend.lower()
        self._lock = RLock()
        self._sqlite_connection: sqlite3.Connection | None = None
        self._mysql_connection: Any | None = None

    def initialize(self) -> None:
        if self._backend == "mysql":
            self._ensure_mysql_database()
        with self.transaction() as session:
            statements = MYSQL_SCHEMA_STATEMENTS if self._backend == "mysql" else SQLITE_SCHEMA_STATEMENTS
            for statement in statements:
                session.execute(statement)
        logger.info("database initialized backend=%s", self._backend)

    def get_user_role(self, user_id: str) -> str | None:
        with self.transaction() as session:
            row = session.fetchone(
                "SELECT role FROM user_roles WHERE user_id = %s",
                (user_id,),
            )
            if row is None:
                return None
            return str(row["role"])

    def upsert_user_role(self, user_id: str, role: str, *, updated_at: int | None = None) -> None:
        if updated_at is None:
            import time

            updated_at = int(time.time())

        with self.transaction() as session:
            existing = session.fetchone(
                "SELECT user_id FROM user_roles WHERE user_id = %s",
                (user_id,),
            )
            if existing is None:
                session.execute(
                    """
                    INSERT INTO user_roles (user_id, role, updated_at)
                    VALUES (%s, %s, %s)
                    """,
                    (user_id, role, updated_at),
                )
                return

            session.execute(
                """
                UPDATE user_roles
                SET role = %s, updated_at = %s
                WHERE user_id = %s
                """,
                (role, updated_at, user_id),
            )

    @contextmanager
    def transaction(self) -> Iterator[DatabaseSession]:
        with self._lock:
            connection = self._get_connection()
            cursor = self._create_cursor(connection)
            session = DatabaseSession(self, connection, cursor)
            try:
                if self._backend == "mysql":
                    connection.begin()
                yield session
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()

    def adapt_sql(self, sql: str) -> str:
        if self._backend == "sqlite":
            return sql.replace("%s", "?")
        return sql

    def normalize_row(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        if isinstance(row, sqlite3.Row):
            return {key: row[key] for key in row.keys()}
        if isinstance(row, dict):
            return row
        raise DatabaseError(f"Unsupported database row type: {type(row)!r}")

    def _get_connection(self) -> Any:
        if self._backend == "sqlite":
            return self._get_sqlite_connection()
        if self._backend == "mysql":
            return self._get_mysql_connection()
        raise DatabaseError(f"Unsupported database backend: {self._backend}")

    def _create_cursor(self, connection: Any) -> Any:
        return connection.cursor()

    def _get_sqlite_connection(self) -> sqlite3.Connection:
        if self._sqlite_connection is None:
            project_root = Path(__file__).resolve().parents[2]
            sqlite_path = project_root / self._settings.sqlite_path
            sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(sqlite_path, check_same_thread=False)
            connection.row_factory = sqlite3.Row
            self._sqlite_connection = connection
        return self._sqlite_connection

    def _ensure_mysql_database(self) -> None:
        try:
            import pymysql
        except ImportError as exc:
            raise DatabaseError("MySQL backend requires PyMySQL. Install requirements first.") from exc

        bootstrap = pymysql.connect(
            host=self._settings.mysql_host,
            port=self._settings.mysql_port,
            user=self._settings.mysql_user,
            password=self._settings.mysql_password,
            charset="utf8mb4",
            autocommit=True,
        )
        try:
            cursor = bootstrap.cursor()
            try:
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{self._settings.mysql_database}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            finally:
                cursor.close()
        finally:
            bootstrap.close()

    def _get_mysql_connection(self) -> Any:
        try:
            import pymysql
            from pymysql.cursors import DictCursor
        except ImportError as exc:
            raise DatabaseError("MySQL backend requires PyMySQL. Install requirements first.") from exc

        if self._mysql_connection is None:
            self._mysql_connection = pymysql.connect(
                host=self._settings.mysql_host,
                port=self._settings.mysql_port,
                user=self._settings.mysql_user,
                password=self._settings.mysql_password,
                database=self._settings.mysql_database,
                charset="utf8mb4",
                autocommit=False,
                cursorclass=DictCursor,
            )
        else:
            self._mysql_connection.ping(reconnect=True)
        return self._mysql_connection
