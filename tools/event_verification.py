"""Conservative event edits, with independent nominations and local audio vetoes.

Repeated phrases are diagnostic evidence, never a source of reference labels.
An original mix is a veto/confirmation only, not another instrument-model vote.
"""
from __future__ import annotations
import bisect
from collections import defaultdict
import numpy as np
from scipy.signal import find_peaks
from tools.audio_verification import SR, FREQ, spectrum, template, fit, validate
from tools.temporal_verification import PitchEnvelope, harmonic_conflict, refine_offsets, split_retrigger


def verification_centers(start, end):
    # Later windows are an out-of-early-window confirmation, not extra votes.
    return sorted(set(start + min(delta, (end-start)*fraction)
                      for delta, fraction in ((.06,.2),(.11,.4),(.18,.65),(.25,.85))))


def addition_gain(before, after, voices):
    # An extra spectral component always makes NNLS fit no worse. Charge for
    # that complexity and demand improvement in every independent time window.
    return before-after > max(.09 + .02*voices, before*.22)


def attacks(samples):
    """Bounded 10ms RMS and broadband spectral-flux candidates, no quantization."""
    hop, window = 160, 1024
    count = (len(samples)+hop-1)//hop
    rms, flux = np.zeros(count), np.zeros(count)
    previous = np.zeros(513)
    for first in range(0,count,256):
        times = np.arange(first,min(count,first+256))*hop
        indices = times[:,None]+np.arange(window)[None,:]-window//2
        frames = samples[np.clip(indices,0,len(samples)-1)]
        frames[(indices < 0) | (indices >= len(samples))] = 0
        rms[first:first+len(times)] = np.sqrt(np.mean(frames*frames,axis=1))
        magnitude = np.abs(np.fft.rfft(frames*np.hanning(window),axis=1))
        differences = np.maximum(0,magnitude-np.vstack([previous,magnitude[:-1]]))
        flux[first:first+len(times)] = differences[:,4:].sum(axis=1)
        previous = magnitude[-1]
    if flux.max(initial=0) < 1e-7: return np.array([])
    peaks,_ = find_peaks(flux,distance=6,prominence=max(1e-7,float(np.percentile(flux,75))*.5))
    peaks = peaks[rms[peaks] >= max(1e-6,rms.max(initial=0)*.012)]
    return peaks*.01


def repeated_phrases(notes):
    grouped = defaultdict(set)
    for note in notes: grouped[round(note["start"]/.04)*.04].add(note["midi"])
    groups = sorted(grouped.items())[:5000]
    patterns = defaultdict(list)
    for index in range(len(groups)-3):
        block = groups[index:index+4]
        if block[-1][0]-block[0][0] < .3 or block[-1][0]-block[0][0] > 6: continue
        key = tuple((tuple(sorted(pitches)),round((time-block[0][0])/.08)) for time,pitches in block)
        occurrences = patterns[key]
        if not occurrences or block[0][0] > occurrences[-1][1]+.3:
            occurrences.append((block[0][0],block[-1][0]))
    examples = [dict(start=times[0][0],end=times[0][1],occurrences=[t[0] for t in times[:8]])
                for times in patterns.values() if len(times) >= 2]
    return dict(matched_patterns=len(examples),examples=examples[:20],policy="exact_pitch_rhythm_hint_not_copy_or_training")


