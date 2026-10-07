import "../app/static/chord-theory.js";
import "../app/static/chord-voicings.js";
const { positions, diagram, caption } = globalThis.ChordLabVoicings;
const tuning = [40,45,50,55,59,64];
function assert(value, message) { if (!value) throw new Error(message); }
Deno.test("familiar open and barre shapes are first, with distinct alternate positions", () => {
  const shapes = { C: [-1,3,2,0,1,0], Am: [-1,0,2,2,1,0], G: [3,2,0,0,0,3],
    D: [-1,-1,0,2,3,2], F: [1,3,3,2,1,1], Bm: [-1,2,4,4,3,2], "C/E": [0,3,2,0,1,0] };
  for (const [label, shape] of Object.entries(shapes)) {
    const options = positions(label);
    assert(JSON.stringify(options[0].shape) === JSON.stringify(shape), `${label}: common shape first`);
    assert(options.length > 1 && options.length <= 6, `${label}: bounded alternatives`);
    assert(new Set(options.map(caption)).size === options.length, `${label}: distinct positions`);
  }
});
Deno.test("all supported qualities preserve chord tones, actual bass and playable bounds", () => {
  const qualities = ["", "m", "6", "m6", "7", "maj7", "m7", "mMaj7", "dim", "dim7", "m7b5", "aug", "sus2", "sus4", "9", "maj9", "m9", "add9"];
  for (const root of ["C","Db","D","Eb","E","F","F#","G","Ab","A","Bb","B"]) {
    for (const quality of qualities) {
      const label = root + quality, parsed = ChordLabTheory.parseChord(label), options = positions(label);
      assert(options.length > 0, `${label}: at least one complete voicing`);
      for (const option of options) {
        const pitches = option.shape.flatMap((fret,i) => fret < 0 ? [] : [tuning[i]+fret]);
        assert(Math.min(...pitches)%12 === parsed.root, `${label}: root bass`);
        assert(parsed.tones.every(tone => pitches.some(pitch => pitch%12 === tone)), `${label}: all tones`);
        assert(pitches.every(pitch => parsed.tones.includes(pitch%12)), `${label}: no extra tones`);
        assert(option.high-option.low <= 3 && option.high <= 15, `${label}: fret span`);
        assert(option.shape.every(fret => fret <= 0 || (fret >= option.start && fret < option.start+5)), `${label}: visible frets`);
        let fingers = option.shape.filter(fret => fret > 0).length;
        if (option.barre) {
          const { fret, from, to } = option.barre;
          assert(option.shape.slice(from,to+1).every(value => value >= fret), `${label}: barre cannot mute open/lower strings`);
          fingers -= option.shape.slice(from,to+1).filter(value => value === fret).length - 1;
        }
        assert(fingers <= 4, `${label}: at most four fretting fingers including barre`);
      }
    }
  }
});
Deno.test("slash bass, aliases, no-chord and hostile labels", () => {
  for (const label of ["C/E","D/F#","C/D","G/B","Am/C"]) {
    const parsed = ChordLabTheory.parseChord(label), options = positions(label);
    assert(options.length, `${label}: inversion available`);
    for (const option of options) {
      const pitches = option.shape.flatMap((fret,i) => fret < 0 ? [] : [tuning[i]+fret]);
      assert(Math.min(...pitches)%12 === parsed.bass, `${label}: actual bass`);
    }
  }
  assert(JSON.stringify(positions("Db:min7")) === JSON.stringify(positions("C#m7")), "enharmonic alias");
  for (const label of [null, "N", "X", "Cunknown", "<script>"]) assert(positions(label).length === 0, "unsupported safe");
});
Deno.test("conventional diagrams show six strings, X/O, fret numbers, nut and higher-position barres", () => {
  const open = diagram(positions("C")[0]);
  assert((open.match(/class="chord-string"/g)||[]).length === 6, "six vertical strings");
  assert(open.includes("chord-nut") && open.includes("○") && open.includes("×"), "nut and open/muted markers");
  assert(open.includes("6 弦不彈") && open.includes("5 弦第 3 格"), "accessible string/fret description");
  const higher = positions("C").find(option => option.low === 8), svg = diagram(higher);
  assert(!svg.includes("chord-nut") && svg.includes("chord-barre"), "high position has no false nut");
  assert(svg.includes('y="82">8</text>'), "offset fret number");
});
