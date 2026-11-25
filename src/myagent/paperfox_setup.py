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

import httpx

from .jobs import atomic_json

DEEPSEEK_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-flash"


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


def setup_state():
    return {"enabled": settings_path() is not None, "configured": bool(api_key()),
            "provider": "DeepSeek", "model": DEEPSEEK_MODEL, "connection": connection_mode()}


def connection_error(exc):
    """Return a useful diagnosis without including URLs, headers or credentials."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        messages = {
            401: "密钥无效。请填 DeepSeek 官方平台创建的 API Key",
            402: "API 账户余额不足，请在 DeepSeek 开放平台检查余额",
            403: "请求被拒绝，请检查 API 账户权限和网络访问限制",
            404: "服务没有返回预期的模型列表接口",
            407: "网络代理要求认证，请检查代理设置",
            429: "请求达到频率限制，请稍后重试",
        }
        message = messages.get(status, "服务暂时异常，请稍后重试" if status >= 500 else "服务拒绝或未能完成请求")
        return f"DeepSeek HTTP {status}：{message}。"
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
        return "DNS 无法解析 api.deepseek.com。请检查网络或换手机热点重试。"
    if any(isinstance(c, (TimeoutError, httpx.TimeoutException)) for c in causes):
        return "连接 DeepSeek 超时。请尝试换网络或切换连接方式。"
    return "连接 DeepSeek 失败。请检查 api.deepseek.com 是否可达，或切换连接方式重试。"


def save_api_key(key, connection="system"):
    path = settings_path()
    if path is None:
        raise ValueError("当前服务使用开发环境配置")
    if connection not in ("system", "direct"):
        raise ValueError("请选择有效的连接方式")
    if not isinstance(key, str):
        raise ValueError("请填写完整的 DeepSeek API Key")
    key = key.strip() or api_key()
    if not (8 <= len(key) <= 256) or not key.isascii() or any(c.isspace() for c in key):
        raise ValueError("请填写完整的 DeepSeek API Key")
    from openai import OpenAI
    try:
        with httpx.Client(trust_env=connection == "system") as transport, OpenAI(
                api_key=key, base_url=DEEPSEEK_URL, timeout=20, max_retries=0,
                http_client=transport) as client:
            response = client.models.list()
    except Exception as exc:
        raise ValueError(connection_error(exc)) from None
    if not any(model.id == DEEPSEEK_MODEL for model in response.data):
        raise ValueError("DeepSeek 已连通，但模型列表中没有 deepseek-flash。请核对 API 账户。")
    sealed = _protect(key.encode("utf-8"))
    atomic_json(path, {"api_key": base64.b64encode(sealed).decode("ascii"), "connection": connection})
    return setup_state()
