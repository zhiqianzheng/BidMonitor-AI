"""
数据存储模块 - 使用 SQLite 存储招标信息

优化说明（v1.1.1）：
- 使用线程本地存储复用数据库连接，提升性能
- 所有公开方法签名保持不变，完全向后兼容
"""
import sqlite3
import hashlib
import os
import threading
import json
from datetime import datetime
from typing import List, Optional
from dataclasses import dataclass, asdict


@dataclass
class BidInfo:
    """招标信息数据类"""
    title: str
    url: str
    publish_date: str
    source: str
    content: str = ""
    purchaser: str = ""
    
    @property
    def unique_id(self) -> str:
        """生成唯一标识（基于URL的MD5）"""
        return hashlib.md5(self.url.encode()).hexdigest()


class Storage:
    """SQLite 数据存储类
    
    使用线程本地存储管理数据库连接，每个线程复用同一个连接，
    避免频繁创建和关闭连接带来的性能开销。
    """
    
    def __init__(self, db_path: str = "data/bids.db"):
        self.db_path = db_path
        # 线程本地存储，用于复用数据库连接
        self._local = threading.local()
        # 确保目录存在
        db_dir = os.path.dirname(db_path)
        if db_dir:  # 处理相对路径情况
            os.makedirs(db_dir, exist_ok=True)
        self._init_db()
        from .workbench import WorkbenchStore
        self.workbench = WorkbenchStore(db_path)
    
    def _get_connection(self) -> sqlite3.Connection:
        """获取当前线程的数据库连接（复用机制）"""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path, timeout=30)
        return self._local.conn
    
    def close(self):
        """关闭当前线程的数据库连接（用于清理资源）"""
        if hasattr(self._local, 'conn') and self._local.conn is not None:
            try:
                self._local.conn.close()
            except:
                pass
            self._local.conn = None
    
    def _init_db(self):
        """初始化数据库表"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bids (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    unique_id TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    publish_date TEXT,
                    source TEXT,
                    content TEXT,
                    purchaser TEXT,
                    notified INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_unique_id ON bids(unique_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_notified ON bids(notified)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_created_at ON bids(created_at)
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS deliveries (
                    bid_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    success INTEGER NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (bid_id, channel, recipient)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ai_pending (
                    unique_id TEXT PRIMARY KEY,
                    bid_json TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
    
    def exists(self, bid: BidInfo) -> bool:
        """检查招标信息是否已存在"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM bids WHERE unique_id = ?",
            (bid.unique_id,)
        )
        return cursor.fetchone() is not None
    
    def save(self, bid: BidInfo, notified: bool = False) -> bool:
        """保存招标信息，返回是否成功（新记录为True，重复为False）"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO bids (unique_id, title, url, publish_date, source, content, purchaser, notified)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            bid.unique_id,
            bid.title,
            bid.url,
            bid.publish_date,
            bid.source,
            bid.content,
            bid.purchaser,
            1 if notified else 0
        ))
        conn.commit()
        return cursor.rowcount == 1
    
    def mark_notified(self, bids):
        """标记招标信息已发送通知
        
        Args:
            bids: 可以是单个BidInfo、BidInfo列表、或URL列表
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # 处理不同输入类型
        if hasattr(bids, 'unique_id'):
            # 单个BidInfo对象
            cursor.execute(
                "UPDATE bids SET notified = 1 WHERE unique_id = ?",
                (bids.unique_id,)
            )
        elif isinstance(bids, list) and len(bids) > 0:
            if hasattr(bids[0], 'unique_id'):
                # BidInfo列表
                for bid in bids:
                    cursor.execute(
                        "UPDATE bids SET notified = 1 WHERE unique_id = ?",
                        (bid.unique_id,)
                    )
            elif isinstance(bids[0], str):
                # URL列表
                for url in bids:
                    unique_id = hashlib.md5(url.encode()).hexdigest()
                    cursor.execute(
                        "UPDATE bids SET notified = 1 WHERE unique_id = ?",
                        (unique_id,)
                    )
        
        conn.commit()
    
    def get_unnotified(self) -> List[BidInfo]:
        """获取未通知的招标信息"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT title, url, publish_date, source, content, purchaser
            FROM bids WHERE notified = 0
        """)
        rows = cursor.fetchall()
        return [
            BidInfo(
                title=row[0],
                url=row[1],
                publish_date=row[2],
                source=row[3],
                content=row[4],
                purchaser=row[5]
            )
            for row in rows
        ]
    
    def get_recent(self, days: int = 7) -> List[BidInfo]:
        """获取最近几天的招标信息"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT title, url, publish_date, source, content, purchaser
            FROM bids 
            WHERE datetime(created_at) > datetime('now', ?)
            ORDER BY created_at DESC
        """, (f'-{days} days',))
        rows = cursor.fetchall()
        return [
            BidInfo(
                title=row[0],
                url=row[1],
                publish_date=row[2],
                source=row[3],
                content=row[4],
                purchaser=row[5]
            )
            for row in rows
        ]
    
    def get_all(self) -> List[BidInfo]:
        """获取所有招标信息"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT title, url, publish_date, source, content, purchaser
            FROM bids 
            ORDER BY created_at DESC
        """)
        rows = cursor.fetchall()
        return [
            BidInfo(
                title=row[0],
                url=row[1],
                publish_date=row[2],
                source=row[3],
                content=row[4],
                purchaser=row[5]
            )
            for row in rows
        ]
    
    def count_all(self) -> int:
        """获取总记录数"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM bids")
        return cursor.fetchone()[0]

    def clear_all(self):
        """清空所有数据"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM bids")
        cursor.execute("DELETE FROM deliveries")
        cursor.execute("DELETE FROM ai_pending")
        conn.commit()

    def delivered_ids(self, channel: str, recipient: str):
        rows = self._get_connection().execute("""
            SELECT d.bid_id FROM deliveries d JOIN bids b ON b.unique_id = d.bid_id
            WHERE d.channel = ? AND d.recipient = ? AND d.success = 1 AND b.notified = 0
        """, (channel, recipient))
        return {row[0] for row in rows}

    def record_delivery(self, bids, channel: str, recipient: str, success: bool):
        conn = self._get_connection()
        with conn:
            conn.executemany("""
                INSERT INTO deliveries (bid_id, channel, recipient, success, attempts)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(bid_id, channel, recipient) DO UPDATE SET
                    success = MAX(deliveries.success, excluded.success),
                    attempts = deliveries.attempts + 1,
                    updated_at = CURRENT_TIMESTAMP
            """, [(b.unique_id, channel, recipient, int(success)) for b in bids])

    def save_pending_ai(self, bid: BidInfo, reason: str):
        conn = self._get_connection()
        with conn:
            conn.execute("""
                INSERT INTO ai_pending (unique_id, bid_json, reason) VALUES (?, ?, ?)
                ON CONFLICT(unique_id) DO UPDATE SET bid_json = excluded.bid_json,
                    reason = excluded.reason, updated_at = CURRENT_TIMESTAMP
            """, (bid.unique_id, json.dumps(asdict(bid), ensure_ascii=False), reason))

    def get_pending_ai(self):
        return [BidInfo(**json.loads(row[0])) for row in
                self._get_connection().execute("SELECT bid_json FROM ai_pending ORDER BY updated_at")]

    def remove_pending_ai(self, bid: BidInfo):
        conn = self._get_connection()
        with conn:
            conn.execute("DELETE FROM ai_pending WHERE unique_id = ?", (bid.unique_id,))

    def get_page(self, limit: int = 50, offset: int = 0):
        rows = self._get_connection().execute("""
            SELECT title, url, publish_date, source, content, purchaser FROM bids
            ORDER BY publish_date DESC, id DESC LIMIT ? OFFSET ?
        """, (limit, offset))
        return [BidInfo(*row) for row in rows]

    def count_today(self):
        return self._get_connection().execute("""
            SELECT COUNT(*) FROM bids
            WHERE created_at >= datetime(date('now', 'localtime'), 'utc')
              AND created_at < datetime(date('now', 'localtime', '+1 day'), 'utc')
        """).fetchone()[0]
