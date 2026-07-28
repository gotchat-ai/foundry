const meta = {
  plugin_id: "theme_demo",
  name: "Theme Demo",
  kind: "ui",
  description: "Switch between system/light/dark themes with accent colors.",
  has_notebook_tab: false,
};

const STYLE_ID = "theme-demo-style";
const THEME_VARS = [
  "--bg-image",
  "--bg-0",
  "--bg-1",
  "--bg-2",
  "--ink",
  "--muted",
  "--accent",
  "--accent-ink",
  "--panel",
  "--border",
  "--shadow",
];

const UI_THEME_VARS = [
  "--ui-ink",
  "--ui-muted",
  "--ui-control-bg",
  "--ui-control-bg-strong",
  "--ui-popover-item-bg",
  "--ui-popover-item-bg-hover",
  "--transcript-ink",
  "--transcript-meta",
];

const DARK_THEME = {
  "--bg-0": "#1c1c1c",
  "--bg-1": "#1c1c1c",
  "--bg-2": "#1a1815",
  "--ink": "#f2e8d8",
  "--muted": "#d7cab9",
  "--panel": "#1f1d1a",
  "--border": "#3a332d",
  "--shadow": "0 30px 60px rgba(0, 0, 0, 0.5)",
};

const DARK_UI_THEME = {
  "--ui-ink": "#ffffff",
  "--ui-muted": "rgba(255, 255, 255, 0.86)",
  "--ui-control-bg": "rgba(52, 48, 43, 0.94)",
  "--ui-control-bg-strong": "rgba(42, 39, 35, 0.98)",
  "--ui-popover-item-bg": "rgba(58, 53, 48, 0.98)",
  "--ui-popover-item-bg-hover": "rgba(71, 65, 59, 1)",
  "--transcript-ink": "#ffffff",
  "--transcript-meta": "rgba(255, 255, 255, 0.82)",
};

const DEFAULT_LIGHT_BG_IMAGE = new URL("./assets/default-light-bg.png", import.meta.url).toString();

const defaultsByTarget = new WeakMap();
let activePanel = null;
let topbarVisibilityEnsured = false;

function ensureStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
//   style.textContent = `
// .theme-demo { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12px; }
// .theme-demo label { font-size: 12px; color: var(--muted); }
// .theme-demo select,
// .theme-demo input[type="color"] {
//   border-radius: 10px;
//   border: 1px solid var(--border);
//   padding: 4px 6px;
//   font-family: inherit;
//   background: rgba(255, 255, 255, 0.8);
// }
//   `;

style.textContent = `
.theme-demo { display: inline-flex; align-items: center; font-size: 12px; position: relative; }

.theme-demo-btn{
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--ui-control-bg);
  color: var(--ui-ink);
  user-select: none;
}

.theme-demo-panel{
  position: fixed;
  z-index: 2000;
  min-width: 260px;
  max-width: min(360px, calc(100vw - 16px));
  max-height: calc(100vh - 16px);
  overflow: auto;
  overscroll-behavior: contain;
  box-sizing: border-box;
  padding: 10px;
  border-radius: 12px;
  border: 1px solid var(--border);
  background: var(--ui-control-bg-strong);
  color: var(--ui-ink);
  box-shadow: var(--shadow);
  backdrop-filter: blur(10px);
}

.theme-demo-panel.hidden {
  display: none;
}

.theme-demo-row{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
  padding: 6px 0;
  font-size: 12px;
  color: var(--ui-muted);
}

.theme-demo-row span { color: var(--ui-muted); }
.theme-demo-row select,
.theme-demo-row input[type="color"]{
  border-radius: 10px;
  border: 1px solid var(--border);
  padding: 4px 6px;
  font-family: inherit;
  background: var(--ui-control-bg);
  color: var(--ui-ink);
}
.theme-demo-row select{
  min-width: 0;
  max-width: 100%;
}
.theme-demo-row.disabled { opacity: 0.55; }
.theme-demo-row-stack{
  align-items:flex-start;
  flex-direction:column;
}
.theme-demo-upload{
  display:flex;
  align-items:center;
  gap:8px;
  width:100%;
}
.theme-demo-upload input[type="file"]{
  flex:1 1 auto;
  min-width:0;
  font-size:11px;
}
.theme-demo-upload button{
  border-radius: 10px;
  border: 1px solid var(--border);
  padding: 4px 8px;
  font-family: inherit;
  background: var(--ui-control-bg);
  color: var(--ui-ink);
}
.theme-demo-image-preview{
  display:flex;
  align-items:center;
  justify-content:flex-start;
  margin: 4px 0 8px;
  padding: 8px;
  min-height: 52px;
  border: 1px dashed var(--border);
  border-radius: 12px;
  background: var(--ui-control-bg);
}
.theme-demo-image-preview.hidden{
  display:none;
}
.theme-demo-image-preview img{
  display:block;
  max-width:100%;
  max-height:84px;
  object-fit:contain;
}
@media (max-width: 520px){
  .theme-demo-panel{
    min-width: 0;
    width: calc(100vw - 16px);
    max-width: calc(100vw - 16px);
    max-height: calc(100vh - 16px);
  }
  .theme-demo-row{
    align-items:center;
    flex-direction:row;
    justify-content:space-between;
    gap:8px;
  }
  .theme-demo-row select{
    width:auto;
    max-width:50%;
  }
  .theme-demo-row input[type="color"]{
    flex:0 0 auto;
  }
  .theme-demo-row > span{
    flex:1 1 auto;
    min-width:0;
  }
  .theme-demo-row-stack{
    align-items:flex-start;
    flex-direction:column;
  }
  .theme-demo-upload{
    flex-direction:column;
    align-items:stretch;
  }
}
`;
  document.head.appendChild(style);
}

