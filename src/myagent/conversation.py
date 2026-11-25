"""Named conversations with a warm in-memory context and restart checkpoints."""
from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from .events import read_events
from .jobs import atomic_json
from .session import resume
from .task_state import now


class ConversationStore:
    def __init__(self, workspace: Path, session_id: str | None = None, *, new: bool = False, title: str = "", select_on_open: bool = True):
        self.workspace = workspace.resolve()
        self.root = self.workspace / ".myagent" / "chat"
        self.root.mkdir(parents=True, exist_ok=True)
        latest = self.root / "latest.json"
        if not session_id and not new and latest.exists():
            session_id = json.loads(latest.read_text(encoding="utf-8"))["session_id"]
        self.id = session_id or uuid4().hex[:12]
        if not self.id.isalnum() or len(self.id) > 64:
            raise ValueError("invalid session id")
        self.path = self.root / f"{self.id}.json"
        self.log_path = self.root / f"{self.id}.jsonl"
        if session_id and not self.path.exists():
            raise ValueError(f"conversation not found: {session_id}")
        # OS lock is released on process exit, including a crash. One writer per session.
        self._lock = (self.root / f"{self.id}.lock").open("a+b")
        self._lock.seek(0, os.SEEK_END)
        if self._lock.tell() == 0:
            self._lock.write(b"0")
            self._lock.flush()
        self._lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._lock.close()
            raise ValueError("this conversation is already open; use --new or another --session") from None
        self.state = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {
            "session_id": self.id, "workspace": str(self.workspace), "title": title or "新对话",
            "created_at": now(), "mode": "general", "messages": [], "goal": None,
            "totals": {"cost": 0.0, "steps": 0, "usage": {}}, "last_event_id": None, "log_bytes": 0,
        }
        if title:
            self.state["title"] = title
        # Normal restart loads just the checkpoint. Replay only after an unclean exit.
        if self.log_path.exists() and self.log_path.stat().st_size != self.state.get("log_bytes", 0):
            events = read_events(self.log_path, tolerate_incomplete_tail=True)
            self.state["messages"] = resume(self.log_path)
            for event in events:
                p = event["payload"]
                if event["type"] == "runtime_state":
                    for key in ("goal", "totals", "mode"):
                        self.state[key] = p[key]
                elif event["type"] == "goal_state":
                    self.state["goal"] = p["goal"]
                elif event["type"] == "model_usage":
                    totals = self.state["totals"]
                    totals["cost"] += p.get("cost", 0)
                    totals["steps"] += p.get("purpose") == "agent"
                    for key, value in p.get("usage", {}).items():
                        totals["usage"][key] = totals["usage"].get(key, 0) + value
                    goal = self.state.get("goal")
                    if goal and goal["status"] in ("running", "waiting_for_job"):
                        goal["cost"] += p.get("cost", 0)
                        goal["steps"] += p.get("purpose") == "agent"
                        goal["tokens"] = goal.get("tokens", 0) + (p.get("usage", {}).get("total_tokens", 0) or 0)
                elif event["type"] == "tool_result" and self.state.get("goal"):
                    try:
                        result = json.loads(p.get("output", ""))
                        result = result.get("result", result)
                        if result.get("id") and result.get("state") == "queued":
                            self.state["goal"]["jobs"][result["id"]] = "queued"
                    except (ValueError, AttributeError):
                        pass
            if events:
                self.state["last_event_id"] = events[-1]["id"]
            if self.state.get("goal") and self.state["goal"]["status"] in ("running", "waiting_for_job"):
                self.state["goal"]["status"] = "paused"
                self.state["goal"]["summary"] = "进程中断后恢复；检查结果未知项，/continue 接续。"
            # Preserve the invalid tail as evidence; remove it from the appendable log.
            raw = self.log_path.read_bytes()
            if raw and not raw.endswith(b"\n"):
                tail = raw.rsplit(b"\n", 1)[-1]
                try:
                    json.loads(tail)
                    with self.log_path.open("ab") as stream:
                        stream.write(b"\n")
                except ValueError:
                    (self.root / f"{self.id}.interrupted-tail.bin").write_bytes(tail)
                    with self.log_path.open("r+b") as stream:
                        stream.truncate(len(raw) - len(tail))
        if select_on_open:
            self.select()

    def save(self, messages: list[dict], logger) -> None:
        self.state["messages"] = messages
        self.state["updated_at"] = now()
        self.state["last_event_id"] = logger.last_id
        self.state["log_bytes"] = self.log_path.stat().st_size
        atomic_json(self.path, self.state)

    def close(self) -> None:
        self._lock.close()

    def select(self):
        """An explicit selection, not a background save, controls the next resume."""
        atomic_json(self.root / "latest.json", {"session_id": self.id})

    @staticmethod
    def selected(workspace):
        root = Path(workspace).resolve() / ".myagent" / "chat"
        path = root / "latest.json"
        if path.exists():
            sid = json.loads(path.read_text(encoding="utf-8")).get("session_id", "")
            if sid.isalnum() and (root / f"{sid}.json").is_file():
                return sid
        rows = ConversationStore.list(Path(workspace))
        return rows[0]["session_id"] if rows else None

    @staticmethod
    def list(workspace: Path) -> list[dict]:
        root = workspace.resolve() / ".myagent" / "chat"
        rows = []
        for path in root.glob("*.json"):
            if path.name == "latest.json":
                continue
            state = json.loads(path.read_text(encoding="utf-8"))
            rows.append({key: state.get(key) for key in ("session_id", "title", "mode", "updated_at")}
                        | {"goal": (state.get("goal") or {}).get("status")})
        return sorted(rows, key=lambda r: r.get("updated_at") or "", reverse=True)
