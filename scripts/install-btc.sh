#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
if [ ! -x .venv-btc/bin/python ]; then
  uv venv .venv-btc --python 3.12
fi
uv pip install --python .venv-btc/bin/python --index-strategy unsafe-best-match -r requirements-btc.txt
mkdir -p vendor/btc/models
checkpoint_tmp=$(mktemp vendor/btc/models/checkpoint.XXXXXXXX)
trap 'rm -f -- "$checkpoint_tmp"' EXIT
curl --fail --location --proto '=https' --proto-redir '=https' --tlsv1.2 \
  https://raw.githubusercontent.com/jayg996/BTC-ISMIR19/2682317be668032e6e4b269ded36adaa2ad57df0/test/btc_model_large_voca.pt \
  -o "$checkpoint_tmp"
echo "1673d23f8f9a55ae7f9e8b80a51da616debb22675b8d8b67ea6ce0ef37b0ab51  $checkpoint_tmp" | sha256sum --check
mv -- "$checkpoint_tmp" vendor/btc/models/btc_model_large_voca.pt
