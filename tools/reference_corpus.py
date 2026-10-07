"""Pinned, licensed audio/annotation corpus. References never come from predictions.

Downloads are explicit (--download); inference is a separate benchmark command.
Only selected microphone recordings are extracted, never arbitrary zip paths.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import urllib.request
import zipfile

SOURCE = "https://zenodo.org/records/3371780"
FILES = {"annotation.zip": "b39b78e63d3446f2e54ddb7a54df9b10",
         "audio_mono-mic.zip": "275966d6610ac34999b58426beb119c3"}
EXCLUDED = {"04_BN3-154-E_comp", "04_Jazz1-200-B_comp", "02_Funk2-119-G_comp"}
TUNING = (40, 45, 50, 55, 59, 64)


def checksum(path, algorithm="sha256"):
    result = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def download(root):
    root.mkdir(parents=True, exist_ok=True)
    for name, expected in FILES.items():
        path = root / name
        if path.is_file() and checksum(path, "md5") == expected:
            continue
        temporary = path.with_suffix(".download")
        with urllib.request.urlopen(f"{SOURCE}/files/{name}?download=1", timeout=60) as response, temporary.open("wb") as output:
            size = 0
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > 750_000_000:
                    raise ValueError("Archive exceeds the download limit")
                output.write(block)
        if checksum(temporary, "md5") != expected:
            raise ValueError("Published archive checksum mismatch")
        temporary.replace(path)
        print("Verified", name, flush=True)


def parse_annotations(payload):
    annotations = [a for a in payload["annotations"] if a["namespace"] == "note_midi"]
    if len(annotations) != 6:
        raise ValueError("Expected six annotated strings")
    notes, seen_strings = [], set()
    for annotation in annotations:
        string = int(annotation["annotation_metadata"]["data_source"])
        if not 0 <= string < 6 or string in seen_strings:
            raise ValueError("Invalid annotated string")
        seen_strings.add(string)
        for event in annotation["data"]:
            midi = round(float(event["value"]))
            start = float(event["time"])
            end = start+float(event["duration"])
            if not all(map(math.isfinite,(start,end))) or end <= start or start < 0 or not 0 <= midi - TUNING[string] <= 24:
                raise ValueError("Invalid reference note")
            notes.append(dict(start=start, end=end, midi=midi, string=string, fret=midi-TUNING[string]))
            if len(notes)>20000: raise ValueError("Reference note limit exceeded")
    chords = []
    for annotation in payload["annotations"]:
        if annotation["namespace"] == "chord":
            chords.append({"provenance": annotation.get("annotation_metadata", {}), "segments": [
                dict(start=e["time"], end=e["time"]+e["duration"], chord=e["value"])
                for e in annotation["data"]]})
    return {"notes": sorted(notes, key=lambda n: (n["start"], n["midi"], n["string"])),
            "chord_annotations": chords, "tuning": "standard", "capo": 0}


def select_diverse(available,count):
    """Round-robin genre/style, then performers; never inspect predictions."""
    def category(name):
        token=name.split('_')[1].split('-')[0]
        genre=token.rstrip('0123456789')
        return genre,name.rsplit('_',1)[-1]
    buckets={}
    for name in available:buckets.setdefault(category(name),[]).append(name)
    selected=[];used_performers={}
    while len(selected)<min(count,len(available)):
        for key in sorted(buckets):
            choices=[name for name in buckets[key] if name not in selected]
            if not choices:continue
            chosen=min(choices,key=lambda name:(used_performers.get(name[:2],0),name))
            selected.append(chosen);used_performers[chosen[:2]]=used_performers.get(chosen[:2],0)+1
            if len(selected)==count:break
    return selected


def build(root, count=6, diverse=False):
    if not 2 <= count <= 60:
        raise ValueError("Corpus selection limit is 2–60")
    archives = root / "archives"
    for name, expected in FILES.items():
        if checksum(archives/name, "md5") != expected:
            raise ValueError("Archive checksum mismatch")
    clips = root / "clips"; clips.mkdir(exist_ok=True)
    records = []
    with zipfile.ZipFile(archives/"annotation.zip") as labels, zipfile.ZipFile(archives/"audio_mono-mic.zip") as audio:
        label_index = {Path(n).stem:n for n in labels.namelist() if n.endswith(".jams") and not Path(n).name.startswith(".")}
        audio_index = {Path(n).stem.removesuffix("_mic"):n for n in audio.namelist() if n.endswith(".wav") and not Path(n).name.startswith(".")}
        # Across performers and comp/solo styles, without inspecting predictions.
        available = sorted(set(label_index) & set(audio_index) - EXCLUDED)
        selected = []
        for performer in sorted({name[:2] for name in available}):
            for style in ("comp", "solo"):
                candidates = [name for name in available if name.startswith(performer+"_") and name.endswith("_"+style)]
                if candidates:
                    selected.append(candidates[0])
        selected.extend(name for name in available if name not in selected)
        if diverse:selected=select_diverse(available,count)
        if count == 2 and selected:
            other = next((name for name in selected if name[:2] != selected[0][:2]),None)
            selected = [selected[0],other] if other else selected[:2]
        selected = selected[:count]
        performers = sorted({name[:2] for name in selected})
        development = set(performers[:max(1,len(performers)//2)])
        for index, name in enumerate(selected):
            directory = clips/name; directory.mkdir(exist_ok=True)
            for archive, member, filename, limit in ((labels,label_index[name],"source.jams",12_000_000), (audio,audio_index[name],"audio.wav",50_000_000)):
                if archive.getinfo(member).file_size > limit:
                    raise ValueError("Selected corpus member exceeds limit")
                path = directory/filename
                data = archive.read(member)
                if path.exists() and path.read_bytes() != data:
                    raise ValueError("Immutable source already differs")
                if not path.exists(): path.write_bytes(data)
            reference = parse_annotations(json.loads((directory/"source.jams").read_text()))
            target = directory/"reference.json"
            rendered = json.dumps(reference, ensure_ascii=False, indent=2)+"\n"
            if target.exists() and target.read_text() != rendered:
                raise ValueError("Immutable reference already differs")
            if not target.exists(): target.write_text(rendered)
            records.append(dict(id=name, performer=name[:2], style=name.rsplit("_",1)[-1],
                genre=name.split('_')[1].split('-')[0].rstrip('0123456789'),source_condition='real_acoustic_guitar',
                split="development" if name[:2] in development else "regression",
                audio=str((directory/"audio.wav").relative_to(root)), reference=str(target.relative_to(root)),
                audio_sha256=checksum(directory/"audio.wav"), reference_sha256=checksum(target),
                source_sha256=checksum(directory/"source.jams")))
    manifest = dict(schema=1, source=SOURCE, version="1.1.0", license="CC-BY-4.0",
        attribution="Qingyang Xi, Rachel M. Bittner, Johan Pauwels, Xuzhou Ye, Juan P. Bello; GuitarSet, ISMIR 2018",
        reference_policy="published_annotations_only_never_predictions", model_training_overlap="possible_or_known_not_independent_blind_test",
        selection='genre_style_performer_round_robin' if diverse else 'legacy_pilot',
        excluded_known_annotation_errors=sorted(EXCLUDED), records=records)
    previous=root/'manifest.json'
    if previous.is_file() and json.loads(previous.read_text())!=manifest:
        raise ValueError('Existing corpus manifest is immutable; use a new corpus directory')
    (root/"manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n")
    print("Corpus records", len(records), flush=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--count", type=int, default=6)
    parser.add_argument('--diverse',action='store_true',help='Balance genre, comp/solo and performers; use a new directory')
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    if args.download: download(args.root/"archives")
    build(args.root, args.count,args.diverse)


if __name__ == "__main__": main()
