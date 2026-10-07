"""Small end-to-end checks for session, edit, and upload boundaries."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main


class SafetyRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="chordlab-safety-")
        self.root = Path(self.temp.name)
        self.jobs = self.root / "jobs"
        self.patches = [
            patch.object(main, "DATA", self.root),
            patch.object(main, "DB_PATH", self.root / "catalog.sqlite3"),
            patch.object(main, "JOBS", self.jobs),
            patch.object(main, "SECRET", "safety-test-secret-" * 3),
        ]
        for item in self.patches:
            item.start()
        main.init_db()
        self.client = TestClient(main.app)
        self.token = main.sign_session("alice@example.com", "google", int(time.time()) + 3600)
        self.client.cookies.set(main.COOKIE, self.token)
        self.headers = {"Origin": "http://testserver"}

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_logout_revokes_the_specific_cookie(self):
        second = main.sign_session("alice@example.com", "google", int(time.time()) + 3600)
        self.assertIsNotNone(main.session_identity(self.token))
        self.assertEqual(self.client.post("/logout", headers=self.headers, follow_redirects=False).status_code, 303)
        self.assertIsNone(main.session_identity(self.token))
        self.assertIsNotNone(main.session_identity(second))

    def test_logout_all_revokes_all_cookies(self):
        second = main.sign_session("alice@example.com", "google", int(time.time()) + 3600)
        self.assertEqual(self.client.post("/api/logout-all", headers=self.headers).status_code, 200)
        self.assertIsNone(main.session_identity(self.token))
        self.assertIsNone(main.session_identity(second))

    def test_chord_revision_rejects_stale_writer_and_can_restore(self):
        job_id = "a" * 32
        result = {"active_method": "chordino", "methods": {"chordino": [
            {"start": 0, "end": 10, "chord": "C", "confidence": .8, "review_note": "original"}]}}
        with main.db() as connection:
            connection.execute("""INSERT INTO jobs(id,title,source,status,duration,result,owner,created_at,updated_at)
                VALUES (?,?,?,'done',10,?,'alice@example.com',1,1)""",
                (job_id, "song", "test", json.dumps(result)))
        path = f"/api/jobs/{job_id}/chords"
        first = self.client.put(path, headers=self.headers,
            json={"method": "chordino", "revision": 0,
                  "chords": [{"start": 0, "end": 10, "chord": "G"}]})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["revision"], 1)
        stale = self.client.put(path, headers=self.headers,
            json={"method": "chordino", "revision": 0,
                  "chords": [{"start": 0, "end": 10, "chord": "Am"}]})
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(self.client.get(path + "/history", params={"method": "chordino"}).json()["history"][0]["revision"], 0)
        restored = self.client.post(path + "/restore", headers=self.headers,
            json={"method": "chordino", "revision": 1, "restore_revision": 0})
        self.assertEqual(restored.status_code, 200, restored.text)
        saved = self.client.get(f"/api/jobs/{job_id}").json()["result"]
        self.assertEqual(saved["methods"]["chordino"][0]["chord"], "C")
        self.assertEqual(saved["methods"]["chordino"][0]["review_note"], "original")
        self.assertEqual(saved["chord_revisions"]["chordino"], 2)

    def test_oversize_content_length_rejected_before_multipart(self):
        with patch.object(main, "MAX_REQUEST_BODY", 8):
            response = self.client.post("/api/jobs", content=b"123456789", headers=self.headers)
        self.assertEqual(response.status_code, 413)

    def test_stream_without_content_length_is_counted(self):
        body = b'--x\r\nContent-Disposition: form-data; name="url"\r\n\r\nhttps://youtu.be/abcdefghijk\r\n--x--\r\n'
        with patch.object(main, "MAX_REQUEST_BODY", 40):
            response = self.client.post("/api/jobs", content=iter([body[:30], body[30:]]),
                headers={**self.headers, "Content-Type": "multipart/form-data; boundary=x"})
        self.assertEqual(response.status_code, 413)

    def test_global_queue_limit_rejects_before_upload(self):
        with main.db() as connection:
            connection.execute("""INSERT INTO jobs(id,title,source,status,owner,created_at,updated_at)
                VALUES ('already','song','source','queued','other@example.com',1,1)""")
        with patch.object(main, "MAX_TOTAL_PENDING", 1):
            response = self.client.post("/api/jobs", data={"url": "https://youtu.be/abcdefghijk"},
                                        headers=self.headers)
        self.assertEqual(response.status_code, 429)
        with main.db() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)

    def test_cancelled_queued_job_cannot_start_and_running_job_stops_at_checkpoint(self):
        with main.db() as connection:
            connection.execute("""INSERT INTO jobs(id,title,source,status,owner,created_at,updated_at)
                VALUES ('wait','song','source','queued','alice@example.com',1,1)""")
            connection.execute("""INSERT INTO jobs(id,title,source,status,owner,created_at,updated_at)
                VALUES ('run','song','source','working','alice@example.com',1,1)""")
        self.assertEqual(self.client.post("/api/jobs/wait/cancel", headers=self.headers).json()["status"], "cancelled")
        with patch.object(main, "normalize_audio") as normalize:
            main.process_job("wait", "upload", "source")
            normalize.assert_not_called()
        response = self.client.post("/api/jobs/run/cancel", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        with self.assertRaises(main.JobCancelled):
            main.update_job("run", progress=30)

    def test_cancel_during_worker_error_remains_cancelled(self):
        job_dir = self.jobs / "race"
        job_dir.mkdir()
        (job_dir / "source.wav").write_bytes(b"source")
        with main.db() as connection:
            connection.execute("""INSERT INTO jobs(id,title,source,status,owner,created_at,updated_at)
                VALUES ('race','song','source.wav','queued','alice@example.com',1,1)""")

        def fail_after_cancel(_source, _destination):
            with main.db() as connection:
                connection.execute("UPDATE jobs SET cancel_requested=1 WHERE id='race'")
            raise RuntimeError("interrupted")

        with patch.object(main, "normalize_audio", side_effect=fail_after_cancel):
            main.process_job("race", "upload", "source.wav")
        with main.db() as connection:
            self.assertEqual(connection.execute("SELECT status FROM jobs WHERE id='race'").fetchone()[0], "cancelled")


if __name__ == "__main__":
    unittest.main()
