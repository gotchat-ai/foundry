from __future__ import annotations

import json
import os
import platform
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from plugins.gui_helpers._framework.utils import require_gui_plugin_enabled


GUI_PLUGIN_ID = "crispasr_runtime_manager"
APP_ROOT = Path(__file__).resolve().parents[3]
CLIENT_ROOT = APP_ROOT / "vendor" / "crispasr_client"
STATE_DIR = APP_ROOT / "data" / "gui_helpers" / "crispasr_runtime_manager"
STATE_FILE = STATE_DIR / "state.json"
LOG_DIR = STATE_DIR / "logs"
REPO_URL = "https://github.com/CrispStrobe/CrispASR.git"


class InstallCreateBody(BaseModel):
    name: str = Field(min_length=1)
    runtime_id: str = Field(min_length=1)
    source_mode: str = "clone"
    source_dir: Optional[str] = None
    notes: Optional[str] = None


class InstallRegisterBody(BaseModel):
    name: str = Field(min_length=1)
    runtime_id: str = Field(min_length=1)
    executable_path: str = Field(min_length=1)
    notes: Optional[str] = None


class InstallActionBody(BaseModel):
    install_id: str = Field(min_length=1)


def _now_ts() -> int:
    return int(time.time())


def _ensure_dirs() -> None:
    for path in (CLIENT_ROOT, STATE_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)


def _default_state() -> Dict[str, Any]:
    return {
        "installs": [],
        "jobs": [],
        "updated_ts": _now_ts(),
    }


def _load_state() -> Dict[str, Any]:
    _ensure_dirs()
    if not STATE_FILE.exists():
        state = _default_state()
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        return state
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("state root is not an object")
    except Exception:
        data = _default_state()
    data.setdefault("installs", [])
    data.setdefault("jobs", [])
    data["updated_ts"] = int(data.get("updated_ts") or _now_ts())
    return data


def _save_state(state: Dict[str, Any]) -> None:
    _ensure_dirs()
    state["updated_ts"] = _now_ts()
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _token_from_request(request: Request) -> str:
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return str(request.headers.get("X-Auth-Token") or "").strip()


def _require_admin(app: Any, request: Request) -> Any:
    db = getattr(app.state, "collab_db", None)
    if db is None:
        raise HTTPException(status_code=403, detail="Admin auth unavailable")
    token = _token_from_request(request)
    try:
        user = db.resolve_token(token)
    except Exception:
        user = None
    if not user or str(getattr(user, "role", "")).lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def _slugify(value: str) -> str:
    raw = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value or "").strip())
    cleaned = "-".join(part for part in raw.split("-") if part)
    return cleaned or f"install-{_now_ts()}"


def _runtime_matrix() -> List[Dict[str, str]]:
    return [
        {"id": "cpu", "label": "CPU", "cmake_flag": "", "device_family": "cpu"},
        {"id": "vulkan", "label": "Vulkan", "cmake_flag": "-DGGML_VULKAN=ON", "device_family": "gpu"},
        {"id": "cuda", "label": "CUDA", "cmake_flag": "-DGGML_CUDA=ON", "device_family": "gpu"},
        {"id": "hip", "label": "AMD ROCm / HIP", "cmake_flag": "-DGGML_HIP=ON", "device_family": "gpu"},
        {"id": "sycl", "label": "Intel SYCL / oneAPI", "cmake_flag": "-DGGML_SYCL=ON", "device_family": "gpu"},
        {"id": "metal", "label": "Apple Metal", "cmake_flag": "-DGGML_METAL=ON", "device_family": "gpu"},
    ]


def _runtime_def(runtime_id: str) -> Dict[str, str]:
    rid = str(runtime_id or "").strip().lower()
    for row in _runtime_matrix():
        if row["id"] == rid:
            return row
    raise HTTPException(status_code=400, detail=f"unsupported_runtime:{runtime_id}")


def _host_os_id() -> str:
    value = platform.system().strip().lower()
    if value.startswith("win"):
        return "windows"
    if value == "darwin":
        return "macos"
    if value == "linux":
        return "linux"
    return value or "unknown"


def _windows_path_candidates(name: str) -> List[Path]:
    low = str(name or "").strip().lower()
    program_dirs = [
        Path(os.environ.get("ProgramFiles") or r"C:\Program Files"),
        Path(os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)"),
        Path(os.environ.get("ProgramW6432") or r"C:\Program Files"),
    ]
    local_app = Path(os.environ.get("LocalAppData") or "")
    candidates: List[Path] = []
    if low == "cmake":
        for base in program_dirs:
            candidates.extend(
                [
                    base / "CMake" / "bin" / "cmake.exe",
                    base / "cmake" / "bin" / "cmake.exe",
                ]
            )
    elif low == "git":
        for base in program_dirs:
            candidates.extend(
                [
                    base / "Git" / "cmd" / "git.exe",
                    base / "Git" / "bin" / "git.exe",
                ]
            )
    elif low == "vulkaninfo":
        for base in program_dirs:
            candidates.extend(
                [
                    base / "VulkanSDK" / "Bin" / "vulkaninfo.exe",
                ]
            )
        vk_sdk = str(os.environ.get("VK_SDK") or "").strip()
        if vk_sdk:
            candidates.append(Path(vk_sdk) / "Bin" / "vulkaninfo.exe")
    elif low == "nvcc":
        for base in program_dirs:
            candidates.extend(
                [
                    base / "NVIDIA GPU Computing Toolkit" / "CUDA" / "bin" / "nvcc.exe",
                ]
            )
    elif low == "nvidia-smi":
        for base in program_dirs:
            candidates.extend(
                [
                    base / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe",
                ]
            )
    elif low == "dpcpp":
        oneapi_root = str(os.environ.get("ONEAPI_ROOT") or "").strip()
        if oneapi_root:
            candidates.extend(
                [
                    Path(oneapi_root) / "compiler" / "latest" / "bin" / "dpcpp.exe",
                ]
            )
        for base in program_dirs:
            candidates.extend(
                [
                    base / "Intel" / "oneAPI" / "compiler" / "latest" / "bin" / "dpcpp.exe",
                ]
            )
    elif low == "sycl-ls":
        oneapi_root = str(os.environ.get("ONEAPI_ROOT") or "").strip()
        if oneapi_root:
            candidates.extend(
                [
                    Path(oneapi_root) / "compiler" / "latest" / "bin" / "sycl-ls.exe",
                ]
            )
        for base in program_dirs:
            candidates.extend(
                [
                    base / "Intel" / "oneAPI" / "compiler" / "latest" / "bin" / "sycl-ls.exe",
                ]
            )
    if local_app:
        if low == "cmake":
            candidates.append(local_app / "Programs" / "CMake" / "bin" / "cmake.exe")
        elif low == "git":
            candidates.append(local_app / "Programs" / "Git" / "cmd" / "git.exe")
    out: List[Path] = []
    seen = set()
    for path in candidates:
        key = str(path).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def _which(name: str) -> str:
    found = str(shutil.which(name) or "").strip()
    if found:
        return found
    if _host_os_id() == "windows":
        for candidate in _windows_path_candidates(name):
            try:
                if candidate.is_file():
                    return str(candidate)
            except Exception:
                continue
    return ""


