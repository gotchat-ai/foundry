const meta = {
  plugin_id: "agent_workflow",
  name: "Agent Workflow",
  kind: "ui",
  description: "Workflow feedback and learning panel.",
  has_notebook_tab: true,
};

const STYLE_ID = "agent-workflow-ui-style";

function ensureStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
.aw-root { display: flex; flex-direction: column; gap: 12px; padding: 10px; }
.aw-card { border: 1px solid var(--border); border-radius: 12px; background: rgba(var(--panel-rgb), 0.92); padding: 12px; display: flex; flex-direction: column; gap: 10px; }
.aw-title { font-size: 14px; font-weight: 700; }
.aw-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.aw-col { display: flex; flex-direction: column; gap: 6px; }
.aw-card label { font-size: 12px; color: var(--ui-muted); }
.aw-card input, .aw-card textarea, .aw-card select {
  width: 100%; border: 1px solid var(--border); border-radius: 8px; background: var(--ui-control-bg); color: var(--ui-ink); padding: 7px 8px; font-size: 12px;
}
.aw-card textarea { min-height: 80px; resize: vertical; }
.aw-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.aw-btn { border: 1px solid var(--border); border-radius: 8px; background: var(--ui-control-bg); color: var(--ui-ink); cursor: pointer; padding: 7px 10px; font-size: 12px; }
.aw-btn.primary { background: var(--accent-warm); color: #1a1306; border-color: transparent; font-weight: 700; }
.aw-status { font-size: 12px; color: var(--ui-muted); min-height: 16px; }
.aw-list { display: flex; flex-direction: column; gap: 8px; max-height: 46vh; overflow: auto; }
.aw-item { border: 1px solid var(--border); border-radius: 10px; padding: 8px; background: var(--ui-popover-item-bg); display: flex; flex-direction: column; gap: 5px; }
.aw-item-top { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; }
.aw-step-card { border: 1px solid var(--border); border-radius: 10px; padding: 8px; background: var(--ui-popover-item-bg); display: flex; flex-direction: column; gap: 6px; }
.aw-step-title { font-size: 12px; font-weight: 700; }
.aw-step-line { font-size: 12px; }
.aw-step-actions { font-size: 12px; margin-left: 12px; }
.aw-mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }
.aw-item-actions { display: flex; gap: 6px; }
.aw-tabs { display: flex; gap: 8px; flex-wrap: wrap; }
.aw-tab-btn { border: 1px solid var(--border); border-radius: 999px; background: var(--ui-control-bg); color: var(--ui-ink); cursor: pointer; padding: 6px 10px; font-size: 12px; }
.aw-tab-btn.active { background: var(--accent-warm); color: #1a1306; border-color: transparent; font-weight: 700; }
.aw-tab-pane { display: none; }
.aw-tab-pane.active { display: flex; flex-direction: column; gap: 12px; }
.aw-tab-pane { max-height: calc(100vh - 180px); overflow-y: auto; padding-right: 4px; }
.aw-modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.45); z-index: 9999; display: flex; align-items: center; justify-content: center; }
.aw-modal { width: min(760px, 92vw); max-height: 82vh; overflow: hidden; border: 1px solid var(--border); border-radius: 12px; background: rgba(var(--panel-rgb), 0.98); display: flex; flex-direction: column; gap: 8px; padding: 10px; }
.aw-modal-list { overflow: auto; border: 1px solid var(--border); border-radius: 8px; padding: 6px; display: flex; flex-direction: column; gap: 6px; max-height: 58vh; }
.aw-modal-item { border: 1px solid var(--border); border-radius: 8px; background: var(--ui-popover-item-bg); padding: 6px 8px; cursor: pointer; font-size: 12px; }
.aw-modal-item:hover { background: var(--ui-popover-item-bg-hover); }
.aw-job-group { border: 1px solid var(--border); border-radius: 10px; background: var(--ui-popover-item-bg); overflow: hidden; }
.aw-job-group summary { list-style: none; cursor: pointer; padding: 8px 10px; font-weight: 700; font-size: 12px; display: flex; justify-content: flex-start; gap: 8px; align-items: center; }
.aw-job-title { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.aw-job-title-btn { appearance: none; border: 0; background: transparent; color: inherit; font: inherit; font-weight: inherit; padding: 0; margin: 0; min-width: 0; text-align: left; cursor: pointer; }
.aw-job-title-btn:hover { text-decoration: underline; }
.aw-job-flow-control { width: 24px; height: 24px; border-radius: 999px; border: 1px solid var(--border); background: var(--ui-control-bg); color: var(--ui-ink); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; flex: 0 0 auto; line-height: 1; }
.aw-job-flow-control:hover { background: var(--ui-popover-item-bg-hover); }
.aw-job-flow-control:disabled { opacity: 0.6; cursor: wait; }
.aw-job-steer-footer { width: 28px; height: 28px; border-radius: 999px; border: 1px solid var(--border); background: var(--ui-control-bg); color: var(--ui-ink); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; font-size: 15px; line-height: 1; }
.aw-job-steer-footer:hover { background: var(--ui-popover-item-bg-hover); }
.aw-job-steer-footer:disabled { opacity: 0.6; cursor: wait; }
.aw-icon-steer::before { content: ""; position: absolute; left: 2px; top: 6px; width: 10px; height: 2px; border-radius: 999px; background: currentColor; transform: rotate(-28deg); transform-origin: left center; }
.aw-icon-steer::after { content: ""; position: absolute; right: 1px; top: 2px; width: 6px; height: 6px; border-top: 2px solid currentColor; border-right: 2px solid currentColor; transform: rotate(18deg); border-radius: 1px; }
.aw-job-submit-status { font-size: 11px; color: var(--ui-muted); min-height: 14px; display: inline-flex; align-items: center; gap: 6px; }
.aw-job-submit-status.error { color: #b91c1c; }
.aw-job-submit-status .aw-submit-spinner { width: 12px; height: 12px; border: 2px solid color-mix(in srgb, currentColor 26%, transparent); border-top-color: currentColor; border-radius: 999px; animation: aw-spin 0.75s linear infinite; flex: 0 0 auto; }
.aw-icon { display: inline-block; position: relative; width: 14px; height: 14px; color: currentColor; }
.aw-icon-pause::before,
.aw-icon-pause::after { content: ""; position: absolute; top: 1px; bottom: 1px; width: 4px; border-radius: 2px; background: currentColor; }
.aw-icon-pause::before { left: 2px; }
.aw-icon-pause::after { right: 2px; }
.aw-icon-play::before { content: ""; position: absolute; left: 4px; top: 2px; width: 0; height: 0; border-top: 5px solid transparent; border-bottom: 5px solid transparent; border-left: 8px solid currentColor; }
.aw-icon-spinner { border: 2px solid color-mix(in srgb, currentColor 28%, transparent); border-top-color: currentColor; border-radius: 999px; animation: aw-spin 0.75s linear infinite; }
@keyframes aw-spin { to { transform: rotate(360deg); } }
.aw-job-step-stat { flex: 0 0 auto; color: var(--ui-muted); font-weight: 600; }
.aw-job-group summary::-webkit-details-marker { display: none; }
.aw-job-group .aw-job-badge { display: none; }
.aw-job-stream { max-height: 180px; overflow: auto; border-top: 1px solid var(--border); background: rgba(var(--panel-rgb), 0.6); }
.aw-job-stream pre { margin: 0; padding: 8px 10px; white-space: pre-wrap; word-break: break-word; font-size: 12px; line-height: 1.35; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }
.aw-job-interaction { border-top: 1px solid var(--border); padding: 10px; background: rgba(var(--panel-rgb), 0.86); display: flex; flex-direction: column; gap: 8px; }
.aw-job-interaction-title { font-size: 11px; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; color: var(--ui-muted); }
.aw-job-interaction-question { font-size: 13px; line-height: 1.45; }
.aw-job-interaction-actions { display: flex; flex-wrap: wrap; gap: 6px; }
.aw-job-interaction textarea { width: 100%; min-height: 74px; border: 1px solid var(--border); border-radius: 8px; background: var(--ui-control-bg); color: var(--ui-ink); padding: 7px 8px; font-size: 12px; resize: vertical; box-sizing: border-box; }
.aw-result-card { border: 1px solid var(--border); border-radius: 14px; background: rgba(var(--panel-rgb), 0.92); overflow: hidden; }
.aw-result-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 10px; border-bottom: 1px solid var(--border); color: var(--ui-muted); font-size: 11px; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; }
.aw-result-body { padding: 10px 12px; line-height: 1.5; }
.aw-result-body > :first-child { margin-top: 0; }
.aw-result-body > :last-child { margin-bottom: 0; }
.aw-result-files { display: flex; flex-direction: column; gap: 8px; }
.aw-result-file-link { display: flex; align-items: center; justify-content: space-between; gap: 10px; border: 1px solid var(--border); border-radius: 10px; padding: 9px 10px; background: var(--ui-popover-item-bg); color: var(--ui-ink); text-decoration: none; }
.aw-result-file-link:hover { background: var(--ui-popover-item-bg-hover); }
.aw-result-file-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 700; }
.aw-result-file-meta { flex: 0 0 auto; color: var(--ui-muted); font-size: 11px; }
.aw-result-details { border-top: 1px solid var(--border); padding: 8px 12px 10px; color: var(--ui-muted); font-size: 12px; }
.aw-result-details summary { cursor: pointer; font-weight: 700; }
.aw-result-details dl { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 6px 10px; margin: 8px 0 0; }
.aw-result-details dt { font-weight: 700; color: var(--ui-muted); }
.aw-result-details dd { margin: 0; min-width: 0; word-break: break-word; }
@media (max-width: 900px) {
  .aw-row { grid-template-columns: 1fr; }
  .aw-result-details dl { grid-template-columns: 1fr; }
}
`;
  document.head.appendChild(style);
}

const agentFlowRunStates = new Map();
const steerDraftByRunId = new Map();
const steerOpenByRunId = new Map();
const clarifyDraftByInteractionId = new Map();
let lastAgentWorkflowInputFocus = null;
const agentFlowStatusRefreshes = new Set();
const agentFlowStatusRefreshCooldowns = new Map();

function agentFlowControlIcon(paused, pending) {
  if (pending) return '<span class="aw-icon aw-icon-spinner" aria-hidden="true"></span>';
  return paused
    ? '<span class="aw-icon aw-icon-play" aria-hidden="true"></span>'
    : '<span class="aw-icon aw-icon-pause" aria-hidden="true"></span>';
}

function parseCsv(v) {
  return String(v || "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

function isAgentJobAssistantMessage(msg) {
  if (!msg || String(msg.role || "").toLowerCase() !== "assistant") return false;
  if (isFlowTokenStreamMessage(msg)) return true;
  if (/_stream$/i.test(String(msg.msg_id || ""))) return true;
  const txt = String(msg.content || "").trim();
  if (!txt) return false;
  return txt.startsWith("[agent_workflow]") || txt.startsWith("[agent_flow]") || txt.startsWith("Flow step ");
}

function isFlowTokenStreamMessage(msg) {
  const meta = msg && typeof msg.meta === "object" ? msg.meta : null;
  return Boolean(meta && (meta.flow_stream_tokens || meta.flow_stream || meta.flow_run_id));
}

function isFlowStreamLikeMessage(msg) {
  return isFlowTokenStreamMessage(msg) || /_stream$/i.test(String(msg?.msg_id || ""));
}

function getFlowRunId(msg) {
  const meta = msg && typeof msg.meta === "object" ? msg.meta : null;
  const fromMeta = String(meta?.flow_run_id || meta?.flowRunId || "").trim();
  if (fromMeta) return fromMeta;
  const m = String(msg?.msg_id || "").match(/^(.+)_stream$/i);
  if (m) return String(m[1] || "").trim();
  const txt = String(msg?.content || "");
  const line = txt.match(/^\[agent_flow\]\s+run_id:\s*([^\s]+)\s*$/m);
  return line ? String(line[1] || "").trim() : "";
}

function agentFlowRunStateKey(pid, sid, runId) {
  const rid = String(runId || "").trim();
  if (!rid) return "";
  return `${String(pid || "").trim()}::${String(sid || "").trim()}::${rid}`;
}

function rememberAgentFlowRunState(data) {
  if (!data || typeof data !== "object") return;
  const runId = String(data.run_id || data.runId || "").trim();
  const pid = String(data.pid || "").trim();
  const sid = String(data.sid || "").trim();
  const key = agentFlowRunStateKey(pid, sid, runId);
  if (!key) return;
  const status = String(data.status || "");
  const statusPaused = /^Paused\b/i.test(status.trim());
  const statusPausing = /^Pausing\b/i.test(status.trim());
  const paused = statusPaused || Boolean(data.paused);
  const pauseRequested = !paused && (statusPausing || Boolean(data.pause_requested || data.pauseRequested));
  agentFlowRunStates.set(key, {
    pid,
    sid,
    runId,
    running: Boolean(data.running),
    paused,
    pauseRequested,
    interaction: data.interaction && typeof data.interaction === "object" ? { ...data.interaction } : null,
    steers: Array.isArray(data.steers) ? data.steers.slice() : [],
    status,
    updatedAt: Date.now(),
  });
}

function getRememberedAgentFlowRunState(pid, sid, runId) {
  return agentFlowRunStates.get(agentFlowRunStateKey(pid, sid, runId)) || null;
}

function flowTextLooksTerminal(text) {
  return /\b(final result message emitted|Completed|Canceled|Error:|workflow_complete)\b/i.test(String(text || ""));
}

function flowTextLooksPaused(text) {
  return /\b(paused|pausing after current node)\b/i.test(String(text || ""));
}

async function refreshAgentFlowRunStatus(ctx, pid, sid, runId) {
  const key = agentFlowRunStateKey(pid, sid, runId);
  if (!ctx?.apiJson || !key || agentFlowStatusRefreshes.has(key)) return;
  const cooldownUntil = Number(agentFlowStatusRefreshCooldowns.get(key) || 0);
  if (cooldownUntil > Date.now()) return;
  agentFlowStatusRefreshes.add(key);
  try {
    const res = await ctx.apiJson(
      `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/agent_flow/status?run_id=${encodeURIComponent(runId)}`,
      {
        headers: {
          "X-Project-Id": pid,
          "X-Session-Id": sid,
          "X-Gui-Enabled-Plugins": "collab_chat,agent_flow,agent_workflow",
        },
      }
    );
    agentFlowStatusRefreshCooldowns.delete(key);
    if (res?.state) {
      rememberAgentFlowRunState({ ...res.state, pid, sid, run_id: runId });
      updateVisibleAgentFlowControls({ ...res.state, pid, sid, run_id: runId });
    }
  } catch (err) {
    agentFlowStatusRefreshCooldowns.set(key, Date.now() + 10000);
    ctx.log?.(`[agent_workflow] agent flow status refresh failed: ${err?.message || err}`, "warn");
  } finally {
    setTimeout(() => agentFlowStatusRefreshes.delete(key), 1200);
  }
}

function renderAgentFlowControlButton(btn, state) {
  if (!btn || !state) return;
  const status = String(state.status || "");
  const running = Boolean(state.running);
  const paused = /^Paused\b/i.test(status.trim()) || Boolean(state.paused);
  const pending = !paused && (/^Pausing\b/i.test(status.trim()) || Boolean(state.pauseRequested));
  btn.style.display = running ? "inline-flex" : "none";
  btn.innerHTML = agentFlowControlIcon(paused, pending);
  btn.title = pending ? "Pausing flow" : (paused ? "Resume flow" : "Pause flow");
  btn.setAttribute("aria-label", btn.title);
  btn.disabled = pending;
}

function updateVisibleAgentFlowControls(data) {
  if (!data || typeof data !== "object") return;
  const pid = String(data.pid || "").trim();
  const sid = String(data.sid || "").trim();
  const runId = String(data.run_id || data.runId || "").trim();
  if (!runId) return;
  const state = getRememberedAgentFlowRunState(pid, sid, runId) || {
    running: Boolean(data.running),
    paused: Boolean(data.paused),
    pauseRequested: Boolean(data.pause_requested || data.pauseRequested),
  };
  const esc = window.CSS && typeof window.CSS.escape === "function"
    ? window.CSS.escape(runId)
    : runId.replace(/["\\]/g, "\\$&");
  const selector = `.aw-job-flow-control[data-flow-run-id="${esc}"]`;
  document.querySelectorAll(selector).forEach((btn) => renderAgentFlowControlButton(btn, state));
}

async function setAgentFlowJobPaused(ctx, g, paused, btn) {
  const pid = String(g?.pid || ctx?.state?.ui?.activePid || "").trim();
  const sid = String(g?.sid || ctx?.state?.ui?.activeSid || "").trim();
  const runId = String(g?.runId || "").trim();
  if (!pid || !sid || !runId) return;
  const action = paused ? "pause" : "resume";
  if (paused) {
    rememberAgentFlowRunState({ pid, sid, run_id: runId, running: true, paused: false, pause_requested: true, status: "Pausing" });
    updateVisibleAgentFlowControls({ pid, sid, run_id: runId });
  }
  if (btn) {
    renderAgentFlowControlButton(btn, {
      running: true,
      paused: false,
      pauseRequested: paused,
    });
  }
  try {
    const res = await ctx.apiJson(
      `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/agent_flow/${action}?run_id=${encodeURIComponent(runId)}`,
      {
        method: "POST",
        headers: {
          "X-Project-Id": pid,
          "X-Session-Id": sid,
          "X-Gui-Enabled-Plugins": "collab_chat,agent_flow,agent_workflow",
        },
      }
    );
    if (res?.state) rememberAgentFlowRunState({ ...res.state, pid, sid, run_id: runId });
    if (btn) {
      const nextState = getRememberedAgentFlowRunState(pid, sid, runId) || {};
      renderAgentFlowControlButton(btn, nextState);
    }
  } catch (err) {
    ctx.log?.(`[agent_workflow] agent flow ${action} failed: ${err?.message || err}`, "warn");
  } finally {
    if (btn) {
      const nextState = getRememberedAgentFlowRunState(pid, sid, runId) || {};
      renderAgentFlowControlButton(btn, nextState);
    }
  }
}

async function submitAgentFlowInteraction(ctx, g, payload) {
  const pid = String(g?.pid || ctx?.state?.ui?.activePid || "").trim();
  const sid = String(g?.sid || ctx?.state?.ui?.activeSid || "").trim();
  const runId = String(g?.runId || "").trim();
  if (!pid || !sid || !runId) return null;
  const res = await ctx.apiJson(
    `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/agent_flow/interaction`,
    {
      method: "POST",
      headers: {
        "X-Project-Id": pid,
        "X-Session-Id": sid,
        "X-Gui-Enabled-Plugins": "collab_chat,agent_flow,agent_workflow",
      },
      body: { ...(payload || {}), run_id: runId },
    }
  );
  if (res?.state) rememberAgentFlowRunState({ ...res.state, pid, sid, run_id: runId });
  return res;
}

async function submitAgentFlowSteer(ctx, g, message, target = "next") {
  const pid = String(g?.pid || ctx?.state?.ui?.activePid || "").trim();
  const sid = String(g?.sid || ctx?.state?.ui?.activeSid || "").trim();
  const runId = String(g?.runId || "").trim();
  if (!pid || !sid || !runId) return null;
  const res = await ctx.apiJson(
    `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/agent_flow/steer`,
    {
      method: "POST",
      headers: {
        "X-Project-Id": pid,
        "X-Session-Id": sid,
        "X-Gui-Enabled-Plugins": "collab_chat,agent_flow,agent_workflow",
      },
      body: { run_id: runId, message, target },
    }
  );
  if (res?.state) rememberAgentFlowRunState({ ...res.state, pid, sid, run_id: runId });
  return res;
}

function isResultTextMessage(msg) {
  if (!msg || String(msg.role || "").toLowerCase() !== "assistant") return false;
  const meta = msg && typeof msg.meta === "object" ? msg.meta : null;
  if (!meta || !meta.flow_result) return false;
  return String(meta.flow_result_mode || "").trim().toLowerCase() === "text";
}

function isResultFileMessage(msg) {
  if (!msg || String(msg.role || "").toLowerCase() !== "assistant") return false;
  const meta = msg && typeof msg.meta === "object" ? msg.meta : null;
  if (!meta || !meta.flow_result) return false;
  const mode = String(meta.flow_result_mode || "").trim().toLowerCase();
  return mode === "files" || mode === "file" || mode === "zip";
}

function normalizeWorkflowUploadUrl(raw, ctx) {
  let src = String(raw || "").trim();
  if (!src) return "";
  const normalized = src.replace(/\\/g, "/");
  const uploadIndex = normalized.indexOf("/uploads/");
  if (uploadIndex >= 0) {
    const rel = normalized.slice(uploadIndex);
    const base = String(ctx?.state?.remote?.serverUrl || "").trim().replace(/\/+$/, "");
    if (base && !base.startsWith("file:")) return `${base}${rel}`;
    return rel;
  }
  if (/^https?:\/\//i.test(normalized) || /^data:/i.test(normalized)) return normalized;
  const base = String(ctx?.state?.remote?.serverUrl || window?.location?.origin || "").trim().replace(/\/+$/, "");
  if (!base) return normalized;
  return normalized.startsWith("/") ? `${base}${normalized}` : `${base}/${normalized}`;
}

function collectWorkflowResultFiles(msg) {
  const meta = msg && typeof msg.meta === "object" ? msg.meta : {};
  const out = [];
  const add = (item) => {
    if (!item) return;
    if (typeof item === "string") {
      out.push({ name: item.split(/[\\/]/).pop() || item, download_url: item });
      return;
    }
    if (typeof item !== "object") return;
    const url = item.download_url || item.relative_download_url || item.url || item.href || item.path || "";
    if (!url) return;
    out.push({
      name: item.name || item.filename || item.staged_name || String(url).split(/[\\/]/).pop() || "Download",
      download_url: url,
      size_bytes: item.size_bytes || item.size || 0,
      file_count: item.file_count || 0,
    });
  };
  // Prefer files staged by result.files/result.zip. Raw file paths are kept in
  // metadata for traceability, but they are not browser-download URLs.
  const hasStagedFiles = Array.isArray(meta.staged_files) && meta.staged_files.length > 0;
  const sources = hasStagedFiles
    ? [meta.staged_files, meta.zip ? [meta.zip] : null]
    : [
        meta.files,
        meta.file,
        meta.zip ? [meta.zip] : null,
      ];
  sources.forEach((src) => {
    if (Array.isArray(src)) src.forEach(add);
    else add(src);
  });
  const seen = new Set();
  return out.filter((item) => {
    const key = String(item.download_url || item.name || "");
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function formatBytes(n) {
  const value = Number(n || 0);
  if (!Number.isFinite(value) || value <= 0) return "";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function parseKeyedResultText(content) {
  const txt = String(content || "").trim();
  if (!txt) return { answer: "", details: {} };
  const keyed = {};
  const lines = txt.split(/\r?\n/);
  let current = "";
  for (const raw of lines) {
    const line = String(raw || "");
    const m = line.match(/^([A-Za-z_][A-Za-z0-9_ -]{0,40}):\s*(.*)$/);
    if (m) {
      current = String(m[1] || "").trim().toLowerCase().replace(/\s+/g, "_");
      keyed[current] = String(m[2] || "").trim();
      continue;
    }
    if (current) {
      const existing = keyed[current] ? `${keyed[current]}\n` : "";
      keyed[current] = `${existing}${line}`.trim();
    }
  }
  const looksStructured = Object.keys(keyed).some((k) =>
    ["role", "plan", "analysis", "response", "did", "result", "answer", "text", "handoff", "skills_invoked", "skill_results"].includes(k)
  );
  if (!looksStructured) return { answer: txt, details: {} };
  const answer =
    keyed.result ||
    keyed.answer ||
    keyed.final_answer ||
    keyed.text ||
    keyed.response ||
    keyed.did ||
    keyed.handoff ||
    txt;
  const details = {};
  for (const key of ["plan", "analysis", "did", "handoff", "skills_invoked"]) {
    if (keyed[key] && keyed[key] !== answer) details[key] = keyed[key];
  }
  return { answer: String(answer || "").trim(), details };
}

function renderResultTextMessage(msg, ctx) {
  if (!isResultTextMessage(msg)) return null;
  ensureStyles();
  const msgId = String(msg.msg_id || "");
  const parsed = parseKeyedResultText(msg.content);
  const answer = parsed.answer || String(msg.content || "").trim() || "Result ready.";
  const wrap = document.createElement("div");
  wrap.className = "message assistant";
  wrap.dataset.msgId = msgId;
  if (msg.author) {
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = msg.author;
    wrap.appendChild(meta);
  }
  const bubble = document.createElement("div");
  bubble.className = "bubble stack";
  const card = document.createElement("div");
  card.className = "aw-result-card";
  const head = document.createElement("div");
  head.className = "aw-result-head";
  const title = document.createElement("span");
  title.textContent = "Workflow Result";
  const mode = document.createElement("span");
  mode.textContent = "Text";
  head.appendChild(title);
  head.appendChild(mode);
  card.appendChild(head);
  const body = document.createElement("div");
  body.className = "aw-result-body";
  const renderMarkdown = ctx?.renderMarkdown || (typeof window !== "undefined" ? window.renderMarkdown : null);
  body.innerHTML = typeof renderMarkdown === "function" ? renderMarkdown(answer) : answer;
  card.appendChild(body);
  const details = parsed.details || {};
  const detailKeys = Object.keys(details).filter((k) => String(details[k] || "").trim());
  if (detailKeys.length) {
    const detailNode = document.createElement("details");
    detailNode.className = "aw-result-details";
    const summary = document.createElement("summary");
    summary.textContent = "Workflow details";
    detailNode.appendChild(summary);
    const dl = document.createElement("dl");
    detailKeys.forEach((key) => {
      const dt = document.createElement("dt");
      dt.textContent = key.replace(/_/g, " ");
      const dd = document.createElement("dd");
      dd.textContent = String(details[key] || "").trim();
      dl.appendChild(dt);
      dl.appendChild(dd);
    });
    detailNode.appendChild(dl);
    card.appendChild(detailNode);
  }
  bubble.appendChild(card);
  wrap.appendChild(bubble);
  return wrap;
}

function renderResultFileMessage(msg, ctx) {
  if (!isResultFileMessage(msg)) return null;
  ensureStyles();
  const meta = msg && typeof msg.meta === "object" ? msg.meta : {};
  const mode = String(meta.flow_result_mode || "").trim().toLowerCase();
  const files = collectWorkflowResultFiles(msg);
  if (!files.length) return null;
  const wrap = document.createElement("div");
  wrap.className = "message assistant";
  wrap.dataset.msgId = String(msg.msg_id || "");
  if (msg.author) {
    const metaNode = document.createElement("div");
    metaNode.className = "meta";
    metaNode.textContent = msg.author;
    wrap.appendChild(metaNode);
  }
  const bubble = document.createElement("div");
  bubble.className = "bubble stack";
  const card = document.createElement("div");
  card.className = "aw-result-card";
  const head = document.createElement("div");
  head.className = "aw-result-head";
  const title = document.createElement("span");
  title.textContent = "Workflow Result";
  const tag = document.createElement("span");
  tag.textContent = mode === "zip" ? "Zip" : "Files";
  head.appendChild(title);
  head.appendChild(tag);
  card.appendChild(head);
  const body = document.createElement("div");
  body.className = "aw-result-body aw-result-files";
  files.forEach((item) => {
    const a = document.createElement("a");
    a.className = "aw-result-file-link";
    a.href = normalizeWorkflowUploadUrl(item.download_url, ctx);
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.download = String(item.name || "").trim();
    const name = document.createElement("span");
    name.className = "aw-result-file-name";
    name.textContent = String(item.name || "Download");
    const info = document.createElement("span");
    info.className = "aw-result-file-meta";
    const size = formatBytes(item.size_bytes);
    info.textContent = item.file_count ? `${item.file_count} file${item.file_count === 1 ? "" : "s"}` : (size || "Download");
    a.appendChild(name);
    a.appendChild(info);
    body.appendChild(a);
  });
  card.appendChild(body);
  bubble.appendChild(card);
  wrap.appendChild(bubble);
  return wrap;
}

function isAgentWorkflowRunStartMessage(msg) {
  if (!msg || String(msg.role || "").toLowerCase() !== "assistant") return false;
  const txt = String(msg.content || "").trim();
  return txt.startsWith("[agent_workflow] Starting automated workflow run...");
}

function getSessionMessages(ctx) {
  const sid = String(ctx?.state?.ui?.activeSid || "");
  const session = sid ? ctx?.state?.sessions?.[sid] : null;
  return Array.isArray(session?.messages) ? session.messages : [];
}

function getAgentJobGroup(ctx, msg) {
  const all = getSessionMessages(ctx);
  const idx = all.findIndex((m) => String(m?.msg_id || "") === String(msg?.msg_id || ""));
  if (idx < 0) return null;
  if (!isAgentJobAssistantMessage(all[idx])) return null;
  if (isFlowStreamLikeMessage(all[idx])) {
    const selfText = String(all[idx]?.content || "").trim();
    const selfRunning = Boolean(all[idx]?.streaming);
    const runId = getFlowRunId(all[idx]);
    const pid = String(all[idx]?.pid || ctx?.state?.ui?.activePid || "").trim();
    const sid = String(all[idx]?.sid || ctx?.state?.ui?.activeSid || "").trim();
    const remembered = getRememberedAgentFlowRunState(pid, sid, runId);
    const inferredPaused = flowTextLooksPaused(selfText);
    const inferredRunning = Boolean(runId) && !flowTextLooksTerminal(selfText);
    if (!remembered && runId && pid && sid && inferredRunning) void refreshAgentFlowRunStatus(ctx, pid, sid, runId);
    const hdr = parseAgentJobsHeader(selfText);
    if (!hdr.workflowName) hdr.workflowName = getAgentJobsWorkflowNameFromState(ctx);
    return {
      startMsgId: String(all[idx]?.msg_id || ""),
      pid,
      sid,
      runId,
      count: 1,
      text: selfText,
      running: remembered ? Boolean(remembered.running) : (selfRunning || inferredRunning),
      paused: remembered ? Boolean(remembered.paused) : inferredPaused,
      pauseRequested: remembered ? Boolean(remembered.pauseRequested) : (!inferredPaused && /\bpausing\b/i.test(selfText)),
      interaction: remembered?.interaction || null,
      workflowName: hdr.workflowName,
      currentNode: hdr.currentNode,
      totalNodes: hdr.totalNodes,
    };
  }
  let start = idx;
  while (start > 0) {
    const prev = all[start - 1];
    if (!isAgentJobAssistantMessage(prev)) break;
    if (isAgentWorkflowRunStartMessage(prev)) {
      start -= 1;
      break;
    }
    start -= 1;
    if (isAgentWorkflowRunStartMessage(all[start])) break;
  }
  let end = idx;
  while (end + 1 < all.length) {
    const nxt = all[end + 1];
    if (!isAgentJobAssistantMessage(nxt)) break;
    if (isAgentWorkflowRunStartMessage(nxt)) break;
    end += 1;
  }
  const msgs = all.slice(start, end + 1);
  const lines = msgs.map((m) => String(m?.content || "").trim()).filter(Boolean);
  const combined = lines.join("\n");
  const hasStreaming = msgs.some((m) => Boolean(m?.streaming));
  const hasCompleteMarker = /\bworkflow_complete\b|\bWorkflow (executed|failed|paused|finished)\b|completion_gate:/i.test(combined);
  const running = hasStreaming || !hasCompleteMarker;
  const hdr = parseAgentJobsHeader(combined);
  if (!hdr.workflowName) hdr.workflowName = getAgentJobsWorkflowNameFromState(ctx);
  const firstFlowMsg = msgs.find((m) => isFlowStreamLikeMessage(m));
  const runId = getFlowRunId(firstFlowMsg || all[start]);
  const pid = String(firstFlowMsg?.pid || all[start]?.pid || ctx?.state?.ui?.activePid || "").trim();
  const sid = String(firstFlowMsg?.sid || all[start]?.sid || ctx?.state?.ui?.activeSid || "").trim();
  const remembered = getRememberedAgentFlowRunState(pid, sid, runId);
  const inferredPaused = flowTextLooksPaused(combined);
  const inferredRunning = Boolean(runId) && !flowTextLooksTerminal(combined);
  if (!remembered && runId && pid && sid && inferredRunning) void refreshAgentFlowRunStatus(ctx, pid, sid, runId);
  return {
    startMsgId: String(all[start]?.msg_id || ""),
    pid,
    sid,
    runId,
    count: msgs.length,
    text: combined,
    running: remembered ? Boolean(remembered.running) : (running || inferredRunning),
    paused: remembered ? Boolean(remembered.paused) : inferredPaused,
    pauseRequested: remembered ? Boolean(remembered.pauseRequested) : (!inferredPaused && /\bpausing\b/i.test(combined)),
    interaction: remembered?.interaction || null,
    workflowName: hdr.workflowName,
    currentNode: hdr.currentNode,
    totalNodes: hdr.totalNodes,
  };
}

function moveMatchingFlowResultsAfterJob(ctx, jobMsg, jobNode) {
  const runId = getFlowRunId(jobMsg);
  if (!runId || !jobNode) return;
  const messages = getSessionMessages(ctx);
  const resultIds = messages
    .filter((row) => {
      const meta = row && typeof row.meta === "object" ? row.meta : null;
      if (!meta || !meta.flow_result) return false;
      return String(meta.flow_result_for_run_id || meta.flow_run_id || "").trim() === runId;
    })
    .map((row) => String(row?.msg_id || "").trim())
    .filter(Boolean);
  if (!resultIds.length) return;
  const repair = () => {
    const parent = jobNode.parentElement;
    if (!parent) return;
    let anchor = jobNode;
    resultIds.forEach((id) => {
      let node = null;
      try {
        node = document.querySelector(`.message.assistant[data-msg-id="${id}"]`);
      } catch (_err) {
        node = null;
      }
      if (!node || node === anchor) return;
      if (node.previousElementSibling !== anchor) {
        parent.insertBefore(node, anchor.nextSibling);
      }
      anchor = node;
    });
  };
  requestAnimationFrame(() => {
    repair();
    requestAnimationFrame(repair);
  });
}

function parseAgentJobsHeader(content) {
  const txt = String(content || "");
  let workflowName = "";
  const fam = txt.match(/^\[agent_workflow\]\s+workflow_start:\s+id=.*?\bfamily=([^\s]+)\s*$/m);
  if (fam && fam[1]) workflowName = String(fam[1]).trim();
  if (!workflowName) {
    const af = txt.match(/^\[agent_flow\]\s+flow_name:\s*([^\s]+)\s*$/m);
    if (af && af[1]) workflowName = String(af[1]).trim();
  }
  const stepRe = /^Flow step\s+(\d+)\s*\/\s*(\d+):/gm;
  let currentNode = 0;
  let totalNodes = 0;
  let m = null;
  while ((m = stepRe.exec(txt)) !== null) {
    currentNode = Number(m[1] || 0);
    totalNodes = Number(m[2] || 0);
  }
  return { workflowName, currentNode, totalNodes };
}

function getAgentJobsWorkflowNameFromState(ctx) {
  const sid = String(ctx?.state?.ui?.activeSid || "").trim();
  if (!sid) return "";
  const routerState = ctx?.state?.router?.settings?.[sid];
  const af = routerState?.agent_flow;
  if (!af || typeof af !== "object") return "";
  const active = String(af.agent_flow_active_flow || "").trim();
  if (active && active !== "__none__") return active;
  return String(af.agent_flow_default_flow || "").trim();
}

function openAgentFlowDesignerForWorkflow(ctx, workflowName) {
  const flowName = String(workflowName || "").trim();
  const sid = String(ctx?.state?.ui?.activeSid || "").trim();
  if (!flowName || !sid) return;
  ctx.state = ctx.state || {};
  ctx.state.router = ctx.state.router || {};
  ctx.state.router.settings = ctx.state.router.settings || {};
  const routerState = ctx.state.router.settings[sid] && typeof ctx.state.router.settings[sid] === "object"
    ? ctx.state.router.settings[sid]
    : {};
  const af = routerState.agent_flow && typeof routerState.agent_flow === "object"
    ? routerState.agent_flow
    : {};
  routerState.agent_flow = { ...af, agent_flow_active_flow: flowName };
  ctx.state.router.settings[sid] = routerState;
  ctx.saveState?.();
  ctx.openPluginPanel?.("agent_flow", { openModal: true });
}

function agentJobsPreRenderer(msg, ctx) {
  if (!isAgentJobAssistantMessage(msg)) return msg;
  if (isFlowStreamLikeMessage(msg)) return msg;
  const g = getAgentJobGroup(ctx, msg);
  if (!g) return msg;
  if (String(msg?.msg_id || "") !== g.startMsgId) return { skip: true };
  return msg;
}

function renderAgentFlowInteraction(box, ctx, g) {
  if (!box) return;
  const steerKey = String(g?.runId || g?.startMsgId || "").trim();
  if (steerKey && steerOpenByRunId.get(steerKey)) box.dataset.awSteerOpen = "true";
  const interaction = g?.interaction && typeof g.interaction === "object" ? g.interaction : null;
  const hasPrompt = interaction && String(interaction.status || "pending") === "pending";
  const steerOpen = box.dataset.awSteerOpen === "true";
  const type = hasPrompt ? String(interaction.type || "approval").trim().toLowerCase() : "";
  const interactionId = hasPrompt ? String(interaction.id || "").trim() : "";
  const question = hasPrompt ? String(interaction.question || "Continue workflow?") : "";
  const signature = JSON.stringify({
    prompt: Boolean(hasPrompt),
    type,
    interactionId,
    question,
    steerOpen,
    steerKey,
  });
  const existingPanel = box.querySelector(".aw-job-interaction");
  const active = document.activeElement;
  const activeInsidePanel = Boolean(existingPanel && active && existingPanel.contains(active));
  const activeInputKind = activeInsidePanel ? String(active?.dataset?.awInputKind || "") : "";
  const activeInputScope = activeInsidePanel ? String(active?.dataset?.awInputScope || "") : "";
  const activeSelectionStart = activeInsidePanel && typeof active?.selectionStart === "number" ? active.selectionStart : null;
  const activeSelectionEnd = activeInsidePanel && typeof active?.selectionEnd === "number" ? active.selectionEnd : null;
  if (existingPanel && activeInsidePanel && existingPanel.dataset.awInteractionSignature === signature) {
    return;
  }
  box.querySelectorAll(".aw-job-interaction").forEach((node) => node.remove());
  if (!hasPrompt && !steerOpen) return;
  const panel = document.createElement("div");
  panel.className = "aw-job-interaction";
  panel.dataset.awInteractionSignature = signature;
  const setStatus = (node, text, isError = false, pending = false) => {
    if (!node) return;
    node.innerHTML = "";
    if (pending) {
      const spinner = document.createElement("span");
      spinner.className = "aw-submit-spinner";
      spinner.setAttribute("aria-hidden", "true");
      node.appendChild(spinner);
    }
    const label = document.createElement("span");
    label.textContent = String(text || "");
    node.appendChild(label);
    node.classList.toggle("error", Boolean(isError));
  };
  if (hasPrompt) {
    const title = document.createElement("div");
    title.className = "aw-job-interaction-title";
    title.textContent = type === "clarify" ? "Clarification Needed" : "Approval Needed";
    panel.appendChild(title);
    const question = document.createElement("div");
    question.className = "aw-job-interaction-question";
    question.textContent = String(interaction.question || "Continue workflow?");
    panel.appendChild(question);
    const actions = document.createElement("div");
    actions.className = "aw-job-interaction-actions";
    const status = document.createElement("div");
    status.className = "aw-job-submit-status";
    if (type === "clarify") {
      const input = document.createElement("textarea");
      input.dataset.awInputKind = "clarify";
      input.placeholder = "Add clarification for the workflow...";
      const clarifyKey = String(interaction.id || g?.runId || g?.startMsgId || "").trim();
      input.dataset.awInputScope = clarifyKey ? `clarify:${clarifyKey}` : "clarify";
      const rememberClarifyFocus = () => {
        lastAgentWorkflowInputFocus = {
          kind: "clarify",
          scope: input.dataset.awInputScope,
          start: typeof input.selectionStart === "number" ? input.selectionStart : null,
          end: typeof input.selectionEnd === "number" ? input.selectionEnd : null,
          ts: Date.now(),
        };
      };
      if (clarifyKey) input.value = String(clarifyDraftByInteractionId.get(clarifyKey) || "");
      input.addEventListener("focus", rememberClarifyFocus);
      input.addEventListener("select", rememberClarifyFocus);
      input.addEventListener("input", () => {
        if (!clarifyKey) return;
        clarifyDraftByInteractionId.set(clarifyKey, String(input.value || ""));
        rememberClarifyFocus();
      });
      panel.appendChild(input);
      const submit = document.createElement("button");
      submit.className = "aw-btn primary";
      submit.textContent = "Submit";
      submit.addEventListener("click", async (event) => {
        event.preventDefault();
        event.stopPropagation();
        const text = String(input.value || "").trim();
        if (!text) return;
        submit.disabled = true;
        setStatus(status, "Submitting...", false, true);
        try {
          await submitAgentFlowInteraction(ctx, g, { interaction_id: interaction.id, text, action: "clarify" });
          if (clarifyKey) clarifyDraftByInteractionId.delete(clarifyKey);
          if (lastAgentWorkflowInputFocus?.scope === input.dataset.awInputScope) lastAgentWorkflowInputFocus = null;
          setStatus(status, "Submitted.");
          ctx.refreshTranscript?.();
        } catch (err) {
          setStatus(status, `Submit failed: ${err?.message || err}`, true);
        } finally {
          submit.disabled = false;
        }
      });
      actions.appendChild(submit);
    } else {
      ["yes", "no", "skip"].forEach((action) => {
        const btn = document.createElement("button");
        btn.className = action === "yes" ? "aw-btn primary" : "aw-btn";
        btn.textContent = action[0].toUpperCase() + action.slice(1);
        btn.addEventListener("click", async (event) => {
          event.preventDefault();
          event.stopPropagation();
          btn.disabled = true;
          const buttons = Array.from(actions.querySelectorAll("button"));
          buttons.forEach((b) => { b.disabled = true; });
          setStatus(status, `Submitting ${action}...`, false, true);
          try {
            await submitAgentFlowInteraction(ctx, g, { interaction_id: interaction.id, action });
            setStatus(status, `${action[0].toUpperCase() + action.slice(1)} submitted.`);
            ctx.refreshTranscript?.();
          } catch (err) {
            setStatus(status, `Submit failed: ${err?.message || err}`, true);
          } finally {
            buttons.forEach((b) => { b.disabled = false; });
          }
        });
        actions.appendChild(btn);
      });
    }
    panel.appendChild(actions);
    panel.appendChild(status);
  }
  if (box.dataset.awSteerOpen === "true") {
    const title = document.createElement("div");
    title.className = "aw-job-interaction-title";
    title.textContent = "Steer Workflow";
    panel.appendChild(title);
    const input = document.createElement("textarea");
    input.dataset.awInputKind = "steer";
    input.placeholder = "Add guidance for the next node or reviewer...";
    input.dataset.awInputScope = steerKey ? `steer:${steerKey}` : "steer";
    const rememberSteerFocus = () => {
      lastAgentWorkflowInputFocus = {
        kind: "steer",
        scope: input.dataset.awInputScope,
        start: typeof input.selectionStart === "number" ? input.selectionStart : null,
        end: typeof input.selectionEnd === "number" ? input.selectionEnd : null,
        ts: Date.now(),
      };
    };
    if (steerKey) input.value = String(steerDraftByRunId.get(steerKey) || "");
    input.addEventListener("focus", rememberSteerFocus);
    input.addEventListener("select", rememberSteerFocus);
    input.addEventListener("input", () => {
      if (!steerKey) return;
      steerDraftByRunId.set(steerKey, String(input.value || ""));
      rememberSteerFocus();
    });
    panel.appendChild(input);
    const actions = document.createElement("div");
    actions.className = "aw-job-interaction-actions";
    const submit = document.createElement("button");
    submit.className = "aw-btn primary";
    submit.textContent = "Send";
    const cancel = document.createElement("button");
    cancel.className = "aw-btn";
    cancel.textContent = "Cancel";
    const status = document.createElement("div");
    status.className = "aw-job-submit-status";
    submit.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      const text = String(input.value || "").trim();
      if (!text) return;
      submit.disabled = true;
      setStatus(status, "Submitting guidance...", false, true);
    try {
      await submitAgentFlowSteer(ctx, g, text, "next");
      box.dataset.awSteerOpen = "false";
      if (steerKey) {
        steerDraftByRunId.delete(steerKey);
        steerOpenByRunId.delete(steerKey);
      }
      if (lastAgentWorkflowInputFocus?.scope === input.dataset.awInputScope) lastAgentWorkflowInputFocus = null;
      setStatus(status, "Guidance submitted.");
      ctx.refreshTranscript?.();
    } catch (err) {
      setStatus(status, `Submit failed: ${err?.message || err}`, true);
    } finally {
      submit.disabled = false;
    }
    });
    cancel.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      box.dataset.awSteerOpen = "false";
      if (steerKey) {
        steerDraftByRunId.delete(steerKey);
        steerOpenByRunId.delete(steerKey);
      }
      if (lastAgentWorkflowInputFocus?.scope === input.dataset.awInputScope) lastAgentWorkflowInputFocus = null;
      ctx.refreshTranscript?.();
    });
    actions.appendChild(submit);
    actions.appendChild(cancel);
    panel.appendChild(actions);
    panel.appendChild(status);
  }
  box.appendChild(panel);
  const recentFocus = lastAgentWorkflowInputFocus && (Date.now() - Number(lastAgentWorkflowInputFocus.ts || 0)) < 10000
    ? lastAgentWorkflowInputFocus
    : null;
  const restoreKind = activeInputKind || String(recentFocus?.kind || "");
  const restoreScope = activeInputScope || String(recentFocus?.scope || "");
  const restoreStart = activeSelectionStart !== null ? activeSelectionStart : (typeof recentFocus?.start === "number" ? recentFocus.start : null);
  const restoreEnd = activeSelectionEnd !== null ? activeSelectionEnd : (typeof recentFocus?.end === "number" ? recentFocus.end : restoreStart);
  if (restoreKind) {
    const scopeSelector = restoreScope ? `[data-aw-input-scope="${restoreScope.replace(/["\\]/g, "\\$&")}"]` : "";
    const nextActive = scopeSelector
      ? panel.querySelector(scopeSelector)
      : panel.querySelector(`[data-aw-input-kind="${restoreKind}"]`);
    if (nextActive && typeof nextActive.focus === "function") {
      try {
        nextActive.focus({ preventScroll: true });
        if (restoreStart !== null && typeof nextActive.setSelectionRange === "function") {
          nextActive.setSelectionRange(restoreStart, restoreEnd ?? restoreStart);
        }
      } catch (_err) {}
    }
  }
}

