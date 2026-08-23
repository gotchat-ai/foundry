from __future__ import annotations

import json
import os
import re
import subprocess
from string import Formatter
from typing import Any, Dict, List, Optional

from fastapi import HTTPException


def parse_json_object(settings: Dict[str, Any], key: str) -> Dict[str, Any]:
    text = str(settings.get(key) or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except Exception as exc:
        raise HTTPException(400, f"{key} must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(400, f"{key} must be a JSON object")
    return dict(parsed)


class StrictFormatter(Formatter):
    def get_value(self, key, args, kwargs):
        if isinstance(key, str):
            if key not in kwargs:
                raise KeyError(key)
            return kwargs[key]
        return Formatter.get_value(self, key, args, kwargs)


def split_extra_args(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [part for part in re.split(r"\s+", text) if part]


def _looks_like_tqdm_progress(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return False
    return all("%|" in line or re.match(r"^\d+%\|", line) for line in lines)


def render_template_args(template: Dict[str, Any], context: Dict[str, Any], settings: Dict[str, Any], *, label: str) -> List[str]:
    fmt = StrictFormatter()
    args: List[str] = []
    for raw in template.get("argv") or []:
        token = str(raw or "")
        try:
            rendered = fmt.vformat(token, (), context)
        except KeyError as exc:
            raise HTTPException(400, f"{label} placeholder is missing: {exc.args[0]}") from exc
        if rendered.strip():
            args.append(rendered)
    for row in template.get("optional") or []:
        if not isinstance(row, dict):
            continue
        flag = str(row.get("flag") or "").strip()
        setting_name = str(row.get("setting") or "").strip()
        if not flag or not setting_name:
            continue
        value = context.get(setting_name)
        mode = str(row.get("mode") or "value").strip().lower()
        expected = row.get("equals")
        if expected is not None and str(value) != str(expected):
            continue
        if mode == "bool_flag":
            if bool(value):
                args.append(flag)
            continue
        if value is None or str(value).strip() == "":
            continue
        args.extend([flag, str(value)])
    extra_setting = str(template.get("append_extra_args_setting") or "").strip()
    if extra_setting:
        args.extend(split_extra_args(settings.get(extra_setting)))
    static_append = template.get("append_args")
    if isinstance(static_append, list):
        args.extend([str(x) for x in static_append if str(x).strip()])
    return args


def build_advanced_command(*, settings: Dict[str, Any], prefix: str, runtime_inputs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    template_key = f"{prefix}_runtime_template_json"
    assets_key = f"{prefix}_runtime_assets_json"
    params_key = f"{prefix}_runtime_params_json"
    extra_args_key = f"{prefix}_runtime_extra_args"
    label = f"{prefix} runtime template"
    template = parse_json_object(settings, template_key)
    if not isinstance(template.get("argv"), list) or not template.get("argv"):
        raise HTTPException(400, f"{template_key} requires a non-empty 'argv' array")
    optional_rows = template.get("optional")
    if optional_rows is None:
        template["optional"] = []
    elif not isinstance(optional_rows, list):
        raise HTTPException(400, f"{template_key} field 'optional' must be an array")
    assets = parse_json_object(settings, assets_key)
    params = parse_json_object(settings, params_key)
    # Precedence should be:
    # 1) tested-profile / preset JSON defaults (assets, params)
    # 2) explicit saved model settings / first-class fields
    # 3) runtime inputs supplied by the caller for a specific invocation
    #
    # This prevents stale JSON defaults from overwriting real user-selected paths.
    context = {}
    context.update(assets)
    context.update(params)
    context.update(settings or {})
    context.update(runtime_inputs or {})
    template.setdefault("append_extra_args_setting", extra_args_key)
    cwd_value = str(template.get("cwd") or "").strip()
    cwd = ""
    if cwd_value:
        try:
            cwd = StrictFormatter().vformat(cwd_value, (), context)
        except KeyError as exc:
            raise HTTPException(400, f"{label} cwd placeholder is missing: {exc.args[0]}") from exc
    env_raw = template.get("env")
    env = dict(os.environ)
    if isinstance(env_raw, dict):
        for key, value in env_raw.items():
            try:
                env[str(key)] = StrictFormatter().vformat(str(value), (), context)
            except KeyError as exc:
                raise HTTPException(400, f"{label} env placeholder is missing: {exc.args[0]}") from exc
    cmd = render_template_args(template, context, settings, label=label)
    if not cmd:
        raise HTTPException(400, f"{template_key} rendered an empty command")
    return {"cmd": cmd, "cwd": cwd or None, "env": env}


def run_advanced_command(
    *,
    settings: Dict[str, Any],
    prefix: str,
    runtime_inputs: Optional[Dict[str, Any]] = None,
    timeout_s: Optional[int] = None,
) -> subprocess.CompletedProcess:
    prepared = build_advanced_command(settings=settings, prefix=prefix, runtime_inputs=runtime_inputs)
    timeout = int(timeout_s if timeout_s is not None else (settings.get("timeout_s") or 300))
    try:
        proc = subprocess.run(
            prepared["cmd"],
            capture_output=True,
            text=True,
            timeout=max(1, timeout),
            cwd=prepared.get("cwd"),
            env=prepared.get("env"),
        )
    except FileNotFoundError as exc:
        missing = prepared["cmd"][0] if prepared.get("cmd") else "command"
        raise HTTPException(400, f"{prefix} command not found: {missing}") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(500, f"{prefix} command timed out after {timeout}s") from exc
    if int(proc.returncode or 0) != 0:
        stderr = str(proc.stderr or "").strip()
        stdout = str(proc.stdout or "").strip()
        if stdout and (stdout.startswith("{") or stdout.startswith("[")):
            message = stdout
        elif stderr and not _looks_like_tqdm_progress(stderr):
            message = stderr
        else:
            cmd0 = ""
            try:
                cmd0 = str((prepared.get("cmd") or [""])[0] or "").strip()
            except Exception:
                cmd0 = ""
            detail_parts = [stdout or stderr or f"{prefix} command failed"]
            detail_parts.append(f"returncode={int(proc.returncode or 0)}")
            if cmd0:
                detail_parts.append(f"cmd={cmd0}")
            if prepared.get("cwd"):
                detail_parts.append(f"cwd={prepared.get('cwd')}")
            message = " | ".join([part for part in detail_parts if str(part or "").strip()])
        raise HTTPException(500, message)
    return proc
