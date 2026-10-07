"""Bounded acoustic change proposals and decomposed evidence, not model votes.

Neither beat positions nor a chord language model force boundaries. Scores are
relative fit evidence, never calibrated probabilities or reference labels.
"""
import math
import numpy as np
from tools.audio_verification import SR, FREQ

ROOTS=('C','Db','D','Eb','E','F','Gb','G','Ab','A','Bb','B')
QUALITIES={'':(0,4,7),'m':(0,3,7),'7':(0,4,7,10),'maj7':(0,4,7,11),
           'm7':(0,3,7,10),'sus2':(0,2,7),'sus4':(0,5,7),'dim':(0,3,6),
           'add9':(0,4,7,2)}


def components(label, spectra, notes, start, end):
    from tools.cross_evidence import tones
    from app.chord_comparison import identity
    parsed=identity(label)
    if parsed is None or tones(label) is None:return {}
    root,quality,bass=parsed
    peaks=np.zeros(12)
    for spec in spectra:
        maximum=max(1e-12,float(spec.max()))
        for midi in range(36,77):
            frequency=440*2**((midi-69)/12)
            peaks[midi%12]=max(peaks[midi%12],float(spec[np.abs(FREQ-frequency)<=10].max(initial=0))/maximum)
    weights=np.zeros(12)
    for note in notes:
        overlap=max(0,min(end,note['end'])-max(start,note['start']))
        weights[note['midi']%12]+=min(.5,overlap)
    total=max(1e-12,float(weights.sum()))
    def item(pc):return {'pitch_class':pc,'fundamental_strength':round(float(peaks[pc]),3),'note_share':round(float(weights[pc])/total,3)}
    third=(root+3)%12 if quality.startswith('m') and not quality.startswith('maj') or quality.startswith('dim') else (root+4)%12
    if quality.startswith('sus'):third=None
    seventh=(root+11)%12 if quality in {'maj7','mMaj7'} else (root+9)%12 if quality=='dim7' else (root+10)%12 if '7' in quality else None
    return {'root':item(root),'bass_target':item(root if bass is None else bass),
            'third':item(third) if third is not None else None,'seventh':item(seventh) if seventh is not None else None,
            'policy':'component_evidence_not_probability'}


class HarmonicContext:
    def __init__(self,samples,notes=(),review_range=None,dense=False):
        if samples.ndim!=1 or not np.isfinite(samples).all():raise ValueError('Invalid harmonic audit audio')
        self.notes=notes
        self.duration=len(samples)/SR
        self.low,self.high=review_range or (0,self.duration)
        if not all(math.isfinite(t) for t in (self.low,self.high)) or not 0<=self.low<self.high<=self.duration+.02:
            raise ValueError('Invalid harmonic audit range')
        self.step=.125 if dense else .25
        self.times=np.arange(self.low+self.step/2,self.high,self.step)
        if len(self.times)>10000:raise ValueError('Harmonic audit frame limit')
        pitches=np.arange(36,89)
        frequencies=440*2**((pitches-69)/12)
        indices=[np.flatnonzero(np.abs(FREQ-frequency)<=8) for frequency in frequencies]
        profiles=[];energies=[]
        window=np.hanning(4096)
        for center in self.times:
            first=round(center*SR)-2048
            frame=np.zeros(4096);left=max(0,first);right=min(len(samples),first+4096)
            if right>left:frame[left-first:right-first]=samples[left:right]
            spec=np.abs(np.fft.rfft(frame*window))
            energy=float(np.sqrt(np.mean(frame*frame)));energies.append(energy)
            values=np.array([spec[index].max(initial=0) for index in indices])
            # Compress timbre dominance; ignore tiny spectral-floor components.
            values=np.sqrt(np.maximum(0,values-values.max(initial=0)*.025))
            pcs=np.bincount(pitches%12,weights=values,minlength=12)
            profiles.append(pcs/max(1e-12,float(np.linalg.norm(pcs))))
        self.profiles=np.asarray(profiles).reshape((-1,12));self.energies=np.asarray(energies)
        self.boundaries=[]
        span=max(2,round(.5/self.step))
        for index in range(span,len(self.times)-span):
            left=self.profiles[index-span:index].mean(axis=0)
            right=self.profiles[index:index+span].mean(axis=0)
            distance=1-float(np.dot(left,right)/max(1e-12,np.linalg.norm(left)*np.linalg.norm(right)))
            # Silence/volume changes cannot nominate a harmonic boundary.
            audible=min(np.median(self.energies[index-span:index]),np.median(self.energies[index:index+span]))>1e-5
            if audible and distance>.16:self.boundaries.append((float(self.times[index]),distance))
        selected=[]
        for time,strength in sorted(self.boundaries,key=lambda pair:-pair[1]):
            if self.low+.5<time<self.high-.5 and all(abs(time-other[0])>=.8 for other in selected):
                selected.append((time,strength))
            if len(selected)>=256:break
        self.boundaries=sorted(selected)

    def profile(self,start,end):
        indices=(self.times>=start)&(self.times<end)&(self.energies>1e-5)
        if not np.any(indices):return None
        profile=np.mean(self.profiles[indices],axis=0)
        return profile/max(1e-12,float(profile.sum()))

    def candidates(self,start,end):
        profile=self.profile(start,end)
        if profile is None:return []
        weights=np.zeros(12)
        for note in self.notes:
            overlap=max(0,min(end,note['end'])-max(start,note['start']))
            weights[note['midi']%12]+=min(.5,overlap)
        weights/=max(1e-12,float(weights.sum()))
        proposals=[]
        for root in range(12):
            for quality,intervals in QUALITIES.items():
                pcs=[(root+interval)%12 for interval in intervals]
                coverage=float(profile[pcs].sum());note_agreement=float(weights[pcs].sum())
                score=coverage+.22*note_agreement+.06*float(profile[root])-.025*(len(pcs)-3)
                proposals.append({'chord':ROOTS[root]+quality,'model':'audio_context','score':round(score,4),
                                  'note_agreement':round(note_agreement,4),'share':1.})
        proposals.sort(key=lambda item:-item['score'])
        return proposals[:3]

    def cuts(self,original):
        if original.get('manual') or original['end']-original['start']<2.5:return []
        return [time for time,_ in self.boundaries if original['start']+.5<time<original['end']-.5][:12]
