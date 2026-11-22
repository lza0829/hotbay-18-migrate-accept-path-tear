from __future__ import annotations
import json
from app.config import TIER_PREFIXES
from app.db import db
from app.services.core import now, prefix_for_tier


def inventory_list():
    with db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM inventory_objects ORDER BY object_key").fetchall()]


def run_verify():
    with db() as conn:
        meta = {
            r["object_key"]: r["bytes"]
            for r in conn.execute(
                '''SELECT c.object_key, c.bytes FROM clips c
                   JOIN partitions p ON p.id=c.partition_id
                   WHERE p.status IN ('在册','已过期')'''
            ).fetchall()
        }
        inv_keys = {
            r["object_key"]: r["bytes"]
            for r in conn.execute("SELECT object_key, bytes FROM inventory_objects").fetchall()
        }
        only_meta = sorted(set(meta) - set(inv_keys))
        only_inv = sorted(set(inv_keys) - set(meta))
        size_drift = sorted(
            k for k in set(meta) & set(inv_keys) if meta[k] != inv_keys[k]
        )
        drifts = []
        for k in only_meta:
            drifts.append({"对象键": k, "问题": "元数据有、目录无"})
        for k in only_inv:
            drifts.append({"对象键": k, "问题": "目录有、元数据无"})
        for k in size_drift:
            drifts.append({"对象键": k, "问题": "字节不一致"})

        # 归属前缀互证：分区现行温层必须能重放出目录前缀，素材对象键须落在该前缀下。
        # 抓住「温层已改、目录未跟」的半截态。
        for p in conn.execute(
            "SELECT * FROM partitions WHERE status IN ('在册','已过期')"
        ).fetchall():
            want_prefix = prefix_for_tier(p["tier"])
            if not p["object_prefix"].startswith(want_prefix):
                drifts.append({
                    "对象键": p["object_prefix"],
                    "问题": f"归属前缀与温层不符：{p['tier']}应以{TIER_PREFIXES[p['tier']]}/开头",
                })
            for c in conn.execute(
                "SELECT object_key FROM clips WHERE partition_id=?", (p["id"],)
            ).fetchall():
                if not c["object_key"].startswith(want_prefix):
                    drifts.append({
                        "对象键": c["object_key"],
                        "问题": f"素材未落在{p['tier']}归属前缀{want_prefix}下",
                    })

        status = "一致" if not drifts else "漂移"
        cur = conn.execute(
            "INSERT INTO verify_runs(status, drift_count, detail, created_at) VALUES (?,?,?,?)",
            (status, len(drifts), json.dumps(drifts, ensure_ascii=False), now()),
        )
        return {
            "run_id": cur.lastrowid,
            "status": status,
            "drift_count": len(drifts),
            "drifts": drifts,
            "meta_count": len(meta),
            "inventory_count": len(inv_keys),
        }


def list_verify_runs():
    with db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM verify_runs ORDER BY id DESC").fetchall()]
