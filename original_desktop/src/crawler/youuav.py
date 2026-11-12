"""
中国无人机网爬虫 - 修复版2
网站：https://www.youuav.com/
"""
from typing import List, Dict, Any
from urllib.parse import urljoin
from .base import BaseCrawler, BidInfo


class YouuavCrawler(BaseCrawler):
    """中国无人机网爬虫"""
    
    name = "youuav"
    base_url = "https://www.youuav.com"
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.search_keywords = config.get('search_keywords', ['无人机', '航拍', 'UAV', '光伏'])
    
    def get_list_urls(self) -> List[str]:
        """中国无人机网 - 只使用首页"""
        return [
            "https://www.youuav.com/",
        ]
    
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
                
                # 无人机网是专业网站，包含招标、采购、项目关键字即可
                title_lower = title.lower()
                bid_keywords = ['招标', '中标', '采购', '项目', '无人机', '航拍', '巡检', '光伏', '风电']
                
                has_keyword = any(kw in title_lower for kw in bid_keywords)
                if not has_keyword:
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
                    source="中国无人机网"
                ))
                
            except Exception as e:
                self.logger.warning(f"Parse error: {e}")
        
        return bids
