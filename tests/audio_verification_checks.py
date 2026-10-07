"""Synthetic held-out timbres and conservative guards; run with .venv-guitar."""
import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.audio_verification import SR, verify, harmonic_profile, combine_profiles


def render(notes, duration=2, weights=(1,.65,.42,.3,.21,.15,.11,.08)):
    samples = np.zeros(round(duration*SR))
    for note in notes:
        first, last = round(note["start"]*SR), round(note["end"]*SR)
        time = np.arange(last-first)/SR
        frequency = 440*2**((note["midi"]-69)/12)
        wave = sum(weight*np.sin(2*np.pi*frequency*(i+1)*time) for i,weight in enumerate(weights))
        samples[first:last] += wave*np.minimum(1,time/.01)*np.exp(-time*2)*.1
    return samples


class VerificationTests(unittest.TestCase):
    def test_wrong_octave_is_repaired_without_retiming_or_overwriting_source(self):
        truth = [dict(start=.1,end=.8,midi=52,velocity=.7), dict(start=1,end=1.7,midi=55,velocity=.7)]
        wrong = [{**note,"midi":note["midi"]+12,"model_string":5,"model_fret":note["midi"]-52} for note in truth]
        result, summary = verify(render(truth), wrong)
        self.assertEqual([note["midi"] for note in result], [52,55])
        self.assertEqual(summary["changed_notes"], 2)
        self.assertEqual(summary["rechecked_changes"],2)
        self.assertLess(summary["verified_loss"], summary["baseline_loss"])
        self.assertEqual([note["start"] for note in result], [.1,1])
        self.assertEqual(wrong[0]["midi"], 64)
        self.assertNotIn("model_string", result[0])

    def test_correct_repeated_attacks_and_manual_notes_are_preserved(self):
        notes = [dict(start=.1,end=.4,midi=52),dict(start=.6,end=.9,midi=52)]
        result, summary = verify(render(notes), notes)
        self.assertEqual([note["midi"] for note in result], [52,52])
        self.assertEqual(summary["changed_notes"], 0)
        manual = [{**note,"midi":64,"edited":True} for note in notes]
        self.assertEqual(verify(render(notes),manual)[0],manual)

    def test_silence_short_dense_and_invalid_audio_do_not_generate_notes(self):
        notes = [dict(start=.1,end=.5,midi=64)]
        result, summary = verify(np.zeros(SR),notes)
        self.assertEqual(result[0]["midi"],64)
        self.assertEqual(summary["changed_notes"],0)
        short = [dict(start=.1,end=.15,midi=64)]
        self.assertEqual(verify(render(short),short)[1]["reviewed_notes"],0)
        for wrong in [np.array([float("nan")]*SR), np.zeros((SR,2))]:
            with self.assertRaises(ValueError): verify(wrong,notes)

    def test_only_confirmed_isolated_edits_can_calibrate_and_need_repeated_evidence(self):
        notes = [dict(start=.1,end=.7,midi=52,edited=True)]
        profile = harmonic_profile(render(notes),notes)
        self.assertIn("52",profile)
        self.assertEqual(combine_profiles([profile,profile]),{})
        self.assertIn("52",combine_profiles([profile,profile,profile]))
        self.assertEqual(harmonic_profile(render(notes),[{**notes[0],"edited":False}]),{})
        overlapping = [*notes,dict(start=.1,end=.7,midi=55,edited=True)]
        self.assertEqual(harmonic_profile(render(overlapping),overlapping),{})

    def test_held_out_timbres_octave_precision_and_correct_note_stability(self):
        changed = stable = total = 0
        for weights in [(1,.4,.3,.15), (1,.8,.2,.1), (.8,.5,.25,.12)]:
            for midi in [40,47,52,59,64,71]:
                notes = [dict(start=.1,end=.7,midi=midi)]
                audio = render(notes,weights=weights)
                changed += verify(audio,[{**notes[0],"midi":midi+12}])[0][0]["midi"] == midi
                stable += verify(audio,notes)[0][0]["midi"] == midi
                total += 1
        print(f"synthetic holdout: octave repairs {changed}/{total}; correct notes retained {stable}/{total}",flush=True)
        self.assertEqual(stable,total)
        self.assertGreaterEqual(changed,total*.8)


if __name__ == "__main__": unittest.main()