function hexToRgbTriplet(hex) {
  if (!hex) return "";
  const h = hex.replace("#", "").trim();
  if (h.length !== 6) return "";
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  if ([r, g, b].some((x) => Number.isNaN(x))) return "";
  return `${r}, ${g}, ${b}`;
}

function rgbaFromHex(hex, alpha, fallback) {
  const rgb = hexToRgbTriplet(hex);
  if (!rgb) return fallback || "";
  return `rgba(${rgb}, ${alpha})`;
}

function adjustHex(hex, amount, fallback) {
  const h = String(hex || "").replace("#", "").trim();
  if (h.length !== 6) return fallback || hex || "";
  const clamp = (value) => Math.max(0, Math.min(255, value));
  const parts = [0, 2, 4].map((index) => parseInt(h.slice(index, index + 2), 16));
  if (parts.some((value) => Number.isNaN(value))) return fallback || hex || "";
  return `#${parts
    .map((value) => clamp(value + amount).toString(16).padStart(2, "0"))
    .join("")}`;
}

function cssUrlValue(url) {
  const value = String(url || "").trim();
  if (!value) return "none";
  const escaped = value.replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\r?\n/g, "");
  return `url("${escaped}")`;
}

function getThemeBaseTarget(ctx) {
  try {
    if (ctx && typeof ctx.getEmbedMount === "function") {
      const mount = ctx.getEmbedMount();
      if (mount instanceof Element && mount !== document.body && mount !== document.documentElement) return mount;
    }
  } catch (_err) {}
  try {
    if (ctx && typeof ctx.getOverlayMount === "function") {
      const mount = ctx.getOverlayMount();
      if (mount instanceof Element && mount !== document.body && mount !== document.documentElement) return mount;
    }
  } catch (_err) {}
  return document.documentElement;
}

function captureDefaults(ctx) {
  const target = getThemeBaseTarget(ctx);
  if (defaultsByTarget.has(target)) return defaultsByTarget.get(target);
  let defaults = null;
  try {
    if (ctx && typeof ctx.getUiThemeDefaults === "function") {
      const raw = ctx.getUiThemeDefaults(target);
      if (raw && typeof raw === "object") {
        defaults = {};
        for (const key of THEME_VARS.concat(UI_THEME_VARS)) {
          defaults[key] = String(raw[key] || "").trim();
        }
      }
    }
  } catch (_err) {}
  if (!defaults) {
    const styles = getComputedStyle(target);
    defaults = {};
    for (const key of THEME_VARS.concat(UI_THEME_VARS)) {
      defaults[key] = styles.getPropertyValue(key).trim();
    }
  }
  defaultsByTarget.set(target, defaults);
  return defaults;
}

