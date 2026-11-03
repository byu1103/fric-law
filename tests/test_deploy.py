"""Production startup must fail closed and serve on the host-assigned port."""

import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from access_control import AccessConfigurationError, make_password_hash
from deploy.entrypoint import ROOT, server_command


class DeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_hash = make_password_hash('Synthetic deployment test credential')

    def test_missing_credentials_fail_before_workspace_is_created(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / 'not-created'
            with patch.dict(os.environ, {'FRIC_WORKSPACE': str(workspace)}, clear=True):
                with self.assertRaises(AccessConfigurationError):
                    server_command()
            self.assertFalse(workspace.exists())

    def test_invalid_port_or_relative_storage_is_rejected(self):
        for changes in ({'PORT': 'invalid'}, {'PORT': '0'}, {'FRIC_WORKSPACE': './ephemeral'}):
            with self.subTest(changes=changes):
                values = {'FRIC_ACCESS_PASSWORD_HASH': self.test_hash, **changes}
                with patch.dict(os.environ, values, clear=True):
                    with self.assertRaises(ValueError):
                        server_command()

    def test_workspace_probe_does_not_leave_files_and_remote_login_is_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            values = {
                'FRIC_ACCESS_PASSWORD_HASH': self.test_hash,
                'FRIC_WORKSPACE': temporary,
                'FRIC_AUTH_REQUIRED': '0',
            }
            with patch.dict(os.environ, values, clear=True):
                command = server_command()
                self.assertEqual(os.environ['FRIC_AUTH_REQUIRED'], '1')
                self.assertEqual(os.environ['FRIC_HOSTED'], '1')
                self.assertIn('--server.enableXsrfProtection=true', command)
                self.assertIn('--server.enableCORS=true', command)
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_file_instead_of_workspace_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / 'occupied'
            workspace.write_text('not a directory', encoding='utf-8')
            values = {'FRIC_ACCESS_PASSWORD_HASH': self.test_hash, 'FRIC_WORKSPACE': str(workspace)}
            with patch.dict(os.environ, values, clear=True):
                with self.assertRaisesRegex(ValueError, 'not writable'):
                    server_command()

    def test_invalid_configuration_does_not_echo_credential(self):
        secret = 'synthetic-invalid-credential-do-not-echo'
        values = {**os.environ, 'FRIC_ACCESS_PASSWORD_HASH': secret}
        result = subprocess.run(
            [sys.executable, str(ROOT / 'deploy' / 'entrypoint.py')],
            env=values,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(secret, result.stdout + result.stderr)

    def test_actual_foreground_server_health_on_assigned_port(self):
        with tempfile.TemporaryDirectory() as temporary:
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                port = listener.getsockname()[1]
            values = {
                **os.environ,
                'FRIC_ACCESS_PASSWORD_HASH': self.test_hash,
                'FRIC_WORKSPACE': temporary,
                'PORT': str(port),
            }
            # No user workspace, credentials, or production port are used.
            with tempfile.TemporaryFile(mode='w+b') as output:
                process = subprocess.Popen(
                    [sys.executable, str(ROOT / 'deploy' / 'entrypoint.py')],
                    env=values,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                )
                try:
                    ready = False
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    deadline = time.monotonic() + 20
                    while time.monotonic() < deadline and process.poll() is None:
                        try:
                            with opener.open(
                                f'http://127.0.0.1:{port}/_stcore/health', timeout=0.5
                            ) as response:
                                ready = response.status == 200 and response.read().strip() == b'ok'
                                if ready:
                                    break
                        except (OSError, urllib.error.URLError):
                            time.sleep(0.1)
                    self.assertTrue(ready, 'Production foreground launcher did not become healthy.')
                    self.assertIsNone(process.poll())
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