def _bool_text(value: bool, good: str, bad: str) -> str:
    return good if value else bad


def _run_capture(cmd: List[str], timeout: float = 6.0) -> str:
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        text = str(proc.stdout or proc.stderr or "").strip()
        return text
    except Exception:
        return ""


def _detect_gpu_names(host_os: str) -> List[str]:
    names: List[str] = []
    if host_os == "windows":
        text = _run_capture(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
            ],
            timeout=8.0,
        )
        names = [line.strip() for line in text.splitlines() if line.strip()]
    elif host_os == "linux":
        text = _run_capture(["sh", "-lc", "lspci | grep -Ei 'vga|3d|display'"], timeout=8.0)
        names = [line.strip() for line in text.splitlines() if line.strip()]
    elif host_os == "macos":
        text = _run_capture(["system_profiler", "SPDisplaysDataType"], timeout=10.0)
        names = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("chipset model:"):
                names.append(stripped.split(":", 1)[1].strip())
    deduped: List[str] = []
    seen = set()
    for name in names:
        low = name.lower()
        if low in seen:
            continue
        seen.add(low)
        deduped.append(name)
    return deduped


def _gpu_facts(host_os: str) -> Dict[str, Any]:
    gpu_names = _detect_gpu_names(host_os)
    blob = " | ".join(gpu_names).lower()
    filtered_blob = " | ".join(
        name for name in gpu_names
        if "microsoft remote display adapter" not in name.lower()
    ).lower()
    active_blob = filtered_blob or blob
    has_nvidia = any(token in active_blob for token in ("nvidia", "geforce", "rtx", "quadro"))
    has_amd = any(token in active_blob for token in ("amd", "radeon", "instinct"))
    has_intel = any(token in active_blob for token in ("intel", "arc"))
    has_gpu = bool(active_blob.strip())
    return {
        "gpu_names": gpu_names,
        "has_gpu": has_gpu,
        "has_nvidia": has_nvidia,
        "has_amd": has_amd,
        "has_intel": has_intel,
        "active_blob": active_blob,
    }


