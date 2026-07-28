#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PORT="${SETUP_WIZARD_PORT:-8095}"

stop_wizard_listener() {
  local pid=""
  if command -v lsof >/dev/null 2>&1; then
    while IFS= read -r pid; do
      [[ -n "${pid}" && "${pid}" != "$$" ]] || continue
      local cmdline=""
      if [[ -r "/proc/${pid}/cmdline" ]]; then
        cmdline="$(tr '\0' ' ' <"/proc/${pid}/cmdline" 2>/dev/null || true)"
      elif command -v ps >/dev/null 2>&1; then
        cmdline="$(ps -p "${pid}" -o command= 2>/dev/null || true)"
      fi
      if [[ -n "${cmdline}" && "${cmdline}" != *"setup_wizard_app.py"* ]]; then
        continue
      fi
      echo "Stopping setup wizard on port ${PORT} (PID ${pid})"
      kill "${pid}" 2>/dev/null || true
      sleep 1
      kill -9 "${pid}" 2>/dev/null || true
    done < <(lsof -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null || true)
  elif command -v fuser >/dev/null 2>&1; then
    fuser -k "${PORT}/tcp" 2>/dev/null || true
  fi
}

echo "Stopping GotChat services started by the setup wizard..."
"${PYTHON_BIN}" "${ROOT}/setup_wizard_app.py" --stop-services
stop_wizard_listener
echo "Done."
