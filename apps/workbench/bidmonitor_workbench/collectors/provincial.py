"""Province-owned public feeds. National aggregation remains a separate source."""
import copy
import base64
import json
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urljoin, urlsplit, urldefrag

from bs4 import BeautifulSoup

from .detail import normalized_date
from ..storage.taxonomy import classify_notice


# Category codes observed in each official site's public navigation. Codes are not
# interchangeable between provinces. Administrative notices are excluded.
ZCY = {
    '14': ('ZcyAnnouncement6 ZcyAnnouncement1 ZcyAnnouncement2 ZcyAnnouncement3 ZcyAnnouncement4 ZcyAnnouncement5 ZcyAnnouncement10 ZcyAnnouncement11 ZcyAnnouncement24', '/site/detail'),
    '22': ('ZcyAnnouncement1 ZcyAnnouncement2 ZcyAnnouncement3 ZcyAnnouncement4 ZcyAnnouncement5 ZcyAnnouncement10', '/site/detail'),
    '31': ('77-938917 77-489585', '/site/detail'),
    '33': ('110-606633 110-115691', '/site/detail'),
    '34': ('ZcyAnnouncement1 ZcyAnnouncement2 ZcyAnnouncement4 ZcyAnnouncement5 ZcyAnnouncement7', '/site/detail'),
    '43': ('160-396330 160-506896', '/luban/front/detail'),
    '45': ('61-266648 ZcyAnnouncement1 ZcyAnnouncement2 ZcyAnnouncement3 ZcyAnnouncement4 ZcyAnnouncement5 ZcyAnnouncement6 ZcyAnnouncement7 ZcyAnnouncement10 ZcyAnnouncement11 ZcyAnnouncement20 ZcyAnnouncement21 ZcyAnnouncement23', '/site/detail'),
    '52': ('ZcyAnnouncement1 ZcyAnnouncement3 ZcyAnnouncement4 ZcyAnnouncement5', '/site/detail'),
    '63': ('ZcyAnnouncement1 ZcyAnnouncement2 ZcyAnnouncement3 ZcyAnnouncement4 ZcyAnnouncement11 ZcyAnnouncement5 ZcyAnnouncement14 ZcyAnnouncement22', '/site/detail'),
    '65': ('ZcyAnnouncement2 ZcyAnnouncement88 ZcyAnnouncement1 ZcyAnnouncement4 ZcyAnnouncement5 ZcyAnnouncement3 ZcyAnnouncement11', '/site/detail'),
}

# Explicit announcement paths, never a broad title-keyword scrape of news pages.
STATIC = {
    'trade-50': (r'/trade/\d+/\d+\?categoryNum=\d+$', r'(?!)'),
    'trade-36': (r'/jyxx/(?:\d+/)+\d{8}/[a-fA-F0-9-]+\.html$', r'(?!)'),
    'trade-37': (r'/(?:jsgc[a-z]+|jyxx[a-z]+|zfcg[a-z]+|gqcg[a-z]+)/\d+\.jhtml(?:\?type=\d+)?$',
                 r'/(?:jsgc[a-z]+|jyxx[a-z]+|zfcg[a-z]+|gqcg[a-z]+)/index(?:_\d+)?\.jhtml$'),
    'trade-41': (r'/jyxx/(?:\d+/)+\d{8}/[a-fA-F0-9-]+\.html$', r'(?!)'),
    'gov-54': (r'/freecms/site/xizang/xzcggg/info/20\d{2}/\d+\.html$', r'/freecms/site/xizang/xzcggg/index(?:_\d+)?\.html$'),
    'trade-54': (r'/jyxx[a-z]+/\d+\.jhtml$', r'/jyxx[a-z]+/(?:index(?:_\d+)?\.jhtml)?$'),
    'trade-31': (r'/(?:jyxx[a-z]+|gqcg[a-z]+)/\d+(?:\?isIndex=y)?$', r'/(?:jyxx[a-z]+|gqcg[a-z]+)/(?:index(?:_\d+)?\.jhtml)?$'),
    'trade-13': (r'/hbggfwpt/jydt/(?:\d+/)+\d{8}/[a-f0-9-]+\.html$', r'/hbggfwpt/jydt/(?:\d+/)*(?:\w+\.html)?$'),
    'trade-51': (r'/jyxx/(?:\d+/)+\d{8}/[A-Za-z0-9_-]+\.html$', r'/jyxx/(?:\d+/)*(?:\w+\.html)?$'),
    'gov-13': (r'/(?:[a-z_]+/)+cggg/(?:[a-zA-Z_]+/)+\d{6}/t\d{8}_\d+\.html$',
               r'/province/cggg/(?:[a-zA-Z_]+/)+(?:index(?:_\d+)?\.html)?$'),
    'gov-11': (r'/xxgg/(?:sjxxgg|qjxxgg)/[^/]+/\d{4}/\d{2}/[a-f0-9]+\.htm',
               r'/xxgg/(?:sjxxgg|qjxxgg)/(?:\w+/)?A\d+index_\d+\.htm'),
    'trade-12': (r'/jyxx[a-z]+/\d+\.jhtml', r'/jyxx[a-z]+/(?:index(?:_\d+)?\.jhtml)?$'),
    'trade-14': (r'/jyxx[a-z]+/\d+\.jhtml', r'/jyxx[a-z]+/(?:index(?:_\d+)?\.jhtml)?$'),
    'trade-23': (r'/jyfwdt/003002/(?:\d+/)+\d{8}/[A-Za-z0-9_-]+\.html', r'/jyfwdt/003002/(?:\d+/)*(?:\w+\.html)?$'),
    'trade-33': (r'/jyxxgk/(?:\d+/)+\d{8}/[a-f0-9-]+\.html', r'/jyxxgk/(?:\d+/)*(?:\w+\.html)?$'),
    'trade-45': (r'/jyfw/jyfw_(?:gcjs|zfcg|tdky|cqjy|tdkq|gycq|yxcg)/.+/t\d+\.shtml', r'/jyfw/jyfw_(?:gcjs|zfcg|tdky|cqjy|tdkq|gycq|yxcg)/.+/(?:index(?:_\d+)?\.(?:s?html))?$'),
    'trade-46': (r'/ggzy/(?:ggzy/)?(?:jgzbgg|jgzbgs|cggg|cgzbgg|jsqtgg|zfcgqtgg|gpgg|cjgg|cpgg)/\d+\.jhtml', r'/ggzy/(?:ggzy/)?(?:jgzbgg|jgzbgs|cggg|cgzbgg|jsqtgg|zfcgqtgg|gpgg|cjgg|cpgg)/(?:index(?:_\d+)?\.jhtml)?$'),
    'trade-63': (r'/ggzy/projectDetail\.html\?infoid=[a-f0-9-]+&categorynum=\d+', r'/ggzy/(?:jyxx|jydt)/(?:\w+/)*(?:\w+\.html)?$'),
    'trade-64': (r'/dzjy/(?:\d+/)+\d{8}/[a-f0-9-]+\.html', r'/dzjy/(?:\d+/)+(?:\w+\.html)?$'),
    'trade-65': (r'/xinjiangggzy_new/jyxx/(?:\d+/)+\d{8}/[a-f0-9-]+\.html', r'/xinjiangggzy_new/jyxx/(?:\d+/)+(?:\w+\.html)?$'),
}

