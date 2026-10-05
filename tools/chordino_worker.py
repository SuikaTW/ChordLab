#!/usr/bin/env python3
"""Run the upstream NNLS Chroma / Chordino Vamp plugin."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import librosa
import vamp


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio")
    parser.add_argument("output")
    args = parser.parse_args()
    samples, sample_rate = librosa.load(args.audio, sr=22050, mono=True)
    data = vamp.collect(
        samples,
        sample_rate,
        "nnls-chroma:chordino",
        parameters={"useNNLS": 1, "rollon": 0.02, "tuningmode": 1},
    )
    features = [feature for feature in data.get("list", []) if float(feature["timestamp"]) < len(samples) / sample_rate]
    duration = len(samples) / sample_rate
    chords = []
    for index, feature in enumerate(features):
        start = float(feature["timestamp"])
        end = min(duration, float(features[index + 1]["timestamp"])) if index + 1 < len(features) else duration
        if end <= start:
            continue
        label = str(feature.get("label", "N")).strip() or "N"
        if label == "N":
            display = "N"
        else:
            display = label.replace(":maj", "").replace(":min", "m")
        chords.append({"start": round(start, 3), "end": round(end, 3), "chord": display, "confidence": None})
    payload = {"engine": "chordino", "duration": round(duration, 3), "chords": chords}
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
