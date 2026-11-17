"""Build explicit geographic/type/industry checklists, without a completeness claim."""
import csv
import json
import re
from collections import Counter
from pathlib import Path
from scripts.census_tender_sites import OUT,PROV_NAMES,connect,export,source_sectors

# GB/T 4754's twenty sections; matching is a research lead, not audited classification.
# Baseline reference: https://www.stats.gov.cn/zs/tjws/tjbz/202301/t20230101_1903769.html
INDUSTRIES = [
 ('A','农、林、牧、渔业',r'农|林业|渔|牧业|畜牧|种子|森工'),
 ('B','采矿业',r'煤|矿业|矿产|石油|海油|地质|黄金|有色'),
 ('C','制造业',r'制造|钢铁|钢材|汽车|装备|机械|机床|船舶|电子|电科|食品|烟草|中烟|化工|纺织|轻工|水泥|建材|制药|医药|航空工业|航天|酒业|乳业|冶金|铝业|铜业|造纸|中车'),
 ('D','电力、热力、燃气及水生产和供应业',r'电力|电网|能源|华能|华电|大唐|电投|电建|能建|发电|热电|热力|燃气|水务|供水|自来水|风电|光伏|核电|中核|中广核|水电'),
 ('E','建筑业',r'建筑|建工|工程|中铁|铁建|中交|路桥|装饰|建设'),
 ('F','批发和零售业',r'商贸|商业|百货|零售|贸易|供销|商场|中粮|粮油|烟草'),
 ('G','交通运输、仓储和邮政业',r'交通|铁路|高速|公路|港口|港务|航运|机场|航空公司|国航|南航|东航|轨道|地铁|物流|仓储|邮政|货运'),
 ('H','住宿和餐饮业',r'酒店|宾馆|饭店|餐饮|锦江|首旅|华住'),
 ('I','信息传输、软件和信息技术服务业',r'通信|电信|移动|联通|广电|广播|信息|软件|数据|互联网|网络'),
 ('J','金融业',r'银行|保险|证券|金融|信托|基金|期货|资产管理'),
 ('K','房地产业',r'房地产|地产|置业|房产|住房|物业'),
 ('L','租赁和商务服务业',r'租赁|咨询|招标|代理|会计|审计|法律|律师|保安|人力|劳务|招商|旅游|旅行'),
 ('M','科学研究和技术服务业',r'科学院|研究院|研究所|实验室|科研|科技|设计院|检测|勘察|地质|气象|地震|测绘'),
 ('N','水利、环境和公共设施管理业',r'水利|环保|环境|生态|市政|园林|园区|景区|公园|污水|固废|环卫'),
 ('O','居民服务、修理和其他服务业',r'居民服务|家政|殡仪|殡葬|公墓|维修|修理|清洁|保洁'),
 ('P','教育',r'大学|学院|学校|教育|职教|幼儿园'),
 ('Q','卫生和社会工作',r'医院|卫生|医疗|疾控|妇幼|血液|养老|福利|康养|民政|社会工作'),
 ('R','文化、体育和娱乐业',r'文化|体育|文旅|传媒|出版|报业|博物|图书|剧院|影业|电视|广播|演艺'),
 ('S','公共管理、社会保障和社会组织',r'政府|机关|政务|公共资源|财政|公安|消防|应急|司法|法院|检察|税务|海关|社保|协会|工会|军队|部队|武警'),
 ('T','国际组织',r'联合国|世界银行|亚洲开发银行|国际组织|亚投行'),
]


def city_aliases(name,stem):
 aliases={name,stem}
 if name.endswith('自治州'):
  prefix=re.split(r'土家族|苗族|藏族|羌族|朝鲜族|彝族|哈尼族|壮族|傣族|白族|景颇族|傈僳族|回族|蒙古族|柯尔克孜族|哈萨克族|布依族|侗族',name)[0]
  if prefix!=name and len(prefix)>=2:aliases.update((prefix+'州',prefix))
 return aliases


def main():
 c=connect();rows=[dict(r) for r in c.execute('SELECT * FROM candidates')]
 # Supplement province inference using the explicitly dated, secondary city baseline.
 baseline=OUT/'geography-baseline-2023.json'
 cities=[]
 if baseline.exists():
  data=json.loads(baseline.read_text())['provinces']
  for p in data:
   prov=next((x for x in PROV_NAMES if p['name'].startswith(x)),p['name'])
   if p['code'] in ('11','12','31','50'):
    cities.append((prov,p['code'],p['name'],prov))
   for city in p['children']:
    if len(city['code']) != 4:continue
    if city['name'] in ('市辖区','县','省直辖县级行政区划','自治区直辖县级行政区划'):continue
    stem=re.sub(r'(市|地区|盟)$','',city['name'])
    cities.append((prov,city['code'],city['name'],stem))
  for r in rows:
   if r['province']=='待核实':
    matches={p for p,_,name,stem in cities if any(a in r['name'] for a in city_aliases(name,stem))}
    if len(matches)==1:
     r['province']=matches.pop();c.execute('UPDATE candidates SET province=? WHERE identity=?',(r['province'],r['identity']))
  c.commit()
 with (OUT/'city-type-checklist.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.writer(f);w.writerow(['省份','区划代码（2023基线）','地市','平台类型','候选数','候选网址','核对状态'])
  for p,code,name,stem in cities:
   for kind in ('政府采购','公共资源','企业招标','医疗卫生','高校科研','金融采购','招标代理','行业平台','综合招标'):
    matched=[r for r in rows if any(a in r['name'] for a in city_aliases(name,stem)) and r['province']==p and r['kind']==kind]
    w.writerow([p,code,name,kind,len(matched),';'.join(r['url'] for r in matched),'有线索，待逐项核对' if matched else '未定位独立入口或统一平台归属，待查'])
 with (OUT/'industry20-checklist.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.writer(f);w.writerow(['门类代码','行业门类','地区','候选入口数','待查状态'])
  for code,name,pattern in INDUSTRIES:
   for p in ['全国']+PROV_NAMES:
    matched=[r for r in rows if r['province']==p and re.search(pattern,r['name'])]
    w.writerow([code,name,p,len(matched),'名称匹配仅为线索；未逐机构证明找全'])
 # Generated search checklist never masquerades as executed research.
 queries=[]
 for p in PROV_NAMES:
  for kind in ('政府采购','公共资源交易','国企阳光采购','医药招采','高校招标采购','金融集中采购','农村产权交易','小额工程采购'):
   queries.append({'query':f'{p} {kind} 官方 网站 导航','status':'pending','dimension':'province-type'})
 for p,code,name,stem in cities:
  queries.append({'query':f'{name} 公共资源交易 政府采购 官方 网站','status':'pending','dimension':'city'})
 for code,name,pattern in INDUSTRIES:
  queries.append({'query':f'{name} 招标采购 官方平台 网站导航','status':'pending','dimension':'industry'})
 (OUT/'search-checklist.json').write_text(json.dumps({'note':'这些是待查检索任务，并非已经搜索或完成的证据；2023地区基线尚待最新官方区划校对。','tasks':queries},ensure_ascii=False,indent=2)+'\n')
 export(c)
 print(json.dumps({'baseline_cities':len(cities),'city_type_cells':len(cities)*9,'pending_searches':len(queries)},ensure_ascii=False))


if __name__=='__main__':main()
