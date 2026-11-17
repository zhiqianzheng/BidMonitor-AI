"""Standalone source census. Never imports sources or calls collection APIs.

Usage: PYTHONPATH=. .venv/bin/python scripts/census_tender_sites.py seed|directories|verify|export
Resume by rerunning a command. Public research state lives separately from the app.
"""
import argparse
import csv
import hashlib
import json
import re
import sqlite3
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import json5
import requests
from bs4 import BeautifulSoup

from apps.workbench.bidmonitor_workbench.collectors.registry import normalize_source, source_identity, redact_url_secrets
from apps.workbench.bidmonitor_workbench.collectors.sectors import SECTORS, source_sectors
from apps.workbench.bidmonitor_workbench.collectors.sources import PROVINCES, catalogue

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'runtime/source-census'
OUT = ROOT / 'research/source-census'
DB = STATE / 'census.sqlite3'
PLATFORM = re.compile(r'招标|招投标|招采|采购|公共资源|交易中心|电子交易|阳光交易|产权交易')
NOISE = re.compile(r'登录|注册|下载|手册|指南|政策|法规|培训|证书|收费|信用查询|失信查询|代理费|计算器|认证|投诉|合同公告|中标|成交|候选人|资格审查|更正|废标|结果公告|变更公告|开标|延期')
NAV = re.compile(r'友情链接|网站导航|站点导航|相关链接|交易平台|交易中心|各地|各市|各县|分网|采购平台|招标平台|招标采购|采购招标|集中采购|招标信息|采购信息|采购公告|招标公告|采购与招标|招投标信息')
FILE = re.compile(r'\.(pdf|docx?|xlsx?|zip|rar|png|jpg|jpeg|gif|mp4|css|js|ico)(?:$|\?)', re.I)
NOTICE = re.compile(r'(?:采购|招标|磋商|询价|竞价|谈判|比选|遴选|征集|竞谈).{0,70}(?:公告|邀请|公示)|(?:公告|公示).{0,70}(?:采购|招标|磋商|询价|比选)')
BLOCKED = re.compile(r'人机验证|安全验证|访问被拒绝|访问过于频繁|验证码|Access Denied|Request blocked|Forbidden|captcha', re.I)
PARKED = re.compile(r'域名出售|域名已过期|域名停靠|domain for sale|account suspended|网站已关闭|网站停止服务', re.I)
PROV_NAMES = [p[1] for p in PROVINCES] + ['兵团','香港','澳门','台湾']


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def connect():
    STATE.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.executescript('''
    CREATE TABLE IF NOT EXISTS candidates (
        identity TEXT PRIMARY KEY, name TEXT, url TEXT, host TEXT, province TEXT, kind TEXT,
        sectors TEXT, discovered_at TEXT, status TEXT DEFAULT 'pending', checked_at TEXT,
        http_status INTEGER, final_url TEXT, page_title TEXT, notice_links INTEGER DEFAULT 0,
        error TEXT DEFAULT '', body_sha256 TEXT DEFAULT '', level TEXT DEFAULT '待核实');
    CREATE TABLE IF NOT EXISTS evidence (
        identity TEXT, evidence_url TEXT, anchor TEXT, origin TEXT, observed_at TEXT,
        UNIQUE(identity, evidence_url, anchor));
    CREATE TABLE IF NOT EXISTS pages (
        url TEXT PRIMARY KEY, name TEXT, depth INTEGER, status TEXT DEFAULT 'pending',
        checked_at TEXT, http_status INTEGER, final_url TEXT, title TEXT, error TEXT);
    CREATE TABLE IF NOT EXISTS excluded_links (url TEXT, name TEXT, evidence_url TEXT, reason TEXT, PRIMARY KEY(url,evidence_url));
    CREATE TABLE IF NOT EXISTS directory_pages (
        url TEXT PRIMARY KEY, status INTEGER, count INTEGER, checked_at TEXT, error TEXT);
    ''')
    return c


