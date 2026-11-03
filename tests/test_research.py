"""Offline fixtures for original-page dates, strict discovery and story grouping."""

from datetime import date
import os
import unittest
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup
import requests

import research


def soup(value):
    return BeautifulSoup(value, 'html.parser')


def page(published=None, text='Bằng chứng nguồn. ' * 30):
    return {
        'published': published,
        'text': text,
        'date_verified': bool(published),
        'date_evidence': {'kind': 'page_metadata', 'value': published} if published else None,
        'date_status': 'verified' if published else 'unknown',
    }


def hit(url, title, **kwargs):
    return dict(url=url, title=title, summary='', **kwargs)


class PublicationDateTests(unittest.TestCase):
    def test_inclusive_seven_calendar_days(self):
        self.assertEqual(
            research.default_date_range(date(2026, 10, 22)), (date(2026, 10, 16), date(2026, 10, 22))
        )
        self.assertEqual(
            research.default_date_range(date(2026, 1, 2)), (date(2025, 12, 27), date(2026, 1, 2))
        )

    def test_timestamp_is_converted_to_vietnam_day_at_midnight(self):
        self.assertEqual(
            research._meta_date(
                soup('<meta property="article:published_time" content="2026-10-15T17:00:00Z">')
            ),
            '2026-10-16',
        )
        self.assertEqual(
            research._meta_date(
                soup('<meta property="article:published_time" content="2026-10-22T16:59:59Z">')
            ),
            '2026-10-22',
        )
        self.assertEqual(
            research._meta_date(
                soup('<meta property="article:published_time" content="2026-10-22T17:00:00Z">')
            ),
            '2026-10-23',
        )

    def test_modified_dates_legal_dates_and_unlabelled_times_are_not_publication(self):
        value = """<meta property="og:updated_time" content="2026-10-22">
          <meta name="date" content="2026-10-22">
          <meta itemprop="dateModified" content="2026-10-22">
          <meta name="dateIssued" content="2026-10-22">
          <time datetime="2026-10-22T09:00:00+07:00">22/10/2026</time>
          <script type="application/ld+json">{"@type":"Legislation", "datePublished":"2026-10-22",
          "legislationDate":"2026-10-22", "dateModified":"2026-10-22"}</script>"""
        self.assertIsNone(research._meta_date(soup(value)))

    def test_json_ld_article_date_and_explicit_time_are_accepted(self):
        value = """<script type="application/ld+json">{"@graph":[{"@type":"WebSite",
          "datePublished":"2020-01-01"},{"@type":"NewsArticle",
          "datePublished":"2026-10-22T00:01:00+07:00","dateModified":"2026-10-23"}]}</script>
          <time itemprop="datePublished" datetime="2026-10-22T00:01:00+07:00"></time>"""
        self.assertEqual(research._meta_date(soup(value)), '2026-10-22')

    def test_related_article_json_ld_is_not_this_pages_publication(self):
        value = """<script type="application/ld+json">{"@graph":[
          {"@type":"NewsArticle","url":"https://vnexpress.net/related", "datePublished":"2026-10-22"},
          {"@type":"NewsArticle","url":"https://vnexpress.net/original", "datePublished":"2026-10-01"}
          ]}</script>"""
        actual, _, _ = research._publication_evidence(soup(value), 'https://vnexpress.net/original')
        self.assertEqual(actual, '2026-10-01')

    def test_conflicting_metadata_requires_human_verification(self):
        value = """<meta property="article:published_time" content="2026-10-22">
          <meta itemprop="datePublished" content="2026-10-01">"""
        actual, evidence, status = research._publication_evidence(soup(value))
        self.assertIsNone(actual)
        self.assertEqual(status, 'conflicting')
        self.assertEqual(evidence['kind'], 'conflicting_metadata')

    def test_invalid_ambiguous_and_timezone_free_dates_are_not_assumed(self):
        for value in ('2026-02-30', '22/10/2026', '2026-10-22T01:00:00', 'October 2026', ''):
            with self.subTest(value=value):
                self.assertIsNone(research._parse_publication_date(value))

    def test_malformed_json_does_not_break_other_metadata(self):
        value = """<script type="application/ld+json">{broken</script>
          <meta name="pubdate" content="2026-10-22">"""
        self.assertEqual(research._meta_date(soup(value)), '2026-10-22')


