"""gbf07 争用失败测 — 双路并发抢「导出白名单变更互斥」，禁止无锁双成。

家族同一验收口径（对打会话 admin / writer）：
- 预置胜方 admin 持 export-whitelist-change 未过期锁，屏障齐发；
- 结果必须恰为 [200,409]：胜方正式变更白名单并留 1 条变更审计，败方只在
  contention_marks 留 1 条痕，不产生正式白名单变更/审计；
- 锁结束释放干净；不预植锁的真实并发靠原子互斥 + UNIQUE 兜底，绝不双份正式成功。

种子代码没有白名单变更口也没有这把互斥，本文件先见红（404/405）。
"""
from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

import db
from app import app
from audit_svc import export_whitelist_lock_key

ACTION = "schedule_create"
LOCK_KEY = export_whitelist_lock_key()
CHANGE_PATH = "/api/audit/export-whitelist"


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "gbf07_race.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    yield db_path


def _seed_winner_lock(db_path, holder: str = "admin", ttl: float = 20.0) -> str:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO row_locks(lock_key, holder, expires_at) VALUES(?,?,?)",
            (LOCK_KEY, holder, time.time() + ttl),
        )
        conn.commit()
    finally:
        conn.close()
    return LOCK_KEY


def _login(client: TestClient, username: str, password: str) -> dict:
    token = client.post(
        "/api/login", json={"username": username, "password": password}
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def duel_audit_drop_schedule(db_path=None, seed_winner: bool = True):
    """并发双请求抢导出白名单变更互斥，返回 [(username, status), ...]。

    与 scripts/duel_audit_drop_schedule.py 同一脚本名口径；
    seed_winner=True 预置 admin 持锁，确定性打出 [200,409]。
    """
    if seed_winner and db_path is not None:
        _seed_winner_lock(db_path, "admin")

    barrier = threading.Barrier(2)
    outcomes: list[tuple[str, int]] = []
    box = threading.Lock()

    def worker(username: str, password: str):
        with TestClient(app) as client:
            headers = _login(client, username, password)
            barrier.wait(timeout=10)
            r = client.post(CHANGE_PATH, headers=headers, json={"action": ACTION})
            with box:
                outcomes.append((username, r.status_code))

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(worker, "admin", "admin123")
        f2 = pool.submit(worker, "writer", "writer123")
        f1.result(timeout=30)
        f2.result(timeout=30)
    return outcomes


def test_foreign_held_lock_loser_leaves_only_mark(isolated_db):
    db_path = isolated_db
    _seed_winner_lock(db_path, holder="rival-winner-session", ttl=600)

    with TestClient(app) as c:
        h = _login(c, "writer", "writer123")
        r = c.post(CHANGE_PATH, headers=h, json={"action": ACTION})

    assert r.status_code == 409, f"他会话持锁必须 409，实际 {r.status_code}: {r.text}"

    conn = sqlite3.connect(db_path)
    try:
        wl = conn.execute(
            "SELECT enabled FROM export_whitelist WHERE action=?", (ACTION,)
        ).fetchone()
        audits = conn.execute(
            "SELECT COUNT(*) c FROM audit_log WHERE action='export_whitelist_change'"
        ).fetchone()[0]
        mark = conn.execute(
            "SELECT loser, winner FROM contention_marks WHERE lock_key=? ORDER BY id DESC LIMIT 1",
            (LOCK_KEY,),
        ).fetchone()
    finally:
        conn.close()

    assert wl is None, "败方不得产生正式白名单变更行"
    assert audits == 0, "败方不得写正式变更审计"
    assert mark is not None and mark[0] == "writer" and mark[1] == "rival-winner-session"


def test_duel_seeded_lock_gives_exactly_one_winner(isolated_db, monkeypatch):
    db_path = isolated_db
    _seed_winner_lock(db_path, "admin")

    import audit_svc

    real_release = audit_svc.release

    def gated_release(conn, key, holder):
        if key == LOCK_KEY and holder == "admin":
            probe = None
            for _ in range(1000):
                probe = sqlite3.connect(db_path)
                try:
                    n = probe.execute(
                        "SELECT COUNT(*) c FROM contention_marks WHERE lock_key=?", (key,)
                    ).fetchone()[0]
                finally:
                    probe.close()
                if n >= 1:
                    break
                time.sleep(0.01)
        return real_release(conn, key, holder)

    monkeypatch.setattr(audit_svc, "release", gated_release)

    outcomes = duel_audit_drop_schedule(None, seed_winner=False)
    statuses = sorted(s for _, s in outcomes)
    assert statuses == [200, 409], f"预置胜方锁后应 [200,409]，实际 {outcomes}"

    conn = sqlite3.connect(db_path)
    try:
        marks = conn.execute(
            "SELECT loser, winner FROM contention_marks WHERE lock_key=?", (LOCK_KEY,)
        ).fetchall()
        left_locks = conn.execute(
            "SELECT COUNT(*) c FROM row_locks WHERE lock_key=?", (LOCK_KEY,)
        ).fetchone()[0]
        audits = conn.execute(
            "SELECT COUNT(*) c FROM audit_log WHERE action='export_whitelist_change'"
        ).fetchone()[0]
        wl = conn.execute(
            "SELECT COUNT(*) c FROM export_whitelist WHERE action=? AND enabled=1", (ACTION,)
        ).fetchone()[0]
    finally:
        conn.close()

    assert len(marks) == 1, f"败方须恰留 1 条争用痕，实际 {marks}"
    assert marks[0][1] == "admin"
    assert marks[0][0] == "writer"
    assert left_locks == 0, "胜方事务结束后互斥锁须释放干净"
    assert audits == 1, "败方零正式成功：白名单变更审计仅胜方 1 条"
    assert wl == 1, "正式白名单中 schedule_create 恰有一条启用行"


def test_unseeded_duel_never_double_formal_success(isolated_db):
    db_path = isolated_db
    outcomes = duel_audit_drop_schedule(db_path, seed_winner=False)

    successes = [x for x in outcomes if 200 <= x[1] < 300]
    assert len(successes) == 1, f"无预置锁并发也必须恰一笔成功，实际 {outcomes}"
    assert all(s in (200, 400, 409) for _, s in outcomes), outcomes

    conn = sqlite3.connect(db_path)
    try:
        audits = conn.execute(
            "SELECT COUNT(*) c FROM audit_log WHERE action='export_whitelist_change'"
        ).fetchone()[0]
        changes = conn.execute(
            "SELECT COUNT(*) c FROM export_whitelist_changes WHERE change_key=?",
            (f"enable:{ACTION}",),
        ).fetchone()[0]
    finally:
        conn.close()
    assert audits == 1, "UNIQUE 兜底：正式变更审计只能一条"
    assert changes == 1
