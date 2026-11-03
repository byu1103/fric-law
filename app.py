"""Vietnamese editorial dashboard: discover, substantiate, review, append one master."""

from __future__ import annotations

import json
import os
import re
from time import perf_counter
from datetime import date, datetime
from zoneinfo import ZoneInfo

import streamlit as st

from access_control import require_access, remote_access_required
from ai_client import AIServiceError, check_ai_connection
from settings import (
    AIBOX_BASE_URL,
    get_ai_settings,
    get_key_status,
    load_startup_settings,
    reload_local_settings,
    save_ai_settings,
    save_api_keys,
)

load_startup_settings()
reload_local_settings()

from core import (  # noqa: E402
    CATEGORIES,
    DOMAINS,
    MASTER,
    TOPICS,
    WORKSPACE,
    append_master_docx,
    approval_requirements,
    approve_article,
    audit_text,
    claim_units,
    generate_article,
    get_approval_history,
    get_approvals,
    get_article,
    get_claim_reviews,
    get_revisions,
    get_sources,
    init,
    legal_missing,
    list_articles,
    official,
    review_claim,
    save_article,
    search_news,
    store_source,
    today_vn,
    update_source,
)
from research import (  # noqa: E402
    cluster_and_rank,
    default_date_range,
    domain_of,
    fetch_evidence,
    search_provider_status,
)

PAGES = ['🔎 Tìm tin', '📚 Thư viện nguồn', '✍️ Soạn & duyệt', '🗂️ Kho bài & xuất bản', '🗺️ Hình & bản đồ']
PRIORITY = [
    'vanban.chinhphu.vn',
    'congbao.chinhphu.vn',
    'chinhphu.vn',
    'baochinhphu.vn',
    'vbpl.vn',
    'vbpl.moj.gov.vn',
    'mof.gov.vn',
    'sbv.gov.vn',
    'thuvienphapluat.vn',
    'cafef.vn',
    'vnexpress.net',
    'vietnamplus.vn',
    'baodautu.vn',
]
LEGAL_LABELS = {
    'authority': 'Cơ quan ban hành',
    'document_number': 'Số hiệu văn bản',
    'article_section': 'Điều / khoản được dẫn',
    'issued': 'Ngày ban hành (YYYY-MM-DD)',
    'effective': 'Ngày hiệu lực (YYYY-MM-DD)',
    'amendment_status': 'Tình trạng sửa đổi / thay thế',
    'amendment_url': 'URL văn bản sửa đổi / nguồn kiểm tra hiệu lực',
}
SEARCH_PROVIDERS = {
    'Tự động (khuyến nghị)': 'auto',
    'Nguồn công khai · không cần khóa': 'public',
    'Tavily API': 'tavily',
}


def jump(page):
    st.session_state['_navigate'] = page
    st.rerun()


def json_value(value, fallback):
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value or '')
    except (TypeError, ValueError):
        return fallback


def date_label(source):
    if source.get('published') and source.get('date_verified'):
        return f'{source["published"]} · đã xác minh ngày đăng'
    return f'{source.get("published") or "Chưa rõ ngày"} · cần xác minh'


def flash(message):
    st.session_state['_flash'] = message


def error_text(exc):
    """Keep useful failures visible without echoing configured secret values."""
    message = str(exc)
    for name, value in os.environ.items():
        if (
            value
            and len(value) >= 6
            and any(token in name.upper() for token in ('KEY', 'SECRET', 'TOKEN', 'PASSWORD'))
        ):
            message = message.replace(value, '[đã ẩn khóa]')
    message = re.sub(r'\bsk-[A-Za-z0-9_-]{8,}', '[đã ẩn khóa]', message)
    return message


def new_draft():
    st.session_state['_new_draft'] = True
    jump(PAGES[2])


def use_topic_query(category):
    st.session_state['search_query'] = TOPICS[category]


def source_connection_details(diagnostics):
    """Show endpoint failures without labelling a partly readable publisher offline."""
    attempted = diagnostics.get('providers_attempted') or []
    succeeded = set(diagnostics.get('providers_succeeded') or [])
    failures = {
        item.get('url'): item
        for item in diagnostics.get('failed_sources', [])
        if isinstance(item, dict) and item.get('url')
    }
    if not attempted:
        return
    total_domains = diagnostics.get('attempted_domain_count', len({domain_of(u) for u in attempted}))
    readable_domains = diagnostics.get('successful_domain_count', len({domain_of(u) for u in succeeded}))
    st.caption(
        f'Đã đọc được {readable_domains}/{total_domains} tên miền · '
        f'{len(succeeded)}/{len(attempted)} RSS/mục tin. Nguồn lỗi không làm mất kết quả từ nguồn khác.'
    )
    with st.expander('Chi tiết kết nối từng nguồn'):
        rows = []
        for url in attempted:
            failure = failures.get(url, {})
            rows.append(
                {
                    'Nguồn': domain_of(url),
                    'Trạng thái': 'Đã đọc' if url in succeeded else 'Chưa đọc được',
                    'Chi tiết': ''
                    if url in succeeded
                    else error_text(failure.get('message') or 'Chưa có dữ liệu đọc được.'),
                    'RSS / mục tin': url,
                }
            )
        st.dataframe(rows, hide_index=True, use_container_width=True)
        st.caption(
            'Trang yêu cầu JavaScript hoặc chặn truy cập tự động có thể cần mở URL gốc. '
            'Bấm Tìm & xếp hạng tin để thử kết nối lại; ứng dụng không bỏ qua chặn truy cập hoặc tự xác nhận dữ kiện.'
        )


