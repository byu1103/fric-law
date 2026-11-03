"""Exercise the private setup CLI with isolated files and no paid API calls."""

import contextlib
import getpass
import io
import os
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

import httpx
import openai

import ai_client
import settings
import setup_ai


class TestAISetupCLI(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / '.env'
        self.enterContext(patch.object(settings, 'ENV_FILE', self.path))
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        self.tty = self.enterContext(patch('setup_ai.sys.stdin.isatty', return_value=True))
        self.hidden = self.enterContext(patch('setup_ai.getpass.getpass', return_value='synthetic-cli-key'))
        self.model_input = self.enterContext(patch('builtins.input', return_value=''))
        self.probe = self.enterContext(
            patch('setup_ai.check_ai_connection', return_value={'ok': True, 'model': settings.DEFAULT_MODEL})
        )

    def run_cli(self, args):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            result = setup_ai.main(args)
        visible = output.getvalue() + error.getvalue()
        self.assertNotIn('synthetic-cli-key', visible)
        self.assertNotIn('synthetic-existing-key', visible)
        return result, output.getvalue(), error.getvalue()

    def test_hidden_prompt_saves_private_key_without_claiming_connection_when_not_tested(self):
        result, output, error = self.run_cli(['--no-test'])
        self.assertEqual(result, 0)
        self.assertFalse(error)
        self.assertIn('Chưa kiểm tra API', output)
        self.assertNotIn('phản hồi thành công', output)
        self.hidden.assert_called_once()
        self.model_input.assert_called_once()
        self.probe.assert_not_called()
        self.assertTrue(settings.get_ai_settings()['configured'])
        self.assertEqual(os.environ['AIBOX_API_KEY'], 'synthetic-cli-key')
        if os.name != 'nt':
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_non_interactive_input_is_rejected_before_prompt_or_write(self):
        self.tty.return_value = False
        with patch('setup_ai.save_ai_settings') as save:
            result, output, error = self.run_cli([])
        self.assertEqual(result, 1)
        self.assertIn('Terminal', error)
        self.assertFalse(output)
        self.hidden.assert_not_called()
        self.model_input.assert_not_called()
        self.probe.assert_not_called()
        save.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_terminal_without_hidden_input_refuses_echo_fallback(self):
        def fallback(prompt):
            warnings.warn('synthetic-cli-key could be echoed', getpass.GetPassWarning)
            return 'synthetic-cli-key'

        self.hidden.side_effect = fallback
        with warnings.catch_warnings(record=True):
            result, output, error = self.run_cli(['--no-test'])
        self.assertEqual(result, 1)
        self.assertFalse(self.path.exists())
        self.assertNotIn('Đã lưu', output)
        self.assertTrue(error)
        self.model_input.assert_not_called()
        self.probe.assert_not_called()

    def test_cancelled_hidden_prompt_returns_safely_without_writing(self):
        for cancellation in (EOFError, KeyboardInterrupt):
            with self.subTest(cancellation=cancellation.__name__):
                self.hidden.side_effect = cancellation()
                result, output, error = self.run_cli([])
                self.assertEqual(result, 1)
                self.assertFalse(self.path.exists())
                self.assertNotIn('Đã lưu', output)
                self.assertTrue(error)
        self.model_input.assert_not_called()
        self.probe.assert_not_called()

    def test_missing_key_returns_without_writing_or_charging_probe(self):
        self.hidden.return_value = ''
        with patch('setup_ai.save_ai_settings') as save:
            result, output, error = self.run_cli([])
        self.assertEqual(result, 1)
        self.assertIn('Chưa có khóa', error)
        self.assertNotIn('Đã lưu', output)
        self.model_input.assert_not_called()
        save.assert_not_called()
        self.probe.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_legacy_openai_key_does_not_satisfy_blank_aibox_setup(self):
        original = 'OPENAI_API_KEY=synthetic-separate-key\nOPENAI_MODEL=codex-model\n'
        self.path.write_text(original, encoding='utf-8')
        os.environ['OPENAI_API_KEY'] = 'synthetic-unrelated-key'
        self.hidden.return_value = ''
        result, output, error = self.run_cli([])
        self.assertEqual(result, 1)
        self.assertIn('AIBox', (output + error).replace(' ', ''))
        self.assertNotIn('platform.openai.com', output + error)
        self.assertNotIn('Đã lưu', output)
        self.assertEqual(self.path.read_text(encoding='utf-8'), original)
        self.assertEqual(os.environ['OPENAI_API_KEY'], 'synthetic-unrelated-key')
        self.assertNotIn('AIBOX_API_KEY', os.environ)
        self.probe.assert_not_called()

    def test_aibox_cli_configuration_preserves_unrelated_openai_settings(self):
        original = 'OPENAI_API_KEY=synthetic-separate-key\nOPENAI_MODEL=codex-model\n'
        self.path.write_text(original, encoding='utf-8')
        os.environ.update(OPENAI_API_KEY='synthetic-runtime-key', OPENAI_MODEL='runtime-model')
        result, output, error = self.run_cli(['--no-test'])
        self.assertEqual(result, 0)
        self.assertFalse(error)
        self.assertIn('AIBox', output.replace(' ', ''))
        self.assertEqual(os.environ['AIBOX_API_KEY'], 'synthetic-cli-key')
        self.assertEqual(os.environ['OPENAI_API_KEY'], 'synthetic-runtime-key')
        self.assertEqual(os.environ['OPENAI_MODEL'], 'runtime-model')
        for line in original.splitlines():
            self.assertIn(line, self.path.read_text(encoding='utf-8'))
        self.probe.assert_not_called()

    def test_blank_key_preserves_existing_tavily_key_and_only_updates_model(self):
        settings.save_api_keys(tavily_key='synthetic-tavily-key', aibox_key='synthetic-existing-key')
        self.hidden.return_value = ''
        self.model_input.return_value = 'different-model'
        result, _, _ = self.run_cli(['--no-test'])
        self.assertEqual(result, 0)
        self.assertEqual(os.environ['AIBOX_API_KEY'], 'synthetic-existing-key')
        self.assertEqual(os.environ['TAVILY_API_KEY'], 'synthetic-tavily-key')
        self.assertEqual(settings.get_ai_settings()['model'], 'different-model')
        self.probe.assert_not_called()

    def test_check_only_uses_saved_configuration_without_tty_prompt_or_write(self):
        settings.save_ai_settings(aibox_key='synthetic-existing-key', model='existing-model')
        before = self.path.read_bytes()
        self.tty.return_value = False
        self.probe.return_value = {'ok': True, 'model': 'existing-model'}
        with patch('setup_ai.save_ai_settings') as save:
            result, output, error = self.run_cli(['--check-only'])
        self.assertEqual(result, 0)
        self.assertIn('phản hồi thành công', output)
        self.assertFalse(error)
        self.assertEqual(self.path.read_bytes(), before)
        self.probe.assert_called_once_with(model='existing-model')
        self.hidden.assert_not_called()
        self.model_input.assert_not_called()
        save.assert_not_called()

    def test_check_only_missing_key_fails_without_opening_sdk_or_writing(self):
        with (
            patch('setup_ai.check_ai_connection', side_effect=ai_client.check_ai_connection),
            patch('openai.OpenAI') as sdk,
        ):
            result, output, error = self.run_cli(['--check-only'])
        self.assertEqual(result, 2)
        self.assertIn('Chưa cấu hình', error)
        self.assertNotIn('phản hồi thành công', output)
        sdk.assert_not_called()
        self.hidden.assert_not_called()
        self.model_input.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_channel_failure_reports_safe_diagnostics_without_rewriting_key(self):
        settings.save_ai_settings(aibox_key='synthetic-existing-key', model='existing-model')
        before = self.path.read_bytes()
        request_id = '202610231123034804067888268d9d6u4RS5N9y'
        self.probe.side_effect = ai_client.AIServiceError(
            'model_unavailable',
            'AI Box chưa có kênh phục vụ model cho nhóm của khóa này.',
            status_code=503,
            request_id=request_id,
        )
        result, output, error = self.run_cli(['--check-only'])
        self.assertEqual(result, 2)
        self.assertIn('chưa có kênh', error)
        self.assertIn('HTTP 503 · model_unavailable', error)
        self.assertIn('Mã yêu cầu AI Box: ' + request_id, error)
        self.assertNotIn('phản hồi thành công', output)
        self.assertEqual(self.path.read_bytes(), before)
        self.hidden.assert_not_called()
        self.model_input.assert_not_called()
        self.probe.assert_called_once_with(model='existing-model')

    def test_selected_model_is_probed_after_explicit_interactive_setup(self):
        self.model_input.return_value = 'selected-model'
        self.probe.return_value = {'ok': True, 'model': 'selected-model'}
        result, output, error = self.run_cli([])
        self.assertEqual(result, 0)
        self.assertIn('selected-model', output)
        self.assertIn('có thể phát sinh phí', output)
        self.assertFalse(error)
        self.probe.assert_called_once_with(model='selected-model')
        self.assertEqual(settings.get_ai_settings()['model'], 'selected-model')

    def test_invalid_model_does_not_save_replacement_key_or_probe(self):
        settings.save_ai_settings(aibox_key='synthetic-existing-key', model='existing-model')
        before = self.path.read_bytes()
        self.model_input.return_value = 'model\nINJECTED=x'
        result, output, error = self.run_cli([])
        self.assertEqual(result, 1)
        self.assertNotIn('Đã lưu', output)
        self.assertIn('Không lưu/đọc', error)
        self.assertNotIn('INJECTED', error)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(os.environ['AIBOX_API_KEY'], 'synthetic-existing-key')
        self.probe.assert_not_called()

    def test_storage_failure_is_safe_and_does_not_probe_or_modify_file(self):
        settings.save_ai_settings(aibox_key='synthetic-existing-key', model='existing-model')
        before = self.path.read_bytes()
        with patch('settings.os.replace', side_effect=OSError('synthetic-cli-key in internal detail')):
            result, output, error = self.run_cli([])
        self.assertEqual(result, 1)
        self.assertNotIn('Đã lưu', output)
        self.assertIn('Không lưu/đọc', error)
        self.assertEqual(self.path.read_bytes(), before)
        self.probe.assert_not_called()

    def test_provider_401_is_sanitized_by_real_adapter_then_reported_without_rewriting_key(self):
        settings.save_ai_settings(aibox_key='synthetic-existing-key', model='existing-model')
        before = self.path.read_bytes()
        client_class = openai.OpenAI
        requests = []
        clients = []

        def reject(request):
            requests.append(request)
            return httpx.Response(
                401,
                json={
                    'error': {
                        'message': 'Provider echoed synthetic-existing-key and CLIENT_SECRET',
                        'type': 'invalid_request_error',
                        'code': 'invalid_api_key',
                    }
                },
            )

        def local_client(**values):
            client = httpx.Client(transport=httpx.MockTransport(reject))
            clients.append(client)
            values['http_client'] = client
            return client_class(**values)

        with (
            patch('openai.OpenAI', side_effect=local_client),
            patch('setup_ai.check_ai_connection', side_effect=ai_client.check_ai_connection),
        ):
            result, output, error = self.run_cli(['--check-only'])
        self.assertEqual(result, 2)
        self.assertIn('không được chấp nhận', error)
        self.assertNotIn('CLIENT_SECRET', output + error)
        self.assertNotIn('phản hồi thành công', output)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(len(requests), 1)
        self.assertEqual(str(requests[0].url), 'https://api.ai-box.vn/v1/chat/completions')
        self.assertTrue(clients[0].is_closed)
        self.hidden.assert_not_called()


if __name__ == '__main__':
    unittest.main()
