import argparse
import os
from pathlib import Path
import subprocess
import sys


def _env_with_overrides(bind: str, port: int, root: str) -> dict[str, str]:
    env: dict[str, str] = {}
    seen: set[str] = set()
    for key, value in os.environ.items():
        norm = key.upper()
        if norm in seen:
            continue
        seen.add(norm)
        env[key] = value
    env["LLMLOADER2_LLAMA_MANAGER_BIND"] = bind
    env["LLMLOADER2_LLAMA_MANAGER_PORT"] = str(port)
    env["LLMLOADER2_LLAMA_MANAGER_ROOT"] = root
    env.setdefault("LLMLOADER2_AUTH_ME_URL", "http://localhost:8000/v1/auth/me")
    return env


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch the llama host service as a detached process.")
    parser.add_argument("--python", required=True)
    parser.add_argument("--script", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--pid-file", required=True)
    parser.add_argument("--stdout", required=True)
    parser.add_argument("--stderr", required=True)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()

    root = str(Path(args.root).resolve())
    script = str(Path(args.script).resolve())
    Path(args.stdout).parent.mkdir(parents=True, exist_ok=True)
    Path(args.stderr).parent.mkdir(parents=True, exist_ok=True)

    creationflags = 0
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )

    env = _env_with_overrides(args.bind, args.port, root)
    with open(args.stdout, "w", encoding="utf-8") as out, open(args.stderr, "w", encoding="utf-8") as err:
        popen_kwargs = {}
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True
        proc = subprocess.Popen(
            [args.python, "-u", script],
            cwd=root,
            stdout=out,
            stderr=err,
            stdin=subprocess.DEVNULL,
            env=env,
            creationflags=creationflags,
            close_fds=True,
            **popen_kwargs,
        )

    Path(args.pid_file).write_text(str(proc.pid), encoding="utf-8")
    print(proc.pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
