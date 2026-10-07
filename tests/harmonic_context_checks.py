"""Offline acoustic-only boundary, decomposed evidence and local preservation."""
from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.audio_verification import synthesize,SR
from tools.cross_evidence import CrossEvidence,review_chords
from tools.harmonic_context import HarmonicContext,components


def notes():
    return [dict(start=a+.05,end=b-.05,midi=m,velocity=.7) for a,b,ps in [(0,3,(48,52,55)),(3,6,(45,52,60))] for m in ps]


class HarmonicTests(unittest.TestCase):
    def test_model_free_boundary_can_recover_a_missing_change_without_extra_vote(self):
        source=notes();audio=synthesize(source,6)
        cross=CrossEvidence({'methods':{'chordino':[dict(start=0,end=6,chord='C')]},'harmony_notes':source},6,'gaps')
        output,summary=review_chords(audio,[],cross)
        self.assertEqual([s['chord'] for s in output],['C','Am'])
        self.assertLess(abs(output[1]['start']-3),.3)
        self.assertEqual(summary['acoustic_supported_changes'],1)
        self.assertTrue(summary['acoustic_proposals_not_extra_votes'])
        self.assertEqual(summary['acoustic_boundaries'],1)
        self.assertIsNotNone(output[1]['refinement']['components']['third'])

    def test_silence_volume_and_arpeggios_do_not_force_chord_changes(self):
        silent=np.zeros(6*SR)
        self.assertFalse(HarmonicContext(silent).boundaries)
        source=[dict(start=.05,end=5.95,midi=m,velocity=.7) for m in (48,52,55)]
        audio=synthesize(source,6);audio[3*SR:]*=.2
        self.assertFalse(HarmonicContext(audio,source).boundaries)
        cross=CrossEvidence({'methods':{'chordino':[dict(start=0,end=6,chord='C')]},'harmony_notes':source},6,'gaps')
        self.assertEqual(review_chords(audio,[],cross)[1]['changed_segments'],0)

    def test_local_range_preserves_outside_and_manual_exactly(self):
        source=notes();audio=synthesize(source,6)
        segments=[dict(start=0,end=2,chord='C',manual=True),dict(start=2,end=6,chord='C')]
        cross=CrossEvidence({'review_baseline':{'method':'ensemble','segments':segments},'harmony_notes':source},6,'gaps')
        output,summary=review_chords(audio,[],cross,review_range=(2.5,5),dense=True)
        self.assertEqual(output[0],segments[0])
        self.assertEqual(output[1],dict(start=2,end=2.5,chord='C'))
        self.assertEqual(output[-1],dict(start=5,end=6,chord='C'))
        self.assertTrue(any(s['chord']=='Am' for s in output))
        self.assertTrue(all(a['end']==b['start'] for a,b in zip(output,output[1:])))
        self.assertEqual(segments[-1],dict(start=2,end=6,chord='C'))

    def test_unsupported_extensions_do_not_win_by_extra_template_freedom(self):
        source=[dict(start=.05,end=5.95,midi=m,velocity=.7) for m in (45,52,60)]
        cross=CrossEvidence({'methods':{'chordino':[dict(start=0,end=6,chord='C')]},'harmony_notes':source},6,'gaps')
        output,_=review_chords(synthesize(source,6),[],cross,review_range=(0,6),dense=True)
        self.assertEqual(output[0]['chord'],'Am')
        self.assertNotIn('7',output[0]['chord'])

    def test_invalid_range_and_decomposed_slash_bass(self):
        with self.assertRaises(ValueError):HarmonicContext(np.zeros(SR),review_range=(0,float('nan')))
        from tools.audio_verification import spectrum
        source=[dict(start=.05,end=.95,midi=m,velocity=.7) for m in (47,48,52,55)]
        spec=spectrum(synthesize(source,1),.5)
        result=components('Cmaj7/B',[spec,spec],source,0,1)
        self.assertEqual(result['root']['pitch_class'],0)
        self.assertEqual(result['bass_target']['pitch_class'],11)
        self.assertEqual(result['third']['pitch_class'],4)
        self.assertEqual(result['seventh']['pitch_class'],11)

    def test_arpeggios_and_wrong_pitch_context_do_not_invent_harmony(self):
        source=[dict(start=i*.45+.02,end=i*.45+.43,midi=(48,52,55)[i%3],velocity=.7) for i in range(12)]
        audio=synthesize(source,6)
        data={'methods':{'chordino':[dict(start=0,end=6,chord='C')]},'harmony_notes':source}
        output,summary=review_chords(audio,[],CrossEvidence(data,6,'gaps'))
        self.assertTrue(all(s['chord']=='C' for s in output))
        self.assertEqual(summary['changed_segments'],0)
        correct=[dict(start=.05,end=5.95,midi=m,velocity=.7) for m in (48,52,55)]
        data['harmony_notes']=[dict(start=.05,end=5.95,midi=m,velocity=.7) for m in (45,52,60)]
        output,summary=review_chords(synthesize(correct,6),[],CrossEvidence(data,6,'gaps'),review_range=(0,6),dense=True)
        self.assertEqual(output[0]['chord'],'C')
        self.assertEqual(summary['changed_segments'],0)


if __name__=='__main__':unittest.main()
