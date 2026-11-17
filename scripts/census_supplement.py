"""Additional public navigation sources with explicit parsing/provenance."""
import json
import re
import string
import time
from urllib.parse import urljoin,urlsplit
from bs4 import BeautifulSoup
from scripts.census_tender_sites import connect,fetch,directory,extract,add,export,now


def main():
 c=connect()
 urls=['https://www.gtba.org.cn/site/socialPlatForm/index','https://www.howbid.cn/links/ggfw','https://www.zcjb.com.cn/','https://biaoxun.vip/quanguo-gaoxiao-caigou-pingtai-daquan/','https://www.getbidwin.cn/zhaobiao-wangzhan-daohang.html','https://www.nongjiao.com/','https://m.nongjiao.com/','https://www.ahaee.com/','https://www.procdata.cn/market','https://bulletin.cebpubservice.com/xxfbcms/media.html','https://www.cebpubservice.com/','https://deal.ggzy.gov.cn/platform/platform.html']
 for url in urls:directory(c,url)
 url='https://www.getbidwin.cn/zhaobiao-wangzhan-daohang.html';r=fetch(url)
 if r['status']==200:
  soup=BeautifulSoup(r['text'],'lxml');n=0
  for a in soup.select('a[href]'):
   if a.get_text(strip=True)!='官网↗':continue
   prev=a.find_previous_sibling('a');li=a.find_parent('li')
   if not prev or not li:continue
   region=li.find('strong');province=region.get_text(strip=True) if region else ''
   city=prev.get_text(strip=True)
   if 2<=len(city)<=20:
    n+=add(c,dict(name=city+'公共资源交易平台',url=urljoin(url,a['href']),kind='公共资源',province=province),url,'城市导航相邻城市名称与官网链接（主办方待核实）')
  c.commit();print('城市导航新增',n,flush=True)
 # Newpoint's published 4 categories x 26 initial-letter files, no truncation at homepage cards.
 for category,kind in {'035001':'公共资源','035002':'招标代理','035003':'高校科研','035004':'企业招标'}.items():
  for letter in string.ascii_uppercase:
   url=f'https://www.etrading.cn/json/websiteheadZiZhanInfo_{category}_{letter}.json'
   def parse(text):
    data=json.loads(text)
    if not isinstance(data,list):raise ValueError('目录结构变化')
    return [dict(name=x['zqname'],url=x['urlname'],kind=kind,province=x.get('province','')) for x in data if isinstance(x,dict) and x.get('zqname') and x.get('urlname') not in (None,'','/')]
   directory(c,url,parse);time.sleep(.35)
 export(c)


if __name__=='__main__':main()
