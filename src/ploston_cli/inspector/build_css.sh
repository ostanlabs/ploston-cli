#!/usr/bin/env bash
# Build the inspector's pre-compiled Tailwind CSS.
#
# Usage:
#   ./build_css.sh          # one-shot compile
#   ./build_css.sh --watch  # watch mode for development
#
# Requires the standalone Tailwind CSS CLI v4+.
# Install: curl -sL https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-macos-arm64 -o /usr/local/bin/tailwindcss && chmod +x /usr/local/bin/tailwindcss
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INPUT="$SCRIPT_DIR/static/input.css"
OUTPUT="$SCRIPT_DIR/static/styles.css"

# Find tailwindcss binary
if command -v tailwindcss &>/dev/null; then
  TW=tailwindcss
elif [ -x /tmp/tailwindcss ]; then
  TW=/tmp/tailwindcss
else
  echo "Error: tailwindcss CLI not found."
  echo "Install: curl -sL https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-macos-arm64 -o /usr/local/bin/tailwindcss && chmod +x /usr/local/bin/tailwindcss"
  exit 1
fi

EXTRA_ARGS=""
if [[ "${1:-}" == "--watch" ]]; then
  EXTRA_ARGS="--watch"
fi

cd "$SCRIPT_DIR"
exec "$TW" -i "$INPUT" -o "$OUTPUT" --minify $EXTRA_ARGS