def search_page(sources):
    st.subheader('Tìm tín hiệu đầu tư đáng viết')
    st.write(
        'Từ thay đổi pháp luật đến dự án mới: chọn một chủ đề, đối chiếu nguồn gốc, rồi viết cho nhà đầu tư Trung Quốc.'
    )
    st.session_state.setdefault('search_category', CATEGORIES[1])
    category = st.pills('Chủ đề ưu tiên', CATEGORIES, key='search_category')
    category = category or CATEGORIES[1]
    # Changing a chip must not silently replace an editor's typed keywords.
    st.session_state.setdefault('search_query', TOPICS[category])
    query = st.text_input(
        'Bạn đang tìm thông tin gì?',
        value=None,
        key='search_query',
        placeholder='Ví dụ: vốn đầu tư Trung Quốc, M&A, tài khoản DICA, khu công nghiệp…',
    )
    st.button(
        'Dùng từ khóa gợi ý cho chủ đề đã chọn',
        on_click=use_topic_query,
        args=(category,),
        key='use_topic_query',
        help='Chỉ thay từ khóa khi bạn bấm nút này; giữ nguyên nội dung đã nhập khi đổi chủ đề.',
    )
    default_start, default_end = default_date_range()
    st.session_state.setdefault('search_start', default_start)
    st.session_state.setdefault('search_end', default_end)
    st.session_state.setdefault('search_sites', [d for d in PRIORITY if d in DOMAINS])
    left, right, settings = st.columns([1, 1, 2])
    start = left.date_input('Từ ngày', value=None, max_value=today_vn(), key='search_start')
    end = right.date_input('Đến ngày', value=None, max_value=today_vn(), key='search_end')
    with settings:
        sites = st.multiselect('Nguồn ưu tiên', DOMAINS, key='search_sites')
    st.caption(
        'Asia/Ho_Chi_Minh · 7 ngày lịch mặc định, bao gồm hôm nay. Chỉ ngày đăng gốc có chứng cứ mới được tính trong khoảng ngày; ngày sửa bài và ngày ban hành luật được tách riêng.'
    )
    st.session_state.setdefault('search_provider', next(iter(SEARCH_PROVIDERS)))
    provider_label = st.selectbox('Nguồn tìm kiếm', list(SEARCH_PROVIDERS), key='search_provider')
    provider = SEARCH_PROVIDERS[provider_label]
    tavily_ready = search_provider_status(provider)['tavily_configured']
    if provider == 'public' or (provider == 'auto' and not tavily_ready):
        st.info(
            'Tìm kiếm nguồn công khai đang sẵn sàng, không cần API key. '
            'Ứng dụng tìm tin theo từ khóa và nguồn đã chọn, sau đó mở bản gốc để kiểm tra ngày đăng. '
            'Một số cổng văn bản hoặc bài chặn truy cập có thể chưa được lập chỉ mục; thêm URL gốc khi cần.'
        )
    elif provider == 'tavily' and not tavily_ready:
        st.warning(
            'Chưa cấu hình Tavily API. Chọn Tự động hoặc Nguồn công khai để tìm ngay; '
            'Tavily là kết nối tùy chọn, cấu hình TAVILY_API_KEY trong tệp .env trên máy.'
        )
    else:
        st.caption(
            'Tavily đã được cấu hình. Chế độ Tự động có thể chuyển sang nguồn công khai khi dịch vụ gặp lỗi. '
            'Kết quả tìm kiếm vẫn cần kiểm tra nội dung và ngày trên trang gốc.'
        )
    if st.button('Tìm & xếp hạng tin', type='primary', use_container_width=True, key='run_search'):
        for key in ('search_clusters', 'search_window', 'search_context', 'search_diagnostics'):
            st.session_state.pop(key, None)
        st.session_state.pop('search_error', None)
        if not query or not query.strip():
            st.session_state['search_error'] = 'Nhập từ khóa tìm kiếm.'
        elif not isinstance(start, date) or not isinstance(end, date):
            st.session_state['search_error'] = 'Chọn đủ ngày bắt đầu và ngày kết thúc.'
        elif start > end:
            st.session_state['search_error'] = 'Ngày bắt đầu phải trước hoặc bằng ngày kết thúc.'
        elif not sites:
            st.session_state['search_error'] = 'Chọn ít nhất một nguồn ưu tiên.'
        else:
            started = perf_counter()
            with st.spinner('Đang tìm nguồn gốc, kiểm tra ngày và gom các tin cùng sự kiện…'):
                try:
                    hits = search_news(query, start, end, domains=sites, provider=provider)
                    st.session_state['search_clusters'] = cluster_and_rank(
                        hits, query=query, existing_urls={s['url'] for s in sources}
                    )
                    st.session_state['search_window'] = (str(start), str(end))
                    st.session_state['search_context'] = {
                        'category': category,
                        'query': query,
                        'sites': list(sites),
                        'provider': provider,
                    }
                    diagnostics = dict(getattr(hits, 'diagnostics', {}))
                    diagnostics.setdefault('candidate_count', len(hits))
                    diagnostics['elapsed'] = perf_counter() - started
                    st.session_state['search_diagnostics'] = diagnostics
                except Exception as exc:
                    st.session_state['search_error'] = (
                        f'Không thể hoàn tất tìm kiếm: {error_text(exc)}. '
                        'Bạn có thể bấm Tìm lại, đổi nguồn tìm kiếm hoặc thêm URL gốc bên dưới.'
                    )
    if st.session_state.get('search_error'):
        st.error(st.session_state['search_error'])
    clusters = st.session_state.get('search_clusters')
    if clusters is None:
        st.info(
            'Nhập từ khóa rồi bấm Tìm & xếp hạng tin. Có thể tìm bằng nguồn công khai ngay khi chưa có API key, '
            'hoặc thêm URL gốc bên dưới để đối chiếu thủ công.'
        )
    else:
        win = st.session_state.get('search_window', (str(start), str(end)))
        context = st.session_state.get('search_context', {})
        result_category = context.get('category', category)
        diagnostics = st.session_state.get('search_diagnostics', {})
        used_provider = {'public': 'Nguồn công khai', 'tavily': 'Tavily API'}.get(
            diagnostics.get('provider'), provider_label
        )
        st.caption(
            f'Kết quả của lần tìm: {win[0]} → {win[1]} · {used_provider} · '
            f'{context.get("query", query)}. Thay bộ lọc rồi bấm Tìm để cập nhật.'
        )
        if (
            context.get('query', query) != query
            or context.get('category', category) != category
            or context.get('sites', sites) != sites
            or context.get('provider', provider) != provider
            or win != (str(start), str(end))
        ):
            st.info('Bộ lọc đã thay đổi. Danh sách dưới đây vẫn thuộc lần tìm trước; bấm Tìm để cập nhật.')
        for warning in diagnostics.get('warnings', []):
            st.warning(error_text(warning))
        if diagnostics.get('coverage_note'):
            st.caption(error_text(diagnostics['coverage_note']))
        source_connection_details(diagnostics)
        valid = [h for h in clusters if h.get('date_status') == 'in_range']
        pending = [h for h in clusters if h.get('date_status') != 'in_range']
        a, b, c, d = st.columns(4)
        a.metric('Nguồn đã dò', diagnostics.get('candidate_count', len(clusters)))
        b.metric('Sự kiện trong khoảng ngày', len(valid))
        c.metric('Sự kiện cần xác minh / bối cảnh', len(pending))
        d.metric('Thời gian tìm', f'{diagnostics.get("elapsed", 0):.1f} giây')
        st.caption(
            'Xác minh ngày đăng không có nghĩa là các luận điểm hoặc hiệu lực pháp luật đã được duyệt.'
        )
        if not clusters:
            if diagnostics.get('failed_sources') and not diagnostics.get('providers_succeeded'):
                st.warning(
                    'Chưa truy cập được dữ liệu từ các nguồn đã chọn; chưa thể kết luận không có tin phù hợp. '
                    'Thử lại, thêm nguồn khác, bổ sung URL gốc để đối chiếu thủ công hoặc dùng Tavily nếu đã có khóa.'
                )
            else:
                empty_message = (
                    'Chưa tìm thấy trong phần nguồn công khai đọc được với từ khóa và bộ lọc hiện tại. '
                    if diagnostics.get('provider') == 'public'
                    else 'Không tìm thấy nguồn phù hợp với từ khóa và bộ lọc hiện tại. '
                )
                st.info(
                    empty_message
                    + 'Thử từ khóa ngắn hơn (ví dụ: đầu tư Trung Quốc), thêm nguồn hoặc điều chỉnh khoảng ngày. '
                    'Ứng dụng không tự nới khoảng ngày; bạn cũng có thể bổ sung URL gốc.'
                )
        if valid:
            st.markdown('#### Danh sách ưu tiên')
            st.caption(
                'Xếp theo tác động tới nhà đầu tư, độ mới và chất lượng nguồn; các bản tin trùng sự kiện được gom một nhóm.'
            )
            for i, hit in enumerate(valid[:5]):
                hit_card(hit, result_category, f'short_{i}')
            if len(valid) > 5:
                with st.expander(f'Xem thêm {len(valid) - 5} sự kiện trong khoảng ngày'):
                    for i, hit in enumerate(valid[5:]):
                        hit_card(hit, result_category, f'more_{i}')
        if pending:
            with st.expander(f'Cần xác minh ngày đăng / nguồn bối cảnh ({len(pending)})', expanded=not valid):
                st.warning('Những nguồn này chưa được tính là tin trong khoảng ngày đã chọn.')
                for i, hit in enumerate(pending):
                    hit_card(hit, result_category, f'pending_{i}')
    st.divider()
    with st.expander('＋ Thêm URL gốc vào thư viện', expanded=not sources):
        with st.form('add_source'):
            url = st.text_input('URL gốc', placeholder='https://vanban.chinhphu.vn/…')
            title = st.text_input('Tên nguồn', placeholder='Tiêu đề bản tin hoặc văn bản')
            submit = st.form_submit_button('Lưu URL')
        if submit:
            try:
                if not title.strip():
                    raise ValueError('Nhập tên nguồn để dễ đối chiếu.')
                sid = store_source({'url': url, 'title': title.strip()}, category)
                flash(f'Đã lưu nguồn {sid}. Mở Thư viện nguồn để bổ sung chứng cứ.')
                st.rerun()
            except Exception as exc:
                st.error(error_text(exc))


