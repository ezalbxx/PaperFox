"""A single owner thread per conversation, shared by CLI-compatible web clients."""
from __future__ import annotations

import copy
import json
import queue
import threading
from collections import deque
from uuid import uuid4

from .config import Config
from .interactive_model import StreamingModel
from .runtime import PersonalRuntime
from .jobs import atomic_json
from .task_state import now

ACTIVITY_KINDS = ("tool_call", "tool_result", "compaction", "api_retry", "paused", "job_finished", "context_preparing", "response_policy", "model_reasoning", "first_answer", "api_end")

class WebRuntime(PersonalRuntime):
    def save(self):
        super().save()
        self.emit("state", status=copy.deepcopy(self.status()))


class WebSession:
    def __init__(self, workspace, *, session_id=None, new=False, model_factory=StreamingModel):
        self.condition = threading.Condition()
        self.events = deque(maxlen=2400)
        self.activity_history = deque(maxlen=80)
        self.sequence = 0
        self.stream_id = uuid4().hex
        self.busy = False
        self.phase = "准备就绪"
        self.current_turn = None
        self.turn_text = {}
        self.active_text = ""
        self.segment_id = None
        self.commands = queue.Queue()
        self.inbox = queue.Queue()
        self.last_status = None
        self.closed = False
        config = Config.from_env(workspace=workspace, execution_policy="trusted")
        model = model_factory(config)
        self.runtime = WebRuntime(config, model, session_id=session_id, new=new, emit=self.emit, select_session=False)
        from .events import read_events
        self.history = []
        for event in read_events(self.runtime.store.log_path):
            if event["type"] in ACTIVITY_KINDS:
                self.activity_history.append({"kind":event["type"], "time":event["ts"], **event["payload"]})
            if event["type"] == "message":
                self.remember_message(event["payload"]["message"])
            elif event["type"] == "web_answer_end":
                self.remember_result(event["payload"])
            elif event["type"] == "web_partial_answer":
                self.remember_message({"role": "assistant", "content": event["payload"]["text"]})
        original_message = self.runtime.logger.message
        def record_message(message):
            with self.condition:
                original_message(message)
                self.remember_message(message)
                if message.get("role") == "assistant" and message.get("content"):
                    self.publish("assistant_message", text=message["content"], segment_id=self.segment_id,
                                 turn_id=self.current_turn)
        self.runtime.logger.message = record_message
        if self.runtime.goal and self.runtime.goal.status in ("running", "waiting_for_job"):
            self.runtime.goal.status = "paused"
            self.runtime.goal.stop_reason = "service_restart"
            self.runtime.goal.summary = "服务重启后已恢复目标；点击继续目标接续。"
            self.runtime.save()
        self.id = self.runtime.store.id
        self.workspace = str(workspace)
        self.pending_path = self.runtime.store.root / f"{self.id}.pending"
        self.pending = json.loads(self.pending_path.read_text(encoding="utf-8")) if self.pending_path.exists() else {}
        for command in self.pending.values():
            if command.pop("processing", False):
                command["interrupted"] = True
            if not command.get("interrupted"):
                self.inbox.put(command)
        self.runtime.input_hook = self.drain
        self.thread = threading.Thread(target=self.work, name=f"wisdom-{self.id}", daemon=True)
        self.thread.start()

    def remember_message(self, message):
        text = message.get("content") or ""
        if message.get("role") in ("user", "assistant") and text and not text.startswith(("[Runtime", "[Compacted historical")):
            with self.condition:
                self.history.append({"role": message["role"], "text": text})
                if message["role"] == "assistant":
                    self.active_text = ""

    def remember_result(self, data):
        # Tool-only completion (e.g. goal_update) is also a visible, persistent answer.
        text = data.get("text")
        display = data.get("display_result", not data.get("streamed"))
        if text and display and (not self.history or self.history[-1] != {"role": "assistant", "text": text}):
            self.remember_message({"role": "assistant", "content": text})

    def publish(self, kind, **data):
        with self.condition:
            self.sequence += 1
            event = {"id": self.sequence, "kind": kind, "time": now(), **data}
            self.events.append(event)
            if kind in ACTIVITY_KINDS:
                self.activity_history.append(event)
            self.condition.notify_all()

    def emit(self, kind, **data):
        with self.condition:
            self._emit(kind, **data)

    def _emit(self, kind, **data):
        phases = {"api_wait": "等待模型响应", "api_first_event": "已收到模型响应", "answer_delta": "正在回答",
                  "context_preparing": "正在整理上下文", "api_retry": "连接重试中", "job_finished": "作业已结束，正在接续",
                  "tool_call": "正在使用本地工具", "tool_result": "工具已返回", "paused": "已暂停",
                  "model_reasoning": "模型正在深入分析", "first_answer": "正在回答"}
        if kind == "state":
            self.last_status = data["status"]
        if kind in phases:
            self.phase = phases[kind]
        if kind == 'tool_progress':
            self.phase = f"{data['name']} 已运行 {data['seconds']:.0f} 秒 · 可暂停"
        if kind == "api_wait":
            self.segment_id = uuid4().hex
        if kind == "answer_delta" and self.current_turn:
            if not self.segment_id:
                self.segment_id = uuid4().hex
            self.turn_text[self.current_turn] = self.turn_text.get(self.current_turn, "") + data["text"]
            self.active_text += data["text"]
        self.publish(kind, turn_id=self.current_turn, segment_id=self.segment_id, **data)

    def snapshot(self):
        with self.condition:
            return {"session_id": self.id, "workspace": self.workspace, "messages": list(self.history),
                    "status": copy.deepcopy(self.last_status), "busy": self.busy, "phase": self.phase,
                    "cursor": self.sequence, "stream_id": self.stream_id, "model": self.runtime.config.model,
                    "active_text": self.active_text, "active_turn": self.current_turn,
                    "active_segment": self.segment_id, "pending": copy.deepcopy(list(self.pending.values())),
                    "activities": copy.deepcopy(list(self.activity_history))}

    def save_pending(self):
        atomic_json(self.pending_path, self.pending)
        self.publish("pending", pending=copy.deepcopy(list(self.pending.values())))

    def submit(self, command):
        action = command.get("action", "send")
        if self.closed:
            raise ValueError("会话已关闭，请刷新页面")
        if action == "discard_pending":
            if self.pending.get(command.get("client_id"), {}).get("processing"):
                raise ValueError("这条消息已经开始处理；可先暂停，不能重复取回执行。")
            self.finish_pending(command)
            return
        if action == "pause":
            self.runtime.cancel()
            self.phase = "正在暂停，停止前台操作并保留后台作业"
            self.publish("busy", busy=self.busy, phase=self.phase)
            if not self.busy:
                self.commands.put({"action": "pause_idle"})
            return
        if self.busy and self.runtime.mode == "goal" and action in ("send", "rename", "remember", "limits", "depth"):
            if action == "send":
                command["client_id"] = command.get("client_id") or uuid4().hex
                command["announced"] = True
                with self.condition:
                    self.pending[command["client_id"]] = command
                    self.save_pending()
                self.publish("user_message", text=command["text"], client_id=command.get("client_id"), queued=True)
            self.inbox.put(command)
            return
        if self.busy and action in ("mode", "cancel_goal"):
            self.runtime.cancel()
        self.commands.put(command)

    def drain(self):
        while not self.inbox.empty():
            if self.runtime.cancelled():
                break
            command = self.inbox.get_nowait()
            if command.get("action", "send") != "send":
                self.control(command)
                continue
            text = command["text"]
            if command.get("client_id") not in self.pending:
                continue
            with self.condition:
                command["processing"] = True
                self.save_pending()
            if command.get("mode") == "consult":
                outer = self.current_turn
                try:
                    self.run_answer(text, mode="consult", depth=command.get("depth"), client_id=command.get("client_id"), announced=True)
                finally:
                    self.current_turn = outer
                    self.finish_pending(command)
            else:
                self.runtime.append_user(text)
                self.runtime.current_user_text = text
                self.publish("user_message", text=text, client_id=command.get("client_id"), queued=False)
                self.runtime.goal.corrections.append(text)
                if self.runtime.goal.status == "completed":
                    self.runtime.goal.status = "waiting_for_user"
                    self.runtime.goal.summary = "已收到新的补充要求；点击继续目标执行。"
                self.runtime.save()
                self.publish("steering_applied", text=text)
                self.finish_pending(command)

    def finish_pending(self, command):
        with self.condition:
            self.pending.pop(command.get("client_id"), None)
            self.save_pending()

    def run_answer(self, text="", *, mode=None, depth=None, continuation=False, client_id=None, announced=False):
        self.current_turn = uuid4().hex
        self.segment_id = None
        turn = self.current_turn
        if text:
            self.publish("user_message", text=text, client_id=client_id, queued=False)
        self.publish("answer_start", turn_id=turn)
        try:
            result = self.runtime.answer(text, mode=mode, depth=depth, continue_goal=continuation)
        except Exception:
            if self.active_text:
                partial = self.active_text + "\n[连接中断，回答尚未完成]"
                self.runtime.logger.log("web_partial_answer", text=partial)
                self.remember_message({"role": "assistant", "content": partial})
                self.publish("assistant_message", text=partial, segment_id=self.segment_id, turn_id=turn)
            self.turn_text.pop(turn, None)
            raise
        streamed = self.turn_text.pop(turn, "")
        display_result = bool(result and (not self.history or self.history[-1] != {"role":"assistant", "text":result}))
        result_event = {"turn_id": turn, "text": result, "streamed": bool(streamed), "display_result": display_result}
        with self.condition:
            self.runtime.logger.log("web_answer_end", **result_event)
            self.remember_result(result_event)
            self.publish("answer_end", turn_id=turn, text=result, display_result=display_result)

    def control(self, command):
        action = command["action"]
        rt = self.runtime
        if action == "mode":
            rt.set_mode(command["mode"])
        elif action == "depth":
            rt.set_depth(command["depth"])
        elif action == "pause_idle":
            rt._paused("用户暂停；后台作业未自动取消")
            rt.save()
        elif action == "cancel_goal":
            if rt.goal:
                rt.goal.status = "cancelled"
                rt.goal.stop_reason = "user_cancelled"
                rt.goal.summary = "用户结束目标，后台作业未自动取消"
            rt.set_mode("general")
        elif action == "rename":
            rt.state["title"] = command["title"][:100].strip() or "新对话"
            rt.save()
        elif action == "remember":
            rt.project.remember(command["text"])
            rt.save()
        elif action == "discard_pending":
            self.finish_pending(command)
        elif action == "limits":
            if not rt.goal:
                raise ValueError("请先创建一个目标")
            for key in ("max_steps", "max_cost", "max_seconds", "max_tokens"):
                if key in command:
                    value = float(command[key])
                    if value < 0:
                        raise ValueError("额度不能为负")
                    setattr(rt.goal, key, int(value) if key in ("max_steps", "max_tokens") else value)
            rt.goal.authorization.update(source="explicit limits update", updated_at=now(),
                max_cost_usd=rt.goal.max_cost, max_tokens=rt.goal.max_tokens, max_seconds=rt.goal.max_seconds)
            rt.save()

    def work(self):
        while True:
            command = self.commands.get()
            if command is None:
                break
            try:
                action = command.get("action", "send")
                if action not in ("send", "continue"):
                    self.control(command)
                    continue
                self.busy, self.phase = True, "准备上下文"
                self.publish("busy", busy=True, phase=self.phase)
                if action == "continue":
                    if not self.runtime.goal:
                        raise ValueError("还没有可继续的目标")
                    self.runtime.set_mode("goal")
                    self.run_answer(continuation=True)
                else:
                    text = command.get("text", "").strip()
                    if not text:
                        raise ValueError("请先输入问题或目标")
                    if self.runtime.state["title"] == "新对话":
                        self.runtime.state["title"] = text.splitlines()[0][:40]
                    mode = command.get("mode", self.runtime.mode)
                    self.runtime.set_mode(mode)
                    if mode == "goal" and (not self.runtime.goal or self.runtime.goal.status in ("completed", "cancelled")):
                        limits = command.get("limits") or {}
                        self.runtime.start_goal(text, max_steps=int(limits.get("max_steps", 100)),
                                                max_cost=float(limits.get("max_cost", .5)),
                                                max_seconds=float(limits.get("max_seconds", 3600)),
                                                max_tokens=int(limits.get("max_tokens", 0)))
                    if command.get("depth"):
                        self.runtime.set_depth(command["depth"])
                    self.run_answer(text, client_id=command.get("client_id"), announced=command.get("announced", False))
                self.drain()
            except Exception as exc:
                self.publish("error", message=str(exc), error_type=type(exc).__name__)
            finally:
                self.busy = False
                self.phase = "准备就绪"
                self.current_turn = None
                self.runtime.save()
                self.publish("busy", busy=False, phase=self.phase)
        self.runtime.close()
        self.closed = True

    def close(self):
        self.runtime.cancel()
        self.commands.put(None)


