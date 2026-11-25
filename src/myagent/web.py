"""Local Wisdom Tree frontend; standard-library server, existing agent runtime."""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import Config
from . import paperfox_setup
from .conversation import ConversationStore
from .tools.base import resolve_workspace_path
from .web_session import WebHub

STATIC = Path(__file__).parent / "web_static"
SERVICE = "myagent-wisdom-tree"


class WisdomServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, hub):
        self.hub = hub
        from .lab_web import LabHub
        self.lab = LabHub()
        super().__init__(address, WisdomHandler)


class WisdomHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def response(self, data, status=200, mime="application/json; charset=utf-8", download=None):
        raw = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        if download:
            self.send_header('Content-Disposition', 'attachment; filename="download"; filename*=UTF-8\'\''+urllib.parse.quote(str(download),safe=''))
        self.end_headers()
        self.wfile.write(raw)

    def params(self):
        url = urllib.parse.urlsplit(self.path)
        return url.path, {k:v[0] for k,v in urllib.parse.parse_qs(url.query).items()}

    def workspace(self, params):
        if paperfox_setup.settings_path() is not None:
            return self.server.hub.default_workspace
        path = Path(params.get("workspace") or self.server.hub.default_workspace).resolve()
        if not path.is_dir():
            raise ValueError("工作目录不存在")
        return path

    def portable_route(self, route, *, write=False):
        if paperfox_setup.settings_path() is None:
            return True
        expected_host = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") != expected_host:
            return False
        if route.startswith("/api/lab/studio/"):
            return True
        if write:
            return route in {"/api/pick", "/api/paperfox/setup", "/api/shutdown", "/api/lab/start", "/api/lab/pause",
                             "/api/lab/report/discussion", "/api/lab/report/memory"}
        return route in {"/", "/studio", "/api/health", "/api/paperfox/setup", "/api/lab/file",
                         "/api/lab/bundle", "/api/lab/state", "/api/lab/report/editor", "/api/lab/report/state", "/api/lab/report/discussions",
                         "/api/lab/report/discussion", "/api/lab/report/memory"} or route.endswith(
                             (".css", ".js", ".svg"))

    def do_GET(self):
        try:
            route, params = self.params()
            if not self.portable_route(route):
                return self.response({"error": "此入口在纸狐测试版不可用"}, 404)
            hub = self.server.hub
            assets = {"/": "studio.html", "/chat": "index.html", "/app.css": "app.css", "/app.js": "app.js", "/tree.svg": "tree.svg",
                      "/lab": "report.html", "/legacy-lab": "lab.html", "/lab.css": "lab.css", "/lab.js": "lab.js",
                      "/report":"report.html","/report.js":"report.js","/report.css":"report.css",
                      "/studio":"studio.html","/studio.js":"studio.js","/studio.css":"studio.css",
                      "/studio-workbench.js":"studio-workbench.js","/studio-workbench.css":"studio-workbench.css",
                      "/fox-scene.js":"fox-scene.js","/fox-motion.js":"fox-motion.js","/three.min.js":"three.min.js",
                      "/paperfox.svg":"paperfox.svg"}
            if route in assets:
                path = STATIC/assets[route]
                self.response(path.read_bytes(), mime=(mimetypes.guess_type(path.name)[0] or "text/plain")+"; charset=utf-8")
            elif route == '/api/lab/file':
                from .lab_project import LabProject
                path = LabProject(self.workspace(params), params['project']).file(params['path'])
                mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
                if mime.startswith('text/') or mime == 'application/json':
                    mime += '; charset=utf-8'
                self.response(path.read_bytes(), mime=mime, download=path.name if params.get('download')=='1' else None)
            elif route.startswith('/api/lab/'):
                from .lab_web import get_lab
                result = get_lab(self.server.lab, self.workspace(params), route, params)
                self.response(result, mime='application/zip' if route == '/api/lab/bundle' else 'application/json; charset=utf-8',
                    download='paperfox-'+params['project']+'.zip' if route=='/api/lab/bundle' else None)
            elif route == "/api/health":
                with hub.lock:
                    busy = [s.id for s in hub.sessions.values() if s.busy]
                self.response({"service": SERVICE, "workspace": str(hub.default_workspace), "pid": os.getpid(),
                               "busy_sessions": busy, "busy_experiments": self.server.lab.busy(),
                               "tool_profile": "skills", "lab_version": 1})
            elif route == "/api/paperfox/setup":
                self.response(paperfox_setup.setup_state())
            elif route == "/api/bootstrap":
                ws = self.workspace(params)
                config = Config.from_env(workspace=ws)
                self.response({"workspace": str(ws), "model": config.model, "configured": bool(config.api_key),
                               "sessions": ConversationStore.list(ws), "selected_session_id": ConversationStore.selected(ws)})
            elif route == "/api/sessions":
                self.response(ConversationStore.list(self.workspace(params)))
            elif route == '/api/export':
                from .conversation_export import export_conversation
                data = export_conversation(self.workspace(params), params['session'])
                raw = json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Content-Disposition', f'attachment; filename="conversation-{data["session_id"]}.json"')
                self.send_header('Content-Length',str(len(raw)))
                self.send_header('Cache-Control','no-store')
                self.end_headers()
                self.wfile.write(raw)
            elif route == "/api/session":
                session = hub.get(self.workspace(params), params.get("session"), select=True)
                self.response(session.snapshot())
            elif route == "/api/events":
                session = hub.get(self.workspace(params), params["session"])
                cursor = int(self.headers.get("Last-Event-ID") or params.get("after", 0))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                while not session.closed:
                    with session.condition:
                        stale = (cursor > session.sequence or
                                 (params.get("stream") and params["stream"] != session.stream_id) or
                                 (session.events and cursor < session.events[0]["id"]-1))
                        if stale:
                            snapshot = session.snapshot()
                        rows = [e for e in session.events if e["id"] > cursor]
                        if not rows and not stale:
                            session.condition.wait(15)
                            rows = [e for e in session.events if e["id"] > cursor]
                    if stale:
                        payload = json.dumps({"kind":"resync", "snapshot":snapshot}, ensure_ascii=False)
                        self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        self.close_connection = True
                        return
                    if not rows:
                        self.wfile.write(b": alive\n\n")
                    for event in rows:
                        cursor = event["id"]
                        payload = json.dumps(event, ensure_ascii=False)
                        self.wfile.write(f"id: {cursor}\ndata: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
            elif route == "/api/files":
                ws = self.workspace(params)
                root = resolve_workspace_path(ws, params.get("path", "."))
                rows = []
                for path in sorted(root.iterdir(), key=lambda p:(p.is_file(),p.name.casefold())):
                    try:
                        resolve_workspace_path(ws, str(path))
                    except ValueError:
                        continue
                    if path.name in ("__pycache__", ".venv", "node_modules"):
                        continue
                    if params.get("q", "").casefold() not in path.name.casefold():
                        continue
                    rows.append({"name": path.name, "path": str(path.relative_to(ws)), "directory": path.is_dir(),
                                 "size": path.stat().st_size if path.is_file() else 0})
                self.response({"path": str(root.relative_to(ws)), "files": rows[:250],
                               "total":len(rows), "truncated":len(rows)>250})
            elif route == "/api/file":
                path = resolve_workspace_path(self.workspace(params), params["path"])
                if path.stat().st_size > 20_000_000:
                    raise ValueError("文件较大，请在本地应用中打开")
                mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                if path.suffix.lower() in (".md", ".py", ".jsonl", ".yaml", ".yml", ".toml", ".log", ".cmd"):
                    mime = "text/plain"
                if mime.startswith("text/") or mime == "application/json":
                    mime += "; charset=utf-8"
                self.response(path.read_bytes(), mime=mime)
            else:
                self.response({"error":"页面不存在"},404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as exc:
            self.response({"error":str(exc)},400)

    def do_POST(self):
        try:
            origin = self.headers.get("Origin")
            if origin and urllib.parse.urlsplit(origin).netloc != self.headers.get("Host"):
                raise ValueError("请从本机纸狐页面发起操作")
            route, params = self.params()
            if not self.portable_route(route, write=True):
                return self.response({"error": "此入口在纸狐测试版不可用"}, 404)
            size = int(self.headers.get("Content-Length", 0))
            if route=='/api/lab/studio/upload':
                from .studio_workspace import receive_upload
                self.response(receive_upload(self.workspace(params),params,self.rfile,size))
                return
            if size > 2_000_000:
                raise ValueError("输入过长")
            data = json.loads(self.rfile.read(size) or b"{}")
            if route == "/api/paperfox/setup":
                self.response(paperfox_setup.save_api_key(data.get("api_key"), data.get("connection", "system")))
            elif route.startswith('/api/lab/'):
                from .lab_web import post_lab
                if route in ("/api/lab/studio/create", "/api/lab/start") and paperfox_setup.settings_path() is not None:
                    if not paperfox_setup.api_key():
                        raise ValueError("请先配置 DeepSeek API Key")
                    if route == "/api/lab/studio/create":
                        data["mode"] = "report"
                        data.pop("interpreter_id", None)
                    else:
                        from .lab_project import LabProject
                        project = LabProject(self.workspace(data), data["project"])
                        if project.data.get("studio", {}).get("mode") != "report":
                            raise ValueError("测试版只支持继续根据材料写作的项目")
                        data["action"] = "studio"
                self.response(post_lab(self.server.lab, self.workspace(data), route, data))
            elif route == "/api/pick":
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost",True)
                try:
                    initial = data.get("initialdir") or data.get("workspace")
                    if data.get("kind") == "folder":
                        selected = filedialog.askdirectory(title="选择实验材料目录", initialdir=initial, mustexist=True)
                    elif data.get("kind") == "guidance":
                        selected = filedialog.askopenfilename(title="选择实验指导书", initialdir=initial,
                                    filetypes=[("实验指导书", "*.pdf *.doc *.docx")])
                    else:
                        selected = filedialog.askopenfilename(title="选择要引用的项目文件", initialdir=initial)
                finally:
                    root.destroy()
                self.response({"path":selected})
            elif route == "/api/new":
                session = self.server.hub.get(self.workspace(data), new=True)
                self.response(session.snapshot())
            elif route == "/api/action":
                session = self.server.hub.get(self.workspace(data), data["session"])
                session.submit(data)
                self.response({"accepted":True})
            elif route == "/api/shutdown":
                if self.server.lab.busy():
                    raise ValueError('实验正在运行，请先暂停再关闭服务')
                self.server.lab.close()
                self.response({"stopping":True})
                threading.Thread(target=self.server.shutdown,daemon=True).start()
            else:
                self.response({"error":"操作不存在"},404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self.response({"error":str(exc)},400)


def cmd_web(args):
    workspace = Path(args.workspace).resolve()
    if not workspace.is_dir():
        print("工作文件夹不存在")
        return 2
    url = f"http://127.0.0.1:{args.port}"
    page = getattr(args, 'page', '/')
    if page not in ('/', '/studio', '/report', '/chat'):
        raise ValueError('未知启动页面')
    launch_url = url + page + '?' + urllib.parse.urlencode({'workspace': str(workspace)})
    try:
        with urllib.request.urlopen(url+"/api/health", timeout=1) as r:
            existing = json.load(r)
        if existing.get("service") == SERVICE:
            if args.open_browser:
                webbrowser.open(launch_url)
            print(f"纸狐已在运行：{launch_url}")
            return 0
    except (OSError, ValueError):
        pass
    server = WisdomServer(("127.0.0.1", args.port), WebHub(workspace))
    print(f"纸狐 Agent: {launch_url}", flush=True)
    if args.open_browser:
        webbrowser.open(launch_url)
    try:
        server.serve_forever(poll_interval=.3)
    except KeyboardInterrupt:
        pass
    finally:
        server.lab.close()
        server.hub.close()
        server.server_close()
    return 0


def register_web_command(sub):
    parser = sub.add_parser("web", help="open the Wisdom Tree desktop web interface")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--page", choices=('/', '/studio', '/report', '/chat'), default='/')
    parser.add_argument("--open", dest="open_browser", action="store_true")
    parser.set_defaults(func=cmd_web)
