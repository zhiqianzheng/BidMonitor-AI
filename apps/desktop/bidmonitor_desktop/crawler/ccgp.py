"""
中国政府采购网爬虫 - 修复版
网站：http://www.ccgp.gov.cn/
"""
import re
from typing import List, Dict, Any
from urllib.parse import urljoin, quote
from .base import BaseCrawler, BidInfo


class CCGPCrawler(BaseCrawler):
    """中国政府采购网爬虫"""
    
    name = "ccgp"
    base_url = "http://www.ccgp.gov.cn"
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.search_keywords = config.get('search_keywords', ['无人机', 'UAV'])
    
    def get_list_urls(self) -> List[str]:
        """使用政府采购网的公告列表页（不使用搜索，避免403）"""
        # 直接访问公告列表，不使用搜索功能
        return [
            "http://www.ccgp.gov.cn/cggg/zygg/",  # 中央公告
            "http://www.ccgp.gov.cn/cggg/dfgg/",  # 地方公告
        ]
    
    def parse(self, html: str) -> List[BidInfo]:
        """解析公告列表页面"""
        bids = []
        soup = self.parse_html(html)
        
        # 查找所有链接
        items = soup.select('ul.vT_z li, div.vT_z_list li, ul.list li')
        if not items:
            items = soup.find_all('a')
        
        for item in items:
            try:
                # 获取链接
                if item.name == 'a':
                    title_elem = item
                else:
                    title_elem = item.select_one('a')
                
                if not title_elem:
                    continue
                
                title = title_elem.get_text(strip=True)
                if not title or len(title) < 10:
                    continue
                
                # 关键字过滤
                title_lower = title.lower()
                keywords_lower = [kw.lower() for kw in self.search_keywords]
                if not any(kw in title_lower for kw in keywords_lower):
                    continue
                
                url = title_elem.get('href', '')
                if url and not url.startswith('http'):
                    url = urljoin(self.base_url, url)
                
                # 查找日期
                date_elem = item.select_one('span.date, span') if item.name != 'a' else None
                publish_date = ""
                if date_elem:
                    publish_date = date_elem.get_text(strip=True)
                
                bids.append(BidInfo(
                    title=title,
                    url=url,
                    publish_date=publish_date,
                    source="中国政府采购网"
                ))
                
            except Exception as e:
                self.logger.warning(f"Parse item error: {e}")
                continue
        
        return bids
