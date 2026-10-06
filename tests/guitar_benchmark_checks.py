"""Run with .venv-guitar/bin/python; no audio, downloads or live DB required."""
import sys
from pathlib import Path
import unittest
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.benchmark_guitar import score
from tools.guitar_worker import write_midi
import mido


class BenchmarkTests(unittest.TestCase):
    def test_matching_is_one_to_one_and_not_greedy(self):
        reference = [{"midi": 64, "start": .04, "end": .2}, {"midi": 64, "start": 0, "end": .2}]
        predicted = [{"midi": 64, "start": .02, "end": .2}, {"midi": 64, "start": .08, "end": .2}]
        self.assertEqual(score(reference, predicted)["matched"], 2)
        self.assertEqual(score(reference[:1], predicted)["matched"], 1)

    def test_pitch_onset_offsets_and_fingerings_are_distinct(self):
        reference = [{"midi": 64, "start": 0, "end": .5, "string": 5, "fret": 0}]
        predicted = [{"midi": 64, "start": .01, "end": 1.5, "model_string": 4, "model_fret": 5}]
        self.assertEqual(score(reference, predicted)["matched"], 1)
        self.assertEqual(score(reference, predicted, offsets=True)["matched"], 0)
        self.assertEqual(score(reference, predicted, fingerings=True)["matched"], 0)

    def test_empty_inputs_are_finite(self):
        self.assertEqual(score([], [])["f1"], 0)
        self.assertEqual(score([{"midi": 64, "start": 0, "end": .5}], [])["f1"], 0)

    def test_string_channels_have_guitar_programs_and_preserve_unisons(self):
        notes = [{"midi": 64, "start": 0, "end": .5, "velocity": .7, "model_string": string} for string in (4, 5)]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "guitar.mid"
            write_midi(notes, path)
            events = list(mido.MidiFile(path).tracks[0])
        programs = {event.channel: event.program for event in events if event.type == "program_change"}
        self.assertTrue(all(programs[channel] == 24 for channel in range(6)))
        self.assertEqual([event.channel for event in events if event.type == "note_on"], [4, 5])


if __name__ == "__main__":
    unittest.main()
