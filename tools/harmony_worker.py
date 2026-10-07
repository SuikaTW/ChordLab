"""Extract independent treble/bass evidence for the experimental decoder."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import sys
import time
import librosa
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.harmony_refinement import decode
from app.chord_comparison import valid_segments

SR, HOP = 22050, 512


def features(path):
    samples, _ = librosa.load(path, sr=SR, mono=True)
    if not .02 <= len(samples) / SR <= 1200.25 or not np.isfinite(samples).all():
        raise ValueError("Invalid harmony audio")
    magnitude = np.abs(librosa.cqt(samples, sr=SR, hop_length=HOP, n_bins=84, fmin=librosa.midi_to_hz(24)))
    # Median time smoothing downweights attacks/percussion without using a
    # separated bass as treble evidence or discarding offbeat chord changes.
    from scipy.ndimage import median_filter
    magnitude = median_filter(magnitude, size=(1, 5))
    # Remove local spectral background before pooling pitch classes. Merely
    # compressing every bin amplifies leakage and can invent a missing third.
    magnitude = np.maximum(0., magnitude - .8 * median_filter(magnitude, size=(5, 1)))
    magnitude[magnitude < magnitude.max(axis=0, keepdims=True) * .04] = 0.
    treble, bass = np.zeros((12, magnitude.shape[1])), np.zeros((12, magnitude.shape[1]))
    for pitch in range(84):
        target = bass if pitch < 24 else treble
        target[(pitch + 24) % 12] += magnitude[pitch]
    rms = librosa.feature.rms(y=samples, hop_length=HOP)[0]
    return len(samples) / SR, treble, bass, rms


def aggregate(matrix, start, end):
    first = min(matrix.shape[-1] - 1, max(0, round(start * SR / HOP)))
    last = min(matrix.shape[-1], max(first + 1, math.ceil(end * SR / HOP)))
    return np.mean(matrix[..., first:last], axis=-1)


def refine(source, baseline_path, btc_path=None, bass_path=None):
    started = time.monotonic()
    duration, treble, bass, rms = features(source)
    if bass_path:
        bass_duration, _, bass, _ = features(bass_path)
        if abs(bass_duration - duration) > .15:
            raise ValueError("Bass stem duration mismatch")
    baseline = valid_segments(json.loads(baseline_path.read_text())["chords"], duration)
    btc = json.loads(btc_path.read_text()) if btc_path else {}
    btc_segments = valid_segments(btc.get("chords", []), duration)
    frames = valid_segments(btc.get("frames", []), duration)
    # Candidate boundaries come from both engines and local chroma contrast.
    # Existing timestamps are not quantized to beats or a fixed note grid.
    boundaries = {0., duration}
    for item in [*baseline, *btc_segments]:
        boundaries.update((item["start"], item["end"]))
    normalized = treble / np.maximum(treble.sum(axis=0, keepdims=True), 1e-9)
    contrast = np.zeros(treble.shape[1])
    window = max(2, round(.12 * SR / HOP))
    for index in range(window, treble.shape[1] - window):
        left = normalized[:, index-window:index].mean(axis=1)
        right = normalized[:, index:index+window].mean(axis=1)
        contrast[index] = np.abs(left-right).sum() / 2
    from scipy.signal import find_peaks
    peaks, _ = find_peaks(contrast, height=.24, distance=round(.18 * SR / HOP), prominence=.08)
    boundaries.update(float(frame * HOP / SR) for frame in peaks if frame * HOP / SR < duration)
    silence_floor = max(1e-6, float(np.max(rms)) * .006)
    quiet = rms < silence_floor
    boundaries.update(float(frame * HOP / SR) for frame in np.flatnonzero(quiet[1:] != quiet[:-1]) + 1
                      if frame * HOP / SR < duration)
    ordered = sorted(boundaries)
    clean = [0.]
    for boundary in ordered[1:-1]:
        if boundary - clean[-1] >= .06 and duration - boundary >= .06:
            clean.append(boundary)
    clean.append(duration)
    # Index input timelines once; no quadratic scan of frame posteriors.
    pointers = [0, 0, 0]
    timelines = [baseline, btc_segments, frames]
    observations = []
    for start, end in zip(clean, clean[1:]):
        labels = {}
        for stream, items in enumerate(timelines):
            while pointers[stream] < len(items) and items[pointers[stream]]["end"] <= start:
                pointers[stream] += 1
            cursor = pointers[stream]
            while cursor < len(items) and items[cursor]["start"] < end:
                item = items[cursor]
                share = max(0., min(end, item["end"]) - max(start, item["start"])) / (end-start)
                if stream < 2:
                    weight = 1. if stream == 0 else .7
                    labels[item["chord"]] = labels.get(item["chord"], 0) + weight * share
                else:
                    for candidate in item.get("candidates", []):
                        labels[candidate["chord"]] = labels.get(candidate["chord"], 0) + .3 * share * candidate["score"]
                cursor += 1
        frame = min(len(contrast)-1, round(start * SR / HOP))
        observations.append(dict(start=start, end=end, chroma=aggregate(treble, start, end).tolist(),
            bass=aggregate(bass, start, end).tolist(), engine_labels=labels, separate_bass=bool(bass_path),
            change=min(1., float(contrast[frame]) * 2), silent=float(aggregate(rms, start, end)) < silence_floor))
    result = decode(observations, duration)
    result["summary"].update(input=source.name, separate_bass=bool(bass_path),
        btc_frame_candidates=bool(frames), elapsed_seconds=round(time.monotonic()-started, 3))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--btc", type=Path)
    parser.add_argument("--bass", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(refine(args.source, args.baseline, args.btc, args.bass), ensure_ascii=False))
