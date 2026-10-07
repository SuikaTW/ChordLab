import unittest
from app.harmony_refinement import decode, rank_observation


def observation(start=0., end=1., pcs=(0, 4, 7), bass_pc=0, baseline="C", **extra):
    chroma = [.01] * 12
    for pc in pcs:
        chroma[pc] = 1.
    bass = [0.] * 12
    bass[bass_pc] = 1.
    return {"start": start, "end": end, "chroma": chroma, "bass": bass,
        "engine_labels": {baseline: 1.}, "change": 1., **extra}


class HarmonyTests(unittest.TestCase):
    def test_acoustic_evidence_can_correct_baseline_without_mutation(self):
        observations = [observation(baseline="Dm"), observation(1, 2, (9, 0, 4), 9, "C")]
        before = repr(observations)
        result = decode(observations, 2)
        self.assertEqual([s["chord"] for s in result["chords"]], ["C", "Am"])
        self.assertEqual(repr(observations), before)
        self.assertTrue(result["summary"]["experimental"])

    def test_bass_is_not_always_root_or_inversion(self):
        short = observation(end=.2, bass_pc=4, separate_bass=True)
        self.assertEqual(rank_observation(short)[0][0], "C")
        self.assertFalse(any("/" in label for label, _ in rank_observation(short)))
        unseparated = observation(bass_pc=4)
        self.assertEqual(rank_observation(unseparated)[0][0], "C")
        sustained = observation(bass_pc=4, separate_bass=True)
        self.assertEqual(rank_observation(sustained)[0][0], "C/E")

    def test_unsupported_extension_is_not_rewarded(self):
        item = observation()
        item["engine_labels"]["Cmaj7"] = 1.7
        self.assertEqual(rank_observation(item)[0][0], "C")

    def test_silence_and_offbeat_change_have_true_timing(self):
        items = [observation(end=.37), observation(.37, 1., (9, 0, 4), 9, "Am"), observation(1., 1.5, silent=True)]
        result = decode(items, 1.5)
        self.assertEqual([s["chord"] for s in result["chords"]], ["C", "Am", "N"])
        self.assertEqual(result["chords"][1]["start"], .37)

    def test_invalid_and_incomplete_evidence_rejected(self):
        for items, duration in [([observation(start=.5)], 1.), ([observation()], 2.),
                                ([observation(chroma=[float("nan")] * 12)], 1.)]:
            with self.assertRaises(ValueError):
                decode(items, duration)


if __name__ == "__main__":
    unittest.main()
