from __future__ import annotations

import json

from .base import Tool, ToolContext, ToolResult, truncate_output
from ..safety import authorize


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self._tools.values()
        ]

    def execute(self, name: str, args: dict | str, ctx: ToolContext) -> ToolResult:
        """Turn one tool call into an observation. Never raise into the agent loop.

        Contract:
        - unknown tool -> ToolResult(-1, error="unknown tool ... available: ...")
        - args is a JSON string -> parse it; invalid JSON -> error observation
        - args is not a dict -> error observation
        - tool.run raises -> error observation (type + message), not a crash
        - tool returns a non-ToolResult -> error observation
        - truncate result.output to ctx.max_output_chars and set truncated
        """
        if name not in self._tools:
            return ToolResult(-1, error=f"unknown tool {name!r}; available: {', '.join(self._tools)}")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError as exc:
                return ToolResult(-1, error=f"invalid JSON: {exc}")
        if not isinstance(args, dict):
            return ToolResult(-1, error="arguments must be a JSON object")
        try:
            authorize(name, args, ctx.execution_policy)
            result = self._tools[name].run(args, ctx)
            if not isinstance(result, ToolResult):
                return ToolResult(-1, error="tool returned a non-ToolResult")
            result.output, shortened = truncate_output(result.output, ctx.max_output_chars)
            result.truncated = result.truncated or shortened
            return result
        except Exception as exc:
            return ToolResult(-1, error=f"{type(exc).__name__}: {exc}")
