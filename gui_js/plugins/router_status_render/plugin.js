const meta = {
  plugin_id: "router_status_render",
  name: "Router Status Render",
  kind: "render",
  description: "Render aiRouter plugin results into friendly status output.",
  has_notebook_tab: false,
};

const FENCE_RE = /```[ \t]*([^\r\n`]*)\r?\n([\s\S]*?)```[ \t]*/;
const STYLE_ID = "router-status-render-style";

function ensureStyles() {
  if (typeof document === "undefined") return;
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
.router-searxng-results {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.router-searxng-header {
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted);
}
.router-searxng-meta {
  font-size: 12px;
  color: var(--muted);
}
.router-searxng-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.router-searxng-card {
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 10px 12px;
  background: rgba(255, 255, 255, 0.02);
}
.router-searxng-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  text-decoration: none;
}
.router-searxng-title:hover {
  text-decoration: underline;
}
.router-searxng-desc {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.45;
  color: var(--muted);
}
.router-searxng-engine {
  margin-top: 6px;
  font-size: 11px;
  color: var(--muted);
}
`;
  document.head.appendChild(style);
}

function prettyName(routeId) {
  const rid = String(routeId || "").trim();
  if (!rid) return "AI Router";
  return rid
    .replace(/[-_]+/g, " ")
    .split(" ")
    .filter(Boolean)
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(" ");
}

function parseJsonText(text) {
  let raw = String(text || "").trim();
  if (!raw) return null;
  if (raw.startsWith("```")) {
    const match = FENCE_RE.exec(raw);
    if (match) raw = String(match[2] || "").trim();
  }
  if ((!raw.startsWith("{") || !raw.endsWith("}")) && raw.includes("{") && raw.includes("}")) {
    raw = raw.slice(raw.indexOf("{"), raw.lastIndexOf("}") + 1).trim();
  }
  if (!raw.startsWith("{") || !raw.endsWith("}")) return null;
  try {
    const obj = JSON.parse(raw);
    return obj && typeof obj === "object" && !Array.isArray(obj) ? obj : null;
  } catch (_err) {
    return null;
  }
}

function extractCodeBlock(text) {
  const raw = String(text || "").trim();
  if (!raw) return { lang: "", code: "" };
  const match = FENCE_RE.exec(raw);
  if (match) {
    const langRaw = String(match[1] || "").trim();
    const lang = langRaw ? langRaw.split(/\s+/)[0] : "";
    const code = String(match[2] || "").trim();
    return { lang, code };
  }
  return { lang: "", code: raw };
}

function getGenSettings(payload) {
  const raw = payload?.gen_settings;
  if (raw && typeof raw === "object" && !Array.isArray(raw)) return raw;
  return {};
}

function isSearxngPayload(payload) {
  return String(payload?.route_id || payload?.plugin_id || "").trim() === "searxng_ai_info_search";
}

function formatSearxngMeta(payload) {
  const parts = [];
  const query = String(payload?.query || "").trim();
  const categories = Array.isArray(payload?.categories) ? payload.categories : [];
  const engines = Array.isArray(payload?.engines) ? payload.engines : [];
  if (query) parts.push(`Query: ${query}`);
  if (categories.length) parts.push(`Categories: ${categories.join(", ")}`);
  if (engines.length) parts.push(`Engines: ${engines.join(", ")}`);
  return parts.join(" | ");
}

function renderSearxngFallback(block) {
  ensureStyles();
  const payload = block?.payload || {};
  const wrap = document.createElement("div");
  wrap.className = "block router-searxng-results";

  const header = document.createElement("div");
  header.className = "router-searxng-header";
  header.textContent = "SearXNG Results";
  wrap.appendChild(header);

  const metaLine = formatSearxngMeta(payload);
  if (metaLine) {
    const meta = document.createElement("div");
    meta.className = "router-searxng-meta";
    meta.textContent = metaLine;
    wrap.appendChild(meta);
  }

  const list = document.createElement("div");
  list.className = "router-searxng-list";
  const results = Array.isArray(payload?.results) ? payload.results : [];
  results.forEach((item) => {
    if (!item || typeof item !== "object") return;
    const card = document.createElement("div");
    card.className = "router-searxng-card";

    const link = document.createElement("a");
    link.className = "router-searxng-title";
    link.href = String(item.url || "#");
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = String(item.title || item.url || "Result");
    card.appendChild(link);

    const descText = String(item.content || "").trim();
    if (descText) {
      const desc = document.createElement("div");
      desc.className = "router-searxng-desc";
      desc.textContent = descText;
      card.appendChild(desc);
    }

    const engineText = String(item.engine || "").trim();
    if (engineText) {
      const engine = document.createElement("div");
      engine.className = "router-searxng-engine";
      engine.textContent = engineText;
      card.appendChild(engine);
    }

    list.appendChild(card);
  });
  wrap.appendChild(list);
  return wrap;
}

