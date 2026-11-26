#!/usr/bin/env python3
"""duel_audit_drop_schedule — 双路并发对打「导出白名单变更互斥」。

脚本名口径：duel_audit_drop_schedule（审计导出曾经 drop 掉 schedule_create）。

两种用法：
1) 打真实起好的服务（纯标准库）：
   python scripts/duel_audit_drop_schedule.py \
       --base http://127.0.0.1:8000
   期望输出两笔状态恰为 [200, 409]（或 UNIQUE 兜底的 400/409），
   并到 /api/locks/contention 看到 1 条 lock_key=export-whitelist-change 的争用痕；
   败方无正式成功。退出码 0 表示口径成立。

2) 不起服务的进程内自检（需要 fastapi/testclient 依赖）：
   python scripts/duel_audit_drop_schedule.py --inproc

也可被测试按路径导入并调用 duel_audit_drop_schedule(...)。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

LOCK_KEY = "export-whitelist-change"
DEFAULT_PATH = "/api/audit/export-whitelist"
DEFAULT_ACTION = "schedule_create"


def _http_json(method: str, url: str, payload: dict | None = None, token: str | None = None):
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            body = {}
        return e.code, body


def _login(base: str, username: str, password: str) -> str:
    status, body = _http_json(
        "POST", f"{base.rstrip('/')}/api/login",
        {"username": username, "password": password},
    )
    if status != 200:
        raise RuntimeError(f"login {username} failed: {status} {body}")
    return body["token"]


def duel_audit_drop_schedule(
    base_url: str = "http://127.0.0.1:8000",
    path: str = DEFAULT_PATH,
    action: str = DEFAULT_ACTION,
    user_a: tuple[str, str] = ("admin", "admin123"),
    user_b: tuple[str, str] = ("writer", "writer123"),
    seed_winner: bool = False,
    db_path: str | None = None,
):
    """向白名单变更口屏障齐发两笔相同请求，返回 [(username, status), ...]。"""
    base = base_url.rstrip("/")
    token_a = _login(base, *user_a)
    token_b = _login(base, *user_b)
    duel_id = uuid.uuid4().hex[:12]
    payload = {"action": action, "duel_id": duel_id}
    barrier = threading.Barrier(2)
    outcomes: list[tuple[str, int]] = []
    box = threading.Lock()

    def worker(username: str, token: str):
        barrier.wait(timeout=10)
        status, _ = _http_json(
            "POST", f"{base}{path}", payload, token=token
        )
        with box:
            outcomes.append((username, status))

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(worker, user_a[0], token_a)
        f2 = pool.submit(worker, user_b[0], token_b)
        f1.result(timeout=40)
        f2.result(timeout=40)
    return outcomes


def duel_inproc() -> list[tuple[str, int]]:
    """进程内临时隔离库对打，便于无服务自检。"""
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "backend"))
    import db  # noqa: E402
    from fastapi.testclient import TestClient  # noqa: E402
    from app import app  # noqa: E402

    tmp_db = Path(tempfile.mkdtemp(prefix="duel_audit_")) / "duel.db"
    db.DB_PATH = tmp_db
    db.init_db()

    barrier = threading.Barrier(2)
    outcomes: list[tuple[str, int]] = []
    box = threading.Lock()
    duel_id = uuid.uuid4().hex[:12]

    def worker(username: str, password: str):
        with TestClient(app) as client:
            token = client.post(
                "/api/login", json={"username": username, "password": password}
            ).json()["token"]
            headers = {"Authorization": f"Bearer {token}"}
            barrier.wait(timeout=10)
            r = client.post(
                DEFAULT_PATH, headers=headers,
                json={"action": DEFAULT_ACTION, "duel_id": duel_id},
            )
            with box:
                outcomes.append((username, r.status_code))

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(worker, "admin", "admin123")
        f2 = pool.submit(worker, "writer", "writer123")
        f1.result(timeout=30)
        f2.result(timeout=30)
    return outcomes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="duel_audit_drop_schedule")
    parser.add_argument("--base", default=None,
                        help="真实服务地址；不给则裸跑进程内 TestClient 对打")
    parser.add_argument("--path", default=DEFAULT_PATH)
    parser.add_argument("--action", default=DEFAULT_ACTION)
    parser.add_argument("--inproc", action="store_true", help="不起真实服务，进程内自检")
    args = parser.parse_args(argv)

    base = args.base or os.environ.get("GRAYROLL_BASE_URL") or os.environ.get("BASE_URL")
    if args.inproc or not base:
        if not args.inproc and not base:
            print("未提供 --base/BASE_URL，使用进程内 TestClient 对打（--inproc）。")
        outcomes = duel_inproc()
    else:
        outcomes = duel_audit_drop_schedule(base, args.path, args.action)

    statuses = sorted(s for _, s in outcomes)
    print("duel_audit_drop_schedule outcomes:", outcomes)
    ok = statuses == [200, 409] or (
        len([s for s in statuses if 200 <= s < 300]) == 1
        and all(s in (200, 400, 409) for s in statuses)
    )
    print("判定:", "PASS 恰一笔正式成功，败方无正式成功" if ok else "FAIL 出现双成/异常状态")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
