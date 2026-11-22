"""启动对账：同路径谓词架构下的假接单/半截态唯一收口。

口径（全局唯一，见 README「温层与目录归属同刷」）：
- 接单成功必须能由「温层 ∪ 目录前缀 ∪ 迁移单 from/to」重放同一路径；
- 对不上则整笔回滚占坑与温层，禁止只改迁移列表色标；
- 幽灵状态（历史假接单层留下的「已接受」等非枚举值）一律按占坑残留收敛。

本模块只做证据对账与整笔修复，不产生任何新的「接单成功」宣称。
"""
from __future__ import annotations

from app.config import JOB_FAILED, JOB_RUNNING
from app.db import db
from app.services.core import (
    now,
    prefix_for_tier,
    replace_tier_prefix,
    same_path_predicate,
)

# 假接单层历史上写入过的幽灵单据状态；config 枚举之外的任何状态也按同一口径处理。
_GHOST_STATUSES = ("已接受", "占坑中")

# 假接单层残留在 settings 表的键，对账后统一清除，总览不再被旧 payload 顶漂。
_SURFACE_SETTING_KEYS = (
    "migrate_accept_surface_ok",
    "migrate_accept_surface_last",
)


def _reconcile_jobs(conn) -> list[str]:
    """收敛占坑残留：幽灵单 → 已失败回滚；同分区多执行中 → 只留最早一张。"""
    notes = []

    # 1) 幽灵状态单：假接单回执宣称执行中、库内却被改成非枚举状态。
    #    按「占坑但路径证据不可信」整笔收口：单子置已失败，分区温层∪前缀恢复到迁前快照。
    ghosts = conn.execute(
        f"""SELECT * FROM migrate_jobs
            WHERE status NOT IN ('{JOB_RUNNING}', '已完成', '已失败', '已拒绝')
               OR status IN ({','.join('?' for _ in _GHOST_STATUSES)})""",
        _GHOST_STATUSES,
    ).fetchall()
    for j in ghosts:
        p = conn.execute(
            "SELECT * FROM partitions WHERE id=?", (j["partition_id"],)
        ).fetchone()
        if p:
            snap_ok = (
                j["snapshot_tier"] and j["snapshot_prefix"]
                and same_path_predicate(j["snapshot_tier"], j["snapshot_prefix"])
            )
            if snap_ok:
                conn.execute(
                    "UPDATE partitions SET tier=?, object_prefix=? WHERE id=?",
                    (j["snapshot_tier"], j["snapshot_prefix"], p["id"]),
                )
            elif not same_path_predicate(p["tier"], p["object_prefix"]):
                # 快照缺失/不可信时不写空值：以现行温层为事实源重放归属前缀。
                fixed_prefix = replace_tier_prefix(p["object_prefix"], p["tier"])
                conn.execute(
                    "UPDATE partitions SET object_prefix=? WHERE id=?",
                    (fixed_prefix, p["id"]),
                )
        conn.execute(
            "UPDATE migrate_jobs SET status=?, note=? WHERE id=?",
            (JOB_FAILED, "启动对账：假接单幽灵状态，整笔回滚占坑与温层到迁前快照", j["id"]),
        )
        conn.execute(
            """INSERT INTO migrate_audit(job_id, partition_id, event, from_tier, to_tier,
                                         reason_code, reason, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (j["id"], j["partition_id"], JOB_FAILED, j["from_tier"], j["to_tier"],
             "reconcile-ghost", "启动对账收敛假接单幽灵占坑，已回滚到迁前快照", now()),
        )
        notes.append(f"幽灵占坑单#{j['id']} → 已失败并回滚分区#{j['partition_id']}")

    # 2) 并发双占坑兜底：库级单飞索引只认「执行中」，历史绕过索引的双单在此收敛。
    #    同分区保留最早一张执行中，其余整笔置已失败（执行期未改温层，无需动分区）。
    dupes = conn.execute(
        """SELECT * FROM migrate_jobs WHERE status=?
           ORDER BY partition_id, id""",
        (JOB_RUNNING,),
    ).fetchall()
    seen: set[int] = set()
    for j in dupes:
        if j["partition_id"] in seen:
            conn.execute(
                "UPDATE migrate_jobs SET status=?, note=? WHERE id=?",
                (JOB_FAILED, "启动对账：同分区并发双占坑，保留最早执行中单，本单整笔回滚", j["id"]),
            )
            conn.execute(
                """INSERT INTO migrate_audit(job_id, partition_id, event, from_tier, to_tier,
                                             reason_code, reason, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (j["id"], j["partition_id"], JOB_FAILED, j["from_tier"], j["to_tier"],
                 "reconcile-double-slot", "启动对账收敛并发双占坑", now()),
            )
            notes.append(f"双占坑单#{j['id']} → 已失败（分区#{j['partition_id']}保留最早单）")
        else:
            seen.add(j["partition_id"])
    return notes


def _reconcile_partitions(conn) -> list[str]:
    """温层∪前缀分叉的分区：按同路径谓词修目录归属，证据只认温层这一列。

    无执行中单时温层是唯一事实源（迁移完成本就同事务同刷，分叉只可能来自旁路/半截），
    因此把前缀首段重写到温层对应归属，素材对象键随同迁移，保证互证可重放同一路径。
    """
    notes = []
    rows = conn.execute("SELECT * FROM partitions").fetchall()
    for p in rows:
        if same_path_predicate(p["tier"], p["object_prefix"]):
            continue
        running = conn.execute(
            "SELECT id FROM migrate_jobs WHERE partition_id=? AND status=?",
            (p["id"], JOB_RUNNING),
        ).fetchone()
        if running:
            # 执行中单在途：分区尚停在迁前温层，前缀必须与迁前快照一致，按快照收口。
            j = conn.execute(
                "SELECT * FROM migrate_jobs WHERE id=?", (running["id"],)
            ).fetchone()
            want_tier, want_prefix = j["snapshot_tier"], j["snapshot_prefix"]
        else:
            want_tier, want_prefix = p["tier"], replace_tier_prefix(p["object_prefix"], p["tier"])
        old_prefix = p["object_prefix"]
        conn.execute(
            "UPDATE partitions SET tier=?, object_prefix=? WHERE id=?",
            (want_tier, want_prefix, p["id"]),
        )
        for c in conn.execute(
            "SELECT id, object_key FROM clips WHERE partition_id=?", (p["id"],)
        ).fetchall():
            if old_prefix and c["object_key"].startswith(old_prefix):
                new_key = want_prefix + c["object_key"][len(old_prefix):]
            else:
                new_key = want_prefix + c["object_key"].split("/", 1)[-1]
            conn.execute("UPDATE clips SET object_key=? WHERE id=?", (new_key, c["id"]))
            conn.execute(
                "UPDATE inventory_objects SET object_key=? WHERE object_key=?",
                (new_key, c["object_key"]),
            )
        notes.append(
            f"分区#{p['id']} 前缀分叉收口：{old_prefix} → {want_prefix}（温层{want_tier}，归属{prefix_for_tier(want_tier)}）"
        )
    return notes


def reconcile_on_startup() -> dict:
    """进程启动时执行一次；全部修复在单一事务内提交，任一失败整体回滚不留新半截。"""
    with db() as conn:
        notes = []
        notes.extend(_reconcile_jobs(conn))
        notes.extend(_reconcile_partitions(conn))
        for key in _SURFACE_SETTING_KEYS:
            cur = conn.execute("DELETE FROM settings WHERE key=?", (key,))
            if cur.rowcount:
                notes.append(f"清除假接单残留设置：{key}")
        # 连带清掉按单号沉淀的 surface payload。
        cur = conn.execute(
            "DELETE FROM settings WHERE key LIKE 'migrate_accept_surface:%'"
        )
        if cur.rowcount:
            notes.append(f"清除 {cur.rowcount} 条按单号假接单 payload")
        return {"reconciled": len(notes), "notes": notes}
