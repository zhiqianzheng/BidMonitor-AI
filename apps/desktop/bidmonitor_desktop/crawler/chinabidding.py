"""
中国采购与招标网爬虫 - 修复版2
网站：https://www.chinabidding.cn/
"""
from typing import List, Dict, Any
from urllib.parse import urljoin
from .base import BaseCrawler, BidInfo


class ChinaBiddingCrawler(BaseCrawler):
    """中国采购与招标网爬虫"""
    
    name = "chinabidding"
    base_url = "https://www.chinabidding.cn"
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.search_keywords = config.get('search_keywords', ['无人机', '光伏'])
    
    def get_list_urls(self) -> List[str]:
        """使用正确的列表页URL"""
        return [self.base_url + '/']
    
    def parse(self, html: str) -> List[BidInfo]:
        """解析页面"""
        bids = []
        soup = self.parse_html(html)
        
        # 查找所有链接
        items = soup.find_all('a')
        
        for item in items:
            try:
                title = item.get_text(strip=True)
                if not title or len(title) < 10:
                    continue
                
                # 关键字过滤
                title_lower = title.lower()
                keywords_lower = [kw.lower() for kw in self.search_keywords]
                bid_keywords = ['招标', '中标', '采购', '公告']
                
                # 必须包含业务关键字或搜索关键字
                has_bid_keyword = any(kw in title_lower for kw in bid_keywords)
                has_search_keyword = any(kw in title_lower for kw in keywords_lower)
                
                if not (has_bid_keyword or has_search_keyword):
                    continue
                
                url = item.get('href', '')
                if not url or url.startswith('javascript'):
                    continue
                if not url.startswith('http'):
                    url = urljoin(self.base_url, url)
                
                bids.append(BidInfo(
                    title=title,
                    url=url,
                    publish_date="",
                    source="中国采购与招标网"
                ))
                
            except Exception as e:
                self.logger.warning(f"Parse error: {e}")
        
        return bids
