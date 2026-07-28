#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import queue
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import winreg  # type: ignore
except Exception:  # pragma: no cover
    winreg = None


ROOT = Path(__file__).resolve().parent
CONFIG_DIR = ROOT / "data" / "setup_wizard"
CONFIG_PATH = CONFIG_DIR / "setup_config.json"
PID_PATH = CONFIG_DIR / "service_pids.json"
LOG_DIR = CONFIG_DIR / "logs"
MSVC_BUILD_TOOLS_URL = "https://aka.ms/vs/17/release/vs_buildtools.exe"
MSVC_BUILD_TOOLS_HELP_URL = "https://visualstudio.microsoft.com/visual-cpp-build-tools/"
VULKAN_SDK_URL = "https://vulkan.lunarg.com/sdk/home#windows"
_CLEANUP_LOCK = threading.Lock()
_CLEANUP_DONE = False
_WINDOWS_CONSOLE_HANDLER = None


GPU_MODELS: Dict[str, List[str]] = {
    "Apple": [
        "Apple Silicon M1",
        "Apple Silicon M2",
        "Apple Silicon M3",
        "Apple Silicon M4",
        "Intel Mac with AMD GPU",
    ],
    "AMD": [
        "Radeon RX 500 series",
        "Radeon RX 5000 series",
        "Radeon RX 6000 series",
        "Radeon RX 7000 series",
        "Radeon Pro",
        "Other AMD GPU",
    ],
    "Intel": [
        "Intel Arc A-series",
        "Intel Arc B-series",
        "Intel Iris Xe",
        "Intel UHD Graphics",
        "Other Intel GPU",
    ],
    "Nvidia": [
        "GeForce GTX 10-series",
        "GeForce RTX 20-series",
        "GeForce RTX 30-series",
        "GeForce RTX 40-series",
        "GeForce RTX 50-series",
        "NVIDIA Quadro/RTX workstation",
        "Other NVIDIA GPU",
    ],
    "No GPU": ["CPU only"],
    "I don't know": ["Auto detect / ask me later"],
}


LINUX_BASE_PACKAGES = [
    "build-essential",
    "cmake",
    "ninja-build",
    "python3-venv",
    "python3-tk",
    "pkg-config",
]


LINUX_VULKAN_PACKAGES = [
    *LINUX_BASE_PACKAGES,
    "libvulkan-dev",
    "vulkan-tools",
    "glslc",
    "spirv-headers",
    "spirv-tools",
    "glslang-tools",
    "libshaderc-dev",
]


def _now() -> int:
    return int(time.time())


def _read_json(path: Path, default: Any) -> Any:
    try:
        if not path.is_file():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _platform_key() -> str:
    value = platform.system().lower()
    if value.startswith("darwin"):
        return "macos"
    if value.startswith("windows"):
        return "windows"
    if value.startswith("linux"):
        return "linux"
    return value or "unknown"


def _windows_env_value(name: str) -> str:
    value = str(os.environ.get(name) or "").strip()
    if value or _platform_key() != "windows" or winreg is None:
        return value
    for root, subkey in (
        (winreg.HKEY_CURRENT_USER, r"Environment"),
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
    ):
        try:
            with winreg.OpenKey(root, subkey) as key:
                raw, _value_type = winreg.QueryValueEx(key, name)
                text = str(raw or "").strip()
                if text:
                    return text
        except Exception:
            continue
    return ""


def _machine_key() -> str:
    return platform.machine().strip().lower()


def _macos_apple_silicon() -> bool:
    return _platform_key() == "macos" and _machine_key() in ("arm64", "aarch64")


def _apple_clang_version() -> Optional[str]:
    if _platform_key() != "macos":
        return None
    for cmd in (["/usr/bin/clang", "--version"], ["xcrun", "clang", "--version"]):
        result = _run_capture(cmd, timeout=5.0)
        output = str(result.get("output") or result.get("stdout") or result.get("stderr") or "")
        for line in output.splitlines():
            if "Apple clang version" in line:
                return line.strip()
        if output.strip() and "AppleClang" in output:
            return output.splitlines()[0].strip()
    return None


def _extract_apple_clang_from_build_line(text: str) -> Optional[str]:
    match = re.search(r"AppleClang\s+([0-9]+(?:\.[0-9]+)*)", text or "")
    if not match:
        return None
    return f"Apple clang version {match.group(1)}"


def _apple_clang_major(version_text: Optional[str]) -> int:
    if not version_text:
        return 0
    marker = "Apple clang version"
    text = version_text
    if marker in text:
        text = text.split(marker, 1)[1].strip()
    token = text.split()[0] if text.split() else ""
    try:
        return int(token.split(".", 1)[0])
    except Exception:
        return 0


def _macos_old_apple_clang_message(version_text: Optional[str]) -> str:
    return (
        f"AppleClang is too old for the current llama-cpp-python source build ({version_text or 'unknown version'}). "
        "Update Xcode Command Line Tools, then run Install Packages again. Try: xcode-select --install"
    )


def _macos_clt_update_available(detection: Dict[str, Any]) -> bool:
    if _platform_key() != "macos":
        return False
    tools = detection.get("tools") if isinstance(detection.get("tools"), dict) else {}
    major = int(tools.get("apple_clang_major") or 0)
    return bool(major and major < 15)


def trigger_macos_clt_update() -> Dict[str, Any]:
    if _platform_key() != "macos":
        return {"ok": False, "error": "Command Line Tools updates are only available on macOS."}
    version = _apple_clang_version()
    major = _apple_clang_major(version)
    if major >= 15:
        return {"ok": True, "message": "AppleClang is already new enough.", "apple_clang_version": version}
    result = _run_capture(["xcode-select", "--install"], timeout=15.0)
    output = str(result.get("output") or "")
    if result.get("ok"):
        return {
            "ok": True,
            "message": "The Apple Command Line Tools installer prompt was opened. Finish that installer, then click Check System again.",
            "apple_clang_version": version,
            "output": output,
        }
    if "already installed" in output.lower():
        opened = False
        try:
            subprocess.Popen(["open", "x-apple.systempreferences:com.apple.Software-Update-Settings.extension"])
            opened = True
        except Exception:
            opened = False
        return {
            "ok": True,
            "message": (
                "Command Line Tools are installed but outdated. macOS says updates must be installed from Software Update. "
                "Install any Command Line Tools or Xcode update shown there, then click Check System again."
            ),
            "apple_clang_version": version,
            "software_update_opened": opened,
            "output": output,
        }
    return {
        "ok": False,
        "error": output or "Unable to open the Command Line Tools installer.",
        "apple_clang_version": version,
    }


def _venv_python(env_dir: Path) -> Path:
    if os.name == "nt":
        return env_dir / "Scripts" / "python.exe"
    return env_dir / "bin" / "python"


def _default_install_root() -> Path:
    return ROOT


def _default_config() -> Dict[str, Any]:
    install_root = _default_install_root()
    env_dir = install_root / ".venv"
    return {
        "version": 1,
        "created_at": _now(),
        "updated_at": _now(),
        "app_root": str(ROOT),
        "install_root": str(install_root),
        "env_dir": str(env_dir),
        "gpu_brand": "I don't know",
        "gpu_model": "Auto detect / ask me later",
        "backend": "auto",
        "llama_cpp": {
            "backend": "auto",
            "cmake_args": "",
            "package": "llama-cpp-python",
        },
        "torch": {
            "backend": "cpu",
            "command": [],
        },
        "install_media_packages": False,
        "system_packages": [],
        "last_detection": {},
    }


def load_config() -> Dict[str, Any]:
    cfg = _default_config()
    existing = _read_json(CONFIG_PATH, {})
    if isinstance(existing, dict):
        cfg.update(existing)
    return cfg


def save_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    previous = load_config()
    previous_signature = str(previous.get("setup_signature") or "").strip()
    previous_installed_signature = str(previous.get("installed_signature") or "").strip()
    previous_ready = bool(previous.get("install_ready"))
    cfg = dict(previous)
    cfg.update(payload)
    install_root = Path(str(cfg.get("install_root") or ROOT)).expanduser()
    cfg["install_root"] = str(install_root)
    cfg["env_dir"] = str(Path(str(cfg.get("env_dir") or install_root / ".venv")).expanduser())
    cfg["app_root"] = str(ROOT)
    cfg["install_media_packages"] = bool(cfg.get("install_media_packages", False))
    cfg["updated_at"] = _now()
    cfg["llama_cpp"] = llama_cpp_plan(cfg)
    cfg["torch"] = torch_plan(cfg)
    cfg["system_packages"] = required_system_packages(cfg)
    cfg["setup_signature"] = setup_signature(cfg)
    cfg["python_setup_signature"] = python_setup_signature(cfg)
    if previous_ready and not previous_installed_signature and previous_signature == cfg["setup_signature"]:
        cfg["installed_signature"] = cfg["setup_signature"]
    elif str(cfg.get("installed_signature") or "").strip() != cfg["setup_signature"]:
        cfg["install_ready"] = False
    _write_json(CONFIG_PATH, cfg)
    return cfg


