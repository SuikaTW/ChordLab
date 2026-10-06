import gc
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main


class DatabaseLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="chordlab-db-test-")
        self.patch = patch.object(main, "DB_PATH", Path(self.temp.name) / "test.sqlite3")
        self.patch.start()
        with main.db() as connection:
            connection.execute("CREATE TABLE events(value TEXT)")

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_commit_and_close_after_success(self):
        with main.db() as connection:
            connection.execute("INSERT INTO events VALUES ('saved')")
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")
        with main.db() as check:
            self.assertEqual(check.execute("SELECT value FROM events").fetchone()[0], "saved")

    def test_rollback_and_close_after_error(self):
        with self.assertRaises(ValueError):
            with main.db() as connection:
                connection.execute("INSERT INTO events VALUES ('not-saved')")
                raise ValueError("simulate failed request")
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")
        with main.db() as check:
            self.assertEqual(check.execute("SELECT count(*) FROM events").fetchone()[0], 0)

    @unittest.skipUnless(Path("/proc/self/fd").exists(), "Linux file descriptor regression")
    def test_repeated_requests_release_handles_without_garbage_collection(self):
        gc_enabled = gc.isenabled()
        gc.disable()
        retained = []
        try:
            before = len(list(Path("/proc/self/fd").iterdir()))
            for _ in range(200):
                with main.db() as connection:
                    connection.execute("SELECT 1").fetchone()
                    retained.append(connection)
            after = len(list(Path("/proc/self/fd").iterdir()))
            self.assertLessEqual(after, before + 2, "Database handles must not accumulate per request")
        finally:
            if gc_enabled:
                gc.enable()


if __name__ == "__main__":
    unittest.main()
