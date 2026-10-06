"""Estimate beats, not downbeats/time signature. UI allows manual correction."""
import argparse
import json
from pathlib import Path
import librosa
import numpy as np


def analyze(source):
    audio, sr = librosa.load(source, sr=11025, mono=True, duration=1200)
    tempo, beats = librosa.beat.beat_track(y=audio, sr=sr, hop_length=256, units="time", trim=False)
    bpm = float(np.asarray(tempo).reshape(-1)[0])
    intervals = np.diff(beats)
    regularity = float(np.clip(1 - np.std(intervals) / max(np.mean(intervals), .001), 0, 1)) if len(intervals) > 2 else 0
    return {"bpm": round(bpm, 2) if 30 <= bpm <= 300 else None,
            "beats": [round(float(t), 4) for t in beats], "regularity": round(regularity, 3),
            "method": "librosa", "downbeat_known": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(analyze(args.audio)), encoding="utf-8")
