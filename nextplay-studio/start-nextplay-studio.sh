#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$APP_DIR/.." && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
PYTHON="${NEXTPLAY_PYTHON:-/Library/Frameworks/Python.framework/Versions/3.14/bin/python3}"
if [[ ! -x "$PYTHON" ]]; then PYTHON=python3; fi
cd -- "$APP_DIR"
exec "$PYTHON" -B -m studio.server --project "$PROJECT_DIR" --port "${NEXTPLAY_PORT:-8777}"
