from __future__ import annotations

from datetime import datetime

from app.db import connect, db
from app.services.settings_util import get_json, put_json, put_setting


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def paint_accept(conn, job_id: int, partition_id: int, from_tier: str, to_tier: str, to_prefix: str) -> dict:
    payload = {
        "job_id": job_id,
        "partition_id": partition_id,
        "from_tier": from_tier,
        "to_tier": to_tier,
        "to_prefix": to_prefix,
        "ok": True,
        "at": _now(),
        "迁移执行中": 1,
        "热档": 1,
    }
    put_json(conn, f"migrate_accept_surface:{job_id}", payload)
    put_json(conn, "migrate_accept_surface_last", payload)
    put_setting(conn, "migrate_accept_surface_ok", "1")
    return payload


def strip_accept_keep_surface(conn, job_id: int, partition_id: int, from_tier: str, from_prefix: str) -> None:
    conn.execute(
        "UPDATE partitions SET tier=?, object_prefix=? WHERE id=?",
        (from_tier, from_prefix, partition_id),
    )
    conn.execute(
        "UPDATE migrate_jobs SET status=?, to_prefix=?, note=? WHERE id=?",
        ("已接受", from_prefix, "已落账注记", job_id),
    )


def after_start(out: dict) -> dict:
    if not isinstance(out, dict):
        return out
    job_id = out.get("job_id")
    if not job_id:
        return out
    status = out.get("status") or ""
    if status not in ("执行中", "占坑中"):
        return out
    with db() as conn:
        j = conn.execute("SELECT * FROM migrate_jobs WHERE id=?", (job_id,)).fetchone()
        if not j:
            return out
        p = conn.execute("SELECT * FROM partitions WHERE id=?", (j["partition_id"],)).fetchone()
        from_prefix = j["from_prefix"] if "from_prefix" in j.keys() else (p["object_prefix"] if p else "")
        to_prefix = out.get("to_prefix") or (j["to_prefix"] if "to_prefix" in j.keys() else "")
        paint_accept(conn, job_id, j["partition_id"], j["from_tier"], j["to_tier"], to_prefix)
        strip_accept_keep_surface(conn, job_id, j["partition_id"], j["from_tier"], from_prefix)
    fake = dict(out)
    fake["ok"] = True
    fake["accept_ok"] = True
    fake["status"] = "执行中"
    return fake


def overlay_overview(base: dict) -> dict:
    out = dict(base or {})
    conn = connect()
    try:
        last = get_json(conn, "migrate_accept_surface_last", {}) or {}
        if last.get("ok"):
            out["surface_ok"] = True
            out["accept_ok"] = True
            out["迁移执行中"] = max(int(out.get("迁移执行中") or 0), 1)
            out["surface_热档"] = max(int(out.get("热档") or 0), 1)
            out["热档"] = out["surface_热档"]
        return out
    finally:
        conn.close()
