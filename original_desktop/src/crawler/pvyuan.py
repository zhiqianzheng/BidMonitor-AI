"""
光伏园网爬虫 - 修复版2
网站：https://www.pvyuan.com/
"""
from typing import List, Dict, Any
from urllib.parse import urljoin
from .base import BaseCrawler, BidInfo


class PvyuanCrawler(BaseCrawler):
    """光伏园网爬虫"""
    
    name = "pvyuan"
    base_url = "https://www.pvyuan.com"
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.search_keywords = config.get('search_keywords', ['光伏', '风电', '无人机'])
    
    def get_list_urls(self) -> List[str]:
        """光伏园网 - 只使用首页"""
        return [
            "https://www.pvyuan.com/",
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
                
                # 关键字过滤 - 必须包含招标相关或业务相关词汇
                title_lower = title.lower()
                keywords_lower = [kw.lower() for kw in self.search_keywords]
                bid_keywords = ['招标', '中标', '采购', '光伏', '风电', '无人机', '巡检']
                
                has_keyword = any(kw in title_lower for kw in bid_keywords + keywords_lower)
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
                    source="光伏园网"
                ))
                
            except Exception as e:
                self.logger.warning(f"Parse error: {e}")
        
        return bids
