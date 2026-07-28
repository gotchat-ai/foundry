/* global window, document, fetch */
// Lightweight embed loader for chat_js.htm without iframes.
//
// Usage:
//   <div id="llm-chat-js"></div>
//   <script
//     src="https://YOUR_GUI_DOMAIN/embed.js"
//     data-target="#llm-chat-js"
//     data-server="https://YOUR_API_DOMAIN"
//     data-rev="timestamp"
//     data-dev="true"
//     data-token="OPTIONAL_AUTH_TOKEN"
//     data-pid="default"
//     data-sid="main"
//     data-alias="Optional display name"
//     data-sass-mode="business|customer"
//     data-sass-account-id="fitsoft"
//     data-sass-business-id="example-business"
//     data-sass-user-id="current-dashboard-user"
//     data-biz-package="business_starter"
//     data-biz-business-id="example-business"
//     data-height="80vh"
//     data-topbar="hidden|visible"
//   ></script>
//
// Notes:
// - This is a single-instance embed (chat_js uses fixed global element IDs).
// - We scope CSS under `#llm-chat-js-embed` to avoid stomping the host page.
(function () {
  const script = document.currentScript;
  if (!script) return;

  const data = script.dataset || {};
  const targetSel = data.target || "#llm-chat-js";
  function getEmbedTarget() {
    const el = document.querySelector(targetSel);
    return el || document.body || document.documentElement;
  }

  const uiBase = new URL(".", script.src);
  const uiOrigin = uiBase.origin;

  // The API server defaults to the UI server origin (works when UI reverse-proxies /v1).
  // In "multi-domain" deployments, we can resolve the correct public API URL via the
  // central account/CMS service using `data-identifier-key`.
  let server = (data.server || uiOrigin || "").replace(/\/+$/, "");
  let hostService = (data.hostService || "").trim();
  let clientService = (data.clientService || "").trim();

  const token = (data.token || "").trim();
  const pid = (data.pid || "").trim();
  const sid = (data.sid || "").trim();
  const alias = (data.alias || "").trim();
  const sass = {
    mode: (data.sassMode || data.sass_mode || "").trim(),
    packageId: (data.sassPackage || data.sass_package || "").trim(),
    tier: (data.sassTier || data.sass_tier || data.sassLevel || data.sass_level || "").trim(),
    accountId: (data.sassAccountId || data.sass_account_id || data.sassCompanyId || data.sass_company_id || "").trim(),
    accountName: (data.sassAccountName || data.sass_account_name || data.sassCompanyName || data.sass_company_name || "").trim(),
    businessId: (data.sassBusinessId || data.sass_business_id || data.sassOrgId || data.sass_org_id || "").trim(),
    businessName: (data.sassBusinessName || data.sass_business_name || data.sassOrgName || data.sass_org_name || "").trim(),
    userId: (data.sassUserId || data.sass_user_id || data.sassUsername || data.sass_username || "").trim(),
    customerId: (data.sassCustomerId || data.sass_customer_id || data.sassMemberId || data.sass_member_id || "").trim(),
    email: (data.sassEmail || data.sass_email || "").trim(),
    displayName: (data.sassDisplayName || data.sass_display_name || data.sassName || data.sass_name || "").trim(),
    role: (data.sassRole || data.sass_role || "").trim(),
    signature: (data.sassSignature || data.sass_signature || data.sassSig || data.sass_sig || "").trim(),
  };
  const biz = {
    mode: (data.bizMode || data.biz_mode || "").trim(),
    packageId: (data.bizPackage || data.biz_package || "").trim(),
    tier: (data.bizTier || data.biz_tier || data.bizLevel || data.biz_level || "").trim(),
    accountId: (data.bizAccountId || data.biz_account_id || data.bizCompanyId || data.biz_company_id || "").trim(),
    accountName: (data.bizAccountName || data.biz_account_name || data.bizCompanyName || data.biz_company_name || "").trim(),
    businessId: (data.bizBusinessId || data.biz_business_id || data.bizOrgId || data.biz_org_id || "").trim(),
    businessName: (data.bizBusinessName || data.biz_business_name || data.bizOrgName || data.biz_org_name || "").trim(),
    userId: (data.bizUserId || data.biz_user_id || data.bizUsername || data.biz_username || "").trim(),
    customerId: (data.bizCustomerId || data.biz_customer_id || data.bizMemberId || data.biz_member_id || "").trim(),
    email: (data.bizEmail || data.biz_email || "").trim(),
    displayName: (data.bizDisplayName || data.biz_display_name || data.bizName || data.biz_name || "").trim(),
    role: (data.bizRole || data.biz_role || "").trim(),
    signature: (data.bizSignature || data.biz_signature || data.bizSig || data.biz_sig || "").trim(),
  };
  const devMode = /^(1|true|yes|on)$/i.test(String(data.dev || "").trim());
  const revRaw = (data.rev || data.cacheBust || "").trim();
  const identifierKey = (data.identifierKey || data.identifier_key || "").trim();
  const cmsBaseRaw = (data.cms || data.cmsBase || data.cms_base || "").trim();
  const cmsBase = (cmsBaseRaw || "https://account.gotchat.ai").replace(/\/+$/, "");
  let pluginRepoApiBase = (data.pluginRepoApiBase || data.pluginRepoApi || "").trim();

  function isEnabledDataValue(value) {
    return /^(1|true|yes|on|show|visible)$/i.test(String(value || "").trim());
  }

  const height = String(data.height || "80vh").trim() || "80vh";
  const topbarMode = String(data.topbar || data.header || "").trim().toLowerCase();
  const hideTopbar =
    isEnabledDataValue(data.hideTopbar || data.hideHeader) ||
    /^(hide|hidden|off|false|0|no|none)$/i.test(topbarMode);
  const showTopbar =
    isEnabledDataValue(data.showTopbar || data.showHeader) ||
    /^(show|visible|on|true|1|yes)$/i.test(topbarMode);
  const shouldHideTopbar = hideTopbar && !showTopbar;
  const pageJsonRetrieverPreload = /^(1|true|yes|on)$/i.test(
    String(data.pageJsonRetrieverPreload || data.pageJsonPreload || data.pjsonrPreload || "").trim(),
  );
  const pageJsonRetrieverAutoEnable = /^(1|true|yes|on)$/i.test(
    String(data.pageJsonRetrieverEnabled || data.pjsonrEnabled || "").trim(),
  );
  const pageJsonRetrieverMaxText = (() => {
    const n = parseInt(String(data.pageJsonRetrieverMaxText || data.pjsonrMaxText || "").trim(), 10);
    return Number.isFinite(n) && n > 1000 ? n : 18000;
  })();
  const pageJsonRetrieverMaxBytes = (() => {
    const n = parseInt(String(data.pageJsonRetrieverMaxBytes || data.pjsonrMaxBytes || "").trim(), 10);
    return Number.isFinite(n) && n > 10000 ? n : 350000;
  })();

  const WRAP_ID = "llm-chat-js-embed";
  // Overlay mount for popovers/modals that should not be constrained by the
  // embed panel (e.g. when the embed is a right-side slide-over).
  const PORTAL_ID = "llm-chat-js-portal";
  const OPEN_CLOSE_GUARD_MS = 700;
  const pageScrollLock = { locked: false, scrollY: 0, body: null, html: null };
  const assetRev = (() => {
    const value = String(revRaw || "").trim();
    if (!value && devMode) return String(Date.now());
    if (!value) return "";
    const lower = value.toLowerCase();
    if (lower === "timestamp" || lower === "now" || lower === "1" || lower === "true") {
      return String(Date.now());
    }
    return value;
  })();
  const assetFetchCache = assetRev ? "no-store" : "force-cache";

  function readStoredChatState() {
    try {
      const raw = localStorage.getItem("llmloader2.chat_js.state");
      if (!raw) return null;
      const obj = JSON.parse(raw);
      return obj && typeof obj === "object" ? obj : null;
    } catch (_err) {
      return null;
    }
  }

  function shouldInstallJsonSniffer() {
    if (pageJsonRetrieverPreload) return true;
    const st = readStoredChatState();
    const prefs = st?.pluginPrefs || st?.plugin_prefs || null;
    if (!prefs || typeof prefs !== "object") return false;
    const enabled = prefs.enabled && typeof prefs.enabled === "object" ? prefs.enabled : {};
    const preloads = prefs.preloads && typeof prefs.preloads === "object" ? prefs.preloads : {};
    const list = Array.isArray(preloads.json_sniffer) ? preloads.json_sniffer : [];
    for (const id of list) {
      const key = String(id || "").trim();
      if (!key) continue;
      if (enabled[key] === false) continue;
      return true;
    }
    return false;
  }

  function installPageJsonRetrieverPreSniffer() {
    if (!shouldInstallJsonSniffer()) return;
    const g = window;
    if (g.__CHAT_JS_PAGE_JSON_RETRIEVER_PREBUFFER?.installed) {
      try {
        const pre = g.__CHAT_JS_PAGE_JSON_RETRIEVER_PREBUFFER;
        pre.enabled = Boolean(pageJsonRetrieverAutoEnable || shouldInstallJsonSniffer());
        pre.maxText = pageJsonRetrieverMaxText;
        pre.maxBytes = pageJsonRetrieverMaxBytes;
        pre.internal = pre.internal || {};
        pre.internal.uiOrigin = toOrigin(uiOrigin) || pre.internal.uiOrigin;
        pre.internal.serverOrigin = toOrigin(server) || pre.internal.serverOrigin;
        pre.internal.cmsOrigin = toOrigin(cmsBase) || pre.internal.cmsOrigin;
        pre.internal.pluginRepoOrigin = toOrigin(pluginRepoApiBase) || pre.internal.pluginRepoOrigin;
        pre.internal.hostServiceOrigin = toOrigin(hostService) || pre.internal.hostServiceOrigin;
      } catch (_err) {}
      return;
    }

    const toOrigin = (value) => {
      const raw = String(value || "").trim();
      if (!raw) return "";
      try {
        return new URL(raw, window.location.href).origin;
      } catch (_err) {
        return "";
      }
    };
    const internal = {
      uiOrigin: toOrigin(uiOrigin),
      serverOrigin: toOrigin(server),
      cmsOrigin: toOrigin(cmsBase),
      pluginRepoOrigin: toOrigin(pluginRepoApiBase),
      hostServiceOrigin: toOrigin(hostService),
    };

    const pre = {
      version: 1,
      installed: true,
      enabled: Boolean(pageJsonRetrieverAutoEnable || shouldInstallJsonSniffer()),
      maxText: pageJsonRetrieverMaxText,
      maxBytes: pageJsonRetrieverMaxBytes,
      internal,
      events: [],
    };
    g.__CHAT_JS_PAGE_JSON_RETRIEVER_PREBUFFER = pre;

    const shouldSkipUrl = (u) => {
      if (!u) return true;
      const raw = String(u.href || u).trim();
      if (!raw) return true;
      const low = raw.toLowerCase();
      if (low.startsWith("data:") || low.startsWith("blob:")) return true;
      return false;
    };
    const isInternalUrl = (u) => {
      try {
        const url = u instanceof URL ? u : new URL(String(u || ""), window.location.href);
        const pathname = String(url.pathname || "");
        if (internal.uiOrigin && url.origin === internal.uiOrigin) return true;
        if (internal.pluginRepoOrigin && url.origin === internal.pluginRepoOrigin) return true;
        if (internal.hostServiceOrigin && url.origin === internal.hostServiceOrigin) return true;
        if (internal.cmsOrigin && url.origin === internal.cmsOrigin) return true;
        if (internal.serverOrigin && url.origin === internal.serverOrigin) {
          if (pathname.startsWith("/v1/") || pathname.startsWith("/uploads/") || pathname.startsWith("/gui_js/")) return true;
        }
        if (pathname.endsWith("/embed.js") || pathname.endsWith("/chat_js.js") || pathname.endsWith("/chat_js.htm")) return true;
        return false;
      } catch (_err) {
        return false;
      }
    };
    const isJsonLike = (contentType, url) => {
      const ct = String(contentType || "").toLowerCase();
      if (ct.includes("application/json") || ct.includes("+json")) return true;
      try {
        return String(url?.pathname || "").toLowerCase().endsWith(".json");
      } catch (_err) {
        return false;
      }
    };
    const looksLikeJsonText = (text) => {
      const t = String(text || "").trim();
      if (!t) return false;
      if ((t.startsWith("{") && t.endsWith("}")) || (t.startsWith("[") && t.endsWith("]"))) return true;
      return t.startsWith("{") || t.startsWith("[");
    };
    const truncate = (text) => {
      const s = String(text || "");
      if (s.length <= pre.maxText) return s;
      return `${s.slice(0, pre.maxText)}\n…(truncated ${s.length - pre.maxText} chars)`;
    };
    const capture = (url, details) => {
      if (!pre.enabled) return;
      if (shouldSkipUrl(url) || isInternalUrl(url)) return;
      const urlBase = (() => {
        try {
          const u = new URL(window.location.href);
          return `${u.origin}${u.pathname}`;
        } catch (_err) {
          return String(window.location?.href || "");
        }
      })();
      pre.events.push({
        ts: Date.now(),
        page: { title: String(document.title || "").trim(), urlBase },
        jsonUrl: (() => {
          try {
            const u = new URL(String(url), window.location.href);
            u.hash = "";
            return u.toString();
          } catch (_err) {
            return String(url || "");
          }
        })(),
        ...details,
      });
      if (pre.events.length > 250) pre.events.splice(0, pre.events.length - 250);
    };

    const origFetch = typeof window.fetch === "function" ? window.fetch.bind(window) : null;
    if (origFetch) {
      window.fetch = async (...args) => {
        const resp = await origFetch(...args);
        try {
          if (!pre.enabled) return resp;
          const input = args[0];
          let url = null;
          if (typeof input === "string") url = new URL(input, window.location.href);
          else if (input && typeof input === "object" && input.url) url = new URL(String(input.url || ""), window.location.href);
          if (!url || shouldSkipUrl(url) || isInternalUrl(url)) return resp;
          const ct = resp.headers?.get?.("content-type") || "";
          const declaredBytes = parseInt(resp.headers?.get?.("content-length") || "0", 10) || 0;
          if (declaredBytes && declaredBytes > pre.maxBytes) {
            capture(url, { status: resp.status, contentType: ct, bytes: declaredBytes, error: "Skipped: too large", dataText: "" });
            return resp;
          }
          if (isJsonLike(ct, url)) {
            const json = await resp.clone().json();
            const raw = JSON.stringify(json, null, 2);
            capture(url, { status: resp.status, contentType: ct, bytes: raw.length, error: "", dataText: truncate(raw) });
            return resp;
          }
          // Fallback for JSON handlers returning the wrong content-type.
          const text = await resp.clone().text();
          if (!looksLikeJsonText(text)) return resp;
          if (text.length > pre.maxBytes) {
            capture(url, { status: resp.status, contentType: ct, bytes: text.length, error: "Skipped: too large", dataText: "" });
            return resp;
          }
          const obj = JSON.parse(text);
          const raw = JSON.stringify(obj, null, 2);
          capture(url, { status: resp.status, contentType: ct, bytes: raw.length, error: "", dataText: truncate(raw) });
        } catch (_err) {}
        return resp;
      };
      pre._origFetch = origFetch;
    }

    const XHR = window.XMLHttpRequest;
    if (XHR && XHR.prototype && typeof XHR.prototype.open === "function" && typeof XHR.prototype.send === "function") {
      const origOpen = XHR.prototype.open;
      const origSend = XHR.prototype.send;
      XHR.prototype.open = function (...args) {
        try {
          this.__pjsonr_pre_url = args[1];
        } catch (_err) {}
        return origOpen.apply(this, args);
      };
      XHR.prototype.send = function (...args) {
        try {
          if (pre.enabled) {
            this.addEventListener(
              "load",
              () => {
                try {
                  const rawUrl = this.__pjsonr_pre_url;
                  if (!rawUrl) return;
                  const url = new URL(String(rawUrl), window.location.href);
                  if (shouldSkipUrl(url) || isInternalUrl(url)) return;
                  const ct = String(this.getResponseHeader?.("content-type") || "");
                  const responseType = String(this.responseType || "").toLowerCase();
                  if (responseType === "json" && this.response && typeof this.response === "object") {
                    const raw = JSON.stringify(this.response, null, 2);
                    if (raw.length > pre.maxBytes) {
                      capture(url, { status: this.status || 0, contentType: ct, bytes: raw.length, error: "Skipped: too large", dataText: "" });
                      return;
                    }
                    capture(url, { status: this.status || 0, contentType: ct, bytes: raw.length, error: "", dataText: truncate(raw) });
                    return;
                  }

                  const text = typeof this.responseText === "string" ? this.responseText : "";
                  const jsonish = isJsonLike(ct, url) || looksLikeJsonText(text);
                  if (!jsonish) return;
                  if (!text) return;
                  if (text.length > pre.maxBytes) {
                    capture(url, { status: this.status || 0, contentType: ct, bytes: text.length, error: "Skipped: too large", dataText: "" });
                    return;
                  }
                  const obj = JSON.parse(text);
                  const raw = JSON.stringify(obj, null, 2);
                  capture(url, { status: this.status || 0, contentType: ct, bytes: raw.length, error: "", dataText: truncate(raw) });
                } catch (_err) {}
              },
              { once: true },
            );
          }
        } catch (_err) {}
        return origSend.apply(this, args);
      };
      pre._origXhrOpen = origOpen;
      pre._origXhrSend = origSend;
    }
  }

  function resolveUiAssetUrl(path) {
    const url = new URL(path, uiBase);
    if (assetRev) url.searchParams.set("rev", assetRev);
    return url.toString();
  }

  function setStatus(text) {
    const host = getEmbedTarget();
    let el = host.querySelector(".llm-chat-js-embed-status");
    if (!el) {
      el = document.createElement("div");
      el.className = "llm-chat-js-embed-status";
      el.style.fontFamily = "system-ui, -apple-system, Segoe UI, sans-serif";
      el.style.fontSize = "14px";
      el.style.color = "#444";
      el.style.padding = "10px 12px";
      el.style.border = "1px solid rgba(0,0,0,0.12)";
      el.style.borderRadius = "10px";
      el.style.background = "rgba(255,255,255,0.85)";
      el.style.maxWidth = "720px";
      host.appendChild(el);
    }
    const value = String(text || "").trim();
    el.textContent = value;
    el.style.display = value ? "" : "none";
  }

  function splitSelectorList(selText) {
    const out = [];
    let cur = "";
    let depth = 0;
    let inStr = null;
    for (let i = 0; i < selText.length; i++) {
      const ch = selText[i];
      if (inStr) {
        cur += ch;
        if (ch === inStr && selText[i - 1] !== "\\") inStr = null;
        continue;
      }
      if (ch === '"' || ch === "'") {
        inStr = ch;
        cur += ch;
        continue;
      }
      if (ch === "(" || ch === "[" ) depth++;
      if (ch === ")" || ch === "]" ) depth = Math.max(0, depth - 1);
      if (ch === "," && depth === 0) {
        out.push(cur.trim());
        cur = "";
        continue;
      }
      cur += ch;
    }
    if (cur.trim()) out.push(cur.trim());
    return out;
  }

  function prefixSelector(sel, scope) {
    const s = String(sel || "").trim();
    if (!s) return "";
    if (s.startsWith("@")) return s;
    // Root / page selectors become the wrapper itself.
    if (s === ":root" || s === "html" || s === "body") return scope;
    if (s === "html,body" || s === "html, body") return scope;
    // Avoid double prefix.
    if (s.startsWith(scope)) return s;
    return `${scope} ${s}`;
  }

  function prefixSelectors(selText, scope) {
    const parts = splitSelectorList(selText);
    const pref = [];
    const seen = new Set();
    parts.forEach((s) => {
      const p = prefixSelector(s, scope).trim();
      if (!p) return;
      if (seen.has(p)) return;
      seen.add(p);
      pref.push(p);
    });
    return pref.join(", ");
  }

  function findMatchingBrace(text, openIdx) {
    let depth = 0;
    let inStr = null;
    for (let i = openIdx; i < text.length; i++) {
      const ch = text[i];
      if (inStr) {
        if (ch === inStr && text[i - 1] !== "\\") inStr = null;
        continue;
      }
      if (ch === '"' || ch === "'") {
        inStr = ch;
        continue;
      }
      if (ch === "{") depth++;
      else if (ch === "}") {
        depth--;
        if (depth === 0) return i;
      }
    }
    return -1;
  }

  function prefixCss(cssText, scope) {
    let i = 0;
    let out = "";
    const text = String(cssText || "");
    while (i < text.length) {
      // Skip whitespace.
      while (i < text.length && /\s/.test(text[i])) {
        out += text[i];
        i++;
      }
      if (i >= text.length) break;

      // Comments.
      if (text[i] === "/" && text[i + 1] === "*") {
        const end = text.indexOf("*/", i + 2);
        if (end === -1) {
          out += text.slice(i);
          break;
        }
        out += text.slice(i, end + 2);
        i = end + 2;
        continue;
      }

      // At-rule.
      if (text[i] === "@") {
        let j = i;
        while (j < text.length && text[j] !== "{" && text[j] !== ";") j++;
        if (j >= text.length) {
          out += text.slice(i);
          break;
        }
        const header = text.slice(i, j).trim();
        if (text[j] === ";") {
          out += text.slice(i, j + 1);
          i = j + 1;
          continue;
        }
        const end = findMatchingBrace(text, j);
        if (end === -1) {
          out += text.slice(i);
          break;
        }
        const inner = text.slice(j + 1, end);
        if (/^@keyframes/i.test(header) || /^@font-face/i.test(header)) {
          out += text.slice(i, end + 1);
        } else {
          out += `${header}{${prefixCss(inner, scope)}}`;
        }
        i = end + 1;
        continue;
      }

      // Normal rule.
      let j = i;
      while (j < text.length && text[j] !== "{") j++;
      if (j >= text.length) {
        out += text.slice(i);
        break;
      }
      const selText = text.slice(i, j).trim();
      const end = findMatchingBrace(text, j);
      if (end === -1) {
        out += text.slice(i);
        break;
      }
      const body = text.slice(j + 1, end);
      const prefSel = prefixSelectors(selText, scope);
      out += `${prefSel}{${body}}`;
      i = end + 1;
    }
    return out;
  }

  async function ensureFonts() {
    const existing = document.querySelector('link[data-llm-chat-embed-fonts="1"]');
    if (existing) return;
    const pre1 = document.createElement("link");
    pre1.rel = "preconnect";
    pre1.href = "https://fonts.googleapis.com";
    pre1.setAttribute("data-llm-chat-embed-fonts", "1");
    const pre2 = document.createElement("link");
    pre2.rel = "preconnect";
    pre2.href = "https://fonts.gstatic.com";
    pre2.crossOrigin = "anonymous";
    pre2.setAttribute("data-llm-chat-embed-fonts", "1");
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href =
      "https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,700&family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap";
    link.setAttribute("data-llm-chat-embed-fonts", "1");
    document.head.appendChild(pre1);
    document.head.appendChild(pre2);
    document.head.appendChild(link);
  }

  async function resolveFromCms() {
    if (!identifierKey || !cmsBase) return;
    try {
      const isHostServiceUrl = (u) => {
        const s = String(u || "").trim().toLowerCase();
        if (!s) return false;
        // Common host-service port used by llmloader2 for host integrations.
        if (s.includes(":8765")) return true;
        if (s.includes("hostservices")) return true;
        return false;
      };

      // 1) Host mappings (per-hostname) is the most precise source of truth.
      //    This allows us to resolve "the public URL that maps to llmloader2:8000"
      //    even when there are multiple server hostnames.
      try {
        const hmUrl = `${cmsBase}/api/docker/host-mappings?key=${encodeURIComponent(identifierKey)}`;
        const hmResp = await fetch(hmUrl, { credentials: "omit", mode: "cors", cache: "no-cache" });
        if (hmResp.ok) {
          const hmPayload = (await hmResp.json()) || {};
          const list = hmPayload.data || hmPayload.Data || [];
          const items = Array.isArray(list) ? list : [];

          const toStr = (v) => String(v == null ? "" : v).trim();
          const lower = (v) => toStr(v).toLowerCase();
          const trimSlash = (u) => toStr(u).replace(/\/+$/, "");
          const asNum = (v) => {
            const n = Number(v);
            return Number.isFinite(n) ? n : 0;
          };
          const parseUpdated = (v) => {
            const s = toStr(v);
            const t = Date.parse(s);
            return Number.isFinite(t) ? t : 0;
          };

          const looksLikeService = (svc, host, port) => {
            const s = lower(svc);
            const h = lower(host);
            const p = String(port || "");
            if (!s) return false;
            if (h && s.includes(h) && p && s.includes(p)) return true;
            // Common "http://llmloader2:8000" / "llmloader2:8000" patterns.
            if (h && p && s.includes(`${h}:${p}`)) return true;
            return false;
          };

          const pickBest = (arr, preferHostnameIncludes) => {
            const pref = String(preferHostnameIncludes || "").toLowerCase();
            const sorted = arr
              .slice()
              .sort((a, b) => (parseUpdated(b.updatedAt) - parseUpdated(a.updatedAt)));
            if (pref) {
              const hit = sorted.find((m) => lower(m.hostname).includes(pref));
              if (hit) return hit;
            }
            return sorted[0] || null;
          };

          // Resolve chat server public URL: prefer a hostname that maps to llmloader2:8000.
          const serverAll = items.filter((m) => lower(m.serviceType) === "server");
          const serverCandidates = serverAll.filter((m) => {
            const st = lower(m.serviceType);
            if (st !== "server") return false;
            if (lower(m.hostname).includes("hostservices")) return false;
            const lp = asNum(m.localPort);
            if (lp === 8000) return true;
            if (looksLikeService(m.service, "llmloader2", 8000)) return true;
            return false;
          });
          const server8000 = serverCandidates.filter((m) => asNum(m.localPort) === 8000 || looksLikeService(m.service, "llmloader2", 8000));
          // If we can't confirm the local port, still prefer obvious public hostnames.
          const bestServer =
            pickBest(server8000, "chatserver") ||
            pickBest(serverCandidates, "chatserver") ||
            pickBest(serverAll.filter((m) => lower(m.hostname).includes("chatserver")), "chatserver") ||
            pickBest(serverAll.filter((m) => lower(m.hostname).includes("chat") && !lower(m.hostname).includes("hostservice") && !lower(m.hostname).includes("hostservices")), "chat") ||
            pickBest(serverAll.filter((m) => !lower(m.hostname).includes("hostservice") && !lower(m.hostname).includes("hostservices")), "") ||
            pickBest(serverAll, "");
          const serverUrl = bestServer ? trimSlash(bestServer.publicUrl || `https://${toStr(bestServer.hostname)}`) : "";
          if (serverUrl) {
            server = serverUrl;
          }

          // Resolve host service public URL: prefer a hostname that maps to
          // llmloader2:8765. This service is distinct from the main chat server.
          if (!hostService) {
            const hostSvcCandidates = items.filter((m) => {
              const lp = asNum(m.localPort);
              if (lp === 8765) return true;
              if (looksLikeService(m.service, "llmloader2", 8765)) return true;
              return false;
            });
            const bestHostSvc =
              pickBest(hostSvcCandidates.filter((m) => lower(m.hostname).includes("hostservice")), "hostservice") ||
              pickBest(hostSvcCandidates, "");
            const hostSvcUrl = bestHostSvc ? trimSlash(bestHostSvc.publicUrl || `https://${toStr(bestHostSvc.hostname)}`) : "";
            if (hostSvcUrl) hostService = hostSvcUrl;
          }

          // Resolve GUI JS client service public URL: prefer a hostname that maps
          // to gui_js:8766. This is distinct from the GUI app URL on 8080.
          if (!clientService) {
            const clientSvcCandidates = items.filter((m) => {
              const lp = asNum(m.localPort);
              if (lp === 8766) return true;
              if (looksLikeService(m.service, "gui_js", 8766)) return true;
              return false;
            });
            const bestClientSvc =
              pickBest(clientSvcCandidates.filter((m) => lower(m.hostname).includes("jshostservice")), "jshostservice") ||
              pickBest(clientSvcCandidates.filter((m) => lower(m.hostname).includes("hostservice")), "hostservice") ||
              pickBest(clientSvcCandidates, "");
            const clientSvcUrl = bestClientSvc ? trimSlash(bestClientSvc.publicUrl || `https://${toStr(bestClientSvc.hostname)}`) : "";
            if (clientSvcUrl) clientService = clientSvcUrl;
          }

          // Resolve plugin repo public API base: prefer hostname that maps to host.docker.internal:5000.
          if (!pluginRepoApiBase) {
            const repoCandidates = items.filter((m) => {
              const st = lower(m.serviceType);
              if (st !== "plugin_repo") return false;
              const lp = asNum(m.localPort);
              if (lp === 5000) return true;
              if (looksLikeService(m.service, "host.docker.internal", 5000)) return true;
              return false;
            });
            const bestRepo = pickBest(repoCandidates, "");
            const repoUrl = bestRepo ? trimSlash(bestRepo.publicUrl || `https://${toStr(bestRepo.hostname)}`) : "";
            if (repoUrl) pluginRepoApiBase = `${repoUrl}/api`;
          }
        }
      } catch (_err) {}

      // 2) Fallback: service-level "public-urls" resolver.
      const url = `${cmsBase}/api/docker/public-urls?key=${encodeURIComponent(identifierKey)}`;
      const resp = await fetch(url, { credentials: "omit", mode: "cors", cache: "no-cache" });
      if (!resp.ok) return;
      const payload = (await resp.json()) || {};
      const data = payload.data || payload.Data || {};
      const chatServerUrl = (data.chatServerUrl || data.ChatServerUrl || data.serverUrl || data.ServerUrl || "").trim();
      const hostServiceUrl = (data.hostServiceUrl || data.HostServiceUrl || "").trim();
      const clientServiceUrl = (data.clientServiceUrl || data.ClientServiceUrl || "").trim();
      const repoApi = (data.pluginRepoApi || data.PluginRepoApi || "").trim();
      // If server is still pointing at the host-service (8765), prefer the real chat server.
      if (chatServerUrl && (!server || isHostServiceUrl(server))) {
        server = chatServerUrl.replace(/\/+$/, "");
      }
      if (hostServiceUrl && !hostService) {
        hostService = hostServiceUrl.replace(/\/+$/, "");
      }
      if (clientServiceUrl && !clientService) {
        clientService = clientServiceUrl.replace(/\/+$/, "");
      }
      if (repoApi && !pluginRepoApiBase) {
        pluginRepoApiBase = repoApi.replace(/\/+$/, "");
      }
    } catch (_err) {
      // Best-effort only.
    }

    // The GUI server exposes the GUI JS client service through /v1/client/*.
    // Remote embeds should use that same-origin proxy when CMS has no explicit
    // client-service public URL instead of guessing a public :8766 endpoint.
    if (!clientService && server) {
      try {
        const serverUrl = new URL(server);
        if (!["localhost", "127.0.0.1", "::1"].includes(serverUrl.hostname.toLowerCase())) {
          clientService = server.replace(/\/+$/, "");
        }
      } catch (_err) {}
    }
  }

  async function ensureScopedCss() {
    const styleId = "llm-chat-js-embed-style";
    if (document.getElementById(styleId)) return;
    const cssUrl = resolveUiAssetUrl("chat_js.css");
    const resp = await fetch(cssUrl, { credentials: "omit", cache: assetFetchCache });
    if (!resp.ok) throw new Error(`Failed to load CSS (${resp.status})`);
    const css = await resp.text();
    // Scope chat_js.css under both the embed mount and an overlay "portal"
    // mounted on <body>. This lets plugins render large modals/popovers outside
    // the embedded panel while still inheriting the chat theme CSS variables.
    const scoped = `${prefixCss(css, `#${WRAP_ID}`)}\n\n${prefixCss(css, `#${PORTAL_ID}`)}\n\n#${WRAP_ID} {\n  font-family: initial !important;\n}\n#${WRAP_ID} > #app {\n  font-family: \"Space Grotesk\", \"Segoe UI\", sans-serif;\n}\n#${WRAP_ID} .body {\n  padding: 7px 0px 0px !important;\n  align-items: stretch !important;\n  overflow: visible !important;\n}\n#${WRAP_ID} .chat {\n  width: 100% !important;\n  height: 100% !important;\n  min-height: 0 !important;\n  flex: 1 1 auto !important;\n  border-left: none !important;\n  border-right: none !important;\n  padding: 10px !important;\n  gap: 10px !important;\n}\n#${WRAP_ID} .chat,\n#${WRAP_ID} .chat-toolbar,\n#${WRAP_ID} .composer,\n#${WRAP_ID} .transcript-bar-shell {\n  overflow: visible !important;\n}\n#${WRAP_ID} .chat,\n#${WRAP_ID} .topbar,\n#${WRAP_ID} .topbar-actions,\n#${WRAP_ID} .chat-toolbar,\n#${WRAP_ID} .composer {\n  position: relative !important;\n}\n#${WRAP_ID} .chat,\n#${WRAP_ID} .topbar,\n#${WRAP_ID} .topbar-actions {\n  isolation: isolate !important;\n}\n#${WRAP_ID} .topbar-actions {\n  z-index: 80 !important;\n}\n#${WRAP_ID} .chat-toolbar {\n  z-index: 30 !important;\n}\n#${WRAP_ID} .composer {\n  z-index: 20 !important;\n}\n#${WRAP_ID} .toolbar-select,\n#${WRAP_ID} .status-menu,\n#${WRAP_ID} .menu-btn,\n#${WRAP_ID} .menu-group {\n  position: relative !important;\n}\n#${WRAP_ID} .toolbar-select,\n#${WRAP_ID} .status-menu {\n  z-index: 85 !important;\n}\n#${WRAP_ID} .menu-btn,\n#${WRAP_ID} .menu-group {\n  z-index: 90 !important;\n}\n#${WRAP_ID} .toolbar-dropdown,\n#${WRAP_ID} .status-dropdown,\n#${WRAP_ID} .menu-dropdown,\n#${WRAP_ID} .menu-sub {\n  background: var(--panel) !important;\n  z-index: 95 !important;\n}\n#${WRAP_ID} .transcript-bar-shell {\n  position: relative !important;\n  z-index: 0 !important;\n  display: flex !important;\n  flex-direction: column !important;\n  align-items: stretch !important;\n  gap: 0 !important;\n}\n#${WRAP_ID} .transcript-bar-shell-top {\n  padding-bottom: 13px !important;\n  margin-top: -9px !important;\n}\n#${WRAP_ID} .transcript-bar-shell-bottom {\n  padding-top: 13px !important;\n  margin-bottom: -9px !important;\n}\n#${WRAP_ID} .transcript-bar-shell.hidden {\n  display: flex !important;\n}\n#${WRAP_ID} .transcript-bar-shell.hidden:not(.is-open) .transcript-bar {\n  max-height: 0 !important;\n  opacity: 0 !important;\n  padding-top: 0 !important;\n  padding-bottom: 0 !important;\n  border-width: 0 !important;\n  pointer-events: none !important;\n}\n#${WRAP_ID} .transcript-bar-shell-top.hidden:not(.is-open) .transcript-bar {\n  transform: translateY(-8px) !important;\n}\n#${WRAP_ID} .transcript-bar-shell-bottom.hidden:not(.is-open) .transcript-bar {\n  transform: translateY(8px) !important;\n}\n#${WRAP_ID} .transcript-bar {\n  overflow-x: auto !important;\n  flex-wrap: nowrap !important;\n  justify-content: flex-start !important;\n  -webkit-overflow-scrolling: touch;\n}\n#${WRAP_ID} .transcript-bar .bar-left,\n#${WRAP_ID} .transcript-bar .bar-right,\n#${WRAP_ID} .transcript-bar .media-upload-bar,\n#${WRAP_ID} .transcript-bar .media-upload-list {\n  flex-wrap: nowrap !important;\n}\n#${WRAP_ID} .transcript-bar-notch {\n  -webkit-appearance: none !important;\n  appearance: none !important;\n  position: absolute !important;\n  left: 50% !important;\n  width: 22px !important;\n  height: 13px !important;\n  padding: 0 !important;\n  margin: 0 !important;\n  display: flex !important;\n  align-items: center !important;\n  justify-content: center !important;\n  border: 1px solid var(--border) !important;\n  background: rgba(var(--panel-rgb), 0.92) !important;\n  color: var(--muted) !important;\n  cursor: pointer !important;\n  z-index: 0 !important;\n  box-shadow: 0 4px 12px rgba(20, 15, 10, 0.08) !important;\n}\n#${WRAP_ID} .transcript-bar-notch svg {\n  width: 8px !important;\n  height: 8px !important;\n  display: block !important;\n  stroke: currentColor !important;\n  stroke-width: 1.8 !important;\n  stroke-linecap: round;\n  stroke-linejoin: round;\n  fill: none !important;\n}\n#${WRAP_ID} .transcript-bar-notch-top {\n  bottom: 0 !important;\n  transform: translateX(-50%) !important;\n  border-top: 0 !important;\n  border-radius: 0 0 8px 8px !important;\n}\n#${WRAP_ID} .transcript-bar-notch-bottom {\n  top: 0 !important;\n  transform: translateX(-50%) !important;\n  border-bottom: 0 !important;\n  border-radius: 8px 8px 0 0 !important;\n}\n\n/* Host CSS guard: if the tools/settings modal is mounted outside the embed wrapper\n   (into the portal on <body>), prevent host modal/button styles from breaking layout. */\n#${PORTAL_ID} #tools-modal .modal-header {\n  display: flex !important;\n  align-items: center !important;\n  justify-content: space-between !important;\n  padding-bottom: 8px !important;\n  position: relative !important;\n}\n#${PORTAL_ID} #tools-modal #modal-close.icon-btn {\n  width: 34px !important;\n  height: 34px !important;\n  display: inline-flex !important;\n  align-items: center !important;\n  justify-content: center !important;\n  padding: 0 !important;\n  line-height: 1 !important;\n  margin: 0 !important;\n  float: none !important;\n  margin-left: auto !important;\n  flex: 0 0 auto !important;\n}\n`;
    const style = document.createElement("style");
    style.id = styleId;
    style.textContent = scoped;
    document.head.appendChild(style);
  }

  function ensureEmbedLayoutOptionCss() {
    const styleId = "llm-chat-js-embed-layout-options";
    if (document.getElementById(styleId)) return;
    const style = document.createElement("style");
    style.id = styleId;
    style.textContent = `
#${WRAP_ID} > #app {
  height: 100% !important;
  min-height: 0 !important;
  display: flex !important;
  flex-direction: column !important;
}
#${WRAP_ID} .body {
  flex: 1 1 auto !important;
  height: auto !important;
  min-height: 0 !important;
  display: flex !important;
  align-items: stretch !important;
  overflow: visible !important;
}
#${WRAP_ID} .chat {
  flex: 1 1 100% !important;
  min-height: 0 !important;
  display: flex !important;
  flex-direction: column !important;
}
#${WRAP_ID} .transcript {
  flex: 1 1 100% !important;
  min-height: 0 !important;
  overflow: auto !important;
}
#${WRAP_ID} .composer {
  flex: 0 0 auto !important;
  margin-top: auto !important;
}
.llm-chat-embed-panel-host[data-llm-chat-inline-panel="1"] {
  display: flex !important;
  flex-direction: column !important;
  height: var(--llm-chat-embed-height, 80vh) !important;
  min-height: 0 !important;
}
.llm-chat-embed-panel-host[data-llm-chat-inline-panel="1"] > [id] {
  flex: 1 1 auto !important;
  height: 100% !important;
  min-height: 0 !important;
  display: flex !important;
  flex-direction: column !important;
}
.llm-chat-embed-panel-host[data-llm-chat-inline-panel="1"] #${WRAP_ID},
.llm-chat-embed-panel-host[data-llm-chat-inline-panel="1"] #${WRAP_ID} > #app,
.llm-chat-embed-panel-host[data-llm-chat-inline-panel="1"] #${WRAP_ID} .body,
.llm-chat-embed-panel-host[data-llm-chat-inline-panel="1"] #${WRAP_ID} .chat {
  flex: 1 1 auto !important;
  height: 100% !important;
  min-height: 0 !important;
}
.llm-chat-embed-panel-host[data-llm-chat-inline-panel="1"] #${WRAP_ID} .chat {
  display: flex !important;
  flex-direction: column !important;
}
.llm-chat-embed-panel-host[data-llm-chat-inline-panel="1"] #${WRAP_ID} .transcript {
  flex: 1 1 auto !important;
  height: auto !important;
  min-height: 0 !important;
}
.llm-chat-embed-panel-host[data-llm-chat-inline-panel="1"] #${WRAP_ID} .composer,
.llm-chat-embed-panel-host[data-llm-chat-inline-panel="1"] #${WRAP_ID} .log-toggle,
.llm-chat-embed-panel-host[data-llm-chat-inline-panel="1"] #${WRAP_ID} .log-panel {
  flex: 0 0 auto !important;
}
#${WRAP_ID}.llm-chat-embed-hide-topbar > #app .topbar {
  display: none !important;
}
#${WRAP_ID}.llm-chat-embed-hide-topbar > #app .body {
  padding-top: 0 !important;
}
    `.trim();
    document.head.appendChild(style);
  }

  function ensurePortal() {
    let portal = document.getElementById(PORTAL_ID);
    if (portal) return portal;
    portal = document.createElement("div");
    portal.id = PORTAL_ID;
    portal.className = "llm-chat-js-portal";
    document.body.appendChild(portal);

    const baseStyleId = "llm-chat-js-portal-base-style";
    if (!document.getElementById(baseStyleId)) {
      const style = document.createElement("style");
      style.id = baseStyleId;
      style.textContent = `
#${PORTAL_ID} {
  position: fixed !important;
  inset: 0 !important;
  /* Must be above the chat panel and above most site UI (Bootstrap modals, etc.). */
  /* Use the same z-layer as the chat panel; since the portal is appended last
     to <body>, it will naturally paint above same-z siblings without risking
     overflow past max z-index values. */
  z-index: var(--llm-chat-z, 2147480000);
  pointer-events: none;
  /* The portal is an overlay host only; keep it visually transparent so it
     doesn't "blank" the host page when we also scope chat_js.css under it. */
  background: transparent !important;
  overflow: visible !important;
  isolation: isolate;
}
#${PORTAL_ID} > * {
  pointer-events: auto;
}
      `.trim();
      document.head.appendChild(style);
    }

    return portal;
  }

  function moveNodeToPortal(node, portal) {
    if (!node || !portal || !(node instanceof Element)) return false;
    if (node.parentElement === portal) return true;
    portal.appendChild(node);
    return true;
  }

  function moveEmbedPluginOverlaysToPortal(portal, root) {
    if (!portal) return 0;
    const scope = root instanceof Element ? root : document;
    let moved = 0;
    const selectors = [".router-modal", ".theme-demo-panel"];
    selectors.forEach((selector) => {
      const nodes = scope.querySelectorAll ? scope.querySelectorAll(selector) : [];
      nodes.forEach((node) => {
        if (moveNodeToPortal(node, portal)) moved += 1;
      });
    });
    return moved;
  }

  function ensurePortalHelpers(portal) {
    if (!portal) return;
    window.__LLM_CHAT_JS_PORTAL_ID = PORTAL_ID;
    window.__LLM_CHAT_JS_PORTAL = portal;
    window.__LLM_CHAT_JS_MOVE_TO_PORTAL = (node) => moveNodeToPortal(node, portal);
    if (portal.__llmChatPortalObserver) return;

    moveEmbedPluginOverlaysToPortal(portal);

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes || []) {
          if (!(node instanceof Element)) continue;
          if (node.matches?.('.router-modal, .theme-demo-panel')) {
            moveNodeToPortal(node, portal);
            continue;
          }
          moveEmbedPluginOverlaysToPortal(portal, node);
        }
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
    portal.__llmChatPortalObserver = observer;
  }

  function ensureWidgetShellStyle() {
    const styleId = "llm-chat-widget-style";
    if (document.getElementById(styleId)) return;
    const style = document.createElement("style");
    style.id = styleId;
    style.textContent = `
:root { --llm-chat-z: 2147480000; }
.llm-chat-launcher {
  position: fixed;
  right: 18px;
  bottom: 18px;
  width: 56px;
  height: 56px;
  border-radius: 18px;
  border: 1px solid rgba(0,0,0,0.10);
  background: radial-gradient(120% 120% at 20% 10%, #ffffff 0%, #eef2ff 40%, #dbeafe 100%);
  box-shadow: 0 16px 40px rgba(0,0,0,0.18);
  color: #0f172a;
  cursor: pointer;
  display: grid;
  place-items: center;
  z-index: var(--llm-chat-z);
  transition: transform 160ms ease, box-shadow 160ms ease;
}
.llm-chat-launcher:hover {
  transform: translateY(-1px);
  box-shadow: 0 18px 46px rgba(0,0,0,0.22);
}
.llm-chat-launcher:active {
  transform: translateY(0px) scale(0.98);
}
.llm-chat-launcher svg {
  width: 28px;
  height: 28px;
}
.llm-chat-overlay {
  position: fixed;
  inset: 0;
  background: rgba(12, 12, 16, 0.38);
  opacity: 0;
  pointer-events: none;
  z-index: calc(var(--llm-chat-z) - 1);
  transition: opacity 240ms ease;
}
.llm-chat-overlay.open {
  opacity: 1;
  pointer-events: auto;
  touch-action: none;
}
.llm-chat-panel {
  position: fixed;
  top: 14px;
  left: auto;
  right: 14px;
  bottom: 14px;
  width: min(460px, calc(100vw - 28px));
  background-image: var(--bg-image, none),
    radial-gradient(circle at 20% 20%, var(--bg-grad-a, #fff9ee) 0%, transparent 55%),
    radial-gradient(circle at 80% 0%, var(--bg-grad-b, #f7e3cc) 0%, transparent 50%),
    linear-gradient(120deg, var(--bg-0, #f4efe6), var(--bg-1, #eadfcd));
  background-size: cover, auto, auto, auto;
  background-position: center center, 0 0, 0 0, 0 0;
  background-repeat: no-repeat, no-repeat, no-repeat, no-repeat;
  backdrop-filter: blur(14px);
  border: 1px solid rgba(15,23,42,0.10);
  border-radius: 26px;
  box-shadow: -18px 18px 54px rgba(15,23,42,0.18);
  transform: translateX(calc(100% + 18px));
  transition: transform 420ms cubic-bezier(.2,.9,.2,1);
  z-index: var(--llm-chat-z);
  display: flex;
  flex-direction: column;
  overflow: visible;
  transition:
    transform 420ms cubic-bezier(.2,.9,.2,1),
    top 280ms cubic-bezier(.22,.88,.24,1),
    right 280ms cubic-bezier(.22,.88,.24,1),
    bottom 280ms cubic-bezier(.22,.88,.24,1),
    left 280ms cubic-bezier(.22,.88,.24,1),
    width 280ms cubic-bezier(.22,.88,.24,1),
    border-radius 220ms ease,
    box-shadow 220ms ease;
}
.llm-chat-panel.open {
  transform: translateX(0);
  overscroll-behavior: contain;
  touch-action: pan-y;
}
.llm-chat-panel.is-expanded {
  top: 0;
  right: 0;
  bottom: 0;
  left: 0;
  width: auto;
  max-width: none;
  border-radius: 0;
  box-shadow: none;
}
.llm-chat-panel-body {
  flex: 1;
  min-height: 0;
  padding: 12px;
  border-radius: 26px;
  background-image: var(--bg-image, none),
    radial-gradient(circle at 20% 20%, var(--bg-grad-a, #fff9ee) 0%, transparent 55%),
    radial-gradient(circle at 80% 0%, var(--bg-grad-b, #f7e3cc) 0%, transparent 50%),
    linear-gradient(120deg, var(--bg-0, #f4efe6), var(--bg-1, #eadfcd));
  background-size: cover, auto, auto, auto;
  background-position: center center, 0 0, 0 0, 0 0;
  background-repeat: no-repeat, no-repeat, no-repeat, no-repeat;
  overflow: visible;
  overscroll-behavior: contain;
  touch-action: pan-y;
}
.llm-chat-panel.is-expanded .llm-chat-panel-body {
  padding: 0;
  border-radius: 0;
}
#llm-chat-js {
  width: 100%;
  height: 100%;
  min-height: 0;
  overscroll-behavior: contain;
}
.llm-chat-embed-panel-host #${WRAP_ID} {
  height: 100% !important;
  min-height: 0 !important;
  border: 0 !important;
  border-radius: 22px !important;
  box-shadow: 0 12px 34px rgba(15, 23, 42, 0.10) !important;
  background-image: var(--bg-image, none),
    radial-gradient(circle at 20% 20%, var(--bg-grad-a, #fff9ee) 0%, transparent 55%),
    radial-gradient(circle at 80% 0%, var(--bg-grad-b, #f7e3cc) 0%, transparent 50%),
    linear-gradient(120deg, var(--bg-0, #f4efe6), var(--bg-1, #eadfcd)) !important;
  background-size: cover, auto, auto, auto !important;
  background-position: center center, 0 0, 0 0, 0 0 !important;
  background-repeat: no-repeat, no-repeat, no-repeat, no-repeat !important;
}
.llm-chat-embed-panel-host #${WRAP_ID} > #app {
  height: 100% !important;
  min-height: 0 !important;
  border-radius: 22px !important;
  overflow: visible !important;
  overscroll-behavior: contain !important;
}
.llm-chat-embed-panel-host #${WRAP_ID} .body {
  flex: 1 1 auto !important;
  height: auto !important;
  min-height: 0 !important;
  align-items: stretch !important;
  overscroll-behavior: contain !important;
}
.llm-chat-embed-panel-host #${WRAP_ID} .chat {
  flex: 1 1 auto !important;
  height: auto !important;
  min-height: 0 !important;
  max-width: none !important;
  width: 100% !important;
  overscroll-behavior: contain !important;
}
.llm-chat-embed-panel-host #${WRAP_ID} .body,
.llm-chat-embed-panel-host #${WRAP_ID} .chat,
.llm-chat-embed-panel-host #${WRAP_ID} .chat-toolbar,
.llm-chat-embed-panel-host #${WRAP_ID} .composer,
.llm-chat-embed-panel-host #${WRAP_ID} .transcript-bar-shell {
  overflow: visible !important;
}
.llm-chat-embed-panel-host.is-expanded #${WRAP_ID} {
  border-radius: 0 !important;
  box-shadow: none !important;
}
.llm-chat-embed-panel-host.is-expanded #${WRAP_ID} > #app {
  border-radius: 0 !important;
  position: relative !important;
}
.llm-chat-embed-panel-host.is-expanded #${WRAP_ID} .topbar {
  position: absolute !important;
  inset: 0 0 auto 0 !important;
  overflow: visible !important;
  z-index: 120 !important;
  transition: transform 320ms cubic-bezier(.22,.88,.24,1), box-shadow 220ms ease !important;
}
.llm-chat-embed-panel-host.is-expanded #${WRAP_ID} .body {
  padding: 84px 0 0 !important;
  transition: padding-top 320ms cubic-bezier(.22,.88,.24,1) !important;
}
.llm-chat-embed-panel-host.is-expanded #${WRAP_ID} > #app.llm-chat-embed-topbar-collapsed .topbar {
  transform: translateY(calc(-100% + 16px)) !important;
}
.llm-chat-embed-panel-host.is-expanded #${WRAP_ID} > #app.llm-chat-embed-topbar-collapsed .body {
  padding: 16px 0 0 !important;
}
.llm-chat-embed-panel-host.is-expanded #${WRAP_ID} .chat {
  border-radius: 0 !important;
  box-shadow: none !important;
  max-width: none !important;
}
.llm-chat-embed-panel-host.is-expanded #${WRAP_ID} .composer {
  margin-top: auto !important;
  margin-right: 0 !important;
  margin-bottom: 0 !important;
  margin-left: 0 !important;
  padding: 10px 16px max(10px, env(safe-area-inset-bottom)) !important;
  border-radius: 0 !important;
  background: rgba(var(--panel-rgb), 0.96) !important;
  border-top: 1px solid var(--border) !important;
}
    `.trim();
    document.head.appendChild(style);
  }

  function ensureEmbedChromeStyle() {
    const styleId = "llm-chat-js-embed-chrome-style";
    if (document.getElementById(styleId)) return;
    const style = document.createElement("style");
    style.id = styleId;
    style.textContent = `
.llm-chat-embed-panel-host {
  overflow: visible !important;
}
.llm-chat-embed-panel-host > .llm-chat-embed-controls {
  position: absolute;
  top: -12px;
  right: -12px;
  display: flex;
  align-items: center;
  gap: 10px;
  z-index: 220;
  overflow: visible !important;
}
.llm-chat-embed-panel-host > .llm-chat-embed-controls > .llm-chat-embed-btn {
  position: absolute;
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(255,255,255,0.24);
  background: rgba(15,23,42,0.78);
  color: #ffffff;
  border-radius: 999px;
  padding: 0;
  cursor: pointer;
  font-family: system-ui, -apple-system, Segoe UI, sans-serif;
  font-size: 20px;
  font-weight: 700;
  line-height: 1;
  text-align: center;
  box-shadow: 0 12px 28px rgba(15,23,42,0.28);
  transition: transform 160ms ease, box-shadow 160ms ease, background 160ms ease, opacity 140ms ease;
  z-index: 221;
}
.llm-chat-embed-panel-host > .llm-chat-embed-controls > .llm-chat-embed-btn {
  position: relative;
}
.llm-chat-embed-panel-host > .llm-chat-embed-controls > .llm-chat-embed-btn svg {
  width: 18px;
  height: 18px;
  display: block;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
  fill: none;
}
.llm-chat-embed-panel-host > .llm-chat-embed-controls > .llm-chat-embed-btn:hover {
  transform: scale(1.04);
  box-shadow: 0 16px 36px rgba(15,23,42,0.34);
  background: rgba(15,23,42,0.92);
}
.llm-chat-embed-panel-host > .llm-chat-embed-controls > .llm-chat-embed-btn:active {
  transform: scale(0.97);
}
.llm-chat-embed-panel-host:not(.open) > .llm-chat-embed-controls {
  opacity: 0;
  pointer-events: none;
}
#${WRAP_ID} .llm-chat-embed-topbar-toggle {
  position: absolute;
  left: 50%;
  bottom: -26px;
  transform: translateX(-50%);
  width: 32px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 1px solid var(--border);
  border-top: 0;
  border-radius: 0 0 12px 12px;
  background: rgba(var(--panel-rgb), 0.94);
  color: var(--muted);
  box-shadow: 0 8px 18px rgba(15,23,42,0.14);
  cursor: pointer;
  opacity: 0;
  pointer-events: none;
  transition: transform 220ms ease, opacity 160ms ease, background 160ms ease, color 160ms ease;
  z-index: 130;
}
#${WRAP_ID} .llm-chat-embed-topbar-toggle:hover {
  background: rgba(var(--panel-rgb), 1);
  color: var(--ink);
}
#${WRAP_ID} .llm-chat-embed-topbar-toggle svg {
  width: 12px;
  height: 12px;
  display: block;
  stroke: currentColor;
  stroke-width: 1.9;
  stroke-linecap: round;
  stroke-linejoin: round;
  fill: none;
  transition: transform 220ms ease;
  transform: rotate(180deg);
}
.llm-chat-embed-panel-host.is-expanded #${WRAP_ID} .llm-chat-embed-topbar-toggle {
  opacity: 1;
  pointer-events: auto;
}
.llm-chat-embed-panel-host.is-expanded #${WRAP_ID} > #app.llm-chat-embed-topbar-collapsed .llm-chat-embed-topbar-toggle svg {
  transform: rotate(0deg);
}
    `.trim();
    document.head.appendChild(style);
  }

  function getPanelHost(wrap) {
    return wrap?.closest?.(".llm-chat-panel, [data-llm-chat-panel], .llm-chat-drawer, .llm-chat-widget-panel") || null;
  }

  function getAppRoot(wrap) {
    if (!wrap) return null;
    if (wrap.firstElementChild && wrap.firstElementChild.id === "app") return wrap.firstElementChild;
    return wrap.querySelector("#app");
  }

  function lockHostPageScroll() {
    if (pageScrollLock.locked || !document.body || !document.documentElement) return;
    pageScrollLock.locked = true;
    pageScrollLock.scrollY = window.scrollY || document.documentElement.scrollTop || 0;
    pageScrollLock.body = {
      position: document.body.style.position,
      top: document.body.style.top,
      left: document.body.style.left,
      right: document.body.style.right,
      width: document.body.style.width,
      overflow: document.body.style.overflow,
      overscrollBehavior: document.body.style.overscrollBehavior,
      touchAction: document.body.style.touchAction,
    };
    pageScrollLock.html = {
      overflow: document.documentElement.style.overflow,
      overscrollBehavior: document.documentElement.style.overscrollBehavior,
      touchAction: document.documentElement.style.touchAction,
    };
    document.documentElement.style.overflow = "hidden";
    document.documentElement.style.overscrollBehavior = "none";
    document.body.style.position = "fixed";
    document.body.style.top = `-${pageScrollLock.scrollY}px`;
    document.body.style.left = "0";
    document.body.style.right = "0";
    document.body.style.width = "100%";
    document.body.style.overflow = "hidden";
    document.body.style.overscrollBehavior = "none";
  }

  function unlockHostPageScroll() {
    if (!pageScrollLock.locked || !document.body || !document.documentElement) return;
    const body = pageScrollLock.body || {};
    const html = pageScrollLock.html || {};
    document.body.style.position = body.position || "";
    document.body.style.top = body.top || "";
    document.body.style.left = body.left || "";
    document.body.style.right = body.right || "";
    document.body.style.width = body.width || "";
    document.body.style.overflow = body.overflow || "";
    document.body.style.overscrollBehavior = body.overscrollBehavior || "";
    document.body.style.touchAction = body.touchAction || "";
    document.documentElement.style.overflow = html.overflow || "";
    document.documentElement.style.overscrollBehavior = html.overscrollBehavior || "";
    document.documentElement.style.touchAction = html.touchAction || "";
    const scrollY = pageScrollLock.scrollY || 0;
    pageScrollLock.locked = false;
    pageScrollLock.body = null;
    pageScrollLock.html = null;
    window.scrollTo(0, scrollY);
  }

  function syncHostPageScrollLock(wrap) {
    const host = getPanelHost(wrap);
    if (host?.dataset?.llmChatInlinePanel === "1") {
      unlockHostPageScroll();
      return;
    }
    if (host?.classList?.contains("open")) {
      lockHostPageScroll();
    } else {
      unlockHostPageScroll();
    }
  }

  function getTopbarToggleMarkup() {
    return `
<svg viewBox="0 0 12 12" aria-hidden="true" focusable="false">
  <path d="M2.25 4.25 6 8l3.75-3.75"></path>
</svg>
    `.trim();
  }

  function getExpandButtonMarkup(expanded) {
    if (expanded) {
      return `
<svg viewBox="0 0 20 20" aria-hidden="true" focusable="false">
  <path d="M7 3H3v4"></path>
  <path d="M3 3l5 5"></path>
  <path d="M13 17h4v-4"></path>
  <path d="M17 17l-5-5"></path>
  <path d="M13 3h4v4"></path>
  <path d="M17 3l-5 5"></path>
  <path d="M7 17H3v-4"></path>
  <path d="M3 17l5-5"></path>
</svg>
      `.trim();
    }
    return `
<svg viewBox="0 0 20 20" aria-hidden="true" focusable="false">
  <path d="M7 3H3v4"></path>
  <path d="M3 3l5 5"></path>
  <path d="M13 17h4v-4"></path>
  <path d="M17 17l-5-5"></path>
  <path d="M13 3h4"></path>
  <path d="M17 3v4"></path>
  <path d="M7 17H3"></path>
  <path d="M3 17v-4"></path>
</svg>
    `.trim();
  }

  function syncTopbarToggleState(wrap) {
    const appRoot = getAppRoot(wrap);
    const btn = appRoot?.querySelector?.(".llm-chat-embed-topbar-toggle");
    if (!btn) return;
    const collapsed = !!appRoot?.classList.contains("llm-chat-embed-topbar-collapsed");
    btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
    btn.setAttribute("aria-label", collapsed ? "Show top bar" : "Hide top bar");
  }

  function setTopbarCollapsed(wrap, collapsed) {
    const appRoot = getAppRoot(wrap);
    if (!appRoot) return;
    appRoot.classList.toggle("llm-chat-embed-topbar-collapsed", !!collapsed);
    syncTopbarToggleState(wrap);
    syncExpandButtonState(wrap);
  }

  function syncExpandButtonState(wrap) {
    const host = getPanelHost(wrap);
    const btn = host?.querySelector?.(":scope > .llm-chat-embed-controls > .llm-chat-embed-expand");
    if (!host || !btn) return;
    const expanded = host.classList.contains("is-expanded");
    const appRoot = getAppRoot(wrap);
    const topbarShown = expanded && appRoot && !appRoot.classList.contains("llm-chat-embed-topbar-collapsed");
    btn.setAttribute("aria-label", expanded ? "Minimize chat" : "Expand chat");
    btn.innerHTML = getExpandButtonMarkup(expanded);
    btn.style.display = topbarShown ? "none" : "";
  }

  function setPanelExpanded(wrap, expanded) {
    const host = getPanelHost(wrap);
    if (!host) return;
    host.classList.toggle("is-expanded", !!expanded);
    if (expanded) {
      setTopbarCollapsed(wrap, true);
    } else {
      setTopbarCollapsed(wrap, false);
    }
    syncExpandButtonState(wrap);
  }

  function markPanelOpened(wrap) {
    const host = getPanelHost(wrap);
    if (!host || !host.dataset) return;
    host.dataset.llmChatOpenedAt = String(Date.now());
  }

  function isWithinOpenGuard(wrap) {
    const host = getPanelHost(wrap);
    if (!host || !host.dataset) return false;
    const openedAt = parseInt(String(host.dataset.llmChatOpenedAt || "").trim(), 10);
    if (!Number.isFinite(openedAt) || openedAt <= 0) return false;
    return (Date.now() - openedAt) < OPEN_CLOSE_GUARD_MS;
  }

  function requestEmbeddedClose(wrap, opts = {}) {
    const force = Boolean(opts && opts.force);
    if (!force && isWithinOpenGuard(wrap)) return;
    const host = getEmbedTarget();
    const detail = { wrap, target: host };
    try {
      host.dispatchEvent(new CustomEvent("llm-chat-js:request-close", { detail, bubbles: true }));
    } catch (_err) {}
    try {
      window.dispatchEvent(new CustomEvent("llm-chat-js:request-close", { detail }));
    } catch (_err) {}

    setPanelExpanded(wrap, false);

    const panel = getPanelHost(wrap);
    if (panel) {
      panel.classList.remove("open");
      panel.setAttribute("aria-hidden", "true");
    }
    syncHostPageScrollLock(wrap);

    const overlays = document.querySelectorAll(".llm-chat-overlay, [data-llm-chat-overlay]");
    overlays.forEach((overlay) => {
      overlay.classList.remove("open");
      overlay.setAttribute("aria-hidden", "true");
    });
  }

  function ensureTopbarToggle(wrap) {
    const topbar = getAppRoot(wrap)?.querySelector?.(".topbar");
    if (!topbar) return null;
    let btn = topbar.querySelector(".llm-chat-embed-topbar-toggle");
    if (btn) return btn;
    btn = document.createElement("button");
    btn.type = "button";
    btn.className = "llm-chat-embed-topbar-toggle";
    btn.innerHTML = getTopbarToggleMarkup();
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const appRoot = getAppRoot(wrap);
      const collapsed = !!appRoot?.classList.contains("llm-chat-embed-topbar-collapsed");
      setTopbarCollapsed(wrap, !collapsed);
    });
    topbar.appendChild(btn);
    syncTopbarToggleState(wrap);
    return btn;
  }

  function ensurePanelControls(wrap) {
    const host = getPanelHost(wrap) || wrap;
    if (!host) return;
    ensureEmbedChromeStyle();
    host.classList.add("llm-chat-embed-panel-host");
    host.style.setProperty("--llm-chat-embed-height", height);
    if (host.dataset?.llmChatInlinePanel === "1" && host.classList.contains("llm-chat-inline-frame")) {
      host.style.height = height;
      if (!host.style.minHeight) host.style.minHeight = "520px";
    }
    try {
      if (window.getComputedStyle(host).position === "static") {
        host.style.position = "relative";
      }
    } catch (_err) {}
    let controls = host.querySelector(":scope > .llm-chat-embed-controls");
    if (!controls) {
      controls = document.createElement("div");
      controls.className = "llm-chat-embed-controls";
      host.appendChild(controls);
    }

    let expandBtn = controls.querySelector(":scope > .llm-chat-embed-expand");
    if (!expandBtn) {
      expandBtn = document.createElement("button");
      expandBtn.type = "button";
      expandBtn.className = "llm-chat-embed-btn llm-chat-embed-expand";
      expandBtn.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        setPanelExpanded(wrap, !host.classList.contains("is-expanded"));
      });
      controls.appendChild(expandBtn);
    }

    let closeBtn = controls.querySelector(":scope > .llm-chat-embed-close");
    if (!closeBtn) {
      closeBtn = document.createElement("button");
      closeBtn.type = "button";
      closeBtn.className = "llm-chat-embed-btn llm-chat-embed-close";
      closeBtn.setAttribute("aria-label", "Close chat");
      closeBtn.textContent = "X";
      closeBtn.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        requestEmbeddedClose(wrap, { force: true });
      });
      controls.appendChild(closeBtn);
    }

    if (!host.__llmChatEmbedPanelObserver) {
      const observer = new MutationObserver(() => {
        if (host.classList.contains("open")) markPanelOpened(wrap);
        if (!host.classList.contains("open")) {
          setPanelExpanded(wrap, false);
        } else {
          syncExpandButtonState(wrap);
          syncTopbarToggleState(wrap);
        }
        syncHostPageScrollLock(wrap);
      });
      observer.observe(host, { attributes: true, attributeFilter: ["class", "hidden", "aria-hidden"] });
      host.__llmChatEmbedPanelObserver = observer;
    }

    ensureTopbarToggle(wrap);
    syncExpandButtonState(wrap);
    syncTopbarToggleState(wrap);
    syncHostPageScrollLock(wrap);
    return controls;
  }

  function applyEmbedLayoutOptions(wrap) {
    if (!wrap) return;
    wrap.classList.toggle("llm-chat-embed-hide-topbar", shouldHideTopbar);
    wrap.style.setProperty("--llm-chat-embed-height", height);
  }

  async function ensureMarkup() {
    let wrap = document.getElementById(WRAP_ID);
    if (wrap) {
      applyEmbedLayoutOptions(wrap);
      return wrap;
    }
    wrap = document.createElement("div");
    wrap.id = WRAP_ID;
    wrap.style.width = "100%";
    wrap.style.height = height;
    wrap.style.minHeight = "520px";
    wrap.style.border = "1px solid rgba(0,0,0,0.12)";
    wrap.style.borderRadius = "16px";
    wrap.style.position = "relative";
    // Allow dropdowns/menus to overflow the wrapper (otherwise embedded submenus
    // near the right edge can get clipped and become un-clickable).
    wrap.style.overflow = "visible";
    wrap.style.background = "#fff";
    applyEmbedLayoutOptions(wrap);
    getEmbedTarget().appendChild(wrap);

    // Load the app DOM skeleton from the same origin as this script.
    const htmlUrl = resolveUiAssetUrl("chat_js.htm");
    const resp = await fetch(htmlUrl, { credentials: "omit", cache: assetFetchCache });
    if (!resp.ok) throw new Error(`Failed to load chat markup (${resp.status})`);
    const html = await resp.text();
    const doc = new DOMParser().parseFromString(html, "text/html");
    const appNode = doc.getElementById("app");
    if (!appNode) throw new Error("chat_js.htm missing #app");

    // Avoid duplicate IDs if user accidentally embedded twice.
    if (document.getElementById("app")) {
      throw new Error("chat_js already mounted on this page (duplicate #app).");
    }
    wrap.appendChild(document.importNode(appNode, true));
    ensurePanelControls(wrap);
    return wrap;
  }

  async function loadChatJs() {
    if (window.__LLM_CHAT_JS_EMBED_LOADED) return;
    window.__LLM_CHAT_JS_EMBED_LOADED = true;
    const jsUrl = resolveUiAssetUrl("chat_js.js");
    const s = document.createElement("script");
    s.type = "module";
    s.src = jsUrl;
    document.head.appendChild(s);
  }

  function ensureEmbeddedTitlePreserver(wrap) {
    try {
      if (window.__LLM_CHAT_EMBED_TITLE_OBSERVER__) return;
      let preservedTitle = String(document.title || "").trim();
      const sync = () => {
        const current = String(document.title || "").trim();
        const chatBrand = String(wrap?.querySelector?.("#brand-title")?.textContent || "").trim();
        if (current && chatBrand && current === chatBrand) {
          if (preservedTitle && current !== preservedTitle) document.title = preservedTitle;
          return;
        }
        if (current) preservedTitle = current;
      };
      const titleEl = document.querySelector("title");
      if (titleEl) {
        const obs = new MutationObserver(() => sync());
        obs.observe(titleEl, { childList: true, characterData: true, subtree: true });
        window.__LLM_CHAT_EMBED_TITLE_OBSERVER__ = obs;
      }
      setTimeout(sync, 0);
      setTimeout(sync, 150);
      setTimeout(sync, 1000);
    } catch (_err) {}
  }

  async function main() {
    setStatus("Loading chat...");
    ensureWidgetShellStyle();
    installPageJsonRetrieverPreSniffer();
    await resolveFromCms();
    // Hosted defaults: if we're embedding from GotChat and CMS didn't return
    // the plugin repo API, use the public plugin server API.
    if (!pluginRepoApiBase && /(?:^|\.)gotchat\.ai$/i.test(String(uiBase.hostname || "").trim())) {
      pluginRepoApiBase = "https://pluginserver.gotchat.ai/api";
    }
    await ensureFonts();
    await ensureScopedCss();
    ensureEmbedLayoutOptionCss();
    const portal = ensurePortal();
    ensurePortalHelpers(portal);
    const wrap = await ensureMarkup();

    // Feed embed configuration to chat_js before the module initializes.
    window.__CHAT_JS_EMBED_MOUNT = wrap;
    window.__CHAT_JS_EMBED_CONFIG = Object.assign({}, window.__CHAT_JS_EMBED_CONFIG || {}, {
      server,
      hostService: hostService || undefined,
      clientService: clientService || undefined,
      uiOrigin,
      devMode: devMode || undefined,
      assetRev: assetRev || undefined,
      cmsBase: cmsBase || undefined,
      token: token || undefined,
      pid: pid || undefined,
      sid: sid || undefined,
      alias: alias || undefined,
      sass: Object.values(sass).some(Boolean) ? sass : undefined,
      biz: Object.values(biz).some(Boolean) ? biz : undefined,
      identifierKey: identifierKey || undefined,
      pluginRepoApiBase: pluginRepoApiBase || undefined,
      mount: wrap,
      overlayMount: portal,
      portal,
      embedded: true,
    });

    ensureEmbeddedTitlePreserver(wrap);
    await loadChatJs();
    setStatus("");
  }

  function start() {
    // Install the pre-sniffer as early as possible, even if we defer mounting
    // until the target element exists.
    try {
      installPageJsonRetrieverPreSniffer();
    } catch (_err) {}

    const run = () => {
      main().catch((err) => {
        console.error("[chat_embed]", err);
        setStatus(`Chat embed failed: ${err.message || err}`);
      });
    };

    // If the mount target doesn't exist yet (e.g., script placed in <head>
    // without defer), wait until DOM is ready.
    try {
      const hasTarget = Boolean(document.querySelector(targetSel));
      if (!hasTarget && document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", run, { once: true });
        return;
      }
    } catch (_err) {}
    run();
  }

  start();
})();



