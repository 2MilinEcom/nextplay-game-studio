#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
PYTHON="${NEXTPLAY_PYTHON:-python3}"
trap 'echo "NEXTPLAY pipeline stopped at line $LINENO; previous AI reports, if present, are not results of this run." >&2' ERR
if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "Existing OPENAI_API_KEY is unavailable here. Run from the terminal where it was confirmed." >&2
  exit 1
fi
# Preserve the selected OpenAI credentials: the legacy collector loads its own .env
# in a separate child process; those assignments cannot override this shell.
"$PYTHON" test_clash_api.py
"$PYTHON" nextplay-clash-v2.py
"$PYTHON" nextplay-clash-ai.py
