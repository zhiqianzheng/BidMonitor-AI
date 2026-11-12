"""Additional official provincial lists, with bounded, resumable collection."""
import copy
import base64
import json
import hashlib
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from .detail import fetch_page, normalized_date
from .feeds import FeedUnavailable
from ..storage.taxonomy import classify_notice


def tianjin_page(html, base, source):
    soup = BeautifulSoup(html, 'lxml')
    rows = []
    for a in soup.select('#reflshPage li a[href], #pageContent li a[href], li a[href]'):
        link = urljoin(base, a['href'])
        if urlsplit(link).hostname != urlsplit(base).hostname or not re.fullmatch(r'/viewer.do\?id=\d+&ver=2', urlsplit(link).path+'?'+urlsplit(link).query):
            continue
        title = (a.get('title') or a.get_text(' ', strip=True)).strip()
        parent = a.find_parent('li')
        date = parent.select_one('.time')
        text = date.get_text(' ', strip=True) if date else parent.get_text(' ', strip=True)
        published = normalized_date(text)
        if not published:
            m = re.search(r'\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) (\w{3}) (\d{1,2}) \d{2}:\d{2}:\d{2} CST (20\d{2})', text)
            if m and m[1] in 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split():
                published = datetime(int(m[3]), 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split().index(m[1])+1, int(m[2])).date().isoformat()
        if len(title) < 6 or not published:
            raise FeedUnavailable('天津分页公告缺少标题或日期，保留当前页', 'needs_adapter')
        rows.append(dict(title=title[:500], url=link, published_at=published,
                         region=source['province'], source=source['name'], notice_type=classify_notice(title)))
    total = soup.select_one('.countPage b')
    if not rows or not total or not total.get_text(strip=True).isdigit():
        raise FeedUnavailable('天津分页未返回有效公告或页数，保留进度', 'needs_adapter')
    return list({r['url']: r for r in rows}.values()), int(total.get_text(strip=True)), soup


def collect_tianjin(source, stop, pages, html_fetch, page_fetch=fetch_page):
    from .provincial import collect_home
    result = collect_home(source, html_fetch)
    rows = {r['url']: r for r in result['rows']}
    state = copy.deepcopy(source.get('checkpoint') or {})
    warnings, retry_after, checked = [], 0, 0
    last_request = time.monotonic()
    endpoint = urljoin(source['url'], '/portal/topicView.do')
    # Codes are obtained from the site's public purchase sidebar, not search forms.
    columns = ['1665', '1664', '1663', '1666', '2014', '2013', '2015', '2016', '1662', '1994', '2033', '2034']
    municipal = {'1665', '1663', '2014', '2015', '1662', '2033'}
    rotation = int(state.get('_next_category', 0)) % len(columns)
    with requests.Session() as session:
        def read(url, data=None):
            nonlocal last_request
            delay = max(0, last_request+4-time.monotonic())
            if stop.is_set() or delay and stop.wait(delay):
                raise FeedUnavailable('采集已停止', 'stopped')
            last_request = time.monotonic()
            return page_fetch(url, session=session, data=data)
        for offset in range(3):
            index = (rotation+offset) % len(columns)
            code = columns[index]
            state['_next_category'] = index
            progress = state.setdefault(code, {'page': 2})
            try:
                params = dict(method='view', view='Infor', id=code, ver=2)
                if code in municipal:
                    params['st'] = 1
                html, base = read(endpoint+'?'+urlencode(params))
                items, total, soup = tianjin_page(html, base, source)
                rows.update({r['url']: r for r in items})
                checked += 1
                previous = '|'.join(r['url'] for r in items)
                cursor = max(2, int(progress.get('page', 2)))
                # Revisit one boundary page to reduce skips caused by new insertions.
                first = max(2, cursor-1)
                for number in range(first, cursor+pages):
                    if number > total:
                        progress.update(page=2, signature='')
                        break
                    token = soup.select_one('#tokken')
                    if not token or not token.get('value'):
                        raise FeedUnavailable('天津公开分页会话失效，下轮重新获取', 'needs_adapter')
                    data = dict(method='view', tokens=token['value'], page=number, id=code, step=1,
                                view='Infor', st='1' if code in municipal else '', ldateQGE='', ldateQLE='')
                    html, base = read(endpoint, data)
                    items, total, soup = tianjin_page(html, base, source)
                    signature = '|'.join(r['url'] for r in items)
                    if signature == previous or number >= cursor and signature == progress.get('signature'):
                        raise FeedUnavailable('天津重复返回同一分页，停止推进进度', 'needs_adapter')
                    rows.update({r['url']: r for r in items})
                    checked += 1
                    previous = signature
                    if number >= cursor:
                        progress.update(page=number+1, signature=signature)
                    if number >= total:
                        progress.update(page=2, signature='')
                        break
                state['_next_category'] = (index+1) % len(columns)
            except ValueError as error:
                warnings.append(str(error))
                retry_after = getattr(error, 'retry_after', 0)
                # Keep this column queued, especially when the portal asks for cooling.
                break
    return dict(rows=list(rows.values()), warnings=warnings, retry_after=retry_after,
                checkpoint=state, empty_ok=False, truncated=True, coverage='limited',
                message=f'天津公开首页＋栏目分页直采 {len(rows)} 条；本轮读取 {checked} 个列表页；'
                        '市区 12 个栏目轮转，重叠一页续采；滚动列表尚非历史全量')