EPOINT = {
    'trade-13': ('/inteligentsearchnew/rest/esinteligentsearch/getFullTextDataNew', '001', '003', 'title', '/hbggfwpt'),
    'trade-51': ('/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew', '001', '002', '', ''),
    'trade-23': ('/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew', '012', '003002', '', ''),
    'trade-33': ('/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew', '001', '002', 'title', ''),
    'trade-64': ('/interface_wz/rest/esinteligentsearch/getFullTextDataNew', '', '001001', 'title', ''),
    'trade-65': ('/inteligentsearchnew/rest/esinteligentsearch/getFullTextDataNew', '002', '001', 'title;projectnum;projectname', '/xinjiangggzy_new'),
}


def direct_sources(base):
    result = []
    for s in base:
        key = s['id']
        code = key.removeprefix('gov-')
        if key == 'gov-61':
            result.append(dict(id='direct-'+key, name=s['name'], province=s['province'], kind=s['kind'],
                               url='https://www.ccgp-shaanxi.gov.cn/', adapter='province_shaanxi_home', route_key=key,
                               channel='省站直采', scope='省市县公开首页 9 类公告及正文；深层查询需验证码，非全量'))
        elif key == 'trade-43':
            result.append(dict(id='direct-'+key, name=s['name'], province=s['province'], kind=s['kind'],
                               url='https://www.hnsggzy.com/', adapter='province_hunan_trade', route_key=key,
                               channel='省站直采', scope='工程交易公开列表分页及标段关联公告；其他交易类型尚未接入'))
        elif key == 'trade-35':
            result.append(dict(id='direct-'+key, name=s['name'], province=s['province'], kind=s['kind'],
                               url='https://ggzyfw.fj.gov.cn/', adapter='province_fujian_trade', route_key=key,
                               channel='省站直采', scope='工程、采购、土地、矿业权、产权和其他交易；原站公开接口分页与日期窗口续采'))
        elif key in ('trade-42', 'trade-53'):
            result.append(dict(id='direct-'+key, name=s['name'], province=s['province'], kind=s['kind'],
                               url='https://www.hbggzyfwpt.cn/' if key == 'trade-42' else 'https://ggzy.yn.gov.cn/',
                               adapter='province_hubei_trade' if key == 'trade-42' else 'province_yunnan_trade',
                               route_key=key, channel='省站直采', scope='工程与采购公开栏目分页；逐栏目日期窗口续采；其他栏目尚未覆盖'))
        elif key in ('gov-50', 'trade-15'):
            result.append(dict(id='direct-'+key, name=s['name'], province=s['province'], kind=s['kind'],
                               url='https://www.ccgp-chongqing.gov.cn/' if key == 'gov-50' else 'https://ggzyjy.nmg.gov.cn/',
                               adapter='province_chongqing' if key == 'gov-50' else 'province_neimenggu_trade',
                               route_key=key, channel='省站直采', scope='原站公开接口分页；最新公告＋固定日期窗口补采'))
        elif key == 'trade-34':
            result.append(dict(id='direct-'+key, name=s['name'], province=s['province'], kind=s['kind'],
                               url='https://ggzy.ah.gov.cn/', adapter='province_anhui_trade', route_key=key, channel='省站直采',
                               scope='省市县公开首页工程、采购、土地矿权、产权和其他交易；尚未覆盖全部历史'))
        elif key in ('gov-21', 'gov-53'):
            result.append(dict(id='direct-'+key, name=s['name'], province=s['province'], kind=s['kind'],
                               url=s['url'], adapter='province_liaoning' if key == 'gov-21' else 'province_yunnan',
                               route_key=key, channel='省站直采', scope='省采购网公开首页分类接口；近期公告直采，深层检索尚未覆盖'))
        elif key in ('gov-62', 'gov-15'):
            from .provincial_more import GPCMS
            result.append(dict(id='direct-'+key, name=s['name'], province=s['province'], kind=s['kind'],
                               url=GPCMS[key][0], adapter='province_gpcms_home', route_key=key, channel='省站直采',
                               scope='原站公开首页各类采购公告；包含结构化字段；深层查询验证尚未接入，非全量'))
        elif key == 'trade-52':
            result.append(dict(id='direct-'+key, name=s['name'], province=s['province'], kind=s['kind'],
                               url='https://ggzy.guizhou.gov.cn/', adapter='province_guizhou', channel='省站直采',
                               scope='省交易平台公开接口；工程、采购、土地、产权及其他交易；按栏目和日期分页续采'))
        elif key in ('gov-12', 'gov-41'):
            result.append(dict(id='direct-'+key, name=s['name'], province=s['province'], kind=s['kind'],
                               url='https://zfcg.henan.gov.cn/' if code == '41' else s['url'],
                               adapter='province_home', route_key=key, channel='省站直采',
                               scope='省官网首页省市县采购栏目；每轮刷新；深层查询受验证或限流限制，非全量'))
            if key == 'gov-12':
                result[-1].update(adapter='province_tianjin', scope='公开首页＋市区采购栏目分页；低频轮转与断点续采，尚非历史全量')
        elif key in ('gov-23', 'gov-64'):
            result.append(dict(id='direct-'+key, name=s['name'], province=s['province'], kind=s['kind'],
                               url=s['url'], adapter='province_hlj' if code == '23' else 'province_nx', channel='省站直采',
                               scope='公开首页公告；深层查询需原站验证码，采集范围以实际状态为准'))
            if code == '64':
                result[-1]['url'] = 'https://www.ccgp-ningxia.gov.cn/NXGPPSP_CMS/public/NXGPP_MAIN/dynamic/index.html'
        elif key.startswith('gov-') and code in ZCY:
            codes, detail = ZCY[code]
            result.append(dict(id='direct-'+key, name=s['name'], province=s['province'], kind=s['kind'],
                               url=s['url'], adapter='province_zcy', channel='省站直采',
                               categories=codes.split(), detail_path=detail, home_only=code == '65',
                               scope='省官网公开公告接口；按栏目分页，定时续采；各栏目范围以原站为准'))
        elif key in STATIC:
            result.append(dict(id='direct-'+key, name=s['name'], province=s['province'], kind=s['kind'],
                               url=s['url'], adapter='province_html', channel='省站直采', route_key=key,
                               scope='省官网公开列表直采；首页各栏目＋可识别分页；动态列表仍可能未覆盖'))
            if key == 'trade-23':
                result[-1]['url'] = 'https://ggzyjyw.hlj.gov.cn/'
            if key == 'gov-13':
                result[-1]['url'] = 'http://www.ccgp-hebei.gov.cn/province/'
            if key == 'trade-51':
                result[-1]['url'] = 'https://ggzyjy.sc.gov.cn/'
            if key == 'trade-54':
                result[-1]['url'] = 'https://ggzy.xizang.gov.cn/'
            if key == 'trade-41':
                result[-1].update(url='http://hnsggzyjy.henan.gov.cn/',
                                  scope='省交易中心公开首页工程、采购、产权等公告；深层分页需验证码，非全量')
            if key == 'trade-36':
                result[-1].update(url='http://www.jxsggzy.cn/', scope='省交易平台公开首页交易公告及成交公示；深层检索尚未接入，非全量')
            if key == 'trade-37':
                result[-1].update(url='https://ggzyjy.shandong.gov.cn/', scope='省交易平台公开首页各交易栏目；修正旧链接协议，动态检索尚未覆盖')
            if key == 'trade-50':
                result[-1].update(url='https://www.cqggzy.com/', scope='公开首页可见产权公告；深层交易列表访问受限，其他类型及历史尚未覆盖')
            if key == 'gov-54':
                result[-1].update(adapter='province_xizang', scope='省采购网公开接口分页；最新列表＋固定日期窗口补采')
            if key in ('trade-31', 'trade-54'):
                result[-1]['scope'] = '省官网公开交易栏目公告直采；脚本静态链接解析，动态检索及历史分页尚未覆盖'
            if key in EPOINT:
                result[-1].update(adapter='province_epoint', scope='省交易平台公开检索接口；工程、采购、产权等公开交易栏目；分页续采')
            if key in ('trade-45', 'trade-63'):
                result[-1].update(adapter='province_public_search', scope=('省官网公开分页检索＋首页补充；重叠翻页续采' if key == 'trade-45' else '省官网公开检索前 490 条＋首页补充；更深分页需原站验证'))
    return result


