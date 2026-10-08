import json
import tempfile
import unittest
import wave
from pathlib import Path

from tools.import_reference_corpus import import_corpus


class ImportReferenceCorpusTests(unittest.TestCase):
    def test_import_and_split_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            with wave.open(str(source / "a.wav"), "wb") as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(8000)
                stream.writeframes(b"\0\0" * 8000)
            (source / "a.json").write_text(json.dumps({"notes": [{"start": 0, "end": .5, "midi": 60}]}))
            row = {"id": "a", "performer": "person", "split": "development",
                "source_condition": "real_acoustic_guitar", "audio": "a.wav", "reference": "a.json",
                "source_url": "https://example.test/owned", "license": "owned", "annotator": "human"}
            (source / "intake.json").write_text(json.dumps({"records": [row]}))
            manifest = import_corpus(source, root / "corpus")
            self.assertEqual(manifest["model_training_overlap"], "unknown_not_audited")
            self.assertTrue((root / "corpus/clips/a/audio.wav").is_file())
            (source / "intake.json").write_text(json.dumps({"records": [row, {**row,
                "id": "b", "split": "regression"}]}))
            with self.assertRaisesRegex(ValueError, "performer"):
                import_corpus(source, root / "invalid")


if __name__ == "__main__":
    unittest.main()