def collect_window(source, stop, pages, read, allow_empty=False):
    """Refresh latest pages and drain a closed date window without advancing failures."""
    today = datetime.now(timezone(timedelta(hours=8))).date()
    yesterday = (today-timedelta(days=1)).isoformat()
    state = copy.deepcopy(source.get('checkpoint') or {})
    window = state.get('window', {})
    if not window.get('end') or window.get('done') and window['end'] < yesterday:
        start = (datetime.fromisoformat(window['end']).date()-timedelta(days=2)).isoformat() if window.get('end') else (today-timedelta(days=7)).isoformat()
        window = dict(start=start, end=yesterday, page=1, done=False)
    state['window'] = window
    rows, warnings, retry_after, checked, blocked = {}, [], 0, 0, False
    try:
        previous = ''
        for bounds in (None, window):
            for offset in range(pages):
                if stop.is_set() or bounds and bounds.get('done'):
                    break
                number = bounds['page'] if bounds else offset+1
                items, total, page_size = read(number, bounds)
                if not isinstance(total, int) or total < 0 or not items and total > (number-1)*page_size:
                    raise FeedUnavailable('省站总数与当前页不一致，保留进度', 'needs_adapter')
                if bounds and any(not bounds['start'] <= r['published_at'][:10] <= bounds['end'] for r in items):
                    raise FeedUnavailable('省站未按日期筛选，保留补采进度', 'needs_adapter')
                signature = '|'.join(r['url'] for r in items)
                if number > 1 and signature and signature == (bounds.get('signature') if bounds else previous):
                    raise FeedUnavailable('省站重复返回同一页，保留进度', 'needs_adapter')
                rows.update({r['url']: r for r in items})
                checked += 1
                previous = signature
                done = number*page_size >= total
                if bounds:
                    bounds.update(page=number+1, done=done, signature=signature)
                if done:
                    break
    except ValueError as error:
        warnings.append(str(error))
        retry_after = getattr(error, 'retry_after', 0)
        blocked = getattr(error, 'status', '') == 'blocked'
        if not rows:
            raise
    if not rows and not stop.is_set() and not (allow_empty and checked and not warnings):
        raise FeedUnavailable('省站未取得有效公告，需核查公开接口', 'needs_adapter')
    return dict(rows=list(rows.values()), warnings=warnings, retry_after=retry_after,
                checkpoint=state, empty_ok=allow_empty and not warnings, blocked=blocked, truncated=True, coverage='backfill',
                message=f'省站公开分页直采 {len(rows)} 条，读取 {checked} 页；最新列表＋固定日期窗口续采；'
                        f'补采窗口 {window["start"]} 至 {window["end"]}，下次第 {window["page"]} 页；尚非全部历史')


def collect_xizang(source, stop, pages, json_fetch):
    from .provincial import clean_text
    def read(number, bounds):
        params = dict(siteId='18de62f0-2fb0-4187-a6c1-cd8fcbfb4585', channel='b541ffff-03ee-4160-be64-b11ccf79660d',
                      currPage=number, pageSize=100, noticeType='', cityOrArea='', noticeName='',
                      operationStartTime='', operationEndTime='', selectTimeName='noticeTime')
        if bounds:
            params.update(operationStartTime=bounds['start']+' 00:00:00', operationEndTime=bounds['end']+' 23:59:59')
        response = json_fetch(urljoin(source['url'], '/freecms/rest/v1/notice/selectInfoMoreChannel.do')+'?'+urlencode(params))
        records, total = response.get('data'), response.get('total')
        if not isinstance(records, list) or not isinstance(total, int):
            raise FeedUnavailable('西藏采购接口结构变化，保留分页进度', 'needs_adapter')
        rows = []
        for record in records:
            fields = record.get('fieldValues') or {}
            link = urljoin(source['url'], record.get('pageurl') or '')
            title = clean_text(fields.get('f_noticeName') or record.get('title'))
            published = normalized_date(fields.get('f_noticeTime') or '')
            if urlsplit(link).hostname != urlsplit(source['url']).hostname or not re.fullmatch(r'/freecms/site/xizang/(?:xzcggg|ggxx)/info/20\d{2}/[a-fA-F0-9-]+\.html', urlsplit(link).path) or not title or not published:
                raise FeedUnavailable('西藏采购公告必要字段缺失，保留当前页', 'needs_adapter')
            rows.append(dict(title=title, url=link, published_at=published, project_no=fields.get('f_openTenderCode') or '',
                             source=source['name'], region=source['province'], notice_type=classify_notice(title)))
        return rows, total, 100
    return collect_window(source, stop, pages, read)


GPCMS = {
    'gov-62': ('https://www.ccgp-gansu.gov.cn/', 'articleGs', 'xmcg-noticeType'),
    'gov-15': ('https://www.ccgp-neimenggu.gov.cn/', 'articleNm', 'msb-noticetype'),
}


