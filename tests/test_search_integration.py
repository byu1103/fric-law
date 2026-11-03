"""No-key discovery integration and real-network failure regressions (offline)."""

from datetime import date
import os
import unittest
from unittest.mock import Mock, patch

import requests
import research


def evidence(published, text='Nguồn chứng cứ. ' * 30):
    return {
        'text': text,
        'published': published,
        'date_verified': bool(published),
        'date_evidence': {'date': published} if published else None,
        'date_status': 'verified' if published else 'unknown',
    }


def response(raw=b'', redirect=False, location=None):
    value = Mock()
    value.is_redirect = value.is_permanent_redirect = redirect
    value.headers = {'Content-Type': 'text/html; charset=utf-8'}
    if location:
        value.headers['Location'] = location
    value.iter_content.return_value = [raw]
    return value


class SearchIntegration(unittest.TestCase):
    def setUp(self):
        self.start, self.end = date(2026, 10, 17), date(2026, 10, 23)

    @patch.dict(os.environ, {'TAVILY_API_KEY': ''})
    @patch('public_search.discover_public')
    @patch('research.fetch_evidence')
    @patch('research.requests.post')
    def test_auto_search_works_without_keys_and_still_requires_original_dates(self, post, fetch, public):
        public.return_value = {
            'candidates': [
                {
                    'url': 'https://cafef.vn/new',
                    'title': 'Trung Quốc đầu tư',
                    'provider_date_hint': '2026-10-01',
                },
                {
                    'url': 'https://cafef.vn/unknown',
                    'title': 'Trung Quốc đầu tư',
                    'provider_date_hint': '2026-10-23',
                },
                {
                    'url': 'https://cafef.vn/old',
                    'title': 'Trung Quốc đầu tư',
                    'provider_date_hint': '2026-10-23',
                },
            ],
            'diagnostics': {
                'coverage_note': 'Latest feeds, not full archive',
                'warnings': ['One site unavailable'],
            },
        }
        dates = {'new': '2026-10-23', 'unknown': None, 'old': '2026-10-01'}
        fetch.side_effect = lambda url: evidence(dates[url.rsplit('/', 1)[-1]])
        hits = research.search_news('đầu tư Trung Quốc', self.start, self.end)
        self.assertEqual([x['date_status'] for x in hits], ['in_range', 'unknown'])
        self.assertIsNone(hits[1]['published'])
        self.assertEqual(hits.diagnostics['provider'], 'public')
        self.assertEqual(hits.diagnostics['verified_count'], 1)
        self.assertEqual(hits.diagnostics['outside_count'], 1)
        self.assertIn('One site unavailable', hits.diagnostics['warnings'])
        post.assert_not_called()

    @patch.dict(os.environ, {'TAVILY_API_KEY': 'synthetic-test-key'})
    @patch('public_search.discover_public', return_value={'candidates': [], 'diagnostics': {}})
    @patch('research.requests.post', side_effect=requests.RequestException('synthetic-test-key'))
    def test_auto_tavily_failure_falls_back_without_echoing_keys(self, post, public):
        hits = research.search_news('đầu tư', self.start, self.end)
        public.assert_called_once()
        self.assertEqual(hits.diagnostics['provider'], 'public')
        self.assertNotIn('synthetic-test-key', str(hits.diagnostics))
        self.assertTrue(hits.diagnostics['warnings'])

    @patch.dict(os.environ, {'TAVILY_API_KEY': 'synthetic-test-key'})
    @patch('public_search.discover_public', return_value={'candidates': [], 'diagnostics': {}})
    @patch('research.requests.post')
    def test_explicit_public_ignores_optional_paid_key(self, post, public):
        research.search_news('đầu tư', self.start, self.end, provider='public')
        post.assert_not_called()
        public.assert_called_once()

    @patch('public_search.discover_public')
    @patch('research.requests.post')
    def test_unknown_provider_fails_before_network(self, post, public):
        with self.assertRaises(ValueError):
            research.search_news('đầu tư', self.start, self.end, provider='invented')
        post.assert_not_called()
        public.assert_not_called()


