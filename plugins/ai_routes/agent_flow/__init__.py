# ai_routes/agent_flow/__init__.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from plugins.ai_routes.base import BaseRoute, RouterCore
from plugins.ai_routes import load_routes


PLUGIN_ID = "agent_flow"
PLUGIN_TITLE = "Agent Flow"
PLUGIN_NAME = "Agent Flow"
PLUGIN_DESCRIPTION = "Agent flow customization"
PLUGIN_TYPE = "control"
AGENT_LINKABLE = False

# This schema is for the *global* behavior of the AgentFlow plugin.
# The actual flow graphs (nodes, edges, conditions) are dynamic and
# come from settings / ext JSON (see below).
PLUGIN_CONFIG_SCHEMA = [
    {
        "key": "agent_flow_default_flow",
        "label": "Default flow name",
        "type": "str",
        "default": "",
        "help": "Name of the flowchart to use by default if none is specified.",
    },
    {
        "key": "agent_flow_max_steps",
        "label": "Max steps per run",
        "type": "int",
        "default": "8",
        "help": "Safety limit to avoid infinite loops when running a flow.",
    },
    {
        "key": "agent_flow_mode",
        "label": "Execution mode",
        "type": "str",
        "default": "plan",
        "help": "Strategy for this plugin: 'plan' (build a plan only) or 'simulate'. "
                "In 'plan' mode, AgentFlow just returns a JSON plan; your client "
                "or another agent is responsible for executing each step.",
    },
]


