"""Render public announcement pages with Chrome; report access restrictions explicitly."""
import logging
import threading
import time
from typing import List, Optional

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.common.exceptions import TimeoutException, WebDriverException
    from webdriver_manager.chrome import ChromeDriverManager
    SELENIUM_AVAILABLE = True
    IMPORT_ERROR_MSG = None
except ImportError as exc:
    SELENIUM_AVAILABLE = False
    IMPORT_ERROR_MSG = str(exc)

from .base import BidInfo
from .listing import parse_links, page_problem


class SharedBrowserManager:
    """A serial, restartable browser session, separate from the user's Chrome profile."""
    _instance = None
    _driver = None
    _lock = threading.RLock()

    @classmethod
    def get_driver(cls, timeout=30):
        with cls._lock:
            if cls._driver is not None:
                try:
                    cls._driver.execute_script('return 1')
                except Exception:
                    cls.close()
            if cls._driver is None:
                cls._driver = cls._create_driver(timeout)
                cls._instance = bool(cls._driver)
            if cls._driver:
                cls._driver.set_page_load_timeout(timeout)
            return cls._driver

    @classmethod
    def _create_driver(cls, timeout):
        if not SELENIUM_AVAILABLE:
            return None
        options = Options()
        options.add_argument('--headless=new')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option('excludeSwitches', ['enable-automation'])
        options.add_experimental_option('useAutomationExtension', False)
        # Keep renderer process isolation: --single-process made a bad navigation
        # destroy the session used by every subsequent source.
        options.page_load_strategy = 'eager'
        driver = None
        try:
            try:
                driver = webdriver.Chrome(options=options)
            except WebDriverException:
                driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
            # Keep the original browser-mode compatibility behavior, but use the
            # installed Chrome version instead of a hard-coded Chrome 120 UA.
            user_agent = driver.execute_script('return navigator.userAgent').replace('HeadlessChrome/', 'Chrome/')
            driver.execute_cdp_cmd('Network.setUserAgentOverride', {'userAgent': user_agent})
            driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            })
            driver.set_page_load_timeout(timeout)
            return driver
        except Exception as exc:
            logging.error('Chrome启动失败: %s', exc)
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
            return None

    @classmethod
    def close(cls):
        with cls._lock:
            driver, cls._driver, cls._instance = cls._driver, None, None
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass


class SeleniumCrawler:
    def __init__(self, config: dict, name: str, url: str, headless: bool = True):
        self.config, self._name, self.url = config, name, url
        self.timeout = config.get('timeout', 30)
        self.logger = logging.getLogger(f'crawler.selenium.{name}')
        self.driver = None
        self.last_status = 'not_started'
        self.last_error = ''
        self.page_url = url
        self.partial_load = False
        self.rendered_pages = []

    @property
    def name(self):
        return self._name

    def fetch(self, url: str, stop_event=None) -> Optional[str]:
        self.last_status, self.last_error = 'fetching', ''
        if stop_event and stop_event.is_set():
            self.last_status = 'cancelled'
            return None
        with SharedBrowserManager._lock:
            for attempt in range(2):
                try:
                    # Reacquire every time: a previous source may have restarted it.
                    self.driver = SharedBrowserManager.get_driver(self.timeout)
                    if not self.driver:
                        self.last_status, self.last_error = 'browser_unavailable', 'Chrome或驱动启动失败'
                        return None
                    self.partial_load = False
                    try:
                        self.driver.get(url)
                    except TimeoutException:
                        self.partial_load = True
                        self.driver.execute_script('window.stop()')
                    started = time.monotonic()
                    from urllib.parse import urlsplit
                    page = urlsplit(url)
                    expected_selector = 'a[href*="business/detail.html?id="]' if page.hostname == 'www.ebidding.com' and page.path == '/e-portal/business.html' else ''
                    deadline = started + self.config.get('render_wait', 18 if expected_selector else 8)
                    previous, stable = None, 0
                    content_ready = not expected_selector
                    while time.monotonic() < deadline:
                        if stop_event and stop_event.wait(0.5):
                            self.last_status = 'cancelled'
                            return None
                        if not stop_event:
                            time.sleep(0.5)
                        signature = self.driver.execute_script('return [document.readyState, document.querySelectorAll("a[href]").length, document.body ? document.body.innerText.length : 0]')
                        if signature == previous and signature[1] > 0:
                            stable += 1
                        else:
                            stable = 0
                        previous = signature
                        content_ready = not expected_selector or bool(self.driver.find_elements('css selector', expected_selector))
                        if stable >= 4 and content_ready and time.monotonic() - started >= 4.5:
                            break
                    if not content_ready:
                        self.partial_load = True
                        self.last_error = '等待动态公告列表超时，未确认公告列表加载完成'
                    self.page_url = self.driver.current_url
                    html = self.driver.page_source
                    problem = page_problem(html, self.page_url)
                    if problem:
                        self.last_status, self.last_error = problem
                        self.logger.warning('%s: %s (%s)', self.name, self.last_error, url)
                        return None
                    self.rendered_pages = [(self.page_url, html)]
                    # Announcements may be rendered inside public same-site frames
                    # (e.g. Huadian). page_source alone only contains the outer page.
                    from urllib.parse import urlsplit
                    frames = self.driver.find_elements('css selector', 'iframe[src], frame[src]')
                    for frame in frames[:10]:
                        src = frame.get_attribute('src') or ''
                        frame_host = urlsplit(src).hostname
                        allowed_host = frame_host == urlsplit(self.page_url).hostname or (urlsplit(self.page_url).hostname == 'www.neep.shop' and frame_host == 'gd-prod.cn-beijing.oss.aliyuncs.com')
                        if not src or not allowed_host or any(s in src.lower() for s in ['login', 'about:blank']):
                            continue
                        try:
                            self.driver.switch_to.frame(frame)
                            frame_html = self.driver.page_source
                            frame_url = self.driver.execute_script('return document.URL')
                            if not page_problem(frame_html, frame_url):
                                self.rendered_pages.append((frame_url, frame_html))
                        except WebDriverException as exc:
                            self.logger.warning('公告子页面读取失败 %s: %s', src, str(exc)[:120])
                            self.partial_load = True
                        finally:
                            self.driver.switch_to.default_content()
                    self.last_status = 'partial_load' if self.partial_load else 'loaded'
                    return html
                except Exception as exc:
                    self.last_status, self.last_error = 'browser_error', str(exc).split('Stacktrace:')[0].strip()[:400]
                    self.logger.warning('%s 浏览器访问失败: %s', url, self.last_error)
                    crash = any(s in str(exc).lower() for s in ['invalid session', 'tab crashed', 'disconnected', 'no such window', 'chrome not reachable'])
                    if not crash or attempt:
                        return None
                    SharedBrowserManager.close()
                    self.driver = None
            return None

    def crawl(self, stop_event=None) -> Optional[List[BidInfo]]:
        html = self.fetch(self.url, stop_event=stop_event)
        if html is None:
            return None
        bids = self.parse(html)
        from .script_links import resolve_titles
        with SharedBrowserManager._lock:
            extra, unresolved = resolve_titles(self.driver, self.page_url, self.name, stop_event, self.config.get('max_dynamic_links', 80))
        from urllib.parse import urlsplit
        if urlsplit(self.page_url).hostname == 'etp.faw.cn':
            import re
            unresolved += len(set(re.findall(r"bgGgDetail\('([\w-]+)','7'\)", html)))
        seen = {b.url for b in bids}
        bids.extend(b for b in extra if b.url not in seen)
        if unresolved:
            self.last_error = f'{unresolved}条可见标题未能解析到独立详情链接，可能漏采'
        if not bids:
            self.last_status = 'no_announcements'
            self.last_error = self.last_error or '页面已打开，但未提取到公告链接；需检查列表入口、登录限制或页面结构'
            self.logger.warning('%s: %s', self.name, self.last_error)
            return None
        self.last_status = 'partial' if unresolved else ('partial_load' if self.partial_load else 'ok')
        return bids

    def parse(self, html):
        pages = self.rendered_pages if self.rendered_pages and self.rendered_pages[0][1] == html else [(self.page_url, html)]
        bids, seen = [], set()
        for url, page in pages:
            for bid in parse_links(page, url, self.name, generic=self.config.get('custom_site', False)):
                if bid.url not in seen:
                    seen.add(bid.url)
                    bids.append(bid)
        return bids

    def close(self):
        # Shared session belongs to the manager, not this crawler.
        self.driver = None
