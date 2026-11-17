"""Read published SPA navigation data, without executing downloaded JavaScript."""
import json
import re
from scripts.census_tender_sites import connect,fetch,add,identity,export
from apps.workbench.bidmonitor_workbench.collectors.registry import normalize_source


def main():
 c=connect();url='https://ggzy.yn.gov.cn/static/js/app.78b49860.js';r=fetch(url)
 if r['status']!=200 or r['error']:raise RuntimeError('云南官方导航资源无法获取，未生成地区入口')
 text=r['text']
 # Both the city codes and the URL template must actually occur in the official bundle.
 template='https://ggzy.yn.gov.cn/ynggfwpt-home-web/#/homePage?page='
 if template not in text:raise ValueError('云南导航模板变化，需人工核查')
 choices=re.findall(r'\{name:"([^"<>]+)",code:"([a-z]{2,4})"\}',text)
 expected={'km','zt','qj','yx','bs','cx','hh','ws','pe','bn','dl','dh','lj','nj','dq','lc'}
 full={'楚雄州':'楚雄彝族自治州','红河州':'红河哈尼族彝族自治州','文山州':'文山壮族苗族自治州','西双版纳州':'西双版纳傣族自治州','大理州':'大理白族自治州','德宏州':'德宏傣族景颇族自治州','怒江州':'怒江傈僳族自治州','迪庆州':'迪庆藏族自治州'}
 found={code:name for name,code in choices if code in expected}
 if set(found)!=expected:raise ValueError('云南官方地区导航不完整，未生成推测地址')
 n=0
 for code,name in found.items():
  name=full.get(name,name)
  row=dict(name=name+'公共资源交易平台（云南统一门户）',url=template+code,kind='公共资源',province='云南')
  n+=add(c,row,url,'云南官方脚本中明确发布的地区名称、代码及跳转模板（共享门户，不计为独立网站）')
  c.execute('UPDATE candidates SET level=? WHERE identity=?',('地市入口（省级统一平台）',identity(normalize_source(row))))
 c.commit();export(c);print(json.dumps({'published_city_routes':len(found),'new':n},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
