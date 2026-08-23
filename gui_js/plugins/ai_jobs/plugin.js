const meta = {
  plugin_id: "ai_jobs",
  name: "AI Jobs",
  kind: "gui",
  description: "Shows queued background AI jobs in the top-right status row.",
};

const STYLE_ID = "ai-jobs-style";
const DEFAULT_POLL_MS = 3000;

let pollTimer = null;
let buttonEl = null;
let badgeEl = null;
let popoverEl = null;
let popoverOpen = false;
let lastJobs = [];
let lastScheduler = null;
let outsideHandler = null;
let refreshDebounceTimer = null;

function ensureStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
.ai-jobs-btn {
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
.ai-jobs-btn:hover {
  border-color: var(--border);
  background: var(--ui-popover-item-bg);
}
.ai-jobs-badge {
  position: absolute;
  top: -4px;
  right: -4px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 999px;
  background: #c2410c;
  color: #fff7ed;
  font-size: 10px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.ai-jobs-popover {
  position: fixed;
  min-width: 240px;
  max-width: 320px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: var(--shadow);
  padding: 12px;
  z-index: 40;
  pointer-events: auto;
  color: var(--ui-ink);
}
.ai-jobs-popover h4 {
  margin: 0 0 8px;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 1.2px;
  color: var(--ui-muted);
}
.ai-jobs-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 280px;
  overflow: auto;
  padding-right: 4px;
}
.ai-jobs-item {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 8px;
  background: var(--ui-popover-item-bg);
  color: var(--ui-ink);
}
.ai-jobs-item.mine {
  border: 1px solid rgba(var(--accent-rgb), 0.7);
  box-shadow: 0 0 0 1px rgba(var(--accent-rgb), 0.15);
}
.ai-jobs-item-title {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
}
.ai-jobs-item-meta {
  margin-top: 4px;
  font-size: 11px;
  color: var(--ui-muted);
  display: flex;
  justify-content: space-between;
  gap: 8px;
}
.ai-jobs-item-actions {
  margin-top: 8px;
  display: flex;
  justify-content: flex-end;
}
.ai-jobs-cancel {
  font-size: 11px;
  padding: 4px 8px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--ui-control-bg);
  color: var(--ui-ink);
  cursor: pointer;
}
.ai-jobs-cancel:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.ai-jobs-muted {
  font-size: 12px;
  color: var(--ui-muted);
}
  `;
  document.head.appendChild(style);
}

function getState(ctx) {
  if (!ctx?.state) return { filters: { messages: true, ai_router: true, agent_flow: true } };
  if (!ctx.state.aiJobs || typeof ctx.state.aiJobs !== "object") {
    ctx.state.aiJobs = { filters: { messages: true, ai_router: true, agent_flow: true } };
  }
  if (!ctx.state.aiJobs.filters) {
    ctx.state.aiJobs.filters = { messages: true, ai_router: true, agent_flow: true };
  }
  return ctx.state.aiJobs;
}

function normalizeKind(kind) {
  const key = String(kind || "messages").toLowerCase();
  if (key === "ai_router" || key === "router") return "ai_router";
  if (key === "agent_flow" || key === "flow") return "agent_flow";
  return "messages";
}

function applyFilters(jobs, state) {
  const filters = state?.filters || {};
  return (jobs || []).filter((job) => {
    const kind = normalizeKind(job.kind);
    if (kind === "messages") return filters.messages !== false;
    if (kind === "ai_router") return filters.ai_router !== false;
    if (kind === "agent_flow") return filters.agent_flow !== false;
    return true;
  });
}

function updateBadge(count) {
  if (!badgeEl) return;
  if (!count) {
    badgeEl.textContent = "";
    badgeEl.style.display = "none";
    return;
  }
  badgeEl.textContent = String(count);
  badgeEl.style.display = "inline-flex";
}

function formatKind(kind) {
  const key = normalizeKind(kind);
  if (key === "ai_router") return "AI Router";
  if (key === "agent_flow") return "Agent Flow";
  return "Message";
}

function formatTitle(job) {
  const key = normalizeKind(job.kind);
  if (job.route_title || job.route_id) {
    return job.route_title || job.route_id;
  }
  if (key === "agent_flow") {
    return job.flow_name || "Agent Flow";
  }
  if (key === "ai_router") {
    return job.route_title || job.route_id || "AI Route";
  }
  return job.title || job.message || "Message";
}

function formatStartTime(job) {
  const ts = Number(job.started_ts || job.created_ts || 0);
  if (!ts) return "";
  try {
    return new Date(ts * 1000).toLocaleTimeString();
  } catch (_err) {
    return "";
  }
}

function formatQueue(job) {
  const pos = job.queue_pos;
  if (pos === 0) return "Running";
  if (pos === undefined || pos === null || pos === "") return "Queued";
  return `Queue ${pos}`;
}

function positionPopover() {
  if (!popoverEl || !buttonEl) return;
  const rect = buttonEl.getBoundingClientRect();
  const width = popoverEl.offsetWidth || 280;
  const left = Math.min(
    Math.max(12, rect.right - width),
    Math.max(12, window.innerWidth - width - 12)
  );
  const top = Math.min(
    Math.max(12, rect.bottom + 8),
    Math.max(12, window.innerHeight - (popoverEl.offsetHeight || 200) - 12)
  );
  popoverEl.style.left = `${left}px`;
  popoverEl.style.top = `${top}px`;
  popoverEl.style.right = "auto";
}

function renderPopover(ctx, jobs) {
  if (!popoverEl) return;
  popoverEl.innerHTML = "";
  const title = document.createElement("h4");
  title.textContent = "AI Jobs";
  popoverEl.appendChild(title);

  if (lastScheduler && typeof lastScheduler === "object") {
    const meta = document.createElement("div");
    meta.className = "ai-jobs-muted";
    const bits = [];
    if (lastScheduler.backend_mode) bits.push(`backend=${lastScheduler.backend_mode}`);
    if (lastScheduler.parallel_slots != null) bits.push(`slots=${lastScheduler.parallel_slots}`);
    if (lastScheduler.slot_count != null) bits.push(`server_slots=${lastScheduler.slot_count}`);
    if (lastScheduler.busy_slots != null && lastScheduler.slot_count != null) bits.push(`busy=${lastScheduler.busy_slots}/${lastScheduler.slot_count}`);
    if (lastScheduler.cont_batching != null) bits.push(`cont_batching=${lastScheduler.cont_batching ? "on" : "off"}`);
    if (lastScheduler.effective_per_model_parallel != null) bits.push(`scheduler_cap=${lastScheduler.effective_per_model_parallel}`);
    meta.textContent = bits.join(" | ") || "No scheduler diagnostics.";
    popoverEl.appendChild(meta);
  }

  if (!jobs.length) {
    const empty = document.createElement("div");
    empty.className = "ai-jobs-muted";
    empty.textContent = "No background jobs queued.";
    popoverEl.appendChild(empty);
    return;
  }

  const list = document.createElement("div");
  list.className = "ai-jobs-list";
  const me = String(ctx?.state?.auth?.username || ctx?.state?.auth?.alias || "").trim().toLowerCase();
  jobs.forEach((job) => {
    const card = document.createElement("div");
    card.className = "ai-jobs-item";
    const owner = String(job.owner_username || job.owner_alias || "").trim().toLowerCase();
    const isOwner = Boolean(me && owner && me === owner);
    if (isOwner) {
      card.classList.add("mine");
    }

    const header = document.createElement("div");
    header.className = "ai-jobs-item-title";
    const kind = document.createElement("span");
    kind.textContent = formatTitle(job);
    const id = document.createElement("span");
    id.textContent = job.job_id ? `#${job.job_id}` : "";
    header.appendChild(kind);
    header.appendChild(id);

    const meta = document.createElement("div");
    meta.className = "ai-jobs-item-meta";
    const queue = document.createElement("span");
    queue.textContent = formatQueue(job);
    const status = document.createElement("span");
    status.textContent = String(job.status || "queued");
    meta.appendChild(queue);
    meta.appendChild(status);

    const meta2 = document.createElement("div");
    meta2.className = "ai-jobs-item-meta";
    const time = document.createElement("span");
    time.textContent = formatStartTime(job);
    const kindLabel = document.createElement("span");
    kindLabel.textContent = formatKind(job.kind);
    meta2.appendChild(time);
    meta2.appendChild(kindLabel);

    const actions = document.createElement("div");
    actions.className = "ai-jobs-item-actions";
    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "ai-jobs-cancel";
    cancelBtn.textContent = "Cancel";
    cancelBtn.disabled = !job.job_id || !isOwner;
    cancelBtn.addEventListener("click", async (event) => {
      event.stopPropagation();
      if (!job.job_id) return;
      cancelBtn.disabled = true;
      try {
        await ctx.apiJson("/v1/ai_jobs/cancel", {
          method: "POST",
          body: { job_id: job.job_id },
        });
        await refreshJobs(ctx);
      } catch (err) {
        cancelBtn.disabled = false;
        ctx.log?.(`[ai_jobs] cancel failed: ${err.message || err}`, "warn");
      }
    });
    actions.appendChild(cancelBtn);

    card.appendChild(header);
    card.appendChild(meta);
    card.appendChild(meta2);
    card.appendChild(actions);
    list.appendChild(card);
  });
  popoverEl.appendChild(list);
  requestAnimationFrame(positionPopover);
}

