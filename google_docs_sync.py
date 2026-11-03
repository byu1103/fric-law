"""Optional, approval-gated append to one Google Docs master.

No Google package or credential is needed to import the local application.
Remote markers reconcile a lost API response before a later attempt can append.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from core import WORKSPACE, export_fingerprint, export_lock, mark_gdoc_saved, record_export, require_approved

SCOPES = ['https://www.googleapis.com/auth/drive.file', 'https://www.googleapis.com/auth/documents']
SECRET = WORKSPACE / 'google_oauth_client.json'
TOKEN = WORKSPACE / 'google_token.json'
CONFIG = WORKSPACE / 'google_sync_state.json'
FOLDER_NAME = 'FRIC LAW WeChat Content Studio'
DOCUMENT_NAME = 'FRIC LAW 微信公众号文章汇总'
FOLDER_MIME = 'application/vnd.google-apps.folder'
DOCUMENT_MIME = 'application/vnd.google-apps.document'


class SyncError(RuntimeError):
    """A dashboard-safe message without an OAuth or API response payload."""


def _atomic_json(path, value):
    """Persist each completed remote step before starting the next one."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            os.chmod(temporary, 0o600)
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def clients():
    if not SECRET.is_file():
        raise SyncError('Chưa có OAuth Desktop Client tại ' + str(SECRET))
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        raise SyncError('Cài các gói Google trong requirements.txt để bật đồng bộ.') from None
    try:
        if TOKEN.exists():
            os.chmod(TOKEN, 0o600)
        credentials = Credentials.from_authorized_user_file(str(TOKEN), SCOPES) if TOKEN.exists() else None
        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(str(SECRET), SCOPES)
                credentials = flow.run_local_server(port=0, open_browser=True)
            _atomic_json(TOKEN, json.loads(credentials.to_json()))
        return (
            build('drive', 'v3', credentials=credentials, cache_discovery=False),
            build('docs', 'v1', credentials=credentials, cache_discovery=False),
        )
    except Exception:
        # API exception bodies and OAuth payloads must never reach the dashboard.
        raise SyncError(
            'Không kết nối được Google. Kiểm tra OAuth, quyền và kết nối mạng; khóa không được hiển thị.'
        ) from None


def _read_state():
    if not CONFIG.exists():
        return {}
    try:
        state = json.loads(CONFIG.read_text(encoding='utf-8'))
        if not isinstance(state, dict):
            raise ValueError
        for field in ('folder_id', 'doc_id'):
            if field in state and (not isinstance(state[field], str) or not state[field]):
                raise ValueError
        return state
    except (OSError, ValueError, TypeError):
        raise SyncError(
            'Trạng thái Google không đọc được. Khôi phục tệp trạng thái; không tự tạo master khác.'
        ) from None


def _quote(value):
    return value.replace('\\', '\\\\').replace("'", "\\'")


def _unique_named(drive, name, mime, parent=None):
    query = f"name='{_quote(name)}' and mimeType='{mime}' and trashed=false"
    if parent:
        query += f" and '{_quote(parent)}' in parents"
    matches = []
    token = None
    while True:
        arguments = {
            'q': query,
            'fields': 'nextPageToken,files(id,name,mimeType,parents,trashed)',
            'pageSize': 100,
        }
        if token:
            arguments['pageToken'] = token
        result = drive.files().list(**arguments).execute()
        matches.extend(result.get('files', []))
        if len(matches) > 1:
            raise SyncError(
                'Có nhiều thư mục/tài liệu master trùng tên. Chọn ID trong tệp trạng thái trước khi tiếp tục.'
            )
        token = result.get('nextPageToken')
        if not token:
            return matches[0] if matches else None


def _file_info(drive, resource_id, mime):
    info = drive.files().get(fileId=resource_id, fields='id,name,mimeType,parents,trashed').execute()
    if info.get('trashed') or info.get('mimeType') != mime:
        raise SyncError('Master đã bị xóa hoặc ID trỏ sai loại tệp. Khôi phục master trước khi đồng bộ.')
    return info


