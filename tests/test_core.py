import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import patch

import core
from docx import Document


class TestFricCore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = patch.multiple(
            core, WORKSPACE=self.root, DB=self.root / 'articles.sqlite3', MASTER=self.root / 'MASTER.docx'
        )
        self.paths.start()
        core.init()
        self.sid = core.store_source(
            {
                'url': 'https://chinhphu.vn/test',
                'title': 'Nguồn thử nghiệm',
                'text': '中资企业关注项目进展。请进一步核查合同条件。' * 30,
            }
        )
        self.content = '# 越南投资观察\n一、项目进展\n中资企业关注项目进展。[S1]\n二、律师建议\n建议进一步核查交易条件。\n免责声明：本文仅供参考，不构成个案法律意见。\n参考来源\nhttps://chinhphu.vn/test'

    def tearDown(self):
        self.paths.stop()
        self.temp.cleanup()

    def draft(self, content=None):
        return core.save_article('越南投资观察', core.CATEGORIES[2], content or self.content, [self.sid])

    def review(self, aid):
        row = core.get_article(aid)
        for unit in core.claim_units(row['content'], json.loads(row['source_snapshot'])):
            if unit['source_ids']:
                core.review_claim(aid, unit['id'], self.sid, '中资企业关注项目进展。', 'Evidence editor')
            else:
                core.review_claim(aid, unit['id'], '', '', 'Evidence editor', 'analysis')

    def approve(self, aid):
        self.review(aid)
        core.approve_article(aid, 'Editor', 'editor')
        core.approve_article(aid, 'Lawyer', 'lawyer')

    def test_source_dedup_order_and_date_proof(self):
        other = core.store_source(
            {
                'url': 'https://vnexpress.net/story?utm_source=test',
                'title': 'Other',
                'published': '2026-10-22',
            }
        )
        again = core.store_source({'url': 'https://chinhphu.vn/test', 'title': 'Same'})
        self.assertEqual(again, self.sid)
        self.assertEqual([s['id'] for s in core.get_sources([other, self.sid])], [other, self.sid])
        self.assertFalse(core.get_sources([other])[0]['date_verified'])
        core.update_source(
            other,
            published='2026-10-22',
            date_verified=True,
            date_evidence='Original article header checked',
            verified_by='Editor',
        )
        self.assertTrue(core.get_sources([other])[0]['date_verified'])
        core.update_source(other, published='2026-10-21')
        self.assertFalse(core.get_sources([other])[0]['date_verified'])

    def test_direct_export_requires_claim_reviews_and_both_approvals(self):
        aid = self.draft()
        with self.assertRaises(ValueError):
            core.append_master_docx(aid)
        with self.assertRaises(ValueError):
            core.approve_article(aid, 'Editor', 'editor')
        self.review(aid)
        core.approve_article(aid, 'Editor', 'editor')
        with self.assertRaises(ValueError):
            core.append_master_docx(aid)
        core.approve_article(aid, 'Lawyer', 'lawyer')
        self.assertEqual(core.require_approved(aid)['status'], 'approved')

    def test_exact_quote_and_cited_source_required(self):
        aid = self.draft()
        unit = next(
            u for u in core.claim_units(self.content, core.get_sources([self.sid])) if u['source_ids']
        )
        with self.assertRaises(ValueError):
            core.review_claim(aid, unit['id'], self.sid, 'A fabricated excerpt', 'Editor')
        with self.assertRaises(ValueError):
            core.review_claim(aid, unit['id'], self.sid, '中资企业关注项目进展。', '')
        core.review_claim(aid, unit['id'], self.sid, '中资企业关注项目进展。', 'Editor')
        self.assertTrue(core.get_claim_reviews(aid)[unit['id']]['official'])

    def test_legal_claim_requires_primary_text_and_legal_fields(self):
        body = self.content.replace('中资企业关注项目进展。', '规定中资企业必须申报。')
        aid = self.draft(body)
        unit = next(u for u in core.claim_units(body, core.get_sources([self.sid])) if u['legal'])
        core.update_source(self.sid, text='规定中资企业必须申报。' * 30)
        core.save_article('越南投资观察', core.CATEGORIES[2], body, [self.sid], aid)
        with self.assertRaises(ValueError):
            core.review_claim(aid, unit['id'], self.sid, '规定中资企业必须申报。', 'Lawyer')
        with self.assertRaises(ValueError):
            core.review_claim(aid, unit['id'], '', '', 'Lawyer', 'analysis')
        legal = dict(
            zip(
                core.LEGAL_FIELDS,
                [
                    'Test authority',
                    'TEST document',
                    'Article TEST',
                    '2026-01-01',
                    '2026-02-01',
                    'Test status checked',
                    'https://vbpl.vn/test',
                ],
            )
        )
        core.update_source(self.sid, source_kind='legal', legal_json=legal)
        core.save_article('越南投资观察', core.CATEGORIES[2], body, [self.sid], aid)
        core.review_claim(aid, unit['id'], self.sid, '规定中资企业必须申报。', 'Lawyer')

    def test_revision_edit_invalidates_approvals_and_preserves_history(self):
        aid = self.draft()
        self.approve(aid)
        changed = self.content.replace('交易条件', '付款安排')
        core.save_article('越南投资观察', core.CATEGORIES[2], changed, [self.sid], aid)
        self.assertEqual(len(core.get_revisions(aid)), 2)
        self.assertEqual(core.get_approvals(aid), [])
        self.assertEqual(core.get_claim_reviews(aid), {})
        self.assertEqual(core.get_article(aid)['status'], 'draft')

    def test_evidence_edit_invalidates_approvals(self):
        aid = self.draft()
        self.approve(aid)
        core.update_source(self.sid, text='New source evidence. ' * 30)
        self.assertEqual(core.get_approvals(aid), [])
        with self.assertRaises(ValueError):
            core.require_approved(aid)
        core.save_article('越南投资观察', core.CATEGORIES[2], self.content, [self.sid], aid)
        self.assertEqual(len(core.get_revisions(aid)), 2)

    def test_review_change_revokes_existing_signoffs(self):
        aid = self.draft()
        self.approve(aid)
        self.review(aid)
        self.assertEqual(core.get_approvals(aid), [])
        history = core.get_approval_history(aid)
        self.assertEqual(sum(e['event'] == 'approved' for e in history), 2)
        self.assertEqual(sum(e['event'] == 'revoked' for e in history), 2)

    def test_master_dedup_and_crash_recovery(self):
        aid = self.draft()
        self.approve(aid)
        with patch.object(
            core, 'record_export', side_effect=sqlite3.OperationalError('simulated DB failure')
        ):
            with self.assertRaises(sqlite3.OperationalError):
                core.append_master_docx(aid)
        path, created = core.append_master_docx(aid)
        self.assertFalse(created)
        self.assertTrue(core.get_article(aid)['docx_saved'])
        duplicate = self.draft()
        self.approve(duplicate)
        _, created = core.append_master_docx(duplicate)
        self.assertFalse(created)
        doc = Document(path)
        self.assertEqual(sum('[FRIC-ARTICLE-ID:' in p.text for p in doc.paragraphs), 1)
        hyperlinks = doc.part.rels.values()
        self.assertTrue(any(r.reltype.endswith('/hyperlink') for r in hyperlinks))
        self.assertFalse(core.append_master_docx(aid)[1])

    def test_master_missing_fail_closed_and_exported_history_immutable(self):
        aid = self.draft()
        self.approve(aid)
        core.append_master_docx(aid)
        with self.assertRaises(ValueError):
            core.save_article('Changed', core.CATEGORIES[2], self.content + ' edit', [self.sid], aid)
        core.MASTER.unlink()
        with self.assertRaises(ValueError):
            core.append_master_docx(aid)

    def test_concurrent_export_appends_only_once(self):
        from concurrent.futures import ThreadPoolExecutor

        aid = self.draft()
        self.approve(aid)
        with ThreadPoolExecutor(max_workers=3) as pool:
            outcomes = list(pool.map(lambda _: core.append_master_docx(aid)[1], range(3)))
        self.assertEqual(outcomes.count(True), 1)
        self.assertEqual(sum('[FRIC-ARTICLE-ID:' in p.text for p in Document(core.MASTER).paragraphs), 1)

    def test_distinct_append_preserves_previous_article_xml(self):
        aid = self.draft()
        self.approve(aid)
        core.append_master_docx(aid)
        first = Document(core.MASTER)
        original_paragraphs = [p._p.xml for p in first.paragraphs]
        self.assertTrue(first.paragraphs[0].runs[0].font.hidden)
        self.assertIsNone(first.styles['Title'].element.find('.//' + core.qn('w:pBdr')))
        newer = core.save_article(
            '越南交易观察',
            core.CATEGORIES[2],
            self.content.replace('越南投资观察', '越南交易观察'),
            [self.sid],
        )
        self.approve(newer)
        self.assertTrue(core.append_master_docx(newer)[1])
        updated = Document(core.MASTER)
        self.assertEqual(
            [p._p.xml for p in updated.paragraphs[: len(original_paragraphs)]], original_paragraphs
        )
        with self.assertRaises(ValueError):
            core.approve_article(aid, 'Replacement editor', 'editor')

    def test_claim_coverage_in_headings_and_boilerplate(self):
        body = (
            self.content
            + '\n二、项目投资额达到50亿美元\n免责声明：一般信息。本项目今年已经开工。\n参考来源：本项目已经获批。\n作者：该项目已经投产。'
        )
        units = core.claim_units(body, core.get_sources([self.sid]))
        covered = '\n'.join(u['text'] for u in units)
        for value in ['50亿美元', '已经开工', '已经获批', '已经投产']:
            self.assertIn(value, covered)

    def test_actual_legacy_schema_migration_is_additive(self):
        original_db = self.root / 'original.sqlite3'
        with closing(sqlite3.connect(original_db)) as con:
            con.execute(
                'CREATE TABLE articles (id TEXT PRIMARY KEY,title TEXT NOT NULL,category TEXT,content TEXT NOT NULL,source_ids TEXT NOT NULL,created TEXT NOT NULL,status TEXT DEFAULT "draft",docx_saved INTEGER DEFAULT 0,gdoc_saved INTEGER DEFAULT 0)'
            )
            con.execute(
                'INSERT INTO articles VALUES (?,?,?,?,?,?,?,?,?)',
                (
                    'old',
                    'Old title',
                    'Old category',
                    'Preserved original',
                    '[]',
                    '2025-01-01',
                    'approved',
                    1,
                    0,
                ),
            )
            con.commit()
        with patch.object(core, 'DB', original_db):
            core.init()
            row = core.get_article('old')
            self.assertEqual(row['content'], 'Preserved original')
            self.assertEqual(row['docx_saved'], 1)
            self.assertEqual(row['status'], 'draft')
            self.assertEqual(row['source_snapshot'], '[]')

    def test_audit_citations_urls_and_pending_fields(self):
        body = (
            self.content.replace('[S1]', '[S9]').replace(
                'https://chinhphu.vn/test', 'https://invented.test/law'
            )
            + '\n[待核实]'
        )
        warnings = '\n'.join(core.audit_text(body, core.get_sources([self.sid])))
        self.assertIn('Mã nguồn', warnings)
        self.assertIn('URL chưa có', warnings)
        self.assertIn('chờ xác minh', warnings)
        self.assertTrue(
            core.audit_text(
                self.content.replace('中资企业', '第123/2026/NĐ-CP号中资企业'), core.get_sources([self.sid])
            )
        )

    def test_no_fric_participation_without_client_confirmation(self):
        aid = self.draft(self.content.replace('建议进一步核查交易条件。', 'FRIC LAW参与该项目。'))
        self.assertTrue(any('khách hàng' in x for x in core.approval_requirements(aid)))

    def test_legacy_database_migration_keeps_content(self):
        with core.connection() as con:
            con.execute(
                'INSERT INTO articles (id,title,content,source_ids,created,status) VALUES (?,?,?,?,?,?)',
                ('legacy', 'Old', 'Keep old approved text', '[]', '2026-01-01', 'approved'),
            )
        core.init()
        row = core.get_article('legacy')
        self.assertEqual(row['content'], 'Keep old approved text')
        self.assertEqual(row['status'], 'draft')
        with self.assertRaises(ValueError):
            core.require_approved('legacy')


if __name__ == '__main__':
    unittest.main()