def identity(item):
    return json.dumps(source_identity(item), ensure_ascii=False)


def infer_kind(name):
    for pat, kind in [(r'公共资源','公共资源'),(r'政府采购|政采|机关采购','政府采购'),(r'大学|学院|学校|科学院|研究院','高校科研'),(r'医院|卫生|医疗|药品|医保','医疗卫生'),(r'银行|保险|金融|证券','金融采购'),(r'代理|招标有限公司|招标有限责任','招标代理'),(r'公司|集团|企业','企业招标')]:
        if re.search(pat,name):
            return kind
    return '行业平台'


def infer_province(name, hint=''):
    hits = [p for p in PROV_NAMES if p in name]
    if hint == '全国':
        return '全国'
    if len(hits) == 1:
        return hits[0]
    return hint if hint in PROV_NAMES else '待核实'


def level(name, kind):
    # Institutions/companies are not administrative tiers even when named after a province.
    if kind not in ('政府采购', '公共资源'):
        return '机构或企业'
    if re.search(r'中央|全国|中国政府|国家机关',name): return '国家级'
    if re.search(r'县|区公共资源|区政府采购|旗公共资源',name): return '区县级（待核实）'
    if re.search(r'省|自治区|兵团',name): return '省级（待核实）'
    if re.search(r'市|自治州|地区|盟',name): return '地市级（待核实）'
    return '待核实'


def add(c, row, evidence_url, origin, enqueue=True):
    try:
        item = normalize_source(row)
    except (ValueError, TypeError):
        return False
    host = urlsplit(item['url']).hostname.removeprefix('www.')
    commercial = any(host == h or host.endswith('.'+h) for h in ('qianlima.com','youzhicai.com','dlzb.com','jianyu360.cn','bidcenter.com.cn','bidchance.com','zbytb.com'))
    path = urlsplit(item['url']).path.rstrip('/')
    if commercial and (path or urlsplit(item['url']).query):
        c.execute('INSERT OR IGNORE INTO excluded_links VALUES(?,?,?,?)',(item['url'],item['name'],evidence_url,'商业聚合站栏目，非独立网站'))
        return False
    if host in ('mp.weixin.qq.com','weixin.qq.com','wpa.qq.com','beian.miit.gov.cn','beian.gov.cn','h5.xunzhuang.net','hebeedu.cn'):
        c.execute('INSERT OR IGNORE INTO excluded_links VALUES(?,?,?,?)',(item['url'],item['name'],evidence_url,'社交或备案链接，非独立采购网站'))
        return False
    key = identity(item)
    prov = infer_province(item['name'], row.get('province',''))
    item['sector_hint'] = row.get('sector_hint','')
    sectors = source_sectors(item)
    previous = c.execute('SELECT province FROM candidates WHERE identity=?',(key,)).fetchone()
    if previous and previous['province']=='待核实' and prov!='待核实':
        c.execute('UPDATE candidates SET province=? WHERE identity=?',(prov,key))
    new = c.execute('INSERT OR IGNORE INTO candidates(identity,name,url,host,province,kind,sectors,discovered_at,level) VALUES(?,?,?,?,?,?,?,?,?)',
                    (key,item['name'],item['url'],urlsplit(item['url']).hostname.removeprefix('www.'),prov,item['kind'],json.dumps(sectors,ensure_ascii=False),now(),level(item['name'],item['kind']))).rowcount
    c.execute('INSERT OR IGNORE INTO evidence VALUES(?,?,?,?,?)',(key,evidence_url,item['name'],origin,now()))
    if enqueue:
        c.execute('INSERT OR IGNORE INTO pages(url,name,depth) VALUES(?,?,0)',(item['url'],item['name']))
    return bool(new)


