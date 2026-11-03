"""Publication-template regressions derived from live public article HTML."""

import unittest

from bs4 import BeautifulSoup

from publication_dates import source_publication_evidence


def evidence(markup, url):
    return source_publication_evidence(BeautifulSoup(markup, 'html.parser'), url)


class KnownPublicationHeaderTests(unittest.TestCase):
    def test_cafef_semantic_span_has_timezone_when_og_meta_does_not(self):
        markup = """<meta property="article:published_time" content="2026-10-23T00:03:00.000000">
        <div class="totalcontentdetail"><p class="dateandcat">
          <span class="pdate" data-role="publishdate" itemprop="datePublished"
            datetime="2026-10-23T00:03:00.000000+07:00">23-10-2026 - 00:03 AM</span>
        </p></div>"""
        published, proof, status = evidence(markup, 'https://cafef.vn/article.chn')
        self.assertEqual((published, status), ('2026-10-23', 'verified'))
        self.assertEqual(proof['timezone_basis'], 'explicit_offset')
        self.assertIn('datePublished', proof['selector'])

    def test_cafef_offset_is_converted_to_vietnam_day(self):
        markup = """<div class="totalcontentdetail"><p class="dateandcat">
        <span data-role="publishdate" itemprop="datePublished"
          datetime="2026-10-22T17:01:00Z"></span></p></div>"""
        self.assertEqual(evidence(markup, 'https://cafef.vn/article.chn')[0], '2026-10-23')

    def test_cafef_naive_metadata_and_related_time_do_not_verify(self):
        markup = """<meta property="article:published_time" content="2026-10-23T00:03:00">
        <span class="time-ago" title="2026-10-23T00:03:00">23/10/2026</span>
        <span itemprop="datePublished" datetime="2026-10-23T00:03:00+07:00"></span>"""
        self.assertEqual(evidence(markup, 'https://cafef.vn/article.chn'), (None, None, 'unknown'))

    def test_baodautu_original_header_not_masthead_clock(self):
        markup = """<div class="date_top">Thứ Sáu, Ngày 23 tháng 10 năm 2026</div>
          <div class="author-share-top"><div><a class="author">PV (ghi)</a>
          <span class="post-time"> - 30/05/2026 23:57</span></div></div>"""
        published, proof, status = evidence(markup, 'https://baodautu.vn/article-d608008.html')
        self.assertEqual((published, status), ('2026-05-30', 'verified'))
        self.assertEqual(proof['value'], '- 30/05/2026 23:57')
        self.assertEqual(proof['timezone_basis'], 'trusted_vietnam_article_header')

    def test_baochinhphu_scoped_publish_label_survives_nested_icons(self):
        markup = """<article class="detail-mcontent"><div class="detail-time">
          <div data-role="publishdate">22/10/2026 <span class="icon"><svg></svg></span>19:45</div>
        </div></article><div data-role="publishdate">23/10/2026 01:00</div>"""
        self.assertEqual(evidence(markup, 'https://baochinhphu.vn/article.htm')[0], '2026-10-22')

    def test_vnexpress_visible_publication_requires_article_scope_and_offset(self):
        markup = """<div class="header-content"><span class="date">23/10/2026 09:00</span></div>
          <section class="page-detail"><div class="sidebar-1"><div class="header-content">
          <span class="date">Thứ năm, 22/10/2026, 21:21 (GMT+7)</span>
          </div></div></section>"""
        self.assertEqual(evidence(markup, 'https://vnexpress.net/article.html')[0], '2026-10-22')
        self.assertIsNone(evidence(markup.replace('(GMT+7)', ''), 'https://vnexpress.net/article.html')[0])

    def test_vietnamplus_uses_article_meta_not_related_story_times(self):
        markup = """<div class="article"><div class="article__meta">
          <time class="time" data-friendly="false" datetime="2026-10-22T19:54:42+07:00"></time>
          </div><time class="time" datetime="2026-10-23T00:00:00+07:00"></time></div>"""
        self.assertEqual(evidence(markup, 'https://www.vietnamplus.vn/article.vnp')[0], '2026-10-22')

    def test_modified_issued_effective_and_invalid_dates_are_never_accepted(self):
        for raw in (
            'Cập nhật: 22/10/2026 09:00',
            'Ban hành: 22/10/2026 09:00',
            'Hiệu lực: 22/10/2026 09:00',
            ' - 31/02/2026 09:00',
            ' - 22/10/2026 24:01',
        ):
            with self.subTest(raw=raw):
                markup = f'<div class="author-share-top"><span class="post-time">{raw}</span></div>'
                self.assertIsNone(evidence(markup, 'https://baodautu.vn/article.html')[0])

    def test_conflicting_original_header_labels_remain_pending(self):
        markup = """<div class="author-share-top"><span class="post-time">22/10/2026 09:00</span>
          <span class="post-time">23/10/2026 09:00</span></div>"""
        published, proof, status = evidence(markup, 'https://baodautu.vn/article.html')
        self.assertIsNone(published)
        self.assertEqual(status, 'conflicting')
        self.assertEqual(len(proof['candidates']), 2)

    def test_unknown_hosts_and_legal_dates_never_use_news_template(self):
        markup = '<div class="author-share-top"><span class="post-time">22/10/2026 09:00</span></div>'
        for url in (
            'https://baodautu.vn.evil.test/article.html',
            'https://vanban.chinhphu.vn/?docid=1',
            None,
        ):
            with self.subTest(url=url):
                self.assertEqual(evidence(markup, url), (None, None, 'unknown'))


if __name__ == '__main__':
    unittest.main()
