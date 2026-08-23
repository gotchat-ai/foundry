const meta = {
  plugin_id: "llama_server_manager",
  name: "Llama Server",
  kind: "plugin",
  description: "Manage host-side llama.cpp server runtimes and processes.",
  has_notebook_tab: false,
};

const STYLE_ID = "llama-server-manager-style";
const DEFAULT_TAG = "latest";
const CLIENT_MODE_KEY = "llama_server_client_service_mode";
const CLIENT_MODE_MANUAL_KEY = "llama_server_client_service_mode_manual";
const CLIENT_TOKEN_KEY = "llama_server_client_service_token";
const STATUS_CACHE_KEY = "llama_server_manager_status_cache";
const RELEASE_TAG_KEY = "llama_server_manager_release_tag";
const LLAMA_MANAGER_PORT = "8767";
const LIVE_STATUS_TTL_MS = 5000;
const DEVICE_PROBE_TTL_MS = 15000;

let liveStatusPayload = null;
let liveStatusFetchedAt = 0;
let liveStatusInflight = null;
const deviceProbeCache = new Map();

function deepClone(value) {
  try {
    return JSON.parse(JSON.stringify(value));
  } catch (_err) {
    return value;
  }
}

function getClientMode() {
  try {
    const raw = String(window.localStorage.getItem(CLIENT_MODE_KEY) || "").trim().toLowerCase();
    const manual = window.localStorage.getItem(CLIENT_MODE_MANUAL_KEY) === "1";
    if (raw === "docker" && isLocalBrowser() && !manual) return "local";
    if (raw === "local" || raw === "docker") return raw;
    return isLocalBrowser() ? "local" : "docker";
  } catch (_err) {
    return isLocalBrowser() ? "local" : "docker";
  }
}

function setClientMode(mode) {
  try {
    window.localStorage.setItem(CLIENT_MODE_KEY, mode === "local" ? "local" : "docker");
    window.localStorage.setItem(CLIENT_MODE_MANUAL_KEY, "1");
  } catch (_err) {}
}

function getClientToken() {
  try {
    return String(window.localStorage.getItem(CLIENT_TOKEN_KEY) || "").trim();
  } catch (_err) {
    return "";
  }
}

function setClientToken(token) {
  try {
    window.localStorage.setItem(CLIENT_TOKEN_KEY, String(token || "").trim());
  } catch (_err) {}
}

