"""Evidence-first discovery, publication-date gates and conservative story clustering.

A search-provider date is a discovery hint only. ``date_verified`` means that an
explicit publication field was found on the original page; it does not verify
any claim in that page or the current legal effect of an instrument.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from functools import lru_cache
from email.utils import parsedate_to_datetime
import ipaddress
import json
import math
import os
import re
import socket
import time
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit, urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
import requests

TZ = ZoneInfo('Asia/Ho_Chi_Minh')
DOMAINS = [
    'vanban.chinhphu.vn',
    'congbao.chinhphu.vn',
    'chinhphu.vn',
    'baochinhphu.vn',
    'vbpl.moj.gov.vn',
    'vbpl.vn',
    'mof.gov.vn',
    'sbv.gov.vn',
    'mpi.gov.vn',
    'moj.gov.vn',
    'thuvienphapluat.vn',
    'cafef.vn',
    'vnexpress.net',
    'vietnamplus.vn',
    'baodautu.vn',
    'vneconomy.vn',
    'vcci.com.vn',
    'customs.gov.vn',
    'vir.com.vn',
]
OFFICIAL = {
    'vanban.chinhphu.vn',
    'congbao.chinhphu.vn',
    'chinhphu.vn',
    'baochinhphu.vn',
    'vbpl.moj.gov.vn',
    'vbpl.vn',
    'mof.gov.vn',
    'sbv.gov.vn',
    'mpi.gov.vn',
    'moj.gov.vn',
    'customs.gov.vn',
}
CATEGORIES = [
    'Pháp luật & chính sách',
    'Đầu tư Việt–Trung',
    'Dự án & hạ tầng',
    'Ngân hàng, thuế & ngoại hối',
    'Doanh nghiệp & M&A',
    'Giải đáp pháp lý',
]
TOPICS = {
    CATEGORIES[0]: 'luật nghị định thông tư mới đầu tư nước ngoài doanh nghiệp Việt Nam',
    CATEGORIES[1]: 'doanh nghiệp Trung Quốc đầu tư Việt Nam FDI nhà máy dự án',
    CATEGORIES[2]: 'dự án mới Việt Nam khu công nghiệp năng lượng giao thông trung tâm tài chính',
    CATEGORIES[3]: 'thuế ngân hàng nhà nước ngoại hối tài khoản vốn đầu tư trực tiếp',
    CATEGORIES[4]: 'mua bán sáp nhập vốn góp cổ phần doanh nghiệp nhà đầu tư nước ngoài',
    CATEGORIES[5]: 'thủ tục đầu tư tranh chấp lao động giấy phép doanh nghiệp nước ngoài Việt Nam',
}
_TRACKING_KEYS = {
    'fbclid',
    'gclid',
    'dclid',
    'msclkid',
    'mc_eid',
    'mc_cid',
    'igshid',
    '_ga',
    'yclid',
}
_LEGAL_PORTALS = {'vanban.chinhphu.vn', 'congbao.chinhphu.vn', 'vbpl.moj.gov.vn', 'vbpl.vn'}
_MAX_HTML_BYTES = 1_600_000
_ARTICLE_TYPES = {
    'Article',
    'NewsArticle',
    'BlogPosting',
    'Report',
    'AnalysisNewsArticle',
    'OpinionNewsArticle',
    'BackgroundNewsArticle',
    'ScholarlyArticle',
}
# ``date``, dateModified, dateCreated, og:updated_time and legal issuance/effect
# fields are intentionally excluded: none proves original news publication.
_PUBLICATION_META = (
    ('property', 'article:published_time'),
    ('name', 'article:published_time'),
    ('itemprop', 'datePublished'),
    ('name', 'pubdate'),
    ('name', 'publishdate'),
    ('name', 'publish_date'),
    ('name', 'publication_date'),
    ('name', 'originalpublicationdate'),
)
_LAW_ID = re.compile(
    r'(?<![A-Za-z0-9])\d{1,4}/(?:19|20)\d{2}/(?:NĐ-CP|ND-CP|QH\d+|TT-[A-ZĐ0-9-]+|'
    r'QĐ-[A-ZĐ0-9-]+|QD-[A-Z0-9-]+|CT-[A-ZĐ0-9-]+|NQ-[A-ZĐ0-9-]+)',
    re.I,
)


def today_vn():
    return datetime.now(TZ).date()


def default_date_range(today=None):
    """The seven inclusive Vietnam calendar dates ending today."""
    end = today if today is not None else today_vn()
    if not isinstance(end, date) or isinstance(end, datetime):
        raise ValueError('Ngày kết thúc phải là một ngày lịch.')
    return end - timedelta(days=6), end


def domain_of(url):
    try:
        host = (urlsplit(str(url)).hostname or '').lower().rstrip('.')
    except ValueError:
        return ''
    return host[4:] if host.startswith('www.') else host


def _allowed_host(host, domains):
    return any(host == domain or host.endswith('.' + domain) for domain in domains)


def official(url):
    return _allowed_host(domain_of(url), OFFICIAL)


def canonical(url: str) -> str:
    """Validate an approved public URL; remove tracking, retain document IDs.

    This is URL validation only. DNS addresses are checked again immediately
    before retrieval. Redirects are never followed automatically.
    """
    if not isinstance(url, str) or len(url) > 4096:
        raise ValueError('URL không hợp lệ.')
    value = url.strip()
    if re.search(r'[\x00-\x20\\]', value):
        raise ValueError('URL chứa ký tự không hợp lệ.')
    try:
        parts = urlsplit(value)
        host = (parts.hostname or '').lower().rstrip('.')
        port = parts.port
    except ValueError:
        raise ValueError('URL không hợp lệ.') from None
    if parts.scheme.lower() not in ('http', 'https') or not host:
        raise ValueError('URL phải dùng http hoặc https.')
    if parts.username is not None or parts.password is not None:
        raise ValueError('URL không được chứa thông tin đăng nhập.')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError('Không chấp nhận URL dùng địa chỉ IP.')
    if host == 'localhost' or host.endswith(('.local', '.internal')):
        raise ValueError('Không chấp nhận máy chủ nội bộ.')
    host = host[4:] if host.startswith('www.') else host
    if not _allowed_host(host, DOMAINS):
        raise ValueError('Nguồn chưa nằm trong danh sách được duyệt.')
    default_port = 443 if parts.scheme.lower() == 'https' else 80
    if port not in (None, default_port):
        raise ValueError('Chỉ cho phép cổng web chuẩn tương ứng với giao thức.')
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith('utm_') and key.lower() not in _TRACKING_KEYS
    ]
    return urlunsplit((parts.scheme.lower(), host, parts.path or '/', urlencode(sorted(query)), ''))


class _UnconfirmedPublicDns(Exception):
    """A failed lookup must leave no cached permission or cached denial."""


@lru_cache(maxsize=128)
def _confirmed_public_dns(host, time_bucket):
    """Cache positive corroboration; exceptions are never cached by lru_cache."""
    del time_bucket  # Cache expires through its five-minute key, not forever.
    response = None
    try:
        response = requests.get(
            'https://dns.google/resolve',
            params={'name': host, 'type': 'A', 'edns_client_subnet': '0.0.0.0/0'},
            timeout=(3, 5),
            allow_redirects=False,
        )
        response.raise_for_status()
        if response.is_redirect:
            raise _UnconfirmedPublicDns
        data = response.json()
        if not isinstance(data, dict) or data.get('Status') != 0 or data.get('TC'):
            raise _UnconfirmedPublicDns
        answers = data.get('Answer') or []
        if not isinstance(answers, list):
            raise _UnconfirmedPublicDns
        addresses = [
            ipaddress.ip_address(row['data'])
            for row in answers
            if isinstance(row, dict) and row.get('type') == 1
        ]
        if not addresses or not all(address.is_global for address in addresses):
            raise _UnconfirmedPublicDns
        return True
    except (requests.RequestException, ValueError, TypeError, KeyError):
        raise _UnconfirmedPublicDns from None
    finally:
        if response is not None:
            response.close()


def _corroborate_public_dns(host, time_bucket):
    """Confirm fixed publishers, retrying immediately after transient failures.

    A failed HTTPS/DNS response still denies this request, but is not cached for
    five minutes. Only a confirmed public answer receives the existing cache.
    """
    try:
        return _confirmed_public_dns(host, time_bucket)
    except _UnconfirmedPublicDns:
        return False


_corroborate_public_dns.cache_clear = _confirmed_public_dns.cache_clear
_corroborate_public_dns.cache_info = _confirmed_public_dns.cache_info


def _assert_public_dns(host):
    try:
        addresses = [
            ipaddress.ip_address(row[4][0]) for row in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        ]
    except (OSError, ValueError):
        raise ValueError('Không xác minh được địa chỉ máy chủ nguồn. Hãy thử lại sau.') from None
    if addresses and all(address.is_global for address in addresses):
        return
    # Some desktop VPNs map every public hostname into 198.18/15 + ULA.
    # Do not treat that as permission to fetch arbitrary local/private URLs:
    # only exact registered publisher names get independent public DNS confirmation.
    benchmark = ipaddress.ip_network('198.18.0.0/15')
    unique_local = ipaddress.ip_network('fc00::/7')
    base = str(host).lower().removeprefix('www.')
    fake_ipv4 = any(address.version == 4 and address in benchmark for address in addresses)
    compatible = all(
        address.is_global
        or (address.version == 4 and address in benchmark)
        or (address.version == 6 and address in unique_local)
        for address in addresses
    )
    if (
        base in DOMAINS
        and fake_ipv4
        and compatible
        and _corroborate_public_dns(str(host).lower(), int(time.monotonic() // 300))
    ):
        return
    raise ValueError(
        'Nguồn trỏ tới địa chỉ mạng không công khai hoặc chưa xác minh được DNS; đã chặn truy cập.'
    )


def _parse_publication_date(value):
    """Parse explicit metadata; timezone-bearing timestamps use Vietnam dates."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    # Date-only and ISO/RFC timestamps are accepted. Ambiguous numeric day/month
    # values and arbitrary prose are not publication evidence.
    if not re.match(r'^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}', value):
        try:
            timestamp = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None
    else:
        try:
            timestamp = datetime.fromisoformat(value.replace('Z', '+00:00').replace('z', '+00:00'))
        except ValueError:
            return None
    if timestamp.tzinfo is None:
        # A timestamp without a UTC offset cannot establish its Vietnam calendar
        # day safely, especially at either edge of the selected date interval.
        return None
    return timestamp.astimezone(TZ).date()


