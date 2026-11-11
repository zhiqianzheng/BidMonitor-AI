"""
监控核心模块 - 整合爬虫、匹配、通知功能
"""
import logging
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from .database.storage import Storage, BidInfo
    from .matcher.keyword import KeywordMatcher
    from .notifier.email import EmailNotifier
    from .notifier.sms import SMSNotifier
    
    from .crawler.ccgp import CCGPCrawler
    from .crawler.chinabidding import ChinaBiddingCrawler
    from .crawler.ebnew import EbnewCrawler
    from .crawler.plap import PLAPCrawler
    from .crawler.ggzy import GGZYCrawler
    from .crawler.bidcenter import BidcenterCrawler
    from .crawler.qianlima import QianlimaCrawler
    from .crawler.chinatender import ChinaTenderCrawler
    from .crawler.solarbe import SolarbeCrawler
    from .crawler.pvyuan import PvyuanCrawler
    from .crawler.dlnyzb import DlnyzbCrawler
    from .crawler.youuav import YouuavCrawler
except ImportError:
    from database.storage import Storage, BidInfo
    from matcher.keyword import KeywordMatcher
    from notifier.email import EmailNotifier
    from notifier.sms import SMSNotifier
    
    from crawler.ccgp import CCGPCrawler
    from crawler.chinabidding import ChinaBiddingCrawler
    from crawler.ebnew import EbnewCrawler
    from crawler.plap import PLAPCrawler
    from crawler.ggzy import GGZYCrawler
    from crawler.bidcenter import BidcenterCrawler
    from crawler.qianlima import QianlimaCrawler
    from crawler.chinatender import ChinaTenderCrawler
    from crawler.solarbe import SolarbeCrawler
    from crawler.pvyuan import PvyuanCrawler
    from crawler.dlnyzb import DlnyzbCrawler
    from crawler.youuav import YouuavCrawler

# 爬虫注册表
def get_all_crawlers():
    """获取所有爬虫类"""
    return {
        'chinabidding': ChinaBiddingCrawler,
        'ccgp': CCGPCrawler,
    }