function renderAgentJobsGroup(msg, ctx) {
  if (!isAgentJobAssistantMessage(msg)) return null;
  const g = getAgentJobGroup(ctx, msg);
  if (!g) return null;
  if (String(msg?.msg_id || "") !== g.startMsgId) return null;

  const msgId = String(msg.msg_id || "");
  let wrap = null;
  try {
    wrap = document.querySelector(`.message.assistant[data-msg-id="${msgId}"]`);
  } catch (_err) {
    wrap = null;
  }
  let box = null;
  let badge = null;
  let titleNode = null;
  let flowControlNode = null;
  let stepStatNode = null;
  let stream = null;
  let pre = null;
  const bindWorkflowTitleNavigation = (node) => {
    if (!node || node.dataset.awFlowNavBound === "1") return;
    node.dataset.awFlowNavBound = "1";
    node.addEventListener("click", (event) => {
      const target = event.target instanceof Element ? event.target.closest(".aw-job-title") : null;
      if (!target) return;
      const wf = String(target.getAttribute("data-workflow-name") || "").trim();
      if (!wf) return;
      event.preventDefault();
      event.stopPropagation();
      openAgentFlowDesignerForWorkflow(ctx, wf);
    });
  };
  const buildJobDom = () => {
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    box = document.createElement("details");
    box.className = "aw-job-group";
    const sum = document.createElement("summary");
    const title = document.createElement("button");
    title.type = "button";
    title.className = "aw-job-title aw-job-title-btn";
    title.textContent = "Agent Jobs";
    flowControlNode = document.createElement("button");
    flowControlNode.type = "button";
    flowControlNode.className = "aw-job-flow-control";
    stepStatNode = document.createElement("span");
    stepStatNode.className = "aw-job-step-stat";
    badge = document.createElement("span");
    badge.className = "aw-job-badge";
    sum.appendChild(title);
    sum.appendChild(flowControlNode);
    sum.appendChild(stepStatNode);
    sum.appendChild(badge);
    box.appendChild(sum);
    stream = document.createElement("div");
    stream.className = "aw-job-stream";
    pre = document.createElement("pre");
    stream.appendChild(pre);
    box.appendChild(stream);
    bubble.appendChild(box);
    return bubble;
  };
  if (!wrap) {
    wrap = document.createElement("div");
    wrap.className = "message assistant";
    wrap.dataset.msgId = msgId;
    wrap.appendChild(buildJobDom());
  } else {
    box = wrap.querySelector(".aw-job-group");
    if (!box) {
      wrap.innerHTML = "";
      wrap.appendChild(buildJobDom());
    }
    badge = wrap.querySelector(".aw-job-badge");
    titleNode = wrap.querySelector(".aw-job-title");
    flowControlNode = wrap.querySelector(".aw-job-flow-control");
    stepStatNode = wrap.querySelector(".aw-job-step-stat");
    stream = wrap.querySelector(".aw-job-stream");
    pre = wrap.querySelector(".aw-job-stream pre");
  }
  bindWorkflowTitleNavigation(wrap);
  if (!titleNode) titleNode = wrap.querySelector(".aw-job-title");
  if (!flowControlNode) flowControlNode = wrap.querySelector(".aw-job-flow-control");
  if (!flowControlNode && box) {
    const sum = box.querySelector("summary");
    if (sum) {
      flowControlNode = document.createElement("button");
      flowControlNode.type = "button";
      flowControlNode.className = "aw-job-flow-control";
      sum.insertBefore(flowControlNode, stepStatNode || badge || null);
    }
  }
  if (titleNode) {
    const wf = String(g.workflowName || "").trim();
    titleNode.classList?.add("aw-job-title-btn");
    titleNode.textContent = wf ? `Agent Jobs - ${wf}` : "Agent Jobs";
    titleNode.title = wf ? `Open ${wf} in Agent Flow` : "";
    titleNode.setAttribute("data-workflow-name", wf);
  }
  if (stepStatNode) {
    const cur = Number(g.currentNode || 0);
    const tot = Number(g.totalNodes || 0);
    stepStatNode.textContent = cur > 0 && tot > 0 ? `${cur}/${tot}` : "";
  }
  if (flowControlNode) {
    const canControl = Boolean(g.runId && g.running);
    const paused = Boolean(g.paused);
    const pending = Boolean(g.pauseRequested && !paused);
    flowControlNode.dataset.flowRunId = String(g.runId || "");
    flowControlNode.dataset.pid = String(g.pid || "");
    flowControlNode.dataset.sid = String(g.sid || "");
    flowControlNode.style.display = canControl ? "inline-flex" : "none";
    renderAgentFlowControlButton(flowControlNode, {
      running: canControl,
      paused,
      pauseRequested: pending,
    });
    flowControlNode.onclick = async (event) => {
      event.preventDefault();
      event.stopPropagation();
      await setAgentFlowJobPaused(ctx, g, !paused, flowControlNode);
    };
  }
  const transcript = getTranscriptScrollContainer(wrap);
  const transcriptShouldStick = shouldStickTranscriptBottom(transcript);
  if (stream && !stream.dataset.awScrollBound) {
    stream.dataset.awScrollBound = "1";
    stream.dataset.awStickBottom = "true";
    stream.addEventListener("scroll", () => {
      const distance = stream.scrollHeight - stream.clientHeight - stream.scrollTop;
      stream.dataset.awStickBottom = distance <= 24 ? "true" : "false";
    }, { passive: true });
  }
  const streamShouldStick = shouldStickAgentJobStreamBottom(stream);
  if (badge) badge.textContent = `${g.count} update${g.count === 1 ? "" : "s"}${g.running ? " • running" : ""}`;
  let textChanged = false;
  if (pre && pre.textContent !== g.text) {
    pre.textContent = g.text;
    textChanged = true;
  }
  if (box) box.open = true;
  renderAgentFlowInteraction(box, ctx, g);
  if (stream && (g.running || textChanged)) {
    if (streamShouldStick) maybeScrollAgentJobStreamBottom(stream, true);
    if (transcriptShouldStick) maybeScrollTranscriptBottom(transcript, true);
  }
  moveMatchingFlowResultsAfterJob(ctx, msg, wrap);
  return wrap;
}

