"""
Selenium浏览器爬虫 - 使用真实浏览器绕过反爬虫机制
"""
import time
import logging
from typing import List, Optional
from datetime import datetime
from urllib.parse import urljoin, urlsplit

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
    SELENIUM_AVAILABLE = True
    IMPORT_ERROR_MSG = None
except ImportError as e:
    SELENIUM_AVAILABLE = False
    IMPORT_ERROR_MSG = str(e)
except Exception as e:
    SELENIUM_AVAILABLE = False
    IMPORT_ERROR_MSG = f"Unexpected error: {str(e)}"

from .base import BidInfo


class SeleniumCrawler:
    """Selenium浏览器爬虫 - 使用真实Chrome浏览器"""
    
    def __init__(self, config: dict, name: str, url: str, headless: bool = True):
        """
        初始化Selenium爬虫
        
        Args:
            config: 爬虫配置
            name: 网站名称
            url: 网站URL
            headless: 是否无头模式（不显示浏览器窗口）
        """
        self.config = config
        self._name = name
        self.url = url
        self.headless = headless
        self.timeout = config.get('timeout', 30)
        self.logger = logging.getLogger(f"crawler.selenium.{name}")
        self.driver = None
        
    @property
    def name(self) -> str:
        return self._name
    
    def _init_driver(self):
        """初始化Chrome浏览器"""
        if not SELENIUM_AVAILABLE:
            self.logger.error("Selenium未安装，请运行: pip install selenium webdriver-manager")
            return None
        
        try:
            options = Options()
            
            if self.headless:
                options.add_argument('--headless=new')
            
            # 防检测设置
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_argument('--disable-extensions')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--window-size=1920,1080')
            options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
            
            # 禁用自动化标志
            options.add_experimental_option('excludeSwitches', ['enable-automation'])
            options.add_experimental_option('useAutomationExtension', False)
            
            driver = None
            
            # 方法1: 尝试使用系统已安装的chromedriver
            try:
                driver = webdriver.Chrome(options=options)
                self.logger.info("使用系统chromedriver初始化成功")
            except Exception as e1:
                self.logger.warning(f"系统chromedriver不可用: {e1}")
                
                # 方法2: 尝试使用webdriver_manager自动下载
                try:
                    service = Service(ChromeDriverManager().install())
                    driver = webdriver.Chrome(service=service, options=options)
                    self.logger.info("使用webdriver_manager初始化成功")
                except Exception as e2:
                    self.logger.error(f"webdriver_manager也失败: {e2}")
                    return None
            
            if driver:
                # 执行CDP命令隐藏webdriver特征
                driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                    'source': '''
                        Object.defineProperty(navigator, 'webdriver', {
                            get: () => undefined
                        })
                    '''
                })
                
                driver.set_page_load_timeout(self.timeout)
            
            return driver
            
        except Exception as e:
            self.logger.error(f"初始化Chrome失败: {e}")
            return None
    
    def fetch(self, url: str) -> Optional[str]:
        """使用浏览器获取页面内容"""
        # 优先使用共享浏览器以节省资源
        if not self.driver:
            self.driver = SharedBrowserManager.get_driver(self.timeout)
            if not self.driver:
                # 共享浏览器不可用时使用独立浏览器
                self.driver = self._init_driver()
            if not self.driver:
                return None
        
        try:
            self.logger.info(f"[Selenium] 正在访问: {url}")
            self.driver.get(url)
            
            # 等待页面加载
            time.sleep(3)
            
            # 等待body加载完成
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # 返回页面源码
            return self.driver.page_source
            
        except Exception as e:
            self.logger.error(f"[Selenium] 访问失败: {url}, 错误: {e}")
            return None
    
    def crawl(self, stop_event=None) -> Optional[List[BidInfo]]:
        """爬取网站
        
        Args:
            stop_event: 停止事件，用于中断爬取
        """
        # 检查停止信号
        if stop_event and stop_event.is_set():
            self.logger.info(f"[Selenium] {self.name}: 检测到停止信号，跳过爬取")
            return []
        
        self.logger.info(f"🌐 [Selenium模式] 正在使用浏览器爬取: {self.name}")
        
        html = self.fetch(self.url)
        if not html:
            return None
        
        return self.parse(html)
    
    def parse(self, html: str) -> List[BidInfo]:
        """解析页面内容"""
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(html, 'lxml')
        bids = []
        seen_urls = set()
        
        for a in soup.find_all('a', href=True):
            text = a.get_text(strip=True)
            href = a['href']
            
            # 过滤无效链接
            if not text or len(text) < 4:
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
            
            bids.append(BidInfo(
                title=text,
                url=full_url,
                publish_date="",
                source=self.name
            ))
        
        self.logger.info(f"[Selenium] {self.name}: 找到 {len(bids)} 个链接")
        return bids
    
    def close(self):
        """关闭浏览器（使用共享浏览器时不立即关闭）"""
        # 如果使用共享浏览器，不在这里关闭
        if self.driver and not SharedBrowserManager._instance:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None
    
    def __del__(self):
        # 使用共享浏览器时不在析构时关闭
        pass


class SharedBrowserManager:
    """共享浏览器管理器 - 所有爬虫复用同一个Chrome实例"""
    _instance = None
    _driver = None
    _lock = None
    
    @classmethod
    def get_driver(cls, timeout: int = 30):
        """获取共享的浏览器实例"""
        import threading
        
        if cls._lock is None:
            cls._lock = threading.Lock()
        
        with cls._lock:
            if cls._driver is None:
                cls._driver = cls._create_driver(timeout)
                cls._instance = True
            return cls._driver
    
    @classmethod
    def _create_driver(cls, timeout: int):
        """创建浏览器实例"""
        if not SELENIUM_AVAILABLE:
            return None
        
        try:
            options = Options()
            options.add_argument('--headless=new')
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_argument('--disable-extensions')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--window-size=1920,1080')
            options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
            # 限制内存使用
            options.add_argument('--memory-pressure-off')
            options.add_argument('--disable-background-networking')
            options.add_argument('--disable-default-apps')
            options.add_argument('--disable-sync')
            options.add_argument('--single-process')  # 单进程模式减少内存
            
            options.add_experimental_option('excludeSwitches', ['enable-automation'])
            options.add_experimental_option('useAutomationExtension', False)
            
            # 尝试使用系统chromedriver
            try:
                driver = webdriver.Chrome(options=options)
                logging.info("共享浏览器: 使用系统chromedriver初始化成功")
            except Exception as e1:
                try:
                    service = Service(ChromeDriverManager().install())
                    driver = webdriver.Chrome(service=service, options=options)
                    logging.info("共享浏览器: 使用webdriver_manager初始化成功")
                except Exception as e2:
                    logging.error(f"共享浏览器初始化失败: {e2}")
                    return None
            
            driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    })
                '''
            })
            driver.set_page_load_timeout(timeout)
            return driver
            
        except Exception as e:
            logging.error(f"共享浏览器创建失败: {e}")
            return None
    
    @classmethod
    def close(cls):
        """关闭共享浏览器"""
        if cls._driver:
            try:
                cls._driver.quit()
            except:
                pass
            cls._driver = None
            cls._instance = None
