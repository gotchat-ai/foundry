from __future__ import annotations

import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import secrets
import ssl
import zipfile
import ctypes
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen


DEFAULT_UA = "llmloader2-llama-server-manager/1.0"


def _now_ts() -> int:
    return int(time.time())


def _https_context() -> Optional[ssl.SSLContext]:
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


def _json_url(url: str, *, timeout: float = 30.0) -> Dict[str, Any]:
    req = Request(url, headers={"User-Agent": DEFAULT_UA, "Accept": "application/json"})
    kwargs: Dict[str, Any] = {}
    if str(url).lower().startswith("https://"):
        context = _https_context()
        if context is not None:
            kwargs["context"] = context
    with urlopen(req, timeout=timeout, **kwargs) as resp:
        return json.loads((resp.read() or b"{}").decode("utf-8", errors="ignore"))


def _windows_hidden_subprocess_kwargs() -> Dict[str, Any]:
    if os.name != "nt":
        return {}
    kwargs: Dict[str, Any] = {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }
    startupinfo = None
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
    except Exception:
        startupinfo = None
    if startupinfo is not None:
        kwargs["startupinfo"] = startupinfo
    return kwargs


def _pid_exists(pid: int) -> bool:
    pid = int(pid or 0)
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except Exception:
            return False
    try:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    except Exception:
        return False


def _download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = Request(url, headers={"User-Agent": DEFAULT_UA})
    kwargs: Dict[str, Any] = {}
    if str(url).lower().startswith("https://"):
        context = _https_context()
        if context is not None:
            kwargs["context"] = context
    with urlopen(req, timeout=120, **kwargs) as resp, open(dest, "wb") as handle:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)


def _safe_id(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip()).strip("-")
    return text or "item"


def _optional_int_from_payload(payload: Dict[str, Any], prev: Dict[str, Any], key: str) -> Optional[int]:
    if key in payload:
        raw = payload.get(key)
        if raw is None:
            return None
        text = str(raw).strip()
        if not text:
            return None
        return int(text)
    if key in prev:
        raw = prev.get(key)
        if raw is None:
            return None
        text = str(raw).strip()
        if not text:
            return None
        return int(text)
    return None


def _optional_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "none":
        return None
    return int(value)


def _coerce_optional_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text or text == "none":
        return None
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    return None


def _optional_bool_from_payload(payload: Dict[str, Any], prev: Dict[str, Any], key: str) -> Optional[bool]:
    if key in payload:
        return _coerce_optional_bool(payload.get(key))
    if key in prev:
        return _coerce_optional_bool(prev.get(key))
    return None


def _split_lines(text: str) -> List[str]:
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]


def _parse_int_list_csv(value: Any) -> List[int]:
    text = str(value or "").strip()
    if not text:
        return []
    out: List[int] = []
    for part in text.split(","):
        token = str(part or "").strip()
        if not token:
            continue
        try:
            out.append(int(token))
        except Exception:
            continue
    return out


def _parse_float_list_csv(value: Any) -> List[float]:
    text = str(value or "").strip()
    if not text:
        return []
    out: List[float] = []
    for part in text.split(","):
        token = str(part or "").strip()
        if not token:
            continue
        try:
            out.append(float(token))
        except Exception:
            continue
    return out


def _sanitize_probe_line(text: str) -> str:
    line = str(text or "").strip()
    if not line:
        return ""
    prefixes = (
        "load_backend: loaded RPC backend from ",
        "load_backend: loaded Vulkan backend from ",
        "load_backend: loaded SYCL backend from ",
        "load_backend: loaded CUDA backend from ",
        "load_backend: loaded Metal backend from ",
        "load_backend: loaded OpenCL backend from ",
        "load_backend: loaded CPU backend from ",
    )
    for prefix in prefixes:
        if line.startswith(prefix):
            return prefix + Path(line[len(prefix):].strip()).name
    return line


def _sanitize_probe_lines(lines: List[str]) -> List[str]:
    out: List[str] = []
    for line in lines:
        clean = _sanitize_probe_line(line)
        if clean:
            out.append(clean)
    return out


def _extract_device_lines(lines: List[str]) -> List[str]:
    in_devices = False
    out: List[str] = []
    for raw in lines:
        line = str(raw or "").strip()
        if not line:
            continue
        lower = line.lower()
        if lower == "available devices:":
            in_devices = True
            continue
        if in_devices:
            if re.match(r"^[A-Za-z]+[0-9]+:\s+", line):
                out.append(line)
                continue
            if out:
                break
    if out:
        return out
    return [line for line in lines if re.match(r"^[A-Za-z]+[0-9]+:\s+", str(line or "").strip())]


def _parse_device_index(line: str) -> Optional[int]:
    match = re.match(r"^[A-Za-z]+([0-9]+):", str(line or "").strip())
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _parse_device_memory(line: str) -> Dict[str, Optional[int]]:
    text = str(line or "").strip()
    match = re.search(r"\((\d+)\s+MiB,\s+(\d+)\s+MiB free\)", text)
    if not match:
        return {"total_bytes": None, "free_bytes": None, "used_bytes": None}
    try:
        total_mib = int(match.group(1))
        free_mib = int(match.group(2))
    except Exception:
        return {"total_bytes": None, "free_bytes": None, "used_bytes": None}
    total_bytes = total_mib * 1024 * 1024
    free_bytes = free_mib * 1024 * 1024
    used_bytes = max(0, total_bytes - free_bytes)
    return {"total_bytes": total_bytes, "free_bytes": free_bytes, "used_bytes": used_bytes}


