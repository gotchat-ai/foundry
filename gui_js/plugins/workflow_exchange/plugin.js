const meta = {
  plugin_id: "workflow_exchange",
  name: "Agent Workflow Exchange",
  kind: "panel",
  description: "Publish, discover, import, evaluate, and install agent workflow exchange bundles.",
  has_notebook_tab: true,
};

const STYLE_ID = "workflow-exchange-style";
const SESSION_CHANGE_EVENT = "chat_js:session-changed";
const AGENT_FLOW_OPEN_EVENT = "agent-flow:open-temp-library-record";
const AGENT_FLOW_PENDING_KEY = "__agentFlowOpenTempLibraryRequest";
let sessionChangeHandler = null;

function ensureStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
.wx-panel { display:flex; flex-direction:column; gap:12px; }
.wx-toolbar { display:flex; gap:8px; align-items:center; justify-content:space-between; flex-wrap:wrap; }
.wx-toolbar .wx-meta { font-size:12px; color:var(--ui-muted); }
.wx-search, .wx-select {
  width: 100%;
  border-radius: 12px;
  border: 1px solid var(--border);
  padding: 8px 12px;
  font-size: 12px;
  background: var(--ui-control-bg);
  color: var(--ui-ink);
}
.wx-textarea {
  width: 100%;
  min-height: 86px;
  resize: vertical;
  border-radius: 12px;
  border: 1px solid var(--border);
  padding: 8px 12px;
  font-size: 12px;
  background: var(--ui-control-bg);
  color: var(--ui-ink);
}
.wx-toolbar-group { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
.wx-overview { display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap:8px; }
.wx-tabs {
  display:flex;
  gap:0;
  flex-wrap:wrap;
  border-bottom:1px solid var(--border);
  padding-top:2px;
}
.wx-tab {
  border:1px solid transparent;
  border-bottom:0;
  background: transparent;
  color: var(--ui-ink);
  border-radius:12px 12px 0 0;
  padding:9px 14px 10px;
  font-size:12px;
  cursor:pointer;
  margin-bottom:-1px;
}
.wx-tab.active {
  background: rgba(var(--panel-rgb), 0.94);
  border-color: var(--border);
  border-bottom-color: rgba(var(--panel-rgb), 0.94);
  font-weight:700;
}
.wx-sections { display:grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap:12px; align-items:start; }
.wx-section { display:flex; flex-direction:column; gap:10px; min-width:0; }
.wx-section-head { display:flex; justify-content:space-between; gap:8px; align-items:center; flex-wrap:wrap; }
.wx-section-title { font-size:13px; font-weight:700; color:var(--ui-ink); }
.wx-section-sub { font-size:11px; color:var(--ui-muted); }
.wx-list { display:flex; flex-direction:column; gap:10px; min-width:0; }
.wx-card {
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 12px;
  background: rgba(var(--panel-rgb), 0.72);
  display:flex;
  flex-direction:column;
  gap:10px;
  min-width:0;
}
.wx-card-head { display:flex; justify-content:space-between; gap:10px; align-items:flex-start; flex-wrap:wrap; }
.wx-title { font-size: 14px; font-weight: 700; color: var(--ui-ink); overflow-wrap:anywhere; }
.wx-sub { font-size: 11px; color: var(--ui-muted); overflow-wrap:anywhere; }
.wx-badges { display:flex; gap:6px; flex-wrap:wrap; }
.wx-badge {
  display:inline-flex; align-items:center; gap:6px;
  padding:3px 8px; border-radius:999px; font-size:10px; line-height:1.2;
  border:1px solid var(--border); background: var(--ui-control-bg);
}
.wx-badge.status-ready_to_flow { background: rgba(16, 185, 129, 0.12); color: #0d7a57; border-color: rgba(16,185,129,0.35); }
.wx-badge.status-needs_local_skill_generation { background: rgba(245, 158, 11, 0.12); color: #9a6200; border-color: rgba(245,158,11,0.35); }
.wx-badge.status-evaluation_running,
.wx-badge.status-evaluation_requested { background: rgba(59, 130, 246, 0.12); color: #1857a5; border-color: rgba(59,130,246,0.35); }
.wx-badge.status-quarantine_review,
.wx-badge.status-imported { background: rgba(107, 114, 128, 0.12); color: #46505f; border-color: rgba(107,114,128,0.35); }
.wx-badge.status-evaluation_failed,
.wx-badge.status-blocked { background: rgba(220, 38, 38, 0.12); color: #9f1d1d; border-color: rgba(220,38,38,0.35); }
.wx-badge.status-candidate_better { background: rgba(16, 185, 129, 0.12); color: #0d7a57; border-color: rgba(16,185,129,0.35); }
.wx-badge.status-candidate_worse,
.wx-badge.status-baseline_missing { background: rgba(245, 158, 11, 0.12); color: #9a6200; border-color: rgba(245,158,11,0.35); }
.wx-badge.status-candidate_equal { background: rgba(107, 114, 128, 0.12); color: #46505f; border-color: rgba(107,114,128,0.35); }
.wx-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap:8px; }
.wx-kv { border:1px solid var(--border); border-radius:10px; padding:8px; background: rgba(var(--panel-rgb), 0.45); }
.wx-kv .k { font-size:10px; text-transform:uppercase; letter-spacing:0.8px; color:var(--ui-muted); }
.wx-kv .v { margin-top:4px; font-size:12px; color:var(--ui-ink); overflow-wrap:anywhere; }
.wx-actions { display:flex; gap:8px; flex-wrap:wrap; }
.wx-actions button {
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--ui-control-bg);
  color: var(--ui-ink);
  padding: 7px 10px;
  font-size: 12px;
  cursor: pointer;
}
.wx-actions button.primary { background: rgba(var(--accent-rgb), 0.14); border-color: rgba(var(--accent-rgb), 0.4); }
.wx-actions button.warn { background: rgba(220, 38, 38, 0.08); border-color: rgba(220, 38, 38, 0.25); }
.wx-actions button:disabled { opacity: 0.55; cursor: not-allowed; }
.wx-empty, .wx-error, .wx-status { font-size:12px; color:var(--ui-muted); }
.wx-error { color: #9f1d1d; }
.wx-feedback-box { border:1px solid var(--border); border-radius:12px; padding:10px; background: rgba(var(--panel-rgb), 0.45); display:flex; flex-direction:column; gap:8px; }
.wx-feedback-q { font-size:12px; color:var(--ui-ink); font-weight:600; }
.wx-feedback-meta { font-size:11px; color:var(--ui-muted); }
.wx-picker { position:relative; display:flex; flex-direction:column; gap:8px; min-width:0; }
.wx-picker-meta { display:flex; justify-content:space-between; gap:8px; align-items:center; flex-wrap:wrap; }
.wx-picker-chip { font-size:11px; color:var(--ui-muted); }
.wx-picker-control {
  width:100%;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--ui-control-bg);
  color: var(--ui-ink);
  display:flex;
  align-items:center;
  gap:8px;
  padding: 0 12px;
}
.wx-picker-chevron {
  font-size: 11px;
  color: var(--ui-muted);
  flex: 0 0 auto;
}
.wx-picker-input {
  flex: 1 1 auto;
  min-width: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: inherit;
  padding: 8px 0;
  font-size: 12px;
}
.wx-picker-input::placeholder { color: var(--ui-muted); }
.wx-popover {
  position:absolute;
  top:calc(100% + 6px);
  left:0;
  right:0;
  z-index:30;
  border:1px solid var(--border);
  border-radius:12px;
  padding:8px;
  background: rgba(var(--panel-rgb), 0.94);
  box-shadow: var(--shadow);
  display:flex;
  flex-direction:column;
  gap:6px;
  max-height:280px;
  overflow:auto;
}
.wx-popover[hidden] { display:none; }
.wx-popover-item {
  border:1px solid var(--border);
  border-radius:10px;
  padding:8px 10px;
  background: var(--ui-control-bg);
  cursor:pointer;
  text-align:left;
  display:flex;
  flex-direction:column;
  gap:4px;
}
.wx-popover-item.active { border-color: rgba(var(--accent-rgb), 0.45); background: rgba(var(--accent-rgb), 0.08); }
.wx-popover-item:hover { background: rgba(var(--accent-rgb), 0.06); }
.wx-popover-card { margin-top: 2px; }
.wx-scroll-list {
  display:flex;
  flex-direction:column;
  gap:10px;
  max-height:520px;
  overflow:auto;
  padding-right:4px;
}
.wx-inline-stack { display:flex; flex-direction:column; gap:10px; }
.wx-setting-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap:12px; }
.wx-field { display:flex; flex-direction:column; gap:6px; min-width:0; }
.wx-field label { font-size:12px; font-weight:700; color:var(--ui-ink); }
.wx-json {
  border:1px solid var(--border);
  border-radius:10px;
  padding:8px;
  background: rgba(var(--panel-rgb), 0.45);
  font-family: Consolas, Menlo, Monaco, monospace;
  font-size:11px;
  white-space:pre-wrap;
  overflow-wrap:anywhere;
}
  `;
  document.head.appendChild(style);
}

function getState(ctx, sid) {
  if (!ctx.state.workflowExchange || typeof ctx.state.workflowExchange !== "object") {
    ctx.state.workflowExchange = { bySid: {} };
  }
  if (!ctx.state.workflowExchange.bySid) ctx.state.workflowExchange.bySid = {};
  if (!ctx.state.workflowExchange.bySid[sid]) {
    ctx.state.workflowExchange.bySid[sid] = {
      imports: [],
      discover: [],
      publicDiscover: [],
      statusText: "",
      errorText: "",
      loading: false,
      savingSettings: false,
      publicQuery: "",
      discoverQuery: "",
      mirrorQuery: "",
      activeTab: "exchange",
      mirrorId: "default",
      relayUrl: "http://host.docker.internal:5001",
      publicRelayUrl: "https://account.gotchat.ai/api",
      privateRelayUrl: "http://host.docker.internal:5001",
      lastLoadedAt: 0,
      discoverySummary: "",
      publicSummary: "",
      sync: {},
      settings: {},
      mirrors: [],
      settingsSchema: [],
    };
  }
  return ctx.state.workflowExchange.bySid[sid];
}

function firstConfiguredUrl(value) {
  if (Array.isArray(value)) {
    const hit = value.find((item) => String(item || "").trim());
    return String(hit || "").trim();
  }
  return String(value || "").trim();
}

function activeIds(ctx) {
  const pid = String(ctx?.state?.auth?.activeProjectId || ctx?.state?.ui?.activeProjectId || ctx?.state?.ui?.activePid || "").trim();
  const sid = String(ctx?.state?.ui?.activeSid || "").trim();
  return { pid, sid };
}

function formatTs(ts) {
  const n = Number(ts || 0);
  if (!n) return "";
  try {
    return new Date(n * 1000).toLocaleString();
  } catch {
    return "";
  }
}

function statusLabel(raw) {
  const v = String(raw || "").trim();
  if (!v) return "unknown";
  return v.replace(/_/g, " ");
}

function shortError(text) {
  const v = String(text || "").trim();
  if (!v) return "";
  return v.length > 120 ? `${v.slice(0, 117)}...` : v;
}

function listToText(value) {
  return Array.isArray(value) ? value.map((item) => String(item || "").trim()).filter(Boolean).join("\n") : "";
}

function textToList(value) {
  return String(value || "")
    .split(/\r?\n|,/)
    .map((item) => String(item || "").trim())
    .filter(Boolean);
}

function button(label, className, onClick) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = className || "";
  btn.textContent = label;
  btn.addEventListener("click", onClick);
  return btn;
}

function pickerTextParts(item) {
  if (!item || typeof item !== "object") return [];
  const out = [];
  for (const value of Object.values(item)) {
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
      out.push(String(value));
    } else if (Array.isArray(value)) {
      for (const inner of value) out.push(String(inner || ""));
    }
  }
  return out;
}

function createSectionPicker({
  placeholder,
  emptyText,
  items,
  getId,
  getTitle,
  getSubtitle,
  renderSelected,
}) {
  const rows = Array.isArray(items) ? items.slice() : [];
  const wrap = document.createElement("div");
  wrap.className = "wx-picker";
  if (!rows.length) {
    const empty = document.createElement("div");
    empty.className = "wx-empty";
    empty.textContent = emptyText;
    wrap.appendChild(empty);
    return wrap;
  }
  let selectedId = String(getId(rows[0]) || "");
  const meta = document.createElement("div");
  meta.className = "wx-picker-meta";
  const chip = document.createElement("div");
  chip.className = "wx-picker-chip";
  meta.appendChild(chip);
  wrap.appendChild(meta);
  const control = document.createElement("div");
  control.className = "wx-picker-control";
  const chevron = document.createElement("div");
  chevron.className = "wx-picker-chevron";
  chevron.textContent = "▾";
  const input = document.createElement("input");
  input.className = "wx-picker-input";
  input.type = "search";
  input.placeholder = placeholder;
  control.appendChild(chevron);
  control.appendChild(input);
  wrap.appendChild(control);
  const pop = document.createElement("div");
  pop.className = "wx-popover";
  pop.hidden = true;
  wrap.appendChild(pop);
  let expandedId = "";

  function filtered() {
    const q = String(input.value || "").trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((item) => pickerTextParts(item).join(" ").toLowerCase().includes(q));
  }

  function renderList() {
    const visible = filtered();
    chip.textContent = `${visible.length} item${visible.length === 1 ? "" : "s"}`;
    pop.innerHTML = "";
    if (!visible.length) {
      const empty = document.createElement("div");
      empty.className = "wx-empty";
      empty.textContent = "No matching items.";
      pop.appendChild(empty);
      return;
    }
    visible.forEach((item) => {
      const id = String(getId(item) || "");
      const row = document.createElement("button");
      row.type = "button";
      row.className = `wx-popover-item${id === selectedId ? " active" : ""}`;
      const title = document.createElement("div");
      title.className = "wx-title";
      title.textContent = getTitle(item);
      row.appendChild(title);
      const subText = String(getSubtitle(item) || "").trim();
      if (subText) {
        const sub = document.createElement("div");
        sub.className = "wx-sub";
        sub.textContent = subText;
        row.appendChild(sub);
      }
      row.addEventListener("click", () => {
        selectedId = id;
        expandedId = expandedId === id ? "" : id;
        renderList();
      });
      pop.appendChild(row);
      if (expandedId === id) {
        const cardWrap = document.createElement("div");
        cardWrap.className = "wx-popover-card";
        cardWrap.appendChild(renderSelected(item));
        pop.appendChild(cardWrap);
      }
    });
  }

  input.addEventListener("focus", () => {
    pop.hidden = false;
    chevron.textContent = "▴";
    renderList();
  });
  input.addEventListener("input", () => {
    pop.hidden = false;
    chevron.textContent = "▴";
    expandedId = "";
    renderList();
  });
  input.addEventListener("click", (event) => {
    event.stopPropagation();
    pop.hidden = false;
    chevron.textContent = "▴";
    renderList();
  });
  control.addEventListener("click", (event) => {
    if (event.target === input) return;
    pop.hidden = !pop.hidden;
    chevron.textContent = pop.hidden ? "▾" : "▴";
    if (!pop.hidden) renderList();
    input.focus();
  });
  wrap.addEventListener("focusout", () => {
    window.setTimeout(() => {
      if (!wrap.contains(document.activeElement)) {
        pop.hidden = true;
        chevron.textContent = "▾";
      }
    }, 0);
  });
  input.value = "";
  renderList();
  return wrap;
}

async function apiJsonWithBody(ctx, path, body) {
  return ctx.apiJson(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
}

async function saveExchangeSettings(ctx, host, container, nextSettings) {
  const { sid } = activeIds(ctx);
  const state = getState(ctx, sid || "default");
  state.errorText = "";
  state.savingSettings = true;
  state.statusText = "Saving exchange settings...";
  renderPanel(container, ctx, host);
  try {
    const data = await apiJsonWithBody(ctx, "/v1/workflow_exchange/settings", { settings: nextSettings || {} });
    state.settings = data?.settings && typeof data.settings === "object" ? data.settings : state.settings;
    state.statusText = "Exchange settings saved.";
    ctx.saveState?.();
    await loadExchangeState(ctx, host, container);
    state.savingSettings = false;
    renderPanel(container, ctx, host);
  } catch (err) {
    state.savingSettings = false;
    state.errorText = `Saving settings failed: ${err?.message || err}`;
    renderPanel(container, ctx, host);
  }
}

async function loadExchangeState(ctx, host, container) {
  const { sid } = activeIds(ctx);
  const state = getState(ctx, sid || "default");
  state.loading = true;
  state.errorText = "";
  renderPanel(container, ctx, host);
  try {
    const [importsData, discoverData, publicData, statusData, peersData, settingsData] = await Promise.all([
      ctx.apiJson("/v1/workflow_exchange/imports"),
      ctx.apiJson("/v1/workflow_exchange/discover"),
      ctx.apiJson("/v1/workflow_exchange/discover?scope=public"),
      ctx.apiJson("/v1/workflow_exchange/status"),
      ctx.apiJson("/v1/workflow_exchange/federation/peers"),
      ctx.apiJson("/v1/workflow_exchange/settings"),
    ]);
    state.imports = Array.isArray(importsData?.items) ? importsData.items : [];
    state.discover = Array.isArray(discoverData?.items) ? discoverData.items : [];
    state.publicDiscover = Array.isArray(publicData?.items) ? publicData.items : [];
    state.discoverySummary = String(discoverData?.summary || "").trim();
    state.publicSummary = String(publicData?.summary || "").trim();
    state.sync = statusData?.sync && typeof statusData.sync === "object" ? statusData.sync : {};
    state.settings = settingsData?.settings && typeof settingsData.settings === "object" ? settingsData.settings : {};
    state.settingsSchema = Array.isArray(settingsData?.settings_schema) ? settingsData.settings_schema : [];
    state.mirrors = Array.isArray(peersData?.mirrors) ? peersData.mirrors : [];
    state.publicRelayUrl = firstConfiguredUrl(state.settings?.workflow_exchange_public_relays) || "https://account.gotchat.ai/api";
    state.privateRelayUrl = firstConfiguredUrl(state.settings?.workflow_exchange_private_relays)
      || firstConfiguredUrl(state.settings?.workflow_exchange_allowed_mirrors)
      || "http://host.docker.internal:5001";
    if (!String(state.relayUrl || "").trim() || String(state.relayUrl || "").trim() === "https://relay.example/api") {
      state.relayUrl = state.privateRelayUrl || state.publicRelayUrl;
    }
    if (!state.mirrorId && state.mirrors[0]?.mirror_id) state.mirrorId = String(state.mirrors[0].mirror_id || "default");
    state.statusText = `Loaded ${state.imports.length} imported and ${state.discover.length} discovered workflows. Mirror sync uses incremental hash/cursor updates.`;
    state.lastLoadedAt = Date.now();
  } catch (err) {
    state.errorText = `Load failed: ${err?.message || err}`;
  } finally {
    state.loading = false;
    ctx.saveState?.();
    renderPanel(container, ctx, host);
  }
}

async function runMirrorAction(ctx, host, container, action) {
  const { sid } = activeIds(ctx);
  const state = getState(ctx, sid || "default");
  state.errorText = "";
  const mirrorId = String(state.mirrorId || "default").trim() || "default";
  const relayUrl = String(state.relayUrl || "").trim();
  state.statusText = `${action === "push" ? "Pushing" : "Pulling"} mirror ${mirrorId}...`;
  renderPanel(container, ctx, host);
  try {
    const payload = {
      mirror_id: mirrorId,
      visibility: "public",
    };
    if (relayUrl) payload.relay_url = relayUrl;
    if (action === "pull") {
      payload.records = [];
    }
    await apiJsonWithBody(ctx, `/v1/workflow_exchange/mirror/${action}`, payload);
    state.statusText = `Mirror ${action} complete.`;
    await loadExchangeState(ctx, host, container);
  } catch (err) {
    state.errorText = `Mirror ${action} failed: ${err?.message || err}`;
    renderPanel(container, ctx, host);
  }
}

function matchesQuery(textParts, query) {
  const q = String(query || "").trim().toLowerCase();
  if (!q) return true;
  return textParts.join(" ").toLowerCase().includes(q);
}

function filteredImports(state) {
  return (state.imports || []).filter((item) => {
    return matchesQuery([
    item?.flow_name,
    item?.workflow_id,
    item?.import_status,
    item?.evaluation_status,
    item?.visibility,
    item?.installed_flow_name,
    ], "");
  });
}

function filteredDiscover(state) {
  return (state.discover || []).filter((item) => matchesQuery([
    item?.flow_name,
    item?.workflow_id,
    item?.visibility,
    item?.summary,
    ...(Array.isArray(item?.tags) ? item.tags : []),
  ], state.discoverQuery)).filter((item) => !isRelayTestFlow(item));
}

function filteredPublicDiscover(state) {
  return (state.publicDiscover || []).filter((item) => matchesQuery([
    item?.flow_name,
    item?.workflow_id,
    item?.visibility,
    item?.summary,
    ...(Array.isArray(item?.tags) ? item.tags : []),
  ], state.publicQuery)).filter((item) => !isRelayTestFlow(item));
}

function isRelayTestFlow(item) {
  const flowName = String(item?.flow_name || "").trim().toLowerCase();
  const workflowId = String(item?.workflow_id || "").trim().toLowerCase();
  const packageId = String(item?.package_id || "").trim().toLowerCase();
  return (
    flowName.startsWith("relay_") ||
    flowName.startsWith("probe_") ||
    flowName.startsWith("public_verify_") ||
    workflowId.startsWith("relay_") ||
    workflowId.startsWith("probe_") ||
    workflowId.startsWith("public_verify_") ||
    packageId.startsWith("relay-") ||
    packageId.startsWith("probe-") ||
    packageId.startsWith("public-verify-")
  );
}

function deriveImportFilterKey(item) {
  if (item?.installed) return "installed";
  if (item?.ready_to_flow) return "ready";
  const importStatus = String(item?.import_status || "").trim();
  const evaluationStatus = String(item?.evaluation_status || "").trim();
  const validationStatus = String(item?.last_validation_status || "").trim();
  if (importStatus === "blocked" || evaluationStatus === "failed" || validationStatus === "failed") return "blocked";
  if (String(importStatus).includes("running") || String(evaluationStatus).includes("running") || evaluationStatus === "requested") return "evaluating";
  if (importStatus === "needs_local_skill_generation") return "needs_skills";
  if (importStatus === "quarantine_review" || validationStatus === "quarantine_review") return "review";
  return "imported";
}

function importSummary(items) {
  const summary = {
    total: 0,
    ready: 0,
    evaluating: 0,
    needs_skills: 0,
    review: 0,
    blocked: 0,
    installed: 0,
    imported: 0,
  };
  for (const item of Array.isArray(items) ? items : []) {
    summary.total += 1;
    const key = deriveImportFilterKey(item);
    if (summary[key] != null) summary[key] += 1;
  }
  return summary;
}

function openAgentFlowDesigner(host, item) {
  const designer = item?.designer || {};
  const recordId = String(designer?.record_id || designer?.open?.record_id || "").trim();
  if (!recordId) return false;
  const request = {
    record_id: recordId,
    pid: designer?.open?.pid || "",
    sid: designer?.open?.sid || "",
    flow_name: designer?.open?.flow_name || "",
  };
  try {
    host?.activatePanelTab?.("agent_flow");
  } catch {}
  try {
    window[AGENT_FLOW_PENDING_KEY] = request;
    const emit = () => window.dispatchEvent(new CustomEvent(AGENT_FLOW_OPEN_EVENT, { detail: request }));
    emit();
    window.setTimeout(emit, 180);
    return true;
  } catch {
    return false;
  }
}

function openAgentFlowDesignerAction(host, action, supportDesigners) {
  const recordId = String(action?.record_id || "").trim();
  if (!recordId) return false;
  const request = {
    record_id: recordId,
    pid: String(action?.pid || supportDesigners?.open?.pid || "").trim(),
    sid: String(action?.sid || supportDesigners?.open?.sid || "").trim(),
    flow_name: String(action?.flow_name || supportDesigners?.flow_name || "").trim(),
  };
  try {
    host?.activatePanelTab?.("agent_flow");
  } catch {}
  try {
    window[AGENT_FLOW_PENDING_KEY] = request;
    const emit = () => window.dispatchEvent(new CustomEvent(AGENT_FLOW_OPEN_EVENT, { detail: request }));
    emit();
    window.setTimeout(emit, 180);
    return true;
  } catch {
    return false;
  }
}

async function runImportAction(ctx, host, container, item, actionKey) {
  const { sid } = activeIds(ctx);
  const state = getState(ctx, sid || "default");
  state.errorText = "";
  const actions = item?.actions || {};
  const action = actions[actionKey] || {};
  if (action?.method === "CLIENT" || actionKey === "open_in_designer") {
    const supportDesigner = item?.support_designers?.[actionKey] || null;
    const ok = actionKey === "open_in_designer" ? openAgentFlowDesigner(host, item) : openAgentFlowDesignerAction(host, action, supportDesigner);
    state.statusText = ok ? "Opened workflow in Agent Flow." : "Designer handoff was not available.";
    renderPanel(container, ctx, host);
    return;
  }
  const path = String(action?.path || "").trim();
  if (!path) {
    state.errorText = `Missing action path for ${actionKey}.`;
    renderPanel(container, ctx, host);
    return;
  }
  state.statusText = `${statusLabel(actionKey)} requested...`;
  renderPanel(container, ctx, host);
  try {
    await apiJsonWithBody(ctx, path, {});
    state.statusText = `${statusLabel(actionKey)} complete.`;
    await loadExchangeState(ctx, host, container);
  } catch (err) {
    state.errorText = `${statusLabel(actionKey)} failed: ${err?.message || err}`;
    renderPanel(container, ctx, host);
  }
}

async function submitImportFeedback(ctx, host, container, item, satisfied) {
  const { sid } = activeIds(ctx);
  const state = getState(ctx, sid || "default");
  state.errorText = "";
  const path = String(item?.actions?.feedback?.path || "").trim();
  if (!path) {
    state.errorText = "Missing feedback action path.";
    renderPanel(container, ctx, host);
    return;
  }
  state.statusText = "Saving workflow feedback...";
  renderPanel(container, ctx, host);
  try {
    await apiJsonWithBody(ctx, path, {
      question: "Did this answer your question?",
      satisfied: Boolean(satisfied),
      target: "candidate",
    });
    state.statusText = "Workflow feedback saved.";
    await loadExchangeState(ctx, host, container);
  } catch (err) {
    state.errorText = `Feedback failed: ${err?.message || err}`;
    renderPanel(container, ctx, host);
  }
}

async function publishImport(ctx, host, container, item, visibility) {
  const { sid } = activeIds(ctx);
  const state = getState(ctx, sid || "default");
  state.errorText = "";
  const publishMode = String(visibility || "public").trim() || "public";
  state.statusText = `Publishing ${item?.flow_name || item?.workflow_id || "workflow"} as ${publishMode}...`;
  renderPanel(container, ctx, host);
  try {
    await apiJsonWithBody(ctx, "/v1/workflow_exchange/publish", {
      import_id: item?.id || "",
      visibility: publishMode,
    });
    state.statusText = "Publish complete.";
    await loadExchangeState(ctx, host, container);
  } catch (err) {
    state.errorText = `Publish failed: ${err?.message || err}`;
    renderPanel(container, ctx, host);
  }
}

async function importDiscovered(ctx, host, container, item) {
  const { pid, sid } = activeIds(ctx);
  const state = getState(ctx, sid || "default");
  state.errorText = "";
  const action = item?.actions?.import || {};
  const payload = action?.payload && typeof action.payload === "object" ? { ...action.payload } : {};
  payload.pid = pid;
  payload.sid = sid;
  state.statusText = `Importing ${item?.flow_name || item?.workflow_id || "workflow"}...`;
  renderPanel(container, ctx, host);
  try {
    await apiJsonWithBody(ctx, "/v1/workflow_exchange/import", payload);
    state.statusText = "Import complete.";
    await loadExchangeState(ctx, host, container);
  } catch (err) {
    state.errorText = `Import failed: ${err?.message || err}`;
    renderPanel(container, ctx, host);
  }
}

async function revokePublished(ctx, host, container, item) {
  const { sid } = activeIds(ctx);
  const state = getState(ctx, sid || "default");
  state.errorText = "";
  state.statusText = `Revoking ${item?.flow_name || item?.workflow_id || "workflow"}...`;
  renderPanel(container, ctx, host);
  try {
    await apiJsonWithBody(ctx, "/v1/workflow_exchange/revoke", { publish_id: item?.id || "", public_id: item?.id || "" });
    state.statusText = "Publish revoked.";
    await loadExchangeState(ctx, host, container);
  } catch (err) {
    state.errorText = `Revoke failed: ${err?.message || err}`;
    renderPanel(container, ctx, host);
  }
}

function renderImportCard(item, ctx, host, container, state) {
  const card = document.createElement("section");
  card.className = "wx-card";

  const head = document.createElement("div");
  head.className = "wx-card-head";
  const titleWrap = document.createElement("div");
  const title = document.createElement("div");
  title.className = "wx-title";
  title.textContent = String(item?.flow_name || item?.workflow_id || item?.id || "Imported Workflow");
  const sub = document.createElement("div");
  sub.className = "wx-sub";
  sub.textContent = [
    item?.visibility ? `visibility: ${item.visibility}` : "",
    item?.workflow_id ? `workflow: ${item.workflow_id}` : "",
    item?.installed_flow_name ? `installed: ${item.installed_flow_name}` : "",
  ].filter(Boolean).join(" | ");
  titleWrap.appendChild(title);
  titleWrap.appendChild(sub);
  const badges = document.createElement("div");
  badges.className = "wx-badges";
  for (const badgeText of [item?.import_status, item?.evaluation_status, item?.comparison_status]) {
    if (!badgeText) continue;
    const badge = document.createElement("span");
    badge.className = `wx-badge status-${String(badgeText).trim()}`;
    badge.textContent = statusLabel(badgeText);
    badges.appendChild(badge);
  }
  if (item?.ready_to_flow) {
    const badge = document.createElement("span");
    badge.className = "wx-badge status-ready_to_flow";
    badge.textContent = "ready";
    badges.appendChild(badge);
  }
  if (item?.installed) {
    const badge = document.createElement("span");
    badge.className = "wx-badge";
    badge.textContent = "installed";
    badges.appendChild(badge);
  }
  head.appendChild(titleWrap);
  head.appendChild(badges);
  card.appendChild(head);

  const grid = document.createElement("div");
  grid.className = "wx-grid";
  for (const [k, v] of [
    ["Imported", formatTs(item?.imported_ts)],
    ["Updated", formatTs(item?.updated_ts)],
    ["Validation", item?.last_validation_status || ""],
    ["Pass/Fail", `${Number(item?.pass_count || 0)}/${Number(item?.fail_count || 0)}`],
    ["Compare", item?.comparison_status ? statusLabel(item.comparison_status) : ""],
    ["A/B Verdict", item?.last_update_comparison?.recommendation || ""],
    ["User Feedback", item?.user_feedback_status ? statusLabel(item.user_feedback_status) : ""],
  ]) {
    const wrap = document.createElement("div");
    wrap.className = "wx-kv";
    const kk = document.createElement("div");
    kk.className = "k";
    kk.textContent = k;
    const vv = document.createElement("div");
    vv.className = "v";
    vv.textContent = String(v || "");
    wrap.appendChild(kk);
    wrap.appendChild(vv);
    grid.appendChild(wrap);
  }
  card.appendChild(grid);

  const actions = document.createElement("div");
  actions.className = "wx-actions";
  const evaluateBtn = button("Evaluate", "primary", () => void runImportAction(ctx, host, container, item, "evaluate"));
  const refreshBtn = button("Refresh", "", () => void runImportAction(ctx, host, container, item, "refresh"));
  const openBtn = button("Open in Designer", "", () => void runImportAction(ctx, host, container, item, "open_in_designer"));
  const installBtn = button("Install", "", () => void runImportAction(ctx, host, container, item, "install"));
  const regenBtn = button("Regenerate Skills", "", () => void runImportAction(ctx, host, container, item, "regenerate_skills"));
  const repairBtn = button("Repair Skills", "", () => void runImportAction(ctx, host, container, item, "repair_skills"));
  const reviewBtn = button("Quarantine Review", "", () => void runImportAction(ctx, host, container, item, "quarantine_review"));
  const compareBtn = button("Compare To Current", "", () => void runImportAction(ctx, host, container, item, "compare"));
  const publishPublicBtn = button("Publish Public", "", () => void publishImport(ctx, host, container, item, "public"));
  const publishPrivateBtn = button("Publish Private", "", () => void publishImport(ctx, host, container, item, "private"));
  const openRegenFlowBtn = button("Open Skill Flow", "", () => void runImportAction(ctx, host, container, item, "open_skill_regen_flow"));
  const openReviewFlowBtn = button("Open Review Flow", "", () => void runImportAction(ctx, host, container, item, "open_quarantine_review_flow"));
  if (String(item?.import_status || "").includes("running")) evaluateBtn.disabled = true;
  if (!item?.designer?.record_id) openBtn.disabled = true;
  if (!item?.actions?.regenerate_skills?.path) regenBtn.disabled = true;
  if (!item?.actions?.repair_skills?.path) repairBtn.disabled = true;
  if (!item?.actions?.quarantine_review?.path) reviewBtn.disabled = true;
  if (!item?.actions?.compare?.path) compareBtn.disabled = true;
  if (!item?.actions?.open_skill_regen_flow) openRegenFlowBtn.disabled = true;
  if (!item?.actions?.open_quarantine_review_flow) openReviewFlowBtn.disabled = true;
  actions.appendChild(evaluateBtn);
  actions.appendChild(refreshBtn);
  actions.appendChild(openBtn);
  actions.appendChild(installBtn);
  actions.appendChild(regenBtn);
  actions.appendChild(repairBtn);
  actions.appendChild(reviewBtn);
  actions.appendChild(compareBtn);
  actions.appendChild(openRegenFlowBtn);
  actions.appendChild(openReviewFlowBtn);
  actions.appendChild(publishPublicBtn);
  actions.appendChild(publishPrivateBtn);
  card.appendChild(actions);

  if (item?.actions?.feedback?.path) {
    const feedbackBox = document.createElement("div");
    feedbackBox.className = "wx-feedback-box";
    const feedbackQ = document.createElement("div");
    feedbackQ.className = "wx-feedback-q";
    feedbackQ.textContent = "Did this answer your question?";
    const feedbackActions = document.createElement("div");
    feedbackActions.className = "wx-actions";
    const yesBtn = button("Yes", "primary", () => void submitImportFeedback(ctx, host, container, item, true));
    const noBtn = button("No", "", () => void submitImportFeedback(ctx, host, container, item, false));
    feedbackActions.appendChild(yesBtn);
    feedbackActions.appendChild(noBtn);
    feedbackBox.appendChild(feedbackQ);
    feedbackBox.appendChild(feedbackActions);
    if (item?.last_user_feedback?.ts) {
      const feedbackMeta = document.createElement("div");
      feedbackMeta.className = "wx-feedback-meta";
      feedbackMeta.textContent = `Last response: ${item?.last_user_feedback?.satisfied ? "Yes" : "No"}${item?.last_user_feedback?.ts ? ` | ${formatTs(item.last_user_feedback.ts)}` : ""}`;
      feedbackBox.appendChild(feedbackMeta);
    }
    card.appendChild(feedbackBox);
  }

  const designer = item?.designer || {};
  if (designer?.flow_name || designer?.workflow_file) {
    const json = document.createElement("div");
    json.className = "wx-json";
    json.textContent = JSON.stringify({
      flow_name: designer.flow_name || "",
      record_id: designer.record_id || "",
      workflow_file: designer.workflow_file || "",
      bundle_dir: designer.bundle_dir || "",
      validate_path: designer?.paths?.validate_path || "",
      install_path: designer?.paths?.install_path || "",
      generated_skill_ids: Array.isArray(item?.generated_skill_ids) ? item.generated_skill_ids : [],
      generated_skill_files: Array.isArray(item?.generated_skill_files) ? item.generated_skill_files : [],
      last_skill_regen_summary: item?.last_skill_regen_summary || {},
      last_quarantine_review_summary: item?.last_quarantine_review_summary || {},
      comparison_status: item?.comparison_status || "",
      candidate_better_than_current: item?.candidate_better_than_current,
      last_update_comparison: item?.last_update_comparison || {},
      user_feedback_status: item?.user_feedback_status || "",
      last_user_feedback: item?.last_user_feedback || {},
      user_satisfaction_score: item?.user_satisfaction_score ?? 0,
    }, null, 2);
    card.appendChild(json);
  }

  return card;
}

function renderDiscoverCard(item, ctx, host, container) {
  const card = document.createElement("section");
  card.className = "wx-card";

  const head = document.createElement("div");
  head.className = "wx-card-head";
  const titleWrap = document.createElement("div");
  const title = document.createElement("div");
  title.className = "wx-title";
  title.textContent = String(item?.flow_name || item?.workflow_id || item?.id || "Published Workflow");
  const sub = document.createElement("div");
  sub.className = "wx-sub";
  sub.textContent = [
    item?.visibility ? `visibility: ${item.visibility}` : "",
    item?.bundle_mode ? `bundle: ${item.bundle_mode}` : "",
    item?.workflow_id ? `workflow: ${item.workflow_id}` : "",
  ].filter(Boolean).join(" | ");
  titleWrap.appendChild(title);
  titleWrap.appendChild(sub);
  const badges = document.createElement("div");
  badges.className = "wx-badges";
  if (item?.visibility) {
    const badge = document.createElement("span");
    badge.className = "wx-badge";
    badge.textContent = item.visibility;
    badges.appendChild(badge);
  }
  if (item?.share_scope) {
    const badge = document.createElement("span");
    badge.className = "wx-badge";
    badge.textContent = item.share_scope;
    badges.appendChild(badge);
  }
  if (item?.source) {
    const badge = document.createElement("span");
    badge.className = "wx-badge";
    badge.textContent = item.source;
    badges.appendChild(badge);
  }
  if (item?.trust?.safety_score != null) {
    const badge = document.createElement("span");
    badge.className = "wx-badge";
    badge.textContent = `safe ${Number(item.trust.safety_score).toFixed(2)}`;
    badges.appendChild(badge);
  }
  head.appendChild(titleWrap);
  head.appendChild(badges);
  card.appendChild(head);

  const grid = document.createElement("div");
  grid.className = "wx-grid";
  for (const [k, v] of [
    ["Published", formatTs(item?.published_ts)],
    ["Updated", formatTs(item?.updated_ts)],
    ["Tags", Array.isArray(item?.tags) ? item.tags.join(", ") : ""],
    ["Summary", item?.summary || ""],
  ]) {
    const wrap = document.createElement("div");
    wrap.className = "wx-kv";
    const kk = document.createElement("div");
    kk.className = "k";
    kk.textContent = k;
    const vv = document.createElement("div");
    vv.className = "v";
    vv.textContent = String(v || "");
    wrap.appendChild(kk);
    wrap.appendChild(vv);
    grid.appendChild(wrap);
  }
  card.appendChild(grid);

  const actions = document.createElement("div");
  actions.className = "wx-actions";
  actions.appendChild(button("Import", "primary", () => void importDiscovered(ctx, host, container, item)));
  if (String(item?.source || "local") === "local") {
    actions.appendChild(button("Revoke", "warn", () => void revokePublished(ctx, host, container, item)));
  }
  card.appendChild(actions);

  const json = document.createElement("div");
  json.className = "wx-json";
  json.textContent = JSON.stringify({
    publish_id: item?.id || "",
    flow_name: item?.flow_name || "",
    workflow_id: item?.workflow_id || "",
    bundle_mode: item?.bundle_mode || "",
    visibility: item?.visibility || "",
    trust: item?.trust || {},
  }, null, 2);
  card.appendChild(json);

  return card;
}

function renderSettingsField(field, state) {
  const wrap = document.createElement("div");
  wrap.className = "wx-field";
  const label = document.createElement("label");
  label.textContent = String(field?.label || field?.key || "Setting");
  wrap.appendChild(label);
  let input;
  const key = String(field?.key || "").trim();
  const type = String(field?.type || "string").trim();
  const current = state.settings?.[key];
  if (type === "bool") {
    input = document.createElement("input");
    input.type = "checkbox";
    input.checked = !!current;
  } else if (type === "select") {
    input = document.createElement("select");
    input.className = "wx-select";
    const options = Array.isArray(field?.options) ? field.options : [];
    options.forEach((value) => {
      const opt = document.createElement("option");
      opt.value = String(value || "");
      opt.textContent = String(value || "");
      input.appendChild(opt);
    });
    input.value = String(current ?? field?.default ?? "");
  } else if (type === "number") {
    input = document.createElement("input");
    input.className = "wx-search";
    input.type = "number";
    input.step = "any";
    input.value = String(current ?? field?.default ?? 0);
  } else if (type === "list") {
    input = document.createElement("textarea");
    input.className = "wx-textarea";
    input.value = listToText(current ?? field?.default ?? []);
  } else {
    input = document.createElement("input");
    input.className = "wx-search";
    input.type = "text";
    input.value = String(current ?? field?.default ?? "");
  }
  input.dataset.settingKey = key;
  input.dataset.settingType = type;
  wrap.appendChild(input);
  const help = String(field?.help || "").trim();
  if (help) {
    const sub = document.createElement("div");
    sub.className = "wx-section-sub";
    sub.textContent = help;
    wrap.appendChild(sub);
  }
  return wrap;
}

function renderPanel(container, ctx, host) {
  ensureStyles();
  const { sid } = activeIds(ctx);
  const state = getState(ctx, sid || "default");
  container.innerHTML = "";

  const root = document.createElement("div");
  root.className = "wx-panel";

  const toolbar = document.createElement("div");
  toolbar.className = "wx-toolbar";
  const metaNode = document.createElement("div");
  metaNode.className = "wx-meta";
  metaNode.textContent = state.lastLoadedAt ? `Last loaded ${new Date(state.lastLoadedAt).toLocaleTimeString()}` : "Not loaded";
  toolbar.appendChild(metaNode);
  root.appendChild(toolbar);

  const tabs = document.createElement("div");
  tabs.className = "wx-tabs";
  for (const [value, label] of [
    ["exchange", "Exchange"],
    ["public", "Public Catalog"],
    ["discover", "Discover"],
    ["settings", "Settings"],
  ]) {
    const tab = document.createElement("button");
    tab.type = "button";
    tab.className = `wx-tab${state.activeTab === value ? " active" : ""}`;
    tab.textContent = label;
    tab.addEventListener("click", () => {
      state.activeTab = value;
      ctx.saveState?.();
      renderPanel(container, ctx, host);
    });
    tabs.appendChild(tab);
  }
  root.appendChild(tabs);

  if (state.statusText) {
    const status = document.createElement("div");
    status.className = "wx-status";
    status.textContent = state.statusText;
    root.appendChild(status);
  }
  if (state.errorText) {
    const err = document.createElement("div");
    err.className = "wx-error";
    err.textContent = state.errorText;
    root.appendChild(err);
  }

  const sections = document.createElement("div");
  sections.className = "wx-sections";

  if (state.activeTab === "exchange") {
    const exchangeOverview = document.createElement("div");
    exchangeOverview.className = "wx-overview";
    for (const [k, v] of [
      ["Local Published", Number(state.sync?.local_published_count || 0)],
      ["Public Catalog", Number(state.sync?.public_catalog_count || 0)],
      ["Mirror Peers", Number(state.sync?.mirror_peer_count || 0)],
      ["Mirror Records", Number(state.sync?.mirror_record_count || 0)],
      ["Pending Installs", Number(state.sync?.pending_installs || 0)],
    ]) {
      const wrap = document.createElement("div");
      wrap.className = "wx-kv";
      const kk = document.createElement("div");
      kk.className = "k";
      kk.textContent = k;
      const vv = document.createElement("div");
      vv.className = "v";
      vv.textContent = String(v);
      wrap.appendChild(kk);
      wrap.appendChild(vv);
      exchangeOverview.appendChild(wrap);
    }
    root.appendChild(exchangeOverview);

    const syncSettings = document.createElement("section");
    syncSettings.className = "wx-section";
    const syncHead = document.createElement("div");
    syncHead.className = "wx-section-head";
    const syncHeadText = document.createElement("div");
    const syncTitle = document.createElement("div");
    syncTitle.className = "wx-section-title";
    syncTitle.textContent = "Sync Settings";
    const syncSub = document.createElement("div");
    syncSub.className = "wx-section-sub";
    syncSub.textContent = "Configure whether public/private interval sync is enabled and the minimum seconds between sync passes.";
    syncHeadText.appendChild(syncTitle);
    syncHeadText.appendChild(syncSub);
    syncHead.appendChild(syncHeadText);
    syncSettings.appendChild(syncHead);
    const syncGrid = document.createElement("div");
    syncGrid.className = "wx-overview";
    for (const [k, v] of [
      ["Public Sync Floor", `${Number(state.settings?.workflow_exchange_public_sync_min_interval_s || 0)}s`],
      ["Private Sync Floor", `${Number(state.settings?.workflow_exchange_private_sync_min_interval_s || 0)}s`],
      ["Private Scheduled Sync", state.settings?.workflow_exchange_private_scheduled_sync_enabled ? "Enabled" : "Manual"],
      ["Relay URL", state.relayUrl || "Not set"],
    ]) {
      const wrap = document.createElement("div");
      wrap.className = "wx-kv";
      const kk = document.createElement("div");
      kk.className = "k";
      kk.textContent = k;
      const vv = document.createElement("div");
      vv.className = "v";
      vv.textContent = String(v || "");
      wrap.appendChild(kk);
      wrap.appendChild(vv);
      syncGrid.appendChild(wrap);
    }
    syncSettings.appendChild(syncGrid);
    const syncForm = document.createElement("div");
    syncForm.className = "wx-inline-stack";
    const publicToggleLabel = document.createElement("label");
    publicToggleLabel.className = "wx-sub";
    const publicToggle = document.createElement("input");
    publicToggle.type = "checkbox";
    publicToggle.checked = Boolean(state.settings?.workflow_exchange_public_scheduled_sync_enabled);
    publicToggleLabel.appendChild(publicToggle);
    publicToggleLabel.appendChild(document.createTextNode(" Enable public interval sync"));
    syncForm.appendChild(publicToggleLabel);
    const publicSeconds = document.createElement("input");
    publicSeconds.className = "wx-search";
    publicSeconds.type = "number";
    publicSeconds.min = "0";
    publicSeconds.step = "1";
    publicSeconds.value = String(Number(state.settings?.workflow_exchange_public_sync_min_interval_s || 0));
    publicSeconds.placeholder = "Public sync interval seconds";
    syncForm.appendChild(publicSeconds);
    const privateToggleLabel = document.createElement("label");
    privateToggleLabel.className = "wx-sub";
    const privateToggle = document.createElement("input");
    privateToggle.type = "checkbox";
    privateToggle.checked = Boolean(state.settings?.workflow_exchange_private_scheduled_sync_enabled);
    privateToggleLabel.appendChild(privateToggle);
    privateToggleLabel.appendChild(document.createTextNode(" Enable private interval sync"));
    syncForm.appendChild(privateToggleLabel);
    const privateSeconds = document.createElement("input");
    privateSeconds.className = "wx-search";
    privateSeconds.type = "number";
    privateSeconds.min = "0";
    privateSeconds.step = "1";
    privateSeconds.value = String(Number(state.settings?.workflow_exchange_private_sync_min_interval_s || 0));
    privateSeconds.placeholder = "Private sync interval seconds";
    syncForm.appendChild(privateSeconds);
    const saveSettingsBtn = button(state.savingSettings ? "Saving..." : "Save Sync Settings", "primary", () => {
      const nextSettings = {
        workflow_exchange_public_scheduled_sync_enabled: !!publicToggle.checked,
        workflow_exchange_public_sync_min_interval_s: Number(publicSeconds.value || 0),
        workflow_exchange_private_scheduled_sync_enabled: !!privateToggle.checked,
        workflow_exchange_private_sync_min_interval_s: Number(privateSeconds.value || 0),
      };
      void saveExchangeSettings(ctx, host, container, nextSettings);
    });
    saveSettingsBtn.disabled = !!state.savingSettings;
    syncForm.appendChild(saveSettingsBtn);
    syncSettings.appendChild(syncForm);
    root.appendChild(syncSettings);

    const mirrorSection = document.createElement("section");
    mirrorSection.className = "wx-section";
    const mirrorHead = document.createElement("div");
    mirrorHead.className = "wx-section-head";
    const mirrorHeadText = document.createElement("div");
    const mirrorTitle = document.createElement("div");
    mirrorTitle.className = "wx-section-title";
    mirrorTitle.textContent = "Mirrors";
    const mirrorSub = document.createElement("div");
    mirrorSub.className = "wx-section-sub";
    const publicInterval = Number(state.settings?.workflow_exchange_public_sync_min_interval_s || 0);
    const privateInterval = Number(state.settings?.workflow_exchange_private_sync_min_interval_s || 0);
    const publicScheduled = Boolean(state.settings?.workflow_exchange_public_scheduled_sync_enabled);
    const privateScheduled = Boolean(state.settings?.workflow_exchange_private_scheduled_sync_enabled);
    mirrorSub.textContent = `Relay-assisted mirror sync with incremental hash/cursor updates. Public relay defaults to ${state.publicRelayUrl || "https://account.gotchat.ai/api"}. Private/local mirror relay defaults to ${state.privateRelayUrl || "http://host.docker.internal:5001"}. Public sync is ${publicScheduled ? "enabled" : "manual"} with ${publicInterval}s floor. Private sync is ${privateScheduled ? "enabled" : "manual"} with ${privateInterval}s floor.`;
    mirrorHeadText.appendChild(mirrorTitle);
    mirrorHeadText.appendChild(mirrorSub);
    mirrorHead.appendChild(mirrorHeadText);
    mirrorSection.appendChild(mirrorHead);
    const mirrorControls = document.createElement("div");
    mirrorControls.className = "wx-actions";
    const mirrorInput = document.createElement("input");
    mirrorInput.className = "wx-search";
    mirrorInput.type = "text";
    mirrorInput.placeholder = "Mirror id";
    mirrorInput.value = state.mirrorId || "default";
    mirrorInput.addEventListener("input", () => {
      state.mirrorId = mirrorInput.value || "default";
      ctx.saveState?.();
    });
    const relayInput = document.createElement("input");
    relayInput.className = "wx-search";
    relayInput.type = "url";
    relayInput.placeholder = "Mirror relay URL e.g. http://host.docker.internal:5001";
    relayInput.value = state.relayUrl || "";
    relayInput.addEventListener("input", () => {
      state.relayUrl = relayInput.value || "";
      ctx.saveState?.();
    });
    mirrorControls.appendChild(mirrorInput);
    mirrorControls.appendChild(relayInput);
    mirrorControls.appendChild(button("Push Local -> Mirror", "", () => void runMirrorAction(ctx, host, container, "push")));
    mirrorControls.appendChild(button("Pull Mirror", "", () => void runMirrorAction(ctx, host, container, "pull")));
    mirrorSection.appendChild(mirrorControls);
    const mirrorSearch = document.createElement("input");
    mirrorSearch.className = "wx-search";
    mirrorSearch.type = "search";
    mirrorSearch.placeholder = "Search mirrors";
    mirrorSearch.value = state.mirrorQuery || "";
    mirrorSearch.addEventListener("input", () => {
      state.mirrorQuery = mirrorSearch.value || "";
      ctx.saveState?.();
      renderPanel(container, ctx, host);
    });
    mirrorSection.appendChild(mirrorSearch);
    const mirrorList = document.createElement("div");
    mirrorList.className = "wx-scroll-list";
    function renderMirrorCard(peer) {
      const card = document.createElement("section");
      card.className = "wx-card";
      const title = document.createElement("div");
      title.className = "wx-title";
      title.textContent = String(peer?.label || peer?.mirror_id || "Mirror");
      const sub = document.createElement("div");
      sub.className = "wx-sub";
      sub.textContent = [
        peer?.mirror_id ? `id: ${peer.mirror_id}` : "",
        peer?.direction ? `last: ${peer.direction}` : "",
        peer?.visibility ? `visibility: ${peer.visibility}` : "",
        peer?.sync_mode ? `sync: ${peer.sync_mode}` : "",
      ].filter(Boolean).join(" | ");
      const grid = document.createElement("div");
      grid.className = "wx-grid";
      for (const [k, v] of [
        ["Last Sync", formatTs(peer?.last_sync_ts)],
        ["Last Pull", formatTs(peer?.last_pull_ts)],
        ["Last Push", formatTs(peer?.last_push_ts)],
        ["Records", Number(peer?.record_count || 0)],
        ["Cursor", Number(peer?.public_cursor_ts || 0)],
        ["Last Sent", Number(peer?.last_sent_count || 0)],
        ["Last Skipped", Number(peer?.last_skipped_count || 0)],
        ["Last Received", Number(peer?.last_received_count || 0)],
      ]) {
        const wrap = document.createElement("div");
        wrap.className = "wx-kv";
        const kk = document.createElement("div");
        kk.className = "k";
        kk.textContent = k;
        const vv = document.createElement("div");
        vv.className = "v";
        vv.textContent = String(v || "");
        wrap.appendChild(kk);
        wrap.appendChild(vv);
        grid.appendChild(wrap);
      }
      card.appendChild(title);
      card.appendChild(sub);
      card.appendChild(grid);
      const syncJson = document.createElement("div");
      syncJson.className = "wx-json";
      syncJson.textContent = JSON.stringify({
        last_status: peer?.last_status || "",
        last_error: shortError(peer?.last_error || ""),
        last_remote_results: Array.isArray(peer?.last_remote_results) ? peer.last_remote_results : [],
      }, null, 2);
      card.appendChild(syncJson);
      return card;
    }
    const mirrorItems = (state.mirrors || []).filter((item) => matchesQuery([
      item?.label,
      item?.mirror_id,
      item?.visibility,
      item?.direction,
      item?.sync_mode,
      item?.last_status,
      item?.last_error,
    ], state.mirrorQuery));
    if (!mirrorItems.length) {
      const empty = document.createElement("div");
      empty.className = "wx-empty";
      empty.textContent = state.loading ? "Loading mirrors..." : "No mirror peers tracked yet.";
      mirrorList.appendChild(empty);
    } else {
      mirrorItems.forEach((item) => mirrorList.appendChild(renderMirrorCard(item)));
    }
    mirrorSection.appendChild(mirrorList);
    sections.appendChild(mirrorSection);

    const importsSection = document.createElement("section");
    importsSection.className = "wx-section";
    const importsHead = document.createElement("div");
    importsHead.className = "wx-section-head";
    const importsHeadText = document.createElement("div");
    const importsTitle = document.createElement("div");
    importsTitle.className = "wx-section-title";
    const importItems = filteredImports(state);
    const allImportSummary = importSummary(state.imports || []);
    importsTitle.textContent = `Imported Workflows (${importItems.length})`;
    const importsSub = document.createElement("div");
    importsSub.className = "wx-section-sub";
    importsSub.textContent = "Imported exchange workflows tracked locally with evaluation, readiness, and designer handoff status.";
    importsHeadText.appendChild(importsTitle);
    importsHeadText.appendChild(importsSub);
    importsHead.appendChild(importsHeadText);
    importsSection.appendChild(importsHead);
    const importsOverview = document.createElement("div");
    importsOverview.className = "wx-overview";
    for (const [k, v] of [
      ["Total Imported", allImportSummary.total],
      ["Ready To Flow", allImportSummary.ready],
      ["Evaluating", allImportSummary.evaluating],
      ["Needs Skills", allImportSummary.needs_skills],
      ["Review / Quarantine", allImportSummary.review],
      ["Blocked / Failed", allImportSummary.blocked],
      ["Installed", allImportSummary.installed],
    ]) {
      const wrap = document.createElement("div");
      wrap.className = "wx-kv";
      const kk = document.createElement("div");
      kk.className = "k";
      kk.textContent = k;
      const vv = document.createElement("div");
      vv.className = "v";
      vv.textContent = String(v);
      wrap.appendChild(kk);
      wrap.appendChild(vv);
      importsOverview.appendChild(wrap);
    }
    importsSection.appendChild(importsOverview);
    const importsList = document.createElement("div");
    importsList.className = "wx-list";
    importsList.appendChild(createSectionPicker({
      placeholder: "Search imported workflows",
      emptyText: state.loading ? "Loading imported workflows..." : "No imported exchange workflows found.",
      items: importItems,
      getId: (item) => item?.id || item?.workflow_id || "",
      getTitle: (item) => String(item?.flow_name || item?.workflow_id || item?.id || "Imported Workflow"),
      getSubtitle: (item) => [
        item?.import_status ? statusLabel(item.import_status) : "",
        item?.evaluation_status ? statusLabel(item.evaluation_status) : "",
        item?.comparison_status ? statusLabel(item.comparison_status) : "",
        item?.installed_flow_name ? `installed: ${item.installed_flow_name}` : "",
      ].filter(Boolean).join(" | "),
      renderSelected: (item) => renderImportCard(item, ctx, host, container, state),
    }));
    importsSection.appendChild(importsList);
    sections.appendChild(importsSection);
  } else if (state.activeTab === "public") {
    const publicSection = document.createElement("section");
    publicSection.className = "wx-section";
    const publicHead = document.createElement("div");
    publicHead.className = "wx-section-head";
    const publicHeadText = document.createElement("div");
    const publicTitle = document.createElement("div");
    publicTitle.className = "wx-section-title";
    publicTitle.textContent = "Public Catalog";
    const publicSub = document.createElement("div");
    publicSub.className = "wx-section-sub";
    publicSub.textContent = state.publicSummary || "Public-safe workflows shared to the broader exchange. These entries are sanitized for public distribution and are intended for general reuse.";
    publicHeadText.appendChild(publicTitle);
    publicHeadText.appendChild(publicSub);
    publicHead.appendChild(publicHeadText);
    publicSection.appendChild(publicHead);
    const publicSearch = document.createElement("input");
    publicSearch.className = "wx-search";
    publicSearch.type = "search";
    publicSearch.placeholder = "Search public catalog";
    publicSearch.value = state.publicQuery || "";
    publicSearch.addEventListener("input", () => {
      state.publicQuery = publicSearch.value || "";
      ctx.saveState?.();
      renderPanel(container, ctx, host);
    });
    publicSection.appendChild(publicSearch);
    const publicList = document.createElement("div");
    publicList.className = "wx-scroll-list";
    const publicItems = filteredPublicDiscover(state);
    if (!publicItems.length) {
      const empty = document.createElement("div");
      empty.className = "wx-empty";
      empty.textContent = state.loading ? "Loading public workflows..." : "No public workflows available yet.";
      publicList.appendChild(empty);
    } else {
      publicItems.forEach((item) => publicList.appendChild(renderDiscoverCard(item, ctx, host, container)));
    }
    publicSection.appendChild(publicList);
    sections.appendChild(publicSection);
  } else if (state.activeTab === "discover") {
    const discoverSection = document.createElement("section");
    discoverSection.className = "wx-section";
    const discoverHead = document.createElement("div");
    discoverHead.className = "wx-section-head";
    const discoverHeadText = document.createElement("div");
    const discoverTitle = document.createElement("div");
    discoverTitle.className = "wx-section-title";
    discoverTitle.textContent = "Discover";
    const discoverSub = document.createElement("div");
    discoverSub.className = "wx-section-sub";
    discoverSub.textContent = state.discoverySummary || "Workflows discovered through your configured exchange sources, mirrors, or relay. This view is broader than Public Catalog and may include private or organization-scoped exchange records.";
    discoverHeadText.appendChild(discoverTitle);
    discoverHeadText.appendChild(discoverSub);
    discoverHead.appendChild(discoverHeadText);
    discoverSection.appendChild(discoverHead);
    const discoverSearch = document.createElement("input");
    discoverSearch.className = "wx-search";
    discoverSearch.type = "search";
    discoverSearch.placeholder = "Search discovered workflows";
    discoverSearch.value = state.discoverQuery || "";
    discoverSearch.addEventListener("input", () => {
      state.discoverQuery = discoverSearch.value || "";
      ctx.saveState?.();
      renderPanel(container, ctx, host);
    });
    discoverSection.appendChild(discoverSearch);
    const discoverList = document.createElement("div");
    discoverList.className = "wx-scroll-list";
    const discoveredItems = filteredDiscover(state);
    if (!discoveredItems.length) {
      const empty = document.createElement("div");
      empty.className = "wx-empty";
      empty.textContent = state.loading ? "Loading discovered workflows..." : "No published workflows found in the exchange catalog.";
      discoverList.appendChild(empty);
    } else {
      discoveredItems.forEach((item) => discoverList.appendChild(renderDiscoverCard(item, ctx, host, container)));
    }
    discoverSection.appendChild(discoverList);
    sections.appendChild(discoverSection);
  } else if (state.activeTab === "settings") {
    const settingsSection = document.createElement("section");
    settingsSection.className = "wx-section";
    const settingsHead = document.createElement("div");
    settingsHead.className = "wx-section-head";
    const settingsHeadText = document.createElement("div");
    const settingsTitle = document.createElement("div");
    settingsTitle.className = "wx-section-title";
    settingsTitle.textContent = "Exchange Settings";
    const settingsSub = document.createElement("div");
    settingsSub.className = "wx-section-sub";
    settingsSub.textContent = "Policy, relay, sync, code safety, and exclusion settings for Agent Workflow Exchange.";
    settingsHeadText.appendChild(settingsTitle);
    settingsHeadText.appendChild(settingsSub);
    settingsHead.appendChild(settingsHeadText);
    settingsSection.appendChild(settingsHead);
    const settingsGrid = document.createElement("div");
    settingsGrid.className = "wx-setting-grid";
    const schemaRows = Array.isArray(state.settingsSchema) ? state.settingsSchema : [];
    schemaRows.forEach((field) => settingsGrid.appendChild(renderSettingsField(field, state)));
    settingsSection.appendChild(settingsGrid);
    const saveBtn = button(state.savingSettings ? "Saving..." : "Save Exchange Settings", "primary", () => {
      const nextSettings = {};
      settingsGrid.querySelectorAll("[data-setting-key]").forEach((node) => {
        const key = String(node.dataset.settingKey || "").trim();
        const type = String(node.dataset.settingType || "string").trim();
        if (!key) return;
        if (type === "bool") {
          nextSettings[key] = !!node.checked;
        } else if (type === "number") {
          nextSettings[key] = Number(node.value || 0);
        } else if (type === "list") {
          nextSettings[key] = textToList(node.value || "");
        } else {
          nextSettings[key] = String(node.value || "");
        }
      });
      void saveExchangeSettings(ctx, host, container, nextSettings);
    });
    saveBtn.disabled = !!state.savingSettings;
    settingsSection.appendChild(saveBtn);
    sections.appendChild(settingsSection);
  }

  root.appendChild(sections);
  container.appendChild(root);
}

const plugin = {
  id: meta.plugin_id,
  name: meta.name,
  kind: meta.kind,
  description: meta.description,
  meta,
  register(host) {
    host.addPanelTab({
      id: meta.plugin_id,
      title: "Agent Workflow Exchange",
      render: (container, ctx) => {
        renderPanel(container, ctx, host);
        void loadExchangeState(ctx, host, container);
        if (!sessionChangeHandler) {
          sessionChangeHandler = () => {
            try {
              renderPanel(container, ctx, host);
              void loadExchangeState(ctx, host, container);
            } catch {}
          };
          document.addEventListener(SESSION_CHANGE_EVENT, sessionChangeHandler);
        }
      },
    });
  },
  dispose() {
    if (sessionChangeHandler) {
      document.removeEventListener(SESSION_CHANGE_EVENT, sessionChangeHandler);
      sessionChangeHandler = null;
    }
  },
};

export default plugin;
