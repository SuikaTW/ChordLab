# Experimental guitar models

Runtime: Python 3.12, CPU-only Torch, two compute threads, queued with other
heavy analysis. Models live in ignored `models/`; never load user checkpoints.
No model downloads are allowed during web requests. Uploaded audio is decoded
inside the existing network-disabled worker sandbox.

## GAPS

- Authors: Xavier Riley, Zixun Guo, Drew Edwards, Simon Dixon.
- Paper: https://arxiv.org/abs/2408.08653
- Author weights: https://huggingface.co/xavriley/midi-transcription-models
- Revision: `b7bec65` (file SHA-256 below is authoritative).
- File: `guitar-gaps-paper-version-12200_iterations.pth`
- Local name: `models/guitar-gaps-paper.pth`
- SHA-256: `94a7c936ec9fde83686d29007dc256274384e832739cadece39e92cee3b69a7e`
- Model card declares MIT. Dataset has separate non-commercial research
  conditions; do not interpret the model card as a dataset redistribution grant.
- Architecture/decoder: Xavier Riley's fork of Qiuqiang Kong's
  `piano_transcription_inference`, pinned at
  `7568dc7f78b625e40cf9776e2806d164006610e3`; upstream package declares MIT.
- ChordLab bypasses the upstream constructor's unrestricted pickle loader,
  downloads, dynamic `eval`, and non-strict state loading. We use checksummed
  weights-only loading with a narrow NumPy-array allowlist and strict state
  loading. Runtime outputs are pitch/onset/offset/velocity, not string labels.
- The generic wrapper's monophonic README conflicts with the polyphonic guitar
  paper; evaluate the actual checkpoint on chords before changing defaults.

## TabCNN + GuitarProFX

- Original TabCNN: Andrew Wiggins and Youngmoo Kim, ISMIR 2019.
- GuitarProFX: Hegel Pedroza, Wallace Abreu, Ryan M. Corey, Iran R. Roman,
  DAFx 2024: https://robust-guitar-tabs.github.io/
- Original weights/data (CC BY 4.0): https://zenodo.org/records/11406378
- ONNX conversion by cstr (not the research authors):
  https://huggingface.co/cstr/tabcnn-onnx
- Revision: `886ead7d8b67db58503bd79f80781724dd33dd60`
- File: `models/tabcnn-gpfx.onnx`
- SHA-256: `8d9ce59157bdab37fb4816d32d7f29f3da0cdbf3c7876707c819af4d1f88e6b7`
- CC BY 4.0. Attribute Pedroza et al., Wiggins/Kim and GuitarSet (Xi et al.,
  ISMIR 2018). GuitarSet: https://github.com/marl/GuitarSet
- Input `[N,192,9,1]`: 22050Hz, hop512, 192 CQT bins, 24 bins/octave,
  C1 fmin; per-clip amplitude-to-dB, min/max normalization. Output `[N,6,21]`
  log probabilities: class0 silent, class1 open, class20 fret19.
- Standard tuning only. Model string/fret hints are ignored for alternate
  tuning or capo != 0; pitch-based playable fingering remains available.
- Frame labels are converted to continuous note runs; repeated plucks on the
  same fret can merge. Probability is not calibrated accuracy or velocity.
  No automatic pitch fusion or claims of original fingering correctness.

## Rebuild

Run `bash scripts/install-guitar.sh` to create the CPU runtime and download both
checksum-verified models. Restart the web service afterwards. Equivalent steps:

```sh
uv venv --python 3.12 .venv-guitar
uv pip install --python .venv-guitar/bin/python torch==2.10.0 --index-url https://download.pytorch.org/whl/cpu
uv pip install --python .venv-guitar/bin/python -r requirements-guitar.txt
mkdir -p vendor/guitar/models
curl -fL https://huggingface.co/xavriley/midi-transcription-models/resolve/b7bec65/guitar-gaps-paper-version-12200_iterations.pth -o vendor/guitar/models/guitar-gaps-paper.pth
curl -fL https://huggingface.co/cstr/tabcnn-onnx/resolve/886ead7d8b67db58503bd79f80781724dd33dd60/tabcnn-gpfx.onnx -o vendor/guitar/models/tabcnn-gpfx.onnx
```

Workers validate SHA-256 before inference. `tools/benchmark_guitar.py` evaluates
saved predictions against annotated notes without touching the web database.
Onset tolerance is 50ms; offset tolerance is max(50ms,20% reference duration).
It reports pitch, timing and string/fret scores separately. EGSet12 is the
authors' own TabCNN benchmark, not a new independent test set. None of the
models should become default based on one clip or synthetic fixtures alone.