def clean_text(value):
    return re.sub(r'\s+', ' ', BeautifulSoup(str(value or ''), 'lxml').get_text(' ', strip=True)).strip()


def timestamp(value):
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value / 1000, timezone(timedelta(hours=8))).isoformat(timespec='seconds')
    return normalized_date(str(value or ''))


def zcy_row(record, source, base, parent=None):
    key, title = record.get('articleId'), clean_text(record.get('title'))
    if not isinstance(key, str) or not key or not title:
        return None
    query = {'articleId': key}
    if parent:
        query['parentId'] = str(parent)
    kind = classify_notice(title)
    if kind == '其他':
        kind = classify_notice(record.get('pathName') or record.get('purchaseMethod') or '')
    return dict(title=title[:500], source=source['name'], region=source['province'],
                url=urljoin(base, source['detail_path'])+'?'+urlencode(query),
                published_at=timestamp(record.get('publishDate') or record.get('pubDate')),
                deadline=timestamp(record.get('bidOpeningTime')),
                purchaser=record.get('purchaseName') or '', project_no=record.get('projectCode') or '',
                notice_type=kind)


def collect_zcy(source, stop, pages, html_fetch, json_fetch):
    from .feeds import FeedUnavailable
    # Resolve genuine homepage redirects (e.g. Anhui's new canonical host).
    _, base = html_fetch(source['url'])
    base = urljoin(base, '/')
    state = copy.deepcopy(source.get('checkpoint') or {})
    rows, warnings, seen = [], [], set()
    incomplete, verified, latest_limited = False, 0, False
    retry_after, deferred = 0, False
    categories = source['categories']
    rotation = int(state.get('_next_category', 0)) % len(categories)
    categories = categories[rotation:] + categories[:rotation]
    calls = 0
    def query(*args, **kwargs):
        nonlocal calls
        if calls >= 42:
            raise FeedUnavailable('本轮请求预算已用完，下轮从当前栏目继续', 'deferred')
        calls += 1
        return json_fetch(*args, **kwargs)
    local = datetime.now(timezone(timedelta(hours=8)))
    yesterday = (local.date() - timedelta(days=1)).isoformat()
    def add(records, parent=None):
        if not isinstance(records, list):
            raise FeedUnavailable('省站公告列表结构变化', 'needs_adapter')
        for record in records:
            row = zcy_row(record, source, base, parent)
            if row and row['url'] not in seen:
                seen.add(row['url']); rows.append(row)
    for code in categories:
        if stop.is_set():
            break
        try:
            if source.get('home_only'):
                response = query(base+'portal/searchHome', json_data={'code': code, 'pageSize': 20, 'needTotal': True})
                data = response.get('result', {}).get('data', {})
                if response.get('success') is not True or not isinstance(data.get('children'), list):
                    raise FeedUnavailable('省站首页公告接口返回异常', 'needs_adapter')
                # A parentId is a navigation hint, not part of announcement identity.
                add(data['children'])
                verified += 1
                incomplete = True
                continue
            def page(number, bounds=None):
                params = dict(categoryCode=code, pageNo=number, pageSize=15)
                if bounds:
                    params.update(publishDateBegin=int(datetime.fromisoformat(bounds['start']+'T00:00:00+08:00').timestamp()*1000),
                                  publishDateEnd=int(datetime.fromisoformat(bounds['end']+'T23:59:59+08:00').timestamp()*1000))
                response = query(base+'portal/category', json_data=params)
                data = response.get('result', {}).get('data', {})
                if response.get('success') is True and data.get('empty') is True and data.get('data') is None and data.get('total') is None:
                    data = {'data': [], 'total': 0}
                if response.get('success') is not True or not isinstance(data.get('data'), list) or 'total' not in data:
                    raise FeedUnavailable('省站分页接口结构变化或访问受限', 'needs_adapter')
                if bounds:
                    for r in data['data']:
                        published = timestamp(r.get('publishDate'))[:10]
                        if not published or not bounds['start'] <= published <= bounds['end']:
                            raise FeedUnavailable('省站未按指定日期筛选，暂停补采进度', 'needs_adapter')
                    signature = '|'.join(str(r.get('articleId')) for r in data['data'])
                    if number > 1 and signature and signature == bounds.get('signature'):
                        raise FeedUnavailable('省站重复返回补采页，暂停推进进度', 'needs_adapter')
                add(data['data'])
                return data
            # Refresh newest pages every run; separately drain a fixed, closed-day
            # window so a burst of new notices cannot indefinitely hide older rows.
            previous = None
            for number in range(1, pages+1):
                data = page(number)
                signature = tuple(r.get('articleId') for r in data['data'])
                if signature and signature == previous:
                    raise FeedUnavailable('省站重复返回同一页，已停止翻页', 'needs_adapter')
                previous = signature
                if number * 15 >= int(data['total']) or not data['data']:
                    break
                if stop.wait(0.5):
                    break
            latest_limited |= int(data['total']) > pages*15
            verified += 1
            progress = state.get(code, {})
            if not progress.get('end') or progress.get('done') and progress['end'] < yesterday:
                start = (datetime.fromisoformat(progress['end']).date()-timedelta(days=2)).isoformat() if progress.get('end') else (local.date()-timedelta(days=7)).isoformat()
                progress = {'start': start, 'end': yesterday, 'page': 1, 'done': False}
            if not progress.get('done'):
                for _ in range(pages):
                    if stop.wait(0.5):
                        break
                    number = progress['page']
                    data = page(number, progress)
                    # Persist only after a fully parsed page; store commits the
                    # checkpoint only after every returned row has been stored.
                    progress['page'] = number+1
                    progress['signature'] = '|'.join(str(r.get('articleId')) for r in data['data'])
                    progress['done'] = number*15 >= int(data['total']) or not data['data']
                    state[code] = dict(progress)
                    if progress['done']:
                        break
            incomplete |= not progress.get('done', False)
        except ValueError as error:
            if getattr(error, 'status', '') == 'deferred':
                deferred = True
                state['_next_category'] = source['categories'].index(code)
                break
            warnings.append(f'{code}：{error}')
            if not rows and getattr(error, 'status', '') == 'blocked':
                raise FeedUnavailable(f'{code}：{error}', 'blocked', getattr(error, 'retry_after', 0)) from None
            if getattr(error, 'status', '') == 'blocked':
                retry_after = getattr(error, 'retry_after', 0)
                state['_next_category'] = source['categories'].index(code)
                break
            if not rows and 'JSON' in str(error):
                break
        if stop.wait(0.5):
            break
    if not verified and not rows and not stop.is_set():
        raise FeedUnavailable('；'.join(warnings) or '省站未返回有效公告列表', 'needs_adapter')
    retryable = bool(warnings)
    if source.get('home_only'):
        warnings.append('首页接口可用；分页及正文接口出现验证页，当前仅采集各栏目最新 20 条，请在原站补查')
    if not deferred and not retry_after and '_next_category' in state:
        state['_next_category'] = 0
    pending = sum(not p.get('done') for k, p in state.items() if not k.startswith('_'))
    return dict(rows=rows, warnings=warnings, truncated=incomplete, empty_ok=verified > 0,
                checkpoint=state, retry_after=retry_after, retryable=retryable, coverage='backfill' if pending or deferred else 'limited' if source.get('home_only') or latest_limited else 'window',
                message=f'省站直采 {len(rows)} 条；已读取 {verified}/{len(source["categories"])} 个栏目；'
                        + ('首页窗口，分页受限' if source.get('home_only') else f'最新每栏目最多 {pages} 页；{pending} 个栏目待续采；首次补近 7 天，后续保留 2 天重叠窗口')
                        + ('；已达请求预算，下轮轮转至未完成栏目' if deferred else ''))


