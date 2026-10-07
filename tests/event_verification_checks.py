"""Independent synthetic truth; no downloads or production writes."""
from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.audio_verification import synthesize, SR
from tools.cross_evidence import CrossEvidence
from tools.event_verification import refine_events, repeated_phrases, addition_gain, verification_centers

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

    def test_offset_shortening_requires_two_models_and_actual_drop(self):
        truth=[note(52,.2,.6)]
        source=[note(52,.2,.85)]
        output,info=refine_events(synthesize(truth,1.5),source,evidence(truth))
        self.assertEqual(output[0]['end'],.6)
        self.assertEqual(info['adjusted_offsets'],1)
        self.assertEqual(source[0]['end'],.85)
        held=synthesize(source,1.5)
        self.assertEqual(refine_events(held,source,evidence(truth))[0][0]['end'],.85)
        single=CrossEvidence({'models':{'gaps':{'notes':truth}}},1.5,'gaps')
        self.assertEqual(refine_events(synthesize(truth,1.5),source,single)[0][0]['end'],.85)

    def test_offset_extension_and_manual_original_veto(self):
        truth=[note(52,.2,.85)]
        source=[note(52,.2,.65)]
        audio=synthesize(truth,1.5)
        output,info=refine_events(audio,source,evidence(truth))
        self.assertEqual(output[0]['end'],.85)
        self.assertEqual(info['adjusted_offsets'],1)
        self.assertEqual(refine_events(audio,source,evidence(truth),np.zeros(round(1.5*SR)))[0],source)
        manual=[{**source[0],'edited':True}]
        self.assertEqual(refine_events(audio,manual,evidence(truth))[0],manual)

    def test_retrigger_split_has_independent_attack_and_energy_rise(self):
        truth=[note(52,.2,.6),note(52,.8,1.2)]
        source=[note(52,.2,1.2)]
        output,info=refine_events(synthesize(truth,1.5),source,evidence(truth))
        self.assertEqual(len(output),2)
        self.assertEqual(info['retrigger_splits'],1)
        self.assertEqual(output[1]['start'],.8)
        self.assertLessEqual(output[0]['end'],.8)
        self.assertEqual(source[0]['end'],1.2)
        continuous=synthesize(source,1.5)
        output,info=refine_events(continuous,source,evidence(truth))
        self.assertEqual(len(output),1)
        self.assertEqual(info['retrigger_splits'],0)
        output,info=refine_events(synthesize(truth,1.5),source,evidence(truth),continuous)
        self.assertEqual(len(output),1)
        self.assertEqual(info['retrigger_splits'],0)

    def test_complexity_penalty_and_late_windows(self):
        self.assertFalse(addition_gain(.5,.41,0))
        self.assertFalse(addition_gain(.5,.37,3))
        self.assertTrue(addition_gain(.5,.3,3))
        centers=verification_centers(.2,.6)
        self.assertEqual(len(centers),4)
        self.assertGreater(centers[-1]-centers[0],.15)
        # Two agreeing models must not turn an existing tone's tail into a note.
        truth=[note(52,.2,1.2)]
        votes=truth+[note(64,.8,1.1)]
        output,info=refine_events(synthesize(truth,1.5),truth,evidence(votes))
        self.assertEqual(len(output),1)
        self.assertEqual(info['added_notes'],0)

    def test_late_audio_disagreement_and_harmonic_offsets_are_not_forced(self):
        from tools.temporal_verification import PitchEnvelope, refine_offsets
        truth=[note(52,.2,.6)]
        source=[note(52,.2,.85)]
        # A mixture vetoes an offset edit when the same pitch keeps sounding.
        output,info=refine_events(synthesize(truth,1.5),source,evidence(truth),synthesize(source,1.5))
        self.assertEqual(output[0]['end'],.85)
        self.assertEqual(info['adjusted_offsets'],0)
        crowded=[note(40,.2,1.2),note(52,.2,.85)]
        edits,_=refine_offsets(crowded,evidence(truth),PitchEnvelope(synthesize(truth,1.5)))
        self.assertEqual(edits,[])
        self.assertEqual(crowded[1]['end'],.85)

    def test_model_end_disagreement_does_not_force_offset(self):
        truth=[note(52,.2,.6)]
        source=[note(52,.2,.85)]
        disagreement=CrossEvidence({'models':{'gaps':{'notes':truth},'basic_pitch':{'notes':source}}},1.5,'gaps')
        output,info=refine_events(synthesize(truth,1.5),source,disagreement)
        self.assertEqual(info['adjusted_offsets'],0)
        self.assertEqual(output[0]['end'],.85)

    def test_stricter_addition_evidence_is_advisory_not_a_recall_regression(self):
        truth=[note(52,.2,.6),note(64,.2,.6)]
        output,info=refine_events(synthesize(truth,1.5),truth[:1],evidence(truth))
        self.assertEqual([n['midi'] for n in output],[52,64])
        added=next(n for n in output if n['midi']==64)
        # An octave can be a real chord tone or an overtone. The additional
        # ambiguity cue must not silently erase this independently nominated
        # real note; mark it for review instead.
        self.assertTrue(added['addition_uncertain'])
        self.assertTrue(added['suspicious'])
        self.assertEqual(info['uncertain_additions'],1)

if __name__=="__main__": unittest.main()
