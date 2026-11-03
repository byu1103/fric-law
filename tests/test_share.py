"""Temporary sharing must preserve credentials and never control unrelated PIDs."""

import json
import io
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

import run_share
from access_control import check_password, make_password_hash


class SharingTests(unittest.TestCase):
    @staticmethod
    def state(**changes):
        return {
            'pid': 987654,
            'created': 'synthetic-process-created-time',
            'root': str(run_share.ROOT),
            'binary': '/private/tmp/synthetic-cloudflared',
            'port': 8502,
            'metrics_port': 8503,
            'url': 'https://synthetic-studio.trycloudflare.com',
            **changes,
        }

    def test_credentials_private_and_stable_on_reuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'share'
            access, hashed = run_share.prepare_credentials(directory)
            before = {path: path.read_bytes() for path in (access, hashed)}
            values = json.loads(access.read_text())
            self.assertEqual(values['username'], 'editor')
            self.assertTrue(check_password(values['password'], hashed.read_text().strip()))
            if os.name != 'nt':
                self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
                for path in (access, hashed):
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with patch('run_share.secrets.token_urlsafe', side_effect=AssertionError('must not rotate')):
                self.assertEqual(run_share.prepare_credentials(directory), (access, hashed))
            self.assertEqual(before, {path: path.read_bytes() for path in (access, hashed)})

    def test_missing_invalid_or_mismatched_credentials_are_not_overwritten(self):
        for failure in (
            'missing-access',
            'missing-hash',
            'bad-json',
            'json-list',
            'json-null',
            'missing-password',
            'wrong-user',
            'mismatch',
        ):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                access, hashed = run_share.prepare_credentials(directory)
                if failure == 'missing-access':
                    access.unlink()
                elif failure == 'missing-hash':
                    hashed.unlink()
                elif failure == 'bad-json':
                    access.write_text('{broken', encoding='utf-8')
                elif failure == 'json-list':
                    access.write_text('[]', encoding='utf-8')
                elif failure == 'json-null':
                    access.write_text('null', encoding='utf-8')
                elif failure == 'missing-password':
                    access.write_text(json.dumps({'username': 'editor'}), encoding='utf-8')
                elif failure == 'wrong-user':
                    access.write_text(
                        json.dumps({'username': 'other', 'password': 'synthetic'}), encoding='utf-8'
                    )
                else:
                    hashed.write_text(make_password_hash('a different synthetic password'), encoding='utf-8')
                before = {path.name: path.read_bytes() for path in directory.iterdir()}
                with self.assertRaises(RuntimeError):
                    run_share.prepare_credentials(directory)
                self.assertEqual(before, {path.name: path.read_bytes() for path in directory.iterdir()})

    def test_exposed_credentials_refuse_reuse(self):
        if os.name == 'nt':
            return
        with tempfile.TemporaryDirectory() as temporary:
            access, hashed = run_share.prepare_credentials(temporary)
            os.chmod(access, 0o644)
            before = access.read_bytes(), hashed.read_bytes()
            with self.assertRaises(RuntimeError):
                run_share.prepare_credentials(temporary)
            self.assertEqual(before, (access.read_bytes(), hashed.read_bytes()))

    def test_read_state_accepts_valid_and_rejects_bad_identity_url_or_port(self):
        invalid = [
            {'pid': True},
            {'pid': 1},
            {'pid': '987654'},
            {'root': '/unrelated/project'},
            {'url': 'http://synthetic-studio.trycloudflare.com'},
            {'url': 'https://synthetic-studio.trycloudflare.com.evil.example'},
            {'url': 'https://synthetic-studio.trycloudflare.com/path'},
            {'port': 1023},
            {'port': 65536},
            {'port': '8502'},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'tunnel.json'
            target.write_text(json.dumps(self.state()), encoding='utf-8')
            self.assertEqual(run_share.read_tunnel(temporary), self.state())
            for changes in invalid:
                with self.subTest(changes=changes):
                    target.write_text(json.dumps(self.state(**changes)), encoding='utf-8')
                    self.assertIsNone(run_share.read_tunnel(temporary))
            for raw in ('not-json', '[]', 'null'):
                target.write_text(raw, encoding='utf-8')
                self.assertIsNone(run_share.read_tunnel(temporary))
            target.unlink()
            self.assertIsNone(run_share.read_tunnel(temporary))

    def test_owned_tunnel_checks_command_port_binary_and_creation_time(self):
        state = self.state()
        command = f'{state["binary"]} tunnel --url http://127.0.0.1:8502'
        for identity, expected in (
            ((command, state['created']), True),
            ((command, 'different-creation-time'), False),
            ((command, ''), False),
            (('/private/tmp/other tunnel --url http://127.0.0.1:8502', state['created']), False),
            ((command.replace('8502', '8504'), state['created']), False),
            ((command.replace('tunnel', 'version'), state['created']), False),
        ):
            with self.subTest(identity=identity):
                with patch('run_share.run_local.process_identity', return_value=identity):
                    self.assertEqual(run_share.owned_tunnel(state), expected)
        with patch('run_share.run_local.process_identity') as inspect:
            self.assertFalse(run_share.owned_tunnel(None))
            inspect.assert_not_called()

    def test_stop_tunnel_never_signals_unowned_pid(self):
        state = self.state()
        with (
            patch('run_share.run_local.process_identity', return_value=('unrelated command', 'other-time')),
            patch('run_share.os.kill') as kill,
        ):
            run_share.stop_tunnel(state)
            kill.assert_not_called()

    def test_tunnel_ready_requires_owned_connector_and_ready_http_200(self):
        state = self.state()
        with (
            patch('run_share.owned_tunnel', return_value=False),
            patch('run_share.urllib.request.build_opener') as build,
        ):
            self.assertFalse(run_share.tunnel_ready(state))
            build.assert_not_called()
        for status, expected in ((200, True), (302, False), (503, False)):
            with self.subTest(status=status):
                response = Mock(status=status)
                response.__enter__ = Mock(return_value=response)
                response.__exit__ = Mock(return_value=False)
                opener = Mock()
                opener.open.return_value = response
                with (
                    patch('run_share.owned_tunnel', return_value=True),
                    patch('run_share.urllib.request.build_opener', return_value=opener),
                ):
                    self.assertEqual(run_share.tunnel_ready(state), expected)
                opener.open.assert_called_once_with('http://127.0.0.1:8503/ready', timeout=1)

    def test_tunnel_ready_handles_missing_metrics_and_network_failure(self):
        with (
            patch('run_share.owned_tunnel', return_value=True),
            patch('run_share.urllib.request.build_opener') as build,
        ):
            self.assertFalse(run_share.tunnel_ready(self.state(metrics_port='8503')))
            build.assert_not_called()
        opener = Mock()
        opener.open.side_effect = urllib.error.URLError('synthetic offline')
        with (
            patch('run_share.owned_tunnel', return_value=True),
            patch('run_share.urllib.request.build_opener', return_value=opener),
        ):
            self.assertFalse(run_share.tunnel_ready(self.state()))

    def test_public_health_checks_exact_url_body_and_does_not_follow_redirects(self):
        for status, body, expected in (
            (200, b'ok', True),
            (200, b'Cloudflare error 1033', False),
            (302, b'ok', False),
            (503, b'ok', False),
        ):
            with self.subTest(status=status, body=body):
                response = Mock(status=status)
                response.read.return_value = body
                response.__enter__ = Mock(return_value=response)
                response.__exit__ = Mock(return_value=False)
                opener = Mock()
                opener.open.return_value = response
                with patch('run_share.urllib.request.build_opener', return_value=opener) as build:
                    self.assertEqual(run_share.public_healthy(self.state()), expected)
                request = opener.open.call_args.args[0]
                self.assertEqual(request.full_url, self.state()['url'] + '/_stcore/health')
                self.assertNotIn('Authorization', request.headers)
                self.assertEqual(opener.open.call_args.kwargs, {'timeout': 3.0})
                self.assertIsInstance(build.call_args.args[1], run_share._NoRedirect)
                self.assertIsNone(
                    build.call_args.args[1].redirect_request(None, None, 302, '', {}, 'https://other.example')
                )
                if status == 200:
                    response.read.assert_called_once_with(16)
                else:
                    response.read.assert_not_called()

    def test_public_health_rejects_bad_urls_and_network_errors(self):
        with patch('run_share.urllib.request.build_opener') as build:
            for state in (
                None,
                self.state(url='http://wrong.trycloudflare.com'),
                self.state(url=self.state()['url'] + '/unexpected'),
            ):
                self.assertFalse(run_share.public_healthy(state))
            build.assert_not_called()
        opener = Mock()
        opener.open.side_effect = urllib.error.URLError('synthetic network failure')
        with patch('run_share.urllib.request.build_opener', return_value=opener):
            self.assertFalse(run_share.public_healthy(self.state(), timeout=99))
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 3)

    def test_active_problem_distinguishes_backend_connector_and_public_route(self):
        for owned, backend, connector, public, expected in (
            (False, True, True, True, 'Chưa có tunnel'),
            (True, False, True, True, 'Ứng dụng chia sẻ'),
            (True, True, False, True, 'mất kết nối Cloudflare'),
            (True, True, True, False, 'URL công khai'),
            (True, True, True, True, ''),
        ):
            with (
                self.subTest(expected=expected),
                patch('run_share.owned_tunnel', return_value=owned),
                patch('run_share.run_local.healthy', return_value=backend),
                patch('run_share.tunnel_ready', return_value=connector),
                patch('run_share.public_healthy', return_value=public),
            ):
                message = run_share.active_problem(self.state())
                if expected:
                    self.assertIn(expected, message)
                else:
                    self.assertEqual(message, '')

    def test_start_existing_connector_public_failure_does_not_rotate_url(self):
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / 'cloudflared'
            binary.touch()
            with (
                patch('run_share.read_tunnel', return_value=self.state()),
                patch('run_share.owned_tunnel', return_value=True),
                patch('run_share.run_local.healthy', return_value=True),
                patch('run_share.tunnel_ready', return_value=True),
                patch('run_share.public_healthy', return_value=False),
                patch('run_share.stop_tunnel') as stop,
                patch('run_share.subprocess.Popen') as popen,
            ):
                with self.assertRaisesRegex(RuntimeError, 'recover'):
                    run_share.start(directory=Path(temporary) / 'share', binary=binary)
                stop.assert_not_called()
                popen.assert_not_called()

    def test_created_tunnel_public_delay_preserves_connector_and_saved_url(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'share'
            binary = Path(temporary) / 'cloudflared'
            binary.touch()
            child = Mock(pid=987654)
            child.poll.return_value = None

            def launch(*args, **kwargs):
                (directory / 'tunnel.log').write_text(self.state()['url'], encoding='utf-8')
                return child

            with (
                patch('run_share.read_tunnel', return_value=None),
                patch('run_share.owned_tunnel', return_value=False),
                patch('run_share.run_local.read_state', return_value=None),
                patch('run_share.run_local.port_busy', return_value=False),
                patch(
                    'run_share.prepare_credentials',
                    return_value=(directory / 'access.json', directory / 'password.scrypt'),
                ),
                patch('run_share.subprocess.Popen', side_effect=launch),
                patch(
                    'run_share.run_local.process_identity', return_value=('synthetic', 'synthetic-created')
                ),
                patch('run_share.tunnel_ready', return_value=True),
                patch('run_share._start_backend', return_value=({}, True)),
                patch('run_share._wait_public', return_value=False),
                patch('run_share.run_local.stop') as stop,
            ):
                with self.assertRaisesRegex(RuntimeError, 'recover'):
                    run_share.start(directory=directory, binary=binary)
            self.assertEqual(json.loads((directory / 'tunnel.json').read_text())['url'], self.state()['url'])
            child.terminate.assert_not_called()
            child.wait.assert_not_called()
            stop.assert_not_called()

    def test_fresh_tunnel_reloads_owned_backend_for_new_hostname(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'share'
            binary = Path(temporary) / 'cloudflared'
            binary.touch()
            child = Mock(pid=987654)
            child.poll.return_value = None
            actions = []

            def launch(*args, **kwargs):
                (directory / 'tunnel.log').write_text(self.state()['url'], encoding='utf-8')
                return child

            def stop(port, server_dir):
                self.assertEqual((port, server_dir), (8502, directory / 'server'))
                actions.append('stop-owned-old-backend')

            def start(state, share_dir, hashed):
                self.assertEqual(state['url'], self.state()['url'])
                self.assertEqual(share_dir, directory)
                actions.append('start-with-new-hostname')
                return {}, True

            with (
                patch('run_share.read_tunnel', return_value=None),
                patch('run_share.owned_tunnel', return_value=False),
                patch('run_share.run_local.read_state', return_value={'pid': 123}),
                patch('run_share.run_local.owned_process', return_value=True),
                patch('run_share.run_local.port_busy', side_effect=[True, False]),
                patch(
                    'run_share.prepare_credentials',
                    return_value=(directory / 'access.json', directory / 'password.scrypt'),
                ),
                patch('run_share.subprocess.Popen', side_effect=launch),
                patch(
                    'run_share.run_local.process_identity', return_value=('synthetic', 'synthetic-created')
                ),
                patch('run_share.tunnel_ready', return_value=True),
                patch('run_share.run_local.stop', side_effect=stop),
                patch('run_share._start_backend', side_effect=start),
                patch('run_share._wait_public', return_value=True),
            ):
                state, created = run_share.start(directory=directory, binary=binary)
            self.assertTrue(created)
            self.assertEqual(state['url'], self.state()['url'])
            self.assertEqual(actions, ['stop-owned-old-backend', 'start-with-new-hostname'])
            child.terminate.assert_not_called()

    def test_recover_waits_for_same_url_without_rotating_credentials_or_connector(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            access, hashed = run_share.prepare_credentials(directory)
            before = access.read_bytes(), hashed.read_bytes()
            with (
                patch('run_share.read_tunnel', return_value=self.state()),
                patch('run_share.owned_tunnel', return_value=True),
                patch('run_share.run_local.read_state', return_value={'pid': 123}),
                patch('run_share.run_local.owned_process', return_value=True),
                patch('run_share.run_local.healthy', return_value=True),
                patch('run_share._wait_public', return_value=True) as wait,
                patch('run_share._start_backend') as start,
                patch('run_share.stop_tunnel') as stop,
                patch('run_share.subprocess.Popen') as popen,
            ):
                self.assertEqual(run_share.recover(directory), self.state())
                self.assertLessEqual(wait.call_args.kwargs['timeout'], 30)
                start.assert_not_called()
                stop.assert_not_called()
                popen.assert_not_called()
            self.assertEqual(before, (access.read_bytes(), hashed.read_bytes()))

    def test_recover_restarts_only_owned_unhealthy_backend_with_authentication(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            _, hashed = run_share.prepare_credentials(directory)

            def start_backend(port, *, directory, timeout):
                self.assertEqual(port, 8502)
                self.assertEqual(directory, Path(temporary) / 'server')
                self.assertEqual(os.environ['FRIC_AUTH_REQUIRED'], '1')
                self.assertEqual(os.environ['FRIC_ACCESS_HASH_FILE'], str(hashed.resolve()))
                self.assertEqual(os.environ['FRIC_ACCESS_USER'], 'editor')
                self.assertEqual(os.environ['FRIC_ACCESS_PASSWORD_HASH'], '')
                self.assertEqual(os.environ['FRIC_ACCESS_PASSWORD_FILE'], '')
                self.assertEqual(
                    os.environ['STREAMLIT_BROWSER_SERVER_ADDRESS'], 'synthetic-studio.trycloudflare.com'
                )
                self.assertGreater(timeout, 0)
                return {}, True

            with (
                patch.dict(os.environ, {'FRIC_AUTH_REQUIRED': 'old-value'}),
                patch('run_share.read_tunnel', return_value=self.state()),
                patch('run_share.owned_tunnel', return_value=True),
                patch('run_share.run_local.read_state', return_value={'pid': 123}),
                patch('run_share.run_local.owned_process', return_value=True),
                patch('run_share.run_local.healthy', return_value=False),
                patch('run_share.run_local.stop') as stop,
                patch('run_share.run_local.start', side_effect=start_backend),
                patch('run_share._wait_public', return_value=True),
                patch('run_share.stop_tunnel') as stop_tunnel,
            ):
                self.assertEqual(run_share.recover(directory), self.state())
                self.assertEqual(os.environ['FRIC_AUTH_REQUIRED'], 'old-value')
                stop.assert_called_once_with(8502, directory / 'server')
                stop_tunnel.assert_not_called()

    def test_recover_refuses_dead_connector_missing_login_and_unrelated_backend(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with (
                patch('run_share.read_tunnel', return_value=self.state()),
                patch('run_share.owned_tunnel', return_value=False),
                patch('run_share.prepare_credentials') as credentials,
            ):
                with self.assertRaisesRegex(RuntimeError, 'không thể giữ URL'):
                    run_share.recover(directory)
                credentials.assert_not_called()
            with (
                patch('run_share.read_tunnel', return_value=self.state()),
                patch('run_share.owned_tunnel', return_value=True),
                patch('run_share.prepare_credentials') as credentials,
            ):
                with self.assertRaisesRegex(RuntimeError, 'không tự tạo lại mật khẩu'):
                    run_share.recover(directory)
                credentials.assert_not_called()
            run_share.prepare_credentials(directory)
            with (
                patch('run_share.read_tunnel', return_value=self.state()),
                patch('run_share.owned_tunnel', return_value=True),
                patch('run_share.run_local.read_state', return_value=None),
                patch('run_share.run_local.owned_process', return_value=False),
                patch('run_share.run_local.port_busy', return_value=True),
                patch('run_share.run_local.start') as start,
                patch('run_share.run_local.stop') as stop,
            ):
                with self.assertRaisesRegex(RuntimeError, 'tiến trình khác'):
                    run_share.recover(directory)
                start.assert_not_called()
                stop.assert_not_called()

    def test_recover_public_failure_preserves_tunnel_and_password(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            access, hashed = run_share.prepare_credentials(directory)
            before = access.read_bytes(), hashed.read_bytes()
            with (
                patch('run_share.read_tunnel', return_value=self.state()),
                patch('run_share.owned_tunnel', return_value=True),
                patch('run_share.run_local.read_state', return_value={'pid': 123}),
                patch('run_share.run_local.owned_process', return_value=True),
                patch('run_share.run_local.healthy', return_value=True),
                patch('run_share._wait_public', return_value=False),
                patch('run_share.stop_tunnel') as stop,
            ):
                with self.assertRaisesRegex(RuntimeError, 'vẫn được giữ'):
                    run_share.recover(directory)
                stop.assert_not_called()
            self.assertEqual(before, (access.read_bytes(), hashed.read_bytes()))

    def test_status_never_prints_an_active_link_for_public_route_failure(self):
        output = io.StringIO()
        with (
            patch('run_share.read_tunnel', return_value=self.state()),
            patch('run_share.owned_tunnel', return_value=True),
            patch('run_share.run_local.healthy', return_value=True),
            patch('run_share.tunnel_ready', return_value=True),
            patch('run_share.public_healthy', return_value=False),
            patch('sys.stdout', output),
        ):
            self.assertEqual(run_share.main(['status']), 1)
        self.assertIn('URL công khai chưa truy cập', output.getvalue())
        self.assertNotIn('URL chia sẻ tạm thời:', output.getvalue())

    def test_wait_public_allows_reconnect_and_caps_wait_at_thirty_seconds(self):
        for readiness in ([False, True], None):
            with self.subTest(readiness=readiness):
                elapsed = [0.0]

                def advance(seconds):
                    elapsed[0] += seconds

                with (
                    patch('run_share.time.monotonic', side_effect=lambda: elapsed[0]),
                    patch('run_share.time.sleep', side_effect=advance),
                    patch('run_share.owned_tunnel', return_value=True),
                    patch('run_share.run_local.healthy', return_value=True),
                    patch('run_share.tunnel_ready', return_value=True),
                    patch('run_share.public_healthy', side_effect=readiness, return_value=False) as public,
                    patch('run_share.stop_tunnel') as stop,
                ):
                    self.assertEqual(run_share._wait_public(self.state(), timeout=999), readiness is not None)
                    self.assertLessEqual(elapsed[0], 30)
                    self.assertTrue(all(0 < call.kwargs['timeout'] <= 3 for call in public.call_args_list))
                    stop.assert_not_called()

    def test_cli_recover_uses_existing_state_without_starting_a_new_tunnel(self):
        output = io.StringIO()
        with (
            patch('run_share.recover', return_value=self.state()) as recover,
            patch('run_share.start') as start,
            patch('run_share.stop') as stop,
            patch('sys.stdout', output),
        ):
            self.assertEqual(run_share.main(['recover']), 0)
            recover.assert_called_once_with()
            start.assert_not_called()
            stop.assert_not_called()
        self.assertIn(self.state()['url'], output.getvalue())

    def test_start_refuses_busy_unowned_port_before_credentials_or_process_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'share'
            binary = Path(temporary) / 'fake-cloudflared'
            binary.write_bytes(b'not executed')
            with (
                patch('run_share.read_tunnel', return_value=None),
                patch('run_share.run_local.read_state', return_value=None),
                patch('run_share.run_local.port_busy', return_value=True),
                patch('run_share.run_local.owned_process', return_value=False),
                patch('run_share.prepare_credentials') as credentials,
                patch('run_share.subprocess.Popen') as popen,
            ):
                with self.assertRaisesRegex(RuntimeError, 'tiến trình khác'):
                    run_share.start(directory=directory, binary=binary)
                credentials.assert_not_called()
                popen.assert_not_called()

    def test_start_preserves_local_app_port_and_rejects_uninstalled_binary(self):
        for port in (8501, 65535):
            with self.subTest(port=port), patch('run_share.subprocess.Popen') as popen:
                with self.assertRaises(RuntimeError):
                    run_share.start(port=port, binary='/synthetic/missing-cloudflared')
                popen.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, 'Chưa cài cloudflared'):
            run_share.start(binary='/synthetic/missing-cloudflared')

    def test_install_checksum_mismatch_preserves_existing_binary(self):
        metadata = Mock()
        metadata.json.return_value = {
            'assets': [
                {
                    'name': 'cloudflared-darwin-arm64.tgz',
                    'browser_download_url': 'https://github.com/cloudflare/cloudflared/releases/download/synthetic/cloudflared-darwin-arm64.tgz',
                    'digest': 'sha256:' + '0' * 64,
                }
            ]
        }
        download = Mock()
        download.iter_content.return_value = iter([b'synthetic archive with deliberately wrong checksum'])
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / 'cloudflared'
            binary.write_bytes(b'preserve existing binary')
            with (
                patch('run_share.sys.platform', 'darwin'),
                patch('platform.machine', return_value='arm64'),
                patch('requests.get', side_effect=[metadata, download]) as get,
                patch('run_share.subprocess.run') as execute,
            ):
                with self.assertRaisesRegex(RuntimeError, 'SHA-256'):
                    run_share.install_cloudflared(binary)
                self.assertEqual(get.call_count, 2)
                execute.assert_not_called()
            self.assertEqual(binary.read_bytes(), b'preserve existing binary')
            self.assertEqual([p.name for p in Path(temporary).iterdir()], ['cloudflared'])
        metadata.close.assert_called_once()
        download.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
