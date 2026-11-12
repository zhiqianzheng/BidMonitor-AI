"""
电力能源招标网爬虫
网站：http://www.dlnyzb.com/
"""
from typing import List, Dict, Any
from urllib.parse import urljoin
from .base import BaseCrawler, BidInfo


class DlnyzbCrawler(BaseCrawler):
    """电力能源招标网爬虫"""
    
    name = "dlnyzb"
    base_url = "http://www.dlnyzb.com"
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.search_keywords = config.get('search_keywords', ['光伏', '风电', '无人机'])
    
    def get_list_urls(self) -> List[str]:
        urls = []
        for keyword in self.search_keywords:
            url = f"http://www.dlnyzb.com/search?keyword={keyword}"
            urls.append(url)
        return urls
    
    def parse(self, html: str) -> List[BidInfo]:
        bids = []
        soup = self.parse_html(html)
        
        items = soup.select('ul.list li, div.list-item, table tr')
        
        for item in items:
            try:
                title_elem = item.select_one('a')
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
                    source="电力能源招标网"
                ))
            except Exception as e:
                self.logger.warning(f"Parse error: {e}")
        
        return bids
