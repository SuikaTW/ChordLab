"""Experimental evidence decoder; scores are not calibrated probabilities.

Bass is a weak independent cue, never automatically the chord root. Extended
qualities must already be proposed by an engine and have acoustic support.
No key/progression prior is imposed; baseline segments are immutable inputs.
"""
from __future__ import annotations
import math
from app.chord_comparison import identity

NAMES = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
INTERVALS = {"": (0, 4, 7), "m": (0, 3, 7), "dim": (0, 3, 6), "aug": (0, 4, 8),
    "6": (0, 4, 7, 9), "m6": (0, 3, 7, 9), "7": (0, 4, 7, 10),
    "maj7": (0, 4, 7, 11), "m7": (0, 3, 7, 10), "mMaj7": (0, 3, 7, 11),
    "dim7": (0, 3, 6, 9), "m7b5": (0, 3, 6, 10), "sus2": (0, 2, 7), "sus4": (0, 5, 7)}


def normalize(values):
    if len(values) != 12 or any(not math.isfinite(float(v)) or v < 0 for v in values):
        raise ValueError("Invalid chroma evidence")
    total = sum(values)
    return [float(v) / total for v in values] if total > 1e-12 else [0.] * 12


def acoustic_score(label, chroma, bass):
    parsed = identity(label)
    if parsed is None or parsed[1] not in INTERVALS:
        return None
    root, quality, inversion = parsed
    intervals = INTERVALS[quality]
    pcs = [(root + interval) % 12 for interval in intervals]
    # Coverage alone favours every extension; the weakest defining tone matters.
    # A root voiced below the treble range is not a missing chord tone. Supply
    # limited bass evidence to that tone only, rather than to every extension.
    defining = [max(chroma[root], .25 * bass[root]) if interval == 0 else chroma[(root + interval) % 12]
                for interval in intervals if interval != 7]
    score = sum(chroma[pc] for pc in pcs) + .7 * min(defining) - .025 * max(0, len(pcs) - 3)
    if len(pcs) > 3 and chroma[pcs[-1]] < .055:
        score -= .3
    if sum(bass):
        score += .22 * bass[root]
        if inversion is not None:
            score += .14 * (bass[inversion] - .4)
    return score


def rank_observation(observation):
    chroma = normalize(observation["chroma"])
    bass = normalize(observation.get("bass", [0.] * 12))
    prior = observation.get("engine_labels", {})
    if observation.get("silent"):
        return [("N", 1.)]
    candidates = set(prior)
    triads = [(NAMES[root] + quality, acoustic_score(NAMES[root] + quality, chroma, bass))
              for root in range(12) for quality in ("", "m")]
    candidates.update(label for label, _ in sorted(triads, key=lambda item: -item[1])[:3])
    # Do not infer inversions from a short passing bass note or an unseparated
    # low register. Only a sustained, independently separated bass permits it.
    bass_pc = max(range(12), key=lambda pc: bass[pc])
    if observation.get("separate_bass") and observation["end"] - observation["start"] >= .35 and bass[bass_pc] >= .6:
        for label in list(candidates):
            parsed = identity(label)
            if parsed and parsed[1] in INTERVALS and parsed[2] is None and bass_pc != parsed[0]:
                if (bass_pc - parsed[0]) % 12 in INTERVALS[parsed[1]]:
                    candidates.add(label + "/" + NAMES[bass_pc])
    scored = []
    for label in candidates:
        score = acoustic_score(label, chroma, bass)
        if score is None:
            # Preserve an unsupported baseline spelling without inventing a
            # template for it, but don't force its acoustic interpretation.
            if label not in {"N", "X"} and prior.get(label, 0) >= 1:
                score = .62
            elif label == "N":
                score = .15
            else:
                continue
        engine_support = prior.get(label, prior.get(label.split("/")[0], 0))
        score += min(.2, .1 * max(0, float(engine_support)))
        scored.append((label, score))
    return sorted(scored, key=lambda item: (-item[1], item[0]))[:8]


def decode(observations, duration):
    if not math.isfinite(duration) or not 0 < duration <= 1200.25 or len(observations) > 30000:
        raise ValueError("Invalid harmony duration")
    paths, layers, ranked = {}, [], []
    previous_end = 0.
    for observation in observations:
        start, end = float(observation["start"]), float(observation["end"])
        if abs(start - previous_end) > .002 or not start < end <= duration + .002:
            raise ValueError("Discontinuous harmony evidence")
        previous_end = end
        choices = rank_observation(observation)
        ranked.append(choices)
        layer, new_paths = {}, {}
        # Weak-change boundaries pay more to fragment; strong changes retain
        # their real timestamps, including changes that fall between beats.
        change_cost = .035 + .075 * (1 - min(1., max(0., observation.get("change", 0.))))
        for label, score in choices:
            if paths:
                predecessor = max(paths, key=lambda old: paths[old] - (0 if old == label else change_cost))
                value = paths[predecessor] - (0 if predecessor == label else change_cost)
            else:
                predecessor, value = None, 0.
            new_paths[label] = value + score * (end - start)
            layer[label] = predecessor
        paths = new_paths
        layers.append(layer)
    if not paths or abs(previous_end - duration) > .002:
        raise ValueError("Incomplete harmony evidence")
    label, labels = max(paths, key=paths.get), []
    for layer in reversed(layers):
        labels.append(label)
        label = layer[label]
    labels.reverse()
    segments, uncertain = [], 0
    for observation, label, choices in zip(observations, labels, ranked):
        margin = choices[0][1] - choices[1][1] if len(choices) > 1 else 1.
        uncertain += int(margin < .12)
        if segments and segments[-1]["chord"] == label:
            segments[-1]["end"] = round(observation["end"], 4)
            segments[-1]["refinement"]["uncertain"] |= margin < .12
        else:
            segments.append(dict(start=round(observation["start"], 4), end=round(observation["end"], 4),
                chord=label, confidence=None, refinement={"uncertain": margin < .12,
                "alternatives": [{"chord": candidate, "evidence_score": round(score, 4)} for candidate, score in choices[:3]]}))
    return {"chords": segments, "summary": {"version": 2, "experimental": True,
        "confidence_kind": "uncalibrated_acoustic_evidence", "intervals": len(observations),
        "ambiguous_intervals": uncertain, "segments": len(segments),
        "policy": "independent_acoustic_bass_context_decode", "baseline_preserved": True}}