def collect_gpcms_home(source, stop, json_fetch):
    """Only the anonymous homepage's tabs; protected deep search is not submitted."""
    from .provincial import clean_text
    base, route, dictionary = GPCMS[source['route_key']]
    def query(path, params):
        response = json_fetch(base+'gpcms/rest/web/v2/'+path+'?'+urlencode(params))
        if str(response.get('code')) != '200':
            raise FeedUnavailable('省采购网公开首页接口异常：'+str(response.get('msg') or ''), 'needs_adapter')
        return response.get('data')
    site = query('index/getDeploymentSiteId', dict(domain=urlsplit(base).hostname))
    if not isinstance(site, dict) or not site.get('id'):
        raise FeedUnavailable('省采购网未返回站点编号', 'needs_adapter')
    tabs = query('index/getDictInfo', dict(site=site['id'], dictType=dictionary))
    if not isinstance(tabs, list) or not tabs:
        raise FeedUnavailable('省采购网未返回公开公告栏目', 'needs_adapter')
    rows, warnings, retry_after = {}, [], 0
    gansu = source['route_key'] == 'gov-62'
    try:
        for tab in tabs:
            for region, level in ([('620001', ''), ('!620001', ''), ('!620001', '3')] if gansu else [('', '')]):
                if stop.is_set():
                    break
                channel = '58d8630f-7191-41a5-921a-db6a0b74f367' if gansu else tab.get('remark')
                if not channel or not tab.get('dictCode'):
                    raise FeedUnavailable('省采购网公告分类变化', 'needs_adapter')
                params = dict(siteId=site['id'], channel=channel, noticeType=tab['dictCode'],
                              regionCode=region, cityOrArea=level, pageSize=8 if gansu else 10)
                params['currPage' if gansu else 'currentPage'] = 1
                data = query('info/selectInfoMoreChannel', params)
                if not isinstance(data, dict) or not isinstance(data.get('rows'), list):
                    raise FeedUnavailable('省采购网首页公告结构变化', 'needs_adapter')
                if not data['rows'] and int(data.get('total') or 0):
                    raise FeedUnavailable('省采购网栏目总数非零但首页为空', 'needs_adapter')
                for record in data['rows']:
                    identity = str(record.get('id') or '')
                    title = clean_text(record.get('title'))
                    published = normalized_date(record.get('noticeTime') or '')
                    if not re.fullmatch(r'[a-fA-F0-9-]{8,80}', identity) or not title or not published:
                        raise FeedUnavailable('省采购网公告必要字段缺失', 'needs_adapter')
                    link = base+'maincms-web/'+route+'?'+urlencode(dict(type='article', id=identity))
                    budget = str(record.get('budget') or '')
                    rows[link] = dict(title=title[:500], url=link, published_at=published,
                                      source=source['name'], region=source['province'],
                                      purchaser=clean_text(record.get('purchaser')), agency=clean_text(record.get('agency')),
                                      project_no=clean_text(record.get('openTenderCode')),
                                      deadline=record.get('openTenderTime') or '',
                                      budget=budget+'元' if re.fullmatch(r'\d+(?:\.\d+)?', budget) else '',
                                      notice_type=classify_notice(title))
    except ValueError as error:
        if not rows:
            raise
        warnings.append(str(error))
        retry_after = getattr(error, 'retry_after', 0)
    if not rows and not stop.is_set():
        raise FeedUnavailable('省采购网公开栏目未取得公告，需核查', 'needs_adapter')
    return dict(rows=list(rows.values()), warnings=warnings, retry_after=retry_after,
                empty_ok=False, truncated=True, coverage='limited',
                message=f'省采购网公开首页各公告类型直采 {len(rows)} 条；每轮刷新，深层查询验证未接入，非全量')


def collect_liaoning(source, stop, json_fetch):
    from .provincial import clean_text
    response = json_fetch(urljoin(source['url'], '/gateway/complaint_core/homePage/list'))
    data = response.get('data')
    if response.get('code') != 200 or not isinstance(data, dict):
        raise FeedUnavailable('辽宁公开首页接口未返回公告', 'needs_adapter')
    rows = {}
    # Procurement-only sections; penalties, news and regulations are not leads.
    for column in ('cgggList', 'jgList', 'gzList', 'dylyList', 'zgysList', 'zzList', 'lyysggList'):
        if not isinstance(data.get(column), list):
            raise FeedUnavailable('辽宁采购栏目结构变化', 'needs_adapter')
        for record in data[column]:
            identity, title = str(record.get('id') or ''), clean_text(record.get('title'))
            published = normalized_date(record.get('releaseDate') or '')
            if not re.fullmatch(r'[a-fA-F0-9-]{8,80}', identity) or not title or not published:
                raise FeedUnavailable('辽宁采购公告必要字段缺失', 'needs_adapter')
            link = urljoin(source['url'], '/portaldetail')+'?'+urlencode(dict(infoId=identity))
            rows[link] = dict(title=title, url=link, published_at=published, region=source['province'],
                              source=source['name'], notice_type=classify_notice(title))
    if not rows:
        raise FeedUnavailable('辽宁公开首页未取得采购公告，需核查', 'needs_adapter')
    return dict(rows=list(rows.values()), warnings=[], empty_ok=False, truncated=True, coverage='limited',
                message=f'辽宁公开首页 7 类采购公告直采 {len(rows)} 条；深层分页及正文授权尚未接通，非全量')


def collect_yunnan(source, stop, json_fetch, html_fetch=fetch_page):
    from .provincial import clean_text
    rows, warnings, retry_after, date_lookups = {}, [], 0, 0
    blocked = False
    for level in ('1', '2'):
        for category in ('1', '2', '3', '7', '9', '6', '5', '10'):
            if stop.is_set():
                break
            try:
                response = json_fetch(urljoin(source['url'], '/api/firstpage/firstpage.gghtlist.svc'), data=dict(LEVEL=level, TYPE=category))
                records = response.get('data')
                if str(response.get('code')) != '1' or not isinstance(records, list):
                    raise FeedUnavailable('云南公开首页栏目接口结构变化', 'needs_adapter')
                for record in records:
                    identity = str(record.get('BULLETIN_ID') or '')
                    title = clean_text(record.get('BULLETINTITLE'))
                    # This entry is a permanent navigation shortcut, not a notice.
                    if identity == 'sddfucggg':
                        continue
                    date = normalized_date(record.get('FINISHDAY') or '') or normalized_date(record.get('BEGINDAY') or '')
                    if not re.fullmatch(r'[a-zA-Z0-9.\-]{8,100}', identity) or not title:
                        warnings.append(f'云南栏目 {category} 有公告编号或标题缺失')
                        continue
                    path, parameter = '/ggmxinfo.html', 'bulletinid'
                    if category in ('5', '10'):
                        path, parameter = '/showZCYBulletinInfo.html', 'bulletin_id'
                        if category == '10' and str(record.get('BULLETINCLASS')) not in ('8039', '8043', '2005'):
                            path = '/showZCYManageBulletinInfo.html'
                    elif category == '9':
                        path, parameter = '/viewPurchaseInfo.html', 'sys_purchaseintention_id'
                    elif category == '6':
                        path, parameter = '/showBulletinInfo.html', 'bulletin_id'
                    link = urljoin(source['url'], path)+'?'+urlencode({parameter: identity})
                    if not date and date_lookups < 4:
                        date_lookups += 1
                        html, _ = html_fetch(link)
                        doc = BeautifulSoup(html, 'lxml')
                        field = doc.select_one('#finishday, #pubTime')
                        if field:
                            date = normalized_date(field.get('value') or field.get_text())
                    if not date:
                        warnings.append(f'云南公告 {identity} 原站未提供日期，本轮保留其余有效记录')
                        continue
                    rows[link] = dict(title=title, url=link, published_at=date, source=source['name'],
                                      region=source['province'], project_no=record.get('PROJECTID') or '',
                                      notice_type=classify_notice(title))
            except ValueError as error:
                warnings.append(str(error))
                retry_after = getattr(error, 'retry_after', 0)
                blocked = getattr(error, 'status', '') in ('blocked', 'stopped')
                if retry_after or blocked:
                    break
        if retry_after or blocked or stop.is_set():
            break
    if not rows and not stop.is_set():
        raise FeedUnavailable('云南公开栏目未取得有效公告：'+'；'.join(warnings), 'blocked' if retry_after else 'needs_adapter', retry_after)
    return dict(rows=list(rows.values()), warnings=warnings, retry_after=retry_after, empty_ok=False,
                truncated=True, coverage='limited', message=f'云南省级及州市公开首页 8 类公告直采 {len(rows)} 条；仅覆盖栏目近期公告，非历史全量')