def static_rows(html, base, source):
    notice_pattern, _ = STATIC[source['route_key']]
    soup = BeautifulSoup(html, 'lxml')
    if source['route_key'] in ('trade-31', 'trade-54'):
        for node in soup.select('[onclick]'):
            match = re.fullmatch(r"\s*window\.open\(['\"]([^'\"]+)['\"]\);?\s*", node['onclick'])
            if match:
                node['href'] = match[1]
                node['data-notice-link'] = '1'
    for a in soup.select('a[href], [data-notice-link]'):
        link = urldefrag(urljoin(base, a['href'].strip()))[0]
        u = urlsplit(link)
        if u.hostname != urlsplit(base).hostname or u.scheme not in ('http', 'https') or not re.search(notice_pattern, link):
            continue
        if source['route_key'] == 'trade-37':
            link = urljoin(base, u.path)+('?' + u.query if u.query else '')
        node = a.select_one('[title]')
        title = a.get('title') or (node.get('title') if node else '')
        if not title:
            clone = BeautifulSoup(str(a), 'lxml')
            for date in clone.select('.date,.time,.datetime'):
                date.decompose()
            title = clone.get_text(' ', strip=True)
        title = clean_text(re.sub(r'\s+\d{4}[/-]\d{2}[/-]\d{2}$', '', title))
        if len(title) < 6:
            continue
        parent = a if a.name == 'li' else a.find_parent(['li', 'tr']) or a.parent
        date_node = parent.select_one('.date,.time,.datetime') if parent else None
        context = date_node.get_text(' ', strip=True) if date_node else parent.get_text(' ', strip=True).replace(a.get_text(' ', strip=True), '') if parent else ''
        published = normalized_date(context)
        if source['route_key'] in ('gov-54', 'trade-31', 'trade-54', 'trade-50'):
            published = published or normalized_date(a.get('data-dd', '') or parent.get_text(' ', strip=True))
            if not published:
                continue
        if source['route_key'] == 'trade-63' and parent:
            month, day = parent.select_one('.proj-date .date'), parent.select_one('.proj-date .day')
            if month and day:
                published = normalized_date(month.get_text(strip=True)+'-'+day.get_text(strip=True))
        if not published:
            m = re.search(r'/(20\d{2})(\d{2})(\d{2})/', u.path)
            if m:
                published = '-'.join(m.groups())
            else:
                m = re.search(r'/(20\d{2})/(\d{2})/', u.path)
                day = re.search(r'(?<!\d)(\d{2})-(\d{2})(?!\d)', context)
                if m and day and m[2] == day[1]:
                    published = f'{m[1]}-{m[2]}-{day[2]}'
        kind = classify_notice(title)
        if kind == '其他' and source['kind'] == '公共资源':
            kind = '交易公告'
        yield dict(title=title[:500], url=link, source=source['name'], region=source['province'],
                   published_at=published, notice_type=kind)


def static_links(html, base, source, next_only=False):
    notice, listing = STATIC[source['route_key']]
    for a in BeautifulSoup(html, 'lxml').select('a[href]'):
        link = urldefrag(urljoin(base, a['href'].strip()))[0]
        if urlsplit(link).hostname != urlsplit(base).hostname or urlsplit(link).scheme not in ('http', 'https'):
            continue
        if next_only and a.get_text('', strip=True) not in ('下一页', '下页', '>', '下一页>'):
            continue
        if re.search(listing, link) and not re.search(notice, link):
            yield link
    if source['route_key'] == 'gov-13':
        # The official static pager emits these URLs in JavaScript, not anchors.
        pager = re.search(r'createPageHTML\(\s*(\d+),\s*(\d+),\s*["\']index["\'],\s*["\']html["\']', html)
        if pager and int(pager[2]) + 1 < int(pager[1]):
            yield urljoin(base, f'index_{int(pager[2])+1}.html')


def collect_static(source, stop, pages, html_fetch):
    from .feeds import FeedUnavailable
    html, base = html_fetch(source['url'])
    rows = {r['url']: r for r in static_rows(html, base, source)}
    state = copy.deepcopy(source.get('checkpoint') or {})
    queue, visited = state.get('queue', []), state.get('visited', [])
    if not queue:
        queue, visited = list(dict.fromkeys(static_links(html, base, source))), []
        if source['route_key'] == 'gov-11':
            queue = [urljoin(base, f'/xxgg/{area}/A00200400{n}index_1.htm') for n, area in [(1,'sjxxgg'),(2,'qjxxgg')]]
        elif source['route_key'] == 'gov-13':
            queue = [urljoin(base, '/province/cggg/zbgg/')]
    warnings, failed, retry_after = [], [], 0
    for _ in range(pages):
        if not queue or stop.wait(0.5):
            break
        link = queue.pop(0)
        # Check persisted URLs against the same strict list rules before fetching.
        if urlsplit(link).hostname != urlsplit(base).hostname or not re.search(STATIC[source['route_key']][1], link):
            continue
        try:
            text, final = html_fetch(link)
            items = list(static_rows(text, final, source))
            if not items:
                warnings.append('栏目需动态接口适配：'+urlsplit(link).path)
            rows.update({r['url']: r for r in items})
            visited.append(link)
            if source['route_key'] == 'gov-13':
                for child in static_links(text, final, source):
                    if child not in visited and child not in queue:
                        queue.append(child)
            for child in static_links(text, final, source, next_only=True):
                if child not in visited and child not in queue:
                    queue.append(child)
        except ValueError as error:
            warnings.append(str(error)); failed.append(link)
            retry_after = max(retry_after, getattr(error, 'retry_after', 0))
            if retry_after:
                break
    queue.extend(failed)
    if not rows and not stop.is_set():
        raise FeedUnavailable('省站页面未识别出公告；不能视为无公告', 'needs_adapter')
    return dict(rows=list(rows.values()), warnings=warnings, retry_after=retry_after, truncated=True, empty_ok=False,
                checkpoint={'queue': queue[:2000], 'visited': visited[-4000:]}, coverage='limited',
                message=f'省站直采 {len(rows)} 条；另有 {len(queue)} 个已发现列表页待轮转；仅覆盖已适配公开栏目')


