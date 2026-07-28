#!/usr/bin/env bash

set -euo pipefail

ACTION="${1:-start}"
PORT="${PORT:-8767}"
BIND="${BIND:-127.0.0.1}"
PYTHON_BIN="${PYTHON_BIN:-python}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PARENT_ROOT="$(cd "${ROOT}/.." && pwd)"
PID_FILE="${SCRIPT_DIR}/host_service.pid"
LOG_FILE="${SCRIPT_DIR}/host_service.log"
ERR_LOG_FILE="${SCRIPT_DIR}/host_service.err.log"
SCRIPT_PATH="${SCRIPT_DIR}/host_service.py"
LAUNCHER_PATH="${SCRIPT_DIR}/host_service_launcher.py"

usage() {
  cat <<EOF
Usage: $(basename "$0") [start|stop|restart|status|foreground] [--port PORT] [--bind HOST] [--python PATH]
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    start|stop|restart|status|foreground)
      ACTION="$1"
      shift
      ;;
    --port)
      PORT="${2:-}"
      shift 2
      ;;
    --bind)
      BIND="${2:-}"
      shift 2
      ;;
    --python)
      PYTHON_BIN="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

get_default_host_service_python_candidates() {
  printf '%s\n' \
    "${ROOT}/.venv/bin/python" \
    "${ROOT}/venv/bin/python" \
    "${PARENT_ROOT}/.venv/bin/python" \
    "${PARENT_ROOT}/venv/bin/python" \
    "${ROOT}/.venv/Scripts/python.exe" \
    "${ROOT}/venv/Scripts/python.exe" \
    "${PARENT_ROOT}/.venv/Scripts/python.exe" \
    "${PARENT_ROOT}/venv/Scripts/python.exe"
}

test_python_has_module() {
  local python_exe="$1"
  local module_name="$2"
  "${python_exe}" -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('${module_name}') else 1)" >/dev/null 2>&1
}

resolve_host_service_python() {
  local requested="${PYTHON_BIN}"
  if [[ -n "${requested}" && "${requested}" != "python" ]]; then
    if [[ -x "${requested}" ]]; then
      printf '%s\n' "${requested}"
      return
    fi
    echo "Requested Python not found or not executable: ${requested}; searching for a usable Python" >&2
  fi
  while IFS= read -r candidate; do
    [[ -n "${candidate}" ]] || continue
    [[ -x "${candidate}" ]] || continue
    if test_python_has_module "${candidate}" "huggingface_hub"; then
      printf '%s\n' "${candidate}"
      return
    fi
  done < <(get_default_host_service_python_candidates)
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return
  fi
  printf '%s\n' "python"
}

test_host_service_health() {
  curl -fsS --max-time 3 "http://${BIND}:${PORT}/health" >/dev/null 2>&1
}

get_host_service_listener_pids() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null | awk '!seen[$0]++'
    return
  fi
  if command -v ss >/dev/null 2>&1; then
    ss -ltnp 2>/dev/null | awk -v port=":${PORT}" '
      index($0, port) {
        while (match($0, /pid=[0-9]+/)) {
          pid = substr($0, RSTART + 4, RLENGTH - 4)
          if (!seen[pid]++) print pid
          $0 = substr($0, RSTART + RLENGTH)
        }
      }
    '
  fi
}

read_host_service_listener_pids() {
  listeners=()
  local listener_pid=""
  while IFS= read -r listener_pid; do
    [[ -n "${listener_pid}" ]] && listeners+=("${listener_pid}")
  done < <(get_host_service_listener_pids || true)
}

array_contains() {
  local needle="$1"
  shift || true
  local item=""
  for item in "$@"; do
    [[ "${item}" == "${needle}" ]] && return 0
  done
  return 1
}

get_host_service_process() {
  local saved_pid=""
  if [[ -f "${PID_FILE}" ]]; then
    saved_pid="$(head -n 1 "${PID_FILE}" 2>/dev/null || true)"
    if [[ "${saved_pid}" =~ ^[0-9]+$ ]] && kill -0 "${saved_pid}" 2>/dev/null; then
      local saved_args=""
      saved_args="$(ps -p "${saved_pid}" -o args= 2>/dev/null || true)"
      if [[ "${saved_args}" == *"${SCRIPT_PATH}"* ]] && [[ "${saved_args}" == *python* ]]; then
        printf '%s\n' "${saved_pid}"
        return 0
      fi
    fi
  fi
  local match_pid=""
  match_pid="$(ps -eo pid=,args= 2>/dev/null | awk -v script="${SCRIPT_PATH}" '
    index($0, script) && $0 ~ /python/ { pid=$1 }
    END { if (pid) print pid }
  ' || true)"
  if [[ "${match_pid}" =~ ^[0-9]+$ ]]; then
    printf '%s\n' "${match_pid}" > "${PID_FILE}" 2>/dev/null || true
    printf '%s\n' "${match_pid}"
    return 0
  fi
  return 1
}

remove_stale_pid() {
  if [[ -f "${PID_FILE}" ]] && ! get_host_service_process >/dev/null 2>&1; then
    rm -f "${PID_FILE}"
  fi
}

