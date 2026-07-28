const meta = {
  plugin_id: "skills_settings",
  name: "Skills Settings",
  kind: "panel",
  description: "Store reusable settings and API keys for agent skills.",
  has_notebook_tab: true,
};

const STYLE_ID = "skills-settings-style";

function ensureStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
.skills-settings-panel { display:flex; flex-direction:column; gap:12px; }
.skills-settings-card { border:1px solid var(--border); border-radius:14px; padding:12px; background:rgba(var(--panel-rgb),0.65); }
.skills-settings-title { font-weight:700; font-size:14px; color:var(--ui-ink); }
.skills-settings-sub { font-size:12px; color:var(--ui-muted); margin-top:3px; }
.skills-settings-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap:10px; margin-top:10px; }
.skills-settings-field { display:flex; flex-direction:column; gap:5px; }
.skills-settings-field label { font-size:12px; font-weight:700; color:var(--ui-ink); }
.skills-settings-input { width:100%; border:1px solid var(--border); border-radius:10px; padding:8px 10px; background:var(--ui-control-bg); color:var(--ui-ink); font-size:12px; }
.skills-settings-select { width:100%; border:1px solid var(--border); border-radius:10px; padding:8px 10px; background:var(--ui-control-bg); color:var(--ui-ink); font-size:12px; }
.skills-settings-actions { display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; align-items:center; }
.skills-settings-actions button { border:1px solid var(--border); border-radius:10px; padding:7px 10px; background:var(--ui-control-bg); color:var(--ui-ink); cursor:pointer; font-size:12px; }
.skills-settings-actions button.primary { background:rgba(var(--accent-rgb),0.14); border-color:rgba(var(--accent-rgb),0.45); }
.skills-settings-msg { font-size:12px; color:var(--ui-muted); }
.skills-settings-list { display:flex; flex-direction:column; gap:8px; }
.skills-settings-row { border:1px solid var(--border); border-radius:10px; padding:8px; background:rgba(var(--panel-rgb),0.38); font-size:12px; }
.skills-settings-row strong { color:var(--ui-ink); }
.skills-settings-code { font-family:Consolas,Menlo,monospace; font-size:11px; overflow-wrap:anywhere; }
`;
  document.head.appendChild(style);
}

function stateFor(ctx) {
  if (!ctx.state.skillsSettings || typeof ctx.state.skillsSettings !== "object") {
    ctx.state.skillsSettings = { loading: false, settings: {}, message: "", drafts: {} };
  }
  const st = ctx.state.skillsSettings;
  st.drafts = st.drafts || {};
  return st;
}

async function apiJson(ctx, url, options = {}) {
  const res = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const text = await res.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch (_err) { data = { ok: false, error: text || `HTTP ${res.status}` }; }
  if (!res.ok || data.ok === false) throw new Error(data.error || data.message || `HTTP ${res.status}`);
  return data;
}

async function loadSettings(ctx) {
  const st = stateFor(ctx);
  st.loading = true;
  try {
    const data = await apiJson(ctx, "/v1/skills_settings");
    st.settings = data.settings || {};
    st.message = "";
  } catch (err) {
    st.message = `Load failed: ${err.message || err}`;
  } finally {
    st.loading = false;
  }
  ctx.refresh?.();
}

async function saveSkillSetting(ctx, skillId, key, value) {
  const st = stateFor(ctx);
  try {
    await apiJson(ctx, `/v1/skills_settings/${encodeURIComponent(skillId)}`, {
      method: "PUT",
      body: JSON.stringify({ settings: { [key]: value } }),
    });
    st.message = `Saved ${key} for ${skillId}.`;
    await loadSettings(ctx);
  } catch (err) {
    st.message = `Save failed: ${err.message || err}`;
    ctx.refresh?.();
  }
}

function settingsRows(settings) {
  const skills = settings?.skills && typeof settings.skills === "object" ? settings.skills : {};
  const entries = Object.entries(skills);
  if (!entries.length) return `<div class="skills-settings-sub">No saved skill settings yet.</div>`;
  return `<div class="skills-settings-list">${entries.map(([skillId, row]) => {
    const keys = Array.isArray(row?.keys) ? row.keys : Object.keys(row?.settings || {});
    const vals = row?.settings && typeof row.settings === "object" ? row.settings : {};
    return `<div class="skills-settings-row"><strong>${escapeHtml(skillId)}</strong><div class="skills-settings-code">${keys.map((k) => `${escapeHtml(k)}: ${escapeHtml(String(vals[k] ?? ""))}`).join("<br>")}</div></div>`;
  }).join("")}</div>`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>\"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" }[ch]));
}

function renderPanelHtml(ctx) {
  ensureStyles();
  const st = stateFor(ctx);
  const savedGoogle = st.settings?.skills?.["external_data.google_scholar"]?.settings || {};
  const draftValue = (key, fallback = "") => Object.prototype.hasOwnProperty.call(st.drafts, key) ? st.drafts[key] : fallback;
  const gsDraft = draftValue("googleScholarSerpApiKey", savedGoogle.serpapi_key || "");
  const gsProvider = draftValue("googleScholarProvider", savedGoogle.provider || "auto");
  const gsSearxngBase = draftValue("googleScholarSearxngBase", savedGoogle.searxng_base_url || "");
  const gsSearxngEngines = draftValue("googleScholarSearxngEngines", savedGoogle.searxng_engines || "google scholar");
  const customSkill = st.drafts.customSkillId || "";
  const customKey = st.drafts.customKey || "";
  const customValue = st.drafts.customValue || "";
  return `
    <div class="skills-settings-panel">
      <div class="skills-settings-card">
        <div class="skills-settings-title">Google Scholar</div>
        <div class="skills-settings-sub"><span class="skills-settings-code">external_data.google_scholar</span> can use SearXNG Google Scholar first, or SerpAPI when selected/provided.</div>
        <div class="skills-settings-grid">
          <div class="skills-settings-field"><label>Provider</label><select class="skills-settings-select" data-ss-draft="googleScholarProvider"><option value="auto" ${gsProvider === "auto" ? "selected" : ""}>Auto</option><option value="searxng" ${gsProvider === "searxng" ? "selected" : ""}>SearXNG</option><option value="serpapi" ${gsProvider === "serpapi" ? "selected" : ""}>SerpAPI</option></select></div>
          <div class="skills-settings-field"><label>SearXNG base URL</label><input class="skills-settings-input" data-ss-draft="googleScholarSearxngBase" value="${escapeHtml(gsSearxngBase)}" placeholder="http://searxng:8080" /></div>
          <div class="skills-settings-field"><label>SearXNG engines</label><input class="skills-settings-input" data-ss-draft="googleScholarSearxngEngines" value="${escapeHtml(gsSearxngEngines)}" placeholder="google scholar" /></div>
          <div class="skills-settings-field"><label>SerpAPI key</label><input class="skills-settings-input" data-ss-draft="googleScholarSerpApiKey" type="password" value="${escapeHtml(gsDraft)}" placeholder="Optional SerpAPI key" /></div>
        </div>
        <div class="skills-settings-actions">
          <button class="primary" data-ss-save-google>Save Google Scholar Settings</button>
        </div>
      </div>
      <div class="skills-settings-card">
        <div class="skills-settings-title">Generic Skill Setting</div>
        <div class="skills-settings-sub">Use this for future skills that need API keys, tokens, endpoints, or other reusable parameters.</div>
        <div class="skills-settings-grid">
          <div class="skills-settings-field"><label>Skill ID</label><input class="skills-settings-input" data-ss-draft="customSkillId" value="${escapeHtml(customSkill)}" placeholder="external_data.some_skill" /></div>
          <div class="skills-settings-field"><label>Key</label><input class="skills-settings-input" data-ss-draft="customKey" value="${escapeHtml(customKey)}" placeholder="api_key" /></div>
          <div class="skills-settings-field"><label>Value</label><input class="skills-settings-input" data-ss-draft="customValue" type="password" value="${escapeHtml(customValue)}" placeholder="secret or setting" /></div>
        </div>
        <div class="skills-settings-actions"><button class="primary" data-ss-save-custom>Save Setting</button><button data-ss-refresh>Refresh</button><span class="skills-settings-msg">${escapeHtml(st.message || (st.loading ? "Loading..." : ""))}</span></div>
      </div>
      <div class="skills-settings-card">
        <div class="skills-settings-title">Saved Settings</div>
        <div class="skills-settings-sub">Secret-looking values are masked in the UI but stored for skill execution.</div>
        ${settingsRows(st.settings)}
      </div>
    </div>`;
}

function bindPanel(ctx, root) {
  const st = stateFor(ctx);
  root.querySelectorAll("[data-ss-draft]").forEach((el) => {
    const updateDraft = () => {
      st.drafts[el.dataset.ssDraft] = el.value;
    };
    el.addEventListener("input", updateDraft);
    el.addEventListener("change", updateDraft);
  });
  root.querySelector("[data-ss-save-google]")?.addEventListener("click", async () => {
    const settings = {
      provider: st.drafts.googleScholarProvider || "auto",
      searxng_base_url: st.drafts.googleScholarSearxngBase || "",
      searxng_engines: st.drafts.googleScholarSearxngEngines || "google scholar",
      serpapi_key: st.drafts.googleScholarSerpApiKey || "",
    };
    try {
      await apiJson(ctx, `/v1/skills_settings/${encodeURIComponent("external_data.google_scholar")}`, {
        method: "PUT",
        body: JSON.stringify({ settings }),
      });
      st.message = "Saved Google Scholar settings.";
      await loadSettings(ctx);
    } catch (err) {
      st.message = `Save failed: ${err.message || err}`;
      ctx.refresh?.();
    }
  });
  root.querySelector("[data-ss-save-custom]")?.addEventListener("click", () => {
    const skillId = String(st.drafts.customSkillId || "").trim();
    const key = String(st.drafts.customKey || "").trim();
    if (!skillId || !key) {
      st.message = "Skill ID and key are required.";
      ctx.refresh?.();
      return;
    }
    saveSkillSetting(ctx, skillId, key, st.drafts.customValue || "");
  });
  root.querySelector("[data-ss-refresh]")?.addEventListener("click", () => loadSettings(ctx));
  if (!st.loading && !st.settings?.skills) setTimeout(() => loadSettings(ctx), 0);
}


function renderPanel(container, ctx) {
  container.innerHTML = renderPanelHtml(ctx);
  bindPanel(ctx, container);
}
const plugin = {
  id: meta.plugin_id,
  name: meta.name,
  kind: meta.kind,
  description: meta.description,
  meta,
  register(host) {
    host.addPanelTab({
      id: meta.plugin_id,
      title: "Skills Settings",
      render: (container, ctx) => renderPanel(container, ctx),
    });
  },
  openSettings(ctx) {
    ctx?.openPluginPanel?.(meta.plugin_id, { openModal: true });
  },
};

export default plugin;

