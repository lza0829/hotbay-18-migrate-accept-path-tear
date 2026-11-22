from __future__ import annotations
from datetime import datetime
from fastapi import HTTPException
from app.config import (
    REASON_CROSS_TIER,
    REASON_SAME_TIER,
    REASON_TEXT,
    TIER_ORDER,
    TIER_PREFIXES,
    TIERS,
)


def now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def require_tier(tier: str) -> str:
    if tier not in TIERS:
        raise HTTPException(400, detail=f"温层只能是{'/'.join(TIERS)}")
    return tier


def vault_partition_count(conn, vault_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS c FROM partitions WHERE vault_id=? AND status='在册'",
        (vault_id,),
    ).fetchone()["c"]


def partition_row(conn, pid: int):
    row = conn.execute("SELECT * FROM partitions WHERE id=?", (pid,)).fetchone()
    if not row:
        raise HTTPException(404, detail="分区不存在")
    return row


def tier_gap(from_tier: str, to_tier: str) -> int:
    """级差 = 落点序号 − 现行序号。零=同层，一=相邻，二=跨两级。"""
    return TIER_ORDER[to_tier] - TIER_ORDER[from_tier]


def migration_rule(from_tier: str, to_tier: str) -> dict:
    """全局唯一级差谓词：递进规则页、迁移发起拒单、拒因重放都调它。

    口径（以相邻一级为准）：
    - 级差为零：同层，不构成迁移；
    - 级差绝对值为一：允许（热↔温、温↔冷）；
    - 级差绝对值为二：跨两级，整笔拒绝，不得一笔直达（热→冷、冷→热）。
    """
    gap = tier_gap(from_tier, to_tier)
    if gap == 0:
        return {"allowed": False, "gap": 0, "reason_code": REASON_SAME_TIER, "reason": REASON_TEXT[REASON_SAME_TIER]}
    if abs(gap) == 1:
        return {"allowed": True, "gap": gap, "reason_code": None, "reason": ""}
    return {"allowed": False, "gap": gap, "reason_code": REASON_CROSS_TIER, "reason": REASON_TEXT[REASON_CROSS_TIER]}


def prefix_for_tier(tier: str) -> str:
    """目录归属前缀可由落点温层直接重放。"""
    return f"{TIER_PREFIXES[tier]}/"


def replace_tier_prefix(object_prefix: str, to_tier: str) -> str:
    """把前缀的第一级目录段换成落点温层段，其余路径保持不动。

    例：hot/红海/主成片/ → warm/红海/主成片/
    """
    rest = object_prefix.split("/", 1)[1] if "/" in object_prefix else ""
    return f"{TIER_PREFIXES[to_tier]}/{rest}"


def same_path_predicate(tier: str, object_prefix: str) -> bool:
    """全局唯一同路径谓词：温层与目录归属前缀必须重放同一路径。

    接单、完成、互证、启动对账全部经此判定，禁止旁路只改温层或只改色标。
    温层 tier 可重放出 prefix_for_tier(tier)，且 object_prefix 必须落在该前缀下。
    """
    return bool(tier) and bool(object_prefix) and object_prefix.startswith(prefix_for_tier(tier))

