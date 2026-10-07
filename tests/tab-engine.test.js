import "../app/static/tab-engine.js";

const { assign } = globalThis.ChordLabTab;
Deno.test("bass four/five strings and Drop D use actual low pitches without guitar capo", () => {
  const four = assign([note(28), note(33), note(38), note(43)], { instrument: "bass", tuning: "bass_standard", capo: 7 });
  assert(four.tuning.join(",") === "28,33,38,43" && four.capo === 0, "Bass is octave-correct and independent of guitar capo");
  assert(four.notes.length === 4 && four.notes.every((n) => n.fret === 0), "Four open strings");
  playable(four);
  const low = assign([note(23)], { instrument: "bass", tuning: "bass_five" });
  assert(low.tuning.length === 5 && low.notes[0].string === 0 && low.notes[0].fret === 0, "Five-string low B");
  assert(assign([note(23)], { instrument: "bass", tuning: "bass_standard" }).notes.length === 0, "Do not fake low B on a four-string E bass");
  const drop = assign([note(26)], { instrument: "bass", tuning: "bass_drop_d" });
  assert(drop.notes[0].string === 0 && drop.notes[0].fret === 0, "Bass Drop D");
  playable(low);
  playable(drop);
});
Deno.test("bass retains repeated plucks and does not use guitar model anchors", () => {
  const repeated = Array.from({ length: 16 }, (_, i) => note(28, i * .08, .18, .5));
  const result = assign(repeated, { instrument: "bass" });
  assert(result.notes.length === repeated.length, "Retain separate repeated attacks");
  assert(result.notes.every((n) => n.string >= 0 && n.string < 4), "Only actual bass strings");
  playable(result);
  const source = [{ ...note(43), model_string: 1, model_fret: 10, fingering_score: 1 }];
  const hinted = assign(source, { instrument: "bass", useModelFingering: true });
  const plain = assign(source, { instrument: "bass" });
  assert(hinted.notes[0].string === plain.notes[0].string, "Guitar hints cannot anchor bass");
});
Deno.test("hybrid alternatives remain soft and reject impossible pitch hints", () => {
  const source = [{ ...note(64), model_string: 3, model_fret: 9, fingering_score: .9,
    fingering_candidates: [{ string: 3, fret: 9, score: .9 }, { string: 5, fret: 0, score: .88 },
      { string: 0, fret: 0, score: 1 }] }];
  const result = assign(source, { useModelFingering: true });
  assert(result.notes[0].string === 5, "Nearly equal evidence permits an easier position");
  playable(result);
});
Deno.test("model string anchors are soft, pitch-checked and tuning/capo aware", () => {
  const source = [{ ...note(64), model_string: 3, model_fret: 9, fingering_score: .99 }];
  assert(assign(source, { useModelFingering: true }).notes[0].string === 3, "Use valid string evidence");
  assert(assign(source, { useModelFingering: false }).notes[0].string === 5, "Playable mode remains independent");
  const invalid = [{ ...source[0], model_fret: 8 }];
  assert(assign(invalid, { useModelFingering: true }).notes[0].string === 5, "Do not apply inconsistent hints");
  const capo = assign(source, { useModelFingering: true, capo: 1 });
  const plain = assign(source, { capo: 1 });
  assert(capo.notes[0].string === plain.notes[0].string, "Ignore fixed-standard model hints under capo");
  const drop = assign(source, { useModelFingering: true, tuning: "drop_d" });
  assert(drop.notes[0].string === assign(source, { tuning: "drop_d" }).notes[0].string, "Ignore hints under alternate tuning");
  playable(capo);
  playable(drop);
});
Deno.test("unisons on two model strings survive deduplication and grouping", () => {
  const result = assign([
    { ...note(64), model_string: 4, model_fret: 5, fingering_score: .99 },
    { ...note(64), model_string: 5, model_fret: 0, fingering_score: .99 },
  ], { useModelFingering: true });
  assert(result.notes.length === 2, "Two strings can play the same pitch");
  assert(new Set(result.notes.map((n) => n.string)).size === 2, "Unison needs distinct strings");
  playable(result);
});
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
  const preferred = assign([note(65)], { position: "middle" });
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
Deno.test("position preference keeps playable open strings in every hand position", () => {
  for (const position of ["auto", "open", "middle", "high"]) {
    for (const midi of [40, 45, 50, 55, 59, 64]) {
      const result = assign([note(midi)], { position });
      assert(result.notes.length === 1 && result.notes[0].fret === 0,
        `${position} must not penalize the open string for pitch ${midi}`);
      playable(result);
    }
    const phrase = assign([note(73, 0), note(64, .2), note(73, .4)], { position });
    assert(phrase.notes.length === 3 && phrase.notes[1].fret === 0, "Open string does not move the fretting hand");
    playable(phrase);
  }
});
Deno.test("open-string exemption follows tuning and capo and retains chord string constraints", () => {
  for (const options of [
    { tuning: "drop_d", capo: 2 }, { tuning: "dadgad", capo: 3 },
    { tuning: "half_down", capo: 1 }, { tuning: "whole_down", capo: 2 },
    { instrument: "bass", tuning: "bass_standard" },
    { instrument: "bass", tuning: "bass_five" },
    { instrument: "bass", tuning: "bass_drop_d" },
  ]) {
    const tuning = globalThis.ChordLabTab.TUNINGS[options.tuning].midi;
    const pitches = tuning.map((midi) => midi + (options.capo || 0));
    const result = assign(pitches.map((midi) => note(midi, 0, .5)), { ...options, position: "high" });
    assert(result.notes.length === pitches.length && result.notes.every((n) => n.fret === 0), "Actual open chord remains playable");
    assert(new Set(result.notes.map((n) => n.string)).size === pitches.length, "Never reuse a string within a chord");
    playable(result);
  }
  const hinted = assign([{ ...note(64), model_string: 3, model_fret: 9, fingering_score: .99 }],
    { position: "high", useModelFingering: true });
  assert(hinted.notes[0].string === 3, "Keep strong model evidence soft but meaningful");
  const chord = assign([64, 65].map((midi) => note(midi, 0, .5)), { position: "high" });
  assert(chord.notes.length === 2 && new Set(chord.notes.map((n) => n.string)).size === 2, "An open-string option cannot overwrite another chord tone");
  playable(chord);
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

Deno.test("phrase allocation preserves an open sustain when another string is playable", () => {
  const source = [note(64, 0, 1.5), note(65, .2, .18), note(67, .4, .4)];
  const snapshot = JSON.stringify(source);
  const result = assign(source);
  assert(result.notes.length === 3, "All pitches retained");
  assert(result.notes[0].fret === 0 && result.notes[0].end === 1.5, "Do not silence the open E unnecessarily");
  assert(result.notes.slice(1).every(n => n.string !== result.notes[0].string), "Melody uses a different string");
  assert(result.diagnostics.sustainConflicts === 0, "No unnecessary truncation");
  assert(JSON.stringify(source) === snapshot, "Source timing remains untouched");
  playable(result);
});

Deno.test("valid manual fingerings survive phrase optimization without imposing invalid tuning hints", () => {
  const source = [{ ...note(64), edited: true, string: 3, fret: 9 }, note(65, .3, .2)];
  const result = assign(source);
  assert(result.notes[0].string === 3 && result.notes[0].fret === 9, "Preserve a valid user's choice");
  const changed = assign(source, { capo: 2 });
  assert(changed.notes.length === 2, "Invalid old tuning/capo hint must not hide a pitch");
  playable(result); playable(changed);
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
