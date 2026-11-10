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
        self.search_keywords = config.get('search_keywords', [])
    
    def get_list_urls(self) -> List[str]:
        """使用政府采购网的公告列表页（不使用搜索，避免403）"""
        # 直接访问公告列表，不使用搜索功能
        return [
            "https://www.ccgp.gov.cn/cggg/zygg/index.htm",  # 中央公告
            "https://www.ccgp.gov.cn/cggg/dfgg/index.htm",  # 地方公告
        ]
    
    def parse(self, html: str) -> List[BidInfo]:
        from .government import parse_announcements
        soup = self.parse_html(html)
        section = 'zygg' if soup.title and '中央公告' in soup.title.get_text() else 'dfgg'
        page = f'https://www.ccgp.gov.cn/cggg/{section}/index.htm'
        return [BidInfo(title=row['title'], url=row['url'], publish_date=row['published_at'],
                        source=row['source'], purchaser=row['purchaser'])
                for row in parse_announcements(html, page)]
