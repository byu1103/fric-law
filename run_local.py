"""Start the local studio independently of the terminal/chat that launched it."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / '.runtime'
HOST = '127.0.0.1'


def url_for(port):
    return f'http://{HOST}:{port}'


def healthy(port):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url_for(port) + '/_stcore/health', timeout=0.7) as response:
            return response.status == 200 and response.read(16).strip() == b'ok'
    except (OSError, urllib.error.URLError):
        return False


def port_busy(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        try:
            # A stopped web server can leave TIME_WAIT connections. Match its
            # Unix reuse policy, then listen to still detect a live listener.
            if os.name != 'nt':
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((HOST, port))
            listener.listen(1)
            return False
        except OSError:
            return True


@contextmanager
def launch_lock(directory):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / 'launcher.lock').open('a+b') as handle:
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


def state_path(directory, port):
    return directory / f'server-{port}.json'


def read_state(directory, port):
    try:
        value = json.loads(state_path(directory, port).read_text(encoding='utf-8'))
        if (
            not isinstance(value, dict)
            or isinstance(value.get('pid'), bool)
            or not isinstance(value.get('pid'), int)
            or value['pid'] < 2
            or value.get('root') != str(ROOT)
            or value.get('port') != port
        ):
            return None
        return value
    except (OSError, ValueError, TypeError):
        return None


def write_state(directory, port, value):
    fd, temporary = tempfile.mkstemp(prefix='.server-', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump(value, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, state_path(directory, port))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def process_identity(pid):
    """Inspect process identity before reusing or signalling a recorded PID."""
    try:
        if os.name == 'nt':
            command = subprocess.check_output(
                [
                    'powershell',
                    '-NoProfile',
                    '-Command',
                    f'Get-CimInstance Win32_Process -Filter "ProcessId = {int(pid)}" | Select-Object CommandLine,CreationDate | ConvertTo-Json -Compress',
                ],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).strip()
            info = json.loads(command)
            return str(info['CommandLine']), str(info['CreationDate'])
        command = subprocess.check_output(
            ['ps', '-p', str(int(pid)), '-o', 'command='],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).strip()
        created = subprocess.check_output(
            ['ps', '-p', str(int(pid)), '-o', 'lstart='],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).strip()
        return command, created
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError):
        return '', ''


def owned_process(state):
    if not state:
        return False
    command, created = process_identity(state['pid'])
    return bool(
        created
        and created == state.get('created')
        and str(ROOT / 'app.py') in command
        and 'streamlit run' in command
        and re.search(r'--server\.port(?:=|\s+)' + str(state['port']) + r'(?:\s|$)', command)
    )


def wait_ready(port, child=None, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if healthy(port):
            return True
        if child is not None and child.poll() is not None:
            return False
        time.sleep(0.15)
    return False


def start(port=8501, directory=RUNTIME, timeout=30):
    directory = Path(directory)
    with launch_lock(directory):
        state = read_state(directory, port)
        if owned_process(state):
            if healthy(port) or wait_ready(port, timeout=timeout):
                return state, False
            raise RuntimeError(
                f'Tiến trình đang chạy nhưng chưa sẵn sàng. Xem log: {directory / "server.log"}; dùng lệnh restart để khởi động lại.'
            )
        if port_busy(port):
            raise RuntimeError(
                f'Cổng {port} đang do tiến trình khác sử dụng. Không dừng tiến trình đó; chọn cổng khác bằng --port.'
            )
        command = [
            sys.executable,
            '-m',
            'streamlit',
            'run',
            str(ROOT / 'app.py'),
            '--server.address',
            HOST,
            '--server.port',
            str(port),
            '--server.headless',
            'true',
            '--browser.gatherUsageStats',
            'false',
        ]
        log_path = directory / 'server.log'
        with log_path.open('ab') as log:
            if os.name != 'nt':
                os.chmod(log_path, 0o600)
            arguments = dict(
                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, close_fds=True
            )
            if os.name == 'nt':
                arguments['creationflags'] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                arguments['start_new_session'] = True
            child = subprocess.Popen(command, **arguments)
        # Capture identity while this PID is known to be our child. Do not persist secrets.
        _, created = process_identity(child.pid)
        state = {'pid': child.pid, 'root': str(ROOT), 'port': port, 'created': created, 'url': url_for(port)}
        write_state(directory, port, state)
        if not wait_ready(port, child, timeout):
            raise RuntimeError(f'Ứng dụng chưa khởi động thành công. Xem log cục bộ: {log_path}')
        return state, True


def stop(port=8501, directory=RUNTIME):
    directory = Path(directory)
    with launch_lock(directory):
        state = read_state(directory, port)
        if not state:
            return False
        if not owned_process(state):
            if port_busy(port):
                raise RuntimeError(
                    'Không xác nhận được PID thuộc ứng dụng này; không tự động dừng tiến trình.'
                )
            state_path(directory, port).unlink(missing_ok=True)
            return False
        os.kill(state['pid'], signal.SIGTERM)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if not owned_process(state):
                state_path(directory, port).unlink(missing_ok=True)
                return True
            time.sleep(0.1)
        raise RuntimeError('Ứng dụng chưa dừng xong. Kiểm tra log trước khi khởi động lại.')


def port_argument(value):
    try:
        number = int(value)
        if 1024 <= number <= 65535:
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError('Cổng phải là số nguyên từ 1024 đến 65535.')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Khởi động FRIC LAW Content Studio trên máy này.')
    parser.add_argument('action', choices=['start', 'stop', 'restart', 'status'], nargs='?', default='start')
    parser.add_argument('--port', type=port_argument, default=8501)
    parser.add_argument('--open-browser', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.action in ('stop', 'restart'):
            changed = stop(args.port)
            if args.action == 'stop':
                print('Đã dừng ứng dụng.' if changed else 'Ứng dụng chưa chạy.')
                return 0
        if args.action == 'status':
            ready = owned_process(read_state(RUNTIME, args.port)) and healthy(args.port)
            print(('Đang chạy: ' if ready else 'Chưa chạy: ') + url_for(args.port))
            return 0 if ready else 1
        state, created = start(args.port)
        print(('Đã khởi động. ' if created else 'Ứng dụng đã chạy sẵn. ') + 'URL: ' + state['url'])
        print('Log: ' + str(RUNTIME / 'server.log'))
        if args.open_browser:
            webbrowser.open(state['url'])
        return 0
    except (OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