class URLAndFetchTests(unittest.TestCase):
    def test_tracking_removed_identifiers_preserved_and_order_stable(self):
        a = 'https://WWW.vanban.chinhphu.vn:443/?utm_source=mail&docid=216524&classid=1#top'
        b = 'https://vanban.chinhphu.vn/?classid=1&docid=216524&fbclid=tracker'
        expected = 'https://vanban.chinhphu.vn/?classid=1&docid=216524'
        self.assertEqual(research.canonical(a), expected)
        self.assertEqual(research.canonical(b), expected)
        self.assertNotEqual(
            research.canonical('https://vanban.chinhphu.vn/?docid=1'),
            research.canonical('https://vanban.chinhphu.vn/?docid=2'),
        )

    def test_private_userinfo_unapproved_and_malformed_urls_blocked(self):
        for value in (
            'http://127.0.0.1/x',
            'http://[::1]/',
            'https://user:secret@vnexpress.net/a',
            'https://vnexpress.net.evil.test/a',
            'file:///etc/passwd',
            'https://vnexpress.net:8080/a',
            'https://vnexpress.net/\r\nX:a',
            'https://vnexpress.net\\@evil.test/a',
            'https://vnexpress.net:bad/a',
        ):
            with self.subTest(value=value):
                self.assertRaises(ValueError, research.canonical, value)

    def test_official_domain_matching_has_label_boundary(self):
        self.assertTrue(research.official('https://vanban.chinhphu.vn/a'))
        self.assertFalse(research.official('https://chinhphu.vn.evil.test/a'))
        self.assertFalse(research.official('https://cafef.vn/a'))

    @patch('research.socket.getaddrinfo')
    def test_fetch_dns_private_rebinding_target_blocked(self, resolve):
        resolve.return_value = [(2, 1, 6, '', ('127.0.0.1', 0))]
        with patch('research.requests.get') as get:
            self.assertRaises(ValueError, research.fetch_evidence, 'https://chinhphu.vn/a')
            get.assert_not_called()

    @patch('research._assert_public_dns')
    @patch('research.requests.get')
    def test_fetch_captures_original_metadata_and_closes_response(self, get, _dns):
        response = Mock()
        response.is_redirect = response.is_permanent_redirect = False
        response.headers = {'Content-Type': 'text/html; charset=utf-8'}
        response.encoding = 'utf-8'
        raw = (
            '<meta property="article:published_time" content="2026-10-22">'
            '<article>' + ('Nội dung nguồn chính thức có thông tin cần kiểm tra. ' * 20) + '</article>'
        )
        response.iter_content.return_value = [raw.encode()]
        get.return_value = response
        actual = research.fetch_evidence('https://chinhphu.vn/a')
        self.assertTrue(actual['date_verified'])
        self.assertEqual(actual['published'], '2026-10-22')
        self.assertIn('chính thức', actual['text'])
        self.assertEqual(actual['date_evidence']['kind'], 'page_metadata')
        response.close.assert_called_once()
        self.assertFalse(get.call_args.kwargs['allow_redirects'])

    @patch('research._assert_public_dns')
    @patch('research.requests.get')
    def test_fetch_redirects_are_never_followed(self, get, _dns):
        response = Mock()
        response.is_redirect = True
        get.return_value = response
        self.assertRaises(ValueError, research.fetch_evidence, 'https://chinhphu.vn/a')
        response.close.assert_called_once()

    @patch('research.fetch_evidence')
    def test_legacy_fetch_tuple_rejects_insufficient_extraction(self, fetch):
        fetch.return_value = page('2026-10-22')
        self.assertEqual(
            research.fetch_content('https://chinhphu.vn/a'), (fetch.return_value['text'], '2026-10-22')
        )
        fetch.return_value = dict(page(None, 'short'), extraction_error='Cần kiểm tra thủ công.')
        self.assertRaises(ValueError, research.fetch_content, 'https://chinhphu.vn/a')