function buildThemeSnapshot(ctx, mode, accent, accentText, darkText, darkBodyColor, panelColor, bodyImage, chatBgAlpha) {
  const base = captureDefaults(ctx);
  const finalAccent = accent || base["--accent"];
  const finalAccentText = accentText || base["--accent-ink"];
  const finalThemeText = darkText || (mode === "dark" ? DARK_UI_THEME["--ui-ink"] : base["--ui-ink"]);
  const finalBodyColor = darkBodyColor || (mode === "dark" ? DARK_THEME["--bg-0"] : base["--bg-0"]);
  const finalPanelColor = panelColor || (mode === "dark" ? DARK_THEME["--panel"] : base["--panel"]);
  const requestedBodyImage = String(bodyImage || "").trim();
  const finalBodyImage = requestedBodyImage || (mode === "dark" ? "" : DEFAULT_LIGHT_BG_IMAGE);
  const vars = {};
  if (mode === "dark") {
    for (const key of THEME_VARS) {
      vars[key] = DARK_THEME[key] || base[key];
    }
    for (const key of UI_THEME_VARS) {
      vars[key] = DARK_UI_THEME[key] || base[key];
    }
    if (finalThemeText) {
      vars["--ui-ink"] = finalThemeText;
      vars["--ui-muted"] = rgbaFromHex(finalThemeText, 0.86, DARK_UI_THEME["--ui-muted"] || base["--ui-muted"]);
      vars["--transcript-ink"] = finalThemeText;
      vars["--transcript-meta"] = rgbaFromHex(
        finalThemeText,
        0.82,
        DARK_UI_THEME["--transcript-meta"] || base["--transcript-meta"]
      );
    }
    vars["--bg-0"] = finalBodyColor;
    vars["--bg-1"] = adjustHex(finalBodyColor, -6, finalBodyColor);
    vars["--bg-grad-a"] = adjustHex(finalBodyColor, 8, finalBodyColor);
    vars["--bg-grad-b"] = adjustHex(finalBodyColor, 2, finalBodyColor);
    vars["--panel"] = finalPanelColor;
    vars["--panel-rgb"] = hexToRgbTriplet(finalPanelColor) || "31, 29, 26";
  } else {
    for (const key of THEME_VARS) {
      vars[key] = base[key];
    }
    for (const key of UI_THEME_VARS) {
      vars[key] = base[key];
    }
    if (finalThemeText) {
      vars["--ui-ink"] = finalThemeText;
      vars["--ui-muted"] = rgbaFromHex(finalThemeText, 0.86, base["--ui-muted"]);
      vars["--transcript-ink"] = finalThemeText;
      vars["--transcript-meta"] = rgbaFromHex(finalThemeText, 0.82, base["--transcript-meta"]);
    }
    vars["--bg-0"] = finalBodyColor;
    vars["--bg-1"] = adjustHex(finalBodyColor, -6, finalBodyColor);
    vars["--bg-grad-a"] = adjustHex(finalBodyColor, 8, "#fff9ee");
    vars["--bg-grad-b"] = adjustHex(finalBodyColor, 2, "#f7e3cc");
    vars["--panel"] = finalPanelColor;
    vars["--panel-rgb"] = hexToRgbTriplet(finalPanelColor) || "248, 249, 251";
  }
  vars["--bg-image"] = cssUrlValue(finalBodyImage);
  vars["--chat-bg-alpha"] = normalizeAlpha(chatBgAlpha, "0.1");

  if (finalAccent) {
    vars["--accent"] = finalAccent;
    const accentRgb = hexToRgbTriplet(finalAccent);
    if (accentRgb) vars["--accent-rgb"] = accentRgb;
  }
  if (finalAccentText) {
    vars["--accent-ink"] = finalAccentText;
  }
  return {
    pluginId: meta.plugin_id,
    vars,
  };
}

function normalizeAlpha(value, fallback = "0.1") {
  const num = Number.parseFloat(String(value ?? "").trim());
  if (!Number.isFinite(num)) return fallback;
  return String(Math.max(0, Math.min(1, num)));
}

