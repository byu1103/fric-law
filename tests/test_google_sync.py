"""Google integration contract tests: no OAuth, network, or real Drive writes."""

import copy
import json
import stat
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import google_docs_sync as sync


class Request:
    def __init__(self, action):
        self.action = action

    def execute(self):
        return self.action()


class FakeDrive:
    def __init__(self):
        self.items = {}
        self.created = []
        self.queries = []
        self.moves = []
        self.fail_read = None
        self.fail_move_once = False
        self.lose_create_response = False

    def files(self):
        return self

    def list(self, **arguments):
        self.queries.append(arguments['q'])

        def action():
            matches = []
            for item in self.items.values():
                query = arguments['q']
                if item.get('trashed'):
                    continue
                if f"name='{item['name']}'" not in query or f"mimeType='{item['mimeType']}'" not in query:
                    continue
                if ' in parents' in query and not any(
                    f"'{parent}' in parents" in query for parent in item.get('parents', [])
                ):
                    continue
                matches.append(copy.deepcopy(item))
            return {'files': matches}

        return Request(action)

    def create(self, body, fields):
        def action():
            identity = 'folder' + str(len(self.created) + 1)
            self.items[identity] = {'id': identity, **body, 'parents': [], 'trashed': False}
            self.created.append(identity)
            if self.lose_create_response:
                self.lose_create_response = False
                raise TimeoutError('folder created, response lost')
            return {'id': identity}

        return Request(action)

    def get(self, fileId, fields):
        def action():
            if self.fail_read == fileId:
                raise TimeoutError('simulated private API response')
            return copy.deepcopy(self.items[fileId])

        return Request(action)

    def update(self, **arguments):
        def action():
            self.moves.append(arguments)
            if self.fail_move_once:
                self.fail_move_once = False
                raise TimeoutError('move failed')
            item = self.items[arguments['fileId']]
            item['parents'] = [arguments['addParents']]
            return copy.deepcopy(item)

        return Request(action)


class FakeDocs:
    def __init__(self, drive):
        self.drive = drive
        self.created = []
        self.text = {}
        self.revisions = {}
        self.batches = []
        self.writes = 0
        self.fail_read = False
        self.timeout_after_write = False
        self.fail_before_write = False
        self.conflict_once = False
        self.no_revision = False
        self.tabs = False
        self.lose_create_response = False

    def documents(self):
        return self

    def create(self, body):
        def action():
            identity = 'doc' + str(len(self.created) + 1)
            self.drive.items[identity] = {
                'id': identity,
                'name': body['title'],
                'mimeType': sync.DOCUMENT_MIME,
                'parents': [],
                'trashed': False,
            }
            self.text[identity], self.revisions[identity] = '', 1
            self.created.append(identity)
            if self.lose_create_response:
                self.lose_create_response = False
                raise TimeoutError('document created, response lost')
            return {'documentId': identity}

        return Request(action)

    def get(self, documentId, includeTabsContent):
        def action():
            if self.fail_read:
                raise TimeoutError('read failed')
            content = self.text.get(documentId, '')
            body = {
                'content': [
                    {
                        'startIndex': 1,
                        'endIndex': sync._utf16_length(content) + 2,
                        'paragraph': {'elements': [{'textRun': {'content': content + '\n'}}]},
                    }
                ]
            }
            document = {'documentId': documentId}
            if not self.no_revision:
                document['revisionId'] = 'r' + str(self.revisions.get(documentId, 1))
            if self.tabs:
                document['tabs'] = [{'tabProperties': {'tabId': 'tab-one'}, 'documentTab': {'body': body}}]
            else:
                document['body'] = body
            return document

        return Request(action)

    def batchUpdate(self, documentId, body):
        def action():
            self.batches.append(copy.deepcopy(body))
            if self.conflict_once:
                self.conflict_once = False
                self.revisions[documentId] += 1
            if body['writeControl']['requiredRevisionId'] != 'r' + str(self.revisions[documentId]):
                raise ValueError('revision conflict')
            if self.fail_before_write:
                self.fail_before_write = False
                raise TimeoutError('not written')
            self.text[documentId] += body['requests'][0]['insertText']['text']
            self.revisions[documentId] += 1
            self.writes += 1
            if self.timeout_after_write:
                self.timeout_after_write = False
                raise TimeoutError('written, response lost')
            return {'writeControl': {'requiredRevisionId': 'r' + str(self.revisions[documentId])}}

        return Request(action)