async function refreshJobs(ctx) {
  if (!ctx?.apiJson) return;
  try {
    const url = popoverOpen ? "/v1/ai_jobs?include_slots=1" : "/v1/ai_jobs";
    const data = await ctx.apiJson(url);
    const jobs = Array.isArray(data?.jobs) ? data.jobs : [];
    lastScheduler = data?.scheduler && typeof data.scheduler === "object" ? data.scheduler : null;
    const state = getState(ctx);
    const filtered = applyFilters(jobs, state);
    lastJobs = filtered;
    updateBadge(filtered.length);
    if (popoverOpen) {
      renderPopover(ctx, filtered);
    }
  } catch (err) {
    lastJobs = [];
    lastScheduler = null;
    updateBadge(0);
    if (popoverOpen) {
      renderPopover(ctx, []);
    }
  }
}

function scheduleRefresh(ctx, delayMs = 0) {
  if (!ctx) return;
  if (refreshDebounceTimer) {
    clearTimeout(refreshDebounceTimer);
    refreshDebounceTimer = null;
  }
  refreshDebounceTimer = setTimeout(() => {
    refreshDebounceTimer = null;
    void refreshJobs(ctx);
  }, Math.max(0, Number(delayMs || 0)));
}

function startPolling(ctx) {
  if (pollTimer) return;
  pollTimer = setInterval(() => {
    void refreshJobs(ctx);
  }, DEFAULT_POLL_MS);
  void refreshJobs(ctx);
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function togglePopover(ctx) {
  popoverOpen = !popoverOpen;
  if (popoverOpen) {
    if (!popoverEl) {
      popoverEl = document.createElement("div");
      popoverEl.className = "ai-jobs-popover";
      const mount = (ctx && typeof ctx.getOverlayMount === "function" && ctx.getOverlayMount()) || document.body;
      mount.appendChild(popoverEl);
      requestAnimationFrame(positionPopover);
    }
    renderPopover(ctx, lastJobs || []);
  } else if (popoverEl) {
    popoverEl.remove();
    popoverEl = null;
  }
}

function closePopover() {
  popoverOpen = false;
  if (popoverEl) {
    popoverEl.remove();
    popoverEl = null;
  }
}

function buildButton(ctx) {
  ensureStyles();
  startPolling(ctx);
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "ai-jobs-btn";
  btn.title = "AI Jobs";
  btn.innerHTML = `
<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
  <rect x="7" y="7" width="10" height="10" rx="2"></rect>
  <path d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3"></path>
</svg>
  `;
  const badge = document.createElement("span");
  badge.className = "ai-jobs-badge";
  badge.style.display = "none";
  btn.appendChild(badge);
  btn.addEventListener("click", (event) => {
    event.stopPropagation();
    togglePopover(ctx);
    void refreshJobs(ctx);
  });
  buttonEl = btn;
  badgeEl = badge;
  return btn;
}

function openSettings(ctx) {
  const state = getState(ctx);
  const modal = window.createRouterModal ? window.createRouterModal("AI Jobs Filters") : null;
  const body = modal?.body || document.createElement("div");

  const wrap = document.createElement("div");
  wrap.className = "charts-box";

  const title = document.createElement("div");
  title.className = "charts-label";
  title.textContent = "Show job types";
  wrap.appendChild(title);

  function makeToggle(label, key) {
    const row = document.createElement("label");
    row.style.display = "flex";
    row.style.alignItems = "center";
    row.style.gap = "8px";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = state.filters[key] !== false;
    cb.addEventListener("change", () => {
      state.filters[key] = cb.checked;
    });
    const span = document.createElement("span");
    span.textContent = label;
    row.appendChild(cb);
    row.appendChild(span);
    return row;
  }

  const list = document.createElement("div");
  list.style.display = "flex";
  list.style.flexDirection = "column";
  list.style.gap = "6px";
  list.appendChild(makeToggle("Messages", "messages"));
  list.appendChild(makeToggle("AI Routers", "ai_router"));
  list.appendChild(makeToggle("Agent Flows", "agent_flow"));
  wrap.appendChild(list);

  body.appendChild(wrap);

  function onSave() {
    ctx.saveState?.();
    refreshJobs(ctx);
  }

  if (modal) {
    modal.overlay.onSave = onSave;
  } else {
    const fallback = document.createElement("div");
    fallback.appendChild(body);
    document.body.appendChild(fallback);
  }
}

function register(host) {
  host.addTopRightIconRow((ctx) => buildButton(ctx));
  host.addEventHandler?.((event, data, ctx) => {
    if (!ctx?.apiJson) return;
    if (event === "assistant_done" || event === "done") {
      scheduleRefresh(ctx, 75);
      return;
    }
    if (event === "message") {
      const msg = data?.msg;
      if (String(msg?.role || "").toLowerCase() === "assistant" && msg?.streaming === false) {
        scheduleRefresh(ctx, 75);
      }
    }
  });
  outsideHandler = (event) => {
    if (!popoverOpen) return;
    if (!popoverEl || !buttonEl) return;
    if (popoverEl.contains(event.target) || buttonEl.contains(event.target)) return;
    closePopover();
  };
  document.addEventListener("click", outsideHandler);
  window.addEventListener("resize", positionPopover);
  window.addEventListener("scroll", positionPopover, { passive: true });
}

function dispose() {
  stopPolling();
  if (refreshDebounceTimer) {
    clearTimeout(refreshDebounceTimer);
    refreshDebounceTimer = null;
  }
  closePopover();
  if (outsideHandler) {
    document.removeEventListener("click", outsideHandler);
    outsideHandler = null;
  }
  window.removeEventListener("resize", positionPopover);
  window.removeEventListener("scroll", positionPopover);
  if (buttonEl && buttonEl.remove) buttonEl.remove();
  buttonEl = null;
  badgeEl = null;
}

export default {
  meta,
  register,
  dispose,
  openSettings,
};
