#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PORT="${SETUP_WIZARD_PORT:-8095}"

# Files copied from Windows often lose executable bits on Linux. If the user
# starts this script with `bash start_setup_wizard.sh`, repair the local helper
# scripts so future `./script.sh` launches work too.
if [[ "$(uname -s 2>/dev/null || true)" != MINGW* && "$(uname -s 2>/dev/null || true)" != CYGWIN* ]]; then
  chmod u+x "${ROOT}/start_setup_wizard.sh" "${ROOT}/llama_server/start_host_service.sh" 2>/dev/null || true
fi

# If a previous setup wizard is still bound to the default port, browsers will
# keep loading that old in-memory copy instead of the updated file on disk.
if command -v lsof >/dev/null 2>&1; then
  while IFS= read -r pid; do
    [[ -n "${pid}" && "${pid}" != "$$" ]] || continue
    kill "${pid}" 2>/dev/null || true
  done < <(lsof -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null || true)
elif command -v fuser >/dev/null 2>&1; then
  fuser -k "${PORT}/tcp" 2>/dev/null || true
fi

exec "${PYTHON_BIN}" "${ROOT}/setup_wizard_app.py" "$@"
