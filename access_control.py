"""Optional login boundary for shared Streamlit access; local use stays unchanged.

Remote launchers must set FRIC_AUTH_REQUIRED=1 before exposing the server. Keep
credentials in the server environment or owner-readable files, never in Git.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import stat
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import MutableMapping

_AUTH_KEY = '_fric_authenticated'
_ATTEMPTS_KEY = '_fric_login_attempts'
_MAX_PASSWORD_BYTES = 1024


class AccessConfigurationError(ValueError):
    """A remote server has no usable access configuration."""


class LoginRateLimited(ValueError):
    def __init__(self, retry_after):
        self.retry_after = max(1, int(retry_after + 0.999))
        super().__init__('Tạm khóa đăng nhập; vui lòng thử lại sau.')


def _encoded(value):
    return base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')


def _decoded(value):
    return base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)


def _hash_parts(encoded):
    try:
        algorithm, n, r, p, salt, digest = encoded.split('$')
        n, r, p = int(n), int(r), int(p)
        salt, digest = _decoded(salt), _decoded(digest)
        if algorithm != 'scrypt' or n not in (16384, 32768) or r != 8 or p != 1:
            raise ValueError
        if not 16 <= len(salt) <= 32 or len(digest) != 32:
            raise ValueError
        return n, r, p, salt, digest
    except (AttributeError, TypeError, ValueError):
        raise AccessConfigurationError('Cấu hình mật khẩu đăng nhập không hợp lệ.') from None


def make_password_hash(password: str) -> str:
    """Generate a salted scrypt hash without logging or echoing the password."""
    value = password.encode('utf-8')
    if not value or len(value) > _MAX_PASSWORD_BYTES:
        raise ValueError('Mật khẩu phải có từ 1 đến 1024 byte UTF-8.')
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(value, salt=salt, n=16384, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)
    return f'scrypt$16384$8$1${_encoded(salt)}${_encoded(digest)}'


def check_password(password: str, encoded: str) -> bool:
    """Verify a supported bounded scrypt hash; malformed hashes fail closed."""
    try:
        n, r, p, salt, expected = _hash_parts(encoded)
        value = password.encode('utf-8')
        if len(value) > _MAX_PASSWORD_BYTES:
            return False
        actual = hashlib.scrypt(value, salt=salt, n=n, r=r, p=p, dklen=32, maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(actual, expected)
    except (AccessConfigurationError, AttributeError, TypeError, ValueError):
        return False


def remote_access_required() -> bool:
    truthy = ('1', 'true', 'yes', 'on')
    return any(
        os.environ.get(name, '').strip().lower() in truthy for name in ('FRIC_AUTH_REQUIRED', 'FRIC_HOSTED')
    )


def _private_file(name):
    """Do not expose filesystem paths or file contents in configuration errors."""
    try:
        path = Path(os.environ[name]).expanduser()
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
            raise ValueError
        if os.name != 'nt' and stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError
        value = path.read_text(encoding='utf-8').strip()
        if not value:
            raise ValueError
        return value
    except (KeyError, OSError, ValueError):
        raise AccessConfigurationError(
            'Không đọc được tệp xác thực riêng tư; quản trị viên cần kiểm tra cấu hình và quyền tệp.'
        ) from None


@dataclass(frozen=True)
class AccessConfig:
    user: str
    password_hash: str = field(default='', repr=False)
    password_file_secret: str = field(default='', repr=False)
    ttl: int = 8 * 60 * 60

    @property
    def revision(self):
        value = f'{self.user}\0{self.password_hash}\0{self.password_file_secret}\0{self.ttl}'
        return hashlib.sha256(value.encode('utf-8')).hexdigest()

    def verify(self, username, password):
        username_ok = hmac.compare_digest(username.encode('utf-8'), self.user.encode('utf-8'))
        if self.password_hash:
            password_ok = check_password(password, self.password_hash)
        else:
            value = password.encode('utf-8')
            password_ok = len(value) <= _MAX_PASSWORD_BYTES and hmac.compare_digest(
                value, self.password_file_secret.encode('utf-8')
            )
        return bool(username_ok and password_ok)


def load_access_config() -> AccessConfig:
    user = os.environ.get('FRIC_ACCESS_USER', 'editor').strip()
    if not user or len(user) > 128:
        raise AccessConfigurationError('Tên đăng nhập trên máy chủ không hợp lệ.')
    try:
        ttl = int(os.environ.get('FRIC_AUTH_SESSION_HOURS', '8')) * 60 * 60
        if not 60 * 60 <= ttl <= 24 * 60 * 60:
            raise ValueError
    except ValueError:
        raise AccessConfigurationError('Thời hạn đăng nhập phải từ 1 đến 24 giờ.') from None
    encoded = os.environ.get('FRIC_ACCESS_PASSWORD_HASH', '').strip()
    if not encoded and os.environ.get('FRIC_ACCESS_HASH_FILE'):
        encoded = _private_file('FRIC_ACCESS_HASH_FILE')
    if encoded:
        _hash_parts(encoded)
        return AccessConfig(user, password_hash=encoded, ttl=ttl)
    if os.environ.get('FRIC_ACCESS_PASSWORD_FILE'):
        password = _private_file('FRIC_ACCESS_PASSWORD_FILE')
        if len(password.encode('utf-8')) > _MAX_PASSWORD_BYTES:
            raise AccessConfigurationError('Cấu hình mật khẩu đăng nhập không hợp lệ.')
        return AccessConfig(user, password_file_secret=password, ttl=ttl)
    raise AccessConfigurationError(
        'Máy chủ chưa cấu hình đăng nhập. Quản trị viên cần đặt FRIC_ACCESS_HASH_FILE '
        'hoặc FRIC_ACCESS_PASSWORD_HASH trước khi cho phép truy cập.'
    )


class LoginLimiter:
    """Bound login attempts across all sessions in this server process."""

    def __init__(self, max_failures=5, window=60, lockout=60):
        self.max_failures, self.window, self.lockout = max_failures, window, lockout
        self._entries = OrderedDict()
        self._lock = threading.Lock()

    def _entry(self, scope, now):
        entry = self._entries.setdefault(scope, {'failed': [], 'until': 0})
        entry['failed'] = [stamp for stamp in entry['failed'] if stamp > now - self.window]
        self._entries.move_to_end(scope)
        while len(self._entries) > 128:
            self._entries.popitem(last=False)
        return entry

    def delay(self, scope, now):
        with self._lock:
            return max(0, self._entry(scope, now)['until'] - now)

    def reserve(self, scope, now):
        with self._lock:
            entry = self._entry(scope, now)
            if entry['until'] > now:
                raise LoginRateLimited(entry['until'] - now)
            entry['failed'].append(now)
            if len(entry['failed']) >= self.max_failures:
                entry['until'] = now + self.lockout
            return max(0, entry['until'] - now)


_LIMITER = LoginLimiter()


def authenticated_user(session: MutableMapping, config: AccessConfig, now=None):
    now = time.time() if now is None else now
    value = session.get(_AUTH_KEY)
    if not isinstance(value, dict):
        return None
    if (
        value.get('revision') != config.revision
        or value.get('user') != config.user
        or not isinstance(value.get('expires'), (int, float))
        or value['expires'] <= now
        or value.get('issued', now + 1) > now
    ):
        # Expiry/credential rotation must discard old draft and credential widgets too.
        session.clear()
        return None
    return value['user']


def login(username, password, session: MutableMapping, config: AccessConfig, now=None, limiter=None):
    now = time.time() if now is None else now
    limiter = _LIMITER if limiter is None else limiter
    attempts = session.get(_ATTEMPTS_KEY, {})
    scope = config.revision
    retry = max(limiter.delay(scope, now), attempts.get('until', 0) - now)
    if retry > 0:
        raise LoginRateLimited(retry)
    # Reserve before the costly password check so concurrent/new sessions cannot
    # race around the process-wide attempt budget. Successful attempts count too.
    limiter.reserve(scope, now)
    if not config.verify(username, password):
        failed = [stamp for stamp in attempts.get('failed', []) if stamp > now - 60]
        failed.append(now)
        until = now + 60 if len(failed) >= 5 else 0
        session[_ATTEMPTS_KEY] = {'failed': failed[-5:], 'until': until}
        return False
    # No prior login's draft/API form values may survive into a new identity.
    session.clear()
    session[_AUTH_KEY] = {
        'user': config.user,
        'revision': config.revision,
        'issued': now,
        'expires': now + config.ttl,
    }
    return True


def logout(session: MutableMapping):
    session.clear()


def require_access(streamlit=None):
    """Stop the app before workspace/database access until remote login succeeds."""
    if not remote_access_required():
        return None
    if streamlit is None:
        import streamlit
    st = streamlit
    try:
        config = load_access_config()
    except AccessConfigurationError as exc:
        logout(st.session_state)
        st.error(str(exc))
        st.stop()
        return None
    user = authenticated_user(st.session_state, config)
    if user:
        with st.sidebar:
            st.caption(f'Đã đăng nhập: {user}')
            if st.button('Đăng xuất', key='_fric_logout'):
                logout(st.session_state)
                st.rerun()
        return user
    if st.session_state.pop('_fric_clear_login_password', False):
        st.session_state.pop('_fric_login_password', None)
    st.title('FRIC LAW · Đăng nhập biên tập')
    st.caption('Đăng nhập để mở nguồn nghiên cứu, bản thảo và công cụ duyệt bài.')
    with st.form('_fric_login', clear_on_submit=True):
        username = st.text_input('Tên đăng nhập', value=config.user, key='_fric_login_user')
        password = st.text_input('Mật khẩu', type='password', key='_fric_login_password')
        submit = st.form_submit_button('Đăng nhập')
    if submit:
        try:
            if login(username, password, st.session_state, config):
                st.rerun()
            st.session_state['_fric_login_error'] = 'Tên đăng nhập hoặc mật khẩu không đúng.'
        except LoginRateLimited as exc:
            st.session_state['_fric_login_error'] = f'Tạm khóa đăng nhập. Thử lại sau {exc.retry_after} giây.'
        st.session_state['_fric_clear_login_password'] = True
        st.rerun()
    message = st.session_state.pop('_fric_login_error', '')
    if message:
        st.error(message)
    st.stop()
    return None


def main():
    import argparse
    import getpass

    parser = argparse.ArgumentParser(
        description='Cấu hình đăng nhập FRIC LAW; không nhận mật khẩu trên dòng lệnh.'
    )
    parser.add_argument('command', choices=('hash', 'validate'))
    args = parser.parse_args()
    if args.command == 'hash':
        password = getpass.getpass('Mật khẩu mới: ')
        confirmation = getpass.getpass('Nhập lại mật khẩu: ')
        if not hmac.compare_digest(password.encode('utf-8'), confirmation.encode('utf-8')):
            parser.exit(1, 'Mật khẩu xác nhận không khớp.\n')
        if len(password) < 12:
            parser.exit(1, 'Dùng mật khẩu có ít nhất 12 ký tự.\n')
        print(make_password_hash(password))
    elif remote_access_required():
        try:
            load_access_config()
        except AccessConfigurationError as exc:
            parser.exit(1, str(exc) + '\n')
        print('Cấu hình đăng nhập từ xa hợp lệ.')
    else:
        print('Đăng nhập từ xa chưa được bật (FRIC_AUTH_REQUIRED).')


if __name__ == '__main__':
    main()
