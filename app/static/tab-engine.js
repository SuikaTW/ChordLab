/* Audio pitch events do not identify the played string. Search several possible
 * fingerings through the phrase, rather than committing greedily to each note. */
(function (root) {
  "use strict";
  const TUNINGS = {
    standard: { label: "標準 E A D G B e", midi: [40, 45, 50, 55, 59, 64] },
    drop_d: { label: "Drop D", midi: [38, 45, 50, 55, 59, 64] },
    dadgad: { label: "DADGAD", midi: [38, 45, 50, 55, 57, 62] },
    half_down: { label: "降半音", midi: [39, 44, 49, 54, 58, 63] },
    whole_down: { label: "降全音", midi: [38, 43, 48, 53, 57, 62] },
    bass_standard: { label: "四弦 E A D G", midi: [28, 33, 38, 43], instrument: "bass" },
    bass_drop_d: { label: "四弦 Drop D · D A D G", midi: [26, 33, 38, 43], instrument: "bass" },
    bass_five: { label: "五弦 B E A D G", midi: [23, 28, 33, 38, 43], instrument: "bass" },
  };

  function prepare(notes, clean) {
    const sorted = notes.map((note, index) => ({
      ...note,
      index,
      start: Number(note.start),
      end: Number(note.end),
      midi: Number(note.midi),
      velocity: Number(note.velocity ?? 1),
    })).filter((note) =>
      Number.isFinite(note.start) && note.start >= 0 &&
      Number.isFinite(note.end) && note.end - note.start >= (clean ? .035 : .02) &&
      Number.isInteger(note.midi) && note.midi >= 0 && note.midi <= 127 &&
      Number.isFinite(note.velocity) && note.velocity >= (clean ? .10 : 0)
    )
      .sort((a, b) => a.start - b.start || b.velocity - a.velocity || a.midi - b.midi);
    const prepared = [], lastByPitch = new Map();
    for (const note of sorted) {
      const pitchKey = Number.isInteger(note.model_string) ? `${note.midi}:${note.model_string}` : note.midi;
      const previous = lastByPitch.get(pitchKey);
      // Only deduplicate essentially identical onsets, never merge repeated plucks.
      if (previous && note.start - previous.start < .008) {
        previous.end = Math.max(previous.end, note.end);
        continue;
      }
      prepared.push(note);
      lastByPitch.set(pitchKey, note);
    }
    return prepared;
  }

  function spanCost(notes) {
    const frets = notes.filter((note) => note.fret > 0).map((note) => note.fret);
    if (frets.length < 2) return 0;
    const span = Math.max(...frets) - Math.min(...frets);
    return Math.max(0, span - 4) ** 2 * 1.5;
  }

  function phraseBeam(candidates, width, start) {
    const unique = new Map();
    for (const candidate of candidates.sort((a, b) => a.cost - b.cost)) {
      const key = `${candidate.position}:` + candidate.active.map((note) =>
        note && note.end > start + .025 ? `${note.midi}/${note.fret}/${Math.round(note.end * 100)}` : "-").join(",") +
        ":" + candidate.placed.map((note) => `${note.midi}/${note.string}`).join(",");
      if (!unique.has(key)) unique.set(key, candidate);
      if (unique.size === width) break;
    }
    return [...unique.values()];
  }

  function assign(notes, options = {}) {
    const clean = options.density !== "full";
    const bass = options.instrument === "bass" || !options.instrument && TUNINGS[options.tuning]?.instrument === "bass";
    const definition = TUNINGS[options.tuning];
    const tuning = (definition && (definition.instrument === "bass") === bass ? definition :
      bass ? TUNINGS.bass_standard : TUNINGS.standard).midi;
    const stringCount = tuning.length;
    const capo = bass ? 0 : Math.min(11, Math.max(0, Math.round(Number(options.capo) || 0)));
    const prepared = prepare(notes, clean), groups = [];
    for (const note of prepared) {
      const last = groups[groups.length - 1];
      if (last && note.start - last.start <= .025 && !last.notes.some((n) =>
        n.midi === note.midi && (!Number.isInteger(note.model_string) || n.model_string === note.model_string))) {
        last.notes.push(note);
      } else {
        groups.push({ start: note.start, notes: [note] });
      }
    }
    // Register selection is only a heuristic; it does not separate guitars.
    if (options.voice === "high" || options.voice === "low") {
      for (const group of groups) {
        const sorted = [...group.notes].sort((a, b) => a.midi - b.midi);
        group.notes = [options.voice === "high" ? sorted[sorted.length - 1] : sorted[0]];
      }
    }
    const range = { open: [0, 4], middle: [5, 9], high: [9, 14] }[options.position];
    const width = 24;
    let beam = [{
      cost: 0,
      position: range ? range[0] : 0,
      active: Array(stringCount).fill(null),
      parent: null,
      placed: [],
    }];
    for (const group of groups) {
      // A single instrument cannot sound more independent notes than strings.
      const pitches = [...group.notes].sort((a, b) => b.velocity - a.velocity)
        .slice(0, stringCount).sort((a, b) => a.midi - b.midi);
      let partial = beam.map((parent) => ({
        cost: parent.cost,
        position: parent.position,
        active: [...parent.active],
        parent,
        placed: [],
        used: new Set(),
      }));
      for (const note of pitches) {
        const next = [];
        for (const candidate of partial) {
          // Keep a path for unplayable pitches; do not silently block new notes
          // just because an earlier model event has an excessively long sustain.
          next.push({ ...candidate, cost: candidate.cost + 18 + Math.min(1, note.velocity) * 12 });
          for (let string = 0; string < stringCount; string++) {
            const fret = note.midi - tuning[string] - capo;
            if (fret < 0 || fret + capo > 24 || candidate.used.has(string)) continue;
            const manual = note.edited && Number.isInteger(note.string) && Number.isInteger(note.fret) &&
              note.string >= 0 && note.string < stringCount && note.fret >= 0 && note.fret + capo <= 24 &&
              tuning[note.string] + capo + note.fret === note.midi;
            if (manual && string !== note.string) continue;
            const placedNote = { ...note, string, fret };
            const placed = [...candidate.placed, placedNote];
            const old = candidate.active[string];
            const overlap = old && old.end > note.start + .025;
            const crossing = candidate.placed.filter((n) => n.midi < note.midi && n.string > string).length;
            const movement = fret > 0 ? Math.abs(fret - candidate.position) * .12 : 0;
            // Open strings need no fretting-hand shift, even at a high position.
            // Keep them in the phrase search; string occupancy and model evidence
            // can still favor a fretted equivalent when it fits the music better.
            const preference = range && fret > 0 ? Math.max(0, range[0] - fret, fret - range[1]) * 2 : 0;
            const validHint = !bass && options.useModelFingering && (!options.tuning || options.tuning === "standard") && capo === 0 &&
              Number.isInteger(note.model_string) && note.model_string >= 0 && note.model_string < 6 &&
              Number.isInteger(note.model_fret) && note.model_fret >= 0 && note.model_fret <= 19 &&
              tuning[note.model_string] + note.model_fret === note.midi;
            // A soft anchor, not a guarantee of the original performer's choice.
            const alternatives = validHint && Array.isArray(note.fingering_candidates) ?
              note.fingering_candidates.filter((item) => Number.isInteger(item.string) &&
                item.string >= 0 && item.string < 6 && Number.isInteger(item.fret) &&
                item.fret >= 0 && item.fret <= 19 && tuning[item.string] + item.fret === note.midi &&
                Number.isFinite(item.score) && item.score >= 0 && item.score <= 1) : [];
            const support = alternatives.find((item) => item.string === string)?.score || 0;
            const hintCost = alternatives.length ?
              3 * (Math.max(...alternatives.map((item) => item.score)) - support) :
              validHint && string !== note.model_string ?
                3 * Math.max(0, Math.min(1, Number(note.fingering_score) || 0)) : 0;
            // Preserve audible sustains (including open strings) when another
            // playable string exists. This is soft: bad model lengths must not
            // prevent a later pitch from appearing at all.
            const sustainCost = overlap && old.midi !== note.midi ?
              .7 + Math.min(3, Math.max(0, old.end - note.start - .05) * 3) : 0;
            const melody = candidate.parent.placed.length === 1 && pitches.length === 1 ? candidate.parent.placed[0] : null;
            const connected = melody && note.start - melody.start <= .3 && Math.abs(note.midi - melody.midi) <= 5;
            const continuity = !bass && connected ? Math.abs(string - melody.string) * .15 : 0;
            const cost = candidate.cost + fret * .025 + movement + crossing * 3 + continuity +
              preference + hintCost + spanCost(placed) - spanCost(candidate.placed) +
              sustainCost;
            const active = [...candidate.active];
            active[string] = placedNote;
            const used = new Set(candidate.used);
            used.add(string);
            next.push({ ...candidate, cost, active, placed, used });
          }
        }
        partial = next.sort((a, b) => a.cost - b.cost).slice(0, width);
      }
      beam = partial.map((candidate) => {
        const frets = candidate.placed.filter((n) => n.fret > 0).map((n) => n.fret).sort((a, b) => a - b);
        const position = frets.length ? frets[Math.floor(frets.length / 2)] : candidate.position;
        const gap = group.start - (candidate.parent.placed[0]?.start ?? group.start);
        const shiftCost = Math.abs(position - candidate.parent.position) * (gap > .8 ? .04 : .18);
        const held = candidate.active.filter((note) => note && note.end > group.start + .04);
        const sustainSpan = Math.max(0, spanCost(held) - spanCost(candidate.placed)) * .6;
        return { ...candidate, position, cost: candidate.cost + shiftCost + sustainSpan };
      });
      beam = phraseBeam(beam, width, group.start);
      // Normalize accumulated costs to keep long songs numerically stable.
      const floor = beam[0].cost;
      beam.forEach((candidate) => {
        candidate.cost -= floor;
      });
    }
    const chunks = [];
    for (let node = beam[0]; node?.parent; node = node.parent) chunks.push(node.placed);
    const assigned = chunks.reverse().flat().sort((a, b) => a.start - b.start || a.string - b.string);
    const diagnostics = {
      crowdedOnsets: groups.filter((group) => group.notes.length > stringCount).length,
      wideShapes: 0,
      rapidShifts: 0,
      sustainConflicts: 0,
    };
    let previousShape = null;
    for (const placed of chunks) {
      if (!placed.length) continue;
      const frets = placed.filter((n) => n.fret > 0).map((n) => n.fret);
      if (frets.length && Math.max(...frets) - Math.min(...frets) > 5) {
        diagnostics.wideShapes++;
        placed.forEach((note) => {
          note.suspicious = true;
        });
      }
      const position = frets.length ? frets.reduce((a, b) => a + b, 0) / frets.length : 0;
      if (
        previousShape && placed[0].start - previousShape.start < .3 &&
        Math.abs(position - previousShape.position) > 7
      ) {
        diagnostics.rapidShifts++;
        placed.forEach((note) => {
          note.suspicious = true;
        });
      }
      previousShape = { position, start: placed[0].start };
    }
    const lastByString = Array(stringCount).fill(null);
    for (const note of assigned) {
      const previous = lastByString[note.string];
      if (previous && previous.end > note.start) {
        if (previous.end > note.start + .08 && previous.midi !== note.midi) diagnostics.sustainConflicts++;
        previous.end = note.start;
      }
      lastByString[note.string] = note;
    }
    const selectedCount = groups.reduce((count, group) => count + group.notes.length, 0);
    return {
      notes: assigned,
      inputCount: notes.length,
      preparedCount: prepared.length,
      voiceFilteredCount: prepared.length - selectedCount,
      omittedCount: selectedCount - assigned.length,
      tuning: [...tuning],
      capo,
      instrument: bass ? "bass" : "guitar",
      diagnostics,
    };
  }

  root.ChordLabTab = { assign, TUNINGS };
})(globalThis);
