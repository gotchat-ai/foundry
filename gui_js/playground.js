const STORAGE_KEY = "llmloader2.chat_js.state";
const STORAGE_AUTH_KEY = "llmloader2.chat_js.auth";
const STORAGE_PREFS_KEY = "llmloader2.chat_js.prefs";
const PLAYGROUND_CHANNEL_NAME = "llmloader2.plugin-playground.v1";

const query = new URLSearchParams(window.location.search);
const targetPluginId = String(query.get("plugin") || "").trim();
const cleanupTasks = [];

function readJsonStorage(key) {
  try { return JSON.parse(localStorage.getItem(key) || "{}"); }
  catch (_err) { return {}; }
}

function mergeDeep(base, extra) {
  if (Array.isArray(base)) return Array.isArray(extra) ? extra.slice() : base.slice();
  if (!extra || typeof extra !== "object") return { ...(base || {}) };
  const out = { ...(base || {}) };
  Object.entries(extra).forEach(([key, value]) => {
    out[key] = value && typeof value === "object" && !Array.isArray(value)
      ? mergeDeep(out[key] || {}, value)
      : value;
  });
  return out;
}

const state = mergeDeep(mergeDeep(readJsonStorage(STORAGE_KEY), readJsonStorage(STORAGE_PREFS_KEY)), readJsonStorage(STORAGE_AUTH_KEY));
state.remote = state.remote || { serverUrl: window.location.origin };
state.auth = state.auth || {};
state.pluginPrefs = state.pluginPrefs || { enabled: {} };
state.ui = state.ui || {};
state.projects = state.projects || {};
state.sessions = state.sessions || {};
if (query.get("pid")) state.ui.activePid = query.get("pid");
if (query.get("sid")) state.ui.activeSid = query.get("sid");

const dom = {
  projectName: document.getElementById("project-name"),
  sessionName: document.getElementById("session-name"),
  scopeLink: document.getElementById("scope-link"),
  pluginTitle: document.getElementById("plugin-title"),
  connectionStatus: document.getElementById("connection-status"),
  connectionLabel: document.getElementById("connection-label"),
  canvas: document.getElementById("playground-canvas"),
  topShell: document.getElementById("top-toolbar-shell"),
  topToolbar: document.getElementById("top-toolbar"),
  topToggle: document.getElementById("top-toolbar-toggle"),
  bottomShell: document.getElementById("bottom-toolbar-shell"),
  bottomToolbar: document.getElementById("bottom-toolbar"),
  bottomToggle: document.getElementById("bottom-toolbar-toggle"),
  settingsButton: document.getElementById("settings-button"),
  settingsMenu: document.getElementById("settings-menu"),
  settingsDialog: document.getElementById("settings-dialog"),
  settingsTitle: document.getElementById("settings-title"),
  settingsBody: document.getElementById("settings-body"),
  settingsClose: document.getElementById("settings-close"),
};

const app = {
  plugins: new Map(),
  playgrounds: [],
  playgroundAssets: [],
  panels: [],
  eventHandlers: [],
  sharedObjects: [],
  messageRenderers: [],
  messagePreRenderers: [],
  blockRenderers: [],
  activeSpec: null,
  composerText: "",
  localStreamsBySid: new Map(),
  localStreamSuppressUntil: new Map(),
};

