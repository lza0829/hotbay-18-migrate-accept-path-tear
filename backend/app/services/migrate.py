from __future__ import annotations
import sqlite3
from fastapi import HTTPException
from app.config import (
    JOB_DONE,
    JOB_FAILED,
    JOB_REJECTED,
    JOB_RUNNING,
    REASON_DOUBLE_MIGRATION,
    REASON_NOT_ACTIVE,
    REASON_NOT_RUNNING,
    REASON_PATH_DIVERGED,
    REASON_TEXT,
    TIER_ORDER,
    TIER_PREFIXES,
)
from app.db import db
from app.services.core import (
    migration_rule,
    now,
    partition_row,
    prefix_for_tier,
    replace_tier_prefix,
    require_tier,
    same_path_predicate,
)


def _audit(conn, *, partition_id, event, job_id=None, from_tier="", to_tier="", reason_code="", reason=""):
    """每一次发起/拒单/完成/失败/回滚都落审计，中间态可对照。"""
    conn.execute(
        '''INSERT INTO migrate_audit(job_id, partition_id, event, from_tier, to_tier, reason_code, reason, created_at)
           VALUES (?,?,?,?,?,?,?,?)''',
        (job_id, partition_id, event, from_tier, to_tier, reason_code, reason, now()),
    )


