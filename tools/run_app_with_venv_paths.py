from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT.parent / ".venv"
LIBRARY_BIN = VENV / "Library" / "bin"
TORCH_LIB = VENV / "Lib" / "site-packages" / "torch" / "lib"
SITE_PACKAGES = VENV / "Lib" / "site-packages"


def _prepend_env_path(value: str) -> None:
    current = os.environ.get("PATH") or ""
    parts = [p for p in current.split(os.pathsep) if p]
    if value not in parts:
        os.environ["PATH"] = value + os.pathsep + current if current else value


def _add_dll_dir(path: Path) -> None:
    if path.exists() and hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(path))


def main() -> None:
    os.environ.setdefault("VIRTUAL_ENV", str(VENV))
    current_py = os.environ.get("PYTHONPATH") or ""
    py_parts = [p for p in current_py.split(os.pathsep) if p]
    if str(SITE_PACKAGES) not in py_parts:
        os.environ["PYTHONPATH"] = (
            str(SITE_PACKAGES) + (os.pathsep + current_py if current_py else "")
        )
    if str(SITE_PACKAGES) not in sys.path:
        sys.path.insert(0, str(SITE_PACKAGES))
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    _prepend_env_path(str(LIBRARY_BIN))
    _prepend_env_path(str(VENV / "Scripts"))
    _add_dll_dir(LIBRARY_BIN)
    _add_dll_dir(TORCH_LIB)
    os.chdir(ROOT)
    sys.argv = ["app.py", *sys.argv[1:]]
    runpy.run_path(str(ROOT / "app.py"), run_name="__main__")


if __name__ == "__main__":
    main()