def fetch(url):
    try:
        # Browser-like Accept, no credential/cookie material and no TLS bypass.
        with requests.get(url, timeout=(5,12), headers={'User-Agent':'BidMonitor-SourceCensus/1.0 (public website directory verification)','Accept':'text/html,application/json;q=0.9,*/*;q=0.5'}, stream=True) as r:
            chunks=[];size=0
            for chunk in r.iter_content(65536):
                size+=len(chunk)
                if size > 4*1024*1024:
                    return {'url':url,'status':r.status_code,'final':r.url,'error':'response_over_4MB','text':''}
                chunks.append(chunk)
            body=b''.join(chunks)
            encoding = r.encoding if r.encoding and r.encoding.lower() != 'iso-8859-1' else None
            if not encoding:
                m=re.search(br'charset\s*=\s*["\']?([a-zA-Z0-9_-]+)',body[:12000])
                encoding=m[1].decode() if m else 'utf-8'
            try: text=body.decode(encoding,errors='replace')
            except LookupError: text=body.decode('utf-8',errors='replace')
            return {'url':url,'status':r.status_code,'final':r.url,'text':text,'error':'','sha':hashlib.sha256(body).hexdigest()}
    except requests.RequestException as e:
        return {'url':url,'status':0,'final':'','text':'','error':type(e).__name__}


def seed(c, existing=None):
    sources=catalogue()
    if existing:
        data=json.loads(Path(existing).read_text())
        sources += data['items'] if isinstance(data,dict) else data
    added=0
    for s in sources:
        added+=add(c,s,s.get('evidence_url') or s['url'],'历史登记（未视为核实）')
    c.commit()
    print(json.dumps({'seed_records':len(sources),'new_candidates':added},ensure_ascii=False),flush=True)


def links(text,url):
    soup=BeautifulSoup(text,'lxml')
    for a in soup.select('a[href],option[value]'):
        name=re.sub(r'\s+',' ',a.get('title') or a.get_text(' ',strip=True)).strip()
        href=(a.get('href') or a.get('value') or '').strip()
        if not href or href.startswith(('javascript:','mailto:','tel:','#')):continue
        try:
            target=urljoin(url,href)
            p=urlsplit(target)
        except ValueError:
            continue
        if p.scheme not in ('https','http') or not p.hostname or FILE.search(target):continue
        if not p.fragment.startswith(('/','!/')):target=urlunsplit((p.scheme,p.netloc,p.path,p.query,''))
        yield name,target


def extract(c,result,name='',depth=0,directory=False):
    text=result['text'];url=result['final'] or result['url']
    soup=BeautifulSoup(text,'lxml')
    title=soup.title.get_text(' ',strip=True)[:300] if soup.title else ''
    host=urlsplit(url).hostname
    notices=0;added=0;navs=[]
    for anchor,target in (links(text,url) if 200 <= result['status'] < 300 and not result['error'] else []):
        if NOTICE.search(anchor) and len(anchor)>18:notices+=1
        if 4<=len(anchor)<=100 and PLATFORM.search(anchor) and not NOISE.search(anchor):
            # Skip dated detail pages and same-host categories disguised as independent websites.
            target_p=urlsplit(target)
            detail=bool(re.search(r'/20\d{2}[/_-]?\d{2}[/_-]?\d{2}|[?&](?:article|news|content)id=',target,re.I))
            generic=anchor in ('招标公告','采购公告','公共资源交易','招标采购','政府采购','招投标','公共资源','采购信息','交易平台','招标信息')
            if not detail and not generic and (target_p.hostname!=host or directory):
                added+=add(c,dict(name=anchor,url=target,kind=infer_kind(anchor)),url,'公开目录链接' if directory else '网站关联链接')
        if urlsplit(target).hostname==host and NAV.search(anchor) and not NOISE.search(anchor) and len(anchor)<45 and depth<2:
            if not re.search(r'/20\d{2}|[?&](?:article|news|content)id=',target,re.I):navs.append((target,anchor))
    # A small navigation depth avoids crawling announcement bodies. New platform roots are unbounded.
    for target,anchor in list(dict.fromkeys(navs))[:8]:
        c.execute('INSERT OR IGNORE INTO pages(url,name,depth) VALUES(?,?,?)',(target,anchor,depth+1))
    status=('request_failed' if result['error'] else 'blocked' if result['status'] in (401,403,429,412,521) or BLOCKED.search(title+' '+soup.get_text(' ',strip=True)[:800]) else 'http_error' if not 200<=result['status']<300 else 'parked_or_closed' if PARKED.search(title+' '+soup.get_text(' ',strip=True)[:2000]) else 'notice_links_found' if notices else 'reachable_needs_review')
    c.execute('UPDATE pages SET status=?,checked_at=?,http_status=?,final_url=?,title=?,error=? WHERE url=?',(status,now(),result['status'],url,title,result['error'],result['url']))
    c.execute('UPDATE candidates SET status=?,checked_at=?,http_status=?,final_url=?,page_title=?,notice_links=?,error=?,body_sha256=? WHERE url=?', (status,now(),result['status'],url,title,notices,result['error'],result.get('sha',''),result['url']))
    return added,status


