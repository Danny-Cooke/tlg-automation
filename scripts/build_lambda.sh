#!/usr/bin/env bash
# Assemble build/lambda/ for Terraform's archive_file.
# Installs deps for the Lambda target (arm64, python3.12) and copies the
# bot package plus the persona file next to it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/build/lambda"

rm -rf "$OUT"
mkdir -p "$OUT"

python -m pip install \
  --quiet \
  --requirement "$ROOT/src/requirements.txt" \
  --target "$OUT" \
  --platform manylinux2014_aarch64 \
  --implementation cp \
  --python-version 3.12 \
  --only-binary=:all:

cp -r "$ROOT/src/bot" "$OUT/bot"
cp -r "$ROOT/src/monitor" "$OUT/monitor"
cp -r "$ROOT/src/menu_sync" "$OUT/menu_sync"
cp "$ROOT/persona/jess.md" "$OUT/bot/jess.md"
find "$OUT" -name "__pycache__" -type d -prune -exec rm -rf {} +

echo "Built $OUT"