function createModeSettings(base = {}) {
  return {
    accent: String(base.accent || "").trim(),
    accentText: String(base.accentText || "").trim(),
    themeText: String(base.themeText || "").trim(),
    bodyColor: String(base.bodyColor || "").trim(),
    panelColor: String(base.panelColor || "").trim(),
    bodyImage: String(base.bodyImage || "").trim(),
    chatBgAlpha: normalizeAlpha(base.chatBgAlpha, "0.1"),
  };
}

function exportThemeState(state) {
  return {
    mode: String(state?.mode || "system").trim() || "system",
    light: createModeSettings(state?.light),
    dark: createModeSettings(state?.dark),
  };
}

function getThemeState(ctx) {
  if (!ctx.state.ui) ctx.state.ui = {};
  const shared = (ctx && typeof ctx.getSharedUiThemeDefault === "function")
    ? ctx.getSharedUiThemeDefault()
    : null;
  const sharedState = shared?.themeState && typeof shared.themeState === "object"
    ? exportThemeState(shared.themeState)
    : null;
  const prev = ctx.state.ui.themeDemo;
  if (!prev || typeof prev !== "object") {
    ctx.state.ui.themeDemo = sharedState || {
      mode: "system",
      light: createModeSettings(),
      dark: createModeSettings(),
    };
    return ctx.state.ui.themeDemo;
  }
  if (!ctx.state.ui.useLocalThemeOverride && sharedState) {
    ctx.state.ui.themeDemo = sharedState;
    return ctx.state.ui.themeDemo;
  }
  if (!prev.light || !prev.dark) {
    ctx.state.ui.themeDemo = {
      mode: String(prev.mode || "system").trim() || "system",
      light: createModeSettings({
        accent: prev.accent,
        accentText: prev.accentText,
        themeText: "",
        bodyColor: "",
        panelColor: "",
        bodyImage: "",
      }),
      dark: createModeSettings({
        accent: prev.accent,
        accentText: prev.accentText,
        themeText: prev.darkText,
        bodyColor: prev.darkBodyColor,
        panelColor: "",
        bodyImage: "",
      }),
    };
    return ctx.state.ui.themeDemo;
  }
  ctx.state.ui.themeDemo = {
    mode: String(prev.mode || "system").trim() || "system",
    light: createModeSettings(prev.light),
    dark: createModeSettings(prev.dark),
  };
  return ctx.state.ui.themeDemo;
}

function getModeSettings(state, mode) {
  const key = mode === "dark" ? "dark" : "light";
  state[key] = createModeSettings(state[key]);
  return state[key];
}

function getThemeMount(ctx) {
  try {
    if (typeof window !== "undefined" && typeof window.__LLM_CHAT_JS_MOVE_TO_PORTAL === "function") {
      const portal = window.__LLM_CHAT_JS_PORTAL;
      if (portal instanceof Element) return portal;
    }
  } catch (_err) {}
  try {
    if (ctx && typeof ctx.getOverlayMount === "function") {
      const mount = ctx.getOverlayMount();
      if (mount instanceof Element) return mount;
    }
  } catch (_err) {}
  return document.body;
}

