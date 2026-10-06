"""Exercise the real request path with temporary storage and a mocked executor."""
import tempfile
import time
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main


class GuitarJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="chordlab-guitar-test-")
        self.root = Path(self.temp.name)
        self.jobs = self.root / "jobs"
        self.jobs.mkdir()
        self.patches = [
            patch.object(main, "DATA", self.root),
            patch.object(main, "DB_PATH", self.root / "catalog.sqlite3"),
            patch.object(main, "JOBS", self.jobs),
            patch.object(main, "SECRET", "guitar-test-secret-" * 3),
            patch.object(main, "ensure_public_url", side_effect=lambda value: value),
            patch.object(main.executor, "submit"),
        ]
        for p in self.patches:
            p.start()
        main.init_db()
        self.client = TestClient(main.app)
        self.client.cookies.set(main.COOKIE, main.sign_session("tester", "local", int(time.time()) + 3600))

    def tearDown(self):
        self.client.close()
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def test_direct_guitar_is_persisted_and_disables_separation(self):
        response = self.client.post("/api/jobs", data={
            "url": "https://youtu.be/9GIRqZfa1Gg", "pure_guitar": "true",
            "separate_stems": "true", "stem_midi": "true", "separation_model": "htdemucs_6s",
        }, headers={"Origin": "http://testserver"})
        self.assertEqual(response.status_code, 202, response.text)
        with main.db() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (response.json()["id"],)).fetchone()
        self.assertEqual(row["pure_guitar"], 1)
        self.assertEqual(row["separate_stems"], 0)
        self.assertEqual(row["stem_midi"], 0)
        self.assertTrue(main.executor.submit.call_args.args[-1])

    def test_existing_database_migration_keeps_existing_jobs(self):
        with main.db() as connection:
            connection.execute("INSERT INTO jobs(id,title,source,status,created_at,updated_at) VALUES ('old','old','old','done',1,1)")
            connection.execute("ALTER TABLE jobs DROP COLUMN pure_guitar")
        main.init_db()
        with main.db() as connection:
            row = connection.execute("SELECT pure_guitar FROM jobs WHERE id='old'").fetchone()
        self.assertEqual(row[0], 0)

    def test_restart_keeps_direct_guitar_mode_in_queue(self):
        with main.db() as connection:
            connection.execute("INSERT INTO jobs(id,title,source,source_kind,status,pure_guitar,created_at,updated_at) VALUES ('pending','pending','https://youtu.be/9GIRqZfa1Gg','url','queued',1,1,1)")
        with patch.object(main, "USERNAME", "tester"), patch.object(main, "PASSWORD", "test"), patch.object(main, "STORAGE_MOUNT", None):
            main.startup()
        self.assertTrue(main.executor.submit.call_args.args[-1])

    def test_direct_pipeline_transcribes_original_and_publishes_guitar_midi(self):
        job_id = "direct-pipeline"
        directory = self.jobs / job_id
        directory.mkdir()
        original = directory / "download.wav"
        original.touch()
        with main.db() as connection:
            connection.execute("INSERT INTO jobs(id,title,source,status,pure_guitar,created_at,updated_at) VALUES (?,?,?,'queued',1,1,1)", (job_id, "test", "test"))

        def fake_command(command, **kwargs):
            if any("basic_pitch_worker.py" in arg for arg in command):
                Path(command[3]).write_text(json.dumps({"notes": [], "chords": [], "note_count": 0}))
            elif any("chordino_worker.py" in arg for arg in command):
                Path(command[3]).write_text(json.dumps({"chords": []}))

        with patch.object(main, "download_url", return_value=(original, "test")), \
             patch.object(main, "normalize_audio", return_value=9.0), \
             patch.object(main, "run_command", side_effect=fake_command), \
             patch.object(main, "separate_audio") as separation, \
             patch.object(main, "transcribe_guitar_tab", return_value=(["guitar"], {})) as guitar:
            main.process_job(job_id, "url", "test", pure_guitar=True)
            separation.assert_not_called()
            guitar.assert_called_once_with(job_id, directory, direct_source=original)
        with main.db() as connection:
            row = connection.execute("SELECT status,result FROM jobs WHERE id=?", (job_id,)).fetchone()
        self.assertEqual(row["status"], "done")
        result = json.loads(row["result"])
        self.assertEqual(result["guitar_tab"], {"profile": "guitar_v2", "source": "original"})
        self.assertIn("guitar", result["separation"]["midi_stems"])


if __name__ == "__main__":
    unittest.main()
