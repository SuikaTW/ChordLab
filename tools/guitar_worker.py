"""Pinned, CPU-only guitar inference; no downloads or unrestricted pickle loads.

GAPS estimates pitches/onsets/offsets. TabCNN estimates standard-tuning string
and fret classes. The hybrid uses pitch-valid fingering hints, not a note union.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import time
import sys

import librosa
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.guitar_refinement import fuse_notes
MODELS = ROOT / "vendor/guitar/models"
CHECKSUMS = {
    "gaps": ("guitar-gaps-paper.pth", "94a7c936ec9fde83686d29007dc256274384e832739cadece39e92cee3b69a7e"),
    "tabcnn": ("tabcnn-gpfx.onnx", "8d9ce59157bdab37fb4816d32d7f29f3da0cdbf3c7876707c819af4d1f88e6b7"),
}
STANDARD = (40, 45, 50, 55, 59, 64)  # low E to high e; same convention as the UI


def checkpoint(engine):
    name, checksum = CHECKSUMS[engine]
    path = MODELS / name
    if hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
        raise ValueError("Guitar checkpoint checksum mismatch")
    return path


def transcribe_gaps(samples, model_path, evidence_path=None):
    import torch
    from piano_transcription_inference.models import Regress_onset_offset_frame_velocity_CRNN
    from piano_transcription_inference.utilities import RegressionPostProcessor

    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    # Bypass upstream's constructor (network download + weights_only=False).
    # This pinned research checkpoint also contains NumPy training statistics.
    # Allow only array reconstruction/dtypes, never arbitrary Python classes.
    allowed = [(np._core.multiarray._reconstruct, "numpy.core.multiarray._reconstruct"),
               np.ndarray, np.dtype, *[type(np.dtype(kind)) for kind in ("float32", "float64", "int64", "uint32")]]
    with torch.serialization.safe_globals(allowed):
        weights = torch.load(model_path, map_location="cpu", weights_only=True)
    model = Regress_onset_offset_frame_velocity_CRNN(frames_per_second=100, classes_num=88).eval()
    model.load_state_dict(weights["model"], strict=True)
    duration = len(samples) / 16000
    # The author's 10s windows overlap by 5s. Keep the central part of each
    # prediction, including the beginning/end of the first/last windows.
    segment = 160000
    padded = np.pad(samples, (0, math.ceil(len(samples) / segment) * segment - len(samples)))
    offsets = list(range(0, len(padded) - segment + 1, segment // 2))
    output = {}
    with torch.inference_mode():
        for index, offset in enumerate(offsets):
            predicted = model(torch.from_numpy(padded[offset:offset + segment].astype(np.float32)).unsqueeze(0))
            for key, value in predicted.items():
                matrix = value[0].numpy()
                if len(offsets) > 1:
                    matrix = matrix[:-1]
                    matrix = matrix[0 if index == 0 else 250:1000 if index == len(offsets) - 1 else 750]
                output.setdefault(key, []).append(matrix)
    output = {key: np.concatenate(value)[:math.ceil(duration * 100)] for key, value in output.items()}
    if evidence_path:
        np.savez_compressed(evidence_path, **{key: value.astype(np.float16) for key, value in output.items()},
                            schema=np.array(2), duration=np.array(duration))
    processor = RegressionPostProcessor(100, classes_num=88, onset_threshold=.3,
        offset_threshold=.3, frame_threshold=.1, pedal_offset_threshold=.2)
    events, _ = processor.output_dict_to_midi_events(output)
    notes = []
    for event in events:
        start, end, midi = float(event["onset_time"]), min(duration, float(event["offset_time"])), int(event["midi_note"])
        if not 36 <= midi <= 99 or end - start < .02 or start < 0:
            continue
        frame = min(len(output["frame_output"]) - 1, max(0, round(start * 100)))
        pitch = midi - 21
        notes.append(dict(start=round(start, 4), end=round(end, 4), midi=midi,
            velocity=round(float(event["velocity"]) / 128, 4),
            onset_score=round(float(output["reg_onset_output"][frame, pitch]), 4)))
    return notes


def transcribe_tabcnn(samples, model_path, return_evidence=False):
    import onnxruntime as ort
    hop, sr = 512, 22050
    duration = len(samples) / sr
    magnitude = np.abs(librosa.cqt(samples, sr=sr, hop_length=hop, n_bins=192, bins_per_octave=24))
    features = librosa.amplitude_to_db(magnitude, ref=np.max)
    features = ((features - features.min()) / (features.max() - features.min() + 1e-9)).astype(np.float32)
    padded = np.pad(features, ((0, 0), (4, 4)))
    config = ort.SessionOptions()
    config.intra_op_num_threads = 2
    config.inter_op_num_threads = 1
    config.enable_mem_pattern = False
    model = ort.InferenceSession(str(model_path), sess_options=config, providers=["CPUExecutionProvider"])
    labels, scores, distributions = [], [], []
    for first in range(0, features.shape[1], 256):
        inputs = np.stack([padded[:, i:i + 9, None] for i in range(first, min(first + 256, features.shape[1]))])
        log_probs = model.run(None, {"input": inputs})[0]
        labels.append(log_probs.argmax(axis=-1))
        scores.append(np.exp(log_probs).max(axis=-1))
        if return_evidence:
            distributions.append(np.exp(log_probs))
    if return_evidence:
        return np.concatenate(distributions), magnitude
    labels, scores = np.concatenate(labels), np.concatenate(scores)
    notes = []
    for string, base in enumerate(STANDARD):
        previous, first = 0, 0
        for frame in range(len(labels) + 1):
            label = int(labels[frame, string]) if frame < len(labels) and frame * hop / sr < duration else 0
            if label == previous:
                continue
            if previous:
                start, end = first * hop / sr, min(duration, frame * hop / sr)
                if end - start >= .04:
                    probability = float(scores[first:frame, string].mean())
                    notes.append(dict(start=round(start, 4), end=round(end, 4),
                        midi=base + previous - 1, velocity=1.0,
                        model_string=string, model_fret=previous - 1,
                        fingering_score=round(probability, 4)))
            previous, first = label, frame
    return sorted(notes, key=lambda note: (note["start"], note["midi"]))


def write_midi(notes, path):
    import mido
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=500000))
    for channel in range(6):
        track.append(mido.Message("program_change", program=24, channel=channel))
    events = []
    for note in notes:
        # One channel per string preserves unisons on different strings.
        channel = int(note.get("model_string", 0))
        events.extend([(round(note["start"] * 960), 1, channel, note), (round(note["end"] * 960), 0, channel, note)])
    previous = 0
    for tick, on, channel, note in sorted(events, key=lambda event: event[:3]):
        track.append(mido.Message("note_on" if on else "note_off", note=note["midi"],
            velocity=max(1, min(127, round(note["velocity"] * 127))) if on else 0,
            channel=channel, time=max(0, tick - previous)))
        previous = tick
    midi.save(str(path))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("midi", type=Path)
    parser.add_argument("--engine", choices=[*CHECKSUMS, "hybrid"], required=True)
    parser.add_argument("--gaps-cache", type=Path)
    args = parser.parse_args()
    started = time.monotonic()
    model = checkpoint("gaps" if args.engine == "hybrid" else args.engine)
    sr = 16000 if args.engine == "gaps" else 22050
    samples, _ = librosa.load(args.audio, sr=sr, mono=True)
    duration = len(samples) / sr
    if not .02 <= duration <= 1200.25 or not np.isfinite(samples).all():
        raise ValueError("Audio outside guitar inference limits")
    refinement = None
    if np.max(np.abs(samples)) < 1e-7:
        notes = []
    elif args.engine == "hybrid":
        cached = json.loads(args.gaps_cache.read_text()) if args.gaps_cache and args.gaps_cache.is_file() else None
        if cached and (cached.get("profile") != "guitar_gaps_v1" or cached.get("checkpoint_sha256") != CHECKSUMS["gaps"][1]
                       or not math.isfinite(float(cached.get("duration", 0)))
                       or abs(float(cached.get("duration", 0)) - duration) > .02
                       or not isinstance(cached.get("notes"), list)):
            raise ValueError("GAPS cache does not match this recording")
        gaps = cached["notes"] if cached else transcribe_gaps(librosa.resample(samples, orig_sr=sr, target_sr=16000), model,
            args.output.parent / "guitar-gaps.evidence.npz")
        if len(gaps) > 20000:
            raise ValueError("Too many cached events")
        probs, magnitude = transcribe_tabcnn(samples, checkpoint("tabcnn"), return_evidence=True)
        notes, refinement = fuse_notes(gaps, probs, magnitude, duration)
        np.savez_compressed(args.output.parent / "guitar-hybrid.evidence.npz", probabilities=probs.astype(np.float16),
                            schema=np.array(2), duration=np.array(duration))
    elif args.engine == "gaps":
        notes = transcribe_gaps(samples, model, args.output.parent / "guitar-gaps.evidence.npz")
    else:
        notes = transcribe_tabcnn(samples, model)
    if len(notes) > 20000:
        raise ValueError("Too many guitar note events")
    payload = dict(engine=args.engine, profile="guitar_hybrid_v2" if args.engine == "hybrid" else f"guitar_{'gaps' if args.engine == 'gaps' else 'tabcnn_gpfx'}_v1",
        duration=round(duration, 4), note_count=len(notes), notes=notes,
        elapsed_seconds=round(time.monotonic() - started, 3), checkpoint_sha256=CHECKSUMS["gaps" if args.engine == "hybrid" else args.engine][1],
        refinement=refinement,
        **({"checkpoints": {name: CHECKSUMS[name][1] for name in ("gaps", "tabcnn")}} if args.engine == "hybrid" else {}),
        experimental=True, confidence_kind="uncalibrated_model_output",
        **({"fingering_tuning": "standard", "fingering_capo": 0,
            "limitations": ["frets_0_to_19", "repeated_same_fret_plucks_may_merge"] if args.engine == "tabcnn" else ["frets_0_to_19", "unverified_fingerings"]} if args.engine in {"tabcnn", "hybrid"} else {}))
    write_midi(notes, args.midi)
    args.output.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
