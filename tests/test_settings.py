import os
import json
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import settings


class TestLocalSettings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / '.env'
        self.path_patch = patch.object(settings, 'ENV_FILE', self.path)
        self.path_patch.start()
        self.env_patch = patch.dict(os.environ, {}, clear=True)
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.path_patch.stop()
        self.tmp.cleanup()

    def test_saved_keys_roundtrip_without_echo_and_private_permissions(self):
        secret = "synthetic-test-key-with-'quotes-$value"
        result = settings.save_api_keys(tavily_key=secret)
        self.assertEqual(result, {'TAVILY_API_KEY': True, 'AIBOX_API_KEY': False})
        self.assertNotIn(secret, str(result))
        os.environ.clear()
        settings.reload_local_settings()
        self.assertEqual(os.environ['TAVILY_API_KEY'], secret)
        if os.name != 'nt':
            self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_preserves_unrelated_settings_and_existing_key(self):
        self.path.write_text('# existing\nFRIC_WORKSPACE=/keep/workspace\nAIBOX_API_KEY=existing-key\n')
        settings.save_api_keys(tavily_key='new-test-key')
        settings.reload_local_settings()
        self.assertEqual(os.environ['AIBOX_API_KEY'], 'existing-key')
        self.assertNotIn('FRIC_WORKSPACE', os.environ)
        self.assertIn('FRIC_WORKSPACE=/keep/workspace', self.path.read_text())

    def test_invalid_or_empty_input_does_not_modify_file(self):
        self.path.write_text('AIBOX_API_KEY=old-test-key\n')
        original = self.path.read_bytes()
        for value in ('', 'a\nINJECTED=x', 'a\rmore', '\x00', 3):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    settings.save_api_keys(tavily_key=value)
                self.assertEqual(self.path.read_bytes(), original)
        with self.assertRaises(ValueError):
            settings.save_api_keys()

    def test_failed_atomic_replace_keeps_previous_configuration(self):
        self.path.write_text('TAVILY_API_KEY=old-test-key\n')
        with patch('settings.os.replace', side_effect=OSError('simulated failure')):
            with self.assertRaises(OSError):
                settings.save_api_keys(tavily_key='new-test-key')
        self.assertEqual(self.path.read_text(), 'TAVILY_API_KEY=old-test-key\n')
        self.assertEqual(list(self.path.parent.glob('.env-*')), [])

    def test_model_only_change_preserves_key_comments_and_workspace(self):
        original = (
            '# Existing editorial setup\n'
            'TAVILY_API_KEY=synthetic-tavily-key\n'
            'AIBOX_API_KEY=synthetic-existing-aibox-key\n'
            'FRIC_WORKSPACE=/keep/editorial/workspace\n'
        )
        self.path.write_text(original, encoding='utf-8')
        before = settings.get_ai_settings()
        result = settings.save_ai_settings(model='alternate-aibox-model')
        self.assertTrue(result['configured'])
        self.assertEqual(result['model'], 'alternate-aibox-model')
        self.assertNotEqual(result['revision'], before['revision'])
        content = self.path.read_text(encoding='utf-8')
        for line in original.splitlines():
            self.assertIn(line, content)
        self.assertEqual(os.environ['AIBOX_API_KEY'], 'synthetic-existing-aibox-key')
        self.assertEqual(os.environ['TAVILY_API_KEY'], 'synthetic-tavily-key')
        self.assertNotIn('FRIC_WORKSPACE', os.environ)
        self.assertNotIn('synthetic-existing-aibox-key', str(result))

    def test_ai_settings_revision_changes_with_key_or_model_but_not_unrelated_settings(self):
        first = settings.save_ai_settings(aibox_key='synthetic-aibox-key-one', model='qwen3.8-max-0902')
        unchanged = settings.get_ai_settings()
        self.assertEqual(unchanged['revision'], first['revision'])
        settings.save_api_keys(tavily_key='synthetic-tavily-key')
        self.assertEqual(settings.get_ai_settings()['revision'], first['revision'])
        second = settings.save_ai_settings(aibox_key='synthetic-aibox-key-two')
        self.assertNotEqual(second['revision'], first['revision'])
        third = settings.save_ai_settings(model='alternate-aibox-model')
        self.assertNotEqual(third['revision'], second['revision'])
        os.environ.update(OPENAI_API_KEY='synthetic-unrelated-openai-key', OPENAI_MODEL='codex-model')
        self.assertEqual(settings.get_ai_settings()['revision'], third['revision'])
        for result in (first, second, third):
            self.assertEqual(
                set(result), {'configured', 'model', 'revision', 'provider', 'base_url', 'api_format'}
            )
            self.assertEqual(result['provider'], 'aibox')
            self.assertEqual(result['base_url'], 'https://api.ai-box.vn/v1')
            self.assertEqual(result['api_format'], 'chat_completions')
            self.assertNotIn('synthetic-aibox-key', str(result))

    def test_legacy_openai_credentials_cannot_configure_website(self):
        self.path.write_text(
            'OPENAI_API_KEY=synthetic-legacy-file-key\nOPENAI_MODEL=legacy-model\n', encoding='utf-8'
        )
        os.environ.update(OPENAI_API_KEY='synthetic-separate-runtime-key', OPENAI_MODEL='runtime-model')
        result = settings.get_ai_settings()
        self.assertFalse(result['configured'])
        self.assertEqual(result['model'], 'deepseek-v4.1-flash')
        self.assertEqual(settings.get_key_status(), {'TAVILY_API_KEY': False, 'AIBOX_API_KEY': False})
        self.assertEqual(os.environ['OPENAI_API_KEY'], 'synthetic-separate-runtime-key')
        self.assertEqual(os.environ['OPENAI_MODEL'], 'runtime-model')
        self.assertNotIn('synthetic-', str(result))

    def test_aibox_save_preserves_legacy_openai_file_and_runtime_values(self):
        old = '# other application\nOPENAI_API_KEY=synthetic-legacy-file-key\nOPENAI_MODEL=legacy-model\n'
        self.path.write_text(old, encoding='utf-8')
        os.environ.update(OPENAI_API_KEY='synthetic-unrelated-runtime-key', OPENAI_MODEL='runtime-model')
        result = settings.save_ai_settings(aibox_key='synthetic-aibox-key', model='qwen3.8-max-0902')
        self.assertTrue(result['configured'])
        for line in old.splitlines():
            self.assertIn(line, self.path.read_text(encoding='utf-8'))
        self.assertEqual(os.environ['OPENAI_API_KEY'], 'synthetic-unrelated-runtime-key')
        self.assertEqual(os.environ['OPENAI_MODEL'], 'runtime-model')

    def test_custom_api_base_url_is_not_loaded_or_selected(self):
        self.path.write_text(
            'AIBOX_API_KEY=synthetic-aibox-key\n'
            'AIBOX_BASE_URL=https://file-untrusted.invalid\n'
            'OPENAI_BASE_URL=https://file-openai-untrusted.invalid\n',
            encoding='utf-8',
        )
        result = settings.get_ai_settings()
        self.assertEqual(result['base_url'], 'https://api.ai-box.vn/v1')
        self.assertNotIn('AIBOX_BASE_URL', os.environ)
        self.assertNotIn('OPENAI_BASE_URL', os.environ)
        os.environ.update(
            AIBOX_BASE_URL='https://runtime-untrusted.invalid',
            OPENAI_BASE_URL='https://runtime-openai-untrusted.invalid',
        )
        self.assertEqual(settings.get_ai_settings()['base_url'], 'https://api.ai-box.vn/v1')
        self.assertEqual(os.environ['OPENAI_BASE_URL'], 'https://runtime-openai-untrusted.invalid')

    def test_website_settings_never_modify_global_codex_configuration(self):
        home = Path(self.tmp.name) / 'synthetic-home'
        codex = home / '.codex'
        codex.mkdir(parents=True)
        config, auth = codex / 'config.toml', codex / 'auth.json'
        config.write_text('model_provider="unchanged-codex-provider"\n', encoding='utf-8')
        auth.write_text('{"synthetic_global_credential":"preserve-this"}\n', encoding='utf-8')
        before = {path: path.read_bytes() for path in (config, auth)}
        os.environ.update(HOME=str(home), CODEX_HOME=str(codex), OPENAI_API_KEY='synthetic-codex-key')
        settings.save_ai_settings(aibox_key='synthetic-website-key', model='qwen3.8-max-0902')
        settings.save_api_keys(tavily_key='synthetic-search-key')
        settings.reload_local_settings()
        self.assertEqual(before, {path: path.read_bytes() for path in (config, auth)})
        self.assertEqual(sorted(path.name for path in codex.iterdir()), ['auth.json', 'config.toml'])
        self.assertEqual(os.environ['OPENAI_API_KEY'], 'synthetic-codex-key')
        self.assertEqual(os.environ['CODEX_HOME'], str(codex))

    def test_invalid_ai_model_or_key_never_partially_updates_configuration(self):
        settings.save_ai_settings(aibox_key='synthetic-existing-key', model='qwen3.8-max-0902')
        before_file = self.path.read_bytes()
        before_env = dict(os.environ)
        for model in (
            '',
            'bad model',
            'model\nINJECTED=1',
            'model\rnew',
            'https://other.invalid/model',
            '\x00',
            9,
            'x' * 201,
        ):
            with self.subTest(model=model), self.assertRaises(ValueError):
                settings.save_ai_settings(aibox_key='synthetic-replacement-key', model=model)
            self.assertEqual(self.path.read_bytes(), before_file)
            self.assertEqual(dict(os.environ), before_env)
        for key in ('', 'new\nINJECTED=x', 'new\rkey', 'new\x00key', 9, 'x' * 4097):
            with self.subTest(key_type=type(key).__name__), self.assertRaises(ValueError):
                settings.save_ai_settings(aibox_key=key, model='different-model')
            self.assertEqual(self.path.read_bytes(), before_file)
            self.assertEqual(dict(os.environ), before_env)
        self.assertEqual(list(self.path.parent.glob('.env-*')), [])

    def test_failed_ai_write_keeps_key_model_and_process_state(self):
        settings.save_ai_settings(aibox_key='synthetic-old-key', model='old-model')
        before = settings.get_ai_settings()
        before_file = self.path.read_bytes()
        before_env = dict(os.environ)
        with patch('settings.os.replace', side_effect=OSError('synthetic write failure')):
            with self.assertRaises(OSError):
                settings.save_ai_settings(aibox_key='synthetic-new-key', model='new-model')
        self.assertEqual(self.path.read_bytes(), before_file)
        self.assertEqual(dict(os.environ), before_env)
        self.assertEqual(settings.get_ai_settings(), before)
        self.assertEqual(list(self.path.parent.glob('.env-*')), [])

    def test_private_ai_configuration_is_read_by_a_new_process(self):
        saved = settings.save_ai_settings(aibox_key='synthetic-cross-process-key', model='custom-model')
        script = (
            'import json, sys; from pathlib import Path; import settings; '
            'settings.ENV_FILE=Path(sys.argv[1]); print(json.dumps(settings.get_ai_settings()))'
        )
        result = subprocess.run(
            [sys.executable, '-c', script, str(self.path)],
            cwd=Path(settings.__file__).parent,
            env={},
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        self.assertEqual(json.loads(result.stdout), saved)
        self.assertNotIn('synthetic-cross-process-key', result.stdout + result.stderr)

    def test_startup_workspace_defaults_never_override_server_access_or_existing_workspace(self):
        self.path.write_text(
            'FRIC_WORKSPACE=/file/workspace\n'
            'FRIC_AUTH_REQUIRED=0\n'
            'FRIC_HOSTED=0\n'
            'FRIC_ACCESS_PASSWORD_HASH=untrusted-file-value\n'
            'OPENAI_BASE_URL=https://untrusted.invalid\n',
            encoding='utf-8',
        )
        os.environ.update(FRIC_AUTH_REQUIRED='1', FRIC_HOSTED='1')
        settings.load_startup_settings()
        self.assertEqual(os.environ['FRIC_WORKSPACE'], '/file/workspace')
        self.assertEqual(os.environ['FRIC_AUTH_REQUIRED'], '1')
        self.assertEqual(os.environ['FRIC_HOSTED'], '1')
        self.assertNotIn('FRIC_ACCESS_PASSWORD_HASH', os.environ)
        self.assertNotIn('OPENAI_BASE_URL', os.environ)
        os.environ['FRIC_WORKSPACE'] = '/server/real/workspace'
        settings.load_startup_settings()
        self.assertEqual(os.environ['FRIC_WORKSPACE'], '/server/real/workspace')


if __name__ == '__main__':
    unittest.main()