function repairDisplayEncoding(text) {
  const cp1252 = new Map([
    [0x20ac,0x80],[0x201a,0x82],[0x0192,0x83],[0x201e,0x84],[0x2026,0x85],[0x2020,0x86],
    [0x2021,0x87],[0x02c6,0x88],[0x2030,0x89],[0x0160,0x8a],[0x2039,0x8b],[0x0152,0x8c],
    [0x017d,0x8e],[0x2018,0x91],[0x2019,0x92],[0x201c,0x93],[0x201d,0x94],[0x2022,0x95],
    [0x2013,0x96],[0x2014,0x97],[0x02dc,0x98],[0x2122,0x99],[0x0161,0x9a],[0x203a,0x9b],
    [0x0153,0x9c],[0x017e,0x9e],[0x0178,0x9f],
  ]);
  const suspicion = (value) => [...value].reduce((score, char) => {
    const code = char.codePointAt(0);
    return score + ("ÂÃâð".includes(char) ? 3 : (code >= 0x80 && code <= 0x9f ? 4 : 0));
  }, 0) + (value.match(/�/g)?.length || 0) * 5
    + ((value.match(/á[º»]/g)?.length || 0) * 6);
  let repaired = String(text ?? "");
  for (let pass = 0; pass < 8; pass += 1) {
    const output = [];
    let run = [];
    const flush = () => {
      if (!run.length) return;
      const original = run.join(""); run = [];
      try {
        const bytes = Uint8Array.from([...original], (char) => cp1252.get(char.codePointAt(0)) ?? char.codePointAt(0));
        const candidate = new TextDecoder("utf-8", { fatal:true }).decode(bytes);
        output.push(candidate && suspicion(candidate) < suspicion(original) ? candidate : original);
      } catch (_error) { output.push(original); }
    };
    for (const char of repaired) {
      const code = char.codePointAt(0);
      if (code <= 0xff || cp1252.has(code)) run.push(char);
      else { flush(); output.push(char); }
    }
    flush();
    const next = output.join("");
    if (next === repaired) break;
    repaired = next;
  }
  return repaired
    .replace(/(?<=\p{L})�(?=(?:s|t|re|ve|ll|d|m)\b)/giu, "'")
    .replace(/(\p{N})\s*�\s*(\p{N})/gu, "$1 × $2")
    .replace(/�+/g, "");
}

function escapeHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderMarkdown(text) {
  const parts = repairDisplayEncoding(text).split("```");
  return parts.map((chunk, index) => {
    if (index % 2) {
      const lines = chunk.split("\n");
      const language = lines.length > 1 ? lines.shift().trim() : "";
      return `<pre><code data-lang="${escapeHtml(language)}">${escapeHtml(lines.join("\n") || chunk)}</code></pre>`;
    }
    return chunk.split("`").map((piece, pieceIndex) => (
      pieceIndex % 2 ? `<code>${escapeHtml(piece)}</code>` : escapeHtml(piece)
    )).join("").replace(/\n/g, "<br>");
  }).join("");
}

function applyMessagePrerender(message) {
  let current = { ...(message || {}), content:repairDisplayEncoding(message?.content || "") };
  for (const entry of app.messagePreRenderers) {
    try {
      const next = entry.fn(current, pluginContext(), { phase:"render" });
      if (next === null || next === false) return null;
      if (next && typeof next === "object" && ("msg" in next || "skip" in next)) {
        if (next.skip) return null;
        if (next.msg) current = next.msg;
      } else if (next && typeof next === "object") current = next;
    } catch (error) {
      console.warn(`[playground] ${entry.pluginId} message pre-render failed`, error);
    }
  }
  return current;
}

function renderMessageWithPlugins(message, options = {}) {
  const current = applyMessagePrerender(message);
  if (!current) return null;
  const ctx = pluginContext();
  for (const entry of app.messageRenderers) {
    try {
      const node = entry.fn(current, ctx);
      if (node) return options.mode === "bubble" && node.querySelector?.(".bubble")
        ? node.querySelector(".bubble") : node;
    } catch (error) {
      console.warn(`[playground] ${entry.pluginId} message render failed`, error);
    }
  }
  const bubble = document.createElement("div");
  bubble.className = options.bubbleClass || "bubble";
  const blocks = Array.isArray(current.blocks) ? current.blocks : [];
  if (blocks.length) {
    blocks.forEach((block) => {
      let rendered = null;
      for (const entry of app.blockRenderers) {
        try { rendered = entry.fn(block, current, ctx); } catch (_error) {}
        if (rendered) break;
      }
      if (rendered) bubble.appendChild(rendered);
      else {
        const fallback = document.createElement("div");
        fallback.innerHTML = renderMarkdown(String(block?.text || block?.content || ""));
        bubble.appendChild(fallback);
      }
    });
  } else {
    bubble.innerHTML = renderMarkdown(String(current.content || ""));
  }
  return bubble;
}

