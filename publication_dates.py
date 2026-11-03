"""Conservative publication evidence from known original-news page templates.

These selectors are scoped to each site's article header, never the current
date in its masthead or related-story timestamps. Local visible dates are
interpreted in Vietnam only for these Vietnamese news templates. They establish
the page's original publication date, not the accuracy or current legal effect
of its contents. Generic metadata parsing remains the primary research gate.
"""

from __future__ import annotations

from datetime import datetime
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


TZ = ZoneInfo('Asia/Ho_Chi_Minh')
_DISALLOWED_LABEL = re.compile(
    r'cập\s*nhật|sửa\s*đổi|hiệu\s*lực|ban\s*hành|modified|updated|effective|issued', re.I
)
_LOCAL_DATE = re.compile(
    r'(?P<day>\d{1,2})(?P<sep>[/\-])(?P<month>\d{1,2})(?P=sep)(?P<year>\d{4})'
    r'\s*[,]?\s*(?:-\s*)?(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?'
)
_TEMPLATES = {
    'cafef.vn': ('.totalcontentdetail .dateandcat [data-role="publishdate"][itemprop="datePublished"]',),
    'baodautu.vn': ('.author-share-top .post-time',),
    'baochinhphu.vn': ('article.detail-mcontent .detail-time [data-role="publishdate"]',),
    'vnexpress.net': ('.page-detail .sidebar-1 .header-content > .date',),
    'vietnamplus.vn': ('.article > .article__meta > time.time[data-friendly="false"]',),
}


def _date_from_known_header(tag, host):
    text = ' '.join(tag.get_text(' ', strip=True).split())
    if _DISALLOWED_LABEL.search(text):
        return None, None, None
    # CafeF puts an explicit UTC offset on a span; the Open Graph equivalent
    # currently omits it. Accept the semantic, offset-bearing span directly.
    raw = tag.get('datetime') or tag.get('content')
    if raw:
        try:
            timestamp = datetime.fromisoformat(raw.strip().replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return None, None, None
        if timestamp.tzinfo is None:
            return None, None, None
        return timestamp.astimezone(TZ).date().isoformat(), raw, 'explicit_offset'
    # Only the exact known header date is admissible. Other text dates (including
    # dates embedded in an article about a law) are never considered evidence.
    match = _LOCAL_DATE.search(text)
    if not match:
        return None, None, None
    prefix, suffix = text[: match.start()].strip(), text[match.end() :].strip()
    prefix = re.sub(r'^Thứ\s+(?:hai|ba|tư|năm|sáu|bảy)\s*,?\s*|^Chủ\s+nhật\s*,?\s*', '', prefix, flags=re.I)
    prefix = prefix.strip(' -–,')
    if prefix or suffix not in ('', '(GMT+7)', '(GMT+07:00)'):
        return None, None, None
    # VnExpress's visible timestamp explicitly labels the offset. Require it
    # rather than assuming the timezone from a generic span.date element.
    if host == 'vnexpress.net' and not suffix:
        return None, None, None
    try:
        timestamp = datetime(
            *(int(match.group(part)) for part in ('year', 'month', 'day', 'hour', 'minute')),
            int(match.group('second') or 0),
            tzinfo=TZ,
        )
    except (ValueError, OverflowError):
        return None, None, None
    return timestamp.date().isoformat(), text, 'trusted_vietnam_article_header'


def source_publication_evidence(soup, url):
    """Return (ISO date, evidence, status) from a known original-news header.

    Use as fallback when generic original-publication metadata is absent. Do
    not replace a generic metadata conflict with this result. RSS/index dates,
    legal portals and arbitrary unlabelled time elements are not supported.
    """
    try:
        host = (urlsplit(url).hostname or '').lower().removeprefix('www.')
    except (TypeError, ValueError, AttributeError):
        return None, None, 'unknown'
    candidates = []
    for selector in _TEMPLATES.get(host, ()):
        for tag in soup.select(selector):
            published, raw, timezone_basis = _date_from_known_header(tag, host)
            if published:
                candidates.append(
                    {
                        'kind': 'page_publication_label',
                        'selector': selector,
                        'value': raw,
                        'date': published,
                        'timezone': 'Asia/Ho_Chi_Minh',
                        'timezone_basis': timezone_basis,
                    }
                )
    dates = {item['date'] for item in candidates}
    if len(dates) == 1:
        evidence = dict(candidates[0])
        evidence['note'] = (
            'Ngày đăng gốc ở đầu bài trên trang nguồn; chưa xác minh nội dung hay hiệu lực pháp luật.'
        )
        return evidence['date'], evidence, 'verified'
    if len(dates) > 1:
        return (
            None,
            {
                'kind': 'conflicting_metadata',
                'candidates': candidates,
                'note': 'Các nhãn ngày đăng gốc mâu thuẫn; cần biên tập viên xác minh.',
            },
            'conflicting',
        )
    return None, None, 'unknown'