def collect_province(source, stop, pages, html_fetch, json_fetch):
    from .feeds import FeedUnavailable
    original = json_fetch
    last_request = 0
    interval = 4.0 if source['id'] == 'direct-gov-45' else 3.0 if source['adapter'] == 'province_zcy' else 0.8
    def polite_json(*args, **kwargs):
        nonlocal last_request
        for attempt in range(2):
            delay = max(0, last_request + interval - time.monotonic())
            if stop.is_set() or delay and stop.wait(delay):
                raise FeedUnavailable('采集已停止', 'stopped')
            last_request = time.monotonic()
            try:
                return original(*args, **kwargs)
            except FeedUnavailable as error:
                if error.status != 'error' or error.retry_after or attempt == 1:
                    raise
                if stop.wait(3):
                    raise FeedUnavailable('采集已停止', 'stopped') from None
    json_fetch = polite_json
    if source['adapter'] == 'province_shaanxi_home':
        from .provincial_more import collect_shaanxi_home
        return collect_shaanxi_home(source, stop, json_fetch)
    if source['adapter'] == 'province_hunan_trade':
        from .provincial_more import collect_hunan_trade
        return collect_hunan_trade(source, stop, pages, json_fetch)
    if source['adapter'] == 'province_fujian_trade':
        from .provincial_more import collect_fujian_trade
        return collect_fujian_trade(source, stop, pages, json_fetch)
    if source['adapter'] in ('province_hubei_trade', 'province_yunnan_trade'):
        from .provincial_more import collect_hubei_trade, collect_yunnan_trade
        return (collect_hubei_trade if source['adapter'] == 'province_hubei_trade' else collect_yunnan_trade)(source, stop, pages, json_fetch)
    if source['adapter'] in ('province_chongqing', 'province_neimenggu_trade'):
        from .provincial_more import collect_chongqing, collect_neimenggu_trade
        return (collect_chongqing if source['adapter'] == 'province_chongqing' else collect_neimenggu_trade)(source, stop, pages, json_fetch)
    if source['adapter'] == 'province_anhui_trade':
        from .provincial_more import collect_anhui_trade
        return collect_anhui_trade(source, stop, json_fetch)
    if source['adapter'] in ('province_liaoning', 'province_yunnan'):
        from .provincial_more import collect_liaoning, collect_yunnan
        return collect_liaoning(source, stop, json_fetch) if source['adapter'] == 'province_liaoning' else collect_yunnan(source, stop, json_fetch, html_fetch)
    if source['adapter'] == 'province_gpcms_home':
        from .provincial_more import collect_gpcms_home
        return collect_gpcms_home(source, stop, json_fetch)
    if source['adapter'] == 'province_xizang':
        from .provincial_more import collect_xizang
        return collect_xizang(source, stop, pages, json_fetch)
    if source['adapter'] == 'province_tianjin':
        from .provincial_more import collect_tianjin
        return collect_tianjin(source, stop, pages, html_fetch)
    if source['adapter'] == 'province_home':
        return collect_home(source, html_fetch)
    if source['adapter'] == 'province_guizhou':
        return collect_guizhou(source, stop, pages, json_fetch)
    if source['adapter'] == 'province_public_search':
        return collect_public_search(source, stop, pages, html_fetch, json_fetch)
    if source['adapter'] == 'province_hlj':
        from .feeds import FeedUnavailable
        result = json_fetch(urljoin(source['url'], '/gateway/gpcms/rest/web/v2/index/getSelectVerifyCodeEnable'))
        if str(result.get('code')) == '200' and str(result.get('data')).lower() == 'true':
            raise FeedUnavailable('黑龙江省采购网已启用查询验证码；尚未接通自动查询，请在原站人工查询。全国汇聚为空不代表省站无公告', 'blocked')
        raise FeedUnavailable('黑龙江省采购网查询配置变化，需重新验证适配', 'needs_adapter')
    if source['adapter'] == 'province_nx':
        return collect_ningxia(source, stop, json_fetch)
    if source['adapter'] == 'province_zcy':
        return collect_zcy(source, stop, pages, html_fetch, json_fetch)
    if source['adapter'] == 'province_epoint':
        return collect_epoint(source, stop, pages, json_fetch)
    return collect_static(source, stop, pages, html_fetch)


def collect_home(source, html_fetch):
    """Only public home columns; do not submit protected deep-search forms."""
    from .feeds import FeedUnavailable
    from ..storage.workbench import is_notice
    html, base = html_fetch(source['url'])
    rows = {}
    soup = BeautifulSoup(html, 'lxml')
    labelled = []
    if source['route_key'] == 'gov-41':
        allowed = {'采购意向', '采购公告', '变更公告', '结果公告', '废标公告', '合同公告', '验收结果公告', '单一来源公示', '非政府采购', '其他'}
        for panel in soup.select('#TabbedPanels3, #TabbedPanels4'):
            tabs = panel.select(':scope > .TabbedPanelsTabGroup > li')
            contents = panel.select(':scope > .TabbedPanelsContentGroup > .TabbedPanelsContent')
            for tab, content in zip(tabs, contents):
                label = tab.get_text('', strip=True)
                if label in allowed:
                    labelled.extend((a, label) for a in content.select('li a[href]'))
    else:
        labelled = [(a, '') for a in soup.select('li a[href]')]
    for a, label in labelled:
        link = urljoin(base, a['href'])
        if urlsplit(link).hostname != urlsplit(base).hostname:
            continue
        if source['route_key'] == 'gov-12':
            valid = re.search(r'/viewer\.do\?id=\d+&ver=2$', link)
        else:
            valid = re.search(r'/henan/content\?infoId=\d+&channelCode=', link)
        title = clean_text(a.get('title') or a.get_text(' ', strip=True))
        if label == '其他' and (not is_notice(title) or administrative_notice(title)):
            continue
        parent = a.find_parent('li')
        # Procurement rows on Henan have an explicit purchasing-unit cell;
        # exclude news, regulations, complaints and expert recruitment columns.
        unit = parent.select_one('.danwei')
        if not valid or len(title) < 6 or source['route_key'] == 'gov-41' and unit is None:
            continue
        if source['route_key'] == 'gov-12':
            box = a.find_parent(class_='boxIndex')
            heading = box.select_one('.title') if box else None
            if not heading or not re.search('采购意向|采购信息|单一来源', heading.get_text()) or not is_notice(title):
                continue
        text = parent.get_text(' ', strip=True).replace(a.get_text(' ', strip=True), '')
        published = normalized_date(text)
        if not published:
            english = re.search(r'\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) (\w{3}) (\d{1,2}) \d{2}:\d{2}:\d{2} CST (20\d{2})', text)
            if english:
                month = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split().index(english[1])+1
                published = datetime(int(english[3]), month, int(english[2])).date().isoformat()
        if not published:
            continue
        purchaser = clean_text(unit.get('title') or unit.get_text()) if unit else ''
        if re.search(r'\.{2,}|…|项目|工程$', purchaser):
            purchaser = ''
        kind = classify_notice(title)
        rows[link] = dict(title=title[:500], url=link, source=source['name'], region=source['province'],
                          published_at=published, purchaser=purchaser,
                          notice_type=classify_notice(label) if kind == '其他' and label else kind)
    if not rows:
        raise FeedUnavailable('省站首页未识别到有效公告，需核查页面或访问限制', 'needs_adapter')
    return dict(rows=list(rows.values()), warnings=['仅覆盖公开首页采购栏目；深层检索受原站验证或限流限制'],
                retryable=False, empty_ok=False, truncated=True, coverage='limited',
                message=f'省站公开首页直采 {len(rows)} 条；每轮刷新省、市县栏目，非历史全量')


