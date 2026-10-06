#!/usr/bin/env bash
set -euo pipefail

DENO_VERSION="2.9.7"
DENO_SHA256="c6527f24f4b16031d3ae4fa9f658d5f11534c8d84ce7dc8502420280919c3490"

if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "This installer currently supports x86_64 Linux only." >&2
  exit 1
fi

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
download_dir="$(mktemp -d)"
trap 'rm -rf -- "$download_dir"' EXIT
archive="$download_dir/deno.zip"

curl --fail --location --retry 3 \
  "https://dl.deno.land/release/v${DENO_VERSION}/deno-x86_64-unknown-linux-gnu.zip" \
  --output "$archive"
printf '%s  %s\n' "$DENO_SHA256" "$archive" | sha256sum --check --status
unzip -q "$archive" -d "$download_dir"
install -m 0755 "$download_dir/deno" "$project_root/bin/deno"
"$project_root/bin/deno" --version
