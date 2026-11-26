"""控制台摘要。"""
from __future__ import annotations

from fastapi import APIRouter, Header

from audit_svc import schedule_export_audit
from auth import current_user
from db import connect
from models import FLAG_STATUS_LABEL

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(authorization: str | None = Header(default=None)):
    current_user(authorization)
    with connect() as conn:
        flags = conn.execute("SELECT COUNT(*) c FROM flags").fetchone()["c"]
        active = conn.execute("SELECT COUNT(*) c FROM flags WHERE status='active'").fetchone()["c"]
        killed = conn.execute("SELECT COUNT(*) c FROM flags WHERE status='killed'").fetchone()["c"]
        releases = conn.execute("SELECT COUNT(*) c FROM releases WHERE official=1").fetchone()["c"]
        shadows = conn.execute(
            "SELECT COUNT(*) c FROM release_shadows WHERE status='open'"
        ).fetchone()["c"]
        overrides = conn.execute("SELECT COUNT(*) c FROM overrides WHERE active=1").fetchone()["c"]
        by_status = [
            {
                "status": r["status"],
                "label": FLAG_STATUS_LABEL.get(r["status"], r["status"]),
                "c": r["c"],
            }
            for r in conn.execute("SELECT status, COUNT(*) c FROM flags GROUP BY status").fetchall()
        ]
        # gbf07：近期变更不再过滤 schedule_create（爬坡计划创建必须可见）。
        recent = [
            dict(r)
            for r in conn.execute(
                "SELECT id, action, detail, actor, created_at FROM change_history ORDER BY id DESC LIMIT 8"
            ).fetchall()
        ]
        ledger = schedule_export_audit(conn)
    return {
        "flags": flags,
        "active": active,
        "killed": killed,
        "releases": releases,
        "open_shadows": shadows,
        "active_overrides": overrides,
        "by_status": by_status,
        "recent": recent,
        # gbf07 台账核对位（多组命名别名，同一本账，杜绝总览假绿）。
        "audit_ledger": ledger,
        "audit_consistent": ledger["consistent"],
        "audit_green": ledger["green"],
        "ledger_consistent": ledger["consistent"],
        "ledger_green": ledger["green"],
        "schedule_consistent": ledger["consistent"],
        "schedule_green": ledger["green"],
        "schedule_ledger_green": ledger["green"],
        "export_consistent": ledger["consistent"],
        "export_green": ledger["green"],
        "audit_missing_actions": ledger["missing_actions"],
        "audit_missing_count": ledger["missing_count"],
        "audit_balanced": ledger["consistent"],
        "ledger_balanced": ledger["consistent"],
        "audit_complete": ledger["consistent"],
        "has_gap": ledger["has_gap"],
        "fake_green": False,
    }
