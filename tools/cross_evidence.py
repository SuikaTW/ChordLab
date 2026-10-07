"""Independent model families and soft harmony constraints, never majority truth."""
import bisect
import math
import hashlib
import json
from app.chord_comparison import identity, relation, valid_segments
from tools.audio_verification import validate, spectrum, template, fit

QUALITIES = {"":(0,4,7), "m":(0,3,7), "6":(0,4,7,9), "m6":(0,3,7,9),
    "7":(0,4,7,10), "maj7":(0,4,7,11), "m7":(0,3,7,10), "mMaj7":(0,3,7,11),
    "dim":(0,3,6), "dim7":(0,3,6,9), "m7b5":(0,3,6,10), "aug":(0,4,8),
    "sus":(0,5,7), "sus2":(0,2,7), "sus4":(0,5,7), "9":(0,4,7,10,2),
    "maj9":(0,4,7,11,2), "m9":(0,3,7,10,2), "add9":(0,4,7,2)}
TUNING = (40,45,50,55,59,64)
FAMILIES = {"basic_pitch":"basic_pitch", "gaps":"gaps", "hybrid":"gaps", "tabcnn":"tabcnn"}


def tones(label):
    parsed = identity(label)
    if not parsed or parsed[1] not in QUALITIES:
        return None
    root,quality,bass = parsed
    result = {(root+interval)%12 for interval in QUALITIES[quality]}
    if bass is not None:
        result.add(bass)
    return result