def _process_memory_bytes(pid: int) -> Dict[str, Optional[int]]:
    out = {
        "working_set_bytes": None,
        "private_bytes": None,
    }
    if int(pid or 0) <= 0:
        return out
    try:
        if os.name == "nt":
            class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.c_ulong),
                    ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                    ("PrivateUsage", ctypes.c_size_t),
                ]

            PROCESS_QUERY_INFORMATION = 0x0400
            PROCESS_VM_READ = 0x0010
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, int(pid))
            if not handle:
                return out
            try:
                counters = PROCESS_MEMORY_COUNTERS_EX()
                counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS_EX)
                ok = ctypes.windll.psapi.GetProcessMemoryInfo(
                    handle,
                    ctypes.byref(counters),
                    counters.cb,
                )
                if ok:
                    out["working_set_bytes"] = int(counters.WorkingSetSize)
                    out["private_bytes"] = int(counters.PrivateUsage)
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
            return out

        proc = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(int(pid))],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=5,
        )
        text = str(proc.stdout or "").strip()
        if text:
            out["working_set_bytes"] = int(text) * 1024
        try:
            smaps_rollup = Path(f"/proc/{int(pid)}/smaps_rollup")
            if smaps_rollup.is_file():
                private_kib = 0
                for line in smaps_rollup.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if line.startswith("Private_Clean:") or line.startswith("Private_Dirty:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            private_kib += int(parts[1])
                if private_kib > 0:
                    out["private_bytes"] = private_kib * 1024
        except Exception:
            pass
        return out
    except Exception:
        return out


def _system_memory_bytes() -> Dict[str, Optional[int]]:
    out = {
        "system_total_bytes": None,
        "system_available_bytes": None,
    }
    try:
        if os.name == "nt":
            proc = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    (
                        "$os = Get-CimInstance Win32_OperatingSystem; "
                        "if ($os) { "
                        "[Console]::WriteLine(($os.TotalVisibleMemorySize.ToString() + ',' + $os.FreePhysicalMemory.ToString())) "
                        "}"
                    ),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
                timeout=5,
                **_windows_hidden_subprocess_kwargs(),
            )
            text = str(proc.stdout or "").strip()
            if text:
                parts = [p.strip() for p in text.split(",", 1)]
                if len(parts) >= 1 and parts[0]:
                    out["system_total_bytes"] = int(parts[0]) * 1024
                if len(parts) >= 2 and parts[1]:
                    out["system_available_bytes"] = int(parts[1]) * 1024
            return out

        meminfo = Path("/proc/meminfo")
        if meminfo.is_file():
            total_kib = None
            avail_kib = None
            for line in meminfo.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("MemTotal:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        total_kib = int(parts[1])
                elif line.startswith("MemAvailable:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        avail_kib = int(parts[1])
                if total_kib is not None and avail_kib is not None:
                    break
            if total_kib is not None:
                out["system_total_bytes"] = total_kib * 1024
            if avail_kib is not None:
                out["system_available_bytes"] = avail_kib * 1024
    except Exception:
        return out
    return out


def _parse_size_to_bytes(text: str) -> Optional[int]:
    raw = str(text or "").strip()
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(KiB|MiB|GiB|TiB|B)\b", raw, re.IGNORECASE)
    if not match:
        return None
    try:
        value = float(match.group(1))
    except Exception:
        return None
    unit = match.group(2).lower()
    scale = {
        "b": 1,
        "kib": 1024,
        "mib": 1024 * 1024,
        "gib": 1024 * 1024 * 1024,
        "tib": 1024 * 1024 * 1024 * 1024,
    }.get(unit)
    if not scale:
        return None
    try:
        return int(value * scale)
    except Exception:
        return None


def _parse_log_buffer_breakdown(log_path: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "cpu_mapped_model_bytes": None,
        "gpu_model_bytes": None,
        "gpu_model_label": None,
        "cpu_kv_bytes": None,
        "gpu_kv_bytes": None,
        "gpu_kv_label": None,
        "cpu_compute_bytes": None,
        "gpu_compute_bytes": None,
        "gpu_compute_label": None,
    }
    try:
        if not log_path.is_file():
            return out
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return out

    for line in reversed(lines):
        text = str(line or "").strip()
        if out["cpu_mapped_model_bytes"] is None:
            m = re.search(r"CPU_Mapped model buffer size\s*=\s*(.+)$", text)
            if m:
                out["cpu_mapped_model_bytes"] = _parse_size_to_bytes(m.group(1))
                continue
        if out["gpu_model_bytes"] is None:
            m = re.search(r"([^:]+?) model buffer size\s*=\s*(.+)$", text)
            if m and "CPU_Mapped" not in m.group(1):
                out["gpu_model_label"] = str(m.group(1)).strip()
                out["gpu_model_bytes"] = _parse_size_to_bytes(m.group(2))
                continue
        if out["cpu_kv_bytes"] is None:
            m = re.search(r"CPU KV buffer size\s*=\s*(.+)$", text)
            if m:
                out["cpu_kv_bytes"] = _parse_size_to_bytes(m.group(1))
                continue
        if out["gpu_kv_bytes"] is None:
            m = re.search(r"([^:]+?) KV buffer size\s*=\s*(.+)$", text)
            if m and "CPU" not in m.group(1):
                out["gpu_kv_label"] = str(m.group(1)).strip()
                out["gpu_kv_bytes"] = _parse_size_to_bytes(m.group(2))
                continue
        if out["cpu_compute_bytes"] is None:
            m = re.search(r"CPU compute buffer size\s*=\s*(.+)$", text)
            if m:
                out["cpu_compute_bytes"] = _parse_size_to_bytes(m.group(1))
                continue
        if out["gpu_compute_bytes"] is None:
            m = re.search(r"([^:]+?) compute buffer size\s*=\s*(.+)$", text)
            if m and "CPU" not in m.group(1):
                out["gpu_compute_label"] = str(m.group(1)).strip()
                out["gpu_compute_bytes"] = _parse_size_to_bytes(m.group(2))
                continue
        if all(
            out.get(key) is not None
            for key in ("cpu_mapped_model_bytes", "gpu_model_bytes", "gpu_kv_bytes", "gpu_compute_bytes")
        ):
            break
    return out


def _listener_pids_for_port(port: int) -> List[int]:
    out: List[int] = []
    try:
        if os.name == "nt":
            proc = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
                timeout=10,
                **_windows_hidden_subprocess_kwargs(),
            )
            for raw in str(proc.stdout or "").splitlines():
                line = raw.strip()
                if not line or "LISTENING" not in line:
                    continue
                parts = re.split(r"\s+", line)
                if len(parts) < 5:
                    continue
                local_addr = str(parts[1] or "")
                if not local_addr.endswith(f":{int(port)}"):
                    continue
                try:
                    pid = int(parts[-1])
                except Exception:
                    continue
                if pid > 0 and pid not in out:
                    out.append(pid)
            return out
        if shutil.which("lsof"):
            proc = subprocess.run(
                ["lsof", "-nP", f"-iTCP:{int(port)}", "-sTCP:LISTEN", "-t"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
                timeout=10,
            )
            for raw in str(proc.stdout or "").splitlines():
                try:
                    pid = int(raw.strip())
                except Exception:
                    continue
                if pid > 0 and pid not in out:
                    out.append(pid)
            if out:
                return out
        proc = subprocess.run(
            ["sh", "-lc", f"ss -ltnp '( sport = :{int(port)} )' || true"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=10,
        )
        for raw in str(proc.stdout or "").splitlines():
            match = re.search(r"pid=(\d+)", raw)
            if not match:
                continue
            try:
                pid = int(match.group(1))
            except Exception:
                continue
            if pid > 0 and pid not in out:
                out.append(pid)
    except Exception:
        return []
    return out


def _tail_text(path: Path, limit: int = 4000) -> str:
    try:
        raw = path.read_bytes()
    except Exception:
        return ""
    if len(raw) > limit:
        raw = raw[-limit:]
    return raw.replace(b"\x00", b"").decode("utf-8", errors="ignore").strip()


def _in_docker() -> bool:
    if os.path.exists("/.dockerenv"):
        return True
    try:
        text = Path("/proc/1/cgroup").read_text(encoding="utf-8", errors="ignore")
        return "docker" in text or "containerd" in text
    except Exception:
        return False


class LlamaServerHostManager:
    def __init__(self, root_dir: str) -> None:
        self.root = Path(root_dir).resolve()
        self.base_dir = self.root / "llama_server"
        self.downloads_dir = self.base_dir / "downloads"
        self.installs_dir = self.base_dir / "installs"
        self.logs_dir = self.base_dir / "logs"
        self.token_path = self.base_dir / "shared_token.json"
        self.state_path = self.base_dir / "state.json"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.installs_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._device_probe_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
        self._host_caps_cache: Optional[tuple[float, Dict[str, Any]]] = None
        self._system_mem_cache: Optional[tuple[float, Dict[str, Any]]] = None
        self._server_status_cache: Dict[str, tuple[float, Dict[str, Any], str]] = {}
        self.ensure_shared_token()

    def _cached_capabilities(self, *, max_age: float = 60.0) -> Dict[str, Any]:
        now = time.time()
        cached = self._host_caps_cache
        if cached and (now - float(cached[0] or 0.0)) < max_age:
            return dict(cached[1] or {})
        value = self._detect_capabilities()
        self._host_caps_cache = (now, dict(value or {}))
        return dict(value or {})

    def _cached_system_memory(self, *, max_age: float = 5.0) -> Dict[str, Any]:
        now = time.time()
        cached = self._system_mem_cache
        if cached and (now - float(cached[0] or 0.0)) < max_age:
            return dict(cached[1] or {})
        value = _system_memory_bytes()
        self._system_mem_cache = (now, dict(value or {}))
        return dict(value or {})

    def _server_status_sig(self, cfg: Dict[str, Any], *, lightweight: bool) -> str:
        parts = [
            str(cfg.get("id") or ""),
            str(cfg.get("pid") or ""),
            str(cfg.get("host") or ""),
            str(cfg.get("port") or ""),
            str(cfg.get("main_gpu") or ""),
            str(cfg.get("install_id") or ""),
            str(cfg.get("runtime_id") or ""),
            str(cfg.get("started_at") or ""),
            str(cfg.get("stopped_at") or ""),
            "light" if lightweight else "full",
        ]
        return "|".join(parts)

    def _cached_server_status(self, cfg: Dict[str, Any], *, lightweight: bool, max_age: float = 2.0) -> Optional[Dict[str, Any]]:
        key = str(cfg.get("id") or "")
        if not key:
            return None
        now = time.time()
        cached = self._server_status_cache.get(key)
        sig = self._server_status_sig(cfg, lightweight=lightweight)
        if cached and cached[2] == sig and (now - float(cached[0] or 0.0)) < max_age:
            return dict(cached[1] or {})
        return None

    def _store_server_status(self, cfg: Dict[str, Any], payload: Dict[str, Any], *, lightweight: bool) -> None:
        key = str(cfg.get("id") or "")
        if not key:
            return
        self._server_status_cache[key] = (time.time(), dict(payload or {}), self._server_status_sig(cfg, lightweight=lightweight))

    def _load_state(self) -> Dict[str, Any]:
        if not self.state_path.is_file():
            return {"installs": {}, "servers": {}}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return {"installs": {}, "servers": {}}

    def _save_state(self, state: Dict[str, Any]) -> None:
        payload = json.dumps(state, indent=2, sort_keys=True)
        tmp_path = self.state_path.with_suffix(".state.tmp")
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(self.state_path)

    def ensure_shared_token(self) -> str:
        if self.token_path.is_file():
            try:
                data = json.loads(self.token_path.read_text(encoding="utf-8"))
                token = str((data or {}).get("token") or "").strip()
                if token:
                    return token
            except Exception:
                pass
        token = secrets.token_urlsafe(32)
        self.token_path.write_text(json.dumps({"token": token, "updated_at": _now_ts()}, indent=2), encoding="utf-8")
        return token

    def get_shared_token(self) -> Dict[str, Any]:
        token = self.ensure_shared_token()
        return {"ok": True, "token": token, "updated_at": _now_ts()}

    def rekey_shared_token(self) -> Dict[str, Any]:
        token = secrets.token_urlsafe(32)
        self.token_path.write_text(json.dumps({"token": token, "updated_at": _now_ts()}, indent=2), encoding="utf-8")
        return {"ok": True, "token": token, "updated_at": _now_ts()}

    def _host_os(self) -> str:
        name = platform.system().strip().lower()
        if name.startswith("win"):
            return "windows"
        if name == "darwin":
            return "macos"
        if name == "linux":
            return "linux"
        return name or "unknown"

    def _run_hidden_kwargs(self) -> Dict[str, Any]:
        return _windows_hidden_subprocess_kwargs()

    def _gpu_names(self) -> List[str]:
        names: List[str] = []
        host_os = self._host_os()
        try:
            if host_os == "windows":
                proc = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    check=False,
                    timeout=10,
                    **self._run_hidden_kwargs(),
                )
                names = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
            elif host_os == "linux":
                proc = subprocess.run(
                    ["sh", "-lc", "lspci | grep -Ei 'vga|3d|display'"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    check=False,
                    timeout=10,
                )
                for line in (proc.stdout or "").splitlines():
                    line = line.strip()
                    if line:
                        names.append(line)
        except Exception:
            pass
        if not names:
            try:
                proc = subprocess.run(
                    ["nvidia-smi", "-L"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    check=False,
                    timeout=10,
                    **self._run_hidden_kwargs(),
                )
                for line in (proc.stdout or "").splitlines():
                    line = line.strip()
                    if line:
                        names.append(line)
            except Exception:
                pass
        return names

    def _detect_capabilities(self) -> Dict[str, Any]:
        host_os = self._host_os()
        gpus = self._gpu_names()
        blob = " | ".join(gpus).lower()
        has_nvidia = "nvidia" in blob or "geforce" in blob or "rtx" in blob
        has_amd = "amd" in blob or "radeon" in blob
        has_intel = "intel" in blob or "arc" in blob
        is_arc_pro_b = "arc pro b" in blob
        is_arc_b = ("arc b" in blob) and not is_arc_pro_b
        runtimes = [
            {
                "id": "cpu",
                "label": "CPU",
                "compatible": True,
                "reason": f"Supported on {host_os}.",
            },
            {
                "id": "vulkan",
                "label": "Vulkan",
                "compatible": host_os in ("windows", "linux"),
                "reason": (
                    "Download available on Windows or Linux. Running it still requires a Vulkan-capable GPU."
                    if host_os in ("windows", "linux")
                    else "Vulkan runtime downloads are only supported on Windows or Linux."
                ),
            },
            {
                "id": "sycl",
                "label": "SYCL",
                "compatible": host_os in ("windows", "linux") and has_intel,
                "reason": "Requires an Intel GPU on Windows or Linux.",
            },
            {
                "id": "cuda",
                "label": "CUDA",
                "compatible": host_os in ("windows", "linux") and has_nvidia,
                "reason": "Requires an NVIDIA GPU.",
            },
        ]
        sriov = {
            "compatible": bool(is_arc_pro_b),
            "reason": (
                "Intel states Arc Pro B-Series supports SR-IOV with Arc Pro driver 32.0.101.8306 or newer."
                if is_arc_pro_b
                else (
                    "Intel states Arc B-Series (non-Pro) does not support SR-IOV."
                    if is_arc_b
                    else ""
                )
            ),
        }
        return {
            "host_os": host_os,
            "arch": platform.machine(),
            "gpu_names": gpus,
            "runtimes": runtimes,
            "sriov": sriov,
        }

    def _asset_filters(self, runtime_id: str) -> Dict[str, List[str]]:
        host_os = self._host_os()
        if host_os == "windows":
            host_any = ["win", "windows"]
            arch_any = ["x64", "amd64"]
        elif host_os == "linux":
            host_any = ["linux", "ubuntu"]
            arch_any = ["x64", "amd64"]
        elif host_os == "macos":
            host_any = ["macos", "darwin", "osx"]
            machine = platform.machine().lower()
            if machine in ("arm64", "aarch64"):
                arch_any = ["arm64", "aarch64", "apple-silicon"]
            else:
                arch_any = ["x64", "x86_64", "amd64"]
        else:
            return {"required_all": [], "required_any_groups": [], "excluded": []}

        excluded = ["vulkan", "sycl", "cuda", "metal"]
        if host_os == "macos":
            excluded = ["vulkan", "sycl", "cuda", "ubuntu", "linux", "win", "windows", "android", "ios"]
        if runtime_id == "cpu":
            if host_os == "linux":
                excluded = [*excluded, "openvino"]
            return {
                "required_all": [],
                "required_any_groups": [host_any, arch_any],
                "excluded": excluded,
            }
        return {
            "required_all": [runtime_id],
            "required_any_groups": [host_any, arch_any],
            "excluded": [x for x in excluded if x != runtime_id],
        }

    def _pick_asset(self, release: Dict[str, Any], runtime_id: str) -> Dict[str, Any]:
        assets = release.get("assets") or []
        filters = self._asset_filters(runtime_id)
        host_os = self._host_os()
        candidates: List[Dict[str, Any]] = []
        diagnostics: List[str] = []
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name") or "").lower()
            if host_os == "windows" and not name.endswith(".zip"):
                continue
            if host_os == "linux" and not any(name.endswith(ext) for ext in (".zip", ".tar.gz", ".tgz")):
                continue
            if host_os == "macos" and not any(name.endswith(ext) for ext in (".zip", ".tar.gz", ".tgz")):
                continue
            required_all = list(filters.get("required_all") or [])
            required_any_groups = list(filters.get("required_any_groups") or [])
            excluded = list(filters.get("excluded") or [])
            if any(token in name for token in excluded):
                diagnostics.append(f"skip excluded:{name}")
                continue
            if not all(token in name for token in required_all):
                diagnostics.append(f"skip required_all:{name}")
                continue
            ok = True
            for group in required_any_groups:
                if not any(token in name for token in group):
                    ok = False
                    diagnostics.append(f"skip required_any:{name}")
                    break
            if ok:
                candidates.append(asset)
        if not candidates:
            sample = ", ".join(str((a or {}).get("name") or "") for a in assets[:10] if isinstance(a, dict))
            raise RuntimeError(
                f"No release asset found for runtime={runtime_id} on {host_os}. "
                f"Sample assets: {sample}"
            )
        return candidates[0]

    def list_status(self, *, lightweight: bool = False) -> Dict[str, Any]:
        state = self._load_state()
        caps = self._cached_capabilities()
        installs = state.get("installs") if isinstance(state.get("installs"), dict) else {}
        servers = state.get("servers") if isinstance(state.get("servers"), dict) else {}
        server_items: List[Dict[str, Any]] = []
        dirty = False
        for server_id, cfg in servers.items():
            item = dict(cfg or {})
            item["id"] = server_id
            runtime = self._server_runtime_status(item, lightweight=lightweight)
            item.update(runtime)
            if item.get("pid") and not runtime.get("running") and not runtime.get("process_alive"):
                item.pop("pid", None)
                servers[server_id] = item
                dirty = True
            server_items.append(item)
        install_items = []
        for install_id, item in installs.items():
            row = dict(item or {})
            row["id"] = install_id
            install_items.append(row)
        if dirty:
            self._save_state(state)
        return {
            "ok": True,
            "host": caps,
            "installs": install_items,
            "servers": server_items,
            "lightweight": bool(lightweight),
        }

    def install_release(self, runtime_id: str, tag: str = "latest") -> Dict[str, Any]:
        runtime_id = str(runtime_id or "").strip().lower()
        if runtime_id not in ("cpu", "vulkan", "sycl", "cuda"):
            raise RuntimeError("runtime_id must be cpu, vulkan, sycl, or cuda")
        rel_url = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
        if tag and tag.lower() != "latest":
            rel_url = f"https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/{tag}"
        release = _json_url(rel_url)
        asset = self._pick_asset(release, runtime_id)
        tag_name = str(release.get("tag_name") or tag or "latest")
        asset_name = str(asset.get("name") or "")
        dl_url = str(asset.get("browser_download_url") or "")
        if not asset_name or not dl_url:
            raise RuntimeError("Release asset missing name or download URL")
        install_id = _safe_id(f"{tag_name}-{runtime_id}-{self._host_os()}")
        archive_path = self.downloads_dir / asset_name
        extract_dir = self.installs_dir / install_id
        extract_dir.mkdir(parents=True, exist_ok=True)
        _download_file(dl_url, archive_path)
        self._extract_archive(archive_path, extract_dir)
        exe_path = self._find_server_executable(extract_dir, archive_name=asset_name)
        state = self._load_state()
        installs = state.setdefault("installs", {})
        installs[install_id] = {
            "runtime_id": runtime_id,
            "tag": tag_name,
            "asset_name": asset_name,
            "archive_path": str(archive_path),
            "extract_dir": str(extract_dir),
            "executable": str(exe_path),
            "installed_at": _now_ts(),
        }
        self._save_state(state)
        return {"ok": True, "install_id": install_id, "install": installs[install_id]}

    def _extract_archive(self, archive_path: Path, extract_dir: Path) -> None:
        if archive_path.suffix.lower() == ".zip":
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(extract_dir)
            return
        if archive_path.name.lower().endswith((".tar.gz", ".tgz")):
            with tarfile.open(archive_path, "r:gz") as tf:
                tf.extractall(extract_dir)
            return
        shutil.unpack_archive(str(archive_path), str(extract_dir))

    def _find_server_executable(self, root: Path, *, archive_name: str = "") -> Path:
        candidates = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            low = path.name.lower()
            if low == "llama-server.exe" or low == "llama-server":
                candidates.append(path)
        if not candidates:
            sample = []
            for path in root.rglob("*"):
                if path.is_file():
                    sample.append(str(path.relative_to(root)))
                if len(sample) >= 25:
                    break
            sample_text = ", ".join(sample) if sample else "(no files)"
            source = f" from {archive_name}" if archive_name else ""
            raise RuntimeError(f"llama-server executable not found in extracted package{source}. Extracted files: {sample_text}")
        candidates.sort(key=lambda p: len(str(p)))
        return candidates[0]

    def _find_named_executable(self, root: Path, names: List[str]) -> Optional[Path]:
        want = {str(name).lower() for name in names}
        candidates: List[Path] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.name.lower() in want:
                candidates.append(path)
        if not candidates:
            return None
        candidates.sort(key=lambda p: len(str(p)))
        return candidates[0]

    def _run_probe_command(self, cmd: List[str], cwd: Optional[str] = None) -> Dict[str, Any]:
        proc = subprocess.run(
            cmd,
            cwd=cwd or None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=20,
            **self._run_hidden_kwargs(),
        )
        lines = _split_lines(proc.stdout or "")
        return {
            "ok": proc.returncode == 0 and bool(lines),
            "returncode": int(proc.returncode),
            "lines": lines,
            "command": cmd,
        }

    def probe_devices(self, *, install_id: str = "", runtime_id: str = "") -> Dict[str, Any]:
        cache_key = f"{str(install_id or '').strip()}::{str(runtime_id or '').strip().lower()}"
        now = time.time()
        cached = self._device_probe_cache.get(cache_key)
        if cached and (now - float(cached[0] or 0.0)) < 15.0:
            return dict(cached[1] or {})
        state = self._load_state()
        installs = state.get("installs") if isinstance(state.get("installs"), dict) else {}
        install: Dict[str, Any] = {}
        selected_install_id = str(install_id or "").strip()
        if selected_install_id:
            install = dict(installs.get(selected_install_id) or {})
        elif runtime_id:
            matches = []
            for iid, item in installs.items():
                row = dict(item or {})
                if str(row.get("runtime_id") or "").strip().lower() == str(runtime_id or "").strip().lower():
                    row["id"] = iid
                    matches.append(row)
            matches.sort(key=lambda x: int(x.get("installed_at") or 0), reverse=True)
            if matches:
                install = matches[0]
                selected_install_id = str(install.get("id") or "").strip()
        else:
            matches = []
            for iid, item in installs.items():
                row = dict(item or {})
                row["id"] = iid
                matches.append(row)
            matches.sort(key=lambda x: int(x.get("installed_at") or 0), reverse=True)
            if matches:
                install = matches[0]
                selected_install_id = str(install.get("id") or "").strip()
        if not install:
            return {"ok": False, "error": "No installed llama.cpp runtime available for probing"}

        runtime = str(install.get("runtime_id") or runtime_id or "").strip().lower()
        exe = Path(str(install.get("executable") or "")).resolve()
        extract_dir = Path(str(install.get("extract_dir") or exe.parent)).resolve()
        if not exe.is_file():
            return {"ok": False, "error": "Installed executable not found", "install_id": selected_install_id}

        attempts: List[Dict[str, Any]] = []
        probe_cmds: List[List[str]] = [[str(exe), "--list-devices"]]

        if runtime == "sycl":
            sycl_probe = self._find_named_executable(extract_dir, ["llama-ls-sycl-device.exe", "llama-ls-sycl-device"])
            if sycl_probe is not None:
                probe_cmds.insert(0, [str(sycl_probe)])
            probe_cmds.append(["sycl-ls"])

        for cmd in probe_cmds:
            try:
                result = self._run_probe_command(cmd, cwd=str(extract_dir))
            except Exception as exc:
                attempts.append({"ok": False, "command": [Path(str(cmd[0])).name, *[str(x) for x in cmd[1:]]], "error": str(exc), "lines": []})
                continue
            result["command"] = [Path(str(cmd[0])).name, *[str(x) for x in cmd[1:]]]
            attempts.append(result)
            if result.get("ok"):
                lines = _sanitize_probe_lines(list(result.get("lines") or []))
                devices = _extract_device_lines(lines)
                out = {
                    "ok": True,
                    "install_id": selected_install_id,
                    "runtime_id": runtime,
                    "source": Path(cmd[0]).name,
                    "command": [Path(str(cmd[0])).name, *[str(x) for x in cmd[1:]]],
                    "lines": devices or lines,
                    "devices": devices,
                }
                self._device_probe_cache[cache_key] = (now, out)
                return out
        result = {
            "ok": False,
            "install_id": selected_install_id,
            "runtime_id": runtime,
            "error": "No device probe command succeeded",
            "attempts": attempts,
        }
        self._device_probe_cache[cache_key] = (now, result)
        return result

    def upsert_server(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        state = self._load_state()
        servers = state.setdefault("servers", {})
        server_id = _safe_id(str(payload.get("id") or payload.get("name") or f"server-{len(servers)+1}"))
        prev = dict(servers.get(server_id) or {})
        cfg = {
            "name": str(payload.get("name") or prev.get("name") or server_id),
            "runtime_id": str(payload.get("runtime_id") or prev.get("runtime_id") or "cpu").strip().lower(),
            "install_id": str(payload.get("install_id") or prev.get("install_id") or "").strip(),
            "model_path": str(payload.get("model_path") or prev.get("model_path") or "").strip(),
            "host": str(payload.get("host") or prev.get("host") or "127.0.0.1").strip(),
            "port": int(payload.get("port") or prev.get("port") or 8080),
            "ctx_size": _optional_int_from_payload(payload, prev, "ctx_size"),
            "n_gpu_layers": _optional_int_from_payload(payload, prev, "n_gpu_layers"),
            "parallel_slots": _optional_int_from_payload(payload, prev, "parallel_slots"),
            "batch_size": _optional_int_from_payload(payload, prev, "batch_size"),
            "ubatch_size": _optional_int_from_payload(payload, prev, "ubatch_size"),
            "n_threads": _optional_int_from_payload(payload, prev, "n_threads"),
            "threads_batch": _optional_int_from_payload(payload, prev, "threads_batch"),
            "main_gpu": _optional_int_from_payload(payload, prev, "main_gpu"),
            "gpu_selection_mode": str(payload.get("gpu_selection_mode") or prev.get("gpu_selection_mode") or "auto").strip().lower(),
            "gpu_split_mode": str(payload.get("gpu_split_mode") or prev.get("gpu_split_mode") or "layer").strip().lower(),
            "gpu_split_devices": str(payload.get("gpu_split_devices") or prev.get("gpu_split_devices") or "").strip(),
            "gpu_split_percent": str(payload.get("gpu_split_percent") or prev.get("gpu_split_percent") or "").strip(),
            "offload_kqv": _optional_bool_from_payload(payload, prev, "offload_kqv"),
            "type_k": str(payload.get("type_k") or prev.get("type_k") or "").strip(),
            "type_v": str(payload.get("type_v") or prev.get("type_v") or "").strip(),
            "flash_attn": _optional_bool_from_payload(payload, prev, "flash_attn"),
            "kv_unified": _optional_bool_from_payload(payload, prev, "kv_unified"),
            "no_host": _optional_bool_from_payload(payload, prev, "no_host"),
            "cache_ram": _optional_int_from_payload(payload, prev, "cache_ram"),
            "mmap": _optional_bool_from_payload(payload, prev, "mmap"),
            "cont_batching": _optional_bool_from_payload(payload, prev, "cont_batching"),
            "ctx_checkpoints": _optional_int_from_payload(payload, prev, "ctx_checkpoints"),
            "emit_thinking": _optional_bool_from_payload(payload, prev, "emit_thinking"),
            "device_filter": str(payload.get("device_filter") or prev.get("device_filter") or "").strip(),
            "extra_args": str(payload.get("extra_args") or prev.get("extra_args") or "").strip(),
            "sriov_vf": str(payload.get("sriov_vf") or prev.get("sriov_vf") or "").strip(),
            "updated_at": _now_ts(),
        }
        if prev.get("pid"):
            cfg["pid"] = prev.get("pid")
        servers[server_id] = cfg
        self._save_state(state)
        return {"ok": True, "server_id": server_id, "server": {"id": server_id, **cfg}}

    def delete_server(self, server_id: str) -> Dict[str, Any]:
        state = self._load_state()
        servers = state.setdefault("servers", {})
        item = dict(servers.get(server_id) or {})
        if item.get("pid"):
            self.stop_server(server_id)
            state = self._load_state()
            servers = state.setdefault("servers", {})
        removed = servers.pop(server_id, None)
        self._save_state(state)
        return {"ok": True, "removed": bool(removed)}

    def start_server(
        self,
        server_id: str,
        *,
        model_path: Optional[str] = None,
        model_relpath: Optional[str] = None,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        state = self._load_state()
        servers = state.setdefault("servers", {})
        installs = state.setdefault("installs", {})
        cfg = dict(servers.get(server_id) or {})
        base_cfg = dict(cfg)
        if not cfg:
            raise RuntimeError("Unknown server id")
        install = dict(installs.get(cfg.get("install_id")) or {})
        if not install:
            wanted_install_id = str(cfg.get("install_id") or "").strip()
            wanted_runtime_id = str(cfg.get("runtime_id") or "").strip().lower()
            recovered_install_id = ""
            recovered_install: Dict[str, Any] = {}
            candidate_dirs: List[Path] = []
            try:
                if self.installs_dir.is_dir():
                    candidate_dirs = [p for p in self.installs_dir.iterdir() if p.is_dir()]
            except Exception:
                candidate_dirs = []
            for root in candidate_dirs:
                try:
                    exe_candidate = self._find_server_executable(root)
                except Exception:
                    continue
                runtime_guess = wanted_runtime_id or ("vulkan" if "vulkan" in root.name.lower() else "")
                if wanted_install_id and root.name == wanted_install_id:
                    recovered_install_id = wanted_install_id
                    recovered_install = {
                        "runtime_id": runtime_guess or "cpu",
                        "tag": "recovered",
                        "asset_name": root.name,
                        "archive_path": "",
                        "extract_dir": str(root),
                        "executable": str(exe_candidate),
                        "installed_at": _now_ts(),
                        "recovered_at": _now_ts(),
                    }
                    break
                if not recovered_install and wanted_runtime_id and wanted_runtime_id in root.name.lower():
                    recovered_install_id = root.name
                    recovered_install = {
                        "runtime_id": wanted_runtime_id,
                        "tag": "recovered",
                        "asset_name": root.name,
                        "archive_path": "",
                        "extract_dir": str(root),
                        "executable": str(exe_candidate),
                        "installed_at": _now_ts(),
                        "recovered_at": _now_ts(),
                    }
            if recovered_install:
                install = dict(recovered_install)
                cfg["install_id"] = recovered_install_id
                installs[recovered_install_id] = dict(recovered_install)
                servers[server_id] = cfg
                self._save_state(state)
            else:
                raise RuntimeError("Unknown install_id")
        exe = Path(str(install.get("executable") or "")).resolve()
        if not exe.is_file():
            raise RuntimeError("llama-server executable not found")
        asset_name = str(install.get("asset_name") or "").strip().lower()
        if (
            str(cfg.get("runtime_id") or "").strip().lower() == "cpu"
            and self._host_os() == "linux"
            and "openvino" in asset_name
        ):
            raise RuntimeError(
                "The selected Linux CPU runtime is an OpenVINO build, and this host is not starting it reliably. "
                "Choose a non-OpenVINO CPU build if available, use embedded GGUF instead, or run a custom llama.cpp "
                "server binary built for this machine."
            )
        ov = dict(overrides or {})
        effective_model_path = ""
        effective_mmproj_path = ""
        if model_relpath:
            rel = str(model_relpath or "").replace("\\", "/").lstrip("/")
            effective_model_path = str((self.root / rel).resolve())
        else:
            effective_model_path = str(model_path or cfg.get("model_path") or "").strip()
        if "mmproj_relpath" in ov:
            mmproj_relpath = str(ov.get("mmproj_relpath") or "").strip()
            if mmproj_relpath:
                rel = mmproj_relpath.replace("\\", "/").lstrip("/")
                effective_mmproj_path = str((self.root / rel).resolve())
            else:
                effective_mmproj_path = ""
        else:
            effective_mmproj_path = str(cfg.get("mmproj_path") or "").strip()
        if not effective_model_path:
            raise RuntimeError("model_path required")
        cfg["model_path"] = effective_model_path
        cfg["effective_model_path"] = effective_model_path
        cfg["mmproj_path"] = effective_mmproj_path
        if "ctx_size" in ov:
            cfg["ctx_size"] = _optional_int(ov.get("ctx_size"))
        if "n_gpu_layers" in ov:
            cfg["n_gpu_layers"] = _optional_int(ov.get("n_gpu_layers"))
        if "parallel_slots" in ov:
            cfg["parallel_slots"] = _optional_int(ov.get("parallel_slots"))
        if "batch_size" in ov:
            cfg["batch_size"] = _optional_int(ov.get("batch_size"))
        if "ubatch_size" in ov:
            cfg["ubatch_size"] = _optional_int(ov.get("ubatch_size"))
        if "n_threads" in ov:
            cfg["n_threads"] = _optional_int(ov.get("n_threads"))
        if "threads_batch" in ov:
            cfg["threads_batch"] = _optional_int(ov.get("threads_batch"))
        if "main_gpu" in ov:
            cfg["main_gpu"] = _optional_int(ov.get("main_gpu"))
        if "gpu_selection_mode" in ov:
            cfg["gpu_selection_mode"] = str(ov.get("gpu_selection_mode") or "").strip().lower() or "auto"
        if "gpu_split_mode" in ov:
            cfg["gpu_split_mode"] = str(ov.get("gpu_split_mode") or "").strip().lower() or "layer"
        if "gpu_split_devices" in ov:
            cfg["gpu_split_devices"] = str(ov.get("gpu_split_devices") or "").strip()
        if "gpu_split_percent" in ov:
            cfg["gpu_split_percent"] = str(ov.get("gpu_split_percent") or "").strip()
        if "offload_kqv" in ov:
            cfg["offload_kqv"] = _coerce_optional_bool(ov.get("offload_kqv"))
        if "type_k" in ov:
            cfg["type_k"] = str(ov.get("type_k") or "").strip()
        if "type_v" in ov:
            cfg["type_v"] = str(ov.get("type_v") or "").strip()
        if "flash_attn" in ov:
            cfg["flash_attn"] = _coerce_optional_bool(ov.get("flash_attn"))
        if "kv_unified" in ov:
            cfg["kv_unified"] = _coerce_optional_bool(ov.get("kv_unified"))
        if "no_host" in ov:
            cfg["no_host"] = _coerce_optional_bool(ov.get("no_host"))
        if "cache_ram" in ov:
            cfg["cache_ram"] = _optional_int(ov.get("cache_ram"))
        if "mmap" in ov:
            cfg["mmap"] = _coerce_optional_bool(ov.get("mmap"))
        if "cont_batching" in ov:
            cfg["cont_batching"] = _coerce_optional_bool(ov.get("cont_batching"))
        if "ctx_checkpoints" in ov:
            cfg["ctx_checkpoints"] = _optional_int(ov.get("ctx_checkpoints"))
        if "emit_thinking" in ov:
            cfg["emit_thinking"] = _coerce_optional_bool(ov.get("emit_thinking"))
        if "device_filter" in ov:
            cfg["device_filter"] = str(ov["device_filter"] or "").strip()
        if "extra_args" in ov:
            cfg["extra_args"] = str(ov["extra_args"] or "").strip()
        desired_cfg = dict(cfg)
        selection_mode = str(cfg.get("gpu_selection_mode") or "auto").strip().lower()
        split_mode = str(cfg.get("gpu_split_mode") or "layer").strip().lower()
        raw_split_devices = _parse_int_list_csv(cfg.get("gpu_split_devices"))
        raw_split_percent = _parse_float_list_csv(cfg.get("gpu_split_percent"))
        split_devices = list(raw_split_devices) if selection_mode == "split" else []
        split_percent = list(raw_split_percent) if selection_mode == "split" else []
        main_gpu = cfg.get("main_gpu")
        chosen_main: Optional[int] = None
        if selection_mode == "split":
            if split_devices:
                chosen_main = split_devices[0]
            elif main_gpu is not None and str(main_gpu).strip() != "":
                try:
                    chosen_main = int(main_gpu)
                except Exception:
                    chosen_main = None
        elif selection_mode == "single":
            if main_gpu is not None and str(main_gpu).strip() != "":
                try:
                    chosen_main = int(main_gpu)
                except Exception:
                    chosen_main = None
        elif selection_mode != "auto" and main_gpu is not None and str(main_gpu).strip() != "":
            try:
                chosen_main = int(main_gpu)
            except Exception:
                chosen_main = None

        try:
            probe = self.probe_devices(
                install_id=str(cfg.get("install_id") or "").strip(),
                runtime_id=str(cfg.get("runtime_id") or "").strip().lower(),
            )
        except Exception:
            probe = {"ok": False}
        probed_device_lines = list((probe or {}).get("devices") or [])
        available_devices = [_parse_device_index(line) for line in probed_device_lines]
        available_devices = [idx for idx in available_devices if idx is not None]
        device_name_by_index: Dict[int, str] = {}
        for line in probed_device_lines:
            raw = str(line or "").strip()
            idx = _parse_device_index(raw)
            if idx is None:
                continue
            token = raw.split(":", 1)[0].strip()
            if token:
                device_name_by_index[int(idx)] = token
        if available_devices:
            available_set = set(int(idx) for idx in available_devices)
            if chosen_main is not None and int(chosen_main) not in available_set:
                raise RuntimeError(
                    f"main_gpu {chosen_main} is invalid for server '{server_id}' "
                    f"(available device ids: {', '.join(str(idx) for idx in sorted(available_set))})"
                )
            invalid_split = [idx for idx in split_devices if int(idx) not in available_set]
            if invalid_split:
                raise RuntimeError(
                    f"gpu_split_devices contains invalid ids for server '{server_id}': "
                    f"{', '.join(str(idx) for idx in invalid_split)} "
                    f"(available device ids: {', '.join(str(idx) for idx in sorted(available_set))})"
                )
        current_status = self._server_runtime_status(cfg)
        current_effective_model = str(cfg.get("effective_model_path") or cfg.get("model_path") or "").strip()
        cfg_change_keys = (
            "ctx_size",
            "n_gpu_layers",
            "parallel_slots",
            "batch_size",
            "ubatch_size",
            "n_threads",
            "threads_batch",
            "main_gpu",
            "gpu_selection_mode",
            "gpu_split_mode",
            "gpu_split_devices",
            "gpu_split_percent",
            "offload_kqv",
            "type_k",
            "type_v",
            "flash_attn",
            "kv_unified",
            "no_host",
            "cache_ram",
            "mmap",
            "cont_batching",
            "ctx_checkpoints",
            "emit_thinking",
            "device_filter",
            "extra_args",
            "mmproj_path",
        )
        config_changed = any(base_cfg.get(k) != desired_cfg.get(k) for k in cfg_change_keys)
        if current_status.get("running") and current_effective_model == effective_model_path and not config_changed:
            return {"ok": True, "server": {"id": server_id, **cfg}, "status": current_status, "reuse": True}

        current_listener_pids = _listener_pids_for_port(int(cfg.get("port") or 0))
        current_listener_pid = current_listener_pids[0] if current_listener_pids else 0
        current_or_listening_pid = int(current_status.get("pid") or current_listener_pid or 0)
        if (
            current_effective_model == effective_model_path
            and not config_changed
            and current_or_listening_pid > 0
        ):
            if not cfg.get("pid"):
                cfg["pid"] = current_or_listening_pid
                servers[server_id] = cfg
                self._save_state(state)
            current_status["pid"] = current_or_listening_pid
            current_status["process_alive"] = True
            return {
                "ok": True,
                "server": {"id": server_id, **cfg},
                "status": current_status,
                "reuse": True,
                "pending": not bool(current_status.get("running")),
            }

        running_pid = int(cfg.get("pid") or 0)
        if running_pid > 0 or current_status.get("process_alive") or current_status.get("running"):
            self.stop_server(server_id)
            state = self._load_state()
            servers = state.setdefault("servers", {})
            cfg = dict(servers.get(server_id) or {})
            cfg.update(desired_cfg)
            cfg["effective_model_path"] = effective_model_path
        configured_host = str(cfg.get("host") or "127.0.0.1").strip()
        listen_host = configured_host
        # The backend container reaches host-native llama-server through host.docker.internal,
        # so a loopback-only bind on the host is not reachable from the container.
        if configured_host.lower() in ("127.0.0.1", "localhost"):
            listen_host = "0.0.0.0"
        cmd = [
            str(exe),
            "-m",
            effective_model_path,
            "--host",
            listen_host,
            "--port",
            str(int(cfg.get("port") or 8080)),
        ]
        runtime_id = str(cfg.get("runtime_id") or "").strip().lower()
        host_os = self._host_os()
        if runtime_id == "cpu" and host_os == "linux":
            # Newer Linux "CPU" builds can auto-select OPENVINO backends and abort
            # on some hosts. Force plain CPU execution unless the server config
            # explicitly opts into device selection.
            selection_mode = str(cfg.get("gpu_selection_mode") or "auto").strip().lower()
            device_filter = str(cfg.get("device_filter") or "").strip()
            if selection_mode in ("", "auto") and not device_filter:
                cmd.extend(["--device", "none"])
            # Keep Linux CPU startups within reasonable memory on smaller machines
            # when the server config leaves llama.cpp defaults unset.
            if not cfg.get("ctx_size"):
                cfg["ctx_size"] = 2048
            if not cfg.get("batch_size"):
                cfg["batch_size"] = 256
            if not cfg.get("ubatch_size"):
                cfg["ubatch_size"] = 128
            if not cfg.get("parallel_slots"):
                cfg["parallel_slots"] = 1
            sys_mem = self._cached_system_memory()
            system_total_bytes = int(sys_mem.get("system_total_bytes") or 0)
            # On smaller Linux hosts, large saved llama.cpp defaults can push the
            # process straight into the OOM killer before the server becomes ready.
            # Cap the startup profile to a conservative baseline unless the user has
            # explicitly tuned with extra args or device selection.
            if system_total_bytes and system_total_bytes < (16 * 1024 * 1024 * 1024):
                extra_args = str(cfg.get("extra_args") or "").strip()
                if not extra_args and selection_mode in ("", "auto") and not device_filter:
                    try:
                        if int(cfg.get("ctx_size") or 0) > 2048:
                            cfg["ctx_size"] = 2048
                    except Exception:
                        cfg["ctx_size"] = 2048
                    try:
                        if int(cfg.get("batch_size") or 0) > 256:
                            cfg["batch_size"] = 256
                    except Exception:
                        cfg["batch_size"] = 256
                    try:
                        if int(cfg.get("ubatch_size") or 0) > 128:
                            cfg["ubatch_size"] = 128
                    except Exception:
                        cfg["ubatch_size"] = 128
                    try:
                        if int(cfg.get("parallel_slots") or 0) > 1:
                            cfg["parallel_slots"] = 1
                    except Exception:
                        cfg["parallel_slots"] = 1
        if effective_mmproj_path:
            cmd.extend(["--mmproj", effective_mmproj_path])
        ctx_size = cfg.get("ctx_size")
        if ctx_size and int(ctx_size) > 0:
            cmd.extend(["--ctx-size", str(int(ctx_size))])
        batch_size = cfg.get("batch_size")
        if batch_size and int(batch_size) > 0:
            cmd.extend(["--batch-size", str(int(batch_size))])
        ubatch_size = cfg.get("ubatch_size")
        if ubatch_size and int(ubatch_size) > 0:
            cmd.extend(["--ubatch-size", str(int(ubatch_size))])
        parallel_slots = cfg.get("parallel_slots")
        if parallel_slots and int(parallel_slots) > 0:
            cmd.extend(["--parallel", str(max(1, int(parallel_slots)))])
        n_threads = cfg.get("n_threads")
        if n_threads and int(n_threads) > 0:
            cmd.extend(["--threads", str(int(n_threads))])
        threads_batch = cfg.get("threads_batch")
        if threads_batch and int(threads_batch) > 0:
            cmd.extend(["--threads-batch", str(int(threads_batch))])
        ngl = int(cfg.get("n_gpu_layers") or 0)
        if ngl > 0:
            cmd.extend(["--n-gpu-layers", str(ngl)])
        explicit_devices: List[str] = []
        if selection_mode == "single" and chosen_main is not None:
            selected_name = device_name_by_index.get(int(chosen_main))
            if selected_name:
                explicit_devices = [selected_name]
                cmd.extend(["--device", ",".join(explicit_devices)])
                cmd.extend(["--main-gpu", "0"])
            else:
                cmd.extend(["--main-gpu", str(int(chosen_main))])
        elif selection_mode == "split":
            if split_devices:
                explicit_devices = [device_name_by_index.get(int(idx), "") for idx in split_devices]
                explicit_devices = [name for name in explicit_devices if name]
                if explicit_devices:
                    cmd.extend(["--device", ",".join(explicit_devices)])
            if chosen_main is not None:
                selected_main = 0 if explicit_devices else int(chosen_main)
                cmd.extend(["--main-gpu", str(selected_main)])
        elif selection_mode != "auto" and chosen_main is not None:
            cmd.extend(["--main-gpu", str(int(chosen_main))])
        if selection_mode == "split":
            if split_mode in ("none", "layer", "row"):
                cmd.extend(["--split-mode", split_mode])
            if split_percent:
                total = sum(x for x in split_percent if x > 0)
                if total > 0:
                    normalized = [str(round(max(0.0, x) / total, 6)).rstrip("0").rstrip(".") or "0" for x in split_percent]
                    cmd.extend(["--tensor-split", ",".join(normalized)])
        elif selection_mode == "single":
            # Force single-device placement. Without this, llama.cpp may still
            # distribute layers across multiple GPUs when more than one is visible.
            cmd.extend(["--split-mode", "none"])
        elif selection_mode != "auto":
            # Backward compatibility: if mode is unknown, honor legacy main_gpu.
            if main_gpu is not None and str(main_gpu).strip() != "":
                try:
                    cmd.extend(["--main-gpu", str(int(main_gpu))])
                except Exception:
                    pass
        if cfg.get("offload_kqv") is False:
            cmd.append("--no-kv-offload")
        type_k = str(cfg.get("type_k") or "").strip()
        if type_k:
            cmd.extend(["--cache-type-k", type_k])
        type_v = str(cfg.get("type_v") or "").strip()
        if type_v:
            cmd.extend(["--cache-type-v", type_v])
        flash_attn = _coerce_optional_bool(cfg.get("flash_attn"))
        if flash_attn is True:
            cmd.extend(["--flash-attn", "on"])
        elif flash_attn is False:
            cmd.extend(["--flash-attn", "off"])
        kv_unified = _coerce_optional_bool(cfg.get("kv_unified"))
        if kv_unified is True:
            cmd.append("--kv-unified")
        elif kv_unified is False:
            cmd.append("--no-kv-unified")
        no_host = _coerce_optional_bool(cfg.get("no_host"))
        if no_host is True:
            cmd.append("--no-host")
        cache_ram = cfg.get("cache_ram")
        if cache_ram is not None and str(cache_ram).strip() != "":
            try:
                cmd.extend(["--cache-ram", str(int(cache_ram))])
            except Exception:
                pass
        mmap = _coerce_optional_bool(cfg.get("mmap"))
        if mmap is True:
            cmd.append("--mmap")
        elif mmap is False:
            cmd.append("--no-mmap")
        cont_batching = _coerce_optional_bool(cfg.get("cont_batching"))
        if cont_batching is True:
            cmd.append("--cont-batching")
        elif cont_batching is False:
            cmd.append("--no-cont-batching")
        ctx_checkpoints = cfg.get("ctx_checkpoints")
        if ctx_checkpoints is not None and str(ctx_checkpoints).strip() != "":
            try:
                cmd.extend(["--ctx-checkpoints", str(int(ctx_checkpoints))])
            except Exception:
                pass
        emit_thinking = _coerce_optional_bool(cfg.get("emit_thinking"))
        if emit_thinking is False:
            cmd.extend(["--reasoning", "off"])
        extra_args = str(cfg.get("extra_args") or "").strip()
        if extra_args:
            extra_tokens = extra_args.split()
            if selection_mode == "single":
                # Strip split flags from custom args so they cannot override single mode.
                filtered = []
                skip_next = False
                for tok in extra_tokens:
                    if skip_next:
                        skip_next = False
                        continue
                    if tok in ("--split-mode", "--tensor-split"):
                        skip_next = True
                        continue
                    if tok.startswith("--split-mode=") or tok.startswith("--tensor-split="):
                        continue
                    filtered.append(tok)
                extra_tokens = filtered
            cmd.extend(extra_tokens)
        env = dict(os.environ)
        device_filter = str(cfg.get("device_filter") or "").strip()
        if device_filter:
            env["SYCL_DEVICE_FILTER"] = device_filter
            env["ONEAPI_DEVICE_SELECTOR"] = device_filter
        cwd = str(exe.parent)
        log_path = self.logs_dir / f"{server_id}.log"
        log_handle = open(log_path, "ab")
        try:
            log_handle.write((f"\n[llmloader2] starting llama-server: {' '.join(cmd)}\n").encode("utf-8", errors="ignore"))
            log_handle.flush()
        except Exception:
            pass
        kwargs: Dict[str, Any] = {
            "cwd": cwd,
            "stdout": log_handle,
            "stderr": log_handle,
            "stdin": subprocess.DEVNULL,
            "env": env,
            "close_fds": os.name != "nt",
        }
        if os.name == "nt":
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.DETACHED_PROCESS
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(cmd, **kwargs)
        log_handle.close()
        cfg["pid"] = proc.pid
        cfg["started_at"] = _now_ts()
        cfg["log_path"] = str(log_path)
        servers[server_id] = cfg
        self._save_state(state)
        ready_url = f"http://127.0.0.1:{int(cfg.get('port') or 8080)}"
        startup_timeout_s = 240.0 if runtime_id == "vulkan" else 120.0
        deadline = time.time() + startup_timeout_s
        last_error = ""
        while time.time() < deadline:
            exit_code = proc.poll()
            if exit_code is not None:
                log_tail = _tail_text(log_path)
                raise RuntimeError(
                    f"llama-server exited during startup (code {exit_code})."
                    + (f" log tail: {log_tail}" if log_tail else "")
                )
            try:
                _json_url(f"{ready_url}/health")
                _json_url(f"{ready_url}/v1/models")
                return {"ok": True, "server": {"id": server_id, **cfg}, "status": self._server_runtime_status(cfg)}
            except Exception as exc:
                last_error = str(exc)
                time.sleep(0.5)
        log_tail = _tail_text(log_path)
        raise RuntimeError(
            f"llama-server did not become ready within {int(startup_timeout_s)}s"
            + (f": {last_error}" if last_error else "")
            + (f" log tail: {log_tail}" if log_tail else "")
        )

    def stop_server(self, server_id: str) -> Dict[str, Any]:
        state = self._load_state()
        servers = state.setdefault("servers", {})
        cfg = dict(servers.get(server_id) or {})
        if not cfg:
            raise RuntimeError("Unknown server id")
        target_pids: List[int] = []
        try:
            pid = int(cfg.get("pid") or 0)
        except Exception:
            pid = 0
        if pid > 0:
            target_pids.append(pid)
        try:
            port_pids = _listener_pids_for_port(int(cfg.get("port") or 0))
            for item in port_pids:
                if item not in target_pids:
                    target_pids.append(item)
        except Exception:
            pass
        stop_errors: List[str] = []
        for target_pid in target_pids:
            try:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(target_pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                        **self._run_hidden_kwargs(),
                    )
                else:
                    try:
                        os.killpg(target_pid, signal.SIGTERM)
                    except Exception:
                        os.kill(target_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except Exception as exc:
                stop_errors.append(f"{target_pid}: {exc}")
        deadline = time.time() + 5.0
        url = f"http://127.0.0.1:{int(cfg.get('port') or 8080)}"
        while time.time() < deadline:
            alive = [item for item in target_pids if _pid_exists(item)]
            try:
                _json_url(f"{url}/health")
                reachable = True
            except Exception:
                reachable = False
            if not alive and not reachable:
                break
            time.sleep(0.25)
        still_alive = [item for item in target_pids if _pid_exists(item)]
        if still_alive and os.name != "nt":
            for target_pid in still_alive:
                try:
                    try:
                        os.killpg(target_pid, signal.SIGKILL)
                    except Exception:
                        os.kill(target_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except Exception as exc:
                    stop_errors.append(f"{target_pid}: SIGKILL failed: {exc}")
            time.sleep(0.25)
            still_alive = [item for item in still_alive if _pid_exists(item)]
        cfg.pop("pid", None)
        cfg["stopped_at"] = _now_ts()
        servers[server_id] = cfg
        self._save_state(state)
        return {
            "ok": not bool(still_alive),
            "server": {"id": server_id, **cfg},
            "target_pids": target_pids,
            "still_alive": still_alive,
            "errors": stop_errors,
        }

    def _server_runtime_status(self, cfg: Dict[str, Any], *, lightweight: bool = False) -> Dict[str, Any]:
        cached = self._cached_server_status(cfg, lightweight=lightweight)
        if cached is not None:
            return cached
        host = str(cfg.get("host") or "127.0.0.1").strip()
        port = int(cfg.get("port") or 8080)
        url = f"http://{host}:{port}"
        if _in_docker() and host.lower() in ("127.0.0.1", "localhost"):
            service_host = str(os.environ.get("LLMLOADER2_CLIENT_SERVICE_HOSTNAME") or "gui_js").strip() or "gui_js"
            llmloader_url = f"http://{service_host}:{port}"
        else:
            host_for_backend = "host.docker.internal" if self._host_os() == "windows" else host
            llmloader_url = f"http://{host_for_backend}:{port}"
        running = False
        process_alive = False
        api_reachable = False
        slots = None
        pid = int(cfg.get("pid") or 0)
        if pid > 0:
            process_alive = _pid_exists(pid)
        if not process_alive:
            listener_pids = _listener_pids_for_port(port)
            if listener_pids:
                pid = int(listener_pids[0] or 0)
                process_alive = _pid_exists(pid) if pid > 0 else False
        try:
            data = _json_url(f"{url}/health", timeout=0.10 if lightweight else 0.15)
            api_reachable = bool(data.get("status") == "ok" or data.get("ok") is True or data)
        except Exception:
            api_reachable = False
        running = bool(api_reachable)
        try:
            slots = _json_url(f"{url}/slots", timeout=0.15 if lightweight else 0.25) if (running and not lightweight) else None
        except Exception:
            slots = None
        mem_info = _process_memory_bytes(pid) if (running and pid > 0 and not lightweight) else {}
        working_set_bytes = mem_info.get("working_set_bytes") if isinstance(mem_info, dict) else None
        private_bytes = mem_info.get("private_bytes") if isinstance(mem_info, dict) else None
        sys_mem = self._cached_system_memory()
        system_total_bytes = sys_mem.get("system_total_bytes") if isinstance(sys_mem, dict) else None
        system_available_bytes = sys_mem.get("system_available_bytes") if isinstance(sys_mem, dict) else None
        log_path = Path(str(cfg.get("log_path") or self.logs_dir / f"{cfg.get('id') or ''}.log"))
        buffer_breakdown = _parse_log_buffer_breakdown(log_path) if not lightweight else {}
        selected_device = None
        selected_device_index = cfg.get("main_gpu")
        gpu_total_bytes = None
        gpu_free_bytes = None
        gpu_used_bytes = None
        install_id = str(cfg.get("install_id") or "").strip()
        runtime_id = str(cfg.get("runtime_id") or "").strip().lower()
        probe = None
        runtime_uses_gpu = runtime_id in ("sycl", "vulkan", "cuda")
        probe_opt_in = str(os.environ.get("LLMLOADER2_LLAMA_STATUS_PROBE_DEVICES") or "").strip().lower()
        probe_enabled = (not lightweight) and (runtime_uses_gpu or probe_opt_in in ("1", "true", "yes", "on"))
        if probe_enabled:
            try:
                probe = self.probe_devices(install_id=install_id, runtime_id=runtime_id)
            except Exception:
                probe = None
        if isinstance(probe, dict) and probe.get("ok"):
            for line in list(probe.get("devices") or []):
                idx = _parse_device_index(str(line or ""))
                if idx is None:
                    continue
                try:
                    selected_idx = int(selected_device_index)
                except Exception:
                    selected_idx = None
                if selected_idx is not None and idx == selected_idx:
                    selected_device = str(line or "")
                    mem = _parse_device_memory(selected_device)
                    gpu_total_bytes = mem.get("total_bytes")
                    gpu_free_bytes = mem.get("free_bytes")
                    gpu_used_bytes = mem.get("used_bytes")
                    break
        if not selected_device and runtime_uses_gpu:
            try:
                selected_idx = int(selected_device_index)
            except Exception:
                selected_idx = None
            if selected_idx is not None and selected_idx >= 0:
                selected_device = f"{runtime_id.upper()} GPU #{selected_idx}"
            else:
                selected_device = f"{runtime_id.upper()} GPU"
        payload = {
            "running": bool(running),
            "process_alive": bool(process_alive),
            "api_reachable": bool(api_reachable),
            "url": url,
            "llmloader_url": llmloader_url,
            "slots": slots,
            "pid": pid if pid > 0 else None,
            "cpu_bytes": working_set_bytes,
            "working_set_bytes": working_set_bytes,
            "private_bytes": private_bytes,
            "system_total_bytes": system_total_bytes,
            "system_available_bytes": system_available_bytes,
            "cpu_mapped_model_bytes": buffer_breakdown.get("cpu_mapped_model_bytes"),
            "gpu_model_bytes": buffer_breakdown.get("gpu_model_bytes"),
            "gpu_model_label": buffer_breakdown.get("gpu_model_label"),
            "cpu_kv_bytes": buffer_breakdown.get("cpu_kv_bytes"),
            "gpu_kv_bytes": buffer_breakdown.get("gpu_kv_bytes"),
            "gpu_kv_label": buffer_breakdown.get("gpu_kv_label"),
            "cpu_compute_bytes": buffer_breakdown.get("cpu_compute_bytes"),
            "gpu_compute_bytes": buffer_breakdown.get("gpu_compute_bytes"),
            "gpu_compute_label": buffer_breakdown.get("gpu_compute_label"),
            "main_gpu": selected_device_index,
            "parallel_slots": cfg.get("parallel_slots"),
            "cont_batching": cfg.get("cont_batching"),
            "selected_device": selected_device,
            "gpu_total_bytes": gpu_total_bytes,
            "gpu_free_bytes": gpu_free_bytes,
            "gpu_used_bytes": gpu_used_bytes,
        }
        self._store_server_status(cfg, payload, lightweight=lightweight)
        return payload

    def get_server_logs(self, server_id: str, *, lines: int = 200) -> Dict[str, Any]:
        state = self._load_state()
        servers = state.get("servers") if isinstance(state.get("servers"), dict) else {}
        cfg = dict(servers.get(server_id) or {})
        if not cfg:
            raise RuntimeError("Unknown server id")
        log_path = Path(str(cfg.get("log_path") or self.logs_dir / f"{server_id}.log"))
        if not log_path.is_file():
            return {"ok": True, "server_id": server_id, "log_path": str(log_path), "lines": []}
        raw = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        tail = raw[-max(1, int(lines or 200)) :]
        return {"ok": True, "server_id": server_id, "log_path": str(log_path), "lines": tail}

    def get_server_diagnostics(self, server_id: str) -> Dict[str, Any]:
        state = self._load_state()
        servers = state.get("servers") if isinstance(state.get("servers"), dict) else {}
        cfg = dict(servers.get(server_id) or {})
        if not cfg:
            raise RuntimeError("Unknown server id")
        status = self._server_runtime_status(cfg)
        url = status.get("url") or ""
        models = None
        try:
            models = _json_url(f"{url}/v1/models")
        except Exception:
            models = None
        try:
            health = _json_url(f"{url}/health")
        except Exception:
            health = None
        return {
            "ok": True,
            "server_id": server_id,
            "config": cfg,
            "status": status,
            "health": health,
            "models": models,
        }
