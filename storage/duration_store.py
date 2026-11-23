"""耗时样本存取：表 `GAMETIME_RECORD`，写入后按上限裁剪。"""

from __future__ import annotations

from typing import List, Optional

from config import settings
from core.logger import get_logger
from storage.database import Database

log = get_logger(__name__)

_TABLE = "GAMETIME_RECORD"


class DurationStore:
    """按关键字（动作名 / 状态名）记录耗时秒数，并提供均值查询。"""

    def __init__(self, database: Optional[Database] = None) -> None:
        self._db = database or Database()

    # ------------------------------------------------------------------ 写入
    def record(self, key: str, seconds: float) -> None:
        """写入一条耗时样本，超出上限时自动裁剪最旧的数据。"""
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO {} (KEY_NAME, P_NUM) VALUES (?, ?)".format(_TABLE),
                (key, float(seconds)),
            )
            count = self._count(conn, key)
        if count > settings.DURATION_SAMPLE_LIMIT:
            self.trim(key, settings.DURATION_SAMPLE_KEEP)

    def trim(self, key: str, keep: int) -> int:
        """只保留 key 最近 keep 条样本，返回删除条数。"""
        with self._db.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM {} WHERE KEY_NAME = ? AND rowid NOT IN ("
                "  SELECT rowid FROM {} WHERE KEY_NAME = ? ORDER BY rowid DESC LIMIT ?"
                ")".format(_TABLE, _TABLE),
                (key, key, keep),
            )
            deleted = cursor.rowcount
        log.info("耗时样本 %s 裁剪 %s 条，保留 %s 条", key, deleted, keep)
        return deleted

    # ------------------------------------------------------------------ 读取
    def average(self, key: str) -> Optional[float]:
        """key 的历史平均耗时；无样本时返回 None。"""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT AVG(P_NUM) FROM {} WHERE KEY_NAME = ?".format(_TABLE), (key,)
            ).fetchone()
        if row is None or row[0] is None:
            return None
        return float(row[0])

    def samples(self, key: str) -> List[float]:
        """key 的全部耗时样本（按写入顺序）。"""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT P_NUM FROM {} WHERE KEY_NAME = ? ORDER BY rowid".format(_TABLE),
                (key,),
            ).fetchall()
        return [float(r[0]) for r in rows]

    def count(self, key: str) -> int:
        with self._db.connect() as conn:
            return self._count(conn, key)

    def keys(self, prefix: str = "") -> List[str]:
        """有样本的全部 key（可按前缀过滤），按字典序返回。

        给 core/timing.py 的 summary() 用：新进程里内存窗口还是空的，
        只遍历内存会误报「暂无计时样本」，必须从库里把 key 捞出来。
        """
        sql = "SELECT DISTINCT KEY_NAME FROM {}".format(_TABLE)
        params: tuple = ()
        if prefix:
            sql += " WHERE KEY_NAME LIKE ?"
            # 转义 LIKE 通配符，避免 key 里的 % / _ 被当成模式
            escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params = (escaped + "%",)
            sql += " ESCAPE '\\'"
        sql += " ORDER BY KEY_NAME"
        with self._db.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [str(row[0]) for row in rows]

    def clear(self, key: str) -> int:
        """删除 key 的全部样本。"""
        with self._db.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM {} WHERE KEY_NAME = ?".format(_TABLE), (key,)
            )
            return cursor.rowcount

    @staticmethod
    def _count(conn, key: str) -> int:
        row = conn.execute(
            "SELECT COUNT(*) FROM {} WHERE KEY_NAME = ?".format(_TABLE), (key,)
        ).fetchone()
        return int(row[0]) if row else 0
