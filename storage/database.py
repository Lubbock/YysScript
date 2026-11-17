"""数据库连接与建表。

路径来自 config.settings.DB_PATH（可用环境变量 YYS_DB_PATH 覆盖），
不再像旧代码那样在进程当前目录随意生成 gray_scan.db。
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from config import settings

_SCHEMA_FILE = Path(__file__).with_name("schema.sql")


class Database:
    """轻量 sqlite 封装：每次操作一个短连接，自动建表。"""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else settings.DB_PATH
        self._initialized = False

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """上下文管理器：产出连接，正常退出时提交，异常时回滚。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path))
        try:
            self._ensure_schema(conn)
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        if self._initialized:
            return
        conn.executescript(_SCHEMA_FILE.read_text(encoding="utf-8"))
        self._initialized = True
