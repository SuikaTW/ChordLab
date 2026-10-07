"""Offline provenance/rounding/exclusion/split/integrity regressions."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import reference_corpus as corpus
from tools.benchmark_corpus import weighted_chords

def annotation():
    return {"annotations":[{"namespace":"note_midi","annotation_metadata":{"data_source":str(i)},
        "data":[{"time":.2,"duration":.4,"value":corpus.TUNING[i]+.07}]} for i in range(6)]}

class CorpusTests(unittest.TestCase):
    def test_missing_prediction_is_wrong_not_an_exception_or_ignored_time(self):
        reference=[dict(start=0,end=1,chord="C")]
        result=weighted_chords(reference,[dict(start=.5,end=1,chord="C:maj")],1)
        self.assertEqual(result["exact_chord_duration_agreement"],.5)
        self.assertEqual(result["annotated_seconds"],1)
    def test_floating_annotation_pitch_is_rounded_not_truncated(self):
        data=annotation(); data["annotations"][0]["data"][0]["value"]=40.96
        result=corpus.parse_annotations(data)
        self.assertEqual(result["notes"][0]["midi"],41)
        self.assertEqual(result["notes"][0]["fret"],1)
    def test_invalid_reference_is_rejected(self):
        data=annotation();data["annotations"][0]["data"][0]["value"]=39
        with self.assertRaises(ValueError): corpus.parse_annotations(data)
        data=annotation();data["annotations"][0]["data"][0]["time"]=float("nan")
        with self.assertRaises(ValueError): corpus.parse_annotations(data)
        data=annotation();data["annotations"][1]["annotation_metadata"]["data_source"]="0"
        with self.assertRaises(ValueError): corpus.parse_annotations(data)
    def test_known_bad_sources_excluded_and_performers_do_not_cross_split(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); archives=root/"archives";archives.mkdir()
            names=[f"{i:02}_BN1-120-C_{style}" for i in range(3) for style in ("comp","solo")]+list(corpus.EXCLUDED)
            with zipfile.ZipFile(archives/"annotation.zip","w") as labels,zipfile.ZipFile(archives/"audio_mono-mic.zip","w") as audio:
                for name in names:
                    labels.writestr("annotation/"+name+".jams",json.dumps(annotation()))
                    audio.writestr("audio/"+name+"_mic.wav",b"test audio")
            checksums={name:corpus.checksum(archives/name,"md5") for name in corpus.FILES}
            with patch.object(corpus,"FILES",checksums):
                manifest=corpus.build(root)
                self.assertEqual(len(manifest["records"]),6)
                dev={r["performer"] for r in manifest["records"] if r["split"]=="development"}
                reg={r["performer"] for r in manifest["records"] if r["split"]=="regression"}
                self.assertFalse(dev&reg)
                self.assertTrue(all(r["id"] not in corpus.EXCLUDED for r in manifest["records"]))
                reference=root/manifest["records"][0]["reference"]
                reference.write_text("{\"notes\":[]}")
                with self.assertRaises(ValueError): corpus.build(root)
    def test_corpus_does_not_claim_independent_blind_test(self):
        self.assertEqual(len(corpus.EXCLUDED),3)
        self.assertTrue(corpus.SOURCE.startswith("https://zenodo.org/"))

if __name__=="__main__": unittest.main()
