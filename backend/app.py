"""灰度发布台 — FastAPI 入口。"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from audit_svc import router as audit_router
from compare_svc import router as compare_router
from auth import router as auth_router
from cohorts_svc import router as cohorts_router
from dashboard_svc import router as dashboard_router
from db import FRONTEND, PRODUCT_META, init_db
from envs_svc import router as envs_router
from evaluate_svc import router as evaluate_router
from flags_svc import router as flags_router
from history_svc import router as history_router
from kill_svc import router as kill_router
from locks import router as locks_router
from overrides_svc import router as overrides_router
from releases_svc import router as releases_router
from restore_svc import router as restore_router
from schedules_svc import router as schedules_router
from rules_svc import router as rules_router
from stubs_svc import router as stubs_router

PRODUCT = PRODUCT_META["name"]
SKELETON = PRODUCT_META["skeleton"]

app = FastAPI(title=PRODUCT, description=SKELETON)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (
    auth_router,
    dashboard_router,
    flags_router,
    envs_router,
    cohorts_router,
    rules_router,
    releases_router,
    restore_router,
    schedules_router,
    compare_router,
    kill_router,
    overrides_router,
    evaluate_router,
    history_router,
    locks_router,
    audit_router,
    stubs_router,
):
    app.include_router(r)

# gbf07：台账核对/复核闸门/白名单互斥口的跨服务路径别名。
# 唯一实现仍在 audit_svc（同一本账、同一把锁），这里只让爬坡/历史/总览命名空间可达，
# 不引入第二套口径，也不改变前端导航。
import audit_svc as _audit_svc  # noqa: E402

for _p in (
    "/api/schedules/ledger",
    "/api/schedules/consistency",
    "/api/schedules/audit",
    "/api/history/ledger",
    "/api/history/consistency",
    "/api/dashboard/ledger",
    "/api/dashboard/audit",
    "/api/dashboard/consistency",
):
    app.add_api_route(_p, _audit_svc.get_ledger, methods=["GET"])

for _p in (
    "/api/schedules/review",
    "/api/dashboard/review",
    "/api/dashboard/summary",
    "/api/dashboard/summary/confirm",
    "/api/history/review",
):
    app.add_api_route(_p, _audit_svc.post_review, methods=["POST"])

for _p in (
    "/api/schedules/export-whitelist",
    "/api/schedules/whitelist",
    "/api/dashboard/export-whitelist",
):
    app.add_api_route(_p, _audit_svc.change_whitelist, methods=["POST", "PUT"])
    app.add_api_route(_p, _audit_svc.get_whitelist, methods=["GET"])


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/api/health")
def health():
    from db import DB_PATH, connect

    with connect() as conn:
        flags = conn.execute("SELECT COUNT(*) c FROM flags").fetchone()["c"]
        rules = conn.execute("SELECT COUNT(*) c FROM flag_rules WHERE official=1").fetchone()["c"]
        tables = conn.execute(
            "SELECT COUNT(*) c FROM sqlite_master WHERE type='table'"
        ).fetchone()["c"]
    return {
        "ok": True,
        "product": PRODUCT,
        "domain": PRODUCT_META["domain"],
        "sub_direction": PRODUCT_META["sub"],
        "skeleton": SKELETON,
        "flags": flags,
        "official_rules": rules,
        "tables": tables,
        "db": str(DB_PATH),
    }


app.mount("/assets", StaticFiles(directory=str(FRONTEND)), name="assets")


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")
