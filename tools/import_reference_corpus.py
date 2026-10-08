"""Import owned/licensed WAV recordings and independent human annotations.

Input directory contains intake.json. Each entry names a relative WAV and a
reference JSON (notes, optional chord_annotations). Nothing is inferred here;
unknown training overlap remains unknown until independently audited.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import wave

CONDITIONS = {"real_acoustic_guitar", "real_electric_guitar", "real_bass", "real_full_mix"}


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def local_file(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError("Audio and annotation paths must be relative")
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file() or path.is_symlink():
        raise ValueError("Missing or unsafe source path")
    return path


def validate_reference(payload: dict, duration: float) -> None:
    if not isinstance(payload, dict) or not isinstance(payload.get("notes"), list):
        raise ValueError("Reference needs a human-annotated notes array")
    if not payload["notes"] and not payload.get("chord_annotations"):
        raise ValueError("Empty reference")
    for note in payload["notes"]:
        if not isinstance(note, dict) or not isinstance(note.get("midi"), int) or not 0 <= note["midi"] <= 127:
            raise ValueError("Invalid reference pitch")
        start, end = note.get("start"), note.get("end")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end <= duration + .1:
            raise ValueError("Reference note outside recording")
        if "string" in note and (not isinstance(note["string"], int) or not 0 <= note["string"] <= 5):
            raise ValueError("Invalid string number")
        if "fret" in note and (not isinstance(note["fret"], int) or not 0 <= note["fret"] <= 30):
            raise ValueError("Invalid fret number")
    for track in payload.get("chord_annotations", []):
        if not isinstance(track, dict) or not isinstance(track.get("segments"), list):
            raise ValueError("Invalid chord track")
        for segment in track["segments"]:
            start, end, chord = segment.get("start"), segment.get("end"), segment.get("chord")
            if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end <= duration + .1 or not isinstance(chord, str) or not chord:
                raise ValueError("Invalid chord interval")


def import_corpus(source: Path, destination: Path) -> dict:
    source = source.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Destination must be new and empty; references are immutable")
    intake = json.loads((source / "intake.json").read_text(encoding="utf-8"))
    if not isinstance(intake.get("records"), list) or not intake["records"]:
        raise ValueError("No recordings listed")
    records, performers, identifiers = [], {}, set()
    for row in intake["records"]:
        identifier, performer = row.get("id"), row.get("performer")
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identifier) or identifier in identifiers:
            raise ValueError("Invalid or duplicate clip id")
        identifiers.add(identifier)
        if row.get("source_condition") not in CONDITIONS or row.get("split") not in {"development", "regression"}:
            raise ValueError("Invalid condition or split")
        if not isinstance(performer, str) or not performer.strip():
            raise ValueError("Performer/group identity is required")
        if performer in performers and performers[performer] != row["split"]:
            raise ValueError("A performer cannot appear in both splits")
        performers[performer] = row["split"]
        if not all(isinstance(row.get(key), str) and row[key].strip() for key in ("source_url", "license", "annotator")):
            raise ValueError("Source URL, license and independent annotator are required")
        audio = local_file(source, row.get("audio"))
        reference = local_file(source, row.get("reference"))
        if audio.suffix.lower() != ".wav" or audio.stat().st_size > 300_000_000 or reference.stat().st_size > 5_000_000:
            raise ValueError("Use a WAV under 300 MB and annotation under 5 MB")
        with wave.open(str(audio), "rb") as stream:
            duration = stream.getnframes() / stream.getframerate()
        if not 1 <= duration <= 1200:
            raise ValueError("Recording duration outside supported range")
        validate_reference(json.loads(reference.read_text(encoding="utf-8")), duration)
        records.append({"id": identifier, "performer": performer, "style": row.get("style", "independent"),
            "genre": row.get("genre", "unknown"), "source_condition": row["source_condition"],
            "split": row["split"], "audio": f"clips/{identifier}/audio.wav",
            "reference": f"clips/{identifier}/reference.json", "audio_sha256": checksum(audio),
            "reference_sha256": checksum(reference), "source_url": row["source_url"],
            "license": row["license"], "annotator": row["annotator"]})
    manifest = {"schema": 1, "source": intake.get("source", "user_supplied_independent_annotations"),
        "reference_policy": "published_annotations_only_never_predictions",
        "model_training_overlap": "unknown_not_audited", "records": records}
    destination.mkdir(parents=True, exist_ok=True)
    for row, record in zip(intake["records"], records):
        target = destination / "clips" / record["id"]
        target.mkdir(parents=True)
        shutil.copyfile(local_file(source, row["audio"]), target / "audio.wav")
        shutil.copyfile(local_file(source, row["reference"]), target / "reference.json")
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(f"Imported {len(import_corpus(args.source, args.destination)['records'])} clips; training overlap still requires audit")
