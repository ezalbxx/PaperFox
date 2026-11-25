from __future__ import annotations

from pathlib import Path
import json
from datetime import datetime

from .events import read_events


def resume(path: Path) -> list[dict]:
    """Rebuild the message list from a JSONL session.

    Contract:
    - read all events; keep payload["message"] for type == "message"
    - if the last message is an assistant with tool_calls and some calls have
      no matching tool message, append an interrupted tool observation for each
      missing call (same tool_call_id, content says "interrupted")
    - return [] for an empty file
    """
    events = read_events(path, tolerate_incomplete_tail=True)
    messages: list[dict] = []
    recorded_results = {}
    for event in events:
        payload = event.get("payload", {})
        if event.get("type") == "context_checkpoint":
            messages = list(payload["messages"])
        elif event.get("type") == "message":
            messages.append(payload["message"])
        elif event.get("type") == "tool_result":
            recorded_results[payload["call_id"]] = {
                k: v for k, v in payload.items() if k != "call_id"
            }
    repaired: list[dict] = []
    pending: dict[str, dict] = {}

    def close_pending():
        for call_id in pending:
            result = recorded_results.get(call_id, {
                "returncode": -1,
                "error": "interrupted: outcome unknown; inspect workspace before retrying any side effect",
                "output": "", "truncated": False,
            })
            repaired.append({"role": "tool", "tool_call_id": call_id,
                             "content": json.dumps(result, ensure_ascii=False)})
        pending.clear()

    for message in messages:
        if message.get("role") == "tool":
            call_id = message.get("tool_call_id")
            if call_id not in pending:
                raise ValueError(f"orphan or duplicate tool result: {call_id}")
            repaired.append(message)
            del pending[call_id]
            continue
        close_pending()
        repaired.append(message)
        calls = message.get("tool_calls", []) or []
        for call in calls:
            if call["id"] in pending:
                raise ValueError("duplicate tool call id")
            pending[call["id"]] = call
    close_pending()
    return repaired


def resume_state(path: Path) -> dict:
    """Restore cumulative limits without counting copied history twice."""
    events = read_events(path, tolerate_incomplete_tail=True)
    state = {"steps": 0, "cost": 0.0, "elapsed_seconds": 0.0,
             "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
    started = None
    for event in events:
        p = event.get("payload", {})
        if event.get("type") == "run_start":
            state.pop("exit_status", None)
            started = datetime.fromisoformat(event["ts"]) if event.get("ts") else None
            state["workspace"] = p.get("workspace")
            state["model"] = p.get("model")
            inherited = p.get("inherited", {})
            state["steps"] = inherited.get("steps", 0)
            state["cost"] = inherited.get("cost", 0.0)
            state["usage"].update(inherited.get("usage", {}))
            state["elapsed_seconds"] = float(inherited.get("elapsed_seconds", 0.0))
        elif event.get("type") == "model_usage":
            state["cost"] += float(p.get("cost", 0.0))
            for key in state["usage"]:
                state["usage"][key] += int(p.get("usage", {}).get(key, 0) or 0)
            if p.get("purpose", "agent") == "agent":
                state["steps"] = max(state["steps"], int(p.get("step", 0)))
        elif event.get("type") == "run_end":
            state["exit_status"] = p.get("exit_status")
            state["steps"] = max(state["steps"], int(p.get("steps", 0)))
            if "elapsed_seconds" in p:
                state["elapsed_seconds"] = float(p["elapsed_seconds"])
            elif started and event.get("ts"):
                state["elapsed_seconds"] += max(0, (datetime.fromisoformat(event["ts"]) - started).total_seconds())
            started = None
    if started and events and events[-1].get("ts"):
        state["elapsed_seconds"] += max(0, (datetime.fromisoformat(events[-1]["ts"]) - started).total_seconds())
    state["messages"] = resume(path)
    return state
