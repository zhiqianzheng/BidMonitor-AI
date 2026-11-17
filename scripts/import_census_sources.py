"""Import a fixed census snapshot offline, with a database backup and receipt.

Stop the local workbench before --apply; restart it afterward to publish the registry.
Default is a read-only preview. Existing source IDs, adapters and collection health
are preserved. Census reachability is never labelled successful notice collection.
"""
import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests
from apps.workbench.bidmonitor_workbench.collectors.registry import normalize_source, source_identity, redact_url_secrets
from apps.workbench.bidmonitor_workbench.collectors.sectors import source_sectors
from apps.workbench.bidmonitor_workbench.collectors.sources import catalogue
from apps.workbench.bidmonitor_workbench.paths import database_path

ROOT=Path(__file__).resolve().parents[1]


def definitions(db):
    current={s['id']:s for s in catalogue()}
    saved=db.execute("SELECT value FROM workbench_settings WHERE key='custom_sources'").fetchone()
    custom=json.loads(saved[0]) if saved else []
    for s in custom:current[s['id']]=current.get(s['id'],{})|s
    return current


def prepare(row, imported_at):
    s=normalize_source(dict(name=row['name'],url=row['url'],province=row['province'],kind=row['kind']))
    # Malformed public links are not useful search sources, even when syntactically URLs.
    host=urlsplit(s['url']).hostname.encode('idna').decode('ascii')
    if len(host)>253 or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?',label) for label in host.split('.')):
        raise ValueError('域名格式无效')
    sectors=json.loads(row['sectors'])
    s.update(channel='全国名录导入',scope='已登记公开网站入口；仅采集标题、原始链接和发布时间；网页可访问不等于公告已采集',
             sector_hint=' '.join(x for x in sectors if x not in ('其他行业','综合采购')),
             census_status=row['status'],census_checked_at=row['checked_at'],census_http_status=row['http_status'],
             census_imported_at=imported_at,census_page_title=row['page_title'] or '',
             census_final_url=redact_url_secrets(row['final_url'] or ''),census_level=row['level'],directory_group='全国网站专项普查')
    s['sectors']=source_sectors(s)
    return s


def initial_health(row):
    state=row['status'];http=row['http_status'] or 0
    if state=='blocked':return 0,'blocked',f'名录核验：访问受限（HTTP {http}），已停用；未执行公告采集'
    if state in ('request_failed','http_error','parked_or_closed'):
        return 0,'error',f'名录核验：{state}（HTTP {http}）；暂时停用，可手动重试；未执行公告采集'
    if state=='notice_links_found':
        return 1,'pending',f"名录核验：发现 {row['notice_links']} 个公告形式链接；尚未执行公告采集，不计为采集成功"
    if state=='reachable_needs_review':return 1,'pending','名录核验：网页可访问，采购栏目仍待确认；尚未执行公告采集'
    return 1,'pending','已导入网站名录；尚未核验或执行公告采集'


