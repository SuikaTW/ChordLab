"""Add beat estimates to existing jobs, preserving concurrently edited results."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import main


def run():
    parser = argparse.ArgumentParser()
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--job", help="One existing completed job ID")
    target.add_argument("--all", action="store_true", help="Fill missing beat estimates, stopping if analysis is active")
    args = parser.parse_args()
    with main.db() as c:
        candidates = c.execute("SELECT id,result FROM jobs WHERE status='done' ORDER BY created_at").fetchall()
    selected = [row for row in candidates if row["id"] == args.job or args.all and not json.loads(row["result"]).get("rhythm")]
    if not selected and not args.all:
        parser.error("找不到已完成的分析")
    for row in selected:
        with main.db() as c:
            busy = c.execute("SELECT (SELECT COUNT(*) FROM jobs WHERE status IN ('queued','working')) + (SELECT COUNT(*) FROM guitar_tasks WHERE status IN ('queued','working'))").fetchone()[0]
        if busy:
            print("Analysis queue is active; stopping backfill safely", flush=True)
            break
        backfill(row["id"], row["result"])


def backfill(job_id, raw_result):
    result = json.loads(raw_result)
    directory = main.JOBS / job_id
    source = directory / "audio.wav"
    if "drums" in (result.get("separation") or {}).get("stems", []):
        source = directory / "stems/drums.wav"
    output = directory / "rhythm.json"
    main.run_command([str(main.BASIC_PYTHON), str(main.ROOT / "tools/rhythm_worker.py"), str(source), str(output)], timeout=300)
    rhythm = json.loads(output.read_text())
    with main.db() as c:
        c.execute("BEGIN IMMEDIATE")
        latest = c.execute("SELECT result FROM jobs WHERE id=?", (job_id,)).fetchone()
        if latest:
            updated = json.loads(latest["result"])
            updated["rhythm"] = rhythm
            c.execute("UPDATE jobs SET result=? WHERE id=?", (json.dumps(updated, ensure_ascii=False), job_id))
    print(json.dumps({"job": job_id, "bpm": rhythm["bpm"], "beat_count": len(rhythm["beats"])}), flush=True)


if __name__ == "__main__":
    run()
