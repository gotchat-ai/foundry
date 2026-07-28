const meta = {
  plugin_id: "language",
  name: "Language",
  kind: "ui",
  description: "Framework-wide language selector and plugin translation bundle loader for chat_js.",
  has_notebook_tab: false,
};

const STYLE_ID = "language-plugin-style";
const DEFAULT_LANGUAGES = [
  { code: "en", label: "English" },
  { code: "es", label: "Español" },
  { code: "ja", label: "日本語" },
  { code: "zh", label: "中文" },
];

const SELF_STRINGS = {
  en: {
    "language.label": "Language:",
    "language.auto_detect": "Auto detect browser language",
    "language.status.ready": "Translations loaded",
    "language.status.loading": "Loading translations…",
  },
  es: {
    "language.label": "Idioma:",
    "language.auto_detect": "Detectar idioma del navegador",
    "language.status.ready": "Traducciones cargadas",
    "language.status.loading": "Cargando traducciones…",
  },
  ja: {
    "language.label": "言語:",
    "language.auto_detect": "ブラウザの言語を自動検出",
    "language.status.ready": "翻訳を読み込みました",
    "language.status.loading": "翻訳を読み込み中…",
  },
  zh: {
    "language.label": "语言：",
    "language.auto_detect": "自动检测浏览器语言",
    "language.status.ready": "翻译已加载",
    "language.status.loading": "正在加载翻译…",
  },
};

function ensureStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
.language-plugin { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12px; }
.language-plugin label { font-size: 12px; color: var(--ui-muted); }
.language-plugin select {
  border-radius: 10px;
  border: 1px solid var(--border);
  padding: 4px 6px;
  font-family: inherit;
  background: var(--ui-control-bg);
  color: var(--ui-ink);
}
.language-plugin-auto { display: inline-flex; align-items: center; gap: 4px; color: var(--ui-muted); }
.language-plugin-auto input { margin: 0; }
.language-plugin-status { color: var(--ui-muted); font-size: 11px; }
  `.trim();
  document.head.appendChild(style);
}

function normalizeLocale(locale) {
  return String(locale || "en").trim().toLowerCase().replace("_", "-") || "en";
}

function getBrowserLocale() {
  const langs = Array.isArray(navigator.languages) && navigator.languages.length
    ? navigator.languages
    : [navigator.language || navigator.userLanguage || "en"];
  return normalizeLocale(langs[0] || "en");
}

function pickSupportedBrowserLocale(host) {
  const browserLocale = getBrowserLocale();
  const base = browserLocale.split("-")[0];
  const supported = uniqueLanguages(host).map((l) => normalizeLocale(l.code));
  if (supported.includes(browserLocale)) return browserLocale;
  if (supported.includes(base)) return base;
  return "en";
}

function getLanguagePrefs(ctx) {
  const state = ctx?.state || {};
  if (!state.plugins || typeof state.plugins !== "object") state.plugins = {};
  if (!state.plugins.language || typeof state.plugins.language !== "object") state.plugins.language = {};
  return state.plugins.language;
}

function uniqueLanguages(host) {
  const seen = new Map(DEFAULT_LANGUAGES.map((l) => [l.code, { ...l }]));
  const bundles = host.getI18nBundles?.() || [];
  for (const bundle of bundles) {
    for (const code of bundle.languages || []) {
      const norm = normalizeLocale(code);
      if (!seen.has(norm)) seen.set(norm, { code: norm, label: norm });
    }
  }
  return Array.from(seen.values());
}

function bundleUrl(bundle, locale) {
  const basePath = String(bundle?.basePath || "").trim();
  if (!basePath) return "";
  const clean = basePath.endsWith("/") ? basePath : `${basePath}/`;
  return new URL(`${locale}.json`, clean).toString();
}

async function fetchBundleJson(bundle, locale) {
  const url = bundleUrl(bundle, locale);
  if (!url) return null;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);

  // Force UTF-8 decoding. Some local/static servers return .json files as
  // text/plain or with a legacy charset, which can make Japanese/Chinese/etc.
  // turn into mojibake when the browser decodes the body automatically.
  const buf = await res.arrayBuffer();
  const text = new TextDecoder("utf-8", { fatal: false }).decode(buf);
  return JSON.parse(text.replace(/^\uFEFF/, ""));
}

async function loadLanguage(host, locale, options = {}) {
  const lang = normalizeLocale(locale);
  const base = lang.split("-")[0];
  const bundles = host.getI18nBundles?.() || [];

  host.installI18nDictionary?.(lang, SELF_STRINGS[lang] || SELF_STRINGS[base] || SELF_STRINGS.en || {});

  for (const bundle of bundles) {
    if (!bundle || !bundle.basePath) continue;
    const languages = Array.isArray(bundle.languages) ? bundle.languages.map(normalizeLocale) : [];
    const fallback = normalizeLocale(bundle.defaultLanguage || "en");
    const candidates = [];
    if (languages.includes(lang)) candidates.push(lang);
    if (base !== lang && languages.includes(base)) candidates.push(base);
    if (fallback && !candidates.includes(fallback)) candidates.push(fallback);
    if (!candidates.includes("en")) candidates.push("en");

    let loaded = false;
    for (const candidate of candidates) {
      try {
        const data = await fetchBundleJson(bundle, candidate);
        if (data && typeof data === "object") {
          host.installI18nDictionary?.(lang, data);
          loaded = true;
          break;
        }
      } catch (_err) {
        // Try next candidate.
      }
    }
    if (!loaded) {
      try { host.log?.(`[language] no translation bundle loaded for ${bundle.id || bundle.pluginId || "plugin"}/${lang}`, "info"); } catch (_err) {}
    }
  }

  if (options.activate !== false) host.setLanguage?.(lang);
  return lang;
}

function buildWidget(host, ctx) {
  ensureStyles();
  const wrap = document.createElement("div");
  wrap.className = "language-plugin";

  const prefs = getLanguagePrefs(ctx);
  const label = document.createElement("label");
  const status = document.createElement("span");
  status.className = "language-plugin-status";

  const select = document.createElement("select");
  const autoWrap = document.createElement("label");
  autoWrap.className = "language-plugin-auto";
  const autoCheck = document.createElement("input");
  autoCheck.type = "checkbox";
  autoCheck.checked = !!prefs.autoDetect;
  const autoText = document.createElement("span");
  autoWrap.appendChild(autoCheck);
  autoWrap.appendChild(autoText);
  const rebuildOptions = () => {
    const current = normalizeLocale(host.getLanguage?.() || ctx?.state?.ui?.locale || "en");
    const langs = uniqueLanguages(host);
    select.innerHTML = "";
    for (const item of langs) {
      const opt = document.createElement("option");
      opt.value = item.code;
      opt.textContent = item.label || item.code;
      select.appendChild(opt);
    }
    select.value = langs.some((l) => l.code === current) ? current : "en";
  };

  const refreshText = () => {
    const locale = normalizeLocale(host.getLanguage?.() || "en");
    const strings = SELF_STRINGS[locale] || SELF_STRINGS[locale.split("-")[0]] || SELF_STRINGS.en;
    label.textContent = strings["language.label"] || "Language:";
    autoText.textContent = strings["language.auto_detect"] || "Auto detect browser language";
  };

  async function activateLanguage(next) {
    const lang = normalizeLocale(next || "en");
    status.textContent = (SELF_STRINGS[lang] || SELF_STRINGS[lang.split("-")[0]] || SELF_STRINGS.en)["language.status.loading"] || "Loading translations…";
    await loadLanguage(host, lang, { activate: true });
    refreshText();
    status.textContent = (SELF_STRINGS[lang] || SELF_STRINGS[lang.split("-")[0]] || SELF_STRINGS.en)["language.status.ready"] || "Translations loaded";
    setTimeout(() => { status.textContent = ""; }, 1400);
  }

  select.addEventListener("change", async () => {
    prefs.autoDetect = false;
    autoCheck.checked = false;
    const next = normalizeLocale(select.value || "en");
    await activateLanguage(next);
  });

  autoCheck.addEventListener("change", async () => {
    prefs.autoDetect = !!autoCheck.checked;
    if (prefs.autoDetect) {
      const next = pickSupportedBrowserLocale(host);
      select.value = next;
      await activateLanguage(next);
    }
  });

  rebuildOptions();
  refreshText();
  wrap.appendChild(label);
  wrap.appendChild(select);
  wrap.appendChild(autoWrap);
  wrap.appendChild(status);

  host.onLanguageChange?.(() => {
    rebuildOptions();
    refreshText();
  });

  if (prefs.autoDetect) {
    setTimeout(() => {
      const next = pickSupportedBrowserLocale(host);
      select.value = next;
      void activateLanguage(next);
    }, 0);
  }

  // Plugins may register bundles after this widget renders. Refresh the list shortly after load.
  setTimeout(() => {
    rebuildOptions();
    if (prefs.autoDetect) {
      const next = pickSupportedBrowserLocale(host);
      select.value = next;
      void activateLanguage(next);
    } else {
      void loadLanguage(host, host.getLanguage?.() || "en", { activate: false });
    }
  }, 300);

  return wrap;
}

const plugin = {
  id: meta.plugin_id,
  name: meta.name,
  kind: meta.kind,
  description: meta.description,
  meta,
  register(host) {
    host.registerI18nBundle?.({
      id: "language",
      pluginId: meta.plugin_id,
      basePath: new URL("./lang/", import.meta.url).toString(),
      languages: DEFAULT_LANGUAGES.map((l) => l.code),
      defaultLanguage: "en",
    });
    for (const [locale, dict] of Object.entries(SELF_STRINGS)) {
      host.installI18nDictionary?.(locale, dict);
    }
    host.addTranscriptTopbar((ctx) => buildWidget(host, ctx), "right");
    void loadLanguage(host, host.getLanguage?.() || "en", { activate: false });
  },
};

export default plugin;
