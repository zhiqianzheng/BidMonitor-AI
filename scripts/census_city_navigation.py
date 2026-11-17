"""Read explicitly linked regional portals; never synthesize city hostnames."""
import json
import re
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from urllib.parse import urljoin,urlsplit
from bs4 import BeautifulSoup
from scripts.census_tender_sites import connect,fetch,add,export,OUT,STATE,PROV_NAMES
from apps.workbench.bidmonitor_workbench.collectors.sources import catalogue


def main():
 c=connect();geo=json.loads((OUT/'geography-baseline-2023.json').read_text())['provinces'];regions={}
 for p in geo:
  prov=next((x for x in PROV_NAMES if p['name'].startswith(x)),p['name'])
  regions[p['name']]=prov;regions[prov]=prov
  for city in p['children']:
   if city['name'] in ('市辖区','县'):continue
   regions[city['name']]=prov;regions[re.sub(r'(市|地区|盟)$','',city['name'])]=prov
 seeds={s['url']:s['name'] for s in catalogue() if s['kind'] in ('公共资源','政府采购') and s.get('province') in PROV_NAMES}
 # Include discovered city portal roots so province/city/county link lists can cross-enrich.
 for r in c.execute("SELECT name,url FROM candidates WHERE kind='公共资源'"):
  seeds.setdefault(r['url'],r['name'])
 new=0;checked=0
 with ThreadPoolExecutor(max_workers=12) as pool:
  tasks={pool.submit(fetch,url):(url,name) for url,name in seeds.items()}
  for f in as_completed(tasks):
   url,parent=tasks[f];r=f.result();checked+=1
   if r['status']!=200 or r['error']:continue
   soup=BeautifulSoup(r['text'],'lxml')
   for a in soup.select('a[href],option[value]'):
    label=re.sub(r'\s+','',a.get_text(' ',strip=True));region=regions.get(label)
    if not region:continue
    href=a.get('href') or a.get('value') or '';target=urljoin(r['final'],href);parsed=urlsplit(target)
    if parsed.scheme not in ('https','http') or not parsed.hostname:continue
    host=parsed.hostname
    if not re.search(r'ggzy|gzyjy|ggfw|jyzx|zfcg|ccgp|ggjy|ggzyzx',host,re.I):continue
    procurement=bool(re.search(r'ccgp|zfcg',host,re.I));kind='政府采购' if procurement else '公共资源'
    name=label+('政府采购网' if procurement else '公共资源交易平台')
    new+=add(c,dict(name=name,url=target,kind=kind,province=region),r['final'],'已发布地区导航链接；短标签按上下文整理名称，待核实')
   c.commit()
   if checked%100==0:print(json.dumps({'navigation_pages_checked':checked,'total':len(seeds),'new':new},ensure_ascii=False),flush=True)
 export(c);print(json.dumps({'navigation_pages_checked':checked,'new':new},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