start_host_service() {
  local resolved_python
  resolved_python="$(resolve_host_service_python)"
  local existing=""
  existing="$(get_host_service_process || true)"
  if [[ "${existing}" =~ ^[0-9]+$ ]]; then
    if test_host_service_health; then
      echo "llama host service already running (PID ${existing})"
      return
    fi
    echo "llama host service process ${existing} is present but not healthy; restarting it" >&2
    kill "${existing}" 2>/dev/null || true
    sleep 0.5
    if kill -0 "${existing}" 2>/dev/null; then
      kill -9 "${existing}" 2>/dev/null || true
    fi
    rm -f "${PID_FILE}"
  fi
  local listeners=()
  read_host_service_listener_pids
  if [[ "${#listeners[@]}" -gt 0 ]]; then
    echo "Port ${PORT} is already in use by PID(s): ${listeners[*]}. Run stop or restart first." >&2
    exit 1
  fi
  "${resolved_python}" "${LAUNCHER_PATH}" \
    --python "${resolved_python}" \
    --script "${SCRIPT_PATH}" \
    --root "${ROOT}" \
    --pid-file "${PID_FILE}" \
    --stdout "${LOG_FILE}" \
    --stderr "${ERR_LOG_FILE}" \
    --bind "${BIND}" \
    --port "${PORT}" >/dev/null
  sleep 1
  local launched_pid=""
  if [[ -f "${PID_FILE}" ]]; then
    launched_pid="$(head -n 1 "${PID_FILE}" 2>/dev/null || true)"
  fi
  if ! test_host_service_health; then
    echo "failed to launch llama host service; check ${LOG_FILE} and ${ERR_LOG_FILE}" >&2
    exit 1
  fi
  if [[ -n "${launched_pid}" ]]; then
    echo "llama host service started on http://${BIND}:${PORT} (PID ${launched_pid}, python ${resolved_python})"
  else
    echo "llama host service started on http://${BIND}:${PORT} (python ${resolved_python})"
  fi
}

stop_host_service() {
  local targets=()
  local existing=""
  existing="$(get_host_service_process || true)"
  if [[ "${existing}" =~ ^[0-9]+$ ]]; then
    targets+=("${existing}")
  fi
  while IFS= read -r listener_pid; do
    [[ "${listener_pid}" =~ ^[0-9]+$ ]] || continue
    if [[ "${#targets[@]}" -eq 0 ]] || ! array_contains "${listener_pid}" "${targets[@]}"; then
      targets+=("${listener_pid}")
    fi
  done < <(get_host_service_listener_pids || true)
  if [[ "${#targets[@]}" -eq 0 ]]; then
    remove_stale_pid
    echo "llama host service is not running"
    return
  fi
  for target_pid in "${targets[@]}"; do
    kill "${target_pid}" 2>/dev/null || true
  done
  local deadline=$((SECONDS + 10))
  local still_up=1
  while (( SECONDS < deadline )); do
    still_up=0
    for target_pid in "${targets[@]}"; do
      if kill -0 "${target_pid}" 2>/dev/null; then
        still_up=1
        break
      fi
    done
    (( still_up == 0 )) && break
    sleep 0.25
  done
  if (( still_up != 0 )); then
    for target_pid in "${targets[@]}"; do
      kill -9 "${target_pid}" 2>/dev/null || true
    done
  fi
  rm -f "${PID_FILE}"
  echo "llama host service stopped (PID(s): ${targets[*]})"
}

wait_host_service_stopped() {
  local timeout_sec="${1:-10}"
  local deadline=$((SECONDS + timeout_sec))
  local listeners=()
  while (( SECONDS < deadline )); do
    read_host_service_listener_pids
    if [[ "${#listeners[@]}" -eq 0 ]]; then
      return 0
    fi
    sleep 0.25
  done
  return 1
}

restart_host_service() {
  echo "restarting llama host service on http://${BIND}:${PORT}"
  stop_host_service
  if ! wait_host_service_stopped 10; then
    local listeners=()
    read_host_service_listener_pids
    echo "Port ${PORT} is still in use after stop (PID(s): ${listeners[*]})" >&2
    exit 1
  fi
  echo "starting llama host service..."
  start_host_service
}

show_status() {
  local existing=""
  existing="$(get_host_service_process || true)"
  local listeners=()
  read_host_service_listener_pids
  if [[ "${existing}" =~ ^[0-9]+$ ]] && test_host_service_health; then
    echo "running pid=${existing} listeners=${listeners[*]:-} url=http://${BIND}:${PORT}"
  elif test_host_service_health; then
    echo "running listeners=${listeners[*]:-} url=http://${BIND}:${PORT}"
  else
    remove_stale_pid
    echo "stopped"
  fi
}

foreground_host_service() {
  local resolved_python
  resolved_python="$(resolve_host_service_python)"
  export LLMLOADER2_LLAMA_MANAGER_BIND="${BIND}"
  export LLMLOADER2_LLAMA_MANAGER_PORT="${PORT}"
  export LLMLOADER2_LLAMA_MANAGER_ROOT="${ROOT}"
  export LLMLOADER2_AUTH_ME_URL="${LLMLOADER2_AUTH_ME_URL:-http://localhost:8000/v1/auth/me}"
  exec "${resolved_python}" -u "${SCRIPT_PATH}"
}

case "${ACTION}" in
  start) start_host_service ;;
  stop) stop_host_service ;;
  restart) restart_host_service ;;
  status) show_status ;;
  foreground) foreground_host_service ;;
  *)
    echo "Unsupported action: ${ACTION}" >&2
    usage >&2
    exit 2
    ;;
esac