def administrative_notice(title):
    return bool(re.search(r'行政处罚|监督检查|融资金融机构|预留项目执|征集.*(?:妨碍|问题线索)', title))


def collect_public_search(source, stop, pages, html_fetch, json_fetch):
    """Use the same public search pages as the provincial site, with overlap.

    Qinghai's UI requires verification beyond page 49; never request that range.
    These are rolling index pages, not a claim of complete historical coverage.
    """
    from .feeds import FeedUnavailable
    state = copy.deepcopy(source.get('checkpoint') or {})
    progress = state.setdefault('public_search', {'page': 1})
    qh = source['route_key'] == 'trade-63'
    base = source['url']
    rows, warnings = {}, []
    retry_after, total, checked = 0, 0, 0
    def read(number):
        if qh:
            params = dict(token='', pn=(number-1)*10, rn=10, sdt='', edt='', wd='', inc_wd='', exc_wd='',
                          fields='title', cnum='001;002;003;004;005;006;007;008;009;010',
                          sort='{"showdate":"0"}', ssort='title', cl=200, terminal='',
                          condition=[dict(fieldName='categorynum', isLike=True, likeType=2, equal='001')],
                          time=None, highlights='title', statistics=None, unionCondition=None,
                          accuracy='100', noParticiple='0', searchRange=None, isBusiness=1)
            data = json_fetch(urljoin(base, '/inteligentsearch/rest/inteligentSearch/getFullTextData'), data=json.dumps(params)).get('result', {})
            records, count = data.get('records'), data.get('totalcount')
        else:
            params = dict(code='190dd7b7c91', tableName='t_187973f42ee',
                          searchFields=[dict(fieldName='f_2023419644732', searchWord='', withHighLight=True)],
                          sorts=[dict(sortField='save_time', sortOrder='DESC')], trackTotalHits=True,
                          granularity='ALL', pageNo=number, pageSize=10,
                          customFilter=dict(operator='and', properties=[], filters=[dict(operator='or', properties=[])]))
            response = json_fetch(urljoin(base, '/irs/front/list'), json_data=params)
            if response.get('success') is not True:
                raise FeedUnavailable('广西公开检索接口返回异常', 'needs_adapter')
            data = response.get('data', {})
            records, count = data.get('list'), data.get('pager', {}).get('total')
        if not isinstance(records, list) or count is None:
            raise FeedUnavailable('省站公开检索结构变化', 'needs_adapter')
        parsed = []
        for record in records:
            if qh:
                identity = str(record.get('id') or '').split('_')[0]
                category = str(record.get('categorynum') or '')
                path = record.get('linkurl') or ''
                lifecycle = {'001001001','001001002','001001003','001001005','001001006','001001007','001001010',
                             '001002001','001002002','001002004','001002005','001002006','001002007',
                             '001004001','001004003','001004004','001005001','001005003','001005005',
                             '001006001001','001006001002','001006001003','001006001004','001006001005',
                             '001006002001','001006002002','001006002003','001006002004',
                             '001006003001','001006003002','001006003003','001006003004'}
                if category in lifecycle and re.fullmatch(r'[a-fA-F0-9-]{8,80}', identity):
                    path = '/ggzy/projectDetail.html?'+urlencode(dict(infoid=identity, categorynum=category))
                link = urljoin(base, path)
                allowed = re.search(r'/ggzy/projectDetail\.html\?infoid=[a-fA-F0-9-]+&categorynum=\d+$|/[a-z]+/jyxx/(?:\d+/)+\d{8}/[a-zA-Z0-9_-]+\.html$', link)
                title, date = clean_text(record.get('title')), normalized_date(record.get('showdate') or '')
            else:
                link = urljoin(base, record.get('doc_pub_url') or '')
                allowed = re.search(STATIC['trade-45'][0], link)
                title = clean_text(record.get('f_2023419644732_ext') or record.get('f_2023419644732'))
                date = normalized_date(record.get('f_20234195622') or '')
            if not allowed or urlsplit(link).hostname != urlsplit(base).hostname or not title or not date:
                raise FeedUnavailable('检索页包含尚未适配的公告链接或日期，保留当前页等待修复', 'needs_adapter')
            parsed.append(dict(title=title[:500], url=link, source=source['name'], region=source['province'],
                               published_at=date, notice_type=classify_notice(title)))
        return parsed, int(count)
    try:
        previous = None
        for number in range(1, pages+1):
            if stop.is_set() or qh and number > 49:
                break
            items, total = read(number)
            signature = '|'.join(r['url'] for r in items)
            if signature and signature == previous:
                raise FeedUnavailable('检索页重复返回，暂停推进进度', 'needs_adapter')
            rows.update({r['url']: r for r in items})
            previous = signature
            checked += 1
            if number*10 >= total or not items:
                break
        # Repeat the previous page at the boundary to absorb list insertions.
        cursor = max(pages+1, int(progress.get('page', 1)))
        for number in range(max(pages+1, cursor-1), cursor+pages):
            if stop.is_set():
                break
            if qh and number > 49:
                progress['page'] = pages+1
                break
            items, total = read(number)
            signature = '|'.join(r['url'] for r in items)
            if signature and signature == previous:
                raise FeedUnavailable('检索页重复返回，暂停推进进度', 'needs_adapter')
            rows.update({r['url']: r for r in items})
            previous = signature
            progress['page'] = number+1
            checked += 1
            if number*10 >= total or not items:
                progress['page'] = pages+1
                break
    except ValueError as error:
        warnings.append(str(error))
        retry_after = getattr(error, 'retry_after', 0)
    # Retain the homepage's broader column mix alongside the dynamic index.
    if not retry_after and not stop.is_set():
        try:
            html, final = html_fetch(base)
            rows.update({r['url']: r for r in static_rows(html, final, source)})
        except ValueError as error:
            warnings.append('首页补充失败：'+str(error))
    if not rows and not stop.is_set():
        raise FeedUnavailable('；'.join(warnings) or '检索未取得有效公告', 'blocked' if retry_after else 'needs_adapter', retry_after)
    return dict(rows=list(rows.values()), warnings=warnings, checkpoint=state, retry_after=retry_after,
                truncated=True, empty_ok=False, coverage='limited',
                message=f'省站动态检索读取 {checked} 页，合并首页共 {len(rows)} 条；下轮续读第 {progress["page"]} 页并重叠一页；'
                        + ('公开检索最多前 490 条，更深分页需原站验证' if qh else '索引滚动分页，尚非历史全量'))