def collect_anhui_trade(source, stop, json_fetch):
    from .provincial import clean_text, timestamp
    rows, warnings, retry_after = {}, [], 0
    blocked = False
    for area in ('sheng', 'shi', 'qu'):
        for category, project_type in [('1','A01'), ('1','AAA'), ('1','A07'), ('2',''), ('4',''), ('5',''), ('6','')]:
            if stop.is_set():
                break
            try:
                endpoint = urljoin(source['url'], '/loadJyXX')+'?'+urlencode(dict(area=area, jyType=category, projectType=project_type))
                data = json_fetch(endpoint, data={})
                if not isinstance(data, dict) or 'bulletinList' not in data:
                    raise FeedUnavailable('安徽交易公开栏目结构变化', 'needs_adapter')
                for field, nature in [('bulletinList','1'), ('zbhxrbulletinList','2'), ('jgbulletinList','3')]:
                    records = data.get(field) or []
                    if not isinstance(records, list):
                        raise FeedUnavailable('安徽交易公告列表格式变化', 'needs_adapter')
                    for record in records:
                        identity = str(record.get('guid') or '')
                        title, date = clean_text(record.get('title')), timestamp(record.get('modityTime'))
                        # Land notices also use Chinese announcement numbers as guid.
                        # urlencode below keeps them a single query parameter.
                        if not identity or len(identity) > 200 or any(ord(c) < 32 for c in identity) or not title or not date:
                            warnings.append(f'安徽 {area}/{category}/{project_type}/{field} 公告必要字段缺失：{identity[:80]}')
                            continue
                        query = dict(guid=identity, bulletinNature=nature)
                        if category == '1':
                            path = 'jsgc'
                            query['tenderProjectType'] = record.get('tenderProjectType') or project_type
                        elif category == '4':
                            path = {'5':'tdsyq', '3':'kyqcr'}.get(str(record.get('jiaoYiType')))
                            if not path:
                                raise FeedUnavailable('安徽土地矿权公告类型变化', 'needs_adapter')
                        else:
                            path = {'2':'zfcg', '5':'cqjy', '6':'qtjy'}[category]
                            if category == '5' and record.get('type') is not None:
                                query['type'] = record['type']
                        link = urljoin(source['url'], '/'+path+'/newDetail')+'?'+urlencode(query)
                        kind = classify_notice(title)
                        rows[link] = dict(title=title, url=link, published_at=date, source=source['name'],
                                          region=source['province'], project_no=record.get('projectCode') or '',
                                          notice_type=kind if kind != '其他' else {'1':'交易公告','2':'中标候选人公示','3':'结果公告'}[nature])
            except ValueError as error:
                warnings.append(f'安徽 {area}/{category}/{project_type}：{error}')
                retry_after = getattr(error, 'retry_after', 0)
                blocked = getattr(error, 'status', '') in ('blocked', 'stopped')
                if retry_after or blocked:
                    break
        if retry_after or blocked or stop.is_set():
            break
    if not rows and not stop.is_set():
        raise FeedUnavailable('安徽交易栏目未取得公告：'+'；'.join(warnings), 'blocked' if retry_after else 'needs_adapter', retry_after)
    return dict(rows=list(rows.values()), warnings=warnings, retry_after=retry_after, empty_ok=False,
                truncated=True, coverage='limited', message=f'安徽省市县 7 类公开交易栏目直采 {len(rows)} 条；本次仅近期栏目，历史分页尚未覆盖')


def decode_chongqing(payload):
    """Decode the anonymous portal response exactly as its public utils/crypt.es.

    These constants and the finite offset cycle are shipped to every visitor;
    this is response formatting, not a login, CAPTCHA or credential exchange.
    """
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7
    charset = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
    indices = [186,197,186,184,185,183,186,204,214,178,185,201,182,179,212,184]
    try:
        ciphertext = base64.b64decode(payload, validate=True)
    except ValueError:
        raise FeedUnavailable('重庆采购网公开响应格式变化', 'needs_adapter') from None
    for offset in range(62):
        try:
            key = ''.join(charset[(i-offset) % 62] for i in indices).encode()
            decryptor = Cipher(algorithms.AES(key), modes.CBC(b'trtOl84T16yLut85')).decryptor()
            unpadder = PKCS7(128).unpadder()
            padded = decryptor.update(ciphertext)+decryptor.finalize()
            plain = unpadder.update(padded)+unpadder.finalize()
            if isinstance(json.loads(plain), dict):
                return plain
        except (ValueError, UnicodeError):
            continue
    raise FeedUnavailable('重庆采购网公开响应解码失败，需要核查官方客户端格式', 'needs_adapter')


