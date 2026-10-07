"""Independent model families and soft harmony constraints, never majority truth."""
import bisect
import math
import hashlib
import json
from app.chord_comparison import identity, valid_segments
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


def review_chords(samples, notes, cross):
    import numpy as np
    if samples.ndim != 1 or not np.isfinite(samples).all():
        raise ValueError("Invalid chord-review audio")
    baseline = cross.active_method if cross.active_method in cross.chords else next(iter(cross.chords),None)
    summary = {"baseline_method":baseline,"changed_segments":0,"review_segments":0,"policy":"independent_candidate_two_window_audio_and_note_check"}
    if not baseline:
        return [],summary
    summary["baseline_digest"] = digest(cross.raw_methods[baseline])
    dictionary = {midi:template(midi) for midi in range(36,100)}
    by_start = sorted(notes,key=lambda note:note["start"])
    starts = [note["start"] for note in by_start]
    output = []
    for original in cross.chords[baseline][0]:
        segment = dict(original); output.append(segment)
        pcs = tones(original["chord"])
        span = original["end"]-original["start"]
        if original.get("manual") or not pcs or span < .4:
            continue
        candidates = {}
        for name,(segments,times) in cross.chords.items():
            if name == baseline or name == "chord_v2" and baseline == "chordino":
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
        if not candidates:
            continue
        summary["review_segments"] += 1
        centers = [original["start"]+span*.35,original["start"]+span*.65]
        observed = [spectrum(samples,center) for center in centers]
        segment["refinement"] = {"uncertain":True,"alternatives":list(candidates.values()),"source":"cross_verified"}
        if any(spec.max() < 1e-7 for spec in observed):
            continue
        # Attack-aligned local notes; do not let full-mix harmony force a solo part.
        low,high = bisect.bisect_left(starts,original["start"]),bisect.bisect_left(starts,original["end"])
        relevant = [note for note in by_start[low:high] if note["end"]-note["start"] >= .12]
        if not relevant:
            continue
        def compatibility(allowed):
            weights = [min(.5,note["end"]-note["start"]) for note in relevant]
            return sum(weight for note,weight in zip(relevant,weights) if note["midi"]%12 in allowed)/sum(weights)
        pitches = [midi for midi in range(36,89) if midi%12 in pcs]
        before = [fit(pitches,spec,dictionary) for spec in observed]
        best,best_loss = None,sum(before)
        for label,candidate in candidates.items():
            proposed_pcs = tones(label)
            if proposed_pcs == pcs or compatibility(proposed_pcs) < max(.5,compatibility(pcs)-.05):
                continue
            # More chord tones give NNLS more freedom; extra complexity is not
            # evidence unless every added pitch class has a visible fundamental.
            from tools.audio_verification import FREQ
            added = proposed_pcs-pcs
            def audible(pc,spec):
                return any(spec[np.abs(FREQ-440*2**((midi-69)/12)) <= 10].max(initial=0) >= spec.max()*.08
                           for midi in range(36,77) if midi%12 == pc)
            if any(not all(audible(pc,spec) for spec in observed) for pc in added):
                continue
            proposed = [midi for midi in range(36,89) if midi%12 in proposed_pcs]
            after = [fit(proposed,spec,dictionary) for spec in observed]
            if all(old-new > max(.035,old*.12) for old,new in zip(before,after)) and sum(after) < best_loss:
                best,best_loss = label,sum(after)
        if best:
            segment["chord"] = best
            segment["refinement"].update(original_chord=original["chord"],changed=True,
                spectral_gain=round((sum(before)-best_loss)/2,4))
            summary["changed_segments"] += 1
    return output,summary
