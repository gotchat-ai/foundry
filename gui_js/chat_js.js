const STORAGE_KEY = "llmloader2.chat_js.state";
const STORAGE_PREFS_KEY = "llmloader2.chat_js.prefs";
const STORAGE_ROUTER_STATE_KEY = "llmloader2.chat_js.router_state";
const STORAGE_ASSET_DB = "llmloader2.chat_js.assets";
const STORAGE_ASSET_STORE = "kv";
const STORAGE_ASSET_REF_PREFIX = "__llm_idb__:";
const STORAGE_ASSET_MIN_LEN = 24 * 1024;

const DEFAULT_STATE = {
  remote: {
    serverUrl: "http://127.0.0.1:8000",
    hostServiceUrl: "",
    clientServiceUrl: "",
    enabled: true,
  },
  auth: {
    token: "",
    username: "",
    role: "",
    mustChange: false,
    alias: "",
    guestId: "",
  },
  projects: {},
  sessions: {},
  sessionAccess: {},
  roster: [],
  pendingUploads: [],
  prefs: {
    systemPrompt: "",
    temperature: "",
    maxTokens: "",
    contextMode: "full",
    geoContextEnabled: false,
    geoContextOverride: "",
    geoContextData: null,
  },
  router: {
    manifest: {},
    enabled: {},
    settings: {},
  },
  pluginRepo: {
    apiBase: "https://pluginserver.gotchat.ai/api",
    downloads: [],
    installedServer: {},
    installedClient: {},
    lastSearch: [],
    manageSearch: "",
    manageTypeFilters: [],
  },
  pluginPrefs: {
    enabled: {},
  },
  permissions: {
    ready: false,
    defaultRole: "user",
    roleIds: ["anonymous"],
    permissions: {
      "ui.account.view": true,
    },
    pluginAccess: {
      auth_projects: { view: true, open: true, settings: false },
    },
    pluginDefaults: { view: false, open: false, settings: false },
    isAdmin: false,
  },
  ui: {
    activePid: "",
    activeSid: "",
    activeGuiPluginId: "",
    leftCollapsed: false,
    rightCollapsed: false,
    showLog: false,
    autoScrollLock: true,
    transcriptTopbarVisible: false,
    transcriptBottombarVisible: false,
    savedTheme: null,
    serverTheme: null,
    serverThemeState: null,
    useLocalThemeOverride: false,
    chatInfo: {
      title: "GotChat Foundry",
      subtitle: "Your AI Chat",
      logo_data_url: "",
    },
  },
};

const app = {
  state: mergeDeep(DEFAULT_STATE, loadState()),
  dom: {},
  serviceUrlResolvePromise: null,
  embedDefaults: {
    pid: "",
    sid: "",
  },
  features: {
    authEnabled: false,
    authEnabledBy: new Set(),
  },
  plugins: {
    list: [],
    meta: {},
    entries: {},
    registry: {},
    instances: {},
    ready: false,
    loadPromise: null,
    autoLoadTimer: null,
    autoLoadAttempts: 0,
    accountActions: [],
    chatsOverride: null,
    sharedObjects: {
      items: [],
    },
    i18n: {
      bundles: [],
      dictionaries: {},
      callbacks: [],
    },
    slots: {
      toolbar: [],
      topRightIconRow: [],
      transcriptTopbar: [],
      transcriptBottombar: [],
      composerLeft: [],
      panels: [],
      messagePreRenderers: [],
      messageRenderers: [],
      blockTransformers: [],
      blockRenderers: [],
      messageFooterItems: [],
      eventHandlers: [],
      completionPayloadHooks: [],
      rosterActions: [],
      sendHooks: [],
      sendContextMenuItems: [],
      projectCreateHandlers: [],
      sessionCreateHandlers: [],
    },
    currentRegistering: null,
    loading: false,
    loadingComplete: false,
    suppressTranscriptRefresh: false,
    forceLiveTranscriptRenderOnce: false,
  },
  streams: {
    events: null,
    active: {},
    bySid: {},
    msgAliases: {},
    placeholderBySid: {},
    placeholderQueueBySid: {},
    placeholderByClientMsgId: {},
    modeBySid: {},
  },
  saveTimer: null,
  saveInFlight: false,
  saveQueued: false,
  routerManifestInFlight: false,
  runtimeControl: {
    status: null,
    loading: false,
  },
  requestCache: {
    inflight: new Map(),
    responses: new Map(),
  },
};

var pluginRepoDownloadInFlight = new Set();
var pluginRepoRestartState = new Map();
const pluginRepoRequirementSummary = new Map();
const pluginRepoRequirementInFlight = new Set();
const pluginRepoRequirementInFlightSignature = new Map();
let pluginRepoHostServiceDownUntil = 0;
let pluginRepoRequirementRenderTimer = null;
let pluginRepoLastTab = "";
let pluginRepoLastRefreshAt = 0;
let pluginRepoSearchRequirementsInitialized = false;
let pluginRepoManageSearchTimer = null;
const PLUGIN_REPO_SEARCH_IDLE_MS = 360;
const pluginRepoRequirementsCache = new Map();

let scrollToBottomTimer = null;
let scrollToBottomRaf = null;
let lastSendKey = "";
let lastSendAt = 0;
let pluginFullView = null;
const TRANSCRIPT_CACHE_OWNER = "chat_js";
const TRANSCRIPT_CACHE_PREFIX = "transcript_v1:";
const TRANSCRIPT_CACHE_TTL_MS = 10 * 60 * 1000;
const PLUGIN_CACHE_STORAGE_KEY = "llmloader2_gui_plugin_cache_v1";
const PLUGIN_DISCOVERY_CACHE_KEY = "llmloader2_gui_plugin_discovery_v3";
const PLUGIN_DISCOVERY_CACHE_TTL_MS = 5 * 60 * 1000;
const TRANSCRIPT_SNAPSHOT_SETTLE_MS = 260;
const TRANSCRIPT_SNAPSHOT_MAX_WAIT_MS = 1400;
const TRANSCRIPT_RENDER_CACHE_VERSION = 5;
const STORAGE_QUOTA_WARN_THROTTLE_MS = 30000;
const GEO_CONTEXT_FETCH_TIMEOUT_MS = 4500;
const GEO_CONTEXT_PROVIDERS = [
  {
    name: "ipapi",
    url: "https://ipapi.co/json/",
    map(data) {
      return {
        ip: data?.ip || "",
        city: data?.city || "",
        region: data?.region || "",
        regionCode: data?.region_code || "",
        country: data?.country_name || "",
        countryCode: data?.country_code || "",
        timezone: data?.timezone || "",
        latitude: data?.latitude,
        longitude: data?.longitude,
      };
    },
  },
  {
    name: "ipwhois",
    url: "https://ipwho.is/",
    map(data) {
      if (data?.success === false) throw new Error(data?.message || "ip_lookup_failed");
      return {
        ip: data?.ip || "",
        city: data?.city || "",
        region: data?.region || "",
        regionCode: data?.region_code || "",
        country: data?.country || "",
        countryCode: data?.country_code || "",
        timezone: data?.timezone?.id || "",
        latitude: data?.latitude,
        longitude: data?.longitude,
      };
    },
  },
];
const uiThemeDefaultsByTarget = new WeakMap();
let storageAssetDbPromise = null;
let transcriptSnapshotRaf = null;
let transcriptSnapshotTimer = null;
let transcriptSnapshotObserver = null;
let lastStorageQuotaWarnAt = 0;

function getPluginCacheApi() {
  try {
    const shared = app?.plugins?.sharedObjects?.items || [];
    return shared.find((item) => item && item.id === "plugin_cache_api" && item.service === "plugin_cache") || null;
  } catch (_err) {
    return null;
  }
}

function transcriptCacheKey(pid, sid) {
  return `${TRANSCRIPT_CACHE_PREFIX}${String(pid || "").trim()}::${String(sid || "").trim()}`;
}

function computeMessageFingerprint(msg) {
  const id = String(msg?.msg_id || "");
  const ts = String(msg?.ts || "");
  const role = String(msg?.role || "");
  const content = msg?.content;
  const contentLen = Array.isArray(content)
    ? content.length
    : String(content == null ? "" : content).length;
  const streaming = msg?.streaming ? "1" : "0";
  return `${id}|${ts}|${role}|${contentLen}|${streaming}`;
}

function computeTranscriptFingerprints(messages) {
  const out = [];
  for (const msg of messages || []) {
    out.push(computeMessageFingerprint(msg));
  }
  return out;
}

function getPluginRenderFingerprint() {
  const meta = app?.plugins?.meta || {};
  const entries = app?.plugins?.entries || {};
  const enabled = [];
  for (const [id, info] of Object.entries(meta)) {
    if (!info?.enabled) continue;
    const entry = info.entry || entries[id] || {};
    enabled.push([
      String(id || ""),
      String(entry.path || ""),
      String(entry.rev || ""),
      String(info.status || ""),
    ].join("|"));
  }
  enabled.sort();
  return enabled.join("||");
}

function loadTranscriptSnapshot(pid, sid) {
  try {
    const session = sid ? app?.state?.sessions?.[sid] : null;
    const snap = session && typeof session._serverTranscriptSnapshot === "object"
      ? session._serverTranscriptSnapshot
      : null;
    if (snap && String(snap.sid || "") === String(sid || "") && String(snap.pid || "") === String(pid || "")) {
      return snap;
    }
  } catch (_err) {}
  const key = transcriptCacheKey(pid, sid);
  const api = getPluginCacheApi();
  if (api) {
    try {
      return api.get(TRANSCRIPT_CACHE_OWNER, key) || null;
    } catch (_err) {}
  }
  try {
    const rawPluginCache = window.localStorage.getItem(PLUGIN_CACHE_STORAGE_KEY);
    const pluginCache = rawPluginCache ? JSON.parse(rawPluginCache) : null;
    const entry = pluginCache?.namespaces?.[TRANSCRIPT_CACHE_OWNER]?.entries?.[key];
    if (entry && typeof entry === "object") {
      const exp = Number(entry.expiresAt || 0);
      if (!exp || exp > Date.now()) {
        return entry.value || null;
      }
    }
  } catch (_err) {}
  try {
    const raw = window.localStorage.getItem(`llmloader2.${key}`);
    const parsed = raw ? JSON.parse(raw) : null;
    return parsed;
  } catch (_err) {
    return null;
  }
}

async function saveTranscriptSnapshotServer(pid, sid, payload) {
  if (!pid || !sid) return;
  if (!canUseRemoteServer()) return;
  try {
    await apiJson(`/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/transcript_cache`, {
      method: "PUT",
      headers: buildHeaders({ pid, sid }),
      body: { payload: payload || {} },
    });
  } catch (_err) {}
}

function transcriptHasStreamingMessages(messages) {
  return (messages || []).some((msg) => Boolean(msg?.streaming));
}

function tryRestoreTranscriptSnapshot(pid, sid, session, messages, fingerprints) {
  const transcript = app?.dom?.transcript;
  if (!transcript || !sid || !pid) {
    markTranscriptCacheStatus("miss", "missing_scope");
    return false;
  }
  if (!Array.isArray(messages) || !messages.length) {
    markTranscriptCacheStatus("miss", "no_messages");
    return false;
  }
  if (transcriptHasStreamingMessages(messages)) {
    markTranscriptCacheStatus("miss", "streaming_messages");
    return false;
  }
  const snap = loadTranscriptSnapshot(pid, sid);
  if (!snap) {
    markTranscriptCacheStatus("miss", "no_snapshot");
    return false;
  }
  if (snap.sid !== sid) {
    markTranscriptCacheStatus("miss", "sid_mismatch");
    return false;
  }
  if (!Array.isArray(snap.fingerprints)) {
    markTranscriptCacheStatus("miss", "missing_fingerprints");
    return false;
  }
  if (snap.pluginsReady !== true || snap.snapshotKind !== "post_render") {
    markTranscriptCacheStatus("miss", "not_post_render_snapshot");
    return false;
  }
  if (snap.renderCacheVersion !== TRANSCRIPT_RENDER_CACHE_VERSION) {
    markTranscriptCacheStatus("miss", `version_${snap.renderCacheVersion || "none"}`);
    return false;
  }
  const same =
    snap.fingerprints.length === fingerprints.length &&
    snap.fingerprints.every((v, i) => v === fingerprints[i]);
  if (!same) {
    markTranscriptCacheStatus("miss", `fingerprint_mismatch:${snap.fingerprints.length}:${fingerprints.length}`);
    return false;
  }
  if (String(snap.pluginRenderFingerprint || "") !== String(getPluginRenderFingerprint() || "")) {
    markTranscriptCacheStatus("miss", "plugin_fingerprint_mismatch");
    return false;
  }
  if (typeof snap.html !== "string" || !snap.html.trim()) {
    markTranscriptCacheStatus("miss", "empty_snapshot_html");
    return false;
  }
  transcript.innerHTML = snap.html;
  restoreTranscriptNodesFromDom();
  if (pluginsActuallyReady()) {
    rehydrateRestoredTranscriptInteractions(session, messages);
  }
  app.state.ui.__transcriptRenderMeta = { sid, pid, fingerprints };
  markTranscriptRenderSource("cache", {
    messageSource: session?.source || "local_state",
    cacheKey: transcriptCacheKey(pid, sid),
    messageCount: messages.length,
  });
  markTranscriptCacheStatus("hit", "restored");
  scrollToBottom();
  return true;
}

function saveTranscriptSnapshot(pid, sid, payload) {
  const key = transcriptCacheKey(pid, sid);
  const api = getPluginCacheApi();
  if (api) {
    try {
      api.set(TRANSCRIPT_CACHE_OWNER, key, payload, { ttlMs: TRANSCRIPT_CACHE_TTL_MS });
    } catch (_err) {}
  }
  try {
    window.localStorage.setItem(`llmloader2.${key}`, JSON.stringify(payload || {}));
  } catch (_err) {}
  try {
    const session = sid ? app?.state?.sessions?.[sid] : null;
    if (session && typeof session === "object") {
      session._serverTranscriptSnapshot = payload || null;
      app.state.sessions[sid] = session;
    }
  } catch (_err) {}
  void saveTranscriptSnapshotServer(pid, sid, payload);
}

function clearTranscriptSnapshotWaiters() {
  if (transcriptSnapshotRaf) {
    try { cancelAnimationFrame(transcriptSnapshotRaf); } catch (_err) {}
    transcriptSnapshotRaf = null;
  }
  if (transcriptSnapshotTimer) {
    try { clearTimeout(transcriptSnapshotTimer); } catch (_err) {}
    transcriptSnapshotTimer = null;
  }
  if (transcriptSnapshotObserver) {
    try { transcriptSnapshotObserver.disconnect(); } catch (_err) {}
    transcriptSnapshotObserver = null;
  }
}

function snapshotTranscriptHtml() {
  const root = app?.dom?.transcript;
  if (!root) return "";
  const clone = root.cloneNode(true);
  // Canvas pixels are not represented in innerHTML. Do not cache an empty drawn
  // canvas as if it were a finished chart; force chart messages to render live.
  clone.querySelectorAll("canvas").forEach((node) => {
    const marker = document.createElement("div");
    marker.className = "transcript-cache-dynamic-skip";
    marker.textContent = "";
    node.replaceWith(marker);
  });
  if (clone.querySelector(".transcript-cache-dynamic-skip")) return "";
  return String(clone.innerHTML || "");
}

function scheduleTranscriptSnapshot(pid, sid, fingerprints) {
  if (!pid || !sid || !app?.dom?.transcript) return;
  if (!app?.plugins?.loadingComplete || !pluginsActuallyReady()) {
    markTranscriptCacheStatus("skip_save", "plugins_not_complete");
    return;
  }
  markTranscriptCacheStatus("pending_save", `v${TRANSCRIPT_RENDER_CACHE_VERSION}:${Array.isArray(fingerprints) ? fingerprints.length : 0}`);
  clearTranscriptSnapshotWaiters();
  const root = app.dom.transcript;
  const startedAt = Date.now();
  const expected = Array.isArray(fingerprints) ? fingerprints.slice() : [];
  const finish = () => {
    clearTranscriptSnapshotWaiters();
    try {
      if (app.state.ui.activePid !== pid || app.state.ui.activeSid !== sid) return;
      const session = app.state.sessions?.[sid];
      const current = computeTranscriptFingerprints(session?.messages || []);
      const same =
        current.length === expected.length &&
        current.every((v, i) => v === expected[i]);
      if (!same) {
        markTranscriptCacheStatus("skip_save", `fingerprint_changed:${current.length}:${expected.length}`);
        return;
      }
      if (transcriptHasStreamingMessages(session?.messages || [])) {
        markTranscriptCacheStatus("skip_save", "streaming_messages");
        return;
      }
      const html = snapshotTranscriptHtml();
      if (!html.trim()) {
        markTranscriptCacheStatus("skip_save", "empty_or_dynamic_html");
        return;
      }
      saveTranscriptSnapshot(pid, sid, {
        sid,
        pid,
        fingerprints: expected,
        pluginRenderFingerprint: getPluginRenderFingerprint(),
        html,
        savedAt: Date.now(),
        pluginsReady: true,
        snapshotKind: "post_render",
        renderCacheVersion: TRANSCRIPT_RENDER_CACHE_VERSION,
      });
      markTranscriptCacheStatus("saved", `v${TRANSCRIPT_RENDER_CACHE_VERSION}:${expected.length}`);
    } catch (_err) {}
  };
  const scheduleFinish = () => {
    if (transcriptSnapshotTimer) {
      try { clearTimeout(transcriptSnapshotTimer); } catch (_err) {}
      transcriptSnapshotTimer = null;
    }
    const elapsed = Date.now() - startedAt;
    const wait = elapsed >= TRANSCRIPT_SNAPSHOT_MAX_WAIT_MS ? 0 : TRANSCRIPT_SNAPSHOT_SETTLE_MS;
    transcriptSnapshotTimer = setTimeout(finish, wait);
  };
  transcriptSnapshotRaf = requestAnimationFrame(() => {
    transcriptSnapshotRaf = requestAnimationFrame(() => {
      transcriptSnapshotRaf = null;
      if (typeof MutationObserver === "function") {
        transcriptSnapshotObserver = new MutationObserver(scheduleFinish);
        transcriptSnapshotObserver.observe(root, {
          childList: true,
          subtree: true,
          characterData: true,
          attributes: true,
        });
      }
      scheduleFinish();
    });
  });
}

function restoreTranscriptNodesFromDom() {
  app.dom.messageNodes = {};
  const nodes = app.dom.transcript?.querySelectorAll?.(".message[data-msg-id]");
  if (!nodes) return;
  nodes.forEach((node) => {
    const id = String(node?.dataset?.msgId || "").trim();
    if (id) app.dom.messageNodes[id] = node;
  });
}

function markTranscriptRenderSource(source, details = {}) {
  const transcript = app?.dom?.transcript;
  if (!transcript) return;
  transcript.dataset.renderSource = String(source || "");
  transcript.dataset.renderAt = String(Date.now());
  if (details.messageSource != null) transcript.dataset.messageSource = String(details.messageSource || "");
  if (details.cacheKey != null) transcript.dataset.cacheKey = String(details.cacheKey || "");
  if (details.messageCount != null) transcript.dataset.messageCount = String(details.messageCount || 0);
}

function markTranscriptCacheStatus(status, reason = "") {
  const transcript = app?.dom?.transcript;
  if (!transcript) return;
  transcript.dataset.cacheStatus = String(status || "");
  transcript.dataset.cacheReason = String(reason || "");
  transcript.dataset.cacheAt = String(Date.now());
}

function normalizeUiThemeSnapshot(snapshot, pluginIdOverride) {
  if (!snapshot || typeof snapshot !== "object") return null;
  const rawVars = snapshot.vars;
  if (!rawVars || typeof rawVars !== "object") return null;
  const vars = {};
  Object.entries(rawVars).forEach(([key, value]) => {
    const name = String(key || "").trim();
    if (!name.startsWith("--")) return;
    if (value == null) return;
    vars[name] = String(value);
  });
  if (Object.keys(vars).length === 0) return null;
  const pluginId = String(pluginIdOverride || snapshot.pluginId || "").trim();
  return {
    pluginId,
    vars,
    savedAt: snapshot.savedAt || Date.now(),
  };
}

function normalizeUiThemeStateValue(value) {
  return value && typeof value === "object" ? JSON.parse(JSON.stringify(value)) : null;
}

function isStorageAssetRef(value) {
  return typeof value === "string" && value.startsWith(STORAGE_ASSET_REF_PREFIX);
}

function makeStorageAssetRef(key) {
  return `${STORAGE_ASSET_REF_PREFIX}${key}`;
}

function parseStorageAssetRef(value) {
  return isStorageAssetRef(value) ? value.slice(STORAGE_ASSET_REF_PREFIX.length) : "";
}

function isLikelyLargeThemeAsset(value) {
  const text = String(value || "");
  if (!text || text.length < STORAGE_ASSET_MIN_LEN) return false;
  return text.startsWith("data:image/") || text.includes('url("data:image/') || text.includes("url('data:image/") || text.includes("url(data:image/");
}

function openStorageAssetDb() {
  if (storageAssetDbPromise) return storageAssetDbPromise;
  storageAssetDbPromise = new Promise((resolve, reject) => {
    try {
      const req = indexedDB.open(STORAGE_ASSET_DB, 1);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORAGE_ASSET_STORE)) {
          db.createObjectStore(STORAGE_ASSET_STORE);
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error || new Error("indexeddb_open_failed"));
    } catch (err) {
      reject(err);
    }
  });
  return storageAssetDbPromise;
}

async function storageAssetSet(key, value) {
  const db = await openStorageAssetDb();
  await new Promise((resolve, reject) => {
    const tx = db.transaction(STORAGE_ASSET_STORE, "readwrite");
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error || new Error("indexeddb_write_failed"));
    tx.objectStore(STORAGE_ASSET_STORE).put(String(value || ""), String(key || ""));
  });
}

async function storageAssetGet(key) {
  const db = await openStorageAssetDb();
  return await new Promise((resolve, reject) => {
    const tx = db.transaction(STORAGE_ASSET_STORE, "readonly");
    tx.onerror = () => reject(tx.error || new Error("indexeddb_read_failed"));
    const req = tx.objectStore(STORAGE_ASSET_STORE).get(String(key || ""));
    req.onsuccess = () => resolve(typeof req.result === "string" ? req.result : "");
    req.onerror = () => reject(req.error || new Error("indexeddb_read_failed"));
  });
}

async function storageAssetDelete(key) {
  const db = await openStorageAssetDb();
  await new Promise((resolve, reject) => {
    const tx = db.transaction(STORAGE_ASSET_STORE, "readwrite");
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error || new Error("indexeddb_delete_failed"));
    tx.objectStore(STORAGE_ASSET_STORE).delete(String(key || ""));
  });
}

function cloneStateForStorage(state) {
  try {
    return JSON.parse(JSON.stringify(state || {}));
  } catch {
    return {};
  }
}

function buildCriticalPrefsSnapshot(state) {
  const src = state && typeof state === "object" ? state : {};
  const ui = src.ui && typeof src.ui === "object" ? src.ui : {};
  return {
    prefs: src.prefs && typeof src.prefs === "object" ? { ...src.prefs } : {},
    pluginPrefs: src.pluginPrefs && typeof src.pluginPrefs === "object"
      ? JSON.parse(JSON.stringify(src.pluginPrefs))
      : { enabled: {} },
    ui: {
      activePid: String(ui.activePid || ""),
      activeSid: String(ui.activeSid || ""),
    },
  };
}

function saveCriticalPrefsSnapshot(state) {
  try {
    localStorage.setItem(STORAGE_PREFS_KEY, JSON.stringify(buildCriticalPrefsSnapshot(state)));
  } catch (_err) {}
}

function loadCriticalPrefsSnapshot() {
  try {
    const raw = localStorage.getItem(STORAGE_PREFS_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function getBrowserTimeZone() {
  try {
    return String(Intl.DateTimeFormat().resolvedOptions().timeZone || "").trim();
  } catch (_err) {
    return "";
  }
}

function formatGeoContextLocation(parts) {
  const items = [];
  if (parts?.city) items.push(String(parts.city).trim());
  const region = String(parts?.region || parts?.regionCode || "").trim();
  if (region) items.push(region);
  const country = String(parts?.country || parts?.countryCode || "").trim();
  if (country) items.push(country);
  return items.filter(Boolean).join(", ");
}

function getGeoContextEffectiveLocation() {
  const override = String(app?.state?.prefs?.geoContextOverride || "").trim();
  if (override) return override;
  const data = app?.state?.prefs?.geoContextData;
  return formatGeoContextLocation(data);
}

function getGeoContextEffectiveTimeZone() {
  const dataTz = String(app?.state?.prefs?.geoContextData?.timezone || "").trim();
  return dataTz || getBrowserTimeZone();
}

function formatGeoContextLocalTime(timeZone) {
  const tz = String(timeZone || "").trim();
  try {
    return new Intl.DateTimeFormat(undefined, {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
      timeZone: tz || undefined,
      timeZoneName: "short",
    }).format(new Date());
  } catch (_err) {
    return new Date().toLocaleString();
  }
}

function buildGeoContextPromptSnippet() {
  if (!app?.state?.prefs?.geoContextEnabled) return "";
  const location = getGeoContextEffectiveLocation();
  const timeZone = getGeoContextEffectiveTimeZone();
  const localTime = formatGeoContextLocalTime(timeZone);
  const data = app?.state?.prefs?.geoContextData || {};
  const lines = [
    "User local context (browser/IP estimated; approximate):",
    location ? `- Estimated location: ${location}` : "- Estimated location: unavailable",
    timeZone ? `- Time zone: ${timeZone}` : "",
    localTime ? `- Current local time: ${localTime}` : "",
    data?.ip ? `- IP used for estimate: ${data.ip}` : "",
    String(app?.state?.prefs?.geoContextOverride || "").trim()
      ? "- Location override was manually provided by the user."
      : "- Use this context only when it is relevant. If the user states a different location or time, follow the user."
  ];
  return lines.filter(Boolean).join("\n");
}

function updateGeoContextStatus(message, tone = "") {
  const el = app?.dom?.geoContextStatus;
  if (!el) return;
  el.textContent = String(message || "");
  el.dataset.state = String(tone || "");
}

function renderGeoContextInputs() {
  if (app.dom.geoContextEnabled) {
    app.dom.geoContextEnabled.checked = Boolean(app.state.prefs.geoContextEnabled);
  }
  if (app.dom.geoContextOverride) {
    app.dom.geoContextOverride.value = String(app.state.prefs.geoContextOverride || "");
  }
  const enabled = Boolean(app.state.prefs.geoContextEnabled);
  const location = getGeoContextEffectiveLocation();
  const timeZone = getGeoContextEffectiveTimeZone();
  if (!enabled) {
    updateGeoContextStatus("Disabled");
    return;
  }
  if (location || timeZone) {
    const parts = [];
    if (location) parts.push(location);
    if (timeZone) parts.push(timeZone);
    updateGeoContextStatus(`Ready: ${parts.join(" | ")}`, "ok");
    return;
  }
  updateGeoContextStatus("Enabled, waiting for location detection", "warn");
}

async function fetchJsonWithTimeout(url, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => {
    try { controller.abort(); } catch (_err) {}
  }, Math.max(1, Number(timeoutMs) || GEO_CONTEXT_FETCH_TIMEOUT_MS));
  try {
    const resp = await fetch(url, { signal: controller.signal, cache: "no-store" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return await resp.json();
  } finally {
    clearTimeout(timer);
  }
}

async function detectGeoContext(force = false) {
  if (!force && !app?.state?.prefs?.geoContextEnabled) return;
  updateGeoContextStatus("Detecting location from IP...", "pending");
  const browserTz = getBrowserTimeZone();
  let lastErr = null;
  for (const provider of GEO_CONTEXT_PROVIDERS) {
    try {
      const raw = await fetchJsonWithTimeout(provider.url, GEO_CONTEXT_FETCH_TIMEOUT_MS);
      const mapped = provider.map(raw) || {};
      app.state.prefs.geoContextData = {
        ...mapped,
        timezone: String(mapped.timezone || browserTz || "").trim(),
        source: provider.name,
        fetchedAt: Date.now(),
      };
      scheduleSave();
      renderGeoContextInputs();
      return app.state.prefs.geoContextData;
    } catch (err) {
      lastErr = err;
    }
  }
  app.state.prefs.geoContextData = {
    timezone: browserTz,
    source: "browser_time_only",
    fetchedAt: Date.now(),
  };
  scheduleSave();
  renderGeoContextInputs();
  updateGeoContextStatus(`Time only: location lookup failed${lastErr?.message ? ` (${lastErr.message})` : ""}`, "warn");
  return app.state.prefs.geoContextData;
}

function buildRouterStateSnapshot(state) {
  const src = state && typeof state === "object" ? state : {};
  const router = src.router && typeof src.router === "object" ? src.router : {};
  return {
    router: {
      // Router manifests and AgentFlow definitions are reloadable from the
      // server. Persisting them here can create multi-MB localStorage/gui_prefs
      // payloads and make the browser settings UI run out of memory.
      manifest: {},
      enabled: router.enabled && typeof router.enabled === "object" ? JSON.parse(JSON.stringify(router.enabled)) : {},
      settings: sanitizeRouterSettingsForStorage(router.settings),
      manifest_ts: router.manifest_ts || 0,
    },
  };
}

function sanitizeRouterSettingsForStorage(settings) {
  const src = settings && typeof settings === "object" ? settings : {};
  const out = {};
  Object.entries(src).forEach(([scopeKey, plugins]) => {
    if (!plugins || typeof plugins !== "object") return;
    const nextPlugins = {};
    Object.entries(plugins).forEach(([pluginId, cfg]) => {
      if (!cfg || typeof cfg !== "object") {
        nextPlugins[pluginId] = cfg;
        return;
      }
      const nextCfg = JSON.parse(JSON.stringify(cfg));
      if (pluginId === "agent_flow") {
        delete nextCfg.agent_flow_flows;
        delete nextCfg.agent_flow_flow_ids_by_name;
        delete nextCfg.agent_flow_default_flow_ids_by_name;
      }
      nextPlugins[pluginId] = nextCfg;
    });
    out[scopeKey] = nextPlugins;
  });
  return out;
}

function saveRouterStateSnapshot(state) {
  try {
    localStorage.setItem(STORAGE_ROUTER_STATE_KEY, JSON.stringify(buildRouterStateSnapshot(state)));
  } catch (_err) {}
}

function loadRouterStateSnapshot() {
  try {
    const raw = localStorage.getItem(STORAGE_ROUTER_STATE_KEY);
    return raw ? { router: normalizeRouterStateSnapshot(JSON.parse(raw)) } : {};
  } catch {
    return {};
  }
}

async function persistLargeThemeAssetValue(value, assetKey) {
  const text = String(value || "").trim();
  if (!text) {
    await storageAssetDelete(assetKey).catch(() => {});
    return "";
  }
  if (isStorageAssetRef(text)) return text;
  if (!isLikelyLargeThemeAsset(text)) {
    await storageAssetDelete(assetKey).catch(() => {});
    return text;
  }
  await storageAssetSet(assetKey, text);
  return makeStorageAssetRef(assetKey);
}

async function prepareStateForStorage(state) {
  const next = cloneStateForStorage(state);
  if (next.remote && typeof next.remote === "object") {
    next.remote.serverUrl = normalizeServerUrl(next.remote.serverUrl || "");
    next.remote.hostServiceUrl = normalizeServerUrl(next.remote.hostServiceUrl || "");
    next.remote.clientServiceUrl = normalizeServerUrl(next.remote.clientServiceUrl || "");
    next.remote.discoveredServerUrl = normalizeServerUrl(next.remote.discoveredServerUrl || "");
    next.remote.publicServerUrl = normalizeServerUrl(next.remote.publicServerUrl || "");
  }
  const ui = next.ui && typeof next.ui === "object" ? next.ui : {};
  next.ui = ui;
  delete ui.__transcriptRenderMeta;
  delete ui.__sessionSwitchToken;
  // Mobile browsers have tight localStorage quotas. Remote/session message
  // payloads are re-fetchable from server APIs and should not be duplicated in
  // full state snapshots.
  const sessions = next.sessions && typeof next.sessions === "object" ? next.sessions : {};
  for (const sess of Object.values(sessions)) {
    if (!sess || typeof sess !== "object") continue;
    delete sess._serverTranscriptSnapshot;
    delete sess._pending_client_msg_ids;
    if (Array.isArray(sess.messages)) {
      if (sess.source === "remote") {
        sess.messages = [];
      } else if (sess.messages.length > 40) {
        sess.messages = sess.messages.slice(-40);
      }
    }
  }
  if (next.sessionAccess && typeof next.sessionAccess === "object") {
    next.sessionAccess = {};
  }
  if (Array.isArray(next.roster)) {
    next.roster = [];
  }
  if (next.router && typeof next.router === "object") {
    next.router = buildRouterStateSnapshot(next).router;
  }
  const themeDemo = ui.themeDemo && typeof ui.themeDemo === "object" ? ui.themeDemo : null;
  if (themeDemo?.light) {
    themeDemo.light.bodyImage = await persistLargeThemeAssetValue(themeDemo.light.bodyImage, "theme_demo.light.bodyImage");
  }
  if (themeDemo?.dark) {
    themeDemo.dark.bodyImage = await persistLargeThemeAssetValue(themeDemo.dark.bodyImage, "theme_demo.dark.bodyImage");
  }
  const serverThemeState = ui.serverThemeState && typeof ui.serverThemeState === "object" ? ui.serverThemeState : null;
  if (serverThemeState?.light) {
    serverThemeState.light.bodyImage = await persistLargeThemeAssetValue(serverThemeState.light.bodyImage, "serverThemeState.light.bodyImage");
  }
  if (serverThemeState?.dark) {
    serverThemeState.dark.bodyImage = await persistLargeThemeAssetValue(serverThemeState.dark.bodyImage, "serverThemeState.dark.bodyImage");
  }
  const savedThemeVars = ui.savedTheme?.vars && typeof ui.savedTheme.vars === "object" ? ui.savedTheme.vars : null;
  if (savedThemeVars) {
    savedThemeVars["--bg-image"] = await persistLargeThemeAssetValue(savedThemeVars["--bg-image"], "savedTheme.vars.--bg-image");
  }
  const serverThemeVars = ui.serverTheme?.vars && typeof ui.serverTheme.vars === "object" ? ui.serverTheme.vars : null;
  if (serverThemeVars) {
    serverThemeVars["--bg-image"] = await persistLargeThemeAssetValue(serverThemeVars["--bg-image"], "serverTheme.vars.--bg-image");
  }
  return next;
}

async function restoreLargeThemeAssetValue(value) {
  const refKey = parseStorageAssetRef(value);
  if (!refKey) return value;
  const restored = await storageAssetGet(refKey).catch(() => "");
  return restored || "";
}

async function hydrateStoredStateAssets() {
  const ui = app.state?.ui;
  if (!ui || typeof ui !== "object") return false;
  let changed = false;
  const themeDemo = ui.themeDemo && typeof ui.themeDemo === "object" ? ui.themeDemo : null;
  if (themeDemo?.light && isStorageAssetRef(themeDemo.light.bodyImage)) {
    themeDemo.light.bodyImage = await restoreLargeThemeAssetValue(themeDemo.light.bodyImage);
    changed = true;
  }
  if (themeDemo?.dark && isStorageAssetRef(themeDemo.dark.bodyImage)) {
    themeDemo.dark.bodyImage = await restoreLargeThemeAssetValue(themeDemo.dark.bodyImage);
    changed = true;
  }
  const serverThemeState = ui.serverThemeState && typeof ui.serverThemeState === "object" ? ui.serverThemeState : null;
  if (serverThemeState?.light && isStorageAssetRef(serverThemeState.light.bodyImage)) {
    serverThemeState.light.bodyImage = await restoreLargeThemeAssetValue(serverThemeState.light.bodyImage);
    changed = true;
  }
  if (serverThemeState?.dark && isStorageAssetRef(serverThemeState.dark.bodyImage)) {
    serverThemeState.dark.bodyImage = await restoreLargeThemeAssetValue(serverThemeState.dark.bodyImage);
    changed = true;
  }
  const savedThemeVars = ui.savedTheme?.vars && typeof ui.savedTheme.vars === "object" ? ui.savedTheme.vars : null;
  if (savedThemeVars && isStorageAssetRef(savedThemeVars["--bg-image"])) {
    savedThemeVars["--bg-image"] = await restoreLargeThemeAssetValue(savedThemeVars["--bg-image"]);
    changed = true;
  }
  const serverThemeVars = ui.serverTheme?.vars && typeof ui.serverTheme.vars === "object" ? ui.serverTheme.vars : null;
  if (serverThemeVars && isStorageAssetRef(serverThemeVars["--bg-image"])) {
    serverThemeVars["--bg-image"] = await restoreLargeThemeAssetValue(serverThemeVars["--bg-image"]);
    changed = true;
  }
  if (changed) {
    const effective = getEffectiveUiThemeSnapshot();
    if (effective) applyUiThemeSnapshot(effective, { save: false });
  }
  return changed;
}

function isQuotaExceededError(err) {
  return err && (
    err.name === "QuotaExceededError" ||
    err.code === 22 ||
    err.code === 1014
  );
}

function logStorageWarn(msg, err) {
  const text = `${msg}${err ? `: ${err.message || err}` : ""}`;
  if (app?.dom?.logOutput) {
    appendLog(text, "warn");
    return;
  }
  console.warn(text, err || "");
}

async function persistStateNow() {
  const prepared = await prepareStateForStorage(app.state);
  saveCriticalPrefsSnapshot(prepared);
  saveRouterStateSnapshot(prepared);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(prepared));
}

async function flushScheduledSave() {
  if (app.saveInFlight) {
    app.saveQueued = true;
    return;
  }
  app.saveInFlight = true;
  try {
    do {
      app.saveQueued = false;
      await persistStateNow();
    } while (app.saveQueued);
  } catch (err) {
    if (isQuotaExceededError(err)) {
      saveCriticalPrefsSnapshot(app.state);
      saveRouterStateSnapshot(app.state);
      const now = Date.now();
      if (now - lastStorageQuotaWarnAt >= STORAGE_QUOTA_WARN_THROTTLE_MS) {
        lastStorageQuotaWarnAt = now;
        logStorageWarn("[storage] full state save skipped because browser storage quota was exceeded; prefs and router settings were preserved separately", err);
      }
    } else {
      console.error("[storage] state save failed", err);
    }
  } finally {
    app.saveInFlight = false;
  }
}

function getUiThemeTargets() {
  const out = [];
  const push = (el) => {
    if (!(el instanceof Element)) return;
    if (out.includes(el)) return;
    out.push(el);
  };
  push(document.documentElement);
  push(window.__CHAT_JS_EMBED_MOUNT);
  const cfg = window.__CHAT_JS_EMBED_CONFIG || {};
  push(cfg.mount);
  const embedMount = cfg.mount instanceof Element ? cfg.mount : window.__CHAT_JS_EMBED_MOUNT;
  push(embedMount?.closest?.(".llm-chat-panel, [data-llm-chat-panel], .llm-chat-drawer, .llm-chat-widget-panel"));
  push(embedMount?.parentElement?.classList?.contains("llm-chat-embed-panel-host") ? embedMount.parentElement : null);
  push(cfg.overlayMount);
  push(cfg.portal);
  push(document.getElementById("llm-chat-js-embed"));
  push(document.getElementById("llm-chat-js-portal"));
  return out;
}

function snapshotCssVars(target) {
  if (!(target instanceof Element)) return {};
  const styles = getComputedStyle(target);
  const out = {};
  for (let i = 0; i < styles.length; i += 1) {
    const key = styles[i];
    if (!String(key || "").startsWith("--")) continue;
    out[key] = styles.getPropertyValue(key).trim();
  }
  return out;
}

function captureInitialUiThemeDefaults() {
  getUiThemeTargets().forEach((target) => {
    if (!(target instanceof Element)) return;
    if (uiThemeDefaultsByTarget.has(target)) return;
    uiThemeDefaultsByTarget.set(target, snapshotCssVars(target));
  });
}

function getUiThemeDefaultsForTarget(target) {
  if (!(target instanceof Element)) return {};
  if (!uiThemeDefaultsByTarget.has(target)) {
    uiThemeDefaultsByTarget.set(target, snapshotCssVars(target));
  }
  return { ...(uiThemeDefaultsByTarget.get(target) || {}) };
}

function applyUiThemeSnapshot(snapshot, options = {}) {
  const normalized = normalizeUiThemeSnapshot(snapshot);
  if (!normalized) return false;
  const targets = getUiThemeTargets();
  if (!targets.length) return;
  targets.forEach((root) => {
    Object.entries(normalized.vars).forEach(([key, value]) => {
      root.style.setProperty(key, value);
    });
  });
  const shouldSave = options.save !== false;
  if (shouldSave) {
    if (!app.state.ui || typeof app.state.ui !== "object") app.state.ui = {};
    app.state.ui.savedTheme = normalized;
    if (options.localOverride !== false) {
      app.state.ui.useLocalThemeOverride = true;
    }
    scheduleSave();
  }
  return true;
}

function clearUiThemeSnapshot(options = {}) {
  const targets = getUiThemeTargets();
  targets.forEach((root) => {
    const prev = normalizeUiThemeSnapshot(app.state?.ui?.savedTheme);
    if (!prev) return;
    Object.keys(prev.vars).forEach((key) => root.style.removeProperty(key));
  });
  if (options.save !== false && app.state.ui) {
    app.state.ui.savedTheme = null;
    app.state.ui.useLocalThemeOverride = false;
    scheduleSave();
  }
}

function setServerUiThemeDefault(themeSnapshot, themeState, options = {}) {
  if (!app.state.ui || typeof app.state.ui !== "object") app.state.ui = {};
  app.state.ui.serverTheme = normalizeUiThemeSnapshot(themeSnapshot) || null;
  app.state.ui.serverThemeState = normalizeUiThemeStateValue(themeState);
  if (options.save !== false) scheduleSave();
}

function getEffectiveUiThemeSnapshot() {
  const local = normalizeUiThemeSnapshot(app.state?.ui?.savedTheme);
  const server = normalizeUiThemeSnapshot(app.state?.ui?.serverTheme);
  if (app.state?.ui?.useLocalThemeOverride && local) return local;
  return server || local;
}

function applySavedUiThemeEarly() {
  const saved = getEffectiveUiThemeSnapshot();
  if (!saved) return;
  applyUiThemeSnapshot(saved, { save: false });
}

function coerceMessageTs(value) {
  if (!value) return null;
  if (typeof value === "number") return value;
  const num = Number(value);
  if (!Number.isNaN(num)) return num;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}


function getMessageDisplayRank(msg) {
  if (!msg || typeof msg !== "object") return 99;
  const role = String(msg.role || "").trim().toLowerCase();
  const skillNotice = Boolean(msg?.meta?.skill_notice);
  if (role === "user") return 0;
  if (role === "assistant" && skillNotice) return 1;
  if (role === "assistant") return 2;
  return 3;
}

function sortMessagesForDisplay(messages) {
  if (!Array.isArray(messages) || messages.length < 2) return Array.isArray(messages) ? messages : [];
  return messages
    .map((msg, index) => ({ msg, index }))
    .sort((a, b) => {
      const tsA = coerceMessageTs(a.msg?.ts) ?? 0;
      const tsB = coerceMessageTs(b.msg?.ts) ?? 0;
      if (tsA !== tsB) return tsA - tsB;
      const rankA = getMessageDisplayRank(a.msg);
      const rankB = getMessageDisplayRank(b.msg);
      if (rankA !== rankB) return rankA - rankB;
      return a.index - b.index;
    })
    .map((entry) => entry.msg);
}

function isLikelyDuplicate(prev, next) {
  if (!prev || !next) return false;
  if (prev.role !== next.role || prev.author !== next.author) return false;
  const prevContent = typeof prev.content === "string" ? prev.content.trim() : null;
  const nextContent = typeof next.content === "string" ? next.content.trim() : null;
  if (!prevContent || !nextContent || prevContent !== nextContent) return false;
  const prevTs = coerceMessageTs(prev.ts);
  const nextTs = coerceMessageTs(next.ts);
  if (prevTs && nextTs) {
    return Math.abs(nextTs - prevTs) < 2000;
  }
  return false;
}

function dedupeSessionMessages(session) {
  if (!session || !Array.isArray(session.messages)) return;
  const seenByTurnRole = new Map();
  const out = [];
  for (const msg of session.messages) {
    if (!msg) continue;
    const cmid = String(msg.meta?.client_msg_id || "").trim();
    if (cmid) {
      // Keep one record per (client turn id + role + author) so a user message
      // and its assistant draft/final do not collapse into a single row.
      const role = String(msg.role || "").trim().toLowerCase() || "unknown";
      const author = String(msg.author_username || msg.author || "").trim().toLowerCase();
      const key = `${cmid}|${role}|${author}`;
      if (seenByTurnRole.has(key)) {
        out[seenByTurnRole.get(key)] = msg;
        continue;
      }
      seenByTurnRole.set(key, out.length);
      out.push(msg);
      continue;
    }
    const prev = out[out.length - 1];
    if (isLikelyDuplicate(prev, msg)) {
      out[out.length - 1] = msg;
      continue;
    }
    out.push(msg);
  }
  session.messages = out;
}

// Defer init until after the module finishes evaluating so later `let/const`
// declarations are initialized (avoids TDZ errors during early render passes).
captureInitialUiThemeDefaults();
applySavedUiThemeEarly();
Promise.resolve().then(() => void init());

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function init() {
  cacheDom();
  registerFrameworkI18nBundle();
  bindEvents();
  applyQueryParams();
  applyEmbedMode();
  await hydrateStoredStateAssets();
  ensureServerUrl();
  applyStateToInputs();
  await discoverRemoteServerUrl();
  applyStateToInputs();
  renderBranding();
  ensureLocalDefaults();
  cleanupStaleDrafts();
  if (!isAuthEnabled() || hasRemoteAuth()) {
    await refreshSharedUiThemeDefault("theme_demo");
  }
  await refreshChatUiInfo();
  await refreshPermissionState({ silent: true });
  renderAll();
  const pluginLoadPromise = ensurePluginsLoaded({ force: true }).then(() => {
    app.plugins.loadingComplete = true;
    app.plugins.ready = pluginsActuallyReady();
    const restoredFromCache =
      app.dom.transcript?.dataset?.renderSource === "cache" &&
      app.dom.transcript?.dataset?.cacheStatus === "hit";
    app.plugins.forceLiveTranscriptRenderOnce = !restoredFromCache;
    renderAll();
    if (app.state.auth?.token) {
      void bootstrapRemote();
    }
  }).catch((err) => {
    appendLog(`[plugins] load failed: ${err.message || err}`, "warn");
  });
  schedulePluginAutoload();
  await bootstrapRemote();
  schedulePluginAutoload();
  void pluginLoadPromise;
}

function cleanupStaleDrafts() {
  let changed = false;
  const sessions = app.state.sessions || {};
  Object.values(sessions).forEach((session) => {
    if (!session || !Array.isArray(session.messages)) return;
    const before = session.messages.length;
    session.messages = session.messages.filter((msg) => {
      if (!msg || msg.role !== "assistant") return true;
      const content = msg.content;
      const empty =
        (Array.isArray(content) && content.length === 0) ||
        (!Array.isArray(content) && !String(content || "").trim());
      const draft = Boolean(msg.streaming || msg?.meta?.is_draft);
      return !(draft && empty);
    });
    if (session.messages.length !== before) changed = true;
  });
  if (changed) scheduleSave();
}

function cleanupSessionDrafts(sid) {
  if (!sid) return false;
  const session = app.state.sessions[sid];
  if (!session || !Array.isArray(session.messages)) return false;
  const placeholderId = app.streams.placeholderBySid[sid];
  const queue = getStreamPlaceholderQueue(sid);
  const byClient = app.streams.placeholderByClientMsgId || {};
  const ownedIds = new Set();
  if (placeholderId) ownedIds.add(placeholderId);
  for (const id of queue) {
    if (id) ownedIds.add(id);
  }
  Object.values(byClient).forEach((id) => {
    if (id) ownedIds.add(id);
  });
  if (!ownedIds.size) return false;
  let removed = false;
  const removedIds = [];
  session.messages = session.messages.filter((msg) => {
    if (!msg || msg.role !== "assistant") return true;
    const content = msg.content;
    const empty =
      (Array.isArray(content) && content.length === 0) ||
      (!Array.isArray(content) && !String(content || "").trim());
    const draft = Boolean(msg.streaming || msg?.meta?.is_draft);
    if (draft && empty) {
      const msgId = String(msg.msg_id || "").trim();
      if (!msgId || !ownedIds.has(msgId)) {
        return true;
      }
      removedIds.push(msgId);
      removed = true;
      return false;
    }
    return true;
  });
  if (removedIds.length) unregisterStreamPlaceholders(sid, removedIds);
  if (removed) {
    app.state.sessions[sid] = session;
    scheduleSave();
  }
  return removed;
}

function applyQueryParams() {
  const embedCfg = window.__CHAT_JS_EMBED_CONFIG || {};
  if (embedCfg.server) app.state.remote.serverUrl = normalizeServerUrl(embedCfg.server);
  if (embedCfg.hostService) app.state.remote.hostServiceUrl = normalizeServerUrl(embedCfg.hostService);
  if (embedCfg.clientService) app.state.remote.clientServiceUrl = normalizeServerUrl(embedCfg.clientService);
  if (embedCfg.token) app.state.auth.token = embedCfg.token;
  if (embedCfg.pid) app.embedDefaults.pid = String(embedCfg.pid || "").trim();
  if (embedCfg.sid) app.embedDefaults.sid = String(embedCfg.sid || "").trim();
  // Embed pid/sid act as fallbacks only. Do not overwrite a saved session
  // selection on every refresh.
  if (!app.state.ui.activePid && app.embedDefaults.pid) app.state.ui.activePid = app.embedDefaults.pid;
  if (!app.state.ui.activeSid && app.embedDefaults.sid) app.state.ui.activeSid = app.embedDefaults.sid;
  if (embedCfg.alias) app.state.auth.alias = embedCfg.alias;
  if (embedCfg.pluginRepoApiBase) {
    if (!app.state.pluginRepo || typeof app.state.pluginRepo !== "object") app.state.pluginRepo = {};
    app.state.pluginRepo.apiBase = normalizePluginRepoApi(embedCfg.pluginRepoApiBase);
  }

  const params = new URLSearchParams(window.location.search);
  const server = params.get("server");
  if (server) app.state.remote.serverUrl = normalizeServerUrl(server);
  const hostService = params.get("host_service");
  if (hostService) app.state.remote.hostServiceUrl = normalizeServerUrl(hostService);
  const clientService = params.get("client_service");
  if (clientService) app.state.remote.clientServiceUrl = normalizeServerUrl(clientService);
  const token = params.get("token");
  if (token) app.state.auth.token = token;
  const pid = params.get("pid");
  if (pid) app.state.ui.activePid = pid;
  const sid = params.get("sid");
  if (sid) app.state.ui.activeSid = sid;
  const alias = params.get("alias");
  if (alias) app.state.auth.alias = alias;
  const identifierKey = params.get("identifier_key") || params.get("identifierKey");
  const cmsBase = params.get("cms_base") || params.get("cmsBase");
  if (identifierKey || cmsBase) {
    // Allow direct chat_js usage to reuse the same CMS-based server discovery
    // path as embed mode.
    window.__CHAT_JS_EMBED_CONFIG = Object.assign({}, embedCfg, {
      identifierKey: identifierKey || embedCfg.identifierKey || embedCfg.identifier_key,
      cmsBase: cmsBase || embedCfg.cmsBase || embedCfg.cms_base,
    });
  }
}

function ensureServerUrl() {
  const current = normalizeServerUrl(app.state.remote.serverUrl);
  if (current && current !== DEFAULT_STATE.remote.serverUrl) {
    app.state.remote.serverUrl = current;
    return;
  }
  const localUrl = deriveLocalServerUrlFromUiOrigin();
  if (localUrl) {
    app.state.remote.serverUrl = localUrl;
    return;
  }
  const origin = window.location.origin;
  if (origin && origin !== "null" && !origin.startsWith("file:")) {
    app.state.remote.serverUrl = origin;
    return;
  }
  app.state.remote.serverUrl = DEFAULT_STATE.remote.serverUrl;
}

function getEmbedMount() {
  const cfg = window.__CHAT_JS_EMBED_CONFIG || {};
  const raw = cfg.mount || window.__CHAT_JS_EMBED_MOUNT;
  if (!raw) return document.body;
  if (raw instanceof Element) return raw;
  if (typeof raw === "string") {
    const el = document.querySelector(raw);
    if (el) return el;
  }
  return document.body;
}

function getOverlayMount() {
  // In embed mode, we can render "big" UI (settings windows, plugin panels,
  // top-right popovers) in an overlay portal mounted on <body> so they are not
  // constrained by a transformed/animated embed container.
  const cfg = window.__CHAT_JS_EMBED_CONFIG || {};
  const raw = cfg.overlayMount || cfg.portal || cfg.overlay || null;
  if (!raw) return document.body;
  if (raw instanceof Element) return raw;
  if (typeof raw === "string") {
    const el = document.querySelector(raw);
    if (el) return el;
  }
  return document.body;
}

function applyEmbedMode() {
  const cfg = window.__CHAT_JS_EMBED_CONFIG || {};
  if (!cfg.embedded) return;
  try {
    const appEl = document.getElementById("app");
    if (appEl) appEl.classList.add("embedded");
  } catch (_err) {}
  try {
    const mount = getEmbedMount();
    if (mount && mount.classList) mount.classList.add("llm-chat-embed-mount");
  } catch (_err) {}
  // Promote key overlays/modals out of the embed mount and into the overlay
  // portal so they can use full page space when the embed is a slide-over.
  try {
    const overlayMount = getOverlayMount();
    const embedMount = getEmbedMount();
    if (overlayMount && overlayMount !== embedMount) {
      const toolsModal = document.getElementById("tools-modal");
      if (toolsModal && toolsModal.parentElement !== overlayMount) {
        overlayMount.appendChild(toolsModal);
      }
      try {
        const portalId = window.__LLM_CHAT_JS_PORTAL_ID || "llm-chat-js-portal";
        if (overlayMount && overlayMount.classList && overlayMount.id === portalId) {
          overlayMount.classList.add("embedded");
        }
      } catch (_err) {}
    }
  } catch (_err) {}
}

function cacheDom() {
  const get = (id) => document.getElementById(id);
  app.dom = {
    serverStatus: get("server-status"),
    sessionStatus: get("session-status"),
    rosterStatus: get("roster-status"),
    sessionMenu: get("session-menu"),
    sessionDropdown: get("session-dropdown"),
    menuBtn: get("menu-btn"),
    menuDropdown: get("menu-dropdown"),
    menuAccount: get("menu-account"),
    menuAccountGroup: get("menu-account-group"),
    menuAccountSub: get("menu-account-sub"),
    menuGuiGroup: get("menu-gui-group"),
    menuGuiSub: get("menu-gui-sub"),
    toolsModal: get("tools-modal"),
    modalContent: document.querySelector("#tools-modal .llm-chat-modal-content"),
    modalClose: get("modal-close"),
    modalTitle: get("modal-title"),
    brandLogo: get("brand-logo"),
    brandTitle: get("brand-title"),
    brandSub: get("brand-sub"),
    projectList: get("project-list"),
    sessionList: get("session-list"),
    projectAdd: get("project-add"),
    sessionAdd: get("session-add"),
    transcript: get("transcript"),
    transcriptTopbarShell: get("transcript-topbar-shell"),
    transcriptTopbarNotch: get("transcript-topbar-notch"),
    transcriptTopbar: get("transcript-topbar"),
    transcriptTopbarLeft: get("transcript-topbar-left"),
    transcriptTopbarRight: get("transcript-topbar-right"),
    transcriptBottombarShell: get("transcript-bottombar-shell"),
    transcriptBottombarNotch: get("transcript-bottombar-notch"),
    transcriptBottombar: get("transcript-bottombar"),
    transcriptBottombarLeft: get("transcript-bottombar-left"),
    transcriptBottombarRight: get("transcript-bottombar-right"),
    toolbarActions: get("toolbar-actions"),
    activeTitle: get("active-title"),
    composerInput: get("composer-input"),
    sendBtn: get("send-btn"),
    uploadBtn: get("upload-btn"),
    typingStatus: get("typing-status"),
    draftStatus: get("draft-status"),
    logPanel: get("log-panel"),
    logToggleBtn: get("log-toggle-btn"),
    logOutput: get("log-output"),
    logClear: get("log-clear"),
    serverUrl: get("server-url"),
    userAlias: get("user-alias"),
    chatInfoTitle: get("chat-info-title"),
    chatInfoSubtitle: get("chat-info-subtitle"),
    chatInfoLogoFile: get("chat-info-logo-file"),
    chatInfoLogoPreviewWrap: get("chat-info-logo-preview-wrap"),
    chatInfoLogoPreview: get("chat-info-logo-preview"),
    chatInfoClearLogo: get("chat-info-clear-logo"),
    chatInfoSave: get("chat-info-save"),
    chatInfoNote: get("chat-info-note"),
    runtimeSection: get("runtime-section"),
    runtimeMode: get("runtime-mode"),
    runtimeGpuDevice: get("runtime-gpu-device"),
    runtimeRefresh: get("runtime-refresh"),
    runtimeApply: get("runtime-apply"),
    runtimeStatusNote: get("runtime-status-note"),
    refreshProjects: get("refresh-projects"),
    refreshSessions: get("refresh-sessions"),
    loginUser: get("login-user"),
    loginPass: get("login-pass"),
    loginBtn: get("login-btn"),
    logoutBtn: get("logout-btn"),
    authStatus: get("auth-status"),
    authStatusTop: get("auth-status-top"),
      topRightIconRow: get("top-right-icon-row"),
      systemPrompt: get("system-prompt"),
      geoContextEnabled: get("geo-context-enabled"),
      geoContextOverride: get("geo-context-override"),
      geoContextDetect: get("geo-context-detect"),
      geoContextStatus: get("geo-context-status"),
      temperature: get("temperature"),
      maxTokens: get("max-tokens"),
      contextMode: get("context-mode"),
      pluginTableBody: get("plugin-table-body"),
    routerRefresh: get("router-refresh"),
    routerTableBody: get("router-table-body"),
    pluginPanels: get("plugin-panels"),
    rosterList: get("roster-list"),
    composerLeft: get("composer-left"),
    chatsDefault: get("chats-default"),
    chatsOverride: get("chats-override"),
    guiPluginsTitle: get("gui-plugins-title"),
    projectButton: get("project-button"),
    projectDropdown: get("project-dropdown"),
    sessionButton: get("session-button"),
    sessionDropdownToolbar: get("session-dropdown-toolbar"),
    sessionJoin: get("session-join-btn"),
    toolbarRoster: get("toolbar-roster"),
    pluginRepoTabs: document.querySelectorAll(".plugin-repo-tab"),
    pluginRepoPanels: document.querySelectorAll(".plugin-repo-panel"),
    pluginRepoManageSearch: get("plugin-repo-manage-search"),
    pluginRepoManageFilterBtn: get("plugin-repo-manage-filter-btn"),
    pluginRepoManageFilterMenu: get("plugin-repo-manage-filter-menu"),
    pluginRepoManageFilterList: get("plugin-repo-manage-filter-list"),
    pluginRepoManageFilterClear: get("plugin-repo-manage-filter-clear"),
    pluginRepoApi: get("plugin-repo-api"),
    pluginRepoSearchInput: get("plugin-repo-search-input"),
    pluginRepoSearchBtn: get("plugin-repo-search-btn"),
    pluginRepoSearchFilter: get("plugin-repo-search-filter"),
    pluginRepoSearchPrev: get("plugin-repo-search-prev"),
    pluginRepoSearchNext: get("plugin-repo-search-next"),
    pluginRepoSearchPage: get("plugin-repo-search-page"),
    pluginRepoSearchPager: get("plugin-repo-search-pager"),
    pluginRepoSearchStatus: get("plugin-repo-search-status"),
    pluginRepoSearchResults: get("plugin-repo-search-results"),
    pluginRepoDownloadRefresh: get("plugin-repo-download-refresh"),
    pluginRepoDownloadPrev: get("plugin-repo-download-prev"),
    pluginRepoDownloadNext: get("plugin-repo-download-next"),
    pluginRepoDownloadPage: get("plugin-repo-download-page"),
    pluginRepoDownloadPager: get("plugin-repo-download-pager"),
    pluginRepoDownloadStatus: get("plugin-repo-download-status"),
    pluginRepoDownloadResults: get("plugin-repo-download-results"),
  };

  // Project/session toolbar labels are dynamic (they reflect selection). These
  // elements had `data-i18n-key` defaults ("No project"/"No session"), and later
  // i18n refresh passes can overwrite the dynamically rendered titles. Strip the
  // i18n keys so `renderToolbar()` remains the single source of truth.
  try {
    app.dom.projectButton?.removeAttribute?.("data-i18n-key");
    app.dom.sessionButton?.removeAttribute?.("data-i18n-key");
  } catch (_err) {}

  app.dom.composerLeftBase = Array.from(app.dom.composerLeft?.children || []);
}

function bindEvents() {
  bindStaticMenuActionButtons();
  app.dom.menuBtn.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleMenu();
  });
  app.dom.menuDropdown.addEventListener("click", (event) => {
    if (shouldUseTapSubmenus()) {
      return;
    }
    handleMenuDropdownEvent(event);
  });
  app.dom.projectButton.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleProjectDropdown();
  });
  app.dom.sessionButton.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleSessionDropdownToolbar();
  });
  if (app.dom.sessionJoin) {
    app.dom.sessionJoin.addEventListener("click", (event) => {
      event.stopPropagation();
      void requestJoinForSession();
    });
  }
  if (app.dom.pluginRepoTabs && app.dom.pluginRepoTabs.length) {
    app.dom.pluginRepoTabs.forEach((tab) => {
      tab.addEventListener("click", () => {
        setActivePluginRepoTab(tab.dataset.pluginTab || "manage");
      });
    });
  }
  if (app.dom.pluginRepoManageSearch) {
    app.dom.pluginRepoManageSearch.addEventListener("input", () => {
      ensurePluginRepoState();
      app.state.pluginRepo.manageSearch = String(app.dom.pluginRepoManageSearch.value || "");
      scheduleSave();
      if (pluginRepoManageSearchTimer) clearTimeout(pluginRepoManageSearchTimer);
      pluginRepoManageSearchTimer = setTimeout(() => {
        pluginRepoManageSearchTimer = null;
        renderPluginTable();
        renderRouterPluginsList();
      }, PLUGIN_REPO_SEARCH_IDLE_MS);
    });
  }
  if (app.dom.pluginRepoManageFilterBtn) {
    app.dom.pluginRepoManageFilterBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      const menu = app.dom.pluginRepoManageFilterMenu;
      if (!menu) return;
      renderPluginRepoManageFilterMenu();
      menu.classList.toggle("hidden");
      app.dom.pluginRepoManageFilterBtn.classList.toggle("active", !menu.classList.contains("hidden") || (app.state.pluginRepo.manageTypeFilters || []).length > 0);
    });
  }
  if (app.dom.pluginRepoManageFilterClear) {
    app.dom.pluginRepoManageFilterClear.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      ensurePluginRepoState();
      app.state.pluginRepo.manageTypeFilters = [];
      scheduleSave();
      renderPluginRepoManageFilterMenu();
      renderPluginTable();
      renderRouterPluginsList();
    });
  }
  if (app.dom.pluginRepoSearchBtn) {
    app.dom.pluginRepoSearchBtn.addEventListener("click", () => {
      void performPluginRepoSearch();
    });
  }
    if (app.dom.pluginRepoSearchInput) {
      app.dom.pluginRepoSearchInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          void performPluginRepoSearch();
        }
      });
    }
    if (app.dom.pluginRepoSearchFilter) {
      app.dom.pluginRepoSearchFilter.addEventListener("change", () => {
        ensurePluginRepoState();
        app.state.pluginRepo.searchFilter = app.dom.pluginRepoSearchFilter.value;
        app.state.pluginRepo.searchPage = 1;
        scheduleSave();
        if ((app.state.pluginRepo.lastSearch || []).length) {
          renderPluginRepoSearchResults(app.state.pluginRepo.lastSearch || []);
        } else {
          void performPluginRepoSearch();
        }
      });
    }
    if (app.dom.pluginRepoSearchPrev) {
      app.dom.pluginRepoSearchPrev.addEventListener("click", () => {
        ensurePluginRepoState();
        app.state.pluginRepo.searchPage = Math.max(1, (app.state.pluginRepo.searchPage || 1) - 1);
        renderPluginRepoSearchResults(app.state.pluginRepo.lastSearch || []);
      });
    }
    if (app.dom.pluginRepoSearchNext) {
      app.dom.pluginRepoSearchNext.addEventListener("click", () => {
        ensurePluginRepoState();
        app.state.pluginRepo.searchPage = (app.state.pluginRepo.searchPage || 1) + 1;
        renderPluginRepoSearchResults(app.state.pluginRepo.lastSearch || []);
      });
    }
    if (app.dom.pluginRepoDownloadRefresh) {
      app.dom.pluginRepoDownloadRefresh.addEventListener("click", () => {
        void refreshPluginRepoServerState({ forceRequirements: true });
      });
    }
    if (app.dom.pluginRepoDownloadPrev) {
      app.dom.pluginRepoDownloadPrev.addEventListener("click", () => {
        ensurePluginRepoState();
        app.state.pluginRepo.downloadedPage = Math.max(1, (app.state.pluginRepo.downloadedPage || 1) - 1);
        renderPluginRepoDownloaded();
      });
    }
    if (app.dom.pluginRepoDownloadNext) {
      app.dom.pluginRepoDownloadNext.addEventListener("click", () => {
        ensurePluginRepoState();
        app.state.pluginRepo.downloadedPage = (app.state.pluginRepo.downloadedPage || 1) + 1;
        renderPluginRepoDownloaded();
      });
    }
  if (app.dom.pluginRepoApi) {
    app.dom.pluginRepoApi.addEventListener("change", () => {
      ensurePluginRepoState();
      app.state.pluginRepo.apiBase = normalizePluginRepoApi(app.dom.pluginRepoApi.value);
      scheduleSave();
    });
  }
  if (app.dom.toolbarRoster) {
    app.dom.toolbarRoster.addEventListener("click", (event) => {
      event.stopPropagation();
      handleRosterClick();
    });
  }
  if (app.dom.sessionStatus) {
    app.dom.sessionStatus.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleSessionDropdown();
    });
  }
  document.addEventListener("click", (event) => {
    if (!app.dom.menuDropdown.classList.contains("hidden")) {
      if (event.target !== app.dom.menuBtn && !app.dom.menuDropdown.contains(event.target)) {
        hideMenu();
      }
    }
    if (app.dom.sessionDropdown && !app.dom.sessionDropdown.classList.contains("hidden")) {
      if (event.target !== app.dom.sessionStatus && !app.dom.sessionMenu.contains(event.target)) {
        hideSessionDropdown();
      }
    }
    if (app.dom.projectDropdown && !app.dom.projectDropdown.classList.contains("hidden")) {
      if (event.target !== app.dom.projectButton && !app.dom.projectDropdown.contains(event.target)) {
        hideProjectDropdown();
      }
    }
    if (app.dom.sessionDropdownToolbar && !app.dom.sessionDropdownToolbar.classList.contains("hidden")) {
      if (event.target !== app.dom.sessionButton && !app.dom.sessionDropdownToolbar.contains(event.target)) {
        hideSessionDropdownToolbar();
      }
    }
    if (app.dom.pluginRepoManageFilterMenu && !app.dom.pluginRepoManageFilterMenu.classList.contains("hidden")) {
      const btn = app.dom.pluginRepoManageFilterBtn;
      if (!app.dom.pluginRepoManageFilterMenu.contains(event.target) && !(btn && btn.contains(event.target))) {
        app.dom.pluginRepoManageFilterMenu.classList.add("hidden");
        renderPluginRepoManageFilterMenu();
      }
    }
  });
  app.dom.toolsModal.addEventListener("click", (event) => {
    if (event.target === app.dom.toolsModal) closeTools();
  });
  app.dom.modalClose.addEventListener("click", () => closeTools());
  app.dom.logToggleBtn.addEventListener("click", () => toggleLog());
  app.dom.projectAdd.addEventListener("click", () => void createProject());
  app.dom.sessionAdd.addEventListener("click", () => void createSession());
  bindMenuActionButton(app.dom.transcriptTopbarNotch, () => toggleTranscriptBarVisibility("top"));
  bindMenuActionButton(app.dom.transcriptBottombarNotch, () => toggleTranscriptBarVisibility("bottom"));
  app.dom.sendBtn.addEventListener("click", () => void sendMessage());
  app.dom.sendBtn.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    openSendContextMenu(e.clientX, e.clientY);
  });
  app.dom.uploadBtn.addEventListener("click", () => void toggleUploadActionMenu());
  app.dom.uploadBtn.setAttribute("aria-haspopup", "menu");
  app.dom.uploadBtn.setAttribute("aria-expanded", "false");
  app.dom.logClear.addEventListener("click", () => clearLog());
  app.dom.refreshProjects.addEventListener("click", () => void refreshProjects());
  app.dom.refreshSessions.addEventListener("click", () => void refreshSessions());
  app.dom.routerRefresh?.addEventListener("click", () => void refreshRouterManifest(true));
  app.dom.loginBtn.addEventListener("click", () => void login());
  app.dom.logoutBtn.addEventListener("click", () => void logout(true));

  app.dom.composerInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendMessage();
    }
  });

  app.dom.composerInput.addEventListener("input", () => {
    app.dom.draftStatus.textContent = app.dom.composerInput.value.trim() ? i18nTranslate("chat_js.composer.draft_ready", "Draft ready") : "";
    keepComposerCaretInView();
  });

  app.dom.projectList.addEventListener("click", (event) => {
    const item = event.target.closest(".list-item");
    if (!item) return;
    const pid = item.dataset.pid;
    if (pid) {
      if (pid === app.state.ui.activePid) return;
      void selectProject(pid);
    }
  });

  app.dom.sessionList.addEventListener("click", (event) => {
    const item = event.target.closest(".list-item");
    if (!item) return;
    const sid = item.dataset.sid;
    if (sid) {
      if (sid === app.state.ui.activeSid) return;
      void selectSession(sid);
    }
  });

  app.dom.serverUrl.addEventListener("change", () => {
    syncServerUrlSelection(app.dom.serverUrl.value, { save: true });
  });
  app.dom.userAlias.addEventListener("change", () => {
    app.state.auth.alias = app.dom.userAlias.value.trim();
    scheduleSave();
  });
  app.dom.systemPrompt.addEventListener("change", () => {
    app.state.prefs.systemPrompt = app.dom.systemPrompt.value.trim();
    scheduleSave();
  });
  app.dom.geoContextEnabled?.addEventListener("change", () => {
    app.state.prefs.geoContextEnabled = Boolean(app.dom.geoContextEnabled.checked);
    scheduleSave();
    renderGeoContextInputs();
    if (app.state.prefs.geoContextEnabled) {
      void detectGeoContext(false);
    }
  });
  app.dom.geoContextOverride?.addEventListener("change", () => {
    app.state.prefs.geoContextOverride = String(app.dom.geoContextOverride.value || "").trim();
    scheduleSave();
    renderGeoContextInputs();
  });
  app.dom.geoContextDetect?.addEventListener("click", () => {
    void detectGeoContext(true);
  });
  app.dom.temperature.addEventListener("change", () => {
    app.state.prefs.temperature = app.dom.temperature.value.trim();
    scheduleSave();
  });
  app.dom.maxTokens.addEventListener("change", () => {
    app.state.prefs.maxTokens = app.dom.maxTokens.value.trim();
    scheduleSave();
  });
  app.dom.contextMode.addEventListener("change", () => {
    app.state.prefs.contextMode = app.dom.contextMode.value;
    scheduleSave();
  });
  app.dom.chatInfoClearLogo?.addEventListener("click", () => {
    if (!hasPermission("plugins.manage.install", false)) return;
    syncChatInfoPreview("");
    if (app.dom.chatInfoLogoFile) app.dom.chatInfoLogoFile.value = "";
  });
  app.dom.chatInfoLogoFile?.addEventListener("change", () => {
    const file = app.dom.chatInfoLogoFile?.files?.[0];
    if (!file) return;
    if (!String(file.type || "").toLowerCase().startsWith("image/")) {
      appendLog("[chat-ui] logo must be an image", "warn");
      app.dom.chatInfoLogoFile.value = "";
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const value = String(reader.result || "").trim();
      syncChatInfoPreview(value);
    };
    reader.onerror = () => appendLog("[chat-ui] failed to read logo file", "warn");
    reader.readAsDataURL(file);
  });
  app.dom.chatInfoSave?.addEventListener("click", () => {
    void saveSharedChatUiInfo();
  });
  app.dom.transcript.addEventListener("scroll", () => {
    app.state.ui.autoScrollLock = isNearBottom();
  });

  window.addEventListener("focus", () => {
    schedulePluginAutoload();
  });
  window.addEventListener("chatjs:server-url-options-changed", (event) => {
    const preferred = normalizeServerUrl(event?.detail?.preferredUrl || "");
    renderServerUrlOptions(preferred || app.state.remote.serverUrl || "");
  });

  bindSubmenuPositioning();
}

function applyStateToInputs() {
  renderServerUrlOptions(app.state.remote.serverUrl || "");
  app.dom.userAlias.value = app.state.auth.alias || "";
  app.dom.systemPrompt.value = app.state.prefs.systemPrompt || "";
  renderGeoContextInputs();
  app.dom.temperature.value = app.state.prefs.temperature || "";
  app.dom.maxTokens.value = app.state.prefs.maxTokens || "";
  updateMaxTokensPlaceholder();
  app.dom.contextMode.value = app.state.prefs.contextMode || "full";
  applyChatInfoToInputs();
  if (app.state.prefs.geoContextEnabled) {
    void detectGeoContext(false);
  }
}

function updateLayout() {
  // no-op: left/right panels removed in chat_js layout
}

function isAuthEnabled() {
  return app.features.authEnabledBy.size > 0;
}

function setAuthEnabledForPlugin(pluginId, enabled) {
  const key = String(pluginId || "");
  if (!key) return;
  if (enabled) {
    app.features.authEnabledBy.add(key);
  } else {
    app.features.authEnabledBy.delete(key);
  }
  app.features.authEnabled = isAuthEnabled();
  applyAccountMenuVisibility();
  renderToolbar();
  if (enabled && app.state.auth?.token) {
    setTimeout(() => {
      if (isAuthEnabled() && app.state.auth?.token) {
        void bootstrapRemote();
      }
    }, 0);
  }
}

function applyAccountMenuVisibility() {
  const visible = isAuthEnabled();
  if (!app.dom.menuAccountGroup) return;
  app.dom.menuAccountGroup.classList.toggle("hidden", !visible);
  if (!visible && app.dom.menuAccountSub) {
    app.dom.menuAccountSub.classList.add("hidden");
  }
  if (!visible) {
    app.dom.menuAccountGroup.classList.remove("submenu-open");
  }
  updateTopStatusVisibility();
}

function handleMenuDropdownEvent(event) {
  const targetEl = event.target instanceof Element ? event.target : event.target?.parentElement || null;
  const submenuBtn = targetEl?.closest?.(".menu-item.has-sub[data-menu]");
  if (submenuBtn) {
    if (shouldUseTapSubmenus()) {
      event.preventDefault();
      event.stopPropagation();
      toggleTouchSubmenu(submenuBtn.dataset.menu || "");
      return true;
    }
    return false;
  }
  const pluginBtn = targetEl?.closest?.("[data-plugin-id]");
  if (pluginBtn) {
    event.preventDefault();
    event.stopPropagation();
    openPluginPanel(pluginBtn.dataset.pluginId, { openModal: true });
    hideMenu();
    return true;
  }
  const accountBtn = targetEl?.closest?.("[data-account-action]");
  if (accountBtn) {
    event.preventDefault();
    event.stopPropagation();
    handleAccountAction(accountBtn.dataset.accountAction);
    hideMenu();
    return true;
  }
  const btn = targetEl?.closest?.(".menu-item");
  if (!btn) return false;
  if (btn.dataset.open) {
    event.preventDefault();
    event.stopPropagation();
    if (btn.dataset.open === "gui-plugins" && !btn.dataset.pluginId) {
      clearGuiPluginsContext();
      return true;
    }
    openTools(btn.dataset.open || "chats");
    return true;
  }
  return false;
}

function bindMenuActionButton(btn, handler) {
  if (!btn || typeof handler !== "function") return;
  if (btn.dataset.menuDirectBound === "1") return;
  btn.dataset.menuDirectBound = "1";
  let lastActivateAt = 0;
  const run = (event) => {
    event.preventDefault();
    event.stopPropagation();
    const now = Date.now();
    if ((now - lastActivateAt) < 500) return;
    lastActivateAt = now;
    handler();
  };
  btn.addEventListener("pointerup", (event) => {
    if (event.pointerType && event.pointerType === "mouse") return;
    run(event);
  });
  btn.addEventListener("touchend", run, { passive: false });
  btn.addEventListener("click", (event) => {
    if (shouldUseTapSubmenus()) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    if ((Date.now() - lastActivateAt) < 700) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    run(event);
  });
}

function bindStaticMenuActionButtons() {
  const directButtons = app.dom.menuDropdown?.querySelectorAll?.(":scope > .menu-item[data-open]") || [];
  directButtons.forEach((btn) => {
    const openId = String(btn.dataset.open || "").trim();
    if (!openId) return;
    bindMenuActionButton(btn, () => {
      if (openId === "gui-plugins" && !btn.dataset.pluginId) {
        clearGuiPluginsContext();
        return;
      }
      openTools(openId || "chats");
    });
  });

  const submenuParents = app.dom.menuDropdown?.querySelectorAll?.(".menu-item.has-sub[data-menu]") || [];
  submenuParents.forEach((btn) => {
    const menuId = String(btn.dataset.menu || "").trim();
    if (!menuId) return;
    bindMenuActionButton(btn, () => {
      if (shouldUseTapSubmenus()) {
        toggleTouchSubmenu(menuId);
        return;
      }
      toggleDesktopSubmenu(menuId);
    });
  });
}

function shouldUseTapSubmenus() {
  try {
    const embedCfg = window.__CHAT_JS_EMBED_CONFIG || {};
    // Keep the regular flyout submenu by default, including on mobile.
    // Touch devices still use click/tap handlers for submenu buttons; this
    // flag only controls the expanded inline submenu presentation.
    return Boolean(embedCfg.embedded && embedCfg.touchSubmenus === true);
  } catch (_err) {
    return false;
  }
}

function closeTouchSubmenus(except = "") {
  const pairs = Array.from(app.dom.menuDropdown?.querySelectorAll?.(".menu-item.has-sub[data-menu]") || []).map((btn) => {
    const menuId = String(btn.dataset.menu || "").trim();
    const group = btn.closest(".menu-group");
    const sub = Array.from(group?.children || []).find((child) => child?.classList?.contains?.("menu-sub")) || null;
    return { id: menuId, group, sub };
  });
  for (const pair of pairs) {
    if (!pair.group || !pair.sub) continue;
    const keepOpen = except && pair.id === except;
    pair.group.classList.toggle("submenu-open", Boolean(keepOpen));
    if (!keepOpen) {
      pair.sub.classList.add("hidden");
    }
  }
}

function toggleTouchSubmenu(menuId) {
  const btn = app.dom.menuDropdown?.querySelector?.(`.menu-item.has-sub[data-menu="${CSS.escape(String(menuId || ""))}"]`) || null;
  const group = btn?.closest?.(".menu-group") || null;
  const sub = Array.from(group?.children || []).find((child) => child?.classList?.contains?.("menu-sub")) || null;
  const pair = group && sub ? { group, sub } : null;
  if (!pair?.group || !pair?.sub || pair.sub.children.length === 0) return;
  const willOpen = pair.sub.classList.contains("hidden") || !pair.group.classList.contains("submenu-open");
  closeTouchSubmenus(willOpen ? menuId : "");
  if (!willOpen) return;
  pair.sub.classList.remove("hidden");
  pair.group.classList.add("submenu-open");
  try {
    adjustSubmenuPosition(pair.group, pair.sub);
  } catch (_err) {}
}

function syncNestedFlyoutContainer(group) {
  const parentSub = group?.closest?.(".menu-sub-level2") || null;
  if (!(parentSub instanceof Element) || !parentSub.classList.contains("menu-sub-level2")) return;
  const scrollHost = Array.from(parentSub.children || []).find((child) => child?.classList?.contains?.("menu-sub-scroll")) || null;
  const nestedHost = scrollHost || parentSub;
  const hasOpenNested = Array.from(nestedHost.children || []).some((child) => (
    child instanceof Element &&
    child.classList.contains("menu-group") &&
    child.classList.contains("submenu-open")
  ));
  if (hasOpenNested) {
    if (scrollHost) {
      scrollHost.style.overflowY = "visible";
      scrollHost.style.maxHeight = "none";
    }
    parentSub.classList.remove("has-overflow");
    return;
  }
  if (scrollHost) {
    scrollHost.style.overflowY = "";
    scrollHost.style.maxHeight = "";
  }
  updateSubmenuOverflowIndicator(parentSub);
}

function toggleDesktopSubmenu(menuId) {
  const btn = app.dom.menuDropdown?.querySelector?.(`.menu-item.has-sub[data-menu="${CSS.escape(String(menuId || ""))}"]`) || null;
  const group = btn?.closest?.(".menu-group") || null;
  const sub = Array.from(group?.children || []).find((child) => child?.classList?.contains?.("menu-sub")) || null;
  if (!group || !sub || sub.children.length === 0) return;
  const willOpen = sub.classList.contains("hidden") || !group.classList.contains("submenu-open");
  const parent = group.parentElement;
  if (parent) {
    Array.from(parent.children || []).forEach((child) => {
      if (!(child instanceof Element) || child === group || !child.classList.contains("menu-group")) return;
      child.classList.remove("submenu-open");
      const childSub = Array.from(child.children || []).find((node) => node?.classList?.contains?.("menu-sub"));
      if (childSub) childSub.classList.add("hidden");
      syncNestedFlyoutContainer(child);
    });
  }
  if (!willOpen) {
    group.classList.remove("submenu-open");
    sub.classList.add("hidden");
    syncNestedFlyoutContainer(group);
    return;
  }
  group.classList.add("submenu-open");
  sub.classList.remove("hidden");
  syncNestedFlyoutContainer(group);
  try {
    adjustSubmenuPosition(group, sub);
  } catch (_err) {}
}

function toggleMenu() {
  const willOpen = app.dom.menuDropdown.classList.contains("hidden");
  if (willOpen) {
    app.dom.menuDropdown.classList.toggle("touch-submenus", shouldUseTapSubmenus());
    app.dom.menuDropdown.classList.remove("hidden");
    // Ensure submenus open inside the visible bounds (important in embedded panels).
    try {
      adjustSubmenuPosition(app.dom.menuGuiGroup, app.dom.menuGuiSub);
      adjustSubmenuPosition(app.dom.menuAccountGroup, app.dom.menuAccountSub);
    } catch (_err) {}
    return;
  }
  app.dom.menuDropdown.classList.add("hidden");
}

function hideMenu() {
  app.dom.menuDropdown.classList.add("hidden");
  closeTouchSubmenus();
}

function closeAnyContextMenus() {
  const m = app.dom._sendContextMenu;
  if (m && m.remove) m.remove();
  app.dom._sendContextMenu = null;
}

function openSendContextMenu(x, y) {
  closeAnyContextMenus();

  const pid = app.state.ui.activePid;
  const sid = app.state.ui.activeSid;
  if (!pid || !sid) return;

  const ctx = getPluginContext();
  const items = [];

  for (const entry of app.plugins.slots.sendContextMenuItems || []) {
    const fn = entry.fn || entry;
    const out = fn({ pid, sid }, ctx);
    if (!out) continue;
    if (Array.isArray(out)) items.push(...out);
    else items.push(out);
  }

  const usable = items.filter((it) => it && it.label && typeof it.onClick === "function" && it.hidden !== true);
  if (!usable.length) return;

  const menu = document.createElement("div");
  menu.className = "action-menu";
  menu.style.position = "fixed";
  menu.style.left = `${x}px`;
  menu.style.top = `${y}px`;
  menu.style.zIndex = 3000;

  for (const it of usable) {
    const btn = document.createElement("button");
    btn.className = "action-menu-item";
    btn.textContent = it.label;
    btn.addEventListener("click", async () => {
      try {
        await it.onClick();
      } finally {
        closeAnyContextMenus();
      }
    });
    menu.appendChild(btn);
  }

  getEmbedMount().appendChild(menu);
  app.dom._sendContextMenu = menu;

  setTimeout(() => {
    const onDown = (ev) => {
      if (!menu.contains(ev.target)) {
        closeAnyContextMenus();
        document.removeEventListener("mousedown", onDown, true);
      }
    };
    document.addEventListener("mousedown", onDown, true);
  }, 0);
}

function toggleSessionDropdown() {
  if (!app.dom.sessionDropdown) return;
  const hidden = app.dom.sessionDropdown.classList.contains("hidden");
  if (hidden) {
    renderSessionDropdown();
    app.dom.sessionDropdown.classList.remove("hidden");
    if (remoteEnabled()) {
      void refreshSessions({ refreshMessages: false }).then(() => {
        if (!app.dom.sessionDropdown.classList.contains("hidden")) {
          renderSessionDropdown();
        }
      });
    }
  } else {
    hideSessionDropdown();
  }
}

function hideSessionDropdown() {
  if (!app.dom.sessionDropdown) return;
  app.dom.sessionDropdown.classList.add("hidden");
}

function toggleProjectDropdown() {
  if (!app.dom.projectDropdown) return;
  const hidden = app.dom.projectDropdown.classList.contains("hidden");
  if (hidden) {
    renderProjectDropdown();
    app.dom.projectDropdown.classList.remove("hidden");
    if (remoteEnabled()) {
      void refreshProjects({ refreshSessions: false }).then(() => {
        if (!app.dom.projectDropdown.classList.contains("hidden")) {
          renderProjectDropdown();
        }
      });
    }
  } else {
    hideProjectDropdown();
  }
}

function hideProjectDropdown() {
  if (!app.dom.projectDropdown) return;
  app.dom.projectDropdown.classList.add("hidden");
}

function renderProjectDropdown() {
  if (!app.dom.projectDropdown) return;
  const pid = app.state.ui.activePid;
  const projects = Object.values(app.state.projects || {}).filter((proj) =>
    remoteEnabled() ? proj?.source === "remote" : proj?.source !== "remote"
  );
  projects.sort((a, b) => (a.name || a.pid).localeCompare(b.name || b.pid));
  app.dom.projectDropdown.innerHTML = "";
  const addCreateProjectAction = () => {
    if (!hasPermission("projects.create", false)) return;
    const sep = document.createElement("div");
    sep.style.height = "1px";
    sep.style.background = "var(--border)";
    sep.style.margin = "6px 4px";
    sep.style.opacity = "0.6";
    app.dom.projectDropdown.appendChild(sep);

    const btn = document.createElement("button");
    btn.className = "menu-item";
    btn.textContent = i18nTranslate("chat_js.projects.new_project", "+ New Project...");
    btn.style.fontWeight = "600";
    btn.addEventListener("click", () => {
      hideProjectDropdown();
      void createProject();
    });
    app.dom.projectDropdown.appendChild(btn);
  };
  if (projects.length === 0) {
    const empty = document.createElement("div");
    empty.className = "menu-item";
    empty.textContent = i18nTranslate("chat_js.projects.no_projects", "No projects");
    empty.style.pointerEvents = "none";
    app.dom.projectDropdown.appendChild(empty);
    addCreateProjectAction();
    return;
  }
  projects.forEach((proj) => {
    const btn = document.createElement("button");
    btn.className = "menu-item";
    btn.textContent = proj.name || proj.pid;
    if (proj.pid === pid) {
      btn.style.borderColor = "var(--accent)";
      btn.style.fontWeight = "600";
    }
    btn.addEventListener("click", async () => {
      hideProjectDropdown();
      await selectProject(proj.pid);
    });
    app.dom.projectDropdown.appendChild(btn);
  });
  addCreateProjectAction();
}

function toggleSessionDropdownToolbar() {
  if (!app.dom.sessionDropdownToolbar) return;
  const hidden = app.dom.sessionDropdownToolbar.classList.contains("hidden");
  if (hidden) {
    renderSessionDropdownToolbar();
    app.dom.sessionDropdownToolbar.classList.remove("hidden");
    if (remoteEnabled()) {
      void refreshSessions({ refreshMessages: false }).then(() => {
        if (!app.dom.sessionDropdownToolbar.classList.contains("hidden")) {
          renderSessionDropdownToolbar();
        }
      });
    }
  } else {
    hideSessionDropdownToolbar();
  }
}

function hideSessionDropdownToolbar() {
  if (!app.dom.sessionDropdownToolbar) return;
  app.dom.sessionDropdownToolbar.classList.add("hidden");
}

function renderSessionDropdownToolbar() {
  if (!app.dom.sessionDropdownToolbar) return;
  const pid = app.state.ui.activePid;
  const sid = app.state.ui.activeSid;
  const list = Object.values(app.state.sessions || {}).filter((s) => {
    if (s.pid !== pid) return false;
    return remoteEnabled() ? s?.source === "remote" : s?.source !== "remote";
  });
  list.sort((a, b) => (a.title || a.sid).localeCompare(b.title || b.sid));
  app.dom.sessionDropdownToolbar.innerHTML = "";
  const addCreateSessionAction = () => {
    if (!hasPermission("sessions.create", false)) return;
    const sep = document.createElement("div");
    sep.style.height = "1px";
    sep.style.background = "var(--border)";
    sep.style.margin = "6px 4px";
    sep.style.opacity = "0.6";
    app.dom.sessionDropdownToolbar.appendChild(sep);

    const btn = document.createElement("button");
    btn.className = "menu-item";
    btn.textContent = i18nTranslate("chat_js.sessions.new_session", "+ New Session...");
    btn.style.fontWeight = "600";
    btn.addEventListener("click", () => {
      hideSessionDropdownToolbar();
      void createSession();
    });
    app.dom.sessionDropdownToolbar.appendChild(btn);
  };
  if (!pid || list.length === 0) {
    const empty = document.createElement("div");
    empty.className = "menu-item";
    empty.textContent = i18nTranslate("chat_js.sessions.no_sessions", "No sessions");
    empty.style.pointerEvents = "none";
    app.dom.sessionDropdownToolbar.appendChild(empty);
    addCreateSessionAction();
    return;
  }
  list.forEach((sess) => {
    const btn = document.createElement("button");
    btn.className = "menu-item";
    btn.textContent = sess.title || sess.sid;
    if (sess.sid === sid) {
      btn.style.borderColor = "var(--accent)";
      btn.style.fontWeight = "600";
    }
    btn.addEventListener("click", async () => {
      hideSessionDropdownToolbar();
      await selectSession(sess.sid);
    });
    app.dom.sessionDropdownToolbar.appendChild(btn);
  });
  addCreateSessionAction();
}

function handleRosterClick() {
  const handlers = app.plugins.slots.rosterActions || [];
  if (!handlers.length) return;
  const ctx = getPluginContext();
  for (const entry of handlers) {
    const fn = entry.fn || entry;
    try {
      fn?.(ctx);
    } catch (err) {
      appendLog(`[roster] ${err.message || err}`, "warn");
    }
  }
}

function renderSessionDropdown() {
  if (!app.dom.sessionDropdown) return;
  const pid = app.state.ui.activePid;
  const sid = app.state.ui.activeSid;
  const list = Object.values(app.state.sessions || {}).filter((s) => {
    if (s.pid !== pid) return false;
    return remoteEnabled() ? s?.source === "remote" : s?.source !== "remote";
  });
  list.sort((a, b) => (a.title || a.sid).localeCompare(b.title || b.sid));
  app.dom.sessionDropdown.innerHTML = "";
  const addCreateSessionAction = () => {
    if (!hasPermission("sessions.create", false)) return;
    const sep = document.createElement("div");
    sep.style.height = "1px";
    sep.style.background = "var(--border)";
    sep.style.margin = "6px 4px";
    sep.style.opacity = "0.6";
    app.dom.sessionDropdown.appendChild(sep);

    const btn = document.createElement("button");
    btn.className = "menu-item";
    btn.textContent = i18nTranslate("chat_js.sessions.new_session", "+ New Session...");
    btn.style.fontWeight = "600";
    btn.addEventListener("click", () => {
      hideSessionDropdown();
      void createSession();
    });
    app.dom.sessionDropdown.appendChild(btn);
  };
  if (!pid || list.length === 0) {
    const empty = document.createElement("div");
    empty.className = "menu-item";
    empty.textContent = i18nTranslate("chat_js.sessions.no_sessions", "No sessions");
    empty.style.pointerEvents = "none";
    app.dom.sessionDropdown.appendChild(empty);
    addCreateSessionAction();
    return;
  }
  list.forEach((sess) => {
    const btn = document.createElement("button");
    btn.className = "menu-item";
    btn.textContent = sess.title || sess.sid;
    if (sess.sid === sid) {
      btn.style.borderColor = "var(--accent)";
      btn.style.fontWeight = "600";
    }
    btn.addEventListener("click", async () => {
      hideSessionDropdown();
      await selectSession(sess.sid);
    });
    app.dom.sessionDropdown.appendChild(btn);
  });
  addCreateSessionAction();
}

function bindSubmenuPositioning() {
  const pairs = [
    [app.dom.menuGuiGroup, app.dom.menuGuiSub],
    [app.dom.menuAccountGroup, app.dom.menuAccountSub],
  ];
  for (const [group, sub] of pairs) {
    if (!group || !sub) continue;
    const adjust = () => adjustSubmenuPosition(group, sub);
    group.addEventListener("mouseenter", adjust);
    group.addEventListener("pointerenter", adjust);
    group.addEventListener("pointerdown", adjust);
    group.addEventListener("focusin", adjust);
    sub.addEventListener("scroll", () => updateSubmenuOverflowIndicator(sub), { passive: true });
  }
  window.addEventListener("resize", () => {
    for (const [group, sub] of pairs) {
      if (!group || !sub) continue;
      adjustSubmenuPosition(group, sub);
    }
  });
}

function adjustSubmenuPosition(group, sub) {
  if (!group || !sub) return;
  if (sub.classList.contains("hidden") || sub.children.length === 0) return;
  if (shouldUseTapSubmenus()) {
    sub.classList.remove("menu-left");
    sub.style.top = "";
    sub.style.maxHeight = "";
    sub.style.overflowY = "";
    sub.style.display = "";
    sub.style.visibility = "";
    sub.style.pointerEvents = "";
    updateSubmenuOverflowIndicator(sub);
    return;
  }

  const prev = {
    display: sub.style.display,
    visibility: sub.style.visibility,
    pointerEvents: sub.style.pointerEvents,
  };
  sub.style.top = "";
  sub.style.maxHeight = "";
  sub.style.overflowY = "";
  sub.style.display = "flex";
  sub.style.visibility = "hidden";
  sub.style.pointerEvents = "none";

  const groupRect = group.getBoundingClientRect();
  const subRect = sub.getBoundingClientRect();
  let boundsLeft = 0;
  let boundsRight = window.innerWidth;
  try {
    const mount = getEmbedMount?.();
    if (mount && mount !== document.body && mount !== document.documentElement) {
      const rect = mount.getBoundingClientRect();
      // Keep flyouts viewport-aware first. Some embeds sit inside narrower
      // wrappers even when the browser still has room, and shrinking the
      // bounds to that wrapper forces unnecessary left-flips.
      if (Number.isFinite(rect.left)) boundsLeft = Math.min(boundsLeft, rect.left);
      if (Number.isFinite(rect.right)) boundsRight = Math.max(boundsRight, rect.right);
    }
  } catch (_err) {}
  const spaceRight = boundsRight - groupRect.right;
  const spaceLeft = groupRect.left - boundsLeft;
  let openLeft = false;
  if (spaceRight < subRect.width + 12) {
    openLeft = spaceLeft >= subRect.width + 12 || spaceLeft > spaceRight;
  }
  sub.classList.toggle("menu-left", openLeft);

  const viewportTop = 12;
  const viewportBottom = window.innerHeight - 12;
  const computedTop = Number.parseFloat(window.getComputedStyle(sub).top || "0") || 0;
  const minTop = viewportTop - groupRect.top;
  const maxTop = viewportBottom - groupRect.top - subRect.height;
  const clampedTop = Math.min(Math.max(computedTop, minTop), maxTop);
  sub.style.top = `${Math.round(clampedTop)}px`;

  const visibleTop = groupRect.top + clampedTop;
  const availableHeight = Math.max(96, viewportBottom - visibleTop);
  if (subRect.height > availableHeight) {
    sub.style.maxHeight = `${Math.floor(availableHeight)}px`;
    sub.style.overflowY = "auto";
  }

  sub.style.display = prev.display;
  sub.style.visibility = prev.visibility;
  sub.style.pointerEvents = prev.pointerEvents;
  updateSubmenuOverflowIndicator(sub);
}

function updateSubmenuOverflowIndicator(sub) {
  if (!sub) return;
  if (sub.id === "menu-gui-sub") {
    sub.classList.remove("has-overflow");
    return;
  }
  const scrollHost = Array.from(sub.children || []).find((child) => child?.classList?.contains?.("menu-sub-scroll")) || sub;
  const hasOverflow = (scrollHost.scrollHeight - scrollHost.clientHeight) > 4;
  const atBottom = (scrollHost.scrollHeight - scrollHost.scrollTop - scrollHost.clientHeight) <= 4;
  sub.classList.toggle("has-overflow", Boolean(hasOverflow && !atBottom));
}

function openTools(panelId) {
  const titleMap = {
    chats: i18nTranslate("chat_js.menu.chats", "Chats"),
    config: i18nTranslate("chat_js.menu.config", "Config"),
    plugins: i18nTranslate("chat_js.menu.plugins", "Plugins"),
    "gui-plugins": i18nTranslate("chat_js.menu.gui_plugins", "Plugin Settings"),
    account: i18nTranslate("chat_js.menu.account", "Account"),
  };
  let target = panelId || "chats";
  if (target === "config" && !hasPermission("ui.config.view", false)) target = "chats";
  if (target === "plugins" && !hasPermission("ui.plugins.view", false)) target = "chats";
  if (target === "gui-plugins" && !hasPermission("ui.gui_plugins.view", false)) target = "chats";
  if (target === "account" && !(hasPermission("ui.account.view", true) || !app.state.auth.token)) target = "chats";
  if (target === "plugins" || target === "gui-plugins" || target === "account") {
    void ensurePluginsLoaded();
  }
  setActiveToolSection(target);
  if (target === "chats") {
    renderChatsOverride();
    app.dom.modalTitle.textContent = getChatsPanelTitle();
  } else if (target === "gui-plugins") {
    updateGuiPluginsTitle();
  } else {
    app.dom.modalTitle.textContent = titleMap[target] || i18nTranslate("chat_js.modal.tools", "Tools");
  }
  app.dom.toolsModal.classList.remove("hidden");
  hideMenu();
}

function closeTools() {
  app.dom.toolsModal.classList.add("hidden");
  applyToolsWindowMode("");
}

function toggleLog() {
  app.state.ui.showLog = !app.state.ui.showLog;
  applyLogVisibility();
  scheduleSave();
}

function applyLogVisibility() {
  if (app.state.ui.showLog) {
    app.dom.logPanel.classList.remove("hidden");
    app.dom.logToggleBtn.textContent = i18nTranslate("chat_js.log.hide", "Hide Log");
  } else {
    app.dom.logPanel.classList.add("hidden");
    app.dom.logToggleBtn.textContent = i18nTranslate("chat_js.log.show", "Show Log");
  }
}

function getChatsPanelTitle() {
  const override = app.plugins.chatsOverride;
  if (override && isPluginEnabled(override.pluginId)) {
    return override.title || i18nTranslate("chat_js.menu.chats", "Chats");
  }
  return i18nTranslate("chat_js.menu.chats", "Chats");
}

function setChatsOverride(pluginId, override) {
  const key = String(pluginId || "");
  if (!key) return;
  if (!override) {
    clearChatsOverride(key);
    return;
  }
  app.plugins.chatsOverride = { ...override, pluginId: key };
  renderChatsOverride();
}

function clearChatsOverride(pluginId) {
  const key = String(pluginId || "");
  if (!key) return;
  if (app.plugins.chatsOverride?.pluginId !== key) return;
  app.plugins.chatsOverride = null;
  renderChatsOverride();
}

function renderChatsOverride() {
  if (!app.dom.chatsDefault || !app.dom.chatsOverride) return;
  const override = app.plugins.chatsOverride;
  if (override && isPluginEnabled(override.pluginId)) {
    app.dom.chatsDefault.classList.add("hidden");
    app.dom.chatsOverride.classList.remove("hidden");
    app.dom.chatsOverride.innerHTML = "";
    try {
      override.render?.(app.dom.chatsOverride, getPluginContext());
    } catch (err) {
      app.dom.chatsOverride.textContent = i18nTranslate("chat_js.errors.override_render_failed", "Failed to render override.");
      appendLog(`[chats] override error: ${err.message || err}`, "warn");
    }
  } else {
    app.dom.chatsOverride.classList.add("hidden");
    app.dom.chatsOverride.innerHTML = "";
    app.dom.chatsDefault.classList.remove("hidden");
  }
  const activePanel = app.dom.toolsModal?.querySelector(".tool-section.active");
  if (activePanel?.dataset.panel === "chats") {
    app.dom.modalTitle.textContent = getChatsPanelTitle();
  }
}

function updateGuiPluginsTitle() {
  const pluginId = app.state.ui.activeGuiPluginId;
  if (pluginId && isPluginEnabled(pluginId)) {
    const info = app.plugins.meta[pluginId];
    const label = info?.name || pluginId;
    app.dom.modalTitle.textContent = label;
    if (app.dom.guiPluginsTitle) {
      app.dom.guiPluginsTitle.classList.add("hidden");
    }
  } else {
    app.dom.modalTitle.textContent = i18nTranslate("chat_js.menu.gui_plugins", "Plugin Settings");
    if (app.dom.guiPluginsTitle) {
      app.dom.guiPluginsTitle.classList.remove("hidden");
    }
  }
}

function clearGuiPluginsContext() {
  app.state.ui.activeGuiPluginId = "";
  scheduleSave();
  updateGuiPluginsTitle();
  renderPluginPanels({ force: true });
  applyToolsWindowMode("gui-plugins");
  if (app.dom.guiPluginsTitle) {
    app.dom.guiPluginsTitle.classList.remove("hidden");
  }
}

function setAccountActions(pluginId, actions) {
  const key = String(pluginId || "");
  if (!key) return;
  const list = Array.isArray(actions) ? actions : [];
  const filtered = app.plugins.accountActions.filter((item) => item.pluginId !== key);
  for (const action of list) {
    if (!action || !action.id) continue;
    filtered.push({ ...action, pluginId: key });
  }
  app.plugins.accountActions = filtered;
  renderAccountMenu();
}

function clearAccountActions(pluginId) {
  const key = String(pluginId || "");
  if (!key) return;
  app.plugins.accountActions = app.plugins.accountActions.filter((item) => item.pluginId !== key);
  renderAccountMenu();
}

function renderGuiPluginsMenu() {
  if (!app.dom.menuGuiSub) return;
  app.dom.menuGuiSub.innerHTML = "";
  if (!hasPermission("ui.gui_plugins.view", false)) {
    app.dom.menuGuiSub.classList.add("hidden");
    return;
  }
  const frontendItems = app.plugins.list.filter((plugin) => {
    const enabled = Boolean(plugin.enabled ?? isPluginEnabled(plugin.id));
    return enabled && plugin.status === "loaded" && plugin.hasPanel && canAccessPlugin(plugin.id, "open");
  });
  const manifest = getRouterManifest();
  if (!Object.keys(manifest).length && canUseRemoteServer() && !app.routerManifestInFlight) {
    void refreshRouterManifest(false);
  }
  const activeSid = String(app.state?.ui?.activeSid || "").trim();
  const routerState = activeSid ? getRouterConfig(activeSid) : getProjectRouterDefaults();
  const enabledServerIds = new Set(
    Array.isArray(routerState?.enabled)
      ? routerState.enabled.map((value) => String(value || "").trim()).filter(Boolean)
      : []
  );
  const serverItems = Object.keys(manifest)
    .filter((pid) => enabledServerIds.has(String(pid || "").trim()))
    .map((pid) => ({ id: pid, meta: manifest[pid] || {} }))
    .sort((a, b) => String(a.meta.title || a.id).localeCompare(String(b.meta.title || b.id)));
  const appendActionButton = (host, label, onClick) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "menu-item";
    btn.textContent = label;
    bindMenuActionButton(btn, () => {
      onClick();
      hideMenu();
    });
    host.appendChild(btn);
  };
  const buildNestedFlyoutGroup = (host, title, menuId, rowsBuilder, levelClass = "menu-sub-level3") => {
    const group = document.createElement("div");
    group.className = "menu-group";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "menu-item has-sub";
    btn.dataset.menu = menuId;
    btn.textContent = title;
    const sub = document.createElement("div");
    sub.className = shouldUseTapSubmenus() ? `menu-sub ${levelClass} hidden` : `menu-sub ${levelClass}`;
    rowsBuilder(sub);
    bindMenuActionButton(btn, () => {
      if (shouldUseTapSubmenus()) {
        toggleTouchSubmenu(menuId);
        return;
      }
      toggleDesktopSubmenu(menuId);
    });
    group.appendChild(btn);
    group.appendChild(sub);
    const adjust = () => adjustSubmenuPosition(group, sub);
    group.addEventListener("mouseenter", adjust);
    group.addEventListener("pointerenter", adjust);
    group.addEventListener("pointerdown", adjust);
    group.addEventListener("focusin", adjust);
    sub.addEventListener("scroll", () => updateSubmenuOverflowIndicator(sub), { passive: true });
    host.appendChild(group);
  };

  const buildFrontendFlyout = (sub) => {
    const items = frontendItems.slice().sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id));
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "menu-item";
      empty.textContent = "No enabled frontend plugin settings";
      empty.style.pointerEvents = "none";
      sub.appendChild(empty);
      return;
    }
    const grouped = new Map();
    const ungrouped = [];
    for (const plugin of items) {
      const category = String(plugin?.meta?.category || plugin?.entry?.category || "").trim();
      if (!category) {
        ungrouped.push(plugin);
        continue;
      }
      if (!grouped.has(category)) grouped.set(category, []);
      grouped.get(category).push(plugin);
    }
    for (const category of Array.from(grouped.keys()).sort((a, b) => a.localeCompare(b))) {
      const categoryMenuId = `plugin-settings-frontend-${String(category).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "group"}`;
      buildNestedFlyoutGroup(sub, category, categoryMenuId, (categorySub) => {
        const categoryItems = (grouped.get(category) || []).slice().sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id));
        for (const plugin of categoryItems) {
          appendActionButton(categorySub, plugin.name || plugin.id, () => {
            openPluginPanel(plugin.id, { openModal: true });
          });
        }
      }, "menu-sub-level3");
    }
    for (const plugin of ungrouped) {
      appendActionButton(sub, plugin.name || plugin.id, () => {
        openPluginPanel(plugin.id, { openModal: true });
      });
    }
  };

  const buildServerFlyout = (sub) => {
    if (!serverItems.length) {
      const empty = document.createElement("div");
      empty.className = "menu-item";
      empty.textContent = canUseRemoteServer() ? "No discovered server plugin settings" : "Connect to a server to load server plugin settings";
      empty.style.pointerEvents = "none";
      sub.appendChild(empty);
      return;
    }
    const grouped = new Map();
    const ungrouped = [];
    for (const item of serverItems) {
      const category = String(item?.meta?.category || "").trim();
      if (!category) {
        ungrouped.push(item);
        continue;
      }
      if (!grouped.has(category)) grouped.set(category, []);
      grouped.get(category).push(item);
    }
    for (const category of Array.from(grouped.keys()).sort((a, b) => a.localeCompare(b))) {
      const categoryMenuId = `plugin-settings-server-${String(category).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "group"}`;
      buildNestedFlyoutGroup(sub, category, categoryMenuId, (categorySub) => {
        const categoryItems = (grouped.get(category) || []).slice().sort((a, b) => String(a.meta.title || a.id).localeCompare(String(b.meta.title || b.id)));
        for (const item of categoryItems) {
          appendActionButton(categorySub, item.meta.title || item.id, () => {
            void openRouterSettings(item.id);
          });
        }
      }, "menu-sub-level3");
    }
    for (const item of ungrouped) {
      appendActionButton(sub, item.meta.title || item.id, () => {
        void openRouterSettings(item.id);
      });
    }
  };

  const appendFlyoutGroup = (title, menuId, builder) => {
    const group = document.createElement("div");
    group.className = "menu-group";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "menu-item has-sub";
    btn.dataset.menu = menuId;
    btn.textContent = title;
    const sub = document.createElement("div");
    sub.className = shouldUseTapSubmenus() ? "menu-sub menu-sub-level2 hidden" : "menu-sub menu-sub-level2";
    const scroll = document.createElement("div");
    scroll.className = "menu-sub-scroll menu-sub-level2-scroll";
    builder(scroll);
    sub.appendChild(scroll);
    bindMenuActionButton(btn, () => {
      if (shouldUseTapSubmenus()) {
        toggleTouchSubmenu(menuId);
        return;
      }
      toggleDesktopSubmenu(menuId);
    });
    group.appendChild(btn);
    group.appendChild(sub);
    const adjust = () => adjustSubmenuPosition(group, sub);
    group.addEventListener("mouseenter", adjust);
    group.addEventListener("pointerenter", adjust);
    group.addEventListener("pointerdown", adjust);
    group.addEventListener("focusin", adjust);
    scroll.addEventListener("scroll", () => updateSubmenuOverflowIndicator(sub), { passive: true });
    app.dom.menuGuiSub.appendChild(group);
  };

  appendFlyoutGroup("Frontend", "plugin-settings-frontend", buildFrontendFlyout);
  appendFlyoutGroup("Server", "plugin-settings-server", buildServerFlyout);

  app.dom.menuGuiSub.classList.toggle("hidden", false);
  // If this submenu is shown inside an embed panel, update the left/right opening
  // immediately after items are rendered.
  queueMicrotask(() => {
    try {
      adjustSubmenuPosition(app.dom.menuGuiGroup, app.dom.menuGuiSub);
    } catch (_err) {}
  });
}

function renderAccountMenu() {
  if (!app.dom.menuAccountSub) return;
  app.dom.menuAccountSub.innerHTML = "";
  if (!isAuthEnabled()) return;
  if (!(hasPermission("ui.account.view", true) || !app.state.auth.token)) {
    app.dom.menuAccountSub.classList.add("hidden");
    return;
  }
  const authed = Boolean(app.state.auth.token);
  const actions = app.plugins.accountActions.filter((action) => {
    if (!action) return false;
    if (action.pluginId && !canAccessPlugin(action.pluginId, "view")) return false;
    if (authed) {
      if (action.hideWhenLoggedIn) return false;
      return true;
    }
    if (action.showWhenLoggedOut) return true;
    if (action.requiresAuth === false) return true;
    return false;
  });
  for (const action of actions) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "menu-item";
    btn.dataset.accountAction = action.id;
    btn.textContent = action.label || action.id;
    bindMenuActionButton(btn, () => {
      handleAccountAction(action.id);
      hideMenu();
    });
    app.dom.menuAccountSub.appendChild(btn);
  }
  app.dom.menuAccountSub.classList.toggle("hidden", actions.length === 0);
  queueMicrotask(() => {
    try {
      adjustSubmenuPosition(app.dom.menuAccountGroup, app.dom.menuAccountSub);
    } catch (_err) {}
  });
}

function handleAccountAction(actionId) {
  const action = app.plugins.accountActions.find((item) => item.id === actionId);
  if (!action) return;
  try {
    action.onClick?.(getPluginContext());
  } catch (err) {
    appendLog(`[account] action failed: ${err.message || err}`, "warn");
  }
}

async function bootstrapRemote() {
  if (app.bootstrapRemoteInFlight) {
    app.bootstrapRemotePending = true;
    return app.bootstrapRemoteInFlight;
  }
  app.bootstrapRemoteInFlight = (async () => {
    if (!canUseRemoteServer()) {
      renderStatus();
      renderProjectList();
      renderSessionList();
      renderToolbar();
      return;
    }
    renderStatus("connecting");
    if (!app.state.auth.token) {
      stopSessionEvents();
      renderStatus();
      renderProjectList();
      renderSessionList();
      renderToolbar();
      return;
    }
    const ok = await verifyAuth();
    if (!ok) {
      stopSessionEvents();
      renderStatus();
      renderProjectList();
      renderSessionList();
      renderToolbar();
      return;
    }
    const desiredPid = app.state.ui.activePid || app.embedDefaults.pid || "";
    const desiredSid = app.state.ui.activeSid || app.embedDefaults.sid || "";
    // In embed mode, saved state wins. Embed pid/sid are fallbacks only and
    // should not pull the user back to "main" on every refresh.
    await refreshProjects({ refreshSessions: false });
    if (desiredPid) {
      await ensureRemoteProjectAndSession(desiredPid, desiredSid);
    } else {
      await refreshSessions();
    }
    if (app.state.ui.activePid) {
      await loadProjectRouterPrefs(app.state.ui.activePid);
    }
    if (hasKnownRemoteSession(app.state.ui.activePid, app.state.ui.activeSid)) {
      startSessionEvents();
    }
    renderProjectList();
    renderSessionList();
    renderToolbar();
  })();
  try {
    return await app.bootstrapRemoteInFlight;
  } finally {
    app.bootstrapRemoteInFlight = null;
    if (app.bootstrapRemotePending) {
      app.bootstrapRemotePending = false;
      setTimeout(() => {
        if (app.state.auth?.token && canUseRemoteServer()) {
          void bootstrapRemote();
        }
      }, 0);
    }
  }
}

async function bootstrapGuestRemote() {
  const desiredPid = app.state.ui.activePid || app.embedDefaults.pid || "";
  const desiredSid = app.state.ui.activeSid || app.embedDefaults.sid || "";
  await refreshProjects({ refreshSessions: false });
  if (desiredPid) {
    app.state.ui.activePid = desiredPid;
    await refreshSessions({ refreshMessages: false });
    await loadProjectRouterPrefs(app.state.ui.activePid);
    if (desiredSid && app.state.sessions?.[desiredSid]?.source === "remote") {
      app.state.ui.activeSid = desiredSid;
    }
  } else {
    await refreshSessions({ refreshMessages: false });
  }
  const pid = app.state.ui.activePid || "";
  const sid = app.state.ui.activeSid || "";
  if (!pid || !sid) return;
  await refreshSessionAccess();
  const access = getActiveSessionAccess();
  if (!access?.can_access || !access?.allow_guest) return;
  const prev = app.state.sessions[sid] || {};
  app.state.sessions[sid] = {
    ...prev,
    sid,
    pid,
    title: prev.title || sid,
    is_public: Boolean(access.session_is_public),
    allow_guest: Boolean(access.allow_guest),
    messages: prev.messages || [],
    source: "remote",
  };
  renderProjectList();
  renderSessionList();
  renderToolbar();
  await loadSessionMessages();
  renderTranscript();
  startSessionEvents();
  void refreshRosterSnapshot();
}

function remoteEnabled() {
  return hasRemoteAuth();
}

function useCollabStream() {
  return Boolean(isAuthEnabled() && remoteEnabled());
}

function hasKnownRemoteSession(pid, sid) {
  const usePid = String(pid || "").trim();
  const useSid = String(sid || "").trim();
  if (!usePid || !useSid) return false;
  const sess = app.state.sessions?.[useSid];
  return Boolean(sess && sess.source === "remote" && String(sess.pid || "") === usePid);
}

async function ensureRemoteProjectAndSession(pid, sid) {
  const wantPid = String(pid || "").trim();
  const wantSid = String(sid || "").trim();
  if (!wantPid || !remoteEnabled()) return;

  function hasRemoteProject(p) {
    return Boolean(app.state.projects?.[p] && app.state.projects[p].source === "remote");
  }

  function hasRemoteSession(p, s) {
    const sess = app.state.sessions?.[s];
    return Boolean(sess && sess.source === "remote" && String(sess.pid || "") === p);
  }

  // 1) Ensure project exists.
  if (!hasRemoteProject(wantPid)) {
    try {
      const name = wantPid === "default" ? "Default" : wantPid;
      await apiJson("/v1/projects", { method: "POST", body: { pid: wantPid, name } });
    } catch (err) {
      appendLog(`[projects] ensure failed for ${wantPid}: ${err.message || err}`, "warn");
    }
    // Refresh project list (without cascading into sessions yet).
    await refreshProjects({ refreshSessions: false });
  }

  if (!hasRemoteProject(wantPid)) {
    // If we can't create/select the requested project, don't attempt to open
    // sessions/events against a non-existent pid (will 404).
    return;
  }

  // Keep the requested pid selected if it exists remotely.
  app.state.ui.activePid = wantPid;
  scheduleSave();

  // 2) Load sessions for the project.
  await refreshSessions({ refreshMessages: false });

  // 3) Only create the requested session as a last resort when the project has
  // no sessions at all. If sessions exist, prefer the existing one selected by
  // `refreshSessions()` instead of forcing the embed default back to "main".
  const remoteSessionsForProject = Object.values(app.state.sessions || {}).filter((sess) => {
    return sess?.source === "remote" && String(sess.pid || "") === wantPid;
  });
  if (wantSid && !hasRemoteSession(wantPid, wantSid) && remoteSessionsForProject.length === 0) {
    try {
      await apiJson(`/v1/projects/${encodeURIComponent(wantPid)}/sessions`, {
        method: "POST",
        headers: buildHeaders({ pid: wantPid }),
        body: { sid: wantSid, title: wantSid },
      });
    } catch (err) {
      appendLog(`[sessions] ensure failed for ${wantPid}/${wantSid}: ${err.message || err}`, "warn");
    }
    await refreshSessions({ refreshMessages: false });
  }

  if (wantSid && hasRemoteSession(wantPid, wantSid)) {
    app.state.ui.activeSid = wantSid;
    scheduleSave();
    // Ensure transcript is hydrated for the selected session.
    await loadSessionMessages();
    renderTranscript();
    renderToolbar();
    renderTopRightIconRow();
    renderTranscriptBars();
    renderPluginPanels();
    renderRouterPluginsList();
    emitSessionChange();
  } else if (app.state.ui.activeSid) {
    // `refreshSessions()` already chose a valid existing remote session.
    scheduleSave();
    await loadSessionMessages();
    renderTranscript();
    renderToolbar();
    renderTopRightIconRow();
    renderTranscriptBars();
    renderPluginPanels();
    renderRouterPluginsList();
    emitSessionChange();
  }
}

function emptyPermissionsState() {
  return {
    ready: false,
    defaultRole: "user",
    roleIds: ["anonymous"],
    permissions: {
      "ui.account.view": true,
    },
    pluginAccess: {
      auth_projects: { view: true, open: true, settings: false },
    },
    pluginDefaults: { view: false, open: false, settings: false },
    isAdmin: false,
  };
}

function normalizePermissionFlag(value, fallback = false) {
  if (value === undefined || value === null) return fallback;
  if (typeof value === "string") {
    const low = value.trim().toLowerCase();
    if (["1", "true", "yes", "on"].includes(low)) return true;
    if (["0", "false", "no", "off"].includes(low)) return false;
  }
  return Boolean(value);
}

function normalizePluginAccessMap(map, defaults = null) {
  const baseDefaults = defaults && typeof defaults === "object"
    ? {
        view: normalizePermissionFlag(defaults.view, false),
        open: normalizePermissionFlag(defaults.open, false),
        settings: normalizePermissionFlag(defaults.settings, false),
      }
    : { view: false, open: false, settings: false };
  const out = {};
  if (!map || typeof map !== "object") return out;
  Object.entries(map).forEach(([pluginId, rule]) => {
    const key = String(pluginId || "").trim();
    if (!key || !rule || typeof rule !== "object") return;
    out[key] = {
      view: normalizePermissionFlag(rule.view, baseDefaults.view),
      open: normalizePermissionFlag(rule.open, baseDefaults.open),
      settings: normalizePermissionFlag(rule.settings, baseDefaults.settings),
    };
  });
  return out;
}

function normalizePermissionsState(payload) {
  const base = emptyPermissionsState();
  const src = payload && typeof payload === "object" ? payload : {};
  const summary = src.summary && typeof src.summary === "object" ? src.summary : src;
  const defaults = summary.plugin_defaults && typeof summary.plugin_defaults === "object"
    ? {
        view: normalizePermissionFlag(summary.plugin_defaults.view, false),
        open: normalizePermissionFlag(summary.plugin_defaults.open, false),
        settings: normalizePermissionFlag(summary.plugin_defaults.settings, false),
      }
    : base.pluginDefaults;
  const permissions = {};
  Object.entries(summary.permissions && typeof summary.permissions === "object" ? summary.permissions : {}).forEach(([key, value]) => {
    const name = String(key || "").trim();
    if (name) permissions[name] = normalizePermissionFlag(value, false);
  });
  const roleIds = Array.isArray(summary.role_ids)
    ? summary.role_ids.map((item) => String(item || "").trim()).filter(Boolean)
    : base.roleIds.slice();
  return {
    ready: true,
    defaultRole: String(summary.default_role || src.default_role || base.defaultRole).trim() || base.defaultRole,
    roleIds: roleIds.length ? roleIds : base.roleIds.slice(),
    permissions,
    pluginAccess: normalizePluginAccessMap(summary.plugin_access, defaults),
    pluginDefaults: defaults,
    isAdmin: normalizePermissionFlag(summary.is_admin, false) || normalizePermissionFlag(permissions["*"], false),
  };
}

function ensurePermissionsState() {
  if (!app.state.permissions || typeof app.state.permissions !== "object") {
    app.state.permissions = emptyPermissionsState();
  }
  return app.state.permissions;
}

function clearPermissionsState() {
  app.state.permissions = emptyPermissionsState();
}

function hasPermission(permissionKey, fallback = false) {
  const perms = ensurePermissionsState();
  if (perms.isAdmin || normalizePermissionFlag(perms.permissions?.["*"], false)) return true;
  const key = String(permissionKey || "").trim();
  if (!key) return true;
  if (!Object.prototype.hasOwnProperty.call(perms.permissions || {}, key)) return fallback;
  return normalizePermissionFlag(perms.permissions[key], fallback);
}

function pluginAccessRule(pluginId) {
  const perms = ensurePermissionsState();
  const defaults = perms.pluginDefaults || { view: false, open: false, settings: false };
  if (perms.isAdmin) {
    return { view: true, open: true, settings: true };
  }
  const wildcard = perms.pluginAccess?.["*"] || null;
  const exact = perms.pluginAccess?.[String(pluginId || "").trim()] || null;
  const out = {
    view: normalizePermissionFlag(defaults.view, false),
    open: normalizePermissionFlag(defaults.open, false),
    settings: normalizePermissionFlag(defaults.settings, false),
  };
  [wildcard, exact].forEach((rule) => {
    if (!rule || typeof rule !== "object") return;
    out.view = normalizePermissionFlag(rule.view, out.view);
    out.open = normalizePermissionFlag(rule.open, out.open);
    out.settings = normalizePermissionFlag(rule.settings, out.settings);
  });
  if (String(pluginId || "").trim() === "model_deck") {
    out.view = out.view || hasPermission("model_deck.view", false);
    out.open = out.open || out.view;
    out.settings = out.settings || hasPermission("model_deck.manage", false);
  }
  if (String(pluginId || "").trim() === "plugin_repo") {
    out.view = out.view || hasPermission("plugin_repo.view", false) || hasPermission("ui.plugins.view", false);
    out.open = out.open || out.view;
    out.settings = out.settings || hasPermission("plugins.manage.install", false);
  }
  if (String(pluginId || "").trim() === "permissions_manager") {
    out.view = out.view || hasPermission("permissions.view", false);
    out.open = out.open || out.view;
    out.settings = out.settings || hasPermission("permissions.manage", false);
  }
  return out;
}

function canAccessPlugin(pluginId, action = "view") {
  const key = String(pluginId || "").trim();
  if (!key) return true;
  const rule = pluginAccessRule(key);
  const mode = String(action || "view").trim().toLowerCase();
  if (mode === "settings") return Boolean(rule.settings);
  if (mode === "open") return Boolean(rule.open || rule.view);
  return Boolean(rule.view);
}

function setMenuItemVisible(openId, visible) {
  const btn = app.dom.menuDropdown?.querySelector?.(`.menu-item[data-open="${openId}"]`);
  if (btn) btn.classList.toggle("hidden", !visible);
}

function applyPermissionVisibility() {
  const showConfig = hasPermission("ui.config.view", false);
  const showPlugins = hasPermission("ui.plugins.view", false);
  const showGuiPlugins = hasPermission("ui.gui_plugins.view", false);
  const showAccount = hasPermission("ui.account.view", true) || !app.state.auth.token;
  setMenuItemVisible("config", showConfig);
  setMenuItemVisible("plugins", showPlugins);
  if (app.dom.menuGuiGroup) app.dom.menuGuiGroup.classList.toggle("hidden", !showGuiPlugins);
  if (app.dom.menuAccountGroup) app.dom.menuAccountGroup.classList.toggle("hidden", !showAccount);
  if (app.dom.projectAdd) app.dom.projectAdd.classList.toggle("hidden", !hasPermission("projects.create", false));
  if (app.dom.sessionAdd) app.dom.sessionAdd.classList.toggle("hidden", !hasPermission("sessions.create", false));
  const activePluginId = String(app.state.ui.activeGuiPluginId || "").trim();
  if (activePluginId && !canAccessPlugin(activePluginId, "open")) {
    app.state.ui.activeGuiPluginId = "";
  }
  const activeSection = app.dom.toolsModal?.querySelector?.(".tool-section.active")?.dataset?.panel || "";
  if ((activeSection === "config" && !showConfig) ||
      (activeSection === "plugins" && !showPlugins) ||
      (activeSection === "gui-plugins" && !showGuiPlugins) ||
      (activeSection === "account" && !showAccount)) {
    setActiveToolSection("chats");
    app.dom.modalTitle.textContent = getChatsPanelTitle();
  }
}

async function refreshPermissionState(options = {}) {
  const silent = options?.silent === true;
  try {
    const data = await apiJson("/v1/permissions/me", { timeoutMs: 8000 });
    app.state.permissions = normalizePermissionsState(data);
  } catch (err) {
    if (!silent) appendLog(`[permissions] ${err.message || err}`, "warn");
    clearPermissionsState();
  }
  applyPermissionVisibility();
  renderTopRightIconRow();
  renderTranscriptBars();
  renderComposerLeft();
  renderPluginPanels({ force: true });
  renderPluginTable();
  renderGuiPluginsMenu();
  renderAccountMenu();
  renderToolbar();
}

async function verifyAuth() {
  try {
    const data = await apiJson("/v1/auth/me");
    const user = data?.user || data || {};
    if (!user) return false;
    app.state.auth.username = user.username || app.state.auth.username;
    app.state.auth.role = user.role || app.state.auth.role;
    app.state.auth.mustChange = Boolean(user.must_change_pw);
    await refreshPermissionState({ silent: true });
    await refreshGuiPluginsDiscovery();
    await refreshSharedUiThemeDefault("theme_demo", { forceApply: true });
    scheduleSave();
    renderStatus("online");
    renderTopRightIconRow();
    applyChatInfoToInputs();
    return true;
  } catch (err) {
    appendLog("[auth] token invalid, logging out", "warn");
    await logout(false);
    return false;
  }
}

function renderAll() {
  updateLayout();
  applyPermissionVisibility();
  renderStatus();
  renderProjectList();
  renderSessionList();
  renderTranscript();
  renderToolbar();
  renderTopRightIconRow();
  renderTranscriptBars();
  renderRoster();
  renderAuthStatus();
  applyLogVisibility();
  applyAccountMenuVisibility();
  renderPluginTable();
  renderRouterPluginsList();
  renderPluginRepoPanel();
  renderGuiPluginsMenu();
  renderAccountMenu();
  renderChatsOverride();
  setActiveToolSection("chats");
  emitSessionChange();
}

function emitSessionChange() {
  const pid = app.state.ui.activePid || "";
  const sid = app.state.ui.activeSid || "";
  document.dispatchEvent(new CustomEvent("chat_js:session-changed", { detail: { pid, sid } }));
}

function renderStatus(forced) {
  const status = forced || ((remoteEnabled() || hasGuestSessionAccess()) ? "online" : "offline");
  const token = app.state.auth.token ? "auth" : (hasGuestSessionAccess() ? "guest" : "no auth");
  if (app.dom.serverStatus) {
    app.dom.serverStatus.textContent = `Server: ${status} (${token})`;
  }
  const sid = app.state.ui.activeSid || "none";
  if (app.dom.sessionStatus) {
    app.dom.sessionStatus.textContent = `Session: ${sid}`;
  }
  updateTopStatusVisibility();
}

function renderAuthStatus() {
  if (app.state.auth.token) {
    const name = app.state.auth.username || "user";
    const role = app.state.auth.role || "user";
    const statusText = `Logged in as ${name} (${role})`;
    if (app.dom.authStatus) app.dom.authStatus.textContent = statusText;
    if (app.dom.authStatusTop) app.dom.authStatusTop.textContent = name;
  } else {
    if (app.dom.authStatus) app.dom.authStatus.textContent = i18nTranslate("chat_js.auth.not_logged_in", "Not logged in");
    if (app.dom.authStatusTop) app.dom.authStatusTop.textContent = i18nTranslate("chat_js.menu.account", "Account");
  }
  updateTopStatusVisibility();
}

function updateTopStatusVisibility() {
  const authVisible = isAuthEnabled();
  if (app.dom.serverStatus) app.dom.serverStatus.classList.toggle("hidden", !authVisible);
  if (app.dom.rosterStatus) app.dom.rosterStatus.classList.toggle("hidden", !authVisible);
  if (app.dom.authStatusTop) app.dom.authStatusTop.classList.toggle("hidden", !authVisible);
  if (app.dom.toolbarRoster) app.dom.toolbarRoster.classList.toggle("hidden", !authVisible);
}

function renderProjectList() {
  const items = Object.values(app.state.projects).filter((proj) =>
    remoteEnabled() ? proj?.source === "remote" : proj?.source !== "remote"
  );
  items.sort((a, b) => (a.name || a.pid).localeCompare(b.name || b.pid));
  app.dom.projectList.innerHTML = "";
  for (const proj of items) {
    const item = document.createElement("div");
    item.className = "list-item" + (proj.pid === app.state.ui.activePid ? " active" : "");
    item.dataset.pid = proj.pid;
    item.innerHTML = `
      <div class="list-title">${escapeHtml(proj.name || proj.pid)}</div>
      <div class="list-meta">${escapeHtml(proj.pid)}</div>
    `;
    app.dom.projectList.appendChild(item);
  }
  if (app.dom.projectDropdown && !app.dom.projectDropdown.classList.contains("hidden")) {
    renderProjectDropdown();
  }
  renderToolbar();
}

function renderSessionList() {
  const pid = app.state.ui.activePid;
  const sessions = Object.values(app.state.sessions).filter((s) => {
    if (s.pid !== pid) return false;
    return remoteEnabled() ? s?.source === "remote" : s?.source !== "remote";
  });
  sessions.sort((a, b) => (a.title || a.sid).localeCompare(b.title || b.sid));
  app.dom.sessionList.innerHTML = "";
  for (const sess of sessions) {
    const item = document.createElement("div");
    item.className = "list-item" + (sess.sid === app.state.ui.activeSid ? " active" : "");
    item.dataset.sid = sess.sid;
    const titleRow = document.createElement("div");
    titleRow.className = "list-title-row";
    const title = document.createElement("div");
    title.className = "list-title";
    title.textContent = sess.title || sess.sid;
    titleRow.appendChild(title);
    if (isSessionStreaming(sess.sid)) {
      const badge = document.createElement("span");
      badge.className = "stream-badge";
      badge.textContent = "streaming";
      titleRow.appendChild(badge);
    }
    const meta = document.createElement("div");
    meta.className = "list-meta";
    meta.textContent = sess.sid;
    item.appendChild(titleRow);
    item.appendChild(meta);
    app.dom.sessionList.appendChild(item);
  }
  if (app.dom.sessionDropdown && !app.dom.sessionDropdown.classList.contains("hidden")) {
    renderSessionDropdown();
  }
  if (app.dom.sessionDropdownToolbar && !app.dom.sessionDropdownToolbar.classList.contains("hidden")) {
    renderSessionDropdownToolbar();
  }
  renderToolbar();
}

function renderToolbar() {
  const pid = app.state.ui.activePid;
  const sid = app.state.ui.activeSid;
  const proj = pid ? app.state.projects[pid] : null;
  // NOTE: This label is dynamic (project name). Do not rely on `data-i18n-key`
  // since i18n re-application can otherwise overwrite it back to "No project".
  const projName = proj?.name || pid || i18nTranslate("chat_js.projects.no_project", "No project");
  const sess = sid ? app.state.sessions[sid] : null;
  // NOTE: This label is dynamic (session title). Same i18n caveat as above.
  const sessName = sess?.title || sid || i18nTranslate("chat_js.sessions.no_session", "No session");
  if (app.dom.projectButton) app.dom.projectButton.textContent = projName;
  if (app.dom.sessionButton) app.dom.sessionButton.textContent = sessName;
  if (app.dom.sessionJoin) {
    const access = getActiveSessionAccess();
    const isMember =
      Boolean(access?.is_project_member) || Boolean(access?.is_session_member) || Boolean(access?.is_owner);
    const showJoin = Boolean(remoteEnabled() && access?.effective_public && !isMember);
    app.dom.sessionJoin.classList.toggle("hidden", !showJoin);
  }
  app.dom.toolbarActions.innerHTML = "";
  for (const item of app.plugins.slots.toolbar) {
    const action = item.action || item;
    const btn = document.createElement("button");
    btn.className = "ghost";
    btn.textContent = action.label || action.id || "Action";
    btn.addEventListener("click", () => action.onClick?.(getPluginContext()));
    app.dom.toolbarActions.appendChild(btn);
  }
  updateComposerAccess();
}

function updateComposerAccess() {
  if (!app.dom.composerInput || !app.dom.sendBtn) return;
  const access = getActiveSessionAccess();
  const sid = app.state.ui.activeSid;
  const session = sid ? app.state.sessions?.[sid] : null;
  const remoteSession = Boolean(canUseRemoteServer() && session?.source === "remote");
  const allowed = !remoteSession || !access || Boolean(access.can_access);
  app.dom.composerInput.disabled = !allowed;
  app.dom.sendBtn.disabled = !allowed;
  if (!allowed) {
    app.dom.composerInput.placeholder = i18nTranslate("chat_js.composer.request_join_placeholder", "Request join to send messages.");
  } else if (app.dom.composerInput.placeholder === i18nTranslate("chat_js.composer.request_join_placeholder", "Request join to send messages.")) {
    app.dom.composerInput.placeholder = i18nTranslate("chat_js.composer.placeholder", "Type a message...");
  }
}

function renderTranscript() {
  const sid = app.state.ui.activeSid;
  const pid = app.state.ui.activePid;
  const session = sid ? app.state.sessions[sid] : null;
  const transcript = app.dom.transcript;
  const prevSid = String(transcript?.dataset?.sid || "");
  if (transcript) transcript.dataset.sid = sid || "";
  app.dom.messageNodes = app.dom.messageNodes || {};
  if (!session) {
    markTranscriptRenderSource("no_session", { messageCount: 0 });
    return;
  }

  const messages = session.messages || [];
  const nextFps = computeTranscriptFingerprints(messages);
  const forceLiveRender = Boolean(app?.plugins?.forceLiveTranscriptRenderOnce);
  if (forceLiveRender) app.plugins.forceLiveTranscriptRenderOnce = false;
  const prevMeta = app.state.ui.__transcriptRenderMeta || {};
  const prevFps = forceLiveRender ? [] : (Array.isArray(prevMeta.fingerprints) ? prevMeta.fingerprints : []);

  // Hydrate from rendered HTML whenever the current message set matches a snapshot.
  // Remote session hydration can run after an initial local render, so this must not
  // be limited to an empty transcript.
  if (!forceLiveRender && tryRestoreTranscriptSnapshot(pid, sid, session, messages, nextFps)) {
    return;
  }

  // Fast path while active: append only new messages if prior messages are unchanged.
  if (!forceLiveRender && sid && prevSid === sid && prevFps.length > 0 && nextFps.length >= prevFps.length) {
    const prefixSame = prevFps.every((v, i) => v === nextFps[i]);
    if (prefixSame && transcript && transcript.childElementCount === prevFps.length) {
      for (let i = prevFps.length; i < messages.length; i += 1) {
        const msg = messages[i];
        const node = renderMessageNode(applyMessagePrerender(msg, "render"));
        if (node) {
          app.dom.messageNodes[msg.msg_id] = node;
          transcript.appendChild(node);
        }
      }
      app.state.ui.__transcriptRenderMeta = { sid, pid, fingerprints: nextFps };
      markTranscriptRenderSource("append", {
        messageSource: session.source || "local_state",
        cacheKey: transcriptCacheKey(pid, sid),
        messageCount: messages.length,
      });
      if (sid && pid) scheduleTranscriptSnapshot(pid, sid, nextFps);
      scrollToBottom();
      return;
    }
  }

  // Full rerender fallback.
  transcript.innerHTML = "";
  app.dom.messageNodes = {};

  for (const msg of messages) {
    const node = renderMessageNode(applyMessagePrerender(msg, "render"));
    if (node) {
      app.dom.messageNodes[msg.msg_id] = node;
      transcript.appendChild(node);
    }
  }
  app.state.ui.__transcriptRenderMeta = { sid, pid, fingerprints: nextFps };
  markTranscriptRenderSource("full", {
    messageSource: session.source || "local_state",
    cacheKey: transcriptCacheKey(pid, sid),
    messageCount: messages.length,
  });
  if (sid && pid) scheduleTranscriptSnapshot(pid, sid, nextFps);
  scrollToBottom();
}

  function applyMessagePrerender(msg, phase) {
    if (!msg) return msg;
    let nextMsg = msg;
    const ctx = getPluginContext();
    for (const entry of app.plugins.slots.messagePreRenderers) {
      const renderer = entry.fn || entry;
      const res = renderer(nextMsg, ctx, { phase });
      if (!res) continue;
      if (res === false) return null;
      if (res && typeof res === "object" && ("msg" in res || "skip" in res)) {
        if (res.skip) return null;
        if (res.msg) nextMsg = res.msg;
        continue;
      }
      nextMsg = res;
    }
    return nextMsg;
  }

  function renderMessageNode(msg) {
    if (!msg) return null;
    for (const entry of app.plugins.slots.messageRenderers) {
      const renderer = entry.fn || entry;
      const node = renderer(msg, getPluginContext());
      if (node) {
        attachMessageFooter(node, msg);
        return node;
      }
    }

    const wrap = document.createElement("div");
  const role = msg.role || "user";
  wrap.className = `message ${role}`;
  if (role === "user" && isOtherUserMessage(msg)) {
    wrap.classList.add("other-user");
  }
  wrap.dataset.msgId = msg.msg_id || "";
  if (msg.author) {
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = msg.author;
    wrap.appendChild(meta);
  }

  const bubble = document.createElement("div");
  bubble.className = "bubble";
    renderMessageBubbleContent(bubble, msg);
    wrap.appendChild(bubble);
    attachMessageFooter(wrap, msg);

    return wrap;
  }

  function renderMessageBubbleContent(bubble, msg) {
    if (!bubble) return;
    const prevState = collectCodeCardState(bubble);
    const blocks = buildMessageBlocks(msg);
    const ctx = getPluginContext();
    bubble.innerHTML = "";
    const contentText = String(msg?.content || "");
    const activeSid = app.state.ui.activeSid;
    const placeholderId = activeSid ? app.streams.placeholderBySid[activeSid] : "";
    const isTyping =
      !contentText.trim() &&
      (msg?.streaming || msg?.meta?.is_draft || msg?.meta?.keep_placeholder || (placeholderId && msg?.msg_id === placeholderId));
    if (isTyping) {
      bubble.classList.remove("stack");
      bubble.classList.add("typing");
      const dots = document.createElement("div");
      dots.className = "typing-dots";
      for (let i = 0; i < 3; i += 1) {
        const dot = document.createElement("span");
        dot.className = "typing-dot";
        dots.appendChild(dot);
      }
      bubble.appendChild(dots);
      return;
    }
    bubble.classList.remove("typing");
    if (!blocks.length) {
      bubble.classList.remove("stack");
      return;
    }
  const hasNonText = blocks.some((block) => (block?.type || "text").toLowerCase() !== "text");
  const needsStack = hasNonText || blocks.length > 1;
  bubble.classList.toggle("stack", needsStack);
  if (!needsStack) {
    bubble.innerHTML = renderMarkdown(blocks[0].text || "");
    return;
  }
    blocks.forEach((block, index) => {
    if (!block || typeof block !== "object") return;
    const type = String(block.type || "text").toLowerCase();
    if (type === "text") {
      const text = String(block.text || "");
      if (!text.trim()) return;
      const div = document.createElement("div");
      div.className = "block block-text";
      div.innerHTML = renderMarkdown(text);
      bubble.appendChild(div);
      return;
    }
    if (type === "code") {
      bubble.appendChild(renderCodeCard(block, index, prevState));
      return;
    }
    if (type === "table") {
      bubble.appendChild(renderGridCard(block));
      return;
    }
    if (type === "image") {
      const wrap = document.createElement("div");
      wrap.className = "block block-image";
      const img = document.createElement("img");
      img.alt = String(block.name || "image");
      img.addEventListener("load", () => {
        if (shouldAutoScroll()) scrollToBottom();
      });
      img.addEventListener("error", () => {
        wrap.textContent = i18nTranslate("chat_js.media.image_not_available", "Image not available");
      });
      img.src = String(block.src || "");
      wrap.appendChild(img);
      if (block.name) {
        const caption = document.createElement("div");
        caption.className = "block-caption";
        caption.textContent = String(block.name || "");
        wrap.appendChild(caption);
      }
      bubble.appendChild(wrap);
      return;
    }
      if (type === "video") {
        const wrap = document.createElement("div");
        wrap.className = "block block-video";
      let src = String(block.src || "");
      const normalized = src.replace(/\\/g, "/");
      if (!/^https?:\/\//i.test(normalized)) {
        if (normalized.includes("/uploads/")) {
          const name = normalized.split("/uploads/").pop();
          if (name) src = `/uploads/${name}`;
        } else if (/\.(mp4|webm|mov|mkv)$/i.test(normalized)) {
          const name = normalized.split("/").pop();
          if (name) src = `/uploads/${name}`;
        } else {
          src = normalized;
        }
      }
      if (!/^https?:\/\//i.test(src) && !/^data:/i.test(src)) {
        const base = String(app?.state?.remote?.serverUrl || "").replace(/\/+$/, "");
        const origin = String(window?.location?.origin || "").replace(/\/+$/, "");
        const host = base && !base.startsWith("file:") ? base : origin;
        if (host) {
          src = src.startsWith("/") ? `${host}${src}` : `${host}/${src}`;
        }
      }
      if (!src) {
        wrap.textContent = i18nTranslate("chat_js.media.video_not_available", "Video not available");
        bubble.appendChild(wrap);
        return;
      }
      const vid = document.createElement("video");
      vid.src = src;
      vid.controls = false;
      vid.preload = "metadata";
      vid.playsInline = true;
      try {
        vid.load();
      } catch (_err) {}
      const errorMsg = document.createElement("div");
      errorMsg.className = "block-caption";
      errorMsg.textContent = i18nTranslate("chat_js.media.video_not_available", "Video not available");
      vid.addEventListener("error", () => {
        if (!errorMsg.parentNode) wrap.appendChild(errorMsg);
      });
      wrap.appendChild(vid);
      const controls = document.createElement("div");
      controls.className = "block-video-controls";
      const btnPlay = document.createElement("button");
      btnPlay.type = "button";
      btnPlay.textContent = i18nTranslate("chat_js.media.play", "Play");
      const btnPause = document.createElement("button");
      btnPause.type = "button";
      btnPause.textContent = i18nTranslate("chat_js.media.pause", "Pause");
      const seek = document.createElement("input");
      seek.type = "range";
      seek.min = "0";
      seek.max = "0";
      seek.value = "0";
      seek.step = "0.1";
      let isSeeking = false;
      btnPlay.addEventListener("click", () => {
        vid.play().catch(() => {});
      });
      btnPause.addEventListener("click", () => {
        vid.pause();
      });
      seek.addEventListener("input", () => {
        isSeeking = true;
        if (Number.isFinite(vid.duration)) {
          vid.currentTime = Number(seek.value || 0);
        }
      });
      seek.addEventListener("change", () => {
        isSeeking = false;
      });
      vid.addEventListener("loadedmetadata", () => {
        const dur = Number.isFinite(vid.duration) ? vid.duration : 0;
        seek.max = String(Math.max(0, dur));
        seek.value = "0";
      });
      vid.addEventListener("timeupdate", () => {
        if (isSeeking) return;
        seek.value = String(vid.currentTime || 0);
      });
      controls.appendChild(btnPlay);
      controls.appendChild(btnPause);
      controls.appendChild(seek);
      wrap.appendChild(controls);
      if (block.name) {
        const caption = document.createElement("div");
        caption.className = "block-caption";
        caption.textContent = String(block.name || "");
        wrap.appendChild(caption);
      }
        bubble.appendChild(wrap);
        return;
      }
      if (app.plugins.slots.blockRenderers.length) {
        for (const entry of app.plugins.slots.blockRenderers) {
          const renderer = entry.fn || entry;
          try {
            const node = renderer(block, msg, ctx);
            if (node) {
              bubble.appendChild(node);
              return;
            }
          } catch (err) {
            appendLog(`[render] block render failed: ${err.message || err}`, "warn");
          }
        }
      }
      const fallback = document.createElement("div");
      fallback.className = "block block-text";
      fallback.innerHTML = renderMarkdown(String(block.text || ""));
      bubble.appendChild(fallback);
    });
  }

  function renderMessageWithPlugins(msg, options = {}) {
    const mode = String(options.mode || "bubble").toLowerCase();
    const nextMsg = applyMessagePrerender(msg, "render");
    if (!nextMsg) return null;
    const ctx = getPluginContext();
    for (const entry of app.plugins.slots.messageRenderers) {
      const renderer = entry.fn || entry;
      const node = renderer(nextMsg, ctx);
      if (node) {
        if (mode === "bubble") {
          const bubble = node.querySelector ? node.querySelector(".bubble") : null;
          return bubble || node;
        }
        return node;
      }
    }

    const bubble = document.createElement("div");
    bubble.className = options.bubbleClass || "bubble";
    renderMessageBubbleContent(bubble, nextMsg);
    if (mode === "bubble") return bubble;

    const wrap = document.createElement("div");
    const role = nextMsg.role || "user";
    wrap.className = `message ${role}`;
    if (role === "user" && isOtherUserMessage(nextMsg)) {
      wrap.classList.add("other-user");
    }
    wrap.dataset.msgId = nextMsg.msg_id || "";
    if (nextMsg.author) {
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent = nextMsg.author;
      wrap.appendChild(meta);
    }
    wrap.appendChild(bubble);
    return wrap;
  }

  function getMessageFooterRole(msg) {
    const role = String(msg?.role || "user").trim().toLowerCase();
    if (role === "user") {
      return isOtherUserMessage(msg) ? "other" : "me";
    }
    return role || "assistant";
  }

  function messageFooterRoleMatches(role, roles) {
    if (!Array.isArray(roles) || roles.length === 0) return true;
    const norm = roles.map((r) => String(r || "").trim().toLowerCase());
    if (role === "me") {
      return norm.includes("me") || norm.includes("user");
    }
    if (role === "other") {
      return norm.includes("other") || norm.includes("user_other") || norm.includes("user");
    }
    return norm.includes(role);
  }

  function collectMessageFooterItems(msg, ctx) {
    const role = getMessageFooterRole(msg);
    const items = [];
    for (const entry of app.plugins.slots.messageFooterItems) {
      const render = entry.render || entry.fn || entry;
      if (typeof render !== "function") continue;
      if (!messageFooterRoleMatches(role, entry.roles)) continue;
      try {
        const node = render(msg, ctx);
        if (!node) continue;
        items.push({
          align: String(entry.align || "left").toLowerCase() === "right" ? "right" : "left",
          node,
        });
      } catch (err) {
        appendLog(`[render] message footer failed: ${err.message || err}`, "warn");
      }
    }
    return items;
  }

  function attachMessageFooter(container, msg) {
    if (!container) return;
    const bubble = container.querySelector(".bubble");
    if (!bubble) return;
    const ctx = getPluginContext();
    const items = collectMessageFooterItems(msg, ctx);
    if (!items.length) return;

    const row = document.createElement("div");
    row.className = "message-footer";
    const left = document.createElement("div");
    left.className = "message-footer-left";
    const right = document.createElement("div");
    right.className = "message-footer-right";
    items.forEach((item) => {
      if (item.align === "right") right.appendChild(item.node);
      else left.appendChild(item.node);
    });
    row.appendChild(left);
    row.appendChild(right);
    bubble.appendChild(row);
  }

  function refreshMessageFooter(container, msg) {
    if (!container) return;
    const bubble = container.querySelector(".bubble");
    if (!bubble) return;
    const existing = bubble.querySelector(".message-footer");
    if (existing) existing.remove();
    attachMessageFooter(container, msg);
  }

  function rehydrateRestoredTranscriptInteractions(session, messages) {
    if (!session || !Array.isArray(messages) || !app?.dom?.transcript) return;
    const byId = new Map();
    messages.forEach((msg) => {
      const id = String(msg?.msg_id || "").trim();
      if (id) byId.set(id, msg);
    });
    app.dom.transcript.querySelectorAll(".message[data-msg-id]").forEach((node) => {
      const msg = byId.get(String(node?.dataset?.msgId || "").trim());
      if (!msg) return;
      refreshMessageFooter(node, msg);
    });
  }

function buildMessageBlocks(msg) {
  if (Array.isArray(msg?.content)) {
    const parts = msg.content;
    let blocks = [];
    for (const part of parts) {
      if (!part || typeof part !== "object") continue;
      const ptype = String(part.type || "").toLowerCase();
      if (ptype === "image_url") {
        const url = part.image_url?.url || part.url || "";
        if (url) {
          blocks.push({ type: "image", src: url, name: part.name || "" });
        }
        continue;
      }
      if (ptype === "text") {
        const text = part.text || part.content || "";
        if (text) blocks.push({ type: "text", text: String(text) });
        continue;
      }
    }
    if (blocks.length) {
      const ctx = getPluginContext();
      for (const entry of app.plugins.slots.blockTransformers) {
        const transformer = entry.transformer || entry.fn || entry;
        const fn = typeof transformer === "function" ? transformer : transformer?.transform;
        if (!fn) continue;
        try {
          const next = fn(blocks, msg, ctx);
          if (Array.isArray(next)) {
            blocks = next;
          }
        } catch (err) {
          appendLog(`[render] block transform failed: ${err.message || err}`, "warn");
        }
      }
      return blocks;
    }
  }

  const base = [{ type: "text", text: msg?.content || "" }];
  if (!app.plugins.slots.blockTransformers.length) return base;
  let blocks = base;
  const ctx = getPluginContext();
  for (const entry of app.plugins.slots.blockTransformers) {
    const transformer = entry.transformer || entry.fn || entry;
    const fn = typeof transformer === "function" ? transformer : transformer?.transform;
    if (!fn) continue;
    try {
      const next = fn(blocks, msg, ctx);
      if (Array.isArray(next)) {
        blocks = next;
      }
    } catch (err) {
      appendLog(`[render] block transform failed: ${err.message || err}`, "warn");
    }
  }
  if (!Array.isArray(blocks) || blocks.length === 0) return base;
  return blocks;
}

// Expose for plugins that need the full block pipeline (charts, etc.).
if (typeof window !== "undefined") {
  window.buildMessageBlocks = buildMessageBlocks;
}

function renderBlocksToContainer(container, msg, blocks) {
  if (!container) return;
  const prevState = collectCodeCardState(container);
  const ctx = getPluginContext();
  container.innerHTML = "";
  if (!Array.isArray(blocks) || blocks.length === 0) {
    container.classList.remove("stack");
    return;
  }
  const hasNonText = blocks.some((block) => (block?.type || "text").toLowerCase() !== "text");
  const needsStack = hasNonText || blocks.length > 1;
  container.classList.toggle("stack", needsStack);
  if (!needsStack) {
    container.innerHTML = renderMarkdown(blocks[0].text || "");
    return;
  }
  blocks.forEach((block, index) => {
    if (!block || typeof block !== "object") return;
    const type = String(block.type || "text").toLowerCase();
    if (type === "text") {
      const text = String(block.text || "");
      if (!text.trim()) return;
      const div = document.createElement("div");
      div.className = "block block-text";
      div.innerHTML = renderMarkdown(text);
      container.appendChild(div);
      return;
    }
    if (type === "code") {
      container.appendChild(renderCodeCard(block, index, prevState));
      return;
    }
    if (type === "table") {
      container.appendChild(renderGridCard(block));
      return;
    }
    if (type === "image") {
      const wrap = document.createElement("div");
      wrap.className = "block block-image";
      const img = document.createElement("img");
      img.alt = String(block.name || "image");
      img.addEventListener("load", () => {
        if (shouldAutoScroll()) scrollToBottom();
      });
      img.addEventListener("error", () => {
        wrap.textContent = i18nTranslate("chat_js.media.image_not_available", "Image not available");
      });
      img.src = String(block.src || "");
      wrap.appendChild(img);
      if (block.name) {
        const caption = document.createElement("div");
        caption.className = "block-caption";
        caption.textContent = String(block.name || "");
        wrap.appendChild(caption);
      }
      container.appendChild(wrap);
      return;
    }
    if (type === "video") {
      const wrap = document.createElement("div");
      wrap.className = "block block-video";
      let src = String(block.src || "");
      const normalized = src.replace(/\\/g, "/");
      if (!/^https?:\/\//i.test(normalized)) {
        if (normalized.includes("/uploads/")) {
          const name = normalized.split("/uploads/").pop();
          if (name) src = `/uploads/${name}`;
        } else if (/\.(mp4|webm|mov|mkv)$/i.test(normalized)) {
          const name = normalized.split("/").pop();
          if (name) src = `/uploads/${name}`;
        } else {
          src = normalized;
        }
      }
      if (!src) {
        wrap.textContent = i18nTranslate("chat_js.media.video_not_available", "Video not available");
        container.appendChild(wrap);
        return;
      }
      const vid = document.createElement("video");
      vid.src = src;
      vid.controls = false;
      vid.preload = "metadata";
      vid.playsInline = true;
      try {
        vid.load();
      } catch (_err) {}
      const errorMsg = document.createElement("div");
      errorMsg.className = "block-caption";
      errorMsg.textContent = i18nTranslate("chat_js.media.video_not_available", "Video not available");
      vid.addEventListener("error", () => {
        if (!errorMsg.parentNode) wrap.appendChild(errorMsg);
      });
      wrap.appendChild(vid);
      const controls = document.createElement("div");
      controls.className = "block-video-controls";
      const btnPlay = document.createElement("button");
      btnPlay.type = "button";
      btnPlay.textContent = i18nTranslate("chat_js.media.play", "Play");
      const btnPause = document.createElement("button");
      btnPause.type = "button";
      btnPause.textContent = i18nTranslate("chat_js.media.pause", "Pause");
      const seek = document.createElement("input");
      seek.type = "range";
      seek.min = "0";
      seek.max = "0";
      seek.value = "0";
      seek.step = "0.1";
      let isSeeking = false;
      btnPlay.addEventListener("click", () => {
        vid.play().catch(() => {});
      });
      btnPause.addEventListener("click", () => {
        vid.pause();
      });
      seek.addEventListener("input", () => {
        isSeeking = true;
        if (Number.isFinite(vid.duration)) {
          vid.currentTime = Number(seek.value || 0);
        }
      });
      seek.addEventListener("change", () => {
        isSeeking = false;
      });
      vid.addEventListener("loadedmetadata", () => {
        const dur = Number.isFinite(vid.duration) ? vid.duration : 0;
        seek.max = String(Math.max(0, dur));
        seek.value = "0";
      });
      vid.addEventListener("timeupdate", () => {
        if (isSeeking) return;
        seek.value = String(vid.currentTime || 0);
      });
      controls.appendChild(btnPlay);
      controls.appendChild(btnPause);
      controls.appendChild(seek);
      wrap.appendChild(controls);
      if (block.name) {
        const caption = document.createElement("div");
        caption.className = "block-caption";
        caption.textContent = String(block.name || "");
        wrap.appendChild(caption);
      }
      container.appendChild(wrap);
      return;
    }
    if (app.plugins.slots.blockRenderers.length) {
      for (const entry of app.plugins.slots.blockRenderers) {
        const renderer = entry.fn || entry;
        try {
          const node = renderer(block, msg, ctx);
          if (node) {
            container.appendChild(node);
            return;
          }
        } catch (err) {
          appendLog(`[render] block render failed: ${err.message || err}`, "warn");
        }
      }
    }
    const fallback = document.createElement("div");
    fallback.className = "block block-text";
    fallback.innerHTML = renderMarkdown(String(block.text || ""));
    container.appendChild(fallback);
  });
}

function renderTextWithPlugins(container, text, opts = {}) {
  if (!container) return;
  const base = typeof opts.msg === "object" && opts.msg ? opts.msg : {};
  const msg = { role: opts.role || base.role || "assistant", ...base, content: text };
  const blocks = buildMessageBlocks(msg);
  renderBlocksToContainer(container, msg, blocks);
}

if (typeof window !== "undefined") {
  window.renderTextWithPlugins = renderTextWithPlugins;
}

function collectCodeCardState(container) {
  const state = {};
  if (!container) return state;
  const cards = container.querySelectorAll(".code-card");
  cards.forEach((card) => {
    const key = card.dataset.blockKey || "";
    if (!key) return;
    state[key] = {
      collapsed: card.dataset.collapsed === "true",
      wrap: card.dataset.wrap === "true",
    };
  });
  return state;
}

const CODE_HL_GENERIC_RE =
  /(\/\/.*?$|\/\*[\s\S]*?\*\/)|("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)|(\b\d+(?:\.\d+)?(?:e[+-]?\d+)?\b)|(\b(?:const|let|var|function|return|if|else|for|while|switch|case|break|continue|try|catch|finally|throw|new|class|extends|import|from|export|default|async|await|yield|this|super|typeof|instanceof|in|of)\b)|(\b(?:true|false|null|undefined)\b)/gm;
const CODE_HL_PY_RE =
  /(#.*?$)|(\"\"\"[\s\S]*?\"\"\"|'''[\s\S]*?'''|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(\b\d+(?:\.\d+)?(?:e[+-]?\d+)?\b)|(\b(?:def|class|return|if|elif|else|for|while|try|except|finally|with|as|import|from|lambda|yield|True|False|None|pass|break|continue|and|or|not|in|is)\b)/gm;
const CODE_HL_JSON_RE = /("(?:\\.|[^"\\])*")|(\b\d+(?:\.\d+)?(?:e[+-]?\d+)?\b)|(\b(?:true|false|null)\b)/g;
const CODE_HL_BASH_RE =
  /(#.*?$)|("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(\$\{[^}]+\}|\$[A-Za-z_][A-Za-z0-9_]*)|(\b(?:if|then|else|elif|fi|for|in|do|done|case|esac|function|select|while|until|time)\b)/gm;
const CODE_HL_HTML_RE = /(<!--[\s\S]*?-->)|(<\/?[^>]+?>)/g;

function highlightCodeHtml(text, lang) {
  const raw = String(text || "");
  if (!raw) return "";
  const mode = detectHighlightMode(lang);
  if (mode === "python") {
    return highlightWithRegex(raw, CODE_HL_PY_RE, {
      1: "tok tok-com",
      2: "tok tok-str",
      3: "tok tok-num",
      4: "tok tok-kw",
    });
  }

    if (mode === "json") {
      return highlightWithRegex(raw, CODE_HL_JSON_RE, {
        1: "tok tok-str",
        2: "tok tok-num",
        3: "tok tok-lit",
    });
  }
  if (mode === "bash") {
    return highlightWithRegex(raw, CODE_HL_BASH_RE, {
      1: "tok tok-com",
      2: "tok tok-str",
      3: "tok tok-var",
      4: "tok tok-kw",
    });
  }
  if (mode === "html") {
    return highlightWithRegex(raw, CODE_HL_HTML_RE, {
      1: "tok tok-com",
      2: "tok tok-tag",
    });
  }
  return highlightWithRegex(raw, CODE_HL_GENERIC_RE, {
    1: "tok tok-com",
    2: "tok tok-str",
    3: "tok tok-num",
    4: "tok tok-kw",
    5: "tok tok-lit",
  });
}

function detectHighlightMode(lang) {
  const value = String(lang || "").trim().toLowerCase();
  if (!value) return "generic";
  if (["py", "python"].includes(value)) return "python";
  if (["json", "jsonc"].includes(value)) return "json";
  if (["bash", "sh", "shell", "zsh", "fish", "powershell", "ps", "ps1"].includes(value)) return "bash";
  if (["html", "htm", "xml", "svg", "xhtml"].includes(value)) return "html";
  return "generic";
}

function highlightWithRegex(text, regex, groupMap) {
  let out = "";
  let lastIndex = 0;
  regex.lastIndex = 0;
  let match;
  while ((match = regex.exec(text)) !== null) {
    if (match.index === regex.lastIndex) regex.lastIndex += 1;
    const start = match.index;
    out += escapeHtml(text.slice(lastIndex, start));
    const token = match[0];
    let cls = "";
    for (let i = 1; i < match.length; i += 1) {
      if (match[i] !== undefined) {
        cls = groupMap?.[i] || "";
        break;
      }
    }
    if (cls) {
      out += `<span class="${cls}">${escapeHtml(token)}</span>`;
    } else {
      out += escapeHtml(token);
    }
    lastIndex = start + token.length;
  }
  out += escapeHtml(text.slice(lastIndex));
  return out;
}

function renderCodeCard(block, index, prevState) {
  const card = document.createElement("div");
  card.className = "code-card";
  const key = `b${index}`;
  card.dataset.blockKey = key;
  const langRaw = String(block.lang || "").trim();
  const lang = langRaw ? langRaw.split(/\s+/)[0] : "";

  const header = document.createElement("div");
  header.className = "code-card-header";
  const title = document.createElement("div");
  title.className = "code-card-title";
  title.textContent = lang ? lang.toUpperCase() : "CODE";
  header.appendChild(title);

  const toolbar = document.createElement("div");
  toolbar.className = "code-card-toolbar";
  header.appendChild(toolbar);
  card.appendChild(header);

  const body = document.createElement("pre");
  body.className = "code-card-body";
  const code = document.createElement("code");
  if (lang) code.dataset.lang = lang;
  body.appendChild(code);
  card.appendChild(body);

  const fullText = typeof block.full_text === "string" ? block.full_text : String(block.text || "");
  const shownText = String(block.text || "");
  const truncated = Boolean(block.is_truncated && block.full_text);
  const state = prevState?.[key] || {};
  let collapsed = typeof state.collapsed === "boolean" ? state.collapsed : Boolean(block.collapsed || truncated);
  let wrap = typeof state.wrap === "boolean" ? state.wrap : Boolean(block.wrap);

  function applyView() {
    card.dataset.collapsed = collapsed ? "true" : "false";
    card.dataset.wrap = wrap ? "true" : "false";
    body.classList.toggle("wrap", wrap);
    const langKey = lang || "";
    if (collapsed && truncated) {
      code.innerHTML = highlightCodeHtml(shownText, langKey);
    } else {
      code.innerHTML = highlightCodeHtml(fullText, langKey);
    }
    if (toggleBtn) toggleBtn.textContent = collapsed ? i18nTranslate("chat_js.code.more", "More") : i18nTranslate("chat_js.code.less", "Less");
    wrapBtn.textContent = wrap ? i18nTranslate("chat_js.code.no_wrap", "No Wrap") : i18nTranslate("chat_js.code.wrap", "Wrap");
  }

  const copyBtn = document.createElement("button");
  copyBtn.className = "code-card-btn";
  copyBtn.textContent = i18nTranslate("chat_js.code.copy", "Copy");
  copyBtn.addEventListener("click", () => {
    const original = copyBtn.textContent;
    copyToClipboard(fullText || shownText)
      .then(() => {
        copyBtn.textContent = i18nTranslate("chat_js.code.copied", "Copied");
        setTimeout(() => {
          copyBtn.textContent = original;
        }, 1200);
      })
      .catch(() => {
        copyBtn.textContent = i18nTranslate("chat_js.common.failed", "Failed");
        setTimeout(() => {
          copyBtn.textContent = original;
        }, 1200);
      });
  });
  toolbar.appendChild(copyBtn);

  const wrapBtn = document.createElement("button");
  wrapBtn.className = "code-card-btn";
  wrapBtn.textContent = i18nTranslate("chat_js.code.wrap", "Wrap");
  wrapBtn.addEventListener("click", () => {
    wrap = !wrap;
    applyView();
  });
  toolbar.appendChild(wrapBtn);

  let toggleBtn = null;
  if (truncated) {
    toggleBtn = document.createElement("button");
    toggleBtn.className = "code-card-btn";
    toggleBtn.textContent = collapsed ? i18nTranslate("chat_js.code.more", "More") : i18nTranslate("chat_js.code.less", "Less");
    toggleBtn.addEventListener("click", () => {
      collapsed = !collapsed;
      applyView();
    });
    toolbar.appendChild(toggleBtn);
  }

  applyView();
  return card;
}

function renderGridCard(block) {
  const card = document.createElement("div");
  card.className = "grid-card";
  const lines = String(block.text || "")
    .split(/\r?\n/)
    .filter((line) => line.trim() !== "");
  if (lines.length < 2 || !isTableSeparator(lines[1])) {
    const pre = document.createElement("pre");
    pre.className = "grid-card-fallback";
    pre.textContent = String(block.text || "");
    card.appendChild(pre);
    return card;
  }
  const headerCells = splitTableRow(lines[0]);
  const bodyLines = lines.slice(2);
  const bodyRows = bodyLines.map(splitTableRow);
  const cols = Math.max(headerCells.length, ...bodyRows.map((row) => row.length), 1);

  function padRow(row) {
    const out = row.slice();
    while (out.length < cols) out.push("");
    return out;
  }

  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  padRow(headerCells).forEach((cell) => {
    const th = document.createElement("th");
    th.textContent = cell;
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  bodyRows.forEach((row) => {
    const tr = document.createElement("tr");
    padRow(row).forEach((cell) => {
      const td = document.createElement("td");
      td.textContent = cell;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);

  card.appendChild(table);
  return card;
}

function splitTableRow(line) {
  let text = String(line || "").trim();
  if (text.startsWith("|")) text = text.slice(1);
  if (text.endsWith("|")) text = text.slice(0, -1);
  if (!text) return [""];
  return text.split("|").map((cell) => cell.trim());
}

function isTableSeparator(line) {
  return /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$/.test(String(line || ""));
}

function copyToClipboard(text) {
  const value = String(text || "");
  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(value);
  }
  return new Promise((resolve, reject) => {
    const textarea = document.createElement("textarea");
    textarea.value = value;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    try {
      document.execCommand("copy");
      resolve();
    } catch (err) {
      reject(err);
    } finally {
      document.body.removeChild(textarea);
    }
  });
}

function updateMessageElement(msg) {
  if (!msg.msg_id) {
    renderTranscript();
    return;
  }
  const node = app.dom.messageNodes[msg.msg_id];
  if (!node) {
    renderTranscript();
    return;
  }
  msg = applyMessagePrerender(msg, "stream");
  if (!msg) {
    renderTranscript();
    return;
  }
  const autoScroll = shouldAutoScroll();
  // If a plugin provides a custom message renderer, re-render the whole node.
  for (const entry of app.plugins.slots.messageRenderers) {
    const renderer = entry.fn || entry;
    const nextNode = renderer(msg, getPluginContext());
    if (nextNode) {
      if (nextNode !== node) {
        node.replaceWith(nextNode);
        app.dom.messageNodes[msg.msg_id] = nextNode;
      }
      refreshMessageFooter(app.dom.messageNodes[msg.msg_id] || node, msg);
      if (autoScroll) scrollToBottom();
      return;
    }
  }
  const bubble = node.querySelector(".bubble");
  if (bubble) {
    renderMessageBubbleContent(bubble, msg);
  }
  if (!msg.streaming) {
    refreshMessageFooter(node, msg);
  }
  if (autoScroll) scrollToBottom();
}

function renderRoster() {
  app.dom.rosterList.innerHTML = "";
  for (const row of app.state.roster || []) {
    const item = document.createElement("div");
    item.className = "list-item";
    const label = row.alias || row.username || "user";
    item.innerHTML = `<div class="list-title">${escapeHtml(label)}</div>`;
    app.dom.rosterList.appendChild(item);
  }
  if (app.dom.rosterStatus) {
    app.dom.rosterStatus.textContent = `Roster: ${(app.state.roster || []).length}`;
  }
  if (app.dom.toolbarRoster) {
    app.dom.toolbarRoster.textContent = `Roster: ${(app.state.roster || []).length}`;
  }
}

function setActiveToolSection(panelId) {
  const panels = app.dom.toolsModal.querySelectorAll(".tool-section");
  panels.forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.panel === panelId);
  });
  applyToolsWindowMode(panelId);
}

function getGuiPluginPanelConfig(pluginId) {
  const pid = String(pluginId || "").trim();
  if (!pid) return null;
  const entry = app.plugins.slots.panels.find((panelEntry) => {
    const tab = panelEntry.tab || panelEntry;
    const id = panelEntry.pluginId || tab?.pluginId || tab?.id;
    return String(id || "") === pid;
  });
  return entry?.tab || entry || null;
}

async function waitForGuiPluginPanelConfig(pluginId, options = {}) {
  const pid = String(pluginId || "").trim();
  if (!pid) return null;
  const timeoutMs = Math.max(0, Number(options.timeoutMs || 6000));
  const intervalMs = Math.max(50, Number(options.intervalMs || 100));
  const deadline = Date.now() + timeoutMs;

  try {
    await ensurePluginsLoaded({ force: Boolean(options.forceLoad) });
  } catch (err) {
    appendLog(`[plugins] load before opening ${pid} failed: ${err.message || err}`, "warn");
  }

  let cfg = getGuiPluginPanelConfig(pid);
  while (!cfg && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
    cfg = getGuiPluginPanelConfig(pid);
  }
  return cfg;
}

async function openPluginPanelWhenReady(pluginId, options = {}) {
  const pid = String(pluginId || "").trim();
  if (!pid) return false;
  const cfg = await waitForGuiPluginPanelConfig(pid, options);
  if (!cfg) {
    appendLog(`[plugins] ${pid} did not register a panel before open timeout`, "warn");
    return false;
  }
  openPluginPanel(pid, options);
  return true;
}

function getToolWindowType(panelId) {
  const panel = String(panelId || "").trim();
  if (panel !== "gui-plugins") return "";
  const cfg = getGuiPluginPanelConfig(app.state.ui.activeGuiPluginId);
  return String(cfg?.windowType || "").trim().toLowerCase();
}

function applyToolsWindowMode(panelId) {
  const card = app.dom.modalContent;
  if (!card) return;
  const mode = getToolWindowType(panelId);
  card.classList.toggle("window-full", mode === "full");
  if (mode) card.dataset.windowType = mode;
  else delete card.dataset.windowType;
}

function ensureLocalDefaults() {
  ensureGuestId();
  if (Object.keys(app.state.projects).length === 0) {
    const pid = "default";
    app.state.projects[pid] = { pid, name: "Default", source: "local" };
  }
  if (!canUseRemoteServer()) {
    const locals = Object.values(app.state.projects).filter((p) => p?.source !== "remote");
    if (locals.length) {
      const activeProj = app.state.projects[app.state.ui.activePid];
      if (!activeProj || activeProj.source === "remote") {
        app.state.ui.activePid = locals[0].pid;
      }
    }
  }
  if (!app.state.ui.activePid) {
    const pid = Object.keys(app.state.projects)[0];
    app.state.ui.activePid = pid || "";
  }
  const pid = app.state.ui.activePid;
  const hasSession = Object.values(app.state.sessions).some((s) => s.pid === pid && s?.source !== "remote");
  if (!hasSession && pid) {
    const sid = "main";
    app.state.sessions[sid] = { sid, pid, title: "Main", messages: [], source: "local" };
    app.state.ui.activeSid = sid;
  }
  scheduleSave();
}

async function selectProject(pid) {
  if (!pid || pid === app.state.ui.activePid) return;
  app.state.ui.activePid = pid;
  await loadProjectRouterPrefs(pid);
  if (app.state.ui.activeSid && app.state.sessions[app.state.ui.activeSid]?.pid !== pid) {
    app.state.ui.activeSid = "";
  }
  scheduleProjectRouterPrefsSave(pid);
  scheduleSave();
  renderProjectList();
  renderSessionList();
  if (canUseRemoteServer()) {
    await refreshSessions();
  }
}

async function selectSession(sid) {
  if (!sid) return;
  if (sid === app.state.ui.activeSid) {
    if (canUseRemoteServer() && hasKnownRemoteSession(app.state.ui.activePid, sid)) {
      await loadSessionMessages();
      renderTranscript();
      renderToolbar();
      renderTopRightIconRow();
      renderTranscriptBars();
      renderPluginPanels();
      renderRouterPluginsList();
      startSessionEvents();
      await refreshSessionAccess();
      emitSessionChange();
    }
    return;
  }
  const switchToken = randomId("session-switch");
  app.state.ui.__sessionSwitchToken = switchToken;
  app.state.ui.activeSid = sid;
  app.state.ui.lastSessionByProject = app.state.ui.lastSessionByProject || {};
  if (app.state.ui.activePid) app.state.ui.lastSessionByProject[app.state.ui.activePid] = sid;
  scheduleProjectRouterPrefsSave(app.state.ui.activePid);
  scheduleSave();
  renderSessionList();
  renderStatus();
  renderTranscript();
  renderToolbar();
  renderTopRightIconRow();
  renderTranscriptBars();
  renderPluginPanels();
  renderRouterPluginsList();
  emitSessionChange();
  await loadSessionMessages();
  if (app.state.ui.activeSid !== sid || app.state.ui.__sessionSwitchToken !== switchToken) return;
  renderTranscript();
  renderToolbar();
  renderTopRightIconRow();
  renderTranscriptBars();
  renderPluginPanels();
  renderRouterPluginsList();
  if (canUseRemoteServer()) {
    startSessionEvents();
    await refreshSessionAccess();
  }
  emitSessionChange();
}

async function setActiveScope(pid, sid) {
  if (pid && pid !== app.state.ui.activePid) {
    await selectProject(pid);
  } else if (pid) {
    await loadProjectRouterPrefs(pid);
    renderProjectList();
  }
  if (sid) {
    await selectSession(sid);
  }
}

function promptTextModal({ title, label, placeholder = "", value = "", submitLabel = "" } = {}) {
  return new Promise((resolve) => {
    let settled = false;
    const modal = createRouterModal(title || "Input");
    const overlay = modal.overlay;
    const body = modal.body;

    const wrap = document.createElement("div");
    wrap.style.display = "flex";
    wrap.style.flexDirection = "column";
    wrap.style.gap = "6px";

    const lab = document.createElement("div");
    lab.style.fontSize = "13px";
    lab.style.fontWeight = "600";
    lab.textContent = label || i18nTranslate("chat_js.common.value", "Value");

    const input = document.createElement("input");
    input.type = "text";
    input.placeholder = placeholder || "";
    input.value = value || "";
    input.style.width = "100%";
    input.style.borderRadius = "12px";
    input.style.border = "1px solid var(--border)";
    input.style.padding = "10px 12px";

    const err = document.createElement("div");
    err.className = "muted";
    err.style.color = "var(--danger, #b42318)";
    err.style.display = "none";

    wrap.appendChild(lab);
    wrap.appendChild(input);
    wrap.appendChild(err);
    body.appendChild(wrap);

    const primary = overlay.querySelector("button.primary");
    if (primary && submitLabel) primary.textContent = submitLabel;

    const finish = (val) => {
      if (settled) return;
      settled = true;
      resolve(val);
    };

    overlay.onSave = () => {
      const v = String(input.value || "").trim();
      if (!v) {
        err.textContent = `${label || i18nTranslate("chat_js.common.value", "Value")} is required.`;
        err.style.display = "block";
        input.focus();
        return false;
      }
      finish(v);
      return true;
    };
    overlay.onClose = () => finish(null);

    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        const save = overlay.querySelector("button.primary");
        save?.click();
      }
    });

    setTimeout(() => {
      input.focus();
      input.select();
    }, 0);
  });
}

async function createProject() {
  if (!hasPermission("projects.create", false)) {
    appendLog("[projects] create blocked by permissions", "warn");
    return;
  }
  const ctx = getPluginContext();
  const projectHandler = (app.plugins.slots.projectCreateHandlers || []).slice(-1)[0];
  if (projectHandler && typeof projectHandler.fn === "function") {
    try {
      await projectHandler.fn(ctx);
    } catch (err) {
      appendLog(`[projects] create failed: ${err.message || err}`, "warn");
    }
    return;
  }

  const name = await promptTextModal({
    title: "New Project",
    label: "Project name",
    placeholder: "My project",
    submitLabel: "Create project",
  });
  if (!name) return;
  if (remoteEnabled()) {
    const data = await apiJson("/v1/projects", {
      method: "POST",
      body: { name: name.trim(), pid: slugify(name) },
    });
    if (data?.pid) {
      app.state.projects[data.pid] = { pid: data.pid, name: data.name || name, source: "remote" };
      app.state.ui.activePid = data.pid;
    }
  } else {
    const pid = slugify(name) || randomId("proj");
    app.state.projects[pid] = { pid, name: name.trim(), source: "local" };
    app.state.ui.activePid = pid;
  }
  scheduleSave();
  renderProjectList();
  await refreshSessions();
}

async function createSession(options = {}) {
  if (!hasPermission("sessions.create", false)) {
    appendLog("[sessions] create blocked by permissions", "warn");
    return;
  }
  const pid = app.state.ui.activePid;
  if (!pid) {
    appendLog("Select a project first", "warn");
    return;
  }
  const ctx = getPluginContext();
  const sessionHandler = (app.plugins.slots.sessionCreateHandlers || []).slice(-1)[0];
  if (sessionHandler && typeof sessionHandler.fn === "function") {
    try {
      await sessionHandler.fn(ctx, { pid });
    } catch (err) {
      appendLog(`[sessions] create failed: ${err.message || err}`, "warn");
    }
    return;
  }

  const title = await promptTextModal({
    title: options?.firstSession ? "Create your first chat session" : "New Session",
    label: "Session title",
    placeholder: "Chat",
    value: "Chat",
    submitLabel: "Create session",
  });
  if (!title) return;
  if (remoteEnabled()) {
    const payload = { title: title.trim() };
    const data = await apiJson(`/v1/projects/${encodeURIComponent(pid)}/sessions`, {
      method: "POST",
      body: payload,
      headers: buildHeaders({ pid }),
    });
    if (data?.sid) {
      app.state.sessions[data.sid] = {
        sid: data.sid,
        pid,
        title: data.title || title.trim(),
        is_public: Boolean(data.is_public),
        messages: [],
        source: "remote",
      };
      app.state.ui.activeSid = data.sid;
    }
  } else {
    const sid = slugify(title) || randomId("sess");
    app.state.sessions[sid] = { sid, pid, title: title.trim(), messages: [], source: "local" };
    app.state.ui.activeSid = sid;
  }
  scheduleSave();
  renderSessionList();
  renderToolbar();
  emitSessionChange();
}

async function refreshProjects(options = {}) {
  const shouldRefreshSessions = options?.refreshSessions !== false;
  if (!canUseRemoteServer()) {
    renderProjectList();
    return;
  }
  const prevPid = app.state.ui.activePid;
  try {
    const data = await apiJson("/v1/projects");
    const list = data?.projects || [];
    const remoteIds = [];
    for (const proj of list) {
      const pid = (proj.pid || "").trim();
      if (!pid) continue;
      const prev = app.state.projects[pid] || {};
      const merged = { ...prev, ...proj };
      const hasPublic = Object.prototype.hasOwnProperty.call(proj, "is_public");
      app.state.projects[pid] = {
        ...merged,
        pid,
        name: proj.name || merged.name || pid,
        is_public: hasPublic ? Boolean(proj.is_public) : Boolean(merged.is_public),
        source: "remote",
      };
      remoteIds.push(pid);
    }
    const remoteSet = new Set(remoteIds);
    for (const [pid, proj] of Object.entries(app.state.projects)) {
      if (proj?.source === "remote" && !remoteSet.has(pid)) {
        delete app.state.projects[pid];
      }
    }
    for (const [sid, sess] of Object.entries(app.state.sessions)) {
      if (sess?.source === "remote" && sess?.pid && !remoteSet.has(sess.pid)) {
        delete app.state.sessions[sid];
      }
    }
    if (list.length) {
      const current = app.state.ui.activePid;
      if (!current || !remoteIds.includes(current)) {
        app.state.ui.activePid = list[0].pid;
      }
    }
    scheduleSave();
    renderProjectList();
    if (shouldRefreshSessions || app.state.ui.activePid !== prevPid) {
      await refreshSessions();
    }
  } catch (err) {
    appendLog(`[projects] ${err.message || err}`, "error");
  }
}

async function refreshSessions(options = {}) {
  const refreshMessages = options?.refreshMessages !== false;
  const pid = app.state.ui.activePid;
  if (!pid) return;
  if (!canUseRemoteServer()) {
    renderSessionList();
    return;
  }
  const prevSid = app.state.ui.activeSid;
  try {
    const data = await apiJson(`/v1/projects/${encodeURIComponent(pid)}/sessions`, {
      headers: buildHeaders({ pid }),
    });
    const sessions = data?.sessions || [];
    const remoteSids = [];
    for (const sess of sessions) {
      const sid = (sess.sid || "").trim();
      if (!sid) continue;
      const prev = app.state.sessions[sid] || {};
      const merged = { ...prev, ...sess };
      const hasPublic = Object.prototype.hasOwnProperty.call(sess, "is_public");
      app.state.sessions[sid] = {
        ...merged,
        sid,
        pid,
        title: sess.title || merged.title || sid,
        is_public: hasPublic ? Boolean(sess.is_public) : Boolean(merged.is_public),
        messages: prev.messages || [],
        source: "remote",
      };
      remoteSids.push(sid);
    }
    const remoteSet = new Set(remoteSids);
    for (const [sid, sess] of Object.entries(app.state.sessions)) {
      if (sess?.source === "remote" && sess?.pid === pid && !remoteSet.has(sid)) {
        delete app.state.sessions[sid];
      }
    }
    if (sessions.length) {
      const current = app.state.ui.activeSid;
      if (!current || !remoteSids.includes(current)) {
        const remembered = String(app.state.ui?.lastSessionByProject?.[pid] || "").trim();
        app.state.ui.activeSid = remembered && remoteSids.includes(remembered)
          ? remembered
          : sessions[0].sid;
      }
    } else {
      app.state.ui.activeSid = "";
    }
    scheduleSave();
    renderSessionList();
    renderToolbar();
    const nextSid = app.state.ui.activeSid;
    if (!refreshMessages && nextSid === prevSid) {
      return;
    }
    await loadSessionMessages();
    renderTranscript();
    if (!nextSid) {
      stopSessionEvents();
      app.state.roster = [];
      renderRoster();
      renderTranscriptBars();
      renderPluginPanels();
      renderRouterPluginsList();
      emitSessionChange();
      return;
    }
    if (nextSid !== prevSid) {
      renderTranscriptBars();
      renderPluginPanels();
      renderRouterPluginsList();
      if (remoteEnabled()) {
        startSessionEvents();
      }
      emitSessionChange();
    }
    await refreshSessionAccess();
  } catch (err) {
    appendLog(`[sessions] ${err.message || err}`, "error");
  }
}

function getActiveSessionAccess() {
  const sid = app.state.ui.activeSid;
  if (!sid) return null;
  return app.state.sessionAccess?.[sid] || null;
}

async function refreshSessionAccess() {
  const pid = app.state.ui.activePid;
  const sid = app.state.ui.activeSid;
  if (!pid || !sid || !canUseRemoteServer()) {
    app.state.sessionAccess = {};
    renderToolbar();
    return;
  }
  try {
    const data = await apiJson(`/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/access`, {
      headers: buildHeaders({ pid, sid }),
    });
    if (data?.ok) {
      app.state.sessionAccess = { ...(app.state.sessionAccess || {}), [sid]: data };
    } else {
      app.state.sessionAccess = { ...(app.state.sessionAccess || {}), [sid]: null };
    }
  } catch (err) {
    app.state.sessionAccess = { ...(app.state.sessionAccess || {}), [sid]: null };
    appendLog(`[access] ${err.message || err}`, "warn");
  }
  renderToolbar();
  updateComposerAccess();
}

async function requestJoinForSession() {
  const pid = app.state.ui.activePid;
  const sid = app.state.ui.activeSid;
  if (!pid || !sid || !remoteEnabled()) return;
  try {
    const data = await apiJson(
      `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/join_requests`,
      { method: "POST", headers: buildHeaders({ pid, sid }) }
    );
    const status = data?.status || "requested";
    if (status === "joined") {
      appendLog("Joined session", "info");
    } else if (status === "pending") {
      appendLog("Join request sent", "info");
    } else if (status === "not_needed") {
      appendLog("Already have access", "info");
    } else {
      appendLog("Join request sent", "info");
    }
  } catch (err) {
    appendLog(`[join] ${err.message || err}`, "error");
  }
  await refreshSessionAccess();
  await refreshRosterSnapshot();
}

async function loadSessionMessages() {
  const pid = app.state.ui.activePid;
  const sid = app.state.ui.activeSid;
  if (!pid || !sid) return;
  const session = app.state.sessions[sid] || { sid, pid, title: sid, messages: [] };
  if (!canUseRemoteServer()) {
    app.state.sessions[sid] = session;
    scheduleSave();
    return;
  }
  try {
    const data = await apiJson(
      `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/messages?limit=200&tail=1`,
      {
        headers: buildHeaders({ pid, sid }),
      }
    );
    const messages = sortMessagesForDisplay((data?.messages || []).map((msg) => normalizeServerMessage(msg)));
    session.messages = messages;
    if (data?.transcript_cache && typeof data.transcript_cache === "object") {
      session._serverTranscriptSnapshot = data.transcript_cache;
    } else {
      delete session._serverTranscriptSnapshot;
    }
    delete session._pending_client_msg_ids;
    app.state.sessions[sid] = session;
    scheduleSave();
  } catch (err) {
    appendLog(`[messages] ${err.message || err}`, "error");
  }
}

  async function sendMessage() {
    const pid = app.state.ui.activePid;
    const sid = app.state.ui.activeSid;
    const access = getActiveSessionAccess();
    if ((remoteEnabled() || hasGuestSessionAccess()) && access && !access.can_access) {
      appendLog("Join required to send messages.", "warn");
      return;
    }
    const text = app.dom.composerInput.value.trim();
    if (!pid || !sid) {
      appendLog("Select a project and session first", "warn");
      return;
    }
    if (!text) return;

    const cleaned = cleanupSessionDrafts(sid);
    if (cleaned && sid === app.state.ui.activeSid) {
      renderTranscript();
    }

    const now = Date.now();
    const dedupKey = `${sid}::${text}`;
    if (dedupKey === lastSendKey && now - lastSendAt < 400) {
      return;
    }
    lastSendKey = dedupKey;
    lastSendAt = now;

  // const hooks = app.plugins.slots.sendHooks;
  // let payload = { pid, sid, text };
  // for (const hook of hooks) {
  //   const fn = hook.fn || hook;
  //   const out = fn(payload, getPluginContext());
  //   if (out?.cancel) return;
  //   if (out?.text) payload.text = out.text;
  // }

  // const clientMsgId = randomId("msg");
  // const userMsg = {
  //   msg_id: clientMsgId,
  //   role: "user",
  //   content: payload.text,
  //   author: app.state.auth.alias || app.state.auth.username || "",
  //   meta: { client_msg_id: clientMsgId },
  // };
  // upsertMessage(sid, userMsg);
  // const session = app.state.sessions[sid];
  // const pending = getPendingClientMsgIds(session);
  // pending.add(clientMsgId);
  // savePendingClientMsgIds(session, pending);
  // scheduleSave();
  // app.dom.composerInput.value = "";
  // app.dom.draftStatus.textContent = "";

  // await startCompletionStream(pid, sid, payload.text, clientMsgId);

  const clientMsgId = randomId("msg");

  if (!app.state.auth.token && access?.allow_guest) {
    const alias = await ensureGuestAliasForSend();
    if (!alias) return;
  }

  // Commit the user message immediately so the transcript updates without waiting on slow plugins.
  // Plugins can still mutate the message content by returning out.text from sendHooks.
  const initialPayload = { pid, sid, text, client_msg_id: clientMsgId, handled: false };
  const userMsg = {
    msg_id: clientMsgId,
    role: "user",
    content: initialPayload.text,
    author: getDisplayAuthorLabel(),
    author_username: getCurrentActorUsername(),
    meta: { client_msg_id: clientMsgId },
    ts: Date.now(),
  };
  upsertMessage(sid, userMsg);
  {
    const session = app.state.sessions[sid];
    const pending = getPendingClientMsgIds(session);
    pending.add(clientMsgId);
    savePendingClientMsgIds(session, pending);
    scheduleSave();
  }
  app.dom.composerInput.value = "";
  app.dom.draftStatus.textContent = "";

  const hooks = app.plugins.slots.sendHooks;
  let payload = { ...initialPayload };
  const defaultSendHookTimeoutMs = 2500;

  for (const hook of hooks) {
    const sendHookTimeoutMs = Math.max(1, Number(hook?.timeoutMs) || defaultSendHookTimeoutMs);
    const fn = hook.fn || hook;
    let out = null;
    try {
      const maybeOut = fn(payload, getPluginContext());
      if (maybeOut && typeof maybeOut.then === "function") {
        out = await Promise.race([
          maybeOut,
          new Promise((_, reject) => setTimeout(() => reject(new Error(`send_hook_timeout:${sendHookTimeoutMs}`)), sendHookTimeoutMs)),
        ]);
      } else {
        out = maybeOut;
      }
    } catch (err) {
      appendLog(`[sendHook] ${(hook?.id || hook?.pluginId || fn?.name || "anonymous_hook")} ${err?.message || err}`, "warn");
      continue;
    }
    if (out?.cancel) {
      // Remove the message that we already inserted.
      try {
        const session = app.state.sessions[sid];
        if (session && Array.isArray(session.messages)) {
          session.messages = session.messages.filter((m) => m.msg_id !== clientMsgId);
        }
        const pending = getPendingClientMsgIds(session);
        pending.delete(clientMsgId);
        savePendingClientMsgIds(session, pending);
        scheduleSave();
      } catch (_err) {}
      // Restore draft (best-effort).
      try {
        app.dom.composerInput.value = text;
      } catch (_err) {}
      return;
    }
    if (out?.text) payload.text = out.text;
    if (out?.handled) payload.handled = true;
  }

  // Apply any text mutation from plugins to the already-inserted message.
  try {
    if (payload.text !== initialPayload.text) {
      const session = app.state.sessions[sid];
      const msg = session?.messages?.find?.((m) => m && m.msg_id === clientMsgId);
      if (msg) {
        msg.content = payload.text;
        updateMessageElement(msg);
        scheduleSave();
      }
    }
  } catch (_err) {}

  if (payload.handled) return;

  await startCompletionStream(pid, sid, payload.text, clientMsgId);
}

function prettyRouteName(routeId) {
  const rid = String(routeId || "").trim();
  if (!rid) return "AI Router";
  return rid
    .replace(/[-_]+/g, " ")
    .split(" ")
    .filter(Boolean)
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(" ");
}

function buildRouterStatusText(data) {
  const status = String(data?.router_status || "").trim();
  if (!status) return "";
  const routeId = String(data?.route_id || "").trim();
  const pretty = prettyRouteName(routeId);
  const lines = ["Checking ai router plugins...", `Using "${pretty}" ...`, status];
  const workflowName = String(data?.workflow_name || "").trim();
  const workflowSource = String(data?.workflow_source || "").trim();
  const workflowScore = Number(data?.workflow_score);
  const workflowReason = String(data?.workflow_reason || "").trim();
  const workflowStep = String(data?.workflow_step_label || data?.workflow_step || "").trim();
  const workflowState = String(data?.workflow_state || "").trim();
  if (workflowName) {
    let sourceLabel = workflowSource;
    if (sourceLabel === "existing") sourceLabel = "Agent Flow library";
    else if (sourceLabel === "created") sourceLabel = "created workflow";
    else if (sourceLabel === "search_miss") sourceLabel = "search result";
    const scoreText = Number.isFinite(workflowScore) ? ` | Score: ${workflowScore.toFixed(3)}` : "";
    lines.push(`Workflow: ${workflowName}${sourceLabel ? ` | Source: ${sourceLabel}` : ""}${scoreText}`);
  } else if (workflowSource === "search_miss" && Number.isFinite(workflowScore)) {
    lines.push(`Workflow search score: ${workflowScore.toFixed(3)}`);
  }
  if (workflowStep || workflowState) {
    lines.push(`Step: ${workflowStep || workflowState}${workflowStep && workflowState ? ` | ${workflowState}` : ""}`);
  }
  if (workflowReason) {
    lines.push(`Why: ${workflowReason}`);
  }
  const step = data?.step;
  const total = data?.total;
  if (step !== undefined && total !== undefined) {
    lines.push(`Progress: ${step}/${total}`);
  }
  return lines.filter(Boolean).join("\n");
}

function mergeRouterStatusContent(existing, next) {
  const current = String(existing || "").trim();
  const incoming = String(next || "").trim();
  if (!incoming) return current;
  if (!current || !current.startsWith("Checking ai router plugins")) return incoming;
  const currentLines = current.split("\n");
  const incomingLines = incoming.split("\n");
  const base = incomingLines.slice(0, 2);
  const currentDetails = currentLines.slice(2).filter(Boolean);
  const incomingDetails = incomingLines.slice(2).filter(Boolean);
  const replacePrefixes = ["Workflow:", "Workflow search score:", "Step:", "Why:", "Progress:"];
  const merged = [];
  const upsertLine = (line) => {
    const text = String(line || "").trim();
    if (!text) return;
    const prefix = replacePrefixes.find((candidate) => text.startsWith(candidate));
    if (prefix) {
      const index = merged.findIndex((entry) => String(entry || "").startsWith(prefix));
      if (index >= 0) {
        merged[index] = text;
        return;
      }
    }
    if (!merged.includes(text)) merged.push(text);
  };
  for (const line of currentDetails) upsertLine(line);
  for (const line of incomingDetails) upsertLine(line);
  return [...base, ...merged].filter(Boolean).join("\n");
}

function updateStreamMessageContent(sid, msgId, content, force, options = {}) {
  if (!sid || !msgId) return;
  const resolvedId = typeof resolveMessageId === "function" ? resolveMessageId(msgId) : msgId;
  const session = app.state.sessions[sid] || { sid, pid: app.state.ui.activePid, messages: [] };
  const messages = session.messages || [];
  let msg = messages.find((m) => m.msg_id === resolvedId);
  const existing = msg ? String(msg.content || "") : "";
  const placeholderId = app.streams.placeholderBySid[sid];
  const allowUpdate =
    force ||
    !existing.trim() ||
    existing.trim().startsWith("Checking ai router plugins") ||
    msg?.streaming ||
    resolvedId === placeholderId;
  if (!allowUpdate) return;
  if (!msg) {
    msg = {
      msg_id: resolvedId,
      role: "assistant",
      content: content,
      author: "assistant",
      streaming: true,
      ts: Date.now(),
      meta: options?.temporary ? { router_status_temporary: true } : {},
    };
    messages.push(msg);
  } else {
    msg.content = mergeRouterStatusContent(existing, content);
    msg.meta = msg.meta && typeof msg.meta === "object" ? msg.meta : {};
    if (options?.temporary) {
      msg.meta.router_status_temporary = true;
    }
  }
  session.messages = messages;
  app.state.sessions[sid] = session;
  scheduleSave();
  if (sid === app.state.ui.activeSid) {
    updateMessageElement(msg);
  }
}

function getStreamPlaceholderQueue(sid) {
  if (!app.streams.placeholderQueueBySid || typeof app.streams.placeholderQueueBySid !== "object") {
    app.streams.placeholderQueueBySid = {};
  }
  const current = app.streams.placeholderQueueBySid[sid];
  if (Array.isArray(current)) return current;
  app.streams.placeholderQueueBySid[sid] = [];
  return app.streams.placeholderQueueBySid[sid];
}

function getDraftClientMsgId(msg) {
  return String(msg?.meta?.client_msg_id || msg?.meta?.clientMsgId || "").trim();
}

function registerStreamPlaceholder(sid, streamId, clientMsgId) {
  if (!sid || !streamId) return;
  app.streams.placeholderBySid[sid] = streamId;
  const queue = getStreamPlaceholderQueue(sid);
  if (!queue.includes(streamId)) queue.push(streamId);
  const cmid = String(clientMsgId || "").trim();
  if (cmid) {
    if (!app.streams.placeholderByClientMsgId || typeof app.streams.placeholderByClientMsgId !== "object") {
      app.streams.placeholderByClientMsgId = {};
    }
    app.streams.placeholderByClientMsgId[cmid] = streamId;
  }
}

function unregisterStreamPlaceholders(sid, ids = []) {
  if (!sid) return;
  const idSet = new Set((Array.isArray(ids) ? ids : [ids]).filter(Boolean));
  if (!idSet.size) return;
  const queue = getStreamPlaceholderQueue(sid);
  app.streams.placeholderQueueBySid[sid] = queue.filter((id) => !idSet.has(id));
  if (idSet.has(app.streams.placeholderBySid[sid])) {
    delete app.streams.placeholderBySid[sid];
  }
  const byClient = app.streams.placeholderByClientMsgId || {};
  Object.entries(byClient).forEach(([cmid, id]) => {
    if (idSet.has(id)) delete byClient[cmid];
  });
}

function findPlaceholderForDraft(sid, msg) {
  if (!sid || !msg?.msg_id) return "";
  const cmid = getDraftClientMsgId(msg);
  const byClient = app.streams.placeholderByClientMsgId || {};
  if (cmid && byClient[cmid]) return byClient[cmid];
  const queue = getStreamPlaceholderQueue(sid);
  while (queue.length) {
    const candidate = queue[0];
    if (!candidate || candidate === msg.msg_id) {
      queue.shift();
      continue;
    }
    return candidate;
  }
  const placeholderId = app.streams.placeholderBySid[sid];
  return placeholderId && placeholderId !== msg.msg_id ? placeholderId : "";
}

function handleRouterDiag(sid, data, fallbackMsgId) {
  if (!sid || !data || typeof data !== "object") return false;
  const placeholderId = app.streams.placeholderBySid[sid];
  const msgId = data.msg_id || fallbackMsgId || placeholderId;
  if (!msgId) return false;
  if (data.router_result_text) {
    const resultText = String(data.router_result_text || "");
    if (resultText) {
      updateStreamMessageContent(sid, msgId, resultText, true);
      return true;
    }
  }
  const statusText = buildRouterStatusText(data);
  if (statusText) {
    const force = Boolean(data.flow_run_id);
    updateStreamMessageContent(sid, msgId, statusText, force, { temporary: data.router_status_temporary !== false });
    return true;
  }
  return false;
}

function userFacingStreamErrorMessage(err) {
  const raw = String(err?.message || err || "").trim();
  if (!raw) return "The assistant request failed before a response was returned. Check the log and try again.";
  if (/HTTP\s+401\b/i.test(raw) || /not authenticated/i.test(raw)) {
    return "Login required. Open Account > Login, sign in, and run the request again.";
  }
  if (/HTTP\s+403\b/i.test(raw) || /forbidden/i.test(raw)) {
    return "You do not have access to run this request in the current session.";
  }
  if (/HTTP\s+404\b/i.test(raw)) {
    return "The requested assistant route or session endpoint was not found.";
  }
  if (/HTTP\s+504\b/i.test(raw) || /timeout/i.test(raw)) {
    return "The assistant request timed out before it completed. Try again.";
  }
  return `Request failed: ${raw}`;
}

function surfaceStreamErrorToAssistant(sid, msgId, err) {
  const message = userFacingStreamErrorMessage(err);
  updateStreamMessageContent(sid, msgId, message, true);
  return message;
}

function getActiveModelContextLimit() {
  try {
    const providers = getSharedObjects({ type: "data_provider", pluginId: "model_deck" }) || [];
    const modelCtx = providers
      .filter((item) => item && item.service === "model_context")
      .sort((a, b) => Number(b.ts || 0) - Number(a.ts || 0))[0];
    const raw = Number(modelCtx?.ctx_limit_eff || modelCtx?.n_ctx || 0);
    return Number.isFinite(raw) && raw > 0 ? Math.floor(raw) : 0;
  } catch (_err) {
    return 0;
  }
}

function getEffectiveMaxTokensPreference() {
  const explicit = parseInt(app.state.prefs.maxTokens || "", 10);
  if (!Number.isNaN(explicit) && explicit > 0) return explicit;
  const ctxLimit = getActiveModelContextLimit();
  if (!ctxLimit) return null;
  return Math.max(1, ctxLimit - Math.min(512, Math.max(64, Math.floor(ctxLimit * 0.05))));
}

function updateMaxTokensPlaceholder() {
  if (!app?.dom?.maxTokens) return;
  const autoValue = getEffectiveMaxTokensPreference();
  app.dom.maxTokens.placeholder = autoValue != null ? `Auto: ${autoValue}` : "Auto from model context";
}


function mergeSystemPromptWithGeoContext(basePrompt) {
  const prompt = String(basePrompt || "").trim();
  const geo = buildGeoContextPromptSnippet();
  if (!geo) return prompt;
  return prompt ? `${prompt}\n\n${geo}` : geo;
}

async function startModelStream(pid, sid, prompt, clientMsgId) {
  const streamId = randomId("stream");
  app.streams.modeBySid[sid] = "local";
  registerStreamPlaceholder(sid, streamId, clientMsgId);
    const placeholder = {
      msg_id: streamId,
      role: "assistant",
      content: "",
      author: "assistant",
      streaming: true,
      meta: clientMsgId ? { client_msg_id: clientMsgId } : {},
      ts: Date.now(),
    };
  upsertMessage(sid, placeholder);

  const body = {
    prompt,
    alias: getPreferredAlias() || undefined,
    client_msg_id: clientMsgId,
  };
  const temp = parseFloat(app.state.prefs.temperature);
  const maxTokens = getEffectiveMaxTokensPreference();
  if (!Number.isNaN(temp)) body.temperature = temp;
  if (maxTokens != null) body.max_tokens = maxTokens;
  const mergedSystemPrompt = mergeSystemPromptWithGeoContext(app.state.prefs.systemPrompt);
  if (mergedSystemPrompt) body.system = mergedSystemPrompt;
  const contextMode = String(app.state.prefs.contextMode || "").trim();
  if (contextMode) body.ext = { ...(body.ext || {}), context_mode: contextMode };

  const url = `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/model_turn_stream`;
  const controller = new AbortController();
  app.streams.active[streamId] = controller;
  incrementSessionStream(sid);

  try {
    await streamSSE(url, {
      method: "POST",
      headers: { ...buildHeaders({ pid, sid }), "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
      onEvent: (event, data) => {
        if (event === "turn" && data?.msg_id) {
          const wasCurrent = app.streams.placeholderBySid[sid] === streamId;
          replaceMessageId(sid, streamId, data.msg_id);
          unregisterStreamPlaceholders(sid, [streamId]);
          if (wasCurrent) app.streams.placeholderBySid[sid] = data.msg_id;
        } else if (event === "message" && data?.msg) {
          handleSessionEvent("message", data);
        } else if (event === "token") {
          const msgId = data?.msg_id || streamId;
          appendToken(sid, msgId, data?.text || "");
        } else if (event === "diag") {
          if (handleRouterDiag(sid, data, streamId)) {
            return;
          }
          const err = data?.error;
          appendLog(`[diag] ${err || safeJson(data)}`, err ? "error" : "info");
        } else if (event === "done") {
          const msgId = data?.msg_id || streamId;
          markStreamDone(sid, msgId);
        }
      },
    });
  } catch (err) {
    appendLog(`[stream] ${err.message || err}`, "error");
    surfaceStreamErrorToAssistant(sid, streamId, err);
    markStreamDone(sid, streamId, { removeEmpty: false });
  } finally {
    delete app.streams.active[streamId];
    decrementSessionStream(sid);
  }
}

async function startCompletionStream(pid, sid, prompt, clientMsgId) {
  if (!app.state.remote.serverUrl) {
    appendLog("Server URL missing", "error");
    return;
  }
  const streamId = randomId("stream");
  const mode = "local";
  app.streams.modeBySid[sid] = mode;
  registerStreamPlaceholder(sid, streamId, clientMsgId);
  const placeholder = {
    msg_id: streamId,
    role: "assistant",
    content: "",
    author: "assistant",
    streaming: true,
    meta: clientMsgId ? { client_msg_id: clientMsgId } : {},
    ts: Date.now(),
  };
  upsertMessage(sid, placeholder);

  const payload = buildCompletionPayload(sid);
  payload.client_msg_id = clientMsgId;
  const controller = new AbortController();
  let sawDone = false;
  app.streams.active[streamId] = controller;
  incrementSessionStream(sid);

  const onEvent = (event, data) => {
    if (data === "[DONE]") {
      sawDone = true;
      if (mode === "local") {
        markStreamDone(sid, streamId);
        for (const handler of app.plugins.slots.eventHandlers) {
          try {
            const fn = handler.fn || handler;
            fn("assistant_done", { sid, msg_id: streamId, local: true }, getPluginContext());
          } catch (_err) {}
        }
      }
      try {
        controller.abort();
      } catch (_err) {}
      return;
    }
    if (event === "token") {
      if (mode === "local") {
        appendToken(sid, streamId, data?.text || "");
      }
      return;
    }
    if (event === "diag") {
      if (handleRouterDiag(sid, data, streamId)) {
        return;
      }
      const err = data?.error;
      appendLog(`[diag] ${safeJson(data)}`, err ? "error" : "info");
      return;
    }
    if (event === "plan" || event === "usage") {
      appendLog(`[${event}] ${safeJson(data)}`, "info");
      return;
    }
    if (event === "done") {
      sawDone = true;
      if (mode === "local") {
        if (data?.ok === false || data?.error) {
          const currentContent = getCurrentAssistantContent().trim();
          if (!currentContent || currentContent.startsWith("Checking ai router plugins")) {
            surfaceStreamErrorToAssistant(sid, streamId, data?.error || "assistant_request_failed");
          }
          if (data?.error) {
            appendLog(`[stream] ${data.error}`, "error");
          }
        }
        markStreamDone(sid, streamId);
        for (const handler of app.plugins.slots.eventHandlers) {
          try {
            const fn = handler.fn || handler;
            fn("assistant_done", { sid, msg_id: streamId, local: true }, getPluginContext());
          } catch (_err) {}
        }
      }
      try {
        controller.abort();
      } catch (_err) {}
    }
  };

  const runStream = async (headers, bodyPayload) => {
    await streamSSE("/v1/chat/completions_stream", {
      method: "POST",
      headers,
      body: JSON.stringify(bodyPayload),
      signal: controller.signal,
      onEvent,
    });
  };

  const getCurrentAssistantContent = () => {
    const session = app.state.sessions[sid] || {};
    const messages = Array.isArray(session.messages) ? session.messages : [];
    const msg = messages.find((entry) => entry && entry.msg_id === streamId);
    return String(msg?.content || "");
  };

  const shouldRetryWithoutSession = (err) => {
    const raw = String(err?.message || err || "");
    return /HTTP\s+404\b/i.test(raw) && /session not found/i.test(raw);
  };

  const buildDirectPayload = (basePayload) => {
    const ext = { ...((basePayload && basePayload.ext) || {}) };
    delete ext.project_id;
    delete ext.pid;
    delete ext.session_id;
    delete ext["session-id"];
    delete ext.sid;
    return {
      ...basePayload,
      ext,
      sid: "",
    };
  };

  try {
    await runStream(buildCompletionHeaders(pid, sid), payload);
  } catch (err) {
    if (!sawDone && shouldRetryWithoutSession(err)) {
      appendLog("[stream] session context missing; retrying direct chat", "warn");
      try {
        await runStream(buildCompletionHeaders("", ""), buildDirectPayload(payload));
        return;
      } catch (retryErr) {
        err = retryErr;
      }
    }
    if (sawDone) {
      markStreamDone(sid, streamId);
      return;
    }
    appendLog(`[stream] ${err.message || err}`, "error");
    surfaceStreamErrorToAssistant(sid, streamId, err);
    markStreamDone(sid, streamId, { removeEmpty: false });
  } finally {
    delete app.streams.active[streamId];
    decrementSessionStream(sid);
  }
}

function getRepoContextForSession(sid) {
  const store = app.state.repoPanel || {};
  const bySid = store.bySid || {};
  const entry = bySid[sid] || {};
  const selectedRepo = String(entry.selected_repo_id || entry.repo_id || "").trim();
  const selectedEntry = String(entry.selected_entry_path || "").trim();
  const selectedPrefix = String(entry.selected_path_prefix || "").trim();
  if (!selectedRepo && !selectedEntry && !selectedPrefix) return null;
  return {
    selected_repo_id: selectedRepo,
    selected_entry_path: selectedEntry,
    selected_path_prefix: selectedPrefix,
  };
}

function applyCompletionPayloadHooks(payload) {
  let next = payload;
  const ctx = getPluginContext();
  for (const hook of app.plugins.slots.completionPayloadHooks) {
    const fn = hook.fn || hook;
    const out = fn?.(next, ctx);
    if (out && typeof out === "object") {
      next = out;
    }
  }
  return next;
}

async function sendAssistantResponse() {
  const pid = app.state.ui.activePid;
  const sid = app.state.ui.activeSid;
  console.log("pid " + pid)
  console.log("sid " + sid)
  if (!pid || !sid) {
    appendLog("Select a project and session first", "warn");
    return;
  }
  const draft = app.dom.composerInput?.value?.trim() || "";
  if (draft) {
    await sendMessage();
    return;
  }
  const clientMsgId = randomId("msg");
  console.log("clientMsgId " + clientMsgId)
  await startCompletionStream(pid, sid, "", clientMsgId);
}

function buildCompletionPayload(sid) {
  const session = app.state.sessions[sid] || { messages: [] };
  const messages = (session.messages || []).map((m) => ({
    role: m.role || "user",
    content: m.content || "",
  }));

  if (app.state.prefs.systemPrompt) {
    if (!messages.length || messages[0].role !== "system") {
      messages.unshift({ role: "system", content: app.state.prefs.systemPrompt });
    } else if (!messages[0].content) {
      messages[0].content = app.state.prefs.systemPrompt;
    }
  }

  const payload = {
    model: "",
    messages,
    backend_type: "auto",
    stream: true,
    router_enabled_plugins: [],
    ext: {},
    sid,
  };
  const pid = app.state.ui.activePid;
  if (pid && sid) {
    payload.ext = {
      ...payload.ext,
      project_id: pid,
      session_id: sid,
      "session-id": sid,
      sid,
    };
  }
  const contextMode = String(app.state.prefs.contextMode || "").trim();
  if (contextMode) {
    payload.ext = { ...payload.ext, context_mode: contextMode };
  }
  const geoSystemPrompt = buildGeoContextPromptSnippet();
  if (geoSystemPrompt) {
    payload.ext = {
      ...payload.ext,
      system_prompts_mode: "system",
      system_prompts: [
        {
          id: "geo_context",
          content: geoSystemPrompt,
        },
      ],
      geo_context: {
        location: getGeoContextEffectiveLocation(),
        timezone: getGeoContextEffectiveTimeZone(),
        source: app.state.prefs.geoContextData?.source || "",
      },
    };
  }
  const routerCfg = getRouterConfig(sid);
  if (routerCfg.enabled.length) payload.router_enabled_plugins = routerCfg.enabled.slice();
  if (Object.keys(routerCfg.settings).length) {
    payload.ext = { ...payload.ext, router_plugin_settings: { ...routerCfg.settings } };
  }
  const repoCtx = getRepoContextForSession(sid);
  if (repoCtx && isPluginEnabled("repo_panel")) {
    payload.ext = { ...payload.ext, ...repoCtx };
  }
  const temp = parseFloat(app.state.prefs.temperature);
  const maxTokens = getEffectiveMaxTokensPreference();
  if (!Number.isNaN(temp)) payload.temperature = temp;
  if (maxTokens != null) payload.max_tokens = maxTokens;
  return applyCompletionPayloadHooks(payload);
}

function startSessionEvents() {
  const pid = app.state.ui.activePid;
  const sid = app.state.ui.activeSid;
  if (!pid || !sid) {
    stopSessionEvents();
    return;
  }
  if (!hasKnownRemoteSession(pid, sid)) {
    stopSessionEvents();
    return;
  }
  if (!(remoteEnabled() || hasGuestSessionAccess())) {
    stopSessionEvents();
    return;
  }
  const activeKey = `${pid}::${sid}`;
  if (app.streams.events && app.streams.eventsKey === activeKey && app.streams.eventsToken) {
    return;
  }
  stopSessionEvents();
  const url = `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/events`;
  const token = randomId("events");
  app.streams.eventsToken = token;
  app.streams.eventsKey = activeKey;
  void refreshRosterSnapshot();
  const run = async () => {
    let backoff = 400;
    while (app.streams.eventsToken === token) {
      const controller = new AbortController();
      app.streams.events = controller;
      try {
        await streamSSE(url, {
          headers: buildHeaders({ pid, sid }),
          signal: controller.signal,
          onEvent: (event, data) => {
            handleSessionEvent(event, data);
            for (const handler of app.plugins.slots.eventHandlers) {
              const fn = handler.fn || handler;
              fn(event, data, getPluginContext());
            }
          },
        });
      } catch (err) {
        if (controller.signal.aborted || app.streams.eventsToken !== token) break;
        appendLog(`[events] ${err.message || err}`, "warn");
      } finally {
        if (app.streams.events === controller) {
          app.streams.events = null;
        }
      }
      if (app.streams.eventsToken !== token) break;
      await delay(backoff);
      backoff = Math.min(Math.round(backoff * 1.6), 8000);
    }
  };
  void run();
}

async function refreshRosterSnapshot() {
  const pid = app.state.ui.activePid;
  const sid = app.state.ui.activeSid;
  if (!pid || !sid || !(remoteEnabled() || hasGuestSessionAccess())) return;
  try {
    const data = await apiJson(`/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/roster`, {
      headers: buildHeaders({ pid, sid }),
    });
    app.state.roster = data?.roster || [];
    scheduleSave();
    renderRoster();
  } catch (err) {
    appendLog(`[roster] ${err.message || err}`, "warn");
  }
}

function incrementSessionStream(sid) {
  if (!sid) return;
  app.streams.bySid[sid] = (app.streams.bySid[sid] || 0) + 1;
  renderSessionList();
}

function decrementSessionStream(sid) {
  if (!sid) return;
  const current = app.streams.bySid[sid] || 0;
  if (current <= 1) {
    delete app.streams.bySid[sid];
  } else {
    app.streams.bySid[sid] = current - 1;
  }
  renderSessionList();
}

function isSessionStreaming(sid) {
  return Boolean(sid && app.streams.bySid[sid]);
}

function stopSessionEvents() {
  if (app.streams.events) {
    app.streams.events.abort();
    app.streams.events = null;
  }
  app.streams.eventsToken = null;
  app.streams.eventsKey = "";
}

function handleSessionEvent(event, data) {
  const sid = app.state.ui.activeSid;
  const me = getCurrentActorUsername();
  if (event === "message" && data?.msg) {
    const msg = normalizeServerMessage(data.msg);
    if (msg?.meta?.is_draft) {
      msg.streaming = true;
    }
    const cmid = msg?.meta?.client_msg_id;
    if (sid && cmid && msg.role === "user") {
      const session = app.state.sessions[sid];
      const pending = getPendingClientMsgIds(session);
      if (pending.has(cmid)) {
        const existing = (session?.messages || []).find((m) => {
          if (!m || m.role !== "user") return false;
          return m?.meta?.client_msg_id === cmid || m?.msg_id === cmid;
        }) || findMessageByClientMsgId(session, cmid);
        if (existing?.msg_id && msg.msg_id && existing.msg_id !== msg.msg_id) {
          replaceMessageId(sid, existing.msg_id, msg.msg_id);
        }
        upsertMessage(sid, { ...msg, meta: { ...(existing?.meta || {}), ...(msg.meta || {}) } });
        pending.delete(cmid);
        savePendingClientMsgIds(session, pending);
        scheduleSave();
        return;
      }
    }
    if (sid && msg.role === "user") {
      const session = app.state.sessions[sid];
      const content = String(msg.content || "").trim();
      if (session && content) {
        const existing = (session.messages || [])
          .slice()
          .reverse()
          .find((m) => {
            if (!m || m.role !== "user") return false;
            if (String(m.content || "").trim() !== content) return false;
            const authorA = String(m.author || "").trim().toLowerCase();
            const authorB = String(msg.author || "").trim().toLowerCase();
            if (authorA && authorB && authorA !== authorB) return false;
            return true;
          });
        if (existing) {
          const prevTs = coerceMessageTs(existing.ts);
          const nextTs = coerceMessageTs(msg.ts);
          const mixedEpochScale = prevTs && nextTs && ((prevTs > 1e12 && nextTs < 1e11) || (nextTs > 1e12 && prevTs < 1e11));
          if (!mixedEpochScale && prevTs && (!nextTs || nextTs <= prevTs)) {
            return;
          }
        }
      }
    }
    if (
      sid &&
      msg.role === "assistant" &&
      msg?.meta?.is_draft &&
      isSessionStreaming(sid)
    ) {
      const cmid = getDraftClientMsgId(msg);
      const byClient = app.streams.placeholderByClientMsgId || {};
      // Only remap ids when this draft is tied to a local stream placeholder.
      // If cmid exists but is not local, this is another collaborator's draft.
      const ownedByClientMsg = cmid && byClient[cmid] ? byClient[cmid] : "";
      const placeholderId = ownedByClientMsg || (!cmid ? findPlaceholderForDraft(sid, msg) : "");
      const ownsPlaceholder = Boolean(
        placeholderId &&
        (ownedByClientMsg || getStreamPlaceholderQueue(sid).includes(placeholderId) || app.streams.placeholderBySid[sid] === placeholderId)
      );
      if (placeholderId && msg.msg_id && placeholderId !== msg.msg_id) {
        if (ownsPlaceholder) {
          const wasCurrent = app.streams.placeholderBySid[sid] === placeholderId;
          replaceMessageId(sid, placeholderId, msg.msg_id);
          unregisterStreamPlaceholders(sid, [placeholderId]);
          if (wasCurrent) app.streams.placeholderBySid[sid] = msg.msg_id;
        }
      }
      const isEmptyDraft = !String(msg.content || "").trim();
      if (ownsPlaceholder && isEmptyDraft) {
        const session = app.state.sessions[sid];
        const currentId = String(msg.msg_id || placeholderId || "").trim();
        const existing = (session?.messages || []).find((m) => m && m.msg_id === currentId);
        if (existing) {
          existing.meta = { ...(existing.meta || {}), ...(msg.meta || {}) };
          if (msg.ts) existing.ts = msg.ts;
          existing.streaming = true;
          scheduleSave();
          if (sid === app.state.ui.activeSid) updateMessageElement(existing);
        }
        return;
      }
      upsertMessage(sid, msg);
      return;
    }
    upsertMessage(sid, msg);
    return;
  }
  if (event === "token") {
    const mode = app.streams.modeBySid[sid] || "local";
    const tokenMsgId = String(data?.msg_id || "");
    // Agent flow streams use backend-generated ids like "<run_id>_stream".
    // Never suppress these, otherwise the sender can miss Agent Jobs updates
    // while collaborator views still render them.
    const isAgentFlowTokenStream = /_stream$/i.test(tokenMsgId);
    if (mode === "local" && sid && isSessionStreaming(sid) && data?.origin && data.origin === me && !isAgentFlowTokenStream) {
      return;
    }
    appendToken(sid, data?.msg_id, data?.text || "");
    return;
  }
  if (event === "done") {
    markStreamDone(sid, data?.msg_id);
    return;
  }
  if (event === "diag") {
    if (handleRouterDiag(sid, data)) {
      return;
    }
    appendLog(`[diag] ${data?.error || "stream error"}`, "error");
    return;
  }
  if (event === "presence") {
    updateRosterPresence(data);
    return;
  }
  if (event === "typing") {
    const alias = data?.alias || data?.username || "user";
    app.dom.typingStatus.textContent = data?.is_typing ? `${alias} is typing...` : "";
  }
}

function updateRosterPresence(data) {
  const action = data?.action || "";
  const username = data?.username || "";
  const alias = data?.alias || "";
  if (!username) return;
  const roster = app.state.roster || [];
  const idx = roster.findIndex((r) => r.username === username);
  if (action === "leave") {
    if (idx >= 0) roster.splice(idx, 1);
  } else {
    const row = { username, alias };
    if (idx >= 0) roster[idx] = row;
    else roster.push(row);
  }
  app.state.roster = roster;
  scheduleSave();
  renderRoster();
}

function getPendingClientMsgIds(session) {
  if (!session || typeof session !== "object") return new Set();
  const raw = session._pending_client_msg_ids;
  if (Array.isArray(raw)) return new Set(raw);
  return new Set();
}

function savePendingClientMsgIds(session, pending) {
  if (!session || typeof session !== "object") return;
  session._pending_client_msg_ids = Array.from(pending || []);
}

function findMessageByClientMsgId(session, clientMsgId) {
  if (!session || !clientMsgId) return null;
  return (session.messages || []).find((m) => m?.meta?.client_msg_id === clientMsgId || m?.msg_id === clientMsgId) || null;
}

function getMessageClientMsgId(msg) {
  return String(msg?.meta?.client_msg_id || msg?.meta?.clientMsgId || msg?.client_msg_id || "").trim();
}

function getAssistantInsertIndex(messages, msg) {
  if (!Array.isArray(messages) || !msg || msg.role !== "assistant") return -1;
  const cmid = getMessageClientMsgId(msg);
  if (!cmid) return -1;
  let anchor = -1;
  for (let i = 0; i < messages.length; i += 1) {
    const row = messages[i];
    if (!row || row.role !== "user") continue;
    const rowCmid = getMessageClientMsgId(row) || String(row.msg_id || "").trim();
    if (rowCmid && rowCmid === cmid) anchor = i;
  }
  if (anchor < 0) return -1;
  let insertAt = anchor + 1;
  for (let i = anchor + 1; i < messages.length; i += 1) {
    const row = messages[i];
    if (!row) continue;
    if (row.role === "assistant" && getMessageClientMsgId(row) === cmid) {
      insertAt = i + 1;
      continue;
    }
    break;
  }
  return insertAt;
}

function upsertMessage(sid, msg) {
  if (!sid) return;
  const session = app.state.sessions[sid] || { sid, pid: app.state.ui.activePid, messages: [] };
  const messages = session.messages || [];
  const idx = msg.msg_id ? messages.findIndex((m) => m.msg_id === msg.msg_id) : -1;
  if (idx >= 0) {
    messages[idx] = { ...messages[idx], ...msg };
  } else {
    const insertAt = getAssistantInsertIndex(messages, msg);
    if (insertAt >= 0 && insertAt <= messages.length) messages.splice(insertAt, 0, msg);
    else messages.push(msg);
  }
  dedupeSessionMessages(session);
  session.messages = sortMessagesForDisplay(messages);
  app.state.sessions[sid] = session;
  scheduleSave();
  if (sid === app.state.ui.activeSid) {
    if (idx >= 0) updateMessageElement(msg);
    else renderTranscript();
  }
}

function stripLeadingStreamFailureText(text) {
  const s = String(text || "");
  return s.replace(/^\[(?:stream error|stream ended)\][^\n]*\s*/i, "");
}

function replaceMessageId(sid, oldId, newId) {
  if (!sid || !oldId || !newId) return;
  const session = app.state.sessions[sid];
  if (!session) return;
  const idx = (session.messages || []).findIndex((m) => m.msg_id === oldId);
  if (idx < 0) return;
  const msg = session.messages[idx];
  msg.msg_id = newId;
  for (let i = session.messages.length - 1; i >= 0; i -= 1) {
    if (i === idx) continue;
    if (session.messages[i]?.msg_id === newId) {
      session.messages.splice(i, 1);
    }
  }
  app.state.sessions[sid] = session;
  app.streams.msgAliases[oldId] = newId;
  if (sid === app.state.ui.activeSid) {
    const node = app.dom.messageNodes[oldId];
    if (node) {
      delete app.dom.messageNodes[oldId];
      node.dataset.msgId = newId;
      app.dom.messageNodes[newId] = node;
    } else {
      renderTranscript();
    }
  }
  scheduleSave();
}

function appendToken(sid, msgId, text) {
  if (!sid || !msgId || !text) return;
  const session = app.state.sessions[sid];
  if (!session) return;
  const resolvedId = resolveMessageId(msgId);
  const msg = session.messages.find((m) => m.msg_id === resolvedId);
    if (!msg) {
      session.messages.push({
        msg_id: resolvedId,
        role: "assistant",
        content: text,
        author: "assistant",
        streaming: true,
        ts: Date.now(),
      });
    } else {
      const existingRaw = String(msg.content || "");
      const temporaryStatus = Boolean(msg.meta && typeof msg.meta === "object" && msg.meta.router_status_temporary);
      const existing = temporaryStatus ? "" : stripLeadingStreamFailureText(existingRaw);
      msg.content = existing.trim() ? `${existing}${text}` : text;
      if (msg.meta && typeof msg.meta === "object") {
        if (msg.meta.keep_placeholder) {
          delete msg.meta.keep_placeholder;
        }
        if (msg.meta.router_status_temporary) {
          delete msg.meta.router_status_temporary;
        }
      }
    }
  scheduleSave();
  if (sid === app.state.ui.activeSid) {
    const autoScroll = shouldAutoScroll();
    updateMessageElement(msg || session.messages.find((m) => m.msg_id === resolvedId));
    if (autoScroll) scrollToBottom();
  }
}

function markStreamDone(sid, msgId, options = {}) {
  if (!sid || !msgId) return;
  const session = app.state.sessions[sid];
  if (!session) return;
  const resolvedId = resolveMessageId(msgId);
  const msg = session.messages.find((m) => m.msg_id === resolvedId);
  if (msg) {
    msg.streaming = false;
    const isEmpty =
      (Array.isArray(msg.content) && msg.content.length === 0) ||
      (!Array.isArray(msg.content) && !String(msg.content || "").trim());
    const removeEmpty = options?.removeEmpty !== false;
    const keepPlaceholder = Boolean(options?.keepPlaceholder);
    if (msg.role === "assistant" && isEmpty && removeEmpty) {
      session.messages = session.messages.filter((m) => m.msg_id !== resolvedId);
      app.state.sessions[sid] = session;
      const node = app.dom.messageNodes?.[resolvedId];
      if (node) {
        node.remove();
        delete app.dom.messageNodes[resolvedId];
      }
      scheduleSave();
    } else {
      if (keepPlaceholder) {
        msg.meta = { ...(msg.meta || {}), keep_placeholder: true };
      } else if (msg.meta?.keep_placeholder) {
        delete msg.meta.keep_placeholder;
      }
      updateMessageElement(msg);
      scheduleSave();
    }
  }
  unregisterStreamPlaceholders(sid, [msgId, resolvedId]);
  if (app.streams.modeBySid[sid]) {
    delete app.streams.modeBySid[sid];
  }
}

function resolveMessageId(msgId) {
  let current = msgId;
  const seen = new Set();
  while (current && app.streams.msgAliases[current] && !seen.has(current)) {
    seen.add(current);
    current = app.streams.msgAliases[current];
  }
  return current || msgId;
}

function applyLoginResponse(data, fallbackUser) {
  clearRequestCaches();
  app.state.auth.token = data.token;
  app.state.auth.username = data.username || fallbackUser || "";
  app.state.auth.role = data.role || "user";
  app.state.auth.mustChange = Boolean(data.must_change_pw);
  app.state.remote.enabled = true;
  scheduleSave();
  renderAuthStatus();
  renderStatus("online");
  renderTopRightIconRow();
  renderPluginPanels();
  renderAccountMenu();
  renderChatsOverride();
  applyChatInfoToInputs();
  void refreshPermissionState({ silent: true });
  void refreshGuiPluginsDiscovery();
  void discoverRemoteServerUrl().then(() => {
    applyStateToInputs();
  }).catch(() => {});
  void bootstrapRemote();
  try {
    window.dispatchEvent(new CustomEvent("chatjs:auth-changed", {
      detail: {
        username: app.state.auth.username || "",
        role: app.state.auth.role || "",
        loggedIn: Boolean(app.state.auth.token),
      },
    }));
  } catch (_err) {}
}

async function loginWithCredentials(username, password) {
  if (!username || !password) {
    appendLog("Enter username and password", "warn");
    return { ok: false };
  }
  try {
    const data = await apiJson("/v1/auth/login", {
      method: "POST",
      body: { username, password },
    });
    if (!data?.token) {
      appendLog("Login failed", "error");
      return { ok: false };
    }
    applyLoginResponse(data, username);
    return { ok: true, data };
  } catch (err) {
    appendLog(`[login] ${err.message || err}`, "error");
    return { ok: false, error: err };
  }
}

async function login() {
  const username = app.dom.loginUser.value.trim();
  const password = app.dom.loginPass.value;
  const res = await loginWithCredentials(username, password);
  if (!res.ok) return;
  app.dom.loginPass.value = "";
}

async function logout(announce) {
  clearRequestCaches();
  if (announce && remoteEnabled()) {
    try {
      await apiJson("/v1/auth/logout", { method: "POST" });
    } catch (err) {
      appendLog(`[logout] ${err.message || err}`, "warn");
    }
  }
  stopSessionEvents();
  app.state.auth.token = "";
  app.state.auth.username = "";
  app.state.auth.role = "";
  app.state.auth.mustChange = false;
  app.state.sessionAccess = {};
  clearPermissionsState();
  ensureLocalDefaults();
  scheduleSave();
  renderAuthStatus();
  renderStatus();
  renderTopRightIconRow();
  renderPluginPanels();
  renderAccountMenu();
  renderChatsOverride();
  renderChatsOverride();
  applyPermissionVisibility();
  applyChatInfoToInputs();
  try {
    window.dispatchEvent(new CustomEvent("chatjs:auth-changed", {
      detail: {
        username: "",
        role: "",
        loggedIn: false,
      },
    }));
  } catch (_err) {}
}

async function handleUpload() {
  const input = document.createElement("input");
  input.type = "file";
  input.multiple = true;
  input.addEventListener("change", async () => {
    const files = Array.from(input.files || []);
    if (!files.length) return;
    for (const file of files) {
      if (remoteEnabled()) {
        await uploadFile(file);
      } else {
        app.state.pendingUploads.push({
          name: file.name,
          size: file.size,
          mime: file.type,
        });
        appendLog(`[upload] staged ${file.name}`, "info");
      }
    }
    scheduleSave();
  });
  input.click();
}

async function uploadFile(file) {
  try {
    const fd = new FormData();
    fd.append("file", file);
    const url = `${normalizeServerUrl(app.state.remote.serverUrl)}/v1/media/upload`;
    const res = await fetch(url, {
      method: "POST",
      headers: buildHeaders(),
      body: fd,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data?.download_url) {
      appendLog(`[upload] failed for ${file.name}`, "error");
      return;
    }
    app.state.pendingUploads.push({
      name: file.name,
      size: data.size || file.size,
      mime: file.type,
      download_url: data.download_url,
    });
    appendLog(`[upload] uploaded ${file.name}`, "info");
  } catch (err) {
    appendLog(`[upload] ${err.message || err}`, "error");
  }
}

function buildHeaders(extra = {}) {
  const headers = {};
  if (isAuthEnabled()) {
    const enabled = new Set(["collab_chat", "plugin_repo"]);
    for (const plugin of app.plugins.list || []) {
      const pid = String(plugin?.id || "").trim();
      if (!pid) continue;
      if (isPluginEnabled(pid)) enabled.add(pid);
    }
    headers["X-Gui-Enabled-Plugins"] = Array.from(enabled).sort().join(",");
  }
  if (app.state.auth.token) {
    headers.Authorization = `Bearer ${app.state.auth.token}`;
  }
  if (!app.state.auth.token && app.state.auth.guestId) {
    headers["X-Guest-Id"] = app.state.auth.guestId;
  }
  if (app.state.auth.alias) {
    headers["X-User-Alias"] = app.state.auth.alias;
  }
  if (extra.pid) headers["X-Project-Id"] = extra.pid;
  if (extra.sid) headers["X-Session-Id"] = extra.sid;
  return { ...headers, ...extra.headers };
}

function buildDirectStreamHeaders() {
  return { "Content-Type": "application/json" };
}

function buildCompletionHeaders(pid, sid) {
  return {
    ...buildHeaders({ pid, sid }),
    "Content-Type": "application/json",
  };
}

async function apiJson(path, options = {}) {
  const url = `${normalizeServerUrl(app.state.remote.serverUrl)}${path}`;
  const method = options.method || "GET";
  const baseHeaders = buildHeaders();
  const headers = options.headers ? { ...baseHeaders, ...options.headers } : baseHeaders;
  const init = { method, headers };
  let timeoutId = null;
  if (options.signal) init.signal = options.signal;
  if (!init.signal && Number(options.timeoutMs || 0) > 0 && typeof AbortController !== "undefined") {
    const controller = new AbortController();
    init.signal = controller.signal;
    timeoutId = setTimeout(() => controller.abort(), Number(options.timeoutMs || 0));
  }
  if (options.body) {
    init.body = JSON.stringify(options.body);
    init.headers = { ...headers, "Content-Type": "application/json" };
  }
  try {
    return await fetchJsonWithCache(url, init, options);
  } catch (err) {
    if (err && err.name === "AbortError") {
      throw new Error(`Request timed out: ${path}`);
    }
    throw err;
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
  }
}

function normalizeRouterStateSnapshot(value) {
  const src = value && typeof value === "object" ? value : {};
  const router = src.router && typeof src.router === "object" ? src.router : src;
  return {
    manifest: router.manifest && typeof router.manifest === "object" ? router.manifest : {},
    enabled: router.enabled && typeof router.enabled === "object" ? router.enabled : {},
    settings: sanitizeRouterSettingsForStorage(router.settings),
    manifest_ts: router.manifest_ts || 0,
  };
}

function mergeRouterStateIntoApp(routerState) {
  ensureRouterState();
  const normalized = normalizeRouterStateSnapshot(routerState);
  app.state.router.manifest = {
    ...(app.state.router.manifest || {}),
    ...(normalized.manifest || {}),
  };
  app.state.router.enabled = {
    ...(app.state.router.enabled || {}),
    ...(normalized.enabled || {}),
  };
  app.state.router.settings = {
    ...(app.state.router.settings || {}),
    ...(normalized.settings || {}),
  };
  app.state.router.manifest_ts = Math.max(
    Number(app.state.router.manifest_ts || 0),
    Number(normalized.manifest_ts || 0)
  );
  saveRouterStateSnapshot(app.state);
  scheduleSave();
}

function routerProjectDefaultsKey(pid = app.state?.ui?.activePid) {
  const cleanPid = String(pid || "").trim();
  return cleanPid ? `${cleanPid}::__project__` : "__project__";
}

function getProjectRouterDefaults(pid = app.state?.ui?.activePid) {
  ensureRouterState();
  const key = routerProjectDefaultsKey(pid);
  const enabled = Array.isArray(app.state.router.enabled?.[key]) ? app.state.router.enabled[key].slice() : [];
  const settings = app.state.router.settings?.[key];
  return {
    enabled,
    settings: settings && typeof settings === "object" ? { ...settings } : {},
  };
}

function setProjectRouterDefaults(enabled, settings, pid = app.state?.ui?.activePid) {
  ensureRouterState();
  const key = routerProjectDefaultsKey(pid);
  if (Array.isArray(enabled)) {
    app.state.router.enabled[key] = enabled.slice();
  } else {
    delete app.state.router.enabled[key];
  }
  if (settings && typeof settings === "object") {
    app.state.router.settings[key] = JSON.parse(JSON.stringify(settings));
  } else {
    delete app.state.router.settings[key];
  }
}

function stripProjectRouterDefaultsFromSnapshot(routerState) {
  const normalized = normalizeRouterStateSnapshot(routerState);
  Object.keys(normalized.enabled || {}).forEach((key) => {
    if (String(key || "").endsWith("::__project__") || String(key || "") === "__project__") {
      delete normalized.enabled[key];
    }
  });
  Object.keys(normalized.settings || {}).forEach((key) => {
    if (String(key || "").endsWith("::__project__") || String(key || "") === "__project__") {
      delete normalized.settings[key];
    }
  });
  return normalized;
}

function routerKeyBelongsToProject(key, pid, state = app.state) {
  const projectId = String(pid || "").trim();
  const scopeKey = String(key || "").trim();
  if (!projectId || !scopeKey) return false;
  if (scopeKey === routerProjectDefaultsKey(projectId)) return true;
  if (scopeKey.startsWith(`${projectId}::`)) return true;
  if (!scopeKey.includes("::")) {
    const sess = state?.sessions?.[scopeKey];
    if (sess && String(sess.pid || "").trim() === projectId) return true;
  }
  return false;
}

function projectRouterSnapshot(routerState, pid, state = app.state) {
  const normalized = stripProjectRouterDefaultsFromSnapshot(routerState);
  const projectId = String(pid || "").trim();
  if (!projectId) return normalized;
  const enabled = {};
  const settings = {};
  Object.entries(normalized.enabled || {}).forEach(([key, value]) => {
    if (routerKeyBelongsToProject(key, projectId, state)) enabled[key] = value;
  });
  Object.entries(normalized.settings || {}).forEach(([key, value]) => {
    if (routerKeyBelongsToProject(key, projectId, state)) settings[key] = value;
  });
  return {
    manifest: {},
    enabled,
    settings,
    manifest_ts: normalized.manifest_ts || 0,
  };
}

function clearProjectRouterScopesFromApp(pid) {
  ensureRouterState();
  const projectId = String(pid || "").trim();
  if (!projectId) return;
  Object.keys(app.state.router.enabled || {}).forEach((key) => {
    if (routerKeyBelongsToProject(key, projectId, app.state)) {
      delete app.state.router.enabled[key];
    }
  });
  Object.keys(app.state.router.settings || {}).forEach((key) => {
    if (routerKeyBelongsToProject(key, projectId, app.state)) {
      delete app.state.router.settings[key];
    }
  });
}

async function loadProjectRouterPrefs(pid, options = {}) {
  const projectId = String(pid || "").trim();
  if (!projectId || !canUseRemoteServer() || !hasRemoteAuth()) return false;
  app.routerPrefsLoaded = app.routerPrefsLoaded || {};
  app.routerPrefsLoading = app.routerPrefsLoading || {};
  app.routerPrefsFailedAt = app.routerPrefsFailedAt || {};
  if (!options.force && app.routerPrefsLoaded[projectId]) return true;
  if (!options.force && app.routerPrefsLoading[projectId]) return app.routerPrefsLoading[projectId];
  const failedAt = Number(app.routerPrefsFailedAt[projectId] || 0);
  if (!options.force && failedAt && (Date.now() - failedAt) < 5000) return false;

  const promise = (async () => {
    try {
      const data = await apiJson(`/v1/projects/${encodeURIComponent(projectId)}/gui_prefs`, {
        headers: buildHeaders({ pid: projectId }),
        timeoutMs: 15000,
      });
      const defaultPrefs = data?.default_prefs && typeof data.default_prefs === "object" ? data.default_prefs : {};
      const projectRouterDefaults = defaultPrefs.router_project_defaults && typeof defaultPrefs.router_project_defaults === "object"
        ? defaultPrefs.router_project_defaults
        : null;
      setProjectRouterDefaults(
        projectRouterDefaults ? projectRouterDefaults.enabled : null,
        projectRouterDefaults ? projectRouterDefaults.settings : null,
        projectId
      );
      const prefs = data?.prefs && typeof data.prefs === "object" ? data.prefs : {};
      const routerPrefs = prefs.router_state && typeof prefs.router_state === "object"
        ? projectRouterSnapshot(prefs.router_state, projectId)
        : null;
      if (routerPrefs) {
        clearProjectRouterScopesFromApp(projectId);
        mergeRouterStateIntoApp(routerPrefs);
        renderRouterPluginsList();
        renderTranscriptBars();
        renderPluginPanels();
      }
      const uiPrefs = prefs.ui_state && typeof prefs.ui_state === "object" ? prefs.ui_state : null;
      if (uiPrefs) {
        const savedPid = String(uiPrefs.activePid || "").trim();
        const savedSid = String(uiPrefs.activeSid || "").trim();
        if (savedPid === projectId && savedSid) {
          app.state.ui.lastSessionByProject = app.state.ui.lastSessionByProject || {};
          app.state.ui.lastSessionByProject[projectId] = savedSid;
        }
      }
      app.routerPrefsLoaded[projectId] = true;
      delete app.routerPrefsFailedAt[projectId];
      return true;
    } catch (err) {
      app.routerPrefsFailedAt[projectId] = Date.now();
      appendLog(`[router] project settings load skipped: ${err.message || err}`, "warn");
      return false;
    } finally {
      delete app.routerPrefsLoading[projectId];
    }
  })();

  app.routerPrefsLoading[projectId] = promise;
  return promise;
}

let routerPrefsSaveTimer = null;

function scheduleProjectRouterPrefsSave(pid = app.state?.ui?.activePid) {
  const projectId = String(pid || "").trim();
  if (!projectId || !canUseRemoteServer() || !hasRemoteAuth()) return;
  if (routerPrefsSaveTimer) clearTimeout(routerPrefsSaveTimer);
  routerPrefsSaveTimer = setTimeout(() => {
    routerPrefsSaveTimer = null;
    void saveProjectRouterPrefs(projectId);
  }, 250);
}

async function saveProjectRouterPrefs(pid = app.state?.ui?.activePid) {
  const projectId = String(pid || "").trim();
  if (!projectId || !canUseRemoteServer() || !hasRemoteAuth()) return false;
  try {
    const current = await apiJson(`/v1/projects/${encodeURIComponent(projectId)}/gui_prefs`, {
      headers: buildHeaders({ pid: projectId }),
      timeoutMs: 8000,
    }).catch(() => ({ prefs: {} }));
    const prefs = current?.prefs && typeof current.prefs === "object" ? { ...current.prefs } : {};
    prefs.router_state = projectRouterSnapshot(buildRouterStateSnapshot(app.state).router, projectId);
    prefs.ui_state = {
      activePid: String(app.state?.ui?.activePid || ""),
      activeSid: String(app.state?.ui?.activeSid || ""),
      updated_ts: Date.now(),
    };
    await apiJson(`/v1/projects/${encodeURIComponent(projectId)}/gui_prefs`, {
      method: "PUT",
      headers: buildHeaders({ pid: projectId }),
      body: { scope: "user", prefs },
      timeoutMs: 8000,
    });
    if (hasPermission("plugins.manage.install", false)) {
      const currentProjectPrefs = current?.default_prefs && typeof current.default_prefs === "object"
        ? { ...current.default_prefs }
        : {};
      const projectDefaults = getProjectRouterDefaults(projectId);
      currentProjectPrefs.router_project_defaults = {
        enabled: Array.isArray(projectDefaults.enabled) ? projectDefaults.enabled.slice() : [],
        settings: sanitizeRouterSettingsForStorage({
          [routerProjectDefaultsKey(projectId)]: projectDefaults.settings || {},
        })[routerProjectDefaultsKey(projectId)] || {},
      };
      await apiJson(`/v1/projects/${encodeURIComponent(projectId)}/gui_prefs`, {
        method: "PUT",
        headers: buildHeaders({ pid: projectId }),
        body: { scope: "project", prefs: currentProjectPrefs },
        timeoutMs: 8000,
      });
    }
    app.routerPrefsLoaded = app.routerPrefsLoaded || {};
    app.routerPrefsLoaded[projectId] = true;
    return true;
  } catch (err) {
    appendLog(`[router] project settings save failed: ${err.message || err}`, "warn");
    return false;
  }
}

async function ensureAuxServiceUrlsResolved() {
  if (normalizeServerUrl(app.state.remote.hostServiceUrl || "") && normalizeServerUrl(app.state.remote.clientServiceUrl || "")) {
    return;
  }
  if (app.serviceUrlResolvePromise) {
    await app.serviceUrlResolvePromise;
    return;
  }
  const embedCfg = window.__CHAT_JS_EMBED_CONFIG || {};
  const identifierKey = String(embedCfg.identifierKey || embedCfg.identifier_key || "").trim();
  if (!identifierKey) return;
  const cmsBase = String(embedCfg.cmsBase || embedCfg.cms_base || "https://account.gotchat.ai").trim().replace(/\/+$/, "");
  if (!cmsBase) return;

  app.serviceUrlResolvePromise = (async () => {
    const trimSlash = (v) => String(v || "").trim().replace(/\/+$/, "");
    const lower = (v) => String(v || "").trim().toLowerCase();
    const asNum = (v) => {
      const n = Number(v);
      return Number.isFinite(n) ? n : 0;
    };
    const looksLikeService = (svc, host, port) => {
      const s = lower(svc);
      if (!s) return false;
      if (host && s.includes(`${String(host).toLowerCase()}:${String(port || "")}`)) return true;
      return false;
    };
    try {
      const url = `${cmsBase}/api/docker/public-urls?key=${encodeURIComponent(identifierKey)}`;
      const resp = await fetch(url, { credentials: "omit", mode: "cors", cache: "no-cache" });
      if (resp.ok) {
        const payload = (await resp.json()) || {};
        const data = payload.data || payload.Data || {};
        const hostServiceUrl = trimSlash(data.hostServiceUrl || data.HostServiceUrl || "");
        const clientServiceUrl = trimSlash(data.clientServiceUrl || data.ClientServiceUrl || "");
        if (hostServiceUrl && !normalizeServerUrl(app.state.remote.hostServiceUrl || "")) {
          app.state.remote.hostServiceUrl = normalizeServerUrl(hostServiceUrl);
        }
        if (clientServiceUrl && !normalizeServerUrl(app.state.remote.clientServiceUrl || "")) {
          app.state.remote.clientServiceUrl = normalizeServerUrl(clientServiceUrl);
        }
      }
    } catch (_err) {}

    if (normalizeServerUrl(app.state.remote.hostServiceUrl || "") && normalizeServerUrl(app.state.remote.clientServiceUrl || "")) {
      return;
    }

    try {
      const url = `${cmsBase}/api/docker/host-mappings?key=${encodeURIComponent(identifierKey)}`;
      const resp = await fetch(url, { credentials: "omit", mode: "cors", cache: "no-cache" });
      if (!resp.ok) return;
      const payload = (await resp.json()) || {};
      const items = Array.isArray(payload.data || payload.Data) ? (payload.data || payload.Data) : [];
      const pickByPort = (port, hostnameHint, serviceHost) => {
        const candidates = items.filter((m) => {
          const lp = asNum(m.localPort);
          return lp === port || looksLikeService(m.service, serviceHost, port);
        });
        const hinted = hostnameHint
          ? candidates.filter((m) => lower(m.hostname).includes(String(hostnameHint).toLowerCase()))
          : [];
        const sorted = (hinted.length ? hinted : candidates)
          .slice()
          .sort((a, b) => Date.parse(String(b.updatedAt || "")) - Date.parse(String(a.updatedAt || "")));
        const hit = sorted[0];
        return hit ? trimSlash(hit.publicUrl || `https://${String(hit.hostname || "").trim()}`) : "";
      };
      if (!normalizeServerUrl(app.state.remote.hostServiceUrl || "")) {
        const hostUrl = pickByPort(8765, "hostservice", "llmloader2");
        if (hostUrl) app.state.remote.hostServiceUrl = normalizeServerUrl(hostUrl);
      }
      if (!normalizeServerUrl(app.state.remote.clientServiceUrl || "")) {
        const clientUrl = pickByPort(8766, "jshostservice", "gui_js") || pickByPort(8766, "hostservice", "gui_js");
        if (clientUrl) app.state.remote.clientServiceUrl = normalizeServerUrl(clientUrl);
      }
    } catch (_err) {}
  })();

  try {
    await app.serviceUrlResolvePromise;
  } finally {
    app.serviceUrlResolvePromise = null;
  }
}

function cloneCachedJson(value) {
  if (value === undefined) return value;
  try {
    if (typeof structuredClone === "function") {
      return structuredClone(value);
    }
  } catch (_err) {}
  try {
    return JSON.parse(JSON.stringify(value));
  } catch (_err) {
    return value;
  }
}

function clearRequestCaches() {
  app.requestCache?.inflight?.clear?.();
  app.requestCache?.responses?.clear?.();
}

function buildRequestCacheKey(url, method, headers = {}) {
  const headerPairs = Object.entries(headers || {})
    .map(([k, v]) => [String(k || "").toLowerCase(), String(v || "")])
    .sort((a, b) => a[0].localeCompare(b[0]));
  return JSON.stringify([String(method || "GET").toUpperCase(), String(url || ""), headerPairs]);
}

function getJsonRequestPolicy(url, method, options = {}) {
  const verb = String(method || "GET").toUpperCase();
  if (verb !== "GET") return { dedupe: false, ttlMs: 0 };
  if (options?.cache === false) return { dedupe: false, ttlMs: 0 };
  let pathname = "";
  try {
    pathname = new URL(String(url || ""), window.location.origin).pathname || "";
  } catch (_err) {}
  if (/\/events(?:\/|$)/i.test(pathname) || /(?:^|\/)stream(?:\/|$)/i.test(pathname)) {
    return { dedupe: false, ttlMs: 0 };
  }
  if (Number.isFinite(Number(options?.cacheTtlMs))) {
    return { dedupe: options?.dedupe !== false, ttlMs: Math.max(0, Number(options.cacheTtlMs || 0)) };
  }
  let ttlMs = 0;
  if (/\/v1\/projects$/i.test(pathname)) ttlMs = 3000;
  else if (/\/v1\/projects\/[^/]+\/sessions$/i.test(pathname)) ttlMs = 3000;
  else if (/\/v1\/projects\/[^/]+\/gui_prefs$/i.test(pathname)) ttlMs = 8000;
  else if (/\/v1\/[^/]+\/default_theme$/i.test(pathname)) ttlMs = 10000;
  else if (/\/v1\/chat_ui\/info$/i.test(pathname)) ttlMs = 10000;
  else if (/\/v1\/router\/plugins$/i.test(pathname)) ttlMs = 10000;
  else if (/\/v1\/plugin_repo\/(approved|downloads|installed|status)$/i.test(pathname)) ttlMs = 10000;
  else if (/\/v1\/plugin_repo\/search$/i.test(pathname)) ttlMs = 5000;
  else if (/\/v1\/client\/gui_js\/installed$/i.test(pathname)) ttlMs = 10000;
  return { dedupe: true, ttlMs };
}

function pruneJsonResponseCache() {
  const store = app.requestCache?.responses;
  if (!store || store.size <= 200) return;
  const entries = Array.from(store.entries()).sort((a, b) => Number(a[1]?.expiresAt || 0) - Number(b[1]?.expiresAt || 0));
  const removeCount = Math.max(0, entries.length - 150);
  for (let i = 0; i < removeCount; i += 1) {
    store.delete(entries[i][0]);
  }
}

async function fetchJsonWithCache(url, init, options = {}) {
  const method = init?.method || "GET";
  const headers = init?.headers || {};
  const policy = getJsonRequestPolicy(url, method, options);
  const canCache = policy.dedupe || policy.ttlMs > 0;
  const cacheKey = canCache ? buildRequestCacheKey(url, method, headers) : "";
  const now = Date.now();
  if (policy.ttlMs > 0 && cacheKey) {
    const cached = app.requestCache.responses.get(cacheKey);
    if (cached && cached.expiresAt > now) {
      return cloneCachedJson(cached.value);
    }
    if (cached && cached.expiresAt <= now) {
      app.requestCache.responses.delete(cacheKey);
    }
  }
  if (policy.dedupe && cacheKey) {
    const inflight = app.requestCache.inflight.get(cacheKey);
    if (inflight) return inflight.then((value) => cloneCachedJson(value));
  }
  const promise = (async () => {
    const res = await fetch(url, init);
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status} ${text.slice(0, 200)}`);
    }
    const value = await res.json();
    if (policy.ttlMs > 0 && cacheKey) {
      app.requestCache.responses.set(cacheKey, {
        value: cloneCachedJson(value),
        expiresAt: Date.now() + policy.ttlMs,
      });
      pruneJsonResponseCache();
    }
    return value;
  })();
  if (policy.dedupe && cacheKey) {
    app.requestCache.inflight.set(cacheKey, promise);
  }
  try {
    return await promise;
  } finally {
    if (policy.dedupe && cacheKey) {
      app.requestCache.inflight.delete(cacheKey);
    }
  }
}

async function hostServiceJson(path, options = {}) {
  await ensureAuxServiceUrlsResolved();
  const url = `${hostServiceUrl()}${path}`;
  const method = options.method || "GET";
  const baseHeaders = buildHeaders();
  const headers = options.headers ? { ...baseHeaders, ...options.headers } : baseHeaders;
  const init = { method, headers };
  if (options.body) {
    init.body = JSON.stringify(options.body);
    init.headers = { ...headers, "Content-Type": "application/json" };
  }
  return fetchJsonWithCache(url, init, options);
}

async function clientServiceJson(path, options = {}) {
  await ensureAuxServiceUrlsResolved();
  const url = `${clientServiceUrl()}${path}`;
  const method = options.method || "GET";
  const headers = options.headers || {};
  const init = { method, headers };
  if (options.body) {
    init.body = JSON.stringify(options.body);
    init.headers = { ...headers, "Content-Type": "application/json" };
  }
  return fetchJsonWithCache(url, init, options);
}

async function streamSSE(path, { method = "GET", headers = {}, body, signal, onEvent } = {}) {
  const url = `${normalizeServerUrl(app.state.remote.serverUrl)}${path}`;
  const res = await fetch(url, {
    method,
    headers,
    body,
    signal,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${text.slice(0, 200)}`);
  }
  if (!res.body) return;
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    buffer = buffer.replace(/\r\n/g, "\n");
    let idx;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      parseSSE(chunk, onEvent);
    }
  }
}

function parseSSE(chunk, onEvent) {
  const lines = chunk.split("\n");
  let event = "message";
  const dataLines = [];
  for (const line of lines) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }
  const dataText = dataLines.join("\n");
  if (!dataText) return;
  let payload = dataText;
  try {
    payload = JSON.parse(dataText);
  } catch {
    payload = dataText;
  }
  if (onEvent) onEvent(event, payload);
}

function appendLog(msg, level) {
  const line = document.createElement("div");
  const ts = new Date().toLocaleTimeString();
  line.textContent = `[${ts}] ${msg}`;
  if (level === "error") line.style.color = "#b42318";
  if (level === "warn") line.style.color = "#a16207";
  app.dom.logOutput.appendChild(line);
  app.dom.logOutput.scrollTop = app.dom.logOutput.scrollHeight;
}

function safeJson(data) {
  if (data === null || data === undefined) return "";
  if (typeof data === "string") return data;
  try {
    return JSON.stringify(data);
  } catch {
    return String(data);
  }
}

function clearLog() {
  app.dom.logOutput.innerHTML = "";
}

function scrollToBottom() {
  const el = app.dom.transcript;
  if (!el) return;
  const doScroll = () => {
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  };
  doScroll();
  if (scrollToBottomRaf) cancelAnimationFrame(scrollToBottomRaf);
  scrollToBottomRaf = requestAnimationFrame(() => {
    doScroll();
    scrollToBottomRaf = null;
  });
  if (scrollToBottomTimer) clearTimeout(scrollToBottomTimer);
  scrollToBottomTimer = setTimeout(() => {
    doScroll();
    scrollToBottomTimer = null;
  }, 60);
  app.state.ui.autoScrollLock = true;
}

function shouldAutoScroll() {
  if (app.state.ui.autoScrollLock === true) return true;
  return isNearBottom();
}

function isNearBottom() {
  const el = app.dom.transcript;
  if (!el) return false;
  const threshold = 96;
  return el.scrollHeight - el.scrollTop - el.clientHeight <= threshold;
}

function normalizeServerUrl(url) {
  if (!url) return "";
  const legacyHostMap = {
    "account.saikick.org": "account.gotchat.ai",
    "embed.saikick.org": "embed.gotchat.ai",
    "embed2.saikick.org": "embed2.gotchat.ai",
    "hostservices.saikick.org": "hostservices.gotchat.ai",
    "jshostservices.saikick.org": "jshostservices.gotchat.ai",
    "pluginserver.saikick.org": "pluginserver.gotchat.ai",
    "llmserver.saikick.org": "llmserver.gotchat.ai",
  };
  const text = String(url || "").replace(/\/+$/, "");
  try {
    const parsed = new URL(text);
    const mappedHost = legacyHostMap[String(parsed.hostname || "").toLowerCase()];
    if (mappedHost) {
      parsed.hostname = mappedHost;
    }
    if (parsed.hostname.toLowerCase() === "localhost" && parsed.port === "8000") {
      parsed.hostname = "127.0.0.1";
      return parsed.toString().replace(/\/+$/, "");
    }
    return parsed.toString().replace(/\/+$/, "");
  } catch (_err) {}
  return text;
}

function isLocalHostName(hostname) {
  return ["localhost", "127.0.0.1", "::1"].includes(String(hostname || "").toLowerCase());
}

function getChatJsUiOrigin() {
  const embedCfg = window.__CHAT_JS_EMBED_CONFIG || {};
  const raw = normalizeServerUrl(embedCfg.uiOrigin || embedCfg.chatJsOrigin || "");
  if (raw) return raw;
  const origin = window.location.origin;
  if (origin && origin !== "null" && !origin.startsWith("file:")) {
    return normalizeServerUrl(origin);
  }
  return "";
}

function deriveLocalServerUrlFromUiOrigin() {
  const uiOrigin = getChatJsUiOrigin();
  if (!uiOrigin) return "";
  try {
    const url = new URL(uiOrigin);
    if (!isLocalHostName(url.hostname)) return "";
    const port = String(url.port || "");
    const nextPort = port === "8080" ? "8000" : (port && port !== "80" && port !== "443" ? port : "8000");
    return normalizeServerUrl(`${url.protocol}//${url.hostname}${nextPort ? `:${nextPort}` : ""}`);
  } catch (_err) {
    return "";
  }
}

async function discoverRemoteServerUrl() {
  if (app.serverUrlResolvePromise) {
    return app.serverUrlResolvePromise;
  }
  app.serverUrlResolvePromise = (async () => {
    const trimSlash = (v) => String(v || "").trim().replace(/\/+$/, "");
    const lower = (v) => String(v || "").trim().toLowerCase();
    const asNum = (v) => {
      const n = Number(v);
      return Number.isFinite(n) ? n : 0;
    };
    const normalizeBase = (v) => normalizeServerUrl(trimSlash(v));
    const pickBest = (items, prefer = "") => {
      const list = Array.isArray(items) ? items.filter(Boolean) : [];
      if (!list.length) return null;
      const pref = lower(prefer);
      const sorted = list.slice().sort((a, b) => {
        const at = Date.parse(String(a?.updatedAt || a?.updated_at || "")) || 0;
        const bt = Date.parse(String(b?.updatedAt || b?.updated_at || "")) || 0;
        return bt - at;
      });
      if (pref) {
        const hit = sorted.find((m) => lower(m?.hostname).includes(pref));
        if (hit) return hit;
      }
      return sorted[0] || null;
    };
    const current = normalizeServerUrl(app.state.remote.serverUrl || "");
    const uiOrigin = getChatJsUiOrigin();
    if (current && current !== DEFAULT_STATE.remote.serverUrl && current !== uiOrigin) {
      app.state.remote.discoveredServerUrl = current;
      app.state.remote.publicServerUrl = current;
      try {
        window.dispatchEvent(new CustomEvent("chatjs:server-url-options-changed", {
          detail: { preferredUrl: current },
        }));
      } catch (_err) {}
      return current;
    }
    const mappingPublicUrl = (m) => {
      const raw = trimSlash(m?.public_url || m?.publicUrl || "");
      if (raw) return normalizeBase(raw);
      const host = trimSlash(m?.hostname || "").replace(/^https?:\/\//, "");
      return host ? normalizeBase(`https://${host}`) : "";
    };
    const findPublicServerFromMappings = (mappings, serverPort = 8000) => {
      const items = Array.isArray(mappings) ? mappings : [];
      const candidates = items.filter((m) => {
        const lp = asNum(m?.local_port ?? m?.localPort);
        const host = lower(m?.local_host ?? m?.localHost);
        const service = lower(m?.service);
        if (lp === Number(serverPort || 8000)) return true;
        if (service.includes("llmloader2") && service.includes(`:${Number(serverPort || 8000)}`)) return true;
        if (host.includes("llmloader2") && lp === Number(serverPort || 8000)) return true;
        return false;
      });
      const sorted = candidates.slice().sort((a, b) => {
        const at = Date.parse(String(a?.updated_at || a?.updatedAt || "")) || 0;
        const bt = Date.parse(String(b?.updated_at || b?.updatedAt || "")) || 0;
        return bt - at;
      });
      return mappingPublicUrl(sorted[0]);
    };

    let publicServer = "";
    try {
      const resp = await fetch("/v1/cloudflare_docker_https/status", { credentials: "same-origin", cache: "no-cache" });
      if (resp.ok) {
        const payload = (await resp.json()) || {};
        publicServer =
          normalizeBase(payload?._public_urls?.server) ||
          findPublicServerFromMappings(payload?.mappings, payload?.server_port || 8000);
      }
    } catch (_err) {}

    if (!publicServer) {
      try {
        const embedCfg = window.__CHAT_JS_EMBED_CONFIG || {};
        const qs = new URLSearchParams(window.location.search || "");
        const identifierKey = String(
          embedCfg.identifierKey ||
          embedCfg.identifier_key ||
          qs.get("identifier_key") ||
          qs.get("identifierKey") ||
          ""
        ).trim();
        const cmsBase = String(
          embedCfg.cmsBase ||
          embedCfg.cms_base ||
          qs.get("cms_base") ||
          qs.get("cmsBase") ||
          "https://account.gotchat.ai"
        ).trim().replace(/\/+$/, "");
        if (identifierKey && cmsBase) {
          const lowerHost = (v) => String(v || "").trim().toLowerCase();
          const looksLikeService = (svc, host, port) => {
            const s = lowerHost(svc);
            if (!s) return false;
            if (host && s.includes(`${String(host).toLowerCase()}:${String(port || "")}`)) return true;
            return false;
          };
          const hmUrl = `${cmsBase}/api/docker/host-mappings?key=${encodeURIComponent(identifierKey)}`;
          const hmResp = await fetch(hmUrl, { credentials: "omit", mode: "cors", cache: "no-cache" });
          if (hmResp.ok) {
            const hmPayload = (await hmResp.json()) || {};
            const items = Array.isArray(hmPayload.data || hmPayload.Data) ? (hmPayload.data || hmPayload.Data) : [];
            const serverAll = items.filter((m) => lowerHost(m.serviceType) === "server");
            const serverCandidates = serverAll.filter((m) => {
              const lp = asNum(m.localPort);
              if (lowerHost(m.hostname).includes("hostservice")) return false;
              if (lp === 8000) return true;
              if (looksLikeService(m.service, "llmloader2", 8000)) return true;
              return false;
            });
            const server8000 = serverCandidates.filter((m) => asNum(m.localPort) === 8000 || looksLikeService(m.service, "llmloader2", 8000));
            const bestServer =
              pickBest(server8000, "chatserver") ||
              pickBest(serverCandidates, "chatserver") ||
              pickBest(serverAll.filter((m) => lowerHost(m.hostname).includes("chatserver")), "chatserver") ||
              pickBest(serverAll.filter((m) => lowerHost(m.hostname).includes("chat") && !lowerHost(m.hostname).includes("hostservice")), "chat") ||
              pickBest(serverAll.filter((m) => !lowerHost(m.hostname).includes("hostservice")), "") ||
              pickBest(serverAll, "");
            publicServer = bestServer ? normalizeBase(bestServer.publicUrl || `https://${String(bestServer.hostname || "").trim()}`) : "";
          }
          if (!publicServer) {
            const puUrl = `${cmsBase}/api/docker/public-urls?key=${encodeURIComponent(identifierKey)}`;
            const puResp = await fetch(puUrl, { credentials: "omit", mode: "cors", cache: "no-cache" });
            if (puResp.ok) {
              const puPayload = (await puResp.json()) || {};
              const data = puPayload.data || puPayload.Data || {};
              publicServer = normalizeBase(data.chatServerUrl || data.ChatServerUrl || data.serverUrl || data.ServerUrl || "");
            }
          }
        }
      } catch (_err) {}
    }

    if (publicServer) {
      app.state.remote.discoveredServerUrl = publicServer;
      app.state.remote.publicServerUrl = publicServer;
      const localUrl = deriveLocalServerUrlFromUiOrigin();
      const shouldPreferRemote = !localUrl && (!current || current === uiOrigin || current === DEFAULT_STATE.remote.serverUrl);
      if (shouldPreferRemote) {
        app.state.remote.serverUrl = publicServer;
      }
      try {
        window.dispatchEvent(new CustomEvent("chatjs:server-url-options-changed", {
          detail: { preferredUrl: app.state.remote.serverUrl || publicServer },
        }));
      } catch (_err) {}
      scheduleSave();
    }

    return publicServer;
  })();
  try {
    return await app.serverUrlResolvePromise;
  } finally {
    app.serverUrlResolvePromise = null;
  }
}

function collectServerUrlOptions() {
  const options = [];
  const seen = new Set();
  const push = (value, label) => {
    const normalized = normalizeServerUrl(value || "");
    if (!normalized || seen.has(normalized)) return;
    seen.add(normalized);
    options.push({ value: normalized, label: label || normalized });
  };

  const localUrl = deriveLocalServerUrlFromUiOrigin();
  if (localUrl) push(localUrl, `Localhost (${localUrl})`);

  const publicUrl = normalizeServerUrl(
    app.state?.remote?.discoveredServerUrl ||
    app.state?.remote?.publicServerUrl ||
    ""
  );
  if (publicUrl) push(publicUrl, `Remote mapped (${publicUrl})`);

  const current = normalizeServerUrl(app.state?.remote?.serverUrl || "");
  const uiOrigin = getChatJsUiOrigin();
  if (current) {
    const label = current === localUrl
      ? `Localhost (${current})`
      : current === publicUrl
        ? `Remote mapped (${current})`
        : current === uiOrigin
          ? ""
          : `Current (${current})`;
    if (label) push(current, label);
  }

  if (!options.length) {
    push(DEFAULT_STATE.remote.serverUrl, `Default (${DEFAULT_STATE.remote.serverUrl})`);
  }
  return options;
}

function renderServerUrlOptions(preferredValue = "") {
  if (!app.dom.serverUrl) return;
  let current = normalizeServerUrl(preferredValue || app.state.remote.serverUrl || "");
  const options = collectServerUrlOptions();
  const uiOrigin = getChatJsUiOrigin();
  const localUrl = deriveLocalServerUrlFromUiOrigin();
  const publicUrl = normalizeServerUrl(
    app.state?.remote?.discoveredServerUrl ||
    app.state?.remote?.publicServerUrl ||
    ""
  );
  if (localUrl && (!current || current === uiOrigin)) {
    current = localUrl;
    app.state.remote.serverUrl = localUrl;
  } else if (publicUrl && (!current || current === uiOrigin)) {
    current = publicUrl;
    app.state.remote.serverUrl = publicUrl;
  }
  app.dom.serverUrl.innerHTML = "";
  for (const option of options) {
    const el = document.createElement("option");
    el.value = option.value;
    el.textContent = option.label;
    app.dom.serverUrl.appendChild(el);
  }
  const fallback = options[0]?.value || "";
  app.dom.serverUrl.value = options.some((opt) => opt.value === current) ? current : fallback;
}

function syncServerUrlSelection(nextValue, { save = true } = {}) {
  const normalized = normalizeServerUrl(nextValue || "");
  app.state.remote.serverUrl = normalized;
  renderServerUrlOptions(normalized);
  if (save) scheduleSave();
  renderStatus();
  app.plugins.autoLoadAttempts = 0;
  void ensurePluginsLoaded({ force: true });
  schedulePluginAutoload();
}

function shouldShowRuntimeSection() {
  return false;
}

function updateRuntimeSectionVisibility() {
  if (!app.dom.runtimeSection) return;
  const visible = shouldShowRuntimeSection();
  app.dom.runtimeSection.classList.toggle("hidden", !visible);
  if (!visible && app.dom.runtimeStatusNote) {
    app.dom.runtimeStatusNote.textContent = "Runtime control is available only when connected to localhost:8000.";
  }
}

function hasRemoteAuth() {
  return Boolean(app.state.remote.enabled && isAuthEnabled() && app.state.auth.token);
}

function hasGuestSessionAccess() {
  const access = getActiveSessionAccess();
  return Boolean(app.state.remote.enabled && isAuthEnabled() && !app.state.auth.token && access?.can_access && access?.allow_guest);
}

function canUseRemoteServer() {
  return Boolean(app.state.remote.enabled && isAuthEnabled() && normalizeServerUrl(app.state.remote.serverUrl));
}

function ensureGuestId() {
  if (!app.state.auth.guestId) {
    app.state.auth.guestId = randomId("guest");
  }
  return app.state.auth.guestId;
}

function getPreferredAlias() {
  return String(app.state.auth.alias || app.state.auth.username || "").trim();
}

function getDisplayAuthorLabel() {
  const alias = getPreferredAlias();
  if (!alias) return "";
  return app.state.auth.token ? alias : `${alias} (guest)`;
}

function getGuestAliasValue() {
  return String(app.state.auth.alias || "").trim();
}

function getCurrentActorUsername() {
  if (app.state.auth.token) return String(app.state.auth.username || "").trim();
  const guestId = String(app.state.auth.guestId || "").trim();
  return guestId ? `guest:${guestId}` : "";
}

function normalizeChatInfo(info) {
  const data = info && typeof info === "object" ? info : {};
  return {
    title: String(data.title || "GotChat Foundry").trim() || "GotChat Foundry",
    subtitle: String(data.subtitle || "Your AI Chat").trim() || "Your AI Chat",
    logo_data_url: String(data.logo_data_url || "").trim(),
  };
}

function getChatInfoState() {
  if (!app.state.ui || typeof app.state.ui !== "object") app.state.ui = {};
  app.state.ui.chatInfo = normalizeChatInfo(app.state.ui.chatInfo);
  return app.state.ui.chatInfo;
}

function renderBranding() {
  const info = getChatInfoState();
  if (app.dom.brandTitle) app.dom.brandTitle.textContent = info.title;
  if (app.dom.brandSub) app.dom.brandSub.textContent = info.subtitle;
  if (app.dom.brandLogo) {
    const hasLogo = Boolean(info.logo_data_url);
    app.dom.brandLogo.src = hasLogo ? info.logo_data_url : "";
    app.dom.brandLogo.classList.toggle("hidden", !hasLogo);
    if (app.dom.brandTitle) app.dom.brandTitle.classList.toggle("hidden", hasLogo);
    if (app.dom.brandSub) app.dom.brandSub.classList.toggle("hidden", hasLogo);
  }
  if (!window.__CHAT_JS_EMBED_CONFIG?.embedded) {
    document.title = info.title || "GotChat Foundry";
  }
}

function syncChatInfoPreview(logoDataUrl) {
  const logo = String(logoDataUrl || "").trim();
  if (!app.dom.chatInfoLogoPreview || !app.dom.chatInfoLogoPreviewWrap) return;
  const hasLogo = Boolean(logo);
  app.dom.chatInfoLogoPreview.src = hasLogo ? logo : "";
  app.dom.chatInfoLogoPreviewWrap.classList.toggle("hidden", !hasLogo);
}

function applyChatInfoToInputs() {
  const info = getChatInfoState();
  if (app.dom.chatInfoTitle) app.dom.chatInfoTitle.value = info.title;
  if (app.dom.chatInfoSubtitle) app.dom.chatInfoSubtitle.value = info.subtitle;
  if (app.dom.chatInfoLogoFile) app.dom.chatInfoLogoFile.value = "";
  syncChatInfoPreview(info.logo_data_url);
  const admin = isAdminUser();
  if (app.dom.chatInfoTitle) app.dom.chatInfoTitle.disabled = !admin;
  if (app.dom.chatInfoSubtitle) app.dom.chatInfoSubtitle.disabled = !admin;
  if (app.dom.chatInfoLogoFile) app.dom.chatInfoLogoFile.disabled = !admin;
  if (app.dom.chatInfoClearLogo) app.dom.chatInfoClearLogo.disabled = !admin;
  if (app.dom.chatInfoSave) app.dom.chatInfoSave.disabled = !admin;
  if (app.dom.chatInfoNote) {
    app.dom.chatInfoNote.textContent = admin
      ? i18nTranslate("chat_js.config.admin_saves_branding_note", "Admin saves shared chat branding for all users.")
      : i18nTranslate("chat_js.config.admin_branding_note", "Only admin can save shared chat branding.");
  }
}

function setRuntimeGpuOptions(options, selected) {
  if (!app.dom.runtimeGpuDevice) return;
  const items = Array.isArray(options) && options.length
    ? options
    : [{ value: "all", label: "All GPUs" }];
  const seen = new Set();
  app.dom.runtimeGpuDevice.innerHTML = "";
  items.forEach((item) => {
    const value = String(item?.value || "").trim();
    if (!value || seen.has(value)) return;
    seen.add(value);
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = String(item?.label || value);
    app.dom.runtimeGpuDevice.appendChild(opt);
  });
  const selectedValue = String(selected || "").trim();
  if (selectedValue && !seen.has(selectedValue)) {
    const extra = document.createElement("option");
    extra.value = selectedValue;
    extra.textContent = selectedValue === "all" ? "All GPUs" : selectedValue;
    app.dom.runtimeGpuDevice.appendChild(extra);
  }
  app.dom.runtimeGpuDevice.value = selectedValue || "all";
}

function applyRuntimeControlState() {
  const runtimeVisible = shouldShowRuntimeSection();
  if (app.dom.runtimeSection) {
    app.dom.runtimeSection.classList.toggle("hidden", !runtimeVisible);
  }
  if (!runtimeVisible) return;
  const status = app.runtimeControl.status || {};
  const mode = String(app.dom.runtimeMode?.value || status.current_runtime || status.configured_runtime || "cpu").trim().toLowerCase();
  const admin = isAdminUser();
  const loading = Boolean(app.runtimeControl.loading);
  if (app.dom.runtimeMode && !app.dom.runtimeMode.value) {
    app.dom.runtimeMode.value = mode;
  }
  const gpuEnabled = mode === "nvidia";
  if (app.dom.runtimeGpuDevice) {
    app.dom.runtimeGpuDevice.disabled = !gpuEnabled || loading;
  }
  if (app.dom.runtimeMode) {
    app.dom.runtimeMode.disabled = loading;
  }
  if (app.dom.runtimeRefresh) {
    app.dom.runtimeRefresh.disabled = loading;
  }
  if (app.dom.runtimeApply) {
    app.dom.runtimeApply.disabled = loading || !admin;
  }
  if (app.dom.runtimeStatusNote) {
    const currentRuntime = String(status.current_runtime || mode || "cpu").toUpperCase();
    const currentGpu = String(status.current_gpu_devices || status.configured_gpu_devices || "all");
    let text = loading
      ? "Loading runtime status..."
      : `Current runtime: ${currentRuntime}${currentRuntime === "NVIDIA" ? ` | GPU devices: ${currentGpu}` : ""}`;
    if (!admin) {
      text += " | Admin only can apply changes.";
    }
    app.dom.runtimeStatusNote.textContent = text;
  }
}

async function refreshRuntimeControlStatus(force = false) {
  if (!shouldShowRuntimeSection()) {
    app.runtimeControl.loading = false;
    if (app.dom.runtimeStatusNote) {
      app.dom.runtimeStatusNote.textContent = "Runtime control is available only when connected to localhost:8000.";
    }
    applyRuntimeControlState();
    return null;
  }
  if (app.runtimeControl.loading && !force) return app.runtimeControl.status;
  app.runtimeControl.loading = true;
  applyRuntimeControlState();
  try {
    const data = await clientServiceJson("/v1/client/runtime_control/status");
    if (!data?.ok) throw new Error(data?.error || "runtime status failed");
    app.runtimeControl.status = data;
    if (app.dom.runtimeMode) {
      app.dom.runtimeMode.value = String(data.current_runtime || data.configured_runtime || "cpu").trim().toLowerCase();
    }
    setRuntimeGpuOptions(data.gpu_device_options || [], data.current_gpu_devices || data.configured_gpu_devices || "all");
    return data;
  } catch (err) {
    app.runtimeControl.status = null;
    if (app.dom.runtimeStatusNote) {
      app.dom.runtimeStatusNote.textContent = `Runtime status unavailable: ${err.message || err}`;
    }
    appendLog(`[runtime] ${err.message || err}`, "warn");
    return null;
  } finally {
    app.runtimeControl.loading = false;
    applyRuntimeControlState();
  }
}

async function applyRuntimeControl() {
  if (!shouldShowRuntimeSection()) {
    appendLog("[runtime] runtime control is available only on localhost:8000", "warn");
    applyRuntimeControlState();
    return;
  }
  if (!hasPermission("plugins.manage.install", false)) {
    appendLog("[runtime] admin only", "warn");
    applyRuntimeControlState();
    return;
  }
  const runtime = String(app.dom.runtimeMode?.value || "cpu").trim().toLowerCase();
  const gpuDevices = String(app.dom.runtimeGpuDevice?.value || "all").trim();
  app.runtimeControl.loading = true;
  applyRuntimeControlState();
  try {
    const payload = await clientServiceJson("/v1/client/runtime_control/apply", {
      method: "POST",
      headers: buildHeaders(),
      body: {
        runtime,
        gpu_devices: runtime === "nvidia" ? gpuDevices : "",
      },
    });
    if (!payload?.ok) throw new Error(payload?.error || "runtime apply failed");
    if (app.dom.runtimeStatusNote) {
      app.dom.runtimeStatusNote.textContent = `Restart queued for ${runtime.toUpperCase()}. Waiting for localhost runtime status to update...`;
    }
    appendLog(`[runtime] restart queued for ${runtime}`, "info");

    // Poll until we either see the runtime switch take effect or we learn the
    // apply job failed (manage_runtime writes `last_apply` into status).
    const deadline = Date.now() + 90_000;
    while (Date.now() < deadline) {
      await delay(2000);
      const status = await refreshRuntimeControlStatus(true);
      if (!status?.ok) continue;
      const lastApply = status?.last_apply || null;
      const lastStatus = String(lastApply?.status || "").trim().toLowerCase();
      const lastErr = String(lastApply?.error || "").trim();
      if (lastStatus === "error") {
        if (app.dom.runtimeStatusNote) {
          app.dom.runtimeStatusNote.textContent = `Runtime apply failed: ${lastErr || "unknown error"}`;
        }
        appendLog(`[runtime] apply failed: ${lastErr || "unknown error"}`, "error");
        break;
      }
      const current = String(status.current_runtime || "").trim().toLowerCase();
      if (current && current === runtime) {
        if (app.dom.runtimeStatusNote) {
          app.dom.runtimeStatusNote.textContent = `Runtime is now ${runtime.toUpperCase()}.`;
        }
        appendLog(`[runtime] runtime is now ${runtime}`, "info");
        break;
      }
    }
  } catch (err) {
    appendLog(`[runtime] apply failed: ${err.message || err}`, "error");
  } finally {
    app.runtimeControl.loading = false;
    applyRuntimeControlState();
  }
}

async function refreshChatUiInfo() {
  const base = normalizeServerUrl(app.state.remote.serverUrl);
  if (!base) return false;
  try {
    const data = await apiJson("/v1/chat_ui/info");
    app.state.ui.chatInfo = normalizeChatInfo(data);
    renderBranding();
    applyChatInfoToInputs();
    scheduleSave();
    return true;
  } catch (err) {
    appendLog(`[chat-ui] ${err.message || err}`, "warn");
    return false;
  }
}

async function refreshSharedUiThemeDefault(pluginId = "theme_demo", options = {}) {
  const pid = String(pluginId || "").trim();
  if (!pid) return false;
  const forceApply = Boolean(options && options.forceApply);
  try {
    const data = await apiJson(`/v1/${encodeURIComponent(pid)}/default_theme`, { timeoutMs: 10000 });
    setServerUiThemeDefault(data?.theme_snapshot || null, data?.theme_state || null, { save: true });
    if (forceApply && data?.theme_snapshot && app.state.ui) {
      app.state.ui.useLocalThemeOverride = false;
    }
    if ((forceApply || !app.state.ui.useLocalThemeOverride) && data?.theme_snapshot) {
      applyUiThemeSnapshot(data.theme_snapshot, { save: false });
    }
    return true;
  } catch (err) {
    appendLog(`[theme] shared default unavailable: ${err.message || err}`, "warn");
    return false;
  }
}

function readChatInfoDraft() {
  const current = getChatInfoState();
  return normalizeChatInfo({
    title: app.dom.chatInfoTitle?.value || current.title,
    subtitle: app.dom.chatInfoSubtitle?.value || current.subtitle,
    logo_data_url: app.dom.chatInfoLogoPreview?.getAttribute("src") || current.logo_data_url,
  });
}

async function saveSharedChatUiInfo() {
  if (!hasPermission("plugins.manage.install", false)) {
    appendLog("[chat-ui] admin only", "warn");
    applyChatInfoToInputs();
    return;
  }
  const draft = readChatInfoDraft();
  try {
    const data = await apiJson("/v1/chat_ui/info", {
      method: "POST",
      body: draft,
    });
    app.state.ui.chatInfo = normalizeChatInfo(data);
    renderBranding();
    applyChatInfoToInputs();
    scheduleSave();
    appendLog("[chat-ui] branding saved", "info");
  } catch (err) {
    appendLog(`[chat-ui] save failed: ${err.message || err}`, "error");
  }
}

function normalizeServerMessage(msg) {
  const role = msg.role || "user";
  let author = msg.author_alias || msg.author_username || "";
  if (role === "assistant") {
    author = "assistant";
  }
  return {
    msg_id: msg.msg_id || randomId("msg"),
    role,
    content: msg.content || "",
    author,
    author_username: msg.author_username || "",
    ts: msg.ts || null,
    meta: msg.meta || {},
  };
}

function isOtherUserMessage(msg) {
  if (!msg || (msg.role || "user") !== "user") return false;
  const authorUsername = String(msg.author_username || "").trim();
  const meUsername = getCurrentActorUsername();
  if (authorUsername && meUsername) {
    return authorUsername.toLowerCase() !== meUsername.toLowerCase();
  }
  const author = String(msg.author || "").trim();
  if (!author) return false;
  const me = String(app.state.auth.alias || app.state.auth.username || "").trim();
  if (!me) return false;
  return author.toLowerCase() !== me.toLowerCase();
}

function renderMarkdown(text) {
  if (!text) return "";
  const parts = text.split("```");
  let out = "";
  for (let i = 0; i < parts.length; i += 1) {
    const chunk = parts[i];
    if (i % 2 === 1) {
      const split = chunk.split("\n");
      const lang = split.length > 1 ? split[0].trim() : "";
      const code = split.length > 1 ? split.slice(1).join("\n") : chunk;
      out += `<pre><code data-lang="${escapeHtml(lang)}">${escapeHtml(code)}</code></pre>`;
    } else {
      out += renderInline(chunk).replace(/\n/g, "<br>");
    }
  }
  return out;
}

function renderInline(text) {
  const pieces = text.split("`");
  let out = "";
  for (let i = 0; i < pieces.length; i += 1) {
    if (i % 2 === 1) out += `<code>${escapeHtml(pieces[i])}</code>`;
    else out += escapeHtml(pieces[i]);
  }
  return out;
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function scheduleSave() {
  if (app.saveInFlight) {
    app.saveQueued = true;
  }
  if (app.saveTimer) return;
  app.saveTimer = setTimeout(() => {
    app.saveTimer = null;
    void flushScheduledSave();
  }, 200);
}

function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const base = raw ? JSON.parse(raw) : {};
    if (base?.router && typeof base.router === "object") {
      base.router = normalizeRouterStateSnapshot(base.router);
    }
    const prefs = loadCriticalPrefsSnapshot();
    const routerState = loadRouterStateSnapshot();
    const next = mergeDeep(mergeDeep(base, prefs), routerState);
    if (next?.ui && typeof next.ui === "object") delete next.ui.__transcriptRenderMeta;
    if (next?.ui && typeof next.ui === "object") delete next.ui.__sessionSwitchToken;
    return next;
  } catch {
    return mergeDeep(loadCriticalPrefsSnapshot(), loadRouterStateSnapshot());
  }
}

function mergeDeep(base, extra) {
  if (Array.isArray(base)) return Array.isArray(extra) ? extra.slice() : base.slice();
  if (!extra || typeof extra !== "object") return { ...base };
  const out = { ...base };
  for (const [key, value] of Object.entries(extra)) {
    if (value && typeof value === "object" && !Array.isArray(value) && base[key] && typeof base[key] === "object") {
      out[key] = mergeDeep(base[key], value);
    } else {
      out[key] = value;
    }
  }
  return out;
}

function slugify(text) {
  return String(text || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9\-_:.\s]/g, "")
    .slice(0, 40);
}

function randomId(prefix) {
  const seed = Math.random().toString(36).slice(2, 10);
  return prefix ? `${prefix}-${seed}` : seed;
}

function getComposerTextValue() {
  return app.dom.composerInput?.value ?? "";
}

function keepComposerCaretInView() {
  const input = app.dom.composerInput;
  if (!input) return;
  requestAnimationFrame(() => {
    if (document.activeElement !== input) return;
    input.scrollTop = input.scrollHeight;
  });
}

function setComposerTextValue(text) {
  if (!app.dom.composerInput) return;
  app.dom.composerInput.value = String(text ?? "");
  app.dom.composerInput.dispatchEvent(new Event("input", { bubbles: true }));
  keepComposerCaretInView();
}

function clearComposerTextValue() {
  setComposerTextValue("");
}

function deleteLastWordFromComposer() {
  const text = getComposerTextValue();
  const trimmed = text.replace(/\s+$/, "");
  const next = trimmed.replace(/\s+\S+$/, "").trimEnd();
  setComposerTextValue(next);
}

function deleteLastLineFromComposer() {
  const text = getComposerTextValue();
  const lines = String(text).split("\n");
  lines.pop();
  const next = lines.join("\n").trimEnd();
  setComposerTextValue(next);
}

function sendComposerMessage() {
  sendMessage();
}

  function coerceBool(value, fallback = true) {
    if (value === undefined || value === null) return fallback;
    if (typeof value === "string") {
      const t = value.trim().toLowerCase();
      if (t === "0" || t === "false" || t === "no" || t === "off") return false;
      if (t === "1" || t === "true" || t === "yes" || t === "on") return true;
    }
    return Boolean(value);
  }

  function getAiEnabledFromState(pid, sid, fallback = true) {
    try {
      const p = String(pid || "").trim();
      const s = String(sid || "").trim();
      const key = p && s ? `${p}:${s}` : "";
      const map = app.state?.ai?.enabledByScope;
      if (key && map && typeof map === "object" && Object.prototype.hasOwnProperty.call(map, key)) {
        return Boolean(map[key]);
      }
    } catch (_err) {}

    // Back-compat: Auth/Projects stores a client-side per-session toggle here.
    try {
      const p = String(pid || "").trim();
      const s = String(sid || "").trim();
      const key = p && s ? `${p}:${s}` : "";
      const map = app.state?.auth_projects?.collab?.aiToggleBySession;
      if (key && map && typeof map === "object" && Object.prototype.hasOwnProperty.call(map, key)) {
        return Boolean(map[key]);
      }
    } catch (_err) {}

    try {
      const sess = app.state?.sessions?.[sid];
      if (sess && sess.ai_default !== undefined && sess.ai_default !== null) return coerceBool(sess.ai_default, fallback);
    } catch (_err) {}
    try {
      const proj = app.state?.projects?.[pid];
      if (proj && proj.ai_default !== undefined && proj.ai_default !== null) return coerceBool(proj.ai_default, fallback);
    } catch (_err) {}
    return fallback;
  }

  function setAiEnabledInState(pid, sid, enabled) {
    try {
      const p = String(pid || "").trim();
      const s = String(sid || "").trim();
      if (!p || !s) return false;
      const key = `${p}:${s}`;
      app.state.ai = app.state.ai || {};
      app.state.ai.enabledByScope = app.state.ai.enabledByScope || {};
      app.state.ai.enabledByScope[key] = Boolean(enabled);
      scheduleSave();
      return true;
    } catch (_err) {
      return false;
    }
  }

  function getPluginContext() {
    const pid = app.plugins.currentRegistering || "";
    return {
      state: app.state,
      log: appendLog,
      apiJson,
      streamSSE,
      renderMarkdown,
      refreshTranscript: renderTranscript,
      refreshMessages: loadSessionMessages,
      loadProjectRouterPrefs,
      getRouterConfig,
      setRouterSettings,
      setRouterEnabled,
      saveState: scheduleSave,
      sendMessage: sendComposerMessage,
      getEmbedMount: () => getEmbedMount(),
      getOverlayMount: () => getOverlayMount(),
      getComposerText: getComposerTextValue,
      setComposerText: setComposerTextValue,
      clearComposerText: clearComposerTextValue,
      deleteLastWord: deleteLastWordFromComposer,
      deleteLastLine: deleteLastLineFromComposer,
      appendMessage: (msg, sidOverride) => {
        const sid = sidOverride || msg?.sid || app.state.ui.activeSid;
        if (!sid || !msg) return;
        upsertMessage(sid, msg);
      },
      updateMessage: (sid, msgId, content, force) => updateStreamMessageContent(sid, msgId, content, force),
      appendToken: (sid, msgId, text) => appendToken(sid, msgId, text),
      markMessageDone: (sid, msgId) => markStreamDone(sid, msgId),
      startCompletionStream: (pid, sid, prompt, clientMsgId) => startCompletionStream(pid, sid, prompt, clientMsgId),
      startModelStream: (pid, sid, prompt, clientMsgId) => startModelStream(pid, sid, prompt, clientMsgId),
      getAiEnabled: (pid, sid, fallback) => getAiEnabledFromState(pid, sid, fallback),
      setAiEnabled: (pid, sid, enabled) => setAiEnabledInState(pid, sid, enabled),
      randomId: (prefix) => randomId(prefix || "id"),
      buildCompletionPayload: (sid) => buildCompletionPayload(sid),
      renderMessageWithPlugins: (msg, options) => renderMessageWithPlugins(msg, options),
      getSharedObjects: (filter) => getSharedObjects(filter),
      registerI18nBundle: (bundle) => registerI18nBundle(bundle),
      installI18nDictionary: (locale, dict, options) => installI18nDictionary(locale, dict, options),
      getI18nBundles: () => ensureI18nState().bundles.slice(),
      t: (key, fallback) => i18nTranslate(key, fallback),
      hasPermission: (key, fallback) => hasPermission(key, fallback),
      canAccessPlugin: (pluginId, action) => canAccessPlugin(pluginId, action),
      refreshPermissions: (options) => refreshPermissionState(options),
      refreshGuiPluginsDiscovery: () => refreshGuiPluginsDiscovery(),
      translateContainer: (root, pluginId) => translateContainer(root, pluginId),
      setLanguage: (locale) => setLanguage(locale),
      getLanguage: () => getLanguage(),
      onLanguageChange: (callback) => onLanguageChange(callback),
      openPluginPanel: (pluginId, options) => openPluginPanel(pluginId, options),
      openPluginPanelWhenReady: (pluginId, options) => openPluginPanelWhenReady(pluginId, options),
      openPluginFullView: (pluginId, options) => openPluginFullView(pluginId, options),
      closePluginFullView: () => closePluginFullView(),
      closeTools: () => closeTools(),
      getSavedUiTheme: () => normalizeUiThemeSnapshot(app.state?.ui?.savedTheme),
      getSharedUiThemeDefault: () => ({
        themeSnapshot: normalizeUiThemeSnapshot(app.state?.ui?.serverTheme),
        themeState: normalizeUiThemeStateValue(app.state?.ui?.serverThemeState),
      }),
      getUiThemeDefaults: (target) => getUiThemeDefaultsForTarget(target || getEmbedMount() || document.documentElement),
      applyUiTheme: (snapshot, options) => {
        const normalized = normalizeUiThemeSnapshot(snapshot, pid);
        return normalized ? applyUiThemeSnapshot(normalized, options) : false;
      },
      saveUiTheme: (snapshot) => {
        const normalized = normalizeUiThemeSnapshot(snapshot, pid);
        return normalized ? applyUiThemeSnapshot(normalized, { save: true }) : false;
      },
      saveSharedUiThemeDefault: async (payload) => {
        const themeSnapshot = normalizeUiThemeSnapshot(payload?.themeSnapshot, pid);
        const themeState = normalizeUiThemeStateValue(payload?.themeState);
        const routePid = String(payload?.pluginId || themeSnapshot?.pluginId || pid || "").trim();
        if (!routePid) throw new Error("plugin id required for shared UI theme save");
        const data = await apiJson(`/v1/${encodeURIComponent(routePid)}/default_theme`, {
          method: "POST",
          body: { theme_snapshot: themeSnapshot, theme_state: themeState },
          timeoutMs: 6000,
        });
        const savedSnapshot = data?.theme_snapshot || themeSnapshot;
        setServerUiThemeDefault(savedSnapshot, data?.theme_state || themeState, { save: true });
        if (savedSnapshot) {
          app.state.ui.useLocalThemeOverride = false;
          applyUiThemeSnapshot(savedSnapshot, { save: false });
        }
        return data;
      },
      clearUiTheme: (options) => clearUiThemeSnapshot(options),
  };
}

function getPluginIdFromEntry(entry) {
  if (!entry) return "";
  const direct = String(entry.id || "").trim();
  if (direct) return direct;
  const path = String(entry.path || "").trim();
  if (!path) return "";
  const match = path.match(/\/plugins\/([^/]+)\//);
  if (match && match[1]) return match[1];
  return path.split("/").pop().replace(/\.(mjs|js)$/i, "");
}

function isPluginEnabled(pluginId) {
  const key = String(pluginId || "");
  if (!key) return true;
  const prefs = app.state.pluginPrefs || {};
  const enabled = prefs.enabled || {};
  return enabled[key] !== false;
}

function ensurePluginPrefs() {
  if (!app.state.pluginPrefs) app.state.pluginPrefs = { enabled: {} };
  if (!app.state.pluginPrefs.enabled) app.state.pluginPrefs.enabled = {};
  if (!Array.isArray(app.state.pluginPrefs.priority)) app.state.pluginPrefs.priority = [];
  if (!app.state.pluginPrefs.preloads || typeof app.state.pluginPrefs.preloads !== "object") {
    app.state.pluginPrefs.preloads = {};
  }
  const preloads = app.state.pluginPrefs.preloads;
  if (!Array.isArray(preloads.json_sniffer)) preloads.json_sniffer = [];
  return app.state.pluginPrefs;
}

function requestPluginPriority(pluginId, { position = "first" } = {}) {
  const key = String(pluginId || "").trim();
  if (!key) return false;
  const prefs = ensurePluginPrefs();
  const list = prefs.priority;
  const next = list.filter((id) => String(id || "").trim() && String(id) !== key);
  const pos = String(position || "first").toLowerCase();
  if (pos === "last") next.push(key);
  else next.unshift(key);
  prefs.priority = next.slice(0, 50);
  scheduleSave();
  return true;
}

function requestPluginPreload(pluginId, kind) {
  const key = String(pluginId || "").trim();
  if (!key) return false;
  const preloadKind = String(kind || "").trim().toLowerCase();
  if (!preloadKind) return false;
  const prefs = ensurePluginPrefs();
  const preloads = prefs.preloads || {};
  if (!Array.isArray(preloads[preloadKind])) preloads[preloadKind] = [];
  const list = preloads[preloadKind].filter((id) => String(id || "").trim() && String(id) !== key);
  list.unshift(key);
  preloads[preloadKind] = list.slice(0, 50);
  prefs.preloads = preloads;
  scheduleSave();
  return true;
}

function pluginDiscoveryCacheKey(base) {
  return String(base || "").replace(/\/+$/, "") || "local";
}

function loadPluginDiscoveryCache(base) {
  try {
    const raw = window.localStorage.getItem(PLUGIN_DISCOVERY_CACHE_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    const bucket = parsed?.[pluginDiscoveryCacheKey(base)];
    if (!bucket || !Array.isArray(bucket.plugins)) return [];
    const age = Date.now() - Number(bucket.savedAt || 0);
    if (age > PLUGIN_DISCOVERY_CACHE_TTL_MS) return [];
    return bucket.plugins.filter((entry) => entry && entry.path);
  } catch (_err) {
    return [];
  }
}

function savePluginDiscoveryCache(base, plugins) {
  try {
    const cleanPlugins = (plugins || []).filter((entry) => entry && entry.path);
    if (!cleanPlugins.length) return;
    const key = pluginDiscoveryCacheKey(base);
    const raw = window.localStorage.getItem(PLUGIN_DISCOVERY_CACHE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    parsed[key] = {
      savedAt: Date.now(),
      plugins: cleanPlugins,
    };
    window.localStorage.setItem(PLUGIN_DISCOVERY_CACHE_KEY, JSON.stringify(parsed));
  } catch (_err) {}
}

function setPluginEnabled(pluginId, enabled) {
  const key = String(pluginId || "");
  if (!key) return;
  ensurePluginPrefs();
  app.state.pluginPrefs.enabled[key] = Boolean(enabled);
  saveCriticalPrefsSnapshot(app.state);
  scheduleSave();
}

function getPluginRegistry(pluginId) {
  const key = String(pluginId || "");
  if (!key) return null;
  if (!app.plugins.registry[key]) {
    app.plugins.registry[key] = {
      toolbar: [],
      topRightIconRow: [],
      transcriptTopbar: [],
      transcriptBottombar: [],
      composerLeft: [],
        panels: [],
        messageRenderers: [],
        blockTransformers: [],
        blockRenderers: [],
        messageFooterItems: [],
        eventHandlers: [],
        completionPayloadHooks: [],
        rosterActions: [],
      sendHooks: [],
      sendContextMenuItems: [],
      projectCreateHandlers: [],
      sessionCreateHandlers: [],
    };
  }
  return app.plugins.registry[key];
}

function addSharedObject(pluginId, obj) {
  const key = String(pluginId || "");
  if (!key || !obj) return;
  if (!app.plugins.sharedObjects) {
    app.plugins.sharedObjects = { items: [] };
  }
  // If a shared object has a stable id, treat it as an upsert for that plugin.
  // This prevents duplicates when plugins refresh/poll and re-share the same object.
  try {
    const sharedId = String(obj.id || "").trim();
    if (sharedId) {
      app.plugins.sharedObjects.items = (app.plugins.sharedObjects.items || []).filter(
        (item) => !(item && item.pluginId === key && String(item.id || "") === sharedId),
      );
    }
  } catch (_err) {}
  const meta = app.plugins.meta?.[key] || {};
  const entry = {
    ...obj,
    pluginId: key,
    pluginName: meta.name || meta.title || key,
    pluginDescription: meta.description || meta.short_description || "",
  };
  app.plugins.sharedObjects.items.push(entry);
  if (entry.type === "data_provider" && entry.service === "model_context") {
    updateMaxTokensPlaceholder();
  }
  return entry;
}

function getSharedObjects(filter = {}) {
  const list = app.plugins.sharedObjects?.items || [];
  const type = String(filter.type || "").trim().toLowerCase();
  const pluginId = String(filter.pluginId || "").trim();
  return list.filter((item) => {
    if (type && String(item.type || "").trim().toLowerCase() !== type) return false;
    if (pluginId && String(item.pluginId || "") !== pluginId) return false;
    return true;
  });
}

function getComposerActions() {
  const items = getSharedObjects({ type: "composer_action" }) || [];
  return items
    .filter((item) => {
      if (!item || typeof item !== "object") return false;
      if (!app.state.auth.token && pluginNeedsLogin(item.pluginId)) return false;
      if (item.pluginId && !canAccessPlugin(item.pluginId, "view")) return false;
      return typeof item.run === "function";
    })
    .sort((a, b) => Number(a.order || 0) - Number(b.order || 0));
}

function closeUploadActionMenu() {
  const menu = app.dom.uploadActionMenu;
  if (!menu) return;
  menu.style.display = "none";
  menu.innerHTML = "";
  if (app.dom.uploadBtn) app.dom.uploadBtn.setAttribute("aria-expanded", "false");
}

function positionUploadActionMenu() {
  const menu = app.dom.uploadActionMenu;
  const btn = app.dom.uploadBtn;
  if (!menu || !btn || menu.style.display === "none") return;
  const rect = btn.getBoundingClientRect();
  menu.style.left = `${Math.round(rect.left)}px`;
  menu.style.top = `${Math.round(rect.bottom + 8)}px`;
}

function ensureUploadActionMenu() {
  if (app.dom.uploadActionMenu) return app.dom.uploadActionMenu;
  const menu = document.createElement("div");
  menu.className = "action-menu-list upload-action-menu";
  menu.style.position = "fixed";
  menu.style.display = "none";
  menu.addEventListener("click", (event) => event.stopPropagation());
  document.body.appendChild(menu);
  document.addEventListener("click", (event) => {
    if (menu.style.display === "none") return;
    if (event.target === app.dom.uploadBtn || app.dom.uploadBtn?.contains?.(event.target)) return;
    closeUploadActionMenu();
  });
  window.addEventListener("resize", positionUploadActionMenu);
  window.addEventListener("scroll", positionUploadActionMenu, true);
  app.dom.uploadActionMenu = menu;
  return menu;
}

function renderUploadActionMenu() {
  const menu = ensureUploadActionMenu();
  const actions = getComposerActions();
  menu.innerHTML = "";
  if (!actions.length) {
    const empty = document.createElement("div");
    empty.className = "muted";
    empty.textContent = "No actions available";
    menu.appendChild(empty);
    return menu;
  }
  actions.forEach((item) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "action-menu-item";
    const ctx = getPluginContext();
    const title = typeof item.getLabel === "function"
      ? String(item.getLabel(ctx) || item.label || item.name || item.id || "Action")
      : String(item.label || item.name || item.id || "Action");
    btn.textContent = title;
    const desc = typeof item.getDescription === "function"
      ? String(item.getDescription(ctx) || "")
      : String(item.description || "");
    if (desc) btn.title = desc;
    btn.addEventListener("click", async () => {
      try {
        await item.run(getPluginContext(), { closeMenu: closeUploadActionMenu });
      } catch (err) {
        appendLog(`[composer_action] ${err?.message || err}`, "warn");
      }
    });
    menu.appendChild(btn);
  });
  return menu;
}

function toggleUploadActionMenu() {
  const menu = renderUploadActionMenu();
  if (menu.style.display !== "none") {
    closeUploadActionMenu();
    return;
  }
  menu.style.display = "flex";
  positionUploadActionMenu();
  if (app.dom.uploadBtn) app.dom.uploadBtn.setAttribute("aria-expanded", "true");
}

function removeSharedObjects(pluginId) {
  const key = String(pluginId || "");
  if (!key || !app.plugins.sharedObjects?.items) return;
  app.plugins.sharedObjects.items = app.plugins.sharedObjects.items.filter(
    (item) => item.pluginId !== key,
  );
}

function unregisterPluginSlots(pluginId) {
  const key = String(pluginId || "");
  if (!key) return;
  const filterOut = (list) => list.filter((entry) => entry.pluginId !== key);
  app.plugins.slots.toolbar = filterOut(app.plugins.slots.toolbar);
  app.plugins.slots.topRightIconRow = filterOut(app.plugins.slots.topRightIconRow);
  app.plugins.slots.transcriptTopbar = filterOut(app.plugins.slots.transcriptTopbar);
  app.plugins.slots.transcriptBottombar = filterOut(app.plugins.slots.transcriptBottombar);
  app.plugins.slots.composerLeft = filterOut(app.plugins.slots.composerLeft);
    app.plugins.slots.panels = filterOut(app.plugins.slots.panels);
    app.plugins.slots.messagePreRenderers = filterOut(app.plugins.slots.messagePreRenderers);
    app.plugins.slots.messageRenderers = filterOut(app.plugins.slots.messageRenderers);
    app.plugins.slots.blockTransformers = filterOut(app.plugins.slots.blockTransformers);
    app.plugins.slots.blockRenderers = filterOut(app.plugins.slots.blockRenderers);
    app.plugins.slots.messageFooterItems = filterOut(app.plugins.slots.messageFooterItems);
    app.plugins.slots.eventHandlers = filterOut(app.plugins.slots.eventHandlers);
  app.plugins.slots.completionPayloadHooks = filterOut(app.plugins.slots.completionPayloadHooks);
  app.plugins.slots.rosterActions = filterOut(app.plugins.slots.rosterActions);
  app.plugins.slots.sendHooks = filterOut(app.plugins.slots.sendHooks);
  app.plugins.slots.sendContextMenuItems = filterOut(app.plugins.slots.sendContextMenuItems);
  app.plugins.slots.projectCreateHandlers = filterOut(app.plugins.slots.projectCreateHandlers);
  app.plugins.slots.sessionCreateHandlers = filterOut(app.plugins.slots.sessionCreateHandlers);
  removeSharedObjects(key);
  delete app.plugins.registry[key];
}

function disablePlugin(pluginId) {
  const key = String(pluginId || "");
  if (!key) return;
  const info = app.plugins.meta[key];
  if (info) {
    info.enabled = false;
    info.status = "disabled";
  }
  setPluginEnabled(key, false);
  setAuthEnabledForPlugin(key, false);
  clearChatsOverride(key);
  clearAccountActions(key);
  if (info?.kind === "auth") {
    stopSessionEvents();
    renderStatus();
  }
  unregisterPluginSlots(key);
  const instance = app.plugins.instances[key];
  try {
    if (instance && typeof instance.dispose === "function") {
      instance.dispose(getPluginContext());
    } else if (instance && typeof instance.unregister === "function") {
      instance.unregister(getPluginContext());
    }
  } catch (err) {
    appendLog(`[plugin] dispose failed: ${err.message || err}`, "warn");
  }
  delete app.plugins.instances[key];
  app.plugins.forceLiveTranscriptRenderOnce = true;
  renderToolbar();
  renderTranscriptBars();
  renderComposerLeft();
  renderTranscript();
  renderPluginPanels();
  renderPluginTable();
  renderGuiPluginsMenu();
  renderAccountMenu();
}

async function enablePlugin(pluginId) {
  const key = String(pluginId || "");
  if (!key) return;
  const info = app.plugins.meta[key];
  if (!info) return;
  info.enabled = true;
  if (info.status === "disabled") {
    info.status = "discovered";
  }
  setPluginEnabled(key, true);
  renderPluginTable();
  renderGuiPluginsMenu();
  renderAccountMenu();
  if (app.plugins.registry[key]) {
    if (app.plugins.meta[key]?.kind === "auth" && app.state.auth.token) {
      await bootstrapRemote();
    }
    return;
  }
  const instance = app.plugins.instances[key];
  if (instance) {
    registerPluginInstance(key, instance, info.entry, instance.meta || instance.pluginMeta || {});
    if (app.plugins.meta[key]?.kind === "auth" && app.state.auth.token) {
      await bootstrapRemote();
    }
    return;
  }
  const entry = info.entry || app.plugins.entries[key];
  if (entry) {
    await loadPlugin(entry);
    if (app.plugins.meta[key]?.kind === "auth" && app.state.auth.token) {
      await bootstrapRemote();
    }
  }
}

async function loadPlugins() {
  const base = normalizeServerUrl(app.state.remote.serverUrl) || window.location.origin;
  const autoUrl = `${base}/v1/gui_js/plugins`;
  let loaded = false;
  const embedCfg = window.__CHAT_JS_EMBED_CONFIG || {};
  const embeddedMode = Boolean(embedCfg.embedded);
  const priorityOrder = (() => {
    const prefs = app.state.pluginPrefs || {};
    const list = Array.isArray(prefs.priority) ? prefs.priority : [];
    const out = [];
    const seen = new Set();
    for (const id of list) {
      const key = String(id || "").trim();
      if (!key || seen.has(key)) continue;
      seen.add(key);
      out.push(key);
    }
    return out;
  })();
  const priorityRank = new Map(priorityOrder.map((id, idx) => [id, idx]));
  const sortEnabledEntries = (list) => {
    const enabledEntries = (list || []).filter((entry) => {
      if (!entry?.path) return false;
      const pid = getPluginIdFromEntry(entry);
      return Boolean(pid) && isPluginEnabled(pid);
    });
    return enabledEntries.slice().sort((a, b) => {
      const pa = getPluginIdFromEntry(a);
      const pb = getPluginIdFromEntry(b);
      const ra = priorityRank.has(pa) ? priorityRank.get(pa) : 999999;
      const rb = priorityRank.has(pb) ? priorityRank.get(pb) : 999999;
      return ra - rb;
    });
  };
  const loadSortedEntries = async (sorted) => {
    if (embeddedMode) {
      const priority = [];
      const rest = [];
      for (const entry of sorted) {
        const pid = getPluginIdFromEntry(entry);
        if (priorityRank.has(pid)) priority.push(entry);
        else rest.push(entry);
      }
      for (const entry of priority) await loadPlugin(entry);
      for (const entry of rest) void loadPlugin(entry);
    } else {
      for (const entry of sorted) await loadPlugin(entry);
    }
  };

  try {
    const res = await fetch(autoUrl, { cache: "no-store", headers: buildHeaders() });
    if (!res.ok) {
      appendLog(`[plugins] discovery failed: ${res.status} ${res.statusText}`, "warn");
    } else {
      const data = await res.json();
      const list = data?.plugins || [];
      if (list.length) {
        savePluginDiscoveryCache(base, list);
        seedPluginList(list);
        await loadSortedEntries(sortEnabledEntries(list));
        loaded = true;
      }
    }
  } catch (err) {
    appendLog(`[plugins] auto-discovery failed: ${err.message || err}`, "warn");
  }

  if (loaded) return;

  const manifestUrl = "./plugins/manifest.json";
  try {
    const res = await fetch(manifestUrl, { cache: "no-store" });
    if (!res.ok) throw new Error("manifest missing");
    const data = await res.json();
    const list = data?.plugins || [];
    if (list.length) savePluginDiscoveryCache(base, list);
    for (const entry of list) {
      if (!entry?.path) continue;
      seedPluginList([entry]);
    }

    await loadSortedEntries(sortEnabledEntries(list));
    loaded = Boolean(list.length);
  } catch (err) {
    appendLog(`[plugins] ${err.message || err}`, "warn");
  }

  if (loaded) return;

  const cachedList = loadPluginDiscoveryCache(base);
  if (cachedList.length) {
    seedPluginList(cachedList);
    await loadSortedEntries(sortEnabledEntries(cachedList));
    setTimeout(() => void refreshGuiPluginsDiscovery(), 0);
  }
}

async function refreshGuiPluginsDiscovery() {
  const base = normalizeServerUrl(app.state.remote.serverUrl) || window.location.origin;
  const autoUrl = `${base}/v1/gui_js/plugins`;
  try {
    const res = await fetch(autoUrl, { cache: "no-store", headers: buildHeaders() });
    if (!res.ok) return;
    const data = await res.json();
    const list = data?.plugins || [];
    if (!Array.isArray(list)) return;
    if (!list.length) return;
    savePluginDiscoveryCache(base, list);

    const nextIds = new Set();
    for (const entry of list) {
      const id = getPluginIdFromEntry(entry);
      if (!id) continue;
      nextIds.add(id);
      const enabled = isPluginEnabled(id);
      const prevEntry = app.plugins.entries[id] || {};
      const pluginChanged = Boolean(
        prevEntry &&
        (String(prevEntry.path || "") !== String(entry.path || "") ||
         String(prevEntry.rev || "") !== String(entry.rev || ""))
      );
      upsertPluginInfo({
        id,
        name: entry.name || entry.id || entry.path,
        kind: entry.kind || "gui",
        description: entry.description || "",
        status: enabled ? "discovered" : "disabled",
        error: "",
        enabled,
        entry,
      });
      app.plugins.entries[id] = entry;
      if (pluginChanged && enabled) {
        disablePlugin(id);
        app.plugins.forceLiveTranscriptRenderOnce = true;
        await enablePlugin(id);
      } else if (enabled && !app.plugins.instances[id]) {
        await loadPlugin(entry);
      }
    }

    for (const id of Object.keys(app.plugins.meta)) {
      if (nextIds.has(id)) continue;
      const existing = app.plugins.meta[id];
      if (existing?.status === "loaded" || isPluginEnabled(id)) {
        continue;
      }
      delete app.plugins.meta[id];
      delete app.plugins.entries[id];
      delete app.plugins.registry[id];
      delete app.plugins.instances[id];
    }
    app.plugins.list = app.plugins.list.filter((info) => {
      if (nextIds.has(info.id)) return true;
      const existing = app.plugins.meta[info.id];
      return Boolean(existing?.status === "loaded" || isPluginEnabled(info.id));
    });
    app.plugins.list.sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id));
    renderPluginTable();
    renderPluginPanels();
  } catch (err) {
    appendLog(`[plugins] refresh failed: ${err.message || err}`, "warn");
  }
}

function ensurePluginsLoaded({ force = false } = {}) {
  if (!force && app.plugins.loadingComplete && pluginsActuallyReady()) {
    return Promise.resolve();
  }
  if (app.plugins.loadPromise) return app.plugins.loadPromise;
  app.plugins.loadPromise = (async () => {
    app.plugins.loading = true;
    app.plugins.loadingComplete = false;
    app.plugins.suppressTranscriptRefresh = true;
    try {
      await loadPlugins();
      app.plugins.loadingComplete = true;
      app.plugins.ready = pluginsActuallyReady();
    } finally {
      app.plugins.loading = false;
      app.plugins.suppressTranscriptRefresh = false;
    }
  })().finally(() => {
    app.plugins.loadPromise = null;
  });
  return app.plugins.loadPromise;
}

function pluginsActuallyReady() {
  const plugins = app?.plugins || {};
  const slots = plugins.slots || {};
  const hasInstances = Object.keys(plugins.instances || {}).length > 0;
  const hasRenderHooks = Boolean(
    (slots.messageRenderers || []).length ||
    (slots.messagePreRenderers || []).length ||
    (slots.blockTransformers || []).length ||
    (slots.blockRenderers || []).length ||
    (slots.messageFooterItems || []).length
  );
  return hasInstances || hasRenderHooks;
}

function schedulePluginAutoload() {
  if (app.plugins.list.length > 0) return;
  if (app.plugins.autoLoadTimer) return;
  const attempt = app.plugins.autoLoadAttempts || 0;
  if (attempt >= 6) return;
  const delay = attempt === 0 ? 300 : Math.min(3000, 800 + attempt * 500);
  app.plugins.autoLoadTimer = setTimeout(async () => {
    app.plugins.autoLoadTimer = null;
    app.plugins.autoLoadAttempts = attempt + 1;
    await ensurePluginsLoaded({ force: true });
    if (app.plugins.list.length === 0) {
      schedulePluginAutoload();
    }
  }, delay);
}

function registerPluginInstance(pluginId, plugin, entry, meta) {
  const key = String(pluginId || "");
  if (!key) return;
  if (app.plugins.registry[key] && app.plugins.instances[key]) {
    if (entry) {
      app.plugins.entries[key] = entry;
      const existingInfo = app.plugins.meta[key];
      if (existingInfo) existingInfo.entry = entry;
    }
    return;
  }
  const metaInfo = meta || {};
  const existing = app.plugins.meta[key] || {};
  const info = upsertPluginInfo({
    id: key,
    name: metaInfo.name || plugin.name || entry?.name || entry?.id || entry?.path || key,
    kind: metaInfo.kind || plugin.kind || plugin.type || entry?.kind || "gui",
    description: metaInfo.description || plugin.description || entry?.description || "",
    hasPanel: Boolean(existing.hasPanel),
    openSettings: typeof plugin.openSettings === "function" ? plugin.openSettings : null,
    status: "loaded",
    error: "",
    enabled: true,
    entry,
    meta: metaInfo,
  });
  info.entry = entry || info.entry;
  info.enabled = true;
  info.status = "loaded";
  info.error = "";
  app.plugins.entries[key] = info.entry;
  app.plugins.instances[key] = plugin;

  app.plugins.currentRegistering = key;
  try {
    if (plugin.register) {
      plugin.register(createPluginHost(key));
    }
  } finally {
    app.plugins.currentRegistering = null;
  }

  app.plugins.list.sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id));
  renderPluginTable();
  renderPluginPanels();
  renderToolbar();
  renderTopRightIconRow();
  renderComposerLeft();
  if (!app.plugins.suppressTranscriptRefresh) renderTranscript();
  renderGuiPluginsMenu();
  renderAccountMenu();
  renderChatsOverride();
}

async function loadPlugin(entry) {
  try {
    const path = resolvePluginPath(entry.path, entry);
    if (!path) return;
    const mod = await import(path);
    const plugin = mod.default || mod.plugin || mod;
    if (!plugin) return;
    const meta = plugin.meta || plugin.pluginMeta || {};
    const pluginId = String(meta.plugin_id || meta.id || plugin.id || entry.id || entry.path || "").trim();
    if (!pluginId) return;
    registerPluginInstance(pluginId, plugin, entry, meta);
  } catch (err) {
    const pid = getPluginIdFromEntry(entry) || entry.path;
    const info = upsertPluginInfo({
      id: pid,
      name: entry.name || entry.id || entry.path || pid,
      kind: entry.kind || "gui",
      description: "",
      status: "error",
      error: err.message || String(err),
      enabled: isPluginEnabled(pid),
    });
    info.status = "error";
    info.error = err.message || String(err);
    renderPluginTable();
    appendLog(`[plugins] failed ${entry.path}: ${err.message || err}`, "warn");
  }
}

function seedPluginList(list) {
  for (const entry of list || []) {
    const id = getPluginIdFromEntry(entry);
    if (!id) continue;
    const enabled = isPluginEnabled(id);
    upsertPluginInfo({
      id,
      name: entry.name || entry.id || entry.path,
      kind: entry.kind || "gui",
      description: entry.description || "",
      status: enabled ? "discovered" : "disabled",
      error: "",
      enabled,
      entry,
    });
    app.plugins.entries[id] = entry;
  }
  app.plugins.list.sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id));
  renderPluginTable();
}

function upsertPluginInfo(info) {
  const existing = app.plugins.meta[info.id];
  if (existing) {
    const keepLoaded = existing.status === "loaded" && info.status === "discovered";
    const loadedFields = keepLoaded
      ? {
          status: existing.status,
          error: existing.error || "",
          openSettings: existing.openSettings,
          hasPanel: existing.hasPanel,
          meta: existing.meta,
        }
      : null;
    Object.assign(existing, info);
    if (loadedFields) {
      Object.assign(existing, loadedFields);
    }
    return existing;
  }
  app.plugins.meta[info.id] = info;
  app.plugins.list.push(info);
  return info;
}

function resolvePluginPath(path, entry = null) {
  if (!path) return "";
  const base = normalizeServerUrl(app.state.remote.serverUrl) || window.location.origin;
  const embedCfg = window.__CHAT_JS_EMBED_CONFIG || {};
  const assetRev = String(
    (entry && (entry.rev || entry.cacheBust || entry.updated_at || entry.updatedAt)) ||
    embedCfg.assetRev ||
    ""
  ).trim();
  const asUrl = (() => {
    if (/^https?:\/\//i.test(path)) return new URL(path);
    if (path.startsWith("/")) return new URL(`${base}${path}`);
    return new URL(path, window.location.href);
  })();
  if (assetRev) {
    asUrl.searchParams.set("rev", assetRev);
  }
  return asUrl.toString();
}


function registerFrameworkI18nBundle() {
  try {
    registerI18nBundle({
      id: "chat_js",
      pluginId: "chat_js",
      basePath: new URL("./lang/", import.meta.url).toString(),
      languages: ["en", "es", "ja", "zh"],
      defaultLanguage: "en",
    });
  } catch (err) {
    try { appendLog(`[i18n] failed to register chat_js language bundle: ${err?.message || err}`, "warn"); } catch (_err) {}
  }
}

function ensureI18nState() {
  if (!app.plugins.i18n || typeof app.plugins.i18n !== "object") {
    app.plugins.i18n = { bundles: [], dictionaries: {}, callbacks: [] };
  }
  if (!Array.isArray(app.plugins.i18n.bundles)) app.plugins.i18n.bundles = [];
  if (!app.plugins.i18n.dictionaries || typeof app.plugins.i18n.dictionaries !== "object") app.plugins.i18n.dictionaries = {};
  if (!Array.isArray(app.plugins.i18n.callbacks)) app.plugins.i18n.callbacks = [];
  if (!app.state.ui) app.state.ui = {};
  if (!app.state.ui.locale) app.state.ui.locale = "en";
  return app.plugins.i18n;
}

function normalizeI18nLocale(locale) {
  return String(locale || "en").trim().toLowerCase().replace("_", "-") || "en";
}

function getLanguage() {
  ensureI18nState();
  return normalizeI18nLocale(app.state.ui.locale || "en");
}

function setLanguage(locale) {
  const next = normalizeI18nLocale(locale || "en");
  ensureI18nState();
  if (!app.state.ui) app.state.ui = {};
  const prev = normalizeI18nLocale(app.state.ui.locale || "en");
  app.state.ui.locale = next;
  scheduleSave();
  if (prev !== next) emitLanguageChange(next, prev);
  return next;
}

window.addEventListener("chatjs:rerender-top-right", () => {
  try {
    renderTopRightIconRow();
  } catch (_err) {}
});

function registerI18nBundle(bundle = {}) {
  const i18n = ensureI18nState();
  const pluginId = String(bundle.pluginId || app.plugins.currentRegistering || "").trim();
  const id = String(bundle.id || pluginId || bundle.basePath || "").trim();
  const basePath = String(bundle.basePath || "").trim();
  if (!id || !basePath) return null;
  const entry = {
    type: "i18n_bundle",
    id,
    pluginId,
    basePath,
    languages: Array.isArray(bundle.languages) ? bundle.languages.map(normalizeI18nLocale) : ["en"],
    defaultLanguage: normalizeI18nLocale(bundle.defaultLanguage || "en"),
  };
  i18n.bundles = i18n.bundles.filter((b) => String(b.id || "") !== id);
  i18n.bundles.push(entry);
  addSharedObject(pluginId, entry);
  return entry;
}

function installI18nDictionary(locale, dict, options = {}) {
  const i18n = ensureI18nState();
  const key = normalizeI18nLocale(locale || getLanguage());
  if (!i18n.dictionaries[key] || typeof i18n.dictionaries[key] !== "object") i18n.dictionaries[key] = {};
  const target = i18n.dictionaries[key];
  const source = dict && typeof dict === "object" ? dict : {};
  for (const [k, v] of Object.entries(source)) {
    if (k === "__text" && v && typeof v === "object") {
      if (!target.__text || typeof target.__text !== "object") target.__text = {};
      Object.assign(target.__text, v);
    } else {
      target[k] = v;
    }
  }
  if (options.activate) setLanguage(key);
  else if (key === getLanguage() || key === getLanguage().split("-")[0] || key === "en") {
    Promise.resolve().then(() => applyFrameworkTranslations());
  }
  return target;
}

function i18nTranslate(key, fallback = "") {
  const i18n = ensureI18nState();
  const locale = getLanguage();
  const exact = i18n.dictionaries?.[locale]?.[key];
  if (exact != null) return String(exact);
  const base = locale.split("-")[0];
  const baseHit = i18n.dictionaries?.[base]?.[key];
  if (baseHit != null) return String(baseHit);
  const en = i18n.dictionaries?.en?.[key];
  if (en != null) return String(en);
  return String(fallback != null ? fallback : key);
}

function translateContainer(root, pluginId = "") {
  if (!root) return;
  const i18n = ensureI18nState();
  const locale = getLanguage();
  const textMap = Object.assign(
    {},
    i18n.dictionaries?.en?.__text || {},
    i18n.dictionaries?.[locale.split("-")[0]]?.__text || {},
    i18n.dictionaries?.[locale]?.__text || {},
  );
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement;
      if (!parent) return NodeFilter.FILTER_REJECT;
      const tag = String(parent.tagName || "").toLowerCase();
      if (["script", "style", "textarea", "pre", "code"].includes(tag)) return NodeFilter.FILTER_REJECT;
      const text = String(node.nodeValue || "");
      if (!text.trim()) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const node of nodes) {
    const raw = String(node.nodeValue || "");
    const trimmed = raw.trim();
    const hit = textMap[trimmed];
    if (hit == null) continue;
    node.nodeValue = raw.replace(trimmed, String(hit));
  }
  for (const el of Array.from(root.querySelectorAll("[data-i18n-key]"))) {
    const key = el.getAttribute("data-i18n-key") || "";
    const attr = el.getAttribute("data-i18n-attr") || "textContent";
    const fallback = el.getAttribute("data-i18n-fallback") || el.textContent || key;
    const value = i18nTranslate(key, fallback);
    if (attr === "textContent") el.textContent = value;
    else el.setAttribute(attr, value);
  }
  for (const attr of ["placeholder", "title", "aria-label"]) {
    const selector = `[data-i18n-${attr}]`;
    for (const el of Array.from(root.querySelectorAll(selector))) {
      const key = el.getAttribute(`data-i18n-${attr}`) || "";
      if (!key) continue;
      const fallback = el.getAttribute(attr) || key;
      el.setAttribute(attr, i18nTranslate(key, fallback));
    }
  }
}

function applyFrameworkTranslations(root = document.body) {
  try {
    document.documentElement.lang = getLanguage();
    document.title = i18nTranslate("chat_js.document.title", document.title || "GotChat Foundry");
    translateContainer(root || document.body, "chat_js");
    renderAuthStatus();
  } catch (err) {
    try { appendLog(`[i18n] framework translation failed: ${err?.message || err}`, "warn"); } catch (_err) {}
  }
}

function onLanguageChange(callback) {
  const i18n = ensureI18nState();
  if (typeof callback !== "function") return () => {};
  i18n.callbacks.push(callback);
  return () => {
    i18n.callbacks = i18n.callbacks.filter((cb) => cb !== callback);
  };
}

function emitLanguageChange(locale, previousLocale) {
  const i18n = ensureI18nState();
  for (const cb of [...i18n.callbacks]) {
    try { cb(locale, previousLocale); } catch (err) { appendLog(`[i18n] language callback failed: ${err?.message || err}`, "warn"); }
  }
  renderTranscriptBars();
  renderPluginPanels();
  renderToolbar();
  applyFrameworkTranslations();
}

function createPluginHost(fixedPluginId = null) {
  const fixedPid = String(fixedPluginId || "").trim() || null;
  return {
    requestLoadPriority(options = {}) {
      const pid = fixedPid || app.plugins.currentRegistering;
      if (!pid) return false;
      const position = options.position || options.mode || options.level || "first";
      return requestPluginPriority(pid, { position });
    },
    requestEmbedPreload(kind) {
      const pid = fixedPid || app.plugins.currentRegistering;
      if (!pid) return false;
      return requestPluginPreload(pid, kind);
    },
    addToolbarAction(action) {
      const pid = fixedPid || app.plugins.currentRegistering;
      const entry = { pluginId: pid, action };
      app.plugins.slots.toolbar.push(entry);
      const reg = getPluginRegistry(pid);
      if (reg) reg.toolbar.push(entry);
      renderToolbar();
    },
    addTopRightIconRow(nodeOrFactory) {
      const pid = fixedPid || app.plugins.currentRegistering;
      const entry = { pluginId: pid, entry: nodeOrFactory, node: null };
      app.plugins.slots.topRightIconRow.push(entry);
      const reg = getPluginRegistry(pid);
      if (reg) reg.topRightIconRow.push(entry);
      renderTopRightIconRow();
    },
    addTranscriptTopbar(nodeOrFactory, side = "right") {
      const pid = fixedPid || app.plugins.currentRegistering;
      const entry = { pluginId: pid, entry: nodeOrFactory, node: null, side };
      app.plugins.slots.transcriptTopbar.push(entry);
      const reg = getPluginRegistry(pid);
      if (reg) reg.transcriptTopbar.push(entry);
      renderTranscriptBars();
    },
    addTranscriptBottombar(nodeOrFactory, side = "left") {
      const pid = fixedPid || app.plugins.currentRegistering;
      const entry = { pluginId: pid, entry: nodeOrFactory, node: null, side };
      app.plugins.slots.transcriptBottombar.push(entry);
      const reg = getPluginRegistry(pid);
      if (reg) reg.transcriptBottombar.push(entry);
      renderTranscriptBars();
    },
    addComposerLeft(nodeOrFactory) {
      const pid = fixedPid || app.plugins.currentRegistering;
      const entry = { pluginId: pid, entry: nodeOrFactory, node: null };
      app.plugins.slots.composerLeft.push(entry);
      const reg = getPluginRegistry(pid);
      if (reg) reg.composerLeft.push(entry);
      renderComposerLeft();
    },
      addPanelTab(tab) {
      const pid = fixedPid || app.plugins.currentRegistering;
      if (pid && tab && !tab.pluginId) {
        tab.pluginId = pid;
      }
      if (pid && app.plugins.meta[pid]) {
        app.plugins.meta[pid].hasPanel = true;
      }
      const entry = { pluginId: pid, tab };
      app.plugins.slots.panels.push(entry);
      const reg = getPluginRegistry(pid);
      if (reg) reg.panels.push(entry);
      renderPluginPanels();
    },
      addMessageRenderer(renderer) {
        const pid = fixedPid || app.plugins.currentRegistering;
        const entry = { pluginId: pid, fn: renderer };
        app.plugins.slots.messageRenderers.push(entry);
        const reg = getPluginRegistry(pid);
        if (reg) reg.messageRenderers.push(entry);
        if (!app.plugins.suppressTranscriptRefresh) renderTranscript();
      },
      addMessagePreRenderer(renderer) {
        const pid = fixedPid || app.plugins.currentRegistering;
        const entry = { pluginId: pid, fn: renderer };
        app.plugins.slots.messagePreRenderers.push(entry);
        const reg = getPluginRegistry(pid);
        if (reg) {
          reg.messagePreRenderers = reg.messagePreRenderers || [];
          reg.messagePreRenderers.push(entry);
        }
        if (!app.plugins.suppressTranscriptRefresh) renderTranscript();
      },
      addBlockRenderer(renderer) {
        const pid = fixedPid || app.plugins.currentRegistering;
        const entry = { pluginId: pid, fn: renderer };
        app.plugins.slots.blockRenderers.push(entry);
        const reg = getPluginRegistry(pid);
        if (reg) {
          reg.blockRenderers = reg.blockRenderers || [];
          reg.blockRenderers.push(entry);
        }
        if (!app.plugins.suppressTranscriptRefresh) renderTranscript();
      },
      addMessageFooterItem(item) {
        const pid = fixedPid || app.plugins.currentRegistering;
        let entry = item;
        if (typeof item === "function") {
          entry = { render: item };
        }
        entry.pluginId = pid;
        app.plugins.slots.messageFooterItems.push(entry);
        const reg = getPluginRegistry(pid);
        if (reg) {
          reg.messageFooterItems = reg.messageFooterItems || [];
          reg.messageFooterItems.push(entry);
        }
        if (!app.plugins.suppressTranscriptRefresh) renderTranscript();
      },
      addBlockTransformer(transformer) {
        const pid = fixedPid || app.plugins.currentRegistering;
        const entry = {
          pluginId: pid,
        transformer,
        priority: Number(transformer?.priority || 0),
      };
      app.plugins.slots.blockTransformers.push(entry);
      const reg = getPluginRegistry(pid);
      if (reg) reg.blockTransformers.push(entry);
      sortBlockTransformers();
      if (!app.plugins.suppressTranscriptRefresh) renderTranscript();
    },
    addCompletionPayloadHook(handler) {
      const pid = fixedPid || app.plugins.currentRegistering;
      const entry = { pluginId: pid, fn: handler };
      app.plugins.slots.completionPayloadHooks.push(entry);
      const reg = getPluginRegistry(pid);
      if (reg) reg.completionPayloadHooks.push(entry);
    },
    addRosterAction(handler) {
      const pid = fixedPid || app.plugins.currentRegistering;
      const entry = { pluginId: pid, fn: handler };
      app.plugins.slots.rosterActions.push(entry);
      const reg = getPluginRegistry(pid);
      if (reg) reg.rosterActions.push(entry);
      if (app.dom.toolbarRoster) {
        app.dom.toolbarRoster.classList.add("clickable");
      }
    },
    addEventHandler(handler) {
      const pid = fixedPid || app.plugins.currentRegistering;
      const entry = { pluginId: pid, fn: handler };
      app.plugins.slots.eventHandlers.push(entry);
      const reg = getPluginRegistry(pid);
      if (reg) reg.eventHandlers.push(entry);
    },
    addSendHook(handler, options = {}) {
      const pid = fixedPid || app.plugins.currentRegistering;
      const timeoutMs = Math.max(1, Number(options?.timeoutMs) || 0) || undefined;
      const entry = { pluginId: pid, fn: handler, ...(timeoutMs ? { timeoutMs } : {}) };
      app.plugins.slots.sendHooks.push(entry);
      const reg = getPluginRegistry(pid);
      if (reg) reg.sendHooks.push(entry);
    },
    addSendContextMenuItem(buildItem) {
      const pid = fixedPid || app.plugins.currentRegistering;
      const entry = { pluginId: pid, fn: buildItem };
      app.plugins.slots.sendContextMenuItems.push(entry);
      const reg = getPluginRegistry(pid);
      if (reg) {
        reg.sendContextMenuItems = reg.sendContextMenuItems || [];
        reg.sendContextMenuItems.push(entry);
      }
    },
    setProjectCreateHandler(handler) {
      const pid = fixedPid || app.plugins.currentRegistering;
      if (!pid || typeof handler !== "function") return;
      const entry = { pluginId: pid, fn: handler };
      // One handler per plugin; last registered wins in UI.
      app.plugins.slots.projectCreateHandlers = (app.plugins.slots.projectCreateHandlers || []).filter((e) => e.pluginId !== pid);
      app.plugins.slots.projectCreateHandlers.push(entry);
      const reg = getPluginRegistry(pid);
      if (reg) {
        reg.projectCreateHandlers = (reg.projectCreateHandlers || []).filter((e) => e.pluginId !== pid);
        reg.projectCreateHandlers.push(entry);
      }
    },
    setSessionCreateHandler(handler) {
      const pid = fixedPid || app.plugins.currentRegistering;
      if (!pid || typeof handler !== "function") return;
      const entry = { pluginId: pid, fn: handler };
      app.plugins.slots.sessionCreateHandlers = (app.plugins.slots.sessionCreateHandlers || []).filter((e) => e.pluginId !== pid);
      app.plugins.slots.sessionCreateHandlers.push(entry);
      const reg = getPluginRegistry(pid);
      if (reg) {
        reg.sessionCreateHandlers = (reg.sessionCreateHandlers || []).filter((e) => e.pluginId !== pid);
        reg.sessionCreateHandlers.push(entry);
      }
    },
    registerI18nBundle(bundle) {
      const pid = fixedPid || app.plugins.currentRegistering;
      return registerI18nBundle({ ...(bundle || {}), pluginId: (bundle && bundle.pluginId) || pid });
    },
    installI18nDictionary(locale, dict, options) {
      return installI18nDictionary(locale, dict, options);
    },
    getI18nBundles() {
      return ensureI18nState().bundles.slice();
    },
    t(key, fallback) {
      return i18nTranslate(key, fallback);
    },
    translateContainer(root, pluginId) {
      return translateContainer(root, pluginId || fixedPid || app.plugins.currentRegistering || "");
    },
    setLanguage(locale) {
      return setLanguage(locale);
    },
    getLanguage() {
      return getLanguage();
    },
    onLanguageChange(callback) {
      return onLanguageChange(callback);
    },
    resolvePluginPath(path) {
      return resolvePluginPath(path);
    },
    shareObject(obj) {
      const pid = fixedPid || app.plugins.currentRegistering;
      return addSharedObject(pid, obj);
    },
    getSharedObjects(filter) {
      return getSharedObjects(filter);
    },
    getSavedUiTheme() {
      return normalizeUiThemeSnapshot(app.state?.ui?.savedTheme);
    },
    getSharedUiThemeDefault() {
      return {
        themeSnapshot: normalizeUiThemeSnapshot(app.state?.ui?.serverTheme),
        themeState: normalizeUiThemeStateValue(app.state?.ui?.serverThemeState),
      };
    },
    getUiThemeDefaults(target) {
      return getUiThemeDefaultsForTarget(target || getEmbedMount() || document.documentElement);
    },
    applyUiTheme(snapshot, options) {
      const pid = fixedPid || app.plugins.currentRegistering;
      const normalized = normalizeUiThemeSnapshot(snapshot, pid);
      return normalized ? applyUiThemeSnapshot(normalized, options) : false;
    },
    saveUiTheme(snapshot) {
      const pid = fixedPid || app.plugins.currentRegistering;
      const normalized = normalizeUiThemeSnapshot(snapshot, pid);
      return normalized ? applyUiThemeSnapshot(normalized, { save: true }) : false;
    },
    async saveSharedUiThemeDefault(payload) {
      const pid = fixedPid || app.plugins.currentRegistering;
      const themeSnapshot = normalizeUiThemeSnapshot(payload?.themeSnapshot, pid);
      const themeState = normalizeUiThemeStateValue(payload?.themeState);
      const routePid = String(payload?.pluginId || themeSnapshot?.pluginId || pid || "").trim();
      if (!routePid) throw new Error("plugin id required for shared UI theme save");
      const data = await apiJson(`/v1/${encodeURIComponent(routePid)}/default_theme`, {
        method: "POST",
        body: { theme_snapshot: themeSnapshot, theme_state: themeState },
        timeoutMs: 6000,
      });
      const savedSnapshot = data?.theme_snapshot || themeSnapshot;
      setServerUiThemeDefault(savedSnapshot, data?.theme_state || themeState, { save: true });
      if (savedSnapshot) {
        app.state.ui.useLocalThemeOverride = false;
        applyUiThemeSnapshot(savedSnapshot, { save: false });
      }
      return data;
    },
    clearUiTheme(options) {
      return clearUiThemeSnapshot(options);
    },
    enableAccountMenu() {
      const pid = fixedPid || app.plugins.currentRegistering;
      setAuthEnabledForPlugin(pid, true);
    },
    disableAccountMenu() {
      const pid = fixedPid || app.plugins.currentRegistering;
      setAuthEnabledForPlugin(pid, false);
    },
    openTools(panelId) {
      openTools(panelId || "chats");
    },
    openPluginPanel(pluginId, options) {
      const pid = pluginId || fixedPid || app.plugins.currentRegistering;
      if (pid) openPluginPanel(pid, options);
    },
    openPluginPanelWhenReady(pluginId, options) {
      const pid = pluginId || fixedPid || app.plugins.currentRegistering;
      if (!pid) return Promise.resolve(false);
      return openPluginPanelWhenReady(pid, options);
    },
    openPluginFullView(pluginId, options) {
      const pid = pluginId || fixedPid || app.plugins.currentRegistering;
      if (pid) openPluginFullView(pid, options);
    },
    setActiveScope(pid, sid) {
      return setActiveScope(pid, sid);
    },
    refreshProjects() {
      return refreshProjects();
    },
    refreshSessions() {
      return refreshSessions();
    },
    refreshMessages() {
      return loadSessionMessages();
    },
    refreshGuiPluginsDiscovery() {
      return refreshGuiPluginsDiscovery();
    },
    login(username, password) {
      return loginWithCredentials(username, password);
    },
    logout(announce) {
      return logout(Boolean(announce));
    },
    sendMessage() {
      return sendMessage();
    },
    sendAssistantResponse() {
      return sendAssistantResponse();
    },
    setChatsOverride(override) {
      const pid = fixedPid || app.plugins.currentRegistering;
      setChatsOverride(pid, override);
    },
    clearChatsOverride() {
      const pid = fixedPid || app.plugins.currentRegistering;
      clearChatsOverride(pid);
    },
    setAccountActions(actions) {
      const pid = fixedPid || app.plugins.currentRegistering;
      setAccountActions(pid, actions);
    },
    clearAccountActions() {
      const pid = fixedPid || app.plugins.currentRegistering;
      clearAccountActions(pid);
    },
    log: appendLog,
    getState: () => app.state,
  };
}

function sortBlockTransformers() {
  app.plugins.slots.blockTransformers.sort((a, b) => {
    const ap = Number(a?.priority || 0);
    const bp = Number(b?.priority || 0);
    return ap - bp;
  });
}

function renderPluginTable() {
  if (!app.dom.pluginTableBody) return;
  app.dom.pluginTableBody.innerHTML = "";
  if (!hasPermission("ui.plugins.view", false)) {
    const empty = document.createElement("div");
    empty.className = "plugin-row plugin-empty";
    empty.innerHTML = '<div class="plugin-cell">Plugin management is not available for this user.</div>';
    app.dom.pluginTableBody.appendChild(empty);
    return;
  }
  const items = (app.plugins.list || []).filter((plugin) =>
    canAccessPlugin(plugin?.id || "", "view") && pluginRepoManageMatches({
      name: plugin?.name || "",
      id: plugin?.id || "",
      description: plugin?.description || plugin?.error || "",
      type: plugin?.kind || "gui",
    })
  );
  if (items.length === 0) {
    const empty = document.createElement("div");
    empty.className = "plugin-row plugin-empty";
    empty.innerHTML = `<div class="plugin-cell">${app.plugins.list.length ? "No loaded plugins match the current filter." : "No plugins loaded"}</div>`;
    app.dom.pluginTableBody.appendChild(empty);
    return;
  }
  for (const plugin of items) {
    const row = document.createElement("div");
    row.className = "plugin-row";
    const onCell = document.createElement("div");
    onCell.className = "plugin-cell plugin-cell-toggle";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    const enabled = Boolean(plugin.enabled ?? isPluginEnabled(plugin.id));
    plugin.enabled = enabled;
    checkbox.checked = enabled;
    checkbox.addEventListener("change", () => {
      const next = checkbox.checked;
      if (next) {
        void enablePlugin(plugin.id);
      } else {
        disablePlugin(plugin.id);
      }
    });
    onCell.appendChild(checkbox);

    const nameCell = document.createElement("div");
    nameCell.className = "plugin-cell plugin-cell-name";
    nameCell.dataset.pluginType = plugin.kind || "gui";
    nameCell.textContent = plugin.name || plugin.id;

    const typeCell = document.createElement("div");
    typeCell.className = "plugin-cell plugin-cell-type";
    typeCell.textContent = plugin.kind || "gui";

    const descCell = document.createElement("div");
    descCell.className = "plugin-cell plugin-cell-desc";
    let descText = plugin.description || "";
    if (plugin.status === "error") {
      const err = plugin.error || "failed to load";
      descText = `Error: ${err}`;
    } else if (!enabled) {
      descText = descText ? `${descText} (disabled)` : "Disabled";
    }
    descCell.textContent = descText;

    const actionCell = document.createElement("div");
    actionCell.className = "plugin-cell plugin-cell-actions";
    const actions = buildPluginActions(plugin);
    actionCell.appendChild(actions);

    row.appendChild(onCell);
    row.appendChild(nameCell);
    row.appendChild(typeCell);
    row.appendChild(descCell);
    row.appendChild(actionCell);
    app.dom.pluginTableBody.appendChild(row);
  }
}

function buildPluginActions(plugin) {
  const wrap = document.createElement("div");
  wrap.className = "action-menu";

  const enabled = Boolean(plugin.enabled ?? isPluginEnabled(plugin.id));
  const loaded = plugin.status === "loaded";
  const canOpen = Boolean(enabled && loaded && plugin.hasPanel && canAccessPlugin(plugin.id, "open"));
  const canSettings = Boolean(enabled && loaded && plugin.openSettings && canAccessPlugin(plugin.id, "settings"));
  if (!canOpen && !canSettings) {
    wrap.innerHTML = "<span class=\"muted\">—</span>";
    return wrap;
  }

  const btn = document.createElement("button");
  btn.className = "ghost action-button";
  btn.textContent = "⋯";

  const menu = document.createElement("div");
  menu.className = "action-menu-list hidden";

  if (canOpen) {
    const openBtn = document.createElement("button");
    openBtn.className = "action-menu-item";
    openBtn.textContent = i18nTranslate("chat_js.common.open", "Open");
    openBtn.addEventListener("click", () => {
      menu.classList.add("hidden");
      openPluginPanel(plugin.id, { openModal: true });
    });
    menu.appendChild(openBtn);
  }

  if (canSettings) {
    const settingsBtn = document.createElement("button");
    settingsBtn.className = "action-menu-item";
    settingsBtn.textContent = i18nTranslate("chat_js.common.settings", "Settings");
    settingsBtn.addEventListener("click", () => {
      menu.classList.add("hidden");
      try {
        const instance = app.plugins.instances[plugin.id];
        const handler = instance?.openSettings || plugin.openSettings;
        handler?.(getPluginContext());
      } catch (err) {
        appendLog(`[plugin] settings error: ${err.message || err}`, "warn");
      }
    });
    menu.appendChild(settingsBtn);
  }

  btn.addEventListener("click", (event) => {
    event.stopPropagation();
    menu.classList.toggle("hidden");
  });
  document.addEventListener("click", (event) => {
    if (!wrap.contains(event.target)) {
      menu.classList.add("hidden");
    }
  });

  wrap.appendChild(btn);
  wrap.appendChild(menu);
  return wrap;
}

function ensurePluginRepoState() {
  if (!app.state.pluginRepo || typeof app.state.pluginRepo !== "object") {
      app.state.pluginRepo = {
        apiBase: "https://pluginserver.gotchat.ai/api",
        downloads: [],
        installedServer: {},
        installedClient: {},
        lastSearch: [],
        manageSearch: "",
        manageTypeFilters: [],
        searchFilter: "top_rated",
        searchPage: 1,
        searchPageSize: 10,
        downloadedPage: 1,
        downloadedPageSize: 10,
        restartRequired: false,
        restartPlugins: [],
      };
  }
  if (!Array.isArray(app.state.pluginRepo.downloads)) app.state.pluginRepo.downloads = [];
    if (!Array.isArray(app.state.pluginRepo.lastSearch)) app.state.pluginRepo.lastSearch = [];
    if (typeof app.state.pluginRepo.manageSearch !== "string") app.state.pluginRepo.manageSearch = "";
    if (!Array.isArray(app.state.pluginRepo.manageTypeFilters)) app.state.pluginRepo.manageTypeFilters = [];
    if (!app.state.pluginRepo.searchFilter) app.state.pluginRepo.searchFilter = "top_rated";
    if (!app.state.pluginRepo.searchPage) app.state.pluginRepo.searchPage = 1;
    if (!app.state.pluginRepo.searchPageSize) app.state.pluginRepo.searchPageSize = 10;
    if (!app.state.pluginRepo.downloadedPage) app.state.pluginRepo.downloadedPage = 1;
    if (!app.state.pluginRepo.downloadedPageSize) app.state.pluginRepo.downloadedPageSize = 10;
  if (app.state.pluginRepo.restartRequired === undefined) {
    app.state.pluginRepo.restartRequired = false;
  }
  if (!Array.isArray(app.state.pluginRepo.restartPlugins)) {
    app.state.pluginRepo.restartPlugins = [];
  }
  if (app.state.pluginRepo.clientServiceAvailable === undefined) {
    app.state.pluginRepo.clientServiceAvailable = false;
  }
  if (app.state.pluginRepo.serverInContainer === undefined) {
    app.state.pluginRepo.serverInContainer = false;
  }
  if (!app.state.pluginRepo.installedServer || typeof app.state.pluginRepo.installedServer !== "object") {
    app.state.pluginRepo.installedServer = {};
  }
  if (!app.state.pluginRepo.installedClient || typeof app.state.pluginRepo.installedClient !== "object") {
    app.state.pluginRepo.installedClient = {};
  }
  if (!app.state.pluginRepo.apiBase) {
    app.state.pluginRepo.apiBase = "https://pluginserver.gotchat.ai/api";
  }
}

function normalizePluginRepoManageType(value) {
  return String(value || "").trim().toLowerCase();
}

function getPluginRepoManageSearch() {
  ensurePluginRepoState();
  return String(app.state.pluginRepo.manageSearch || "").trim().toLowerCase();
}

function getPluginRepoManageTypeFilters() {
  ensurePluginRepoState();
  return Array.from(
    new Set(
      (app.state.pluginRepo.manageTypeFilters || [])
        .map(normalizePluginRepoManageType)
        .filter(Boolean)
    )
  );
}

function pluginRepoManageMatches({ name = "", id = "", description = "", type = "" } = {}) {
  const query = getPluginRepoManageSearch();
  const typeFilters = getPluginRepoManageTypeFilters();
  const normalizedType = normalizePluginRepoManageType(type);
  if (typeFilters.length && !typeFilters.includes(normalizedType)) return false;
  if (!query) return true;
  const haystack = [name, id, description, normalizedType].map((part) => String(part || "").toLowerCase()).join(" ");
  return haystack.includes(query);
}

function getPluginRepoManageTypeCounts() {
  const counts = new Map();
  for (const plugin of app.plugins.list || []) {
    const type = normalizePluginRepoManageType(plugin?.kind || "gui");
    if (!type) continue;
    counts.set(type, (counts.get(type) || 0) + 1);
  }
  const sid = app.state.ui.activeSid;
  const { enabled, settings } = getRouterConfig(sid);
  const manifest = getRouterManifest();
  for (const pid of routerAvailablePlugins(manifest, enabled, settings)) {
    const meta = manifest[pid] || {};
    const type = normalizePluginRepoManageType(meta.type || "router");
    if (!type) continue;
    counts.set(type, (counts.get(type) || 0) + 1);
  }
  return Array.from(counts.entries()).sort((a, b) => a[0].localeCompare(b[0]));
}

function renderPluginRepoManageFilterMenu() {
  if (!app.dom.pluginRepoManageFilterList) return;
  ensurePluginRepoState();
  const list = app.dom.pluginRepoManageFilterList;
  list.innerHTML = "";
  const selected = new Set(getPluginRepoManageTypeFilters());
  const entries = getPluginRepoManageTypeCounts();
  if (!entries.length) {
    const empty = document.createElement("div");
    empty.className = "muted";
    empty.textContent = "No plugin types.";
    list.appendChild(empty);
  } else {
    for (const [type, count] of entries) {
      const row = document.createElement("div");
      row.className = "plugin-manage-filter-item";
      const label = document.createElement("label");
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = selected.has(type);
      box.addEventListener("change", () => {
        ensurePluginRepoState();
        const next = new Set(getPluginRepoManageTypeFilters());
        if (box.checked) next.add(type);
        else next.delete(type);
        app.state.pluginRepo.manageTypeFilters = Array.from(next);
        scheduleSave();
        renderPluginRepoManageFilterMenu();
        renderPluginTable();
        renderRouterPluginsList();
      });
      const text = document.createElement("span");
      text.textContent = type || "unknown";
      label.appendChild(box);
      label.appendChild(text);
      row.appendChild(label);
      const countNode = document.createElement("span");
      countNode.className = "plugin-manage-filter-count";
      countNode.textContent = String(count);
      row.appendChild(countNode);
      list.appendChild(row);
    }
  }
  if (app.dom.pluginRepoManageFilterBtn) {
    const menuOpen = app.dom.pluginRepoManageFilterMenu && !app.dom.pluginRepoManageFilterMenu.classList.contains("hidden");
    app.dom.pluginRepoManageFilterBtn.classList.toggle("active", selected.size > 0 || Boolean(menuOpen));
  }
}

function normalizePluginRepoApi(raw) {
  let base = String(raw || "").trim();
  if (!base) return "https://pluginserver.gotchat.ai/api";
  base = base.replace(/\/+$/, "");
  if (!base.endsWith("/api")) {
    base = `${base}/api`;
  }
  try {
    const url = new URL(base);
    if (["localhost", "127.0.0.1", "::1", "host.docker.internal"].includes(String(url.hostname || "").toLowerCase())) {
      return "https://pluginserver.gotchat.ai/api";
    }
  } catch {
    return "https://pluginserver.gotchat.ai/api";
  }
  return base;
}

function pluginRepoApi() {
  ensurePluginRepoState();
  return normalizePluginRepoApi(app.state.pluginRepo.apiBase);
}

function pluginRepoServerPath(path, params = {}) {
  const query = new URLSearchParams({ ...params, repo_api: pluginRepoApi() }).toString();
  return `${path}?${query}`;
}

function isLocalhostUrl(value) {
  if (!value) return false;
  try {
    const url = new URL(normalizeServerUrl(value));
    return ["localhost", "127.0.0.1", "::1"].includes(url.hostname);
  } catch {
    return false;
  }
}

function hostServiceUrl() {
  const override = normalizeServerUrl(app.state.remote.hostServiceUrl || "");
  const server = normalizeServerUrl(app.state.remote.serverUrl);
  const fallback = "http://127.0.0.1:8000";
  if (override) {
    if (!isLocalhostUrl(override)) return override;
    if (!server || isLocalhostUrl(server)) return server || override;
  }
  if (!server) return fallback;
  if (isLocalhostUrl(server)) return server;
  try {
    const url = new URL(server);
    url.port = "8765";
    return url.toString().replace(/\/+$/, "");
  } catch {
    return fallback;
  }
}

function clientServiceUrl() {
  const override = normalizeServerUrl(app.state.remote.clientServiceUrl || "");
  const server = normalizeServerUrl(app.state.remote.serverUrl);
  const fallback = "http://127.0.0.1:8766";
  if (override) {
    if (!isLocalhostUrl(override)) return override;
    if (!server || isLocalhostUrl(server)) return override;
  }
  if (!server) return fallback;
  if (window.__CHAT_JS_EMBED_CONFIG?.embedded && !isLocalhostUrl(server)) {
    return server;
  }
  try {
    const url = new URL(server);
    url.port = "8766";
    return url.toString().replace(/\/+$/, "");
  } catch {
    return fallback;
  }
}

function pluginRepoAssetUrl(pluginId, assetPath) {
  const base = pluginRepoApi().replace(/\/+$/, "");
  const qs = new URLSearchParams({ path: assetPath }).toString();
  return `${base}/plugin/${encodeURIComponent(pluginId)}/assets?${qs}`;
}

  function setActivePluginRepoTab(tabId) {
    if (!app.dom.pluginRepoTabs || !app.dom.pluginRepoPanels) return;
    const tabChanged = tabId !== pluginRepoLastTab;
    pluginRepoLastTab = tabId;
    app.dom.pluginRepoTabs.forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.pluginTab === tabId);
    });
    app.dom.pluginRepoPanels.forEach((panel) => {
      panel.classList.toggle("active", panel.dataset.pluginPanel === tabId);
    });
    ensurePluginRepoState();
    app.state.pluginRepo.activeTab = tabId;
    scheduleSave();
    if (tabId === "downloaded") {
      renderPluginRepoDownloaded();
      const now = Date.now();
      if (tabChanged || now - pluginRepoLastRefreshAt > 15000) {
        pluginRepoLastRefreshAt = now;
        void refreshPluginRepoServerState();
      }
    }
    if (tabId === "search") {
      const lastSearch = app.state.pluginRepo.lastSearch || [];
      if (tabChanged) {
        if (!lastSearch.length) {
          void performPluginRepoSearch();
        } else {
          renderPluginRepoSearchResults(lastSearch);
        }
      }
      if (lastSearch.length && !pluginRepoSearchRequirementsInitialized) {
        pluginRepoSearchRequirementsInitialized = true;
        void refreshPluginRepoRequirementLists(lastSearch, { force: true });
      }
    }
  }

  function renderPluginRepoPanel() {
    if (app.dom.pluginRepoApi) {
      ensurePluginRepoState();
      app.dom.pluginRepoApi.value = pluginRepoApi();
    }
    if (app.dom.pluginRepoManageSearch) {
      ensurePluginRepoState();
      app.dom.pluginRepoManageSearch.value = app.state.pluginRepo.manageSearch || "";
    }
    renderPluginRepoManageFilterMenu();
    if (app.dom.pluginRepoSearchFilter) {
      ensurePluginRepoState();
      app.dom.pluginRepoSearchFilter.value = app.state.pluginRepo.searchFilter || "top_rated";
    }
    const active = app.state.pluginRepo?.activeTab || "manage";
    setActivePluginRepoTab(active);
    if (active === "search" && app.dom.pluginRepoSearchResults) {
      const lastSearch = app.state.pluginRepo?.lastSearch || [];
      if (lastSearch.length && !app.dom.pluginRepoSearchResults.children.length) {
        renderPluginRepoSearchResults(lastSearch);
      }
    }
  }

  async function performPluginRepoSearch() {
    if (!app.dom.pluginRepoSearchInput || !app.dom.pluginRepoSearchStatus) return;
  const query = String(app.dom.pluginRepoSearchInput.value || "").trim();
  ensurePluginRepoState();
  void refreshPluginRepoServerState();
    if (query) {
      app.dom.pluginRepoSearchStatus.textContent = i18nTranslate("chat_js.plugins.searching", "Searching...");
    } else {
      const filter = app.state.pluginRepo.searchFilter || "top_rated";
      app.dom.pluginRepoSearchStatus.textContent =
        filter === "popular" ? "Loading popular plugins..." : "Loading top rated plugins...";
    }
    renderPluginRepoSearchResults([]);
    try {
      const data = query
        ? await apiJson(pluginRepoServerPath("/v1/plugin_repo/search", { q: query }))
        : await apiJson(pluginRepoServerPath("/v1/plugin_repo/approved"));
      const list = Array.isArray(data) ? data : [];
      ensurePluginRepoState();
      app.state.pluginRepo.lastSearch = list;
      app.lastPluginRepoSearch = list;
      app.state.pluginRepo.searchPage = 1;
      scheduleSave();
      if (query) {
        app.dom.pluginRepoSearchStatus.textContent = list.length ? `Found ${list.length} plugins.` : i18nTranslate("chat_js.plugins.no_results", "No results.");
      } else if (!list.length) {
        app.dom.pluginRepoSearchStatus.textContent = i18nTranslate("chat_js.plugins.no_results", "No results.");
      } else {
        const filter = app.state.pluginRepo.searchFilter || "top_rated";
        app.dom.pluginRepoSearchStatus.textContent =
          filter === "popular" ? "Popular plugins." : "Top rated plugins.";
      }
      renderPluginRepoSearchResults(list);
      void refreshPluginRepoRequirementLists(list, { force: true });
    } catch (err) {
      app.dom.pluginRepoSearchStatus.textContent = `Search failed: ${err.message || err}`;
    }
  }

  function renderPluginRepoSearchResults(list) {
    if (!app.dom.pluginRepoSearchResults) return;
    ensurePluginRepoState();
    const filter = app.state.pluginRepo.searchFilter || "top_rated";
    const source = Array.isArray(list) ? list : [];
    const sorted = sortPluginRepoResults(source, filter);
    const pageSize = app.state.pluginRepo.searchPageSize || 10;
    const total = sorted.length;
    if (app.dom.pluginRepoSearchPager) {
      app.dom.pluginRepoSearchPager.style.display = total > pageSize ? "flex" : "none";
    }
    const totalPages = total ? Math.ceil(total / pageSize) : 0;
    if (totalPages === 0) {
      app.state.pluginRepo.searchPage = 1;
    } else if (app.state.pluginRepo.searchPage > totalPages) {
      app.state.pluginRepo.searchPage = totalPages;
    }
    const page = Math.max(1, app.state.pluginRepo.searchPage || 1);
    const start = (page - 1) * pageSize;
    const items = sorted.slice(start, start + pageSize);
    if (app.dom.pluginRepoSearchPage) {
      app.dom.pluginRepoSearchPage.textContent = totalPages ? `Page ${page} of ${totalPages}` : "Page 0 of 0";
    }
    if (app.dom.pluginRepoSearchPrev) app.dom.pluginRepoSearchPrev.disabled = page <= 1;
    if (app.dom.pluginRepoSearchNext) app.dom.pluginRepoSearchNext.disabled = page >= totalPages;
    app.dom.pluginRepoSearchResults.innerHTML = "";
    for (const plugin of items) {
      const card = buildPluginRepoCard(plugin, {
        showDownload: true,
        showInstall: true,
        installLabelWhenInstalled: true,
        showRestart: true,
      });
      app.dom.pluginRepoSearchResults.appendChild(card);
    }
  }

  function isPluginRepoDownloadInFlight(id) {
    return pluginRepoDownloadInFlight.has(String(id));
  }

  function renderPluginRepoDownloaded() {
    if (!app.dom.pluginRepoDownloadResults || !app.dom.pluginRepoDownloadStatus) return;
    ensurePluginRepoState();
    const downloads = app.state.pluginRepo.downloads || [];
    const pageSize = app.state.pluginRepo.downloadedPageSize || 10;
    const total = downloads.length;
    if (app.dom.pluginRepoDownloadPager) {
      app.dom.pluginRepoDownloadPager.style.display = total > pageSize ? "flex" : "none";
    }
    const totalPages = total ? Math.ceil(total / pageSize) : 0;
    if (totalPages === 0) {
      app.state.pluginRepo.downloadedPage = 1;
    } else if (app.state.pluginRepo.downloadedPage > totalPages) {
      app.state.pluginRepo.downloadedPage = totalPages;
    }
    const page = Math.max(1, app.state.pluginRepo.downloadedPage || 1);
    const start = (page - 1) * pageSize;
    const items = downloads.slice(start, start + pageSize);
    app.dom.pluginRepoDownloadResults.innerHTML = "";
    if (!downloads.length) {
      app.dom.pluginRepoDownloadStatus.textContent = i18nTranslate("chat_js.plugins.no_downloaded", "No downloaded plugins yet.");
      if (app.dom.pluginRepoDownloadPage) app.dom.pluginRepoDownloadPage.textContent = "Page 0 of 0";
      if (app.dom.pluginRepoDownloadPrev) app.dom.pluginRepoDownloadPrev.disabled = true;
      if (app.dom.pluginRepoDownloadNext) app.dom.pluginRepoDownloadNext.disabled = true;
      return;
    }
    app.dom.pluginRepoDownloadStatus.textContent = `Showing ${items.length} of ${downloads.length} downloaded plugin(s).`;
    if (app.dom.pluginRepoDownloadPage) app.dom.pluginRepoDownloadPage.textContent = `Page ${page} of ${totalPages}`;
    if (app.dom.pluginRepoDownloadPrev) app.dom.pluginRepoDownloadPrev.disabled = page <= 1;
    if (app.dom.pluginRepoDownloadNext) app.dom.pluginRepoDownloadNext.disabled = page >= totalPages;
    for (const plugin of items) {
      const card = buildPluginRepoCard(plugin, {
        showDownload: false,
        showInstall: true,
        installLabelWhenInstalled: false,
        showRemove: true,
        showUninstall: true,
        showServerInstall: true,
        showUpdate: true,
        showRestart: true,
      });
      app.dom.pluginRepoDownloadResults.appendChild(card);
    }
  }

function sortPluginRepoResults(list, filter) {
  const items = Array.isArray(list) ? list.slice() : [];
    const ratingOf = (plugin) => {
      const raw = plugin.averageRating ?? plugin.AverageRating ?? 0;
      const val = Number(raw);
      return Number.isFinite(val) ? val : 0;
    };
    const downloadsOf = (plugin) => {
      const raw = plugin.downloads ?? plugin.Downloads ?? 0;
      const val = Number(raw);
      return Number.isFinite(val) ? val : 0;
    };
    if (filter === "popular") {
      return items.sort((a, b) => downloadsOf(b) - downloadsOf(a));
    }
  const filtered = items.filter((plugin) => ratingOf(plugin) >= 4);
  return filtered.sort((a, b) => ratingOf(b) - ratingOf(a));
}

function splitRequirementText(text) {
  if (!text) return [];
  const out = [];
  text
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .split("\n")
    .forEach((raw) => {
      let line = raw.trim();
      if (!line) return;
      line = line.replace(/^(?:-|\*|\d+\.)\s*/, "");
      line = line.replace(/^pip\s+install\s+/i, "");
      if (!line) return;
      line.split(",").forEach((part) => {
        const val = part.trim();
        if (val) out.push(val);
      });
    });
  return out;
}

function requirementSignature(items) {
  const list = Array.isArray(items) ? items : [];
  const normalized = Array.from(
    new Set(
      list
        .map((item) => String(item || "").trim().toLowerCase())
        .filter(Boolean)
    )
  ).sort();
  return normalized.join("|");
}

function pluginRepoHostServiceAvailable() {
  const url = hostServiceUrl();
  if (!url) return false;
  return Date.now() >= pluginRepoHostServiceDownUntil;
}

function pluginRepoUseServerGuiInstall() {
  ensurePluginRepoState();
  if (app.state.pluginRepo.serverInContainer) return false;
  if (app.state.pluginRepo.clientServiceAvailable) return false;
  return true;
}

function notePluginRepoHostServiceFailure(err) {
  const msg = String(err?.message || err || "");
  if (msg.includes("ERR_CONNECTION_FAILED") || msg.includes("Failed to fetch")) {
    pluginRepoHostServiceDownUntil = Date.now() + 60000;
  }
}

function schedulePluginRepoRequirementRender() {
  if (pluginRepoRequirementRenderTimer) return;
  pluginRepoRequirementRenderTimer = window.setTimeout(() => {
    pluginRepoRequirementRenderTimer = null;
    renderActivePluginRepoResults();
  }, 120);
}

function renderActivePluginRepoResults() {
  const active = app.state.pluginRepo?.activeTab || "manage";
  if (active === "search") {
    renderPluginRepoSearchResults(app.state.pluginRepo.lastSearch || []);
    return;
  }
  if (active === "downloaded") {
    renderPluginRepoDownloaded();
  }
}

function extractReadmeSection(content, sectionName) {
  if (!content || !sectionName) return "";
  const target = sectionName.trim().toLowerCase();
  const lines = String(content).replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
  const section = [];
  let inSection = false;
  for (const raw of lines) {
    const trimmed = raw.trim();
    if (trimmed.startsWith("==") && trimmed.endsWith("==") && !trimmed.startsWith("===")) {
      const name = trimmed.replace(/=/g, "").trim().toLowerCase();
      if (inSection) break;
      inSection = name === target;
      continue;
    }
    if (inSection) section.push(raw);
  }
  return section.join("\n").trim();
}

function extractServerRequirementsFromPlugin(plugin) {
  const parsed = plugin?.readmeParsed || plugin?.ReadmeParsed || {};
  let text = parsed.serverRequirements || parsed.ServerRequirements || "";
  if (!text) {
    const content = plugin?.readmeContent || plugin?.ReadmeContent || "";
    text = extractReadmeSection(content, "server requirements");
  }
  if (!text) {
    const downloads = app.state.pluginRepo?.downloads || [];
    const match = downloads.find((item) => String(item?.id) === String(plugin?.id));
    if (match) {
      const parsed2 = match.readmeParsed || match.ReadmeParsed || {};
      text = parsed2.serverRequirements || parsed2.ServerRequirements || "";
      if (!text) {
        const content2 = match.readmeContent || match.ReadmeContent || "";
        text = extractReadmeSection(content2, "server requirements");
      }
    }
  }
  return splitRequirementText(text);
}

function getServerRequirementsFromPlugin(plugin) {
  const id = String(plugin?.id || "");
  const updatedAt = pluginRepoUpdatedAt(plugin);
  if (id) {
    const cached = pluginRepoRequirementsCache.get(id);
    if (cached && cached.requirements && (!updatedAt || cached.updatedAt === updatedAt)) {
      return cached.requirements;
    }
  }
  return extractServerRequirementsFromPlugin(plugin);
}

function pluginRepoNeedsAttention(plugin) {
  const key = String(plugin?.id || "");
  if (pluginRepoRequirementSummary.has(key)) {
    const summary = pluginRepoRequirementSummary.get(key);
    if (summary?.serverMissing === null) {
      return false;
    }
    return Boolean(summary?.serverMissing);
  }
  return false;
}

function pluginRepoPackagesLabel(plugin) {
  const requirements = getServerRequirementsFromPlugin(plugin);
  const signature = requirementSignature(requirements);
  const key = String(plugin?.id || "");
  const summary = pluginRepoRequirementSummary.get(key);
  const updatedAt = pluginRepoUpdatedAt(plugin);
  const total = summary?.total;
  const missing = summary?.missing;
  if (!summary || missing === null) {
    return "Packages";
  }
  if (summary?.signature && signature && summary.signature !== signature) {
    return "Packages";
  }
  if (updatedAt && summary.updatedAt && summary.updatedAt !== updatedAt) {
    return "Packages";
  }
  if (Number.isFinite(total) && total > 0 && Number.isFinite(missing)) {
    const ok = Math.max(0, total - missing);
    return `Packages (${ok}/${total})`;
  }
  return "Packages";
}

function pluginRepoUpdatedAt(plugin) {
  return (
    plugin?.updatedAt ||
    plugin?.UpdatedAt ||
    plugin?.publishedAt ||
    plugin?.PublishedAt ||
    plugin?.createdAt ||
    plugin?.CreatedAt ||
    ""
  );
}

async function schedulePluginRepoRequirementCheck(plugin) {
  if (!hasPermission("plugins.manage.install", false)) return;
  const id = String(plugin?.id || "");
  if (!id || pluginRepoRequirementInFlight.has(id)) return;
  const updatedAt = pluginRepoUpdatedAt(plugin);
  if (pluginRepoRequirementSummary.has(id)) {
    const summary = pluginRepoRequirementSummary.get(id);
    const requirements = getServerRequirementsFromPlugin(plugin);
    const signature = requirementSignature(requirements);
    if (
      summary &&
      summary.serverMissing !== null &&
      (!updatedAt || summary.updatedAt === updatedAt) &&
      (!summary.signature || summary.signature === signature)
    ) {
      return;
    }
    if (summary && summary.serverMissing === null) {
      const lastCheck = summary.lastCheckedAt || 0;
      if (Date.now() - lastCheck < 60000 && (!summary.signature || summary.signature === signature)) {
        return;
      }
    }
  }
  const requirements = getServerRequirementsFromPlugin(plugin);
  const signature = requirementSignature(requirements);
  if (!requirements.length) {
    pluginRepoRequirementSummary.set(id, {
      serverMissing: false,
      serverTotal: 0,
      serverMissingCount: 0,
      total: 0,
      missing: 0,
      signature,
      updatedAt,
      lastCheckedAt: Date.now(),
    });
    return;
  }
  if (!pluginRepoHostServiceAvailable()) {
    pluginRepoRequirementSummary.set(id, {
      serverMissing: null,
      serverTotal: requirements.length,
      serverMissingCount: null,
      total: requirements.length,
      missing: null,
      signature,
      updatedAt,
      lastCheckedAt: Date.now(),
    });
    return;
  }
  pluginRepoRequirementInFlight.add(id);
  pluginRepoRequirementInFlightSignature.set(id, signature);
  hostServiceJson("/v1/plugin_repo/requirements_status", {
    method: "POST",
    body: { requirements },
  })
    .then((payload) => {
      const expectedSignature = pluginRepoRequirementInFlightSignature.get(id);
      const currentSignature = requirementSignature(getServerRequirementsFromPlugin(plugin));
      if (expectedSignature && currentSignature && expectedSignature !== currentSignature) {
        pluginRepoRequirementSummary.delete(id);
        return;
      }
      const items = Array.isArray(payload?.items) ? payload.items : [];
      const statusMap = new Map();
      for (const item of items) {
        if (!item || !item.requirement) continue;
        statusMap.set(String(item.requirement).trim().toLowerCase(), item);
      }
      let missingCount = 0;
      for (const req of requirements) {
        const info = statusMap.get(String(req).trim().toLowerCase()) || {};
        if (info.installed || info.included_in_python) continue;
        missingCount += 1;
      }
      pluginRepoRequirementSummary.set(id, {
        serverMissing: missingCount > 0,
        serverTotal: requirements.length,
        serverMissingCount: missingCount,
        total: requirements.length,
        missing: missingCount,
        signature,
        updatedAt,
        lastCheckedAt: Date.now(),
      });
    })
    .catch((err) => {
      notePluginRepoHostServiceFailure(err);
      const expectedSignature = pluginRepoRequirementInFlightSignature.get(id);
      const currentSignature = requirementSignature(getServerRequirementsFromPlugin(plugin));
      if (expectedSignature && currentSignature && expectedSignature !== currentSignature) {
        pluginRepoRequirementSummary.delete(id);
        return;
      }
      pluginRepoRequirementSummary.set(id, {
        serverMissing: null,
        serverTotal: requirements.length,
        serverMissingCount: null,
        total: requirements.length,
        missing: null,
        signature,
        updatedAt,
        lastCheckedAt: Date.now(),
      });
    })
    .finally(() => {
      pluginRepoRequirementInFlight.delete(id);
      pluginRepoRequirementInFlightSignature.delete(id);
      if (pluginRepoRequirementInFlight.size === 0) {
        schedulePluginRepoRequirementRender();
      }
    });
}

function buildPluginRepoCard(plugin, options) {
  const opts = options || {};
  const card = document.createElement("div");
  card.className = "plugin-card";
  card.addEventListener("click", () => openPluginRepoDetail(plugin));

  const img = document.createElement("img");
  img.alt = plugin.name || "Plugin";
  const imgUrl = resolvePluginRepoImage(plugin);
  if (imgUrl) {
    img.src = imgUrl;
  }

  const body = document.createElement("div");

  const title = document.createElement("div");
  title.className = "plugin-card-title";
  title.textContent = plugin.name || "Untitled Plugin";

  const summary = document.createElement("div");
  summary.className = "plugin-card-summary";
  const summaryText = resolvePluginRepoSummary(plugin);
  summary.textContent = summaryText || plugin.description || "";

  const author = document.createElement("div");
  author.className = "plugin-card-author";
  const authorName = plugin.authorName || plugin.AuthorName || plugin.author || plugin.Author || "";
  author.textContent = authorName ? `By ${authorName}` : "";

  const meta = document.createElement("div");
  meta.className = "plugin-card-meta";
  const metaParts = [];
  const ratingRaw = plugin.averageRating ?? plugin.AverageRating ?? 0;
  const reviewCount = plugin.reviewCount ?? plugin.ReviewCount ?? 0;
  const rating = Number.isFinite(Number(ratingRaw)) ? Number(ratingRaw) : 0;
  if (reviewCount > 0) {
    metaParts.push(`Rating ${rating.toFixed(1)} (${reviewCount})`);
  } else {
    metaParts.push("No ratings");
  }
  const updatedAt = plugin.updatedAt || plugin.UpdatedAt || plugin.publishedAt || plugin.PublishedAt || plugin.createdAt || plugin.CreatedAt;
  if (updatedAt) {
    metaParts.push(`Updated ${formatPluginRepoDate(updatedAt)}`);
  }
  const version = plugin.version || plugin.Version || "";
  if (version) {
    metaParts.push(`Version ${version}`);
  }
  meta.textContent = metaParts.join(" | ");

  const actions = document.createElement("div");
  actions.className = "plugin-card-actions";
  const downloaded = isPluginRepoDownloaded(plugin.id);
  const installed = isPluginRepoInstalled(plugin.id);
  const serverInstalled = isPluginRepoServerInstalled(plugin.id);
  const hasServer = pluginRepoHasServerAny(plugin);
  const canInstallPlugins = hasPermission("plugins.manage.install", false);
  const canUninstallPlugins = hasPermission("plugins.manage.uninstall", false);
  const canUpgradePlugins = hasPermission("plugins.manage.upgrade", false);
  const canRestartPlugins = hasPermission("plugins.manage.restart", false);
  if (installed) {
    void schedulePluginRepoRequirementCheck(plugin);
  }

  if (opts.showDownload) {
    const downloading = isPluginRepoDownloadInFlight(plugin.id);
    const btn = document.createElement("button");
    btn.className = downloaded || downloading ? "ghost" : "primary";
    btn.textContent = downloading ? i18nTranslate("chat_js.plugins.downloading", "Downloading...") : downloaded ? i18nTranslate("chat_js.plugins.downloaded", "Downloaded") : i18nTranslate("chat_js.plugins.download", "Download");
    btn.disabled = downloaded || downloading;
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      void downloadPluginRepo(plugin);
    });
    actions.appendChild(btn);
  }

  if (opts.showInstall && canInstallPlugins) {
    const showInstalledLabel = opts.installLabelWhenInstalled !== false;
    if (!installed || showInstalledLabel) {
      const btn = document.createElement("button");
      btn.className = installed ? "ghost" : "primary";
      const label = installed
        ? "Installed"
        : hasServer && serverInstalled
          ? "Install client"
          : "Install";
      btn.textContent = label;
      const needsServerInstall = !isAdminUser() && hasServer && !serverInstalled;
      btn.disabled = installed || needsServerInstall;
      if (needsServerInstall) {
        btn.title = "Server install required";
      }
      btn.addEventListener("click", (event) => {
        event.stopPropagation();
        void installPluginRepo(plugin);
      });
      actions.appendChild(btn);
    }
  }

  if (opts.showUninstall && installed && canUninstallPlugins) {
    const btn = document.createElement("button");
    btn.className = "ghost";
    btn.textContent = i18nTranslate("chat_js.plugins.uninstall", "Uninstall");
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      uninstallPluginRepo(plugin);
    });
    actions.appendChild(btn);
  }

  if (opts.showServerInstall && installed && hasServer && !serverInstalled && canInstallPlugins) {
    const btn = document.createElement("button");
    btn.className = "ghost";
    btn.textContent = i18nTranslate("chat_js.plugins.install_server", "Install server");
    btn.disabled = false;
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      void installPluginRepoServerOnly(plugin);
    });
    actions.appendChild(btn);
  }

  if (opts.showUpdate && canUpgradePlugins && (installed || serverInstalled)) {
    const btn = document.createElement("button");
    btn.className = "ghost";
    btn.textContent = i18nTranslate("chat_js.plugins.check_updates", "Check for updates");
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      void checkPluginRepoUpdates(plugin);
    });
    actions.appendChild(btn);
  }

  const restartRequired = Boolean(app.state.pluginRepo.restartRequired);
  const restartState = pluginRepoRestartState.get(String(plugin?.id || ""));
  if (
    opts.showRestart &&
    canRestartPlugins &&
    hasServer &&
    serverInstalled &&
    installed &&
    (isPluginRepoRestartRequiredForPlugin(plugin?.id) || restartState)
  ) {
    const btn = document.createElement("button");
    btn.className = "ghost";
    if (restartState === "restarting") {
      btn.textContent = i18nTranslate("chat_js.plugins.restarting", "Restarting...");
      btn.disabled = true;
    } else if (restartState === "done") {
      btn.textContent = i18nTranslate("chat_js.common.done", "Done");
      btn.disabled = true;
    } else {
      btn.textContent = i18nTranslate("chat_js.plugins.server_restart_required", "Server restart required");
    }
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      void requestPluginRepoServerRestart(plugin);
    });
    actions.appendChild(btn);
  }

  if (opts.showRemove && canUninstallPlugins) {
    if (!installed && !serverInstalled) {
      const btn = document.createElement("button");
      btn.className = "ghost";
      btn.textContent = i18nTranslate("chat_js.common.remove", "Remove");
      btn.addEventListener("click", (event) => {
        event.stopPropagation();
        removePluginRepo(plugin);
      });
      actions.appendChild(btn);
    }
  }

  if (installed) {
    const btn = document.createElement("button");
    const needsAttention = pluginRepoNeedsAttention(plugin);
    btn.className = needsAttention ? "alert" : "ghost";
    btn.textContent = pluginRepoPackagesLabel(plugin);
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      void openPluginRepoRequirementsTodo(plugin);
    });
    actions.appendChild(btn);
  }

  body.appendChild(title);
  body.appendChild(summary);
  if (authorName) body.appendChild(author);
  if (meta.textContent) body.appendChild(meta);
  if (actions.children.length) body.appendChild(actions);

  card.appendChild(img);
  card.appendChild(body);
  return card;
}

function resolvePluginRepoSummary(plugin) {
  const parsed = plugin.readmeParsed || plugin.ReadmeParsed || {};
  return parsed.summary || parsed.Summary || plugin.summary || "";
}

function resolvePluginRepoImage(plugin) {
  const parsed = plugin.readmeParsed || plugin.ReadmeParsed || {};
  const screenshots = getPluginRepoScreenshots(parsed);
  const shot = screenshots.length ? getPluginRepoScreenshotFile(screenshots[0]) : "";
  if (shot) {
    return pluginRepoAssetUrl(plugin.id, `resources/${shot}`);
  }
  const media = plugin.media?.[0]?.s3Url || plugin.media?.[0]?.S3Url || plugin.Media?.[0]?.s3Url || plugin.Media?.[0]?.S3Url;
  return media || "";
}

function getPluginRepoScreenshots(parsed) {
  const shots = parsed?.screenshots || parsed?.Screenshots;
  return Array.isArray(shots) ? shots : [];
}

function getPluginRepoScreenshotFile(shot) {
  return shot?.file || shot?.File || "";
}

function getPluginRepoScreenshotCaption(shot) {
  return shot?.caption || shot?.Caption || "";
}

function formatPluginRepoDate(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString();
}


  async function refreshPluginRepoServerState(options = {}) {
    const forceRequirements = Boolean(options.forceRequirements);
    try {
      const downloads = await apiJson("/v1/plugin_repo/downloads");
      const installed = await apiJson("/v1/plugin_repo/installed");
      let clientInstalled = null;
      let clientAvailable = false;
      try {
        const client = await clientServiceJson("/v1/client/gui_js/installed");
        clientAvailable = true;
        if (client?.installed && typeof client.installed === "object") {
          clientInstalled = client.installed;
        }
      } catch (_err) {
        clientInstalled = null;
        clientAvailable = false;
      }
      ensurePluginRepoState();
      app.state.pluginRepo.downloads = Array.isArray(downloads?.downloads) ? downloads.downloads : [];
      app.state.pluginRepo.installedServer =
        installed?.server && typeof installed.server === "object" ? installed.server : {};
      app.state.pluginRepo.clientServiceAvailable = clientAvailable;
      app.state.pluginRepo.serverInContainer = Boolean(installed?.in_container);
      if (clientInstalled) {
        app.state.pluginRepo.installedClient = clientInstalled;
      } else if (!clientAvailable && !app.state.pluginRepo.serverInContainer) {
        app.state.pluginRepo.installedClient =
          installed?.gui_js && typeof installed.gui_js === "object" ? installed.gui_js : {};
      } else if (!app.state.pluginRepo.installedClient) {
        app.state.pluginRepo.installedClient = {};
      }
      app.state.pluginRepo.restartRequired = Boolean(installed?.restart_required);
    app.state.pluginRepo.restartPlugins = Array.isArray(installed?.restart_plugins)
      ? installed.restart_plugins.map((value) => String(value))
      : [];
    scheduleSave();
    renderPluginRepoDownloaded();
    void hydratePluginRepoRequirementSummary();
    void refreshPluginRepoRequirementLists(app.state.pluginRepo.downloads || [], {
      force: forceRequirements,
    });
  } catch (err) {
    if (app.dom.pluginRepoDownloadStatus) {
      app.dom.pluginRepoDownloadStatus.textContent = `Refresh failed: ${err.message || err}`;
    }
  }
}

async function refreshPluginRepoRequirementLists(list, options = {}) {
  ensurePluginRepoState();
  if (!hasPermission("plugins.manage.install", false)) return;
  const force = Boolean(options.force);
  const now = Date.now();
  const items = Array.isArray(list) ? list : [];
  const installedIds = new Set(Object.keys(app.state.pluginRepo.installedClient || {}));
  for (const plugin of items) {
    const id = String(plugin?.id || "");
    if (!id || !installedIds.has(id)) continue;
    const updatedAt = pluginRepoUpdatedAt(plugin);
    const cached = pluginRepoRequirementsCache.get(id);
    if (!force && cached && cached.requirements) {
      if (updatedAt && cached.updatedAt === updatedAt) {
        continue;
      }
      if (!updatedAt && cached.fetchedAt && now - cached.fetchedAt < 60000) {
        continue;
      }
    }
    try {
      const pluginData = await apiJson(pluginRepoServerPath(`/v1/plugin_repo/plugin/${id}`));
      const requirements = extractServerRequirementsFromPlugin(pluginData);
      pluginRepoRequirementsCache.set(id, { requirements, updatedAt, fetchedAt: now });
      pluginRepoRequirementSummary.delete(id);
    } catch (_err) {
      continue;
    }
  }
  schedulePluginRepoRequirementRender();
}

async function hydratePluginRepoRequirementSummary() {
  ensurePluginRepoState();
  if (!hasPermission("plugins.manage.install", false)) {
    for (const [key, summary] of pluginRepoRequirementSummary.entries()) {
      if (summary?.serverMissing !== null) {
        summary.serverMissing = null;
        pluginRepoRequirementSummary.set(key, summary);
      }
    }
    return;
  }
  const downloads = app.state.pluginRepo.downloads || [];
  const installedIds = new Set(Object.keys(app.state.pluginRepo.installedClient || {}));
  let updated = false;
  for (const plugin of downloads) {
    const id = String(plugin?.id || "");
    if (!id || !installedIds.has(id)) continue;
    const requirements = getServerRequirementsFromPlugin(plugin);
    const signature = requirementSignature(requirements);
    const updatedAt = pluginRepoUpdatedAt(plugin);
    const existing = pluginRepoRequirementSummary.get(id);
    if (existing && existing.serverMissing !== null && (!updatedAt || existing.updatedAt === updatedAt)) {
      continue;
    }
    if (existing && existing.serverMissing === null) {
      const lastCheck = existing.lastCheckedAt || 0;
      if (Date.now() - lastCheck < 60000) {
        continue;
      }
    }
    if (!requirements.length) {
      pluginRepoRequirementSummary.set(id, {
        serverMissing: false,
        serverTotal: 0,
        serverMissingCount: 0,
        total: 0,
        missing: 0,
        signature,
        updatedAt,
        lastCheckedAt: Date.now(),
      });
      updated = true;
      continue;
    }
    if (!pluginRepoHostServiceAvailable()) {
      pluginRepoRequirementSummary.set(id, {
        serverMissing: null,
        serverTotal: requirements.length,
        serverMissingCount: null,
        total: requirements.length,
        missing: null,
        signature,
        updatedAt,
        lastCheckedAt: Date.now(),
      });
      updated = true;
      continue;
    }
    try {
      const payload = await hostServiceJson("/v1/plugin_repo/requirements_status", {
        method: "POST",
        body: { requirements },
      });
      const items = Array.isArray(payload?.items) ? payload.items : [];
      const statusMap = new Map();
      for (const item of items) {
        if (!item || !item.requirement) continue;
        statusMap.set(String(item.requirement).trim().toLowerCase(), item);
      }
      let missingCount = 0;
      for (const req of requirements) {
        const info = statusMap.get(String(req).trim().toLowerCase()) || {};
        if (info.installed || info.included_in_python) continue;
        missingCount += 1;
      }
      pluginRepoRequirementSummary.set(id, {
        serverMissing: missingCount > 0,
        serverTotal: requirements.length,
        serverMissingCount: missingCount,
        total: requirements.length,
        missing: missingCount,
        signature,
        updatedAt,
        lastCheckedAt: Date.now(),
      });
      updated = true;
    } catch (_err) {
      notePluginRepoHostServiceFailure(_err);
      pluginRepoRequirementSummary.set(id, {
        serverMissing: null,
        serverTotal: requirements.length,
        serverMissingCount: null,
        total: requirements.length,
        missing: null,
        signature,
        updatedAt,
        lastCheckedAt: Date.now(),
      });
      updated = true;
    }
  }
  if (updated) {
    schedulePluginRepoRequirementRender();
  }
}

function isPluginRepoDownloaded(id) {
  ensurePluginRepoState();
  return (app.state.pluginRepo.downloads || []).some((p) => String(p.id) === String(id));
}

function isPluginRepoInstalled(id) {
  ensurePluginRepoState();
  return Boolean(app.state.pluginRepo.installedClient?.[String(id)]);
}

function isPluginRepoServerInstalled(id) {
  ensurePluginRepoState();
  return Boolean(app.state.pluginRepo.installedServer?.[String(id)]);
}

function isPluginRepoRestartRequiredForPlugin(id) {
  ensurePluginRepoState();
  if (!app.state.pluginRepo.restartRequired) return false;
  const plugins = app.state.pluginRepo.restartPlugins || [];
  if (!plugins.length) return true;
  return plugins.includes(String(id));
}

function pluginRepoHasServer(plugin) {
  if (!plugin || typeof plugin !== "object") return false;
  if (plugin.hasServer !== undefined) return Boolean(plugin.hasServer);
  if (plugin.HasServer !== undefined) return Boolean(plugin.HasServer);
  const folders = plugin.serverFolders || plugin.ServerFolders;
  return Array.isArray(folders) && folders.length > 0;
}

function pluginRepoHasServerAny(plugin) {
  if (pluginRepoHasServer(plugin)) return true;
  const downloads = app.state.pluginRepo?.downloads || [];
  const match = downloads.find((item) => String(item.id) === String(plugin?.id));
  return pluginRepoHasServer(match || {});
}

function isAdminUser() {
  return String(app.state.auth.role || "").toLowerCase() === "admin";
}

async function downloadPluginRepo(plugin) {
  ensurePluginRepoState();
  if (!plugin?.id) return;
  const key = String(plugin.id);
  if (pluginRepoDownloadInFlight.has(key)) return;
  try {
    pluginRepoDownloadInFlight.add(key);
    renderPluginRepoSearchResults(app.state.pluginRepo.lastSearch || []);
    renderPluginRepoDownloaded();
    await apiJson("/v1/plugin_repo/download", {
      method: "POST",
      body: { plugin_id: plugin.id, repo_api: pluginRepoApi() },
    });
    await refreshPluginRepoServerState();
  } catch (err) {
    if (app.dom.pluginRepoSearchStatus) {
      app.dom.pluginRepoSearchStatus.textContent = `Download failed: ${err.message || err}`;
    }
  } finally {
    pluginRepoDownloadInFlight.delete(key);
    renderPluginRepoSearchResults(app.state.pluginRepo.lastSearch || []);
    renderPluginRepoDownloaded();
  }
}

  async function installPluginRepo(plugin) {
    if (!plugin?.id) return;
    if (!hasPermission("plugins.manage.install", false)) {
      alert("Install permission required.");
      return;
    }
    try {
      const serverInstalled = isPluginRepoServerInstalled(plugin.id);
      const hasServer = pluginRepoHasServerAny(plugin);
      const useServerGuiInstall = pluginRepoUseServerGuiInstall();
      if (!serverInstalled && hasServer) {
        await hostServiceJson("/v1/plugin_repo/install", {
          method: "POST",
          body: { plugin_id: plugin.id, repo_api: pluginRepoApi() },
        });
      }
      if (useServerGuiInstall) {
        const res = await apiJson("/v1/plugin_repo/install_gui_js", {
          method: "POST",
          body: { plugin_id: plugin.id, repo_api: pluginRepoApi() },
        });
        if (!res?.ok && res?.installed === undefined) {
          throw new Error("Client install failed");
        }
      } else {
        const res = await clientServiceJson("/v1/client/gui_js/install", {
          method: "POST",
          body: { plugin_id: plugin.id, repo_api: pluginRepoApi() },
        });
        if (!res?.ok) {
          throw new Error("Client install failed");
        }
      }
      await refreshPluginRepoServerState();
      await refreshGuiPluginsDiscovery();
    } catch (err) {
      alert(`Install failed: ${err.message || err}`);
    }
  renderPluginRepoSearchResults(app.state.pluginRepo.lastSearch || []);
}

async function installPluginRepoServerOnly(plugin) {
  if (!plugin?.id) return;
  if (!hasPermission("plugins.manage.install", false)) {
    alert("Install permission required.");
    return;
  }
  try {
    await hostServiceJson("/v1/plugin_repo/install", {
      method: "POST",
      body: { plugin_id: plugin.id, repo_api: pluginRepoApi() },
    });
    await refreshPluginRepoServerState();
  } catch (err) {
    alert(`Server install failed: ${err.message || err}`);
  }
  renderPluginRepoSearchResults(app.state.pluginRepo.lastSearch || []);
}

async function requestPluginRepoServerRestart(plugin) {
  if (!plugin?.id) return false;
  if (!hasPermission("plugins.manage.restart", false)) {
    alert("Restart permission required.");
    return false;
  }
  try {
    pluginRepoRestartState.set(String(plugin.id), "restarting");
    renderPluginRepoSearchResults(app.state.pluginRepo.lastSearch || []);
    renderPluginRepoDownloaded();
    await hostServiceJson("/v1/plugin_repo/restart_server", {
      method: "POST",
      body: { plugin_id: plugin.id, reason: "server_restart_required" },
    });
    const online = await waitForPluginRepoServerOnline();
    if (!online) {
      pluginRepoRestartState.delete(String(plugin.id));
      renderPluginRepoSearchResults(app.state.pluginRepo.lastSearch || []);
      renderPluginRepoDownloaded();
      return false;
    }
    pluginRepoRestartState.set(String(plugin.id), "done");
    renderPluginRepoSearchResults(app.state.pluginRepo.lastSearch || []);
    renderPluginRepoDownloaded();
    setTimeout(() => {
      pluginRepoRestartState.delete(String(plugin.id));
      renderPluginRepoSearchResults(app.state.pluginRepo.lastSearch || []);
      renderPluginRepoDownloaded();
    }, 3000);
    return true;
  } catch (err) {
    const msg = `Restart failed: ${err.message || err}`;
    if (app.dom.pluginRepoSearchStatus) app.dom.pluginRepoSearchStatus.textContent = msg;
    if (app.dom.pluginRepoDownloadStatus) app.dom.pluginRepoDownloadStatus.textContent = msg;
    pluginRepoRestartState.delete(String(plugin.id));
    renderPluginRepoSearchResults(app.state.pluginRepo.lastSearch || []);
    renderPluginRepoDownloaded();
    return false;
  }
}

async function waitForPluginRepoServerOnline() {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  await sleep(2500);
  let sawDown = false;
  for (let attempt = 0; attempt < 90; attempt += 1) {
    try {
      await apiJson("/v1/plugin_repo/status");
      if (sawDown) {
        await refreshPluginRepoServerState();
        return true;
      }
    } catch {
      sawDown = true;
    }
    await sleep(1000);
  }
  return false;
}

function removePluginRepo(plugin) {
  if (!plugin?.id) return;
  if (!hasPermission("plugins.manage.uninstall", false)) {
    alert("Uninstall permission required.");
    return;
  }
  if (isPluginRepoInstalled(plugin.id)) return;
  void hostServiceJson("/v1/plugin_repo/remove", {
    method: "POST",
    body: { plugin_id: plugin.id },
  })
    .then(() => refreshPluginRepoServerState())
    .catch((err) => {
      alert(`Remove failed: ${err.message || err}`);
    })
    .finally(() => {
      renderPluginRepoSearchResults(app.state.pluginRepo.lastSearch || []);
    });
}

function uninstallPluginRepo(plugin) {
  if (!plugin?.id) return;
  if (!hasPermission("plugins.manage.uninstall", false)) {
    alert("Uninstall permission required.");
    return;
  }
  const useServerGuiInstall = pluginRepoUseServerGuiInstall();
  const actions = [];
  const errors = [];
  if (hasPermission("plugins.manage.uninstall", false)) {
    actions.push(
      hostServiceJson("/v1/plugin_repo/uninstall", {
        method: "POST",
        body: { plugin_id: plugin.id },
      }).catch((err) => {
        errors.push(`Server uninstall failed: ${err.message || err}`);
      })
    );
  }
  if (useServerGuiInstall) {
    actions.push(
      apiJson("/v1/plugin_repo/uninstall_gui_js", {
        method: "POST",
        body: { plugin_id: plugin.id },
      }).catch((err) => {
        errors.push(`Client uninstall failed: ${err.message || err}`);
      })
    );
  } else {
    actions.push(
      clientServiceJson("/v1/client/gui_js/uninstall", {
        method: "POST",
        body: { plugin_id: plugin.id },
      }).catch((err) => {
        errors.push(`Client uninstall failed: ${err.message || err}`);
      })
    );
  }
  void Promise.allSettled(actions)
    .then(() => refreshPluginRepoServerState())
    .then(() => refreshGuiPluginsDiscovery())
    .then(() => {
      if (errors.length) {
        const msg = errors.join(" ");
        if (app.dom.pluginRepoSearchStatus) app.dom.pluginRepoSearchStatus.textContent = msg;
        if (app.dom.pluginRepoDownloadStatus) app.dom.pluginRepoDownloadStatus.textContent = msg;
      }
    })
    .finally(() => {
      renderPluginRepoSearchResults(app.state.pluginRepo.lastSearch || []);
    });
}

async function checkPluginRepoUpdates(plugin) {
  if (!plugin?.id) return;
  if (!hasPermission("plugins.manage.upgrade", false)) {
    alert("Update permission required.");
    return;
  }
  try {
    const payload = await apiJson("/v1/plugin_repo/check_update", {
      method: "POST",
      body: { plugin_id: plugin.id, repo_api: pluginRepoApi() },
    });
    const latestVersion = payload?.latest_version || payload?.latestVersion || "";
    const currentVersion = payload?.current_version || payload?.currentVersion || "";
    if (!latestVersion || latestVersion === currentVersion) {
      alert("No updates available.");
      return;
    }
    const ok = confirm(`Update available: ${currentVersion} -> ${latestVersion}. Download now?`);
    if (!ok) return;
    await downloadPluginRepo(plugin);
    await refreshPluginRepoServerState();
    renderPluginRepoSearchResults(app.state.pluginRepo.lastSearch || []);
  } catch (err) {
    alert(`Update check failed: ${err.message || err}`);
  }
}

let pluginRepoDetailModal = null;
let pluginRepoRequirementsModal = null;

async function openPluginRepoDetail(plugin) {
  if (!plugin?.id) return;
  if (pluginRepoDetailModal) pluginRepoDetailModal.remove();
  pluginRepoDetailModal = document.createElement("div");
  pluginRepoDetailModal.className = "plugin-repo-modal";
  pluginRepoDetailModal.innerHTML = `
    <div class="plugin-repo-modal-card">
      <div class="plugin-repo-modal-header">
        <div class="llm-chat-modal-title">${escapeHtml(plugin.name || "Plugin")}</div>
        <button class="ghost" data-close>Close</button>
      </div>
      <div class="plugin-repo-modal-body">
        <div class="plugin-detail-tabs">
          <button class="plugin-detail-tab active" data-tab="overview">Overview</button>
          <button class="plugin-detail-tab" data-tab="files">Files</button>
          <button class="plugin-detail-tab" data-tab="reviews">Reviews</button>
          <button class="plugin-detail-tab" data-tab="bugs">Bugs</button>
          <button class="plugin-detail-tab" data-tab="git">Git Log</button>
        </div>
        <div class="plugin-detail-section active" data-section="overview"></div>
        <div class="plugin-detail-section" data-section="files"></div>
        <div class="plugin-detail-section" data-section="reviews"></div>
        <div class="plugin-detail-section" data-section="bugs"></div>
      <div class="plugin-detail-section" data-section="git"></div>
      </div>
    </div>`;
  getOverlayMount().appendChild(pluginRepoDetailModal);
  pluginRepoDetailModal.querySelector("[data-close]").addEventListener("click", () => {
    pluginRepoDetailModal.remove();
  });
  pluginRepoDetailModal.addEventListener("click", (event) => {
    if (event.target === pluginRepoDetailModal) {
      pluginRepoDetailModal.remove();
    }
  });
  pluginRepoDetailModal.querySelectorAll(".plugin-detail-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;
      pluginRepoDetailModal
        .querySelectorAll(".plugin-detail-tab")
        .forEach((b) => b.classList.toggle("active", b === btn));
      pluginRepoDetailModal
        .querySelectorAll(".plugin-detail-section")
        .forEach((section) => {
          section.classList.toggle("active", section.dataset.section === tab);
        });
    });
  });

  await loadPluginRepoDetail(plugin.id);
}

async function openPluginRepoRequirementsTodo(plugin) {
  if (!plugin?.id) return;
  if (pluginRepoRequirementsModal) pluginRepoRequirementsModal.remove();
  pluginRepoRequirementsModal = document.createElement("div");
  pluginRepoRequirementsModal.className = "plugin-repo-modal";
  pluginRepoRequirementsModal.innerHTML = `
    <div class="plugin-repo-modal-card">
      <div class="plugin-repo-modal-header">
        <div class="llm-chat-modal-title">Requirements: ${escapeHtml(plugin.name || "Plugin")}</div>
        <button class="ghost" data-close>Close</button>
      </div>
      <div class="plugin-repo-modal-body">
        <div class="requirements-panel"></div>
      </div>
    </div>`;
  getOverlayMount().appendChild(pluginRepoRequirementsModal);
  pluginRepoRequirementsModal.querySelector("[data-close]").addEventListener("click", () => {
    pluginRepoRequirementsModal.remove();
  });
  pluginRepoRequirementsModal.addEventListener("click", (event) => {
    if (event.target === pluginRepoRequirementsModal) {
      pluginRepoRequirementsModal.remove();
    }
  });
  const panel = pluginRepoRequirementsModal.querySelector(".requirements-panel");
  panel.innerHTML = "<div class=\"muted\">Loading...</div>";
  try {
    const pluginData = await apiJson(pluginRepoServerPath(`/v1/plugin_repo/plugin/${plugin.id}`));
    panel.innerHTML = "";
    const parsed = pluginData.readmeParsed || pluginData.ReadmeParsed || {};
    await renderPluginRepoRequirementsTodo(panel, pluginData, parsed, "server");
    if (!panel.children.length) {
      panel.innerHTML = "<div class=\"muted\">No requirements listed.</div>";
    }
  } catch (err) {
    panel.innerHTML = `<div class="muted">Failed to load requirements.</div>`;
  }
}

async function loadPluginRepoDetail(pluginId) {
  const modal = pluginRepoDetailModal;
  if (!modal) return;
  const overview = modal.querySelector('[data-section="overview"]');
  const files = modal.querySelector('[data-section="files"]');
  const reviews = modal.querySelector('[data-section="reviews"]');
  const bugs = modal.querySelector('[data-section="bugs"]');
  const git = modal.querySelector('[data-section="git"]');
  try {
    const [plugin, reviewsData, bugsData, filesData, gitData] = await Promise.all([
      apiJson(pluginRepoServerPath(`/v1/plugin_repo/plugin/${pluginId}`)),
      apiJson(pluginRepoServerPath(`/v1/plugin_repo/reviews/${pluginId}`)).catch(() => []),
      apiJson(pluginRepoServerPath(`/v1/plugin_repo/bugs/${pluginId}`)).catch(() => []),
      apiJson(pluginRepoServerPath(`/v1/plugin_repo/files/${pluginId}`)).catch(() => []),
      apiJson(pluginRepoServerPath(`/v1/plugin_repo/gitlog/${pluginId}`)).catch(() => []),
    ]);

    await renderPluginRepoOverview(overview, plugin);
    renderPluginRepoFiles(files, pluginId, filesData);
    renderPluginRepoCards(reviews, reviewsData, formatReviewCard);
    renderPluginRepoCards(bugs, bugsData, formatBugCard);
    renderPluginRepoCards(git, gitData, formatGitCard);
  } catch (err) {
    overview.innerHTML = `<div class="muted">Failed to load plugin.</div>`;
  }
}

async function renderPluginRepoOverview(container, plugin) {
  container.innerHTML = "";
  const parsed = plugin.readmeParsed || plugin.ReadmeParsed || {};
  const screenshots = getPluginRepoScreenshots(parsed);
  const addCard = (title, content) => {
    if (!content) return;
    const card = document.createElement("div");
    card.className = "plugin-detail-card";
    card.innerHTML = `<h4>${escapeHtml(title)}</h4><p>${escapeHtml(content).replace(/\n/g, "<br>")}</p>`;
    container.appendChild(card);
  };
  const authorName = plugin.authorName || plugin.AuthorName || "";
  if (authorName) addCard("Author", authorName);
  addCard("Summary", parsed.summary || parsed.Summary || "");
  addCard("Description", parsed.description || parsed.Description || "");
  addCard("Installation", parsed.installation || parsed.Installation || "");
  const faqItems = parsed.faq || parsed.Faq || [];
  if (faqItems.length) {
    const lines = faqItems
      .map((item) => `- ${item.question || item.Question}\n  ${item.answer || item.Answer || ""}`)
      .join("\n");
    addCard("FAQ", lines);
  }
  const changelog = parsed.changelog || parsed.Changelog || [];
  if (changelog.length) {
    const lines = changelog.map((item) => `${item.version || item.Version}:\n${item.notes || item.Notes || ""}`).join("\n");
    addCard("Changelog", lines);
  }
  await renderPluginRepoRequirementsStatus(container, plugin, parsed, "server");
  addCard("Requirements", parsed.requirements || parsed.Requirements || "");
  addCard("Special Note on Requirements", parsed.specialNoteOnRequirements || parsed.SpecialNoteOnRequirements || "");

  if (screenshots.length) {
    let index = 0;
    const gallery = document.createElement("div");
    gallery.className = "plugin-detail-gallery";
    const prev = document.createElement("button");
    prev.className = "ghost";
    prev.textContent = i18nTranslate("chat_js.common.prev", "Prev");
    const next = document.createElement("button");
    next.className = "ghost";
    next.textContent = i18nTranslate("chat_js.common.next", "Next");
    const img = document.createElement("img");
    const caption = document.createElement("div");
    const update = () => {
      const shot = screenshots[index];
      const file = getPluginRepoScreenshotFile(shot);
      img.src = pluginRepoAssetUrl(plugin.id, `resources/${file}`);
      caption.textContent = getPluginRepoScreenshotCaption(shot);
    };
    prev.addEventListener("click", () => {
      index = (index - 1 + screenshots.length) % screenshots.length;
      update();
    });
    next.addEventListener("click", () => {
      index = (index + 1) % screenshots.length;
      update();
    });
    update();
    container.appendChild(gallery);
    gallery.appendChild(prev);
    const frame = document.createElement("div");
    frame.appendChild(img);
    frame.appendChild(caption);
    gallery.appendChild(frame);
    gallery.appendChild(next);
  }
}

async function renderPluginRepoRequirementsTodo(container, plugin, parsed, kind) {
  const isServer = kind === "server";
  const title = isServer ? "Server Requirements" : "Client Requirements";
  const rawText = isServer
    ? parsed.serverRequirements || parsed.ServerRequirements || ""
    : parsed.clientRequirements || parsed.ClientRequirements || "";
  if (!rawText) return;
  const requirements = splitRequirementText(rawText);
  if (!requirements.length) return;

  let items = [];
  if (isServer) {
    if (hasPermission("plugins.manage.install", false)) {
      try {
        const payload = await hostServiceJson("/v1/plugin_repo/requirements_status", {
          method: "POST",
          body: { requirements },
        });
        items = Array.isArray(payload?.items) ? payload.items : [];
      } catch (_err) {
        items = [];
      }
    }
  } else {
    try {
      const payload = await clientServiceJson("/v1/client/requirements_status", {
        method: "POST",
        body: { requirements },
      });
      items = Array.isArray(payload?.items) ? payload.items : [];
    } catch (_err) {
      items = [];
    }
  }

  const statusMap = new Map();
  items.forEach((item) => {
    if (item && item.requirement) {
      statusMap.set(item.requirement, item);
    }
  });

  if (items.length) {
    let missing = false;
    for (const req of requirements) {
      const info = statusMap.get(req) || {};
      if (!info.installed && !info.included_in_python) {
        missing = true;
        break;
      }
    }
    const key = String(plugin?.id || "");
    const summary = pluginRepoRequirementSummary.get(key) || {};
    if (isServer) {
      summary.serverMissing = Boolean(missing);
    } else {
      summary.clientMissing = Boolean(missing);
    }
    pluginRepoRequirementSummary.set(key, summary);
  } else {
    const key = String(plugin?.id || "");
    const summary = pluginRepoRequirementSummary.get(key) || {};
    if (isServer) {
      summary.serverMissing = null;
    } else {
      summary.clientMissing = null;
    }
    pluginRepoRequirementSummary.set(key, summary);
  }

  const card = document.createElement("div");
  card.className = "plugin-detail-card requirements-card";

  const heading = document.createElement("h4");
  heading.textContent = title;
  card.appendChild(heading);

  const list = document.createElement("div");
  list.className = "requirements-list";
  const missingBoxes = [];

  requirements.forEach((req) => {
    const info = statusMap.get(req) || {};
    const row = document.createElement("div");
    row.className = "requirements-item";
    if (info.installed) {
      row.innerHTML = `<span class="req-check">✓</span><span>${escapeHtml(req)}</span>`;
    } else if (info.included_in_python) {
      row.innerHTML = `<span>${escapeHtml(req)}</span><span class="req-note">(included in python)</span>`;
    } else {
      const label = document.createElement("label");
      label.className = "req-missing";
      const box = document.createElement("input");
      box.type = "checkbox";
      if (isServer && !hasPermission("plugins.manage.install", false)) {
        box.disabled = true;
      }
      const span = document.createElement("span");
      span.textContent = req;
      const missingTag = document.createElement("span");
      missingTag.className = "req-missing-tag";
      missingTag.textContent = "(missing)";
      label.appendChild(box);
      label.appendChild(span);
      label.appendChild(missingTag);
      row.appendChild(label);
      missingBoxes.push(box);
    }
    list.appendChild(row);
  });

  if (!missingBoxes.length && items.length) {
    const done = document.createElement("div");
    done.className = "req-note";
    done.textContent = "All requirements satisfied.";
    list.appendChild(done);
  }

  card.appendChild(list);

  const actions = document.createElement("div");
  actions.className = "requirements-actions";
  const installBtn = document.createElement("button");
  installBtn.className = "primary";
  installBtn.textContent = "Install selected";
  const installAdminLocked = isServer && !hasPermission("plugins.manage.install", false);
  if (!missingBoxes.length) installBtn.style.display = "none";
  if (installAdminLocked) {
    installBtn.disabled = true;
    installBtn.title = "Install permission required";
  }
  const updateInstallState = () => {
    if (!missingBoxes.length) return;
    if (installAdminLocked) return;
    const hasSelected = missingBoxes.some((box) => box.checked);
    installBtn.disabled = !hasSelected;
    installBtn.title = hasSelected ? "" : "Select at least one package.";
  };
  missingBoxes.forEach((box) => {
    box.addEventListener("change", updateInstallState);
  });
  updateInstallState();
  installBtn.addEventListener("click", async (event) => {
    event.stopPropagation();
    const selected = missingBoxes
      .filter((box) => box.checked)
      .map((box) => box.nextSibling?.textContent || "")
      .filter(Boolean);
    if (!selected.length) {
      alert("Select at least one package.");
      return;
    }
      try {
        if (isServer) {
          if (!hasPermission("plugins.manage.install", false)) throw new Error("Install permission required");
          await hostServiceJson("/v1/plugin_repo/install_packages", {
            method: "POST",
            body: { packages: selected, plugin_id: plugin.id },
          });
          await refreshPluginRepoServerState();
        } else {
          await clientServiceJson("/v1/client/install_packages", {
            method: "POST",
            body: { packages: selected },
          });
        }
        try {
          const pluginData = await apiJson(pluginRepoServerPath(`/v1/plugin_repo/plugin/${plugin.id}`));
          const nextParsed = pluginData.readmeParsed || pluginData.ReadmeParsed || {};
          container.innerHTML = "";
          await renderPluginRepoRequirementsTodo(container, pluginData, nextParsed, kind);
        } catch (_err) {
          // fallback to stale view if refresh fails
        }
        await loadPluginRepoDetail(plugin.id);
        renderPluginRepoSearchResults(app.state.pluginRepo.lastSearch || []);
        renderPluginRepoDownloaded();
      } catch (err) {
        alert(`Install failed: ${err.message || err}`);
      }
  });
  if (missingBoxes.length) {
    actions.appendChild(installBtn);
  }

  if (isServer) {
    const restartBtn = document.createElement("button");
    restartBtn.className = "ghost";
    restartBtn.textContent = i18nTranslate("chat_js.plugins.server_restart_required", "Server restart required");
    if (!hasPermission("plugins.manage.restart", false)) {
      restartBtn.disabled = true;
      restartBtn.title = "Restart permission required";
    } else if (!isPluginRepoRestartRequiredForPlugin(plugin.id)) {
      restartBtn.disabled = true;
    }
    restartBtn.addEventListener("click", async (event) => {
      event.stopPropagation();
      if (restartBtn.disabled) return;
      const baseText = restartBtn.textContent;
      const spinner = document.createElement("span");
      spinner.className = "btn-spinner";
      restartBtn.classList.add("btn-loading");
      restartBtn.textContent = "Restarting";
      restartBtn.appendChild(spinner);
      restartBtn.disabled = true;
      const ok = await requestPluginRepoServerRestart(plugin);
      restartBtn.classList.remove("btn-loading");
      if (ok) {
        restartBtn.textContent = "Restarted";
        restartBtn.disabled = true;
      } else {
        restartBtn.textContent = baseText || i18nTranslate("chat_js.plugins.server_restart_required", "Server restart required");
        restartBtn.disabled = false;
      }
    });
    if (missingBoxes.length) {
      actions.appendChild(restartBtn);
    }
  } else {
    const note = document.createElement("span");
    note.className = "req-note";
    note.textContent = "Restart app after installation.";
    if (missingBoxes.length) {
      actions.appendChild(note);
    }
  }

  card.appendChild(actions);
  container.appendChild(card);
}

async function renderPluginRepoRequirementsStatus(container, plugin, parsed, kind) {
  const isServer = kind === "server";
  const title = isServer ? "Server Requirements" : "Client Requirements";
  const rawText = isServer
    ? parsed.serverRequirements || parsed.ServerRequirements || ""
    : parsed.clientRequirements || parsed.ClientRequirements || "";
  if (!rawText) return;
  const requirements = splitRequirementText(rawText);
  if (!requirements.length) return;

  let items = [];
  if (isServer) {
    if (hasPermission("plugins.manage.install", false)) {
      try {
        const payload = await hostServiceJson("/v1/plugin_repo/requirements_status", {
          method: "POST",
          body: { requirements },
        });
        items = Array.isArray(payload?.items) ? payload.items : [];
      } catch (_err) {
        items = [];
      }
    }
  } else {
    try {
      const payload = await clientServiceJson("/v1/client/requirements_status", {
        method: "POST",
        body: { requirements },
      });
      items = Array.isArray(payload?.items) ? payload.items : [];
    } catch (_err) {
      items = [];
    }
  }

  const statusMap = new Map();
  items.forEach((item) => {
    if (item && item.requirement) {
      statusMap.set(item.requirement, item);
    }
  });

  const lines = requirements.map((req) => {
    const info = statusMap.get(req);
    if (!info) {
      return `<span>${escapeHtml(req)}</span>`;
    }
    if (info.installed) {
      return `<span class="req-check">✓</span> ${escapeHtml(req)}`;
    }
    if (info.included_in_python) {
      return `${escapeHtml(req)} <span class="req-note">(included in python)</span>`;
    }
    return `${escapeHtml(req)} <span class="req-missing-tag">(missing)</span>`;
  });

  const card = document.createElement("div");
  card.className = "plugin-detail-card requirements-status-card";
  card.innerHTML = `
    <h4>${escapeHtml(title)}</h4>
    <div class="requirements-status-list">${lines.join("<br>")}</div>
  `;
  container.appendChild(card);
}

function renderPluginRepoFiles(container, pluginId, tree) {
  container.innerHTML = "";
  const wrap = document.createElement("div");
  wrap.className = "plugin-detail-files";

  const treeBox = document.createElement("div");
  treeBox.className = "plugin-detail-filetree";

  const pre = document.createElement("pre");
  pre.className = "plugin-detail-filecontent";
  pre.textContent = i18nTranslate("chat_js.common.select_file", "Select a file.");

  const buildTree = (nodes, depth = 0) => {
    const list = document.createElement("div");
    nodes.forEach((node) => {
      if (node.type === "folder") {
        const row = document.createElement("div");
        row.className = "file-tree-row file-tree-folder";
        row.style.paddingLeft = `${depth * 12}px`;
        const toggle = document.createElement("button");
        toggle.className = "file-tree-toggle";
        toggle.textContent = "+";
        const label = document.createElement("span");
        label.textContent = node.name || "";
        row.appendChild(toggle);
        row.appendChild(label);

        const children = document.createElement("div");
        children.className = "file-tree-children hidden";
        if (Array.isArray(node.children) && node.children.length) {
          children.appendChild(buildTree(node.children, depth + 1));
        }

        const toggleFolder = () => {
          const hidden = children.classList.toggle("hidden");
          toggle.textContent = hidden ? "+" : "-";
        };
        toggle.addEventListener("click", (event) => {
          event.stopPropagation();
          toggleFolder();
        });
        row.addEventListener("click", toggleFolder);

        list.appendChild(row);
        list.appendChild(children);
        return;
      }

      const row = document.createElement("div");
      row.className = "file-tree-row file-tree-file";
      row.style.paddingLeft = `${depth * 12}px`;
      row.textContent = node.name || "";
      row.addEventListener("click", async () => {
        const payload = await apiJson(
          pluginRepoServerPath(`/v1/plugin_repo/file/${pluginId}`, { path: node.path })
        );
        pre.textContent = payload.content || "";
      });
      list.appendChild(row);
    });
    return list;
  };

  treeBox.appendChild(buildTree(tree));
  wrap.appendChild(treeBox);
  wrap.appendChild(pre);
  container.appendChild(wrap);
}

function renderPluginRepoCards(container, items, formatter) {
  container.innerHTML = "";
  if (!items || !items.length) {
    container.innerHTML = "<div class=\"muted\">No data available.</div>";
    return;
  }
  const list = document.createElement("div");
  list.className = "plugin-detail-list";
  items.forEach((item) => {
    const data = formatter(item);
    const card = document.createElement("div");
    card.className = "plugin-detail-card";
    card.innerHTML = `<h4>${escapeHtml(data.title)}</h4><p>${escapeHtml(data.meta)}</p><p>${escapeHtml(data.body).replace(/\n/g, "<br>")}</p>`;
    list.appendChild(card);
  });
  container.appendChild(list);
}

function formatReviewCard(item) {
  const rating = Number.isFinite(Number(item.rating)) ? Number(item.rating) : 0;
  return {
    title: `${item.userName || "User"} - ${rating.toFixed(1)}`,
    meta: item.createdAt ? new Date(item.createdAt).toLocaleDateString() : "",
    body: item.comment || "",
  };
}

function formatBugCard(item) {
  return {
    title: item.title || "Bug",
    meta: [item.status, item.createdAt ? new Date(item.createdAt).toLocaleDateString() : ""].filter(Boolean).join(" | "),
    body: item.description || "",
  };
}

function formatGitCard(item) {
  const author =
    item.authorName ||
    item.authorNickname ||
    item.author ||
    item.authorEmail ||
    "Unknown";
  const files = Array.isArray(item.files)
    ? item.files.map((f) => {
        if (!f) return "";
        const status = f.status || f.Status || "";
        const path = f.path || f.Path || "";
        const path2 = f.path2 || f.Path2 || "";
        if (path2) return `${status} ${path} -> ${path2}`.trim();
        return `${status} ${path}`.trim();
      }).filter(Boolean)
    : [];
  return {
    title: item.subject || "Commit",
    meta: [author, item.date ? new Date(item.date).toLocaleDateString() : ""].filter(Boolean).join(" | "),
    body: [item.body || item.message || "", files.join("\n")].filter(Boolean).join("\n"),
  };
}

function ensureRouterState() {
  if (!app.state.router) {
    app.state.router = { manifest: {}, enabled: {}, settings: {} };
  }
  if (!app.state.router.manifest) app.state.router.manifest = {};
  if (!app.state.router.enabled) app.state.router.enabled = {};
  if (!app.state.router.settings) app.state.router.settings = {};
}

function routerScopeKey(pid, sid) {
  const cleanPid = String(pid || app.state?.ui?.activePid || "").trim();
  const cleanSid = String(sid || "").trim();
  if (!cleanSid) return "";
  return cleanPid ? `${cleanPid}::${cleanSid}` : cleanSid;
}

function getRouterConfig(sid, pid = app.state?.ui?.activePid) {
  ensureRouterState();
  const key = routerScopeKey(pid, sid);
  const projectKey = routerProjectDefaultsKey(pid);
  const legacyKey = String(sid || "").trim();
  if (!key) return { enabled: [], settings: {} };
  const projectEnabled = Array.isArray(app.state.router.enabled[projectKey]) ? app.state.router.enabled[projectKey] : [];
  const scopedEnabled = app.state.router.enabled[key];
  const legacyEnabled = legacyKey && legacyKey !== key ? app.state.router.enabled[legacyKey] : null;
  const enabled = Array.from(new Set([
    ...projectEnabled,
    ...(Array.isArray(scopedEnabled) ? scopedEnabled : []),
    ...(Array.isArray(legacyEnabled) ? legacyEnabled : []),
  ]));
  const projectSettings = app.state.router.settings[projectKey];
  const scopedSettings = app.state.router.settings[key];
  const legacySettings = legacyKey && legacyKey !== key ? app.state.router.settings[legacyKey] : null;
  const useLegacySettings = legacySettings && typeof legacySettings === "object" && (!scopedSettings || !Object.keys(scopedSettings || {}).length);
  const mergedSettings = {
    ...((projectSettings && typeof projectSettings === "object") ? projectSettings : {}),
    ...(useLegacySettings ? legacySettings : {}),
    ...((scopedSettings && typeof scopedSettings === "object") ? scopedSettings : {}),
  };
  return {
    enabled,
    settings: mergedSettings,
  };
}

function setRouterEnabled(sid, pluginId, enabled, pid = app.state?.ui?.activePid) {
  ensureRouterState();
  const key = routerScopeKey(pid, sid);
  if (!key) return;
  const list = Array.isArray(app.state.router.enabled[key]) ? app.state.router.enabled[key].slice() : [];
  const pluginKey = String(pluginId || "").trim();
  if (!pluginKey) return;
  const has = list.includes(pluginKey);
  if (enabled && !has) list.push(pluginKey);
  if (!enabled && has) {
    const next = list.filter((item) => item !== pluginKey);
    app.state.router.enabled[key] = next;
  } else {
    app.state.router.enabled[key] = list;
  }
  if (isAdminUser()) {
    const projectKey = routerProjectDefaultsKey(pid);
    const projectList = Array.isArray(app.state.router.enabled[projectKey]) ? app.state.router.enabled[projectKey].slice() : [];
    const hasProject = projectList.includes(pluginKey);
    if (enabled && !hasProject) projectList.push(pluginKey);
    if (!enabled && hasProject) {
      app.state.router.enabled[projectKey] = projectList.filter((item) => item !== pluginKey);
    } else {
      app.state.router.enabled[projectKey] = projectList;
    }
  }
  saveRouterStateSnapshot(app.state);
  scheduleProjectRouterPrefsSave(pid);
  scheduleSave();
}

function setRouterSettings(sid, pluginId, values, pid = app.state?.ui?.activePid) {
  ensureRouterState();
  const key = routerScopeKey(pid, sid);
  if (!key) return;
  const pluginKey = String(pluginId || "").trim();
  if (!pluginKey) return;
  if (!app.state.router.settings[key] || typeof app.state.router.settings[key] !== "object") {
    app.state.router.settings[key] = {};
  }
  app.state.router.settings[key][pluginKey] = values || {};
  if (isAdminUser()) {
    const projectKey = routerProjectDefaultsKey(pid);
    if (!app.state.router.settings[projectKey] || typeof app.state.router.settings[projectKey] !== "object") {
      app.state.router.settings[projectKey] = {};
    }
    app.state.router.settings[projectKey][pluginKey] = values || {};
  }
  saveRouterStateSnapshot(app.state);
  scheduleProjectRouterPrefsSave(pid);
  scheduleSave();
}

function getRouterManifest() {
  ensureRouterState();
  return app.state.router.manifest || {};
}

function setRouterManifest(manifest) {
  ensureRouterState();
  app.state.router.manifest = manifest || {};
  app.state.router.manifest_ts = Date.now();
  saveRouterStateSnapshot(app.state);
  scheduleSave();
}

function routerAvailablePlugins(manifest, enabled, settings) {
  const list = Object.keys(manifest || {});
  if (list.length) return list.sort();
  const fallback = new Set([...(enabled || []), ...Object.keys(settings || {})]);
  return Array.from(fallback).sort();
}

function extractRouterPluginSchema(item) {
  const candidates = [
    item?.config_schema,
    item?.schema,
    item?.settings_schema,
    item?.settingsSchema,
    item?.config?.schema,
    item?.manifest?.config_schema,
    item?.manifest?.schema,
  ];
  for (const value of candidates) {
    if (Array.isArray(value)) return value;
  }
  return [];
}

async function refreshRouterManifest(force) {
  if (app.routerManifestInFlight && !force) return;
  if (!app.state.remote.serverUrl) return;
  const now = Date.now();
  if (!force && Number(app.routerManifestRetryAfterTs || 0) > now) return;
  app.routerManifestInFlight = true;
  try {
    const data = await apiJson("/v1/router/plugins");
    app.routerManifestRetryAfterTs = 0;
    app.routerManifestLastError = "";
    const out = {};
    for (const item of data?.plugins || []) {
      const pid = String(item?.plugin_id || item?.id || "").trim();
      if (!pid) continue;
      out[pid] = {
        title: item?.title || item?.name || pid,
        short_description: item?.short_description || item?.description || "",
        type: item?.type || "router",
        schema: extractRouterPluginSchema(item),
        model_type: item?.model_type || "",
        interaction_type: item?.interaction_type || "",
      };
    }
    setRouterManifest(out);
  } catch (err) {
    const message = String(err?.message || err || "router_manifest_failed");
    app.routerManifestLastError = message;
    app.routerManifestRetryAfterTs = Date.now() + 30000;
    const lastLoggedAt = Number(app.routerManifestLastLoggedAt || 0);
    if (!lastLoggedAt || (Date.now() - lastLoggedAt) >= 15000) {
      appendLog(`[router] ${message}`, "warn");
      app.routerManifestLastLoggedAt = Date.now();
    }
  } finally {
    app.routerManifestInFlight = false;
    renderRouterPluginsList();
  }
}

function renderRouterPluginsList() {
  const body = app.dom.routerTableBody;
  if (!body) return;
  body.innerHTML = "";
  const sid = app.state.ui.activeSid;
  const activePid = app.state.ui.activePid;
  if (!sid) {
    body.appendChild(renderRouterEmpty("Select a session to configure router plugins."));
    return;
  }
  if (activePid && canUseRemoteServer() && !app.routerPrefsLoaded?.[activePid]) {
    void loadProjectRouterPrefs(activePid);
  }

  const { enabled, settings } = getRouterConfig(sid);
  const manifest = getRouterManifest();
  if (!Object.keys(manifest).length && !app.routerManifestInFlight) {
    void refreshRouterManifest(false);
  }
  const avail = routerAvailablePlugins(manifest, enabled, settings).filter((pid) => {
    const meta = manifest[pid] || {};
    return pluginRepoManageMatches({
      name: meta.title || pid,
      id: pid,
      description: meta.short_description || "",
      type: meta.type || "router",
    });
  });
  if (!avail.length) {
    const anyDiscovered = routerAvailablePlugins(manifest, enabled, settings).length > 0;
    body.appendChild(renderRouterEmpty(anyDiscovered ? "No server plugins match the current filter." : "No server plugins discovered."));
    return;
  }

  for (const pid of avail) {
    const meta = manifest[pid] || {};
    const row = document.createElement("div");
    row.className = "plugin-row";

    const onCell = document.createElement("div");
    onCell.className = "plugin-cell plugin-cell-toggle";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = enabled.includes(pid);
    checkbox.addEventListener("change", () => {
      setRouterEnabled(sid, pid, checkbox.checked);
    });
    onCell.appendChild(checkbox);

    const nameCell = document.createElement("div");
    nameCell.className = "plugin-cell plugin-cell-name";
    nameCell.dataset.pluginType = meta.type || "router";
    nameCell.textContent = meta.title || pid;

    const typeCell = document.createElement("div");
    typeCell.className = "plugin-cell plugin-cell-type";
    typeCell.textContent = meta.type || "router";

    const descCell = document.createElement("div");
    descCell.className = "plugin-cell plugin-cell-desc";
    descCell.textContent = meta.short_description || "";

    const actionCell = document.createElement("div");
    actionCell.className = "plugin-cell plugin-cell-actions";
    const btn = document.createElement("button");
    btn.className = "ghost";
    btn.textContent = i18nTranslate("chat_js.common.settings", "Settings");
    btn.addEventListener("click", () => {
      void openRouterSettings(pid);
    });
    actionCell.appendChild(btn);

    row.appendChild(onCell);
    row.appendChild(nameCell);
    row.appendChild(typeCell);
    row.appendChild(descCell);
    row.appendChild(actionCell);
    body.appendChild(row);
  }
}

function renderRouterEmpty(text) {
  const row = document.createElement("div");
  row.className = "plugin-row plugin-empty";
  const cell = document.createElement("div");
  cell.className = "plugin-cell";
  cell.textContent = text;
  row.appendChild(cell);
  return row;
}

async function openRouterSettings(pluginId) {
  const sid = app.state.ui.activeSid;
  const pid = app.state.ui.activePid;
  if (!sid) {
    appendLog("Select a session first.", "warn");
    return;
  }
  if (pid) {
    if (!app.routerPrefsLoaded?.[pid]) {
      void loadProjectRouterPrefs(pid);
    }
  }
  if (app.state.remote.serverUrl && !Object.keys(getRouterManifest()).length && !app.routerManifestInFlight) {
    void refreshRouterManifest(false);
  }
  const manifest = getRouterManifest();
  const meta = manifest[pluginId] || {};
  const schema = Array.isArray(meta.schema) ? meta.schema : [];
  const { settings } = getRouterConfig(sid);
  const current = (settings[pluginId] && typeof settings[pluginId] === "object") ? settings[pluginId] : {};
  const title = `Router Plugin Settings: ${meta.title || pluginId}`;

  const modal = createRouterModal(title);
  const body = modal.body;

  let saveHandler = null;

  const metaRow = document.createElement("div");
  metaRow.className = "router-meta-row";
  const modelType = String(meta.model_type || "");
  const interactionType = String(meta.interaction_type || "");
  if (modelType) {
    const tag = document.createElement("span");
    tag.className = "router-tag";
    tag.textContent = `Model_Type=${modelType}`;
    metaRow.appendChild(tag);
  }
  if (interactionType) {
    const tag = document.createElement("span");
    tag.className = "router-tag";
    tag.textContent = `Interaction_Type=${interactionType}`;
    metaRow.appendChild(tag);
  }
  if (metaRow.childNodes.length) {
    body.appendChild(metaRow);
  }

  if (schema.length) {
    const form = document.createElement("div");
    form.className = "router-form";
    const inputs = [];

    schema.forEach((field) => {
      if (!field || typeof field !== "object") return;
      const key = String(field.key || "").trim();
      if (!key) return;
      const label = String(field.label || key);
      const type = String(field.type || "str").toLowerCase();
      const help = String(field.help || field.description || "");
      const defaultValue = field.default;
      const value = current[key] ?? defaultValue ?? "";

      const wrapper = document.createElement("label");
      wrapper.className = "field";
      if (field.indent) {
        wrapper.style.marginLeft = "14px";
      }
      const span = document.createElement("span");
      span.textContent = label;
      wrapper.appendChild(span);

      let input = null;
      if (type === "bool" || type === "boolean") {
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = Boolean(value);
        input = checkbox;
      } else if (type === "int" || type === "integer") {
        const num = document.createElement("input");
        num.type = "number";
        num.step = "1";
        num.value = value !== undefined && value !== null ? String(value) : "";
        input = num;
      } else if (type === "float" || type === "number") {
        const num = document.createElement("input");
        num.type = "number";
        num.step = "any";
        num.value = value !== undefined && value !== null ? String(value) : "";
        input = num;
      } else if (type === "enum" || type === "select") {
        const sel = document.createElement("select");
        const opts = Array.isArray(field.options || field.choices) ? field.options || field.choices : [];
        opts.forEach((opt) => {
          const option = document.createElement("option");
          option.value = String(opt);
          option.textContent = String(opt);
          sel.appendChild(option);
        });
        if (value !== undefined && value !== null) {
          sel.value = String(value);
        }
        input = sel;
      } else {
        const txt = document.createElement("input");
        txt.type = "text";
        txt.value = value !== undefined && value !== null ? String(value) : "";
        input = txt;
      }

      if (help) {
        input.title = help;
      }
      wrapper.appendChild(input);
      form.appendChild(wrapper);
      inputs.push({ key, type, input });
      if (help) {
        const helpEl = document.createElement("div");
        helpEl.className = "muted";
        helpEl.textContent = help;
        form.appendChild(helpEl);
      }
    });

    body.appendChild(form);

    saveHandler = () => {
      const next = {};
      inputs.forEach(({ key, type, input }) => {
        let value;
        if (type === "bool" || type === "boolean") {
          value = Boolean(input.checked);
        } else if (type === "int" || type === "integer") {
          const parsed = parseInt(input.value, 10);
          value = Number.isNaN(parsed) ? null : parsed;
        } else if (type === "float" || type === "number") {
          const parsed = parseFloat(input.value);
          value = Number.isNaN(parsed) ? null : parsed;
        } else {
          value = input.value;
        }
        if (Array.isArray(value) ? value.length > 0 : (value !== null && value !== undefined && value !== "")) {
          next[key] = value;
        }
      });
      setRouterSettings(sid, pluginId, next);
    };
  } else {
    const textarea = document.createElement("textarea");
    textarea.value = JSON.stringify(current, null, 2);
    body.appendChild(textarea);
    saveHandler = () => {
      let parsed = {};
      try {
        parsed = JSON.parse(textarea.value.trim() || "{}");
      } catch (err) {
        alert(`Invalid JSON: ${err.message || err}`);
        return false;
      }
      setRouterSettings(sid, pluginId, parsed);
      return true;
    };
  }

  modal.overlay.onSave = saveHandler;
}

function createRouterModal(title) {
  const overlay = document.createElement("div");
  overlay.className = "router-modal";
  const card = document.createElement("div");
  card.className = "router-modal-card";
  overlay.appendChild(card);

  const header = document.createElement("div");
  header.className = "section-header";
  const titleEl = document.createElement("div");
  titleEl.className = "llm-chat-modal-title";
  titleEl.textContent = title || i18nTranslate("chat_js.common.settings", "Settings");
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

  function close() {
    try {
      if (typeof overlay.onClose === "function") {
        overlay.onClose();
      }
    } catch (_err) {}
    overlay.remove();
  }
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) close();
  });
  closeBtn.addEventListener("click", close);
  cancelBtn.addEventListener("click", close);
  saveBtn.addEventListener("click", () => {
    if (typeof overlay.onSave === "function") {
      const result = overlay.onSave();
      if (result === false) return;
    }
    close();
  });

  getOverlayMount().appendChild(overlay);
  return { overlay, body };
}

async function promptForGuestAlias() {
  const modal = createRouterModal("Guest Alias");
  const body = modal.body;
  const note = document.createElement("div");
  note.className = "muted";
  note.textContent = "Set an alias to join this public chat as a guest.";
  body.appendChild(note);
  const field = document.createElement("label");
  field.className = "field";
  const label = document.createElement("span");
  label.textContent = "Alias";
  field.appendChild(label);
  const input = document.createElement("input");
  input.type = "text";
  input.maxLength = 80;
  input.value = getGuestAliasValue();
  field.appendChild(input);
  body.appendChild(field);
  return await new Promise((resolve) => {
    const close = modal.overlay.onClose;
    modal.overlay.onClose = () => {
      if (typeof close === "function") close();
      resolve("");
    };
    modal.overlay.onSave = () => {
      const alias = String(input.value || "").trim();
      if (!alias) {
        input.focus();
        return false;
      }
      resolve(alias);
      return true;
    };
    setTimeout(() => input.focus(), 0);
  });
}

async function ensureGuestAliasForSend() {
  if (app.state.auth.token) return getPreferredAlias();
  let alias = getGuestAliasValue();
  if (!alias) {
    alias = await promptForGuestAlias();
    if (!alias) return "";
    app.state.auth.alias = alias;
    applyStateToInputs();
    scheduleSave();
  }
  ensureGuestId();
  return alias;
}

// Expose for plugins needing themed dialogs.
if (typeof window !== "undefined") {
  window.createRouterModal = createRouterModal;
  window.getPluginSharedObjects = getSharedObjects;
}

function pluginNeedsLogin(pluginId) {
  const key = String(pluginId || "").trim();
  if (!key) return false;
  const meta = app.plugins.meta?.[key] || {};
  return String(meta.kind || "").trim().toLowerCase() !== "auth";
}

function renderComposerLeft() {
  const slot = app.dom.composerLeft;
  const extra = app.plugins.slots.composerLeft;
  slot.innerHTML = "";
  const baseNodes = app.dom.composerLeftBase || [];
  for (const node of baseNodes) {
    slot.appendChild(node);
  }
  for (const item of extra) {
    if (!app.state.auth.token && pluginNeedsLogin(item.pluginId)) continue;
    if (item.pluginId && !canAccessPlugin(item.pluginId, "view")) continue;
    const entry = item.entry || item;
    let node = item.node || null;
    if (!node) {
      if (typeof entry === "function") {
        node = entry(getPluginContext());
      } else {
        node = entry;
      }
      item.node = node || null;
    }
    if (node) {
      slot.appendChild(node);
    }
  }
}

function renderTopRightIconRow() {
  const slot = app.dom.topRightIconRow;
  if (!slot) return;
  slot.innerHTML = "";
  let count = 0;
  for (const item of app.plugins.slots.topRightIconRow || []) {
    if (!app.state.auth.token && pluginNeedsLogin(item.pluginId)) continue;
    if (item.pluginId && !canAccessPlugin(item.pluginId, "view")) continue;
    const entry = item.entry || item;
    let node = item.node || null;
    if (typeof entry === "function") {
      node = entry(getPluginContext()) || null;
      item.node = node;
    } else if (!node) {
      node = entry;
      if (node) item.node = node;
    }
    if (node) {
      slot.appendChild(node);
      count += 1;
    }
  }
  slot.classList.toggle("hidden", count === 0);
}

function isTranscriptBarVisible(kind) {
  return kind === "top"
    ? Boolean(app.state.ui.transcriptTopbarVisible)
    : Boolean(app.state.ui.transcriptBottombarVisible);
}

function setTranscriptBarVisibility(kind, visible) {
  if (kind === "top") {
    app.state.ui.transcriptTopbarVisible = Boolean(visible);
  } else {
    app.state.ui.transcriptBottombarVisible = Boolean(visible);
  }
  scheduleSave();
  renderTranscriptBars();
}

function toggleTranscriptBarVisibility(kind) {
  setTranscriptBarVisibility(kind, !isTranscriptBarVisible(kind));
}

function renderTranscriptBars() {
  renderTranscriptBar(
    "top",
    app.dom.transcriptTopbarShell,
    app.dom.transcriptTopbarNotch,
    app.dom.transcriptTopbar,
    app.dom.transcriptTopbarLeft,
    app.dom.transcriptTopbarRight,
    app.plugins.slots.transcriptTopbar,
  );
  renderTranscriptBar(
    "bottom",
    app.dom.transcriptBottombarShell,
    app.dom.transcriptBottombarNotch,
    app.dom.transcriptBottombar,
    app.dom.transcriptBottombarLeft,
    app.dom.transcriptBottombarRight,
    app.plugins.slots.transcriptBottombar,
  );
}

function getTranscriptNotchIconMarkup(kind, isOpen) {
  const path =
    kind === "top"
      ? (isOpen ? "M2.25 7.75 6 4l3.75 3.75" : "M2.25 4.25 6 8l3.75-3.75")
      : (isOpen ? "M2.25 4.25 6 8l3.75-3.75" : "M2.25 7.75 6 4l3.75 3.75");
  return `
    <svg viewBox="0 0 12 12" aria-hidden="true" focusable="false">
      <path d="${path}"></path>
    </svg>
  `.trim();
}

function syncTranscriptBarNotch(kind, notch, showShell, isOpen) {
  if (!notch) return;
  const markup = getTranscriptNotchIconMarkup(kind, showShell && isOpen);
  if (notch.innerHTML.trim() !== markup) {
    notch.innerHTML = markup;
  }
}

function renderTranscriptBar(kind, shell, notch, wrapper, left, right, entries) {
  if (!shell || !notch || !wrapper || !left || !right) return;
  const isBottomBar = kind === "bottom";
  left.innerHTML = "";
  right.innerHTML = "";
  let count = 0;
  for (const item of entries || []) {
    if (!app.state.auth.token && pluginNeedsLogin(item.pluginId)) continue;
    if (item.pluginId && !canAccessPlugin(item.pluginId, "view")) continue;
    const entry = item.entry || item;
    let node = item.node || null;
    if (!node) {
      if (typeof entry === "function") {
        node = entry(getPluginContext());
      } else {
        node = entry;
      }
      if (node) {
        item.node = node;
      }
    }
    if (!node) continue;
    const side = (item.side || "right").toString().toLowerCase();
    let mountNode = node;
    if (isBottomBar) {
      const slot = document.createElement("div");
      slot.className = "transcript-slot-item";
      slot.style.display = "inline-flex";
      slot.style.alignItems = "center";
      slot.style.flex = "0 0 auto";
      slot.style.minWidth = "max-content";
      slot.style.width = "auto";
      slot.style.maxWidth = "none";
      slot.style.whiteSpace = "nowrap";
      slot.appendChild(node);
      mountNode = slot;
    }
    if (side === "left") {
      left.appendChild(mountNode);
    } else {
      right.appendChild(mountNode);
    }
    count += 1;
  }
  const isOpen = isTranscriptBarVisible(kind);
  if (isBottomBar) {
    // Match the intended bottombar wrapper behavior in embeds even if the
    // scoped stylesheet misses this selector.
    wrapper.style.display = "";
    wrapper.style.overflowX = "auto";
    wrapper.style.overflowY = "hidden";
    wrapper.style.webkitOverflowScrolling = "touch";
    wrapper.style.scrollbarWidth = "thin";
    wrapper.style.justifyContent = "flex-start";
    wrapper.style.flexWrap = "nowrap";
    left.style.display = "inline-flex";
    right.style.display = "inline-flex";
    left.style.flexWrap = "nowrap";
    right.style.flexWrap = "nowrap";
    left.style.flex = "0 0 auto";
    right.style.flex = "0 0 auto";
    left.style.minWidth = "max-content";
    right.style.minWidth = "max-content";
    left.style.whiteSpace = "nowrap";
    right.style.whiteSpace = "nowrap";
    left.style.verticalAlign = "middle";
    right.style.verticalAlign = "middle";
    left.style.gap = "8px";
    right.style.marginLeft = count ? "12px" : "0";
  } else {
    wrapper.style.display = "";
    wrapper.style.flexWrap = "";
    wrapper.style.justifyContent = "";
    wrapper.style.overflowX = "";
    wrapper.style.overflowY = "";
    wrapper.style.webkitOverflowScrolling = "";
    wrapper.style.scrollbarWidth = "";
    left.style.display = "";
    right.style.display = "";
    left.style.flexWrap = "";
    right.style.flexWrap = "";
    left.style.flex = "";
    right.style.flex = "";
    left.style.minWidth = "";
    right.style.minWidth = "";
    left.style.whiteSpace = "";
    right.style.whiteSpace = "";
    left.style.verticalAlign = "";
    right.style.verticalAlign = "";
    left.style.gap = "";
    right.style.marginLeft = "";
  }
  const showShell = count > 0;
  shell.classList.toggle("hidden", !showShell);
  shell.classList.toggle("is-open", showShell && isOpen);
  wrapper.classList.remove("hidden");
  notch.classList.toggle("hidden", !showShell);
  syncTranscriptBarNotch(kind, notch, showShell, isOpen);
  notch.disabled = count === 0;
  notch.setAttribute("aria-disabled", count === 0 ? "true" : "false");
  notch.setAttribute("aria-expanded", showShell && isOpen ? "true" : "false");
  notch.title = `${showShell && isOpen ? "Hide" : "Show"} ${kind === "top" ? "top" : "bottom"} transcript bar`;
}

function renderPluginPanels(options = {}) {
  const activeId = String(app.state.ui.activeGuiPluginId || "").trim();
  const canRenderActive = Boolean(activeId && isPluginEnabled(activeId) && canAccessPlugin(activeId, "open"));
  const currentActive = String(app.dom.pluginPanels?.dataset?.activePluginId || "").trim();
  if (!options.force && canRenderActive && currentActive === activeId && app.dom.pluginPanels?.childElementCount) {
    return;
  }
  app.dom.pluginPanels.innerHTML = "";
  app.dom.pluginPanels.dataset.activePluginId = canRenderActive ? activeId : "";
  if (!canRenderActive) return;
  const entry = (app.plugins.slots.panels || []).find((item) => {
    const panel = item.tab || item;
    const panelId = item.pluginId || panel.pluginId || panel.id;
    return String(panelId || "").trim() === activeId;
  });
  if (!entry) return;
  const panel = entry.tab || entry;
  const panelId = entry.pluginId || panel.pluginId || panel.id;
  if (!app.state.auth.token && pluginNeedsLogin(panelId)) return;
  const wrapper = document.createElement("div");
  wrapper.className = "plugin-panel";
  if (panelId) {
    wrapper.dataset.pluginId = panelId;
    wrapper.id = `plugin-panel-${panelId}`;
  }
  const title = document.createElement("h3");
  title.textContent = panel.title || panel.id || "Plugin";
  wrapper.appendChild(title);
  const body = document.createElement("div");
  wrapper.appendChild(body);
  try {
    panel.render?.(body, getPluginContext());
  } catch (err) {
    const message = err?.stack || err?.message || String(err || "Unknown plugin render error");
    appendLog(`[plugins] ${panelId} panel render failed: ${err?.message || err}`, "error");
    body.innerHTML = "";
    const fallback = document.createElement("div");
    fallback.className = "plugin-render-error";
    fallback.innerHTML = `
      <h4>Plugin render failed</h4>
      <p>The ${escapeHtml(panelId)} panel could not render.</p>
      <pre></pre>
    `;
    const pre = fallback.querySelector("pre");
    if (pre) pre.textContent = message;
    body.appendChild(fallback);
  }
  app.dom.pluginPanels.appendChild(wrapper);
}

function ensurePluginFullView() {
  if (pluginFullView) return pluginFullView;
  const overlay = document.createElement("div");
  overlay.className = "plugin-fullscreen hidden";
  overlay.innerHTML = `
    <div class="plugin-fullscreen-card">
      <div class="plugin-fullscreen-header">
        <div class="plugin-fullscreen-title"></div>
        <button class="ghost plugin-fullscreen-close" type="button">Close</button>
      </div>
      <div class="plugin-fullscreen-body"></div>
    </div>
  `;
  const titleEl = overlay.querySelector(".plugin-fullscreen-title");
  const bodyEl = overlay.querySelector(".plugin-fullscreen-body");
  const closeBtn = overlay.querySelector(".plugin-fullscreen-close");
  const close = () => closePluginFullView();
  closeBtn.addEventListener("click", close);
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) close();
  });
  getOverlayMount().appendChild(overlay);
  pluginFullView = { overlay, titleEl, bodyEl };
  return pluginFullView;
}

function openPluginFullView(pluginId, options = {}) {
  const pid = String(pluginId || "").trim();
  if (!pid) return;
  const view = ensurePluginFullView();
  const info = app.plugins.meta[pid] || {};
  view.titleEl.textContent = options.title || info.name || pid;
  view.bodyEl.innerHTML = "";
  view.overlay.classList.remove("hidden");

  const entry = app.plugins.slots.panels.find((panel) => {
    const tab = panel.tab || panel;
    const id = panel.pluginId || tab?.pluginId || tab?.id;
    return String(id || "") === pid;
  });
  const panel = entry?.tab || entry;
  const render =
    options.render ||
    panel?.renderFull ||
    panel?.render ||
    app.plugins.instances?.[pid]?.renderFull;
  if (typeof render === "function") {
    try {
      render(view.bodyEl, getPluginContext(), { fullView: true });
    } catch (err) {
      const message = err?.stack || err?.message || String(err || "Unknown plugin render error");
      appendLog(`[plugins] ${pid} full view render failed: ${err?.message || err}`, "error");
      view.bodyEl.innerHTML = "";
      const fallback = document.createElement("div");
      fallback.className = "plugin-render-error";
      fallback.innerHTML = `
        <h3>Plugin render failed</h3>
        <p>The ${escapeHtml(pid)} panel could not render.</p>
        <pre></pre>
      `;
      const pre = fallback.querySelector("pre");
      if (pre) pre.textContent = message;
      view.bodyEl.appendChild(fallback);
    }
  } else {
    view.bodyEl.textContent = "No full view available for this plugin.";
  }
}

function closePluginFullView() {
  if (!pluginFullView) return;
  pluginFullView.bodyEl.innerHTML = "";
  pluginFullView.overlay.classList.add("hidden");
}

function openPluginPanel(pluginId, options = {}) {
  if (!pluginId) return;
  if (!canAccessPlugin(pluginId, "open")) return;
  const openModal = options.openModal !== false;
  const panelCfg = getGuiPluginPanelConfig(pluginId);
  const windowType = String(panelCfg?.windowType || "").trim().toLowerCase();
  app.state.ui.activeGuiPluginId = pluginId;
  scheduleSave();
  updateGuiPluginsTitle();
  if (windowType === "full") {
    closeTools();
    openPluginFullView(pluginId);
    return;
  }
  renderPluginPanels({ force: true });
  applyToolsWindowMode("gui-plugins");
  const modalOpen = app.dom.toolsModal && !app.dom.toolsModal.classList.contains("hidden");
  const activePanel = app.dom.toolsModal?.querySelector(".tool-section.active");
  const isGuiPanel = activePanel?.dataset.panel === "gui-plugins";
  if (openModal) {
    openTools("gui-plugins");
  }
  if (openModal || (modalOpen && isGuiPanel)) {
    requestAnimationFrame(() => {
      const el = app.dom.pluginPanels.querySelector(`[data-plugin-id="${pluginId}"]`);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  }
}

