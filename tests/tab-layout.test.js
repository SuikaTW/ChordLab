import "../app/static/tab-layout.js";
const { bars, rows, flowRows, rests, locate } = globalThis.ChordLabLayout;
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
Deno.test('responsive score groups sparse bars without changing their boundaries', () => {
  const measures = bars(16, {bpm:120, manual:true});
  const phone = flowRows(measures, [], 310), desktop = flowRows(measures, [], 900);
  assert(phone.every(row => row.measures.length === 2), 'Two sparse bars fit a phone');
  assert(desktop.every(row => row.measures.length === 4), 'Four sparse bars fit a wide score');
  assert(flowRows(measures, [], 240).every(row => row.measures.length === 1), 'Narrow viewport remains readable');
  assert(desktop[0].start === measures[0].start && desktop.at(-1).end === measures.at(-1).end, 'Keep full coverage');
});
Deno.test('dense measures stay alone and repeated chord onsets do not inflate width', () => {
  const measures = bars(8, {bpm:120, manual:true});
  const dense = Array.from({length:12}, (_,i) => ({start:i*.15,end:i*.15+.1,string:0,midi:40}));
  const snapshot = JSON.stringify(dense), result = flowRows(measures, dense, 310);
  assert(result[0].measures.length === 1, 'Do not squeeze twelve onsets beside another bar');
  assert(JSON.stringify(dense) === snapshot, 'Never mutate notes');
  const chords = Array.from({length:6}, (_,string) => ({start:.1,end:1,string,midi:40+string}));
  assert(flowRows(measures,chords,310)[0].measures.length === 2, 'Polyphonic onset fits one column');
});
Deno.test('responsive layout handles intro, uneven detected beats and empty input', () => {
  const measures = bars(10,{bpm:120,meter:4,offset:1,manual:true});
  const result = flowRows(measures,[],320);
  assert(result[0].start === 0 && result.at(-1).end === 10, 'Keep pickup and ending');
  assert(result.flatMap(row => row.measures).every((bar,i) => bar === measures[i]), 'Keep exact measure objects/order');
  assert(flowRows([],[],0).length === 0, 'No phantom measures');
  assert(flowRows(measures,[],NaN).every(row => row.measures.length === 1), 'Safe width fallback');
});