def collect_chongqing(source, stop, pages, json_fetch):
    from .provincial import clean_text
    def read(number, bounds):
        params = dict(pi=number, ps=20)
        if bounds:
            params.update(startDate=bounds['start'], endDate=bounds['end'])
        response = json_fetch(urljoin(source['url'], '/gwebsite/api/v1/notices/stable/new')+'?'+urlencode(params), decoder=decode_chongqing)
        records, total = response.get('notices'), response.get('total')
        if response.get('res') != 0 or not isinstance(records, list) or not isinstance(total, int):
            raise FeedUnavailable('重庆采购公开列表结构变化', 'needs_adapter')
        rows = []
        for record in records:
            identity, title = str(record.get('id') or ''), clean_text(record.get('title'))
            date = normalized_date(record.get('issueTime') or '')
            if not identity.isdigit() or not title or not date:
                raise FeedUnavailable('重庆采购公告必要字段缺失，保留当前页', 'needs_adapter')
            budget = str(record.get('projectBudget') or '')
            rows.append(dict(title=title, url=urljoin(source['url'], '/info-notice/procument-notice-detail/'+identity),
                             published_at=date, source=source['name'], region=source['province'],
                             purchaser=record.get('buyerName') or '', agency=record.get('agentName') or '',
                             project_no=record.get('projectCode') or '', deadline=record.get('bidEndTime') or '',
                             budget=budget+'元' if budget else '', notice_type=classify_notice(title)))
        return rows, total, 20
    return collect_window(source, stop, pages, read)


def collect_neimenggu_trade(source, stop, pages, json_fetch):
    from .provincial import clean_text
    def read(number, bounds):
        params = dict(noticeName='', projectCode='', bidSectionCodes='', pageSize=10, pageNum=number,
                      noticeTypeName='', platformCode='', regionCode='', startTime='', endTime='',
                      transactionTypeName='', industriesTypeName='')
        if bounds:
            params.update(startTime=bounds['start']+' 00:00:00', endTime=bounds['end']+' 23:59:59')
        response = json_fetch(urljoin(source['url'], '/trssearch/openSearch/searchPublishResource')+'?'+urlencode(params))
        data = response.get('data') or {}
        records, total = data.get('data'), data.get('total')
        if str(response.get('state')) != '200' or not isinstance(records, list) or not isinstance(total, int):
            raise FeedUnavailable('内蒙古交易公开检索结构变化', 'needs_adapter')
        rows = []
        for record in records:
            identity = str(record.get('sourceDataKey') or '')
            title, date = clean_text(record.get('noticeName')), normalized_date(record.get('noticeSendTime') or '')
            if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,200}', identity) or not title or not date:
                raise FeedUnavailable('内蒙古交易公告必要字段缺失，保留当前页', 'needs_adapter')
            page = '24' if record.get('transactionTypeName') == '工程建设' else '39'
            link = urljoin(source['url'], '/jyxx/index_'+page+'.html')+'?'+urlencode(dict(id=identity))
            kind = classify_notice(title)
            rows.append(dict(title=title, url=link, published_at=date, source=source['name'], region=source['province'],
                             project_no=record.get('projectCode') or '', deadline=record.get('bidFinishTime') or '',
                             notice_type=kind if kind != '其他' else '交易公告'))
        return rows, total, 10
    return collect_window(source, stop, pages, read)


def collect_columns(source, stop, pages, columns, reader):
    """Keep an independent closed-window cursor for each public category."""
    state = copy.deepcopy(source.get('checkpoint') or {})
    rows, warnings, messages, retry_after = {}, [], [], 0
    for code, config in columns.items():
        if stop.is_set():
            break
        child = dict(source, checkpoint=state.get(code, {}))
        try:
            result = collect_window(child, stop, pages, lambda number, bounds: reader(config, number, bounds), allow_empty=True)
        except ValueError as error:
            warnings.append(f'{code}：{error}')
            retry_after = getattr(error, 'retry_after', 0)
            if retry_after or getattr(error, 'status', '') in ('blocked', 'stopped'):
                break
            continue
        rows.update({r['url']: r for r in result['rows']})
        state[code] = result['checkpoint']
        warnings.extend(f'{code}：{w}' for w in result['warnings'])
        messages.append(f"{code} {len(result['rows'])} 条")
        retry_after = max(retry_after, result.get('retry_after', 0))
        if retry_after or result.get('blocked'):
            break
    return dict(rows=list(rows.values()), warnings=warnings, checkpoint=state, retry_after=retry_after,
                empty_ok=not warnings, truncated=True, coverage='backfill',
                message='；'.join(messages)+'；已接栏目按固定日期窗口续采，其他栏目和早期历史尚未覆盖')


HUBEI_COLUMNS = {
    '工程招标': ('/jyxxAjax/jsgcZbggNew', '/jyxx/jsgcZbggDetail', 'tenderBulletinGuid', 'bulletinName', 'bulletinIssueTime'),
    '工程候选': ('/jyxxAjax/jsgcpbjggsNew', '/jyxx/jsgcpbjggsDetail', 'guid', 'publiCityName', 'publiCityReferTime'),
    '工程结果': ('/jyxxAjax/jsgcZbjggsNew', '/jyxx/jsgcZbjggsDetail', 'winBidBulletinGuid', 'bulletinName', 'bulletinIssueTime'),
    '采购公告': ('/jyxx/zfcg/cgggNew', '/jyxx/zfcg/cgggDetail', 'guid', 'bulletinTitle', 'bulletinStartTime'),
    '采购更正': ('/jyxx/zfcg/gzsxsNew', '/jyxx/zfcg/gzsxDetail', 'guid', 'terminationBulletinTitle', 'modificationStartTime'),
    '采购结果': ('/jyxx/zfcg/zbjggsNew', '/jyxx/zfcg/zbjggsDetail', 'guid', 'winBidBulletinTitle', 'winBidBulletinStartTime'),
}