class FetchRegressions(unittest.TestCase):
    @patch('research._assert_public_dns')
    @patch('research.requests.get')
    def test_same_page_www_alias_verified_and_short_legal_lines_preserved(self, get, dns):
        original = response(redirect=True, location='https://www.vietnamplus.vn/example-post1.vnp')
        raw = (
            '<meta property="article:published_time" content="2026-10-23">'
            '<div class="article__body"><p>123/2026/NĐ-CP</p><p>一、法规</p><p>'
            + 'Bằng chứng nguồn. ' * 30
            + '</p></div>'
        )
        final = response(raw.encode())
        get.side_effect = [original, final]
        result = research.fetch_evidence('https://vietnamplus.vn/example-post1.vnp')
        self.assertTrue(result['date_verified'])
        self.assertIn('123/2026/NĐ-CP', result['text'])
        self.assertIn('一、法规', result['text'])
        self.assertEqual(result['fetched_url'], 'https://www.vietnamplus.vn/example-post1.vnp')
        self.assertEqual(dns.call_count, 2)
        original.close.assert_called_once()
        final.close.assert_called_once()
        self.assertTrue(all(not c.kwargs['allow_redirects'] for c in get.call_args_list))

    @patch('research._assert_public_dns')
    @patch('research.requests.get')
    def test_other_page_and_https_downgrade_redirects_stay_blocked(self, get, dns):
        for destination in [
            'https://vietnamplus.vn/unrelated',
            'http://vietnamplus.vn/original',
            'https://cafef.vn/original',
            'http://127.0.0.1/internal',
        ]:
            with self.subTest(destination=destination):
                get.reset_mock()
                get.return_value = response(redirect=True, location=destination)
                with self.assertRaises(ValueError):
                    research.fetch_evidence('https://vietnamplus.vn/original')
                get.assert_called_once()

    @patch('research._assert_public_dns')
    @patch('research.requests.get')
    def test_cafef_header_fallback_proves_original_when_og_timestamp_ambiguous(self, get, dns):
        raw = (
            '<meta property="article:published_time" content="2026-10-23T02:00:00">'
            '<div class="totalcontentdetail"><div class="dateandcat"><span itemprop="datePublished" data-role="publishdate" datetime="2026-10-22T23:00:00+07:00"></span></div></div>'
            '<div class="detail-content">' + 'Bằng chứng nguồn. ' * 30 + '</div>'
        )
        get.return_value = response(raw.encode())
        result = research.fetch_evidence('https://cafef.vn/example.chn')
        self.assertEqual(result['published'], '2026-10-22')
        self.assertEqual(result['date_evidence']['kind'], 'page_publication_label')