def _prereq_hints(runtime_id: str, host_os: str, checks: Dict[str, str], facts: Dict[str, Any]) -> List[Dict[str, Any]]:
    rid = str(runtime_id or "").strip().lower()
    hints: List[Dict[str, Any]] = []

    def by_os(windows: str, linux: str, macos: str, fallback: str = "") -> str:
        if host_os == "windows":
            return windows
        if host_os == "linux":
            return linux
        if host_os == "macos":
            return macos
        return fallback or windows or linux or macos

    def add_hint(
        key: str,
        present: bool,
        title: str,
        why: str,
        install_where: str,
        verify: str,
        install_url: str = "",
    ) -> None:
        hints.append(
            {
                "key": key,
                "present": bool(present),
                "title": title,
                "why": why,
                "install_where": install_where,
                "verify": verify,
                "install_url": str(install_url or "").strip(),
            }
        )

    add_hint(
        "cmake",
        bool(checks.get("cmake")),
        "CMake",
        "Required to configure and generate the CrispASR build.",
        by_os(
            "Install CMake for Windows and enable the installer option to add CMake to the system PATH.",
            "Install CMake from your distro package manager or official binaries and ensure `cmake` is on PATH.",
            "Install CMake via Homebrew or the official macOS package and ensure `cmake` is on PATH.",
            "Install CMake and ensure `cmake` is on PATH.",
        ),
        by_os(
            "Open a new PowerShell session and run `cmake --version` in the same environment as this backend.",
            "Run `cmake --version` in the same shell/environment as this backend.",
            "Run `cmake --version` in the same shell/environment as this backend.",
            "Run `cmake --version`.",
        ),
        "https://cmake.org/download/",
    )
    add_hint(
        "git",
        bool(checks.get("git")),
        "Git",
        "Needed when the install source mode is set to clone the CrispASR repository.",
        by_os(
            "Install Git for Windows and allow the installer to add Git to PATH.",
            "Install Git from your distro package manager and ensure `git` is on PATH.",
            "Install Git via Xcode Command Line Tools or Homebrew and ensure `git` is on PATH.",
            "Install Git and ensure `git` is on PATH.",
        ),
        "Run `git --version`.",
        by_os(
            "https://git-scm.com/install/windows",
            "https://git-scm.com/download/linux",
            "https://git-scm.com/install/mac",
            "https://git-scm.com/downloads",
        ),
    )

    if rid == "vulkan":
        add_hint(
            "gpu",
            bool(facts.get("has_gpu")),
            "Vulkan-capable GPU",
            "Vulkan builds require a local GPU adapter.",
            "Use a system with a Vulkan-capable GPU and working drivers.",
            "The Host Compatibility section should list a real GPU adapter.",
        )
        add_hint(
            "vulkan_tools",
            bool(checks.get("vulkaninfo") or checks.get("vk_sdk")),
            "Vulkan SDK / runtime tools",
            "The manager uses Vulkan tooling to verify the runtime is actually available.",
            by_os(
                "Install the Vulkan SDK for Windows or your GPU vendor Vulkan runtime tools so `vulkaninfo` works, and make sure `VK_SDK` is available if you rely on the SDK.",
                "Install `vulkan-tools` or the Vulkan SDK for Linux so `vulkaninfo` is available, or export `VK_SDK` if you rely on the SDK.",
                "Metal builds are the normal macOS path; Vulkan guidance is only relevant when probing shared tooling.",
                "Install Vulkan SDK/runtime tools so `vulkaninfo` works, or set `VK_SDK`.",
            ),
            by_os(
                "Run `vulkaninfo` in PowerShell or confirm `VK_SDK` is set for the backend process.",
                "Run `vulkaninfo` in the backend environment or confirm `VK_SDK` is exported there.",
                "Not typically required on macOS for CrispASR builds.",
                "Run `vulkaninfo` or confirm `VK_SDK`.",
            ),
            by_os(
                "https://vulkan.lunarg.com/doc/view/1.3.290.0/windows/getting_started.html",
                "https://vulkan.lunarg.com/doc/view/latest/linux/getting_started.html",
                "https://www.lunarg.com/products/vulkan-sdk/",
                "https://www.lunarg.com/products/vulkan-sdk/",
            ),
        )
    elif rid == "cuda":
        add_hint(
            "gpu",
            bool(facts.get("has_nvidia")),
            "NVIDIA GPU",
            "CUDA builds require an NVIDIA GPU.",
            "Use a system with an NVIDIA GPU and working drivers.",
            "The Host Compatibility section should show an NVIDIA adapter.",
        )
        add_hint(
            "cuda_tools",
            bool(checks.get("nvcc") or checks.get("nvidia-smi")),
            "CUDA toolkit / NVIDIA tools",
            "Needed to confirm the CUDA toolchain and driver are visible.",
            by_os(
                "Install current NVIDIA Windows drivers and the CUDA Toolkit so `nvidia-smi` or `nvcc` is available.",
                "Install current NVIDIA Linux drivers and the CUDA Toolkit so `nvidia-smi` or `nvcc` is available.",
                "CUDA is not the normal path for CrispASR on macOS.",
                "Install NVIDIA drivers and CUDA Toolkit so `nvidia-smi` or `nvcc` is available.",
            ),
            "Run `nvidia-smi` or `nvcc --version`.",
            "https://developer.nvidia.com/cuda-downloads?target_os=Windows",
        )
    elif rid == "hip":
        add_hint(
            "linux",
            host_os == "linux",
            "Linux host",
            "ROCm/HIP builds are supported in this manager on Linux only.",
            "Run the manager on Linux for ROCm builds.",
            "Host OS should show `linux`.",
        )
        add_hint(
            "gpu",
            bool(facts.get("has_amd")),
            "AMD GPU",
            "HIP builds require an AMD GPU.",
            "Use a Linux system with a supported AMD GPU and drivers.",
            "The Host Compatibility section should show an AMD adapter.",
        )
        add_hint(
            "rocm_tools",
            bool(checks.get("hipconfig") or checks.get("rocminfo")),
            "ROCm tools",
            "Needed to verify ROCm is installed and visible to the backend.",
            by_os(
                "ROCm/HIP builds are not supported in this manager on Windows.",
                "Install ROCm for Linux so `hipconfig` or `rocminfo` is available to the backend.",
                "ROCm/HIP builds are not supported in this manager on macOS.",
                "Install ROCm so `hipconfig` or `rocminfo` is available.",
            ),
            "Run `hipconfig` or `rocminfo`.",
            "https://rocm.docs.amd.com/en/develop/install/rocm.html",
        )
    elif rid == "sycl":
        add_hint(
            "gpu",
            bool(facts.get("has_intel")),
            "Intel GPU",
            "SYCL builds require an Intel GPU.",
            "Use a system with an Intel GPU and current drivers.",
            "The Host Compatibility section should show an Intel adapter.",
        )
        add_hint(
            "oneapi_tools",
            bool(checks.get("sycl-ls") or checks.get("dpcpp") or checks.get("oneapi_root")),
            "Intel oneAPI / SYCL tools",
            "Needed to compile and verify SYCL support.",
            by_os(
                "Install Intel oneAPI Base Toolkit for Windows so `dpcpp` or `sycl-ls` is available, or make sure `ONEAPI_ROOT` is visible to the backend.",
                "Install Intel oneAPI Base Toolkit for Linux so `dpcpp` or `sycl-ls` is available, or export `ONEAPI_ROOT` for the backend.",
                "SYCL is not the normal CrispASR path on macOS.",
                "Install Intel oneAPI Base Toolkit so `dpcpp` or `sycl-ls` is available, or set `ONEAPI_ROOT`.",
            ),
            by_os(
                "Run `sycl-ls` or `dpcpp --version` from the backend shell, or confirm `ONEAPI_ROOT` is set there.",
                "Run `sycl-ls` or `dpcpp --version` from the backend shell, or confirm `ONEAPI_ROOT` is exported there.",
                "Not typically required on macOS.",
                "Run `sycl-ls` or `dpcpp --version`, or confirm `ONEAPI_ROOT`.",
            ),
            by_os(
                "https://www.intel.com/content/www/us/en/docs/oneapi-toolkit/installation-guide-windows/latest/install-intel-oneapi-toolkit.html",
                "https://www.intel.com/content/www/us/en/developer/tools/oneapi/oneapi-toolkit-download.html",
                "https://www.intel.com/content/www/us/en/developer/tools/oneapi/oneapi-toolkit-download.html",
                "https://www.intel.com/content/www/us/en/developer/tools/oneapi/oneapi-toolkit-download.html",
            ),
        )
    elif rid == "metal":
        add_hint(
            "macos",
            host_os == "macos",
            "macOS host",
            "Metal builds are only available on macOS.",
            "Run the manager on macOS for Metal builds.",
            "Host OS should show `macos`.",
        )
        add_hint(
            "clang",
            bool(checks.get("clang++")),
            "Apple build tools",
            "Metal builds need the Apple clang toolchain.",
            by_os(
                "Metal builds are not available on Windows.",
                "Metal builds are not available on Linux.",
                "Install Xcode Command Line Tools so `clang++` is available.",
                "Install Apple build tools so `clang++` is available.",
            ),
            "Run `clang++ --version`.",
            "https://developer.apple.com/documentation/xcode/installing-the-command-line-tools?changes=_8%2C_8",
        )

    return hints