class TestGoogleSync(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.config = Path(self.temporary.name) / 'google_sync_state.json'
        self.drive = FakeDrive()
        self.docs = FakeDocs(self.drive)
        self.row = {
            'id': 'a1',
            'title': '越南投资观察😀',
            'content': '事实 [S1]\n参考来源',
            'source_snapshot': json.dumps(
                [
                    {
                        'title': '官方原文',
                        'url': 'https://vanban.chinhphu.vn/example',
                        'published': '2026-10-22',
                    }
                ]
            ),
        }
        self.patches = [
            patch.object(sync, 'CONFIG', self.config),
            patch.object(sync, 'clients', return_value=(self.drive, self.docs)),
            patch.object(sync, 'export_lock', side_effect=lambda path: nullcontext()),
            patch.object(sync, 'require_approved', side_effect=lambda aid: {**self.row, 'id': aid}),
            patch.object(sync, 'export_fingerprint', return_value='same-content'),
            patch.object(sync, 'record_export'),
            patch.object(sync, 'mark_gdoc_saved'),
        ]
        for item in self.patches:
            item.start()
        self.addCleanup(self.temporary.cleanup)
        for item in reversed(self.patches):
            self.addCleanup(item.stop)

    def configured(self):
        self.drive.items['f1'] = {
            'id': 'f1',
            'name': sync.FOLDER_NAME,
            'mimeType': sync.FOLDER_MIME,
            'parents': [],
            'trashed': False,
        }
        self.drive.items['d1'] = {
            'id': 'd1',
            'name': sync.DOCUMENT_NAME,
            'mimeType': sync.DOCUMENT_MIME,
            'parents': ['f1'],
            'trashed': False,
        }
        self.docs.text['d1'], self.docs.revisions['d1'] = '', 1
        sync._atomic_json(self.config, {'folder_id': 'f1', 'doc_id': 'd1'})

    def test_requires_approval_before_credentials(self):
        sync.require_approved.side_effect = ValueError('approval missing')
        with self.assertRaises(ValueError):
            sync.append_to_gdoc('draft')
        sync.clients.assert_not_called()
        sync.mark_gdoc_saved.assert_not_called()

    def test_configured_read_failure_never_recreates(self):
        self.configured()
        self.drive.fail_read = 'd1'
        with self.assertRaises(RuntimeError):
            sync.ensure_master(self.drive, self.docs)
        self.assertEqual(self.docs.created, [])
        self.assertEqual(self.drive.created, [])
        self.assertEqual(json.loads(self.config.read_text())['doc_id'], 'd1')

    def test_docs_read_failure_never_recreates(self):
        self.configured()
        self.docs.fail_read = True
        with self.assertRaises(RuntimeError):
            sync.ensure_master(self.drive, self.docs)
        self.assertEqual(self.docs.created, [])
        self.assertEqual(self.drive.created, [])

    def test_partial_move_retry_reuses_created_document(self):
        self.drive.fail_move_once = True
        with self.assertRaises(RuntimeError):
            sync.ensure_master(self.drive, self.docs)
        saved = json.loads(self.config.read_text())
        self.assertEqual(saved['doc_id'], 'doc1')
        self.assertTrue(saved['pending_move'])
        self.assertEqual(sync.ensure_master(self.drive, self.docs), 'doc1')
        self.assertEqual(len(self.docs.created), 1)
        self.assertEqual(len(self.drive.created), 1)
        self.assertFalse(json.loads(self.config.read_text())['pending_move'])

    def test_lost_creation_response_recovers_global_unique_title(self):
        self.configured()
        self.drive.items['d1']['parents'] = []
        sync._atomic_json(self.config, {'folder_id': 'f1', 'pending_create': True})
        self.assertEqual(sync.ensure_master(self.drive, self.docs), 'd1')
        self.assertEqual(self.docs.created, [])
        self.assertEqual(self.drive.items['d1']['parents'], ['f1'])

    def test_uncertain_doc_create_does_not_repeat_while_lookup_is_empty(self):
        self.docs.lose_create_response = True
        with self.assertRaises(RuntimeError):
            sync.ensure_master(self.drive, self.docs)
        self.assertTrue(json.loads(self.config.read_text())['pending_create'])
        # Drive's index may not expose a just-created Doc yet.
        with patch.object(sync, '_unique_named', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'không tạo master thứ hai'):
                sync.ensure_master(self.drive, self.docs)
        self.assertEqual(self.docs.created, ['doc1'])
        self.assertEqual(sync.ensure_master(self.drive, self.docs), 'doc1')
        self.assertEqual(self.docs.created, ['doc1'])

    def test_uncertain_folder_create_does_not_repeat_while_lookup_is_empty(self):
        self.drive.lose_create_response = True
        with self.assertRaises(RuntimeError):
            sync.ensure_master(self.drive, self.docs)
        self.assertTrue(json.loads(self.config.read_text())['pending_folder_create'])
        with patch.object(sync, '_unique_named', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'không tạo thư mục thứ hai'):
                sync.ensure_master(self.drive, self.docs)
        self.assertEqual(self.drive.created, ['folder1'])
        self.assertEqual(sync.ensure_master(self.drive, self.docs), 'doc1')
        self.assertEqual(self.drive.created, ['folder1'])

    def test_ambiguous_named_resources_fail_closed(self):
        self.configured()
        self.config.unlink()
        self.drive.items['f2'] = {**self.drive.items['f1'], 'id': 'f2'}
        with self.assertRaisesRegex(RuntimeError, 'trùng tên'):
            sync.ensure_master(self.drive, self.docs)
        self.assertEqual(self.docs.created, [])

    def test_append_idempotent_for_article_and_content(self):
        self.configured()
        for identity in ('a1', 'a1', 'a2'):
            self.assertTrue(sync.append_to_gdoc(identity).endswith('/d1/edit'))
        self.assertEqual(self.docs.writes, 1)
        self.assertEqual(sync.mark_gdoc_saved.call_count, 3)
        self.assertTrue(
            all('mimeType=' in query and 'trashed=false' in query for query in self.drive.queries)
        )

    def test_timeout_after_write_is_reconciled(self):
        self.configured()
        self.docs.timeout_after_write = True
        sync.append_to_gdoc('a1')
        self.assertEqual(self.docs.writes, 1)
        sync.mark_gdoc_saved.assert_called_once_with('a1')

    def test_timeout_before_write_does_not_mark_saved(self):
        self.configured()
        self.docs.fail_before_write = True
        with self.assertRaises(RuntimeError):
            sync.append_to_gdoc('a1')
        sync.mark_gdoc_saved.assert_not_called()
        sync.record_export.assert_not_called()
        sync.append_to_gdoc('a1')
        self.assertEqual(self.docs.writes, 1)

    def test_revision_conflict_does_not_retry_mutation(self):
        self.configured()
        self.docs.conflict_once = True
        with self.assertRaises(RuntimeError):
            sync.append_to_gdoc('a1')
        self.assertEqual(len(self.docs.batches), 1)
        self.assertEqual(self.docs.writes, 0)
        sync.mark_gdoc_saved.assert_not_called()
        self.assertEqual(self.docs.batches[0]['writeControl'], {'requiredRevisionId': 'r1'})

    def test_missing_revision_does_not_write(self):
        self.configured()
        self.docs.no_revision = True
        with self.assertRaisesRegex(RuntimeError, 'revision'):
            sync.append_to_gdoc('a1')
        self.assertEqual(self.docs.batches, [])
        sync.mark_gdoc_saved.assert_not_called()

    def test_saved_database_flag_with_missing_remote_marker_fails_closed(self):
        self.configured()
        self.row['gdoc_saved'] = 1
        with self.assertRaisesRegex(RuntimeError, 'master thiếu marker'):
            sync.append_to_gdoc('a1')
        self.assertEqual(self.docs.batches, [])
        sync.mark_gdoc_saved.assert_not_called()

    def test_tab_aware_links_use_utf16_offsets_and_snapshot(self):
        self.configured()
        self.docs.tabs = True
        sync.append_to_gdoc('a1')
        requests = self.docs.batches[0]['requests']
        self.assertEqual(requests[0]['insertText']['endOfSegmentLocation'], {'tabId': 'tab-one'})
        text = requests[0]['insertText']['text']
        url = 'https://vanban.chinhphu.vn/example'
        link = requests[1]['updateTextStyle']
        self.assertEqual(link['range']['tabId'], 'tab-one')
        self.assertEqual(link['range']['startIndex'], 1 + sync._utf16_length(text[: text.index(url)]))
        self.assertEqual(link['textStyle']['link']['url'], url)
        self.assertIn('[FRIC-CONTENT-HASH:same-content]', text)

    def test_state_is_private_and_wrong_mime_is_not_replaced(self):
        self.configured()
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)
        self.drive.items['d1']['mimeType'] = 'text/plain'
        with self.assertRaises(RuntimeError):
            sync.ensure_master(self.drive, self.docs)
        self.assertEqual(self.docs.created, [])


if __name__ == '__main__':
    unittest.main()
