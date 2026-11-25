"""Launch the report-only PaperFox distribution on Windows."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback
import urllib.request
import webbrowser

from myagent.web import SERVICE, WisdomServer
from myagent.web_session import WebHub


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
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

    def open_page(port):
        url = f"http://127.0.0.1:{port}/studio"
        print(url, flush=True)
        if not args.no_browser:
            webbrowser.open(url)

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/api/health", timeout=.4) as response:
            health = json.load(response)
        if health.get("service") == SERVICE and Path(health["workspace"]) == workspace:
            open_page(args.port)
            return
    except (OSError, ValueError, KeyError):
        pass
    hub = WebHub(workspace)
    try:
        server = WisdomServer(("127.0.0.1", args.port), hub)
    except OSError:
        server = WisdomServer(("127.0.0.1", 0), hub)
    try:
        open_page(server.server_port)
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
    except Exception:
        traceback.print_exc()
        if "--self-test" not in sys.argv:
            ctypes.windll.user32.MessageBoxW(None, "纸狐启动失败。请查看本机 PaperFox 目录中的 startup.log。",
                                            "纸狐", 0x10)
        raise SystemExit(1)