def _reject(conn, *, partition_id, from_tier, to_tier, from_prefix, reason_code, reason):
    """拒单同样落迁移单（状态=已拒绝）与审计，拒因是结构化码+文案，不是裸字符串。

    from/to 温层与迁前/落点前缀一并记录，落点前缀可由目标温层直接重放。
    """
    cur = conn.execute(
        '''INSERT INTO migrate_jobs(partition_id, from_tier, to_tier, status, created_at,
                                    reject_code, reject_reason, from_prefix, to_prefix,
                                    snapshot_tier, snapshot_prefix)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
        (
            partition_id, from_tier, to_tier, JOB_REJECTED, now(),
            reason_code, reason, from_prefix, prefix_for_tier(to_tier), from_tier, from_prefix,
        ),
    )
    _audit(conn, partition_id=partition_id, event=JOB_REJECTED, job_id=cur.lastrowid,
           from_tier=from_tier, to_tier=to_tier, reason_code=reason_code, reason=reason)
    return cur.lastrowid


def list_jobs():
    with db() as conn:
        rows = conn.execute(
            '''SELECT j.*, p.part_key, p.title FROM migrate_jobs j
               JOIN partitions p ON p.id=j.partition_id ORDER BY j.id DESC'''
        ).fetchall()
        return [dict(r) for r in rows]


def list_audit(partition_id: int | None = None):
    with db() as conn:
        if partition_id is not None:
            rows = conn.execute(
                '''SELECT a.*, p.part_key FROM migrate_audit a
                   JOIN partitions p ON p.id=a.partition_id
                   WHERE a.partition_id=? ORDER BY a.id DESC''',
                (partition_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                '''SELECT a.*, p.part_key FROM migrate_audit a
                   JOIN partitions p ON p.id=a.partition_id ORDER BY a.id DESC'''
            ).fetchall()
        return [dict(r) for r in rows]


def _refuse_diverged(conn, *, partition_id, tier, object_prefix, to_tier=""):
    """接单证据分叉时的唯一收口：只落审计留痕，不建迁移单。

    拒单单据会把分叉的 from/to 固化成「拧花」证据，故此处仅写审计，
    占坑与温层的整笔回滚由启动对账（reconcile）统一执行。
    """
    want = prefix_for_tier(tier)
    _audit(
        conn, partition_id=partition_id, event=JOB_REJECTED,
        from_tier=tier, to_tier=to_tier,
        reason_code=REASON_PATH_DIVERGED,
        reason=f"{REASON_TEXT[REASON_PATH_DIVERGED]}；现行前缀{object_prefix}，应重放为{want}",
    )
    conn.commit()
    raise HTTPException(
        409,
        detail={
            "code": REASON_PATH_DIVERGED,
            "reason": REASON_TEXT[REASON_PATH_DIVERGED],
            "tier": tier,
            "object_prefix": object_prefix,
            "want_prefix": want,
        },
    )


def start_migrate(partition_id: int, to_tier: str):
    to_tier = require_tier(to_tier)
    with db() as conn:
        p = partition_row(conn, partition_id)
        from_tier = p["tier"]
        from_prefix = p["object_prefix"]

        # 同路径谓词闸门①：接单前分区自身的「温层∪目录前缀」必须先能重放同一路径。
        # 现行证据若已分叉（半截态残留），拒绝再占坑，交由启动对账收口，禁止假接单。
        if not same_path_predicate(from_tier, from_prefix):
            _refuse_diverged(
                conn, partition_id=partition_id, tier=from_tier,
                object_prefix=from_prefix, to_tier=to_tier,
            )

        if p["status"] != "在册":
            code, text = REASON_NOT_ACTIVE, REASON_TEXT[REASON_NOT_ACTIVE]
            job_id = _reject(conn, partition_id=partition_id, from_tier=from_tier, to_tier=to_tier,
                             from_prefix=from_prefix, reason_code=code, reason=text)
            # 拒单与审计必须留痕：先提交再抛错，避免异常回滚把拒单一并撤销。
            conn.commit()
            raise HTTPException(400, detail={"code": code, "reason": text, "job_id": job_id})

        # 同一级差谓词：规则页与拒单共用，跨两级在此整笔拒绝，不产生执行中单。
        rule = migration_rule(from_tier, to_tier)
        if not rule["allowed"]:
            code = rule["reason_code"]
            job_id = _reject(conn, partition_id=partition_id, from_tier=from_tier, to_tier=to_tier,
                             from_prefix=from_prefix, reason_code=code, reason=rule["reason"])
            conn.commit()
            raise HTTPException(400, detail={"code": code, "reason": rule["reason"], "job_id": job_id})

        to_prefix = replace_tier_prefix(from_prefix, to_tier)
        # 同路径谓词闸门②：落点前缀必须能由目标温层直接重放，
        # 单据 from/to 与温层∪前缀三者锁定同一路径后才允许占坑。
        if not same_path_predicate(to_tier, to_prefix):
            _refuse_diverged(
                conn, partition_id=partition_id, tier=to_tier,
                object_prefix=to_prefix, to_tier=to_tier,
            )
        try:
            cur = conn.execute(
                '''INSERT INTO migrate_jobs(partition_id, from_tier, to_tier, status, created_at,
                                            from_prefix, to_prefix, snapshot_tier, snapshot_prefix)
                   VALUES (?,?,?,?,?,?,?,?,?)''',
                (partition_id, from_tier, to_tier, JOB_RUNNING, now(),
                 from_prefix, to_prefix, from_tier, from_prefix),
            )
        except sqlite3.IntegrityError:
            # 库级单飞索引兜底：并发双迁只有第一张能落成「执行中」，第二张在此拒绝。
            code, text = REASON_DOUBLE_MIGRATION, REASON_TEXT[REASON_DOUBLE_MIGRATION]
            job_id = _reject(conn, partition_id=partition_id, from_tier=from_tier, to_tier=to_tier,
                             from_prefix=from_prefix, reason_code=code, reason=text)
            conn.commit()
            raise HTTPException(409, detail={"code": code, "reason": text, "job_id": job_id})
        job_id = cur.lastrowid
        _audit(conn, partition_id=partition_id, event=JOB_RUNNING, job_id=job_id,
               from_tier=from_tier, to_tier=to_tier)
        return {
            "job_id": job_id, "status": JOB_RUNNING,
            "from_tier": from_tier, "to_tier": to_tier,
            "from_prefix": from_prefix, "to_prefix": to_prefix,
            "snapshot_tier": from_tier, "snapshot_prefix": from_prefix,
        }


def _rewrite_object_keys(conn, partition_id: int, old_prefix: str, new_prefix: str):
    """目录归属随落点同刷：分区前缀、素材对象键、目录清单对象键全部换前缀。

    与温层更新处于同一事务，不存在「温层已改、目录未跟」的半截态。
    """
    conn.execute("UPDATE partitions SET object_prefix=? WHERE id=?", (new_prefix, partition_id))
    clips = conn.execute(
        "SELECT id, object_key FROM clips WHERE partition_id=?", (partition_id,)
    ).fetchall()
    for c in clips:
        new_key = new_prefix + c["object_key"][len(old_prefix):]
        conn.execute("UPDATE clips SET object_key=? WHERE id=?", (new_key, c["id"]))
        conn.execute(
            "UPDATE inventory_objects SET object_key=? WHERE object_key=?",
            (new_key, c["object_key"]),
        )


def finish_migrate(job_id: int, success: bool = True):
    with db() as conn:
        j = conn.execute("SELECT * FROM migrate_jobs WHERE id=?", (job_id,)).fetchone()
        if not j:
            raise HTTPException(404, detail="迁移单不存在")
        if j["status"] != JOB_RUNNING:
            code, text = REASON_NOT_RUNNING, REASON_TEXT[REASON_NOT_RUNNING]
            raise HTTPException(400, detail={"code": code, "reason": text})

        # 状态翻转闸门：并发「完成」同一单时，只有一个事务能把执行中翻走，
        # 另一个 rowcount=0 整笔回滚，杜绝对象键被二次改写的半截态。
        flipped = conn.execute(
            "UPDATE migrate_jobs SET finished_at=? WHERE id=? AND status='执行中'",
            (now(), job_id),
        ).rowcount
        if flipped == 0:
            code, text = REASON_NOT_RUNNING, REASON_TEXT[REASON_NOT_RUNNING]
            raise HTTPException(409, detail={"code": code, "reason": text})

        p = partition_row(conn, j["partition_id"])
        if success:
            # 同成败：温层列 + 目录前缀 + 对象键在同一事务提交，任一失败整体回滚到迁前快照。
            conn.execute("UPDATE partitions SET tier=? WHERE id=?", (j["to_tier"], p["id"]))
            _rewrite_object_keys(conn, p["id"], j["from_prefix"], j["to_prefix"])
            # 同路径谓词闸门③：提交前重放校验——新温层必须能重放出新前缀，
            # 单据 to_tier/to_prefix 与分区现状三者一致，对不上则抛错整笔回滚，禁止半截提交。
            fresh = partition_row(conn, p["id"])
            if not (
                same_path_predicate(fresh["tier"], fresh["object_prefix"])
                and fresh["tier"] == j["to_tier"]
                and fresh["object_prefix"] == j["to_prefix"]
            ):
                raise HTTPException(
                    500,
                    detail={
                        "code": REASON_PATH_DIVERGED,
                        "reason": REASON_TEXT[REASON_PATH_DIVERGED],
                        "job_id": job_id,
                    },
                )
            conn.execute(
                "UPDATE migrate_jobs SET status=? WHERE id=?",
                (JOB_DONE, job_id),
            )
            _audit(conn, partition_id=p["id"], event=JOB_DONE, job_id=job_id,
                   from_tier=j["from_tier"], to_tier=j["to_tier"])
            return {
                "job_id": job_id, "status": JOB_DONE,
                "tier": j["to_tier"], "object_prefix": j["to_prefix"],
            }

        # 失败回滚：温层与目录一律恢复到迁前快照（执行期本未改，此处为显式兜底，杜绝半截态）。
        conn.execute(
            "UPDATE partitions SET tier=?, object_prefix=? WHERE id=?",
            (j["snapshot_tier"], j["snapshot_prefix"], p["id"]),
        )
        # 同路径谓词闸门④：回滚后的温层∪前缀也必须重放同一路径，否则不留半截态直接抛错回滚。
        fresh = partition_row(conn, p["id"])
        if not same_path_predicate(fresh["tier"], fresh["object_prefix"]):
            raise HTTPException(
                500,
                detail={
                    "code": REASON_PATH_DIVERGED,
                    "reason": REASON_TEXT[REASON_PATH_DIVERGED],
                    "job_id": job_id,
                },
            )
        conn.execute(
            "UPDATE migrate_jobs SET status=?, note=? WHERE id=?",
            (JOB_FAILED, "执行失败，温层与目录回滚到迁前快照", job_id),
        )
        _audit(conn, partition_id=p["id"], event=JOB_FAILED, job_id=job_id,
               from_tier=j["from_tier"], to_tier=j["to_tier"],
               reason_code="execute-failed", reason="执行失败，已回滚到迁前快照")
        return {
            "job_id": job_id, "status": JOB_FAILED,
            "tier": j["snapshot_tier"], "object_prefix": j["snapshot_prefix"],
        }


def rule_book():
    """递进规则页数据源：与 migration_rule 同一谓词，可逐对重放。"""
    matrix = []
    for frm in ("热档", "温档", "冷档"):
        for to in ("热档", "温档", "冷档"):
            r = migration_rule(frm, to)
            matrix.append({
                "from_tier": frm,
                "to_tier": to,
                "allowed": r["allowed"],
                "gap": r["gap"],
                "reason_code": r["reason_code"],
                "reason": r["reason"],
            })
    return {
        "policy": "以相邻一级为准：仅接受级差为一级的迁移，跨两级整笔拒绝，不得一笔直达",
        "tier_order": TIER_ORDER,
        "tier_prefixes": TIER_PREFIXES,
        "max_abs_gap": 1,
        "matrix": matrix,
    }