def _json_nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from _json_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _json_nodes(child)


def _publication_evidence(soup, url=None):
    candidates = []
    for attr, key in _PUBLICATION_META:
        for tag in soup.find_all('meta', attrs={attr: re.compile('^' + re.escape(key) + '$', re.I)}):
            raw = tag.get('content', '')
            parsed = _parse_publication_date(raw)
            if parsed:
                candidates.append(
                    {
                        'kind': 'page_metadata',
                        'selector': f'meta[{attr}="{key}"]',
                        'value': raw,
                        'date': parsed.isoformat(),
                    }
                )
    for tag in soup.find_all('time', attrs={'itemprop': re.compile(r'^datePublished$', re.I)}):
        raw = tag.get('datetime') or tag.get('content') or tag.get_text(' ', strip=True)
        parsed = _parse_publication_date(raw)
        if parsed:
            candidates.append(
                {
                    'kind': 'page_metadata',
                    'selector': 'time[itemprop="datePublished"]',
                    'value': raw,
                    'date': parsed.isoformat(),
                }
            )
    for script in soup.find_all('script', attrs={'type': 'application/ld+json'}):
        try:
            data = json.loads(script.string or script.get_text())
        except (ValueError, TypeError, RecursionError):
            continue
        try:
            nodes = list(_json_nodes(data))
        except RecursionError:
            continue
        for node in nodes:
            types = node.get('@type', [])
            types = [types] if isinstance(types, str) else types
            if not isinstance(types, list) or not any(
                isinstance(kind, str) and kind.rsplit('/', 1)[-1] in _ARTICLE_TYPES for kind in types
            ):
                continue
            node_url = node.get('url')
            if url and isinstance(node_url, str):
                try:
                    if canonical(node_url) != canonical(url):
                        continue  # Publication date of a related story is not this page's date.
                except ValueError:
                    continue
            raw = node.get('datePublished')
            parsed = _parse_publication_date(raw)
            if parsed:
                candidates.append(
                    {
                        'kind': 'page_metadata',
                        'selector': 'JSON-LD Article.datePublished',
                        'value': raw,
                        'date': parsed.isoformat(),
                    }
                )
    dates = {item['date'] for item in candidates}
    if len(dates) == 1:
        evidence = dict(candidates[0])
        evidence['note'] = (
            'Ngày đăng gốc trong metadata của trang; chưa xác minh nội dung hay hiệu lực pháp luật.'
        )
        return evidence['date'], evidence, 'verified'
    if len(dates) > 1:
        return (
            None,
            {
                'kind': 'conflicting_metadata',
                'candidates': candidates,
                'note': 'Các trường ngày đăng gốc mâu thuẫn; cần biên tập viên xác minh.',
            },
            'conflicting',
        )
    if url:
        from publication_dates import source_publication_evidence

        return source_publication_evidence(soup, url)
    return None, None, 'unknown'


