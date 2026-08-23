const meta = {
  plugin_id: "auth_projects",
  name: "Auth/Projects",
  kind: "auth",
  description: "Remote login, projects/sessions, collab sync",
  has_notebook_tab: true,
};

const STYLE_ID = "auth-projects-style";
const APP_UPDATE_SLUG = "gotchat";
const APP_UPDATE_NAME = "chatchat";
let lastRenderTarget = null;
let lastRenderCtx = null;
let lastRenderHost = null;
let visibilityMenu = null;
let visibilityMenuHandler = null;
let activeAuthModals = new Set();
let bootstrapWizardChecked = false;
let bootstrapWizardInFlight = false;
let bootstrapWizardOpen = false;
let bootstrapWizardRetryTimers = [];
let coreTranscriptHydrateTimer = null;
let coreTranscriptHydrateKey = "";

const I18N_LANGUAGES = ["en", "es", "ja", "zh"];

function authT(key, fallback = "") {
  try {
    if (lastRenderHost && typeof lastRenderHost.t === "function") {
      return lastRenderHost.t(key, fallback);
    }
  } catch (_err) {}
  return String(fallback != null ? fallback : key);
}

function translateAuthNode(node) {
  try {
    if (node && lastRenderHost && typeof lastRenderHost.translateContainer === "function") {
      lastRenderHost.translateContainer(node, meta.plugin_id);
    }
  } catch (_err) {}
  return node;
}

function rerenderLastAuthPanel() {
  try {
    if (lastRenderTarget && lastRenderCtx && lastRenderHost) {
      renderPanel(lastRenderTarget, lastRenderCtx, lastRenderHost);
    }
  } catch (_err) {}
}

function logAsyncError(ctx, label, err) {
  const message = String(err?.message || err || 'unknown_error');
  try {
    ctx?.log?.(`[auth_projects] ${label}: ${message}`, 'warn');
  } catch (_err) {}
  try {
    console.warn(`[auth_projects] ${label}: ${message}`);
  } catch (_err) {}
}

function runAsyncTask(task, onError = null) {
  try {
    const result = typeof task === 'function' ? task() : task;
    if (result && typeof result.then === 'function') {
      result.catch((err) => {
        if (typeof onError === 'function') onError(err);
        else {
          try {
            console.warn('[auth_projects] async task failed', err);
          } catch (_err) {}
        }
      });
    }
    return result;
  } catch (err) {
    if (typeof onError === 'function') onError(err);
    else {
      try {
        console.warn('[auth_projects] async task failed', err);
      } catch (_err) {}
    }
    return null;
  }
}

function getCollabState(ctx) {
  ctx.state.auth_projects = ctx.state.auth_projects || {};
  ctx.state.auth_projects.collab = ctx.state.auth_projects.collab || {
    forceAiOnce: false,
    forceSystemPrompt: "",
    aiToggleBySession: {},
  };
  return ctx.state.auth_projects.collab;
}

function getAiToggleKey(pid, sid) {
  if (!pid || !sid) return "";
  return `${pid}:${sid}`;
}

function getAiToggle(ctx, pid, sid) {
  const st = getCollabState(ctx);
  const key = getAiToggleKey(pid, sid);
  if (!key) return Boolean(ctx?.getAiEnabled?.(pid, sid, true));
  const map = st.aiToggleBySession || {};
  if (Object.prototype.hasOwnProperty.call(map, key)) {
    return Boolean(map[key]);
  }
  if (typeof ctx?.getAiEnabled === "function") {
    return Boolean(ctx.getAiEnabled(pid, sid, true));
  }
  return true;
}

function setAiToggle(ctx, pid, sid, enabled) {
  const st = getCollabState(ctx);
  const key = getAiToggleKey(pid, sid);
  if (!key) return;
  st.aiToggleBySession = st.aiToggleBySession || {};
  st.aiToggleBySession[key] = Boolean(enabled);
  // Publish to the generic chat_js AI state (so other plugins can query AI state
  // without reading Auth/Projects plugin-specific state).
  try {
    ctx.state.ai = ctx.state.ai || {};
    ctx.state.ai.enabledByScope = ctx.state.ai.enabledByScope || {};
    ctx.state.ai.enabledByScope[key] = Boolean(enabled);
  } catch (_err) {}
}

function coerceBool(value, fallback = true) {
  if (value === undefined || value === null) return fallback;
  if (typeof value === "string") {
    const trimmed = value.trim().toLowerCase();
    if (trimmed === "0" || trimmed === "false" || trimmed === "no" || trimmed === "off") return false;
    if (trimmed === "1" || trimmed === "true" || trimmed === "yes" || trimmed === "on") return true;
  }
  return Boolean(value);
}


const NO_FLOW_VALUE = "__none__";
function getAiRouterBridgeState(ctx, bridge) {
  ctx.state.auth_projects = ctx.state.auth_projects || {};
  ctx.state.auth_projects.aiRouterBridgeState = ctx.state.auth_projects.aiRouterBridgeState || {};
  const key = String(bridge?.id || bridge?.routeId || "").trim();
  if (!key) return { pendingByClientMsgId: {} };
  ctx.state.auth_projects.aiRouterBridgeState[key] = ctx.state.auth_projects.aiRouterBridgeState[key] || {
    pendingByClientMsgId: {},
  };
  return ctx.state.auth_projects.aiRouterBridgeState[key];
}

function markPendingAiRouterBridge(ctx, bridge, payload) {
  const clientMsgId = String(payload?.client_msg_id || "").trim();
  if (!clientMsgId) return;
  const state = getAiRouterBridgeState(ctx, bridge);
  state.pendingByClientMsgId[clientMsgId] = {
    pid: String(payload?.pid || "").trim(),
    sid: String(payload?.sid || "").trim(),
    ts: Date.now(),
  };
}

function consumePendingAiRouterBridge(ctx, bridge, clientMsgId) {
  const key = String(clientMsgId || "").trim();
  if (!key) return null;
  const state = getAiRouterBridgeState(ctx, bridge);
  const entry = state.pendingByClientMsgId[key] || null;
  if (entry) delete state.pendingByClientMsgId[key];
  const now = Date.now();
  Object.keys(state.pendingByClientMsgId).forEach((id) => {
    const item = state.pendingByClientMsgId[id];
    if (!item || (now - Number(item.ts || 0)) > 120000) delete state.pendingByClientMsgId[id];
  });
  return entry;
}

function getAiRouterBridges(ctx) {
  const list = typeof ctx?.getAiRouterBridges === "function" ? ctx.getAiRouterBridges() : [];
  return Array.isArray(list) ? list : [];
}

async function callAiRouterBridgeTurn(payload, ctx, bridge) {
  const pid = String(payload?.pid || "").trim();
  const sid = String(payload?.sid || "").trim();
  const text = String(payload?.text || "").trim();
  const clientMsgId = String(payload?.client_msg_id || "").trim();
  if (!pid || !sid || !text) return { handled: false };
  markPendingAiRouterBridge(ctx, bridge, payload);
  if (typeof ctx.startCompletionStream === "function") {
    try {
      await ctx.startCompletionStream(pid, sid, text, clientMsgId);
      return { handled: true };
    } catch (err) {
      consumePendingAiRouterBridge(ctx, bridge, clientMsgId);
      throw err;
    }
  }
  if (typeof ctx.startModelStream === "function") {
    await ctx.startModelStream(pid, sid, text, clientMsgId);
    return { handled: true };
  }
  throw new Error(`${String(bridge?.routeId || bridge?.id || "ai_router").trim() || "ai_router"}_stream_unavailable`);
}

function ensureStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
.auth-root { display: flex; flex-direction: column; gap: 12px; }
.auth-tabs { display: flex; gap: 6px; flex-wrap: wrap; border-bottom: 1px solid var(--border); padding-bottom: 2px; }
.auth-tab { border: 1px solid transparent; border-bottom: none; background: transparent; border-radius: 10px 10px 0 0; padding: 8px 14px; cursor: pointer; font-size: 12px; color: var(--muted); }
.auth-tab.active { background: var(--panel); color: var(--ink); border-color: var(--border); border-bottom-color: transparent; box-shadow: 0 -4px 10px rgba(20, 15, 10, 0.08); }
.auth-tab:disabled { opacity: 0.5; cursor: not-allowed; }
.auth-panel { display: none; flex-direction: column; gap: 12px; }
.auth-panel.active { display: flex; }
.auth-columns { display: grid; grid-template-columns: 1fr 1.4fr; gap: 12px; }
.auth-columns,
.auth-column,
.auth-list,
.auth-request-main { min-width: 0; }
.auth-meta { font-size: 12px; color: var(--muted); white-space: pre-line; }
.auth-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.auth-inline { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.auth-subtabs { display: flex; gap: 6px; flex-wrap: wrap; border-bottom: 1px solid var(--border); padding-bottom: 2px; }
.auth-modal { position: fixed; inset: 0; background: rgba(26,22,18,0.4); display: flex; align-items: center; justify-content: center; z-index: 30; padding: 16px; overflow-y: auto; overscroll-behavior: contain; -webkit-overflow-scrolling: touch; box-sizing: border-box; }
.auth-modal.hidden { display: none; }
.auth-modal-card { background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 16px; width: 100%; max-width: 520px; max-height: calc(100dvh - 32px); overflow-y: auto; display: flex; flex-direction: column; gap: 10px; box-sizing: border-box; min-width: 0; }
.auth-column { display: flex; flex-direction: column; gap: 8px; }
.auth-list-header h2 { margin: 0; }
.auth-badge { font-size: 10px; text-transform: uppercase; letter-spacing: 1px; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--border); background: rgba(var(--panel-rgb), 0.7); }
.auth-badge.public { color: var(--accent); border-color: rgba(var(--accent-rgb), 0.3); background: rgba(var(--accent-rgb), 0.12); }
.auth-badge.private { color: var(--accent); border-color: rgba(var(--accent-rgb, 37, 99, 235), 0.35); background: rgba(var(--accent-rgb, 37, 99, 235), 0.12); }
.auth-admin-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; align-items: start; }
.auth-list.tall { min-height: 240px; }
.auth-field-spacer { margin-top: 10px; }
.auth-checkbox { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--muted); margin: 8px 0; }
.auth-checkbox input { margin: 0; }
.auth-textarea { min-height: 140px; resize: vertical; }
.auth-form-actions { margin-top: 10px; }
.auth-visibility-menu { position: fixed; z-index: 40; background: var(--panel); border: 1px solid var(--border); border-radius: 10px; box-shadow: var(--shadow); padding: 6px; display: flex; flex-direction: column; gap: 4px; min-width: 120px; color: var(--ink); }
.auth-visibility-menu button { text-align: left; border: 1px solid transparent; background: rgba(var(--panel-rgb), 0.8); color: var(--ink); padding: 6px 8px; border-radius: 8px; font-size: 12px; cursor: pointer; }
.auth-visibility-menu button:hover { border-color: var(--border); }
.auth-list { max-height: 220px; overflow: auto; }
.auth-about-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.auth-about-card { border: 1px solid var(--border); border-radius: 12px; padding: 10px; background: rgba(var(--panel-rgb), 0.72); display: flex; flex-direction: column; gap: 6px; }
.auth-about-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }
.auth-about-value { font-size: 13px; font-weight: 600; overflow-wrap: anywhere; }
.auth-about-log { max-height: 220px; overflow: auto; border: 1px solid var(--border); border-radius: 12px; padding: 10px; background: rgba(var(--panel-rgb), 0.62); display: flex; flex-direction: column; gap: 8px; }
.auth-about-log-item { border-bottom: 1px solid var(--border); padding-bottom: 8px; }
.auth-about-log-item:last-child { border-bottom: 0; padding-bottom: 0; }
.auth-about-log-subject { font-weight: 700; }
.auth-about-log-meta { font-size: 11px; color: var(--muted); margin-top: 2px; }
.auth-about-status { font-size: 12px; color: var(--muted); min-height: 18px; }
.auth-about-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.auth-about-inline { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.auth-about-inline input { flex: 1 1 180px; }
.auth-about-empty { font-size: 12px; color: var(--muted); }
.auth-item-actions { display: inline-flex; align-items: center; gap: 6px; }
.auth-roster-row { padding: 10px 12px; border-bottom: 1px solid var(--border); }
.auth-roster-row:last-child { border-bottom: none; }
.auth-request-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.auth-request-main { min-width: 0; flex: 1 1 auto; }
.auth-request-actions { display: inline-flex; align-items: center; gap: 6px; flex: 0 0 auto; }
.auth-request-actions button { white-space: nowrap; }
.auth-wizard-note { font-size: 12px; color: var(--muted); line-height: 1.5; white-space: pre-line; }
.auth-wizard-secret { display: flex; flex-direction: column; gap: 6px; padding: 12px; border: 1px solid var(--border); border-radius: 12px; background: rgba(var(--panel-rgb), 0.55); }
.auth-wizard-secret code { font-size: 15px; font-weight: 700; word-break: break-all; }
.auth-wizard-status { min-height: 18px; font-size: 12px; color: var(--muted); }
.auth-gear { width: 28px; height: 24px; display: inline-flex; align-items: center; justify-content: center; border-radius: 10px; border: 1px solid var(--border); background: rgba(var(--panel-rgb), 0.55); color: var(--muted); cursor: pointer; }
.auth-gear:hover { color: var(--ink); box-shadow: 0 0 0 2px rgba(var(--accent-rgb), 0.12); }
.auth-gear-menu { position: fixed; z-index: 45; background: var(--panel); border: 1px solid var(--border); border-radius: 10px; box-shadow: var(--shadow); padding: 6px; display: flex; flex-direction: column; gap: 4px; min-width: 180px; color: var(--ink); }
.auth-gear-menu button { text-align: left; border: 1px solid transparent; background: rgba(var(--panel-rgb), 0.8); color: var(--ink); padding: 6px 8px; border-radius: 8px; font-size: 12px; cursor: pointer; }
.auth-gear-menu button:hover { border-color: var(--border); }
.auth-small { font-size: 11px; color: var(--muted); }
.auth-service-block { border: 1px solid var(--border); border-radius: 12px; background: rgba(var(--panel-rgb), 0.55); padding: 10px; display: flex; flex-direction: column; gap: 6px; }
.auth-service-block code { white-space: pre-wrap; word-break: break-word; font-size: 12px; }
.auth-service-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.auth-ai-toggle { display: inline-flex; align-items: center; gap: 8px; font-size: 11px; color: var(--muted); }
.auth-ai-toggle-label { font-weight: 600; letter-spacing: 0.6px; text-transform: uppercase; }
.auth-ai-switch { position: relative; display: inline-flex; align-items: center; }
.auth-ai-switch input { position: absolute; opacity: 0; width: 0; height: 0; }
.auth-ai-slider { width: 42px; height: 22px; border-radius: 999px; background: rgba(0, 0, 0, 0.15); border: 1px solid var(--border); display: inline-flex; align-items: center; padding: 2px; transition: background 0.2s ease; }
.auth-ai-slider::after { content: ""; width: 16px; height: 16px; border-radius: 50%; background: var(--panel); border: 1px solid rgba(0, 0, 0, 0.1); transition: transform 0.2s ease; }
.auth-ai-switch input:checked + .auth-ai-slider { background: rgba(var(--accent-rgb), 0.5); }
.auth-ai-switch input:checked + .auth-ai-slider::after { transform: translateX(18px); }
@media (max-width: 820px) {
  .auth-columns,
  .auth-admin-grid,
  .auth-about-grid {
    grid-template-columns: minmax(0, 1fr);
  }
  .auth-request-row {
    flex-direction: column;
    align-items: stretch;
  }
  .auth-request-actions {
    justify-content: flex-end;
    flex-wrap: wrap;
  }
}
@media (max-width: 640px) {
  .auth-modal {
    align-items: flex-start;
    padding: 10px;
  }
  .auth-modal-card {
    width: 100%;
    max-width: 100%;
    max-height: calc(100dvh - 20px);
    padding: 14px;
    border-radius: 12px;
  }
  .auth-actions,
  .auth-about-actions {
    width: 100%;
    justify-content: flex-start;
  }
  .auth-actions > *,
  .auth-about-actions > * {
    flex: 1 1 100%;
  }
}
  `;
  document.head.appendChild(style);
}

function button(label, className, onClick) {
  const btn = document.createElement("button");
  btn.className = className || "ghost";
  btn.textContent = label;
  btn.addEventListener("click", (event) => {
    runAsyncTask(() => onClick?.(event));
  });
  return btn;
}

function field(labelText, input) {
  const wrap = document.createElement("label");
  wrap.className = "field";
  const label = document.createElement("span");
  label.textContent = labelText;
  wrap.appendChild(label);
  wrap.appendChild(input);
  return wrap;
}

function selectOptions(values) {
  const sel = document.createElement("select");
  values.forEach((val) => {
    const opt = document.createElement("option");
    opt.value = val;
    opt.textContent = val;
    sel.appendChild(opt);
  });
  return sel;
}

function openModal(titleText) {
  ensureStyles();
  // In embed mode, chat_js CSS is scoped under the embed wrapper. We render
  // modals into the overlay portal (if available) so they can use full page
  // space and still inherit the chat theme vars.
  const mount =
    (lastRenderCtx && typeof lastRenderCtx.getOverlayMount === "function" && lastRenderCtx.getOverlayMount()) ||
    (lastRenderCtx && typeof lastRenderCtx.getEmbedMount === "function" && lastRenderCtx.getEmbedMount()) ||
    document.body;
  const modal = document.createElement("div");
  modal.className = "auth-modal";
  const card = document.createElement("div");
  card.className = "auth-modal-card";
  if (titleText) {
    const title = document.createElement("div");
    title.className = "list-title";
    title.textContent = titleText;
    card.appendChild(title);
  }
  modal.appendChild(card);
  function close() {
    activeAuthModals.delete(modal);
    modal.remove();
  }
  modal.addEventListener("click", (event) => {
    if (event.target === modal) close();
  });
  mount.appendChild(modal);
  activeAuthModals.add(modal);
  translateAuthNode(modal);
  return { modal, card, close };
}

function closeAllAuthModals() {
  const modals = Array.from(activeAuthModals);
  activeAuthModals.clear();
  modals.forEach((modal) => {
    try {
      modal?.remove?.();
    } catch (_err) {}
  });
}

function openPromptForm({ title, fields, submitLabel = authT("auth_projects.common.save", "Save"), cancelLabel = authT("auth_projects.common.cancel", "Cancel") }) {
  return new Promise((resolve) => {
    const { modal, card, close } = openModal(title);
    const form = document.createElement("form");
    const inputs = {};

    fields.forEach((cfg) => {
      let input = null;
      if (cfg.type === "textarea") {
        input = document.createElement("textarea");
        input.classList.add("auth-textarea");
        input.rows = Number(cfg.rows || 6);
        input.value = cfg.value || "";
        if (cfg.placeholder) input.placeholder = cfg.placeholder;
      } else if (cfg.type === "select") {
        input = document.createElement("select");
        const options = Array.isArray(cfg.options) ? cfg.options : [];
        options.forEach((opt) => {
          const val = typeof opt === "string" ? opt : opt.value;
          const label = typeof opt === "string" ? opt : opt.label ?? opt.value;
          if (val === undefined || val === null) return;
          const option = document.createElement("option");
          option.value = String(val);
          option.textContent = String(label);
          input.appendChild(option);
        });
        if (cfg.value !== undefined && cfg.value !== null) {
          input.value = String(cfg.value);
        }
      } else {
        input = document.createElement("input");
        input.type = cfg.type || "text";
        if (input.type === "checkbox") {
          input.checked = Boolean(cfg.value);
        } else {
          input.value = cfg.value || "";
          if (cfg.placeholder) input.placeholder = cfg.placeholder;
        }
      }
      if (cfg.required) input.required = true;
      inputs[cfg.key] = input;

      let row = null;
      if (input.type === "checkbox") {
        row = document.createElement("label");
        row.className = "auth-checkbox";
        row.appendChild(input);
        const txt = document.createElement("span");
        txt.textContent = cfg.label || cfg.key;
        row.appendChild(txt);
      } else {
        row = field(cfg.label || cfg.key, input);
      }
      if (cfg.spacer) row.classList.add("auth-field-spacer");
      form.appendChild(row);
    });

    const actions = document.createElement("div");
    actions.className = "auth-actions auth-form-actions";
    const cancelBtn = button(cancelLabel, "ghost", () => {
      close();
      resolve(null);
    });
    const submitBtn = button(submitLabel, "primary", () => form.requestSubmit());
    actions.appendChild(cancelBtn);
    actions.appendChild(submitBtn);
    form.appendChild(actions);

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const data = {};
      Object.entries(inputs).forEach(([key, input]) => {
        if (input.type === "checkbox") data[key] = input.checked;
        else data[key] = input.value;
      });
      close();
      resolve(data);
    });

    modal.addEventListener("click", (event) => {
      if (event.target === modal) {
        close();
        resolve(null);
      }
    });

    card.appendChild(form);
  });
}

function openConfirm({ title, message, confirmLabel = authT("auth_projects.common.confirm", "Confirm"), cancelLabel = authT("auth_projects.common.cancel", "Cancel") }) {
  return new Promise((resolve) => {
    const { modal, card, close } = openModal(title);
    if (message) {
      const msg = document.createElement("div");
      msg.className = "auth-meta";
      msg.textContent = message;
      card.appendChild(msg);
    }
    const actions = document.createElement("div");
    actions.className = "auth-actions";
    const cancelBtn = button(cancelLabel, "ghost", () => {
      close();
      resolve(false);
    });
    const okBtn = button(confirmLabel, "primary", () => {
      close();
      resolve(true);
    });
    actions.appendChild(cancelBtn);
    actions.appendChild(okBtn);
    card.appendChild(actions);

    modal.addEventListener("click", (event) => {
      if (event.target === modal) {
        close();
        resolve(false);
      }
    });
  });
}

function getServerUrl(host) {
  const state = host?.getState?.() || {};
  return String(state?.remote?.serverUrl || "").trim().replace(/\/+$/, "");
}

async function serverJson(host, path, options = {}) {
  const server = getServerUrl(host);
  if (!server) throw new Error("Server URL is not configured.");
  const state = host?.getState?.() || {};
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  const token = String(state?.auth?.token || "").trim();
  if (token && !headers.Authorization) headers.Authorization = `Bearer ${token}`;
  const init = { method: options.method || "GET", headers };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  const res = await fetch(`${server}${path}`, init);
  const text = await res.text().catch(() => "");
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch (_err) {
      data = null;
    }
  }
  if (!res.ok) {
    throw new Error((data && (data.detail || data.error || data.message)) || text || `HTTP ${res.status}`);
  }
  return data;
}

async function copyText(text) {
  const value = String(text || "");
  if (!value) return false;
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch (_err) {
    return false;
  }
}

async function showSessionServiceUrlModal(pid, sid, ctx, host) {
  const info = await serverJson(host, `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/service_info`, {
    headers: { "X-Project-Id": pid, "X-Session-Id": sid },
  });
  const { modal, card, close } = openModal(authT("auth_projects.session.service_url", "Service URL"));

  const intro = document.createElement("div");
  intro.className = "auth-meta";
  intro.textContent = "Use the login endpoint to get a bearer token, then post messages to the session service URL. The request runs against this session using the saved router/flow settings and writes the messages back into the live chat.";
  card.appendChild(intro);

  const serviceBlock = document.createElement("div");
  serviceBlock.className = "auth-service-block";
  serviceBlock.innerHTML = `<div class="auth-small">Session message endpoint</div><code>${info?.service_url || ""}</code>`;
  card.appendChild(serviceBlock);

  const authBlock = document.createElement("div");
  authBlock.className = "auth-service-block";
  authBlock.innerHTML = `<div class="auth-small">Login endpoint</div><code>${info?.auth_url || ""}</code>`;
  card.appendChild(authBlock);

  const headerBlock = document.createElement("div");
  headerBlock.className = "auth-service-block";
  headerBlock.innerHTML = `<div class="auth-small">Required auth header</div><code>${info?.auth_header || "Authorization: Bearer <token>"}</code>`;
  card.appendChild(headerBlock);

  const sample = {
    message: "Add your message here.",
  };
  const sampleBlock = document.createElement("div");
  sampleBlock.className = "auth-service-block";
  sampleBlock.innerHTML = `<div class="auth-small">Sample request body</div><code>${JSON.stringify(info?.sample_body || sample, null, 2)}</code>`;
  card.appendChild(sampleBlock);

  const mode = document.createElement("div");
  mode.className = "auth-meta";
  const activeFlow = String(info?.active_flow || "").trim();
  const modeBits = [
    `Active flow: ${activeFlow || (info?.no_flow_selected ? "No Flow" : "Normal chat")}`,
    `AutoFlow: ${info?.autoflow_enabled ? "on" : "off"}`,
    `Enabled plugins: ${Array.isArray(info?.router_enabled_plugins) && info.router_enabled_plugins.length ? info.router_enabled_plugins.join(", ") : "none"}`,
  ];
  mode.textContent = modeBits.join("\n");
  card.appendChild(mode);

  const actions = document.createElement("div");
  actions.className = "auth-service-actions";
  actions.appendChild(button(authT("auth_projects.common.copy", "Copy") + " URL", "ghost", async () => {
    await copyText(String(info?.service_url || ""));
  }));
  actions.appendChild(button(authT("auth_projects.common.copy", "Copy") + " Login", "ghost", async () => {
    await copyText(String(info?.auth_url || ""));
  }));
  actions.appendChild(button(authT("auth_projects.common.copy", "Copy") + " Body", "ghost", async () => {
    await copyText(JSON.stringify(info?.sample_body || sample, null, 2));
  }));
  actions.appendChild(button(authT("auth_projects.common.close", "Close"), "primary", () => close()));
  card.appendChild(actions);

  modal.addEventListener("click", (event) => {
    if (event.target === modal) close();
  });
}

async function fetchBootstrapAdminSetup(host) {
  return await serverJson(host, "/v1/auth/bootstrap_admin_setup");
}

async function ensureStarterSession(ctx, host) {
  const body = {
    pid: "default",
    project_name: "Default",
    sid: "chat",
    title: "Chat",
  };
  if (ctx?.apiJson) {
    return await ctx.apiJson("/v1/auth/ensure_starter_session", {
      method: "POST",
      body,
    });
  }
  return await serverJson(host, "/v1/auth/ensure_starter_session", {
    method: "POST",
    body,
  });
}

function openBootstrapAdminWizard(ctx, host, payload) {
  if (bootstrapWizardOpen) return;
  bootstrapWizardOpen = true;
  const username = String(payload?.username || "admin").trim() || "admin";
  const tempPassword = String(payload?.password || "").trim();
  const { card, close } = openModal("Admin Setup");

  const finish = () => {
    bootstrapWizardOpen = false;
    close();
  };

  function renderIntro() {
    card.innerHTML = "";
    const note = document.createElement("div");
    note.className = "auth-wizard-note";
    note.textContent = "A temporary admin password was generated for this first-time setup.\nWrite it down if you plan to keep using it, or continue to change it now.";
    card.appendChild(note);

    const userField = document.createElement("input");
    userField.value = username;
    userField.readOnly = true;
    card.appendChild(field("Username", userField));

    const secret = document.createElement("div");
    secret.className = "auth-wizard-secret";
    secret.innerHTML = `<div class="auth-small">Temporary password</div><code>${tempPassword || "(not available)"}</code>`;
    card.appendChild(secret);

    const actions = document.createElement("div");
    actions.className = "auth-actions";
    const continueBtn = button("Change Password Now", "primary", () => renderChange());
    continueBtn.disabled = !tempPassword;
    actions.appendChild(continueBtn);
    actions.appendChild(button("Close", "ghost", finish));
    card.appendChild(actions);
  }

  function renderChange() {
    card.innerHTML = "";
    const note = document.createElement("div");
    note.className = "auth-wizard-note";
    note.textContent = "Set a new admin password now. After the change succeeds, the admin account will be logged in automatically.";
    card.appendChild(note);

    const newInput = document.createElement("input");
    newInput.type = "password";
    const confirmInput = document.createElement("input");
    confirmInput.type = "password";
    card.appendChild(field("New Password", newInput));
    card.appendChild(field("Confirm Password", confirmInput));

    const status = document.createElement("div");
    status.className = "auth-wizard-status";
    card.appendChild(status);

    const actions = document.createElement("div");
    actions.className = "auth-actions";
    const backBtn = button("Back", "ghost", () => renderIntro());
    const saveBtn = button("Save and Login", "primary", async () => {
      const newPw = newInput.value;
      const confirmPw = confirmInput.value;
      if (!newPw) {
        status.textContent = "New password is required.";
        return;
      }
      if (newPw !== confirmPw) {
        status.textContent = "Passwords do not match.";
        return;
      }
      status.textContent = "Updating password...";
      backBtn.disabled = true;
      saveBtn.disabled = true;
      try {
        const loginRes = await host.login(username, tempPassword);
        if (!loginRes?.ok) {
          status.textContent = "Unable to sign in with the temporary password.";
          return;
        }
        if (ctx?.apiJson) {
          await ctx.apiJson("/v1/auth/change_password", {
            method: "POST",
            body: { old_password: tempPassword, new_password: newPw },
          });
          if (ctx.state?.auth) ctx.state.auth.mustChange = false;
          ctx.saveState?.();
        } else {
          await serverJson(host, "/v1/auth/change_password", {
            method: "POST",
            body: { old_password: tempPassword, new_password: newPw },
          });
        }
        status.textContent = "Creating your first chat...";
        let starter = null;
        try {
          starter = await ensureStarterSession(ctx, host);
        } catch (starterErr) {
          console.warn("[auth_projects] starter chat creation failed", starterErr);
        }
        finish();
        rerenderPanel();
        try {
          await host.refreshProjects();
        } catch (refreshErr) {
          console.warn("[auth_projects] project refresh failed after admin setup", refreshErr);
        }
        const starterPid = String(starter?.project?.pid || "");
        const starterSid = String(starter?.session?.sid || "");
        if (starterPid && starterSid && ctx?.state?.ui) {
          ctx.state.ui.activePid = starterPid;
          ctx.state.ui.activeSid = starterSid;
          ctx.saveState?.();
        }
        setTimeout(() => {
          runAsyncTask(async () => {
            const options = { openModal: true, timeoutMs: 8000, forceLoad: true };
            if (typeof ctx?.openPluginPanelWhenReady === "function") {
              await ctx.openPluginPanelWhenReady("setup_wizard", options);
              return;
            } else if (typeof host?.openPluginPanelWhenReady === "function") {
              await host.openPluginPanelWhenReady("setup_wizard", options);
              return;
            }
            if (typeof ctx?.openPluginPanel === "function") {
              ctx.openPluginPanel("setup_wizard", { openModal: true });
            } else {
              host?.openPluginPanel?.("setup_wizard", { openModal: true });
            }
          }, (openErr) => logAsyncError(ctx, "open setup wizard after admin setup", openErr));
        }, 250);
      } catch (err) {
        status.textContent = err?.message || String(err || "Password change failed.");
      } finally {
        backBtn.disabled = false;
        saveBtn.disabled = false;
      }
    });
    actions.appendChild(backBtn);
    actions.appendChild(saveBtn);
    card.appendChild(actions);
  }

  renderIntro();
}

async function maybeOpenBootstrapAdminWizard(ctx, host) {
  if (bootstrapWizardChecked || bootstrapWizardInFlight || bootstrapWizardOpen) return;
  if ((ctx?.state?.auth?.token || host?.getState?.()?.auth?.token || "").trim()) {
    bootstrapWizardChecked = true;
    return;
  }
  bootstrapWizardInFlight = true;
  try {
    const data = await fetchBootstrapAdminSetup(host);
    bootstrapWizardChecked = true;
    if (data?.show && data?.password) {
      openBootstrapAdminWizard(ctx || lastRenderCtx || {}, host, data);
    }
  } catch (_err) {
    // Server may still be starting; allow a later render/timeout to retry.
  } finally {
    bootstrapWizardInFlight = false;
  }
}

function clearBootstrapWizardRetryTimers() {
  for (const timer of bootstrapWizardRetryTimers) {
    try {
      clearTimeout(timer);
    } catch (_err) {}
  }
  bootstrapWizardRetryTimers = [];
}

function scheduleBootstrapAdminWizardChecks(host, ctxProvider) {
  clearBootstrapWizardRetryTimers();
  const delays = [0, 300, 1000, 2500, 5000, 9000, 14000];
  for (const delayMs of delays) {
    const timer = setTimeout(() => {
      if (bootstrapWizardChecked || bootstrapWizardOpen) return;
      const ctx = typeof ctxProvider === "function" ? ctxProvider() : null;
      void maybeOpenBootstrapAdminWizard(ctx || lastRenderCtx || {}, host);
    }, delayMs);
    bootstrapWizardRetryTimers.push(timer);
  }
}

function slugify(text) {
  return String(text || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9\-_:.\s]/g, "")
    .slice(0, 40);
}

async function refreshAuthProjectsCache(ctx, pid = "") {
  if (!ctx) return;
  ctx.state.auth_projects = ctx.state.auth_projects || {};
  ctx.state.auth_projects.remote = ctx.state.auth_projects.remote || { projects: [], sessionsByPid: {} };

  try {
    const data = await ctx.apiJson("/v1/projects");
    ctx.state.auth_projects.remote.projects = data?.projects || [];
  } catch (_err) {}

  const usePid = String(pid || "").trim();
  if (usePid) {
    try {
      const data = await ctx.apiJson(`/v1/projects/${encodeURIComponent(usePid)}/sessions`, {
        headers: { "X-Project-Id": usePid },
      });
      ctx.state.auth_projects.remote.sessionsByPid[usePid] = data?.sessions || [];
    } catch (_err) {}
  }
  ctx.saveState?.();
}

async function openNewProjectWindow(ctx, host) {
  // Ensure embed modals attach inside the chat embed wrapper (so CSS vars apply).
  lastRenderCtx = ctx;
  const token = ((ctx.state.auth || {}).token || "").trim();
  if (!token) {
    openLoginModal(host);
    return;
  }
  const data = await openPromptForm({
    title: authT("auth_projects.project.new_title", "New Project"),
    submitLabel: authT("auth_projects.project.create", "Create project"),
    fields: [
      { key: "name", label: authT("auth_projects.project.name", "Project name"), type: "text", value: "" },
      { key: "pid", label: authT("auth_projects.project.id_optional", "Project id (optional)"), type: "text", value: "", spacer: true },
      { key: "is_public", label: authT("auth_projects.project.public", "Public project"), type: "checkbox", value: false },
    ],
  });
  if (!data) return;
  const name = String(data.name || "").trim();
  if (!name) {
    ctx.log("Project name is required.", "warn");
    return;
  }
  const pid = String(data.pid || "").trim() || slugify(name);
  const isPublic = Boolean(data.is_public);
  await ctx.apiJson("/v1/projects", {
    method: "POST",
    body: { pid, name, is_public: Boolean(isPublic) },
  });
  await refreshAuthProjectsCache(ctx, pid);
  await host.refreshProjects();
  await host.setActiveScope(pid, "");
}

async function openNewSessionWindow(ctx, host, pid) {
  // Ensure embed modals attach inside the chat embed wrapper (so CSS vars apply).
  lastRenderCtx = ctx;
  const token = ((ctx.state.auth || {}).token || "").trim();
  if (!token) {
    openLoginModal(host);
    return;
  }
  const usePid = String(pid || ctx.state.ui.activePid || "").trim();
  if (!usePid) {
    ctx.log("Select a project first.", "warn");
    return;
  }
  const data = await openPromptForm({
    title: authT("auth_projects.session.new_title", "New Session"),
    submitLabel: authT("auth_projects.session.create", "Create session"),
    fields: [
      { key: "title", label: authT("auth_projects.session.title", "Session title"), type: "text", value: "Chat" },
      { key: "is_public", label: authT("auth_projects.session.public", "Public session"), type: "checkbox", value: false },
    ],
  });
  if (!data) return;
  const title = String(data.title || "").trim();
  if (!title) {
    ctx.log("Session title is required.", "warn");
    return;
  }
  const isPublic = Boolean(data.is_public);
  const created = await ctx.apiJson(`/v1/projects/${encodeURIComponent(usePid)}/sessions`, {
    method: "POST",
    body: { title, is_public: Boolean(isPublic) },
    headers: { "X-Project-Id": usePid },
  });
  await refreshAuthProjectsCache(ctx, usePid);
  await host.refreshSessions();
  if (created?.sid) {
    await host.setActiveScope(usePid, created.sid);
  }
}

function rerenderPanel() {
  if (lastRenderTarget && lastRenderCtx && lastRenderHost) {
    renderPanel(lastRenderTarget, lastRenderCtx, lastRenderHost);
  }
}

function closeVisibilityMenu() {
  if (visibilityMenu) {
    visibilityMenu.remove();
    visibilityMenu = null;
  }
  if (visibilityMenuHandler) {
    document.removeEventListener("click", visibilityMenuHandler);
    visibilityMenuHandler = null;
  }
}

function openVisibilityMenu(anchor, currentValue, onSelect) {
  closeVisibilityMenu();
  const menu = document.createElement("div");
  menu.className = "auth-visibility-menu";
  const options = [
    { label: authT("auth_projects.visibility.public", "Public"), value: true },
    { label: authT("auth_projects.visibility.private", "Private"), value: false },
  ];
  options.forEach((opt) => {
    const btn = document.createElement("button");
    btn.textContent = opt.label;
    if (opt.value === Boolean(currentValue)) {
      btn.style.borderColor = "var(--accent)";
      btn.style.fontWeight = "600";
    }
    btn.addEventListener("click", () => {
      closeVisibilityMenu();
      onSelect(opt.value);
    });
    menu.appendChild(btn);
  });
  const mount =
    (lastRenderCtx && typeof lastRenderCtx.getOverlayMount === "function" && lastRenderCtx.getOverlayMount()) ||
    (lastRenderCtx && typeof lastRenderCtx.getEmbedMount === "function" && lastRenderCtx.getEmbedMount()) ||
    document.body;
  mount.appendChild(menu);
  const rect = anchor.getBoundingClientRect();
  menu.style.left = `${Math.min(rect.left, window.innerWidth - menu.offsetWidth - 8)}px`;
  menu.style.top = `${Math.min(rect.bottom + 6, window.innerHeight - menu.offsetHeight - 8)}px`;
  visibilityMenu = menu;
  visibilityMenuHandler = (event) => {
    if (event.target === anchor || menu.contains(event.target)) return;
    closeVisibilityMenu();
  };
  setTimeout(() => document.addEventListener("click", visibilityMenuHandler), 0);
}

let gearMenu = null;
let gearMenuHandler = null;

function closeGearMenu() {
  if (gearMenu) {
    gearMenu.remove();
    gearMenu = null;
  }
  if (gearMenuHandler) {
    document.removeEventListener("click", gearMenuHandler);
    gearMenuHandler = null;
  }
}

function openGearMenu(anchor, items) {
  closeGearMenu();

  const menu = document.createElement("div");
  menu.className = "auth-gear-menu";

  items.forEach((it) => {
    const btn = document.createElement("button");
    btn.textContent = it.label;
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      closeGearMenu();
      await it.onClick();
    });
    menu.appendChild(btn);
  });

  const mount =
    (lastRenderCtx && typeof lastRenderCtx.getOverlayMount === "function" && lastRenderCtx.getOverlayMount()) ||
    (lastRenderCtx && typeof lastRenderCtx.getEmbedMount === "function" && lastRenderCtx.getEmbedMount()) ||
    document.body;
  mount.appendChild(menu);
  const rect = anchor.getBoundingClientRect();
  menu.style.left = `${Math.min(rect.left, window.innerWidth - menu.offsetWidth - 8)}px`;
  menu.style.top = `${Math.min(rect.bottom + 6, window.innerHeight - menu.offsetHeight - 8)}px`;

  gearMenu = menu;
  gearMenuHandler = (event) => {
    if (event.target === anchor || menu.contains(event.target)) return;
    closeGearMenu();
  };
  setTimeout(() => document.addEventListener("click", gearMenuHandler), 0);
}

function renderPanel(container, ctx, host, options = {}) {
  container.innerHTML = "";
  ensureStyles();
  lastRenderTarget = container;
  lastRenderCtx = ctx;
  lastRenderHost = host;

  const root = document.createElement("div");
  root.className = "auth-root";
  container.appendChild(root);

  const status = document.createElement("div");
  status.className = "muted";
  root.appendChild(status);

  const tabs = document.createElement("div");
  tabs.className = "auth-tabs";
  root.appendChild(tabs);

  const panels = document.createElement("div");
  panels.className = "auth-panels";
  root.appendChild(panels);

  const tabDefs = [
    { id: "remote", label: authT("auth_projects.tabs.remote_projects", "Remote Projects") },
    { id: "admin", label: authT("auth_projects.tabs.admin", "Admin") },
    { id: "login", label: authT("auth_projects.tabs.login", "Login") },
  ].filter((tab) => !(options.hideAdmin && tab.id === "admin"));

  const panelEls = {};
  const initialTab = options.defaultTab || "remote";
  let activeTab = tabDefs.some((t) => t.id === initialTab) ? initialTab : tabDefs[0]?.id || "remote";

  function setStatus(text) {
    status.textContent = text || "";
  }

  function setActiveTab(id) {
    activeTab = id;
    for (const def of tabDefs) {
      const btn = tabs.querySelector(`[data-tab="${def.id}"]`);
      const panel = panelEls[def.id];
      if (!btn || !panel) continue;
      const active = def.id === id;
      btn.classList.toggle("active", active);
      panel.classList.toggle("active", active);
    }
  }

  tabDefs.forEach((def) => {
    const btn = document.createElement("button");
    btn.className = "auth-tab";
    btn.dataset.tab = def.id;
    btn.textContent = def.label;
    btn.addEventListener("click", () => setActiveTab(def.id));
    tabs.appendChild(btn);

    const panel = document.createElement("div");
    panel.className = "auth-panel";
    panel.dataset.panel = def.id;
    panelEls[def.id] = panel;
    panels.appendChild(panel);
  });

  const token = ((ctx.state.auth || {}).token || "").trim();
  const role = (ctx.state.auth || {}).role || "";
  if (token) {
    const user = ctx.state.auth.username || "user";
    setStatus(`Logged in as ${user} (${role || "user"})`);
  } else {
    setStatus(authT("auth_projects.status.not_logged_in", "Not logged in"));
  }

  buildRemotePanel(panelEls.remote, ctx, host);
  buildAdminPanel(panelEls.admin, ctx, host);
  buildLoginPanel(panelEls.login, ctx, host, container);

  if (role !== "admin") {
    const adminBtn = tabs.querySelector('[data-tab="admin"]');
    if (adminBtn) adminBtn.disabled = true;
  }
  if (!token) {
    const remoteBtn = tabs.querySelector('[data-tab="remote"]');
    if (remoteBtn) remoteBtn.disabled = true;
    if (activeTab === "remote") {
      activeTab = "login";
    }
  } else {
    const loginBtn = tabs.querySelector('[data-tab="login"]');
    if (loginBtn) loginBtn.disabled = true;
    if (activeTab === "login") {
      activeTab = "remote";
    }
  }

  setActiveTab(activeTab);
  translateAuthNode(root);
  void maybeOpenBootstrapAdminWizard(ctx, host);
}

function buildAiToggleNode(ctx) {
  ensureStyles();
  const wrap = document.createElement("div");
  wrap.className = "auth-ai-toggle";
  const label = document.createElement("span");
  label.className = "auth-ai-toggle-label";
  const switchWrap = document.createElement("label");
  switchWrap.className = "auth-ai-switch";
  const input = document.createElement("input");
  input.type = "checkbox";
  const slider = document.createElement("span");
  slider.className = "auth-ai-slider";
  switchWrap.appendChild(input);
  switchWrap.appendChild(slider);
  wrap.appendChild(label);
  wrap.appendChild(switchWrap);

  const update = () => {
    const pid = ctx.state?.ui?.activePid || "";
    const sid = ctx.state?.ui?.activeSid || "";
    if (!pid || !sid) {
      wrap.style.display = "none";
      return;
    }
    wrap.style.display = "inline-flex";
    const enabled = getAiToggle(ctx, pid, sid);
    input.checked = enabled;
    label.textContent = enabled ? authT("auth_projects.ai.on", "AI on") : authT("auth_projects.ai.off", "AI off");
  };

  input.addEventListener("change", () => {
    const pid = ctx.state?.ui?.activePid || "";
    const sid = ctx.state?.ui?.activeSid || "";
    setAiToggle(ctx, pid, sid, input.checked);
    ctx.saveState?.();
    update();
  });

  document.addEventListener("chat_js:session-changed", update);
  update();
  return wrap;
}

function buildRemotePanel(panel, ctx, host) {
  panel.innerHTML = "";

  const token = ((ctx.state.auth || {}).token || "").trim();
  const hasAuth = Boolean(token);

  const projectList = document.createElement("div");
  projectList.className = "list auth-list";
  const sessionList = document.createElement("div");
  sessionList.className = "list auth-list";

  const columns = document.createElement("div");
  columns.className = "auth-columns";
  const projectCol = document.createElement("div");
  projectCol.className = "auth-column";
  const projectHeader = document.createElement("div");
  projectHeader.className = "section-header auth-list-header";
  const projectLabel = document.createElement("h2");
  projectLabel.textContent = authT("auth_projects.remote.projects", "Projects");
  const projectNewBtn = button(authT("auth_projects.common.new", "New"), "ghost", async () => {
    await newProject();
  });
  projectHeader.appendChild(projectLabel);
  projectHeader.appendChild(projectNewBtn);
  projectCol.appendChild(projectHeader);
  projectCol.appendChild(projectList);

  const sessionCol = document.createElement("div");
  sessionCol.className = "auth-column";
  const sessionHeader = document.createElement("div");
  sessionHeader.className = "section-header auth-list-header";
  const sessionLabel = document.createElement("h2");
  sessionLabel.textContent = authT("auth_projects.remote.sessions", "Sessions");
  const sessionNewBtn = button(authT("auth_projects.common.new", "New"), "ghost", async () => {
    await newSession();
  });
  sessionHeader.appendChild(sessionLabel);
  sessionHeader.appendChild(sessionNewBtn);
  sessionCol.appendChild(sessionHeader);
  sessionCol.appendChild(sessionList);

  columns.appendChild(projectCol);
  columns.appendChild(sessionCol);
  panel.appendChild(columns);

  const visibility = document.createElement("div");
  visibility.className = "auth-meta";
  panel.appendChild(visibility);

  const actionRow = document.createElement("div");
  actionRow.className = "auth-actions";
  panel.appendChild(actionRow);

  const modal = document.createElement("div");
  modal.className = "auth-modal hidden";
  modal.innerHTML = `
    <div class="auth-modal-card">
      <div class="list auth-list" id="auth-requests-list"></div>
      <div class="auth-actions">
        <button class="ghost" id="auth-req-refresh">Refresh</button>
        <button class="primary" id="auth-req-approve">Approve</button>
        <button class="ghost" id="auth-req-deny">Deny</button>
        <button class="ghost" id="auth-req-close">Close</button>
      </div>
    </div>
  `;
  panel.appendChild(modal);

  const reqList = modal.querySelector("#auth-requests-list");
  const reqRefresh = modal.querySelector("#auth-req-refresh");
  const reqApprove = modal.querySelector("#auth-req-approve");
  const reqDeny = modal.querySelector("#auth-req-deny");
  const reqClose = modal.querySelector("#auth-req-close");

  const state = {
    projects: [],
    sessions: [],
    selectedPid: ctx.state.ui.activePid || "",
    selectedSid: ctx.state.ui.activeSid || "",
  };

  function scheduleCoreTranscriptHydration() {
    const pid = String(state.selectedPid || "").trim();
    const sid = String(state.selectedSid || "").trim();
    if (!pid || !sid) return;
    const key = `${pid}:${sid}`;
    if (coreTranscriptHydrateTimer) {
      clearTimeout(coreTranscriptHydrateTimer);
    }
    coreTranscriptHydrateTimer = setTimeout(async () => {
      coreTranscriptHydrateTimer = null;
      try {
        const activePid = String(ctx.state?.ui?.activePid || "").trim();
        const activeSid = String(ctx.state?.ui?.activeSid || "").trim();
        if ((activePid || activeSid) && (activePid !== pid || activeSid !== sid)) {
          return;
        }
        const currentMessages = ctx.state?.sessions?.[sid]?.messages || [];
        const activeMatches = activePid === pid && activeSid === sid;
        if (activeMatches && coreTranscriptHydrateKey === key && Array.isArray(currentMessages) && currentMessages.length) {
          return;
        }
        coreTranscriptHydrateKey = key;
        if (activeMatches && typeof host.refreshMessages === "function") {
          await host.refreshMessages();
        } else if (!activePid && !activeSid && typeof host.setActiveScope === "function") {
          await host.setActiveScope(pid, sid);
        }
      } catch (err) {
        try {
          ctx.log(`[auth_projects] message hydrate failed: ${err?.message || err}`, "warn");
        } catch (_err) {}
      }
    }, 0);
  }

  ctx.state.auth_projects = ctx.state.auth_projects || {};
  ctx.state.auth_projects.remote = ctx.state.auth_projects.remote || { projects: [], sessionsByPid: {} };

  function updateVisibility() {
    const proj = state.projects.find((p) => p.pid === state.selectedPid);
    const sess = state.sessions.find((s) => s.sid === state.selectedSid);
    if (!proj || !sess) {
      visibility.textContent = "";
      return;
    }
    const projPub = Boolean(proj.is_public);
    const sessPub = Boolean(sess.is_public);
    const allowGuest = Boolean(sess.allow_guest);
    const effective = projPub && sessPub;
    const effTxt = sessPub && !projPub ? "private (forced: project is private)" : effective ? "public" : "private";
    visibility.textContent = `Project: ${projPub ? "public" : "private"}\nSession: ${sessPub ? "public" : "private"}\nEffective: ${effTxt}\nAllow guest: ${allowGuest ? "yes" : "no"}`;
  }

  function renderProjects() {
    projectList.innerHTML = "";
    state.projects.forEach((proj) => {
      const item = document.createElement("div");
      item.className = "list-item" + (proj.pid === state.selectedPid ? " active" : "");
      item.dataset.pid = proj.pid;
      item.dataset.public = proj.is_public ? "1" : "0";
      item.innerHTML = `
        <div class="list-title-row">
          <div class="list-title">${proj.name || proj.pid}</div>
            <div class="auth-item-actions">
              <button class="auth-badge ${proj.is_public ? "public" : "private"}" data-visibility="project">${proj.is_public ? authT("auth_projects.visibility.public", "Public") : authT("auth_projects.visibility.private", "Private")}</button>
              <button class="auth-gear" data-gear="project" title="Settings">⚙</button>
            </div>
        </div>
        <div class="list-meta">${proj.pid}</div>
      `;
      const badge = item.querySelector("[data-visibility='project']");
      if (badge) {
        badge.addEventListener("click", async (event) => {
          event.stopPropagation();
          openVisibilityMenu(badge, proj.is_public, async (nextValue) => {
            await setProjectVisibility(proj.pid, nextValue);
            await refreshProjects();
          });
        });
      }
      const gear = item.querySelector("[data-gear='project']");
      if (gear) {
        gear.addEventListener("click", async (event) => {
          event.stopPropagation();
          await showCollabSettingsMenu({ anchor: gear, scope: "project", pid: proj.pid, sid: "" }, ctx, state, host);
        });
      }
      item.addEventListener("click", async () => {
        state.selectedPid = proj.pid;
        state.selectedSid = "";
        renderProjects();
        await refreshSessions();
        updateVisibility();
        await host.setActiveScope(proj.pid, "");
      });
      projectList.appendChild(item);
    });
  }

  function renderSessions() {
    sessionList.innerHTML = "";
    state.sessions.forEach((sess) => {
      const item = document.createElement("div");
      item.className = "list-item" + (sess.sid === state.selectedSid ? " active" : "");
      item.dataset.sid = sess.sid;
      item.dataset.public = sess.is_public ? "1" : "0";
      item.innerHTML = `
        <div class="list-title-row">
          <div class="list-title">${sess.title || sess.sid}</div>
          <div class="auth-item-actions">
            <button class="auth-badge ${sess.is_public ? "public" : "private"}" data-visibility="session">${sess.is_public ? authT("auth_projects.visibility.public", "Public") : authT("auth_projects.visibility.private", "Private")}</button>
            <button class="auth-gear" data-gear="session" title="Settings">⚙</button>
          </div>
        </div>
        <div class="list-meta">${sess.sid}</div>
      `;
      const badge = item.querySelector("[data-visibility='session']");
      if (badge) {
        badge.addEventListener("click", async (event) => {
          event.stopPropagation();
          openVisibilityMenu(badge, sess.is_public, async (nextValue) => {
            await setSessionVisibility(state.selectedPid, sess.sid, nextValue);
            await refreshSessions();
          });
        });
      }
      const gear = item.querySelector("[data-gear='session']");
      if (gear) {
        gear.addEventListener("click", async (event) => {
          event.stopPropagation();
          await showCollabSettingsMenu({ anchor: gear, scope: "session", pid: state.selectedPid, sid: sess.sid }, ctx, state, host);
        });
      }
      item.addEventListener("click", async () => {
        state.selectedSid = sess.sid;
        renderSessions();
        updateVisibility();
        await host.setActiveScope(state.selectedPid, sess.sid);
      });
      sessionList.appendChild(item);
    });
  }

  async function showCollabSettingsMenu(ref, ctx, state, host) {
    const role = (ctx.state.auth || {}).role || "";
    if (role !== "admin") {
      ctx.log("Admin required.", "warn");
      return;
    }
    const remoteState = (ctx.state.auth_projects || {}).remote || {};

    const promptsRes = await ctx.apiJson("/v1/collab_prompts");
    const prompts = (promptsRes && promptsRes.prompts) ? promptsRes.prompts : [];

    const isSession = ref.scope === "session";

    const currentProj = state.projects.find((p) => p.pid === ref.pid) || {};
    const currentSess = isSession ? state.sessions.find((s) => s.sid === ref.sid) || {} : {};

    const curAi = isSession
      ? coerceBool(currentSess.ai_default, true)
      : coerceBool(currentProj.ai_default, true);
    const curAllowGuest = isSession ? coerceBool(currentSess.allow_guest, false) : false;

    const curPromptId = isSession
      ? (currentSess.collab_prompt_id || "")
      : (currentProj.collab_prompt_id || "");

    const items = [
      ...(isSession ? [{
        label: authT("auth_projects.session.service_url", "Service URL"),
        onClick: async () => {
          await showSessionServiceUrlModal(ref.pid, ref.sid, ctx, host);
        },
      }] : []),
      {
        label: authT("auth_projects.prompts.set", "Set Collab Prompt"),
        onClick: async () => {
          const pick = await openPromptForm({
            title: authT("auth_projects.prompts.set", "Set Collab Prompt"),
            submitLabel: authT("auth_projects.common.set", "Set"),
            fields: [
              {
                key: "prompt_id",
                label: authT("auth_projects.prompts.prompt", "Prompt"),
                type: "select",
                options: prompts.map((p) => ({ label: p.name || p.prompt_id, value: p.prompt_id })),
                value: curPromptId || (prompts[0] ? prompts[0].prompt_id : ""),
              },
            ],
          });
          if (!pick) return;
          const wanted = String(pick.prompt_id || "").trim();
          const found = prompts.find((p) => String(p.prompt_id || "").trim() === wanted) || prompts[0];
          if (!found) return;

          if (isSession) {
            await ctx.apiJson(`/v1/projects/${encodeURIComponent(ref.pid)}/sessions/${encodeURIComponent(ref.sid)}/collab_settings`, {
              method: "PUT",
              headers: { "X-Project-Id": ref.pid, "X-Session-Id": ref.sid },
              body: { collab_prompt_id: found.prompt_id },
            });
            if (ctx.state.sessions && ctx.state.sessions[ref.sid]) {
              ctx.state.sessions[ref.sid].collab_prompt_id = found.prompt_id;
            }
            if (remoteState.sessionsByPid?.[ref.pid]) {
              const row = remoteState.sessionsByPid[ref.pid].find((s) => s.sid === ref.sid);
              if (row) row.collab_prompt_id = found.prompt_id;
            }
            await host.refreshSessions();
          } else {
            await ctx.apiJson(`/v1/projects/${encodeURIComponent(ref.pid)}/collab_settings`, {
              method: "PUT",
              headers: { "X-Project-Id": ref.pid },
              body: { collab_prompt_id: found.prompt_id },
            });
            if (ctx.state.projects && ctx.state.projects[ref.pid]) {
              ctx.state.projects[ref.pid].collab_prompt_id = found.prompt_id;
            }
            await host.refreshProjects();
          }
          await rerenderPanel();
        },
      },
      {
        label: authT("auth_projects.prompts.add_new", "Add New Prompt"),
        onClick: async () => {
          const data = await openPromptForm({
            title: authT("auth_projects.prompts.add_title", "Add Collab Prompt"),
            submitLabel: authT("auth_projects.common.create", "Create"),
            fields: [
              { key: "name", label: authT("auth_projects.prompts.name", "Prompt name"), type: "text", value: "" },
              { key: "prompt", label: authT("auth_projects.prompts.system_prompt", "System prompt"), type: "textarea", rows: 8, value: "", spacer: true },
            ],
          });
          if (!data) return;
          const name = String(data.name || "").trim();
          const prompt = String(data.prompt || "").trim();
          if (!name || !prompt) return;

          const res = await ctx.apiJson("/v1/collab_prompts", { method: "POST", body: { name, prompt } });
          const newId = res.prompt_id;
          if (!newId) return;

          if (isSession) {
            await ctx.apiJson(`/v1/projects/${encodeURIComponent(ref.pid)}/sessions/${encodeURIComponent(ref.sid)}/collab_settings`, {
              method: "PUT",
              headers: { "X-Project-Id": ref.pid, "X-Session-Id": ref.sid },
              body: { collab_prompt_id: newId },
            });
            if (ctx.state.sessions && ctx.state.sessions[ref.sid]) {
              ctx.state.sessions[ref.sid].collab_prompt_id = newId;
            }
            if (remoteState.sessionsByPid?.[ref.pid]) {
              const row = remoteState.sessionsByPid[ref.pid].find((s) => s.sid === ref.sid);
              if (row) row.collab_prompt_id = newId;
            }
            await host.refreshSessions();
          } else {
            await ctx.apiJson(`/v1/projects/${encodeURIComponent(ref.pid)}/collab_settings`, {
              method: "PUT",
              headers: { "X-Project-Id": ref.pid },
              body: { collab_prompt_id: newId },
            });
            if (ctx.state.projects && ctx.state.projects[ref.pid]) {
              ctx.state.projects[ref.pid].collab_prompt_id = newId;
            }
            await host.refreshProjects();
          }
          await rerenderPanel();
        },
      },
      {
        label: `AI default ${curAi ? "On" : "Off"} → Toggle`,
        onClick: async () => {
          const next = !curAi;
          if (isSession) {
            await ctx.apiJson(`/v1/projects/${encodeURIComponent(ref.pid)}/sessions/${encodeURIComponent(ref.sid)}/collab_settings`, {
              method: "PUT",
              headers: { "X-Project-Id": ref.pid, "X-Session-Id": ref.sid },
              body: { ai_default: Boolean(next) },
            });
            if (ctx.state.sessions && ctx.state.sessions[ref.sid]) {
              ctx.state.sessions[ref.sid].ai_default = Boolean(next) ? 1 : 0;
            }
            const localRow = state.sessions.find((s) => s.sid === ref.sid);
            if (localRow) localRow.ai_default = Boolean(next) ? 1 : 0;
            if (remoteState.sessionsByPid?.[ref.pid]) {
              const row = remoteState.sessionsByPid[ref.pid].find((s) => s.sid === ref.sid);
              if (row) row.ai_default = Boolean(next) ? 1 : 0;
            }
            await host.refreshSessions();
          } else {
            await ctx.apiJson(`/v1/projects/${encodeURIComponent(ref.pid)}/collab_settings`, {
              method: "PUT",
              headers: { "X-Project-Id": ref.pid },
              body: { ai_default: Boolean(next) },
            });
            if (ctx.state.projects && ctx.state.projects[ref.pid]) {
              ctx.state.projects[ref.pid].ai_default = Boolean(next) ? 1 : 0;
            }
            const localProj = state.projects.find((p) => p.pid === ref.pid);
            if (localProj) localProj.ai_default = Boolean(next) ? 1 : 0;
            await host.refreshProjects();
          }
          await rerenderPanel();
        },
      },
      ...(isSession ? [{
        label: `Allow guest ${curAllowGuest ? "On" : "Off"} -> Toggle`,
        onClick: async () => {
          const next = !curAllowGuest;
          await ctx.apiJson(`/v1/projects/${encodeURIComponent(ref.pid)}/sessions/${encodeURIComponent(ref.sid)}/collab_settings`, {
            method: "PUT",
            headers: { "X-Project-Id": ref.pid, "X-Session-Id": ref.sid },
            body: { allow_guest: Boolean(next) },
          });
          if (ctx.state.sessions && ctx.state.sessions[ref.sid]) {
            ctx.state.sessions[ref.sid].allow_guest = Boolean(next) ? 1 : 0;
          }
          const localRow = state.sessions.find((s) => s.sid === ref.sid);
          if (localRow) localRow.allow_guest = Boolean(next) ? 1 : 0;
          if (remoteState.sessionsByPid?.[ref.pid]) {
            const row = remoteState.sessionsByPid[ref.pid].find((s) => s.sid === ref.sid);
            if (row) row.allow_guest = Boolean(next) ? 1 : 0;
          }
          await host.refreshSessions();
          await rerenderPanel();
        },
      }] : []),
      {
        label: isSession ? authT("auth_projects.session.remove", "Remove Session") : authT("auth_projects.project.remove", "Remove Project"),
        onClick: async () => {
          const ok = await openConfirm({
            title: isSession ? authT("auth_projects.session.remove", "Remove Session") : authT("auth_projects.project.remove", "Remove Project"),
            message: isSession
              ? `Remove session '${ref.sid}' from project '${ref.pid}'?`
              : `Remove project '${ref.pid}' and all its sessions?`,
            confirmLabel: "Remove",
          });
          if (!ok) return;
          if (isSession) {
            await ctx.apiJson(`/v1/projects/${encodeURIComponent(ref.pid)}/sessions/${encodeURIComponent(ref.sid)}`, {
              method: "DELETE",
              headers: { "X-Project-Id": ref.pid, "X-Session-Id": ref.sid },
            });
            state.selectedSid = "";
            await refreshSessions();
            updateVisibility();
            await host.refreshSessions();
            await host.setActiveScope(ref.pid, state.selectedSid);
          } else {
            await ctx.apiJson(`/v1/projects/${encodeURIComponent(ref.pid)}`, {
              method: "DELETE",
              headers: { "X-Project-Id": ref.pid },
            });
            state.selectedPid = "";
            state.selectedSid = "";
            await refreshProjects();
            updateVisibility();
            await host.refreshProjects();
            await host.setActiveScope(state.selectedPid, state.selectedSid);
          }
          await rerenderPanel();
        },
      },
    ];

    openGearMenu(ref.anchor, items);
  }

  async function refreshProjects() {
    if (!hasAuth) {
      ctx.log("Login required.", "warn");
      return;
    }
    const data = await ctx.apiJson("/v1/projects");
    state.projects = data.projects || [];
    ctx.state.auth_projects.remote.projects = state.projects;
    ctx.saveState?.();
    if (!state.selectedPid && state.projects.length) {
      state.selectedPid = state.projects[0].pid;
    }
    renderProjects();
    await refreshSessions();
    updateVisibility();
  }

  async function refreshSessions() {
    if (!state.selectedPid) {
      state.sessions = [];
      ctx.state.auth_projects.remote.sessionsByPid[state.selectedPid] = state.sessions;
      ctx.saveState?.();
      renderSessions();
      return;
    }
    const data = await ctx.apiJson(`/v1/projects/${encodeURIComponent(state.selectedPid)}/sessions`, {
      headers: { "X-Project-Id": state.selectedPid },
    });
    state.sessions = data.sessions || [];
    ctx.state.auth_projects.remote.sessionsByPid[state.selectedPid] = state.sessions;
    ctx.saveState?.();
    const coreSid = String(ctx.state?.ui?.activeSid || "").trim();
    const corePid = String(ctx.state?.ui?.activePid || "").trim();
    const sessionIds = new Set(state.sessions.map((sess) => String(sess?.sid || "").trim()).filter(Boolean));
    if (corePid === state.selectedPid && coreSid && sessionIds.has(coreSid)) {
      state.selectedSid = coreSid;
    } else if ((!state.selectedSid || !sessionIds.has(state.selectedSid)) && state.sessions.length) {
      state.selectedSid = state.sessions[0].sid;
    }
    renderSessions();
    scheduleCoreTranscriptHydration();
  }

  async function newProject() {
    if (!hasAuth) return;
    const data = await openPromptForm({
      title: authT("auth_projects.project.new_title", "New Project"),
      submitLabel: authT("auth_projects.project.create", "Create project"),
      fields: [
        { key: "name", label: authT("auth_projects.project.name", "Project name"), type: "text", value: "" },
        { key: "pid", label: authT("auth_projects.project.id_optional", "Project id (optional)"), type: "text", value: "", spacer: true },
        { key: "is_public", label: authT("auth_projects.project.public", "Public project"), type: "checkbox", value: false },
      ],
    });
    if (!data) return;
    const name = String(data.name || "").trim();
    if (!name) {
      ctx.log("Project name is required.", "warn");
      return;
    }
    const pid = String(data.pid || "").trim() || slugify(name);
    const isPublic = Boolean(data.is_public);
    await ctx.apiJson("/v1/projects", {
      method: "POST",
      body: { pid, name, is_public: Boolean(isPublic) },
    });
    await refreshProjects();
    await host.refreshProjects();
  }

  async function newSession() {
    if (!hasAuth) return;
    if (!state.selectedPid) {
      ctx.log("Select a project first.", "warn");
      return;
    }
    const data = await openPromptForm({
      title: authT("auth_projects.session.new_title", "New Session"),
      submitLabel: authT("auth_projects.session.create", "Create session"),
      fields: [
        { key: "title", label: authT("auth_projects.session.title", "Session title"), type: "text", value: "Chat" },
        { key: "is_public", label: authT("auth_projects.session.public", "Public session"), type: "checkbox", value: false },
      ],
    });
    if (!data) return;
    const title = String(data.title || "").trim();
    if (!title) {
      ctx.log("Session title is required.", "warn");
      return;
    }
    const isPublic = Boolean(data.is_public);
    await ctx.apiJson(`/v1/projects/${encodeURIComponent(state.selectedPid)}/sessions`, {
      method: "POST",
      body: { title, is_public: Boolean(isPublic) },
      headers: { "X-Project-Id": state.selectedPid },
    });
    await refreshSessions();
    await host.refreshSessions();
  }

  async function setProjectVisibility(pid, value) {
    if (!hasAuth || !pid) return;
    await ctx.apiJson(`/v1/projects/${encodeURIComponent(pid)}/visibility`, {
      method: "PUT",
      body: { is_public: Boolean(value) },
      headers: { "X-Project-Id": pid },
    });
  }

  async function setSessionVisibility(pid, sid, value) {
    if (!hasAuth || !pid || !sid) return;
    await ctx.apiJson(
      `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/visibility`,
      {
        method: "PUT",
        body: { is_public: Boolean(value) },
        headers: { "X-Project-Id": pid, "X-Session-Id": sid },
      }
    );
  }

  async function requestJoin() {
    if (!hasAuth || !state.selectedPid || !state.selectedSid) return;
    await ctx.apiJson(
      `/v1/projects/${encodeURIComponent(state.selectedPid)}/sessions/${encodeURIComponent(state.selectedSid)}/join_requests`,
      {
        method: "POST",
        body: {},
        headers: { "X-Project-Id": state.selectedPid, "X-Session-Id": state.selectedSid },
      }
    );
    ctx.log("Join request submitted.", "info");
  }

  async function refreshRequests() {
    reqList.innerHTML = "";
    if (!state.selectedPid || !state.selectedSid) return;
    const data = await ctx.apiJson(
      `/v1/projects/${encodeURIComponent(state.selectedPid)}/sessions/${encodeURIComponent(state.selectedSid)}/join_requests`,
      {
        headers: { "X-Project-Id": state.selectedPid, "X-Session-Id": state.selectedSid },
      }
    );
    const items = data.requests || data.join_requests || [];
    items.forEach((it) => {
      const rid = (it.req_id || it.rid || it.id || "").trim();
      const user = (it.user || it.username || it.alias || "").trim();
      const ts = it.created_ts || it.ts || it.created_at || "";
      if (!rid) return;
      const row = document.createElement("div");
      row.className = "list-item";
      row.dataset.rid = rid;
      row.innerHTML = `<div class="list-title">${user || "user"}</div><div class="list-meta">${rid} ${ts}</div>`;
      row.addEventListener("click", () => {
        reqList.querySelectorAll(".list-item").forEach((el) => el.classList.remove("active"));
        row.classList.add("active");
      });
      reqList.appendChild(row);
    });
  }

  async function approveRequest(yes) {
    const selected = reqList.querySelector(".list-item.active");
    if (!selected) return;
    const rid = selected.dataset.rid;
    if (!rid) return;
    const action = yes ? "approve" : "deny";
    await ctx.apiJson(
      `/v1/projects/${encodeURIComponent(state.selectedPid)}/sessions/${encodeURIComponent(state.selectedSid)}/join_requests/${encodeURIComponent(rid)}/${action}`,
      {
        method: "POST",
        body: {},
        headers: { "X-Project-Id": state.selectedPid, "X-Session-Id": state.selectedSid },
      }
    );
    await refreshRequests();
  }

  function toggleModal(show) {
    modal.classList.toggle("hidden", !show);
  }

  actionRow.appendChild(button("Refresh", "ghost", async () => {
    await refreshProjects();
  }));
  actionRow.appendChild(button("Request Join", "ghost", async () => {
    await requestJoin();
  }));
  actionRow.appendChild(button("Approve Requests", "ghost", async () => {
    toggleModal(true);
    await refreshRequests();
  }));

  reqRefresh.addEventListener("click", refreshRequests);
  reqApprove.addEventListener("click", () => approveRequest(true));
  reqDeny.addEventListener("click", () => approveRequest(false));
  reqClose.addEventListener("click", () => toggleModal(false));
  modal.addEventListener("click", (event) => {
    if (event.target === modal) toggleModal(false);
  });

  if (hasAuth) {
    runAsyncTask(() => refreshProjects(), (err) => logAsyncError(ctx, "refresh_projects", err));
  }
}

function buildAdminPanel(panel, ctx, host) {
  panel.innerHTML = "";

  const token = ((ctx.state.auth || {}).token || "").trim();
  const role = (ctx.state.auth || {}).role || "";
  if (!token || role !== "admin") {
    const msg = document.createElement("div");
    msg.className = "muted";
    msg.textContent = authT("auth_projects.admin.access_required", "Admin access required.");
    panel.appendChild(msg);
    return;
  }

  const tabs = document.createElement("div");
  tabs.className = "auth-subtabs";
  panel.appendChild(tabs);

  const panels = document.createElement("div");
  panel.appendChild(panels);

  const usersPanel = document.createElement("div");
  usersPanel.className = "auth-panel active";
  panels.appendChild(usersPanel);

  const membersPanel = document.createElement("div");
  membersPanel.className = "auth-panel";
  panels.appendChild(membersPanel);

  const promptsPanel = document.createElement("div");
  promptsPanel.className = "auth-panel";
  panels.appendChild(promptsPanel);

  const usersBtn = document.createElement("button");
  usersBtn.className = "auth-tab active";
  usersBtn.textContent = authT("auth_projects.admin.users", "Users");
  const membersBtn = document.createElement("button");
  membersBtn.className = "auth-tab";
  membersBtn.textContent = authT("auth_projects.admin.project_members", "Project Members");
  const promptBtn = document.createElement("button");
  promptBtn.className = "auth-tab";
  promptBtn.textContent = authT("auth_projects.admin.collab_system_prompt", "Collab System Prompt");
  tabs.appendChild(usersBtn);
  tabs.appendChild(membersBtn);
  tabs.appendChild(promptBtn);

  function showAdminTab(which) {
    const usersOn = which === "users";
    const membersOn = which === "members";
    const promptsOn = which === "prompts";
    usersBtn.classList.toggle("active", usersOn);
    membersBtn.classList.toggle("active", membersOn);
    promptBtn.classList.toggle("active", promptsOn);
    usersPanel.classList.toggle("active", usersOn);
    membersPanel.classList.toggle("active", membersOn);
    promptsPanel.classList.toggle("active", promptsOn);
  }

  usersBtn.addEventListener("click", () => showAdminTab("users"));
  membersBtn.addEventListener("click", () => showAdminTab("members"));
  promptBtn.addEventListener("click", () => showAdminTab("prompts"));

  buildUsersTab(usersPanel, ctx);
  buildMembersTab(membersPanel, ctx);
  buildCollabPromptsTab(promptsPanel, ctx)
}

function buildCollabPromptsTab(panel, ctx) {
  panel.innerHTML = "";

  const header = document.createElement("div");
  header.className = "section-title";
  header.textContent = authT("auth_projects.prompts.title", "Collab System Prompts");
  panel.appendChild(header);

  const meta = document.createElement("div");
  meta.className = "auth-meta";
  meta.textContent = "These prompts can be selected per project/session and injected as a system message when AI responds.";
  panel.appendChild(meta);

  const list = document.createElement("div");
  list.className = "list auth-list tall";
  panel.appendChild(list);

  const nameInput = document.createElement("input");
  const promptInput = document.createElement("textarea");
  promptInput.style.minHeight = "140px";
  promptInput.style.resize = "vertical";

  panel.appendChild(field("Name", nameInput));
  panel.appendChild(field(authT("auth_projects.prompts.system_prompt", "System prompt"), promptInput));

  const actions = document.createElement("div");
  actions.className = "auth-actions auth-form-actions";
  panel.appendChild(actions);

  let currentId = "";

  async function refresh() {
    list.innerHTML = "";
    const res = await ctx.apiJson("/v1/collab_prompts");
    const prompts = res.prompts || [];
    prompts.forEach((p) => {
      const item = document.createElement("div");
      item.className = "list-item";
      item.innerHTML = `<div class="list-title">${p.name}</div><div class="list-meta">${p.prompt_id}</div>`;
      item.addEventListener("click", () => {
        currentId = p.prompt_id;
        nameInput.value = p.name || "";
        promptInput.value = p.prompt || "";
      });
      list.appendChild(item);
    });
  }

  async function addNew() {
    currentId = "";
    nameInput.value = "";
    promptInput.value = "";
    nameInput.focus();
  }

  async function save() {
    const name = String(nameInput.value || "").trim();
    const prompt = String(promptInput.value || "").trim();
    if (!name || !prompt) {
      ctx.log("Name and prompt required.", "warn");
      return;
    }
    const payload = { name, prompt };
    if (currentId) payload.prompt_id = currentId;
    const res = await ctx.apiJson("/v1/collab_prompts", { method: "POST", body: payload });
    currentId = res.prompt_id || currentId;
    await refresh();
  }

  actions.appendChild(button("Refresh", "ghost", refresh));
  actions.appendChild(button(authT("auth_projects.common.new", "New"), "ghost", addNew));
  actions.appendChild(button("Save", "primary", save));

  runAsyncTask(() => refresh(), (err) => logAsyncError(ctx, "refresh_collab_prompts", err));
}

function buildUsersTab(panel, ctx) {
  panel.innerHTML = "";

  const grid = document.createElement("div");
  grid.className = "auth-admin-grid";
  panel.appendChild(grid);

  const leftCol = document.createElement("div");
  leftCol.className = "auth-column";
  grid.appendChild(leftCol);

  const rightCol = document.createElement("div");
  rightCol.className = "auth-column";
  grid.appendChild(rightCol);

  const usersHeader = document.createElement("div");
  usersHeader.className = "section-title";
  usersHeader.textContent = authT("auth_projects.admin.users", "Users");
  leftCol.appendChild(usersHeader);

  const list = document.createElement("div");
  list.className = "list auth-list tall";
  leftCol.appendChild(list);

  const listActions = document.createElement("div");
  listActions.className = "auth-actions";
  leftCol.appendChild(listActions);

  const userInput = document.createElement("input");
  const roleSelect = selectOptions(["user", "admin"]);
  const projectsInput = document.createElement("input");
  const tempInput = document.createElement("input");
  tempInput.type = "password";

  rightCol.appendChild(field("Username", userInput));
  rightCol.appendChild(field("Role", roleSelect));
  rightCol.appendChild(field("Project scope (comma list, blank=ALL)", projectsInput));
  rightCol.appendChild(field("Temp Password (set/reset)", tempInput));

  const actionRow = document.createElement("div");
  actionRow.className = "auth-actions";
  rightCol.appendChild(actionRow);

  async function refreshUsers() {
    list.innerHTML = "";
    const data = await ctx.apiJson("/v1/auth/users");
    const users = data.users || data.items || [];
    users.forEach((u) => {
      const uname = (u.username || u.user || "").trim();
      if (!uname) return;
      const item = document.createElement("div");
      item.className = "list-item";
      item.textContent = uname;
      item.addEventListener("click", () => {
        userInput.value = uname;
        void loadUser(uname);
      });
      list.appendChild(item);
    });
  }

  async function loadUser(username) {
    const data = await ctx.apiJson(`/v1/auth/users/${encodeURIComponent(username)}`);
    const user = data.user || data;
    roleSelect.value = String(user.role || "user");
    const scope = user.projects;
    if (scope === null || scope === undefined) {
      projectsInput.value = "";
    } else if (Array.isArray(scope)) {
      projectsInput.value = scope.join(",");
    } else {
      projectsInput.value = String(scope);
    }
  }

  async function saveUser() {
    const username = userInput.value.trim();
    if (!username) {
      ctx.log("Username required.", "warn");
      return;
    }
    const tempPw = tempInput.value.trim();
    if (!tempPw) {
      ctx.log("Temp password required.", "warn");
      return;
    }
    const scope = projectsInput.value
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const payload = {
      username,
      password: tempPw,
      role: roleSelect.value || "user",
    };
    if (scope.length) {
      payload.projects = scope;
    }
    await ctx.apiJson("/v1/auth/users", { method: "POST", body: payload });
    tempInput.value = "";
    await refreshUsers();
  }

  async function deleteUser() {
    const username = userInput.value.trim();
    if (!username) return;
    if (username === "admin") {
      ctx.log("Refusing to delete admin.", "warn");
      return;
    }
    const ok = await openConfirm({
      title: authT("auth_projects.users.delete", "Delete User"),
      message: `Delete user '${username}'?`,
      confirmLabel: "Delete",
    });
    if (!ok) return;
    await ctx.apiJson(`/v1/auth/users/${encodeURIComponent(username)}`, { method: "DELETE" });
    await refreshUsers();
  }

  listActions.appendChild(button("Refresh", "ghost", refreshUsers));
  actionRow.appendChild(button("Save/Add", "primary", saveUser));
  actionRow.appendChild(button("Delete", "ghost", deleteUser));

  void refreshUsers();
}

function buildMembersTab(panel, ctx) {
  panel.innerHTML = "";

  const grid = document.createElement("div");
  grid.className = "auth-admin-grid";
  panel.appendChild(grid);

  const leftCol = document.createElement("div");
  leftCol.className = "auth-column";
  grid.appendChild(leftCol);

  const rightCol = document.createElement("div");
  rightCol.className = "auth-column";
  grid.appendChild(rightCol);

  const row = document.createElement("div");
  row.className = "auth-inline";
  leftCol.appendChild(row);

  const projectSelect = document.createElement("select");
  row.appendChild(field("Project", projectSelect));

  const membersHeader = document.createElement("div");
  membersHeader.className = "section-title";
  membersHeader.textContent = authT("auth_projects.members.title", "Members");
  leftCol.appendChild(membersHeader);

  const list = document.createElement("div");
  list.className = "list auth-list tall";
  leftCol.appendChild(list);

  const refreshBtn = button("Refresh members", "ghost", refreshMembers);
  leftCol.appendChild(refreshBtn);

  const userInput = document.createElement("input");
  const roleSelect = selectOptions(["member", "admin", "owner"]);
  rightCol.appendChild(field("Username", userInput));
  rightCol.appendChild(field("Role", roleSelect));

  const actions = document.createElement("div");
  actions.className = "auth-actions";
  rightCol.appendChild(actions);

  async function refreshProjects() {
    projectSelect.innerHTML = "";
    const data = await ctx.apiJson("/v1/projects");
    const projects = data.projects || [];
    projects.forEach((p) => {
      if (!p.pid) return;
      const opt = document.createElement("option");
      opt.value = p.pid;
      opt.textContent = p.pid;
      projectSelect.appendChild(opt);
    });
    if (projectSelect.options.length) {
      projectSelect.value = projectSelect.options[0].value;
    }
  }

  async function refreshMembers() {
    const pid = projectSelect.value;
    if (!pid) return;
    list.innerHTML = "";
    const data = await ctx.apiJson(`/v1/projects/${encodeURIComponent(pid)}/members`, {
      headers: { "X-Project-Id": pid },
    });
    const members = data.members || [];
    members.forEach((m) => {
      const uname = (m.username || m.user || "").trim();
      const role = (m.role || "member").trim();
      if (!uname) return;
      const item = document.createElement("div");
      item.className = "list-item";
      item.dataset.username = uname;
      item.dataset.role = role;
      item.innerHTML = `<div class="list-title">${uname}</div><div class="list-meta">${role}</div>`;
      item.addEventListener("click", () => {
        userInput.value = uname;
        roleSelect.value = role;
      });
      list.appendChild(item);
    });
  }

  async function addMember() {
    const pid = projectSelect.value;
    const username = userInput.value.trim();
    if (!pid || !username) return;
    await ctx.apiJson(`/v1/projects/${encodeURIComponent(pid)}/members`, {
      method: "POST",
      body: { username, role: roleSelect.value },
      headers: { "X-Project-Id": pid },
    });
    await refreshMembers();
  }

  async function removeMember() {
    const pid = projectSelect.value;
    const username = userInput.value.trim();
    if (!pid || !username) return;
    const ok = await openConfirm({
      title: authT("auth_projects.members.remove", "Remove Member"),
      message: `Remove '${username}' from project '${pid}'?`,
      confirmLabel: "Remove",
    });
    if (!ok) return;
    await ctx.apiJson(`/v1/projects/${encodeURIComponent(pid)}/members/${encodeURIComponent(username)}`, {
      method: "DELETE",
      headers: { "X-Project-Id": pid },
    });
    await refreshMembers();
  }

  projectSelect.addEventListener("change", () => {
    void refreshMembers();
  });

  actions.appendChild(button("Add/Update", "primary", addMember));
  actions.appendChild(button("Remove", "ghost", removeMember));

  void refreshProjects().then(refreshMembers);
}

function buildLoginPanel(panel, ctx, host, root) {
  panel.innerHTML = "";

  const userInput = document.createElement("input");
  const passInput = document.createElement("input");
  passInput.type = "password";

  panel.appendChild(field("Username", userInput));
  panel.appendChild(field("Password", passInput));

  const actions = document.createElement("div");
  actions.className = "auth-actions";
  panel.appendChild(actions);

  const status = document.createElement("div");
  status.className = "muted";
  panel.appendChild(status);

  function updateStatus() {
    const token = ((ctx.state.auth || {}).token || "").trim();
    if (token) {
      status.textContent = "";
    } else {
      status.textContent = "";
    }
  }

  actions.appendChild(button(authT("auth_projects.tabs.login", "Login"), "primary", async () => {
    const username = userInput.value.trim();
    const password = passInput.value;
    const res = await host.login(username, password);
    if (res?.ok) {
      passInput.value = "";
      renderPanel(root, ctx, host);
      await host.refreshProjects();
    }
  }));
  const token = ((ctx.state.auth || {}).token || "").trim();
  if (token) {
    actions.appendChild(button(authT("auth_projects.account.logout", "Logout"), "ghost", async () => {
      await host.logout(true);
      renderPanel(root, ctx, host);
    }));
  }

  updateStatus();
}

function openLoginModal(host) {
  closeAllAuthModals();
  const state = (typeof host?.getState === "function" ? host.getState() : null) || lastRenderCtx?.state || {};
  const authed = Boolean(((state?.auth || {}).token || "").trim());
  const title = authed
    ? authT("auth_projects.account.switch_user", "Switch User")
    : authT("auth_projects.tabs.login", "Login");
  const { card, close } = openModal(title);
  const userInput = document.createElement("input");
  const passInput = document.createElement("input");
  passInput.type = "password";
  card.appendChild(field("Username", userInput));
  card.appendChild(field("Password", passInput));
  const status = document.createElement("div");
  status.className = "muted";
  card.appendChild(status);

  const actions = document.createElement("div");
  actions.className = "auth-actions";
  card.appendChild(actions);

  actions.appendChild(button(authT("auth_projects.tabs.login", "Login"), "primary", async () => {
    const username = userInput.value.trim();
    const password = passInput.value;
    status.textContent = "";
    const res = await host.login(username, password);
    if (res?.ok) {
      closeAllAuthModals();
      rerenderPanel();
      await host.refreshProjects();
      return;
    }
    const raw = String(res?.error?.message || res?.error || authT("auth_projects.login_failed", "Login failed"));
    const detailMatch = raw.match(/\{.*\}/);
    if (detailMatch) {
      try {
        const parsed = JSON.parse(detailMatch[0]);
        status.textContent = String(parsed?.detail || parsed?.error || raw);
        return;
      } catch (_err) {}
    }
    status.textContent = raw;
  }));
  actions.appendChild(button("Cancel", "ghost", close));
}

function openChangePasswordModal(ctx) {
  const { card, close } = openModal(authT("auth_projects.account.change_password", "Change Password"));
  const oldInput = document.createElement("input");
  oldInput.type = "password";
  const newInput = document.createElement("input");
  newInput.type = "password";
  card.appendChild(field("Old Password", oldInput));
  card.appendChild(field("New Password", newInput));

  const actions = document.createElement("div");
  actions.className = "auth-actions";
  card.appendChild(actions);

  actions.appendChild(button("Change", "primary", async () => {
    const oldPw = oldInput.value;
    const newPw = newInput.value;
    if (!oldPw || !newPw) return;
    try {
      await ctx.apiJson("/v1/auth/change_password", {
        method: "POST",
        body: { old_password: oldPw, new_password: newPw },
      });
      close();
    } catch (err) {
      ctx.log(`Change password failed: ${err.message || err}`, "warn");
    }
  }));
  actions.appendChild(button("Cancel", "ghost", close));
}

async function openAboutModal(ctx) {
  const { card, close } = openModal("About");
  const aboutState = {
    updateAvailable: false,
    downloadUrl: "",
    latestVersion: "",
    targetVersion: "",
    targetTag: "",
    targetCommit: "",
    busy: false,
  };
  const infoGrid = document.createElement("div");
  infoGrid.className = "auth-about-grid";
  card.appendChild(infoGrid);

  const fields = {};
  const addInfo = (label) => {
    const box = document.createElement("div");
    box.className = "auth-about-card";
    const title = document.createElement("div");
    title.className = "auth-about-label";
    title.textContent = label;
    const value = document.createElement("div");
    value.className = "auth-about-value";
    value.textContent = "-";
    box.appendChild(title);
    box.appendChild(value);
    infoGrid.appendChild(box);
    return value;
  };

  fields.installedVersion = addInfo("Installed version");
  fields.latestVersion = addInfo("Latest version");
  fields.branch = addInfo("Git branch");
  fields.repoSlug = addInfo("Repository");

  const adminRow = document.createElement("div");
  adminRow.className = "auth-about-inline";
  const installedInput = document.createElement("input");
  installedInput.type = "text";
  installedInput.placeholder = "Set installed version";
  const saveBtn = button(authT("auth_projects.common.save", "Save"), "ghost", async () => {
    saveBtn.disabled = true;
    try {
      await ctx.apiJson("/v1/plugin_repo/app_update/local", {
        method: "POST",
        body: {
          app_slug: APP_UPDATE_SLUG,
          name: APP_UPDATE_NAME,
          current_version: installedInput.value.trim(),
        },
      });
      status.textContent = "Installed version saved.";
      await refresh();
    } catch (err) {
      status.textContent = `Save failed: ${err.message || err}`;
    } finally {
      saveBtn.disabled = false;
    }
  });
  adminRow.appendChild(installedInput);
  adminRow.appendChild(saveBtn);
  card.appendChild(adminRow);

  const status = document.createElement("div");
  status.className = "auth-about-status";
  card.appendChild(status);

  const actions = document.createElement("div");
  actions.className = "auth-about-actions";
  card.appendChild(actions);

  const checkBtn = button("Check for update", "primary", async () => {
    if (aboutState.updateAvailable) {
      await runUpdate("patch");
      return;
    }
    await refresh(true);
  });
  const fullBtn = button("Full update", "ghost", async () => {
    await runUpdate("full");
  });
  const restartBtn = button("Restart server", "ghost", async () => {
    await restartServer();
  });
  const closeBtn = button(authT("auth_projects.common.close", "Close"), "ghost", close);
  actions.appendChild(checkBtn);
  actions.appendChild(fullBtn);
  actions.appendChild(restartBtn);
  actions.appendChild(closeBtn);

  const logWrap = document.createElement("div");
  logWrap.className = "auth-about-log";
  card.appendChild(logWrap);

  const renderGitLog = (items) => {
    logWrap.innerHTML = "";
    const list = Array.isArray(items) ? items : [];
    if (!list.length) {
      const empty = document.createElement("div");
      empty.className = "auth-about-empty";
      empty.textContent = "No git history available.";
      logWrap.appendChild(empty);
      return;
    }
    list.slice(0, 12).forEach((item) => {
      const row = document.createElement("div");
      row.className = "auth-about-log-item";
      const subject = document.createElement("div");
      subject.className = "auth-about-log-subject";
      subject.textContent = String(item?.subject || item?.Subject || "(no subject)");
      const meta = document.createElement("div");
      meta.className = "auth-about-log-meta";
      const hash = String(item?.hash || item?.Hash || "").trim();
      const author = String(item?.author || item?.Author || "").trim();
      const date = String(item?.date || item?.Date || "").trim();
      meta.textContent = [hash, author, date].filter(Boolean).join(" | ");
      row.appendChild(subject);
      row.appendChild(meta);
      logWrap.appendChild(row);
    });
  };

  const refresh = async (manual) => {
    status.textContent = manual ? "Checking for update..." : "Loading version info...";
    setBusy(true);
    try {
      const payload = await ctx.apiJson(`/v1/plugin_repo/app_update/check?slug=${encodeURIComponent(APP_UPDATE_SLUG)}`);
      const local = payload?.local || {};
      const remote = payload?.remote || {};
      const currentVersion = String(payload?.current_version || local?.current_version || "").trim();
      const latestVersion = String(payload?.latest_version || remote?.LatestVersion || remote?.latestVersion || "").trim();
      const updateAvailable = Boolean(payload?.update_available);
      aboutState.updateAvailable = updateAvailable;
      aboutState.latestVersion = latestVersion;
      aboutState.targetVersion = latestVersion;
      aboutState.targetTag = String((remote?.Versions || [])[0]?.Tag || "").trim();
      aboutState.targetCommit = String((remote?.Versions || [])[0]?.Commit || "").trim();
      aboutState.downloadUrl = String(remote?.DownloadUrl || remote?.downloadUrl || "").trim();
      fields.installedVersion.textContent = currentVersion || "unversioned local build";
      fields.latestVersion.textContent = latestVersion || "not published";
      fields.branch.textContent = String(local?.git_branch || "-");
      fields.repoSlug.textContent = String(remote?.RepoSlug || remote?.repoSlug || "-");
      installedInput.value = currentVersion;
      checkBtn.textContent = updateAvailable && latestVersion ? `Update to version ${latestVersion}` : "Check for update";
      status.textContent = updateAvailable && latestVersion
        ? `Update available: ${currentVersion || "local"} -> ${latestVersion}`
        : (aboutState.restartRequired ? "Update applied. Restart the server to load the new code." : "You are up to date.");
      syncActionVisibility();
      const gitItems = await ctx.apiJson(`/v1/plugin_repo/app_update/gitlog?slug=${encodeURIComponent(APP_UPDATE_SLUG)}&limit=12`).catch(() => []);
      renderGitLog(gitItems);
    } catch (err) {
      status.textContent = `Update check failed: ${err.message || err}`;
      renderGitLog([]);
    } finally {
      setBusy(false);
    }
  };

  const syncActionVisibility = () => {
    const showUpdateActions = !!isAdmin && !!aboutState.updateAvailable;
    const showRestart = !!isAdmin && !!aboutState.restartRequired;
    fullBtn.style.display = showUpdateActions ? "" : "none";
    restartBtn.style.display = showRestart ? "" : "none";
  };

  const setBusy = (busy) => {
    aboutState.busy = !!busy;
    checkBtn.disabled = !!busy;
    fullBtn.disabled = !!busy || !aboutState.updateAvailable;
    restartBtn.disabled = !!busy || !aboutState.restartRequired;
    installedInput.disabled = !!busy;
    saveBtn.disabled = !!busy;
    syncActionVisibility();
  };

  const runUpdate = async (mode) => {
    if (!aboutState.updateAvailable) {
      status.textContent = "No update available.";
      return;
    }
    setBusy(true);
    status.textContent = mode === "patch" ? "Applying patch update..." : "Applying full update...";
    try {
      const payload = await ctx.apiJson("/v1/plugin_repo/app_update/apply", {
        method: "POST",
        body: {
          slug: APP_UPDATE_SLUG,
          version: aboutState.targetVersion,
          tag: aboutState.targetTag,
          commit: aboutState.targetCommit,
          mode,
        },
      });
      const result = payload?.result || {};
      aboutState.restartRequired = true;
      status.textContent = `${mode === "patch" ? "Patch" : "Full"} update applied: ${result.copied_files || 0} file(s) updated, ${result.unchanged_files || 0} unchanged. Restart the server to load the new code.`;
      await refresh(false);
    } catch (err) {
      status.textContent = `${mode === "patch" ? "Patch" : "Full"} update failed: ${err.message || err}`;
    } finally {
      setBusy(false);
    }
  };

  const restartServer = async () => {
    setBusy(true);
    status.textContent = "Queueing server restart...";
    try {
      await ctx.apiJson("/v1/plugin_repo/restart_server", {
        method: "POST",
        body: {
          reason: "about_app_update_restart",
        },
      });
      aboutState.restartRequired = false;
      status.textContent = "Server restart queued through the host service.";
      syncActionVisibility();
    } catch (err) {
      status.textContent = `Restart failed: ${err.message || err}`;
    } finally {
      setBusy(false);
    }
  };

  const isAdmin = String(ctx?.state?.auth?.role || "").toLowerCase() === "admin";
  aboutState.restartRequired = false;
  adminRow.style.display = isAdmin ? "" : "none";
  syncActionVisibility();
  await refresh(false);
}

function openRosterModal(ctx, host) {
  const { card, close } = openModal("Roster");
  const columns = document.createElement("div");
  columns.className = "auth-columns";
  card.appendChild(columns);

  const left = document.createElement("div");
  left.className = "auth-column";
  columns.appendChild(left);

  const right = document.createElement("div");
  right.className = "auth-column";
  columns.appendChild(right);

  const leftTitle = document.createElement("div");
  leftTitle.className = "section-title";
  leftTitle.textContent = authT("auth_projects.roster.in_chat", "In chat");
  left.appendChild(leftTitle);

  const rosterList = document.createElement("div");
  rosterList.className = "list auth-list";
  left.appendChild(rosterList);

  const rightTitle = document.createElement("div");
  rightTitle.className = "section-title";
  rightTitle.textContent = authT("auth_projects.roster.join_requests", "Join requests");
  right.appendChild(rightTitle);

  const requestList = document.createElement("div");
  requestList.className = "list auth-list";
  right.appendChild(requestList);

  const actions = document.createElement("div");
  actions.className = "auth-actions";
  card.appendChild(actions);
  actions.appendChild(button("Refresh", "ghost", () => void refresh()));
  actions.appendChild(button("Close", "ghost", close));

  async function refresh() {
    rosterList.innerHTML = "";
    requestList.innerHTML = "";

    const roster = ctx.state.roster || [];
    if (!roster.length) {
      const empty = document.createElement("div");
      empty.className = "muted";
      empty.textContent = authT("auth_projects.roster.empty", "No one in chat yet.");
      rosterList.appendChild(empty);
    } else {
      roster.forEach((row) => {
        const item = document.createElement("div");
        item.className = "auth-roster-row";
        const label = row.alias || row.username || "user";
        const rawUser = String(row.username || "").trim();
        const meta = rawUser.startsWith("guest:") ? "guest" : rawUser;
        item.innerHTML = `<div class="list-title">${label}</div><div class="list-meta">${meta}</div>`;
        rosterList.appendChild(item);
      });
    }

    const token = ((ctx.state.auth || {}).token || "").trim();
    const pid = ctx.state.ui.activePid;
    const sid = ctx.state.ui.activeSid;
    if (!token) {
      const msg = document.createElement("div");
      msg.className = "muted";
      msg.textContent = authT("auth_projects.roster.login_required", "Login required to view requests.");
      requestList.appendChild(msg);
      return;
    }
    if (!pid || !sid) {
      const msg = document.createElement("div");
      msg.className = "muted";
      msg.textContent = authT("auth_projects.roster.select_scope", "Select a project/session.");
      requestList.appendChild(msg);
      return;
    }
    try {
      const data = await ctx.apiJson(
        `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/join_requests`,
        { headers: { "X-Project-Id": pid, "X-Session-Id": sid } },
      );
      const items = data.requests || data.join_requests || [];
      if (!items.length) {
        const msg = document.createElement("div");
        msg.className = "muted";
        msg.textContent = authT("auth_projects.roster.no_pending", "No pending requests.");
        requestList.appendChild(msg);
      } else {
        items.forEach((it) => {
          const user = (it.user || it.username || it.alias || "").trim();
          const rid = (it.req_id || it.rid || it.id || "").trim();
          const ts = it.created_ts || it.ts || it.created_at || "";
          const row = document.createElement("div");
          row.className = "list-item auth-request-row";
          row.dataset.rid = rid;
          const main = document.createElement("div");
          main.className = "auth-request-main";
          main.innerHTML = `<div class="list-title">${user || "user"}</div><div class="list-meta">${rid} ${ts}</div>`;
          row.appendChild(main);
          const rowActions = document.createElement("div");
          rowActions.className = "auth-request-actions";
          const approveBtn = button("Approve", "primary", async (event) => {
            event.stopPropagation();
            await approveRequest(rid, true, approveBtn, denyBtn);
          });
          const denyBtn = button("Deny", "ghost", async (event) => {
            event.stopPropagation();
            await approveRequest(rid, false, approveBtn, denyBtn);
          });
          rowActions.appendChild(approveBtn);
          rowActions.appendChild(denyBtn);
          row.appendChild(rowActions);
          requestList.appendChild(row);
        });
      }
    } catch (err) {
      const msg = document.createElement("div");
      msg.className = "muted";
      msg.textContent = `Failed to load requests.`;
      requestList.appendChild(msg);
    }
  }

  async function approveRequest(rid, yes, ...buttons) {
    if (!rid) return;
    const pid = ctx.state.ui.activePid;
    const sid = ctx.state.ui.activeSid;
    if (!pid || !sid) return;
    const action = yes ? "approve" : "deny";
    buttons.forEach((btn) => {
      if (btn) btn.disabled = true;
    });
    await ctx.apiJson(
      `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/join_requests/${encodeURIComponent(rid)}/${action}`,
      { method: "POST", body: {}, headers: { "X-Project-Id": pid, "X-Session-Id": sid } },
    );
    await refresh();
  }

  void refresh();
}

const plugin = {
  id: meta.plugin_id,
  name: meta.name,
  kind: meta.kind,
  description: meta.description,
  meta,
  register(host) {
    try {
      host.registerI18nBundle?.({
        id: meta.plugin_id,
        pluginId: meta.plugin_id,
        basePath: new URL("./lang/", import.meta.url).toString(),
        languages: I18N_LANGUAGES,
        defaultLanguage: "en",
      });
      host.onLanguageChange?.(() => rerenderLastAuthPanel());
    } catch (_err) {}

    host.enableAccountMenu();
    // Provide the styled project/session creation windows to the core UI dropdowns.
    host.setProjectCreateHandler((ctx) => openNewProjectWindow(ctx, host));
    host.setSessionCreateHandler((ctx, opts = {}) => openNewSessionWindow(ctx, host, opts?.pid));

    host.setAccountActions([
      {
        id: "login",
        label: authT("auth_projects.tabs.login", "Login"),
        showWhenLoggedOut: true,
        hideWhenLoggedIn: true,
        onClick: () => {
          openLoginModal(host);
        },
      },
      {
        id: "switch-user",
        label: authT("auth_projects.account.switch_user", "Switch User"),
        requiresAuth: true,
        onClick: () => {
          openLoginModal(host);
        },
      },
      {
        id: "change-password",
        label: authT("auth_projects.account.change_password", "Change Password"),
        requiresAuth: true,
        onClick: (ctx) => {
          const token = ((ctx.state.auth || {}).token || "").trim();
          if (!token) {
            openLoginModal(host);
            return;
          }
          openChangePasswordModal(ctx);
        },
      },
      {
        id: "logout",
        label: authT("auth_projects.account.logout", "Logout"),
        requiresAuth: true,
        onClick: () => {
          host.logout(true);
        },
      },
      {
        id: "about",
        label: "About",
        requiresAuth: false,
        showWhenLoggedOut: true,
        onClick: (ctx) => {
          void openAboutModal(ctx);
        },
      },
    ]);

    host.setChatsOverride({
      title: authT("auth_projects.tabs.remote_projects", "Remote Projects"),
      render: (container, ctx) => {
        renderPanel(container, ctx, host, { defaultTab: "remote" });
      },
    });

    scheduleBootstrapAdminWizardChecks(host, () => lastRenderCtx || { state: host.getState?.() || {} });
    window.addEventListener("chatjs:auth-changed", (event) => {
      const loggedIn = Boolean(event?.detail?.loggedIn);
      bootstrapWizardInFlight = false;
      if (loggedIn) {
        bootstrapWizardChecked = true;
        clearBootstrapWizardRetryTimers();
        return;
      }
      bootstrapWizardChecked = false;
      scheduleBootstrapAdminWizardChecks(host, () => lastRenderCtx || { state: host.getState?.() || {} });
    });

    host.addRosterAction((ctx) => {
      const token = ((ctx.state.auth || {}).token || "").trim();
      if (!token) {
        openLoginModal(host);
        return;
      }
      openRosterModal(ctx, host);
    });

    // host.addSendHook((_payload, ctx) => {
    //   const token = ((ctx.state.auth || {}).token || "").trim();
    //   if (token) return null;
    //   host.openTools("account");
    //   host.log("Login required (Auth/Projects).", "warn");
    //   return { cancel: true };
    // });

    host.addSendHook((payload, ctx2) => {
      const remoteState = (ctx2.state.auth_projects || {}).remote || {};
      const projs = remoteState.projects || [];
      const sessByPid = remoteState.sessionsByPid || {};

      const hostProj = ctx2.state.projects ? ctx2.state.projects[payload.pid] : null;
      const hostSess = ctx2.state.sessions ? ctx2.state.sessions[payload.sid] : null;
      const proj = hostProj || projs.find((p) => p.pid === payload.pid) || null;
      const sess = (hostSess && hostSess.pid === payload.pid)
        ? hostSess
        : (sessByPid[payload.pid] || []).find((s) => s.sid === payload.sid) || null;

      const effAi = getAiToggle(ctx2, payload.pid, payload.sid);

      const st = getCollabState(ctx2);
      if (payload?.handled) return;

      if (st.forceAiOnce) {
        // let normal flow continue (AI on)
        st.forceAiOnce = false;
        ctx2.saveState?.();
        return;
      }

      if (effAi) {
        for (const bridge of getAiRouterBridges(ctx2)) {
          try {
            if (typeof bridge?.shouldHandle === "function" && bridge.shouldHandle(payload, ctx2)) {
              void callAiRouterBridgeTurn(payload, ctx2, bridge).catch((err) => {
                ctx2.log?.(`[${String(bridge?.routeId || bridge?.id || "ai_router")}] ${err?.message || err}`, "error");
              });
              return { handled: true };
            }
          } catch (err) {
            ctx2.log?.(`[${String(bridge?.routeId || bridge?.id || "ai_router")}] ${err?.message || err}`, "error");
          }
        }
      }

      if (!effAi) {
        // AI default OFF: plugin posts message to server, framework stops.
        void (async () => {
          await ctx2.apiJson(`/v1/projects/${encodeURIComponent(payload.pid)}/sessions/${encodeURIComponent(payload.sid)}/messages_no_ai`, {
            method: "POST",
            headers: { "X-Project-Id": payload.pid, "X-Session-Id": payload.sid },
            body: {
              content: payload.text,
              alias: ctx2.state.auth?.alias || undefined,
              client_msg_id: payload.client_msg_id,
              meta: { client_msg_id: payload.client_msg_id },
            },
          });
        })();
        return { handled: true };
      }
    }, { timeoutMs: 240000 });

    host.addCompletionPayloadHook((body, ctx2) => {
      const pid = ctx2.state.ui.activePid;
      const sid = ctx2.state.ui.activeSid;
      if (!pid || !sid) return body;

      body.ext = body.ext || {};
      const clientMsgId = String(body?.client_msg_id || "").trim();
      let forcedBridge = null;
      for (const bridge of getAiRouterBridges(ctx2)) {
        const pending = consumePendingAiRouterBridge(ctx2, bridge, clientMsgId);
        let force = Boolean(pending);
        if (!force) {
          try {
            force = Boolean(typeof bridge?.shouldHandle === "function" && bridge.shouldHandle({ pid, sid, client_msg_id: clientMsgId }, ctx2));
          } catch (_err) {
            force = false;
          }
        }
        if (force) {
          forcedBridge = bridge;
          break;
        }
      }
      if (forcedBridge) {
        const routeId = String(forcedBridge.routeId || forcedBridge.id || "").trim();
        const activeFlowValue = String(forcedBridge.activeFlowValue || "").trim();
        body.route_id = routeId;
        const enabled = Array.isArray(body.router_enabled_plugins) ? body.router_enabled_plugins.slice() : [];
        if (routeId && !enabled.includes(routeId)) enabled.unshift(routeId);
        body.router_enabled_plugins = enabled;
        if (activeFlowValue) body.ext.agent_flow_active_flow = activeFlowValue;
        body.ext.router_enabled_plugins = enabled.slice();
        body.ext.__route_debug = { forced_route: routeId, active_flow: activeFlowValue };
      }
      const st = getCollabState(ctx2);
      if (st.forceAiOnce) {
        body.ext.no_user_message = true;
        body.ext.skip_user_message = true;
      }
      if (!body.ext.context) {
        body.ext.context = {
          mode: "since_last_assistant",
          summarize: true,
        };
      }

      const remoteState = (ctx2.state.auth_projects || {}).remote || {};
      const projs = remoteState.projects || [];
      const sessByPid = remoteState.sessionsByPid || {};
      const hostProj = ctx2.state.projects ? ctx2.state.projects[pid] : null;
      const hostSess = ctx2.state.sessions ? ctx2.state.sessions[sid] : null;
      const proj = hostProj || projs.find((p) => p.pid === pid) || null;
      const sess = (hostSess && hostSess.pid === pid)
        ? hostSess
        : (sessByPid[pid] || []).find((s) => s.sid === sid) || null;

      const promptId = (sess && sess.collab_prompt_id) || (proj && proj.collab_prompt_id) || "collab_default";
      // One-shot forced system prompt from right-click
      if (st.forceSystemPrompt) {
        body.messages = [{ role: "system", content: String(st.forceSystemPrompt) }].concat(body.messages || []);
        st.forceSystemPrompt = "";
        ctx2.saveState?.();
        return body;
      }

      // Default: use selected prompt id if available and AI is on
      const promptsCache = ((ctx2.state.auth_projects || {}).promptsCache || {});
      const sys = promptsCache[promptId];
      if (sys && String(sys).trim()) {
        body.messages = [{ role: "system", content: String(sys) }].concat(body.messages || []);
      }

      return body;
    });

    host.addSendContextMenuItem(({ pid, sid }, ctx2) => {
      const remoteState = (ctx2.state.auth_projects || {}).remote || {};
      const projs = remoteState.projects || [];
      const sessByPid = remoteState.sessionsByPid || {};
      const hostProj = ctx2.state.projects ? ctx2.state.projects[pid] : null;
      const hostSess = ctx2.state.sessions ? ctx2.state.sessions[sid] : null;
      const proj = hostProj || projs.find((p) => p.pid === pid) || null;
      const sess = (hostSess && hostSess.pid === pid)
        ? hostSess
        : (sessByPid[pid] || []).find((s) => s.sid === sid) || null;

      const effAi = getAiToggle(ctx2, pid, sid);

      if (effAi) return null;

      return {
        label: authT("auth_projects.send_menu.ai_response", "AI response"),
        onClick: async () => {
          const st = getCollabState(ctx2);
          st.forceAiOnce = true;

          const promptId = (sess && sess.collab_prompt_id) || (proj && proj.collab_prompt_id) || "collab_default";
          const cache = (ctx2.state.auth_projects || {}).promptsCache || {};
          st.forceSystemPrompt = cache[promptId] || cache["collab_default"] || "";
          ctx2.saveState?.();

          // Trigger normal send (framework click handler)
          if (typeof host.sendAssistantResponse === "function") {
            await host.sendAssistantResponse();
          } else if (typeof host.sendMessage === "function") {
            await host.sendMessage();
          }
          st.forceAiOnce = false;
          ctx2.saveState?.();
        },
      };
    });

    host.addTranscriptBottombar((ctx2) => buildAiToggleNode(ctx2), "right");

    host.addPanelTab({
      id: meta.plugin_id,
      title: authT("auth_projects.title", "Auth/Projects"),
      render: (container, ctx) => {
        renderPanel(container, ctx, host);
      },
    });
  },
};

export default plugin;