function serverBase() {
  const configured = String(state.remote?.serverUrl || "").replace(/\/+$/, "");
  return configured || window.location.origin;
}

function requestHeaders(extra = {}) {
  const headers = { ...extra };
  if (state.auth?.token) headers.Authorization = `Bearer ${state.auth.token}`;
  if (state.auth?.alias) headers["X-User-Alias"] = state.auth.alias;
  return headers;
}

async function apiJson(path, options = {}) {
  const url = /^https?:\/\//i.test(path) ? path : `${serverBase()}${path.startsWith("/") ? path : `/${path}`}`;
  const init = { ...options, headers: requestHeaders(options.headers || {}) };
  if (init.body && typeof init.body !== "string" && !(init.body instanceof FormData) && !(init.body instanceof Blob)) {
    init.headers["Content-Type"] = init.headers["Content-Type"] || "application/json";
    init.body = JSON.stringify(init.body);
  } else if (typeof init.body === "string" && /^[\s]*[\[{]/.test(init.body)) {
    init.headers["Content-Type"] = init.headers["Content-Type"] || "application/json";
  }
  const response = await fetch(url, init);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload?.detail || payload?.error || `HTTP ${response.status}`);
  return payload;
}

function setPlaygroundComposerText(text) {
  app.composerText = String(text ?? "");
  window.dispatchEvent(new CustomEvent("playground:composer-change", { detail: { text: app.composerText } }));
  return app.composerText;
}

async function consumeEventStream(response) {
  if (!response.body) return false;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let eventName = "message";
  let dataLines = [];
  let sawTerminal = false;
  const emit = () => {
    if (!dataLines.length) return;
    const raw = dataLines.join("\n");
    let data = raw;
    try { data = JSON.parse(raw); } catch (_err) {}
    let normalizedEvent = eventName === "tokens" ? "token" : (eventName || "message");
    const payload = data && typeof data === "object" ? data : { text: String(data || "") };
    if (normalizedEvent === "message"
        && payload && typeof payload === "object"
        && !payload.msg && !payload.message
        && payload.assistant_message) {
      payload.msg = payload.assistant_message;
    }
    if (normalizedEvent === "message"
        && payload && typeof payload === "object"
        && !payload.msg && !payload.message
        && (payload.assistant_response || payload.response || payload.result?.assistant_response)) {
      normalizedEvent = "token";
      payload.text = String(payload.assistant_response || payload.response || payload.result?.assistant_response || "");
    }
    if (normalizedEvent === "message"
        && payload && typeof payload === "object"
        && !payload.msg && !payload.message
        && (payload.text || payload.content || payload.token || payload.delta)) {
      normalizedEvent = "token";
    }
    if (normalizedEvent === "token" && payload && typeof payload === "object" && !payload.text) {
      payload.text = String(payload.content || payload.token || payload.delta || "");
    }
    if (["assistant_done", "done"].includes(normalizedEvent)) sawTerminal = true;
    dispatchPluginEvent(normalizedEvent, payload);
    eventName = "message";
    dataLines = [];
  };
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split(/\r?\n/);
    buffer = done ? "" : lines.pop() || "";
    for (const line of lines) {
      if (!line) emit();
      else if (line.startsWith("event:")) eventName = line.slice(6).trim() || "message";
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
    }
    if (done) {
      if (buffer) dataLines.push(buffer);
      emit();
      break;
    }
  }
  return sawTerminal;
}

