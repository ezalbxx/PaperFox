"""Personal chat / consult / goal CLI. No changes to original course commands."""
from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

from .config import Config, PRICES
from .conversation import ConversationStore
from .interactive_model import StreamingModel
from .jobs import atomic_json, JobManager
from .runtime import PersonalRuntime, MODES

HELP = '''
/mode consult|general|goal  切换咨询/通用/目标模式（切出goal会暂停目标）
/depth auto|quick|balanced|deep  自动/简答/常规/深入，与工作模式分开
/goal 目标文字             保存新目标并持续执行
/continue                 接续当前未完成目标
/ask 问题                 暂时咨询，回答后继续原目标
/status                   本地会话/目标/费用状态，不调用模型
/pause                    暂停目标与后续派发；不取消已有后台作业
/cancel-goal              结束目标；已有作业仍可单独查询/取消
/cancel-job 作业ID         请求取消指定作业
/limits 步数 美元 秒数 [tokens] 修改目标总额度；0表示该项不设上限
/remember 要求            明确保存项目偏好
/memory  /forget 序号      查看/撤销偏好
/help  /exit              帮助/保存退出；下次默认接着聊
'''


class TerminalUI:
    def __init__(self):
        self.streaming = False
        self.text = ""

    def __call__(self, kind, **data):
        if kind == "answer_delta":
            if not self.streaming:
                print("\nAgent> ", end="", flush=True)
                self.streaming = True
            print(data["text"], end="", flush=True)
            self.text += data["text"]
        else:
            if self.streaming:
                print(flush=True)
                self.streaming = False
            if kind == "api_wait":
                print("[等待 API 响应]", flush=True)
            elif kind == "context_preparing":
                print("[正在压缩上下文]", flush=True)
            elif kind == "api_retry":
                print(f"[重试 {data['attempt']}: {data['reason']}]", flush=True)
            elif kind == "tool_call":
                print(f"[工具 {data.get('name')}]", flush=True)
            elif kind == "tool_result":
                print(f"[工具结束 rc={data.get('returncode')} {str(data.get('error', ''))[:160]}]", flush=True)
            elif kind == "compaction":
                print("[上下文压缩完成，计入用量]", flush=True)
            elif kind == "paused":
                print(f"[暂停] {data['reason']}", flush=True)
            elif kind == "job_finished":
                print(f"[作业 {data['job_id']} {data['state']}]", flush=True)

    def result(self, text):
        if self.streaming:
            print(flush=True)
            self.streaming = False
        if text and text.strip() != self.text.strip():
            print(f"\nAgent> {text}", flush=True)
        self.text = ""


def _config(args):
    return Config.from_env(workspace=args.workspace, provider=args.provider, base_url=args.base_url,
                           model=args.model, max_steps=args.max_steps, max_cost=args.max_cost,
                           max_seconds=args.max_seconds, execution_policy=args.execution_policy,
                           context_max_tokens=args.context_max_tokens, python_exe=args.python)


def _session_path(workspace, session_id):
    root = workspace.resolve()/".myagent"/"chat"
    if not session_id:
        session_id = json.loads((root/"latest.json").read_text(encoding="utf-8"))["session_id"]
    if not session_id.isalnum():
        raise ValueError("invalid session id")
    path = root/f"{session_id}.json"
    if not path.exists():
        raise ValueError("conversation not found")
    return path


def _background(runtime, args):
    session_id = runtime.store.id
    log = runtime.store.root / f"{session_id}.worker.log"
    runtime.close()
    command = [sys.executable, "-B", "-m", "myagent", "goal", "--workspace", str(runtime.config.workspace),
               "--session", session_id, "--continue", "--worker",
               "--execution-policy", runtime.config.execution_policy, "--provider", runtime.config.provider,
               "--base-url", runtime.config.base_url, "--model", runtime.config.model,
               "--python", runtime.config.python_exe,
               "--context-max-tokens", str(runtime.config.context_max_tokens)]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    flags = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    with log.open("ab") as stream:
        process = subprocess.Popen(command, cwd=runtime.config.workspace, env=env, stdin=subprocess.DEVNULL,
                                   stdout=stream, stderr=stream, **flags)
    atomic_json(log.with_suffix(".json"), {"pid": process.pid, "session_id": session_id})
    print(f"Goal已交给后台进程：{session_id}\n日志：{log}\n查询：myagent goal --status --session {session_id} --workspace \"{runtime.config.workspace}\"")


def _goal_limits(args, runtime):
    return dict(max_steps=args.max_steps if args.max_steps is not None else 100,
                max_cost=args.max_cost if args.max_cost is not None else runtime.config.max_cost,
                max_seconds=args.max_seconds if args.max_seconds is not None else 3600,
                max_tokens=args.max_tokens or 0)


