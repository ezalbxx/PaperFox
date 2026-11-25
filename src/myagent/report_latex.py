"""LaTeX (Tectonic) report renderer.

Single public entry point: ``render_latex``.  All geometry values are PDF
points; TeX receives them as ``bp``.  Nothing here mutates document content:
text is escaped, images are copied verbatim, numbers are untouched.
"""

from __future__ import annotations

import hashlib
import os
import re
import copy
import shutil
import subprocess
import tempfile
from pathlib import Path

DEFAULT_MARGINS = {"left": 56.0, "right": 56.0, "top": 44.0, "bottom": 48.0}
DEFAULT_PAGE = [595.28, 841.89]
DEFAULT_FIELDS = {}
COMPILE_TIMEOUT = 300

_TEX_SPECIALS = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "&": r"\&",
    "#": r"\#",
    "^": r"\textasciicircum{}",
    "_": r"\_",
    "%": r"\%",
    "~": r"\textasciitilde{}",
}
_ESCAPE_RE = re.compile(r"[\\{}$&#^_%~]")
_CN_NUM = "一二三四五六七八九十"


def _esc(value) -> str:
    """Escape every TeX special character in arbitrary source text."""
    if value is None:
        return ""
    return _ESCAPE_RE.sub(lambda m: _TEX_SPECIALS[m.group(0)], str(value))


