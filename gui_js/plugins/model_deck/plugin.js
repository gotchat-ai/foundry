const meta = {
  plugin_id: "model_deck",
  name: "Model Deck",
  kind: "panel",
  description: "Catalog model types + saved loader settings; exposes deck endpoints for routers/agents.",
  has_notebook_tab: true,
};

const STYLE_ID = "model-deck-style";
const DEFAULT_TYPE_ORDER = [
  "text_llm",
  "vlm",
  "os_agent",
  "retrieval",
  "speech",
  "safety",
  "image_gen",
  "video_gen",
  "control",
  "gen3d",
];
const HIDDEN_OVERVIEW_TYPE_IDS = new Set([
  "os_agent",
  "retrieval",
  "safety",
  "control",
  "gen3d",
]);
const HIDDEN_EDITOR_LOADER_IDS = new Set([
  "model_loader.model_deck.os_agent",
  "model_loader.model_deck.retrieval",
  "model_loader.model_deck.safety",
  "model_loader.model_deck.3d",
]);
const TYPE_META_ENABLED = false;

let processStream = { token: 0, controller: null };
let deckTimer = null;
let deckButton = null;
let deckBadge = null;
let deckPopover = null;
let deckOpen = false;
let deckOutsideHandler = null;
let deckState = { processes: {} };
const deckPending = new Map();
const DECK_POLL_MS = 4000;
let deckNavRequest = null; // { action: "open" | "edit-model", typeId?: string, modelId?: string }
let modelInfoTimer = null;
let lastSharedModelSig = "";
let modelDeckCache = { ts: 0, deck: null };
const CACHE_OWNER_MODEL_DECK = "model_deck";
const CACHE_KEY_DECK = "deck";
const CACHE_KEY_POPOVER_PROCESSES = "popover_processes";
const CACHE_KEY_EDITOR_BOOTSTRAP = "editor_bootstrap";
const CACHE_KEY_MANAGED_SERVERS = "managed_servers";
const CACHE_KEY_MANAGED_DEVICE_PREFIX = "managed_devices:";
const CACHE_TTL_DECK_MS = 45000;
const CACHE_TTL_POPOVER_MS = 15000;
const CACHE_TTL_EDITOR_MS = 30000;
const CACHE_TTL_MANAGED_SERVERS_MS = 15000;
const CACHE_TTL_MANAGED_DEVICE_MS = 30000;
const CLIENT_MODE_KEY = "llama_server_client_service_mode";
const CLIENT_TOKEN_KEY = "llama_server_client_service_token";
const LLAMA_MANAGER_PORT = "8767";

const MODEL_INFO_POLL_MS = 12000;
const MODEL_INFO_DECK_REFRESH_MS = 45000;

function getCacheApi(ctx) {
  const shared = ctx?.getSharedObjects?.({ type: "api_provider" }) || [];
  return shared.find((item) => item && item.id === "plugin_cache_api" && item.service === "plugin_cache") || null;
}

function getSetupWizardGgufSearch(ctx) {
  const shared = ctx?.getSharedObjects?.({ pluginId: "setup_wizard", type: "model_search_provider" }) || [];
  return shared.find((item) => item && item.service === "huggingface_gguf" && typeof item.open === "function") || null;
}

function cacheGet(ctx, key) {
  try {
    const api = getCacheApi(ctx);
    if (!api || typeof api.get !== "function") return null;
    return api.get(CACHE_OWNER_MODEL_DECK, key);
  } catch (_err) {
    return null;
  }
}

function cacheSet(ctx, key, value, ttlMs) {
  try {
    const api = getCacheApi(ctx);
    if (!api || typeof api.set !== "function") return value;
    api.set(CACHE_OWNER_MODEL_DECK, key, value, { ttlMs });
  } catch (_err) {}
  return value;
}

function mergeManagedProcessSnapshot(base, managed) {
  const out = base && typeof base === "object" ? JSON.parse(JSON.stringify(base)) : {};
  const managedBySlot = new Map();
  for (const entry of [managed?.main, ...(Array.isArray(managed?.defaults) ? managed.defaults : [])]) {
    if (!entry || typeof entry !== "object") continue;
    const slot = String(entry.slot || "").trim();
    if (slot) managedBySlot.set(slot, entry);
  }
  const apply = (entry) => {
    if (!entry || typeof entry !== "object") return;
    const slot = String(entry.slot || "").trim();
    const patch = managedBySlot.get(slot);
    if (!patch) return;
    const patchLoaded = Boolean(patch.loaded);
    const patchRunning = Boolean(patch.server_running);
    Object.assign(entry, {
      loaded: patchLoaded || patchRunning ? true : (patch.loaded ?? entry.loaded),
      server_running: patch.server_running,
      server_url: _rewriteClientUrl(patch.server_url),
      server_device: patch.server_device,
      server_pid: patch.server_pid,
      cpu_bytes: (patchLoaded || patchRunning) ? (patch.cpu_bytes ?? entry.cpu_bytes) : patch.cpu_bytes,
      gpu_bytes: (patchLoaded || patchRunning) ? (patch.gpu_bytes ?? entry.gpu_bytes) : patch.gpu_bytes,
      phase: patch.phase || ((patchLoaded || patchRunning) ? "loaded" : "stopped"),
      last_error: patchRunning ? "" : (patch.last_error || (patchLoaded ? entry.last_error : "")),
      status_note: patch.status_note || ((patchLoaded || patchRunning) ? entry.status_note : ""),
    });
  };
  apply(out.main);
  for (const entry of Array.isArray(out.defaults) ? out.defaults : []) apply(entry);
  if (managed?.totals && typeof managed.totals === "object") {
    out.totals = { ...(out.totals || {}), ...(managed.totals || {}) };
  }
  return out;
}

function stabilizeManagedProcessSnapshot(prev, next) {
  const out = next && typeof next === "object" ? JSON.parse(JSON.stringify(next)) : {};
  const prevBySlot = new Map();
  for (const entry of [prev?.main, ...(Array.isArray(prev?.defaults) ? prev.defaults : [])]) {
    if (!entry || typeof entry !== "object") continue;
    const slot = String(entry.slot || "").trim();
    if (slot) prevBySlot.set(slot, entry);
  }
  const apply = (entry, kind, typeId) => {
    if (!entry || typeof entry !== "object") return;
    if (String(entry.backend_mode || "").trim().toLowerCase() !== "llama_server") return;
    const slot = String(entry.slot || "").trim();
    if (!slot) return;
    const prevEntry = prevBySlot.get(slot);
    if (!prevEntry || typeof prevEntry !== "object") return;
    const pending = deckPending.get(`${kind}:${typeId || ""}`);
    if (pending === "stop") {
      entry.loaded = false;
      entry.server_running = false;
      entry.phase = "stopping";
      return;
    }
    if (!entry.loaded && prevEntry.loaded && prevEntry.server_running) {
      entry.loaded = true;
      entry.server_running = prevEntry.server_running;
      entry.server_url = prevEntry.server_url || entry.server_url;
      entry.server_device = prevEntry.server_device || entry.server_device;
      entry.server_pid = prevEntry.server_pid || entry.server_pid;
      entry.pid = entry.pid || prevEntry.pid || prevEntry.server_pid || null;
      entry.cpu_bytes = entry.cpu_bytes ?? prevEntry.cpu_bytes;
      entry.gpu_bytes = entry.gpu_bytes ?? prevEntry.gpu_bytes;
      entry.phase = entry.phase || prevEntry.phase || "loaded";
      entry.status_note = entry.status_note || prevEntry.status_note;
      entry.last_error = entry.last_error || prevEntry.last_error;
    }
    if (entry.server_running && !entry.loaded) {
      entry.loaded = true;
      entry.phase = entry.phase || "loaded";
      entry.last_error = "";
    }
  };
  if (out.main && typeof out.main === "object") {
    apply(out.main, "main", out.main.type_id || "text_llm");
  }
  for (const entry of Array.isArray(out.defaults) ? out.defaults : []) {
    if (!entry || typeof entry !== "object") continue;
    apply(entry, "default", entry.type_id || "");
  }
  return out;
}

function _findModelInDeck(deck, typeId, modelId) {
  try {
    const types = deck?.types && typeof deck.types === "object" ? deck.types : {};
    const t = types[typeId];
    if (!t || typeof t !== "object") return null;
    const models = Array.isArray(t.models) ? t.models : [];
    const mid = String(modelId || "").trim();
    if (!mid) return null;
    const m = models.find((x) => String(x?.model_id || x?.modelId || x?.model || "") === mid) || null;
    if (!m || typeof m !== "object") return null;
    const settings = m.settings && typeof m.settings === "object" ? m.settings : {};
    return { type: t, model: m, settings };
  } catch (_err) {
    return null;
  }
}

async function _getDeckCached(ctx) {
  const now = Date.now();
  const age = now - (modelDeckCache.ts || 0);
  if (modelDeckCache.deck && age < MODEL_INFO_DECK_REFRESH_MS) return modelDeckCache.deck;
  const cached = cacheGet(ctx, CACHE_KEY_DECK);
  if (cached && typeof cached === "object") {
    modelDeckCache = { ts: now, deck: cached };
    return modelDeckCache.deck;
  }
  const res = await apiJson(ctx, "/v1/model_deck/deck").catch(() => null);
  const deck = res?.deck || null;
  if (deck && typeof deck === "object") {
    modelDeckCache = { ts: now, deck };
    cacheSet(ctx, CACHE_KEY_DECK, deck, CACHE_TTL_DECK_MS);
  }
  return modelDeckCache.deck;
}

function _embedCfg() {
  try {
    return typeof window !== "undefined" ? (window.__CHAT_JS_EMBED_CONFIG || {}) : {};
  } catch (_err) {
    return {};
  }
}

function _trimSlash(value) {
  return String(value || "").trim().replace(/\/+$/, "");
}

function _getClientMode() {
  try {
    const raw = String(window.localStorage.getItem(CLIENT_MODE_KEY) || "").trim().toLowerCase();
    if (!raw) return _isLocalBrowser() ? "local" : "docker";
    return raw === "local" ? "local" : "docker";
  } catch (_err) {
    return _isLocalBrowser() ? "local" : "docker";
  }
}

function _localClientServiceBase() {
  return `http://localhost:${LLAMA_MANAGER_PORT}`;
}

function _dockerClientServiceBase() {
  return `http://host.docker.internal:${LLAMA_MANAGER_PORT}`;
}

function _rewriteClientUrl(urlText, mode = _getClientMode()) {
  const raw = _trimSlash(urlText);
  if (!raw) return "";
  try {
    const url = new URL(raw);
    const host = String(url.hostname || "").trim().toLowerCase();
    if (mode === "local") {
      if (host === "host.docker.internal") url.hostname = "localhost";
      return _trimSlash(url.toString());
    }
    if (["localhost", "127.0.0.1", "::1"].includes(host)) url.hostname = "host.docker.internal";
    return _trimSlash(url.toString());
  } catch (_err) {
    return mode === "local"
      ? raw.replace(/host\.docker\.internal/gi, "localhost")
      : raw.replace(/\blocalhost\b|127\.0\.0\.1|::1/gi, "host.docker.internal");
  }
}

function _isFrontendServiceUrl(urlText) {
  const raw = _trimSlash(urlText);
  if (!raw) return false;
  try {
    const url = new URL(raw, window.location?.href || undefined);
    const port = String(url.port || (url.protocol === "https:" ? "443" : "80"));
    if (port === "8080") return true;
    if (typeof window !== "undefined" && window.location) {
      const sameHost = String(url.hostname || "").toLowerCase() === String(window.location.hostname || "").toLowerCase();
      const samePort = String(url.port || "") === String(window.location.port || "");
      if (sameHost && samePort) return true;
    }
  } catch (_err) {
    return /(^|:)8080\b/.test(raw);
  }
  return false;
}

function _isUsableLlamaManagerUrl(urlText) {
  const raw = _trimSlash(urlText);
  return Boolean(raw && !_isFrontendServiceUrl(raw));
}

function _isLikelyLlamaManagerUrl(urlText) {
  const raw = _trimSlash(urlText);
  if (!raw) return false;
  try {
    const u = new URL(raw, window.location?.href || undefined);
    const host = String(u.hostname || "").toLowerCase();
    const port = String(u.port || (u.protocol === "https:" ? "443" : "80"));
    if (port === LLAMA_MANAGER_PORT) return true;
    if (host.includes("llamahostservice")) return true;
    if (host.includes("llmserver")) return true;
    return false;
  } catch (_err) {
    return /(^|:)8767\b/.test(raw) || /llamahostservice/i.test(raw) || /llmserver/i.test(raw);
  }
}

function _isLocalBrowser() {
  if (typeof window === "undefined" || !window.location) return false;
  const host = String(window.location.hostname || "").trim().toLowerCase();
  return host === "localhost" || host === "127.0.0.1" || host === "::1";
}

function isWorkflowTrainingPluginEnabled(ctx) {
  const enabled = ctx?.state?.pluginPrefs?.enabled || {};
  return enabled.workflow_training !== false;
}

function workflowTrainingModelTokens(value) {
  const raw = String(value || "").trim().replace(/\\/g, "/").toLowerCase();
  if (!raw) return [];
  let base = raw.replace(/\/+$/, "").split("/").pop() || raw;
  base = base.replace(/^models--/i, "").replace(/--/g, "/");
  base = base.replace(/\.(gguf|safetensors|bin|json|pt)$/i, "");
  const tokens = base.match(/[a-z]+(?:\d+(?:\.\d+)*)?|\d+b/g) || [];
  const stop = new Set([
    "gguf", "instruct", "instruction", "chat", "model", "models", "transformers",
    "snapshot", "snapshots", "resolve", "blob", "main", "data", "adapter", "adapters",
  ]);
  return tokens.filter((token) => token && !stop.has(token));
}

function getVisibleLoaderIds(loaderIds, selectedLoaderId = "") {
  const selected = String(selectedLoaderId || "").trim();
  const rows = Array.isArray(loaderIds) ? loaderIds : [];
  return rows.filter((lid) => {
    const value = String(lid || "").trim();
    if (!value) return false;
    if (value === selected) return true;
    return !HIDDEN_EDITOR_LOADER_IDS.has(value);
  });
}

function workflowTrainingModelsCompatible(left, right) {
  const leftTokens = workflowTrainingModelTokens(left);
  const rightTokens = workflowTrainingModelTokens(right);
  if (!leftTokens.length || !rightTokens.length) return false;
  const rightSet = new Set(rightTokens);
  const shared = leftTokens.filter((token) => rightSet.has(token));
  if (shared.length >= 2) return true;
  const leftJoined = leftTokens.join("");
  const rightJoined = rightTokens.join("");
  return !!(leftJoined && rightJoined && (leftJoined.includes(rightJoined) || rightJoined.includes(leftJoined)));
}