def _command(runtime, line, ui, args):
    cmd, _, tail = line.partition(" ")
    tail = tail.strip()
    if cmd in ("/exit", "/quit"):
        runtime.cancel()
        return False
    if cmd == "/help":
        print(HELP)
    elif cmd == "/status":
        print(json.dumps(runtime.status(), ensure_ascii=False, indent=2))
    elif cmd == "/mode":
        runtime.set_mode(tail)
        print(f"模式：{tail}")
    elif cmd == "/depth":
        runtime.set_depth(tail)
        print(f"回答深度：{tail}")
    elif cmd == "/pause":
        runtime.cancel()
        runtime._paused("用户暂停；后台作业保持原状态。")
        runtime.save()
    elif cmd == "/goal":
        runtime.start_goal(tail, **_goal_limits(args, runtime))
        ui.result(runtime.answer(tail))
    elif cmd == "/continue":
        if not runtime.goal:
            raise ValueError("没有待续目标")
        runtime.set_mode("goal")
        ui.result(runtime.answer(continue_goal=True))
    elif cmd == "/ask":
        # Do not recursively drain the same input queue while answering an aside.
        hook, runtime.input_hook = runtime.input_hook, None
        try:
            ui.result(runtime.answer(tail, mode="consult"))
        finally:
            runtime.input_hook = hook
    elif cmd == "/cancel-goal":
        if runtime.goal:
            runtime.goal.status = "cancelled"
            runtime.goal.stop_reason = "user_cancelled"
            runtime.goal.summary = "用户结束目标；后台作业未自动取消"
            runtime.set_mode("general")
        print("目标结束；作业状态可用 job status 单独查询。")
    elif cmd == "/cancel-job":
        print(json.dumps(JobManager(runtime.config.workspace).cancel(tail), ensure_ascii=False))
    elif cmd == "/limits":
        values = tail.split()
        if len(values) not in (3, 4):
            raise ValueError("/limits 步数 美元 秒数 [tokens]")
        steps, usd, seconds = values[:3]
        if not runtime.goal:
            raise ValueError("没有目标")
        if min(float(steps), float(usd), float(seconds)) < 0:
            raise ValueError("额度不能为负")
        runtime.goal.max_steps, runtime.goal.max_cost, runtime.goal.max_seconds = int(steps), float(usd), float(seconds)
        if len(values) == 4:
            tokens = int(values[3])
            if tokens < 0:
                raise ValueError("token额度不能为负")
            runtime.goal.max_tokens = tokens
        runtime.goal.authorization.update(source="explicit limits update", max_cost_usd=runtime.goal.max_cost,
                                          max_tokens=runtime.goal.max_tokens, max_seconds=runtime.goal.max_seconds)
        runtime.save()
        print("目标总额度已更新；/continue 继续。")
    elif cmd == "/remember":
        runtime.project.remember(tail)
        print("已保存项目偏好。")
    elif cmd == "/memory":
        runtime.project.refresh()
        print(json.dumps({"notes":runtime.project.notes,"records":runtime.project.records}, ensure_ascii=False, indent=2))
    elif cmd == "/forget":
        runtime.project.forget(int(tail))
        print("已撤销该偏好。")
    else:
        raise ValueError("未知命令；/help 查看帮助")
    return True


def _interactive(runtime, ui, args):
    inputs = queue.Queue()
    closed = False

    def reader():
        while True:
            line = sys.stdin.readline()
            if not line:
                inputs.put(None)
                return
            line = line.strip()
            if line.split(" ", 1)[0] in ("/pause", "/exit", "/quit", "/mode", "/cancel-goal"):
                runtime.cancel()
            inputs.put(line)

    threading.Thread(target=reader, daemon=True).start()

    def drain():
        nonlocal closed
        while not inputs.empty():
            line = inputs.get_nowait()
            if line is None:
                closed = True
                runtime.cancel()
                return
            if not line:
                continue
            try:
                if line.startswith("/"):
                    if line.startswith(("/goal ", "/continue")):
                        print("[当前目标运行中，请先 /pause 再切换或接续目标]")
                    else:
                        closed = not _command(runtime, line, ui, args)
                else:
                    runtime.append_user(line)
                    runtime.goal.corrections.append(line)
                    runtime.save()
            except (ValueError, OSError) as exc:
                print(f"[输入] {exc}")
            if closed:
                return

    runtime.input_hook = drain
    print(HELP)
    while not closed:
        print("\n你> ", end="", flush=True)
        try:
            line = inputs.get()
            if line is None:
                break
            if not line:
                continue
            if line.startswith("/"):
                closed = not _command(runtime, line, ui, args)
            else:
                if runtime.mode == "goal" and (not runtime.goal or runtime.goal.status in ("completed", "cancelled")):
                    runtime.start_goal(line, **_goal_limits(args, runtime))
                ui.result(runtime.answer(line))
        except KeyboardInterrupt:
            runtime.cancel()
            runtime._paused("用户暂停；/continue 接续，/exit 保存退出")
            runtime.save()
        except Exception as exc:
            print(f"[未完成，已保存] {type(exc).__name__}: {exc}", file=sys.stderr)


