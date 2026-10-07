"""Controlled audio integration checks, not a real-song accuracy benchmark."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np
from scipy.io import wavfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.harmony_worker import refine, SR


class WorkerChecks(unittest.TestCase):
    def test_known_audio_corrects_wrong_engine_and_retains_silence(self):
        duration = 4.5
        audio = np.zeros(round(duration * SR), dtype=np.float32)
        reference = [(0., .9, "C", (48, 64, 67)), (.9, 1.9, "Am", (45, 60, 64)),
                     (1.9, 3., "F", (41, 57, 60, 65)), (3., 4., "G", (43, 59, 62, 67))]
        for start, end, _, pitches in reference:
            first, last = round(start * SR), round(end * SR)
            t = np.arange(last-first) / SR
            envelope = np.minimum(1., np.minimum(t * 200, (end-start-t) * 200))
            for pitch in pitches:
                frequency = 440 * 2 ** ((pitch-69)/12)
                audio[first:last] += (.15 * np.sin(2*np.pi*frequency*t) + .02*np.sin(4*np.pi*frequency*t)) * envelope
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            wavfile.write(directory / "audio.wav", SR, audio)
            baseline = {"chords": [{"start": 0., "end": duration, "chord": "Dm"}]}
            (directory / "baseline.json").write_text(json.dumps(baseline))
            result = refine(directory / "audio.wav", directory / "baseline.json")
            self.assertEqual(json.loads((directory / "baseline.json").read_text()), baseline)
        correct = 0.
        for start, end, expected, _ in reference:
            correct += sum(max(0., min(end, segment["end"]) - max(start, segment["start"]))
                for segment in result["chords"] if segment["chord"] == expected)
        self.assertGreater(correct / 4., .85, result)
        self.assertEqual(result["chords"][-1]["chord"], "N")
        self.assertEqual(result["chords"][0]["start"], 0.)
        self.assertEqual(result["chords"][-1]["end"], duration)


if __name__ == "__main__":
    unittest.main()
