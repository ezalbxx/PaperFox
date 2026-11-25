"""Local report protocol recovery; never supplies prose, measurements or judgments."""
from __future__ import annotations

import copy
import json


class ProtocolError(ValueError):
    def __init__(self, field, expected, actual):
        super().__init__(json.dumps({'kind': 'protocol', 'field': field,
            'expected': expected, 'actual': actual}, ensure_ascii=False))


class FactConflict(ValueError):
    pass


class RequirementConflict(ValueError):
    pass


class StageUnresolved(Exception):
    def __init__(self, kind, reason, *, candidate=None, questions=None):
        super().__init__(reason)
        self.kind, self.reason = kind, reason
        self.candidate = copy.deepcopy(candidate)
        self.questions = copy.deepcopy(questions or [])


def submission(args):
    """Unwrap only lossless, unambiguous transport mistakes, keeping an audit trail."""
    value = copy.deepcopy(args); changes = []
    if set(value) == {'arguments'}:
        inner = value['arguments']
        if isinstance(inner, str):
            try: inner = json.loads(inner)
            except ValueError as exc: raise ProtocolError('arguments', 'valid JSON object', str(exc)) from exc
        if not isinstance(inner, dict): raise ProtocolError('arguments', 'object', inner)
        value = inner; changes.append('unwrapped_arguments')
    if set(value) == {'unresolved'}:
        pending = value['unresolved']
        if not isinstance(pending, dict) or not pending.get('reason') or pending.get('kind') not in (
                'protocol', 'quality', 'facts', 'requirements', 'materials', 'safety'):
            raise ProtocolError('unresolved', 'kind and nonempty reason', pending)
        return None, changes, pending
    if not isinstance(value.get('result'), dict):
        raise ProtocolError('result', 'object', value.get('result'))
    result = value['result']
    for key in set(value) - {'result'}:
        if key in result and result[key] != value[key]:
            raise ProtocolError('result.' + key, 'one unambiguous value', [result[key], value[key]])
        result[key] = value[key]; changes.append('moved_to_result:' + key)
    if result.get('status') == 'unresolved':
        return submission({'unresolved': {k: v for k, v in result.items() if k != 'status'}})
    return result, changes, None
