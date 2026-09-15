#!/usr/bin/env bash
# Idempotently put `psrw` on PATH. Never edits a shell profile.
set -euo pipefail

TOOLKIT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$TOOLKIT/bin/psrw"
DEST_DIR="$HOME/.local/bin"
DEST="$DEST_DIR/psrw"

if [ ! -x "$SRC" ]; then
  echo "ERROR: $SRC is missing or not executable" >&2
  exit 1
fi

mkdir -p "$DEST_DIR"
ln -sfn "$SRC" "$DEST"
echo "linked $DEST -> $SRC"

case ":$PATH:" in
  *":$DEST_DIR:"*)
    echo "✅ psrw is on PATH. Try: psrw status"
    ;;
  *)
    echo "⚠️  $DEST_DIR is not on your PATH."
    echo "   Add it to your shell profile, or invoke it directly:"
    echo "   $SRC"
    ;;
esac
