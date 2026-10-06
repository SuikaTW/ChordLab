"""Conservative cross-check: annotate a baseline, never vote away its labels."""
from __future__ import annotations

from collections import defaultdict
import math
import re

ROOTS = {"C": 0, "B#": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
         "E": 4, "Fb": 4, "E#": 5, "F": 5, "F#": 6, "Gb": 6, "G": 7,
         "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11, "Cb": 11}
ALIASES = {"maj": "", "min": "m", "min7": "m7", "min6": "m6", "maj6": "6",
           "minmaj7": "mMaj7", "hdim7": "m7b5"}


def identity(label):
    match = re.fullmatch(r"([A-G](?:#|b)?):?([^/]*)(?:/([A-G](?:#|b)?))?", label)
    if not match or match[1] not in ROOTS:
        return None
    quality = ALIASES.get(match[2], match[2])
    bass = ROOTS.get(match[3]) if match[3] else None
    return ROOTS[match[1]], quality, bass


def relation(a, b):
    if a in {"N", "X"} or b in {"N", "X"}:
        return "agree" if a == b == "N" else "conflict"
    left, right = identity(a), identity(b)
    if left is None or right is None:
        return "conflict"
    if left == right:
        return "agree"
    # Distinguish extensions from actual root/third conflicts. Suspended,
    # augmented and diminished chords are not classified as major/minor.
    def family(q):
        if q in {"", "6", "7", "maj7"}:
            return "major"
        if q in {"m", "m6", "m7", "mMaj7"}:
            return "minor"
        return q
    return "detail" if left[0] == right[0] and family(left[1]) == family(right[1]) else "conflict"


def valid_segments(items, duration):
    cleaned = []
    for item in items:
        start, end = float(item["start"]), min(float(item["end"]), duration)
        if math.isfinite(start) and math.isfinite(end) and 0 <= start < end:
            cleaned.append({**item, "start": start, "end": end})
    cleaned.sort(key=lambda s: s["start"])
    for i in range(1, len(cleaned)):
        if cleaned[i]["start"] < cleaned[i-1]["end"]:
            raise ValueError("Overlapping chord segments")
    return cleaned


def compare_chords(baseline, btc, duration):
    baseline, btc = valid_segments(baseline, duration), valid_segments(btc, duration)
    output, totals = [], defaultdict(float)
    cursor = 0
    for segment in baseline:
        start, end = segment["start"], segment["end"]
        while cursor < len(btc) and btc[cursor]["end"] <= start:
            cursor += 1
        labels, statuses = defaultdict(float), defaultdict(float)
        j = cursor
        while j < len(btc) and btc[j]["start"] < end:
            candidate = btc[j]
            overlap = min(end, candidate["end"]) - max(start, candidate["start"])
            if overlap > 0:
                labels[candidate["chord"]] += overlap
                kind = relation(segment["chord"], candidate["chord"])
                statuses[kind] += overlap
                totals[kind] += overlap
            j += 1
        covered = sum(labels.values())
        span = end-start
        ranked = sorted(labels.items(), key=lambda pair: (-pair[1], pair[0]))
        if covered < span * .8:
            status = "unavailable"
        elif statuses["agree"] >= span * .8:
            status = "agree"
        elif statuses["agree"] + statuses["detail"] >= span * .8:
            status = "detail"
        elif ranked and ranked[0][1] >= span * .6:
            status = "conflict"
        else:
            status = "mixed"
        output.append({**segment, "comparison": {
            "status": status,
            "candidates": [{"chord": name, "share": round(seconds/span, 3)} for name, seconds in ranked[:2]],
        }})
    compared = sum(totals.values())
    return {"chords": output, "summary": {
        "compared_seconds": round(compared, 3),
        "agreement_ratio": round(totals["agree"]/compared, 4) if compared else None,
        "detail_seconds": round(totals["detail"], 3),
        "conflict_seconds": round(totals["conflict"], 3),
        "review_segments": sum(s["comparison"]["status"] not in {"agree", "unavailable"} for s in output),
        "policy": "preserve_chordino_labels", "version": 1,
    }}