function renderAgentFlowSteerFooter(msg, ctx) {
  if (!isAgentJobAssistantMessage(msg) || !isFlowStreamLikeMessage(msg)) return null;
  const g = getAgentJobGroup(ctx, msg);
  if (!g || !g.runId || !g.running) return null;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "aw-job-steer-footer";
  btn.title = "Steer workflow";
  btn.setAttribute("aria-label", "Steer workflow");
  const icon = document.createElement("span");
  icon.className = "aw-icon aw-icon-steer";
  icon.setAttribute("aria-hidden", "true");
  btn.appendChild(icon);
  btn.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    let wrap = null;
    try {
      wrap = document.querySelector(`.message.assistant[data-msg-id="${String(msg.msg_id || "").replace(/["\\]/g, "\\$&")}"]`);
    } catch (_err) {
      wrap = null;
    }
    const box = wrap?.querySelector?.(".aw-job-group");
    if (!box) return;
    box.open = true;
    const steerKey = String(g?.runId || g?.startMsgId || "").trim();
    const open = box.dataset.awSteerOpen !== "true";
    box.dataset.awSteerOpen = open ? "true" : "false";
    if (steerKey) {
      if (open) steerOpenByRunId.set(steerKey, true);
      else steerOpenByRunId.delete(steerKey);
    }
    renderAgentFlowInteraction(box, ctx, g);
    if (open) {
      const input = box.querySelector('[data-aw-input-kind="steer"]');
      try { input?.focus?.({ preventScroll: true }); } catch (_err) {}
    }
  });
  return btn;
}

function bindAgentJobStreamFollow(stream) {
  if (!stream || stream.dataset.awScrollBound) return;
  stream.dataset.awScrollBound = "1";
  stream.dataset.awStickBottom = "true";
  stream.addEventListener("scroll", () => {
    const distance = stream.scrollHeight - stream.clientHeight - stream.scrollTop;
    stream.dataset.awStickBottom = distance <= 24 ? "true" : "false";
  }, { passive: true });
}

function getTranscriptScrollContainer(node) {
  const direct = document.getElementById("transcript");
  if (direct) return direct;
  return node?.closest?.("#transcript") || null;
}

function shouldStickTranscriptBottom(transcript) {
  if (!transcript) return false;
  const distance = transcript.scrollHeight - transcript.clientHeight - transcript.scrollTop;
  return distance <= 96;
}

function shouldStickAgentJobStreamBottom(stream) {
  if (!stream) return false;
  bindAgentJobStreamFollow(stream);
  if (String(stream.dataset.awStickBottom || "true") === "false") return false;
  const distance = stream.scrollHeight - stream.clientHeight - stream.scrollTop;
  return distance <= 24;
}

function maybeScrollTranscriptBottom(transcript, force = false) {
  if (!transcript) return;
  const shouldStick = force || shouldStickTranscriptBottom(transcript);
  if (!shouldStick) return;
  const snap = () => {
    if (force || shouldStickTranscriptBottom(transcript)) {
      transcript.scrollTop = transcript.scrollHeight;
    }
  };
  snap();
  requestAnimationFrame(() => {
    snap();
    requestAnimationFrame(snap);
  });
  setTimeout(snap, 60);
}

function maybeScrollAgentJobStreamBottom(stream, force = false) {
  if (!stream) return;
  bindAgentJobStreamFollow(stream);
  const shouldStick = force || shouldStickAgentJobStreamBottom(stream);
  if (!shouldStick) return;
  const snap = () => {
    if (force || shouldStickAgentJobStreamBottom(stream)) {
      stream.scrollTop = stream.scrollHeight;
    }
  };
  snap();
  requestAnimationFrame(() => {
    snap();
    requestAnimationFrame(snap);
  });
  setTimeout(snap, 60);
}

function shouldRunWorkflowForText(rawText) {
  const text = String(rawText || "").trim();
  if (!text) return false;
  const lower = text.toLowerCase();
  if (lower.startsWith("/aw ")) return true;
  // Question-first/read-only prompts should not auto-trigger code execution.
  if (/^(what|why|how|can you|could you|would you|explain|describe|summarize|review|read)\b/.test(lower)) {
    return false;
  }
  const changeIntent = /\b(create|implement|add|build|generate|write|modify|change|update|fix|debug|refactor|patch|edit|replace|remove|delete)\b/;
  const targetHint = /\b(code|file|files|function|class|module|repo|repository|plugin|test|tests|bug|feature|game|app|javascript|typescript|python|html|css)\b/;
  return changeIntent.test(lower) && targetHint.test(lower);
}

function buildPluginHeaders(ctx, extra = {}) {
  const headers = {};
  const token = String(ctx?.state?.auth?.token || "").trim();
  const guestId = String(ctx?.state?.auth?.guestId || "").trim();
  const alias = String(ctx?.state?.auth?.alias || "").trim();
  if (token) headers.Authorization = `Bearer ${token}`;
  else if (guestId) headers["X-Guest-Id"] = guestId;
  if (alias) headers["X-User-Alias"] = alias;
  const pid = String(extra?.pid || "").trim();
  const sid = String(extra?.sid || "").trim();
  if (pid) headers["X-Project-Id"] = pid;
  if (sid) headers["X-Session-Id"] = sid;
  return { ...headers, ...(extra?.headers || {}) };
}

function getPidSid(ctx) {
  const pid = ctx?.state?.ui?.activePid || "";
  const sid = ctx?.state?.ui?.activeSid || "";
  return { pid: String(pid || ""), sid: String(sid || "") };
}

