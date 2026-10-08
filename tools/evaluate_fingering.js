import "../app/static/chord-theory.js";
import "../app/static/chord-voicings.js";
import "../app/static/tab-engine.js";
const [notesPath, referencePath, outputPath, mode] = Deno.args;
const notes = JSON.parse(await Deno.readTextFile(notesPath)).notes;
const reference = JSON.parse(await Deno.readTextFile(referencePath));
const chordShapeAssist = mode === "model-chord" || mode === "playable-chord";
const chordShapes = chordShapeAssist ? JSON.parse(await Deno.readTextFile(
  notesPath.replace(/[^/]+$/, "chordino.json"))).chords.map((segment) => ({
    start: segment.start, end: segment.end, confidence: segment.confidence,
    shapes: ChordLabVoicings.positions(segment.chord).map((voicing) => voicing.shape),
  })) : [];
const result = ChordLabTab.assign(notes, {
  tuning: reference.tuning || "standard",
  capo: reference.capo || 0,
  useModelFingering: mode === "model" || mode === "model-context" || mode === "model-chord",
  contextReview: mode === "model-context",
  chordShapeAssist, chordShapes,
});
function matches(expected, exact) {
  const edges = expected.map((event) => result.notes.flatMap((note, index) =>
    note.midi === event.midi && Math.abs(note.start - event.start) <= .08 &&
      (!exact || note.string === event.string && note.fret === event.fret) ? [index] : []));
  const assigned = new Map();
  function augment(row, visited) {
    for (const column of edges[row]) {
      if (visited.has(column)) continue;
      visited.add(column);
      if (!assigned.has(column) || augment(assigned.get(column), visited)) {
        assigned.set(column, row);
        return true;
      }
    }
    return false;
  }
  return edges.reduce((count, _, row) => count + Number(augment(row, new Set())), 0);
}
const knownNotes = reference.notes.filter((event) => Number.isInteger(event.string) && Number.isInteger(event.fret));
const matched = matches(reference.notes, false), exact = matches(knownNotes, true), known = knownNotes.length;
const precision = matched / Math.max(1, result.notes.length),
  recall = matched / Math.max(1, reference.notes.length);
const metrics = {
  displayed_notes: result.notes.length,
  matched,
  precision,
  recall,
  f1: 2 * precision * recall / Math.max(.0001, precision + recall),
  diagnostics: result.diagnostics,
  onset_tolerance_seconds: .08,
  matching: "maximum_one_to_one",
};
if (known) {
  metrics.reference_fingerings = known;
  metrics.fingering_agreement = exact / known;
}
await Deno.writeTextFile(outputPath, JSON.stringify(metrics));
