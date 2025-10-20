"""
logger_setup.py
----------------------------------------
全局日志配置模块（生产级版本）
- 控制台: INFO 级别
- 文件: DEBUG 级别
- 日志文件每日自动归档，保留30天
----------------------------------------
"""

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


def setup_logging():
    """
    初始化全局 logging 配置
    """
    LOG_DIR = Path("logs")
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / "monitor.log"

    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    # 根 logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # 控制台 handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(fmt, datefmt))

    # ✅ 每日归档文件 handler（保留30天）
    file_handler = TimedRotatingFileHandler(
        filename=log_file,
        when="midnight",      # 每天午夜轮转
        interval=1,           # 1天
        backupCount=30,       # 保留30天
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(fmt, datefmt))

    # 防止重复添加 handler
    if not root_logger.handlers:
        root_logger.addHandler(console_handler)
        root_logger.addHandler(file_handler)

    # 附加说明日志
    root_logger.info("🪵 Logging system initialized: rotating daily, keep 30 days of history.")
