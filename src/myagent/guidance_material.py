"""Read explicitly selected guidance as page- or slide-anchored text."""
from __future__ import annotations

import codecs
import hashlib
import io
import json
import os
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from threading import Lock

from .jobs import atomic_json
from .word_material import WORD, word_pages

SLIDES = {'.ppt', '.pptx'}
IMAGE_GUIDES = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'}
_ocr_lock = Lock()


class GuidanceReadError(ValueError):
    pass


def pdf_pages(path):
    import fitz

    with fitz.open(path) as pdf:
        return [{'page': i, 'text': page.get_text()} for i, page in enumerate(pdf, 1)]


@lru_cache(maxsize=1)
def _ocr_engine():
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise ValueError('本机缺少图片文字识别组件，请用最新版启动脚本安装组件后重试。') from exc
    return RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)


def image_text(source):
    import numpy as np
    from PIL import Image, ImageOps

    with Image.open(source) as original:
        rgba = ImageOps.exif_transpose(original).convert('RGBA')
    background = Image.new('RGBA', rgba.size, 'white')
    rgb = Image.alpha_composite(background, rgba).convert('RGB')
    bgr = np.ascontiguousarray(np.asarray(rgb)[:, :, ::-1])
    with _ocr_lock:
        rows, _ = _ocr_engine()(bgr)
    return '\n'.join(text for _, text, _ in rows or [])


def _legacy_slides(path):
    if os.name != 'nt':
        raise ValueError('旧版 PPT 需要 Windows 上的 PowerPoint，也可另存为 PPTX。')
    with tempfile.TemporaryDirectory(prefix='paperfox-slides-') as folder:
        output = Path(folder) / 'slides.json'
        script = Path(__file__).with_name('read_powerpoint.ps1').read_text(encoding='utf8')
        env = {**os.environ, 'PAPERFOX_PPT_INPUT': str(path), 'PAPERFOX_PPT_OUTPUT': str(output)}
        try:
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                    env=env, capture_output=True, timeout=45,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired as exc:
            raise ValueError('PowerPoint 读取旧版 PPT 超时，请另存为 PPTX。') from exc
        if result.returncode or not output.is_file():
            raise ValueError('无法在 PowerPoint 的受保护视图读取旧版 PPT，请另存为 PPTX 或 PDF。')
        return json.loads(output.read_text(encoding='utf-8-sig'))


def _slide_shapes(shapes):
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    for shape in sorted(shapes, key=lambda item: (item.top, item.left)):
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _slide_shapes(shape.shapes)
        else:
            yield shape


def slide_pages(path):
    if path.suffix.lower() == '.ppt':
        slides = _legacy_slides(path)
    else:
        from PIL import UnidentifiedImageError
        from pptx import Presentation

        slides = []
        for slide in Presentation(path).slides:
            text = []
            for shape in _slide_shapes(slide.shapes):
                if shape.has_text_frame and shape.text.strip():
                    text.append(shape.text)
                elif shape.has_table:
                    text.extend('\t'.join(cell.text for cell in row.cells) for row in shape.table.rows)
                elif hasattr(shape, 'image'):
                    try:
                        text.append(image_text(io.BytesIO(shape.image.blob)))
                    except UnidentifiedImageError:
                        continue
            slides.append('\n'.join(part for part in text if part.strip()))
    return [{'page': i, 'text': text, 'anchor_type': 'slide'} for i, text in enumerate(slides, 1)]


def _plain_text_pages(path):
    with path.open('rb') as stream:
        raw = stream.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError('纯文本指导书过大，请选取所需内容或另存为可读文档。')
    encoding = 'utf-16' if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) else 'utf-8-sig'
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError as exc:
        raise ValueError('无法识别文件格式或编码。可换成 PPTX、PDF、Word、常见图片或 UTF-8 文本。') from exc
    if any(not char.isprintable() and not char.isspace() for char in text):
        raise ValueError('该文件没有可直接读取的正文。可换成 PPTX、PDF、Word、常见图片或 UTF-8 文本。')
    return [{'page': i // 6000 + 1, 'text': text[i:i+6000], 'anchor_type': 'text_part'}
            for i in range(0, len(text), 6000)]


def guidance_pages(path, cache, *, name=None):
    """Keep OCR and presentation results separate from the untouched source."""
    path = Path(path)
    name = name or path.name
    suffix = path.suffix.lower()
    dest = None
    try:
        if suffix in WORD:
            pages = word_pages(path, cache)
        elif suffix == '.pdf':
            pages = pdf_pages(path)
            if not any(page['text'].strip() for page in pages):
                raise ValueError('这是扫描件。可以选用截图、照片、带正文的 Word 或经过 OCR 的 PDF。')
        elif suffix in IMAGE_GUIDES | SLIDES:
            sha = hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    sha.update(chunk)
            dest = Path(cache) / f'guide-v1-{suffix[1:]}-{sha.hexdigest()}.json'
            if dest.is_file():
                return json.loads(dest.read_text(encoding='utf8'))
            pages = slide_pages(path) if suffix in SLIDES else [
                {'page': 1, 'text': image_text(path), 'anchor_type': 'image_ocr'}]
        else:
            pages = _plain_text_pages(path)
        if not any(page['text'].strip() for page in pages):
            raise ValueError('文件没有可读取的正文，请换一份内容清晰的指导书。')
        if dest is not None:
            dest.parent.mkdir(parents=True, exist_ok=True)
            atomic_json(dest, pages)
        return pages
    except Exception as exc:
        reason = str(exc) if type(exc) is ValueError else '文件损坏、受保护，或本机缺少相应的读取组件。'
        raise GuidanceReadError(f'无法读取指导书「{name}」。{reason}') from exc