function unwrapRouterPayload(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return payload;
  const candidates = [
    payload.router_result,
    payload.result,
    payload.data,
    payload.ext?.router_result,
    payload.choices?.[0]?.ext?.router_result,
  ];
  for (const candidate of candidates) {
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) continue;
    if (candidate.route_id || candidate.plugin_id || candidate.image_url || candidate.video_url || candidate.answer) {
      return candidate;
    }
  }
  return payload;
}

function formatVideoSettings(payload) {
  const s = getGenSettings(payload);
  const parts = [];
  if (s.width && s.height) parts.push(`${s.width}w x ${s.height}h`);
  if (s.frames) parts.push(`${s.frames} frms`);
  if (s.fps) parts.push(`${s.fps} fps`);
  if (s.steps) parts.push(`${s.steps} steps`);
  if (s.guidance_scale !== undefined && s.guidance_scale !== null && s.guidance_scale !== "") {
    parts.push(`${s.guidance_scale} guidance scale`);
  }
  return parts.join(", ");
}

function formatImageSettings(payload) {
  const s = getGenSettings(payload);
  const parts = [];
  if (s.width && s.height) parts.push(`${s.width}w x ${s.height}h`);
  if (s.steps) parts.push(`${s.steps} steps`);
  if (s.guidance_scale !== undefined && s.guidance_scale !== null && s.guidance_scale !== "") {
    parts.push(`${s.guidance_scale} guidance scale`);
  }
  if (s.format) parts.push(String(s.format));
  return parts.join(", ");
}

function toUploadPath(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  if (raw.startsWith("/uploads/")) return raw;
  if (raw.startsWith("uploads/")) return `/${raw}`;
  if (raw.startsWith("http://") || raw.startsWith("https://")) return raw;
  const normalized = raw.replace(/\\/g, "/");
  if (normalized.includes("/uploads/")) {
    const name = normalized.split("/uploads/").pop();
    return name ? `/uploads/${name}` : "";
  }
  return "";
}

function absolutizeUpload(src, ctx) {
  if (!src) return "";
  if (src.startsWith("http://") || src.startsWith("https://")) return src;
  let base = String(ctx?.state?.remote?.serverUrl || "").replace(/\/+$/, "");
  if (!base || base.startsWith("file:")) {
    base = String(window?.location?.origin || "").replace(/\/+$/, "");
  }
  if (!base) return src;
  if (src.startsWith("/")) return `${base}${src}`;
  return `${base}/${src}`;
}

function resolveImageSource(payload, ctx) {
  let imageUrl = payload?.image_url || payload?.url || payload?.output_url || payload?.data?.image_url || payload?.result?.image_url;
  if (imageUrl && typeof imageUrl === "object") {
    imageUrl = imageUrl.url || imageUrl.href || "";
  }
  imageUrl = String(imageUrl || "").trim();
  const imagePath = String(payload?.image_path || payload?.path || payload?.output_path || payload?.data?.image_path || payload?.result?.image_path || "").trim();
  let src = "";
  if (imageUrl) {
    src = toUploadPath(imageUrl) || imageUrl;
  } else {
    src = toUploadPath(imagePath);
  }
  if (!src) return "";
  if (src.startsWith("/uploads/") || src.startsWith("uploads/")) {
    return absolutizeUpload(src, ctx);
  }
  return src;
}