def _probe_runtime(runtime_id: str, host_os: str) -> Dict[str, Any]:
    rid = str(runtime_id or "").strip().lower()
    env = os.environ
    facts = _gpu_facts(host_os)
    checks = {
        "git": _which("git"),
        "cmake": _which("cmake"),
        "ninja": _which("ninja"),
        "vulkaninfo": _which("vulkaninfo"),
        "nvcc": _which("nvcc"),
        "nvidia-smi": _which("nvidia-smi"),
        "hipconfig": _which("hipconfig"),
        "rocminfo": _which("rocminfo"),
        "sycl-ls": _which("sycl-ls"),
        "dpcpp": _which("dpcpp"),
        "clang++": _which("clang++"),
        "vk_sdk": str(env.get("VK_SDK") or "").strip(),
        "oneapi_root": str(env.get("ONEAPI_ROOT") or "").strip(),
    }
    compatible = False
    build_ready = False
    reasons: List[str] = []
    if rid == "cpu":
        compatible = True
        build_ready = bool(checks["cmake"])
        reasons.append(f"CPU runtime is supported on {host_os}.")
        if not build_ready:
            reasons.append("Build tools are incomplete: `cmake` is not on PATH yet.")
    elif rid == "vulkan":
        compatible = host_os in {"windows", "linux"} and bool(facts["has_gpu"])
        build_ready = bool(checks["cmake"]) and bool(checks["vulkaninfo"] or checks["vk_sdk"])
        reasons.append("Requires Windows or Linux plus a Vulkan-capable GPU.")
        if not compatible:
            reasons.append("No local GPU adapter was detected for Vulkan probing.")
        elif not (checks["vulkaninfo"] or checks["vk_sdk"]):
            reasons.append("Vulkan build/runtime tools are not fully visible yet (`vulkaninfo` or `VK_SDK` missing).")
        elif not checks["cmake"]:
            reasons.append("Vulkan looks available, but `cmake` is still missing for local builds.")
    elif rid == "cuda":
        compatible = host_os in {"windows", "linux"} and bool(facts["has_nvidia"])
        build_ready = bool(checks["cmake"]) and bool(checks["nvcc"] or checks["nvidia-smi"])
        reasons.append("Requires an NVIDIA GPU and CUDA tooling.")
        if not compatible:
            reasons.append("No NVIDIA GPU was detected.")
        elif not (checks["nvcc"] or checks["nvidia-smi"]):
            reasons.append("CUDA GPU detected, but `nvcc`/`nvidia-smi` are not visible yet.")
        elif not checks["cmake"]:
            reasons.append("CUDA looks available, but `cmake` is still missing for local builds.")
    elif rid == "hip":
        compatible = host_os == "linux" and bool(facts["has_amd"])
        build_ready = bool(checks["cmake"]) and bool(checks["hipconfig"] or checks["rocminfo"])
        reasons.append("Requires ROCm/HIP on Linux.")
        if host_os != "linux":
            reasons.append("ROCm/HIP builds are Linux-only in this manager.")
        elif not compatible:
            reasons.append("No AMD GPU was detected.")
        elif not (checks["hipconfig"] or checks["rocminfo"]):
            reasons.append("AMD GPU detected, but ROCm tools are not visible yet (`hipconfig` / `rocminfo`).")
        elif not checks["cmake"]:
            reasons.append("ROCm looks available, but `cmake` is still missing for local builds.")
    elif rid == "sycl":
        compatible = host_os in {"windows", "linux"} and bool(facts["has_intel"])
        build_ready = bool(checks["cmake"]) and bool(checks["sycl-ls"] or checks["dpcpp"] or checks["oneapi_root"])
        reasons.append("Requires Intel oneAPI / SYCL tooling.")
        if not compatible:
            reasons.append("No Intel GPU was detected.")
        elif not (checks["sycl-ls"] or checks["dpcpp"] or checks["oneapi_root"]):
            reasons.append("Intel GPU detected, but SYCL tooling is not visible yet (`sycl-ls`, `dpcpp`, or `ONEAPI_ROOT`).")
        elif not checks["cmake"]:
            reasons.append("SYCL looks available, but `cmake` is still missing for local builds.")
    elif rid == "metal":
        compatible = host_os == "macos"
        build_ready = bool(checks["cmake"]) and bool(checks["clang++"])
        reasons.append("Requires macOS with Metal-capable tooling.")
        if host_os != "macos":
            reasons.append("Metal builds only apply to macOS.")
        elif not checks["clang++"]:
            reasons.append("Metal host detected, but Apple build tools are not fully visible yet (`clang++` missing).")
        elif not checks["cmake"]:
            reasons.append("Metal looks available, but `cmake` is still missing for local builds.")
    else:
        reasons.append("Unknown runtime.")
    return {
        "runtime_id": rid,
        "compatible": bool(compatible),
        "build_ready": bool(build_ready),
        "checks": checks,
        "gpu_names": list(facts["gpu_names"]),
        "reasons": reasons,
        "prerequisites": _prereq_hints(rid, host_os, checks, facts),
    }


def _host_probe() -> Dict[str, Any]:
    host_os = _host_os_id()
    facts = _gpu_facts(host_os)
    return {
        "host_os": host_os,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cwd": str(APP_ROOT),
        "client_root": str(CLIENT_ROOT),
        "gpu_names": list(facts["gpu_names"]),
        "compatibility": [_probe_runtime(row["id"], host_os) | row for row in _runtime_matrix()],
    }


def _host_runtime_probe(runtime_id: str) -> Dict[str, Any]:
    return _probe_runtime(runtime_id, _host_os_id())


