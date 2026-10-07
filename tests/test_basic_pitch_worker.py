"""Worker option regressions without loading/downloading a model."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class BasicPitchWorkerTests(unittest.TestCase):
    def run_worker(self, flags, events=None):
        instrument = SimpleNamespace(program=0)
        midi = SimpleNamespace(instruments=[instrument], write=lambda path: Path(path).write_bytes(b"MThd"))
        predict = Mock(return_value=({}, midi, events if events is not None else [(0., .08, 28, .7)]))
        spec = importlib.util.spec_from_file_location("worker_options_test", Path(__file__).resolve().parents[1] / "tools/basic_pitch_worker.py")
        worker = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"basic_pitch.inference": SimpleNamespace(predict=predict)}):
            spec.loader.exec_module(worker)
        with tempfile.TemporaryDirectory() as temporary:
            output, midi_path = Path(temporary) / "notes.json", Path(temporary) / "notes.mid"
            with patch.object(sys, "argv", ["worker", "audio.wav", str(output), str(midi_path), *flags]):
                worker.main()
            result = json.loads(output.read_text())
        return result, predict.call_args.kwargs, instrument.program

    def test_bass_has_low_b_range_short_notes_and_bass_midi_program(self):
        result, options, program = self.run_worker(["--bass"])
        self.assertEqual(result["profile"], "bass_v1")
        self.assertEqual(options["minimum_note_length"], 60.)
        self.assertEqual(options["onset_threshold"], .5)
        self.assertAlmostEqual(options["minimum_frequency"], 440 * 2 ** ((23-69)/12))
        self.assertAlmostEqual(options["maximum_frequency"], 440 * 2 ** ((67-69)/12))
        self.assertEqual(program, 33)
        self.assertEqual(result["notes"][0]["midi"], 28)

    def test_general_and_guitar_settings_remain_unchanged(self):
        result, options, program = self.run_worker([])
        self.assertEqual((result["profile"], options, program), ("general", {}, 0))
        result, options, program = self.run_worker(["--guitar"])
        self.assertEqual(result["profile"], "guitar_v2")
        self.assertEqual(options["minimum_note_length"], 80.)
        self.assertEqual(options["onset_threshold"], .6)
        self.assertEqual(program, 0)

    def test_bass_event_limit_and_mutually_exclusive_instruments(self):
        with self.assertRaises(ValueError):
            self.run_worker(["--bass"], [(0., .08, 28, .7)] * 20001)
        with patch.object(sys, "stderr", io.StringIO()), self.assertRaises(SystemExit):
            self.run_worker(["--bass", "--guitar"])


if __name__ == "__main__":
    unittest.main()
