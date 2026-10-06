/* Audio pitch events do not identify the played string. Search several possible
 * fingerings through the phrase, rather than committing greedily to each note. */
(function (root) {
  'use strict';
  const TUNINGS = {
    standard: {label: '標準 E A D G B e', midi: [40, 45, 50, 55, 59, 64]},
    drop_d: {label: 'Drop D', midi: [38, 45, 50, 55, 59, 64]},
    dadgad: {label: 'DADGAD', midi: [38, 45, 50, 55, 57, 62]},
    half_down: {label: '降半音', midi: [39, 44, 49, 54, 58, 63]},
    whole_down: {label: '降全音', midi: [38, 43, 48, 53, 57, 62]},
  };

  function prepare(notes, clean) {
    const sorted = notes.map((note, index) => ({
      ...note, index, start: Number(note.start), end: Number(note.end),
      midi: Number(note.midi), velocity: Number(note.velocity ?? 1),
    })).filter(note => Number.isFinite(note.start) && note.start >= 0 &&
      Number.isFinite(note.end) && note.end - note.start >= (clean ? .035 : .02) &&
      Number.isInteger(note.midi) && note.midi >= 0 && note.midi <= 127 &&
      Number.isFinite(note.velocity) && note.velocity >= (clean ? .10 : 0))
      .sort((a, b) => a.start - b.start || b.velocity - a.velocity || a.midi - b.midi);
    const prepared = [], lastByPitch = new Map();
    for (const note of sorted) {
      const previous = lastByPitch.get(note.midi);
      // Only deduplicate essentially identical onsets, never merge repeated plucks.
      if (previous && note.start - previous.start < .008) {
        previous.end = Math.max(previous.end, note.end);
        continue;
      }
      prepared.push(note);
      lastByPitch.set(note.midi, note);
    }
    return prepared;
  }

  function spanCost(notes) {
    const frets = notes.filter(note => note.fret > 0).map(note => note.fret);
    if (frets.length < 2) return 0;
    const span = Math.max(...frets) - Math.min(...frets);
    return Math.max(0, span - 4) ** 2 * 1.5;
  }

  function assign(notes, options = {}) {
    const clean = options.density !== 'full';
    const tuning = (TUNINGS[options.tuning] || TUNINGS.standard).midi;
    const capo = Math.min(11, Math.max(0, Math.round(Number(options.capo) || 0)));
    const prepared = prepare(notes, clean), groups = [];
    for (const note of prepared) {
      const last = groups[groups.length - 1];
      if (last && note.start - last.start <= .025 && !last.notes.some(n => n.midi === note.midi)) {
        last.notes.push(note);
      } else {
        groups.push({start: note.start, notes: [note]});
      }
    }
    const width = 24;
    let beam = [{cost: 0, position: 0, active: Array(6).fill(null), parent: null, placed: []}];
    for (const group of groups) {
      // A single guitar has at most six independently sounding strings.
      const pitches = [...group.notes].sort((a, b) => b.velocity - a.velocity)
        .slice(0, 6).sort((a, b) => a.midi - b.midi);
      let partial = beam.map(parent => ({
        cost: parent.cost, position: parent.position, active: [...parent.active],
        parent, placed: [], used: new Set(),
      }));
      for (const note of pitches) {
        const next = [];
        for (const candidate of partial) {
          // Keep a path for unplayable pitches; do not silently block new notes
          // just because an earlier model event has an excessively long sustain.
          next.push({...candidate, cost: candidate.cost + 18 + Math.min(1, note.velocity) * 12});
          for (let string = 0; string < 6; string++) {
            const fret = note.midi - tuning[string] - capo;
            if (fret < 0 || fret > 24 || candidate.used.has(string)) continue;
            const placedNote = {...note, string, fret};
            const placed = [...candidate.placed, placedNote];
            const old = candidate.active[string];
            const overlap = old && old.end > note.start + .025;
            const crossing = candidate.placed.filter(n => n.midi < note.midi && n.string > string).length;
            const movement = fret > 0 ? Math.abs(fret - candidate.position) * .12 : 0;
            const cost = candidate.cost + fret * .025 + movement + crossing * 3 +
              spanCost(placed) - spanCost(candidate.placed) +
              (overlap && old.midi !== note.midi ? .7 : 0);
            const active = [...candidate.active]; active[string] = placedNote;
            const used = new Set(candidate.used); used.add(string);
            next.push({...candidate, cost, active, placed, used});
          }
        }
        partial = next.sort((a, b) => a.cost - b.cost).slice(0, width);
      }
      beam = partial.map(candidate => {
        const frets = candidate.placed.filter(n => n.fret > 0).map(n => n.fret).sort((a, b) => a - b);
        const position = frets.length ? frets[Math.floor(frets.length / 2)] : candidate.position;
        const gap = group.start - (candidate.parent.placed[0]?.start ?? group.start);
        const shiftCost = Math.abs(position - candidate.parent.position) * (gap > .8 ? .04 : .18);
        return {...candidate, position, cost: candidate.cost + shiftCost};
      }).sort((a, b) => a.cost - b.cost).slice(0, width);
      // Normalize accumulated costs to keep long songs numerically stable.
      const floor = beam[0].cost;
      beam.forEach(candidate => { candidate.cost -= floor; });
    }
    const chunks = [];
    for (let node = beam[0]; node?.parent; node = node.parent) chunks.push(node.placed);
    const assigned = chunks.reverse().flat().sort((a, b) => a.start - b.start || a.string - b.string);
    const lastByString = Array(6).fill(null);
    for (const note of assigned) {
      const previous = lastByString[note.string];
      if (previous && previous.end > note.start) previous.end = note.start;
      lastByString[note.string] = note;
    }
    return {notes: assigned, inputCount: notes.length, preparedCount: prepared.length,
      omittedCount: prepared.length - assigned.length, tuning: [...tuning], capo};
  }

  root.ChordLabTab = {assign, TUNINGS};
})(globalThis);
