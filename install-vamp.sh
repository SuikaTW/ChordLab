#!/usr/bin/env bash
set -euo pipefail
root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dest="$root_dir/vendor/vamp"
archive_name="nnls-chroma-linux64-v1.1.tar.bz2"
expected_sha256="877964bce86027d1c73c9210fcb3446b1da10dc40bba36b1bf04a61a60ad1d7f"
primary="https://code.soundsoftware.ac.uk/attachments/download/1693/$archive_name"
mirror="https://github.com/bkl2000/chordflask/releases/download/vamp-deps-1/$archive_name"
mkdir -p "$dest"
if [[ -f "$dest/nnls-chroma.so" ]]; then
  echo "Chordino is already installed."
  exit 0
fi
temp_dir="$(mktemp -d)"
trap 'rm -rf "$temp_dir"' EXIT
if ! curl -fL --connect-timeout 15 --max-time 300 -o "$temp_dir/$archive_name" "$primary"; then
  curl -fL --connect-timeout 15 --max-time 300 -o "$temp_dir/$archive_name" "$mirror"
fi
actual="$(sha256sum "$temp_dir/$archive_name" | awk '{print $1}')"
[[ "$actual" == "$expected_sha256" ]] || { echo "Chordino archive checksum mismatch" >&2; exit 1; }
python3 - "$temp_dir/$archive_name" "$temp_dir" <<'PY'
import sys
import tarfile

with tarfile.open(sys.argv[1], "r:bz2") as archive:
    archive.extractall(sys.argv[2], filter="data")
PY
find "$temp_dir" -type f \( -name 'nnls-chroma.so' -o -name 'nnls-chroma.cat' -o -name 'nnls-chroma.n3' -o -name 'chord.dict' \) -exec cp -f {} "$dest/" \;
[[ -f "$dest/nnls-chroma.so" ]] || { echo "Chordino plugin was not found after extraction" >&2; exit 1; }
echo "Chordino installed in $dest"
