"""Bounded public feeds; a blank page is never reported as successful ingestion."""
import re
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit, urldefrag

import requests
from bs4 import BeautifulSoup

from .detail import fetch_page, public_url, normalized_date, MAX_BYTES
from .government import parse_announcements as parse_ccgp
from .ceec import parse_announcements as parse_ceec
from ..database.taxonomy import classify_notice
from ..database.workbench import is_notice


class FeedUnavailable(ValueError):
    def __init__(self, message, status='error', retry_after=0):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def retry_seconds(value):
    try:
        return max(0, int(value))
    except (ValueError, TypeError):
        try:
            return max(0, int((parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()))
        except (ValueError, TypeError, OverflowError):
            return 0


def public_json(url, data=None, json_data=None, content_type=None, decoder=None, headers=None):
    public_url(url)
    headers = {'User-Agent': 'Mozilla/5.0'} | (headers or {})
    if isinstance(data, str):
        headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8'
    if content_type:
        headers['Content-Type'] = content_type
    try:
        with requests.request('POST' if data is not None or json_data is not None else 'GET', url, data=data, json=json_data,
                              headers=headers, timeout=(8, 20),
                              allow_redirects=False, stream=True) as response:
            if response.status_code in (401, 403, 429):
                limited = response.status_code == 429
                raise FeedUnavailable(f'来源限制访问（HTTP {response.status_code}）'+('，暂停请求并等待冷却后续采' if limited else '，请打开原站查看'),
                                      'blocked', max(3600, retry_seconds(response.headers.get('Retry-After'))) if limited else 0)
            response.raise_for_status()
            if response.is_redirect:
                raise FeedUnavailable('接口地址已跳转，需要更新适配', 'needs_adapter')
            content = bytearray()
            for chunk in response.iter_content(65536):
                content.extend(chunk)
                if len(content) > MAX_BYTES:
                    raise FeedUnavailable('接口响应超过 5 MB')
            import json
            if b'aliyun_waf_' in content or b'captcha' in content[:1000].lower() and b'<html' in content[:1000].lower():
                raise FeedUnavailable('原站返回安全验证页，需在原站人工查看', 'blocked')
            return json.loads(decoder(bytes(content)) if decoder else content)
    except requests.RequestException as error:
        raise FeedUnavailable(f'接口访问失败：{type(error).__name__}') from None
    except (ValueError, UnicodeError) as error:
        if isinstance(error, FeedUnavailable):
            raise
        raise FeedUnavailable('接口未返回有效 JSON，可能需要验证或适配', 'needs_adapter') from None


def parse_html(html, url, source):
    soup, seen = BeautifulSoup(html, 'lxml'), set()
    routes = {
        'gov-32': r'/jiangsu/js_cggg/details\.html\?',
        'gov-42': r'/notice/\d{6}/notice_',
        'csg': r'/(zbgg|zbhxrgs|cggg|cgjggg|lxcggg|zbjggg|gngg)/\d+\.jhtml',
        'ctg': r'/cms/channel/1ywgg\w*/\d+\.htm',
    }
    allowed = routes.get(source['id'])
    if not allowed:
        return
    for a in soup.select('a[href]'):
        link = urldefrag(urljoin(url, a['href'].strip()))[0]
        parsed = urlsplit(link)
        if parsed.scheme not in ('http', 'https') or parsed.hostname != urlsplit(url).hostname:
            continue
        if not re.search(allowed, link):
            continue
        title = re.sub(r'\s+', ' ', (a.get('title') or a.get_text(' ', strip=True))).strip()
        if source['id'] == 'gov-42':
            title = re.sub(r'^\[.*?\]\s*', '', title)
        if not is_notice(title) or re.search('操作指南|政策解读|管理办法|工作通知|征集.*专家|营商环境|采购法|系统升级通知', title):
            continue
        if re.search(r'/news/|/zcfg/|/tzgg/|/help/|/login', parsed.path, re.I):
            continue
        if not re.search(r'\d{5,}|[0-9a-f]{8}-|detail|content|article|noticeId|infoid|bulletin', parsed.path+'?'+parsed.query, re.I):
            continue
        if link in seen or re.search(r'\.(pdf|docx?|xlsx?|zip)(?:$|\?)', link, re.I):
            continue
        parent = a.find_parent(['li', 'tr']) or a.parent
        text = parent.get_text(' ', strip=True) if parent else title
        # Do not mistake a year or project number inside the title for the publication date.
        published = normalized_date(text.replace(a.get_text(' ', strip=True), '')) or normalized_date(parsed.path)
        if source['id'] == 'ctg':
            published = normalized_date(' '.join(n.get_text(' ', strip=True) for n in a.select('em')))
        # Only dated rows or explicit detail routes, never section navigation.
        if not published and not re.search(r'detail|noticeId|infoid|bulletin', link, re.I):
            continue
        seen.add(link)
        notice_type = classify_notice(title)
        if source['id'] == 'csg' and '/zbhxrgs/' in link:
            notice_type = '中标结果' if '中标公告' in title else '中标候选'
        yield dict(title=title[:500], url=link, source=source['name'],
                   region='' if source['province'] == '全国' else source['province'],
                   published_at=published, notice_type=notice_type)


def list_links(html, url):
    soup = BeautifulSoup(html, 'lxml')
    seen = set()
    for a in soup.select('a[href]'):
        label = a.get_text('', strip=True)
        if label not in ('招标公告', '采购公告', '采购信息', '中标公告', '中标结果', '交易信息', '信息公告', '招标采购'):
            continue
        link = urldefrag(urljoin(url, a['href']))[0]
        if urlsplit(link).scheme in ('http', 'https') and urlsplit(link).hostname == urlsplit(url).hostname and link != url and link not in seen:
            seen.add(link)
            yield link


def national_type(row):
    title_type = classify_notice(row['title'])
    label = row.get('informationTypeText') or ''
    if '开标' in label:
        return '开标记录'
    for word, value in [('澄清', '变更公告'), ('更正', '变更公告'), ('候选', '中标候选'),
                        ('成交', '中标结果'), ('结果', '中标结果'), ('合同', '合同公告'),
                        ('终止', '废标终止'), ('采购意向', '采购意向')]:
        if word in label:
            return value
    return title_type if title_type != '其他' else ('招标公告' if '招标' in label or '采购公告' in label else '交易公告' if '交易公告' in label else '其他')


def collect_source(source, stop, pages=3, html_fetch=fetch_page, json_fetch=public_json):
    """Return rows plus a factual scope/partial-result report; no database side effects."""
    if source['adapter'].startswith('province_'):
        from .provincial import collect_province
        return collect_province(source, stop, pages, html_fetch, json_fetch)
    rows, warnings, seen = [], [], set()
    truncated = False
    def add(items):
        for item in items:
            if item['url'] not in seen:
                seen.add(item['url'])
                rows.append(item)
    if source['adapter'] in ('crcc', 'cnbm'):
        total = 0
        for page in range(1, pages+1):
            if stop.is_set() or (page > 1 and stop.wait(1)):
                break
            try:
                if source['adapter'] == 'crcc':
                    data = json_fetch('https://www.crccep.cn/crcc-purportal-manage/portal/specialtopic/findNoticesBynotices',
                                      json_data={'pageNum': page, 'pageSize': 15, 'noticeType': '1,2,3,4,5,6', 'sourcingModeID': None})
                    records = data.get('list')
                else:
                    response = json_fetch('https://c.cnbm.com.cn/portal-sso/portal/index/query',
                                          json_data={'pageNum': page, 'pageSize': 20, 'businessType': 'NOTICE',
                                                     'noticePolymerizeType': '', 'projectTypeList': [], 'keyword': ''})
                    if str(response.get('code')) != '200':
                        raise FeedUnavailable('企业公开接口限制访问或要求登录', 'blocked')
                    data = response.get('data', {})
                    records = data.get('records')
                if not isinstance(records, list) or 'total' not in data:
                    raise FeedUnavailable('企业接口结构变化，需要更新适配', 'needs_adapter')
                total = int(data['total'])
                for record in records:
                    row = enterprise_row(source, record)
                    if row:
                        add([row])
                if not records or page >= int(data.get('pages') or ((total+14)//15 if source['adapter']=='crcc' else (total+19)//20)):
                    break
            except ValueError as error:
                if not rows:
                    raise
                warnings.append(str(error))
                break
        return dict(rows=rows, warnings=warnings, truncated=total > len(rows), empty_ok=total == 0,
                    message=f'企业公开接口共 {total} 条，本次读取 {len(rows)} 条；每次最多 {pages} 页')
    if source['adapter'] == 'national':
        total = 0
        params = {'SOURCE_TYPE': source.get('source_type', '1'), 'DEAL_TIME': '02'}
        if source.get('province_code'):
            params['DEAL_PROVINCE'] = source['province_code']
        if source.get('bid_platform'):
            params['BID_PLATFORM'] = source['bid_platform']
        if source.get('deal_classify'):
            params['DEAL_CLASSIFY'] = source['deal_classify']
        for page in range(1, pages+1):
            if stop.is_set():
                break
            if page > 1 and stop.wait(1):
                break
            try:
                result = json_fetch('https://www.ggzy.gov.cn/information/pubTradingInfo/getTradList',
                                    dict(params, PAGENUMBER=page))
            except ValueError as error:
                if not rows:
                    raise
                warnings.append(str(error))
                break
            code = result.get('code')
            if code != 200:
                message = '来源要求验证码或限制访问' if code in (829, 800, 801) else '来源接口拒绝查询'
                if rows:
                    warnings.append(message)
                    break
                raise FeedUnavailable(f'{message}（{code}），请在原站查看', 'blocked')
            data = result.get('data', {})
            if not isinstance(data, dict) or not isinstance(data.get('records'), list) or 'total' not in data:
                raise FeedUnavailable('接口结构变化，不能判断为空窗口', 'needs_adapter')
            records, total = data.get('records', []), int(data.get('total', 0))
            for r in records:
                if not r.get('title') or not r.get('url'):
                    continue
                if source.get('province_code') and r.get('province') != source['province_code']:
                    continue
                link = urljoin('https://www.ggzy.gov.cn/', r['url'])
                if urlsplit(link).hostname != 'www.ggzy.gov.cn' or not urlsplit(link).path.startswith('/information/deal/html/'):
                    continue
                add([dict(title=r['title'][:500], url=link, source=source['name']+'（全国平台汇聚）',
                          region='' if source['province'] == '全国' else source['province'], published_at=r.get('publishTime') or '',
                          project_no=r.get('tenderProjectCode') or '', notice_type=national_type(r))])
            if page >= int(data.get('pages', 1)) or not records:
                break
        truncated = total > len(rows)
        return dict(rows=rows, warnings=warnings, truncated=truncated,
                    message=f'近三天接口共 {total} 条，本次读取 {len(rows)} 条；每次最多 {pages} 页', empty_ok=total == 0)
    if source['adapter'] == 'ccgp':
        for area in ('zygg', 'dfgg'):
            for page in range(pages):
                if stop.is_set():
                    break
                url = f'https://www.ccgp.gov.cn/cggg/{area}/index'+(f'_{page}' if page else '')+'.htm'
                try:
                    html, final = html_fetch(url)
                    items = list(parse_ccgp(html, final))
                    if not items:
                        raise FeedUnavailable('公告列表未识别到有效公告', 'needs_adapter')
                    add(items)
                except ValueError as error:
                    warnings.append(str(error))
                    break
                if stop.wait(0.5):
                    break
        truncated = True
    else:
        html, final = html_fetch(source.get('list_url') or source['url'])
        parser = parse_ceec if source['adapter'] == 'ceec' else lambda h,u: parse_html(h,u,source)
        add(parser(html, final))
        if source['adapter'] == 'html':
            for link in list(list_links(html, final))[:max(0,pages-1)]:
                if stop.is_set():
                    break
                try:
                    extra, target = html_fetch(link)
                    add(parser(extra, target))
                except ValueError as error:
                    warnings.append(str(error))
        truncated = True
    if not rows and not stop.is_set():
        raise FeedUnavailable('未识别到有效公告；可能为动态页面、验证页面或列表结构变化，需适配', 'needs_adapter')
    return dict(rows=rows, warnings=warnings, truncated=truncated,
                message=f'读取 {len(rows)} 条公开公告；当前列表窗口，非历史全量', empty_ok=False)


def enterprise_row(source, record):
    if source['adapter'] == 'crcc':
        key, title = str(record.get('id') or ''), record.get('noticeTitle') or ''
        if not key.isdigit() or not title:
            return None
        column = {'TPCG': 'CompetitiveNegotiation', 'XJCG': 'InquiryAnnouncement',
                  'JJCG': 'BiddingOrderAnnouncement', 'KSXJ': 'QuickInquiry'}.get(record.get('sourcingModeID'), 'BiddingAnnouncement')
        if str(record.get('noticeType')) in ('4', '6'):
            column = 'AddendumAnnouncement'
        if str(record.get('noticeType')) in ('3', '5'):
            column = 'LetterOfAcceptance'
        return dict(title=title[:500], source=source['name'],
                    url=f'https://www.crccep.cn/findNotices?columnId={column}&noticeId={key}',
                    published_at=record.get('publishTime') or '', deadline=record.get('bidEndTime') or '',
                    purchaser=record.get('orgSimpleName') or record.get('purCompanyName') or '',
                    project_no=record.get('tenderProjectCode') or '', notice_type=classify_notice(title))
    key, title = str(record.get('businessCode') or ''), record.get('businessTitle') or ''
    if not re.fullmatch(r'[A-Za-z0-9_-]+', key) or not title or record.get('businessType') != 'NOTICE':
        return None
    soup = BeautifulSoup(record.get('businessContentText') or '', 'lxml')
    for node in soup.select('script,style'):
        node.decompose()
    content = soup.get_text('\n', strip=True)
    kind = classify_notice(content[:400])
    return dict(title=title[:500], source=source['name'],
                url=f'https://c.cnbm.com.cn/cnbm-portal-view/#/procurementDetail?noticeCode={key}',
                published_at=record.get('releaseTime') or '', deadline=record.get('stopTime') or '',
                purchaser=record.get('tenderName') or '', project_no=record.get('projectCode') or '',
                notice_type=kind if kind != '其他' else classify_notice(record.get('polymerizeTypeName') or title),
                content=content[:200000] if len(content) >= 100 else '')