def cmd_personal(args):
    runtime = None
    try:
        config = _config(args)
        if getattr(args, "status", False) or getattr(args, "pause", False):
            path = _session_path(config.workspace, args.session)
            if args.pause:
                atomic_json(path.with_suffix(".control.json"), {"command": "pause"})
                print("已提交暂停请求；在请求返回/工具边界处理，作业不自动取消。")
            else:
                state = json.loads(path.read_text(encoding="utf-8"))
                print(json.dumps({k:v for k,v in state.items() if k != "messages"}, ensure_ascii=False, indent=2))
            return 0
        ui = TerminalUI()
        model = StreamingModel(config, ui)
        runtime = PersonalRuntime(config, model, session_id=args.session, new=args.new, title=args.title, emit=ui)
        if args.depth:
            runtime.set_depth(args.depth)
        print(f"会话 {runtime.store.id} · {runtime.state['title']} · workspace={config.workspace}")
        if config.model not in PRICES:
            print("[费用] 当前模型无已知价表，金额预算无法保证；请使用步数/时间额度。")
        if args.command == "goal":
            if args.task:
                runtime.start_goal(args.task, **_goal_limits(args, runtime))
                runtime.append_user(args.task)
                runtime.save()
            elif not args.continue_goal or not runtime.goal:
                raise ValueError('用 goal "目标" 创建目标，或 goal --continue 接续')
            else:
                for key in ("max_steps", "max_cost", "max_seconds", "max_tokens"):
                    value = getattr(args, key)
                    if value is not None:
                        if value < 0:
                            raise ValueError("额度不能为负")
                        setattr(runtime.goal, key, value)
            runtime.set_mode("goal")
            if args.background:
                _background(runtime, args)
                runtime = None
                return 0
            control = runtime.store.path.with_suffix(".control.json")
            def poll_control():
                if control.exists():
                    data = json.loads(control.read_text(encoding="utf-8"))
                    control.unlink()
                    if data.get("command") == "pause":
                        runtime.cancel()
            runtime.input_hook = poll_control
            ui.result(runtime.answer(continue_goal=True))
            print(json.dumps(runtime.status(), ensure_ascii=False, indent=2))
            return 0 if runtime.goal.status in ("completed", "waiting_for_user") else 3
        if args.mode:
            runtime.set_mode(args.mode)
        if args.message:
            if runtime.mode == "goal" and (not runtime.goal or runtime.goal.status in ("completed", "cancelled")):
                runtime.start_goal(args.message, **_goal_limits(args, runtime))
            ui.result(runtime.answer(args.message))
            return 0
        _interactive(runtime, ui, args)
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"[未完成] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    finally:
        if runtime is not None:
            runtime.close()


def cmd_sessions(args):
    for row in ConversationStore.list(Path(args.workspace)):
        print(json.dumps(row, ensure_ascii=False))
    return 0


def register_personal_commands(sub):
    for name in ("chat", "goal"):
        parser = sub.add_parser(name, help="persistent personal chat" if name == "chat" else "keep advancing a persistent goal")
        parser.add_argument("--workspace", default=".")
        parser.add_argument("--session", help="conversation ID; default last conversation in this workspace")
        parser.add_argument("--new", action="store_true", help="start a separate conversation")
        parser.add_argument("--title", default="")
        parser.add_argument("--provider", default=None)
        parser.add_argument("--base-url", default=None)
        parser.add_argument("--model", default=None)
        parser.add_argument("--python", default=None)
        parser.add_argument("--execution-policy", choices=("trusted", "guarded"), default=None)
        parser.add_argument("--max-steps", type=int, default=None)
        parser.add_argument("--max-cost", type=float, default=None, help="USD peak estimate, not invoice")
        parser.add_argument("--max-seconds", type=int, default=None)
        parser.add_argument("--max-tokens", type=int, default=None, help="goal cumulative tokens, including summaries; 0 unlimited")
        parser.add_argument("--depth", choices=("auto", "quick", "balanced", "deep"), default=None)
        parser.add_argument("--context-max-tokens", type=int, default=None)
        if name == "chat":
            parser.add_argument("--mode", choices=MODES, default=None)
            parser.add_argument("--message", "-m", help="one message, save and exit")
        else:
            parser.add_argument("task", nargs="?")
            parser.add_argument("--continue", dest="continue_goal", action="store_true")
            parser.add_argument("--background", action="store_true")
            parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
            parser.add_argument("--status", action="store_true")
            parser.add_argument("--pause", action="store_true")
        parser.set_defaults(func=cmd_personal)
    sessions = sub.add_parser("sessions", help="list saved personal conversations without model calls")
    sessions.add_argument("--workspace", default=".")
    sessions.set_defaults(func=cmd_sessions)