def _install_paths(install_id: str) -> Dict[str, Path]:
    slug = _slugify(install_id)
    base = CLIENT_ROOT / "installs" / slug
    source = base / "source"
    build = base / "build"
    scripts = base / "scripts"
    logs = base / "logs"
    return {
        "base": base,
        "source": source,
        "build": build,
        "scripts": scripts,
        "logs": logs,
    }


def _crispasr_executable(build_dir: Path) -> Path:
    if _host_os_id() == "windows":
        candidates = [
            build_dir / "bin" / "crispasr.exe",
            build_dir / "bin" / "Release" / "crispasr.exe",
            build_dir / "Release" / "crispasr.exe",
        ]
    else:
        candidates = [
            build_dir / "bin" / "crispasr",
            build_dir / "Release" / "crispasr",
        ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def _build_plan(name: str, runtime_id: str, source_mode: str = "clone", source_dir: Optional[str] = None) -> Dict[str, Any]:
    install_id = _slugify(name)
    runtime = _runtime_def(runtime_id)
    paths = _install_paths(install_id)
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    runtime_flag = runtime["cmake_flag"]
    extra_flags = [
        "-DCMAKE_BUILD_TYPE=Release",
        "-DCRISPASR_BUILD_TESTS=OFF",
        "-DCRISPASR_BUILD_EXAMPLES=ON",
        "-DCRISPASR_BUILD_SERVER=OFF",
    ]
    if runtime_flag:
        extra_flags.append(runtime_flag)
    use_source = Path(str(source_dir).strip()).expanduser() if str(source_dir or "").strip() else paths["source"]
    exe_path = _crispasr_executable(paths["build"])
    git_path = _which("git") or "git"
    cmake_path = _which("cmake") or "cmake"
    return {
        "install_id": install_id,
        "name": name,
        "runtime_id": runtime["id"],
        "runtime_label": runtime["label"],
        "source_mode": source_mode,
        "repo_url": REPO_URL,
        "source_dir": str(use_source),
        "build_dir": str(paths["build"]),
        "scripts_dir": str(paths["scripts"]),
        "logs_dir": str(paths["logs"]),
        "executable_path": str(exe_path),
        "cmake_flags": extra_flags,
        "build_target": "crispasr-cli",
        "tool_paths": {
            "git": git_path,
            "cmake": cmake_path,
        },
    }


def _crispasr_compat_patch_note() -> str:
    return (
        "llmloader2 compatibility patch: export the WeSpeaker C API symbols from "
        "crispasr.dll/shared libraries so the WeSpeaker WebRTC plugin can call the "
        "runtime through ctypes after users rebuild or reinstall CrispASR."
    )


def _windows_script(plan: Dict[str, Any]) -> str:
    source_dir = plan["source_dir"]
    build_dir = plan["build_dir"]
    git_cmd = str(((plan.get("tool_paths") or {}).get("git")) or "git")
    cmake_cmd = str(((plan.get("tool_paths") or {}).get("cmake")) or "cmake")
    cmake_configure = " ".join(
        [f'"-S"', f'"{source_dir}"', f'"-B"', f'"{build_dir}"'] + [f'"{part}"' for part in (plan.get("cmake_flags") or [])]
    )
    clone_block = ""
    patch_block = (
        "function Apply-Llmloader2CrispAsrPatch {\n"
        "  param([string]$SourceDir)\n"
        "  $Header = Join-Path $SourceDir \"src\\wespeaker.h\"\n"
        "  if (-not (Test-Path $Header)) { return }\n"
        "  $Text = Get-Content -LiteralPath $Header -Raw\n"
        "  if ($Text -notmatch \"#ifndef WESPEAKER_API\") {\n"
        "    $Needle = \"#include <stdint.h>`r`n\"\n"
        "    if ($Text -notlike \"*$Needle*\") { $Needle = \"#include <stdint.h>`n\" }\n"
        "    $Macro = \"`n#ifndef WESPEAKER_API`n#if defined(_WIN32)`n#define WESPEAKER_API __declspec(dllexport)`n#elif defined(__GNUC__) || defined(__clang__)`n#define WESPEAKER_API __attribute__((visibility(`\"default`\")))`n#else`n#define WESPEAKER_API`n#endif`n#endif`n\"\n"
        "    $Text = $Text.Replace($Needle, $Needle + $Macro)\n"
        "  }\n"
        "  $Names = @(\n"
        "    \"wespeaker_context_default_params\",\n"
        "    \"wespeaker_init_from_file\",\n"
        "    \"wespeaker_free\",\n"
        "    \"wespeaker_init_worker\",\n"
        "    \"wespeaker_embed_dim\",\n"
        "    \"wespeaker_sample_rate\",\n"
        "    \"wespeaker_n_mels\",\n"
        "    \"wespeaker_min_samples\",\n"
        "    \"wespeaker_embed\",\n"
        "    \"wespeaker_embed_windows\",\n"
        "    \"wespeaker_compute_fbank\",\n"
        "    \"wespeaker_embed_staged\"\n"
        "  )\n"
        "  foreach ($Name in $Names) {\n"
        "    $Text = [regex]::Replace($Text, \"(?m)^(?!WESPEAKER_API\\s)(struct\\s+wespeaker_context_params\\s+$Name\\s*\\()\", \"WESPEAKER_API `$1\")\n"
        "    $Text = [regex]::Replace($Text, \"(?m)^(?!WESPEAKER_API\\s)(struct\\s+wespeaker_context\\*\\s+$Name\\s*\\()\", \"WESPEAKER_API `$1\")\n"
        "    $Text = [regex]::Replace($Text, \"(?m)^(?!WESPEAKER_API\\s)(void\\s+$Name\\s*\\()\", \"WESPEAKER_API `$1\")\n"
        "    $Text = [regex]::Replace($Text, \"(?m)^(?!WESPEAKER_API\\s)(int\\s+$Name\\s*\\()\", \"WESPEAKER_API `$1\")\n"
        "    $Text = [regex]::Replace($Text, \"(?m)^(?!WESPEAKER_API\\s)(float\\*\\s+$Name\\s*\\()\", \"WESPEAKER_API `$1\")\n"
        "  }\n"
        "  Set-Content -LiteralPath $Header -Value $Text -NoNewline\n"
        "  Write-Host \"Applied llmloader2 CrispASR compatibility patch to $Header\"\n"
        "}\n"
    )
    if plan["source_mode"] == "clone":
        clone_block = (
            "function Invoke-Native {\n"
            "  param(\n"
            "    [string]$Exe,\n"
            "    [Parameter(ValueFromRemainingArguments = $true)]\n"
            "    [string[]]$Args\n"
            "  )\n"
            "  & $Exe @Args\n"
            "  if ($LASTEXITCODE -ne 0) { throw \"Command failed with exit code ${LASTEXITCODE}: $Exe $($Args -join ' ')\" }\n"
            "}\n"
            f'if (-not (Test-Path "{source_dir}\\.git")) {{\n'
            f'  Invoke-Native "{git_cmd}" "clone" "--recursive" "{plan["repo_url"]}" "{source_dir}"\n'
            "}\n"
            f'Set-Location "{source_dir}"\n'
            f'Invoke-Native "{git_cmd}" "fetch" "--all" "--tags"\n'
            f'Invoke-Native "{git_cmd}" "pull" "--ff-only"\n'
            f'Invoke-Native "{git_cmd}" "submodule" "update" "--init" "--recursive"\n'
        )
    else:
        clone_block = (
            "function Invoke-Native {\n"
            "  param(\n"
            "    [string]$Exe,\n"
            "    [Parameter(ValueFromRemainingArguments = $true)]\n"
            "    [string[]]$Args\n"
            "  )\n"
            "  & $Exe @Args\n"
            "  if ($LASTEXITCODE -ne 0) { throw \"Command failed with exit code ${LASTEXITCODE}: $Exe $($Args -join ' ')\" }\n"
            "}\n"
            f'Set-Location "{source_dir}"\n'
            f'Invoke-Native "{git_cmd}" "submodule" "update" "--init" "--recursive"\n'
        )
    return (
        "$ErrorActionPreference = 'Stop'\n"
        f'New-Item -ItemType Directory -Force -Path "{build_dir}" | Out-Null\n'
        f"{clone_block}"
        f"{patch_block}"
        f'Apply-Llmloader2CrispAsrPatch "{source_dir}"\n'
        f'Invoke-Native "{cmake_cmd}" {cmake_configure}\n'
        f'Invoke-Native "{cmake_cmd}" "--build" "{build_dir}" "--config" "Release" "--target" "{str(plan.get("build_target") or "crispasr-cli")}"\n'
    )


def _posix_script(plan: Dict[str, Any]) -> str:
    source_dir = plan["source_dir"]
    build_dir = plan["build_dir"]
    flags = " ".join(plan["cmake_flags"])
    git_cmd = str(((plan.get("tool_paths") or {}).get("git")) or "git")
    cmake_cmd = str(((plan.get("tool_paths") or {}).get("cmake")) or "cmake")
    patch_python_fallback = shlex.quote(sys.executable or "python")
    clone_block = ""
    patch_block = (
        "apply_llmloader2_crispasr_patch() {\n"
        "  header=\"$1/src/wespeaker.h\"\n"
        "  [ -f \"$header\" ] || return 0\n"
        "  patch_python=\"${LLMLOADER2_PATCH_PYTHON:-}\"\n"
        "  if [ -z \"$patch_python\" ]; then\n"
        "    if command -v python3 >/dev/null 2>&1; then\n"
        "      patch_python=\"python3\"\n"
        "    elif command -v python >/dev/null 2>&1; then\n"
        "      patch_python=\"python\"\n"
        "    else\n"
        f"      patch_python={patch_python_fallback}\n"
        "    fi\n"
        "  fi\n"
        "  \"$patch_python\" - \"$header\" <<'PY'\n"
        "import re, sys\n"
        "from pathlib import Path\n"
        "path = Path(sys.argv[1])\n"
        "text = path.read_text(encoding='utf-8')\n"
        "if '#ifndef WESPEAKER_API' not in text:\n"
        "    text = text.replace(\n"
        "        '#include <stdint.h>\\n',\n"
        "        '#include <stdint.h>\\n\\n#ifndef WESPEAKER_API\\n#if defined(_WIN32)\\n#define WESPEAKER_API __declspec(dllexport)\\n#elif defined(__GNUC__) || defined(__clang__)\\n#define WESPEAKER_API __attribute__((visibility(\"default\")))\\n#else\\n#define WESPEAKER_API\\n#endif\\n#endif\\n',\n"
        "    )\n"
        "names = [\n"
        "    'wespeaker_context_default_params', 'wespeaker_init_from_file', 'wespeaker_free',\n"
        "    'wespeaker_init_worker', 'wespeaker_embed_dim', 'wespeaker_sample_rate',\n"
        "    'wespeaker_n_mels', 'wespeaker_min_samples', 'wespeaker_embed',\n"
        "    'wespeaker_embed_windows', 'wespeaker_compute_fbank', 'wespeaker_embed_staged',\n"
        "]\n"
        "for name in names:\n"
        "    for prefix in ('struct wespeaker_context_params', 'struct wespeaker_context\\\\*', 'void', 'int', 'float\\\\*'):\n"
        "        text = re.sub(rf'(?m)^(?!WESPEAKER_API\\\\s)({prefix}\\\\s+{name}\\\\s*\\\\()', r'WESPEAKER_API \\1', text)\n"
        "path.write_text(text, encoding='utf-8')\n"
        "PY\n"
        "  echo \"Applied llmloader2 CrispASR compatibility patch to $header\"\n"
        "}\n"
    )
    if plan["source_mode"] == "clone":
        clone_block = (
            f'if [ ! -d "{source_dir}/.git" ]; then\n'
            f'  "{git_cmd}" clone --recursive "{plan["repo_url"]}" "{source_dir}"\n'
            "fi\n"
            f'cd "{source_dir}"\n'
            f'"{git_cmd}" fetch --all --tags\n'
            f'"{git_cmd}" pull --ff-only\n'
            f'"{git_cmd}" submodule update --init --recursive\n'
        )
    else:
        clone_block = (
            f'cd "{source_dir}"\n'
            f'"{git_cmd}" submodule update --init --recursive\n'
        )
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f'mkdir -p "{build_dir}"\n'
        f"{clone_block}"
        f"{patch_block}"
        f'apply_llmloader2_crispasr_patch "{source_dir}"\n'
        f'"{cmake_cmd}" -S "{source_dir}" -B "{build_dir}" {flags}\n'
        f'"{cmake_cmd}" --build "{build_dir}" --config Release --target "{str(plan.get("build_target") or "crispasr-cli")}"\n'
    )