# 默认内置网站配置 (用于通用爬虫)
def get_default_sites():
    """获取默认的内置网站列表"""
    return {
        'ccgp': {'name': '中国政府采购网', 'url': 'https://www.ccgp.gov.cn/cggg/dfgg/index.htm'},
        'chinabidding': {'name': '中国采购与招标网', 'url': 'http://www.chinabidding.cn/'},
        'dlzb': {'name': '中国电力招标网', 'url': 'http://www.dlzb.com/'},
        'chinabiddingcc': {'name': '中国采购招标网', 'url': 'http://www.chinabidding.cc/'},
        'gdtzb': {'name': '国电投招标网', 'url': 'http://www.gdtzb.com'},
        'cpeinet': {'name': '中国电力设备信息网', 'url': 'http://www.cpeinet.com.cn/'},
        'espic': {'name': '电能e招采', 'url': 'https://ebid.espic.com.cn/'},
        'chng': {'name': '华能集团电子商务平台', 'url': 'http://ec.chng.com.cn/ecmall/'},
        'powerchina': {'name': '中国电建采购电子商务平台', 'url': 'http://ec.powerchina.cn'},
        'powerchina_bid': {'name': '中国电建采购招标数智化平台', 'url': 'https://bid.powerchina.cn/bidweb/'},
        'powerchina_ec': {'name': '中国电建设备物资集中采购平台', 'url': 'https://ec.powerchina.cn/'},
        'powerchina_scm': {'name': '中国电建供应链云服务平台', 'url': 'https://scm.powerchina.cn/'},
        'powerchina_idx': {'name': '中国电建承包商管理系统', 'url': 'http://bid.powerchina.cn/index'},
        'powerchina_nw': {'name': '中国电建西北勘测设计研究院', 'url': 'http://ec1.powerchina.cn'},
        'ceec': {'name': '中国能建电子采购平台', 'url': 'https://ec.ceec.net.cn/'},
        'chdtp': {'name': '中国华电电子商务平台', 'url': 'http://www.chdtp.com/'},
        'chec_gys': {'name': '中国华电科工供应商填报系统', 'url': 'http://gys.chec.com.cn:90'},
        'chinazbcg': {'name': '中国招投标信息网', 'url': 'http://www.chinazbcg.com'},
        'cdt': {'name': '中国大唐电子商务平台', 'url': 'http://www.cdt-ec.com/'},
        'ebidding': {'name': '国义招标', 'url': 'http://www.ebidding.com/portal/'},
        'neep': {'name': '国家能源e购', 'url': 'https://www.neep.shop/'},
        'ceic': {'name': '国家能源集团生态协作平台', 'url': 'https://cooperation.ceic.com/'},
        'sgcc': {'name': '国家电网电子商务平台', 'url': 'https://ecp.sgcc.com.cn/'},
        'cecep': {'name': '中国节能环保电子采购平台', 'url': 'http://www.ebidding.cecep.cn/'},
        'gdg': {'name': '广州发展集团电子采购平台', 'url': 'https://eps.gdg.com.cn/'},
        'crpower': {'name': '华润电力', 'url': 'https://b2b.crpower.com.cn'},
        'crc': {'name': '华润集团守正电子招标采购平台', 'url': 'https://szecp.crc.com.cn/'},
        'longi': {'name': '隆基股份SRM系统', 'url': 'https://srm.longi.com:6080'},
        'cgnpc': {'name': '中广核电子商务平台', 'url': 'https://ecp.cgnpc.com.cn'},
        'dongfang': {'name': '东方电气', 'url': 'http://nsrm.dongfang.com/'},
        'zjycgzx': {'name': '浙江云采购中心', 'url': 'https://www.zjycgzx.com'},
        'ctg': {'name': '中国三峡电子采购平台', 'url': 'https://eps.ctg.com.cn/'},
        'sdicc': {'name': '国投集团电子采购平台', 'url': 'https://www.sdicc.com.cn/'},
        'csg': {'name': '中国南方电网供应链服务平台', 'url': 'http://www.bidding.csg.cn/'},
        'sgccetp': {'name': '国网电子商务平台电工交易专区', 'url': 'https://sgccetp.com.cn/'},
        'powerbeijing': {'name': '北京京能电子商务平台', 'url': 'http://www.powerbeijing-ec.com'},
        'ccccltd': {'name': '中交集团供应链管理系统', 'url': 'http://ec.ccccltd.cn/'},
        'jchc': {'name': '江苏交通控股', 'url': 'https://zbcg.jchc.cn/portal'},
        'minmetals': {'name': '中国五矿集团供应链管理平台', 'url': 'https://ec.minmetals.com.cn/'},
        'sunwoda': {'name': '欣旺达SRM', 'url': 'https://srm.sunwoda.com/'},
        'cnbm': {'name': '中国建材集团采购平台', 'url': 'https://c.cnbm.com.cn/'},
        'hghn': {'name': '华光环能数字化采购管理平台', 'url': 'https://hgcg.hghngroup.com/'},
        'xcmg': {'name': '徐工全球数字化供应链系统平台', 'url': 'http://xdsc.xcmg.com:8985/'},
        'xinecai': {'name': '安天智采', 'url': 'http://www.xinecai.com'},
        'ariba': {'name': '远景SAP系统', 'url': 'https://service.ariba.com/'},
        'faw': {'name': '中国一汽电子招标采购交易平台', 'url': 'https://srm.etp.faw.cn/staging'},
    }


