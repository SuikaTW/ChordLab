"""Local browser-test server: temporary catalog, existing media read-only by workflow."""
import sqlite3
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from app import main


def run():
    fixture_id = "d0a3f98491a64544a5a86c568dc9ffef"
    with sqlite3.connect(main.DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        row = dict(connection.execute("SELECT * FROM jobs WHERE id=?", (fixture_id,)).fetchone())
    with tempfile.TemporaryDirectory(prefix="chordlab-browser-catalog-") as temporary:
        main.DATA = Path(temporary)
        main.DB_PATH = main.DATA / "catalog.sqlite3"
        main.JOBS = main.DATA / "jobs"
        main.JOBS.mkdir()
        (main.JOBS / fixture_id).symlink_to(Path("/mnt/sdb/chordlab/jobs") / fixture_id, target_is_directory=True)
        main.USERNAME = "browser-test"
        main.PASSWORD = "local-browser-test-password"
        main.SECRET = "local-browser-test-secret-" * 3
        main.SECURE_COOKIE = False
        main.GOOGLE_ENABLED = False
        main.init_db()
        row["owner"] = main.USERNAME
        row["status"] = "done"
        result = json.loads(row["result"])
        separation = result["separation"]
        separation["all_stems"] = separation.get("all_stems") or separation["stems"]
        separation["stems"] = [name for name in separation["all_stems"] if name != "piano"]
        separation["activity"] = {"piano": {"active": False}}
        row["result"] = json.dumps(result)
        pending_row = dict(row)
        pending_row["id"] = "a" * 32
        pending_row["created_at"] = row["created_at"] - 1
        pending_row["is_public"] = 0
        pending_result = json.loads(row["result"])
        pending_result["separation"]["midi_stems"] = []
        pending_result["guitar_tab"] = {"profile": None, "source": "separated", "status": "pending"}
        pending_row["result"] = json.dumps(pending_result)
        (main.JOBS / pending_row["id"]).symlink_to(Path("/mnt/sdb/chordlab/jobs") / fixture_id, target_is_directory=True)
        mobile_pending_row = dict(pending_row)
        mobile_pending_row["id"] = "b" * 32
        mobile_pending_row["created_at"] = row["created_at"] - 2
        (main.JOBS / mobile_pending_row["id"]).symlink_to(Path("/mnt/sdb/chordlab/jobs") / fixture_id, target_is_directory=True)
        # Exercise real durable task/HTTP/UI code, reusing existing transcription
        # read-only instead of running Basic Pitch or modifying saved media.
        main.transcribe_guitar_tab = lambda *args, **kwargs: (["guitar"], {})
        with main.db() as connection:
            columns = ",".join(row)
            placeholders = ",".join("?" for _ in row)
            connection.execute(f"INSERT INTO jobs ({columns}) VALUES ({placeholders})", list(row.values()))
            connection.execute(f"INSERT INTO jobs ({columns}) VALUES ({placeholders})", list(pending_row.values()))
            connection.execute(f"INSERT INTO jobs ({columns}) VALUES ({placeholders})", list(mobile_pending_row.values()))
        uvicorn.run(main.app, host="127.0.0.1", port=8790, access_log=False, log_level="warning")


if __name__ == "__main__":
    run()
