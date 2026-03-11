from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from json import dumps as json_dumps, loads as json_loads

from .config import Settings
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
    settings: Settings

    def ensure_initialized(self) -> None:
        self.permissions.initialize()

    def get_profile(self, user_id: str) -> dict[str, int | str]:
        role = self.permissions.get_role(user_id)
        with self.database.transaction() as session:
            self._ensure_user(session, user_id)
            user = session.fetchone("SELECT user_id, balance, created_at, updated_at FROM users WHERE user_id = %s", (user_id,))
            if user is None:
                raise NotFoundError("error.user_not_found")
            return {
                "user_id": str(user["user_id"]),
                "balance": int(user["balance"]),
                "role": role,
                "created_at": int(user["created_at"]),
                "updated_at": int(user["updated_at"]),
            }

    def generate_cards(self, actor_user_id: str, amount: int, count: int) -> list[str]:
        if amount <= 0 or count <= 0:
            raise StoreError("error.amount_count_positive")

        created_at = int(time.time())
        cards: list[tuple[str, int, str, int]] = []
        generated_codes: set[str] = set()
        while len(cards) < count:
            card_code = self._new_card_code()
            if card_code in generated_codes:
                continue
            generated_codes.add(card_code)
            cards.append((card_code, amount, actor_user_id, created_at))

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

    def list_payment_amounts(self) -> list[int]:
        with self.database.transaction() as session:
            rows = session.fetchall(
                """
                SELECT amount
                FROM payment_amount_options
                ORDER BY amount ASC
                """
            )
        return [int(row["amount"]) for row in rows]

    def is_payment_amount_allowed(self, amount: int, allowed_amounts: list[int] | None = None) -> bool:
        if amount <= 0:
            return False

        normalized_amounts = allowed_amounts if allowed_amounts is not None else self.list_payment_amounts()
        if normalized_amounts and amount in normalized_amounts:
            return True

        if not self.settings.payment_allow_custom_amount:
            return False

        minimum = min(self.settings.payment_custom_amount_min, self.settings.payment_custom_amount_max)
        maximum = max(self.settings.payment_custom_amount_min, self.settings.payment_custom_amount_max)
        return minimum <= amount <= maximum

    def replace_payment_amounts(self, actor_user_id: str, amounts: list[int]) -> list[int]:
        normalized = sorted({int(amount) for amount in amounts if int(amount) > 0})
        if not normalized:
            raise StoreError("error.payment_amounts_empty")

        now = int(time.time())
        with self.database.transaction() as session:
            session.execute("DELETE FROM payment_amount_options")
            session.executemany(
                """
                INSERT INTO payment_amount_options (amount, created_by, created_at, updated_at)
                VALUES (%s, %s, %s, %s)
                """,
                [(amount, actor_user_id, now, now) for amount in normalized],
            )
        return normalized

    def create_payment_order(
        self,
        user_id: str,
        *,
        amount: int,
        pay_type: str,
        order_no: str,
        create_payload: dict[str, object],
    ) -> None:
        now = int(time.time())
        with self.database.transaction() as session:
            self._ensure_user(session, user_id)
            allowed_amounts = self._list_payment_amounts_in_session(session)
            if not self.is_payment_amount_allowed(amount, allowed_amounts):
                raise StoreError("error.payment_amount_not_allowed")
            session.execute(
                """
                INSERT INTO payment_orders (
                    order_no, user_id, amount, pay_type, status, create_payload, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    order_no,
                    user_id,
                    amount,
                    pay_type,
                    "pending",
                    json_dumps(create_payload, ensure_ascii=False),
                    now,
                    now,
                ),
            )

    def get_payment_order(self, order_no: str) -> dict[str, int | str] | None:
        with self.database.transaction() as session:
            row = session.fetchone(
                """
                SELECT order_no, platform_trade_no, user_id, amount, pay_type, status, create_payload, created_at, paid_at
                FROM payment_orders
                WHERE order_no = %s
                """,
                (order_no,),
            )
        if row is None:
            return None
        return {
            "order_no": str(row["order_no"]),
            "platform_trade_no": str(row["platform_trade_no"] or ""),
            "user_id": str(row["user_id"]),
            "amount": int(row["amount"]),
            "pay_type": str(row["pay_type"]),
            "status": str(row["status"]),
            "create_payload": str(row.get("create_payload") or ""),
            "created_at": int(row["created_at"]),
            "paid_at": int(row["paid_at"] or 0),
        }

    def get_payment_submit_payload(self, order_no: str) -> dict[str, str] | None:
        order = self.get_payment_order(order_no)
        if order is None:
            return None
        raw_payload = str(order.get("create_payload") or "").strip()
        if not raw_payload:
            return None
        try:
            payload = json_loads(raw_payload)
        except ValueError:
            return None
        if not isinstance(payload, dict):
            return None
        return {str(key): str(value) for key, value in payload.items()}

    def complete_payment_order(
        self,
        *,
        order_no: str,
        trade_no: str,
        amount: int,
        pay_type: str,
        notify_payload: dict[str, object],
    ) -> dict[str, int | str] | None:
        now = int(time.time())
        with self.database.transaction() as session:
            order = session.fetchone(
                """
                SELECT order_no, user_id, amount, pay_type, status
                FROM payment_orders
                WHERE order_no = %s
                """,
                (order_no,),
            )
            if order is None:
                return None
            if str(order["status"]) == "paid":
                user = session.fetchone("SELECT balance FROM users WHERE user_id = %s", (str(order["user_id"]),))
                return {
                    "user_id": str(order["user_id"]),
                    "amount": int(order["amount"]),
                    "balance_after": int((user or {}).get("balance", 0)),
                    "order_no": str(order["order_no"]),
                    "trade_no": trade_no,
                    "already_paid": True,
                }

            expected_amount = int(order["amount"])
            if expected_amount != amount or str(order["pay_type"]) != pay_type:
                raise StoreError("error.payment_callback_mismatch")

            user = self._get_user_balance_row(session, str(order["user_id"]), lock_for_update=session.is_mysql)
            if user is None:
                raise NotFoundError("error.user_not_found")

            balance_after = int(user["balance"]) + amount
            session.execute(
                "UPDATE users SET balance = %s, updated_at = %s WHERE user_id = %s",
                (balance_after, now, str(order["user_id"])),
            )
            session.execute(
                """
                UPDATE payment_orders
                SET platform_trade_no = %s, status = %s, notify_payload = %s, paid_at = %s, updated_at = %s
                WHERE order_no = %s
                """,
                (
                    trade_no,
                    "paid",
                    json_dumps(notify_payload, ensure_ascii=False),
                    now,
                    now,
                    order_no,
                ),
            )
            self._insert_transaction(session, str(order["user_id"]), "payment_recharge", amount, balance_after, order_no, now)
            return {
                "user_id": str(order["user_id"]),
                "amount": amount,
                "balance_after": balance_after,
                "order_no": str(order["order_no"]),
                "trade_no": trade_no,
                "already_paid": False,
            }

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
            stock_before = self._count_available_product_keys(session, int(product["id"]))
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
            restock_user_ids = self._pop_product_subscriptions(session, int(product["id"])) if stock_before == 0 else []
        return {
            "key_id": key_id,
            "product_id": int(product["id"]),
            "product_name": str(product["name"]),
            "price": price,
            "restock_user_ids": restock_user_ids,
        }

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
            stock_before = self._count_available_product_keys(session, int(product["id"]))

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
            restock_user_ids = self._pop_product_subscriptions(session, int(product["id"])) if stock_before == 0 else []
            return {
                "product_id": int(product["id"]),
                "product_name": str(product["name"]),
                "count": len(normalized_keys),
                "price": price,
                "restock_user_ids": restock_user_ids,
            }

    def import_keys(
        self,
        actor_user_id: str,
        product_id: str,
        price: int,
        key_contents: list[str],
    ) -> dict[str, int | str | list[str]]:
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
                restock_user_ids = self._pop_product_subscriptions(session, int(product["id"]))
            else:
                restock_user_ids = []

            skipped_duplicates = duplicates_in_file + len(existing_keys)
            return {
                "product_id": int(product["id"]),
                "product_name": str(product["name"]),
                "parsed_total": len(parsed_keys),
                "inserted_count": len(new_keys),
                "skipped_duplicates": skipped_duplicates,
                "restock_user_ids": restock_user_ids,
            }

    def list_products(self) -> list[dict[str, int | str]]:
        with self.database.transaction() as session:
            rows = session.fetchall(
                """
                SELECT
                    p.id,
                    p.name,
                    p.description,
                    COALESCE(MIN(CASE WHEN pk.is_sold = 0 AND COALESCE(pk.is_void, 0) = 0 THEN pk.price END), 0) AS price,
                    COALESCE(SUM(CASE WHEN pk.is_sold = 0 AND COALESCE(pk.is_void, 0) = 0 THEN 1 ELSE 0 END), 0) AS stock
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

    def subscribe_product(self, user_id: str, product_id: str) -> dict[str, int | str]:
        now = int(time.time())
        with self.database.transaction() as session:
            self._ensure_user(session, user_id)
            product = self._find_product(session, product_id)
            if product is None:
                raise NotFoundError("error.product_not_found")

            stock = self._count_available_product_keys(session, int(product["id"]))
            if stock > 0:
                raise StoreError("error.product_in_stock", stock=stock)

            existing = session.fetchone(
                """
                SELECT id
                FROM product_subscriptions
                WHERE user_id = %s AND product_id = %s
                """,
                (user_id, int(product["id"])),
            )
            if existing is not None:
                raise StoreError("error.product_already_subscribed")

            session.execute(
                """
                INSERT INTO product_subscriptions (user_id, product_id, created_at)
                VALUES (%s, %s, %s)
                """,
                (user_id, int(product["id"]), now),
            )
            return {
                "product_id": int(product["id"]),
                "product_name": str(product["name"]),
            }

    def unsubscribe_product(self, user_id: str, product_id: str) -> dict[str, int | str]:
        with self.database.transaction() as session:
            self._ensure_user(session, user_id)
            product = self._find_product(session, product_id)
            if product is None:
                raise NotFoundError("error.product_not_found")

            existing = session.fetchone(
                """
                SELECT id
                FROM product_subscriptions
                WHERE user_id = %s AND product_id = %s
                """,
                (user_id, int(product["id"])),
            )
            if existing is None:
                raise StoreError("error.product_not_subscribed")

            session.execute(
                """
                DELETE FROM product_subscriptions
                WHERE user_id = %s AND product_id = %s
                """,
                (user_id, int(product["id"])),
            )
            return {
                "product_id": int(product["id"]),
                "product_name": str(product["name"]),
            }

    def buy_product(self, user_id: str, product_id: str, *, quantity: int = 1) -> dict[str, int | str | list[str]]:
        if quantity <= 0:
            raise StoreError("error.quantity_positive")

        now = int(time.time())
        with self.database.transaction() as session:
            self._ensure_user(session, user_id)
            product = self._find_product(session, product_id, lock_for_update=session.is_mysql)
            if product is None:
                raise NotFoundError("error.product_not_found")

            key_rows = self._select_available_keys(
                session,
                int(product["id"]),
                quantity,
                lock_for_update=session.is_mysql,
            )
            available_count = len(key_rows)
            if available_count < quantity:
                raise OutOfStockError(
                    "error.out_of_stock_buy",
                    requested=quantity,
                    available=available_count,
                )

            user = self._get_user_balance_row(session, user_id, lock_for_update=session.is_mysql)
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

    def refund_product_key(self, actor_user_id: str, user_id: str, key_content: str) -> dict[str, int | str]:
        now = int(time.time())
        with self.database.transaction() as session:
            self._ensure_user(session, user_id)
            user = self._get_user_balance_row(session, user_id, lock_for_update=session.is_mysql)
            if user is None:
                raise NotFoundError("error.user_not_found")

            refund_row = self._find_sold_key(
                session,
                user_id,
                key_content,
                lock_for_update=session.is_mysql,
            )
            if refund_row is None:
                raise NotFoundError("error.refund_target_not_found")
            if int(refund_row["is_void"] or 0) == 1:
                raise StoreError("error.refund_already_processed")

            refund_amount = int(refund_row["price"])
            balance_after = int(user["balance"]) + refund_amount
            session.execute(
                "UPDATE users SET balance = %s, updated_at = %s WHERE user_id = %s",
                (balance_after, now, user_id),
            )
            session.execute(
                """
                UPDATE product_keys
                SET is_void = 1, void_reason = %s, refunded_at = %s, refunded_by = %s
                WHERE id = %s
                """,
                ("refunded", now, actor_user_id, int(refund_row["id"])),
            )
            self._insert_transaction(
                session,
                user_id,
                "refund",
                refund_amount,
                balance_after,
                f"refund:key:{refund_row['id']}",
                now,
            )
            return {
                "user_id": user_id,
                "product_id": int(refund_row["product_id"]),
                "product_name": str(refund_row["product_name"]),
                "refund_amount": refund_amount,
                "balance_after": balance_after,
                "key_content": str(refund_row["key_content"]),
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

    def _find_product(self, session, product_id: str, *, lock_for_update: bool = False) -> dict[str, int | str] | None:
        if not product_id.isdigit():
            return None
        sql = "SELECT id, name, description FROM products WHERE id = %s"
        if lock_for_update and session.is_mysql:
            sql += " FOR UPDATE"
        return session.fetchone(sql, (int(product_id),))

    def _get_user_balance_row(self, session, user_id: str, *, lock_for_update: bool = False) -> dict[str, int] | None:
        sql = "SELECT balance FROM users WHERE user_id = %s"
        if lock_for_update and session.is_mysql:
            sql += " FOR UPDATE"
        return session.fetchone(sql, (user_id,))

    def _count_available_product_keys(self, session, product_id: int) -> int:
        row = session.fetchone(
            """
            SELECT COUNT(*) AS stock
            FROM product_keys
            WHERE product_id = %s AND is_sold = 0 AND COALESCE(is_void, 0) = 0
            """,
            (product_id,),
        )
        if row is None:
            return 0
        return int(row["stock"] or 0)

    def _select_available_keys(self, session, product_id: int, quantity: int, *, lock_for_update: bool) -> list[dict[str, int | str]]:
        sql = """
            SELECT id, key_content, price
            FROM product_keys
            WHERE product_id = %s AND is_sold = 0 AND COALESCE(is_void, 0) = 0
            ORDER BY id ASC
            LIMIT %s
        """
        if lock_for_update and session.is_mysql:
            sql += " FOR UPDATE"
        return session.fetchall(sql, (product_id, quantity))

    def _find_sold_key(self, session, user_id: str, key_content: str, *, lock_for_update: bool) -> dict[str, int | str] | None:
        sql = """
            SELECT
                pk.id,
                pk.product_id,
                pk.key_content,
                pk.price,
                pk.is_void,
                p.name AS product_name
            FROM product_keys pk
            INNER JOIN products p ON p.id = pk.product_id
            WHERE pk.sold_to = %s AND pk.key_content = %s AND pk.is_sold = 1
        """
        if lock_for_update and session.is_mysql:
            sql += " FOR UPDATE"
        return session.fetchone(sql, (user_id, key_content))

    def _pop_product_subscriptions(self, session, product_id: int) -> list[str]:
        rows = session.fetchall(
            """
            SELECT user_id
            FROM product_subscriptions
            WHERE product_id = %s
            ORDER BY id ASC
            """,
            (product_id,),
        )
        if not rows:
            return []
        session.execute(
            "DELETE FROM product_subscriptions WHERE product_id = %s",
            (product_id,),
        )
        return [str(row["user_id"]) for row in rows]

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

    def _list_payment_amounts_in_session(self, session) -> list[int]:
        rows = session.fetchall(
            """
            SELECT amount
            FROM payment_amount_options
            ORDER BY amount ASC
            """
        )
        return [int(row["amount"]) for row in rows]

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

    def _new_card_code(self) -> str:
        # 充值卡格式支持环境变量模板，默认仍然生成大写随机串。
        alphabet = self.settings.recharge_card_alphabet or "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        random_part = "".join(secrets.choice(alphabet) for _ in range(self.settings.recharge_card_random_length))
        template = self.settings.recharge_card_format or "RC-{random}"
        try:
            return template.format(
                random=random_part,
                timestamp=int(time.time()),
            )
        except Exception:
            logger.warning("invalid recharge card format template=%r, fallback to default", template)
            return f"RC-{random_part}"

    def _new_card_code(self) -> str:
        alphabet = self.settings.recharge_card_alphabet or "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        random_part = "".join(secrets.choice(alphabet) for _ in range(self.settings.recharge_card_random_length))
        template = self.settings.recharge_card_format or "RC-{random}"
        try:
            return template.format(
                random=random_part,
                timestamp=int(time.time()),
            )
        except Exception:
            logger.warning("invalid recharge card format template=%r, fallback to default", template)
            return f"RC-{random_part}"
