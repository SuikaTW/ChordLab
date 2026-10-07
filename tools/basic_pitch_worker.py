#!/usr/bin/env python3
"""Run Spotify Basic Pitch and derive an independently smoothed chord track."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from basic_pitch.inference import predict

PITCH_NAMES = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
QUALITIES = {
    "": ({0, 4, 7}, 1.0),
    "m": ({0, 3, 7}, 1.0),
    "7": ({0, 4, 7, 10}, 0.92),
    "maj7": ({0, 4, 7, 11}, 0.92),
    "m7": ({0, 3, 7, 10}, 0.92),
    "sus4": ({0, 5, 7}, 0.88),
    "dim": ({0, 3, 6}, 0.84),
}


def templates() -> list[tuple[str, set[int], float]]:
    result = []
    for root in range(12):
        for suffix, (steps, bias) in QUALITIES.items():
            result.append((PITCH_NAMES[root] + suffix, {(root + step) % 12 for step in steps}, bias))
    return result


def score_chords(note_events: list, duration: float, window: float = 0.5) -> list[dict]:
    bank = templates()
    frames: list[tuple[float, list[float], float]] = []
    count = max(1, math.ceil(duration / window))
    for index in range(count):
        start = index * window
        end = min(duration, start + window)
        chroma = [0.0] * 12
        for event in note_events:
            note_start, note_end, midi, amplitude = float(event[0]), float(event[1]), int(event[2]), float(event[3])
            overlap = max(0.0, min(end, note_end) - max(start, note_start))
            if overlap:
                chroma[midi % 12] += overlap * max(0.05, amplitude)
        energy = sum(chroma)
        scores = []
        for _name, tones, bias in bank:
            inside = sum(chroma[p] for p in tones)
            outside = energy - inside
            root_pc = PITCH_NAMES.index(_name[:2]) if len(_name) > 1 and _name[1] in "#b" else PITCH_NAMES.index(_name[0])
            score = (inside - outside * 0.62 + chroma[root_pc] * 0.15) * bias
            scores.append(score)
        frames.append((start, scores, energy))

    # Viterbi-style smoothing: changing harmony costs a little evidence.
    if not frames:
        return []
    previous = frames[0][1]
    paths = [[-1] * len(bank) for _ in frames]
    for frame_index in range(1, len(frames)):
        current_scores = frames[frame_index][1]
        next_scores = []
        best_previous = max(range(len(previous)), key=previous.__getitem__)
        best_value = previous[best_previous]
        for chord_index, observation in enumerate(current_scores):
            stay = previous[chord_index]
            change = best_value - 0.18
            if stay >= change:
                paths[frame_index][chord_index] = chord_index
                next_scores.append(stay + observation)
            else:
                paths[frame_index][chord_index] = best_previous
                next_scores.append(change + observation)
        maximum = max(next_scores)
        previous = [value - maximum for value in next_scores]

    chosen = [0] * len(frames)
    chosen[-1] = max(range(len(previous)), key=previous.__getitem__)
    for frame_index in range(len(frames) - 1, 0, -1):
        chosen[frame_index - 1] = paths[frame_index][chosen[frame_index]]

    raw = []
    for index, ((start, scores, energy), chord_index) in enumerate(zip(frames, chosen, strict=True)):
        label = "N" if energy < 0.025 else bank[chord_index][0]
        sorted_scores = sorted(scores, reverse=True)
        confidence = 0.0 if energy < 0.025 else max(0.05, min(0.99, 0.5 + (sorted_scores[0] - sorted_scores[1]) / (energy + 1e-6)))
        raw.append({"start": round(start, 3), "end": round(min(duration, start + window), 3), "chord": label, "confidence": round(confidence, 3)})

    merged: list[dict] = []
    for segment in raw:
        if merged and merged[-1]["chord"] == segment["chord"]:
            total = merged[-1]["end"] - merged[-1]["start"] + segment["end"] - segment["start"]
            merged[-1]["confidence"] = round((merged[-1]["confidence"] * (merged[-1]["end"] - merged[-1]["start"]) + segment["confidence"] * (segment["end"] - segment["start"])) / max(total, 0.001), 3)
            merged[-1]["end"] = segment["end"]
        else:
            merged.append(segment.copy())
    return merged


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio")
    parser.add_argument("output")
    parser.add_argument("midi")
    instruments = parser.add_mutually_exclusive_group()
    instruments.add_argument("--guitar", action="store_true", help="Preserve short guitar plucks and constrain the pitch range")
    instruments.add_argument("--bass", action="store_true", help="Bass pitch range, including low B; retain repeated plucks")
    args = parser.parse_args()
    options = {}
    if args.guitar:
        options = {
            "minimum_note_length": 80.0,
            "onset_threshold": 0.6,
            "minimum_frequency": 440 * 2 ** ((36 - 69) / 12),
            "maximum_frequency": 440 * 2 ** ((99 - 69) / 12),
        }
    elif args.bass:
        options = {
            "minimum_note_length": 60.0,
            "onset_threshold": 0.5,
            "minimum_frequency": 440 * 2 ** ((23 - 69) / 12),
            "maximum_frequency": 440 * 2 ** ((67 - 69) / 12),
        }
    model_output, midi_data, note_events = predict(args.audio, **options)
    del model_output
    if args.bass and len(note_events) > 20000:
        raise ValueError("Too many Bass note events")
    if args.bass:
        for instrument in midi_data.instruments:
            instrument.program = 33  # GM fingered electric bass, zero-based.
    midi_data.write(args.midi)
    duration = max((float(event[1]) for event in note_events), default=0.0)
    payload = {
        "engine": "basic_pitch",
        "profile": "guitar_v2" if args.guitar else "bass_v1" if args.bass else "general",
        "duration": round(duration, 3),
        "note_count": len(note_events),
        "notes": [
            {
                "start": round(float(event[0]), 4),
                "end": round(float(event[1]), 4),
                "midi": int(event[2]),
                "velocity": round(float(event[3]), 4),
            }
            for event in note_events
        ],
        "chords": score_chords(note_events, duration),
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