class WebHub:
    def __init__(self, default_workspace, model_factory=StreamingModel):
        self.default_workspace = default_workspace
        self.model_factory = model_factory
        self.sessions = {}
        self.lock = threading.Lock()

    def get(self, workspace, session_id=None, *, new=False, select=False):
        from pathlib import Path
        workspace = Path(workspace).resolve()
        if not workspace.is_dir():
            raise ValueError("工作目录不存在，请选择已有文件夹")
        key = (str(workspace).casefold(), session_id)
        with self.lock:
            if not new and session_id and key in self.sessions:
                if select:
                    self.sessions[key].runtime.store.select()
                return self.sessions[key]
            # Selecting a workspace without an explicit ID chooses its last conversation.
            if not new and not session_id:
                from .conversation import ConversationStore
                session_id = ConversationStore.selected(workspace)
                if session_id:
                    key = (str(workspace).casefold(), session_id)
                    if key in self.sessions:
                        return self.sessions[key]
            session = WebSession(workspace, session_id=session_id, new=new, model_factory=self.model_factory)
            self.sessions[(str(workspace).casefold(), session.id)] = session
            if select or new:
                session.runtime.store.select()
            return session

    def close(self):
        for session in list(self.sessions.values()):
            session.close()
        for session in list(self.sessions.values()):
            session.thread.join(timeout=5)
