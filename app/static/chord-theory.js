/* Supported chord pitch classes, separate from audio-note/TAB transcription. */
((scope) => {
  const roots = { C: 0, "B#": 0, "C#": 1, Db: 1, D: 2, "D#": 3, Eb: 3, E: 4,
    Fb: 4, "E#": 5, F: 5, "F#": 6, Gb: 6, G: 7, "G#": 8, Ab: 8,
    A: 9, "A#": 10, Bb: 10, B: 11, Cb: 11 };
  const qualities = {
    "": [0, 4, 7], maj: [0, 4, 7], m: [0, 3, 7], min: [0, 3, 7],
    "6": [0, 4, 7, 9], maj6: [0, 4, 7, 9], m6: [0, 3, 7, 9], min6: [0, 3, 7, 9],
    "7": [0, 4, 7, 10], maj7: [0, 4, 7, 11], m7: [0, 3, 7, 10], min7: [0, 3, 7, 10],
    mMaj7: [0, 3, 7, 11], minmaj7: [0, 3, 7, 11],
    dim: [0, 3, 6], dim7: [0, 3, 6, 9], m7b5: [0, 3, 6, 10], hdim7: [0, 3, 6, 10],
    aug: [0, 4, 8], sus2: [0, 2, 7], sus4: [0, 5, 7], sus: [0, 5, 7],
    "9": [0, 4, 7, 10, 2], maj9: [0, 4, 7, 11, 2], m9: [0, 3, 7, 10, 2], add9: [0, 4, 7, 2],
  };
  function parseChord(label) {
    const match = label?.match(/^([A-G][#b]?):?([^/]*)(?:\/([A-G][#b]?))?$/);
    if (!match || roots[match[1]] === undefined || !qualities[match[2]]) return null;
    const root = roots[match[1]], tones = qualities[match[2]].map((s) => (root+s)%12);
    const bass = match[3] ? roots[match[3]] : undefined;
    if (bass !== undefined && !tones.includes(bass)) tones.push(bass);
    return { root, tones, bass };
  }
  scope.ChordLabTheory = { parseChord };
})(globalThis);