def hit_card(hit, category, key):
    with st.container(border=True):
        main, action = st.columns([5, 1])
        with main:
            st.markdown(f'**{hit.get("title") or "Nguồn chưa có tên"}**')
            status = (
                '✓ Trong khoảng ngày'
                if hit.get('date_status') == 'in_range'
                else '⚠ Cần xác minh ngày / chỉ làm bối cảnh'
            )
            kind = '🏛 Nguồn chính thức' if hit.get('official') else '📰 Nguồn báo chí'
            novelty = 'Đã có trong thư viện' if hit.get('novelty') == 'seen' else 'Nguồn mới'
            st.caption(f'{kind} · {hit.get("published") or "Chưa rõ ngày"} · {status} · {novelty}')
            st.write((hit.get('summary') or '')[:380])
            reasons = hit.get('impact_reasons') or hit.get('rationale') or []
            if reasons:
                st.caption('Ưu tiên: ' + ' · '.join(reasons))
            members = hit.get('members') or [hit]
            if len(members) > 1:
                st.caption(f'{len(members)} nguồn cùng sự kiện · một chủ đề cho mỗi bài')
            st.link_button('Mở nguồn gốc ↗', hit['url'])
            if len(members) > 1:
                with st.expander('Các nguồn đối chiếu cùng sự kiện'):
                    for member in members:
                        st.link_button(member.get('title') or member['url'], member['url'])
        with action:
            if st.button('Lưu nguồn', key=f'save_hit_{key}', use_container_width=True):
                try:
                    store_source(hit, category)
                    st.success('Đã lưu vào thư viện.')
                except Exception as exc:
                    st.error(error_text(exc))


def source_page(sources):
    st.subheader('Thư viện chứng cứ')
    st.caption(
        'Ngày đăng bản tin, ngày ban hành, ngày hiệu lực và tình trạng sửa đổi là bốn thông tin riêng. Văn bản AI tạo không phải chứng cứ.'
    )
    if not sources:
        st.info('Chưa có nguồn. Thêm một URL ở trang Tìm tin để bắt đầu.')
        return
    a, b, c = st.columns([2, 1, 1])
    term = a.text_input('Lọc tên / URL nguồn', key='source_filter')
    kind = b.selectbox('Loại nguồn', ['Tất cả', 'Nguồn chính thức', 'Báo chí'], key='source_kind_filter')
    date_filter = c.selectbox(
        'Ngày đăng', ['Tất cả', 'Cần xác minh', 'Đã xác minh'], key='source_date_filter'
    )
    filtered = [
        s
        for s in sources
        if term.lower() in (s['title'] + ' ' + s['url']).lower()
        and (kind == 'Tất cả' or official(s['url']) == (kind == 'Nguồn chính thức'))
        and (date_filter == 'Tất cả' or bool(s.get('date_verified')) == (date_filter == 'Đã xác minh'))
    ]
    st.caption(f'{len(filtered)} / {len(sources)} nguồn · hiển thị tối đa 60 nguồn phù hợp')
    if not filtered:
        st.info('Không có nguồn khớp bộ lọc.')
    for source in filtered[:60]:
        source_editor(source)


def source_editor(source):
    sid = source['id']
    prefix = f'source_{sid}_'
    with st.expander(
        f'{"🏛" if official(source["url"]) else "📰"} {source["title"][:110]} · {date_label(source)}'
    ):
        st.link_button('Mở bản gốc để đối chiếu ↗', source['url'])
        st.caption(source['url'])
        if st.button('Trích xuất nội dung và dấu ngày gốc', key=f'fetch_{sid}'):
            try:
                with st.spinner('Đang đọc trang gốc…'):
                    evidence = fetch_evidence(source['url'])
                    if evidence.get('extraction_error'):
                        st.warning(evidence['extraction_error'])
                    update_source(
                        sid,
                        text=evidence.get('text') or '',
                        published=evidence.get('published') or '',
                        date_evidence=json.dumps(evidence.get('date_evidence'), ensure_ascii=False)
                        if evidence.get('date_evidence')
                        else '',
                        date_verified=int(bool(evidence.get('date_verified'))),
                    )
                for key in list(st.session_state):
                    if key.startswith(prefix):
                        del st.session_state[key]
                flash(
                    'Đã trích xuất. Hãy đối chiếu văn bản và bằng chứng ngày đăng với trang gốc; cần người duyệt từng luận điểm.'
                )
                st.rerun()
            except Exception as exc:
                st.warning(
                    f'Không thể trích xuất: {error_text(exc)}. Với PDF/trang chặn truy cập, đọc bản gốc và dán đoạn liên quan bên dưới.'
                )
        legal = json_value(source.get('legal_json'), {})
        date_proof = source.get('date_evidence') or ''
        if isinstance(date_proof, dict):
            date_proof = json.dumps(date_proof, ensure_ascii=False)
        with st.form(f'edit_source_{sid}'):
            left, right = st.columns(2)
            published = left.text_input(
                'Ngày đăng gốc (YYYY-MM-DD)', value=source.get('published') or '', key=prefix + 'published'
            )
            reviewer = right.text_input(
                'Người đối chiếu nguồn', value=source.get('verified_by') or '', key=prefix + 'reviewer'
            )
            proof = st.text_area(
                'Bằng chứng ngày đăng gốc (trích dấu ngày / metadata; không dùng ngày cập nhật)',
                value=date_proof,
                key=prefix + 'date_evidence',
                height=80,
            )
            date_verified = st.checkbox(
                'Tôi đã đối chiếu ngày đăng gốc với bằng chứng trên',
                value=bool(source.get('date_verified')),
                key=prefix + 'date_verified',
            )
            text = st.text_area(
                'Văn bản nguồn (nguyên văn; dùng để đối chiếu trích dẫn)',
                value=source.get('text') or '',
                height=230,
                key=prefix + 'text',
            )
            source_kind = st.selectbox(
                'Phân loại tài liệu',
                ['news', 'legal'],
                index=1 if source.get('source_kind') == 'legal' else 0,
                format_func=lambda item: (
                    'Văn bản pháp luật / hồ sơ pháp lý' if item == 'legal' else 'Bản tin / tài liệu bối cảnh'
                ),
                key=prefix + 'kind',
            )
            st.markdown('**Thông tin pháp lý** · để trống nếu chưa có chứng cứ; không tự suy đoán hiệu lực.')
            legal_columns = st.columns(2)
            values = {}
            for i, (field, label) in enumerate(LEGAL_LABELS.items()):
                values[field] = legal_columns[i % 2].text_input(
                    label, value=str(legal.get(field) or ''), key=prefix + field
                )
            submitted = st.form_submit_button('Lưu chứng cứ & thông tin pháp lý', type='primary')
        if submitted:
            try:
                if published:
                    date.fromisoformat(published)
                if date_verified and (not published or not proof.strip() or not reviewer.strip()):
                    raise ValueError('Xác minh ngày cần đủ ngày đăng, bằng chứng và tên người đối chiếu.')
                update_source(
                    sid,
                    text=text,
                    published=published,
                    date_evidence=proof,
                    date_verified=int(date_verified),
                    verified_by=reviewer.strip(),
                    source_kind=source_kind,
                    legal_json=json.dumps(values, ensure_ascii=False),
                )
                flash('Đã lưu chứng cứ. Thay đổi chứng cứ sẽ yêu cầu duyệt lại các bài liên quan.')
                st.rerun()
            except Exception as exc:
                st.error(error_text(exc))
        if source.get('source_kind') == 'legal':
            missing = legal_missing(source)
            if missing:
                st.warning(
                    'Thông tin pháp lý còn thiếu: ' + ', '.join(LEGAL_LABELS.get(x, x) for x in missing)
                )