async function sendPlaygroundMessage(text, options = {}) {
  const pid = String(state.ui.activePid || "");
  const sid = String(state.ui.activeSid || "");
  const message = String(text ?? app.composerText).trim();
  if (!pid || !sid) throw new Error("Select a project and session first.");
  if (!state.auth?.token) throw new Error("Authentication is required.");
  if (!message) return false;
  const clientMsgId = `playground-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
  setPlaygroundComposerText("");
  const response = await fetch(`${serverBase()}/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/service_chat`, {
    method: "POST",
    headers: requestHeaders({
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      "X-Project-ID": pid,
      "X-Session-ID": sid,
    }),
    body: JSON.stringify({
      message,
      stream: true,
      client_msg_id: clientMsgId,
      system: String(options.system || "").trim() || undefined,
    }),
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(detail || `HTTP ${response.status}`);
  }
  app.localStreamsBySid.set(sid, Number(app.localStreamsBySid.get(sid) || 0) + 1);
  try {
    const sawTerminal = await consumeEventStream(response);
    if (!sawTerminal) dispatchPluginEvent("assistant_done", { sid, local: true });
    await loadSessionMessages();
    return true;
  } finally {
    const remaining = Math.max(0, Number(app.localStreamsBySid.get(sid) || 1) - 1);
    if (remaining) app.localStreamsBySid.set(sid, remaining);
    else app.localStreamsBySid.delete(sid);
    app.localStreamSuppressUntil.set(sid, Date.now() + 5000);
  }
}

function saveState() {
  const snapshot = {
    pluginPrefs: JSON.parse(JSON.stringify(state.pluginPrefs || { enabled: {} })),
    ui: { activePid: String(state.ui.activePid || ""), activeSid: String(state.ui.activeSid || "") },
  };
  localStorage.setItem(STORAGE_PREFS_KEY, JSON.stringify(snapshot));
}

function pluginContext() {
  return {
    state,
    apiJson,
    buildHeaders: requestHeaders,
    saveState,
    refreshMessages: loadSessionMessages,
    hasPlayground: () => true,
    openPlayground: () => window,
    getComposerText: () => app.composerText,
    setComposerText: (text) => setPlaygroundComposerText(text),
    clearComposerText: () => setPlaygroundComposerText(""),
    deleteLastWord: () => setPlaygroundComposerText(
      app.composerText.replace(/\s+$/, "").replace(/\s+\S+$/, "").trimEnd(),
    ),
    deleteLastLine: () => setPlaygroundComposerText(app.composerText.split("\n").slice(0, -1).join("\n").trimEnd()),
    sendMessage: (text, options) => sendPlaygroundMessage(text, options),
    renderMarkdown,
    renderMessageWithPlugins,
    getSharedObjects: (filter) => app.sharedObjects.filter((item) => !filter || Object.entries(filter).every(([key, value]) => item[key] === value)),
    log: (message) => console.info("[playground]", message),
    surface: "playground",
  };
}

function attachResult(container, result) {
  if (result instanceof Node && !result.isConnected) container.appendChild(result);
  if (typeof result === "function") cleanupTasks.push(result);
  else if (result && typeof result.dispose === "function") cleanupTasks.push(() => result.dispose());
}

function createPluginHost(pluginId) {
  const noop = () => null;
  const host = {
    surface: "playground",
    getState: () => state,
    apiJson,
    requestLoadPriority: () => true,
    requestEmbedPreload: () => true,
    addPlayground(spec) {
      if (!spec || typeof spec !== "object") return null;
      const entry = { ...spec, id: String(spec.id || pluginId), pluginId, title: String(spec.title || pluginId) };
      app.playgrounds = app.playgrounds.filter((item) => !(item.pluginId === pluginId && item.id === entry.id));
      app.playgrounds.push(entry);
      return entry;
    },
    addPlaygroundAsset(spec) {
      if (!spec || typeof spec !== "object" || typeof spec.render !== "function") return null;
      const entry = {
        ...spec,
        pluginId,
        id: String(spec.id || `${pluginId}-playground-asset`),
        targetPluginId: String(spec.targetPluginId || spec.target || "").trim(),
        area: String(spec.area || "bottom-toolbar").trim().toLowerCase(),
        priority: Number(spec.priority || 0),
      };
      if (!entry.targetPluginId) return null;
      app.playgroundAssets = app.playgroundAssets.filter((item) => !(item.pluginId === pluginId && item.id === entry.id));
      app.playgroundAssets.push(entry);
      return entry;
    },
    openPlayground: noop,
    addPanelTab(tab) {
      if (tab) app.panels.push({ pluginId, tab: { ...tab, pluginId: tab.pluginId || pluginId } });
    },
    addEventHandler(handler) {
      if (typeof handler === "function") app.eventHandlers.push({ pluginId, fn: handler });
    },
    shareObject(object) {
      if (object) app.sharedObjects.push({ ...object, pluginId, service: object.service || pluginId });
      return object;
    },
    getSharedObjects(filter) {
      return app.sharedObjects.filter((item) => !filter || Object.entries(filter).every(([key, value]) => item[key] === value));
    },
    resolvePluginPath(path) { return new URL(path, window.location.href).toString(); },
    openPluginPanel() { openSettings(); },
    openPluginPanelWhenReady() { openSettings(); return Promise.resolve(true); },
    addToolbarAction: noop,
    addTopRightIconRow: noop,
    addTranscriptTopbar: noop,
    addTranscriptBottombar: noop,
    addComposerLeft: noop,
    addMessageRenderer(fn) {
      if (typeof fn === "function") app.messageRenderers.push({ pluginId, fn });
    },
    addMessageAttachment: noop,
    addAssistantMessageAttachment: noop,
    addMessagePreRenderer(fn) {
      if (typeof fn === "function") app.messagePreRenderers.push({ pluginId, fn });
    },
    addBlockRenderer(fn) {
      if (typeof fn === "function") app.blockRenderers.push({ pluginId, fn });
    },
    addMessageFooterItem: noop,
    addBlockTransformer: noop,
    addCompletionPayloadHook: noop,
    addAiRouterBridge: noop,
    addRosterAction: noop,
    addSendHook: noop,
    addSendContextMenuItem: noop,
    setProjectCreateHandler: noop,
    setSessionCreateHandler: noop,
    registerI18nBundle: noop,
    installI18nDictionary: noop,
    onLanguageChange: () => noop,
    t: (_key, fallback) => fallback || _key,
    translateContainer: noop,
    getLanguage: () => document.documentElement.lang || "en",
    log: (message) => console.info(`[${pluginId}]`, message),
  };
  return new Proxy(host, { get: (target, key) => key in target ? target[key] : noop });
}

function pluginIdFromEntry(entry) {
  if (entry?.id) return String(entry.id);
  return String(entry?.path || "").match(/\/plugins\/([^/]+)\//)?.[1] || "";
}

function pluginEnabled(id) {
  return state.pluginPrefs?.enabled?.[id] !== false;
}

function playgroundPreloadRank(pluginId) {
  const key = String(pluginId || "").trim();
  if (!key) return 999999;
  if (key === targetPluginId) return 0;
  const preloads = state.pluginPrefs?.preloads && typeof state.pluginPrefs.preloads === "object"
    ? state.pluginPrefs.preloads
    : {};
  const playground = Array.isArray(preloads.playground) ? preloads.playground : [];
  const index = playground.findIndex((id) => String(id || "").trim() === key);
  return index >= 0 ? index + 1 : 999999;
}

function resolvePluginPath(entry) {
  const rawPath = String(entry.path || "");
  const browserPath = rawPath.startsWith("/gui_js/") ? `./${rawPath.slice("/gui_js/".length)}` : rawPath;
  const url = new URL(browserPath, window.location.href);
  const rev = entry.rev || entry.cacheBust || entry.updated_at || entry.updatedAt;
  if (rev) url.searchParams.set("rev", rev);
  return url.toString();
}

async function loadPlugins() {
  let discovered = [];
  try {
    const response = await fetch(`${serverBase()}/v1/gui_js/plugins`, { cache: "no-store", headers: requestHeaders() });
    if (response.ok) discovered = (await response.json())?.plugins || [];
  } catch (_err) {}
  if (!discovered.length) {
    const response = await fetch("./plugins/manifest.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`Plugin discovery failed: HTTP ${response.status}`);
    discovered = (await response.json())?.plugins || [];
  }
  const entries = discovered
    .filter((entry) => entry?.path && pluginEnabled(pluginIdFromEntry(entry)))
    .sort((a, b) => {
      const pa = pluginIdFromEntry(a);
      const pb = pluginIdFromEntry(b);
      const ra = playgroundPreloadRank(pa);
      const rb = playgroundPreloadRank(pb);
      return ra - rb || String(pa).localeCompare(String(pb));
    });
  for (const entry of entries) {
    const pluginId = pluginIdFromEntry(entry);
    try {
      const module = await import(resolvePluginPath(entry));
      const plugin = module.default || module.plugin || module;
      if (!plugin) continue;
      app.plugins.set(pluginId, plugin);
      if (typeof plugin.register === "function") plugin.register(createPluginHost(pluginId));
      else if (typeof plugin.init === "function") plugin.init(createPluginHost(pluginId));
    } catch (error) {
      console.warn(`[playground] failed to load ${pluginId}`, error);
      if (pluginId === targetPluginId) throw error;
    }
  }
}

function updateScope(scope = {}) {
  const pid = String(scope.pid || state.ui.activePid || "");
  const sid = String(scope.sid || state.ui.activeSid || "");
  state.ui.activePid = pid;
  state.ui.activeSid = sid;
  const projectName = String(scope.projectName || state.projects?.[pid]?.name || pid || "No project");
  const sessionName = String(scope.sessionName || state.sessions?.[sid]?.title || sid || "No session");
  dom.projectName.textContent = projectName;
  dom.sessionName.textContent = sessionName;
  const link = new URL("./chat_js.htm", window.location.href);
  if (pid) link.searchParams.set("pid", pid);
  if (sid) link.searchParams.set("sid", sid);
  dom.scopeLink.href = link.toString();
}

async function loadSessionMessages() {
  const pid = String(state.ui.activePid || "");
  const sid = String(state.ui.activeSid || "");
  if (!pid || !sid || !state.auth?.token) return [];
  try {
    const data = await apiJson(`/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/messages?limit=200&tail=1`, {
      headers: { "X-Project-ID": pid, "X-Session-ID": sid },
    });
    const session = state.sessions[sid] || { pid, sid, title: sid };
    session.messages = Array.isArray(data?.messages) ? data.messages : [];
    state.sessions[sid] = session;
    return session.messages;
  } catch (_err) {
    return [];
  }
}

function setConnected(label = "Connected", error = false) {
  dom.connectionLabel.textContent = label;
  dom.connectionStatus.classList.toggle("connected", !error);
  dom.connectionStatus.classList.toggle("error", error);
}

function toolbarStateKey() {
  return `llmloader2.playground.layout.${targetPluginId || "default"}`;
}

function readToolbarState() {
  try { return JSON.parse(localStorage.getItem(toolbarStateKey()) || "{}"); }
  catch (_err) { return {}; }
}

function setToolbarExpanded(which, expanded) {
  const shell = which === "top" ? dom.topShell : dom.bottomShell;
  const toggle = which === "top" ? dom.topToggle : dom.bottomToggle;
  shell.classList.toggle("collapsed", !expanded);
  toggle.setAttribute("aria-expanded", String(Boolean(expanded)));
  const layout = readToolbarState();
  layout[which] = Boolean(expanded);
  localStorage.setItem(toolbarStateKey(), JSON.stringify(layout));
}

function renderPlaygroundAssets(area, container, ctx) {
  app.playgroundAssets
    .filter((entry) => entry.targetPluginId === targetPluginId && entry.area === area)
    .sort((a, b) => b.priority - a.priority || a.pluginId.localeCompare(b.pluginId))
    .forEach((entry) => attachResult(container, entry.render(container, ctx)));
}

function renderPlayground() {
  const spec = app.playgrounds.find((entry) => entry.pluginId === targetPluginId && (!query.get("view") || entry.id === query.get("view")));
  app.activeSpec = spec || null;
  dom.canvas.replaceChildren();
  dom.topToolbar.replaceChildren();
  dom.bottomToolbar.replaceChildren();
  if (!spec) {
    dom.pluginTitle.textContent = targetPluginId || "Plugin Playground";
    dom.topShell.classList.add("empty");
    dom.bottomShell.classList.add("empty");
    return;
  }
  dom.pluginTitle.textContent = spec.title;
  document.title = `${spec.title} - Playground`;
  const ctx = pluginContext();
  if (typeof spec.renderCanvas === "function") attachResult(dom.canvas, spec.renderCanvas(dom.canvas, ctx));
  if (typeof spec.renderTopToolbar === "function") attachResult(dom.topToolbar, spec.renderTopToolbar(dom.topToolbar, ctx));
  if (typeof spec.renderBottomToolbar === "function") attachResult(dom.bottomToolbar, spec.renderBottomToolbar(dom.bottomToolbar, ctx));
  renderPlaygroundAssets("canvas", dom.canvas, ctx);
  renderPlaygroundAssets("top-toolbar", dom.topToolbar, ctx);
  renderPlaygroundAssets("bottom-toolbar", dom.bottomToolbar, ctx);
  dom.topShell.classList.toggle("empty", !dom.topToolbar.childNodes.length);
  dom.bottomShell.classList.toggle("empty", !dom.bottomToolbar.childNodes.length);
  const layout = readToolbarState();
  setToolbarExpanded("top", layout.top === true);
  setToolbarExpanded("bottom", layout.bottom === true);
}

function targetPanel() {
  return app.panels.find((entry) => entry.pluginId === targetPluginId)?.tab || null;
}

function settingsProviders() {
  const pluginIds = new Set([targetPluginId]);
  app.playgroundAssets.forEach((asset) => {
    if (asset.targetPluginId === targetPluginId && asset.settings !== false) pluginIds.add(asset.pluginId);
  });
  return [...pluginIds].map((pluginId) => {
    const entry = app.panels.find((row) => row.pluginId === pluginId);
    return entry ? { pluginId, panel: entry.tab } : null;
  }).filter(Boolean);
}

function closeSettingsMenu() {
  dom.settingsMenu.hidden = true;
  dom.settingsButton.setAttribute("aria-expanded", "false");
}

function openSettings(provider = null) {
  const selected = provider || settingsProviders()[0] || null;
  const panel = selected?.panel || selected || targetPanel();
  if (!panel) return;
  closeSettingsMenu();
  dom.settingsBody.replaceChildren();
  dom.settingsBody.className = "pg-settings-body";
  dom.settingsTitle.textContent = panel.title || `${app.activeSpec?.title || targetPluginId} settings`;
  const render = panel.renderFull || panel.render;
  if (typeof render === "function") Promise.resolve(render(dom.settingsBody, pluginContext())).catch((error) => {
    dom.settingsBody.textContent = error.message || String(error);
  });
  if (!dom.settingsDialog.open) dom.settingsDialog.showModal();
}

function handleSettingsButton() {
  const providers = settingsProviders();
  if (providers.length <= 1) {
    openSettings(providers[0] || null);
    return;
  }
  dom.settingsMenu.replaceChildren();
  providers.forEach((provider) => {
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("role", "menuitem");
    button.textContent = provider.panel.title || provider.pluginId;
    button.addEventListener("click", () => openSettings(provider));
    dom.settingsMenu.appendChild(button);
  });
  dom.settingsMenu.hidden = !dom.settingsMenu.hidden;
  dom.settingsButton.setAttribute("aria-expanded", String(!dom.settingsMenu.hidden));
}

function dispatchPluginEvent(event, data) {
  app.eventHandlers.forEach((handler) => {
    try { handler.fn(event, data, pluginContext()); }
    catch (error) { console.warn(`[playground] ${handler.pluginId} event failed`, error); }
  });
  if (typeof app.activeSpec?.onEvent === "function") {
    try { app.activeSpec.onEvent(event, data, pluginContext()); } catch (_err) {}
  }
}

const channel = typeof BroadcastChannel === "function" ? new BroadcastChannel(PLAYGROUND_CHANNEL_NAME) : null;
let presenceTimer = null;

function publishPresence(active = true) {
  channel?.postMessage({
    type: "playground-presence",
    pluginId: targetPluginId,
    active,
    at: Date.now(),
  });
}

if (channel) {
  channel.addEventListener("message", (event) => {
    const message = event.data || {};
    if (message.type === "scope") {
      updateScope(message.payload || message.scope || {});
      void loadSessionMessages();
      return;
    }
    if (message.type !== "plugin-event") return;
    const scope = message.scope || {};
    if (scope.sid && state.ui.activeSid && scope.sid !== state.ui.activeSid) return;
    const payload = message.payload || {};
    const sid = String(scope.sid || payload.data?.sid || state.ui.activeSid || "");
    const duplicateLocalStream = Number(app.localStreamsBySid.get(sid) || 0) > 0
      || Date.now() < Number(app.localStreamSuppressUntil.get(sid) || 0);
    let eventName = payload.event === "tokens" ? "token" : payload.event;
    const origin = String(payload.origin || payload.source || "");
    if (duplicateLocalStream && origin === "playground" && ["token", "assistant_done", "done", "message"].includes(eventName)) return;
    const data = payload.data || {};
    if (eventName === "message"
        && data && typeof data === "object"
        && !data.msg && !data.message
        && (data.text || data.content || data.token || data.delta)) {
      eventName = "token";
    }
    if (eventName === "token" && data && typeof data === "object" && !data.text) {
      data.text = String(data.content || data.token || data.delta || "");
    }
    dispatchPluginEvent(eventName, data);
    if (["assistant_done", "done", "message"].includes(eventName)) void loadSessionMessages();
  });
}

dom.topToggle.addEventListener("click", () => setToolbarExpanded("top", dom.topShell.classList.contains("collapsed")));
dom.bottomToggle.addEventListener("click", () => setToolbarExpanded("bottom", dom.bottomShell.classList.contains("collapsed")));
dom.settingsButton.addEventListener("click", (event) => {
  event.stopPropagation();
  handleSettingsButton();
});
dom.settingsClose.addEventListener("click", () => dom.settingsDialog.close());
dom.settingsDialog.addEventListener("click", (event) => {
  if (event.target === dom.settingsDialog) dom.settingsDialog.close();
});
document.addEventListener("click", (event) => {
  if (dom.settingsMenu.hidden) return;
  if (dom.settingsMenu.contains(event.target) || dom.settingsButton.contains(event.target)) return;
  closeSettingsMenu();
});

window.addEventListener("storage", (event) => {
  if (event.key !== STORAGE_PREFS_KEY || !event.newValue) return;
  try {
    const incoming = JSON.parse(event.newValue);
    if (incoming.pluginPrefs) state.pluginPrefs = mergeDeep(state.pluginPrefs, incoming.pluginPrefs);
    if (incoming.ui) updateScope(incoming.ui);
    if (typeof app.activeSpec?.onStateChange === "function") app.activeSpec.onStateChange(pluginContext());
  } catch (_err) {}
});

window.addEventListener("beforeunload", () => {
  publishPresence(false);
  if (presenceTimer) clearInterval(presenceTimer);
  cleanupTasks.splice(0).forEach((cleanup) => { try { cleanup(); } catch (_err) {} });
  channel?.close();
});

async function boot() {
  updateScope();
  try {
    await loadPlugins();
    renderPlayground();
    await loadSessionMessages();
    dom.settingsButton.disabled = settingsProviders().length === 0;
    dom.settingsButton.setAttribute("aria-haspopup", settingsProviders().length > 1 ? "menu" : "dialog");
    dom.settingsButton.setAttribute("aria-expanded", "false");
    setConnected("Connected");
    publishPresence(true);
    presenceTimer = setInterval(() => publishPresence(true), 5000);
    channel?.postMessage({ type: "request-scope", pluginId: targetPluginId, at: Date.now() });
  } catch (error) {
    setConnected("Plugin load failed", true);
    const note = document.createElement("div");
    note.className = "pg-error";
    note.textContent = error.message || String(error);
    dom.canvas.replaceChildren(note);
  }
}

void boot();
