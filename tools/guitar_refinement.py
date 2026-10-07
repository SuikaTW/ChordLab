"""GAPS events + pitch-valid TabCNN evidence; never union noisy note lists.

Release proposals are diagnostic only until independently evaluated. Actual
events keep the GAPS timing, including repeated same-pitch attacks.
"""
import math
import numpy as np

STANDARD = (40, 45, 50, 55, 59, 64)


def release_proposal(envelope, first, last, step):
    segment = np.asarray(envelope[first:last], dtype=float)
    if len(segment) < 12 or not np.isfinite(segment).all():
        return None
    peak = float(segment.max())
    if peak < 1e-7:
        return None
    smooth = np.convolve(segment, np.ones(3) / 3, mode="same")
    peak_frame = int(np.argmax(smooth))
    hold = max(3, math.ceil(.08 / step))
    for index in range(max(peak_frame + 2, math.ceil(.08 / step)), len(smooth) - hold):
        if np.all(smooth[index:index + hold] < peak * .2) and float(np.max(smooth[index:])) < peak * .35:
            return round((first + index) * step, 4)
    return None


def fuse_notes(notes, probabilities, magnitudes, duration, step=512 / 22050):
    probabilities = np.asarray(probabilities)
    if probabilities.ndim != 3 or probabilities.shape[1:] != (6, 21) or not len(probabilities) or not np.isfinite(probabilities).all():
        raise ValueError("Invalid TabCNN evidence")
    if np.any(probabilities < 0) or np.any(probabilities > 1.001):
        raise ValueError("Invalid TabCNN scores")
    output, hints, uncertain, releases = [], 0, 0, 0
    magnitudes = np.asarray(magnitudes)
    if magnitudes.ndim != 2 or magnitudes.shape[0] != 192 or not magnitudes.shape[1] or not np.isfinite(magnitudes).all():
        raise ValueError("Invalid guitar spectral evidence")
    previous = {}
    repeated = 0
    for original in sorted(notes, key=lambda note: (note["start"], note["midi"])):
        note = dict(original)
        if not isinstance(note["midi"], int) or isinstance(note["midi"], bool) or not 36 <= note["midi"] <= 99:
            raise ValueError("Invalid GAPS pitch")
        start, end, midi = float(note["start"]), float(note["end"]), int(note["midi"])
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= duration + .01):
            raise ValueError("Invalid GAPS event timing")
        if midi in previous and start - previous[midi] < .8:
            repeated += 1
        previous[midi] = start
        first = min(len(probabilities) - 1, max(0, round((start + .025) / step)))
        last = min(len(probabilities), max(first + 1, math.ceil(min(end, start + .18) / step)))
        candidates = []
        for string, base in enumerate(STANDARD):
            fret = midi - base
            if 0 <= fret <= 19:
                support = float(probabilities[first:last, string, fret + 1].mean())
                candidates.append(dict(string=string, fret=fret, score=round(support, 4)))
        candidates.sort(key=lambda item: -item["score"])
        if candidates and candidates[0]["score"] >= .35:
            best = candidates[0]
            note.update(model_string=best["string"], model_fret=best["fret"], fingering_score=best["score"],
                        fingering_candidates=candidates[:3])
            hints += 1
        else:
            note["fingering_uncertain"] = True
            uncertain += 1
        # Inspect the fundamental band, not the sum of every harmonic. This
        # can still contain another instrument; do not automatically trim.
        pitch_bin = 2 * (midi - 24)
        if 0 <= pitch_bin < magnitudes.shape[0]:
            onset_frame = max(0, int(start / step))
            end_frame = min(magnitudes.shape[1], math.ceil(end / step))
            proposed = release_proposal(magnitudes[pitch_bin], onset_frame, end_frame, step)
            if proposed is not None and proposed < end - .08:
                note["release_candidate"] = proposed
                releases += 1
        output.append(note)
    return output, dict(input_notes=len(notes), output_notes=len(output), pitch_valid_hints=hints,
        uncertain_fingerings=uncertain, repeated_pitch_attacks_preserved=repeated,
        release_candidates=releases, release_policy="diagnostic_only", note_policy="preserve_gaps_events",
        confidence_kind="uncalibrated_evidence", version=2)
