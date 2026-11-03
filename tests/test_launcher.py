"""Local launcher lifecycle and ephemeral socket tests, without user workspace."""

import json
import os
import signal
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import run_local as launcher


class TestLocalLauncher(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.port = 18501
        self.created = 'Fri Oct 23 09:00:00 2026'
        self.state = {
            'pid': 23456,
            'root': str(launcher.ROOT),
            'port': self.port,
            'created': self.created,
            'url': launcher.url_for(self.port),
        }
        self.command = (
            f'python -m streamlit run {launcher.ROOT / "app.py"} '
            f'--server.address 127.0.0.1 --server.port {self.port}'
        )

    def tearDown(self):
        self.temp.cleanup()

    def save_state(self, value):
        launcher.state_path(self.directory, self.port).write_text(json.dumps(value), encoding='utf-8')

    def test_repeated_start_reuses_server_and_launches_detached_without_shell(self):
        child = Mock(pid=self.state['pid'])
        with (
            patch.object(launcher, 'port_busy', return_value=False),
            patch.object(launcher, 'process_identity', return_value=(self.command, self.created)),
            patch.object(launcher, 'wait_ready', return_value=True),
            patch.object(launcher, 'healthy', return_value=True),
            patch.object(launcher.subprocess, 'Popen', return_value=child) as spawn,
        ):
            first, created = launcher.start(self.port, self.directory)
            again, created_again = launcher.start(self.port, self.directory)

        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first, again)
        spawn.assert_called_once()
        arguments, options = spawn.call_args
        command = arguments[0]
        self.assertIsInstance(command, list)
        self.assertEqual(command[:4], [launcher.sys.executable, '-m', 'streamlit', 'run'])
        self.assertEqual(command[4], str(launcher.ROOT / 'app.py'))
        self.assertIn('--server.headless', command)
        self.assertEqual(command[command.index('--server.port') + 1], str(self.port))
        self.assertEqual(command[command.index('--server.address') + 1], '127.0.0.1')
        self.assertFalse(options.get('shell', False))
        self.assertEqual(options['stdin'], subprocess.DEVNULL)
        self.assertEqual(options['stderr'], subprocess.STDOUT)
        self.assertEqual(options['cwd'], launcher.ROOT)
        if os.name == 'nt':
            self.assertTrue(options['creationflags'] & subprocess.DETACHED_PROCESS)
        else:
            self.assertTrue(options['start_new_session'])

    def test_occupied_unrelated_port_is_not_replaced_or_signalled(self):
        with (
            patch.object(launcher, 'port_busy', return_value=True),
            patch.object(launcher.subprocess, 'Popen') as spawn,
            patch.object(launcher.os, 'kill') as kill,
        ):
            with self.assertRaisesRegex(RuntimeError, 'Cổng .* tiến trình khác'):
                launcher.start(self.port, self.directory)
        spawn.assert_not_called()
        kill.assert_not_called()
        self.assertFalse(launcher.state_path(self.directory, self.port).exists())

    def test_malformed_state_cannot_be_used_to_signal_a_process(self):
        values = [
            [],
            {},
            dict(self.state, pid=True),
            dict(self.state, pid='23456'),
            dict(self.state, pid=1),
            dict(self.state, root='/unrelated/project'),
            dict(self.state, port=self.port + 1),
        ]
        with patch.object(launcher.os, 'kill') as kill:
            for value in values:
                with self.subTest(state=value):
                    self.save_state(value)
                    self.assertIsNone(launcher.read_state(self.directory, self.port))
                    self.assertFalse(launcher.stop(self.port, self.directory))
            launcher.state_path(self.directory, self.port).write_text('{bad JSON', encoding='utf-8')
            self.assertIsNone(launcher.read_state(self.directory, self.port))
            self.assertFalse(launcher.stop(self.port, self.directory))
        kill.assert_not_called()

    def test_stale_state_on_a_free_port_is_replaced_by_new_child(self):
        self.save_state(self.state)
        child = Mock(pid=34567)
        identities = [('', ''), (self.command, 'new child creation time')]
        with (
            patch.object(launcher, 'process_identity', side_effect=identities),
            patch.object(launcher, 'port_busy', return_value=False),
            patch.object(launcher, 'wait_ready', return_value=True),
            patch.object(launcher.subprocess, 'Popen', return_value=child) as spawn,
            patch.object(launcher.os, 'kill') as kill,
        ):
            state, created = launcher.start(self.port, self.directory)
        self.assertTrue(created)
        self.assertEqual(state['pid'], 34567)
        self.assertEqual(launcher.read_state(self.directory, self.port), state)
        spawn.assert_called_once()
        kill.assert_not_called()

    def test_stop_only_signals_recorded_process_with_matching_identity(self):
        self.save_state(self.state)
        with (
            patch.object(launcher, 'process_identity', side_effect=[(self.command, self.created), ('', '')]),
            patch.object(launcher.os, 'kill') as kill,
        ):
            self.assertTrue(launcher.stop(self.port, self.directory))
        kill.assert_called_once_with(self.state['pid'], signal.SIGTERM)
        self.assertFalse(launcher.state_path(self.directory, self.port).exists())

    def test_reused_pid_or_wrong_command_is_never_stopped(self):
        identities = [
            (self.command, 'different process creation time'),
            ('python unrelated.py', self.created),
            (self.command.replace(str(self.port), str(self.port + 1)), self.created),
        ]
        for identity in identities:
            with self.subTest(identity=identity):
                self.save_state(self.state)
                with (
                    patch.object(launcher, 'process_identity', return_value=identity),
                    patch.object(launcher, 'port_busy', return_value=True),
                    patch.object(launcher.os, 'kill') as kill,
                ):
                    with self.assertRaisesRegex(RuntimeError, 'Không xác nhận được PID'):
                        launcher.stop(self.port, self.directory)
                kill.assert_not_called()
                self.assertTrue(launcher.state_path(self.directory, self.port).exists())

    def test_startup_health_failure_points_to_local_log_without_exposing_secret(self):
        secret = 'synthetic-secret-must-not-appear'
        child = Mock(pid=self.state['pid'])
        with (
            patch.dict(os.environ, {'OPENAI_API_KEY': secret}),
            patch.object(launcher, 'port_busy', return_value=False),
            patch.object(launcher, 'process_identity', return_value=(self.command, self.created)),
            patch.object(launcher, 'wait_ready', return_value=False),
            patch.object(launcher.subprocess, 'Popen', return_value=child),
        ):
            with self.assertRaises(RuntimeError) as caught:
                launcher.start(self.port, self.directory, timeout=0.1)
        message = str(caught.exception)
        self.assertIn(str(self.directory / 'server.log'), message)
        self.assertNotIn(secret, message)
        self.assertNotIn(secret, launcher.state_path(self.directory, self.port).read_text())
        self.assertNotIn(secret, (self.directory / 'server.log').read_text())

    def test_readiness_stops_waiting_when_healthy_child_exits_or_timeout_elapses(self):
        child = Mock()
        with patch.object(launcher, 'healthy', return_value=True):
            self.assertTrue(launcher.wait_ready(self.port, child, timeout=1))
        child.poll.assert_not_called()
        child.poll.return_value = 1
        with (
            patch.object(launcher, 'healthy', return_value=False),
            patch.object(launcher.time, 'sleep') as sleep,
        ):
            self.assertFalse(launcher.wait_ready(self.port, child, timeout=1))
        sleep.assert_not_called()
        with (
            patch.object(launcher, 'healthy', return_value=False),
            patch.object(launcher.time, 'monotonic', side_effect=[0, 0.1, 1.1]),
            patch.object(launcher.time, 'sleep') as sleep,
        ):
            self.assertFalse(launcher.wait_ready(self.port, timeout=1))
        sleep.assert_called_once()


class TestRestartPortProbe(unittest.TestCase):
    def test_live_listener_is_busy_even_when_socket_reuse_is_enabled(self):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            self.assertTrue(launcher.port_busy(listener.getsockname()[1]))

    @unittest.skipIf(os.name == 'nt', 'Unix TIME_WAIT port reuse policy')
    def test_closed_http_connection_does_not_prevent_server_restart(self):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
            listener.listen(1)
            with socket.create_connection(('127.0.0.1', port), timeout=2) as client:
                accepted, _ = listener.accept()
                with accepted:
                    accepted.shutdown(socket.SHUT_WR)
                    self.assertEqual(client.recv(1), b'')
        self.assertFalse(launcher.port_busy(port))


if __name__ == '__main__':
    unittest.main()
