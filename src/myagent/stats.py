from __future__ import annotations

from pathlib import Path
from typing import Any

from .events import read_events

_USAGE_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens")


def _empty_usage() -> dict[str, int]:
    return {key: 0 for key in _USAGE_KEYS}


def _add_usage(target: dict[str, int], usage: Any) -> None:
    if not isinstance(usage, dict):
        return
    for key in _USAGE_KEYS:
        target[key] += int(usage.get(key, 0) or 0)


def summarize_session(path: Path) -> dict:
    """Summarize the run evidence stored in one JSONL session file.

    Returns a dict with keys: exit_status, steps, cost, cost_currency,
    usage, tool_calls, tool_failures, compactions, resumed_from.

    - tool_calls counts ``tool_call`` events actually recorded.
    - tool_failures counts ``tool_result`` events with a nonzero returncode.
    - compactions counts ``compaction`` events with accepted=True.
    - A complete session (has ``run_end``) reports the final run_end totals so
      inherited resume costs are not counted twice.
    - An incomplete session reports exit_status="Incomplete" and derives
      cumulative steps/cost/usage from run_start.inherited plus model_usage.
    """
    path = Path(path)
    events = read_events(path, tolerate_incomplete_tail=True)

    tool_calls = 0
    tool_failures = 0
    compactions = 0
    resumed_from: str | None = None
    run_end: dict | None = None
    inherited: dict = {}
    derived_steps = 0
    derived_cost = 0.0
    derived_usage = _empty_usage()

    for event in events:
        kind = event.get("type")
        payload = event.get("payload") or {}
        if kind == "run_start":
            resumed_from = payload.get("resumed_from") or resumed_from
            inherited = payload.get("inherited") or {}
            derived_steps = int(inherited.get("steps", 0) or 0)
            derived_cost = float(inherited.get("cost", 0.0) or 0.0)
            derived_usage = _empty_usage()
            _add_usage(derived_usage, inherited.get("usage"))
        elif kind == "model_usage":
            derived_cost += float(payload.get("cost", 0.0) or 0.0)
            _add_usage(derived_usage, payload.get("usage"))
            if payload.get("purpose", "agent") == "agent":
                derived_steps = max(derived_steps, int(payload.get("step", 0) or 0))
        elif kind == "tool_call":
            tool_calls += 1
        elif kind == "tool_result":
            returncode = payload.get("returncode")
            if returncode is None:
                returncode = 0
            try:
                failed = int(returncode) != 0
            except (TypeError, ValueError):
                failed = True
            if failed:
                tool_failures += 1
        elif kind == "compaction":
            if payload.get("accepted"):
                compactions += 1
        elif kind == "run_end":
            run_end = payload

    if run_end is not None:
        usage = _empty_usage()
        _add_usage(usage, run_end.get("usage"))
        return {
            "exit_status": run_end.get("exit_status", "Unknown"),
            "steps": int(run_end.get("steps", 0) or 0),
            "cost": float(run_end.get("cost", 0.0) or 0.0),
            "cost_currency": "USD",
            "usage": usage,
            "tool_calls": tool_calls,
            "tool_failures": tool_failures,
            "compactions": compactions,
            "resumed_from": resumed_from,
        }

    return {
        "exit_status": "Incomplete",
        "steps": derived_steps,
        "cost": derived_cost,
        "cost_currency": "USD",
        "usage": derived_usage,
        "tool_calls": tool_calls,
        "tool_failures": tool_failures,
        "compactions": compactions,
        "resumed_from": resumed_from,
    }
