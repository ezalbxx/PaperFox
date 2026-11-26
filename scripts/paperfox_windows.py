"""Launch the report-only PaperFox distribution on Windows."""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import traceback
import urllib.request
import webbrowser

from myagent.web import SERVICE, WisdomServer
from myagent.web_session import WebHub

DESKTOP_TITLE = "纸狐 PaperFox"


class DesktopStartupError(RuntimeError):
    pass


def activate_desktop(pid):
    """Restore the existing PaperFox window for the service that owns this library."""
    user32 = ctypes.WinDLL("user32")
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = (callback, wintypes.LPARAM)
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.IsIconic.argtypes = (wintypes.HWND,)
    user32.ShowWindowAsync.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    user32.FlashWindow.argtypes = (wintypes.HWND, wintypes.BOOL)
    window = None

    @callback
    def find(hwnd, _):
        nonlocal window
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            title = ctypes.create_unicode_buffer(128)
            user32.GetWindowTextW(hwnd, title, len(title))
            if title.value == DESKTOP_TITLE:
                window = hwnd
                return False
        return True

    user32.EnumWindows(find, 0)
    if window is None:
        return False
    if user32.IsIconic(window):
        user32.ShowWindowAsync(window, 9)  # SW_RESTORE
    if not user32.SetForegroundWindow(window):
        user32.FlashWindow(window, True)
    return True


def require_webview_runtime():
    import winreg

    key = r"Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    for hive, view in ((winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY), (winreg.HKEY_CURRENT_USER, 0)):
        try:
            with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as handle:
                version, _ = winreg.QueryValueEx(handle, "pv")
            if version and version != "0.0.0.0":
                return
        except OSError:
            continue
    raise DesktopStartupError("请安装 Microsoft Edge WebView2 Runtime (Evergreen)，然后重新打开纸狐。")