function getStatusCache() {
  try {
    const raw = window.localStorage.getItem(STATUS_CACHE_KEY) || "";
    const parsed = raw ? JSON.parse(raw) : null;
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch (_err) {
    return null;
  }
}

function setStatusCache(payload) {
  try {
    window.localStorage.setItem(STATUS_CACHE_KEY, JSON.stringify(payload || {}));
  } catch (_err) {}
  liveStatusPayload = deepClone(payload || {});
  liveStatusFetchedAt = Date.now();
}

function getReleaseTag() {
  try {
    const raw = String(window.localStorage.getItem(RELEASE_TAG_KEY) || "").trim();
    return raw || DEFAULT_TAG;
  } catch (_err) {
    return DEFAULT_TAG;
  }
}

function setReleaseTag(tag) {
  try {
    const value = String(tag || "").trim() || DEFAULT_TAG;
    window.localStorage.setItem(RELEASE_TAG_KEY, value);
  } catch (_err) {}
}

function embedCfg() {
  try {
    return typeof window !== "undefined" ? (window.__CHAT_JS_EMBED_CONFIG || {}) : {};
  } catch (_err) {
    return {};
  }
}

function trimSlash(value) {
  return String(value || "").trim().replace(/\/+$/, "");
}

function localClientServiceBase() {
  return `http://localhost:${LLAMA_MANAGER_PORT}`;
}

function dockerClientServiceBase() {
  return `http://host.docker.internal:${LLAMA_MANAGER_PORT}`;
}

function rewriteClientUrl(urlText, mode = getClientMode()) {
  const raw = trimSlash(urlText);
  if (!raw) return "";
  try {
    const url = new URL(raw);
    const host = String(url.hostname || "").trim().toLowerCase();
    if (mode === "local") {
      if (host === "host.docker.internal") url.hostname = "localhost";
      return trimSlash(url.toString());
    }
    if (["localhost", "127.0.0.1", "::1"].includes(host)) url.hostname = "host.docker.internal";
    return trimSlash(url.toString());
  } catch (_err) {
    return mode === "local"
      ? raw.replace(/host\.docker\.internal/gi, "localhost")
      : raw.replace(/\blocalhost\b|127\.0\.0\.1|::1/gi, "host.docker.internal");
  }
}

function isFrontendServiceUrl(urlText) {
  const raw = trimSlash(urlText);
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

function isUsableLlamaManagerUrl(urlText) {
  const raw = trimSlash(urlText);
  return Boolean(raw && !isFrontendServiceUrl(raw));
}

function isLikelyLlamaManagerUrl(urlText) {
  const raw = trimSlash(urlText);
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

function isLocalBrowser() {
  if (typeof window === "undefined" || !window.location) return false;
  const host = String(window.location.hostname || "").trim().toLowerCase();
  return host === "localhost" || host === "127.0.0.1" || host === "::1";
}

function browserHostOs() {
  try {
    const platform = String(navigator.userAgentData?.platform || navigator.platform || navigator.userAgent || "").toLowerCase();
    if (platform.includes("win")) return "windows";
    if (platform.includes("mac")) return "macos";
    if (platform.includes("linux")) return "linux";
    if (platform.includes("android")) return "android";
    if (platform.includes("iphone") || platform.includes("ipad") || platform.includes("ios")) return "ios";
  } catch (_err) {}
  return "unknown";
}

function defaultManagedServerPort() {
  const hostOs = browserHostOs();
  if (hostOs === "linux" || hostOs === "android" || hostOs === "macos" || hostOs === "ios") {
    return "8085";
  }
  return "8080";
}

function localHostServiceCommands() {
  const hostOs = browserHostOs();
  if (hostOs === "linux" || hostOs === "android") {
    return {
      start: "./llama_server/start_host_service.sh start",
      restart: "./llama_server/start_host_service.sh restart",
      note: "Run these from the project root on the Linux host.",
    };
  }
  if (hostOs === "macos" || hostOs === "ios") {
    return {
      start: "./llama_server/start_host_service.sh start",
      restart: "./llama_server/start_host_service.sh restart",
      note: "Run these from the project root on the host machine.",
    };
  }
  return {
    start: ".\\llama_server\\start_host_service.ps1 -Action start",
    restart: ".\\llama_server\\start_host_service.ps1 -Action restart",
    note: "Run these from the project root in PowerShell.",
  };
}

function hostViewForMode(host) {
  const src = host && typeof host === "object" ? host : {};
  if (getClientMode() !== "local" || !isLocalBrowser()) return src;
  if (src.host_os || (Array.isArray(src.runtimes) && src.runtimes.length) || (Array.isArray(src.gpu_names) && src.gpu_names.length)) {
    return src;
  }
  const hostOs = browserHostOs();
  const runtime = (id, label, compatible, reason) => ({ id, label, compatible, reason });
  return {
    host_os: hostOs,
    arch: "browser",
    gpu_names: [],
    runtimes: [
      runtime("cpu", "CPU", true, `Supported on ${hostOs}.`),
      runtime("vulkan", "Vulkan", hostOs === "windows" || hostOs === "linux", "Requires a Vulkan-capable GPU on Windows or Linux."),
      runtime("sycl", "SYCL", hostOs === "windows" || hostOs === "linux", "Requires Intel oneAPI/SYCL support on Windows or Linux."),
      runtime("cuda", "CUDA", hostOs === "windows" || hostOs === "linux", "Requires an NVIDIA GPU on Windows or Linux."),
    ],
    sriov: { compatible: false, reason: "Unavailable from browser-only detection." },
    compatibility_source: "browser",
  };
}

function inferInstallHostOs(install) {
  const row = install && typeof install === "object" ? install : {};
  const blob = [
    String(row.id || ""),
    String(row.asset_name || ""),
    String(row.archive_path || ""),
    String(row.extract_dir || ""),
    String(row.executable || ""),
  ].join(" ").toLowerCase();
  if (blob.includes("windows") || blob.includes(".exe") || /^[a-z]:\\/.test(String(row.executable || ""))) return "windows";
  if (blob.includes("linux") || blob.includes("ubuntu") || blob.includes("/home/") || blob.includes("/usr/")) return "linux";
  if (blob.includes("macos") || blob.includes("darwin") || blob.includes(".app/")) return "macos";
  return "";
}

function installsForCurrentHost(installs, host) {
  const rows = Array.isArray(installs) ? installs.slice() : [];
  const hostOs = String(host?.host_os || browserHostOs() || "").trim().toLowerCase();
  if (!hostOs) return rows;
  const direct = rows.filter((item) => {
    const installOs = inferInstallHostOs(item);
    return !installOs || installOs === hostOs;
  });
  return direct.length ? direct : rows;
}

function pickProbeInstall(installs, host) {
  const rows = installsForCurrentHost(installs, host);
  rows.sort((a, b) => Number(b?.installed_at || 0) - Number(a?.installed_at || 0));
  return (
    rows.find((x) => ["sycl", "vulkan", "cuda"].includes(String(x?.runtime_id || "").trim().toLowerCase())) ||
    rows.find((x) => String(x?.runtime_id || "").trim().toLowerCase() === "cpu") ||
    rows[0] ||
    null
  );
}

function preferredRuntimeId(host, installs) {
  const rows = installsForCurrentHost(installs, host);
  const installedIds = new Set(rows.map((x) => String(x?.runtime_id || "").trim().toLowerCase()).filter(Boolean));
  const runtimes = Array.isArray(host?.runtimes) ? host.runtimes : [];
  const compatible = new Set(
    runtimes
      .filter((x) => x && x.compatible)
      .map((x) => String(x.id || "").trim().toLowerCase())
      .filter(Boolean),
  );
  for (const id of ["vulkan", "sycl", "cuda", "cpu"]) {
    if (installedIds.has(id)) return id;
  }
  for (const id of ["vulkan", "sycl", "cuda", "cpu"]) {
    if (compatible.has(id)) return id;
  }
  return "cpu";
}

async function resolveRemoteClientServiceUrl(ctx) {
  const state = ctx?.getState?.() || {};
  const remote = state.remote || {};
  const existing = trimSlash(remote.llamaManagerUrl || "");
  if (isUsableLlamaManagerUrl(existing)) return existing;
  const fallbackClient = trimSlash(remote.clientServiceUrl || "");
  if (isUsableLlamaManagerUrl(fallbackClient) && isLikelyLlamaManagerUrl(fallbackClient)) return fallbackClient;
  const cfg = embedCfg();
  const identifierKey = String(cfg.identifierKey || cfg.identifier_key || "").trim();
  const cmsBase = trimSlash(cfg.cmsBase || cfg.cms_base || "https://account.gotchat.ai");
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
      const resolved = bestClientSvc ? trimSlash(bestClientSvc.publicUrl || `https://${toStr(bestClientSvc.hostname)}`) : "";
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
      const candidate = trimSlash(data.llamaManagerUrl || data.LlamaManagerUrl || "");
      const fallback = trimSlash(data.clientServiceUrl || data.ClientServiceUrl || "");
      const resolved = candidate || (isLikelyLlamaManagerUrl(fallback) ? fallback : "");
      if (resolved && remote && typeof remote === "object") remote.llamaManagerUrl = resolved;
      if (resolved) return resolved;
    }
  } catch (_err) {}
  try {
    const payload = await ctx.apiJson("/v1/cloudflare_docker_https/status");
    const items = Array.isArray(payload?.mappings) ? payload.mappings : [];
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
    const resolved = hinted ? trimSlash(hinted.public_url || hinted.publicUrl || (hinted.hostname ? `https://${hinted.hostname}` : "")) : "";
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

function ensureStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
.lsm-root { display:flex; flex-direction:column; gap:14px; }
.lsm-card { background:var(--panel); border:1px solid var(--border); border-radius:12px; padding:12px; display:flex; flex-direction:column; gap:10px; }
.lsm-row { display:flex; gap:10px; flex-wrap:wrap; align-items:flex-end; }
.lsm-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:10px; }
.lsm-runtime { border:1px solid var(--border); border-radius:10px; padding:10px; display:flex; flex-direction:column; gap:6px; background:color-mix(in srgb, var(--panel) 85%, white 15%); }
.lsm-ok { color:#2e9d59; font-weight:600; }
.lsm-bad { color:#d65858; font-weight:600; }
.lsm-muted { color:var(--muted); font-size:12px; }
.lsm-actions { display:flex; gap:8px; flex-wrap:wrap; }
.lsm-field { display:flex; flex-direction:column; gap:4px; min-width:180px; }
.lsm-field > span { font-size:12px; color:var(--muted); }
.lsm-field > input, .lsm-field > select, .lsm-field > textarea { width:100%; }
.lsm-server { border:1px solid var(--border); border-radius:10px; padding:10px; display:flex; flex-direction:column; gap:8px; }
.lsm-server-title { display:flex; justify-content:space-between; gap:12px; align-items:center; }
.lsm-server-url { font-family:monospace; font-size:12px; word-break:break-all; }
.lsm-pre { background:rgba(0,0,0,0.18); border:1px solid var(--border); border-radius:8px; padding:10px; white-space:pre-wrap; max-height:260px; overflow:auto; font-family:monospace; font-size:12px; }
.lsm-details { border:1px dashed var(--border); border-radius:10px; padding:8px 10px; }
.lsm-details > summary { cursor:pointer; color:var(--muted); font-size:12px; user-select:none; }
.lsm-busy { position:relative; }
.lsm-busy::after { content:""; width:12px; height:12px; margin-left:8px; border:2px solid currentColor; border-top-color:transparent; border-radius:50%; display:inline-block; vertical-align:-2px; animation:lsm-spin 0.8s linear infinite; }
.lsm-code { font-family:monospace; font-size:12px; background:rgba(0,0,0,0.16); border:1px solid var(--border); border-radius:8px; padding:8px 10px; white-space:pre-wrap; word-break:break-word; }
@keyframes lsm-spin { to { transform: rotate(360deg); } }
  `;
  document.head.appendChild(style);
}

function clientServiceBase(ctx) {
  const state = ctx?.getState?.() || {};
  const remote = state.remote || {};
  const llamaOverride = String(remote.llamaManagerUrl || "").trim().replace(/\/+$/, "");
  const clientFallback = String(remote.clientServiceUrl || "").trim().replace(/\/+$/, "");
  const rawOverride = llamaOverride || (isLikelyLlamaManagerUrl(clientFallback) ? clientFallback : "");
  const override = isUsableLlamaManagerUrl(rawOverride) ? rewriteClientUrl(rawOverride) : "";
  const mode = getClientMode();
  if (override) return override;
  if (mode === "docker" && !isLocalBrowser()) return "";
  return mode === "local" ? localClientServiceBase() : dockerClientServiceBase();
}

function authTokenFromCtx(ctx) {
  return String(
    ctx?.state?.auth?.token ||
    ctx?.getState?.()?.auth?.token ||
    ""
  ).trim();
}

async function clientJson(ctx, path, options = {}) {
  if (typeof ctx?.apiJson === "function") {
    try {
      return await ctx.apiJson(path, options);
    } catch (err) {
      const msg = String(err?.message || err || "");
      const status = Number(err?.status || 0);
      const isMissingRoute = status === 404 || /404/.test(msg) || /not found/i.test(msg);
      if (!isMissingRoute) throw err;
    }
  }
  let base = clientServiceBase(ctx);
  if (!base) {
    base = rewriteClientUrl(await resolveRemoteClientServiceUrl(ctx), "docker");
  }
  if (!base) {
    throw new Error("Llama host service URL could not be resolved for the selected mode.");
  }
  const method = options.method || "GET";
  const headers = { ...(options.headers || {}) };
  const token = authTokenFromCtx(ctx);
  if (token) headers.Authorization = `Bearer ${token}`;
  const shared = getClientToken();
  if (shared) headers["X-Client-Service-Token"] = shared;
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

async function ensureSharedToken(ctx) {
  const current = getClientToken();
  if (current) return current;
  try {
    const payload = await clientJson(ctx, "/v1/llama_server/token", { headers: {} });
    const resolved = String(payload?.token || "").trim();
    if (resolved) setClientToken(resolved);
    return resolved;
  } catch (_err) {
    return "";
  }
}

async function fetchDeviceProbe(ctx, installId) {
  const key = String(installId || "").trim();
  if (!key) return null;
  const now = Date.now();
  const cached = deviceProbeCache.get(key);
  if (cached && (now - Number(cached.fetchedAt || 0)) < DEVICE_PROBE_TTL_MS) {
    return deepClone(cached.payload);
  }
  if (cached?.promise) {
    return deepClone(await cached.promise);
  }
  const promise = (async () => {
    const payload = await clientJson(
      ctx,
      `/v1/llama_server/devices?install_id=${encodeURIComponent(key)}`,
      { headers: {} },
    );
    deviceProbeCache.set(key, { payload: deepClone(payload), fetchedAt: Date.now(), promise: null });
    return payload;
  })().catch((err) => {
    deviceProbeCache.delete(key);
    throw err;
  });
  deviceProbeCache.set(key, { payload: cached?.payload || null, fetchedAt: Number(cached?.fetchedAt || 0), promise });
  return deepClone(await promise);
}

async function fetchLiveStatus(ctx, { force = false } = {}) {
  const now = Date.now();
  if (!force && liveStatusPayload && (now - liveStatusFetchedAt) < LIVE_STATUS_TTL_MS) {
    return deepClone(liveStatusPayload);
  }
  if (!force && liveStatusInflight) {
    return deepClone(await liveStatusInflight);
  }
  liveStatusInflight = (async () => {
    const payload = await clientJson(ctx, "/v1/llama_server/status");
    const probeInstall = pickProbeInstall(payload.installs || [], payload.host || {});
    if (probeInstall?.id) {
      try {
        const probe = await fetchDeviceProbe(ctx, probeInstall.id);
        const lines = Array.isArray(probe?.devices) ? probe.devices : Array.isArray(probe?.lines) ? probe.lines : [];
        if (lines.length) {
          payload.host = {
            ...(payload.host || {}),
            gpu_names: lines,
            device_probe_source: String(probe?.source || ""),
          };
        }
      } catch (_err) {}
    }
    setStatusCache(payload);
    return deepClone(payload);
  })().finally(() => {
    liveStatusInflight = null;
  });
  return deepClone(await liveStatusInflight);
}

function field(label, input) {
  const wrap = document.createElement("label");
  wrap.className = "lsm-field";
  const span = document.createElement("span");
  span.textContent = label;
  wrap.appendChild(span);
  wrap.appendChild(input);
  return wrap;
}

function button(label, onClick, kind = "ghost") {
  const btn = document.createElement("button");
  btn.className = kind === "primary" ? "primary" : "ghost";
  btn.type = "button";
  btn.textContent = label;
  btn.addEventListener("click", async () => {
    if (btn.disabled) return;
    btn.disabled = true;
    btn.classList.add("lsm-busy");
    try {
      await onClick();
    } finally {
      btn.disabled = false;
      btn.classList.remove("lsm-busy");
    }
  });
  return btn;
}

function renderPanel(container, ctx) {
  ensureStyles();
  container.innerHTML = "";

  const root = document.createElement("div");
  root.className = "lsm-root";
  container.appendChild(root);

  const status = document.createElement("div");
  status.className = "lsm-muted";
  root.appendChild(status);

  const hostCard = document.createElement("div");
  hostCard.className = "lsm-card";
  root.appendChild(hostCard);

  const runtimesCard = document.createElement("div");
  runtimesCard.className = "lsm-card";
  root.appendChild(runtimesCard);

  const serversCard = document.createElement("div");
  serversCard.className = "lsm-card";
  root.appendChild(serversCard);

  function setStatus(text) {
    status.textContent = text || "";
  }

  function renderPayload(payload, { note = "" } = {}) {
    const data = payload && typeof payload === "object" ? payload : {};
    const effectiveHost = hostViewForMode(data.host || {});
    renderHost(effectiveHost);
    renderRuntimes(effectiveHost, data.installs || []);
    renderServers(data.servers || [], data.installs || [], effectiveHost);
    if (note) setStatus(note);
  }

  function renderHostServiceOfflineHelp(message, route = "") {
    const text = String(message || "").trim();
    const timedOut = /timed out|timeout/i.test(text);
    const titleText = timedOut
      ? "Host llama service responded, but status polling timed out"
      : "Host llama service is not running";
    const cmds = localHostServiceCommands();
    const noteText = timedOut
      ? "The route resolved, but the manager status request took too long. The service may be up while live status is overloaded."
      : "Start the host-side llama manager first. The browser plugin cannot launch PowerShell directly.";
    const card = document.createElement("div");
    card.className = "lsm-card";
    const title = document.createElement("div");
    title.style.fontWeight = "600";
    title.textContent = titleText;
    card.appendChild(title);
    const note = document.createElement("div");
    note.className = "lsm-muted";
    note.textContent = noteText;
    card.appendChild(note);
    if (route) {
      const routeLine = document.createElement("div");
      routeLine.className = "lsm-muted";
      routeLine.textContent = `Route: ${route}`;
      card.appendChild(routeLine);
    }
    if (message) {
      const err = document.createElement("div");
      err.className = "lsm-bad";
      err.textContent = message;
      card.appendChild(err);
    }
    const startCmd = cmds.start;
    const restartCmd = cmds.restart;
    const startBox = document.createElement("div");
    startBox.className = "lsm-code";
    startBox.textContent = startCmd;
    const restartBox = document.createElement("div");
    restartBox.className = "lsm-code";
    restartBox.textContent = restartCmd;
    if (cmds.note) {
      const cmdNote = document.createElement("div");
      cmdNote.className = "lsm-muted";
      cmdNote.textContent = cmds.note;
      card.appendChild(cmdNote);
    }
    card.appendChild(field("Start command", startBox));
    card.appendChild(field("Restart command", restartBox));
    const actions = document.createElement("div");
    actions.className = "lsm-actions";
    actions.appendChild(button("Copy start", async () => {
      await navigator.clipboard.writeText(startCmd);
      setStatus("Copied start command.");
    }));
    actions.appendChild(button("Copy restart", async () => {
      await navigator.clipboard.writeText(restartCmd);
      setStatus("Copied restart command.");
    }));
    actions.appendChild(button("Retry", async () => {
      await reload();
    }, "primary"));
    card.appendChild(actions);
    serversCard.appendChild(card);
  }

  async function reload({ force = false } = {}) {
    const cached = getStatusCache();
    if (cached) {
      renderPayload(cached, { note: "Loading latest llama-server manager status..." });
    } else {
      setStatus("Loading llama-server manager status...");
      renderHost({});
    }
    try {
      const payload = await fetchLiveStatus(ctx, { force });
      renderPayload(payload, { note: "Ready." });
      setStatus("Ready.");
    } catch (err) {
      const message = String(err?.message || err || "Failed to load llama-server manager.");
      const route = clientServiceBase(ctx);
      if (cached) {
        renderPayload(cached, { note: "Using cached llama-server status. Live status unavailable." });
      } else {
        renderPayload({ host: {}, installs: [], servers: [] }, { note: "Llama server status could not be loaded yet." });
      }
      if (getClientMode() === "local") {
        renderHostServiceOfflineHelp(message, route);
      } else {
        const detail = document.createElement("div");
        detail.className = "lsm-bad";
        detail.textContent = message;
        serversCard.appendChild(detail);
      }
      setStatus(message);
    }
  }

  function renderHost(host) {
    const effectiveHost = hostViewForMode(host);
    hostCard.innerHTML = "";
    const title = document.createElement("div");
    title.textContent = effectiveHost.compatibility_source === "browser" ? "Local browser compatibility" : "Manager environment compatibility";
    title.style.fontWeight = "600";
    hostCard.appendChild(title);
    const infoRow = document.createElement("div");
    infoRow.className = "lsm-row";
    infoRow.style.justifyContent = "space-between";
    infoRow.style.alignItems = "flex-start";
    const info = document.createElement("div");
    info.className = "lsm-muted";
    info.textContent = `OS: ${effectiveHost.host_os || "unknown"}  |  Arch: ${effectiveHost.arch || "unknown"}`;
    infoRow.appendChild(info);
    const modeSelect = document.createElement("select");
    modeSelect.appendChild(new Option("Docker", "docker"));
    modeSelect.appendChild(new Option("Local", "local"));
    modeSelect.value = getClientMode();
    modeSelect.addEventListener("change", async () => {
      setClientMode(modeSelect.value);
      await reload({ force: true });
    });
    infoRow.appendChild(field("Route mode", modeSelect));
    hostCard.appendChild(infoRow);
    const gpu = document.createElement("div");
    gpu.className = "lsm-muted";
    gpu.textContent = `GPUs: ${(effectiveHost.gpu_names || []).join(" | ") || "none detected"}`;
    hostCard.appendChild(gpu);
    if (effectiveHost.device_probe_source) {
      const src = document.createElement("div");
      src.className = "lsm-muted";
      src.textContent = `Device probe: ${effectiveHost.device_probe_source}`;
      hostCard.appendChild(src);
    }
    const sriovReason = String(effectiveHost.sriov?.reason || "").trim();
    const suppressSriovLine = !effectiveHost.sriov?.compatible && sriovReason === "No Arc Pro B-Series GPU detected.";
    if (!suppressSriovLine) {
      const sriov = document.createElement("div");
      sriov.className = effectiveHost.sriov?.compatible ? "lsm-ok" : "lsm-muted";
      sriov.textContent = `SR-IOV: ${effectiveHost.sriov?.compatible ? "compatible" : "not compatible"}${sriovReason ? ` - ${sriovReason}` : ""}`;
      hostCard.appendChild(sriov);
    }
    if (effectiveHost.compatibility_source === "browser") {
      const note = document.createElement("div");
      note.className = "lsm-muted";
      note.textContent = "Local mode uses the browser OS for compatibility hints. GPU capability is not verified from the browser.";
      hostCard.appendChild(note);
    }

    const modeRow = document.createElement("div");
    modeRow.className = "lsm-row";
    const routeInfo = document.createElement("div");
    routeInfo.className = "lsm-muted";
    routeInfo.textContent = "Resolving client service route...";
    modeRow.appendChild(routeInfo);
    (async () => {
      try {
        let resolved = clientServiceBase(ctx);
        if (!resolved) resolved = rewriteClientUrl(await resolveRemoteClientServiceUrl(ctx), "docker");
        routeInfo.textContent = `Using ${resolved || "unresolved"}`;
        routeInfo.className = resolved ? "lsm-muted" : "lsm-bad";
      } catch (_err) {
        routeInfo.textContent = "Using unresolved llama host service route";
        routeInfo.className = "lsm-bad";
      }
    })();
    const tokenInput = document.createElement("input");
    tokenInput.type = "password";
    tokenInput.placeholder = "Optional shared token";
    tokenInput.value = getClientToken();
    tokenInput.addEventListener("change", () => {
      setClientToken(tokenInput.value);
    });
    modeRow.appendChild(field("Shared token", tokenInput));
    const tokenActions = document.createElement("div");
    tokenActions.className = "lsm-actions";
    tokenActions.appendChild(button("Load token", async () => {
      const payload = await clientJson(ctx, "/v1/llama_server/token", { headers: {} });
      const token = String(payload?.token || "").trim();
      setClientToken(token);
      tokenInput.value = token;
      setStatus("Loaded shared token from server.");
    }));
    tokenActions.appendChild(button("Rekey", async () => {
      const payload = await clientJson(ctx, "/v1/llama_server/token/rekey", { method: "POST", headers: {} });
      const token = String(payload?.token || "").trim();
      setClientToken(token);
      tokenInput.value = token;
      setStatus("Shared token rotated.");
    }, "primary"));
    modeRow.appendChild(tokenActions);
    hostCard.appendChild(modeRow);
  }

  function renderRuntimes(host, installs) {
    const effectiveHost = hostViewForMode(host);
    runtimesCard.innerHTML = "";
    const title = document.createElement("div");
    title.textContent = "Runtime downloads";
    title.style.fontWeight = "600";
    runtimesCard.appendChild(title);

    const releaseRow = document.createElement("div");
    releaseRow.className = "lsm-row";
    const tagInput = document.createElement("input");
    tagInput.type = "text";
    tagInput.value = getReleaseTag();
    tagInput.addEventListener("change", () => {
      setReleaseTag(tagInput.value);
    });
    releaseRow.appendChild(field("Release tag", tagInput));
    const note = document.createElement("div");
    note.className = "lsm-muted";
    note.textContent = "Use a llama.cpp tag like b8733 or 'latest'.";
    releaseRow.appendChild(note);
    runtimesCard.appendChild(releaseRow);

    const grid = document.createElement("div");
    grid.className = "lsm-grid";
    runtimesCard.appendChild(grid);
    const installList = Array.isArray(installs) ? installs : [];
    for (const runtime of effectiveHost.runtimes || []) {
      const card = document.createElement("div");
      card.className = "lsm-runtime";
      const head = document.createElement("div");
      head.style.fontWeight = "600";
      head.textContent = runtime.label || runtime.id;
      card.appendChild(head);
      const compat = document.createElement("div");
      compat.className = runtime.compatible ? "lsm-ok" : "lsm-bad";
      compat.textContent = runtime.compatible ? "Compatible" : "Not compatible";
      card.appendChild(compat);
      const why = document.createElement("div");
      why.className = "lsm-muted";
      why.textContent = runtime.reason || "";
      card.appendChild(why);
      const installed = installList.filter((item) => String(item.runtime_id || "") === String(runtime.id || ""));
      if (installed.length) {
        const last = installed[installed.length - 1];
        const have = document.createElement("div");
        have.className = "lsm-muted";
        have.textContent = `Installed: ${last.tag || "unknown"} (${last.asset_name || ""})`;
        card.appendChild(have);
      }
      const actions = document.createElement("div");
      actions.className = "lsm-actions";
      actions.appendChild(button("Download", async () => {
        const requestedTag = String(tagInput.value || "").trim() || DEFAULT_TAG;
        setReleaseTag(requestedTag);
        setStatus(`Downloading ${runtime.id} ${requestedTag}...`);
        await clientJson(ctx, "/v1/llama_server/install", {
          method: "POST",
          body: { runtime_id: runtime.id, tag: requestedTag },
        });
        await reload({ force: true });
      }, "primary"));
      card.appendChild(actions);
      grid.appendChild(card);
    }
  }

  function renderServers(servers, installs, host) {
    serversCard.innerHTML = "";
    const title = document.createElement("div");
    title.textContent = "Managed servers";
    title.style.fontWeight = "600";
    serversCard.appendChild(title);

    const form = document.createElement("div");
    form.className = "lsm-card";
    let editingId = "";
    const row = document.createElement("div");
    row.className = "lsm-row";
    const name = document.createElement("input");
    name.type = "text";
    let nameAuto = true;
    const runtime = document.createElement("select");
    for (const item of host.runtimes || []) runtime.appendChild(new Option(item.label || item.id, item.id));
    runtime.value = preferredRuntimeId(host, installs);
    name.value = `${runtime.value || "server"}-main`;
    name.addEventListener("input", () => {
      nameAuto = false;
    });
    const install = document.createElement("select");
    const model = document.createElement("input");
    model.type = "text";
    model.placeholder = "C:\\models\\model.gguf or D:\\models\\file.gguf";
    const port = document.createElement("input");
    port.type = "number";
    port.value = defaultManagedServerPort();
    const ctxSize = document.createElement("input");
    ctxSize.type = "number";
    const gpuLayers = document.createElement("input");
    gpuLayers.type = "number";
    const parallel = document.createElement("input");
    parallel.type = "number";
    const batch = document.createElement("input");
    batch.type = "number";
    const ubatch = document.createElement("input");
    ubatch.type = "number";
    const threads = document.createElement("input");
    threads.type = "number";
    const threadsBatch = document.createElement("input");
    threadsBatch.type = "number";
    const kvUnified = document.createElement("select");
    kvUnified.appendChild(new Option("Auto", ""));
    kvUnified.appendChild(new Option("On", "true"));
    kvUnified.appendChild(new Option("Off", "false"));
    const noHost = document.createElement("select");
    noHost.appendChild(new Option("Auto", ""));
    noHost.appendChild(new Option("On", "true"));
    noHost.appendChild(new Option("Off", "false"));
    const cacheRam = document.createElement("input");
    cacheRam.type = "number";
    cacheRam.placeholder = "0 disables prompt cache";
    const mmap = document.createElement("select");
    mmap.appendChild(new Option("Auto", ""));
    mmap.appendChild(new Option("On", "true"));
    mmap.appendChild(new Option("Off", "false"));
    const contBatching = document.createElement("select");
    contBatching.appendChild(new Option("Auto", ""));
    contBatching.appendChild(new Option("On", "true"));
    contBatching.appendChild(new Option("Off", "false"));
    const ctxCheckpoints = document.createElement("input");
    ctxCheckpoints.type = "number";
    const deviceFilter = document.createElement("input");
    deviceFilter.type = "text";
    deviceFilter.placeholder = "Optional SYCL_DEVICE_FILTER / ONEAPI_DEVICE_SELECTOR";
    const extraArgs = document.createElement("input");
    extraArgs.type = "text";
    extraArgs.placeholder = "--threads 8 --no-mmap";

    row.appendChild(field("Name", name));
    row.appendChild(field("Runtime", runtime));
    row.appendChild(field("Installed build", install));
    row.appendChild(field("Model path", model));
    row.appendChild(field("Port", port));
    form.appendChild(row);

    const more = document.createElement("details");
    more.className = "lsm-details";
    const summary = document.createElement("summary");
    summary.textContent = "More settings (optional)";
    more.appendChild(summary);
    const moreRow = document.createElement("div");
    moreRow.className = "lsm-row";
    moreRow.style.marginTop = "10px";
    moreRow.appendChild(field("Parallel slots (-np / --parallel)", parallel));
    moreRow.appendChild(field("Context size", ctxSize));
    moreRow.appendChild(field("GPU layers", gpuLayers));
    moreRow.appendChild(field("Batch size", batch));
    moreRow.appendChild(field("Micro-batch", ubatch));
    moreRow.appendChild(field("Threads", threads));
    moreRow.appendChild(field("Threads batch", threadsBatch));
    moreRow.appendChild(field("KV unified", kvUnified));
    moreRow.appendChild(field("No host buffer", noHost));
    moreRow.appendChild(field("Cache RAM MiB", cacheRam));
    moreRow.appendChild(field("Memory map", mmap));
    moreRow.appendChild(field("Continuous batching", contBatching));
    moreRow.appendChild(field("Ctx checkpoints", ctxCheckpoints));
    moreRow.appendChild(field("Device filter", deviceFilter));
    moreRow.appendChild(field("Extra args", extraArgs));
    more.appendChild(moreRow);
    const moreNote = document.createElement("div");
    moreNote.className = "lsm-muted";
    moreNote.style.marginTop = "8px";
    moreNote.textContent = "Leave these blank to let llama-server use its own defaults. These are launch overrides, not required to save a server.";
    more.appendChild(moreNote);
    form.appendChild(more);

    function refreshInstallOptions() {
      const runtimeId = runtime.value;
      const current = install.value;
      install.innerHTML = "";
      const matches = (installs || []).filter((item) => String(item.runtime_id || "") === runtimeId);
      if (!matches.length) {
        install.appendChild(new Option("No installed build for this runtime", ""));
        install.disabled = true;
        return;
      }
      install.disabled = false;
      for (const item of matches) {
        install.appendChild(new Option(`${item.runtime_id} ${item.tag}`, item.id));
      }
      if (current && matches.some((item) => item.id === current)) {
        install.value = current;
      } else {
        const sorted = matches.slice().sort((a, b) => Number(b?.installed_at || 0) - Number(a?.installed_at || 0));
        install.value = String(sorted[0]?.id || matches[0]?.id || "");
      }
    }

    runtime.addEventListener("change", () => {
      if (nameAuto) name.value = `${runtime.value || "server"}-main`;
      refreshInstallOptions();
    });
    refreshInstallOptions();

    const actions = document.createElement("div");
    actions.className = "lsm-actions";
    const formNote = document.createElement("div");
    formNote.className = "lsm-muted";
    function clearEditor() {
      editingId = "";
      nameAuto = true;
      name.value = `${runtime.value || "server"}-main`;
      model.value = "";
      port.value = defaultManagedServerPort();
      ctxSize.value = "";
      gpuLayers.value = "";
      parallel.value = "";
      batch.value = "";
      ubatch.value = "";
      threads.value = "";
      threadsBatch.value = "";
      kvUnified.value = "";
      noHost.value = "";
      cacheRam.value = "";
      mmap.value = "";
      contBatching.value = "";
      ctxCheckpoints.value = "";
      deviceFilter.value = "";
      extraArgs.value = "";
      refreshInstallOptions();
      formNote.textContent = "";
    }
    function loadEditor(item) {
      editingId = String(item.id || "").trim();
      nameAuto = false;
      name.value = String(item.name || "");
      runtime.value = String(item.runtime_id || preferredRuntimeId(host, installs));
      refreshInstallOptions();
      if (item.install_id) install.value = String(item.install_id);
      model.value = String(item.model_path || "");
      port.value = String(item.port || defaultManagedServerPort());
      ctxSize.value = item.ctx_size == null ? "" : String(item.ctx_size);
      gpuLayers.value = item.n_gpu_layers == null ? "" : String(item.n_gpu_layers);
      parallel.value = item.parallel_slots == null ? "" : String(item.parallel_slots);
      batch.value = item.batch_size == null ? "" : String(item.batch_size);
      ubatch.value = item.ubatch_size == null ? "" : String(item.ubatch_size);
      threads.value = item.n_threads == null ? "" : String(item.n_threads);
      threadsBatch.value = item.threads_batch == null ? "" : String(item.threads_batch);
      kvUnified.value = item.kv_unified == null ? "" : String(Boolean(item.kv_unified));
      noHost.value = item.no_host == null ? "" : String(Boolean(item.no_host));
      cacheRam.value = item.cache_ram == null ? "" : String(item.cache_ram);
      mmap.value = item.mmap == null ? "" : String(Boolean(item.mmap));
      contBatching.value = item.cont_batching == null ? "" : String(Boolean(item.cont_batching));
      ctxCheckpoints.value = item.ctx_checkpoints == null ? "" : String(item.ctx_checkpoints);
      deviceFilter.value = String(item.device_filter || "");
      extraArgs.value = String(item.extra_args || "");
      formNote.textContent = `Editing ${item.name || item.id}`;
    }

    async function saveEditorServer({ clearAfter = false, reloadAfter = true } = {}) {
      const submitted = {
        id: editingId || undefined,
        name: name.value.trim(),
        runtime_id: runtime.value,
        install_id: install.value,
        model_path: model.value.trim(),
        port: Number(port.value || defaultManagedServerPort()),
        ctx_size: ctxSize.value.trim() ? Number(ctxSize.value) : null,
        n_gpu_layers: gpuLayers.value.trim() ? Number(gpuLayers.value) : null,
        parallel_slots: parallel.value.trim() ? Number(parallel.value) : null,
        batch_size: batch.value.trim() ? Number(batch.value) : null,
        ubatch_size: ubatch.value.trim() ? Number(ubatch.value) : null,
        n_threads: threads.value.trim() ? Number(threads.value) : null,
        threads_batch: threadsBatch.value.trim() ? Number(threadsBatch.value) : null,
        kv_unified: kvUnified.value === "" ? null : kvUnified.value === "true",
        no_host: noHost.value === "" ? null : noHost.value === "true",
        cache_ram: cacheRam.value.trim() ? Number(cacheRam.value) : null,
        mmap: mmap.value === "" ? null : mmap.value === "true",
        cont_batching: contBatching.value === "" ? null : contBatching.value === "true",
        ctx_checkpoints: ctxCheckpoints.value.trim() ? Number(ctxCheckpoints.value) : null,
        device_filter: deviceFilter.value.trim(),
        extra_args: extraArgs.value.trim(),
      };
      const payload = await clientJson(ctx, "/v1/llama_server/server/upsert", {
        method: "POST",
        body: submitted,
      });
      const saved = payload?.server || {};
      editingId = String(saved.id || editingId || "").trim();
      const mismatches = [];
      if (submitted.model_path && String(saved.model_path || "").trim() !== submitted.model_path) {
        mismatches.push("model path");
      }
      if (submitted.install_id && String(saved.install_id || "").trim() !== submitted.install_id) {
        mismatches.push("install");
      }
      if (Number.isFinite(submitted.port) && Number(saved.port || 0) !== submitted.port) {
        mismatches.push("port");
      }
      if (editingId) {
        formNote.textContent = mismatches.length
          ? `Saved ${String(saved.name || submitted.name || editingId)}, but ${mismatches.join(", ")} did not round-trip from the manager.`
          : `Saved ${String(saved.name || submitted.name || editingId)}`;
      }
      if (clearAfter) clearEditor();
      if (reloadAfter) await reload({ force: true });
      return payload;
    }

    actions.appendChild(button("Save server", async () => {
      await saveEditorServer();
    }, "primary"));
    actions.appendChild(button("Clear", async () => {
      clearEditor();
    }));
    form.appendChild(actions);
    form.appendChild(formNote);
    const note = document.createElement("div");
    note.className = "lsm-muted";
    note.textContent = "Concurrent jobs can use llama-server parallel slots if you set them. Continuous batching should stay enabled for slot reuse. AI jobs reuse the OpenAI-compatible endpoint.";
    form.appendChild(note);
    serversCard.appendChild(form);

    for (const item of servers || []) {
      const card = document.createElement("div");
      card.className = "lsm-server";
      const header = document.createElement("div");
      header.className = "lsm-server-title";
      const left = document.createElement("div");
      left.innerHTML = `<strong>${item.name || item.id}</strong><div class="lsm-muted">${item.runtime_id || ""} - install ${item.install_id || ""}</div>`;
      header.appendChild(left);
      const right = document.createElement("div");
      right.className = item.running ? "lsm-ok" : "lsm-bad";
      right.textContent = item.running ? "Running" : "Stopped";
      header.appendChild(right);
      card.appendChild(header);
      const url = document.createElement("div");
      url.className = "lsm-server-url";
      url.textContent = `Host: ${rewriteClientUrl(item.url || "", "local") || ""}  |  Frontend mode: ${rewriteClientUrl(item.llmloader_url || "") || ""}`;
      card.appendChild(url);
      const modelPath = document.createElement("div");
      modelPath.className = "lsm-muted";
      modelPath.textContent = `Model: ${String(item.effective_model_path || item.model_path || "").trim() || "(none saved; Play can inject one)"}`;
      card.appendChild(modelPath);
      const configBits = [
        `port=${item.port || ""}`,
        item.ctx_size != null ? `ctx=${item.ctx_size}` : "",
        item.n_gpu_layers != null ? `gpu_layers=${item.n_gpu_layers}` : "",
        item.batch_size != null ? `batch=${item.batch_size}` : "",
        item.ubatch_size != null ? `ubatch=${item.ubatch_size}` : "",
        item.n_threads != null ? `threads=${item.n_threads}` : "",
        item.threads_batch != null ? `threads_batch=${item.threads_batch}` : "",
        item.parallel_slots != null ? `parallel=${item.parallel_slots}` : "",
        item.cont_batching != null ? `cont_batching=${item.cont_batching ? "on" : "off"}` : "",
        item.main_gpu != null ? `main_gpu=${item.main_gpu}` : "",
        item.kv_unified != null ? `kv_unified=${item.kv_unified}` : "",
        item.no_host != null ? `no_host=${item.no_host}` : "",
        item.cache_ram != null ? `cache_ram=${item.cache_ram}` : "",
        item.mmap != null ? `mmap=${item.mmap}` : "",
        item.ctx_checkpoints != null ? `ctx_checkpoints=${item.ctx_checkpoints}` : "",
        item.device_filter ? `device_filter=${item.device_filter}` : "",
        item.extra_args ? `extra_args=${item.extra_args}` : "",
      ].filter(Boolean);
      const configLine = document.createElement("div");
      configLine.className = "lsm-muted";
      configLine.textContent = `Config: ${configBits.join(" | ") || "(defaults)"}`;
      card.appendChild(configLine);
      const slots = document.createElement("div");
      slots.className = "lsm-muted";
      const slotCount = Array.isArray(item.slots) ? item.slots.length : 0;
      const serverState = item.running
        ? "api ready"
        : item.process_alive
          ? "process alive, api unavailable"
          : "stopped";
      slots.textContent = slotCount ? `Server slots: ${slotCount} | ${serverState}` : `Server slots: unavailable | ${serverState}`;
      card.appendChild(slots);
      const actions = document.createElement("div");
      actions.className = "lsm-actions";
      actions.appendChild(button("Edit", async () => {
        loadEditor(item);
      }));
      if (item.running) {
        actions.appendChild(button("Stop", async () => {
          await clientJson(ctx, "/v1/llama_server/server/stop", { method: "POST", body: { server_id: item.id } });
          await reload({ force: true });
        }));
      } else {
        actions.appendChild(button("Start", async () => {
          let targetServerId = String(item.id || "").trim();
          let savedModel = String(item.model_path || "").trim();
          if (editingId && editingId === targetServerId) {
            const editorModel = model.value.trim();
            if (!editorModel) {
              throw new Error("model_path required for manual Start. Save a model path here, or start it from Model Deck Play so the model is injected automatically.");
            }
            const saved = await saveEditorServer({ clearAfter: false, reloadAfter: false });
            targetServerId = String(saved?.server?.id || targetServerId).trim();
            savedModel = String(saved?.server?.model_path || editorModel).trim();
          }
          if (!savedModel) {
            throw new Error("model_path required for manual Start. Save a model path here, or start it from Model Deck Play so the model is injected automatically.");
          }
          await clientJson(ctx, "/v1/llama_server/server/start", { method: "POST", body: { server_id: targetServerId } });
          if (editingId && editingId === targetServerId) clearEditor();
          await reload({ force: true });
        }, "primary"));
      }
      actions.appendChild(button("Delete", async () => {
        await clientJson(ctx, "/v1/llama_server/server/delete", { method: "POST", body: { server_id: item.id } });
        await reload({ force: true });
      }));
      card.appendChild(actions);

      const diagActions = document.createElement("div");
      diagActions.className = "lsm-actions";
      const diagPre = document.createElement("pre");
      diagPre.className = "lsm-pre";
      diagPre.style.display = "none";
      const logsPre = document.createElement("pre");
      logsPre.className = "lsm-pre";
      logsPre.style.display = "none";
      diagActions.appendChild(button("Health", async () => {
        const payload = await clientJson(ctx, `/v1/llama_server/diagnostics?server_id=${encodeURIComponent(item.id)}`);
        diagPre.style.display = "block";
        diagPre.textContent = JSON.stringify(payload, null, 2);
      }));
      diagActions.appendChild(button("Logs", async () => {
        const payload = await clientJson(ctx, `/v1/llama_server/logs?server_id=${encodeURIComponent(item.id)}&lines=200`);
        logsPre.style.display = "block";
        logsPre.textContent = Array.isArray(payload.lines) ? payload.lines.join("\n") : "";
      }));
      card.appendChild(diagActions);
      card.appendChild(diagPre);
      card.appendChild(logsPre);
      serversCard.appendChild(card);
    }

    clearEditor();
  }

  void reload().catch((err) => {
    setStatus(String(err?.message || err || "Failed to load llama-server manager."));
  });
}

function createSharedApi(host) {
  const sharedCtx = {
    getState: typeof host.getState === "function" ? host.getState.bind(host) : undefined,
    apiJson: typeof host.apiJson === "function" ? host.apiJson.bind(host) : undefined,
    state: typeof host.getState === "function" ? host.getState() : {},
  };
  return {
    id: "llama_server_api",
    type: "api_provider",
    service: "llama_server",
    async getStatus({ lightweight = true } = {}) {
      return clientJson(sharedCtx, `/v1/llama_server/status?lightweight=${lightweight ? 1 : 0}`);
    },
    async getDevices({ installId = "", runtimeId = "" } = {}) {
      const qs = installId
        ? `install_id=${encodeURIComponent(String(installId))}`
        : `runtime_id=${encodeURIComponent(String(runtimeId || ""))}`;
      return clientJson(sharedCtx, `/v1/llama_server/devices?${qs}`);
    },
    async getToken() {
      return ensureSharedToken(sharedCtx);
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
    host.shareObject(createSharedApi(host));
    host.addPanelTab({
      id: meta.plugin_id,
      title: "Llama Server",
      render: (container, ctx) => renderPanel(container, ctx),
    });
  },
};

export default plugin;
