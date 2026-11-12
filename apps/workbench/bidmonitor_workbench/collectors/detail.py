"""Bounded public-page retrieval and conservative announcement extraction."""
import ipaddress
import re
import socket
import threading
import time
from contextlib import nullcontext
from datetime import datetime
from urllib.parse import urljoin, urlsplit, parse_qs, urlencode

import requests
from bs4 import BeautifulSoup, NavigableString, Tag, Comment, Doctype, Declaration, ProcessingInstruction

_browser_lock = threading.Lock()
MAX_BYTES = 5 * 1024 * 1024


def public_url(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("来源链接必须是公开的 HTTP/HTTPS 网页")
    if parsed.port not in (None, 80, 443):
        raise ValueError("来源链接仅支持标准网页端口")
    for addr in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(addr[4][0]).is_global:
            raise ValueError("不能采集本机或内网地址")
    return url


def browser_page(url):
    # Only this known public source needs browser rendering. Never render arbitrary user HTML.
    if urlsplit(url).hostname != "ec.ceec.net.cn":
        raise ValueError("该来源暂不支持浏览器采集，请打开原文核对或手动补录")
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    with _browser_lock:
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1440,1000")
        driver = webdriver.Chrome(options=options)
        try:
            driver.set_page_load_timeout(25)
            driver.get(url)
            time.sleep(2)
            public_url(driver.current_url)
            return driver.page_source, driver.current_url
        finally:
            driver.quit()


def fetch_page(url, *, session=None, data=None):
    current = public_url(url)
    try:
        with (nullcontext(session) if session is not None else requests.Session()) as session:
            for _ in range(5):
                request = session.get if data is None else session.post
                options = {} if data is None else {'data': data}
                with request(current, **options, headers={"User-Agent": "Mozilla/5.0"},
                                 timeout=(8, 20), stream=True, allow_redirects=False) as response:
                    if response.is_redirect:
                        target = public_url(urljoin(current, response.headers["Location"]))
                        if data is not None and urlsplit(target).hostname != urlsplit(current).hostname:
                            raise ValueError('公开分页入口重定向到其他站点，停止提交分页参数')
                        current = target
                        continue
                    if response.status_code == 429:
                        from .feeds import FeedUnavailable, retry_seconds
                        raise FeedUnavailable('来源限制访问（HTTP 429），暂停请求并等待冷却后续采', 'blocked',
                                              max(3600, retry_seconds(response.headers.get('Retry-After'))))
                    response.raise_for_status()
                    content_type = response.headers.get("Content-Type", "text/html").lower()
                    national_html = (urlsplit(current).hostname == 'www.ggzy.gov.cn'
                                     and urlsplit(current).path.startswith('/information/deal/html/')
                                     and 'text/plain' in content_type)
                    if "html" not in content_type and not national_html:
                        raise ValueError("来源不是 HTML 网页，请直接查看原文附件")
                    chunks, size = [], 0
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise ValueError("网页超过 5 MB，请打开原文查看")
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    if national_html and not re.match(br'\s*<!doctype html|\s*<html', body[:100], re.I):
                        raise ValueError('来源未返回公告网页，请打开原文核对')
                    encoding = response.encoding
                    if not encoding or encoding.lower() == "iso-8859-1":
                        encoding = BeautifulSoup(body, "html.parser").original_encoding or "utf-8"
                    if encoding.lower().replace('-', '') in ('gb2312', 'gbk'):
                        encoding = 'gb18030'
                    html = body.decode(encoding, errors="replace")
                    check_html_limit(html)
                    return html, current
            raise ValueError("来源重定向过多")
    except requests.RequestException:
        if urlsplit(current).hostname == "ec.ceec.net.cn":
            return browser_page(current)
        raise ValueError("来源访问失败或超时，请稍后重试，也可直接打开原文") from None


def check_html_limit(html):
    # Some portals return a rate-limit page with HTTP 200.
    soup = BeautifulSoup(html, 'lxml')
    heading = ' '.join(n.get_text(' ', strip=True) for n in soup.select('title,h1,h2'))
    if re.search('访问过于频繁|请求过于频繁|Too Many Requests', heading, re.I):
        from .feeds import FeedUnavailable
        raise FeedUnavailable('原站限流提示页（HTTP 200），暂停请求并等待冷却后续采', 'blocked', 3600)


def normalized_date(value):
    match = re.search(r"(20\d{2})\s*[-年/.]\s*(\d{1,2})\s*[-月/.]\s*(\d{1,2})", value)
    if not match:
        return ""
    try:
        return datetime(*map(int, match.groups())).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def readable_text(node):
    # Inline fonts/spans are presentation, not field boundaries. Splitting every
    # text node truncated company names and dates in government Word-export HTML.
    blocks = {'p', 'div', 'section', 'article', 'tr', 'td', 'th', 'li', 'h1', 'h2', 'h3', 'h4', 'table'}
    parts = []
    def visit(item):
        if isinstance(item, (Comment, Doctype, Declaration, ProcessingInstruction)):
            return
        if isinstance(item, NavigableString):
            value = re.sub(r'\s+', ' ', str(item))
            if value.strip():
                parts.append(value)
        elif isinstance(item, Tag):
            block = item.name in blocks
            if block or item.name == 'br':
                parts.append('\n')
            for child in item.children:
                visit(child)
            if block:
                parts.append('\n')
    visit(node)
    return '\n'.join(line.strip() for line in ''.join(parts).splitlines() if line.strip())


def extract_fields(content):
    """Extract labelled values, preferring body fields to a repeated page title."""
    result = {}
    number_label = r'(?:采购项目编号|项目招标编号|项目编号|招标编号|采购编号|采购计划编号)'
    candidates = re.findall(r'(?m)^\s*(?:[一二三四五六七八九十\d]+[、.．]\s*)?'+number_label+r'[ \t]*(?:[:：]\s*|\n\s*)([^\n]{2,100})', content)
    if not candidates:
        candidates = re.findall(number_label+r'\s*[:：]\s*([^\n]{2,100})', content)
    for value in candidates:
        value = re.split(r'(?:项目名称|采购项目名称)\s*[:：]', value)[0].strip()
        value = re.sub(r'[)）]\s*(?:公开招标|竞争性|询价|中标|成交|合同).*$', '', value).strip()
        for left, right in [('(', ')'), ('（', '）')]:
            while value.endswith(right) and value.count(right) > value.count(left):
                value = value[:-1].rstrip()
        if re.search(r'\d', value) and not re.search(r'公告|详见|附件|项目名称', value):
            result['project_no'] = value
            break
    labels = {
        'purchaser': r'采购人名称|招标人名称|招标采购单位|采购单位|采购人|招标人',
        'agency': r'代理机构名称|招标代理机构名称|招标代理机构|采购代理机构|代理机构',
    }
    for field, label in labels.items():
        direct = re.search(r'(?m)^\s*(?:'+label+r')\s*[:：]\s*([^\n]{2,100})', content)
        if not direct:
            # Table layouts put the label and value in adjacent lines, without a colon.
            direct = re.search(r'(?m)^\s*(?:'+label+r')\s*\n\s*([^\n]{2,100})', content)
        value = direct[1].strip() if direct else ''
        if not value:
            section = r'(?:采购人|招标人)信息' if field == 'purchaser' else r'(?:采购|招标)?代理机构信息'
            match = re.search(section+r'\s*[:：]?\s*\n?\s*名\s*称\s*[:：]\s*([^\n]{2,100})', content)
            value = match[1].strip() if match else ''
        value = re.split(r'\s*(?:地\s*址|联系方式|项目联系人)\s*[:：]', value)[0].strip()
        value = re.sub(r'[（(]\s*需盖[^）)]*[）)]', '', value).strip()
        if value and not re.match(r'信息|名称|名\s*称|地址|联系方式|详见|本项目', value):
            result[field] = value
    deadline_patterns = [
        r'(?:提交投标文件截止时间、开标时间和地点|提交投标文件截止时间|投标截止时间|响应文件提交截止时间|报价截止时间|递交截止时间|截标/开标时间|截标时间)\s*[:：]?\s*([^\n]{8,60})',
        r'响应文件提交[\s\S]{0,220}?截止时间\s*[:：]\s*([^\n]{8,60})',
        r'并于\s*([^\n]{8,60})\s*(?:[（(]北京时间[）)]\s*)?前(?:递交投标|提交响应)文件',
    ]
    deadlines = []
    for priority, pattern in enumerate(deadline_patterns):
        for match in re.finditer(pattern, content):
            value = normalized_date(match[1])
            clock = re.search(r'(\d{1,2})\s*[:时点]\s*(\d{1,2})', match[1])
            if value and (not clock or int(clock[1]) < 24 and int(clock[2]) < 60):
                deadlines.append((bool(clock), -priority, value + (f' {int(clock[1]):02}:{int(clock[2]):02}' if clock else '')))
    if deadlines:
        result['deadline'] = max(deadlines, key=lambda x: x[:2])[2]
    amount = re.search(r'(?:预算金额|采购预算控制额度|采购预算|项目预算)\s*(?:[（(](亿元|万元|元)[）)])?\s*[:：]?\s*([\d,]+(?:\.\d+)?)\s*(亿元|万元|元)?', content)
    if amount and (amount[1] or amount[3]):
        result['budget'] = amount[2]+' '+(amount[1] or amount[3])
    return result


def extract_detail(html, url):
    soup = BeautifulSoup(html, "lxml")
    if urlsplit(url).hostname == 'www.cqggzy.com':
        body = soup.select_one('.app-detail')
        if body is None or len(body.get_text(strip=True)) < 80:
            raise ValueError('重庆交易公告正文尚未加载，页面导航不作为公告内容')
        soup = BeautifulSoup('<article>'+str(body)+'</article>', 'lxml')
    if urlsplit(url).hostname == 'www.hbggzyfwpt.cn':
        body = soup.select_one('#detailNeirong, .detailNeirong')
        if body is None or len(body.get_text(strip=True)) < 80:
            raise ValueError('湖北原站正文尚未加载，页面导航不作为公告内容，请打开原文查看')
        soup = BeautifulSoup('<article>'+str(body)+'</article>', 'lxml')
    if urlsplit(url).hostname == 'ggzy.xizang.gov.cn':
        body = soup.select_one('.content-text, article')
        if body is None or len(body.get_text(strip=True)) < 80:
            raise ValueError('西藏交易公告正文尚未加载，页面导航不作为公告内容')
        soup = BeautifulSoup('<article>'+str(body)+'</article>', 'lxml')
    if urlsplit(url).hostname == 'ggzy.ah.gov.cn' and soup.select_one('#zbgg, #zbjg'):
        nature = parse_qs(urlsplit(url).query).get('bulletinNature', ['1'])[0]
        body = soup.select_one('#zbjg' if nature == '3' else '#zbgg')
        if body is None or len(body.get_text(strip=True)) < 80:
            raise ValueError('安徽原站未返回当前公告正文，请打开原文查看')
        body.attrs.pop('style', None)
        soup = BeautifulSoup('<article>'+str(body)+'</article>', 'lxml')
    if urlsplit(url).hostname == 'www.ccgp-ningxia.gov.cn':
        body = soup.select_one('#zbDiv')
        if body is None or len(body.get_text(strip=True)) < 100:
            raise ValueError('宁夏原站正文需要动态加载，当前未取得有效正文，请打开原文查看；页面导航不作为公告内容')
        # Procurement intentions include a table outside the short lead paragraph.
        soup = BeautifulSoup('<article>'+str(body)+'</article>', 'lxml')
    if urlsplit(url).hostname == "ec.ceec.net.cn":
        body = soup.select_one('#yugaozw, #xmjs')
        if body is not None and len(body.get_text(strip=True)) < 80:
            raise ValueError("来源未公开可用正文，可能需要登录或签收公告，请在原网站查看")
    for node in soup.select('[hidden], [style]'):
        if node.attrs and (node.has_attr('hidden') or re.search(r'display\s*:\s*none', node.get('style', ''), re.I)):
            node.decompose()
    for node in soup.select("script,style,noscript,nav,header,footer,input,button,select,textarea,iframe,#baoming,#Panel1"):
        node.decompose()
    # Prefer the source's announcement container over global navigation and recommendation lists.
    candidates = soup.select("article, .article-content, .article_content, .vF_detail_content, "
                             "#news_content, #contentText, .TRS_Editor, .detail-content, .detail_content, .information_box, .ewb-details-info")
    node = max(candidates, key=lambda n: len(n.get_text()), default=soup.body or soup)
    content = readable_text(node)
    if len(content) < 100 or re.search(r"^(安全验证|验证码|访问受限|Access Denied)", content[:80], re.I):
        raise ValueError("未获取到可用公告正文，可能需要登录或网页尚未加载，请查看原文")
    result = {"content": content[:200000], "attachments": []}
    if urlsplit(url).hostname == "ec.ceec.net.cn":
        title_node = soup.select_one('#yugaobt, #gonggaobt')
        if title_node and title_node.get_text(strip=True):
            result['title'] = title_node.get_text(strip=True)
    for a in node.select("a[href]"):
        link = urljoin(url, a["href"])
        if urlsplit(link).scheme in ("http", "https") and re.search(r"\.(pdf|docx?|xlsx?|zip|rar)(?:[?#]|$)", link, re.I):
            result["attachments"].append({"name": a.get_text(strip=True) or "公告附件", "url": link})
    fields = {
        "budget": r"(?:预算金额|项目预算|采购预算)\s*[:：]\s*([^\n]{2,80})",
        "region": r"(?:项目所在地区|项目所在地|所属地区)\s*[:：]\s*([^\n]{2,60})",
    }
    for key, pattern in fields.items():
        match = re.search(pattern, content)
        if match:
            result[key] = match[1].strip()
    amount = re.search(r'(?:预算金额|采购预算)\s*[（(]([^）)\n]{1,12})[）)]\s*[:：]\s*([\d,.]+)',content)
    if amount:
        result['budget'] = amount[2] + ' ' + amount[1]
    amount_tail = re.search(r'(?:预算金额|采购预算)\s*[:：]\s*([\d,.]+)\s*[（(]\s*(亿元|万元|元|美元|万美元)\s*[）)]',content)
    if amount_tail:
        result['budget'] = amount_tail[1] + ' ' + amount_tail[2]
    if urlsplit(url).hostname == 'www.ccgp.gov.cn':
        for cell in soup.select('td'):
            if cell.get_text(strip=True) in ('品目','采购品目'):
                value = cell.find_next_sibling('td')
                if value:
                    category = value.get_text(strip=True)
                    for label in ('工程','货物','服务'):
                        if category.startswith(label):
                            result['category'] = label
                            break
    if not result.get('region'):
        location = re.search(r'(?:交货地点|项目地点|建设地点)\s*[:：]\s*([^\n]{2,100})', content)
        if location:
            province = re.search(r'(北京市|天津市|上海市|重庆市|内蒙古自治区|广西壮族自治区|西藏自治区|宁夏回族自治区|新疆维吾尔自治区|[\u4e00-\u9fff]{2,3}省)', location[1])
            if province:
                result['region'] = province[1]
    for key, label in (("published_at", "预告发布时间|发布时间|发布日期|发布日"),
                       ("deadline", "投标截止时间|响应文件提交截止时间|报价截止时间|递交截止时间|截标/开标时间|截标时间")):
        match = re.search(r"(?:" + label + r")\s*[:：]?\s*([^\n]{8,50})", content)
        if match:
            value = normalized_date(match[1])
            if value:
                clock = re.search(r"(\d{1,2})\s*[:时点]\s*(\d{2})", match[1])
                result[key] = value + (f" {int(clock[1]):02}:{clock[2]}" if clock else "")
    response_deadline = re.search(r'响应文件提交[\s\S]{0,220}?截止时间\s*[:：]\s*([^\n]{8,50})',content)
    if response_deadline:
        day = normalized_date(response_deadline[1])
        clock = re.search(r'(\d{1,2})\s*[:时点]\s*(\d{2})',response_deadline[1])
        if day:
            result['deadline'] = day + (f' {int(clock[1]):02}:{clock[2]}' if clock else '')
    result.update(extract_fields(content))
    if urlsplit(url).hostname == "ec.ceec.net.cn":
        article = soup.select_one('#yugaozw, #xmjs')
        if article and len(article.get_text(strip=True)) >= 80:
            result['content'] = '\n'.join(line.strip() for line in article.get_text('\n').splitlines() if line.strip())[:200000]
    return result


def fetch_detail(url):
    parsed = urlsplit(url)
    if parsed.hostname == 'www.hnsggzy.com' and parsed.fragment.startswith('/resources/transactionDetail/'):
        from .feeds import public_json
        from .provincial_more import hunan_notices
        query = parse_qs(urlsplit(parsed.fragment).query)
        identity = query.get('notice_id', [''])[0]
        records = hunan_notices(query.get('bidSectionId', [''])[0], public_json)
        record = next((r for r in records if str(r.get('id')) == identity), None)
        if not record or not record.get('noticeContent'):
            raise ValueError('湖南工程未返回当前公告正文，请打开原文核对')
        result = extract_detail('<article>'+record['noticeContent']+'</article>', url)
        result['title'] = BeautifulSoup(record.get('noticeName') or '', 'lxml').get_text(' ', strip=True)
        result['published_at'] = normalized_date(record.get('noticeSendTime') or '')
        return result
    hubei_details = {
        '/jyxx/zfcg/cgggDetail': ('zfcgCgggDetail', 'object', 'bulletinContent', 'bulletinTitle'),
        '/jyxx/zfcg/gzsxDetail': ('zfcgGzsxDetail', 'bean', 'terminationBulletinContent', 'terminationBulletinTitle'),
        '/jyxx/zfcg/zbjggsDetail': ('showZbjgDeatail', 'object', 'winBidBulletinContent', 'winBidBulletinTitle'),
    }
    if parsed.hostname == 'www.hbggzyfwpt.cn' and parsed.path in hubei_details:
        from .feeds import public_json
        identity = parse_qs(parsed.query).get('guid', [''])[0]
        if not re.fullmatch(r'[a-zA-Z0-9_-]{8,120}', identity):
            raise ValueError('湖北采购公告链接缺少有效编号')
        endpoint, container, field, title = hubei_details[parsed.path]
        response = public_json('https://www.hbggzyfwpt.cn/jyxxAjax/zfcg/'+endpoint, data=dict(guid=identity))
        record = response.get(container) or {}
        if str(record.get('guid')) != identity or not record.get(field):
            raise ValueError('湖北采购接口未返回当前公告正文，请打开原文查看')
        result = extract_detail('<div id="detailNeirong">'+record[field]+'</div>', url)
        result['title'] = BeautifulSoup(record.get(title) or '', 'lxml').get_text(' ', strip=True)
        return result
    if parsed.hostname == 'ggzy.xizang.gov.cn' and re.fullmatch(r'/jyxx[a-z]+/\d+\.jhtml', parsed.path):
        from .feeds import public_json
        html, _ = fetch_page(url)
        match = re.search(r"var\s+pc\s*=\s*'([^']+)'", html)
        if not match:
            return extract_detail(html, url)
        code = match[1]
        channel, identity = parsed.path.strip('/').split('/')
        identity = identity.removesuffix('.jhtml')
        response = public_json('https://ggzy.xizang.gov.cn/personalitySearch/initDetailbyProjectCode',
                               json_data=dict(projectCode=code, path=channel, sId=22))
        records = (response.get('data') or {}).get('listData') or []
        record = next((r for r in records if str(r.get('id')) == identity and r.get('projectCode') == code), None)
        if str(response.get('code')) != '200' or not record or not record.get('txt'):
            raise ValueError('西藏交易接口未返回当前公告正文，请打开原文核对')
        result = extract_detail('<article>'+record['txt']+'</article>', url)
        result['title'] = BeautifulSoup(record.get('title') or '', 'lxml').get_text(' ', strip=True)
        result['published_at'] = normalized_date(record.get('publishTime') or '')
        return result
    if parsed.hostname == 'ggzyfw.fj.gov.cn' and parsed.path == '/business/detail':
        from .feeds import public_json
        from .provincial_more import fujian_public
        query = parse_qs(parsed.query)
        params = {k: query.get(k, [''])[0] for k in ('name', 'cid', 'type')}
        identity = query.get('notice_id', [''])[0]
        if params['type'] not in ('GCJS', 'ZFCG', 'TDSYQ', 'KYQ', 'GYCQ', 'QT') or not identity.isdigit() or not params['cid']:
            raise ValueError('福建交易公告链接缺少有效栏目或编号')
        detail = fujian_public('/Trade/TradeInfoDetail', params, public_json)
        if params['type'] == 'GCJS':
            candidates = [r for n in detail.get('Nodes', []) for r in n.get('Children', [])]
            node = next((r for r in candidates if str(r.get('M_ID')) == identity and str(r.get('Type')) == query.get('notice_type', [''])[0]), None)
            content_type = node.get('Type') if node else None
        else:
            candidates = [r for n in detail.values() if isinstance(n, dict) for r in n.get('Data', [])]
            node = next((r for r in candidates if str(r.get('M_ID')) == identity), None)
            content_type = node.get('ENTITY_TYPE') if node else None
        if not node or not content_type:
            raise ValueError('福建项目详情中未找到当前公告，保留原有数据，请打开原文核对')
        record = fujian_public('/Trade/TradeInfoContent', dict(type=content_type, m_id=identity), public_json)
        if str(record.get('M_ID')) != identity or not record.get('Contents'):
            raise ValueError('福建原站未返回当前公告正文，可能仅提供附件，请打开原文查看')
        result = extract_detail('<article>'+record['Contents']+'</article>', url)
        base = detail.get('BaseInfo') or {}
        for field, names in [('project_no', ('TENDER_PROJECT_CODE', 'ProjectCode')), ('purchaser', ('TENDERER_NAME',)),
                             ('agency', ('TENDER_AGENCY_NAME',)), ('deadline', ('BID_DOC_REFER_END_TIME',))]:
            value = next((base.get(k) for k in names if base.get(k)), '')
            if value and not result.get(field):
                result[field] = str(value)
        return result
    if parsed.hostname == 'ggzy.yn.gov.cn' and parsed.fragment.startswith('/tradeHall/tradeDetail?'):
        from .feeds import public_json
        from .provincial_more import YUNNAN_COLUMNS
        query = parse_qs(urlsplit(parsed.fragment).query)
        identity = query.get('guid', [''])[0]
        category, label = query.get('colCode', [''])[0], query.get('rowCode', [''])[0]
        config = next((c for c in YUNNAN_COLUMNS.values() if c[:2] == (category, label)), None)
        if not config or not re.fullmatch(r'[a-zA-Z0-9_-]{8,120}', identity):
            raise ValueError('云南交易公告链接缺少有效栏目或编号')
        endpoint = config[2].rsplit('/', 1)[0]+'/'+config[5]
        response = public_json('https://ggzy.yn.gov.cn/ynggfwpt-home-api'+endpoint+'?'+urlencode(dict(guid=identity)))
        record = response.get('value') or {}
        body = record.get('bulletincontent') or record.get('winbidbulletincontent') or record.get('terminationbulletincontent') or record.get('changecontent')
        if str(response.get('code')) != '1' or record.get('guid') != identity or not body:
            raise ValueError('云南交易平台未返回当前公告正文，请打开原文核对')
        result = extract_detail('<article>'+body+'</article>', url)
        result['title'] = BeautifulSoup(record.get(config[3]) or '', 'lxml').get_text(' ', strip=True)
        result['published_at'] = normalized_date(record.get(config[4]) or '')
        if not result.get('project_no'):
            result['project_no'] = record.get('purchaseprojectcode') or record.get('tenderprojectcode') or ''
        return result
    if parsed.hostname == 'www.ccgp-chongqing.gov.cn' and re.fullmatch(r'/info-notice/procument-notice-detail/\d+', parsed.path):
        from .feeds import public_json
        from .provincial_more import decode_chongqing
        identity = parsed.path.rsplit('/', 1)[1]
        response = public_json('https://www.ccgp-chongqing.gov.cn/gwebsite/api/v1/notices/stable/'+identity, decoder=decode_chongqing)
        record = response.get('notice') or {}
        if response.get('res') != 0 or str(record.get('id')) != identity or not record.get('html'):
            raise ValueError('重庆采购网未返回当前公告正文，请打开原站核对')
        result = extract_detail('<article>'+record['html']+'</article>', url)
        result['title'] = record.get('title') or ''
        result['published_at'] = normalized_date(record.get('issueTime') or '')
        for field, key in [('purchaser','buyerName'), ('agency','agentName'), ('project_no','projectCode'), ('deadline','bidEndTime')]:
            if record.get(key) and not result.get(field):
                result[field] = str(record[key])
        return result
    if parsed.hostname == 'ggzyjy.nmg.gov.cn' and parsed.path in ('/jyxx/index_24.html', '/jyxx/index_39.html'):
        from .feeds import public_json
        identity = parse_qs(parsed.query).get('id', [''])[0]
        if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,200}', identity):
            raise ValueError('内蒙古交易公告链接缺少有效编号')
        response = public_json('https://ggzyjy.nmg.gov.cn/trssearch/openSearch/getPublishResourceDealContent?'+urlencode(dict(sourceDataKey=identity)))
        record = (response.get('data') or {}).get('dealContent') or {}
        if str(response.get('state')) != '200' or record.get('sourceDataKey') != identity or not record.get('noticeContent'):
            raise ValueError('内蒙古交易平台未返回当前公告正文，请打开原站核对')
        result = extract_detail('<article>'+record['noticeContent']+'</article>', url)
        result['title'] = BeautifulSoup(record.get('noticeName') or '', 'lxml').get_text(' ', strip=True)
        result['published_at'] = normalized_date(record.get('noticeSendTime') or '')
        if record.get('projectCode') and not result.get('project_no'):
            result['project_no'] = str(record['projectCode'])
        return result
    if parsed.hostname == 'www.ccgp-liaoning.gov.cn' and parsed.path == '/portaldetail':
        # The anonymous homepage is public, while the current detail API asks
        # for authorization. Never mistake the SPA/navigation shell for a body.
        raise ValueError('辽宁原站正文接口要求授权，请打开原文查看；当前仅采集公开首页公告')
    if parsed.hostname == 'www.ccgp-yunnan.gov.cn' and parsed.path == '/ggmxinfo.html':
        identity = parse_qs(parsed.query).get('bulletinid', [''])[0]
        if not re.fullmatch(r'[a-zA-Z0-9.\-]{8,100}', identity):
            raise ValueError('云南公告链接缺少有效编号')
        body, _ = fetch_page(f'{parsed.scheme}://{parsed.netloc}/ggInfo.html?'+urlencode(dict(bulletin_id=identity)))
        soup = BeautifulSoup(body, 'lxml')
        node = soup.select_one('#showBulletinInfoDiv .vF_detail_content')
        if node is None or len(node.get_text(strip=True)) < 80:
            raise ValueError('云南原站未返回当前公告正文，请打开原文核对')
        # The official page toggles this already-public body on "显示公告正文".
        node.attrs.pop('style', None)
        result = extract_detail('<article>'+str(node)+'</article>', url)
        title = soup.select_one('#showBulletinInfoDiv h2')
        if title:
            result['title'] = title.get_text(' ', strip=True)
        published = soup.select_one('#showBulletinInfoDiv #pubTime')
        if published:
            result['published_at'] = normalized_date(published.get_text())
        return result
    gpcms_routes = {'www.ccgp-gansu.gov.cn': '/maincms-web/articleGs',
                    'www.ccgp-neimenggu.gov.cn': '/maincms-web/articleNm'}
    if parsed.hostname in gpcms_routes and parsed.path == gpcms_routes[parsed.hostname]:
        from .feeds import public_json
        identity = parse_qs(parsed.query).get('id', [''])[0]
        if not re.fullmatch(r'[a-fA-F0-9-]{8,80}', identity):
            raise ValueError('省采购网公告链接缺少有效编号')
        response = public_json(f'{parsed.scheme}://{parsed.netloc}/gpcms/rest/web/v2/info/getInfoById?'+urlencode(dict(id=identity)))
        record = response.get('data') or {}
        if str(response.get('code')) != '200' or record.get('id') != identity or not record.get('content'):
            raise ValueError('省采购网未返回当前公告正文，请打开原站核对')
        result = extract_detail('<article>'+record['content']+'</article>', url)
        result['title'] = BeautifulSoup(record.get('title') or '', 'lxml').get_text(' ', strip=True)
        result['published_at'] = normalized_date(record.get('noticeTime') or '')
        for field, key in [('purchaser', 'purchaser'), ('agency', 'agency'), ('project_no', 'openTenderCode'), ('deadline', 'openTenderTime')]:
            if record.get(key) and not result.get(field):
                result[field] = str(record[key])
        return result
    if parsed.hostname == 'www.qhggzyjy.gov.cn' and parsed.path == '/ggzy/projectDetail.html':
        from .feeds import public_json
        query = parse_qs(parsed.query)
        identity, category = query.get('infoid', [''])[0], query.get('categorynum', [''])[0]
        if not re.fullmatch(r'[a-fA-F0-9-]{8,80}', identity) or not re.fullmatch(r'\d{6,12}', category):
            raise ValueError('青海公告链接缺少有效编号')
        index = public_json(f'{parsed.scheme}://{parsed.netloc}/qhztbjson/getDetails/{identity}.json')
        records = index.get('infoList') or []
        match = next((r for r in records if r.get('infoid') == identity and r.get('categorynum') == category), None)
        if not match:
            raise ValueError('青海原站未返回当前公告的正文索引，请打开原站核对')
        path = match.get('visiturl') or ''
        if not re.fullmatch(r'/jyxx/(?:\d+/)+\d{8}/'+re.escape(identity)+r'\.html', path) or '/'+category+'/' not in path:
            raise ValueError('青海正文地址与当前公告不一致，请打开原站核对')
        html, final_url = fetch_page(f'{parsed.scheme}://{parsed.netloc}/ggzy'+path)
        result = extract_detail(html, final_url)
        if match.get('title'):
            result['title'] = BeautifulSoup(match['title'], 'lxml').get_text(' ', strip=True)
        if normalized_date(match.get('infodate') or ''):
            result['published_at'] = normalized_date(match['infodate'])
        return result
    from .provincial import ZCY, timestamp
    from .sources import PROVINCES
    provincial_hosts = {f'www.ccgp-{slug}.gov.cn' for code, _, slug, _ in PROVINCES if code in ZCY}
    provincial_hosts.add('www.ccgp-anhui.gov.cn')
    if parsed.hostname in provincial_hosts and parsed.path in ('/site/detail', '/luban/detail', '/luban/front/detail'):
        from .feeds import public_json
        query = parse_qs(parsed.query)
        key = query.get('articleId', [''])[0]
        if not key or len(key) > 200:
            raise ValueError('省站公告链接缺少有效编号')
        response = public_json(f'{parsed.scheme}://{parsed.netloc}/portal/detail?'+urlencode({'articleId': key}))
        data = response.get('result', {}).get('data', {})
        if response.get('success') is not True or not data.get('content'):
            raise ValueError('省站正文未公开或需要验证，请打开原站查看')
        result = extract_detail('<article>'+data['content']+'</article>', url)
        result.update({k:v for k,v in dict(title=data.get('title'), published_at=timestamp(data.get('publishDate')),
                                          project_no=data.get('projectCode')).items() if v})
        return result
    if parsed.hostname in ('www.crccep.cn', 'c.cnbm.com.cn'):
        from .feeds import public_json
        if parsed.hostname == 'www.crccep.cn':
            query = parse_qs(parsed.query)
            key = query.get('noticeId', [''])[0]
            column = query.get('columnId', ['BiddingAnnouncement'])[0]
            if not key.isdigit() or not re.fullmatch('[A-Za-z]+', column):
                raise ValueError('铁建云链公告链接缺少有效编号')
            data = public_json('https://www.crccep.cn/crcc-purportal-manage/portal/specialtopic/findNoticesDetails?'+
                               urlencode({'id': key, 'columnId': column}))
            body = data.get('noticeContent') or ''
            metadata = dict(title=data.get('noticeTitle') or '', purchaser=data.get('orgSimpleName') or '',
                            published_at=data.get('publishTime') or '', deadline=data.get('bidEndTime') or '',
                            project_no=data.get('tenderProjectCode') or '')
        else:
            query = parse_qs(urlsplit(parsed.fragment).query or parsed.query)
            key = query.get('noticeCode', [''])[0]
            if not re.fullmatch(r'[A-Za-z0-9_-]+', key):
                raise ValueError('中国建材公告链接缺少有效编号')
            response = public_json('https://c.cnbm.com.cn/portal-sso/bid/queryByCodeFromNotice?'+urlencode({'noticeCode': key}))
            if str(response.get('code')) != '200':
                raise ValueError('中国建材暂未提供公开正文，请打开原站查看')
            data = response.get('data') or {}
            body = data.get('contentText') or ''
            metadata = dict(title=data.get('noticeTitle') or '', purchaser=data.get('tenderName') or '',
                            published_at=data.get('createTime') or '', deadline=data.get('quoteStopTime') or '',
                            project_no=data.get('projectCode') or '')
        result = extract_detail('<article>'+body+'</article>', url)
        result.update({k:v for k,v in metadata.items() if v})
        return result
    html, final_url = fetch_page(url)
    if urlsplit(final_url).hostname == 'zfcg.henan.gov.cn' and urlsplit(final_url).path == '/henan/content':
        identity = parse_qs(urlsplit(final_url).query).get('infoId', [''])[0]
        match = re.search(r'\$\.get\(["\']([^"\']+)["\']', html)
        if not identity.isdigit() or not match or not re.fullmatch(r'/cmsweb[a-zA-Z0-9]+/(?:[a-zA-Z0-9_]+/)+webinfo/\d{4}/\d{2}/'+identity+r'\.htm', match[1]):
            raise ValueError('河南公告正文地址未识别，不能将导航页面作为正文')
        soup = BeautifulSoup(html, 'lxml')
        title = soup.select_one('#print-content h1')
        body, _ = fetch_page(urljoin(final_url, match[1]))
        result = extract_detail('<article>'+body+'</article>', final_url)
        if title:
            result['title'] = title.get_text(' ', strip=True)
        return result
    if urlsplit(final_url).hostname == 'www.ggzy.gov.cn' and '/information/deal/html/a/' in final_url:
        # The public landing page contains a timeline; its body is a separate static document.
        match = re.search(r"var\s+firstLastUrl\s*=\s*['\"]([^'\"]+)['\"]", html)
        if not match:
            raise ValueError('全国平台未提供正文地址，请打开原站核对')
        body_url = urljoin(final_url, match[1])
        expected = urlsplit(final_url).path.replace('/html/a/', '/html/b/', 1)
        if urlsplit(body_url).hostname != 'www.ggzy.gov.cn' or urlsplit(body_url).path != expected:
            raise ValueError('正文地址与当前公告不一致，请打开原站核对')
        html, final_url = fetch_page(body_url)
    if urlsplit(final_url).hostname == "ec.ceec.net.cn":
        soup = BeautifulSoup(html, "lxml")
        dynamic = soup.select_one('#yugaozw, #xmjs')
        if dynamic is not None and len(dynamic.get_text(strip=True)) < 80:
            html, final_url = browser_page(final_url)
            rendered = BeautifulSoup(html, "lxml").select_one('#yugaozw, #xmjs')
            if rendered is None or len(rendered.get_text(strip=True)) < 80:
                raise ValueError("来源尚未返回公告正文，请稍后重试或查看原文")
    return extract_detail(html, final_url)