def collect_ningxia(source, stop, json_fetch):
    from .feeds import FeedUnavailable
    base = 'https://www.ccgp-ningxia.gov.cn/NXGPPSP_CMS/'
    def query(method, params, content_type='application/json'):
        encoded = base64.b64encode(json.dumps(params).encode()).decode()
        data = json_fetch(base+'nxgpp/'+method+'.do', data=encoded, content_type=content_type)
        if data.get('result') != '1':
            raise FeedUnavailable('宁夏官网公开栏目接口返回异常', 'needs_adapter')
        return data
    config = query('NewsQuery_findModelConfig', {'siteCode': 'NXGPP_MAIN'}, 'text/plain')
    tabs = config.get('data', {}).get('noticeTwoLevelColumn')
    if not isinstance(tabs, list) or not tabs:
        raise FeedUnavailable('宁夏采购栏目配置变化', 'needs_adapter')
    rows, warnings = {}, []
    retry_after = 0
    kinds = {'CGXQ':'cgxq', 'ZBGG':'zbgg', 'ZHBGG':'ZB', 'SBGG':'fbgg', 'GZGG':'gzgg',
             'DYLY':'zbgg', 'HTGG':'htgg', 'LYYSGG':'lyysgg'}
    for area in ('QBJ', 'SX'):
        for tab in tabs:
            if stop.is_set() or retry_after:
                break
            code = tab.get('code')
            if code not in kinds and code not in ('CGYXGK', 'JJGG', 'KJXYGG'):
                warnings.append('未适配栏目：'+str(code)); continue
            try:
                data = query('NewsQuery_findNoticeWithCount', dict(columnId=tab['id'], count=tab.get('displayRow') or '10',
                                                                  columnCode=code, parentColumnCode=area))
                records = data.get('dataList')
                if not isinstance(records, list):
                    raise FeedUnavailable('宁夏公告列表结构变化', 'needs_adapter')
                for r in records:
                    key, title = str(r.get('ID') or ''), clean_text(r.get('CAPTION'))
                    if not key or not re.fullmatch(r'[A-Za-z0-9_-]+', key) or not title:
                        continue
                    if code in ('CGYXGK','KJXYGG'):
                        column = 'CGYXGK' if code == 'CGYXGK' else r.get('COLUMN_CODE') or ''
                        if not re.fullmatch(r'[A-Za-z0-9_-]+', column):
                            continue
                        link = urljoin(source['url'], f'contents/CGGG/{column}/content.jsp')+'?'+urlencode(dict(id=key, cid=tab.get('columnId') if code == 'CGYXGK' else r.get('COLUMN_ID'), sid=tab.get('siteId')))
                    else:
                        kind = kinds.get(code) if code != 'JJGG' else {'01':'biz','03':'bizwin'}.get(r.get('NOTICE_TYPE'),'bizfail')
                        params = dict(noticeType=kind, noticeId=key)
                        if code not in ('DYLY','HTGG','LYYSGG'):
                            params['tab'] = area
                        if code in ('ZHBGG','SBGG','GZGG'):
                            params['type'] = {'ZHBGG':'108','SBGG':'113','GZGG':'110'}[code]
                        if code == 'HTGG' and r.get('IS_OLD_AGRE') is not None:
                            params['isOldAgre'] = r['IS_OLD_AGRE']
                        link = base+'nxgpp/NoticeFullProcess.do?'+urlencode(params)
                    rows[link] = dict(title=title[:500], url=link, source=source['name'], region=source['province'],
                                      published_at=normalized_date(r.get('PUBLISH_TIME') or ''), notice_type=classify_notice(title))
            except ValueError as error:
                warnings.append(str(error))
                retry_after = getattr(error, 'retry_after', 0)
                if getattr(error, 'status', '') == 'blocked':
                    if not rows:
                        raise
                    break
            if stop.wait(0.5):
                break
    if not rows and not stop.is_set():
        raise FeedUnavailable('宁夏公开首页未取得有效公告：'+'；'.join(warnings), 'needs_adapter')
    retryable = bool(warnings)
    warnings.append('高级检索和分页需要原站验证码，当前仅覆盖自治区及市县首页各栏目最新公告')
    return dict(rows=list(rows.values()), warnings=warnings, retry_after=retry_after, retryable=retryable, truncated=True, empty_ok=False, coverage='limited',
                message=f'宁夏省站首页接口读取 {len(rows)} 条；已修复旧入口的页面跳转；深层分页仍需人工核对')


def collect_guizhou(source, stop, pages, json_fetch):
    from .feeds import FeedUnavailable
    # Channel IDs returned by the public home aggregate and used by its lists.
    categories = ('5904475', '5904543', '5904476', '5904477', '5904479')
    state = copy.deepcopy(source.get('checkpoint') or {})
    local = datetime.now(timezone(timedelta(hours=8))).date()
    yesterday = (local-timedelta(days=1)).isoformat()
    rows, warnings, retry_after, total_calls = {}, [], 0, 0
    rotation = int(state.get('_next_category', 0)) % len(categories)
    ordered = categories[rotation:] + categories[:rotation]
    deferred = False
    def read(category, number, bounds=None):
        nonlocal total_calls
        if total_calls >= 40:
            raise FeedUnavailable('本轮请求预算已用完，下轮继续', 'deferred')
        if number > 500:
            raise FeedUnavailable('原站公开列表最多 500 页，当前日期窗口需进一步拆分', 'needs_adapter')
        total_calls += 1
        params = dict(channelId=category, pageNum=number, pageSize=20)
        if bounds:
            params.update(startTime=bounds['start']+' 00:00:00', endTime=bounds['end']+' 23:59:59')
        response = json_fetch(urljoin(source['url'], '/tradeInfo/es/list'), json_data=params)
        records, total = response.get('list'), response.get('total')
        if not isinstance(records, list) or not isinstance(total, int) or total < 0:
            raise FeedUnavailable('贵州公开列表结构变化，保留分页进度', 'needs_adapter')
        valid = []
        for record in records:
            link, title = record.get('apiUrl', ''), clean_text(record.get('docTitle'))
            published = timestamp(record.get('docRelTime'))
            if (urlsplit(link).hostname != 'ggzy.guizhou.gov.cn' or urlsplit(link).scheme not in ('http', 'https')
                    or not re.fullmatch(r'/tradeInfo/detailHtml\?metaId=\d+', urlsplit(link).path+'?'+urlsplit(link).query)
                    or str(record.get('channelId')) != category or not title or not published):
                raise FeedUnavailable('贵州公告链接或必要字段无法识别，保留分页进度', 'needs_adapter')
            if bounds and not bounds['start'] <= published[:10] <= bounds['end']:
                raise FeedUnavailable('贵州未按日期筛选，保留补采进度', 'needs_adapter')
            kind = classify_notice(title)
            if kind == '其他':
                kind = classify_notice(record.get('announcement') or '')
            valid.append(dict(title=title[:500], url=link, source=source['name'], region=source['province'],
                              published_at=published, project_no=record.get('tenderProjectCode') or '',
                              notice_type=kind if kind != '其他' else '交易公告'))
        if not records and total > (number-1)*20:
            raise FeedUnavailable('贵州列表总数非零但当前页为空，保留进度', 'needs_adapter')
        signature = '|'.join(r['url'] for r in valid)
        if bounds and number > 1 and signature and signature == bounds.get('signature'):
            raise FeedUnavailable('贵州重复返回同一补采页，保留进度', 'needs_adapter')
        rows.update({r['url']: r for r in valid})
        return total, len(records), signature
    for category in ordered:
        if stop.is_set():
            break
        progress = state.setdefault(category, {})
        if not progress.get('end') or progress.get('done') and progress['end'] < yesterday:
            start = (datetime.fromisoformat(progress['end']).date()-timedelta(days=2)).isoformat() if progress.get('end') else (local-timedelta(days=7)).isoformat()
            progress = dict(start=start, end=yesterday, page=1, done=False)
            state[category] = progress
        try:
            previous = None
            for number in range(1, pages+1):
                if stop.is_set():
                    break
                total, size, signature = read(category, number)
                if signature and signature == previous:
                    raise FeedUnavailable('贵州最新列表重复返回同一页', 'needs_adapter')
                previous = signature
                if number*20 >= total or not size:
                    break
            for _ in range(pages):
                if stop.is_set() or progress.get('done'):
                    break
                number = progress['page']
                total, size, signature = read(category, number, progress)
                progress.update(page=number+1, done=number*20 >= total, signature=signature)
        except ValueError as error:
            if getattr(error, 'status', '') == 'deferred':
                deferred = True
                state['_next_category'] = categories.index(category)
                break
            warnings.append(str(error))
            retry_after = getattr(error, 'retry_after', 0)
            if retry_after or getattr(error, 'status', '') == 'blocked':
                break
        state['_next_category'] = (categories.index(category)+1) % len(categories)
    if not rows and not stop.is_set():
        raise FeedUnavailable('贵州省站未取得有效公告：'+'；'.join(warnings), 'blocked' if retry_after else 'needs_adapter', retry_after)
    return dict(rows=list(rows.values()), warnings=warnings, retry_after=retry_after, empty_ok=False,
                truncated=True, coverage='backfill', checkpoint=state,
                message=f'贵州省站 5 类公开交易直采 {len(rows)} 条；最新列表＋固定日期窗口续采；'
                        +('本轮预算已用完，下轮继续' if deferred else '尚未覆盖全部历史'))


