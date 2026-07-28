const meta = {
  plugin_id: "chat_style_renderer",
  name: "Chat Style Renderer",
  kind: "render",
  description: "Style chat tags and render <think> blocks as collapsible sections.",
  has_notebook_tab: false,
};

const THINK_RE = /<think>([\s\S]*?)<\/think>/gi;
const THINK_LABEL_RE = /(^|\n)\s*(thinking|thoughts?|reasoning)\s*:\s*/i;
const FINAL_LABEL_RE = /(^|\n)\s*(final|answer|response)\s*:\s*/i;
const STYLE_ID = "chat-style-renderer";
const THINK_PROMPT_KEY = "chat_style_renderer:think";
const RELEVANT_TAG_RE = /<!--\s*is_relevant\s*:\s*(true|false)\s*-->/gi;
const URL_RE = /https?:\/\/[^\s<>"')]+/gi;
const MD_LINK_RE = /\[[^\]]*\]\((https?:\/\/[^\s)]+)\)/gi;
const LONG_URL_MIN = 60;
const DISPLAY_MATH_RE = /\$\$([\s\S]*?)\$\$/g;
const FENCED_CODE_RE = /```[\s\S]*?```/g;
const MOJIBAKE_HINT_RE = /(?:Ãƒ.|Ã‚.|Ã¢.|Ã°[\u0080-\u00BF]|ð[\u0080-\u00BF]|Ã¯[\u0080-\u00BF]|Â[^\s]|â[^\s])/;
const INLINE_MATH_DELIM_RE = /\$(?!\$)/;
const CP1252_EXTRA_BYTES = {
  0x20ac: 0x80,
  0x201a: 0x82,
  0x0192: 0x83,
  0x201e: 0x84,
  0x2026: 0x85,
  0x2020: 0x86,
  0x2021: 0x87,
  0x02c6: 0x88,
  0x2030: 0x89,
  0x0160: 0x8a,
  0x2039: 0x8b,
  0x0152: 0x8c,
  0x017d: 0x8e,
  0x2018: 0x91,
  0x2019: 0x92,
  0x201c: 0x93,
  0x201d: 0x94,
  0x2022: 0x95,
  0x2013: 0x96,
  0x2014: 0x97,
  0x02dc: 0x98,
  0x2122: 0x99,
  0x0161: 0x9a,
  0x203a: 0x9b,
  0x0153: 0x9c,
  0x017e: 0x9e,
  0x0178: 0x9f,
};

function applySystemPromptHook(payload) {
  try {
    payload.ext = payload.ext && typeof payload.ext === "object" ? payload.ext : {};
    payload.ext.system_prompts =
      payload.ext.system_prompts && typeof payload.ext.system_prompts === "object" && !Array.isArray(payload.ext.system_prompts)
        ? payload.ext.system_prompts
        : {};
    payload.ext.system_prompts[THINK_PROMPT_KEY] =
      "If you include reasoning or scratchpad content, wrap it in <think>...</think> tags so the UI can collapse it. " +
      "Do not include <think> in the final answer unless you are providing reasoning text.";
    if (!payload.ext.system_prompts_mode) payload.ext.system_prompts_mode = "system";
  } catch (_err) {
    // ignore
  }
  return payload;
}

function ensureStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
.think-card {
  border: 1px solid var(--border);
  border-radius: 12px;
  background: rgba(var(--panel-rgb), 0.6);
  overflow: hidden;
}
.think-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border: none;
  background: rgba(var(--accent-rgb), 0.08);
  cursor: pointer;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: inherit;
}
.think-caret {
  width: 0;
  height: 0;
  border-left: 5px solid transparent;
  border-right: 5px solid transparent;
  border-top: 6px solid var(--muted);
  transition: transform 0.2s ease;
}
.think-card.open .think-caret {
  transform: rotate(180deg);
}
.think-body {
  padding: 8px 10px;
  display: none;
}
.think-card.open .think-body {
  display: block;
}
.message .bubble,
.message .bubble .block-text,
.message .bubble .block,
.message .bubble a,
.message .bubble code {
  overflow-wrap: anywhere;
  word-break: break-word;
}
.csr-math-display {
  margin: 10px 0;
  padding: 10px 14px;
  border-left: 3px solid rgba(var(--accent-rgb), 0.45);
  background: rgba(var(--accent-rgb), 0.06);
  border-radius: 10px;
  overflow-x: auto;
  text-align: center;
}
.csr-math-inline {
  display: inline-block;
  padding: 0 0.2em;
  border-radius: 0.35em;
  background: rgba(var(--accent-rgb), 0.06);
}
.csr-math-tex {
  font-family: "Cambria Math", "STIX Two Math", "Times New Roman", serif;
  font-style: italic;
  font-size: 1.02em;
  white-space: pre-wrap;
}
.code-card[data-collapsed="false"] .code-card-body {
  max-height: 28rem;
  overflow-y: auto;
}
  `;
  document.head.appendChild(style);
}

function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function stripRelevantTag(text) {
  return String(text || "").replace(RELEVANT_TAG_RE, "").trim();
}

function decodeUtf8Mojibake(text) {
  const raw = String(text || "");
  if (!raw || !MOJIBAKE_HINT_RE.test(raw)) return raw;
  try {
    let current = raw;
    for (let pass = 0; pass < 3; pass += 1) {
      const bytes = [];
      let valid = true;
      for (let i = 0; i < current.length; i += 1) {
        const code = current.charCodeAt(i);
        if (code <= 255) {
          bytes.push(code & 0xff);
          continue;
        }
        const cp1252 = CP1252_EXTRA_BYTES[code];
        if (cp1252 != null) {
          bytes.push(cp1252);
          continue;
        }
        if (code > 255) {
          valid = false;
          break;
        }
      }
      if (!valid) break;
      const decoded = new TextDecoder("utf-8", { fatal: false }).decode(new Uint8Array(bytes));
      if (!decoded || decoded === current) break;
      current = decoded;
      if (!MOJIBAKE_HINT_RE.test(current)) break;
    }
    if (current !== raw) return current;
  } catch (_err) {
    // ignore
  }
  return raw;
}

function findMarkdownLinkRanges(text) {
  const ranges = [];
  if (!text) return ranges;
  for (const match of text.matchAll(MD_LINK_RE)) {
    if (typeof match.index !== "number") continue;
    ranges.push([match.index, match.index + match[0].length]);
  }
  return ranges;
}

function isInRanges(idx, ranges) {
  for (const [start, end] of ranges) {
    if (idx >= start && idx < end) return true;
  }
  return false;
}

function formatUrlDisplay(url) {
  try {
    const parsed = new URL(url);
    const host = parsed.hostname || parsed.host || url;
    const parts = parsed.pathname.split("/").filter(Boolean);
    let tail = parts.length ? parts[parts.length - 1] : "";
    if (tail.length > 30) tail = `${tail.slice(0, 27)}…`;
    let display = host;
    if (tail) {
      display += parts.length > 1 ? `/…/${tail}` : `/${tail}`;
    } else if (parsed.pathname && parsed.pathname !== "/") {
      display += "/…";
    }
    if (parsed.search) display += "?…";
    return display;
  } catch (_err) {
    return url;
  }
}

function shortenLongUrls(text) {
  if (!text) return text;
  const ranges = findMarkdownLinkRanges(text);
  let out = "";
  let last = 0;
  URL_RE.lastIndex = 0;
  let match;
  while ((match = URL_RE.exec(text)) !== null) {
    const start = match.index;
    const end = start + match[0].length;
    if (isInRanges(start, ranges)) {
      out += text.slice(last, end);
      last = end;
      continue;
    }
    out += text.slice(last, start);
    let raw = match[0];
    let trailing = "";
    while (/[),.!?]$/.test(raw)) {
      trailing = raw.slice(-1) + trailing;
      raw = raw.slice(0, -1);
    }
    if (raw.length >= LONG_URL_MIN) {
      const label = formatUrlDisplay(raw);
      out += `[${label}](${raw})${trailing}`;
    } else {
      out += `${raw}${trailing}`;
    }
    last = end;
  }
  out += text.slice(last);
  return out;
}

function renderTexHtml(tex) {
  const clean = String(tex || "").trim();
  if (!clean) return "";
  try {
    const katex = typeof window !== "undefined" ? window.katex : null;
    if (katex && typeof katex.renderToString === "function") {
      return katex.renderToString(clean, { displayMode: false, throwOnError: false, strict: "ignore" });
    }
  } catch (_err) {
    // ignore
  }
  return `<span class="csr-math-tex">${escapeHtml(clean)}</span>`;
}

function splitDisplayMath(text) {
  const out = [];
  const raw = String(text || "");
  let pos = 0;
  DISPLAY_MATH_RE.lastIndex = 0;
  let match;
  while ((match = DISPLAY_MATH_RE.exec(raw)) !== null) {
    const start = match.index;
    const end = start + match[0].length;
    if (start > pos) out.push({ type: "text", text: raw.slice(pos, start) });
    out.push({ type: "math_display", text: String(match[1] || "").trim() });
    pos = end;
  }
  if (pos < raw.length) out.push({ type: "text", text: raw.slice(pos) });
  return out;
}

function splitCodeFences(text) {
  const parts = [];
  const raw = String(text || "");
  let pos = 0;
  FENCED_CODE_RE.lastIndex = 0;
  let match;
  while ((match = FENCED_CODE_RE.exec(raw)) !== null) {
    const start = match.index;
    const end = start + match[0].length;
    if (start > pos) parts.push({ type: "text", text: raw.slice(pos, start) });
    parts.push({ type: "code", text: raw.slice(start, end) });
    pos = end;
  }
  if (pos < raw.length) parts.push({ type: "text", text: raw.slice(pos) });
  return parts;
}

function decodeMessageMojibake(msg) {
  if (!msg || typeof msg !== "object") return msg;
  let changed = false;
  const next = { ...msg };
  if (typeof next.content === "string") {
    const decoded = decodeUtf8Mojibake(next.content);
    if (decoded !== next.content) {
      next.content = decoded;
      changed = true;
    }
  } else if (Array.isArray(next.content)) {
    const parts = next.content.map((part) => {
      if (!part || typeof part !== "object") return part;
      let partChanged = false;
      const nextPart = { ...part };
      if (typeof nextPart.text === "string") {
        const decoded = decodeUtf8Mojibake(nextPart.text);
        if (decoded !== nextPart.text) {
          nextPart.text = decoded;
          partChanged = true;
        }
      }
      if (typeof nextPart.content === "string") {
        const decoded = decodeUtf8Mojibake(nextPart.content);
        if (decoded !== nextPart.content) {
          nextPart.content = decoded;
          partChanged = true;
        }
      }
      return partChanged ? nextPart : part;
    });
    if (parts.some((part, idx) => part !== next.content[idx])) {
      next.content = parts;
      changed = true;
    }
  }
  return changed ? next : msg;
}

function splitInlineMathSegments(text) {
  const raw = String(text || "");
  if (!raw || !INLINE_MATH_DELIM_RE.test(raw)) return null;
  const parts = [];
  let last = 0;
  let i = 0;
  while (i < raw.length) {
    if (raw[i] !== "$" || raw[i - 1] === "\\" || raw[i + 1] === "$" || raw[i - 1] === "$") {
      i += 1;
      continue;
    }
    let j = i + 1;
    while (j < raw.length) {
      if (raw[j] === "\n") break;
      if (raw[j] === "$" && raw[j - 1] !== "\\" && raw[j + 1] !== "$") break;
      j += 1;
    }
    if (j >= raw.length || raw[j] !== "$" || j === i + 1) {
      i += 1;
      continue;
    }
    const expr = raw.slice(i + 1, j).trim();
    if (!expr) {
      i = j + 1;
      continue;
    }
    if (i > last) parts.push({ type: "text", text: raw.slice(last, i) });
    parts.push({ type: "math", text: expr });
    last = j + 1;
    i = j + 1;
  }
  if (!parts.length) return null;
  if (last < raw.length) parts.push({ type: "text", text: raw.slice(last) });
  return parts;
}

function renderInlineMathSpan(expr) {
  const span = document.createElement("span");
  span.className = "csr-math-inline";
  span.innerHTML = renderTexHtml(expr);
  return span;
}

function enhanceTextNodeInlineMath(node) {
  if (!node || !node.parentNode) return false;
  const parentEl = node.parentElement;
  if (
    parentEl &&
    parentEl.closest(".code-card, pre, code, .csr-math-inline, .csr-math-display, .think-card, script, style")
  ) {
    return false;
  }
  const parts = splitInlineMathSegments(node.nodeValue || "");
  if (!parts || !parts.length) return false;
  const frag = document.createDocumentFragment();
  for (const part of parts) {
    if (part.type === "math") {
      frag.appendChild(renderInlineMathSpan(part.text));
    } else if (part.text) {
      frag.appendChild(document.createTextNode(part.text));
    }
  }
  node.parentNode.replaceChild(frag, node);
  return true;
}

function enhanceInlineMath(root) {
  if (!root) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  let current;
  while ((current = walker.nextNode())) {
    if (!current.nodeValue || current.nodeValue.indexOf("$") === -1) continue;
    nodes.push(current);
  }
  for (const node of nodes) enhanceTextNodeInlineMath(node);
}

let enhanceQueued = false;
let sweepTimer = null;
function getTranscriptRoot() {
  if (typeof document === "undefined") return null;
  return document.getElementById("transcript") || document.querySelector("[data-sid]") || null;
}

function blockInlineMathFingerprint(node) {
  const text = String(node?.textContent || "");
  return `${text.length}:${text}`;
}

function sweepTranscriptInlineMath(root) {
  if (!root) return;
  const candidates = root.querySelectorAll(".block-text, .think-body");
  for (const node of candidates) {
    if (!(node instanceof HTMLElement)) continue;
    const text = String(node.textContent || "");
    if (!text || text.indexOf("$") === -1) continue;
    const fp = blockInlineMathFingerprint(node);
    if (node.dataset.csrInlineMathFingerprint === fp) continue;
    enhanceInlineMath(node);
    node.dataset.csrInlineMathFingerprint = blockInlineMathFingerprint(node);
  }
}

function scheduleEnhanceInlineMath() {
  if (enhanceQueued) return;
  enhanceQueued = true;
  const run = () => {
    enhanceQueued = false;
    const root = getTranscriptRoot();
    if (!root) return;
    sweepTranscriptInlineMath(root);
  };
  if (typeof window !== "undefined" && typeof window.requestAnimationFrame === "function") {
    window.requestAnimationFrame(run);
  } else {
    setTimeout(run, 0);
  }
}

function ensureSweepTimer() {
  if (sweepTimer) return;
  sweepTimer = setInterval(() => {
    scheduleEnhanceInlineMath();
  }, 750);
}

function extractThinkFallback(text) {
  const raw = String(text || "");
  if (!raw) return null;
  const lower = raw.toLowerCase();
  const closeIdx = lower.indexOf("</think>");
  if (closeIdx !== -1 && lower.indexOf("<think>") === -1) {
    const before = raw.slice(0, closeIdx).trim();
    const after = raw.slice(closeIdx + "</think>".length).trim();
    const out = [];
    if (before) out.push({ type: "think", text: before });
    if (after) out.push({ type: "text", text: after });
    return out.length ? out : null;
  }

  const match = THINK_LABEL_RE.exec(raw);
  if (!match) return null;
  if (match.index > 200) return null;

  const start = match.index + match[0].length;
  let end = raw.length;
  let after = "";
  const rest = raw.slice(start);
  const finalMatch = FINAL_LABEL_RE.exec(rest);
  if (finalMatch) {
    end = start + finalMatch.index;
    after = rest.slice(finalMatch.index + finalMatch[0].length);
  }

  const pre = raw.slice(0, match.index).trim();
  const thinkText = raw.slice(start, end).trim();
  after = String(after || "").trim();
  const blocks = [];
  if (pre) blocks.push({ type: "text", text: pre });
  if (thinkText) blocks.push({ type: "think", text: thinkText });
  if (after) blocks.push({ type: "text", text: after });
  return blocks.length ? blocks : null;
}

function transformBlocks(blocks, msg) {
  const role = String(msg?.role || "").trim().toLowerCase();
  if (role && role !== "assistant" && role !== "tool") return blocks;

  const out = [];
  for (const block of blocks || []) {
    if (!block || typeof block !== "object") continue;
    const type = String(block.type || "text").toLowerCase();
    if (type === "code") {
      out.push({ ...block, text: decodeUtf8Mojibake(String(block.text || "")) });
      continue;
    }
    if (type !== "text") {
      out.push(block);
      continue;
    }
    const text = shortenLongUrls(stripRelevantTag(String(block.text || "")));
    let pos = 0;
    let usedThinkTag = false;
    THINK_RE.lastIndex = 0;
    let match;
    while ((match = THINK_RE.exec(text)) !== null) {
      const start = match.index;
      const end = start + match[0].length;
      if (start > pos) {
        out.push({ type: "text", text: text.slice(pos, start) });
      }
      out.push({ type: "think", text: String(match[1] || "") });
      usedThinkTag = true;
      pos = end;
    }
    if (pos < text.length) {
      const remaining = text.slice(pos);
      if (!usedThinkTag) {
        const fallback = extractThinkFallback(remaining);
        if (fallback) {
          out.push(...fallback);
        } else {
          out.push({ type: "text", text: remaining });
        }
      } else {
        out.push({ type: "text", text: remaining });
      }
    }
  }
  const normalized = [];
  for (const block of out.length ? out : blocks) {
    if (!block || typeof block !== "object") continue;
    const type = String(block.type || "text").toLowerCase();
    if (type !== "text") {
      normalized.push(block);
      continue;
    }
    for (const part of splitCodeFences(String(block.text || ""))) {
      if (part.type === "code") {
        normalized.push({ type: "text", text: part.text });
        continue;
      }
      for (const chunk of splitDisplayMath(part.text)) {
        normalized.push(chunk.type === "math_display" ? chunk : { type: "text", text: chunk.text });
      }
    }
  }
  return normalized.length ? normalized : blocks;
}

transformBlocks.priority = 12;

function renderThinkBlock(block, renderMarkdown) {
  ensureStyles();
  const wrap = document.createElement("div");
  wrap.className = "block block-think";

  const card = document.createElement("div");
  card.className = "think-card";

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "think-toggle";

  const caret = document.createElement("span");
  caret.className = "think-caret";
  const label = document.createElement("span");
  label.textContent = "thinking";

  toggle.appendChild(caret);
  toggle.appendChild(label);

  const body = document.createElement("div");
  body.className = "think-body";
  const content = document.createElement("div");
  const text = String(block?.text || "").trim();
  content.innerHTML = renderMarkdown ? renderMarkdown(text) : escapeHtml(text).replace(/\n/g, "<br>");
  body.appendChild(content);

  toggle.addEventListener("click", () => {
    card.classList.toggle("open");
  });

  card.appendChild(toggle);
  card.appendChild(body);
  wrap.appendChild(card);
  return wrap;
}

function renderMathDisplayBlock(block) {
  ensureStyles();
  const wrap = document.createElement("div");
  wrap.className = "block block-math-display";
  const body = document.createElement("div");
  body.className = "csr-math-display";
  const text = String(block?.text || "").trim();
  body.innerHTML = renderTexHtml(text);
  wrap.appendChild(body);
  return wrap;
}

const plugin = {
  id: meta.plugin_id,
  name: meta.name,
  kind: meta.kind,
  description: meta.description,
  meta,
  register(host) {
    host.addBlockTransformer(transformBlocks);
    host.addMessagePreRenderer((msg) => {
      return decodeMessageMojibake(msg);
    });
    host.addCompletionPayloadHook(applySystemPromptHook);
    host.addBlockRenderer((block, _msg, ctx) => {
      const type = String(block?.type || "text").toLowerCase();
      if (type === "math_display") return renderMathDisplayBlock(block);
      if (type !== "think") return null;
      const renderMarkdown = ctx?.renderMarkdown;
      return renderThinkBlock(block, renderMarkdown);
    });
    ensureStyles();
    ensureSweepTimer();
    scheduleEnhanceInlineMath();
    if (typeof host?.refreshTranscript === "function") {
      setTimeout(() => host.refreshTranscript(), 0);
    } else if (typeof window !== "undefined" && typeof window.renderTranscript === "function") {
      setTimeout(() => window.renderTranscript(), 0);
    }
  },
};

export default plugin;
