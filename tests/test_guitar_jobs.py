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
            patch.object(main, "schedule_download"),
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
            elif any("rhythm_worker.py" in arg for arg in command):
                Path(command[3]).write_text(json.dumps({"bpm": 120, "beats": []}))

        with patch.object(main, "download_url", return_value=(original, "test")), \
             patch.object(main, "normalize_audio", return_value=9.0), \
             patch.object(main, "run_command", side_effect=fake_command), \
             patch.object(main, "separate_audio") as separation, \
             patch.object(main, "transcribe_guitar_tab", return_value=(["guitar"], {})) as guitar:
            main.process_job(job_id, "url", "test", pure_guitar=True)
            separation.assert_not_called()
            guitar.assert_called_once_with(job_id, directory, direct_source=directory / "audio.wav")
        with main.db() as connection:
            row = connection.execute("SELECT status,result FROM jobs WHERE id=?", (job_id,)).fetchone()
        self.assertEqual(row["status"], "done")
        result = json.loads(row["result"])
        self.assertEqual(result["guitar_tab"], {"profile": "guitar_v2", "source": "original", "status": "done"})
        self.assertIn("guitar", result["separation"]["midi_stems"])

    def test_dual_engine_uses_same_audio_and_failure_is_nonfatal(self):
        for fail in (False, True):
            with self.subTest(btc_failure=fail):
                job_id = "comparison-failed" if fail else "comparison-good"
                directory = self.jobs / job_id
                directory.mkdir()
                (directory / "source.wav").touch()
                with main.db() as connection:
                    connection.execute("INSERT INTO jobs(id,title,source,status,created_at,updated_at) VALUES (?,?,?,'queued',1,1)", (job_id, "test", "test"))
                inputs = {}
                def fake_command(command, **kwargs):
                    worker = Path(command[1]).name
                    if worker == "basic_pitch_worker.py":
                        payload = {"notes": [], "chords": [], "note_count": 0}
                    elif worker == "chordino_worker.py":
                        inputs["chordino"] = command[2]
                        payload = {"chords": [{"start": 0, "end": 10, "chord": "C"}]}
                    elif worker == "btc_worker.py":
                        inputs["btc"] = command[2]
                        if fail:
                            raise RuntimeError("simulated BTC failure")
                        payload = {"chords": [{"start": 0, "end": 10, "chord": "Cmaj7"}], "elapsed_seconds": 1, "engine": "btc_ismir19_170"}
                    else:
                        payload = {"bpm": 120, "beats": []}
                    Path(command[3]).write_text(json.dumps(payload))
                with patch.object(main, "normalize_audio", return_value=10), \
                     patch.object(main, "run_command", side_effect=fake_command), \
                     patch.object(main, "BTC_ENABLED", True), \
                     patch.object(main, "BTC_PYTHON", Path(__file__)), \
                     patch.object(main, "BTC_MODEL", Path(__file__)):
                    main.process_job(job_id, "upload", "test")
                with main.db() as connection:
                    row = connection.execute("SELECT status,result FROM jobs WHERE id=?", (job_id,)).fetchone()
                result = json.loads(row["result"])
                self.assertEqual(row["status"], "done")
                self.assertEqual(inputs["btc"], inputs["chordino"])
                self.assertEqual(result["active_method"], "chordino" if fail else "ensemble")
                if fail:
                    self.assertNotIn("ensemble", result["methods"])
                    self.assertIsNotNone(result["btc_error"])
                else:
                    self.assertEqual(result["methods"]["ensemble"][0]["chord"], "C")
                    self.assertEqual(result["methods"]["ensemble"][0]["comparison"]["status"], "detail")

    def test_editing_comparison_preserves_original_and_clears_only_changed_hint(self):
        job_id = "c" * 32
        timeline = [{"start": 0, "end": 5, "chord": "C", "comparison": {"status": "detail", "candidates": [{"chord": "Cmaj7", "share": 1}]}},
                    {"start": 5, "end": 10, "chord": "G", "comparison": {"status": "agree", "candidates": [{"chord": "G", "share": 1}]}}]
        result = {"active_method": "ensemble", "methods": {"ensemble": timeline, "chordino": timeline, "btc": []}, "chord_comparison": {"review_segments": 1}}
        with main.db() as connection:
            connection.execute("INSERT INTO jobs(id,title,source,status,duration,result,owner,created_at,updated_at) VALUES (?,?,?,'done',10,?,'tester',1,1)",
                               (job_id, "test", "test", json.dumps(result)))
        changed = [{"start": 0, "end": 5, "chord": "Cmaj7"}, {"start": 5, "end": 10, "chord": "G"}]
        response = self.client.put(f"/api/jobs/{job_id}/chords", json={"method": "ensemble", "chords": changed, "revision": 0}, headers={"Origin": "http://testserver"})
        self.assertEqual(response.status_code, 200, response.text)
        with main.db() as connection:
            saved = json.loads(connection.execute("SELECT result FROM jobs WHERE id=?", (job_id,)).fetchone()[0])
        self.assertEqual(saved["methods"]["chordino"][0]["chord"], "C")
        self.assertTrue(saved["methods"]["ensemble"][0]["manual"])
        self.assertNotIn("comparison", saved["methods"]["ensemble"][0])
        self.assertEqual(saved["methods"]["ensemble"][1]["comparison"]["status"], "agree")
        self.assertEqual(saved["chord_comparison"]["review_segments"], 0)

    def test_separated_pipeline_skips_weak_tracks_before_midi(self):
        job_id = "gated-pipeline"
        directory = self.jobs / job_id
        directory.mkdir()
        source = directory / "source.wav"
        source.touch()
        with main.db() as connection:
            connection.execute("INSERT INTO jobs(id,title,source,status,created_at,updated_at) VALUES (?,?,?,'queued',1,1)", (job_id, "test", "test"))

        def fake_command(command, **kwargs):
            if any("basic_pitch_worker.py" in arg for arg in command):
                Path(command[3]).write_text(json.dumps({"notes": [], "chords": [], "note_count": 0}))
            elif any("chordino_worker.py" in arg for arg in command):
                Path(command[3]).write_text(json.dumps({"chords": []}))
            elif any("rhythm_worker.py" in arg for arg in command):
                Path(command[3]).write_text(json.dumps({"bpm": 120, "beats": []}))

        with patch.object(main, "normalize_audio", return_value=9.0), \
             patch.object(main, "run_command", side_effect=fake_command), \
             patch.object(main, "separate_audio", return_value=(source, ["original", "harmony", "guitar", "piano"])), \
             patch.object(main, "detect_activity", return_value={"piano": {"active": False}}), \
             patch.object(main, "transcribe_stem_midis", return_value=(["guitar"], {})) as midi:
            main.process_job(job_id, "upload", "test", separate_stems=True, separation_model="htdemucs_6s", stem_midi=True)
        self.assertEqual(midi.call_args.args[2], ["original", "harmony", "guitar"])
        with main.db() as connection:
            row = connection.execute("SELECT result,status FROM jobs WHERE id=?", (job_id,)).fetchone()
        self.assertEqual(row["status"], "done")
        separation = json.loads(row["result"])["separation"]
        self.assertNotIn("piano", separation["stems"])
        self.assertIn("piano", separation["all_stems"])

    def test_hidden_audio_remains_accessible_but_unknown_track_is_rejected(self):
        directory = self.jobs / "hidden-track"
        (directory / "stems").mkdir(parents=True)
        (directory / "stems" / "piano.wav").write_bytes(b"test")
        result = {"separation": {"stems": ["original"], "all_stems": ["original", "piano"]}}
        with main.db() as connection:
            connection.execute("INSERT INTO jobs(id,title,source,status,owner,result,created_at,updated_at) VALUES ('hidden-track','test','test','done','tester',?,1,1)", (json.dumps(result),))
        self.assertEqual(self.client.get("/api/jobs/hidden-track/audio/piano").status_code, 200)
        self.assertEqual(self.client.get("/api/jobs/hidden-track/audio/unknown").status_code, 404)
        self.assertEqual(self.client.get("/api/jobs/hidden-track/audio-mix?tracks=original,unknown").status_code, 400)

    def test_review_mode_is_persisted_and_passed_to_queue(self):
        response = self.client.post("/api/jobs", data={"url": "https://youtu.be/9GIRqZfa1Gg", "separate_stems": "true",
                                   "separation_model": "htdemucs_6s", "review_guitar": "true"}, headers={"Origin": "http://testserver"})
        self.assertEqual(response.status_code, 202)
        with main.db() as c:
            self.assertEqual(c.execute("SELECT review_guitar FROM jobs WHERE id=?", (response.json()["id"],)).fetchone()[0], 1)
        self.assertTrue(main.executor.submit.call_args.kwargs["review_guitar"])

    def test_review_pipeline_defers_guitar_transcription(self):
        job_id = "review-pipeline"
        directory = self.jobs / job_id
        directory.mkdir()
        source = directory / "source.wav"
        source.touch()
        with main.db() as c:
            c.execute("INSERT INTO jobs(id,title,source,status,created_at,updated_at) VALUES (?,?,?,'queued',1,1)", (job_id, "test", "test"))
        def fake_command(command, **kwargs):
            if any("worker.py" in arg for arg in command):
                Path(command[3]).write_text(json.dumps({"notes": [], "chords": [], "note_count": 0, "bpm": 120, "beats": []}))
        with patch.object(main, "normalize_audio", return_value=9.0), \
             patch.object(main, "run_command", side_effect=fake_command), \
             patch.object(main, "detect_activity", return_value={}), \
             patch.object(main, "separate_audio", return_value=(source, ["original", "harmony", "guitar"])), \
             patch.object(main, "transcribe_guitar_tab") as guitar:
            main.process_job(job_id, "upload", "test", separate_stems=True, separation_model="htdemucs_6s", review_guitar=True)
            guitar.assert_not_called()
        with main.db() as c:
            row = c.execute("SELECT result,status FROM jobs WHERE id=?", (job_id,)).fetchone()
        self.assertEqual(row["status"], "done")
        self.assertEqual(json.loads(row["result"])["guitar_tab"]["status"], "pending")

    def test_original_review_mode_defers_and_failure_is_retryable(self):
        for review in (True, False):
            with self.subTest(review=review):
                job_id = f"original-review-{review}"
                directory = self.jobs / job_id
                directory.mkdir()
                (directory / "source.webm").touch()
                with main.db() as c:
                    c.execute("INSERT INTO jobs(id,title,source,status,pure_guitar,created_at,updated_at) VALUES (?,?,?,'queued',1,1,1)", (job_id, "test", "test"))
                def fake_command(command, **kwargs):
                    if any("worker.py" in arg for arg in command):
                        Path(command[3]).write_text(json.dumps({"notes": [], "chords": [], "note_count": 0, "bpm": 120, "beats": []}))
                with patch.object(main, "normalize_audio", return_value=9.0), \
                     patch.object(main, "run_command", side_effect=fake_command), \
                     patch.object(main, "BTC_ENABLED", False), \
                     patch.object(main, "transcribe_guitar_tab", return_value=([], {"guitar": "轉錄失敗"})) as guitar:
                    main.process_job(job_id, "upload", "test", pure_guitar=True, review_guitar=review)
                    if review:
                        guitar.assert_not_called()
                    else:
                        guitar.assert_called_once_with(job_id, directory, direct_source=directory / "audio.wav")
                with main.db() as c:
                    result = json.loads(c.execute("SELECT result FROM jobs WHERE id=?", (job_id,)).fetchone()[0])
                self.assertEqual(result["guitar_tab"]["source"], "original")
                self.assertEqual(result["guitar_tab"]["status"], "pending" if review else "failed")


if __name__ == "__main__":
    unittest.main()
