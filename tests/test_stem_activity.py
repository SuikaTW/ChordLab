from array import array
from pathlib import Path
import math
import sys
import tempfile
import unittest
import wave

from app.stem_activity import detect_activity


class StemActivityTests(unittest.TestCase):
    def write_audio(self, path, amplitude, burst=False, stereo=False):
        samples = array("h")
        for i in range(16000 * 3):
            value = round(amplitude * 32767 * math.sin(2 * math.pi * 440 * i / 16000))
            if burst and not 16000 <= i < 20000:
                value = 0
            samples.extend([value, -value] if stereo else [value])
        if sys.byteorder != "little":
            samples.byteswap()
        with wave.open(str(path), "wb") as out:
            out.setparams((2 if stereo else 1, 2, 16000, 0, "NONE", "not compressed"))
            out.writeframes(samples.tobytes())

    def test_silence_and_weak_residue_hidden_but_quiet_and_brief_parts_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "stems").mkdir()
            self.write_audio(directory / "audio.wav", .5)
            for name, amplitude, burst in [("silent", 0, False), ("residue", .0001, False),
                                            ("quiet", .02, False), ("brief", .1, True)]:
                self.write_audio(directory / "stems" / f"{name}.wav", amplitude, burst)
            result = detect_activity(directory, ["original", "silent", "residue", "quiet", "brief", "missing"])
            self.assertFalse(result["silent"]["active"])
            self.assertFalse(result["residue"]["active"])
            self.assertTrue(result["quiet"]["active"])
            self.assertTrue(result["brief"]["active"])
            self.assertTrue(result["missing"]["active"])

    def test_opposite_phase_stereo_is_not_silence(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "stems").mkdir()
            self.write_audio(directory / "audio.wav", .5)
            self.write_audio(directory / "stems" / "guitar.wav", .3, stereo=True)
            self.assertTrue(detect_activity(directory, ["guitar"])["guitar"]["active"])

    def test_missing_reference_keeps_tracks(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(detect_activity(Path(tmp), ["guitar"]), {})
