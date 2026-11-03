from datetime import date
from unittest.mock import Mock, patch
import unittest

import requests

import public_search as public


RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>China investment in an industrial park</title>
<link>https://vnexpress.net/china-investment-123.html?utm_source=feed</link>
<description><![CDATA[<p>Original investment report</p>]]></description>
<pubDate>Thu, 22 Oct 2026 10:00:00 +0700</pubDate></item>
<item><title>Unreviewed source investment</title><link>https://evil.example/article</link></item>
<item><title>Opaque aggregator investment</title><link>https://news.google.com/rss/articles/opaque</link></item>
</channel></rss>"""


class PublicSearchTests(unittest.TestCase):
    def setUp(self):
        self.start, self.end = date(2026, 10, 17), date(2026, 10, 23)

    def _discover(self, query='đầu tư Trung Quốc', domains=None, max_results=20):
        return public.discover_public(
            query,
            self.start,
            self.end,
            domains or ['vnexpress.net'],
            max_results,
        )

    def test_rss_dates_remain_unverified_discovery_hints(self):
        entries = public._parse_feed(RSS, 'https://vnexpress.net/rss/kinh-doanh.rss')
        self.assertEqual(entries[0]['provider_date_hint'], 'Thu, 22 Oct 2026 10:00:00 +0700')
        self.assertNotIn('published', entries[0])
        self.assertNotIn('date_verified', entries[0])
        self.assertEqual(entries[0]['summary'], 'Original investment report')

    def test_atom_uses_published_never_modified(self):
        feed = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
        <title>Bank investment</title><link href="https://vnexpress.net/article-123.html"/>
        <updated>2026-10-23T00:00:00Z</updated><published>2020-01-01T00:00:00Z</published>
        </entry></feed>"""
        hit = public._parse_feed(feed, 'https://vnexpress.net/feed')[0]
        self.assertEqual(hit['provider_date_hint'], '2020-01-01T00:00:00Z')

    def test_feed_rejects_html_and_entity_declarations(self):
        for raw in (b'<html><body>Denied</body></html>', b'<!DOCTYPE rss><rss/>', b'broken XML'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                public._parse_feed(raw, 'https://vnexpress.net/')

    def test_select_domains_deduplicates_and_rejects_opaque_or_unapproved_urls(self):
        entries = public._parse_feed(RSS, 'https://vnexpress.net/')
        with patch.object(public, '_read_source', return_value=('vnexpress.net', entries)):
            result = self._discover()
        self.assertEqual(len(result['candidates']), 1)
        hit = result['candidates'][0]
        self.assertEqual(hit['url'], 'https://vnexpress.net/china-investment-123.html')
        self.assertEqual(hit['discovery_provider'], 'publisher_rss')
        self.assertNotIn('date_verified', hit)
        self.assertGreater(hit['provider_score'], 0)

    def test_selected_domain_does_not_admit_other_approved_publishers(self):
        entries = [{'url': 'https://cafef.vn/investment-123.chn', 'title': 'China investment'}]
        with patch.object(public, '_read_source', return_value=('vnexpress.net', entries)):
            self.assertEqual(self._discover()['candidates'], [])

    def test_partial_failure_preserves_candidates_and_sanitizes_errors(self):
        entries = public._parse_feed(RSS, 'https://vnexpress.net/')

        def reader(source, deadline):
            if 'phap-luat' in source[2]:
                raise requests.RequestException('Bearer super-secret-key should never surface')
            return source[0], entries

        with patch.object(public, '_read_source', side_effect=reader):
            result = self._discover()
        self.assertEqual(len(result['candidates']), 1)
        self.assertTrue(result['diagnostics']['warnings'])
        self.assertNotIn('super-secret', str(result))

    def test_partial_endpoint_failure_does_not_label_whole_publisher_unavailable(self):
        entries = public._parse_feed(RSS, 'https://vnexpress.net/')

        def reader(source, deadline):
            if 'phap-luat' in source[2]:
                raise public.PublicSourceError('http_error', 503)
            return source[0], entries

        with patch.object(public, '_read_source', side_effect=reader):
            result = self._discover()
        diagnostics = result['diagnostics']
        self.assertEqual(diagnostics['fully_failed_domains'], [])
        self.assertEqual(diagnostics['partial_domains'], ['vnexpress.net'])
        self.assertEqual(diagnostics['successful_domain_count'], 1)
        self.assertEqual(diagnostics['failed_sources'][0]['status_code'], 503)
        self.assertIn('http_error', diagnostics['failed_sources'][0]['reason'])
        self.assertTrue(any('vẫn dùng các mục đã đọc được' in text for text in diagnostics['warnings']))

    def test_timeout_tls_and_dns_have_distinct_sanitized_diagnostics(self):
        cases = (
            (requests.Timeout('secret body'), 'timeout'),
            (requests.exceptions.SSLError('secret key'), 'tls_error'),
            (public.PublicSourceError('dns_unverified'), 'dns_unverified'),
        )
        for error, reason in cases:
            with self.subTest(reason=reason), patch.object(public, '_read_source', side_effect=error):
                diagnostics = self._discover()['diagnostics']
            self.assertTrue(all(item['reason'] == reason for item in diagnostics['failed_sources']))
            self.assertEqual(diagnostics['fully_failed_domains'], ['vnexpress.net'])
            self.assertNotIn('secret', str(diagnostics))

    def test_waf_rejection_with_http_200_is_not_a_successful_index(self):
        raw = b'<html><head><title>Request Rejected</title></head><body>Rejected.</body></html>'
        with patch.object(public, '_request', return_value=(raw, 'https://vnexpress.net/')):
            with self.assertRaises(public.PublicSourceError) as caught:
                public._read_source(('vnexpress.net', 'index', 'https://vnexpress.net/'), 999)
        self.assertEqual(caught.exception.reason, 'access_blocked')

    def test_no_matches_is_distinct_from_provider_failure(self):
        entries = [{'url': 'https://vnexpress.net/football-123.html', 'title': 'Football season news'}]
        with patch.object(public, '_read_source', return_value=('vnexpress.net', entries)):
            result = self._discover()
        self.assertEqual(result['candidates'], [])
        self.assertTrue(result['diagnostics']['providers_succeeded'])
        self.assertFalse(result['diagnostics']['failed_sources'])

    def test_empty_index_is_not_reported_as_successful_source(self):
        with patch.object(public, '_read_source', return_value=('vnexpress.net', [])):
            result = self._discover()
        self.assertEqual(result['diagnostics']['providers_succeeded'], [])
        self.assertTrue(result['diagnostics']['failed_sources'])
        self.assertTrue(
            all(source['reason'] == 'empty_index' for source in result['diagnostics']['failed_sources'])
        )
        self.assertTrue(result['diagnostics']['warnings'])

    def test_unsupported_source_reported_without_unselected_requests(self):
        with patch.object(public, '_read_source') as reader:
            result = self._discover(domains=['customs.gov.vn'])
        reader.assert_not_called()
        self.assertEqual(result['diagnostics']['unsupported_domains'], ['customs.gov.vn'])
        self.assertIn('customs.gov.vn', result['diagnostics']['warnings'][0])

    def test_does_not_filter_originals_by_a_feed_date(self):
        entries = [
            {
                'url': 'https://vnexpress.net/china-investment-123.html',
                'title': 'China investment',
                'provider_date_hint': '2000-01-01',
            }
        ]
        with patch.object(public, '_read_source', return_value=('vnexpress.net', entries)):
            result = self._discover()
        self.assertEqual(len(result['candidates']), 1)

    def test_chinese_alias_accentless_query_and_category_or_matching(self):
        score, matches = public.relevance_score('中国投资', 'Doanh nghiệp Trung Quốc đầu tư nhà máy')
        self.assertGreater(score, 0)
        self.assertIn('trung quoc', matches)
        self.assertGreater(public.relevance_score('khu cong nghiep', 'Mở rộng khu công nghiệp mới')[0], 0)
        self.assertGreater(
            public.relevance_score(
                'luật nghị định thông tư mới đầu tư nước ngoài doanh nghiệp Việt Nam',
                'Nghị định sửa đổi điều kiện kinh doanh',
            )[0],
            0,
        )
        self.assertEqual(public.relevance_score('đầu tư Trung Quốc', 'Giải bóng đá Việt Nam')[0], 0)

    def test_explicit_china_requires_country_and_financial_context(self):
        query = 'doanh nghiệp Trung Quốc đầu tư Việt Nam FDI nhà máy dự án'
        rejected = (
            'Sau IPO doanh nghiệp lấy gì để giữ chân nhà đầu tư',
            'Doanh nghiệp đề xuất đầu tư dự án điện gió tại Đắk Lắk',
            'Ca sĩ Đông Đào đầu tư thua lỗ nhà máy nước với đối tác Trung Quốc',
            'Phát hiện 129 đối tượng chủ yếu người Trung Quốc lập ổ lừa đảo online',
            'Doanh nghiệp Trung Quốc tổ chức tiệc kỷ niệm ngày thành lập',
        )
        for title in rejected:
            with self.subTest(title=title):
                self.assertEqual(public.relevance_score(query, title)[0], 0)
        for title in (
            'Ngành tài chính tham vấn đối tác Trung Quốc trước thềm APEC',
            'Doanh nghiệp Trung Quốc đầu tư nhà máy tại Việt Nam',
            'Đẩy mạnh thương mại Việt Nam Trung Quốc',
        ):
            with self.subTest(title=title):
                self.assertGreater(public.relevance_score(query, title)[0], 0)

    def test_country_constraint_can_match_summary_and_crime_must_be_requested(self):
        self.assertGreater(
            public.relevance_score(
                'đầu tư Trung Quốc',
                'Khởi công nhà máy mới',
                'Nhà đầu tư Trung Quốc góp vốn',
            )[0],
            0,
        )

    def test_rental_is_not_tax_and_incidental_global_china_is_not_fdi(self):
        query = 'doanh nghiệp Trung Quốc đầu tư Việt Nam FDI nhà máy dự án'
        self.assertEqual(
            public.relevance_score(
                query,
                'Cô gái và chồng hờ tổ chức nhập cảnh trái phép',
                'Người Trung Quốc thuê nhà tại Việt Nam',
            )[0],
            0,
        )
        self.assertEqual(
            public.relevance_score(
                query,
                'Thỏa thuận diesel Mỹ Nga khó kéo giá nhiên liệu xuống',
                'Nga xuất khẩu nhiên liệu. Lãnh đạo Mỹ gặp lãnh đạo Trung Quốc.',
            )[0],
            0,
        )
        self.assertGreater(
            public.relevance_score(
                query,
                'Trung Quốc điều chỉnh thuế nhập khẩu',
            )[0],
            0,
        )
        self.assertGreater(
            public.relevance_score(
                'lừa đảo đầu tư Trung Quốc',
                'Điều tra lừa đảo đầu tư của đối tượng Trung Quốc',
            )[0],
            0,
        )

    def test_focused_industrial_parks_require_complete_topic_not_shared_syllables(self):
        for title in (
            'Giá xăng dầu giảm tại các khu vực công cộng',
            'Đẩy nhanh công trình hạ tầng khu vực phục vụ APEC',
            'Ngành dược công bố kết quả doanh nghiệp tại khu vực miền Bắc',
            'Phát triển khu công nghệ cao tại miền Bắc',
        ):
            with self.subTest(title=title):
                self.assertEqual(public.relevance_score('khu công nghiệp', title)[0], 0)
        for query, title in (
            ('khu công nghiệp', 'Triển khai dự án KCN Sóc Sơn'),
            ('KCN', 'Mở rộng khu công nghiệp Viglacera'),
            ('工业园区', 'Vietnam opens a new industrial park'),
            ('khu cong nghiep moi', 'Thêm khu công nghiệp xanh tại Bắc Ninh'),
            ('industrial park', 'Mở rộng KCN tại miền Bắc'),
        ):
            with self.subTest(query=query, title=title):
                self.assertGreater(public.relevance_score(query, title)[0], 0)
        self.assertEqual(public.relevance_score('kcn', 'Doanh nghiệp SKCN công bố kết quả')[0], 0)

    def test_long_infrastructure_category_retains_alternative_topics(self):
        query = 'dự án mới Việt Nam khu công nghiệp năng lượng giao thông trung tâm tài chính'
        self.assertGreater(public.relevance_score(query, 'Dự án điện gió mới bổ sung nguồn năng lượng')[0], 0)

    def test_dica_alias_matches_capital_account_not_generic_banking(self):
        for query, title in (
            ('DICA', 'Hướng dẫn mở tài khoản vốn đầu tư trực tiếp'),
            ('tài khoản vốn', 'Doanh nghiệp sử dụng DICA chuyển lợi nhuận'),
            ('DICA', 'New rules for direct investment capital accounts'),
        ):
            with self.subTest(query=query, title=title):
                self.assertGreater(public.relevance_score(query, title)[0], 0)
        self.assertEqual(public.relevance_score('DICA', 'Ngân hàng giảm lãi suất cho vay')[0], 0)

    def test_index_accepts_document_ids_without_inventing_publication_dates(self):
        raw = """<html><nav><a href="/?docid=1">A very long navigation label for investment</a></nav>
        <a href="/?pageid=27160&amp;docid=99">Quy định mới về đầu tư nước ngoài và nhà máy</a>
        <a href="/category">Danh mục đầu tư nước ngoài và nhà máy</a></html>""".encode()
        hits = public._parse_index(raw, 'https://vanban.chinhphu.vn/')
        self.assertEqual(len(hits), 1)
        self.assertIn('docid=99', hits[0]['url'])
        self.assertIsNone(hits[0]['provider_date_hint'])

    def test_request_closes_and_bounds_response(self):
        response = Mock(is_redirect=False, is_permanent_redirect=False)
        response.iter_content.return_value = [b'a' * (public._MAX_BYTES + 1)]
        with (
            patch('research._assert_public_dns'),
            patch.object(public.requests, 'get', return_value=response),
        ):
            with self.assertRaises(ValueError):
                public._request('https://vnexpress.net/rss/kinh-doanh.rss', public.time.monotonic() + 5)
        response.close.assert_called_once()

    def test_transient_connection_retries_once_with_same_global_deadline(self):
        response = Mock(is_redirect=False, is_permanent_redirect=False, status_code=200)
        response.iter_content.return_value = [RSS]
        with (
            patch('research._assert_public_dns'),
            patch.object(
                public.requests,
                'get',
                side_effect=[requests.Timeout('temporary'), response],
            ) as request,
        ):
            data, _ = public._request('https://vnexpress.net/rss/kinh-doanh.rss', public.time.monotonic() + 5)
        self.assertEqual(data, RSS)
        self.assertEqual(request.call_count, 2)
        self.assertTrue(all(call.kwargs['allow_redirects'] is False for call in request.call_args_list))
        response.close.assert_called_once()

    def test_transient_http_error_retries_then_closes_both_responses(self):
        temporary = Mock(is_redirect=False, is_permanent_redirect=False, status_code=503)
        good = Mock(is_redirect=False, is_permanent_redirect=False, status_code=200)
        good.iter_content.return_value = [RSS]
        with (
            patch('research._assert_public_dns'),
            patch.object(
                public.requests,
                'get',
                side_effect=[temporary, good],
            ) as request,
        ):
            data, _ = public._request('https://vnexpress.net/rss/kinh-doanh.rss', public.time.monotonic() + 5)
        self.assertEqual(data, RSS)
        self.assertEqual(request.call_count, 2)
        temporary.close.assert_called_once()
        good.close.assert_called_once()

    def test_tls_failure_and_unverified_dns_do_not_retry_or_disclose_response(self):
        with (
            patch('research._assert_public_dns'),
            patch.object(
                public.requests,
                'get',
                side_effect=requests.exceptions.SSLError('secret'),
            ) as request,
        ):
            with self.assertRaises(requests.exceptions.SSLError):
                public._request('https://vnexpress.net/rss/kinh-doanh.rss', public.time.monotonic() + 5)
            self.assertEqual(request.call_count, 1)
        with (
            patch('research._assert_public_dns', side_effect=ValueError('secret')),
            patch.object(
                public.requests,
                'get',
            ) as request,
        ):
            with self.assertRaises(public.PublicSourceError) as caught:
                public._request('https://vnexpress.net/rss/kinh-doanh.rss', public.time.monotonic() + 5)
            self.assertEqual(caught.exception.reason, 'dns_unverified')
            self.assertNotIn('secret', str(caught.exception))
            request.assert_not_called()

    def test_redirect_cannot_escape_publisher_or_use_private_network(self):
        for target in ('https://evil.example/feed', 'http://127.0.0.1/rss', 'https://cafef.vn/feed'):
            response = Mock(is_redirect=True, is_permanent_redirect=False, headers={'Location': target})
            with (
                self.subTest(target=target),
                patch('research._assert_public_dns'),
                patch.object(
                    public.requests,
                    'get',
                    return_value=response,
                ) as request,
            ):
                with self.assertRaises(ValueError):
                    public._request('https://vnexpress.net/rss/kinh-doanh.rss', public.time.monotonic() + 5)
                self.assertEqual(request.call_count, 1)
                response.close.assert_called_once()

    def test_bad_input_rejected_before_network(self):
        for query, domains, limit in [
            ('x', ['vnexpress.net'], 20),
            ('test', ['evil.example'], 20),
            ('test', ['vnexpress.net'], True),
        ]:
            with (
                self.subTest(query=query, domains=domains, limit=limit),
                patch.object(
                    public,
                    '_read_source',
                ) as reader,
                self.assertRaises(ValueError),
            ):
                self._discover(query, domains, limit)
            reader.assert_not_called()


if __name__ == '__main__':
    unittest.main()
