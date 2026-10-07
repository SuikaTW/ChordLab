"""Run the application's pinned, sandboxed workers against immutable references.

Audio/reference stay on HDD. No live jobs, model weights or reference labels
are updated. Development and regression performers are reported separately.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.reference_corpus import checksum
from tools.benchmark_guitar import score


def weighted_chords(reference, predicted, duration):
    from app.chord_comparison import identity
    boundaries=sorted({0.,duration,*[max(0.,min(duration,float(s[k]))) for segments in (reference,predicted) for s in segments for k in ("start","end")]})
    matched,covered=0.,0.
    for left,right in zip(boundaries,boundaries[1:]):
        center=(left+right)/2
        expected=next((s["chord"] for s in reference if s["start"]<=center<s["end"]),None)
        actual=next((s["chord"] for s in predicted if s["start"]<=center<s["end"]),None)
        if expected is None: continue
        covered+=right-left
        if actual is not None and (expected==actual or identity(expected) is not None and identity(expected)==identity(actual)): matched+=right-left
    return dict(annotated_seconds=round(covered,3),exact_chord_duration_agreement=round(matched/max(covered,1e-12),4))


def run(root, infer=False, limit=None, reuse_raw_report=None):
    from dotenv import load_dotenv
    load_dotenv(ROOT/".env")
    from app import main
    manifest_hash=checksum(root/"manifest.json")
    manifest=json.loads((root/"manifest.json").read_text())
    if manifest.get("reference_policy")!="published_annotations_only_never_predictions":
        raise ValueError("Unreviewed corpus provenance")
    reusable = {}
    reuse_provenance = None
    if reuse_raw_report:
        previous=json.loads(reuse_raw_report.read_text())
        if previous.get('manifest_sha256') != manifest_hash:
            raise ValueError('Raw predictions belong to a different corpus manifest')
        for row in previous['reports']:
            if row['engine'] in {'basic_pitch','gaps','tabcnn','hybrid','chordino'}:
                key=(row['id'],row['engine'])
                if key in reusable: raise ValueError('Duplicate raw prediction provenance')
                reusable[key]=row
        reuse_provenance=dict(report_sha256=checksum(reuse_raw_report),pipeline_sha256=previous['pipeline_sha256'])
    if infer:
        with main.db() as connection:
            if connection.execute("SELECT 1 FROM guitar_tasks WHERE status IN ('queued','working')").fetchone() or connection.execute("SELECT 1 FROM jobs WHERE status IN ('queued','working')").fetchone():
                raise RuntimeError("Live analyses active; rerun the resumable benchmark later")
    code_paths=["tools/basic_pitch_worker.py","tools/guitar_worker.py","tools/guitar_refinement.py",
        "tools/audio_verification.py","tools/audio_verification_worker.py","tools/cross_evidence.py",
        "tools/event_verification.py","tools/temporal_verification.py","tools/chordino_worker.py","app/static/tab-engine.js"]
    code_hashes={name:checksum(ROOT/name) for name in code_paths}
    pipeline=hashlib.sha256(json.dumps(code_hashes,sort_keys=True).encode()).hexdigest()
    evaluation_paths=["tools/benchmark_corpus.py","tools/benchmark_guitar.py",
        "tools/evaluate_fingering.js","tools/reference_corpus.py"]
    evaluation=hashlib.sha256(json.dumps({name:checksum(ROOT/name) for name in evaluation_paths},sort_keys=True).encode()).hexdigest()
    main.JOBS=root/"runs"/pipeline[:12]
    main.JOBS.mkdir(parents=True,exist_ok=True)
    reports=[]
    for record in manifest["records"][:limit]:
        audio,reference=root/record["audio"],root/record["reference"]
        if checksum(audio)!=record["audio_sha256"] or checksum(reference)!=record["reference_sha256"]:
            raise ValueError("Immutable corpus checksum mismatch")
        labels=json.loads(reference.read_text())
        directory=main.JOBS/record["id"]; directory.mkdir(exist_ok=True)
        local_audio=directory/"audio.wav"
        if not local_audio.exists(): shutil.copyfile(audio,local_audio)
        if checksum(local_audio)!=record["audio_sha256"]: raise ValueError("Benchmark input changed")
        with wave.open(str(local_audio),"rb") as recording:
            duration=recording.getnframes()/recording.getframerate()
        for engine in ("basic_pitch","gaps","tabcnn","hybrid","chordino","cross_verified","event_verified"):
            path=directory/(engine+".json")
            if not path.exists() and (record['id'],engine) in reusable:
                cached=reusable[(record['id'],engine)]
                source=(root/cached['prediction']).resolve()
                if not source.is_relative_to((root/'runs').resolve()) or source.parent.name != record['id'] or source.name != engine+'.json':
                    raise ValueError('Raw prediction path outside pinned corpus run')
                if cached['reference_sha256'] != record['reference_sha256'] or checksum(source) != cached['prediction_sha256'] or checksum(source.parent/'audio.wav') != record['audio_sha256']:
                    raise ValueError('Raw prediction provenance/checksum mismatch')
                shutil.copyfile(source,path)
            if infer and not path.exists():
                output=directory/(engine+".tmp.json"); midi=directory/(engine+".mid")
                if engine=="basic_pitch":
                    command=[str(main.BASIC_PYTHON),str(ROOT/"tools/basic_pitch_worker.py"),str(local_audio),str(output),str(midi),"--guitar"]
                elif engine=="chordino":
                    command=[str(main.CHORDINO_PYTHON),str(ROOT/"tools/chordino_worker.py"),str(local_audio),str(output)]
                elif engine in {"cross_verified","event_verified"}:
                    models={name:json.loads((directory/(name+".json")).read_text()) for name in ("basic_pitch","gaps","tabcnn","hybrid")}
                    chords=json.loads((directory/"chordino.json").read_text())["chords"]
                    evidence=directory/"evidence.json"
                    evidence.write_text(json.dumps(dict(models=models,methods={"chordino":chords},active_method="chordino")))
                    command=[str(main.GUITAR_PYTHON),str(ROOT/"tools/audio_verification_worker.py"),str(local_audio),str(output),str(midi),"--notes-cache",str(directory/"hybrid.json"),"--cross-evidence",str(evidence),"--harmony-audio",str(local_audio),*(["--event-review"] if engine=="event_verified" else [])]
                else:
                    command=[str(main.GUITAR_PYTHON),str(ROOT/"tools/guitar_worker.py"),str(local_audio),str(output),str(midi),"--engine",engine,*(["--gaps-cache",str(directory/"gaps.json")] if engine=="hybrid" else [])]
                started=time.monotonic()
                main.run_command(command,timeout=1800,env={"VAMP_PATH":str(main.VAMP_PATH)} if engine=="chordino" else None)
                output.replace(path)
                print(record["id"],engine,"seconds",round(time.monotonic()-started,1),flush=True)
            if not path.exists(): continue
            predicted=json.loads(path.read_text())
            report=dict(id=record["id"],split=record["split"],style=record["style"],engine=engine,prediction=str(path.relative_to(root)),
                reference_sha256=record["reference_sha256"],prediction_sha256=checksum(path))
            if "notes" in predicted:
                notes=predicted["notes"]
                report.update(reference_notes=len(labels["notes"]),predicted_notes=len(notes),
                    pitch_onset=score(labels["notes"],notes),pitch_onset_offset=score(labels["notes"],notes,offsets=True))
                if all("model_string" in n for n in notes): report["string_fret_onset"]=score(labels["notes"],notes,fingerings=True)
                fingering=directory/(engine+"-fingering.json")
                # Use the actual client allocator, not a separate idealized one.
                subprocess.run([str(ROOT/"bin/deno"),"run","--allow-read="+str(directory)+","+str(reference),"--allow-write="+str(directory),
                    str(ROOT/"tools/evaluate_fingering.js"),str(path),str(reference),str(fingering),"model"],timeout=120,
                    check=True,capture_output=True,text=True,cwd=ROOT,env=main.command_environment())
                report["displayed_tab"]=json.loads(fingering.read_text())
                if predicted.get("event_review"): report["event_review"]=predicted["event_review"]
            if "chords" in predicted:
                report["chord_annotations"]=[dict(provenance=track["provenance"],metrics=weighted_chords(track["segments"],predicted["chords"],duration)) for track in labels["chord_annotations"]]
            reports.append(report)
        assert checksum(reference)==record["reference_sha256"], "Reference must never change"
        aggregate=[]
        for split in ("development","regression"):
            for engine in ("basic_pitch","gaps","tabcnn","hybrid","cross_verified","event_verified"):
                rows=[r for r in reports if r["split"]==split and r["engine"]==engine and "pitch_onset" in r]
                if not rows: continue
                matched=sum(r["pitch_onset"]["matched"] for r in rows)
                expected=sum(r["reference_notes"] for r in rows);actual=sum(r["predicted_notes"] for r in rows)
                precision=matched/max(1,actual);recall=matched/max(1,expected)
                aggregate.append(dict(split=split,engine=engine,clips=len(rows),matched=matched,reference_notes=expected,predicted_notes=actual,
                    precision=round(precision,4),recall=round(recall,4),f1=round(2*precision*recall/max(1e-12,precision+recall),4)))
        if checksum(root/"manifest.json")!=manifest_hash:
            raise ValueError("Corpus manifest changed during evaluation")
        if any(checksum(ROOT/name)!=digest for name,digest in code_hashes.items()):
            raise ValueError('Inference code changed during evaluation; rerun under its new fingerprint')
        result=dict(schema=1,source=manifest["source"],model_training_overlap=manifest["model_training_overlap"],
            pipeline_sha256=pipeline,inference_code_hashes=code_hashes,evaluation_sha256=evaluation,manifest_sha256=manifest_hash,
            policy="references_not_passed_to_inference_no_automatic_training",reused_raw_predictions=reuse_provenance,reports=reports,aggregate=aggregate)
        (root/"report.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
        (root/("report-"+pipeline[:12]+"-"+evaluation[:12]+".json")).write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return reports


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("--infer",action="store_true")
    parser.add_argument("--limit",type=int)
    parser.add_argument("--reuse-raw-report",type=Path,help="Explicit checksum-verified fixed raw predictions; cross/event stages rerun")
    args=parser.parse_args()
    run(args.root,args.infer,args.limit,args.reuse_raw_report)

if __name__=="__main__": main()
