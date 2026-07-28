from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugins.gui_helpers.agent_flow import routes as agent_flow_routes
from plugins.gui_helpers.agent_flow.routes import install as install_agent_flow
from plugins.gui_helpers.workflow_exchange.package import build_skill_spec, default_workflow_package
from plugins.gui_helpers.workflow_exchange.routes import install
from plugins.gui_helpers.workflow_exchange.settings_schema import DEFAULT_SETTINGS


HDRS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "X-Gui-Enabled-Plugins": "workflow_exchange",
}


def _make_app(workdir: Path) -> FastAPI:
    app = FastAPI()
    data_dir = workdir / "llmloader2" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    settings_box = {
        **DEFAULT_SETTINGS,
        "router_plugin_settings": {
            "workflow_exchange": {
                **DEFAULT_SETTINGS,
                "workflow_exchange_mode": "hybrid",
                "workflow_exchange_public_publish_enabled": True,
                "workflow_exchange_public_min_safety_score": 0.1,
                "workflow_exchange_public_min_quality_score": 0.1,
            }
        },
    }

    def _settings():
        return settings_box

    app.state.workdir = str(workdir)
    app.state.data_dir = str(data_dir)
    app.state.settings = _settings
    app.state.collab_hub = SimpleNamespace(publish=lambda *args, **kwargs: None)
    app.state.collab_db = SimpleNamespace(add_message=lambda *args, **kwargs: None)
    app.state.ai_jobs = SimpleNamespace(upsert=lambda *args, **kwargs: None, remove=lambda *args, **kwargs: None)
    app.state.ai_jobs_cancelled = {}
    agent_flow_routes._require_user = lambda app0, request: SimpleNamespace(username="test")
    agent_flow_routes._require_session_access = lambda app0, user, pid, sid: None
    install_agent_flow(app)
    install(app)
    return app


def _bundle_dir(base: Path, name: str) -> tuple[Path, Path]:
    bundle_dir = base / name
    bundle_dir.mkdir(parents=True, exist_ok=True)
    workflow_file = bundle_dir / f"{name}.json"
    return bundle_dir, workflow_file


def _workflow_doc(flow_name: str, skill_id: str, *, output_skills: list[str] | None = None) -> dict:
    output_skill_list = list(output_skills or ["result.text"])
    return {
        "flows": {
            flow_name: {
                "name": flow_name,
                "description": f"Smoke workflow for {flow_name}.",
                "start": "execute",
                "nodes": {
                    "execute": {
                        "label": "Execute",
                        "plugin_id": "agent_workflow_member",
                        "agent_kind": "tooling",
                        "system_prompt": "Run the imported skill.",
                        "x": 120,
                        "y": 120,
                        "delay_ms": 0,
                        "return_only_text": True,
                        "transitions": [{"condition": {"type": "always"}, "target": "output"}],
                        "plugin_settings": {
                            "node_type": "tool_node",
                            "member_role": "tooling",
                            "handoff_format": "plain",
                            "output_protocol": "tagged",
                            "member_token_stream": True,
                            "action_skills": [skill_id],
                            "tool_config": {"tool": skill_id, "params": {"request_text": "demo"}},
                        },
                    },
                    "output": {
                        "label": "Output",
                        "plugin_id": "agent_workflow_member",
                        "agent_kind": "release",
                        "system_prompt": "Emit the tool result text.",
                        "x": 420,
                        "y": 120,
                        "delay_ms": 0,
                        "return_only_text": True,
                        "transitions": [],
                        "plugin_settings": {
                            "node_type": "output_node",
                            "member_role": "release",
                            "handoff_format": "plain",
                            "output_protocol": "tagged",
                            "member_token_stream": True,
                            "action_skills": output_skill_list,
                        },
                    },
                },
            }
        }
    }


