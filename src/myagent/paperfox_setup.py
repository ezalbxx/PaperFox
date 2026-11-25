"""First-run configuration for the portable Windows workbench."""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import socket
import ssl
import time
from urllib.parse import urlsplit, urlunsplit

import httpx

from .jobs import atomic_json

DEEPSEEK_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-flash"
PRESETS = {
    "deepseek": {"label": "DeepSeek 官方", "base_url": DEEPSEEK_URL, "model": DEEPSEEK_MODEL,
                 "protocol": "chat", "auth": "bearer"},
    "qianwen": {"label": "千问 AI 平台", "base_url": "https://maas.qianwenaiapi.com/compatible-mode/v1",
                "model": "deepseek-v4.1-flash-1017", "protocol": "chat", "auth": "bearer"},
    "openai": {"label": "OpenAI 官方", "base_url": "https://api.openai.com/v1", "model": "",
               "protocol": "responses", "auth": "bearer"},
    "anthropic": {"label": "Anthropic Claude", "base_url": "https://api.anthropic.com/v1", "model": "",
                  "protocol": "anthropic", "auth": "x-api-key"},
    "gemini": {"label": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta", "model": "",
               "protocol": "gemini", "auth": "x-goog-api-key"},
    "ollama": {"label": "Ollama 本地", "base_url": "http://127.0.0.1:11434/v1", "model": "",
               "protocol": "chat", "auth": "none"},
    "custom": {"label": "自定义 API", "base_url": "", "model": "", "protocol": "chat", "auth": "bearer"},
}
PROTOCOL_PATHS = {"chat": "/chat/completions", "responses": "/responses", "anthropic": "/messages", "gemini": ""}
AUTH_TYPES = ("bearer", "api-key", "x-api-key", "x-goog-api-key", "none")


def settings_path():
    value = os.environ.get("PAPERFOX_SETTINGS")
    return Path(value) if value else None


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _protect(value, *, decrypt=False):
    """Windows DPAPI binds the API key to the current Windows user."""
    buffer = ctypes.create_string_buffer(value)
    source = _Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = _Blob()
    crypt = ctypes.windll.crypt32
    operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ValueError("Windows 无法读取本机保存的密钥，请重新填写")
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        release = ctypes.windll.kernel32.LocalFree
        release.argtypes = [ctypes.c_void_p]
        release.restype = ctypes.c_void_p
        release(result.data)


def _settings():
    path = settings_path()
    if not path or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def api_key():
    try:
        sealed = _settings()["api_key"]
        return _protect(base64.b64decode(sealed, validate=True), decrypt=True).decode("utf-8")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return ""


def connection_mode():
    return "direct" if _settings().get("connection") == "direct" else "system"


def _public_settings():
    saved = _settings()
    selected = saved.get('preset', 'deepseek')
    preset = PRESETS.get(selected, PRESETS['deepseek'])
    return {
        'preset': selected, 'base_url': saved.get('base_url', preset['base_url']),
        'model': saved.get('model', preset['model']), 'protocol': saved.get('protocol', preset['protocol']),
        'auth': saved.get('auth', preset['auth']), 'api_version': saved.get('api_version', ''),
        'buffered': bool(saved.get('buffered')), 'connection': connection_mode(),
    }


def _secret_scope(settings):
    return (settings['base_url'], settings['protocol'], settings['auth'])


def _runtime_options(settings, key):
    host = urlsplit(settings['base_url']).hostname
    providers = {'api.deepseek.com': 'deepseek', 'maas.qianwenaiapi.com': 'qianwen',
                 'dashscope.aliyuncs.com': 'dashscope', 'api.openai.com': 'openai'}
    return {'provider': providers.get(host, 'custom'), 'base_url': settings['base_url'],
            'model': settings['model'], 'api_key': key, 'api_auth': settings['auth'],
            'api_protocol': settings['protocol'], 'api_version': settings['api_version'],
            'buffered': settings['buffered'], 'trust_env': settings['connection'] == 'system'}


def model_settings():
    settings = _public_settings()
    return _runtime_options(settings, api_key() if settings['auth'] != 'none' else '')


def setup_state():
    settings = _public_settings()
    has_key = bool(api_key())
    configured = bool(settings['base_url'] and settings['model']
                      and (has_key or settings['auth'] == 'none'))
    return {'enabled': settings_path() is not None, 'configured': configured, 'has_key': has_key,
            **settings, 'presets': PRESETS}


