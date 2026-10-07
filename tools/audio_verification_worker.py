"""CPU-only optional verification. Outputs are separate from every baseline."""
import argparse
import json
from pathlib import Path
import sys
import time
import librosa
import numpy as np
from scipy.io import wavfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.audio_verification import verify, harmonic_profile, combine_profiles, synthesize
from tools.guitar_worker import write_midi
from tools.cross_evidence import CrossEvidence, review_chords
from tools.event_verification import refine_events


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("midi", type=Path)
    parser.add_argument("--notes-cache", required=True, type=Path)
    parser.add_argument("--references", type=Path)
    parser.add_argument("--reference-audio", action="append", type=Path, default=[])
    parser.add_argument("--preview", type=Path)
    parser.add_argument("--cross-evidence", type=Path)
    parser.add_argument("--harmony-audio",type=Path)
    parser.add_argument("--event-review",action="store_true")
    parser.add_argument("--original-audio",type=Path)
    args = parser.parse_args()
    started = time.monotonic()
    samples, _ = librosa.load(args.audio, sr=16000, mono=True)
    source = json.loads(args.notes_cache.read_text())
    if source.get("profile") not in {"guitar_v2", "guitar_v1", "general"} and source.get("duration") is not None and abs(float(source["duration"])-len(samples)/16000) > .05:
        raise ValueError("Cached notes do not match recording duration")
    if len(samples)/16000 > 1200.25 or not np.isfinite(samples).all():
        raise ValueError("Invalid verification recording")
    profiles = []
    if args.references:
        for reference in json.loads(args.references.read_text())[:8]:
            if Path(reference["audio"]) not in args.reference_audio:
                raise ValueError("Reference audio outside explicit allowlist")
            audio, _ = librosa.load(reference["audio"], sr=16000, mono=True)
            profiles.append(harmonic_profile(audio, reference["notes"]))
    cross = CrossEvidence(json.loads(args.cross_evidence.read_text()),len(samples)/16000,source.get("engine","basic_pitch")) if args.cross_evidence else None
    notes, summary = verify(samples, source["notes"], combine_profiles(profiles), cross=cross)
    if args.event_review and cross is None:
        raise ValueError("Event review requires independent evidence")
    event_summary = None
    if args.event_review:
        original,_ = librosa.load(args.original_audio,sr=16000,mono=True) if args.original_audio else (None,None)
        notes,event_summary = refine_events(samples,notes,cross,original)
        summary.update(timing_policy="bounded_onset_repairs",note_count_policy="bounded_independent_additions",
            limitations=["spectral_gain_is_not_accuracy","no_string_identification","no_automatic_training","event_edits_experimental"])
    payload = dict(engine="event_verified" if args.event_review else "cross_verified" if cross else "verified", profile="guitar_event_verified_v1" if args.event_review else "guitar_cross_verified_v1" if cross else "guitar_verified_v1", duration=round(len(samples)/16000,4),
        notes=notes, note_count=len(notes), refinement=summary, experimental=True,
        source_engine=source.get("engine", "basic_pitch"),
        elapsed_seconds=round(time.monotonic()-started,3), confidence_kind="uncalibrated_spectral_fit")
    if event_summary:
        payload["event_review"] = event_summary
    if cross:
        payload.update(fingering_tuning="standard",fingering_capo=0)
        harmony,_ = librosa.load(args.harmony_audio,sr=16000,mono=True) if args.harmony_audio else (samples,16000)
        if abs(len(harmony)-len(samples))/16000 > .05:
            raise ValueError("Harmony recording is not time-aligned")
        payload["chords"],payload["chord_review"] = review_chords(harmony,notes,cross)
        payload["elapsed_seconds"] = round(time.monotonic()-started,3)
    write_midi(notes, args.midi)
    if args.preview:
        wavfile.write(args.preview, 16000, (synthesize(notes,len(samples)/16000)*32767).astype(np.int16))
    args.output.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
