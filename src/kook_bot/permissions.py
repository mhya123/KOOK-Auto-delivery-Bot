from __future__ import annotations

from dataclasses import dataclass

from .database import Database
from .logging_utils import get_logger

logger = get_logger("kook_bot.permissions")


class Role:
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    USER = "user"


ROLE_PRIORITY = {
    Role.USER: 10,
    Role.ADMIN: 20,
    Role.SUPER_ADMIN: 30,
}


def role_allows(current_role: str, required_role: str) -> bool:
    return ROLE_PRIORITY.get(current_role, 0) >= ROLE_PRIORITY.get(required_role, 0)


class PermissionDenied(RuntimeError):
    pass


@dataclass(slots=True)
class PermissionService:
    database: Database
    super_admin_ids: tuple[str, ...]

    def initialize(self) -> None:
        self.database.initialize()
        for user_id in self.super_admin_ids:
            self.database.upsert_user_role(user_id, Role.SUPER_ADMIN)
        logger.info("permission service initialized super_admin_ids=%s", self.super_admin_ids)

    def get_role(self, user_id: str) -> str:
        if user_id in self.super_admin_ids:
            return Role.SUPER_ADMIN

        stored_role = self.database.get_user_role(user_id)
        if stored_role in {Role.SUPER_ADMIN, Role.ADMIN, Role.USER}:
            return stored_role
        return Role.USER

    def is_super_admin(self, user_id: str) -> bool:
        return self.get_role(user_id) == Role.SUPER_ADMIN

    def is_admin(self, user_id: str) -> bool:
        return role_allows(self.get_role(user_id), Role.ADMIN)

    def add_admin(self, actor_user_id: str, target_user_id: str) -> None:
        if not self.is_super_admin(actor_user_id):
            raise PermissionDenied("Only super administrators can add administrators.")

        if target_user_id in self.super_admin_ids:
            return

        self.database.upsert_user_role(target_user_id, Role.ADMIN)
        logger.info("admin granted actor=%s target=%s", actor_user_id, target_user_id)