class MonitorCore:
    """监控核心类"""
    
    def __init__(self, 
                 keywords: List[str],
                 exclude_keywords: List[str] = None,
                 must_contain_keywords: List[str] = None,
                 notify_method: str = "email",
                 email: str = "",
                 phone: str = "",
                 email_config: Dict[str, Any] = None,
                 sms_config: Dict[str, Any] = None,
                 log_callback: Callable[[str], None] = None,
                 ai_config: Dict[str, Any] = None):
        """
        初始化监控核心
        
        Args:
            keywords: 搜索关键字列表 (OR组 - 行业词)
            exclude_keywords: 排除关键字列表
            must_contain_keywords: 必须包含关键字列表 (AND组 - 产品词)
            notify_method: 通知方式 (email/sms/both)
            email: 邮箱地址
            phone: 手机号
            email_config: 邮件配置
            sms_config: 短信配置
            log_callback: 日志回调函数
        """
        self.keywords = keywords
        self.exclude_keywords = exclude_keywords or []
        self.must_contain_keywords = must_contain_keywords or []
        self.notify_method = notify_method
        self.email = email
        self.phone = phone
        self.log_callback = log_callback or (lambda x: None)
        
        # 初始化组件
        self.storage = Storage()
        self.matcher = KeywordMatcher(keywords, exclude_keywords, must_contain_keywords, match_all=not keywords)
        
        # 加载配置文件
        self.config = self._load_config()
        
        # 初始化通知器
        if email_config:
            self.email_notifier = EmailNotifier(email_config)
        elif self.config.get('email'):
            email_cfg = self.config['email'].copy()
            if email:
                email_cfg['receiver'] = email
            self.email_notifier = EmailNotifier(email_cfg)
        else:
            self.email_notifier = None
        
        if sms_config:
            self.sms_notifier = SMSNotifier(sms_config)
        elif self.config.get('sms'):
            self.sms_notifier = SMSNotifier(self.config['sms'])
        else:
            self.sms_notifier = None
        
        # 初始化 AI 守卫
        self.ai_guard = None
        if ai_config and ai_config.get('enable'):
            try:
                from ai_guard import AIGuard
                self.ai_guard = AIGuard(ai_config, log_callback=self.log)
                self.log("✅ [AI] 智能过滤已启用")
            except Exception as e:
                self.log(f"[WARN] AI初始化失败: {e}")
        
        # 初始化爬虫
        self.crawlers = self._init_crawlers()
    
    def clear_data(self):
        """清空所有历史数据"""
        self.storage.clear_all()
        self.log("All history data cleared.")

    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        import yaml
        config_paths = [
            'config/config.yaml',
            '../config/config.yaml',
            os.path.join(os.path.dirname(__file__), '..', 'config', 'config.yaml')
        ]
        
        for path in config_paths:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    return yaml.safe_load(f) or {}
        
        return {}
    
    def _init_crawlers(self) -> List:
        """初始化所有爬虫"""
        crawlers = []
        crawler_config = self.config.get('crawler', {})
        crawler_config['search_keywords'] = self.keywords[:3]
        
        # 获取启用的网站列表
        enabled = crawler_config.get('enabled_sites', [])
        
        # 1. 加载内置爬虫类
        crawler_classes = get_all_crawlers()
        
        for name in enabled:
            if name in crawler_classes:
                try:
                    crawler = crawler_classes[name](crawler_config)
                    crawlers.append(crawler)
                    self.log(f"[OK] Loaded crawler: {name}")
                except Exception as e:
                    self.log(f"[WARN] Failed to load crawler {name}: {e}")
        
        # 判断是否使用Selenium模式
        use_selenium = crawler_config.get('use_selenium', False)
        self.log(f"[DEBUG] Selenium模式: {'启用' if use_selenium else '禁用'}")
        
        # 2. 加载默认内置网站
        if use_selenium:
            try:
                from crawler.selenium_crawler import SeleniumCrawler, SELENIUM_AVAILABLE, IMPORT_ERROR_MSG
                self.log(f"[DEBUG] Selenium可用: {SELENIUM_AVAILABLE}")
                if not SELENIUM_AVAILABLE:
                    self.log(f"[WARN] Selenium模块导入失败: {IMPORT_ERROR_MSG}，回退到普通模式")
                    use_selenium = False
            except ImportError as e:
                self.log(f"[WARN] Selenium模块文件加载失败: {e}，回退到普通模式")
                use_selenium = False
        
        from crawler.custom import CustomCrawler
        default_sites = get_default_sites()
        
        for key in enabled:
            if key in default_sites and key not in crawler_classes:
                site = default_sites[key]
                try:
                    if use_selenium:
                        crawler = SeleniumCrawler(crawler_config, site['name'], site['url'], headless=True)
                        self.log(f"[OK] Loaded site (Selenium): {site['name']}")
                    else:
                        crawler = CustomCrawler(crawler_config, site['name'], site['url'])
                        self.log(f"[OK] Loaded site: {site['name']}")
                    crawlers.append(crawler)
                except Exception as e:
                    self.log(f"[WARN] Failed to load site {site['name']}: {e}")
        
        # 3. 加载用户自定义爬虫
        custom_sites = self.config.get('custom_sites', [])
        for site in custom_sites:
            try:
                name = site.get('name', 'Unknown')
                url = site.get('url', '')
                if name and url:
                    if use_selenium:
                        crawler = SeleniumCrawler(crawler_config, name, url, headless=True)
                        self.log(f"[OK] Loaded custom (Selenium): {name}")
                    else:
                        crawler = CustomCrawler(crawler_config, name, url)
                        self.log(f"[OK] Loaded custom crawler: {name}")
                    crawlers.append(crawler)
            except Exception as e:
                self.log(f"[WARN] Failed to load custom crawler {site.get('name')}: {e}")
        
        return crawlers
    
    def log(self, message: str):
        """记录日志"""
        logging.info(message)
        self.log_callback(message)
    
    def run_once(self, progress_callback=None, stop_event=None) -> Dict[str, Any]:
        """
        执行一次监控
        
        Args:
            progress_callback: 进度回调函数 (current, total, site_name)
            stop_event: 停止事件，用于中断爬取
        
        Returns:
            结果字典，包含 new_count, failed_sites 等
        """
        self.log("=" * 40)
        self.log(f"Start crawling at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        all_matched_bids = []
        failed_sites = []
        total_crawlers = len(self.crawlers)
        
        # AI 过滤统计
        ai_stats = {
            'keyword_matched': [],  # 关键词匹配的项目 (title, url)
            'ai_approved': [],      # AI 判定相关的项目 (title, url, reason)
            'ai_rejected': [],      # AI 判定不相关的项目 (title, url, reason)
            'ai_pending': [],
        }

        seen = set()

        def process_bid(bid):
            if bid.unique_id in seen:
                return False
            seen.add(bid.unique_id)
            from database.workbench import is_notice
            if is_notice(bid.title):
                self.storage.workbench.archive_bid(bid)
            elif not self.keywords:
                return False
            if self.storage.exists(bid):
                self.storage.remove_pending_ai(bid)
                return False
            result = self.matcher.match_any(bid.title, bid.content)
            if not result.matched:
                self.storage.remove_pending_ai(bid)
                return False
            ai_stats['keyword_matched'].append({'title': bid.title, 'url': bid.url})
            if self.ai_guard:
                relevant, reason = self.ai_guard.check_relevance(
                    bid.title, bid.content or "", stop_event=stop_event)
                entry = {'title': bid.title, 'url': bid.url, 'reason': reason}
                if relevant is None:
                    self.storage.save_pending_ai(bid, reason)
                    ai_stats['ai_pending'].append(entry)
                    self.log(f"[AI待复核] {bid.title[:40]}: {reason}，下轮重试")
                    return False
                self.storage.remove_pending_ai(bid)
                if relevant is False:
                    ai_stats['ai_rejected'].append(entry)
                    return False
                ai_stats['ai_approved'].append(entry)
            saved = self.storage.save(bid, notified=False)
            self.storage.remove_pending_ai(bid)
            if saved:
                all_matched_bids.append(bid)
            return saved

        # Retry persisted AI failures even if the source no longer lists the item.
        for bid in self.storage.get_pending_ai():
            if stop_event and stop_event.is_set():
                break
            process_bid(bid)
        
        for idx, crawler in enumerate(self.crawlers, 1):
            # 检查停止信号
            if stop_event and stop_event.is_set():
                self.log("检测到停止信号，中断爬取")
                break
            
            # 调用进度回调
            if progress_callback:
                progress_callback(idx, total_crawlers, crawler.name)
            
            try:
                self.log(f"Crawling: {crawler.name}...")
                bids = crawler.crawl(stop_event=stop_event)
                
                # 爬取后再次检查停止信号
                if stop_event and stop_event.is_set():
                    self.log("检测到停止信号，中断处理")
                    break
                
                if bids is None:
                    # 爬取失败
                    failed_sites.append({
                        'name': crawler.name,
                        'error': 'Failed to fetch data (possibly blocked)'
                    })
                    self.log(f"[FAILED] {crawler.name}: Website may be blocking requests!")
                    continue
                
                # 匹配关键字
                matched_count = 0
                for bid in bids:
                    # 在匹配过程中也检查停止信号
                    if stop_event and stop_event.is_set():
                        self.log("检测到停止信号，中断匹配")
                        break
                    
                    if process_bid(bid):
                        matched_count += 1
                
                self.log(f"[OK] {crawler.name}: Found {len(bids)} items, {matched_count} new matches")
                
            except Exception as e:
                failed_sites.append({'name': crawler.name, 'error': str(e)})
                self.log(f"[ERROR] {crawler.name}: {e}")
        
        # 发送通知
        if all_matched_bids:
            self.log(f"Sending notifications for {len(all_matched_bids)} new items...")
            self._send_notifications(all_matched_bids)
        else:
            self.log("No new matching items found")
        
        # 报告失败的网站
        if failed_sites:
            self.log("-" * 40)
            self.log(f"WARNING: {len(failed_sites)} site(s) failed:")
            for site in failed_sites:
                self.log(f"  - {site['name']}: {site['error']}")
        
        # 输出 AI 过滤汇总报告
        if self.ai_guard and (ai_stats['keyword_matched'] or ai_stats['ai_approved'] or ai_stats['ai_rejected']):
            self.log("")
            self.log("=" * 50)
            self.log("📊 本次检索汇总报告")
            self.log("=" * 50)
            self.log(f"🔍 关键词匹配结果: {len(ai_stats['keyword_matched'])} 条")
            
            if ai_stats['keyword_matched']:
                self.log("   匹配的网页链接:")
                for item in ai_stats['keyword_matched'][:10]:  # 最多显示10条
                    self.log(f"   • {item['title'][:40]}...")
                    self.log(f"     {item['url']}")
                if len(ai_stats['keyword_matched']) > 10:
                    self.log(f"   ... 还有 {len(ai_stats['keyword_matched']) - 10} 条")
            
            self.log("")
            self.log(f"✅ AI判断符合要求: {len(ai_stats['ai_approved'])} 条")
            if ai_stats['ai_approved']:
                for item in ai_stats['ai_approved'][:5]:
                    self.log(f"   ✓ {item['title'][:35]}... (理由: {item['reason']})")
            
            self.log("")
            self.log(f"❌ AI判断不符合: {len(ai_stats['ai_rejected'])} 条")
            if ai_stats['ai_rejected']:
                for item in ai_stats['ai_rejected'][:5]:
                    self.log(f"   ✗ {item['title'][:35]}... (理由: {item['reason']})")
            
            self.log("=" * 50)
        
        self.log("=" * 40)
        
        # 关闭共享浏览器以释放内存
        try:
            from crawler.selenium_crawler import SharedBrowserManager
            SharedBrowserManager.close()
            self.log("✅ 已关闭共享浏览器，释放内存")
        except:
            pass
        
        return {
            'new_count': len(all_matched_bids),
            'failed_sites': failed_sites,
            'total_crawlers': len(self.crawlers),
            'ai_stats': ai_stats
        }
    
    def _send_notifications(self, bids: List[BidInfo]):
        """发送通知"""
        success = False
        
        if self.notify_method in ('email', 'both') and self.email_notifier:
            try:
                if self.email:
                    # 临时修改收件人
                    original_receiver = self.email_notifier.receiver
                    self.email_notifier.receiver = self.email
                    success = self.email_notifier.send(bids)
                    self.email_notifier.receiver = original_receiver
                else:
                    success = self.email_notifier.send(bids)
                
                if success:
                    self.log(f"[OK] Email sent to {self.email or self.email_notifier.receiver}")
            except Exception as e:
                self.log(f"[ERROR] Email failed: {e}")
        
        if self.notify_method in ('sms', 'both') and self.sms_notifier:
            try:
                if self.phone:
                    success = self.sms_notifier.send(self.phone, bids)
                    if success:
                        self.log(f"[OK] SMS sent to {self.phone}")
            except Exception as e:
                self.log(f"[ERROR] SMS failed: {e}")
        
        if success:
            for bid in bids:
                self.storage.mark_notified(bid)
