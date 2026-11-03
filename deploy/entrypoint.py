"""Foreground production launcher: authenticated access and durable workspace."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Running the saved script directly must import the application next to deploy/.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from access_control import AccessConfigurationError, load_access_config  # noqa: E402


def server_command():
    """Validate deployment before binding a public port or creating a database."""
    # This launcher is exclusively for shared deployment. Local use retains the
    # existing run_local.py workflow and does not require a shared password.
    os.environ['FRIC_AUTH_REQUIRED'] = '1'
    os.environ['FRIC_HOSTED'] = '1'
    load_access_config()

    try:
        port = int(os.environ.get('PORT', '8501'))
        if not 1024 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise ValueError('PORT must be an integer from 1024 to 65535.') from None

    workspace = Path(os.environ.get('FRIC_WORKSPACE', '/data')).expanduser()
    if not workspace.is_absolute():
        raise ValueError('FRIC_WORKSPACE must be an absolute persistent-disk path.')
    try:
        workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryFile(dir=workspace) as probe:
            probe.write(b'workspace-check')
            probe.flush()
    except OSError:
        raise ValueError('The persistent workspace is not writable by the application user.') from None
    os.environ['FRIC_WORKSPACE'] = str(workspace)

    return [
        sys.executable,
        '-m',
        'streamlit',
        'run',
        str(ROOT / 'app.py'),
        '--server.address=0.0.0.0',
        f'--server.port={port}',
        '--server.headless=true',
        '--server.enableCORS=true',
        '--server.enableXsrfProtection=true',
        '--server.enableStaticServing=false',
        '--server.fileWatcherType=none',
        '--browser.gatherUsageStats=false',
    ]


def main():
    os.umask(0o077)
    try:
        command = server_command()
    except (AccessConfigurationError, ValueError) as exc:
        print(f'Deployment configuration error: {exc}', file=sys.stderr)
        return 1
    os.chdir(ROOT)
    os.execv(command[0], command)


if __name__ == '__main__':
    raise SystemExit(main())
