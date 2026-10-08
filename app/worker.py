"""Single-host durable analysis consumer, independent of HTTP process lifetime.

The advisory lock keeps exactly one consumer for this SQLite/HDD installation.
Queue rows are written by the web processes and polled here, so a web crash
cannot strand a submission between database commit and an in-memory submit.
"""
from __future__ import annotations

import fcntl
import logging
import time

from app import main

LOG = logging.getLogger(__name__)


def recover_interrupted() -> None:
    """Only the process holding worker.lock may reset abandoned work."""
    with main.db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE jobs SET status='cancelled',message='已取消' WHERE status='working' AND cancel_requested=1")
        connection.execute("UPDATE jobs SET status='queued',progress=2,message='分析服務重啟，已重新加入佇列' WHERE status='working'")
        connection.execute("UPDATE guitar_tasks SET status='queued' WHERE status='working'")


def next_task() -> tuple[str, str] | None:
    with main.db() as connection:
        row = connection.execute("""
            SELECT kind,id FROM (
                SELECT 'song' AS kind,id,created_at FROM jobs WHERE status='queued' AND cancel_requested=0
                UNION ALL
                SELECT 'tab' AS kind,job_id AS id,created_at FROM guitar_tasks WHERE status='queued'
            ) ORDER BY created_at,id LIMIT 1
        """).fetchone()
        return (row["kind"], row["id"]) if row else None


def run_once() -> bool:
    task = next_task()
    if not task:
        return False
    kind, job_id = task
    try:
        if kind == "tab":
            main.process_guitar_task(job_id)
        else:
            with main.db() as connection:
                row = connection.execute("SELECT * FROM jobs WHERE id=? AND status='queued'", (job_id,)).fetchone()
            if row:
                main.process_job(
                    job_id, row["source_kind"], row["source"], bool(row["separate_stems"]),
                    row["separation_model"], bool(row["stem_midi"]), bool(row["transcribe_lyrics"]),
                    bool(row["pure_guitar"]), review_guitar=bool(row["review_guitar"]),
                )
    except Exception:
        LOG.exception("Uncaught %s processing error for %s", kind, job_id)
        with main.db() as connection:
            if kind == "tab":
                connection.execute("UPDATE guitar_tasks SET status='failed',updated_at=? WHERE job_id=? AND status IN ('queued','working')", (int(time.time()), job_id))
            else:
                connection.execute("UPDATE jobs SET status='failed',message='分析服務發生未預期錯誤',updated_at=? WHERE id=? AND status IN ('queued','working')", (int(time.time()), job_id))
    return True


def serve() -> None:
    if main.EMBEDDED_WORKER:
        raise RuntimeError("Dedicated worker requires CHORDLAB_EMBEDDED_WORKER=false")
    main.startup()  # identical credential, mount and tool validation as HTTP
    main.DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (main.DATA / "worker.lock").open("a+b") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another ChordLab analysis worker is already running") from exc
        recover_interrupted()
        LOG.warning("ChordLab analysis worker ready")
        while True:
            try:
                if not run_once():
                    time.sleep(2)
            except Exception:
                LOG.exception("Uncaught analysis worker error")
                time.sleep(5)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    serve()
