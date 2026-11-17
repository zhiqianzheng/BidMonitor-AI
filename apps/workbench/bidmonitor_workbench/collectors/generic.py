"""Conservative, bounded collection for additional public notice lists."""
import re
from datetime import datetime
from urllib.parse import parse_qs
from urllib.parse import urljoin, urlsplit, urldefrag

from bs4 import BeautifulSoup

from .detail import normalized_date
from ..storage.availability import CHINA_TIME
from ..storage.taxonomy import classify_notice, is_result_notice


NOISE = re.compile(r'操作指南|用户手册|平台维护|系统升级|政策解读|管理办法|工作动态|新闻|培训通知|招聘|采购法规|专家征集|工作组|采购规则|采购制度|采购指南|招标培训|采购培训|系统演示|系统测试|测试项目|国泰测试|测试公告|全国统一大市场|招标投标领域|实施意见')
NOTICE = re.compile(r'招标|采购|询价|询比|磋商|谈判|竞价|比选|遴选|资格预审|招募|征集')


def publication_date(anchor, row, title, path):
    """Read publication fields, never the first of several unrelated dates."""
    value = normalized_date(anchor.get('data-published', ''))
    if not value and row and row.name == 'tr':
        table = row.find_parent('table')
        headers = table.select('thead th') if table else []
        if not headers and table:
            headers = table.select('tr th')
        cells = row.find_all('td', recursive=False)
        for index, header in enumerate(headers):
            if re.search('发布时间|发布日期|公告日期|发布日', header.get_text()):
                if index < len(cells):
                    value = normalized_date(cells[index].get_text(' ', strip=True))
                break
    parent = row
    if not value:
        for _ in range(3):
            if not parent or parent.name in ('body', 'html', 'main'):
                break
            text = parent.get_text(' ', strip=True)
            if len(text) > 2000:
                break
            others = [a for a in parent.select('a[href]') if a is not anchor
                      and NOTICE.search(a.get_text(' ', strip=True))
                      and a.get('href') != anchor.get('href')]
            if others:
                break
            label = anchor.select_one('[title],.item-name,.title,.txt')
            visible = label.get_text(' ', strip=True) if label else title
            text = text.replace(title, '').replace(visible, '')
            explicit = re.search(r'(?:发布时间|发布日期|发布于|公告日期)\s*[:：]?\s*(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2})', text)
            if explicit:
                value = normalized_date(explicit[1])
            else:
                dates = {normalized_date(match[0]) for match in re.finditer(r'20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}', text)} - {''}
                # Multiple different dates have no safe default.
                if len(dates) == 1 and not re.search('截止|开标|报名|会议时间|活动时间', text):
                    value = dates.pop()
            if value:
                break
            parent = parent.parent
    if not value:
        value = normalized_date(path)
    if not value:
        compact = re.search(r'/(20\d{2})([01]\d)([0-3]\d)(?:/|_)', path)
        if compact:
            value = normalized_date('-'.join(compact.groups()))
    if value and value > datetime.now(CHINA_TIME).date().isoformat():
        return ''
    return value


def etrading_kind(link):
    parsed = urlsplit(link)
    if not (parsed.hostname or '').endswith('.etrading.cn'):
        return ''
    category = (parse_qs(parsed.query).get('categorynum') or [''])[0]
    if not category:
        match = re.search(r'/((?:001|002)00[1-9]00[1-4]|02600[1-5])/', parsed.path)
        category = match[1] if match else ''
    if category.startswith(('001', '002')) and len(category) == 9:
        return {'001': '招标公告', '002': '变更公告', '003': '中标候选', '004': '中标结果'}.get(category[-3:], '')
    return {'026001': '招标公告', '026002': '变更公告', '026003': '中标候选', '026004': '中标结果', '026005': '采购需求'}.get(category, '')


