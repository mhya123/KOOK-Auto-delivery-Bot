from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from .database import Database
from .logging_utils import get_logger
from .permissions import PermissionService

logger = get_logger("kook_bot.store")


class StoreError(RuntimeError):
    def __init__(self, message_key: str, **message_params: object) -> None:
        self.message_key = message_key
        self.message_params = message_params
        super().__init__(message_key)


class NotFoundError(StoreError):
    pass


class InsufficientBalanceError(StoreError):
    pass


class OutOfStockError(StoreError):
    pass


@dataclass(slots=True)
class StoreService:
    """业务逻辑集中在这里，命令层只负责参数解析和回复。"""

    database: Database
    permissions: PermissionService

    def ensure_initialized(self) -> None:
        self.permissions.initialize()

    def get_profile(self, user_id: str) -> dict[str, int | str]:
        with self.database.transaction() as session:
            self._ensure_user(session, user_id)
            user = session.fetchone("SELECT user_id, balance, created_at, updated_at FROM users WHERE user_id = %s", (user_id,))
            if user is None:
                raise NotFoundError("error.user_not_found")
            return {
                "user_id": str(user["user_id"]),
                "balance": int(user["balance"]),
                "role": self.permissions.get_role(user_id),
                "created_at": int(user["created_at"]),
                "updated_at": int(user["updated_at"]),
            }

    def generate_cards(self, actor_user_id: str, amount: int, count: int) -> list[str]:
        if amount <= 0 or count <= 0:
            raise StoreError("error.amount_count_positive")

        created_at = int(time.time())
        cards: list[tuple[str, int, str, int]] = []
        for _ in range(count):
            cards.append((self._new_card_code(), amount, actor_user_id, created_at))

        with self.database.transaction() as session:
            session.executemany(
                """
                INSERT INTO recharge_cards (code, amount, created_by, created_at)
                VALUES (%s, %s, %s, %s)
                """,
                cards,
            )
        return [item[0] for item in cards]

    def export_unused_cards(self) -> list[dict[str, int | str]]:
        with self.database.transaction() as session:
            rows = session.fetchall(
                """
                SELECT code, amount, created_at
                FROM recharge_cards
                WHERE is_used = 0
                ORDER BY created_at ASC, code ASC
                """
            )
        return [{"code": str(row["code"]), "amount": int(row["amount"]), "created_at": int(row["created_at"])} for row in rows]

    def export_recharge_cards(self, *, include_used: bool = True) -> list[dict[str, int | str | None]]:
        with self.database.transaction() as session:
            sql = (
                """
                SELECT code, amount, is_used, used_by, used_at, created_by, created_at
                FROM recharge_cards
                """
            )
            params: tuple[object, ...] = ()
            if not include_used:
                sql += " WHERE is_used = %s"
                params = (0,)
            sql += " ORDER BY created_at ASC, code ASC"
            rows = session.fetchall(sql, params)
        return [
            {
                "code": str(row["code"]),
                "amount": int(row["amount"]),
                "is_used": int(row["is_used"] or 0),
                "used_by": str(row["used_by"]) if row.get("used_by") is not None else "",
                "used_at": int(row["used_at"]) if row.get("used_at") is not None else 0,
                "created_by": str(row["created_by"]) if row.get("created_by") is not None else "",
                "created_at": int(row["created_at"]),
            }
            for row in rows
        ]

    def delete_card(self, card_code: str) -> bool:
        with self.database.transaction() as session:
            row = session.fetchone(
                "SELECT code, is_used FROM recharge_cards WHERE code = %s",
                (card_code,),
            )
            if row is None:
                return False
            session.execute("DELETE FROM recharge_cards WHERE code = %s", (card_code,))
            return True

    def recharge(self, user_id: str, card_code: str) -> dict[str, int]:
        now = int(time.time())
        with self.database.transaction() as session:
            self._ensure_user(session, user_id)
            card = session.fetchone(
                """
                SELECT code, amount, is_used
                FROM recharge_cards
                WHERE code = %s
                """,
                (card_code,),
            )
            if card is None:
                raise NotFoundError("error.card_not_found")
            if int(card["is_used"]) == 1:
                raise StoreError("error.card_used")

            user = session.fetchone("SELECT balance FROM users WHERE user_id = %s", (user_id,))
            if user is None:
                raise NotFoundError("error.user_not_found")

            amount = int(card["amount"])
            balance_after = int(user["balance"]) + amount
            session.execute(
                "UPDATE users SET balance = %s, updated_at = %s WHERE user_id = %s",
                (balance_after, now, user_id),
            )
            session.execute(
                """
                UPDATE recharge_cards
                SET is_used = 1, used_by = %s, used_at = %s
                WHERE code = %s
                """,
                (user_id, now, card_code),
            )
            self._insert_transaction(session, user_id, "recharge", amount, balance_after, card_code, now)
            return {"amount": amount, "balance_after": balance_after}

    def add_product(self, actor_user_id: str, name: str, description: str) -> dict[str, int | str]:
        now = int(time.time())
        with self.database.transaction() as session:
            existing = session.fetchone(
                "SELECT id FROM products WHERE LOWER(name) = LOWER(%s)",
                (name,),
            )
            if existing is not None:
                raise StoreError("error.product_exists")
            session.execute(
                """
                INSERT INTO products (name, description, created_by, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (name, description, actor_user_id, now, now),
            )
            product_id = session.lastrowid
        return {"id": product_id, "name": name, "description": description}

    def add_key(self, actor_user_id: str, product_id: str, price: int, key_content: str) -> dict[str, int | str]:
        if price <= 0:
            raise StoreError("error.price_positive")

        now = int(time.time())
        with self.database.transaction() as session:
            product = self._find_product(session, product_id)
            if product is None:
                raise NotFoundError("error.product_not_found")
            session.execute(
                """
                INSERT INTO product_keys (product_id, key_content, price, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (int(product["id"]), key_content, price, actor_user_id, now),
            )
            session.execute(
                "UPDATE products SET updated_at = %s WHERE id = %s",
                (now, int(product["id"])),
            )
            key_id = session.lastrowid
        return {"key_id": key_id, "product_id": int(product["id"]), "price": price}

    def add_keys(
        self,
        actor_user_id: str,
        product_id: str,
        price: int,
        key_contents: list[str],
    ) -> dict[str, int]:
        if price <= 0:
            raise StoreError("error.price_positive")

        normalized_keys = [item.strip() for item in key_contents if item.strip()]
        if not normalized_keys:
            raise StoreError("error.no_valid_keys")

        now = int(time.time())
        with self.database.transaction() as session:
            product = self._find_product(session, product_id)
            if product is None:
                raise NotFoundError("error.product_not_found")

            rows = [
                (int(product["id"]), key_content, price, actor_user_id, now)
                for key_content in normalized_keys
            ]
            session.executemany(
                """
                INSERT INTO product_keys (product_id, key_content, price, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                rows,
            )
            session.execute(
                "UPDATE products SET updated_at = %s WHERE id = %s",
                (now, int(product["id"])),
            )
            return {"product_id": int(product["id"]), "count": len(normalized_keys), "price": price}

    def import_keys(
        self,
        actor_user_id: str,
        product_id: str,
        price: int,
        key_contents: list[str],
    ) -> dict[str, int]:
        if price <= 0:
            raise StoreError("error.price_positive")

        parsed_keys = [item.strip() for item in key_contents if item.strip()]
        if not parsed_keys:
            raise StoreError("error.no_valid_keys")

        unique_keys: list[str] = []
        seen_keys: set[str] = set()
        for key_content in parsed_keys:
            if key_content in seen_keys:
                continue
            seen_keys.add(key_content)
            unique_keys.append(key_content)

        duplicates_in_file = len(parsed_keys) - len(unique_keys)
        now = int(time.time())
        with self.database.transaction() as session:
            product = self._find_product(session, product_id)
            if product is None:
                raise NotFoundError("error.product_not_found")

            existing_keys = self._get_existing_product_keys(session, unique_keys)
            new_keys = [key_content for key_content in unique_keys if key_content not in existing_keys]

            if new_keys:
                rows = [
                    (int(product["id"]), key_content, price, actor_user_id, now)
                    for key_content in new_keys
                ]
                session.executemany(
                    """
                    INSERT INTO product_keys (product_id, key_content, price, created_by, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    rows,
                )
                session.execute(
                    "UPDATE products SET updated_at = %s WHERE id = %s",
                    (now, int(product["id"])),
                )

            skipped_duplicates = duplicates_in_file + len(existing_keys)
            return {
                "product_id": int(product["id"]),
                "parsed_total": len(parsed_keys),
                "inserted_count": len(new_keys),
                "skipped_duplicates": skipped_duplicates,
            }

    def list_products(self) -> list[dict[str, int | str]]:
        with self.database.transaction() as session:
            rows = session.fetchall(
                """
                SELECT
                    p.id,
                    p.name,
                    p.description,
                    COALESCE(MIN(CASE WHEN pk.is_sold = 0 THEN pk.price END), 0) AS price,
                    COALESCE(SUM(CASE WHEN pk.is_sold = 0 THEN 1 ELSE 0 END), 0) AS stock
                FROM products p
                LEFT JOIN product_keys pk ON pk.product_id = p.id
                GROUP BY p.id, p.name, p.description
                ORDER BY p.id ASC
                """
            )
        return [
            {
                "id": int(row["id"]),
                "name": str(row["name"]),
                "description": str(row["description"]),
                "price": int(row["price"] or 0),
                "stock": int(row["stock"] or 0),
            }
            for row in rows
        ]

    def export_product_keys(self, product_id: str) -> dict[str, list[dict[str, int | str | None]]]:
        with self.database.transaction() as session:
            if product_id.strip().lower() == "all":
                rows = session.fetchall(
                    """
                    SELECT
                        p.id AS product_id,
                        p.name AS product_name,
                        pk.id AS key_id,
                        pk.key_content,
                        pk.price,
                        pk.is_sold,
                        pk.sold_to,
                        pk.sold_at,
                        pk.created_by,
                        pk.created_at
                    FROM product_keys pk
                    INNER JOIN products p ON p.id = pk.product_id
                    ORDER BY p.id ASC, pk.id ASC
                    """
                )
            else:
                product = self._find_product(session, product_id)
                if product is None:
                    raise NotFoundError("error.product_not_found")
                rows = session.fetchall(
                    """
                    SELECT
                        p.id AS product_id,
                        p.name AS product_name,
                        pk.id AS key_id,
                        pk.key_content,
                        pk.price,
                        pk.is_sold,
                        pk.sold_to,
                        pk.sold_at,
                        pk.created_by,
                        pk.created_at
                    FROM product_keys pk
                    INNER JOIN products p ON p.id = pk.product_id
                    WHERE p.id = %s
                    ORDER BY pk.id ASC
                    """,
                    (int(product["id"]),),
                )

        grouped: dict[str, list[dict[str, int | str | None]]] = {}
        for row in rows:
            product_name = str(row["product_name"])
            grouped.setdefault(product_name, []).append(
                {
                    "product_id": int(row["product_id"]),
                    "product_name": product_name,
                    "key_id": int(row["key_id"]),
                    "key_content": str(row["key_content"]),
                    "price": int(row["price"]),
                    "is_sold": int(row["is_sold"] or 0),
                    "sold_to": str(row["sold_to"]) if row.get("sold_to") is not None else "",
                    "sold_at": int(row["sold_at"]) if row.get("sold_at") is not None else 0,
                    "created_by": str(row["created_by"]) if row.get("created_by") is not None else "",
                    "created_at": int(row["created_at"]),
                }
            )
        return grouped

    def buy_product(self, user_id: str, product_id: str, *, quantity: int = 1) -> dict[str, int | str | list[str]]:
        if quantity <= 0:
            raise StoreError("error.quantity_positive")

        now = int(time.time())
        with self.database.transaction() as session:
            self._ensure_user(session, user_id)
            product = self._find_product(session, product_id)
            if product is None:
                raise NotFoundError("error.product_not_found")

            key_rows = session.fetchall(
                """
                SELECT id, key_content, price
                FROM product_keys
                WHERE product_id = %s AND is_sold = 0
                ORDER BY id ASC
                LIMIT %s
                """,
                (int(product["id"]), quantity),
            )
            available_count = len(key_rows)
            if available_count < quantity:
                raise OutOfStockError(
                    "error.out_of_stock_buy",
                    requested=quantity,
                    available=available_count,
                )

            user = session.fetchone("SELECT balance FROM users WHERE user_id = %s", (user_id,))
            if user is None:
                raise NotFoundError("error.user_not_found")

            balance = int(user["balance"])
            total_price = sum(int(row["price"]) for row in key_rows)
            if balance < total_price:
                raise InsufficientBalanceError(
                    "error.insufficient_balance_buy",
                    required=total_price,
                    current=balance,
                )

            balance_after = balance - total_price
            session.execute(
                "UPDATE users SET balance = %s, updated_at = %s WHERE user_id = %s",
                (balance_after, now, user_id),
            )
            key_ids = [int(row["id"]) for row in key_rows]
            placeholders = ", ".join(["%s"] * len(key_ids))
            session.execute(
                f"""
                UPDATE product_keys
                SET is_sold = 1, sold_to = %s, sold_at = %s
                WHERE id IN ({placeholders})
                """,
                (user_id, now, *key_ids),
            )
            self._insert_transaction(
                session,
                user_id,
                "purchase",
                -total_price,
                balance_after,
                f"product:{product['id']}:count:{quantity}",
                now,
            )
            return {
                "product_id": int(product["id"]),
                "product_name": str(product["name"]),
                "quantity": quantity,
                "total_price": total_price,
                "balance_after": balance_after,
                "key_contents": [str(row["key_content"]) for row in key_rows],
            }

    def _ensure_user(self, session, user_id: str) -> None:
        now = int(time.time())
        existing = session.fetchone("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
        if existing is None:
            session.execute(
                """
                INSERT INTO users (user_id, balance, created_at, updated_at)
                VALUES (%s, %s, %s, %s)
                """,
                (user_id, 0, now, now),
            )

    def _find_product(self, session, product_id: str) -> dict[str, int | str] | None:
        if not product_id.isdigit():
            return None
        return session.fetchone(
            "SELECT id, name, description FROM products WHERE id = %s",
            (int(product_id),),
        )

    def _get_existing_product_keys(self, session, key_contents: list[str]) -> set[str]:
        existing_keys: set[str] = set()
        chunk_size = 500
        for start in range(0, len(key_contents), chunk_size):
            chunk = key_contents[start : start + chunk_size]
            placeholders = ", ".join(["%s"] * len(chunk))
            rows = session.fetchall(
                f"SELECT key_content FROM product_keys WHERE key_content IN ({placeholders})",
                tuple(chunk),
            )
            existing_keys.update(str(row["key_content"]) for row in rows)
        return existing_keys

    def _insert_transaction(
        self,
        session,
        user_id: str,
        kind: str,
        amount: int,
        balance_after: int,
        reference: str,
        created_at: int,
    ) -> None:
        session.execute(
            """
            INSERT INTO transactions (user_id, kind, amount, balance_after, reference, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (user_id, kind, amount, balance_after, reference, created_at),
        )

    def _new_card_code(self) -> str:
        """充值卡使用大写随机串，避免用户输入时混淆。"""
        return f"RC-{secrets.token_hex(8).upper()}"