def ai_failure_state(exc, config):
    """Persist only display-safe failure metadata for this exact configuration."""
    status = getattr(exc, 'status_code', None)
    request_id = getattr(exc, 'request_id', None)
    if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,160}', request_id):
        request_id = None
    return {
        'revision': config['revision'],
        'model': config['model'],
        'message': error_text(exc),
        'code': exc.code,
        'status_code': status if isinstance(status, int) and 100 <= status <= 599 else None,
        'request_id': error_text(request_id) if request_id else None,
        'checked_at': datetime.now(ZoneInfo('Asia/Ho_Chi_Minh')).isoformat(timespec='seconds'),
    }


def show_ai_result_time(result):
    """A rerender shows the saved result, without implying a new provider check."""
    try:
        checked = datetime.fromisoformat(result.get('checked_at', ''))
        if checked.tzinfo is None:
            raise ValueError('Missing timezone')
        label = checked.astimezone(ZoneInfo('Asia/Ho_Chi_Minh')).strftime('%d/%m/%Y %H:%M:%S')
    except (TypeError, ValueError):
        st.caption('Kết quả đã lưu trong phiên chưa có thời điểm. Bấm Kiểm tra kết nối AI để kiểm tra mới.')
    else:
        st.caption(
            f'Phản hồi gần nhất: {label} · Asia/Ho_Chi_Minh. Hiển thị lại trang không gửi yêu cầu AI mới.'
        )


def ai_support_report(failure):
    """Export only known diagnostics, never provider bodies or editorial content."""
    model = failure.get('model')
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}', model):
        model = '(cần kiểm tra tên model)'
    code = 'model_unavailable' if failure.get('code') == 'model_unavailable' else 'service_error'
    status = failure.get('status_code')
    if not isinstance(status, int) or not 100 <= status <= 599:
        status = '(chưa rõ)'
    request_id = failure.get('request_id')
    if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,160}', request_id):
        request_id = '(chưa có)'
    return error_text(
        'Nhờ AI Box kiểm tra kênh hoạt động và quyền model cho nhóm của API key.\n'
        f'Endpoint: {AIBOX_BASE_URL}/chat/completions\n'
        f'Model: {model}\n'
        f'HTTP: {status}\n'
        f'Mã lỗi ứng dụng: {code}\n'
        f'Mã yêu cầu: {request_id}'
    )


def show_ai_failure(failure):
    st.error(failure['message'])
    show_ai_result_time(failure)
    if failure.get('code') == 'model_unavailable':
        st.caption(
            'AI Box cần mở kênh phục vụ model cho nhóm/tài khoản này. '
            'Tạo khóa mới trong cùng nhóm chưa chắc khắc phục được.'
        )
        st.markdown(
            '1. Mở [API Keys AI Box](https://home.ai-box.vn/console/token), kiểm tra **nhóm của khóa** '
            'và quyền model.\n'
            '2. Chỉ chọn nhóm/model được cấp phép và có kênh hoạt động; sau khi cập nhật, '
            'bấm **Kiểm tra kết nối AI**. Danh sách model đọc được chưa chứng minh sinh văn bản hoạt động.'
        )
        with st.expander('Thông tin kỹ thuật để sao chép'):
            st.code(ai_support_report(failure), language=None)
            st.caption('Chỉ chuẩn bị thông tin; ứng dụng chưa gửi tới AI Box.')
    details = [f'Model: {failure["model"]}'] if failure.get('model') else []
    if failure.get('status_code'):
        details.append(f'HTTP {failure["status_code"]}')
    if details:
        st.caption(' · '.join(details))
    if failure.get('request_id') and failure.get('code') != 'model_unavailable':
        st.caption('Mã yêu cầu để trao đổi với hỗ trợ AI Box:')
        st.code(failure['request_id'], language=None)


def ai_connection_panel():
    """Expose connection state without treating a stored key as a verified service."""
    config = get_ai_settings()
    shared = remote_access_required()
    checked = st.session_state.get('_ai_check', {})
    if checked.get('revision') != config['revision']:
        checked = {}
        st.session_state.pop('_ai_check', None)
    generation_error = st.session_state.get('_ai_generation_error', {})
    if generation_error.get('revision') != config['revision']:
        generation_error = {}
        st.session_state.pop('_ai_generation_error', None)
    with st.expander(
        'Kết nối AI Box',
        expanded=not config['configured'] or checked.get('ok') is False or bool(generation_error),
    ):
        if not config['configured']:
            st.info(
                'Chưa có khóa AI Box API. Tạo khóa để bật AI soạn thảo; bạn vẫn có thể viết, '
                'dán, lưu và duyệt bản thảo tiếng Trung bên dưới.'
            )
        elif generation_error:
            show_ai_failure(generation_error)
        elif checked.get('ok'):
            st.success(f'Đã kiểm tra kết nối thành công · {config["model"]}.')
            show_ai_result_time(checked)
            st.caption('Kết quả thuộc cấu hình hiện tại; từng lần soạn vẫn có thể gặp lỗi mạng hoặc hạn mức.')
        elif checked.get('ok') is False:
            show_ai_failure(checked)
        else:
            st.info(f'Đã lưu cấu hình · {config["model"]} · chưa kiểm tra kết nối.')
        if not config['configured']:
            st.markdown(
                '1. Đăng nhập [AI Box](https://home.ai-box.vn/console/token), mở **API Keys** và tạo khóa mới.\n'
                '2. Kiểm tra số dư, hạn mức và tên model khả dụng trong tài khoản AI Box.\n'
                '3. Lưu khóa bằng ô mật khẩu trên máy quản trị hoặc công cụ cấu hình trên Mac. '
                'Không gửi khóa qua chat hoặc bản thảo.'
            )
        st.caption(
            'AI soạn thảo trên website chỉ gọi AI Box. Cấu hình này không thay đổi cấu hình hoặc hạn mức '
            'ChatGPT/Codex trong cuộc trò chuyện của bạn.'
        )
        st.caption('Endpoint cố định · Chat Completions · tương thích OpenAI SDK')
        st.code(config['base_url'], language=None)
        if shared:
            st.caption(
                'Bạn đang dùng khu vực biên tập qua link chia sẻ. Quản trị viên cần chạy '
                'setup_ai.py trên Mac/máy chủ để nhập khóa; link này không cho thay đổi khóa hoặc model.'
            )
        else:
            st.caption(
                'Chỉ nhập trên máy quản trị. Khóa được lưu cục bộ trong .env và không được điền lại vào giao diện.'
            )
            if (
                st.session_state.get('_ai_form_revision') != config['revision']
                or 'ai_model' not in st.session_state
            ):
                st.session_state['ai_model'] = config['model']
                st.session_state['_ai_form_revision'] = config['revision']
            with st.form('ai_connection_settings', clear_on_submit=True):
                provider_idx = 0 if config['provider'] == 'gemini' else 1
                provider_sel = st.radio(
                    'Chọn nhà cung cấp AI',
                    ['Google Gemini (Miễn phí - Khuyên dùng)', 'AI Box'],
                    index=provider_idx,
                    horizontal=True,
                    key='ai_provider_sel',
                )
                is_gemini = 'Gemini' in provider_sel
                key = st.text_input('Khóa API mới (Google Gemini hoặc AI Box)', type='password', key='ai_aibox_key')
                model = st.text_input('Model AI', key='ai_model')
                st.caption(
                    '• Google Gemini: Lấy khóa miễn phí tại [aistudio.google.com](https://aistudio.google.com/apikey) (Model: gemini-3.5-flash hoặc gemini-3.5-flash-lite).\n'
                    '• AI Box: Quản lý khóa tại [home.ai-box.vn](https://home.ai-box.vn/console/token) (Model: qwen3.8-max-0902, deepseek-v4.1-flash, v.v.).'
                )
                save = st.form_submit_button('Lưu kết nối AI', type='primary')
            if save:
                try:
                    raw_key = key.strip()
                    if raw_key.startswith('AIza') or (is_gemini and not raw_key.startswith('sk-')):
                        saved_config = save_ai_settings(gemini_key=raw_key or None, model=model, provider='gemini')
                    else:
                        saved_config = save_ai_settings(aibox_key=raw_key or None, model=model, provider='aibox')
                    st.session_state['_ai_settings_notice'] = (
                        'Đã lưu cấu hình AI. Bấm Kiểm tra kết nối AI; không cần khởi động lại.'
                        if saved_config['configured']
                        else 'Đã lưu model. Cần thêm khóa API để kết nối và soạn bài.'
                    )
                    st.session_state.pop('_ai_check', None)
                except Exception as exc:
                    st.session_state['_ai_settings_error'] = error_text(exc)
                st.session_state['_clear_ai_inputs'] = True
                st.rerun()
        if '_ai_settings_notice' in st.session_state:
            st.success(st.session_state.pop('_ai_settings_notice'))
        if '_ai_settings_error' in st.session_state:
            st.error(st.session_state.pop('_ai_settings_error'))
        refresh, probe = st.columns(2)
        if refresh.button('Đọc lại cấu hình AI', key='reload_ai_settings', use_container_width=True):
            reload_local_settings()
            st.rerun()
        st.caption(
            'Kiểm tra kết nối gửi một yêu cầu API nhỏ có thể phát sinh phí; không gửi nguồn hoặc bản thảo.'
        )
        if probe.button(
            'Kiểm tra kết nối AI',
            key='check_ai_connection',
            disabled=not config['configured'],
            use_container_width=True,
        ):
            with st.spinner('Đang kiểm tra kết nối AI Box…'):
                try:
                    check_ai_connection(model=config['model'])
                    result = {'ok': True}
                except AIServiceError as exc:
                    result = {'ok': False, **ai_failure_state(exc, config)}
                except Exception:
                    result = {
                        'ok': False,
                        'message': 'Không kiểm tra được kết nối AI. Kiểm tra cấu hình và thử lại.',
                    }
                st.session_state['_ai_check'] = {
                    'revision': config['revision'],
                    **result,
                    'checked_at': datetime.now(ZoneInfo('Asia/Ho_Chi_Minh')).isoformat(timespec='seconds'),
                }
                st.session_state.pop('_ai_generation_error', None)
            st.rerun()
    return config


