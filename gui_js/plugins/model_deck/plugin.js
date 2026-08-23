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
  "speech_asr",
  "speech_tts",
  "image_gen",
  "video_gen",
];
const OVERVIEW_TYPE_IDS = new Set(DEFAULT_TYPE_ORDER);
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

const ASR_PRESET_TEMPLATE_JSON = {
  generic_asr: {
    argv: ["--backend", "{speech_backend}", "-m", "{model_path}", "-f", "{audio_path}"],
    optional: [
      { setting: "language", flag: "-l" },
      { setting: "beam_size", flag: "-t" },
      { setting: "task", equals: "translate", flag: "--translate", mode: "bool_flag" },
      { setting: "vad", flag: "--vad", mode: "bool_flag" },
      { setting: "word_timestamps", flag: "-owts", mode: "bool_flag" },
    ],
    append_extra_args_setting: "speech_runtime_extra_args",
  },
};

const ASR_PRESET_ASSET_JSON = {
  generic_asr: {},
};

const ASR_PRESET_PARAM_JSON = {
  generic_asr: {
    language: "en",
    beam_size: 8,
    task: "transcribe",
    vad: true,
    word_timestamps: false,
  },
};

const TTS_PRESET_TEMPLATE_JSON = {
  chatterbox: {
    argv: ["--backend", "{speech_backend}", "-m", "{model_path}", "--tts", "{input_text}", "--tts-output", "{output_path}"],
    optional: [
      { setting: "companion_model_path", flag: "--codec-model" },
      { setting: "voice_path", flag: "--voice" },
      { setting: "language", flag: "-l" },
      { setting: "instruct_text", flag: "--instruct" },
      { setting: "temperature", flag: "--temperature" },
    ],
    append_extra_args_setting: "speech_runtime_extra_args",
  },
  kokoro: {
    argv: ["--backend", "{speech_backend}", "-m", "{model_path}", "--tts", "{input_text}", "--tts-output", "{output_path}"],
    optional: [
      { setting: "voice_path", flag: "--voice" },
      { setting: "language", flag: "-l" },
    ],
    append_extra_args_setting: "speech_runtime_extra_args",
  },
  vibevoice_custom: {
    argv: ["--backend", "{speech_backend}", "-m", "{model_path}", "--tts", "{input_text}", "--tts-output", "{output_path}"],
    optional: [
      { setting: "voice_path", flag: "--voice" },
      { setting: "language", flag: "-l" },
      { setting: "instruct_text", flag: "--instruct" },
      { setting: "temperature", flag: "--temperature" },
    ],
    append_extra_args_setting: "speech_runtime_extra_args",
  },
};

const TTS_PRESET_ASSET_JSON = {
  chatterbox: {
    companion_model_path: "C:/models/chatterbox-s3gen.gguf",
    voice_path: "C:/models/chatterbox-reference.wav",
  },
  kokoro: {
    voice_path: "C:/models/kokoro-voice.gguf",
  },
  vibevoice_custom: {
    voice_path: "C:/models/vibevoice-reference.wav",
    ref_text: "Optional transcript for the reference audio",
  },
};

const TTS_PRESET_PARAM_JSON = {
  chatterbox: {
    language: "en",
    instruct_text: "Optional style instruction",
    temperature: 0.8,
  },
  kokoro: {
    language: "en",
  },
  vibevoice_custom: {
    language: "en",
    instruct_text: "Optional style instruction",
    temperature: 0.7,
  },
};

const IMAGE_PRESET_TEMPLATE_JSON = {
  generic_diffusers: {
    argv: ["{python_bin}", "{script_path}", "--model", "{model_id}", "--prompt", "{prompt}", "--output", "{output_path}"],
    optional: [
      { setting: "negative_prompt", flag: "--negative-prompt" },
      { setting: "width", flag: "--width" },
      { setting: "height", flag: "--height" },
      { setting: "steps", flag: "--steps" },
      { setting: "guidance_scale", flag: "--guidance-scale" },
      { setting: "seed", flag: "--seed" },
    ],
    append_extra_args_setting: "image_runtime_extra_args",
  },
  flux_gguf_custom: {
    argv: ["{command_path}", "--model", "{gguf_path}", "--prompt", "{prompt}", "--output", "{output_path}"],
    optional: [
      { setting: "text_encoder_path", flag: "--text-encoder" },
      { setting: "vae_path", flag: "--vae" },
      { setting: "negative_prompt", flag: "--negative-prompt" },
      { setting: "width", flag: "--width" },
      { setting: "height", flag: "--height" },
      { setting: "steps", flag: "--steps" },
      { setting: "guidance_scale", flag: "--guidance-scale" },
      { setting: "seed", flag: "--seed" },
    ],
    append_extra_args_setting: "image_runtime_extra_args",
  },
  gguf_cli_custom: {
    argv: ["{command_path}", "--model", "{gguf_path}", "--prompt", "{prompt}", "--output", "{output_path}"],
    optional: [
      { setting: "negative_prompt", flag: "--negative-prompt" },
      { setting: "width", flag: "--width" },
      { setting: "height", flag: "--height" },
      { setting: "steps", flag: "--steps" },
      { setting: "guidance_scale", flag: "--guidance-scale" },
      { setting: "seed", flag: "--seed" },
    ],
    append_extra_args_setting: "image_runtime_extra_args",
  },
};

const IMAGE_PRESET_ASSET_JSON = {
  generic_diffusers: {
    python_bin: "python",
    script_path: "C:/tools/run_image_model.py",
  },
  flux_gguf_custom: {
    command_path: "C:/tools/flux_runner.exe",
    gguf_path: "C:/models/flux1-dev-q4_k_m.gguf",
    text_encoder_path: "C:/models/t5xxl_fp16.safetensors",
    vae_path: "C:/models/ae.safetensors",
  },
  gguf_cli_custom: {
    command_path: "C:/tools/image_gguf_cli.exe",
    gguf_path: "C:/models/model.gguf",
  },
};

const IMAGE_PRESET_PARAM_JSON = {
  generic_diffusers: {
    model_id: "black-forest-labs/FLUX.1-dev",
    width: 1024,
    height: 1024,
    steps: 28,
    guidance_scale: 3.5,
  },
  flux_gguf_custom: {
    width: 1024,
    height: 1024,
    steps: 28,
    guidance_scale: 3.5,
  },
  gguf_cli_custom: {
    width: 1024,
    height: 1024,
    steps: 28,
    guidance_scale: 3.5,
  },
};

const IMAGE_PRESET_REQUIREMENTS_TEXT = {
  generic_diffusers: "Requires a runnable Python image pipeline script plus torch, diffusers, transformers, and accelerate in that environment.",
  flux_gguf_custom: "Usually needs a custom Flux GGUF runner plus the GGUF base model and any companion text encoder / VAE files your runner expects.",
  gguf_cli_custom: "Requires an external image GGUF CLI that accepts prompt and output-path arguments.",
};

const IMAGE_PRESET_INSTALL_TEXT = {
  generic_diffusers: "Example:\\npip install torch diffusers transformers accelerate safetensors\\n# then point script_path to your custom launcher",
  flux_gguf_custom: "Example:\\n1. Build or download your Flux GGUF runner\\n2. Download the GGUF + companion encoder / VAE files\\n3. Point command_path and asset paths above",
  gguf_cli_custom: "Example:\\n1. Install your preferred GGUF image CLI\\n2. Fill command_path\\n3. Map any extra flags in the custom command template JSON",
};

const VIDEO_PRESET_TEMPLATE_JSON = {
  generic_diffusers: {
    argv: ["{python_bin}", "{script_path}", "--model", "{model_id}", "--prompt", "{prompt}", "--output", "{output_path}"],
    optional: [
      { setting: "negative_prompt", flag: "--negative-prompt" },
      { setting: "width", flag: "--width" },
      { setting: "height", flag: "--height" },
      { setting: "frames", flag: "--frames" },
      { setting: "fps", flag: "--fps" },
      { setting: "steps", flag: "--steps" },
      { setting: "guidance_scale", flag: "--guidance-scale" },
      { setting: "seed", flag: "--seed" },
    ],
    append_extra_args_setting: "video_runtime_extra_args",
  },
  wan_pipeline: {
    argv: ["{python_bin}", "{script_path}", "--model", "{model_id}", "--prompt", "{prompt}", "--output", "{output_path}"],
    optional: [
      { setting: "negative_prompt", flag: "--negative-prompt" },
      { setting: "width", flag: "--width" },
      { setting: "height", flag: "--height" },
      { setting: "frames", flag: "--frames" },
      { setting: "fps", flag: "--fps" },
      { setting: "steps", flag: "--steps" },
      { setting: "guidance_scale", flag: "--guidance-scale" },
      { setting: "seed", flag: "--seed" },
      { setting: "wan_vae_subfolder", flag: "--vae-subfolder" },
    ],
    append_extra_args_setting: "video_runtime_extra_args",
  },
};

const VIDEO_PRESET_ASSET_JSON = {
  generic_diffusers: {
    python_bin: "python",
    script_path: "C:/tools/run_video_model.py",
  },
  wan_pipeline: {
    python_bin: "python",
    script_path: "C:/tools/run_wan_video.py",
  },
};

const VIDEO_PRESET_PARAM_JSON = {
  generic_diffusers: {
    model_id: "genmo/mochi-1-preview",
    width: 848,
    height: 480,
    frames: 31,
    fps: 16,
    steps: 64,
    guidance_scale: 6.0,
  },
  wan_pipeline: {
    model_id: "Wan-AI/Wan2.1-T2V-1.3B-Diffusers",
    width: 832,
    height: 480,
    frames: 49,
    fps: 16,
    steps: 40,
    guidance_scale: 5.0,
    wan_vae_subfolder: "vae",
  },
};

const VIDEO_PRESET_REQUIREMENTS_TEXT = {
  generic_diffusers: "Requires a runnable Python video pipeline script plus torch, diffusers, transformers, and imageio-ffmpeg in that environment.",
  wan_pipeline: "Requires a Wan-capable diffusers environment and any optional Wan VAE assets your workflow expects.",
};

const VIDEO_PRESET_INSTALL_TEXT = {
  generic_diffusers: "Example:\\npip install torch diffusers transformers accelerate imageio imageio-ffmpeg\\n# then point script_path to your custom launcher",
  wan_pipeline: "Example:\\npip install torch diffusers transformers accelerate imageio imageio-ffmpeg\\n# then install any Wan-specific dependencies required by your script",
};

let processStream = { token: 0, controller: null };
let refreshProcessesPromise = null;
let refreshProcessesQueued = false;
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
const CACHE_KEY_MANAGED_STATUS_LIGHT = "managed_status_light";
const CACHE_KEY_MANAGED_DEVICE_PREFIX = "managed_devices:";
const CACHE_KEY_HOST_GPU_CHOICES = "host_gpu_choices";
const CACHE_TTL_DECK_MS = 300000;
const CACHE_TTL_POPOVER_MS = 15000;
const CACHE_TTL_EDITOR_MS = 120000;
const CACHE_TTL_MANAGED_SERVERS_MS = 15000;
const CACHE_TTL_MANAGED_STATUS_MS = 5000;
const CACHE_TTL_MANAGED_DEVICE_MS = 30000;
const CACHE_TTL_HOST_GPU_MS = 5000;
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

