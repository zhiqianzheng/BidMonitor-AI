"""
千里马招标网爬虫
网站：https://www.qianlima.com/
"""
from typing import List, Dict, Any
from urllib.parse import urljoin
from .base import BaseCrawler, BidInfo


class QianlimaCrawler(BaseCrawler):
    """千里马招标网爬虫"""
    
    name = "qianlima"
    base_url = "https://www.qianlima.com"
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.search_keywords = config.get('search_keywords', ['无人机', '光伏'])
    
    def get_list_urls(self) -> List[str]:
        urls = []
        for keyword in self.search_keywords:
            url = f"https://www.qianlima.com/zb/search.php?keywords={keyword}&search_type=zhaobiao"
            urls.append(url)
        return urls
    
    def parse(self, html: str) -> List[BidInfo]:
        bids = []
        soup = self.parse_html(html)
        
        items = soup.select('div.searchBody ul li, table.list-table tr, div.result-item')
        
        for item in items:
            try:
                title_elem = item.select_one('a.title, a.name, h3 a, a')
                if not title_elem:
                    continue
                
                title = title_elem.get_text(strip=True)
                if not title or len(title) < 5:
                    continue
                
                url = title_elem.get('href', '')
                if url and not url.startswith('http'):
                    url = urljoin(self.base_url, url)
                
                date_elem = item.select_one('span.date, span.time, div.time')
                publish_date = date_elem.get_text(strip=True) if date_elem else ""
                
                region_elem = item.select_one('span.region, span.area')
                purchaser = region_elem.get_text(strip=True) if region_elem else ""
                
                bids.append(BidInfo(
                    title=title,
                    url=url,
                    publish_date=publish_date,
                    source="千里马招标网",
                    purchaser=purchaser
                ))
            except Exception as e:
                self.logger.warning(f"Parse error: {e}")
                continue
        
        return bids
