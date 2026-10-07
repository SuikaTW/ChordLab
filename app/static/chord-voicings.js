/* Standard-tuning chord shapes, independent of recorded-note TAB transcription. */
((scope) => {
  const tuning = [40, 45, 50, 55, 59, 64], cache = new Map();
  // Authored common open shapes; moving all sounded strings also yields barre shapes.
  const common = [
    ["C", [-1,3,2,0,1,0]], ["A", [-1,0,2,2,2,0]],
    ["G", [3,2,0,0,0,3]], ["G", [3,2,0,0,3,3]],
    ["E", [0,2,2,1,0,0]], ["D", [-1,-1,0,2,3,2]],
    ["Am", [-1,0,2,2,1,0]], ["Em", [0,2,2,0,0,0]], ["Dm", [-1,-1,0,2,3,1]],
    ["C7", [-1,3,2,3,1,0]], ["A7", [-1,0,2,0,2,0]],
    ["G7", [3,2,0,0,0,1]], ["E7", [0,2,0,1,0,0]], ["D7", [-1,-1,0,2,1,2]],
    ["Cmaj7", [-1,3,2,0,0,0]], ["Amaj7", [-1,0,2,1,2,0]],
    ["Emaj7", [0,2,1,1,0,0]], ["Dmaj7", [-1,-1,0,2,2,2]],
    ["Am7", [-1,0,2,0,1,0]], ["Em7", [0,2,0,0,0,0]], ["Dm7", [-1,-1,0,2,1,1]],
    ["Asus2", [-1,0,2,2,0,0]], ["Dsus2", [-1,-1,0,2,3,0]],
    ["Asus4", [-1,0,2,2,3,0]], ["Esus4", [0,2,2,2,0,0]], ["Dsus4", [-1,-1,0,2,3,3]],
    ["C/E", [0,3,2,0,1,0]], ["D/F#", [2,-1,0,2,3,2]],
    ["G/B", [-1,2,0,0,0,3]], ["Am/C", [-1,3,2,2,1,0]],
  ];
  function hand(shape) {
    const fretted = shape.flatMap((fret, string) => fret > 0 ? [{ fret, string }] : []);
    if (fretted.length <= 4) return { fingers: fretted.length, barre: null };
    let barre = null, fingers = fretted.length;
    for (const fret of new Set(fretted.map((point) => point.fret))) {
      const strings = fretted.filter((point) => point.fret === fret).map((point) => point.string);
      // One continuous barre may never cross a lower fret, an open or a muted string.
      for (const from of strings) for (const to of strings) {
        if (to <= from || shape.slice(from, to + 1).some((value) => value < fret)) continue;
        const covered = strings.filter((string) => string >= from && string <= to).length;
        const count = fretted.length - covered + 1;
        if (count < fingers) { fingers = count; barre = { fret, from, to }; }
      }
    }
    return { fingers, barre };
  }
  function describe(shape, parsed, known = false) {
    const played = shape.flatMap((fret, string) => fret < 0 ? [] : [{ fret, pitch: tuning[string] + fret }]);
    if (played.length < 3) return null;
    const pcs = new Set(played.map((note) => note.pitch % 12));
    if (!parsed.tones.every((tone) => pcs.has(tone)) || [...pcs].some((tone) => !parsed.tones.includes(tone))) return null;
    // Lowest sounding pitch, not simply the leftmost string (important for inversions).
    const bass = Math.min(...played.map((note) => note.pitch)) % 12;
    if (bass !== (parsed.bass ?? parsed.root)) return null;
    const fretted = played.filter((note) => note.fret > 0).map((note) => note.fret);
    const low = fretted.length ? Math.min(...fretted) : 0, high = fretted.length ? Math.max(...fretted) : 0;
    if (high - low > 3 || high > 15) return null;
    if (high > 5 && shape.includes(0)) return null;
    const grip = hand(shape);
    if (grip.fingers > 4) return null;
    const start = high <= 5 ? 1 : Math.max(1, low);
    const score = (known ? -10 : 0) + low * .35 + (high-low) * 1.5 + grip.fingers * .7 +
      shape.filter((fret) => fret < 0).length * .8 + (bass === parsed.root ? 0 : 4);
    return { shape: [...shape], start, low, high, barre: grip.barre, known, score };
  }
  function positions(label) {
    if (cache.has(label)) return cache.get(label);
    const parsed = scope.ChordLabTheory.parseChord(label);
    if (!parsed) return [];
    const found = new Map();
    function add(shape, known = false) {
      const result = describe(shape, parsed, known), key = shape.join(",");
      if (result && (!found.has(key) || result.score < found.get(key).score)) found.set(key, result);
    }
    for (const [name, shape] of common) {
      const source = scope.ChordLabTheory.parseChord(name);
      const offset = (parsed.root - source.root + 12) % 12;
      for (const shift of [offset, offset + 12]) add(shape.map((fret) => fret < 0 ? -1 : fret + shift), true);
    }
    // Bounded four-fret windows. Mutes only at the edges keep strums practical.
    for (let base = 1; base <= 12; base++) {
      const choices = tuning.map((pitch) => {
        const values = [-1];
        if (parsed.tones.includes(pitch % 12)) values.push(0);
        for (let fret = base; fret <= base + 3; fret++) {
          if (parsed.tones.includes((pitch + fret) % 12)) values.push(fret);
        }
        return values;
      });
      function walk(index, shape, started, ended) {
        if (index === 6) { add(shape); return; }
        for (const fret of choices[index]) {
          if (ended && fret >= 0) continue;
          walk(index + 1, [...shape, fret], started || fret >= 0, ended || (started && fret < 0));
        }
      }
      walk(0, [], false, false);
    }
    const sorted = [...found.values()].sort((a,b) => a.score-b.score || a.shape.join(",").localeCompare(b.shape.join(",")));
    const selected = [], seen = new Set();
    // One representative per actual hand position; keep the choices compact.
    for (const result of sorted) {
      const position = result.shape.includes(0) && result.high <= 4 ? "open" : result.low;
      if (seen.has(position)) continue;
      seen.add(position); selected.push(result);
      if (selected.length === 6) break;
    }
    if (selected.length > 1) selected.splice(1, selected.length - 1, ...selected.slice(1).sort((a,b) => a.low-b.low));
    if (cache.size >= 96) cache.delete(cache.keys().next().value);
    cache.set(label, selected);
    return selected;
  }
  function caption(voicing) {
    return voicing.shape.includes(0) && voicing.high <= 4 ? "開放把位" : `第 ${voicing.low || 1} 把位`;
  }
  function diagram(voicing) {
    const { shape, start, barre } = voicing;
    const x = (string) => 46 + string * 28, y = (fret) => 62 + (fret - start + .5) * 30;
    const parts = [];
    for (let fret = 0; fret <= 5; fret++) parts.push(`<line class="chord-fret${fret === 0 && start === 1 ? " chord-nut" : ""}" x1="46" y1="${62+fret*30}" x2="186" y2="${62+fret*30}"/>`);
    for (let string = 0; string < 6; string++) {
      parts.push(`<line class="chord-string" x1="${x(string)}" y1="62" x2="${x(string)}" y2="212"/>`);
      parts.push(`<text class="chord-string-label" x="${x(string)}" y="237">${["E","A","D","G","B","e"][string]}</text>`);
      parts.push(`<text class="chord-string-number" x="${x(string)}" y="253">${6-string}</text>`);
      if (shape[string] <= 0) parts.push(`<text class="chord-open-muted" x="${x(string)}" y="46">${shape[string] === 0 ? "○" : "×"}</text>`);
      else parts.push(`<circle class="chord-dot" cx="${x(string)}" cy="${y(shape[string])}" r="8"/>`);
    }
    if (barre) parts.push(`<line class="chord-barre" x1="${x(barre.from)}" y1="${y(barre.fret)}" x2="${x(barre.to)}" y2="${y(barre.fret)}"/>`);
    for (let row = 0; row < 5; row++) parts.push(`<text class="chord-fret-number" x="24" y="${82+row*30}">${start+row}</text>`);
    const description = shape.map((fret,i) => `${6-i} 弦${fret < 0 ? "不彈" : fret === 0 ? "空弦" : `第 ${fret} 格`}`).join("，");
    return `<svg class="chord-chart" viewBox="0 0 232 268" role="img" aria-label="${description}"><title>${description}</title>${parts.join("")}</svg>`;
  }
  scope.ChordLabVoicings = { positions, caption, diagram };
})(globalThis);