def directory(c,url, parser=None):
    old=c.execute('SELECT status FROM directory_pages WHERE url=?',(url,)).fetchone()
    if old and old[0]==200:return
    r=fetch(url);count=0;error=r['error']
    if r['status']==200 and not error:
        try:
            if parser:
                rows=parser(r['text'])
                for row in rows:count+=add(c,row,url,'公开目录数据')
            else:
                count,_=extract(c,r,directory=True)
        except (ValueError,KeyError,TypeError) as e:error=type(e).__name__+': '+str(e)[:150]
    c.execute('INSERT OR REPLACE INTO directory_pages VALUES(?,?,?,?,?)',(url,r['status'],count,now(),error))
    c.commit()
    print(json.dumps({'directory':url,'http':r['status'],'new':count,'error':error},ensure_ascii=False),flush=True)


def directories(c):
    for url in ['https://www.ggzy.gov.cn/platform/platform.html','https://www.ccgp.gov.cn/','https://www.tbrdh.com/','https://www.procdata.cn/site-map','https://www.toubiaoku.com/daohang','https://www.huison.cn/daohang/','https://www.etrading.cn/']:
        directory(c,url)
    def jet(text):
        a=json5.loads(text[text.index('['):text.rindex(']')+1]);rows=[]
        allowed={'公共资源','政府采购','央企采购','国企采购','工程招标','政采商城','交易平台','采购意向','招标计划'}
        for section in a:
            if section['sectionTitle'] in allowed:
                for x in section['content']:
                    rows.append(dict(name=x['title'],url=x['url'],kind=infer_kind(x['title'])))
        return rows
    directory(c,'https://jetbid.cn/js/all-site.js',jet)
    from scripts.refresh_source_directory import parse_arrays,GROUPS
    def biaoxun(text):
        return [dict(name=x['n'],url=x['u'],province=x.get('p',''),kind=GROUPS[g],sector_hint=x.get('g','')) for g,arr in parse_arrays(text).items() for x in arr if x.get('u') and x.get('n') and not re.search('仲裁|法律法规|贸易法委员会',x['n'])]
    directory(c,'https://biaoxun.vip/nav/data.js?v=164',biaoxun)
    # Public paginated directory: respect server page size and exhaust the advertised count.
    page=1
    while True:
        url=f'https://www.procdata.cn/site-map-prov-sites?page={page}&ps=50'
        r=fetch(url)
        if r['status']!=200 or r['error']:
            c.execute('INSERT OR REPLACE INTO directory_pages VALUES(?,?,?,?,?)',(url,r['status'],0,now(),r['error']));c.commit();break
        try:
            data=json.loads(r['text']);rows=data['sites'];size=int(data['ps']);total=int(data['count'])
            if not rows or size<=0:break
            new=0
            for row in rows:new+=add(c,dict(name=row['name'],url=row['url'],kind=infer_kind(row['name'])),url,'公采汇公开分页名录')
            c.execute('INSERT OR REPLACE INTO directory_pages VALUES(?,?,?,?,?)',(url,200,len(rows),now(),''));c.commit()
            if page%10==0 or page==1:print(json.dumps({'directory':'公采汇','page':page,'page_size':size,'advertised_records':total,'new':new},ensure_ascii=False),flush=True)
            if page*size>=total:break
            page+=1;time.sleep(.35)
        except (ValueError,KeyError,TypeError) as e:
            c.execute('INSERT OR REPLACE INTO directory_pages VALUES(?,?,?,?,?)',(url,r['status'],0,now(),type(e).__name__));c.commit();break


