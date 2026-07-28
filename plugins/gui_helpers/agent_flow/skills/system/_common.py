from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_TOOLS = [
    "powershell", "pwsh", "cmd", "python", "python3", "py", "node", "npm", "npx",
    "dotnet", "docker", "git", "rg", "curl", "where", "where.exe", "which",
]

ALLOWED_EXES = set(DEFAULT_TOOLS + ["pytest", "python.exe", "node.exe", "npm.cmd", "npx.cmd", "dotnet.exe", "docker.exe", "git.exe", "rg.exe", "curl.exe"])
BLOCK_PATTERNS = [
    r"\brm\s+-rf\b", r"\brmdir\b", r"\bdel\b", r"\bremove-item\b", r"\bformat\s+[a-z]:", r"\bshutdown\b", r"\breboot\b", r"\bgit\s+reset\s+--hard\b", r"\bgit\s+clean\b",
    r"\bdocker\s+system\s+prune\b", r"\bdocker\s+rm\b", r"\bdocker\s+rmi\b",
]


def find_tool(name: str) -> str:
    return shutil.which(str(name or "")) or ""


def availability(tools: Optional[List[str]] = None) -> Dict[str, Any]:
    rows = []
    for name in (tools or DEFAULT_TOOLS):
        path = find_tool(name)
        rows.append({"name": name, "available": bool(path), "path": path})
    return {"tools": rows, "platform": sys.platform, "cwd": os.getcwd(), "path": os.environ.get("PATH", "")}


def _split_command(command: str) -> List[str]:
    if os.name == "nt":
        return shlex.split(command, posix=False)
    return shlex.split(command, posix=True)


def is_blocked(command: str, allow_destructive: bool = False) -> Tuple[bool, str]:
    if allow_destructive:
        return False, ""
    low = str(command or "").lower()
    for pat in BLOCK_PATTERNS:
        if re.search(pat, low):
            return True, f"blocked_pattern:{pat}"
    return False, ""


def _safe_cwd(cwd: str = "") -> str:
    raw = str(cwd or "").strip()
    if not raw:
        return os.getcwd()
    path = os.path.abspath(raw)
    if not os.path.isdir(path):
        raise FileNotFoundError(f"cwd_not_found:{path}")
    return path


def run_process(command: str, *, cwd: str = "", timeout: float = 20.0, mode: str = "argv", allow_destructive: bool = False) -> Dict[str, Any]:
    command = str(command or "").strip()
    if not command:
        return {"ok": False, "data": {}, "warnings": ["command_required"]}
    blocked, reason = is_blocked(command, allow_destructive=allow_destructive)
    if blocked:
        return {"ok": False, "data": {"command": command}, "warnings": [reason]}
    workdir = _safe_cwd(cwd)
    mode = str(mode or "argv").lower()
    try:
        if mode == "powershell":
            exe = find_tool("powershell") or find_tool("pwsh")
            if not exe:
                return {"ok": False, "data": availability(["powershell", "pwsh"]), "warnings": ["powershell_unavailable"]}
            args = [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]
        elif mode == "shell":
            shell = os.environ.get("COMSPEC") if os.name == "nt" else find_tool("sh") or "/bin/sh"
            if os.name == "nt":
                args = [shell or "cmd.exe", "/c", command]
            else:
                args = [shell, "-lc", command]
        else:
            args = _split_command(command)
            if not args:
                return {"ok": False, "data": {}, "warnings": ["command_parse_failed"]}
            exe_name = os.path.basename(args[0]).lower()
            if exe_name not in ALLOWED_EXES:
                return {"ok": False, "data": {"exe": args[0], "allowed": sorted(ALLOWED_EXES)}, "warnings": ["executable_not_allowed"]}
            exe_path = find_tool(args[0]) or args[0]
            args[0] = exe_path
        start = time.time()
        proc = subprocess.run(
            args,
            cwd=workdir,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=max(1.0, min(float(timeout or 20.0), 120.0)),
        )
        return {
            "ok": proc.returncode == 0,
            "data": {
                "command": command,
                "mode": mode,
                "cwd": workdir,
                "returncode": proc.returncode,
                "stdout": proc.stdout[-20000:],
                "stderr": proc.stderr[-20000:],
                "duration_s": round(time.time() - start, 3),
            },
            "warnings": [] if proc.returncode == 0 else [f"exit_code:{proc.returncode}"],
        }
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "data": {"command": command, "stdout": (exc.stdout or "")[-12000:], "stderr": (exc.stderr or "")[-12000:]}, "warnings": ["command_timeout"]}
    except Exception as exc:
        return {"ok": False, "data": {"command": command}, "warnings": [f"command_failed:{exc}"]}


def read_text_file(path: str, max_chars: int = 20000) -> Dict[str, Any]:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        return {"ok": False, "data": {"path": str(p)}, "warnings": ["file_not_found"]}
    text = p.read_text(encoding="utf-8", errors="replace")
    return {"ok": True, "data": {"path": str(p), "size": p.stat().st_size, "text": text[:max_chars]}, "warnings": []}


