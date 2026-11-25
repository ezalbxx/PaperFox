"""Workspace-local persistent jobs. The worker owns its child process handle."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from .safety import authorize

TERMINAL = frozenset({"completed", "failed", "cancelled", "timed_out"})


def atomic_json(path: Path, data: dict) -> None:
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        # Windows readers may briefly hold a handle without FILE_SHARE_DELETE.
        # Retain the old complete file and retry only the atomic rename.
        for attempt in range(8):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if os.name != 'nt' or attempt == 7:raise
                time.sleep(min(.01 * (2 ** attempt), .08))
    finally:
        temporary.unlink(missing_ok=True)


class JobManager:
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace).resolve()
        internal = self.workspace / ".myagent"
        self.root = internal / "jobs"
        # Do not write through a symlink into an external directory.
        if internal.resolve() != internal or self.root.resolve() != self.root:
            raise ValueError("job storage cannot be a symlink")

    def directory(self, job_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", job_id):
            raise ValueError("invalid job id")
        path = self.root / job_id
        if path.resolve() != path:
            raise ValueError("job directory cannot be a symlink")
        return path

    def status(self, job_id: str, wait_seconds: float = 0) -> dict:
        path = self.directory(job_id)
        deadline = time.monotonic() + min(max(0, wait_seconds), 30)
        while True:
            record_path = path / "record.json"
            if record_path.is_symlink():
                raise ValueError("invalid job record")
            data = json.loads(record_path.read_text(encoding="utf-8"))
            if data["state"] not in TERMINAL and time.time() - data["heartbeat"] > 15:
                data = dict(data, state="unknown", diagnostic="worker heartbeat stale; inspect logs; no automatic replay")
            if data["state"] in TERMINAL or time.monotonic() >= deadline:
                return data
            time.sleep(0.1)

    def start(self, argv: list[str], *, max_seconds: float = 3600, python_exe: str = sys.executable) -> dict:
        authorize("start_job", {"argv": argv}, "trusted")
        if not isinstance(argv, list) or not argv or len(argv) > 64 or not all(
            isinstance(a, str) and "\0" not in a for a in argv
        ):
            raise ValueError("argv must be a nonempty list of strings")
        if not 0 < float(max_seconds) <= 86400:
            raise ValueError("max_seconds must be in (0, 86400]")
        self.root.mkdir(parents=True, exist_ok=True)
        # One creation lock serializes admission across separate CLI processes.
        lock = self.root / ".admission.lock"
        deadline = time.monotonic() + 5
        while True:
            try:
                lock.mkdir()
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("job admission busy; inspect stale lock if no launcher is active")
                time.sleep(0.05)
        try:
            active = 0
            for entry in self.root.iterdir():
                if re.fullmatch(r"[0-9a-f]{32}", entry.name):
                    state = self.status(entry.name)
                    if state["state"] not in TERMINAL:
                        active += 1
            if active >= 2:
                raise RuntimeError("at most two active jobs per workspace; wait or cancel an owned job")
            job_id = uuid4().hex
            path = self.directory(job_id)
            path.mkdir()
            now = time.time()
            record = {"id": job_id, "state": "queued", "argv": argv, "workspace": str(self.workspace),
                      "created": now, "heartbeat": now, "max_seconds": float(max_seconds)}
            atomic_json(path / "record.json", record)
            flags = {}
            if os.name == "nt":
                flags["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            else:
                flags["start_new_session"] = True
            # Source root is passed explicitly for editable installs and test isolation.
            env = os.environ.copy()
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
            with (path / "worker.log").open("ab") as worker_log:
                try:
                    subprocess.Popen([python_exe, "-m", "myagent.job_worker", str(path / "record.json")],
                                     cwd=self.workspace, stdin=subprocess.DEVNULL, stdout=worker_log,
                                     stderr=worker_log, env=env, close_fds=True, **flags)
                except Exception as exc:
                    atomic_json(path / "record.json", dict(record, state="failed", error=str(exc)))
                    raise
            return record
        finally:
            lock.rmdir()

    def logs(self, job_id: str, max_chars: int = 8000) -> dict:
        path = self.directory(job_id)
        result = {}
        budget = min(max(1, max_chars), 16000)
        for name in ("stdout.log", "stderr.log", "worker.log"):
            p = path / name
            if p.is_symlink():
                raise ValueError("invalid log path")
            if not p.exists():
                result[name] = ""
                continue
            with p.open("rb") as stream:
                size = stream.seek(0, 2)
                stream.seek(max(0, size - budget))
                result[name] = stream.read(budget).decode("utf-8", errors="replace")
        return result

    def cancel(self, job_id: str) -> dict:
        state = self.status(job_id)
        if state["state"] not in TERMINAL:
            # Never kill a PID read from mutable disk; request the live owner worker to stop its child.
            (self.directory(job_id) / "cancel.request").touch(exist_ok=True)
        return {"id": job_id, "cancel_requested": state["state"] not in TERMINAL, "state": state["state"]}