def writer_page(sources):
    st.subheader('Soạn tiếng Trung, duyệt bằng chứng')
    st.caption(
        'Một bài, một chủ đề. Mọi luận điểm thực chứng cần trích nguồn, đối chiếu nguyên văn và được luật sư + biên tập viên duyệt trước khi xuất.'
    )
    if st.button('＋ Tạo bản nháp mới', key='new_draft'):
        new_draft()
    names = {s['id']: f'{s["title"][:80]} · {"官方" if official(s["url"]) else "媒体"}' for s in sources}
    # Sources may have been removed outside the UI between runs.
    if 'selected_src' in st.session_state:
        st.session_state['selected_src'] = [sid for sid in st.session_state['selected_src'] if sid in names]
    ids = st.multiselect(
        'Nguồn cho bài này · thứ tự tương ứng [S1], [S2]…',
        list(names),
        format_func=names.get,
        key='selected_src',
    )
    selected = get_sources(ids)
    category = st.selectbox('Chuyên mục bài viết', CATEGORIES, index=None, key='write_category')
    with st.expander('Chỉ dẫn cho AI và mức sẵn sàng của nguồn'):
        custom = st.text_area(
            'Ghi chú biên tập (tùy chọn)',
            value=None,
            key='draft_notes',
            placeholder='Ví dụ: giải thích tác động tới nhà sản xuất Trung Quốc, tập trung một quy định mới.',
            height=90,
        )
        for i, source in enumerate(selected, 1):
            st.caption(f'[S{i}] {source["title"]} · {date_label(source)}')
            if len(source.get('text') or '') < 240:
                st.warning(f'[S{i}] Chưa đủ văn bản nguồn; bổ sung trong Thư viện chứng cứ.')
            if source.get('source_kind') == 'legal' and legal_missing(source):
                st.warning(f'[S{i}] Thiếu thông tin pháp lý: {", ".join(legal_missing(source))}')
        client_confirmation = st.text_area(
            'Hồ sơ khách hàng xác nhận FRIC LAW tham gia dự án (nếu bài có tuyên bố này)',
            value=None,
            key='client_confirmation',
            height=80,
            placeholder='Chỉ điền khi có xác nhận thực tế: người xác nhận, ngày và mã hồ sơ/vị trí lưu chứng cứ. Không nhập dữ liệu mật.',
        )
    config = ai_connection_panel()
    readiness = []
    if not selected:
        readiness.append('Chọn ít nhất một nguồn cho bài viết.')
    if category not in CATEGORIES:
        readiness.append('Chọn chuyên mục bài viết.')
    for i, source in enumerate(selected, 1):
        if len(source.get('text') or '') < 240:
            readiness.append(f'[S{i}] Cần ít nhất 240 ký tự văn bản nguồn; bổ sung trong Thư viện nguồn.')
    if (
        category in (CATEGORIES[0], CATEGORIES[3], CATEGORIES[5])
        and selected
        and not any(official(source['url']) for source in selected)
    ):
        readiness.append('Chuyên mục pháp lý cần ít nhất một nguồn chính thức từ cơ quan nhà nước.')
    for issue in readiness:
        st.warning(issue)
    if config['configured'] and not readiness:
        st.caption('Nguồn đã đủ điều kiện để yêu cầu AI soạn nháp; điều này chưa xác minh nội dung nguồn.')
    st.caption(
        'Khi bấm AI soạn bài tiếng Trung, nội dung nguồn đã chọn và ghi chú biên tập sẽ được gửi '
        'tới AI Box để tạo bản nháp. Chỉ chọn tài liệu bạn được phép gửi.'
    )
    if st.button(
        'AI soạn bài tiếng Trung',
        type='primary',
        disabled=not config['configured'] or bool(readiness),
        key='generate_draft',
    ):
        with st.spinner('Đang viết theo STYLE_GUIDE và các nguồn đã chọn…'):
            try:
                content = generate_article(category, selected, custom)
                st.session_state['draft_content'] = content
                st.session_state['draft_title'] = next(
                    (line.lstrip('# ').strip() for line in content.splitlines() if line.strip()), ''
                )
                st.session_state.pop('_ai_generation_error', None)
                # A successful draft is a more recent service result than a failed probe.
                st.session_state.pop('_ai_check', None)
                flash(
                    'AI đã tạo bản nháp. Nội dung này chưa được xác minh độc lập; cần đối chiếu từng luận điểm.'
                )
                st.rerun()
            except AIServiceError as exc:
                st.session_state['_ai_generation_error'] = ai_failure_state(exc, config)
                st.session_state.pop('_ai_check', None)
                st.rerun()
            except Exception as exc:
                st.error(error_text(exc))
    if st.session_state.get('_ai_generation_error'):
        st.caption(
            'Lần soạn AI chưa hoàn tất. Bản thảo và nguồn đã chọn được giữ nguyên; bạn vẫn có thể '
            'viết hoặc dán nội dung, lưu bản nháp, đối chiếu và phê duyệt theo quy trình bên dưới.'
        )
    title = st.text_input(
        'Tiêu đề tiếng Trung',
        value=None,
        key='draft_title',
        placeholder='Tiêu đề rõ thay đổi và tác động tới nhà đầu tư',
    )
    content = st.text_area(
        'Nội dung bản thảo (简体中文)',
        value=None,
        key='draft_content',
        height=440,
        placeholder='Dán bài tự viết hoặc dùng AI sau khi bổ sung chứng cứ. Dẫn [S1] ngay sau luận điểm, và URL gốc ở 参考来源.',
    )
    aid = st.session_state.get('editing_article_id')
    saved = get_article(aid) if aid else None
    dirty = not saved or any(
        (
            saved['title'] != title,
            saved['content'] != content,
            saved['category'] != category,
            json_value(saved['source_ids'], []) != ids,
            json_value(saved.get('source_snapshot'), []) != selected,
            (saved.get('client_confirmation') or '') != client_confirmation,
        )
    )
    if content.strip():
        issues = audit_text(content, selected)
        if issues:
            with st.expander(f'Kiểm tra sơ bộ: {len(issues)} điểm cần xử lý', expanded=True):
                for issue in issues:
                    st.warning(issue)
        else:
            st.info('Kiểm tra cấu trúc sơ bộ đạt. Kết quả tự động không chứng minh tính đúng của nội dung.')
    if st.button('Lưu bản nháp / phiên bản mới', use_container_width=True, key='save_draft'):
        try:
            if not title.strip() or not content.strip() or not selected:
                raise ValueError('Cần tiêu đề, nội dung và ít nhất một nguồn.')
            if category not in CATEGORIES:
                raise ValueError('Chọn chuyên mục bài viết.')
            article_id = save_article(
                title.strip(),
                category,
                content,
                ids,
                existing_id=aid,
                client_confirmation=client_confirmation,
            )
            st.session_state['editing_article_id'] = article_id
            flash(f'Đã lưu bản nháp {article_id}. Có thể đối chiếu luận điểm ở bên dưới.')
            st.rerun()
        except Exception as exc:
            st.error(error_text(exc))
    st.divider()
    st.markdown('#### Đối chiếu luận điểm & phê duyệt')
    if not saved:
        st.info(
            'Lưu bản nháp trước khi đối chiếu và duyệt. Mọi lần lưu thay đổi nội dung sẽ hủy phê duyệt cũ.'
        )
        return
    if saved['docx_saved'] or saved['gdoc_saved']:
        st.success(
            'Bài này đã vào tài liệu tổng hợp và lịch sử được giữ nguyên. Mở Kho bài để tải MASTER hoặc tạo bản sửa mới.'
        )
        return
    if dirty:
        st.warning(
            'Nội dung hoặc chứng cứ có thay đổi chưa được lưu thành phiên bản. Lưu trước khi đối chiếu, phê duyệt hoặc xuất Word.'
        )
        return
    st.caption(
        f'Bản đã lưu: {aid} · {len(get_revisions(aid))} phiên bản · mọi duyệt gắn với đúng nội dung và chứng cứ này'
    )
    claims = claim_units(saved['content'], selected)
    reviews = get_claim_reviews(aid)
    supported = sum(bool(reviews.get(claim['id'])) for claim in claims)
    st.progress(
        supported / len(claims) if claims else 0,
        text=f'{supported}/{len(claims)} luận điểm đã được người đối chiếu ghi nhận',
    )
    for index, claim in enumerate(claims, 1):
        review_key = f'{aid}_{saved["content_hash"][:12]}_{claim["id"]}'
        review = reviews.get(claim['id'])
        if review and review.get('disposition') == 'analysis':
            badge = '💬 Phân tích / khuyến nghị đã duyệt'
        elif review and review.get('official'):
            badge = '🏛 Có nguồn chính thức · người duyệt đã đối chiếu'
        elif review:
            badge = '📰 Có nguồn báo chí · người duyệt đã đối chiếu'
        else:
            badge = '⚠ Chưa xác minh'
        with st.expander(f'{index}. {badge} · {claim["text"][:105]}', expanded=not review and index == 1):
            st.write(claim['text'])
            if claim.get('legal'):
                st.caption(
                    'Luận điểm pháp lý: cần nguồn chính thức, điều/khoản và tình trạng hiệu lực đầy đủ.'
                )
            if review:
                st.caption(f'Người đối chiếu: {review.get("reviewer", "")} · {review.get("disposition", "")}')
                if review.get('excerpt'):
                    st.code(review['excerpt'], language=None)
            with st.form(f'review_{review_key}'):
                disposition_label = st.selectbox(
                    'Cách xử lý luận điểm',
                    ['Thực chứng: nguồn hỗ trợ', 'Phân tích / khuyến nghị thuần túy'],
                    key=f'disposition_{review_key}',
                )
                claim_sources = [source for source in selected if source['id'] in claim.get('source_ids', [])]
                options = [source['id'] for source in claim_sources]
                picked = st.selectbox(
                    'Nguồn được trích dẫn trong luận điểm',
                    options,
                    format_func=names.get,
                    index=0 if options else None,
                    key=f'claim_source_{review_key}',
                )
                if picked:
                    with st.expander('Đọc văn bản đã lưu của nguồn'):
                        source = next(source for source in selected if source['id'] == picked)
                        st.text((source.get('text') or '')[:20000])
                excerpt = st.text_area(
                    'Trích nguyên văn đúng đoạn chứng minh luận điểm (giữ ngôn ngữ gốc)',
                    value=review.get('excerpt', '') if review else '',
                    height=100,
                    key=f'excerpt_{review_key}',
                )
                reviewer = st.text_input(
                    'Họ tên người đối chiếu',
                    value=review.get('reviewer', '') if review else '',
                    key=f'reviewer_{review_key}',
                )
                attested = st.checkbox(
                    'Tôi đã kiểm tra đoạn nguồn thực sự hỗ trợ luận điểm; không chỉ kiểm tra có URL',
                    key=f'attest_{review_key}',
                )
                submitted = st.form_submit_button('Ghi nhận đối chiếu')
            if submitted:
                try:
                    if not attested:
                        raise ValueError('Cần xác nhận đã đối chiếu nội dung của luận điểm.')
                    disposition = 'analysis' if disposition_label.startswith('Phân tích') else 'supported'
                    review_claim(aid, claim['id'], picked or '', excerpt, reviewer, disposition=disposition)
                    flash('Đã lưu kết quả đối chiếu luận điểm.')
                    st.rerun()
                except Exception as exc:
                    st.error(error_text(exc))
    blockers = approval_requirements(aid)
    with st.expander('Điều kiện phê duyệt & xuất tài liệu', expanded=bool(blockers)):
        if blockers:
            for blocker in blockers:
                st.warning(blocker)
        else:
            st.success('Chứng cứ và nội dung đã sẵn sàng cho bước duyệt.')
        for approval in get_approvals(aid):
            role = 'Luật sư' if approval['role'] == 'lawyer' else 'Biên tập viên'
            st.caption(f'✓ {role}: {approval["reviewer"]} · {approval.get("created", "")}')
        with st.form(f'approve_{aid}_{saved["content_hash"][:12]}'):
            reviewer = st.text_input('Họ tên người phê duyệt', key='approval_reviewer')
            role = st.selectbox(
                'Vai trò phê duyệt',
                ['lawyer', 'editor'],
                format_func=lambda role: 'Luật sư' if role == 'lawyer' else 'Biên tập viên',
            )
            confirm = st.checkbox(
                'Tôi đã kiểm tra pháp luật hiện hành, các sửa đổi, nguồn và toàn bộ nội dung; bài chỉ có một chủ đề và tôi đồng ý xuất phiên bản này.',
                key=f'approval_attestation_{aid}_{saved["content_hash"][:12]}',
            )
            approve = st.form_submit_button('Phê duyệt phiên bản đã lưu', type='primary')
        if approve:
            try:
                if not confirm:
                    raise ValueError('Cần xác nhận kiểm tra toàn bộ nội dung trước khi phê duyệt.')
                approve_article(aid, reviewer, role)
                flash('Đã ghi nhận phê duyệt. Cần đủ cả vai trò luật sư và biên tập viên để xuất.')
                st.rerun()
            except Exception as exc:
                st.error(error_text(exc))
    roles = {approval['role'] for approval in get_approvals(aid)}
    can_export = not blockers and {'lawyer', 'editor'} <= roles
    if st.button(
        'Nối bài đã duyệt vào Word MASTER',
        type='primary',
        disabled=not can_export,
        use_container_width=True,
        key='export_master',
    ):
        try:
            path, added = append_master_docx(aid)
            flash(('Đã nối bài vào ' if added else 'Bài đã có trong ') + str(path))
            st.rerun()
        except Exception as exc:
            st.error(error_text(exc))


