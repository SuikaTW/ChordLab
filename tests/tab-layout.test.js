import "../app/static/tab-layout.js";
const { bars, rows, rests, locate } = globalThis.ChordLabLayout;
const assert = (value, message) => {
  if (!value) throw new Error(message);
};
Deno.test("manual bar layout covers intro and ending without moving notes", () => {
  const measures = bars(10, { bpm: 120, meter: 4, offset: 1, manual: true });
  assert(measures[0].start === 0 && measures[0].end === 1, "Keep intro");
  assert(measures[1].start === 1 && measures[1].end === 3, "Four beats per bar");
  assert(measures.at(-1).end === 10, "Cover last partial bar");
  const systems = rows(measures, 2);
  assert(locate(systems, 3.01) === 1, "Find correct row in logarithmic lookup");
});
Deno.test("detected irregular beats are retained with explicit assumed meter", () => {
  const detected = { bpm: 120, beats: [0, .51, 1.03, 1.56, 2.1, 2.61, 3.15, 3.68, 4.2] };
  const measures = bars(5, { meter: 4 }, detected);
  assert(measures[0].end === 2.1, "Follow detected timing, not fixed seconds");
  assert(measures[1].start === 2.1, "Adjacent bar boundaries");
  assert(measures.at(-1).end === 5, "Include song ending");
});
Deno.test("rests respect overlapping voices and sustained notes", () => {
  const gaps = rests([{ start: 0, end: 1 }, { start: .5, end: 2 }, { start: 3, end: 4 }], 0, 5, .25);
  assert(
    JSON.stringify(gaps) === '[{"start":2,"end":3},{"start":4,"end":5}]',
    "Merge sounding intervals before finding rests",
  );
});
Deno.test("empty or silent rhythm has a bounded usable fallback", () => {
  const measures = bars(1200, {}, { bpm: null, beats: [] });
  assert(measures.length === 600, "Bound rows for maximum duration");
  assert(bars(0).length === 1, "Empty audio must not break layout");
});
