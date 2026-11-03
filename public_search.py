"""No-key discovery from the publishers' own RSS and public index pages.

This is a bounded scan of currently exposed entries, not a full web/archive
index. Feed timestamps only help order candidates; callers must fetch the
original page to prove publication dates. No feed result verifies legal claims.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from datetime import date, datetime
import re
from threading import Lock
import time
import unicodedata
from urllib.parse import parse_qs, urljoin, urlsplit
from xml.etree import ElementTree

from bs4 import BeautifulSoup
import requests

# Fixed, publisher-owned endpoints; never execute a URL supplied in a query.
# Government legal indexes expose issuance/effect dates, so index discovery
# deliberately supplies no publication date for them.
PUBLIC_SOURCES = (
    ('baochinhphu.vn', 'rss', 'https://baochinhphu.vn/home.rss'),
    ('baochinhphu.vn', 'rss', 'https://baochinhphu.vn/kinh-te.rss'),
    ('baochinhphu.vn', 'rss', 'https://baochinhphu.vn/chinh-sach-moi.rss'),
    ('baochinhphu.vn', 'rss', 'https://baochinhphu.vn/phap-luat.rss'),
    ('vnexpress.net', 'rss', 'https://vnexpress.net/rss/kinh-doanh.rss'),
    ('vnexpress.net', 'rss', 'https://vnexpress.net/rss/phap-luat.rss'),
    ('cafef.vn', 'rss', 'https://cafef.vn/vi-mo-dau-tu.rss'),
    ('cafef.vn', 'rss', 'https://cafef.vn/doanh-nghiep.rss'),
    ('cafef.vn', 'rss', 'https://cafef.vn/tai-chinh-ngan-hang.rss'),
    ('vietnamplus.vn', 'rss', 'https://www.vietnamplus.vn/rss/kinhte-311.rss'),
    ('vneconomy.vn', 'rss', 'https://vneconomy.vn/dau-tu.rss'),
    ('vneconomy.vn', 'rss', 'https://vneconomy.vn/tai-chinh.rss'),
    ('baodautu.vn', 'index', 'https://baodautu.vn/'),
    ('vanban.chinhphu.vn', 'index', 'https://vanban.chinhphu.vn/'),
    ('congbao.chinhphu.vn', 'index', 'https://congbao.chinhphu.vn/'),
    ('sbv.gov.vn', 'index', 'https://sbv.gov.vn/vi/trang-chu'),
    ('mof.gov.vn', 'index', 'https://mof.gov.vn/'),
    ('vbpl.vn', 'index', 'https://vbpl.vn/Pages/portal.aspx'),
    ('vbpl.moj.gov.vn', 'index', 'https://vbpl.moj.gov.vn/Pages/portal.aspx'),
    ('thuvienphapluat.vn', 'index', 'https://thuvienphapluat.vn/phap-luat/thoi-su-phap-luat'),
)
_MAX_BYTES = 1_500_000
_SCAN_SECONDS = 12
_HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; FRIC-LAW-research/1.0; human-reviewed)'}
_DNS_LOCKS = {urlsplit(url).hostname: Lock() for _, _, url in PUBLIC_SOURCES}
_ERROR_LABELS = {
    'dns_unverified': 'Chưa xác minh được DNS công khai; kiểm tra VPN/DNS.',
    'timeout': 'Nguồn phản hồi quá chậm.',
    'tls_error': 'Không thiết lập được kết nối HTTPS được xác thực.',
    'connection_error': 'Không kết nối được với máy chủ nguồn.',
    'http_error': 'Máy chủ trả về lỗi HTTP.',
    'access_blocked': 'Máy chủ chặn yêu cầu đọc tự động.',
    'empty_index': 'Trang không cung cấp danh sách bài đọc được (có thể cần JavaScript).',
    'invalid_feed': 'Nguồn RSS không trả về dữ liệu XML được hỗ trợ.',
    'redirect_blocked': 'Nguồn chuyển hướng ngoài máy chủ được duyệt.',
    'oversized': 'Nguồn vượt giới hạn dung lượng đọc.',
    'unavailable': 'Chưa đọc được dữ liệu từ nguồn.',
}
_STOP_WORDS = {
    'viet',
    'nam',
    'moi',
    'cac',
    'cua',
    'cho',
    'voi',
    'trong',
    'nhung',
    'nhieu',
    'mot',
    'the',
    'and',
    'for',
    'vietnam',
    'new',
    'luat',
    'dau',
    'nghiep',
    'nuoc',
    'ngoai',
}
# Editorial query aliases only; these do not translate or substantiate articles.
_THEMES = (
    ('trung quoc', 'china', 'chinese', '中国', '中资'),
    ('dau tu', 'investment', 'investor', '投资'),
    ('fdi', 'dau tu nuoc ngoai', 'foreign investment', '外商投资'),
    (
        'khu cong nghiep',
        'kcn',
        'industrial park',
        'industrial parks',
        'industrial zone',
        'industrial zones',
        'industrial estate',
        'industrial estates',
        '工业园',
        '工业区',
        '产业园',
    ),
    ('nha may', 'factory', '工厂'),
    ('du an', 'project', '项目'),
    ('ha tang', 'infrastructure', '基础设施'),
    ('nang luong', 'energy', '能源'),
    ('nghi dinh', 'decree', '法令'),
    ('thong tu', 'circular', '通知'),
    ('phap luat', 'luat', 'law', 'legal', '法律'),
    ('sua doi', 'amendment', 'amended', '修订'),
    ('ngoai hoi', 'foreign exchange', '外汇'),
    ('ngan hang', 'bank', '银行'),
    ('thue', 'tax', '税'),
    ('chuyen tien', 'remittance', '汇款'),
    (
        'tai khoan von',
        'dica',
        'capital account',
        'capital accounts',
        'direct investment capital account',
        '资本账户',
    ),
    ('mua ban sap nhap', 'sap nhap', 'm&a', 'acquisition', '并购'),
    ('co phan', 'von gop', 'equity', '股权'),
    ('doanh nghiep', 'business', 'enterprise', '企业'),
    ('lao dong', 'labour', 'labor', '劳动'),
    ('giay phep', 'license', 'licence', '许可证'),
    ('thu tuc', 'procedure', '手续'),
)


def _normalise(value):
    value = unicodedata.normalize('NFKD', str(value).lower()).replace('đ', 'd')
    value = ''.join(ch for ch in value if not unicodedata.combining(ch))
    return ' '.join(re.findall(r'[a-z0-9&]+|[\u3400-\u9fff]+', value))


def _contains(text, phrase):
    # Latin word boundaries avoid e.g. "law" matching "lawyer" by accident.
    if re.fullmatch(r'[a-z0-9& ]+', phrase):
        return bool(re.search(r'(?<![a-z0-9])' + re.escape(phrase) + r'(?![a-z0-9])', text))
    return phrase in text


def relevance_score(query, title, summary=''):
    """Accent-insensitive OR-of-topics scoring, retaining narrow exact matches.

    A long category query represents alternative related themes. Requiring
    every word would wrongly discard most investment news. China/FDI phrases
    receive extra weight so direct investor relevance ranks above broad terms.
    """
    original_text = unicodedata.normalize('NFC', str(title) + ' ' + str(summary)).lower()
    query, title, summary = map(_normalise, (query, title, summary))
    text = title + ' ' + summary
    china_query = any(_contains(query, phrase) for phrase in _THEMES[0])
    investment_query = any(_contains(query, phrase) for phrase in _THEMES[1])
    china_match = any(_contains(text, phrase) for phrase in _THEMES[0])
    investment_match = any(_contains(text, phrase) for phrase in _THEMES[1])
    industrial_query = any(_contains(query, phrase) for phrase in _THEMES[3])
    if industrial_query and len(query.split()) <= 6:
        # A focused industrial-park search must not match just "khu" and
        # "công" in unrelated construction, gasoline or business articles.
        # Long category bags deliberately retain alternative related themes.
        if not any(_contains(text, phrase) for phrase in _THEMES[3]):
            return 0.0, []
    if china_query and not china_match:
        # An explicit country in the user's/category query is a constraint,
        # rather than an invitation to return every generic investment item.
        return 0.0, []
    sensational = (
        'ca si',
        'dien vien',
        'showbiz',
        'giai tri',
        'lua dao',
        'bat giu',
        'co bac',
        'danh bac',
        'nhap canh trai phep',
    )
    if china_query and any(_contains(text, phrase) for phrase in sensational):
        if not any(_contains(query, phrase) for phrase in sensational):
            return 0.0, []
    if china_query and investment_query:
        context = (
            'tai chinh',
            'kinh te',
            'thuong mai',
            'xuat khau',
            'nhap khau',
            'logistics',
            'finance',
            'economy',
            'trade',
        )
        # "thuê nhà" (rent a house) and "thuế" (tax) become identical after
        # accent folding. Only a real tax spelling/phrase can supply context.
        economic_themes = _THEMES[1:8] + _THEMES[12:14] + _THEMES[15:19]
        economic = any(_contains(text, phrase) for aliases in economic_themes for phrase in aliases)
        tax_context = 'thuế' in original_text or any(
            _contains(text, phrase) for phrase in ('tax', '税', 'thue thu nhap', 'thue gia tri', 'thue suat')
        )
        linked_context = any(_contains(title, phrase) for phrase in context) or (
            _contains(text, 'viet nam') and any(_contains(text, phrase) for phrase in context)
        )
        if not economic and not tax_context and not linked_context:
            return 0.0, []
    score = 0.0
    matched = []
    for aliases in _THEMES:
        if any(_contains(query, phrase) for phrase in aliases):
            title_match = any(_contains(title, phrase) for phrase in aliases)
            summary_match = any(_contains(summary, phrase) for phrase in aliases)
            if title_match or summary_match:
                weight = 4 if aliases[0] in ('trung quoc', 'fdi', 'khu cong nghiep') else 2
                score += weight * (1 if title_match else 0.45)
                matched.append(aliases[0])
    words = {word for word in query.split() if len(word) >= 3 and word not in _STOP_WORDS}
    overlap = words & set((title + ' ' + summary).split())
    # Two overlapping words or one distinctive long word avoid single generic
    # syllables becoming a match. Explicit themes above handle short FDI/tax.
    if len(overlap) >= 2 or any(len(word) >= 5 for word in overlap):
        score += min(2, len(overlap) * 0.35)
    if len(query) >= 4 and _contains(title, query):
        score += 5
    if china_query and investment_query and china_match and investment_match:
        score += 4  # Exact investor relationship deserves priority over either topic alone.
    return score, matched


class PublicSourceError(ValueError):
    """Only a controlled reason/status may cross into editor diagnostics."""

    def __init__(self, reason, status_code=None):
        self.reason = reason if reason in _ERROR_LABELS else 'unavailable'
        self.status_code = status_code
        super().__init__(_ERROR_LABELS[self.reason])


def _failure(source, error):
    reason, status = 'unavailable', None
    if isinstance(error, PublicSourceError):
        reason, status = error.reason, error.status_code
    elif isinstance(error, requests.exceptions.SSLError):
        reason = 'tls_error'
    elif isinstance(error, requests.Timeout):
        reason = 'timeout'
    elif isinstance(error, requests.ConnectionError):
        reason = 'connection_error'
    elif isinstance(error, requests.HTTPError):
        reason = 'http_error'
        if error.response is not None:
            status = error.response.status_code
    result = {
        'domain': source[0],
        'url': source[2],
        'reason': reason,
        'message': _ERROR_LABELS[reason],
    }
    if isinstance(status, int) and 100 <= status <= 599:
        result['status_code'] = status
    return result


def _request(url, deadline):
    # Import at call time: research owns the one approved-domain/DNS policy.
    from research import _assert_public_dns, canonical, domain_of

    response = None
    for hop in range(3):
        canonical(url)
        host = urlsplit(url).hostname
        # Several feeds from one publisher must not simultaneously trigger
        # repeated independent DNS corroboration on desktop VPN connections.
        dns_lock = _DNS_LOCKS.get(host)
        acquired = dns_lock is None or dns_lock.acquire(timeout=max(0, deadline - time.monotonic()))
        if not acquired:
            raise PublicSourceError('timeout')
        try:
            try:
                _assert_public_dns(host)
            except (ValueError, OSError):
                raise PublicSourceError('dns_unverified') from None
        finally:
            if dns_lock is not None:
                dns_lock.release()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise PublicSourceError('timeout')
        # One retry for transient transport/server errors, within the same
        # overall discovery deadline. Access blocks and invalid TLS never retry.
        for attempt in range(2):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PublicSourceError('timeout')
            try:
                response = requests.get(
                    url,
                    headers=_HEADERS,
                    timeout=(min(2, remaining), min(4, remaining)),
                    allow_redirects=False,
                    stream=True,
                )
                if response.status_code in (429, 502, 503, 504) and not attempt and remaining > 1:
                    response.close()
                    continue
                break
            except requests.exceptions.SSLError:
                raise
            except (requests.Timeout, requests.ConnectionError):
                if attempt or deadline - time.monotonic() < 1:
                    raise
        try:
            if response.is_redirect or response.is_permanent_redirect:
                target = urljoin(url, response.headers.get('Location', ''))
                # Same publisher only. A feed cannot redirect into a different
                # approved publisher, a login host or any private network.
                if hop == 2 or domain_of(target) != domain_of(url) or target == url:
                    raise PublicSourceError('redirect_blocked')
                canonical(target)
                url = target
                continue
            if response.status_code in (401, 403, 429):
                raise PublicSourceError('access_blocked', response.status_code)
            response.raise_for_status()
            chunks, total = [], 0
            for chunk in response.iter_content(chunk_size=65_536):
                if time.monotonic() > deadline:
                    raise PublicSourceError('timeout')
                total += len(chunk)
                if total > _MAX_BYTES:
                    raise PublicSourceError('oversized')
                chunks.append(chunk)
            return b''.join(chunks), url
        finally:
            response.close()
    raise PublicSourceError('redirect_blocked')


def _clean_html(value, limit):
    return BeautifulSoup(value or '', 'html.parser').get_text(' ', strip=True)[:limit]


def _parse_feed(raw, base_url):
    """Parse RSS/Atom, excluding external entities and opaque aggregator URLs."""
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise PublicSourceError('invalid_feed')
    try:
        root = ElementTree.fromstring(raw.lstrip())
    except ElementTree.ParseError:
        raise PublicSourceError('invalid_feed') from None
    if root.tag.rsplit('}', 1)[-1] not in ('rss', 'feed', 'RDF'):
        raise PublicSourceError('invalid_feed')
    items = []
    for node in root.iter():
        if node.tag.rsplit('}', 1)[-1] not in ('item', 'entry'):
            continue
        fields = {}
        for child in node:
            name = child.tag.rsplit('}', 1)[-1]
            text = ''.join(child.itertext()).strip()
            if name == 'link':
                link = child.get('href') or text
                if link and child.get('rel', 'alternate') == 'alternate':
                    fields['url'] = urljoin(base_url, link)
            elif name == 'guid' and child.get('isPermaLink', 'true') != 'false':
                fields.setdefault('url', urljoin(base_url, text))
            elif name == 'title':
                fields['title'] = _clean_html(text, 400)
            elif name in ('description', 'summary'):
                fields['summary'] = _clean_html(text, 1000)
            elif name in ('pubDate', 'published', 'date'):
                fields['provider_date_hint'] = text[:100] or None
        if fields.get('url') and fields.get('title'):
            fields.setdefault('summary', '')
            fields.setdefault('provider_date_hint', None)
            items.append(fields)
        if len(items) >= 120:
            break
    return items


def _is_article_url(url):
    from research import domain_of

    parts = urlsplit(url)
    host = domain_of(url)
    path = parts.path.lower()
    if host == 'vanban.chinhphu.vn':
        return bool(parse_qs(parts.query).get('docid'))
    if host == 'congbao.chinhphu.vn':
        return bool(re.search(r'^/van-ban/.+-\d+\.htm$', path))
    if host == 'sbv.gov.vn':
        return path.startswith('/w/')
    if host == 'baodautu.vn':
        return bool(re.search(r'-d\d+\.html$', path))
    if host in ('vbpl.vn', 'vbpl.moj.gov.vn'):
        return bool(parse_qs(parts.query).get('ItemID'))
    if host == 'mof.gov.vn':
        return '/tin-tuc/' in path or '/chi-tiet' in path
    if host == 'thuvienphapluat.vn':
        return bool(re.search(r'-\d+\.html$', path))
    return False


def _parse_index(raw, base_url):
    soup = BeautifulSoup(raw, 'html.parser')
    for tag in soup(['nav', 'header', 'footer', 'script', 'style']):
        tag.decompose()
    result, seen = [], set()
    for anchor in soup.find_all('a', href=True):
        url = urljoin(base_url, anchor['href'])
        title = anchor.get_text(' ', strip=True)
        if len(title) < 24 or url in seen or not _is_article_url(url):
            continue
        seen.add(url)
        result.append(
            {
                'url': url,
                'title': title[:400],
                'summary': '',
                'provider_date_hint': None,
            }
        )
        if len(result) >= 160:
            break
    return result


def _read_source(source, deadline):
    host, kind, url = source
    raw, final_url = _request(url, deadline)
    if re.search(
        rb'<title[^>]*>\s*(?:request\s*rejected|access\s*denied|forbidden)|'
        rb'your\s+requested\s+url\s+was\s+rejected',
        raw[:8192],
        re.I,
    ):
        raise PublicSourceError('access_blocked')
    items = _parse_feed(raw, final_url) if kind == 'rss' else _parse_index(raw, final_url)
    return host, items


def discover_public(query, start, end, domains, max_results=20):
    """Return {candidates, diagnostics}; publication verification is caller-owned.

    Searches the selected publishers' latest feeds/indexes in parallel, using
    no account or secret. Partial failures never conceal surviving candidates.
    The date interval is validated but never enforced from a feed timestamp.
    """
    from research import _allowed_host, _normalise_domains, canonical, domain_of

    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 500 or '\x00' in query:
        raise ValueError('Từ khóa cần từ 2 đến 500 ký tự.')
    if (
        any(not isinstance(value, date) or isinstance(value, datetime) for value in (start, end))
        or start > end
    ):
        raise ValueError('Khoảng ngày không hợp lệ.')
    if isinstance(max_results, bool) or not isinstance(max_results, int) or max_results < 1:
        raise ValueError('Số kết quả phải là số nguyên dương.')
    selected = _normalise_domains(domains)
    sources = [source for source in PUBLIC_SOURCES if _allowed_host(source[0], selected)]
    covered = {host for host, _, _ in sources}
    unsupported = [
        domain for domain in selected if not any(_allowed_host(host, [domain]) for host in covered)
    ]
    diagnostics = {
        'provider': 'public_rss',
        'providers_attempted': [source[2] for source in sources],
        'providers_succeeded': [],
        'failed_sources': [],
        'unsupported_domains': unsupported,
        'warnings': [],
        'coverage_note': (
            'Đọc RSS/mục tin công khai hiện có của nguồn đã chọn; không phải toàn bộ kho lưu trữ. '
            'Ngày trong RSS chỉ là gợi ý, từng URL vẫn phải xác minh ngày đăng gốc.'
        ),
    }
    if unsupported:
        diagnostics['warnings'].append('Chưa có bộ đọc công khai cho: ' + ', '.join(unsupported) + '.')
    deadline = time.monotonic() + _SCAN_SECONDS
    pool = ThreadPoolExecutor(max_workers=min(12, len(sources) or 1))
    jobs = {pool.submit(_read_source, source, deadline): source for source in sources}
    items = []
    try:
        for future in as_completed(jobs, timeout=_SCAN_SECONDS + 0.2):
            source = jobs[future]
            try:
                _, entries = future.result()
                if not entries:
                    diagnostics['failed_sources'].append(_failure(source, PublicSourceError('empty_index')))
                else:
                    diagnostics['providers_succeeded'].append(source[2])
                for entry in entries:
                    # Only original, reviewed, selected publisher URLs survive.
                    try:
                        url = canonical(entry['url'])
                    except ValueError:
                        continue
                    if not _allowed_host(domain_of(url), selected):
                        continue
                    score, matches = relevance_score(query, entry['title'], entry.get('summary', ''))
                    if score <= 0:
                        continue
                    items.append(
                        dict(
                            entry,
                            url=url,
                            discovery_provider='publisher_rss' if source[1] == 'rss' else 'publisher_index',
                            discovery_source=source[2],
                            discovery_matches=matches,
                            provider_score=round(min(score / 15, 1), 4),
                            _match_score=score,
                        )
                    )
            except (ValueError, OSError, requests.RequestException) as error:
                # Never echo exception bodies, redirected URLs or credentials.
                diagnostics['failed_sources'].append(_failure(source, error))
    except TimeoutError:
        diagnostics['warnings'].append('Một số nguồn phản hồi chậm; đã trả phần kết quả đọc được.')
    finally:
        for future, source in jobs.items():
            if not future.done():
                future.cancel()
                diagnostics['failed_sources'].append(_failure(source, PublicSourceError('timeout')))
        pool.shutdown(wait=False, cancel_futures=True)
    if diagnostics['failed_sources']:
        successful_domains = {domain_of(url) for url in diagnostics['providers_succeeded']}
        failed_domains = {item['domain'] for item in diagnostics['failed_sources']}
        fully_failed = sorted(failed_domains - successful_domains)
        partial = sorted(failed_domains & successful_domains)
        if fully_failed:
            diagnostics['warnings'].append(
                'Chưa đọc được nguồn: '
                + ', '.join(fully_failed)
                + '. Xem chi tiết kết nối hoặc thêm URL gốc thủ công.'
            )
        if partial:
            diagnostics['warnings'].append(
                'Một số mục của nguồn '
                + ', '.join(partial)
                + ' chưa phản hồi; vẫn dùng các mục đã đọc được của những nguồn này.'
            )
        diagnostics['fully_failed_domains'] = fully_failed
        diagnostics['partial_domains'] = partial
    else:
        diagnostics['fully_failed_domains'] = []
        diagnostics['partial_domains'] = []
    diagnostics['successful_domains'] = sorted({domain_of(url) for url in diagnostics['providers_succeeded']})
    diagnostics['attempted_domain_count'] = len(covered)
    diagnostics['successful_domain_count'] = len(diagnostics['successful_domains'])
    diagnostics['failed_sources'].sort(key=lambda item: (item['domain'], item['url']))
    # Hint dates can break a relevance tie; never discard an original based on
    # a feed date. The caller's original-page gate alone establishes recency.
    from research import _parse_publication_date

    def ordering(item):
        hint = _parse_publication_date(item.get('provider_date_hint'))
        in_range_hint = bool(hint and start <= hint <= end)
        return (-item['_match_score'], not in_range_hint, -(hint.toordinal() if hint else 0), item['url'])

    unique = {}
    for item in sorted(items, key=ordering):
        unique.setdefault(item['url'], item)
    candidates = list(unique.values())[: min(max_results, 40)]
    for candidate in candidates:
        candidate.pop('_match_score', None)
    diagnostics['candidate_count'] = len(candidates)
    diagnostics['matched_before_limit'] = len(unique)
    diagnostics['providers_succeeded'].sort()
    return {'candidates': candidates, 'diagnostics': diagnostics}