def library_page(articles):
    st.subheader('Kho bài & một tài liệu tổng hợp')
    st.caption(
        'Mỗi bài duy nhất chỉ nối vào tài liệu tổng hợp sau khi đủ phê duyệt. Bài đã xuất được lưu nguyên trạng; chỉnh sửa tiếp bằng bản nháp mới.'
    )
    st.code(str(MASTER), language=None)
    if MASTER.exists():
        st.download_button(
            'Tải Word MASTER hiện tại',
            MASTER.read_bytes(),
            file_name=MASTER.name,
            mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )
    if not articles:
        st.info('Chưa có bài đã lưu. Chọn nguồn và lưu bản thảo tại Soạn & duyệt.')
    else:
        left, right = st.columns([2, 1])
        term = left.text_input('Lọc tiêu đề bài', key='article_filter')
        status = right.selectbox(
            'Trạng thái bài',
            ['Tất cả', 'Đang soạn / chờ duyệt', 'Đã duyệt', 'Đã vào Word'],
            key='article_status_filter',
        )
        filtered = [
            article
            for article in articles
            if term.lower() in article['title'].lower()
            and (
                status == 'Tất cả'
                or (status == 'Đã vào Word' and article['docx_saved'])
                or (status == 'Đã duyệt' and article['status'] == 'approved')
                or (
                    status == 'Đang soạn / chờ duyệt'
                    and article['status'] != 'approved'
                    and not article['docx_saved']
                )
            )
        ]
        if not filtered:
            st.info('Không có bài khớp bộ lọc.')
        for article in filtered:
            with st.container(border=True):
                left, right = st.columns([4, 1])
                with left:
                    st.markdown(f'**{article["title"]}**')
                    st.caption(
                        f'{article["created"][:16]} · {article["category"]} · {article["status"]} · Word {"✓" if article["docx_saved"] else "—"} · Google Docs {"✓" if article["gdoc_saved"] else "—"}'
                    )
                    with st.expander('Xem bản đã lưu & lịch sử phiên bản'):
                        st.text(article['content'])
                        for event in get_approval_history(article['id']):
                            st.caption(
                                f'{event["event"]} · {event["role"]} · {event["reviewer"]} · {event["created"]} · {event["reason"]}'
                            )
                        for revision in get_revisions(article['id']):
                            st.caption(
                                f'Phiên bản {revision.get("revision", revision.get("id", ""))} · {revision.get("created", "")}'
                            )
                            with st.expander(
                                'Nội dung phiên bản ' + str(revision.get('revision', revision.get('id', '')))
                            ):
                                st.text(revision.get('content', ''))
                with right:
                    if not article['docx_saved'] and not article['gdoc_saved']:
                        if st.button('Mở bản nháp', key='edit_' + article['id'], use_container_width=True):
                            st.session_state['_load_draft'] = dict(article)
                            jump(PAGES[2])
                    else:
                        if st.button(
                            'Tạo bản sửa mới', key='copy_' + article['id'], use_container_width=True
                        ):
                            copy = dict(article)
                            copy['id'] = None
                            st.session_state['_load_draft'] = copy
                            jump(PAGES[2])
                    if article['status'] == 'approved' and not article['gdoc_saved']:
                        if st.button('Nối Google Doc', key='gdoc_' + article['id'], use_container_width=True):
                            try:
                                with st.spinner('Đang nối vào một Google Doc tổng hợp…'):
                                    from google_docs_sync import append_to_gdoc

                                    url = append_to_gdoc(article['id'])
                                st.success('Đã đồng bộ vào Google Doc tổng hợp.')
                                st.link_button('Mở Google Doc ↗', url)
                            except Exception as exc:
                                st.error(error_text(exc))
    with st.expander('Google Docs tùy chọn · thiết lập OAuth'):
        st.markdown("""1. Bật Google Docs API và Google Drive API trong Google Cloud; tạo OAuth client loại Desktop.
2. Lưu JSON vào `google_oauth_client.json` trong thư mục làm việc hiển thị ở thanh bên. Không đưa secrets hay token vào Git.
3. Bấm **Nối Google Doc** trên bài đã được duyệt. Cửa sổ trình duyệt sẽ yêu cầu đăng nhập và cấp quyền.
4. Ứng dụng nối vào **một Google Doc trong một thư mục Drive**, kiểm tra trùng trước khi nối lại sau lỗi.

Word MASTER hoạt động độc lập với Google. Không có chức năng đăng tự động lên WeChat.""")


