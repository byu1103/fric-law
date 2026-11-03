"""Local optional credentials, never prefilled or returned to the dashboard."""

from __future__ import annotations

import os
import hashlib
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path

from dotenv import dotenv_values, set_key

ENV_FILE = Path(__file__).resolve().parent / '.env'
KEYS = ('TAVILY_API_KEY', 'AIBOX_API_KEY')
AIBOX_BASE_URL = 'https://api.ai-box.vn/v1'
GEMINI_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta/openai/'
DEFAULT_MODEL = 'deepseek-v4.1-flash'
DEFAULT_GEMINI_MODEL = 'gemini-3.5-flash-lite'


@contextmanager
def _lock(path):
    with path.with_name(path.name + '.lock').open('a+b') as handle:
        if os.name == 'nt':
            import msvcrt

            handle.write(b'0')
            handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def reload_local_settings():
    """Apply only API settings; never change an open database's workspace path."""
    if ENV_FILE.exists():
        values = dotenv_values(ENV_FILE, interpolate=False)
        for name in (*KEYS, 'GEMINI_API_KEY', 'AIBOX_MODEL', 'GEMINI_MODEL', 'AI_PROVIDER'):
            if name in values and values[name] is not None:
                os.environ[name] = values[name]


def load_startup_settings():
    """Load only the optional workspace before core computes its database paths.

    Authentication is owned by deployment environment/launchers. A local API
    config file must never turn off the shared server's login boundary.
    """
    if ENV_FILE.exists():
        workspace = dotenv_values(ENV_FILE, interpolate=False).get('FRIC_WORKSPACE')
        if workspace:
            os.environ.setdefault('FRIC_WORKSPACE', workspace)


def get_key_status():
    return {name: bool(os.getenv(name, '').strip()) for name in KEYS}


def get_ai_settings():
    """Return display-safe configuration; configured does not mean API-verified."""
    reload_local_settings()
    raw_provider = os.getenv('AI_PROVIDER', '').strip().lower()
    gemini_key = os.getenv('GEMINI_API_KEY', '').strip()
    aibox_key = os.getenv('AIBOX_API_KEY', '').strip()

    if raw_provider == 'gemini':
        provider = 'gemini'
    elif raw_provider == 'aibox':
        provider = 'aibox'
    elif gemini_key and not aibox_key:
        provider = 'gemini'
    else:
        provider = 'aibox'

    if provider == 'gemini':
        key = gemini_key
        model = os.getenv('GEMINI_MODEL', '').strip() or DEFAULT_GEMINI_MODEL
        base_url = GEMINI_BASE_URL
    else:
        provider = 'aibox'
        key = aibox_key
        model = os.getenv('AIBOX_MODEL', '').strip() or DEFAULT_MODEL
        base_url = AIBOX_BASE_URL

    # A verification result belongs to this exact credential/model combination.
    revision = hashlib.sha256(
        (provider + '\0' + base_url + '\0' + key + '\0' + model).encode('utf-8')
    ).hexdigest()
    return {
        'configured': bool(key),
        'model': model,
        'revision': revision,
        'provider': provider,
        'base_url': base_url,
        'api_format': 'chat_completions',
    }


def _validated_key(value):
    if not isinstance(value, str) or any(ch in value for ch in '\r\n\x00'):
        raise ValueError('Khóa không hợp lệ; mỗi khóa phải nằm trên một dòng.')
    value = value.strip()
    if not value or len(value) > 4096:
        raise ValueError('Nhập khóa hợp lệ hoặc để trống để giữ nguyên cấu hình.')
    return value


def save_ai_settings(aibox_key=None, model=None, provider=None, gemini_key=None):
    """Save optional key/model atomically, available to all local server processes."""
    changes = {}
    if provider is not None:
        p = str(provider).strip().lower()
        if p in ('gemini', 'aibox'):
            changes['AI_PROVIDER'] = p
    if aibox_key is not None:
        changes['AIBOX_API_KEY'] = _validated_key(aibox_key)
    if gemini_key is not None:
        changes['GEMINI_API_KEY'] = _validated_key(gemini_key)
    if model is not None:
        if not isinstance(model, str):
            raise ValueError('Tên model AI không hợp lệ.')
        model = model.strip()
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}', model):
            raise ValueError('Nhập tên model AI hợp lệ, không có khoảng trắng hoặc URL.')
        if '://' in model:
            raise ValueError('Nhập tên model, không phải URL dịch vụ.')
        target_provider = changes.get('AI_PROVIDER') or os.getenv('AI_PROVIDER', '').strip().lower()
        if target_provider == 'gemini':
            changes['GEMINI_MODEL'] = model
        else:
            changes['AIBOX_MODEL'] = model
    _save_changes(changes)
    return get_ai_settings()


def save_api_keys(tavily_key=None, aibox_key=None):
    changes = {}
    for name, value in (('TAVILY_API_KEY', tavily_key), ('AIBOX_API_KEY', aibox_key)):
        if value is None:
            continue
        changes[name] = _validated_key(value)
    _save_changes(changes)
    return get_key_status()


def _save_changes(changes):
    if not changes:
        raise ValueError('Nhập ít nhất một khóa hoặc model để lưu.')
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _lock(ENV_FILE):
        fd, temporary = tempfile.mkstemp(prefix='.env-', dir=ENV_FILE.parent)
        try:
            with os.fdopen(fd, 'wb') as output:
                if ENV_FILE.exists():
                    output.write(ENV_FILE.read_bytes())
            for name, value in changes.items():
                set_key(temporary, name, value, quote_mode='always')
            os.chmod(temporary, 0o600)
            with open(temporary, 'rb') as output:
                os.fsync(output.fileno())
            os.replace(temporary, ENV_FILE)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    os.environ.update(changes)