function resolveVideoSource(payload, ctx) {
  let videoUrl = payload?.video_url || payload?.url || payload?.output_url || payload?.data?.video_url || payload?.result?.video_url;
  if (videoUrl && typeof videoUrl === "object") {
    videoUrl = videoUrl.url || videoUrl.href || "";
  }
  videoUrl = String(videoUrl || "").trim();
  const videoPath = String(payload?.video_path || payload?.path || payload?.output_path || payload?.data?.video_path || payload?.result?.video_path || "").trim();
  let src = "";
  if (videoPath) {
    src = toUploadPath(videoPath) || videoPath;
  } else if (videoUrl) {
    src = toUploadPath(videoUrl) || videoUrl;
  }
  if (!src) return "";
  if (src.startsWith("/uploads/") || src.startsWith("uploads/")) {
    return absolutizeUpload(src, ctx);
  }
  return src;
}

function renderPayload(payload, ctx) {
  payload = unwrapRouterPayload(payload);
  const blocks = [];
  const routeId = String(payload.route_id || payload.plugin_id || "").trim();
  const name = prettyName(routeId) || "AI Router";

  const lines = [];
  const nodeLabel = String(payload.flow_node_label || "").trim();
  if (nodeLabel) lines.push(nodeLabel);
  const preferCompact = nodeLabel && routeId === "image_gen";
  if (!preferCompact) {
    lines.push(`Using "${name}" ...`);
  }
  let error = payload.error || payload.reason || "";
  const failure = payload.failure && typeof payload.failure === "object" ? payload.failure : null;
  if (failure) {
    error = error || failure.detail || failure.reason || "";
  }
  if (payload.ok === false || error) {
    lines.push(error ? `"${name}" error: ${error}` : `"${name}" error.`);
    blocks.push({ type: "text", text: lines.join("\n") });
    return blocks;
  }

  if (isSearxngPayload(payload) && Array.isArray(payload.results) && payload.results.length) {
    return [{ type: "router_searxng_results", payload }];
  }

  if (routeId === "vlm_code2") {
    blocks.push({ type: "text", text: lines.join("\n") });
    const original = String(payload.original_code || "");
    const updated = String(payload.updated_code || "");
    const explanation = String(payload.explanation || "");
    if (original.trim()) {
      blocks.push({ type: "text", text: "Original code:" });
      const { lang, code } = extractCodeBlock(original);
      blocks.push({ type: "code", lang, text: code });
    }
    if (updated.trim()) {
      blocks.push({ type: "text", text: "Updated code:" });
      const { lang, code } = extractCodeBlock(updated);
      blocks.push({ type: "code", lang, text: code });
    }
    if (explanation.trim()) {
      blocks.push({ type: "text", text: `Explanation:\n${explanation}` });
    }
    return blocks;
  }

  const plan = payload.plan && typeof payload.plan === "object" ? payload.plan : null;
  if (plan) {
    const reason = String(plan.reason || "").trim();
    if (reason) lines.push(`Plan: ${reason}`);
    const steps = Array.isArray(plan.steps) ? plan.steps : [];
    if (steps.length) {
      lines.push("Steps:");
      steps.forEach((step, idx) => {
        if (!step || typeof step !== "object") return;
        const kind = String(step.kind || "").trim();
        const target = String(step.target || step.target_box || "").trim();
        if (target) lines.push(`${idx + 1}. ${kind} ${target}`);
        else lines.push(`${idx + 1}. ${kind}`);
      });
    }
  }

  const actions = Array.isArray(payload.actions) ? payload.actions : [];
  if (actions.length) {
    lines.push("Actions:");
    actions.forEach((action, idx) => {
      if (!action || typeof action !== "object") return;
      const ok = action.ok;
      const step = action.step && typeof action.step === "object" ? action.step : {};
      const kind = String(step.kind || action.kind || "").trim();
      const target = String(step.target || action.target || "").trim();
      const status = ok ? "ok" : "failed";
      if (routeId === "os_auto_cmd_browse") {
        const line = formatOsAutoCmdAction(step, action, status);
        lines.push(`${idx + 1}. ${line}`);
        return;
      }
      if (target) lines.push(`${idx + 1}. ${kind} ${target} (${status})`);
      else lines.push(`${idx + 1}. ${kind} (${status})`);
    });
  }

  const answerValue =
    payload.answer ||
    payload.text ||
    payload.response ||
    payload.content ||
    payload.summary ||
    payload.description ||
    (typeof payload.result === "string" ? payload.result : "") ||
    "";
  const answer = String(answerValue || "").trim();
  if (answer) {
    blocks.push({ type: "text", text: lines.join("\n") });
    blocks.push({ type: "text", text: answer });
    return blocks;
  }

  if (routeId === "video_gen") {
    const info = formatVideoSettings(payload);
    if (info) lines.push(`Generate Video: ${info}`);
  }

  if (routeId === "image_gen") {
    const info = formatImageSettings(payload);
    if (info) lines.push(`Generate Image: ${info}`);
  }

  const src = resolveImageSource(payload, ctx);
  if (src) {
    blocks.push({ type: "text", text: lines.join("\n") });
    blocks.push({ type: "image", src, name: "Generated image" });
    return blocks;
  }

  const vsrc = resolveVideoSource(payload, ctx);
  if (vsrc) {
    blocks.push({ type: "text", text: lines.join("\n") });
    blocks.push({ type: "video", src: vsrc, name: "Generated video" });
    return blocks;
  }

  if (lines.length <= 2) {
    lines.push(`"${name}" task done.`);
  }
  blocks.push({ type: "text", text: lines.join("\n") });
  return blocks;
}