def import_snapshot(census_path, target, apply=False):
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');imported_at=datetime.now(timezone.utc).isoformat(timespec='seconds')
    with sqlite3.connect(f'file:{census_path}?mode=ro',uri=True) as research:
        research.row_factory=sqlite3.Row;research.execute('BEGIN')
        rows=[dict(r) for r in research.execute('SELECT * FROM candidates ORDER BY identity')]
        proofs=defaultdict(list)
        for e in research.execute('SELECT identity,evidence_url FROM evidence ORDER BY observed_at,evidence_url'):
            if e['evidence_url'] not in proofs[e['identity']]:proofs[e['identity']].append(e['evidence_url'])
    with sqlite3.connect(f'file:{target}?mode=ro',uri=True) as db:
        current=definitions(db)
        saved_blocks=db.execute("SELECT value FROM workbench_settings WHERE key='source_host_blocks'").fetchone()
        host_blocks=json.loads(saved_blocks[0]) if saved_blocks else {}
    by_identity=defaultdict(list)
    for s in current.values():by_identity[source_identity(s)].append(s['id'])
    added=[];enriched=set();rejected=[];health=[];identities=[]
    metadata=('census_status','census_checked_at','census_http_status','census_imported_at','census_page_title','census_final_url','census_level')
    for row in rows:
        try:s=prepare(row,imported_at)
        except (ValueError,TypeError,UnicodeError) as e:
            rejected.append({'name':row['name'],'url':row['url'],'reason':str(e)[:150]});continue
        proof=proofs.get(row['identity'],[]);s['evidence_url']=proof[0] if proof else row['url'];s['census_evidence_count']=len(proof)
        key=source_identity(s);identities.append(row['identity'])
        if key in by_identity:
            for source_id in by_identity[key]:
                old=current[source_id]
                old.update({k:s[k] for k in metadata});old['census_evidence_count']=len(proof)
                if not old.get('evidence_url'):old['evidence_url']=s['evidence_url']
                if old.get('province') in ('待核实','全国') and s['province'] not in ('待核实','全国'):old['province']=s['province']
                if old.get('kind')=='行业平台' and s['kind']!='行业平台':old['kind']=s['kind']
                if s.get('sector_hint'):old['sector_hint']=s['sector_hint']
                old['sectors']=source_sectors(old);enriched.add(source_id)
            continue
        if s['id'] in current:raise ValueError('来源ID冲突，已停止导入')
        current[s['id']]=s;by_identity[key].append(s['id']);added.append(s['id'])
        enabled,state,message=initial_health(row)
        host=urlsplit(s['url']).hostname.removeprefix('www.')
        port=urlsplit(s['url']).port
        if port not in (None,80,443):host+=f':{port}'
        if len(host_blocks.get(host,[]))>=3:
            enabled,state,message=0,'blocked','此前同一站点多个频道限制访问；名录已登记，保留停用状态'
        health.append((s['id'],s['name'],enabled,state,message))
    report=dict(imported_at=imported_at,applied=apply,national_complete=False,candidate_records=len(rows),added=len(added),
                matched_existing_records=len(rows)-len(added)-len(rejected),enriched_existing_sources=len(enriched),
                rejected=rejected,total_sources=len(current),new_sources_enabled=sum(x[2] for x in health),
                new_sources_disabled=sum(not x[2] for x in health),new_source_states=dict(Counter(x[3] for x in health)),
                source_snapshot_sha256=hashlib.sha256('\n'.join(r['identity'] for r in rows).encode()).hexdigest())
    if not apply:return report
    backup=ROOT/'runtime/source-census/backups'/f'workbench-before-census-import-{stamp}.sqlite3';backup.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(target) as live,sqlite3.connect(backup) as saved:live.backup(saved)
    # Definitions and initial health publish in one transaction. Keep every historical
    # definition so existing projects, adapters and source IDs continue to resolve.
    with sqlite3.connect(target,timeout=30) as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('INSERT INTO workbench_settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('custom_sources',json.dumps(list(current.values()),ensure_ascii=False)))
        db.executemany('INSERT INTO workbench_sources(id,search_name,enabled,status,message) VALUES (?,?,?,?,?)',health)
        db.execute('INSERT INTO workbench_settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('source_census_import',json.dumps(report,ensure_ascii=False)))
    report['backup_path']=str(backup)
    out=ROOT/'research/source-census';out.mkdir(parents=True,exist_ok=True)
    (out/'import-receipt.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (ROOT/'runtime/source-census/imported-identities.json').write_text(json.dumps(identities,ensure_ascii=False)+'\n')
    (out/'IMPORT.md').write_text(f"# 全国名录导入结果\n\n导入时间：{imported_at}\n\n已将当次快照中的 {len(rows):,} 条候选记录与工作台来源库合并：新增 {len(added):,} 个入口，匹配已有 {report['matched_existing_records']:,} 条，拒绝无效记录 {len(rejected):,} 条。导入后来源总数 {len(current):,}。\n\n新增来源中 {report['new_sources_enabled']:,} 个已启用，{report['new_sources_disabled']:,} 个因访问受限、请求失败或失效而停用，可在工作台查看原因并重试。网页核验未冒充公告采集成功；已有来源的开关、适配器、采集记录和项目关联保留。\n\n本次导入不表示全国网站已找全；普查仍有缺口。完整结果见 [导入回执](import-receipt.json)。数据库备份保存在本机 runtime/source-census/backups。\n")
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--apply',action='store_true');p.add_argument('--census',type=Path,default=ROOT/'runtime/source-census/census.sqlite3');p.add_argument('--db',type=Path,default=database_path());args=p.parse_args()
    if args.apply:
        try:r=requests.get('http://127.0.0.1:8765/api/health',timeout=2)
        except requests.RequestException:pass
        else:
            if r.ok:raise SystemExit('请先停止工作台服务，避免内存来源表与数据库不一致')
    print(json.dumps(import_snapshot(args.census,args.db,args.apply),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
