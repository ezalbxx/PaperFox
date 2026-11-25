"""Small interactive tools: local search and persistent goal updates."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .tools.base import ToolResult, resolve_workspace_path
from .task_state import now


class SearchFilesTool:
    name = "search_files"
    description = "Search text in local workspace files, returning path:line. Literal case-insensitive search; no shell needed."
    parameters = {"type": "object", "properties": {
        "query": {"type": "string"}, "path": {"type": "string", "description": "relative file/directory; default ."},
        "glob": {"type": "string", "description": "filename pattern, default *"},
        "max_matches": {"type": "integer"}}, "required": ["query"]}

    def run(self, args, ctx):
        import fnmatch
        query = args["query"]
        if not isinstance(query, str) or not query:
            return ToolResult(-1, error="query must be nonempty")
        root = resolve_workspace_path(ctx.workspace, args.get("path", "."))
        matches, scanned, limited = [], 0, False
        limit = max(1, min(int(args.get("max_matches", 30)), 100))
        pattern = args.get("glob", "*")
        def paths():
            if root.is_file():
                yield root
                return
            for directory, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d not in (".git", ".myagent", ".venv", "node_modules", "__pycache__")
                           and not (Path(directory)/d).is_symlink()]
                for filename in files:
                    if fnmatch.fnmatch(filename, pattern):
                        yield Path(directory)/filename
        for path in paths():
            if scanned >= 2000:
                limited = True
                break
            try:
                path = resolve_workspace_path(ctx.workspace, str(path))
                if path.stat().st_size > 2_000_000:
                    continue
                scanned += 1
                raw = path.read_bytes()
                if b"\0" in raw[:4096]:
                    continue
                text = raw.decode("utf-8-sig")
            except (OSError, UnicodeError, ValueError):
                continue
            for index, line in enumerate(text.splitlines(), 1):
                if query.casefold() in line.casefold():
                    matches.append(f"{path.relative_to(ctx.workspace)}:{index}: {line[:500]}")
                    if len(matches) >= limit:
                        limited = True
                        break
            if limited:
                break
        return ToolResult(0, json.dumps({"matches": matches, "files_scanned": scanned, "limited": limited}, ensure_ascii=False))


class GoalUpdateTool:
    name = "goal_update"
    description = "Update the CURRENT persistent goal. progress saves plan/status; complete requires actual result evidence; wait_for_user stops at a required user checkpoint."
    parameters = {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["progress", "complete", "wait_for_user"]},
        "summary": {"type": "string", "description": "Visible reply to the user. Include the actual answer, advice, sample or options and the precise question at a checkpoint; never only say you have prepared them."}, "plan": {"type": "array", "items": {"type": "string"}},
        "evidence": {"type": "array", "items": {"type": "string"}, "description": "Actual artifact/result locations or specific verified findings; never planned outcomes"}},
        "required": ["action", "summary"]}

    def __init__(self, runtime):
        self.runtime = runtime

    def run(self, args, ctx):
        goal = self.runtime.goal
        if not goal or self.runtime.mode != "goal":
            return ToolResult(-1, error="no active goal in goal mode")
        action, summary = args.get("action"), args.get("summary", "")
        if action not in ("progress", "complete", "wait_for_user") or not isinstance(summary, str) or not summary.strip():
            return ToolResult(-1, error="valid action and nonempty summary required")
        evidence = args.get("evidence", [])
        plan = args.get("plan", goal.plan)
        if not isinstance(plan, list) or not all(isinstance(x, str) for x in plan):
            return ToolResult(-1, error="plan must contain strings")
        if not isinstance(evidence, list) or not all(isinstance(x, str) and x.strip() for x in evidence):
            return ToolResult(-1, error="evidence must contain nonempty strings")
        if action == "complete":
            from .jobs import TERMINAL
            if any(state not in TERMINAL for state in goal.jobs.values()) or self.runtime.pending_jobs():
                return ToolResult(-1, error="goal has unfinished jobs; inspect results before completing")
            if not evidence:
                return ToolResult(-1, error="complete requires actual evidence/findings; do not invent PASS")
        goal.summary, goal.plan, goal.updated_at = summary, plan, now()
        if evidence:
            goal.evidence = list(dict.fromkeys(goal.evidence + evidence))
        if action != "progress":
            goal.status = "completed" if action == "complete" else "waiting_for_user"
            goal.stop_reason = "completed" if action == "complete" else "user_checkpoint"
            ctx.submitted, ctx.submission = True, summary
        self.runtime.project.update("goal:" + goal.id, summary, kind="progress",
                                    status="completed" if action == "complete" else "active",
                                    sources=goal.evidence, session_id=self.runtime.store.id)
        self.runtime.logger.log("goal_state", goal=goal.as_dict())
        return ToolResult(0, json.dumps(goal.as_dict(), ensure_ascii=False))


class ProjectMemoryTool:
    name = "project_memory"
    description = "Read or update timestamped project progress/decisions. Reuse the same key to replace old state. Completed needs evidence. A user decision must quote the user's actual current message. Never treat a proposal as approval."
    parameters = {"type":"object", "properties": {
        "action":{"type":"string","enum":["read","update"]},
        "key":{"type":"string"}, "text":{"type":"string"},
        "kind":{"type":"string","enum":["progress","decision","reference"]},
        "status":{"type":"string","enum":["active","completed","blocked","superseded"]},
        "sources":{"type":"array","items":{"type":"string"}},
        "user_quote":{"type":"string"}}, "required":["action"]}

    def __init__(self, runtime):
        self.runtime = runtime

    def run(self, args, ctx):
        project = self.runtime.project
        if args["action"] == "read":
            project.refresh()
            rows = [project.records[args["key"]]] if args.get("key") else list(project.records.values())
            return ToolResult(0, json.dumps(rows, ensure_ascii=False))
        if args["action"] != "update":
            raise ValueError("unknown memory action")
        kind = args.get("kind", "progress")
        sources = args.get("sources", [])
        if kind == "decision":
            quote = args.get("user_quote", "").strip()
            if not quote or quote not in self.runtime.current_user_text:
                raise ValueError("decision needs an exact quote from the current user message")
            sources = sources + ["user:" + self.runtime.store.id + ":" + quote]
        record = project.update(args["key"], args["text"], kind=kind,
                                status=args.get("status", "active"), sources=sources,
                                session_id=self.runtime.store.id)
        self.runtime.logger.log("project_memory_updated", key=record["key"], kind=kind, status=record["status"], sources=sources)
        return ToolResult(0, json.dumps({k:v for k,v in record.items() if k != "history"}, ensure_ascii=False))