function formatOsAutoCmdAction(step, action, status) {
  const kind = String(step?.kind || action?.kind || "").trim();
  const target = String(step?.target || action?.target || "").trim();
  if (kind === "command") {
    let cmd = String(step?.command || step?.cmd || action?.command || "").trim();
    const args = String(step?.args || "").trim();
    const text = String(step?.text || "").trim();
    if (args) cmd = cmd ? `${cmd} ${args}` : args;
    if (text) cmd = cmd ? `${cmd} ${text}` : text;
    const desc = target ? ` ${target}` : "";
    return cmd ? `command${desc}: ${cmd} (${status})` : `command${desc} (${status})`;
  }
  if (kind === "browser_dom") {
    const actionName = String(step?.action || "").trim().toLowerCase();
    const url = String(step?.url || "").trim();
    const selector = String(step?.selector || "").trim();
    const text = String(step?.text || "").trim();
    let code = `browser_dom: ${actionName}`;
    if (actionName === "goto" && url) {
      code = `page.goto(${JSON.stringify(url)})`;
    } else if (actionName === "click" && selector) {
      code = `page.click(${JSON.stringify(selector)})`;
    } else if (actionName === "type" && selector) {
      code = `page.type(${JSON.stringify(selector)}, ${JSON.stringify(text)})`;
    } else if (actionName === "read" && selector) {
      code = `page.innerText(${JSON.stringify(selector)})`;
    } else if (actionName === "snapshot") {
      code = "page.accessibility.snapshot()";
    }
    const desc = target ? ` ${target}` : "";
    return `${code}${desc} (${status})`;
  }
  if (kind) {
    return target ? `${kind} ${target} (${status})` : `${kind} (${status})`;
  }
  return `action (${status})`;
}

function transformBlocks(blocks, msg, ctx) {
  const role = String(msg?.role || "").trim().toLowerCase();
  if (role && role !== "assistant" && role !== "tool") return blocks;

  const out = [];
  for (const block of blocks || []) {
    if (!block || typeof block !== "object") continue;
    const type = String(block.type || "text").toLowerCase();
    if (type !== "text") {
      out.push(block);
      continue;
    }
    const text = String(block.text || "");
    const payload = parseJsonText(text);
    if (!payload) {
      out.push(block);
      continue;
    }
    out.push(...renderPayload(payload, ctx));
  }
  return out.length ? out : blocks;
}

transformBlocks.priority = 6;

const plugin = {
  id: meta.plugin_id,
  name: meta.name,
  kind: meta.kind,
  description: meta.description,
  meta,
  register(host) {
    ensureStyles();
    host.addBlockTransformer(transformBlocks);
    host.addBlockRenderer((block) => {
      if (!block || block.type !== "router_searxng_results") return null;
      return renderSearxngFallback(block);
    });
  },
};

export default plugin;
