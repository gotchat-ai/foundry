from __future__ import annotations

import json
import socket
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
import uvicorn

from plugins.gui_helpers.workflow_exchange.package import build_skill_spec, default_workflow_package
from plugins.gui_helpers.workflow_exchange.routes import install
from plugins.gui_helpers.workflow_exchange.settings_schema import DEFAULT_SETTINGS


HDRS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "X-Gui-Enabled-Plugins": "workflow_exchange",
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _make_app(workdir: Path) -> FastAPI:
    app = FastAPI()

    def _settings():
        return {
            **DEFAULT_SETTINGS,
            "router_plugin_settings": {
                "workflow_exchange": {
                    **DEFAULT_SETTINGS,
                    "workflow_exchange_mode": "public",
                    "workflow_exchange_public_publish_enabled": True,
                    "workflow_exchange_public_min_safety_score": 0.5,
                    "workflow_exchange_public_min_quality_score": 0.5,
                }
            },
        }

    app.state.workdir = str(workdir)
    app.state.settings = _settings
    install(app)
    return app


def _start_server(app: FastAPI, port: int):
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10.0
    base = f"http://127.0.0.1:{port}"
    while time.time() < deadline:
      try:
            _json_get(f"{base}/v1/workflow_exchange/settings")
            return server, thread, base
      except Exception:
            time.sleep(0.1)
    raise RuntimeError(f"server did not start on {base}")


def _json_get(url: str):
    req = urllib.request.Request(url, headers=HDRS, method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _json_post(url: str, payload: dict):
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=HDRS, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _package() -> dict:
    pkg = default_workflow_package()
    pkg["visibility"] = "public"
    pkg["bundle_mode"] = "spec_only"
    pkg["workflow_id"] = "relay-demo"
    pkg["flow_name"] = "relay_demo_flow"
    pkg["workflow"]["summary"] = "Public relay smoke test workflow."
    pkg["workflow"]["tags"] = ["relay", "public", "smoke"]
    pkg["workflow"]["workflow_json"] = {
        "start": "n1",
        "nodes": {
            "n1": {
                "plugin_id": "noop",
                "plugin_settings": {},
            }
        },
    }
    pkg["skills"]["skill_specs"] = [
        build_skill_spec(
            "relay_demo_skill",
            intent="Relay-safe spec-only demo skill.",
            category="utility",
            required_capabilities=["http"],
        )
    ]
    return pkg


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="workflow_exchange_relay_"))
    a_dir = tmp / "a"
    b_dir = tmp / "b"
    a_dir.mkdir(parents=True, exist_ok=True)
    b_dir.mkdir(parents=True, exist_ok=True)

    port_a = _free_port()
    port_b = _free_port()
    server_a = thread_a = server_b = thread_b = None
    try:
        server_a, thread_a, base_a = _start_server(_make_app(a_dir), port_a)
        server_b, thread_b, base_b = _start_server(_make_app(b_dir), port_b)

        publish = _json_post(f"{base_a}/v1/workflow_exchange/publish", {"visibility": "public", "package": _package()})
        assert publish.get("ok") is True, publish
        assert (publish.get("public_item") or {}).get("source") == "public", publish

        push = _json_post(
            f"{base_a}/v1/workflow_exchange/mirror/push",
            {"mirror_id": "relay-b", "visibility": "public", "relay_url": base_b},
        )
        assert push.get("ok") is True, push

        pub_b = _json_get(f"{base_b}/v1/workflow_exchange/discover?{urllib.parse.urlencode({'scope': 'public'})}")
        items_b = pub_b.get("items") or []
        assert any(str(row.get("flow_name") or "") == "relay_demo_flow" for row in items_b), pub_b
        assert any(str(((row.get("package") or {}).get("source") or {}).get("publisher_id") or "").startswith("anon-") for row in items_b), pub_b

        pull = _json_post(
            f"{base_a}/v1/workflow_exchange/mirror/pull",
            {"mirror_id": "relay-b", "visibility": "public", "relay_url": base_b},
        )
        assert pull.get("ok") is True, pull
        discover_a = _json_get(f"{base_a}/v1/workflow_exchange/discover")
        items_a = discover_a.get("items") or []
        assert any(str(row.get("source") or "") == "mirror" and str(row.get("flow_name") or "") == "relay_demo_flow" for row in items_a), discover_a

        print(json.dumps({
            "ok": True,
            "publish": publish.get("public_item"),
            "relay_push_remote": push.get("remote"),
            "relay_b_public_count": len(items_b),
            "relay_a_discover_count": len(items_a),
        }, ensure_ascii=True))
        return 0
    finally:
        if server_a is not None:
            server_a.should_exit = True
        if server_b is not None:
            server_b.should_exit = True
        if thread_a is not None:
            thread_a.join(timeout=3)
        if thread_b is not None:
            thread_b.join(timeout=3)


if __name__ == "__main__":
    raise SystemExit(main())
