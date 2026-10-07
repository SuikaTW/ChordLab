import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from app import main
from app.guitar_engines import paths


class GuitarEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [patch.object(main, "DATA", self.root), patch.object(main, "DB_PATH", self.root / "db.sqlite3"),
            patch.object(main, "JOBS", self.root / "jobs"), patch.object(main, "SECRET", "engines-test-" * 4),
            patch.object(main.executor, "submit"), patch.object(main, "guitar_engine_available", return_value=True)]
        for item in self.patches:
            item.start()
        main.init_db()
        self.client = TestClient(main.app)
        self.client.cookies.set(main.COOKIE, main.sign_session("alice@example.com", "google", int(time.time()) + 3600))
        self.directory = main.JOBS / "song"
        (self.directory / "stem-midi").mkdir(parents=True)
        (self.directory / "audio.wav").write_bytes(b"audio")
        self.baseline = {"guitar_tab": {"source": "original", "status": "done", "profile": "guitar_v2"},
            "methods": {"chordino": [{"chord": "C", "start": 0, "end": 10}]},
            "separation": {"stems": ["original"], "midi_stems": ["guitar"]}}
        for path in paths(self.directory, "basic_pitch"):
            path.write_text(json.dumps({"notes": [{"midi": 64}], "profile": "guitar_v2"}) if path.suffix == ".json" else "midi")
        with main.db() as connection:
            connection.execute("INSERT INTO jobs(id,title,source,status,owner,result,duration,pure_guitar,is_public,created_at,updated_at) VALUES ('song','song','test','done','alice@example.com',?,10,1,1,1,1)", (json.dumps(self.baseline),))

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def post(self, engine):
        return self.client.post(f"/api/jobs/song/guitar-analysis?engine={engine}", headers={"Origin": "http://testserver"})

    def test_experiments_are_durable_idempotent_and_cannot_race(self):
        self.assertEqual(self.post("gaps").json()["status"], "queued")
        self.assertEqual(self.post("gaps").json()["status"], "queued")
        self.assertEqual(self.post("tabcnn").status_code, 409)
        self.assertEqual(main.executor.submit.call_count, 1)
        with main.db() as connection:
            self.assertEqual(connection.execute("SELECT engine FROM guitar_tasks").fetchone()[0], "gaps")
            connection.execute("UPDATE guitar_tasks SET status='working'")
        with patch.object(main, "USERNAME", "test"), patch.object(main, "PASSWORD", "test"), patch.object(main, "STORAGE_MOUNT", None):
            main.startup()
        with main.db() as connection:
            self.assertEqual(connection.execute("SELECT engine,status FROM guitar_tasks").fetchone()[0], "gaps")

    def test_gaps_completion_leaves_baseline_chords_and_personal_tab_unchanged(self):
        self.post("gaps")
        original = paths(self.directory, "basic_pitch")[0].read_bytes()
        with main.db() as connection:
            connection.execute("INSERT INTO user_tabs(job_id,viewer,revision,document,updated_at) VALUES ('song','alice',1,'{}',1)")
        def fake_command(command, **kwargs):
            self.assertIn("guitar_worker.py", command[1])
            self.assertIn(str(self.directory / "audio.wav"), command)
            Path(command[3]).write_text(json.dumps({"profile": "guitar_gaps_v1", "notes": [{"start": 0, "end": .5, "midi": 64}]}))
            Path(command[4]).write_bytes(b"midi")
        with patch.object(main, "run_command", side_effect=fake_command):
            main.process_guitar_task("song")
        self.assertEqual(paths(self.directory, "basic_pitch")[0].read_bytes(), original)
        with main.db() as connection:
            result = json.loads(connection.execute("SELECT result FROM jobs").fetchone()[0])
            self.assertEqual(connection.execute("SELECT document FROM user_tabs").fetchone()[0], "{}")
        self.assertEqual(result["guitar_tab"]["profile"], "guitar_v2")
        self.assertEqual(result["guitar_tab"]["variants"]["gaps"]["status"], "done")
        self.assertEqual(result["methods"], self.baseline["methods"])
        self.assertEqual(self.client.get("/api/jobs/song/notes/guitar?engine=gaps").json()["notes"][0]["midi"], 64)
        self.assertEqual(self.client.get("/api/jobs/song/guitar-midi/gaps").status_code, 200)
        self.assertEqual(self.post("gaps").json()["status"], "done")
        self.assertEqual(self.post("tabcnn").json()["status"], "queued")

    def test_failure_of_experiment_does_not_break_ready_baseline(self):
        self.post("tabcnn")
        with patch.object(main, "run_command", side_effect=RuntimeError("model failure")):
            main.process_guitar_task("song")
        self.assertEqual(self.client.get("/api/jobs/song/guitar-analysis?engine=tabcnn").json()["status"], "failed")
        self.assertEqual(self.client.get("/api/jobs/song/guitar-analysis").json()["status"], "done")
        self.assertEqual(self.client.get("/api/jobs/song/notes/guitar").status_code, 200)

    def test_switching_failed_engines_cannot_bypass_daily_quota(self):
        with patch.object(main, "DAILY_JOB_LIMIT", 2):
            self.assertEqual(self.post("gaps").status_code, 202)
            with main.db() as connection:
                connection.execute("UPDATE guitar_tasks SET status='failed'")
            self.assertEqual(self.post("tabcnn").status_code, 202)
            with main.db() as connection:
                connection.execute("UPDATE guitar_tasks SET status='failed'")
            self.assertEqual(self.post("gaps").status_code, 429)
        with main.db() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM guitar_submissions").fetchone()[0], 2)

    def test_failure_status_survives_work_on_another_engine(self):
        self.post("tabcnn")
        with patch.object(main, "run_command", side_effect=RuntimeError("model failure")):
            main.process_guitar_task("song")
        self.post("gaps")
        self.assertEqual(self.client.get("/api/jobs/song/guitar-analysis?engine=tabcnn").json()["status"], "failed")

    def test_invalid_engine_csrf_permissions_and_uninstalled_models(self):
        self.assertEqual(self.post("../gaps").status_code, 400)
        self.assertEqual(self.client.get("/api/jobs/song/guitar-analysis?engine=unknown").status_code, 400)
        self.assertEqual(self.client.post("/api/jobs/song/guitar-analysis?engine=gaps").status_code, 403)
        with patch.object(main, "guitar_engine_available", return_value=False):
            self.assertEqual(self.post("gaps").status_code, 503)
        self.client.cookies.set(main.COOKIE, main.sign_session("bob@example.com", "google", int(time.time()) + 3600))
        self.assertEqual(self.post("gaps").status_code, 404)
        self.assertEqual(self.client.get("/api/jobs/song/guitar-midi/gaps").status_code, 404)
        with main.db() as connection:
            connection.execute("UPDATE jobs SET is_public=0")
        self.assertEqual(self.client.get("/api/jobs/song/notes/guitar?engine=gaps").status_code, 404)

    def test_hybrid_completion_preserves_original_and_passes_cached_gaps(self):
        paths(self.directory, "gaps")[0].write_text('{"notes": []}')
        self.assertEqual(self.post("hybrid").status_code, 202)
        original = paths(self.directory, "basic_pitch")[0].read_bytes()
        def fake_command(command, **kwargs):
            self.assertIn("--gaps-cache", command)
            self.assertIn("hybrid", command)
            Path(command[3]).write_text(json.dumps({"profile": "guitar_hybrid_v2", "notes": [{"start": 0, "end": .5, "midi": 64}]}))
            Path(command[4]).write_bytes(b"MThd")
        with patch.object(main, "run_command", side_effect=fake_command):
            main.process_guitar_task("song")
        self.assertEqual(paths(self.directory, "basic_pitch")[0].read_bytes(), original)
        self.assertEqual(self.client.get("/api/jobs/song/guitar-analysis?engine=hybrid").json()["status"], "done")

    def test_verified_variant_uses_existing_notes_and_preserves_originals(self):
        self.assertEqual(self.post("verified").json()["status"], "queued")
        baseline = paths(self.directory,"basic_pitch")[0].read_bytes()
        def command(args, **kwargs):
            self.assertIn("audio_verification_worker.py",args[1])
            self.assertEqual(args[args.index("--notes-cache")+1],str(paths(self.directory,"basic_pitch")[0]))
            Path(args[3]).write_text(json.dumps({"profile":"guitar_verified_v1","notes":[],"refinement":{"changed_notes":0}}))
            Path(args[4]).write_bytes(b"MThd")
            Path(args[args.index("--preview")+1]).write_bytes(b"RIFF")
        with patch.object(main,"run_command",side_effect=command):
            main.process_guitar_task("song")
        self.assertEqual(paths(self.directory,"basic_pitch")[0].read_bytes(),baseline)
        self.assertEqual(self.client.get("/api/jobs/song/guitar-analysis?engine=verified").json()["status"],"done")
        self.assertEqual(self.client.get("/api/jobs/song/verification-preview").content,b"RIFF")
        self.assertFalse((self.directory/"stem-midi/verification-references.private.json").exists())
        self.assertEqual(self.post("verified").json()["status"],"done")

    def test_verification_requires_existing_notes_and_has_no_unsafe_engine_paths(self):
        paths(self.directory,"basic_pitch")[0].unlink()
        self.assertEqual(self.post("verified").status_code,400)
        self.assertEqual(self.post("../../verified").status_code,400)

    def test_reference_audio_jobs_are_mounted_readonly_in_sandbox(self):
        other = main.JOBS / "reference"
        other.mkdir()
        reference = other / "audio.wav"
        reference.write_bytes(b"audio")
        command = [str(main.GUITAR_PYTHON),str(main.ROOT/"tools/audio_verification_worker.py"),
                   str(self.directory/"audio.wav"),"--reference-audio",str(reference)]
        with patch.object(main,"BWRAP",Path("/usr/bin/true")):
            sandbox = main.sandbox_command(command,False)
        expected = ["--ro-bind",str(other),str(other)]
        self.assertTrue(any(sandbox[index:index+3] == expected for index in range(len(sandbox))))

    def test_verification_calibration_does_not_read_other_users_private_references(self):
        self.post("verified")
        document = json.dumps({"notes":[{"start":0,"end":1,"midi":64,"edited":True}]})
        alice = main.identity_key({"sub":"alice@example.com","provider":"google"})
        bob = main.identity_key({"sub":"bob@example.com","provider":"google"})
        with main.db() as connection:
            connection.execute("INSERT OR IGNORE INTO users(id,subject,provider,display_name,is_admin,is_blocked,created_at,last_seen) VALUES (?,?,?,'Bob',0,0,1,1)",(bob,"bob@example.com","google"))
            for viewer in [alice,bob]:
                connection.execute("INSERT INTO tab_references VALUES ('song',?,'guitar',1,?,1)",(viewer,document))
        def command(args, **kwargs):
            references = json.loads(Path(args[args.index("--references")+1]).read_text())
            self.assertEqual(len(references),1)
            self.assertEqual(references[0]["notes"][0]["midi"],64)
            self.assertEqual(references[0]["audio"],str(self.directory/"audio.wav"))
            Path(args[3]).write_text(json.dumps({"profile":"guitar_verified_v1","notes":[]}))
            Path(args[4]).write_bytes(b"MThd")
            Path(args[args.index("--preview")+1]).write_bytes(b"RIFF")
        with patch.object(main,"run_command",side_effect=command):
            main.process_guitar_task("song")
        self.assertEqual(self.client.get("/api/jobs/song/guitar-analysis?engine=verified").json()["status"],"done")

    def test_chord_refinement_durable_shared_queue_and_preserved_manual_edits(self):
        (self.directory / "chordino.json").write_text(json.dumps({"chords": self.baseline["methods"]["chordino"]}))
        response = self.client.post("/api/jobs/song/chord-refinement", headers={"Origin": "http://testserver"})
        self.assertEqual(response.json()["status"], "queued")
        self.assertEqual(self.post("hybrid").status_code, 409)
        def fake_command(command, **kwargs):
            self.assertIn("harmony_worker.py", command[1])
            Path(command[4]).write_text(json.dumps({"summary": {"version": 2},
                "chords": [{"start": 0, "end": 10, "chord": "Am"}]}))
            with main.db() as connection:
                result = {**self.baseline, "active_method": "chordino", "key": {"label": "user key"},
                    "methods": {"chordino": [{"start": 0, "end": 10, "chord": "F", "manual": True}]}}
                connection.execute("UPDATE jobs SET result=?", (json.dumps(result),))
        with patch.object(main, "run_command", side_effect=fake_command):
            main.process_guitar_task("song")
        with main.db() as connection:
            result = json.loads(connection.execute("SELECT result FROM jobs").fetchone()[0])
        self.assertEqual(result["methods"]["chordino"][0]["chord"], "F")
        self.assertEqual(result["active_method"], "chordino")
        self.assertEqual(result["key"]["label"], "user key")
        self.assertEqual(result["methods"]["chord_v2"][0]["chord"], "Am")
        self.assertEqual(self.client.get("/api/jobs/song/chord-refinement").json()["status"], "done")
        refined = [{"start": 0, "end": 10, "chord": "Dm"}]
        saved = self.client.put("/api/jobs/song/chords", headers={"Origin": "http://testserver"},
            json={"method": "chord_v2", "chords": refined})
        self.assertEqual(saved.status_code, 200)
        with main.db() as connection:
            saved_result = json.loads(connection.execute("SELECT result FROM jobs").fetchone()[0])
        self.assertTrue(saved_result["methods"]["chord_v2"][0]["manual"])
        self.assertEqual(saved_result["methods"]["chordino"][0]["chord"], "F")
        before = main.executor.submit.call_count
        self.assertEqual(self.client.post("/api/jobs/song/chord-refinement", headers={"Origin": "http://testserver"}).json()["status"], "done")
        self.assertEqual(main.executor.submit.call_count, before)

    def test_chord_refinement_failure_is_nonfatal_and_permissions_apply(self):
        (self.directory / "chordino.json").write_text('{"chords": [{"chord":"C"}]}')
        self.assertEqual(self.client.post("/api/jobs/song/chord-refinement").status_code, 403)
        self.client.post("/api/jobs/song/chord-refinement", headers={"Origin": "http://testserver"})
        with patch.object(main, "run_command", side_effect=RuntimeError("refinement failure")):
            main.process_guitar_task("song")
        self.assertEqual(self.client.get("/api/jobs/song/chord-refinement").json()["status"], "failed")
        self.post("gaps")
        self.assertEqual(self.client.get("/api/jobs/song/chord-refinement").json()["status"], "failed")
        self.assertEqual(self.client.get("/api/jobs/song").json()["status"], "done")
        self.client.cookies.set(main.COOKIE, main.sign_session("bob@example.com", "google", int(time.time()) + 3600))
        self.assertEqual(self.client.post("/api/jobs/song/chord-refinement", headers={"Origin": "http://testserver"}).status_code, 404)

    def test_chord_refinement_restart_and_shared_quota(self):
        with patch.object(main, "DAILY_JOB_LIMIT", 1):
            self.client.post("/api/jobs/song/chord-refinement", headers={"Origin": "http://testserver"})
            with main.db() as connection:
                connection.execute("UPDATE guitar_tasks SET status='working'")
            with patch.object(main, "USERNAME", "test"), patch.object(main, "PASSWORD", "test"), patch.object(main, "STORAGE_MOUNT", None):
                main.startup()
            with main.db() as connection:
                task = connection.execute("SELECT engine,status FROM guitar_tasks").fetchone()
                self.assertEqual(tuple(task), ("chord_v2", "queued"))
                connection.execute("UPDATE guitar_tasks SET status='failed'")
            self.assertEqual(self.post("hybrid").status_code, 429)


if __name__ == "__main__":
    unittest.main()
