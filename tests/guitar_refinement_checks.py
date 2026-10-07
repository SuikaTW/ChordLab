"""Run using .venv-guitar/bin/python, without audio inference or downloads."""
from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.guitar_refinement import fuse_notes, release_proposal, STANDARD


class RefinementTests(unittest.TestCase):
    def test_hints_match_pitch_and_do_not_union_or_retime_notes(self):
        notes = [dict(start=0., end=.3, midi=64, velocity=.7), dict(start=.1, end=.4, midi=64, velocity=.7)]
        probs = np.zeros((30, 6, 21))
        probs[:, 4, 6] = .9
        probs[:, 5, 1] = .8
        result, summary = fuse_notes(notes, probs, np.ones((192, 30)), 1.)
        self.assertEqual(len(result), len(notes))
        self.assertEqual(summary["repeated_pitch_attacks_preserved"], 1)
        for original, fused in zip(notes, result):
            self.assertTrue(all(fused[key] == value for key, value in original.items()))
            self.assertEqual(STANDARD[fused["model_string"]] + fused["model_fret"], fused["midi"])
            self.assertTrue(all(STANDARD[c["string"]] + c["fret"] == fused["midi"] for c in fused["fingering_candidates"]))
        self.assertNotIn("model_string", notes[0])

    def test_low_evidence_is_not_an_anchor(self):
        notes = [dict(start=0., end=.3, midi=64)]
        result, summary = fuse_notes(notes, np.zeros((30, 6, 21)), np.ones((192, 30)), 1.)
        self.assertTrue(result[0]["fingering_uncertain"])
        self.assertNotIn("model_string", result[0])
        self.assertEqual(summary["uncertain_fingerings"], 1)

    def test_release_proposals_do_not_trim_sustain(self):
        self.assertIsNone(release_proposal(np.ones(40), 0, 40, .02))
        envelope = np.r_[np.ones(10), np.zeros(30)]
        self.assertAlmostEqual(release_proposal(envelope, 0, 40, .02), .22)
        probs = np.zeros((40, 6, 21))
        magnitude = np.tile(envelope, (192, 1))
        result, summary = fuse_notes([dict(start=0., end=.8, midi=64)], probs, magnitude, .8, .02)
        self.assertEqual(result[0]["end"], .8)
        self.assertEqual(summary["release_policy"], "diagnostic_only")

    def test_invalid_probabilities_and_timestamps_rejected(self):
        for probs in [np.zeros((30, 21)), np.full((30, 6, 21), float("nan")), np.full((30, 6, 21), 2.)]:
            with self.assertRaises(ValueError):
                fuse_notes([], probs, np.ones((192, 30)), 1.)
        with self.assertRaises(ValueError):
            fuse_notes([dict(start=-1., end=.2, midi=64)], np.zeros((30, 6, 21)), np.ones((192, 30)), 1.)


if __name__ == "__main__":
    unittest.main()
