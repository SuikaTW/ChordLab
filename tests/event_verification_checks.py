"""Independent synthetic truth; no downloads or production writes."""
from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.audio_verification import synthesize, SR
from tools.cross_evidence import CrossEvidence
from tools.event_verification import refine_events, repeated_phrases

def note(pitch,start=.2,end=.6,**extra):
    return dict(midi=pitch,start=start,end=end,velocity=.7,**extra)

def evidence(notes):
    return CrossEvidence({"models":{n:{"notes":notes} for n in ("basic_pitch","gaps")}},1.5,"gaps")

class EventTests(unittest.TestCase):
    def test_onset_repair_requires_audio_and_independent_timing(self):
        truth=[note(52,.2,.6)]
        wrong=[note(52,.26,.6)]
        output,summary=refine_events(synthesize(truth,1.5),wrong,evidence(truth))
        self.assertEqual(output[0]["start"],.2)
        self.assertEqual(summary["adjusted_onsets"],1)
        self.assertEqual(wrong[0]["start"],.26)
        manual=[{**wrong[0],"edited":True}]
        self.assertEqual(refine_events(synthesize(truth,1.5),manual,evidence(truth))[0],manual)
    def test_missing_note_needs_two_models_and_audio(self):
        truth=[note(52),note(64,.8,1.2)]
        original=[truth[0]]
        output,summary=refine_events(synthesize(truth,1.5),original,evidence(truth))
        self.assertEqual([n["midi"] for n in output],[52,64])
        self.assertEqual(summary["added_notes"],1)
        self.assertEqual(original,[truth[0]])
        quiet,info=refine_events(np.zeros(round(1.5*SR)),original,evidence(truth))
        self.assertEqual(quiet,original); self.assertEqual(info["added_notes"],0)

    def test_correlated_models_and_original_mix_veto(self):
        truth=[note(52),note(64,.8,1.2)]
        correlated=CrossEvidence({"models":{n:{"notes":truth} for n in ("gaps","hybrid")}},1.5,"gaps")
        self.assertEqual(refine_events(synthesize(truth,1.5),truth[:1],correlated)[1]["added_notes"],0)
        output,info=refine_events(synthesize(truth,1.5),truth[:1],evidence(truth),np.zeros(round(1.5*SR)))
        self.assertEqual(output,truth[:1]); self.assertEqual(info["added_notes"],0)
        self.assertTrue(info["original_mix_checked"])

    def test_repeated_attacks_manual_and_sustains_are_not_removed(self):
        source=[note(52,.2,1.2,edited=True)]
        votes=[note(52,.2,.6),note(52,.8,1.2)]
        output,info=refine_events(synthesize(votes,1.5),source,evidence(votes))
        self.assertEqual(output,source)
        self.assertEqual(info["removed_notes"],0)
        self.assertTrue(any(s["kind"]=="possible_retrigger" for s in info["suggestions"]))

    def test_no_harmonic_hallucination_or_misaligned_mix(self):
        truth=[note(52,.2,1.2)]
        votes=truth+[note(64,.2,1.2)]
        self.assertEqual(refine_events(synthesize(truth,1.5),truth,evidence(votes))[1]["added_notes"],0)
        with self.assertRaises(ValueError):
            refine_events(synthesize(truth,1.5),truth,evidence(truth),np.zeros(SR))

    def test_repeated_phrases_only_report_not_create_truth(self):
        notes=[note(pitch,base+i*.3,base+i*.3+.2) for base in (0,3) for i,pitch in enumerate((52,55,59,64))]
        info=repeated_phrases(notes)
        self.assertGreater(info["matched_patterns"],0)
        self.assertIn("not_copy_or_training",info["policy"])

if __name__=="__main__": unittest.main()
