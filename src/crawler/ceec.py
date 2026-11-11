"""Announcement links from the public CEEC homepage (not news or navigation)."""
import re
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
from .detail import normalized_date

DETAIL_TYPES = {
    "yugao_detail.aspx": "采购意向",
    "zigeysgg_details.aspx": "资格预审",
    "zhaobiaogg_details.aspx": "招标公告",
    "projectdetail.aspx": "招标公告",
    "windiddetails.aspx": "中标结果",
}


def parse_announcements(html, url):
    soup, seen = BeautifulSoup(html, "lxml"), set()
    for a in soup.select("a[href]"):
        link = urljoin(url, a["href"])
        parsed = urlsplit(link)
        kind = DETAIL_TYPES.get(parsed.path.rsplit("/", 1)[-1].lower())
        if not kind or parsed.hostname != "ec.ceec.net.cn" or parsed.scheme not in ("http", "https") or link in seen:
            continue
        title = re.sub(r"^\s*\[公开\]\s*", "", a.get_text(" ", strip=True))
        if kind != '采购意向' and a.get('title'):
            tooltip_title = re.split(r'\s*发布时间\s*[:：]', a['title'])[0].strip()
            if len(tooltip_title) >= len(title.rstrip('.…')):
                title = tooltip_title
        if len(title) < 6:
            continue
        seen.add(link)
        row = a.find_parent("li")
        date_text = a.get("title", "") + " " + (row.get_text(" ", strip=True) if row else "")
        yield {"title": title, "url": link, "source": "中国能建电子采购平台",
               "notice_type": kind, "published_at": normalized_date(date_text)}