class CrossEvidence:
    def __init__(self, payload, duration, base_engine):
        self.streams, self.chords = {}, {}
        self.invalid_tab_events = 0
        self.raw_methods = {name:payload.get("methods",{}).get(name,[]) for name in ("chordino","btc","chord_v2")}
        self.active_method = payload.get("active_method")
        explicit=payload.get('review_baseline')
        if explicit:
            self.raw_methods[explicit['method']]=explicit['segments']
            self.active_method=explicit['method']
        # Harmonic-track note context is not an additional model vote. Isolated
        # guitar may be silent while piano/bass establish the song's harmony.
        self.harmony_notes = [n for n in payload.get('harmony_notes',[])[:20000]
                              if isinstance(n.get('midi'),int) and not isinstance(n['midi'],bool) and 36<=n['midi']<=99]
        validate(self.harmony_notes,duration)
        self.base_family = FAMILIES.get(base_engine, "basic_pitch")
        # Prefer raw GAPS if both GAPS and its hybrid exist, count the family once.
        for name in ("basic_pitch", "gaps", "hybrid", "tabcnn"):
            cached = payload.get("models", {}).get(name)
            if not cached:
                continue
            family = FAMILIES[name]
            if family in self.streams:
                continue
            # Basic Pitch's legacy duration is the final event end, not audio length.
            if name != "basic_pitch" and cached.get("duration") is not None and (not math.isfinite(float(cached["duration"])) or abs(float(cached["duration"])-duration) > .05):
                raise ValueError("Cross-model recording duration mismatch")
            notes = cached.get("notes", [])
            validate(notes,duration)
            cleaned = []
            for note in notes:
                if name == "tabcnn":
                    string,fret = note.get("model_string"),note.get("model_fret")
                    if not isinstance(string,int) or isinstance(string,bool) or not 0 <= string < 6 or not isinstance(fret,int) or isinstance(fret,bool) or not 0 <= fret <= 19 or TUNING[string]+fret != note["midi"]:
                        self.invalid_tab_events += 1
                        continue
                cleaned.append(note)
            cleaned.sort(key=lambda note: note["start"])
            if cleaned:
                self.streams[family] = (cleaned,[note["start"] for note in cleaned])
        # Basic-Pitch-derived chords, ensemble and earlier verification are NOT new votes.
        for name in ("chordino", "btc", "chord_v2"):
            if payload.get("methods", {}).get(name):
                segments = valid_segments(payload["methods"][name],duration)
                self.chords[name] = (segments,[segment["start"] for segment in segments])
        if explicit:
            segments=valid_segments(explicit['segments'],duration)
            self.chords[explicit['method']]=(segments,[segment['start'] for segment in segments])

    def context(self, note):
        support, hints = {}, {}
        for family,(notes,starts) in self.streams.items():
            low,high = bisect.bisect_left(starts,note["start"]-.1),bisect.bisect_right(starts,note["start"]+.1)
            for candidate in notes[low:min(high,low+64)]:
                if candidate["end"] <= note["start"]+.025:
                    continue
                # Only nearby pitch alternatives, not every tone of the other voice.
                midi = candidate["midi"]
                if abs(midi-note["midi"]) > 12:
                    continue
                support.setdefault(midi,set()).add(family)
                if family == "tabcnn" and candidate.get("fingering_score",0) >= .65:
                    hints[midi] = {key:candidate[key] for key in ("model_string","model_fret","fingering_score")}
        support.setdefault(note["midi"],set()).add(self.base_family)
        labels = []
        # Do not use changing chord boundaries as a reason to remove a passing tone.
        center = note["start"]+min(.1,(note["end"]-note["start"])/2)
        for name,(segments,starts) in self.chords.items():
            at = bisect.bisect_right(starts,center)-1
            if at < 0:
                continue
            segment = segments[at]
            pcs = tones(segment["chord"])
            if pcs and segment["start"]+.1 <= center < segment["end"]-.1:
                labels.append((name,segment["chord"],pcs))
        # Chord-v2 shares spectral evidence; do not amplify the same acoustic cue.
        independent = [entry for entry in labels if entry[0] != "chord_v2"] or labels[:1]
        affinity = lambda midi: sum(midi%12 in pcs for _,_,pcs in independent)/max(1,len(independent))
        original_votes = len(support[note["midi"]])
        alternatives = [midi for midi,voters in support.items() if midi != note["midi"] and len(voters) >= 2]
        # Other simultaneous chord tones are not contradictory votes for this note.
        stronger = any(len(support[midi]) > original_votes for midi in alternatives)
        conflict = bool(stronger or (independent and affinity(note["midi"]) == 0))
        return {"support":support,"hints":hints,"alternatives":alternatives,"conflict":conflict,
                "affinity":affinity,"original_votes":original_votes,"labels":[label for _,label,_ in independent]}

    @staticmethod
    def rank(context, midi, audio_loss):
        # A small tie-breaker only: harmony can never waive the audio acceptance gate.
        voters = len(context["support"].get(midi,()))
        return audio_loss - .012*min(3,voters) - .004*context["affinity"](midi)


