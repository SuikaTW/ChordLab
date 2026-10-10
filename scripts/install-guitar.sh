#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
if [ ! -x .venv-guitar/bin/python ]; then
  uv venv --python 3.12 .venv-guitar
fi
uv pip install --python .venv-guitar/bin/python torch==2.10.0 --index-url https://download.pytorch.org/whl/cpu
uv pip install --python .venv-guitar/bin/python -r requirements/guitar.txt
mkdir -p vendor/guitar/models
guitar_download_tmp=$(mktemp vendor/guitar/models/download.XXXXXXXX)
trap 'rm -f -- "$guitar_download_tmp"' EXIT
curl --fail --location --proto '=https' --proto-redir '=https' --tlsv1.2 \
  https://huggingface.co/xavriley/midi-transcription-models/resolve/b7bec65/guitar-gaps-paper-version-12200_iterations.pth \
  -o "$guitar_download_tmp"
echo "94a7c936ec9fde83686d29007dc256274384e832739cadece39e92cee3b69a7e  $guitar_download_tmp" | sha256sum --check
mv -- "$guitar_download_tmp" vendor/guitar/models/guitar-gaps-paper.pth
guitar_download_tmp=$(mktemp vendor/guitar/models/download.XXXXXXXX)
curl --fail --location --proto '=https' --proto-redir '=https' --tlsv1.2 \
  https://huggingface.co/cstr/tabcnn-onnx/resolve/886ead7d8b67db58503bd79f80781724dd33dd60/tabcnn-gpfx.onnx \
  -o "$guitar_download_tmp"
echo "8d9ce59157bdab37fb4816d32d7f29f3da0cdbf3c7876707c819af4d1f88e6b7  $guitar_download_tmp" | sha256sum --check
mv -- "$guitar_download_tmp" vendor/guitar/models/tabcnn-gpfx.onnx
