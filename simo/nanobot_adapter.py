"""Build an upstream-compatible, Simo-only nanobot tool registry.

Import this module only in the installed nanobot runtime. The core Simo package stays
independent of nanobot's optional runtime dependencies for offline tests.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from simo.db import SimoDatabase
from simo.policy import SimoTool, SimoToolRegistry, ToolContext


def build_nanobot_registry(
    database: SimoDatabase,
    tools: list[SimoTool],
    context_provider: Callable[[], ToolContext | None],
):
    """Return nanobot's ToolRegistry populated exclusively with guarded Simo tools.

    The provider must derive its context from authenticated channel middleware, not
    from tool arguments or model-generated content.
    """
    from nanobot.agent.tools.base import Tool, ToolResult
    from nanobot.agent.tools.registry import ToolRegistry

    core = SimoToolRegistry(database, tools)

    class GuardedSimoTool(Tool):
        def __init__(self, definition: SimoTool) -> None:
            self.definition = definition

        @property
        def name(self) -> str:
            return self.definition.name

        @property
        def description(self) -> str:
            return self.definition.description

        @property
        def parameters(self) -> dict:
            return self.definition.parameters

        @property
        def read_only(self) -> bool:
            from simo.policy import ToolClass
            return self.definition.tool_class == ToolClass.READ

        async def execute(self, **kwargs):
            context = context_provider()
            if context is None:
                return ToolResult.error("Simo policy denied this call: authenticated context is unavailable")
            result = core.execute(self.definition.name, kwargs, context)
            return json.dumps(result, ensure_ascii=False, default=str)

    class SimoOnlyToolRegistry(ToolRegistry):
        def prepare_call(self, name, params):
            if self.get(name) is None:
                context = context_provider()
                if context is not None:
                    denied = core.execute(name, {}, context)
                    return None, params, ToolResult.error(json.dumps(denied, ensure_ascii=False))
            return super().prepare_call(name, params)

    registry = SimoOnlyToolRegistry()
    for definition in tools:
        registry.register(GuardedSimoTool(definition))
    return registry
