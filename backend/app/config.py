from __future__ import annotations
import os
from pathlib import Path

PROJECT_NAME = "热档片间"
ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.environ.get("HOTBAY_DB", str(ROOT / "data" / "hotbay.db")))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# 全局唯一口径：以相邻一级为准（递进沉降）。
# 热→冷跨两级不得一笔直达，必须经温档；冷→热同理逐级回升。
TIERS = ("热档", "温档", "冷档")
TIER_ORDER = {"热档": 0, "温档": 1, "冷档": 2}

# 温层 → 目录归属前缀（第一级目录段）。目录归属必须能由落点温层重放。
TIER_PREFIXES = {"热档": "hot", "温档": "warm", "冷档": "cold"}
PREFIX_TIER = {v: k for k, v in TIER_PREFIXES.items()}

# 迁移单状态
JOB_RUNNING = "执行中"
JOB_DONE = "已完成"
JOB_FAILED = "已失败"
JOB_REJECTED = "已拒绝"

# 结构化拒因码（规则页与迁移页拒因共用同一谓词产出，禁止只改文案）
REASON_SAME_TIER = "same-tier"
REASON_CROSS_TIER = "cross-tier"
REASON_NOT_ACTIVE = "not-active"
REASON_DOUBLE_MIGRATION = "double-migration"
REASON_NOT_RUNNING = "not-running"

REASON_TEXT = {
    REASON_SAME_TIER: "目标温层与现行相同，级差为零，不构成迁移",
    REASON_CROSS_TIER: "禁止跨两级直达：仅接受相邻一级迁移（热档→温档→冷档），请先落到相邻温层",
    REASON_NOT_ACTIVE: "仅在册分区可迁移",
    REASON_DOUBLE_MIGRATION: "同一分区已有执行中的迁移，拒绝并发双迁",
    REASON_NOT_RUNNING: "迁移单不在执行中",
}