def ensure_master(drive, docs):
    """Resolve one master, failing closed on unreadable configured resources.

    The caller holds ``export_lock(CONFIG)``. A pending move is persisted as soon
    as Docs creation returns, so a failed move resumes without creating a Doc.
    A unique global title lookup also recovers a creation whose response was lost.
    """
    state = _read_state()
    try:
        if state.get('folder_id'):
            _file_info(drive, state['folder_id'], FOLDER_MIME)
        else:
            folder = _unique_named(drive, FOLDER_NAME, FOLDER_MIME)
            if folder is None:
                if state.get('pending_folder_create'):
                    raise SyncError(
                        'Kết quả tạo thư mục trước chưa xác định. Kiểm tra Drive và ghi folder_id vào tệp trạng thái; không tạo thư mục thứ hai.'
                    )
                state['pending_folder_create'] = True
                _atomic_json(CONFIG, state)
                folder = (
                    drive.files()
                    .create(body={'name': FOLDER_NAME, 'mimeType': FOLDER_MIME}, fields='id')
                    .execute()
                )
            state['folder_id'] = folder['id']
            state.pop('pending_folder_create', None)
            _atomic_json(CONFIG, state)

        folder_id = state['folder_id']
        if not state.get('doc_id'):
            document = _unique_named(drive, DOCUMENT_NAME, DOCUMENT_MIME, folder_id)
            if document is None:
                document = _unique_named(drive, DOCUMENT_NAME, DOCUMENT_MIME)
            if document is None:
                if state.get('pending_create'):
                    raise SyncError(
                        'Kết quả tạo Google Doc trước chưa xác định. Kiểm tra Drive và ghi doc_id vào tệp trạng thái; không tạo master thứ hai.'
                    )
                state['pending_create'] = True
                _atomic_json(CONFIG, state)
                created = docs.documents().create(body={'title': DOCUMENT_NAME}).execute()
                document = {'id': created['documentId']}
            state['doc_id'] = document['id']
            state['pending_move'] = True
            state.pop('pending_create', None)
            _atomic_json(CONFIG, state)

        doc_id = state['doc_id']
        info = _file_info(drive, doc_id, DOCUMENT_MIME)
        parents = info.get('parents', [])
        if folder_id not in parents:
            state['pending_move'] = True
            _atomic_json(CONFIG, state)
            arguments = {'fileId': doc_id, 'addParents': folder_id, 'fields': 'id,parents'}
            previous = [parent for parent in parents if parent != folder_id]
            if previous:
                arguments['removeParents'] = ','.join(previous)
            drive.files().update(**arguments).execute()
        # Do not clear recovery state until the remote move is confirmed.
        final = _file_info(drive, doc_id, DOCUMENT_MIME)
        if folder_id not in final.get('parents', []):
            raise SyncError('Chưa xác nhận tài liệu nằm trong thư mục master.')
        docs.documents().get(documentId=doc_id, includeTabsContent=True).execute()
        state['pending_move'] = False
        _atomic_json(CONFIG, state)
        return doc_id
    except SyncError:
        raise
    except Exception:
        raise SyncError(
            'Không xác minh được Google master. Đã giữ trạng thái để thử lại; không tạo bản thay thế khi lỗi đọc hoặc mất kết nối.'
        ) from None


def _document_tabs(document):
    def walk(tabs):
        for tab in tabs or []:
            if 'documentTab' in tab:
                yield tab
            yield from walk(tab.get('childTabs', []))

    return list(walk(document.get('tabs', [])))


def _all_text(document):
    pieces = []

    def walk(contents):
        for part in contents or []:
            if 'paragraph' in part:
                for element in part['paragraph'].get('elements', []):
                    pieces.append(element.get('textRun', {}).get('content', ''))
            for row in part.get('table', {}).get('tableRows', []):
                for cell in row.get('tableCells', []):
                    walk(cell.get('content', []))
            if 'tableOfContents' in part:
                walk(part['tableOfContents'].get('content', []))

    walk(document.get('body', {}).get('content', []))
    for tab in _document_tabs(document):
        walk(tab['documentTab'].get('body', {}).get('content', []))
    return ''.join(pieces)