def visual_page():
    st.subheader('Hình dữ kiện & bản đồ có nguồn')
    st.info(
        'Bản đồ chỉ dùng tọa độ đáng tin cậy do người dùng cung cấp. Hình dữ kiện phải được đối chiếu trước khi tạo.'
    )
    with st.expander('Bản đồ cho một dự án có tên', expanded=True):
        with st.form('map_form'):
            name = st.text_input('Tên dự án / địa điểm (中文)', key='map_name')
            left, right = st.columns(2)
            lat = left.text_input('Vĩ độ đã xác minh', placeholder='Ví dụ: 21.123456', key='map_lat')
            lon = right.text_input('Kinh độ đã xác minh', placeholder='Ví dụ: 105.123456', key='map_lon')
            url = st.text_input('URL nguồn xác minh tọa độ', key='map_source')
            confirmed = st.checkbox(
                'Tôi đã kiểm tra các tọa độ này thuộc đúng dự án nêu tên, dựa trên nguồn gốc đáng tin cậy.',
                key='map_verified',
            )
            submitted = st.form_submit_button('Tạo bản đồ HTML')
        if submitted:
            try:
                from visuals import location_map

                if not lat.strip() or not lon.strip():
                    raise ValueError('Nhập tọa độ của dự án; ứng dụng không tự suy ra vị trí.')
                path = location_map(name, float(lat), float(lon), url, coordinates_verified=confirmed)
                st.download_button(
                    'Tải bản đồ HTML có dẫn nguồn', path.read_bytes(), file_name=path.name, mime='text/html'
                )
                st.success('Đã tạo bản đồ dựa trên tọa độ đã được người dùng xác minh.')
            except Exception as exc:
                st.error(error_text(exc))
    with st.expander('Thẻ dữ kiện tiếng Trung'):
        with st.form('fact_form'):
            title = st.text_input('Tiêu đề thẻ (中文)', key='visual_title')
            fact = st.text_input('Một dữ kiện đã kiểm chứng (中文)', key='visual_fact')
            url = st.text_input('URL nguồn chứng minh dữ kiện', key='visual_src')
            reviewed = st.checkbox(
                'Tôi đã đối chiếu dữ kiện với nguồn gốc và duyệt nội dung tiếng Trung.', key='fact_reviewed'
            )
            submit = st.form_submit_button('Tạo thẻ dữ kiện 1200×630')
        if submit:
            try:
                from visuals import fact_visual

                path = fact_visual(title, fact, url, reviewed=reviewed)
                st.image(str(path))
                st.download_button('Tải thẻ PNG', path.read_bytes(), file_name=path.name, mime='image/png')
                st.caption('Thẻ dữ kiện minh họa; không phải hình ảnh thực tế hoặc bản phối cảnh dự án.')
            except Exception as exc:
                st.error(error_text(exc))
    with st.expander('Tạo ảnh minh họa AI (AI Image Generator)', expanded=True):
        st.caption('Sinh ảnh minh họa theo mô tả văn bản bằng AI (hoàn toàn miễn phí, phong cách chân thực/báo chí).')
        with st.form('ai_image_form'):
            img_prompt = st.text_area(
                'Mô tả ảnh cần tạo (Prompt - tiếng Việt, tiếng Anh hoặc tiếng Trung)',
                placeholder='Ví dụ: Các doanh nhân và luật sư đang họp ký kết hợp đồng đầu tư tại văn phòng hiện đại nhìn ra cầu Nhật Tân Hà Nội',
                key='ai_img_prompt',
                height=90,
            )
            img_title = st.text_input('Tiêu đề / Ghi chú ảnh (tùy chọn)', key='ai_img_title')
            generate_btn = st.form_submit_button('Vẽ và tải ảnh AI', type='primary')
        if generate_btn:
            try:
                from visuals import generate_ai_image

                with st.spinner('Đang tạo và tải ảnh minh họa AI…'):
                    img_path = generate_ai_image(img_prompt, title=img_title)
                st.image(str(img_path), caption=f'Ảnh minh họa AI · {img_title or img_prompt[:60]}')
                st.download_button(
                    'Tải ảnh JPG',
                    img_path.read_bytes(),
                    file_name=img_path.name,
                    mime='image/jpeg',
                )
                st.success('Đã tạo ảnh minh họa thành công và lưu vào thư mục visuals/!')
            except Exception as exc:
                st.error(error_text(exc))