def refine_events(samples, notes, cross, original=None):
    samples = np.asarray(samples,dtype=float)
    duration = len(samples)/SR
    validate(notes,duration)
    if not np.isfinite(samples).all() or samples.ndim != 1:
        raise ValueError("Invalid event audio")
    if original is not None:
        original = np.asarray(original,dtype=float)
        if original.ndim != 1 or not np.isfinite(original).all() or abs(len(original)-len(samples))/SR > .05:
            raise ValueError("Original mix not time-aligned")
    output = [dict(note) for note in notes]
    peaks = attacks(samples)
    dictionary = {pitch:template(pitch) for pitch in range(36,100)}
    envelope = PitchEnvelope(samples)
    original_envelope = PitchEnvelope(original) if original is not None else None
    edits, suggestions = [], []
    def has_attack(start):
        at = bisect.bisect_left(peaks,start-.06)
        return at < len(peaks) and peaks[at] <= start+.06
    def attack_distance(start):
        at = bisect.bisect_left(peaks,start)
        return min((abs(float(peaks[i])-start) for i in (at-1,at) if 0 <= i < len(peaks)),default=float("inf"))
    def audible(pitch,start,end,audio=samples):
        centers = [start+min(.08,(end-start)*.3),start+min(.16,(end-start)*.7)]
        specs = [spectrum(audio,c) for c in centers]
        frequency = 440*2**((pitch-69)/12)
        return all(spec.max() >= 1e-7 and spec[np.abs(FREQ-frequency)<=10].max(initial=0) >= spec.max()*.07 for spec in specs)
    # Existing events: only bounded timing repair with two model onsets AND an
    # audio transient. False notes are reported unless they are truly silent.
    for index,note in enumerate(output):
        if note.get("edited"): continue
        support = []
        for family,(stream,starts) in cross.streams.items():
            low,high = bisect.bisect_left(starts,note["start"]-.08),bisect.bisect_right(starts,note["start"]+.08)
            matches = [n for n in stream[low:high] if n["midi"]==note["midi"]]
            if matches: support.append((family,min(matches,key=lambda n:abs(n["start"]-note["start"]))))
        if len(support)>=2:
            proposed = float(np.median([n["start"] for _,n in support]))
            if .015 < abs(proposed-note["start"]) <= .06 and proposed >= 0 and note["end"]-proposed >= .06 and attack_distance(proposed) <= .025 and attack_distance(note["start"])-attack_distance(proposed) > .02:
                if audible(note["midi"],proposed,note["end"]) and (original is None or audible(note["midi"],proposed,note["end"],original)):
                    before = note["start"]; note.update(start=round(proposed,4),event_changed=True)
                    edits.append(dict(kind="onset",index=index,before=before,after=note["start"]))
        if note["end"]-note["start"] < .18 or audible(note["midi"],note["start"],note["end"]): continue
        suggestions.append(dict(kind="possible_false_note",index=index,start=note["start"],midi=note["midi"]))
    # Missing events must be independently nominated by at least two families.
    # No peaks-alone transcription and no generated MIDI/TAB-as-truth votes.
    nominations = []
    for family,(stream,_) in cross.streams.items():
        nominations.extend((n["start"],n["midi"],family,n) for n in stream)
    nominations.sort(key=lambda item:(item[0],item[1],item[2]))
    by_pitch = defaultdict(list)
    for _,pitch,family,note in nominations:
        matches = by_pitch[pitch]
        if matches and note["start"]-matches[-1][0] <= .035:
            matches[-1][1].setdefault(family,note)
        else: matches.append((note["start"],{family:note}))
    additions, candidate_checks, retriggers = 0, 0, 0
    for pitch,groups in by_pitch.items():
        for _,voters in groups:
            if additions >= 128 or len(output) >= 20000: break
            if len(voters) < 2: continue
            candidate_checks += 1
            if candidate_checks > 512: continue
            start = float(np.median([n["start"] for n in voters.values()]))
            end = min(duration,float(np.median([n["end"] for n in voters.values()])))
            if not 40<=pitch<=88 or end-start<.18 or not has_attack(start): continue
            same = [n for n in output if n["midi"]==pitch and abs(n["start"]-start)<.1]
            if same: continue
            # Splitting a long event is a retrigger candidate, not safe to force.
            if any(n["midi"]==pitch and n["start"]<start<n["end"] for n in output):
                split = split_retrigger(output,pitch,start,end,voters,peaks,envelope,original_envelope) if retriggers < 64 else None
                if split:
                    edits.append(split); retriggers += 1
                else:
                    suggestions.append(dict(kind="possible_retrigger",start=start,midi=pitch))
                continue
            if not audible(pitch,start,end) or original is not None and not audible(pitch,start,end,original): continue
            centers = [start+min(.08,(end-start)*.3),start+min(.16,(end-start)*.7)]
            neighbors = [[n["midi"] for n in output if n["start"]<=c<n["end"]][:7] for c in centers]
            if max(map(len,neighbors))>5 or any(pitch in p for p in neighbors): continue
            observed = [spectrum(samples,c) for c in centers]
            before = [fit(p,s,dictionary) if p else 1. for p,s in zip(neighbors,observed)]
            after = [fit([pitch,*p],s,dictionary) for p,s in zip(neighbors,observed)]
            if not all(a-b>max(.06,a*.15) for a,b in zip(before,after)): continue
            # The stricter four-window gate lost true notes on regression data.
            # Keep the validated selection policy and expose extra evidence as
            # advisory uncertainty, not a silently worse default threshold.
            strong = envelope.rises(pitch,start) and (original_envelope is None or original_envelope.rises(pitch,start))
            for center in verification_centers(start,end):
                pitches=[n['midi'] for n in output if n['start'] <= center < n['end']]
                if len(pitches)>5 or pitch in pitches or harmonic_conflict(output,pitch,center):
                    strong=False; break
                spec=spectrum(samples,center)
                old_fit=fit(pitches,spec,dictionary) if pitches else 1.
                if not addition_gain(old_fit,fit([pitch,*pitches],spec,dictionary),len(pitches)):
                    strong=False; break
            if not strong:
                suggestions.append(dict(kind="uncertain_addition",start=start,midi=pitch))
            note = dict(start=round(start,4),end=round(end,4),midi=pitch,
                velocity=float(np.median([n.get("velocity",.5) for n in voters.values()])),
                event_changed=True,event_added=True,fingering_uncertain=True,
                addition_uncertain=not strong,suspicious=not strong)
            output.append(note); additions+=1
            edits.append(dict(kind="add",start=start,midi=pitch,models=sorted(voters)))
    # Final simultaneous-note audit: revert additions whose evidence disappears.
    retained = []
    for note in output:
        if note.get("event_added"):
            centers = [note["start"]+min(.08,(note["end"]-note["start"])*.3),note["start"]+min(.16,(note["end"]-note["start"])*.7)]
            passed=True
            for center in centers:
                pitches=[n["midi"] for n in output if n is not note and n["start"]<=center<n["end"]]
                if len(pitches)>5 or note["midi"] in pitches: passed=False; break
                spec=spectrum(samples,center)
                before=fit(pitches,spec,dictionary) if pitches else 1.
                if before-fit([note["midi"],*pitches],spec,dictionary)<=max(.06,before*.15): passed=False; break
            if not passed: continue
        retained.append(note)
    retained.sort(key=lambda n:(n["start"],n["midi"]))
    offset_edits, offset_checks = refine_offsets(retained,cross,envelope,original_envelope)
    edits.extend(offset_edits)
    added=sum(bool(n.get("event_added")) for n in retained)
    summary=dict(version=2,added_notes=added,removed_notes=0,candidate_checks=min(candidate_checks,512),adjusted_onsets=sum(e["kind"]=="onset" for e in edits),
        adjusted_offsets=len(offset_edits),offset_checks=offset_checks,retrigger_splits=retriggers,
        uncertain_additions=sum(bool(n.get('event_added') and n.get('addition_uncertain')) for n in retained),
        reverted_additions=additions-added,review_candidates=len(suggestions),suggestions=suggestions[:200],
        changes=[e for e in edits if e["kind"]!="add" or any(n.get("event_added") and n["midi"]==e["midi"] and abs(n["start"]-e["start"])<.001 for n in retained)][:200],
        original_mix_checked=original is not None,repeat_evidence=repeated_phrases(notes),
        policy="two_window_selection_four_window_penalized_evidence_advisory_final_recheck",
        addition_evidence_policy="stricter_gate_not_default_due_to_regression_recall_loss",
        training_policy="none_no_predictions_as_reference",offset_policy="bounded_two_model_audio_drop",false_note_policy="review_only_no_automatic_deletion")
    validate(retained,duration)
    return retained,summary