def _meta_date(soup):
    """Backwards-compatible date helper; ignores modified and legal-effect dates."""
    return _publication_evidence(soup)[0]


def fetch_evidence(url):
    """Fetch a source; allow only same-page www/HTTPS aliases after DNS checks."""
    url = canonical(url)
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; FRIC-LAW-research/1.0; human-reviewed)'}
    response = None
    try:
        retrieval_url = url
        for attempt in range(3):
            _assert_public_dns(urlsplit(retrieval_url).hostname)
            response = requests.get(
                retrieval_url, headers=headers, timeout=(4, 8), allow_redirects=False, stream=True
            )
            if not (response.is_redirect or response.is_permanent_redirect):
                break
            location = response.headers.get('Location')
            if not isinstance(location, str) or not location or attempt == 2:
                raise ValueError('Trang chuyển hướng: mở và kiểm tra URL đích trước khi thêm nguồn.')
            target = urljoin(retrieval_url, location)
            checked = canonical(target)
            before, after = urlsplit(canonical(retrieval_url)), urlsplit(checked)
            if (before.hostname, before.path, before.query) != (after.hostname, after.path, after.query) or (
                before.scheme == 'https' and after.scheme != 'https'
            ):
                raise ValueError('Nguồn chuyển sang trang khác; mở URL đích và kiểm tra thủ công.')
            response.close()
            target_parts = urlsplit(target)
            retrieval_url = urlunsplit((after.scheme, target_parts.netloc, after.path, after.query, ''))
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', '').lower()
        if 'pdf' in content_type:
            raise ValueError('Nguồn PDF: trích xuất và xác minh thủ công rồi dán nội dung liên quan.')
        if content_type and not any(value in content_type for value in ('html', 'text/plain', 'xhtml')):
            raise ValueError('Định dạng nguồn không được hỗ trợ; cần kiểm tra thủ công.')
        chunks = []
        total = 0
        deadline = time.monotonic() + 15
        for chunk in response.iter_content(chunk_size=65_536):
            if time.monotonic() > deadline:
                raise ValueError('Nguồn phản hồi quá chậm; thử lại hoặc kiểm tra thủ công.')
            if chunk:
                total += len(chunk)
                if total > _MAX_HTML_BYTES:
                    raise ValueError('Trang quá lớn để trích xuất an toàn; cần kiểm tra thủ công.')
                chunks.append(chunk)
        raw = b''.join(chunks)
        # Let HTML charset declarations win. Requests defaults to ISO-8859-1
        # for text/html without an HTTP charset, which corrupts Vietnamese.
        declared_charset = re.search(r'charset=[\"\']?([^;\s\"\']+)', content_type)
        soup = BeautifulSoup(
            raw, 'html.parser', from_encoding=declared_charset.group(1) if declared_charset else None
        )
        pub, evidence, date_status = _publication_evidence(soup, retrieval_url)
        for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'form']):
            tag.decompose()
        area = (
            soup.select_one(
                '[itemprop="articleBody"], .detail-content, article.fck_detail, .article__body, .article-body, #content_detail_news'
            )
            or soup.find('article')
            or soup.find('main')
            or soup
        )
        text = '\n'.join(
            line.strip() for line in area.get_text('\n', strip=True).splitlines() if line.strip()
        )[:20000]
        result = {
            'text': text,
            'published': pub,
            'date_evidence': evidence,
            'date_verified': bool(pub),
            'date_status': date_status,
            'fetched_url': retrieval_url,
        }
        if len(text) < 240:
            result['extraction_error'] = 'Chưa trích đủ nội dung; kiểm tra trang gốc và dán văn bản thủ công.'
        return result
    except requests.RequestException:
        raise ValueError(
            'Không tải được trang nguồn. Kiểm tra kết nối, quyền truy cập hoặc dán nội dung thủ công.'
        ) from None
    finally:
        if response is not None:
            response.close()