class SearchGateTests(unittest.TestCase):
    def setUp(self):
        self.start, self.end = date(2026, 10, 16), date(2026, 10, 22)

    @patch('research.fetch_evidence')
    @patch('research.requests.post')
    def test_original_publication_overrides_new_provider_dates_and_unknown_stays_pending(self, post, fetch):
        post.return_value.json.return_value = {
            'results': [
                {
                    'url': 'https://vnexpress.net/old',
                    'title': 'Updated old original',
                    'published_date': '2026-10-22',
                },
                {'url': 'https://vnexpress.net/new', 'title': 'New original', 'published_date': '2026-10-01'},
                {
                    'url': 'https://chinhphu.vn/unknown',
                    'title': 'Unknown original',
                    'published_date': '2026-10-22',
                },
            ]
        }
        fetch.side_effect = lambda url: page(
            {'https://vnexpress.net/old': '2026-10-01', 'https://vnexpress.net/new': '2026-10-22'}.get(url)
        )
        with patch.dict(os.environ, {'TAVILY_API_KEY': 'private-test-key'}):
            actual = research.search_news('đầu tư Trung Quốc', self.start, self.end)
        self.assertEqual([value['date_status'] for value in actual], ['in_range', 'unknown'])
        self.assertEqual(actual[1]['published'], None)
        self.assertEqual(actual[1]['provider_date_hint'], '2026-10-22')
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['start_date'], '2026-10-15')
        self.assertEqual(payload['end_date'], '2026-10-23')
        self.assertNotIn('api_key', payload)
        self.assertTrue(payload['include_published_date'])
        self.assertFalse(payload['filter_by_published_date'])
        self.assertEqual(payload['include_domains_mode'], 'restrict')

    @patch('research.fetch_evidence')
    @patch('research.requests.post')
    def test_both_boundaries_included_and_outside_excluded(self, post, fetch):
        dates = ['2026-10-15', '2026-10-16', '2026-10-22', '2026-10-23']
        post.return_value.json.return_value = {
            'results': [{'url': 'https://vnexpress.net/' + value, 'title': value} for value in dates]
        }
        fetch.side_effect = lambda url: page(url.rsplit('/', 1)[-1])
        with patch.dict(os.environ, {'TAVILY_API_KEY': 'private-test-key'}):
            actual = research.search_news('đầu tư', self.start, self.end)
        self.assertEqual([value['published'] for value in actual], dates[1:3])

    @patch('research.fetch_evidence', side_effect=ValueError('secret should never surface'))
    @patch('research.requests.post')
    def test_verification_failure_is_pending_with_sanitized_message(self, post, _fetch):
        post.return_value.json.return_value = {'results': [{'url': 'https://chinhphu.vn/a', 'title': 'Tin'}]}
        with patch.dict(os.environ, {'TAVILY_API_KEY': 'private-test-key'}):
            actual = research.search_news('đầu tư', self.start, self.end)
        self.assertEqual(actual[0]['date_status'], 'unknown')
        self.assertNotIn('secret', actual[0]['verification_error'])

    @patch('research.fetch_evidence')
    @patch('research.requests.post')
    def test_selected_domains_rechecked_and_tracking_duplicates_fetched_once(self, post, fetch):
        post.return_value.json.return_value = {
            'results': [
                {'url': 'https://cafef.vn/story', 'title': 'Excluded'},
                {'url': 'https://chinhphu.vn/story?utm_source=a', 'title': 'First'},
                {'url': 'https://chinhphu.vn/story?fbclid=b', 'title': 'Duplicate'},
                {'url': 'https://chinhphu.vn.evil.test/story', 'title': 'Unsafe'},
            ]
        }
        fetch.return_value = page('2026-10-22')
        with patch.dict(os.environ, {'TAVILY_API_KEY': 'private-test-key'}):
            actual = research.search_news('đầu tư', self.start, self.end, domains=['chinhphu.vn'])
        self.assertEqual(len(actual), 1)
        fetch.assert_called_once_with('https://chinhphu.vn/story')

    @patch('research.fetch_evidence')
    @patch('research.requests.post')
    def test_legal_portal_is_flagged_without_guessing_legal_fields(self, post, fetch):
        post.return_value.json.return_value = {
            'results': [
                {'url': 'https://vanban.chinhphu.vn/?docid=216524', 'title': 'Văn bản'},
                {'url': 'https://baochinhphu.vn/news', 'title': 'Bản tin pháp luật'},
            ]
        }
        fetch.return_value = page(None)
        with patch.dict(os.environ, {'TAVILY_API_KEY': 'private-test-key'}):
            actual = research.search_news('nghị định', self.start, self.end)
        self.assertEqual([item['source_kind'] for item in actual], ['legal', 'news'])
        self.assertNotIn('legal_json', actual[0])

    @patch('research.requests.post')
    def test_invalid_input_never_calls_provider(self, post):
        for kwargs in (
            {'query': ''},
            {'query': 'x'},
            {'query': 'a' * 501},
            {'start': date(2026, 10, 23)},
            {'domains': []},
            {'domains': ['evil.test']},
            {'max_results': 0},
            {'max_results': True},
        ):
            params = dict(query='đầu tư', start=self.start, end=self.end)
            params.update(kwargs)
            with self.subTest(kwargs=kwargs):
                self.assertRaises(ValueError, research.search_news, **params)
        post.assert_not_called()

    @patch('research.requests.post', side_effect=requests.HTTPError('Bearer private-test-key'))
    def test_provider_error_does_not_expose_key(self, _post):
        with patch.dict(os.environ, {'TAVILY_API_KEY': 'private-test-key'}):
            with self.assertRaises(RuntimeError) as caught:
                research.search_news('đầu tư', self.start, self.end, provider='tavily')
        self.assertNotIn('private-test-key', str(caught.exception))

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_key_has_actionable_error(self):
        self.assertRaisesRegex(
            RuntimeError,
            'TAVILY_API_KEY',
            research.search_news,
            'đầu tư',
            self.start,
            self.end,
            provider='tavily',
        )