function getWorkflowUiState(ctx) {
  if (!ctx?.state) return { autoIndexRepo: true, targetRepoRoot: "", repoContextJson: "", repoRagHitsJson: "", indexCache: {}, lastIndexRoot: "", lastIndexTs: 0, lastIndexStatus: "", lastIndexError: "", requireApproval: false, pendingApproval: null };
  if (!ctx.state.agent_workflow_ui || typeof ctx.state.agent_workflow_ui !== "object") {
    ctx.state.agent_workflow_ui = { autoIndexRepo: true, targetRepoRoot: "", repoContextJson: "", repoRagHitsJson: "", indexCache: {}, lastIndexRoot: "", lastIndexTs: 0, lastIndexStatus: "", lastIndexError: "", requireApproval: false, pendingApproval: null };
  }
  const s = ctx.state.agent_workflow_ui;
  return {
    autoIndexRepo: s.autoIndexRepo !== false,
    targetRepoRoot: String(s.targetRepoRoot || ""),
    repoContextJson: String(s.repoContextJson || ""),
    repoRagHitsJson: String(s.repoRagHitsJson || ""),
    indexCache: s.indexCache && typeof s.indexCache === "object" ? s.indexCache : {},
    lastIndexRoot: String(s.lastIndexRoot || ""),
    lastIndexTs: Number(s.lastIndexTs || 0),
    lastIndexStatus: String(s.lastIndexStatus || ""),
    lastIndexError: String(s.lastIndexError || ""),
    requireApproval: Boolean(s.requireApproval),
    pendingApproval: s.pendingApproval && typeof s.pendingApproval === "object" ? s.pendingApproval : null,
  };
}

async function ensureRepoIndexed(ctx, rootRel) {
  const st = getWorkflowUiState(ctx);
  if (!st.autoIndexRepo) return { ok: true, skipped: "auto_index_disabled" };
  const root = String(rootRel || "").trim();
  if (!root) return { ok: true, skipped: "no_target_repo_root" };

  const cache = st.indexCache || {};
  const now = Date.now();

  const pid = String(ctx?.state?.ui?.activePid || "");
  const sid = String(ctx?.state?.ui?.activeSid || "");
  if (!pid || !sid) {
    setWorkflowUiState(ctx, { lastIndexRoot: root, lastIndexTs: now, lastIndexStatus: "failed", lastIndexError: "active_project_or_session_missing" });
    return { ok: false, error: "active_project_or_session_missing" };
  }

  let rootDir = "";
  try {
    const prep = await ctx.apiJson("/v1/agent_workflow/repo_prepare", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Gui-Enabled-Plugins": "agent_workflow,repo_panel,collab_chat",
      },
      body: { pid, sid, target_repo_root: root },
    });
    rootDir = String(prep?.abs_dir || "").trim();
  } catch (err) {
    const msg = `repo_prepare_failed:${err?.message || err}`;
    setWorkflowUiState(ctx, { lastIndexRoot: root, lastIndexTs: now, lastIndexStatus: "failed", lastIndexError: msg });
    return { ok: false, error: msg };
  }
  if (!rootDir) {
    setWorkflowUiState(ctx, { lastIndexRoot: root, lastIndexTs: now, lastIndexStatus: "failed", lastIndexError: "repo_prepare_missing_abs_dir" });
    return { ok: false, error: "repo_prepare_missing_abs_dir" };
  }
  let ingest = null;
  try {
    ingest = await ctx.apiJson("/v1/agent_workflow/repo_ingest", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Gui-Enabled-Plugins": "agent_workflow,repo_panel,collab_chat",
      },
      body: {
        pid,
        sid,
        repo_id: "current",
        target_repo_root: root,
        root_dir: rootDir,
        chunk_lines: 220,
        max_file_bytes: 220000,
      },
    });
  } catch (err) {
    const msg = `repo_ingest_failed:${err?.message || err}`;
    setWorkflowUiState(ctx, { lastIndexRoot: root, lastIndexTs: now, lastIndexStatus: "failed", lastIndexError: msg });
    return { ok: false, error: msg };
  }

  setWorkflowUiState(ctx, {
    indexCache: { ...(cache || {}), [root]: now },
    lastIndexRoot: root,
    lastIndexTs: now,
    lastIndexStatus: String(ingest?.mode || "indexed"),
    lastIndexError: "",
  });
  return { ok: true, indexed: true, root, mode: String(ingest?.mode || "indexed"), ingest };
}

function setWorkflowUiState(ctx, patch) {
  const cur = getWorkflowUiState(ctx);
  ctx.state.agent_workflow_ui = { ...cur, ...(patch || {}) };
  ctx.saveState?.();
  return ctx.state.agent_workflow_ui;
}

const repoWarmupJobs = new Map();
const repoWarmupLastRunAtByKey = new Map();
const repoWarmupNoDeltaUntilByKey = new Map();
let repoWarmupObserverTimer = 0;
let repoWarmupObserverKey = "";
let repoWarmupObserverLastRunAt = 0;
const REPO_WARMUP_MIN_INTERVAL_MS = 30000;
const REPO_WARMUP_NO_DELTA_BACKOFF_MS = 120000;

async function performRepoWarmup(ctx, options = {}) {
  const st = getWorkflowUiState(ctx);
  const root = String(options.root || st.targetRepoRoot || "").trim();
  const query = String(options.query || "").trim();
  const pid = String(ctx?.state?.ui?.activePid || "");
  const sid = String(ctx?.state?.ui?.activeSid || "");
  if (!pid || !sid || !root) return { ok: true, skipped: "missing_scope_or_root" };

  setWorkflowUiState(ctx, {
    lastIndexRoot: root,
    lastIndexTs: Date.now(),
    lastIndexStatus: "warming",
    lastIndexError: "",
  });

  let indexed = null;
  try {
    indexed = await ensureRepoIndexed(ctx, root);
  } catch (err) {
    const msg = String(err?.message || err || "repo_index_failed");
    setWorkflowUiState(ctx, {
      lastIndexRoot: root,
      lastIndexTs: Date.now(),
      lastIndexStatus: "failed",
      lastIndexError: msg,
    });
    return { ok: false, error: msg };
  }

  if (query) {
    try {
      const rag = await ctx.apiJson("/v1/agent_workflow/rag_query", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Gui-Enabled-Plugins": "agent_workflow,collab_chat" },
        body: { pid, sid, query, target_repo_root: root, k: 6, max_chars: 1200 },
      });
      let hits = Array.isArray(rag?.hits) ? rag.hits : [];
      const fm = query.match(/([A-Za-z0-9_./\\-]+\.(?:py|js|ts|tsx|jsx|json|md|html|css))/);
      const fname = String(fm?.[1] || "").trim();
      if (fname) {
        try {
          const rr = await ctx.apiJson("/v1/agent_workflow/repo_read", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Gui-Enabled-Plugins": "agent_workflow,collab_chat" },
            body: { pid, sid, target_repo_root: root, target: fname, max_chars: 3200 },
          });
          if (rr?.ok && rr?.found && rr?.text) {
            const lead = { path: String(rr.path || fname), score: 1.0, text: String(rr.text || "") };
            hits = [lead, ...hits.filter((h) => String(h?.path || "") !== lead.path)];
          }
        } catch (_err) {}
      }
      setWorkflowUiState(ctx, { repoRagHitsJson: JSON.stringify(hits) });
    } catch (_err) {
      setWorkflowUiState(ctx, { repoRagHitsJson: "[]" });
    }
  }

  try {
    const repoCtx = await buildRepoContextForMainChat(ctx, root);
    setWorkflowUiState(ctx, {
      repoContextJson: repoCtx || "",
      lastIndexRoot: root,
      lastIndexTs: Date.now(),
      lastIndexStatus: indexed?.ok ? (indexed?.indexed ? "indexed" : "ready") : "ready",
      lastIndexError: "",
    });
  } catch (_err) {
    setWorkflowUiState(ctx, {
      lastIndexRoot: root,
      lastIndexTs: Date.now(),
      lastIndexStatus: indexed?.ok ? "ready" : "failed",
    });
  }
  return { ok: true, root, indexed };
}

function scheduleRepoWarmup(ctx, options = {}) {
  const st = getWorkflowUiState(ctx);
  const root = String(options.root || st.targetRepoRoot || "").trim();
  const pid = String(ctx?.state?.ui?.activePid || "");
  const sid = String(ctx?.state?.ui?.activeSid || "");
  if (!pid || !sid || !root) return Promise.resolve({ ok: true, skipped: "missing_scope_or_root" });
  const key = `${pid}::${sid}::${root}`;
  const existing = repoWarmupJobs.get(key);
  if (existing && !options.force) return existing;
  const now = Date.now();
  const hasQuery = !!String(options.query || "").trim();
  const noDeltaUntil = Number(repoWarmupNoDeltaUntilByKey.get(key) || 0);
  if (!options.force && !hasQuery && noDeltaUntil > now) {
    return Promise.resolve({ ok: true, skipped: "no_delta_backoff", root });
  }
  const lastRunAt = Number(repoWarmupLastRunAtByKey.get(key) || 0);
  if (!options.force && !hasQuery && lastRunAt && (now - lastRunAt) < REPO_WARMUP_MIN_INTERVAL_MS) {
    return Promise.resolve({ ok: true, skipped: "warmup_recent", root });
  }
  repoWarmupLastRunAtByKey.set(key, now);
  const nextRun = Promise.resolve()
    .then(() => performRepoWarmup(ctx, { ...options, root }))
    .then((result) => {
      const mode = String(result?.indexed?.mode || result?.indexed?.ingest?.mode || "");
      if (mode === "no_delta" || mode === "cached_no_delta") {
        repoWarmupNoDeltaUntilByKey.set(key, Date.now() + REPO_WARMUP_NO_DELTA_BACKOFF_MS);
      } else if (mode) {
        repoWarmupNoDeltaUntilByKey.delete(key);
      }
      return result;
    });
  let tracked = null;
  tracked = nextRun.finally(() => {
    if (repoWarmupJobs.get(key) === tracked) repoWarmupJobs.delete(key);
  });
  repoWarmupJobs.set(key, tracked);
  return tracked;
}

function stopRepoWarmupObserver() {
  if (repoWarmupObserverTimer) {
    try { clearInterval(repoWarmupObserverTimer); } catch (_err) {}
    repoWarmupObserverTimer = 0;
  }
  repoWarmupObserverKey = "";
  repoWarmupObserverLastRunAt = 0;
}

function startRepoWarmupObserver(ctx) {
  if (!ctx?.state) return;
  const pollMs = 60000;
  const tick = () => {
    try {
      const st = getWorkflowUiState(ctx);
      const pid = String(ctx?.state?.ui?.activePid || "").trim();
      const sid = String(ctx?.state?.ui?.activeSid || "").trim();
      const root = String(st.targetRepoRoot || "").trim();
      const key = `${pid}::${sid}::${root}`;
      if (!pid || !sid || !root) {
        repoWarmupObserverKey = key;
        return;
      }
      const now = Date.now();
      if (key === repoWarmupObserverKey && (now - repoWarmupObserverLastRunAt) < pollMs) return;
      repoWarmupObserverKey = key;
      repoWarmupObserverLastRunAt = now;
      void scheduleRepoWarmup(ctx, { root });
    } catch (_err) {}
  };
  tick();
  if (repoWarmupObserverTimer) return;
  repoWarmupObserverTimer = setInterval(tick, 10000);
}

async function pickWorkspaceFolder(ctx) {
  const REPO_BASE = "data/agent_workflow/repo";
  const pid = String(ctx?.state?.ui?.activePid || "");
  const sid = String(ctx?.state?.ui?.activeSid || "");
  if (!pid || !sid) throw new Error("Active project/session required.");
  const data = await ctx.apiJson(`/v1/agent_workflow/repo_tree?pid=${encodeURIComponent(pid)}&sid=${encodeURIComponent(sid)}&max_files=3000`, {
    headers: { "X-Gui-Enabled-Plugins": "agent_workflow,collab_chat" },
  });
  const files = Array.isArray(data?.data?.files) ? data.data.files : [];
  const dirs = new Set([REPO_BASE]);
  files.forEach((f) => {
    const p = String(f || "").replace(/\\/g, "/");
    if (!(p === REPO_BASE || p.startsWith(`${REPO_BASE}/`))) return;
    const parts = p.split("/");
    for (let i = 1; i < parts.length; i += 1) {
      const d = parts.slice(0, i).join("/");
      if (d && (d === REPO_BASE || d.startsWith(`${REPO_BASE}/`))) dirs.add(d);
    }
  });
  const sorted = Array.from(dirs).sort((a, b) => a.localeCompare(b));
  return new Promise((resolve) => {
    const backdrop = document.createElement("div");
    backdrop.className = "aw-modal-backdrop";
    const modal = document.createElement("div");
    modal.className = "aw-modal";
    modal.innerHTML = `
      <div class="aw-title">Select Repo Folder</div>
      <input id="aw-modal-filter" placeholder="Filter folders..." />
      <div class="aw-modal-list" id="aw-modal-list"></div>
      <div class="aw-actions">
        <button class="aw-btn" id="aw-modal-cancel">Cancel</button>
      </div>
    `;
    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);
    const list = modal.querySelector("#aw-modal-list");
    const filter = modal.querySelector("#aw-modal-filter");
    const cancel = modal.querySelector("#aw-modal-cancel");
    const render = () => {
      const q = String(filter.value || "").toLowerCase().trim();
      list.innerHTML = "";
      sorted
        .filter((d) => !q || d.toLowerCase().includes(q))
        .slice(0, 600)
        .forEach((d) => {
          const row = document.createElement("div");
          row.className = "aw-modal-item aw-mono";
          row.textContent = d;
          row.addEventListener("click", () => {
            backdrop.remove();
            resolve(d);
          });
          list.appendChild(row);
        });
    };
    filter.addEventListener("input", render);
    cancel.addEventListener("click", () => {
      backdrop.remove();
      resolve("");
    });
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) {
        backdrop.remove();
        resolve("");
      }
    });
    render();
    filter.focus();
  });
}

function summarizeWorkflowResult(data) {
  const warnings = Array.isArray(data?.warnings) ? data.warnings : [];
  const errors = Array.isArray(data?.errors) ? data.errors : [];
  const outputs = Array.isArray(data?.outputs) ? data.outputs : [];
  const lines = [];
  lines.push(`[agent_workflow] ${String(data?.summary || "Workflow run completed.")}`);
  lines.push(`workflow_id: ${String(data?.workflow_id || "")}`);
  lines.push(`ok: ${Boolean(data?.ok)}`);
  if (warnings.length) lines.push("warnings:");
  warnings.slice(0, 12).forEach((w) => lines.push(`- ${String(w)}`));
  if (errors.length) lines.push("errors:");
  errors.slice(0, 12).forEach((e) => lines.push(`- ${String(e)}`));

  const plan = outputs.find((o) => o?.type === "workflow_plan")?.data || {};
  const review = outputs.find((o) => o?.type === "review")?.data || {};
  const iter = outputs.find((o) => o?.type === "iteration")?.data || {};
  const gate = outputs.find((o) => o?.type === "completion_gate")?.data || {};
  if (Array.isArray(plan?.steps) && plan.steps.length) {
    lines.push("plan_steps:");
    plan.steps.slice(0, 8).forEach((s) => lines.push(`- ${String(s)}`));
  }
  if (Array.isArray(review?.results) && review.results.length) {
    const bad = review.results.filter((r) => !r?.ok).map((r) => String(r?.profile || ""));
    lines.push(`review: ${review.ok ? "pass" : "issues"}${bad.length ? ` (profiles: ${bad.join(", ")})` : ""}`);
  }
  if (Array.isArray(iter?.attempts) && iter.attempts.length) {
    const last = iter.attempts[iter.attempts.length - 1] || {};
    const changed = Array.isArray(last?.apply?.data?.changed_files) ? last.apply.data.changed_files : [];
    lines.push(`iteration: attempts=${iter.attempts.length}/${iter.max_attempts || "?"}, all_ok=${Boolean(iter.all_ok)}`);
    if (changed.length) {
      lines.push("changed_files:");
      changed.slice(0, 12).forEach((f) => lines.push(`- ${String(f)}`));
    }
    const testRuns = Array.isArray(last?.test?.data?.runs) ? last.test.data.runs : [];
    if (testRuns.length) {
      lines.push("test_runs:");
      testRuns.slice(0, 6).forEach((r) => {
        const cmd = Array.isArray(r?.command) ? r.command.join(" ") : String(r?.command || "");
        lines.push(`- ${cmd} => ${r?.ok ? "ok" : "fail"} (exit=${r?.exit_code})`);
      });
    }
  }
  if (gate && typeof gate === "object") {
    lines.push(`completion_gate: working_code=${Boolean(gate.working_code)} tests_passed=${Boolean(gate.tests_passed)} critical_review_passed=${Boolean(gate.critical_review_passed)}`);
  }
  return lines.join("\n");
}

function parseStepDetailsFromText(content) {
  const txt = String(content || "");
  if (!txt) return null;
  const m = txt.match(/^Flow step\s+(\d+)\/(\d+):\s*(.+)$/m);
  if (!m) return null;
  const step = Number(m[1] || 0);
  const total = Number(m[2] || 0);
  const member = String(m[3] || "").trim();
  const lines = txt.split(/\r?\n/);
  let did = "";
  let handoff = "";
  let skills = "";
  const actions = [];
  let inActions = false;
  for (const raw of lines) {
    const ln = String(raw || "").trim();
    if (!ln) continue;
    if (ln.toLowerCase().startsWith("did:")) {
      did = ln.slice(4).trim();
      inActions = false;
      continue;
    }
    if (ln.toLowerCase() === "actions:") {
      inActions = true;
      continue;
    }
    if (ln.toLowerCase().startsWith("skills_invoked:")) {
      skills = ln.slice("skills_invoked:".length).trim();
      inActions = false;
      continue;
    }
    if (ln.toLowerCase().startsWith("handoff:")) {
      handoff = ln.slice("handoff:".length).trim();
      inActions = false;
      continue;
    }
    if (inActions && ln.startsWith("- ")) {
      actions.push(ln.slice(2).trim());
    }
  }
  return { step, total, member, did, actions, skills, handoff };
}

function renderStepDetailsCard(listNode, details) {
  const card = document.createElement("div");
  card.className = "aw-step-card";
  const title = document.createElement("div");
  title.className = "aw-step-title";
  title.textContent = `Step ${details.step}/${details.total}: ${details.member}`;
  card.appendChild(title);
  if (details.did) {
    const did = document.createElement("div");
    did.className = "aw-step-line";
    did.textContent = `Did: ${details.did}`;
    card.appendChild(did);
  }
  if (Array.isArray(details.actions) && details.actions.length) {
    const aTitle = document.createElement("div");
    aTitle.className = "aw-step-line";
    aTitle.textContent = "Actions:";
    card.appendChild(aTitle);
    details.actions.slice(0, 8).forEach((a) => {
      const row = document.createElement("div");
      row.className = "aw-step-actions";
      row.textContent = `- ${a}`;
      card.appendChild(row);
    });
  }
  if (details.skills) {
    const s = document.createElement("div");
    s.className = "aw-step-line";
    s.textContent = `Skills: ${details.skills}`;
    card.appendChild(s);
  }
  if (details.handoff) {
    const h = document.createElement("div");
    h.className = "aw-step-line";
    h.textContent = `Handoff: ${details.handoff}`;
    card.appendChild(h);
  }
  listNode.appendChild(card);
}

