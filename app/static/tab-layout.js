/* Rhythm layout is independent of fingering. Never silently quantize audio notes. */
(function (root) {
  "use strict";
  function locate(items, time, key = "start") {
    let low = 0, high = items.length;
    while (low < high) {
      const mid = (low + high) >> 1;
      if (items[mid][key] <= time) low = mid + 1;
      else high = mid;
    }
    return low - 1;
  }
  function bars(duration, rhythm = {}, detected = {}) {
    duration = Math.max(.01, Number(duration) || .01);
    const bpm = Math.min(300, Math.max(30, Number(rhythm.bpm) || Number(detected.bpm) || 120));
    const meter = [3, 4, 6].includes(Number(rhythm.meter)) ? Number(rhythm.meter) : 4;
    const offset = Math.min(duration, Math.max(0, Number(rhythm.offset) || 0)), period = 60 / bpm;
    let beats = !rhythm.manual && Array.isArray(detected.beats)
      ? detected.beats.filter((t) => Number.isFinite(t) && t >= 0 && t < duration)
      : [];
    if (beats.length >= 4) {
      beats = [...new Set(beats)].sort((a, b) => a - b);
      // Extrapolate boundaries to include introductions and the ending.
      while (beats[0] > period) beats.unshift(Math.max(0, beats[0] - period));
      while (beats[beats.length - 1] < duration) beats.push(beats[beats.length - 1] + period);
    } else {
      beats = [];
      for (let t = offset; t <= duration + period; t += period) beats.push(t);
    }
    const result = [];
    if (beats[0] > 0) result.push({ start: 0, end: Math.min(duration, beats[0]), beats: [0], number: 0 });
    for (let i = 0; i < beats.length - 1; i += meter) {
      const start = beats[i], end = Math.min(duration, beats[i + meter] ?? start + meter * period);
      if (start >= duration) break;
      if (end > start) {
        result.push({
          start,
          end,
          beats: beats.slice(i, i + meter).filter((t) => t < end),
          number: Math.floor(i / meter) + 1,
        });
      }
    }
    return result.length ? result : [{ start: 0, end: duration, beats: [0], number: 1 }];
  }
  function rows(measures, perRow) {
    const result = [];
    for (let i = 0; i < measures.length; i += perRow) {
      const slice = measures.slice(i, i + perRow);
      result.push({ start: slice[0].start, end: slice[slice.length - 1].end, measures: slice, notes: [] });
    }
    return result;
  }
  // Layout only: group adjacent measures using available width and onset density.
  // A dense measure stays alone; never quantize, merge or drop audio events.
  function flowRows(measures, notes, width) {
    width = Math.max(100, Number(width) || 100);
    const maxBars = width >= 680 ? 4 : 2;
    const counts = measures.map(() => new Map());
    for (const note of notes) {
      if (!Number.isFinite(note.start)) continue;
      const index = locate(measures, note.start);
      if (index < 0 || note.start >= measures[index].end) continue;
      const strings = counts[index], key = note.string ?? note.midi;
      if (!strings.has(key)) strings.set(key, new Set());
      strings.get(key).add(Math.round(note.start * 1000));
    }
    const weights = counts.map(strings => Math.max(140, 24 + 22 * Math.max(0, ...[...strings.values()].map(onsets => onsets.size))));
    const result = [];
    let slice = [], used = 0;
    function flush() {
      if (!slice.length) return;
      result.push({start:slice[0].start, end:slice.at(-1).end, measures:slice, notes:[]});
      slice = []; used = 0;
    }
    measures.forEach((bar, index) => {
      if (slice.length && (slice.length >= maxBars || used + weights[index] > width)) flush();
      slice.push(bar); used += weights[index];
    });
    flush();
    return result;
  }
  function rests(notes, start, end, minGap) {
    const spans = notes.filter((n) => n.end > start && n.start < end).sort((a, b) => a.start - b.start);
    const result = [];
    let cursor = start;
    for (const note of spans) {
      const left = Math.max(start, note.start);
      if (left - cursor >= minGap) result.push({ start: cursor, end: left });
      cursor = Math.max(cursor, Math.min(end, note.end));
    }
    if (end - cursor >= minGap) result.push({ start: cursor, end });
    return result;
  }
  root.ChordLabLayout = { locate, bars, rows, flowRows, rests };
})(globalThis);
