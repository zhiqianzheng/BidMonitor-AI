"""
索比光伏网爬虫 - 修复版
网站：https://www.solarbe.com/
"""
from typing import List, Dict, Any
from urllib.parse import urljoin
from .base import BaseCrawler, BidInfo


class SolarbeCrawler(BaseCrawler):
    """索比光伏网爬虫"""
    
    name = "solarbe"
    base_url = "https://www.solarbe.com"
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.search_keywords = config.get('search_keywords', ['光伏', '无人机', '招标'])
    
    def get_list_urls(self) -> List[str]:
        """索比光伏网资讯页面"""
        return [
            "https://news.solarbe.com/",  # 新闻首页
            "https://www.solarbe.com/news/",  # 资讯
        ]
    
    def parse(self, html: str) -> List[BidInfo]:
        """解析页面"""
        bids = []
        soup = self.parse_html(html)
        
        # 查找所有链接
        items = soup.select('ul li a, div.news-item a, h3 a, h4 a, a.title')
        if not items:
            items = soup.find_all('a')
        
        for item in items:
            try:
                title = item.get_text(strip=True)
                if not title or len(title) < 10:
                    continue
                
                # 关键字过滤 - 包含招标、中标关键字
                title_lower = title.lower()
                bid_keywords = ['招标', '中标', '采购', '光伏', '无人机', '巡检']
                if not any(kw in title_lower for kw in bid_keywords):
                    continue
                
                url = item.get('href', '')
                if url and not url.startswith('http'):
                    url = urljoin(self.base_url, url)
                
                bids.append(BidInfo(
                    title=title,
                    url=url,
                    publish_date="",
                    source="索比光伏网"
                ))
                
            except Exception as e:
                self.logger.warning(f"Parse error: {e}")
        
        return bids
