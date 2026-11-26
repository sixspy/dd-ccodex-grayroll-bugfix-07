"""gbf07 失败测乙（假绿）— 台账不得把『导出缺行』当成已复核齐套而报假绿。

埋雷表象：总览摘要照常 200、角标/统计一片绿，但 schedule_create 被导出白名单滤掉，
缺行动作在台账核对里被当成『已复核』，是为假绿。

修复口径（与甲路径同一本账，不混乙路径）：
- 审计服务提供同事务联查 audit_log × rollout_schedules 的账实报告，
  缺口存在时 consistent/green 必须为 False，并点名 missing_actions=schedule_create；
- 总览服务、历史服务挂出同一本账的真实状态，不得各自报假绿；
- 缺口下复核/汇总写口拒写；账实齐套后才允许复核落正式行（真绿）。
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

import db
from app import app

ACTION = "schedule_create"
STEPS = '[{"percent":20,"after_hours":0},{"percent":40,"after_hours":12}]'


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "gbf07_fake.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    with TestClient(app) as c:
        yield c, db_path


def _h(c: TestClient, username: str = "admin", password: str = "admin123") -> dict:
    t = c.post("/api/login", json={"username": username, "password": password}).json()["token"]
    return {"Authorization": f"Bearer {t}"}


def _create_schedule(c: TestClient, h: dict) -> int:
    r = c.post(
        "/api/schedules",
        headers=h,
        json={"flag_id": 2, "env_id": 2, "steps_json": STEPS, "note": "假绿核对爬坡"},
    )
    assert r.status_code == 200, r.text
    return int(r.json()["id"])


def _force_gap(monkeypatch):
    import audit_svc

    monkeypatch.setattr(audit_svc, "EXPORT_WHITELIST", set(audit_svc.EXPORT_WHITELIST) - {ACTION})


def test_ledger_report_flags_missing_action_not_fake_green(client, monkeypatch):
    c, db_path = client
    h = _h(c)
    sid = _create_schedule(c, h)
    _force_gap(monkeypatch)

    r = c.get("/api/audit/ledger", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["consistent"] is False, "导出缺计划创建时账实必须不一致"
    assert body["green"] is False, "把缺行动作当齐套 = 假绿，必须封死"
    assert ACTION in body["missing_actions"]
    missing_ids = [row.get("entity_id") for row in body["missing_rows"] if row.get("action") == ACTION]
    assert sid in missing_ids


def test_dashboard_must_not_report_fake_green(client, monkeypatch):
    """假绿分属总览服务：缺口时总览挂出的核对位必须为 False。"""
    c, _ = client
    h = _h(c)
    _create_schedule(c, h)
    _force_gap(monkeypatch)

    r = c.get("/api/dashboard", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("audit_consistent", "audit_green", "schedule_ledger_green"):
        assert key in body, f"总览必须挂出台账核对位 {key}"
    assert body["audit_consistent"] is False
    assert body["audit_green"] is False, "总览不得用角标动画/统计把缺口盖成真绿"
    assert body["schedule_ledger_green"] is False
    assert ACTION in body["audit_missing_actions"]


def test_history_service_surfaces_same_ledger_truth(client, monkeypatch):
    """假绿分属历史服务：历史口挂出的同一本账也不得报绿。"""
    c, _ = client
    h = _h(c)
    _create_schedule(c, h)
    _force_gap(monkeypatch)

    r = c.get("/api/history", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("consistent") is False or body.get("audit_consistent") is False
    assert body.get("green") is False or body.get("audit_green") is False


def test_review_gate_rejects_gap_and_then_real_green_after_heal(client, monkeypatch):
    """缺口拒写（零增）；摘掉缺口（恢复白名单）后复核成功 = 真绿，不再假绿。"""
    c, db_path = client
    h = _h(c)
    _create_schedule(c, h)
    _force_gap(monkeypatch)

    bad = c.post("/api/audit/review", headers=h, json={})
    assert 400 <= bad.status_code < 500, bad.text
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) c FROM audit_reviews").fetchone()[0] == 0
    finally:
        conn.close()

    # 摘掉缺口（把动作码加回当前生效集合，等价于重新配码）后，同一本账转真绿。
    import audit_svc

    audit_svc.EXPORT_WHITELIST.add(ACTION)
    ok = c.post("/api/audit/review", headers=h, json={})
    assert ok.status_code == 200, ok.text
    rb = ok.json()
    assert rb["reviewed"] is True
    assert rb["consistent"] is True and rb["green"] is True

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) c FROM audit_reviews").fetchone()[0] == 1
    finally:
        conn.close()


def test_healthy_dashboard_recent_shows_schedule_create(client):
    """齐套时总览『最近变更』不得再吞 schedule_create（第三处滤点）。"""
    c, _ = client
    h = _h(c)
    sid = _create_schedule(c, h)
    d = c.get("/api/dashboard", headers=h).json()
    assert any(
        row.get("action") in (ACTION, "schedule") and f"{sid}" in str(row.get("detail", ""))
        for row in d["recent"]
    ), "总览最近变更必须看得到爬坡计划创建"
    assert d["audit_green"] is True
