"""Validate local worker proposals independently before publishing or applying."""
import math
from app.chord_comparison import valid_segments


def merge_local(original,refined,start,end):
    """Restore exact outside/manual metadata, including approved tail margins."""
    merged=[]
    for segment in original:
        if segment.get('manual'):
            merged.append(dict(segment));continue
        for left,right in ((segment['start'],min(start,segment['end'])),(max(end,segment['start']),segment['end'])):
            if left<right:merged.append({**segment,'start':left,'end':right})
    merged.extend(dict(s) for s in refined if not s.get('manual') and start-1e-7<=s['start']<s['end']<=end+1e-7)
    return sorted(merged,key=lambda s:s['start'])


def validate_proposal(proposal,baseline,start,end,duration):
    if not isinstance(proposal,list) or not 1<=len(proposal)<=len(baseline)+514:
        raise ValueError('Invalid local proposal count')
    for segment in proposal:
        if not isinstance(segment,dict) or not isinstance(segment.get('chord'),str) or not 1<=len(segment['chord'])<=24:
            raise ValueError('Invalid local chord label')
        for key in ('start','end'):
            value=segment.get(key)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
                raise ValueError('Invalid local chord time')
        if not 0<=segment['start']<segment['end']<=duration+.25:
            raise ValueError('Local chord outside recording')
    cleaned=valid_segments(proposal,duration+.25)
    original=valid_segments(baseline,duration+.25)
    if len(cleaned)!=len(proposal):raise ValueError('Invalid local chord segments')
    def coverage(segments):
        intervals=[]
        for segment in segments:
            if intervals and abs(intervals[-1][1]-segment['start'])<=1e-7:
                intervals[-1][1]=segment['end']
            else:intervals.append([segment['start'],segment['end']])
        return intervals
    def outside(segments):
        pieces=[]
        for segment in segments:
            for left,right in ((segment['start'],min(start,segment['end'])),(max(end,segment['start']),segment['end'])):
                if left<right:pieces.append({**segment,'start':left,'end':right})
        return pieces
    if coverage(cleaned)!=coverage(original):raise ValueError('Local proposal changed source coverage')
    if outside(cleaned)!=outside(original):raise ValueError('Local proposal changed outside selected range')
    if [s for s in cleaned if s.get('manual')]!=[s for s in original if s.get('manual')]:
        raise ValueError('Local proposal changed manual segments')
    return cleaned