def _write_build_scripts(plan: Dict[str, Any]) -> Dict[str, str]:
    scripts_dir = Path(plan["scripts_dir"])
    scripts_dir.mkdir(parents=True, exist_ok=True)
    ps1 = scripts_dir / "build_crispasr.ps1"
    sh = scripts_dir / "build_crispasr.sh"
    ps1.write_text(_windows_script(plan), encoding="utf-8")
    sh.write_text(_posix_script(plan), encoding="utf-8")
    try:
        sh.chmod(0o755)
    except Exception:
        pass
    return {"powershell": str(ps1), "bash": str(sh)}


def _state_install(state: Dict[str, Any], install_id: str) -> Optional[Dict[str, Any]]:
    for row in state.get("installs", []):
        if str(row.get("install_id") or "") == str(install_id):
            return row
    return None


def _state_job(state: Dict[str, Any], job_id: str) -> Optional[Dict[str, Any]]:
    for row in state.get("jobs", []):
        if str(row.get("job_id") or "") == str(job_id):
            return row
    return None


def _refresh_job(job: Dict[str, Any]) -> Dict[str, Any]:
    pid = int(job.get("pid") or 0)
    if pid <= 0:
        return job
    running = False
    exit_code = job.get("exit_code")
    try:
        if _host_os_id() == "windows":
            result = subprocess.run(["powershell", "-NoProfile", "-Command", f"Get-Process -Id {pid}"], capture_output=True, text=True, timeout=4)
            running = result.returncode == 0
        else:
            os.kill(pid, 0)
            running = True
    except Exception:
        running = False
    if not running and str(job.get("status") or "") == "running":
        job["status"] = "finished"
        job["finished_ts"] = _now_ts()
        log_path = Path(str(job.get("log_path") or ""))
        if log_path.is_file():
            text = log_path.read_text(encoding="utf-8", errors="ignore")
            if "error" in text.lower() or "failed" in text.lower():
                job["status"] = "failed"
                exit_code = 1 if exit_code is None else exit_code
        job["exit_code"] = 0 if exit_code is None else exit_code
    return job


