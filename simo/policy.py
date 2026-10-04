"""Fail-closed tool allowlist and release capability checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable

from simo.db import SimoDatabase, StoreError


class ToolClass(StrEnum):
    READ = "READ"
    WRITE_LOCAL = "WRITE_LOCAL"
    RELEASE = "RELEASE"


@dataclass(frozen=True, slots=True)
class ToolContext:
    teacher_id: str
    class_id: str
    authenticated_teacher: bool


@dataclass(frozen=True, slots=True)
class Decision:
    kind: str
    reason: str


@dataclass(frozen=True, slots=True)
class SimoTool:
    name: str
    tool_class: ToolClass
    handler: Callable[[dict[str, Any], ToolContext], Any]
    description: str = "Simo teacher workflow tool"
    parameters: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}, "additionalProperties": False})


class ToolPolicy:
    def __init__(self, database: SimoDatabase, allowed_names: set[str]) -> None:
        self.database = database
        self.allowed_names = frozenset(allowed_names)

    def check(self, tool: SimoTool, args: dict[str, Any], context: ToolContext) -> Decision:
        if tool.name not in self.allowed_names:
            return Decision("deny", "tool is not in the Simo allowlist")
        if not context.teacher_id.strip() or not context.class_id.strip():
            return Decision("deny", "authenticated teacher/class context is required")
        if tool.tool_class == ToolClass.WRITE_LOCAL and not context.authenticated_teacher:
            return Decision("deny", "teacher authentication is required for local changes")
        if tool.tool_class == ToolClass.RELEASE:
            artifact_id = args.get("artifact_id")
            if not isinstance(artifact_id, str):
                return Decision("deny", "release requires a scoped artifact id")
            try:
                authorized = self.database.has_valid_approval(
                    context.teacher_id, context.class_id, artifact_id, "release",
                )
            except (StoreError, ValueError):
                authorized = False
            if not authorized:
                return Decision("needs_approval", "a current approval for this artifact is required")
        return Decision("allow", "policy checks passed")


class SimoToolRegistry:
    """An isolated registry: unknown, shell, file, and web tools never dispatch."""

    def __init__(self, database: SimoDatabase, tools: list[SimoTool]) -> None:
        self._tools = {tool.name: tool for tool in tools}
        if len(self._tools) != len(tools):
            raise ValueError("duplicate Simo tool name")
        self.policy = ToolPolicy(database, set(self._tools))

    def execute(self, name: str, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            decision = Decision("deny", "tool is not in the Simo allowlist")
        else:
            decision = self.policy.check(tool, args, context)
        self.policy.database.record_event(
            context.teacher_id, context.class_id, "policy_decision",
            {"tool": name, "decision": decision.kind, "reason": decision.reason},
        )
        if tool is None:
            return {"ok": False, "status": "denied", "reason": decision.reason}
        if decision.kind != "allow":
            status = "denied" if decision.kind == "deny" else decision.kind
            return {"ok": False, "status": status, "reason": decision.reason}
        try:
            return {"ok": True, "status": "completed", "result": tool.handler(args, context)}
        except Exception:
            return {"ok": False, "status": "error", "reason": "tool failed"}
