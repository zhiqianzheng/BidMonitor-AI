"""
爬虫基类 - 定义所有爬虫的公共接口和通用功能

优化说明（v1.1.1）：
- 使用指数退避策略进行重试
- 改进日志输出，更易于调试
- 添加更多浏览器特征模拟
"""
import time
import random
import logging
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass

# 导入存储模块的数据类
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database.storage import BidInfo


# User-Agent 池 - 保持最新的浏览器版本
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


class BaseCrawler(ABC):
    """爬虫基类"""
    
    # 子类需要覆盖这些属性
    name: str = "base"
    base_url: str = ""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.timeout = config.get('timeout', 30)
        self.request_delay = config.get('request_delay', 5)
        self.max_retries = config.get('max_retries', 3)
        self.logger = logging.getLogger(f"crawler.{self.name}")
        self.session = requests.Session()
        self.last_status = 'not_started'
        self.last_error = ''
    
    def _get_headers(self) -> Dict[str, str]:
        """获取请求头，随机选择 User-Agent 并添加更多浏览器特征"""
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Cache-Control": "max-age=0",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Sec-Ch-Ua": '"Chromium";v="120", "Not_A Brand";v="24", "Google Chrome";v="120"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
        }
    
    def fetch(self, url: str, params: Optional[Dict] = None, stop_event=None) -> Optional[str]:
        """
        发起 HTTP 请求获取页面内容
        
        Args:
            url: 目标URL
            params: 查询参数
            
        Returns:
            页面HTML内容，失败返回None
        """
        if self.config.get('use_selenium'):
            from .selenium_crawler import SeleniumCrawler
            browser = getattr(self, '_browser', None)
            if browser is None:
                browser = self._browser = SeleniumCrawler(self.config, self.name, url)
            html = browser.fetch(url, stop_event=stop_event)
            self.last_status, self.last_error = browser.last_status, browser.last_error
            return html
        for attempt in range(self.max_retries):
            if stop_event and stop_event.is_set():
                return None
            try:
                self.logger.debug(f"正在请求: {url} (尝试 {attempt + 1}/{self.max_retries})")
                
                response = self.session.get(
                    url,
                    params=params,
                    headers=self._get_headers(),
                    timeout=self.timeout,
                    verify=True,
                    allow_redirects=True
                )
                if response.status_code == 429:
                    self.last_status, self.last_error = 'rate_limited', 'HTTP 429：站点限流，本轮停止请求此页面'
                    self.logger.warning('%s: %s', url, self.last_error)
                    return None
                response.raise_for_status()
                
                # 尝试自动检测编码
                response.encoding = response.apparent_encoding or 'utf-8'
                
                # 添加请求延迟
                delay = self.request_delay + random.uniform(0, 2)
                self.logger.debug(f"请求成功，等待 {delay:.1f} 秒")
                if stop_event:
                    if stop_event.wait(delay):
                        return None
                else:
                    time.sleep(delay)
                
                self.last_status, self.last_error = 'loaded', ''
                return response.text
                
            except requests.exceptions.SSLError as e:
                self.logger.warning(f"SSL错误: {url}, 错误: {e}")
            except requests.exceptions.Timeout as e:
                self.logger.warning(f"请求超时: {url}")
            except requests.exceptions.ConnectionError as e:
                self.logger.warning(f"连接失败: {url}, 可能网站不可访问或需要VPN")
            except requests.exceptions.HTTPError as e:
                status_code = e.response.status_code if e.response is not None else 'N/A'
                self.logger.warning(f"HTTP错误 {status_code}: {url}")
                if status_code in [401, 403]:
                    self.last_status = 'login_required' if status_code == 401 else 'blocked'
                    self.last_error = f'HTTP {status_code}，需要授权或人工确认'
                    self.logger.info(f"该网站可能需要登录或被屏蔽了爬虫")
                    return None  # 不重试
            except requests.RequestException as e:
                self.logger.warning(f"请求失败: {url}, 错误: {e}")
            
            if attempt < self.max_retries - 1:
                # 指数退避: 2, 4, 8... 秒，加上随机抖动
                wait_time = (2 ** (attempt + 1)) + random.uniform(0, 1)
                self.logger.info(f"⏳ 等待 {wait_time:.1f} 秒后第 {attempt + 2} 次重试...")
                if stop_event:
                    if stop_event.wait(wait_time):
                        return None
                else:
                    time.sleep(wait_time)
        
        self.logger.error(f"请求最终失败: {url}")
        self.last_status, self.last_error = 'fetch_failed', f'页面请求失败: {url}'
        return None
    
    def parse_html(self, html: str) -> BeautifulSoup:
        """解析HTML内容"""
        return BeautifulSoup(html, 'lxml')
    
    @abstractmethod
    def parse(self, html: str) -> List[BidInfo]:
        """
        解析页面，提取招标信息
        
        Args:
            html: 页面HTML内容
            
        Returns:
            招标信息列表
        """
        pass
    
    @abstractmethod
    def get_list_urls(self) -> List[str]:
        """
        获取需要爬取的列表页URL
        
        Returns:
            URL列表
        """
        pass
    
    def crawl(self, stop_event=None) -> Optional[List[BidInfo]]:
        """
        执行爬取任务
        
        Args:
            stop_event: 停止事件，用于中断爬取
        
        Returns:
            所有抓取到的招标信息，如果全部失败返回None
        """
        all_bids = []
        seen_urls = set()
        urls = self.get_list_urls()
        failed_count = 0
        
        self.logger.info(f"[{self.name}] Starting crawl, {len(urls)} page(s)")
        
        for url in urls:
            # 检查停止信号
            if stop_event and stop_event.is_set():
                self.logger.info(f"[{self.name}] Crawl interrupted by stop signal")
                break
            
            html = self.fetch(url, stop_event=stop_event)
            if html:
                # 检查是否被反爬虫拦截
                if self._is_blocked(html):
                    self.last_status, self.last_error = 'blocked', '页面要求验证或拒绝访问'
                    self.logger.warning(f"[{self.name}] BLOCKED by anti-crawler at {url}")
                    failed_count += 1
                    continue
                
                try:
                    bids = self.parse(html)
                    for bid in bids:
                        if bid.url not in seen_urls:
                            all_bids.append(bid)
                            seen_urls.add(bid.url)
                    self.logger.info(f"[{self.name}] Got {len(bids)} items from {url}")
                except Exception as e:
                    self.logger.error(f"[{self.name}] Parse failed {url}: {e}")
                    failed_count += 1
            else:
                failed_count += 1
        
        # 如果全部失败，返回None表示该网站可能有问题
        if failed_count == len(urls) and len(urls) > 0:
            self.logger.error(f"[{self.name}] ALL requests failed! Site may be blocking.")
            return None
        
        self.logger.info(f"[{self.name}] Crawl done, got {len(all_bids)} items total")
        if not all_bids:
            self.last_status, self.last_error = 'no_announcements', '未提取到公告，需检查列表入口或页面结构'
            return None
        self.last_status = 'partial' if failed_count else 'ok'
        if failed_count:
            self.last_error = f'{len(urls)}个列表页中有{failed_count}页失败，可能漏采'
        return all_bids
    
    def _is_blocked(self, html: str) -> bool:
        """检查是否被反爬虫拦截"""
        from .listing import page_problem
        return page_problem(html) is not None


class DemoCrawler(BaseCrawler):
    """演示用爬虫（用于测试）"""
    
    name = "demo"
    base_url = "https://example.com"
    
    def get_list_urls(self) -> List[str]:
        return [self.base_url]
    
    def parse(self, html: str) -> List[BidInfo]:
        # 返回空列表，仅用于测试框架
        return []