def _package(flow_name: str, skill_id: str, *, quarantine: bool = False, output_skills: list[str] | None = None) -> dict:
    pkg = default_workflow_package()
    pkg["visibility"] = "public"
    pkg["bundle_mode"] = "spec_only"
    pkg["workflow_id"] = flow_name
    pkg["flow_name"] = flow_name
    pkg["workflow"]["summary"] = f"Imported workflow {flow_name}"
    pkg["workflow"]["tags"] = ["smoke", "workflow_exchange"]
    pkg["workflow"]["workflow_json"] = _workflow_doc(flow_name, skill_id, output_skills=output_skills)
    pkg["skills"]["skill_specs"] = [
        build_skill_spec(
            skill_id,
            intent=f"Implement {skill_id}",
            category="custom",
            required_capabilities=["filesystem"],
        )
    ]
    if quarantine:
        pkg["sanitization"]["review_findings"] = ["manual_policy_review"]
    return pkg


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="workflow_exchange_local_"))
    client = TestClient(_make_app(tmp))

    settings_res = client.post(
        "/v1/workflow_exchange/settings",
        headers=HDRS,
        json={
            "settings": {
                "workflow_exchange_public_scheduled_sync_enabled": True,
                "workflow_exchange_public_sync_min_interval_s": 321,
                "workflow_exchange_private_scheduled_sync_enabled": True,
                "workflow_exchange_private_sync_min_interval_s": 42,
                "workflow_exchange_public_relays": ["https://account.gotchat.ai/api"],
                "workflow_exchange_private_relays": ["http://host.docker.internal:5001"],
                "workflow_exchange_exclude_share_tags": ["private", "secret"],
            }
        },
    )
    assert settings_res.status_code == 200, settings_res.text
    settings_data = settings_res.json()
    assert settings_data.get("ok") is True, settings_data

    bundle_dir_1, workflow_file_1 = _bundle_dir(tmp / "bundles", "regen_bundle")
    workflow_file_1.write_text(json.dumps(_workflow_doc("regen_flow", "custom.demo_regen"), ensure_ascii=True, indent=2), encoding="utf-8")
    import_res = client.post(
        "/v1/workflow_exchange/import",
        headers=HDRS,
        json={
            "pid": "project2",
            "sid": "default",
            "bundle_dir": str(bundle_dir_1),
            "workflow_file": str(workflow_file_1),
            "flow_name": "regen_flow",
            "visibility": "public",
            "package": _package("regen_flow", "custom.demo_regen"),
        },
    )
    assert import_res.status_code == 200, import_res.text
    imported = import_res.json()
    record = imported.get("import_record") or {}
    import_id = str(record.get("id") or "").strip()
    assert import_id, imported
    assert str(record.get("import_status") or "") == "needs_local_skill_generation", record

    regen_res = client.post(f"/v1/workflow_exchange/imports/{import_id}/regenerate_skills", headers=HDRS, json={})
    assert regen_res.status_code == 200, regen_res.text
    regen_data = regen_res.json()
    assert regen_data.get("ok") is True, regen_data
    regen_item = regen_data.get("item") or {}
    assert (regen_data.get("result") or {}).get("written_files"), regen_data
    assert (regen_item.get("actions") or {}).get("open_skill_regen_flow"), regen_item
    run_res = client.post(
        "/v1/projects/project2/sessions/default/agent_flow/run",
        headers={"X-Gui-Enabled-Plugins": "agent_flow"},
        json={
            "text": "Run the regenerated smoke workflow.",
            "ext": {
                "agent_flow_flows": (_package("regen_flow", "custom.demo_regen").get("workflow") or {}).get("workflow_json", {}).get("flows", {}),
                "agent_flow_active_flow": "regen_flow",
                "agent_flow_default_flow": "regen_flow",
                "bundle_dir": str(regen_item.get("bundle_dir") or ""),
                "workflow_file": str(regen_item.get("workflow_file") or ""),
                "flow_name": "regen_flow",
            },
        },
    )
    assert run_res.status_code == 200, run_res.text
    run_data = run_res.json()
    run_id = str(run_data.get("run_id") or "").strip()
    assert run_id, run_data
    final_state = {}
    deadline = time.time() + 15.0
    while time.time() < deadline:
        status_res = client.get(f"/v1/projects/project2/sessions/default/agent_flow/status?run_id={run_id}", headers={"X-Gui-Enabled-Plugins": "agent_flow"})
        assert status_res.status_code == 200, status_res.text
        final_state = status_res.json().get("state") or {}
        if not final_state.get("running"):
            break
        time.sleep(0.2)
    assert final_state and not final_state.get("running"), final_state
    assert str(final_state.get("status") or "").strip().lower() == "completed", final_state

    bundle_dir_2, workflow_file_2 = _bundle_dir(tmp / "bundles", "quarantine_bundle")
    workflow_file_2.write_text(json.dumps(_workflow_doc("quarantine_flow", "custom.demo_review"), ensure_ascii=True, indent=2), encoding="utf-8")
    quarantine_import_res = client.post(
        "/v1/workflow_exchange/import",
        headers=HDRS,
        json={
            "pid": "project2",
            "sid": "default",
            "bundle_dir": str(bundle_dir_2),
            "workflow_file": str(workflow_file_2),
            "flow_name": "quarantine_flow",
            "visibility": "public",
            "package": _package("quarantine_flow", "custom.demo_review", quarantine=True),
        },
    )
    assert quarantine_import_res.status_code == 200, quarantine_import_res.text
    quarantine_import = quarantine_import_res.json()
    quarantine_record = quarantine_import.get("import_record") or {}
    quarantine_id = str(quarantine_record.get("id") or "").strip()
    assert quarantine_id, quarantine_import
    assert str(quarantine_import.get("decision") or "") == "quarantine_review", quarantine_import

    review_res = client.post(f"/v1/workflow_exchange/imports/{quarantine_id}/quarantine_review", headers=HDRS, json={})
    assert review_res.status_code == 200, review_res.text
    review_data = review_res.json()
    assert review_data.get("ok") is True, review_data
    review_item = review_data.get("item") or {}
    review_summary = (review_data.get("result") or {}).get("summary") or {}
    assert str(review_summary.get("recommendation") or "") == "manual_review_required", review_data
    assert (review_item.get("actions") or {}).get("open_quarantine_review_flow"), review_item

    baseline_flow_doc = _workflow_doc("compare_flow", "custom.compare_baseline", output_skills=["result.text"])
    baseline_save = client.post(
        "/v1/projects/project2/sessions/default/agent_flow/flows",
        headers={"X-Gui-Enabled-Plugins": "agent_flow"},
        json={"flows": baseline_flow_doc.get("flows") or {}},
    )
    assert baseline_save.status_code == 200, baseline_save.text
    compare_bundle_dir, compare_workflow_file = _bundle_dir(tmp / "bundles", "compare_bundle")
    compare_workflow_file.write_text(
        json.dumps(_workflow_doc("compare_flow", "custom.compare_candidate", output_skills=["result.file"]), ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    compare_import_res = client.post(
        "/v1/workflow_exchange/import",
        headers=HDRS,
        json={
            "pid": "project2",
            "sid": "default",
            "bundle_dir": str(compare_bundle_dir),
            "workflow_file": str(compare_workflow_file),
            "flow_name": "compare_flow",
            "visibility": "public",
            "package": _package("compare_flow", "custom.compare_candidate", output_skills=["result.file"]),
        },
    )
    assert compare_import_res.status_code == 200, compare_import_res.text
    compare_import = compare_import_res.json()
    compare_record = compare_import.get("import_record") or {}
    compare_id = str(compare_record.get("id") or "").strip()
    assert compare_id, compare_import
    compare_res = client.post(
        f"/v1/workflow_exchange/imports/{compare_id}/compare",
        headers=HDRS,
        json={
            "request_text": "Export a downloadable report file for this workflow.",
            "baseline_flow_name": "compare_flow",
            "baseline_workflow_json": baseline_flow_doc,
        },
    )
    assert compare_res.status_code == 200, compare_res.text
    compare_data = compare_res.json()
    assert compare_data.get("ok") is True, compare_data
    assert compare_data.get("compared") is True, compare_data
    comparison = compare_data.get("comparison") or {}
    assert str(comparison.get("status") or "") == "candidate_better", compare_data
    assert comparison.get("recommendation") == "update_recommended", compare_data
    feedback_res = client.post(
        f"/v1/workflow_exchange/imports/{compare_id}/feedback",
        headers=HDRS,
        json={"question": "Did this answer your question?", "satisfied": True, "target": "candidate"},
    )
    assert feedback_res.status_code == 200, feedback_res.text
    feedback_data = feedback_res.json()
    assert feedback_data.get("ok") is True, feedback_data
    feedback_item = feedback_data.get("item") or {}
    assert (feedback_item.get("last_user_feedback") or {}).get("satisfied") is True, feedback_item
    assert str(feedback_item.get("user_feedback_status") or "") == "satisfied", feedback_item

    settings_get = client.get("/v1/workflow_exchange/settings", headers=HDRS)
    assert settings_get.status_code == 200, settings_get.text
    stored = settings_get.json().get("settings") or {}
    assert stored.get("workflow_exchange_public_sync_min_interval_s") == 321, stored
    assert stored.get("workflow_exchange_private_sync_min_interval_s") == 42, stored
    assert stored.get("workflow_exchange_public_scheduled_sync_enabled") is True, stored

    print(
        json.dumps(
            {
                "ok": True,
                "regen_import_id": import_id,
                "regen_written_files": (regen_data.get("result") or {}).get("written_files") or [],
                "regen_run_id": run_id,
                "regen_run_status": final_state.get("status"),
                "quarantine_import_id": quarantine_id,
                "quarantine_report_path": (review_data.get("result") or {}).get("report_path") or "",
                "compare_import_id": compare_id,
                "compare_status": comparison.get("status"),
                "compare_feedback_status": feedback_item.get("user_feedback_status"),
                "saved_public_sync_interval": stored.get("workflow_exchange_public_sync_min_interval_s"),
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
