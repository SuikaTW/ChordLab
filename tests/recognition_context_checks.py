"""Synthetic controls for context proposals; independent of trained scorer."""
from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.audio_verification import synthesize, SR
from tools.recognition_context import refine_boundary, audio_repeats, sequence_choices
from tools.cross_evidence import CrossEvidence, review_chords
from tools.event_verification import refine_events
from tools.note_plausibility import features, predict


class ContextTests(unittest.TestCase):
    def test_boundary_preserves_real_change_without_beats(self):
        notes = [dict(start=start, end=end, midi=pitch) for start, end, pitches in
                 [(.05, 2.73, (48, 52, 55)), (2.74, 5.9, (45, 52, 60))] for pitch in pitches]
        audio = synthesize(notes, 6)
        refined = refine_boundary(audio, 2.88)
        self.assertLess(abs(refined - 2.74), .13)
        cross = CrossEvidence({'methods': {'chordino': [dict(start=0, end=6, chord='C')]}, 'harmony_notes': notes}, 6, 'gaps')
        output, info = review_chords(audio, notes, cross, context_review=True)
        self.assertTrue(any(segment['chord'] == 'Am' for segment in output))
        self.assertTrue(all(a['end'] == b['start'] for a, b in zip(output, output[1:])))

    def test_sequence_cannot_invent_unvalidated_chords(self):
        rows = [[dict(chord='C', loss=.2)], [dict(chord='C', loss=.21), dict(chord='Am', loss=.20)], [dict(chord='C', loss=.2)]]
        self.assertEqual([row['chord'] for row in sequence_choices(rows)], ['C', 'C', 'C'])
        rows[1][1]['loss'] = .05
        self.assertEqual(sequence_choices(rows)[1]['chord'], 'Am')

    def test_audio_repeats_find_missing_prediction_without_copying(self):
        truth = [dict(start=base + .2 + i * .65, end=base + .65 + i * .65, midi=pitch)
                 for base in (0, 4.5) for i, pitch in enumerate((48, 55, 59, 64))]
        audio = synthesize(truth, 9)
        incomplete = [note for note in truth if note['start'] != truth[5]['start']]
        result = audio_repeats(audio, incomplete)
        self.assertTrue(result['pairs'])
        self.assertTrue(any(row['midi'] == truth[5]['midi'] and abs(row['start'] - truth[5]['start']) < .2 for row in result['suggestions']))
        self.assertEqual(len(incomplete), 7)
        self.assertFalse(audio_repeats(np.zeros(SR * 9), [])['pairs'])

    def test_fast_events_still_require_independent_audio(self):
        truth = [dict(start=.2, end=.32, midi=52), dict(start=.45, end=.57, midi=55)]
        cross = CrossEvidence({'models': {name: {'notes': truth} for name in ('basic_pitch', 'gaps')}}, 1., 'gaps')
        audio = synthesize(truth, 1.)
        revised, _ = refine_events(audio, truth[:1], cross, context_review=True)
        self.assertTrue(any(note['midi'] == 55 for note in revised))
        silent, _ = refine_events(np.zeros(SR), truth[:1], cross, context_review=True)
        self.assertEqual(silent, truth[:1])

    def test_scorer_features_finite_for_silence(self):
        values = features(np.zeros(SR), 64, .2, .5)
        self.assertTrue(np.isfinite(values).all())
        self.assertEqual(len(values), 6)


if __name__ == '__main__':
    unittest.main()