function getModelDeckFieldEnhancers(ctx) {
  const shared = ctx?.getSharedObjects?.({ type: "model_deck_field_enhancer" }) || [];
  return shared.filter((item) => item && typeof item === "object");
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

function mergeManagedServerLists(...lists) {
  const out = [];
  const seen = new Map();
  for (const list of lists) {
    for (const item of Array.isArray(list) ? list : []) {
      if (!item || typeof item !== "object") continue;
      const sid = String(item?.id || "").trim();
      const key = sid || String(item?.url || item?.llmloader_url || "").trim();
      if (!key) continue;
      const existingIndex = seen.get(key);
      if (existingIndex === undefined) {
        seen.set(key, out.length);
        out.push({ ...item });
        continue;
      }
      out[existingIndex] = { ...out[existingIndex], ...item };
    }
  }
  return out;
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
    if (!entry.server_running && String(entry.phase || "").trim().toLowerCase() === "stopped") {
      entry.loaded = false;
      return;
    }
    if (!entry.loaded && prevEntry.loaded && prevEntry.server_running) {
      if (!entry.server_running) {
        return;
      }
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

function ensureGuiPluginEnabled(ctx, pluginId) {
  const key = String(pluginId || "").trim();
  if (!key) return false;
  try {
    if (typeof ctx?.setPluginEnabled === "function") ctx.setPluginEnabled(key, true);
    if (typeof ctx?.requestPluginPriority === "function") ctx.requestPluginPriority(key, { position: "first" });
    if (typeof ctx?.requestPluginPreload === "function") ctx.requestPluginPreload(key, "gui");
  } catch (_err) {}
  if (!ctx?.state) return false;
  try {
    if (!ctx.state.pluginPrefs || typeof ctx.state.pluginPrefs !== "object") ctx.state.pluginPrefs = {};
    if (!ctx.state.pluginPrefs.enabled || typeof ctx.state.pluginPrefs.enabled !== "object") ctx.state.pluginPrefs.enabled = {};
    ctx.state.pluginPrefs.enabled[key] = true;
    if (Array.isArray(ctx.state.pluginPrefs.priority)) {
      ctx.state.pluginPrefs.priority = [key, ...ctx.state.pluginPrefs.priority.filter((id) => String(id || "") !== key)].slice(0, 50);
    }
    if (typeof ctx.saveState === "function") ctx.saveState();
    return true;
  } catch (_err) {
    return false;
  }
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

function sortManagedServers(servers) {
  const rows = Array.isArray(servers) ? servers.slice() : [];
  rows.sort((left, right) => {
    const aRunning = Boolean(left?.running || left?.server_running || left?.process_alive);
    const bRunning = Boolean(right?.running || right?.server_running || right?.process_alive);
    if (aRunning !== bRunning) return aRunning ? -1 : 1;
    const aUpdated = Number(left?.updated_at || left?.stopped_at || left?.started_at || 0);
    const bUpdated = Number(right?.updated_at || right?.stopped_at || right?.started_at || 0);
    if (aUpdated !== bUpdated) return bUpdated - aUpdated;
    const aName = String(left?.name || left?.id || left?.url || "").toLowerCase();
    const bName = String(right?.name || right?.id || right?.url || "").toLowerCase();
    return aName.localeCompare(bName);
  });
  return rows;
}

function getProcessManagedServers(ctx, seedProcesses = null) {
  const out = [];
  try {
    const proc = seedProcesses || ctx?.state?.modelDeckState?.processes || ctx?.state?.processes || null;
    for (const entry of [proc?.main, ...(Array.isArray(proc?.defaults) ? proc.defaults : [])]) {
      const managed = entry?.managed_server;
      if (!managed || typeof managed !== "object") continue;
      if (!(managed.llmloader_url || managed.url)) continue;
      out.push(managed);
    }
  } catch (_err) {}
  return sortManagedServers(mergeManagedServerLists(out));
}

async function getManagedLlamaServers(ctx, seedProcesses = null, options = {}) {
  const forceFresh = Boolean(options && options.forceFresh);
  const processServers = getProcessManagedServers(ctx, seedProcesses);
  const cached = forceFresh ? null : cacheGet(ctx, CACHE_KEY_MANAGED_SERVERS);
  const cachedServers = Array.isArray(cached) ? sortManagedServers(cached) : [];
  try {
    let payload = forceFresh ? null : cacheGet(ctx, CACHE_KEY_MANAGED_STATUS_LIGHT);
    if (!(payload && typeof payload === "object" && Array.isArray(payload.servers))) {
      payload = await apiJson(ctx, "/v1/llama_server/status?lightweight=1");
      cacheSet(ctx, CACHE_KEY_MANAGED_STATUS_LIGHT, payload || {}, CACHE_TTL_MANAGED_STATUS_MS);
    }
    const servers = Array.isArray(payload?.servers) ? payload.servers : [];
    const filtered = servers.filter((item) => item && (item.llmloader_url || item.url));
    const merged = sortManagedServers(mergeManagedServerLists(filtered, cachedServers));
    cacheSet(ctx, CACHE_KEY_MANAGED_SERVERS, merged, CACHE_TTL_MANAGED_SERVERS_MS);
    return merged;
  } catch (_err) {
    return sortManagedServers(mergeManagedServerLists(processServers, cachedServers));
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

function isGenericDisplayAdapterLabel(label) {
  const text = String(label || "").trim().toLowerCase();
  return text === "microsoft display adapter"
    || text === "microsoft basic display adapter"
    || text === "microsoft remote display adapter";
}

function normalizeHostGpuChoices(payload) {
  const devices = Array.isArray(payload?.devices) ? payload.devices : [];
  const out = [];
  const seen = new Set();
  for (const item of devices) {
    const value = String(item?.value ?? "").trim();
    const label = String(item?.label ?? "").trim();
    if (!value || !label) continue;
    if (seen.has(value)) continue;
    seen.add(value);
    out.push({ value, label });
  }
  return out;
}

function normalizeEmbeddedFallbackChoices(choices, deviceKind) {
  const kind = String(deviceKind || "").trim().toLowerCase();
  const rows = Array.isArray(choices) ? choices : [];
  const filtered = [];
  const matchers = {
    xpu: (label) => /\bintel\b|\barc\b/i.test(label),
    cuda: (label) => /\bnvidia\b|\bgeforce\b|\brtx\b|\bquadro\b|\btesla\b/i.test(label),
    vulkan: (label) => !isGenericDisplayAdapterLabel(label),
    cpu: () => false,
    mps: (label) => /\bapple\b|\bm\d\b/i.test(label),
  };
  const matcher = matchers[kind];
  if (!matcher) return [];
  for (const row of rows) {
    const label = String(row?.label || "").trim();
    if (!label || isGenericDisplayAdapterLabel(label)) continue;
    if (!matcher(label)) continue;
    filtered.push({ label });
  }
  return filtered.map((row, idx) => ({ value: String(idx), label: row.label }));
}

async function getHostGpuChoices(ctx, options = {}) {
  const forceFresh = Boolean(options && options.forceFresh);
  if (!forceFresh) {
    const cached = cacheGet(ctx, CACHE_KEY_HOST_GPU_CHOICES);
    if (Array.isArray(cached) && cached.length) return cached;
  }
  try {
    const payload = await apiJson(ctx, `/v1/llama_server/host_gpus?refresh=${forceFresh ? 1 : 0}`);
    const choices = normalizeHostGpuChoices(payload);
    if (choices.length) {
      cacheSet(ctx, CACHE_KEY_HOST_GPU_CHOICES, choices, CACHE_TTL_HOST_GPU_MS);
    }
    return choices;
  } catch (_err) {
    const cached = cacheGet(ctx, CACHE_KEY_HOST_GPU_CHOICES);
    return Array.isArray(cached) ? cached : [];
  }
}

function hasNamedGpuChoices(choices) {
  return Array.isArray(choices) && choices.some((item) => {
    const label = String(item?.label || "").trim();
    return !!label && !/^GPU\s+\d+$/i.test(label) && !isGenericDisplayAdapterLabel(label);
  });
}

async function getManagedLlamaDeviceChoices(ctx, managedServers, managedId, options = {}) {
  const forceFresh = Boolean(options && options.forceFresh);
  const server = (Array.isArray(managedServers) ? managedServers : []).find((item) => String(item?.id || "") === String(managedId || ""));
  if (!server) return [];
  const installId = String(server.install_id || "").trim();
  const runtimeId = String(server.runtime_id || "").trim().toLowerCase();
  if (!installId && !runtimeId) return [];
  const cacheKey = `${CACHE_KEY_MANAGED_DEVICE_PREFIX}${managedId || installId || runtimeId}`;
  const selected = String(server?.selected_device || server?.server_device || "").trim();
  const mainGpu = String(server?.main_gpu ?? "").trim();
  if (!forceFresh) {
    const cached = cacheGet(ctx, cacheKey);
    if (Array.isArray(cached) && cached.length) {
      const genericCached = cached.every((item) => /^GPU\s+\d+$/i.test(String(item?.label || "").trim()));
      if (!genericCached) return cached;
    }
  }
  try {
    const qs = installId
      ? `install_id=${encodeURIComponent(String(installId))}`
      : `runtime_id=${encodeURIComponent(String(runtimeId || ""))}`;
    const payload = await apiJson(ctx, `/v1/llama_server/devices?${qs}`);
    const choices = parseManagedDeviceChoices(payload?.devices || payload?.lines || []);
    if (choices.length) cacheSet(ctx, cacheKey, choices, CACHE_TTL_MANAGED_DEVICE_MS);
    return choices;
  } catch (_err) {
    const hostChoices = await getHostGpuChoices(ctx, { forceFresh });
    const mainGpuIndex = Number.parseInt(mainGpu, 10);
    if (Number.isFinite(mainGpuIndex) && mainGpuIndex >= 0 && mainGpuIndex < hostChoices.length) {
      const hostLabel = String(hostChoices[mainGpuIndex]?.label || "").trim();
      if (hostLabel && !isGenericDisplayAdapterLabel(hostLabel)) {
        const fallback = [{ value: String(mainGpuIndex), label: hostLabel }];
        cacheSet(ctx, cacheKey, fallback, CACHE_TTL_MANAGED_DEVICE_MS);
        return fallback;
      }
    }
    if (!forceFresh && selected && mainGpu && !isGenericDisplayAdapterLabel(selected)) {
      const fallback = [{ value: mainGpu, label: selected }];
      cacheSet(ctx, cacheKey, fallback, CACHE_TTL_MANAGED_DEVICE_MS);
      return fallback;
    }
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

async function refreshAndShareModelContext(host, ctx, procSnapshot = null) {
  if (!host || !ctx) return;
  const proc = (procSnapshot && typeof procSnapshot === "object")
    ? procSnapshot
    : (deckState.processes && typeof deckState.processes === "object" && Object.keys(deckState.processes).length
      ? deckState.processes
      : null);
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
.md-compat-section {
  border: 1px solid color-mix(in srgb, var(--accent) 28%, var(--line) 72%);
  border-radius: 16px;
  padding: 14px;
  background: color-mix(in srgb, var(--panel) 90%, white 10%);
  box-shadow: inset 0 0 0 1px rgba(var(--accent-rgb), 0.05);
}
.md-compat-section .md-card {
  border-radius: 12px;
}
.md-collapsible-section > summary {
  cursor: pointer;
  list-style: none;
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 4px;
  font-weight: 600;
}
.md-collapsible-section > summary::-webkit-details-marker { display: none; }
.md-collapsible-section > summary::before {
  content: "▸";
  color: var(--ui-muted);
  margin-right: 2px;
}
.md-collapsible-section[open] > summary::before {
  content: "▾";
}
.md-collapsible-section > summary + * {
  margin-top: 10px;
}
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
.mdhf-modal {
  position: fixed;
  inset: 0;
  background: rgba(24, 19, 16, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  z-index: 2147483647;
}
.mdhf-card {
  width: min(980px, 96vw);
  max-height: min(86vh, 960px);
  overflow: auto;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 18px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-shadow: var(--shadow);
}
.mdhf-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.mdhf-title { font-size: 20px; font-weight: 800; color: var(--ink); }
.mdhf-sub { color: var(--ui-muted); font-size: 13px; line-height: 1.5; margin-top: 4px; }
.mdhf-close {
  border: 1px solid var(--border);
  background: transparent;
  color: var(--ink);
  border-radius: 12px;
  min-width: 72px;
  height: 40px;
  padding: 0 14px;
  line-height: 1;
  font-size: 13px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-sizing: border-box;
}
.mdhf-close:hover {
  background: rgba(var(--ink-rgb), 0.04);
}
.mdhf-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}
.mdhf-btn {
  appearance: none;
  min-height: 34px;
  padding: 0 12px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: rgba(var(--panel-rgb), 0.92);
  color: var(--ui-ink);
  font-size: 13px;
  font-weight: 600;
  line-height: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  white-space: nowrap;
  cursor: pointer;
  box-sizing: border-box;
}
.mdhf-btn:hover {
  background: rgba(var(--ink-rgb), 0.05);
}
.mdhf-btn.primary {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}
.mdhf-btn.primary:hover {
  filter: brightness(1.03);
}
.mdhf-btn.ghost {
  background: transparent;
}
.mdhf-btn:disabled,
.mdhf-close:disabled {
  opacity: 0.6;
  cursor: default;
}
.mdhf-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:10px; }
.mdhf-toggle-row { display:flex; gap:12px; flex-wrap:wrap; align-items:center; }
.mdhf-checklabel { display:inline-flex; gap:8px; align-items:center; color:var(--ui-ink); }
.mdhf-status-card { border:1px solid var(--border); border-radius:14px; padding:12px; background:color-mix(in srgb, var(--panel) 78%, white 22%); display:flex; flex-direction:column; gap:6px; }
.mdhf-status-title { font-size:12px; text-transform:uppercase; letter-spacing:0.08em; color:var(--ui-muted); }
.mdhf-status-main { font-size:16px; font-weight:700; color:var(--ui-ink); }
.mdhf-status-meta { font-size:12px; color:var(--ui-muted); }
.mdhf-legend { border:1px solid var(--border); border-radius:12px; padding:10px 12px; }
.mdhf-legend-title { cursor:pointer; font-weight:600; }
.mdhf-legend-grid { display:grid; gap:8px; margin-top:10px; }
.mdhf-legend-item { display:grid; grid-template-columns:auto 1fr; gap:8px; align-items:start; }
.mdhf-repo-list { display:grid; gap:12px; }
.mdhf-repo-card { border:1px solid var(--border); border-radius:14px; padding:12px; background:rgba(var(--panel-rgb), 0.55); }
.mdhf-repo-summary { display:flex; align-items:center; justify-content:space-between; gap:12px; cursor:pointer; list-style:none; }
.mdhf-repo-summary::-webkit-details-marker { display:none; }
.mdhf-repo-id { font-weight:700; color:var(--ui-ink); word-break:break-word; }
.mdhf-repo-meta, .mdhf-note { color:var(--ui-muted); font-size:12px; }
.mdhf-repo-count { font-size:12px; color:var(--ui-muted); white-space:nowrap; }
.mdhf-repo-head { display:flex; align-items:center; justify-content:space-between; gap:10px; margin-top:8px; margin-bottom:8px; flex-wrap:wrap; }
.mdhf-file-list { display:grid; gap:8px; }
.mdhf-file-row { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:10px; align-items:center; border:1px solid rgba(var(--ink-rgb), 0.08); border-radius:12px; padding:10px; background:rgba(var(--panel-rgb), 0.72); }
.mdhf-file-name { font-weight:600; color:var(--ui-ink); word-break:break-word; }
.mdhf-badge-row { display:flex; gap:6px; flex-wrap:wrap; margin-top:6px; }
.mdhf-badge { display:inline-flex; align-items:center; border:1px solid var(--border); border-radius:999px; padding:2px 8px; font-size:10px; letter-spacing:0.06em; text-transform:uppercase; color:var(--ui-ink); background:rgba(var(--panel-rgb), 0.72); }
.mdhf-badge.ok { color:#2ca65a; border-color:rgba(44, 166, 90, 0.28); background:rgba(44, 166, 90, 0.10); }
.mdhf-badge.warn { color:#b7791f; border-color:rgba(183, 121, 31, 0.28); background:rgba(183, 121, 31, 0.10); }
.mdhf-badge.danger { color:#d55a5a; border-color:rgba(213, 90, 90, 0.28); background:rgba(213, 90, 90, 0.10); }
.mdhf-badge.best { color:var(--accent); border-color:rgba(var(--accent-rgb), 0.32); background:rgba(var(--accent-rgb), 0.12); }
.mdhf-link { color: var(--accent); text-decoration: none; }
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
  const headers = { "X-Gui-Enabled-Plugins": "collab_chat,model_deck,llama_server_manager" };
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

function toast(ctx, message, isError = false) {
  const text = String(message || "").trim();
  if (!text) return;
  try {
    if (typeof ctx?.toast === "function") {
      ctx.toast(text, { error: Boolean(isError) });
      return;
    }
    if (typeof ctx?.notify === "function") {
      ctx.notify(text, { type: isError ? "error" : "info" });
      return;
    }
    if (typeof ctx?.log === "function") {
      ctx.log(text, isError ? "error" : "info");
      return;
    }
  } catch (_err) {}
  try {
    const fn = isError ? console.warn : console.info;
    fn.call(console, `[model_deck] ${text}`);
  } catch (_err) {}
}

function ensureRouterState(ctx) {
  if (!ctx?.state) return;
  if (!ctx.state.router || typeof ctx.state.router !== "object") ctx.state.router = {};
  if (!ctx.state.router.settings || typeof ctx.state.router.settings !== "object") ctx.state.router.settings = {};
  if (!ctx.state.router.enabled || typeof ctx.state.router.enabled !== "object") ctx.state.router.enabled = {};
}

function setRouterSettings(ctx, sid, pluginId, values) {
  if (typeof ctx?.setRouterSettings === "function") {
    ctx.setRouterSettings(sid, pluginId, values, ctx?.state?.ui?.activePid);
    return;
  }
  ensureRouterState(ctx);
  if (!ctx?.state?.router) return;
  const key = String(sid || "");
  if (!ctx.state.router.settings[key] || typeof ctx.state.router.settings[key] !== "object") {
    ctx.state.router.settings[key] = {};
  }
  ctx.state.router.settings[key][pluginId] = values || {};
  ctx.saveState?.();
}

function getRouterSettings(ctx, sid, pluginId) {
  if (typeof ctx?.getRouterConfig === "function") {
    const cfg = ctx.getRouterConfig(sid, ctx?.state?.ui?.activePid) || {};
    const settings = cfg.settings && typeof cfg.settings === "object" ? cfg.settings : {};
    const row = settings[pluginId];
    return row && typeof row === "object" ? row : {};
  }
  ensureRouterState(ctx);
  const key = String(sid || "");
  const settings = ctx?.state?.router?.settings?.[key];
  const row = settings && typeof settings === "object" ? settings[pluginId] : null;
  return row && typeof row === "object" ? row : {};
}

function formatStatus(entry) {
  if (!entry) return "";
  if (entry.kind === "worker") return entry.alive ? "running" : "stopped";
  if (entry.phase) return String(entry.phase);
  if (entry.loaded) return "loaded";
  if (entry.backend_mode === "llama_server" && entry.server_running) return "server running";
  return "stopped";
}

function isRunning(entry) {
  if (!entry) return false;
  if (entry.kind === "worker") return Boolean(entry.alive);
  const phase = String(entry.phase || "").trim().toLowerCase();
  if (phase === "stopped" || phase === "failed" || phase === "unsupported") return false;
  if (entry.loaded) return true;
  return Boolean(entry.backend_mode === "llama_server" && entry.server_running);
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
      server_running: Boolean(main.server_running),
      backend_mode: main.backend_mode || "",
      phase: main.phase || "",
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
      server_running: Boolean(entry.server_running),
      backend_mode: entry.backend_mode || "",
      phase: entry.phase || "",
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
  deckState.loading = true;
  try {
    const [proc, managed] = await Promise.all([
      apiJson(ctx, "/v1/model_deck/processes?include_managed=0"),
      apiJson(ctx, "/v1/model_deck/processes?managed_detail=light").catch(() => ({})),
    ]);
    deckState.processes = mergeManagedProcessSnapshot(
      stabilizeManagedProcessSnapshot(deckState.processes, proc || {}),
      managed || {}
    );
    cacheSet(ctx, CACHE_KEY_POPOVER_PROCESSES, deckState.processes, CACHE_TTL_POPOVER_MS);
  } catch (_err) {
    deckState.processes = {};
  }
  const entries = buildProcessEntries(deckState.processes);
  entries.forEach((entry) => {
    const key = deckEntryKey(entry);
    const pending = deckPending.get(key);
    if (!pending) return;
    if (pending === "start" && isRunning(entry)) deckPending.delete(key);
    if (pending === "stop" && !isRunning(entry)) deckPending.delete(key);
  });
  updateDeckBadge(countRunning(entries));
  deckState.loading = false;
  if (render) renderDeckPopover(ctx);
  // Share current model context for other plugins (e.g. Page JSON Retriever token budgeting).
  try {
    if (deckState.host) {
      await refreshAndShareModelContext(deckState.host, ctx, deckState.processes);
    }
  } catch (_err) {}
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
  const target = isRunning(entry) ? "/v1/model_deck/processes/stop" : "/v1/model_deck/processes/start";
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
    empty.textContent = deckState.loading ? "Loading model status..." : "No models loaded.";
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
    const hadCache = applyCachedDeckProcesses(ctx);
    if (!hadCache) deckState.loading = true;
    renderDeckPopover(ctx);
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
  const entries = Object.entries(types || {}).filter(([tid, t]) => {
    const typeId = String(tid || "").trim();
    if (!OVERVIEW_TYPE_IDS.has(typeId)) return false;
    return !!t && typeof t === "object" && !Array.isArray(t);
  });
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
      const openTypeModels = () => {
        state.activeTypeId = tid;
        setActiveTab("models");
        renderModels();
      };
      const typeBtn = document.createElement("button");
      typeBtn.type = "button";
      typeBtn.className = "md-link-btn";
      typeBtn.textContent = tid;
      typeBtn.title = `Open ${tid} models`;
      typeBtn.addEventListener("click", openTypeModels);
      const countBtn = document.createElement("button");
      countBtn.type = "button";
      countBtn.className = "md-link-btn md-overview-count-btn";
      countBtn.textContent = String(models.length);
      countBtn.title = "Edit this model type";
      countBtn.addEventListener("click", openTypeModels);
      const actions = createActionSelect([
        {
          value: "edit",
          label: "Edit",
          onSelect: openTypeModels,
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
          typeBtn,
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

    if (!state.activeTypeId && typeEntries.length) {
      state.activeTypeId = typeEntries[0][0];
    }

    const t = types[state.activeTypeId];
    if (!t) {
      const empty = document.createElement("div");
      empty.className = "md-muted";
      empty.textContent = "No model type selected.";
      target.appendChild(empty);
      return;
    }

    const typeSummary = document.createElement("div");
    typeSummary.className = "md-muted";
    typeSummary.textContent = `Type: ${t.label || state.activeTypeId}`;
    target.appendChild(typeSummary);

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
    deckState.processes = state.processes || {};
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

  function applyDeckOnlyCache(deck) {
    if (!deck || typeof deck !== "object") return false;
    state.deck = deck;
    if (!state.activeTypeId) {
      const ordered = sortTypes(state.deck?.types || {});
      if (ordered.length) state.activeTypeId = ordered[0][0];
    }
    renderOverview();
    renderModels();
    return true;
  }

  async function reloadAll() {
    statusLabel.textContent = "Loading...";
    try {
      const deckPromise = apiJson(ctx, "/v1/model_deck/deck");
      const metaPromise = Promise.all([
        apiJson(ctx, "/v1/model_deck/type_templates"),
        apiJson(ctx, "/v1/model_deck_loader/schema"),
        apiJson(ctx, "/v1/model_deck/status"),
      ]);

      const deck = await deckPromise;
      const nextDeck = deck?.deck || {};
      applyDeckOnlyCache(nextDeck);
      cacheSet(ctx, CACHE_KEY_DECK, nextDeck, CACHE_TTL_DECK_MS);
      statusLabel.textContent = "Loading metadata...";

      const [tpl, sch, st] = await metaPromise;
      const bootstrap = {
        templates: tpl?.templates || {},
        schemas: sch?.schemas || {},
        deck: nextDeck,
        loaderIds: st?.loader_ids || [],
        processes: state.processes || {},
      };
      applyEditorBootstrap(bootstrap);
      cacheSet(ctx, CACHE_KEY_EDITOR_BOOTSTRAP, bootstrap, CACHE_TTL_EDITOR_MS);
      statusLabel.textContent = "OK";
      void refreshProcesses();
    } catch (err) {
      statusLabel.textContent = `Error: ${err.message || err}`;
    }
  }

  async function refreshProcesses() {
    if (refreshProcessesPromise) {
      refreshProcessesQueued = true;
      return refreshProcessesPromise;
    }
    refreshProcessesPromise = (async () => {
      try {
        const managedDetail = state.activeTab === "processes" ? "full" : "light";
        const [proc, managed] = await Promise.all([
          apiJson(ctx, "/v1/model_deck/processes?include_managed=0"),
          apiJson(ctx, `/v1/model_deck/processes?managed_detail=${managedDetail}`).catch(() => ({})),
        ]);
        state.processes = mergeManagedProcessSnapshot(
          stabilizeManagedProcessSnapshot(state.processes, proc || {}),
          managed || {}
        );
        deckState.processes = state.processes || {};
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
      } finally {
        refreshProcessesPromise = null;
        if (refreshProcessesQueued) {
          refreshProcessesQueued = false;
          void refreshProcesses();
        }
      }
    })();
    try {
      return await refreshProcessesPromise;
    } finally {}
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
    let managedServersLoaded = false;
    let managedServersLoading = false;
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
    let managedServersLoadPromise = null;
    let managedServersLoadedAt = 0;
    let workflowTrainingArtifacts = [];
    let selectedCompatManifestId = String(model?.settings?.model_deck_compat_manifest_id || "").trim();
    let lastDownloadedHfRepoId = String(model?.settings?.hf_source_repo_id || "").trim();
    let lastDownloadedHfFilename = String(model?.settings?.hf_source_filename || "").trim();
    let hfSearchModeOverride = "";
    let requestCompatRefresh = () => {};
    const workflowTrainingEnabled = isWorkflowTrainingPluginEnabled(ctx);

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
    let searchBtn = null;
    function setAllEntriesDisplay(key, displayValue) {
      for (const entry of entries) {
        if (entry?.key === key && entry?.wrap) entry.wrap.style.display = displayValue;
      }
    }
    function getDeckSearchQuery() {
      const candidates = [
        model?.settings?.model_path,
        model?.settings?.model_id,
        model?.settings?.gguf_path,
        model?.model_id,
        modelIdField?.input?.value,
      ];
      for (const candidate of candidates) {
        const text = String(candidate || "").trim();
        if (!text) continue;
        const lowerText = text.toLowerCase();
        const last = text.split(/[\\/]/).pop() || text;
        const cleaned = last
          .replace(/\.gguf$/i, "")
          .replace(/q\d+[_-]k[_-]?[a-z0-9]+/ig, "")
          .replace(/bf16|f16|f32|instruct/ig, "")
          .replace(/[._-]+/g, " ")
          .trim();
        if (cleaned) {
          if ((typeId === "speech" || typeId === "speech_asr" || typeId === "speech_tts") && /models--cstr--|(^|[\\/])cstr([\\/]|$)|\bcstr\b/i.test(lowerText)) {
            return `cstr ${cleaned}`.trim();
          }
          return cleaned;
        }
      }
      if (typeId === "vlm") return "Qwen VL";
      if (typeId === "speech_asr") return "cstr parakeet canary qwen asr";
      if (typeId === "speech_tts") return "cstr chatterbox kokoro vibevoice tts";
      if (typeId === "speech") return "cstr parakeet canary qwen asr";
      if (typeId === "image_gen") return "Flux";
      if (typeId === "video_gen") return "Wan 2.1";
      return "Qwen";
    }
    function getCompanionSearchQuery() {
      const candidates = [
        entriesByKey["companion_model_path"]?.input?.value,
        model?.settings?.companion_model_path,
      ];
      for (const candidate of candidates) {
        const text = String(candidate || "").trim();
        if (!text) continue;
        const last = text.split(/[\\/]/).pop() || text;
        const cleaned = last
          .replace(/\.gguf$/i, "")
          .replace(/q\d+[_-]k[_-]?[a-z0-9]+/ig, "")
          .replace(/bf16|f16|f32|codec|model/ig, "")
          .replace(/[._-]+/g, " ")
          .trim();
        if (cleaned) return cleaned;
      }
      const presetId = String(entriesByKey["speech_template_preset"]?.input?.value || model?.settings?.speech_template_preset || "").trim().toLowerCase();
      if (presetId === "chatterbox") return "cstr chatterbox s3gen codec gguf";
      if (presetId === "kokoro") return "kokoro voice gguf";
      if (presetId === "vibevoice_custom") return "vibevoice gguf";
      return "codec gguf";
    }
    function getBackendValue() {
      if (typeId !== "image_gen" && typeId !== "video_gen") return "";
      return String(entriesByKey["backend"]?.input?.value || model?.settings?.backend || "diffusers").trim().toLowerCase();
    }
    function getHfSearchMode() {
      if ((typeId === "image_gen" || typeId === "video_gen") && hfSearchModeOverride) {
        return hfSearchModeOverride;
      }
      if (typeId === "image_gen") {
        const backend = getBackendValue();
        return backend === "sd_cpp" || backend === "gguf_cli" ? "gguf" : "repo";
      }
      if (typeId === "video_gen") {
        const backend = getBackendValue();
        return backend === "sd_cpp" ? "gguf" : "repo";
      }
      return "gguf";
    }
    function getRepoSearchTask() {
      return typeId === "video_gen" ? "video" : "image";
    }
    function getModelDeckBackendMode() {
      return String(entriesByKey["backend_mode"]?.input?.value || model?.settings?.backend_mode || "embedded").trim() || "embedded";
    }
    function getSearchButtonLabel() {
      if (typeId === "image_gen" || typeId === "video_gen") {
        return getHfSearchMode() === "repo" ? "Search HuggingFace Repo" : "Search HuggingFace GGUF";
      }
      return "Search HuggingFace GGUF";
    }
    function updateSearchButtonLabel() {
      if (searchBtn) searchBtn.textContent = getSearchButtonLabel();
    }
    function applyPickedGguf(selection) {
      const modelSource = String(selection?.modelSource || selection?.result?.model_source || "").trim();
      if (!modelSource) return;
      const modelPathEntry = entriesByKey["model_path"];
      const ggufModelEntry = entriesByKey["model_id"];
      const ggufPathEntry = entriesByKey["gguf_path"];
      const mmprojEntry = entriesByKey["mmproj_path"];
      const repoId = String(selection?.repoId || selection?.repo_id || "").trim();
      const filename = String(selection?.filename || "").trim();
      const repoOrSource = repoId || modelSource;
      if ((typeId === "image_gen" || typeId === "video_gen") && ggufModelEntry?.input && "value" in ggufModelEntry.input) {
        ggufModelEntry.input.value = repoOrSource;
      } else if (ggufModelEntry?.input && "value" in ggufModelEntry.input) {
        ggufModelEntry.input.value = modelSource;
      }
      if ((typeId === "image_gen" || typeId === "video_gen") && modelPathEntry?.input && "value" in modelPathEntry.input) {
        if (!String(modelPathEntry.input.value || "").trim()) modelPathEntry.input.value = repoOrSource;
      } else if (modelPathEntry?.input && "value" in modelPathEntry.input) {
        modelPathEntry.input.value = modelSource;
      }
      if (ggufPathEntry?.input && "value" in ggufPathEntry.input) {
        ggufPathEntry.input.value = modelSource;
      }
      const mmprojSource = String(selection?.mmprojSource || "").trim();
      if (mmprojSource && mmprojEntry?.input && "value" in mmprojEntry.input) {
        mmprojEntry.input.value = mmprojSource;
      }
      if (modelIdField?.input && !String(modelIdField.input.value || "").trim()) {
        modelIdField.input.value = String(selection?.suggestedModelEntryId || "").trim();
      }
      lastDownloadedHfRepoId = repoId;
      lastDownloadedHfFilename = filename;
      requestCompatRefresh();
    }
    function applyPickedRepo(selection) {
      const repoId = String(selection?.repo_id || selection?.repoId || selection?.modelSource || "").trim();
      if (!repoId) return;
      const cachePath = String(selection?.cache_path || selection?.cachePath || "").trim();
      const modelPathEntry = entriesByKey["model_path"];
      const modelIdEntry = entriesByKey["model_id"];
      if (modelIdEntry?.input && "value" in modelIdEntry.input) {
        modelIdEntry.input.value = repoId;
      }
      if (modelPathEntry?.input && "value" in modelPathEntry.input && !String(modelPathEntry.input.value || "").trim()) {
        modelPathEntry.input.value = cachePath || repoId;
      }
      if (modelIdField?.input && !String(modelIdField.input.value || "").trim()) {
        const suggested = repoId.split("/").pop() || repoId;
        modelIdField.input.value = suggested.replace(/[^a-z0-9._-]+/gi, "_");
      }
      lastDownloadedHfRepoId = repoId;
      lastDownloadedHfFilename = "";
      requestCompatRefresh();
    }
    function applyPickedCompanionGguf(selection) {
      const modelSource = String(selection?.modelSource || selection?.result?.model_source || "").trim();
      if (!modelSource) return;
      const companionEntry = entriesByKey["companion_model_path"];
      if (companionEntry?.input && "value" in companionEntry.input) {
        companionEntry.input.value = modelSource;
      }
    }
    function formatByteSize(value) {
      const num = Number(value || 0);
      if (!Number.isFinite(num) || num <= 0) return "";
      if (num >= 1024 ** 3) return `${(num / (1024 ** 3)).toFixed(2)} GB`;
      if (num >= 1024 ** 2) return `${(num / (1024 ** 2)).toFixed(1)} MB`;
      if (num >= 1024) return `${Math.round(num / 1024)} KB`;
      return `${Math.round(num)} B`;
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
    async function openGgufSearchPicker(options = null) {
      const pickerOptions = options && typeof options === "object" ? options : {};
      const modalTitle = String(pickerOptions.title || "Search GGUF models");
      const modalSubtext = String(
        pickerOptions.subtext
        || "Search HuggingFace for GGUF repositories that match the model hint. Selecting a file will save it into the Hugging Face cache for embedded mode or copy it into data/models for llama.cpp server mode."
      );
      const overlay = document.createElement("div");
      overlay.className = "mdhf-modal";
      overlay.dataset.modelDeckModal = "1";
      const card = document.createElement("div");
      card.className = "mdhf-card";
      overlay.appendChild(card);
      const mount = moveNodeIntoChatPortal(overlay) || resolveOverlayMount(ctx);
      mount.appendChild(overlay);
      requestAnimationFrame(() => { moveNodeIntoChatPortal(overlay); });
      const head = document.createElement("div");
      head.className = "mdhf-head";
      const titleWrap = document.createElement("div");
      titleWrap.innerHTML = `<div class="mdhf-title">${modalTitle}</div><div class="mdhf-sub">${modalSubtext}</div>`;
      const closeBtn = document.createElement("button");
      closeBtn.type = "button";
      closeBtn.className = "mdhf-close";
      closeBtn.textContent = "Close";
      head.appendChild(titleWrap);
      head.appendChild(closeBtn);
      card.appendChild(head);
      const searchState = {
        query: String(pickerOptions.query || getDeckSearchQuery()),
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
        activeSize: 0,
        activeDownloaded: 0,
        activeExpected: 0,
        activePhase: "",
      };
      let selectedRepoId = "";
      let selectedFilename = "";
      function closeModal(ok = false) {
        overlay.remove();
        return ok;
      }
      function addField(labelText, input) {
        const wrap = document.createElement("label");
        wrap.className = "field";
        const title = document.createElement("span");
        title.textContent = labelText;
        wrap.appendChild(title);
        wrap.appendChild(input);
        return wrap;
      }
      function buildBadgeLegend() {
        const details = document.createElement("details");
        details.className = "mdhf-legend";
        const summary = document.createElement("summary");
        summary.className = "mdhf-legend-title";
        summary.textContent = "Badge guide";
        details.appendChild(summary);
        const grid = document.createElement("div");
        grid.className = "mdhf-legend-grid";
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
          row.className = "mdhf-legend-item";
          const badge = document.createElement("span");
          badge.className = `mdhf-badge ${cls}`.trim();
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
      function buildFileBadges(file, isBest = false) {
        const row = document.createElement("div");
        row.className = "mdhf-badge-row";
        const add = (label, className) => {
          const badge = document.createElement("span");
          badge.className = `mdhf-badge ${className || ""}`.trim();
          badge.textContent = label;
          row.appendChild(badge);
        };
        if (isBest) add("Best", "best");
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
      function scoreSearchFile(file) {
        const low = String(file?.filename || "").toLowerCase();
        const pref = String(searchState.quantPreference || "q4_k_m").toLowerCase();
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
        const filter = String(searchState.filenameFilter || "").trim().toLowerCase();
        const repoSort = String(searchState.repoSort || "downloads_desc").trim();
        const fileSort = String(searchState.fileSort || "size_desc").trim();
        const safeOnly = searchState.safeOnly !== false;
        const singleFileOnly = searchState.singleFileOnly !== false;
        const repos = Array.isArray(searchState.results) ? searchState.results.slice() : [];
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
      const content = document.createElement("div");
      card.appendChild(content);
      function renderSearchUi() {
        content.innerHTML = "";
        const searchRow = document.createElement("div");
        searchRow.className = "mdhf-grid";
        const query = document.createElement("input");
        query.type = "text";
        query.value = searchState.query || "";
        query.placeholder = "Qwen Coder";
        query.addEventListener("input", () => { searchState.query = query.value; });
        query.addEventListener("keydown", async (event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            await runSearch();
          }
        });
        const fileFilter = document.createElement("input");
        fileFilter.type = "text";
        fileFilter.value = searchState.filenameFilter || "";
        fileFilter.placeholder = "Q4_K_M or 7B";
        fileFilter.addEventListener("input", () => {
          searchState.filenameFilter = fileFilter.value;
          renderSearchUi();
        });
        const repoSort = document.createElement("select");
        [["downloads_desc", "Repos: Most downloads"], ["likes_desc", "Repos: Most likes"], ["name_asc", "Repos: Name A-Z"]].forEach(([value, label]) => repoSort.appendChild(new Option(label, value)));
        repoSort.value = searchState.repoSort || "downloads_desc";
        repoSort.addEventListener("change", () => {
          searchState.repoSort = repoSort.value;
          renderSearchUi();
        });
        const fileSort = document.createElement("select");
        [["size_desc", "Files: Largest first"], ["name_asc", "Files: Name A-Z"], ["name_desc", "Files: Name Z-A"]].forEach(([value, label]) => fileSort.appendChild(new Option(label, value)));
        fileSort.value = searchState.fileSort || "size_desc";
        fileSort.addEventListener("change", () => {
          searchState.fileSort = fileSort.value;
          renderSearchUi();
        });
        searchRow.appendChild(addField("Search HuggingFace", query));
        searchRow.appendChild(addField("Filter filenames", fileFilter));
        searchRow.appendChild(addField("Repo sort", repoSort));
        searchRow.appendChild(addField("File sort", fileSort));
        content.appendChild(searchRow);
        const toggleRow = document.createElement("div");
        toggleRow.className = "mdhf-toggle-row";
        const safeToggle = document.createElement("label");
        safeToggle.className = "mdhf-checklabel";
        const safeInput = document.createElement("input");
        safeInput.type = "checkbox";
        safeInput.checked = searchState.safeOnly !== false;
        safeInput.addEventListener("change", () => {
          searchState.safeOnly = Boolean(safeInput.checked);
          renderSearchUi();
        });
        safeToggle.appendChild(safeInput);
        safeToggle.appendChild(document.createTextNode("Safe files only"));
        const singleToggle = document.createElement("label");
        singleToggle.className = "mdhf-checklabel";
        const singleInput = document.createElement("input");
        singleInput.type = "checkbox";
        singleInput.checked = searchState.singleFileOnly !== false;
        singleInput.addEventListener("change", () => {
          searchState.singleFileOnly = Boolean(singleInput.checked);
          renderSearchUi();
        });
        singleToggle.appendChild(singleInput);
        singleToggle.appendChild(document.createTextNode("Single-file GGUF only"));
        toggleRow.appendChild(safeToggle);
        toggleRow.appendChild(singleToggle);
        content.appendChild(toggleRow);
        const actions = document.createElement("div");
        actions.className = "mdhf-actions";
        const searchButton = document.createElement("button");
        searchButton.type = "button";
        searchButton.className = "mdhf-btn primary";
        searchButton.textContent = searchState.loading ? "Searching..." : "Search models";
        searchButton.disabled = searchState.loading;
        searchButton.addEventListener("click", () => { void runSearch(); });
        const expandAll = document.createElement("button");
        expandAll.type = "button";
        expandAll.className = "mdhf-btn ghost";
        expandAll.textContent = "Expand all";
        expandAll.addEventListener("click", () => {
          for (const repo of Array.isArray(searchState.results) ? searchState.results : []) searchState.collapsedRepos[String(repo?.repo_id || "")] = false;
          renderSearchUi();
        });
        const collapseAll = document.createElement("button");
        collapseAll.type = "button";
        collapseAll.className = "mdhf-btn ghost";
        collapseAll.textContent = "Collapse all";
        collapseAll.addEventListener("click", () => {
          for (const repo of Array.isArray(searchState.results) ? searchState.results : []) searchState.collapsedRepos[String(repo?.repo_id || "")] = true;
          renderSearchUi();
        });
        const destination = document.createElement("select");
        [["auto", backendModeValue() === "embedded" ? "Save for embedded (HF cache)" : "Save for llama.cpp server (data/models)"], ["hf_cache", "Save to HF cache only"], ["models_dir", "Save to data/models only"], ["both", "Save to both"]].forEach(([value, label]) => destination.appendChild(new Option(label, value)));
        destination.value = searchState.destinationMode || "auto";
        destination.addEventListener("change", () => { searchState.destinationMode = destination.value; });
        const quantPref = document.createElement("select");
        [["q4_k_m", "Prefer Q4_K_M"], ["q5_k_m", "Prefer Q5_K_M"], ["highest_quality", "Prefer highest quality"], ["smallest", "Prefer smallest"]].forEach(([value, label]) => quantPref.appendChild(new Option(label, value)));
        quantPref.value = searchState.quantPreference || "q4_k_m";
        quantPref.addEventListener("change", () => {
          searchState.quantPreference = quantPref.value;
          renderSearchUi();
        });
        actions.appendChild(searchButton);
        actions.appendChild(expandAll);
        actions.appendChild(collapseAll);
        actions.appendChild(addField("Destination", destination));
        actions.appendChild(addField("Best-file preference", quantPref));
        content.appendChild(actions);
        if (searchState.status) {
          const statusCard = document.createElement("div");
          statusCard.className = "mdhf-status-card";
          const phaseLabel = searchState.activePhase ? String(searchState.activePhase) : (searchState.loading ? "working" : "idle");
          statusCard.innerHTML = `<div class="mdhf-status-title">Current phase</div><div class="mdhf-status-main">${phaseLabel || "idle"}</div><div class="mdhf-status-meta">${searchState.status}</div>`;
          if (searchState.activeFile) {
            const meta = document.createElement("div");
            meta.className = "mdhf-status-meta";
            const expected = Number(searchState.activeExpected || searchState.activeSize || 0);
            const downloaded = Number(searchState.activeDownloaded || 0);
            if (expected > 0 && downloaded > 0) meta.textContent = `${searchState.activeFile} ${formatByteSize(downloaded)} / ${formatByteSize(expected)}`;
            else if (expected > 0) meta.textContent = `${searchState.activeFile} ${formatByteSize(expected)}`;
            else meta.textContent = searchState.activeFile;
            statusCard.appendChild(meta);
          }
          content.appendChild(statusCard);
        }
        content.appendChild(buildBadgeLegend());
        const list = document.createElement("div");
        list.className = "mdhf-repo-list";
        const visibleResults = getVisibleSearchResults();
        for (const repo of visibleResults) {
          const repoCard = document.createElement("div");
          repoCard.className = "mdhf-repo-card";
          const details = document.createElement("details");
          const repoId = String(repo?.repo_id || "");
          details.open = !Boolean(searchState.collapsedRepos[repoId] ?? true);
          details.addEventListener("toggle", () => { searchState.collapsedRepos[repoId] = !details.open; });
          const summary = document.createElement("summary");
          summary.className = "mdhf-repo-summary";
          summary.innerHTML = `<div><div class="mdhf-repo-id">${repoId}</div><div class="mdhf-repo-meta">Downloads: ${Number(repo?.downloads || 0)} | Likes: ${Number(repo?.likes || 0)} | ${repo?.pipeline_tag || "model"}</div></div><div class="mdhf-repo-count">${repo.visible_count}/${repo.total_count} files</div>`;
          details.appendChild(summary);
          const bestPick = pickBestSearchFile(repo.gguf_files || []);
          const bestName = String(bestPick?.file?.filename || "");
          const headRow = document.createElement("div");
          headRow.className = "mdhf-repo-head";
          headRow.innerHTML = `<div class="mdhf-note">Visible GGUF files for this repo${bestName ? ` | Best candidate: ${bestName} (${String(searchState.quantPreference || "q4_k_m").replace(/_/g, " ")})` : ""}</div><a class="mdhf-link" href="${repo.repo_url}" target="_blank" rel="noreferrer">Open repo</a>`;
          details.appendChild(headRow);
          const files = document.createElement("div");
          files.className = "mdhf-file-list";
          for (const file of repo.gguf_files || []) {
            const row = document.createElement("div");
            row.className = "mdhf-file-row";
            const info = document.createElement("div");
            const isBest = bestName && String(file?.filename || "") === bestName;
            info.innerHTML = `<div class="mdhf-file-name">${file.filename}</div><div class="mdhf-note">${file.size != null ? formatByteSize(file.size) : "Size unavailable"}${isBest ? " | highlighted best candidate" : ""}</div>`;
            const badges = buildFileBadges(file, isBest);
            if (badges) info.appendChild(badges);
            const act = document.createElement("div");
            act.className = "md-actions";
            const useBtn = document.createElement("button");
            useBtn.type = "button";
            useBtn.className = "primary";
            useBtn.textContent = searchState.loading ? "Saving..." : "Use this file";
            useBtn.disabled = searchState.loading;
            useBtn.addEventListener("click", () => {
              selectedRepoId = repoId;
              selectedFilename = String(file?.filename || "");
              void saveSelection();
            });
            act.appendChild(useBtn);
            row.appendChild(info);
            row.appendChild(act);
            files.appendChild(row);
          }
          details.appendChild(files);
          repoCard.appendChild(details);
          list.appendChild(repoCard);
        }
        if (!visibleResults.length && !searchState.loading) {
          const empty = document.createElement("div");
          empty.className = "mdhf-note";
          empty.textContent = (searchState.results || []).length ? "No files match the current filename filter." : "No results yet. Search using the model hint or edit the query.";
          list.appendChild(empty);
        }
        content.appendChild(list);
      }
      function backendModeValue() {
        return String(entriesByKey["backend_mode"]?.input?.value || model?.settings?.backend_mode || "embedded").trim() || "embedded";
      }
      async function runGgufDownloadJob(repoId, filename, backendMode, destinationMode, expectedBytes) {
        const started = await apiJson(ctx, "/v1/model_deck/hf_gguf_download_start", {
          method: "POST",
          body: {
            repo_id: repoId,
            filename,
            backend_mode: backendMode,
            destination_mode: destinationMode,
            expected_bytes: Number(expectedBytes || 0),
          },
        });
        const jobId = String(started?.job_id || "").trim();
        if (!jobId) throw new Error("Download job was not created");
        let finalRow = null;
        for (let attempt = 0; attempt < 14400; attempt += 1) {
          await new Promise((resolve) => window.setTimeout(resolve, 1000));
          const row = await apiJson(ctx, `/v1/model_deck/hf_gguf_download_status?job_id=${encodeURIComponent(jobId)}`);
          searchState.activePhase = String(row?.phase || searchState.activePhase || "working");
          searchState.status = String(row?.status || searchState.status || "Working...");
          searchState.activeDownloaded = Number(row?.downloaded_bytes || searchState.activeDownloaded || 0);
          searchState.activeExpected = Number(row?.expected_bytes || expectedBytes || searchState.activeExpected || 0);
          renderSearchUi();
          if (row?.done) {
            finalRow = row;
            break;
          }
        }
        if (!finalRow) throw new Error("Model download timed out");
        if (finalRow.ok === false) throw new Error(String(finalRow.error || finalRow.status || "Download failed"));
        return finalRow;
      }
      async function runSearch() {
        const query = String(searchState.query || "").trim();
        if (!query) {
          searchState.status = "Enter a model name to search.";
          renderSearchUi();
          return;
        }
        selectedRepoId = "";
        selectedFilename = "";
        searchState.results = [];
        searchState.loading = true;
        searchState.status = `Searching Hugging Face GGUF for ${query}...`;
        renderSearchUi();
        try {
          const res = await apiJson(ctx, "/v1/model_deck/hf_gguf_search", {
            method: "POST",
            body: { query, limit: 10 },
          });
          searchState.results = Array.isArray(res?.results) ? res.results : [];
          const repoCount = searchState.results.length;
          const fileCount = searchState.results.reduce((sum, repo) => sum + ((repo?.gguf_files || []).length || 0), 0);
          searchState.status = repoCount ? `Found ${repoCount} repositories and ${fileCount} GGUF files.` : "No GGUF repositories found.";
        } catch (err) {
          searchState.status = String(err?.message || err || "Search failed");
        } finally {
          searchState.loading = false;
          renderSearchUi();
        }
      }
      async function saveSelection() {
        if (!selectedRepoId || !selectedFilename) {
          searchState.status = "Select a GGUF file first.";
          renderSearchUi();
          return;
        }
        try {
          const backendMode = backendModeValue();
          const destinationMode = String(searchState.destinationMode || (backendMode === "embedded" ? "hf_cache" : "models_dir")).trim() || "auto";
          const selectedRepo = searchState.results.find((row) => String(row?.repo_id || "") === selectedRepoId) || null;
          const selectedFile = Array.isArray(selectedRepo?.gguf_files)
            ? selectedRepo.gguf_files.find((item) => String(item?.filename || "") === selectedFilename)
            : null;
          const expectedBytes = Number(selectedFile?.size || 0);
          searchState.loading = true;
          searchState.activeFile = selectedFilename;
          searchState.activeSize = expectedBytes;
          searchState.activeDownloaded = 0;
          searchState.activeExpected = expectedBytes;
          searchState.activePhase = "download";
          searchState.status = `Downloading ${selectedFilename} from ${selectedRepoId}...`;
          renderSearchUi();
          const finalRow = await runGgufDownloadJob(selectedRepoId, selectedFilename, backendMode, destinationMode, expectedBytes);
          const downloaded = finalRow?.result || {};
          let mmprojSource = "";
          if (typeId === "vlm") {
            const mmprojFile = pickRepoMmprojFile(selectedRepo);
            if (mmprojFile?.filename && String(mmprojFile.filename || "") !== selectedFilename) {
              try {
                searchState.activeFile = String(mmprojFile.filename || "");
                searchState.activeSize = Number(mmprojFile.size || 0);
                searchState.activeDownloaded = 0;
                searchState.activeExpected = Number(mmprojFile.size || 0);
                searchState.status = `Downloading ${mmprojFile.filename} from ${selectedRepoId}...`;
                renderSearchUi();
                const mmprojFinalRow = await runGgufDownloadJob(
                  selectedRepoId,
                  String(mmprojFile.filename || "").trim(),
                  backendMode,
                  destinationMode,
                  Number(mmprojFile.size || 0),
                );
                mmprojSource = String(mmprojFinalRow?.result?.model_source || "").trim();
              } catch (_mmprojErr) {
                mmprojSource = "";
              }
            }
          }
          const pickedSelection = {
            modelSource: String(downloaded?.model_source || "").trim(),
            mmprojSource,
            repoId: selectedRepoId,
            filename: selectedFilename,
            suggestedModelEntryId: String(selectedFilename || selectedRepoId || "").replace(/\.gguf$/i, "").replace(/[^a-z0-9._-]+/gi, "_"),
          };
          if (typeof pickerOptions.onPick === "function") pickerOptions.onPick(pickedSelection);
          else applyPickedGguf(pickedSelection);
          closeModal(true);
        } catch (err) {
          searchState.activePhase = "error";
          searchState.status = String(err?.message || err || "Download failed");
          renderSearchUi();
        } finally {
          searchState.loading = false;
        }
      }
      closeBtn.addEventListener("click", () => { closeModal(false); });
      overlay.addEventListener("click", (event) => {
        if (event.target === overlay && !searchState.loading) closeModal(false);
      });
      renderSearchUi();
      await runSearch();
    }
    async function openRepoSearchPicker() {
      const picker = createModal(typeId === "video_gen" ? "Search Hugging Face video models" : "Search Hugging Face image models");
      const queryField = createTextField("Search", getDeckSearchQuery());
      const searchNowBtn = document.createElement("button");
      searchNowBtn.type = "button";
      searchNowBtn.className = "secondary";
      searchNowBtn.textContent = "Search";
      const toolbar = document.createElement("div");
      toolbar.style.display = "flex";
      toolbar.style.gap = "8px";
      toolbar.style.alignItems = "end";
      toolbar.style.marginBottom = "10px";
      toolbar.appendChild(queryField.wrap);
      toolbar.appendChild(searchNowBtn);
      const status = document.createElement("div");
      status.style.fontSize = "12px";
      status.style.opacity = "0.8";
      status.style.marginBottom = "10px";
      const resultsWrap = document.createElement("div");
      resultsWrap.style.display = "flex";
      resultsWrap.style.flexDirection = "column";
      resultsWrap.style.gap = "8px";
      resultsWrap.style.maxHeight = "380px";
      resultsWrap.style.overflowY = "auto";
      picker.body.appendChild(toolbar);
      picker.body.appendChild(status);
      picker.body.appendChild(resultsWrap);
      let rows = [];
      let selectedRepoId = "";
      function setStatus(text) {
        status.textContent = String(text || "");
      }
      async function runRepoDownloadJob(repoId) {
        const started = await apiJson(ctx, "/v1/model_deck/hf_repo_download_start", {
          method: "POST",
          body: { repo_id: repoId },
        });
        const jobId = String(started?.job_id || "").trim();
        if (!jobId) throw new Error("Download job was not created");
        let finalRow = null;
        for (let attempt = 0; attempt < 14400; attempt += 1) {
          await new Promise((resolve) => window.setTimeout(resolve, 1000));
          const row = await apiJson(ctx, `/v1/model_deck/hf_repo_download_status?job_id=${encodeURIComponent(jobId)}`);
          const downloaded = Number(row?.downloaded_bytes || 0);
          const expected = Number(row?.expected_bytes || 0);
          let text = String(row?.status || "Working...");
          if (downloaded > 0 && expected > 0) text += ` (${formatByteSize(downloaded)} / ${formatByteSize(expected)})`;
          else if (downloaded > 0) text += ` (${formatByteSize(downloaded)})`;
          setStatus(text);
          if (row?.done) {
            finalRow = row;
            break;
          }
        }
        if (!finalRow) throw new Error("Repository download timed out");
        if (finalRow.ok === false) throw new Error(String(finalRow.error || finalRow.status || "Download failed"));
        return finalRow;
      }
      function renderResults() {
        resultsWrap.innerHTML = "";
        for (const row of rows) {
          const repoId = String(row?.repo_id || "").trim();
          if (!repoId) continue;
          const card = document.createElement("button");
          card.type = "button";
          card.className = "secondary";
          card.style.textAlign = "left";
          card.style.padding = "10px";
          card.style.border = selectedRepoId === repoId ? "2px solid var(--accent, #4f8cff)" : "";
          card.innerHTML = `
            <div style="font-weight:600;">${repoId}</div>
            <div style="font-size:12px;opacity:0.8;margin-top:4px;">
              ${(row?.pipeline_tag || "model")} | Downloads: ${row?.downloads || 0} | Likes: ${row?.likes || 0}
            </div>
            <div style="font-size:12px;opacity:0.75;margin-top:4px;word-break:break-word;">
              ${Array.isArray(row?.tags) ? row.tags.slice(0, 6).join(", ") : ""}
            </div>
          `;
          card.addEventListener("click", () => {
            selectedRepoId = repoId;
            status.textContent = `Selected ${repoId}. Click Save to download and apply it.`;
            renderResults();
          });
          resultsWrap.appendChild(card);
        }
      }
      async function runSearch() {
        const query = String(queryField.input.value || "").trim();
        if (!query) {
          status.textContent = "Enter a model name to search.";
          return;
        }
        selectedRepoId = "";
        rows = [];
        status.textContent = `Searching Hugging Face for ${query}...`;
        renderResults();
        try {
          const res = await apiJson(ctx, "/v1/model_deck/hf_repo_search", {
            method: "POST",
            body: { query, limit: 12, task: getRepoSearchTask() },
          });
          rows = Array.isArray(res?.results) ? res.results : [];
          status.textContent = rows.length ? `Found ${rows.length} repositories.` : "No repositories found.";
          renderResults();
        } catch (err) {
          status.textContent = String(err?.message || err || "Search failed");
        }
      }
      searchNowBtn.addEventListener("click", () => { void runSearch(); });
      queryField.input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          void runSearch();
        }
      });
      await runSearch();
      await picker.open(async () => {
        if (!selectedRepoId) {
          setStatus("Select a repository first.");
          return false;
        }
        try {
          setStatus(`Downloading ${selectedRepoId} to the Hugging Face cache...`);
          const finalRow = await runRepoDownloadJob(selectedRepoId);
          applyPickedRepo(finalRow?.result || { repo_id: selectedRepoId });
          return true;
        } catch (err) {
          setStatus(String(err?.message || err || "Download failed"));
          return false;
        }
      });
    }
    if (typeId === "text_llm" || typeId === "vlm" || typeId === "speech" || typeId === "speech_asr" || typeId === "speech_tts" || typeId === "image_gen" || typeId === "video_gen") {
      if (typeId === "image_gen" || typeId === "video_gen") {
        const hasExistingGguf = Boolean(
          String(model?.settings?.gguf_path || "").trim()
          || String(model?.settings?.hf_source_filename || "").trim()
        );
        hfSearchModeOverride = hasExistingGguf ? "gguf" : "";
      }
      if (typeId === "image_gen" || typeId === "video_gen") {
        const searchModeField = createSelectField(
          "Hugging Face search",
          [
            { value: "repo", label: "Repo folder" },
            { value: "gguf", label: "GGUF file" },
          ],
          getHfSearchMode(),
        );
        searchModeField.input.addEventListener("change", () => {
          hfSearchModeOverride = String(searchModeField.input.value || "").trim().toLowerCase();
          updateSearchButtonLabel();
        });
        settingsHead.appendChild(searchModeField.wrap);
      }
      searchBtn = document.createElement("button");
      searchBtn.type = "button";
      searchBtn.className = "secondary";
      searchBtn.textContent = getSearchButtonLabel();
      searchBtn.addEventListener("click", async () => {
        try {
          if ((typeId === "image_gen" || typeId === "video_gen") && getHfSearchMode() === "repo") {
            await openRepoSearchPicker();
            return;
          }
          await openGgufSearchPicker();
        } catch (err) {
          toast(ctx, String(err?.message || err || "Failed to search HuggingFace"), true);
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
      let defaultValue = value !== undefined ? value : field.default ?? "";
      if ((typeId === "image_gen" || typeId === "video_gen") && key === "model_backend" && value === undefined) {
        const savedWorkflowMode = String(model?.settings?.workflow_loader_mode || "").trim().toLowerCase();
        defaultValue = savedWorkflowMode === "workflow_model_loader" ? "workflow" : "default";
      }
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
        if (field.ui_hidden === true) {
          entry.wrap.style.display = "none";
        }
        if (key === "main_gpu") {
          mainGpuEntry = entry;
        }
        if (supportsManagedLlamaServer && key === "backend_mode") {
          backendModeEntry = entry;
        }
        if (key === "gpu_selection_mode") {
          gpuSelectionModeEntry = entry;
        }
        if (key === "gpu_split_mode") {
          gpuSplitModeEntry = entry;
        }
        if (key === "gpu_split_devices") {
          gpuSplitDevicesEntry = entry;
        }
        if (key === "gpu_split_percent") {
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
        const formEntry = {
          key,
          type,
          input: entry.input,
          wrap: entry.wrap,
          backendScope: typeId === "image_gen" ? imageGenFieldBackend(label) : "",
          persistWhenHidden: field.ui_hidden === true,
        };
        entries.push(formEntry);
        entriesByKey[key] = formEntry;
        if (key === "main_gpu") {
          mainGpuFormEntry = formEntry;
        }
      }
    }

    async function applySharedFieldEnhancers() {
      const enhancers = getModelDeckFieldEnhancers(ctx);
      for (const enhancer of enhancers) {
        const fieldKey = String(enhancer?.fieldKey || "").trim();
        if (!fieldKey) continue;
        const entry = entriesByKey[fieldKey];
        if (!entry?.wrap || !entry?.input) continue;
        const enhancerTypeId = String(enhancer?.typeId || "").trim();
        if (enhancerTypeId && enhancerTypeId !== typeId) continue;
        if (typeof enhancer.appliesTo === "function") {
          let ok = false;
          try {
            ok = !!enhancer.appliesTo({ typeId, fieldKey, model, field: fields.find((row) => String(row?.key || "").trim() === fieldKey) || null });
          } catch (_err) {
            ok = false;
          }
          if (!ok) continue;
        }
        if (entry.wrap.querySelector(`[data-field-enhancer="${String(enhancer.id || fieldKey)}"]`)) continue;
        const shell = document.createElement("div");
        shell.className = "field";
        shell.style.marginTop = "8px";
        shell.dataset.fieldEnhancer = String(enhancer.id || fieldKey);
        const top = document.createElement("div");
        top.style.display = "flex";
        top.style.gap = "8px";
        top.style.alignItems = "center";
        top.style.flexWrap = "wrap";
        const select = document.createElement("select");
        select.className = "plugin-search-input";
        const empty = document.createElement("option");
        empty.value = "";
        empty.textContent = String(enhancer.emptyLabel || "No managed options available");
        select.appendChild(empty);
        const refreshBtn = document.createElement("button");
        refreshBtn.type = "button";
        refreshBtn.className = "secondary";
        refreshBtn.textContent = String(enhancer.refreshLabel || "Refresh");
        top.appendChild(select);
        top.appendChild(refreshBtn);
        shell.appendChild(top);
        if (enhancer.helpText) {
          const hint = document.createElement("div");
          hint.className = "field-help";
          hint.textContent = String(enhancer.helpText);
          shell.appendChild(hint);
        }
        const refreshOptions = async () => {
          try {
            refreshBtn.disabled = true;
            select.innerHTML = "";
            const pending = document.createElement("option");
            pending.value = "";
            pending.textContent = "Loading options...";
            select.appendChild(pending);
            let options = [];
            if (typeof enhancer.loadOptions === "function") {
              const res = await enhancer.loadOptions(ctx, { typeId, fieldKey, model });
              options = Array.isArray(res) ? res : [];
            }
            select.innerHTML = "";
            const blank = document.createElement("option");
            blank.value = "";
            blank.textContent = options.length ? String(enhancer.placeholder || "Select a managed option...") : String(enhancer.emptyLabel || "No managed options available");
            select.appendChild(blank);
            for (const optionRow of options) {
              const opt = document.createElement("option");
              opt.value = String(optionRow?.value || "");
              opt.textContent = String(optionRow?.label || optionRow?.value || "");
              if (optionRow?.description) opt.title = String(optionRow.description);
              if (String(optionRow?.value || "") === String(entry.input.value || "").trim()) opt.selected = true;
              select.appendChild(opt);
            }
          } catch (_err) {
            select.innerHTML = "";
            const failed = document.createElement("option");
            failed.value = "";
            failed.textContent = "Failed to load options";
            select.appendChild(failed);
          } finally {
            refreshBtn.disabled = false;
          }
        };
        select.addEventListener("change", () => {
          if ("value" in entry.input) entry.input.value = select.value;
        });
        refreshBtn.addEventListener("click", () => {
          void refreshOptions();
        });
        entry.wrap.appendChild(shell);
        void refreshOptions();
      }
    }

    let compatDynamicAssetEntries = [];
    let compatDynamicAssetSection = null;
    let compatAssetSearchBtn = null;
    let compatOpenWorkflowBtn = null;
    let compatManifestCache = new Map();
    let currentStatus = null;

    function parseJsonObjectSafe(value) {
      if (value && typeof value === "object" && !Array.isArray(value)) return { ...value };
      const raw = String(value || "").trim();
      if (!raw) return {};
      try {
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
      } catch (_err) {
        return {};
      }
    }

    function getCompatRuntimeConfig() {
      return typeId === "image_gen" ? imageRuntimeConfig : (typeId === "video_gen" ? videoRuntimeConfig : null);
    }

    function getCompatAssetJsonEntry() {
      const config = getCompatRuntimeConfig();
      return config ? entriesByKey[config.assetsKey] : null;
    }

    function getCompatParamJsonEntry() {
      const config = getCompatRuntimeConfig();
      return config ? entriesByKey[config.paramsKey] : null;
    }

    function getRuntimeJsonSettingValue(key) {
      const settingKey = String(key || "").trim();
      if (!settingKey) return "";
      const direct = entriesByKey[settingKey]?.input && "value" in entriesByKey[settingKey].input
        ? entriesByKey[settingKey].input.value
        : model?.settings?.[settingKey];
      if (direct !== undefined && direct !== null && String(direct).trim() !== "") return direct;
      const config = getCompatRuntimeConfig();
      for (const sourceKey of [config?.paramsKey, config?.assetsKey]) {
        const raw = entriesByKey[sourceKey]?.input && "value" in entriesByKey[sourceKey].input
          ? entriesByKey[sourceKey].input.value
          : model?.settings?.[sourceKey];
        const obj = parseJsonObjectSafe(raw || "");
        const nested = obj?.[settingKey];
        if (nested !== undefined && nested !== null && String(nested).trim() !== "") return nested;
      }
      return "";
    }

    function getSavedWorkflowFlowName() {
      return String(
        getRuntimeJsonSettingValue("model_workflow_flow_name")
        || getRuntimeJsonSettingValue("model_workflow_template_flow_name")
        || ""
      ).trim();
    }

    function hasOpenableWorkflowTarget(manifest = null) {
      return Boolean(getSavedWorkflowFlowName())
        || Boolean(manifest?.workflow_json && Object.keys(manifest.workflow_json || {}).length);
    }

    function getModelBackendValue() {
      const explicit = String(entriesByKey["model_backend"]?.input?.value || "").trim().toLowerCase();
      if (explicit === "workflow" || explicit === "default") return explicit;
      const workflowMode = String(entriesByKey["workflow_loader_mode"]?.input?.value || model?.settings?.workflow_loader_mode || "").trim().toLowerCase();
      return workflowMode === "workflow_model_loader" ? "workflow" : "default";
    }

    function setEntryValue(key, value) {
      const entry = entriesByKey[key];
      const input = entry?.input;
      if (!input) return;
      if (input instanceof HTMLInputElement && input.type === "checkbox") {
        input.checked = Boolean(value);
        return;
      }
      if ("value" in input) input.value = String(value ?? "");
    }

    function syncExecutionModeForBackend(config) {
      if (!config || typeId !== config.typeId) return;
      const entry = entriesByKey[config.modeKey];
      const input = entry?.input;
      if (!(input instanceof HTMLSelectElement)) return;
      const backend = getModelBackendValue();
      const defaultBackend = backend === "default";
      for (const option of Array.from(input.options || [])) {
        const isAdvanced = String(option.value || "").trim().toLowerCase() === "advanced";
        if (!isAdvanced) continue;
        option.disabled = defaultBackend;
        option.hidden = defaultBackend;
        option.style.display = defaultBackend ? "none" : "";
      }
      if (defaultBackend && String(input.value || "").trim().toLowerCase() === "advanced") {
        input.value = "standard";
      }
    }

    function syncModelBackendCompatibilityFields() {
      if (typeId !== "image_gen" && typeId !== "video_gen") return;
      const backend = getModelBackendValue();
      if (backend === "workflow") {
        setEntryValue("workflow_loader_mode", "workflow_model_loader");
        setEntryValue("workflow_execution_backend", "native_graph");
        return;
      }
      setEntryValue("workflow_loader_mode", "checkpoint_runner");
      setEntryValue("workflow_execution_backend", typeId === "image_gen" ? "built_in_runner" : "native_graph");
    }

    function compatFieldFallbackMeta(slot) {
      const key = String(slot?.key || "").trim().toLowerCase();
      if (key === "native_transformer_offload") {
        return {
          label: "Transformer offload mode",
          type: "enum",
          choices: [
            { value: "none", label: "No offload / eager GPU load (GGUF supported)" },
            { value: "disk", label: "Disk-backed CPU slots (safetensors only)" },
            { value: "cpu", label: "RAM-pinned CPU streaming (safetensors only)" },
          ],
        };
      }
      if (key === "gemma_text_encoding_device") {
        return {
          label: "Text encoder runtime device",
          type: "enum",
          choices: [
            { value: "cpu", label: "CPU" },
            { value: "gpu", label: "GPU / main video device" },
          ],
        };
      }
      if (key === "workflow_loader_mode") {
        return {
          label: "Workflow loader mode",
          type: "enum",
          choices: [
            { value: "checkpoint_runner", label: "Checkpoint runner / built-in path" },
            { value: "workflow_model_loader", label: "Workflow model loader / Agent Flow graph" },
          ],
        };
      }
      if (key === "workflow_node_lifecycle_policy") {
        return {
          label: "Workflow node lifecycle policy",
          type: "enum",
          choices: [
            { value: "lazy_unload", label: "Lazy load, unload after node" },
            { value: "lazy_persist", label: "Lazy load, keep hot after first use" },
            { value: "preload_persist", label: "Preload and keep resident" },
          ],
        };
      }
      if (key === "workflow_execution_backend") {
        return {
          label: "Workflow execution backend",
          type: "enum",
          choices: [
            { value: "native_graph", label: "Native staged graph execution" },
            { value: "ltx_checkpoint_runner", label: "Legacy checkpoint runner" },
          ],
        };
      }
      return null;
    }

    function inferCompatAssetFieldType(slot) {
      const roleMeta = slot?.role_meta && typeof slot.role_meta === "object" ? slot.role_meta : {};
      const fallbackMeta = compatFieldFallbackMeta(slot);
      const declaredType = String(slot?.type || roleMeta?.field_type || fallbackMeta?.type || "").trim().toLowerCase();
      if (declaredType) return declaredType;
      if (
        Array.isArray(slot?.options) ||
        Array.isArray(slot?.choices) ||
        Array.isArray(roleMeta?.options) ||
        Array.isArray(roleMeta?.choices) ||
        Array.isArray(fallbackMeta?.options) ||
        Array.isArray(fallbackMeta?.choices)
      ) {
        return "enum";
      }
      const key = String(slot?.key || "").trim().toLowerCase();
      const source = String(slot?.source || "").trim().toLowerCase();
      if (key.startsWith("enable_") || key.startsWith("use_")) return "bool";
      if (source.includes("file") || source.includes("dir") || key.endsWith("_path")) return "path";
      return "str";
    }

    function syncCompatAssetJsonFromDynamicFields() {
      const assetEntry = getCompatAssetJsonEntry();
      const paramEntry = getCompatParamJsonEntry();
      const nextAssetJson = parseJsonObjectSafe(assetEntry?.input?.value || "");
      const nextParamJson = parseJsonObjectSafe(paramEntry?.input?.value || "");
      for (const row of compatDynamicAssetEntries) {
        if (!row?.slot?.key) continue;
        const value = readFieldValue(row.type, row.input);
        const source = String(row?.slot?.source || "").trim().toLowerCase();
        const targetJson = source === "setting" ? nextParamJson : nextAssetJson;
        if (value === undefined || value === null || value === "") delete targetJson[row.slot.key];
        else targetJson[row.slot.key] = value;
      }
      if (assetEntry?.input && "value" in assetEntry.input) {
        assetEntry.input.value = stableJsonString(nextAssetJson);
      }
      if (paramEntry?.input && "value" in paramEntry.input) {
        paramEntry.input.value = stableJsonString(nextParamJson);
      }
    }

    function clearCompatDynamicAssetFields() {
      for (const row of compatDynamicAssetEntries) {
        if (row?.wrap?.parentElement) row.wrap.parentElement.removeChild(row.wrap);
      }
      compatDynamicAssetEntries = [];
      if (compatDynamicAssetSection) compatDynamicAssetSection.style.display = "none";
      if (compatAssetSearchBtn) compatAssetSearchBtn.style.display = "none";
    }

    function renderCompatDynamicAssetFields(manifest) {
      clearCompatDynamicAssetFields();
      const runtimeProfile = manifest?.runtime_profile && typeof manifest.runtime_profile === "object" ? manifest.runtime_profile : null;
      const runtimeKind = String(runtimeProfile?.kind || "").trim().toLowerCase();
      const assetSlots = Array.isArray(runtimeProfile?.asset_slots) ? runtimeProfile.asset_slots : [];
      if (!compatDynamicAssetSection || !assetSlots.length) return;
      const assetEntry = getCompatAssetJsonEntry();
      const paramEntry = getCompatParamJsonEntry();
      const assetValues = parseJsonObjectSafe(assetEntry?.input?.value || manifest?.assets_json || {});
      const paramValues = parseJsonObjectSafe(paramEntry?.input?.value || manifest?.params_json || {});
      const liveSettings = snapshotEditorSettings();
      let created = 0;
      for (const slot of assetSlots) {
        if (!slot || typeof slot !== "object") continue;
        const key = String(slot.key || "").trim();
        if (!key || entriesByKey[key]) continue;
        const fallbackMeta = compatFieldFallbackMeta(slot);
        const type = inferCompatAssetFieldType(slot);
        const label = String(slot?.role_meta?.label || fallbackMeta?.label || slot?.label || slot?.key || "Asset");
        const source = String(slot?.source || "").trim();
        const sourceSuffix = source && source.toLowerCase() !== "setting" ? ` (${source})` : "";
        const choices = Array.isArray(slot?.options)
          ? slot.options
          : (Array.isArray(slot?.choices)
            ? slot.choices
            : (Array.isArray(slot?.role_meta?.options)
              ? slot.role_meta.options
              : (Array.isArray(slot?.role_meta?.choices)
                ? slot.role_meta.choices
                : (Array.isArray(fallbackMeta?.options) ? fallbackMeta.options : (Array.isArray(fallbackMeta?.choices) ? fallbackMeta.choices : [])))));
        const field = {
          key,
          type,
          required: !!slot?.required,
          description: `${label}${sourceSuffix}`,
          choices,
        };
        const isSettingSlot = String(slot?.source || "").trim().toLowerCase() === "setting";
        const initialValue = liveSettings?.[key] ?? (isSettingSlot ? paramValues[key] : assetValues[key]);
        const entry = createSchemaField(label, type, field, initialValue);
        if (!entry?.wrap || !entry?.input) continue;
        entry.wrap.style.marginBottom = "12px";
        const help = document.createElement("div");
        help.className = "field-help";
        help.style.marginTop = "4px";
        help.style.marginBottom = "10px";
        const helpText = field.required ? `${field.description} Required by this tested profile.` : field.description;
        const normalizedHelp = String(helpText || "").trim().toLowerCase();
        const normalizedLabel = String(label || "").trim().toLowerCase();
        const normalizedKey = String(key || "").trim().toLowerCase();
        const repeatsTitle = normalizedHelp === normalizedLabel || normalizedHelp === normalizedKey;
        if (helpText && !repeatsTitle) {
          help.textContent = helpText;
          entry.wrap.appendChild(help);
        } else {
          entry.wrap.style.marginBottom = "16px";
        }
        const inputEl = entry.input?.value instanceof HTMLElement ? entry.input.value : entry.input;
        if (inputEl && typeof inputEl.addEventListener === "function") {
          inputEl.addEventListener("input", syncCompatAssetJsonFromDynamicFields);
          inputEl.addEventListener("change", () => {
            syncCompatAssetJsonFromDynamicFields();
          });
        }
        if (entry.input?.mode instanceof HTMLElement) {
          entry.input.mode.addEventListener("change", syncCompatAssetJsonFromDynamicFields);
        }
        compatDynamicAssetSection.appendChild(entry.wrap);
        compatDynamicAssetEntries.push({ key, type, input: entry.input, wrap: entry.wrap, slot, synthetic: true });
        created += 1;
      }
      compatDynamicAssetSection.style.display = created > 0 ? "" : "none";
      if (compatAssetSearchBtn) compatAssetSearchBtn.style.display = created > 0 ? "" : "none";
      if (created > 0) syncCompatAssetJsonFromDynamicFields();
    }

    function workflowJsonToAgentFlowImport(manifest) {
      const workflow = manifest?.workflow_json && typeof manifest.workflow_json === "object" ? manifest.workflow_json : null;
      const nodes = Array.isArray(workflow?.nodes) ? workflow.nodes : [];
      if (!workflow || !nodes.length) return null;
      const flowName = String(workflow.flow_name || workflow.workflow_id || manifest?.label || "Model workflow").trim();
      const assetEntry = getCompatAssetJsonEntry();
      const paramEntry = getCompatParamJsonEntry();
      const liveSettings = snapshotEditorSettings();
      const assets = {
        ...parseJsonObjectSafe(assetEntry?.input?.value || manifest?.assets_json || {}),
      };
      const settings = {
        ...parseJsonObjectSafe(paramEntry?.input?.value || manifest?.params_json || {}),
        ...(liveSettings && typeof liveSettings === "object" ? liveSettings : {}),
      };
      if (String(settings.workflow_loader_mode || "").trim().toLowerCase() === "checkpoint_runner") {
        settings.workflow_loader_mode = "workflow_model_loader";
      }
      const backendValue = String(settings.workflow_execution_backend || "").trim().toLowerCase();
      if (!backendValue || backendValue === "ltx_checkpoint_runner" || backendValue === "checkpoint_runner") {
        settings.workflow_execution_backend = "native_graph";
      }
      if (String(settings.native_transformer_offload || "").trim().toLowerCase() === "disk") {
        settings.native_transformer_offload = "none";
      }
      if (settings.video_runtime_params_json) {
        const runtimeParams = parseJsonObjectSafe(settings.video_runtime_params_json);
        if (Object.keys(runtimeParams).length) {
          if (String(runtimeParams.workflow_loader_mode || "").trim().toLowerCase() === "checkpoint_runner") {
            runtimeParams.workflow_loader_mode = "workflow_model_loader";
          }
          const runtimeBackend = String(runtimeParams.workflow_execution_backend || "").trim().toLowerCase();
          if (!runtimeBackend || runtimeBackend === "ltx_checkpoint_runner" || runtimeBackend === "checkpoint_runner") {
            runtimeParams.workflow_execution_backend = "native_graph";
          }
          if (String(runtimeParams.native_transformer_offload || "").trim().toLowerCase() === "disk") {
            runtimeParams.native_transformer_offload = "none";
          }
          settings.video_runtime_params_json = stableJsonString(runtimeParams);
        }
      }
      for (const [key, value] of Object.entries(settings)) {
        if ((key.endsWith("_path") || key === "gguf_path" || key === "workflow_runner_path") && value !== undefined && value !== null && value !== "") {
          assets[key] = value;
        }
      }
      const flowNodes = {};
      nodes.forEach((node, index) => {
        const nodeId = String(node?.id || `node${index + 1}`).trim();
        const skillId = String(node?.type || "").trim();
        if (!nodeId || !skillId) return;
        const next = Array.isArray(node?.transitions) ? node.transitions : [];
        const nodeInputs = node?.inputs && typeof node.inputs === "object" ? node.inputs : {};
        const resolvedNodeParams = {};
        const paramsFromInput = [];
        for (const [inputKey, inputValue] of Object.entries(nodeInputs)) {
          if (typeof inputValue === "string" && inputValue.startsWith("$input.")) {
            const sourceKey = inputValue.slice("$input.".length).trim();
            if (sourceKey && !paramsFromInput.includes(inputKey)) paramsFromInput.push(inputKey);
            const fallbackValue = settings[inputKey] ?? settings[sourceKey];
            if (fallbackValue !== undefined && fallbackValue !== null && fallbackValue !== "") resolvedNodeParams[inputKey] = fallbackValue;
            continue;
          }
          if (typeof inputValue === "string" && inputValue.startsWith("$setting.")) {
            const sourceKey = inputValue.slice("$setting.".length).trim();
            const fallbackValue = settings[sourceKey];
            if (fallbackValue !== undefined && fallbackValue !== null && fallbackValue !== "") resolvedNodeParams[inputKey] = fallbackValue;
            continue;
          }
          if (typeof inputValue === "string" && inputValue.includes(".")) {
            continue;
          }
          resolvedNodeParams[inputKey] = inputValue;
        }
        if (skillId === "models.ltx_prompt_encoder" && !paramsFromInput.includes("prompt")) paramsFromInput.push("prompt");
        if (skillId === "models.video_encode" && !paramsFromInput.includes("prompt")) paramsFromInput.push("prompt");
        flowNodes[nodeId] = {
          label: String(node?.label || nodeId),
          plugin_id: "agent_workflow_member",
          agent_kind: "model",
          system_prompt: `Run model workflow node ${nodeId}.`,
          return_only_text: false,
          delay_ms: 0,
          x: Number(node?.x || 80 + (index % 4) * 260),
          y: Number(node?.y || 80 + Math.floor(index / 4) * 180),
          transitions: next.map((row) => ({
            target: String(row?.target || "").trim(),
            condition: row?.condition && typeof row.condition === "object" ? row.condition : { type: "always" },
          })).filter((row) => row.target),
          plugin_settings: {
            role: "Model workflow node",
            node_type: "tool_node",
            action_skill_categories: [],
            action_skills: [skillId],
            tool_config: {
              tool: skillId,
              params_from_input: paramsFromInput,
              params: {
                node_id: nodeId,
                lifecycle: String(node?.lifecycle || workflow?.runtime?.default_lifecycle_policy || "lazy_unload"),
                loader: String(node?.loader || ""),
                device_setting: String(node?.device_setting || ""),
                memory_policy_setting: String(node?.memory_policy_setting || ""),
                assets,
                settings,
                ...resolvedNodeParams,
              },
            },
          },
        };
      });
      const start = String(nodes[0]?.id || "").trim() || Object.keys(flowNodes)[0] || null;
      return {
        flows: {
          [flowName]: {
            workflow_id: String(workflow.workflow_id || manifest?.runtime_profile?.workflow_model_loader_id || manifest?.id || "").trim(),
            category: "models",
            description: String(workflow.description || manifest?.description || ""),
            start,
            nodes: flowNodes,
          },
        },
        default_flow: flowName,
        active_flow: flowName,
        mode: "execute",
        max_steps: Math.max(8, nodes.length + 2),
        metadata: {
          source: "model_deck",
          type_id: typeId,
          manifest_id: String(manifest?.id || ""),
        },
      };
    }

    async function openManifestWorkflowInAgentFlow(manifest) {
      const payload = workflowJsonToAgentFlowImport(manifest);
      if (!payload) {
        toast(ctx, "This tested profile does not declare a workflow graph yet.", true);
        return false;
      }
      const activePid = String(ctx?.state?.ui?.activePid || "default").trim() || "default";
      const activeSid = String(ctx?.state?.ui?.activeSid || "main").trim() || "main";
      const importRes = await apiJson(ctx, `/v1/projects/${encodeURIComponent(activePid)}/sessions/${encodeURIComponent(activeSid)}/agent_flow/flows/import`, {
        method: "POST",
        body: { import: payload, merge: true },
        headers: { "X-Gui-Enabled-Plugins": "collab_chat,agent_flow,model_deck,agent_workflow_member" },
      });
      const resFlows = payload.flows && typeof payload.flows === "object" ? payload.flows : {};
      const current = getRouterSettings(ctx, activeSid, "agent_flow");
      const returnedSettings = importRes?.agent_flow_settings && typeof importRes.agent_flow_settings === "object"
        ? importRes.agent_flow_settings
        : {};
      const returnedFlowIds = importRes?.flow_ids_by_name && typeof importRes.flow_ids_by_name === "object"
        ? importRes.flow_ids_by_name
        : {};
      const mergedFlows = {
        ...(current.agent_flow_flows && typeof current.agent_flow_flows === "object" ? current.agent_flow_flows : {}),
        ...resFlows,
      };
      const mergedFlowIds = {
        ...(current.agent_flow_flow_ids_by_name && typeof current.agent_flow_flow_ids_by_name === "object" ? current.agent_flow_flow_ids_by_name : {}),
        ...returnedFlowIds,
      };
      try {
        const active = String(payload.active_flow || payload.default_flow || "").trim();
        if (active) {
          setRouterSettings(ctx, activeSid, "agent_flow", {
            ...current,
            ...returnedSettings,
            agent_flow_flows: mergedFlows,
            agent_flow_flow_ids_by_name: mergedFlowIds,
            agent_flow_default_flow: active,
            agent_flow_active_flow: active,
            agent_flow_default_workflow_id: String(returnedFlowIds[active] || current.agent_flow_default_workflow_id || ""),
            agent_flow_active_workflow_id: String(returnedFlowIds[active] || current.agent_flow_active_workflow_id || ""),
            agent_flow_mode: "execute",
            agent_flow_max_steps: Number(payload.max_steps || current.agent_flow_max_steps || 32),
          });
        }
      } catch (_err) {}
      ensureGuiPluginEnabled(ctx, "agent_flow");
      if (ctx?.state?.ui && typeof ctx.state.ui === "object") {
        ctx.state.ui.activeGuiPluginId = "agent_flow";
        if (typeof ctx.saveState === "function") ctx.saveState();
      }
      if (typeof ctx?.canAccessPlugin === "function" && !ctx.canAccessPlugin("agent_flow", "open")) {
        toast(ctx, "Workflow was imported, but your current permissions do not allow opening the Agent Flow panel.", true);
        return false;
      }
      if (typeof ctx?.refreshGuiPluginsDiscovery === "function") {
        try {
          await ctx.refreshGuiPluginsDiscovery();
        } catch (_err) {}
      }
      let opened = false;
      if (typeof ctx?.openPluginPanelWhenReady === "function") {
        opened = await ctx.openPluginPanelWhenReady("agent_flow", { openModal: true, forceLoad: true, timeoutMs: 10000 });
      } else if (typeof ctx?.openPluginPanel === "function") {
        ctx.openPluginPanel("agent_flow", { openModal: true });
        opened = true;
      }
      if (!opened && typeof ctx?.openPluginPanel === "function") {
        ctx.openPluginPanel("agent_flow", { openModal: true });
      }
      if (typeof ctx?.openPluginFullView === "function") {
        try {
          ctx.openPluginFullView("agent_flow", { title: "Agent Flow" });
          opened = true;
        } catch (_err) {}
      }
      if (typeof ctx?.activatePanelTab === "function") {
        ctx.activatePanelTab("agent_flow");
      }
      if (opened) {
        toast(ctx, `Opened workflow model loader graph for ${String(manifest?.label || manifest?.id || "profile")}`);
      } else {
        toast(ctx, `Imported workflow graph for ${String(manifest?.label || manifest?.id || "profile")}. Agent Flow did not register an openable panel yet.`, true);
      }
      return opened;
    }

    async function openNamedWorkflowInAgentFlow(flowName, workflowId = "") {
      const active = String(flowName || "").trim();
      if (!active) {
        toast(ctx, "Model workflow was created, but no flow name was returned.", true);
        return false;
      }
      const activePid = String(ctx?.state?.ui?.activePid || "default").trim() || "default";
      const activeSid = String(ctx?.state?.ui?.activeSid || "main").trim() || "main";
      const flowPayload = await apiJson(ctx, `/v1/projects/${encodeURIComponent(activePid)}/sessions/${encodeURIComponent(activeSid)}/agent_flow/flows`, {
        headers: { "X-Gui-Enabled-Plugins": "collab_chat,agent_flow,model_deck,agent_workflow_member" },
      });
      const flows = flowPayload?.flows && typeof flowPayload.flows === "object" ? flowPayload.flows : {};
      const flowIds = flowPayload?.flow_ids_by_name && typeof flowPayload.flow_ids_by_name === "object" ? flowPayload.flow_ids_by_name : {};
      if (!flows[active]) {
        toast(ctx, `Model workflow '${active}' was saved, but Agent Flow did not return it yet. Try reopening the Agent Flow panel.`, true);
        return false;
      }
      const current = getRouterSettings(ctx, activeSid, "agent_flow");
      try {
        setRouterSettings(ctx, activeSid, "agent_flow", {
          ...current,
          agent_flow_flows: flows,
          agent_flow_flow_ids_by_name: flowIds,
          agent_flow_default_flow: active,
          agent_flow_active_flow: active,
          agent_flow_default_workflow_id: String(workflowId || flowIds[active] || ""),
          agent_flow_active_workflow_id: String(workflowId || flowIds[active] || ""),
          agent_flow_mode: "execute",
          agent_flow_max_steps: Number(current.agent_flow_max_steps || 32),
        });
      } catch (_err) {}
      ensureGuiPluginEnabled(ctx, "agent_flow");
      if (ctx?.state?.ui && typeof ctx.state.ui === "object") {
        ctx.state.ui.activeGuiPluginId = "agent_flow";
        if (typeof ctx.saveState === "function") ctx.saveState();
      }
      if (typeof ctx?.canAccessPlugin === "function" && !ctx.canAccessPlugin("agent_flow", "open")) {
        toast(ctx, "Model workflow is ready, but your current permissions do not allow opening the Agent Flow panel.", true);
        return false;
      }
      if (typeof ctx?.refreshGuiPluginsDiscovery === "function") {
        try {
          await ctx.refreshGuiPluginsDiscovery();
        } catch (_err) {}
      }
      let opened = false;
      if (typeof ctx?.openPluginPanelWhenReady === "function") {
        opened = await ctx.openPluginPanelWhenReady("agent_flow", { openModal: true, forceLoad: true, timeoutMs: 10000 });
      } else if (typeof ctx?.openPluginPanel === "function") {
        ctx.openPluginPanel("agent_flow", { openModal: true });
        opened = true;
      }
      if (!opened && typeof ctx?.openPluginPanel === "function") {
        ctx.openPluginPanel("agent_flow", { openModal: true });
      }
      if (typeof ctx?.openPluginFullView === "function") {
        try {
          ctx.openPluginFullView("agent_flow", { title: "Agent Flow" });
          opened = true;
        } catch (_err) {}
      }
      if (typeof ctx?.activatePanelTab === "function") {
        ctx.activatePanelTab("agent_flow");
      }
      toast(ctx, opened ? `Opened model-specific workflow: ${active}` : `Model-specific workflow is ready: ${active}`);
      return opened;
    }

    function applyPickedCompatAssetToField(targetKey, selection) {
      const key = String(targetKey || "").trim();
      const path = String(selection?.modelSource || selection?.result?.model_source || "").trim();
      if (!key || !path) return;
      const row = compatDynamicAssetEntries.find((item) => String(item?.key || "") === key);
      const entryInput = row?.input || entriesByKey[key]?.input || null;
      if (!entryInput) return;
      if (entryInput.allowAuto) {
        if (entryInput.mode) entryInput.mode.value = "manual";
        if (entryInput.value) {
          entryInput.value.disabled = false;
          entryInput.value.value = path;
        }
      } else if ("value" in entryInput) {
        entryInput.value = path;
      }
      syncCompatAssetJsonFromDynamicFields();
    }

    function normalizeCompatNameTokens(values) {
      return Array.isArray(values) ? values.map((item) => String(item || "").trim().toLowerCase()).filter(Boolean) : [];
    }

    function compatAssetRoleScore(slot, file) {
      const roleMeta = slot?.role_meta && typeof slot.role_meta === "object" ? slot.role_meta : {};
      const name = String(file?.filename || "").trim().toLowerCase();
      const ext = String(file?.extension || (name.includes(".") ? `.${name.split(".").pop()}` : "")).trim().toLowerCase();
      const preferredPatterns = normalizeCompatNameTokens(roleMeta?.preferred_patterns);
      const avoidPatterns = normalizeCompatNameTokens(roleMeta?.avoid_patterns);
      const preferredExtensions = normalizeCompatNameTokens(roleMeta?.preferred_extensions);
      let score = 0;
      if (preferredExtensions.length) {
        if (preferredExtensions.includes(ext)) score += 40;
        else score -= 10;
      }
      for (const token of preferredPatterns) {
        if (name.includes(token)) score += 18;
      }
      for (const token of avoidPatterns) {
        if (name.includes(token)) score -= 30;
      }
      const key = String(slot?.key || "").trim().toLowerCase();
      for (const token of key.split(/[^a-z0-9]+/).filter(Boolean)) {
        if (token.length >= 3 && name.includes(token)) score += 8;
      }
      if (slot?.required) score += 2;
      return score;
    }

    function pickBestCompatAssetFile(slot, files) {
      const list = Array.isArray(files) ? files : [];
      let best = null;
      for (const file of list) {
        const score = compatAssetRoleScore(slot, file);
        if (!best || score > best.score) best = { file, score };
      }
      return best;
    }

    function getCompatAssetSearchQuery(targetKey = "") {
      const key = String(targetKey || "").trim();
      const slot = compatDynamicAssetEntries.find((row) => String(row?.key || "") === key)?.slot || null;
      const roleMeta = slot?.role_meta && typeof slot.role_meta === "object" ? slot.role_meta : {};
      const repoHintCandidates = [
        lastDownloadedHfRepoId,
        model?.settings?.hf_source_repo_id,
        entriesByKey["model_id"]?.input?.value,
        model?.settings?.model_id,
      ];
      let repoHint = "";
      for (const candidate of repoHintCandidates) {
        const text = String(candidate || "").trim();
        if (!text) continue;
        if (/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(text)) {
          repoHint = text;
          break;
        }
      }
      const preferred = normalizeCompatNameTokens(roleMeta?.preferred_patterns).slice(0, 3).join(" ");
      const base = repoHint || getDeckSearchQuery();
      return `${base} ${preferred}`.trim();
    }

    async function openCompatAssetSearchPicker() {
      if (!compatDynamicAssetEntries.length) {
        toast(ctx, "No custom asset fields are active for this profile yet.", true);
        return;
      }
      const picker = createModal("Search Hugging Face asset files");
      const defaultTargetKey = String(compatDynamicAssetEntries[0]?.key || "");
      const queryField = createTextField("Search", getCompatAssetSearchQuery(defaultTargetKey));
      const targetField = createSelectField(
        "Populate field",
        compatDynamicAssetEntries.map((row) => ({
          value: String(row.key || ""),
          label: String(row.slot?.role_meta?.label || row.slot?.label || row.key || ""),
        })),
        defaultTargetKey,
      );
      const extField = createSelectField(
        "File type",
        [
          { value: ".gguf,.safetensors", label: "GGUF + safetensors" },
          { value: ".safetensors", label: "safetensors only" },
          { value: ".gguf", label: "GGUF only" },
        ],
        ".gguf,.safetensors",
      );
      const destinationField = createSelectField(
        "Destination",
        [
          { value: "auto", label: getModelDeckBackendMode() === "embedded" ? "Save for embedded (HF cache)" : "Save to data/models" },
          { value: "hf_cache", label: "Save to HF cache only" },
          { value: "models_dir", label: "Save to data/models only" },
          { value: "both", label: "Save to both" },
        ],
        getModelDeckBackendMode() === "embedded" ? "hf_cache" : "models_dir",
      );
      const searchBtn = document.createElement("button");
      searchBtn.type = "button";
      searchBtn.className = "secondary";
      searchBtn.textContent = "Search";
      const toolbar = document.createElement("div");
      toolbar.style.display = "flex";
      toolbar.style.gap = "8px";
      toolbar.style.alignItems = "end";
      toolbar.style.flexWrap = "wrap";
      toolbar.style.marginBottom = "10px";
      toolbar.appendChild(queryField.wrap);
      toolbar.appendChild(targetField.wrap);
      toolbar.appendChild(extField.wrap);
      toolbar.appendChild(destinationField.wrap);
      toolbar.appendChild(searchBtn);
      const status = document.createElement("div");
      status.className = "field-help";
      status.style.marginBottom = "10px";
      const resultsWrap = document.createElement("div");
      resultsWrap.style.display = "grid";
      resultsWrap.style.gap = "8px";
      resultsWrap.style.maxHeight = "420px";
      resultsWrap.style.overflowY = "auto";
      picker.body.appendChild(toolbar);
      picker.body.appendChild(status);
      picker.body.appendChild(resultsWrap);
      let rows = [];
      let selectedRepoId = "";
      let selectedFilename = "";
      let lastAutoQuery = String(queryField.input.value || "").trim();

      async function runAssetDownloadJob(repoId, filename, backendMode, destinationMode, expectedBytes) {
        const started = await apiJson(ctx, "/v1/model_deck/hf_asset_download_start", {
          method: "POST",
          body: {
            repo_id: repoId,
            filename,
            backend_mode: backendMode,
            destination_mode: destinationMode,
            expected_bytes: Number(expectedBytes || 0),
          },
        });
        const jobId = String(started?.job_id || "").trim();
        if (!jobId) throw new Error("Download job was not created");
        let finalRow = null;
        for (let attempt = 0; attempt < 14400; attempt += 1) {
          await new Promise((resolve) => window.setTimeout(resolve, 1000));
          const row = await apiJson(ctx, `/v1/model_deck/hf_asset_download_status?job_id=${encodeURIComponent(jobId)}`);
          const downloaded = Number(row?.downloaded_bytes || 0);
          const expected = Number(row?.expected_bytes || expectedBytes || 0);
          let text = String(row?.status || "Working...");
          if (downloaded > 0 && expected > 0) text += ` (${formatByteSize(downloaded)} / ${formatByteSize(expected)})`;
          else if (expected > 0) text += ` (${formatByteSize(expected)})`;
          status.textContent = text;
          if (row?.done) {
            finalRow = row;
            break;
          }
        }
        if (!finalRow) throw new Error("Asset download timed out");
        if (finalRow.ok === false) throw new Error(String(finalRow.error || finalRow.status || "Download failed"));
        return finalRow;
      }

      function renderResults() {
        resultsWrap.innerHTML = "";
        const activeTargetKey = String(targetField.input.value || "").trim();
        const activeSlot = compatDynamicAssetEntries.find((row) => String(row?.key || "") === activeTargetKey)?.slot || null;
        if (!rows.length) {
          const empty = document.createElement("div");
          empty.className = "field-help";
          empty.textContent = "No matching asset files found yet. Try a broader repo/model query or switch file type.";
          resultsWrap.appendChild(empty);
        }
        for (const repo of rows) {
          const repoId = String(repo?.repo_id || "").trim();
          if (!repoId) continue;
          const card = document.createElement("div");
          card.className = "mdhf-repo-card";
          const title = document.createElement("div");
          title.style.fontWeight = "600";
          title.textContent = repoId;
          const meta = document.createElement("div");
          meta.className = "field-help";
          meta.textContent = `${repo?.pipeline_tag || "model"} | Downloads: ${repo?.downloads || 0} | Likes: ${repo?.likes || 0}`;
          const link = document.createElement("a");
          link.href = String(repo?.repo_url || "#");
          link.target = "_blank";
          link.rel = "noreferrer";
          link.textContent = "Open repo";
          link.style.fontSize = "12px";
          const bestPick = pickBestCompatAssetFile(activeSlot, Array.isArray(repo?.files) ? repo.files : []);
          const bestName = String(bestPick?.file?.filename || "");
          card.appendChild(title);
          card.appendChild(meta);
          card.appendChild(link);
          if (bestName) {
            const bestHint = document.createElement("div");
            bestHint.className = "field-help";
            bestHint.style.marginTop = "6px";
            bestHint.textContent = `Best match for this field: ${bestName}`;
            card.appendChild(bestHint);
          }
          const list = document.createElement("div");
          list.style.display = "grid";
          list.style.gap = "6px";
          list.style.marginTop = "8px";
          const repoFiles = Array.isArray(repo?.files) ? repo.files.slice() : [];
          repoFiles.sort((a, b) => compatAssetRoleScore(activeSlot, b) - compatAssetRoleScore(activeSlot, a));
          for (const file of repoFiles) {
            const row = document.createElement("div");
            row.className = "mdhf-file-row";
            const info = document.createElement("div");
            const score = compatAssetRoleScore(activeSlot, file);
            const isBest = bestName && String(file?.filename || "") === bestName;
            info.innerHTML = `<div class="mdhf-file-name">${file.filename}${isBest ? " <span class=\"md-tag\" style=\"margin-left:6px;\">Best</span>" : ""}</div><div class="mdhf-note">${file.size != null ? formatByteSize(file.size) : "Size unavailable"} | ${file.extension || "file"}${score ? ` | score ${score}` : ""}</div>`;
            const act = document.createElement("div");
            act.className = "md-actions";
            const useBtn = document.createElement("button");
            useBtn.type = "button";
            useBtn.className = "primary";
            useBtn.textContent = "Use this file";
            useBtn.addEventListener("click", async () => {
              try {
                selectedRepoId = repoId;
                selectedFilename = String(file?.filename || "");
                status.textContent = `Downloading ${selectedFilename} from ${selectedRepoId}...`;
                const finalRow = await runAssetDownloadJob(
                  selectedRepoId,
                  selectedFilename,
                  getModelDeckBackendMode(),
                  String(destinationField.input.value || "auto"),
                  Number(file?.size || 0),
                );
                applyPickedCompatAssetToField(String(targetField.input.value || ""), {
                  modelSource: String(finalRow?.result?.model_source || "").trim(),
                });
                overlayClose();
              } catch (err) {
                status.textContent = String(err?.message || err || "Download failed");
              }
            });
            act.appendChild(useBtn);
            row.appendChild(info);
            row.appendChild(act);
            list.appendChild(row);
          }
          card.appendChild(list);
          resultsWrap.appendChild(card);
        }
      }

      async function runSearch() {
        const query = String(queryField.input.value || "").trim();
        if (!query) {
          status.textContent = "Enter a model or repo name to search.";
          return;
        }
        status.textContent = `Searching Hugging Face files for ${query}...`;
        resultsWrap.innerHTML = "";
        try {
          const extensions = String(extField.input.value || ".gguf,.safetensors").split(",").map((item) => String(item || "").trim()).filter(Boolean);
          const res = await apiJson(ctx, "/v1/model_deck/hf_asset_search", {
            method: "POST",
            body: { query, limit: 10, extensions },
          });
          rows = Array.isArray(res?.results) ? res.results : [];
          const fileCount = rows.reduce((sum, repo) => sum + ((repo?.files || []).length || 0), 0);
          status.textContent = rows.length ? `Found ${rows.length} repositories and ${fileCount} matching files.` : "No matching asset files found.";
          renderResults();
        } catch (err) {
          status.textContent = String(err?.message || err || "Search failed");
        }
      }

      searchBtn.addEventListener("click", () => { void runSearch(); });
      targetField.input.addEventListener("change", () => {
        const nextAuto = getCompatAssetSearchQuery(String(targetField.input.value || ""));
        const current = String(queryField.input.value || "").trim();
        if (!current || current === lastAutoQuery) {
          queryField.input.value = nextAuto;
          lastAutoQuery = nextAuto;
        }
        renderResults();
        if (rows.length) return;
        void runSearch();
      });
      queryField.input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          void runSearch();
        }
      });

      let overlayClosed = false;
      function overlayClose() {
        if (overlayClosed) return;
        overlayClosed = true;
        const overlay = picker.body.closest(".router-modal");
        if (!overlay) return;
        const buttons = Array.from(overlay.querySelectorAll("button"));
        const closeLike = buttons.find((btn) => {
          const text = String(btn?.textContent || "").trim().toLowerCase();
          return text === "cancel" || text === "close";
        });
        if (closeLike) closeLike.click();
        else overlay.remove();
      }
      await runSearch();
      await picker.open(async () => false);
    }

    function snapshotEditorSettings() {
      syncCompatAssetJsonFromDynamicFields();
      const settings = {};
      for (const entry of entries) {
        if (!entry?.key) continue;
        if (entry.synthetic) continue;
        const hiddenRuntimeJson = [
          "image_runtime_template_json",
          "image_runtime_assets_json",
          "image_runtime_params_json",
          "image_runtime_extra_args",
        ].includes(String(entry.key || ""));
        if (typeId === "image_gen" && entry.wrap && entry.wrap.style.display === "none" && !entry.persistWhenHidden && !hiddenRuntimeJson) continue;
        const val = readFieldValue(entry.type, entry.input);
        if (val !== undefined) settings[entry.key] = val;
      }
      if (lastDownloadedHfRepoId) settings.hf_source_repo_id = lastDownloadedHfRepoId;
      if (lastDownloadedHfFilename) settings.hf_source_filename = lastDownloadedHfFilename;
      return settings;
    }

    function prefillDiffusersLoaderFields(manifest, force = false) {
      const loader = manifest?.diffusers_loader && typeof manifest.diffusers_loader === "object" ? manifest.diffusers_loader : null;
      if (!loader) return;
      for (const [fieldKey, loaderKey] of [
        ["diffusers_pipeline_class", "pipeline_class"],
        ["diffusers_transformer_class", "transformer_class"],
      ]) {
        const entry = entriesByKey[fieldKey];
        const nextValue = String(loader?.[loaderKey] || "").trim();
        if (!entry?.input || !("value" in entry.input) || !nextValue) continue;
        const currentValue = String(entry.input.value || "").trim();
        const lastAuto = String(entry.input.dataset.modelDeckAutofill || "").trim();
        if (force || !currentValue || currentValue === lastAuto) {
          entry.input.value = nextValue;
          entry.input.dataset.modelDeckAutofill = nextValue;
        }
      }
    }

    function mergePresetJsonPreservingUserValues(currentValue, presetValue, autoCacheKey, wrap, extraAutoCacheKeys = []) {
      const currentObj = parseJsonObjectSafe(currentValue);
      const presetObj = presetValue && typeof presetValue === "object" ? { ...presetValue } : {};
      const lastAutoObj = parseJsonObjectSafe(wrap?.dataset?.[autoCacheKey] || "");
      const extraAutoObjs = Array.isArray(extraAutoCacheKeys)
        ? extraAutoCacheKeys.map((key) => parseJsonObjectSafe(wrap?.dataset?.[key] || ""))
        : [];
      const merged = { ...currentObj };
      for (const [key, nextVal] of Object.entries(presetObj)) {
        const currentVal = merged[key];
        const lastAutoVal = lastAutoObj[key];
        const matchesExtraAuto = extraAutoObjs.some((obj) => JSON.stringify(currentVal) === JSON.stringify(obj?.[key]));
        const currentEmpty = currentVal === undefined || currentVal === null || String(currentVal).trim() === "";
        const matchesLastAuto = currentVal !== undefined && JSON.stringify(currentVal) === JSON.stringify(lastAutoVal);
        if (currentEmpty || matchesLastAuto || matchesExtraAuto) {
          merged[key] = nextVal;
        }
      }
      if (wrap?.dataset) wrap.dataset[autoCacheKey] = stableJsonString(presetObj);
      return stableJsonString(merged);
    }

    function applyCompatManifestToEditor(manifest) {
      if (!manifest || typeof manifest !== "object") return;
      const config = typeId === "image_gen" ? imageRuntimeConfig : (typeId === "video_gen" ? videoRuntimeConfig : null);
      if (!config) return;
      const runtimeProfile = manifest?.runtime_profile && typeof manifest.runtime_profile === "object" ? manifest.runtime_profile : null;
      const runtimeKind = String(runtimeProfile?.kind || "").trim().toLowerCase();
      const modeEntry = entriesByKey[config.modeKey];
      const presetEntry = entriesByKey[config.presetKey];
      const templateEntry = entriesByKey[config.templateKey];
      const assetEntry = entriesByKey[config.assetsKey];
      const paramEntry = entriesByKey[config.paramsKey];
      if (modeEntry?.input && "value" in modeEntry.input) {
        modeEntry.input.value = runtimeKind === "custom_command" ? "advanced" : "standard";
      }
      if (presetEntry?.input && "value" in presetEntry.input) {
        presetEntry.input.value = "";
      }
      if (runtimeKind === "custom_command" && templateEntry?.input && "value" in templateEntry.input) {
        const presetTemplate = stableJsonString(manifest.template_json || {});
        templateEntry.input.value = presetTemplate;
        if (templateEntry.wrap?.dataset) templateEntry.wrap.dataset.autoCompatTemplate = presetTemplate;
      }
      if (assetEntry?.input && "value" in assetEntry.input) {
        assetEntry.input.value = mergePresetJsonPreservingUserValues(
          assetEntry.input.value,
          manifest.assets_json || {},
          "autoCompatAssets",
          assetEntry.wrap,
          ["autoPresetAssets"],
        );
      }
      if (paramEntry?.input && "value" in paramEntry.input) {
        const presetParams = stableJsonString(manifest.params_json || {});
        paramEntry.input.value = presetParams;
        if (paramEntry.wrap?.dataset) paramEntry.wrap.dataset.autoCompatParams = presetParams;
      }
      prefillDiffusersLoaderFields(manifest, true);
      renderCompatDynamicAssetFields(manifest);
      syncCustomRuntimeModeVisibility(config);
      syncVideoWanVisibility();
    }

    async function mountCompatibilityPanel() {
      if (typeId !== "image_gen" && typeId !== "video_gen") return;
      const card = document.createElement("div");
      card.className = "md-card md-compat-section";
      const title = document.createElement("div");
      title.style.fontWeight = "600";
      title.textContent = "Tested compatibility profile";
      const hint = document.createElement("div");
      hint.className = "field-help";
      hint.textContent = "Backend-defined tested profiles live in the Model Deck backend. Select one to check installed requirements and apply its preset template files.";
      const top = document.createElement("div");
      top.style.display = "flex";
      top.style.gap = "8px";
      top.style.alignItems = "end";
      top.style.flexWrap = "wrap";
      const selectField = createSelectField(
        "Tested profile",
        [{ value: "", label: "Auto-detect from this model" }],
        selectedCompatManifestId
      );
      const refreshBtn = document.createElement("button");
      refreshBtn.type = "button";
      refreshBtn.className = "secondary";
      refreshBtn.textContent = "Refresh";
      const applyBtn = document.createElement("button");
      applyBtn.type = "button";
      applyBtn.className = "secondary";
      applyBtn.textContent = "Apply preset files";
      const installAllBtn = document.createElement("button");
      installAllBtn.type = "button";
      installAllBtn.className = "secondary";
      installAllBtn.textContent = "Install missing";
      const uninstallAllBtn = document.createElement("button");
      uninstallAllBtn.type = "button";
      uninstallAllBtn.className = "secondary";
      uninstallAllBtn.textContent = "Uninstall profile deps";
      const openWorkflowBtn = document.createElement("button");
      openWorkflowBtn.type = "button";
      openWorkflowBtn.className = "secondary";
      openWorkflowBtn.textContent = "Open workflow in Agent Flow";
      compatOpenWorkflowBtn = openWorkflowBtn;
      const status = document.createElement("div");
      status.className = "field-help";
      compatDynamicAssetSection = document.createElement("details");
      compatDynamicAssetSection.className = "md-card md-collapsible-section";
      compatDynamicAssetSection.open = false;
      compatDynamicAssetSection.style.display = "none";
      compatDynamicAssetSection.style.padding = "10px";
      const compatAssetHead = document.createElement("summary");
      compatAssetHead.style.display = "flex";
      compatAssetHead.style.alignItems = "center";
      compatAssetHead.style.justifyContent = "space-between";
      compatAssetHead.style.gap = "8px";
      const compatAssetTitle = document.createElement("div");
      compatAssetTitle.style.fontWeight = "600";
      compatAssetTitle.textContent = "Profile asset fields";
      compatAssetSearchBtn = document.createElement("button");
      compatAssetSearchBtn.type = "button";
      compatAssetSearchBtn.className = "secondary";
      compatAssetSearchBtn.textContent = "Search Hugging Face asset files";
      compatAssetSearchBtn.style.display = "none";
      compatAssetSearchBtn.style.marginLeft = "auto";
      compatAssetSearchBtn.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        void openCompatAssetSearchPicker();
      });
      compatAssetHead.appendChild(compatAssetTitle);
      compatAssetHead.appendChild(compatAssetSearchBtn);
      const compatAssetHint = document.createElement("div");
      compatAssetHint.className = "field-help";
      compatAssetHint.textContent = "These fields are declared by the tested profile and sync back into the custom asset JSON automatically.";
      compatDynamicAssetSection.appendChild(compatAssetHead);
      compatDynamicAssetSection.appendChild(compatAssetHint);
      const reqDetails = document.createElement("details");
      reqDetails.className = "md-card md-collapsible-section";
      reqDetails.open = false;
      reqDetails.style.padding = "10px";
      const reqSummary = document.createElement("summary");
      reqSummary.textContent = "Requirements / dependency packages";
      reqDetails.appendChild(reqSummary);
      const reqList = document.createElement("div");
      reqList.style.display = "grid";
      reqList.style.gap = "8px";
      reqList.style.marginTop = "10px";
      reqDetails.appendChild(reqList);
      top.appendChild(selectField.wrap);
      top.appendChild(refreshBtn);
      top.appendChild(applyBtn);
      top.appendChild(openWorkflowBtn);
      top.appendChild(installAllBtn);
      top.appendChild(uninstallAllBtn);
      card.appendChild(title);
      card.appendChild(hint);
      card.appendChild(top);
      card.appendChild(status);
      card.appendChild(compatDynamicAssetSection);
      card.appendChild(reqDetails);
      settingsWrap.appendChild(card);

      let manifests = [];
      let refreshTimer = null;

      function isWorkflowCompatManifest(manifest) {
        if (!manifest || typeof manifest !== "object") return false;
        const runtimeProfile = manifest.runtime_profile && typeof manifest.runtime_profile === "object" ? manifest.runtime_profile : null;
        const runtimeKind = String(runtimeProfile?.kind || "").trim().toLowerCase();
        const text = `${String(manifest.id || "")} ${String(manifest.label || "")}`.toLowerCase();
        return Boolean(manifest.workflow_json && Object.keys(manifest.workflow_json || {}).length)
          || runtimeKind === "internal_workflow"
          || runtimeKind.includes("workflow")
          || text.includes("workflow");
      }

      function visibleCompatManifests() {
        if (getModelBackendValue() !== "default") return manifests;
        return manifests.filter((row) => !isWorkflowCompatManifest(row));
      }

      function selectedManifestId() {
        const id = String(selectField.input.value || selectedCompatManifestId || "").trim();
        if (!id) return "";
        return visibleCompatManifests().some((row) => String(row?.id || "") === id) ? id : "";
      }

      function scheduleRefresh() {
        if (refreshTimer) window.clearTimeout(refreshTimer);
        refreshTimer = window.setTimeout(() => { void refreshStatus(); }, 250);
      }
      requestCompatRefresh = scheduleRefresh;

      function renderStatus(payload) {
        const rawPayload = payload || null;
        const rawManifest = rawPayload?.manifest || null;
        const ignoredWorkflowForDefault = getModelBackendValue() === "default" && isWorkflowCompatManifest(rawManifest);
        payload = ignoredWorkflowForDefault ? { ...(rawPayload || {}), manifest: null, matched: false, requirements: [] } : rawPayload;
        currentStatus = payload || null;
        selectedCompatManifestId = String(payload?.manifest?.id || selectedManifestId() || selectedCompatManifestId || "").trim();
        if (ignoredWorkflowForDefault) selectedCompatManifestId = "";
        if (selectedCompatManifestId && selectField.input.value !== selectedCompatManifestId) {
          selectField.input.value = selectedCompatManifestId;
        }
        if (!selectedCompatManifestId && selectField.input.value) {
          selectField.input.value = "";
        }
        reqList.innerHTML = "";
        const manifest = payload?.manifest || null;
        const matched = !!payload?.matched;
        if (manifest) {
          status.textContent = `${matched ? "Matched" : "Selected"} profile: ${manifest.label || manifest.id}${payload?.all_installed ? " — all requirements installed" : ""}`;
        } else if (ignoredWorkflowForDefault) {
          status.textContent = "No default-route tested profile matched this model. Switch Model Backend to Workflow to use workflow profiles.";
        } else {
          status.textContent = "No tested profile matched this model yet.";
        }
        renderCompatDynamicAssetFields(manifest);
        syncVideoWanVisibility();
        applyBtn.disabled = !manifest;
        uninstallAllBtn.disabled = !manifest;
        openWorkflowBtn.disabled = !hasOpenableWorkflowTarget(manifest);
        syncWorkflowModelLoaderVisibility();
        const requirements = Array.isArray(payload?.requirements) ? payload.requirements : [];
        const missingCount = requirements.filter((row) => !row?.installed).length;
        const hasMissingInstallable = requirements.some((row) => !row?.installed && Array.isArray(row?.install) && row.install.length);
        installAllBtn.style.display = hasMissingInstallable ? "" : "none";
        installAllBtn.disabled = !manifest || !hasMissingInstallable;
        reqSummary.textContent = requirements.length
          ? `Requirements / dependency packages (${missingCount ? `${missingCount} missing of ${requirements.length}` : `${requirements.length} installed`})`
          : "Requirements / dependency packages";
        if (!requirements.length) {
          const empty = document.createElement("div");
          empty.className = "field-help";
          empty.textContent = manifest ? "This profile does not declare any installable requirements." : "Add a tested-model folder in the backend registry to enable compatibility checks here.";
          reqList.appendChild(empty);
          return;
        }
        for (const row of requirements) {
          const wrap = document.createElement("div");
          wrap.className = "md-card";
          wrap.style.padding = "10px";
          const head = document.createElement("div");
          head.style.display = "flex";
          head.style.justifyContent = "space-between";
          head.style.alignItems = "center";
          head.style.gap = "8px";
          const label = document.createElement("div");
          label.innerHTML = `<div style="font-weight:600;">${String(row?.label || row?.id || "Requirement")}</div><div class="field-help">${String(row?.detail || "")}</div>`;
          if (row?.url || row?.target_path || row?.install_hint) {
            const sourceHelp = document.createElement("div");
            sourceHelp.className = "field-help";
            sourceHelp.style.marginTop = "4px";
            const parts = [];
            if (row?.kind) parts.push(`type: ${String(row.kind)}`);
            if (row?.target_path) parts.push(`target: ${String(row.target_path)}`);
            if (row?.url) parts.push(`git: ${String(row.url)}`);
            if (row?.install_hint) parts.push(`install: ${String(row.install_hint)}`);
            sourceHelp.textContent = parts.join(" · ");
            label.appendChild(sourceHelp);
          }
          const actions = document.createElement("div");
          actions.className = "md-actions";
          const stateChip = document.createElement("span");
          stateChip.className = "md-tag";
          stateChip.textContent = row?.installed ? "Installed" : "Missing";
          stateChip.style.background = row?.installed ? "rgba(44, 166, 90, 0.12)" : "rgba(213, 90, 90, 0.12)";
          stateChip.style.border = row?.installed ? "1px solid rgba(44, 166, 90, 0.28)" : "1px solid rgba(213, 90, 90, 0.28)";
          actions.appendChild(stateChip);
          if (!row?.installed && Array.isArray(row?.install) && row.install.length) {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "secondary";
            btn.textContent = "Install";
            btn.addEventListener("click", async () => {
              try {
                btn.disabled = true;
                await apiJson(ctx, "/v1/model_deck/compat/install", {
                  method: "POST",
                  body: { type_id: typeId, manifest_id: manifest?.id || "", settings: snapshotEditorSettings(), requirement_ids: [String(row?.id || "")] },
                });
                toast(ctx, `Installed ${String(row?.label || row?.id || "requirement")}`);
                await refreshStatus();
              } catch (err) {
                toast(ctx, String(err?.message || err || "Install failed"), true);
              } finally {
                btn.disabled = false;
              }
            });
            actions.appendChild(btn);
          }
          if (Array.isArray(row?.uninstall) && row.uninstall.length) {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "secondary";
            btn.textContent = "Uninstall";
            btn.addEventListener("click", async () => {
              try {
                btn.disabled = true;
                await apiJson(ctx, "/v1/model_deck/compat/uninstall", {
                  method: "POST",
                  body: { type_id: typeId, manifest_id: manifest?.id || "", settings: snapshotEditorSettings(), requirement_ids: [String(row?.id || "")] },
                });
                toast(ctx, `Uninstalled ${String(row?.label || row?.id || "requirement")}`);
                await refreshStatus();
              } catch (err) {
                toast(ctx, String(err?.message || err || "Uninstall failed"), true);
              } finally {
                btn.disabled = false;
              }
            });
            actions.appendChild(btn);
          }
          head.appendChild(label);
          head.appendChild(actions);
          wrap.appendChild(head);
          reqList.appendChild(wrap);
        }
      }

      async function refreshCatalog() {
        const payload = await apiJson(ctx, `/v1/model_deck/compat/catalog?type_id=${encodeURIComponent(typeId)}`);
        manifests = Array.isArray(payload?.manifests) ? payload.manifests : [];
        compatManifestCache = new Map(manifests.map((row) => [String(row?.id || ""), row]));
        const current = selectedManifestId() || selectedCompatManifestId;
        const visibleManifests = visibleCompatManifests();
        selectField.input.innerHTML = "";
        selectField.input.appendChild(new Option("Auto-detect from this model", ""));
        for (const row of visibleManifests) {
          const opt = new Option(String(row?.label || row?.id || ""), String(row?.id || ""));
          if (row?.description) opt.title = String(row.description);
          selectField.input.appendChild(opt);
        }
        if (current && visibleManifests.some((row) => String(row?.id || "") === current)) {
          selectField.input.value = current;
          selectedCompatManifestId = current;
        } else if (current) {
          selectField.input.value = "";
          selectedCompatManifestId = "";
        }
      }

      async function refreshStatus() {
        try {
          refreshBtn.disabled = true;
          status.textContent = "Checking compatibility requirements...";
          const payload = await apiJson(ctx, "/v1/model_deck/compat/status", {
            method: "POST",
            body: {
              type_id: typeId,
              manifest_id: selectedManifestId(),
              settings: snapshotEditorSettings(),
            },
          });
          const manifest = payload?.manifest || null;
          if (manifest?.id && !selectedManifestId() && !(getModelBackendValue() === "default" && isWorkflowCompatManifest(manifest))) {
            selectField.input.value = String(manifest.id);
          }
          renderStatus(payload);
          if (manifest) prefillDiffusersLoaderFields(manifest, false);
        } catch (err) {
          status.textContent = String(err?.message || err || "Compatibility check failed");
          reqList.innerHTML = "";
          reqSummary.textContent = "Requirements / dependency packages";
        } finally {
          refreshBtn.disabled = false;
        }
      }

      selectField.input.addEventListener("change", () => {
        selectedCompatManifestId = selectedManifestId();
        void refreshStatus();
      });
      if (entriesByKey["model_backend"]?.input && typeof entriesByKey["model_backend"].input.addEventListener === "function") {
        entriesByKey["model_backend"].input.addEventListener("change", () => {
          void (async () => {
            await refreshCatalog();
            await refreshStatus();
          })();
        });
      }
      refreshBtn.addEventListener("click", () => { void refreshStatus(); });
      applyBtn.addEventListener("click", () => {
        const manifest = currentStatus?.manifest || null;
        if (!manifest) return;
        applyCompatManifestToEditor(manifest);
        toast(ctx, `Applied tested preset files for ${String(manifest.label || manifest.id || "profile")}`);
      });
      openWorkflowBtn.addEventListener("click", async () => {
        let manifest = currentStatus?.manifest || null;
        try {
          openWorkflowBtn.disabled = true;
          openWorkflowBtn.textContent = "Opening workflow...";
          status.textContent = "Preparing workflow graph for Agent Flow...";
          const savedFlowName = getSavedWorkflowFlowName();
          if (!manifest) {
            if (savedFlowName) {
              const opened = await openNamedWorkflowInAgentFlow(savedFlowName, "");
              status.textContent = opened
                ? `Opened Agent Flow for ${savedFlowName}.`
                : `Prepared ${savedFlowName}, but Agent Flow did not open. Open the Agent Flow panel manually and select this workflow.`;
              return;
            }
            toast(ctx, "Loading tested profile workflow...");
            await refreshStatus();
            manifest = currentStatus?.manifest || null;
          }
          if (!manifest) {
            const msg = "No tested profile is selected or matched yet.";
            status.textContent = msg;
            toast(ctx, msg, true);
            return;
          }
          if (!(manifest?.workflow_json && Object.keys(manifest.workflow_json || {}).length)) {
            const msg = "This tested profile is loaded, but the server did not return workflow_json. Restart the backend if this was just patched.";
            status.textContent = msg;
            toast(ctx, msg, true);
            return;
          }
          const activePid = String(ctx?.state?.ui?.activePid || "default").trim() || "default";
          const editorSettings = snapshotEditorSettings();
          // The editor field named "model_id" is often the underlying HF repo
          // or runtime model path.  The workflow endpoint needs the saved deck
          // model id first, otherwise repos like "vantagewithai/LTX-2.3-GGUF"
          // are mistaken for deck ids and produce a 404.
          const editorModelId = String(model?.model_id || entriesByKey["model_id"]?.input?.value || "").trim();
          if (!editorModelId) {
            const msg = "Save or enter a Model ID before opening its private workflow.";
            status.textContent = msg;
            toast(ctx, msg, true);
            return;
          }
          status.textContent = `Preparing model-specific workflow for ${editorModelId}...`;
          const ensured = await apiJson(ctx, "/v1/model_deck/model/workflow/ensure", {
            method: "POST",
            body: {
              type_id: typeId,
              model_id: editorModelId,
              pid: activePid,
              template_flow_name: String(manifest?.workflow_json?.active_flow || manifest?.workflow_json?.default_flow || "Models / Unsloth LTX 2.3 GGUF"),
              settings: editorSettings,
            },
            headers: { "X-Gui-Enabled-Plugins": "collab_chat,agent_flow,model_deck,agent_workflow_member" },
          });
          status.textContent = `${ensured?.created ? "Created" : "Using"} private workflow: ${String(ensured?.flow_name || "")}`;
          if (entriesByKey["model_workflow_flow_name"]?.input) {
            entriesByKey["model_workflow_flow_name"].input.value = String(ensured?.flow_name || "");
          }
          if (entriesByKey["model_workflow_template_flow_name"]?.input) {
            entriesByKey["model_workflow_template_flow_name"].input.value = String(ensured?.template_flow_name || "");
          }
          const opened = await openNamedWorkflowInAgentFlow(String(ensured?.flow_name || ""), String(ensured?.workflow_id || ""));
          status.textContent = opened
            ? `Opened Agent Flow for ${String(ensured?.flow_name || manifest.label || manifest.id || "workflow")}.`
            : `Prepared ${String(ensured?.flow_name || manifest.label || manifest.id || "workflow")}, but Agent Flow did not open. Open the Agent Flow panel manually and select this workflow.`;
        } catch (err) {
          const msg = String(err?.message || err || "Failed to open workflow");
          status.textContent = msg;
          toast(ctx, msg, true);
        } finally {
          openWorkflowBtn.textContent = "Open workflow in Agent Flow";
          openWorkflowBtn.disabled = !hasOpenableWorkflowTarget(currentStatus?.manifest || null);
          syncWorkflowModelLoaderVisibility();
        }
      });
      installAllBtn.addEventListener("click", async () => {
        const manifest = currentStatus?.manifest || null;
        if (!manifest) return;
        try {
          installAllBtn.disabled = true;
          await apiJson(ctx, "/v1/model_deck/compat/install", {
            method: "POST",
            body: { type_id: typeId, manifest_id: String(manifest.id || ""), settings: snapshotEditorSettings(), requirement_ids: [] },
          });
          toast(ctx, `Installed declared requirements for ${String(manifest.label || manifest.id || "profile")}`);
          await refreshStatus();
        } catch (err) {
          toast(ctx, String(err?.message || err || "Install failed"), true);
        } finally {
          installAllBtn.disabled = false;
        }
      });
      uninstallAllBtn.addEventListener("click", async () => {
        const manifest = currentStatus?.manifest || null;
        if (!manifest) return;
        try {
          uninstallAllBtn.disabled = true;
          await apiJson(ctx, "/v1/model_deck/compat/uninstall", {
            method: "POST",
            body: { type_id: typeId, manifest_id: String(manifest.id || ""), settings: snapshotEditorSettings(), requirement_ids: [] },
          });
          toast(ctx, `Uninstalled declared requirements for ${String(manifest.label || manifest.id || "profile")}`);
          await refreshStatus();
        } catch (err) {
          toast(ctx, String(err?.message || err || "Uninstall failed"), true);
        } finally {
          uninstallAllBtn.disabled = false;
        }
      });

      for (const key of ["model_id", "backend", "gguf_path", "model_path"]) {
        const entry = entriesByKey[key];
        if (entry?.input && typeof entry.input.addEventListener === "function") {
          entry.input.addEventListener("change", scheduleRefresh);
          entry.input.addEventListener("input", scheduleRefresh);
        }
      }

      status.textContent = "Loading tested compatibility profile...";
      void (async () => {
        try {
          await refreshCatalog();
          await refreshStatus();
        } catch (err) {
          status.textContent = String(err?.message || err || "Compatibility profile failed to load");
          reqList.innerHTML = "";
          reqSummary.textContent = "Requirements / dependency packages";
        }
      })();
    }

    function attachSpeechTtsCompanionSearchButton() {
      if (typeId !== "speech_tts") return;
      const companionEntry = entriesByKey["companion_model_path"];
      if (!companionEntry?.wrap || !companionEntry?.input || companionEntry.wrap.querySelector('[data-field-action="companion-hf-search"]')) return;
      const shell = document.createElement("div");
      shell.className = "field";
      shell.style.marginTop = "8px";
      shell.dataset.fieldAction = "companion-hf-search";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary";
      button.textContent = "Search HuggingFace GGUF";
      button.addEventListener("click", async () => {
        try {
          await openGgufSearchPicker({
            title: "Search companion GGUF model",
            subtext: "Search HuggingFace for companion or codec GGUF files such as Chatterbox S3Gen. Selecting a file downloads it and fills Companion Model Path.",
            query: getCompanionSearchQuery(),
            onPick: applyPickedCompanionGguf,
          });
        } catch (err) {
          toast(ctx, String(err?.message || err || "Failed to search HuggingFace"), true);
        }
      });
      const hint = document.createElement("div");
      hint.className = "field-help";
      hint.textContent = "Download a companion / codec GGUF from Hugging Face and fill this field automatically.";
      shell.appendChild(button);
      shell.appendChild(hint);
      companionEntry.wrap.appendChild(shell);
    }

    function syncSpeechTtsPresetTemplate() {
      if (typeId !== "speech_tts") return;
      const presetEntry = entriesByKey["speech_template_preset"];
      const templateEntry = entriesByKey["speech_runtime_template_json"];
      const assetEntry = entriesByKey["speech_runtime_assets_json"];
      const paramEntry = entriesByKey["speech_runtime_params_json"];
      if (!presetEntry?.input || !templateEntry?.input || !("value" in presetEntry.input) || !("value" in templateEntry.input)) return;
      const presetId = String(presetEntry.input.value || "").trim();
      const preset = TTS_PRESET_TEMPLATE_JSON[presetId];
      if (!preset) return;
      const nextText = stableJsonString(preset);
      const currentText = String(templateEntry.input.value || "").trim();
      const lastAutoText = String(templateEntry.wrap?.dataset?.autoPresetTemplate || "").trim();
      if (!currentText || currentText === lastAutoText) {
        templateEntry.input.value = nextText;
        if (templateEntry.wrap?.dataset) templateEntry.wrap.dataset.autoPresetTemplate = nextText;
      }
      if (assetEntry?.input && "value" in assetEntry.input) {
        const nextAssetText = stableJsonString(TTS_PRESET_ASSET_JSON[presetId] || {});
        const currentAssetText = String(assetEntry.input.value || "").trim();
        const lastAutoAssetText = String(assetEntry.wrap?.dataset?.autoPresetAssets || "").trim();
        if (!currentAssetText || currentAssetText === lastAutoAssetText) {
          assetEntry.input.value = nextAssetText;
          if (assetEntry.wrap?.dataset) assetEntry.wrap.dataset.autoPresetAssets = nextAssetText;
        }
      }
      if (paramEntry?.input && "value" in paramEntry.input) {
        const nextParamText = stableJsonString(TTS_PRESET_PARAM_JSON[presetId] || {});
        const currentParamText = String(paramEntry.input.value || "").trim();
        const lastAutoParamText = String(paramEntry.wrap?.dataset?.autoPresetParams || "").trim();
        if (!currentParamText || currentParamText === lastAutoParamText) {
          paramEntry.input.value = nextParamText;
          if (paramEntry.wrap?.dataset) paramEntry.wrap.dataset.autoPresetParams = nextParamText;
        }
      }
    }

    function syncSpeechAsrPresetTemplate() {
      if (typeId !== "speech_asr") return;
      const presetEntry = entriesByKey["speech_template_preset"];
      const templateEntry = entriesByKey["speech_runtime_template_json"];
      const assetEntry = entriesByKey["speech_runtime_assets_json"];
      const paramEntry = entriesByKey["speech_runtime_params_json"];
      if (!presetEntry?.input || !templateEntry?.input || !("value" in presetEntry.input) || !("value" in templateEntry.input)) return;
      const presetId = String(presetEntry.input.value || "").trim();
      const preset = ASR_PRESET_TEMPLATE_JSON[presetId];
      if (!preset) return;
      const nextText = stableJsonString(preset);
      const currentText = String(templateEntry.input.value || "").trim();
      const lastAutoText = String(templateEntry.wrap?.dataset?.autoPresetTemplate || "").trim();
      if (!currentText || currentText === lastAutoText) {
        templateEntry.input.value = nextText;
        if (templateEntry.wrap?.dataset) templateEntry.wrap.dataset.autoPresetTemplate = nextText;
      }
      if (assetEntry?.input && "value" in assetEntry.input) {
        const nextAssetText = stableJsonString(ASR_PRESET_ASSET_JSON[presetId] || {});
        const currentAssetText = String(assetEntry.input.value || "").trim();
        const lastAutoAssetText = String(assetEntry.wrap?.dataset?.autoPresetAssets || "").trim();
        if (!currentAssetText || currentAssetText === lastAutoAssetText) {
          assetEntry.input.value = nextAssetText;
          if (assetEntry.wrap?.dataset) assetEntry.wrap.dataset.autoPresetAssets = nextAssetText;
        }
      }
      if (paramEntry?.input && "value" in paramEntry.input) {
        const nextParamText = stableJsonString(ASR_PRESET_PARAM_JSON[presetId] || {});
        const currentParamText = String(paramEntry.input.value || "").trim();
        const lastAutoParamText = String(paramEntry.wrap?.dataset?.autoPresetParams || "").trim();
        if (!currentParamText || currentParamText === lastAutoParamText) {
          paramEntry.input.value = nextParamText;
          if (paramEntry.wrap?.dataset) paramEntry.wrap.dataset.autoPresetParams = nextParamText;
        }
      }
    }

    function syncCustomRuntimePreset(config) {
      if (!config || typeId !== config.typeId) return;
      const presetEntry = entriesByKey[config.presetKey];
      const templateEntry = entriesByKey[config.templateKey];
      const assetEntry = entriesByKey[config.assetsKey];
      const paramEntry = entriesByKey[config.paramsKey];
      const requirementsEntry = entriesByKey[config.requirementsKey];
      const installEntry = entriesByKey[config.installKey];
      if (!presetEntry?.input || !templateEntry?.input || !("value" in presetEntry.input) || !("value" in templateEntry.input)) return;
      const presetId = String(presetEntry.input.value || "").trim();
      const preset = config.templateMap?.[presetId];
      if (!preset) return;
      const nextText = stableJsonString(preset);
      const currentText = String(templateEntry.input.value || "").trim();
      const lastAutoText = String(templateEntry.wrap?.dataset?.autoPresetTemplate || "").trim();
      if (!currentText || currentText === lastAutoText) {
        templateEntry.input.value = nextText;
        if (templateEntry.wrap?.dataset) templateEntry.wrap.dataset.autoPresetTemplate = nextText;
      }
      if (assetEntry?.input && "value" in assetEntry.input) {
        const nextAssetText = stableJsonString(config.assetMap?.[presetId] || {});
        const currentAssetText = String(assetEntry.input.value || "").trim();
        const lastAutoAssetText = String(assetEntry.wrap?.dataset?.autoPresetAssets || "").trim();
        if (!currentAssetText || currentAssetText === lastAutoAssetText) {
          assetEntry.input.value = nextAssetText;
          if (assetEntry.wrap?.dataset) assetEntry.wrap.dataset.autoPresetAssets = nextAssetText;
        }
      }
      if (paramEntry?.input && "value" in paramEntry.input) {
        const nextParamText = stableJsonString(config.paramMap?.[presetId] || {});
        const currentParamText = String(paramEntry.input.value || "").trim();
        const lastAutoParamText = String(paramEntry.wrap?.dataset?.autoPresetParams || "").trim();
        if (!currentParamText || currentParamText === lastAutoParamText) {
          paramEntry.input.value = nextParamText;
          if (paramEntry.wrap?.dataset) paramEntry.wrap.dataset.autoPresetParams = nextParamText;
        }
      }
      if (requirementsEntry?.input && "value" in requirementsEntry.input) {
        const nextRequirementsText = String(config.requirementsMap?.[presetId] || "").trim();
        const currentRequirementsText = String(requirementsEntry.input.value || "").trim();
        const lastAutoRequirementsText = String(requirementsEntry.wrap?.dataset?.autoPresetRequirements || "").trim();
        if (!currentRequirementsText || currentRequirementsText === lastAutoRequirementsText) {
          requirementsEntry.input.value = nextRequirementsText;
          if (requirementsEntry.wrap?.dataset) requirementsEntry.wrap.dataset.autoPresetRequirements = nextRequirementsText;
        }
      }
      if (installEntry?.input && "value" in installEntry.input) {
        const nextInstallText = String(config.installMap?.[presetId] || "").trim();
        const currentInstallText = String(installEntry.input.value || "").trim();
        const lastAutoInstallText = String(installEntry.wrap?.dataset?.autoPresetInstall || "").trim();
        if (!currentInstallText || currentInstallText === lastAutoInstallText) {
          installEntry.input.value = nextInstallText;
          if (installEntry.wrap?.dataset) installEntry.wrap.dataset.autoPresetInstall = nextInstallText;
        }
      }
    }

    function syncCustomRuntimeModeVisibility(config) {
      if (!config || typeId !== config.typeId) return;
      syncModelBackendCompatibilityFields();
      const modeEntry = entriesByKey[config.modeKey];
      syncExecutionModeForBackend(config);
      const modeValue = String(modeEntry?.input?.value || "standard").trim().toLowerCase();
      const showWorkflow = getModelBackendValue() === "workflow";
      const showCustom = modeValue === "advanced" && !showWorkflow;
      for (const key of [config.presetKey, config.templateKey, config.assetsKey, config.paramsKey, config.extraArgsKey]) {
        const entry = entriesByKey[key];
        if (!entry?.wrap) continue;
        entry.wrap.style.display = showCustom ? "" : "none";
      }
      if (entriesByKey[config.modeKey]?.wrap) {
        entriesByKey[config.modeKey].wrap.style.display = showWorkflow ? "none" : "";
      }
      if (compatDynamicAssetSection) {
        const selectedManifest = compatManifestCache.get(String(selectedCompatManifestId || "").trim()) || null;
        const runtimeProfile = selectedManifest?.runtime_profile && typeof selectedManifest.runtime_profile === "object" ? selectedManifest.runtime_profile : null;
        const runtimeKind = String(runtimeProfile?.kind || "").trim().toLowerCase();
        const showCompatAssets = compatDynamicAssetEntries.length && (runtimeKind === "internal_workflow" || showCustom);
        compatDynamicAssetSection.style.display = showCompatAssets ? "" : "none";
      }
      syncWorkflowModelLoaderVisibility();
    }

    function syncWorkflowModelLoaderVisibility() {
      if (typeId !== "image_gen" && typeId !== "video_gen") return;
      syncModelBackendCompatibilityFields();
      const showWorkflow = getModelBackendValue() === "workflow";
      for (const key of ["workflow_node_lifecycle_policy", "workflow_node_timeout_s"]) {
        setAllEntriesDisplay(key, showWorkflow ? "" : "none");
      }
      for (const key of ["workflow_loader_mode", "workflow_execution_backend", "comfyui_runtime_root", "comfyui_gguf_vendor_root"]) {
        setAllEntriesDisplay(key, "none");
      }
      if (compatOpenWorkflowBtn) {
        compatOpenWorkflowBtn.style.display = showWorkflow ? "" : "none";
        compatOpenWorkflowBtn.disabled = !showWorkflow || !hasOpenableWorkflowTarget(currentStatus?.manifest || null);
      }
      syncDefaultBackendFieldVisibility();
      syncVideoWanVisibility();
    }

    function syncDefaultBackendFieldVisibility() {
      if (typeId !== "image_gen" && typeId !== "video_gen") return;
      const showWorkflow = getModelBackendValue() === "workflow";
      const keys = typeId === "video_gen"
        ? [
          "model_id",
          "diffusers_pipeline_class",
          "diffusers_transformer_class",
          "enable_model_cpu_offload",
          "enable_sequential_cpu_offload",
          "gguf_path",
          "gemma_max_tokens",
          "allow_eager_gemma_gpu",
        ]
        : [
          "model_id",
          "image_command_mode",
          "image_template_preset",
          "image_runtime_template_json",
          "image_runtime_assets_json",
          "image_runtime_params_json",
          "image_runtime_extra_args",
          "diffusers_pipeline_class",
          "diffusers_transformer_class",
          "enable_model_cpu_offload",
          "enable_sequential_cpu_offload",
          "gguf_path",
          "text_encoder_path",
          "use_unet",
          "sdxl_unet_path",
          "sdxl_unet_repo",
          "sdxl_unet_filename",
          "sdxl_base_model",
          "sdxl_variant",
          "sdxl_timestep_spacing",
          "vae_path",
          "clip_path",
          "gguf_filename",
          "hf_token",
          "dtype",
          "device",
          "gpu_selection_mode",
          "main_gpu",
          "max_sequence_length",
          "low_cpu_mem_usage",
          "cli_path",
          "cli_args",
          "output_ext",
          "clip_l_path",
          "clip_g_path",
          "t5xxl_path",
          "t5_path",
          "n_threads",
          "n_gpu_layers",
          "sdcpp_kwargs",
          "timeout_s",
          "steps",
          "cfg_scale",
          "width",
          "height",
          "sampler",
          "seed",
        ];
      for (const key of keys) {
        setAllEntriesDisplay(key, showWorkflow ? "none" : "");
      }
    }

    function syncVideoWanVisibility() {
      if (typeId !== "video_gen") return;
      const showWorkflow = getModelBackendValue() === "workflow";
      for (const key of ["ltx_video_only", "use_wan", "use_wan_vae", "wan_vae_subfolder", "wan_vae_dtype"]) {
        const entry = entriesByKey[key];
        if (entry?.wrap && showWorkflow) entry.wrap.style.display = "none";
      }
      if (showWorkflow) return;
      const modelText = String(entriesByKey["model_id"]?.input?.value || model?.settings?.model_id || "").trim().toLowerCase();
      const explicitWan = Boolean(entriesByKey["use_wan"]?.input?.checked);
      const compatText = String(selectedCompatManifestId || "").trim().toLowerCase();
      const showWan = explicitWan || compatText.includes("wan") || /\bwan([-. ]?2(\.1)?)?\b/.test(modelText);
      if (entriesByKey["ltx_video_only"]?.wrap) entriesByKey["ltx_video_only"].wrap.style.display = "";
      for (const key of ["use_wan", "use_wan_vae", "wan_vae_subfolder", "wan_vae_dtype"]) {
        const entry = entriesByKey[key];
        if (!entry?.wrap) continue;
        entry.wrap.style.display = showWan ? "" : "none";
      }
    }

    function syncSpeechTtsModeVisibility() {
      if (typeId !== "speech_tts") return;
      const modeEntry = entriesByKey["speech_command_mode"];
      const modeValue = String(modeEntry?.input?.value || "standard").trim().toLowerCase();
      const showCustom = modeValue === "advanced";
      for (const key of [
        "speech_template_preset",
        "speech_runtime_template_json",
        "speech_runtime_assets_json",
        "speech_runtime_params_json",
      ]) {
        const entry = entriesByKey[key];
        if (!entry?.wrap) continue;
        entry.wrap.style.display = showCustom ? "" : "none";
      }
    }

    function syncSpeechAsrModeVisibility() {
      if (typeId !== "speech_asr") return;
      const modeEntry = entriesByKey["speech_command_mode"];
      const modeValue = String(modeEntry?.input?.value || "standard").trim().toLowerCase();
      const showCustom = modeValue === "advanced";
      for (const key of [
        "speech_template_preset",
        "speech_runtime_template_json",
        "speech_runtime_assets_json",
        "speech_runtime_params_json",
      ]) {
        const entry = entriesByKey[key];
        if (!entry?.wrap) continue;
        entry.wrap.style.display = showCustom ? "" : "none";
      }
    }

    const imageRuntimeConfig = {
      typeId: "image_gen",
      modeKey: "image_command_mode",
      presetKey: "image_template_preset",
      templateKey: "image_runtime_template_json",
      assetsKey: "image_runtime_assets_json",
      paramsKey: "image_runtime_params_json",
      extraArgsKey: "image_runtime_extra_args",
      requirementsKey: "image_runtime_requirements_text",
      installKey: "image_runtime_install_text",
      templateMap: IMAGE_PRESET_TEMPLATE_JSON,
      assetMap: IMAGE_PRESET_ASSET_JSON,
      paramMap: IMAGE_PRESET_PARAM_JSON,
      requirementsMap: IMAGE_PRESET_REQUIREMENTS_TEXT,
      installMap: IMAGE_PRESET_INSTALL_TEXT,
    };
    const videoRuntimeConfig = {
      typeId: "video_gen",
      modeKey: "video_command_mode",
      presetKey: "video_template_preset",
      templateKey: "video_runtime_template_json",
      assetsKey: "video_runtime_assets_json",
      paramsKey: "video_runtime_params_json",
      extraArgsKey: "video_runtime_extra_args",
      requirementsKey: "video_runtime_requirements_text",
      installKey: "video_runtime_install_text",
      templateMap: VIDEO_PRESET_TEMPLATE_JSON,
      assetMap: VIDEO_PRESET_ASSET_JSON,
      paramMap: VIDEO_PRESET_PARAM_JSON,
      requirementsMap: VIDEO_PRESET_REQUIREMENTS_TEXT,
      installMap: VIDEO_PRESET_INSTALL_TEXT,
    };

    if (entriesByKey["backend"]?.input) {
      entriesByKey["backend"].input.addEventListener("change", () => {
        updateSearchButtonLabel();
      });
    }
    if (typeId === "speech_tts" && entriesByKey["speech_command_mode"]?.input) {
      entriesByKey["speech_command_mode"].input.addEventListener("change", () => {
        syncSpeechTtsModeVisibility();
      });
      syncSpeechTtsModeVisibility();
    }
    if (typeId === "speech_asr" && entriesByKey["speech_command_mode"]?.input) {
      entriesByKey["speech_command_mode"].input.addEventListener("change", () => {
        syncSpeechAsrModeVisibility();
      });
      syncSpeechAsrModeVisibility();
    }
    if (typeId === "speech_tts" && entriesByKey["speech_template_preset"]?.input) {
      entriesByKey["speech_template_preset"].input.addEventListener("change", () => {
        syncSpeechTtsPresetTemplate();
      });
      syncSpeechTtsPresetTemplate();
    }
    if (typeId === "speech_asr" && entriesByKey["speech_template_preset"]?.input) {
      entriesByKey["speech_template_preset"].input.addEventListener("change", () => {
        syncSpeechAsrPresetTemplate();
      });
      syncSpeechAsrPresetTemplate();
    }
    if (typeId === "image_gen" && entriesByKey["image_command_mode"]?.input) {
      entriesByKey["image_command_mode"].input.addEventListener("change", () => {
        syncCustomRuntimeModeVisibility(imageRuntimeConfig);
      });
      syncCustomRuntimeModeVisibility(imageRuntimeConfig);
    }
    if (typeId === "video_gen" && entriesByKey["video_command_mode"]?.input) {
      entriesByKey["video_command_mode"].input.addEventListener("change", () => {
        syncCustomRuntimeModeVisibility(videoRuntimeConfig);
      });
      syncCustomRuntimeModeVisibility(videoRuntimeConfig);
    }
    if ((typeId === "image_gen" || typeId === "video_gen") && entriesByKey["model_backend"]?.input) {
      entriesByKey["model_backend"].input.addEventListener("change", () => {
        syncModelBackendCompatibilityFields();
        if (typeId === "image_gen") syncCustomRuntimeModeVisibility(imageRuntimeConfig);
        if (typeId === "video_gen") syncCustomRuntimeModeVisibility(videoRuntimeConfig);
        syncWorkflowModelLoaderVisibility();
        syncVideoWanVisibility();
      });
      syncModelBackendCompatibilityFields();
      syncWorkflowModelLoaderVisibility();
    }
    if ((typeId === "image_gen" || typeId === "video_gen") && entriesByKey["workflow_loader_mode"]?.input) {
      entriesByKey["workflow_loader_mode"].input.addEventListener("change", () => {
        if (typeId === "image_gen") syncCustomRuntimeModeVisibility(imageRuntimeConfig);
        if (typeId === "video_gen") syncCustomRuntimeModeVisibility(videoRuntimeConfig);
        syncWorkflowModelLoaderVisibility();
      });
      syncWorkflowModelLoaderVisibility();
    }
    if ((typeId === "image_gen" || typeId === "video_gen") && entriesByKey["workflow_execution_backend"]?.input) {
      entriesByKey["workflow_execution_backend"].input.addEventListener("change", () => {
        syncWorkflowModelLoaderVisibility();
      });
      syncWorkflowModelLoaderVisibility();
    }
    if (typeId === "image_gen" && entriesByKey["image_template_preset"]?.input) {
      entriesByKey["image_template_preset"].input.addEventListener("change", () => {
        syncCustomRuntimePreset(imageRuntimeConfig);
      });
      syncCustomRuntimePreset(imageRuntimeConfig);
    }
    if (typeId === "video_gen" && entriesByKey["video_template_preset"]?.input) {
      entriesByKey["video_template_preset"].input.addEventListener("change", () => {
        syncCustomRuntimePreset(videoRuntimeConfig);
      });
      syncCustomRuntimePreset(videoRuntimeConfig);
    }
    if (typeId === "video_gen") {
      for (const key of ["model_id", "use_wan", "gguf_path"]) {
        const entry = entriesByKey[key];
        if (entry?.input && typeof entry.input.addEventListener === "function") {
          entry.input.addEventListener("input", syncVideoWanVisibility);
          entry.input.addEventListener("change", syncVideoWanVisibility);
        }
      }
      syncVideoWanVisibility();
    }
    attachSpeechTtsCompanionSearchButton();
    updateSearchButtonLabel();
    await mountCompatibilityPanel();
    await applySharedFieldEnhancers();

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

    function applyMainGpuChoices(choices, titleText) {
      if (!Array.isArray(choices) || !choices.length) return false;
      installMainGpuPickerFromChoices(choices);
      if (mainGpuEntry?.input instanceof HTMLElement) {
        mainGpuEntry.input.title = titleText || "Select the GPU by device name (stored as device id).";
      }
      renderGpuSplitRows();
      syncGpuFieldVisibility();
      return true;
    }

    async function syncEmbeddedMainGpuChoices() {
      if (!mainGpuEntry) return;
      const embeddedDeviceKind = String(entriesByKey.device?.input?.value || model?.settings?.device || "").trim().toLowerCase();
      let runtimeHint = "";
      try {
        const payload = await apiJson(ctx, "/v1/model_deck_loader/schema");
        runtimeHint = String(payload?.runtime || "").trim().toLowerCase();
        const schemas = payload?.schemas || {};
        if (schemas && typeof schemas === "object") {
          state.schemas = schemas;
        }
        const freshSchema = schemas?.[typeId] || {};
        const schemaChoices = getSchemaMainGpuChoices(freshSchema);
        if (hasNamedGpuChoices(schemaChoices)) {
          applyMainGpuChoices(schemaChoices, "Select the embedded runtime GPU device id reported by the active backend.");
          return;
        }
      } catch (_err) {
      }
      const hostChoices = await getHostGpuChoices(ctx, { forceFresh: true });
      const fallbackDeviceKind = embeddedDeviceKind && embeddedDeviceKind !== "auto"
        ? embeddedDeviceKind
        : (["intel", "xpu", "sycl"].includes(runtimeHint) ? "xpu" : (runtimeHint === "cuda" ? "cuda" : runtimeHint));
      const embeddedChoices = normalizeEmbeddedFallbackChoices(hostChoices, fallbackDeviceKind);
      if (hasNamedGpuChoices(embeddedChoices)) {
        applyMainGpuChoices(embeddedChoices, "Select the embedded runtime GPU device id mapped from host adapter names.");
        return;
      }
      if (hasNamedGpuChoices(hostChoices)) {
        applyMainGpuChoices(hostChoices, "Select the embedded GGUF GPU by live device name (stored as device id).");
        return;
      }
      await refreshSchemaGpuChoicesLazily();
    }

    async function syncMainGpuChoicesForCurrentBackend(options = {}) {
      const forceFresh = Boolean(options && options.forceFresh);
      const backendMode = String(backendModeEntry?.input?.value || model?.settings?.backend_mode || "").trim().toLowerCase();
      if (backendMode === "llama_server") {
        await ensureManagedServerData({ syncGpu: true, forceFresh });
        return;
      }
      await syncEmbeddedMainGpuChoices();
    }

    async function syncManagedMainGpuChoices() {
      if (!mainGpuEntry || !mainGpuEntry.input) return;
      const backendMode = String(backendModeEntry?.input?.value || "").trim().toLowerCase();
      if (backendMode !== "llama_server" || !selectedManagedServerId) return;
      const choices = await getManagedLlamaDeviceChoices(ctx, managedServers, selectedManagedServerId, { forceFresh: true });
      applyMainGpuChoices(choices, "Select the llama.cpp server GPU device id reported by --list-devices.");
    }

    async function ensureManagedServerData({ syncGpu = false, forceFresh = false } = {}) {
      if (!supportsManagedLlamaServer) return;
      const freshEnough = managedServersLoaded && (Date.now() - managedServersLoadedAt) < CACHE_TTL_MANAGED_SERVERS_MS;
      if (!forceFresh && freshEnough) {
        if (syncGpu) await syncManagedMainGpuChoices();
        return;
      }
      if (managedServersLoadPromise) {
        await managedServersLoadPromise;
        if (syncGpu) await syncManagedMainGpuChoices();
        return;
      }
      if (managedServerHint) {
        managedServerHint.textContent = "Loading managed servers...";
      }
      managedServersLoading = true;
      managedServersLoadPromise = (async () => {
        try {
          const resolved = await getManagedLlamaServers(ctx, state.processes || {}, { forceFresh });
          managedServers.splice(0, managedServers.length, ...(Array.isArray(resolved) ? resolved : []));
          managedServersLoaded = true;
          managedServersLoadedAt = Date.now();
          populateManagedServerPicker();
          if (syncGpu) {
            await syncManagedMainGpuChoices();
          }
        } catch (_err) {
          if (managedServerHint) {
            managedServerHint.textContent = "Managed server lookup failed. You can still enter a URL manually above.";
          }
        } finally {
          managedServersLoading = false;
          managedServersLoadPromise = null;
        }
      })();
      await managedServersLoadPromise;
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

    function getSchemaMainGpuChoices(schemaObj) {
      const fieldsLocal = Array.isArray(schemaObj?.fields) ? schemaObj.fields : [];
      for (const field of fieldsLocal) {
        if (!field || typeof field !== "object") continue;
        if (String(field.key || "").trim() !== "main_gpu") continue;
        if (!Array.isArray(field.choices)) return [];
        return field.choices
          .map((choice) => {
            if (choice && typeof choice === "object") {
              const value = String(choice.value ?? "").trim();
              const label = String(choice.label ?? choice.value ?? "").trim();
              return value ? { value, label: label || value } : null;
            }
            const value = String(choice ?? "").trim();
            return value ? { value, label: value } : null;
          })
          .filter(Boolean);
      }
      return [];
    }

    async function refreshSchemaGpuChoicesLazily() {
      if (!mainGpuEntry) return;
      try {
        const payload = await apiJson(ctx, "/v1/model_deck_loader/schema");
        const schemas = payload?.schemas || {};
        if (schemas && typeof schemas === "object") {
          state.schemas = schemas;
        }
        const freshSchema = schemas?.[typeId] || {};
        const schemaChoices = getSchemaMainGpuChoices(freshSchema);
        if (hasNamedGpuChoices(schemaChoices) && applyMainGpuChoices(schemaChoices)) {
          return;
        }
        const hostChoices = await getHostGpuChoices(ctx, { forceFresh: true });
        if (hasNamedGpuChoices(hostChoices) && applyMainGpuChoices(hostChoices)) {
          return;
        }
        if (!schemaChoices.length) return;
        applyMainGpuChoices(schemaChoices);
      } catch (_err) {
      }
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
      const backendMode = String(backendModeEntry?.input?.value || "").trim().toLowerCase();
      const selectionMode = String(gpuSelectionModeEntry?.input?.value || "auto").trim().toLowerCase();
      const splitMode = String(gpuSplitModeEntry?.input?.value || "layer").trim().toLowerCase();
      const supportsGpuControls = !!(mainGpuFormEntry || entriesByKey.gpu_split_mode || entriesByKey.gpu_split_devices || entriesByKey.gpu_split_percent);
      if (!supportsGpuControls) return;
      const supportsBackendScopedGpuControls = backendMode === "llama_server" || backendMode === "embedded" || !backendMode;
      const activeGpuControls = backendMode ? supportsBackendScopedGpuControls : true;
      const showMainGpu = activeGpuControls && (selectionMode === "single" || selectionMode === "split");
      const showSplitMode = activeGpuControls && selectionMode === "split";
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
        if (llamaServerUrlEntry?.input?.value) {
          const matchedByUrl = findManagedServerIdByUrl(llamaServerUrlEntry.input.value);
          if (matchedByUrl) selectedManagedServerId = matchedByUrl;
        }
        void syncMainGpuChoicesForCurrentBackend({ forceFresh: true });
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

    function isForeignCustomSettingForType(key) {
      const clean = String(key || "").trim();
      const lower = clean.toLowerCase();
      if (!clean) return true;
      const videoOnlyPrefixes = [
        "wan_",
        "ltx_",
        "hunyuan_",
        "minimax_",
        "mochi_",
        "video_",
      ];
      const imageOnlyPrefixes = [
        "image_",
        "flux_",
        "sdxl_",
        "zimage_",
      ];
      const speechOnlyPrefixes = [
        "speech_",
        "asr_",
        "tts_",
        "wesep_",
        "wespeaker_",
      ];
      const workflowKeys = new Set([
        "model_workflow_backend",
        "workflow_loader_mode",
        "workflow_node_lifecycle_policy",
        "workflow_execution_backend",
        "workflow_node_timeout_seconds",
        "workflow_model_loader_id",
        "workflow_model_id",
        "model_deck_compat_manifest_id",
      ]);
      const videoOnlyKeys = new Set([
        "fps",
        "frames",
        "video_codec",
        "use_wan",
        "use_wan_vae",
        "wan_vae_subfolder",
        "wan_vae_dtype",
        "ltx_video_only",
        "native_transformer_offload",
        "gemma_text_encoding_device",
        "gemma_max_prompt_tokens",
        "allow_legacy_eager_gemma_gpu_load",
      ]);
      if (typeId === "text_llm" || typeId === "vlm") {
        if (workflowKeys.has(lower) || videoOnlyKeys.has(lower)) return true;
        if (videoOnlyPrefixes.some((prefix) => lower.startsWith(prefix))) return true;
        if (imageOnlyPrefixes.some((prefix) => lower.startsWith(prefix))) return true;
        if (speechOnlyPrefixes.some((prefix) => lower.startsWith(prefix))) return true;
        return false;
      }
      if (typeId === "image_gen") {
        if (videoOnlyKeys.has(lower)) return true;
        if (videoOnlyPrefixes.some((prefix) => lower.startsWith(prefix))) return true;
        if (speechOnlyPrefixes.some((prefix) => lower.startsWith(prefix))) return true;
        return false;
      }
      if (typeId === "video_gen") {
        if (imageOnlyPrefixes.some((prefix) => lower.startsWith(prefix))) return true;
        if (speechOnlyPrefixes.some((prefix) => lower.startsWith(prefix))) return true;
        return false;
      }
      return false;
    }

    const knownKeys = new Set(entries.map((e) => e.key));
    if (model?.settings && typeof model.settings === "object") {
      const extra = {};
      for (const [k, v] of Object.entries(model.settings)) {
        if (isForeignCustomSettingForType(k)) continue;
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
      if (currentUrl) {
        const matchedByUrl = findManagedServerIdByUrl(currentUrl);
        if (matchedByUrl) selectedManagedServerId = matchedByUrl;
      }
      managedServerPicker.innerHTML = "";
      const blank = document.createElement("option");
      blank.value = "";
      blank.textContent = managedServers.length
        ? "Choose managed server..."
        : (managedServersLoaded ? "No managed servers found" : "Load managed servers...");
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
          : (managedServersLoaded
            ? "No managed servers are cached yet. You can still enter a URL manually above."
            : "Managed servers will load when llama-server mode is active.");
      }
    }

    populateManagedServerPicker();
    if (managedServerPicker) {
      managedServerPicker.addEventListener("focus", () => {
        void ensureManagedServerData({ syncGpu: true, forceFresh: true });
      });
      managedServerPicker.addEventListener("pointerdown", () => {
        void ensureManagedServerData({ syncGpu: true, forceFresh: true });
      });
    }
    if (llamaServerUrlEntry?.input instanceof HTMLElement) {
      llamaServerUrlEntry.input.addEventListener("focus", () => {
        const backendMode = String(backendModeEntry?.input?.value || "").trim().toLowerCase();
        if (backendMode === "llama_server") {
          void ensureManagedServerData({ syncGpu: true, forceFresh: true });
        }
      });
    }
    if (!(supportsManagedLlamaServer)) {
      void (async () => {
        await loadWorkflowTrainingArtifacts();
        addWorkflowTrainingPickers();
        syncLoraFieldVisibility();
      })();
    } else {
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
    if (mainGpuEntry?.input instanceof HTMLElement) {
      const refreshLiveGpuChoices = () => {
        void syncMainGpuChoicesForCurrentBackend({ forceFresh: true });
      };
      mainGpuEntry.input.addEventListener("focus", refreshLiveGpuChoices);
      mainGpuEntry.input.addEventListener("pointerdown", refreshLiveGpuChoices);
    }
    if (supportsManagedLlamaServer) {
      const initialBackendMode = String(backendModeEntry?.input?.value || model?.settings?.backend_mode || "").trim().toLowerCase();
      if (initialBackendMode === "llama_server") {
        void ensureManagedServerData({ syncGpu: true, forceFresh: true });
      } else if (mainGpuEntry) {
        setTimeout(() => {
          void syncEmbeddedMainGpuChoices();
        }, 0);
      }
    } else if (mainGpuEntry) {
      setTimeout(() => {
        void syncEmbeddedMainGpuChoices();
      }, 0);
    }
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
      syncCompatAssetJsonFromDynamicFields();
      const settings = {};
      for (const entry of entries) {
        if (typeId === "image_gen" && entry.wrap && entry.wrap.style.display === "none") continue;
        const val = readFieldValue(entry.type, entry.input);
        if (val !== undefined) settings[entry.key] = val;
      }
      if ((typeId === "image_gen" || typeId === "video_gen") && compatDynamicAssetEntries.length) {
        const assetEntry = getCompatAssetJsonEntry();
        const paramEntry = getCompatParamJsonEntry();
        if (assetEntry?.input && "value" in assetEntry.input) {
          const assetText = String(assetEntry.input.value || "").trim();
          if (assetText) settings[getCompatRuntimeConfig()?.assetsKey] = assetText;
        }
        if (paramEntry?.input && "value" in paramEntry.input) {
          const paramText = String(paramEntry.input.value || "").trim();
          if (paramText) settings[getCompatRuntimeConfig()?.paramsKey] = paramText;
        }
        for (const row of compatDynamicAssetEntries) {
          if (!row?.key) continue;
          const val = readFieldValue(row.type, row.input);
          if (val !== undefined) settings[row.key] = val;
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
      if (supportsManagedLlamaServer) {
        const backendMode = String(settings.backend_mode || "").trim().toLowerCase();
        if (backendMode === "llama_server" && typeof settings.llama_server_url === "string") {
          settings.llama_server_url = _rewriteClientUrl(settings.llama_server_url);
        }
        const matchedManagedServerId = backendMode === "llama_server"
          ? findManagedServerIdByUrl(settings.llama_server_url)
          : "";
        if (backendMode === "llama_server" && matchedManagedServerId) {
          settings.llama_server_managed_id = matchedManagedServerId;
        } else {
          delete settings.llama_server_managed_id;
        }
      }
      if ((typeId === "image_gen" || typeId === "video_gen") && selectedCompatManifestId) {
        settings.model_deck_compat_manifest_id = selectedCompatManifestId;
      } else {
        delete settings.model_deck_compat_manifest_id;
      }
      if (lastDownloadedHfRepoId) settings.hf_source_repo_id = lastDownloadedHfRepoId;
      else delete settings.hf_source_repo_id;
      if (lastDownloadedHfFilename) settings.hf_source_filename = lastDownloadedHfFilename;
      else delete settings.hf_source_filename;
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
    } else if (type === "textarea") {
      input = document.createElement("textarea");
      input.rows = Math.max(3, parseInt(String(field?.rows || 6), 10) || 6);
      if (value !== undefined && value !== null && value !== "") input.value = String(value);
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

  function stableJsonString(value) {
    try {
      return JSON.stringify(value || {}, null, 2);
    } catch (_err) {
      return "";
    }
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
  renderOverview();
  renderModels();
  renderProcesses();
  const cachedBootstrap = cacheGet(ctx, CACHE_KEY_EDITOR_BOOTSTRAP);
  if (cachedBootstrap && typeof cachedBootstrap === "object") {
    applyEditorBootstrap(cachedBootstrap);
    statusLabel.textContent = "Cached";
  } else {
    const cachedDeck = cacheGet(ctx, CACHE_KEY_DECK);
    if (cachedDeck && typeof cachedDeck === "object") {
      applyDeckOnlyCache(cachedDeck);
      statusLabel.textContent = "Cached deck";
    }
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
