"""gbf07 失败测甲（红测）— 导出正式结果必须含计划创建动作，台账两侧条数一致。

夹具「有计划创建动作但导出缺行」：
POST /api/schedules 同事务写 rollout_schedules + audit_log(action=schedule_create)，
但种子代码的 /api/audit/export 用黑名单把 schedule_create 滤掉，
于是动作账有行、导出正式结果缺行（台账两侧条数对不上）。

甲路径正确性口径（拍板封死，不混乙路径影子草案）：
- 导出白名单显式配 schedule_create 动作码，正式导出/审计列表都不得吞该业务创建动作；
- 同事务联查 audit_log × rollout_schedules 跨表账实；
- 若导出仍缺计划创建，汇总/复核正式写口整笔拒写（4xx），正式复核账零增。

本文件在种子代码上先见红：导出断言失败 / 复核口 404。
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

import db
from app import app

ACTION = "schedule_create"
STEPS = '[{"percent":10,"after_hours":0},{"percent":30,"after_hours":24}]'


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "gbf07_red.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    with TestClient(app) as c:
        yield c, db_path


def _token(c: TestClient, username: str = "admin", password: str = "admin123") -> str:
    r = c.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _h(c: TestClient, username: str = "admin", password: str = "admin123") -> dict:
    return {"Authorization": f"Bearer {_token(c, username, password)}"}


def _create_schedule(c: TestClient, h: dict, note: str = "gbf07 红测爬坡") -> int:
    r = c.post(
        "/api/schedules",
        headers=h,
        json={"flag_id": 1, "env_id": 1, "steps_json": STEPS, "note": note},
    )
    assert r.status_code == 200, r.text
    return int(r.json()["id"])


@pytest.fixture(name="有计划创建动作但导出缺行")
def _gap_fixture(client, monkeypatch):
    """点名夹具：动作账有 schedule_create；临时把该码移出导出白名单复刻埋雷缺口。"""
    c, db_path = client
    h = _h(c)
    sid = _create_schedule(c, h)
    import audit_svc

    gapped = set(audit_svc.EXPORT_WHITELIST) - {ACTION}
    monkeypatch.setattr(audit_svc, "EXPORT_WHITELIST", gapped)
    return c, db_path, h, sid


def test_fixture_named_gap_reproduces_action_present_but_export_missing(有计划创建动作但导出缺行):
    """先点名夹具「有计划创建动作但导出缺行」，并确认前置状态成立。"""
    c, db_path, h, sid = 有计划创建动作但导出缺行

    conn = sqlite3.connect(db_path)
    try:
        n_audit = conn.execute(
            "SELECT COUNT(*) c FROM audit_log WHERE action=? AND entity_id=?", (ACTION, sid)
        ).fetchone()[0]
    finally:
        conn.close()
    assert n_audit == 1, "夹具前置：动作账必须有该计划创建动作"

    exported = c.get("/api/audit/export", headers=h).json()["items"]
    assert all(
        not (it["action"] == ACTION and it.get("entity_id") == sid) for it in exported
    ), "夹具前置：白名单被临时摘掉后，导出必须缺行（复刻埋雷）"


def test_official_export_contains_schedule_create(client):
    """红测甲本体：修复后导出正式结果必须仍能查到计划创建，而不是『仍无计划创建』。"""
    c, _ = client
    h = _h(c)
    sid = _create_schedule(c, h)

    r = c.get("/api/audit/export", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    rows = [it for it in body["items"] if it["action"] == ACTION and it.get("entity_id") == sid]
    assert rows, "导出正式结果仍无计划创建 = 埋雷未修：白名单必须含 schedule_create"
    assert body["exported"] == len(body["items"])


def test_audit_list_also_contains_schedule_create(client):
    c, _ = client
    h = _h(c)
    sid = _create_schedule(c, h)
    r = c.get("/api/audit", headers=h)
    assert r.status_code == 200, r.text
    assert any(
        it["action"] == ACTION and it.get("entity_id") == sid for it in r.json()["items"]
    ), "审计列表同样不得吞 schedule_create"


def test_export_counts_match_action_ledger(client):
    """台账两侧条数一致：导出条数 == 动作账条数（本用例产生的全是白名单业务动作）。"""
    c, db_path = client
    h = _h(c)
    _create_schedule(c, h, note="条数核对 A")
    _create_schedule(c, h, note="条数核对 B")

    body = c.get("/api/audit/export?limit=500", headers=h).json()
    conn = sqlite3.connect(db_path)
    try:
        total = conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()[0]
        sched_create = conn.execute(
            "SELECT COUNT(*) c FROM audit_log WHERE action=?", (ACTION,)
        ).fetchone()[0]
    finally:
        conn.close()

    assert sched_create >= 2
    assert body["exported"] == total == len(body["items"]), (
        f"导出 {body['exported']} 与动作账 {total} 条数不一致"
    )
    assert sum(1 for it in body["items"] if it["action"] == ACTION) == sched_create


def test_jia_review_write_rejected_zero_growth_when_export_gap(有计划创建动作但导出缺行):
    """甲路径：导出缺计划创建时，汇总/复核正式写口整笔拒写，正式复核账零增。"""
    c, db_path, h, sid = 有计划创建动作但导出缺行

    conn = sqlite3.connect(db_path)
    try:
        before = conn.execute("SELECT COUNT(*) c FROM audit_reviews").fetchone()[0]
    finally:
        conn.close()

    r = c.post("/api/audit/review", headers=h, json={"scope": "schedule_export"})
    assert 400 <= r.status_code < 500, f"账实缺口下复核必须拒写，实际 {r.status_code}: {r.text}"

    conn = sqlite3.connect(db_path)
    try:
        after = conn.execute("SELECT COUNT(*) c FROM audit_reviews").fetchone()[0]
        max_id = conn.execute("SELECT MAX(id) m FROM audit_reviews").fetchone()[0]
    finally:
        conn.close()
    assert after == before == 0, "拒写后正式复核账必须零增"
    assert max_id is None
