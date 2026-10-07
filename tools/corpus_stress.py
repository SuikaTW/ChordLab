"""Explicit, reproducible timbre/mix stress cases from licensed references.

These are effect-rendered acoustic guitar / procedural drum mixes, NOT real
electric-guitar or band recordings. No timing/pitch alteration or learned labels.
Use a new output directory; source references and pilot corpus never change.
"""
import argparse
import json
from pathlib import Path
import shutil
import sys
import wave
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.reference_corpus import checksum


def render(samples,sr,mode):
    source=np.asarray(samples,dtype=float)
    if mode=='effect_rendered':
        peak=max(1e-8,float(np.max(np.abs(source))))
        # Memoryless soft clipping: introduces harmonics, not delay or tuning.
        output=np.tanh(source/peak*3)*peak
    elif mode=='synthetic_drum_mix':
        rng=np.random.default_rng(20261008)
        percussion=np.zeros(len(source))
        for time in np.arange(0,len(source)/sr,.5):
            start=round(time*sr);size=min(round(.12*sr),len(source)-start)
            t=np.arange(size)/sr
            percussion[start:start+size]+=rng.normal(0,1,size)*np.exp(-t*45)
        rms=lambda signal:float(np.sqrt(np.mean(signal*signal)))
        output=source+percussion*(rms(source)/max(1e-12,rms(percussion)))*.25
    else:raise ValueError('Unknown stress condition')
    return output/max(1.,float(np.max(np.abs(output)))*1.01)


def build(source,destination,count=4):
    if destination.exists():raise ValueError('Use a new stress corpus directory')
    if not 1<=count<=12:raise ValueError('Stress selection limit is 1–12')
    manifest=json.loads((source/'manifest.json').read_text())
    if manifest['license']!='CC-BY-4.0' or manifest['reference_policy']!='published_annotations_only_never_predictions':
        raise ValueError('Unreviewed source corpus')
    destination.mkdir(parents=True)
    records=[]
    for record in manifest['records'][:count]:
        audio=source/record['audio'];reference=source/record['reference']
        if checksum(audio)!=record['audio_sha256'] or checksum(reference)!=record['reference_sha256']:
            raise ValueError('Immutable input checksum mismatch')
        with wave.open(str(audio),'rb') as input:
            sr=input.getframerate()
            if input.getnchannels()!=1 or input.getsampwidth()!=2:raise ValueError('Expected mono PCM16')
            samples=np.frombuffer(input.readframes(input.getnframes()),dtype='<i2')/32768.
        for mode in ('effect_rendered','synthetic_drum_mix'):
            identifier=record['id']+'__'+mode
            directory=destination/'clips'/identifier;directory.mkdir(parents=True)
            with wave.open(str(directory/'audio.wav'),'wb') as output:
                output.setnchannels(1);output.setsampwidth(2);output.setframerate(sr)
                output.writeframes(np.clip(render(samples,sr,mode)*32768,-32768,32767).astype('<i2').tobytes())
            shutil.copyfile(reference,directory/'reference.json')
            records.append({**record,'id':identifier,'source_condition':mode,'derived_from':record['id'],
                'audio':str((directory/'audio.wav').relative_to(destination)),
                'reference':str((directory/'reference.json').relative_to(destination)),
                'audio_sha256':checksum(directory/'audio.wav')})
    result={**manifest,'selection':'controlled_derived_stress_not_real_electric_or_mix',
        'source_manifest_sha256':checksum(source/'manifest.json'),'records':records}
    (destination/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print('Controlled stress clips',len(records),flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path);parser.add_argument('destination',type=Path)
    parser.add_argument('--count',type=int,default=4)
    args=parser.parse_args();build(args.source,args.destination,args.count)
