"""Read saved conversation evidence without opening a writer or calling the model."""
from __future__ import annotations

import json
from pathlib import Path

from .task_state import now


def export_conversation(workspace: Path, session_id: str) -> dict:
    if not session_id or not session_id.isalnum() or len(session_id)>64:
        raise ValueError('invalid session id')
    root=Path(workspace).resolve()/'.myagent'/'chat'
    path=root/f'{session_id}.json'
    checkpoint=json.loads(path.read_text(encoding='utf-8'))
    # Read once: export a prefix of the real append-only trace, never reconstruct events.
    raw=(root/f'{session_id}.jsonl').read_bytes()
    cut=raw.rfind(b'\n')+1
    complete=raw[:cut]
    events=[json.loads(line) for line in complete.decode('utf-8').splitlines() if line.strip()]
    messages=[]
    for e in events:
        p=e['payload']
        if e['type']=='message':
            m=p['message']
            if m.get('role') in ('user','assistant') and m.get('content') and not m['content'].startswith(('[Runtime','[Compacted historical')):
                messages.append({'role':m['role'],'text':m['content']})
        elif e['type']=='web_partial_answer':
            messages.append({'role':'assistant','text':p['text']})
        elif e['type']=='web_answer_end' and p.get('display_result',not p.get('streamed')) and p.get('text'):
            m={'role':'assistant','text':p['text']}
            if not messages or messages[-1]!=m: messages.append(m)
    return {'format':'myagent-conversation-v1','exported_at':now(),'session_id':session_id,
            'workspace':str(Path(workspace).resolve()),'title':checkpoint['title'],
            'messages':messages,'events':events,'checkpoint':public_checkpoint(checkpoint),
            'source':{'jsonl_bytes':len(complete),'incomplete_tail_omitted':cut<len(raw),
                      'checkpoint_matches_trace':checkpoint.get('last_event_id')==(events[-1]['id'] if events else None)},
            'notice':'Derived export of original events, not a new run. Active conversations may continue after this prefix.'}


def public_checkpoint(value):
    """Provider protocol reasoning stays private; exports contain original visible events."""
    if isinstance(value, dict):
        return {k:public_checkpoint(v) for k,v in value.items() if k != 'reasoning_content'}
    if isinstance(value, list):
        return [public_checkpoint(v) for v in value]
    return value


def cmd_export(args):
    from .jobs import atomic_json
    result=export_conversation(Path(args.workspace),args.session)
    target=Path(args.output).resolve()
    source_root=Path(args.workspace).resolve()/'.myagent'/'chat'
    if target==source_root or source_root in target.parents:
        raise ValueError('export outside the live chat directory to preserve source records')
    if target.exists():
        raise ValueError('export target already exists; choose a new output path')
    target.parent.mkdir(parents=True,exist_ok=True)
    atomic_json(target,result)
    print(str(target))
    return 0
