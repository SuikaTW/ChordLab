import json
import tempfile
import unittest
from pathlib import Path

from tools.corpus_summary import summarize


class CorpusSummaryTests(unittest.TestCase):
    def test_weighted_chords_and_clip_identity_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manifest.json").write_text(json.dumps({"records": [{"id": "one"}, {"id": "two"}]}))
            rows = []
            for clip, seconds, agreement, matched in (("one", 10, .5, 1), ("two", 30, .9, 2)):
                rows.append({"id": clip, "engine": "chordino", "split": "development",
                    "source_condition": "real_acoustic_guitar", "chord_annotations": [{"metrics": {
                        "annotated_seconds": seconds, "exact_chord_duration_agreement": agreement,
                        "boundary_matched": matched, "boundary_predicted_count": 3,
                        "boundary_reference_count": 4}}]})
            (root / "report.json").write_text(json.dumps({"reports": rows,
                "pipeline_sha256": "p", "evaluation_sha256": "e", "manifest_sha256": "m",
                "model_training_overlap": "unknown"}))
            result = summarize(root)
            self.assertEqual(result["chord_metrics_first_annotation_weighted"]["chordino"]["exact_chord_duration_agreement"], .8)
            self.assertEqual(result["chord_metrics_first_annotation_weighted"]["chordino"]["boundary_f1"], round(2 * 3 / 14, 4))


if __name__ == "__main__":
    unittest.main()
