"""Offline Streamlit workflows with an isolated SQLite/MASTER workspace."""

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
import openai

from ai_client import AIServiceError
import core
from research import SearchResults
import settings
from streamlit.testing.v1 import AppTest


APP = Path(__file__).resolve().parents[1] / 'app.py'
PAGES = ['🔎 Tìm tin', '📚 Thư viện nguồn', '✍️ Soạn & duyệt', '🗂️ Kho bài & xuất bản', '🗺️ Hình & bản đồ']


class TestEditorialAppSmoke(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.env = patch.dict(
            os.environ,
            {
                'FRIC_WORKSPACE': str(root),
                'AIBOX_API_KEY': '',
                'OPENAI_API_KEY': 'sk-test-unrelated-chat-key',
                'OPENAI_MODEL': 'unrelated-chat-model',
                'TAVILY_API_KEY': '',
                'AIBOX_MODEL': 'qwen3.8-max-0902',
                'FRIC_AUTH_REQUIRED': '0',
                'FRIC_HOSTED': '0',
            },
        )
        self.env.start()
        self.settings_path = patch.object(settings, 'ENV_FILE', root / '.env')
        self.settings_path.start()
        self.reload_settings = patch('settings.reload_local_settings')
        self.reload_settings.start()
        self.paths = patch.multiple(
            core, WORKSPACE=root, DB=root / 'articles.sqlite3', MASTER=root / 'MASTER.docx'
        )
        self.paths.start()
        core.init()

    def tearDown(self):
        self.paths.stop()
        self.reload_settings.stop()
        self.settings_path.stop()
        self.env.stop()
        self.temp.cleanup()

    def app(self):
        app = AppTest.from_file(str(APP), default_timeout=20).run()
        self.assertFalse(app.exception, str(app.exception))
        return app

    def page(self, app, page):
        app.radio(key='navigation').set_value(page).run()
        self.assertFalse(app.exception, str(app.exception))

    def click(self, app, label):
        button = next(item for item in app.button if item.label == label)
        button.click().run()
        self.assertFalse(app.exception, str(app.exception))

    def test_empty_navigation_strict_dates_and_public_search_without_keys(self):
        app = self.app()
        self.assertEqual(app.date_input(key='search_start').value, core.today_vn() - timedelta(days=6))
        self.assertEqual(app.date_input(key='search_end').value, core.today_vn())
        app.date_input(key='search_start').set_value(core.today_vn())
        app.date_input(key='search_end').set_value(core.today_vn() - timedelta(days=1))
        app.button(key='run_search').click().run()
        self.assertTrue(any('Ngày bắt đầu' in item.value for item in app.error))
        app.date_input(key='search_end').set_value(core.today_vn())
        with patch('core.search_news', return_value=[]) as search:
            app.button(key='run_search').click().run()
        self.assertFalse(app.exception, str(app.exception))
        self.assertFalse(app.error, str(app.error))
        self.assertEqual(search.call_args.kwargs['provider'], 'auto')
        self.assertTrue(any('Không tìm thấy nguồn phù hợp' in item.value for item in app.info))
        for page in PAGES[1:]:
            self.page(app, page)
        self.assertEqual(app.text_input(key='map_lat').value, '')
        self.assertEqual(app.text_input(key='map_lon').value, '')

    def public_hits(self):
        return [
            {
                'url': 'https://chinhphu.vn/du-an-trung-quoc-thu-nghiem',
                'title': 'Doanh nghiệp Trung Quốc mở nhà máy Việt Nam',
                'published': core.today_vn().isoformat(),
                'date_verified': True,
                'date_status': 'in_range',
                'date_evidence': 'Original datePublished: ' + core.today_vn().isoformat(),
                'text': 'Nguồn thử nghiệm có dấu ngày gốc; không phải tin thực tế.',
            },
            {
                'url': 'https://mof.gov.vn/van-ban-boi-canh-thu-nghiem',
                'title': 'Tài liệu tham khảo về thuế doanh nghiệp',
                'date_verified': False,
                'date_status': 'needs_verification',
            },
        ]

    def test_all_public_sources_unavailable_does_not_claim_no_matching_news(self):
        app = self.app()
        findings = SearchResults(
            [],
            diagnostics={
                'provider': 'public',
                'failed_sources': ['https://sbv.gov.vn/'],
                'providers_succeeded': [],
            },
        )
        with patch('core.search_news', return_value=findings):
            app.button(key='run_search').click().run()
        self.assertFalse(app.exception, str(app.exception))
        self.assertTrue(any('chưa thể kết luận không có tin phù hợp' in item.value for item in app.warning))
        self.assertFalse(any('Không tìm thấy nguồn phù hợp' in item.value for item in app.info))

    def test_public_search_save_source_and_preserve_editor_filters(self):
        app = self.app()
        query = 'nhà máy Trung Quốc'
        original_category = core.CATEGORIES[1]
        app.text_input(key='search_query').set_value(query)
        app.selectbox(key='search_provider').set_value('Nguồn công khai · không cần khóa')
        app.multiselect(key='search_sites').set_value(['chinhphu.vn', 'mof.gov.vn'])
        with patch('core.search_news', return_value=self.public_hits()) as search:
            app.button(key='run_search').click().run()
        self.assertFalse(app.exception, str(app.exception))
        self.assertFalse(app.error, str(app.error))
        self.assertEqual(search.call_args.args[0], query)
        self.assertEqual(search.call_args.kwargs['provider'], 'public')
        self.assertEqual(search.call_args.kwargs['domains'], ['chinhphu.vn', 'mof.gov.vn'])
        self.assertTrue(
            any(item.label == 'Sự kiện trong khoảng ngày' and item.value == '1' for item in app.metric)
        )
        self.assertTrue(any('Cần xác minh ngày đăng' in item.label for item in app.expander))
        # A category change must retain typed keywords and the result's original category.
        app.session_state['search_category'] = core.CATEGORIES[2]
        app.run()
        self.assertEqual(app.text_input(key='search_query').value, query)
        self.assertTrue(any('Bộ lọc đã thay đổi' in item.value for item in app.info))
        app.button(key='save_hit_short_0').click().run()
        self.assertFalse(app.exception, str(app.exception))
        saved = core.get_sources()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]['category'], original_category)
        self.assertTrue(saved[0]['date_verified'])
        self.page(app, PAGES[1])
        self.page(app, PAGES[0])
        self.assertEqual(app.text_input(key='search_query').value, query)
        self.assertEqual(app.selectbox(key='search_provider').value, 'Nguồn công khai · không cần khóa')
        self.assertEqual(app.multiselect(key='search_sites').value, ['chinhphu.vn', 'mof.gov.vn'])

    def test_partial_source_failures_show_endpoint_status_and_keep_results(self):
        app = self.app()
        readable = 'https://baochinhphu.vn/home.rss'
        blocked = 'https://mof.gov.vn/'
        findings = SearchResults(
            self.public_hits(),
            diagnostics={
                'provider': 'public',
                'providers_attempted': [readable, blocked],
                'providers_succeeded': [readable],
                'attempted_domain_count': 2,
                'successful_domain_count': 1,
                'failed_sources': [
                    {
                        'domain': 'mof.gov.vn',
                        'url': blocked,
                        'reason': 'empty_index',
                        'message': 'Trang cần JavaScript; chưa đọc được bài viết.',
                    }
                ],
                'warnings': ['Chưa truy cập được mục tin của mof.gov.vn.'],
            },
        )
        with patch('core.search_news', return_value=findings):
            app.button(key='run_search').click().run()
        self.assertFalse(app.exception, str(app.exception))
        self.assertFalse(app.error, str(app.error))
        self.assertTrue(any('Đã đọc được 1/2 tên miền' in item.value for item in app.caption))
        self.assertTrue(
            any(item.label == 'Sự kiện trong khoảng ngày' and item.value == '1' for item in app.metric)
        )
        self.assertEqual(len(app.dataframe), 1)
        rows = app.dataframe[0].value.to_dict('records')
        self.assertEqual(rows[0]['Trạng thái'], 'Đã đọc')
        self.assertIn('JavaScript', rows[1]['Chi tiết'])
        self.assertTrue(any(item.label == 'Lưu nguồn' for item in app.button))

    def test_failed_search_clears_previous_hits_and_retains_inputs(self):
        app = self.app()
        app.text_input(key='search_query').set_value('dự án Việt Nam')
        with patch('core.search_news', return_value=self.public_hits()):
            app.button(key='run_search').click().run()
        self.assertTrue(any(item.key == 'save_hit_short_0' for item in app.button))
        with patch('core.search_news', side_effect=RuntimeError('Dịch vụ tạm thời không phản hồi')):
            app.button(key='run_search').click().run()
        self.assertFalse(app.exception, str(app.exception))
        self.assertTrue(any('Dịch vụ tạm thời không phản hồi' in item.value for item in app.error))
        self.assertFalse(any((item.key or '').startswith('save_hit_') for item in app.button))
        self.assertEqual(app.text_input(key='search_query').value, 'dự án Việt Nam')

    def test_quick_search_presets_populate_and_reset_query(self):
        app = self.app()
        self.assertEqual(app.text_input(key='search_query').value, core.TOPICS[core.CATEGORIES[1]])
        app.pills(key='search_preset_pill').select('📈 FDI').run()
        self.assertFalse(app.exception, str(app.exception))
        self.assertEqual(app.text_input(key='search_query').value, 'FDI')
        # Multi-select combines keywords
        app.pills(key='search_preset_pill').select('🤝 Trung - Việt').run()
        self.assertEqual(app.text_input(key='search_query').value, 'FDI đầu tư Trung Quốc - Việt Nam')
        # Unselecting one keyword keeps the remaining ones
        app.pills(key='search_preset_pill').unselect('📈 FDI').run()
        self.assertEqual(app.text_input(key='search_query').value, 'đầu tư Trung Quốc - Việt Nam')
        # Reset to topic defaults
        app.button(key='use_topic_query').click().run()
        self.assertEqual(app.text_input(key='search_query').value, core.TOPICS[core.CATEGORIES[1]])
        self.assertEqual(app.pills(key='search_preset_pill').value, [])
        # Custom input resets preset selection
        app.pills(key='search_preset_pill').select('📈 FDI').run()
        self.assertEqual(app.text_input(key='search_query').value, 'FDI')
        app.text_input(key='search_query').set_value('tùy chỉnh khác').run()
        self.assertEqual(app.pills(key='search_preset_pill').value, [])

    def test_missing_ai_key_disables_generation_and_keeps_manual_writing(self):
        sid = core.store_source(
            {'url': 'https://chinhphu.vn/test-manual-draft', 'title': 'Nguồn cho bài viết tay'},
            core.CATEGORIES[0],
        )
        app = self.app()
        self.page(app, PAGES[2])
        app.multiselect(key='selected_src').set_value([sid]).run()
        self.assertTrue(app.button(key='generate_draft').disabled)
        self.assertTrue(any('Chưa có khóa AI Box API' in item.value for item in app.info))
        guide = '\n'.join(item.value for item in app.markdown)
        self.assertIn('tài khoản AI Box', guide)
        self.assertFalse('platform.openai.com' in guide)
        captions = '\n'.join(item.value for item in app.caption)
        self.assertIn('không thay đổi cấu hình hoặc hạn mức ChatGPT/Codex', captions)
        self.assertIn('https://api.ai-box.vn/v1', '\n'.join(item.value for item in app.code))
        self.assertTrue(app.button(key='check_ai_connection').disabled)
        self.assertEqual(app.text_input(key='ai_aibox_key').value, '')
        self.assertFalse(any('khởi động lại ứng dụng' in item.value for item in app.info))
        self.assertFalse(app.text_area(key='draft_content').disabled)
        self.assertFalse(app.button(key='save_draft').disabled)

    def ready_ai_writer(self, key='sk-test-local-ui-secret'):
        os.environ['AIBOX_API_KEY'] = key
        sid = core.store_source(
            {
                'url': 'https://chinhphu.vn/test-ai-source',
                'title': 'Nguồn thử nghiệm AI, không phải bản tin thực',
                'text': '原始来源材料，仅用于软件测试，请逐项核实。' * 30,
            },
            core.CATEGORIES[1],
        )
        app = self.app()
        self.page(app, PAGES[2])
        app.multiselect(key='selected_src').set_value([sid])
        app.selectbox(key='write_category').set_value(core.CATEGORIES[1]).run()
        return app, sid

    def test_existing_openai_settings_do_not_enable_aibox_drafting(self):
        with patch('openai.OpenAI') as client:
            app, _ = self.ready_ai_writer(key='')
        client.assert_not_called()
        self.assertTrue(app.button(key='generate_draft').disabled)
        self.assertTrue(app.button(key='check_ai_connection').disabled)
        self.assertTrue(any('Chưa có khóa AI Box API' in item.value for item in app.info))
        self.assertEqual(app.text_input(key='ai_model').value, 'qwen3.8-max-0902')
        self.assertEqual(os.environ['OPENAI_API_KEY'], 'sk-test-unrelated-chat-key')

    def test_ai_readiness_disables_thin_sources_and_missing_official_authority(self):
        os.environ['AIBOX_API_KEY'] = 'sk-test-source-readiness'
        sid = core.store_source(
            {'url': 'https://cafef.vn/test-secondary', 'title': 'Nguồn báo chí', 'text': 'Quá ngắn.'},
            core.CATEGORIES[0],
        )
        app = self.app()
        self.page(app, PAGES[2])
        app.multiselect(key='selected_src').set_value([sid]).run()
        self.assertTrue(app.button(key='generate_draft').disabled)
        self.assertTrue(any('240 ký tự' in item.value for item in app.warning))
        self.assertTrue(any('nguồn chính thức' in item.value for item in app.warning))

    def test_local_ai_configuration_applies_immediately_preserving_draft(self):
        app, sid = self.ready_ai_writer(key='')
        body = '已有中文草稿，连接配置不能覆盖。'
        app.text_input(key='draft_title').set_value('原来的标题')
        app.text_area(key='draft_content').set_value(body)
        app.text_area(key='draft_notes').set_value('保留编辑要求')
        fake_key = 'sk-test-config-save-secret'
        app.text_input(key='ai_aibox_key').set_value(fake_key)
        app.text_input(key='ai_model').set_value('qwen3.8-max-0902')
        with patch('ai_client.check_ai_connection') as probe:
            self.click(app, 'Lưu kết nối AI')
        probe.assert_not_called()
        self.assertEqual(os.environ['AIBOX_API_KEY'], fake_key)
        self.assertEqual(os.environ['OPENAI_API_KEY'], 'sk-test-unrelated-chat-key')
        self.assertEqual(os.environ['OPENAI_MODEL'], 'unrelated-chat-model')
        saved_env = settings.ENV_FILE.read_text(encoding='utf-8')
        self.assertIn('AIBOX_API_KEY', saved_env)
        self.assertNotIn('OPENAI_API_KEY', saved_env)
        self.assertNotIn('OPENAI_MODEL', saved_env)
        self.assertEqual(app.text_input(key='ai_aibox_key').value, '')
        self.assertFalse(app.button(key='generate_draft').disabled)
        self.assertEqual(app.text_input(key='draft_title').value, '原来的标题')
        self.assertEqual(app.text_area(key='draft_content').value, body)
        self.assertEqual(app.text_area(key='draft_notes').value, '保留编辑要求')
        self.assertEqual(app.multiselect(key='selected_src').value, [sid])
        self.assertTrue(any('chưa kiểm tra kết nối' in item.value for item in app.info))
        self.assertTrue(any('không cần khởi động lại' in item.value for item in app.success))
        self.assertFalse(any(fake_key in item.value for item in [*app.text_input, *app.markdown]))
        self.page(app, PAGES[0])
        self.page(app, PAGES[2])
        self.assertEqual(app.text_input(key='ai_model').value, 'qwen3.8-max-0902')
        self.assertEqual(app.text_input(key='ai_aibox_key').value, '')

    def test_ai_settings_failure_clears_key_and_keeps_manual_content(self):
        app, _ = self.ready_ai_writer(key='')
        app.text_area(key='draft_content').set_value('现有手工稿件')
        app.text_input(key='ai_aibox_key').set_value('sk-test-invalid-configuration')
        app.text_input(key='ai_model').set_value('')
        with patch('settings.save_ai_settings', side_effect=ValueError('Model không hợp lệ.')):
            self.click(app, 'Lưu kết nối AI')
        self.assertTrue(any('Model không hợp lệ' in item.value for item in app.error))
        self.assertEqual(app.text_input(key='ai_aibox_key').value, '')
        self.assertEqual(app.text_area(key='draft_content').value, '现有手工稿件')
        self.assertEqual(os.environ['AIBOX_API_KEY'], '')

    def test_ai_probe_is_explicit_and_invalidated_by_configuration_change(self):
        with patch(
            'ai_client.check_ai_connection',
            return_value={'ok': True, 'model': 'qwen3.8-max-0902', 'provider': 'aibox'},
        ) as probe:
            app, sid = self.ready_ai_writer()
            probe.assert_not_called()
            app.text_area(key='draft_content').set_value('测试连接保留的中文草稿')
            app.button(key='check_ai_connection').click().run()
            probe.assert_called_once_with(model='qwen3.8-max-0902')
        self.assertFalse(app.exception, str(app.exception))
        self.assertTrue(any('Đã kiểm tra kết nối thành công' in item.value for item in app.success))
        self.assertEqual(app.text_area(key='draft_content').value, '测试连接保留的中文草稿')
        self.assertEqual(app.multiselect(key='selected_src').value, [sid])
        os.environ['AIBOX_MODEL'] = 'qwen3.8-flash'
        app.run()
        self.assertFalse(any('Đã kiểm tra kết nối thành công' in item.value for item in app.success))
        self.assertTrue(any('chưa kiểm tra kết nối' in item.value for item in app.info))
        with patch(
            'ai_client.check_ai_connection',
            side_effect=AIServiceError('authentication', 'Khóa AI Box không được chấp nhận.'),
        ):
            app.button(key='check_ai_connection').click().run()
        self.assertTrue(any('Khóa AI Box không được chấp nhận' in item.value for item in app.error))
        self.assertFalse(app.button(key='generate_draft').disabled)
        self.assertEqual(app.text_area(key='draft_content').value, '测试连接保留的中文草稿')

    def test_ai_generation_uses_actual_adapter_and_leaves_draft_unapproved(self):
        body = '越南投资观察\n一、项目进展\n请核实原始来源。\n律师建议：核查审批条件。\n免责声明：本文不构成个案法律意见。\n参考来源\nhttps://chinhphu.vn/test-ai-source'
        with patch('openai.OpenAI') as client:
            app, sid = self.ready_ai_writer()
            client.assert_not_called()
            request = client.return_value.__enter__.return_value.chat.completions.create
            request.return_value = {'choices': [{'finish_reason': 'stop', 'message': {'content': body}}]}
            app.button(key='generate_draft').click().run()
            request.assert_called_once()
            sent = request.call_args.kwargs
            self.assertIn('原始来源材料', sent['messages'][-1]['content'])
            self.assertEqual(client.call_args.kwargs['base_url'], 'https://api.ai-box.vn/v1')
            self.assertEqual(client.call_args.kwargs['api_key'], os.environ['AIBOX_API_KEY'])
            self.assertEqual(sent['model'], 'qwen3.8-max-0902')
        self.assertFalse(app.exception, str(app.exception))
        self.assertEqual(app.text_area(key='draft_content').value, body)
        self.assertEqual(app.text_input(key='draft_title').value, '越南投资观察')
        self.assertEqual(app.multiselect(key='selected_src').value, [sid])
        self.assertTrue(any('chưa được xác minh độc lập' in item.value for item in app.success))
        self.assertFalse(core.list_articles())
        self.assertFalse(any(item.key == 'export_master' for item in app.button))

    def test_ai_model_channel_error_has_contextual_steps_instead_of_key_onboarding(self):
        app, sid = self.ready_ai_writer(key='')
        self.assertIn('tạo khóa mới', '\n'.join(item.value for item in app.markdown))
        os.environ['AIBOX_API_KEY'] = 'sk-test-configured-channel-key'
        app.run()
        self.assertNotIn('tạo khóa mới', '\n'.join(item.value for item in app.markdown))
        request_id = '202610240613239989039318268d9d6GXGHkD9h'
        failure = AIServiceError(
            'model_unavailable', 'Model chưa có kênh phục vụ.', status_code=503, request_id=request_id
        )
        with patch('ai_client.check_ai_connection', side_effect=failure) as probe:
            app.button(key='check_ai_connection').click().run()
            probe.assert_called_once()
        self.assertFalse(app.exception, str(app.exception))
        instructions = '\n'.join(item.value for item in app.markdown)
        self.assertIn('https://home.ai-box.vn/console/token', instructions)
        self.assertIn('nhóm của khóa', instructions)
        self.assertNotIn('tạo khóa mới', instructions)
        report = next(item.value for item in app.code if 'Endpoint:' in item.value)
        self.assertIn('Endpoint: https://api.ai-box.vn/v1/chat/completions', report)
        self.assertIn('Model: qwen3.8-max-0902', report)
        self.assertIn('HTTP: 503', report)
        self.assertIn('Mã lỗi ứng dụng: model_unavailable', report)
        self.assertIn(request_id, report)
        self.assertFalse(app.text_area(key='draft_content').disabled)
        self.assertFalse(app.button(key='save_draft').disabled)
        self.assertEqual(app.multiselect(key='selected_src').value, [sid])

    def test_ai_support_report_redacts_all_fields_and_excludes_error_body_and_draft(self):
        secret = 'sk-test-support-report-secret'
        os.environ['AIBOX_MODEL'] = 'model-' + secret
        app, _ = self.ready_ai_writer(key=secret)
        app.text_area(key='draft_content').set_value('EDITORIAL_CONTENT_MUST_NOT_BE_IN_SUPPORT_REPORT')
        failure = AIServiceError('model_unavailable', 'PROVIDER_MESSAGE_MUST_NOT_BE_IN_SUPPORT_REPORT')
        failure.status_code = 503
        failure.request_id = 'req-' + secret
        with patch('ai_client.check_ai_connection', side_effect=failure):
            app.button(key='check_ai_connection').click().run()
        self.assertFalse(app.exception, str(app.exception))
        report = next(item.value for item in app.code if 'Endpoint:' in item.value)
        self.assertNotIn(secret, report)
        self.assertIn('[đã ẩn khóa]', report)
        self.assertNotIn(str(failure), report)
        self.assertNotIn('EDITORIAL_CONTENT', report)
        self.assertNotIn('原始来源材料', report)
        self.assertEqual(
            app.text_area(key='draft_content').value, 'EDITORIAL_CONTENT_MUST_NOT_BE_IN_SUPPORT_REPORT'
        )

    def test_ai_result_time_survives_rerenders_and_handles_older_session_state(self):
        app, _ = self.ready_ai_writer()
        with patch('ai_client.check_ai_connection', return_value={'ok': True}) as probe:
            app.button(key='check_ai_connection').click().run()
            checked_at = app.session_state['_ai_check']['checked_at']
            self.assertEqual(datetime.fromisoformat(checked_at).utcoffset(), timedelta(hours=7))
            app.run()
            self.assertEqual(app.session_state['_ai_check']['checked_at'], checked_at)
            probe.assert_called_once()
        self.assertIn('Phản hồi gần nhất:', '\n'.join(item.value for item in app.caption))
        self.assertIn('không gửi yêu cầu AI mới', '\n'.join(item.value for item in app.caption))
        legacy = dict(app.session_state['_ai_check'])
        legacy.pop('checked_at')
        app.session_state['_ai_check'] = legacy
        with patch('ai_client.check_ai_connection') as probe:
            app.run()
            probe.assert_not_called()
        self.assertFalse(app.exception, str(app.exception))
        self.assertIn('chưa có thời điểm', '\n'.join(item.value for item in app.caption))
        failure = AIServiceError('model_unavailable', 'Model chưa có kênh phục vụ.')
        with patch('core.generate_article', side_effect=failure) as generate:
            app.button(key='generate_draft').click().run()
            failed_at = app.session_state['_ai_generation_error']['checked_at']
            self.assertEqual(datetime.fromisoformat(failed_at).utcoffset(), timedelta(hours=7))
            app.run()
            self.assertEqual(app.session_state['_ai_generation_error']['checked_at'], failed_at)
            generate.assert_called_once()

    def test_invalid_ai_key_keeps_existing_draft_and_never_echoes_provider_error(self):
        app, sid = self.ready_ai_writer()
        app.text_input(key='draft_title').set_value('原来的标题')
        app.text_area(key='draft_content').set_value('原有稿件保持不变')
        secret = os.environ['AIBOX_API_KEY']
        error = openai.AuthenticationError(
            'Provider error containing ' + secret,
            response=httpx.Response(
                401, request=httpx.Request('POST', 'https://api.ai-box.vn/v1/chat/completions')
            ),
            body={'error': {'message': 'Invalid key: ' + secret}},
        )
        with patch('openai.OpenAI') as client:
            client.return_value.__enter__.return_value.chat.completions.create.side_effect = error
            app.button(key='generate_draft').click().run()
        self.assertFalse(app.exception, str(app.exception))
        self.assertTrue(any('không được chấp nhận' in item.value for item in app.error))
        self.assertFalse(any(secret in item.value for item in app.error))
        self.assertEqual(app.text_area(key='draft_content').value, '原有稿件保持不变')
        self.assertEqual(app.text_input(key='draft_title').value, '原来的标题')
        self.assertEqual(app.multiselect(key='selected_src').value, [sid])

    def test_model_channel_failure_replaces_stale_success_and_survives_rerender(self):
        app, sid = self.ready_ai_writer()
        with patch('ai_client.check_ai_connection', return_value={'ok': True}):
            app.button(key='check_ai_connection').click().run()
        self.assertTrue(any('Đã kiểm tra kết nối thành công' in item.value for item in app.success))
        app.text_input(key='draft_title').set_value('原来的标题')
        app.text_area(key='draft_content').set_value('原有稿件保持不变')
        app.text_area(key='draft_notes').set_value('保留编辑要求')
        app.text_area(key='client_confirmation').set_value('Confirmed file reference, test only')
        failure = AIServiceError(
            'model_unavailable',
            'AI Box chưa có kênh phục vụ model cho nhóm tài khoản hiện tại. Liên hệ hỗ trợ AI Box.',
        )
        failure.status_code = 503
        failure.request_id = 'req-ui-model-channel-503'
        with patch('core.generate_article', side_effect=failure) as generate:
            app.button(key='generate_draft').click().run()
            app.run()
            generate.assert_called_once()
        self.assertFalse(app.exception, str(app.exception))
        self.assertFalse(any('Đã kiểm tra kết nối thành công' in item.value for item in app.success))
        self.assertTrue(any('chưa có kênh phục vụ model' in item.value for item in app.error))
        self.assertIn('HTTP 503', '\n'.join(item.value for item in app.caption))
        self.assertIn('AI Box cần mở kênh phục vụ model', '\n'.join(item.value for item in app.caption))
        self.assertIn('req-ui-model-channel-503', '\n'.join(item.value for item in app.code))
        self.assertEqual(app.text_input(key='draft_title').value, '原来的标题')
        self.assertEqual(app.text_area(key='draft_content').value, '原有稿件保持不变')
        self.assertEqual(app.text_area(key='draft_notes').value, '保留编辑要求')
        self.assertEqual(
            app.text_area(key='client_confirmation').value, 'Confirmed file reference, test only'
        )
        self.assertEqual(app.multiselect(key='selected_src').value, [sid])
        self.assertFalse(app.button(key='save_draft').disabled)
        self.assertIn('phê duyệt theo quy trình', '\n'.join(item.value for item in app.caption))
        with patch('ai_client.check_ai_connection', return_value={'ok': True}):
            app.button(key='check_ai_connection').click().run()
        self.assertFalse(any('chưa có kênh phục vụ model' in item.value for item in app.error))
        self.assertTrue(any('Đã kiểm tra kết nối thành công' in item.value for item in app.success))
        self.assertEqual(app.text_area(key='draft_content').value, '原有稿件保持不变')

    def test_ai_failure_details_follow_current_configuration_and_successful_generation(self):
        app, sid = self.ready_ai_writer()
        failure = AIServiceError('model_unavailable', 'Model chưa có kênh cho tài khoản hiện tại.')
        failure.status_code = 503
        failure.request_id = 'req-config-fixture'
        with patch('core.generate_article', side_effect=failure):
            app.button(key='generate_draft').click().run()
        os.environ['AIBOX_MODEL'] = 'different-model'
        with patch('ai_client.check_ai_connection') as probe, patch('core.generate_article') as generate:
            app.run()
            probe.assert_not_called()
            generate.assert_not_called()
        self.assertFalse(any('kênh cho tài khoản' in item.value for item in app.error))
        self.assertNotIn('req-config-fixture', '\n'.join(item.value for item in app.code))
        with patch('ai_client.check_ai_connection', side_effect=failure):
            app.button(key='check_ai_connection').click().run()
        self.assertIn('HTTP 503', '\n'.join(item.value for item in app.caption))
        self.assertIn('req-config-fixture', '\n'.join(item.value for item in app.code))
        with patch('core.generate_article', return_value='# 新标题\n新草稿。[S1]'):
            app.button(key='generate_draft').click().run()
        self.assertFalse(any('kênh cho tài khoản' in item.value for item in app.error))
        self.assertNotIn('req-config-fixture', '\n'.join(item.value for item in app.code))
        self.assertEqual(app.text_input(key='draft_title').value, '新标题')
        self.assertEqual(app.multiselect(key='selected_src').value, [sid])

    def test_remote_editor_cannot_modify_ai_secrets_or_model(self):
        os.environ['FRIC_AUTH_REQUIRED'] = '1'
        with patch('access_control.require_access'):
            app = self.app()
            self.page(app, PAGES[2])
        keys = {item.key for item in app.text_input}
        self.assertTrue({'ai_aibox_key', 'ai_model', 'local_aibox_key', 'local_tavily_key'}.isdisjoint(keys))
        self.assertFalse(
            any(item.label in ('Lưu kết nối AI', 'Lưu cấu hình API trên máy') for item in app.button)
        )
        self.assertTrue(app.button(key='check_ai_connection').disabled)
        self.assertTrue(any('setup_ai.py' in item.value for item in app.caption))
        self.assertFalse(app.text_area(key='draft_content').disabled)

    def test_source_draft_review_approval_and_master_export(self):
        sid = core.store_source(
            {
                'url': 'https://chinhphu.vn/test-editorial-smoke',
                'title': 'Nguồn thử nghiệm biên tập',
                'text': '中资企业关注项目进展。请进一步核查合同条件。' * 30,
            },
            core.CATEGORIES[2],
        )
        app = self.app()
        self.page(app, PAGES[1])
        prefix = f'source_{sid}_'
        app.text_input(key=prefix + 'published').set_value(core.today_vn().isoformat())
        app.text_input(key=prefix + 'reviewer').set_value('Nguoi doi chieu')
        app.text_area(key=prefix + 'date_evidence').set_value(
            'Original publication header: ' + core.today_vn().isoformat()
        )
        app.checkbox(key=prefix + 'date_verified').check()
        self.click(app, 'Lưu chứng cứ & thông tin pháp lý')
        self.assertTrue(core.get_sources([sid])[0]['date_verified'])
        self.page(app, PAGES[2])
        app.multiselect(key='selected_src').set_value([sid])
        app.text_input(key='draft_title').set_value('越南投资观察')
        body = '# 越南投资观察\n一、项目进展\n中资企业关注项目进展。[S1]\n二、律师建议\n建议进一步核查交易条件。\n免责声明：本文仅供参考，不构成个案法律意见。\n参考来源\nhttps://chinhphu.vn/test-editorial-smoke'
        app.text_area(key='draft_content').set_value(body)
        self.page(app, PAGES[0])
        self.page(app, PAGES[2])
        self.assertEqual(app.text_area(key='draft_content').value, body)
        self.assertEqual(app.multiselect(key='selected_src').value, [sid])
        app.button(key='save_draft').click().run()
        self.assertFalse(app.exception, str(app.exception))
        aid = core.list_articles()[0]['id']
        digest = core.get_article(aid)['content_hash'][:12]
        self.assertTrue(app.button(key='export_master').disabled)
        # AI downtime must not block review/approval of an already saved manual draft.
        os.environ['AIBOX_API_KEY'] = 'sk-test-manual-review-during-outage'
        app.run()
        failure = AIServiceError('model_unavailable', 'Model AI Box chưa có kênh phục vụ tài khoản.')
        failure.status_code = 503
        failure.request_id = 'req-manual-review-fixture'
        with patch('core.generate_article', side_effect=failure) as generate:
            app.button(key='generate_draft').click().run()
            app.run()
            generate.assert_called_once()
        self.assertEqual(app.session_state['editing_article_id'], aid)
        self.assertEqual(app.text_area(key='draft_content').value, body)
        self.assertEqual(app.multiselect(key='selected_src').value, [sid])
        self.assertTrue(app.button(key='export_master').disabled)
        # Drive the actual per-claim evidence UI, including analysis disposition.
        for unit in core.claim_units(body, core.get_sources([sid])):
            review_key = f'{aid}_{digest}_{unit["id"]}'
            if unit['source_ids']:
                app.text_area(key='excerpt_' + review_key).set_value('中资企业关注项目进展。')
            else:
                app.selectbox(key='disposition_' + review_key).set_value('Phân tích / khuyến nghị thuần túy')
            app.text_input(key='reviewer_' + review_key).set_value('Evidence editor')
            app.checkbox(key='attest_' + review_key).check()
            form_key = f'FormSubmitter:review_{review_key}-Ghi nhận đối chiếu'
            app.button(key=form_key).click().run()
            self.assertFalse(app.exception, str(app.exception))
            self.assertEqual([item.value for item in app.error], [str(failure)])
        for role in ['editor', 'lawyer']:
            app.text_input(key='approval_reviewer').set_value(role.title())
            next(item for item in app.selectbox if item.label == 'Vai trò phê duyệt').set_value(role)
            app.checkbox(key=f'approval_attestation_{aid}_{digest}').check()
            self.click(app, 'Phê duyệt phiên bản đã lưu')
            self.assertEqual([item.value for item in app.error], [str(failure)])
        self.assertFalse(app.button(key='export_master').disabled)
        # Unsaved content must remove the review/export controls until saved again.
        app.text_area(key='draft_content').set_value(body + '\n建议核查商业条件。').run()
        self.assertFalse(any(item.key == 'export_master' for item in app.button))
        app.text_area(key='draft_content').set_value(body).run()
        app.button(key='export_master').click().run()
        self.assertFalse(app.exception, str(app.exception))
        self.assertTrue(core.MASTER.exists())
        self.assertTrue(core.get_article(aid)['docx_saved'])
        self.page(app, PAGES[3])
        self.assertTrue(any(item.label == 'Tạo bản sửa mới' for item in app.button))


if __name__ == '__main__':
    unittest.main()
