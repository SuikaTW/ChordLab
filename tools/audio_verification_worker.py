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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("midi", type=Path)
    parser.add_argument("--notes-cache", required=True, type=Path)
    parser.add_argument("--references", type=Path)
    parser.add_argument("--reference-audio", action="append", type=Path, default=[])
    parser.add_argument("--preview", type=Path)
    args = parser.parse_args()
    started = time.monotonic()
    samples, _ = librosa.load(args.audio, sr=16000, mono=True)
    source = json.loads(args.notes_cache.read_text())
    if source.get("duration") is not None and abs(float(source["duration"])-len(samples)/16000) > .05:
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
    notes, summary = verify(samples, source["notes"], combine_profiles(profiles))
    payload = dict(engine="verified", profile="guitar_verified_v1", duration=round(len(samples)/16000,4),
        notes=notes, note_count=len(notes), refinement=summary, experimental=True,
        source_engine=source.get("engine", "basic_pitch"),
        elapsed_seconds=round(time.monotonic()-started,3), confidence_kind="uncalibrated_spectral_fit")
    write_midi(notes, args.midi)
    if args.preview:
        wavfile.write(args.preview, 16000, (synthesize(notes,len(samples)/16000)*32767).astype(np.int16))
    args.output.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