async function _resolveRemoteClientServiceUrl(ctx) {
  const state = ctx?.getState?.() || {};
  const remote = state.remote || {};
  const existing = _trimSlash(remote.llamaManagerUrl || "");
  if (_isUsableLlamaManagerUrl(existing)) return existing;
  const fallbackClient = _trimSlash(remote.clientServiceUrl || "");
  if (_isUsableLlamaManagerUrl(fallbackClient) && _isLikelyLlamaManagerUrl(fallbackClient)) return fallbackClient;
  const cfg = _embedCfg();
  const identifierKey = String(cfg.identifierKey || cfg.identifier_key || "").trim();
  const cmsBase = _trimSlash(cfg.cmsBase || cfg.cms_base || "https://account.gotchat.ai");
  if (!identifierKey || !cmsBase) {
    try {
      const host = String(window.location.hostname || "").trim().toLowerCase();
      if (host.endsWith(".gotchat.ai") || host === "gotchat.ai") {
        return "https://llmserver.gotchat.ai";
      }
    } catch (_e0) {}
    return "";
  }
  const toStr = (v) => String(v == null ? "" : v).trim();
  const lower = (v) => toStr(v).toLowerCase();
  const asNum = (v) => {
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
  };
  const parseUpdated = (v) => {
    const t = Date.parse(toStr(v));
    return Number.isFinite(t) ? t : 0;
  };
  const looksLikeService = (svc, host, port) => {
    const s = lower(svc);
    const h = lower(host);
    const p = String(port || "");
    if (!s) return false;
    if (h && s.includes(`${h}:${p}`)) return true;
    if (h && s.includes(h) && p && s.includes(p)) return true;
    return false;
  };
  const pickBest = (arr, preferHostnameIncludes) => {
    const pref = String(preferHostnameIncludes || "").toLowerCase();
    const sorted = arr.slice().sort((a, b) => parseUpdated(b.updatedAt) - parseUpdated(a.updatedAt));
    if (pref) {
      const hit = sorted.find((m) => lower(m.hostname).includes(pref));
      if (hit) return hit;
    }
    return sorted[0] || null;
  };
  try {
    const hmUrl = `${cmsBase}/api/docker/host-mappings?key=${encodeURIComponent(identifierKey)}`;
    const hmResp = await fetch(hmUrl, { credentials: "omit", mode: "cors", cache: "no-cache" });
    if (hmResp.ok) {
      const hmPayload = (await hmResp.json()) || {};
      const items = Array.isArray(hmPayload.data || hmPayload.Data) ? (hmPayload.data || hmPayload.Data) : [];
      const clientSvcCandidates = items.filter((m) => {
        const lp = asNum(m.localPort);
        if (lp === 8767) return true;
        if (looksLikeService(m.service, "llama_hostservice", 8767)) return true;
        return false;
      });
      const bestClientSvc =
        pickBest(clientSvcCandidates.filter((m) => lower(m.hostname).includes("llmserver")), "llmserver") ||
        pickBest(clientSvcCandidates.filter((m) => lower(m.hostname).includes("llamahostservice")), "llamahostservice") ||
        pickBest(clientSvcCandidates.filter((m) => lower(m.hostname).includes("hostservice")), "hostservice") ||
        pickBest(clientSvcCandidates, "");
      const resolved = bestClientSvc ? _trimSlash(bestClientSvc.publicUrl || `https://${toStr(bestClientSvc.hostname)}`) : "";
      if (resolved && remote && typeof remote === "object") remote.llamaManagerUrl = resolved;
      if (resolved) return resolved;
    }
  } catch (_err) {}
  try {
    const url = `${cmsBase}/api/docker/public-urls?key=${encodeURIComponent(identifierKey)}`;
    const resp = await fetch(url, { credentials: "omit", mode: "cors", cache: "no-cache" });
    if (resp.ok) {
      const payload = (await resp.json()) || {};
      const data = payload.data || payload.Data || {};
      const candidate = _trimSlash(data.llamaManagerUrl || data.LlamaManagerUrl || "");
      const fallback = _trimSlash(data.clientServiceUrl || data.ClientServiceUrl || "");
      const resolved = candidate || (_isLikelyLlamaManagerUrl(fallback) ? fallback : "");
      if (resolved && remote && typeof remote === "object") remote.llamaManagerUrl = resolved;
      if (resolved) return resolved;
    }
  } catch (_err) {}
  try {
    const payload = await apiJson(ctx, "/v1/cloudflare_docker_https/status");
    const items = Array.isArray(payload?.mappings) ? payload.mappings : [];
    const lower = (v) => String(v || "").trim().toLowerCase();
    const candidates = items.filter((m) => {
      const lp = Number(m?.local_port || m?.localPort || 0);
      const svc = lower(m?.remote_service || m?.service || "");
      if (lp === 8767) return true;
      if (svc.includes("8767")) return true;
      return false;
    });
    const hinted =
      candidates.find((m) => lower(m?.hostname).includes("llmserver")) ||
      candidates.find((m) => lower(m?.hostname).includes("llamahostservice")) ||
      candidates.find((m) => lower(m?.hostname).includes("hostservice")) ||
      candidates[0];
    const resolved = hinted ? _trimSlash(hinted.public_url || hinted.publicUrl || (hinted.hostname ? `https://${hinted.hostname}` : "")) : "";
    if (resolved && remote && typeof remote === "object") remote.llamaManagerUrl = resolved;
    if (resolved) return resolved;
  } catch (_err) {}
  try {
    const host = String(window.location.hostname || "").trim().toLowerCase();
    if (host.endsWith(".gotchat.ai") || host === "gotchat.ai") {
      return "https://llmserver.gotchat.ai";
    }
  } catch (_e2) {}
  return "";
}

function clientServiceBase(ctx) {
  const mode = _getClientMode();
  const state = ctx?.getState?.() || {};
  const remote = state.remote || {};
  const llamaOverride = String(remote.llamaManagerUrl || "").trim().replace(/\/+$/, "");
  const clientFallback = String(remote.clientServiceUrl || "").trim().replace(/\/+$/, "");
  const rawOverride = llamaOverride || (_isLikelyLlamaManagerUrl(clientFallback) ? clientFallback : "");
  const override = _isUsableLlamaManagerUrl(rawOverride) ? _rewriteClientUrl(rawOverride) : "";
  if (override) return override;
  if (mode === "docker" && !_isLocalBrowser()) return "";
  return mode === "local" ? _localClientServiceBase() : _dockerClientServiceBase();
}

function _authTokenFromCtx(ctx) {
  return String(
    ctx?.state?.auth?.token ||
    ctx?.getState?.()?.auth?.token ||
    ""
  ).trim();
}

async function clientServiceJson(ctx, path, options = {}) {
  let base = clientServiceBase(ctx);
  try {
    if (!base) base = _rewriteClientUrl(await _resolveRemoteClientServiceUrl(ctx), "docker");
  } catch (_err) {}
  if (!base) throw new Error("Llama host service URL could not be resolved for the selected mode.");
  const method = options.method || "GET";
  const headers = { ...(options.headers || {}) };
  const token = _authTokenFromCtx(ctx);
  if (token) headers.Authorization = `Bearer ${token}`;
  try {
    const shared = String(window.localStorage.getItem(CLIENT_TOKEN_KEY) || "").trim();
    if (shared) headers["X-Client-Service-Token"] = shared;
  } catch (_err) {}
  const init = { method, headers };
  if (options.body) {
    init.body = JSON.stringify(options.body);
    init.headers = { ...headers, "Content-Type": "application/json" };
  }
  const url = `${base}${path}`;
  const res = await fetch(url, init);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${text.slice(0, 200)}`);
  }
  return res.json();
}

async function getManagedLlamaServers(ctx) {
  const cached = cacheGet(ctx, CACHE_KEY_MANAGED_SERVERS);
  if (Array.isArray(cached)) return cached;
  try {
    const provider = (ctx?.getSharedObjects?.({ pluginId: "llama_server_manager", type: "api_provider" }) || [])
      .find((item) => item && item.id === "llama_server_api" && typeof item.getStatus === "function");
    if (!provider) return [];
    const payload = await provider.getStatus();
    const servers = Array.isArray(payload?.servers) ? payload.servers : [];
    const filtered = servers.filter((item) => item && (item.llmloader_url || item.url));
    cacheSet(ctx, CACHE_KEY_MANAGED_SERVERS, filtered, CACHE_TTL_MANAGED_SERVERS_MS);
    return filtered;
  } catch (_err) {
    return [];
  }
}

function parseManagedDeviceChoices(lines) {
  const out = [];
  const seen = new Set();
  for (const raw of Array.isArray(lines) ? lines : []) {
    const text = String(raw || "").trim();
    const match = text.match(/^[A-Za-z]+(\d+):\s+(.*)$/);
    if (!match) continue;
    const value = String(match[1] || "").trim();
    if (!value || seen.has(value)) continue;
    seen.add(value);
    out.push({ value, label: text });
  }
  return out;
}

async function getManagedLlamaDeviceChoices(ctx, managedServers, managedId) {
  const server = (Array.isArray(managedServers) ? managedServers : []).find((item) => String(item?.id || "") === String(managedId || ""));
  if (!server) return [];
  const installId = String(server.install_id || "").trim();
  const runtimeId = String(server.runtime_id || "").trim().toLowerCase();
  if (!installId && !runtimeId) return [];
  const cacheKey = `${CACHE_KEY_MANAGED_DEVICE_PREFIX}${managedId || installId || runtimeId}`;
  const cached = cacheGet(ctx, cacheKey);
  if (Array.isArray(cached) && cached.length) return cached;
  try {
    const provider = (ctx?.getSharedObjects?.({ pluginId: "llama_server_manager", type: "api_provider" }) || [])
      .find((item) => item && item.id === "llama_server_api" && typeof item.getDevices === "function");
    if (!provider) return [];
    const payload = await provider.getDevices({ installId, runtimeId });
    const choices = parseManagedDeviceChoices(payload?.devices || payload?.lines || []);
    if (choices.length) cacheSet(ctx, cacheKey, choices, CACHE_TTL_MANAGED_DEVICE_MS);
    return choices;
  } catch (_err) {
    return [];
  }
}

function _ctxEffFromSettings(settings) {
  try {
    const nCtx = parseInt(settings?.n_ctx ?? settings?.nCtx ?? settings?.ctx ?? 0, 10) || 0;
    const yarnOrig = parseInt(settings?.yarn_orig_ctx ?? settings?.yarnOrigCtx ?? 0, 10) || 0;
    const eff = Math.min(...[nCtx, yarnOrig].filter((v) => v && v > 0));
    return { n_ctx: nCtx, yarn_orig_ctx: yarnOrig, ctx_limit_eff: eff || nCtx || yarnOrig || 0 };
  } catch (_err) {
    return { n_ctx: 0, yarn_orig_ctx: 0, ctx_limit_eff: 0 };
  }
}

async function refreshAndShareModelContext(host, ctx) {
  if (!host || !ctx) return;
  let proc = null;
  try {
    proc = await apiJson(ctx, "/v1/model_deck/processes");
  } catch (_err) {
    proc = null;
  }
  const main = proc?.main && typeof proc.main === "object" ? proc.main : null;
  if (!main) return;

  const typeId = String(main.type_id || "").trim() || "text_llm";
  const modelId = String(main.model_id || "").trim();
  const loaderId = String(main.loader_id || "").trim();

  const deck = await _getDeckCached(ctx);
  const hit = deck ? _findModelInDeck(deck, typeId, modelId) : null;
  const settings = hit?.settings || {};
  const limits = _ctxEffFromSettings(settings);

  const sig = `${typeId}::${modelId}::${loaderId}::${limits.n_ctx}::${limits.yarn_orig_ctx}`;
  if (sig === lastSharedModelSig && modelInfoTimer) return;
  lastSharedModelSig = sig;

  host.shareObject({
    id: "model_context",
    type: "data_provider",
    service: "model_context",
    ts: Date.now(),
    source: "model_deck",
    model_id: modelId,
    type_id: typeId,
    loader_id: loaderId,
    n_ctx: limits.n_ctx,
    yarn_orig_ctx: limits.yarn_orig_ctx,
    ctx_limit_eff: limits.ctx_limit_eff,
    rope_scaling_type: settings?.rope_scaling_type ?? settings?.ropeScalingType ?? "",
    rope_freq_base: settings?.rope_freq_base ?? settings?.ropeFreqBase ?? null,
    rope_freq_scale: settings?.rope_freq_scale ?? settings?.ropeFreqScale ?? null,
    yarn_ext_factor: settings?.yarn_ext_factor ?? null,
    yarn_attn_factor: settings?.yarn_attn_factor ?? null,
    yarn_beta_fast: settings?.yarn_beta_fast ?? null,
    yarn_beta_slow: settings?.yarn_beta_slow ?? null,
    // Include raw settings for advanced plugins (bounded by deck save format).
    settings: settings,
  });
}

function ensureModelInfoPolling(host, ctx) {
  if (!host || !ctx) return;
  if (modelInfoTimer) return;
  const tick = async () => {
    try {
      await refreshAndShareModelContext(host, ctx);
    } catch (_err) {}
  };
  void tick();
  modelInfoTimer = setInterval(tick, MODEL_INFO_POLL_MS);
}

function resolveOverlayMount(ctx) {
  try {
    const cfg = typeof window !== "undefined" ? (window.__CHAT_JS_EMBED_CONFIG || {}) : {};
    const raw = cfg.overlayMount || cfg.portal || cfg.overlay || null;
    if (raw instanceof Element) return raw;
    if (typeof raw === "string") {
      const el = document.querySelector(raw) || document.getElementById(String(raw).replace(/^#/, ""));
      if (el) return el;
    }
  } catch (_err) {
    // fall through
  }
  try {
    const directPortal = document.getElementById("llm-chat-js-portal");
    if (directPortal) return directPortal;
  } catch (_err) {
    // fall through
  }
  try {
    if (ctx && typeof ctx.getOverlayMount === "function") {
      const mount = ctx.getOverlayMount();
      if (mount instanceof Element) return mount;
    }
  } catch (_err) {
    // fall through
  }
  return document.body;
}

function moveNodeIntoChatPortal(node) {
  if (!node) return null;
  try {
    const portal = document.getElementById("llm-chat-js-portal");
    if (portal && node.parentElement !== portal) {
      portal.appendChild(node);
    }
    return portal || null;
  } catch (_err) {
    return null;
  }
}

function ensureStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
.model-deck-root {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
.model-deck-header { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; flex: 0 0 auto; }
.model-deck-root .plugin-repo-tabs { flex: 0 0 auto; }
.model-deck-root .plugin-repo-panel {
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  -webkit-overflow-scrolling: touch;
  padding-bottom: 16px;
}
.md-list { display: flex; flex-direction: column; gap: 6px; }
.md-row { display: grid; gap: 8px; align-items: center; padding: 8px 10px; border-radius: 10px; border: 1px solid rgba(var(--ink-rgb), 0.08); background: rgba(var(--panel-rgb), 0.65); }
.md-row-header { font-size: 12px; text-transform: uppercase; letter-spacing: 1.2px; color: var(--ui-muted); }
.md-cell { font-size: 13px; color: var(--ui-ink); overflow-wrap: anywhere; }
.md-cell.muted { color: var(--ui-muted); }
.md-scroll { display: flex; flex-direction: column; gap: 6px; max-width: 100%; }
.md-scroll-viewport { overflow-x: auto; max-width: 100%; scrollbar-width: none; -ms-overflow-style: none; }
.md-scroll-viewport::-webkit-scrollbar { height: 0; }
.md-scroll-viewport .md-row { min-width: 980px; }
.md-scrollbar { position: sticky; bottom: 0; height: 12px; overflow-x: auto; overflow-y: hidden; background: rgba(var(--panel-rgb), 0.85); border-top: 1px solid rgba(var(--ink-rgb), 0.08); }
.md-scrollbar-inner { height: 1px; }
.md-actions { display: flex; gap: 6px; flex-wrap: wrap; }
.md-action-select { min-width: 140px; }
.md-inline { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.md-muted { color: var(--ui-muted); }
.md-card { border: 1px solid var(--line); border-radius: 12px; padding: 12px; background: var(--panel); }
.md-split { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
.md-mobile-label { display: none; }
.md-auto-field {
  display: flex;
  flex-wrap: nowrap;
  gap: 8px;
  align-items: center;
  width: 100%;
  min-width: 0;
}
.md-auto-field .plugin-search-input,
.md-auto-field input {
  display: block;
  width: 100% !important;
  min-width: 0;
  box-sizing: border-box;
  max-width: 100%;
}
.md-auto-field .plugin-search-input {
  flex: 0 0 156px;
}
.md-auto-field input {
  flex: 1 1 180px;
}
@media (max-width: 720px) {
  .model-deck-root .plugin-repo-panel {
    padding-bottom: 72px;
  }
  .md-list {
    gap: 10px;
  }
  .md-scroll-viewport {
    overflow-x: visible;
    padding: 2px 2px 6px;
  }
  .md-scrollbar {
    display: none;
  }
  .md-scroll-viewport .md-row {
    min-width: 0;
  }
  .md-row-header {
    display: none;
  }
  .md-row.md-overview-row,
  .md-row.md-model-row,
  .md-row.md-process-row {
    grid-template-columns: minmax(0, 1fr) auto !important;
    gap: 6px 10px;
    align-items: start;
    padding: 12px;
    border-radius: 12px;
    border: 1px solid var(--border);
    background: transparent;
    box-shadow: none;
  }
  .md-row.md-overview-row {
    grid-template-areas:
      "title count"
      "label label"
      "default default"
      "main main"
      "actions actions";
  }
  .md-row.md-model-row {
    grid-template-columns: minmax(0, 1fr) !important;
    grid-template-areas:
      "title"
      "loader"
      "flags"
      "actions";
  }
  .md-row.md-process-row {
    grid-template-columns: minmax(0, 1fr) !important;
    grid-template-areas:
      "title"
      "model"
      "details"
      "status"
      "mem"
      "actions";
  }
  .md-cell {
    min-width: 0;
  }
  .md-cell[data-mobile-hide="true"] {
    display: none;
  }
  .md-mobile-label {
    display: inline;
    color: var(--ui-muted);
    margin-right: 6px;
  }
  .md-overview-type { grid-area: title; font-weight: 700; }
  .md-overview-count { grid-area: count; justify-self: end; }
  .md-overview-label { grid-area: label; }
  .md-overview-default { grid-area: default; }
  .md-overview-main { grid-area: main; }
  .md-overview-actions { grid-area: actions; }
  .md-model-id { grid-area: title; font-weight: 700; }
  .md-model-loader { grid-area: loader; }
  .md-model-flags { grid-area: flags; }
  .md-model-actions { grid-area: actions; }
  .md-process-name { grid-area: title; font-weight: 700; }
  .md-process-model { grid-area: model; }
  .md-process-details { grid-area: details; }
  .md-process-status { grid-area: status; }
  .md-process-mem { grid-area: mem; }
  .md-process-actions { grid-area: actions; }
  .md-link-btn.md-overview-count-btn {
    color: var(--accent) !important;
    font-weight: 700;
    text-align: right;
  }
  .md-inline-pairs {
    display: flex;
    flex-wrap: wrap;
    gap: 8px 10px;
  }
  .md-inline-pair {
    display: flex;
    align-items: baseline;
    gap: 4px;
    min-width: 0;
    flex-wrap: wrap;
  }
  .md-inline-pair-label {
    color: var(--ui-muted);
  }
  .md-value-yes {
    color: var(--accent);
    font-weight: 700;
  }
  .md-value-no {
    color: var(--ui-muted);
  }
  .md-status-loaded,
  .md-status-running,
  .md-status-server-running {
    color: #3fb950;
    font-weight: 700;
  }
  .md-status-stopped {
    color: #f85149;
    font-weight: 700;
  }
  .md-overview-actions .plugin-search-input,
  .md-model-actions .plugin-search-input,
  .md-process-actions .ghost,
  .md-process-actions .plugin-search-input,
  .md-actions,
  .md-actions > * {
    width: 100%;
    max-width: 100%;
  }
  .md-auto-field {
    flex-wrap: wrap;
  }
  .md-auto-field .plugin-search-input,
  .md-auto-field input {
    flex: 1 1 100%;
  }
}
.md-deck-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 10px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--ui-ink);
  cursor: pointer;
  transition: border-color 0.2s ease, background 0.2s ease;
}
.md-deck-btn:hover {
  border-color: var(--border);
  background: var(--ui-popover-item-bg);
}
.md-deck-badge {
  position: absolute;
  top: -4px;
  right: -4px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 999px;
  background: #16a34a;
  color: #ecfdf5;
  font-size: 10px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.md-deck-popover {
  position: fixed;
  min-width: 260px;
  max-width: 340px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: var(--shadow);
  padding: 12px;
  z-index: 40;
  pointer-events: auto;
  color: var(--ui-ink);
}
.md-deck-popover h4 {
  margin: 0 0 8px;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 1.2px;
  color: var(--ui-muted);
}
.md-link-btn {
  appearance: none;
  background: none;
  border: 0;
  padding: 0;
  margin: 0;
  color: inherit;
  font: inherit;
  cursor: pointer;
  text-align: left;
}
.md-link-btn:hover { text-decoration: underline; }
.md-link-btn:focus-visible { outline: 2px solid rgba(var(--ink-rgb), 0.25); outline-offset: 2px; border-radius: 6px; }
.md-deck-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 280px;
  overflow: auto;
  padding-right: 4px;
}
.md-deck-item {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 8px;
  background: var(--ui-popover-item-bg);
  color: var(--ui-ink);
}
.md-deck-item.running {
  border: 1px solid rgba(22, 163, 74, 0.6);
  box-shadow: 0 0 0 1px rgba(22, 163, 74, 0.12);
}
.md-deck-item-title {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
}
.md-deck-item-meta {
  margin-top: 4px;
  font-size: 11px;
  color: var(--ui-muted);
  display: flex;
  justify-content: space-between;
  gap: 8px;
}
.md-deck-item-actions {
  margin-top: 8px;
  display: flex;
  justify-content: flex-end;
}
.md-deck-action {
  font-size: 11px;
  padding: 4px 8px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--ui-control-bg);
  color: var(--ui-ink);
  cursor: pointer;
  position: relative;
}
.md-deck-action.pending {
  opacity: 0.7;
  cursor: not-allowed;
}
.md-deck-action.pending::after {
  content: "";
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 2px solid currentColor;
  border-top-color: transparent;
  display: inline-block;
  margin-left: 6px;
  animation: md-deck-spin 0.8s linear infinite;
}
@keyframes md-deck-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.md-deck-muted {
  font-size: 12px;
  color: var(--muted);
}
  `;
  document.head.appendChild(style);
}

