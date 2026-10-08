"""Bounded acoustic context experiments; scores are evidence, not probabilities."""
from __future__ import annotations
import numpy as np
from tools.audio_verification import SR, FREQ, spectrum


def chroma(samples, center):
    spec = spectrum(samples, center)
    pitches = np.arange(40, 89)
    values = np.array([spec[np.abs(FREQ - 440 * 2 ** ((pitch - 69) / 12)) < 8].max(initial=0)
                       for pitch in pitches])
    profile = np.bincount(pitches % 12, weights=np.sqrt(np.maximum(0, values - values.max(initial=0) * .03)), minlength=12)
    return profile / max(1e-12, float(np.linalg.norm(profile)))


def refine_boundary(samples, coarse):
    """Locate an existing harmonic proposal at 20 ms resolution, never quantize."""
    duration = len(samples) / SR
    choices = []
    for time in np.arange(max(.16, coarse - .22), min(duration - .16, coarse + .221), .02):
        left = (chroma(samples, time - .12) + chroma(samples, time - .06)) / 2
        right = (chroma(samples, time + .06) + chroma(samples, time + .12)) / 2
        if min(np.linalg.norm(left), np.linalg.norm(right)) < .5:
            continue
        distance = 1 - float(left @ right / max(1e-12, np.linalg.norm(left) * np.linalg.norm(right)))
        choices.append((distance, float(time)))
    if not choices:
        return coarse
    strongest = max(score for score, _ in choices)
    # Flat plateaus are ambiguous; prefer the original proposal within that plateau.
    return round(min((time for score, time in choices if score >= strongest - .01), key=lambda time: abs(time - coarse)), 4)


def sequence_choices(rows, switch_cost=.025):
    """Choose only locally accepted chord alternatives; no key/progression prior."""
    if not rows:
        return []
    paths = [(0., [])]
    for row in rows:
        next_paths = []
        for option in row:
            candidates = [(cost + float(option['loss']) + (switch_cost if path and path[-1]['chord'] != option['chord'] else 0), path + [option])
                          for cost, path in paths]
            next_paths.append(min(candidates, key=lambda item: item[0]))
        paths = next_paths
    return min(paths, key=lambda item: item[0])[1]


def audio_repeats(samples, notes, max_pairs=12):
    """Match 3 s acoustic phrases with bounded time stretching, then audit notes.

    Search is bounded to 600 windows and 12 pairs. Repeated audio does not count
    as an independent model vote and never supplies training labels.
    """
    duration = len(samples) / SR
    if duration < 6:
        return dict(pairs=[], suggestions=[], policy='audio_alignment_advisory_only')
    step = max(1.5, (duration - 3) / 599)
    starts = np.arange(0, duration - 3 + 1e-6, step)
    grid = np.arange(.125, 3, .25)
    windows = np.array([[chroma(samples, start + offset) for offset in grid] for start in starts])
    descriptors = windows.reshape(len(windows), -1)
    norms = np.linalg.norm(descriptors, axis=1)
    descriptors /= np.maximum(1e-12, norms[:, None])
    similarities = descriptors @ descriptors.T
    pairs = []
    for i in range(len(starts)):
        # Exclude silence, drones and windows without harmonic variation.
        if norms[i] < 2 or np.mean(np.std(windows[i], axis=0)) < .035:
            continue
        choices = np.flatnonzero((starts >= starts[i] + 3.5) & (similarities[i] > .93))
        for j in choices:
            if norms[j] >= 2:
                pairs.append((float(similarities[i, j]), i, int(j)))
    selected, suggestions = [], []
    for similarity, i, j in sorted(pairs, reverse=True):
        a, b = float(starts[i]), float(starts[j])
        if any(abs(a - pair['source_start']) < 1 and abs(b - pair['target_start']) < 1 for pair in selected):
            continue
        best = (similarity, 1., 0.)
        for scale in (.94, 1., 1.06):
            for shift in (-.1, 0., .1):
                target_times = b + shift + grid * scale
                if target_times[0] < 0 or target_times[-1] >= duration:
                    continue
                target = np.array([chroma(samples, time) for time in target_times])
                score = float(np.mean(np.sum(windows[i] * target, axis=1)))
                if score > best[0]:
                    best = (score, scale, shift)
        score, scale, shift = best
        if score < .94:
            continue
        selected.append(dict(source_start=a, target_start=round(b + shift, 4), duration=3., scale=scale, similarity=round(score, 4)))
        # Both directions, with target-audio support and a hard suggestion limit.
        for source, target, ratio in ((a, b + shift, scale), (b + shift, a, 1 / scale)):
            for note in notes:
                if not source + .15 <= note['start'] < source + 2.7 or note.get('edited'):
                    continue
                time = target + (note['start'] - source) * ratio
                if any(other['midi'] == note['midi'] and abs(other['start'] - time) < .12 for other in notes):
                    continue
                profile = chroma(samples, time + .08)
                frequency = 440 * 2 ** ((note['midi'] - 69) / 12)
                fundamentals = []
                for center in (time + .06, time + .12):
                    observed = spectrum(samples, center)
                    fundamentals.append(observed[np.abs(FREQ - frequency) < 10].max(initial=0) /
                                        max(1e-9, observed.max(initial=0)))
                if profile[note['midi'] % 12] > .25 and min(fundamentals) >= .07 and len(suggestions) < 64:
                    suggestions.append(dict(kind='repeat_missing_candidate', start=round(time, 4), midi=note['midi'],
                        donor_start=note['start'], similarity=round(score, 4), requires_local_model_and_audio=True))
        if len(selected) >= max_pairs:
            break
    return dict(pairs=selected, suggestions=suggestions, policy='audio_alignment_advisory_only',
                limits=dict(windows=len(starts), pairs=max_pairs, suggestions=64))
