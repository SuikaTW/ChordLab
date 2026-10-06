# BTC inference sources

Source: https://github.com/jayg996/BTC-ISMIR19
Pinned commit: `2682317be668032e6e4b269ded36adaa2ad57df0` (MIT; see LICENSE).
Park, Choi, Jeon, Kim and Park, *A Bi-Directional Transformer for Musical Chord Recognition*, ISMIR 2019.

Vendored inference modules only. Changes: local imports, removal of unused HParams/demo,
and NumPy `np.float` compatibility. Network access and training are not used.
The checkpoint is downloaded from that same official repository by `scripts/install-btc.sh`,
SHA-256 verified before installation and again before inference. Loading uses restricted
`weights_only=True` with a narrow NumPy float64 allowlist, not arbitrary pickle execution.

170 labels: 12 roots × 14 qualities, unknown and no chord. This is not a 9/11/13
or guitar-note transcription model. Softmax scores are uncalibrated model scores.
Comparison keeps Chordino's labels and boundaries and shows BTC disagreement for review.
