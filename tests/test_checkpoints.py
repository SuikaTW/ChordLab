import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main
from app.checkpoints import StageCache


class CheckpointTests(unittest.TestCase):
    def test_changed_artifact_or_signature_invalidates_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            artifact = root / "audio.wav"
            artifact.write_bytes(b"good")
            cache = StageCache(root, "pipeline-a")
            self.assertTrue(cache.save("normalize", [artifact], {"duration": 10}))
            self.assertEqual(cache.read("normalize"), {"duration": 10})
            self.assertIsNone(StageCache(root, "pipeline-b").read("normalize"))
            artifact.write_bytes(b"different")
            self.assertIsNone(cache.read("normalize"))

    def test_restarted_job_skips_finished_media_and_recognition_stages(self):
        with tempfile.TemporaryDirectory(prefix="chordlab-checkpoints-") as folder:
            root = Path(folder)
            jobs = root / "jobs"
            jobs.mkdir()
            job_dir = jobs / "song"
            job_dir.mkdir()
            (job_dir / "source.wav").write_bytes(b"source")
            patches = [patch.object(main, "DATA", root),
                       patch.object(main, "DB_PATH", root / "catalog.sqlite3"),
                       patch.object(main, "JOBS", jobs), patch.object(main, "BTC_ENABLED", False)]
            for item in patches:
                item.start()
            try:
                main.init_db()
                with main.db() as db:
                    db.execute("""INSERT INTO jobs(id,title,source,status,owner,created_at,updated_at)
                        VALUES ('song','song','source.wav','queued','test',1,1)""")

                def normalize(_source, output):
                    output.write_bytes(b"normalized")
                    return 10.0

                def worker(command, **_kwargs):
                    name = Path(command[1]).name
                    output = Path(command[3])
                    if name == "basic_pitch_worker.py":
                        output.write_text(json.dumps({"notes": [], "chords": [], "note_count": 0}))
                        Path(command[4]).write_bytes(b"midi")
                    elif name == "chordino_worker.py":
                        output.write_text(json.dumps({"chords": []}))
                    elif name == "rhythm_worker.py":
                        output.write_text(json.dumps({"bpm": 120, "beats": []}))
                    else:
                        raise AssertionError(name)

                with patch.object(main, "normalize_audio", side_effect=normalize) as normalize_call, \
                     patch.object(main, "run_command", side_effect=worker) as workers:
                    main.process_job("song", "upload", "source.wav")
                    with main.db() as db:
                        db.execute("UPDATE jobs SET status='queued' WHERE id='song'")
                    main.process_job("song", "upload", "source.wav")
                    self.assertEqual(normalize_call.call_count, 1)
                    self.assertEqual(workers.call_count, 3)
                    with main.db() as db:
                        self.assertEqual(db.execute("SELECT status FROM jobs WHERE id='song'").fetchone()[0], "done")
            finally:
                for item in reversed(patches):
                    item.stop()


if __name__ == "__main__":
    unittest.main()