def verify(c,workers,limit):
    done=0;new=0;states=Counter();started=time.monotonic();loaded=set();backlog=[]
    def pending():
        nonlocal backlog
        backlog=[dict(p) for p in c.execute("SELECT * FROM pages WHERE status='pending' ORDER BY depth, CASE WHEN url LIKE '%gov.cn%' THEN 0 ELSE 1 END,url") if p['url'] not in loaded]
    pending()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        tasks={};hosts=set()
        while done<limit:
            while len(tasks)<workers and done+len(tasks)<limit:
                index=next((i for i,p in enumerate(backlog) if urlsplit(p['url']).hostname not in hosts),None)
                if index is None:break
                p=backlog.pop(index);loaded.add(p['url']);host=urlsplit(p['url']).hostname;hosts.add(host)
                tasks[pool.submit(fetch,p['url'])]=(p,host)
            if not tasks:
                pending()
                if not backlog:break
                continue
            completed,_=wait(tasks,return_when=FIRST_COMPLETED)
            for f in completed:
                p,host=tasks.pop(f);hosts.discard(host)
                added,status=extract(c,f.result(),p['name'],p['depth']);new+=added;done+=1;states[status]+=1
            c.commit()
            if done%50<len(completed):
                print(json.dumps({'checked_this_run':done,'new_candidates':new,'states':states,'pending_pages':c.execute("SELECT COUNT(*) FROM pages WHERE status='pending'").fetchone()[0],'elapsed_seconds':round(time.monotonic()-started)},ensure_ascii=False),flush=True)
            if done%500<len(completed):export(c)
            if not backlog:pending()
    export(c)


