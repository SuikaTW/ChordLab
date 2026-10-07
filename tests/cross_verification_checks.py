"""Run with .venv-guitar. No downloads or production writes."""
from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.audio_verification import verify, synthesize, SR
from tools.cross_evidence import CrossEvidence, tones, review_chords


def event(midi,**extra):
    return dict(start=.2,end=.9,midi=midi,velocity=.7,**extra)


def evidence(original=52,alternative=54):
    return {"models":{
        "gaps":{"notes":[event(original)]},
        "hybrid":{"notes":[event(original)]},
        "basic_pitch":{"notes":[event(alternative)]},
        "tabcnn":{"notes":[event(alternative,model_string=2,model_fret=alternative-50,fingering_score=.9)]}},
        "methods":{"chordino":[{"start":0,"end":1.2,"chord":"D"}],
                   "btc":[{"start":0,"end":1.2,"chord":"D"}]}}


class CrossTests(unittest.TestCase):
    def test_independent_two_model_candidate_can_repair_a_whole_tone(self):
        wrong=[event(52)]
        cross=CrossEvidence(evidence(),1.2,"hybrid")
        result,summary=verify(synthesize([event(54)],1.2),wrong,cross=cross)
        self.assertEqual(result[0]["midi"],54)
        self.assertEqual(summary["changed_notes"],1)
        self.assertEqual(summary["independent_models"],["basic_pitch","gaps","tabcnn"])
        self.assertEqual(summary["rechecked_changes"],1)
        self.assertEqual(result[0]["model_string"],2)
        self.assertEqual(result[0]["model_fret"],4)
        self.assertEqual(wrong[0]["midi"],52)
        self.assertEqual(summary["changes"][0]["models"],["basic_pitch","tabcnn"])

    def test_correlated_hybrid_does_not_double_vote_or_propose_whole_tone_alone(self):
        data=evidence()
        data["models"].pop("basic_pitch"); data["models"].pop("tabcnn")
        data["models"]["gaps"]["notes"]=[event(54)]
        data["models"]["hybrid"]["notes"]=[event(54)]
        cross=CrossEvidence(data,1.2,"gaps")
        self.assertEqual(list(cross.streams),["gaps"])
        context=cross.context(event(52))
        self.assertNotIn(54,context["alternatives"])

    def test_agreed_polyphonic_chord_is_not_a_conflict_just_because_it_has_other_notes(self):
        notes=[event(pitch) for pitch in (50,54,57)]
        models={name:{"notes":notes} for name in ("gaps","basic_pitch")}
        models["tabcnn"]={"notes":[event(50,model_string=2,model_fret=0),event(54,model_string=2,model_fret=4),event(57,model_string=3,model_fret=2)]}
        cross=CrossEvidence({"models":models,"methods":{"chordino":[{"start":0,"end":1.2,"chord":"D"}]}},1.2,"gaps")
        self.assertFalse(cross.context(event(54))["conflict"])

    def test_true_outside_chord_tone_survives_wrong_consensus_and_wrong_chord(self):
        data=evidence(54,55)
        for method in data["methods"].values(): method[0]["chord"]="C"
        cross=CrossEvidence(data,1.2,"gaps")
        result,summary=verify(synthesize([event(54)],1.2),[event(54)],cross=cross)
        self.assertEqual(result[0]["midi"],54)
        self.assertTrue(result[0]["cross_conflict"])
        self.assertEqual(summary["changed_notes"],0)

    def test_no_evidence_never_becomes_trained_truth_and_manual_notes_stay(self):
        cross=CrossEvidence({"models":{},"methods":{}},1.2,"gaps")
        result,summary=verify(np.zeros(round(1.2*SR)),[event(52,edited=True)],cross=cross)
        self.assertEqual(result,[event(52,edited=True)])
        self.assertEqual(summary["independent_models"],[])
        self.assertEqual(summary["changed_notes"],0)

    def test_invalid_tab_pitch_and_derived_chords_are_not_votes(self):
        data=evidence()
        data["models"]["tabcnn"]["notes"][0]["model_fret"]=3
        data["methods"]["basic_pitch"]=data["methods"]["chordino"]
        data["methods"]["ensemble"]=data["methods"]["chordino"]
        cross=CrossEvidence(data,1.2,"hybrid")
        self.assertEqual(cross.invalid_tab_events,1)
        self.assertNotIn("tabcnn",cross.streams)
        self.assertNotIn(54,cross.context(event(52))["alternatives"])
        self.assertEqual(set(cross.chords),{"chordino","btc"})

    def test_aliases_extended_chords_and_source_duration_guards(self):
        self.assertEqual(tones("Db:min7"),tones("C#m7"))
        self.assertIn(2,tones("C/D"))
        self.assertEqual(tones("Cmaj9"),{0,2,4,7,11})
        self.assertIsNone(tones("N")); self.assertIsNone(tones("Cunknown"))
        data=evidence(); data["models"]["gaps"]["duration"]=9
        with self.assertRaises(ValueError): CrossEvidence(data,1.2,"gaps")
        data=evidence(); data["models"]["basic_pitch"]["duration"]=.9
        self.assertIn("basic_pitch",CrossEvidence(data,1.2,"gaps").streams)

    def test_independent_chord_candidate_needs_audio_and_note_evidence(self):
        data=evidence()
        data["methods"]={"chordino":[{"start":0,"end":1.2,"chord":"C"}],"btc":[{"start":0,"end":1.2,"chord":"Am"}]}
        notes=[event(pitch) for pitch in (45,52,60)]
        cross=CrossEvidence(data,1.2,"gaps")
        output,summary=review_chords(synthesize(notes,1.2),notes,cross)
        self.assertEqual(output[0]["chord"],"Am")
        self.assertEqual(summary["changed_segments"],1)
        self.assertEqual(data["methods"]["chordino"][0]["chord"],"C")
        correct=[event(pitch) for pitch in (48,52,55)]
        self.assertEqual(review_chords(synthesize(correct,1.2),correct,cross)[0][0]["chord"],"C")
        data["methods"]["chordino"][0]["manual"]=True
        manual=CrossEvidence(data,1.2,"gaps")
        self.assertEqual(review_chords(synthesize(notes,1.2),notes,manual)[0][0]["chord"],"C")

    def test_chord_recheck_never_relabels_silence_or_unsupported_chords(self):
        data=evidence()
        data["methods"]["chordino"][0]["chord"]="C"
        data["methods"]["btc"][0]["chord"]="Am"
        cross=CrossEvidence(data,1.2,"gaps")
        self.assertEqual(review_chords(np.zeros(round(1.2*SR)),[event(45)],cross)[1]["changed_segments"],0)
        self.assertEqual(review_chords(synthesize([event(45)],1.2),[],cross)[1]["changed_segments"],0)


if __name__=="__main__": unittest.main()
