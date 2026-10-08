"""Bounded event boundaries, nominated by models and vetoed by local audio.

No reference labels, beat quantization, source edits or technique guesses.
"""
import bisect
from functools import lru_cache
import numpy as np
from tools.audio_verification import SR, FREQ, spectrum


class PitchEnvelope:
    def __init__(self, samples):
        self.samples = samples

    @lru_cache(maxsize=512)
    def frame(self, tick):
        return spectrum(self.samples, tick / 100)

    def energy(self, pitch, center):
        frequency = 440 * 2 ** ((pitch - 69) / 12)
        bins = self.frame(round(max(0, center) * 100))
        return float(bins[np.abs(FREQ - frequency) <= 10].max(initial=0))

    def drops(self, pitch, boundary):
        before = np.median([self.energy(pitch, boundary - delta) for delta in (.08, .04)])
        after = max(self.energy(pitch, boundary + delta) for delta in (.08, .12))
        return before > 1e-5 and after < before * .3

    def rises(self, pitch, boundary):
        before = max(self.energy(pitch, boundary - delta) for delta in (.08, .05))
        after = min(self.energy(pitch, boundary + delta) for delta in (.06, .1))
        return after > max(1e-5, before * 1.8)


def nominations(cross, pitch, start, tolerance=.08):
    matched = {}
    for family, (stream, starts) in cross.streams.items():
        low, high = bisect.bisect_left(starts, start - tolerance), bisect.bisect_right(starts, start + tolerance)
        candidates = [n for n in stream[low:min(high, low + 64)] if n['midi'] == pitch]
        if candidates:
            matched[family] = min(candidates, key=lambda n: abs(n['start'] - start))
    return matched


def harmonic_conflict(notes, pitch, center, excluded=None):
    """A lower active note can explain the candidate fundamental as an overtone."""
    for note in notes:
        if note is excluded or not note['start'] <= center < note['end'] or note['midi'] >= pitch:
            continue
        ratio = 2 ** ((pitch - note['midi']) / 12)
        if any(abs(12 * np.log2(ratio / harmonic)) < .2 for harmonic in (2, 3, 4)):
            return True
    return False


def refine_offsets(notes, cross, envelope, original=None):
    edits, reviewed = [], 0
    for index, note in enumerate(notes):
        if note.get('edited') or note['end'] - note['start'] < .2:
            continue
        voters = nominations(cross, note['midi'], note['start'])
        ends = sorted(float(n['end']) for n in voters.values())
        pairs = [(a, b) for i, a in enumerate(ends) for b in ends[i + 1:] if b - a <= .06]
        if not pairs:
            continue
        proposed = float(np.median(min(pairs, key=lambda pair: abs(np.mean(pair) - note['end']))))
        delta = abs(proposed - note['end'])
        if not .06 < delta <= min(.3, (note['end'] - note['start']) * .5) or proposed - note['start'] < .12:
            continue
        if reviewed >= 256:
            break
        reviewed += 1
        if harmonic_conflict(notes, note['midi'], proposed - .04, note):
            continue
        if not envelope.drops(note['midi'], proposed) or original and not original.drops(note['midi'], proposed):
            continue
        # Do not extend through silence or clip a still-audible sustain.
        earlier = min(proposed, note['end'])
        later = max(proposed, note['end'])
        middle = (earlier + later) / 2
        inside = envelope.energy(note['midi'], proposed - .08)
        between = envelope.energy(note['midi'], middle)
        if proposed > note['end'] and between < inside * .5:
            continue
        if proposed < note['end'] and between > inside * .4:
            continue
        before = note['end']
        note.update(end=round(proposed, 4), event_changed=True, offset_changed=True)
        edits.append(dict(kind='offset', index=index, start=note['start'], before=before, after=note['end']))
    return edits, reviewed


def split_retrigger(output, pitch, start, end, voters, peaks, envelope, original=None, fast=False):
    minimum = .09 if fast else .18
    sustaining = [n for n in output if n['midi'] == pitch and n['start'] + minimum < start < n['end'] - .08]
    if len(sustaining) != 1 or sustaining[0].get('edited') or len(output) >= 20000:
        return None
    at = bisect.bisect_left(peaks, start - .025)
    if at >= len(peaks) or peaks[at] > start + .025 or len(voters) < 2 or end - start < minimum:
        return None
    if harmonic_conflict(output, pitch, start + .06, sustaining[0]):
        return None
    if not envelope.rises(pitch, start) or original and not original.rises(pitch, start):
        return None
    old = sustaining[0]
    before = old['end']
    old.update(end=round(start, 4), event_changed=True, retrigger_split=True)
    output.append(dict(start=round(start, 4), end=round(end, 4), midi=pitch,
        velocity=float(np.median([n.get('velocity', .5) for n in voters.values()])),
        event_changed=True, retrigger_added=True, fingering_uncertain=True))
    return dict(kind='retrigger', start=start, midi=pitch, previous_end=before, models=sorted(voters))
