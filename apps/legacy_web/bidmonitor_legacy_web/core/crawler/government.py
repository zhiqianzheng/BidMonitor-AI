"""Parse public CCGP announcement lists, without sector keyword filtering."""
import re
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
from .detail import normalized_date
try:
    from ..database.taxonomy import classify_notice
except ImportError:
    from apps.legacy_web.bidmonitor_legacy_web.core.database.taxonomy import classify_notice

SOURCE = {"id": "ccgp", "name": "中国政府采购网（中央及地方公告）",
          "url": "https://www.ccgp.gov.cn/cggg/dfgg/index.htm",
          "pages": ("https://www.ccgp.gov.cn/cggg/zygg/index.htm", "https://www.ccgp.gov.cn/cggg/dfgg/index.htm")}


def parse_announcements(html, url):
    soup, seen = BeautifulSoup(html, 'lxml'), set()
    for a in soup.select('a[href]'):
        link = urljoin(url, a['href'])
        parsed = urlsplit(link)
        if parsed.hostname != 'www.ccgp.gov.cn' or not re.search(r'/cggg/(zygg|dfgg)/[^/]+/\d{6}/t\d+_\d+\.htm$', parsed.path):
            continue
        if link in seen:
            continue
        title = a.get('title') or a.get_text(strip=True)
        if len(title) < 6:
            continue
        seen.add(link)
        row = a.find_parent('li')
        row_text = row.get_text(' ',strip=True) if row else ''
        region = re.search(r'地域\s*[:：]\s*(.*?)\s*采购人', row_text)
        buyer = re.search(r'采购人\s*[:：]\s*(.+)$', row_text)
        published = re.search(r'发布时间\s*[:：]\s*(20\d{2}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)',row_text)
        yield dict(title=title,url=link,source='中国政府采购网',notice_type=classify_notice(title),
                   published_at=published[1] if published else '',region=region[1].strip() if region else '',
                   purchaser=buyer[1].strip() if buyer else '')
