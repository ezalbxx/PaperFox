"""Translate PaperFox tool conversations into supported model API protocols."""
from __future__ import annotations

import json
from types import SimpleNamespace as NS
from urllib.parse import quote
from uuid import uuid4

import httpx


class EndpointError(RuntimeError):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def request_headers(config):
    names = {'api-key': 'api-key', 'x-api-key': 'x-api-key', 'x-goog-api-key': 'x-goog-api-key'}
    headers = {}
    if config.api_auth == 'bearer' and config.api_key:
        headers['Authorization'] = 'Bearer ' + config.api_key
    elif config.api_auth in names and config.api_key:
        headers[names[config.api_auth]] = config.api_key
    if config.api_protocol == 'anthropic':
        headers['anthropic-version'] = '2023-06-01'
    return headers


def chat_messages(messages):
    return [{key: value for key, value in message.items() if key != 'native_turn'} for message in messages]


def _text(message):
    content = message.get('content') or ''
    if isinstance(content, str):
        return content
    return '\n'.join(part['text'] for part in content if part.get('type') == 'text')


def _arguments(raw):
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _functions(tools):
    return [tool['function'] for tool in tools if tool.get('type') == 'function']


def _forced_name(choice):
    return choice.get('function', {}).get('name') if isinstance(choice, dict) else None


def _anthropic_request(messages, tools, choice, limit):
    turns = []
    for message in messages:
        role = message['role']
        if role in ('system', 'developer'):
            continue
        if role == 'tool':
            role = 'user'
            content = [{'type': 'tool_result', 'tool_use_id': message['tool_call_id'], 'content': _text(message)}]
        else:
            text = _text(message)
            content = [{'type': 'text', 'text': text}] if text else []
            content.extend({'type': 'tool_use', 'id': call['id'], 'name': call['function']['name'],
                            'input': _arguments(call['function']['arguments'])}
                           for call in message.get('tool_calls', []))
        if not content:
            continue
        if turns and turns[-1]['role'] == role:
            turns[-1]['content'].extend(content)
        else:
            turns.append({'role': role, 'content': content})
    body = {'messages': turns, 'max_tokens': limit}
    system = '\n\n'.join(_text(m) for m in messages if m['role'] in ('system', 'developer'))
    if system:
        body['system'] = system
    if tools and choice != 'none':
        body['tools'] = [{'name': f['name'], 'description': f.get('description', ''),
                          'input_schema': f['parameters']} for f in _functions(tools)]
        name = _forced_name(choice)
        body['tool_choice'] = {'type': 'tool', 'name': name} if name else {'type': 'auto'}
    return body


def _responses_request(messages, tools, choice, limit, *, official=False):
    items = []
    for message in messages:
        role = message['role']
        if role == 'tool':
            items.append({'type': 'function_call_output', 'call_id': message['tool_call_id'], 'output': _text(message)})
        else:
            native = message.get('native_turn', {})
            if role == 'assistant' and native.get('protocol') == 'responses':
                items.extend(native['items'])
                continue
            if text := _text(message):
                items.append({'role': role, 'content': text})
            items.extend({'type': 'function_call', 'call_id': call['id'], **call['function']}
                         for call in message.get('tool_calls', []))
    body = {'input': items, 'max_output_tokens': limit, 'store': False}
    if official:
        body['include'] = ['reasoning.encrypted_content']
    if tools:
        body['tools'] = [{'type': 'function', **f, 'strict': False} for f in _functions(tools)]
        name = _forced_name(choice)
        body['tool_choice'] = {'type': 'function', 'name': name} if name else choice
        body['parallel_tool_calls'] = False
    return body


def _gemini_request(messages, tools, choice, limit):
    turns, names = [], {}
    for message in messages:
        role = message['role']
        if role in ('system', 'developer'):
            continue
        parts = []
        if role == 'tool':
            call_id = message['tool_call_id']
            name, provider_id = names[call_id]
            response = {'name': name, 'response': {'result': _text(message)}}
            if provider_id:
                response['id'] = provider_id
            parts.append({'functionResponse': response})
        else:
            native = message.get('native_turn', {})
            if role == 'assistant' and native.get('protocol') == 'gemini':
                parts = native['parts']
            elif text := _text(message):
                parts.append({'text': text})
            calls = message.get('tool_calls', [])
            if native.get('protocol') == 'gemini':
                functions = [part['functionCall'] for part in parts if 'functionCall' in part]
                names.update((call['id'], (function['name'], function.get('id'))) for call, function in zip(calls, functions))
            else:
                for call in calls:
                    function = call['function']
                    names[call['id']] = (function['name'], None)
                    parts.append({'functionCall': {'name': function['name'], 'args': _arguments(function['arguments'])}})
        role = 'model' if role == 'assistant' else 'user'
        if parts and turns and turns[-1]['role'] == role:
            turns[-1]['parts'].extend(parts)
        elif parts:
            turns.append({'role': role, 'parts': list(parts)})
    body = {'contents': turns, 'generationConfig': {'maxOutputTokens': limit}}
    system = [_text(m) for m in messages if m['role'] in ('system', 'developer')]
    if system:
        body['systemInstruction'] = {'parts': [{'text': '\n\n'.join(system)}]}
    if tools:
        body['tools'] = [{'functionDeclarations': [
            {'name': f['name'], 'description': f.get('description', ''), 'parametersJsonSchema': f['parameters']}
            for f in _functions(tools)]}]
        name = _forced_name(choice)
        options = {'mode': 'ANY' if name else 'NONE' if choice == 'none' else 'AUTO'}
        if name:
            options['allowedFunctionNames'] = [name]
        body['toolConfig'] = {'functionCallingConfig': options}
    return body


