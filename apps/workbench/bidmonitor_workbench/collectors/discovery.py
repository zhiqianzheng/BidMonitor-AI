"""Find related procurement websites from public navigation, with provenance."""
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .registry import normalize_source

PLATFORM = re.compile(r'采购(?:网|平台|中心|系统|管理|与招标)|招标(?:网|平台|采购|中心|代理)|招投标|招采|公共资源|交易中心|阳光采购|电子交易|易采|中招')
NOISE = re.compile(r'公告|公示|新闻|通知|办法|条例|政策|培训|认证|登录|注册|操作|指南|收费|合同|文件|下载|法律|标准|手册|关于|系统维护|制度')


def discover_links(html, page_url, source):
    soup = BeautifulSoup(html, 'lxml')
    rows, seen = [], set()
    for anchor in soup.select('a[href],option[value]'):
        href = anchor.get('href') or anchor.get('value') or ''
        if not href.strip():
            continue
        url = urljoin(page_url, href.strip())
        parsed = urlsplit(url)
        if parsed.scheme not in ('https', 'http') or not parsed.hostname:
            continue
        if parsed.hostname == urlsplit(page_url).hostname:
            continue
        name = re.sub(r'\s+', ' ', anchor.get('title') or anchor.get_text(' ', strip=True)).strip()
        if not 4 <= len(name) <= 100 or not PLATFORM.search(name) or NOISE.search(name):
            continue
        if re.search(r'\.(?:pdf|docx?|xlsx?|zip|jpg|png)(?:$|\?)', url, re.I) or re.search(r'/20\d{2}[/-]?\d{2}[/-]?\d{2}', parsed.path):
            continue
        if name in seen:
            continue
        kind = '高校科研' if re.search('大学|学院|高校', name) else '医疗卫生' if re.search('医院|卫生|医疗', name) else '公共资源' if '公共资源' in name else '行业平台'
        try:
            item = normalize_source(dict(name=name, url=url, province='待核实', kind=kind))
        except ValueError:
            continue
        item.update(evidence_url=page_url, directory_group='来源网站关联导航', auto_discovered=True,
                    discovered_from=source['id'])
        seen.add(name)
        rows.append(item)
    return rows
