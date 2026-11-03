"""Auth tests isolate credentials and never touch the editorial SQLite workspace."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import access_control as access
import settings

APP = Path(__file__).resolve().parents[1] / 'app.py'


class TestAccessControl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = 'fixture-editor-password-123'
        cls.password_hash = access.make_password_hash(cls.password)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.enterContext(patch.object(settings, 'ENV_FILE', Path(temporary.name) / '.env'))
        self.env = patch.dict(
            os.environ,
            {
                'FRIC_AUTH_REQUIRED': '',
                'FRIC_HOSTED': '',
                'FRIC_ACCESS_USER': 'editor',
                'FRIC_ACCESS_PASSWORD_HASH': '',
                'FRIC_ACCESS_HASH_FILE': '',
                'FRIC_ACCESS_PASSWORD_FILE': '',
                'FRIC_AUTH_SESSION_HOURS': '8',
            },
        )
        self.env.start()
        self.limiter = access.LoginLimiter()
        self.config = access.AccessConfig('editor', password_hash=self.password_hash)

    def tearDown(self):
        self.env.stop()

    def test_hash_roundtrip_salt_wrong_password_and_malformed_hash(self):
        other = access.make_password_hash(self.password)
        self.assertNotEqual(other, self.password_hash)
        self.assertTrue(access.check_password(self.password, other))
        self.assertFalse(access.check_password('wrong', other))
        self.assertFalse(access.check_password(self.password, 'broken'))
        self.assertFalse(access.check_password(self.password, other.replace('$16384$', '$1073741824$')))
        self.assertFalse(access.check_password('x' * 1025, other))

    def test_local_mode_default_and_remote_configuration_fail_closed(self):
        self.assertFalse(access.remote_access_required())
        os.environ['FRIC_AUTH_REQUIRED'] = '1'
        self.assertTrue(access.remote_access_required())
        with self.assertRaises(access.AccessConfigurationError):
            access.load_access_config()
        os.environ['FRIC_ACCESS_PASSWORD_HASH'] = 'invalid'
        with self.assertRaises(access.AccessConfigurationError):
            access.load_access_config()

    def test_hosted_mode_cannot_disable_required_authentication(self):
        os.environ['FRIC_HOSTED'] = '1'
        os.environ['FRIC_AUTH_REQUIRED'] = '0'
        self.assertTrue(access.remote_access_required())
        with self.assertRaises(access.AccessConfigurationError):
            access.load_access_config()
        with patch('core.init') as initialize:
            app = AppTest.from_file(str(APP)).run()
        self.assertFalse(app.exception, str(app.exception))
        initialize.assert_not_called()
        self.assertTrue(any('chưa cấu hình đăng nhập' in item.value for item in app.error))

    def test_private_hash_file_and_environment_configuration(self):
        os.environ['FRIC_ACCESS_PASSWORD_HASH'] = self.password_hash
        self.assertTrue(access.load_access_config().verify('editor', self.password))
        os.environ['FRIC_ACCESS_PASSWORD_HASH'] = ''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'login.hash'
            path.write_text(self.password_hash)
            path.chmod(0o600)
            os.environ['FRIC_ACCESS_HASH_FILE'] = str(path)
            config = access.load_access_config()
            self.assertTrue(config.verify('editor', self.password))
            self.assertNotIn(self.password_hash, repr(config))
            if os.name != 'nt':
                path.chmod(0o644)
                with self.assertRaises(access.AccessConfigurationError) as caught:
                    access.load_access_config()
                self.assertNotIn(str(path), str(caught.exception))

    def test_private_plaintext_file_supported_without_secret_in_repr(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'login.secret'
            path.write_text(self.password + '\n')
            path.chmod(0o600)
            os.environ['FRIC_ACCESS_PASSWORD_FILE'] = str(path)
            config = access.load_access_config()
            self.assertTrue(config.verify('editor', self.password))
            self.assertFalse(config.verify('not-editor', self.password))
            self.assertNotIn(self.password, repr(config))

    def test_wrong_credentials_and_rate_limit_across_new_sessions(self):
        for count in range(5):
            session = {}
            self.assertFalse(
                access.login('editor', 'wrong', session, self.config, now=100 + count, limiter=self.limiter)
            )
            self.assertIsNone(access.authenticated_user(session, self.config, now=104))
        with self.assertRaises(access.LoginRateLimited) as caught:
            access.login('editor', self.password, {}, self.config, now=105, limiter=self.limiter)
        self.assertGreater(caught.exception.retry_after, 0)
        session = {}
        self.assertTrue(
            access.login('editor', self.password, session, self.config, now=165, limiter=self.limiter)
        )
        self.assertEqual(access.authenticated_user(session, self.config, now=166), 'editor')

    def test_per_session_budget_survives_process_limiter_replacement(self):
        session = {}
        for count in range(5):
            access.login('editor', 'wrong', session, self.config, now=100 + count, limiter=self.limiter)
        with self.assertRaises(access.LoginRateLimited):
            access.login(
                'editor', self.password, session, self.config, now=105, limiter=access.LoginLimiter()
            )

    def test_success_expiry_rotation_and_logout_clear_all_draft_state(self):
        session = {'draft_content': 'previous draft', 'local_aibox_key': 'fixture-secret'}
        self.assertTrue(
            access.login('editor', self.password, session, self.config, now=100, limiter=self.limiter)
        )
        self.assertNotIn('draft_content', session)
        self.assertNotIn('local_aibox_key', session)
        self.assertEqual(access.authenticated_user(session, self.config, now=101), 'editor')
        session['draft_content'] = 'new draft'
        self.assertIsNone(access.authenticated_user(session, self.config, now=100 + self.config.ttl))
        self.assertEqual(session, {})
        access.login('editor', self.password, session, self.config, now=40000, limiter=self.limiter)
        session['draft_content'] = 'new draft'
        changed = access.AccessConfig('editor', password_hash=access.make_password_hash('different-password'))
        self.assertIsNone(access.authenticated_user(session, changed, now=40001))
        self.assertEqual(session, {})
        access.logout(session)
        self.assertEqual(session, {})

    def test_configuration_invalid_session_duration_or_empty_user(self):
        os.environ['FRIC_ACCESS_PASSWORD_HASH'] = self.password_hash
        for value in ('0', '25', 'invalid'):
            os.environ['FRIC_AUTH_SESSION_HOURS'] = value
            with self.assertRaises(access.AccessConfigurationError):
                access.load_access_config()
        os.environ['FRIC_AUTH_SESSION_HOURS'] = '8'
        os.environ['FRIC_ACCESS_USER'] = ' '
        with self.assertRaises(access.AccessConfigurationError):
            access.load_access_config()

    def test_ui_remote_missing_credentials_stops_before_database(self):
        os.environ['FRIC_AUTH_REQUIRED'] = '1'
        with patch('core.init') as initialize, patch('core.get_sources') as read_sources:
            app = AppTest.from_file(str(APP)).run()
        self.assertFalse(app.exception, str(app.exception))
        initialize.assert_not_called()
        read_sources.assert_not_called()
        self.assertTrue(any('chưa cấu hình đăng nhập' in item.value for item in app.error))
        self.assertFalse(app.button)
        self.assertFalse(app.text_area)

    def test_ui_remote_login_blocks_workspace_and_clears_password_input(self):
        os.environ['FRIC_AUTH_REQUIRED'] = '1'
        os.environ['FRIC_ACCESS_PASSWORD_HASH'] = self.password_hash
        with patch('core.init') as initialize, patch('core.get_sources') as read_sources:
            app = AppTest.from_file(str(APP)).run()
            self.assertFalse(app.exception, str(app.exception))
            self.assertEqual(len(app.text_input), 2)
            app.text_input(key='_fric_login_password').set_value('wrong')
            app.button[0].click().run()
        initialize.assert_not_called()
        read_sources.assert_not_called()
        self.assertFalse(app.exception, str(app.exception))
        self.assertTrue(any('không đúng' in item.value for item in app.error))
        self.assertFalse(app.text_area)
        self.assertEqual(app.text_input(key='_fric_login_password').value, '')
        self.assertFalse(any(item.key == 'run_search' for item in app.button))

    def test_ui_success_and_logout_remove_draft_and_hide_editorial_workspace(self):
        os.environ['FRIC_AUTH_REQUIRED'] = '1'
        os.environ['FRIC_ACCESS_PASSWORD_HASH'] = self.password_hash
        with (
            patch.object(access, '_LIMITER', self.limiter),
            patch('core.init') as initialize,
            patch('core.get_sources', return_value=[]) as read_sources,
            patch('core.list_articles', return_value=[]),
        ):
            app = AppTest.from_file(str(APP)).run()
            initialize.assert_not_called()
            app.text_input(key='_fric_login_password').set_value(self.password)
            app.button[0].click().run()
            self.assertFalse(app.exception, str(app.exception))
            self.assertTrue(any(item.key == 'run_search' for item in app.button))
            self.assertTrue(any('Đã đăng nhập: editor' in item.value for item in app.caption))
            self.assertFalse(
                any(item.key in ('local_tavily_key', 'local_aibox_key') for item in app.text_input)
            )
            self.assertFalse(any(item.label == 'Lưu cấu hình API trên máy' for item in app.button))
            self.assertTrue(any('Khóa API do quản trị viên cấu hình' in item.value for item in app.caption))
            self.assertTrue(initialize.called)
            self.assertTrue(read_sources.called)
            count = initialize.call_count
            app.session_state['draft_content'] = 'unsaved confidential fixture'
            app.button(key='_fric_logout').click().run()
            self.assertFalse(app.exception, str(app.exception))
            self.assertEqual(initialize.call_count, count)
            self.assertFalse(any(item.key == 'run_search' for item in app.button))
            self.assertNotIn('draft_content', app.session_state)


if __name__ == '__main__':
    unittest.main()