def _normalized(text, calls, input_tokens, output_tokens, *, finish_reason=None, native=None, usage_known=True, cache=0):
    if finish_reason in ('max_tokens', 'max_output_tokens', 'MAX_TOKENS'):
        finish_reason = 'length'
    message = NS(content=text, reasoning_content=None, tool_calls=[
        NS(id=call_id, function=NS(name=name, arguments=args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)))
        for call_id, name, args in calls])
    usage = NS(prompt_tokens=input_tokens, completion_tokens=output_tokens, total_tokens=input_tokens + output_tokens,
               prompt_cache_hit_tokens=cache, prompt_tokens_details=NS(cached_tokens=cache))
    return NS(choices=[NS(message=message)], usage=usage), finish_reason, native, usage_known


def _normalize_payload(protocol, data):
    if protocol == 'gemini':
        candidate = (data.get('candidates') or [{}])[0]
        parts = candidate.get('content', {}).get('parts', [])
        usage = data.get('usageMetadata') or {}
        return _normalized(''.join(part.get('text', '') for part in parts if not part.get('thought')),
                           [(f.get('id') or 'gemini_'+uuid4().hex, f['name'], f.get('args', {}))
                            for f in (part['functionCall'] for part in parts if 'functionCall' in part)],
                           usage.get('promptTokenCount', 0), usage.get('candidatesTokenCount', 0) + usage.get('thoughtsTokenCount', 0),
                           finish_reason=candidate.get('finishReason'), usage_known=bool(usage),
                           native={'protocol': 'gemini', 'parts': parts}, cache=usage.get('cachedContentTokenCount', 0))
    usage = data.get('usage') or {}
    if protocol == 'anthropic':
        parts = data.get('content', [])
        cache = usage.get('cache_read_input_tokens', 0)
        return _normalized(''.join(part['text'] for part in parts if part['type'] == 'text'),
                           [(p['id'], p['name'], p['input']) for p in parts if p['type'] == 'tool_use'],
                           usage.get('input_tokens', 0) + cache + usage.get('cache_creation_input_tokens', 0),
                           usage.get('output_tokens', 0), finish_reason=data.get('stop_reason'),
                           usage_known=bool(usage), cache=cache)
    if protocol == 'responses':
        items = data.get('output', [])
        return _normalized(''.join(p['text'] for item in items if item['type'] == 'message'
                                    for p in item['content'] if p['type'] == 'output_text'),
                           [(p['call_id'], p['name'], p['arguments']) for p in items if p['type'] == 'function_call'],
                           usage.get('input_tokens', 0), usage.get('output_tokens', 0),
                           finish_reason=(data.get('incomplete_details') or {}).get('reason') or data.get('status'),
                           native={'protocol': 'responses', 'items': [
                               item for item in items if item['type'] in ('reasoning', 'message', 'function_call')]},
                           usage_known=bool(usage), cache=(usage.get('input_tokens_details') or {}).get('cached_tokens', 0))
    choice = data['choices'][0]
    raw = choice['message']
    result, reason, native, known = _normalized(raw.get('content') or '',
        [(call['id'], call['function']['name'], call['function']['arguments']) for call in raw.get('tool_calls') or []],
        usage.get('prompt_tokens', 0), usage.get('completion_tokens', 0),
        finish_reason=choice.get('finish_reason'), usage_known=bool(usage),
        cache=usage.get('prompt_cache_hit_tokens') or (usage.get('prompt_tokens_details') or {}).get('cached_tokens', 0))
    result.choices[0].message.reasoning_content = raw.get('reasoning_content')
    return result, reason, native, known


def buffered_call(config, messages, tools=(), choice='auto', *, limit=4096, timeout=60, thinking=False, effort=None):
    protocol = config.api_protocol
    tools = tools or []
    if protocol == 'anthropic':
        path, body = '/messages', _anthropic_request(messages, tools, choice, limit)
    elif protocol == 'gemini':
        model = quote(config.model.removeprefix('models/'), safe='')
        path, body = f'/models/{model}:generateContent', _gemini_request(messages, tools, choice, limit)
    elif protocol == 'responses':
        path = '/responses'
        body = _responses_request(messages, tools, choice, limit, official=config.provider == 'openai')
    else:
        path = '/chat/completions'
        token_field = 'max_completion_tokens' if config.provider == 'openai' else 'max_tokens'
        body = {'messages': chat_messages(messages), token_field: limit,
                **config.request_options(thinking=thinking, effort=effort)}
        if tools:
            body.update(tools=tools, tool_choice=choice)
    if protocol != 'gemini':
        body['model'] = config.model
    options = {'headers': request_headers(config), 'json': body,
               'params': {'api-version': config.api_version} if config.api_version else None}
    with httpx.Client(timeout=timeout, trust_env=config.trust_env, follow_redirects=False) as client:
        response = client.post(config.base_url.rstrip('/') + path, **options)
    if not response.is_success:
        raise EndpointError('模型 API 返回 HTTP '+str(response.status_code), response.status_code)
    try:
        return _normalize_payload(protocol, response.json())
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise EndpointError('模型响应不符合所选 API 协议，请检查协议、模型和 API 地址。') from exc
