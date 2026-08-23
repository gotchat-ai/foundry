const meta = {
  plugin_id: "setup_wizard",
  name: "Setup Wizard",
  kind: "plugin",
  description: "Guided onboarding for admins to configure domains, runtimes, and starter models.",
};

const STYLE_ID = "setup-wizard-style";
const DRAFT_KEY = "gotchat.setup_wizard.draft";
const AUTO_OPEN_KEY = "gotchat.setup_wizard.auto_opened";
const DISMISSED_KEY = "gotchat.setup_wizard.dismissed";
const DEFAULT_CPU_QWEN_MODEL = "Qwen3.5-0.8B-Q4_K_M.gguf";
const DEFAULT_CPU_QWEN_MODEL_ID = "Qwen3.5-0.8B-Q4_K_M";
const DEFAULT_CPU_CTX_SIZE = 20000;
const DEFAULT_CPU_BATCH_SIZE = 1024;

const steps = [
  { id: "welcome", title: "Welcome", blurb: "Verify admin access and current environment." },
  { id: "workflow_exchange", title: "Workflow Exchange", blurb: "Control anonymous workflow library sync and public sharing." },
  { id: "network", title: "Network", blurb: "Check local ports and decide how services will be exposed." },
  { id: "hardware", title: "Hardware", blurb: "Inspect available memory, GPUs, and llama runtimes." },
  { id: "profiles", title: "Presets", blurb: "Pick a setup profile based on workload and hardware." },
  { id: "model", title: "Model", blurb: "Validate the model source and backend choice." },
  { id: "apply", title: "Apply + Test", blurb: "Write the config into Model Deck and verify the result." },
];

let renderLast = null;

const state = {
  bootstrap: null,
  bootstrapKey: "",
  bootstrapPromise: null,
  recommendations: [],
  recommendationsLoading: false,
  recommendationsRequested: false,
  modelInfo: null,
  checks: null,
  applyResult: null,
  testResult: null,
  busy: false,
  activeStep: "welcome",
  workflowExchange: {
    loaded: false,
    saving: false,
    loadedKey: "",
    publicSyncEnabled: true,
    publicPublishEnabled: true,
    mode: "hybrid",
    status: "",
  },
  hfSearch: {
    open: false,
    query: "",
    results: [],
    status: "",
    loading: false,
    filenameFilter: "",
    repoSort: "downloads_desc",
    fileSort: "size_desc",
    safeOnly: true,
    singleFileOnly: true,
    collapsedRepos: {},
    destinationMode: "auto",
    quantPreference: "q4_k_m",
    activeFile: "",
    activeSize: null,
    activeDownloaded: 0,
    activeExpected: 0,
    activePhase: "",
  },
  draft: loadDraft(),
};

const sharedSearchSession = {
  external: false,
  ctx: null,
  options: null,
  resolve: null,
  portal: null,
};

let authRefreshBound = false;

function loadDraft() {
  try {
    const raw = window.localStorage.getItem(DRAFT_KEY) || "";
    const parsed = raw ? JSON.parse(raw) : {};
    return {
      route_mode: parsed.route_mode || "local",
      intent: parsed.intent || "general_chat",
      deployment_mode: parsed.deployment_mode || "local",
      prefers_vision: Boolean(parsed.prefers_vision),
      concurrency_target: Number(parsed.concurrency_target || 1),
      profile_id: parsed.profile_id || "",
      profile_title: parsed.profile_title || "",
      type_id: parsed.type_id || "text_llm",
      backend_mode: parsed.backend_mode || "llama_server",
      runtime_id: parsed.runtime_id || "vulkan",
      model_source: parsed.model_source || "",
      model_entry_id: parsed.model_entry_id || DEFAULT_CPU_QWEN_MODEL_ID,
      model_label: parsed.model_label || DEFAULT_CPU_QWEN_MODEL,
      managed_server_id: parsed.managed_server_id || "wizard-main",
      managed_server_name: parsed.managed_server_name || "wizard-main",
      port: Number(parsed.port || 8087),
      ctx_size: Number(parsed.ctx_size || DEFAULT_CPU_CTX_SIZE),
      n_gpu_layers: Number(parsed.n_gpu_layers || 0),
      parallel_slots: Number(parsed.parallel_slots || 1),
      batch_size: Number(parsed.batch_size || DEFAULT_CPU_BATCH_SIZE),
      ubatch_size: Number(parsed.ubatch_size || 512),
      main_gpu: Number(parsed.main_gpu || 0),
      persist: parsed.persist !== false,
      lazy: parsed.lazy !== false,
      set_default: parsed.set_default !== false,
      set_main: parsed.set_main !== false,
      use_managed_server: parsed.use_managed_server !== false,
      flash_attn: parsed.flash_attn !== false,
      offload_kqv: parsed.offload_kqv !== false,
      kv_unified: parsed.kv_unified !== false,
      mmap: parsed.mmap !== false,
      urls: parsed.urls || ["http://127.0.0.1:8000", "http://127.0.0.1:8080", "http://127.0.0.1:8767"],
      ports: parsed.ports || [8000, 8080, 8767, 8087],
    };
  } catch (_err) {
    return {
      route_mode: "local",
      intent: "general_chat",
      deployment_mode: "local",
      prefers_vision: false,
      concurrency_target: 1,
      profile_id: "",
      profile_title: "",
      type_id: "text_llm",
      backend_mode: "llama_server",
      runtime_id: "vulkan",
      model_source: "",
      model_entry_id: DEFAULT_CPU_QWEN_MODEL_ID,
      model_label: DEFAULT_CPU_QWEN_MODEL,
      managed_server_id: "wizard-main",
      managed_server_name: "wizard-main",
      port: 8087,
      ctx_size: DEFAULT_CPU_CTX_SIZE,
      n_gpu_layers: 0,
      parallel_slots: 1,
      batch_size: DEFAULT_CPU_BATCH_SIZE,
      ubatch_size: 512,
      main_gpu: 0,
      persist: true,
      lazy: true,
      set_default: true,
      set_main: true,
      use_managed_server: true,
      flash_attn: true,
      offload_kqv: true,
      kv_unified: true,
      mmap: true,
      urls: ["http://127.0.0.1:8000", "http://127.0.0.1:8080", "http://127.0.0.1:8767"],
      ports: [8000, 8080, 8767, 8087],
    };
  }
}

function saveDraft() {
  try {
    window.localStorage.setItem(DRAFT_KEY, JSON.stringify(state.draft || {}));
  } catch (_err) {}
}

function markWizardDismissed() {
  try {
    window.localStorage.setItem(DISMISSED_KEY, "1");
  } catch (_err) {}
}

function wizardDismissed() {
  try {
    return window.localStorage.getItem(DISMISSED_KEY) === "1";
  } catch (_err) {
    return false;
  }
}

function syncDraftFromStandaloneEnvironment(env = {}) {
  const standalone = env?.standalone_setup || {};
  const chatUrl = String(standalone?.chat_url || "").trim();
  const urls = [
    standalone?.backend_url || "http://127.0.0.1:8000",
    chatUrl || "http://127.0.0.1:8080",
    standalone?.llama_host_url || env?.llama_manager_base || "http://127.0.0.1:8767",
  ].map((item) => String(item || "").trim()).filter(Boolean);
  if (urls.length) state.draft.urls = Array.from(new Set(urls));
  const ports = Array.isArray(env?.ports) ? env.ports.map((item) => Number(item?.port || 0)).filter((port) => port > 0) : [];
  if (ports.length) state.draft.ports = Array.from(new Set(ports));
  if (!env?.in_container && state.draft.route_mode === "docker") {
    state.draft.route_mode = "local";
    state.draft.deployment_mode = "local";
  }
}

function cleanupSharedSearchPortal() {
  if (sharedSearchSession.portal && sharedSearchSession.portal.parentNode) {
    sharedSearchSession.portal.parentNode.removeChild(sharedSearchSession.portal);
  }
  sharedSearchSession.portal = null;
}

function finishSharedSearch(result) {
  const resolve = typeof sharedSearchSession.resolve === "function" ? sharedSearchSession.resolve : null;
  sharedSearchSession.resolve = null;
  if (sharedSearchSession.external) {
    cleanupSharedSearchPortal();
  }
  sharedSearchSession.external = false;
  sharedSearchSession.ctx = null;
  sharedSearchSession.options = null;
  if (resolve) resolve(result ?? null);
}

function getSearchRenderCallback() {
  if (sharedSearchSession.external) return renderSharedSearchPortal;
  return () => renderLast?.();
}

function requestSearchRender() {
  const render = getSearchRenderCallback();
  if (typeof render === "function") render();
}

function getSearchBackendMode() {
  const mode = sharedSearchSession.options?.backendMode;
  return String(mode || state.draft.backend_mode || "llama_server").trim() || "llama_server";
}

function getSearchDefaultQuery() {
  const externalQuery = String(sharedSearchSession.options?.query || "").trim();
  if (externalQuery) return externalQuery;
  return getProfileSearchQuery();
}

function closeModelSearch(result = null) {
  state.hfSearch.open = false;
  requestSearchRender();
  if (sharedSearchSession.external) {
    finishSharedSearch(result);
  }
}

function findSearchRepo(repoId) {
  return (Array.isArray(state.hfSearch.results) ? state.hfSearch.results : []).find((repo) => String(repo?.repo_id || "") === String(repoId || "")) || null;
}

function pickRepoMmprojFile(repo) {
  const files = Array.isArray(repo?.gguf_files) ? repo.gguf_files : [];
  let best = null;
  let bestScore = -Infinity;
  for (const file of files) {
    const low = String(file?.filename || "").toLowerCase();
    if (!/mmproj|projector|vision/.test(low)) continue;
    let score = 0;
    if (/mmproj/.test(low)) score += 80;
    if (/f16|bf16/.test(low)) score += 20;
    if (/q4|q5|q6|q8/.test(low)) score -= 10;
    if (/shard|part|split|00001-of/.test(low)) score -= 40;
    if (score > bestScore) {
      best = file;
      bestScore = score;
    }
  }
  return best;
}

async function runModelDownloadJob(ctx, repoId, filename, backendMode) {
  const repo = findSearchRepo(repoId);
  const file = Array.isArray(repo?.gguf_files) ? repo.gguf_files.find((item) => String(item?.filename || "") === String(filename || "")) : null;
  const expectedBytes = Number(file?.size || state.hfSearch.activeSize || 0);
  const started = await api(ctx, "/v1/setup_wizard/model/download", {
    method: "POST",
    body: {
      repo_id: repoId,
      filename,
      backend_mode: backendMode,
      destination_mode: state.hfSearch.destinationMode || "auto",
      expected_bytes: expectedBytes,
    },
  });
  const jobId = String(started?.job_id || "").trim();
  if (!jobId) throw new Error("Download job was not created");
  let finalRow = null;
  for (let attempt = 0; attempt < 14400; attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
    const row = await api(ctx, `/v1/setup_wizard/model/download_status?job_id=${encodeURIComponent(jobId)}`);
    state.hfSearch.activePhase = String(row?.phase || state.hfSearch.activePhase || "working");
    state.hfSearch.status = String(row?.status || state.hfSearch.status || "Working...");
    state.hfSearch.activeDownloaded = Number(row?.downloaded_bytes || state.hfSearch.activeDownloaded || 0);
    state.hfSearch.activeExpected = Number(row?.expected_bytes || expectedBytes || state.hfSearch.activeExpected || 0);
    requestSearchRender();
    if (row?.done) {
      finalRow = row;
      break;
    }
  }
  if (!finalRow) throw new Error("Model download timed out");
  if (finalRow.ok === false) throw new Error(String(finalRow.error || finalRow.status || "Download failed"));
  return finalRow;
}

