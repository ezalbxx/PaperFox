"""Read Word material without changing the uploaded original."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile
from xml.etree import ElementTree as ET

from .jobs import atomic_json

WORD = {'.doc', '.docx'}
GUIDES = WORD | {'.pdf'}
OLE = bytes.fromhex('d0cf11e0a1b11ae1')


def xml_pages(path):
    """WordprocessingML text, with explicit or last-rendered page breaks when present."""
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read('word/document.xml'))
    ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    pages = [[]]
    for para in root.iter(ns+'p'):
        for node in para.iter():
            if node.tag == ns+'t':
                pages[-1].append(node.text or '')
            elif node.tag == ns+'tab':
                pages[-1].append('\t')
            elif node.tag == ns+'lastRenderedPageBreak' or (node.tag == ns+'br' and node.get(ns+'type') == 'page'):
                if pages[-1]:
                    pages.append([])
            elif node.tag in (ns+'br', ns+'cr'):
                pages[-1].append('\n')
        pages[-1].append('\n')
    # Some editors save no pagination. Keep long guides addressable by text part.
    chunks = []
    for parts in pages:
        text = ''.join(parts).strip()
        while len(text) > 6000:
            end = text.rfind('\n', 3000, 6000)
            if end < 0:
                end = 6000
            chunks.append(text[:end])
            text = text[end:].lstrip('\n')
        chunks.append(text)
    return chunks


def binary_pages(path):
    with tempfile.TemporaryDirectory(prefix='paperfox-word-') as folder:
        source = Path(folder)/'source.doc'
        shutil.copyfile(path, source)
        if os.name == 'nt':
            output = Path(folder)/'pages.json'
            cmd = ['powershell.exe','-NoProfile','-NonInteractive','-Command',
                   Path(__file__).with_name('read_word.ps1').read_text(encoding='utf8')]
            env = {**os.environ,'PAPERFOX_WORD_INPUT':str(source),'PAPERFOX_WORD_OUTPUT':str(output)}
            result = subprocess.run(cmd, env=env, capture_output=True, timeout=90,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode or not output.is_file():
                raise ValueError(f'{path.name}：Word 受保护视图无法读取，请检查本机 Word、文件完整性或加密状态')
            return json.loads(output.read_text(encoding='utf-8-sig'))
        reader = shutil.which('antiword')
        if not reader:
            raise ValueError('读取旧版 DOC 需要本机安装 antiword 或在装有 Word 的 Windows 工作台打开')
        result = subprocess.run([reader,'-m','UTF-8.txt',str(source)],capture_output=True,timeout=90)
        if result.returncode:
            raise ValueError(f'{path.name}：antiword 无法读取旧版 Word 文稿')
        return result.stdout.decode('utf8').split('\f')


def word_pages(path, cache=None):
    path = Path(path)
    if cache is not None:
        key = hashlib.sha256(path.read_bytes()).hexdigest()
        dest = Path(cache)/('word-v2-'+key+'.json')
        if dest.is_file():
            return json.loads(dest.read_text(encoding='utf8'))
    with path.open('rb') as f:
        signature = f.read(8)
    if signature == OLE:
        chunks = binary_pages(path)
        anchor = 'word_page' if os.name=='nt' else 'text_part'
    elif zipfile.is_zipfile(path):
        try:
            chunks = xml_pages(path)
        except (KeyError, ET.ParseError, zipfile.BadZipFile) as exc:
            raise ValueError(f'{path.name} 不是可读取的 DOCX 正文') from exc
        anchor = 'xml_text_part'
    else:
        raise ValueError(f'{path.name} 的内容不是受支持的 DOC 或 DOCX 文件')
    pages = [{'page':i,'text':text,'anchor_type':anchor} for i,text in enumerate(chunks,1)]
    if not any(p['text'].strip() for p in pages):
        raise ValueError(f'{path.name} 没有可提取的正文，请提供可读文字')
    if cache is not None:
        dest.parent.mkdir(exist_ok=True,parents=True)
        atomic_json(dest,pages)
    return pages
