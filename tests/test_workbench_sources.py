"""Registry persistence, bounded bulk imports, and generic list parsing."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from apps.workbench.bidmonitor_workbench.api import create_app
from apps.workbench.bidmonitor_workbench.collectors.collection import CollectionService
from apps.workbench.bidmonitor_workbench.collectors.generic import collect_generic, parse_listing
from apps.workbench.bidmonitor_workbench.collectors.registry import parse_import
from apps.workbench.bidmonitor_workbench.collectors.sources import catalogue
from apps.workbench.bidmonitor_workbench.storage.workbench import WorkbenchStore

SOURCE = dict(id='test', name='测试采购网', url='https://example.com/notices/', province='全国', adapter='generic')
HTML = '''<ul>
<li><a href="/notice/1.html">实验室设备采购公告</a><time>2020-11-16</time></li>
<li><a href="/notice/2.html">实验室设备成交公告更正</a><time>2020-11-16</time></li>
<li><a href="/notice/3.html">2025-01-01批次设备采购公告</a></li>
<li><a href="https://other.example/1">外部转载设备采购公告</a><time>2020-11-16</time></li>
</ul><a href="?page=2">下一页</a>'''


class SourceTests(unittest.TestCase):
    def test_catalogue_has_unique_ids_and_evidence_for_extensions(self):
        sources = catalogue()
        self.assertEqual(len(sources), len({s['id'] for s in sources}))
        additions = [s for s in sources if s['adapter'] == 'generic']
        self.assertGreaterEqual(len(additions), 70)
        self.assertTrue(all(s['evidence_url'].startswith(('http:', 'https:')) for s in additions))

    def test_csv_rejects_entire_batch_with_bad_url(self):
        with self.assertRaisesRegex(ValueError, '第 3 行'):
            parse_import('名称,网址\n有效来源,https://example.com/\n内网来源,http://127.0.0.1/')
        self.assertEqual(len(parse_import('name,url\n"含,逗号名称",https://example.com/')), 1)

    def test_ten_thousand_rows_accepted_and_overflow_rejected(self):
        body = '名称,网址\n' + ''.join(f'来源{i},https://example.com/{i}\n' for i in range(10000))
        self.assertEqual(len(parse_import(body)), 10000)
        with self.assertRaisesRegex(ValueError, '10000'):
            parse_import(body + '超限来源,https://example.com/extra\n')

    def test_registry_deduplication_and_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            store = WorkbenchStore(Path(folder)/'test.db')
            service = CollectionService(store, sources=[])
            output = service.import_sources('名称,网址,地区,类别\n测试采购,https://example.com/notices/,江苏,高校科研\n重复来源,http://www.example.com/notices,全国,行业平台')
            self.assertEqual((output['added'], output['duplicates']), (1, 1))
            source = CollectionService(store, sources=[]).sources()[0]
            self.assertEqual((source['province'], source['kind'], source['status']), ('江苏', '高校科研', 'pending'))
            with self.assertRaises(ValueError):
                service.import_sources('名称,网址\n有效来源,https://new.example.com/\n错误来源,http://localhost/')
            self.assertEqual(len(service.sources()), 1)

    def test_public_ports_are_distinct_source_entries(self):
        from apps.workbench.bidmonitor_workbench.collectors.registry import source_identity
        rows = parse_import('名称,网址\n采购一号,http://example.com:8080/\n采购二号,http://example.com:9000/')
        self.assertNotEqual(source_identity(rows[0]), source_identity(rows[1]))

    def test_parser_only_uses_dated_opportunities(self):
        rows = list(parse_listing(HTML, SOURCE['url'], SOURCE))
        self.assertEqual([r['title'] for r in rows], ['实验室设备采购公告'])
        self.assertEqual(rows[0]['published_at'], '2020-11-16')
        self.assertEqual(rows[0]['url'], 'https://example.com/notice/1.html')

    def test_pagination_is_bounded_and_deduplicated(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return HTML, url
        result = collect_generic(SOURCE, threading.Event(), 2, fetch)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(result['rows']), 1)
        self.assertTrue(result['truncated'])

    def test_table_uses_publication_column_not_opening_time(self):
        html = '<table><thead><tr><th>项目</th><th>开标时间</th><th>发布时间</th></tr></thead><tbody><tr><td><a href="/notice/1">实验室设备采购公告</a></td><td>2099-12-01</td><td>2020-11-16</td></tr></tbody></table>'
        self.assertEqual(list(parse_listing(html, SOURCE['url'], SOURCE))[0]['published_at'], '2020-11-16')

    def test_pdf_notice_does_not_require_downloading_body(self):
        html = '<ul><li><a href="/files/notice.pdf">实验室设备采购公告</a><span>2020-11-16</span></li></ul>'
        row = list(parse_listing(html, SOURCE['url'], SOURCE))[0]
        self.assertEqual(row['url'], 'https://example.com/files/notice.pdf')
        self.assertNotIn('content', row)

    def test_wrapped_title_does_not_include_date(self):
        html = '<ul><li><a href="/notice/1"><div class="item-name" title="实验室设备采购公告">实验室设备采购公告</div><div class="item-date">2020-11-16</div></a></li></ul>'
        row = list(parse_listing(html, SOURCE['url'], SOURCE))[0]
        self.assertEqual((row['title'], row['published_at']), ('实验室设备采购公告', '2020-11-16'))

    def test_literal_onclick_and_result_channel(self):
        source = SOURCE | {'url': 'https://test.etrading.cn/'}
        html = '<ul><li><a title="实验室一号楼施工项目" onclick="geturl(\'/jyxx/001001/001001001/20201116/abc-123.html\',\'abc-123\',\'001001001\')">实验室一号楼施工项目</a><span>2020-11-16</span></li><li><a href="/jyxx/001001/001001003/20201116/result.html">实验室设备采购项目</a><span>2020-11-16</span></li></ul>'
        rows = list(parse_listing(html, source['url'], source))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['notice_type'], '招标公告')

    def test_future_or_ambiguous_dates_are_not_used(self):
        html = '<ul><li><a href="/notice/1">实验室设备采购公告</a><span>2099-11-16</span></li><li><a href="/notice/2">实验室设备采购公告</a><span>2020-11-01 2020-11-20</span></li></ul>'
        self.assertEqual(list(parse_listing(html, SOURCE['url'], SOURCE)), [])

    def test_import_api(self):
        with tempfile.TemporaryDirectory() as folder, TestClient(create_app(Path(folder)/'test.db')) as client:
            response = client.post('/api/sources/import', json={'csv': '名称,网址\n测试来源,https://example.com/notices/'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['added'], 1)
            self.assertTrue(any(s['name'] == '测试来源' for s in client.get('/api/sources').json()['items']))



class DiscoveryExpansionTests(unittest.TestCase):
    def test_related_platforms_are_discovered_with_provenance(self):
        from apps.workbench.bidmonitor_workbench.collectors.discovery import discover_links
        html = '<a href="https://b.example.com/">区域公共资源交易平台</a><a href="https://b.example.com/news/2026/11/16/x.html">采购政策通知</a><a href="http://127.0.0.1/">单位招标采购平台</a>'
        rows = discover_links(html, SOURCE['url'], SOURCE)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['evidence_url'], SOURCE['url'])
        self.assertTrue(rows[0]['auto_discovered'])

    def test_bulk_collection_continues_into_new_platform(self):
        from apps.workbench.bidmonitor_workbench.collectors.registry import normalize_source
        with tempfile.TemporaryDirectory() as folder:
            store = WorkbenchStore(Path(folder)/'test.db')
            original = SOURCE | {'kind': '行业平台', 'channel': '网站直采'}
            discovered = normalize_source(dict(name='新采购平台',url='https://b.example.com/'))
            calls = []
            def runner(source, stop, pages):
                calls.append(source['id'])
                return dict(rows=[], warnings=[], empty_ok=True, message='空窗口',
                            discovered_sources=[discovered] if source['id'] == original['id'] else [])
            service = CollectionService(store, runner=runner, sources=[original])
            service.job.update(running=True, total=1)
            service._collect(service.sources(), 1)
            self.assertEqual(calls, [original['id'], discovered['id']])
            self.assertEqual(service.job['discovered'], 1)
            self.assertEqual(len(CollectionService(store, sources=[]).sources()), 1)
    def test_repeated_site_blocks_stop_other_channels_and_survive_restart(self):
        from apps.workbench.bidmonitor_workbench.collectors.feeds import FeedUnavailable
        from apps.workbench.bidmonitor_workbench.collectors.registry import normalize_source
        with tempfile.TemporaryDirectory() as folder:
            store = WorkbenchStore(Path(folder)/'test.db')
            sources = [normalize_source(dict(name=f'测试采购平台{i}', url=f'https://example.com/list/{i}')) for i in range(4)]
            calls = []
            def blocked(source, stop, pages):
                calls.append(source['id'])
                raise FeedUnavailable('HTTP 403 访问限制', 'blocked')
            service = CollectionService(store, runner=blocked, sources=sources)
            service.job['total'] = 4
            for source in service.sources():
                service._one(source, 1)
            self.assertEqual(len(calls), 3)
            restored = CollectionService(store, runner=blocked, sources=sources)
            self.assertTrue(all(not s['enabled'] for s in restored.sources()))
            restored.enable(sources[3]['id'], True)
            self.assertEqual(restored.host_blocks, {})
            self.assertEqual(CollectionService(store, sources=sources).host_blocks, {})

    def test_pending_only_resumes_without_recrawling_checked_sources(self):
        from apps.workbench.bidmonitor_workbench.collectors.registry import normalize_source
        with tempfile.TemporaryDirectory() as folder:
            store = WorkbenchStore(Path(folder)/'test.db')
            sources = [normalize_source(dict(name=f'测试采购平台{i}', url=f'https://example.com/{i}')) for i in range(2)]
            calls = []
            def runner(source, stop, pages):
                calls.append(source['id'])
                return dict(rows=[], warnings=[], empty_ok=True, message='已核验空窗口')
            service = CollectionService(store, runner=runner, sources=sources)
            with store.connection() as db:
                db.execute("UPDATE workbench_sources SET status='empty' WHERE id=?", (sources[0]['id'],))
            service.start(pending_only=True)
            service.worker.join(3)
            self.assertFalse(service.worker.is_alive())
            self.assertEqual(calls, [sources[1]['id']])




class PublicRedirectTests(unittest.TestCase):
    def test_redirect_credentials_are_not_exported(self):
        from apps.workbench.bidmonitor_workbench.collectors.registry import redact_url_secrets
        from urllib.parse import parse_qs, urlsplit
        url = 'https://portal.example.org/login?service=https%3A%2F%2Fsite.example.org%2Flist%3Fpage%3D2&secret=example-secret&OSSAccessKeyId=example-id&Signature=example-signature&Expires=123'
        cleaned = redact_url_secrets(url)
        self.assertEqual(parse_qs(urlsplit(cleaned).query), {'service': ['https://site.example.org/list?page=2']})
        self.assertNotIn('example-secret', cleaned)
        self.assertEqual(redact_url_secrets('https://site.example.org/#/home?page=km'), 'https://site.example.org/#/home?page=km')
        self.assertEqual(redact_url_secrets('https://site.example.org/#/home?page=km&token=example-token'), 'https://site.example.org/#/home?page=km')


if __name__ == '__main__':
    unittest.main()
