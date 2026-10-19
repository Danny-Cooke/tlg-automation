#!/usr/bin/env bash
# Assemble a Lambda bundle for Terraform's archive_file.
#
#   scripts/build_lambda.sh                        -> build/lambda        (bot, monitor, menu_sync + persona)
#   scripts/build_lambda.sh menu_sync              -> build/menu_sync     (that package only)
#   scripts/build_lambda.sh fresha_watch menu_sync -> build/fresha_watch  (named after the first package,
#                                                                          holds every package listed)
#
# Installs deps for the Lambda target (arm64, python3.12) and copies the named
# src/ packages next to them. The persona and the rendered salon config ship
# only with the bot (rendering needs python-hcl2 from requirements-mcp.txt).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ $# -eq 0 ]; then
  PACKAGES=(bot monitor menu_sync)
  OUT="$ROOT/build/lambda"
else
  PACKAGES=("$@")
  OUT="$ROOT/build/$1"
fi

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

for pkg in "${PACKAGES[@]}"; do
  cp -r "$ROOT/src/$pkg" "$OUT/$pkg"
done
if [ -d "$OUT/bot" ]; then
  cp "$ROOT/persona/jess.md" "$OUT/bot/jess.md"
  # Salon facts travel in the bundle, not in an env var (4KB limit). Needs python-hcl2.
  python "$ROOT/scripts/render_salon_config.py" "$ROOT/terraform" "$OUT/bot/salon_config.json"
fi
find "$OUT" -name "__pycache__" -type d -prune -exec rm -rf {} +

echo "Built $OUT (${PACKAGES[*]})"
