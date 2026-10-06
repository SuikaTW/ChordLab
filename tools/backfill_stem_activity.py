"""Apply the conservative gate to existing completed jobs; never delete audio.

Run with the same CHORDLAB_JOBS_DIR environment as the service.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import main
from app.stem_activity import detect_activity


def run():
    with main.db() as connection:
        rows = connection.execute("SELECT id, result FROM jobs WHERE status='done'").fetchall()
    for row in rows:
        result = json.loads(row["result"] or "{}")
        separation = result.get("separation") or {}
        if not separation.get("enabled") or separation.get("activity"):
            continue
        stems = separation.get("all_stems") or separation.get("stems") or []
        activity = detect_activity(main.JOBS / row["id"], stems)
        separation.update(all_stems=stems, activity=activity,
                          stems=[name for name in stems if activity.get(name, {}).get("active", True)])
        # Optimistic update: never overwrite concurrently edited chords/metadata.
        with main.db() as connection:
            updated = connection.execute("UPDATE jobs SET result=? WHERE id=? AND result=?",
                                         (json.dumps(result, ensure_ascii=False), row["id"], row["result"]))
        hidden = [name for name, info in activity.items() if not info["active"]]
        print(row["id"], "updated" if updated.rowcount else "changed: skipped", "hidden:", hidden, flush=True)


if __name__ == "__main__":
    run()