def parse_listing(html, url, source):
    """Require a dated opportunity link; never invent a date from the title."""
    soup, seen = BeautifulSoup(html, 'lxml'), set()
    # Decode only the observed literal URL argument, without executing JavaScript.
    for anchor in soup.select('a[onclick]:not([href])'):
        match = re.fullmatch(r"geturl\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"][\w-]+['\"]\s*,\s*['\"]\d+['\"]\s*\)\s*;?", anchor['onclick'])
        if match:
            anchor['href'] = match[1]
    for anchor in soup.select('a[href]'):
        label = anchor.select_one('[title],.item-name,.title,.txt')
        label_text = (label.get('title') or label.get_text(' ', strip=True)) if label else anchor.get_text(' ', strip=True)
        title = re.sub(r'\s+', ' ', anchor.get('title') or label_text).strip()
        link = urljoin(url, anchor['href'].strip())
        if not urlsplit(link).fragment.startswith(('/', '!/')):
            link = urldefrag(link)[0]
        parsed = urlsplit(link)
        if parsed.scheme not in ('http', 'https') or parsed.hostname != urlsplit(url).hostname:
            continue
        kind = etrading_kind(link)
        if link in seen or not 8 <= len(title) <= 500 or (not NOTICE.search(title) and not kind):
            continue
        if NOISE.search(title) or is_result_notice(title, kind) or anchor.find_parent(['nav', 'header', 'footer']):
            continue
        if re.search(r'\.(xlsx?|zip|rar|exe|jpg|png)$|/(login|register|help)(/|$)', parsed.path, re.I):
            continue
        parent = anchor.find_parent(['li', 'tr']) or anchor.parent
        published = publication_date(anchor, parent, title, parsed.path)
        if not published:
            continue
        seen.add(link)
        yield dict(title=title, url=link, published_at=published, source=source['name'],
                   region='' if source['province'] in ('全国', '待核实') else source['province'], notice_type=kind or classify_notice(title))


def collect_generic(source, stop, pages, html_fetch):
    from .feeds import FeedUnavailable
    queued = [source.get('list_url') or source['url']]
    visited, seen, rows, warnings = set(), set(), [], []
    first_listing = None
    discovered = []
    blocked = False
    while queued and len(visited) < pages and not stop.is_set():
        url = queued.pop(0)
        if url in visited:
            continue
        if visited and stop.wait(1):
            break
        visited.add(url)
        try:
            html, final = html_fetch(url)
            from .discovery import discover_links
            discovered.extend(discover_links(html, final, source))
            for row in parse_listing(html, final, source):
                if row['url'] not in seen:
                    seen.add(row['url'])
                    rows.append(row)
                    if first_listing is None:
                        first_listing = final
            soup = BeautifulSoup(html, 'lxml')
            for anchor in soup.select('a[href]'):
                label = anchor.get_text('', strip=True)
                category = label in ('招标公告', '采购公告', '采购信息', '招标采购', '招标信息', '采购与招标', '公开招标', '询价公告', '采购意向', '采购计划', '招采公告', '采购招标', '招标与采购', '采购中心', '招标采购中心')
                if not category and not re.fullmatch(r'下一页|下页|Next|[>›»]+', label, re.I) and anchor.get('rel') != ['next']:
                    continue
                link = urldefrag(urljoin(final, anchor['href']))[0]
                if len(queued) >= 20:
                    break
                if urlsplit(link).scheme in ('https', 'http') and urlsplit(link).hostname == urlsplit(final).hostname and link not in visited and link not in queued:
                    queued.append(link)
        except ValueError as error:
            if not rows:
                raise
            warnings.append(str(error))
            blocked = getattr(error, 'status', '') == 'blocked'
            break
    if not rows and not stop.is_set():
        error = FeedUnavailable('未识别到含发布时间的公开招采列表；动态页面或专用接口需要适配，不能视为已接入', 'needs_adapter')
        error.discovered_sources = discovered
        raise error
    return dict(rows=rows, warnings=warnings, blocked=blocked, discovered_sources=discovered, empty_ok=False, truncated=True,
                list_url=first_listing, message=f'公开列表读取 {len(visited)} 页，收录 {len(rows)} 条标题、原始链接及发布时间；非全量覆盖')
