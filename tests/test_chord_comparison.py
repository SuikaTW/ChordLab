import unittest

from app.chord_comparison import compare_chords, relation


def seg(start, end, chord):
    return dict(start=start, end=end, chord=chord)


class ComparisonTests(unittest.TestCase):
    def test_enharmonic_names_and_harte_aliases(self):
        self.assertEqual(relation("Dbm7", "C#:min7"), "agree")
        self.assertEqual(relation("Cmaj7", "C:minmaj7"), "conflict")
        self.assertEqual(relation("C", "Cmaj7"), "detail")
        self.assertEqual(relation("C", "C/E"), "detail")
        self.assertEqual(relation("C", "Csus4"), "conflict")
        self.assertEqual(relation("Cdim", "Cm"), "conflict")
        self.assertEqual(relation("N", "N"), "agree")
        self.assertEqual(relation("X", "X"), "conflict")

    def test_alignment_preserves_baseline_and_duration_weights(self):
        baseline = [seg(0, 5, "C"), seg(5, 10, "Am")]
        btc = [seg(0, 4.9, "C"), seg(4.9, 10, "Am")]
        result = compare_chords(baseline, btc, 10)
        self.assertEqual(result["summary"]["agreement_ratio"], .99)
        self.assertEqual(result["summary"]["review_segments"], 0)
        self.assertEqual([s["chord"] for s in result["chords"]], ["C", "Am"])
        self.assertEqual(result["chords"][0]["end"], 5)
        self.assertNotIn("comparison", baseline[0])

    def test_extensions_conflicts_and_no_chord(self):
        result = compare_chords([seg(0, 2, "C"), seg(2, 4, "Am"), seg(4, 6, "N")],
                                [seg(0, 2, "Cmaj7"), seg(2, 4, "A"), seg(4, 6, "C")], 6)
        self.assertEqual([s["comparison"]["status"] for s in result["chords"]], ["detail", "conflict", "conflict"])
        self.assertEqual(result["summary"]["detail_seconds"], 2)
        self.assertEqual(result["summary"]["conflict_seconds"], 4)

    def test_gaps_are_not_treated_as_agreement(self):
        result = compare_chords([seg(0, 10, "C")], [seg(0, 1, "C")], 10)
        self.assertEqual(result["chords"][0]["comparison"]["status"], "unavailable")
        self.assertEqual(result["summary"]["compared_seconds"], 1)

    def test_many_transitions_show_mixed_not_confident_majority(self):
        btc = [seg(0, 2, "Dm"), seg(2, 4, "F"), seg(4, 6, "G")]
        result = compare_chords([seg(0, 6, "C")], btc, 6)
        self.assertEqual(result["chords"][0]["comparison"]["status"], "mixed")
        self.assertEqual(len(result["chords"][0]["comparison"]["candidates"]), 2)

    def test_invalid_and_overlapping_segments(self):
        result = compare_chords([seg(0, float("inf"), "C")], [], 10)
        self.assertIsNone(result["summary"]["agreement_ratio"])
        with self.assertRaises(ValueError):
            compare_chords([seg(0, 3, "C")], [seg(0, 2, "C"), seg(1, 3, "G")], 3)


if __name__ == "__main__":
    unittest.main()
