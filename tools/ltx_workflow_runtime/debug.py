from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict


def debug_run_dir(repo_root: Path, output_path: str) -> Path:
    stem = Path(str(output_path or "output")).stem or "output"
    out = repo_root / "tmp" / "ltx_debug" / stem
    out.mkdir(parents=True, exist_ok=True)
    return out


def run_log_paths(repo_root: Path, output_path: str) -> tuple[Path, Path]:
    debug_dir = debug_run_dir(repo_root, output_path)
    run_stamp = time.strftime("%Y%m%d_%H%M%S")
    pid = os.getpid()
    per_run = debug_dir / f"run_{run_stamp}_{pid}.json"
    latest = debug_dir / "latest.json"
    return per_run, latest


def write_run_log(repo_root: Path, output_path: str, payload: Dict[str, Any]) -> str:
    per_run, latest = run_log_paths(repo_root, output_path)
    text = json.dumps(payload, indent=2, sort_keys=True)
    per_run.write_text(text, encoding="utf-8")
    latest.write_text(text, encoding="utf-8")
    return str(per_run)


def tensor_stats(tensor: Any) -> Dict[str, Any]:
    x = tensor.detach()
    shape = tuple(int(v) for v in x.shape)
    work = x.float()
    out = {
        "shape": shape,
        "dtype": str(getattr(x, "dtype", "")),
        "device": str(getattr(x, "device", "")),
        "min": float(work.min().item()),
        "max": float(work.max().item()),
        "mean": float(work.mean().item()),
        "std": float(work.std().item()) if work.numel() > 1 else 0.0,
        "abs_mean": float(work.abs().mean().item()),
        "nonzero_frac": float((work != 0).float().mean().item()),
    }
    if x.dim() >= 3 and int(x.shape[-1]) == 3:
        out["channel_mean"] = [float(work[..., c].mean().item()) for c in range(3)]
        out["channel_std"] = [float(work[..., c].std().item()) if work[..., c].numel() > 1 else 0.0 for c in range(3)]
        out["channel_min"] = [float(work[..., c].min().item()) for c in range(3)]
        out["channel_max"] = [float(work[..., c].max().item()) for c in range(3)]
    return out


def append_tensor_stats(diagnostics: list[str], label: str, tensor: Any) -> None:
    try:
        stats = tensor_stats(tensor)
        line = (
            f"{label}: shape={stats['shape']} dtype={stats['dtype']} device={stats['device']} "
            f"min={stats['min']:.6f} max={stats['max']:.6f} mean={stats['mean']:.6f} "
            f"std={stats['std']:.6f} abs_mean={stats['abs_mean']:.6f} nonzero_frac={stats['nonzero_frac']:.6f}"
        )
        if "channel_mean" in stats:
            line += (
                " "
                f"channel_mean={[round(v, 6) for v in stats['channel_mean']]} "
                f"channel_std={[round(v, 6) for v in stats['channel_std']]}"
            )
        diagnostics.append(line)
    except Exception as exc:
        diagnostics.append(f"{label}: failed to summarize tensor: {exc}")

