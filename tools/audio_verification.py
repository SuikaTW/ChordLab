"""Bounded analysis-by-synthesis pitch repair, not a trained transcription model.

Fit nonnegative harmonic spectra at two distinct audio windows. Accept a pitch
edit only if both windows improve and the new fundamental is present. Timing,
event count and repeated attacks are preserved. No self-generated labels learn.
"""
from __future__ import annotations
import math
import heapq
import numpy as np
from scipy.optimize import nnls

SR, FFT, WINDOW = 16000, 4096, 2048
FREQ = np.fft.rfftfreq(FFT, 1 / SR)
MASK = (FREQ >= 65) & (FREQ <= 6000)
DEFAULT = np.array([1., .65, .42, .3, .21, .15, .11, .08])


def validate(notes, duration):
    if not math.isfinite(duration) or not .02 <= duration <= 1200.25 or len(notes) > 20000:
        raise ValueError("Verification input outside limits")
    for note in notes:
        midi, start, end = note.get("midi"), note.get("start"), note.get("end")
        if not isinstance(midi, int) or isinstance(midi, bool) or not 36 <= midi <= 99:
            raise ValueError("Invalid verification pitch")
        if not isinstance(start, (int,float)) or not isinstance(end, (int,float)) or not all(map(math.isfinite, [start,end])) or not 0 <= start < end <= duration + .02:
            raise ValueError("Invalid verification timing")


def spectrum(samples, center):
    first = round(center * SR) - WINDOW // 2
    signal = np.zeros(WINDOW)
    low, high = max(0, first), min(len(samples), first + WINDOW)
    if high > low:
        signal[low-first:high-first] = samples[low:high]
    return np.abs(np.fft.rfft(signal * np.hanning(WINDOW), n=FFT))


def harmonic_profile(samples, notes):
    """Only explicitly confirmed, edited, isolated sustained notes may calibrate."""
    notes = [note for note in notes if note.get("end",0) <= len(samples)/SR+.02]
    validate(notes, len(samples)/SR)
    learned = {}
    attempted = 0
    for note in notes:
        if not note.get("edited") or note["end"]-note["start"] < .25:
            continue
        attempted += 1
        if attempted > 128:
            break
        center = note["start"] + min(.18, (note["end"]-note["start"])/2)
        if any(other is not note and other["start"] < center+.08 and other["end"] > center-.08 for other in notes):
            continue
        spec = spectrum(samples, center)
        frequency = 440 * 2 ** ((note["midi"]-69)/12)
        amplitudes = np.array([spec[np.abs(FREQ-frequency*harmonic) < 10].max(initial=0) for harmonic in range(1,9)])
        if amplitudes[0] < max(1e-7, spec.max()*.08):
            continue
        vector = np.clip(amplitudes / amplitudes[0], 0, 3)
        learned.setdefault(str(note["midi"]), []).append(vector)
        if sum(map(len, learned.values())) >= 32:
            break
    return {pitch: [vector.tolist() for vector in vectors] for pitch, vectors in learned.items()}


def combine_profiles(profiles):
    grouped = {}
    for profile in profiles:
        for pitch, vectors in profile.items():
            grouped.setdefault(pitch, []).extend(vectors[:32])
    return {pitch: np.median(vectors, axis=0).tolist() for pitch, vectors in grouped.items() if len(vectors) >= 3}


def template(midi, profile=None):
    harmonics = DEFAULT.copy()
    if profile and str(midi) in profile:
        supplied = np.asarray(profile[str(midi)], dtype=float)
        if supplied.shape != (8,) or not np.isfinite(supplied).all() or np.any(supplied < 0) or np.any(supplied > 3):
            raise ValueError("Invalid calibrated harmonic profile")
        harmonics = .7 * DEFAULT + .3 * supplied
    frequency = 440 * 2 ** ((midi-69)/12)
    bins = np.zeros(len(FREQ))
    for harmonic, amplitude in enumerate(harmonics, 1):
        bins += amplitude * np.exp(-.5*((FREQ-frequency*harmonic)/6.5)**2)
    bins = np.sqrt(bins[MASK])
    return bins / max(1e-12, np.linalg.norm(bins))


def synthesize(notes, duration):
    """Audible reference only; timbre/phase mismatch must not be an accuracy claim."""
    validate(notes, duration)
    rendered = np.zeros(math.ceil(duration*SR), dtype=np.float32)
    for note in notes:
        first, last = round(note["start"]*SR), min(len(rendered),round(note["end"]*SR))
        time = np.arange(max(0,last-first))/SR
        frequency = 440*2**((note["midi"]-69)/12)
        envelope = np.minimum(1,time/.008)*np.minimum(1,(len(time)/SR-time)/.015)*np.exp(-time*1.5)
        wave = np.zeros(len(time))
        for harmonic,amplitude in enumerate(DEFAULT,1):
            if frequency*harmonic < SR/2:
                wave += amplitude*np.sin(2*np.pi*frequency*harmonic*time)
        rendered[first:last] += (wave*envelope*max(.05,min(1,note.get("velocity",.5)))).astype(np.float32)
    rendered *= .85/max(1,float(np.max(np.abs(rendered),initial=0)))
    return rendered


def fit(pitches, observed, dictionary):
    matrix = np.stack([dictionary[pitch] for pitch in pitches], axis=1)
    target = np.sqrt(observed[MASK])
    target /= max(1e-12, np.linalg.norm(target))
    _, residual = nnls(matrix, target, maxiter=100)
    return float(residual**2)