def fetch_content(url):
    result = fetch_evidence(url)
    if result.get('extraction_error'):
        raise ValueError(result['extraction_error'])
    return result['text'], result['published']


def _normalise_domains(domains):
    if domains is None:
        return list(DOMAINS)
    if not isinstance(domains, (list, tuple, set)) or not domains:
        raise ValueError('Hãy chọn ít nhất một nguồn được duyệt.')
    values = []
    for domain in domains:
        if not isinstance(domain, str):
            raise ValueError('Danh sách nguồn không hợp lệ.')
        host = domain.strip().lower()
        host = host[4:] if host.startswith('www.') else host
        if host not in DOMAINS:
            raise ValueError('Nguồn tìm kiếm chưa nằm trong danh sách được duyệt.')
        if host not in values:
            values.append(host)
    return values


def _verify_hit(hit, start, end):
    result = dict(hit)
    try:
        page = fetch_evidence(hit['url'])
        result.update(page)
        pub = date.fromisoformat(page['published']) if page.get('published') else None
        result['date_status'] = (
            'in_range' if pub and start <= pub <= end else ('outside' if pub else 'unknown')
        )
        if page.get('extraction_error'):
            result['verification_error'] = page['extraction_error']
    except (ValueError, OSError, requests.RequestException):
        # Never surface response bodies, exception strings, API keys or URL userinfo.
        result.update(
            {
                'published': None,
                'date_verified': False,
                'date_evidence': None,
                'date_status': 'unknown',
                'text': '',
                'verification_error': 'Chưa xác minh được ngày đăng gốc/nội dung tại trang nguồn.',
            }
        )
    result['date_label'] = (
        'Trong khoảng ngày đã chọn' if result['date_status'] == 'in_range' else 'Cần xác minh ngày đăng'
    )
    return result


