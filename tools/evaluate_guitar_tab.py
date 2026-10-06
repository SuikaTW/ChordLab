#!/usr/bin/env python3
"""Compare transcription profiles on a short clip, without changing saved jobs.

Run with the same environment variables as the service. A synthetic plucked-tone
fixture checks short-note recall; this does not measure real-song accuracy.
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def synthetic_fixture(path: Path) -> list[dict]:
    sample_rate = 22050
    reference = []
    for i in range(16):
        reference.append({"start": .5 + i * .16, "midi": [52, 55, 59, 64][i % 4], "length": .10})
    for i in range(8):
        reference.append({"start": 3.5 + i * .5, "midi": [52, 55, 59, 64][i % 4], "length": .35})
    samples = [0.0] * (sample_rate * 9)
    for event in reference:
        frequency = 440 * 2 ** ((event["midi"] - 69) / 12)
        for frame in range(int(event["length"] * sample_rate)):
            t = frame / sample_rate
            envelope = min(1.0, t / .003) * math.exp(-t / .12)
            release = min(1.0, (event["length"] - t) / .015)
            signal = sum(math.sin(2 * math.pi * frequency * harmonic * t) / harmonic ** 2
                         for harmonic in range(1, 5))
            samples[int(event["start"] * sample_rate) + frame] += .45 * envelope * release * signal
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, value)) * 32767)) for value in samples))
    return reference


def onset_metrics(reference: list[dict], notes: list[dict]) -> dict:
    remaining = list(notes)
    matched = 0
    for event in reference:
        candidates = [note for note in remaining if note["midi"] == event["midi"]
                      and abs(note["start"] - event["start"]) <= .08]
        if candidates:
            chosen = min(candidates, key=lambda note: abs(note["start"] - event["start"]))
            remaining.remove(chosen)
            matched += 1
    precision = matched / max(1, len(notes))
    recall = matched / len(reference)
    return {"matched": matched, "reference": len(reference), "precision": round(precision, 3),
            "recall": round(recall, 3), "f1": round(2 * precision * recall / max(.0001, precision + recall), 3)}


def compare(audio: Path, directory: Path, label: str, reference: list[dict] | None = None) -> dict:
    from app.main import BASIC_PYTHON, ROOT, run_command
    report = {"clip": label}
    for profile, flags in (("general", []), ("guitar_v2", ["--guitar"])):
        output = directory / f"{label}-{profile}.json"
        run_command([str(BASIC_PYTHON), str(ROOT / "tools/basic_pitch_worker.py"), str(audio),
                     str(output), str(output.with_suffix(".mid")), *flags], timeout=300)
        notes = json.loads(output.read_text())["notes"]
        metrics = {"note_count": len(notes), "under_128ms": sum(note["end"] - note["start"] < .128 for note in notes)}
        if reference is not None:
            metrics.update(onset_metrics(reference, notes))
        report[profile] = metrics
    return report


def main() -> None:
    from app.main import FFMPEG, JOBS, run_command
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=Path, help="Optional real guitar stem to compare")
    parser.add_argument("--start", type=float, default=20)
    parser.add_argument("--seconds", type=float, default=25)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix=".tab-evaluation-", dir=JOBS) as temporary:
        directory = Path(temporary)
        synthetic = directory / "synthetic.wav"
        reference = synthetic_fixture(synthetic)
        print(json.dumps(compare(synthetic, directory, "synthetic", reference), ensure_ascii=False), flush=True)
        if args.audio:
            clip = directory / "guitar.wav"
            run_command([str(FFMPEG), "-nostdin", "-y", "-ss", str(args.start), "-i", str(args.audio.resolve()),
                         "-t", str(args.seconds), "-ac", "1", "-ar", "22050", str(clip)], timeout=90)
            print(json.dumps(compare(clip, directory, "real-guitar-no-reference"), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