class DnsVpnRegressions(unittest.TestCase):
    def setUp(self):
        research._corroborate_public_dns.cache_clear()

    def tearDown(self):
        research._corroborate_public_dns.cache_clear()

    @patch('research.socket.getaddrinfo')
    @patch('research._corroborate_public_dns', return_value=True)
    def test_exact_publisher_fake_vpn_addresses_need_independent_confirmation(self, confirm, resolve):
        resolve.return_value = [(2, 1, 6, '', ('198.18.0.2', 0)), (10, 1, 6, '', ('fc00::100', 0))]
        research._assert_public_dns('cafef.vn')
        confirm.assert_called_once()
        confirm.reset_mock()
        with self.assertRaises(ValueError):
            research._assert_public_dns('unreviewed.cafef.vn')
        confirm.assert_not_called()

    @patch('research.socket.getaddrinfo')
    @patch('research._corroborate_public_dns', return_value=True)
    def test_private_local_targets_never_use_doh_exception(self, confirm, resolve):
        for address in ['127.0.0.1', '10.0.0.1', '192.168.1.1', '169.254.169.254']:
            resolve.return_value = [(2, 1, 6, '', (address, 0))]
            with self.assertRaises(ValueError):
                research._assert_public_dns('cafef.vn')
        confirm.assert_not_called()

    @patch('research.requests.get')
    def test_doh_confirmation_rejects_private_empty_truncated_or_failed_answers(self, get):
        for payload in [
            {'Status': 0, 'Answer': [{'type': 1, 'data': '127.0.0.1'}]},
            {'Status': 0, 'Answer': []},
            {'Status': 2, 'Answer': [{'type': 1, 'data': '8.8.8.8'}]},
            {'Status': 0, 'TC': True, 'Answer': [{'type': 1, 'data': '8.8.8.8'}]},
        ]:
            research._corroborate_public_dns.cache_clear()
            r = Mock()
            r.is_redirect = False
            r.json.return_value = payload
            get.return_value = r
            self.assertFalse(research._corroborate_public_dns('cafef.vn', 1))
            r.close.assert_called_once()

    @patch('research.requests.get')
    def test_doh_uses_fixed_https_endpoint_and_caches_public_answer(self, get):
        r = Mock()
        r.is_redirect = False
        r.json.return_value = {'Status': 0, 'Answer': [{'type': 1, 'data': '8.8.8.8'}]}
        get.return_value = r
        self.assertTrue(research._corroborate_public_dns('cafef.vn', 1))
        self.assertTrue(research._corroborate_public_dns('cafef.vn', 1))
        get.assert_called_once()
        self.assertEqual(get.call_args.args[0], 'https://dns.google/resolve')
        self.assertFalse(get.call_args.kwargs['allow_redirects'])
        self.assertEqual(get.call_args.kwargs['params']['edns_client_subnet'], '0.0.0.0/0')

    @patch('research.requests.get')
    def test_transient_dns_http_failure_can_recover_immediately_in_same_time_bucket(self, get):
        good = Mock(is_redirect=False)
        good.json.return_value = {'Status': 0, 'Answer': [{'type': 1, 'data': '8.8.8.8'}]}
        get.side_effect = [requests.Timeout('temporary connection failure'), good]
        self.assertFalse(research._corroborate_public_dns('cafef.vn', 123))
        self.assertEqual(research._corroborate_public_dns.cache_info().currsize, 0)
        self.assertTrue(research._corroborate_public_dns('cafef.vn', 123))
        self.assertTrue(research._corroborate_public_dns('cafef.vn', 123))
        self.assertEqual(get.call_count, 2)
        good.close.assert_called_once()

    @patch('research.requests.get')
    def test_private_dns_answers_never_cache_a_success_or_a_failure(self, get):
        private = Mock(is_redirect=False)
        private.json.return_value = {'Status': 0, 'Answer': [{'type': 1, 'data': '10.0.0.1'}]}
        good = Mock(is_redirect=False)
        good.json.return_value = {'Status': 0, 'Answer': [{'type': 1, 'data': '8.8.8.8'}]}
        get.side_effect = [private, private, good]
        self.assertFalse(research._corroborate_public_dns('cafef.vn', 123))
        self.assertFalse(research._corroborate_public_dns('cafef.vn', 123))
        self.assertEqual(research._corroborate_public_dns.cache_info().currsize, 0)
        self.assertTrue(research._corroborate_public_dns('cafef.vn', 123))
        self.assertEqual(get.call_count, 3)
        self.assertEqual(private.close.call_count, 2)
        good.close.assert_called_once()

    @patch('research.requests.get')
    def test_invalid_json_response_is_closed_and_does_not_cache_denial(self, get):
        invalid = Mock(is_redirect=False)
        invalid.json.side_effect = ValueError('not JSON')
        good = Mock(is_redirect=False)
        good.json.return_value = {'Status': 0, 'Answer': [{'type': 1, 'data': '8.8.8.8'}]}
        get.side_effect = [invalid, good]
        self.assertFalse(research._corroborate_public_dns('cafef.vn', 123))
        self.assertTrue(research._corroborate_public_dns('cafef.vn', 123))
        invalid.close.assert_called_once()
        good.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
