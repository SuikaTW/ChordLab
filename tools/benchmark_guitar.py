"""Score saved predictions against annotated notes, without editing saved jobs.

Reference: JSON list of start/end/midi and optional string/fret, or EGSet12
per-string note_midi JAMS. EGSet12 is the TabCNN authors' benchmark, not an
independently held-out evaluation set. No thresholds are tuned by this script.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import maximum_bipartite_matching

STANDARD = (40, 45, 50, 55, 59, 64)


def load_reference(path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if "annotations" not in payload:
        return payload["notes"]
    annotations = [annotation for annotation in payload["annotations"] if annotation["namespace"] == "note_midi"]
    if len(annotations) != 6:
        raise ValueError("Expected six per-string EGSet12 annotations")
    notes = []
    for annotation in annotations:
        string = int(annotation["annotation_metadata"]["data_source"])
        if not 0 <= string <= 5:
            raise ValueError("Invalid string annotation")
        for event in annotation["data"]:
            notes.append(dict(start=float(event["time"]), end=float(event["time"] + event["duration"]),
                midi=int(event["value"]), string=string, fret=int(event["value"]) - STANDARD[string]))
    return sorted(notes, key=lambda event: (event["start"], event["midi"]))


def score(reference, predicted, *, offsets=False, fingerings=False):
    if len(reference) > 20000 or len(predicted) > 20000:
        raise ValueError("Benchmark note limit exceeded")
    by_pitch = {}
    for index, event in enumerate(predicted):
        by_pitch.setdefault(event["midi"], []).append((index, event))
    rows, columns = [], []
    for row, expected in enumerate(reference):
        for column, actual in by_pitch.get(expected["midi"], []):
            if abs(actual["start"] - expected["start"]) > .05:
                continue
            if offsets and abs(actual["end"] - expected["end"]) > max(.05, .2 * (expected["end"] - expected["start"])):
                continue
            if fingerings and (actual.get("model_string", actual.get("string")), actual.get("model_fret", actual.get("fret"))) != (expected.get("string"), expected.get("fret")):
                continue
            rows.append(row)
            columns.append(column)
    graph = csr_matrix((np.ones(len(rows)), (rows, columns)), shape=(len(reference), len(predicted)))
    matched = int(np.sum(maximum_bipartite_matching(graph, perm_type="column") >= 0)) if reference and predicted else 0
    precision, recall = matched / max(1, len(predicted)), matched / max(1, len(reference))
    return dict(matched=matched, precision=round(precision, 4), recall=round(recall, 4),
        f1=round(2 * precision * recall / max(1e-12, precision + recall), 4))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", type=Path)
    parser.add_argument("predictions", nargs="+", type=Path)
    parser.add_argument("--reference-output", type=Path)
    args = parser.parse_args()
    reference = load_reference(args.reference)
    if args.reference_output:
        args.reference_output.write_text(json.dumps({"notes": reference}), encoding="utf-8")
    reports = []
    for path in args.predictions:
        payload = json.loads(path.read_text(encoding="utf-8"))
        notes = payload["notes"]
        report = dict(file=path.name, engine=payload.get("engine"), reference_notes=len(reference), predicted_notes=len(notes),
            pitch_onset=score(reference, notes), pitch_onset_offset=score(reference, notes, offsets=True),
            elapsed_seconds=payload.get("elapsed_seconds"))
        if notes and all("model_string" in note or "string" in note for note in notes):
            report["string_fret_onset"] = score(reference, notes, fingerings=True)
        reports.append(report)
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