def collect_hubei_trade(source, stop, pages, json_fetch):
    from .provincial import clean_text
    def read(config, number, bounds):
        endpoint, detail, identity_field, title_field, date_field = config
        params = dict(currentPage=number, pageSize=10, currentArea='', area='000',
                      publishTimeType='4' if bounds else '0', publishTimeStart='', publishTimeEnd='',
                      projectName='', bulletinTitle='', purchaserMode=99, purchaserModeType=0)
        if bounds:
            params.update(publishTimeStart=bounds['start'], publishTimeEnd=bounds['end'])
        response = json_fetch(urljoin(source['url'], endpoint), data=params)
        records, page_count = response.get('data'), response.get('pages')
        if not isinstance(records, list) or not isinstance(page_count, int) or page_count < 0:
            raise FeedUnavailable('湖北公开栏目分页结构变化', 'needs_adapter')
        rows = []
        for record in records:
            identity, title = str(record.get(identity_field) or ''), clean_text(record.get(title_field))
            raw_date = str(record.get(date_field) or '')
            if re.fullmatch(r'20\d{12}', raw_date):
                raw_date = raw_date[:4]+'-'+raw_date[4:6]+'-'+raw_date[6:8]
            date = normalized_date(raw_date)
            if not re.fullmatch(r'[a-zA-Z0-9_-]{8,120}', identity) or not title or not date:
                raise FeedUnavailable('湖北公告必要字段缺失，保留当前页', 'needs_adapter')
            rows.append(dict(title=title, url=urljoin(source['url'], detail)+'?'+urlencode(dict(guid=identity, isOther='false')),
                             published_at=date, source=source['name'], region=source['province'],
                             project_no=record.get('purchaseProjectCode') or record.get('tenderProjectCode') or '',
                             notice_type=classify_notice(title)))
        total = max(0, page_count-1)*10 + (len(rows) if number >= page_count else 10) if page_count else 0
        return rows, total, 10
    return collect_columns(source, stop, pages, HUBEI_COLUMNS, read)


YUNNAN_COLUMNS = {
    '工程招标': ('1', '招标公告', '/jyzyCenter/jyInfo/gcjs/getZbggList', 'bulletinname', 'bulletinissuetime', 'findZbggByGuid'),
    '工程更正': ('1', '变更通知', '/jyzyCenter/jyInfo/gcjs/getGzsxList', 'changetitle', 'fabutime', 'findGzsxByGuid'),
    '工程结果': ('1', '中标结果公示', '/jyzyCenter/jyInfo/gcjs/getZbJgGgList', 'bulletinname', 'bulletinissuetime', 'findZbJgGgByGuid'),
    '采购公告': ('2', '采购公告', '/jyInfo/zfcg/getCgggList', 'bulletintitle', 'bulletinstarttime', 'findCgggByGuid'),
    '采购更正': ('2', '变更通知', '/jyInfo/zfcg/getGzsxList', 'terminationbulletintitle', 'modificationstarttime', 'findGzsxByGuid'),
    '采购结果': ('2', '结果公示', '/jyInfo/zfcg/getZbjgList', 'winbidbulletintitle', 'winbidbulletinstarttime', 'findZbjgByGuid'),
}


def collect_yunnan_trade(source, stop, pages, json_fetch):
    from .provincial import clean_text
    state = copy.deepcopy(source.get('checkpoint') or {})
    if state.get('_date_format') != 'compact14':
        for value in state.values():
            if isinstance(value, dict) and isinstance(value.get('window'), dict):
                value['window'].update(page=1, done=False, signature='')
        state['_date_format'] = 'compact14'
    source = dict(source, checkpoint=state)
    def read(config, number, bounds):
        category, label, endpoint, title_field, date_field, _ = config
        params = dict(pageNum=number, pageSize=10, cityId='', industryCode='', childType='',
                      title='', startTime='', endTime='')
        if category == '1':
            params['tradeType'] = 'gcjs'
        if bounds:
            params.update(startTime=bounds['start'].replace('-', '')+'000000', endTime=bounds['end'].replace('-', '')+'235959')
        response = json_fetch(urljoin(source['url'], '/ynggfwpt-home-api'+endpoint), json_data=params)
        data = response.get('value') or {}
        records, total = data.get('list'), data.get('total')
        if str(response.get('code')) != '1' or not isinstance(records, list) or not isinstance(total, int):
            raise FeedUnavailable('云南交易公开分页结构变化', 'needs_adapter')
        rows = []
        for record in records:
            identity, title = str(record.get('guid') or ''), clean_text(record.get(title_field))
            date = normalized_date(str(record.get(date_field) or ''))
            if not re.fullmatch(r'[a-zA-Z0-9_-]{8,120}', identity) or not title or not date:
                raise FeedUnavailable(f'云南交易 {label} 必要字段缺失，保留当前页', 'needs_adapter')
            params = dict(guid=identity, colCode=category, rowCode=label, from_='jiaoYi')
            params['from'] = params.pop('from_')
            rows.append(dict(title=title, url=urljoin(source['url'], '/')+'#/tradeHall/tradeDetail?'+urlencode(params),
                             published_at=date, source=source['name'], region=source['province'],
                             project_no=record.get('purchaseprojectcode') or record.get('tenderprojectcode') or '',
                             deadline=record.get('biddocreferendtime') or record.get('bidclosingtime') or '',
                             notice_type=classify_notice(title)))
        return rows, total, 10
    return collect_columns(source, stop, pages, YUNNAN_COLUMNS, read)