def collect_epoint(source, stop, pages, json_fetch):
    from .feeds import FeedUnavailable
    endpoint, cnum, category, fields, prefix = EPOINT[source['route_key']]
    base = source['url']
    local = datetime.now(timezone(timedelta(hours=8)))
    yesterday = (local.date()-timedelta(days=1)).isoformat()
    progress = copy.deepcopy(source.get('checkpoint') or {}).get('window', {})
    if not progress.get('end') or progress.get('done') and progress['end'] < yesterday:
        start = (datetime.fromisoformat(progress['end']).date()-timedelta(days=2)).isoformat() if progress.get('end') else (local.date()-timedelta(days=7)).isoformat()
        progress = dict(start=start, end=yesterday, page=1, done=False)
    rows, warnings = {}, []
    latest_total, retry_after = 0, 0
    def read(number, bounds=None):
        params = dict(token='', pn=(number-1)*20, rn=20, sdt='', edt='', wd='', inc_wd='', exc_wd='',
                      fields=fields, cnum=cnum, sort='{"webdate":"0","id":"0"}', ssort='', cl=200,
                      terminal='', condition=[dict(fieldName='categorynum', equal=category, isLike=True, likeType=2)],
                      time=[], highlights='', statistics=None, unionCondition=None, accuracy='', noParticiple='1',
                      searchRange=None, noWd=True)
        if source['route_key'] not in ('trade-23', 'trade-51'):
            params['isBusiness'] = '1'
        if bounds:
            params['time'] = [dict(fieldName='webdate', startTime=bounds['start']+' 00:00:00', endTime=bounds['end']+' 23:59:59')]
        response = json_fetch(urljoin(base, endpoint), data=json.dumps(params))
        data = response.get('result', {})
        records = data.get('records')
        if not isinstance(records, list) or 'totalcount' not in data:
            raise FeedUnavailable('省交易平台接口结构变化', 'needs_adapter')
        if not records and int(data['totalcount']) > (number-1)*20:
            raise FeedUnavailable('省站总数非零但当前页为空，保留分页进度', 'needs_adapter')
        valid = []
        for record in records:
            path = record.get('linkurl') or ''
            if prefix and path.startswith(('/jyxx/', '/jydt/')):
                path = prefix+path
            link = urljoin(base, path)
            if urlsplit(link).hostname != urlsplit(base).hostname or not re.search(STATIC[source['route_key']][0], link):
                raise FeedUnavailable('省站公告链接无法识别，暂停推进分页', 'needs_adapter')
            title = clean_text(record.get('titlenew') or record.get('title'))
            published = normalized_date(record.get('webdate') or '')
            if not title or not published:
                raise FeedUnavailable('省站公告缺少标题或日期，暂停推进分页', 'needs_adapter')
            if bounds and not bounds['start'] <= published[:10] <= bounds['end']:
                raise FeedUnavailable('省站未按指定日期筛选，暂停推进补采进度', 'needs_adapter')
            kind = classify_notice(title)
            if kind == '其他':
                kind = classify_notice(record.get('categoryname') or '')
            if kind == '其他':
                kind = '交易公告'
            valid.append(dict(title=title[:500], url=link, source=source['name'], region=source['province'],
                              published_at=published, project_no=record.get('projectnum') or '', notice_type=kind))
        if records and not valid:
            raise FeedUnavailable('接口有记录但公告链接无法识别，需适配', 'needs_adapter')
        signature = '|'.join(r['url'] for r in valid)
        if bounds and number > 1 and signature and signature == bounds.get('signature'):
            raise FeedUnavailable('接口重复返回同一页，暂停推进补采进度', 'needs_adapter')
        rows.update({r['url']: r for r in valid})
        return int(data['totalcount']), len(records), signature
    try:
        previous = None
        for number in range(1, pages+1):
            if stop.is_set():
                break
            latest_total, size, signature = read(number)
            if signature and signature == previous:
                raise FeedUnavailable('最新列表重复返回同一页', 'needs_adapter')
            previous = signature
            if latest_total <= number*20 or not size or stop.wait(0.5):
                break
        for _ in range(pages):
            if progress.get('done') or stop.wait(0.5):
                break
            number = progress['page']
            total, size, signature = read(number, progress)
            progress.update(page=number+1, done=number*20 >= total or not size, signature=signature)
    except ValueError as error:
        if not rows:
            raise
        warnings.append(str(error))
        retry_after = getattr(error, 'retry_after', 0)
    if not rows and not stop.is_set():
        raise FeedUnavailable('省站全量索引返回空列表，需核查接口，不能据此判定无公告', 'needs_adapter')
    return dict(rows=list(rows.values()), warnings=warnings, retry_after=retry_after, empty_ok=False, truncated=not progress.get('done'),
                checkpoint={'window': progress}, coverage='backfill' if not progress.get('done') else 'limited',
                message=f'省站接口直采 {len(rows)} 条；最新列表共 {latest_total} 条，本次最多 {pages} 页；'
                        f'补采 {progress["start"]} 至 {progress["end"]}，'+
                        ('该窗口已读完' if progress.get('done') else f'下次从第 {progress["page"]} 页继续'))
