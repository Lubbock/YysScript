"""日志。

修掉旧 utils/Logger.py 的两个问题：
1. 日志路径写死成 E:\\github\\YysScript\\test.log；
2. 每次 Logger() 都 addHandler，导致同一条日志重复输出。
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional

from config import settings

_FORMAT = "[%(asctime)s] %(name)s %(filename)s:%(lineno)d [%(levelname)s] %(message)s"
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 3
_configured = False


def _configure_root() -> None:
    """只执行一次：给根 logger 挂上控制台 + 文件 handler。"""
    global _configured
    if _configured:
        return

    settings.ensure_dirs()
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    formatter = logging.Formatter(_FORMAT)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    root.addHandler(console)

    try:
        file_handler = RotatingFileHandler(
            str(settings.LOG_FILE),
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError:  # 只读文件系统等场景，降级为只输出到控制台
        _configured = True
        return
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    _configured = True


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """获取 logger。name 为空时用调用方模块名。"""
    _configure_root()
    if name is None:
        frame = sys._getframe(1)
        name = frame.f_globals.get("__name__", "yys")
    return logging.getLogger(name)