function buildWidget(ctx) {
  ensureStyles();
  if (!topbarVisibilityEnsured && ctx?.state?.ui && !ctx.state.ui.transcriptTopbarVisible) {
    ctx.state.ui.transcriptTopbarVisible = true;
    ctx.saveState?.();
    topbarVisibilityEnsured = true;
  }
  const state = getThemeState(ctx);

  const wrap = document.createElement("div");
  wrap.className = "theme-demo";

  const button = document.createElement("button");
  button.type = "button";
  button.className = "theme-demo-btn";
  button.textContent = "Theme v";

  const panel = document.createElement("div");
  panel.className = "theme-demo-panel";
  panel.classList.add("hidden");
  panel.dataset.themeDemoPanel = "1";

  panel.innerHTML = `
    <label class="theme-demo-row">
      <span>Mode</span>
      <select data-mode>
        <option value="system">System</option>
        <option value="light">Light</option>
        <option value="dark">Dark</option>
      </select>
    </label>

    <label class="theme-demo-row">
      <span>Accent</span>
      <input data-accent type="color" />
    </label>

    <label class="theme-demo-row">
      <span>Accent Text</span>
      <input data-accent-text type="color" />
    </label>

    <label class="theme-demo-row" data-dark-text-row>
      <span>Theme Text</span>
      <input data-dark-text type="color" />
    </label>

    <label class="theme-demo-row" data-dark-body-row>
      <span>Body Color</span>
      <input data-dark-body type="color" />
    </label>

    <label class="theme-demo-row" data-panel-color-row>
      <span>Panel</span>
      <input data-panel-color type="color" />
    </label>

    <label class="theme-demo-row" data-chat-bg-alpha-row>
      <span>Chat Bg Alpha</span>
      <input data-chat-bg-alpha type="number" min="0" max="1" step="0.05" />
    </label>

    <label class="theme-demo-row theme-demo-row-stack" data-body-image-row>
      <span>Body Image</span>
      <div class="theme-demo-upload">
        <input data-body-image-file type="file" accept="image/*" />
        <button type="button" data-body-image-clear>Clear</button>
      </div>
    </label>
    <div class="theme-demo-image-preview hidden" data-body-image-preview-row>
      <img data-body-image-preview alt="Body image preview" />
    </div>
  `;

  const select = panel.querySelector("[data-mode]");
  const accentInput = panel.querySelector("[data-accent]");
  const accentTextInput = panel.querySelector("[data-accent-text]");
  const darkTextInput = panel.querySelector("[data-dark-text]");
  const darkBodyInput = panel.querySelector("[data-dark-body]");
  const panelColorInput = panel.querySelector("[data-panel-color]");
  const chatBgAlphaInput = panel.querySelector("[data-chat-bg-alpha]");
  const darkTextRow = panel.querySelector("[data-dark-text-row]");
  const darkBodyRow = panel.querySelector("[data-dark-body-row]");
  const panelColorRow = panel.querySelector("[data-panel-color-row]");
  const chatBgAlphaRow = panel.querySelector("[data-chat-bg-alpha-row]");
  const bodyImageRow = panel.querySelector("[data-body-image-row]");
  const bodyImageFile = panel.querySelector("[data-body-image-file]");
  const bodyImageClear = panel.querySelector("[data-body-image-clear]");
  const bodyImagePreviewRow = panel.querySelector("[data-body-image-preview-row]");
  const bodyImagePreview = panel.querySelector("[data-body-image-preview]");
  const defaults = captureDefaults(ctx);

  function syncBodyImagePreview(value) {
    const src = String(value || "").trim();
    const hasImage = Boolean(src);
    if (bodyImagePreview) bodyImagePreview.src = hasImage ? src : "";
    if (bodyImagePreviewRow) bodyImagePreviewRow.classList.toggle("hidden", !hasImage);
  }

  function syncInputsFromMode() {
    const activeMode = (state.mode || "system") === "dark" ? "dark" : "light";
    const modeSettings = getModeSettings(state, activeMode);
    select.value = state.mode || "system";
    accentInput.value = modeSettings.accent || defaults["--accent"] || "#0f766e";
    accentTextInput.value = modeSettings.accentText || defaults["--accent-ink"] || "#f0fffb";
    darkTextInput.value = modeSettings.themeText
      || (activeMode === "dark" ? DARK_UI_THEME["--ui-ink"] : defaults["--ui-ink"] || "#1b1916");
    darkBodyInput.value = modeSettings.bodyColor
      || (activeMode === "dark" ? DARK_THEME["--bg-0"] : defaults["--bg-0"] || "#f4efe6");
    panelColorInput.value = modeSettings.panelColor
      || (activeMode === "dark" ? DARK_THEME["--panel"] : defaults["--panel"] || "#f8f9fb");
    chatBgAlphaInput.value = normalizeAlpha(modeSettings.chatBgAlpha, "0.1");
    if (bodyImageFile) bodyImageFile.value = "";
    syncBodyImagePreview(modeSettings.bodyImage);
  }

  syncInputsFromMode();

  function persist() {
    ctx.saveState?.();
  }

  async function apply({ persistLocal = false, persistShared = false } = {}) {
    const activeMode = (state.mode || "system") === "dark" ? "dark" : "light";
    const modeSettings = getModeSettings(state, activeMode);
    const snapshot = buildThemeSnapshot(
      ctx,
      state.mode,
      modeSettings.accent,
      modeSettings.accentText,
      modeSettings.themeText,
      modeSettings.bodyColor,
      modeSettings.panelColor,
      modeSettings.bodyImage,
      modeSettings.chatBgAlpha
    );
    if (ctx && typeof ctx.applyUiTheme === "function") {
      ctx.applyUiTheme(snapshot, { save: false });
    }
    if (persistLocal && ctx && typeof ctx.saveUiTheme === "function") {
      ctx.saveUiTheme(snapshot);
    }
    if (persistShared && ctx && typeof ctx.saveSharedUiThemeDefault === "function") {
      try {
        await ctx.saveSharedUiThemeDefault({
          themeSnapshot: snapshot,
          themeState: exportThemeState(state),
        });
      } catch (_err) {}
    }
  }

  function syncThemeColorUi() {
    const enabled = (state.mode || "system") !== "system";
    darkTextInput.disabled = !enabled;
    darkBodyInput.disabled = !enabled;
    panelColorInput.disabled = !enabled;
    if (bodyImageFile) bodyImageFile.disabled = !enabled;
    if (chatBgAlphaInput) chatBgAlphaInput.disabled = !enabled;
    if (bodyImageClear) bodyImageClear.disabled = !enabled || !Boolean(getModeSettings(state, (state.mode || "system") === "dark" ? "dark" : "light").bodyImage);
    darkTextRow.classList.toggle("disabled", !enabled);
    darkBodyRow.classList.toggle("disabled", !enabled);
    panelColorRow.classList.toggle("disabled", !enabled);
    chatBgAlphaRow.classList.toggle("disabled", !enabled);
    bodyImageRow.classList.toggle("disabled", !enabled);
    bodyImagePreviewRow.classList.toggle("disabled", !enabled);
  }

  select.addEventListener("change", () => {
    state.mode = select.value || "system";
    syncInputsFromMode();
    syncThemeColorUi();
    void apply({ persistLocal: true, persistShared: String(ctx?.state?.auth?.role || "").toLowerCase() === "admin" });
    persist();
  });

  accentInput.addEventListener("change", () => {
    const activeMode = (state.mode || "system") === "dark" ? "dark" : "light";
    getModeSettings(state, activeMode).accent = accentInput.value || "";
    void apply({ persistLocal: true, persistShared: String(ctx?.state?.auth?.role || "").toLowerCase() === "admin" });
    persist();
  });

  accentTextInput.addEventListener("change", () => {
    const activeMode = (state.mode || "system") === "dark" ? "dark" : "light";
    getModeSettings(state, activeMode).accentText = accentTextInput.value || "";
    void apply({ persistLocal: true, persistShared: String(ctx?.state?.auth?.role || "").toLowerCase() === "admin" });
    persist();
  });

  darkTextInput.addEventListener("change", () => {
    const activeMode = (state.mode || "system") === "dark" ? "dark" : "light";
    getModeSettings(state, activeMode).themeText = darkTextInput.value || "";
    void apply({ persistLocal: true, persistShared: String(ctx?.state?.auth?.role || "").toLowerCase() === "admin" });
    persist();
  });

  darkBodyInput.addEventListener("change", () => {
    const activeMode = (state.mode || "system") === "dark" ? "dark" : "light";
    getModeSettings(state, activeMode).bodyColor = darkBodyInput.value || "";
    void apply({ persistLocal: true, persistShared: String(ctx?.state?.auth?.role || "").toLowerCase() === "admin" });
    persist();
  });

  panelColorInput.addEventListener("change", () => {
    const activeMode = (state.mode || "system") === "dark" ? "dark" : "light";
    getModeSettings(state, activeMode).panelColor = panelColorInput.value || "";
    void apply({ persistLocal: true, persistShared: String(ctx?.state?.auth?.role || "").toLowerCase() === "admin" });
    persist();
  });

  chatBgAlphaInput.addEventListener("change", () => {
    const activeMode = (state.mode || "system") === "dark" ? "dark" : "light";
    const value = normalizeAlpha(chatBgAlphaInput.value, "0.1");
    chatBgAlphaInput.value = value;
    getModeSettings(state, activeMode).chatBgAlpha = value;
    void apply({ persistLocal: true, persistShared: String(ctx?.state?.auth?.role || "").toLowerCase() === "admin" });
    persist();
  });

  bodyImageClear.addEventListener("click", () => {
    const activeMode = (state.mode || "system") === "dark" ? "dark" : "light";
    getModeSettings(state, activeMode).bodyImage = "";
    if (bodyImageFile) bodyImageFile.value = "";
    syncBodyImagePreview("");
    syncThemeColorUi();
    void apply({ persistLocal: true, persistShared: String(ctx?.state?.auth?.role || "").toLowerCase() === "admin" });
    persist();
  });

  bodyImageFile.addEventListener("change", () => {
    const file = bodyImageFile.files && bodyImageFile.files[0];
    if (!file) return;
    if (!String(file.type || "").toLowerCase().startsWith("image/")) return;
    const activeMode = (state.mode || "system") === "dark" ? "dark" : "light";
    const reader = new FileReader();
    reader.onload = () => {
      const value = String(reader.result || "").trim();
      getModeSettings(state, activeMode).bodyImage = value;
      syncBodyImagePreview(value);
      syncThemeColorUi();
      void apply({ persistLocal: true, persistShared: String(ctx?.state?.auth?.role || "").toLowerCase() === "admin" });
      persist();
    };
    reader.readAsDataURL(file);
  });

  function positionPanel() {
    const rect = button.getBoundingClientRect();
    const mount = getThemeMount(ctx);
    if (panel.parentElement !== mount) mount.appendChild(panel);
    if (typeof window !== "undefined" && typeof window.__LLM_CHAT_JS_MOVE_TO_PORTAL === "function") {
      try {
        window.__LLM_CHAT_JS_MOVE_TO_PORTAL(panel);
      } catch (_err) {}
    }
    const padding = 8;
    const maxLeft = window.innerWidth - panel.offsetWidth - padding;
    const left = Math.max(padding, Math.min(maxLeft, rect.right - panel.offsetWidth));
    const maxTop = window.innerHeight - panel.offsetHeight - padding;
    const top = Math.min(maxTop, rect.bottom + 8);
    panel.style.left = `${Math.max(padding, left)}px`;
    panel.style.top = `${Math.max(padding, top)}px`;
  }

  function setOpen(next) {
    if (next && activePanel && activePanel !== panel) {
      activePanel.classList.add("hidden");
    }
    panel.classList.toggle("hidden", !next);
    if (next) {
      activePanel = panel;
      requestAnimationFrame(positionPanel);
    } else if (activePanel === panel) {
      activePanel = null;
    }
  }

  function eventHitsThemeUi(event) {
    const path = typeof event?.composedPath === "function" ? event.composedPath() : null;
    if (Array.isArray(path) && path.length) {
      if (path.includes(wrap) || path.includes(panel)) return true;
    }
    return Boolean(
      (event?.target && wrap.contains(event.target)) ||
      (event?.target && panel.contains(event.target))
    );
  }

  button.addEventListener("click", (event) => {
    event.stopPropagation();
    setOpen(panel.classList.contains("hidden"));
  });

  panel.addEventListener("click", (event) => event.stopPropagation());

  document.addEventListener("pointerdown", (event) => {
    if (panel.classList.contains("hidden")) return;
    if (!eventHitsThemeUi(event)) setOpen(false);
  }, true);

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (!panel.classList.contains("hidden")) setOpen(false);
  });

  window.addEventListener("resize", () => {
    if (!panel.classList.contains("hidden")) positionPanel();
  });

  wrap.appendChild(button);

  syncThemeColorUi();
  void apply({ persistLocal: false, persistShared: false });
  return wrap;
}


const plugin = {
  id: meta.plugin_id,
  name: meta.name,
  kind: meta.kind,
  description: meta.description,
  meta,
  register(host) {
    host.addTranscriptTopbar((ctx) => buildWidget(ctx), "right");
  },
};

export default plugin;
