"""
无人机招投标监控系统 - 主程序入口
"""
import os
import sys
import argparse
import logging
from datetime import datetime

import yaml

# 添加src目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.storage import Storage, BidInfo
from crawler.ccgp import CCGPCrawler
from crawler.chinabidding import ChinaBiddingCrawler
from crawler.ebnew import EbnewCrawler
from crawler.plap import PLAPCrawler
from matcher.keyword import KeywordMatcher
from notifier.email import EmailNotifier
from scheduler.runner import Scheduler


# 爬虫注册表
CRAWLER_REGISTRY = {
    'ccgp': CCGPCrawler,
    'chinabidding': ChinaBiddingCrawler,
    'ebnew': EbnewCrawler,
    'plap': PLAPCrawler,
}


def load_config(config_path: str) -> dict:
    """加载配置文件"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def setup_logging(config: dict):
    """配置日志"""
    log_config = config.get('logging', {})
    level = getattr(logging, log_config.get('level', 'INFO').upper())
    log_file = log_config.get('file')
    
    handlers = [logging.StreamHandler()]
    
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding='utf-8'))
    
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers
    )


class BidMonitor:
    """招标监控器主类"""
    
    def __init__(self, config: dict):
        self.config = config
        self.logger = logging.getLogger("monitor")
        
        # 初始化组件
        self.storage = Storage()
        self.matcher = KeywordMatcher(
            include_keywords=config['keywords']['include'],
            exclude_keywords=config['keywords'].get('exclude', [])
        )
        self.notifier = EmailNotifier(config['email'])
        
        # 初始化爬虫
        self.crawlers = []
        crawler_config = config.get('crawler', {})
        enabled_sites = crawler_config.get('enabled_sites', ['ccgp', 'chinabidding', 'ebnew'])
        
        for site in enabled_sites:
            if site in CRAWLER_REGISTRY:
                crawler_class = CRAWLER_REGISTRY[site]
                crawler = crawler_class({
                    **crawler_config,
                    'search_keywords': config['keywords']['include'][:3]  # 使用前3个关键字搜索
                })
                self.crawlers.append(crawler)
                self.logger.info(f"已启用爬虫: {site}")
    
    def run_once(self):
        """执行一次监控任务"""
        self.logger.info("=" * 50)
        self.logger.info(f"开始监控任务 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        all_matched_bids = []
        
        # 遍历所有爬虫
        for crawler in self.crawlers:
            try:
                self.logger.info(f"正在爬取: {crawler.name}")
                bids = crawler.crawl()
                
                # 匹配关键字
                for bid in bids:
                    match_result = self.matcher.match_any(bid.title, bid.content)
                    
                    if match_result.matched:
                        # 检查是否已存在
                        if not self.storage.exists(bid):
                            self.storage.save(bid, notified=False)
                            all_matched_bids.append(bid)
                            self.logger.info(f"[新] 匹配招标: {bid.title[:50]}... 关键字: {match_result.matched_keywords}")
                    elif match_result.excluded_by:
                        self.logger.debug(f"排除: {bid.title[:30]}... (包含排除词: {match_result.excluded_by})")
                        
            except Exception as e:
                self.logger.error(f"爬虫 {crawler.name} 执行失败: {e}")
        
        # 发送通知
        if all_matched_bids:
            self.logger.info(f"发现 {len(all_matched_bids)} 条新招标信息，准备发送通知...")
            success = self.notifier.send(all_matched_bids)
            
            if success:
                # 标记为已通知
                for bid in all_matched_bids:
                    self.storage.mark_notified(bid)
                self.logger.info("邮件发送成功")
            else:
                self.logger.error("邮件发送失败，下次将重新发送")
        else:
            self.logger.info("本次检查没有发现新的匹配招标信息")
        
        self.logger.info(f"监控任务完成 - 数据库共 {self.storage.count_all()} 条记录")
        self.logger.info("=" * 50)
    
    def test_email(self):
        """测试邮件发送"""
        self.logger.info("发送测试邮件...")
        success = self.notifier.send_test()
        if success:
            self.logger.info("测试邮件发送成功，请检查收件箱")
        else:
            self.logger.error("测试邮件发送失败，请检查邮件配置")
        return success


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='Drone Bidding Monitor System')
    parser.add_argument('--config', '-c', default='config/config.yaml',
                        help='Config file path (default: config/config.yaml)')
    parser.add_argument('--crawl-once', action='store_true',
                        help='Crawl once without starting scheduler')
    parser.add_argument('--test-email', action='store_true',
                        help='Send a test email')
    
    args = parser.parse_args()
    
    # 切换到脚本所在目录
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    # 加载配置
    try:
        config = load_config(args.config)
    except FileNotFoundError:
        print(f"错误: 配置文件不存在 - {args.config}")
        print("请复制 config/config.yaml.example 并配置您的邮箱信息")
        sys.exit(1)
    
    # 配置日志
    setup_logging(config)
    logger = logging.getLogger("main")
    
    logger.info("=" * 60)
    logger.info("  无人机招投标监控系统 启动")
    logger.info("=" * 60)
    
    # 创建监控器
    monitor = BidMonitor(config)
    
    # 根据参数执行不同操作
    if args.test_email:
        monitor.test_email()
    elif args.crawl_once:
        monitor.run_once()
    else:
        # 启动定时任务
        schedule_config = config.get('schedule', {})
        scheduler = Scheduler(
            interval_minutes=schedule_config.get('interval_minutes', 30),
            run_immediately=schedule_config.get('run_immediately', True)
        )
        
        logger.info(f"启动定时监控，间隔 {schedule_config.get('interval_minutes', 30)} 分钟")
        logger.info("按 Ctrl+C 停止程序")
        
        scheduler.start(monitor.run_once)


if __name__ == '__main__':
    main()
