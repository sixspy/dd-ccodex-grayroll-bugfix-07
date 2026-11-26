"""变更历史。"""
from __future__ import annotations

from fastapi import APIRouter, Header

from audit_svc import schedule_export_audit
from auth import current_user
from db import connect

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("")
def list_history(authorization: str | None = Header(default=None), limit: int = 100):
    current_user(authorization)
    with connect() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                """
                SELECT h.*, f.key AS flag_key, e.code AS env_code
                FROM change_history h
                LEFT JOIN flags f ON f.id=h.flag_id
                LEFT JOIN environments e ON e.id=h.env_id
                ORDER BY h.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        ]
        # 爬坡创建在历史里沿用 action='schedule'，与动作账 schedule_create 是同一业务动作，
        # 显式挂别名，避免台账两侧动作码口径错位被误读成缺行/假绿。
        for row in rows:
            aliases = [row["action"]]
            if row["action"] == "schedule":
                aliases.append("schedule_create")
                row["business_action"] = "schedule_create"
            row["action_aliases"] = aliases
        ledger = schedule_export_audit(conn)
    return {
        "items": rows,
        # gbf07：历史口同样挂台账真相，不得把缺行动作当已复核。
        "ledger": ledger,
        "audit_ledger": ledger,
        "consistent": ledger["consistent"],
        "green": ledger["green"],
        "audit_consistent": ledger["consistent"],
        "audit_green": ledger["green"],
        "missing_actions": ledger["missing_actions"],
    }
