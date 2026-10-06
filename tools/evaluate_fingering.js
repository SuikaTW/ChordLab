import "../app/static/tab-engine.js";
const [notesPath, referencePath, outputPath] = Deno.args;
const notes = JSON.parse(await Deno.readTextFile(notesPath)).notes;
const reference = JSON.parse(await Deno.readTextFile(referencePath));
const result = ChordLabTab.assign(notes, {
  tuning: reference.tuning || "standard",
  capo: reference.capo || 0,
});
const remaining = [...result.notes];
let matched = 0, exact = 0, known = 0;
for (const event of reference.notes) {
  const candidates = remaining.filter((n) => n.midi === event.midi && Math.abs(n.start - event.start) <= .08);
  const chosen = candidates.sort((a, b) =>
    Math.abs(a.start - event.start) - Math.abs(b.start - event.start)
  )[0];
  const hasFingering = Number.isInteger(event.string) && Number.isInteger(event.fret);
  if (hasFingering) known++;
  if (chosen) {
    matched++;
    remaining.splice(remaining.indexOf(chosen), 1);
    if (hasFingering && chosen.string === event.string && chosen.fret === event.fret) exact++;
  }
}
const precision = matched / Math.max(1, result.notes.length),
  recall = matched / Math.max(1, reference.notes.length);
const metrics = {
  displayed_notes: result.notes.length,
  matched,
  precision,
  recall,
  f1: 2 * precision * recall / Math.max(.0001, precision + recall),
  diagnostics: result.diagnostics,
};
if (known) {
  metrics.reference_fingerings = known;
  metrics.fingering_agreement = exact / known;
}
await Deno.writeTextFile(outputPath, JSON.stringify(metrics));
