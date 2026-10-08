"""Train a reproducible lightweight scorer on procedurally known guitar notes.

Timbre groups, not rows from the same recording, determine train/dev/test splits.
No uploaded songs, predictions, or user edits are treated as training labels.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import wave
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.note_plausibility import FEATURES, features, predict
from tools.audio_verification import SR


def render(pitches, group, rng):
    audio = np.zeros(SR, dtype=float)
    time = np.arange(round(.65 * SR)) / SR
    envelope = np.minimum(1, time / (.003 + .002 * (group % 4))) * np.exp(-time * (1 + group % 5))
    envelope *= np.minimum(1, (.65 - time) / .03)
    for pitch in pitches:
        frequency = 440 * 2 ** ((pitch - 69) / 12)
        tone = np.zeros(len(time))
        for harmonic in range(1, 13):
            if frequency * harmonic >= SR / 2:
                continue
            weight = harmonic ** (-.7 - (group % 4) * .3)
            if harmonic == 1 and group % 3 == 0:
                weight *= .25
            tone += weight * np.sin(2 * np.pi * frequency * harmonic * time + rng.uniform(-np.pi, np.pi))
        audio[round(.15 * SR):round(.15 * SR) + len(time)] += tone * envelope * rng.uniform(.4, 1)
    if group % 2:
        audio = np.tanh(audio * (1 + group % 3))
    delay = round((.035 + .007 * group) * SR)
    audio[delay:] += audio[:-delay].copy() * .12
    audio /= max(1e-9, np.max(np.abs(audio)))
    audio += rng.normal(0, .001 + .0005 * group, len(audio))
    return audio


def train(root, count=24):
    if not 4 <= count <= 200:
        raise ValueError('Use 4–200 recordings per timbre group')
    if root.exists() and any(root.iterdir()):
        raise ValueError('Use a new experiment directory')
    root.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20261008)
    matrix, labels, groups, records = [], [], [], []
    for group in range(12):
        split = 'train' if group < 8 else 'development' if group < 10 else 'regression'
        for index in range(count):
            base = int(rng.integers(43, 72))
            pitches = sorted({base, *([base + 4, base + 7] if index % 3 == 0 else [])})
            audio = render(pitches, group, rng)
            name = f'g{group:02d}-{index:03d}.wav'
            with wave.open(str(root / name), 'wb') as stream:
                stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(SR)
                stream.writeframes((np.clip(audio, -1, 1) * 32767).astype('<i2').tobytes())
            records.append(dict(audio=name, group=group, split=split,
                notes=[dict(start=.15, end=.8, midi=pitch) for pitch in pitches],
                audio_sha256=hashlib.sha256((root / name).read_bytes()).hexdigest()))
            for pitch in sorted(set(pitches + [base + 12, base - 12, base + 1, base + 6])):
                matrix.append(features(audio, pitch, .15, .8))
                labels.append(int(pitch in pitches)); groups.append(group)
    x, y, groups = np.array(matrix), np.array(labels), np.array(groups)
    train_mask = groups < 8
    mean, scale = x[train_mask].mean(axis=0), np.maximum(.05, x[train_mask].std(axis=0))
    normalized = (x[train_mask] - mean) / scale
    weights, bias = np.zeros(len(FEATURES)), 0.
    # Deterministic full-batch logistic regression, L2 regularized.
    for _ in range(800):
        logits = normalized @ weights + bias
        errors = 1 / (1 + np.exp(-np.clip(logits, -30, 30))) - y[train_mask]
        weights -= .08 * (normalized.T @ errors / len(errors) + .01 * weights)
        bias -= .08 * errors.mean()
    model = dict(version=1, features=FEATURES, mean=mean.tolist(), scale=scale.tolist(),
        weights=weights.tolist(), bias=float(bias), policy='synthetic_trained_advisory_only')
    metrics = {}
    for split, mask in [('train', groups < 8), ('development', (groups >= 8) & (groups < 10)), ('regression', groups >= 10)]:
        predicted = predict(x[mask], model) >= .5
        truth = y[mask].astype(bool)
        tp, fp, fn = int(np.sum(predicted & truth)), int(np.sum(predicted & ~truth)), int(np.sum(~predicted & truth))
        metrics[split] = dict(examples=int(mask.sum()), precision=tp / max(1, tp + fp), recall=tp / max(1, tp + fn), f1=2 * tp / max(1, 2 * tp + fp + fn))
    manifest = dict(seed=20261008, provenance='procedural_known_pitches_not_transcription_labels',
        split_policy='disjoint_timbre_groups', records=records)
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    model['manifest_sha256'] = hashlib.sha256((root / 'manifest.json').read_bytes()).hexdigest()
    model['synthetic_metrics'] = metrics
    (root / 'model.json').write_text(json.dumps(model, indent=2))
    np.savez_compressed(root / 'features.npz', x=x, y=y, groups=groups)
    print(json.dumps(metrics, indent=2))
    return model


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--count', type=int, default=24)
    args = parser.parse_args()
    train(args.root, args.count)
