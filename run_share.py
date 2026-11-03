"""Temporary authenticated Internet access; does not install a boot service.

The original local app on port 8501 is left in place. A separate authenticated
process serves the same workspace on loopback 8502 through Cloudflare Tunnel.
Credentials stay in owner-readable, ignored .runtime/share files.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from access_control import check_password, make_password_hash
import run_local

ROOT = Path(__file__).resolve().parent
SHARE = ROOT / '.runtime' / 'share'
BINARY = ROOT / '.runtime' / 'bin' / 'cloudflared'
URL_PATTERN = re.compile(r'https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com\b')


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def private_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.share-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def prepare_credentials(directory=SHARE):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    access, hashed = directory / 'access.json', directory / 'password.scrypt'
    if access.exists() or hashed.exists():
        try:
            data = json.loads(access.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                raise ValueError
            if data.get('username') != 'editor' or not check_password(
                data['password'], hashed.read_text().strip()
            ):
                raise ValueError
            if os.name != 'nt' and any(p.stat().st_mode & 0o077 for p in (access, hashed)):
                raise ValueError
        except (OSError, KeyError, TypeError, ValueError):
            raise RuntimeError(
                'Tệp đăng nhập chia sẻ thiếu hoặc không hợp lệ; không tự ghi đè mật khẩu.'
            ) from None
    else:
        password = secrets.token_urlsafe(24)
        private_write(hashed, make_password_hash(password) + '\n')
        private_write(access, json.dumps({'username': 'editor', 'password': password}, indent=2) + '\n')
    return access, hashed


def install_cloudflared(binary=BINARY):
    """User-requested local install, verifying the official release SHA-256."""
    import platform
    import requests

    if sys.platform != 'darwin':
        raise RuntimeError('Tự tải hiện hỗ trợ macOS; cài cloudflared chính thức rồi dùng --cloudflared.')
    architecture = 'arm64' if platform.machine() == 'arm64' else 'amd64'
    name = f'cloudflared-darwin-{architecture}.tgz'
    response = requests.get(
        'https://api.github.com/repos/cloudflare/cloudflared/releases/latest', timeout=(5, 25)
    )
    try:
        response.raise_for_status()
        data = response.json()
        asset = next(a for a in data['assets'] if a['name'] == name)
        url, digest = asset['browser_download_url'], asset.get('digest') or ''
        if not url.startswith(
            'https://github.com/cloudflare/cloudflared/releases/download/'
        ) or not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
            raise ValueError
    except (ValueError, KeyError, StopIteration, TypeError):
        raise RuntimeError('Không xác minh được bản phát hành cloudflared chính thức.') from None
    finally:
        response.close()
    download = requests.get(url, timeout=(10, 40), stream=True)
    try:
        download.raise_for_status()
        chunks, size = [], 0
        for chunk in download.iter_content(65536):
            size += len(chunk)
            if size > 64 * 1024 * 1024:
                raise RuntimeError('Bản tải cloudflared vượt giới hạn kích thước.')
            chunks.append(chunk)
        archive = b''.join(chunks)
    finally:
        download.close()
    if hashlib.sha256(archive).hexdigest() != digest.split(':', 1)[1]:
        raise RuntimeError('SHA-256 cloudflared không khớp; không cài đặt.')
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as package:
        entry = next(
            (
                item
                for item in package.getmembers()
                if item.name in ('cloudflared', './cloudflared') and item.isfile()
            ),
            None,
        )
        if entry is None or entry.size > 100 * 1024 * 1024:
            raise RuntimeError('Gói cloudflared không hợp lệ.')
        source = package.extractfile(entry)
        contents = source.read()
    binary = Path(binary)
    binary.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.cloudflared-', dir=binary.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(contents)
        os.chmod(temporary, 0o700)
        subprocess.run(
            [temporary, '--version'],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        os.replace(temporary, binary)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return binary


def read_tunnel(directory=SHARE):
    try:
        state = json.loads((Path(directory) / 'tunnel.json').read_text())
        if (
            not isinstance(state, dict)
            or not isinstance(state.get('pid'), int)
            or isinstance(state['pid'], bool)
            or state['pid'] < 2
        ):
            return None
        if state.get('root') != str(ROOT) or not URL_PATTERN.fullmatch(state.get('url', '')):
            return None
        if not isinstance(state.get('port'), int) or not 1024 <= state['port'] <= 65535:
            return None
        return state
    except (OSError, ValueError, TypeError):
        return None


def owned_tunnel(state):
    if not state:
        return False
    command, created = run_local.process_identity(state['pid'])
    return bool(
        created
        and created == state.get('created')
        and isinstance(state.get('binary'), str)
        and bool(state['binary'])
        and state['binary'] in command
        and f'--url {run_local.url_for(state["port"])}' in command
        and 'tunnel' in command
    )


def stop_tunnel(state):
    if not owned_tunnel(state):
        return
    os.kill(state['pid'], signal.SIGTERM)
    deadline = time.monotonic() + 10
    while owned_tunnel(state) and time.monotonic() < deadline:
        time.sleep(0.1)
    if owned_tunnel(state):
        # The identity is checked again before ending our own stalled connector.
        os.kill(state['pid'], signal.SIGKILL)


def tunnel_ready(state):
    if not owned_tunnel(state) or not isinstance(state.get('metrics_port'), int):
        return False
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{state["metrics_port"]}/ready', timeout=1) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def public_healthy(state, timeout=3):
    """Check the recorded public route, without redirects or any credentials."""
    if not state or not URL_PATTERN.fullmatch(state.get('url', '')):
        return False
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        request = urllib.request.Request(
            state['url'] + '/_stcore/health', headers={'Cache-Control': 'no-cache'}
        )
        with opener.open(request, timeout=max(0.1, min(float(timeout), 3))) as response:
            return response.status == 200 and response.read(16).strip() == b'ok'
    except (OSError, ValueError, urllib.error.URLError):
        return False


def active_problem(state):
    """Return the failed layer instead of equating connector readiness to access."""
    if not owned_tunnel(state):
        return 'Chưa có tunnel thuộc phiên chia sẻ đang chạy; URL cũ có thể đã hết hiệu lực.'
    if not run_local.healthy(state['port']):
        return 'Ứng dụng chia sẻ chưa sẵn sàng; dùng run_share.py recover để khôi phục cùng URL.'
    if not tunnel_ready(state):
        return 'Tunnel đang mất kết nối Cloudflare; dùng run_share.py recover để chờ nối lại cùng URL.'
    if not public_healthy(state):
        return (
            'URL công khai chưa truy cập được dù ứng dụng cục bộ còn chạy; '
            'giữ nguyên tunnel và dùng run_share.py recover để kiểm tra lại.'
        )
    return ''


def _start_backend(state, directory, hashed, timeout=30):
    env_changes = {
        'FRIC_AUTH_REQUIRED': '1',
        'FRIC_ACCESS_HASH_FILE': str(hashed.resolve()),
        'FRIC_ACCESS_USER': 'editor',
        'FRIC_ACCESS_PASSWORD_HASH': '',
        'FRIC_ACCESS_PASSWORD_FILE': '',
        'STREAMLIT_BROWSER_SERVER_ADDRESS': urlsplit(state['url']).hostname,
        'STREAMLIT_BROWSER_SERVER_PORT': '443',
    }
    previous = {name: os.environ.get(name) for name in env_changes}
    try:
        os.environ.update(env_changes)
        return run_local.start(state['port'], directory=Path(directory) / 'server', timeout=timeout)
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _wait_public(state, timeout=30):
    deadline = time.monotonic() + max(0, min(timeout, 30))
    while time.monotonic() < deadline:
        if not owned_tunnel(state):
            return False
        remaining = deadline - time.monotonic()
        if (
            run_local.healthy(state['port'])
            and tunnel_ready(state)
            and public_healthy(state, timeout=min(3, max(0.1, remaining)))
        ):
            return True
        time.sleep(min(0.5, max(0, deadline - time.monotonic())))
    return False


def recover(directory=SHARE, timeout=30):
    """Recover an existing share without rotating its URL or login password."""
    directory = Path(directory)
    deadline = time.monotonic() + max(0, min(timeout, 30))
    with run_local.launch_lock(directory):
        state = read_tunnel(directory)
        if not owned_tunnel(state):
            raise RuntimeError(
                'Tunnel cũ đã dừng hoặc không xác nhận được PID; không thể giữ URL cũ. '
                'Dùng run_share.py start để tạo phiên mới.'
            )
        # Recovery never generates replacement credentials for an existing URL.
        if not all((directory / name).is_file() for name in ('access.json', 'password.scrypt')):
            raise RuntimeError('Thiếu tệp đăng nhập chia sẻ; không tự tạo lại mật khẩu khi khôi phục.')
        _, hashed = prepare_credentials(directory)
        server_dir = directory / 'server'
        server_state = run_local.read_state(server_dir, state['port'])
        owned_server = run_local.owned_process(server_state)
        if not owned_server and run_local.port_busy(state['port']):
            raise RuntimeError(
                'Cổng chia sẻ do tiến trình khác sử dụng; không dừng hoặc chia sẻ tiến trình đó.'
            )
        if not owned_server or not run_local.healthy(state['port']):
            if owned_server:
                run_local.stop(state['port'], server_dir)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError('Hết thời gian khôi phục ứng dụng; tunnel và URL hiện tại vẫn được giữ.')
            _start_backend(state, directory, hashed, timeout=remaining)
        if not _wait_public(state, timeout=deadline - time.monotonic()):
            raise RuntimeError(
                'Chưa xác nhận được URL công khai sau khi chờ nối lại; '
                'tunnel, URL và mật khẩu hiện tại vẫn được giữ. Kiểm tra mạng/VPN rồi dùng recover lại.'
            )
        return state


def resolve_vpn_edges():
    """Process-local workaround for VPNs blocking Go SRV DNS/DoT, keeping TLS.

    cloudflared's internal --edge flag bypasses SRV discovery only. This is
    opt-in for the temporary tunnel; use managed hosting for production.
    """
    import requests

    addresses = []
    for host in ('region1.v2.argotunnel.com', 'region2.v2.argotunnel.com'):
        response = requests.get(
            'https://dns.google/resolve',
            params={'name': host, 'type': 'A', 'edns_client_subnet': '0.0.0.0/0'},
            timeout=(3, 5),
            allow_redirects=False,
        )
        try:
            response.raise_for_status()
            data = response.json()
            if response.is_redirect or data.get('Status') != 0 or data.get('TC'):
                raise ValueError
            found = [
                ipaddress.ip_address(row['data']) for row in data.get('Answer', []) if row.get('type') == 1
            ]
            if not found or not all(ip.version == 4 and ip.is_global for ip in found):
                raise ValueError
            addresses.append(str(found[0]) + ':7844')
        except (ValueError, TypeError, KeyError):
            raise RuntimeError(
                'Không xác minh được DNS công khai của Cloudflare edge; không mở tunnel.'
            ) from None
        finally:
            response.close()
    return addresses


def start(port=8502, directory=SHARE, binary=BINARY, timeout=60, vpn_dns=False):
    directory, binary = Path(directory), Path(binary).resolve()
    if port in (8501, 65535):
        raise RuntimeError('Cổng chia sẻ phải khác 8501 để giữ nguyên ứng dụng cục bộ.')
    if not binary.is_file():
        raise RuntimeError(
            'Chưa cài cloudflared. Dùng run_share.py install hoặc --cloudflared /đường/dẫn/cloudflared.'
        )
    with run_local.launch_lock(directory):
        state = read_tunnel(directory)
        if owned_tunnel(state):
            if state['port'] != port:
                raise RuntimeError('Đang chia sẻ ở cổng khác; dừng phiên chia sẻ hiện tại trước.')
            problem = active_problem(state)
            if problem:
                raise RuntimeError(problem)
            return state, False
        server_dir = directory / 'server'
        server_state = run_local.read_state(server_dir, port)
        if run_local.port_busy(port) and not run_local.owned_process(server_state):
            raise RuntimeError(
                'Cổng chia sẻ đang do tiến trình khác sử dụng; không mở tunnel tới tiến trình đó.'
            )
        if run_local.port_busy(port + 1):
            raise RuntimeError('Cổng kiểm tra tunnel đang được sử dụng; chọn --port khác.')
        _, hashed = prepare_credentials(directory)
        command = [
            str(binary),
            'tunnel',
            '--no-autoupdate',
            '--grace-period',
            '5s',
            '--protocol',
            'http2',
            '--metrics',
            f'127.0.0.1:{port + 1}',
        ]
        if vpn_dns:
            command.append('--no-prechecks')
            for address in resolve_vpn_edges():
                command.extend(['--edge', address])
        command.extend(['--url', run_local.url_for(port)])
        log_path = directory / 'tunnel.log'
        # Fresh log prevents stale URLs from being mistaken for a new tunnel.
        fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'wb') as log:
            child = subprocess.Popen(
                command,
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        _, created = run_local.process_identity(child.pid)
        state = {
            'pid': child.pid,
            'created': created,
            'root': str(ROOT),
            'binary': str(binary),
            'port': port,
            'metrics_port': port + 1,
            'url': '',
        }
        server_created = False
        try:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    raise RuntimeError(
                        'Không tạo được tunnel. Xem .runtime/share/tunnel.log; có thể mạng/VPN chặn kết nối.'
                    )
                match = URL_PATTERN.search(log_path.read_text(errors='replace'))
                if match:
                    state['url'] = match.group(0)
                    break
                time.sleep(0.2)
            if not state['url']:
                raise RuntimeError('Hết thời gian tạo URL chia sẻ; xem .runtime/share/tunnel.log.')
            while time.monotonic() < deadline and child.poll() is None:
                if tunnel_ready(state):
                    break
                time.sleep(0.2)
            if not tunnel_ready(state):
                raise RuntimeError(
                    'Tunnel chưa kết nối được Cloudflare. Kiểm tra mạng/VPN hoặc thử --vpn-dns; chưa có URL hoạt động.'
                )
            # A fresh Quick Tunnel has a new hostname. An old backend cannot
            # inherit the new origin/auth settings by merely reusing its PID.
            if run_local.owned_process(server_state):
                run_local.stop(port, server_dir)
            # Never pass credentials on the command line or log them.
            _, server_created = _start_backend(state, directory, hashed)
            private_write(directory / 'tunnel.json', json.dumps(state))
        except BaseException:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=10)
            if server_created:
                run_local.stop(port, server_dir)
            raise
        # A public routing delay must not destroy a provisioned Quick Tunnel:
        # replacing its connector also invalidates the URL just created.
        if not _wait_public(state, timeout=max(1, deadline - time.monotonic())):
            raise RuntimeError(
                'Tunnel đã tạo nhưng URL công khai chưa được xác nhận truy cập. '
                'Giữ nguyên phiên; dùng run_share.py recover để kiểm tra lại cùng URL.'
            )
        return state, True


def stop(directory=SHARE):
    directory = Path(directory)
    with run_local.launch_lock(directory):
        state = read_tunnel(directory)
        stop_tunnel(state)
        # Refuse stale/reused PIDs through the local launcher's identity checks.
        if state:
            run_local.stop(state['port'], directory / 'server')
        (directory / 'tunnel.json').unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Chia sẻ FRIC LAW bằng link HTTPS tạm thời có đăng nhập.')
    parser.add_argument(
        'action',
        choices=['install', 'start', 'stop', 'restart', 'recover', 'status'],
        nargs='?',
        default='start',
    )
    parser.add_argument('--port', type=run_local.port_argument, default=8502)
    parser.add_argument('--cloudflared', type=Path, default=BINARY)
    parser.add_argument(
        '--vpn-dns',
        action='store_true',
        help='Dùng DNS-over-HTTPS riêng cho tunnel khi VPN chặn SRV DNS; không đổi DNS hệ thống.',
    )
    args = parser.parse_args(argv)
    try:
        if args.action == 'install':
            install_cloudflared(args.cloudflared)
            print('Đã cài cloudflared vào .runtime/bin; SHA-256 đã khớp bản phát hành chính thức.')
            return 0
        if args.action in ('stop', 'restart'):
            stop()
            if args.action == 'stop':
                print('Đã dừng link chia sẻ. Ứng dụng cục bộ cổng 8501 vẫn giữ nguyên.')
                return 0
        if args.action == 'status':
            state = read_tunnel()
            problem = active_problem(state)
            if problem:
                print(problem)
                return 1
        elif args.action == 'recover':
            state = recover()
        else:
            state, _ = start(args.port, binary=args.cloudflared, vpn_dns=args.vpn_dns)
        print('URL chia sẻ tạm thời: ' + state['url'])
        print('Tệp đăng nhập riêng trên máy: ' + str(SHARE / 'access.json'))
        print('Giữ Mac thức và có Internet. URL đổi khi khởi động lại tunnel; đây chưa phải hosting 24/7.')
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        # Application-created errors contain paths/statuses, never raw server responses or passwords.
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
