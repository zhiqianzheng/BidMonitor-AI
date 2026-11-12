"""
定时调度模块
"""
import logging
from typing import Callable
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger


class Scheduler:
    """定时任务调度器"""
    
    def __init__(self, interval_minutes: int = 30, run_immediately: bool = True):
        """
        初始化调度器
        
        Args:
            interval_minutes: 执行间隔（分钟）
            run_immediately: 是否立即执行一次
        """
        self.interval_minutes = interval_minutes
        self.run_immediately = run_immediately
        self.scheduler = BlockingScheduler()
        self.logger = logging.getLogger("scheduler")
    
    def add_job(self, func: Callable, name: str = "monitor_job"):
        """
        添加定时任务
        
        Args:
            func: 要执行的函数
            name: 任务名称
        """
        self.scheduler.add_job(
            func,
            IntervalTrigger(minutes=self.interval_minutes),
            id=name,
            name=name,
            replace_existing=True
        )
        self.logger.info(f"已添加定时任务: {name}, 间隔 {self.interval_minutes} 分钟")
    
    def start(self, job_func: Callable):
        """
        启动调度器
        
        Args:
            job_func: 要定时执行的函数
        """
        self.add_job(job_func)
        
        # 是否立即执行一次
        if self.run_immediately:
            self.logger.info("立即执行一次任务...")
            try:
                job_func()
            except Exception as e:
                self.logger.error(f"首次执行失败: {e}")
        
        self.logger.info("调度器启动，等待下次执行...")
        
        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            self.logger.info("调度器停止")
            self.scheduler.shutdown()
    
    def stop(self):
        """停止调度器"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            self.logger.info("调度器已停止")