function renderStepDetailsFromSession(ctx, sid, listNode, statusNode) {
  listNode.innerHTML = "";
  const session = ctx?.state?.sessions?.[sid];
  const msgs = Array.isArray(session?.messages) ? session.messages : [];
  const found = [];
  for (let i = msgs.length - 1; i >= 0; i -= 1) {
    const m = msgs[i];
    if (!m || String(m.role || "").toLowerCase() !== "assistant") continue;
    const details = parseStepDetailsFromText(m.content);
    if (details) found.push(details);
    if (found.length >= 24) break;
  }
  if (!found.length) {
    statusNode.textContent = "No step details found in transcript yet.";
    return;
  }
  found.reverse().forEach((d) => renderStepDetailsCard(listNode, d));
  statusNode.textContent = `Rendered ${found.length} step detail entr${found.length === 1 ? "y" : "ies"}.`;
}

async function buildRepoContextForMainChat(ctx, rootRel) {
  const pid = String(ctx?.state?.ui?.activePid || "");
  const sid = String(ctx?.state?.ui?.activeSid || "");
  const root = String(rootRel || "").trim();
  if (!pid || !sid || !root) return "";
  try {
    const data = await ctx.apiJson(`/v1/agent_workflow/repo_tree?pid=${encodeURIComponent(pid)}&sid=${encodeURIComponent(sid)}&max_files=2500`, {
      headers: { "X-Gui-Enabled-Plugins": "agent_workflow,collab_chat" },
    });
    const files = (Array.isArray(data?.data?.files) ? data.data.files : [])
      .map((x) => String(x || "").replace(/\\/g, "/"))
      .filter((p) => p === root || p.startsWith(`${root}/`));
    if (!files.length) return "";
    const relFiles = files
      .map((p) => (p === root ? "" : p.slice(root.length + 1)))
      .filter(Boolean);
    const topDirs = Array.from(
      new Set(
        relFiles
          .map((p) => p.split("/")[0] || "")
          .filter(Boolean)
      )
    ).slice(0, 20);
    const sampleFiles = relFiles.slice(0, 40);
    return JSON.stringify({
      target_repo_root: root,
      file_count_under_root: relFiles.length,
      top_level_dirs: topDirs,
      sample_files: sampleFiles.map((f) => `${root}/${f}`),
    });
  } catch {
    return "";
  }
}

function applyRepoContextToPayload(payload, ctx) {
  const st = getWorkflowUiState(ctx);
  const raw = String(st.repoContextJson || "").trim();
  const root = String(st.targetRepoRoot || "").trim();
  if (!root) return payload;
  let snap = null;
  try {
    snap = JSON.parse(raw);
  } catch {
    snap = null;
  }
  let ragHits = [];
  try {
    const arr = JSON.parse(String(st.repoRagHitsJson || "[]"));
    if (Array.isArray(arr)) ragHits = arr;
  } catch {}
  const out = { ...(payload || {}) };
  const ext = { ...(out.ext || {}) };
  // Activate existing custom-rag repo_context path (RAG retrieval) for main chat turns.
  ext.selected_repo_id = String(ext.selected_repo_id || "current");
  ext.selected_path_prefix = root;
  ext.custom_rag_plugin_settings = {
    ...(ext.custom_rag_plugin_settings || {}),
    repo_context: {
      enabled: true,
      max_files: 6,
      per_file_max_chars: 4500,
      max_defs: 20,
      outline_items: 12,
    },
  };
  if (snap && typeof snap === "object") {
    ext.agent_workflow_repo_context = snap;
  }
  ext.agent_workflow_rag_hits = ragHits;
  ext.agent_workflow_target_repo_root = root;
  out.ext = ext;
  const hitLines = (ragHits || []).slice(0, 5).map((h, i) => `#${i + 1} ${String(h.path || "")}\n${String(h.text || "").slice(0, 500)}`);
  const systemBlock = [
    "[agent_workflow_system_context]",
    `target_repo_root=${root}`,
    "Repository context is available via custom-rag repo_context (selected_path_prefix).",
    hitLines.length ? "Top retrieved code snippets:\n" + hitLines.join("\n\n") : "No retrieved snippets available for this turn.",
    "Use retrieved repo evidence to answer architecture/code questions with file-path references.",
    "Do not claim you cannot access files when repo context/snippets are present.",
    "If user asks whether you can read a specific file and snippet/path is present, answer yes and reference that path.",
    "If code changes are requested, provide concise patch plan and mention /aw run or /aw patch.",
    "[/agent_workflow_system_context]",
  ].join("\n");
  const msgs = Array.isArray(out.messages) ? out.messages.slice() : [];
  if (!msgs.length || msgs[0]?.role !== "system") {
    msgs.unshift({ role: "system", content: systemBlock });
  } else {
    const prior = String(msgs[0].content || "");
    if (!prior.includes("[agent_workflow_system_context]")) {
      msgs[0] = { ...msgs[0], content: `${prior}\n\n${systemBlock}`.trim() };
    }
  }
  out.messages = msgs;
  return out;
}

