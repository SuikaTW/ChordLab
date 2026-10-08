"""Web/worker separation and recovery of committed queue entries."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main, worker
from support import runtime_patches


class DurableWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [patch.object(main, "DATA", self.root),
            patch.object(main, "DB_PATH", self.root / "db.sqlite3"),
            patch.object(main, "JOBS", self.root / "jobs"), *runtime_patches(main)]
        for item in self.patches:
            item.start()
        main.init_db()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_web_startup_never_requeues_live_work(self):
        with main.db() as connection:
            connection.execute("INSERT INTO jobs(id,title,source,status,created_at,updated_at) VALUES ('a','a','a','working',1,1)")
        with patch.object(main, "EMBEDDED_WORKER", False), patch.object(main, "USERNAME", "test"), \
             patch.object(main, "PASSWORD", "test"), patch.object(main, "SECRET", "x" * 32), \
             patch.object(main, "STORAGE_MOUNT", None), patch.object(main.executor, "submit") as submit:
            main.startup()
        with main.db() as connection:
            self.assertEqual(connection.execute("SELECT status FROM jobs WHERE id='a'").fetchone()[0], "working")
        submit.assert_not_called()

    def test_durable_poll_and_recovery(self):
        with main.db() as connection:
            connection.execute("INSERT INTO jobs(id,title,source,status,created_at,updated_at) VALUES ('a','a','a','working',1,1)")
            connection.execute("INSERT INTO jobs(id,title,source,status,created_at,updated_at) VALUES ('b','b','b','queued',2,2)")
        worker.recover_interrupted()
        self.assertEqual(worker.next_task(), ("song", "a"))
        with patch.object(main, "process_job") as process:
            self.assertTrue(worker.run_once())
            self.assertEqual(process.call_args.args[:3], ("a", "upload", "a"))

    def test_completed_refinement_cannot_be_replayed(self):
        with main.db() as connection:
            connection.execute("INSERT INTO jobs(id,title,source,status,created_at,updated_at) VALUES ('a','a','a','done',1,1)")
            connection.execute("INSERT INTO guitar_tasks(job_id,status,engine,created_at,updated_at) VALUES ('a','done','bass',1,1)")
        with patch.object(main, "process_bass_task") as process:
            main.process_guitar_task("a")
        process.assert_not_called()

    def test_uncaught_processor_failure_is_visible_not_stuck(self):
        with main.db() as connection:
            connection.execute("INSERT INTO jobs(id,title,source,status,created_at,updated_at) VALUES ('a','a','a','queued',1,1)")
        with patch.object(main, "process_job", side_effect=RuntimeError("unexpected")):
            self.assertTrue(worker.run_once())
        with main.db() as connection:
            self.assertEqual(connection.execute("SELECT status FROM jobs WHERE id='a'").fetchone()[0], "failed")


if __name__ == "__main__":
    unittest.main()