def connection_error(exc):
    """Return a useful diagnosis without including URLs, headers or credentials."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        messages = {
            401: "密钥无效，请核对密钥来源和鉴权方式",
            402: "API 账户余额不足，请到所选服务商检查余额",
            403: "请求被拒绝，请检查 API 账户权限和网络访问限制",
            404: "接口或模型不存在，请核对协议、API 地址和模型名",
            407: "网络代理要求认证，请检查代理设置",
            429: "请求达到频率限制，请稍后重试",
        }
        message = messages.get(status, "服务暂时异常，请稍后重试" if status >= 500 else "服务拒绝或未能完成请求")
        return f"模型 API HTTP {status}：{message}。"
    causes = []
    cause = exc
    while cause is not None and all(cause is not item for item in causes):
        causes.append(cause)
        cause = cause.__cause__ or cause.__context__
    if any(isinstance(c, ssl.SSLError) or "CERTIFICATE_VERIFY_FAILED" in str(c) for c in causes):
        return "TLS 证书验证失败。请检查系统日期和网络代理，或更换可信网络。"
    if any(isinstance(c, httpx.ProxyError) for c in causes):
        return "网络代理连接失败。请检查代理，或在下方切换连接方式后重试。"
    if any(isinstance(c, socket.gaierror) for c in causes):
        return "DNS 无法解析模型服务地址。请检查地址和网络。"
    if any(isinstance(c, (TimeoutError, httpx.TimeoutException)) for c in causes):
        return "连接模型服务超时。请检查网络或切换连接方式。"
    return "连接模型服务失败。请检查 API 地址和代理。"


def _base_url(value, protocol):
    try:
        url = urlsplit(value.strip())
        _ = url.port
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("请填写完整的 HTTP 或 HTTPS API 地址") from exc
    if (url.scheme not in ('http', 'https') or not url.hostname or url.username is not None
            or url.password is not None or url.query or url.fragment or any(c.isspace() for c in value.strip())):
        raise ValueError("请填写 HTTP 或 HTTPS API 地址。密钥和 API 版本应填入各自的输入框。")
    path = url.path.rstrip('/')
    suffix = PROTOCOL_PATHS[protocol]
    if suffix and path.endswith(suffix):
        path = path[:-len(suffix)]
    if protocol == 'gemini' and path.endswith(':generateContent') and '/models/' in path:
        path = path.rsplit('/models/', 1)[0]
    if not path and protocol in ('anthropic', 'gemini'):
        path = '/v1' if protocol == 'anthropic' else '/v1beta'
    if not path and url.hostname == 'api.openai.com':
        path = '/v1'
    return urlunsplit((url.scheme, url.netloc.lower(), path, '', ''))


def _probe(settings, key):
    from .config import Config
    from .interactive_model import StreamingModel
    from .model_endpoint import EndpointError

    config = Config(**_runtime_options(settings, key))
    model = StreamingModel(config)
    model.deadline = time.monotonic() + 25
    model.output_token_limit = 256
    function = {'name': 'paperfox_connection_check', 'description': 'Confirm this test tool call.',
                'parameters': {'type': 'object', 'properties': {'value': {'type': 'string'}}, 'required': ['value']}}
    # Test the same adapter used by reports, with a synthetic request and no user material.
    try:
        result = model.chat([{'role': 'user', 'content': 'Call paperfox_connection_check once with value OK.'}],
                            [{'type': 'function', 'function': function}])
    finally:
        if not config.buffered:
            model._client.close()
    if not any(call['name'] == function['name'] for call in result['tool_calls']):
        raise EndpointError("服务已连通，但模型未返回工具调用。请选择支持工具调用的模型。")


def save_settings(data):
    path = settings_path()
    if path is None:
        raise ValueError("当前服务使用开发环境配置")
    old = _public_settings()
    selected = data.get('preset', old['preset'])
    if selected not in PRESETS:
        raise ValueError("请选择有效的供应商")
    defaults = old if selected == old['preset'] else PRESETS[selected]
    protocol = data.get('protocol', defaults['protocol'])
    auth = data.get('auth', defaults['auth'])
    connection = data.get('connection', old['connection'])
    if protocol not in PROTOCOL_PATHS or auth not in AUTH_TYPES:
        raise ValueError("请选择有效的 API 协议和鉴权方式")
    if connection not in ("system", "direct"):
        raise ValueError("请选择有效的连接方式")
    base = _base_url(data.get('base_url', defaults['base_url']), protocol)
    model = data.get('model', defaults['model'])
    version = data.get('api_version', defaults.get('api_version', ''))
    if not isinstance(model, str) or not model.strip() or len(model) > 256 or not model.isprintable():
        raise ValueError("请填写供应商提供的模型 ID")
    if not isinstance(version, str) or len(version) > 48 or (version and not all(c.isascii() and (c.isalnum() or c in '-_.') for c in version)):
        raise ValueError("API 版本填写有误")
    settings = {'preset': selected, 'base_url': base, 'model': model.strip(), 'protocol': protocol, 'auth': auth,
                'api_version': version, 'connection': connection, 'buffered': data.get('buffered', defaults.get('buffered', False)) is True}
    key = data.get('api_key', '')
    if not isinstance(key, str):
        raise ValueError("请填写 API Key")
    key = key.strip()
    if auth == 'none':
        key = ''
    elif not key and _secret_scope(old) == _secret_scope(settings):
        key = api_key()
    if auth != 'none' and (not key or len(key) > 8192 or not key.isascii() or not key.isprintable() or any(c.isspace() for c in key)):
        raise ValueError("请填写此 API 地址对应的密钥。更换地址或鉴权方式后需要重新填写。")
    from .model_endpoint import EndpointError
    try:
        _probe(settings, key)
    except EndpointError as exc:
        raise ValueError(connection_error(exc) if exc.status_code is not None else str(exc)) from None
    except Exception as exc:
        raise ValueError(connection_error(exc)) from None
    if key:
        settings['api_key'] = base64.b64encode(_protect(key.encode('utf8'))).decode('ascii')
    atomic_json(path, settings)
    return setup_state()
