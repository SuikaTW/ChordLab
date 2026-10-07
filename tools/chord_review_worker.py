"""Sandboxed local chord recheck; produces a proposal, never edits stored chords."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audio',type=Path)
    parser.add_argument('evidence',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--bass',type=Path)
    parser.add_argument('--start',type=float,required=True)
    parser.add_argument('--end',type=float,required=True)
    args=parser.parse_args()
    if not 0<=args.start<args.end or not .5<=args.end-args.start<=90:raise ValueError('Local review duration outside limits')
    import librosa
    from tools.cross_evidence import CrossEvidence,review_chords
    from app.chord_review import merge_local,validate_proposal
    audio,_=librosa.load(args.audio,sr=16000,mono=True)
    bass,_=librosa.load(args.bass,sr=16000,mono=True) if args.bass else (None,None)
    data=json.loads(args.evidence.read_text())
    cross=CrossEvidence(data,len(audio)/16000,'basic_pitch')
    chords,summary=review_chords(audio,[],cross,bass,(args.start,args.end),dense=True)
    original=data['review_baseline']['segments']
    chords=merge_local(original,chords,args.start,args.end)
    chords=validate_proposal(chords,original,args.start,args.end,len(audio)/16000)
    args.output.write_text(json.dumps({'chords':chords,'summary':summary},ensure_ascii=False))


if __name__=='__main__':main()
