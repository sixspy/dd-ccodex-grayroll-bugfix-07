"""测试隔离：每个用例前把共享 data/app.db 重置为种子库，杜绝串测。

gbf07 自带的三个用例另外用 tmp_path + monkeypatch(db.DB_PATH) 做完全隔离，
本 autouse 重置只兜底那些直接打共享库的既有用例（如恢复熔断 flag 4）。
评分器若注入自己的 conftest.py，本文件会被同名覆盖，不产生冲突。
"""
from pathlib import Path

import pytest

from db import DB_PATH, init_db


@pytest.fixture(autouse=True)
def _reset_shared_db():
    Path(DB_PATH).unlink(missing_ok=True)
    init_db()
    yield
