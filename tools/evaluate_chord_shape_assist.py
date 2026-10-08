"""Compare opt-in chord-shape TAB placement on immutable pinned references."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from reference_corpus import checksum

ROOT = Path(__file__).resolve().parents[1]


def run(report_path: Path, playable: bool = False) -> dict:
    report = json.loads(report_path.read_text())
    corpus = report_path.parent
    manifest = json.loads((corpus / "manifest.json").read_text())
    if checksum(corpus / "manifest.json") != report["manifest_sha256"]:
        raise ValueError("Corpus manifest changed since the pinned report")
    references = {row["id"]: corpus / row["reference"] for row in manifest["records"]}
    results = []
    with tempfile.TemporaryDirectory(prefix="chordlab-chord-tab-") as temporary:
        for row in report["reports"]:
            if row["engine"] != "event_verified" or "displayed_tab" not in row:
                continue
            if checksum(corpus / row["prediction"]) != row["prediction_sha256"] or \
                    checksum(references[row["id"]]) != row["reference_sha256"]:
                raise ValueError(f"Pinned prediction/reference changed: {row['id']}")
            def evaluate(mode: str) -> dict:
                output = Path(temporary) / f"{row['id']}-{mode}.json"
                command = [str(ROOT / "bin/deno"), "run",
                    "--allow-read=" + str(corpus), "--allow-write=" + str(output),
                    str(ROOT / "tools/evaluate_fingering.js"), str(corpus / row["prediction"]),
                    str(references[row["id"]]), str(output), mode]
                subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True, timeout=120)
                return json.loads(output.read_text())
            candidate = evaluate("playable-chord" if playable else "model-chord")
            baseline = evaluate("playable") if playable else row["displayed_tab"]
            results.append(dict(id=row["id"], split=row["split"], baseline=baseline,
                candidate=candidate, delta_fingering=round(candidate.get("fingering_agreement", 0) -
                    baseline.get("fingering_agreement", 0), 6)))
    aggregate = {}
    for split in ("development", "regression", "all"):
        rows = [row for row in results if split == "all" or row["split"] == split]
        aggregate[split] = dict(clips=len(rows), reference_fingerings=sum(
            row["baseline"].get("reference_fingerings", 0) for row in rows))
        for label in ("baseline", "candidate"):
            total = sum(row[label].get("reference_fingerings", 0) for row in rows)
            aggregate[split][label] = dict(fingering_agreement=round(sum(
                row[label].get("fingering_agreement", 0) * row[label].get("reference_fingerings", 0)
                for row in rows) / max(1, total), 6),
                displayed_f1=round(sum(row[label]["f1"] for row in rows) / max(1, len(rows)), 6))
    return dict(source_report=str(report_path), source_report_sha256=checksum(report_path),
        evaluator_sha256=checksum(ROOT / "tools/evaluate_fingering.js"),
        tab_engine_sha256=checksum(ROOT / "app/static/tab-engine.js"),
        voicings_sha256=checksum(ROOT / "app/static/chord-voicings.js"),
        mode="playable" if playable else "model",
        policy="prediction_chords_only; references_scoring_only",
        aggregate=aggregate, results=results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--playable", action="store_true", help="Compare without model string/fret hints")
    args = parser.parse_args()
    result = run(args.report, args.playable)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result["aggregate"], ensure_ascii=False, indent=2))