def digest(segments):
    return hashlib.sha256(json.dumps(segments,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def stable_chord_runs(segments):
    """Combine same-family extension flicker, not distinct harmonic roots."""
    runs = []
    for segment in segments:
        length = segment['end'] - segment['start']
        if runs and abs(segment['start'] - runs[-1]['end']) <= .06 and relation(runs[-1]['chord'],segment['chord']) in {'agree','detail'}:
            run = runs[-1]
            run['end'] = segment['end']
        else:
            run = dict(start=segment['start'],end=segment['end'],chord=segment['chord'],weights={},confidence_weight=0.,confidence_duration=0.)
            runs.append(run)
        run['weights'][segment['chord']] = run['weights'].get(segment['chord'],0.) + length
        confidence = segment.get('confidence')
        if isinstance(confidence,(int,float)) and math.isfinite(confidence):
            run['confidence_weight'] += max(0.,min(1.,confidence))*length
            run['confidence_duration'] += length
    for run in runs:
        weights=run.pop('weights')
        run['chord'] = max(weights,key=weights.get)
        run['confidence'] = run.pop('confidence_weight') / run['confidence_duration'] if run['confidence_duration'] else None
        run.pop('confidence_duration')
    return runs


def chord_pieces(original, sources, baseline, acoustic_cuts=()):
    """Only durable independent-model changes nominate internal boundaries."""
    if original.get('manual') or not tones(original['chord']) or original['end']-original['start'] < 2.5:
        return [dict(original)]
    proposed = set(acoustic_cuts)
    for name, (segments, _) in sources.items():
        if name==baseline or name not in {'chordino','btc'}:
            continue
        for segment in segments:
            if segment['end'] <= original['start'] or segment['start'] >= original['end']:
                continue
            if segment['end']-segment['start'] < .8 or not tones(segment['chord']) or segment.get('confidence') is not None and segment['confidence'] < .45:
                continue
            if relation(segment['chord'],original['chord']) in {'agree','detail'}:
                continue
            proposed.update(t for t in (segment['start'],segment['end']) if original['start']+.4 < t < original['end']-.4)
    points = [original['start']]
    for boundary in sorted(proposed):
        if len(points) >= 17:
            break
        if boundary-points[-1] >= .5 and original['end']-boundary >= .5:
            points.append(boundary)
    points.append(original['end'])
    return [{**original,'start':a,'end':b} for a,b in zip(points,points[1:])]


def bass_pitch_class(samples, center):
    import numpy as np
    import librosa
    from tools.audio_verification import SR
    first=round(center*SR)-2048
    frame=np.zeros(4096)
    low,high=max(0,first),min(len(samples),first+4096)
    if high>low: frame[low-first:high-first]=samples[low:high]
    frame-=frame.mean()
    if np.sqrt(np.mean(frame*frame)) < 1e-5:
        return None
    frequency=float(librosa.yin(frame,fmin=30,fmax=300,sr=SR,frame_length=4096,hop_length=4096,center=False)[0])
    midi=69+12*np.log2(frequency/440)
    lag=round(SR/frequency)
    if not np.isfinite(midi) or abs(midi-round(midi))>.4 or not 0<lag<2048:
        return None
    left,right=frame[:-lag],frame[lag:]
    periodicity=float(np.dot(left,right)/max(1e-12,np.linalg.norm(left)*np.linalg.norm(right)))
    return int(round(midi))%12 if periodicity>=.7 else None


def review_chords(samples, notes, cross, bass=None, review_range=None, dense=False, acoustic=True):
    import numpy as np
    if samples.ndim != 1 or not np.isfinite(samples).all():
        raise ValueError("Invalid chord-review audio")
    if bass is not None and (bass.ndim!=1 or not np.isfinite(bass).all() or abs(len(bass)-len(samples))>800):
        raise ValueError('Bass is not time-aligned with harmony')
    baseline = cross.active_method if cross.active_method in cross.chords else next(iter(cross.chords),None)
    summary = {"version":3,"baseline_method":baseline,"changed_segments":0,"review_segments":0,
        "split_baseline_segments":0,"added_boundaries":0,"bass_supported_changes":0,
        "harmonic_root_changes":0,"acoustic_boundaries":0,"acoustic_supported_changes":0,
        "note_context":"harmonic_track_not_extra_vote" if cross.harmony_notes else "guitar_fallback",
        "policy":"stable_independent_internal_boundaries_two_window_audio_note_and_optional_bass_check"}
    if not baseline:
        return [],summary
    summary["baseline_digest"] = digest(cross.raw_methods[baseline])
    dictionary = {midi:template(midi) for midi in range(36,100)}
    by_start = sorted(cross.harmony_notes or notes,key=lambda note:note["start"])
    from tools.harmonic_context import HarmonicContext,components
    audit=HarmonicContext(samples,by_start,review_range,dense) if acoustic else None
    summary['acoustic_boundaries']=len(audit.boundaries) if audit else 0
    summary['acoustic_proposals_not_extra_votes']=True
    starts = [note["start"] for note in by_start]
    sources = {name:(stable_chord_runs(segments),[]) for name,(segments,_) in cross.chords.items()}
    for segments,times in sources.values(): times.extend(segment['start'] for segment in segments)
    output = []
    prepared = []
    for original in cross.chords[baseline][0]:
        clipped=[original]
        if review_range and not original.get('manual'):
            low,high=review_range
            points=sorted({original['start'],original['end'],*[t for t in (low,high) if original['start']<t<original['end']]})
            clipped=[{**original,'start':a,'end':b} for a,b in zip(points,points[1:])]
        pieces=[]
        for part in clipped:
            in_range=not review_range or part['start']>=review_range[0]-.001 and part['end']<=review_range[1]+.001
            cuts=audit.cuts(part) if audit and in_range else []
            pieces.extend(chord_pieces(part,sources,baseline,cuts) if in_range and summary['added_boundaries']<496 else [dict(part)])
        if len(pieces)>1:
            summary['split_baseline_segments']+=1
            summary['added_boundaries']+=len(pieces)-1
        prepared.extend(pieces)
    audio_checks = 0
    for original in prepared:
        segment = dict(original); output.append(segment)
        pcs = tones(original["chord"])
        span = original["end"]-original["start"]
        if original.get("manual") or not pcs or span < .4 or review_range and not (original['start']>=review_range[0]-.001 and original['end']<=review_range[1]+.001):
            continue
        candidates = {}
        for name,(segments,times) in sources.items():
            if name == baseline or name not in {'chordino','btc','chord_v2'} or name == "chord_v2" and baseline == "chordino":
                continue
            at = max(0,bisect.bisect_right(times,original["start"])-1)
            overlaps = {}
            while at < len(segments) and segments[at]["start"] < original["end"]:
                other = segments[at]
                share = max(0,min(other["end"],original["end"])-max(other["start"],original["start"]))/span
                overlaps[other["chord"]] = overlaps.get(other["chord"],0)+share
                at += 1
            for label,share in overlaps.items():
                if share >= .8 and tones(label) and identity(label) != identity(original["chord"]):
                    candidates[label] = {"chord":label,"share":round(share,3),"model":name}
        # Acoustic proposals do not count as independent model consensus. They
        # require stricter local note/audio acceptance below.
        if audit:
            proposals=audit.candidates(original['start'],original['end'])
            touching=any(original['start']-.5<t<original['end']+.5 for t,_ in audit.boundaries)
            if dense or touching:
                for proposal in proposals:
                    if identity(proposal['chord'])!=identity(original['chord']) and proposal['note_agreement']>=.75:
                        candidates.setdefault(proposal['chord'],proposal)
        if not candidates:continue
        summary["review_segments"] += 1
        centers = [original["start"]+span*.35,original["start"]+span*.65]
        observed = [spectrum(samples,center) for center in centers]
        segment["refinement"] = {"uncertain":True,"alternatives":list(candidates.values()),"source":"cross_verified"}
        if any(spec.max() < 1e-7 for spec in observed) or audio_checks >= 256:
            continue
        audio_checks += 1
        # Attack-aligned local notes; do not let full-mix harmony force a solo part.
        high = bisect.bisect_left(starts,original["end"])
        relevant = [note for note in by_start[:high] if min(original['end'],note['end'])-max(original['start'],note['start']) >= .12]
        segment['refinement']['components']=components(original['chord'],observed,relevant,original['start'],original['end'])
        if not relevant:
            continue
        def compatibility(allowed):
            weights = [min(.5,min(original['end'],note['end'])-max(original['start'],note['start'])) for note in relevant]
            return sum(weight for note,weight in zip(relevant,weights) if note["midi"]%12 in allowed)/sum(weights)
        pitches = [midi for midi in range(36,89) if midi%12 in pcs]
        before = [fit(pitches,spec,dictionary) for spec in observed]
        best,best_loss = None,sum(before)
        bass_classes=[bass_pitch_class(bass,center) for center in centers] if bass is not None else []
        best_root_source=None
        for label,candidate in candidates.items():
            proposed_pcs = tones(label)
            if proposed_pcs == pcs or compatibility(proposed_pcs) < .5 or not cross.harmony_notes and compatibility(proposed_pcs) < compatibility(pcs)-.05:
                continue
            # More chord tones give NNLS more freedom; extra complexity is not
            # evidence unless every added pitch class has a visible fundamental.
            from tools.audio_verification import FREQ
            added = proposed_pcs-pcs
            def audible(pc,spec):
                return any(spec[np.abs(FREQ-440*2**((midi-69)/12)) <= 10].max(initial=0) >= spec.max()*.08
                           for midi in range(36,77) if midi%12 == pc)
            # Arpeggios need not sound every chord tone simultaneously. All
            # added classes must appear across the two interior windows.
            if any(not any(audible(pc,spec) for spec in observed) for pc in added):
                continue
            proposed = [midi for midi in range(36,89) if midi%12 in proposed_pcs]
            after = [fit(proposed,spec,dictionary) for spec in observed]
            spectral = all(old-new > max(.035,old*.12) for old,new in zip(before,after))
            proposed_identity=identity(label)
            bass_target=proposed_identity[2] if proposed_identity[2] is not None else proposed_identity[0]
            # Harmonic templates can misread a low bass's overtones as another
            # root. A stable separated bass plus visible new chord tones and
            # harmonic-note agreement can disambiguate, never a vote by itself.
            root_classes=[]
            for index,(center,spec) in enumerate(zip(centers,observed)):
                root=bass_classes[index] if bass_classes else None
                if root is None and cross.harmony_notes:
                    low_notes=[n for n in relevant if n['start']<=center<n['end'] and n['midi']<=55 and n.get('velocity',.5)>=.25]
                    lowest=min(low_notes,key=lambda n:n['midi']) if low_notes else None
                    if lowest:
                        fundamental=440*2**((lowest['midi']-69)/12)
                        if spec[np.abs(FREQ-fundamental)<=10].max(initial=0)>=spec.max()*.15:
                            root=lowest['midi']%12
                root_classes.append(root)
            root_supported=bool(candidate['model']!='audio_context' and cross.harmony_notes and proposed_identity[0]!=identity(original['chord'])[0] and
                all(pc==bass_target for pc in root_classes) and compatibility(proposed_pcs)>=.65 and
                all(new-old<.15 for old,new in zip(before,after)))
            root_source='bass' if bass_classes and all(pc==bass_target for pc in bass_classes) else 'harmonic_notes'
            if candidate['model']=='audio_context':
                total=sum(min(.5,n['end']-n['start']) for n in relevant)
                extra_notes=all(sum(min(.5,n['end']-n['start']) for n in relevant if n['midi']%12==pc)>=total*.08 for pc in proposed_pcs)
                spectral=spectral and extra_notes and compatibility(proposed_pcs)>=.75 and all(new<.65 for new in after)
            if (spectral or root_supported) and (best is None or sum(after) < best_loss):
                best,best_loss,best_root_source = label,sum(after),root_source if root_supported and not spectral else None
        if best:
            segment["chord"] = best
            segment["refinement"].update(original_chord=original["chord"],changed=True,
                spectral_gain=round((sum(before)-best_loss)/2,4),root_support=best_root_source)
            segment['refinement']['components']=components(best,observed,relevant,original['start'],original['end'])
            summary['acoustic_supported_changes']+=int(candidates[best]['model']=='audio_context')
            summary["changed_segments"] += 1
            summary['bass_supported_changes'] += int(best_root_source=='bass')
            summary['harmonic_root_changes'] += int(best_root_source=='harmonic_notes')
    summary['audio_checks'] = audio_checks
    return output,summary
