"""
采招网爬虫
网站：https://www.bidcenter.com.cn/
"""
from typing import List, Dict, Any
from urllib.parse import urljoin
from .base import BaseCrawler, BidInfo


class BidcenterCrawler(BaseCrawler):
    """采招网爬虫"""
    
    name = "bidcenter"
    base_url = "https://www.bidcenter.com.cn"
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.search_keywords = config.get('search_keywords', ['无人机', '光伏'])
    
    def get_list_urls(self) -> List[str]:
        urls = []
        for keyword in self.search_keywords:
            url = f"https://www.bidcenter.com.cn/newssearch-1-{keyword}-1.html"
            urls.append(url)
        return urls
    
    def parse(self, html: str) -> List[BidInfo]:
        bids = []
        soup = self.parse_html(html)
        
        items = soup.select('ul.news_list li, div.list-item a, table.list tr')
        
        for item in items:
            try:
                title_elem = item.select_one('a') if item.name != 'a' else item
                if not title_elem:
                    continue
                
                title = title_elem.get_text(strip=True)
                if not title or len(title) < 5:
                    continue
                
                url = title_elem.get('href', '')
                if url and not url.startswith('http'):
                    url = urljoin(self.base_url, url)
                
                date_elem = item.select_one('span.date, span.time')
                publish_date = date_elem.get_text(strip=True) if date_elem else ""
                
                bids.append(BidInfo(
                    title=title,
                    url=url,
                    publish_date=publish_date,
                    source="采招网"
                ))
            except Exception as e:
                self.logger.warning(f"Parse error: {e}")
                continue
        
        return bids