def _destination(document):
    tabs = _document_tabs(document)
    if tabs:
        tab = tabs[0]
        tab_id = tab.get('tabProperties', {}).get('tabId')
        body = tab['documentTab'].get('body', {})
        if not tab_id:
            raise SyncError('Không xác định được tab Google master.')
    else:
        tab_id, body = None, document.get('body', {})
    end = max((part.get('endIndex', 0) for part in body.get('content', [])), default=0)
    if end < 2:
        raise SyncError('Không xác định được vị trí nối bài trong master.')
    return tab_id, end - 1


def _utf16_length(value):
    return len(value.encode('utf-16-le')) // 2


def _append_requests(row, document, fingerprint):
    try:
        sources = json.loads(row['source_snapshot'])
        if not isinstance(sources, list) or not sources:
            raise ValueError
    except (KeyError, ValueError, TypeError):
        raise SyncError('Bài đã duyệt thiếu bản chụp chứng cứ; cần duyệt lại trước khi xuất.') from None
    tab_id, insertion = _destination(document)
    body = (
        f'\n\n[FRIC-ARTICLE-ID:{row["id"]}]\n[FRIC-CONTENT-HASH:{fingerprint}]\n'
        f'{row["title"]}\n{row["content"]}\n\n参考来源（审核时保存的证据）\n'
    )
    links = []
    for source in sources:
        stamp = source.get('published') if source.get('date_verified') else '原始发布日期待核实'
        body += f'{source["title"]} | {stamp}\n'
        start = insertion + _utf16_length(body)
        url = source['url']
        body += url + '\n'
        location = {'startIndex': start, 'endIndex': start + _utf16_length(url)}
        if tab_id:
            location['tabId'] = tab_id
        links.append(
            {'updateTextStyle': {'range': location, 'textStyle': {'link': {'url': url}}, 'fields': 'link'}}
        )
    end_location = {'tabId': tab_id} if tab_id else {}
    return [{'insertText': {'endOfSegmentLocation': end_location, 'text': body}}, *links]


def append_to_gdoc(aid):
    with export_lock(WORKSPACE / 'editorial'), export_lock(CONFIG):
        row = require_approved(aid)
        fingerprint = export_fingerprint(row)
        marker = f'[FRIC-ARTICLE-ID:{aid}]'
        content_marker = f'[FRIC-CONTENT-HASH:{fingerprint}]'
        drive, docs = clients()
        doc_id = ensure_master(drive, docs)
        url = 'https://docs.google.com/document/d/' + doc_id + '/edit'

        def read():
            return docs.documents().get(documentId=doc_id, includeTabsContent=True).execute()

        def contains(document):
            text = _all_text(document)
            return marker in text or content_marker in text

        try:
            document = read()
            if not contains(document):
                if row.get('gdoc_saved'):
                    raise SyncError(
                        'Cơ sở dữ liệu ghi đã đồng bộ nhưng master thiếu marker. Khôi phục đúng tài liệu trước khi thử lại; không tự nối vào master khác.'
                    )
                revision = document.get('revisionId')
                if not revision:
                    raise SyncError('Không có revision ID để nối bài an toàn; chưa xuất.')
                requests = _append_requests(row, document, fingerprint)
                try:
                    docs.documents().batchUpdate(
                        documentId=doc_id,
                        body={
                            'writeControl': {'requiredRevisionId': revision},
                            'requests': requests,
                        },
                    ).execute()
                except Exception:
                    # A timeout can mean the write succeeded. Reconcile; do not
                    # blindly retry a mutating request whose outcome is unknown.
                    if not contains(read()):
                        raise SyncError(
                            'Chưa xác nhận bài đã được nối. Thử lại để đối chiếu marker; chưa đánh dấu đã đồng bộ.'
                        ) from None
                else:
                    if not contains(read()):
                        raise SyncError('Google chưa xác nhận marker bài viết; chưa đánh dấu đã đồng bộ.')
            record_export(aid, 'gdoc', url)
            mark_gdoc_saved(aid)
            return url
        except SyncError:
            raise
        except Exception:
            raise SyncError(
                'Không xác nhận được kết quả Google. Thử lại để đối chiếu trước khi nối; trạng thái đã lưu được giữ nguyên.'
            ) from None
