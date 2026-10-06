import "../app/static/chord-theory.js";
const parse = globalThis.ChordLabTheory.parseChord;
function assert(value, message) { if (!value) throw new Error(message); }
Deno.test("all BTC 170-class qualities have correct pitch classes", () => {
  const cases = {
    Cm: [0,3,7], C: [0,4,7], Cdim: [0,3,6], Caug: [0,4,8], Cm6: [0,3,7,9],
    C6: [0,4,7,9], Cm7: [0,3,7,10], CmMaj7: [0,3,7,11], Cmaj7: [0,4,7,11],
    C7: [0,4,7,10], Cdim7: [0,3,6,9], Cm7b5: [0,3,6,10], Csus2: [0,2,7], Csus4: [0,5,7],
  };
  for (const [chord, expected] of Object.entries(cases)) {
    assert(JSON.stringify(parse(chord).tones) === JSON.stringify(expected), chord);
  }
});
Deno.test("Harte names, enharmonics and slash bass are explicit", () => {
  assert(parse("Db:min7").root === 1, "flat root");
  assert(parse("C/E").bass === 4, "inversion bass");
  assert(parse("C/D").tones.includes(2), "non-triad bass included");
  for (const chord of ["N", "X", "Cunknown", "<script>", null]) assert(parse(chord) === null, "unsupported label");
});
