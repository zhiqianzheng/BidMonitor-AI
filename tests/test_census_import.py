import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import census_tender_sites as census
from scripts import import_census_sources as importer


class ImportTests(unittest.TestCase):
 def test_import_preserves_ids_health_and_is_idempotent(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);research=root/'research.sqlite3';target=root/'workbench.sqlite3'
   with patch.multiple(census,STATE=root,DB=research):
    c=census.connect()
    for name,url,status in [('现有电力采购','https://existing.example.org/','blocked'),('新能源采购网','https://new.example.org/','notice_links_found'),('医院采购平台','https://blocked.example.org/','blocked'),('银行采购网','https://hostblocked.example.org/','reachable_needs_review'),('错误采购网','https://host.example.org)错误/','pending')]:
     census.add(c,dict(name=name,url=url,kind='行业平台',province='全国'),'https://directory.example.org/','测试')
     c.execute('UPDATE candidates SET status=?,notice_links=4 WHERE url=?',(status,url))
    c.commit();c.close()
   existing=dict(id='keep-adapter',name='现有电力采购',url='https://existing.example.org/',kind='企业招标',province='全国',adapter='existing_adapter',channel='直采',scope='原配置')
   with sqlite3.connect(target) as db:
    db.executescript('CREATE TABLE workbench_settings(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE workbench_sources(id TEXT PRIMARY KEY,search_name TEXT,enabled INTEGER,status TEXT,message TEXT);CREATE TABLE projects(id INTEGER PRIMARY KEY,title TEXT);INSERT INTO projects VALUES(1,"保留项目");')
    db.execute('INSERT INTO workbench_sources VALUES(?,?,?,?,?)',('keep-adapter',existing['name'],1,'success','已采集公告'))
    db.execute('INSERT INTO workbench_settings VALUES(?,?)',('source_host_blocks',json.dumps({'hostblocked.example.org':['a','b','c']})))
   with patch.object(importer,'ROOT',root),patch.object(importer,'catalogue',return_value=[existing]):
    preview=importer.import_snapshot(research,target)
    self.assertEqual(preview['added'],3);self.assertEqual(len(preview['rejected']),1)
    self.assertFalse((root/'research/source-census/import-receipt.json').exists())
    report=importer.import_snapshot(research,target,True)
    self.assertEqual(report['new_sources_enabled'],1);self.assertEqual(report['new_sources_disabled'],2)
    self.assertTrue(Path(report['backup_path']).exists())
    with sqlite3.connect(target) as db:
     self.assertEqual(db.execute('SELECT enabled,status,message FROM workbench_sources WHERE id="keep-adapter"').fetchone(),(1,'success','已采集公告'))
     definitions=json.loads(db.execute('SELECT value FROM workbench_settings WHERE key="custom_sources"').fetchone()[0]);old=next(s for s in definitions if s['id']=='keep-adapter');self.assertEqual(old['adapter'],'existing_adapter');self.assertEqual(old['census_status'],'blocked')
     self.assertEqual(db.execute('SELECT COUNT(*) FROM projects').fetchone()[0],1)
     self.assertEqual(db.execute('SELECT COUNT(*) FROM workbench_sources WHERE status="success"').fetchone()[0],1)
    second=importer.import_snapshot(research,target,True)
    self.assertEqual(second['added'],0);self.assertEqual(second['total_sources'],report['total_sources'])


if __name__=='__main__':unittest.main()