def verify(samples, notes, profile=None, passes=2):
    samples = np.asarray(samples, dtype=float)
    if samples.ndim != 1 or not np.isfinite(samples).all() or passes not in (1,2):
        raise ValueError("Invalid verification audio/passes")
    duration = len(samples)/SR
    validate(notes, duration)
    output = [dict(note) for note in notes]
    # Sweep time queries once; never scan the entire song per note.
    centers_by_note = [[note["start"] + min(.085, (note["end"]-note["start"])*.3),
                        note["start"] + min(.18, (note["end"]-note["start"])*.7)] for note in notes]
    queries = sorted((center,index,window) for index,centers in enumerate(centers_by_note) for window,center in enumerate(centers))
    ordered = sorted(range(len(notes)), key=lambda index: notes[index]["start"])
    neighbors = [[[],[]] for _ in notes]
    active, ends, pointer = set(), [], 0
    for center,index,window in queries:
        while pointer < len(ordered) and notes[ordered[pointer]]["start"] <= center:
            other = ordered[pointer]; active.add(other); heapq.heappush(ends,(notes[other]["end"],other)); pointer += 1
        while ends and ends[0][0] <= center:
            active.discard(heapq.heappop(ends)[1])
        neighbors[index][window] = [other for other in active if other != index][:6]
    dictionary = {midi: template(midi, profile) for midi in range(36,100)}
    changes, reviewed, uncertain, losses, spent = [], set(), set(), [], 0
    for iteration in range(passes):
        accepted = 0
        for index, note in enumerate(output):
            length = note["end"]-note["start"]
            if length < .18 or note.get("edited") or note.get("verification_changed"):
                continue
            centers = centers_by_note[index]
            active = [[output[other]["midi"] for other in indices] for indices in neighbors[index]]
            # Dense/polyphonic bleed is too ambiguous for conservative correction.
            if max(map(len, active)) > 5 or any(note["midi"] in pitches for pitches in active):
                uncertain.add(index); continue
            observed = [spectrum(samples, center) for center in centers]
            if min(float(spec.max()) for spec in observed) < 1e-7:
                uncertain.add(index); continue
            baseline = [fit([note["midi"], *pitches], spec, dictionary) for pitches,spec in zip(active,observed)]
            reviewed.add(index); original = note["midi"]
            best, best_losses = original, baseline
            for midi in [original-12, original-1, original+1, original+12]:
                if not 40 <= midi <= 88 or any(midi in pitches for pitches in active):
                    continue
                frequency = 440 * 2 ** ((midi-69)/12)
                if any(spec[np.abs(FREQ-frequency) <= 10].max(initial=0) < spec.max()*.06 for spec in observed):
                    continue
                proposed = [fit([midi, *pitches], spec, dictionary) for pitches,spec in zip(active,observed)]
                spent += 1
                if all(before-after > max(.025, before*.08) for before,after in zip(baseline,proposed)) and sum(proposed) < sum(best_losses):
                    best, best_losses = midi, proposed
            if best != original:
                note.update(midi=best, verification_changed=True, verification_original_midi=original,
                    verification_gain=round((sum(baseline)-sum(best_losses))/2,4))
                for field in ["model_string","model_fret","fingering_score","fingering_candidates"]:
                    note.pop(field, None)
                note["fingering_uncertain"] = True
                changes.append(dict(index=index, before=original, after=best, start=note["start"],
                    gain=note["verification_gain"], pass_number=iteration+1))
                losses.append((sum(baseline)/2, sum(best_losses)/2)); accepted += 1
            elif min(baseline) > .5:
                uncertain.add(index)
        if not accepted:
            break
    # Recheck the completed result, not just the provisional local edit. A nearby
    # correction may change harmonic attribution; revert if the evidence vanishes.
    reverted = set()
    for _ in range(2):
        undone = False
        for change in changes:
            index = change["index"]
            if index in reverted:
                continue
            observed = [spectrum(samples,center) for center in centers_by_note[index]]
            surrounding = [[output[other]["midi"] for other in indices] for indices in neighbors[index]]
            before = [fit([change["before"],*pitches],spec,dictionary) for pitches,spec in zip(surrounding,observed)]
            after = [fit([change["after"],*pitches],spec,dictionary) for pitches,spec in zip(surrounding,observed)]
            if not all(old-new > max(.025,old*.08) for old,new in zip(before,after)):
                output[index] = dict(notes[index]); uncertain.add(index); reverted.add(index); undone = True
        if not undone:
            break
    rechecked = len(changes)
    changes = [change for change in changes if change["index"] not in reverted]
    losses = []
    for change in changes:
        index = change["index"]
        observed = [spectrum(samples,center) for center in centers_by_note[index]]
        before = [fit([notes[index]["midi"],*[notes[other]["midi"] for other in indices]],spec,dictionary) for indices,spec in zip(neighbors[index],observed)]
        after = [fit([output[index]["midi"],*[output[other]["midi"] for other in indices]],spec,dictionary) for indices,spec in zip(neighbors[index],observed)]
        losses.append((sum(before)/2,sum(after)/2))
    for index in uncertain:
        output[index]["verification_uncertain"] = True
    summary = dict(version=1, policy="two_window_harmonic_resynthesis", experimental=True,
        passes=iteration+1, reviewed_notes=len(reviewed), changed_notes=len(changes),
        uncertain_notes=len(uncertain), candidate_checks=spent, changes=changes[:200],
        rechecked_changes=rechecked, reverted_changes=len(reverted),
        baseline_loss=round(np.mean([item[0] for item in losses]),4) if losses else None,
        verified_loss=round(np.mean([item[1] for item in losses]),4) if losses else None,
        calibrated_pitches=len(profile or {}), timing_policy="preserve_original", note_count_policy="preserve_original",
        confidence_kind="uncalibrated_spectral_fit", learning_policy="confirmed_private_edits_only",
        limitations=["spectral_gain_is_not_accuracy", "no_string_identification", "no_automatic_training", "pitch_only"])
    return output, summary
