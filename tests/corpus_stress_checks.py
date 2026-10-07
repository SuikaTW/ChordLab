from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.corpus_stress import render


class StressTests(unittest.TestCase):
    def test_effect_preserves_length_silence_and_does_not_add_latency(self):
        signal=np.zeros(16000);signal[1234]=.2
        output=render(signal,16000,'effect_rendered')
        self.assertEqual(len(output),len(signal))
        self.assertEqual(np.argmax(output),1234)
        self.assertEqual(np.count_nonzero(output),1)
    def test_mix_is_repeatable_bounded_and_never_alters_reference(self):
        signal=np.sin(np.arange(16000)*.1)*.2;copy=signal.copy()
        first=render(signal,16000,'synthetic_drum_mix')
        self.assertTrue(np.array_equal(first,render(signal,16000,'synthetic_drum_mix')))
        self.assertTrue(np.array_equal(signal,copy))
        self.assertEqual(len(signal),len(first))
        self.assertLessEqual(np.max(np.abs(first)),1)
    def test_unknown_condition_is_rejected(self):
        with self.assertRaises(ValueError):render(np.zeros(4),16000,'real_electric')


if __name__=='__main__':unittest.main()
