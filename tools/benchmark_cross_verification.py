"""Generated ground truth for cross-checking, NOT a real-song accuracy claim."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.audio_verification import verify, synthesize
from tools.cross_evidence import CrossEvidence, review_chords
from tools.benchmark_guitar import score


def main():
    reference=[dict(start=i*.55+.15,end=i*.55+.6,midi=pitch) for i,pitch in enumerate((45,50,54,57,61,64,66,69))]
    predicted=[{**note,"midi":note["midi"]-2 if index%2==0 else note["midi"]} for index,note in enumerate(reference)]
    data={"models":{"gaps":{"notes":predicted},"hybrid":{"notes":predicted},"basic_pitch":{"notes":reference},
          "tabcnn":{"notes":[{**note,"model_string":max(index for index,base in enumerate((40,45,50,55,59,64)) if base<=note["midi"]),"model_fret":0} for note in reference]}},
          "methods":{"chordino":[{"start":0,"end":4.6,"chord":"D"}],"btc":[{"start":0,"end":4.6,"chord":"D"}]}}
    tuning=(40,45,50,55,59,64)
    for note in data["models"]["tabcnn"]["notes"]:
        note["model_fret"]=note["midi"]-tuning[note["model_string"]]
    audio=synthesize(reference,4.6)
    old,_=verify(audio,predicted)
    cross=CrossEvidence(data,4.6,"gaps")
    new,summary=verify(audio,predicted,cross=cross)
    print(json.dumps({"corpus":"synthetic_whole_tone_errors_and_outside_chord_tones","before":score(reference,predicted),
        "audio_only":score(reference,old),"cross_check":score(reference,new),"changes":summary["changed_notes"],
        "models":summary["independent_models"],"label":"synthetic_only_not_real_song_accuracy"},indent=2))


if __name__=="__main__": main()