class AgentFlowRoute(BaseRoute):
    """
    Meta-route that orchestrates a named flowchart of aiRouter plugins.

    AgentFlow does NOT directly execute OS actions. It builds a structured
    plan describing which plugin should run in which order, with optional
    conditions and delays between steps.

    The GUI flow editor is responsible for:
      - authoring the flow graphs (nodes/arrows/conditions)
      - storing them into settings / ext as JSON
      - telling AgentFlow which flow name to use for this chat turn.
    """

    route_id = "agent_flow"
    short_description = (
        "Run a named flowchart composed of other aiRouter plugins "
        "(OS-Atlas, VLM code, print, etc.) with conditions and delays."
    )
    backend_types = {"hf", "hf_assist", "gguf", "vllm", "auto"}

    # ------------------------------------------------------------------ #
    # BaseRoute hooks
    # ------------------------------------------------------------------ #
    def can_handle(self, req: Any) -> bool:
        """
        Only handle if we actually have flow definitions and a target flow.

        This keeps AgentFlow from being selected accidentally when there are
        no flows configured.
        """
        flows = self._get_flows(req)
        if not flows:
            return False

        flow_name = self._get_active_flow_name(req, flows)
        return bool(flow_name and flow_name in flows)

    def handle(self, req: Any) -> Any:
        """
        Build (or simulate) the execution plan for the active flow.

        For now, this plugin only *plans* the flow: it does not invoke other
        plugins or OS actions directly. The returned JSON is meant to be
        consumed by your host app / GUI, which can then execute each step by
        calling /v1/chat/completions_ext with the appropriate route_id.
        """
        settings = self.core.settings or {}
        flows = self._get_flows(req)
        if not flows:
            return {
                "route_id": self.route_id,
                "ok": False,
                "error": "no_flows_defined",
                "message": "No AgentFlow flows provided in settings or ext.",
            }

        flow_name = self._get_active_flow_name(req, flows)
        if not flow_name or flow_name not in flows:
            return {
                "route_id": self.route_id,
                "ok": False,
                "error": "flow_not_found",
                "message": f"Flow '{flow_name}' not found.",
                "available_flows": list(flows.keys()),
            }

        flow_def = flows[flow_name]
        mode = str(settings.get("agent_flow_mode", "plan")).lower()

        if mode == "execute":
            return self._execute_flow(req, flows, flow_name)
        

        max_steps = int(settings.get("agent_flow_max_steps", 8))
        user_text = self._extract_user_text(req)

        # Build a static execution plan. In the future you can extend this
        # to actually run each node and attach live results.
        plan = self._build_plan(flow_def, user_text, max_steps)

        return {
            "route_id": self.route_id,
            "ok": True,
            "mode": mode,
            "flow_name": flow_name,
            "plan": plan,
        }

    # ------------------------------------------------------------------ #
    # Flow helpers
    # ------------------------------------------------------------------ #
    def _get_flows(self, req: Any) -> Dict[str, Any]:
        """
        Retrieve flow definitions from either:
          - req.ext["agent_flow_flows"], or
          - settings["agent_flow_flows"]

        Expected shape (example):

            {
              "MyFlow": {
                "start": "node1",
                "nodes": {
                  "node1": {
                    "label": "Locate login button",
                    "plugin_id": "os_atlas",
                    "agent_kind": "vlm",
                    "system_prompt": "...",
                    "delay_ms": 0,
                    "transitions": [
                      {
                        "condition": {
                          "type": "always"
                        },
                        "target": "node2"
                      }
                    ]
                  },
                  "node2": {
                    "label": "Click button",
                    "plugin_id": "pc_automation",
                    "agent_kind": "desktop",
                    "system_prompt": "...",
                    "delay_ms": 250
                  }
                }
              }
            }
        """
        # From ext first (per-request overrides)
        ext = getattr(req, "ext", None)
        if isinstance(ext, dict) and "agent_flow_flows" in ext:
            flows = ext.get("agent_flow_flows") or {}
            if isinstance(flows, dict):
                return flows

        # Then from global settings
        settings = self.core.settings or {}
        flows = settings.get("agent_flow_flows") or {}
        if isinstance(flows, dict):
            return flows

        return {}

    def _get_active_flow_name(self, req: Any, flows: Dict[str, Any]) -> Optional[str]:
        """
        Resolve which flow to run for this request, in priority order:

          1) req.ext["agent_flow_active_flow"]
          2) req.agent_flow_active_flow (if present as a field)
          3) settings["agent_flow_default_flow"]
          4) If only one flow exists, use that name.
        """
        ext = getattr(req, "ext", None)
        if isinstance(ext, dict) and "agent_flow_active_flow" in ext:
            name = ext.get("agent_flow_active_flow")
            if isinstance(name, str) and name.strip():
                return name.strip()

        # Optional direct field
        name = getattr(req, "agent_flow_active_flow", None)
        if isinstance(name, str) and name.strip():
            return name.strip()

        # Settings default
        settings = self.core.settings or {}
        name = settings.get("agent_flow_default_flow")
        if isinstance(name, str) and name.strip():
            return name.strip()

        # Only one defined -> implicit default
        if len(flows) == 1:
            return next(iter(flows.keys()))

        return None

    def _build_plan(
        self,
        flow_def: Dict[str, Any],
        user_text: str,
        max_steps: int,
    ) -> Dict[str, Any]:
        """
        Build a static execution plan for the flow.

        This does *not* execute plugins; it describes what SHOULD happen:

            - which plugin to call
            - which system prompt to use
            - optional agent-kind tag
            - optional delay before/after
            - transitions (conditions) to other nodes

        Your GUI / client can then:
          - Render this as a flow preview,
          - Execute step-by-step, calling /v1/chat/completions_ext with
            route_id=<plugin_id> for each node.
        """
        nodes = flow_def.get("nodes") or {}
        start = flow_def.get("start")
        if not isinstance(nodes, dict) or not start:
            return {
                "steps": [],
                "error": "invalid_flow_def",
            }

        steps: List[Dict[str, Any]] = []
        visited: set[str] = set()
        current_id: Optional[str] = str(start)

        step_count = 0
        while current_id and step_count < max_steps:
            node = nodes.get(current_id)
            if not isinstance(node, dict):
                break

            step = {
                "step_index": step_count,
                "node_id": current_id,
                "label": node.get("label", current_id),
                "plugin_id": node.get("plugin_id", "chat"),
                "agent_kind": node.get("agent_kind", None),   # e.g. "desktop", "vlm", "code", ...
                "system_prompt": node.get("system_prompt", ""),
                "delay_ms": int(node.get("delay_ms", 0) or 0),
                # Conditions / transitions are left as-is for the client/agent
                # to interpret at runtime.
                "transitions": node.get("transitions", []),
            }

            if step_count == 0:
                # Attach the original user text only to the first step
                step["initial_user_input"] = user_text

            steps.append(step)
            visited.add(current_id)
            step_count += 1

            # For planning, pick the "default" next node:
            #   - If there's exactly one transition -> follow its `target`
            #   - Otherwise, stop; the client will decide dynamically at runtime.
            transitions = node.get("transitions", [])
            next_id: Optional[str] = None
            if isinstance(transitions, list) and len(transitions) == 1:
                t0 = transitions[0]
                tid = t0.get("target")
                if isinstance(tid, str) and tid and tid not in visited:
                    next_id = tid

            current_id = next_id

        return {
            "steps": steps,
            "truncated": bool(current_id and step_count >= max_steps),
        }

    # ------------------------------------------------------------------ #
    # Utility: extract last user message text
    # ------------------------------------------------------------------ #
    def _extract_user_text(self, req: Any) -> str:
        msgs = getattr(req, "messages", None)
        if isinstance(msgs, list) and msgs:
            last_user = None
            for m in msgs:
                try:
                    if (m.get("role") or "").lower() == "user":
                        last_user = m
                except AttributeError:
                    continue
            if last_user is None:
                last_user = msgs[-1]
            return str(last_user.get("content", ""))

        # Fallback
        try:
            if hasattr(req, "model_dump"):
                import json

                return json.dumps(req.model_dump(), ensure_ascii=False)
            if hasattr(req, "dict"):
                import json

                return json.dumps(req.dict(), ensure_ascii=False)
        except Exception:
            pass
        return str(req)
    
    def _execute_flow(self, req: Any, flows: dict, flow_name: str) -> Any:
        settings = self.core.settings or {}
        sid = str(settings.get("__sid") or "_default")
        pid = str(settings.get("__pid") or "_default")
        reg = settings.get("__model_loader_registry", None)

        flow_def = flows[flow_name]
        nodes = (flow_def or {}).get("nodes") or {}
        start = (flow_def or {}).get("start")
        if not start or start not in nodes:
            return {"route_id": self.route_id, "ok": False, "error": "flow_missing_start"}

        # Build route registry once
        try:
            routes = load_routes(self.core) or []
            route_by_id = {r.route_id: r for r in routes}
        except Exception as exc:
            return {"route_id": self.route_id, "ok": False, "error": f"load_routes_failed: {exc}"}

        messages = list(getattr(req, "messages", None) or [])
        trace = []

        cur = start
        for step_i in range(int(settings.get("agent_flow_max_steps") or 32)):
            node = nodes.get(cur) or {}
            plugin_id = str(node.get("plugin_id") or "").strip()
            if not plugin_id:
                return {"route_id": self.route_id, "ok": False, "error": f"node_missing_plugin_id:{cur}", "trace": trace}

            route = route_by_id.get(plugin_id)
            if not route:
                return {"route_id": self.route_id, "ok": False, "error": f"unknown_route:{plugin_id}", "trace": trace}

            # --- THIS is where lazy_load takes effect ---
            orig_llm = self.core.chat_llm
            loaded_slot = None
            loader_plugin = None

            if bool(node.get("lazy_load")):
                loader_id = str(node.get("model_loader_id") or "model_loader.gguf")
                ms = (node.get("model_settings") or {}) if isinstance(node.get("model_settings"), dict) else {}

                if not reg:
                    return {"route_id": self.route_id, "ok": False, "error": "model_loader_registry_missing", "trace": trace}

                loader_plugin = reg.get(loader_id)
                if not loader_plugin:
                    return {"route_id": self.route_id, "ok": False, "error": f"model_loader_not_found:{loader_id}", "trace": trace}

                loaded_slot = f"agent:{cur}"
                # load model for this node
                load_res = self.awaitable_call(loader_plugin.load_for, sid, loaded_slot, settings=ms)
                if not (load_res or {}).get("ok"):
                    return {"route_id": self.route_id, "ok": False, "error": f"load_failed:{load_res}", "trace": trace}

                m = loader_plugin.get_model_for(sid, loaded_slot)
                if not m:
                    return {"route_id": self.route_id, "ok": False, "error": "loaded_model_missing", "trace": trace}

                # bind node model for this step
                self.core.chat_llm = m

            # run route
            step_req = self._clone_req_with_messages(req, messages)

            try:
                if getattr(step_req, "ext", None) is None:
                    step_req.ext = {}
                if isinstance(step_req.ext, dict):
                    step_req.ext.setdefault("pid", pid)
                    step_req.ext.setdefault("sid", sid)
                    step_req.ext["agent_flow_node_id"] = cur
                    step_req.ext["agent_flow_node"] = dict(node or {})
                    step_req.ext["agent_flow_flow_name"] = str(flow_name or "")
            except Exception:
                pass

            leases = {}
            unload_policy = str(node.get("unload_policy") or "on_step_end").lower()

            try:
                enabled = None
                try:
                    enabled = getattr(req, "router_enabled_plugins", None)
                except Exception:
                    enabled = None

                if enabled is not None:
                    enabled_set = {str(x).lower() for x in (enabled if isinstance(enabled, (list, tuple, set)) else [enabled])}
                else:
                    enabled_set = None

                if enabled_set is not None and plugin_id.lower() not in enabled_set:
                    raise RuntimeError(f"Route not enabled for this request: {plugin_id}")

                requested = self._node_requested_resources(node, route)

                for rtype in requested:
                    client = self._lease_resource(rtype, node, pid, sid)
                    leases[rtype] = client

                    if isinstance(getattr(step_req, "ext", None), dict):
                        step_req.ext.setdefault("__leases", {})
                        if isinstance(step_req.ext.get("__leases"), dict):
                            step_req.ext["__leases"][rtype] = client

                    if isinstance(getattr(self.core, "resource_clients", None), dict):
                        self.core.resource_clients[(rtype, pid, sid)] = client

                out = route.handle(step_req)

            finally:
                if unload_policy == "on_step_end":
                    for rtype, client in leases.items():
                        try:
                            close = getattr(client, "close", None)
                            if callable(close):
                                close()
                        except Exception:
                            pass
                        try:
                            if isinstance(getattr(self.core, "resource_clients", None), dict):
                                self.core.resource_clients.pop((rtype, pid, sid), None)
                        except Exception:
                            pass

            # out = route.handle(step_req)

            # try to extract assistant text from out
            assistant_text = self._extract_text(out)
            if assistant_text:
                messages = messages + [{"role": "assistant", "content": assistant_text}]

            trace_item = {"node": cur, "plugin_id": plugin_id, "ok": True}
            if isinstance(out, dict):
                if out.get("ok") is False:
                    trace_item["node_error"] = str(out.get("error") or "")
                if isinstance(out.get("raw_text"), str) and out.get("raw_text"):
                    trace_item["raw_text_head"] = str(out.get("raw_text"))[:500]
            trace.append(trace_item)

            # restore llm
            self.core.chat_llm = orig_llm

            # --- THIS is where unload_policy takes effect ---
            if loaded_slot and loader_plugin:
                pol = str(node.get("unload_policy") or "on_step_end").lower()
                if pol == "on_step_end":
                    self.awaitable_call(loader_plugin.unload_for, sid, loaded_slot)

            # next transition (pick first for now)
            nxts = node.get("transitions") or []
            if not nxts:
                break
            t0 = nxts[0]
            if isinstance(t0, dict):
                target = str(t0.get("target") or "").strip()
            else:
                target = str(t0 or "").strip()
            if not target:
                break
            cur = target

        return {"route_id": self.route_id, "ok": True, "flow": flow_name, "trace": trace, "messages": messages}
    
    def _node_requested_resources(self, node: dict, route: Any) -> set[str]:
        req = set()

        # Node can explicitly request resources
        v = node.get("resources")
        if isinstance(v, (list, tuple, set)):
            for x in v:
                if x:
                    req.add(str(x).strip().lower())

        # Back-compat: lazy_load implies route resource types (if declared)
        lazy = bool(node.get("lazy_load")) or bool(node.get("lazy"))
        if lazy:
            rtypes = getattr(route, "resource_types", None)
            if isinstance(rtypes, set):
                req |= {str(x).strip().lower() for x in rtypes if x}

        return req
    
    def _lease_resource(self, rtype: str, node: dict, pid: str, sid: str) -> Any:
        factories = getattr(self.core, "resource_factories", None)
        if not isinstance(factories, dict) or rtype not in factories:
            raise RuntimeError(f"Resource factory not registered: {rtype}")

        merged = dict(self.core.settings or {})

        over = None
        for k in ("resource_settings", f"{rtype}_settings", "os_atlas_settings", "vlm_settings", "model_settings"):
            v = node.get(k)
            if isinstance(v, dict):
                over = v
                break
        if isinstance(over, dict):
            merged.update(over)

        merged["__pid"] = pid
        merged["__sid"] = sid

        backend = str(merged.get("backend_type") or self.core.backend_type or "auto")
        return factories[rtype](merged, backend)

    def awaitable_call(self, fn, *a, **kw):
        v = fn(*a, **kw)
        import inspect
        if inspect.isawaitable(v):
            import asyncio
            return asyncio.get_event_loop().run_until_complete(v)
        return v

    def _clone_req_with_messages(self, req, messages):
        if hasattr(req, "model_copy"):
            return req.model_copy(update={"messages": messages})
        if hasattr(req, "copy"):
            return req.copy(update={"messages": messages})
        try:
            d = req.dict()
            d["messages"] = messages
            return type(req)(**d)
        except Exception:
            req.messages = messages
            return req

    def _extract_text(self, out):
        if isinstance(out, str):
            return out
        if isinstance(out, dict):
            for k in ["text", "final_text", "content", "answer", "raw_text"]:
                if k in out and isinstance(out[k], str):
                    return out[k]
            if isinstance(out.get("patch_candidates"), list):
                try:
                    import json
                    return json.dumps({"patch_candidates": out.get("patch_candidates")}, ensure_ascii=False)
                except Exception:
                    pass
            try:
                return out["choices"][0]["message"]["content"]
            except Exception:
                pass
        return ""

    # def awaitable_call(fn, *a, **kw):
    #     v = fn(*a, **kw)
    #     # support async and sync functions
    #     import inspect
    #     if inspect.isawaitable(v):
    #         import asyncio
    #         return asyncio.get_event_loop().run_until_complete(v)
    #     return v

    # def _clone_req_with_messages(req, messages):
    #     if hasattr(req, "model_copy"):
    #         return req.model_copy(update={"messages": messages})
    #     if hasattr(req, "copy"):
    #         return req.copy(update={"messages": messages})
    #     # fallback: mutate a shallow clone dict if needed
    #     try:
    #         d = req.dict()
    #         d["messages"] = messages
    #         return type(req)(**d)
    #     except Exception:
    #         req.messages = messages
    #         return req

    # def _extract_text(out):
    #     if isinstance(out, str):
    #         return out
    #     if isinstance(out, dict):
    #         for k in ["text", "final_text", "content", "answer"]:
    #             if k in out and isinstance(out[k], str):
    #                 return out[k]
    #         # OpenAI-like
    #         try:
    #             return out["choices"][0]["message"]["content"]
    #         except Exception:
    #             pass
    #     return ""


def build_routes(core: RouterCore) -> List[BaseRoute]:
    return [AgentFlowRoute(core)]