class SearchResults(list):
    """List-compatible findings with honest coverage and verification diagnostics."""

    def __init__(self, values=(), diagnostics=None):
        super().__init__(values)
        self.diagnostics = diagnostics or {}


def search_provider_status(provider='auto'):
    if provider not in ('auto', 'public', 'tavily'):
        raise ValueError('Nguồn tìm kiếm không hợp lệ.')
    configured = bool(os.getenv('TAVILY_API_KEY', '').strip())
    active = ('tavily' if configured else 'public') if provider == 'auto' else provider
    return {'provider': active, 'tavily_configured': configured}


def _discover_tavily(query, start, end, domains, max_results, key):
    # Provider boundaries are after/before, so widen one day; the original-page
    # Vietnam-calendar gate below is the authority for inclusive local dates.
    payload = {
        'query': query,
        'topic': 'general',
        'search_depth': 'advanced',
        'max_results': min(max_results, 20),
        'include_raw_content': False,
        'include_published_date': True,
        'filter_by_published_date': False,
        'include_domains': domains,
        'include_domains_mode': 'restrict',
        'start_date': (start - timedelta(days=1)).isoformat() if start > date.min else start.isoformat(),
        'end_date': (end + timedelta(days=1)).isoformat() if end < date.max else end.isoformat(),
    }
    try:
        response = requests.post(
            'https://api.tavily.com/search',
            json=payload,
            headers={'Authorization': 'Bearer ' + key},
            timeout=(5, 40),
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        raise RuntimeError(
            'Tìm kiếm thất bại. Kiểm tra kết nối, khóa Tavily hoặc hạn mức rồi thử lại; chi tiết nhạy cảm đã được ẩn.'
        ) from None
    if not isinstance(data, dict) or not isinstance(data.get('results', []), list):
        raise RuntimeError('Dịch vụ tìm kiếm trả về dữ liệu không hợp lệ. Hãy thử lại sau.')
    return data.get('results', [])


def search_news(query, start: date, end: date, domains=None, max_results=20, provider='auto'):
    """Find source URLs without requiring a key, then verify original-page dates.

    Public feeds cover latest publisher items, not a complete historical web
    index. Neither a feed date nor a provider estimate passes the date gate.
    """
    if not isinstance(query, str) or '\x00' in query:
        raise ValueError('Từ khóa tìm kiếm không hợp lệ.')
    query = ' '.join(query.split())
    if not 2 <= len(query) <= 500:
        raise ValueError('Từ khóa cần từ 2 đến 500 ký tự.')
    if (
        any(not isinstance(value, date) or isinstance(value, datetime) for value in (start, end))
        or start > end
    ):
        raise ValueError('Khoảng ngày không hợp lệ: ngày bắt đầu phải trước hoặc bằng ngày kết thúc.')
    if isinstance(max_results, bool) or not isinstance(max_results, int) or max_results < 1:
        raise ValueError('Số kết quả phải là số nguyên dương.')
    selected_domains = _normalise_domains(domains)
    began = time.monotonic()
    active = search_provider_status(provider)['provider']
    diagnostics = {
        'provider': active,
        'warnings': [],
        'candidate_count': 0,
        'verified_count': 0,
        'outside_count': 0,
        'returned_count': 0,
    }
    candidates_raw = []
    if active == 'tavily':
        key = os.getenv('TAVILY_API_KEY', '').strip()
        if not key:
            raise RuntimeError(
                'Chưa có TAVILY_API_KEY. Chọn Tự động / Nguồn công khai, hoặc thêm khóa tại Kết nối & thư mục làm việc.'
            )
        try:
            candidates_raw = _discover_tavily(query, start, end, selected_domains, max_results, key)
        except RuntimeError:
            if provider != 'auto':
                raise
            active = 'public'
            diagnostics['warnings'].append(
                'Tavily hiện không phản hồi hợp lệ; đã chuyển sang các nguồn công khai không cần khóa.'
            )
        if not candidates_raw and provider == 'auto':
            active = 'public'
            if not diagnostics['warnings']:
                diagnostics['warnings'].append('Tavily chưa có kết quả; đã kiểm tra thêm nguồn công khai.')
    if active == 'public':
        from public_search import discover_public

        discovered = discover_public(query, start, end, selected_domains, max_results=max_results)
        candidates_raw = discovered.get('candidates', [])
        public_diagnostics = discovered.get('diagnostics') or {}
        diagnostics.update({k: v for k, v in public_diagnostics.items() if k != 'warnings'})
        diagnostics['warnings'].extend(public_diagnostics.get('warnings') or [])
    diagnostics['provider'] = active
    candidates, seen = [], set()
    for item in candidates_raw:
        if not isinstance(item, dict):
            continue
        try:
            url = canonical(item.get('url', ''))
        except ValueError:
            continue
        if url in seen or not _allowed_host(domain_of(url), selected_domains):
            continue
        seen.add(url)
        try:
            score = float(item.get('provider_score', item.get('score', 0)) or 0)
            score = max(0.0, min(score, 1.0)) if math.isfinite(score) else 0.0
        except (ValueError, TypeError):
            score = 0.0
        candidates.append(
            {
                'url': url,
                'title': str(item.get('title') or 'Tin chưa có tên')[:400],
                'summary': str(item.get('summary', item.get('content', '')) or '')[:1000],
                'provider_date_hint': str(
                    item.get('provider_date_hint') or item.get('published_date') or item.get('date') or ''
                )[:100]
                or None,
                'provider_score': score,
                'score': score,
                'official': official(url),
                'discovery_provider': item.get('discovery_provider') or active,
                'source_kind': 'legal' if domain_of(url) in _LEGAL_PORTALS else 'news',
            }
        )
        if len(candidates) >= min(max_results, 40):
            break
    diagnostics['candidate_count'] = len(candidates)
    results = []
    if candidates:
        with ThreadPoolExecutor(max_workers=min(6, len(candidates))) as pool:
            results = list(pool.map(lambda hit: _verify_hit(hit, start, end), candidates))
    diagnostics['outside_count'] = sum(x['date_status'] == 'outside' for x in results)
    findings = [x for x in results if x['date_status'] != 'outside']
    diagnostics['verified_count'] = sum(x['date_status'] == 'in_range' for x in findings)
    diagnostics['returned_count'] = len(findings)
    diagnostics['elapsed_seconds'] = round(time.monotonic() - began, 1)
    return SearchResults(findings, diagnostics)


def _normalised_title(title):
    value = unicodedata.normalize('NFKD', str(title).lower()).replace('đ', 'd')
    value = ''.join(ch for ch in value if not unicodedata.combining(ch))
    return ' '.join(re.findall(r'[a-z0-9]+|[\u3400-\u9fff]+', value))


def _story_key(hit):
    title = str(hit.get('title') or '')
    return frozenset(
        value.upper().replace('NĐ', 'ND').replace('QĐ', 'QD') for value in _LAW_ID.findall(title)
    )


def _same_story(left, right):
    a_ids, b_ids = _story_key(left), _story_key(right)
    if a_ids or b_ids:
        # A distinct decree/amendment must remain a distinct finding.
        return bool(a_ids and a_ids == b_ids)
    a = _normalised_title(left.get('title', ''))
    b = _normalised_title(right.get('title', ''))
    if not a or not b:
        return False
    if re.search(r'\b(luat|nghi dinh|thong tu|quyet dinh|nghi quyet)\b', a + ' ' + b):
        # No document number: do not collapse legal findings on vague titles.
        return False
    if a == b:
        return len(a) >= 18
    if set(re.findall(r'\b\d+\b', a)) != set(re.findall(r'\b\d+\b', b)):
        return False
    a_words, b_words = set(a.split()), set(b.split())
    common = a_words & b_words
    return (
        len(common) >= 6
        and len(common) / max(len(a_words | b_words), 1) >= 0.82
        and SequenceMatcher(None, a, b).ratio() >= 0.88
    )


def _impact_score(hit, query, seen_urls):
    title = _normalised_title(hit.get('title', ''))
    text = title + ' ' + _normalised_title(hit.get('summary', ''))
    score, reasons = 0.0, []
    if official(hit.get('url', '')):
        score += 30
        reasons.append('Ưu tiên nguồn cơ quan nhà nước; vẫn cần kiểm tra hiệu lực và từng luận điểm.')
    if hit.get('date_status') == 'in_range' and hit.get('date_verified'):
        score += 20
        reasons.append('Có ngày đăng gốc trong khoảng đã chọn.')
    else:
        reasons.append('Ngày đăng chưa được xác minh; không được gắn nhãn tin tuần này.')
    themes = (
        (
            ('trung quoc', 'chinese', 'china', '中资', '中国'),
            15,
            'Có nhắc đến Trung Quốc; cần đánh giá tác động tới nhà đầu tư.',
        ),
        (
            ('nghi dinh', 'thong tu', 'sua doi', 'hieu luc', 'quoc hoi', '法律', '修订'),
            12,
            'Có dấu hiệu thay đổi chính sách/pháp luật cần luật sư kiểm tra.',
        ),
        (
            (
                'ngoai hoi',
                'tai khoan von',
                'chuyen loi nhuan',
                'remittance',
                'capital account',
                '汇款',
                '资本',
            ),
            12,
            'Liên quan dòng vốn và tuân thủ ngân hàng.',
        ),
        (
            ('mua ban sap nhap', 'm a', 'co phan', 'von gop', 'acquisition', '并购'),
            10,
            'Liên quan giao dịch vốn hoặc M&A.',
        ),
        (
            ('khu cong nghiep', 'nang luong', 'ha tang', 'du an', 'industrial', 'infrastructure', '项目'),
            8,
            'Liên quan dự án, hạ tầng hoặc chuỗi cung ứng.',
        ),
        (('fdi', 'dau tu nuoc ngoai', 'foreign investment'), 8, 'Có liên quan đầu tư nước ngoài.'),
    )
    for terms, points, reason in themes:
        if any(
            (
                term in text
                if re.search(r'[\u3400-\u9fff]', term)
                else re.search(r'(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])', text)
            )
            for term in terms
        ):
            score += points
            reasons.append(reason)
    if query:
        query_words = set(_normalised_title(query).split())
        title_words = set(title.split())
        score += min(8, len(query_words & title_words))
    is_new = hit['url'] not in seen_urls
    score += 12 if is_new else 0
    reasons.append(
        'URL chưa có trong kho cục bộ; đây chỉ là chỉ báo mới với tòa soạn.'
        if is_new
        else 'URL đã có trong kho cục bộ; xem lại trước khi soạn bài trùng.'
    )
    try:
        provider_score = float(hit.get('provider_score', hit.get('score', 0)))
        if math.isfinite(provider_score):
            score += max(0, min(provider_score, 1)) * 5
    except (ValueError, TypeError):
        pass
    return round(score, 2), reasons, is_new


def cluster_and_rank(hits, query='', existing_urls=None):
    """Return transparent, conservative story groups, highest impact first.

    The representative is also exposed as flat source fields for existing UI
    callers. ``members``/``cluster_sources`` preserve original URLs and source
    evidence. This ranking is an editorial heuristic, never a legal conclusion
    or an investment recommendation. "New" means absent from the local archive.
    """
    seen_urls = set()
    for value in existing_urls or ():
        try:
            seen_urls.add(canonical(value))
        except ValueError:
            continue
    unique = {}
    for value in hits:
        if not isinstance(value, dict):
            continue
        try:
            url = canonical(value.get('url', ''))
        except ValueError:
            continue
        hit = dict(value, url=url, official=official(url))
        old = unique.get(url)
        if old is None or (bool(hit.get('date_verified')), len(hit.get('text') or '')) > (
            bool(old.get('date_verified')),
            len(old.get('text') or ''),
        ):
            unique[url] = hit
    clusters = []
    for hit in unique.values():
        target = next((group for group in clusters if _same_story(group[0], hit)), None)
        if target is None:
            clusters.append([hit])
        else:
            target.append(hit)
    ranked = []
    for group in clusters:
        scored = [(_impact_score(hit, query, seen_urls), hit) for hit in group]
        # A verified in-range member represents a recent cluster. An undated
        # official background page must not hide that event in the pending queue.
        scored.sort(
            key=lambda pair: (
                not (pair[1].get('date_verified') and pair[1].get('date_status') == 'in_range'),
                -pair[0][0],
                pair[1]['url'],
            )
        )
        (score, reasons, _), representative = scored[0]
        is_new = all(hit['url'] not in seen_urls for hit in group)
        if not is_new:
            # A syndicated new URL does not make an already collected story new.
            if representative['url'] not in seen_urls:
                score = round(score - 12, 2)
                reasons[-1] = 'Một nguồn trong cụm đã có trong kho; kiểm tra bài trùng.'
        members = [hit for _, hit in scored]
        ranked.append(
            dict(
                representative,
                representative=dict(representative),
                members=members,
                cluster_sources=members,
                cluster_size=len(members),
                score=score,
                rank_score=score,
                rationale=reasons,
                impact_reasons=reasons,
                novelty='new' if is_new else 'seen',
                is_new=is_new,
                has_official_source=any(official(hit['url']) for hit in members),
            )
        )
    return sorted(ranked, key=lambda item: (-item['rank_score'], item['url']))
