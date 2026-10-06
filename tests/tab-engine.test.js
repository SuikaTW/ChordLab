import "../app/static/tab-engine.js";

const { assign } = globalThis.ChordLabTab;
Deno.test("capo must not extend the physical fretboard beyond 24 frets", () => {
  const invalid = assign([note(99)], { capo: 11 });
  assert(invalid.notes.length === 0, "Capo does not create additional frets");
  const top = assign([note(88)], { capo: 11 });
  assert(top.notes.length === 1 && top.notes[0].fret === 13, "24th physical fret remains playable");
  playable(top);
});
Deno.test("register filters are explicit and position preference preserves pitch", () => {
  const source = [note(52), note(64), note(67), note(55, .5), note(69, .5)];
  const high = assign(source, { voice: "high" }), low = assign(source, { voice: "low" });
  assert(high.notes.map((n) => n.midi).join(",") === "67,69", "Keep highest onset notes");
  assert(low.notes.map((n) => n.midi).join(",") === "52,55", "Keep lowest onset notes");
  assert(
    high.voiceFilteredCount === 3 && high.omittedCount === 0,
    "Separate filter count from unplayable count",
  );
  const preferred = assign([note(64)], { position: "middle" });
  assert(preferred.notes[0].fret >= 5 && preferred.notes[0].fret <= 9, "Prefer requested position");
  playable(preferred);
  playable(high);
  playable(low);
  const necessary = assign([note(40)], { position: "high" });
  assert(
    necessary.notes.length === 1 && necessary.notes[0].fret === 0,
    "Preference must not drop necessary notes",
  );
});
function assert(value, message) {
  if (!value) throw new Error(message);
}
function note(midi, start = 0, length = .09, velocity = .4) {
  return { midi, start, end: start + length, velocity };
}
function playable(result) {
  for (const n of result.notes) {
    assert(n.midi === result.tuning[n.string] + result.capo + n.fret, "Pitch must match tuning/capo/fret");
    assert(n.fret >= 0 && n.fret <= 24, "Fret out of range");
    assert(n.fret + result.capo <= 24, "Absolute fret exceeds physical fretboard");
    assert(n.end > n.start, "Note must have positive duration");
  }
  for (let string = 0; string < 6; string++) {
    const notes = result.notes.filter((n) => n.string === string);
    for (let i = 1; i < notes.length; i++) {
      assert(notes[i - 1].end <= notes[i].start, "Overlapping notes on one string");
    }
  }
}

Deno.test("quiet, short repeated plucks are preserved, including retriggered sustains", () => {
  const source = Array.from({ length: 12 }, (_, i) => note(40, i * .075, .16, .35));
  const result = assign(source);
  assert(result.notes.length === source.length, "Repeated low E notes must not merge or disappear");
  assert(result.notes.every((n) => n.string === 0 && n.fret === 0), "Low E must use its open string");
  playable(result);
});

Deno.test("a six-note E chord uses six distinct strings and a playable hand span", () => {
  const result = assign([40, 47, 52, 56, 59, 64].map((midi) => note(midi, 0, 1, .65)));
  assert(result.notes.length === 6, "Complete chord must be retained");
  assert(new Set(result.notes.map((n) => n.string)).size === 6, "One note per string");
  const frets = result.notes.filter((n) => n.fret > 0).map((n) => n.fret);
  assert(Math.max(...frets) - Math.min(...frets) <= 4, "Chord must not require a huge hand span");
  playable(result);
});

Deno.test("Drop D and capo change fret mapping without changing the sound", () => {
  const standard = assign([note(38)]);
  assert(standard.notes.length === 0 && standard.omittedCount === 1, "D2 cannot sound in standard tuning");
  const dropD = assign([note(38)], { tuning: "drop_d" });
  assert(dropD.notes[0].string === 0 && dropD.notes[0].fret === 0, "D2 must be open Drop D");
  const capo = assign([note(40)], { tuning: "drop_d", capo: 2 });
  assert(capo.notes[0].fret === 0, "Drop D capo 2 sounds E2 on its open string");
  playable(capo);
});

Deno.test("unsupported noise cannot displace all real chord notes", () => {
  const chord = [40, 47, 52, 56, 59, 64].map((midi) => note(midi, 0, 1, .7));
  const result = assign([...chord, note(100, 0, .1, .15)]);
  assert(result.notes.length === 6 && result.omittedCount === 1, "Retain stronger playable chord");
  playable(result);
});

Deno.test("overlapping consecutive pitches may reuse a string instead of disappearing", () => {
  const result = assign([note(40, 0, 1), note(41, .12, 1), note(42, .24, .4)]);
  assert(result.notes.length === 3, "Long estimated sustains must not block later low notes");
  playable(result);
});

Deno.test("invalid events and true duplicate onsets are removed without mutating input", () => {
  const input = [note(60), note(60, .002, .12), note(61, 1, .05, .05), {
    midi: 62,
    start: NaN,
    end: 2,
    velocity: .5,
  }];
  const original = JSON.stringify(input);
  const clean = assign(input), full = assign(input, { density: "full" });
  assert(clean.notes.length === 1 && full.notes.length === 2, "Full mode should preserve weak events");
  assert(JSON.stringify(input) === original, "Do not mutate source events");
  playable(full);
});

Deno.test("a long polyphonic phrase remains playable with stable ordering", () => {
  const source = Array.from({ length: 160 }, (_, i) =>
    [48, 52, 55, 60, 64]
      .map((midi) => note(midi, i * .25, .3, .6))).flat();
  const result = assign(source);
  assert(result.notes.length === source.length, "Do not drop playable chords in long phrases");
  playable(result);
});