def setup_signature(cfg: Dict[str, Any]) -> str:
    payload = {
        "platform": _platform_key(),
        "install_root": str(cfg.get("install_root") or ""),
        "env_dir": str(cfg.get("env_dir") or ""),
        "gpu_brand": str(cfg.get("gpu_brand") or ""),
        "gpu_model": str(cfg.get("gpu_model") or ""),
        "install_media_packages": bool(cfg.get("install_media_packages", False)),
        "llama_cpp": llama_cpp_plan(cfg),
        "torch": torch_plan(cfg),
        "system_packages": required_system_packages(cfg),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def python_setup_signature(cfg: Dict[str, Any]) -> str:
    payload = {
        "platform": _platform_key(),
        "env_dir": str(cfg.get("env_dir") or ""),
        "gpu_brand": str(cfg.get("gpu_brand") or ""),
        "gpu_model": str(cfg.get("gpu_model") or ""),
        "install_media_packages": bool(cfg.get("install_media_packages", False)),
        "llama_cpp": llama_cpp_plan(cfg),
        "torch": torch_plan(cfg),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def llama_cpp_plan(cfg: Dict[str, Any]) -> Dict[str, str]:
    brand = str(cfg.get("gpu_brand") or "").strip().lower()
    model = str(cfg.get("gpu_model") or "").strip().lower()
    sysname = _platform_key()
    if sysname == "macos":
        if _macos_apple_silicon() and (brand == "apple" or "apple silicon" in model):
            return {
                "backend": "metal",
                "cmake_args": "-DGGML_METAL=ON -DLLAMA_METAL=ON -DGGML_VULKAN=OFF",
                "package": "llama-cpp-python",
            }
        return {
            "backend": "cpu",
            "cmake_args": "-DGGML_METAL=OFF -DLLAMA_METAL=OFF -DGGML_VULKAN=OFF -DGGML_NATIVE=OFF -DLLAMA_NATIVE=OFF",
            "package": "llama-cpp-python",
        }
    if sysname == "windows":
        has_vulkan_sdk = bool(_windows_env_value("VULKAN_SDK"))
        if brand == "nvidia" and bool(_windows_env_value("CUDA_PATH")):
            return {"backend": "cuda", "cmake_args": "-DGGML_CUDA=on", "package": "llama-cpp-python"}
        if brand in ("amd", "intel", "no gpu", "i don't know", "nvidia") and has_vulkan_sdk:
            return {"backend": "vulkan", "cmake_args": "-DGGML_VULKAN=on", "package": "llama-cpp-python"}
        return {
            "backend": "cpu",
            "cmake_args": "-DGGML_VULKAN=OFF -DGGML_CUDA=OFF -DGGML_NATIVE=OFF -DLLAMA_NATIVE=OFF",
            "package": "llama-cpp-python",
        }
    if brand == "apple":
        return {"backend": "metal", "cmake_args": "-DGGML_METAL=on", "package": "llama-cpp-python"}
    if brand == "nvidia":
        if sysname == "linux" and not _visible_nvidia_runtime():
            return {"backend": "vulkan", "cmake_args": "-DGGML_VULKAN=on", "package": "llama-cpp-python"}
        return {"backend": "cuda", "cmake_args": "-DGGML_CUDA=on", "package": "llama-cpp-python"}
    if brand in ("amd", "intel"):
        return {"backend": "vulkan", "cmake_args": "-DGGML_VULKAN=on", "package": "llama-cpp-python"}
    if brand in ("no gpu", "i don't know"):
        return {"backend": "vulkan", "cmake_args": "-DGGML_VULKAN=on", "package": "llama-cpp-python"}
    return {"backend": "vulkan", "cmake_args": "-DGGML_VULKAN=on", "package": "llama-cpp-python"}


def _linux_x86_64() -> bool:
    return _platform_key() == "linux" and platform.machine().lower() in ("x86_64", "amd64")


def _visible_nvidia_runtime() -> bool:
    if shutil.which("nvidia-smi") or shutil.which("nvcc"):
        return True
    return os.path.exists("/proc/driver/nvidia/version")


def _cpu_torch_packages() -> List[str]:
    if _linux_x86_64():
        return ["torch==2.8.0+cpu", "torchvision==0.23.0+cpu", "torchaudio==2.8.0+cpu"]
    return ["torch", "torchvision", "torchaudio"]


def torch_plan(cfg: Dict[str, Any]) -> Dict[str, Any]:
    brand = str(cfg.get("gpu_brand") or "").strip().lower()
    sysname = _platform_key()
    packages = ["torch", "torchvision", "torchaudio"]
    if sysname == "macos":
        cpu_packages = _cpu_torch_packages()
        return {
            "backend": "cpu",
            "command": ["install", *cpu_packages, "--index-url", "https://download.pytorch.org/whl/cpu"],
            "reason": "PyTorch CUDA/XPU/ROCm wheels are not used on macOS by this wizard; CPU Torch is the safest supported package plan for this system.",
        }
    if brand == "nvidia":
        if sysname == "linux" and not _visible_nvidia_runtime():
            cpu_packages = _cpu_torch_packages()
            return {
                "backend": "cpu",
                "command": ["install", *cpu_packages, "--index-url", "https://download.pytorch.org/whl/cpu"],
                "reason": "Nvidia was selected, but no NVIDIA runtime/tooling was detected on this Linux machine.",
            }
        return {
            "backend": "cuda",
            "command": ["install", "--pre", *packages, "--index-url", "https://download.pytorch.org/whl/nightly/cu128"],
        }
    if brand == "intel":
        return {
            "backend": "xpu",
            "command": ["install", *packages, "--index-url", "https://download.pytorch.org/whl/xpu"],
        }
    if brand == "amd" and sysname == "linux":
        return {
            "backend": "rocm",
            "command": ["install", "--pre", *packages, "--index-url", "https://download.pytorch.org/whl/nightly/rocm"],
        }
    cpu_packages = _cpu_torch_packages()
    return {
        "backend": "cpu",
        "command": ["install", *cpu_packages, "--index-url", "https://download.pytorch.org/whl/cpu"],
    }


def required_system_packages(cfg: Dict[str, Any]) -> List[str]:
    if _platform_key() != "linux":
        return []
    backend = llama_cpp_plan(cfg).get("backend")
    if backend == "vulkan":
        return list(LINUX_VULKAN_PACKAGES)
    if backend == "cuda":
        return list(LINUX_BASE_PACKAGES)
    return list(LINUX_BASE_PACKAGES)


def _run_capture(cmd: List[str], timeout: float = 10.0) -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {"ok": proc.returncode == 0, "code": proc.returncode, "output": proc.stdout.strip()}
    except Exception as exc:
        return {"ok": False, "code": -1, "output": str(exc)}


def _dpkg_installed(package: str) -> bool:
    if shutil.which("dpkg-query") is None:
        return False
    result = _run_capture(["dpkg-query", "-W", "-f=${Status}", package], timeout=5.0)
    return result.get("ok") and "install ok installed" in str(result.get("output") or "")


def _python_has_module(python_exe: Path, module: str) -> bool:
    if not python_exe.is_file():
        return False
    result = _run_capture(
        [str(python_exe), "-c", f"import importlib.util, sys; sys.exit(0 if importlib.util.find_spec({module!r}) else 1)"],
        timeout=10.0,
    )
    return bool(result.get("ok"))


def _python_version_text(python_exe: Path) -> str:
    if not python_exe.is_file():
        return ""
    result = _run_capture([str(python_exe), "-c", "import sys; print('.'.join(map(str, sys.version_info[:3])))"], timeout=10.0)
    return str(result.get("output") or "").strip() if result.get("ok") else ""


def _pip_version_tuple(python_exe: Path) -> tuple:
    if not python_exe.is_file():
        return ()
    result = _run_capture(
        [str(python_exe), "-c", "import pip; print(getattr(pip, '__version__', ''))"],
        timeout=10.0,
    )
    if not result.get("ok"):
        return ()
    parts: List[int] = []
    for token in str(result.get("output") or "").strip().split("."):
        digits = "".join(ch for ch in token if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def _python_imports_module(python_exe: Path, module: str) -> bool:
    if not python_exe.is_file():
        return False
    result = _run_capture([str(python_exe), "-c", f"import {module}"], timeout=10.0)
    return bool(result.get("ok"))


def _python_module_version(python_exe: Path, module: str) -> str:
    if not python_exe.is_file():
        return ""
    result = _run_capture(
        [str(python_exe), "-c", f"import {module}; print(getattr({module}, '__version__', ''))"],
        timeout=10.0,
    )
    return str(result.get("output") or "").strip() if result.get("ok") else ""


def _version_tuple(value: str) -> tuple:
    parts: List[int] = []
    for token in str(value or "").split("."):
        digits = "".join(ch for ch in token if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def _numpy_compatible_with_torch(python_exe: Path) -> bool:
    if _platform_key() != "macos":
        return True
    version = _python_module_version(python_exe, "numpy")
    parsed = _version_tuple(version)
    return bool(parsed and parsed < (2, 0))


def _python_torch_matches_plan(python_exe: Path, tplan: Dict[str, Any]) -> bool:
    if not python_exe.is_file():
        return False
    result = _run_capture(
        [
            str(python_exe),
            "-c",
            "import torch; print(getattr(torch, '__version__', ''))",
        ],
        timeout=10.0,
    )
    if not result.get("ok"):
        return False
    version = str(result.get("output") or "").strip().lower()
    backend = str(tplan.get("backend") or "").strip().lower()
    if backend == "cpu" and _linux_x86_64():
        return "+cpu" in version and "+cu" not in version
    if backend == "cuda":
        return "+cu" in version or "cuda" in version
    return True


def _windows_program_files_x86() -> Path:
    return Path(os.environ.get("ProgramFiles(x86)") or os.environ.get("ProgramFiles") or "C:\\Program Files (x86)")


def _windows_vswhere_path() -> Optional[Path]:
    candidates = [
        _windows_program_files_x86() / "Microsoft Visual Studio" / "Installer" / "vswhere.exe",
        Path(os.environ.get("ProgramFiles") or "C:\\Program Files") / "Microsoft Visual Studio" / "Installer" / "vswhere.exe",
    ]
    for path in candidates:
        if path.is_file():
            return path
    found = shutil.which("vswhere")
    return Path(found) if found else None


def _windows_msvc_install_path() -> str:
    if _platform_key() != "windows":
        return ""
    vswhere = _windows_vswhere_path()
    if vswhere:
        result = _run_capture(
            [
                str(vswhere),
                "-latest",
                "-products",
                "*",
                "-requires",
                "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                "-property",
                "installationPath",
            ],
            timeout=12.0,
        )
        path = str(result.get("output") or "").strip().splitlines()
        if result.get("ok") and path:
            return path[0].strip()
    for env_name in ("VSINSTALLDIR", "VCToolsInstallDir"):
        value = str(os.environ.get(env_name) or "").strip()
        if value:
            return value
    roots = [
        _windows_program_files_x86() / "Microsoft Visual Studio" / "2022",
        Path(os.environ.get("ProgramFiles") or "C:\\Program Files") / "Microsoft Visual Studio" / "2022",
    ]
    editions = ("BuildTools", "Community", "Professional", "Enterprise")
    for root in roots:
        for edition in editions:
            path = root / edition
            if (path / "VC" / "Auxiliary" / "Build" / "vcvars64.bat").is_file():
                return str(path)
            if list((path / "VC" / "Tools" / "MSVC").glob("*/bin/Hostx64/x64/cl.exe")):
                return str(path)
    cl_path = shutil.which("cl")
    if cl_path:
        return str(Path(cl_path).parent)
    return ""


def _windows_has_msvc_build_tools() -> bool:
    return bool(_windows_msvc_install_path())


def install_ready_from_detection(detection: Dict[str, Any]) -> bool:
    tools = detection.get("tools") if isinstance(detection.get("tools"), dict) else {}
    if detection.get("missing_system_packages"):
        return False
    prerequisites = detection.get("prerequisites") if isinstance(detection.get("prerequisites"), list) else []
    if any(isinstance(item, dict) and item.get("required") and not item.get("ok") for item in prerequisites):
        return False
    required = ["venv_exists", "pip_ready", "llama_cpp_ready", "torch_ready", "torch_plan_ready"]
    if detection.get("platform") == "linux":
        required.append("tkinter_ready")
    if detection.get("platform") == "macos":
        required.append("numpy_torch_compatible")
    return all(bool(tools.get(key)) for key in required)


def detect_environment(cfg: Dict[str, Any]) -> Dict[str, Any]:
    env_python = _venv_python(Path(str(cfg.get("env_dir") or "")))
    sysname = _platform_key()
    plan = llama_cpp_plan(cfg)
    tplan = torch_plan(cfg)
    signature = setup_signature(cfg)
    py_signature = python_setup_signature(cfg)
    installed_signature = str(cfg.get("installed_signature") or "").strip()
    installed_py_signature = str(cfg.get("installed_python_signature") or "").strip()
    config_matches_installed = not installed_signature or installed_signature == signature
    python_config_matches_installed = not installed_py_signature or installed_py_signature == py_signature
    packages = required_system_packages(cfg)
    missing_packages = []
    if sysname == "linux":
        missing_packages = [pkg for pkg in packages if not _dpkg_installed(pkg)]
    tools = {
        "python": sys.executable,
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "venv_python": str(env_python),
        "venv_python_version": _python_version_text(env_python),
        "venv_exists": env_python.is_file(),
        "pip_ready": _python_has_module(env_python, "pip"),
        "numpy_version": _python_module_version(env_python, "numpy"),
        "numpy_torch_compatible": _numpy_compatible_with_torch(env_python),
        "llama_cpp_ready": _python_has_module(env_python, "llama_cpp"),
        "torch_ready": _python_has_module(env_python, "torch"),
        "torch_plan_ready": _python_torch_matches_plan(env_python, tplan),
        "torchvision_ready": _python_has_module(env_python, "torchvision"),
        "torchaudio_ready": _python_has_module(env_python, "torchaudio"),
        "diffusers_ready": _python_has_module(env_python, "diffusers"),
        "transformers_ready": _python_has_module(env_python, "transformers"),
        "accelerate_ready": _python_has_module(env_python, "accelerate"),
        "safetensors_ready": _python_has_module(env_python, "safetensors"),
        "tkinter_ready": _python_imports_module(env_python, "tkinter"),
        "vulkaninfo": bool(shutil.which("vulkaninfo")),
        "glslc": bool(shutil.which("glslc")),
        "glslangValidator": bool(shutil.which("glslangValidator")),
        "nvcc": bool(shutil.which("nvcc")),
        "cmake": bool(shutil.which("cmake")),
        "ninja": bool(shutil.which("ninja")),
    }
    if sysname == "macos":
        tools["xcode_tools"] = bool(_run_capture(["xcode-select", "-p"], timeout=5.0).get("ok"))
        tools["apple_clang_version"] = _apple_clang_version()
        tools["apple_clang_major"] = _apple_clang_major(str(tools.get("apple_clang_version") or ""))
    if sysname == "windows":
        tools["vulkan_sdk"] = bool(_windows_env_value("VULKAN_SDK"))
        tools["cuda_path"] = bool(_windows_env_value("CUDA_PATH"))
        tools["msvc_build_tools"] = _windows_has_msvc_build_tools()
        tools["msvc_install_path"] = _windows_msvc_install_path()
    warnings: List[str] = []
    prerequisites: List[Dict[str, Any]] = []
    backend = str(plan.get("backend") or "")
    if sysname == "windows":
        msvc_required = not tools.get("llama_cpp_ready")
        prerequisites.append(
            {
                "id": "msvc_build_tools",
                "label": "Microsoft C++ Build Tools",
                "ok": bool(tools.get("msvc_build_tools")),
                "required": bool(msvc_required),
                "url": MSVC_BUILD_TOOLS_URL,
                "help_url": MSVC_BUILD_TOOLS_HELP_URL,
                "detail": (
                    "Install Visual Studio 2022 Build Tools with the Desktop development with C++ workload."
                    if not tools.get("msvc_build_tools")
                    else f"Found at {tools.get('msvc_install_path') or 'detected toolchain'}."
                ),
            }
        )
        if not tools.get("msvc_build_tools") and msvc_required:
            warnings.append("Microsoft C++ Build Tools were not detected. Install Visual Studio 2022 Build Tools with the Desktop development with C++ workload, then run Check System again.")
        if backend == "cuda" and not tools.get("cuda_path"):
            warnings.append("CUDA was selected, but CUDA_PATH is not set. Install the NVIDIA CUDA Toolkit before building llama-cpp-python with CUDA.")
        if backend == "vulkan" and not tools.get("vulkan_sdk"):
            warnings.append("Vulkan was selected, but VULKAN_SDK is not set. Install the Windows Vulkan SDK, then run Check System again so the wizard can detect it.")
        if backend == "vulkan" or str(cfg.get("gpu_brand") or "").strip().lower() in ("amd", "intel", "no gpu", "i don't know"):
            prerequisites.append(
                {
                    "id": "vulkan_sdk",
                    "label": "Vulkan SDK",
                    "ok": bool(tools.get("vulkan_sdk")),
                    "required": False,
                    "url": VULKAN_SDK_URL,
                    "detail": (
                        "VULKAN_SDK is set, so embedded llama-cpp-python can be built with Vulkan."
                        if tools.get("vulkan_sdk")
                        else "Optional for embedded llama-cpp-python Vulkan builds. The downloaded llama-server Vulkan runtime does not need this SDK."
                    ),
                }
            )
        if tplan.get("backend") == "xpu":
            warnings.append("Intel XPU Torch wheels are installed from the PyTorch XPU index. If this GPU is unsupported, switch Torch to CPU by selecting No GPU or I don't know.")
        if str(cfg.get("gpu_brand") or "").strip().lower() == "amd":
            warnings.append("PyTorch ROCm wheels are Linux-oriented. This wizard will use CPU Torch for AMD on Windows/macOS.")
        warnings.append("Windows standalone setup skips miniupnpc by default because it can require a native wheel build. Core chat does not require it; the optional Firewall + UPnP plugin will report UPnP unavailable if miniupnpc is missing.")
    if sysname == "macos" and not tools.get("xcode_tools"):
        warnings.append("macOS builds require Xcode Command Line Tools. Install them with: xcode-select --install")
    if sysname == "macos":
        if backend == "cpu" and str(cfg.get("gpu_brand") or "").strip().lower() in ("amd", "intel", "nvidia", "apple"):
            warnings.append("This Mac is not using Apple Silicon, so the wizard will use CPU/Accelerate for llama-cpp-python instead of Metal/CUDA/XPU/ROCm.")
        if int(tools.get("apple_clang_major") or 0) and int(tools.get("apple_clang_major") or 0) < 15:
            warnings.append(_macos_old_apple_clang_message(str(tools.get("apple_clang_version") or "")))
        warnings.append("macOS standalone setup skips openai-whisper by default because it can require fragile numba/llvmlite source builds. Core chat does not require it.")
        warnings.append("macOS setup installs cryptography from binary wheels only. If no wheel exists for this Python/architecture, use Python 3.11/3.12 or install Homebrew pkgconf and openssl for native builds.")
        version_text = str(tools.get("venv_python_version") or tools.get("python_version") or "")
        try:
            major, minor, *_ = [int(part) for part in version_text.split(".") if part.isdigit()]
        except Exception:
            major, minor = 0, 0
        if (major, minor) >= (3, 13):
            warnings.append("Python 3.13+ may not have wheels for numba/llvmlite yet. If those fail, install Python 3.12 and recreate the setup venv with that interpreter.")
    if sysname == "linux" and backend == "cuda" and not tools.get("nvcc"):
        warnings.append("CUDA was selected, but nvcc was not found. Install the NVIDIA CUDA Toolkit before building llama-cpp-python with CUDA.")
    if tplan.get("reason"):
        warnings.append(str(tplan.get("reason")))
    if tplan.get("backend") == "rocm":
        warnings.append("AMD Torch uses nightly ROCm wheels. If your AMD card or driver is not ROCm-supported, rerun with No GPU to install CPU Torch.")
    if sysname == "linux" and missing_packages:
        sudo_path = shutil.which("sudo")
        sudo_ok = bool(sudo_path and _run_capture([sudo_path, "-n", "true"], timeout=5.0).get("ok"))
        if sudo_ok:
            warnings.append("Missing Linux packages will be installed with passwordless sudo.")
        elif shutil.which("pkexec"):
            warnings.append("Missing Linux packages require administrator permission. The installer will open a pkexec authentication prompt.")
        else:
            warnings.append("Missing Linux packages require administrator permission. Install them manually in a terminal, then run Install Packages again.")
    detection = {
        "platform": sysname,
        "machine": platform.machine(),
        "plan": plan,
        "torch_plan": tplan,
        "required_system_packages": packages,
        "missing_system_packages": missing_packages,
        "prerequisites": prerequisites,
        "warnings": warnings,
        "tools": tools,
        "requirements_file": str(ROOT / "requirements.txt"),
        "config_path": str(CONFIG_PATH),
        "setup_signature": signature,
        "python_setup_signature": py_signature,
        "installed_signature": installed_signature,
        "installed_python_signature": installed_py_signature,
        "config_matches_installed": config_matches_installed,
        "python_config_matches_installed": python_config_matches_installed,
    }
    detection["macos_clt_update_required"] = _macos_clt_update_available(detection)
    detection["install_ready"] = install_ready_from_detection(detection) and config_matches_installed
    return detection


class Job:
    def __init__(self) -> None:
        self.id = str(_now())
        self.status = "idle"
        self.logs: "queue.Queue[str]" = queue.Queue()
        self.history: List[str] = []
        self.summary: Dict[str, Any] = {}
        self.thread: Optional[threading.Thread] = None
        self.phase = "Idle"
        self.step = 0
        self.total_steps = 0
        self.current_command = ""
        self.started_at = 0.0
        self.finished_at = 0.0
        self.detected_apple_clang_version = ""

    def line(self, text: str) -> None:
        value = str(text)
        self.history.append(value)
        self.logs.put(value)

    def set_progress(self, phase: str, step: Optional[int] = None, total_steps: Optional[int] = None) -> None:
        self.phase = str(phase or "")
        if step is not None:
            self.step = int(step)
        if total_steps is not None:
            self.total_steps = int(total_steps)
        self.line(f"[{self.step}/{self.total_steps}] {self.phase}")


JOB = Job()


def _stream_command(job: Job, cmd: List[str], *, cwd: Path = ROOT, env: Optional[Dict[str, str]] = None) -> int:
    job.current_command = " ".join(cmd)
    job.line(f"$ {job.current_command}")
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        text = line.rstrip()
        job.line(text)
        if _platform_key() == "macos" and not job.detected_apple_clang_version:
            detected = _extract_apple_clang_from_build_line(text)
            if detected:
                job.detected_apple_clang_version = detected
    code = proc.wait()
    job.line(f"[exit {code}] {job.current_command}")
    job.current_command = ""
    return code


def _create_venv(job: Job, cfg: Dict[str, Any]) -> Path:
    env_dir = Path(str(cfg.get("env_dir") or "")).expanduser()
    env_python = _venv_python(env_dir)
    if env_python.is_file():
        job.line(f"venv already exists: {env_dir}")
        return env_python
    env_dir.parent.mkdir(parents=True, exist_ok=True)
    code = _stream_command(job, [sys.executable, "-m", "venv", str(env_dir)], cwd=ROOT)
    if code != 0:
        raise RuntimeError(f"venv creation failed with exit code {code}")
    return env_python


def _install_linux_packages(job: Job, cfg: Dict[str, Any]) -> None:
    missing = detect_environment(cfg).get("missing_system_packages") or []
    if not missing:
        job.line("system packages already satisfied")
        return
    job.line("missing system packages: " + ", ".join(str(item) for item in missing))
    if _platform_key() != "linux":
        job.line("system package install is manual on this platform")
        return
    if shutil.which("apt-get") is None:
        job.line("apt-get not found; install these manually: " + ", ".join(missing))
        return
    code = _stream_privileged_apt(job, ["apt-get", "update"], missing)
    if code != 0:
        raise RuntimeError(f"apt-get update failed with exit code {code}")
    code = _stream_privileged_apt(job, ["apt-get", "install", "-y", *missing], missing)
    if code != 0:
        raise RuntimeError(f"apt-get install failed with exit code {code}")


def _stream_privileged_apt(job: Job, apt_args: List[str], packages: List[str]) -> int:
    sudo_path = shutil.which("sudo")
    pkexec_path = shutil.which("pkexec")
    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"
    if sudo_path:
        sudo_check = _run_capture([sudo_path, "-n", "true"], timeout=5.0)
        if sudo_check.get("ok"):
            return _stream_command(job, [sudo_path, "-n", *apt_args], cwd=ROOT, env=env)
        job.line("sudo requires a password, so the browser wizard cannot answer it directly.")
    if pkexec_path:
        job.line("Opening a system authentication prompt with pkexec...")
        return _stream_command(job, [pkexec_path, *apt_args], cwd=ROOT, env=env)
    manual = (
        "sudo apt-get update\n"
        f"sudo apt-get install -y {' '.join(packages)}"
    )
    raise RuntimeError(
        "System packages require administrator permission, but passwordless sudo and pkexec are not available. "
        "Run these commands in a terminal, then press Install Packages again:\n"
        + manual
    )


def _filtered_requirements_file(cfg: Dict[str, Any]) -> Path:
    source = ROOT / "requirements.txt"
    skip_prefixes = ("torch", "torchvision", "torchaudio")
    skip_names = set()
    if _platform_key() == "windows":
        # Optional Firewall + UPnP feature only. miniupnpc often has no usable
        # Windows wheel for fresh installs and can fail native wheel builds.
        skip_names.add("miniupnpc")
    if _platform_key() == "macos":
        skip_prefixes = (*skip_prefixes, "numpy")
        # openai-whisper pulls numba/llvmlite, which can fall back to fragile
        # native source builds and block the core chat setup.
        skip_names.add("openai-whisper")
        # Installed separately with --only-binary to avoid Rust/OpenSSL builds.
        skip_names.add("cryptography")
    lines: List[str] = []
    for raw in source.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        lowered = stripped.lower()
        if any(lowered.startswith(prefix) for prefix in skip_prefixes):
            continue
        package_name = re.split(r"[<>=!~;\[\]\s]", lowered, maxsplit=1)[0].strip()
        if package_name in skip_names:
            continue
        lines.append(raw)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix="-gotchat-requirements.txt")
    with handle:
        handle.write("\n".join(lines))
        handle.write("\n")
    return Path(handle.name)


def _pip_install(job: Job, env_python: Path, cfg: Dict[str, Any]) -> None:
    pip_cmd = [str(env_python), "-m", "pip"]
    py_version = _python_version_text(env_python)
    if py_version:
        job.line(f"Python environment version: {py_version}")
    detection = detect_environment(cfg)
    tools = detection.get("tools") if isinstance(detection.get("tools"), dict) else {}
    current_py_signature = python_setup_signature(cfg)
    installed_py_signature = str(cfg.get("installed_python_signature") or "").strip()
    python_plan_changed = bool(installed_py_signature and installed_py_signature != current_py_signature)
    core_keys = ["pip_ready", "llama_cpp_ready", "torch_ready", "torch_plan_ready"]
    if _platform_key() == "macos":
        core_keys.append("numpy_torch_compatible")
    core_ready = all(bool(tools.get(key)) for key in core_keys)
    media_ready = all(
        bool(tools.get(key))
        for key in ("diffusers_ready", "transformers_ready", "accelerate_ready", "safetensors_ready")
    )
    if not installed_py_signature and core_ready and (not bool(cfg.get("install_media_packages", False)) or media_ready):
        job.line("Python packages already import correctly; recording current Python package plan.")
        cfg["installed_python_signature"] = current_py_signature
        return
    if not python_plan_changed and core_ready and (not bool(cfg.get("install_media_packages", False)) or media_ready):
        job.line("Python packages already match the selected setup; skipping pip installs.")
        return
    if python_plan_changed:
        job.line("Python package plan changed; updating pip packages for the selected GPU/setup.")
    pip_version = _pip_version_tuple(env_python)
    pip_too_old = bool(pip_version and pip_version < (24, 3))
    if python_plan_changed or not bool(tools.get("pip_ready")) or pip_too_old:
        job.set_progress("Upgrading pip tooling", 5)
        if pip_too_old:
            job.line(f"pip is {'.'.join(str(part) for part in pip_version)}; upgrading before installing wheels.")
        code = _stream_command(job, pip_cmd + ["install", "--upgrade", "pip", "setuptools", "wheel"], cwd=ROOT)
        if code != 0:
            raise RuntimeError(f"pip bootstrap failed with exit code {code}")
    if python_plan_changed or not core_ready:
        filtered_req = _filtered_requirements_file(cfg)
        req_cmd = pip_cmd + ["install", "-r", str(filtered_req)]
        if _platform_key() == "macos":
            job.set_progress("Installing macOS binary prerequisites", 6)
            numpy_cmd = pip_cmd + ["install", "--upgrade", "--force-reinstall", "numpy<2"]
            code = _stream_command(job, numpy_cmd, cwd=ROOT)
            if code != 0:
                raise RuntimeError("numpy<2 install failed. PyTorch on this macOS setup requires NumPy 1.x compatibility.")
            crypto_cmd = pip_cmd + ["install", "--only-binary=:all:", "--upgrade", "cryptography"]
            code = _stream_command(job, crypto_cmd, cwd=ROOT)
            if code != 0:
                raise RuntimeError(
                    "cryptography binary wheel install failed. Avoid source builds on macOS by using Python 3.11/3.12 "
                    "for your Mac architecture, or install Homebrew pkgconf/openssl if you intentionally want native builds."
                )
            req_cmd = pip_cmd + ["install", "--prefer-binary", "-r", str(filtered_req)]
        job.set_progress("Installing app requirements", 6)
        code = _stream_command(job, req_cmd, cwd=ROOT)
        if code != 0:
            raise RuntimeError(f"requirements install failed with exit code {code}")
    tplan = torch_plan(cfg)
    if python_plan_changed or not bool(tools.get("torch_plan_ready")):
        torch_cmd = pip_cmd + list(tplan.get("command") or [])
        job.set_progress(f"Installing PyTorch ({tplan.get('backend')})", 7)
        code = _stream_command(job, torch_cmd, cwd=ROOT)
        if code != 0:
            raise RuntimeError(f"torch install failed with exit code {code}")
    else:
        job.line(f"PyTorch already importable; skipping torch install ({tplan.get('backend')}).")
    if bool(cfg.get("install_media_packages", False)) and (python_plan_changed or not media_ready):
        media_packages = ["diffusers", "transformers", "accelerate", "safetensors"]
        job.set_progress("Installing image/video helper packages", 8)
        code = _stream_command(job, pip_cmd + ["install", *media_packages], cwd=ROOT)
        if code != 0:
            raise RuntimeError(f"media packages install failed with exit code {code}")
    plan = llama_cpp_plan(cfg)
    if python_plan_changed or not bool(tools.get("llama_cpp_ready")):
        if _platform_key() == "macos" and int(tools.get("apple_clang_major") or 0) and int(tools.get("apple_clang_major") or 0) < 15:
            raise RuntimeError(_macos_old_apple_clang_message(str(tools.get("apple_clang_version") or "")))
        llama_env = os.environ.copy()
        if plan.get("cmake_args"):
            llama_env["CMAKE_ARGS"] = str(plan["cmake_args"])
            job.line(f"CMAKE_ARGS={llama_env['CMAKE_ARGS']}")
        job.set_progress(f"Installing llama-cpp-python ({plan.get('backend')})", 9)
        llama_cmd = pip_cmd + ["install", str(plan.get("package") or "llama-cpp-python"), "--no-cache-dir"]
        if python_plan_changed:
            llama_cmd.append("--force-reinstall")
        job.detected_apple_clang_version = ""
        code = _stream_command(job, llama_cmd, cwd=ROOT, env=llama_env)
        if code != 0:
            detected_clang = str(getattr(job, "detected_apple_clang_version", "") or "")
            if _platform_key() == "macos" and _apple_clang_major(detected_clang) and _apple_clang_major(detected_clang) < 15:
                raise RuntimeError(_macos_old_apple_clang_message(detected_clang))
            raise RuntimeError(f"llama-cpp-python install failed with exit code {code}")
    else:
        job.line(f"llama-cpp-python already importable; skipping install ({plan.get('backend')}).")
    cfg["installed_python_signature"] = current_py_signature


def run_install_job(cfg: Dict[str, Any]) -> None:
    JOB.status = "running"
    JOB.summary = {}
    JOB.started_at = time.time()
    JOB.finished_at = 0.0
    JOB.current_command = ""
    JOB.set_progress("Saving setup configuration", 1, 10)
    try:
        save_config(cfg)
        JOB.line("starting setup")
        JOB.set_progress("Checking system", 2)
        detection = detect_environment(cfg)
        JOB.line(json.dumps(detection, indent=2))
        JOB.set_progress("Installing system packages", 3)
        _install_linux_packages(JOB, cfg)
        JOB.set_progress("Creating Python environment", 4)
        env_python = _create_venv(JOB, cfg)
        _pip_install(JOB, env_python, cfg)
        JOB.set_progress("Final verification", 10)
        cfg["installed_signature"] = setup_signature(cfg)
        cfg["last_detection"] = detect_environment(cfg)
        cfg["install_ready"] = bool(cfg["last_detection"].get("install_ready"))
        save_config(cfg)
        JOB.summary = {"ok": True, "config": cfg, "install_ready": bool(cfg.get("install_ready"))}
        JOB.status = "complete"
        JOB.finished_at = time.time()
        JOB.phase = "Complete"
        JOB.step = JOB.total_steps
        JOB.line("setup complete")
    except Exception as exc:
        error_text = str(exc)
        JOB.summary = {"ok": False, "error": error_text}
        if _platform_key() == "macos" and "AppleClang is too old" in error_text:
            JOB.summary["action"] = "macos_clt_update"
            JOB.summary["detection"] = detect_environment(cfg)
        JOB.status = "failed"
        JOB.finished_at = time.time()
        JOB.phase = "Failed"
        JOB.current_command = ""
        JOB.line(f"ERROR: {exc}")


def start_install(cfg: Dict[str, Any]) -> Dict[str, Any]:
    if JOB.thread and JOB.thread.is_alive():
        return {"ok": False, "error": "job already running"}
    JOB.history = []
    while not JOB.logs.empty():
        try:
            JOB.logs.get_nowait()
        except Exception:
            break
    JOB.thread = threading.Thread(target=run_install_job, args=(cfg,), daemon=True)
    JOB.thread.start()
    return {"ok": True, "job_id": JOB.id}


def browse_directory(current: str = "") -> str:
    initial = str(current or "").strip()
    if initial and not os.path.isdir(str(Path(initial).expanduser())):
        initial = str(Path(initial).expanduser().parent)
    if not initial or not os.path.isdir(str(Path(initial).expanduser())):
        initial = str(ROOT)
    initial_path = Path(initial).expanduser()
    if _platform_key() == "macos":
        script = (
            'set startFolder to POSIX file '
            + json.dumps(str(initial_path))
            + '\nset chosenFolder to choose folder with prompt "Choose setup folder" default location startFolder\n'
            + 'return POSIX path of chosenFolder\n'
        )
        result = _run_capture(["osascript", "-e", script], timeout=120.0)
        output = str(result.get("output") or "").strip()
        if result.get("ok") and output:
            return output.rstrip("/")
        if "User canceled" in output:
            return ""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        raise RuntimeError(f"folder picker is not available on this system: {exc}") from exc
    root = tk.Tk()
    root.withdraw()
    try:
        chosen = filedialog.askdirectory(initialdir=str(initial_path), title="Choose setup folder")
        return str(chosen or "")
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def _port_free(port: int, host: str = "127.0.0.1") -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(0.3)
        return sock.connect_ex((host, int(port))) != 0
    finally:
        sock.close()


def _ensure_linux_script_permissions() -> None:
    if os.name == "nt":
        return
    for path in (ROOT / "start_setup_wizard.sh", ROOT / "llama_server" / "start_host_service.sh"):
        try:
            if not path.is_file():
                continue
            mode = path.stat().st_mode
            if mode & 0o100:
                continue
            path.chmod(mode | 0o100)
        except Exception:
            pass


def _spawn(cmd: List[str], *, cwd: Path, env: Dict[str, str]) -> subprocess.Popen:
    flags = 0
    kwargs: Dict[str, Any] = {}
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP
        kwargs["creationflags"] = flags
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)


def _spawn_logged(name: str, cmd: List[str], *, cwd: Path, env: Dict[str, str]) -> tuple[subprocess.Popen, Path]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{name}.log"
    flags = 0
    kwargs: Dict[str, Any] = {}
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP
        kwargs["creationflags"] = flags
    else:
        kwargs["start_new_session"] = True
    log_file = log_path.open("ab")
    try:
        stamp = f"\n\n[setup_wizard] {_now()} starting: {' '.join(cmd)}\n".encode("utf-8", errors="replace")
        log_file.write(stamp)
        log_file.flush()
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            **kwargs,
        )
        return proc, log_path
    finally:
        log_file.close()


def _run_service_command(cmd: List[str], *, cwd: Path, env: Dict[str, str], timeout_s: float = 60.0) -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        return {"ok": proc.returncode == 0, "code": proc.returncode, "output": proc.stdout or ""}
    except Exception as exc:
        return {"ok": False, "code": -1, "output": str(exc)}


def _wait_http(url: str, timeout_s: float = 30.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if 200 <= int(getattr(resp, "status", 200)) < 500:
                    return True
        except urllib.error.HTTPError as exc:
            if 200 <= int(getattr(exc, "code", 500)) < 500:
                return True
        except Exception:
            time.sleep(0.5)
    return False


def _wait_http_stable(url: str, timeout_s: float = 30.0, stable_checks: int = 3) -> bool:
    deadline = time.time() + timeout_s
    ok_count = 0
    while time.time() < deadline:
        if _wait_http(url, timeout_s=2.0):
            ok_count += 1
            if ok_count >= stable_checks:
                return True
        else:
            ok_count = 0
        time.sleep(0.75)
    return False


def _wait_process_http_stable(
    proc: subprocess.Popen,
    urls: List[str],
    timeout_s: float = 30.0,
    stable_checks: int = 3,
) -> bool:
    deadline = time.time() + timeout_s
    ok_count = 0
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        if any(_wait_http(url, timeout_s=1.5) for url in urls):
            ok_count += 1
            if ok_count >= stable_checks:
                return True
        else:
            ok_count = 0
        time.sleep(0.75)
    return False


def _stop_process(proc: Optional[subprocess.Popen]) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _pid_exists(pid: int) -> bool:
    try:
        pid = int(pid or 0)
    except Exception:
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        result = _run_capture(["tasklist", "/FI", f"PID eq {pid}"], timeout=5.0)
        return str(pid) in str(result.get("output") or "")
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def _stop_pid_tree(pid: int, *, timeout_s: float = 5.0) -> Dict[str, Any]:
    try:
        pid = int(pid or 0)
    except Exception:
        pid = 0
    if pid <= 0:
        return {"ok": False, "pid": pid, "error": "invalid_pid"}
    if not _pid_exists(pid):
        return {"ok": True, "pid": pid, "already_stopped": True}
    if os.name == "nt":
        result = _run_capture(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=timeout_s)
        return {"ok": bool(result.get("ok")) or not _pid_exists(pid), "pid": pid, "result": result}
    errors: List[str] = []
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return {"ok": True, "pid": pid, "already_stopped": True}
    except Exception as exc:
        errors.append(f"SIGTERM group: {exc}")
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception as inner:
            errors.append(f"SIGTERM pid: {inner}")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not _pid_exists(pid):
            return {"ok": True, "pid": pid, "errors": errors}
        time.sleep(0.2)
    try:
        os.killpg(pid, signal.SIGKILL)
    except Exception as exc:
        errors.append(f"SIGKILL group: {exc}")
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception as inner:
            errors.append(f"SIGKILL pid: {inner}")
    return {"ok": not _pid_exists(pid), "pid": pid, "errors": errors}


def _read_llama_shared_token() -> str:
    token_path = ROOT / "llama_server" / "shared_token.json"
    try:
        data = _read_json(token_path, {})
        return str((data or {}).get("token") or "").strip()
    except Exception:
        return ""


def _llama_manager_request(path: str, payload: Optional[Dict[str, Any]] = None, *, timeout_s: float = 4.0) -> Dict[str, Any]:
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    token = _read_llama_shared_token()
    if token:
        headers["X-Client-Service-Token"] = token
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    method = "POST" if payload is not None else "GET"
    req = urllib.request.Request(f"http://127.0.0.1:8767{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        body = resp.read() or b"{}"
    return json.loads(body.decode("utf-8", errors="replace"))


def _stop_managed_llama_servers() -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    try:
        status = _llama_manager_request("/v1/llama_server/status", timeout_s=4.0)
    except Exception as exc:
        return [{"ok": False, "stage": "status", "error": str(exc)}]
    servers = status.get("servers") if isinstance(status.get("servers"), list) else []
    for server in servers:
        if not isinstance(server, dict):
            continue
        server_id = str(server.get("id") or "").strip()
        if not server_id:
            continue
        try:
            results.append({"server_id": server_id, **_llama_manager_request("/v1/llama_server/server/stop", {"server_id": server_id}, timeout_s=8.0)})
        except Exception as exc:
            results.append({"ok": False, "server_id": server_id, "error": str(exc)})
    return results


def _read_stack_pid_state() -> Dict[str, Any]:
    path = ROOT / "host_services" / "stack_pids.json"
    try:
        payload = _read_json(path, {})
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _remove_stack_pid_state() -> None:
    path = ROOT / "host_services" / "stack_pids.json"
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


def stop_services(*, remove_pid_file: bool = True, force: bool = False) -> Dict[str, Any]:
    state = _read_json(PID_PATH, {})
    if not force and (not isinstance(state, dict) or not state):
        return {"ok": True, "skipped": True, "reason": "no setup wizard service record found"}
    pids = state.get("pids") if isinstance(state.get("pids"), dict) else {}
    stack_pids = _read_stack_pid_state()
    results: Dict[str, Any] = {"ok": True, "pids": {}, "stack_pids": {}, "managed_llama_servers": []}
    for name in ("serve_chat_js", "launch_stack"):
        pid = int((pids or {}).get(name) or 0)
        if pid > 0:
            results["pids"][name] = _stop_pid_tree(pid)
    for name in ("uvicorn_pid", "vllm_pid"):
        pid = int((stack_pids or {}).get(name) or 0)
        if pid > 0:
            results["stack_pids"][name] = _stop_pid_tree(pid)
    results["managed_llama_servers"] = _stop_managed_llama_servers()
    if os.name == "nt":
        host_cmd = [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "llama_server" / "start_host_service.ps1"),
            "stop",
        ]
    else:
        host_cmd = ["bash", str(ROOT / "llama_server" / "start_host_service.sh"), "stop"]
    results["llama_host_service"] = _run_service_command(host_cmd, cwd=ROOT, env=os.environ.copy(), timeout_s=30.0)
    if remove_pid_file:
        try:
            PID_PATH.unlink(missing_ok=True)
        except Exception:
            pass
        _remove_stack_pid_state()
    results["ok"] = True
    return results


def cleanup_started_services() -> Dict[str, Any]:
    global _CLEANUP_DONE
    with _CLEANUP_LOCK:
        if _CLEANUP_DONE:
            return {"ok": True, "skipped": True, "reason": "cleanup already ran"}
        _CLEANUP_DONE = True
    if not PID_PATH.is_file():
        return {"ok": True, "skipped": True, "reason": "no setup wizard service record found"}
    return stop_services(remove_pid_file=True)


def install_windows_console_cleanup_handler() -> None:
    global _WINDOWS_CONSOLE_HANDLER
    if os.name != "nt" or _WINDOWS_CONSOLE_HANDLER is not None:
        return
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return

    handler_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

    @handler_type
    def _handler(_ctrl_type):
        try:
            cleanup_started_services()
        except Exception:
            pass
        return False

    try:
        if ctypes.windll.kernel32.SetConsoleCtrlHandler(_handler, True):
            _WINDOWS_CONSOLE_HANDLER = _handler
    except Exception:
        _WINDOWS_CONSOLE_HANDLER = None


def _tail_text(path: Path, limit: int = 4000) -> str:
    try:
        if not path.is_file():
            return ""
        data = path.read_bytes()
        return data[-limit:].decode("utf-8", errors="replace")
    except Exception:
        return ""


def start_services(cfg: Dict[str, Any]) -> Dict[str, Any]:
    _ensure_linux_script_permissions()
    detection = detect_environment(cfg)
    if not bool(detection.get("install_ready")):
        return {
            "ok": False,
            "error": "packages are not fully installed yet",
            "detection": detection,
        }
    if PID_PATH.is_file():
        stop_services(remove_pid_file=True)
    env_python = _venv_python(Path(str(cfg.get("env_dir") or "")))
    python_cmd = str(env_python if env_python.is_file() else Path(sys.executable))
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    pids: Dict[str, int] = {}
    if os.name == "nt":
        host_cmd = [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "llama_server" / "start_host_service.ps1"),
            "restart",
            "-Python",
            python_cmd,
        ]
    else:
        host_cmd = ["bash", str(ROOT / "llama_server" / "start_host_service.sh"), "restart", "--python", python_cmd]
    host_result = _run_service_command(host_cmd, cwd=ROOT, env=env, timeout_s=90.0)
    llama_host_ready = _wait_http_stable("http://127.0.0.1:8767/health", timeout_s=20.0, stable_checks=3)
    if not host_result.get("ok") or not llama_host_ready:
        return {
            "ok": False,
            "error": "llama host service did not become reachable on http://127.0.0.1:8767",
            "host_command": host_cmd,
            "host_result": host_result,
            "llama_host_ready": llama_host_ready,
            "host_log_tail": _tail_text(ROOT / "llama_server" / "host_service.log"),
            "host_err_tail": _tail_text(ROOT / "llama_server" / "host_service.err.log"),
        }
    backend, backend_log = _spawn_logged("launch_stack", [python_cmd, str(ROOT / "launch_stack.py")], cwd=ROOT, env=env)
    pids["launch_stack"] = backend.pid
    chat_port = 8080
    while not _port_free(chat_port) and chat_port < 8090:
        chat_port += 1
    env["LLMLOADER2_GUI_BACKEND_BASE"] = "http://127.0.0.1:8000"
    chat, chat_log = _spawn_logged(
        "serve_chat_js",
        [python_cmd, str(ROOT / "gui_js" / "serve_chat_js.py"), "--host", "127.0.0.1", "--port", str(chat_port)],
        cwd=ROOT,
        env=env,
    )
    pids["serve_chat_js"] = chat.pid
    chat_url = f"http://127.0.0.1:{chat_port}/"
    backend_ready = _wait_process_http_stable(
        backend,
        ["http://127.0.0.1:8000/health", "http://127.0.0.1:8000/v1/auth/ping"],
        timeout_s=60.0,
        stable_checks=3,
    )
    if not backend_ready:
        _stop_process(chat)
        _stop_process(backend)
        return {
            "ok": False,
            "error": "backend did not become reachable on http://127.0.0.1:8000",
            "pids": pids,
            "backend_exit_code": backend.poll(),
            "backend_log_path": str(backend_log),
            "backend_log_tail": _tail_text(backend_log, limit=8000),
            "host_result": host_result,
        }
    frontend_ready = _wait_process_http_stable(chat, [chat_url], timeout_s=25.0, stable_checks=2)
    if not frontend_ready:
        _stop_process(chat)
        _stop_process(backend)
        return {
            "ok": False,
            "error": f"chat frontend did not become reachable on {chat_url}",
            "pids": pids,
            "frontend_exit_code": chat.poll(),
            "frontend_log_path": str(chat_log),
            "frontend_log_tail": _tail_text(chat_log, limit=8000),
            "backend_log_path": str(backend_log),
            "backend_log_tail": _tail_text(backend_log, limit=8000),
            "host_result": host_result,
            "backend_ready": backend_ready,
        }
    if frontend_ready:
        try:
            webbrowser.open(chat_url)
        except Exception:
            pass
    _write_json(
        PID_PATH,
        {
            "updated_at": _now(),
            "pids": pids,
            "chat_url": chat_url,
            "llama_host_ready": llama_host_ready,
            "host_result": host_result,
            "backend_ready": backend_ready,
            "frontend_ready": frontend_ready,
            "backend_log_path": str(backend_log),
            "frontend_log_path": str(chat_log),
        },
    )
    cfg["services"] = {
        "backend_url": "http://127.0.0.1:8000",
        "chat_url": chat_url,
        "llama_host_url": "http://127.0.0.1:8767",
        "ports": {
            "chat_api_backend": 8000,
            "chat_js_frontend": chat_port,
            "llama_host_service": 8767,
        },
        "updated_at": _now(),
    }
    save_config(cfg)
    return {
        "ok": True,
        "pids": pids,
        "chat_url": chat_url,
        "llama_host_ready": llama_host_ready,
        "host_result": host_result,
        "backend_ready": backend_ready,
        "frontend_ready": frontend_ready,
        "backend_log_path": str(backend_log),
        "frontend_log_path": str(chat_log),
    }


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GotChat Foundry Setup Wizard</title>
  <style>
    :root { color-scheme: light; --ink:#182027; --muted:#66717d; --line:#d9e0e7; --panel:#ffffff; --accent:#0f766e; --soft:#eef8f6; --warn:#8a4b08; --bad:#a12424; }
    * { box-sizing: border-box; }
    body { margin:0; font:15px/1.45 ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color:var(--ink); background:linear-gradient(145deg,#f7fafc,#edf4f2); }
    main { max-width: 980px; margin: 0 auto; padding: 32px 18px; }
    h1 { font-size: 30px; margin: 0 0 8px; }
    h2 { font-size: 20px; margin: 0 0 12px; }
    p { color: var(--muted); }
    .shell { background:var(--panel); border:1px solid var(--line); border-radius:8px; box-shadow:0 12px 28px rgba(25,42,54,.08); overflow:hidden; }
    .steps { display:grid; grid-template-columns:repeat(4,1fr); border-bottom:1px solid var(--line); background:#f8fbfb; }
    .step-tab { padding:14px 12px; border:0; background:transparent; text-align:left; font-weight:650; color:var(--muted); }
    .step-tab.active { color:var(--accent); background:var(--soft); }
    .page { display:none; padding:24px; }
    .page.active { display:block; }
    .field { display:grid; gap:7px; margin:14px 0; }
    label { font-weight:650; }
    input, select { width:100%; padding:10px 12px; border:1px solid var(--line); border-radius:6px; background:white; font:inherit; }
    button { border:0; border-radius:6px; padding:10px 14px; font-weight:700; cursor:pointer; background:var(--accent); color:white; }
    button.secondary { background:#e8eef0; color:var(--ink); }
    button:disabled { opacity:.55; cursor:not-allowed; }
    button.loading { display:inline-flex; align-items:center; gap:8px; }
    button.loading::before { content:""; width:14px; height:14px; border-radius:50%; border:2px solid rgba(255,255,255,.45); border-top-color:#fff; animation:spin .8s linear infinite; }
    .row { display:flex; gap:10px; flex-wrap:wrap; align-items:center; padding-top:18px; }
    .path-row { display:grid; grid-template-columns:1fr auto; gap:8px; align-items:center; }
    .check-row { display:flex; gap:10px; align-items:flex-start; margin:14px 0; }
    .check-row input { width:auto; margin-top:4px; }
    .notice { border:1px solid var(--line); background:#fbfdfd; padding:14px; border-radius:8px; }
    .warn { color:var(--warn); }
    .bad { color:var(--bad); }
    pre { overflow:auto; max-height:360px; background:#101820; color:#d7f7ef; padding:14px; border-radius:8px; white-space:pre-wrap; }
    .progress-wrap { margin-top:14px; border:1px solid var(--line); border-radius:8px; padding:12px; background:#fbfdfd; }
    .progress-meta { display:flex; justify-content:space-between; gap:10px; flex-wrap:wrap; font-weight:700; }
    .progress-bar { height:12px; background:#e5ecef; border-radius:999px; overflow:hidden; margin-top:10px; }
    .progress-fill { height:100%; width:0%; background:var(--accent); transition:width .25s ease; }
    .command-line { color:var(--muted); margin-top:8px; overflow-wrap:anywhere; }
    .grid { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
    @keyframes spin { to { transform:rotate(360deg); } }
    @media (max-width:760px){ .steps,.grid{grid-template-columns:1fr;} }
  </style>
</head>
<body>
<main>
  <h1>GotChat Foundry Setup Wizard</h1>
  <p>This prepares a local Python environment, embedded GGUF support, and the local chat services for this machine.</p>
  <section class="shell">
    <nav class="steps">
      <button class="step-tab active" data-step="0">1. Welcome</button>
      <button class="step-tab" data-step="1">2. Install Path</button>
      <button class="step-tab" data-step="2">3. GPU</button>
      <button class="step-tab" data-step="3">4. Install</button>
    </nav>
    <section class="page active" data-page="0">
      <h2>Package Installation</h2>
      <p>This wizard installs packages into a Python virtual environment. It may also install system libraries such as Vulkan headers/tools on Linux when your GPU choice needs them.</p>
      <div class="notice">No packages are installed until you reach the final step and press Install.</div>
      <div class="row"><button data-next>Continue</button></div>
    </section>
    <section class="page" data-page="1">
      <h2>Install Path</h2>
      <p>Choose the folder that will hold the Python environment. The app will run from this project folder using that environment.</p>
      <div class="field"><label>Install root</label><div class="path-row"><input id="installRoot"><button class="secondary" data-browse="installRoot" type="button">Browse</button></div></div>
      <div class="field"><label>Python environment path</label><div class="path-row"><input id="envDir"><button class="secondary" data-browse="envDir" type="button">Browse</button></div></div>
      <div id="pathStatus" class="notice"></div>
      <div class="row"><button class="secondary" data-prev>Back</button><button data-next>Continue</button></div>
    </section>
    <section class="page" data-page="2">
      <h2>GPU Questionnaire</h2>
      <div class="grid">
        <div class="field"><label>GPU Brand</label><select id="gpuBrand"></select></div>
        <div class="field"><label>Card model</label><select id="gpuModel"></select></div>
      </div>
      <div id="gpuPlan" class="notice"></div>
      <div id="detectStatus" class="notice"></div>
      <div class="row"><button class="secondary" data-prev>Back</button><button id="detectBtn">Check System</button><button data-next>Continue</button></div>
    </section>
    <section class="page" data-page="3">
      <h2>Library Installation</h2>
      <div id="detectOut" class="notice"></div>
      <label class="check-row"><input id="installMedia" type="checkbox"><span>Install image/video generation helpers: diffusers, transformers, accelerate, safetensors.</span></label>
      <div class="row"><button class="secondary" data-prev>Back</button><button id="cltUpdateBtn" hidden>Update Apple Command Line Tools</button><button id="installBtn">Install Packages</button><button id="startBtn" hidden>Start Services</button></div>
      <div class="progress-wrap">
        <div class="progress-meta"><span id="phase">Idle</span><span id="percent">0%</span></div>
        <div class="progress-bar"><div id="progressFill" class="progress-fill"></div></div>
        <div id="commandLine" class="command-line"></div>
      </div>
      <pre id="log"></pre>
      <div id="done" class="notice"></div>
    </section>
  </section>
</main>
<script>
const GPU_MODELS = __GPU_MODELS__;
let cfg = {};
let step = 0;
let macToolsPromptShown = false;
let installDetectTimer = null;
let installDetectInFlight = false;
let installJobActive = false;
const $ = (id) => document.getElementById(id);
try { if ('scrollRestoration' in history) history.scrollRestoration = 'manual'; } catch(e) {}
function applyDetectionToUi(detection, options = {}) {
  cfg.last_detection = detection;
  updatePathStatus(detection);
  setMacToolsUpdateVisible(Boolean(detection.macos_clt_update_required));
  const missing = detection.missing_system_packages || [];
  const warnings = detection.warnings || [];
  $('detectOut').innerHTML = missing.length
    ? `<b>Missing system packages:</b> ${missing.join(', ')}`
    : `<b>System package check:</b> ready or no OS packages required.`;
  $('detectOut').innerHTML += `<br><b>llama-cpp-python:</b> ${detection.plan.backend} ${detection.plan.cmake_args || ''}`;
  $('detectOut').innerHTML += `<br><b>PyTorch:</b> ${detection.torch_plan.backend} ${(detection.torch_plan.command || []).join(' ')}`;
  $('detectOut').innerHTML += `<br><b>Installed PyTorch matches plan:</b> ${detection.tools?.torch_plan_ready ? 'yes' : 'no'}`;
  if (detection.platform === 'macos') {
    $('detectOut').innerHTML += `<br><b>NumPy:</b> ${detection.tools?.numpy_version || 'not installed'} (${detection.tools?.numpy_torch_compatible ? 'Torch compatible' : 'needs numpy<2'})`;
  }
  if (detection.torch_plan.reason) {
    $('detectOut').innerHTML += `<br><b class="warn">PyTorch fallback:</b> ${detection.torch_plan.reason}`;
  }
  $('detectOut').innerHTML += `<br><b>Install ready:</b> ${detection.install_ready ? 'yes' : 'no'}`;
  if (detection.config_matches_installed === false) {
    $('detectOut').innerHTML += `<br><b class="warn">Setup changed:</b> install/update packages before starting services.`;
  }
  $('detectOut').innerHTML += renderPrerequisites(detection.prerequisites);
  if (warnings.length) $('detectOut').innerHTML += `<br><b class="warn">Warnings:</b> ${warnings.join(' ')}`;
  cfg.install_ready = Boolean(detection.install_ready);
  setStartServicesVisible(Boolean(detection.install_ready));
  if (options.skipStatus) return;
  if (options.autoRefresh) {
    $('done').innerHTML = detection.install_ready
      ? '<b>Background check:</b> requirements are satisfied and the current setup is ready.'
      : '<b>Background check:</b> requirement status refreshed.';
    return;
  }
  $('detectStatus').innerHTML = detection.install_ready
    ? '<b>System check complete.</b> Packages already match this setup. You can start services from the Install step.'
    : detection.macos_clt_update_required
      ? '<b class="warn">Apple Command Line Tools update required.</b> Continue to the Install step and click Update Apple Command Line Tools before installing packages.'
      : '<b>System check complete.</b> Continue to the Install step to install or update the missing packages.';
}
async function refreshInstallDetection(options = {}) {
  if (installDetectInFlight || installJobActive || document.hidden) return;
  installDetectInFlight = true;
  try {
    cfg = (await api('/api/config', collect())).config;
    const data = await api('/api/detect');
    applyDetectionToUi(data.detection, { autoRefresh: Boolean(options.autoRefresh), skipStatus: Boolean(options.skipStatus) });
  } catch (err) {
  } finally {
    installDetectInFlight = false;
  }
}
function stopInstallDetectRefresh() {
  if (installDetectTimer) {
    window.clearInterval(installDetectTimer);
    installDetectTimer = null;
  }
}
function startInstallDetectRefresh() {
  if (step !== 3 || installJobActive) {
    stopInstallDetectRefresh();
    return;
  }
  stopInstallDetectRefresh();
  refreshInstallDetection({ autoRefresh: true, skipStatus: true });
  installDetectTimer = window.setInterval(() => {
    if (step !== 3 || installJobActive || document.hidden) return;
    refreshInstallDetection({ autoRefresh: true, skipStatus: true });
  }, 3000);
}
function page(n, options = {}){
  step = Math.max(0, Math.min(3, Number(n) || 0));
  document.querySelectorAll('.page').forEach(x=>x.classList.toggle('active', x.dataset.page==step));
  document.querySelectorAll('.step-tab').forEach(x=>x.classList.toggle('active', x.dataset.step==step));
  if (step === 3 && !installJobActive) startInstallDetectRefresh();
  else stopInstallDetectRefresh();
  if (options.save !== false) saveDraft();
}
function resetToWelcomeStep() {
  page(0, { save: false });
}
resetToWelcomeStep();
document.addEventListener('DOMContentLoaded', resetToWelcomeStep);
window.addEventListener('load', resetToWelcomeStep);
window.addEventListener('pageshow', resetToWelcomeStep);
setTimeout(resetToWelcomeStep, 0);
setTimeout(resetToWelcomeStep, 250);
document.querySelectorAll('[data-next]').forEach(b=>b.onclick=()=>page(Math.min(3,step+1)));
document.querySelectorAll('[data-prev]').forEach(b=>b.onclick=()=>page(Math.max(0,step-1)));
document.querySelectorAll('.step-tab').forEach(b=>b.onclick=()=>page(Number(b.dataset.step)));
async function api(path, body){
  const res = await fetch(path, { method: body ? 'POST':'GET', headers:{'Content-Type':'application/json'}, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json();
  if (!res.ok || data.ok === false) {
    const err = new Error(data.error || res.statusText);
    err.payload = data;
    throw err;
  }
  return data;
}
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}
function renderPrerequisites(prerequisites) {
  if (!Array.isArray(prerequisites) || !prerequisites.length) return '';
  const rows = prerequisites.map((item) => {
    const ok = Boolean(item?.ok);
    const required = Boolean(item?.required);
    const status = ok ? 'Ready' : (required ? 'Required' : 'Recommended');
    const cls = ok ? '' : (required ? 'bad' : 'warn');
    const links = [
      item?.url ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener">Download</a>` : '',
      item?.help_url ? `<a href="${escapeHtml(item.help_url)}" target="_blank" rel="noopener">Instructions</a>` : '',
    ].filter(Boolean).join(' | ');
    return `<div><b>${escapeHtml(item?.label || 'Prerequisite')}</b>: <span class="${cls}">${status}</span><br><span>${escapeHtml(item?.detail || '')}</span>${links ? `<br>${links}` : ''}</div>`;
  }).join('<hr>');
  return `<br><b>Windows prerequisites:</b><div class="notice">${rows}</div>`;
}
function syncModels(){
  const brand = $('gpuBrand').value;
  $('gpuModel').innerHTML = '';
  for (const model of GPU_MODELS[brand] || []) {
    const opt = document.createElement('option'); opt.value=model; opt.textContent=model; $('gpuModel').appendChild(opt);
  }
  if (cfg.gpu_model) $('gpuModel').value = cfg.gpu_model;
  renderPlan();
}
function collect(){
  return {
    install_root:$('installRoot').value.trim(),
    env_dir:$('envDir').value.trim(),
    gpu_brand:$('gpuBrand').value,
    gpu_model:$('gpuModel').value,
    install_media_packages:Boolean($('installMedia')?.checked),
  };
}
function updatePathStatus(detection) {
  const status = $('pathStatus');
  if (!status) return;
  const envPath = $('envDir')?.value?.trim() || cfg.env_dir || '';
  const tools = detection?.tools || cfg.last_detection?.tools || {};
  const exists = Boolean(tools.venv_exists);
  const pythonPath = tools.venv_python || (envPath ? `${envPath}/bin/python` : '');
  const hiddenNote = envPath.includes('/.') ? ' On macOS, folders beginning with a dot are hidden in Finder; press Cmd+Shift+. to show them.' : '';
  status.innerHTML = exists
    ? `<b>Python environment found.</b> ${envPath}<br><b>Python:</b> ${pythonPath}${hiddenNote}`
    : `<b>Python environment will be created during Install Packages.</b> ${envPath || '(not selected yet)'}${hiddenNote}`;
}
async function saveDraft(){
  try {
    cfg = (await api('/api/config', collect())).config;
    renderPlan();
    setStartServicesVisible(Boolean(cfg.install_ready));
    updatePathStatus(cfg.last_detection);
  } catch(e){}
}
function setStartServicesVisible(visible) {
  $('startBtn').hidden = !visible;
  $('installBtn').hidden = Boolean(visible);
}
function setMacToolsUpdateVisible(visible) {
  const btn = $('cltUpdateBtn');
  if (!btn) return;
  btn.hidden = !visible;
  if ($('installBtn')) $('installBtn').disabled = Boolean(visible);
}
function appleClangUpdateMessage(detection) {
  const version = detection?.tools?.apple_clang_version || 'the current AppleClang version';
  return `macOS needs to update Apple Command Line Tools before llama-cpp-python can build.\n\nDetected: ${version}\n\nOpen Apple's installer or Software Update now?`;
}
async function openMacToolsUpdater(detection) {
  if (!confirm(appleClangUpdateMessage(detection))) return false;
  const btn = $('cltUpdateBtn');
  const oldText = btn ? btn.textContent : '';
  try {
    if (btn) {
      btn.disabled = true;
      btn.classList.add('loading');
      btn.textContent = 'Opening updater...';
    }
    const data = await api('/api/macos_clt_update', {});
    $('done').innerHTML = `<b>Apple update prompt opened.</b> ${data.message || 'Finish the update, then click Check System again.'}`;
    return true;
  } catch (err) {
    $('done').innerHTML = `<b class="bad">Could not open Apple update prompt:</b> ${err.message || err}`;
    return false;
  } finally {
    if (btn) {
      btn.classList.remove('loading');
      btn.disabled = false;
      btn.textContent = oldText || 'Update Apple Command Line Tools';
    }
  }
}
function renderPlan(){
  const brand = $('gpuBrand').value;
  const isMac = cfg.platform === 'macos';
  const isWindows = cfg.platform === 'windows';
  const isAppleSilicon = isMac && ['arm64', 'aarch64'].includes(String(cfg.machine || '').toLowerCase());
  const plannedBackend = String(cfg?.llama_cpp?.backend || '').toLowerCase();
  let backend = 'CPU';
  let torch = 'CPU';
  if (isMac && isAppleSilicon && brand === 'Apple') backend = 'Metal';
  else if (isMac) backend = 'CPU / Accelerate';
  else if (isWindows && plannedBackend) backend = plannedBackend === 'vulkan' ? 'Vulkan' : (plannedBackend === 'cuda' ? 'CUDA' : 'CPU for embedded Python; llama-server runtime can still use Vulkan separately');
  else if (brand === 'Apple') backend = 'Metal';
  if (!isWindows && brand === 'AMD') { backend = 'Vulkan'; torch = 'ROCm nightly on Linux, CPU elsewhere'; }
  if (!isWindows && brand === 'Intel') { backend = 'Vulkan'; torch = 'XPU'; }
  if (!isWindows && brand === 'Nvidia') { backend = 'CUDA when NVIDIA runtime is detected, otherwise Vulkan'; torch = 'CUDA when NVIDIA runtime is detected, otherwise CPU'; }
  if (!isWindows && (brand === 'No GPU' || brand === "I don't know")) { backend = 'Vulkan'; torch = 'CPU'; }
  if (isWindows && brand === 'Intel') torch = 'XPU';
  if (isWindows && brand === 'Nvidia') torch = 'CUDA when NVIDIA runtime is detected, otherwise CPU';
  if (isMac && isAppleSilicon && brand === 'Apple') { backend = 'Metal'; torch = 'CPU'; }
  else if (isMac) { backend = 'CPU / Accelerate'; torch = 'CPU'; }
  $('gpuPlan').textContent = `Embedded GGUF backend plan: ${backend}. Torch plan: ${torch}.`;
}
async function detect(){
  const btn = $('detectBtn');
  const oldText = btn ? btn.textContent : '';
  const startedAt = Date.now();
  try {
    if (btn) {
      btn.disabled = true;
      btn.classList.add('loading');
      btn.textContent = 'Checking system...';
    }
    $('detectStatus').innerHTML = '<b>Checking system...</b> This may take a moment while Python, GPU tools, Vulkan/CUDA/SYCL, and package state are inspected.';
    cfg = (await api('/api/config', collect())).config;
    const data = await api('/api/detect');
    const minBusyMs = 1200;
    const elapsed = Date.now() - startedAt;
    if (elapsed < minBusyMs) {
      await new Promise((resolve) => window.setTimeout(resolve, minBusyMs - elapsed));
    }
    applyDetectionToUi(data.detection);
  } catch (err) {
    const detail = err.payload?.error || err.message || String(err || 'System check failed.');
    $('detectStatus').innerHTML = `<b class="bad">System check failed:</b> ${detail}`;
    $('detectOut').innerHTML = `<b class="bad">System check failed:</b> ${detail}`;
  } finally {
    if (btn) {
      btn.classList.remove('loading');
      btn.disabled = false;
      btn.textContent = oldText || 'Check System';
    }
  }
}
async function poll(){
  const data = await api('/api/job');
  const progress = data.progress || {};
  const total = Number(progress.total_steps || 0);
  const current = Number(progress.step || 0);
  const pct = total > 0 ? Math.max(0, Math.min(100, Math.round((current / total) * 100))) : 0;
  $('phase').textContent = progress.phase || data.status || 'Idle';
  $('percent').textContent = `${pct}%`;
  $('progressFill').style.width = `${pct}%`;
  $('commandLine').textContent = progress.current_command ? `Running: ${progress.current_command}` : '';
  $('log').textContent = data.logs.join('\n');
  $('log').scrollTop = $('log').scrollHeight;
  $('installBtn').disabled = data.status === 'running';
  installJobActive = data.status === 'running';
  if (installJobActive) stopInstallDetectRefresh();
  if (data.status === 'running') setTimeout(poll, 1000);
  if (data.status === 'complete') {
    installJobActive = false;
    const ready = Boolean(data.summary?.install_ready || data.summary?.config?.install_ready);
    setStartServicesVisible(ready);
    $('done').innerHTML = ready
      ? '<b>Setup complete.</b> You can start services now.'
      : '<b>Setup finished, but readiness checks did not pass.</b> Review the log above.';
    if (step === 3 && !ready) startInstallDetectRefresh();
  }
  if (data.status === 'failed') {
    installJobActive = false;
    setStartServicesVisible(false);
    const error = data.summary.error || 'unknown error';
    const isClang = data.summary.action === 'macos_clt_update' || String(error).includes('AppleClang is too old');
    setMacToolsUpdateVisible(isClang);
    $('done').innerHTML = isClang
      ? `<b class="bad">Apple Command Line Tools update required:</b> ${error}`
      : `<b class="bad">Setup failed:</b> ${error}`;
    if (isClang && !macToolsPromptShown) {
      macToolsPromptShown = true;
      await openMacToolsUpdater(data.summary.detection || cfg?.last_detection || null);
    }
    if (step === 3) startInstallDetectRefresh();
  }
}
$('gpuBrand').onchange = () => { cfg.gpu_model=''; syncModels(); saveDraft(); };
$('gpuModel').onchange = saveDraft;
$('installRoot').onchange = saveDraft;
$('envDir').onchange = saveDraft;
$('installMedia').onchange = saveDraft;
document.querySelectorAll('[data-browse]').forEach((btn) => {
  btn.addEventListener('click', async () => {
    try {
      const target = btn.getAttribute('data-browse');
      const current = target === 'envDir' ? $('envDir').value : $('installRoot').value;
      const data = await api('/api/browse_dir', { current });
      if (!data.path || !$(target)) return;
      $(target).value = data.path;
      if (target === 'installRoot' && !$('envDir').value.trim()) $('envDir').value = `${data.path.replace(/[\\\/]+$/, '')}/.venv`;
      await saveDraft();
    } catch (err) {
      alert(`Folder picker failed: ${err.payload?.error || err.message || err}`);
    }
  });
});
$('detectBtn').onclick = detect;
$('cltUpdateBtn').onclick = async()=>{
  try {
    const data = await api('/api/detect');
    await openMacToolsUpdater(data.detection);
  } catch (err) {
    $('done').innerHTML = `<b class="bad">System check failed:</b> ${err.message || err}`;
  }
};
$('installBtn').onclick = async()=>{
  $('done').textContent='';
  $('installBtn').disabled = true;
  macToolsPromptShown = false;
  try {
    cfg = (await api('/api/config', collect())).config;
    const data = await api('/api/detect');
    if (data.detection.macos_clt_update_required) {
      setMacToolsUpdateVisible(true);
      await openMacToolsUpdater(data.detection);
      return;
    }
    setMacToolsUpdateVisible(false);
    await api('/api/install', collect());
    installJobActive = true;
    stopInstallDetectRefresh();
    poll();
  } catch (err) {
    installJobActive = false;
    if (err.payload?.action === 'macos_clt_update') {
      setMacToolsUpdateVisible(true);
      await openMacToolsUpdater(err.payload.detection);
    } else {
      $('done').innerHTML = `<b class="bad">Install failed:</b> ${err.message || err}`;
    }
  } finally {
    if (!$('cltUpdateBtn') || $('cltUpdateBtn').hidden) $('installBtn').disabled = false;
  }
};
document.addEventListener('visibilitychange', () => {
  if (document.hidden) return;
  if (step === 3 && !installJobActive) startInstallDetectRefresh();
});
$('startBtn').onclick = async()=>{
  const btn = $('startBtn');
  const oldText = btn.textContent;
  try {
    btn.disabled = true;
    btn.classList.add('loading');
    btn.textContent = 'Starting services...';
    $('done').textContent = 'Starting local services...';
    const data=await api('/api/start', collect());
    $('done').innerHTML=`<b>Services started.</b> Chat UI: <a href="${data.chat_url}" target="_blank">${data.chat_url}</a>`;
  } catch (err) {
    const payload = err.payload || {};
    const details = [
      payload.host_result?.output,
      payload.host_log_tail ? `host_service.log:\n${payload.host_log_tail}` : '',
      payload.host_err_tail ? `host_service.err.log:\n${payload.host_err_tail}` : '',
      payload.backend_log_tail ? `${payload.backend_log_path || 'launch_stack.log'}:\n${payload.backend_log_tail}` : '',
      payload.frontend_log_tail ? `${payload.frontend_log_path || 'serve_chat_js.log'}:\n${payload.frontend_log_tail}` : '',
    ].filter(Boolean).join('\n\n');
    $('done').innerHTML=`<b class="bad">Start failed:</b> ${err.message || err}`;
    if (details) $('log').textContent = details;
    setStartServicesVisible(false);
    await detect();
  } finally {
    btn.classList.remove('loading');
    btn.disabled = false;
    btn.textContent = oldText;
  }
};
async function init(){
  cfg = (await api('/api/config')).config;
  $('installRoot').value = cfg.install_root || '';
  $('envDir').value = cfg.env_dir || '';
  $('installMedia').checked = Boolean(cfg.install_media_packages);
  setStartServicesVisible(Boolean(cfg.install_ready));
  for (const brand of Object.keys(GPU_MODELS)) { const opt=document.createElement('option'); opt.value=brand; opt.textContent=brand; $('gpuBrand').appendChild(opt); }
  $('gpuBrand').value = cfg.gpu_brand || "I don't know";
  syncModels();
  page(0, { save: false });
  await detect();
  page(0, { save: false });
}
init();
</script>
</body>
</html>
"""


class WizardHandler(BaseHTTPRequestHandler):
    server_version = "GotChatSetupWizard/1.0"

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        if path in ("/", "/index.html"):
            html = INDEX_HTML.replace("__GPU_MODELS__", json.dumps(GPU_MODELS))
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/config":
            self._send_json(200, {"ok": True, "config": load_config()})
            return
        if path == "/api/detect":
            cfg = load_config()
            detection = detect_environment(cfg)
            cfg["last_detection"] = detection
            cfg["install_ready"] = bool(detection.get("install_ready"))
            if cfg["install_ready"] and not str(cfg.get("installed_signature") or "").strip():
                cfg["installed_signature"] = str(detection.get("setup_signature") or setup_signature(cfg))
            save_config(cfg)
            self._send_json(200, {"ok": True, "detection": detection})
            return
        if path == "/api/job":
            self._send_json(
                200,
                {
                    "ok": True,
                    "status": JOB.status,
                    "logs": list(JOB.history),
                    "summary": JOB.summary,
                    "progress": {
                        "phase": JOB.phase,
                        "step": JOB.step,
                        "total_steps": JOB.total_steps,
                        "current_command": JOB.current_command,
                        "started_at": JOB.started_at,
                        "finished_at": JOB.finished_at,
                    },
                },
            )
            return
        self.send_error(404)

    def do_POST(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        body = self._read_body()
        if path == "/api/config":
            cfg = save_config(body)
            self._send_json(200, {"ok": True, "config": cfg})
            return
        if path == "/api/install":
            cfg = save_config(body)
            detection = detect_environment(cfg)
            prereq_blockers = [
                item for item in (detection.get("prerequisites") or [])
                if isinstance(item, dict) and item.get("required") and not item.get("ok")
            ]
            if prereq_blockers:
                names = ", ".join(str(item.get("label") or item.get("id") or "prerequisite") for item in prereq_blockers)
                self._send_json(
                    409,
                    {
                        "ok": False,
                        "error": f"Install prerequisites are missing: {names}. Install them, reopen this wizard, then run Install Packages again.",
                        "action": "windows_prerequisites",
                        "detection": detection,
                        "prerequisites": prereq_blockers,
                    },
                )
                return
            if detection.get("macos_clt_update_required"):
                self._send_json(
                    409,
                    {
                        "ok": False,
                        "error": _macos_old_apple_clang_message(
                            str((detection.get("tools") or {}).get("apple_clang_version") or "")
                        ),
                        "action": "macos_clt_update",
                        "detection": detection,
                    },
                )
                return
            self._send_json(200, start_install(cfg))
            return
        if path == "/api/macos_clt_update":
            result = trigger_macos_clt_update()
            self._send_json(200 if result.get("ok") else 400, result)
            return
        if path == "/api/browse_dir":
            try:
                selected = browse_directory(str(body.get("current") or ""))
                self._send_json(200, {"ok": True, "path": selected})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/api/start":
            cfg = save_config(body)
            try:
                result = start_services(cfg)
                self._send_json(200 if result.get("ok") else 400, result)
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/api/stop":
            try:
                result = stop_services(remove_pid_file=True)
                self._send_json(200 if result.get("ok") else 500, result)
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        self.send_error(404)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[setup_wizard] {self.address_string()} - {fmt % args}")


def main() -> None:
    _ensure_linux_script_permissions()
    parser = argparse.ArgumentParser(description="GotChat standalone setup wizard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8095)
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--stop-services", action="store_true")
    args = parser.parse_args()
    if args.stop_services:
        result = stop_services(remove_pid_file=True)
        print(json.dumps(result, indent=2))
        return
    server = ThreadingHTTPServer((args.host, args.port), WizardHandler)
    url = f"http://{args.host}:{args.port}/"
    open_url = f"{url}?launch={int(time.time())}"
    print(f"GotChat setup wizard running at {url}")
    install_windows_console_cleanup_handler()

    def _handle_exit_signal(signum, _frame):
        raise KeyboardInterrupt

    for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _handle_exit_signal)
        except Exception:
            pass

    if not args.no_open:
        try:
            webbrowser.open(open_url, new=2)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print("Stopping GotChat services started by setup wizard...")
        try:
            result = cleanup_started_services()
            print(json.dumps(result, indent=2))
        except Exception as exc:
            print(f"Failed to stop services cleanly: {exc}")
        server.server_close()


if __name__ == "__main__":
    main()
