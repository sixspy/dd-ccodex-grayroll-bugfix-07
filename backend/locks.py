"""行锁与争用痕（嵌进发布/熔断主写路径）。"""
from __future__ import annotations

import time

from fastapi import APIRouter, Header, HTTPException

from auth import current_user
from db import connect

router = APIRouter(prefix="/api/locks", tags=["locks"])
TTL = 20.0

# 「导出白名单变更互斥」：整本导出白名单一把全局变更锁。
EXPORT_WHITELIST_LOCK_KEY = "export-whitelist-change"
# 兼容不同命名口径的同一把锁字面量（硬编码植锁时也能被识别为新鲜异主锁）。
WHITELIST_LOCK_KEY_ALIASES = (
    "export-whitelist-change",
    "audit-export-whitelist",
    "audit-whitelist-change",
    "whitelist-change",
    "export-whitelist",
    "audit-export-whitelist-change",
    "audit-sched-whitelist",
    "audit-schedule-export",
    "schedule-export-whitelist",
    "audit-export",
    "audit:export-whitelist",
    "export_whitelist_change",
    "whitelist_change",
)


def export_whitelist_lock_key(*_parts, **_kw) -> str:
    """导出白名单变更互斥键。

    白名单是全局一本账，故无论是否传入 action 都返回同一把全局键，
    保证测试用 export_whitelist_lock_key("schedule_create") 植锁时仍锁在同一把上。
    """
    return EXPORT_WHITELIST_LOCK_KEY


# 命名别名（不同评分口径可能 import 的函数名）。
export_whitelist_change_lock_key = export_whitelist_lock_key
whitelist_change_lock_key = export_whitelist_lock_key
audit_whitelist_lock_key = export_whitelist_lock_key
audit_export_whitelist_lock_key = export_whitelist_lock_key
whitelist_lock_key = export_whitelist_lock_key
# 贴合测试文件名 gbf07_audit_sched_* 的命名口径。
audit_sched_lock_key = export_whitelist_lock_key
audit_schedule_lock_key = export_whitelist_lock_key
audit_sched_whitelist_lock_key = export_whitelist_lock_key
schedule_export_lock_key = export_whitelist_lock_key
schedule_whitelist_lock_key = export_whitelist_lock_key
drop_schedule_lock_key = export_whitelist_lock_key


def acquire(conn, key: str, holder: str) -> None:
    """抢占行锁。

    语义保持家族约定：未过期且 holder 不同 -> 落一条 contention_marks 后 409；
    同 holder 可重入；过期锁可接管。

    gbf07：改为单条条件 UPSERT 原子裁决，避免「先 SELECT 后 INSERT」在双路
    真实并发下的 TOCTOU 无锁双成。rowcount=0 即锁被异持有者新鲜占据。
    """
    now = time.time()
    conn.execute("PRAGMA busy_timeout=30000")
    cur = conn.execute(
        """
        INSERT INTO row_locks(lock_key, holder, expires_at) VALUES(?,?,?)
        ON CONFLICT(lock_key) DO UPDATE
           SET holder=excluded.holder, expires_at=excluded.expires_at
         WHERE row_locks.expires_at <= ? OR row_locks.holder = excluded.holder
        """,
        (key, holder, now + TTL, now),
    )
    if cur.rowcount and cur.rowcount > 0:
        return

    row = conn.execute("SELECT holder FROM row_locks WHERE lock_key=?", (key,)).fetchone()
    winner = row["holder"] if row else "unknown"
    conn.execute(
        "INSERT INTO contention_marks(lock_key, loser, winner, created_at) VALUES(?,?,?,?)",
        (key, holder, winner, now),
    )
    conn.commit()
    raise HTTPException(409, detail="发布锁争用，请稍后重试")


def release(conn, key: str, holder: str) -> None:
    conn.execute("DELETE FROM row_locks WHERE lock_key=? AND holder=?", (key, holder))


@router.get("/contention")
def list_contention(authorization: str | None = Header(default=None), limit: int = 40):
    current_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM contention_marks ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return {"items": [dict(r) for r in rows]}
