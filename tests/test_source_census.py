import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import census_tender_sites as census


class CensusTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
  self.patch=patch.multiple(census,STATE=root,DB=root/'research.sqlite3',OUT=root/'export');self.patch.start();self.db=census.connect()
 def tearDown(self):
  self.db.close();self.patch.stop();self.tmp.cleanup()
 def test_aggregation_channels_do_not_inflate_website_count(self):
  self.assertFalse(census.add(self.db,{'name':'某市招标采购网','url':'https://www.qianlima.com/zb/area_123/'},'https://directory.example.org/','测试'))
  self.assertEqual(self.db.execute('SELECT COUNT(*) FROM candidates').fetchone()[0],0)
  self.assertEqual(self.db.execute('SELECT COUNT(*) FROM excluded_links').fetchone()[0],1)
  self.assertTrue(census.add(self.db,{'name':'千里马招标网','url':'https://www.qianlima.com/'},'https://directory.example.org/','测试'))
 def test_identity_dedup_retains_all_evidence_and_spa_routes(self):
  row={'name':'某省公共资源交易平台','url':'https://portal.example.org/#/city/one','kind':'公共资源'}
  self.assertTrue(census.add(self.db,row,'https://directory.example.org/a','测试'))
  self.assertFalse(census.add(self.db,row|{'url':'http://www.portal.example.org/#/city/one'},'https://directory.example.org/b','测试'))
  self.assertTrue(census.add(self.db,row|{'url':'https://portal.example.org/#/city/two'},'https://directory.example.org/a','测试'))
  self.assertEqual(self.db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0],3)
 def test_blocked_pages_cannot_add_unverified_links(self):
  r={'url':'https://blocked.example.org/','final':'https://blocked.example.org/','status':403,'text':'<title>Forbidden</title><a href="https://fake.example.org/">虚构采购平台</a>','error':''}
  count,status=census.extract(self.db,r)
  self.assertEqual(count,0);self.assertEqual(status,'blocked')
  self.assertEqual(self.db.execute('SELECT COUNT(*) FROM candidates').fetchone()[0],0)
 def test_malformed_external_link_does_not_stop_census(self):
  html='<a href="https://[bad/">错误采购平台</a><a href="https://valid.example.org/">正常采购平台</a>'
  self.assertEqual(list(census.links(html,'https://directory.example.org/')),[('正常采购平台','https://valid.example.org/')])
 def test_export_never_certifies_completeness_or_import(self):
  census.add(self.db,{'name':'某医院采购平台','url':'https://hospital.example.org/'},'https://directory.example.org/','测试')
  report=census.export(self.db)
  self.assertFalse(report['complete']);self.assertFalse(report['imported']);self.assertEqual(report['states'],{'pending':1})
  self.assertTrue((census.OUT/'hosts.csv').exists())
  self.assertEqual(census.infer_province('中国能源采购平台','全国'),'全国')
  self.assertEqual(census.infer_kind('某某国有投资公司'),'企业招标')


if __name__=='__main__':unittest.main()
