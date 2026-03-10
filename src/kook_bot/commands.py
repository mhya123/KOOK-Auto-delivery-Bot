from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from .context import CommandContext
from .permissions import Role, role_allows

CommandHandler = Callable[[CommandContext], Awaitable[None]]


@dataclass(slots=True)
class CommandSpec:
    """命令元数据用于 help、权限校验和热重载重新注册。"""

    name: str
    handler: CommandHandler
    description: str = ""
    usage: str = ""
    required_role: str = Role.USER
    aliases: tuple[str, ...] = field(default_factory=tuple)


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, CommandSpec] = {}
        self._aliases: dict[str, str] = {}

    def clear(self) -> None:
        self._commands.clear()
        self._aliases.clear()

    def command(
        self,
        name: str,
        *,
        description: str = "",
        usage: str = "",
        required_role: str = Role.USER,
        aliases: tuple[str, ...] = (),
    ) -> Callable[[CommandHandler], CommandHandler]:
        normalized_name = name.strip().lower()
        normalized_aliases = tuple(alias.strip().lower() for alias in aliases if alias.strip())
        if not normalized_name:
            raise ValueError("Command name cannot be empty.")

        def decorator(handler: CommandHandler) -> CommandHandler:
            spec = CommandSpec(
                name=normalized_name,
                handler=handler,
                description=description,
                usage=usage or normalized_name,
                required_role=required_role,
                aliases=normalized_aliases,
            )
            self._commands[normalized_name] = spec
            for alias in normalized_aliases:
                self._aliases[alias] = normalized_name
            return handler

        return decorator

    def get(self, name: str) -> CommandSpec | None:
        normalized_name = name.strip().lower()
        command_name = self._aliases.get(normalized_name, normalized_name)
        return self._commands.get(command_name)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._commands))

    def all_commands(self) -> tuple[CommandSpec, ...]:
        return tuple(sorted(self._commands.values(), key=lambda spec: spec.name))

    def visible_commands(self, role: str) -> tuple[CommandSpec, ...]:
        return tuple(spec for spec in self.all_commands() if role_allows(role, spec.required_role))