function fmtBytes(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let idx = 0;
  let next = n;
  while (next >= 1024 && idx < units.length - 1) {
    next /= 1024;
    idx += 1;
  }
  return `${next.toFixed(2)} ${units[idx]}`;
}

function hasBytes(value) {
  return Number.isFinite(Number(value)) && Number(value) >= 0;
}

function buildPluginHeaders(ctx) {
  const headers = { "X-Gui-Enabled-Plugins": "collab_chat,model_deck" };
  const token = ctx?.state?.auth?.token;
  if (token) headers.Authorization = `Bearer ${token}`;
  const alias = ctx?.state?.auth?.alias;
  if (alias) headers["X-User-Alias"] = alias;
  const pid = ctx?.state?.ui?.activePid;
  const sid = ctx?.state?.ui?.activeSid;
  if (pid) headers["X-Project-Id"] = pid;
  if (sid) headers["X-Session-Id"] = sid;
  return headers;
}

function apiJson(ctx, path, options = {}) {
  const headers = { ...buildPluginHeaders(ctx), ...(options.headers || {}) };
  return ctx.apiJson(path, { ...options, headers });
}

function formatStatus(entry) {
  if (!entry) return "";
  if (entry.kind === "worker") return entry.alive ? "running" : "stopped";
  return entry.loaded ? "loaded" : "stopped";
}

function isRunning(entry) {
  if (!entry) return false;
  if (entry.kind === "worker") return Boolean(entry.alive);
  return Boolean(entry.loaded);
}

function normalizeModelId(value) {
  return String(value || "").trim().replace(/\\/g, "/");
}

function sameModelId(left, right) {
  const a = normalizeModelId(left);
  const b = normalizeModelId(right);
  return Boolean(a) && Boolean(b) && a === b;
}

function deckEntryKey(entry) {
  if (!entry) return "";
  if (entry.kind === "worker") return `worker:${entry.worker_id || ""}`;
  return `${entry.kind || "model"}:${entry.type_id || ""}`;
}

function buildProcessEntries(processes) {
  const data = processes || {};
  const out = [];
  const main = data.main || null;
  const defaults = Array.isArray(data.defaults) ? data.defaults : [];
  const workers = Array.isArray(data.workers) ? data.workers : [];
  if (main && typeof main === "object") {
    out.push({
      kind: "main",
      name: main.label || "Main text LLM",
      type_id: main.type_id || "text_llm",
      model_id: main.model_id || "",
      persist: Boolean(main.persist),
      supports_load: Boolean(main.supports_load),
      loaded: Boolean(main.loaded),
    });
  }
  defaults.forEach((entry) => {
    if (!entry || typeof entry !== "object") return;
    out.push({
      kind: "default",
      name: `Default: ${entry.label || entry.type_id || ""}`,
      type_id: entry.type_id || "",
      model_id: entry.model_id || "",
      persist: Boolean(entry.persist),
      supports_load: Boolean(entry.supports_load),
      loaded: Boolean(entry.loaded),
    });
  });
  workers.forEach((entry) => {
    if (!entry || typeof entry !== "object") return;
    const meta = entry.meta || {};
    out.push({
      kind: "worker",
      name: `Worker: ${meta.model_type || meta.slot || "vlm"}`,
      type_id: meta.model_type || "",
      model_id: meta.model_id || "",
      persist: Boolean(meta.persist),
      alive: Boolean(entry.alive),
      worker_id: entry.worker_id,
    });
  });
  return out;
}

function formatModelId(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  const normalized = raw.replace(/\\/g, "/");
  const parts = normalized.split("/");
  const last = parts[parts.length - 1] || "";
  return last || raw;
}

function countRunning(entries) {
  return entries.filter((entry) => isRunning(entry)).length;
}

function updateDeckBadge(count) {
  if (!deckBadge) return;
  if (!count) {
    deckBadge.textContent = "";
    deckBadge.style.display = "none";
    return;
  }
  deckBadge.textContent = String(count);
  deckBadge.style.display = "inline-flex";
}

function positionDeckPopover() {
  if (!deckPopover || !deckButton) return;
  const rect = deckButton.getBoundingClientRect();
  const width = deckPopover.offsetWidth || 300;
  const left = Math.min(
    Math.max(12, rect.right - width),
    Math.max(12, window.innerWidth - width - 12)
  );
  const top = Math.min(
    Math.max(12, rect.bottom + 8),
    Math.max(12, window.innerHeight - (deckPopover.offsetHeight || 220) - 12)
  );
  deckPopover.style.left = `${left}px`;
  deckPopover.style.top = `${top}px`;
  deckPopover.style.right = "auto";
}

async function refreshDeckProcesses(ctx, { render } = {}) {
  try {
    const proc = await apiJson(ctx, "/v1/model_deck/processes?include_managed=0");
    deckState.processes = stabilizeManagedProcessSnapshot(deckState.processes, proc || {});
    cacheSet(ctx, CACHE_KEY_POPOVER_PROCESSES, deckState.processes, CACHE_TTL_POPOVER_MS);
  } catch (_err) {
    deckState.processes = {};
  }
  // Share current model context for other plugins (e.g. Page JSON Retriever token budgeting).
  try {
    if (deckState.host) {
      await refreshAndShareModelContext(deckState.host, ctx);
    }
  } catch (_err) {}
  const entries = buildProcessEntries(deckState.processes);
  entries.forEach((entry) => {
    const key = deckEntryKey(entry);
    const pending = deckPending.get(key);
    if (!pending) return;
    if (pending === "start" && isRunning(entry)) deckPending.delete(key);
    if (pending === "stop" && !isRunning(entry)) deckPending.delete(key);
  });
  updateDeckBadge(countRunning(entries));
  if (render) renderDeckPopover(ctx);
  void (async () => {
    try {
      const managed = await apiJson(ctx, "/v1/model_deck/processes");
      deckState.processes = mergeManagedProcessSnapshot(deckState.processes, managed || {});
      cacheSet(ctx, CACHE_KEY_POPOVER_PROCESSES, deckState.processes, CACHE_TTL_POPOVER_MS);
      updateDeckBadge(countRunning(buildProcessEntries(deckState.processes)));
      if (render) renderDeckPopover(ctx);
    } catch (_err) {}
  })();
}

function applyCachedDeckProcesses(ctx) {
  const cached = cacheGet(ctx, CACHE_KEY_POPOVER_PROCESSES);
  if (!cached || typeof cached !== "object") return false;
  deckState.processes = cached;
  updateDeckBadge(countRunning(buildProcessEntries(deckState.processes)));
  return true;
}

function startDeckPolling(ctx) {
  if (deckTimer) return;
  deckTimer = setInterval(() => {
    const isAdmin = (ctx?.state?.auth?.role || "") === "admin";
    if (!isAdmin) {
      closeDeckPopover();
      stopDeckPolling();
      if (deckButton && deckButton.remove) deckButton.remove();
      deckButton = null;
      deckBadge = null;
      return;
    }
    void refreshDeckProcesses(ctx, { render: deckOpen });
  }, DECK_POLL_MS);
}

function stopDeckPolling() {
  if (deckTimer) {
    clearInterval(deckTimer);
    deckTimer = null;
  }
}

async function toggleDeckProcess(ctx, entry) {
  if (!entry) return;
  if (entry.kind === "worker") {
    await apiJson(ctx, "/v1/model_deck/processes/stop", {
      method: "POST",
      body: { kind: "worker", worker_id: entry.worker_id },
    });
    return;
  }
  const target = entry.loaded ? "/v1/model_deck/processes/stop" : "/v1/model_deck/processes/start";
  await apiJson(ctx, target, { method: "POST", body: { kind: entry.kind, type_id: entry.type_id } });
}

function renderDeckPopover(ctx) {
  if (!deckPopover) return;
  const prevList = deckPopover.querySelector(".md-deck-list");
  const prevScrollTop = prevList ? prevList.scrollTop : 0;
  deckPopover.innerHTML = "";
  const title = document.createElement("h4");
  const titleBtn = document.createElement("button");
  titleBtn.type = "button";
  titleBtn.className = "md-link-btn";
  titleBtn.textContent = "Model Deck";
  titleBtn.title = "Open Model Deck";
  titleBtn.addEventListener("click", (event) => {
    event.stopPropagation();
    deckNavRequest = { action: "open" };
    closeDeckPopover();
    if (ctx?.openPluginPanel) ctx.openPluginPanel(meta.plugin_id, { openModal: true });
  });
  title.appendChild(titleBtn);
  deckPopover.appendChild(title);

  const entries = buildProcessEntries(deckState.processes);
  if (!entries.length) {
    const empty = document.createElement("div");
    empty.className = "md-deck-muted";
    empty.textContent = "No models loaded.";
    deckPopover.appendChild(empty);
    return;
  }

  const list = document.createElement("div");
  list.className = "md-deck-list";
  entries.forEach((entry) => {
    const card = document.createElement("div");
    card.className = "md-deck-item";
    if (isRunning(entry)) card.classList.add("running");
    const titleRow = document.createElement("div");
    titleRow.className = "md-deck-item-title";
    const name = document.createElement("button");
    name.type = "button";
    name.className = "md-link-btn";
    name.textContent = entry.name || entry.type_id || "Model";
    name.title = "Edit in Model Deck";
    name.addEventListener("click", (event) => {
      event.stopPropagation();
      deckNavRequest = {
        action: "edit-model",
        typeId: String(entry.type_id || "").trim(),
        modelId: String(entry.model_id || "").trim(),
      };
      closeDeckPopover();
      if (ctx?.openPluginPanel) ctx.openPluginPanel(meta.plugin_id, { openModal: true });
    });
    const status = document.createElement("div");
    status.textContent = formatStatus(entry);
    titleRow.appendChild(name);
    titleRow.appendChild(status);
    card.appendChild(titleRow);

    const metaRow = document.createElement("div");
    metaRow.className = "md-deck-item-meta";
    const type = document.createElement("div");
    type.textContent = entry.type_id || "";
    const model = document.createElement("div");
    model.textContent = formatModelId(entry.model_id || "");
    metaRow.appendChild(type);
    metaRow.appendChild(model);
    card.appendChild(metaRow);

    const actions = document.createElement("div");
    actions.className = "md-deck-item-actions";
    const canToggle = entry.kind === "worker" || (entry.supports_load && entry.persist);
    if (canToggle) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "md-deck-action";
      const entryKey = deckEntryKey(entry);
      const pendingAction = deckPending.get(entryKey);
      const running = isRunning(entry);
      btn.textContent = running ? "Stop" : "Play";
      if (pendingAction) {
        btn.disabled = true;
        btn.classList.add("pending");
        btn.textContent = pendingAction === "start" ? "Loading" : "Stopping";
      }
      btn.addEventListener("click", async (event) => {
        event.stopPropagation();
        const action = isRunning(entry) ? "stop" : "start";
        deckPending.set(entryKey, action);
        btn.disabled = true;
        btn.classList.add("pending");
        try {
          await toggleDeckProcess(ctx, entry);
          if (action === "stop") deckPending.delete(entryKey);
          await refreshDeckProcesses(ctx, { render: true });
        } catch (_err) {
          deckPending.delete(entryKey);
          btn.disabled = false;
          btn.classList.remove("pending");
        }
      });
      actions.appendChild(btn);
    }
    card.appendChild(actions);
    list.appendChild(card);
  });
  deckPopover.appendChild(list);
  if (prevScrollTop && list.scrollHeight > list.clientHeight) {
    list.scrollTop = prevScrollTop;
  }
  requestAnimationFrame(positionDeckPopover);
}