async function runWorkflowFromPayload(ctx, payload) {
  const pid = String(payload?.pid || ctx?.state?.ui?.activePid || "");
  const sid = String(payload?.sid || ctx?.state?.ui?.activeSid || "");
  if (!pid || !sid) return false;
  const text = String(payload?.text || "").trim();
  if (!text) return false;
  const st = getWorkflowUiState(ctx);
  try {
    await ensureRepoIndexed(ctx, st.targetRepoRoot);
  } catch (_err) {}
  const req = {
    pid,
    sid,
    intent: "auto",
    input: text,
    mode: String(payload?.ext?.agent_workflow_mode_override || "apply_patch"),
    targets: { repo_ids: ["current"], files: [] },
    constraints: { preserve_plugin_boundaries: true },
    options: {
      ...(st.targetRepoRoot ? { target_repo_root: String(st.targetRepoRoot) } : {}),
      max_attempts: 3,
      require_approval: Boolean(st.requireApproval),
      auto_fix_rules: payload?.ext?.agent_workflow_auto_fix_rules || [],
      patch_candidates: payload?.ext?.agent_workflow_patch_candidates || [],
    },
  };
  const sidForTranscript = String(payload?.sid || sid || ctx?.state?.ui?.activeSid || "");
  const msgId = (prefix) => `${prefix}-${sidForTranscript || "sid"}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const streamMsgId = msgId("aw");
  let streamLog = "";
  let streamCreated = false;
  let flushTimer = 0;
  let flushPending = false;
  const syncStateFromDom = (force = false) => {
    if (!force || !sidForTranscript || !streamCreated) return;
    if (typeof ctx.updateMessage === "function") {
      ctx.updateMessage(sidForTranscript, streamMsgId, streamLog, true);
    }
  };
  const paintStreamDom = () => {
    const rows = Array.from(document.querySelectorAll(`.message.assistant[data-msg-id]`));
    const row = rows.find((el) => String(el?.dataset?.msgId || "") === String(streamMsgId));
    const pre = row ? row.querySelector(".aw-job-stream pre") : null;
    const box = row ? row.querySelector(".aw-job-group") : null;
    const transcript = getTranscriptScrollContainer(row);
    const transcriptShouldStick = shouldStickTranscriptBottom(transcript);
    const stream = pre?.closest?.(".aw-job-stream");
    const streamShouldStick = shouldStickAgentJobStreamBottom(stream);
    let textChanged = false;
    if (pre && pre.textContent !== streamLog) {
      pre.textContent = streamLog;
      textChanged = true;
    }
    if (box) box.open = true;
    if (stream && textChanged) {
      if (streamShouldStick) maybeScrollAgentJobStreamBottom(stream);
    }
    if (textChanged && transcriptShouldStick) maybeScrollTranscriptBottom(transcript);
  };
  const flushAssistant = () => {
    flushPending = false;
    flushTimer = 0;
    if (!sidForTranscript || !streamLog) return;
    if (!streamCreated) {
      ctx.appendMessage?.(
        {
          msg_id: streamMsgId,
          role: "assistant",
          author: "assistant",
          content: streamLog,
        },
        sidForTranscript
      );
      streamCreated = true;
      requestAnimationFrame(() => paintStreamDom());
      return;
    }
    // Live updates paint only inside agent jobs container to avoid global flicker.
    paintStreamDom();
  };
  const scheduleFlush = () => {
    if (flushPending) return;
    flushPending = true;
    flushTimer = setTimeout(() => flushAssistant(), 80);
  };
  const appendAssistant = (text, append = true) => {
    if (!sidForTranscript || !text) return;
    streamLog = append ? `${streamLog}${streamLog ? "\n" : ""}${String(text)}` : String(text);
    if (!streamCreated) {
      flushAssistant();
      return;
    }
    scheduleFlush();
  };
  try {
    appendAssistant("[agent_workflow] Starting automated workflow run...", false);
    let finalData = null;
    let streamWorkflowId = "";
    let tracePollStop = false;
    let traceSeen = 0;
    const traceTailToLine = (r) => {
      const stage = String(r?.stage || "");
      const et = String(r?.event_type || "");
      const msg = String(r?.message || "");
      return `[agent_workflow] trace: ${stage}/${et}${msg ? ` - ${msg}` : ""}`;
    };
    const startTracePolling = () => {
      if (!streamWorkflowId) return;
      const loop = async () => {
        while (!tracePollStop) {
          try {
            const tr = await ctx.apiJson(`/v1/agent_workflow/trace/${encodeURIComponent(streamWorkflowId)}`, {
              headers: { "X-Gui-Enabled-Plugins": "agent_workflow,collab_chat" },
            });
            const rows = Array.isArray(tr?.trace) ? tr.trace : [];
            if (rows.length > traceSeen) {
              const next = rows.slice(traceSeen, Math.min(rows.length, traceSeen + 8));
              next.forEach((r) => appendAssistant(traceTailToLine(r)));
              traceSeen = rows.length;
            }
          } catch (_err) {}
          await new Promise((res) => setTimeout(res, 900));
        }
      };
      setTimeout(() => { loop(); }, 0);
    };
    await ctx.streamSSE("/v1/agent_workflow/stream", {
      method: "POST",
      headers: {
        ...buildPluginHeaders(ctx, { pid, sid }),
        "Content-Type": "application/json",
        "X-Gui-Enabled-Plugins": "agent_workflow,collab_chat",
      },
      body: JSON.stringify(req),
      onEvent: (event, data) => {
        const name = String(event || "");
        const d = data || {};
        if (name === "workflow_start") {
          streamWorkflowId = String(d.workflow_id || "");
          appendAssistant(`[agent_workflow] workflow_start: id=${String(d.workflow_id || "")} family=${String(d.family || "")}`);
          startTracePolling();
          return;
        }
        if (name === "stage_start") {
          appendAssistant(`[agent_workflow] stage_start: ${String(d.stage || "")}`);
          return;
        }
        if (name === "stage_progress") {
          appendAssistant(`[agent_workflow] stage_progress: ${String(d.stage || "")} - ${String(d.message || "")}`);
          return;
        }
        if (name === "stage_result") {
          const stage = String(d.stage || "");
          const p = Number(d.progress || 0);
          appendAssistant(`[agent_workflow] stage_result: ${stage} progress=${Math.round(p * 100)}% warnings=${Number(d.warnings_count || 0)} errors=${Number(d.errors_count || 0)}`);
          const it = d.iteration;
          if (it && Array.isArray(it.attempts) && it.attempts.length) {
            const last = it.attempts[it.attempts.length - 1] || {};
            const changed = Array.isArray(last?.apply?.data?.changed_files) ? last.apply.data.changed_files.length : 0;
            appendAssistant(`[agent_workflow] iterate_attempt: ${Number(last.attempt || it.attempts.length)}/${Number(it.max_attempts || "?")} ok=${Boolean(last.ok)} changed_files=${changed}`);
          }
          return;
        }
        if (name === "stage_detail") {
          const stage = String(d.stage || "");
          if (stage === "plan") {
            const plan = d.plan || {};
            const steps = Array.isArray(plan.steps) ? plan.steps.slice(0, 4) : [];
            if (steps.length) appendAssistant(`[agent_workflow] plan_detail:\n- ${steps.join("\n- ")}`);
          }
          if (stage === "iterate") {
            const it = d.iteration || {};
            const changed = Array.isArray(it.changed_files) ? it.changed_files : [];
            const applyErrs = Array.isArray(it.apply_errors) ? it.apply_errors : [];
            const runs = Array.isArray(it.test_runs) ? it.test_runs : [];
            if (changed.length) appendAssistant(`[agent_workflow] changed_files:\n- ${changed.slice(0, 12).join("\n- ")}`);
            if (applyErrs.length) appendAssistant(`[agent_workflow] apply_errors:\n- ${applyErrs.slice(0, 10).join("\n- ")}`);
            if (runs.length) {
              const rows = runs.slice(0, 8).map((r) => {
                const cmd = Array.isArray(r?.command) ? r.command.join(" ") : String(r?.command || "");
                const parsed = r?.parsed || {};
                const sum = String(parsed?.summary || "");
                return `${cmd} => ${r?.ok ? "ok" : "fail"} (exit=${r?.exit_code})${sum ? ` summary=${sum}` : ""}`;
              });
              appendAssistant(`[agent_workflow] test_runs:\n- ${rows.join("\n- ")}`);
            }
          }
          if (stage === "review") {
            const rev = d.review || {};
            const res = Array.isArray(rev.results) ? rev.results : [];
            const bad = res.filter((x) => !x?.ok).map((x) => `${String(x?.profile || "")}: ${(Array.isArray(x?.findings) ? x.findings.slice(0, 2) : []).join("; ")}`);
            if (bad.length) appendAssistant(`[agent_workflow] review_findings:\n- ${bad.slice(0, 8).join("\n- ")}`);
          }
          const nw = Array.isArray(d.new_warnings) ? d.new_warnings : [];
          const ne = Array.isArray(d.new_errors) ? d.new_errors : [];
          if (nw.length) appendAssistant(`[agent_workflow] warnings_added:\n- ${nw.slice(0, 10).join("\n- ")}`);
          if (ne.length) appendAssistant(`[agent_workflow] errors_added:\n- ${ne.slice(0, 10).join("\n- ")}`);
          return;
        }
        if (name === "approval_required") {
          appendAssistant(`[agent_workflow] approval_required: workflow_id=${String(d.workflow_id || "")} node_id=${String(d.node_id || "approval_1")}`);
          return;
        }
        if (name === "workflow_complete") {
          tracePollStop = true;
          appendAssistant(`[agent_workflow] workflow_complete: id=${String(d.workflow_id || "")} ok=${Boolean(d.ok)}`);
          return;
        }
        if (name === "workflow_result") {
          finalData = d || null;
          return;
        }
        if (name === "workflow_error") {
          tracePollStop = true;
          appendAssistant(`[agent_workflow] workflow_error: ${String(d?.message || "")}`);
        }
      },
    });
    tracePollStop = true;
    if (!finalData || !finalData.workflow_id) {
      // fallback to sync run if stream body did not include final object
      appendAssistant("[agent_workflow] stream ended without workflow_result; fetching status/trace...");
      try {
        if (streamWorkflowId) {
          const tr0 = await ctx.apiJson(`/v1/agent_workflow/trace/${encodeURIComponent(streamWorkflowId)}`, {
            headers: { "X-Gui-Enabled-Plugins": "agent_workflow,collab_chat" },
          });
          if (tr0?.workflow_id) finalData = { ...(finalData || {}), workflow_id: tr0.workflow_id };
        }
      } catch (_err0) {}
      if (!finalData || !finalData.workflow_id) {
        finalData = await ctx.apiJson("/v1/agent_workflow/run", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Gui-Enabled-Plugins": "agent_workflow,collab_chat",
          },
          body: req,
        });
      }
    }
    if (finalData?.workflow_id) {
      ctx.log?.(`[agent_workflow] run started: ${finalData.workflow_id}`, "info");
      appendAssistant(summarizeWorkflowResult(finalData));
      const paused = String(finalData?.summary || "").toLowerCase().includes("awaiting approval");
      if (paused) {
        const pending = { workflow_id: String(finalData.workflow_id || ""), node_id: "approval_1", action: "approve" };
        setWorkflowUiState(ctx, { pendingApproval: pending });
        appendAssistant(`[agent_workflow] Approval required.\nworkflow_id: ${pending.workflow_id}\nnode_id: ${pending.node_id}\nUse Workflow tab approval controls to approve/reject/revise.`);
      } else {
        setWorkflowUiState(ctx, { pendingApproval: null });
      }
      try {
        const tr = await ctx.apiJson(`/v1/agent_workflow/trace/${encodeURIComponent(String(finalData.workflow_id || ""))}`, {
          headers: { "X-Gui-Enabled-Plugins": "agent_workflow,collab_chat" },
        });
        const rows = Array.isArray(tr?.trace) ? tr.trace : [];
        const brief = rows.slice(-12).map((r) => `- ${String(r.stage || "")}: ${String(r.event_type || "")} ${String(r.message || "")}`);
        if (brief.length) appendAssistant(`[agent_workflow] trace_tail:\n${brief.join("\n")}`);
      } catch (_err) {}
      return true;
    }
    ctx.log?.("[agent_workflow] run did not return workflow_id", "warn");
    appendAssistant("[agent_workflow] Run finished without workflow_id.");
    return false;
  } catch (err) {
    ctx.log?.(`[agent_workflow] run failed: ${err?.message || err}`, "warn");
    appendAssistant(`[agent_workflow] Run failed: ${err?.message || err}`);
    return false;
  } finally {
    if (flushTimer) clearTimeout(flushTimer);
    flushAssistant();
    syncStateFromDom(true);
  }
}

async function sendApprovalDecision(ctx, payload, statusNode) {
  const workflowId = String(payload?.workflow_id || "").trim();
  const nodeId = String(payload?.node_id || "approval_1").trim() || "approval_1";
  const action = String(payload?.action || "approve").trim();
  const notes = String(payload?.notes || "").trim();
  if (!workflowId) {
    statusNode.textContent = "workflow_id is required.";
    return false;
  }
  statusNode.textContent = `Sending approval action '${action}'...`;
  try {
    const data = await ctx.apiJson("/v1/agent_workflow/approval", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Gui-Enabled-Plugins": "agent_workflow,collab_chat",
      },
      body: { workflow_id: workflowId, node_id: nodeId, action, notes: notes || null },
    });
    const sid = String(ctx?.state?.ui?.activeSid || "");
    if (sid && ctx.appendMessage) {
      ctx.appendMessage(
        {
          msg_id: `aw-approval-${sid}-${Date.now()}`,
          role: "assistant",
          author: "assistant",
          content: `[agent_workflow] Approval action '${action}' submitted for ${workflowId}. resumed: ${Boolean(data?.resumed)}`,
        },
        sid
      );
    }
    setWorkflowUiState(ctx, { pendingApproval: null });
    statusNode.textContent = `Approval action '${action}' submitted.`;
    return true;
  } catch (err) {
    statusNode.textContent = `Approval failed: ${err?.message || err}`;
    return false;
  }
}

async function sendHook(payload, ctx) {
  const sid = String(payload?.sid || ctx?.state?.ui?.activeSid || "");
  if (!sid) return payload;
  const st = getWorkflowUiState(ctx);
  const bypass = Boolean(payload?.ext?.agent_workflow_bypass);
  if (bypass) return payload;
  const text = String(payload?.text || "").trim();
  if (st.targetRepoRoot) {
    const root = st.targetRepoRoot;
    setTimeout(() => {
      try { void scheduleRepoWarmup(ctx, { root }); } catch (_err) {}
    }, 2500);
  }
  const m = text.match(/^\/aw\s+(plan|run|patch)\s+([\s\S]+)$/i);
  if (m) {
    const modeMap = { plan: "plan_only", run: "apply_patch", patch: "apply_patch" };
    const next = String(m[2] || "").trim();
    const p2 = {
      ...payload,
      text: next,
      ext: {
        ...(payload?.ext || {}),
        agent_workflow_bypass: false,
        agent_workflow_mode_override: modeMap[String(m[1] || "").toLowerCase()] || "apply_patch",
      },
    };
    setTimeout(() => runWorkflowFromPayload(ctx, p2), 0);
    return { ...payload, handled: true };
  }
  return payload;
}

async function submitFeedback(ctx, form, statusNode) {
  const { pid, sid } = getPidSid(ctx);
  if (!pid || !sid) {
    statusNode.textContent = "Active project/session is required.";
    return;
  }
  const payload = {
    workflow_id: String(form.workflowId.value || "").trim() || null,
    pid,
    sid,
    pattern: String(form.pattern.value || "").trim(),
    correction_type: String(form.correctionType.value || "").trim(),
    notes: String(form.notes.value || "").trim(),
    preferred_files: parseCsv(form.preferredFiles.value),
    avoid: parseCsv(form.avoid.value),
    workflow_family: String(form.workflowFamily.value || "").trim() || null,
  };
  if (!payload.pattern) {
    statusNode.textContent = "Pattern is required.";
    return;
  }
  statusNode.textContent = "Submitting feedback...";
  try {
    const data = await ctx.apiJson("/v1/agent_workflow/feedback", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Gui-Enabled-Plugins": "agent_workflow,collab_chat",
      },
      body: payload,
    });
    if (data?.ok) {
      statusNode.textContent = `Feedback saved: ${data?.feedback?.feedback_id || "ok"}`;
      form.pattern.value = "";
      form.notes.value = "";
    } else {
      statusNode.textContent = "Feedback submit failed.";
    }
  } catch (err) {
    statusNode.textContent = `Feedback submit failed: ${err?.message || err}`;
  }
}

async function loadLearning(ctx, listNode, statusNode, limit = 40) {
  statusNode.textContent = "Loading learning data...";
  listNode.innerHTML = "";
  try {
    const data = await ctx.apiJson(`/v1/agent_workflow/learning?limit=${encodeURIComponent(String(limit))}`, {
      headers: { "X-Gui-Enabled-Plugins": "agent_workflow,collab_chat" },
    });
    const items = Array.isArray(data?.learning) ? data.learning.slice().reverse() : [];
    if (!items.length) {
      statusNode.textContent = "No learning items yet.";
      return;
    }
    items.forEach((it) => {
      const row = document.createElement("div");
      row.className = "aw-item";
      const top = document.createElement("div");
      top.className = "aw-item-top";
      top.innerHTML = `<span class="aw-mono">${it.feedback_id || ""}</span><span>${it.timestamp || ""}</span>`;
      const p = document.createElement("div");
      p.textContent = `Pattern: ${it.pattern || ""}`;
      const c = document.createElement("div");
      c.textContent = `Type: ${it.correction_type || ""}${it.workflow_family ? ` | Family: ${it.workflow_family}` : ""}`;
      const f = document.createElement("div");
      f.textContent = `Preferred files: ${(it.preferred_files || []).join(", ") || "-"}`;
      const a = document.createElement("div");
      a.textContent = `Avoid: ${(it.avoid || []).join(", ") || "-"}`;
      row.appendChild(top);
      row.appendChild(p);
      row.appendChild(c);
      row.appendChild(f);
      row.appendChild(a);
      if (it.notes) {
        const n = document.createElement("div");
        n.textContent = `Notes: ${it.notes}`;
        row.appendChild(n);
      }
      listNode.appendChild(row);
    });
    statusNode.textContent = `Loaded ${items.length} item(s).`;
  } catch (err) {
    statusNode.textContent = `Load failed: ${err?.message || err}`;
  }
}

async function loadTrace(ctx, workflowId, listNode, statusNode, onUse) {
  const wid = String(workflowId || "").trim();
  listNode.innerHTML = "";
  if (!wid) {
    statusNode.textContent = "Enter a workflow id to load trace.";
    return;
  }
  statusNode.textContent = "Loading trace...";
  try {
    const data = await ctx.apiJson(`/v1/agent_workflow/trace/${encodeURIComponent(wid)}`, {
      headers: { "X-Gui-Enabled-Plugins": "agent_workflow,collab_chat" },
    });
    const rows = Array.isArray(data?.trace) ? data.trace : [];
    if (!rows.length) {
      statusNode.textContent = "No trace entries found.";
      return;
    }
    rows.slice().reverse().forEach((it) => {
      const row = document.createElement("div");
      row.className = "aw-item";
      const top = document.createElement("div");
      top.className = "aw-item-top";
      top.innerHTML = `<span>${it.stage || ""} / ${it.event_type || ""}</span><span>${it.timestamp || ""}</span>`;
      const msg = document.createElement("div");
      msg.textContent = it.message || "";
      const actions = document.createElement("div");
      actions.className = "aw-item-actions";
      const useBtn = document.createElement("button");
      useBtn.className = "aw-btn";
      useBtn.textContent = "Use for Feedback";
      useBtn.addEventListener("click", () => onUse(it));
      actions.appendChild(useBtn);
      row.appendChild(top);
      row.appendChild(msg);
      row.appendChild(actions);
      listNode.appendChild(row);
    });
    statusNode.textContent = `Loaded ${rows.length} trace item(s).`;
  } catch (err) {
    statusNode.textContent = `Trace load failed: ${err?.message || err}`;
  }
}

async function loadProfiles(ctx, listNode, statusNode, teamUi) {
  listNode.innerHTML = "";
  statusNode.textContent = "Loading profile teams...";
  try {
    const data = await ctx.apiJson("/v1/agent_workflow/profiles", {
      headers: { "X-Gui-Enabled-Plugins": "agent_workflow,collab_chat" },
    });
    const profiles = data?.profiles || {};
    const teams = data?.teams || {};
    Object.keys(teams).forEach((teamName) => {
      const row = document.createElement("div");
      row.className = "aw-item";
      const top = document.createElement("div");
      top.className = "aw-item-top";
      top.innerHTML = `<span>Team: <span class="aw-mono">${teamName}</span></span><span>${(teams[teamName] || []).length} profiles</span>`;
      const body = document.createElement("div");
      body.textContent = (teams[teamName] || []).join(", ");
      const details = document.createElement("div");
      details.style.fontSize = "11px";
      details.style.color = "var(--ui-muted)";
      details.textContent = (teams[teamName] || [])
        .map((pid) => `${pid}: ${(profiles?.[pid]?.description || "").trim()}`)
        .join(" | ");
      row.appendChild(top);
      row.appendChild(body);
      row.appendChild(details);
      listNode.appendChild(row);
    });
    if (teamUi && teamUi.selectNode && teamUi.membersNode) {
      const prev = String(teamUi.selectNode.value || "").trim();
      teamUi.selectNode.innerHTML = "";
      Object.keys(teams).sort().forEach((teamName) => {
        const opt = document.createElement("option");
        opt.value = teamName;
        opt.textContent = teamName;
        teamUi.selectNode.appendChild(opt);
      });
      if (!teamUi.selectNode.options.length) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "(no teams)";
        teamUi.selectNode.appendChild(opt);
      }
      const selected = Object.prototype.hasOwnProperty.call(teams, prev)
        ? prev
        : String(teamUi.selectNode.value || "");
      teamUi.selectNode.value = selected;
      const members = Array.isArray(teams[selected]) ? teams[selected] : [];
      teamUi.membersNode.value = members.join(", ");
      if (teamUi.teamProfilesNode) {
        const rows = members.map((pid) => `${pid}: ${(profiles?.[pid]?.description || "").trim() || "-"}`);
        teamUi.teamProfilesNode.textContent = rows.length ? rows.join(" | ") : "No members for selected team.";
      }
      if (teamUi.teamStatusNode) {
        teamUi.teamStatusNode.textContent = `Selected team '${selected}' with ${members.length} profile(s).`;
      }
    }
    statusNode.textContent = "Loaded profile teams.";
  } catch (err) {
    statusNode.textContent = `Profile load failed: ${err?.message || err}`;
  }
}

async function loadProfileCatalog(ctx, listNode, statusNode, onPick) {
  listNode.innerHTML = "";
  statusNode.textContent = "Loading reviewer profiles...";
  try {
    const data = await ctx.apiJson("/v1/agent_workflow/profiles", {
      headers: { "X-Gui-Enabled-Plugins": "agent_workflow,collab_chat" },
    });
    const profiles = data?.profiles || {};
    const keys = Object.keys(profiles).sort();
    const dir = data?.profile_json?.dir || "";
    if (!keys.length) {
      statusNode.textContent = "No profiles available.";
      return;
    }
    keys.forEach((pid) => {
      const p = profiles[pid] || {};
      const row = document.createElement("div");
      row.className = "aw-item";
      const top = document.createElement("div");
      top.className = "aw-item-top";
      top.innerHTML = `<span class="aw-mono">${pid}</span><span>${p?.phase || "review"}</span>`;
      const body = document.createElement("div");
      body.textContent = `${p?.label || pid} | ${p?.description || ""}`;
      const actions = document.createElement("div");
      actions.className = "aw-item-actions";
      const btn = document.createElement("button");
      btn.className = "aw-btn";
      btn.textContent = "Edit (as JSON override)";
      btn.addEventListener("click", () => onPick(pid, p));
      actions.appendChild(btn);
      row.appendChild(top);
      row.appendChild(body);
      row.appendChild(actions);
      listNode.appendChild(row);
    });
    statusNode.textContent = `Loaded ${keys.length} profile(s). Profiles dir: ${dir}`;
  } catch (err) {
    statusNode.textContent = `Profile catalog load failed: ${err?.message || err}`;
  }
}

async function loadProfileFiles(ctx, listNode, statusNode) {
  listNode.innerHTML = "";
  statusNode.textContent = "Loading profile files...";
  try {
    const data = await ctx.apiJson("/v1/agent_workflow/profiles/files", {
      headers: { "X-Gui-Enabled-Plugins": "agent_workflow,collab_chat" },
    });
    const files = Array.isArray(data?.files) ? data.files : [];
    files.forEach((it) => {
      const row = document.createElement("div");
      row.className = "aw-item";
      const top = document.createElement("div");
      top.className = "aw-item-top";
      top.innerHTML = `<span class="aw-mono">${it.file_name || ""}</span><span>${Object.keys((it.content || {}).profiles || {}).length} profiles</span>`;
      row.appendChild(top);
      listNode.appendChild(row);
    });
    statusNode.textContent = `Loaded ${files.length} file(s).`;
  } catch (err) {
    statusNode.textContent = `Profile file load failed: ${err?.message || err}`;
  }
}

async function upsertProfileAndTeam(ctx, payload, statusNode) {
  statusNode.textContent = "Saving profile/team...";
  try {
    const data = await ctx.apiJson("/v1/agent_workflow/profiles/upsert", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Gui-Enabled-Plugins": "agent_workflow,collab_chat",
      },
      body: payload,
    });
    if (data?.ok) {
      statusNode.textContent = "Saved profile/team JSON.";
      return true;
    }
    statusNode.textContent = "Save failed.";
    return false;
  } catch (err) {
    statusNode.textContent = `Save failed: ${err?.message || err}`;
    return false;
  }
}

async function loadAgentTeams(ctx, listNode, statusNode) {
  listNode.innerHTML = "";
  statusNode.textContent = "Loading agent teams...";
  try {
    const data = await ctx.apiJson("/v1/agent_workflow/agents/config", {
      headers: { "X-Gui-Enabled-Plugins": "agent_workflow,collab_chat" },
    });
    const teams = data?.teams || {};
    Object.keys(teams).forEach((name) => {
      const workers = Array.isArray(teams[name]) ? teams[name] : [];
      const row = document.createElement("div");
      row.className = "aw-item";
      const top = document.createElement("div");
      top.className = "aw-item-top";
      top.innerHTML = `<span class="aw-mono">${name}</span><span>${workers.length} workers</span>`;
      const body = document.createElement("div");
      body.textContent = workers.map((w) => `${w.worker_id}:${w.profile_id}`).join(", ");
      const actions = document.createElement("div");
      actions.className = "aw-item-actions";
      const useBtn = document.createElement("button");
      useBtn.className = "aw-btn";
      useBtn.textContent = "Use in Auto Run";
      useBtn.addEventListener("click", () => {
        setWorkflowUiState(ctx, { multiAgentWorkers: workers });
        statusNode.textContent = `Selected team '${name}' for auto-run.`;
      });
      actions.appendChild(useBtn);
      row.appendChild(top);
      row.appendChild(body);
      row.appendChild(actions);
      listNode.appendChild(row);
    });
    statusNode.textContent = `Loaded ${Object.keys(teams).length} team(s).`;
  } catch (err) {
    statusNode.textContent = `Agent team load failed: ${err?.message || err}`;
  }
}

async function saveAgentTeam(ctx, payload, statusNode) {
  statusNode.textContent = "Saving agent team...";
  try {
    const data = await ctx.apiJson("/v1/agent_workflow/agents/config", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Gui-Enabled-Plugins": "agent_workflow,collab_chat",
      },
      body: payload,
    });
    if (data?.ok) {
      statusNode.textContent = "Agent team saved.";
      return true;
    }
    statusNode.textContent = "Save failed.";
    return false;
  } catch (err) {
    statusNode.textContent = `Save failed: ${err?.message || err}`;
    return false;
  }
}

function renderPanel(container, ctx) {
  ensureStyles();
  container.innerHTML = "";
  const sid = String(ctx?.state?.ui?.activeSid || "");

  const root = document.createElement("div");
  root.className = "aw-root";
  const tabs = document.createElement("div");
  tabs.className = "aw-tabs";
  const tabWorkflowBtn = document.createElement("button");
  tabWorkflowBtn.className = "aw-tab-btn active";
  tabWorkflowBtn.textContent = "Workflow";
  const tabFeedbackBtn = document.createElement("button");
  tabFeedbackBtn.className = "aw-tab-btn";
  tabFeedbackBtn.textContent = "Feedback";
  const tabProfilesBtn = document.createElement("button");
  tabProfilesBtn.className = "aw-tab-btn";
  tabProfilesBtn.textContent = "Profiles & Agents";
  tabs.appendChild(tabWorkflowBtn);
  tabs.appendChild(tabFeedbackBtn);
  tabs.appendChild(tabProfilesBtn);
  root.appendChild(tabs);

  const paneWorkflow = document.createElement("div");
  paneWorkflow.className = "aw-tab-pane active";
  const paneFeedback = document.createElement("div");
  paneFeedback.className = "aw-tab-pane";
  const paneProfiles = document.createElement("div");
  paneProfiles.className = "aw-tab-pane";

  const cardForm = document.createElement("div");
  cardForm.className = "aw-card";
  cardForm.innerHTML = `
    <div class="aw-title">Capture Workflow Feedback</div>
    <div class="aw-row">
      <div class="aw-col"><label>Auto Index Repo for Chat</label><select id="aw-auto-index-repo"><option value="true">enabled (recommended)</option><option value="false">disabled</option></select></div>
      <div class="aw-col"><label>Require Approval</label><select id="aw-require-approval"><option value="false">disabled (default)</option><option value="true">enabled</option></select></div>
    </div>
    <div class="aw-col"><label>Target Repo Root (optional)</label><input id="aw-target-repo-root" placeholder="my_repo or repos/my_repo" /></div>
    <div class="aw-actions">
      <button class="aw-btn" id="aw-target-repo-browse">Browse Folder...</button>
    </div>
    <div class="aw-status" id="aw-target-repo-status"></div>
    <div class="aw-item">
      <div class="aw-item-top"><span>Index Status</span><span id="aw-index-status-badge">idle</span></div>
      <div id="aw-index-status-body" class="aw-mono">No index runs yet.</div>
    </div>
    <div class="aw-row">
      <div class="aw-col"><label>Workflow ID (optional)</label><input id="aw-workflow-id" placeholder="wf_..." /></div>
      <div class="aw-col"><label>Correction Type</label>
        <select id="aw-correction-type">
          <option value="wrong_file">wrong_file</option>
          <option value="wrong_function">wrong_function</option>
          <option value="wrong_workflow">wrong_workflow</option>
          <option value="missing_dependency">missing_dependency</option>
          <option value="bad_patch_location">bad_patch_location</option>
        </select>
      </div>
    </div>
    <div class="aw-col"><label>Pattern</label><input id="aw-pattern" placeholder="auth_projects JS login" /></div>
    <div class="aw-row">
      <div class="aw-col"><label>Workflow Family (optional)</label>
        <select id="aw-workflow-family">
          <option value="">(auto)</option>
          <option value="feature">feature</option>
          <option value="bugfix">bugfix</option>
          <option value="review">review</option>
          <option value="qa_release">qa_release</option>
          <option value="learning_feedback">learning_feedback</option>
        </select>
      </div>
      <div class="aw-col"><label>Preferred Files (comma-separated)</label><input id="aw-preferred-files" placeholder="gui_js/plugins/auth_projects/plugin.js" /></div>
    </div>
    <div class="aw-col"><label>Avoid Rules (comma-separated)</label><input id="aw-avoid" placeholder="hardcoding plugin logic into framework" /></div>
    <div class="aw-col"><label>Notes</label><textarea id="aw-notes" placeholder="What should change next time"></textarea></div>
    <div class="aw-actions">
      <button class="aw-btn primary" id="aw-submit">Submit Feedback</button>
    </div>
    <div class="aw-row">
      <div class="aw-col"><label>Pending Approval Workflow ID</label><input id="aw-approval-workflow-id" placeholder="wf_..." /></div>
      <div class="aw-col"><label>Node ID</label><input id="aw-approval-node-id" value="approval_1" /></div>
    </div>
    <div class="aw-col"><label>Approval Notes (optional)</label><input id="aw-approval-notes" placeholder="optional notes" /></div>
    <div class="aw-actions">
      <button class="aw-btn primary" id="aw-approval-approve">Approve</button>
      <button class="aw-btn" id="aw-approval-reject">Reject</button>
      <button class="aw-btn" id="aw-approval-revise">Revise</button>
    </div>
    <div class="aw-status" id="aw-approval-status"></div>
    <div class="aw-status" id="aw-submit-status"></div>
  `;

  const cardList = document.createElement("div");
  cardList.className = "aw-card";
  cardList.innerHTML = `
    <div class="aw-title">Learning History</div>
    <div class="aw-actions">
      <button class="aw-btn" id="aw-refresh">Refresh</button>
    </div>
    <div class="aw-status" id="aw-load-status"></div>
    <div class="aw-list" id="aw-list"></div>
  `;

  const cardTrace = document.createElement("div");
  cardTrace.className = "aw-card";
  cardTrace.innerHTML = `
    <div class="aw-title">Workflow Trace</div>
    <div class="aw-row">
      <div class="aw-col"><label>Workflow ID</label><input id="aw-trace-workflow-id" placeholder="wf_..." /></div>
      <div class="aw-col">
        <label>&nbsp;</label>
        <div class="aw-actions"><button class="aw-btn" id="aw-trace-load">Load Trace</button></div>
      </div>
    </div>
    <div class="aw-status" id="aw-trace-status"></div>
    <div class="aw-list" id="aw-trace-list"></div>
  `;

  const cardStepDetails = document.createElement("div");
  cardStepDetails.className = "aw-card";
  cardStepDetails.innerHTML = `
    <div class="aw-title">Step Details</div>
    <div class="aw-actions">
      <button class="aw-btn" id="aw-step-details-refresh">Refresh</button>
    </div>
    <div class="aw-status" id="aw-step-details-status"></div>
    <div class="aw-list" id="aw-step-details-list"></div>
  `;

  const cardProfiles = document.createElement("div");
  cardProfiles.className = "aw-card";
  cardProfiles.innerHTML = `
    <div class="aw-title">Profile Teams</div>
    <div class="aw-actions">
      <button class="aw-btn" id="aw-profiles-refresh">Refresh</button>
    </div>
    <div class="aw-row">
      <div class="aw-col"><label>Select Team</label><select id="aw-team-select"></select></div>
      <div class="aw-col"><label>Team Members CSV</label><input id="aw-team-members" placeholder="product,architect,staff_engineer,qa,docs" /></div>
    </div>
    <div class="aw-actions">
      <button class="aw-btn" id="aw-team-load">Load Team</button>
      <button class="aw-btn primary" id="aw-team-save">Save Team</button>
    </div>
    <div class="aw-status" id="aw-team-status"></div>
    <div class="aw-item"><div class="aw-mono" id="aw-team-profiles">No team selected.</div></div>
    <div class="aw-status" id="aw-profiles-status"></div>
    <div class="aw-list" id="aw-profiles-list"></div>
  `;

  const profileManageCard = document.createElement("div");
  profileManageCard.className = "aw-card";
  profileManageCard.innerHTML = `
    <div class="aw-title">Add/Update Profile JSON</div>
    <div class="aw-row">
      <div class="aw-col"><label>File Name</label><input id="aw-prof-file" placeholder="custom_profiles.json" /></div>
      <div class="aw-col"><label>Profile ID</label><input id="aw-prof-id" placeholder="my_debugger" /></div>
    </div>
    <div class="aw-row">
      <div class="aw-col"><label>Profile Label</label><input id="aw-prof-label" placeholder="My Debugger" /></div>
      <div class="aw-col"><label>Profile Description</label><input id="aw-prof-desc" placeholder="Profile purpose" /></div>
    </div>
    <div class="aw-col"><label>Rules JSON (array)</label><textarea id="aw-prof-rules" placeholder='[{"when_any":["error"],"finding":"...","recommendation":"..."}]'></textarea></div>
    <div class="aw-row">
      <div class="aw-col"><label>Team Name (optional)</label><input id="aw-prof-team-name" placeholder="bugfix" /></div>
      <div class="aw-col"><label>Team Members CSV (optional)</label><input id="aw-prof-team-members" placeholder="staff_engineer,security,qa,my_debugger" /></div>
    </div>
    <div class="aw-actions"><button class="aw-btn primary" id="aw-prof-save">Save Profile/Team</button></div>
    <div class="aw-status" id="aw-prof-save-status"></div>
  `;
  const reviewerProfilesCard = document.createElement("div");
  reviewerProfilesCard.className = "aw-card";
  reviewerProfilesCard.innerHTML = `
    <div class="aw-title">Reviewer Profiles (Active)</div>
    <div class="aw-actions"><button class="aw-btn" id="aw-prof-catalog-refresh">Refresh</button></div>
    <div class="aw-status" id="aw-prof-catalog-status"></div>
    <div class="aw-list" id="aw-prof-catalog-list"></div>
  `;
  const profileFilesCard = document.createElement("div");
  profileFilesCard.className = "aw-card";
  profileFilesCard.innerHTML = `
    <div class="aw-title">Profile Files</div>
    <div class="aw-actions"><button class="aw-btn" id="aw-prof-files-refresh">Refresh</button></div>
    <div class="aw-status" id="aw-prof-files-status"></div>
    <div class="aw-list" id="aw-prof-files-list"></div>
  `;
  const agentManageCard = document.createElement("div");
  agentManageCard.className = "aw-card";
  agentManageCard.innerHTML = `
    <div class="aw-title">Add/Update Agent Team</div>
    <div class="aw-row">
      <div class="aw-col"><label>Team Name</label><input id="aw-agent-team-name" placeholder="backend_specialists" /></div>
      <div class="aw-col"><label>Workers JSON Array</label><textarea id="aw-agent-workers" placeholder='[{"worker_id":"w1","profile_id":"staff_engineer","responsibility":"patch"}]'></textarea></div>
    </div>
    <div class="aw-actions"><button class="aw-btn primary" id="aw-agent-save">Save Agent Team</button></div>
    <div class="aw-status" id="aw-agent-save-status"></div>
  `;
  const agentTeamsCard = document.createElement("div");
  agentTeamsCard.className = "aw-card";
  agentTeamsCard.innerHTML = `
    <div class="aw-title">Agent Teams</div>
    <div class="aw-actions"><button class="aw-btn" id="aw-agent-refresh">Refresh</button></div>
    <div class="aw-status" id="aw-agent-status"></div>
    <div class="aw-list" id="aw-agent-list"></div>
  `;

  paneWorkflow.appendChild(cardForm);
  paneWorkflow.appendChild(cardStepDetails);
  paneFeedback.appendChild(cardList);
  paneFeedback.appendChild(cardTrace);
  paneProfiles.appendChild(cardProfiles);
  paneProfiles.appendChild(profileManageCard);
  paneProfiles.appendChild(reviewerProfilesCard);
  paneProfiles.appendChild(profileFilesCard);
  paneProfiles.appendChild(agentManageCard);
  paneProfiles.appendChild(agentTeamsCard);

  root.appendChild(paneWorkflow);
  root.appendChild(paneFeedback);
  root.appendChild(paneProfiles);
  container.appendChild(root);

  const form = {
    autoIndexRepo: cardForm.querySelector("#aw-auto-index-repo"),
    targetRepoRoot: cardForm.querySelector("#aw-target-repo-root"),
    requireApproval: cardForm.querySelector("#aw-require-approval"),
    workflowId: cardForm.querySelector("#aw-workflow-id"),
    correctionType: cardForm.querySelector("#aw-correction-type"),
    pattern: cardForm.querySelector("#aw-pattern"),
    workflowFamily: cardForm.querySelector("#aw-workflow-family"),
    preferredFiles: cardForm.querySelector("#aw-preferred-files"),
    avoid: cardForm.querySelector("#aw-avoid"),
    notes: cardForm.querySelector("#aw-notes"),
  };
  const submitBtn = cardForm.querySelector("#aw-submit");
  const targetRepoBrowseBtn = cardForm.querySelector("#aw-target-repo-browse");
  const targetRepoStatus = cardForm.querySelector("#aw-target-repo-status");
  const indexStatusBadge = cardForm.querySelector("#aw-index-status-badge");
  const indexStatusBody = cardForm.querySelector("#aw-index-status-body");
  const approvalWorkflowId = cardForm.querySelector("#aw-approval-workflow-id");
  const approvalNodeId = cardForm.querySelector("#aw-approval-node-id");
  const approvalNotes = cardForm.querySelector("#aw-approval-notes");
  const approvalApproveBtn = cardForm.querySelector("#aw-approval-approve");
  const approvalRejectBtn = cardForm.querySelector("#aw-approval-reject");
  const approvalReviseBtn = cardForm.querySelector("#aw-approval-revise");
  const approvalStatus = cardForm.querySelector("#aw-approval-status");
  const submitStatus = cardForm.querySelector("#aw-submit-status");
  const stepDetailsRefreshBtn = cardStepDetails.querySelector("#aw-step-details-refresh");
  const stepDetailsStatus = cardStepDetails.querySelector("#aw-step-details-status");
  const stepDetailsList = cardStepDetails.querySelector("#aw-step-details-list");
  const refreshBtn = cardList.querySelector("#aw-refresh");
  const loadStatus = cardList.querySelector("#aw-load-status");
  const listNode = cardList.querySelector("#aw-list");
  const traceWorkflowId = cardTrace.querySelector("#aw-trace-workflow-id");
  const traceLoadBtn = cardTrace.querySelector("#aw-trace-load");
  const traceStatus = cardTrace.querySelector("#aw-trace-status");
  const traceList = cardTrace.querySelector("#aw-trace-list");
  const profilesRefreshBtn = cardProfiles.querySelector("#aw-profiles-refresh");
  const teamSelect = cardProfiles.querySelector("#aw-team-select");
  const teamMembers = cardProfiles.querySelector("#aw-team-members");
  const teamLoadBtn = cardProfiles.querySelector("#aw-team-load");
  const teamSaveBtn = cardProfiles.querySelector("#aw-team-save");
  const teamStatus = cardProfiles.querySelector("#aw-team-status");
  const teamProfiles = cardProfiles.querySelector("#aw-team-profiles");
  const profilesStatus = cardProfiles.querySelector("#aw-profiles-status");
  const profilesList = cardProfiles.querySelector("#aw-profiles-list");
  const profFile = profileManageCard.querySelector("#aw-prof-file");
  const profId = profileManageCard.querySelector("#aw-prof-id");
  const profLabel = profileManageCard.querySelector("#aw-prof-label");
  const profDesc = profileManageCard.querySelector("#aw-prof-desc");
  const profRules = profileManageCard.querySelector("#aw-prof-rules");
  const profTeamName = profileManageCard.querySelector("#aw-prof-team-name");
  const profTeamMembers = profileManageCard.querySelector("#aw-prof-team-members");
  const profSaveBtn = profileManageCard.querySelector("#aw-prof-save");
  const profSaveStatus = profileManageCard.querySelector("#aw-prof-save-status");
  const profFilesRefresh = profileFilesCard.querySelector("#aw-prof-files-refresh");
  const profFilesStatus = profileFilesCard.querySelector("#aw-prof-files-status");
  const profFilesList = profileFilesCard.querySelector("#aw-prof-files-list");
  const profCatalogRefresh = reviewerProfilesCard.querySelector("#aw-prof-catalog-refresh");
  const profCatalogStatus = reviewerProfilesCard.querySelector("#aw-prof-catalog-status");
  const profCatalogList = reviewerProfilesCard.querySelector("#aw-prof-catalog-list");
  const agentTeamName = agentManageCard.querySelector("#aw-agent-team-name");
  const agentWorkers = agentManageCard.querySelector("#aw-agent-workers");
  const agentSaveBtn = agentManageCard.querySelector("#aw-agent-save");
  const agentSaveStatus = agentManageCard.querySelector("#aw-agent-save-status");
  const agentRefreshBtn = agentTeamsCard.querySelector("#aw-agent-refresh");
  const agentStatus = agentTeamsCard.querySelector("#aw-agent-status");
  const agentList = agentTeamsCard.querySelector("#aw-agent-list");
  function pickProfileForEdit(pid, p) {
    [paneWorkflow, paneFeedback, paneProfiles].forEach((x) => x.classList.remove("active"));
    [tabWorkflowBtn, tabFeedbackBtn, tabProfilesBtn].forEach((x) => x.classList.remove("active"));
    paneProfiles.classList.add("active");
    tabProfilesBtn.classList.add("active");
    profFile.value = "custom_profiles.json";
    profId.value = String(pid || "");
    profLabel.value = String(p?.label || pid || "");
    profDesc.value = String(p?.description || "");
    profRules.value = "[]";
    profSaveStatus.textContent = `Loaded ${pid} into form. Add rules JSON and save as override.`;
    profId.focus?.();
    profileManageCard.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  const uiState = getWorkflowUiState(ctx);
  const refreshIndexStatus = () => {
    const s = getWorkflowUiState(ctx);
    const ts = Number(s.lastIndexTs || 0);
    const when = ts ? new Date(ts).toLocaleString() : "-";
    const status = String(s.lastIndexStatus || "idle");
    const err = String(s.lastIndexError || "");
    indexStatusBadge.textContent = status;
    indexStatusBody.textContent = `root: ${s.lastIndexRoot || "-"} | last: ${when}${err ? ` | error: ${err}` : ""}`;
  };
  refreshIndexStatus();
  form.autoIndexRepo.value = uiState.autoIndexRepo ? "true" : "false";
  form.targetRepoRoot.value = uiState.targetRepoRoot || "";
  form.requireApproval.value = uiState.requireApproval ? "true" : "false";
  form.autoIndexRepo.addEventListener("change", () => {
    setWorkflowUiState(ctx, { autoIndexRepo: form.autoIndexRepo.value === "true" });
  });
  form.targetRepoRoot.addEventListener("change", () => {
    const nextRoot = String(form.targetRepoRoot.value || "").trim();
    const prevRoot = String(getWorkflowUiState(ctx).targetRepoRoot || "").trim();
    setWorkflowUiState(ctx, {
      targetRepoRoot: nextRoot,
      ...(nextRoot !== prevRoot ? { repoContextJson: "", repoRagHitsJson: "[]", lastIndexStatus: "", lastIndexError: "" } : {}),
    });
    if (nextRoot) void scheduleRepoWarmup(ctx, { root: nextRoot });
  });
  targetRepoBrowseBtn.addEventListener("click", async () => {
    try {
      targetRepoStatus.textContent = "Loading workspace folders...";
      const picked = await pickWorkspaceFolder(ctx);
      if (!picked) {
        targetRepoStatus.textContent = "Folder selection cancelled.";
        return;
      }
      form.targetRepoRoot.value = picked;
      const prevRoot = String(getWorkflowUiState(ctx).targetRepoRoot || "").trim();
      setWorkflowUiState(ctx, {
        targetRepoRoot: picked,
        ...(picked !== prevRoot ? { repoContextJson: "", repoRagHitsJson: "[]", lastIndexStatus: "", lastIndexError: "" } : {}),
      });
      void scheduleRepoWarmup(ctx, { root: picked });
      targetRepoStatus.textContent = `Target Repo Root set to '${picked}'.`;
      refreshIndexStatus();
    } catch (err) {
      targetRepoStatus.textContent = `Folder picker failed: ${err?.message || err}`;
    }
  });
  form.requireApproval.addEventListener("change", () => {
    setWorkflowUiState(ctx, { requireApproval: form.requireApproval.value === "true" });
  });

  submitBtn.addEventListener("click", () => submitFeedback(ctx, form, submitStatus).then(() => loadLearning(ctx, listNode, loadStatus)));
  const pendingFromState = uiState.pendingApproval;
  if (pendingFromState && pendingFromState.workflow_id) {
    approvalWorkflowId.value = String(pendingFromState.workflow_id || "");
    approvalNodeId.value = String(pendingFromState.node_id || "approval_1");
    approvalStatus.textContent = "Pending approval detected from last run.";
  }
  approvalApproveBtn.addEventListener("click", () =>
    sendApprovalDecision(
      ctx,
      { workflow_id: approvalWorkflowId.value, node_id: approvalNodeId.value, action: "approve", notes: approvalNotes.value },
      approvalStatus
    )
  );
  approvalRejectBtn.addEventListener("click", () =>
    sendApprovalDecision(
      ctx,
      { workflow_id: approvalWorkflowId.value, node_id: approvalNodeId.value, action: "reject", notes: approvalNotes.value },
      approvalStatus
    )
  );
  approvalReviseBtn.addEventListener("click", () =>
    sendApprovalDecision(
      ctx,
      { workflow_id: approvalWorkflowId.value, node_id: approvalNodeId.value, action: "revise", notes: approvalNotes.value },
      approvalStatus
    )
  );
  refreshBtn.addEventListener("click", () => loadLearning(ctx, listNode, loadStatus));
  stepDetailsRefreshBtn.addEventListener("click", () => renderStepDetailsFromSession(ctx, sid, stepDetailsList, stepDetailsStatus));
  traceLoadBtn.addEventListener("click", () =>
    loadTrace(ctx, traceWorkflowId.value, traceList, traceStatus, (entry) => {
      form.workflowId.value = traceWorkflowId.value.trim();
      form.pattern.value = `${entry.stage || ""} ${entry.event_type || ""} ${entry.message || ""}`.trim();
      form.correctionType.value = "wrong_workflow";
      form.notes.value = String(entry.message || "");
      submitStatus.textContent = "Feedback form prefilled from trace entry.";
    })
  );
  profilesRefreshBtn.addEventListener("click", () =>
    loadProfiles(ctx, profilesList, profilesStatus, { selectNode: teamSelect, membersNode: teamMembers, teamStatusNode: teamStatus, teamProfilesNode: teamProfiles })
  );
  teamLoadBtn.addEventListener("click", () =>
    loadProfiles(ctx, profilesList, profilesStatus, { selectNode: teamSelect, membersNode: teamMembers, teamStatusNode: teamStatus, teamProfilesNode: teamProfiles })
  );
  teamSelect.addEventListener("change", () =>
    loadProfiles(ctx, profilesList, profilesStatus, { selectNode: teamSelect, membersNode: teamMembers, teamStatusNode: teamStatus, teamProfilesNode: teamProfiles })
  );
  teamSaveBtn.addEventListener("click", async () => {
    const tn = String(teamSelect.value || "").trim();
    if (!tn) {
      teamStatus.textContent = "Select or create a team name first.";
      return;
    }
    const payload = {
      file_name: String(profFile.value || "custom_profiles.json").trim() || "custom_profiles.json",
      team_name: tn,
      team_members: parseCsv(teamMembers.value),
    };
    const ok = await upsertProfileAndTeam(ctx, payload, teamStatus);
    if (ok) {
      await loadProfiles(ctx, profilesList, profilesStatus, { selectNode: teamSelect, membersNode: teamMembers, teamStatusNode: teamStatus, teamProfilesNode: teamProfiles });
    }
  });
  profFilesRefresh.addEventListener("click", () => loadProfileFiles(ctx, profFilesList, profFilesStatus));
  profCatalogRefresh.addEventListener("click", () =>
    loadProfileCatalog(ctx, profCatalogList, profCatalogStatus, (pid, p) => pickProfileForEdit(pid, p))
  );
  profSaveBtn.addEventListener("click", async () => {
    let rules;
    try {
      rules = JSON.parse(String(profRules.value || "[]"));
    } catch (err) {
      profSaveStatus.textContent = `Invalid rules JSON: ${err?.message || err}`;
      return;
    }
    const payload = {
      file_name: String(profFile.value || "custom_profiles.json").trim(),
      profile_id: String(profId.value || "").trim(),
      profile: {
        label: String(profLabel.value || "").trim(),
        phase: "review",
        description: String(profDesc.value || "").trim(),
        rules: Array.isArray(rules) ? rules : [],
      },
    };
    const tn = String(profTeamName.value || "").trim();
    if (tn) {
      payload.team_name = tn;
      payload.team_members = parseCsv(profTeamMembers.value);
    }
    const ok = await upsertProfileAndTeam(ctx, payload, profSaveStatus);
    if (ok) {
      loadProfiles(ctx, profilesList, profilesStatus, { selectNode: teamSelect, membersNode: teamMembers, teamStatusNode: teamStatus, teamProfilesNode: teamProfiles });
      loadProfileFiles(ctx, profFilesList, profFilesStatus);
      loadProfileCatalog(ctx, profCatalogList, profCatalogStatus, (pid, p) => pickProfileForEdit(pid, p));
    }
  });
  agentSaveBtn.addEventListener("click", async () => {
    let workers;
    try {
      workers = JSON.parse(String(agentWorkers.value || "[]"));
    } catch (err) {
      agentSaveStatus.textContent = `Invalid workers JSON: ${err?.message || err}`;
      return;
    }
    const payload = { team_name: String(agentTeamName.value || "").trim(), workers: Array.isArray(workers) ? workers : [] };
    const ok = await saveAgentTeam(ctx, payload, agentSaveStatus);
    if (ok) loadAgentTeams(ctx, agentList, agentStatus);
  });
  agentRefreshBtn.addEventListener("click", () => loadAgentTeams(ctx, agentList, agentStatus));

  function showPane(target) {
    [paneWorkflow, paneFeedback, paneProfiles].forEach((p) => p.classList.remove("active"));
    [tabWorkflowBtn, tabFeedbackBtn, tabProfilesBtn].forEach((b) => b.classList.remove("active"));
    if (target === "workflow") {
      paneWorkflow.classList.add("active");
      tabWorkflowBtn.classList.add("active");
      return;
    }
    if (target === "feedback") {
      paneFeedback.classList.add("active");
      tabFeedbackBtn.classList.add("active");
      return;
    }
    paneProfiles.classList.add("active");
    tabProfilesBtn.classList.add("active");
  }
  tabWorkflowBtn.addEventListener("click", () => showPane("workflow"));
  tabFeedbackBtn.addEventListener("click", () => showPane("feedback"));
  tabProfilesBtn.addEventListener("click", () => showPane("profiles"));

  loadLearning(ctx, listNode, loadStatus);
  renderStepDetailsFromSession(ctx, sid, stepDetailsList, stepDetailsStatus);
  loadProfiles(ctx, profilesList, profilesStatus, { selectNode: teamSelect, membersNode: teamMembers, teamStatusNode: teamStatus, teamProfilesNode: teamProfiles });
  loadProfileFiles(ctx, profFilesList, profFilesStatus);
  loadProfileCatalog(ctx, profCatalogList, profCatalogStatus, (pid, p) => pickProfileForEdit(pid, p));
  loadAgentTeams(ctx, agentList, agentStatus);
}

function buildDevPipelineImportPayload() {
  const flowName = "workflow_dev_pipeline";
  const taggedBuildProtocol = [
    "For create/build implementation tasks, prefer the TAGGED protocol instead of JSON tool_calls for large artifacts.",
    "Emit tagged sections exactly like this when writing a file:",
    "<<<AW_SUMMARY>>> ... <<<END_AW_SUMMARY>>>",
    "<<<AW_PLAN>>> ... <<<END_AW_PLAN>>>",
    "<<<AW_ANALYSIS>>> ... <<<END_AW_ANALYSIS>>>",
    "<<<AW_RESPONSE>>> ... <<<END_AW_RESPONSE>>>",
    "<<<AW_ACTIONS>>>",
    "- item",
    "<<<END_AW_ACTIONS>>>",
    "<<<AW_HANDOFF>>> ... <<<END_AW_HANDOFF>>>",
    "<<<AW_TOOL_CALL>>>",
    "skill: code.apply_patch",
    "reason: Create or update the artifact",
    "path: relative/file.html",
    "op: write",
    "<<<AW_CONTENT>>>",
    "raw file content here",
    "<<<END_AW_CONTENT>>>",
    "<<<END_AW_TOOL_CALL>>>",
    "For large files, emit additional <<<AW_TOOL_CALL>>> blocks with op: append for continuation chunks.",
    "Do not wrap tagged output in markdown fences.",
  ].join("\n");
  const rolePrompt = (rid, label) => {
    const base = `You are the ${label} (${rid}). Do your role and handoff clearly.`;
    if (["staff_engineer", "coder", "gui_designer"].includes(String(rid || ""))) return `${base}\n${taggedBuildProtocol}`;
    if (["qa", "security", "docs", "release", "architect"].includes(String(rid || ""))) return `${base}\nIf no artifact has been written yet, do not pretend to verify it. State that implementation must create it first.`;
    return base;
  };
  const roleCfg = {
    product: { label: "Product", skills: ["auth.project_context", "repo.context", "repo.read", "learning.get_hints"] },
    gui_designer: { label: "GUI Designer", skills: ["repo.context", "repo.read", "rag.search", "learning.get_hints"] },
    architect: { label: "Architect", skills: ["repo.tree", "repo.context", "repo.read", "rag.search"] },
    staff_engineer: { label: "Staff Engineer", skills: ["repo.tree", "repo.read", "repo.write", "rag.search", "code.generate_patch_candidates", "code.apply_patch", "tests.run_project"] },
    coder: { label: "Coding Engineer", skills: ["repo.tree", "repo.read", "repo.write", "rag.search", "code.generate_patch_candidates", "code.apply_patch"] },
    qa: { label: "QA Reviewer", skills: ["repo.read", "tests.run_project", "tests.smoke", "debug.fix_from_errors"] },
    security: { label: "Security Reviewer", skills: ["repo.tree", "repo.read", "rag.search"] },
    docs: { label: "Docs Reviewer", skills: ["repo.context", "repo.read", "learning.get_hints"] },
    release: { label: "Release Reviewer", skills: ["repo.read", "repo.write", "tests.run_project", "learning.list"] },
  };
  const teamSubflows = [
    { subflow: "workflow_team_discovery", label: "Discovery Team", members: ["product", "gui_designer", "architect"] },
    { subflow: "workflow_team_build", label: "Build Team", members: ["staff_engineer", "coder", "gui_designer"] },
    { subflow: "workflow_team_quality", label: "Quality Team", members: ["qa", "security", "docs"] },
    { subflow: "workflow_team_release", label: "Release Team", members: ["release", "staff_engineer", "qa", "docs"] },
  ];
  const subflowTransitions = (subflowName, rid, sidNext) => {
    if (subflowName === "workflow_team_release" && rid === "qa") {
      return [
        { condition: { type: "test_failures_gte", value: "1" }, target: "n2", loop_max_passes: 2, system_prompt: "Release QA found test failures. Repair the implementation before returning to QA." },
        ...(sidNext ? [{ condition: { type: "always" }, target: sidNext }] : []),
      ];
    }
    if (subflowName === "workflow_team_release" && rid === "docs" && !sidNext) {
      return [
        { condition: { type: "bugs_present" }, target: "n2", loop_max_passes: 2, system_prompt: "Release review found remaining issues. Fix them before closing release." },
        { condition: { type: "no_changed_files" }, target: "n2", loop_max_passes: 2, system_prompt: "Release review found that no files were actually changed. Make the required implementation edits now." },
      ];
    }
    if (subflowName === "workflow_team_quality" && rid === "docs" && !sidNext) {
      return [
        { condition: { type: "bugs_present" }, target: "n1", loop_max_passes: 1, system_prompt: "Quality review found unresolved issues. Re-run the quality pass with those issues addressed." },
      ];
    }
    return sidNext ? [{ condition: { type: "always" }, target: sidNext }] : [];
  };
  const topLevelTransitions = (team, nextTop) => {
    if (team.subflow === "workflow_team_quality") {
      return [
        {
          condition: { operator: "any", rules: [{ type: "bugs_present" }, { type: "test_failures_gte", value: "1" }] },
          target: "n2",
          loop_max_passes: 2,
          system_prompt: "Quality Team found bugs or test failures. Re-enter Build Team and repair the implementation before continuing.",
        },
        ...(nextTop ? [{ condition: { type: "always" }, target: nextTop }] : []),
      ];
    }
    return nextTop ? [{ condition: { type: "always" }, target: nextTop }] : [];
  };
  const topNodes = {};
  const allFlows = {};
  for (let i = 0; i < teamSubflows.length; i += 1) {
    const t = teamSubflows[i];
    const topNodeId = `n${i + 1}`;
    const nextTop = i + 1 < teamSubflows.length ? `n${i + 2}` : "";
    const subNodes = {};
    for (let j = 0; j < t.members.length; j += 1) {
      const rid = String(t.members[j] || "").trim();
      const rc = roleCfg[rid];
      if (!rc) continue;
      const sidN = `n${j + 1}`;
      const sidNext = j + 1 < t.members.length ? `n${j + 2}` : "";
        subNodes[sidN] = {
        label: rc.label,
        plugin_id: "agent_workflow_member",
        agent_kind: rid,
        system_prompt: rolePrompt(rid, rc.label),
        x: 80 + (j % 3) * 290,
        y: 80 + Math.floor(j / 3) * 170,
        delay_ms: 0,
        return_only_text: true,
          transitions: subflowTransitions(t.subflow, rid, sidNext),
        plugin_settings: {
          member_role: rid,
          handoff_format: "plain",
          output_protocol: "tagged",
          member_token_stream: true,
          action_skills: rc.skills,
        },
      };
    }
    allFlows[t.subflow] = { start: "n1", nodes: subNodes };
      topNodes[topNodeId] = {
      label: t.label,
      plugin_id: "agent_flow_subflow",
      agent_kind: "subflow",
      system_prompt: "",
      x: 80 + (i % 3) * 290,
      y: 80 + Math.floor(i / 3) * 170,
      delay_ms: 0,
      return_only_text: true,
        transitions: topLevelTransitions(t, nextTop),
        plugin_settings: {
          subflow_name: t.subflow,
        },
      };
  }
  allFlows[flowName] = { start: "n1", nodes: topNodes };
  return { flows: allFlows, default_flow: flowName, active_flow: flowName, mode: "execute", max_steps: 24 };
}

function buildRepoImprovementImportPayload() {
  const flowName = "workflow_repo_improvement";
  const nodes = {
    n1: {
      label: "Repo Analyst",
      plugin_id: "agent_workflow_member",
      agent_kind: "architect",
      system_prompt: [
        "You are the Repo Analyst.",
        "Read the repo relevant to the user request.",
        "If the user names a specific plugin, folder, or file, inspect that exact path first instead of scanning broadly.",
        "If repo knowledge may be stale or the user points to specific folders/files, request repo.ingest for those targets before relying on RAG results.",
        "Use repo.tree, repo.context, repo.read, and rag.search to find the right files quickly.",
        "Summarize the relevant architecture, likely change points, and concrete implementation handoff for engineering.",
        "Do not claim code changes unless you actually invoke write-capable tools.",
      ].join("\n"),
      x: 80,
      y: 80,
      delay_ms: 0,
      return_only_text: true,
      transitions: [{ condition: { type: "always" }, target: "n2" }],
      plugin_settings: {
        member_role: "architect",
        handoff_format: "plain",
        output_protocol: "tagged",
        member_token_stream: true,
        action_skills: ["repo.tree", "repo.context", "repo.read", "repo.ingest", "rag.search"],
      },
    },
    n2: {
      label: "Coding Engineer",
      plugin_id: "agent_workflow_member",
      agent_kind: "coder",
      system_prompt: [
        "You are the Coding Engineer.",
        "Use the repo analysis and handoff to implement the requested improvement or bug fix.",
        "If the user named a plugin, folder, or file, inspect and edit that real repo path.",
        "Prefer precise file edits over broad rewrites.",
        "Do not create standalone artifact files for repo-edit tasks.",
        "If creating or modifying code, emit write-capable tool calls and keep changes scoped to the request.",
      ].join("\n"),
      x: 380,
      y: 80,
      delay_ms: 0,
      return_only_text: true,
      transitions: [{ condition: { type: "always" }, target: "n3" }],
      plugin_settings: {
        member_role: "coder",
        handoff_format: "plain",
        output_protocol: "tagged",
        member_token_stream: true,
        action_skills: ["repo.read", "repo.write", "repo.ingest", "rag.search", "code.generate_patch_candidates", "code.apply_patch", "debug.fix_from_errors"],
      },
    },
    n3: {
      label: "Release Engineer",
      plugin_id: "agent_workflow_member",
      agent_kind: "staff_engineer",
      system_prompt: [
        "You are the Release Engineer.",
        "This is the final repair pass before QA.",
        "If no files were changed yet, you must modify the real repo file now.",
        "Prefer precise patch operations over broad rewrites.",
        "Do not create standalone artifact files for repo-edit tasks.",
      ].join("\n"),
      x: 680,
      y: 80,
      delay_ms: 0,
      return_only_text: true,
      transitions: [
        {
          condition: { type: "no_changed_files" },
          target: "n2",
          loop_max_passes: 2,
          system_prompt: "The previous review/repair pass still produced no changed files. Edit the real repo file now and keep the patch narrow.",
        },
        { condition: { type: "always" }, target: "n4" },
      ],
      plugin_settings: {
        member_role: "staff_engineer",
        handoff_format: "plain",
        output_protocol: "tagged",
        member_token_stream: true,
        action_skills: ["repo.read", "repo.write", "repo.ingest", "rag.search", "code.generate_patch_candidates", "code.apply_patch", "debug.fix_from_errors", "tests.run_project"],
      },
    },
    n4: {
      label: "QA Reviewer",
      plugin_id: "agent_workflow_member",
      agent_kind: "qa",
      system_prompt: [
        "You are the QA Reviewer.",
        "Read changed files, verify the implementation against the request, and run available smoke/project tests.",
        "Report concrete findings, test results, and any remaining risks.",
      ].join("\n"),
      x: 980,
      y: 80,
      delay_ms: 0,
      return_only_text: true,
      transitions: [
        {
          condition: { type: "bugs_present" },
          target: "n2",
          loop_max_passes: 2,
          system_prompt: "QA found concrete issues. Fix the identified bugs in the same repo files and keep the patch scoped to those findings.",
        },
        {
          condition: { type: "test_failures_gte", value: "1" },
          target: "n2",
          loop_max_passes: 2,
          system_prompt: "Tests failed. Repair the implementation, then leave the flow ready for QA to rerun verification.",
        },
      ],
      plugin_settings: {
        member_role: "qa",
        handoff_format: "plain",
        output_protocol: "tagged",
        member_token_stream: true,
        action_skills: ["repo.read", "repo.ingest", "tests.smoke", "tests.run_project", "debug.fix_from_errors"],
      },
    },
  };
  return {
    flows: {
      [flowName]: {
        start: "n1",
        nodes,
      },
    },
    default_flow: flowName,
    active_flow: flowName,
    mode: "execute",
    max_steps: 8,
  };
}


function mergeWithExistingAgentFlowImport(ctx, helpers, imp) {
  const base = imp && typeof imp === "object" ? JSON.parse(JSON.stringify(imp)) : {};
  const sid = String(helpers?.sid || ctx?.state?.ui?.activeSid || "").trim();
  const settings = ctx?.state?.router?.settings?.[sid]?.agent_flow;
  const existingFlows = settings && settings.agent_flow_flows && typeof settings.agent_flow_flows === "object"
    ? settings.agent_flow_flows
    : {};
  const incomingFlows = base.flows && typeof base.flows === "object" ? base.flows : {};
  base.flows = { ...existingFlows, ...incomingFlows };
  base.merge = true;
  base.replace = false;
  return base;
}

function createAgentFlowImportSource() {
  return {
    id: "agent_workflow_agent_flow_imports",
    type: "agent_flow_import_source",
    getEntries(ctx, helpers) {
      return [
        {
          id: "agent_workflow_one_click",
          title: "Agent Workflow: Team Import",
          description: "Import team-member nodes from Agent Workflow profiles.",
          render(node) {
            const row = document.createElement("div");
            row.className = "button-row";
            const select = document.createElement("select");
            select.className = "input";
            const btn = document.createElement("button");
            btn.className = "primary";
            btn.textContent = "Import Team";
            btn.disabled = true;
            row.appendChild(select);
            row.appendChild(btn);
            node.appendChild(row);
            const members = document.createElement("div");
            members.className = "small";
            members.textContent = "Loading teams...";
            node.appendChild(members);
            ctx.apiJson("/v1/agent_workflow/profiles", {
              method: "GET",
              headers: {
                ...helpers.buildHeaders(ctx),
                "X-Gui-Enabled-Plugins": "collab_chat,agent_flow,agent_workflow",
              },
            }).then((res) => {
              const teams = (res && typeof res === "object" && res.teams && typeof res.teams === "object") ? res.teams : {};
              select.innerHTML = "";
              Object.keys(teams).sort().forEach((t) => select.appendChild(new Option(t, t)));
              if (!select.options.length) select.appendChild(new Option("feature", "feature"));
              const renderMembers = () => {
                const k = String(select.value || "").trim();
                const rows = Array.isArray(teams[k]) ? teams[k] : [];
                members.textContent = `Team members: ${rows.length ? rows.join(", ") : "-"}`;
              };
              select.addEventListener("change", renderMembers);
              renderMembers();
              btn.disabled = false;
            }).catch(() => {
              members.textContent = "Failed to load Agent Workflow teams.";
            });
            btn.addEventListener("click", async () => {
              try {
                const team = String(select.value || "feature").trim() || "feature";
                const payload = await ctx.apiJson("/v1/agent_workflow/agent_flow_nodes", {
                  method: "POST",
                  headers: {
                    ...helpers.buildHeaders(ctx),
                    "Content-Type": "application/json",
                    "X-Gui-Enabled-Plugins": "collab_chat,agent_flow,agent_workflow",
                  },
                  body: { pid: helpers.pid, sid: helpers.sid, team, flow_name: `workflow_${team}` },
                });
                const imp = mergeWithExistingAgentFlowImport(ctx, helpers, payload?.agent_flow_import || {});
                await helpers.importFlowsFromJsonText(JSON.stringify(imp), { merge: true, replace: false });
                helpers.closePopover?.();
              } catch (err) {
                ctx.log?.(`[agent_workflow] team import failed: ${err?.message || err}`, "warn");
              }
            });
          },
        },
        {
          id: "agent_workflow_dev_pipeline",
          title: "Agent Workflow: Dev Pipeline",
          description: "Import orchestrator and team subflows for app development.",
          render(node) {
            const row = document.createElement("div");
            row.className = "button-row";
            const btn = document.createElement("button");
            btn.className = "ghost";
            btn.textContent = "Import Dev Pipeline";
            btn.addEventListener("click", async () => {
              try {
                const imp = mergeWithExistingAgentFlowImport(ctx, helpers, buildDevPipelineImportPayload());
                await helpers.importFlowsFromJsonText(JSON.stringify(imp), { merge: true, replace: false });
                helpers.closePopover?.();
              } catch (err) {
                ctx.log?.(`[agent_workflow] import development pipeline failed: ${err?.message || err}`, "warn");
              }
            });
            row.appendChild(btn);
            node.appendChild(row);
          },
        },
        {
          id: "agent_workflow_repo_improvement",
          title: "Agent Workflow: Repo Improvement",
          description: "Compact repo-reading flow: analyze with RAG, implement with engineering, then QA test.",
          render(node) {
            const row = document.createElement("div");
            row.className = "button-row";
            const btn = document.createElement("button");
            btn.className = "ghost";
            btn.textContent = "Import Repo Flow";
            btn.addEventListener("click", async () => {
              try {
                const imp = mergeWithExistingAgentFlowImport(ctx, helpers, buildRepoImprovementImportPayload());
                await helpers.importFlowsFromJsonText(JSON.stringify(imp), { merge: true, replace: false });
                helpers.closePopover?.();
              } catch (err) {
                ctx.log?.(`[agent_workflow] import repo improvement flow failed: ${err?.message || err}`, "warn");
              }
            });
            row.appendChild(btn);
            node.appendChild(row);
          },
        },
      ];
    },
  };
}

const plugin = {
  id: meta.plugin_id,
  name: meta.name,
  kind: meta.kind,
  description: meta.description,
  meta,
  register(host) {
    ensureStyles();
    host.addTopRightIconRow((ctx) => {
      startRepoWarmupObserver(ctx);
      const node = document.createElement("span");
      node.style.display = "none";
      node.setAttribute("aria-hidden", "true");
      return node;
    });
    host.shareObject(createAgentFlowImportSource());
    host.addPanelTab({
      id: meta.plugin_id,
      title: "Agent Workflow",
      windowType: "full",
      render: (container, ctx) => renderPanel(container, ctx),
    });
    host.addSendHook(sendHook);
    host.addCompletionPayloadHook((payload, ctx) => applyRepoContextToPayload(payload, ctx));
    host.addMessagePreRenderer(agentJobsPreRenderer);
    host.addMessageRenderer(renderResultFileMessage);
    host.addMessageRenderer(renderResultTextMessage);
    host.addMessageRenderer(renderAgentJobsGroup);
    host.addMessageFooterItem({ roles: ["assistant"], align: "right", render: renderAgentFlowSteerFooter });
    host.addEventHandler((event, data) => {
      if (event === "flow_status") {
        rememberAgentFlowRunState(data);
        updateVisibleAgentFlowControls(data);
      }
    });
  },
  dispose() {
    stopRepoWarmupObserver();
  },
};

export default plugin;