def fujian_public(endpoint, params, json_fetch):
    """Anonymous request/response format from the official public portal client."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7
    params = dict(params, ts=int(time.time()*1000))
    signed = {k: v for k, v in params.items() if v != '' and v is not None}
    plain = 'B3978D054A72A7002063637CCDF6B2E5'+''.join(k+str(signed[k]) for k in sorted(signed, key=str.upper))
    response = json_fetch('https://ggzyfw.fj.gov.cn/FwPortalApi'+endpoint, json_data=params,
                          headers={'portal-sign': hashlib.md5(plain.encode()).hexdigest()})
    if str(response.get('State') or response.get('statusCode')) != '200':
        raise FeedUnavailable('福建公开接口未接受当前请求，请核查原站状态', 'needs_adapter')
    try:
        data = base64.b64decode(response.get('Data') or response.get('data'), validate=True)
        decoder = Cipher(algorithms.AES(b'EB444973714E4A40876CE66BE45D5930'), modes.CBC(b'B5A8904209931867')).decryptor()
        raw = decoder.update(data)+decoder.finalize()
        unpadder = PKCS7(128).unpadder()
        return json.loads(unpadder.update(raw)+unpadder.finalize())
    except (ValueError, TypeError, UnicodeError):
        raise FeedUnavailable('福建公开响应格式变化', 'needs_adapter') from None


def collect_fujian_trade(source, stop, pages, json_fetch):
    from .provincial import clean_text
    def read(category, number, bounds):
        params = dict(pageNo=number, pageSize=20, KIND=category, AREACODE='', M_PROJECT_TYPE='',
                      GGTYPE='', PROTYPE='', timeType='0')
        if bounds:
            params.update(timeType='', BeginTime=bounds['start']+' 00:00:00', EndTime=bounds['end']+' 23:59:59')
        data = fujian_public('/Trade/TradeInfo', params, json_fetch)
        records, total = data.get('Table'), data.get('Total')
        if not isinstance(records, list) or not isinstance(total, int):
            raise FeedUnavailable('福建交易公开列表结构变化', 'needs_adapter')
        rows = []
        for record in records:
            identity = str(record.get('M_ID' if category == 'GCJS' else 'PROCODE') or '')
            title, date = clean_text(record.get('NAME')), normalized_date(record.get('TM') or '')
            if not identity or len(identity) > 200 or not title or not date or record.get('KIND') != category:
                raise FeedUnavailable('福建交易必要字段缺失，保留当前页', 'needs_adapter')
            notice_id = str(record.get('M_ID') or '')
            if not notice_id.isdigit():
                raise FeedUnavailable('福建交易公告编号缺失，保留当前页', 'needs_adapter')
            # The public route groups a project's lifecycle. Preserve the actual
            # announcement identity so corrections/results cannot overwrite it.
            link = urljoin(source['url'], '/business/detail')+'?'+urlencode(dict(name=title, cid=identity, type=category,
                                                                               notice_id=notice_id, notice_type=record.get('GGTYPE') or ''))
            kind = classify_notice(title)
            if kind == '其他':
                kind = classify_notice(record.get('TITLE') or '')
            rows.append(dict(title=title, url=link, published_at=date, source=source['name'],
                             region=source['province'], notice_type=kind))
        return rows, total, 20
    return collect_columns(source, stop, pages, {'工程交易':'GCJS', '政府采购':'ZFCG', '土地使用权':'TDSYQ',
                                               '矿业权':'KYQ', '国有产权':'GYCQ', '其他交易':'QT'}, read)


def hunan_notices(section, json_fetch):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}', section):
        raise FeedUnavailable('湖南标段编号无效', 'needs_adapter')
    response = json_fetch('https://www.hnsggzy.com/tradeApi/constructionNotice/getBySectionId?'+urlencode(dict(sectionId=section)))
    records = (response.get('data') or {}).get('noticeList')
    if str(response.get('code')) != '200' or not isinstance(records, list) or not records:
        raise FeedUnavailable('湖南标段未返回关联公告，保留当前页', 'needs_adapter')
    if any(r.get('constructionSectionId') != section for r in records):
        raise FeedUnavailable('湖南关联公告与当前标段不一致', 'needs_adapter')
    return records


def collect_hunan_trade(source, stop, pages, json_fetch):
    from .provincial import clean_text
    from .detail import extract_detail
    state = copy.deepcopy(source.get('checkpoint') or {})
    cursor = max(pages+1, int(state.get('page', pages+1)))
    numbers = list(dict.fromkeys(list(range(1, pages+1))+list(range(max(pages+1, cursor-1), cursor+pages))))
    rows, cache, warnings, retry_after, checked, previous = {}, {}, [], 0, 0, ''
    try:
        for number in numbers:
            if stop.is_set():
                break
            response = json_fetch(urljoin(source['url'], '/tradeApi/constructionTender/listByFile')+'?'+urlencode(dict(current=number, size=7)))
            data = response.get('data') or {}
            records, total = data.get('records'), data.get('total')
            if str(response.get('code')) != '200' or not isinstance(records, list) or not isinstance(total, int):
                raise FeedUnavailable('湖南工程公开分页结构变化', 'needs_adapter')
            if not records and total > (number-1)*7:
                raise FeedUnavailable('湖南工程总数非零但当前页为空，保留进度', 'needs_adapter')
            signature = '|'.join(str(r.get('bidSectionId')) for r in records)
            if signature and (signature == previous or number >= cursor and signature == state.get('signature')):
                raise FeedUnavailable('湖南工程重复返回同一页，保留进度', 'needs_adapter')
            page_rows = {}
            for record in records:
                if stop.is_set():
                    raise FeedUnavailable('采集已停止', 'stopped')
                section = str(record.get('bidSectionId') or '')
                resource_type = str(record.get('tenderProjectType') or '')
                if not re.fullmatch(r'[A-Z_]+', resource_type):
                    raise FeedUnavailable('湖南工程项目类型缺失，保留当前页', 'needs_adapter')
                route = resource_type.lower().split('_')
                route = route[0]+''.join(x.capitalize() for x in route[1:])
                if section not in cache:
                    cache[section] = hunan_notices(section, json_fetch)
                for notice in cache[section]:
                    identity, title = str(notice.get('id') or ''), clean_text(notice.get('noticeName'))
                    date = normalized_date(notice.get('noticeSendTime') or '')
                    if not re.fullmatch(r'[a-zA-Z0-9_-]{8,200}', identity) or not title or not date:
                        raise FeedUnavailable('湖南工程关联公告必要字段缺失，保留当前页', 'needs_adapter')
                    query = dict(bidSectionId=section, regionCode=record.get('regionCode') or '',
                                 isPublic=record.get('isPublic') or '0', default='projectInfo', notice_id=identity)
                    link = urljoin(source['url'], '/')+'#/resources/transactionDetail/'+route+'?'+urlencode(query)
                    row = dict(title=title, url=link, published_at=date, source=source['name'], region=source['province'],
                               notice_type=classify_notice(title), deadline=notice.get('bidDocReferEndTime') or '')
                    if notice.get('noticeContent'):
                        try:
                            body = extract_detail('<article>'+notice['noticeContent']+'</article>', link)
                            row.update({k: body[k] for k in ('content','budget','purchaser','agency','project_no') if body.get(k)})
                        except ValueError:
                            warnings.append(f'湖南公告 {identity} 正文尚不可用，保留有效列表记录')
                    page_rows[link] = row
            rows.update(page_rows)
            checked += 1
            previous = signature
            if number >= cursor:
                state.update(page=number+1, signature=signature)
            if number*7 >= total:
                state.update(page=pages+1, signature='')
                break
    except ValueError as error:
        warnings.append(str(error))
        retry_after = getattr(error, 'retry_after', 0)
        if not rows and not stop.is_set():
            raise
    return dict(rows=list(rows.values()), warnings=warnings, checkpoint=state, retry_after=retry_after,
                empty_ok=False, truncated=True, coverage='limited',
                message=f'湖南工程 {checked} 个标段列表页、{len(rows)} 条关联公告；刷新最新并重叠续采，其他交易类型及全部历史尚未覆盖')


def shaanxi_home_headers():
    """Public homepage request format; deep search separately requires CAPTCHA."""
    from cryptography.hazmat.primitives.serialization import load_der_public_key
    from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
    public_key = ('MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCS2TZDs5+orLYCL5SsJ54+bPCV'
                  's1ZQQwP2RoPkFQF2jcT0HnNNT8ZoQgJTrGwNi5QNTBDoHC4oJesAVYe6DoxXS9Nl'
                  's8WbGE8ZNgOC5tVv1WVjyBw7k2x72C/qjPoyo/kO7TYl6Qnu4jqW/ImLoup/nsJp'
                  'pUznF0YgbyU/dFFNBQIDAQAB')
    endpoint = '/freecms/rest/v1/notice/selectInfoForIndex.do'
    stamp = str(int(time.time()*1000))
    digest = hashlib.sha1((stamp+'_'+endpoint+'_bosssoft_platform_095285').encode()).hexdigest()
    encoded = load_der_public_key(base64.b64decode(public_key)).encrypt((endpoint+'$$'+stamp).encode(), PKCS1v15())
    return {'nsssjss': base64.b64encode(encoded).decode(), 'time':stamp, 'url':endpoint,
            'sign':hashlib.md5(digest.encode()).hexdigest()}


def collect_shaanxi_home(source, stop, json_fetch):
    from .provincial import clean_text
    from .detail import extract_detail
    categories = ['001011,001012,001013,001014,001016,001019',
                  '001021,001022,001023,001024,001025,001026,001029,001006',
                  '001031,001032', '001004,001006', '001053,001052,00105B',
                  '001051,00105F,001059', '59,5E', '001054,00105K,001033', '00105A,001009,00100C']
    rows, warnings, retry_after = {}, [], 0
    for region, level in [('610001',''), ('!610001',''), ('!610001','3')]:
        for category in categories:
            if stop.is_set():
                break
            params = dict(siteId='a7a15d60-de5b-42f2-b35a-7e3efc34e54f', channel='1eb454a2-7ff7-4a3b-b12c-12acc2685bd1',
                          currPage=1, pageSize=11, regionCode=region, cityOrArea=level, noticeType=category, selectTimeName='noticeTime')
            try:
                headers = shaanxi_home_headers()
                response = json_fetch(urljoin(source['url'], headers['url'])+'?'+urlencode(params), headers=headers)
                records = response.get('data')
                if str(response.get('code')) != '200' or not isinstance(records, list):
                    raise FeedUnavailable('陕西公开首页接口结构变化或要求验证', 'needs_adapter')
                for record in records:
                    link = urljoin(source['url'], str(record.get('pageurl') or ''))
                    title, date = clean_text(record.get('title')), normalized_date(record.get('noticeTime') or '')
                    if urlsplit(link).hostname != urlsplit(source['url']).hostname or not re.fullmatch(r'/freecms/site/shaanxi/[a-z]+/info/20\d{2}/[a-zA-Z0-9-]+\.html', urlsplit(link).path) or not title or not date:
                        warnings.append('陕西公开首页有公告必要字段缺失，已保留其他有效记录')
                        continue
                    budget = str(record.get('budget') or '')
                    row = dict(title=title, url=link, published_at=date, source=source['name'], region=source['province'],
                               notice_type=classify_notice(title), purchaser=record.get('purchaser') or '',
                               agency=record.get('agency') or '', project_no=record.get('openTenderCode') or '',
                               budget=budget+'元' if budget else '', deadline=record.get('openTenderTime') or '')
                    if record.get('content'):
                        try:
                            body = extract_detail('<article>'+record['content']+'</article>', link)
                            row['content'] = body['content']
                        except ValueError:
                            warnings.append('陕西部分公告正文未公开，保留有效列表记录')
                    rows[link] = row
            except ValueError as error:
                warnings.append(f'陕西 {region}/{level}/{category}：{error}')
                retry_after = getattr(error, 'retry_after', 0)
                if retry_after or getattr(error, 'status', '') in ('blocked','stopped'):
                    return dict(rows=list(rows.values()), warnings=warnings, retry_after=retry_after, empty_ok=False,
                                truncated=True, coverage='limited', message='陕西公开首页部分栏目受限，保留已取得公告')
    if not rows and not stop.is_set():
        raise FeedUnavailable('陕西公开首页未取得有效公告：'+'；'.join(warnings), 'needs_adapter')
    return dict(rows=list(rows.values()), warnings=warnings, retry_after=retry_after, empty_ok=False,
                truncated=True, coverage='limited', message=f'陕西省市县公开首页 9 类公告直采 {len(rows)} 条；深层检索需验证码，未覆盖全部历史')
