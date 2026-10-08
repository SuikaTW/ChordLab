import unittest

from tools.accuracy_gate import assess


class AccuracyGateTests(unittest.TestCase):
    def test_incomplete_or_overlapping_corpus_cannot_promote(self):
        report = {"complete_selection": True, "selected_clips": 12, "evaluated_clips": 12,
                  "model_training_overlap": "possible", "groups": []}
        issues = assess(report, "old", "new", {"real_acoustic_guitar"})
        self.assertTrue(any("重疊" in issue for issue in issues))
        self.assertTrue(any("三段" in issue for issue in issues))

    def test_regression_rejected_even_if_development_improves(self):
        def row(engine, split, score):
            metrics = {name: {"micro_f1": score} for name in
                       ("pitch_onset", "pitch_onset_offset", "displayed_tab")}
            metrics["displayed_tab"]["actual_fingering_agreement"] = score
            return {"engine": engine, "split": split, "genre": "all",
                    "source_condition": "real_acoustic_guitar", "clips": 3,
                    "clip_ids": [f"{split}-{index}" for index in range(3)], "metrics": metrics}
        report = {"complete_selection": True, "selected_clips": 6, "evaluated_clips": 6,
                  "model_training_overlap": "verified_none",
                  "groups": [row("old", "development", .80), row("new", "development", .83),
                             row("old", "regression", .80), row("new", "regression", .77)],
                  "chord_metrics_first_annotation_weighted": {
                      "old": {"exact_chord_duration_agreement": .5, "boundary_f1": .5},
                      "new": {"exact_chord_duration_agreement": .5, "boundary_f1": .5}}}
        self.assertTrue(any("降到" in issue for issue in assess(report, "old", "new", {"real_acoustic_guitar"})))
        report["groups"][-1] = row("new", "regression", .81)
        self.assertEqual(assess(report, "old", "new", {"real_acoustic_guitar"}), [])


if __name__ == "__main__":
    unittest.main()