class ClusteringTests(unittest.TestCase):
    def test_tracking_duplicate_collapsed_and_all_original_sources_retained(self):
        hits = [
            hit('https://cafef.vn/a?utm_source=mail', 'Khởi công nhà máy năng lượng xanh tại Hải Phòng'),
            hit('https://cafef.vn/a?fbclid=xx', 'Khởi công nhà máy năng lượng xanh tại Hải Phòng'),
            hit('https://baodautu.vn/b', 'Khởi công nhà máy năng lượng xanh tại Hải Phòng'),
        ]
        actual = research.cluster_and_rank(hits)
        self.assertEqual(len(actual), 1)
        self.assertEqual(actual[0]['cluster_size'], 2)
        self.assertEqual(len(actual[0]['cluster_sources']), 2)
        self.assertEqual(actual[0]['representative']['url'], actual[0]['url'])

    def test_different_legal_numbers_do_not_merge_and_same_instrument_does(self):
        hits = [
            hit('https://chinhphu.vn/a', 'Nghị định 10/2026/NĐ-CP quy định đầu tư nước ngoài'),
            hit('https://chinhphu.vn/b', 'Nghị định 11/2026/NĐ-CP quy định đầu tư nước ngoài'),
            hit('https://cafef.vn/c', 'Tìm hiểu Nghị định 10/2026/NĐ-CP'),
        ]
        actual = research.cluster_and_rank(hits)
        self.assertEqual(len(actual), 2)
        self.assertEqual(sorted(item['cluster_size'] for item in actual), [1, 2])

    def test_legal_document_query_identifiers_do_not_disappear(self):
        actual = research.cluster_and_rank(
            [
                hit('https://vanban.chinhphu.vn/?docid=1', 'Nghị định mới về đầu tư'),
                hit('https://vanban.chinhphu.vn/?docid=2', 'Nghị định mới về đầu tư'),
            ]
        )
        self.assertEqual(len(actual), 2)

    def test_similar_projects_with_different_numbers_remain_separate(self):
        actual = research.cluster_and_rank(
            [
                hit('https://baodautu.vn/a', 'Khởi công dự án nhà máy 100 triệu USD tại Hải Phòng'),
                hit('https://baodautu.vn/b', 'Khởi công dự án nhà máy 200 triệu USD tại Hải Phòng'),
            ]
        )
        self.assertEqual(len(actual), 2)

    def test_investor_tags_use_word_boundaries_not_fragments_of_names(self):
        result = research.cluster_and_rank(
            [hit('https://cafef.vn/kim-anh', 'Xã Kim Anh thúc đẩy khu công nghiệp')]
        )[0]
        self.assertFalse(any('M&A' in reason for reason in result['impact_reasons']))
        actual = research.cluster_and_rank([hit('https://cafef.vn/ma', 'Giao dịch M&A tại Việt Nam')])[0]
        self.assertTrue(any('M&A' in reason for reason in actual['impact_reasons']))

    def test_official_support_priority_and_novelty_are_transparent(self):
        actual = research.cluster_and_rank(
            [
                hit('https://cafef.vn/a', 'Tin doanh nghiệp', **page(None)),
                hit(
                    'https://chinhphu.vn/b',
                    'Đầu tư Trung Quốc và quy định ngoại hối',
                    **dict(page('2026-10-22'), date_status='in_range'),
                ),
            ],
            existing_urls={'https://cafef.vn/a?utm_source=old'},
        )
        self.assertEqual(actual[0]['url'], 'https://chinhphu.vn/b')
        self.assertTrue(actual[0]['is_new'])
        self.assertEqual(actual[1]['novelty'], 'seen')
        self.assertTrue(any('cơ quan nhà nước' in item for item in actual[0]['rationale']))
        self.assertTrue(any('chưa được xác minh' in item for item in actual[1]['rationale']))

    def test_verified_member_represents_cluster_with_undated_official_background(self):
        actual = research.cluster_and_rank(
            [
                hit('https://chinhphu.vn/a', 'Nghị định 10/2026/NĐ-CP về nhà đầu tư Trung Quốc'),
                hit(
                    'https://cafef.vn/b',
                    'Tin Nghị định 10/2026/NĐ-CP',
                    **dict(page('2026-10-22'), date_status='in_range'),
                ),
            ]
        )
        self.assertEqual(len(actual), 1)
        self.assertEqual(actual[0]['url'], 'https://cafef.vn/b')
        self.assertEqual(actual[0]['date_status'], 'in_range')
        self.assertTrue(actual[0]['has_official_source'])

    def test_new_syndicated_url_does_not_make_existing_story_new(self):
        title = 'Khởi công nhà máy năng lượng xanh tại Hải Phòng'
        actual = research.cluster_and_rank(
            [
                hit('https://cafef.vn/a', title),
                hit('https://chinhphu.vn/b', title),
            ],
            existing_urls={'https://cafef.vn/a'},
        )
        self.assertEqual(len(actual), 1)
        self.assertEqual(actual[0]['novelty'], 'seen')
        self.assertTrue(any('trong cụm đã có' in item for item in actual[0]['rationale']))


if __name__ == '__main__':
    unittest.main()
