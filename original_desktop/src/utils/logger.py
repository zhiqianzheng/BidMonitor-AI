"""
统一日志配置工具

提供统一的日志配置，支持控制台和文件输出。
这个模块是可选的增强，现有代码无需改动即可继续工作。
"""
import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional


def setup_logger(
    name: str, 
    log_file: Optional[str] = None, 
    level: int = logging.INFO,
    max_bytes: int = 5 * 1024 * 1024,  # 5MB
    backup_count: int = 3
) -> logging.Logger:
    """
    配置并返回一个logger实例
    
    Args:
        name: Logger名称
        log_file: 日志文件路径（可选）
        level: 日志级别
        max_bytes: 单个日志文件最大大小
        backup_count: 保留的备份文件数量
    
    Returns:
        配置好的Logger实例
    
    Example:
        logger = setup_logger("crawler", "logs/crawler.log")
        logger.info("开始爬取...")
    """
    logger = logging.getLogger(name)
    
    # 避免重复添加handler
    if logger.handlers:
        return logger
    
    # 日志格式
    formatter = logging.Formatter(
        '%(asctime)s | %(name)-12s | %(levelname)-7s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 文件处理器（可选）
    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    logger.setLevel(level)
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """
    获取一个logger，如果不存在则使用默认配置创建
    
    Args:
        name: Logger名称
    
    Returns:
        Logger实例
    """
    logger = logging.getLogger(name)
    
    # 如果没有handler，添加一个基本的控制台handler
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            '%(asctime)s | %(name)s | %(levelname)s | %(message)s'
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    
    return logger
