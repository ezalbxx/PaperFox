"""Inspectable writing lessons derived exclusively from adopted revisions."""
from __future__ import annotations

from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import threading
from uuid import uuid4

from .jobs import atomic_json
from .task_state import now

_LOCK = threading.RLock()


def memory_path():
    configured = os.environ.get('MYAGENT_WRITING_MEMORY', '')
    return Path(configured).resolve() if configured else Path(__file__).resolve().parents[3] / '.myagent/writing-memory.json'


@contextmanager
def locked_store():
    path = memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, path.with_suffix('.lock').open('a+b') as lock:
        lock.seek(0, 2)
        if not lock.tell():
            lock.write(b'0');lock.flush()
        lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'version': 1, 'entries': []}
            yield data
            atomic_json(path, data)
        finally:
            if os.name == 'nt':
                lock.seek(0);msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def memories(include_deleted=False):
    path = memory_path()
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'entries': []}
    return copy.deepcopy([e for e in data['entries'] if include_deleted or e.get('status') == 'active'])


def remember(project, thread, adoption, lessons):
    """Idempotent per adoption; provenance keeps the exact adopted text and dialogue."""
    ids = []
    with locked_store() as data:
        for index, lesson in enumerate(lessons):
            key = adoption['id'] + ':' + str(index)
            existing = next((e for e in data['entries'] if e.get('adoption_key') == key), None)
            if existing:
                ids.append(existing['id']);continue
            entry = {'id': uuid4().hex[:12], 'adoption_key': key, 'status': 'active', 'at': now(),
                     'lesson': lesson['lesson'], 'scope': lesson['scope'], 'keywords': lesson['keywords'],
                     'before': thread['quote'], 'after': adoption['replacement'],
                     'user_feedback': [m['text'] for m in thread['messages'] if m['role'] == 'user'],
                     'source': {'workspace': str(project.workspace), 'project': project.id,
                                'thread_id': thread['id'], 'adoption_id': adoption['id'],
                                'version': adoption['version'], 'title': project.data['title'],
                                'dialogue': f'outputs/report-discussions/{thread["id"]}.json'},
                     'origin': thread.get('origin', 'human'), 'reviewed': False, 'history': []}
            data['entries'].append(entry);ids.append(entry['id'])
    return ids


def update_memory(identifier, *, lesson=None, delete=False, restore=False):
    with locked_store() as data:
        entry = next((e for e in data['entries'] if e['id'] == identifier), None)
        if entry is None:raise ValueError('这条写作经验不存在')
        entry['history'].append({k: copy.deepcopy(v) for k, v in entry.items() if k != 'history'})
        if lesson is not None:
            if not isinstance(lesson, str) or not 1 <= len(lesson.strip()) <= 1500:raise ValueError('经验需要1—1500个字符')
            entry.update(lesson=lesson.strip(), reviewed=True)
        if delete:entry['status'] = 'deleted'
        if restore:entry['status'] = 'active'
        entry['updated_at'] = now()
        return copy.deepcopy(entry)


def revoke(adoption_id):
    with locked_store() as data:
        for entry in data['entries']:
            if entry['source']['adoption_id'] == adoption_id:entry.update(status='revoked', updated_at=now())


def retrieve(project, payload, limit=4, max_chars=4500):
    focus = ' '.join(str(payload.get(k, '')) for k in
                     ('focus', 'target_heading', 'part_plan', 'candidate', 'requirement_feedback', 'selection', 'feedback'))[:20000].casefold()
    ranked = []
    for entry in memories():
        if entry.get('origin') != 'human':continue
        if entry['scope'] == 'local' and (entry['source']['workspace'] != str(project.workspace) or entry['source']['project'] != project.id):continue
        matches = sum(len(w) for w in entry['keywords'] if w and w.casefold() in focus)
        if entry['scope'] == 'topic' and not matches:continue
        ranked.append((matches, entry))
    selected, size = [], 0
    for _, entry in sorted(ranked, key=lambda pair: (pair[0], pair[1].get('updated_at', pair[1]['at'])), reverse=True):
        item = {k: copy.deepcopy(entry[k]) for k in ('id', 'lesson', 'scope', 'before', 'after', 'source', 'reviewed')}
        item['before'] = item['before'][:900];item['after'] = item['after'][:900]
        length = len(json.dumps(item, ensure_ascii=False))
        if len(selected) < limit and size + length <= max_chars:selected.append(item);size += length
    return selected
