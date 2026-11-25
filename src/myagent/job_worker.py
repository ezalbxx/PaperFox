from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .jobs import atomic_json
from .tools.base import kill_process_tree


def run(record_path: Path) -> int:
    data = json.loads(record_path.read_text(encoding="utf-8"))
    directory = record_path.parent
    started = time.time()
    proc = None

    def save(state, **extra):
        data.update(state=state, heartbeat=time.time(), **extra)
        atomic_json(record_path, data)

    def event(kind, **extra):
        with (directory / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"time": time.time(), "type": kind, **extra}) + "\n")
            stream.flush()

    try:
        if (directory / "cancel.request").exists():
            save("cancelled", finished=time.time())
            event("cancelled_before_start")
            return 0
        flags = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
        env = os.environ.copy()
        env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        with (directory / "stdout.log").open("ab") as out, (directory / "stderr.log").open("ab") as err:
            proc = subprocess.Popen(data["argv"], cwd=data["workspace"], stdin=subprocess.DEVNULL,
                                    stdout=out, stderr=err, env=env, **flags)
            save("running", pid=proc.pid, worker_pid=os.getpid(), started=started)
            event("started", argv=data["argv"], pid=proc.pid)
            while proc.poll() is None:
                state = None
                if (directory / "cancel.request").exists():
                    state = "cancelled"
                elif time.time() - started >= data["max_seconds"]:
                    state = "timed_out"
                if state:
                    kill_process_tree(proc.pid)
                    proc.wait(timeout=10)
                    save(state, returncode=proc.returncode, finished=time.time())
                    event(state, returncode=proc.returncode)
                    return 0
                save("running")
                time.sleep(0.2)
            state = "completed" if proc.returncode == 0 else "failed"
            save(state, returncode=proc.returncode, finished=time.time())
            event(state, returncode=proc.returncode)
        return 0
    except BaseException as exc:
        if proc is not None and proc.poll() is None:
            kill_process_tree(proc.pid)
            proc.wait(timeout=10)
        save("failed", error=f"{type(exc).__name__}: {exc}", finished=time.time())
        event("failed", error=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(run(Path(sys.argv[1]).resolve()))