def run_desktop(server, url, state):
    import webview

    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PaperFox.Desktop")
    icon = Path(sys.executable).resolve().with_name("PaperFox.ico")
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["ALLOW_FILE_URLS"] = False
    window = webview.create_window(DESKTOP_TITLE, url, width=1240, height=820, min_size=(420, 500),
                                   text_select=True, background_color="#FFFFFF")
    closing = threading.Event()

    def can_close():
        try:
            server.lab.begin_shutdown()
        except ValueError as exc:
            ctypes.windll.user32.MessageBoxW(None, str(exc), "纸狐 PaperFox", 0x30 | 0x10000)
            return False
        closing.set()
        return True

    def serve_window():
        server.serve_forever(poll_interval=.1)
        if not closing.is_set():
            window.destroy()

    window.events.closing += can_close
    thread = threading.Thread(target=serve_window, name="paperfox-local-service", daemon=True)
    thread.start()
    try:
        webview.start(gui="edgechromium", private_mode=False, storage_path=str(state / "DesktopView"),
                      icon=str(icon) if icon.is_file() else None)
    finally:
        closing.set()
        server.shutdown()
        thread.join(timeout=3)


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--desktop", action="store_true", help="Open an independent desktop window")
    mode.add_argument("--no-browser", action="store_true", help="Start the service only, for local testing")
    parser.add_argument("--port", type=int, default=8786)
    parser.add_argument("--state-dir", type=Path, default=Path(os.environ["LOCALAPPDATA"]) / "PaperFox")
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    state = args.state_dir.resolve()
    state.mkdir(parents=True, exist_ok=True)
    workspace = state / "Reports"
    workspace.mkdir(exist_ok=True)
    os.environ["PAPERFOX_SETTINGS"] = str(state / "deepseek.json")
    os.environ["MYAGENT_WRITING_MEMORY"] = str(state / "writing-memory.json")
    os.environ["MYAGENT_REPORT_STYLE_LIBRARY"] = str(state / "report-style-library.json")
    os.environ["MYAGENT_FIGURE_REFERENCE_LIBRARY"] = str(state / "figure-reference-library")
    app = Path(sys.executable).resolve().parent
    os.environ["PATH"] = str(app / "tectonic") + os.pathsep + os.environ.get("PATH", "")
    if (app / "fonts" / "PaperFoxSerif.otf").is_file():
        os.environ["PAPERFOX_TEX_FONTS"] = str(app / "fonts")
        from matplotlib import font_manager
        font_manager.fontManager.addfont(app / "fonts" / "PaperFoxSans.otf")

    if sys.stdout is None or sys.stderr is None:
        log = (state / "startup.log").open("a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log

    if args.self_test:
        runtime_check(state)
        return
    desktop = args.desktop or (getattr(sys, "frozen", False) and not args.no_browser)
    if desktop:
        require_webview_runtime()

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/api/health", timeout=.4) as response:
            health = json.load(response)
        if health.get("service") == SERVICE and Path(health["workspace"]) == workspace:
            if desktop:
                if activate_desktop(health["pid"]):
                    return
                raise DesktopStartupError("这个报告库的本机服务仍在运行，当前找不到桌面窗口。如果正在启动，请稍候再试。")
            url = f"http://127.0.0.1:{args.port}/studio"
            print(url, flush=True)
            if not args.no_browser:
                webbrowser.open(url)
            return
    except (OSError, ValueError, KeyError):
        pass
    hub = WebHub(workspace)
    try:
        server = WisdomServer(("127.0.0.1", args.port), hub)
    except OSError:
        server = WisdomServer(("127.0.0.1", 0), hub)
    try:
        url = f"http://127.0.0.1:{server.server_port}/studio"
        print(url, flush=True)
        if desktop:
            run_desktop(server, url, state)
        else:
            if not args.no_browser:
                webbrowser.open(url)
            server.serve_forever(poll_interval=.3)
    finally:
        server.lab.close()
        hub.close()
        server.server_close()


def runtime_check(state):
    """Test the installed runtime without using a configured account."""
    from importlib.resources import files
    import fitz
    import tkinter

    from myagent.jobs import atomic_json
    from myagent.lab_project import LabProject
    from myagent.paperfox_setup import _protect
    from myagent.report_workflow import ReportWorkflow

    assert tkinter.Tcl().eval("info patchlevel")
    marker = b"paperfox-local-key-check"
    assert _protect(_protect(marker), decrypt=True) == marker
    with tempfile.TemporaryDirectory(dir=state, prefix="runtime-") as folder:
        workspace = Path(folder)
        guide = workspace / "实验指导书.pdf"
        with fitz.open() as pdf:
            pdf.new_page().insert_text((60, 60), "PaperFox runtime")
            pdf.save(guide)
        project = LabProject.create(workspace, title="纸狐排版自检",
                                    materials=[{"path": str(guide), "role": "guidance"}])
        doc = {"title": "纸狐排版自检", "sections": [{"heading": "实验结果", "blocks": [
            {"id": "heading", "type": "heading", "text": "Lab 1 检查"},
            {"id": "body", "type": "text", "text": "纸狐已读取指导书并排版。"},
            {"id": "code", "type": "code", "text": "value = 12.5\nprint(value)"},
        ]}]}
        template = json.loads(files("myagent").joinpath("default_report_template.json").read_text(encoding="utf-8"))
        project.data["template"] = {**template, "headings": ["实验结果"]}
        report = ReportWorkflow(project).format_report(doc)
        with fitz.open(project.file(report["pdf"])) as pdf:
            text = "".join(page.get_text() for page in pdf)
            assert "纸狐已读取指导书并排版" in text
        atomic_json(state / "runtime-check.json", {
            "backend": report["pdf_backend"]["backend"],
            "fallback_reason": report["pdf_backend"].get("fallback_reason"),
            "block_pages": report["block_pages"], "tcl": True, "dpapi": True,
        })


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        traceback.print_exc()
        if "--self-test" not in sys.argv:
            message = str(exc) if isinstance(exc, DesktopStartupError) else "纸狐启动失败。请查看本机 PaperFox 目录中的 startup.log。"
            ctypes.windll.user32.MessageBoxW(None, message, "纸狐", 0x10)
        raise SystemExit(1)
