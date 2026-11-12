"""
全国公共资源交易平台爬虫
网站：http://www.ggzy.gov.cn/
"""
from typing import List, Dict, Any
from urllib.parse import urljoin
from .base import BaseCrawler, BidInfo


class GGZYCrawler(BaseCrawler):
    """全国公共资源交易平台爬虫"""
    
    name = "ggzy"
    base_url = "http://www.ggzy.gov.cn"
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.search_keywords = config.get('search_keywords', ['无人机', '光伏', '风电'])
    
    def get_list_urls(self) -> List[str]:
        """生成搜索URL列表"""
        urls = []
        for keyword in self.search_keywords:
            # 公共资源交易平台搜索接口
            url = f"http://deal.ggzy.gov.cn/ds/deal/dealList_find.jsp?TIMEBEGIN_SHOW=&TIMEEND_SHOW=&TIMEBEGIN=&TIMEEND=&SOURCE_TYPE=&DEAL_TIME=02&DEAL_CLASSIFY=01&DEAL_STAGE=&DEAL_PROVINCE=&DEAL_CITY=&DEAL_PLATFORM=&BID_PLATFORM=&DEAL_TRADE=&isShowAll=1&KEYWORD={keyword}&TIME=6"
            urls.append(url)
        return urls
    
    def parse(self, html: str) -> List[BidInfo]:
        """解析搜索结果"""
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
                
                date_elem = item.select_one('span.date, td.time, span.time')
                publish_date = date_elem.get_text(strip=True) if date_elem else ""
                
                bids.append(BidInfo(
                    title=title,
                    url=url,
                    publish_date=publish_date,
                    source="全国公共资源交易平台"
                ))
            except Exception as e:
                self.logger.warning(f"Parse error: {e}")
                continue
        
        return bids
