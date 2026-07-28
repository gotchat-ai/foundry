from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
import threading
from dataclasses import dataclass
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List


HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[5]
SKILLS_ROOT = PROJECT_ROOT / "llmloader2" / "plugins" / "gui_helpers" / "agent_flow" / "skills"
WORKFLOW_ROOT = HERE / "workflows"
FIXTURE_ROOT = HERE / "fixtures"
ARTIFACT_ROOT = HERE / "artifacts"

for candidate in (PROJECT_ROOT, PROJECT_ROOT / "llmloader2"):
    text = str(candidate)
    if text not in sys.path:
        sys.path.insert(0, text)


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot_load_module:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tool_modules() -> Dict[str, Any]:
    tools: Dict[str, Any] = {}
    counter = 0
    for path in sorted(SKILLS_ROOT.rglob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            module = _load_module(path, f"af_skill_{counter}")
        except Exception:
            counter += 1
            continue
        counter += 1
        spec = getattr(module, "TOOL_SPEC", None)
        tool_id = str((spec or {}).get("id") or "").strip() if isinstance(spec, dict) else ""
        run_fn = getattr(module, "run", None)
        if tool_id and callable(run_fn):
            tools[tool_id] = module
    return tools


def _replace_tokens(value: Any, mapping: Dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {k: _replace_tokens(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace_tokens(v, mapping) for v in value]
    if isinstance(value, str):
        out = value
        for key, repl in mapping.items():
            out = out.replace(key, repl)
        return out
    return value


def _state_get(state: Dict[str, Any], path: str) -> Any:
    current: Any = state
    for part in [p for p in str(path or "").split(".") if p]:
        if isinstance(current, dict):
            current = current.get(part)
            continue
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except Exception:
                return None
            continue
        return None
    return current


def _assert_expectations(state: Dict[str, Any], expectations: List[Dict[str, Any]]) -> List[str]:
    failures: List[str] = []
    for row in expectations:
        path = str(row.get("path") or "").strip()
        actual = _state_get(state, path)
        if "equals" in row and actual != row.get("equals"):
            failures.append(f"{path}: expected {row.get('equals')!r}, got {actual!r}")
        if "contains" in row:
            wanted = row.get("contains")
            if isinstance(actual, list):
                if wanted not in actual:
                    failures.append(f"{path}: expected list to contain {wanted!r}, got {actual!r}")
            else:
                if str(wanted) not in str(actual):
                    failures.append(f"{path}: expected text to contain {wanted!r}, got {actual!r}")
        if "min_length" in row:
            if not isinstance(actual, (list, str)) or len(actual) < int(row.get("min_length") or 0):
                failures.append(f"{path}: expected min length {row.get('min_length')}, got {actual!r}")
        if bool(row.get("exists_file")):
            if not actual or not Path(str(actual)).is_file():
                failures.append(f"{path}: expected existing file, got {actual!r}")
    return failures


def _next_target(node: Dict[str, Any]) -> str:
    transitions = node.get("transitions") if isinstance(node.get("transitions"), list) else []
    for transition in transitions:
        if isinstance(transition, dict):
            target = str(transition.get("target") or "").strip()
            if target:
                return target
    return ""


def _build_params(tool_cfg: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    params = dict(tool_cfg.get("params") or {}) if isinstance(tool_cfg.get("params"), dict) else {}
    for key in tool_cfg.get("params_from_input") or []:
        pkey = str(key or "").strip()
        if pkey and pkey not in params and pkey in state:
            params[pkey] = state.get(pkey)
    bindings = tool_cfg.get("input_bindings") if isinstance(tool_cfg.get("input_bindings"), dict) else {}
    for param_name, state_path in bindings.items():
        params[str(param_name)] = _state_get(state, str(state_path))
    return params


def _execute_workflow(workflow: Dict[str, Any], tool_modules: Dict[str, Any], base_state: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    nodes = workflow.get("nodes") if isinstance(workflow.get("nodes"), dict) else {}
    current = str(workflow.get("start") or "").strip()
    state = dict(base_state)
    visited = 0
    trace: List[Dict[str, Any]] = []
    while current and current in nodes and visited < 32:
        visited += 1
        node = nodes.get(current) if isinstance(nodes.get(current), dict) else {}
        ps = node.get("plugin_settings") if isinstance(node.get("plugin_settings"), dict) else {}
        tool_cfg = ps.get("tool_config") if isinstance(ps.get("tool_config"), dict) else {}
        tool_name = str(tool_cfg.get("tool") or "").strip()
        if not tool_name:
            raise RuntimeError(f"missing_tool:{current}")
        module = tool_modules.get(tool_name)
        if module is None:
            raise RuntimeError(f"tool_not_loaded:{tool_name}")
        params = _build_params(tool_cfg, state)
        local_ctx = {
            **ctx,
            "user_text": str(state.get("request_text") or ""),
            "original_request": str(state.get("request_text") or ""),
        }
        result = module.run(local_ctx, params)
        if not isinstance(result, dict):
            result = {"ok": False, "data": {"result": result}, "warnings": ["invalid_result_shape"]}
        state[current] = result
        state["last_result"] = result
        state["last_data"] = result.get("data") if isinstance(result.get("data"), dict) else {}
        trace.append({"node_id": current, "tool": tool_name, "ok": bool(result.get("ok")), "warnings": list(result.get("warnings") or [])})
        current = _next_target(node)
    state["__trace__"] = trace
    return state


@dataclass
class LocalWebServer:
    root: Path
    server: ThreadingHTTPServer | None = None
    thread: threading.Thread | None = None
    url: str = ""

    def start(self) -> None:
        root = self.root

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, directory=str(root), **kwargs)

            def log_message(self, format: str, *args: Any) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        host, port = self.server.server_address
        self.url = f"http://{host}:{port}/index.html"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=2)


def _create_sqlite_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(str(path))
    try:
        con.execute("create table synthetic_orders (id integer primary key, region text, total_amount real)")
        con.executemany(
            "insert into synthetic_orders (id, region, total_amount) values (?, ?, ?)",
            [
                (1, "north", 125.5),
                (2, "south", 98.0),
                (3, "west", 201.25),
            ],
        )
        con.commit()
    finally:
        con.close()


def main() -> int:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    sqlite_path = ARTIFACT_ROOT / "synthetic_orders.sqlite"
    draft_path = ARTIFACT_ROOT / "synthetic_validation_draft.eml"
    quarantine_dir = ARTIFACT_ROOT / "quarantine_review_bundle"
    _create_sqlite_fixture(sqlite_path)
    web = LocalWebServer(FIXTURE_ROOT / "web")
    web.start()
    try:
        mapping = {
            "__WORKSPACE_DIR__": str((FIXTURE_ROOT / "workspace").resolve()),
            "__FIXTURE_DOC__": str((FIXTURE_ROOT / "sample_document.txt").resolve()),
            "__FIXTURE_MAILBOX__": str((FIXTURE_ROOT / "sample_mailbox.json").resolve()),
            "__FIXTURE_SQLITE__": str(sqlite_path.resolve()),
            "__DRAFT_OUTPUT__": str(draft_path.resolve()),
            "__QUARANTINE_OUTPUT_DIR__": str(quarantine_dir.resolve()),
            "__LOCAL_WEB_URL__": web.url,
        }
        tool_modules = _tool_modules()
        fake_app = SimpleNamespace(
            state=SimpleNamespace(
                workdir=str(PROJECT_ROOT),
                data_dir=str(ARTIFACT_ROOT),
                settings={},
            )
        )
        ctx = {"app": fake_app}
        summary: Dict[str, Any] = {"ok": True, "workflows": []}
        for workflow_path in sorted(WORKFLOW_ROOT.glob("*.json")):
            workflow_doc = json.loads(workflow_path.read_text(encoding="utf-8"))
            workflow_doc = _replace_tokens(workflow_doc, mapping)
            test = workflow_doc.get("test") if isinstance(workflow_doc.get("test"), dict) else {}
            request_text = str(test.get("request_text") or "").strip()
            initial_state = dict(test.get("initial_state") or {}) if isinstance(test.get("initial_state"), dict) else {}
            if web.url:
                initial_state.setdefault("local_url", web.url)
                initial_state.setdefault("local_url_list", [web.url])
            initial_state.setdefault("request_text", request_text)
            initial_state.setdefault("user_request", request_text)
            initial_state.setdefault("request", request_text)
            initial_state.setdefault("text", request_text)
            state = _execute_workflow(workflow_doc, tool_modules, initial_state, ctx)
            failures = _assert_expectations(state, list(test.get("expect") or []))
            row = {
                "workflow": str(workflow_doc.get("name") or workflow_path.stem),
                "passed": not failures,
                "failures": failures,
                "trace": state.get("__trace") or state.get("__trace__") or [],
            }
            summary["workflows"].append(row)
            if failures:
                summary["ok"] = False
        print(json.dumps(summary, ensure_ascii=True, indent=2))
        return 0 if summary.get("ok") else 1
    finally:
        web.stop()


if __name__ == "__main__":
    raise SystemExit(main())