def _num(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _label(block_id: str) -> str:
    digest = hashlib.sha1(str(block_id).encode("utf-8")).hexdigest()[:10]
    return "bf" + digest


def _has_cn_number(heading: str) -> bool:
    head = heading.lstrip()
    return bool(re.match(r"^[%s]+[、.．]" % _CN_NUM, head))


def _preamble(template: dict, layout: dict, bundled_fonts=False) -> str:
    margins = dict(DEFAULT_MARGINS)
    margins.update({k: _num(v, DEFAULT_MARGINS[k]) for k, v in (template.get("margins") or {}).items()})
    page = template.get("page_size") or DEFAULT_PAGE
    width = _num(page[0] if len(page) > 0 else None, DEFAULT_PAGE[0])
    height = _num(page[1] if len(page) > 1 else None, DEFAULT_PAGE[1])
    body = _num(template.get("body_font_size"), 12.0)
    heading = _num(template.get("heading_font_size"), 16.0)
    h2 = _num(layout.get("heading2_font_size"), 14.0)
    leading = _num(layout.get("body_leading_factor"), 1.5)
    indent = _num(layout.get("first_line_indent_chars"), 2.0)
    space_after = _num(layout.get("paragraph_space_after"), 0.0)
    caption = _num(layout.get("caption_font_size"), 10.5)
    table_font = _num(layout.get("table_font_size"), 10.5)
    img_h = _num(layout.get("image_max_height"), 300.0)
    return "\n".join(
        [
            r"\documentclass[UTF8,zihao=-4]{article}",
            r"\usepackage[a4paper,paperwidth=%.2fbp,paperheight=%.2fbp,"
            r"left=%.2fbp,right=%.2fbp,top=%.2fbp,bottom=%.2fbp]{geometry}"
            % (width, height, margins["left"], margins["right"], margins["top"], margins["bottom"]),
            r"\usepackage{fontspec}",
            r"\usepackage{xeCJK}",
            r"\usepackage{graphicx}",
            r"\usepackage{longtable}",
            r"\usepackage{array}",
            r"\usepackage{needspace}",
            r"\usepackage{fvextra}",
    r"\usepackage{indentfirst}",
    r"\usepackage{xcolor}",
            r"\usepackage[hidelinks]{hyperref}",
            r"\IfFontExistsTF{Times New Roman}{\setmainfont{Times New Roman}}{\setmainfont{Latin Modern Roman}}",
            r"\IfFontExistsTF{Consolas}{\setmonofont{Consolas}}{\setmonofont{Latin Modern Mono}}",
            *(
                [r"\IfFontExistsTF{SimSun}{\IfFontExistsTF{SimHei}{\def\PaperFoxWindowsFonts{1}}{}}{}",
                 r"\ifdefined\PaperFoxWindowsFonts"]
                if bundled_fonts else []
            ),
            r"\setCJKmainfont[BoldFont=SimHei]{SimSun}",
            r"\setCJKsansfont{SimHei}",
            r"\setCJKmonofont{SimSun}",
            r"\newCJKfontfamily\heiti{SimHei}",
            r"\newCJKfontfamily\songti{SimSun}",
            *(
                [r"\else",
                 r"\setCJKmainfont[BoldFont=PaperFoxSans.otf]{PaperFoxSerif.otf}",
                 r"\setCJKsansfont{PaperFoxSans.otf}",
                 r"\setCJKmonofont{PaperFoxSerif.otf}",
                 r"\newCJKfontfamily\heiti{PaperFoxSans.otf}",
                 r"\newCJKfontfamily\songti{PaperFoxSerif.otf}",
                 r"\fi"]
                if bundled_fonts else []
            ),
            r"\setlength{\parindent}{%.2fbp}" % (body * indent),
            r"\setlength{\parskip}{%.2fbp}" % space_after,

            r"\setlength{\LTpre}{6bp}\setlength{\LTpost}{6bp}",
            r"\renewcommand{\arraystretch}{1.25}",
            r"\makeatletter",
            r"\renewcommand\section{\@startsection{section}{1}{\z@}"
            r"{-12bp \@plus -3bp \@minus -2bp}{6bp}"
            r"{\normalfont\heiti\fontsize{%.2fbp}{%.2fbp}\selectfont}}"
            % (heading, heading * 1.4),
            r"\renewcommand\subsection{\@startsection{subsection}{2}{\z@}"
            r"{-10bp \@plus -3bp \@minus -2bp}{5bp}"
            r"{\normalfont\heiti\fontsize{%.2fbp}{%.2fbp}\selectfont}}"
            % (h2, h2 * 1.4),
            r"\makeatother",
            r"\newcommand{\bfcaption}[1]{\par\vspace{3bp}{\centering\songti"
            r"\fontsize{%.2fbp}{%.2fbp}\selectfont #1\par}}" % (caption, caption * 1.35),
            r"\newcommand{\bfimgmax}{%.2fbp}" % img_h,
            r"\newcommand{\bftablefont}{\fontsize{%.2fbp}{%.2fbp}\selectfont}" % (table_font, table_font * 1.3),
            r"\newcommand{\bfneed}[1]{\needspace{#1\baselineskip}}",
            r"\begin{document}",
            r"\fontsize{%.2fbp}{%.2fbp}\selectfont" % (body, body * leading),
            r"\setlength{\parindent}{%.2fbp}" % (body * indent),
        ]
    )


def _image_tex(path: str, caption: str, max_h: float) -> str:
    parts = [
        r"\begin{center}",
        r"\includegraphics[width=\linewidth,height=\bfimgmax,keepaspectratio]{%s}" % path,
        r"\end{center}",
    ]
    if caption:
        parts.append(r"\bfcaption{%s}" % _esc(caption))
    return "\n".join(parts)


def _table_tex(block: dict, width: float) -> str:
    headers = [str(h) for h in (block.get("headers") or [])]
    rows = block.get("rows") or []
    cols = max([len(headers)] + [len(r) for r in rows] + [1])
    col_w = (width - (cols + 1) * 0.4) / cols - 12.0
    spec = "|" + "|".join("p{%.2fbp}" % col_w for _ in range(cols)) + "|"
    out = [r"\begingroup\bftablefont", r"\begin{longtable}{%s}" % spec]
    if headers:
        head = " & ".join(r"\textbf{%s}" % _esc(h) for h in headers)
        out.append(r"\hline")
        out.append(head + r" \\ \hline")
        out.append(r"\endfirsthead")
        out.append(r"\hline")
        out.append(head + r" \\ \hline")
        out.append(r"\endhead")
    out.append(r"\hline")
    out.append(r"\endlastfoot")
    for row in rows:
        cells = [_esc(c) for c in row] + [""] * (cols - len(row))
        out.append(" & ".join(cells) + r" \\ \hline")
    out.append(r"\end{longtable}")
    caption = block.get("caption")
    if caption:
        out.append(r"\bfcaption{%s}" % _esc(caption))
    out.append(r"\endgroup")
    return "\n".join(out)


def _code_tex(block: dict, workdir: Path, index: int) -> str:
    text = block.get("text") or ""
    name = "code_%s.txt" % _label(block.get("id", index))  # cross-chapter unique, filesystem-safe
    (workdir / name).write_text(str(text), encoding="utf-8")
    return "\n".join(
        [
            r"\begin{quote}",
            r"\begingroup",
            r"\fontsize{10bp}{13bp}\selectfont",
            r"\VerbatimInput["
            r"fontsize=\fontsize{10bp}{13bp}\selectfont,"
            r"frame=single,"
            r"rulecolor=\color{gray!50},"
            r"framesep=5bp,"
            r"xleftmargin=12bp,"
            r"xrightmargin=12bp,"
            r"tabsize=4,"
            r"obeytabs=true,"
            r"breaklines=true,"
            r"breakanywhere=true,"
            r"breaksymbolleft={},"
            r"breaksymbolright={}"
            r"]{%s}" % name,
            r"\endgroup",
            r"\end{quote}",
        ]
    )


def _block_tex(block: dict, layout: dict, workdir: Path, index: int, width: float) -> str:
    kind = block.get("type")
    label = _label(block.get("id", "b%d" % index))
    if kind == "heading":
        return r"\bfneed{3}\subsection*{%s}\phantomsection\label{%s}" % (_esc(block.get("text")), label)
    if kind == "image":
        return r"\phantomsection\label{%s}" % label + "\n" + _image_tex(
            block.get("path", ""), block.get("caption") or "", 0.0
        )
    if kind == "table":
        return r"\phantomsection\label{%s}" % label + "\n" + _table_tex(block, width)
    if kind == "list":
        items = block.get("items") or []
        body = "\n".join(r"\item %s" % _esc(i) for i in items)
        return r"\phantomsection\label{%s}" % label + "\n" + "\\begin{enumerate}\n%s\n\\end{enumerate}" % body
    if kind == "code":
        return r"\phantomsection\label{%s}" % label + "\n" + _code_tex(block, workdir, index)
    text = block.get("text") or ""
    return r"\phantomsection\label{%s}" % label + "\n" + _esc(text) + "\n"


def _grouped_tex(blocks: list, layout: dict, workdir: Path, width: float) -> str:
    by_id = {str(b.get("id")): b for b in blocks}
    # 首块ID -> 配对成员列表（按 layout 中给出的顺序）
    # 说明：遍历 blocks 原顺序，前后正文不挪动；仅配对首块处输出并排一行。
    pair_head: dict = {}
    # 所有作为配对尾部的块ID
    pair_tail: set = set()
    # 配对尾部ID集合用于跳过已配对尾部。
    for group in layout.get("image_groups") or []:
        ids = [str(i) for i in (group.get("block_ids") or [])]
        members = [by_id[i] for i in ids if i in by_id and by_id[i].get("type") == "image"]
        if len(members) < 2:
            continue
        head_id = str(members[0].get("id"))
        if head_id in pair_head:
            continue
        pair_head[head_id] = members
        for m in members[1:]:
            pair_tail.add(str(m.get("id")))

    out: list = []
    for index, block in enumerate(blocks):
        bid = str(block.get("id"))
        if bid in pair_tail:
            # 已作为配对尾部输出，跳过
            continue
        members = pair_head.get(bid)
        if members:
            # 配对首块：输出并排一行，左右各自独立 minipage
            sub = max(width / len(members) - 8.0, 40.0)
            cells = []
            for m in members:
                mid = str(m.get("id"))
                page = m.get("page")
                page_tex = "" if page is None else r"\textsuperscript{%s}" % _esc(str(page))
                cap = m.get("caption")
                cap_tex = r"\bfcaption{%s}" % _esc(str(cap)) if cap else ""
                cells.append(
                    r"\begin{minipage}[t]{%.2fbp}\centering"
                    r"\phantomsection\label{%s}"
                    r"\includegraphics[width=\linewidth,height=\bfimgmax,keepaspectratio]{%s}"
                    r"%s%s"
                    r"\end{minipage}" % (sub, _label(mid), m.get("path", ""), page_tex, cap_tex)
                )
            out.append(r"\begin{center}" + r"\hfill".join(cells) + r"\end{center}")
            continue
        out.append(_block_tex(block, layout, workdir, index, width))
    return "\n\n".join(out)


def _document_tex(project, display_document: dict, template: dict, layout: dict, workdir: Path) -> str:
    margins = dict(DEFAULT_MARGINS)
    margins.update({k: _num(v, DEFAULT_MARGINS[k]) for k, v in (template.get("margins") or {}).items()})
    page = template.get("page_size") or DEFAULT_PAGE
    width = _num(page[0] if len(page) > 0 else None, DEFAULT_PAGE[0]) - margins["left"] - margins["right"]
    number_sub = bool(layout.get("number_subheadings", True))
    fields = template.get("fields") or DEFAULT_FIELDS
    student = project.data.get("student") or {}
    values = {
        "student_id": project.data.get("student_id", ""),
        "name": student.get("name", ""),
        "student_name": student.get("name", ""),
        "class": student.get("class", ""),
        "major": student.get("major", ""),
    }
    body: list = []
    title = display_document.get("title") or ""
    if title:
        title_size = getattr(getattr(template, "typography", None), "title_font_size", None) or 20.5
        body.append(r"\begin{center}{\heiti\fontsize{%sbp}{%sbp}\selectfont %s\par}\end{center}" % (title_size, title_size * 1.35, _esc(title)))
    identity = []
    for key, label in fields.items():
        value = values.get(str(key), values.get(str(label), ""))
        if value in ("", None):
            continue
        identity.append(r"\textbf{%s}：%s" % (_esc(label), _esc(value)))
    if identity:
        body.append(r"\begin{center}%s\par\end{center}" % r"\quad ".join(identity))
    for section_index, section in enumerate(display_document.get("sections") or [], 1):
        heading = str(section.get("heading") or "")
        if not re.search(r"[一二三四五六七八九十0-9]", heading):
            if section_index <= 10:
                heading = _CN_NUM[section_index - 1] + "、" + heading
            else:
                heading = f"{section_index}、" + heading
        if heading:
            if _has_cn_number(heading):
                body.append(r"\bfneed{3}\section*{%s}" % _esc(heading))
            else:
                body.append(r"\bfneed{3}\section{%s}" % _esc(heading))
        blocks = section.get("blocks") or []
        numbered_blocks = []
        heading_index = 0
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "heading":
                heading_index += 1
                if number_sub:
                    block = dict(block)
                    block["text"] = f"{section_index}.{heading_index} " + str(block.get("text") or "")
            numbered_blocks.append(block)
        body.append(_grouped_tex(numbered_blocks, layout, workdir, width))
    bundled_fonts = (workdir / "PaperFoxSerif.otf").is_file()
    return _preamble(template, layout, bundled_fonts) + "\n" + "\n\n".join(body) + "\n\\end{document}\n"


def _parse_aux(aux: Path) -> dict:
    pages: dict = {}
    if not aux.exists():
        return pages
    pattern = re.compile(r"\\newlabel\{([^}]*)\}\{\{([^{}]*)\}\{([^{}]*)\}")
    for match in pattern.finditer(aux.read_text(encoding="utf-8", errors="replace")):
        name, _number, page = match.group(1), match.group(2), match.group(3)
        try:
            pages[name] = int(page)
        except ValueError:
            continue
    return pages


def render_latex(project, display_document, template, layout, output_pdf):
    """Render ``display_document`` to ``output_pdf``; return (block_pages, metadata)."""
    template = template or {}
    layout = layout or {}
    output_pdf = Path(output_pdf)
    root = Path(project.root)
    root.mkdir(parents=True, exist_ok=True)
    metadata = {"backend": "latex", "engine": "tectonic", "log": ""}
    with tempfile.TemporaryDirectory(prefix="latex_", dir=str(root)) as tmp:
        workdir = Path(tmp)
        font_dir = os.environ.get("PAPERFOX_TEX_FONTS")
        if font_dir:
            for name in ("PaperFoxSerif.otf", "PaperFoxSans.otf"):
                shutil.copyfile(Path(font_dir) / name, workdir / name)
        # Deep-copy the display document so image path rewrites stay local.
        compile_document = copy.deepcopy(display_document)
        _allowed_image_suffixes = {".png", ".jpg", ".jpeg", ".pdf"}
        _image_index = 0
        for _block in (block for section in compile_document.get("sections", []) for block in section.get("blocks", [])):
            if not isinstance(_block, dict) or _block.get("type") != "image":
                continue
            _raw_path = _block.get("path")
            if not _raw_path:
                continue
            _source = project.file(_raw_path)
            _suffix = Path(_raw_path).suffix.lower()
            if _suffix not in _allowed_image_suffixes:
                raise RuntimeError(
                    f"unsupported image extension {_suffix!r} for {_raw_path!r}"
                )
            _image_index += 1
            _safe_name = f"image_{_image_index:03d}{_suffix}"
            _target = Path(workdir) / _safe_name
            shutil.copyfile(_source, _target)
            _block["path"] = _safe_name
        tex = _document_tex(project, compile_document, template, layout, workdir)
        (workdir / "main.tex").write_text(tex, encoding="utf-8")
        argv = [
            "tectonic",
            "--untrusted",
            "--keep-logs",
            "--keep-intermediates",
            "main.tex",
        ]
        try:
            proc = subprocess.run(
                argv,
                cwd=str(workdir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=COMPILE_TIMEOUT,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("tectonic 未安装或不可执行: %s" % exc) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("tectonic 编译超时(%ss)" % COMPILE_TIMEOUT) from exc
        log_text = (proc.stdout or "") + (proc.stderr or "")
        log_file = workdir / "main.log"
        if log_file.exists():
            log_text += "\n" + log_file.read_text(encoding="utf-8", errors="replace")
        metadata["log"] = log_text[-4000:]
        pdf = workdir / "main.pdf"
        if proc.returncode != 0 or not pdf.exists():
            tail = "\n".join(log_text.strip().splitlines()[-12:])
            raise RuntimeError("tectonic 编译失败(rc=%s): %s" % (proc.returncode, tail))
        pages = _parse_aux(workdir / "main.aux")
        block_pages: dict = {}
        for section in display_document.get("sections") or []:
            for block in section.get("blocks") or []:
                name = _label(block.get("id", ""))
                if name in pages:
                    block_pages[str(block.get("id"))] = pages[name]
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pdf, output_pdf)
    metadata["pages"] = max(block_pages.values()) if block_pages else 0
    return block_pages, metadata
