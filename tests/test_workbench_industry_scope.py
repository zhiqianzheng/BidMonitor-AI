"""Industry selection constrains sources, queries, export and collection together."""
import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from apps.workbench.bidmonitor_workbench.api import create_app
from apps.workbench.bidmonitor_workbench.collectors.collection import CollectionService
from apps.workbench.bidmonitor_workbench.collectors.registry import normalize_source
from apps.workbench.bidmonitor_workbench.collectors.sectors import INDUSTRY_SOURCE_SECTORS, matches_industry
from apps.workbench.bidmonitor_workbench.storage.taxonomy import INDUSTRIES
from apps.workbench.bidmonitor_workbench.storage.workbench import WorkbenchStore


def site(key, name, kind='行业平台', hint=''):
    return dict(id=key, name=name, kind=kind, sector_hint=hint, province='全国',
                url=f'https://{key}.example.com/', adapter='generic', channel='网站直采', scope='测试公开列表')


SOURCES = [site('power', '通用采购平台', hint='中国华能集团'),
           site('hospital', '通用采购平台', hint='人民医院'),
           site('coal', '煤炭集团采购网'), site('college', '大学采购网', '高校科研'),
           site('it', '中国联通采购网'), site('generic', '综合招标网', '综合招标'),
           site('safety', '消防救援采购平台'), site('office', '中央机关采购网')]


def empty_runner(source, stop, pages):
    return dict(rows=[], warnings=[], empty_ok=True, message='已检查公开窗口')


class IndustryScopeTests(unittest.TestCase):
    def test_every_search_industry_has_a_source_mapping(self):
        self.assertEqual(set(INDUSTRY_SOURCE_SECTORS), set(INDUSTRIES))
        for industry, matching, other in [('能源电力', 'power', 'hospital'), ('能源电力', 'coal', 'generic'),
                                          ('医疗卫生', 'hospital', 'power'), ('教育科研', 'college', 'it'),
                                          ('信息技术', 'it', 'college'), ('公共安全', 'safety', 'generic'),
                                          ('行政办公', 'office', 'power')]:
            with self.subTest(industry=industry, matching=matching):
                self.assertTrue(matches_industry(next(s for s in SOURCES if s['id'] == matching), industry))
                self.assertFalse(matches_industry(next(s for s in SOURCES if s['id'] == other), industry))

    def test_scoped_collection_cannot_fall_back_to_all_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            store = WorkbenchStore(Path(folder)/'test.db')
            calls = []
            def runner(source, stop, pages):
                calls.append(source['id'])
                return empty_runner(source, stop, pages)
            service = CollectionService(store, runner=runner, sources=SOURCES)
            service.start(industry='能源电力')
            service.worker.join(5)
            self.assertCountEqual(calls, ['power', 'coal'])
            self.assertEqual(service.job['scope_label'], '能源电力')
            for kwargs in [dict(industry='不存在的行业'), dict(industry='能源电力', source_ids=['hospital']), dict(source_ids=[])]:
                with self.assertRaises(ValueError):
                    service.start(**kwargs)
            self.assertCountEqual(calls, ['power', 'coal'])

    def test_discovered_sites_are_only_collected_within_chosen_industry(self):
        with tempfile.TemporaryDirectory() as folder:
            store = WorkbenchStore(Path(folder)/'test.db')
            added_power = normalize_source(dict(name='新光伏采购平台', url='https://new-power.example.com/'))
            added_hospital = normalize_source(dict(name='新医院采购平台', url='https://new-hospital.example.com/', kind='医疗卫生'))
            calls = []
            def runner(source, stop, pages):
                calls.append(source['id'])
                return empty_runner(source, stop, pages) | {'discovered_sources': [added_power, added_hospital] if source['id'] == 'power' else []}
            service = CollectionService(store, runner=runner, sources=SOURCES[:2])
            service.start(industry='能源电力')
            service.worker.join(5)
            self.assertEqual(calls, ['power', added_power['id']])
            self.assertIn(added_hospital['id'], service.catalogue)  # Saved for the global catalogue, not used here.

    def test_search_export_and_source_endpoint_share_scope(self):
        with tempfile.TemporaryDirectory() as folder, patch('apps.workbench.bidmonitor_workbench.collectors.collection.catalogue', return_value=SOURCES):
            app = create_app(Path(folder)/'test.db')
            store, collector = app.state.store, app.state.collector
            collector.runner = empty_runner
            for source_id, title, industry in [('power', '华能光伏设备采购公告', '能源电力'),
                                                ('hospital', '医院光伏设备采购公告', '能源电力'),
                                                ('power', '华能办公软件采购公告', '信息技术'),
                                                ('college', '大学教学设备采购公告', '教育科研')]:
                name = next(s['name'] for s in SOURCES if s['id'] == source_id)
                key, _ = store.upsert_project(dict(title=title, industry=industry, source=name,
                                                   url=f'https://{source_id}.example.com/notice/{industry}', published_at='2020-11-16'))
                with store.connection() as db:
                    db.execute('INSERT INTO project_sources VALUES (?,?)', (source_id, key))
            store.upsert_project(dict(title='手动录入能源发电采购公告', industry='能源电力', source='手动录入', published_at='2020-11-16'))
            with TestClient(app) as client:
                energy = client.get('/api/sources', params={'industry':'能源电力'}).json()['items']
                self.assertCountEqual([s['id'] for s in energy], ['power', 'coal'])
                result = client.get('/api/projects', params={'industry':'能源电力','limit':1}).json()
                self.assertEqual(result['total'], 3)
                self.assertNotIn('医院', result['items'][0]['title'])
                rows = list(csv.reader(io.StringIO(client.get('/api/export?industry=能源电力').text.lstrip('\ufeff'))))
                self.assertCountEqual([r[0] for r in rows[1:]], ['华能光伏设备采购公告', '华能办公软件采购公告', '手动录入能源发电采购公告'])
                self.assertEqual(client.get('/api/projects?industry=教育科研').json()['total'], 1)
                self.assertEqual(client.get('/api/projects?source_sector=电力新能源').json()['total'], 2)
                self.assertEqual(client.get('/api/projects?industry=信息技术').json()['total'], 0)
                self.assertEqual(client.get('/api/projects').json()['total'], 5)
                # Passing an unrelated ID cannot expand the selected industry.
                response = client.post('/api/collect?industry=能源电力', json={'source_ids':['hospital']})
                self.assertEqual(response.status_code, 400)
                response = client.post('/api/collect?industry=能源电力', json={'source_ids':['power']})
                self.assertEqual(response.status_code, 200, response.text)
                collector.worker.join(5)
                self.assertEqual(collector.job['total'], 1)
                self.assertIn('source_industry_sectors', client.get('/api/meta').json())
            # More than SQLite's common variable limit still works, without leaking same-named sites.
            result = store.search(industry='能源电力', source_ids=['power']+[f'missing-{i}' for i in range(1200)], source_names=['通用采购平台'])
            self.assertEqual(result['total'], 3)


if __name__ == '__main__':
    unittest.main()
