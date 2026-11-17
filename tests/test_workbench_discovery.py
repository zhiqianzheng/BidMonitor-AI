"""Offline checks for the workbench's lightweight discovery workflow."""
import csv
import io
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from apps.workbench.bidmonitor_workbench.api import create_app
from apps.workbench.bidmonitor_workbench.collectors.collection import CollectionService
from apps.workbench.bidmonitor_workbench.collectors.feeds import collect_source, FeedUnavailable
from apps.workbench.bidmonitor_workbench.storage.workbench import WorkbenchStore

SOURCE = dict(id='test', name='测试来源', adapter='crcc', province='全国', channel='企业直采', url='https://example.com')


class DiscoveryTests(unittest.TestCase):
    def test_collection_filters_results_and_discards_body_fields(self):
        result = dict(rows=[
            dict(title='设备采购公告', url='https://example.com/1', published_at='2026-11-16', content='正文', deadline='2026-12-01', purchaser='单位'),
            dict(title='设备采购成交公告更正', url='https://example.com/2', notice_type='变更公告'),
            dict(title='设备采购', url='https://example.com/3', notice_type='中标结果'),
        ], warnings=[], message='测试')
        with patch('apps.workbench.bidmonitor_workbench.collectors.feeds._collect_source', return_value=result):
            rows = collect_source(SOURCE, threading.Event())['rows']
        self.assertEqual(rows, [dict(title='设备采购公告', url='https://example.com/1', published_at='2026-11-16')])

    def test_future_api_date_is_unknown_not_a_publication_claim(self):
        result = dict(rows=[dict(title='设备采购公告', url='https://example.com/1', published_at='2099-01-01')], warnings=[], message='测试')
        with patch('apps.workbench.bidmonitor_workbench.collectors.feeds._collect_source', return_value=result):
            output = collect_source(SOURCE, threading.Event())
        self.assertEqual(output['rows'][0]['published_at'], '')
        self.assertIn('待核实', output['warnings'][0])

    def test_results_only_is_a_valid_empty_window(self):
        result = dict(rows=[dict(title='中标公告', url='https://example.com/2')], warnings=[], message='测试')
        with patch('apps.workbench.bidmonitor_workbench.collectors.feeds._collect_source', return_value=result):
            output = collect_source(SOURCE, threading.Event())
        self.assertEqual(output['rows'], [])
        self.assertTrue(output['empty_ok'])

    def test_existing_results_hidden_before_pagination_without_deletion(self):
        with tempfile.TemporaryDirectory() as folder:
            store = WorkbenchStore(Path(folder)/'test.db')
            store.upsert_project(dict(title='设备成交公告更正', notice_type='变更公告', url='https://example.com/2'))
            store.upsert_project(dict(title='设备采购公告', url='https://example.com/1', published_at='2026-11-16', deadline='2020-01-01'))
            result = store.search(limit=1)
            self.assertEqual(result['total'], 1)
            self.assertEqual(result['items'][0]['title'], '设备采购公告')
            with store.connection() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM projects').fetchone()[0], 2)

    def test_blocked_source_stays_disabled(self):
        with tempfile.TemporaryDirectory() as folder:
            store = WorkbenchStore(Path(folder)/'test.db')
            def blocked(*args):
                raise FeedUnavailable('来源限制访问（HTTP 403）', 'blocked')
            service = CollectionService(store, runner=blocked, sources=[SOURCE])
            service.job['total'] = 1
            service._one(service.sources()[0], 1)
            source = CollectionService(store, sources=[SOURCE]).sources()[0]
            self.assertFalse(source['enabled'])
            self.assertEqual(source['status'], 'blocked')

    def test_export_and_disabled_detail_endpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            app = create_app(Path(folder)/'test.db')
            with TestClient(app) as client:
                response = client.post('/api/projects', json=dict(title='设备采购公告', url='https://example.com/1', published_at='2026-11-16'))
                self.assertEqual(response.status_code, 201, response.text)
                key = response.json()['project']['id']
                rows = list(csv.reader(io.StringIO(client.get('/api/export').text.lstrip('\ufeff'))))
                self.assertEqual(rows, [['标题', '原始URL', '公告发布时间'], ['设备采购公告', 'https://example.com/1', '2026-11-16']])
                self.assertEqual(client.post(f'/api/projects/{key}/detail').status_code, 410)
                self.assertEqual(client.get('/').status_code, 200)


if __name__ == '__main__':
    unittest.main()
