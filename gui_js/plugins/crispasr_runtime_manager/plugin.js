const meta = {
  plugin_id: "crispasr_runtime_manager",
  name: "CrispASR Runtime Manager",
  kind: "panel",
  description: "Manage CrispASR runtime builds and executable paths for speech models.",
  has_notebook_tab: true,
};

const STYLE_ID = "crispasr-runtime-style";
const POLL_MS = 2500;

function ensureStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
.crm-root { display:flex; flex-direction:column; gap:12px; }
.crm-section, .crm-card, .crm-details {
  border:1px solid var(--border);
  border-radius:14px;
  padding:12px;
  background: rgba(var(--panel-rgb), 0.72);
}
.crm-title { font-size:14px; font-weight:700; color:var(--ui-ink); }
.crm-sub { font-size:11px; color:var(--ui-muted); }
.crm-value { font-size:12px; color:var(--ui-ink); overflow-wrap:anywhere; }
.crm-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:10px; }
.crm-actions { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
.crm-actions button {
  border-radius:10px; border:1px solid var(--border); background:var(--ui-control-bg);
  color:var(--ui-ink); padding:7px 10px; font-size:12px; cursor:pointer;
}
.crm-actions button.primary { background: rgba(var(--accent-rgb), 0.14); border-color: rgba(var(--accent-rgb), 0.4); }
.crm-actions button[disabled] { opacity:0.55; cursor:default; }
.crm-form { display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:10px; }
.crm-field { display:flex; flex-direction:column; gap:6px; }
.crm-field label { font-size:12px; font-weight:700; color:var(--ui-ink); }
.crm-input, .crm-select, .crm-textarea {
  width:100%; border-radius:12px; border:1px solid var(--border); padding:8px 10px;
  font-size:12px; background:var(--ui-control-bg); color:var(--ui-ink);
}
.crm-textarea { min-height:80px; resize:vertical; }
.crm-list { display:flex; flex-direction:column; gap:10px; max-height:520px; overflow:auto; }
.crm-json {
  border:1px solid var(--border); border-radius:10px; padding:8px; background:rgba(var(--panel-rgb), 0.45);
  font-family:Consolas, Menlo, monospace; font-size:11px; white-space:pre-wrap; overflow-wrap:anywhere;
}
.crm-pill {
  display:inline-flex; align-items:center; gap:6px; padding:3px 8px; border-radius:999px;
  border:1px solid var(--border); font-size:10px; text-transform:uppercase; letter-spacing:0.05em;
}
.crm-pill.ok { border-color: rgba(18, 126, 67, 0.28); background: rgba(18, 126, 67, 0.08); color:#127e43; }
.crm-pill.bad { border-color: rgba(180, 35, 24, 0.28); background: rgba(180, 35, 24, 0.08); color:#b42318; }
.crm-message {
  border-radius:10px; padding:8px 10px; font-size:12px; border:1px solid var(--border);
  background: rgba(var(--panel-rgb), 0.46); color:var(--ui-ink);
}
.crm-message.error { border-color: rgba(180, 35, 24, 0.28); background: rgba(180, 35, 24, 0.08); color:#b42318; }
.crm-message.success { border-color: rgba(18, 126, 67, 0.28); background: rgba(18, 126, 67, 0.08); color:#127e43; }
.crm-hint {
  border-radius:10px; padding:8px 10px; font-size:12px; border:1px solid var(--border);
  background: rgba(var(--panel-rgb), 0.38); color:var(--ui-muted);
}
.crm-collapsible-head {
  display:flex; align-items:center; justify-content:space-between; gap:10px;
  cursor:pointer; user-select:none;
}
.crm-collapsible-head .crm-title { margin:0; }
`;
  document.head.appendChild(style);
}

function isAdmin(ctx) {
  return String(ctx?.state?.auth?.role || "").toLowerCase() === "admin";
}

function activeSid(ctx) {
  return String(ctx?.state?.ui?.activeSid || "default").trim() || "default";
}

function panelState(ctx, sid) {
  if (!ctx.state.crispasrRuntime || typeof ctx.state.crispasrRuntime !== "object") ctx.state.crispasrRuntime = { bySid: {} };
  if (!ctx.state.crispasrRuntime.bySid) ctx.state.crispasrRuntime.bySid = {};
  if (!ctx.state.crispasrRuntime.bySid[sid]) {
    ctx.state.crispasrRuntime.bySid[sid] = {
      loading: false,
      status: null,
      message: null,
      draft: {
        name: "",
        runtime_id: "vulkan",
        source_mode: "clone",
        source_dir: "",
        notes: "",
      },
      register: {
        name: "",
        runtime_id: "cpu",
        executable_path: "",
        notes: "",
      },
      prereqCollapsed: true,
      expandedJobLogs: {},
      pendingBuilds: {},
      pollTimer: null,
      lastOpenJobId: "",
    };
  }
  const state = ctx.state.crispasrRuntime.bySid[sid];
  if (typeof state.prereqCollapsed !== "boolean") state.prereqCollapsed = true;
  if (!state.expandedJobLogs || typeof state.expandedJobLogs !== "object") state.expandedJobLogs = {};
  if (!state.pendingBuilds || typeof state.pendingBuilds !== "object") state.pendingBuilds = {};
  return state;
}

function setMessage(state, kind, text) {
  state.message = text ? { kind, text } : null;
}

function isInstallBuildBusy(state, installId) {
  const key = String(installId || "").trim();
  if (!key) return false;
  if (state?.pendingBuilds && state.pendingBuilds[key]) return true;
  const installs = Array.isArray(state?.status?.installs) ? state.status.installs : [];
  const row = installs.find((item) => String(item?.install_id || "") === key);
  return !!String(row?.active_job_id || "").trim();
}

async function apiPost(ctx, path, body) {
  return ctx.apiJson(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
}

function clearPoll(state) {
  if (state?.pollTimer) {
    clearTimeout(state.pollTimer);
    state.pollTimer = null;
  }
}

async function fetchJobLogs(ctx, state, jobId, lines = 120) {
  const cleanJobId = String(jobId || "").trim();
  if (!cleanJobId) return;
  try {
    const res = await ctx.apiJson(`/v1/crispasr_runtime/logs?job_id=${encodeURIComponent(cleanJobId)}&lines=${encodeURIComponent(String(lines))}`);
    state.status = state.status || {};
    if (!state.status.jobLogs) state.status.jobLogs = {};
    state.status.jobLogs[cleanJobId] = res;
    state.lastOpenJobId = cleanJobId;
  } catch (err) {
    setMessage(state, "error", `Logs failed: ${err?.message || err}`);
  }
}

async function refreshActiveJobLogs(ctx, state) {
  const jobs = Array.isArray(state?.status?.jobs) ? state.status.jobs : [];
  const runningJobs = jobs.filter((job) => String(job?.status || "").toLowerCase() === "running");
  if (runningJobs.length) {
    for (const job of runningJobs) {
      await fetchJobLogs(ctx, state, job?.job_id);
    }
    return;
  }
  if (state.lastOpenJobId) {
    const known = jobs.find((job) => String(job?.job_id || "") === String(state.lastOpenJobId));
    if (known) await fetchJobLogs(ctx, state, state.lastOpenJobId);
  }
}

function captureScrollState(container) {
  const state = {
    containerTop: Number(container?.scrollTop || 0),
    descendants: [],
  };
  if (!container?.querySelectorAll) return state;
  const rows = container.querySelectorAll("[data-scroll-key]");
  rows.forEach((el) => {
    state.descendants.push({
      key: String(el.getAttribute("data-scroll-key") || ""),
      top: Number(el.scrollTop || 0),
      left: Number(el.scrollLeft || 0),
    });
  });
  return state;
}

function restoreScrollState(container, snapshot) {
  if (!container?.isConnected || !snapshot) return;
  requestAnimationFrame(() => {
    try { container.scrollTop = Number(snapshot.containerTop || 0); } catch (_err) {}
    if (!container?.querySelectorAll) return;
    const rows = container.querySelectorAll("[data-scroll-key]");
    rows.forEach((el) => {
      const key = String(el.getAttribute("data-scroll-key") || "");
      const saved = (snapshot.descendants || []).find((row) => row.key && row.key === key);
      if (!saved) return;
      try { el.scrollTop = Number(saved.top || 0); } catch (_err) {}
      try { el.scrollLeft = Number(saved.left || 0); } catch (_err) {}
    });
  });
}

function isEditingForm(container) {
  try {
    const active = document?.activeElement;
    if (!active || !container?.contains?.(active)) return false;
    if (active.matches?.(".crm-input, .crm-select, .crm-textarea")) return true;
    const tag = String(active.tagName || "").toUpperCase();
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
  } catch (_err) {
    return false;
  }
}

async function loadStatus(ctx, container) {
  const state = panelState(ctx, activeSid(ctx));
  clearPoll(state);
  const scrollSnapshot = captureScrollState(container);
  const shouldRenderLoading = !state.status;
  const preserveEditor = isEditingForm(container);
  state.loading = true;
  if (shouldRenderLoading && !preserveEditor) renderPanel(container, ctx);
  try {
    const previousJobLogs = state.status?.jobLogs && typeof state.status.jobLogs === "object" ? state.status.jobLogs : {};
    const freshStatus = await ctx.apiJson("/v1/crispasr_runtime/status");
    const liveInstalls = Array.isArray(freshStatus?.installs) ? freshStatus.installs : [];
    Object.keys(state.pendingBuilds || {}).forEach((installId) => {
      const row = liveInstalls.find((item) => String(item?.install_id || "") === String(installId));
      if (row && String(row?.active_job_id || "").trim()) delete state.pendingBuilds[installId];
    });
    state.status = {
      ...(freshStatus || {}),
      jobLogs: { ...previousJobLogs },
    };
    await refreshActiveJobLogs(ctx, state);
    setMessage(state, null, "");
  } catch (err) {
    setMessage(state, "error", err?.message || String(err));
  } finally {
    state.loading = false;
    if (!preserveEditor) {
      renderPanel(container, ctx);
      restoreScrollState(container, scrollSnapshot);
    }
  }
}

function runtimeChoices(state) {
  const rows = state?.status?.host?.compatibility || [];
  return rows.map((row) => ({
    value: String(row?.id || row?.runtime_id || ""),
    label: String(row?.label || row?.runtime_id || ""),
  })).filter((row) => row.value);
}

function runtimeInfo(state, runtimeId) {
  const rid = String(runtimeId || "").trim().toLowerCase();
  const rows = Array.isArray(state?.status?.host?.compatibility) ? state.status.host.compatibility : [];
  return rows.find((row) => String(row?.id || row?.runtime_id || "").trim().toLowerCase() === rid) || null;
}

function renderPrereqList(prereqs) {
  const rows = Array.isArray(prereqs) ? prereqs : [];
  if (!rows.length) return null;
  const wrap = document.createElement("div");
  wrap.className = "crm-list";
  wrap.setAttribute("data-scroll-key", "prereq-list");
  rows.forEach((row) => {
    const card = document.createElement("div");
    card.className = "crm-card";
    const head = document.createElement("div");
    head.className = "crm-actions";
    head.appendChild(Object.assign(document.createElement("div"), {
      className: "crm-title",
      textContent: String(row?.title || row?.key || "Prerequisite"),
    }));
    const pill = document.createElement("span");
    pill.className = `crm-pill ${row?.present ? "ok" : "bad"}`;
    pill.textContent = row?.present ? "ready" : "needed";
    head.appendChild(pill);
    card.appendChild(head);
    [row?.why, row?.install_where ? `Install: ${row.install_where}` : "", row?.verify ? `Verify: ${row.verify}` : ""]
      .filter(Boolean)
      .forEach((text) => {
        card.appendChild(Object.assign(document.createElement("div"), {
          className: "crm-sub",
          textContent: String(text),
        }));
      });
    if (row?.install_url) {
      const linkWrap = document.createElement("div");
      linkWrap.className = "crm-actions";
      const link = document.createElement("a");
      link.href = String(row.install_url);
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.className = "crm-sub";
      link.textContent = "Open install page";
      linkWrap.appendChild(link);
      card.appendChild(linkWrap);
    }
    wrap.appendChild(card);
  });
  return wrap;
}

function selectField(value, choices, onChange) {
  const sel = document.createElement("select");
  sel.className = "crm-select";
  choices.forEach((choice) => {
    const opt = document.createElement("option");
    opt.value = String(choice.value);
    opt.textContent = String(choice.label);
    if (String(choice.value) === String(value)) opt.selected = true;
    sel.appendChild(opt);
  });
  sel.addEventListener("change", () => onChange(sel.value));
  return sel;
}

function inputField(value, onChange, placeholder = "") {
  const input = document.createElement("input");
  input.className = "crm-input";
  input.value = String(value || "");
  if (placeholder) input.placeholder = placeholder;
  input.addEventListener("input", () => onChange(input.value));
  return input;
}

function textareaField(value, onChange, placeholder = "") {
  const input = document.createElement("textarea");
  input.className = "crm-textarea";
  input.value = String(value || "");
  if (placeholder) input.placeholder = placeholder;
  input.addEventListener("input", () => onChange(input.value));
  return input;
}

function renderMessage(message) {
  if (!message?.text) return null;
  const el = document.createElement("div");
  el.className = `crm-message${message.kind === "error" ? " error" : message.kind === "success" ? " success" : ""}`;
  el.textContent = String(message.text);
  return el;
}

function copyText(text) {
  try {
    if (navigator?.clipboard?.writeText) return navigator.clipboard.writeText(String(text || ""));
  } catch (_err) {}
  return Promise.resolve();
}

function renderPanel(container, ctx) {
  ensureStyles();
  const state = panelState(ctx, activeSid(ctx));
  clearPoll(state);
  container.innerHTML = "";
  const root = document.createElement("div");
  root.className = "crm-root";

  if (!isAdmin(ctx)) {
    root.appendChild(Object.assign(document.createElement("div"), {
      className: "crm-hint",
      textContent: "This panel is available to admins only.",
    }));
    container.appendChild(root);
    return;
  }

  const hostSection = document.createElement("div");
  hostSection.className = "crm-section";
  hostSection.appendChild(Object.assign(document.createElement("div"), { className: "crm-title", textContent: "Host Compatibility" }));
  const host = state.status?.host || {};
  const hostGrid = document.createElement("div");
  hostGrid.className = "crm-grid";
  [
    ["Host OS", host.host_os || "--"],
    ["Platform", host.platform || "--"],
    ["Python", host.python || "--"],
    ["App root", host.cwd || "--"],
    ["CrispASR client root", host.client_root || "--"],
  ].forEach(([label, value]) => {
    const card = document.createElement("div");
    card.className = "crm-card";
    card.appendChild(Object.assign(document.createElement("div"), { className: "crm-sub", textContent: String(label) }));
    card.appendChild(Object.assign(document.createElement("div"), { className: "crm-value", textContent: String(value) }));
    hostGrid.appendChild(card);
  });
  hostSection.appendChild(hostGrid);

  const compatGrid = document.createElement("div");
  compatGrid.className = "crm-grid";
  (host.compatibility || []).forEach((row) => {
    const card = document.createElement("div");
    card.className = "crm-card";
    card.appendChild(Object.assign(document.createElement("div"), { className: "crm-title", textContent: String(row?.label || row?.runtime_id || "Runtime") }));
    const pill = document.createElement("span");
    pill.className = `crm-pill ${row?.compatible ? "ok" : "bad"}`;
    pill.textContent = row?.compatible ? "compatible" : "missing pieces";
    card.appendChild(pill);
    const reasons = document.createElement("div");
    reasons.className = "crm-sub";
    reasons.textContent = (row?.reasons || []).join(" ");
    card.appendChild(reasons);
    compatGrid.appendChild(card);
  });
  hostSection.appendChild(compatGrid);
  const selectedDraftRuntime = runtimeInfo(state, state.draft.runtime_id);
  if (selectedDraftRuntime?.prerequisites?.length) {
    const prereqSection = document.createElement("div");
    prereqSection.className = "crm-section";
    const missingCount = (selectedDraftRuntime.prerequisites || []).filter((row) => !row?.present).length;
    const prereqHead = document.createElement("div");
    prereqHead.className = "crm-collapsible-head";
    prereqHead.appendChild(Object.assign(document.createElement("div"), {
      className: "crm-title",
      textContent: `Prerequisites for ${selectedDraftRuntime.label || selectedDraftRuntime.runtime_id || state.draft.runtime_id}`,
    }));
    const headActions = document.createElement("div");
    headActions.className = "crm-actions";
    if (missingCount > 0) {
      headActions.appendChild(Object.assign(document.createElement("span"), {
        className: "crm-pill bad",
        textContent: `${missingCount} missing`,
      }));
    }
    headActions.appendChild(Object.assign(document.createElement("span"), {
      className: "crm-pill",
      textContent: state.prereqCollapsed ? "collapsed" : "expanded",
    }));
    prereqHead.appendChild(headActions);
    prereqHead.addEventListener("click", () => {
      state.prereqCollapsed = !state.prereqCollapsed;
      renderPanel(container, ctx);
    });
    prereqSection.appendChild(prereqHead);
    if (!state.prereqCollapsed) {
      prereqSection.appendChild(Object.assign(document.createElement("div"), {
        className: "crm-sub",
        textContent: "Check these before creating or building a managed install.",
      }));
      prereqSection.appendChild(renderPrereqList(selectedDraftRuntime.prerequisites));
    }
    hostSection.appendChild(prereqSection);
  }
  root.appendChild(hostSection);

  const createSection = document.createElement("div");
  createSection.className = "crm-section";
  createSection.appendChild(Object.assign(document.createElement("div"), { className: "crm-title", textContent: "Create Managed CrispASR Install" }));
  const createForm = document.createElement("div");
  createForm.className = "crm-form";
  const createFields = [
    ["Install name", inputField(state.draft.name, (v) => { state.draft.name = v; }, "crispasr-intel-vulkan")],
    ["Runtime", selectField(state.draft.runtime_id, runtimeChoices(state), (v) => { state.draft.runtime_id = v; })],
    ["Source mode", selectField(state.draft.source_mode, [{ value: "clone", label: "Clone CrispASR repo" }, { value: "existing", label: "Use existing source dir" }], (v) => { state.draft.source_mode = v; renderPanel(container, ctx); })],
    ["Source dir (optional)", inputField(state.draft.source_dir, (v) => { state.draft.source_dir = v; }, state.draft.source_mode === "existing" ? String(host.client_root || "") : "leave blank to clone into vendor/crispasr_client")],
    ["Notes", textareaField(state.draft.notes, (v) => { state.draft.notes = v; }, "Intel Arc B70 Vulkan build, ROCm laptop build, etc.")],
  ];
  createFields.forEach(([label, field]) => {
    const wrap = document.createElement("label");
    wrap.className = "crm-field";
    wrap.appendChild(Object.assign(document.createElement("span"), { textContent: String(label) }));
    wrap.appendChild(field);
    createForm.appendChild(wrap);
  });
  createSection.appendChild(createForm);
  const createActions = document.createElement("div");
  createActions.className = "crm-actions";
  const previewBtn = document.createElement("button");
  previewBtn.textContent = "Preview plan";
  previewBtn.addEventListener("click", async () => {
    try {
      const res = await apiPost(ctx, "/v1/crispasr_runtime/plan", state.draft);
      setMessage(state, "success", `Plan ready. Runtime path: ${res?.plan?.executable_path || "--"}`);
      state.status = state.status || {};
      state.status.lastPlan = res;
    } catch (err) {
      setMessage(state, "error", `Plan failed: ${err?.message || err}`);
    }
    renderPanel(container, ctx);
  });
  const createBtn = document.createElement("button");
  createBtn.className = "primary";
  createBtn.textContent = "Create install";
  createBtn.addEventListener("click", async () => {
    try {
      const res = await apiPost(ctx, "/v1/crispasr_runtime/install/create", state.draft);
      setMessage(state, "success", `Created ${res?.install?.install_id || "install"}.`);
      state.draft.name = "";
      await loadStatus(ctx, container);
      return;
    } catch (err) {
      setMessage(state, "error", `Create failed: ${err?.message || err}`);
    }
    renderPanel(container, ctx);
  });
  createActions.appendChild(previewBtn);
  createActions.appendChild(createBtn);
  createSection.appendChild(createActions);
  if (state.status?.lastPlan?.plan) {
    createSection.appendChild(Object.assign(document.createElement("div"), {
      className: "crm-json",
      textContent: JSON.stringify(state.status.lastPlan, null, 2),
    }));
  }
  root.appendChild(createSection);

  const registerSection = document.createElement("div");
  registerSection.className = "crm-section";
  registerSection.appendChild(Object.assign(document.createElement("div"), { className: "crm-title", textContent: "Register Existing CrispASR Path" }));
  const registerForm = document.createElement("div");
  registerForm.className = "crm-form";
  [
    ["Install name", inputField(state.register.name, (v) => { state.register.name = v; }, "crispasr-cuda-existing")],
    ["Runtime", selectField(state.register.runtime_id, runtimeChoices(state), (v) => { state.register.runtime_id = v; })],
    ["Executable path", inputField(state.register.executable_path, (v) => { state.register.executable_path = v; }, "C:\\path\\to\\crispasr.exe")],
    ["Notes", textareaField(state.register.notes, (v) => { state.register.notes = v; }, "Host build path, shared workstation path, etc.")],
  ].forEach(([label, field]) => {
    const wrap = document.createElement("label");
    wrap.className = "crm-field";
    wrap.appendChild(Object.assign(document.createElement("span"), { textContent: String(label) }));
    wrap.appendChild(field);
    registerForm.appendChild(wrap);
  });
  registerSection.appendChild(registerForm);
  const registerActions = document.createElement("div");
  registerActions.className = "crm-actions";
  const registerBtn = document.createElement("button");
  registerBtn.textContent = "Register path";
  registerBtn.addEventListener("click", async () => {
    try {
      await apiPost(ctx, "/v1/crispasr_runtime/install/register", state.register);
      setMessage(state, "success", "Registered existing CrispASR executable.");
      state.register.name = "";
      state.register.executable_path = "";
      state.register.notes = "";
      await loadStatus(ctx, container);
      return;
    } catch (err) {
      setMessage(state, "error", `Register failed: ${err?.message || err}`);
    }
    renderPanel(container, ctx);
  });
  registerActions.appendChild(registerBtn);
  registerSection.appendChild(registerActions);
  root.appendChild(registerSection);

  const msg = renderMessage(state.message);
  if (msg) root.appendChild(msg);
  root.appendChild(Object.assign(document.createElement("div"), {
    className: "crm-hint",
    textContent: "Builds run on the server and keep going even if you close this dialog. Reopen it anytime to watch status and logs.",
  }));

  const installsSection = document.createElement("div");
  installsSection.className = "crm-section";
  installsSection.appendChild(Object.assign(document.createElement("div"), { className: "crm-title", textContent: "Managed Installs" }));
  const installList = document.createElement("div");
  installList.className = "crm-list";
  installList.setAttribute("data-scroll-key", "install-list");
  const installs = state.status?.installs || [];
  installs.forEach((row) => {
    const installId = String(row?.install_id || "");
    const probe = runtimeInfo(state, row?.runtime_id);
    const canBuild = !!probe?.build_ready && !!probe?.compatible;
    const buildBusy = isInstallBuildBusy(state, installId);
    const card = document.createElement("div");
    card.className = "crm-card";
    card.appendChild(Object.assign(document.createElement("div"), { className: "crm-title", textContent: String(row?.name || row?.install_id || "install") }));
    card.appendChild(Object.assign(document.createElement("div"), { className: "crm-sub", textContent: `${row?.runtime_label || row?.runtime_id || "--"} | ${row?.host_os || "--"}` }));
    if (probe && !canBuild) {
      card.appendChild(Object.assign(document.createElement("div"), {
        className: "crm-message error",
        textContent: `Build not ready: ${String((probe.reasons || []).join(" "))}`,
      }));
    }
    const grid = document.createElement("div");
    grid.className = "crm-grid";
    [
      ["Install id", row?.install_id || "--"],
      ["Executable path", row?.executable_path || "--"],
      ["Executable exists", row?.executable_exists ? "yes" : "no"],
      ["Source dir", row?.source_dir || "--"],
      ["Build dir", row?.build_dir || "--"],
      ["Scripts dir", row?.scripts_dir || "--"],
      ["Logs dir", row?.logs_dir || "--"],
      ["Active job", row?.active_job_id || "--"],
    ].forEach(([label, value]) => {
      const kv = document.createElement("div");
      kv.className = "crm-card";
      kv.appendChild(Object.assign(document.createElement("div"), { className: "crm-sub", textContent: String(label) }));
      kv.appendChild(Object.assign(document.createElement("div"), { className: "crm-value", textContent: String(value) }));
      grid.appendChild(kv);
    });
    card.appendChild(grid);

    const actions = document.createElement("div");
    actions.className = "crm-actions";
    const copyBtn = document.createElement("button");
    copyBtn.textContent = "Copy path";
    copyBtn.addEventListener("click", async () => {
      await copyText(row?.executable_path || "");
      setMessage(state, "success", `Copied path for ${row?.install_id || "install"}.`);
      renderPanel(container, ctx);
    });
    actions.appendChild(copyBtn);
    const buildBtn = document.createElement("button");
    buildBtn.className = "primary";
    buildBtn.textContent = buildBusy ? "Build running" : "Build now";
    buildBtn.disabled = buildBusy || !canBuild;
    if (!canBuild && probe?.reasons?.length) buildBtn.title = String(probe.reasons.join(" "));
    buildBtn.addEventListener("click", async () => {
      try {
        state.pendingBuilds[installId] = true;
        setMessage(state, "success", `Starting build for ${installId}...`);
        renderPanel(container, ctx);
        await apiPost(ctx, "/v1/crispasr_runtime/build/start", { install_id: row?.install_id });
        setMessage(state, "success", `Started build for ${row?.install_id}.`);
        await loadStatus(ctx, container);
        return;
      } catch (err) {
        delete state.pendingBuilds[installId];
        setMessage(state, "error", `Build start failed: ${err?.message || err}`);
      }
      renderPanel(container, ctx);
    });
    actions.appendChild(buildBtn);
    const stopBtn = document.createElement("button");
    stopBtn.textContent = "Stop build";
    stopBtn.disabled = !row?.active_job_id;
    stopBtn.addEventListener("click", async () => {
      try {
        await apiPost(ctx, "/v1/crispasr_runtime/build/stop", { install_id: row?.install_id });
        setMessage(state, "success", `Stopped build for ${row?.install_id}.`);
        await loadStatus(ctx, container);
        return;
      } catch (err) {
        setMessage(state, "error", `Stop failed: ${err?.message || err}`);
      }
      renderPanel(container, ctx);
    });
    actions.appendChild(stopBtn);
    const removeBtn = document.createElement("button");
    removeBtn.textContent = "Remove";
    removeBtn.disabled = !!row?.active_job_id;
    removeBtn.addEventListener("click", async () => {
      if (!window.confirm(`Remove ${row?.install_id}?`)) return;
      try {
        await apiPost(ctx, "/v1/crispasr_runtime/install/remove", { install_id: row?.install_id });
        setMessage(state, "success", `Removed ${row?.install_id}.`);
        await loadStatus(ctx, container);
        return;
      } catch (err) {
        setMessage(state, "error", `Remove failed: ${err?.message || err}`);
      }
      renderPanel(container, ctx);
    });
    actions.appendChild(removeBtn);
    card.appendChild(actions);
    if (row?.active_job_id) {
      const activeLogs = state.status?.jobLogs?.[row.active_job_id];
      if (activeLogs?.lines?.length) {
        card.appendChild(Object.assign(document.createElement("div"), { className: "crm-sub", textContent: "Live build log tail" }));
        card.appendChild(Object.assign(document.createElement("div"), {
          className: "crm-json",
          "data-scroll-key": `install-active-log:${row.active_job_id}`,
          textContent: String((activeLogs.lines || []).join("\n")),
        }));
      }
    }
    if (row?.scripts) {
      card.appendChild(Object.assign(document.createElement("div"), {
        className: "crm-json",
        "data-scroll-key": `install-scripts:${row?.install_id || ""}`,
        textContent: JSON.stringify(row.scripts, null, 2),
      }));
    }
    installList.appendChild(card);
  });
  if (!installs.length) {
    installList.appendChild(Object.assign(document.createElement("div"), { className: "crm-sub", textContent: state.loading ? "Loading..." : "No CrispASR installs yet." }));
  }
  installsSection.appendChild(installList);
  root.appendChild(installsSection);

  const jobsSection = document.createElement("div");
  jobsSection.className = "crm-section";
  jobsSection.appendChild(Object.assign(document.createElement("div"), { className: "crm-title", textContent: "Build Jobs" }));
  const jobList = document.createElement("div");
  jobList.className = "crm-list";
  jobList.setAttribute("data-scroll-key", "job-list");
  const jobs = state.status?.jobs || [];
  jobs.forEach((job) => {
    const jobId = String(job?.job_id || "");
    const card = document.createElement("div");
    card.className = "crm-card";
    card.appendChild(Object.assign(document.createElement("div"), { className: "crm-title", textContent: String(jobId || "job") }));
    card.appendChild(Object.assign(document.createElement("div"), { className: "crm-sub", textContent: `${job?.status || "--"} | install=${job?.install_id || "--"} | pid=${job?.pid || "--"}` }));
    const actions = document.createElement("div");
    actions.className = "crm-actions";
    const logs = state.status?.jobLogs?.[jobId];
    const logsBtn = document.createElement("button");
    const expanded = !!state.expandedJobLogs[jobId];
    logsBtn.textContent = expanded ? "Hide logs" : "Load logs";
    logsBtn.addEventListener("click", async () => {
      const isExpanded = !!state.expandedJobLogs[jobId];
      if (isExpanded) {
        state.expandedJobLogs = {};
      } else {
        state.expandedJobLogs = { [jobId]: true };
        await fetchJobLogs(ctx, state, jobId);
      }
      renderPanel(container, ctx);
    });
    actions.appendChild(logsBtn);
    const copyLogsBtn = document.createElement("button");
    copyLogsBtn.textContent = "Copy logs";
    copyLogsBtn.addEventListener("click", async () => {
      let currentLogs = state.status?.jobLogs?.[jobId];
      if (!Array.isArray(currentLogs?.lines) || !currentLogs.lines.length) {
        await fetchJobLogs(ctx, state, jobId);
        currentLogs = state.status?.jobLogs?.[jobId];
      }
      const text = Array.isArray(currentLogs?.lines) ? currentLogs.lines.join("\n") : "";
      if (!text) {
        setMessage(state, "error", `No logs available for ${jobId}.`);
        renderPanel(container, ctx);
        return;
      }
      await copyText(text);
      setMessage(state, "success", `Copied logs for ${jobId}.`);
      renderPanel(container, ctx);
    });
    actions.appendChild(copyLogsBtn);
    const deleteJobBtn = document.createElement("button");
    deleteJobBtn.textContent = "Delete job";
    deleteJobBtn.disabled = String(job?.status || "").toLowerCase() === "running";
    deleteJobBtn.addEventListener("click", async () => {
      if (!window.confirm(`Delete build job ${jobId}?`)) return;
      try {
        await apiPost(ctx, "/v1/crispasr_runtime/job/remove", { install_id: jobId });
        delete state.expandedJobLogs[jobId];
        if (state.status?.jobLogs) delete state.status.jobLogs[jobId];
        if (String(state.lastOpenJobId || "") === jobId) state.lastOpenJobId = "";
        setMessage(state, "success", `Deleted build job ${jobId}.`);
        await loadStatus(ctx, container);
        return;
      } catch (err) {
        setMessage(state, "error", `Delete job failed: ${err?.message || err}`);
      }
      renderPanel(container, ctx);
    });
    actions.appendChild(deleteJobBtn);
    card.appendChild(actions);
    if (expanded && logs?.lines) {
      const logBox = document.createElement("div");
      logBox.className = "crm-json";
      logBox.setAttribute("data-scroll-key", `job-log:${jobId}`);
      logBox.textContent = String((logs.lines || []).join("\n"));
      card.appendChild(logBox);
    }
    jobList.appendChild(card);
  });
  if (!jobs.length) {
    jobList.appendChild(Object.assign(document.createElement("div"), { className: "crm-sub", textContent: state.loading ? "Loading..." : "No build jobs yet." }));
  }
  jobsSection.appendChild(jobList);
  root.appendChild(jobsSection);

  container.appendChild(root);

  if (container.isConnected) {
    state.pollTimer = setTimeout(() => {
      if (!container.isConnected) return;
      void loadStatus(ctx, container);
    }, POLL_MS);
  }
}

const plugin = {
  id: meta.plugin_id,
  name: meta.name,
  kind: meta.kind,
  description: meta.description,
  meta,
  register(host) {
    host.shareObject({
      id: "crispasr-managed-install-picker",
      type: "model_deck_field_enhancer",
      service: "select_options",
      appliesTo({ typeId, fieldKey }) {
        const tid = String(typeId || "").trim();
        return fieldKey === "managed_crispasr_install_id" && (tid === "speech" || tid === "speech_asr" || tid === "speech_tts");
      },
      fieldKey: "managed_crispasr_install_id",
      placeholder: "Select a managed CrispASR install...",
      emptyLabel: "No managed CrispASR installs found",
      helpText: "Pick a managed CrispASR runtime install from the shared registry, or type the install id manually above.",
      async loadOptions(ctx) {
        try {
          const payload = await ctx.apiJson("/v1/crispasr_runtime/status");
          const installs = Array.isArray(payload?.installs) ? payload.installs : [];
          return installs.map((row) => ({
            value: String(row?.install_id || ""),
            label: `${String(row?.name || row?.install_id || "install")} [${String(row?.runtime_id || "--")}]`,
            description: String(row?.executable_path || ""),
          })).filter((row) => row.value);
        } catch (_err) {
          return [];
        }
      },
    });
    host.addPanelTab({
      id: meta.plugin_id,
      title: "CrispASR Runtime",
      render: (container, ctx) => {
        if (!isAdmin(ctx)) {
          container.innerHTML = "";
          return;
        }
        renderPanel(container, ctx);
        void loadStatus(ctx, container);
      },
    });
  },
};

export default plugin;
