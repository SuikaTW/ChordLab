"""Reproducible generated reference corpus. This is NOT a real-song accuracy test."""
from pathlib import Path
import json
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.audio_verification import synthesize, verify, SR
from tools.benchmark_guitar import score


def main():
    melody = [dict(start=i*.5+.1,end=i*.5+.45,midi=pitch) for i,pitch in enumerate([40,47,52,55,59,64,67,71])]
    chords = [dict(start=i*.6+.1,end=i*.6+.55,midi=pitch) for i,pitches in enumerate([[48,52,55,60],[45,52,57,60],[41,48,53,57],[43,50,55,59]]) for pitch in pitches]
    reports = []
    for title,reference,duration in [("single_notes",melody,4.2),("polyphonic_progression",chords,2.6)]:
        for noise in [0,.002]:
            audio = synthesize(reference,duration)
            audio = audio + np.random.default_rng(20261007).normal(0,noise,len(audio))
            predicted = [{**note,"midi":note["midi"]+12 if index%3==0 else note["midi"]} for index,note in enumerate(reference)]
            corrected,summary = verify(audio,predicted)
            reports.append(dict(corpus=title,noise=noise,reference_notes=len(reference),
                before=score(reference,predicted),after=score(reference,corrected),
                changes=summary["changed_notes"],rechecked=summary["rechecked_changes"],
                label="synthetic_only_not_real_song_accuracy"))
    print(json.dumps(reports,ensure_ascii=False,indent=2))


if __name__ == "__main__": main()
