"""Cited visual artifacts must retain all supplied facts and explicit review."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import visuals


class TestVisuals(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.workspace = patch.object(visuals, 'WORKSPACE', self.directory)
        self.workspace.start()
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(self.workspace.stop)
        self.source = 'https://vanban.chinhphu.vn/example'

    def test_explicit_review_required(self):
        with self.assertRaises(ValueError):
            visuals.fact_visual('标题', '事实', self.source)
        with self.assertRaises(ValueError):
            visuals.location_map('测试项目', 10, 106, self.source)
        self.assertFalse((self.directory / 'visuals').exists())

    def test_sources_must_pass_allowlist(self):
        with self.assertRaises(ValueError):
            visuals.fact_visual('标题', '事实', 'javascript:alert(1)', reviewed=True)
        with self.assertRaises(ValueError):
            visuals.location_map(
                '测试项目', 10, 106, 'https://untrusted.invalid/a', coordinates_verified=True
            )

    def test_map_requires_named_finite_coordinates(self):
        for project, lat, lon in [
            ('', 10, 106),
            ('测试', float('nan'), 106),
            ('测试', 10, float('inf')),
            ('测试', True, 106),
            ('测试', 91, 106),
            ('测试', 10, -181),
        ]:
            with self.subTest(project=project, lat=lat, lon=lon):
                with self.assertRaises(ValueError):
                    visuals.location_map(project, lat, lon, self.source, coordinates_verified=True)

    def test_map_escapes_markup_and_preserves_clickable_source(self):
        output = visuals.location_map(
            '<img src=x onerror=alert(1)>`${alert(1)}`测试项目',
            10,
            106,
            self.source,
            coordinates_verified=True,
        )
        content = output.read_text(encoding='utf-8')
        self.assertNotIn('<img src=x', content)
        self.assertNotIn('${alert(1)}', content)
        self.assertIn('href=', content)
        self.assertIn(self.source, content)
        metadata = json.loads(output.with_suffix('.json').read_text(encoding='utf-8'))
        self.assertEqual(metadata['source_url'], self.source)
        self.assertTrue(metadata['coordinates_verified_by_editor'])
        self.assertFalse(metadata['inferred_coordinates'])

    def test_fact_card_keeps_review_and_source_metadata(self):
        output = visuals.fact_visual(
            '越南投资观察', '示例：请以官方原文及律师审核结果为准。', self.source, reviewed=True
        )
        from PIL import Image

        with Image.open(output) as image:
            self.assertEqual(image.size, (1200, 630))
        metadata = json.loads(output.with_suffix('.json').read_text(encoding='utf-8'))
        self.assertEqual(metadata['source_url'], self.source)
        self.assertTrue(metadata['reviewed_by_editor'])
        self.assertFalse(metadata['actual_project_rendering'])

    def test_long_fact_is_rejected_instead_of_silently_truncated(self):
        with self.assertRaisesRegex(ValueError, 'quá dài'):
            visuals.fact_visual('标题', '未经删减的完整事实' * 100, self.source, reviewed=True)
        self.assertEqual(list(self.directory.rglob('*.png')), [])

    def test_generate_ai_image_validates_prompt_and_saves_metadata(self):
        with self.assertRaises(ValueError):
            visuals.generate_ai_image('')
        with self.assertRaises(ValueError):
            visuals.generate_ai_image('   ')

        class MockResponse:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self):
                return b'FAKE_JPEG_IMAGE_DATA_EXCEEDING_ONE_THOUSAND_BYTES_' * 30

        with patch('urllib.request.urlopen', return_value=MockResponse()):
            output = visuals.generate_ai_image('Hanoi investment meeting', title='Hanoi Office')
            self.assertTrue(output.exists())
            self.assertTrue(output.name.endswith('.jpg'))
            metadata = json.loads(output.with_suffix('.json').read_text(encoding='utf-8'))
            self.assertEqual(metadata['prompt'], 'Hanoi investment meeting')
            self.assertEqual(metadata['title'], 'Hanoi Office')
            self.assertTrue(metadata['is_conceptual_illustration'])
            self.assertFalse(metadata['actual_project_rendering'])


if __name__ == '__main__':
    unittest.main()
