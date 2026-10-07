import asyncio
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from fastapi.responses import FileResponse
import httpx
from app import main
from app.light_tasks import LightTaskPool, PoolBusy
from app.preparation import DownloadPreparation


class TabApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [patch.object(main, "DATA", self.root), patch.object(main, "DB_PATH", self.root / "catalog.sqlite3"),
                        patch.object(main, "JOBS", self.root / "jobs"), patch.object(main, "SECRET", "tab-test-secret-" * 4),
                        patch.object(main.executor, "submit")]
        for p in self.patches:
            p.start()
        main.init_db()
        self.client = TestClient(main.app)
        self.login("alice@example.com")
        self.result = {"methods": {"chordino": [{"start": 0, "end": 10, "chord": "C"}]},
                       "separation": {"stems": ["original", "guitar"], "midi_stems": []},
                       "guitar_tab": {"status": "pending", "source": "separated"}}
        with main.db() as c:
            c.execute("INSERT INTO jobs(id,title,source,status,owner,result,duration,is_public,created_at,updated_at) VALUES ('song','test','test','done','alice@example.com',?,10,1,1,1)", (json.dumps(self.result),))
        self.directory = main.JOBS / "song"
        (self.directory / "stems").mkdir(parents=True)
        (self.directory / "stems/guitar.wav").write_bytes(b"test")
        self.document = {"revision": 0, "notes": [{"index": 0, "start": 0, "end": 1, "midi": 64, "string": 5, "fret": 0}]}

    def tearDown(self):
        self.client.close()
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def login(self, subject):
        self.client.cookies.set(main.COOKIE, main.sign_session(subject, "google", int(time.time()) + 3600))

    def put(self, payload):
        return self.client.put("/api/jobs/song/tab", json=payload, headers={"Origin": "http://testserver"})

    def add_bass(self):
        self.result["separation"]["stems"].append("bass")
        (self.directory / "stems/bass.wav").write_bytes(b"bass-audio")
        with main.db() as c:
            c.execute("UPDATE jobs SET result=?", (json.dumps(self.result),))

    def bass_document(self):
        return {"instrument": "bass", "tuning": "bass_standard", "revision": 0,
            "notes": [{"index": 0, "start": 0, "end": 1, "midi": 28, "string": 0, "fret": 0}]}

    def put_bass(self, document):
        return self.client.put("/api/jobs/song/tab?instrument=bass", json=document, headers={"Origin": "http://testserver"})

    def test_bass_and_legacy_guitar_versions_have_independent_private_revisions(self):
        self.assertEqual(self.put(self.document).status_code, 200)
        self.assertEqual(self.put_bass(self.bass_document()).status_code, 200)
        self.assertEqual(self.put_bass(self.bass_document()).status_code, 409)
        guitar = self.client.get("/api/jobs/song/tab").json()
        bass = self.client.get("/api/jobs/song/tab?instrument=bass").json()
        self.assertEqual(guitar["revision"], bass["revision"])
        self.assertEqual(guitar["document"]["notes"][0]["midi"], 64)
        self.assertEqual(bass["document"]["notes"][0]["midi"], 28)
        self.login("bob@example.com")
        self.assertIsNone(self.client.get("/api/jobs/song/tab?instrument=bass").json()["document"])
        self.assertEqual(self.put_bass(self.bass_document()).status_code, 200)

    def test_private_reference_requires_confirmation_and_is_not_shared(self):
        headers = {"Origin":"http://testserver"}
        url = "/api/jobs/song/tab?confirmed_reference=true"
        self.assertEqual(self.client.put(url,json=self.document,headers=headers).status_code,400)
        document = {**self.document,"notes":[{**self.document["notes"][0],"edited":True}]}
        saved = self.client.put(url,json=document,headers=headers)
        self.assertTrue(saved.json()["reference_confirmed"])
        self.assertEqual(self.client.get("/api/jobs/song/tab-reference").json()["notes"][0]["midi"],64)
        self.login("bob@example.com")
        self.assertEqual(self.client.get("/api/jobs/song/tab-reference").status_code,404)
        self.client.delete("/api/jobs/song/tab-reference",headers=headers)
        self.login("alice@example.com")
        self.assertEqual(self.client.get("/api/jobs/song/tab-reference").status_code,200)
        self.assertEqual(self.put({**document,"revision":1}).status_code,200)
        self.assertEqual(self.client.get("/api/jobs/song/tab-reference").status_code,404)
        self.assertEqual(self.client.put(url,json={**document,"revision":2},headers=headers).status_code,200)
        self.assertEqual(self.client.delete("/api/jobs/song/tab-reference",headers=headers).status_code,200)
        self.assertFalse(self.client.get("/api/jobs/song/tab").json()["reference_confirmed"])
        self.assertEqual(self.client.get("/api/jobs/song/tab").json()["revision"],3)

    def test_bass_validation_rejects_guitar_settings_and_nonexistent_strings(self):
        bass = self.bass_document()
        for wrong in [{"capo": 2}, {"source_engine": "hybrid"}, {"tuning": "standard"}]:
            self.assertEqual(self.put_bass({**bass, **wrong}).status_code, 422)
        wrong = {**bass, "notes": [{**bass["notes"][0], "string": 4}]}
        self.assertEqual(self.put_bass(wrong).status_code, 422)
        self.assertEqual(self.put(bass).status_code, 400)
        self.assertEqual(self.client.get("/api/jobs/song/tab?instrument=../bass").status_code, 422)
        five = {**bass, "tuning": "bass_five", "notes": [{**bass["notes"][0], "midi": 23}]}
        self.assertEqual(self.put_bass(five).status_code, 200)

    def test_bass_generation_owner_queue_restart_and_concurrent_edit_preservation(self):
        self.add_bass()
        headers = {"Origin": "http://testserver"}
        self.login("bob@example.com")
        self.assertEqual(self.client.post("/api/jobs/song/bass-analysis", headers=headers).status_code, 404)
        self.login("alice@example.com")
        self.assertEqual(self.client.post("/api/jobs/song/bass-analysis").status_code, 403)
        self.assertEqual(self.client.post("/api/jobs/song/bass-analysis", headers=headers).json()["status"], "queued")
        self.assertEqual(self.client.post("/api/jobs/song/bass-analysis", headers=headers).json()["status"], "queued")
        self.assertEqual(self.client.post("/api/jobs/song/guitar-analysis", headers=headers).status_code, 409)
        with main.db() as c:
            c.execute("UPDATE guitar_tasks SET status='working'")
        with patch.object(main, "USERNAME", "test"), patch.object(main, "PASSWORD", "test"), patch.object(main, "STORAGE_MOUNT", None):
            main.startup()
        with main.db() as c:
            self.assertEqual(tuple(c.execute("SELECT engine,status FROM guitar_tasks").fetchone()), ("bass", "queued"))
        def fake_command(command, **kwargs):
            self.assertIn("--bass", command)
            self.assertIn(str(self.directory / "stems/bass.wav"), command)
            Path(command[3]).write_text(json.dumps({"profile": "bass_v1", "notes": [{"start": 0, "end": 1, "midi": 28}]}))
            Path(command[4]).write_bytes(b"MThd")
            with main.db() as c:
                result = {**self.result, "key": {"label": "manual key"},
                    "methods": {"chordino": [{"start": 0, "end": 10, "chord": "Dm"}]}}
                c.execute("UPDATE jobs SET result=?", (json.dumps(result),))
        with patch.object(main, "run_command", side_effect=fake_command):
            main.process_guitar_task("song")
        self.assertEqual(self.client.get("/api/jobs/song/bass-analysis").json()["status"], "done")
        self.assertEqual(self.client.get("/api/jobs/song/notes/bass").json()["profile"], "bass_v1")
        with main.db() as c:
            result = json.loads(c.execute("SELECT result FROM jobs").fetchone()[0])
        self.assertEqual(result["methods"]["chordino"][0]["chord"], "Dm")
        self.assertEqual(result["key"]["label"], "manual key")
        self.assertEqual(result["guitar_tab"], self.result["guitar_tab"])

    def test_existing_bass_midi_reused_without_queue_or_file_changes(self):
        self.add_bass()
        directory = self.directory / "stem-midi"
        directory.mkdir()
        (directory / "bass.json").write_text('{"profile":"general","notes":[{"midi":28}]}')
        (directory / "bass.mid").write_bytes(b"original-midi")
        self.result["separation"]["midi_stems"].append("bass")
        with main.db() as c:
            c.execute("UPDATE jobs SET result=?", (json.dumps(self.result),))
        response = self.client.post("/api/jobs/song/bass-analysis", headers={"Origin": "http://testserver"})
        self.assertEqual(response.json()["status"], "done")
        self.assertEqual(main.executor.submit.call_count, 0)
        self.assertEqual((directory / "bass.mid").read_bytes(), b"original-midi")

    def test_bass_failure_nonfatal_missing_source_and_preview_caches_separate(self):
        self.assertEqual(self.client.get("/api/jobs/song/bass-analysis").json()["status"], "unavailable")
        self.assertEqual(self.client.post("/api/jobs/song/bass-analysis", headers={"Origin": "http://testserver"}).status_code, 400)
        self.add_bass()
        self.client.post("/api/jobs/song/bass-analysis", headers={"Origin": "http://testserver"})
        with patch.object(main, "run_command", side_effect=RuntimeError("bass failure")):
            main.process_guitar_task("song")
        self.assertEqual(self.client.get("/api/jobs/song/bass-analysis").json()["status"], "failed")
        self.assertEqual(self.client.get("/api/jobs/song").json()["status"], "done")
        def fake_preview(command, **kwargs):
            Path(command[-1]).write_bytes(b"m4a")
        with patch.object(main, "run_command", side_effect=fake_preview) as command:
            self.assertEqual(self.client.get("/api/jobs/song/guitar-preview?track=bass").status_code, 200)
            self.assertEqual(self.client.get("/api/jobs/song/guitar-preview").status_code, 200)
            self.assertEqual(command.call_count, 2)
        self.assertTrue((self.directory / "bass-preview-0.m4a").exists())
        self.assertTrue((self.directory / "guitar-preview-0.m4a").exists())
        self.assertEqual(self.client.get("/api/jobs/song/guitar-preview?track=../bass").status_code, 422)

    def test_bass_uses_shared_daily_active_limits_and_deletion_cascades(self):
        self.add_bass()
        headers = {"Origin": "http://testserver"}
        with patch.object(main, "DAILY_JOB_LIMIT", 1):
            self.assertEqual(self.client.post("/api/jobs/song/bass-analysis", headers=headers).status_code, 202)
            self.assertEqual(self.client.get("/api/queue").json()["waiting"], 1)
            with patch.object(main, "MAX_ACTIVE_PER_USER", 1):
                self.assertEqual(self.client.post("/api/jobs", data={"url": "https://youtu.be/9GIRqZfa1Gg"}, headers=headers).status_code, 429)
            with main.db() as c:
                c.execute("UPDATE guitar_tasks SET status='failed'")
            self.assertEqual(self.client.post("/api/jobs/song/guitar-analysis", headers=headers).status_code, 429)
        self.assertEqual(self.put(self.document).status_code, 200)
        self.assertEqual(self.put_bass(self.bass_document()).status_code, 200)
        with main.db() as c:
            c.execute("DELETE FROM jobs WHERE id='song'")
            self.assertEqual(c.execute("SELECT COUNT(*) FROM user_tabs").fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM user_bass_tabs").fetchone()[0], 0)

    def test_personal_versions_are_private_and_do_not_change_shared_result(self):
        self.assertEqual(self.put(self.document).status_code, 200)
        self.assertEqual(self.client.get("/api/jobs/song/tab").json()["revision"], 1)
        self.login("bob@example.com")
        self.assertIsNone(self.client.get("/api/jobs/song/tab").json()["document"])
        self.assertEqual(self.put(self.document).status_code, 200)
        self.login("alice@example.com")
        self.assertEqual(self.client.get("/api/jobs/song/tab").json()["document"]["notes"][0]["midi"], 64)
        with main.db() as c:
            self.assertEqual(json.loads(c.execute("SELECT result FROM jobs WHERE id='song'").fetchone()[0]), self.result)

    def test_revision_conflict_and_request_origin_are_enforced(self):
        self.assertEqual(self.put(self.document).status_code, 200)
        self.assertEqual(self.put(self.document).status_code, 409)
        self.assertEqual(self.client.put("/api/jobs/song/tab", json=self.document).status_code, 403)
        self.document["revision"] = 1
        self.assertEqual(self.put(self.document).json()["revision"], 2)

    def test_pitch_duplicate_overlap_nan_and_length_rejected(self):
        payload = json.loads(json.dumps(self.document))
        payload["notes"][0]["midi"] = 65
        self.assertEqual(self.put(payload).status_code, 422)
        payload = json.loads(json.dumps(self.document))
        payload["notes"].append(dict(payload["notes"][0]))
        self.assertEqual(self.put(payload).status_code, 422)
        payload["notes"][1]["index"] = 1
        self.assertEqual(self.put(payload).status_code, 422)
        payload = json.loads(json.dumps(self.document))
        payload["notes"][0]["end"] = 12
        self.assertEqual(self.put(payload).status_code, 400)
        self.assertEqual(self.client.get("/api/jobs/song/guitar-preview?start=nan").status_code, 422)

    def test_private_song_cannot_be_edited_by_another_viewer(self):
        with main.db() as c:
            c.execute("UPDATE jobs SET is_public=0 WHERE id='song'")
        self.login("bob@example.com")
        self.assertEqual(self.client.get("/api/jobs/song/tab").status_code, 404)
        self.assertEqual(self.put(self.document).status_code, 404)

    def test_guitar_generation_is_owner_only_idempotent_and_in_queue_counts(self):
        headers = {"Origin": "http://testserver"}
        self.login("bob@example.com")
        self.assertEqual(self.client.post("/api/jobs/song/guitar-analysis", headers=headers).status_code, 404)
        self.login("alice@example.com")
        self.assertEqual(self.client.post("/api/jobs/song/guitar-analysis", headers=headers).status_code, 202)
        self.assertEqual(self.client.post("/api/jobs/song/guitar-analysis", headers=headers).status_code, 202)
        self.assertEqual(main.executor.submit.call_count, 1)
        self.assertEqual(self.client.get("/api/jobs/song/guitar-analysis").json()["status"], "queued")
        self.assertEqual(self.client.get("/api/queue").json()["waiting"], 1)

    def test_guitar_completion_preserves_concurrent_chord_changes(self):
        self.client.post("/api/jobs/song/guitar-analysis", headers={"Origin": "http://testserver"})
        def transcribe(*args):
            updated = dict(self.result)
            updated["methods"] = {"chordino": [{"start": 0, "end": 10, "chord": "Dm"}]}
            with main.db() as c:
                c.execute("UPDATE jobs SET result=? WHERE id='song'", (json.dumps(updated),))
            return ["guitar"], {}
        with patch.object(main, "transcribe_guitar_tab", side_effect=transcribe):
            main.process_guitar_task("song")
        with main.db() as c:
            result = json.loads(c.execute("SELECT result FROM jobs WHERE id='song'").fetchone()[0])
        self.assertEqual(result["methods"]["chordino"][0]["chord"], "Dm")
        self.assertIn("guitar", result["separation"]["midi_stems"])
        self.assertEqual(self.client.get("/api/jobs/song/guitar-analysis").json()["status"], "done")

    def test_original_guitar_retry_uses_normalized_audio_and_preserves_source(self):
        result = {**self.result, "separation": {"stems": ["original"], "midi_stems": [], "midi_errors": {"guitar": "轉錄失敗"}},
                  "guitar_tab": {"source": "original", "status": "unavailable"}}
        (self.directory / "audio.wav").write_bytes(b"normalized-audio")
        with main.db() as c:
            c.execute("UPDATE jobs SET pure_guitar=1,result=? WHERE id='song'", (json.dumps(result),))
        self.assertEqual(self.client.get("/api/jobs/song/guitar-analysis").json()["status"], "failed")
        self.login("bob@example.com")
        self.assertEqual(self.client.post("/api/jobs/song/guitar-analysis", headers={"Origin": "http://testserver"}).status_code, 404)
        self.login("alice@example.com")
        self.assertEqual(self.client.post("/api/jobs/song/guitar-analysis", headers={"Origin": "http://testserver"}).status_code, 202)
        with patch.object(main, "transcribe_guitar_tab", return_value=(["guitar"], {})) as transcribe:
            main.process_guitar_task("song")
            transcribe.assert_called_once_with("song", self.directory, direct_source=self.directory / "audio.wav")
        with main.db() as c:
            saved = json.loads(c.execute("SELECT result FROM jobs WHERE id='song'").fetchone()[0])
        self.assertEqual(saved["guitar_tab"]["source"], "original")
        self.assertEqual(saved["guitar_tab"]["status"], "done")
        self.assertEqual(saved["methods"], result["methods"])
        self.assertNotIn("guitar", saved["separation"]["midi_errors"])

    def test_original_guitar_without_source_metadata_still_uses_original_preview(self):
        result = {"separation": {"stems": ["original"], "midi_stems": []}}
        (self.directory / "audio.wav").write_bytes(b"normalized-audio")
        with main.db() as c:
            c.execute("UPDATE jobs SET pure_guitar=1,result=? WHERE id='song'", (json.dumps(result),))
        self.assertEqual(self.client.get("/api/jobs/song/guitar-analysis").json()["status"], "pending")
        def fake_command(command, **kwargs):
            self.assertIn(str(self.directory / "audio.wav"), command)
            Path(command[-1]).write_bytes(b"m4a")
        with patch.object(main, "run_command", side_effect=fake_command):
            self.assertEqual(self.client.get("/api/jobs/song/guitar-preview").status_code, 200)

    def test_optional_light_payload_preserves_original_note_api(self):
        result = dict(self.result, notes=[{"midi": 64, "start": 0, "end": 1}])
        with main.db() as c:
            c.execute("UPDATE jobs SET result=? WHERE id='song'", (json.dumps(result),))
        self.assertIn("notes", self.client.get("/api/jobs/song").json()["result"])
        self.assertNotIn("notes", self.client.get("/api/jobs/song?include_notes=false").json()["result"])
        self.assertNotIn("notes", self.client.get("/api/public/jobs/song?include_notes=false").json()["result"])

    def test_guitar_task_counts_against_active_limit(self):
        self.client.post("/api/jobs/song/guitar-analysis", headers={"Origin": "http://testserver"})
        with patch.object(main, "MAX_ACTIVE_PER_USER", 1):
            response = self.client.post("/api/jobs", data={"url": "https://youtu.be/9GIRqZfa1Gg"}, headers={"Origin": "http://testserver"})
        self.assertEqual(response.status_code, 429)

    def test_preview_is_short_cached_and_rejects_invalid_start(self):
        def fake_command(command, **kwargs):
            self.assertIn("20", command)
            Path(command[-1]).write_bytes(b"m4a")
        with patch.object(main, "run_command", side_effect=fake_command) as command:
            self.assertEqual(self.client.get("/api/jobs/song/guitar-preview?start=3").status_code, 200)
            self.assertEqual(self.client.get("/api/jobs/song/guitar-preview?start=9").status_code, 200)
            self.assertEqual(command.call_count, 1)
        self.assertEqual(self.client.get("/api/jobs/song/guitar-preview?start=-1").status_code, 422)

    def test_stream_is_compressed_cached_and_download_remains_wav(self):
        def fake_command(command, **kwargs):
            self.assertIn("aac", command)
            Path(command[-1]).write_bytes(b"m4a")
        with patch.object(main, "run_command", side_effect=fake_command) as command:
            self.assertEqual(self.client.get("/api/jobs/song/audio-stream/guitar").status_code, 200)
            self.assertEqual(self.client.get("/api/jobs/song/audio-stream/guitar").status_code, 200)
            self.assertEqual(command.call_count, 1)
        raw = self.client.get("/api/jobs/song/audio/guitar")
        self.assertEqual(raw.content, b"test")
        self.assertEqual(raw.headers["content-type"], "audio/wav")
        self.assertEqual(self.client.get("/api/jobs/song/audio-stream/unknown").status_code, 404)

    def test_restart_recovers_pending_guitar_tasks(self):
        with main.db() as c:
            c.execute("INSERT INTO guitar_tasks(job_id,status,created_at,updated_at) VALUES ('song','working',1,1)")
        with patch.object(main, "USERNAME", "tester"), patch.object(main, "PASSWORD", "test"), patch.object(main, "STORAGE_MOUNT", None):
            main.startup()
        self.assertIs(main.executor.submit.call_args.args[0], main.process_guitar_task)
        self.assertEqual(self.client.get("/api/jobs/song/guitar-analysis").json()["status"], "queued")

    def test_admin_cannot_delete_during_guitar_transcription(self):
        job_id = "1" * 32
        with main.db() as c:
            c.execute("INSERT INTO jobs(id,title,source,status,owner,result,duration,created_at,updated_at) VALUES (?,'test','test','done','alice@example.com',?,10,1,1)", (job_id, json.dumps(self.result)))
            c.execute("INSERT INTO guitar_tasks(job_id,status,created_at,updated_at) VALUES (?,'working',1,1)", (job_id,))
        self.client.cookies.set(main.COOKIE, main.sign_session("tester", "local", int(time.time()) + 3600))
        response = self.client.request("DELETE", f"/api/admin/jobs/{job_id}", json={"confirm": job_id}, headers={"Origin": "http://testserver"})
        self.assertEqual(response.status_code, 409)

    def test_busy_media_pool_does_not_block_health_requests(self):
        pool = LightTaskPool(workers=1, capacity=1)
        started, finish = threading.Event(), threading.Event()
        def blocked_mix(*args):
            started.set()
            finish.wait(5)
            return FileResponse(self.directory / "stems/guitar.wav")
        async def scenario():
            cookies = {main.COOKIE: self.client.cookies.get(main.COOKIE)}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://testserver", cookies=cookies) as client:
                first = asyncio.create_task(client.get("/api/jobs/song/audio-mix?tracks=original,guitar"))
                try:
                    self.assertTrue(await asyncio.to_thread(started.wait, 2))
                    busy = await asyncio.wait_for(client.get("/api/jobs/song/audio-mix?tracks=original,guitar"), 1)
                    self.assertEqual(busy.status_code, 429)
                    health = await asyncio.wait_for(client.get("/healthz"), 1)
                    self.assertEqual(health.status_code, 200)
                    self.assertFalse(finish.is_set())
                finally:
                    finish.set()
                    response = await asyncio.wait_for(first, 2)
                    self.assertEqual(response.status_code, 200)
        try:
            with patch.object(main, "light_tasks", pool), patch.object(main, "build_audio_mix", side_effect=blocked_mix):
                asyncio.run(scenario())
        finally:
            finish.set()
            pool.executor.shutdown(wait=True)


class LightPoolTests(unittest.IsolatedAsyncioTestCase):
    async def test_download_preparation_is_bounded_and_can_be_consumed(self):
        preparation = DownloadPreparation(workers=1, capacity=1)
        try:
            self.assertTrue(preparation.submit("first", lambda: 1))
            self.assertFalse(preparation.submit("second", lambda: 2))
            first = preparation.take("first")
            self.assertEqual(await asyncio.to_thread(first.result, 2), 1)
            self.assertTrue(preparation.submit("second", lambda: 2))
            self.assertEqual(await asyncio.to_thread(preparation.take("second").result, 2), 2)
        finally:
            preparation.executor.shutdown(wait=True)

    async def test_capacity_stays_reserved_after_request_cancelled(self):
        pool = LightTaskPool(workers=1, capacity=1)
        started, finish = threading.Event(), threading.Event()
        def blocked():
            started.set()
            finish.wait(5)
        task = asyncio.create_task(pool.run(blocked))
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 2))
            with self.assertRaises(PoolBusy):
                await pool.run(lambda: None)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            with self.assertRaises(PoolBusy):
                await pool.run(lambda: None)
            finish.set()
            await asyncio.to_thread(pool.executor.shutdown, True)
            self.assertTrue(pool.capacity.acquire(blocking=False))
            pool.capacity.release()
        finally:
            finish.set()
            pool.executor.shutdown(wait=True)
