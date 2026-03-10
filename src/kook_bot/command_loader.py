from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from .commands import CommandRegistry
from .logging_utils import get_logger

logger = get_logger("kook_bot.command_loader")


class CommandLoader:
    """负责扫描并热重载命令模块。"""

    def __init__(self, bot: "KookBot") -> None:
        self._bot = bot
        self._module_mtimes: dict[str, float] = {}
        self._module_names: tuple[str, ...] = ()
        self._commands_path = Path(__file__).resolve().parent / "command_modules"

    def load(self, *, force: bool = False) -> bool:
        current_state = self._scan_modules()
        current_names = tuple(sorted(current_state))
        if not force and current_state == self._module_mtimes and current_names == self._module_names:
            return False

        old_registry = self._bot.commands
        new_registry = CommandRegistry()
        self._bot.commands = new_registry
        importlib.invalidate_caches()

        try:
            for module_name in current_names:
                import_name = f"kook_bot.command_modules.{module_name}"
                if import_name in sys.modules:
                    module = importlib.reload(sys.modules[import_name])
                else:
                    module = importlib.import_module(import_name)

                register = getattr(module, "register", None)
                if callable(register):
                    register(self._bot)
        except Exception:
            self._bot.commands = old_registry
            logger.exception("failed to reload command modules")
            return False

        self._module_mtimes = current_state
        self._module_names = current_names
        logger.info("command modules loaded names=%s", current_names)
        return True

    def _scan_modules(self) -> dict[str, float]:
        modules: dict[str, float] = {}
        for path in self._commands_path.glob("*.py"):
            if path.name.startswith("_") or path.name == "__init__.py":
                continue
            modules[path.stem] = path.stat().st_mtime
        return modules


if TYPE_CHECKING:
    from .bot import KookBot