function isEmbeddedBackend() {
  return String(state.draft?.backend_mode || "") === "embedded";
}

function ensureStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
.sw-root { display:grid; grid-template-columns: 250px minmax(0,1fr); gap:16px; min-height:70vh; max-height:calc(100dvh - 110px); overflow-y:auto; padding-right:4px; }
.sw-sidebar, .sw-panel, .sw-card { background:var(--panel); border:1px solid var(--border); border-radius:18px; }
.sw-sidebar { padding:14px; display:flex; flex-direction:column; gap:8px; position:sticky; top:0; align-self:start; max-height:calc(100dvh - 130px); overflow:auto; }
.sw-step { border:1px solid transparent; border-radius:14px; padding:12px; cursor:pointer; background:transparent; text-align:left; }
.sw-step.is-active { border-color: color-mix(in srgb, var(--accent) 55%, var(--border) 45%); background: color-mix(in srgb, var(--accent) 10%, transparent 90%); }
.sw-step-title { font-weight:700; color:var(--ink); display:block; }
.sw-step-blurb { display:block; font-size:12px; color:var(--muted); margin-top:4px; line-height:1.4; }
.sw-main { display:flex; flex-direction:column; gap:14px; min-width:0; }
.sw-panel { padding:16px; display:flex; flex-direction:column; gap:14px; }
.sw-head { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; flex-wrap:wrap; }
.sw-title { font-size:22px; font-weight:800; }
.sw-sub { color:var(--muted); max-width:760px; line-height:1.5; }
.sw-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; }
.sw-card { padding:14px; display:flex; flex-direction:column; gap:10px; }
.sw-k { font-size:12px; color:var(--muted); text-transform:uppercase; letter-spacing:0.08em; }
.sw-v { font-size:15px; font-weight:700; word-break:break-word; }
.sw-actions { display:flex; gap:8px; flex-wrap:wrap; }
.sw-btn { border:1px solid var(--border); border-radius:12px; padding:10px 14px; background:transparent; color:var(--ink); cursor:pointer; }
.sw-btn.primary { background:var(--accent); color:#fff; border-color:transparent; }
.sw-btn.ghost { background:color-mix(in srgb, var(--panel) 82%, white 18%); }
.sw-btn:disabled { opacity:0.55; cursor:default; }
.sw-btn.is-loading { display:inline-flex; align-items:center; gap:8px; }
.sw-btn-spinner { width:14px; height:14px; border:2px solid currentColor; border-right-color:transparent; border-radius:50%; display:inline-block; animation: swSpin 0.8s linear infinite; flex:0 0 auto; }
.sw-btn.compact { padding:7px 11px; min-height:34px; font-size:12px; border-radius:10px; }
.sw-field { display:flex; flex-direction:column; gap:6px; }
.sw-field > span { font-size:12px; color:var(--muted); }
.sw-field > input, .sw-field > select, .sw-field > textarea { width:100%; min-height:42px; border-radius:12px; border:1px solid var(--border); background:color-mix(in srgb, var(--panel) 88%, white 12%); color:var(--ink); padding:10px 12px; }
.sw-field > textarea { min-height:84px; resize:vertical; }
.sw-checks { display:grid; gap:10px; }
.sw-check { border:1px solid var(--border); border-radius:14px; padding:12px; display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }
.sw-ok { color:#2ca65a; font-weight:700; }
.sw-bad { color:#d55a5a; font-weight:700; }
.sw-note { color:var(--muted); font-size:12px; line-height:1.5; white-space:pre-line; }
.sw-pillrow { display:flex; gap:8px; flex-wrap:wrap; }
.sw-pill { border:1px solid var(--border); border-radius:999px; padding:8px 12px; cursor:pointer; background:transparent; }
.sw-pill.is-active { border-color:var(--accent); color:var(--accent); }
.sw-summary { border:1px dashed var(--border); border-radius:14px; padding:12px; background:color-mix(in srgb, var(--panel) 80%, white 20%); }
.sw-service-list { display:grid; gap:6px; margin-top:10px; }
.sw-service-row { display:flex; justify-content:space-between; gap:10px; border-top:1px solid var(--border); padding-top:6px; color:var(--muted); font-size:12px; }
.sw-service-row strong { color:var(--ink); }
.sw-launcher { display:inline-flex; align-items:center; gap:8px; padding:8px 12px; border:1px solid var(--border); border-radius:999px; background:var(--panel); color:var(--ink); cursor:pointer; }
.sw-launcher-dot { width:9px; height:9px; border-radius:50%; background:var(--accent); box-shadow:0 0 0 0 color-mix(in srgb, var(--accent) 50%, transparent 50%); animation: swPulse 1.5s infinite; }
.sw-inline-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:10px; }
.sw-modal { position:fixed; inset:0; background:rgba(24, 19, 16, 0.45); display:flex; align-items:center; justify-content:center; padding:20px; z-index:2147483647; }
.sw-modal-card { width:min(980px, 96vw); max-height:min(86vh, 960px); overflow:auto; background:var(--panel); border:1px solid var(--border); border-radius:18px; padding:16px; display:flex; flex-direction:column; gap:14px; box-shadow:var(--shadow); }
.sw-modal-head { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }
.sw-modal-title { font-size:20px; font-weight:800; color:var(--ink); }
.sw-modal-close { border:1px solid var(--border); background:transparent; color:var(--ink); border-radius:12px; min-width:40px; height:40px; cursor:pointer; }
.sw-repo-list { display:grid; gap:12px; }
.sw-repo-card { border:1px solid var(--border); border-radius:16px; background:rgba(var(--panel-rgb), 0.72); padding:12px; display:flex; flex-direction:column; gap:10px; }
.sw-repo-head { display:flex; justify-content:space-between; gap:10px; align-items:flex-start; flex-wrap:wrap; }
.sw-repo-id { font-weight:700; color:var(--ink); word-break:break-word; }
.sw-repo-meta { font-size:12px; color:var(--muted); }
.sw-file-list { display:grid; gap:8px; }
.sw-file-row { border:1px solid var(--border); border-radius:12px; padding:10px; background:color-mix(in srgb, var(--panel) 82%, white 18%); display:flex; justify-content:space-between; gap:10px; align-items:center; flex-wrap:wrap; }
.sw-file-name { font-size:13px; font-weight:600; color:var(--ink); word-break:break-word; }
.sw-toggle-row { display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
.sw-checklabel { display:inline-flex; align-items:center; gap:8px; color:var(--ink); font-size:12px; }
.sw-repo-summary { display:flex; align-items:center; justify-content:space-between; gap:10px; cursor:pointer; list-style:none; }
.sw-repo-summary::-webkit-details-marker { display:none; }
.sw-repo-count { font-size:12px; color:var(--muted); }
.sw-status-card { border:1px solid var(--border); border-radius:14px; padding:12px; background:color-mix(in srgb, var(--panel) 78%, white 22%); display:flex; flex-direction:column; gap:6px; }
.sw-status-title { font-size:12px; text-transform:uppercase; letter-spacing:0.08em; color:var(--muted); }
.sw-status-main { font-size:15px; font-weight:700; color:var(--ink); }
.sw-status-meta { font-size:12px; color:var(--muted); }
.sw-badge-row { display:flex; gap:6px; flex-wrap:wrap; margin-top:6px; }
.sw-badge { display:inline-flex; align-items:center; border:1px solid var(--border); border-radius:999px; padding:2px 8px; font-size:10px; letter-spacing:0.06em; text-transform:uppercase; color:var(--ink); background:rgba(var(--panel-rgb), 0.72); }
.sw-badge.ok { color:#2ca65a; border-color:rgba(44, 166, 90, 0.28); background:rgba(44, 166, 90, 0.10); }
.sw-badge.warn { color:#b7791f; border-color:rgba(183, 121, 31, 0.28); background:rgba(183, 121, 31, 0.10); }
.sw-badge.danger { color:#d55a5a; border-color:rgba(213, 90, 90, 0.28); background:rgba(213, 90, 90, 0.10); }
.sw-badge.best { color:var(--accent); border-color:rgba(var(--accent-rgb), 0.32); background:rgba(var(--accent-rgb), 0.12); }
.sw-legend { border:1px dashed var(--border); border-radius:14px; padding:10px 12px; background:color-mix(in srgb, var(--panel) 82%, white 18%); display:flex; flex-direction:column; gap:8px; }
.sw-legend-title { font-size:12px; text-transform:uppercase; letter-spacing:0.08em; color:var(--muted); }
.sw-legend-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:8px 12px; }
.sw-legend-item { display:flex; align-items:flex-start; gap:8px; color:var(--muted); font-size:12px; line-height:1.4; }
.sw-link { color:var(--accent); text-decoration:none; }
.sw-link:hover { text-decoration:underline; }
@keyframes swPulse { 0% { box-shadow:0 0 0 0 color-mix(in srgb, var(--accent) 50%, transparent 50%); } 70% { box-shadow:0 0 0 8px transparent; } 100% { box-shadow:0 0 0 0 transparent; } }
@keyframes swSpin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
@media (max-width: 900px) { .sw-root { grid-template-columns:1fr; } .sw-sidebar { display:none; } }
  `;
  document.head.appendChild(style);
}

function field(label, input) {
  const wrap = document.createElement("label");
  wrap.className = "sw-field";
  const title = document.createElement("span");
  title.textContent = label;
  wrap.appendChild(title);
  wrap.appendChild(input);
  return wrap;
}

function button(label, onClick, kind = "", options = {}) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = `sw-btn ${kind}`.trim();
  const idleLabel = String(label || "");
  const loadingLabel = String(options.loadingLabel || idleLabel || "Working...");
  btn.textContent = idleLabel;
  btn.addEventListener("click", async () => {
    if (state.busy) return;
    try {
      state.busy = true;
      btn.disabled = true;
      btn.classList.add("is-loading");
      btn.innerHTML = `<span class="sw-btn-spinner" aria-hidden="true"></span><span>${loadingLabel}</span>`;
      await onClick();
    } finally {
      state.busy = false;
      btn.disabled = false;
      btn.classList.remove("is-loading");
      btn.textContent = idleLabel;
    }
  });
  return btn;
}

function currentWorkflowExchangeKey() {
  return JSON.stringify({
    publicSyncEnabled: !!state.workflowExchange.publicSyncEnabled,
    publicPublishEnabled: !!state.workflowExchange.publicPublishEnabled,
    mode: String(state.workflowExchange.mode || "hybrid").trim().toLowerCase() || "hybrid",
  });
}

async function persistWorkflowExchangeSettings(ctx) {
  if (!state.workflowExchange.loaded) return;
  const nextKey = currentWorkflowExchangeKey();
  if (nextKey === state.workflowExchange.loadedKey) return;
  const publicEnabled = !!state.workflowExchange.publicSyncEnabled;
  let mode = String(state.workflowExchange.mode || "hybrid").trim().toLowerCase() || "hybrid";
  if (publicEnabled && (mode === "off" || mode === "private")) mode = "hybrid";
  if (!publicEnabled && mode === "public") mode = "private";
  state.workflowExchange.saving = true;
  state.workflowExchange.status = "Saving workflow exchange preference...";
  try {
    await api(ctx, "/v1/workflow_exchange/settings", {
      method: "POST",
      body: {
        settings: {
          workflow_exchange_enabled: true,
          workflow_exchange_mode: mode,
          workflow_exchange_public_publish_enabled: publicEnabled,
          workflow_exchange_public_scheduled_sync_enabled: publicEnabled,
        },
      },
    });
    state.workflowExchange.mode = mode;
    state.workflowExchange.publicPublishEnabled = publicEnabled;
    state.workflowExchange.loadedKey = JSON.stringify({
      publicSyncEnabled: publicEnabled,
      publicPublishEnabled: publicEnabled,
      mode,
    });
    state.workflowExchange.status = publicEnabled
      ? "Anonymous public workflow sync is enabled."
      : "Anonymous public workflow sync is disabled. Local/private workflow tools remain available.";
  } finally {
    state.workflowExchange.saving = false;
  }
}

async function persistActiveStep(ctx) {
  if (state.activeStep === "workflow_exchange") {
    await persistWorkflowExchangeSettings(ctx);
  }
}

function formatBytes(value) {
  const num = Number(value || 0);
  if (!num) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let idx = 0;
  let out = num;
  while (out >= 1024 && idx < units.length - 1) {
    out /= 1024;
    idx += 1;
  }
  return `${out.toFixed(out >= 10 || idx === 0 ? 0 : 1)} ${units[idx]}`;
}

function getActiveProfile() {
  return (state.recommendations || []).find((item) => item.id === state.draft.profile_id) || null;
}

function defaultCpuQwenProfile() {
  return {
    id: "cpu_qwen35_08b_local",
    title: "CPU-friendly Qwen starter",
    summary: "Uses Qwen3.5-0.8B Q4_K_M with a large context and llama.cpp settings that run well on regular PCs.",
    backend_mode: "llama_server",
    runtime_id: "vulkan",
    ctx_size: DEFAULT_CPU_CTX_SIZE,
    n_gpu_layers: 0,
    parallel_slots: 1,
    batch_size: DEFAULT_CPU_BATCH_SIZE,
    ubatch_size: 512,
    mmap: true,
    kv_unified: true,
    flash_attn: true,
    offload_kqv: true,
    model_hint: DEFAULT_CPU_QWEN_MODEL,
    notes: [
      "Best default for no-GPU, VM, or regular PC setup.",
      "Keeps Vulkan as the llama.cpp runtime target when available, while still running CPU-only if no GPU is present.",
    ],
  };
}

function syncDraftFromProfile(profile) {
  if (!profile) return;
  state.draft.profile_id = profile.id;
  state.draft.profile_title = profile.title || "";
  state.draft.backend_mode = profile.backend_mode || state.draft.backend_mode;
  state.draft.runtime_id = profile.runtime_id || state.draft.runtime_id;
  state.draft.ctx_size = Number(profile.ctx_size || state.draft.ctx_size || 8192);
  state.draft.n_gpu_layers = Number(profile.n_gpu_layers || 0);
  state.draft.parallel_slots = Number(profile.parallel_slots || 1);
  state.draft.batch_size = Number(profile.batch_size || 512);
  state.draft.ubatch_size = Number(profile.ubatch_size || state.draft.ubatch_size || 512);
  state.draft.flash_attn = profile.flash_attn !== false;
  state.draft.offload_kqv = profile.offload_kqv !== false;
  state.draft.kv_unified = profile.kv_unified !== false;
  state.draft.mmap = profile.mmap !== false;
  if (!state.draft.model_label && profile.model_hint) state.draft.model_label = profile.model_hint;
  saveDraft();
}

async function api(ctx, path, options = {}) {
  const appState = (ctx?.getState?.() || ctx?.state || {});
  const auth = appState?.auth || {};
  const ui = appState?.ui || {};
  const baseHeaders = {
    "X-Gui-Enabled-Plugins": "collab_chat,setup_wizard,model_deck,llama_server_manager",
  };
  if (auth?.token) baseHeaders.Authorization = `Bearer ${auth.token}`;
  if (auth?.alias) baseHeaders["X-User-Alias"] = auth.alias;
  if (ui?.activePid) baseHeaders["X-Project-Id"] = ui.activePid;
  if (ui?.activeSid) baseHeaders["X-Session-Id"] = ui.activeSid;
  return ctx.apiJson(path, {
    ...options,
    headers: { ...baseHeaders, ...(options.headers || {}) },
  });
}

function currentBootstrapKey(ctx) {
  const appState = ctx?.getState?.() || {};
  const auth = appState?.auth || {};
  const remote = appState?.remote || {};
  return JSON.stringify({
    server_url: String(remote.serverUrl || ""),
    username: String(auth.username || ""),
    role: String(auth.role || ""),
    has_token: Boolean(auth.token),
  });
}

async function loadBootstrap(ctx) {
  state.bootstrapKey = currentBootstrapKey(ctx);
  state.bootstrap = await api(ctx, "/v1/setup_wizard/bootstrap");
  const wizardState = state.bootstrap?.state || {};
  const env = state.bootstrap?.environment || {};
  const exchangeSettings = state.bootstrap?.workflow_exchange?.settings || {};
  if (wizardState.route_mode) {
    state.draft.route_mode = wizardState.route_mode;
    state.draft.deployment_mode = wizardState.route_mode;
  }
  syncDraftFromStandaloneEnvironment(env);
  state.workflowExchange.publicSyncEnabled = exchangeSettings.workflow_exchange_public_scheduled_sync_enabled !== false;
  state.workflowExchange.publicPublishEnabled = exchangeSettings.workflow_exchange_public_publish_enabled !== false;
  state.workflowExchange.mode = String(exchangeSettings.workflow_exchange_mode || "hybrid").trim().toLowerCase() || "hybrid";
  state.workflowExchange.loaded = true;
  state.workflowExchange.status = "";
  state.workflowExchange.loadedKey = JSON.stringify({
    publicSyncEnabled: !!state.workflowExchange.publicSyncEnabled,
    publicPublishEnabled: !!state.workflowExchange.publicPublishEnabled,
    mode: state.workflowExchange.mode,
  });
  const savedModel = wizardState.selected_model || {};
  if (savedModel.source && !state.draft.model_source) state.draft.model_source = savedModel.source;
  if (savedModel.managed_server_id && !state.draft.managed_server_id) state.draft.managed_server_id = savedModel.managed_server_id;
  saveDraft();
}

function ensureBootstrapCurrent(ctx) {
  const key = currentBootstrapKey(ctx);
  if (state.bootstrap && state.bootstrapKey === key) {
    return state.bootstrapPromise || Promise.resolve(state.bootstrap);
  }
  if (state.bootstrapPromise) return state.bootstrapPromise;
  state.bootstrap = null;
  state.bootstrapKey = key;
  state.bootstrapPromise = loadBootstrap(ctx)
    .then((data) => {
      try {
        window.dispatchEvent(new CustomEvent("chatjs:rerender-top-right"));
      } catch (_err) {}
      if (typeof renderLast === "function") renderLast();
      return data;
    })
    .finally(() => {
      state.bootstrapPromise = null;
    });
  return state.bootstrapPromise;
}

function currentUserLooksAdmin(ctx) {
  const appState = ctx?.getState?.() || {};
  const role = String(appState?.auth?.role || "").trim().toLowerCase();
  if (role) return role === "admin" || role === "owner" || role === "superadmin";
  if (!state.bootstrap) return false;
  return state.bootstrap?.summary?.is_admin === true;
}

function bindAuthRefresh(host, ctxFactory) {
  if (authRefreshBound) return;
  authRefreshBound = true;
  window.addEventListener("chatjs:auth-changed", () => {
    state.bootstrap = null;
    state.bootstrapKey = "";
    state.bootstrapPromise = null;
    const ctx = typeof ctxFactory === "function" ? ctxFactory() : null;
    if (!ctx) return;
    ensureBootstrapCurrent(ctx).catch(() => {}).finally(() => {
      try {
        window.dispatchEvent(new CustomEvent("chatjs:rerender-top-right"));
      } catch (_err) {}
      try {
        host.openPluginPanelWhenReady(meta.plugin_id, { reopen: false });
      } catch (_err) {}
      if (typeof renderLast === "function") renderLast();
    });
  });
}

async function refreshRecommendations(ctx) {
  if (state.recommendationsLoading) return;
  state.recommendationsLoading = true;
  try {
    const res = await api(ctx, "/v1/setup_wizard/recommendations", {
      method: "POST",
      body: {
        intent: state.draft.intent,
        deployment_mode: state.draft.deployment_mode,
        prefers_vision: Boolean(state.draft.prefers_vision),
        concurrency_target: Number(state.draft.concurrency_target || 1),
        privacy_mode: "private",
      },
    });
    const profiles = Array.isArray(res?.profiles) ? res.profiles : [];
    state.recommendations = profiles.length ? profiles : [defaultCpuQwenProfile()];
    if (!getActiveProfile() && state.recommendations[0]) syncDraftFromProfile(state.recommendations[0]);
  } catch (err) {
    console.warn("[setup_wizard] recommendation request failed; using local CPU fallback", err);
    state.recommendations = [defaultCpuQwenProfile()];
    if (!getActiveProfile()) syncDraftFromProfile(state.recommendations[0]);
  } finally {
    state.recommendationsLoading = false;
  }
}

async function resolveModel(ctx) {
  state.modelInfo = await api(ctx, "/v1/setup_wizard/model/resolve", {
    method: "POST",
    body: {
      source: state.draft.model_source,
      type_id: state.draft.type_id,
      backend_mode: state.draft.backend_mode,
    },
  });
  if (state.modelInfo?.filename && !state.draft.model_entry_id) {
    state.draft.model_entry_id = String(state.modelInfo.filename).replace(/\.gguf$/i, "").replace(/[^a-z0-9._-]+/gi, "_");
    saveDraft();
  }
}

async function runChecks(ctx) {
  state.checks = await api(ctx, "/v1/setup_wizard/url_checks", {
    method: "POST",
    body: { ports: state.draft.ports, urls: state.draft.urls },
  });
}

async function applyWizard(ctx) {
  const body = { ...state.draft };
  const profile = getActiveProfile();
  if (profile) {
    body.profile_id = profile.id;
    body.profile_title = profile.title;
  }
  state.applyResult = await api(ctx, "/v1/setup_wizard/apply", { method: "POST", body });
}

async function runTest(ctx) {
  state.testResult = await api(ctx, "/v1/setup_wizard/test_run", {
    method: "POST",
    body: { type_id: state.draft.type_id, expect_main: Boolean(state.draft.set_main) },
  });
  if (state.testResult?.state) {
    state.bootstrap = state.bootstrap || {};
    state.bootstrap.state = state.testResult.state;
  }
}

function closeWizardPanel(ctx) {
  markWizardDismissed();
  document.querySelectorAll(".sw-launcher").forEach((node) => node.remove());
  if (typeof ctx?.closePluginFullView === "function") {
    ctx.closePluginFullView();
    return;
  }
  if (typeof ctx?.closeTools === "function") {
    ctx.closeTools();
    return;
  }
  const closeButton = document.getElementById("modal-close");
  if (closeButton && typeof closeButton.click === "function") {
    closeButton.click();
    return;
  }
  alert("Setup wizard complete. You can close this panel.");
}

function buildSidebar(rerender) {
  const side = document.createElement("div");
  side.className = "sw-sidebar";
  for (const step of steps) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `sw-step ${state.activeStep === step.id ? "is-active" : ""}`.trim();
    btn.innerHTML = `<span class="sw-step-title">${step.title}</span><span class="sw-step-blurb">${step.blurb}</span>`;
    btn.addEventListener("click", () => {
      state.activeStep = step.id;
      rerender();
    });
    side.appendChild(btn);
  }
  return side;
}

function buildWelcomeStep(ctx) {
  const wrap = document.createElement("div");
  wrap.className = "sw-panel";
  const summary = state.bootstrap?.summary || {};
  const env = state.bootstrap?.environment || {};
  wrap.innerHTML = `<div class="sw-head"><div><div class="sw-title">Welcome</div><div class="sw-sub">This setup guides a new admin from environment validation to a working starter model. It reads the current machine, suggests defaults, and writes the result into Model Deck and the managed llama-server configuration.</div></div></div>`;
  const cards = document.createElement("div");
  cards.className = "sw-grid";
  const routeMode = state.draft.route_mode || env.route_mode || (env.in_container ? "docker" : "local");
  const items = [["Signed in", summary?.username || "unknown"], ["Role", summary?.role || "unknown"], ["Route mode", routeMode === "docker" ? "Docker / container" : "Local host"], ["Host service", env?.llama_manager_base || "n/a"]];
  for (const [k, v] of items) {
    const card = document.createElement("div");
    card.className = "sw-card";
    card.innerHTML = `<div class="sw-k">${k}</div><div class="sw-v">${v}</div>`;
    cards.appendChild(card);
  }
  wrap.appendChild(cards);
  const actions = document.createElement("div");
  actions.className = "sw-actions";
  actions.appendChild(button("Refresh environment", async () => { await loadBootstrap(ctx); }, "primary"));
  wrap.appendChild(actions);
  return wrap;
}

function buildWorkflowExchangeStep(ctx) {
  const wrap = document.createElement("div");
  wrap.className = "sw-panel";
  wrap.innerHTML = `<div class="sw-title">Agent Workflow Exchange</div><div class="sw-sub">Agent Workflow Exchange lets this app discover, import, and anonymously share workflow library entries with other GotChat users through the public exchange. Shared workflows are sanitized for public use, and the exchange can help users find reusable automations and agent flows without exposing account identity.</div>`;
  const summary = document.createElement("div");
  summary.className = "sw-summary";
  summary.innerHTML = `<strong>What this does</strong><div class="sw-note">When enabled, GotChat can participate in anonymous public workflow syncing so new workflow library entries can be discovered and shared. When disabled, the public sync path is turned off, but local workflow tools and private exchange behavior remain available.</div>`;
  wrap.appendChild(summary);
  const toggleRow = document.createElement("label");
  toggleRow.className = "sw-check";
  const toggleInfo = document.createElement("div");
  toggleInfo.innerHTML = `<strong>Enable anonymous public workflow syncing</strong><div class="sw-note">Recommended for users who want access to the shared workflow library and want to contribute sanitized workflows back to the public exchange.</div>`;
  const toggleCell = document.createElement("div");
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = !!state.workflowExchange.publicSyncEnabled;
  checkbox.disabled = !!state.workflowExchange.saving;
  checkbox.addEventListener("change", () => {
    state.workflowExchange.publicSyncEnabled = !!checkbox.checked;
    state.workflowExchange.publicPublishEnabled = !!checkbox.checked;
    state.workflowExchange.status = checkbox.checked
      ? "Anonymous public workflow sync will be enabled when you continue."
      : "Anonymous public workflow sync will be disabled when you continue.";
    renderLast?.();
  });
  toggleCell.appendChild(checkbox);
  toggleRow.appendChild(toggleInfo);
  toggleRow.appendChild(toggleCell);
  wrap.appendChild(toggleRow);
  const note = document.createElement("div");
  note.className = "sw-note";
  note.textContent = state.workflowExchange.saving
    ? "Saving workflow exchange preference..."
    : (state.workflowExchange.status || "Default: on. You can turn this off if you do not want anonymous public workflow syncing on this installation.");
  wrap.appendChild(note);
  const actions = document.createElement("div");
  actions.className = "sw-actions";
  actions.appendChild(button("Save workflow exchange setting", async () => {
    await persistWorkflowExchangeSettings(ctx);
    renderLast?.();
  }, "primary", { loadingLabel: "Saving workflow exchange..." }));
  wrap.appendChild(actions);
  return wrap;
}

function buildNetworkStep(ctx) {
  const wrap = document.createElement("div");
  wrap.className = "sw-panel";
  const env = state.bootstrap?.environment || {};
  const standalone = env?.standalone_setup || {};
  wrap.innerHTML = `<div class="sw-title">Network and routing</div><div class="sw-sub">Choose how the browser reaches the local services, then validate the ports that this machine is using. Local mode uses 127.0.0.1 URLs. Docker mode is only for container routing. The standalone setup wizard can choose an open chat_js port automatically, and this page reads that saved service map when available.</div>`;
  const modeRow = document.createElement("div");
  modeRow.className = "sw-pillrow";
  [["docker", "Docker / container route mode"], ["local", "Local host route mode"]].forEach(([id, label]) => {
    const pill = document.createElement("button");
    pill.type = "button";
    pill.className = `sw-pill ${state.draft.route_mode === id ? "is-active" : ""}`.trim();
    pill.textContent = label;
    pill.addEventListener("click", () => {
      state.draft.route_mode = id;
      state.draft.deployment_mode = id;
      saveDraft();
      renderLast?.();
    });
    modeRow.appendChild(pill);
  });
  wrap.appendChild(modeRow);
  const serviceMap = document.createElement("div");
  serviceMap.className = "sw-summary";
  const portRows = Array.isArray(env.ports) ? env.ports : [];
  const rows = portRows.length
    ? portRows.map((item) => `<div class="sw-service-row"><strong>${item.label || "Service"}</strong><span>Port ${item.port} · ${item.status === "in_use" ? "in use/running" : "available"}</span></div>`).join("")
    : "<div class=\"sw-note\">No service port plan was returned by the backend yet.</div>";
  serviceMap.innerHTML = `<strong>Local service map</strong><div class="sw-note">Chat API backend: http://127.0.0.1:8000\nChat frontend: ${standalone.chat_url || "http://127.0.0.1:8080"}\nLlama host manager: ${standalone.llama_host_url || env.llama_manager_base || "http://127.0.0.1:8767"}</div><div class="sw-service-list">${rows}</div>`;
  wrap.appendChild(serviceMap);
  const urls = document.createElement("textarea");
  urls.value = (state.draft.urls || []).join("\n");
  urls.addEventListener("change", () => {
    state.draft.urls = urls.value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    saveDraft();
  });
  const ports = document.createElement("input");
  ports.type = "text";
  ports.value = (state.draft.ports || []).join(", ");
  ports.addEventListener("change", () => {
    state.draft.ports = ports.value.split(",").map((v) => Number(String(v).trim())).filter((v) => Number.isFinite(v) && v > 0);
    saveDraft();
  });
  const searchActions = document.createElement("div");
  searchActions.className = "sw-actions";
  wrap.appendChild(searchActions);
  const grid = document.createElement("div");
  grid.className = "sw-inline-grid";
  grid.appendChild(field("Service URLs to validate", urls));
  grid.appendChild(field("Ports to probe", ports));
  wrap.appendChild(grid);
  const actions = document.createElement("div");
  actions.className = "sw-actions";
  actions.appendChild(button("Run checks", async () => { await runChecks(ctx); renderLast?.(); }, "primary"));
  wrap.appendChild(actions);
  if (state.checks) {
    const list = document.createElement("div");
    list.className = "sw-checks";
    for (const item of (state.checks.ports || [])) {
      const row = document.createElement("div");
      row.className = "sw-check";
      const portState = item.available ? "Available" : (item.status === "in_use" ? "In use" : "Needs fix");
      row.innerHTML = `<div><strong>${item.port}</strong><div class="sw-note">${item.label || item.reason || "Port check"}</div></div><div class="${item.available ? "sw-ok" : "sw-bad"}">${portState}</div>`;
      list.appendChild(row);
    }
    for (const item of (state.checks.urls || [])) {
      const row = document.createElement("div");
      row.className = "sw-check";
      row.innerHTML = `<div><strong>${item.url}</strong><div class="sw-note">${item.reason || "URL check"}</div></div><div class="${item.valid ? "sw-ok" : "sw-bad"}">${item.valid ? "Valid" : "Needs fix"}</div>`;
      list.appendChild(row);
    }
    wrap.appendChild(list);
  }
  return wrap;
}

function buildHardwareStep(ctx) {
  const wrap = document.createElement("div");
  wrap.className = "sw-panel";
  wrap.innerHTML = `<div class="sw-title">Hardware and runtimes</div><div class="sw-sub">The wizard reads the current machine so it can recommend a startup profile that matches available memory, GPUs, and llama.cpp runtime installs.</div>`;
  const hw = state.bootstrap?.hardware || {};
  const cards = document.createElement("div");
  cards.className = "sw-grid";
  const items = [["CPU threads", String(hw?.cpu?.logical || 0)], ["RAM total", formatBytes(hw?.memory?.total_bytes || 0)], ["RAM available", formatBytes(hw?.memory?.available_bytes || 0)], ["Detected GPUs", String((hw?.gpus || []).length)]];
  for (const [k, v] of items) {
    const card = document.createElement("div");
    card.className = "sw-card";
    card.innerHTML = `<div class="sw-k">${k}</div><div class="sw-v">${v}</div>`;
    cards.appendChild(card);
  }
  wrap.appendChild(cards);
  const detail = document.createElement("div");
  detail.className = "sw-grid";
  const gpuCard = document.createElement("div");
  gpuCard.className = "sw-card";
  gpuCard.innerHTML = `<div class="sw-k">GPU devices</div><div class="sw-note">${(hw?.gpus || []).map((item) => item.name).join("\n") || "No GPUs reported by the llama host service yet."}</div>`;
  const runtimeCard = document.createElement("div");
  runtimeCard.className = "sw-card";
  runtimeCard.innerHTML = `<div class="sw-k">Installed llama runtimes</div><div class="sw-note">${(hw?.llama_installs || []).map((item) => `${item.runtime_id} ${item.tag || ""}`).join("\n") || "No llama.cpp runtime installs found yet."}</div>`;
  detail.appendChild(gpuCard);
  detail.appendChild(runtimeCard);
  wrap.appendChild(detail);
  const actions = document.createElement("div");
  actions.className = "sw-actions";
  actions.appendChild(button("Refresh hardware", async () => { await loadBootstrap(ctx); renderLast?.(); }, "primary"));
  wrap.appendChild(actions);
  return wrap;
}

function buildProfilesStep(ctx) {
  const wrap = document.createElement("div");
  wrap.className = "sw-panel";
  if (!state.recommendationsRequested && !state.recommendationsLoading && !(state.recommendations || []).length) {
    state.recommendationsRequested = true;
    setTimeout(async () => {
      await refreshRecommendations(ctx);
      renderLast?.();
    }, 0);
  }
  wrap.innerHTML = `<div class="sw-title">Generated Recommendations</div><div class="sw-sub">Pick what the app needs to do first. The wizard turns that into a concrete starter profile and leaves room for later optimization.</div>`;
  const controls = document.createElement("div");
  controls.className = "sw-inline-grid";
  const intent = document.createElement("select");
  [["general_chat", "General chat"], ["coding", "Coding / repo analysis"], ["agents", "Agents / workflows"], ["vision", "Vision / document reading"]].forEach(([value, label]) => intent.appendChild(new Option(label, value)));
  intent.value = state.draft.intent;
  intent.addEventListener("change", () => {
    state.draft.intent = intent.value;
    state.recommendations = [];
    state.recommendationsRequested = false;
    saveDraft();
    renderLast?.();
  });
  const concurrency = document.createElement("input");
  concurrency.type = "number";
  concurrency.min = "1";
  concurrency.value = String(state.draft.concurrency_target || 1);
  concurrency.addEventListener("change", () => {
    state.draft.concurrency_target = Number(concurrency.value || 1);
    state.recommendations = [];
    state.recommendationsRequested = false;
    saveDraft();
    renderLast?.();
  });
  const vision = document.createElement("select");
  vision.appendChild(new Option("No", "false"));
  vision.appendChild(new Option("Yes", "true"));
  vision.value = String(Boolean(state.draft.prefers_vision));
  vision.addEventListener("change", () => {
    state.draft.prefers_vision = vision.value === "true";
    state.recommendations = [];
    state.recommendationsRequested = false;
    saveDraft();
    renderLast?.();
  });
  controls.appendChild(field("Primary goal", intent));
  controls.appendChild(field("Expected parallel chats", concurrency));
  controls.appendChild(field("Need vision later", vision));
  wrap.appendChild(controls);
  const actions = document.createElement("div");
  actions.className = "sw-actions";
  actions.appendChild(button(state.recommendationsLoading ? "Generating recommendations..." : "Generate recommendations", async () => { await refreshRecommendations(ctx); renderLast?.(); }, "primary"));
  wrap.appendChild(actions);
  const list = document.createElement("div");
  list.className = "sw-grid";
  for (const profile of state.recommendations || []) {
    const card = document.createElement("div");
    card.className = "sw-card";
    const active = state.draft.profile_id === profile.id;
    if (active) card.style.borderColor = "var(--accent)";
    card.innerHTML = `<div class="sw-k">${profile.runtime_id || "runtime"}</div><div class="sw-v">${profile.title}</div><div class="sw-note">${profile.summary}</div>`;
    const metaRow = document.createElement("div");
    metaRow.className = "sw-note";
    metaRow.textContent = `Backend: ${profile.backend_mode} | Context: ${profile.ctx_size} | Parallel: ${profile.parallel_slots} | Model hint: ${profile.model_hint}`;
    card.appendChild(metaRow);
    const notes = document.createElement("div");
    notes.className = "sw-note";
    notes.textContent = Array.isArray(profile.notes) ? profile.notes.join(" ") : "";
    card.appendChild(notes);
    const cardActions = document.createElement("div");
    cardActions.className = "sw-actions";
    cardActions.appendChild(button(active ? "Selected" : "Use this preset", async () => { syncDraftFromProfile(profile); renderLast?.(); }, active ? "ghost" : "primary"));
    card.appendChild(cardActions);
    list.appendChild(card);
  }
  if (!list.children.length) {
    const note = document.createElement("div");
    note.className = "sw-note";
    note.textContent = state.recommendationsLoading ? "Generating recommendations..." : "No recommendations yet. Generate them after choosing the main goal for this machine.";
    wrap.appendChild(note);
  } else {
    wrap.appendChild(list);
  }
  return wrap;
}

function getProfileSearchQuery() {
  const active = getActiveProfile();
  const hint = String(active?.model_hint || state.draft.model_label || "").trim();
  if (hint) return normalizeModelSearchQuery(hint);
  if (state.draft.intent === "coding" || state.draft.intent === "agents") return "Qwen Coder";
  if (state.draft.intent === "vision") return "Qwen VL";
  return "Qwen";
}

function normalizeModelSearchQuery(value) {
  let text = String(value || "").trim();
  if (!text) return "";
  text = text.replace(/\s+or\s+.+$/i, "");
  text = text.replace(/[.\s]+$/g, "");
  text = text.replace(/\.gguf$/i, "");
  text = text.replace(/[.\s]+$/g, "");
  text = text.replace(/\bGGUF\b/ig, "");
  text = text.replace(/[-_]+Q[0-9]+(?:_[A-Z0-9]+)*$/i, "");
  text = text.replace(/[-_]+(?:K|M|S|L)$/i, "");
  text = text.replace(/([A-Za-z])[-_]+([0-9])/g, "$1 $2");
  text = text.replace(/([0-9])[-_]+([0-9])/g, "$1 $2");
  text = text.replace(/[_-]+/g, " ");
  text = text.replace(/\s+/g, " ").trim();
  if (/^qwen3\.5\s+0\.8b$/i.test(text)) return "Qwen3.5 0.8B";
  return text;
}

async function openModelSearch(ctx, options = null) {
  ensureStyles();
  sharedSearchSession.external = Boolean(options && options.external);
  sharedSearchSession.ctx = ctx || null;
  sharedSearchSession.options = options || null;
  if (sharedSearchSession.external) {
    cleanupSharedSearchPortal();
  }
  state.hfSearch.open = true;
  state.hfSearch.activeFile = "";
  state.hfSearch.activeSize = null;
  state.hfSearch.activePhase = "";
  if (options && typeof options.destinationMode === "string" && options.destinationMode.trim()) {
    state.hfSearch.destinationMode = options.destinationMode.trim();
  }
  if (options && typeof options.query === "string" && options.query.trim()) {
    state.hfSearch.query = options.query.trim();
  } else if (!String(state.hfSearch.query || "").trim()) {
    state.hfSearch.query = getSearchDefaultQuery();
  }
  if (sharedSearchSession.external) {
    requestSearchRender();
  }
  if (!(state.hfSearch.results || []).length) {
    await runModelSearch(ctx);
  } else {
    requestSearchRender();
  }
  if (sharedSearchSession.external) {
    return new Promise((resolve) => {
      sharedSearchSession.resolve = resolve;
      requestSearchRender();
    });
  }
  return null;
}

async function runModelSearch(ctx) {
  const query = String(state.hfSearch.query || "").trim();
  if (!query) {
    state.hfSearch.status = "Enter a model name to search.";
    requestSearchRender();
    return;
  }
  state.hfSearch.loading = true;
  state.hfSearch.status = `Searching Hugging Face for ${query} GGUF...`;
  requestSearchRender();
  try {
    const res = await api(ctx, "/v1/setup_wizard/model/search", { method: "POST", body: { query, limit: 10 } });
    state.hfSearch.results = Array.isArray(res?.results) ? res.results : [];
    const repoCount = state.hfSearch.results.length;
    const fileCount = state.hfSearch.results.reduce((sum, repo) => sum + ((repo?.gguf_files || []).length || 0), 0);
    state.hfSearch.status = repoCount ? `Found ${repoCount} repositories and ${fileCount} GGUF files.` : "No GGUF repositories found.";
  } catch (err) {
    state.hfSearch.results = [];
    state.hfSearch.status = String(err?.message || err || "Search failed");
  } finally {
    state.hfSearch.loading = false;
    requestSearchRender();
  }
}

async function useSearchedModel(ctx, repoId, filename, fileSize) {
  state.hfSearch.loading = true;
  state.hfSearch.activeFile = String(filename || "");
  state.hfSearch.activeSize = Number.isFinite(Number(fileSize)) ? Number(fileSize) : null;
  state.hfSearch.activePhase = "queued";
  state.hfSearch.status = `Queued ${filename} for download...`;
  requestSearchRender();
  try {
    const backendMode = getSearchBackendMode();
    const finalRow = await runModelDownloadJob(ctx, repoId, filename, backendMode);
    const res = finalRow.result || {};
    let mmprojSource = "";
    if (sharedSearchSession.options?.includeMmproj) {
      const mmprojFile = pickRepoMmprojFile(findSearchRepo(repoId));
      if (mmprojFile?.filename) {
        try {
          state.hfSearch.activeFile = String(mmprojFile.filename || "");
          state.hfSearch.activeSize = Number.isFinite(Number(mmprojFile.size)) ? Number(mmprojFile.size) : null;
          state.hfSearch.activePhase = "queued";
          state.hfSearch.status = `Queued ${mmprojFile.filename} for download...`;
          requestSearchRender();
          const mmprojRow = await runModelDownloadJob(ctx, repoId, mmprojFile.filename, backendMode);
          mmprojSource = String(mmprojRow?.result?.model_source || "").trim();
        } catch (_mmprojErr) {
          mmprojSource = "";
        }
      }
    }
    const payload = {
      repoId: String(repoId || ""),
      filename: String(filename || ""),
      fileSize: Number.isFinite(Number(fileSize)) ? Number(fileSize) : null,
      backendMode,
      modelSource: String(res?.model_source || "").trim(),
      mmprojSource,
      cachePath: String(res?.cache_path || "").trim(),
      savedPath: String(res?.saved_path || "").trim(),
      copiedPath: String(res?.copied_path || "").trim(),
      suggestedModelEntryId: String(filename || repoId || "")
        .replace(/\.gguf$/i, "")
        .replace(/[^a-z0-9._-]+/gi, "_"),
      result: res,
    };
    if (!sharedSearchSession.external) {
      state.draft.model_source = payload.modelSource;
      state.draft.model_label = String(filename || repoId || "").trim();
      state.draft.model_entry_id = payload.suggestedModelEntryId;
      saveDraft();
    }
    state.hfSearch.activePhase = String(finalRow.phase || "complete");
    state.hfSearch.status = String(finalRow.status || "Model selected.");
    closeModelSearch(payload);
  } catch (err) {
    state.hfSearch.activePhase = "error";
    state.hfSearch.status = String(err?.message || err || "Download failed");
    requestSearchRender();
  } finally {
    state.hfSearch.loading = false;
  }
}

function setAllReposCollapsed(collapsed) {
  const map = {};
  for (const repo of Array.isArray(state.hfSearch.results) ? state.hfSearch.results : []) {
    const repoId = String(repo?.repo_id || "").trim();
    if (!repoId) continue;
    map[repoId] = Boolean(collapsed);
  }
  state.hfSearch.collapsedRepos = map;
}

function buildBadgeLegend() {
  const details = document.createElement("details");
  details.className = "sw-legend";
  details.open = false;
  const title = document.createElement("summary");
  title.className = "sw-legend-title";
  title.textContent = "Badge guide";
  details.appendChild(title);
  const grid = document.createElement("div");
  grid.className = "sw-legend-grid";
  const items = [
    ["Safe", "ok", "Likely primary text model file."],
    ["Auxiliary", "warn", "Usually helper files like mmproj, adapter, or imatrix."],
    ["Single", "ok", "Single GGUF file, preferred by this app."],
    ["Sharded", "danger", "Multi-part GGUF split across files."],
    ["MMProj", "warn", "Multimodal projector file, not the main text model."],
    ["IMatrix", "warn", "Importance matrix or auxiliary quant data."],
    ["Adapter", "warn", "LoRA/adapter-style file, not the main base model."],
  ];
  for (const [label, cls, desc] of items) {
    const row = document.createElement("div");
    row.className = "sw-legend-item";
    const badge = document.createElement("span");
    badge.className = `sw-badge ${cls}`.trim();
    badge.textContent = label;
    const text = document.createElement("div");
    text.textContent = desc;
    row.appendChild(badge);
    row.appendChild(text);
    grid.appendChild(row);
  }
  details.appendChild(grid);
  return details;
}

function buildFileBadges(file) {
  const row = document.createElement("div");
  row.className = "sw-badge-row";
  const add = (label, className) => {
    const badge = document.createElement("span");
    badge.className = `sw-badge ${className || ""}`.trim();
    badge.textContent = label;
    row.appendChild(badge);
  };
  if (file?.is_safe !== false) add("Safe", "ok");
  else add("Auxiliary", "warn");
  if (file?.is_single_file !== false) add("Single", "ok");
  else add("Sharded", "danger");
  const low = String(file?.filename || "").toLowerCase();
  if (low.includes("mmproj")) add("MMProj", "warn");
  if (low.includes("imatrix")) add("IMatrix", "warn");
  if (low.includes("lora") || low.includes("adapter")) add("Adapter", "warn");
  return row.childNodes.length ? row : null;
}

function isRepoCollapsed(repoId) {
  const map = state.hfSearch.collapsedRepos || {};
  if (!Object.prototype.hasOwnProperty.call(map, repoId)) return true;
  return Boolean(map[repoId]);
}

function setRepoCollapsed(repoId, collapsed) {
  state.hfSearch.collapsedRepos = state.hfSearch.collapsedRepos || {};
  state.hfSearch.collapsedRepos[repoId] = Boolean(collapsed);
}

function scoreSearchFile(file) {
  const low = String(file?.filename || "").toLowerCase();
  const pref = String(state.hfSearch.quantPreference || "q4_k_m").toLowerCase();
  let score = 0;
  if (file?.is_safe !== false) score += 120;
  if (file?.is_single_file !== false) score += 120;
  const hasQ4 = /q4_k_m/.test(low);
  const hasQ5 = /q5_k_m/.test(low);
  const hasQ6 = /q6_k/.test(low);
  const hasQ8 = /q8_0/.test(low);
  const hasF16 = /bf16|f16/.test(low);
  if (hasQ4) score += 40;
  if (hasQ5) score += 38;
  if (hasQ6) score += 34;
  if (hasQ8) score += 24;
  if (hasF16) score += 12;
  if (pref === "q4_k_m") {
    if (hasQ4) score += 90;
    if (hasQ5) score += 35;
    if (hasQ6) score += 20;
  } else if (pref === "q5_k_m") {
    if (hasQ5) score += 90;
    if (hasQ4) score += 35;
    if (hasQ6) score += 28;
  } else if (pref === "highest_quality") {
    if (hasF16) score += 95;
    if (hasQ8) score += 60;
    if (hasQ6) score += 35;
  } else if (pref === "smallest") {
    const size = Number(file?.size || 0);
    if (size > 0) score -= Math.min(80, size / (1024 ** 3) * 4);
    if (hasQ4) score += 45;
    if (hasQ5) score += 18;
    if (hasF16) score -= 40;
  }
  if (/instruct|chat/.test(low)) score += 12;
  if (/mmproj|adapter|lora|imatrix|vision|projector/.test(low)) score -= 250;
  if (/00001-of|shard|split|part/.test(low)) score -= 180;
  const size = Number(file?.size || 0);
  if (size > 0) score += Math.min(20, size / (1024 ** 3));
  return score;
}

function pickBestSearchFile(files) {
  const list = Array.isArray(files) ? files : [];
  let best = null;
  let bestScore = -Infinity;
  for (const file of list) {
    const score = scoreSearchFile(file);
    if (score > bestScore) {
      best = file;
      bestScore = score;
    }
  }
  return best ? { file: best, score: bestScore } : null;
}

function compareSearchRepos(a, b, mode) {
  const leftDownloads = Number(a?.downloads || 0);
  const rightDownloads = Number(b?.downloads || 0);
  const leftLikes = Number(a?.likes || 0);
  const rightLikes = Number(b?.likes || 0);
  const leftId = String(a?.repo_id || "").toLowerCase();
  const rightId = String(b?.repo_id || "").toLowerCase();
  if (mode === "likes_desc") {
    if (rightLikes !== leftLikes) return rightLikes - leftLikes;
    if (rightDownloads !== leftDownloads) return rightDownloads - leftDownloads;
    return leftId.localeCompare(rightId);
  }
  if (mode === "name_asc") return leftId.localeCompare(rightId);
  if (rightDownloads !== leftDownloads) return rightDownloads - leftDownloads;
  if (rightLikes !== leftLikes) return rightLikes - leftLikes;
  return leftId.localeCompare(rightId);
}

function compareSearchFiles(a, b, mode) {
  const leftName = String(a?.filename || "").toLowerCase();
  const rightName = String(b?.filename || "").toLowerCase();
  const leftSize = Number(a?.size || 0);
  const rightSize = Number(b?.size || 0);
  if (mode === "name_asc") return leftName.localeCompare(rightName);
  if (mode === "name_desc") return rightName.localeCompare(leftName);
  if (rightSize !== leftSize) return rightSize - leftSize;
  return leftName.localeCompare(rightName);
}

function getVisibleSearchResults() {
  const filter = String(state.hfSearch.filenameFilter || "").trim().toLowerCase();
  const repoSort = String(state.hfSearch.repoSort || "downloads_desc").trim();
  const fileSort = String(state.hfSearch.fileSort || "size_desc").trim();
  const safeOnly = state.hfSearch.safeOnly !== false;
  const singleFileOnly = state.hfSearch.singleFileOnly !== false;
  const repos = Array.isArray(state.hfSearch.results) ? state.hfSearch.results.slice() : [];
  repos.sort((a, b) => compareSearchRepos(a, b, repoSort));
  const visible = [];
  for (const repo of repos) {
    const files = Array.isArray(repo?.gguf_files) ? repo.gguf_files.slice() : [];
    files.sort((a, b) => compareSearchFiles(a, b, fileSort));
    const filteredFiles = files.filter((file) => {
      const name = String(file?.filename || "").toLowerCase();
      if (filter && !name.includes(filter)) return false;
      if (safeOnly && file?.is_safe === false) return false;
      if (singleFileOnly && file?.is_single_file === false) return false;
      return true;
    });
    if (!filteredFiles.length) continue;
    visible.push({ ...repo, visible_count: filteredFiles.length, total_count: files.length, gguf_files: filteredFiles });
  }
  return visible;
}

function buildModelSearchModal(ctx) {
  if (!state.hfSearch.open) return null;
  const modal = document.createElement("div");
  modal.className = "sw-modal";
  modal.addEventListener("click", (event) => {
    if (event.target === modal && !state.hfSearch.loading) {
      closeModelSearch(null);
    }
  });
  const card = document.createElement("div");
  card.className = "sw-modal-card";
  const head = document.createElement("div");
  head.className = "sw-modal-head";
  const titleWrap = document.createElement("div");
  titleWrap.innerHTML = `<div class="sw-modal-title">Search GGUF models</div><div class="sw-sub">Search HuggingFace for GGUF repositories that match the preset model hint. Selecting a file will save it into the Hugging Face cache for embedded mode or copy it into data/models for llama.cpp server mode.</div>`;
  const close = document.createElement("button");
  close.type = "button";
  close.className = "sw-modal-close";
  close.textContent = "Close";
  close.disabled = Boolean(state.hfSearch.loading);
  close.addEventListener("click", () => { closeModelSearch(null); });
  head.appendChild(titleWrap);
  head.appendChild(close);
  card.appendChild(head);
  const searchRow = document.createElement("div");
  searchRow.className = "sw-inline-grid";
  const query = document.createElement("input");
  query.type = "text";
  query.value = state.hfSearch.query || "";
  query.placeholder = "Qwen Coder";
  query.addEventListener("input", () => { state.hfSearch.query = query.value; });
  query.addEventListener("keydown", async (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      await runModelSearch(ctx);
    }
  });
  const fileFilter = document.createElement("input");
  fileFilter.type = "text";
  fileFilter.value = state.hfSearch.filenameFilter || "";
  fileFilter.placeholder = "Q4_K_M or 7B";
  fileFilter.addEventListener("input", () => {
    state.hfSearch.filenameFilter = fileFilter.value;
    requestSearchRender();
  });
  const repoSort = document.createElement("select");
  [["downloads_desc", "Repos: Most downloads"], ["likes_desc", "Repos: Most likes"], ["name_asc", "Repos: Name A-Z"]].forEach(([value, label]) => repoSort.appendChild(new Option(label, value)));
  repoSort.value = state.hfSearch.repoSort || "downloads_desc";
  repoSort.addEventListener("change", () => {
    state.hfSearch.repoSort = repoSort.value;
    requestSearchRender();
  });
  const fileSort = document.createElement("select");
  [["size_desc", "Files: Largest first"], ["name_asc", "Files: Name A-Z"], ["name_desc", "Files: Name Z-A"]].forEach(([value, label]) => fileSort.appendChild(new Option(label, value)));
  fileSort.value = state.hfSearch.fileSort || "size_desc";
  fileSort.addEventListener("change", () => {
    state.hfSearch.fileSort = fileSort.value;
    requestSearchRender();
  });
  searchRow.appendChild(field("Search HuggingFace", query));
  searchRow.appendChild(field("Filter filenames", fileFilter));
  searchRow.appendChild(field("Repo sort", repoSort));
  searchRow.appendChild(field("File sort", fileSort));
  card.appendChild(searchRow);
  const toggleRow = document.createElement("div");
  toggleRow.className = "sw-toggle-row";
  const safeToggle = document.createElement("label");
  safeToggle.className = "sw-checklabel";
  const safeInput = document.createElement("input");
  safeInput.type = "checkbox";
  safeInput.checked = state.hfSearch.safeOnly !== false;
  safeInput.addEventListener("change", () => {
    state.hfSearch.safeOnly = Boolean(safeInput.checked);
    requestSearchRender();
  });
  safeToggle.appendChild(safeInput);
  safeToggle.appendChild(document.createTextNode("Safe files only"));
  const singleToggle = document.createElement("label");
  singleToggle.className = "sw-checklabel";
  const singleInput = document.createElement("input");
  singleInput.type = "checkbox";
  singleInput.checked = state.hfSearch.singleFileOnly !== false;
  singleInput.addEventListener("change", () => {
    state.hfSearch.singleFileOnly = Boolean(singleInput.checked);
    requestSearchRender();
  });
  singleToggle.appendChild(singleInput);
  singleToggle.appendChild(document.createTextNode("Single-file GGUF only"));
  toggleRow.appendChild(safeToggle);
  toggleRow.appendChild(singleToggle);
  card.appendChild(toggleRow);
  const searchActions = document.createElement("div");
  searchActions.className = "sw-actions";
  searchActions.appendChild(button(state.hfSearch.loading ? "Searching..." : "Search models", async () => { await runModelSearch(ctx); }, "primary compact"));
  searchActions.appendChild(button("Expand all", async () => { setAllReposCollapsed(false); requestSearchRender(); }, "ghost compact"));
  searchActions.appendChild(button("Collapse all", async () => { setAllReposCollapsed(true); requestSearchRender(); }, "ghost compact"));
  const destination = document.createElement("select");
  [["auto", getSearchBackendMode() === "embedded" ? "Save for embedded (HF cache)" : "Save for llama.cpp server (data/models)"], ["hf_cache", "Save to HF cache only"], ["models_dir", "Save to data/models only"], ["both", "Save to both"]].forEach(([value, label]) => destination.appendChild(new Option(label, value)));
  destination.value = state.hfSearch.destinationMode || "auto";
  destination.addEventListener("change", () => {
    state.hfSearch.destinationMode = destination.value;
    requestSearchRender();
  });
  const quantPref = document.createElement("select");
  [["q4_k_m", "Prefer Q4_K_M"], ["q5_k_m", "Prefer Q5_K_M"], ["highest_quality", "Prefer highest quality"], ["smallest", "Prefer smallest"]].forEach(([value, label]) => quantPref.appendChild(new Option(label, value)));
  quantPref.value = state.hfSearch.quantPreference || "q4_k_m";
  quantPref.addEventListener("change", () => {
    state.hfSearch.quantPreference = quantPref.value;
    requestSearchRender();
  });
  searchActions.appendChild(field("Destination", destination));
  searchActions.appendChild(field("Best-file preference", quantPref));
  card.appendChild(searchActions);
  if (state.hfSearch.status) {
    const statusCard = document.createElement("div");
    statusCard.className = "sw-status-card";
    const phaseLabel = state.hfSearch.activePhase ? String(state.hfSearch.activePhase) : (state.hfSearch.loading ? "working" : "idle");
    statusCard.innerHTML = `<div class="sw-status-title">Current phase</div><div class="sw-status-main">${phaseLabel || "idle"}</div><div class="sw-status-meta">${state.hfSearch.status}</div>`;
    if (state.hfSearch.activeFile) {
      const meta = document.createElement("div");
      meta.className = "sw-status-meta";
      const expected = Number(state.hfSearch.activeExpected || state.hfSearch.activeSize || 0);
      const downloaded = Number(state.hfSearch.activeDownloaded || 0);
      if (expected > 0 && downloaded > 0) meta.textContent = `${state.hfSearch.activeFile} ${formatBytes(downloaded)} / ${formatBytes(expected)}`;
      else if (expected > 0) meta.textContent = `${state.hfSearch.activeFile} ${formatBytes(expected)}`;
      else meta.textContent = state.hfSearch.activeFile;
      statusCard.appendChild(meta);
    }
    card.appendChild(statusCard);
  }
  card.appendChild(buildBadgeLegend());
  const list = document.createElement("div");
  list.className = "sw-repo-list";
  const visibleResults = getVisibleSearchResults();
  for (const repo of visibleResults) {
    const repoCard = document.createElement("div");
    repoCard.className = "sw-repo-card";
    const downloads = Number(repo?.downloads || 0);
    const likes = Number(repo?.likes || 0);
    const bestPick = pickBestSearchFile(repo.gguf_files || []);
    const bestName = String(bestPick?.file?.filename || "");
    const details = document.createElement("details");
    details.open = !isRepoCollapsed(repo.repo_id);
    details.addEventListener("toggle", () => setRepoCollapsed(repo.repo_id, !details.open));
    const summary = document.createElement("summary");
    summary.className = "sw-repo-summary";
    summary.innerHTML = `<div><div class="sw-repo-id">${repo.repo_id}</div><div class="sw-repo-meta">Downloads: ${downloads || 0} | Likes: ${likes || 0} | ${repo.pipeline_tag || "model"}</div></div><div class="sw-repo-count">${repo.visible_count}/${repo.total_count} files</div>`;
    details.appendChild(summary);
    const head = document.createElement("div");
    head.className = "sw-repo-head";
    head.innerHTML = `<div class="sw-note">Visible GGUF files for this repo${bestName ? ` | Best candidate: ${bestName} (${String(state.hfSearch.quantPreference || "q4_k_m").replace(/_/g, " ")})` : ""}</div><a class="sw-link" href="${repo.repo_url}" target="_blank" rel="noreferrer">Open repo</a>`;
    details.appendChild(head);
    const files = document.createElement("div");
    files.className = "sw-file-list";
    for (const file of repo.gguf_files || []) {
      const row = document.createElement("div");
      row.className = "sw-file-row";
      const info = document.createElement("div");
      const isBest = bestName && String(file?.filename || "") === bestName;
      info.innerHTML = `<div class="sw-file-name">${file.filename}</div><div class="sw-note">${file.size != null ? formatBytes(file.size) : "Size unavailable"}${isBest ? " | highlighted best candidate" : ""}</div>`;
      const badges = buildFileBadges(file);
      if (isBest) {
        const bestBadge = document.createElement("span");
        bestBadge.className = "sw-badge best";
        bestBadge.textContent = "Best";
        if (badges) badges.prepend(bestBadge);
      }
      if (badges) info.appendChild(badges);
      const act = document.createElement("div");
      act.className = "sw-actions";
      act.appendChild(button(state.hfSearch.loading ? "Saving..." : "Use this file", async () => { await useSearchedModel(ctx, repo.repo_id, file.filename, file.size); }, "primary"));
      row.appendChild(info);
      row.appendChild(act);
      files.appendChild(row);
    }
    details.appendChild(files);
    repoCard.appendChild(details);
    list.appendChild(repoCard);
  }
  if (!visibleResults.length && !state.hfSearch.loading) {
    const empty = document.createElement("div");
    empty.className = "sw-note";
    empty.textContent = (state.hfSearch.results || []).length ? "No files match the current filename filter." : "No results yet. Search using the preset model hint or edit the query.";
    list.appendChild(empty);
  }
  card.appendChild(list);
  modal.appendChild(card);
  return modal;
}

function renderSharedSearchPortal() {
  if (!sharedSearchSession.external) {
    cleanupSharedSearchPortal();
    return;
  }
  const ctx = sharedSearchSession.ctx;
  if (!ctx || !state.hfSearch.open) {
    cleanupSharedSearchPortal();
    return;
  }
  if (!sharedSearchSession.portal) {
    const portal = document.createElement("div");
    portal.dataset.setupWizardSharedSearch = "1";
    portal.style.position = "fixed";
    portal.style.inset = "0";
    portal.style.zIndex = "2147483647";
    portal.style.pointerEvents = "none";
    sharedSearchSession.portal = portal;
    document.body.appendChild(portal);
  }
  sharedSearchSession.portal.innerHTML = "";
  const modal = buildModelSearchModal(ctx);
  if (modal) {
    modal.style.pointerEvents = "auto";
    sharedSearchSession.portal.appendChild(modal);
  }
}

function buildModelStep(ctx) {
  const wrap = document.createElement("div");
  wrap.className = "sw-panel";
  wrap.innerHTML = `<div class="sw-title">Model source and backend</div><div class="sw-sub">Point the wizard at the starter model you want to use. It can be a local GGUF path or another source that your current stack already supports.</div>`;
  const searchActions = document.createElement("div");
  searchActions.className = "sw-actions";
  const searchBtn = button("Search HuggingFace GGUF", async () => {
    const picked = await openModelSearch(ctx, {
      query: getProfileSearchQuery(),
      backendMode: state.draft.backend_mode,
      destinationMode: state.draft.backend_mode === "embedded" ? "hf_cache" : "models_dir",
      includeMmproj: String(state.draft.type_id || "").trim().toLowerCase() === "vlm",
    });
    if (!picked) return;
    state.draft.model_source = String(picked.modelSource || "").trim();
    state.draft.model_label = String(picked.filename || picked.repoId || "").trim();
    if (!String(state.draft.model_entry_id || "").trim()) {
      state.draft.model_entry_id = String(picked.suggestedModelEntryId || "").trim();
    }
    saveDraft();
    renderLast?.();
  }, "ghost");
  searchActions.appendChild(searchBtn);
  wrap.appendChild(searchActions);
  const grid = document.createElement("div");
  grid.className = "sw-inline-grid";
  const source = document.createElement("input");
  source.type = "text";
  source.value = state.draft.model_source || "";
  source.placeholder = "C:\\models\\model.gguf or data/models/model.gguf";
  source.addEventListener("change", () => { state.draft.model_source = source.value.trim(); saveDraft(); });
  const modelId = document.createElement("input");
  modelId.type = "text";
  modelId.value = state.draft.model_entry_id || "";
  modelId.placeholder = "qwen3_main";
  modelId.addEventListener("change", () => { state.draft.model_entry_id = modelId.value.trim(); saveDraft(); });
  const backend = document.createElement("select");
  [["llama_server", "llama.cpp server"], ["embedded", "Embedded GGUF"]].forEach(([value, label]) => backend.appendChild(new Option(label, value)));
  backend.value = state.draft.backend_mode;
  backend.addEventListener("change", () => {
    state.draft.backend_mode = backend.value;
    state.draft.use_managed_server = backend.value === "llama_server";
    saveDraft();
    renderLast?.();
  });
  const runtime = document.createElement("select");
  const runtimes = Array.isArray(state.bootstrap?.hardware?.runtime_options) ? state.bootstrap.hardware.runtime_options : [];
  const runtimeIds = new Set();
  for (const row of runtimes) {
    const id = String(row?.id || "").trim();
    if (!id || runtimeIds.has(id)) continue;
    runtimeIds.add(id);
    runtime.appendChild(new Option(row.label || id, id));
  }
  if (!runtime.children.length) ["vulkan", "sycl", "cuda", "cpu"].forEach((id) => runtime.appendChild(new Option(id, id)));
  runtime.value = state.draft.runtime_id || "vulkan";
  runtime.addEventListener("change", () => { state.draft.runtime_id = runtime.value; saveDraft(); });
  const port = document.createElement("input");
  port.type = "number";
  port.value = String(state.draft.port || 8087);
  port.addEventListener("change", () => { state.draft.port = Number(port.value || 8087); saveDraft(); });
  const ctxSize = document.createElement("input");
  ctxSize.type = "number";
  ctxSize.value = String(state.draft.ctx_size || 8192);
  ctxSize.addEventListener("change", () => { state.draft.ctx_size = Number(ctxSize.value || 8192); saveDraft(); });
  const parallel = document.createElement("input");
  parallel.type = "number";
  parallel.value = String(state.draft.parallel_slots || 1);
  parallel.addEventListener("change", () => { state.draft.parallel_slots = Number(parallel.value || 1); saveDraft(); });
  const embedded = isEmbeddedBackend();
  grid.appendChild(field("Model source", source));
  grid.appendChild(field("Deck model id", modelId));
  grid.appendChild(field("Backend", backend));
  if (!embedded) grid.appendChild(field("Runtime", runtime));
  if (!embedded) grid.appendChild(field("Port", port));
  grid.appendChild(field("Context size", ctxSize));
  grid.appendChild(field("Parallel slots", parallel));
  wrap.appendChild(grid);
  const toggleRow = document.createElement("div");
  toggleRow.className = "sw-pillrow";
  [["mmap", "Memory-map model file"], ["kv_unified", "Unified KV cache buffer"], ["flash_attn", "Flash Attention"], ["offload_kqv", "Offload K/Q/V + KV cache to GPU"]].forEach(([key, label]) => {
    const pill = document.createElement("button");
    pill.type = "button";
    pill.className = `sw-pill ${state.draft[key] ? "is-active" : ""}`.trim();
    pill.textContent = label;
    pill.addEventListener("click", () => {
      state.draft[key] = !state.draft[key];
      saveDraft();
      renderLast?.();
    });
    toggleRow.appendChild(pill);
  });
  wrap.appendChild(toggleRow);
  const actions = document.createElement("div");
  actions.className = "sw-actions";
  actions.appendChild(button("Validate model source", async () => { await resolveModel(ctx); renderLast?.(); }, "primary"));
  wrap.appendChild(actions);
  if (state.modelInfo) {
    const summary = document.createElement("div");
    summary.className = "sw-summary";
    summary.innerHTML = `<strong>Validation result</strong><div class="sw-note">Source kind: ${state.modelInfo.source_kind} | Exists locally: ${state.modelInfo.exists_local ? "yes" : "no"} | Suggested type: ${state.modelInfo.suggested_type_id}</div>`;
    wrap.appendChild(summary);
  }
  return wrap;
}

function buildStepNav(ctx) {
  const currentIndex = steps.findIndex((step) => step.id === state.activeStep);
  const wrap = document.createElement("div");
  wrap.className = "sw-actions";
  const prev = document.createElement("button");
  prev.type = "button";
  prev.className = "sw-btn ghost";
  prev.textContent = currentIndex > 0 ? `Previous: ${steps[currentIndex - 1].title}` : "Previous";
  prev.disabled = currentIndex <= 0;
  prev.addEventListener("click", async (event) => {
    event.preventDefault();
    event.stopPropagation();
    const liveIndex = steps.findIndex((step) => step.id === state.activeStep);
    const navIndex = liveIndex >= 0 ? liveIndex : currentIndex;
    if (navIndex <= 0) return;
    await persistActiveStep(ctx);
    state.activeStep = steps[navIndex - 1].id;
    renderLast?.();
  });
  const next = document.createElement("button");
  next.type = "button";
  next.className = "sw-btn primary";
  next.textContent = currentIndex < steps.length - 1 ? `Next: ${steps[currentIndex + 1].title}` : "Finish";
  next.disabled = false;
  next.addEventListener("click", async (event) => {
    event.preventDefault();
    event.stopPropagation();
    const liveIndex = steps.findIndex((step) => step.id === state.activeStep);
    const navIndex = liveIndex >= 0 ? liveIndex : currentIndex;
    await persistActiveStep(ctx);
    if (navIndex >= steps.length - 1) {
      if (!state.applyResult || !state.testResult?.passed) {
        alert("Apply the wizard configuration and run a passing validation test before finishing.");
        state.activeStep = "apply";
        renderLast?.();
        return;
      }
      closeWizardPanel(ctx);
      return;
    }
    state.activeStep = steps[navIndex + 1].id;
    renderLast?.();
  });
  wrap.appendChild(prev);
  wrap.appendChild(next);
  return wrap;
}

function buildApplyStep(ctx) {
  const wrap = document.createElement("div");
  wrap.className = "sw-panel";
  wrap.innerHTML = `<div class="sw-title">Apply and test</div><div class="sw-sub">This step writes the selected model into Model Deck, installs the selected llama.cpp runtime if this is a fresh machine, creates or updates the managed llama-server entry, and then checks whether the required pieces are in place.</div>`;
  const profile = getActiveProfile();
  const runtimeSummary = isEmbeddedBackend() ? "embedded runtime" : state.draft.runtime_id;
  const preview = document.createElement("div");
  preview.className = "sw-summary";
  preview.innerHTML = `<div><strong>Selected preset:</strong> ${profile?.title || "Manual configuration"}</div><div class="sw-note">Intent: ${state.draft.intent} | Backend: ${state.draft.backend_mode} | Runtime: ${runtimeSummary} | Model: ${state.draft.model_source || "(not set)"}</div><div class="sw-note">Main/default: ${state.draft.set_main ? "main" : "not main"}, ${state.draft.set_default ? "default" : "not default"} | Persist: ${state.draft.persist ? "yes" : "no"} | Lazy: ${state.draft.lazy ? "yes" : "no"}</div>`;
  wrap.appendChild(preview);
  const actions = document.createElement("div");
  actions.className = "sw-actions";
  actions.appendChild(button("Apply wizard configuration", async () => { await applyWizard(ctx); renderLast?.(); }, "primary", { loadingLabel: "Applying wizard configuration..." }));
  actions.appendChild(button("Run validation test", async () => { await runTest(ctx); renderLast?.(); }, "ghost", { loadingLabel: "Running validation test..." }));
  if (state.applyResult && state.testResult?.passed) {
    actions.appendChild(button("Finish setup", async () => { closeWizardPanel(ctx); }, "primary"));
  }
  wrap.appendChild(actions);
  if (state.applyResult) {
    const applyBox = document.createElement("div");
    applyBox.className = "sw-summary";
    const server = state.applyResult?.server || {};
    const serverDetail = server.skipped
      ? "Managed server skipped"
      : server.ok
        ? `Managed server saved: ${server.server_id || server?.server?.id || state.draft.managed_server_id || "wizard-main"}${server.runtime_installed_by_wizard ? " (runtime installed by wizard)" : ""}`
        : `Managed server warning: ${server.warning || server.error || "not saved"}`;
    applyBox.innerHTML = `<strong>Applied</strong><div class="sw-note">Model Deck entry: ${state.applyResult?.model?.model_id || "n/a"}\n${serverDetail}</div>`;
    wrap.appendChild(applyBox);
  }
  if (state.testResult) {
    const list = document.createElement("div");
    list.className = "sw-checks";
    for (const row of (state.testResult.checks || [])) {
      const item = document.createElement("div");
      item.className = "sw-check";
      item.innerHTML = `<div><strong>${row.label}</strong><div class="sw-note">${row.detail || ""}</div></div><div class="${row.ok ? "sw-ok" : "sw-bad"}">${row.ok ? "Ready" : "Fix needed"}</div>`;
      list.appendChild(item);
    }
    wrap.appendChild(list);
    const done = document.createElement("div");
    done.className = `sw-summary ${state.testResult.passed ? "sw-ok" : "sw-bad"}`;
    done.textContent = state.testResult.passed ? "Wizard validation passed. The starter stack is ready for admin use." : "Wizard validation found remaining issues. Fix the failed checks before handing the app to users.";
    wrap.appendChild(done);
  }
  return wrap;
}

function renderPanel(container, ctx) {
  ensureStyles();
  renderLast = () => renderPanel(container, ctx);
  container.innerHTML = "";
  const root = document.createElement("div");
  root.className = "sw-root";
  root.appendChild(buildSidebar(renderLast));
  const main = document.createElement("div");
  main.className = "sw-main";
  if (!state.bootstrap) {
    const loading = document.createElement("div");
    loading.className = "sw-panel";
    loading.innerHTML = `<div class="sw-title">Loading wizard</div><div class="sw-note">Fetching environment details and current wizard state.</div>`;
    main.appendChild(loading);
    root.appendChild(main);
    container.appendChild(root);
    ensureBootstrapCurrent(ctx).then(() => refreshRecommendations(ctx)).then(() => renderPanel(container, ctx)).catch((err) => {
      loading.innerHTML = `<div class="sw-title">Setup wizard unavailable</div><div class="sw-note">${String(err?.message || err || "Unknown error")}</div>`;
    });
    return;
  }
  if (state.activeStep === "welcome") main.appendChild(buildWelcomeStep(ctx));
  else if (state.activeStep === "workflow_exchange") main.appendChild(buildWorkflowExchangeStep(ctx));
  else if (state.activeStep === "network") main.appendChild(buildNetworkStep(ctx));
  else if (state.activeStep === "hardware") main.appendChild(buildHardwareStep(ctx));
  else if (state.activeStep === "profiles") main.appendChild(buildProfilesStep(ctx));
  else if (state.activeStep === "model") main.appendChild(buildModelStep(ctx));
  else main.appendChild(buildApplyStep(ctx));
  const searchModal = buildModelSearchModal(ctx);
  if (searchModal) main.appendChild(searchModal);
  main.appendChild(buildStepNav(ctx));
  root.appendChild(main);
  container.appendChild(root);
}

function createSharedGgufSearchApi() {
  return {
    id: "setup_wizard_gguf_search",
    type: "model_search_provider",
    service: "huggingface_gguf",
    async open(ctx, options = {}) {
      return openModelSearch(ctx, { ...options, external: true });
    },
  };
}

function buildLauncher(ctx, host) {
  if (wizardDismissed()) return null;
  if (!state.bootstrap || state.bootstrapKey !== currentBootstrapKey(ctx)) {
    ensureBootstrapCurrent(ctx).then(() => {
      const summary = state.bootstrap?.summary || {};
      const stateInfo = state.bootstrap?.state || {};
      if (currentUserLooksAdmin(ctx) && !stateInfo.completed && !wizardDismissed()) {
        const username = String(ctx?.getState?.()?.auth?.username || summary?.username || "admin");
        const autoKey = `${AUTO_OPEN_KEY}:${username}`;
        const already = window.localStorage.getItem(autoKey) === "1";
        if (!already) {
          window.localStorage.setItem(autoKey, "1");
          setTimeout(() => host.openPluginPanel(meta.plugin_id, { openModal: true }), 250);
        }
      }
      renderLast?.();
    }).catch(() => {});
    return null;
  }
  const summary = state.bootstrap?.summary || {};
  if (!currentUserLooksAdmin(ctx)) return null;
  const stateInfo = state.bootstrap?.state || {};
  if (stateInfo.completed) return null;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "sw-launcher";
  const incomplete = !stateInfo.completed;
  btn.innerHTML = `${incomplete ? '<span class="sw-launcher-dot"></span>' : ""}<span>Setup</span>`;
  btn.addEventListener("click", () => host.openPluginPanel(meta.plugin_id, { openModal: true }));
  if (incomplete && state.bootstrap) {
    try {
      const username = String(ctx?.getState?.()?.auth?.username || summary?.username || "admin");
      const autoKey = `${AUTO_OPEN_KEY}:${username}`;
      const already = window.localStorage.getItem(autoKey) === "1";
      if (!already) {
        window.localStorage.setItem(autoKey, "1");
        setTimeout(() => host.openPluginPanel(meta.plugin_id, { openModal: true }), 250);
      }
    } catch (_err) {}
  }
  return btn;
}

const plugin = {
  id: meta.plugin_id,
  name: meta.name,
  kind: meta.kind,
  description: meta.description,
  meta,
  register(host) {
    ensureStyles();
    bindAuthRefresh(host, () => ({ ...(host.getState ? { getState: host.getState } : {}), apiJson: host.apiJson }));
    host.shareObject(createSharedGgufSearchApi());
    host.addPanelTab({
      id: meta.plugin_id,
      title: "Setup Wizard",
      windowType: "full",
      render: (container, ctx) => renderPanel(container, ctx),
    });
    host.addTopRightIconRow((ctx) => buildLauncher(ctx, host));
  },
};

export default plugin;
