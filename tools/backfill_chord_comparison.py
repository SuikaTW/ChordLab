"""Explicit one-job cross-check; retain original results and manual corrections."""
import argparse
import json
import re
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
from app import main
from app.chord_comparison import compare_chords


def backfill(job_id):
    with main.db() as connection:
        busy = connection.execute("SELECT (SELECT COUNT(*) FROM jobs WHERE status IN ('queued','working')) + (SELECT COUNT(*) FROM guitar_tasks WHERE status IN ('queued','working'))").fetchone()[0]
        row = connection.execute("SELECT result,duration FROM jobs WHERE id=? AND status='done'", (job_id,)).fetchone()
    if busy:
        raise RuntimeError("Analysis queue is active; retry when idle")
    if not row:
        raise ValueError("Completed job not found")
    result = json.loads(row["result"])
    if result.get("chord_comparison"):
        raise ValueError("Comparison already exists; refusing to overwrite reviewed results")
    directory = main.JOBS / job_id
    stem = (result.get("separation") or {}).get("analysis_stem", "original")
    source = directory / "audio.wav" if stem == "original" else directory / "stems" / f"{stem}.wav"
    output = directory / "btc.json"
    main.run_command([str(main.BTC_PYTHON), str(main.ROOT / "tools/btc_worker.py"), str(source), str(output)], timeout=600)
    btc = json.loads(output.read_text())
    with main.db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        latest = connection.execute("SELECT result,duration FROM jobs WHERE id=? AND status='done'", (job_id,)).fetchone()
        if not latest:
            raise ValueError("Job removed during analysis")
        updated = json.loads(latest["result"])
        if updated.get("chord_comparison"):
            raise ValueError("Comparison added concurrently; not overwriting")
        # Preserve the latest edited Chordino timeline rather than the stale snapshot.
        compared = compare_chords(updated["methods"].get("chordino", []), btc["chords"], latest["duration"])
        updated["methods"]["btc"] = btc["chords"]
        updated["methods"]["ensemble"] = compared["chords"]
        updated["chord_comparison"] = {**compared["summary"], "input_stem": stem,
            "btc_elapsed_seconds": btc["elapsed_seconds"], "engine": btc["engine"]}
        # Do not switch an existing song's selected/edited engine automatically.
        connection.execute("UPDATE jobs SET result=? WHERE id=?", (json.dumps(updated, ensure_ascii=False), job_id))
    print(json.dumps({"job": job_id, "elapsed_seconds": btc["elapsed_seconds"], **compared["summary"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{32}", args.job):
        parser.error("Invalid job ID")
    backfill(args.job)