def _refresh_state_jobs(state: Dict[str, Any]) -> Dict[str, Any]:
    for job in state.get("jobs", []):
        _refresh_job(job)
    for install in state.get("installs", []):
        active = next((j for j in state.get("jobs", []) if str(j.get("install_id") or "") == str(install.get("install_id") or "") and str(j.get("status") or "") == "running"), None)
        install["active_job_id"] = str(active.get("job_id") or "") if active else ""
        exe = str(install.get("executable_path") or "").strip()
        install["executable_exists"] = bool(exe and Path(exe).is_file())
        install["updated_ts"] = _now_ts()
    return state


def _launch_build(plan: Dict[str, Any]) -> Dict[str, Any]:
    paths = _install_paths(plan["install_id"])
    scripts = _write_build_scripts(plan)
    logs_dir = paths["logs"]
    logs_dir.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex
    log_path = logs_dir / f"{job_id}.log"
    host_os = _host_os_id()
    if host_os == "windows":
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", scripts["powershell"]]
    else:
        cmd = ["bash", scripts["bash"]]
    with log_path.open("a", encoding="utf-8") as handle:
        process = subprocess.Popen(
            cmd,
            cwd=plan["source_dir"] if Path(plan["source_dir"]).exists() else str(APP_ROOT),
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
    return {
        "job_id": job_id,
        "pid": process.pid,
        "command": cmd,
        "log_path": str(log_path),
        "scripts": scripts,
    }


def install(app):
    router = APIRouter()

    @router.get("/v1/crispasr_runtime/status")
    def crispasr_runtime_status(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(app, request)
        state = _refresh_state_jobs(_load_state())
        _save_state(state)
        return {"ok": True, "host": _host_probe(), "installs": state.get("installs", []), "jobs": state.get("jobs", [])}

    @router.post("/v1/crispasr_runtime/plan")
    def crispasr_runtime_plan(body: InstallCreateBody, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(app, request)
        plan = _build_plan(body.name, body.runtime_id, body.source_mode, body.source_dir)
        scripts = _write_build_scripts(plan)
        return {"ok": True, "plan": plan, "scripts": scripts, "host": _host_probe()}

    @router.post("/v1/crispasr_runtime/install/register")
    def crispasr_runtime_register(body: InstallRegisterBody, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(app, request)
        state = _load_state()
        install_id = _slugify(body.name)
        row = _state_install(state, install_id)
        payload = {
            "install_id": install_id,
            "name": body.name,
            "runtime_id": str(body.runtime_id).strip().lower(),
            "host_os": _host_os_id(),
            "source_mode": "manual",
            "source_dir": "",
            "build_dir": "",
            "scripts_dir": "",
            "logs_dir": "",
            "executable_path": str(Path(body.executable_path).expanduser()),
            "executable_exists": Path(str(Path(body.executable_path).expanduser())).is_file(),
            "notes": str(body.notes or "").strip(),
            "created_ts": row.get("created_ts") if isinstance(row, dict) else _now_ts(),
            "updated_ts": _now_ts(),
            "active_job_id": "",
        }
        if row is None:
            state["installs"].append(payload)
        else:
            row.update(payload)
        _save_state(state)
        return {"ok": True, "install": payload}

    @router.post("/v1/crispasr_runtime/install/create")
    def crispasr_runtime_create(body: InstallCreateBody, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(app, request)
        state = _load_state()
        plan = _build_plan(body.name, body.runtime_id, body.source_mode, body.source_dir)
        scripts = _write_build_scripts(plan)
        install = {
            "install_id": plan["install_id"],
            "name": plan["name"],
            "runtime_id": plan["runtime_id"],
            "runtime_label": plan["runtime_label"],
            "host_os": _host_os_id(),
            "source_mode": plan["source_mode"],
            "source_dir": plan["source_dir"],
            "build_dir": plan["build_dir"],
            "scripts_dir": plan["scripts_dir"],
            "logs_dir": plan["logs_dir"],
            "executable_path": plan["executable_path"],
            "executable_exists": Path(plan["executable_path"]).is_file(),
            "notes": str(body.notes or "").strip(),
            "scripts": scripts,
            "created_ts": _now_ts(),
            "updated_ts": _now_ts(),
            "active_job_id": "",
        }
        existing = _state_install(state, install["install_id"])
        if existing is None:
            state["installs"].append(install)
        else:
            existing.update(install)
            install = existing
        _save_state(state)
        return {"ok": True, "install": install, "host": _host_probe()}

    @router.post("/v1/crispasr_runtime/build/start")
    def crispasr_runtime_build_start(body: InstallActionBody, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(app, request)
        state = _refresh_state_jobs(_load_state())
        install_row = _state_install(state, body.install_id)
        if install_row is None:
            raise HTTPException(status_code=404, detail="install_not_found")
        if str(install_row.get("active_job_id") or "").strip():
            raise HTTPException(status_code=409, detail="build_already_running")
        runtime_probe = _host_runtime_probe(str(install_row.get("runtime_id") or "cpu"))
        if not bool(runtime_probe.get("compatible")):
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "runtime_not_compatible",
                    "runtime_id": str(install_row.get("runtime_id") or "cpu"),
                    "reasons": list(runtime_probe.get("reasons") or []),
                },
            )
        if not bool(runtime_probe.get("build_ready")):
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "runtime_build_not_ready",
                    "runtime_id": str(install_row.get("runtime_id") or "cpu"),
                    "checks": dict(runtime_probe.get("checks") or {}),
                    "reasons": list(runtime_probe.get("reasons") or []),
                },
            )
        plan = _build_plan(
            str(install_row.get("name") or body.install_id),
            str(install_row.get("runtime_id") or "cpu"),
            str(install_row.get("source_mode") or "clone"),
            str(install_row.get("source_dir") or "") or None,
        )
        launched = _launch_build(plan)
        job = {
            "job_id": launched["job_id"],
            "install_id": body.install_id,
            "status": "running",
            "pid": launched["pid"],
            "log_path": launched["log_path"],
            "command": launched["command"],
            "scripts": launched["scripts"],
            "created_ts": _now_ts(),
            "updated_ts": _now_ts(),
        }
        state["jobs"].append(job)
        install_row["active_job_id"] = job["job_id"]
        install_row["scripts"] = launched["scripts"]
        install_row["updated_ts"] = _now_ts()
        _save_state(state)
        return {"ok": True, "job": job, "install": install_row}

    @router.post("/v1/crispasr_runtime/build/stop")
    def crispasr_runtime_build_stop(body: InstallActionBody, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(app, request)
        state = _refresh_state_jobs(_load_state())
        install_row = _state_install(state, body.install_id)
        if install_row is None:
            raise HTTPException(status_code=404, detail="install_not_found")
        job_id = str(install_row.get("active_job_id") or "").strip()
        if not job_id:
            return {"ok": True, "stopped": False, "reason": "no_active_job"}
        job = _state_job(state, job_id)
        if job is None:
            install_row["active_job_id"] = ""
            _save_state(state)
            return {"ok": True, "stopped": False, "reason": "job_missing"}
        pid = int(job.get("pid") or 0)
        if pid > 0:
            try:
                if _host_os_id() == "windows":
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, timeout=10)
                else:
                    os.kill(pid, signal.SIGTERM)
            except Exception:
                pass
        job["status"] = "stopped"
        job["finished_ts"] = _now_ts()
        install_row["active_job_id"] = ""
        _save_state(state)
        return {"ok": True, "stopped": True, "job": job}

    @router.post("/v1/crispasr_runtime/job/remove")
    def crispasr_runtime_job_remove(body: InstallActionBody, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(app, request)
        state = _refresh_state_jobs(_load_state())
        job_id = str(body.install_id or "").strip()
        job = _state_job(state, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job_not_found")
        if str(job.get("status") or "").strip().lower() == "running":
            raise HTTPException(status_code=409, detail="job_still_running")
        state["jobs"] = [row for row in state.get("jobs", []) if str(row.get("job_id") or "") != job_id]
        for install in state.get("installs", []):
            if str(install.get("active_job_id") or "") == job_id:
                install["active_job_id"] = ""
                install["updated_ts"] = _now_ts()
        _save_state(state)
        return {"ok": True, "removed_job_id": job_id}

    @router.post("/v1/crispasr_runtime/install/remove")
    def crispasr_runtime_install_remove(body: InstallActionBody, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(app, request)
        state = _refresh_state_jobs(_load_state())
        install_row = _state_install(state, body.install_id)
        if install_row is None:
            raise HTTPException(status_code=404, detail="install_not_found")
        if str(install_row.get("active_job_id") or "").strip():
            raise HTTPException(status_code=409, detail="stop_build_before_remove")
        state["installs"] = [row for row in state.get("installs", []) if str(row.get("install_id") or "") != body.install_id]
        _save_state(state)
        return {"ok": True, "removed_install_id": body.install_id}

    @router.get("/v1/crispasr_runtime/logs")
    def crispasr_runtime_logs(request: Request, job_id: str = "", lines: int = 200):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(app, request)
        state = _refresh_state_jobs(_load_state())
        if not str(job_id or "").strip():
            return {"ok": True, "job": None, "lines": []}
        job = _state_job(state, job_id)
        if job is None:
            return {"ok": True, "job": None, "lines": []}
        log_path = Path(str(job.get("log_path") or ""))
        if not log_path.is_file():
            return {"ok": True, "job": job, "lines": []}
        text = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        return {"ok": True, "job": job, "lines": text[-max(1, int(lines or 200)) :]}

    app.include_router(router)
