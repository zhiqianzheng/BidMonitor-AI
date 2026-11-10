"""
自定义通用爬虫 - 用于用户添加的网站
"""
from typing import List
from urllib.parse import urljoin, urlsplit
from datetime import datetime
from .base import BaseCrawler, BidInfo

class CustomCrawler(BaseCrawler):
    """自定义通用爬虫"""
    
    def __init__(self, config: dict, name: str, url: str):
        self._name = name  # 必须在 super().__init__() 之前设置，因为父类会访问 self.name
        self.url = url
        super().__init__(config)
        
    @property
    def name(self) -> str:
        return self._name
        
    def get_list_urls(self) -> List[str]:
        return [self.url]
        
    def parse(self, html: str) -> List[BidInfo]:
        soup = self.parse_html(html)
        bids = []
        
        # 提取所有链接
        seen_urls = set()
        
        for a in soup.find_all('a', href=True):
            text = a.get_text(strip=True)
            href = a['href']
            
            # 简单过滤无效链接
            if not text or len(text) < 4: # 标题太短通常不是招标信息
                continue
            if href.lower().startswith(('javascript:', '#', 'mailto:', 'tel:')):
                continue
                
            # 补全URL
            full_url = urljoin(self.url, href)
            if urlsplit(full_url).scheme.lower() not in ('http', 'https'):
                continue
            
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            
            # 创建BidInfo
            # 注意：这里我们返回页面上所有看起来像标题的链接
            # 真正的关键字过滤会在 MonitorCore 中进行
            bids.append(BidInfo(
                title=text,
                url=full_url,
                publish_date="",  # 未提取到发布日期，不能用抓取日期替代
                source=self.name
            ))
            
        return bids
