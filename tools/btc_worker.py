"""CPU-only BTC-ISMIR19 inference. No downloads or unrestricted pickle loading."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import librosa
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor/btc"))
from btc_model import BTC_model

CHECKSUM = "1673d23f8f9a55ae7f9e8b80a51da616debb22675b8d8b67ea6ce0ef37b0ab51"
MODEL = ROOT / "vendor/btc/models/btc_model_large_voca.pt"
QUALITIES = ("m", "", "dim", "aug", "m6", "6", "m7", "mMaj7", "maj7", "7", "dim7", "m7b5", "sus2", "sus4")
ROOTS = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
CONFIG = dict(feature_size=144, timestep=108, num_chords=170, hidden_size=128,
              num_layers=8, num_heads=4, total_key_depth=128, total_value_depth=128,
              filter_size=128, input_dropout=0.2, layer_dropout=0.2,
              attention_dropout=0.2, relu_dropout=0.2, probs_out=True)


def load_model():
    if hashlib.sha256(MODEL.read_bytes()).hexdigest() != CHECKSUM:
        raise ValueError("BTC checkpoint checksum mismatch")
    # The official legacy checkpoint includes one NumPy float64 statistic.
    # Allow only this scalar constructor; never enable weights_only=False.
    allowed = [(np._core.multiarray.scalar, "numpy.core.multiarray.scalar"),
               np.dtype, type(np.dtype("float64"))]
    with torch.serialization.safe_globals(allowed):
        checkpoint = torch.load(MODEL, map_location="cpu", weights_only=True)
    mean, std = float(checkpoint["mean"]), float(checkpoint["std"])
    if not np.isfinite([mean, std]).all() or std <= 0:
        raise ValueError("Invalid BTC normalization")
    model = BTC_model(CONFIG).eval()
    model.load_state_dict(checkpoint["model"], strict=True)
    return model, mean, std


def label(index):
    return "N" if index == 169 else "X" if index == 168 else ROOTS[index // 14] + QUALITIES[index % 14]


def analyze(source):
    started = time.monotonic()
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    model, mean, std = load_model()
    samples, sr = librosa.load(source, sr=22050, mono=True)
    duration = len(samples) / sr
    if not 0 < duration <= 1200.25:
        raise ValueError("Audio duration outside BTC limits")
    events = []
    with torch.inference_mode():
        # Match upstream's ten-second CQT blocks and normalization. Keep actual
        # hop timestamps, avoiding accumulated rounding drift in long songs.
        for offset in range(0, len(samples), sr * 10):
            chunk = samples[offset:offset + sr * 10]
            features = np.log(np.abs(librosa.cqt(np.pad(chunk, (0, max(0, 4096 - len(chunk)))),
                sr=sr, n_bins=144, bins_per_octave=24, hop_length=2048)) + 1e-6).T
            count = min(len(features), 108)
            features = np.pad((features[:count] - mean) / std, ((0, 108-count), (0, 0)))
            hidden, _ = model.self_attn_layers(torch.tensor(features, dtype=torch.float32).unsqueeze(0))
            probs = torch.softmax(model.output_layer(hidden), dim=-1)[0, :count]
            scores, indices = probs.max(dim=-1)
            for frame, (index, score) in enumerate(zip(indices.tolist(), scores.tolist())):
                timestamp = (offset + frame * 2048) / sr
                if timestamp < duration:
                    events.append((timestamp, label(index), score))
    chords = []
    for i, (start, chord, score) in enumerate(events):
        end = events[i+1][0] if i+1 < len(events) else duration
        if end <= start:
            continue
        if chords and chords[-1]["chord"] == chord:
            segment = chords[-1]
            segment["score_sum"] += score * (end-start)
            segment["end"] = end
        else:
            chords.append(dict(start=start, end=end, chord=chord, score_sum=score*(end-start)))
    for segment in chords:
        segment["confidence"] = round(segment.pop("score_sum") / (segment["end"]-segment["start"]), 4)
        segment["start"] = round(segment["start"], 4)
        segment["end"] = round(segment["end"], 4)
    return dict(engine="btc_ismir19_170", duration=duration, chords=chords,
                elapsed_seconds=round(time.monotonic()-started, 3), checkpoint_sha256=CHECKSUM,
                confidence_kind="uncalibrated_softmax", input=Path(source).name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(analyze(args.source), ensure_ascii=False), encoding="utf-8")