function closeDeckPopover() {
  if (!deckPopover) return;
  deckPopover.remove();
  deckPopover = null;
  deckOpen = false;
}

function buildDeckButton(ctx) {
  ensureStyles();
  const isAdmin = (ctx?.state?.auth?.role || "") === "admin";
  // `renderTopRightIconRow()` caches nodes, so keep a stable node for admins
  // and hard-remove for non-admins to avoid leaking the icon across sessions.
  if (!isAdmin) {
    closeDeckPopover();
    stopDeckPolling();
    if (deckButton && deckButton.remove) deckButton.remove();
    deckButton = null;
    deckBadge = null;
    return null;
  }
  if (deckButton) return deckButton;
  deckButton = document.createElement("button");
  deckButton.type = "button";
  deckButton.className = "md-deck-btn";
  deckButton.title = "Model Deck";
  deckButton.innerHTML = `
<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
  <rect x="3" y="4" width="8" height="8" rx="2"></rect>
  <rect x="13" y="4" width="8" height="8" rx="2"></rect>
  <rect x="3" y="12" width="8" height="8" rx="2"></rect>
  <rect x="13" y="12" width="8" height="8" rx="2"></rect>
</svg>
  `;
  deckBadge = document.createElement("span");
  deckBadge.className = "md-deck-badge";
  deckBadge.style.display = "none";
  deckButton.appendChild(deckBadge);

  deckButton.addEventListener("click", async (event) => {
    event.stopPropagation();
    if (deckOpen) {
      closeDeckPopover();
      return;
    }
    deckOpen = true;
    deckPopover = document.createElement("div");
    deckPopover.className = "md-deck-popover";
    const mount = (ctx && typeof ctx.getOverlayMount === "function" && ctx.getOverlayMount()) || document.body;
    mount.appendChild(deckPopover);
    requestAnimationFrame(positionDeckPopover);
    if (applyCachedDeckProcesses(ctx)) {
      renderDeckPopover(ctx);
    }
    void refreshDeckProcesses(ctx, { render: true });
  });

  startDeckPolling(ctx);
  applyCachedDeckProcesses(ctx);
  void refreshDeckProcesses(ctx, { render: false });
  return deckButton;
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function wrapStickyScroll(list) {
  const wrap = document.createElement("div");
  wrap.className = "md-scroll";
  const viewport = document.createElement("div");
  viewport.className = "md-scroll-viewport";
  viewport.appendChild(list);
  wrap.appendChild(viewport);

  const bar = document.createElement("div");
  bar.className = "md-scrollbar";
  const inner = document.createElement("div");
  inner.className = "md-scrollbar-inner";
  bar.appendChild(inner);
  wrap.appendChild(bar);

  let syncing = false;
  const sync = (source, target) => {
    if (syncing) return;
    syncing = true;
    target.scrollLeft = source.scrollLeft;
    syncing = false;
  };
  viewport.addEventListener("scroll", () => sync(viewport, bar));
  bar.addEventListener("scroll", () => sync(bar, viewport));

  const updateWidth = () => {
    inner.style.width = `${list.scrollWidth}px`;
  };
  updateWidth();
  if (typeof ResizeObserver !== "undefined") {
    const ro = new ResizeObserver(updateWidth);
    ro.observe(list);
    ro.observe(viewport);
    wrap._ro = ro;
  } else {
    window.addEventListener("resize", updateWidth);
  }

  return wrap;
}

function sortTypes(types) {
  const entries = Object.entries(types || {});
  return entries.sort(([a], [b]) => {
    const ai = DEFAULT_TYPE_ORDER.indexOf(a);
    const bi = DEFAULT_TYPE_ORDER.indexOf(b);
    if (ai !== -1 || bi !== -1) {
      return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
    }
    return a.localeCompare(b);
  });
}

function renderPanel(container, ctx) {
  ensureStyles();
  container.innerHTML = "";
  if (!ctx?.state?.auth?.token) {
    const note = document.createElement("div");
    note.className = "md-muted";
    note.textContent = "Please log in.";
    container.appendChild(note);
    return;
  }
  if ((ctx?.state?.auth?.role || "") !== "admin") {
    const note = document.createElement("div");
    note.className = "md-muted";
    note.textContent = "Admin only.";
    container.appendChild(note);
    return;
  }

  const state = {
    templates: {},
    schemas: {},
    deck: {},
    loaderIds: [],
    processes: {},
    processActionPending: {},
    activeTab: "overview",
    activeTypeId: "",
  };

  const root = document.createElement("div");
  root.className = "model-deck-root";
  container.appendChild(root);

  const header = document.createElement("div");
  header.className = "model-deck-header";
  const title = document.createElement("div");
  title.textContent = "Model Deck";
  title.style.fontWeight = "600";
  const statusLabel = document.createElement("div");
  statusLabel.className = "md-muted";
  const refreshBtn = document.createElement("button");
  refreshBtn.className = "ghost";
  refreshBtn.textContent = "Refresh";
  refreshBtn.addEventListener("click", () => void reloadAll());
  const hfBtn = document.createElement("button");
  hfBtn.className = "ghost";
  hfBtn.textContent = "Hugging Face login...";
  hfBtn.addEventListener("click", () => void promptHfLogin());
  header.appendChild(title);
  header.appendChild(statusLabel);
  header.appendChild(refreshBtn);
  header.appendChild(hfBtn);
  root.appendChild(header);

  const tabs = document.createElement("div");
  tabs.className = "plugin-repo-tabs";
  root.appendChild(tabs);

  const tabSections = {
    overview: document.createElement("div"),
    models: document.createElement("div"),
    processes: document.createElement("div"),
  };
  Object.values(tabSections).forEach((sec) => {
    sec.className = "plugin-repo-panel";
    root.appendChild(sec);
  });

  const tabButtons = {};
  [
    ["overview", "Overview"],
    ["models", "Add / Edit Models"],
    ["processes", "Processes"],
  ].forEach(([id, label]) => {
    const btn = document.createElement("button");
    btn.className = "plugin-repo-tab";
    btn.textContent = label;
    btn.addEventListener("click", () => setActiveTab(id));
    tabs.appendChild(btn);
    tabButtons[id] = btn;
  });

  function setActiveTab(tabId) {
    state.activeTab = tabId;
    for (const [id, btn] of Object.entries(tabButtons)) {
      btn.classList.toggle("active", id === tabId);
      tabSections[id].classList.toggle("active", id === tabId);
    }
  }

  function renderOverview() {
    const target = tabSections.overview;
    target.innerHTML = "";
    const deck = state.deck || {};
    const types = deck.types || {};

    const list = document.createElement("div");
    list.className = "md-list";
    const template = "160px 1.4fr 1.6fr 1.6fr 100px 160px";
    list.appendChild(buildRow(template, ["Type ID", "Label", "Default model", "Main model", "# Models", "Actions"], true, {
      rowClass: "md-overview-row",
      cellClasses: ["md-overview-type", "md-overview-label", "md-overview-default", "md-overview-main", "md-overview-count", "md-overview-actions"],
    }));
    for (const [tid, t] of sortTypes(types)) {
      if (HIDDEN_OVERVIEW_TYPE_IDS.has(String(tid || "").trim())) continue;
      const models = Array.isArray(t.models) ? t.models : [];
      const main = tid === "text_llm" ? (t.main_model_id || "") : "";
      const isDefault = DEFAULT_TYPE_ORDER.includes(tid);
      const countBtn = document.createElement("button");
      countBtn.type = "button";
      countBtn.className = "md-link-btn md-overview-count-btn";
      countBtn.textContent = String(models.length);
      countBtn.title = "Edit this model type";
      countBtn.addEventListener("click", () => {
        state.activeTypeId = tid;
        setActiveTab("models");
        renderModels();
      });
      const actions = createActionSelect([
        {
          value: "edit",
          label: "Edit",
          onSelect: () => {
            state.activeTypeId = tid;
            setActiveTab("models");
            renderModels();
          },
        },
        {
          value: "delete",
          label: "Delete",
          disabled: isDefault,
          onSelect: () => void deleteType(tid),
        },
      ]);
      const row = buildRow(
        template,
        [
          tid,
          { mobileLabel: "Info:", text: t.label || tid },
          { mobileLabel: "Default Model:", text: t.default_model_id || "" },
          { mobileLabel: "Main Model:", text: main || "" },
          countBtn,
          actions,
        ],
        false,
        {
          rowClass: "md-overview-row",
          cellClasses: ["md-overview-type", "md-overview-label", "md-overview-default", "md-overview-main", "md-overview-count", "md-overview-actions"],
        }
      );
      list.appendChild(row);
    }
    const listWrap = wrapStickyScroll(list);
    target.appendChild(listWrap);
  }

  function getProcessActionKey(kind, typeId, workerId) {
    if (kind === "worker") return `worker:${workerId || ""}`;
    if (kind === "default") return `default:${typeId || ""}`;
    return `main:${typeId || "main"}`;
  }

  function createInlinePairs(items) {
    const wrap = document.createElement("div");
    wrap.className = "md-inline-pairs";
    for (const item of items || []) {
      if (!item || !item.label) continue;
      const pair = document.createElement("div");
      pair.className = "md-inline-pair";
      const label = document.createElement("span");
      label.className = "md-inline-pair-label";
      label.textContent = `${item.label}`;
      const value = document.createElement("span");
      const rawValue = String(item.value ?? "").trim();
      const lowValue = rawValue.toLowerCase();
      value.textContent = rawValue;
      if (lowValue === "yes") value.className = "md-value-yes";
      else if (lowValue === "no") value.className = "md-value-no";
      else if (["loaded", "running", "server running"].includes(lowValue)) value.className = `md-status-${lowValue.replace(/\s+/g, "-")}`;
      else if (lowValue === "stopped") value.className = "md-status-stopped";
      pair.appendChild(label);
      pair.appendChild(value);
      wrap.appendChild(pair);
    }
    return wrap;
  }

  function setProcessActionPending(key, pending) {
    if (!key) return;
    if (pending) state.processActionPending[key] = true;
    else delete state.processActionPending[key];
    if (state.activeTab === "processes") renderProcesses();
  }

  function buildProcessActionButton(label, key) {
    const btn = document.createElement("button");
    btn.className = "ghost";
    btn.textContent = label;
    if (key && state.processActionPending[key]) {
      btn.classList.add("btn-loading");
      btn.disabled = true;
      const spinner = document.createElement("span");
      spinner.className = "btn-spinner";
      btn.appendChild(spinner);
    }
    return btn;
  }

  function renderModels() {
    const target = tabSections.models;
    target.innerHTML = "";

    const deck = state.deck || {};
    const types = deck.types || {};
    const typeEntries = sortTypes(types);

    const typeRow = document.createElement("div");
    typeRow.className = "md-inline";
    const typeLabel = document.createElement("span");
    typeLabel.textContent = "Type:";
    const typeSelect = document.createElement("select");
    typeSelect.className = "plugin-search-input";
    typeEntries.forEach(([tid, t]) => {
      const opt = document.createElement("option");
      opt.value = tid;
      opt.textContent = t.label || tid;
      typeSelect.appendChild(opt);
    });
    if (!state.activeTypeId && typeEntries.length) {
      state.activeTypeId = typeEntries[0][0];
    }
    typeSelect.value = state.activeTypeId || "";
    typeSelect.addEventListener("change", () => {
      state.activeTypeId = typeSelect.value;
      renderModels();
    });
    typeRow.appendChild(typeLabel);
    typeRow.appendChild(typeSelect);

    const templateSelect = document.createElement("select");
    templateSelect.className = "plugin-search-input";
    templateSelect.appendChild(new Option("Custom...", "__custom__"));
    for (const tid of DEFAULT_TYPE_ORDER) {
      if (state.templates[tid]) {
        templateSelect.appendChild(new Option(state.templates[tid].label || tid, tid));
      }
    }
    for (const [tid, meta] of Object.entries(state.templates || {})) {
      if (DEFAULT_TYPE_ORDER.includes(tid)) continue;
      templateSelect.appendChild(new Option(meta.label || tid, tid));
    }
    const addTypeBtn = document.createElement("button");
    addTypeBtn.className = "ghost";
    addTypeBtn.textContent = "Add type";
    addTypeBtn.addEventListener("click", () => void addTypeFromTemplate(templateSelect.value));

    typeRow.appendChild(document.createElement("span")).textContent = "Add from:";
    typeRow.appendChild(templateSelect);
    typeRow.appendChild(addTypeBtn);
    target.appendChild(typeRow);

    const t = types[state.activeTypeId];
    if (!t) {
      const empty = document.createElement("div");
      empty.className = "md-muted";
      empty.textContent = "No model type selected.";
      target.appendChild(empty);
      return;
    }

    if (TYPE_META_ENABLED) {
      const metaCard = document.createElement("div");
      metaCard.className = "md-card";
      const metaGrid = document.createElement("div");
      metaGrid.className = "md-split";
      const labelField = createTextField("Label", t.label || state.activeTypeId);
      const notesField = createTextArea("Notes", t.notes || "");
      metaGrid.appendChild(labelField.wrap);
      metaGrid.appendChild(notesField.wrap);
      metaCard.appendChild(metaGrid);
      const saveMetaBtn = document.createElement("button");
      saveMetaBtn.className = "ghost";
      saveMetaBtn.textContent = "Save type meta";
      saveMetaBtn.addEventListener("click", () => void saveTypeMeta(state.activeTypeId, labelField.input.value, notesField.input.value));
      metaCard.appendChild(saveMetaBtn);
      target.appendChild(metaCard);
    }

    const models = Array.isArray(t.models) ? t.models : [];
    const list = document.createElement("div");
    list.className = "md-list";
    const template = "2.2fr 1.6fr 80px 80px 70px 80px 160px";
    list.appendChild(buildRow(template, ["Model ID", "Loader", "Default", "Main", "Lazy", "Persist", "Actions"], true, {
      rowClass: "md-model-row",
      cellClasses: ["md-model-id", "md-model-loader", "md-model-default", "md-model-main", "md-model-lazy", "md-model-persist", "md-model-actions"],
    }));
    for (const model of models) {
      if (!model || typeof model !== "object") continue;
      const mid = String(model.model_id || "");
      const loaderId = String(model.loader_id || "");
      const isDefault = sameModelId(mid, t.default_model_id || "");
      const isMain = state.activeTypeId === "text_llm" && sameModelId(mid, t.main_model_id || "");
      const midBtn = document.createElement("button");
      midBtn.type = "button";
      midBtn.className = "md-link-btn";
      midBtn.textContent = mid;
      midBtn.title = "Edit model";
      midBtn.addEventListener("click", () => void openModelEditor(state.activeTypeId, model));
      const actions = [
        {
          value: "set-default",
          label: "Set default",
          onSelect: () => void setDefaultModel(state.activeTypeId, mid),
        },
      ];
      if (state.activeTypeId === "text_llm") {
        actions.push({
          value: "set-main",
          label: "Set main",
          onSelect: () => void setMainModel(state.activeTypeId, mid),
        });
      }
      actions.push(
        {
          value: "edit",
          label: "Edit",
          onSelect: () => void openModelEditor(state.activeTypeId, model),
        },
        {
          value: "clone",
          label: "Clone",
          onSelect: () => void cloneModel(state.activeTypeId, mid),
        },
        {
          value: "pre-download",
          label: "Pre-download",
          onSelect: () => void preDownloadModel(state.activeTypeId, mid),
        },
        {
          value: "delete",
          label: "Delete",
          onSelect: () => void deleteModel(state.activeTypeId, mid),
        }
      );
      const flagsLine = createInlinePairs([
        { label: "Default:", value: isDefault ? "Yes" : "No" },
        { label: "Main:", value: isMain ? "Yes" : "No" },
        { label: "Lazy:", value: model.lazy === false ? "No" : "Yes" },
        { label: "Persist:", value: model.persist ? "Yes" : "No" },
      ]);
      const row = buildRow(
        template,
        [
          midBtn,
          { mobileLabel: "Loader:", text: loaderId },
          isDefault ? "yes" : "no",
          isMain ? "yes" : "no",
          model.lazy === false ? "no" : "yes",
          model.persist ? "yes" : "no",
          createActionSelect(actions),
        ],
        false,
        {
          rowClass: "md-model-row",
          cellClasses: ["md-model-id", "md-model-loader", "md-model-default md-model-flags md-model-flag-source", "md-model-main md-model-flag-source", "md-model-lazy md-model-flag-source", "md-model-persist md-model-flag-source", "md-model-actions"],
          mobileOverrides: {
            2: flagsLine,
          },
          hideOnMobile: [3, 4, 5],
        }
      );
      list.appendChild(row);
    }
    const listWrap = wrapStickyScroll(list);
    target.appendChild(listWrap);

    const addRow = document.createElement("div");
    addRow.className = "md-actions";
    const addBtn = document.createElement("button");
    addBtn.className = "ghost";
    addBtn.textContent = "Add model...";
    addBtn.addEventListener("click", () => void openModelEditor(state.activeTypeId, null));
    addRow.appendChild(addBtn);
    target.appendChild(addRow);
  }

  function renderProcesses() {
    const target = tabSections.processes;
    target.innerHTML = "";

    const data = state.processes || {};
    const main = data.main || null;
    const defaults = Array.isArray(data.defaults) ? data.defaults : [];
    const workers = Array.isArray(data.workers) ? data.workers : [];

    const list = document.createElement("div");
    list.className = "md-list";
    const template = "2.2fr 1.4fr 1.8fr 70px 90px 110px 110px 1.4fr 120px";
    list.appendChild(buildRow(template, ["Name", "Type", "Model ID", "Persist", "Status", "CPU Mem", "GPU Mem", "Details", "Actions"], true, {
      rowClass: "md-process-row",
      cellClasses: ["md-process-name", "md-process-type", "md-process-model", "md-process-persist md-process-status", "md-process-status", "md-process-cpu md-process-mem", "md-process-gpu", "md-process-details", "md-process-actions"],
    }));

    const totals = data.totals || {};
    const sharedGpu = totals.gpu_bytes ? `est. ${fmtBytes(totals.gpu_bytes)}` : "";

    function addRow(entry, extra) {
      const actions = document.createElement("div");
      actions.className = "md-actions";
      if (extra?.actionBtn) actions.appendChild(extra.actionBtn);
      const row = buildRow(
        template,
        [
          `${entry.name || ""}${entry.type ? ` - ${entry.type}` : ""}`,
          entry.type || "",
          { mobileLabel: "Model ID:", text: entry.model_id || "" },
          entry.persist ? "yes" : "no",
          entry.status || "",
          entry.cpu || "",
          entry.gpu || sharedGpu || "",
          { mobileLabel: "Details:", text: entry.details || "" },
          actions,
        ],
        false,
        {
          rowClass: "md-process-row",
          cellClasses: ["md-process-name", "md-process-type", "md-process-model", "md-process-persist", "md-process-status", "md-process-cpu", "md-process-gpu", "md-process-details", "md-process-actions"],
          mobileOverrides: {
            2: { mobileLabel: "Model ID:", text: entry.model_id || "" },
            3: createInlinePairs([
              { label: "Persist:", value: entry.persist ? "Yes" : "No" },
              { label: "Status:", value: entry.status || "" },
            ]),
            5: { mobileLabel: "", text: `CPU MEM: ${entry.cpu || ""}  GPU MEM: ${entry.gpu || sharedGpu || ""}` },
            7: { mobileLabel: "Details:", text: entry.details || "" },
          },
          hideOnMobile: [1, 4, 6],
        }
      );
      list.appendChild(row);
    }

    if (main && typeof main === "object") {
      const loaded = Boolean(main.loaded);
      const supports = Boolean(main.supports_load);
      const status = main.phase || (supports
        ? (loaded ? "loaded" : (main.backend_mode === "llama_server" && main.server_running ? "server running" : "stopped"))
        : "unsupported");
      let actionBtn = null;
      if (supports && main.persist) {
        const actionKey = getProcessActionKey("main", main.type_id);
        actionBtn = buildProcessActionButton(loaded ? "Stop" : "Play", actionKey);
        actionBtn.addEventListener("click", () => void toggleProcess("main", main.type_id, loaded, actionKey));
      }
      addRow(
        {
          name: main.label || "Main text LLM",
          type: main.type_id || "text_llm",
          model_id: main.model_id || "",
          persist: Boolean(main.persist),
          status,
          cpu: fmtBytes(main.cpu_bytes),
          gpu: fmtBytes(main.gpu_bytes),
          details: [main.slot || "", main.server_device || "", main.server_url || "", main.status_note || "", main.last_error ? `error: ${main.last_error}` : ""].filter(Boolean).join(" | "),
        },
        { actionBtn }
      );
    }

    for (const entry of defaults) {
      if (!entry || typeof entry !== "object") continue;
      const loaded = Boolean(entry.loaded);
      const supports = Boolean(entry.supports_load);
      const status = entry.phase || (supports
        ? (loaded ? "loaded" : (entry.backend_mode === "llama_server" && entry.server_running ? "server running" : "stopped"))
        : "unsupported");
      let actionBtn = null;
      if (supports && entry.persist) {
        const actionKey = getProcessActionKey("default", entry.type_id);
        actionBtn = buildProcessActionButton(loaded ? "Stop" : "Play", actionKey);
        actionBtn.addEventListener("click", () => void toggleProcess("default", entry.type_id, loaded, actionKey));
      }
      addRow(
        {
          name: `Default: ${entry.label || entry.type_id || ""}`,
          type: entry.type_id || "",
          model_id: entry.model_id || "",
          persist: Boolean(entry.persist),
          status,
          cpu: fmtBytes(entry.cpu_bytes),
          gpu: fmtBytes(entry.gpu_bytes),
          details: [entry.slot || "", entry.server_device || "", entry.server_url || "", entry.status_note || "", entry.last_error ? `error: ${entry.last_error}` : ""].filter(Boolean).join(" | "),
        },
        { actionBtn }
      );
    }

    for (const entry of workers) {
      if (!entry || typeof entry !== "object") continue;
      const meta = entry.meta || {};
      const actionKey = getProcessActionKey("worker", null, entry.worker_id);
      const actionBtn = buildProcessActionButton("Stop", actionKey);
      actionBtn.addEventListener("click", () => void stopWorker(entry.worker_id, actionKey));
      addRow(
        {
          name: `Worker: ${meta.model_type || meta.slot || "vlm"}`,
          type: meta.model_type || "",
          model_id: meta.model_id || "",
          persist: Boolean(meta.persist),
          status: entry.alive ? "running" : "stopped",
          cpu: fmtBytes(entry.cpu_bytes),
          gpu: fmtBytes(entry.gpu_bytes),
          details: `pid: ${entry.pid || ""}`,
        },
        { actionBtn }
      );
    }

    const listWrap = wrapStickyScroll(list);
    target.appendChild(listWrap);

    const totalsRow = document.createElement("div");
    totalsRow.className = "md-muted";
    const cpuText = hasBytes(totals.cpu_bytes) && hasBytes(totals.cpu_total_bytes)
      ? `${fmtBytes(totals.cpu_bytes)} / ${fmtBytes(totals.cpu_total_bytes)}`
      : (hasBytes(totals.cpu_bytes) ? fmtBytes(totals.cpu_bytes) : "");
    const gpuText = hasBytes(totals.gpu_bytes) && hasBytes(totals.gpu_total_bytes)
      ? `${fmtBytes(totals.gpu_bytes)} / ${fmtBytes(totals.gpu_total_bytes)}`
      : (hasBytes(totals.gpu_bytes) ? fmtBytes(totals.gpu_bytes) : "");
    const cpuPct = totals.cpu_percent ? `${totals.cpu_percent}%` : "";
    const gpuPct = totals.gpu_percent ? `${totals.gpu_percent}%` : "";
    const cpuBufferText = hasBytes(totals.cpu_buffer_bytes) ? ` | llama.cpp CPU buffers ${fmtBytes(totals.cpu_buffer_bytes)}` : "";
    const gpuActualText = hasBytes(totals.gpu_actual_bytes) ? ` | GPU actual ${fmtBytes(totals.gpu_actual_bytes)}` : "";
    const gpuBufferText = hasBytes(totals.gpu_buffer_bytes) ? ` | llama.cpp GPU buffers ${fmtBytes(totals.gpu_buffer_bytes)}` : "";
    totalsRow.textContent = `Totals: CPU ${cpuText} ${cpuPct} | GPU ${gpuText} ${gpuPct}${gpuActualText}${cpuBufferText}${gpuBufferText}`.trim();
    target.appendChild(totalsRow);
  }

  function applyEditorBootstrap(bootstrap) {
    if (!bootstrap || typeof bootstrap !== "object") return false;
    state.templates = bootstrap.templates || {};
    state.schemas = bootstrap.schemas || {};
    state.deck = bootstrap.deck || {};
    state.loaderIds = bootstrap.loaderIds || [];
    state.processes = bootstrap.processes || {};
    if (!state.activeTypeId) {
      const types = state.deck?.types || {};
      const ordered = sortTypes(types);
      if (ordered.length) state.activeTypeId = ordered[0][0];
    }
    renderOverview();
    renderModels();
    renderProcesses();
    return true;
  }

  async function reloadAll() {
    statusLabel.textContent = "Loading...";
    try {
      const [tpl, sch, st, deck, proc, managed] = await Promise.all([
        apiJson(ctx, "/v1/model_deck/type_templates"),
        apiJson(ctx, "/v1/model_deck_loader/schema"),
        apiJson(ctx, "/v1/model_deck/status"),
        apiJson(ctx, "/v1/model_deck/deck"),
        apiJson(ctx, "/v1/model_deck/processes?include_managed=0").catch(() => ({})),
        apiJson(ctx, "/v1/model_deck/processes").catch(() => ({})),
      ]);
      const mergedProcesses = mergeManagedProcessSnapshot(
        stabilizeManagedProcessSnapshot(state.processes, proc || {}),
        managed || {}
      );
      const bootstrap = {
        templates: tpl?.templates || {},
        schemas: sch?.schemas || {},
        deck: deck?.deck || {},
        loaderIds: st?.loader_ids || [],
        processes: mergedProcesses,
      };
      applyEditorBootstrap(bootstrap);
      cacheSet(ctx, CACHE_KEY_EDITOR_BOOTSTRAP, bootstrap, CACHE_TTL_EDITOR_MS);
      cacheSet(ctx, CACHE_KEY_DECK, bootstrap.deck || {}, CACHE_TTL_DECK_MS);
      statusLabel.textContent = "OK";
    } catch (err) {
      statusLabel.textContent = `Error: ${err.message || err}`;
    }
  }

  async function refreshProcesses() {
    try {
      const [proc, managed] = await Promise.all([
        apiJson(ctx, "/v1/model_deck/processes?include_managed=0"),
        apiJson(ctx, "/v1/model_deck/processes").catch(() => ({})),
      ]);
      state.processes = mergeManagedProcessSnapshot(
        stabilizeManagedProcessSnapshot(state.processes, proc || {}),
        managed || {}
      );
      cacheSet(ctx, CACHE_KEY_EDITOR_BOOTSTRAP, {
        templates: state.templates,
        schemas: state.schemas,
        deck: state.deck,
        loaderIds: state.loaderIds,
        processes: state.processes,
      }, CACHE_TTL_EDITOR_MS);
      if (state.activeTab === "processes") renderProcesses();
    } catch (err) {
      statusLabel.textContent = `Error: ${err.message || err}`;
    }
  }

  async function addTypeFromTemplate(templateId) {
    if (!templateId) return;
    if (templateId === "__custom__") {
      const result = await promptCustomType();
      if (!result) return;
      await apiJson(ctx, "/v1/model_deck/type/upsert", {
        method: "POST",
        body: { type_id: result.typeId, label: result.label, notes: result.notes || "" },
      });
      state.activeTypeId = result.typeId;
      await reloadAll();
      setActiveTab("models");
      return;
    }
    const tpl = state.templates[templateId];
    if (!tpl) return;
    await apiJson(ctx, "/v1/model_deck/type/upsert", {
      method: "POST",
      body: { type_id: templateId, label: tpl.label || templateId, notes: tpl.notes || "" },
    });
    state.activeTypeId = templateId;
    await reloadAll();
    setActiveTab("models");
  }

  async function saveTypeMeta(typeId, label, notes) {
    if (!typeId) return;
    await apiJson(ctx, "/v1/model_deck/type/upsert", {
      method: "POST",
      body: { type_id: typeId, label: label || typeId, notes: notes || "" },
    });
    await reloadAll();
  }

  async function deleteType(typeId) {
    if (!typeId) return;
    if (!confirm(`Delete model type '${typeId}'?`)) return;
    await apiJson(ctx, "/v1/model_deck/type/delete", {
      method: "POST",
      body: { type_id: typeId },
    });
    await reloadAll();
  }

  async function setDefaultModel(typeId, modelId) {
    await apiJson(ctx, "/v1/model_deck/model/set_default", {
      method: "POST",
      body: { type_id: typeId, model_id: modelId },
    });
    await reloadAll();
  }

  async function setMainModel(typeId, modelId) {
    await apiJson(ctx, "/v1/model_deck/model/set_main", {
      method: "POST",
      body: { type_id: typeId, model_id: modelId },
    });
    await reloadAll();
  }

  async function deleteModel(typeId, modelId) {
    if (!confirm(`Delete model '${modelId}' from '${typeId}'?`)) return;
    await apiJson(ctx, "/v1/model_deck/model/delete", {
      method: "POST",
      body: { type_id: typeId, model_id: modelId },
    });
    await reloadAll();
  }

  async function cloneModel(typeId, modelId) {
    if (!typeId || !modelId) return;
    const res = await apiJson(ctx, "/v1/model_deck/model/clone", {
      method: "POST",
      body: { type_id: typeId, model_id: modelId },
    });
    const clonedId = String(res?.model?.model_id || "").trim();
    await reloadAll();
    if (clonedId) statusLabel.textContent = `Cloned as ${clonedId}`;
  }

  async function preDownloadModel(typeId, modelId) {
    if (!typeId || !modelId) return;
    statusLabel.textContent = `Pre-downloading ${modelId}...`;
    try {
      const res = await apiJson(ctx, "/v1/model_deck/model/pre_download", {
        method: "POST",
        body: { type_id: typeId, model_id: modelId },
      });
      const downloads = Array.isArray(res?.result?.downloads) ? res.result.downloads : [];
      if (!downloads.length) {
        const note = res?.result?.note ? `\n${res.result.note}` : "";
        alert(`Pre-download complete.${note}`);
        return;
      }
      const lines = downloads.map((item) => {
        const label = item.kind ? `${item.kind}: ` : "";
        const path = item.path || item.filename || item.repo_id || "";
        return `${label}${path}`;
      });
      alert(`Pre-download complete:\n${lines.join("\n")}`);
    } catch (err) {
      alert(`Pre-download failed: ${err?.message || err}`);
    } finally {
      statusLabel.textContent = "";
    }
  }

  async function toggleProcess(kind, typeId, isLoaded, actionKey) {
    if (!kind) return;
    setProcessActionPending(actionKey, true);
    const shouldStop = Boolean(isLoaded);
    const path =
      kind === "main" || kind === "default"
        ? shouldStop
          ? "/v1/model_deck/processes/stop"
          : "/v1/model_deck/processes/start"
        : "/v1/model_deck/processes/stop";
    const payload = { kind };
    if (kind === "default") payload.type_id = typeId;
    try {
      await apiJson(ctx, path, { method: "POST", body: payload });
      statusLabel.textContent = shouldStop ? "Stopped" : "Started";
    } catch (err) {
      statusLabel.textContent = `${shouldStop ? "Stop" : "Start"} failed: ${err?.message || err}`;
      throw err;
    } finally {
      setProcessActionPending(actionKey, false);
      await refreshProcesses();
    }
  }

  async function stopWorker(workerId, actionKey) {
    if (!workerId) return;
    setProcessActionPending(actionKey, true);
    try {
      await apiJson(ctx, "/v1/model_deck/processes/stop", {
        method: "POST",
        body: { kind: "worker", worker_id: workerId },
      });
    } finally {
      setProcessActionPending(actionKey, false);
      await refreshProcesses();
    }
  }

  async function promptHfLogin() {
    const modal = createModal("Hugging Face login");
    const field = createTextField("Access token", "");
    field.input.type = "password";
    modal.body.appendChild(field.wrap);
    return modal.open(async () => {
      const token = field.input.value.trim();
      if (!token) {
        alert("Token is required.");
        return false;
      }
      await apiJson(ctx, "/v1/model_deck/hf_token", { method: "POST", body: { token } });
      return true;
    });
  }

  function buildRow(template, cells, isHeader, options = {}) {
    const row = document.createElement("div");
    row.className = "md-row";
    if (isHeader) row.classList.add("md-row-header");
    if (options.rowClass) row.classList.add(...String(options.rowClass).split(/\s+/).filter(Boolean));
    row.style.gridTemplateColumns = template;
    const useMobileOverrides = typeof window !== "undefined" && window.matchMedia && window.matchMedia("(max-width: 720px)").matches;
    cells.forEach((cell, index) => {
      const override = useMobileOverrides && options.mobileOverrides && options.mobileOverrides[index] ? options.mobileOverrides[index] : null;
      const cellEl = document.createElement("div");
      cellEl.className = "md-cell";
      if (isHeader) cellEl.classList.add("muted");
      const cellClass = Array.isArray(options.cellClasses) ? options.cellClasses[index] : "";
      if (cellClass) cellEl.classList.add(...String(cellClass).split(/\s+/).filter(Boolean));
      if (Array.isArray(options.hideOnMobile) && options.hideOnMobile.includes(index)) {
        cellEl.dataset.mobileHide = "true";
      }
      const value = override || cell;
      if (value instanceof HTMLElement) {
        cellEl.appendChild(value);
      } else if (value && typeof value === "object" && !Array.isArray(value)) {
        const mobileLabel = String(value.mobileLabel || "").trim();
        if (mobileLabel) {
          const label = document.createElement("span");
          label.className = "md-mobile-label";
          label.textContent = mobileLabel;
          cellEl.appendChild(label);
        }
        const textNode = document.createElement("span");
        textNode.textContent = String(value.text ?? "");
        cellEl.appendChild(textNode);
      } else {
        cellEl.textContent = String(value ?? "");
      }
      row.appendChild(cellEl);
    });
    return row;
  }

  function createActionSelect(actions) {
    const select = document.createElement("select");
    select.className = "plugin-search-input md-action-select";
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "Actions...";
    placeholder.disabled = true;
    placeholder.selected = true;
    select.appendChild(placeholder);
    const handlers = new Map();
    for (const action of actions || []) {
      if (!action || !action.value) continue;
      const option = document.createElement("option");
      option.value = action.value;
      option.textContent = action.label || action.value;
      if (action.disabled) option.disabled = true;
      select.appendChild(option);
      handlers.set(action.value, action.onSelect);
    }
    select.addEventListener("change", () => {
      const value = select.value;
      const handler = handlers.get(value);
      if (handler) handler();
      select.value = "";
    });
    return select;
  }

  async function openModelEditor(typeId, model) {
    const supportsManagedLlamaServer = typeId === "text_llm" || typeId === "vlm";
    const schema = state.schemas?.[typeId] || {};
    const fields = Array.isArray(schema.fields) ? schema.fields : [];
    const loaderIds = Array.isArray(state.loaderIds) ? state.loaderIds : [];
    const selectedLoaderId = model?.loader_id || schema.recommended_loader_id || loaderIds[0] || "";
    const visibleLoaderIds = getVisibleLoaderIds(loaderIds, selectedLoaderId);
    const managedServers = [];
    const managedServerPromise = supportsManagedLlamaServer ? getManagedLlamaServers(ctx) : Promise.resolve([]);
    let mainGpuEntry = null;
    let mainGpuFormEntry = null;
    let preferredMainGpuValue = String(model?.settings?.main_gpu ?? "").trim();
    let backendModeEntry = null;
    let gpuSelectionModeEntry = null;
    let gpuSplitModeEntry = null;
    let gpuSplitDevicesEntry = null;
    let gpuSplitPercentEntry = null;
    let llamaServerUrlEntry = null;
    let managedServerPicker = null;
    let managedServerHint = null;
    let selectedManagedServerId = String(model?.settings?.llama_server_managed_id || "").trim();
    let workflowTrainingArtifacts = [];
    const workflowTrainingEnabled = isWorkflowTrainingPluginEnabled(ctx);
    const sharedGgufSearch = getSetupWizardGgufSearch(ctx);

    const modal = createModal(model ? "Edit model" : "Add model");
    const form = document.createElement("div");
    form.className = "md-card";

    const modelIdField = createTextField("Model ID", model?.model_id || "");
    const loaderField = createSelectField(
      "Loader",
      visibleLoaderIds.map((lid) => ({ value: lid, label: lid })),
      selectedLoaderId
    );
    const lazyField = createCheckboxField("Lazy load", model ? model.lazy !== false : true);
    const persistField = createCheckboxField("Persist", model ? Boolean(model.persist) : false);

    form.appendChild(modelIdField.wrap);
    form.appendChild(loaderField.wrap);
    form.appendChild(lazyField.wrap);
    form.appendChild(persistField.wrap);

    const settingsWrap = document.createElement("div");
    settingsWrap.className = "md-card";
    const settingsHead = document.createElement("div");
    settingsHead.style.display = "flex";
    settingsHead.style.alignItems = "center";
    settingsHead.style.justifyContent = "space-between";
    settingsHead.style.gap = "10px";
    settingsHead.style.flexWrap = "wrap";
    const settingsTitle = document.createElement("div");
    settingsTitle.textContent = "Settings";
    settingsTitle.style.fontWeight = "600";
    settingsHead.appendChild(settingsTitle);
    settingsWrap.appendChild(settingsHead);

    const entries = [];
    const entriesByKey = {};
    function getDeckSearchQuery() {
      const candidates = [
        model?.settings?.model_path,
        model?.settings?.model_id,
        model?.model_id,
        modelIdField?.input?.value,
      ];
      for (const candidate of candidates) {
        const text = String(candidate || "").trim();
        if (!text) continue;
        const last = text.split(/[\\/]/).pop() || text;
        const cleaned = last
          .replace(/\.gguf$/i, "")
          .replace(/q\d+[_-]k[_-]?[a-z0-9]+/ig, "")
          .replace(/bf16|f16|f32|instruct/ig, "")
          .replace(/[._-]+/g, " ")
          .trim();
        if (cleaned) return cleaned;
      }
      return typeId === "vlm" ? "Qwen VL" : "Qwen";
    }
    function applyPickedGguf(selection) {
      const modelSource = String(selection?.modelSource || selection?.result?.model_source || "").trim();
      if (!modelSource) return;
      const modelPathEntry = entriesByKey["model_path"];
      const ggufModelEntry = entriesByKey["model_id"];
      const mmprojEntry = entriesByKey["mmproj_path"];
      if (modelPathEntry?.input && "value" in modelPathEntry.input) {
        modelPathEntry.input.value = modelSource;
      }
      if (ggufModelEntry?.input && "value" in ggufModelEntry.input) {
        ggufModelEntry.input.value = modelSource;
      }
      const mmprojSource = String(selection?.mmprojSource || "").trim();
      if (mmprojSource && mmprojEntry?.input && "value" in mmprojEntry.input) {
        mmprojEntry.input.value = mmprojSource;
      }
      if (modelIdField?.input && !String(modelIdField.input.value || "").trim()) {
        modelIdField.input.value = String(selection?.suggestedModelEntryId || "").trim();
      }
    }
    if (sharedGgufSearch && (typeId === "text_llm" || typeId === "vlm")) {
      const searchBtn = document.createElement("button");
      searchBtn.type = "button";
      searchBtn.className = "secondary";
      searchBtn.textContent = "Search HuggingFace GGUF";
      searchBtn.addEventListener("click", async () => {
        try {
          const backendMode = String(entriesByKey["backend_mode"]?.input?.value || model?.settings?.backend_mode || "embedded").trim() || "embedded";
          const picked = await sharedGgufSearch.open(ctx, {
            query: getDeckSearchQuery(),
            backendMode,
            destinationMode: backendMode === "embedded" ? "hf_cache" : "models_dir",
            includeMmproj: typeId === "vlm",
          });
          if (picked) applyPickedGguf(picked);
        } catch (err) {
          toast(ctx, String(err?.message || err || "Failed to search HuggingFace GGUF"), true);
        }
      });
      settingsHead.appendChild(searchBtn);
    }
    function imageGenFieldBackend(labelText) {
      const text = String(labelText || "");
      const match = text.match(/\((sd_cpp|diffusers|gguf_cli)\)/i);
      return match ? String(match[1] || "").toLowerCase() : "";
    }
    for (const field of fields) {
      if (!field || typeof field !== "object") continue;
      const key = String(field.key || "").trim();
      if (!key) continue;
      const label = String(field.label || key);
      const type = String(field.type || "str").toLowerCase();
      const value = model?.settings?.[key];
      const defaultValue = value !== undefined ? value : field.default ?? "";
      const entry = createSchemaField(label, type, field, defaultValue);
      if (entry) {
        if (
          key === "backend"
          && type === "enum"
          && Array.isArray(field.choices)
          && field.choices.length <= 1
        ) {
          entry.wrap.style.display = "none";
        }
        if (supportsManagedLlamaServer && key === "main_gpu") {
          mainGpuEntry = entry;
        }
        if (supportsManagedLlamaServer && key === "backend_mode") {
          backendModeEntry = entry;
        }
        if (supportsManagedLlamaServer && key === "gpu_selection_mode") {
          gpuSelectionModeEntry = entry;
        }
        if (supportsManagedLlamaServer && key === "gpu_split_mode") {
          gpuSplitModeEntry = entry;
        }
        if (supportsManagedLlamaServer && key === "gpu_split_devices") {
          gpuSplitDevicesEntry = entry;
        }
        if (supportsManagedLlamaServer && key === "gpu_split_percent") {
          gpuSplitPercentEntry = entry;
        }
        if (supportsManagedLlamaServer && key === "llama_server_url" && entry.input instanceof HTMLElement && "value" in entry.input) {
          llamaServerUrlEntry = entry;
          const picker = document.createElement("select");
          picker.className = "plugin-search-input";
          const blank = document.createElement("option");
          blank.value = "";
          blank.textContent = "Loading managed servers...";
          picker.appendChild(blank);
          picker.addEventListener("change", () => {
            entry.input.value = picker.value;
            const opt = picker.selectedOptions && picker.selectedOptions[0];
            selectedManagedServerId = String(opt?.dataset?.serverId || "").trim();
            void syncManagedMainGpuChoices();
          });
          const hint = document.createElement("div");
          hint.className = "field-help";
          hint.textContent = "Select a host-managed llama-server or enter a URL manually above.";
          entry.wrap.appendChild(picker);
          entry.wrap.appendChild(hint);
          managedServerPicker = picker;
          managedServerHint = hint;
        }
        settingsWrap.appendChild(entry.wrap);
        const formEntry = { key, type, input: entry.input, wrap: entry.wrap, backendScope: typeId === "image_gen" ? imageGenFieldBackend(label) : "" };
        entries.push(formEntry);
        entriesByKey[key] = formEntry;
        if (supportsManagedLlamaServer && key === "main_gpu") {
          mainGpuFormEntry = formEntry;
        }
      }
    }

    async function loadWorkflowTrainingArtifacts() {
      if (!workflowTrainingEnabled) {
        workflowTrainingArtifacts = [];
        return;
      }
      if (typeId !== "text_llm" && typeId !== "vlm") return;
      try {
        const payload = await apiJson(ctx, "/v1/workflow_training/artifacts");
        workflowTrainingArtifacts = Array.isArray(payload?.items) ? payload.items : [];
      } catch (_err) {
        workflowTrainingArtifacts = [];
      }
    }

    function syncLoraFieldVisibility() {
      const adapterEntry = entriesByKey["lora_adapter_path"];
      const baseEntry = entriesByKey["lora_base_model_path"];
      const scaleEntry = entriesByKey["lora_scale"];
      const hasAdapter = !!String(adapterEntry?.input?.value || "").trim();
      if (baseEntry?.wrap) {
        baseEntry.wrap.style.display = hasAdapter ? "" : "none";
      }
      if (scaleEntry?.wrap) {
        scaleEntry.wrap.style.display = hasAdapter ? "" : "none";
      }
    }

    function addWorkflowTrainingPickers() {
      if (!workflowTrainingEnabled) return;
      const adapterEntry = entriesByKey["lora_adapter_path"];
      const baseEntry = entriesByKey["lora_base_model_path"];
      if (!adapterEntry) return;
      const modelRefs = [
        entriesByKey["model_path"]?.input?.value,
        entriesByKey["model_id"]?.input?.value,
        model?.settings?.model_path,
        model?.settings?.model_id,
        model?.model_id,
      ].filter((value) => String(value || "").trim());
      const adapterDirItems = workflowTrainingArtifacts.filter((item) => String(item?.kind || "") === "adapter_dir");
      const compatibleItems = adapterDirItems.filter((item) => {
        const itemBase = String(item?.base_model || "").trim();
        if (!itemBase || !modelRefs.length) return true;
        return modelRefs.some((ref) => workflowTrainingModelsCompatible(itemBase, ref));
      });
      const compatiblePaths = new Set(compatibleItems.map((item) => String(item?.path || "")));
      const adapterItems = [
        ...compatibleItems,
        ...adapterDirItems.filter((item) => !compatiblePaths.has(String(item?.path || ""))),
      ];
      if (adapterEntry?.wrap) {
        const picker = document.createElement("select");
        picker.className = "plugin-search-input";
        const blank = document.createElement("option");
        blank.value = "";
        blank.textContent = adapterItems.length
          ? (compatibleItems.length ? "Choose Workflow Training adapter..." : "No exact base-model match found. Choose an adapter manually...")
          : "No Workflow Training adapters found";
        picker.appendChild(blank);
        for (const item of adapterItems) {
          const option = document.createElement("option");
          option.value = String(item?.path || "");
          const compatible = compatiblePaths.has(String(item?.path || ""));
          option.textContent = `${compatible ? "[Compatible] " : ""}${String(item?.job_id || "adapter")} - ${String(item?.path || "")}`;
          picker.appendChild(option);
        }
        picker.addEventListener("change", () => {
          if (adapterEntry.input && "value" in adapterEntry.input) adapterEntry.input.value = picker.value;
          if (baseEntry?.input && "value" in baseEntry.input && !String(baseEntry.input.value || "").trim()) {
            const selected = adapterItems.find((item) => String(item?.path || "") === String(picker.value || ""));
            if (selected?.base_model) baseEntry.input.value = String(selected.base_model || "");
          }
          syncLoraFieldVisibility();
        });
        const hint = document.createElement("div");
        hint.className = "field-help";
        hint.textContent = compatibleItems.length
          ? "Pick a finished Workflow Training adapter directory for this base model, or keep using a manual path."
          : "No exact compatible adapter was detected automatically. You can still choose a Workflow Training adapter directory manually.";
        adapterEntry.wrap.appendChild(picker);
        adapterEntry.wrap.appendChild(hint);
      }
    }

    function syncImageGenBackendVisibility() {
      if (typeId !== "image_gen") return;
      const backendEntry = entries.find((e) => e.key === "backend");
      const backend = String(backendEntry?.input?.value || "").trim().toLowerCase();
      for (const entry of entries) {
        const scope = String(entry.backendScope || "").trim().toLowerCase();
        if (!scope || !entry.wrap) continue;
        entry.wrap.style.display = scope === backend ? "" : "none";
      }
    }

    async function syncManagedMainGpuChoices() {
      if (!mainGpuEntry || !mainGpuEntry.input) return;
      const backendMode = String(backendModeEntry?.input?.value || "").trim().toLowerCase();
      if (backendMode !== "llama_server" || !selectedManagedServerId) return;
      const choices = await getManagedLlamaDeviceChoices(ctx, managedServers, selectedManagedServerId);
      if (!choices.length) return;
      let inputEl = mainGpuEntry.input;
      const prev = String(inputEl.value || "").trim();
      const preferred = String(preferredMainGpuValue || "").trim();
      if (inputEl.tagName !== "SELECT") {
        const select = document.createElement("select");
        select.className = "plugin-search-input";
        select.name = inputEl.name || "";
        select.title = inputEl.title || "";
        inputEl.replaceWith(select);
        mainGpuEntry.input = select;
        if (mainGpuFormEntry) mainGpuFormEntry.input = select;
        inputEl = select;
      }
      inputEl.innerHTML = "";
      for (const opt of choices) {
        const option = document.createElement("option");
        option.value = String(opt.value || "");
        option.textContent = String(opt.label || opt.value || "");
        inputEl.appendChild(option);
      }
      if (preferred && choices.some((opt) => String(opt.value) === preferred)) {
        inputEl.value = preferred;
      } else if (choices.some((opt) => String(opt.value) === prev)) {
        inputEl.value = prev;
      } else {
        inputEl.value = String(choices[0]?.value || "0");
      }
      inputEl.title = "Select the llama.cpp server GPU device id reported by --list-devices.";
    }

    function parseCsvList(value) {
      return String(value || "")
        .split(",")
        .map((x) => String(x || "").trim())
        .filter(Boolean);
    }

    function parseNumberCsvList(value) {
      return String(value || "")
        .split(",")
        .map((x) => Number(x))
        .map((n) => (Number.isFinite(n) ? n : 0));
    }

    function currentGpuChoices() {
      const inputEl = mainGpuEntry?.input;
      if (inputEl && inputEl.tagName === "SELECT") {
        const out = [];
        for (const opt of Array.from(inputEl.options || [])) {
          const value = String(opt.value || "").trim();
          if (!value) continue;
          out.push({ value, label: String(opt.textContent || value).trim() });
        }
        if (out.length) return out;
      }
      return [{ value: "0", label: "GPU 0" }];
    }

    function installMainGpuPickerFromChoices(choices) {
      if (!mainGpuEntry || !mainGpuEntry.input || !Array.isArray(choices) || !choices.length) return;
      let inputEl = mainGpuEntry.input;
      const prev = String(inputEl.value || "").trim();
      const preferred = String(preferredMainGpuValue || "").trim();
      if (inputEl.tagName !== "SELECT") {
        const select = document.createElement("select");
        select.className = "plugin-search-input";
        select.name = inputEl.name || "";
        select.title = inputEl.title || "";
        inputEl.replaceWith(select);
        mainGpuEntry.input = select;
        if (mainGpuFormEntry) mainGpuFormEntry.input = select;
        inputEl = select;
      }
      inputEl.innerHTML = "";
      for (const opt of choices) {
        const option = document.createElement("option");
        option.value = String(opt.value || "");
        option.textContent = String(opt.label || opt.value || "");
        inputEl.appendChild(option);
      }
      if (preferred && choices.some((opt) => String(opt.value) === preferred)) {
        inputEl.value = preferred;
      } else if (choices.some((opt) => String(opt.value) === prev)) {
        inputEl.value = prev;
      } else {
        inputEl.value = String(choices[0]?.value || "0");
      }
      inputEl.title = "Select the GPU by device name (stored as device id).";
    }

    let gpuSplitPanel = null;
    let gpuSplitRows = null;
    function ensureGpuSplitPanel() {
      if (!gpuSplitDevicesEntry?.wrap || !gpuSplitPercentEntry?.wrap) return;
      if (gpuSplitPanel) return;
      gpuSplitPanel = document.createElement("div");
      gpuSplitPanel.className = "md-card";
      const title = document.createElement("div");
      title.style.fontWeight = "600";
      title.textContent = "Split GPU allocation";
      const hint = document.createElement("div");
      hint.className = "field-help";
      hint.textContent = "Each line is one GPU device. Enter the workload percentage for each selected GPU.";
      gpuSplitRows = document.createElement("div");
      gpuSplitRows.style.display = "grid";
      gpuSplitRows.style.gap = "8px";
      gpuSplitPanel.appendChild(title);
      gpuSplitPanel.appendChild(hint);
      gpuSplitPanel.appendChild(gpuSplitRows);
      gpuSplitDevicesEntry.wrap.appendChild(gpuSplitPanel);
    }

    function renderGpuSplitRows() {
      ensureGpuSplitPanel();
      if (!gpuSplitRows || !gpuSplitDevicesEntry || !gpuSplitPercentEntry) return;
      gpuSplitRows.innerHTML = "";
      const choices = currentGpuChoices();
      const selectedIds = parseCsvList(gpuSplitDevicesEntry.input?.value || "");
      const percentVals = parseNumberCsvList(gpuSplitPercentEntry.input?.value || "");
      const selectedSet = new Set(selectedIds);
      const idToLabel = new Map(choices.map((c) => [String(c.value), String(c.label)]));
      const orderedIds = selectedIds.length
        ? [...selectedIds, ...choices.map((c) => String(c.value || "").trim()).filter((id) => id && !selectedSet.has(id))]
        : choices.map((c) => String(c.value || "").trim()).filter(Boolean);
      const rows = orderedIds.map((id, idx) => {
        const selectedIndex = selectedIds.indexOf(id);
        const pctFromSelected = selectedIndex >= 0 ? Number(percentVals[selectedIndex] || 0) : 0;
        const pctFromOrder = Number(percentVals[idx] || 0);
        const checked = selectedIds.length ? selectedSet.has(id) : Boolean(pctFromOrder > 0);
        const pct = selectedIds.length ? pctFromSelected : pctFromOrder;
        return { id, pct, checked };
      });
      const refreshHidden = () => {
        const idOut = [];
        const pctOut = [];
        const lineEls = Array.from(gpuSplitRows.querySelectorAll("[data-gpu-id]"));
        for (const line of lineEls) {
          const id = String(line.getAttribute("data-gpu-id") || "").trim();
          const enabled = line.querySelector("input[type='checkbox']");
          const input = line.querySelector("input[type='number']");
          if (!id || !input || !enabled) continue;
          if (!enabled.checked) continue;
          const pct = Number(input.value);
          if (!Number.isFinite(pct) || pct <= 0) continue;
          idOut.push(id);
          pctOut.push(pct);
        }
        gpuSplitDevicesEntry.input.value = idOut.join(",");
        gpuSplitPercentEntry.input.value = pctOut.join(",");
      };

      for (const row of rows) {
        const id = String(row.id || "").trim();
        if (!id) continue;
        const line = document.createElement("div");
        line.className = "field";
        line.style.margin = "0";
        line.setAttribute("data-gpu-id", id);
        const top = document.createElement("div");
        top.style.display = "flex";
        top.style.gap = "8px";
        top.style.alignItems = "center";
        top.style.justifyContent = "space-between";
        const left = document.createElement("label");
        left.style.display = "inline-flex";
        left.style.alignItems = "center";
        left.style.gap = "8px";
        const enabled = document.createElement("input");
        enabled.type = "checkbox";
        enabled.checked = Boolean(row.checked);
        enabled.addEventListener("change", () => {
          pct.disabled = !enabled.checked;
          refreshHidden();
        });
        const name = document.createElement("span");
        name.textContent = idToLabel.get(id) || `GPU ${id} (saved)`;
        left.appendChild(enabled);
        left.appendChild(name);
        const pct = document.createElement("input");
        pct.type = "number";
        pct.step = "0.1";
        pct.min = "0";
        pct.max = "100";
        pct.placeholder = "percent";
        pct.value = row.pct > 0 ? String(row.pct) : "";
        pct.disabled = !enabled.checked;
        pct.addEventListener("input", refreshHidden);
        top.appendChild(left);
        top.appendChild(pct);
        line.appendChild(top);
        gpuSplitRows.appendChild(line);
      }
      refreshHidden();
    }

    function syncGpuFieldVisibility() {
      if (!supportsManagedLlamaServer) return;
      const backendMode = String(backendModeEntry?.input?.value || "").trim().toLowerCase();
      const selectionMode = String(gpuSelectionModeEntry?.input?.value || "auto").trim().toLowerCase();
      const splitMode = String(gpuSplitModeEntry?.input?.value || "layer").trim().toLowerCase();
      const isLlamaServer = backendMode === "llama_server";
      const showMainGpu = isLlamaServer && (selectionMode === "single" || selectionMode === "split");
      const showSplitMode = isLlamaServer && selectionMode === "split";
      const showSplitRows = showSplitMode && splitMode !== "none";

      if (mainGpuFormEntry?.wrap) mainGpuFormEntry.wrap.style.display = showMainGpu ? "" : "none";
      if (entriesByKey.gpu_split_mode?.wrap) entriesByKey.gpu_split_mode.wrap.style.display = showSplitMode ? "" : "none";
      if (entriesByKey.gpu_split_devices?.wrap) entriesByKey.gpu_split_devices.wrap.style.display = showSplitRows ? "" : "none";
      if (entriesByKey.gpu_split_percent?.wrap) entriesByKey.gpu_split_percent.wrap.style.display = "none";
      if (gpuSplitPanel) gpuSplitPanel.style.display = showSplitRows ? "" : "none";
      if (showSplitRows) renderGpuSplitRows();
    }

    if (backendModeEntry?.input instanceof HTMLElement) {
      backendModeEntry.input.addEventListener("change", () => {
        void syncManagedMainGpuChoices();
        syncGpuFieldVisibility();
      });
    }
    if (mainGpuEntry?.input instanceof HTMLElement) {
      mainGpuEntry.input.addEventListener("change", () => {
        preferredMainGpuValue = String(mainGpuEntry?.input?.value || "").trim();
      });
    }
    if (gpuSelectionModeEntry?.input instanceof HTMLElement) {
      gpuSelectionModeEntry.input.addEventListener("change", () => {
        syncGpuFieldVisibility();
      });
    }
    if (gpuSplitModeEntry?.input instanceof HTMLElement) {
      gpuSplitModeEntry.input.addEventListener("change", () => {
        syncGpuFieldVisibility();
      });
    }
    const imageBackendEntry = typeId === "image_gen" ? entries.find((e) => e.key === "backend") : null;
    if (imageBackendEntry?.input instanceof HTMLElement) {
      imageBackendEntry.input.addEventListener("change", () => {
        syncImageGenBackendVisibility();
      });
    }
    syncImageGenBackendVisibility();

    const customWrap = document.createElement("div");
    customWrap.className = "md-card";
    const customTitle = document.createElement("div");
    customTitle.textContent = "Custom settings (JSON)";
    customTitle.style.fontWeight = "600";
    const customArea = document.createElement("textarea");
    customArea.rows = 6;
    customArea.placeholder = "{\"extra_key\": \"value\"}";
    customWrap.appendChild(customTitle);
    customWrap.appendChild(customArea);

    function shouldShowCustom() {
      if (typeId === "text_llm" || typeId === "vlm") return true;
      if (typeId === "image_gen") {
        const backend = entries.find((e) => e.key === "backend")?.input?.value;
        return String(backend || "").toLowerCase() === "diffusers";
      }
      return false;
    }

    const knownKeys = new Set(entries.map((e) => e.key));
    if (model?.settings && typeof model.settings === "object") {
      const extra = {};
      for (const [k, v] of Object.entries(model.settings)) {
        if (!knownKeys.has(k)) extra[k] = v;
      }
      if (Object.keys(extra).length) {
        customArea.value = JSON.stringify(extra, null, 2);
      }
    }
    customWrap.style.display = shouldShowCustom() ? "block" : "none";
    entries.forEach((entry) => {
      if (entry.key === "backend") {
        entry.input.addEventListener("change", () => {
          customWrap.style.display = shouldShowCustom() ? "block" : "none";
        });
      }
    });

    modal.body.appendChild(form);
    modal.body.appendChild(settingsWrap);
    modal.body.appendChild(customWrap);

    function normalizeManagedServerUrlForCompare(value) {
      const raw = String(value || "").trim().replace(/\/+$/, "");
      if (!raw) return "";
      try {
        const url = new URL(raw);
        let host = String(url.hostname || "").trim().toLowerCase();
        if (["localhost", "0.0.0.0", "host.docker.internal", "::1"].includes(host)) host = "127.0.0.1";
        const port = url.port || (url.protocol === "https:" ? "443" : "80");
        return `${String(url.protocol || "http:").toLowerCase()}//${host}:${port}`;
      } catch (_err) {
        return raw.toLowerCase();
      }
    }

    function findManagedServerIdByUrl(value) {
      const target = normalizeManagedServerUrlForCompare(_rewriteClientUrl(String(value || "").trim()));
      if (!target) return "";
      for (const server of managedServers) {
        const urls = [
          server?.llmloader_url,
          server?.url,
          server?.port ? `http://${server?.host || "127.0.0.1"}:${server.port}` : "",
        ].map((url) => normalizeManagedServerUrlForCompare(_rewriteClientUrl(String(url || "").trim())));
        if (urls.includes(target)) return String(server?.id || "").trim();
      }
      return "";
    }

    function populateManagedServerPicker() {
      if (!managedServerPicker || !llamaServerUrlEntry) return;
      const currentUrl = _rewriteClientUrl(String(llamaServerUrlEntry.input?.value || "").trim());
      managedServerPicker.innerHTML = "";
      const blank = document.createElement("option");
      blank.value = "";
      blank.textContent = managedServers.length ? "Choose managed server..." : "No managed servers found";
      managedServerPicker.appendChild(blank);
      let matchedCurrent = false;
      for (const server of managedServers) {
        const url = _rewriteClientUrl(String(server.llmloader_url || server.url || "").trim());
        if (!url) continue;
        const option = document.createElement("option");
        option.value = url;
        option.dataset.serverId = String(server.id || "");
        option.textContent = `${server.name || server.id} (${server.runtime_id || "server"}, ${server.running ? "running" : "stopped"}) - ${url}`;
        if (url === currentUrl) {
          matchedCurrent = true;
          selectedManagedServerId = String(server.id || selectedManagedServerId || "");
        }
        managedServerPicker.appendChild(option);
      }
      if (currentUrl && !matchedCurrent) {
        const option = document.createElement("option");
        option.value = currentUrl;
        option.textContent = `Current custom URL - ${currentUrl}`;
        managedServerPicker.appendChild(option);
      }
      if (currentUrl) managedServerPicker.value = currentUrl;
      if (managedServerHint) {
        managedServerHint.textContent = managedServers.length
          ? "Select a host-managed llama-server or enter a URL manually above."
          : "No managed servers are cached yet. You can still enter a URL manually above.";
      }
    }

    populateManagedServerPicker();
    void (async () => {
      try {
        await loadWorkflowTrainingArtifacts();
        const resolved = await managedServerPromise;
        managedServers.splice(0, managedServers.length, ...(Array.isArray(resolved) ? resolved : []));
        populateManagedServerPicker();
        addWorkflowTrainingPickers();
        await syncManagedMainGpuChoices();
        installMainGpuPickerFromChoices(currentGpuChoices());
        renderGpuSplitRows();
        syncGpuFieldVisibility();
      } catch (_err) {
        if (managedServerHint) {
          managedServerHint.textContent = "Managed server lookup failed. You can still enter a URL manually above.";
        }
      }
    })();
      if (!(supportsManagedLlamaServer)) {
      void (async () => {
        await loadWorkflowTrainingArtifacts();
        addWorkflowTrainingPickers();
        syncLoraFieldVisibility();
      })();
    }
    const loraAdapterEntry = entriesByKey["lora_adapter_path"];
    if (loraAdapterEntry?.input && typeof loraAdapterEntry.input.addEventListener === "function") {
      loraAdapterEntry.input.addEventListener("input", syncLoraFieldVisibility);
      loraAdapterEntry.input.addEventListener("change", syncLoraFieldVisibility);
    }
    installMainGpuPickerFromChoices(currentGpuChoices());
    syncGpuFieldVisibility();
    syncLoraFieldVisibility();

    modal.open(async () => {
      const mid = modelIdField.input.value.trim();
      if (!mid) {
        alert("Model ID is required.");
        return false;
      }
      const loaderId = loaderField.input.value.trim();
      if (!loaderId) {
        alert("Loader is required.");
        return false;
      }
      const settings = {};
      for (const entry of entries) {
        if (typeId === "image_gen" && entry.wrap && entry.wrap.style.display === "none") continue;
        const val = readFieldValue(entry.type, entry.input);
        if (val !== undefined) settings[entry.key] = val;
      }
      if (supportsManagedLlamaServer) {
        const backendMode = String(settings.backend_mode || "").trim().toLowerCase();
        if (backendMode === "llama_server" && typeof settings.llama_server_url === "string") {
          settings.llama_server_url = _rewriteClientUrl(settings.llama_server_url);
        }
        const matchedManagedServerId = backendMode === "llama_server"
          ? findManagedServerIdByUrl(settings.llama_server_url)
          : "";
        if (backendMode === "llama_server" && (matchedManagedServerId || selectedManagedServerId)) {
          settings.llama_server_managed_id = matchedManagedServerId || selectedManagedServerId;
        } else {
          delete settings.llama_server_managed_id;
        }
      }
      if (customWrap.style.display !== "none" && customArea.value.trim()) {
        let extra = {};
        try {
          extra = JSON.parse(customArea.value.trim());
        } catch (err) {
          alert(`Custom settings JSON error: ${err.message || err}`);
          return false;
        }
        if (extra && typeof extra === "object" && !Array.isArray(extra)) {
          Object.assign(settings, extra);
        }
      }
      const requiredErrors = [];
      for (const field of fields) {
        if (!field || typeof field !== "object") continue;
        if (!field.required) continue;
        const key = String(field.key || "").trim();
        if (!key) continue;
        const value = settings[key];
        if (value === undefined || value === null || value === "") {
          requiredErrors.push(field.label || key);
        }
      }
      if (requiredErrors.length) {
        alert(`Missing required fields:\n${requiredErrors.join("\n")}`);
        return false;
      }
      await apiJson(ctx, "/v1/model_deck/model/upsert", {
        method: "POST",
        body: {
          type_id: typeId,
          model: {
            model_id: mid,
            loader_id: loaderId,
            settings,
            lazy: lazyField.input.checked,
            persist: persistField.input.checked,
            tags: [],
          },
        },
      });
      await reloadAll();
      return true;
    });
  }

  function consumeNavRequestIfAny() {
    const req = deckNavRequest;
    if (!req) return;
    deckNavRequest = null;
    if (req.action === "open") {
      setActiveTab("overview");
      return;
    }
    if (req.action !== "edit-model") return;
    const typeId = String(req.typeId || "").trim();
    const modelId = String(req.modelId || "").trim();
    const types = state.deck?.types || {};
    if (typeId && types[typeId]) state.activeTypeId = typeId;
    setActiveTab("models");
    renderModels();
    const t = state.deck?.types?.[state.activeTypeId];
    const models = Array.isArray(t?.models) ? t.models : [];
    const found = modelId ? models.find((m) => String(m?.model_id || "") === modelId) : null;
    if (found) {
      void openModelEditor(state.activeTypeId, found);
    }
  }

  async function promptCustomType() {
    const modal = createModal("Add custom model type");
    const typeField = createTextField("Type ID", "");
    const labelField = createTextField("Label", "");
    const notesField = createTextArea("Notes", "");
    modal.body.appendChild(typeField.wrap);
    modal.body.appendChild(labelField.wrap);
    modal.body.appendChild(notesField.wrap);
    let result = null;
    await modal.open(async () => {
      const typeId = typeField.input.value.trim();
      if (!typeId) {
        alert("Type ID is required.");
        return false;
      }
      result = {
        typeId,
        label: labelField.input.value.trim() || typeId,
        notes: notesField.input.value.trim(),
      };
      return true;
    });
    return result;
  }

  function createModal(title) {
    const overlay = document.createElement("div");
    overlay.className = "router-modal";
    overlay.style.zIndex = "2147483646";
    overlay.dataset.modelDeckModal = "1";
    const card = document.createElement("div");
    card.className = "router-modal-card";
    card.style.position = "relative";
    card.style.zIndex = "2147483647";
    overlay.appendChild(card);
    const header = document.createElement("div");
    header.className = "section-header";
    const titleEl = document.createElement("div");
    titleEl.className = "modal-title";
    titleEl.textContent = title || "Dialog";
    header.appendChild(titleEl);
    const closeBtn = document.createElement("button");
    closeBtn.className = "ghost";
    closeBtn.textContent = "Close";
    header.appendChild(closeBtn);
    card.appendChild(header);
    const body = document.createElement("div");
    body.className = "router-modal-body";
    card.appendChild(body);
    const actions = document.createElement("div");
    actions.className = "router-modal-actions";
    const saveBtn = document.createElement("button");
    saveBtn.className = "primary";
    saveBtn.textContent = "Save";
    const cancelBtn = document.createElement("button");
    cancelBtn.className = "ghost";
    cancelBtn.textContent = "Cancel";
    actions.appendChild(cancelBtn);
    actions.appendChild(saveBtn);
    card.appendChild(actions);
    const mount = moveNodeIntoChatPortal(overlay) || resolveOverlayMount(ctx);
    mount.appendChild(overlay);
    // Force the modal into the shared embed portal after mount so it does not
    // remain attached to <body> when the plugin is used from embed chat flows.
    requestAnimationFrame(() => {
      moveNodeIntoChatPortal(overlay);
    });
    const api = {
      body,
      open: async (onSave) => {
        return new Promise((resolve) => {
          function close() {
            overlay.remove();
            resolve(false);
          }
          closeBtn.addEventListener("click", close);
          cancelBtn.addEventListener("click", close);
          overlay.addEventListener("click", (event) => {
            if (event.target === overlay) close();
          });
          saveBtn.addEventListener("click", async () => {
            if (typeof onSave === "function") {
              const ok = await onSave();
              if (ok === false) return;
            }
            overlay.remove();
            resolve(true);
          });
        });
      },
    };
    return api;
  }

  function createTextField(label, value) {
    const wrap = document.createElement("label");
    wrap.className = "field";
    const title = document.createElement("span");
    title.textContent = label;
    const input = document.createElement("input");
    input.type = "text";
    input.value = value ?? "";
    wrap.appendChild(title);
    wrap.appendChild(input);
    return { wrap, input };
  }

  function createTextArea(label, value) {
    const wrap = document.createElement("label");
    wrap.className = "field";
    const title = document.createElement("span");
    title.textContent = label;
    const input = document.createElement("textarea");
    input.rows = 4;
    input.value = value ?? "";
    wrap.appendChild(title);
    wrap.appendChild(input);
    return { wrap, input };
  }

  function createSelectField(label, options, value) {
    const wrap = document.createElement("label");
    wrap.className = "field";
    const title = document.createElement("span");
    title.textContent = label;
    const input = document.createElement("select");
    input.className = "plugin-search-input";
    for (const opt of options || []) {
      const option = document.createElement("option");
      option.value = opt.value;
      option.textContent = opt.label || opt.value;
      input.appendChild(option);
    }
    if (value !== undefined && value !== null) input.value = String(value);
    wrap.appendChild(title);
    wrap.appendChild(input);
    return { wrap, input };
  }

  function createCheckboxField(label, value) {
    const wrap = document.createElement("label");
    wrap.className = "field";
    const title = document.createElement("span");
    title.textContent = label;
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = Boolean(value);
    wrap.appendChild(title);
    wrap.appendChild(input);
    return { wrap, input };
  }

  function createSchemaField(label, type, field, value) {
    const wrap = document.createElement("label");
    wrap.className = "field";
    const title = document.createElement("span");
    title.textContent = label;
    wrap.appendChild(title);
    const allowAuto = Boolean(field?.allow_auto) && (type === "int" || type === "integer" || type === "float" || type === "number");
    let input;
    if (allowAuto) {
      const row = document.createElement("div");
      row.className = "md-auto-field";
      const mode = document.createElement("select");
      mode.className = "plugin-search-input";
      const autoOpt = document.createElement("option");
      autoOpt.value = "auto";
      autoOpt.textContent = "Auto";
      const manualOpt = document.createElement("option");
      manualOpt.value = "manual";
      manualOpt.textContent = "Manual";
      mode.appendChild(autoOpt);
      mode.appendChild(manualOpt);
      const num = document.createElement("input");
      num.type = "number";
      num.step = type === "int" || type === "integer" ? "1" : "any";
      const isManual = value !== undefined && value !== null && value !== "";
      mode.value = isManual ? "manual" : "auto";
      if (isManual) num.value = String(value);
      num.disabled = !isManual;
      mode.addEventListener("change", () => {
        const manual = mode.value === "manual";
        num.disabled = !manual;
        if (!manual) num.value = "";
      });
      row.appendChild(mode);
      row.appendChild(num);
      wrap.appendChild(row);
      input = { mode, value: num, allowAuto: true };
    } else if (type === "bool" || type === "boolean") {
      input = document.createElement("input");
      input.type = "checkbox";
      input.checked = Boolean(value);
    } else if (type === "int" || type === "integer") {
      input = document.createElement("input");
      input.type = "number";
      input.step = "1";
      if (value !== undefined && value !== null && value !== "") input.value = String(value);
    } else if (type === "float" || type === "number") {
      input = document.createElement("input");
      input.type = "number";
      input.step = "any";
      if (value !== undefined && value !== null && value !== "") input.value = String(value);
    } else if (type === "enum" || type === "select") {
      input = document.createElement("select");
      input.className = "plugin-search-input";
      const opts = Array.isArray(field.options || field.choices) ? field.options || field.choices : [];
      for (const opt of opts) {
        const option = document.createElement("option");
        if (opt && typeof opt === "object") {
          option.value = String(opt.value ?? "");
          option.textContent = String(opt.label ?? opt.value ?? "");
        } else {
          option.value = String(opt);
          option.textContent = String(opt);
        }
        input.appendChild(option);
      }
      if (value !== undefined && value !== null) input.value = String(value);
    } else {
      input = document.createElement("input");
      input.type = "text";
      if (value !== undefined && value !== null && value !== "") input.value = String(value);
    }
    const titleText = String(field.description || field.help || "");
    if (titleText) {
      if (input instanceof HTMLElement) input.title = titleText;
      else if (input?.value instanceof HTMLElement) input.value.title = titleText;
    }
    if (input instanceof HTMLElement) wrap.appendChild(input);
    return { wrap, input };
  }

  function readFieldValue(type, input) {
    if (!input) return undefined;
    if (input.allowAuto) {
      if (input.mode?.value !== "manual") return undefined;
      input = input.value;
    }
    if (type === "bool" || type === "boolean") return Boolean(input.checked);
    if (type === "int" || type === "integer") {
      if (!input.value) return undefined;
      const parsed = parseInt(input.value, 10);
      return Number.isNaN(parsed) ? undefined : parsed;
    }
    if (type === "float" || type === "number") {
      if (!input.value) return undefined;
      const parsed = parseFloat(input.value);
      return Number.isNaN(parsed) ? undefined : parsed;
    }
    if (input.value === "") return undefined;
    return input.value;
  }

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function startProcessStream() {
    if (processStream.controller) return;
    const token = ++processStream.token;
    const run = async () => {
      let backoff = 400;
      while (processStream.token === token) {
        const controller = new AbortController();
        processStream.controller = controller;
        try {
          await ctx.streamSSE("/v1/gui/events/stream?prefix=processes", {
            headers: buildPluginHeaders(ctx),
            signal: controller.signal,
            onEvent: () => {
              if (processStream.token !== token) return;
              void refreshProcesses();
            },
          });
        } catch (_err) {
          if (controller.signal.aborted) break;
        } finally {
          if (processStream.controller === controller) {
            processStream.controller = null;
          }
        }
        if (processStream.token !== token) break;
        await delay(backoff);
        backoff = Math.min(Math.round(backoff * 1.6), 8000);
      }
    };
    void run();
  }

  setActiveTab("overview");
  const cachedBootstrap = cacheGet(ctx, CACHE_KEY_EDITOR_BOOTSTRAP);
  if (cachedBootstrap && typeof cachedBootstrap === "object") {
    applyEditorBootstrap(cachedBootstrap);
    statusLabel.textContent = "Cached";
  }
  void reloadAll().then(() => consumeNavRequestIfAny());
  startProcessStream();
}

const plugin = {
  id: meta.plugin_id,
  name: meta.name,
  kind: meta.kind,
  description: meta.description,
  meta,
  register(host) {
    deckState.host = host;
    host.addPanelTab({
      id: meta.plugin_id,
      title: meta.name,
      windowType: "full",
      render: (container, ctx) => {
        renderPanel(container, ctx);
      },
    });
    host.addTopRightIconRow((ctx) => {
      // Share model context even for non-admins (no icon shown, but shared object is still useful).
      ensureModelInfoPolling(host, ctx);
      return buildDeckButton(ctx);
    });
    deckOutsideHandler = (event) => {
      if (!deckOpen) return;
      if (!deckPopover || !deckButton) return;
      if (deckPopover.contains(event.target) || deckButton.contains(event.target)) return;
      closeDeckPopover();
    };
    document.addEventListener("click", deckOutsideHandler);
    window.addEventListener("resize", positionDeckPopover);
    window.addEventListener("scroll", positionDeckPopover, { passive: true });
  },
  dispose() {
    if (processStream.controller) {
      try {
        processStream.controller.abort();
      } catch (_err) {
        // ignore
      }
      processStream.controller = null;
    }
    processStream.token += 1;
    stopDeckPolling();
    closeDeckPopover();
    if (deckOutsideHandler) {
      document.removeEventListener("click", deckOutsideHandler);
      deckOutsideHandler = null;
    }
    window.removeEventListener("resize", positionDeckPopover);
    window.removeEventListener("scroll", positionDeckPopover);
    if (modelInfoTimer) {
      clearInterval(modelInfoTimer);
      modelInfoTimer = null;
    }
    if (deckButton && deckButton.remove) deckButton.remove();
    deckButton = null;
    deckBadge = null;
  },
};

export default plugin;