def main():
    st.set_page_config(page_title='FRIC LAW · Content Studio', page_icon='⚖️', layout='wide')
    require_access(st)
    try:
        init()
    except Exception as exc:
        st.error('Không thể mở thư mục dữ liệu / SQLite: ' + error_text(exc))
        st.stop()
    if st.session_state.pop('_clear_api_inputs', False):
        st.session_state.pop('local_tavily_key', None)
        st.session_state.pop('local_aibox_key', None)
    if st.session_state.pop('_clear_ai_inputs', False):
        st.session_state.pop('ai_aibox_key', None)
        st.session_state.pop('ai_model', None)
        st.session_state.pop('_ai_form_revision', None)
    if st.session_state.pop('_new_draft', False):
        for key in (
            'draft_title',
            'draft_content',
            'selected_src',
            'editing_article_id',
            'draft_notes',
            'client_confirmation',
        ):
            st.session_state.pop(key, None)
    load = st.session_state.pop('_load_draft', None)
    if load:
        st.session_state.update(
            draft_title=load['title'],
            draft_content=load['content'],
            selected_src=json_value(load['source_ids'], []),
            editing_article_id=load['id'],
            write_category=load['category'],
            client_confirmation=load.get('client_confirmation') or '',
        )
    if '_navigate' in st.session_state:
        st.session_state['navigation'] = st.session_state.pop('_navigate')
    for key, value in {
        'draft_title': '',
        'draft_content': '',
        'selected_src': [],
        'write_category': CATEGORIES[0],
        'client_confirmation': '',
        'draft_notes': '',
        'navigation': PAGES[0],
    }.items():
        st.session_state.setdefault(key, value)
    # Detach persistent draft values from Streamlit's hidden-widget cleanup.
    # Moving between research and writing must not discard unsaved editorial work.
    for key in (
        'draft_title',
        'draft_content',
        'selected_src',
        'write_category',
        'client_confirmation',
        'draft_notes',
        'search_query',
        'search_start',
        'search_end',
        'search_sites',
        'search_category',
        'search_provider',
    ):
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]
    st.markdown(
        """<style>
    .block-container{padding-top:3.5rem;padding-bottom:3rem;max-width:1260px}
    [data-testid="stSidebar"]{background:#eff4f3}
    [data-testid="stMetric"]{border:1px solid #d9e5e2;border-radius:12px;padding:1rem;background:#f9fbfa}
    [data-testid="stMetricValue"]{color:#17675f}
    [data-testid="stTextInput"] input{border-radius:9px}
    h1{letter-spacing:-.025em}h2,h3{color:#184f4b}
    .brand-kicker{font-size:.76rem;letter-spacing:.18em;color:#627b77;font-weight:700;margin-bottom:.45rem}
    </style>""",
        unsafe_allow_html=True,
    )
    sources, articles = get_sources(), list_articles()
    with st.sidebar:
        st.markdown('### ⚖️ FRIC LAW')
        st.caption('CONTENT STUDIO · 本地编辑工作台')
        page = st.radio(
            'Điều hướng biên tập', PAGES, index=None, key='navigation', label_visibility='collapsed'
        )
        st.divider()
        st.caption('NGHIÊN CỨU → CHỨNG CỨ → BẢN THẢO → DUYỆT → MASTER')
        with st.expander('Kết nối & thư mục làm việc'):
            st.caption('Dữ liệu SQLite, bản thảo, lịch sử và Word được lưu trên máy.')
            st.code(str(WORKSPACE), language=None)
            st.caption('● Sẵn sàng · Tìm kiếm nguồn công khai (không cần API key)')
            key_status = get_key_status()
            for key, label in [('TAVILY_API_KEY', 'Tavily tùy chọn'), ('AIBOX_API_KEY', 'AI Box soạn thảo')]:
                st.caption(f'{"● Đã cấu hình" if key_status.get(key) else "○ Chưa cấu hình"} · {label}')
            st.caption(
                'Đã cấu hình chỉ có nghĩa đã lưu khóa. Mở Soạn & duyệt → Kết nối AI Box để kiểm tra thực tế.'
            )
            if remote_access_required():
                st.caption(
                    'Khóa API do quản trị viên cấu hình trên máy chủ; không thay đổi qua link chia sẻ.'
                )
            else:
                st.caption('Đọc khóa từ .env. Không nhập hoặc hiển thị khóa trong bản thảo.')
                with st.form('local_api_settings', clear_on_submit=True):
                    st.caption('Kết nối tùy chọn trên máy này. Để trống nếu không cần thay đổi khóa đã lưu.')
                    tavily_key = st.text_input('Tavily API key', type='password', key='local_tavily_key')
                    aibox_key = st.text_input('AI Box API key', type='password', key='local_aibox_key')
                    save_keys = st.form_submit_button('Lưu cấu hình API trên máy')
                if save_keys:
                    try:
                        if not tavily_key.strip() and not aibox_key.strip():
                            raise ValueError(
                                'Nhập ít nhất một khóa mới; tìm kiếm nguồn công khai không cần khóa.'
                            )
                        save_api_keys(
                            tavily_key=tavily_key.strip() or None,
                            aibox_key=aibox_key.strip() or None,
                        )
                        st.session_state['_clear_api_inputs'] = True
                        flash('Đã lưu cấu hình API trên máy. Khóa không được hiển thị trong giao diện.')
                        st.rerun()
                    except Exception as exc:
                        st.error(error_text(exc))
        with st.expander('Nguyên tắc biên tập'):
            st.write(
                'Ưu tiên nguồn nhà nước; tách biệt sự kiện, quy định pháp luật và phân tích. Một bài chỉ có một chủ đề.'
            )
            st.write(
                'Mỗi luận điểm phải có chứng cứ. Bản thảo AI cần được xác minh độc lập. Chỉ xuất sau khi luật sư và biên tập viên duyệt.'
            )
            st.caption(
                'Mẫu .docx chỉ hướng dẫn phong cách. Không mặc nhiên là căn cứ pháp lý hay xác nhận FRIC LAW tham gia dự án.'
            )
    st.markdown(
        '<div class="brand-kicker">VIETNAM × CHINA · LEGAL & INVESTMENT INTELLIGENCE</div>',
        unsafe_allow_html=True,
    )
    st.title('FRIC LAW · Content Studio')
    st.caption('越南法律资讯 · 越南律师解答 · 面向中国投资者的专业内容')
    if '_flash' in st.session_state:
        st.success(st.session_state.pop('_flash'))
    a, b, c, d = st.columns(4)
    a.metric('Nguồn nghiên cứu', len(sources))
    b.metric('Ngày đăng đã xác minh', sum(bool(s.get('date_verified')) for s in sources))
    c.metric('Bài đã lưu', len(articles))
    d.metric('Bài trong Word MASTER', sum(bool(article['docx_saved']) for article in articles))
    st.write('')
    if page == PAGES[0]:
        search_page(sources)
    elif page == PAGES[1]:
        source_page(sources)
    elif page == PAGES[2]:
        writer_page(sources)
    elif page == PAGES[3]:
        library_page(articles)
    else:
        visual_page()


if __name__ == '__main__':
    main()