def export(c):
    OUT.mkdir(parents=True,exist_ok=True)
    receipt_path=OUT/'import-receipt.json'
    receipt=json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    imported=bool(receipt.get('applied'))
    rows=[dict(r) for r in c.execute('SELECT * FROM candidates ORDER BY province,kind,name,url')]
    for r in rows:
        r['final_url']=redact_url_secrets(r['final_url']);r['sectors']=json.loads(r['sectors']);r['evidence']=[dict(e) for e in c.execute('SELECT evidence_url,anchor,origin,observed_at FROM evidence WHERE identity=?',(r['identity'],))]
    (OUT/'candidates.json').write_text(json.dumps({'generated_at':now(),'complete':False,'imported':imported,'imported_snapshot_at':receipt.get('imported_at'),'records':rows},ensure_ascii=False,indent=2)+'\n')
    fields=['name','url','host','province','kind','level','sectors','status','http_status','page_title','final_url','notice_links','checked_at','evidence_urls']
    with (OUT/'candidates.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for r in rows:
            d={k:r.get(k,'') for k in fields};d['sectors']=';'.join(r['sectors']);d['evidence_urls']=';'.join(dict.fromkeys(x['evidence_url'] for x in r['evidence']));w.writerow(d)
    excluded=[dict(r) for r in c.execute('SELECT url,MIN(name) AS name,MIN(evidence_url) AS evidence_url,MIN(reason) AS reason,COUNT(*) AS evidence_count FROM excluded_links GROUP BY url ORDER BY url')]
    with (OUT/'excluded-links.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['url','name','evidence_url','reason','evidence_count']);w.writeheader();w.writerows(excluded)
    states=Counter(r['status'] for r in rows)
    report={'generated_at':now(),'complete':False,'imported':imported,'imported_snapshot_at':receipt.get('imported_at'),'candidate_entries':len(rows),'distinct_hosts':len({r['host'] for r in rows}),'states':dict(states),'frontier':dict(c.execute('SELECT status,COUNT(*) FROM pages GROUP BY status').fetchall()),'excluded_unique_urls':len(excluded),'excluded_link_evidence_records':c.execute('SELECT COUNT(*) FROM excluded_links').fetchone()[0],'directory_requests':c.execute('SELECT COUNT(*) FROM directory_pages').fetchone()[0],'directory_errors':[dict(r) for r in c.execute('SELECT * FROM directory_pages WHERE status!=200 OR error!=""')],'by_province':dict(Counter(r['province'] for r in rows)),'by_kind':dict(Counter(r['kind'] for r in rows)),'by_sector':dict(Counter(s for r in rows for s in r['sectors']))}
    with (OUT/'hosts.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['域名主机（非独立机构数量）','候选入口数','登记名称','候选入口'])
        grouped={}
        for r in rows:grouped.setdefault(r['host'],[]).append(r)
        for host,group in sorted(grouped.items()):w.writerow([host,len(group),';'.join(dict.fromkeys(r['name'] for r in group)),';'.join(r['url'] for r in group)])
    (OUT/'progress.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    with (OUT/'province-sector-gaps.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['地区','行业','候选入口数','发现公告链接入口数','审查状态'])
        for p in PROV_NAMES:
            for s in SECTORS:
                matched=[r for r in rows if r['province']==p and s in r['sectors']]
                w.writerow([p,s,len(matched),sum(r['status']=='notice_links_found' for r in matched),'尚待人工核对；存在条目也不代表找全' if matched else '缺少登记；需补查'])
    import_status=('已有快照导入工作台，详见 [导入回执](IMPORT.md)' if imported else '尚未导入工作台')
    summary=f'''# 全国招投标网站普查进度\n\n更新：{now()}\n\n状态：**普查进行中，未证明找全，{import_status}。**\n\n当前 {len(rows):,} 个去重入口，涉及 {report['distinct_hosts']:,} 个主机。入口数不等于独立机构数，同一统一平台的栏目、地区入口会保留但分开统计。\n\n核验状态：\n\n'''+''.join(f'- {k}：{v:,}\n' for k,v in states.items())+'''\n`notice_links_found` 只表示网页中发现公告形式的链接，仍需核对主办方与采购栏目；`reachable_needs_review` 只表示可访问，导入后仍需定位采购栏目，不能当作公告采集成功。网络失败、拦截、失效均单列，不算成功。\n\n- [候选名录 CSV](candidates.csv)：名称、网址、地区、行业、类型、层级、访问结果、依据。\n- [完整证据 JSON](candidates.json)：每项保留所有来源网页和发现时间。\n- [地市×类型查漏表](city-type-checklist.csv)及[20行业门类查漏表](industry20-checklist.csv)。\n- [域名主机去重汇总](hosts.csv)和[排除记录](excluded-links.csv)。\n- [方法、证据和未完成事项](METHOD.md)。\n- [省份×行业缺口表](province-sector-gaps.csv)：不能以某格非零作为完成标记。\n- [机器可读进度](progress.json)。\n\n全国全量网站没有可据以证明完备的单一名册；目录有遗漏、旧域名、动态页面。历史登记只作为线索。层级和行业为自动推断，标记为待核实；“全国/待核实”地区条目不摊派到31省，不虚增覆盖率。\n'''
    (OUT/'PROGRESS.md').write_text(summary)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['seed','directories','verify','export']);p.add_argument('--existing');p.add_argument('--workers',type=int,default=12,choices=range(1,17));p.add_argument('--limit',type=int,default=100000)
    args=p.parse_args();c=connect()
    if args.command=='seed':seed(c,args.existing)
    elif args.command=='directories':directories(c)
    elif args.command=='verify':verify(c,args.workers,args.limit)
    report=export(c);print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
