const meta = {
  plugin_id: "agent_flow",
  name: "Agent Flow",
  kind: "ui",
  description: "Agent Flow designer for router plugin flows.",
  has_notebook_tab: true,
};

const STYLE_ID = "agent-flow-style";
const NODE_W = 140;
const NODE_H = 60;
const SESSION_CHANGE_EVENT = "chat_js:session-changed";
const OPEN_TEMP_LIBRARY_EVENT = "agent-flow:open-temp-library-record";
const OPEN_TEMP_LIBRARY_PENDING_KEY = "__agentFlowOpenTempLibraryRequest";
const NO_FLOW_VALUE = "__none__";
const LLM_AUTOFLOW_FLOW_VALUE = "__llm_autoflow__";
const LLM_SKILL_AUTOFLOW_FLOW_VALUE = "__llm_skill_autoflow__";
const FLOW_SEARCH_IDLE_MS = 360;
function ensureStyles() {
  let style = document.getElementById(STYLE_ID);
  if (!style) {
    style = document.createElement("style");
    style.id = STYLE_ID;
    document.head.appendChild(style);
  }
  style.textContent = `
.agent-flow { position: relative; display: flex; flex-direction: column; gap: 10px; min-height: 520px; height: min(82dvh, 980px); }
.agent-flow .panel { border: 1px solid var(--border); border-radius: 14px; background: rgba(var(--panel-rgb), 0.92); padding: 12px; display: flex; flex-direction: column; gap: 10px; }
.agent-flow .flow-picker-wrap { position: relative; min-width: 0; z-index: 18; }
.agent-flow .flow-list-popover,
.flow-list-popover { position: fixed; left: 0; top: 0; width: min(520px, calc(100vw - 48px)); max-width: calc(100vw - 48px); max-height: calc(100dvh - 24px); border: 1px solid var(--border); border-radius: 14px; background: rgba(var(--panel-rgb), 0.98); box-shadow: var(--shadow); padding: 10px; display: none; flex-direction: column; gap: 8px; z-index: 2147483200; box-sizing: border-box; overflow: hidden; }
.agent-flow .flow-list-popover.open,
.flow-list-popover.open { display: flex; }
.agent-flow .flow-list-popover-head,
.flow-list-popover-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.agent-flow .flow-list-popover-head-actions,
.flow-list-popover-head-actions { display: inline-flex; align-items: center; gap: 8px; }
.agent-flow .flow-list-popover-title,
.flow-list-popover-title { font-size: 11px; color: var(--ui-muted); text-transform: uppercase; letter-spacing: 0.9px; }
.agent-flow .flow-list-popover-tip,
.flow-list-popover-tip { font-size: 11px; color: var(--ui-muted); }
.agent-flow .flow-list-popover-close,
.flow-list-popover-close { width: 24px; height: 24px; border-radius: 999px; border: 1px solid var(--border); background: var(--ui-control-bg); color: var(--ui-ink); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; font-size: 12px; line-height: 1; }
.agent-flow .flow-list-popover-close:hover,
.flow-list-popover-close:hover { background: var(--ui-popover-item-bg-hover); }
.agent-flow .flow-list { display: flex; flex-direction: column; gap: 6px; height: 460px; min-height: 460px; max-height: 460px; overflow: auto; }
.agent-flow .flow-list .list-item,
.flow-list .list-item { cursor: pointer; }
.agent-flow .flow-list .list-item .flow-name,
.flow-list .list-item .flow-name { font-weight: 700; font-size: 11px; line-height: 1.2; overflow-wrap: anywhere; word-break: break-word; }
.agent-flow .flow-list .list-item .flow-info,
.flow-list .list-item .flow-info { margin-top: 3px; font-size: 11px; color: var(--ui-muted); overflow-wrap: anywhere; }
.agent-flow input[type="search"].agent-flow-popover-search,
.agent-flow input[type="search"],
.agent-flow-popover input[type="search"].agent-flow-popover-search { border: 1px solid var(--border); border-radius: 999px !important; background: var(--ui-control-bg); color: var(--ui-ink); padding: 7px 12px; font-size: 12px; }
.agent-flow input[type="search"].agent-flow-popover-search::placeholder,
.agent-flow input[type="search"]::placeholder,
.agent-flow-popover input[type="search"].agent-flow-popover-search::placeholder { color: var(--ui-muted); }
.agent-flow .agent-flow-search-row,
.agent-flow-popover .agent-flow-search-row { display: block; min-width: 0; }
.agent-flow .agent-flow-search-shell,
.agent-flow-popover .agent-flow-search-shell { position: relative; width: 100%; min-width: 0; }
.agent-flow .agent-flow-search-chevron,
.agent-flow-popover .agent-flow-search-chevron { position: absolute; top: 50%; left: 8px; transform: translateY(-50%); z-index: 2; width: 24px; height: 24px; border-radius: 999px; border: 1px solid transparent; background: transparent; color: var(--ui-muted); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; }
.agent-flow .agent-flow-search-chevron:hover,
.agent-flow-popover .agent-flow-search-chevron:hover { color: var(--ui-ink); background: rgba(var(--panel-rgb), 0.72); }
.agent-flow .agent-flow-search-chevron.open,
.agent-flow-popover .agent-flow-search-chevron.open { color: var(--ui-ink); }
.agent-flow .agent-flow-search-shell input[type="search"],
.agent-flow-popover .agent-flow-search-shell input[type="search"] { width: 100%; min-width: 0; padding-left: 38px; padding-right: 42px; border-radius: 999px !important; }
.agent-flow .agent-flow-filter-wrap,
.agent-flow-popover .agent-flow-filter-wrap { position: absolute; top: 50%; right: 6px; transform: translateY(-50%); z-index: 2; }
.agent-flow .agent-flow-filter-btn,
.agent-flow-popover .agent-flow-filter-btn { width: 28px; height: 28px; border-radius: 999px; border: 1px solid transparent; background: transparent; color: var(--ui-muted); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; }
.agent-flow .agent-flow-filter-btn.active,
.agent-flow-popover .agent-flow-filter-btn.active { border-color: rgba(var(--accent-rgb, 37, 99, 235), 0.6); color: var(--accent); box-shadow: 0 0 0 1px rgba(var(--accent-rgb, 37, 99, 235), 0.16); }
.agent-flow .agent-flow-filter-btn:hover,
.agent-flow-popover .agent-flow-filter-btn:hover { color: var(--ui-ink); background: rgba(var(--panel-rgb), 0.72); }
.agent-flow .agent-flow-filter-menu,
.agent-flow-popover .agent-flow-filter-menu { position: absolute; top: calc(100% + 8px); right: 0; width: min(220px, calc(100vw - 24px)); max-height: min(260px, 50vh); overflow: auto; padding: 8px; border-radius: 14px; border: 1px solid var(--border); background: var(--panel); box-shadow: var(--shadow); z-index: 30; display: flex; flex-direction: column; gap: 6px; }
.agent-flow .agent-flow-filter-menu.hidden,
.agent-flow-popover .agent-flow-filter-menu.hidden { display: none; }
.agent-flow .agent-flow-filter-head,
.agent-flow-popover .agent-flow-filter-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding-left: 4px; font-size: 10px; color: var(--ui-muted); text-transform: uppercase; letter-spacing: 0.9px; }
.agent-flow .agent-flow-filter-list,
.agent-flow-popover .agent-flow-filter-list { display: flex; flex-direction: column; gap: 6px; }
.agent-flow .agent-flow-filter-item,
.agent-flow-popover .agent-flow-filter-item { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 5px 7px; border-radius: 10px; background: var(--ui-popover-item-bg); }
.agent-flow .agent-flow-filter-item label,
.agent-flow-popover .agent-flow-filter-item label { display: flex; align-items: center; gap: 7px; min-width: 0; flex: 1 1 auto; cursor: pointer; font-size: 11px; }
.agent-flow .agent-flow-filter-count,
.agent-flow-popover .agent-flow-filter-count { font-size: 10px; color: var(--ui-muted); }
.agent-flow .agent-flow-readonly-note { font-size: 11px; color: var(--ui-muted); border: 1px dashed var(--border); border-radius: 10px; padding: 8px; background: rgba(var(--panel-rgb), 0.45); }
.agent-flow .flow-meta-card { border: 1px solid var(--border); border-radius: 12px; padding: 0; background: var(--ui-popover-item-bg); overflow: hidden; }
.agent-flow .flow-meta-card summary { list-style: none; cursor: pointer; padding: 10px; display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.agent-flow .flow-meta-card summary::-webkit-details-marker { display: none; }
.agent-flow .flow-meta-card summary::after { content: "▸"; color: var(--ui-muted); font-size: 12px; }
.agent-flow .flow-meta-card[open] summary::after { content: "▾"; }
.agent-flow .flow-meta-card-body { padding: 0 10px 10px; display: flex; flex-direction: column; gap: 8px; }
.agent-flow .flow-meta-card textarea { min-height: 110px; resize: vertical; }
.agent-flow-json-form-popover { position: fixed; inset: 18px; z-index: 2147483200; background: var(--panel); color: var(--ui-ink); border: 1px solid var(--border); border-radius: 16px; box-shadow: var(--shadow); padding: 14px; display: flex; flex-direction: column; gap: 12px; overflow: hidden; box-sizing: border-box; }
.agent-flow-json-form-popover .json-form-head { display:flex; align-items:center; justify-content:space-between; gap:10px; }
.agent-flow-json-form-popover .json-form-title { font-weight:700; font-size:13px; }
.agent-flow-json-form-popover .json-form-body { overflow:auto; display:flex; flex-direction:column; gap:10px; padding-right:4px; }
.agent-flow-json-form-popover .json-form-section { border:1px solid var(--border); border-radius:12px; padding:10px; background: var(--ui-popover-item-bg); display:flex; flex-direction:column; gap:8px; }
.agent-flow-json-form-popover .json-form-section-title { font-size:11px; font-weight:700; color:var(--ui-muted); text-transform:uppercase; letter-spacing:.8px; }
.agent-flow-json-form-popover .json-form-field { display:flex; flex-direction:column; gap:4px; }
.agent-flow-json-form-popover .json-form-field span { font-size:11px; color:var(--ui-muted); }
.agent-flow-json-form-popover .json-form-actions { display:flex; justify-content:flex-end; gap:8px; }
.agent-flow .model-node-editor { display:flex; flex-direction:column; gap:10px; }
.agent-flow .model-node-section { border:1px solid var(--border); border-radius:12px; padding:10px; background:var(--ui-popover-item-bg); display:flex; flex-direction:column; gap:8px; }
.agent-flow .model-node-section-title { font-size:11px; font-weight:700; color:var(--ui-muted); text-transform:uppercase; letter-spacing:.8px; }
.agent-flow .model-node-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(210px, 1fr)); gap:8px; }
.agent-flow .model-node-field { display:flex; flex-direction:column; gap:4px; min-width:0; }
.agent-flow .model-node-field span { font-size:11px; color:var(--ui-muted); }
.agent-flow .model-node-field input,
.agent-flow .model-node-field select,
.agent-flow .model-node-field textarea { width:100%; box-sizing:border-box; }
.agent-flow .model-node-advanced summary { font-size:12px; color:var(--ui-muted); cursor:pointer; }
.agent-flow .agent-flow-canvas-wrap { position: relative; flex: 1; min-height: 0; height: 100%; padding-top: 36px; }
.agent-flow .flow-canvas { position: relative; border: 1px dashed var(--border); border-radius: 14px; background: radial-gradient(circle at 20% 20%, rgba(20, 20, 20, 0.08), transparent 60%), #faf6f0; height: 100%; min-height: 520px; overflow: auto; -webkit-overflow-scrolling: touch; overscroll-behavior: contain; touch-action: pan-x pan-y; user-select: none; -webkit-user-select: none; }
.agent-flow .flow-canvas-inner { position: relative; min-width: 100%; min-height: 100%; zoom: var(--agent-flow-zoom, 1); }
.agent-flow .flow-node { position: absolute; width: ${NODE_W}px; height: ${NODE_H}px; border-radius: 12px; background: #2b2825; color: #f3e8d7; border: 2px solid rgba(255,255,255,0.2); display: flex; align-items: center; justify-content: center; font-size: 12px; text-align: center; padding: 6px; cursor: grab; user-select: none; -webkit-user-select: none; -webkit-touch-callout: none; touch-action: none; }
.agent-flow .flow-node .node-main-label { display: block; line-height: 1.15; }
.agent-flow .flow-node .node-sub-badge { display: inline-block; margin-top: 4px; padding: 1px 6px; border-radius: 999px; font-size: 10px; line-height: 1.1; border: 1px solid rgba(255,255,255,0.22); color: #fdf3dd; background: rgba(245, 158, 11, 0.22); max-width: 126px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.agent-flow .flow-node.selected { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(var(--accent-rgb, 37, 99, 235), 0.3); }
.agent-flow .flow-node.dragging { cursor: grabbing; }
.agent-flow .flow-node.read-only { cursor: default; opacity: 0.9; }
.agent-flow .flow-selection-box { position: absolute; border: 1.5px dashed rgba(245, 158, 11, 0.95); background: rgba(245, 158, 11, 0.12); border-radius: 8px; pointer-events: none; z-index: 6; }
.agent-flow .flow-edge { stroke: rgba(20,20,20,0.6); stroke-width: 2; }
.agent-flow .flow-edge.conditional { stroke: rgba(217, 119, 6, 0.95); stroke-dasharray: 6 4; }
.agent-flow .flow-edge.loopback { stroke: rgba(190, 24, 93, 0.92); stroke-dasharray: 7 5; }
.agent-flow .flow-edge-label { fill: rgba(20,20,20,0.86); font-size: 10px; font-weight: 700; paint-order: stroke; stroke: rgba(250,246,240,0.92); stroke-width: 3px; stroke-linejoin: round; }
.agent-flow .flow-hint { font-size: 11px; color: var(--ui-muted); min-height: 16px; }
.agent-flow .properties { display: flex; flex-direction: column; gap: 8px; }
.agent-flow .properties textarea { min-height: 90px; }
.agent-flow .transition-list { display: flex; flex-direction: column; gap: 10px; }
.agent-flow .transition-item { border: 1px solid var(--border); border-radius: 10px; padding: 8px; background: var(--ui-popover-item-bg); display: flex; flex-direction: column; gap: 8px; }
.agent-flow .transition-item-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.agent-flow .transition-item-title { font-size: 11px; font-weight: 700; color: var(--ui-muted); text-transform: uppercase; letter-spacing: 0.8px; }
.agent-flow .transition-inline { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.agent-flow .transition-inline.single { grid-template-columns: 1fr; }
.agent-flow .transition-rules { display: flex; flex-direction: column; gap: 8px; }
.agent-flow .transition-rule { border: 1px dashed var(--border); border-radius: 8px; padding: 8px; display: flex; flex-direction: column; gap: 8px; background: rgba(var(--panel-rgb), 0.5); }
.agent-flow .transition-group { border: 1px solid var(--border); border-radius: 10px; padding: 8px; background: rgba(var(--panel-rgb), 0.62); display: flex; flex-direction: column; gap: 8px; }
.agent-flow .transition-rule .transition-inline { grid-template-columns: 1fr; }
.agent-flow .transition-item .field,
.agent-flow .transition-rule .field,
.agent-flow .transition-group .field { min-width: 0; }
.agent-flow .transition-item select,
.agent-flow .transition-item input,
.agent-flow .transition-item textarea,
.agent-flow .transition-rule select,
.agent-flow .transition-rule input,
.agent-flow .transition-rule textarea,
.agent-flow .transition-group select,
.agent-flow .transition-group input,
.agent-flow .transition-group textarea { width: 100%; min-width: 0; box-sizing: border-box; }
.agent-flow .section-title { font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: var(--ui-muted); }
.agent-flow .small { font-size: 11px; color: var(--ui-muted); }
.agent-flow .button-row { display: flex; gap: 6px; flex-wrap: wrap; }
.agent-flow .flow-svg { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: auto; }
.agent-flow .flow-svg line { pointer-events: none; }
.agent-flow .flow-edge-chip { cursor: pointer; }
.agent-flow .flow-edge-chip-bg { fill: rgba(255,250,244,0.96); stroke: rgba(20,20,20,0.18); stroke-width: 1; rx: 8px; ry: 8px; }
.agent-flow .context-menu { position: absolute; z-index: 20; background: var(--panel); border: 1px solid var(--border); border-radius: 10px; box-shadow: var(--shadow); padding: 6px; display: flex; flex-direction: column; gap: 4px; min-width: 160px; }
.agent-flow .context-menu button { text-align: left; border: 1px solid transparent; background: var(--ui-popover-item-bg); color: var(--ui-ink); padding: 6px 8px; border-radius: 8px; font-size: 12px; cursor: pointer; }
.agent-flow .context-menu button:hover { border-color: var(--border); }
.agent-flow .context-menu button:disabled { opacity: 0.5; cursor: not-allowed; }
.agent-flow-bar { display: inline-flex; align-items: center; gap: 8px; font-size: 12px; }
.agent-flow-bar-btn { padding: 4px 10px; border-radius: 999px; border: 1px solid var(--border); background: var(--ui-control-bg); color: var(--ui-ink); cursor: pointer; display: inline-flex; align-items: center; gap: 8px; }
.agent-flow-bar-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.agent-flow-bar-btn .label { font-weight: 600; }
.agent-flow-bar-btn .hint { color: var(--ui-muted); font-weight: 500; }
.agent-flow-popover { position: fixed; min-width: 240px; width: min(360px, calc(100vw - 24px)); max-width: calc(100vw - 24px); max-height: calc(100dvh - 24px); background: var(--panel); border: 1px solid var(--border); border-radius: 12px; box-shadow: var(--shadow); padding: 12px; z-index: 2147483200; pointer-events: auto; color: var(--ui-ink); box-sizing: border-box; overflow: hidden; }
.agent-flow-popover h4 { margin: 0 0 8px; font-size: 12px; text-transform: uppercase; letter-spacing: 1.2px; color: var(--ui-muted); }
.agent-flow-popover .list { display: flex; flex-direction: column; gap: 8px; height: 320px; min-height: 320px; max-height: 320px; overflow: auto; padding-right: 4px; }
.agent-flow-popover .item { border: 1px solid var(--border); border-radius: 10px; padding: 8px; background: var(--ui-popover-item-bg); display: flex; gap: 10px; justify-content: space-between; min-width: 0; }
.agent-flow-popover .item.selected { border-color: rgba(var(--accent-rgb, 37, 99, 235), 0.6); box-shadow: 0 0 0 1px rgba(var(--accent-rgb, 37, 99, 235), 0.16); }
.agent-flow-popover .meta { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.agent-flow-popover .name { appearance: none; background: none; border: 0; padding: 0; margin: 0; text-align: left; cursor: pointer; font: inherit; color: inherit; font-weight: 700; font-size: 12px; width: 100%; min-width: 0; white-space: normal; overflow-wrap: anywhere; word-break: break-word; }
.agent-flow-popover .name:hover { text-decoration: underline; }
.agent-flow-popover .sub { font-size: 11px; color: var(--ui-muted); overflow-wrap: anywhere; word-break: break-word; white-space: normal; }
.agent-flow-popover .nodes { display: flex; flex-direction: column; gap: 2px; font-size: 11px; color: var(--text); }
.agent-flow-popover .nodes .node { display: grid; grid-template-columns: minmax(0, 1fr); gap: 2px; min-width: 0; }
.agent-flow-popover .nodes .node > div { min-width: 0; overflow-wrap: anywhere; word-break: break-word; white-space: normal; }
.agent-flow-popover .nodes .node .pid { color: var(--ui-muted); }
.agent-flow-popover .actions { display: flex; align-items: flex-start; flex: 0 0 auto; }
.agent-flow-popover .select-btn { font-size: 11px; padding: 4px 8px; border-radius: 8px; border: 1px solid var(--border); background: var(--ui-control-bg); color: var(--ui-ink); cursor: pointer; }
.agent-flow-popover .select-btn:hover { background: var(--ui-popover-item-bg-hover); }
.agent-flow-popover .select-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.agent-flow-popover .muted { font-size: 12px; color: var(--ui-muted); }
.agent-flow-fly { position: absolute; top: 0; bottom: 0; width: 280px; z-index: 30; overflow: auto; transition: transform 0.2s ease, opacity 0.2s ease; }
.agent-flow-fly.left { left: 0; }
.agent-flow-fly.right { right: 0; }
.agent-flow-fly.collapsed { opacity: 0; pointer-events: none; }
.agent-flow-fly.left.collapsed { transform: translateX(-105%); }
.agent-flow-fly.right.collapsed { transform: translateX(105%); }
.agent-flow-tag { position: absolute; top: 6px; z-index: 7; background: var(--ui-control-bg-strong); color: var(--ui-ink); border: 1px solid var(--border); border-radius: 999px; padding: 6px 10px; font-size: 11px; cursor: pointer; box-shadow: var(--shadow); }
.agent-flow-tag.left { left: 12px; }
.agent-flow-tag.right { right: 12px; }
.agent-flow-tag.back { right: 90px; }
.agent-flow-view-controls { position: absolute; top: 6px; left: 50%; transform: translateX(-50%); z-index: 10; display: inline-flex; align-items: center; gap: 6px; padding: 4px 6px; border: 1px solid var(--border); border-radius: 999px; background: rgba(var(--panel-rgb), 0.94); box-shadow: var(--shadow); }
.agent-flow-view-controls button { width: 28px; height: 28px; border-radius: 999px; border: 1px solid var(--border); background: var(--ui-control-bg); color: var(--ui-ink); cursor: pointer; font-size: 14px; line-height: 1; }
.agent-flow-view-controls .zoom-label { min-width: 42px; text-align: center; font-size: 11px; color: var(--ui-muted); }
.agent-flow-canvas-header { position: absolute; top: 44px; left: 12px; z-index: 5; display: flex; flex-direction: column; gap: 4px; pointer-events: none; }
.agent-flow-progress { display: flex; flex-direction: column; gap: 6px; padding: 8px 10px; border-radius: 10px; border: 1px solid var(--border); background: rgba(var(--panel-rgb), 0.9); min-width: 220px; max-width: 320px; }
.agent-flow-progress.hidden { display: none; }
.agent-flow-progress-head { display: flex; align-items: center; gap: 8px; }
.agent-flow-progress-control { width: 24px; height: 24px; border-radius: 999px; border: 1px solid var(--border); background: var(--ui-control-bg); color: var(--ui-ink); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; flex: 0 0 auto; line-height: 1; }
.agent-flow-progress-control:hover { background: var(--ui-popover-item-bg-hover); }
.agent-flow-progress-control:disabled { opacity: 0.6; cursor: wait; }
.agent-flow-icon { display: inline-block; position: relative; width: 14px; height: 14px; color: currentColor; }
.agent-flow-icon-pause::before,
.agent-flow-icon-pause::after { content: ""; position: absolute; top: 1px; bottom: 1px; width: 4px; border-radius: 2px; background: currentColor; }
.agent-flow-icon-pause::before { left: 2px; }
.agent-flow-icon-pause::after { right: 2px; }
.agent-flow-icon-play::before { content: ""; position: absolute; left: 4px; top: 2px; width: 0; height: 0; border-top: 5px solid transparent; border-bottom: 5px solid transparent; border-left: 8px solid currentColor; }
.agent-flow-icon-spinner { border: 2px solid color-mix(in srgb, currentColor 28%, transparent); border-top-color: currentColor; border-radius: 999px; animation: agent-flow-spin 0.75s linear infinite; }
@keyframes agent-flow-spin { to { transform: rotate(360deg); } }
.agent-flow-progress-title { font-size: 12px; font-weight: 600; }
.agent-flow-progress-status { font-size: 11px; color: var(--ui-muted); }
.agent-flow-progress-meta { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.agent-flow-loop-badge { display: inline-flex; align-items: center; gap: 6px; max-width: 100%; padding: 3px 8px; border-radius: 999px; border: 1px solid var(--border); background: rgba(var(--panel-rgb), 0.86); color: var(--ui-ink); font-size: 10px; line-height: 1.2; }
.agent-flow-loop-badge .src { color: var(--ui-muted); text-transform: uppercase; letter-spacing: 0.4px; }
.agent-flow-loop-badge .val { font-weight: 700; }
.agent-flow-progress-list { display: flex; flex-direction: column; gap: 4px; }
.agent-flow-progress-item { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: 11px; }
.agent-flow-progress-item .label { color: var(--text); }
.agent-flow-progress-item .state { color: var(--ui-muted); }
.agent-flow-alert-wrap { position: relative; display: inline-flex; align-items: center; }
.agent-flow-alert-btn { width: 34px; height: 34px; border-radius: 999px; border: 1px solid var(--border); background: var(--ui-control-bg); color: var(--ui-ink); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; position: relative; }
.agent-flow-alert-btn:hover { background: var(--ui-popover-item-bg-hover); }
.agent-flow-alert-count { position: absolute; top: -4px; right: -4px; min-width: 16px; height: 16px; padding: 0 4px; border-radius: 999px; background: var(--accent-warm); color: #1a1306; font-size: 10px; font-weight: 700; display: inline-flex; align-items: center; justify-content: center; }
.agent-flow-alert-popover { position: fixed; width: min(440px, calc(100vw - 24px)); max-width: calc(100vw - 24px); max-height: min(72vh, calc(100dvh - 24px), 640px); background: var(--panel); border: 1px solid var(--border); border-radius: 12px; box-shadow: var(--shadow); padding: 12px; z-index: 2147483200; display: flex; flex-direction: column; gap: 10px; color: var(--ui-ink); box-sizing: border-box; overflow: hidden; }
.agent-flow-alert-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.agent-flow-alert-title { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; color: var(--ui-muted); }
.agent-flow-alert-body { display: grid; grid-template-columns: minmax(180px, 210px) 1fr; gap: 10px; min-height: 220px; }
.agent-flow-alert-list { border: 1px solid var(--border); border-radius: 10px; background: var(--ui-popover-item-bg); overflow: auto; display: flex; flex-direction: column; gap: 6px; padding: 6px; }
.agent-flow-alert-item { border: 1px solid var(--border); border-radius: 8px; background: rgba(var(--panel-rgb), 0.72); padding: 7px 8px; cursor: pointer; display: flex; flex-direction: column; gap: 4px; }
.agent-flow-alert-item.active { border-color: rgba(245, 158, 11, 0.6); box-shadow: 0 0 0 1px rgba(245, 158, 11, 0.18); }
.agent-flow-alert-item-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: 12px; font-weight: 600; }
.agent-flow-alert-pill { font-size: 10px; border-radius: 999px; padding: 2px 6px; background: rgba(var(--accent-rgb), 0.12); color: var(--accent); }
.agent-flow-alert-sub { font-size: 11px; color: var(--ui-muted); word-break: break-word; }
.agent-flow-alert-detail { border: 1px solid var(--border); border-radius: 10px; background: var(--ui-popover-item-bg); padding: 8px; display: flex; flex-direction: column; gap: 8px; overflow: auto; }
.agent-flow-alert-detail-title { font-size: 12px; font-weight: 700; }
.agent-flow-alert-empty { font-size: 12px; color: var(--ui-muted); padding: 10px 4px; }
.agent-flow-alert-popover .select-btn { font-size: 11px; padding: 4px 8px; border-radius: 8px; border: 1px solid var(--border); background: var(--ui-control-bg); color: var(--ui-ink); cursor: pointer; }
.agent-flow-import-wrap { position: relative; display: inline-flex; }
.agent-flow-import-popover { position: fixed; min-width: 520px; width: min(720px, calc(100vw - 24px)); max-width: min(720px, calc(100vw - 24px)); max-height: 80vh; overflow: auto; background: var(--panel); border: 1px solid var(--border); border-radius: 12px; box-shadow: var(--shadow); padding: 10px; z-index: 2147483200; display: flex; flex-direction: column; gap: 10px; }
.agent-flow-import-popover textarea { min-height: 320px; max-height: 58vh; }
.agent-flow-import-head { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; color: var(--ui-muted); }
.agent-flow-import-item { border: 1px solid var(--border); border-radius: 10px; background: var(--ui-popover-item-bg); padding: 8px; display: flex; flex-direction: column; gap: 6px; }
.agent-flow-import-item-title { font-size: 12px; font-weight: 700; }
.agent-flow-import-item-sub { font-size: 11px; color: var(--ui-muted); }
.agent-flow-awf-popover { position: fixed; min-width: min(560px, calc(100vw - 24px)); width: min(760px, calc(100vw - 24px)); max-width: min(760px, calc(100vw - 24px)); max-height: min(80vh, calc(100dvh - 24px)); overflow: auto; background: var(--panel); border: 1px solid var(--border); border-radius: 12px; box-shadow: var(--shadow); padding: 12px; z-index: 2147483200; display: flex; flex-direction: column; gap: 10px; box-sizing: border-box; }
.agent-flow-awf-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.agent-flow-awf-title-wrap { display: inline-flex; align-items: center; gap: 10px; min-width: 0; }
.agent-flow-awf-title { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; color: var(--ui-muted); }
.agent-flow-awf-loading-badge { display: inline-flex; align-items: center; gap: 8px; padding: 4px 10px; border: 1px solid var(--border); border-radius: 999px; background: rgba(var(--panel-rgb), 0.7); color: var(--ui-muted); font-size: 11px; }
.agent-flow-awf-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.agent-flow-awf-search { flex: 1 1 280px; min-width: min(280px, 100%); }
.agent-flow-awf-search input[type="search"] { width: 100%; min-width: 0; }
.agent-flow-awf-status { font-size: 11px; color: var(--ui-muted); }
.agent-flow-awf-pager { display: inline-flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.agent-flow-awf-pager-bottom { width: 100%; justify-content: flex-end; margin-top: 2px; }
.agent-flow-awf-page { font-size: 11px; color: var(--ui-muted); min-width: 72px; text-align: center; }
.agent-flow-awf-list { display: flex; flex-direction: column; gap: 10px; }
.agent-flow-awf-item { border: 1px solid var(--border); border-radius: 10px; background: var(--panel); padding: 10px; display: flex; flex-direction: column; gap: 8px; box-shadow: none; }
.agent-flow-awf-name { font-size: 13px; font-weight: 700; color: var(--ui-ink); overflow-wrap: anywhere; word-break: break-word; white-space: normal; }
.agent-flow-awf-sub { font-size: 11px; color: var(--ui-muted); overflow-wrap: anywhere; }
.agent-flow-awf-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.agent-flow-awf-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.agent-flow-awf-empty { font-size: 12px; color: var(--ui-muted); padding: 10px 2px; }
.agent-flow-awf-loading { display: flex; align-items: center; gap: 10px; padding: 14px 2px; color: var(--ui-muted); font-size: 12px; }
.agent-flow-awf-spinner { width: 16px; height: 16px; border: 2px solid rgba(var(--accent-rgb, 37, 99, 235), 0.18); border-top-color: var(--accent); border-radius: 999px; animation: agent-flow-spin 0.75s linear infinite; flex: 0 0 auto; }
.agent-flow-awf-launch-indicator { display: inline-flex; align-items: center; gap: 8px; padding: 0 4px; color: var(--ui-muted); font-size: 11px; }
.agent-flow-awf-launch-indicator[hidden] { display: none; }
.agent-flow-awf-launch-indicator .agent-flow-awf-spinner { width: 14px; height: 14px; }
.agent-flow .agent-flow-active-input { border-radius: 12px !important; }
.agent-flow .agent-flow-profile-group { display: flex; flex-direction: column; gap: 8px; }
.agent-flow .agent-flow-profile-group.hidden { display: none; }
@media (max-width: 720px) {
  .agent-flow-awf-popover { width: calc(100vw - 16px); min-width: 0; max-width: calc(100vw - 16px); max-height: calc(100dvh - 16px); padding: 10px; border-radius: 10px; }
  .agent-flow-awf-head { align-items: flex-start; flex-wrap: wrap; }
  .agent-flow-awf-actions { width: 100%; }
  .agent-flow-awf-actions button { flex: 1 1 calc(50% - 8px); min-width: 0; }
}
  `;
}

function ensureRouterState(ctx) {
  if (!ctx.state.router || typeof ctx.state.router !== "object") {
    ctx.state.router = { manifest: {}, enabled: {}, settings: {} };
  }
  if (!ctx.state.router.manifest) ctx.state.router.manifest = {};
  if (!ctx.state.router.enabled) ctx.state.router.enabled = {};
  if (!ctx.state.router.settings) ctx.state.router.settings = {};
}

async function ensureManifest(ctx) {
  ensureRouterState(ctx);
  const manifest = ctx.state.router.manifest || {};
  if (Object.keys(manifest).length) return manifest;
  try {
    const data = await ctx.apiJson("/v1/router/plugins");
    const out = {};
    for (const item of data?.plugins || []) {
      const pid = String(item?.plugin_id || item?.id || "").trim();
      if (!pid) continue;
      out[pid] = {
        title: item?.title || pid,
        short_description: item?.short_description || item?.description || "",
        schema: item?.schema || item?.config_schema || [],
        agent_linkable: item?.agent_linkable,
        type: item?.type || "router",
        family: item?.family || "router",
      };
    }
    ctx.state.router.manifest = out;
    ctx.saveState?.();
    return out;
  } catch {
    return manifest;
  }
}

let agentFlowSkillCatalog = null;

async function loadAgentFlowSkillCatalog(ctx, force = false) {
  const pid = ctx?.state?.ui?.activePid;
  const sid = ctx?.state?.ui?.activeSid;
  if (!pid || !sid) return null;

  if (agentFlowSkillCatalog && !force) return agentFlowSkillCatalog;

  const data = await ctx.apiJson(
    `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/agent_flow/skills`
  );

  agentFlowSkillCatalog = data && data.ok ? data : null;
  return agentFlowSkillCatalog;
}

function mergeAgentFlowSkillSchema(schema) {
  if (!Array.isArray(schema)) return schema;

  const catalog = agentFlowSkillCatalog || {};
  const categories = catalog.categories && typeof catalog.categories === "object" ? catalog.categories : {};
  const dynamicSkills = [];

  Object.values(categories).forEach((rows) => {
    if (Array.isArray(rows)) {
      rows.forEach((skillId) => {
        const val = String(skillId || "").trim();
        if (val && !dynamicSkills.includes(val)) dynamicSkills.push(val);
      });
    }
  });

  const directSkills = catalog.skills && typeof catalog.skills === "object" ? Object.keys(catalog.skills) : [];
  directSkills.forEach((skillId) => {
    const val = String(skillId || "").trim();
    if (val && !dynamicSkills.includes(val)) dynamicSkills.push(val);
  });

  const dynamicCategories = Object.keys(categories).sort();

  return schema.map((field) => {
    if (!field || typeof field !== "object") return field;

    const key = String(field.key || "").trim();
    if (key !== "action_skills" && key !== "action_skill_categories") return field;

    const next = { ...field };
    const existing = Array.isArray(next.options || next.choices)
      ? (next.options || next.choices).map((v) => String(v || "").trim()).filter(Boolean)
      : [];

    if (key === "action_skills") {
      next.options = Array.from(new Set([...existing, ...dynamicSkills])).sort();
    }

    if (key === "action_skill_categories") {
      next.options = Array.from(new Set([...existing, ...dynamicCategories])).sort();
    }

    return next;
  });
}

function getAgentFlowSkillMeta(skillId) {
  const sid = String(skillId || "").trim();
  if (!sid) return null;
  const catalog = agentFlowSkillCatalog || {};
  const skills = catalog.skills && typeof catalog.skills === "object" ? catalog.skills : {};
  const meta = skills[sid];
  return meta && typeof meta === "object" ? meta : null;
}

function getAgentFlowSkillHoverText(skillId) {
  const sid = String(skillId || "").trim();
  const meta = getAgentFlowSkillMeta(sid) || {};
  const desc = String(meta.description || meta.short_description || meta.summary || "").trim();
  return desc ? `${sid}\n${desc}` : sid;
}

function getAgentFlowModelAdapters() {
  const catalog = agentFlowSkillCatalog || {};
  const adapters = catalog.model_adapters && typeof catalog.model_adapters === "object" ? catalog.model_adapters : {};
  return adapters;
}

function findModelAdapterForTool(toolId, values = {}) {
  const tool = String(toolId || "").trim();
  if (!tool.startsWith("models.")) return null;
  const adapters = getAgentFlowModelAdapters();
  const toolConfig = values?.tool_config && typeof values.tool_config === "object" ? values.tool_config : {};
  const params = toolConfig.params && typeof toolConfig.params === "object" ? toolConfig.params : {};
  const settings = params.settings && typeof params.settings === "object" ? params.settings : {};
  const explicit = String(
    params.model_runtime_adapter ||
    params.runtime_adapter ||
    settings.model_runtime_adapter ||
    settings.runtime_adapter ||
    settings.workflow_adapter ||
    ""
  ).trim();
  if (explicit && adapters[explicit]) return adapters[explicit];
  const wantedProfile = String(settings.model_deck_compat_manifest_id || settings.tested_profile || settings.compat_profile || "").trim().toLowerCase();
  const wantedFamily = String(settings.model_family || settings.architecture || settings.workflow_family || "").trim().toLowerCase();
  for (const adapter of Object.values(adapters)) {
    if (!adapter || typeof adapter !== "object") continue;
    const skills = adapter.skills && typeof adapter.skills === "object" ? Object.values(adapter.skills).map((v) => String(v || "").trim()) : [];
    if (!skills.includes(tool)) continue;
    const aliases = Array.isArray(adapter.aliases) ? adapter.aliases.map((v) => String(v || "").trim().toLowerCase()) : [];
    const families = Array.isArray(adapter.families) ? adapter.families.map((v) => String(v || "").trim().toLowerCase()) : [];
    if (wantedProfile && aliases.includes(wantedProfile)) return adapter;
    if (wantedFamily && families.includes(wantedFamily)) return adapter;
  }
  for (const adapter of Object.values(adapters)) {
    if (!adapter || typeof adapter !== "object") continue;
    const skills = adapter.skills && typeof adapter.skills === "object" ? Object.values(adapter.skills).map((v) => String(v || "").trim()) : [];
    if (skills.includes(tool)) return adapter;
  }
  return null;
}


function getRouterConfig(ctx, sid) {
  if (typeof ctx?.getRouterConfig === "function") {
    return ctx.getRouterConfig(sid, ctx?.state?.ui?.activePid);
  }
  ensureRouterState(ctx);
  const enabled = Array.isArray(ctx.state.router.enabled?.[sid]) ? ctx.state.router.enabled[sid].slice() : [];
  const settings = ctx.state.router.settings?.[sid] && typeof ctx.state.router.settings[sid] === "object" ? ctx.state.router.settings[sid] : {};
  return { enabled, settings };
}

function setRouterSettings(ctx, sid, pluginId, values) {
  if (typeof ctx?.setRouterSettings === "function") {
    ctx.setRouterSettings(sid, pluginId, values, ctx?.state?.ui?.activePid);
    return;
  }
  ensureRouterState(ctx);
  if (!ctx.state.router.settings[sid] || typeof ctx.state.router.settings[sid] !== "object") {
    ctx.state.router.settings[sid] = {};
  }
  ctx.state.router.settings[sid][pluginId] = values || {};
  ctx.saveState?.();
}

function setRouterEnabled(ctx, sid, pluginId, enabled) {
  if (typeof ctx?.setRouterEnabled === "function") {
    ctx.setRouterEnabled(sid, pluginId, enabled, ctx?.state?.ui?.activePid);
    return;
  }
  ensureRouterState(ctx);
  const key = String(sid || "");
  const pid = String(pluginId || "").trim();
  if (!key || !pid) return;
  const current = Array.isArray(ctx.state.router.enabled?.[key]) ? ctx.state.router.enabled[key].slice() : [];
  const has = current.includes(pid);
  if (enabled && !has) current.push(pid);
  if (!enabled && has) {
    ctx.state.router.enabled[key] = current.filter((item) => item !== pid);
  } else {
    ctx.state.router.enabled[key] = current;
  }
  ctx.saveState?.();
}

function getAgentFlowSettings(ctx, sid) {
  const cfg = getRouterConfig(ctx, sid);
  const settings = cfg.settings || {};
  const agent = settings.agent_flow;
  if (agent && typeof agent === "object") return agent;
  return {};
}

function updateAgentFlowSettings(ctx, sid, patch) {
  const current = getAgentFlowSettings(ctx, sid);
  const next = { ...current, ...(patch || {}) };
  setRouterSettings(ctx, sid, "agent_flow", next);
  return next;
}

function normalizeLoopMaxSetting(value, fallback = 16) {
  const n = Number(value);
  if (!Number.isFinite(n)) return Math.max(0, Math.trunc(fallback || 0));
  return Math.max(0, Math.trunc(n));
}

function normalizeTimeoutSetting(value, fallback = 45) {
  const n = Number(value);
  if (!Number.isFinite(n)) return Math.max(0, Math.trunc(fallback || 0));
  return Math.max(0, Math.trunc(n));
}

function normalizeBoolSetting(value, fallback = false) {
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value !== 0;
  if (typeof value === "string") {
    const s = value.trim().toLowerCase();
    if (!s) return !!fallback;
    if (["1", "true", "yes", "on"].includes(s)) return true;
    if (["0", "false", "no", "off"].includes(s)) return false;
  }
  return !!fallback;
}

function normalizeSandboxProfileSetting(value, fallback = "lightweight") {
  const s = String(value || "").trim().toLowerCase();
  if (s === "independent") return "independent";
  if (s === "lightweight") return "lightweight";
  return String(fallback || "lightweight").trim().toLowerCase() === "independent" ? "independent" : "lightweight";
}

function getStoredActiveFlowId(settings) {
  return String(settings?.agent_flow_active_workflow_id || "").trim();
}

function getStoredDefaultFlowId(settings) {
  return String(settings?.agent_flow_default_workflow_id || "").trim();
}

function getFlowNameByStableId(settings, flows, workflowId) {
  const wanted = String(workflowId || "").trim();
  if (!wanted || !flows || typeof flows !== "object") return "";
  const maps = [getFlowIdMap(settings), getDefaultFlowIdMap(settings)];
  for (const ids of maps) {
    for (const [name, rowId] of Object.entries(ids || {})) {
      if (String(rowId || "").trim() !== wanted) continue;
      if (flows[name]) return String(name || "").trim();
    }
  }
  return "";
}

function buildFlowSelectionPatch(settings, flowName, options = {}) {
  const mode = String(options.mode || "active").trim().toLowerCase() === "default" ? "default" : "active";
  const name = String(flowName || "").trim();
  const workflowId = name ? getFlowStableId(settings, name) : "";
  if (mode === "default") {
    return {
      agent_flow_default_flow: name,
      agent_flow_default_workflow_id: workflowId,
    };
  }
  if (!name) {
    return {
      agent_flow_active_flow: options.allowNoFlow ? NO_FLOW_VALUE : "",
      agent_flow_active_workflow_id: "",
    };
  }
  if (isSpecialFlowSelectionValue(name)) {
    return {
      agent_flow_active_flow: name,
      agent_flow_active_workflow_id: "",
    };
  }
  return {
    agent_flow_active_flow: name,
    agent_flow_active_workflow_id: workflowId,
  };
}

function resolveActiveFlowName(settings, flows) {
  const activeId = getStoredActiveFlowId(settings);
  const activeById = getFlowNameByStableId(settings, flows, activeId);
  if (activeById) return activeById;
  const active = typeof settings.agent_flow_active_flow === "string" ? settings.agent_flow_active_flow.trim() : "";
  if (active === NO_FLOW_VALUE) return "";
  if (isSpecialFlowSelectionValue(active)) return "";
  if (active && flows?.[active]) return active;
  if (Object.prototype.hasOwnProperty.call(settings || {}, "agent_flow_active_flow") && active === "") return "";
  const defaultId = getStoredDefaultFlowId(settings);
  const defaultById = getFlowNameByStableId(settings, flows, defaultId);
  if (defaultById) return defaultById;
  const fallback = typeof settings.agent_flow_default_flow === "string" ? settings.agent_flow_default_flow.trim() : "";
  if (fallback && flows?.[fallback]) return fallback;
  // Auto-select the first available flow when a session has flows loaded but
  // no explicit active/default is set. Preserve explicit "No flow" above.
  const names = flows && typeof flows === "object" ? Object.keys(flows) : [];
  return names.length ? String(names[0] || "") : "";
}

function hasNoFlowSelection(settings) {
  const active = typeof settings.agent_flow_active_flow === "string" ? settings.agent_flow_active_flow.trim() : "";
  return active === NO_FLOW_VALUE || (Object.prototype.hasOwnProperty.call(settings || {}, "agent_flow_active_flow") && active === "");
}

function isLLMAutoFlowSelectionValue(value) {
  return String(value || "").trim() === LLM_AUTOFLOW_FLOW_VALUE;
}

function isLLMSkillAutoFlowSelectionValue(value) {
  return String(value || "").trim() === LLM_SKILL_AUTOFLOW_FLOW_VALUE;
}

function isSpecialFlowSelectionValue(value) {
  return isLLMAutoFlowSelectionValue(value) || isLLMSkillAutoFlowSelectionValue(value);
}

function getSpecialFlowSelectionLabel(value) {
  const raw = String(value || "").trim();
  if (raw === LLM_AUTOFLOW_FLOW_VALUE) return "LLM select/create WorkFlows";
  if (raw === LLM_SKILL_AUTOFLOW_FLOW_VALUE) return "LLM run Skills";
  return "";
}

function getSpecialFlowSelectionDescription(value) {
  const raw = String(value || "").trim();
  if (raw === LLM_AUTOFLOW_FLOW_VALUE) return "Use the LLM AutoFlow plugin to search or create workflows before answering.";
  if (raw === LLM_SKILL_AUTOFLOW_FLOW_VALUE) return "Use the LLM Skill AutoFlow plugin to run Agent Flow skills directly before answering.";
  return "";
}

function isGuiPluginEnabled(ctx, pluginId) {
  const key = String(pluginId || "").trim();
  if (!key) return true;
  const enabled = ctx?.state?.pluginPrefs?.enabled;
  return !enabled || enabled[key] !== false;
}

function isLLMAutoFlowGuiAvailable(ctx) {
  return isGuiPluginEnabled(ctx, "llm_autoflow");
}

function isLLMSkillAutoFlowGuiAvailable(ctx) {
  return isGuiPluginEnabled(ctx, "llm_skill_autoflow");
}

function hasSpecialFlowSelection(settings) {
  const active = typeof settings?.agent_flow_active_flow === "string" ? settings.agent_flow_active_flow.trim() : "";
  return isSpecialFlowSelectionValue(active);
}

function getFlowDescription(flowDef) {
  if (!flowDef || typeof flowDef !== "object") return "";
  return String(flowDef.description || flowDef.info || flowDef.short_info || "").trim();
}

function normalizeFlowIdMap(value) {
  if (!value || typeof value !== "object") return {};
  const out = {};
  Object.entries(value).forEach(([name, workflowId]) => {
    const key = String(name || "").trim();
    const val = String(workflowId || "").trim();
    if (key && val) out[key] = val;
  });
  return out;
}

function getFlowIdMap(settings) {
  return normalizeFlowIdMap(settings?.agent_flow_flow_ids_by_name);
}

function getDefaultFlowIdMap(settings) {
  return normalizeFlowIdMap(settings?.agent_flow_default_flow_ids_by_name);
}

function getFlowStableId(settings, flowName) {
  const name = String(flowName || "").trim();
  if (!name) return "";
  const ids = getFlowIdMap(settings);
  const current = String(ids[name] || "").trim();
  if (current) return current;
  const fallback = getDefaultFlowIdMap(settings);
  return String(fallback[name] || "").trim();
}

function shortFlowStableId(workflowId) {
  const raw = String(workflowId || "").trim();
  if (!raw) return "";
  if (raw.length <= 18) return raw;
  return `${raw.slice(0, 10)}...${raw.slice(-6)}`;
}

function resolveFlowNameWithStableId(settings, flows, flowName, workflowId) {
  const byId = getFlowNameByStableId(settings, flows, workflowId);
  if (byId) return byId;
  const byName = String(flowName || "").trim();
  if (byName && flows?.[byName]) return byName;
  return "";
}

function normalizeSubflowPluginSettings(settings, flows, agentSettings) {
  const current = settings && typeof settings === "object" ? { ...settings } : {};
  const subflowName = resolveFlowNameWithStableId(agentSettings, flows, current.subflow_name, current.subflow_workflow_id);
  if (subflowName) {
    current.subflow_name = subflowName;
    current.subflow_workflow_id = getFlowStableId(agentSettings, subflowName);
  }
  const loopSubflowName = resolveFlowNameWithStableId(agentSettings, flows, current.loop_subflow_name, current.loop_subflow_workflow_id);
  if (loopSubflowName) {
    current.loop_subflow_name = loopSubflowName;
    current.loop_subflow_workflow_id = getFlowStableId(agentSettings, loopSubflowName);
  }
  return current;
}

function skillCategoryFromId(skillId) {
  const raw = String(skillId || "").trim();
  const dot = raw.indexOf(".");
  return dot > 0 ? raw.slice(0, dot) : "general";
}

function labelForSkillCategory(category) {
  return String(category || "general")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (m) => m.toUpperCase());
}

function normalizeSkillArray(value) {
  if (Array.isArray(value)) {
    return value.map((v) => String(v || "").trim()).filter(Boolean);
  }
  return String(value || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

function collectFlowSkillCategories(flowDef) {
  const nodes = flowDef && typeof flowDef === "object" && flowDef.nodes && typeof flowDef.nodes === "object"
    ? Object.values(flowDef.nodes)
    : [];
  const categories = new Set();
  nodes.forEach((node) => {
    const settings = node && typeof node.plugin_settings === "object" ? node.plugin_settings : {};
    normalizeSkillArray(settings.action_skill_categories).forEach((category) => {
      if (category) categories.add(category);
    });
    normalizeSkillArray(settings.action_skills).forEach((skillId) => {
      if (!skillId) return;
      categories.add(skillId.endsWith(".*") ? skillId.slice(0, -2) : skillCategoryFromId(skillId));
    });
    const toolId = String(settings?.tool_config?.tool || settings?.tool || "").trim();
    if (toolId && toolId.includes(".")) categories.add(skillCategoryFromId(toolId));
  });
  return Array.from(categories).sort();
}

function flowMatchesQuery(flowName, flowDef, query, selectedCategories = null) {
  const needle = String(query || "").trim().toLowerCase();
  const nodes = flowDef && typeof flowDef === "object" && flowDef.nodes && typeof flowDef.nodes === "object"
    ? Object.values(flowDef.nodes)
    : [];
  if (selectedCategories instanceof Set && selectedCategories.size) {
    const flowCategories = new Set(collectFlowSkillCategories(flowDef));
    let matchedCategory = false;
    selectedCategories.forEach((category) => {
      if (flowCategories.has(category)) matchedCategory = true;
    });
    if (!matchedCategory) return false;
  }
  if (!needle) return true;
  const hay = [
    String(flowName || ""),
    getFlowDescription(flowDef),
    ...nodes.map((node) => String(node?.label || node?.plugin_id || "").trim()),
    ...collectFlowSkillCategories(flowDef),
  ]
    .join("\n")
    .toLowerCase();
  return hay.includes(needle);
}

function mergeHiddenSubflowSettings(prevSettings, nextSettings) {
  const prev = prevSettings && typeof prevSettings === "object" ? prevSettings : {};
  const next = nextSettings && typeof nextSettings === "object" ? nextSettings : {};
  const merged = { ...next };
  HIDDEN_SUBFLOW_SETTINGS_KEYS.forEach((key) => {
    if (Object.prototype.hasOwnProperty.call(next, key)) return;
    if (Object.prototype.hasOwnProperty.call(prev, key)) {
      merged[key] = prev[key];
    }
  });
  return merged;
}

function summarizeFlow(flowName, flowDef) {
  const nodes = flowDef && typeof flowDef === "object" && flowDef.nodes && typeof flowDef.nodes === "object"
    ? flowDef.nodes
    : {};
  const nodeCount = Object.keys(nodes).length;
  const skills = Array.from(new Set(
    Object.values(nodes)
      .map((node) => String(node?.plugin_id || "").trim())
      .filter(Boolean)
  ));
  return {
    name: String(flowName || ""),
    description: getFlowDescription(flowDef),
    node_count: nodeCount,
    skills,
  };
}

function availableFlowSkillCategories(flows) {
  const counts = new Map();
  const allFlows = flows && typeof flows === "object" ? Object.values(flows) : [];
  allFlows.forEach((flowDef) => {
    const categories = new Set(collectFlowSkillCategories(flowDef));
    categories.forEach((category) => {
      counts.set(category, Number(counts.get(category) || 0) + 1);
    });
  });
  return Array.from(counts.entries())
    .map(([category, count]) => ({ category, count }))
    .sort((a, b) => a.category.localeCompare(b.category));
}

function buildFlowFilterControls({ flows, selectedCategories, onChange, menuClassName = "" }) {
  const resolveFlows = () => (typeof flows === "function" ? flows() : flows) || {};
  const wrap = document.createElement("div");
  wrap.className = "agent-flow-filter-wrap";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = `agent-flow-filter-btn${selectedCategories.size ? " active" : ""}`;
  btn.title = selectedCategories.size ? `Filter categories (${selectedCategories.size} active)` : "Filter by skill category";
  btn.setAttribute("aria-label", "Filter workflows by skill category");
  btn.textContent = "F";
  wrap.appendChild(btn);

  const menu = document.createElement("div");
  menu.className = `agent-flow-filter-menu hidden ${menuClassName}`.trim();
  wrap.appendChild(menu);

  const closeMenu = () => menu.classList.add("hidden");
  const toggleMenu = () => menu.classList.toggle("hidden");

  const renderMenu = () => {
    menu.innerHTML = "";
    const options = availableFlowSkillCategories(resolveFlows());
    const head = document.createElement("div");
    head.className = "agent-flow-filter-head";
    const title = document.createElement("span");
    title.textContent = "Skill categories";
    head.appendChild(title);
    if (selectedCategories.size) {
      const clearBtn = document.createElement("button");
      clearBtn.type = "button";
      clearBtn.className = "ghost";
      clearBtn.textContent = "Clear";
      clearBtn.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        selectedCategories.clear();
        btn.classList.remove("active");
        btn.title = "Filter by skill category";
        renderMenu();
        onChange();
      });
      head.appendChild(clearBtn);
    }
    menu.appendChild(head);

    const list = document.createElement("div");
    list.className = "agent-flow-filter-list";
    if (!options.length) {
      const empty = document.createElement("div");
      empty.className = "muted";
      empty.textContent = "No skill categories found in workflows.";
      list.appendChild(empty);
    } else {
      options.forEach(({ category, count }) => {
        const row = document.createElement("div");
        row.className = "agent-flow-filter-item";
        const label = document.createElement("label");
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = selectedCategories.has(category);
        cb.addEventListener("change", () => {
          if (cb.checked) selectedCategories.add(category);
          else selectedCategories.delete(category);
          btn.classList.toggle("active", selectedCategories.size > 0);
          btn.title = selectedCategories.size ? `Filter categories (${selectedCategories.size} active)` : "Filter by skill category";
          onChange();
          renderMenu();
        });
        const text = document.createElement("span");
        text.textContent = labelForSkillCategory(category);
        label.appendChild(cb);
        label.appendChild(text);
        row.appendChild(label);
        const countEl = document.createElement("span");
        countEl.className = "agent-flow-filter-count";
        countEl.textContent = String(count);
        row.appendChild(countEl);
        list.appendChild(row);
      });
    }
    menu.appendChild(list);
  };

  renderMenu();

  btn.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    toggleMenu();
  });
  menu.addEventListener("click", (event) => event.stopPropagation());
  document.addEventListener("click", closeMenu);
  wrap._agentFlowDestroy = () => {
    document.removeEventListener("click", closeMenu);
  };
  return wrap;
}

async function ensureRunnableFlowSettings(ctx, sid, pid) {
  const current = getAgentFlowSettings(ctx, sid);
  if (hasNoFlowSelection(current)) {
    return { settings: current, flowName: "", flowDef: null, reason: "no_flow_selected" };
  }

  let settings = current;
  let flows = settings.agent_flow_flows && typeof settings.agent_flow_flows === "object"
    ? settings.agent_flow_flows
    : {};
  let flowName = resolveActiveFlowName(settings, flows);
  let flowDef = flowName ? flows?.[flowName] : null;

  if (!flowName || !flowIsRunnable(flowDef)) {
    const serverPayload = await fetchProjectFlows(ctx, pid, sid);
    const serverFlows = serverPayload?.flows;
    if (serverFlows && typeof serverFlows === "object") {
      flows = deepClone(serverFlows);
      const cfg = {
        ...(getAgentFlowSettings(ctx, sid) || {}),
        agent_flow_flows: flows,
        agent_flow_flow_ids_by_name: normalizeFlowIdMap(serverPayload?.flowIdsByName),
        agent_flow_default_flow_ids_by_name: normalizeFlowIdMap(serverPayload?.defaultFlowIdsByName),
      };
      flowName = resolveActiveFlowName(cfg, flows);
      flowDef = flowName ? flows?.[flowName] : null;
      if (flowName && cfg.agent_flow_active_flow !== flowName && cfg.agent_flow_active_flow !== NO_FLOW_VALUE) {
        cfg.agent_flow_active_flow = flowName;
      }
      setRouterSettings(ctx, sid, "agent_flow", cfg);
      settings = cfg;
      updateBottomBar(ctx);
    }
  }

  if (!flowName) {
    return { settings, flowName: "", flowDef: null, reason: "no_active_flow" };
  }
  if (!flowIsRunnable(flowDef)) {
    return { settings, flowName, flowDef, reason: "flow_not_runnable" };
  }
  return { settings, flowName, flowDef, reason: "" };
}

function getAutoFlowSettings(ctx, sid) {
  const cfg = getRouterConfig(ctx, sid);
  const settings = cfg.settings || {};
  const auto = settings.autoflow;
  if (auto && typeof auto === "object") return auto;
  return {};
}

function isAutoFlowRouterEnabled(ctx, sid) {
  const cfg = getRouterConfig(ctx, sid);
  const enabled = Array.isArray(cfg?.enabled) ? cfg.enabled : [];
  return enabled.includes("autoflow");
}

function isLLMAutoFlowRouterEnabled(ctx, sid) {
  const cfg = getRouterConfig(ctx, sid);
  const enabled = Array.isArray(cfg?.enabled) ? cfg.enabled : [];
  const settings = cfg?.settings && typeof cfg.settings === "object" ? cfg.settings : {};
  const llm = settings.llm_autoflow;
  const llmSettings = llm && typeof llm === "object" ? llm : {};
  return enabled.includes("llm_autoflow") && llmSettings.llm_autoflow_enabled !== false;
}

function isLLMSkillAutoFlowRouterEnabled(ctx, sid) {
  const cfg = getRouterConfig(ctx, sid);
  const enabled = Array.isArray(cfg?.enabled) ? cfg.enabled : [];
  const settings = cfg?.settings && typeof cfg.settings === "object" ? cfg.settings : {};
  const llm = settings.llm_skill_autoflow;
  const llmSettings = llm && typeof llm === "object" ? llm : {};
  return enabled.includes("llm_skill_autoflow") && llmSettings.llm_skill_autoflow_enabled !== false;
}

function inferAutoFlowCreatorFlowName(agentSettings = {}, autoSettings = null) {
  const explicitAuto = String(
    autoSettings?.autoflow_creator_flow_name
    || agentSettings?.autoflow?.autoflow_creator_flow_name
    || ""
  ).trim();
  if (explicitAuto) return explicitAuto;
  const active = String(agentSettings?.agent_flow_active_flow || "").trim();
  const fallback = String(agentSettings?.agent_flow_default_flow || "").trim();
  const looksCreator = (name) => {
    const low = String(name || "").trim().toLowerCase();
    return low.startsWith("flow creator /") || low.startsWith("flow creator");
  };
  if (looksCreator(active)) return active;
  if (looksCreator(fallback)) return fallback;
  return "";
}

function hasWorkflowLikeAttachments(payload) {
  const ext = payload?.ext && typeof payload.ext === "object" ? payload.ext : {};
  const attachments = Array.isArray(ext.attachments) ? ext.attachments : [];
  return attachments.length > 0;
}

function looksLikeFileOrArtifactRequest(text) {
  const low = String(text || "").toLowerCase();
  if (!low) return false;
  if (/\/(uploads|app|data|repo)\//i.test(low)) return true;
  if (/[a-z]:\\/i.test(low)) return true;
  if (/\b[^\s]+\.(csv|tsv|xlsx|xls|json|txt|md|pdf|docx|pptx|zip|png|jpg|jpeg)\b/i.test(low)) return true;
  return /(spreadsheet|csv|excel|workbook|file|folder|directory|pdf|document|powerpoint|slides|upload|zip|repo|repository|codebase)/i.test(low);
}

function looksLikeLiveDataOrToolRequest(text) {
  const low = String(text || "").toLowerCase();
  if (!low) return false;
  return /(latest|today|current|recent|weather|forecast|stock|stocks|share price|price on|market cap|average volume|yahoo finance|world bank|imf|google scholar|arxiv|news|headline|web|online|browse|search|look up|find online|research|database|sql|email)/i.test(low);
}

function looksLikeStructuredWorkRequest(text) {
  const low = String(text || "").toLowerCase();
  if (!low) return false;
  return /(create|draft|prepare|build|design|plan|analyze|analyse|compare|review|extract|generate|write a|write an|make me|turn .* into|use .* to|flag|triage|summar)/i.test(low);
}

function shouldBypassAutoFlowForDirectQuestion(payload) {
  const text = String(payload?.text || "").trim();
  if (!text) return false;
  if (hasWorkflowLikeAttachments(payload)) return false;
  if (looksLikeFileOrArtifactRequest(text)) return false;
  if (looksLikeLiveDataOrToolRequest(text)) return false;
  if (looksLikeStructuredWorkRequest(text)) return false;
  if (text.length > 220) return false;
  if (/^\//.test(text)) return false;
  if (/\n/.test(text)) return false;
  return /^(what|what's|who|who's|where|when|why|how|is|are|can|could|would|do|does|did|explain|define|describe|summarize|tell me\b|tell me more about\b|tell me about\b)/i.test(text);
}

let bottomBarNode = null;
let bottomBarButton = null;
let bottomBarPopover = null;
let bottomBarCtx = null;
let bottomBarPopoverHost = null;
let bottomBarPopoverRenderKey = "";
let bottomBarPopoverListScrollTop = 0;
let bottomBarPopoverSearchTimer = null;
let sessionChangeHandler = null;
let progressNode = null;
let flowAlertNode = null;
let flowAlertButton = null;
let flowAlertCount = null;
let flowAlertPopover = null;
let flowAlertSelectedSid = "";
const flowRuns = new Map();
const flowStatusPollers = new Map();
let importPopover = null;
let importButtonNode = null;
let awfLibraryPopover = null;
let awfLibraryButtonNode = null;
let awfLibrarySearchTimer = null;
let awfLibraryFetchSeq = 0;
let awfLibraryLoading = false;
let awfLibraryLaunchLoading = false;
let awfLibraryState = { query: "", draftQuery: "", page: 1, pageSize: 12, total: 0, totalPages: 1, hiddenCount: 0, records: [] };
let bottomBarOutsideHandler = null;
let openTempLibraryRecordHandler = null;
let flowNavRequest = null; // { sid: string, flowName: string }
let bottomBarPopoverQuery = "";
let bottomBarPopoverSkillFilters = new Set();
let flowListSearchTimer = null;
const emptyFlowWarned = new Map(); // sid -> flowName
const directChatBypassBySid = new Map(); // sid -> ts for one-turn plain-chat bypass
const HIDDEN_SUBFLOW_SETTINGS_KEYS = new Set([
  "iteration_key",
  "iteration_keys",
  "subflow_input_map",
  "subflow_output_map",
  "subflow_workflow_id",
  "loop_subflow_workflow_id",
]);

function flowRunKey(sid, runId) {
  const rid = String(runId || "").trim();
  return rid || String(sid || "");
}

function agentFlowControlIcon(paused, pending) {
  if (pending) return '<span class="agent-flow-icon agent-flow-icon-spinner" aria-hidden="true"></span>';
  return paused
    ? '<span class="agent-flow-icon agent-flow-icon-play" aria-hidden="true"></span>'
    : '<span class="agent-flow-icon agent-flow-icon-pause" aria-hidden="true"></span>';
}

function normalizeFlowRunFlags(data) {
  const status = String(data?.status || "");
  const statusPaused = /^Paused\b/i.test(status.trim());
  const statusPausing = /^Pausing\b/i.test(status.trim());
  const paused = statusPaused || Boolean(data?.paused);
  const pauseRequested = !paused && (statusPausing || Boolean(data?.pause_requested || data?.pauseRequested));
  return { paused, pauseRequested, status };
}

function normalizeLoopCapMeta(data) {
  const loopCap = data?.loop_cap;
  if (!loopCap || typeof loopCap !== "object") return null;
  const source = String(loopCap.source || "").trim();
  const valueLabel = String(loopCap.value_label || "").trim();
  const retry = Number(loopCap.retry || 0);
  const kind = String(loopCap.kind || "").trim();
  const nodeLabel = String(loopCap.node_label || "").trim();
  if (!source && !valueLabel) return null;
  return {
    kind,
    source,
    value: Number(loopCap.value || 0),
    valueLabel: valueLabel || (Number(loopCap.value || 0) <= 0 ? "unlimited" : String(loopCap.value || "")),
    retry: Number.isFinite(retry) ? retry : 0,
    nodeLabel,
    targetId: String(loopCap.target_id || "").trim(),
  };
}

function renderLoopCapBadge(meta) {
  if (!meta) return null;
  const badge = document.createElement("div");
  badge.className = "agent-flow-loop-badge";
  const src = document.createElement("span");
  src.className = "src";
  src.textContent = `${meta.kind || "loop"} • ${meta.source || "unknown"}`;
  const val = document.createElement("span");
  val.className = "val";
  val.textContent = `${meta.valueLabel}`;
  badge.appendChild(src);
  badge.appendChild(val);
  if (meta.retry > 0) {
    const retry = document.createElement("span");
    retry.className = "src";
    retry.textContent = `retry ${meta.retry}`;
    badge.appendChild(retry);
  }
  const titleBits = [
    meta.nodeLabel ? `node=${meta.nodeLabel}` : "",
    meta.targetId ? `target=${meta.targetId}` : "",
    meta.source ? `source=${meta.source}` : "",
    meta.valueLabel ? `value=${meta.valueLabel}` : "",
    meta.retry > 0 ? `retry=${meta.retry}` : "",
  ].filter(Boolean);
  if (titleBits.length) badge.title = titleBits.join(" | ");
  return badge;
}

function stopFlowStatusPolling(sid, runId = "") {
  const key = flowRunKey(sid, runId);
  if (!key) return;
  const t = flowStatusPollers.get(key);
  if (t) {
    try { clearInterval(t); } catch {}
    flowStatusPollers.delete(key);
  }
}

function startFlowStatusPolling(ctx, sid, runId = "") {
  const key = flowRunKey(sid, runId);
  if (!key) return;
  stopFlowStatusPolling(sid, runId);
  const timer = setInterval(() => {
    const rs = flowRuns.get(key);
    if (!rs || !rs.running) {
      stopFlowStatusPolling(sid, runId);
      return;
    }
    void refreshFlowStatus(ctx, sid, runId);
  }, 1200);
  flowStatusPollers.set(key, timer);
}

function flowIsRunnable(flowDef) {
  if (!flowDef || typeof flowDef !== "object") return false;
  const nodes = flowDef.nodes || {};
  const start = flowDef.start;
  if (!start) return false;
  if (!nodes || typeof nodes !== "object") return false;
  if (!Object.keys(nodes).length) return false;
  return Boolean(nodes[start]);
}


function makeDefaultConditionRule() {
  return { kind: "rule", type: "always", value: "" };
}

function makeDefaultConditionGroup() {
  return { kind: "group", operator: "all", rules: [makeDefaultConditionRule()] };
}

function normalizeTransitionConditionNode(node) {
  const raw = node && typeof node === "object" ? node : {};
  if (Array.isArray(raw.rules)) {
    const operator = String(raw.operator || raw.mode || "all").trim().toLowerCase() === "any" ? "any" : "all";
    const rules = raw.rules.map((child) => normalizeTransitionConditionNode(child)).filter(Boolean);
    return {
      kind: "group",
      operator,
      rules: rules.length ? rules : [makeDefaultConditionRule()],
    };
  }
  return {
    kind: "rule",
    type: String(raw.type || "always").trim() || "always",
    value: String(raw.value || "").trim(),
  };
}

function normalizeTransitionCondition(condition) {
  const normalized = normalizeTransitionConditionNode(condition);
  if (normalized.kind === "group") return normalized;
  return { kind: "group", operator: "all", rules: [normalized] };
}

function isAlwaysConditionTree(condition) {
  const root = normalizeTransitionCondition(condition);
  return root.rules.length === 1 && root.rules[0]?.kind === "rule" && String(root.rules[0]?.type || "") === "always";
}

function singleConditionLabel(rule) {
  const c = rule && typeof rule === "object" ? rule : { type: "always", value: "" };
  if (c.type === "always") return "always";
  if (c.type === "no_changed_files") return "no changes";
  if (c.type === "changed_files_present") return "has changes";
  if (c.type === "bugs_present") return "bugs present";
  if (c.type === "no_bugs") return "no bugs";
  if (c.type === "handoff_contains") return c.value ? `handoff has "${c.value}"` : "handoff contains";
  if (c.type === "did_contains") return c.value ? `did has "${c.value}"` : "did contains";
  if (c.type === "output_contains") return c.value ? `output has "${c.value}"` : "output contains";
  if (c.type === "output_not_contains") return c.value ? `output lacks "${c.value}"` : "output not contains";
  if (c.type === "test_failures_gte") return c.value ? `test fails >= ${c.value}` : "test fails >=";
  if (c.type === "test_failures_lte") return c.value ? `test fails <= ${c.value}` : "test fails <=";
  return c.type;
}

function transitionConditionNodeLabel(node) {
  const current = node && typeof node === "object" ? node : makeDefaultConditionRule();
  if (current.kind === "group" || Array.isArray(current.rules)) {
    const group = normalizeTransitionCondition(current);
    const joiner = group.operator === "any" ? " OR " : " AND ";
    if (!group.rules.length) return "always";
    if (group.rules.length === 1) return transitionConditionNodeLabel(group.rules[0]);
    return `(${group.rules.map((rule) => transitionConditionNodeLabel(rule)).join(joiner)})`;
  }
  return singleConditionLabel(current);
}

function transitionConditionLabel(condition) {
  return transitionConditionNodeLabel(normalizeTransitionCondition(condition));
}

function choosePreviewTransition(node, nodes, visited) {
  const transitions = Array.isArray(node?.transitions) ? node.transitions : [];
  if (!transitions.length) return null;
  const forwardAlways = transitions.find((t) => {
    const target = String((t && typeof t === "object" ? t.target : t) || "").trim();
    if (!target || !nodes[target] || visited.has(target)) return false;
    return isAlwaysConditionTree(t?.condition);
  });
  if (forwardAlways) return forwardAlways;
  return transitions.find((t) => {
    const target = String((t && typeof t === "object" ? t.target : t) || "").trim();
    return Boolean(target && nodes[target] && !visited.has(target));
  }) || null;
}

function updateBottomBar(ctx) {
  if (!bottomBarButton) return;
  const sid = ctx.state.ui.activeSid;
  if (!sid) {
    bottomBarButton.disabled = true;
    bottomBarButton.querySelector(".label").textContent = "Flow";
    bottomBarButton.querySelector(".hint").textContent = "No session";
    return;
  }
  const settings = getAgentFlowSettings(ctx, sid);
  const flows = settings.agent_flow_flows || {};
  const names = Object.keys(flows).sort();
  bottomBarButton.disabled = false;
  const resolved = resolveActiveFlowName(settings, flows);
  const activeRaw = typeof settings.agent_flow_active_flow === "string" ? settings.agent_flow_active_flow.trim() : "";
  const specialLabel = ((activeRaw === LLM_AUTOFLOW_FLOW_VALUE && isLLMAutoFlowGuiAvailable(ctx)) || (activeRaw === LLM_SKILL_AUTOFLOW_FLOW_VALUE && isLLMSkillAutoFlowGuiAvailable(ctx)))
    ? getSpecialFlowSelectionLabel(activeRaw)
    : "";
  const display = specialLabel || resolved || "No flow";
  bottomBarButton.querySelector(".label").textContent = "Flow";
  bottomBarButton.querySelector(".hint").textContent = display;
  bottomBarButton.dataset.activeFlow = display === "No flow" ? "" : display;
  bottomBarButton.dataset.hasFlows = names.length ? "true" : "false";
  if (bottomBarPopover) {
    renderBottomBarPopover(ctx, { skipIfUnchanged: true });
  }
}

function closeBottomBarPopover() {
  if (!bottomBarPopover) return;
  bottomBarPopover.remove();
  bottomBarPopover = null;
  bottomBarPopoverHost = null;
  bottomBarPopoverRenderKey = "";
  bottomBarPopoverListScrollTop = 0;
}

function getBottomBarPopoverHost(ctx) {
  try {
    const embedCfg = typeof window !== "undefined" ? (window.__CHAT_JS_EMBED_CONFIG || {}) : {};
    const portal = embedCfg.overlayMount || embedCfg.portal || embedCfg.overlay || null;
    if (portal instanceof Element) return portal;
    if (typeof portal === "string") {
      const el = document.querySelector(portal) || document.getElementById(portal.replace(/^#/, ""));
      if (el) return el;
    }
  } catch (_err) {}
  try {
    const host = ctx?.getOverlayMount?.() || ctx?.getEmbedMount?.();
    if (host && host !== document.body && host !== document.documentElement) {
      return host;
    }
  } catch (_err) {}
  return document.body;
}

function getPopoverViewportMetrics() {
  const vv = window.visualViewport;
  const width = Math.max(0, Math.round(vv?.width || window.innerWidth || 0));
  const height = Math.max(0, Math.round(vv?.height || window.innerHeight || 0));
  const offsetLeft = Math.round(vv?.offsetLeft || 0);
  const offsetTop = Math.round(vv?.offsetTop || 0);
  return { width, height, offsetLeft, offsetTop, gutter: 12 };
}

function clampPopoverLeft(desiredLeft, popWidth) {
  const { width, offsetLeft, gutter } = getPopoverViewportMetrics();
  const maxLeft = Math.max(offsetLeft + gutter, offsetLeft + width - popWidth - gutter);
  return Math.min(Math.max(offsetLeft + gutter, desiredLeft), maxLeft);
}

function clampPopoverTop(desiredTop, popHeight) {
  const { height, offsetTop, gutter } = getPopoverViewportMetrics();
  const maxTop = Math.max(offsetTop + gutter, offsetTop + height - popHeight - gutter);
  return Math.min(Math.max(offsetTop + gutter, desiredTop), maxTop);
}

function positionPopoverAroundRect(popover, anchorRect, opts = {}) {
  if (!popover || !anchorRect) return;
  const { width, height, offsetTop, gutter } = getPopoverViewportMetrics();
  const popWidth = popover.offsetWidth || opts.fallbackWidth || 320;
  const popHeight = popover.offsetHeight || opts.fallbackHeight || 240;
  const align = opts.align === "left" ? "left" : "right";
  const preferredLeft = align === "left" ? anchorRect.left : (anchorRect.right - popWidth);
  const left = clampPopoverLeft(preferredLeft, popWidth);
  const belowTop = anchorRect.bottom + (opts.offsetY ?? 8);
  const aboveTop = anchorRect.top - popHeight - (opts.offsetY ?? 8);
  const fitsBelow = belowTop + popHeight <= offsetTop + height - gutter;
  const top = clampPopoverTop(fitsBelow ? belowTop : aboveTop, popHeight);
  popover.style.left = `${left}px`;
  popover.style.top = `${top}px`;
  popover.style.right = "auto";
  popover.style.bottom = "auto";
}

function positionBottomBarPopover() {
  if (!bottomBarPopover || !bottomBarButton) return;
  const rect = bottomBarButton.getBoundingClientRect();
  const { width, gutter } = getPopoverViewportMetrics();
  const targetWidth = Math.min(Math.max(280, rect.width + 80), Math.max(240, width - (gutter * 2)));
  bottomBarPopover.style.width = `${targetWidth}px`;
  positionPopoverAroundRect(bottomBarPopover, rect, {
    align: "right",
    fallbackWidth: targetWidth,
    fallbackHeight: 320,
    offsetY: 8,
  });
}

function buildFlowPreview(flowDef, maxNodes = 6) {
  if (!flowDef || typeof flowDef !== "object") return [];
  const nodes = flowDef.nodes || {};
  const ids = Object.keys(nodes || {});
  if (!ids.length) return [];
  const start = flowDef.start;
  const order = [];
  const visited = new Set();
  let current = start && nodes[start] ? start : ids[0];
  while (current && nodes[current] && order.length < maxNodes && !visited.has(current)) {
    const node = nodes[current] || {};
    order.push({
      node_id: current,
      label: node.label || current,
      plugin_id: node.plugin_id || "chat",
      plugin_settings: node.plugin_settings || {},
    });
    visited.add(current);
    let nextId = null;
    const chosen = choosePreviewTransition(node, nodes, visited);
    const target = chosen && typeof chosen === "object" ? chosen.target : chosen;
    if (typeof target === "string" && target && nodes[target] && !visited.has(target)) {
      nextId = target;
    }
    current = nextId;
  }
  // If the graph is not a simple chain, fill with remaining nodes so the user sees more context.
  if (order.length < Math.min(maxNodes, ids.length)) {
    ids
      .filter((id) => !visited.has(id))
      .slice(0, maxNodes - order.length)
      .forEach((id) => {
        const node = nodes[id] || {};
        order.push({ node_id: id, label: node.label || id, plugin_id: node.plugin_id || "chat", plugin_settings: node.plugin_settings || {} });
      });
  }
  return order;
}

function bottomBarPopoverKey(settings, flows, names, activeRaw, selectedName) {
  const defaultFlow = String(settings.agent_flow_default_flow || "").trim();
  const parts = names.map((name) => {
    const flow = flows?.[name] || {};
    const nodes = flow.nodes && typeof flow.nodes === "object" ? flow.nodes : {};
    return `${name}:${flow.start || ""}:${Object.keys(nodes).length}`;
  });
  return JSON.stringify({
    sid: ctxSafeSid(),
    active: activeRaw || "",
    selected: selectedName || "",
    defaultFlow,
    flows: parts,
  });
}

function ctxSafeSid() {
  try {
    return String(bottomBarCtx?.state?.ui?.activeSid || "");
  } catch {
    return "";
  }
}

function rememberBottomBarListScroll() {
  if (!bottomBarPopover) return;
  const list = bottomBarPopover.querySelector(".list");
  if (list) bottomBarPopoverListScrollTop = Number(list.scrollTop || 0);
}

function renderBottomBarPopover(ctx, opts = {}) {
  if (!bottomBarPopover || !bottomBarButton) return;
  const sid = ctx.state.ui.activeSid;
  const settings = getAgentFlowSettings(ctx, sid);
  const flows = settings.agent_flow_flows || {};
  const names = Object.keys(flows).sort();
  const activeRaw = typeof settings.agent_flow_active_flow === "string" ? settings.agent_flow_active_flow.trim() : "";
  const activeExplicit = Object.prototype.hasOwnProperty.call(settings || {}, "agent_flow_active_flow");
  const selectedName = activeRaw && activeRaw !== NO_FLOW_VALUE && !isSpecialFlowSelectionValue(activeRaw) && flows?.[activeRaw] ? activeRaw : "";
  const renderKey = bottomBarPopoverKey(settings, flows, names, activeRaw, selectedName, isLLMAutoFlowRouterEnabled(ctx, sid), isLLMSkillAutoFlowRouterEnabled(ctx, sid));
  if (opts.skipIfUnchanged && bottomBarPopoverRenderKey === renderKey) {
    positionBottomBarPopover();
    return;
  }
  rememberBottomBarListScroll();
  bottomBarPopoverRenderKey = renderKey;
  Array.from(bottomBarPopover.querySelectorAll(".agent-flow-filter-wrap")).forEach((el) => {
    if (typeof el._agentFlowDestroy === "function") el._agentFlowDestroy();
  });

  bottomBarPopover.innerHTML = "";
  const title = document.createElement("h4");
  const titleBtn = document.createElement("button");
  titleBtn.type = "button";
  titleBtn.className = "name";
  titleBtn.textContent = "Agent Flow";
  titleBtn.title = "Open Agent Flow editor";
  titleBtn.addEventListener("click", (event) => {
    event.stopPropagation();
    closeBottomBarPopover();
    ctx.openPluginPanel?.(meta.plugin_id, { openModal: true });
  });
  title.appendChild(titleBtn);
  bottomBarPopover.appendChild(title);

  const searchRow = document.createElement("div");
  searchRow.className = "agent-flow-search-row";
  const searchShell = document.createElement("div");
  searchShell.className = "agent-flow-search-shell";
  const search = document.createElement("input");
  search.type = "search";
  search.className = "agent-flow-popover-search";
  search.placeholder = "Search workflows";
  search.style.width = "100%";
  search.value = bottomBarPopoverQuery;
  search.addEventListener("input", () => {
    bottomBarPopoverQuery = String(search.value || "");
    const selectionStart = search.selectionStart;
    const selectionEnd = search.selectionEnd;
    if (bottomBarPopoverSearchTimer) clearTimeout(bottomBarPopoverSearchTimer);
    bottomBarPopoverSearchTimer = setTimeout(() => {
      bottomBarPopoverSearchTimer = null;
      renderBottomBarPopover(ctx, {
        focusSearch: true,
        selectionStart,
        selectionEnd,
      });
    }, FLOW_SEARCH_IDLE_MS);
  });
  searchShell.appendChild(search);
  const filterControls = buildFlowFilterControls({
    flows: () => flows,
    selectedCategories: bottomBarPopoverSkillFilters,
    menuClassName: "bottom-bar-filter-menu",
    onChange: () => renderBottomBarPopover(ctx, { focusSearch: true }),
  });
  searchShell.appendChild(filterControls);
  searchRow.appendChild(searchShell);
  bottomBarPopover.appendChild(searchRow);

  const list = document.createElement("div");
  list.className = "list";
  list.addEventListener("scroll", () => {
    bottomBarPopoverListScrollTop = Number(list.scrollTop || 0);
  }, { passive: true });

  function addItem({ name, flowDef, isNone, specialValue = "", specialLabel = "", specialDescription = "" }) {
    const item = document.createElement("div");
    item.className = "item";
    const isSpecial = Boolean(specialValue);
    const isSelected = isNone
      ? (activeRaw === NO_FLOW_VALUE || (activeExplicit && activeRaw === ""))
      : isSpecial
        ? activeRaw === specialValue
        : name === selectedName;
    if (isSelected) item.classList.add("selected");

    const metaCol = document.createElement("div");
    metaCol.className = "meta";

    const nameBtn = document.createElement("button");
    nameBtn.type = "button";
    nameBtn.className = "name";
    nameBtn.textContent = isNone ? "No flow" : (specialLabel || name);
    nameBtn.disabled = Boolean(isNone);
      if (!isNone && !isSpecial) {
        nameBtn.addEventListener("click", (event) => {
          event.stopPropagation();
          const sid2 = String(ctx.state?.ui?.activeSid || "").trim();
          if (!sid2) return;
          const currentSettings = getAgentFlowSettings(ctx, sid2) || {};
          updateAgentFlowSettings(ctx, sid2, buildFlowSelectionPatch(currentSettings, name, { mode: "active" }));
          ctx.saveState?.();
          updateBottomBar(ctx);
          flowNavRequest = { sid: sid2, flowName: name };
          closeBottomBarPopover();
        ctx.openPluginPanel?.(meta.plugin_id, { openModal: true });
      });
    }
    metaCol.appendChild(nameBtn);

    const nodes = flowDef?.nodes && typeof flowDef.nodes === "object" ? flowDef.nodes : {};
    const nodeCount = isNone || isSpecial ? 0 : Object.keys(nodes || {}).length;
    const sub = document.createElement("div");
    sub.className = "sub";
    const defaultFlow = String(settings.agent_flow_default_flow || "").trim();
    const defaultTag = !isNone && !isSpecial && defaultFlow && defaultFlow === name ? " (default)" : "";
    const start = !isNone && !isSpecial ? String(flowDef?.start || "").trim() : "";
    const workflowId = !isNone && !isSpecial ? getFlowStableId(settings, name) : "";
    const shortId = workflowId ? ` | ID: ${shortFlowStableId(workflowId)}` : "";
    sub.textContent = isNone
      ? "Bypass flows and chat normally."
      : isSpecial
        ? specialDescription
        : `${nodeCount} node${nodeCount === 1 ? "" : "s"}${defaultTag}${start ? ` | start: ${start}` : ""}${shortId}`;
    metaCol.appendChild(sub);

    if (!isNone && !isSpecial) {
      const preview = buildFlowPreview(flowDef, 6);
      if (preview.length) {
        const nodesList = document.createElement("div");
        nodesList.className = "nodes";
        preview.forEach((n) => {
          const row = document.createElement("div");
          row.className = "node";
          const label = document.createElement("div");
          label.textContent = n.label || n.node_id || "";
          const pid = document.createElement("div");
          pid.className = "pid";
          const basePid = n.plugin_id || "chat";
          if (basePid === "agent_flow_subflow") {
            const sf = String((n.plugin_settings || {}).subflow_name || "").trim();
            pid.textContent = sf ? `${basePid} -> ${sf}` : basePid;
          } else {
            pid.textContent = basePid;
          }
          row.appendChild(label);
          row.appendChild(pid);
          nodesList.appendChild(row);
        });
        const remaining = Math.max(0, nodeCount - preview.length);
        if (remaining > 0) {
          const more = document.createElement("div");
          more.className = "sub";
          more.textContent = `+${remaining} more...`;
          nodesList.appendChild(more);
        }
        metaCol.appendChild(nodesList);
      } else {
        const muted = document.createElement("div");
        muted.className = "muted";
        muted.textContent = "No nodes.";
        metaCol.appendChild(muted);
      }
    }

    const actions = document.createElement("div");
    actions.className = "actions";
    const selectBtn = document.createElement("button");
    selectBtn.type = "button";
    selectBtn.className = "select-btn";
    selectBtn.textContent = isSelected ? "Selected" : "Select";
    selectBtn.disabled = Boolean(isSelected);
    selectBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      const sid2 = ctx.state.ui.activeSid;
      if (!sid2) return;
      const currentSettings = getAgentFlowSettings(ctx, sid2) || {};
      updateAgentFlowSettings(
        ctx,
        sid2,
        isNone
          ? buildFlowSelectionPatch(currentSettings, "", { mode: "active", allowNoFlow: true })
          : buildFlowSelectionPatch(currentSettings, isSpecial ? specialValue : name, { mode: "active" })
      );
      ctx.saveState?.();
      closeBottomBarPopover();
      updateBottomBar(ctx);
    });
    actions.appendChild(selectBtn);

    item.appendChild(metaCol);
    item.appendChild(actions);
    list.appendChild(item);
  }

  const filteredNames = names.filter((name) => flowMatchesQuery(name, flows[name], bottomBarPopoverQuery, bottomBarPopoverSkillFilters));
  addItem({ name: "", flowDef: null, isNone: true });
  if (isLLMAutoFlowGuiAvailable(ctx) && isLLMAutoFlowRouterEnabled(ctx, sid)) {
    addItem({
      name: "",
      flowDef: null,
      isNone: false,
      specialValue: LLM_AUTOFLOW_FLOW_VALUE,
      specialLabel: getSpecialFlowSelectionLabel(LLM_AUTOFLOW_FLOW_VALUE),
      specialDescription: getSpecialFlowSelectionDescription(LLM_AUTOFLOW_FLOW_VALUE),
    });
  }
  if (isLLMSkillAutoFlowGuiAvailable(ctx) && isLLMSkillAutoFlowRouterEnabled(ctx, sid)) {
    addItem({
      name: "",
      flowDef: null,
      isNone: false,
      specialValue: LLM_SKILL_AUTOFLOW_FLOW_VALUE,
      specialLabel: getSpecialFlowSelectionLabel(LLM_SKILL_AUTOFLOW_FLOW_VALUE),
      specialDescription: getSpecialFlowSelectionDescription(LLM_SKILL_AUTOFLOW_FLOW_VALUE),
    });
  }
  if (!names.length) {
    const empty = document.createElement("div");
    empty.className = "muted";
    empty.textContent = "No flows yet.";
    list.appendChild(empty);
  } else if (!filteredNames.length) {
    const empty = document.createElement("div");
    empty.className = "muted";
    empty.textContent = "No matching workflows.";
    list.appendChild(empty);
  } else {
    filteredNames.forEach((name) => addItem({ name, flowDef: flows[name], isNone: false }));
  }

  bottomBarPopover.appendChild(list);
  if (bottomBarPopoverListScrollTop > 0) {
    requestAnimationFrame(() => {
      if (!bottomBarPopover) return;
      const nextList = bottomBarPopover.querySelector(".list");
      if (nextList) nextList.scrollTop = bottomBarPopoverListScrollTop;
    });
  }
  if (opts.focusSearch) {
    requestAnimationFrame(() => {
      const nextSearch = bottomBarPopover?.querySelector(".agent-flow-popover-search");
      if (!(nextSearch instanceof HTMLInputElement)) return;
      nextSearch.focus({ preventScroll: true });
      const start = Number.isFinite(opts.selectionStart) ? opts.selectionStart : nextSearch.value.length;
      const end = Number.isFinite(opts.selectionEnd) ? opts.selectionEnd : start;
      try {
        nextSearch.setSelectionRange(start, end);
      } catch {}
    });
  }
  positionBottomBarPopover();
}

function ensureBottomBar(ctx) {
  if (bottomBarNode) {
    bottomBarCtx = ctx;
    updateBottomBar(ctx);
    refreshFlowStatus(ctx, ctx.state.ui.activeSid);
    return bottomBarNode;
  }
  bottomBarCtx = ctx;
  const wrap = document.createElement("div");
  wrap.className = "agent-flow-bar";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "agent-flow-bar-btn";
  btn.innerHTML = `<span class="label">Flow</span><span class="hint">No flow</span><span aria-hidden="true">&#9662;</span>`;
  btn.addEventListener("click", (event) => {
    event.stopPropagation();
    if (bottomBarPopover) {
      closeBottomBarPopover();
      return;
    }
    bottomBarPopover = document.createElement("div");
    bottomBarPopover.className = "agent-flow-popover";
    bottomBarPopover.style.position = "fixed";
    bottomBarPopover.style.zIndex = "2147483200";
    bottomBarPopover.style.pointerEvents = "auto";
    bottomBarPopover.style.minWidth = "240px";
    bottomBarPopover.style.maxWidth = "320px";
    bottomBarPopoverHost = getBottomBarPopoverHost(ctx);
    bottomBarPopoverHost.appendChild(bottomBarPopover);
    renderBottomBarPopover(ctx);
  });
  wrap.appendChild(btn);
  bottomBarNode = wrap;
  bottomBarButton = btn;
  updateBottomBar(ctx);
  refreshFlowStatus(ctx, ctx.state.ui.activeSid);
  if (!sessionChangeHandler) {
    sessionChangeHandler = () => {
      if (bottomBarCtx) updateBottomBar(bottomBarCtx);
      if (bottomBarCtx) updateProgressPanel(bottomBarCtx, bottomBarCtx.state.ui.activeSid);
      if (bottomBarCtx) updateFlowAlert(bottomBarCtx);
      if (bottomBarCtx) refreshFlowStatus(bottomBarCtx, bottomBarCtx.state.ui.activeSid);
      if (bottomBarCtx) {
        const pid = bottomBarCtx.state.ui.activePid;
        const sid = bottomBarCtx.state.ui.activeSid;
        fetchProjectFlows(bottomBarCtx, pid, sid).then((serverPayload) => {
          const flows = serverPayload?.flows;
          if (!flows || typeof flows !== "object") return;
          const cfg = {
            ...(getAgentFlowSettings(bottomBarCtx, sid) || {}),
            agent_flow_flows: flows,
            agent_flow_flow_ids_by_name: normalizeFlowIdMap(serverPayload?.flowIdsByName),
            agent_flow_default_flow_ids_by_name: normalizeFlowIdMap(serverPayload?.defaultFlowIdsByName),
          };
          setRouterSettings(bottomBarCtx, sid, "agent_flow", cfg);
          updateBottomBar(bottomBarCtx);
        });
      }
    };
    document.addEventListener(SESSION_CHANGE_EVENT, sessionChangeHandler);
  }
  if (!bottomBarOutsideHandler) {
    bottomBarOutsideHandler = (event) => {
      if (bottomBarPopover && bottomBarButton) {
        if (!bottomBarPopover.contains(event.target) && !bottomBarButton.contains(event.target)) {
          closeBottomBarPopover();
        }
      }
      if (importPopover && !importPopover.contains(event.target) && !(importButtonNode && importButtonNode.contains(event.target))) {
        closeImportPopover();
      }
      if (awfLibraryPopover && !awfLibraryPopover.contains(event.target) && !(awfLibraryButtonNode && awfLibraryButtonNode.contains(event.target))) {
        closeAwfLibraryPopover();
      }
    };
    document.addEventListener("click", bottomBarOutsideHandler);
    window.addEventListener("resize", positionBottomBarPopover);
  }
  return wrap;
}

function ensureProgressPanel(ctx) {
  if (progressNode) return progressNode;
  const panel = document.createElement("div");
  panel.className = "agent-flow-progress hidden";
  const head = document.createElement("div");
  head.className = "agent-flow-progress-head";
  const control = document.createElement("button");
  control.type = "button";
  control.className = "agent-flow-progress-control";
  control.title = "Pause flow";
  control.innerHTML = agentFlowControlIcon(false, false);
  const title = document.createElement("div");
  title.className = "agent-flow-progress-title";
  head.appendChild(control);
  head.appendChild(title);
  panel.appendChild(head);
  const status = document.createElement("div");
  status.className = "agent-flow-progress-status";
  panel.appendChild(status);
  const meta = document.createElement("div");
  meta.className = "agent-flow-progress-meta";
  panel.appendChild(meta);
  const list = document.createElement("div");
  list.className = "agent-flow-progress-list";
  panel.appendChild(list);
  progressNode = panel;
  progressNode._control = control;
  progressNode._title = title;
  progressNode._status = status;
  progressNode._meta = meta;
  progressNode._list = list;
  return panel;
}

function closeFlowAlertPopover() {
  if (!flowAlertPopover) return;
  flowAlertPopover.remove();
  flowAlertPopover = null;
}

function getOrderedFlowRuns() {
  return Array.from(flowRuns.entries())
    .map(([key, state]) => ({ key, ...(state || {}) }))
    .sort((a, b) => {
      if (Boolean(a.running) !== Boolean(b.running)) return a.running ? -1 : 1;
      return Number(b.updatedAt || 0) - Number(a.updatedAt || 0);
    });
}

function renderFlowAlertDetail(detailNode, state) {
  if (!detailNode) return;
  detailNode.innerHTML = "";
  if (!state) {
    const empty = document.createElement("div");
    empty.className = "agent-flow-alert-empty";
    empty.textContent = "No flow run selected.";
    detailNode.appendChild(empty);
    return;
  }
  const title = document.createElement("div");
  title.className = "agent-flow-alert-detail-title";
  title.textContent = `${state.flowName || "Agent Flow"}${state.runId ? ` • ${state.runId}` : ""}`;
  detailNode.appendChild(title);
  const status = document.createElement("div");
  status.className = "agent-flow-alert-sub";
  status.textContent = state.status || (state.running ? "Running" : "Idle");
  detailNode.appendChild(status);
  const loopBadge = renderLoopCapBadge(state.loopCap);
  if (loopBadge) detailNode.appendChild(loopBadge);
  (state.steps || []).forEach((step) => {
    const row = document.createElement("div");
    row.className = "agent-flow-progress-item";
    const label = document.createElement("div");
    label.className = "label";
    label.textContent = step.label || step.node_id || "";
    const statusNode = document.createElement("div");
    statusNode.className = "state";
    let stateText = step.state || "";
    const output = String(step.output || "").trim();
    if (output) {
      const short = output.length > 80 ? `${output.slice(0, 77)}...` : output;
      stateText = stateText ? `${stateText} • ${short}` : short;
    }
    statusNode.textContent = stateText;
    row.appendChild(label);
    row.appendChild(statusNode);
    detailNode.appendChild(row);
  });
}

function renderFlowAlertPopover(ctx) {
  if (!flowAlertPopover || !flowAlertButton) return;
  const prevList = flowAlertPopover.querySelector(".agent-flow-alert-list");
  const prevDetail = flowAlertPopover.querySelector(".agent-flow-alert-detail");
  const listStickBottom = prevList
    ? (prevList.scrollHeight - prevList.clientHeight - prevList.scrollTop) <= 24
    : true;
  const detailStickBottom = prevDetail
    ? (prevDetail.scrollHeight - prevDetail.clientHeight - prevDetail.scrollTop) <= 24
    : true;
  const listScrollTop = prevList ? prevList.scrollTop : 0;
  const detailScrollTop = prevDetail ? prevDetail.scrollTop : 0;
  const runs = getOrderedFlowRuns();
  const currentSid = String(ctx?.state?.ui?.activeSid || "");
  if (!flowAlertSelectedSid || !runs.some((r) => r.key === flowAlertSelectedSid)) {
    flowAlertSelectedSid = (runs.find((r) => r.sid === currentSid) || runs[0] || {}).key || "";
  }
  flowAlertPopover.innerHTML = "";
  flowAlertPopover.onclick = (event) => event.stopPropagation();
  const head = document.createElement("div");
  head.className = "agent-flow-alert-head";
  const title = document.createElement("div");
  title.className = "agent-flow-alert-title";
  title.textContent = "Agent Flows";
  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "select-btn";
  closeBtn.textContent = "Close";
  closeBtn.addEventListener("click", () => closeFlowAlertPopover());
  head.appendChild(title);
  head.appendChild(closeBtn);
  flowAlertPopover.appendChild(head);

  const body = document.createElement("div");
  body.className = "agent-flow-alert-body";
  const list = document.createElement("div");
  list.className = "agent-flow-alert-list";
  const detail = document.createElement("div");
  detail.className = "agent-flow-alert-detail";
  body.appendChild(list);
  body.appendChild(detail);

  if (!runs.length) {
    const empty = document.createElement("div");
    empty.className = "agent-flow-alert-empty";
    empty.textContent = "No agent flow runs in queue.";
    list.appendChild(empty);
  } else {
    runs.forEach((state) => {
      const item = document.createElement("div");
      item.className = "agent-flow-alert-item";
      if (state.key === flowAlertSelectedSid) item.classList.add("active");
      const top = document.createElement("div");
      top.className = "agent-flow-alert-item-top";
      const name = document.createElement("div");
      name.textContent = state.flowName || "Agent Flow";
      const pill = document.createElement("div");
      pill.className = "agent-flow-alert-pill";
      const flags = normalizeFlowRunFlags(state);
      pill.textContent = flags.pauseRequested ? "pausing" : (flags.paused ? "paused" : (state.running ? "running" : "idle"));
      top.appendChild(name);
      top.appendChild(pill);
      const sub = document.createElement("div");
      sub.className = "agent-flow-alert-sub";
      sub.textContent = `${state.status || "-"}${state.sid ? ` • sid ${state.sid}` : ""}`;
      item.appendChild(top);
      item.appendChild(sub);
      item.addEventListener("click", (event) => {
        event.stopPropagation();
        flowAlertSelectedSid = state.key;
        renderFlowAlertPopover(ctx);
      });
      list.appendChild(item);
    });
  }
  const selected = runs.find((r) => r.key === flowAlertSelectedSid) || runs[0] || null;
  renderFlowAlertDetail(detail, selected);
  flowAlertPopover.appendChild(body);
  if (prevList) {
    list.scrollTop = listStickBottom ? list.scrollHeight : listScrollTop;
  }
  if (prevDetail) {
    detail.scrollTop = detailStickBottom ? detail.scrollHeight : detailScrollTop;
  }
  const rect = flowAlertButton.getBoundingClientRect();
  positionPopoverAroundRect(flowAlertPopover, rect, {
    align: "right",
    fallbackWidth: 440,
    fallbackHeight: 320,
    offsetY: 8,
  });
}

function updateFlowAlert(ctx) {
  if (!flowAlertButton || !flowAlertCount) return;
  const runs = getOrderedFlowRuns();
  const runningCount = runs.filter((r) => r.running).length;
  flowAlertCount.textContent = String(runningCount);
  flowAlertCount.style.display = runningCount ? "inline-flex" : "none";
  flowAlertButton.title = runningCount ? `${runningCount} agent flow run(s)` : "No running agent flows";
  if (flowAlertPopover) renderFlowAlertPopover(ctx);
}

function ensureFlowAlert(ctx) {
  if (flowAlertNode) {
    updateFlowAlert(ctx);
    return flowAlertNode;
  }
  const wrap = document.createElement("div");
  wrap.className = "agent-flow-alert-wrap";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "agent-flow-alert-btn";
  btn.innerHTML = `<span aria-hidden="true">&#9888;</span>`;
  const count = document.createElement("span");
  count.className = "agent-flow-alert-count";
  count.style.display = "none";
  btn.appendChild(count);
  btn.addEventListener("click", (event) => {
    event.stopPropagation();
    if (flowAlertPopover) {
      closeFlowAlertPopover();
      return;
    }
    flowAlertPopover = document.createElement("div");
    flowAlertPopover.className = "agent-flow-alert-popover";
    document.body.appendChild(flowAlertPopover);
    renderFlowAlertPopover(ctx);
  });
  wrap.appendChild(btn);
  flowAlertNode = wrap;
  flowAlertButton = btn;
  flowAlertCount = count;
  updateFlowAlert(ctx);
  if (!bottomBarOutsideHandler) {
    bottomBarOutsideHandler = (event) => {
      if (bottomBarPopover && !bottomBarPopover.contains(event.target) && !bottomBarButton?.contains(event.target)) {
        closeBottomBarPopover();
      }
      if (flowAlertPopover && !flowAlertPopover.contains(event.target) && !flowAlertButton?.contains(event.target)) {
        closeFlowAlertPopover();
      }
      if (importPopover && !importPopover.contains(event.target) && !(importButtonNode && importButtonNode.contains(event.target))) {
        closeImportPopover();
      }
      if (awfLibraryPopover && !awfLibraryPopover.contains(event.target) && !(awfLibraryButtonNode && awfLibraryButtonNode.contains(event.target))) {
        closeAwfLibraryPopover();
      }
    };
    document.addEventListener("click", bottomBarOutsideHandler);
    window.addEventListener("resize", () => {
      positionBottomBarPopover();
      if (flowAlertPopover && bottomBarCtx) renderFlowAlertPopover(bottomBarCtx);
    });
  }
  return wrap;
}

function updateProgressPanel(ctx, sid) {
  if (!progressNode) return;
  const state = getOrderedFlowRuns().find((r) => String(r.sid || "") === String(sid || "") && r.running);
  if (!state || !state.running) {
    progressNode.classList.add("hidden");
    return;
  }
  progressNode.classList.remove("hidden");
  progressNode._title.textContent = `Flow: ${state.flowName || ""}`.trim();
  progressNode._status.textContent = state.status || "";
  if (progressNode._meta) {
    progressNode._meta.innerHTML = "";
    const loopBadge = renderLoopCapBadge(state.loopCap);
    if (loopBadge) progressNode._meta.appendChild(loopBadge);
  }
  if (progressNode._control) {
    const flags = normalizeFlowRunFlags(state);
    const paused = flags.paused;
    const pending = flags.pauseRequested;
    progressNode._control.style.display = state.running ? "inline-flex" : "none";
    progressNode._control.innerHTML = agentFlowControlIcon(paused, pending);
    progressNode._control.title = pending ? "Pausing flow" : (paused ? "Resume flow" : "Pause flow");
    progressNode._control.setAttribute("aria-label", progressNode._control.title);
    progressNode._control.disabled = pending;
    progressNode._control.onclick = async (event) => {
      event.preventDefault();
      event.stopPropagation();
      await setFlowPaused(ctx, state, !paused);
    };
  }
  progressNode._list.innerHTML = "";
  (state.steps || []).forEach((step) => {
    const row = document.createElement("div");
    row.className = "agent-flow-progress-item";
    const label = document.createElement("div");
    label.className = "label";
    label.textContent = step.label || step.node_id || "";
    const status = document.createElement("div");
    status.className = "state";
    let stateText = step.state || "";
    const output = String(step.output || "").trim();
    if (output) {
      const short = output.length > 64 ? `${output.slice(0, 61)}...` : output;
      stateText = stateText ? `${stateText} • ${short}` : short;
    }
    status.textContent = stateText;
    row.appendChild(label);
    row.appendChild(status);
    progressNode._list.appendChild(row);
  });
  updateFlowAlert(ctx);
}

async function setFlowPaused(ctx, state, paused) {
  const pid = String(state?.pid || ctx?.state?.ui?.activePid || "");
  const sid = String(state?.sid || ctx?.state?.ui?.activeSid || "");
  const runId = String(state?.runId || state?.run_id || "");
  if (!pid || !sid || !runId) return;
  const action = paused ? "pause" : "resume";
  const key = flowRunKey(sid, runId);
  const current = flowRuns.get(key) || {};
  if (paused) {
    flowRuns.set(key, { ...current, pid, sid, runId, running: true, paused: false, pauseRequested: true, status: "Pausing", updatedAt: Date.now() });
    updateProgressPanel(ctx, sid);
    updateFlowAlert(ctx);
  }
  try {
    const res = await ctx.apiJson(
      `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/agent_flow/${action}?run_id=${encodeURIComponent(runId)}`,
      {
        method: "POST",
        headers: {
          ...buildHeaders(ctx, pid, sid),
          "X-Gui-Enabled-Plugins": "collab_chat,agent_flow",
        },
      }
    );
    if (res?.state) applyFlowStatus(ctx, res.state);
  } catch (err) {
    ctx.log?.(`[agent_flow] ${action} failed: ${err?.message || err}`, "warn");
  }
}

function buildFlowPlan(flowDef, userText, maxSteps) {
  if (!flowDef || typeof flowDef !== "object") return [];
  const nodes = flowDef.nodes || {};
  const start = flowDef.start;
  if (!start || !nodes[start]) return [];
  const steps = [];
  let current = start;
  let count = 0;
  const visited = new Set();
  while (current && count < maxSteps) {
    const node = nodes[current] || {};
    const step = {
      step_index: count,
      node_id: current,
      label: node.label || current,
      plugin_id: node.plugin_id || "chat",
      agent_kind: node.agent_kind || "",
      system_prompt: node.system_prompt || "",
      return_only_text: node.return_only_text !== false,
      delay_ms: Number(node.delay_ms || 0),
      transitions: Array.isArray(node.transitions) ? node.transitions : [],
      plugin_settings: node.plugin_settings || {},
      initial_user_input: count === 0 ? userText : "",
    };
    steps.push(step);
    visited.add(current);
    count += 1;
    let nextId = null;
    const chosen = choosePreviewTransition(node, nodes, visited);
    const target = chosen && typeof chosen === "object" ? chosen.target : chosen;
    if (typeof target === "string" && target && !visited.has(target)) {
      nextId = target;
    }
    current = nextId;
  }
  return steps;
}

function buildHeaders(ctx, pid, sid) {
  const headers = {};
  const token = ctx?.state?.auth?.token;
  if (token) headers.Authorization = `Bearer ${token}`;
  const alias = ctx?.state?.auth?.alias;
  if (alias) headers["X-User-Alias"] = alias;
  if (pid) headers["X-Project-Id"] = pid;
  if (sid) headers["X-Session-Id"] = sid;
  return headers;
}


function hasAuthToken(ctx) {
  return Boolean(String(ctx?.state?.auth?.token || "").trim());
}

function getAgentWorkflowUiTargetRepoRoot(ctx) {
  const raw = ctx?.state?.agent_workflow_ui?.targetRepoRoot;
  return String(raw || "").trim();
}

async function fetchProjectFlows(ctx, pid, sid) {
  if (!pid || !sid) return null;
  if (!hasAuthToken(ctx)) return null;
  try {
    const res = await ctx.apiJson(
      `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/agent_flow/flows`,
      {
        headers: {
          ...buildHeaders(ctx, pid, sid),
          "X-Gui-Enabled-Plugins": "collab_chat,agent_flow",
        },
      }
    );
    try {
      const count = res?.flows && typeof res.flows === "object" ? Object.keys(res.flows).length : 0;
      ctx?.log?.(`[agent_flow] fetchProjectFlows ok pid=${pid} sid=${sid} flows=${count}`, "info");
    } catch {}
    return {
      flows: res?.flows && typeof res.flows === "object" ? res.flows : null,
      flowIdsByName: normalizeFlowIdMap(res?.flow_ids_by_name),
      defaultFlowIdsByName: normalizeFlowIdMap(res?.default_flow_ids_by_name),
    };
  } catch (err) {
    const msg = String(err?.message || err || "").trim() || "unknown_error";
    ctx?.log?.(`[agent_flow] failed to load project flows pid=${pid} sid=${sid}: ${msg}`, "warn");
    return null;
  }
}

async function fetchTempLibraryRecords(ctx, pid, sid) {
  if (!pid || !sid) return [];
  if (!hasAuthToken(ctx)) return [];
  try {
    const res = await ctx.apiJson(
      `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/agent_flow/temp_library`,
      {
        headers: {
          ...buildHeaders(ctx, pid, sid),
          "X-Gui-Enabled-Plugins": "collab_chat,agent_flow",
        },
      }
    );
    const sourceRows = Array.isArray(res?.items)
      ? res.items
      : Array.isArray(res?.records)
        ? res.records
        : [];
    const rows = sourceRows.filter((row) => row && typeof row === "object");
    try {
      ctx?.log?.(`[agent_flow] fetchTempLibraryRecords ok pid=${pid} sid=${sid} records=${rows.length}`, "info");
    } catch {}
    return rows;
  } catch (err) {
    const msg = String(err?.message || err || "").trim() || "unknown_error";
    ctx?.log?.(`[agent_flow] failed to load temp library pid=${pid} sid=${sid}: ${msg}`, "warn");
    return [];
  }
}

function sanitizeAutoFlowFlows(cachedFlows, projectFlows, tempLibraryRecords) {
  const cache = cachedFlows && typeof cachedFlows === "object" ? cachedFlows : {};
  const server = projectFlows && typeof projectFlows === "object" ? projectFlows : {};
  const allowedLibraryNames = new Set(
    (Array.isArray(tempLibraryRecords) ? tempLibraryRecords : [])
      .map((row) => String(row?.flow_name || "").trim())
      .filter(Boolean)
  );
  const next = {};
  Object.entries(server).forEach(([name, def]) => {
    if (def && typeof def === "object") next[name] = def;
  });
  Object.entries(cache).forEach(([name, def]) => {
    if (!def || typeof def !== "object") return;
    if (Object.prototype.hasOwnProperty.call(next, name)) return;
    if (allowedLibraryNames.has(String(name || "").trim())) {
      next[name] = def;
    }
  });
  return next;
}

async function persistProjectFlows(ctx, pid, sid, flows) {
  if (!pid || !sid) return;
  if (!hasAuthToken(ctx)) return;
  try {
    const currentSettings = getAgentFlowSettings(ctx, sid) || {};
    const res = await ctx.apiJson(
      `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/agent_flow/flows`,
      {
        method: "POST",
        headers: {
          ...buildHeaders(ctx, pid, sid),
          "X-Gui-Enabled-Plugins": "collab_chat,agent_flow",
        },
        body: {
          flows,
          flow_ids_by_name: getFlowIdMap(currentSettings),
        },
      }
    );
    if (res?.ok === false) {
      ctx?.log?.("[agent_flow] failed to save project flows", "warn");
    }
    return {
      ok: res?.ok !== false,
      flowIdsByName: normalizeFlowIdMap(res?.flow_ids_by_name),
    };
  } catch (err) {
    const msg = String(err?.message || err || "").trim() || "unknown_error";
    ctx?.log?.(`[agent_flow] failed to save project flows pid=${pid} sid=${sid}: ${msg}`, "warn");
    return { ok: false, flowIdsByName: {} };
  }
}

function isMainChatRoute(pluginId) {
  const id = String(pluginId || "").trim().toLowerCase();
  return !id || id === "chat" || id === "main" || id === "default";
}

function extractTextFromRouterPayload(payload) {
  if (!payload) return "";
  if (typeof payload === "string") {
    const raw = payload.trim();
    if (raw.startsWith("{") && raw.endsWith("}")) {
      try {
        const parsed = JSON.parse(raw);
        return extractTextFromRouterPayload(parsed) || raw;
      } catch {
        return raw;
      }
    }
    return raw;
  }
  if (typeof payload === "object") {
    for (const key of ["text", "final_text", "content", "answer"]) {
      if (typeof payload[key] === "string") return payload[key];
    }
    try {
      return payload.choices?.[0]?.message?.content || "";
    } catch {
      return "";
    }
  }
  return "";
}

function safeJson(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function applyNodeSystemPrompt(messages, prompt) {
  const text = String(prompt || "").trim();
  if (!text) return messages;
  const systemMsg = { role: "system", content: text };
  const sys = messages.filter((m) => m.role === "system");
  const rest = messages.filter((m) => m.role !== "system");
  return [...sys, systemMsg, ...rest];
}

function formatFlowStatus(step, idx, totalSteps, data) {
  const status = String(data?.router_status || "").trim();
  if (!status) return "";
  const label = step?.label || step?.node_id || "Flow step";
  const lines = [`Flow step ${idx + 1}/${totalSteps}: ${label}`];
  lines.push(status);
  const stepNum = data?.step;
  const stepTotal = data?.total;
  if (stepNum !== undefined && stepTotal !== undefined) {
    lines.push(`Progress: ${stepNum}/${stepTotal}`);
  }
  return lines.join("\n");
}

async function persistFlowMessage(ctx, pid, sid, msgId, content) {
  if (!pid || !sid || !content) return;
  try {
    const session = ctx.state.sessions?.[sid];
    if (session) {
      const pending = new Set(session._pending_client_msg_ids || []);
      pending.add(msgId);
      session._pending_client_msg_ids = Array.from(pending);
      ctx.state.sessions[sid] = session;
      ctx.saveState?.();
    }
    await ctx.apiJson(`/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/messages`, {
      method: "POST",
      headers: buildHeaders(ctx, pid, sid),
      body: {
        role: "assistant",
        kind: "model",
        content,
        client_msg_id: msgId,
        meta: { flow: true },
      },
    });
  } catch (err) {
    ctx.log?.(`[agent_flow] persist message failed: ${err?.message || err}`, "warn");
  }
}

async function persistFlowUserMessage(ctx, pid, sid, msgId, content) {
  if (!pid || !sid || !content) return;
  try {
    const session = ctx.state.sessions?.[sid];
    const msg = session?.messages?.find((m) => m?.msg_id === msgId);
    let text = content;
    let attachments = [];
    if (msg) {
      if (Array.isArray(msg.content)) {
        const parts = msg.content;
        const texts = parts
          .filter((p) => String(p?.type || "").toLowerCase() === "text")
          .map((p) => String(p?.text || p?.content || "").trim())
          .filter(Boolean);
        if (texts.length) text = texts.join("\n");
      } else if (typeof msg.content === "string" && msg.content.trim()) {
        text = msg.content.trim();
      }
      if (Array.isArray(msg?.meta?.attachments)) {
        attachments = msg.meta.attachments.map((a) => ({ ...a }));
      }
    }
    const finalText = text || (attachments.length ? "[image]" : content);
    await ctx.apiJson(`/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/messages`, {
      method: "POST",
      headers: buildHeaders(ctx, pid, sid),
      body: {
        role: "user",
        kind: "human",
        content: finalText,
        client_msg_id: msgId,
        meta: { flow: true, attachments },
      },
    });
  } catch (err) {
    ctx.log?.(`[agent_flow] persist user message failed: ${err?.message || err}`, "warn");
  }
}

async function emitAutoFlowNarration(ctx, pid, sid, lines, opts = {}) {
  if (!pid || !sid) return "";
  const text = Array.isArray(lines)
    ? lines.map((x) => String(x || "").trim()).filter(Boolean).join("\n")
    : String(lines || "").trim();
  if (!text) return "";
  const msgId = String(opts.msgId || `autoflow-${sid}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`);
  const append = opts.append === true;
  try {
    if (!append) {
      ctx.appendMessage?.(
        { msg_id: msgId, role: "assistant", content: text, author: "assistant", streaming: true },
        sid
      );
    } else {
      ctx.updateMessage?.(sid, msgId, text, true);
    }
    await new Promise((resolve) => setTimeout(resolve, 0));
    await persistFlowMessage(ctx, pid, sid, msgId, text);
    if (opts.done !== false) {
      ctx.markMessageDone?.(sid, msgId);
    }
  } catch (err) {
    ctx.log?.(`[autoflow] narration failed: ${err?.message || err}`, "warn");
  }
  return msgId;
}

function clipAutoFlowText(value, maxLen = 88) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return "";
  if (text.length <= maxLen) return text;
  return `${text.slice(0, Math.max(0, maxLen - 3)).trim()}...`;
}

async function runFlow(ctx, payload) {
  const sid = payload.sid;
  const pid = payload.pid || ctx.state.ui.activePid;
  if (!sid || flowRuns.get(sid)?.running) return;
  const settings = getAgentFlowSettings(ctx, sid);
  const flows = settings.agent_flow_flows || {};
  const flowName = resolveActiveFlowName(settings, flows);
  if (!flowName) return;
  const flowDef = flows[flowName];
  const maxSteps = Number(settings.agent_flow_max_steps || 8);
  const steps = buildFlowPlan(flowDef, payload.text, maxSteps);
  if (!steps.length) {
    ctx.log?.("[agent_flow] No steps to execute.", "warn");
    return;
  }
  const runState = {
    flowName,
    running: true,
    status: `Running 0/${steps.length}`,
    steps: steps.map((s) => ({ node_id: s.node_id, label: s.label, state: "queued" })),
  };
  flowRuns.set(sid, runState);
  updateProgressPanel(ctx, sid);
  let lastOutputText = "";
  let lastOutputRaw = "";

  for (let idx = 0; idx < steps.length; idx += 1) {
    const step = steps[idx];
    runState.steps[idx].state = "running";
    runState.status = `Running ${idx + 1}/${steps.length}`;
    updateProgressPanel(ctx, sid);
    if (step.delay_ms) {
      await new Promise((resolve) => setTimeout(resolve, step.delay_ms));
    }
    const msgId = `flow-${sid}-${Date.now()}-${idx}`;
    const initial = `Flow step ${idx + 1}/${steps.length}: ${step.label} (${step.plugin_id || "chat"})`;
    const basePayload = ctx.buildCompletionPayload ? ctx.buildCompletionPayload(sid) : { messages: [] };
    let messages = [];
    if (idx === 0) {
      messages = applyNodeSystemPrompt(basePayload.messages || [], step.system_prompt);
    } else {
      const nextInput = step.return_only_text ? lastOutputText : (lastOutputRaw || lastOutputText);
      messages = applyNodeSystemPrompt(
        [{ role: "user", content: nextInput || step.initial_user_input || "" }],
        step.system_prompt
      );
    }
    ctx.appendMessage?.(
      { msg_id: msgId, role: "assistant", content: initial, author: "assistant", streaming: true },
      sid
    );
    const ext = { ...(basePayload.ext || {}), router_mode: "exclude_agent_flow" };
    if (idx > 0 && ext.attachments) {
      ext.attachments = [];
    }
    const pluginSettings = { ...(ext.router_plugin_settings || {}) };
    if (step.plugin_id && step.plugin_settings && typeof step.plugin_settings === "object") {
      pluginSettings[step.plugin_id] = step.plugin_settings;
    }
    if (step.plugin_id === "image_reader" && step.system_prompt) {
      pluginSettings.image_reader = {
        ...(pluginSettings.image_reader || {}),
        image_reader_system_prompt: step.system_prompt,
      };
    }
    if (step.plugin_id === "image_gen" && step.system_prompt) {
      pluginSettings.image_gen = {
        ...(pluginSettings.image_gen || {}),
        image_gen_system_prompt: step.system_prompt,
      };
    }
    if (step.plugin_id === "image_gen") {
      pluginSettings.image_gen = {
        image_gen_use_prompt_embeds: false,
        debug_prompt_embeds: false,
        ...(pluginSettings.image_gen || {}),
      };
    }
    ext.router_plugin_settings = pluginSettings;
    if (isMainChatRoute(step.plugin_id)) {
      const body = {
        ...basePayload,
        messages,
        router_enabled_plugins: [],
        ext,
        stream: true,
      };
      let buffer = "";
      try {
        await ctx.streamSSE("/v1/chat/completions_stream", {
          method: "POST",
          headers: { ...buildHeaders(ctx, pid, sid), "Content-Type": "application/json" },
          body: JSON.stringify(body),
          onEvent: (event, data) => {
            if (event === "token") {
              const text = data?.text || "";
              buffer += text;
              ctx.appendToken?.(sid, msgId, text);
              return;
            }
            if (event === "done" || data === "[DONE]") {
              return;
            }
          },
        });
      } catch (err) {
        ctx.updateMessage?.(sid, msgId, `${initial}\n\n[error] ${err?.message || err}`, true);
      }
      ctx.markMessageDone?.(sid, msgId);
      if (buffer.trim()) {
        const cleaned = buffer.trim();
        ctx.updateMessage?.(sid, msgId, `${initial}\n\n${cleaned}`, true);
        lastOutputText = cleaned;
        lastOutputRaw = cleaned;
        runState.steps[idx].output = cleaned;
        await persistFlowMessage(ctx, pid, sid, msgId, cleaned);
      }
    } else {
      const body = {
        ...basePayload,
        route_id: step.plugin_id,
        messages,
        router_enabled_plugins: step.plugin_id ? [step.plugin_id] : [],
        ext,
      };
      let routerResult = null;
      try {
        if (step.plugin_id === "image_gen" || step.plugin_id === "video_gen" || step.plugin_id === "image_reader") {
          await ctx.streamSSE("/v1/chat/completions_ext_stream", {
            method: "POST",
            headers: { ...buildHeaders(ctx, pid, sid), "Content-Type": "application/json" },
            body: JSON.stringify(body),
            onEvent: (event, data) => {
              if (event === "diag") {
                const statusText = formatFlowStatus(step, idx, steps.length, data);
                if (statusText) {
                  ctx.updateMessage?.(sid, msgId, statusText, true);
                }
                return;
              }
              if (event === "router") {
                routerResult = data?.router_result || data;
              }
            },
          });
        } else {
          const res = await ctx.apiJson("/v1/chat/completions_ext", {
            method: "POST",
            headers: buildHeaders(ctx, pid, sid),
            body,
          });
          routerResult = res?.choices?.[0]?.ext?.router_result || res?.choices?.[0]?.ext || res?.ext || res;
        }
        const text = extractTextFromRouterPayload(routerResult) || extractTextFromRouterPayload({ result: routerResult });
        if (text) {
          lastOutputText = text;
        }
        lastOutputRaw = safeJson(routerResult || {});
        const outputSummary =
          text ||
          (routerResult && (routerResult.image_url || routerResult.image_path) ? "image generated" : "");
        if (outputSummary) {
          runState.steps[idx].output = outputSummary;
        }
        if (routerResult && typeof routerResult === "object" && !Array.isArray(routerResult)) {
          routerResult.flow_node_label = `Flow step ${idx + 1}/${steps.length}: ${step.label || step.node_id || ""}`.trim();
        }
        const jsonText = routerResult ? safeJson(routerResult) : "";
        if (jsonText) {
          ctx.updateMessage?.(sid, msgId, jsonText, true);
          await persistFlowMessage(ctx, pid, sid, msgId, jsonText);
        } else {
          const finalText = text ? `${initial}\n\n${text}` : `${initial}\n\n[done]`;
          ctx.updateMessage?.(sid, msgId, finalText, true);
          await persistFlowMessage(ctx, pid, sid, msgId, finalText);
        }
      } catch (err) {
        const errText = `${initial}\n\n[error] ${err?.message || err}`;
        ctx.updateMessage?.(sid, msgId, errText, true);
        await persistFlowMessage(ctx, pid, sid, msgId, errText);
      }
      ctx.markMessageDone?.(sid, msgId);
    }
    runState.steps[idx].state = "done";
    updateProgressPanel(ctx, sid);
  }
  runState.running = false;
  runState.status = "Completed";
  updateProgressPanel(ctx, sid);
}

async function requestAutoFlow(ctx, payload, settings, flows, options = {}) {
  const sid = String(payload.sid || "");
  const pid = payload.pid || ctx.state.ui.activePid;
  if (!sid || !pid) return null;
  if (!isAutoFlowRouterEnabled(ctx, sid)) return null;
  const autoSettings = getAutoFlowSettings(ctx, sid);
  const enabled = autoSettings.autoflow_enabled !== false && autoSettings.enabled !== false;
  if (!enabled) return null;
  const summaries = {};
  Object.entries(flows || {}).forEach(([name, flowDef]) => {
    summaries[name] = summarizeFlow(name, flowDef);
  });
  const basePayload = ctx.buildCompletionPayload ? ctx.buildCompletionPayload(sid) : { messages: [] };
  const ext = { ...(basePayload.ext || {}) };
  ext.agent_flow_flows = flows;
  ext.autoflow_flow_summaries = summaries;
  const creatorFlowNameHint = inferAutoFlowCreatorFlowName(settings || {}, autoSettings || {});
  ext.autoflow_settings = creatorFlowNameHint && !String(autoSettings.autoflow_creator_flow_name || "").trim()
    ? { ...autoSettings, autoflow_creator_flow_name: creatorFlowNameHint }
    : autoSettings;
  if (creatorFlowNameHint && !String(autoSettings.autoflow_creator_flow_name || "").trim()) {
    ext.autoflow_creator_flow_name_hint = creatorFlowNameHint;
  }
  ext.last_user_content = payload.text || ext.last_user_content || "";
  if (options && typeof options === "object") {
    if (options.mode) ext.autoflow_mode = String(options.mode || "").trim();
    if (Array.isArray(options.avoidFlows) && options.avoidFlows.length) ext.autoflow_avoid_flows = options.avoidFlows.slice();
    if (Array.isArray(options.avoidGeneratedRecordIds) && options.avoidGeneratedRecordIds.length) {
      ext.autoflow_avoid_generated_record_ids = options.avoidGeneratedRecordIds.slice();
    }
    if (Array.isArray(options.attempts) && options.attempts.length) ext.autoflow_attempts = options.attempts.slice();
    if (options.requestPlan && typeof options.requestPlan === "object") ext.autoflow_request_plan = { ...options.requestPlan };
    if (options.flowResultText) ext.autoflow_flow_result_text = String(options.flowResultText || "");
    if (options.flowName) ext.autoflow_flow_name = String(options.flowName || "");
    if (options.flowResultMeta && typeof options.flowResultMeta === "object") ext.autoflow_flow_result_meta = { ...options.flowResultMeta };
  }
  const routerSettings = ext.router_plugin_settings && typeof ext.router_plugin_settings === "object"
    ? { ...ext.router_plugin_settings }
    : {};
  routerSettings.autoflow = { ...(routerSettings.autoflow || {}), ...autoSettings };
  ext.router_plugin_settings = routerSettings;
  const body = {
    ...basePayload,
    route_id: "autoflow",
    router_enabled_plugins: ["autoflow"],
    messages: [{ role: "user", content: payload.text || "" }],
    ext,
  };
  try {
    const res = await ctx.apiJson("/v1/chat/completions_ext", {
      method: "POST",
      headers: buildHeaders(ctx, pid, sid),
      body,
    });
    const rr = res?.choices?.[0]?.ext?.router_result || res?.choices?.[0]?.ext || res?.ext || res;
    if (!rr || typeof rr !== "object") {
      ctx.log?.("[autoflow] route returned no structured result", "warn");
      return null;
    }
    const selected = String(rr?.selected_flow || rr?.flow_name || "").trim();
    if (selected) {
      ctx.log?.(`[autoflow] selected flow '${selected}'${rr?.confidence !== undefined ? ` (${rr.confidence})` : ""}: ${rr?.reason || ""}`, "info");
    } else if (!options?.allowEmptyResult) {
      ctx.log?.(`[autoflow] no matching flow selected for this request${rr?.reason ? `: ${rr.reason}` : ""}`, "warn");
    }
    const generated = rr?.generated_workflow && typeof rr.generated_workflow === "object" ? rr.generated_workflow : null;
    const creatorRun = rr?.creator_run && typeof rr.creator_run === "object" ? rr.creator_run : null;
    return {
      flowName: selected,
      flowDef: selected && flows?.[selected] ? flows[selected] : (generated?.workflow_json || null),
      generatedWorkflow: generated,
      creatorRun,
      result: rr,
    };
  } catch (err) {
    ctx.log?.(`[autoflow] route selection failed: ${err?.message || err}`, "warn");
    return null;
  }
}

function sleepMs(ms) {
  return new Promise((resolve) => setTimeout(resolve, Math.max(0, Number(ms) || 0)));
}

async function planAutoFlow(ctx, payload, settings, flows, options = {}) {
  return requestAutoFlow(ctx, payload, settings, flows, {
    mode: "plan",
    avoidFlows: options.avoidFlows || [],
    avoidGeneratedRecordIds: options.avoidGeneratedRecordIds || [],
    attempts: options.attempts || [],
  });
}

async function selectAutoFlow(ctx, payload, settings, flows) {
  return requestAutoFlow(ctx, payload, settings, flows, { mode: "select" });
}

function buildAutoFlowRuntimeAlias(flowName, generatedWorkflow, attemptIndex) {
  const base = String(flowName || "").trim() || "generated_workflow";
  const recordId = String(generatedWorkflow?.record_id || "").trim().replace(/[^a-zA-Z0-9_-]+/g, "_");
  const attempt = Number.isFinite(Number(attemptIndex)) ? Math.max(1, Number(attemptIndex) + 1) : 1;
  if (recordId) return `${base}__autoflow_runtime__${recordId}`;
  return `${base}__autoflow_runtime__attempt_${attempt}`;
}

async function fetchLatestAssistantMessage(ctx, pid, sid) {
  if (!pid || !sid) return null;
  try {
    const res = await ctx.apiJson(
      `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/messages?limit=20&tail=1`,
      {
        headers: buildHeaders(ctx, pid, sid),
      }
    );
    const rows = Array.isArray(res?.messages) ? res.messages : [];
    for (const row of rows) {
      if (String(row?.role || "").toLowerCase() === "assistant") return row;
    }
  } catch (err) {
    ctx.log?.(`[autoflow] latest assistant fetch failed: ${err?.message || err}`, "warn");
  }
  return null;
}

async function waitForFlowCompletion(ctx, pid, sid, runId) {
  if (!pid || !sid || !runId) return { ok: false, error: "missing_run_id" };
  let state = null;
  for (let loops = 0; loops < 360; loops += 1) {
    try {
      const query = `?run_id=${encodeURIComponent(runId)}`;
      const res = await ctx.apiJson(
        `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/agent_flow/status${query}`,
        {
          headers: {
            ...buildHeaders(ctx, pid, sid),
            "X-Gui-Enabled-Plugins": "collab_chat,agent_flow",
          },
        }
      );
      if (res?.state) {
        state = res.state;
        applyFlowStatus(ctx, state);
      }
      if (!state?.running) {
        const message = await fetchLatestAssistantMessage(ctx, pid, sid);
        return { ok: true, state, message };
      }
    } catch (err) {
      ctx.log?.(`[autoflow] flow completion poll failed: ${err?.message || err}`, "warn");
      return { ok: false, error: err?.message || String(err || "poll_failed"), state };
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  const message = await fetchLatestAssistantMessage(ctx, pid, sid);
  return { ok: false, error: "timed_out", state, message };
}

async function runFlowServer(ctx, payload, flowOverride = "", runOptions = {}) {
  const sid = payload.sid;
  const pid = payload.pid || ctx.state.ui.activePid;
  if (!sid || !pid) return { ok: false, error: "missing_sid_or_pid" };
  let runnable = await ensureRunnableFlowSettings(ctx, sid, pid);
  let settings = runnable.settings || {};
  let flows = settings.agent_flow_flows || {};
  let flowName = runnable.flowName || "";
  let flowDef = runnable.flowDef;
  const injectedFlowDef = runOptions && typeof runOptions.flowDef === "object" ? runOptions.flowDef : null;
  const injectedTempSkillDirs = Array.isArray(runOptions?.tempSkillDirs) ? runOptions.tempSkillDirs.slice() : [];
  const flowNameOverride = String(runOptions?.flowNameOverride || "").trim();
  const override = String(flowNameOverride || flowOverride || "").trim();
  if (override) {
    settings = getAgentFlowSettings(ctx, sid);
    flows = settings.agent_flow_flows && typeof settings.agent_flow_flows === "object" ? settings.agent_flow_flows : {};
    if (injectedFlowDef) {
      flows = { ...(flows || {}), [override]: injectedFlowDef };
    }
    if (!flows[override]) {
      const serverPayload = await fetchProjectFlows(ctx, pid, sid);
      const serverFlows = serverPayload?.flows;
      if (serverFlows && typeof serverFlows === "object") {
        flows = deepClone(serverFlows);
        if (injectedFlowDef) flows[override] = injectedFlowDef;
        settings = {
          ...(settings || {}),
          agent_flow_flows: flows,
          agent_flow_flow_ids_by_name: normalizeFlowIdMap(serverPayload?.flowIdsByName),
          agent_flow_default_flow_ids_by_name: normalizeFlowIdMap(serverPayload?.defaultFlowIdsByName),
        };
        setRouterSettings(ctx, sid, "agent_flow", settings);
      }
    }
    flowName = flows[override] ? override : "";
    flowDef = flowName ? flows[flowName] : null;
    runnable = { settings, flowName, flowDef, reason: flowName ? "" : "autoflow_selection_missing" };
  }
  if (!flowName || !flowIsRunnable(flowDef)) {
    ctx.log?.(`[agent_flow] run skipped: ${runnable.reason || "no runnable flow"}`, "warn");
    return { ok: false, error: runnable.reason || "no_runnable_flow" };
  }
  const basePayload = ctx.buildCompletionPayload ? ctx.buildCompletionPayload(sid) : { ext: {} };
  const ext = { ...(basePayload.ext || {}), ...((payload && payload.ext && typeof payload.ext === "object") ? payload.ext : {}) };
  const currentRouterSettings = ctx?.state?.router?.settings?.[String(sid || "")];
  let effectiveRouterSettings = currentRouterSettings && typeof currentRouterSettings === "object"
    ? { ...currentRouterSettings }
    : {};
  if (!effectiveRouterSettings.agent_workflow_member) {
    const allRouterSettings = ctx?.state?.router?.settings;
    if (allRouterSettings && typeof allRouterSettings === "object") {
      for (const key of Object.keys(allRouterSettings)) {
        const row = allRouterSettings[key];
        if (!row || typeof row !== "object") continue;
        if (row.agent_workflow_member && typeof row.agent_workflow_member === "object") {
          effectiveRouterSettings.agent_workflow_member = { ...row.agent_workflow_member };
          break;
        }
      }
    }
  }
  if (effectiveRouterSettings && typeof effectiveRouterSettings === "object") {
    const existingRps = ext.router_plugin_settings && typeof ext.router_plugin_settings === "object"
      ? { ...ext.router_plugin_settings }
      : {};
    Object.entries(effectiveRouterSettings).forEach(([pluginId, pluginCfg]) => {
      if (!pluginId || !pluginCfg || typeof pluginCfg !== "object") return;
      const prior = existingRps[pluginId] && typeof existingRps[pluginId] === "object"
        ? { ...existingRps[pluginId] }
        : {};
      existingRps[pluginId] = { ...prior, ...pluginCfg };
    });
    ext.router_plugin_settings = existingRps;
    const awMember = effectiveRouterSettings.agent_workflow_member;
    if (awMember && typeof awMember === "object") {
      ext.agent_workflow_member_settings = {
        ...(ext.agent_workflow_member_settings && typeof ext.agent_workflow_member_settings === "object"
          ? ext.agent_workflow_member_settings
          : {}),
        ...awMember,
      };
    }
  }
  const mediaState = ctx.state.media_upload || {};
  const inflight = Array.isArray(mediaState.inflightBySid?.[sid]) ? mediaState.inflightBySid[sid] : [];
  const pending = Array.isArray(mediaState.pendingBySid?.[sid]) ? mediaState.pendingBySid[sid] : [];
  const mediaAttachments = inflight.length ? inflight : pending;
  if (!Array.isArray(ext.attachments) || !ext.attachments.length) {
    if (mediaAttachments.length) {
      ext.attachments = mediaAttachments.map((att) => ({
        name: att.name || "image",
        mime: att.mime || "",
        path: att.path || att.local_path || "",
        url: att.download_url || att.url || att.data_url || att.dataUrl || "",
        kind: "image",
        source: att.source || "media_upload",
      }));
    }
  }
  if (!ext.base_url && ctx.state?.remote?.serverUrl) {
    ext.base_url = ctx.state.remote.serverUrl;
  }
  const workflowTargetRepoRoot = getAgentWorkflowUiTargetRepoRoot(ctx);
  if (workflowTargetRepoRoot) {
    ext.agent_workflow_target_repo_root = workflowTargetRepoRoot;
    ext.target_repo_root = workflowTargetRepoRoot;
    const rps = ext.router_plugin_settings && typeof ext.router_plugin_settings === "object"
      ? { ...ext.router_plugin_settings }
      : {};
    const aw = rps.agent_workflow && typeof rps.agent_workflow === "object"
      ? { ...rps.agent_workflow }
      : {};
    if (!String(aw.target_repo_root || "").trim()) aw.target_repo_root = workflowTargetRepoRoot;
    rps.agent_workflow = aw;
    ext.router_plugin_settings = rps;
  }
  ext.agent_flow_flows = flows;
  ext.agent_flow_active_flow = flowName;
  ext.agent_flow_default_flow = settings.agent_flow_default_flow || "";
  ext.agent_flow_max_steps = Number(settings.agent_flow_max_steps || 8);
  if (injectedTempSkillDirs.length) {
    ext.agent_flow_temp_skill_dirs = injectedTempSkillDirs.slice();
  }
  if (injectedFlowDef) {
    ext.agent_flow_force_runtime_flow = true;
  }
  const sandboxProfile = normalizeSandboxProfileSetting(settings.agent_flow_autobuild_sandbox_profile, "lightweight");
  const lightweightMaxRequests = Math.max(1, Math.trunc(Number(settings.agent_flow_autobuild_lightweight_max_requests ?? 1) || 1));
  const lightweightWait = normalizeTimeoutSetting(settings.agent_flow_autobuild_lightweight_wait_s, 120);
  const lightweightGrace = normalizeTimeoutSetting(settings.agent_flow_autobuild_lightweight_final_grace_s, 10);
  const independentMaxRequests = Math.max(1, Math.trunc(Number(settings.agent_flow_autobuild_independent_max_requests ?? 3) || 3));
  const independentWait = normalizeTimeoutSetting(settings.agent_flow_autobuild_independent_wait_s, 180);
  const independentGrace = normalizeTimeoutSetting(settings.agent_flow_autobuild_independent_final_grace_s, 20);
  ext.agent_flow_autobuild_sandbox_profile = sandboxProfile;
  ext.agent_flow_autobuild_lightweight_max_requests = lightweightMaxRequests;
  ext.agent_flow_autobuild_lightweight_wait_s = lightweightWait;
  ext.agent_flow_autobuild_lightweight_final_grace_s = lightweightGrace;
  ext.agent_flow_autobuild_independent_max_requests = independentMaxRequests;
  ext.agent_flow_autobuild_independent_wait_s = independentWait;
  ext.agent_flow_autobuild_independent_final_grace_s = independentGrace;
  ext.agent_flow_autobuild_sandbox_max_requests = sandboxProfile === "independent" ? independentMaxRequests : lightweightMaxRequests;
  ext.agent_flow_autobuild_sandbox_max_request_wait_s = sandboxProfile === "independent" ? independentWait : lightweightWait;
  ext.agent_flow_autobuild_sandbox_poll_interval_s = 1;
  ext.agent_flow_autobuild_sandbox_final_step_grace_s = sandboxProfile === "independent" ? independentGrace : lightweightGrace;
  ext.max_requests = ext.agent_flow_autobuild_sandbox_max_requests;
  ext.max_request_wait_s = ext.agent_flow_autobuild_sandbox_max_request_wait_s;
  ext.poll_interval_s = ext.agent_flow_autobuild_sandbox_poll_interval_s;
  ext.final_step_grace_s = ext.agent_flow_autobuild_sandbox_final_step_grace_s;
  const enabledSet = new Set(
    Array.isArray(basePayload.router_enabled_plugins)
      ? basePayload.router_enabled_plugins.map((x) => String(x || "").trim()).filter(Boolean)
      : []
  );
  // Ensure flow node plugins are considered enabled even when cached router
  // plugin flags are stale/missing in local state.
  try {
    const nodes = flowDef && typeof flowDef === "object" && flowDef.nodes && typeof flowDef.nodes === "object"
      ? flowDef.nodes
      : {};
    Object.values(nodes).forEach((n) => {
      const pid0 = String((n && typeof n === "object" ? n.plugin_id : "") || "").trim();
      if (pid0) enabledSet.add(pid0);
    });
  } catch (_err) {}
  enabledSet.add("agent_flow");
  ext.agent_flow_enabled_plugins = Array.from(enabledSet);
  const body = {
    text: payload.text || "",
    client_msg_id: payload.client_msg_id || "",
    ext,
  };
  try {
    const res = await ctx.apiJson(
      `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/agent_flow/run`,
      {
        method: "POST",
        headers: {
          ...buildHeaders(ctx, pid, sid),
          "X-Gui-Enabled-Plugins": "collab_chat,agent_flow",
        },
        body,
      }
    );
    const runState = {
      pid,
      sid,
      runId: res?.run_id || "",
      flowName: res?.flow_name || flowName,
      running: true,
      status: "Starting...",
      steps: [],
      updatedAt: Date.now(),
    };
    const key = flowRunKey(sid, runState.runId);
    flowRuns.set(key, runState);
    if (res?.state && typeof res.state === "object") {
      applyFlowStatus(ctx, res.state);
    }
    updateProgressPanel(ctx, sid);
    updateFlowAlert(ctx);
    startFlowStatusPolling(ctx, sid, runState.runId);
    return { ok: true, runId: runState.runId, flowName: runState.flowName, pid, sid };
  } catch (err) {
    ctx.log?.(`[agent_flow] server run failed: ${err?.message || err}`, "warn");
    return { ok: false, error: err?.message || String(err || "run_failed") };
  }
}

async function runFlowServerUntilDone(ctx, payload, flowOverride = "", runOptions = {}) {
  const started = await runFlowServer(ctx, payload, flowOverride, runOptions);
  if (!started?.ok) return started || { ok: false, error: "run_failed" };
  const done = await waitForFlowCompletion(ctx, started.pid, started.sid, started.runId);
  if (!done?.ok) {
    return {
      ok: false,
      error: done?.error || "wait_failed",
      runId: started.runId,
      flowName: started.flowName,
      state: done?.state || null,
      message: done?.message || null,
    };
  }
  return {
    ok: true,
    runId: started.runId,
    flowName: started.flowName,
    state: done.state || null,
    message: done.message || null,
  };
}

async function judgeAutoFlowResult(ctx, payload, settings, flows, judgeOptions = {}) {
  return requestAutoFlow(ctx, payload, settings, flows, {
    mode: "judge",
    allowEmptyResult: true,
    flowResultText: judgeOptions.flowResultText || "",
    flowName: judgeOptions.flowName || "",
    flowResultMeta: judgeOptions.flowResultMeta || {},
  });
}

async function runAutoFlowLoop(ctx, payload, settings, flows) {
  const sid = String(payload.sid || "");
  const pid = payload.pid || ctx.state.ui.activePid;
  if (!sid || !pid) return false;
  const autoSettings = getAutoFlowSettings(ctx, sid);
  const configuredCreatorFlowName = inferAutoFlowCreatorFlowName(settings || {}, autoSettings || {});
  const configuredRetryLoops = Math.max(1, Math.trunc(Number(autoSettings.autoflow_retry_loops ?? 2) || 2));
  const requireJudge = autoSettings.autoflow_require_satisfaction_check !== false;
  const createEnabled = autoSettings.autoflow_create_if_request_not_satisfied === true;
  const retryLoops = configuredRetryLoops;
  const attempts = [];
  const avoidFlows = [];
  const avoidGeneratedRecordIds = [];
  let narrationMsgId = "";
  for (let attemptIndex = 0; attemptIndex < retryLoops; attemptIndex += 1) {
    narrationMsgId = await emitAutoFlowNarration(ctx, pid, sid, [
      `AutoFlow ${attemptIndex + 1}/${retryLoops}`,
      "Checking direct answers, built-in skills, and existing workflows.",
      createEnabled ? "Creating a new workflow only if nothing suitable matches." : "",
    ], { msgId: narrationMsgId || "", append: Boolean(narrationMsgId), done: false });
    let selection = null;
    const slowSelectionMsgId = narrationMsgId || "";
    const slowSelectionTimer = setTimeout(() => {
      void emitAutoFlowNarration(ctx, pid, sid, [
        `AutoFlow ${attemptIndex + 1}/${retryLoops}`,
        createEnabled
          ? "Checking whether workflow creation is actually needed."
          : "Matching built-ins and existing workflows.",
      ], { msgId: slowSelectionMsgId, append: Boolean(slowSelectionMsgId), done: false });
    }, 900);
    try {
      selection = await requestAutoFlow(ctx, payload, settings, flows, {
        mode: createEnabled ? "select_or_create" : "select",
        avoidFlows,
        avoidGeneratedRecordIds,
        attempts,
      });
    } finally {
      clearTimeout(slowSelectionTimer);
    }
    const rr = selection?.result || {};
    const requestPlan = rr?.plan && typeof rr.plan === "object" ? rr.plan : null;
    const planSummary = String(requestPlan?.summary || "").trim();
    const planNeed = Array.isArray(requestPlan?.must_use_capabilities) ? requestPlan.must_use_capabilities.filter(Boolean) : [];
    const planAvoid = Array.isArray(requestPlan?.avoid_capabilities) ? requestPlan.avoid_capabilities.filter(Boolean) : [];
    if (planSummary || planNeed.length || planAvoid.length) {
      narrationMsgId = await emitAutoFlowNarration(ctx, pid, sid, [
        `AutoFlow ${attemptIndex + 1}/${retryLoops}`,
        planSummary ? `Plan: ${clipAutoFlowText(planSummary, 96)}` : "Plan ready.",
        planNeed.length ? `Need: ${clipAutoFlowText(planNeed.join(", "), 72)}` : "",
        planAvoid.length ? `Avoid: ${clipAutoFlowText(planAvoid.join(", "), 72)}` : "",
      ], { msgId: narrationMsgId || "", append: Boolean(narrationMsgId), done: false });
    }
    const chosenFlowName = String(selection?.flowName || rr?.flow_name || rr?.selected_flow || "").trim();
    const generated = selection?.generatedWorkflow && typeof selection.generatedWorkflow === "object" ? selection.generatedWorkflow : null;
    const creatorRun = selection?.creatorRun && typeof selection.creatorRun === "object" ? selection.creatorRun : null;
    const chosenFlowDef = selection?.flowDef && typeof selection.flowDef === "object"
      ? selection.flowDef
      : (generated?.workflow_json && typeof generated.workflow_json === "object" ? generated.workflow_json : null);
    const tempSkillDirs = Array.isArray(generated?.temp_skill_dirs) ? generated.temp_skill_dirs.slice() : [];
    const generatedRecordId = String(generated?.record_id || "").trim();
    const runtimeFlowName = generated
      ? buildAutoFlowRuntimeAlias(chosenFlowName, generated, attemptIndex)
      : chosenFlowName;
    const selectionSource = String(rr?.source || (generated ? "generated" : "existing") || "existing").trim();
    if (!chosenFlowName || !chosenFlowDef || !flowIsRunnable(chosenFlowDef)) {
      const creatorStatus = creatorRun?.status ? String(creatorRun.status) : "";
      await emitAutoFlowNarration(ctx, pid, sid, [
        `AutoFlow ${attemptIndex + 1}/${retryLoops}`,
        createEnabled ? "No runnable flow yet." : "No runnable match.",
        creatorStatus
          ? clipAutoFlowText(`Creator: ${creatorStatus}`)
          : clipAutoFlowText(rr?.reason || "No direct answer, built-in skill, or runnable workflow matched this request."),
      ], { msgId: narrationMsgId || "", append: Boolean(narrationMsgId) });
      if (attemptIndex === 0) return false;
      break;
    }
    narrationMsgId = await emitAutoFlowNarration(ctx, pid, sid, [
      `AutoFlow ${attemptIndex + 1}/${retryLoops}`,
      generated
        ? `Built: ${clipAutoFlowText(chosenFlowName, 56)}.`
        : `Using: ${clipAutoFlowText(chosenFlowName, 56)}.`,
      generated && creatorRun?.run_id ? `Creator run ${creatorRun.run_id}.` : "",
      "Running.",
    ], { msgId: narrationMsgId || "", append: Boolean(narrationMsgId) });
    const runResult = await runFlowServerUntilDone(ctx, payload, chosenFlowName, {
      flowNameOverride: runtimeFlowName,
      flowDef: chosenFlowDef,
      tempSkillDirs,
    });
    const assistantMsg = runResult?.message && typeof runResult.message === "object" ? runResult.message : {};
    const assistantText = String(assistantMsg?.content || "").trim();
    const assistantMeta = assistantMsg?.meta && typeof assistantMsg.meta === "object" ? assistantMsg.meta : {};
    if (!requireJudge) {
      await emitAutoFlowNarration(ctx, pid, sid, [
        `AutoFlow ${attemptIndex + 1}/${retryLoops}`,
        runResult?.ok ? "Done. Review disabled." : `Run failed${runResult?.error ? `: ${clipAutoFlowText(runResult.error, 56)}` : ""}.`,
      ], { msgId: narrationMsgId || "", append: Boolean(narrationMsgId) });
      return Boolean(runResult?.ok);
    }
    narrationMsgId = await emitAutoFlowNarration(ctx, pid, sid, [
      `AutoFlow ${attemptIndex + 1}/${retryLoops}`,
      "Checking result.",
    ], { msgId: narrationMsgId || "", append: Boolean(narrationMsgId), done: false });
    const judged = await judgeAutoFlowResult(ctx, payload, settings, flows, {
      flowResultText: assistantText || safeJson(assistantMeta || {}),
      flowName: chosenFlowName,
      flowResultMeta: assistantMeta,
    });
    const judgeResult = judged?.result || {};
    const satisfied = judgeResult?.satisfied === true;
    attempts.push({
      flow_name: chosenFlowName,
      source: rr?.source || (generated ? "generated" : "existing"),
      judge_reason: String(judgeResult?.reason || "").trim(),
      improved_request: String(judgeResult?.improved_request || "").trim(),
    });
    if (satisfied) {
      await emitAutoFlowNarration(ctx, pid, sid, [
        `AutoFlow ${attemptIndex + 1}/${retryLoops}`,
        "Passed.",
        clipAutoFlowText(judgeResult?.reason || ""),
      ], { msgId: narrationMsgId || "", append: Boolean(narrationMsgId) });
      return true;
    }
    avoidFlows.push(chosenFlowName);
    if (generatedRecordId) avoidGeneratedRecordIds.push(generatedRecordId);
    if (chosenFlowName && flows && typeof flows === "object") {
      delete flows[chosenFlowName];
    }
    const hasRetry = attemptIndex + 1 < retryLoops;
    await emitAutoFlowNarration(ctx, pid, sid, [
      `AutoFlow ${attemptIndex + 1}/${retryLoops}`,
      `Missed: ${clipAutoFlowText(judgeResult?.reason || "missing requested output", 72)}`,
      hasRetry
        ? "Retrying with a new flow."
        : "No retries left.",
    ], { msgId: narrationMsgId || "", append: Boolean(narrationMsgId) });
    ctx.log?.(`[autoflow] '${chosenFlowName}' did not satisfy the request: ${judgeResult?.reason || "unspecified"}`, "warn");
  }
  return attempts.length > 0;
}

function applyFlowStatus(ctx, data) {
  if (!data || typeof data !== "object") return;
  const sid = String(data.sid || "");
  if (!sid) return;
  const steps = Array.isArray(data.steps)
    ? data.steps.map((s) => ({
        node_id: s?.node_id || "",
        label: s?.label || s?.node_id || "",
        state: s?.state || "",
        output: s?.output || "",
      }))
    : [];
  const runState = {
    pid: String(data.pid || ctx?.state?.ui?.activePid || ""),
    sid,
    runId: String(data.run_id || data.runId || ""),
    flowName: data.flow_name || data.flowName || "",
    running: Boolean(data.running),
    paused: normalizeFlowRunFlags(data).paused,
    pauseRequested: normalizeFlowRunFlags(data).pauseRequested,
    status: data.status || "",
    loopCap: normalizeLoopCapMeta(data),
    steps,
    updatedAt: Date.now(),
  };
  const key = flowRunKey(sid, runState.runId);
  flowRuns.set(key, runState);
  if (!runState.running) {
    stopFlowStatusPolling(sid, runState.runId);
  } else {
    startFlowStatusPolling(ctx, sid, runState.runId);
  }
  if (sid === ctx.state.ui.activeSid) {
    updateProgressPanel(ctx, sid);
  }
  updateFlowAlert(ctx);
}

async function refreshFlowStatus(ctx, sid, runId = "") {
  const pid = ctx.state.ui.activePid;
  if (!pid || !sid) return;
  if (!hasAuthToken(ctx)) return;
  try {
    const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
    const res = await ctx.apiJson(
      `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/agent_flow/status${query}`,
      {
        headers: {
          ...buildHeaders(ctx, pid, sid),
          "X-Gui-Enabled-Plugins": "collab_chat,agent_flow",
        },
      }
    );
    if (res?.state) applyFlowStatus(ctx, res.state);
  } catch (err) {
    ctx.log?.(`[agent_flow] status check failed: ${err?.message || err}`, "warn");
  }
}


async function runBuiltinAutoFlowCandidate(ctx, payload, selection) {
  const sid = String(payload?.sid || "").trim();
  const pid = payload?.pid || ctx?.state?.ui?.activePid;
  const candidate = selection?.result && typeof selection.result === "object" ? selection.result : {};
  if (!pid || !sid || !hasAuthToken(ctx)) return null;
  try {
    const res = await ctx.apiJson(
      `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/autoflow/execute_builtin`,
      {
        method: "POST",
        headers: {
          ...buildHeaders(ctx, pid, sid),
          "X-Gui-Enabled-Plugins": "collab_chat,agent_flow,agent_workflow_member,autoflow",
        },
        body: {
          message: String(payload?.text || ""),
          candidate,
          client_msg_id: String(payload?.client_msg_id || ""),
        },
      }
    );
    const assistant = res?.assistant_message && typeof res.assistant_message === "object" ? res.assistant_message : {};
    const content = String(assistant?.content || res?.assistant_response || "").trim();
    if (!content) return null;
    const msgId = String(assistant?.msg_id || `builtin-autoflow-${sid}-${Date.now()}`);
    ctx.appendMessage?.(
      {
        msg_id: msgId,
        role: String(assistant?.role || "assistant"),
        content,
        author: String(assistant?.author_alias || assistant?.author_username || "assistant"),
        author_username: String(assistant?.author_username || "assistant"),
        meta: assistant?.meta && typeof assistant.meta === "object" ? assistant.meta : {},
        ts: Number(assistant?.ts || Date.now()),
      },
      sid
    );
    ctx.markMessageDone?.(sid, msgId);
    const builtinState = res?.result?.state;
    if (builtinState && typeof builtinState === "object") {
      try {
        applyFlowStatus(ctx, { ...builtinState, pid, sid, flow_name: String(res?.result?.flow_name || candidate?.selected_flow || candidate?.flow_name || "") });
      } catch (_err) {}
    }
    return { ok: true, response: res };
  } catch (err) {
    ctx.log?.(`[autoflow] builtin execution failed: ${err?.message || err}`, "warn");
    return null;
  }
}


async function sendHook(payload, ctx) {
  const sid = String(payload.sid || "");
  if (!sid) return payload;
  const currentSettings = getAgentFlowSettings(ctx, sid);
  if (isLLMAutoFlowSelectionValue(currentSettings?.agent_flow_active_flow) || isLLMSkillAutoFlowSelectionValue(currentSettings?.agent_flow_active_flow)) {
    return payload;
  }
  const pid = payload.pid || ctx.state.ui.activePid;
  if (pid && typeof ctx.loadProjectRouterPrefs === "function") {
    await ctx.loadProjectRouterPrefs(pid);
  }
  const runnable = await ensureRunnableFlowSettings(ctx, sid, pid);
  if (runnable.reason === "no_flow_selected") {
    if (!isAutoFlowRouterEnabled(ctx, sid)) {
      ctx.log?.("[autoflow] No Flow active and AutoFlow router is disabled; sending normal assistant response.", "info");
      return payload;
    }
    if (shouldBypassAutoFlowForDirectQuestion(payload)) {
      directChatBypassBySid.set(sid, Date.now());
      ctx.log?.("[autoflow] No Flow active. Bypassing AutoFlow for a plain direct question so chat can stream immediately.", "info");
      return payload;
    }
    let settings = runnable.settings || getAgentFlowSettings(ctx, sid);
    const cachedFlows = settings.agent_flow_flows && typeof settings.agent_flow_flows === "object" ? settings.agent_flow_flows : {};
    const serverPayload = await fetchProjectFlows(ctx, pid, sid);
    const serverFlows = serverPayload?.flows && typeof serverPayload.flows === "object" ? serverPayload.flows : {};
    let flows = {};
    if (Object.keys(serverFlows).length) {
      flows = sanitizeAutoFlowFlows(cachedFlows, serverFlows, []);
      if (!Object.keys(flows).length) {
        flows = deepClone(serverFlows);
      }
    } else if (cachedFlows && Object.keys(cachedFlows).length) {
      const tempLibraryRecords = await fetchTempLibraryRecords(ctx, pid, sid);
      flows = sanitizeAutoFlowFlows(cachedFlows, {}, tempLibraryRecords);
      if (!Object.keys(flows).length) {
        flows = deepClone(cachedFlows);
      }
    }
    settings = {
      ...(settings || {}),
      agent_flow_flows: flows,
      agent_flow_flow_ids_by_name: normalizeFlowIdMap(serverPayload?.flowIdsByName),
      agent_flow_default_flow_ids_by_name: normalizeFlowIdMap(serverPayload?.defaultFlowIdsByName),
    };
    setRouterSettings(ctx, sid, "agent_flow", settings);
    const autoSettings = getAutoFlowSettings(ctx, sid);
    const creatorName = String(autoSettings.autoflow_creator_flow_name || "").trim() || inferAutoFlowCreatorFlowName(settings, autoSettings) || "(not set)";
    const createEnabled = autoSettings.autoflow_create_if_request_not_satisfied === true;
    const requireJudge = autoSettings.autoflow_require_satisfaction_check !== false;
    const createMode = createEnabled ? "enabled" : "disabled";
    ctx.log?.(
      `[autoflow] No Flow active. AutoFlow will first try direct answers or built-in skills, then select an existing workflow; workflow creation is ${createMode}. creator=${creatorName}`,
      "info"
    );
    if (requireJudge || createEnabled) {
      const handled = await runAutoFlowLoop(ctx, payload, settings, flows);
      if (handled) return { ...payload, handled: true };
      ctx.log?.("[autoflow] AutoFlow loop could not complete; falling back to normal assistant response", "warn");
      return payload;
    }
    const selected = await selectAutoFlow(ctx, payload, settings, flows);
    if (selected?.flowName) {
      const selectedRunName = String(selected?.flowName || "").trim();
      if (selectedRunName.startsWith("__autoflow_builtin_")) {
        const builtinOk = await runBuiltinAutoFlowCandidate(ctx, payload, selected);
        if (builtinOk?.ok) {
          ctx.log?.(`[autoflow] No Flow active. Executed built-in candidate '${selectedRunName}' directly.`, "info");
          return { ...payload, handled: true };
        }
        ctx.log?.("[autoflow] built-in candidate could not execute directly; falling back to normal assistant response", "warn");
        return payload;
      }
      const ok = await runFlowServer(ctx, payload, selectedRunName, {
        flowNameOverride: selectedRunName,
        flowDef: selected?.flowDef && typeof selected.flowDef === "object" ? selected.flowDef : null,
        tempSkillDirs: Array.isArray(selected?.generatedWorkflow?.temp_skill_dirs) ? selected.generatedWorkflow.temp_skill_dirs.slice() : [],
      });
      if (ok?.ok) {
        ctx.log?.(`[autoflow] No Flow active. Selected existing workflow '${selectedRunName}' without entering the creator loop.`, "info");
        return { ...payload, handled: true };
      }
      ctx.log?.("[autoflow] selected flow could not start; falling back to normal assistant response", "warn");
      return payload;
    }
    ctx.log?.("[autoflow] No Flow selected, but AutoFlow creation is not enabled for this session.", "warn");
    return payload;
  }
  const active = runnable.flowName || "";
  const flowDef = runnable.flowDef;
  if (!active) {
    ctx.log?.("[agent_flow] no active flow resolved; sending normal chat.", "warn");
    return payload;
  }
  if (!flowIsRunnable(flowDef)) {
    const lastWarned = emptyFlowWarned.get(sid);
    if (lastWarned !== active) {
      emptyFlowWarned.set(sid, active);
      ctx.log?.(`[agent_flow] '${active}' has no nodes/start after refresh; bypassing flow and sending normal chat.`, "warn");
    }
    return payload;
  }
  const ok = await runFlowServer(ctx, payload);
  if (!ok?.ok) {
    ctx.log?.("[agent_flow] server run failed; falling back to normal assistant response", "warn");
    return payload;
  }
  return { ...payload, handled: true };
}

function deepClone(obj) {
  try {
    return JSON.parse(JSON.stringify(obj || {}));
  } catch {
    return {};
  }
}

function schemaDefaults(schema) {
  const defaults = {};
  for (const field of schema || []) {
    if (!field || typeof field !== "object") continue;
    const key = String(field.key || "").trim();
    if (!key) continue;
    if ("default" in field) defaults[key] = field.default;
  }
  return defaults;
}

function coerceBool(val) {
  if (typeof val === "string") {
    const v = val.trim().toLowerCase();
    if (["0", "false", "no", "off", ""].includes(v)) return false;
    if (["1", "true", "yes", "on"].includes(v)) return true;
  }
  return Boolean(val);
}

function buildPluginIdInput(pluginIds) {
  const wrap = document.createElement("div");
  wrap.style.display = "flex";
  wrap.style.flexDirection = "column";
  const select = document.createElement("select");
  pluginIds.forEach((pid) => {
    const opt = document.createElement("option");
    opt.value = pid;
    opt.textContent = pid;
    select.appendChild(opt);
  });
  wrap.appendChild(select);
  return { wrap, input: select, select };
}

function renderPanel(container, ctx) {
  ensureStyles();
  container.innerHTML = "";

  const pid = ctx.state.ui.activePid;
  const sid = ctx.state.ui.activeSid;
  if (!pid || !sid) {
    const empty = document.createElement("div");
    empty.className = "muted";
    empty.textContent = "Select a project and session first.";
    container.appendChild(empty);
    return;
  }

  ensureRouterState(ctx);

  const { enabled, settings } = getRouterConfig(ctx, sid);
  const agentSettings = deepClone(settings.agent_flow || {});
  let flows = deepClone(agentSettings.agent_flow_flows || {});
  let defaultFlow = getFlowNameByStableId(agentSettings, flows, getStoredDefaultFlowId(agentSettings))
    || String(agentSettings.agent_flow_default_flow || "");
  let currentFlow = "";
  let activeFlow = getFlowNameByStableId(agentSettings, flows, getStoredActiveFlowId(agentSettings))
    || String(agentSettings.agent_flow_active_flow || "");
  let flowListQuery = "";
  const flowListSkillFilters = new Set();
  const navSid = String(flowNavRequest?.sid || "").trim();
  const initialNavTarget = navSid && navSid === String(sid || "").trim()
    ? String(flowNavRequest?.flowName || "").trim()
    : "";
  if (activeFlow !== NO_FLOW_VALUE && !initialNavTarget) {
    if (!activeFlow || !flows[activeFlow]) {
      activeFlow = resolveActiveFlowName(agentSettings, flows);
    }
    if (activeFlow && activeFlow !== agentSettings.agent_flow_active_flow) {
      updateAgentFlowSettings(ctx, sid, buildFlowSelectionPatch(agentSettings, activeFlow, { mode: "active" }));
    }
  }
  currentFlow = initialNavTarget && flows[initialNavTarget]
    ? initialNavTarget
    : (activeFlow && activeFlow !== NO_FLOW_VALUE ? activeFlow : (Object.keys(flows)[0] || ""));

  const root = document.createElement("div");
  root.className = "agent-flow";
  container.appendChild(root);

  const canvasWrap = document.createElement("div");
  canvasWrap.className = "agent-flow-canvas-wrap";
  root.appendChild(canvasWrap);

  const canvasHeader = document.createElement("div");
  canvasHeader.className = "agent-flow-canvas-header";
  canvasWrap.appendChild(canvasHeader);

  const canvasTitle = document.createElement("div");
  canvasTitle.className = "section-title";
  canvasTitle.textContent = "Flow canvas";
  canvasHeader.appendChild(canvasTitle);

  const hint = document.createElement("div");
  hint.className = "flow-hint";
  canvasHeader.appendChild(hint);

  const canvas = document.createElement("div");
  canvas.className = "flow-canvas";
  canvasWrap.appendChild(canvas);
  const canvasInner = document.createElement("div");
  canvasInner.className = "flow-canvas-inner";
  canvas.appendChild(canvasInner);
  const selectionBox = document.createElement("div");
  selectionBox.className = "flow-selection-box";
  selectionBox.style.display = "none";
  canvasInner.appendChild(selectionBox);

  const viewControls = document.createElement("div");
  viewControls.className = "agent-flow-view-controls";
  const zoomOutBtn = document.createElement("button");
  zoomOutBtn.type = "button";
  zoomOutBtn.textContent = "-";
  zoomOutBtn.title = "Zoom out";
  const zoomLabel = document.createElement("span");
  zoomLabel.className = "zoom-label";
  const zoomInBtn = document.createElement("button");
  zoomInBtn.type = "button";
  zoomInBtn.textContent = "+";
  zoomInBtn.title = "Zoom in";
  viewControls.appendChild(zoomOutBtn);
  viewControls.appendChild(zoomLabel);
  viewControls.appendChild(zoomInBtn);
  canvasWrap.appendChild(viewControls);

  const leftPanel = document.createElement("div");
  leftPanel.className = "panel agent-flow-fly left";
  root.appendChild(leftPanel);

  const rightPanel = document.createElement("div");
  rightPanel.className = "panel agent-flow-fly right";
  root.appendChild(rightPanel);

  const leftTag = document.createElement("button");
  leftTag.className = "agent-flow-tag left";
  leftTag.textContent = "Flows";
  canvasWrap.appendChild(leftTag);

  const rightTag = document.createElement("button");
  rightTag.className = "agent-flow-tag right";
  rightTag.textContent = "Node";
  canvasWrap.appendChild(rightTag);
  const backTag = document.createElement("button");
  backTag.className = "agent-flow-tag right back";
  backTag.textContent = "<-- Back";
  backTag.style.display = "none";
  canvasWrap.appendChild(backTag);

  let leftOpen = Object.keys(flows).length === 0;
  let rightOpen = false;

  function setLeftOpen(open) {
    leftOpen = Boolean(open);
    leftPanel.classList.toggle("collapsed", !leftOpen);
    leftTag.textContent = leftOpen ? "Flows >>" : "Flows >>";
  }

  function setRightOpen(open) {
    rightOpen = Boolean(open);
    rightPanel.classList.toggle("collapsed", !rightOpen);
    rightTag.textContent = rightOpen ? "<< Node" : "<< Node";
  }

  leftTag.addEventListener("click", () => setLeftOpen(!leftOpen));
  rightTag.addEventListener("click", () => setRightOpen(!rightOpen));

  setLeftOpen(leftOpen);
  setRightOpen(rightOpen);

  const defaultLabel = document.createElement("div");
  defaultLabel.className = "small";
  leftPanel.appendChild(defaultLabel);

  const flowPickerWrap = document.createElement("div");
  flowPickerWrap.className = "flow-picker-wrap";
  leftPanel.appendChild(flowPickerWrap);

  const flowSearchRow = document.createElement("div");
  flowSearchRow.className = "agent-flow-search-row";
  const flowSearchShell = document.createElement("div");
  flowSearchShell.className = "agent-flow-search-shell";
  const flowSearchChevron = document.createElement("button");
  flowSearchChevron.type = "button";
  flowSearchChevron.className = "agent-flow-search-chevron";
  flowSearchChevron.textContent = "▾";
  flowSearchChevron.title = "Show workflow list";
  flowSearchChevron.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (flowListPopover.classList.contains("open")) closeFlowListPopover();
    else openFlowListPopover();
  });
  flowSearchShell.appendChild(flowSearchChevron);
  const flowSearch = document.createElement("input");
  flowSearch.type = "search";
  flowSearch.placeholder = "Search workflows";
  flowSearch.style.width = "100%";
  flowSearch.addEventListener("input", () => {
    flowListQuery = String(flowSearch.value || "");
    if (flowListSearchTimer) clearTimeout(flowListSearchTimer);
    flowListSearchTimer = setTimeout(() => {
      flowListSearchTimer = null;
      refreshFlowList();
    }, FLOW_SEARCH_IDLE_MS);
    openFlowListPopover();
  });
  flowSearch.addEventListener("focus", () => openFlowListPopover());
  flowSearch.addEventListener("click", (event) => {
    event.stopPropagation();
    openFlowListPopover();
  });
  flowSearch.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeFlowListPopover();
      flowSearch.blur();
    }
  });
  flowSearchShell.appendChild(flowSearch);
  const flowSearchFilters = buildFlowFilterControls({
    flows: () => flows,
    selectedCategories: flowListSkillFilters,
    menuClassName: "left-panel-filter-menu",
    onChange: () => {
      refreshFlowList();
      openFlowListPopover();
    },
  });
  flowSearchShell.appendChild(flowSearchFilters);
  flowSearchRow.appendChild(flowSearchShell);
  flowPickerWrap.appendChild(flowSearchRow);

  const flowListPopover = document.createElement("div");
  flowListPopover.className = "flow-list-popover";
  flowListPopover.addEventListener("click", (event) => event.stopPropagation());
  const flowListPopoverHead = document.createElement("div");
  flowListPopoverHead.className = "flow-list-popover-head";
  const flowListPopoverTitle = document.createElement("div");
  flowListPopoverTitle.className = "flow-list-popover-title";
  flowListPopoverTitle.textContent = "Workflow list";
  const flowListPopoverHeadActions = document.createElement("div");
  flowListPopoverHeadActions.className = "flow-list-popover-head-actions";
  const flowListPopoverTip = document.createElement("div");
  flowListPopoverTip.className = "flow-list-popover-tip";
  flowListPopoverTip.textContent = "Select a flow";
  const flowListPopoverClose = document.createElement("button");
  flowListPopoverClose.type = "button";
  flowListPopoverClose.className = "flow-list-popover-close";
  flowListPopoverClose.textContent = "x";
  flowListPopoverClose.title = "Close";
  flowListPopoverClose.addEventListener("click", (event) => {
    event.stopPropagation();
    closeFlowListPopover();
  });
  flowListPopoverHeadActions.appendChild(flowListPopoverTip);
  flowListPopoverHeadActions.appendChild(flowListPopoverClose);
  flowListPopoverHead.appendChild(flowListPopoverTitle);
  flowListPopoverHead.appendChild(flowListPopoverHeadActions);
  flowListPopover.appendChild(flowListPopoverHead);

  const flowList = document.createElement("div");
  flowList.className = "flow-list";
  flowListPopover.appendChild(flowList);
  document.body.appendChild(flowListPopover);
  if (container.__agentFlowFlowPickerOutsideHandler) {
    document.removeEventListener("click", container.__agentFlowFlowPickerOutsideHandler, true);
  }
  container.__agentFlowFlowPickerOutsideHandler = (event) => {
    if (!flowPickerWrap.contains(event.target) && !flowListPopover.contains(event.target)) closeFlowListPopover();
  };
  document.addEventListener("click", container.__agentFlowFlowPickerOutsideHandler, true);
  if (container.__agentFlowFlowPickerRepositionHandler) {
    window.removeEventListener("resize", container.__agentFlowFlowPickerRepositionHandler, true);
    window.removeEventListener("scroll", container.__agentFlowFlowPickerRepositionHandler, true);
  }
  container.__agentFlowFlowPickerRepositionHandler = () => {
    if (flowListPopover.classList.contains("open")) positionFlowListPopover();
  };
  window.addEventListener("resize", container.__agentFlowFlowPickerRepositionHandler, true);
  window.addEventListener("scroll", container.__agentFlowFlowPickerRepositionHandler, true);

  const flowButtons = document.createElement("div");
  flowButtons.className = "button-row";
  leftPanel.appendChild(flowButtons);

  const btnNew = document.createElement("button");
  btnNew.className = "ghost";
  btnNew.textContent = "New";
  const btnRename = document.createElement("button");
  btnRename.className = "ghost";
  btnRename.textContent = "Rename";
  const btnDelete = document.createElement("button");
  btnDelete.className = "ghost";
  btnDelete.textContent = "Delete";
  const importWrap = document.createElement("div");
  importWrap.className = "agent-flow-import-wrap";
  const btnImport = document.createElement("button");
  btnImport.className = "ghost";
  btnImport.textContent = "Import / Export / AWF ▾";
  importButtonNode = btnImport;
  awfLibraryButtonNode = btnImport;
  importWrap.appendChild(btnImport);
  const awfLaunchIndicator = document.createElement("div");
  awfLaunchIndicator.className = "agent-flow-awf-launch-indicator";
  awfLaunchIndicator.hidden = true;
  const awfLaunchSpinner = document.createElement("div");
  awfLaunchSpinner.className = "agent-flow-awf-spinner";
  awfLaunchSpinner.setAttribute("aria-hidden", "true");
  awfLaunchIndicator.appendChild(awfLaunchSpinner);
  const awfLaunchText = document.createElement("div");
  awfLaunchText.textContent = "Loading AWF...";
  awfLaunchIndicator.appendChild(awfLaunchText);
  importWrap.appendChild(awfLaunchIndicator);
  flowButtons.appendChild(btnNew);
  flowButtons.appendChild(btnRename);
  flowButtons.appendChild(btnDelete);
  flowButtons.appendChild(importWrap);

  const activeWrap = document.createElement("div");
  activeWrap.className = "properties";
  leftPanel.appendChild(activeWrap);

  const activeLabel = document.createElement("div");
  activeLabel.className = "small";
  activeLabel.textContent = "Active flow name:";
  activeWrap.appendChild(activeLabel);
  const btnBackFlow = document.createElement("button");
  btnBackFlow.className = "ghost";
  btnBackFlow.textContent = "<-- Back";
  btnBackFlow.style.display = "none";
  activeWrap.appendChild(btnBackFlow);
  const activeInput = document.createElement("input");
  activeInput.type = "text";
  activeInput.className = "agent-flow-active-input";
  activeInput.value = currentFlow;
  activeWrap.appendChild(activeInput);
  const activeIdField = document.createElement("label");
  activeIdField.className = "field";
  activeIdField.innerHTML = "<span>Workflow ID</span>";
  const activeIdInput = document.createElement("input");
  activeIdInput.type = "text";
  activeIdInput.readOnly = true;
  activeIdInput.placeholder = "Saved flows get a stable DB ID";
  activeIdField.appendChild(activeIdInput);
  activeWrap.appendChild(activeIdField);
  const quickSandboxProfileField = document.createElement("label");
  quickSandboxProfileField.className = "field";
  quickSandboxProfileField.innerHTML = "<span>Sandbox profile</span>";
  const quickSandboxProfileInput = document.createElement("select");
  [
    ["lightweight", "Lightweight"],
    ["independent", "Full Sandbox"],
  ].forEach(([value, label]) => {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = label;
    quickSandboxProfileInput.appendChild(opt);
  });
  quickSandboxProfileInput.value = normalizeSandboxProfileSetting(agentSettings.agent_flow_autobuild_sandbox_profile, "lightweight");
  quickSandboxProfileField.appendChild(quickSandboxProfileInput);
  activeWrap.appendChild(quickSandboxProfileField);
  const quickSandboxProfileHelp = document.createElement("div");
  quickSandboxProfileHelp.className = "small";
  quickSandboxProfileHelp.textContent = "Lightweight keeps batch autobuild validation short. Full Sandbox runs the fuller standalone validation path.";
  activeWrap.appendChild(quickSandboxProfileHelp);

  const workflowSettingsCard = document.createElement("details");
  workflowSettingsCard.className = "flow-meta-card";
  workflowSettingsCard.open = false;
  const workflowSettingsSummary = document.createElement("summary");
  const workflowSettingsTitle = document.createElement("div");
  workflowSettingsTitle.className = "section-title";
  workflowSettingsTitle.textContent = "Workflow settings";
  workflowSettingsSummary.appendChild(workflowSettingsTitle);
  workflowSettingsCard.appendChild(workflowSettingsSummary);
  const workflowSettingsBody = document.createElement("div");
  workflowSettingsBody.className = "flow-meta-card-body";
  const flowReadOnlyField = document.createElement("label");
  flowReadOnlyField.className = "field";
  flowReadOnlyField.innerHTML = "<span>Read-only</span>";
  const flowReadOnlyInput = document.createElement("input");
  flowReadOnlyInput.type = "checkbox";
  flowReadOnlyField.appendChild(flowReadOnlyInput);
  workflowSettingsBody.appendChild(flowReadOnlyField);
  const sandboxProfileField = document.createElement("label");
  sandboxProfileField.className = "field";
  sandboxProfileField.innerHTML = "<span>Autobuild sandbox profile</span>";
  const sandboxProfileInput = document.createElement("select");
  [
    ["lightweight", "Lightweight (default)"],
    ["independent", "Full Sandbox"],
  ].forEach(([value, label]) => {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = label;
    sandboxProfileInput.appendChild(opt);
  });
  sandboxProfileInput.value = normalizeSandboxProfileSetting(agentSettings.agent_flow_autobuild_sandbox_profile, "lightweight");
  sandboxProfileField.appendChild(sandboxProfileInput);
  workflowSettingsBody.appendChild(sandboxProfileField);
  const loopSettingField = document.createElement("label");
  loopSettingField.className = "field";
  loopSettingField.innerHTML = "<span>Default loop max passes</span>";
  const loopSettingInput = document.createElement("input");
  loopSettingInput.type = "number";
  loopSettingInput.min = "0";
  loopSettingInput.step = "1";
  loopSettingInput.value = String(normalizeLoopMaxSetting(agentSettings.agent_flow_loop_max_passes, 16));
  loopSettingField.appendChild(loopSettingInput);
  workflowSettingsBody.appendChild(loopSettingField);
  const timeoutSettingField = document.createElement("label");
  timeoutSettingField.className = "field";
  timeoutSettingField.innerHTML = "<span>Sandbox request timeout (s)</span>";
  const timeoutSettingInput = document.createElement("input");
  timeoutSettingInput.type = "number";
  timeoutSettingInput.min = "0";
  timeoutSettingInput.step = "1";
  timeoutSettingInput.value = String(normalizeTimeoutSetting(agentSettings.agent_flow_request_timeout_s, 45));
  timeoutSettingField.appendChild(timeoutSettingInput);
  workflowSettingsBody.appendChild(timeoutSettingField);
  const lightweightProfileGroup = document.createElement("div");
  lightweightProfileGroup.className = "agent-flow-profile-group";
  workflowSettingsBody.appendChild(lightweightProfileGroup);
  const nestedLightTitle = document.createElement("div");
  nestedLightTitle.className = "section-title";
  nestedLightTitle.textContent = "Lightweight Profile";
  lightweightProfileGroup.appendChild(nestedLightTitle);
  const lightMaxRequestsField = document.createElement("label");
  lightMaxRequestsField.className = "field";
  lightMaxRequestsField.innerHTML = "<span>Requests per generated workflow</span>";
  const lightMaxRequestsInput = document.createElement("input");
  lightMaxRequestsInput.type = "number";
  lightMaxRequestsInput.min = "1";
  lightMaxRequestsInput.step = "1";
  lightMaxRequestsInput.value = String(Math.max(1, Math.trunc(Number(agentSettings.agent_flow_autobuild_lightweight_max_requests ?? 1) || 1)));
  lightMaxRequestsField.appendChild(lightMaxRequestsInput);
  lightweightProfileGroup.appendChild(lightMaxRequestsField);
  const lightWaitField = document.createElement("label");
  lightWaitField.className = "field";
  lightWaitField.innerHTML = "<span>Request wait timeout (s)</span>";
  const lightWaitInput = document.createElement("input");
  lightWaitInput.type = "number";
  lightWaitInput.min = "0";
  lightWaitInput.step = "1";
  lightWaitInput.value = String(normalizeTimeoutSetting(agentSettings.agent_flow_autobuild_lightweight_wait_s, 120));
  lightWaitField.appendChild(lightWaitInput);
  lightweightProfileGroup.appendChild(lightWaitField);
  const lightGraceField = document.createElement("label");
  lightGraceField.className = "field";
  lightGraceField.innerHTML = "<span>Final-step grace (s)</span>";
  const lightGraceInput = document.createElement("input");
  lightGraceInput.type = "number";
  lightGraceInput.min = "0";
  lightGraceInput.step = "1";
  lightGraceInput.value = String(normalizeTimeoutSetting(agentSettings.agent_flow_autobuild_lightweight_final_grace_s, 10));
  lightGraceField.appendChild(lightGraceInput);
  lightweightProfileGroup.appendChild(lightGraceField);
  const independentProfileGroup = document.createElement("div");
  independentProfileGroup.className = "agent-flow-profile-group";
  workflowSettingsBody.appendChild(independentProfileGroup);
  const independentTitle = document.createElement("div");
  independentTitle.className = "section-title";
  independentTitle.textContent = "Full Sandbox Profile";
  independentProfileGroup.appendChild(independentTitle);
  const independentMaxRequestsField = document.createElement("label");
  independentMaxRequestsField.className = "field";
  independentMaxRequestsField.innerHTML = "<span>Requests per generated workflow</span>";
  const independentMaxRequestsInput = document.createElement("input");
  independentMaxRequestsInput.type = "number";
  independentMaxRequestsInput.min = "1";
  independentMaxRequestsInput.step = "1";
  independentMaxRequestsInput.value = String(Math.max(1, Math.trunc(Number(agentSettings.agent_flow_autobuild_independent_max_requests ?? 3) || 3)));
  independentMaxRequestsField.appendChild(independentMaxRequestsInput);
  independentProfileGroup.appendChild(independentMaxRequestsField);
  const independentWaitField = document.createElement("label");
  independentWaitField.className = "field";
  independentWaitField.innerHTML = "<span>Request wait timeout (s)</span>";
  const independentWaitInput = document.createElement("input");
  independentWaitInput.type = "number";
  independentWaitInput.min = "0";
  independentWaitInput.step = "1";
  independentWaitInput.value = String(normalizeTimeoutSetting(agentSettings.agent_flow_autobuild_independent_wait_s, 180));
  independentWaitField.appendChild(independentWaitInput);
  independentProfileGroup.appendChild(independentWaitField);
  const independentGraceField = document.createElement("label");
  independentGraceField.className = "field";
  independentGraceField.innerHTML = "<span>Final-step grace (s)</span>";
  const independentGraceInput = document.createElement("input");
  independentGraceInput.type = "number";
  independentGraceInput.min = "0";
  independentGraceInput.step = "1";
  independentGraceInput.value = String(normalizeTimeoutSetting(agentSettings.agent_flow_autobuild_independent_final_grace_s, 20));
  independentGraceField.appendChild(independentGraceInput);
  independentProfileGroup.appendChild(independentGraceField);
  const loopOverrideField = document.createElement("label");
  loopOverrideField.className = "field";
  loopOverrideField.innerHTML = "<span>Override all edge loop caps</span>";
  const loopOverrideInput = document.createElement("input");
  loopOverrideInput.type = "checkbox";
  loopOverrideInput.checked = normalizeBoolSetting(agentSettings.agent_flow_force_loop_max_passes, false);
  loopOverrideField.appendChild(loopOverrideInput);
  workflowSettingsBody.appendChild(loopOverrideField);
  const workflowSettingsHelp = document.createElement("div");
  workflowSettingsHelp.className = "small";
  workflowSettingsHelp.textContent = "Use 0 for unlimited. Loop max passes is the workflow-level default for new loop edges and for runtime loops without an explicit cap. Enable override to force that cap onto all loop edges and retry loops. Autobuild sandbox profile controls how generated workflows are validated: Lightweight is intended for looped parent builders, Full Sandbox is the fuller standalone profile.";
  workflowSettingsBody.appendChild(workflowSettingsHelp);
  const flowInfoCard = document.createElement("details");
  flowInfoCard.className = "flow-meta-card";
  flowInfoCard.open = false;
  const flowInfoSummary = document.createElement("summary");
  const flowInfoTitle = document.createElement("div");
  flowInfoTitle.className = "section-title";
  flowInfoTitle.textContent = "Flow info";
  flowInfoSummary.appendChild(flowInfoTitle);
  flowInfoCard.appendChild(flowInfoSummary);
  const flowInfoBody = document.createElement("div");
  flowInfoBody.className = "flow-meta-card-body";
  const flowInfoField = document.createElement("label");
  flowInfoField.className = "field";
  flowInfoField.innerHTML = "<span>Description and intended use</span>";
  const flowInfoInput = document.createElement("textarea");
  flowInfoInput.placeholder = "Describe what this flow does, what inputs it expects, and when AutoFlow should route a user to it.";
  flowInfoField.appendChild(flowInfoInput);
  flowInfoBody.appendChild(flowInfoField);
  const flowInfoHelp = document.createElement("div");
  flowInfoHelp.className = "small";
  flowInfoHelp.textContent = "AutoFlow uses this description with node labels and plugin IDs to route No flow requests.";
  flowInfoBody.appendChild(flowInfoHelp);
  flowInfoCard.appendChild(flowInfoBody);
  activeWrap.appendChild(flowInfoCard);
  workflowSettingsCard.appendChild(workflowSettingsBody);
  activeWrap.appendChild(workflowSettingsCard);

  const btnDefault = document.createElement("button");
  btnDefault.className = "primary";
  btnDefault.textContent = "Set as default for session";
  const btnSave = document.createElement("button");
  btnSave.className = "ghost";
  btnSave.textContent = "Save flows to project";
  activeWrap.appendChild(btnDefault);
  activeWrap.appendChild(btnSave);

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("flow-svg");
  canvasInner.appendChild(svg);

  const propsTitle = document.createElement("div");
  propsTitle.className = "section-title";
  propsTitle.textContent = "Node properties";
  rightPanel.appendChild(propsTitle);

  const props = document.createElement("div");
  props.className = "properties";
  rightPanel.appendChild(props);

  const nodeIdLabel = document.createElement("div");
  nodeIdLabel.className = "small";
  props.appendChild(nodeIdLabel);

  const labelField = document.createElement("label");
  labelField.className = "field";
  labelField.innerHTML = "<span>Label</span>";
  const labelInput = document.createElement("input");
  labelInput.type = "text";
  labelField.appendChild(labelInput);
  props.appendChild(labelField);

  function resolvePluginIds(list, manifestObj) {
    const manifestIds = Object.keys(manifestObj || {}).filter((id) => id && id !== "agent_flow");
    const base = manifestIds.length ? manifestIds : (list || []).filter((id) => id && id !== "agent_flow");
    const out = Array.isArray(base) ? base.slice() : [];
    if (!out.includes("agent_flow_subflow")) out.push("agent_flow_subflow");
    return out.length ? out : [];
  }

  let manifest = ctx.state.router.manifest || {};
  let pluginIds = resolvePluginIds(enabled, manifest);
  const pluginIdField = document.createElement("label");
  pluginIdField.className = "field";
  pluginIdField.innerHTML = "<span>Plugin ID</span>";
  const pluginInputWrap = buildPluginIdInput(pluginIds);
  pluginIdField.appendChild(pluginInputWrap.wrap);
  props.appendChild(pluginIdField);

  const agentField = document.createElement("label");
  agentField.className = "field";
  agentField.innerHTML = "<span>Agent kind (Optional tag)</span>";
  const agentInput = document.createElement("input");
  agentInput.type = "text";
  agentField.appendChild(agentInput);
  props.appendChild(agentField);

  const delayField = document.createElement("label");
  delayField.className = "field";
  delayField.innerHTML = "<span>Delay (ms)</span>";
  const delayInput = document.createElement("input");
  delayInput.type = "number";
  delayInput.min = "0";
  delayInput.step = "1";
  delayField.appendChild(delayInput);
  props.appendChild(delayField);

  const promptField = document.createElement("label");
  promptField.className = "field";
  promptField.innerHTML = "<span>System prompt</span>";
  const promptInput = document.createElement("textarea");
  promptField.appendChild(promptInput);
  props.appendChild(promptField);

  const returnOnlyField = document.createElement("label");
  returnOnlyField.className = "field";
  const returnOnlyWrap = document.createElement("div");
  returnOnlyWrap.style.display = "flex";
  returnOnlyWrap.style.alignItems = "center";
  returnOnlyWrap.style.gap = "8px";
  const returnOnlyInput = document.createElement("input");
  returnOnlyInput.type = "checkbox";
  returnOnlyInput.checked = true;
  const returnOnlyLabel = document.createElement("span");
  returnOnlyLabel.textContent = "Return only text";
  returnOnlyWrap.appendChild(returnOnlyInput);
  returnOnlyWrap.appendChild(returnOnlyLabel);
  returnOnlyField.appendChild(returnOnlyWrap);
  props.appendChild(returnOnlyField);

  const pluginSettingsTitle = document.createElement("div");
  pluginSettingsTitle.className = "section-title";
  pluginSettingsTitle.textContent = "Plugin settings";
  props.appendChild(pluginSettingsTitle);
  const pluginSettingsBox = document.createElement("div");
  props.appendChild(pluginSettingsBox);

  const transitionsCard = document.createElement("details");
  transitionsCard.className = "flow-meta-card";
  transitionsCard.open = false;
  const transitionsSummary = document.createElement("summary");
  const transitionsTitle = document.createElement("div");
  transitionsTitle.className = "section-title";
  transitionsTitle.textContent = "Transitions";
  transitionsSummary.appendChild(transitionsTitle);
  transitionsCard.appendChild(transitionsSummary);
  const transitionsBody = document.createElement("div");
  transitionsBody.className = "flow-meta-card-body";
  const transitionsBox = document.createElement("div");
  transitionsBox.className = "transition-list";
  transitionsBody.appendChild(transitionsBox);
  const btnAddTransition = document.createElement("button");
  btnAddTransition.className = "ghost";
  btnAddTransition.textContent = "Add transition";
  transitionsBody.appendChild(btnAddTransition);
  transitionsCard.appendChild(transitionsBody);
  props.appendChild(transitionsCard);

  const propsButtons = document.createElement("div");
  propsButtons.className = "button-row";
  const btnApply = document.createElement("button");
  btnApply.className = "primary";
  btnApply.textContent = "Apply changes";
  propsButtons.appendChild(btnApply);
  rightPanel.appendChild(propsButtons);

  let selectedNodeId = "";
  let selectedNodeIds = new Set();
  let linkSourceId = "";
  const flowNavStack = [];
  let pluginSettingsInputs = [];
  let transitionInputs = [];
  let saveTimer = null;
  const nodeElements = new Map();
  let contextMenu = null;
  if (!ctx.state.agent_flow_view || typeof ctx.state.agent_flow_view !== "object") {
    ctx.state.agent_flow_view = {};
  }
  const viewKey = `${pid || "default"}:${sid || "default"}`;
  const canvasView = ctx.state.agent_flow_view[viewKey] && typeof ctx.state.agent_flow_view[viewKey] === "object"
    ? ctx.state.agent_flow_view[viewKey]
    : { zoom: 1 };
  ctx.state.agent_flow_view[viewKey] = canvasView;
  if (typeof canvasView.zoom !== "number" || Number.isNaN(canvasView.zoom)) canvasView.zoom = 1;
  const focusView = { active: false, zoom: 1, left: 0, top: 0 };
  let canvasLogicalWidth = 900;
  let canvasLogicalHeight = 620;

  function clampZoom(value) {
    return Math.max(0.35, Math.min(1.8, Number(value) || 1));
  }

  function applyCanvasZoom(persist = false) {
    canvasView.zoom = clampZoom(canvasView.zoom);
    canvasInner.style.setProperty("--agent-flow-zoom", String(canvasView.zoom));
    zoomLabel.textContent = `${Math.round(canvasView.zoom * 100)}%`;
    if (persist) ctx.saveState?.();
  }

  function setCanvasZoom(nextZoom, persist = true) {
    const before = Number(canvasView.zoom) || 1;
    const centerX = (canvas.scrollLeft + canvas.clientWidth / 2) / before;
    const centerY = (canvas.scrollTop + canvas.clientHeight / 2) / before;
    canvasView.zoom = clampZoom(nextZoom);
    applyCanvasZoom(persist);
    canvas.scrollLeft = Math.max(0, centerX * canvasView.zoom - canvas.clientWidth / 2);
    canvas.scrollTop = Math.max(0, centerY * canvasView.zoom - canvas.clientHeight / 2);
  }

  function focusNodeInCanvas(nodeId) {
    const node = getCurrentNodes()[nodeId];
    if (!node) return;
    if (!focusView.active) {
      focusView.active = true;
      focusView.zoom = Number(canvasView.zoom) || 1;
      focusView.left = canvas.scrollLeft;
      focusView.top = canvas.scrollTop;
    }
    canvasView.zoom = Math.max(1.2, Number(canvasView.zoom) || 1);
    applyCanvasZoom(false);
    const centerX = (Number(node.x) || 0) + NODE_W / 2;
    const centerY = (Number(node.y) || 0) + NODE_H / 2;
    canvas.scrollTo({
      left: Math.max(0, centerX * canvasView.zoom - canvas.clientWidth / 2),
      top: Math.max(0, centerY * canvasView.zoom - canvas.clientHeight / 2),
      behavior: "smooth",
    });
  }

  function restoreCanvasFocus() {
    if (!focusView.active) return false;
    focusView.active = false;
    canvasView.zoom = focusView.zoom || 1;
    applyCanvasZoom(false);
    canvas.scrollTo({ left: focusView.left || 0, top: focusView.top || 0, behavior: "smooth" });
    return true;
  }

  applyCanvasZoom(false);
  zoomOutBtn.addEventListener("click", () => setCanvasZoom((Number(canvasView.zoom) || 1) - 0.1));
  zoomInBtn.addEventListener("click", () => setCanvasZoom((Number(canvasView.zoom) || 1) + 0.1));

  function syncActiveFlowFromState() {
    const settings = getAgentFlowSettings(ctx, sid);
    const raw = String(settings.agent_flow_active_flow || "");
    if (raw === NO_FLOW_VALUE) {
      activeFlow = NO_FLOW_VALUE;
      return;
    }
    activeFlow = resolveActiveFlowName(settings, flows);
  }

  function scheduleSave() {
    if (saveTimer) return;
    saveTimer = setTimeout(() => {
      saveTimer = null;
      saveFlows(false);
    }, 300);
  }

  function closeContextMenu() {
    if (contextMenu) {
      contextMenu.remove();
      contextMenu = null;
    }
  }

  function openContextMenu(x, y, items) {
    closeContextMenu();
    const menu = document.createElement("div");
    menu.className = "context-menu";
    items.forEach((item) => {
      const btn = document.createElement("button");
      btn.textContent = item.label;
      if (item.disabled) btn.disabled = true;
      btn.addEventListener("click", (event) => {
        event.stopPropagation();
        closeContextMenu();
        item.onClick?.();
      });
      menu.appendChild(btn);
    });
    menu.style.left = `${x}px`;
    menu.style.top = `${y}px`;
    canvasInner.appendChild(menu);
    const zoom = Number(canvasView.zoom) || 1;
    const menuW = menu.offsetWidth || 160;
    const menuH = menu.offsetHeight || 44;
    const minLeft = canvas.scrollLeft / zoom + 6;
    const minTop = canvas.scrollTop / zoom + 6;
    const maxLeft = (canvas.scrollLeft + canvas.clientWidth) / zoom - menuW - 6;
    const maxTop = (canvas.scrollTop + canvas.clientHeight) / zoom - menuH - 6;
    menu.style.left = `${Math.max(minLeft, Math.min(x, maxLeft))}px`;
    menu.style.top = `${Math.max(minTop, Math.min(y, maxTop))}px`;
    contextMenu = menu;
  }

  function startLongPress(event, onTrigger) {
    if (!event || event.pointerType !== "touch") return null;
    const startX = event.clientX;
    const startY = event.clientY;
    let triggered = false;
    const timer = setTimeout(() => {
      triggered = true;
      onTrigger?.();
    }, 520);
    return {
      isTriggered: () => triggered,
      move: (moveEvent) => {
        const dx = moveEvent.clientX - startX;
        const dy = moveEvent.clientY - startY;
        if (Math.hypot(dx, dy) > 8) {
          clearTimeout(timer);
        }
      },
      cancel: () => {
        clearTimeout(timer);
      },
    };
  }

  function canvasPointFromEvent(event) {
    const rect = canvas.getBoundingClientRect();
    const zoom = Number(canvasView.zoom) || 1;
    const x = (event.clientX - rect.left + canvas.scrollLeft) / zoom;
    const y = (event.clientY - rect.top + canvas.scrollTop) / zoom;
    return { x, y };
  }

  function saveFlows(notify) {
    const freshSettings = getAgentFlowSettings(ctx, sid);
    const raw = String(freshSettings.agent_flow_active_flow || "");
    const activeFlowName = raw === NO_FLOW_VALUE ? NO_FLOW_VALUE : resolveActiveFlowName(freshSettings, flows);
    const activeFlowId = activeFlowName && activeFlowName !== NO_FLOW_VALUE ? getFlowStableId(freshSettings, activeFlowName) : "";
    const defaultFlowId = defaultFlow ? getFlowStableId(freshSettings, defaultFlow) : "";
    const cfg = {
      ...(freshSettings || {}),
      agent_flow_flows: flows,
      agent_flow_default_flow: defaultFlow || "",
      agent_flow_default_workflow_id: defaultFlowId,
      agent_flow_active_flow: activeFlowName || "",
      agent_flow_active_workflow_id: activeFlowId,
    };
    activeFlow = activeFlowName === NO_FLOW_VALUE ? "" : (activeFlowName || "");
    setRouterSettings(ctx, sid, "agent_flow", cfg);
    persistProjectFlows(ctx, pid, sid, flows).then((res) => {
      const nextIds = normalizeFlowIdMap(res?.flowIdsByName);
      if (!Object.keys(nextIds).length) return;
      const latest = getAgentFlowSettings(ctx, sid) || {};
      setRouterSettings(ctx, sid, "agent_flow", {
        ...(latest || {}),
        agent_flow_flow_ids_by_name: nextIds,
        agent_flow_active_workflow_id: activeFlowName && activeFlowName !== NO_FLOW_VALUE ? String(nextIds[activeFlowName] || latest.agent_flow_active_workflow_id || "").trim() : "",
        agent_flow_default_workflow_id: defaultFlow ? String(nextIds[defaultFlow] || latest.agent_flow_default_workflow_id || "").trim() : "",
      });
      refreshFlowList();
      updateActivePanel();
      updateBottomBar(ctx);
    });
    if (notify) ctx.log?.("[agent_flow] flows saved", "info");
  }

  function exportFlowsJson() {
    const freshSettings = getAgentFlowSettings(ctx, sid) || {};
    const rawActive = String(freshSettings.agent_flow_active_flow || "").trim();
    const resolvedActive = rawActive === NO_FLOW_VALUE ? NO_FLOW_VALUE : (resolveActiveFlowName(freshSettings, flows) || "");
    const selectedFlowName = currentFlow && flows?.[currentFlow]
      ? currentFlow
      : ((resolvedActive && resolvedActive !== NO_FLOW_VALUE && flows?.[resolvedActive]) ? resolvedActive : "");
    if (!selectedFlowName || !flows?.[selectedFlowName]) {
      throw new Error("No selected workflow to export.");
    }
    const selectedWorkflowId = getFlowStableId(freshSettings, selectedFlowName);
    const selectedFlowIds = selectedWorkflowId ? { [selectedFlowName]: selectedWorkflowId } : {};
    const payload = {
      flows: {
        [selectedFlowName]: deepClone(flows[selectedFlowName] || {}),
      },
      flow_ids_by_name: selectedFlowIds,
      default_flow_ids_by_name: selectedFlowIds,
      root_flow: selectedFlowName,
      exported_workflow_id: selectedWorkflowId,
      default_flow: selectedFlowName,
      active_flow: selectedFlowName,
      mode: String(freshSettings.agent_flow_mode || "execute").trim() || "execute",
      max_steps: Number(freshSettings.agent_flow_max_steps || 32),
      loop_max_passes: normalizeLoopMaxSetting(freshSettings.agent_flow_loop_max_passes, 16),
      force_loop_max_passes: normalizeBoolSetting(freshSettings.agent_flow_force_loop_max_passes, false),
      request_timeout_s: normalizeTimeoutSetting(freshSettings.agent_flow_request_timeout_s, 45),
      autobuild_sandbox_profile: normalizeSandboxProfileSetting(freshSettings.agent_flow_autobuild_sandbox_profile, "lightweight"),
      autobuild_lightweight_max_requests: Math.max(1, Math.trunc(Number(freshSettings.agent_flow_autobuild_lightweight_max_requests ?? 1) || 1)),
      autobuild_lightweight_wait_s: normalizeTimeoutSetting(freshSettings.agent_flow_autobuild_lightweight_wait_s, 120),
      autobuild_lightweight_final_grace_s: normalizeTimeoutSetting(freshSettings.agent_flow_autobuild_lightweight_final_grace_s, 10),
      autobuild_independent_max_requests: Math.max(1, Math.trunc(Number(freshSettings.agent_flow_autobuild_independent_max_requests ?? 3) || 3)),
      autobuild_independent_wait_s: normalizeTimeoutSetting(freshSettings.agent_flow_autobuild_independent_wait_s, 180),
      autobuild_independent_final_grace_s: normalizeTimeoutSetting(freshSettings.agent_flow_autobuild_independent_final_grace_s, 20),
    };
    const flowPart = selectedFlowName;
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    const filename = `agent_flow_${flowPart}_${stamp}.json`;
    const json = JSON.stringify(payload, null, 2);
    const blob = new Blob([json], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
    ctx.log?.(`[agent_flow] exported selected flow JSON: ${filename}`, "info");
  }

  function updateDefaultLabel() {
    defaultLabel.textContent = `Default flow for this session: ${defaultFlow || ""}`;
  }

  function currentFlowIsReadOnly() {
    if (!currentFlow || !flows[currentFlow] || typeof flows[currentFlow] !== "object") return false;
    return Boolean(flows[currentFlow].read_only);
  }

  function findSubflowUsage(targetFlowName) {
    const target = String(targetFlowName || "").trim();
    if (!target) return [];
    const out = [];
    Object.entries(flows || {}).forEach(([flowName, flowDef]) => {
      if (!flowDef || typeof flowDef !== "object" || !flowDef.nodes || typeof flowDef.nodes !== "object") return;
      const refs = [];
      Object.entries(flowDef.nodes || {}).forEach(([nodeId, node]) => {
        if (!node || typeof node !== "object") return;
        if (String(node.plugin_id || "").trim() !== "agent_flow_subflow") return;
        const subflowName = String((node.plugin_settings || {}).subflow_name || "").trim();
        if (subflowName !== target) return;
        refs.push({
          nodeId,
          label: String(node.label || nodeId || "").trim() || nodeId,
        });
      });
      if (refs.length) {
        out.push({ flowName, refs });
      }
    });
    return out;
  }

  function updateWorkflowSettingsProfileUi() {
    const profile = normalizeSandboxProfileSetting(sandboxProfileInput.value, "lightweight");
    quickSandboxProfileInput.value = profile;
    const showLightweight = profile === "lightweight";
    lightweightProfileGroup.classList.toggle("hidden", !showLightweight);
    independentProfileGroup.classList.toggle("hidden", showLightweight);
  }

  function updateReadOnlyUi() {
    const has = Boolean(currentFlow);
    const readOnly = has && currentFlowIsReadOnly();
    flowReadOnlyInput.checked = readOnly;
    activeInput.disabled = !has || readOnly;
    flowInfoInput.disabled = !has || readOnly;
    btnRename.disabled = !has || readOnly;
    btnDelete.disabled = !has || readOnly;
    btnApply.disabled = !selectedNodeId || readOnly;
    btnAddTransition.disabled = !selectedNodeId || readOnly;
    labelInput.disabled = !selectedNodeId || readOnly;
    pluginInputWrap.input.disabled = !selectedNodeId || readOnly;
    pluginInputWrap.select.disabled = !selectedNodeId || readOnly;
    agentInput.disabled = !selectedNodeId || readOnly;
    delayInput.disabled = !selectedNodeId || readOnly;
    promptInput.disabled = !selectedNodeId || readOnly;
    returnOnlyInput.disabled = !selectedNodeId || readOnly;
    canvasInner.querySelectorAll(".flow-node").forEach((el) => {
      el.classList.toggle("read-only", readOnly);
    });
    if (readOnly) {
      hint.textContent = "This workflow is read-only. Disable Read-only to edit nodes or transitions.";
    } else if (hint.textContent.includes("read-only")) {
      updateHint();
    }
  }

  function updateActivePanel() {
    const has = Boolean(currentFlow);
    activeWrap.style.display = has ? "" : "none";
    flowInfoCard.style.display = has ? "" : "none";
    if (has) {
      const flow = ensureFlow(currentFlow);
      flowInfoInput.value = getFlowDescription(flow);
      flowReadOnlyInput.checked = Boolean(flow.read_only);
      activeIdInput.value = getFlowStableId(getAgentFlowSettings(ctx, sid), currentFlow);
    } else {
      flowInfoInput.value = "";
      flowReadOnlyInput.checked = false;
      activeIdInput.value = "";
    }
    updateReadOnlyUi();
  }

  function refreshFlowList() {
    flowList.innerHTML = "";
    const names = Object.keys(flows).sort();
    const filteredNames = names.filter((name) => flowMatchesQuery(name, flows[name], flowListQuery, flowListSkillFilters));
    if (!names.length) {
      const empty = document.createElement("div");
      empty.className = "muted";
      empty.textContent = "No flows yet.";
      flowList.appendChild(empty);
      flowListPopoverTip.textContent = "No saved flows";
      updateActivePanel();
      return;
    }
    if (!filteredNames.length) {
      const empty = document.createElement("div");
      empty.className = "muted";
      empty.textContent = "No matching workflows.";
      flowList.appendChild(empty);
      flowListPopoverTip.textContent = "No matches";
      updateActivePanel();
      return;
    }
    flowListPopoverTip.textContent = `${filteredNames.length} result${filteredNames.length === 1 ? "" : "s"}`;
    filteredNames.forEach((name) => {
      const item = document.createElement("div");
      item.className = "list-item" + (name === currentFlow ? " active" : "");
      const nameEl = document.createElement("div");
      nameEl.className = "flow-name";
      nameEl.textContent = flows[name]?.read_only ? `${name} [read-only]` : name;
      item.appendChild(nameEl);
      const workflowId = getFlowStableId(getAgentFlowSettings(ctx, sid), name);
      if (workflowId) {
        const idEl = document.createElement("div");
        idEl.className = "flow-info";
        idEl.textContent = `ID: ${shortFlowStableId(workflowId)}`;
        item.appendChild(idEl);
      }
      const desc = getFlowDescription(flows[name]);
      if (desc) {
        const infoEl = document.createElement("div");
        infoEl.className = "flow-info";
        infoEl.textContent = desc;
        item.appendChild(infoEl);
      }
      item.addEventListener("click", () => {
        loadFlow(name, { resetNav: true });
        closeFlowListPopover();
      });
      flowList.appendChild(item);
    });
    updateActivePanel();
  }

  function openFlowListPopover() {
    positionFlowListPopover();
    flowListPopover.classList.add("open");
    flowSearchChevron.classList.add("open");
    flowSearchChevron.textContent = "▴";
    flowSearchChevron.title = "Hide workflow list";
  }

  function closeFlowListPopover() {
    flowListPopover.classList.remove("open");
    flowSearchChevron.classList.remove("open");
    flowSearchChevron.textContent = "▾";
    flowSearchChevron.title = "Show workflow list";
  }

  function positionFlowListPopover() {
    if (!flowListPopover || !flowSearchShell) return;
    const rect = flowSearchShell.getBoundingClientRect();
    const { width, height, offsetTop, gutter } = getPopoverViewportMetrics();
    const targetWidth = Math.min(520, Math.max(280, rect.width));
    flowListPopover.style.width = `${Math.min(targetWidth, Math.max(240, width - (gutter * 2)))}px`;
    const headerHeight = 64;
    const spaceBelow = Math.max(0, (offsetTop + height) - rect.bottom - gutter - headerHeight);
    const spaceAbove = Math.max(0, rect.top - offsetTop - gutter - headerHeight);
    const preferredSpace = Math.max(spaceBelow, spaceAbove);
    const listHeight = Math.max(160, Math.min(460, preferredSpace || spaceBelow || spaceAbove || 160));
    flowList.style.height = `${listHeight}px`;
    flowList.style.minHeight = `${listHeight}px`;
    flowList.style.maxHeight = `${listHeight}px`;
    flowList.style.overflowY = "auto";
    flowList.style.overflowX = "hidden";
    positionPopoverAroundRect(flowListPopover, rect, {
      align: "left",
      fallbackWidth: targetWidth,
      fallbackHeight: listHeight + headerHeight,
      offsetY: 8,
    });
  }

  async function syncFlowsFromServer() {
    const serverPayload = await fetchProjectFlows(ctx, pid, sid);
    const serverFlows = serverPayload?.flows;
    if (!serverFlows || typeof serverFlows !== "object") {
      ctx?.log?.(`[agent_flow] syncFlowsFromServer: no server flows for pid=${pid} sid=${sid}`, "warn");
      return;
    }
    flows = deepClone(serverFlows);
    try {
      ctx?.log?.(`[agent_flow] syncFlowsFromServer applied flows=${Object.keys(flows).length}`, "info");
    } catch {}
    const freshSettings = getAgentFlowSettings(ctx, sid);
    const cfg = {
      ...(freshSettings || {}),
      agent_flow_flows: flows,
      agent_flow_flow_ids_by_name: normalizeFlowIdMap(serverPayload?.flowIdsByName),
      agent_flow_default_flow_ids_by_name: normalizeFlowIdMap(serverPayload?.defaultFlowIdsByName),
    };
    setRouterSettings(ctx, sid, "agent_flow", cfg);
    const rawActive = String(cfg.agent_flow_active_flow || "").trim();
    const noFlowActive = rawActive === NO_FLOW_VALUE || (Object.prototype.hasOwnProperty.call(cfg, "agent_flow_active_flow") && rawActive === "");
    if (!noFlowActive && activeFlow && !flows[activeFlow]) {
      activeFlow = resolveActiveFlowName(cfg, flows);
      updateAgentFlowSettings(ctx, sid, buildFlowSelectionPatch(cfg, activeFlow, { mode: "active" }));
    }
    currentFlow = activeFlow && activeFlow !== NO_FLOW_VALUE && flows[activeFlow]
      ? activeFlow
      : (currentFlow && flows[currentFlow] ? currentFlow : (Object.keys(flows)[0] || ""));
    refreshFlowList();
    updateActivePanel();
    renderCanvas();
    updateBackButton();
    updateDefaultLabel();
    consumeFlowNavRequest();
  }

  function ensureFlow(name) {
    if (!flows[name]) flows[name] = { start: null, nodes: {} };
    if (Array.isArray(flows[name].nodes)) {
      const mapped = {};
      flows[name].nodes.forEach((rawNode, index) => {
        if (!rawNode || typeof rawNode !== "object" || Array.isArray(rawNode)) return;
        const nodeId = String(rawNode.id || rawNode.node_id || `node_${index + 1}`).trim() || `node_${index + 1}`;
        mapped[nodeId] = {
          ...rawNode,
          label: rawNode.label || nodeId,
          plugin_id: rawNode.plugin_id || rawNode.type || "chat",
          agent_kind: rawNode.agent_kind || "agent_workflow_member",
          x: typeof rawNode.x === "number" ? rawNode.x : 80 + (index % 4) * 260,
          y: typeof rawNode.y === "number" ? rawNode.y : 80 + Math.floor(index / 4) * 180,
        };
        delete mapped[nodeId].id;
        delete mapped[nodeId].node_id;
      });
      flows[name].nodes = mapped;
    }
    if (!flows[name].nodes || typeof flows[name].nodes !== "object") flows[name].nodes = {};
    if (typeof flows[name].read_only !== "boolean") flows[name].read_only = false;
    if (!flows[name].settings || typeof flows[name].settings !== "object" || Array.isArray(flows[name].settings)) {
      flows[name].settings = {};
    }
    Object.keys(flows[name].nodes || {}).forEach((nodeId) => {
      const node = flows[name].nodes[nodeId];
      if (node && typeof node === "object" && !Array.isArray(node)) return;
      if (!Object.prototype.hasOwnProperty.call(flows[name].settings, nodeId)) {
        flows[name].settings[nodeId] = node;
      }
      delete flows[name].nodes[nodeId];
    });
    Object.keys(flows[name].nodes || {}).forEach((nodeId) => {
      const node = flows[name].nodes[nodeId];
      if (!node || typeof node !== "object") return;
      if (String(node.plugin_id || "").trim() !== "agent_flow_subflow") return;
      node.plugin_settings = normalizeSubflowPluginSettings(
        node.plugin_settings,
        flows,
        getAgentFlowSettings(ctx, sid) || {}
      );
    });
    return flows[name];
  }

  function updateBackButton() {
    const showBack = flowNavStack.length > 0;
    btnBackFlow.style.display = showBack ? "" : "none";
    backTag.style.display = showBack ? "" : "none";
    const prev = flowNavStack.length ? String(flowNavStack[flowNavStack.length - 1] || "") : "";
    btnBackFlow.title = prev ? `Back to ${prev}` : "Back";
    backTag.title = prev ? `Back to ${prev}` : "Back";
  }

  function goBackFlow() {
    if (!flowNavStack.length) return;
    const prev = String(flowNavStack.pop() || "").trim();
    if (prev && flows[prev]) {
      loadFlow(prev, { resetNav: false });
    } else {
      updateBackButton();
    }
  }

  function loadFlow(name, options = {}) {
    const resetNav = options && options.resetNav !== false;
    if (resetNav) flowNavStack.length = 0;
    if (!name) {
      currentFlow = "";
      activeInput.value = "";
      updateActivePanel();
      renderCanvas();
      updateBackButton();
      return;
    }
    currentFlow = name;
    activeInput.value = name;
    ensureFlow(name);
    refreshFlowList();
    updateActivePanel();
    renderCanvas();
    updateBackButton();
  }

  function jumpToSubflowFromNode(nodeId) {
    const node = getCurrentNodes()[nodeId];
    if (!node) return false;
    if (String(node.plugin_id || "").trim() !== "agent_flow_subflow") return false;
    const subflowName = resolveFlowNameWithStableId(
      getAgentFlowSettings(ctx, sid) || {},
      flows,
      (node.plugin_settings || {}).subflow_name,
      (node.plugin_settings || {}).subflow_workflow_id
    );
    if (!subflowName) {
      ctx.log?.("[agent_flow] subflow node has no resolvable subflow target configured", "warn");
      return true;
    }
    if (!flows[subflowName]) {
      ctx.log?.(`[agent_flow] subflow '${subflowName}' not found`, "warn");
      return true;
    }
    if (currentFlow && currentFlow !== subflowName) {
      flowNavStack.push(currentFlow);
    }
    loadFlow(subflowName, { resetNav: false });
    setLeftOpen(true);
    return true;
  }

  function consumeFlowNavRequest() {
    const req = flowNavRequest;
    if (!req || (!req.flowName && !req.workflowId)) return;
    const reqSid = String(req.sid || "").trim();
    if (reqSid && reqSid !== String(sid || "").trim()) return;
    const target = resolveFlowNameWithStableId(
      getAgentFlowSettings(ctx, sid) || {},
      flows,
      req.flowName,
      req.workflowId
    );
    flowNavRequest = null;
    if (!target || !flows[target]) return;
    loadFlow(target);
    setLeftOpen(true);
  }

  function tempLibraryRequestFromWindow() {
    try {
      const req = window?.[OPEN_TEMP_LIBRARY_PENDING_KEY];
      return req && typeof req === "object" ? req : null;
    } catch {
      return null;
    }
  }

  function clearTempLibraryRequestFromWindow() {
    try {
      delete window[OPEN_TEMP_LIBRARY_PENDING_KEY];
    } catch {
      try {
        window[OPEN_TEMP_LIBRARY_PENDING_KEY] = null;
      } catch {}
    }
  }

  function getBundleManifestSettings(record) {
    const metadata = record && typeof record.metadata === "object" ? record.metadata : null;
    const manifest = metadata && typeof metadata.bundle_manifest === "object" ? metadata.bundle_manifest : null;
    const settings = manifest && typeof manifest.agent_flow_settings === "object" ? manifest.agent_flow_settings : null;
    return settings && Object.keys(settings).length ? settings : null;
  }

  function applyBundleManifestSettings(record, flowNameHint = "") {
    const settings = getBundleManifestSettings(record);
    if (!settings) return false;
    const currentSettings = getAgentFlowSettings(ctx, sid) || {};
    const next = { ...currentSettings };
    let changed = false;
    const setIfPresent = (targetKey, sourceKey, normalize) => {
      if (!Object.prototype.hasOwnProperty.call(settings, sourceKey)) return;
      const raw = settings[sourceKey];
      if (raw == null) return;
      if (typeof raw === "string" && !raw.trim()) return;
      const value = typeof normalize === "function" ? normalize(raw) : raw;
      if (value == null) return;
      if (next[targetKey] === value) return;
      next[targetKey] = value;
      changed = true;
    };
    const flowName = String(flowNameHint || record?.flow_name || "").trim();
    const normalizedDefault = String(settings.default_flow || "").trim();
    const normalizedActive = String(settings.active_flow || "").trim();
    if (normalizedDefault) {
      next.agent_flow_default_flow = normalizedDefault;
      changed = changed || currentSettings.agent_flow_default_flow !== normalizedDefault;
    }
    if (normalizedActive) {
      next.agent_flow_active_flow = normalizedActive;
      changed = changed || currentSettings.agent_flow_active_flow !== normalizedActive;
    } else if (flowName && !String(currentSettings.agent_flow_active_flow || "").trim()) {
      next.agent_flow_active_flow = flowName;
      changed = true;
    }
    setIfPresent("agent_flow_mode", "mode", (v) => String(v || "").trim() || "execute");
    setIfPresent("agent_flow_max_steps", "max_steps", (v) => Number(v || 32));
    setIfPresent("agent_flow_loop_max_passes", "loop_max_passes", (v) => normalizeLoopMaxSetting(v, 16));
    setIfPresent("agent_flow_force_loop_max_passes", "force_loop_max_passes", (v) => normalizeBoolSetting(v, false));
    setIfPresent("agent_flow_request_timeout_s", "request_timeout_s", (v) => normalizeTimeoutSetting(v, 45));
    setIfPresent("agent_flow_autobuild_sandbox_profile", "autobuild_sandbox_profile", (v) => normalizeSandboxProfileSetting(v, "lightweight"));
    setIfPresent("agent_flow_autobuild_lightweight_max_requests", "autobuild_lightweight_max_requests", (v) => Math.max(1, Math.trunc(Number(v) || 1)));
    setIfPresent("agent_flow_autobuild_lightweight_wait_s", "autobuild_lightweight_wait_s", (v) => normalizeTimeoutSetting(v, 120));
    setIfPresent("agent_flow_autobuild_lightweight_final_grace_s", "autobuild_lightweight_final_grace_s", (v) => normalizeTimeoutSetting(v, 10));
    setIfPresent("agent_flow_autobuild_independent_max_requests", "autobuild_independent_max_requests", (v) => Math.max(1, Math.trunc(Number(v) || 3)));
    setIfPresent("agent_flow_autobuild_independent_wait_s", "autobuild_independent_wait_s", (v) => normalizeTimeoutSetting(v, 180));
    setIfPresent("agent_flow_autobuild_independent_final_grace_s", "autobuild_independent_final_grace_s", (v) => normalizeTimeoutSetting(v, 20));
    if (!changed) return false;
    setRouterSettings(ctx, sid, "agent_flow", next);
    return true;
  }

  async function consumeTempLibraryOpenRequest() {
    const req = tempLibraryRequestFromWindow();
    if (!req) return false;
    const reqPid = String(req.pid || "").trim();
    const reqSid = String(req.sid || "").trim();
    if ((reqPid && reqPid !== String(pid || "").trim()) || (reqSid && reqSid !== String(sid || "").trim())) {
      return false;
    }
    let target = String(req.flow_name || "").trim();
    const recordId = String(req.record_id || "").trim();
    const workflowId = String(req.workflow_id || "").trim();
    if (recordId) {
      try {
        const payload = await fetchAwfLibraryRecords();
        const rows = Array.isArray(payload?.records) ? payload.records : [];
        const row = rows.find((item) => String(item?.id || "").trim() === recordId);
        if (row) {
          target = String(row?.flow_name || target || "").trim();
          req.workflow_id = String(row?.workflow_id || row?.id || workflowId || "").trim();
          req._record = row;
        }
      } catch (err) {
        ctx?.log?.(`[agent_flow] temp library lookup failed: ${err?.message || err}`, "warn");
      }
    }
    const resolvedTarget = resolveFlowNameWithStableId(
      getAgentFlowSettings(ctx, sid) || {},
      flows,
      target,
      req.workflow_id || workflowId
    );
    if (resolvedTarget) target = resolvedTarget;
    if (!target) return false;
    if (flows[target]) {
      clearTempLibraryRequestFromWindow();
      applyBundleManifestSettings(req._record, target);
      loadFlow(target);
      setLeftOpen(true);
      return true;
    }
    flowNavRequest = { sid: String(sid || "").trim(), flowName: target, workflowId: String(req.workflow_id || workflowId || "").trim() };
    try {
      await syncFlowsFromServer();
    } catch (err) {
      ctx?.log?.(`[agent_flow] temp library sync failed: ${err?.message || err}`, "warn");
    }
    if (flows[target]) {
      clearTempLibraryRequestFromWindow();
      applyBundleManifestSettings(req._record, target);
      setLeftOpen(true);
      return true;
    }
    return false;
  }

  function nextNodeId(nodes) {
    let i = 1;
    let id = `node${i}`;
    while (nodes[id]) {
      i += 1;
      id = `node${i}`;
    }
    return id;
  }

  function addNodeAt(x, y) {
    if (!currentFlow) {
      setLeftOpen(true);
      ctx.log?.("Create or select a flow first.", "warn");
      return;
    }
    if (currentFlowIsReadOnly()) {
      ctx.log?.("This workflow is read-only.", "warn");
      return;
    }
    const nodes = getCurrentNodes();
    const nodeId = nextNodeId(nodes);
    nodes[nodeId] = {
      label: nodeId,
      plugin_id: pluginInputWrap.input.value.trim() || pluginIds[0] || "chat",
      agent_kind: "",
      system_prompt: "",
      return_only_text: true,
      delay_ms: 0,
      transitions: [],
      x: Math.max(0, Math.round(x)),
      y: Math.max(0, Math.round(y)),
      plugin_settings: {},
    };
    const flow = ensureFlow(currentFlow);
    if (!flow.start) flow.start = nodeId;
    renderCanvas();
    selectNode(nodeId);
    scheduleSave();
  }

  function syncSelectedNodeClasses() {
    nodeElements.forEach((el, id) => {
      el.classList.toggle("selected", selectedNodeIds.has(id));
    });
  }

  function setSelectedNodes(nodeIds, options = {}) {
    const next = new Set((nodeIds || []).filter(Boolean));
    selectedNodeIds = next;
    const requestedPrimary = String(options.primary || "").trim();
    selectedNodeId = requestedPrimary && next.has(requestedPrimary)
      ? requestedPrimary
      : (next.values().next().value || "");
    syncSelectedNodeClasses();
    if (!selectedNodeId) {
      clearProperties();
      return;
    }
    const node = getCurrentNodes()[selectedNodeId];
    if (!node) {
      clearProperties();
      return;
    }
    nodeIdLabel.textContent = `Node ID: ${selectedNodeId}`;
    labelInput.value = node.label || selectedNodeId;
    pluginInputWrap.input.value = node.plugin_id || "";
    agentInput.value = node.agent_kind || "";
    delayInput.value = node.delay_ms ?? 0;
    promptInput.value = node.system_prompt || "";
    returnOnlyInput.checked = node.return_only_text !== false;
    const schema = schemaForPlugin(node.plugin_id || "");
    buildPluginSettingsForm(schema, node.plugin_settings || {});
    renderTransitionEditor(selectedNodeId, node.transitions || []);
    updateReadOnlyUi();
    if (options.openPanel) setRightOpen(true);
  }

  function selectNode(nodeId, options = {}) {
    setSelectedNodes([nodeId], { ...options, primary: nodeId });
  }

  function selectNodesInRect(rect, options = {}) {
    const nodes = getCurrentNodes();
    const picks = Object.keys(nodes).filter((nodeId) => {
      const node = nodes[nodeId];
      if (!node) return false;
      const left = Number(node.x) || 0;
      const top = Number(node.y) || 0;
      const right = left + NODE_W;
      const bottom = top + NODE_H;
      return right >= rect.left && left <= rect.right && bottom >= rect.top && top <= rect.bottom;
    });
    setSelectedNodes(picks, { primary: picks[0] || "", ...options });
  }

  function clearProperties() {
    selectedNodeId = "";
    selectedNodeIds = new Set();
    nodeIdLabel.textContent = "";
    labelInput.value = "";
    pluginInputWrap.input.value = "";
    agentInput.value = "";
    delayInput.value = "0";
    promptInput.value = "";
    returnOnlyInput.checked = true;
    pluginSettingsBox.innerHTML = "";
    pluginSettingsInputs = [];
    transitionsBox.innerHTML = "";
    transitionInputs = [];
    syncSelectedNodeClasses();
    updateReadOnlyUi();
  }

  function getCurrentNodes() {
    if (!currentFlow) return {};
    const flow = ensureFlow(currentFlow);
    return flow.nodes || {};
  }

  function skillCategoryFromId(skillId) {
    const raw = String(skillId || "").trim();
    const dot = raw.indexOf(".");
    return dot > 0 ? raw.slice(0, dot) : "general";
  }

  function labelForSkillCategory(category) {
    return String(category || "general")
      .replace(/[_-]+/g, " ")
      .replace(/\b\w/g, (m) => m.toUpperCase());
  }

  function normalizeSkillArray(value) {
    if (Array.isArray(value)) {
      return value.map((v) => String(v || "").trim()).filter(Boolean);
    }
    return String(value || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  }

  function subflowNodeMode(node) {
    const ps = node && typeof node.plugin_settings === "object" ? node.plugin_settings : {};
    const nodeType = String(ps?.node_type || "").trim().toLowerCase();
    return nodeType === "fan_out_node" ? "fan_out_node" : "subflow_node";
  }

  function subflowBadgeText(node) {
    const subflowName = String((node?.plugin_settings || {}).subflow_name || "").trim();
    const mode = subflowNodeMode(node);
    if (mode === "fan_out_node") {
      const keysRaw = (node?.plugin_settings || {}).iteration_keys;
      const keys = Array.isArray(keysRaw)
        ? keysRaw.map((v) => String(v || "").trim()).filter(Boolean)
        : [String((node?.plugin_settings || {}).iteration_key || "").trim()].filter(Boolean);
      const suffix = keys.length ? ` [${keys.join(", ")}]` : "";
      return `Fan-Out: ${subflowName || "(unset)"}${suffix}`;
    }
    return `Subflow: ${subflowName || "(unset)"}`;
  }

  function getBoundToolSkill(values) {
    if (!values || typeof values !== "object") return "";
    const nodeType = String(values.node_type || "").trim().toLowerCase();
    const toolConfig = values.tool_config && typeof values.tool_config === "object" ? values.tool_config : {};
    const toolId = String(toolConfig.tool || "").trim();
    if (nodeType !== "tool_node" || !toolId) return "";
    return toolId;
  }

  function buildGroupedSkillPicker(field, mergedValues) {
    const opts = Array.isArray(field.options || field.choices) ? field.options || field.choices : [];
    const skills = opts.map((v) => String(v || "").trim()).filter(Boolean);
    const boundToolSkill = getBoundToolSkill(mergedValues);
    const isBoundToolNode = Boolean(boundToolSkill);
    if (boundToolSkill && !skills.includes(boundToolSkill)) skills.push(boundToolSkill);
    const selectedSkills = new Set(normalizeSkillArray(mergedValues.action_skills));
    const selectedCategories = new Set(normalizeSkillArray(mergedValues.action_skill_categories));
    const existingRules = mergedValues && typeof mergedValues.action_skill_rules === "object"
      ? mergedValues.action_skill_rules
      : {};
    if (boundToolSkill) selectedSkills.add(boundToolSkill);

    selectedSkills.forEach((skillId) => {
      if (skillId.endsWith(".*")) {
        selectedCategories.add(skillId.slice(0, -2));
        selectedSkills.delete(skillId);
      }
    });

    const grouped = {};
    skills.forEach((skillId) => {
      const category = skillCategoryFromId(skillId);
      if (!grouped[category]) grouped[category] = [];
      grouped[category].push(skillId);
    });

    const wrap = document.createElement("div");
    wrap.className = "multi-check agent-flow-skill-picker";

    if (isBoundToolNode) {
      const note = document.createElement("div");
      note.className = "muted";
      note.style.marginBottom = "8px";
      note.style.fontSize = "12px";
      note.innerHTML = `This tool node is bound to <code>${boundToolSkill}</code> via <code>tool_config.tool</code>. That skill stays pinned, but you can still select additional skills.`;
      wrap.appendChild(note);
    }

    Object.keys(grouped).sort().forEach((category) => {
      const categorySkills = grouped[category].slice().sort();

      const box = document.createElement("div");
      box.style.border = "1px solid rgba(148, 163, 184, 0.35)";
      box.style.borderRadius = "10px";
      box.style.padding = "8px";
      box.style.marginBottom = "8px";

      const head = document.createElement("div");
      head.style.display = "flex";
      head.style.alignItems = "center";
      head.style.justifyContent = "space-between";
      head.style.gap = "8px";

      const left = document.createElement("span");
      left.style.display = "flex";
      left.style.alignItems = "center";
      left.style.gap = "6px";

      const catCb = document.createElement("input");
      catCb.type = "checkbox";
      catCb.dataset.skillCategory = category;
      catCb.checked = selectedCategories.has(category);

      const catText = document.createElement("strong");
      catText.textContent = labelForSkillCategory(category);

      left.appendChild(catCb);
      left.appendChild(catText);

      const count = document.createElement("span");
      count.className = "muted";
      count.textContent = `0/${categorySkills.length} skills`;

      const collapseBtn = document.createElement("button");
      collapseBtn.type = "button";
      collapseBtn.className = "ghost";
      collapseBtn.style.padding = "0 6px";
      collapseBtn.style.minHeight = "20px";
      collapseBtn.style.lineHeight = "1.2";
      collapseBtn.title = "Expand/collapse category";

      const right = document.createElement("span");
      right.style.display = "inline-flex";
      right.style.alignItems = "center";
      right.style.gap = "6px";
      right.appendChild(count);
      right.appendChild(collapseBtn);

      head.appendChild(left);
      head.appendChild(right);
      box.appendChild(head);

      const skillsBox = document.createElement("div");
      skillsBox.style.marginTop = "8px";
      skillsBox.style.paddingLeft = "18px";
      skillsBox.style.display = "grid";
      skillsBox.style.gap = "4px";
      let isCollapsed = true;
      const syncCollapsedUi = () => {
        skillsBox.style.display = isCollapsed ? "none" : "grid";
        collapseBtn.textContent = isCollapsed ? "▸" : "▾";
      };
      syncCollapsedUi();

      const syncCategoryState = () => {
        const checks = Array.from(skillsBox.querySelectorAll("input[data-skill-id]"));
        const checkedCount = checks.filter((cb) => cb.checked).length;
        const totalCount = checks.length;
        count.textContent = `${checkedCount}/${totalCount} skills`;
        const categoryLocked = selectedCategories.has(category);
        catCb.checked = categoryLocked;
        catCb.indeterminate = !categoryLocked && checkedCount > 0 && checkedCount < totalCount;
        checks.forEach((cb) => {
          cb.disabled = isBoundToolNode && String(cb.dataset.skillId || "").trim() === boundToolSkill;
        });
      };

      categorySkills.forEach((skillId) => {
        const row = document.createElement("div");
        row.dataset.agentFlowSkillRow = "1";
        row.dataset.skillId = skillId;
        row.style.display = "flex";
        row.style.alignItems = "flex-start";
        row.style.gap = "6px";
        row.style.flexDirection = "column";
        row.style.position = "relative";

        const rowTop = document.createElement("div");
        rowTop.style.display = "grid";
        rowTop.style.gridTemplateColumns = "auto minmax(0, 1fr) auto";
        rowTop.style.alignItems = "center";
        rowTop.style.gap = "6px";
        rowTop.style.width = "100%";
        rowTop.style.position = "relative";
        rowTop.style.minWidth = "0";
        rowTop.style.maxWidth = "100%";
        rowTop.style.overflow = "hidden";
        rowTop.style.cursor = isBoundToolNode ? "default" : "pointer";

        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.value = skillId;
        cb.dataset.skillId = skillId;
        cb.dataset.skillCategory = category;
        cb.checked = selectedCategories.has(category) || selectedSkills.has(skillId) || (isBoundToolNode && skillId === boundToolSkill);
        if (isBoundToolNode) {
          cb.disabled = skillId === boundToolSkill;
        }

        const tx = document.createElement("span");
        tx.textContent = skillId;
        tx.title = getAgentFlowSkillHoverText(skillId);
        tx.setAttribute("aria-label", skillId);
        tx.style.flex = "1 1 auto";
        tx.style.minWidth = "0";
        tx.style.maxWidth = "100%";
        tx.style.overflow = "hidden";
        tx.style.textOverflow = "ellipsis";
        tx.style.whiteSpace = "nowrap";
        tx.style.fontSize = "11px";
        tx.style.lineHeight = "1.2";
        tx.style.cursor = isBoundToolNode ? "default" : "pointer";

        const runIfLink = document.createElement("button");
        runIfLink.type = "button";
        runIfLink.className = "ghost";
        runIfLink.dataset.skillRunif = "1";
        runIfLink.textContent = "Req";
        runIfLink.title = "Require-if settings";
        runIfLink.style.marginLeft = "auto";
        runIfLink.style.padding = "0 6px";
        runIfLink.style.lineHeight = "1.2";
        runIfLink.style.fontWeight = "700";
        runIfLink.style.minHeight = "20px";
        runIfLink.style.flex = "0 0 auto";
        runIfLink.style.fontSize = "10px";
        runIfLink.style.whiteSpace = "nowrap";

        const prevRule = existingRules && typeof existingRules[skillId] === "object" ? existingRules[skillId] : {};

        const popover = document.createElement("div");
        popover.className = "agent-flow-runif-popover";
        popover.style.position = "fixed";
        popover.style.zIndex = "2147483200";
        popover.style.minWidth = "280px";
        popover.style.width = "min(360px, calc(100vw - 24px))";
        popover.style.maxWidth = "calc(100vw - 24px)";
        popover.style.padding = "10px";
        popover.style.borderRadius = "10px";
        popover.style.border = "1px solid rgba(148, 163, 184, 0.45)";
        popover.style.background = "var(--panel, #fff)";
        popover.style.boxShadow = "0 12px 34px rgba(0,0,0,0.18)";
        popover.style.display = "none";

        const starLabel = document.createElement("label");
        starLabel.style.display = "flex";
        starLabel.style.alignItems = "center";
        starLabel.style.gap = "6px";
        starLabel.title = "Enforce this skill at least once when run-if matches.";

        const starCb = document.createElement("input");
        starCb.type = "checkbox";
        starCb.dataset.skillRuleSkill = skillId;
        starCb.dataset.skillRuleType = "enforce_once";
        starCb.checked = Boolean(prevRule && prevRule.enforce_once);

        const starText = document.createElement("span");
        starText.textContent = "Run if";
        starText.style.fontSize = "12px";
        starText.style.opacity = "0.9";

        starLabel.appendChild(starCb);
        starLabel.appendChild(starText);
        popover.appendChild(starLabel);

        const guideInput = document.createElement("input");
        guideInput.type = "text";
        guideInput.placeholder = "Optional: when/format prompt for this skill";
        guideInput.dataset.skillRuleSkill = skillId;
        guideInput.dataset.skillRuleType = "guidance";
        guideInput.value = String(prevRule && prevRule.guidance ? prevRule.guidance : "");
        guideInput.style.display = "block";
        guideInput.style.width = "100%";
        guideInput.style.marginTop = "8px";
        guideInput.style.fontSize = "12px";
        popover.appendChild(guideInput);

        const closeAllPopovers = () => {
          Array.from(wrap.querySelectorAll(".agent-flow-runif-popover")).forEach((el) => {
            if (el instanceof HTMLElement) el.style.display = "none";
          });
        };

        const updateRunIfLinkState = () => {
          const enabled = !cb.disabled;
          const active = Boolean(cb.checked && enabled && starCb.checked);
          runIfLink.disabled = false;
          runIfLink.style.opacity = enabled ? "1" : "0.7";
          runIfLink.style.color = active ? "var(--accent, #0f766e)" : "rgba(148, 163, 184, 0.95)";
          runIfLink.textContent = active ? "Req*" : "Req";
        };

        const positionRunIfPopover = () => {
          const rect = runIfLink.getBoundingClientRect();
          popover.style.display = "block";
          const width = popover.offsetWidth || Math.min(360, window.innerWidth - 24);
          const height = popover.offsetHeight || 120;
          const left = Math.min(
            Math.max(12, rect.right - width),
            Math.max(12, window.innerWidth - width - 12)
          );
          const below = rect.bottom + 8;
          const top = below + height <= window.innerHeight
            ? below
            : Math.max(12, rect.top - height - 8);
          popover.style.left = `${left}px`;
          popover.style.top = `${top}px`;
        };

        runIfLink.addEventListener("click", (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          const enabled = !cb.disabled;
          if (!enabled) return;
          if (!cb.checked) {
            cb.checked = true;
            cb.dispatchEvent(new Event("change", { bubbles: true }));
          }
          const openNow = popover.style.display === "block";
          closeAllPopovers();
          if (!openNow) positionRunIfPopover();
        });

        popover.addEventListener("click", (ev) => ev.stopPropagation());
        starCb.addEventListener("change", () => {
          guideInput.disabled = !starCb.checked;
          updateRunIfLinkState();
        });
        guideInput.addEventListener("input", () => updateRunIfLinkState());

        cb.addEventListener("click", (ev) => ev.stopPropagation());
        cb.addEventListener("change", () => {
          syncCategoryState();
          starCb.disabled = cb.disabled;
          guideInput.disabled = cb.disabled || !starCb.checked;
          updateRunIfLinkState();
        });
        rowTop.addEventListener("click", (ev) => {
          const target = ev.target;
          if (target instanceof HTMLInputElement || target instanceof HTMLButtonElement) return;
          if (cb.disabled) return;
          ev.preventDefault();
          cb.checked = !cb.checked;
          cb.dispatchEvent(new Event("change", { bubbles: true }));
        });

        rowTop.appendChild(cb);
        rowTop.appendChild(tx);
        rowTop.appendChild(runIfLink);
        row.appendChild(rowTop);
        row.appendChild(popover);
        skillsBox.appendChild(row);

        starCb.disabled = cb.disabled;
        guideInput.disabled = cb.disabled || !starCb.checked;
        updateRunIfLinkState();
      });

      catCb.addEventListener("change", () => {
        if (catCb.checked) selectedCategories.add(category);
        else selectedCategories.delete(category);
        const checks = Array.from(skillsBox.querySelectorAll("input[data-skill-id]"));
        checks.forEach((cb) => {
          if (cb.disabled) {
            cb.checked = true;
            return;
          }
          cb.checked = catCb.checked;
        });
        syncCategoryState();
      });
      collapseBtn.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        isCollapsed = !isCollapsed;
        syncCollapsedUi();
      });

      box.appendChild(skillsBox);
      wrap.appendChild(box);
      syncCategoryState();
    });

    document.addEventListener("click", () => {
      Array.from(wrap.querySelectorAll(".agent-flow-runif-popover")).forEach((el) => {
        if (el instanceof HTMLElement) el.style.display = "none";
      });
    });

    wrap._agentFlowCollectValue = () => {
      const categories = Array.from(wrap.querySelectorAll("input[data-skill-category]:not([data-skill-id])"))
        .filter((cb) => cb.checked)
        .map((cb) => String(cb.dataset.skillCategory || "").trim())
        .filter(Boolean);

      const categorySet = new Set(categories);

      const selected = Array.from(wrap.querySelectorAll("input[data-skill-id]"))
        .filter((cb) => cb.checked)
        .map((cb) => ({
          skill: String(cb.dataset.skillId || "").trim(),
          category: String(cb.dataset.skillCategory || "").trim(),
        }))
        .filter((item) => item.skill && !categorySet.has(item.category))
        .map((item) => item.skill);
      if (boundToolSkill && !selected.includes(boundToolSkill) && !categorySet.has(skillCategoryFromId(boundToolSkill))) {
        selected.push(boundToolSkill);
      }

      const selectedSet = new Set(selected);
      const rules = {};
      Array.from(wrap.querySelectorAll("input[data-skill-rule-skill][data-skill-rule-type='enforce_once']")).forEach((cb) => {
        const sid = String(cb.dataset.skillRuleSkill || "").trim();
        if (!sid || !selectedSet.has(sid)) return;
        if (!cb.checked) return;
        if (!rules[sid]) rules[sid] = {};
        rules[sid].enforce_once = true;
      });
      Array.from(wrap.querySelectorAll("input[data-skill-rule-skill][data-skill-rule-type='guidance']")).forEach((inp) => {
        const sid = String(inp.dataset.skillRuleSkill || "").trim();
        if (!sid || !selectedSet.has(sid)) return;
        const text = String(inp.value || "").trim();
        if (!text) return;
        if (!rules[sid]) rules[sid] = {};
        rules[sid].guidance = text;
      });

      return {
        action_skill_categories: categories,
        action_skills: selected,
        action_skill_rules: rules,
      };
    };

    // Ensure per-skill controls follow current selection state.
    Array.from(wrap.querySelectorAll("input[data-skill-id]")).forEach((cb) => {
      const sid = String(cb.dataset.skillId || "").trim();
      const star = wrap.querySelector(`input[data-skill-rule-skill="${sid}"][data-skill-rule-type="enforce_once"]`);
      const guide = wrap.querySelector(`input[data-skill-rule-skill="${sid}"][data-skill-rule-type="guidance"]`);
      const row = cb.closest('[data-agent-flow-skill-row="1"]');
      const link = row?.querySelector('button[data-skill-runif="1"]');
      if (!(star instanceof HTMLInputElement) || !(guide instanceof HTMLInputElement)) return;
      const enabled = cb.checked && !cb.disabled;
      star.disabled = !enabled;
      guide.disabled = !enabled || !star.checked;
      if (link instanceof HTMLButtonElement) {
        link.disabled = !enabled;
        link.style.opacity = enabled ? "1" : "0.55";
        link.style.color = star.checked ? "var(--accent, #0f766e)" : "rgba(148, 163, 184, 0.95)";
      }
    });

    return wrap;
  }

  function parseJsonEditorValue(textarea) {
    const text = String(textarea?.value || "").trim();
    if (!text) return {};
    try {
      const parsed = JSON.parse(text);
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
    } catch (err) {
      ctx.log?.(`Tool params JSON parse failed: ${err?.message || err}`, "warn");
      return {};
    }
  }

  const MODEL_NODE_DEFS = {
    asset_resolver: {
      label: "Asset resolver",
      tool: "models.asset_resolver",
      help: "Resolves model-deck assets and validates required file paths before later nodes run.",
      assetKeys: ["gguf_path", "embeddings_connectors_path", "video_vae_path", "audio_vae_path", "text_encoder_gguf_path", "text_encoder_safetensors_path", "text_encoder_projection_path", "text_encoder_mmproj_path", "distilled_lora_path", "spatial_upscaler_path"],
      settingKeys: ["model_id", "model_family", "workflow_variant", "device", "dtype", "workflow_loader_mode", "workflow_execution_backend"],
      paramKeys: ["asset_keys"],
    },
    prompt_encoder: {
      label: "Prompt encoder / text encoder",
      tool: "models.prompt_encoder",
      help: "Loads Gemma/text encoder assets and turns prompt text into conditioning embeddings.",
      assetKeys: ["text_encoder_safetensors_path", "text_encoder_gguf_path", "text_encoder_tokenizer_gguf_path", "text_encoder_projection_path", "text_encoder_mmproj_path", "embeddings_connectors_path"],
      settingKeys: ["gemma_text_encoding_device", "gemma_max_tokens", "allow_eager_gemma_gpu", "device", "dtype", "negative_prompt", "native_default_negative_prompt"],
      paramKeys: ["negative_prompt"],
      paramsFromInput: ["prompt", "negative_prompt"],
    },
    text_encoder_loader: {
      label: "Text encoder loader",
      tool: "models.prompt_encoder",
      help: "Generic text encoder loader/encoder node. Tested adapters can split tokenizer, text encoder, and projection behavior as needed.",
      assetKeys: ["text_encoder_safetensors_path", "text_encoder_gguf_path", "text_encoder_tokenizer_gguf_path", "text_encoder_projection_path", "text_encoder_mmproj_path"],
      settingKeys: ["gemma_text_encoding_device", "gemma_max_tokens", "allow_eager_gemma_gpu", "device", "dtype"],
      paramKeys: [],
      paramsFromInput: ["prompt", "negative_prompt"],
    },
    diffusers_repo_prompt_encoder: {
      label: "Image prompt / request text",
      tool: "models.prompt_encoder",
      help: "Prepares the image generation prompt and negative prompt for generic Diffusers image/repo workflows.",
      assetKeys: [],
      settingKeys: ["prompt", "default_prompt", "negative_prompt", "use_default_when_blank"],
      paramKeys: ["negative_prompt"],
      paramsFromInput: ["prompt", "negative_prompt"],
    },
    diffusers_repo_pipeline_loader: {
      label: "Diffusers pipeline / model loader",
      tool: "models.transformer_loader",
      help: "Loads the Diffusers image pipeline, tested profile, GGUF transformer, SDXL Lightning UNet, or repo pipeline.",
      assetKeys: ["gguf_path", "sdxl_unet_path", "text_encoder_path", "vae_path", "clip_path"],
      settingKeys: ["backend", "model_id", "repo_id", "model_deck_compat_manifest_id", "model_family", "diffusers_pipeline_class", "diffusers_transformer_class", "use_unet", "sdxl_base_model", "sdxl_variant", "sdxl_timestep_spacing", "dtype", "device", "gpu_selection_mode", "main_gpu", "enable_model_cpu_offload", "enable_sequential_cpu_offload", "low_cpu_mem_usage"],
      paramKeys: [],
    },
    diffusers_repo_sampler: {
      label: "Image sampler / generate",
      tool: "models.sampler",
      help: "Runs the loaded image pipeline with prompt, size, steps, CFG/guidance, and seed.",
      assetKeys: [],
      settingKeys: ["width", "height", "steps", "num_inference_steps", "cfg_scale", "guidance_scale", "sampler", "scheduler", "seed", "max_sequence_length"],
      paramKeys: ["width", "height", "steps", "guidance_scale", "seed"],
      paramsFromInput: ["prompt", "negative_prompt", "width", "height", "steps", "guidance_scale", "seed"],
    },
    diffusers_repo_vae_decode: {
      label: "Image VAE / decode pass-through",
      tool: "models.vae_decode",
      help: "For Diffusers image pipelines, VAE decode usually happens inside the sampler. This node records/validates that decoded output is available.",
      assetKeys: ["vae_path"],
      settingKeys: ["dtype", "device"],
      paramKeys: [],
    },
    diffusers_repo_media_encode: {
      label: "Image file output",
      tool: "models.media_encode",
      help: "Publishes the generated image as the workflow result.",
      assetKeys: [],
      settingKeys: ["output_ext"],
      paramKeys: ["output_path"],
      paramsFromInput: ["prompt"],
    },
    diffusers_repo_cleanup: {
      label: "Diffusers cleanup / unload",
      tool: "models.cleanup",
      help: "Releases the image Diffusers pipeline and accelerator cache after generation.",
      assetKeys: [],
      settingKeys: ["release_workflow_object", "cleanup_xpu_cache", "cleanup_cuda_cache", "workflow_node_lifecycle_policy"],
      paramKeys: ["targets"],
    },
    gguf_transformer_loader: {
      label: "GGUF transformer loader",
      tool: "models.transformer_loader",
      help: "Loads the video/image transformer GGUF using the selected memory policy.",
      assetKeys: ["gguf_path", "model_path", "embeddings_connectors_path"],
      settingKeys: ["native_gguf_execution_mode", "native_lazy_quantized_packed_device", "native_transformer_offload", "native_transformer_gpu_slots", "device", "main_gpu", "gpu_selection_mode", "dtype"],
      paramKeys: [],
    },
    dual_transformer_loader: {
      label: "Dual GGUF transformer loader",
      tool: "models.dual_transformer_loader",
      help: "Loads/declares paired transformer stages such as Wan HighNoise and LowNoise GGUF models.",
      assetKeys: ["high_noise_gguf_path", "low_noise_gguf_path", "gguf_path_high", "gguf_path_low"],
      settingKeys: ["native_gguf_execution_mode", "native_lazy_quantized_packed_device", "native_transformer_offload", "device", "main_gpu", "gpu_selection_mode", "dtype", "high_noise_model_role", "low_noise_model_role"],
      paramKeys: ["high_noise_steps", "low_noise_steps", "stage_split"],
    },
    connector_lora_attach: {
      label: "Connector / LoRA attach",
      tool: "models.connector_loader",
      help: "Attaches connector/projection files and optional LoRA weights to the transformer.",
      assetKeys: ["embeddings_connectors_path", "text_encoder_projection_path", "text_encoder_mmproj_path", "distilled_lora_path"],
      settingKeys: ["native_skip_lora", "skip_lora", "native_allow_lora_mismatch_fallback", "native_lora_partial_fuse", "ltx_distilled_lora_strength", "ltx_detailer_lora_strength", "native_require_asset_pairing"],
      paramKeys: [],
    },
    lora_loader: {
      label: "LoRA / adapter loader",
      tool: "models.lora_loader",
      help: "Loads one optional LoRA/adapter asset. Add multiple nodes when a model supports multiple LoRAs.",
      assetKeys: ["distilled_lora_path", "lora_adapter_path"],
      settingKeys: ["native_skip_lora", "skip_lora", "native_allow_lora_mismatch_fallback", "native_lora_partial_fuse", "ltx_distilled_lora_strength", "ltx_detailer_lora_strength"],
      paramKeys: ["lora_name", "strength", "apply_stage"],
    },
    vae_loader: {
      label: "VAE loader",
      tool: "models.vae_decode",
      help: "Loads/declares VAE assets. Some adapters combine VAE loading with decode; others can preload the VAE here.",
      assetKeys: ["video_vae_path", "audio_vae_path", "vae_path"],
      settingKeys: ["device", "dtype", "vae_dtype", "enable_model_cpu_offload", "enable_sequential_cpu_offload"],
      paramKeys: ["vae_role"],
    },
    ltx_graph_settings: {
      label: "LTX graph settings / crop guides",
      tool: "models.graph_settings",
      help: "Comfy-parity settings such as crop guides, chunking, samplers, sigmas, CFG, and stage controls.",
      assetKeys: ["spatial_upscaler_path"],
      settingKeys: ["width", "height", "frames", "fps", "steps", "guidance_scale", "ltx_crop_guides_enabled", "ltx_stage1_sampler", "ltx_stage1_sigmas", "ltx_stage1_cfg", "ltx_stage2_sampler", "ltx_stage2_sigmas", "ltx_stage2_cfg", "ltx_chunk_feedforward_chunks", "ltx_chunk_feedforward_dim_threshold", "native_force_stage2", "native_debug_skip_stage2", "native_normalize_stage1_latent", "native_stage1_latent_target_std"],
      paramKeys: [],
    },
    latent_video_init: {
      label: "Latent video initializer",
      tool: "models.latent_video_init",
      help: "Creates the initial empty latent video tensor for T2V workflows. Wan uses Hunyuan-shaped latent video initialization.",
      assetKeys: [],
      settingKeys: ["width", "height", "frames", "batch_size", "latent_format", "device", "dtype"],
      paramKeys: ["width", "height", "frames", "batch_size", "latent_format"],
      paramsFromInput: ["width", "height", "frames"],
    },
    staged_sampler: {
      label: "Staged sampler",
      tool: "models.staged_sampler",
      help: "Runs multi-stage sampling where one model handles early/noisy steps and another handles later/low-noise steps.",
      assetKeys: ["high_noise_gguf_path", "low_noise_gguf_path", "lora_adapter_path"],
      settingKeys: ["steps", "high_noise_steps", "low_noise_steps", "guidance_scale", "high_noise_cfg", "low_noise_cfg", "sampler_name", "scheduler", "seed", "device", "dtype", "workflow_node_lifecycle_policy"],
      paramKeys: ["steps", "high_noise_steps", "low_noise_steps", "guidance_scale", "high_noise_cfg", "low_noise_cfg", "sampler_name", "scheduler", "seed"],
      paramsFromInput: ["steps", "guidance_scale", "seed"],
    },
    sampler: {
      label: "Video latent sampler",
      tool: "models.sampler",
      help: "Runs denoising/sampling and produces video latents.",
      assetKeys: ["gguf_path", "embeddings_connectors_path", "distilled_lora_path", "spatial_upscaler_path"],
      settingKeys: ["width", "height", "frames", "fps", "steps", "guidance_scale", "seed", "ltx_video_only", "native_force_stage2", "native_skip_lora", "ltx_stage1_cfg", "ltx_stage2_cfg", "device", "dtype"],
      paramKeys: ["width", "height", "frames", "fps", "steps", "guidance_scale", "seed"],
      paramsFromInput: ["width", "height", "frames", "fps", "steps", "guidance_scale", "seed"],
    },
    vae_decode: {
      label: "Video VAE decode",
      tool: "models.vae_decode",
      help: "Loads the selected VAE assets and decodes latents into frames.",
      assetKeys: ["video_vae_path", "audio_vae_path"],
      settingKeys: ["device", "dtype", "vae_dtype"],
      paramKeys: [],
    },
    video_encode: {
      label: "MP4/video encoder",
      tool: "models.media_encode",
      help: "Encodes decoded frames to an MP4 artifact.",
      assetKeys: [],
      settingKeys: ["fps", "video_codec"],
      paramKeys: ["fps", "codec"],
      paramsFromInput: ["fps", "prompt"],
    },
    frame_interpolator: {
      label: "Frame interpolation",
      tool: "models.frame_interpolator",
      help: "Optional post-process node such as RIFE frame interpolation before final MP4 encode.",
      assetKeys: ["frame_interpolator_model_path", "rife_model_path"],
      settingKeys: ["fps", "target_fps", "interpolation_multiplier", "frame_interpolator_dtype", "device"],
      paramKeys: ["target_fps", "interpolation_multiplier"],
    },
    wan_optional_prompt: {
      label: "Wan optional prompt",
      tool: "models.wan22_optional_prompt",
      help: "Consumes/normalizes the user's optional I2V/T2V prompt before prompt encoding.",
      assetKeys: [],
      settingKeys: ["prompt", "negative_prompt"],
      paramKeys: ["prompt", "negative_prompt"],
      paramsFromInput: ["prompt", "negative_prompt"],
    },
    wan_prompt_encoder: {
      label: "Wan prompt encoder / UMT5",
      tool: "models.wan22_prompt_encoder",
      help: "Loads the Wan UMT5 text encoder GGUF and encodes prompt conditioning.",
      assetKeys: ["text_encoder_gguf_path"],
      settingKeys: ["wan_prompt_encoder_cache_mode", "wan_prompt_encoder_persist", "device", "dtype", "negative_prompt"],
      paramKeys: ["negative_prompt"],
      paramsFromInput: ["prompt", "negative_prompt"],
    },
    wan_source_prepare: {
      label: "Wan I2V source image prepare",
      tool: "models.wan22_i2v_source_prepare",
      help: "Fits/crops the source image to the model workflow size before VAE source encoding.",
      assetKeys: ["source_image_path"],
      settingKeys: ["width", "height", "wan_i2v_prepare_source_to_output_size", "wan_i2v_source_fit_mode"],
      paramKeys: ["source_image_path"],
    },
    wan_source_vae_encode: {
      label: "Wan I2V source VAE encode",
      tool: "models.wan22_i2v_source_vae_encode",
      help: "Encodes the prepared source image into Wan I2V latent conditioning, including CPU/GPU and temporal-halo source encode controls.",
      assetKeys: ["video_vae_path", "source_image_path"],
      settingKeys: ["wan_i2v_vae_encode_device", "wan_i2v_vae_encode_dtype", "wan_i2v_source_encode_mode", "wan_i2v_source_halo_core_latent_frames", "wan_i2v_source_halo_latent_frames", "wan_i2v_source_halo_max_window_latent_frames", "wan_i2v_source_encode_cleanup_each_stage", "wan_i2v_min_gpu_free_mb", "device", "dtype"],
      paramKeys: ["node_id"],
    },
    wan_i2v_conditioning: {
      label: "Wan I2V conditioning inject",
      tool: "models.wan22_i2v_conditioning_inject",
      help: "Injects source-image latent conditioning into the prompt conditioning before sampling.",
      assetKeys: [],
      settingKeys: ["wan_i2v_denoise_strength", "wan_i2v_source_hold_frames", "wan_i2v_source_tail_mode", "wan_i2v_source_tail_min_strength"],
      paramKeys: ["node_id"],
    },
    wan_stage_transformer_loader: {
      label: "Wan stage GGUF transformer loader",
      tool: "models.wan22_stage_transformer_loader",
      help: "Loads one Wan HighNoise or LowNoise GGUF transformer stage so split workflows do not keep both resident.",
      assetKeys: ["high_noise_gguf_path", "low_noise_gguf_path"],
      settingKeys: ["stage", "device", "dtype", "native_gguf_execution_mode", "native_lazy_quantized_packed_device", "workflow_node_lifecycle_policy"],
      paramKeys: ["stage", "node_id"],
    },
    wan_dual_transformer_loader: {
      label: "Wan dual GGUF transformer loader",
      tool: "models.wan22_dual_transformer_loader",
      help: "Loads/declares both Wan HighNoise and LowNoise transformer stages for non-split workflows.",
      assetKeys: ["high_noise_gguf_path", "low_noise_gguf_path"],
      settingKeys: ["device", "dtype", "native_gguf_execution_mode", "native_lazy_quantized_packed_device"],
      paramKeys: ["high_noise_steps", "low_noise_steps"],
    },
    wan_lora_attach: {
      label: "Wan LoRA attach",
      tool: "models.wan22_lora_attach",
      help: "Attaches the Wan high/low LoRA adapters with per-stage strengths.",
      assetKeys: ["high_noise_lora_path", "low_noise_lora_path"],
      settingKeys: ["wan_apply_stage_lora", "wan_stage_lora_stock_loader", "wan_stage_lora_strength", "high_noise_lora_strength", "low_noise_lora_strength", "wan_stage_lora_mismatch_fallback"],
      paramKeys: ["stage"],
    },
    wan_latent_video_init: {
      label: "Wan latent video init",
      tool: "models.wan22_latent_video_init",
      help: "Creates the empty Hunyuan/Wan latent video tensor for T2V or the base latent for I2V.",
      assetKeys: [],
      settingKeys: ["width", "height", "frames", "batch_size", "latent_format", "device", "dtype"],
      paramKeys: ["width", "height", "frames", "batch_size", "latent_format"],
      paramsFromInput: ["width", "height", "frames"],
    },
    wan_i2v_latent_init: {
      label: "Wan I2V latent init",
      tool: "models.wan22_i2v_latent_init",
      help: "Creates/merges the Wan I2V latent payload from source conditioning and empty video latents.",
      assetKeys: [],
      settingKeys: ["width", "height", "frames", "batch_size", "latent_format", "wan_i2v_denoise_strength", "device", "dtype"],
      paramKeys: ["width", "height", "frames", "batch_size", "latent_format"],
      paramsFromInput: ["width", "height", "frames"],
    },
    wan_stage_sampler: {
      label: "Wan stage sampler",
      tool: "models.wan22_stage_sampler",
      help: "Runs a single Wan high-noise or low-noise sampling stage.",
      assetKeys: ["high_noise_gguf_path", "low_noise_gguf_path", "high_noise_lora_path", "low_noise_lora_path"],
      settingKeys: ["stage", "steps", "high_noise_steps", "low_noise_steps", "guidance_scale", "high_noise_cfg", "low_noise_cfg", "sampler_name", "scheduler", "seed", "shift", "high_noise_shift", "low_noise_shift", "device", "dtype"],
      paramKeys: ["stage", "steps", "seed"],
      paramsFromInput: ["steps", "guidance_scale", "seed"],
    },
    wan_staged_sampler: {
      label: "Wan staged sampler",
      tool: "models.wan22_staged_sampler",
      help: "Runs the combined Comfy-style Wan high-noise then low-noise sampling path.",
      assetKeys: ["high_noise_gguf_path", "low_noise_gguf_path", "high_noise_lora_path", "low_noise_lora_path"],
      settingKeys: ["steps", "high_noise_steps", "low_noise_steps", "guidance_scale", "high_noise_cfg", "low_noise_cfg", "sampler_name", "scheduler", "seed", "shift", "high_noise_shift", "low_noise_shift", "device", "dtype"],
      paramKeys: ["steps", "seed"],
      paramsFromInput: ["steps", "guidance_scale", "seed"],
    },
    wan_release_transformer: {
      label: "Wan release transformer",
      tool: "models.wan22_release_transformer",
      help: "Releases one Wan transformer stage and clears cache before the next heavy stage.",
      assetKeys: [],
      settingKeys: ["stage", "cleanup_xpu_cache", "cleanup_cuda_cache"],
      paramKeys: ["stage", "targets"],
    },
    wan_vae_decode: {
      label: "Wan video VAE decode",
      tool: "models.wan22_vae_decode",
      help: "Decodes Wan video latents to frames, including CPU/GPU full decode, temporal halo chunking, and spatial tiling controls.",
      assetKeys: ["video_vae_path"],
      settingKeys: ["wan_vae_decode_device", "wan_vae_decode_mode", "wan_vae_dtype", "wan_vae_halo_core_latent_frames", "wan_vae_halo_core_overlap_latent_frames", "wan_vae_halo_latent_frames", "wan_vae_halo_max_window_latent_frames", "wan_vae_halo_spatial_tiled", "wan_vae_halo_tile_size", "wan_vae_halo_tile_overlap", "wan_vae_halo_cpu_fallback", "wan_luminance_stabilize", "wan_luminance_strength", "device", "dtype"],
      paramKeys: ["node_id"],
    },
    wan_frame_interpolator: {
      label: "Wan frame interpolation",
      tool: "models.wan22_frame_interpolator",
      help: "Optional Wan frame interpolation/pass-through stage.",
      assetKeys: ["frame_interpolator_model_path", "rife_model_path"],
      settingKeys: ["fps", "target_fps", "interpolation_multiplier", "frame_interpolator_dtype", "device"],
      paramKeys: ["target_fps", "interpolation_multiplier"],
    },
    wan_media_encode: {
      label: "Wan MP4/video encode",
      tool: "models.wan22_media_encode",
      help: "Encodes decoded Wan frames to MP4 and can apply post-VAE temporal denoise.",
      assetKeys: [],
      settingKeys: ["fps", "target_fps", "video_codec", "wan_video_temporal_denoise", "wan_video_temporal_denoise_strength", "wan_video_temporal_denoise_radius", "wan_video_temporal_denoise_motion_gate"],
      paramKeys: ["fps", "codec"],
      paramsFromInput: ["fps", "prompt"],
    },

    minimax_ref_inputs: {
      label: "MiniMax H3 reference inputs",
      tool: "models.minimax_ref_inputs",
      help: "Declares REF2V reference image/video/audio inputs and the tag mapping used by MiniMaxH3ReferenceToVideo.",
      assetKeys: ["reference_image_1_path", "reference_image_2_path", "reference_video_path", "reference_audio_path"],
      settingKeys: ["minimax_conditioning_mode", "minimax_ref_image_size", "minimax_reference_conditioning_device", "minimax_reference_tags", "minimax_resize_references", "minimax_ref1_width", "minimax_ref1_height", "minimax_ref2_width", "minimax_ref2_height", "width", "height", "frames", "fps"],
      paramKeys: ["ref_image_size", "reference_tags"],
      paramsFromInput: ["prompt", "source_image_path"],
    },
    minimax_text_encoder: {
      label: "MiniMax H3 Qwen text encoder",
      tool: "models.minimax_text_encoder",
      help: "Loads/declares the Qwen3-VL text encoder GGUF/safetensors and prepares MiniMax prompt conditioning.",
      assetKeys: ["text_encoder_gguf_path", "text_encoder_safetensors_path"],
      settingKeys: ["minimax_text_encoder_device", "minimax_text_encoder_cache_mode", "max_sequence_length", "device", "dtype", "negative_prompt"],
      paramKeys: ["negative_prompt"],
      paramsFromInput: ["prompt", "negative_prompt"],
    },
    minimax_ref2va_transformer_loader: {
      label: "MiniMax H3 REF2VA transformer loader",
      tool: "models.minimax_ref2va_transformer_loader",
      help: "Loads/declares the active REF2VA transformer GGUF or safetensors model.",
      assetKeys: ["gguf_path", "ref2va_gguf_path", "fl2va_gguf_path", "ref2va_safetensors_path"],
      settingKeys: ["minimax_model_role", "minimax_conditioning_mode", "minimax_unet_loader", "minimax_gguf_dequant_dtype", "minimax_gguf_patch_dtype", "minimax_gguf_patch_on_device", "native_gguf_execution_mode", "native_lazy_quantized_packed_device", "native_transformer_offload", "device", "main_gpu", "gpu_selection_mode", "dtype"],
      paramKeys: [],
    },
    minimax_ref2v_conditioning: {
      label: "MiniMax H3 REF2V conditioning",
      tool: "models.minimax_ref2v_conditioning",
      help: "Represents the MiniMaxH3ReferenceToVideo conditioning node: prompt plus tagged references into video/audio latent conditioning.",
      assetKeys: ["ref_image_1_path", "ref_image_2_path", "ref_video_1_path", "ref_audio_1_path"],
      settingKeys: ["width", "height", "frames", "fps", "duration_seconds", "minimax_ref_image_size", "minimax_reference_conditioning_device", "minimax_reference_tags"],
      paramKeys: ["ref_image_size", "reference_tags"],
      paramsFromInput: ["prompt", "width", "height", "frames"],
    },
    minimax_sampler: {
      label: "MiniMax H3 sampler",
      tool: "models.minimax_sampler",
      help: "MiniMax H3 sampling settings matching the Comfy SamplerCustomAdvanced path.",
      assetKeys: ["gguf_path", "text_encoder_gguf_path"],
      settingKeys: ["steps", "guidance_scale", "sampler_name", "scheduler", "seed", "minimax_shift_video", "minimax_shift_audio", "minimax_noise_seed_mode", "device", "dtype"],
      paramKeys: ["steps", "guidance_scale", "sampler_name", "scheduler", "seed"],
      paramsFromInput: ["steps", "guidance_scale", "seed"],
    },
    minimax_video_vae_decode: {
      label: "MiniMax H3 video VAE decode",
      tool: "models.minimax_video_vae_decode",
      help: "Decodes the video half of MiniMax H3 packed latent using the video VAE. Low-resource workflows can expose GPU chunking and temporal-halo settings here.",
      assetKeys: ["video_vae_path"],
      settingKeys: ["minimax_video_vae_decode_mode", "minimax_video_vae_device", "minimax_vae_chunk_latent_frames", "minimax_vae_chunk_overlap_latent_frames", "minimax_vae_chunk_blend_frames", "minimax_vae_halo_core_latent_frames", "minimax_vae_halo_latent_frames", "minimax_vae_halo_max_window_latent_frames", "minimax_vae_tile_size", "minimax_vae_tile_overlap", "vae_dtype", "enable_model_cpu_offload", "enable_sequential_cpu_offload", "device", "dtype"],
      paramKeys: ["vae_role"],
    },
    minimax_audio_vae_decode: {
      label: "MiniMax H3 audio VAE decode",
      tool: "models.minimax_audio_vae_decode",
      help: "Decodes the audio half of MiniMax H3 packed latent using the audio VAE.",
      assetKeys: ["audio_vae_path"],
      settingKeys: ["minimax_enable_audio", "minimax_audio_vae_device", "audio_sample_rate", "vae_dtype", "device", "dtype"],
      paramKeys: ["vae_role"],
    },
    minimax_rtx_upscale: {
      label: "MiniMax H3 RTX video upscale",
      tool: "models.minimax_rtx_upscale",
      help: "Optional RTX video super-resolution/upscale stage from the Comfy workflow.",
      assetKeys: [],
      settingKeys: ["minimax_rtx_upscale_enabled", "minimax_rtx_upscale_mode", "minimax_rtx_upscale_multiplier", "minimax_rtx_upscale_quality"],
      paramKeys: ["enabled", "scale", "quality"],
    },
    minimax_media_encode: {
      label: "MiniMax H3 mux / MP4 output",
      tool: "models.minimax_media_encode",
      help: "Muxes decoded MiniMax video and audio into the final MP4.",
      assetKeys: [],
      settingKeys: ["fps", "target_fps", "video_codec", "audio_codec", "minimax_enable_audio", "output_ext"],
      paramKeys: ["fps", "codec"],
      paramsFromInput: ["fps", "prompt"],
    },
    hunyuan15_assets: {
      label: "HunyuanVideo 1.5 assets",
      tool: "models.hunyuan15_assets",
      help: "Declares HunyuanVideo 1.5 GGUF, VAE, dual text encoders, optional LoRA/upscale, and source image assets.",
      assetKeys: ["hunyuan_gguf_path", "gguf_path", "video_vae_path", "text_encoder_1_path", "text_encoder_2_path", "source_image_path", "hunyuan_fast_lora_path", "hunyuan_leapfusion_lora_path", "upscale_model_path"],
      settingKeys: ["workflow_variant", "hunyuan_conditioning_mode", "width", "height", "frames", "fps"],
      paramKeys: ["node_id"],
      paramsFromInput: ["prompt", "source_image_path"],
    },
    hunyuan15_text_encoder: {
      label: "Hunyuan dual text encoder",
      tool: "models.hunyuan15_text_encoder",
      help: "Loads the Hunyuan dual text encoders through Comfy DualCLIPLoader.",
      assetKeys: ["text_encoder_1_path", "text_encoder_2_path", "clip_l_path", "llava_text_encoder_path", "qwen_text_encoder_path", "byt5_text_encoder_path"],
      settingKeys: ["hunyuan_text_encoder_device", "hunyuan_text_encoder_cache_mode", "clip_type", "hunyuan_clip_type", "negative_prompt", "device", "dtype"],
      paramKeys: ["node_id"],
      paramsFromInput: ["prompt", "negative_prompt"],
    },
    hunyuan15_transformer_loader: {
      label: "Hunyuan GGUF transformer loader",
      tool: "models.hunyuan15_transformer_loader",
      help: "Loads/declares the HunyuanVideo 1.5 T2V or I2V GGUF transformer.",
      assetKeys: ["hunyuan_gguf_path", "gguf_path"],
      settingKeys: ["hunyuan_unet_loader", "hunyuan_gguf_dequant_dtype", "hunyuan_gguf_patch_dtype", "hunyuan_gguf_patch_on_device", "native_gguf_execution_mode", "native_lazy_quantized_packed_device", "native_transformer_offload", "device", "main_gpu", "gpu_selection_mode", "dtype"],
      paramKeys: ["node_id"],
    },
    hunyuan15_conditioning: {
      label: "Hunyuan T2V/I2V conditioning",
      tool: "models.hunyuan15_conditioning",
      help: "Creates HunyuanVideo 1.5 empty T2V latent or I2V source-image conditioning.",
      assetKeys: ["source_image_path", "reference_image_path", "image_path", "video_vae_path"],
      settingKeys: ["hunyuan_conditioning_mode", "width", "height", "frames", "batch_size", "hunyuan_i2v_source_fit_mode", "hunyuan_i2v_source_encode_device", "device", "dtype"],
      paramKeys: ["node_id"],
      paramsFromInput: ["prompt", "source_image_path", "width", "height", "frames"],
    },
    hunyuan15_sampler: {
      label: "Hunyuan sampler",
      tool: "models.hunyuan15_sampler",
      help: "Runs HunyuanVideo 1.5 sampling settings matching the Comfy sampler path.",
      assetKeys: ["hunyuan_gguf_path", "hunyuan_fast_lora_path", "hunyuan_leapfusion_lora_path"],
      settingKeys: ["steps", "guidance_scale", "sampler_name", "scheduler", "shift", "denoise", "seed", "hunyuan_apply_model_sampling_sd3", "device", "dtype"],
      paramKeys: ["steps", "guidance_scale", "sampler_name", "scheduler", "seed"],
      paramsFromInput: ["steps", "guidance_scale", "seed"],
    },
    hunyuan15_latent_upscale: {
      label: "Hunyuan latent upscaler",
      tool: "models.hunyuan15_latent_upscale",
      help: "Optionally applies the official HunyuanVideo 1.5 latent upscaler before VAE decode.",
      assetKeys: ["upscale_model_path", "latent_upscale_model_path"],
      settingKeys: ["hunyuan_upscale_enabled", "hunyuan_upscale_width", "hunyuan_upscale_height", "hunyuan_upscale_method", "hunyuan_upscale_crop", "device", "dtype"],
      paramKeys: ["node_id"],
    },
    hunyuan15_vae_decode: {
      label: "Hunyuan video VAE decode",
      tool: "models.hunyuan15_vae_decode",
      help: "Decodes Hunyuan latents with full/tiled/temporal VAE controls.",
      assetKeys: ["video_vae_path", "hunyuan_video_vae_path"],
      settingKeys: ["hunyuan_vae_decode_mode", "hunyuan_video_vae_device", "hunyuan_vae_tile_size", "hunyuan_vae_tile_overlap", "hunyuan_vae_temporal_size", "hunyuan_vae_temporal_overlap", "vae_dtype", "enable_model_cpu_offload", "enable_sequential_cpu_offload", "device", "dtype"],
      paramKeys: ["node_id"],
    },
    hunyuan15_media_encode: {
      label: "Hunyuan MP4/video encode",
      tool: "models.hunyuan15_media_encode",
      help: "Executes the native Hunyuan graph and writes the final MP4.",
      assetKeys: [],
      settingKeys: ["fps", "target_fps", "video_codec", "output_ext"],
      paramKeys: ["fps", "codec"],
      paramsFromInput: ["fps", "prompt"],
    },
    hunyuan15_cleanup: {
      label: "Hunyuan cleanup / unload",
      tool: "models.hunyuan15_cleanup",
      help: "Releases Hunyuan workflow handles, tensors, and accelerator caches.",
      assetKeys: [],
      settingKeys: ["release_workflow_object", "cleanup_xpu_cache", "cleanup_cuda_cache", "workflow_node_lifecycle_policy"],
      paramKeys: ["targets"],
    },
    cleanup: {
      label: "Cleanup / unload resources",
      tool: "models.cleanup",
      help: "Releases workflow handles, tensors, and cached model resources.",
      assetKeys: [],
      settingKeys: ["release_workflow_object", "cleanup_xpu_cache", "cleanup_cuda_cache", "workflow_node_lifecycle_policy"],
      paramKeys: ["targets"],
    },
  };

  const MODEL_TOOL_TO_NODE_TYPE = Object.fromEntries(
    Object.entries(MODEL_NODE_DEFS).map(([key, def]) => [def.tool, key])
  );
  Object.assign(MODEL_TOOL_TO_NODE_TYPE, {
    "models.ltx_prompt_encoder": "prompt_encoder",
    "models.gguf_transformer_loader": "gguf_transformer_loader",
    "models.ltx_asset_attach": "connector_lora_attach",
    "models.ltx_graph_settings": "ltx_graph_settings",
    "models.ltx_sampler": "sampler",
    "models.video_vae_decode": "vae_decode",
    "models.video_encode": "video_encode",
    "models.diffusers_repo_prompt_encoder": "diffusers_repo_prompt_encoder",
    "models.diffusers_repo_pipeline_loader": "diffusers_repo_pipeline_loader",
    "models.diffusers_repo_sampler": "diffusers_repo_sampler",
    "models.diffusers_repo_vae_decode": "diffusers_repo_vae_decode",
    "models.diffusers_repo_media_encode": "diffusers_repo_media_encode",
    "models.diffusers_repo_cleanup": "diffusers_repo_cleanup",
    "models.wan22_optional_prompt": "wan_optional_prompt",
    "models.wan22_prompt_encoder": "wan_prompt_encoder",
    "models.wan22_i2v_source_prepare": "wan_source_prepare",
    "models.wan22_i2v_source_vae_encode": "wan_source_vae_encode",
    "models.wan22_i2v_conditioning_inject": "wan_i2v_conditioning",
    "models.wan22_stage_transformer_loader": "wan_stage_transformer_loader",
    "models.wan22_dual_transformer_loader": "wan_dual_transformer_loader",
    "models.wan22_lora_attach": "wan_lora_attach",
    "models.wan22_latent_video_init": "wan_latent_video_init",
    "models.wan22_i2v_latent_init": "wan_i2v_latent_init",
    "models.wan22_stage_sampler": "wan_stage_sampler",
    "models.wan22_staged_sampler": "wan_staged_sampler",
    "models.wan22_release_transformer": "wan_release_transformer",
    "models.wan22_vae_decode": "wan_vae_decode",
    "models.wan22_frame_interpolator": "wan_frame_interpolator",
    "models.wan22_media_encode": "wan_media_encode",
    "models.minimax_ref_inputs": "minimax_ref_inputs",
    "models.minimax_text_encoder": "minimax_text_encoder",
    "models.minimax_ref2va_transformer_loader": "minimax_ref2va_transformer_loader",
    "models.minimax_ref2v_conditioning": "minimax_ref2v_conditioning",
    "models.minimax_sampler": "minimax_sampler",
    "models.minimax_video_vae_decode": "minimax_video_vae_decode",
    "models.minimax_audio_vae_decode": "minimax_audio_vae_decode",
    "models.minimax_rtx_upscale": "minimax_rtx_upscale",
    "models.minimax_media_encode": "minimax_media_encode",
    "models.hunyuan15_assets": "hunyuan15_assets",
    "models.hunyuan15_text_encoder": "hunyuan15_text_encoder",
    "models.hunyuan15_transformer_loader": "hunyuan15_transformer_loader",
    "models.hunyuan15_conditioning": "hunyuan15_conditioning",
    "models.hunyuan15_sampler": "hunyuan15_sampler",
    "models.hunyuan15_latent_upscale": "hunyuan15_latent_upscale",
    "models.hunyuan15_vae_decode": "hunyuan15_vae_decode",
    "models.hunyuan15_media_encode": "hunyuan15_media_encode",
    "models.hunyuan15_cleanup": "hunyuan15_cleanup",
  });

  function isModelToolNodeValues(values) {
    const tool = String(values?.tool_config?.tool || "").trim();
    return String(values?.node_type || "").trim().toLowerCase() === "tool_node" && tool.startsWith("models.");
  }

  function inferModelNodeType(values) {
    const toolConfig = values?.tool_config && typeof values.tool_config === "object" ? values.tool_config : {};
    const params = toolConfig.params && typeof toolConfig.params === "object" ? toolConfig.params : {};
    const tool = String(toolConfig.tool || "").trim();
    const toolMapped = MODEL_TOOL_TO_NODE_TYPE[tool] || "";
    // Prefer exact tool mappings for model-family nodes. Older saved graphs can
    // carry a stale generic model_node_type (for example "vae_decode") even
    // though the bound tool is Wan-specific ("models.wan22_vae_decode").
    if (toolMapped && /^(models\.(wan22|minimax|hunyuan15)_)/i.test(tool)) return toolMapped;
    const explicit = String(
      values?.model_node_type ||
      values?.model_asset_type ||
      toolConfig.model_node_type ||
      toolConfig.model_asset_type ||
      params.model_node_type ||
      params.model_asset_type ||
      ""
    ).trim();
    if (explicit && MODEL_NODE_DEFS[explicit]) return explicit;
    return toolMapped || (tool.startsWith("models.") ? "asset_resolver" : "");
  }

  function modelNodeValueType(key, value) {
    if (typeof value === "boolean") return "bool";
    if (typeof value === "number") return Number.isInteger(value) ? "int" : "float";
    if (["width", "height", "frames", "fps", "steps", "num_inference_steps", "main_gpu", "seed", "native_transformer_gpu_slots", "gemma_max_tokens", "ltx_chunk_feedforward_chunks", "ltx_chunk_feedforward_dim_threshold", "max_sequence_length", "duration_seconds", "audio_sample_rate", "minimax_rtx_upscale_multiplier", "minimax_ref1_width", "minimax_ref1_height", "minimax_ref2_width", "minimax_ref2_height", "minimax_vae_chunk_latent_frames", "minimax_vae_chunk_overlap_latent_frames", "minimax_vae_chunk_blend_frames", "minimax_vae_halo_core_latent_frames", "minimax_vae_halo_latent_frames", "minimax_vae_halo_max_window_latent_frames", "minimax_vae_tile_size", "minimax_vae_tile_overlap", "hunyuan_vae_tile_size", "hunyuan_vae_tile_overlap", "hunyuan_vae_temporal_size", "hunyuan_vae_temporal_overlap", "hunyuan_upscale_width", "hunyuan_upscale_height"].includes(key)) return "int";
    if (["guidance_scale", "cfg_scale", "denoise", "shift", "ltx_stage1_cfg", "ltx_stage2_cfg", "ltx_distilled_lora_strength", "ltx_detailer_lora_strength", "native_stage1_latent_target_std", "minimax_shift_video", "minimax_shift_audio"].includes(key)) return "float";
    if (["native_skip_lora", "skip_lora", "native_allow_lora_mismatch_fallback", "native_lora_partial_fuse", "native_force_stage2", "native_debug_skip_stage2", "native_normalize_stage1_latent", "native_require_asset_pairing", "allow_eager_gemma_gpu", "ltx_crop_guides_enabled", "enable_model_cpu_offload", "enable_sequential_cpu_offload", "ltx_video_only", "release_workflow_object", "cleanup_xpu_cache", "cleanup_cuda_cache", "use_unet", "low_cpu_mem_usage", "use_default_when_blank", "minimax_rtx_upscale_enabled", "minimax_enable_audio", "minimax_gguf_patch_on_device", "minimax_resize_references", "hunyuan_gguf_patch_on_device", "hunyuan_apply_model_sampling_sd3", "hunyuan_upscale_enabled"].includes(key)) return "bool";
    if (["gemma_text_encoding_device"].includes(key)) return "select:cpu,gpu,main,cpu_after_encode";
    if (["workflow_node_lifecycle_policy", "lifecycle"].includes(key)) return "select:lazy_unload,lazy_persist,preload_persist,persist,terminal";
    if (["wan_i2v_source_encode_mode"].includes(key)) return "select:source_motion_burst,source_latent_hold,comfy_temporal_halo,comfy_exact,masked_start_only";
    if (["wan_i2v_source_tail_mode"].includes(key)) return "select:blend_source_to_neutral,neutral";
    if (["wan_i2v_resource_guard_action"].includes(key)) return "select:fallback_cpu,fail,warn";
    if (["stage", "wan_noise_stage"].includes(key)) return "select:high_noise,low_noise";
    if (["video_codec", "codec"].includes(key)) return "select:libx264,libx265,h264,h265,hevc,mpeg4";
    if (["minimax_text_encoder_device", "minimax_video_vae_device", "minimax_audio_vae_device", "minimax_reference_conditioning_device"].includes(key)) return "select:auto,cpu,gpu";
    if (["minimax_text_encoder_cache_mode"].includes(key)) return "select:off,cpu,gpu";
    if (["minimax_video_vae_decode_mode"].includes(key)) return "select:cpu_full,gpu_full,gpu_chunked,gpu_temporal_halo";
    if (["hunyuan_text_encoder_device", "hunyuan_video_vae_device", "hunyuan_i2v_source_encode_device"].includes(key)) return "select:auto,cpu,gpu";
    if (["hunyuan_text_encoder_cache_mode"].includes(key)) return "select:off,cpu,gpu";
    if (["hunyuan_vae_decode_mode"].includes(key)) return "select:cpu_full,gpu_full,gpu_chunked,gpu_temporal_halo";
    if (["device"].includes(key)) return "select:auto,cpu,cuda,xpu,mps";
    if (["dtype"].includes(key)) return "select:auto,float16,bfloat16,float32";
    if (["native_transformer_offload"].includes(key)) return "select:none,cpu_slots,disk_cpu_slots";
    if (["native_gguf_execution_mode"].includes(key)) return "select:lazy_quantized,eager_dequantized,comfy_gguf_lazy";
    if (["native_lazy_quantized_packed_device"].includes(key)) return "select:gpu,cpu";
    if (["workflow_loader_mode"].includes(key)) return "select:workflow_model_loader,built_in";
    if (["workflow_execution_backend"].includes(key)) return "select:native_graph,external_runtime_template";
    if (["backend"].includes(key)) return "select:diffusers";
    if (["gpu_selection_mode"].includes(key)) return "select:auto,single";
    if (["diffusers_pipeline_class"].includes(key)) return "select:DiffusionPipeline,AutoPipelineForText2Image,FluxPipeline,ZImagePipeline,StableDiffusionXLPipeline";
    if (["diffusers_transformer_class"].includes(key)) return "select:,FluxTransformer2DModel,ZImageTransformer2DModel";
    if (["model_deck_compat_manifest_id"].includes(key)) return "select:,flux_diffusers,zimage_diffusers,sdxl_lightning_diffusers";
    if (["sdxl_timestep_spacing"].includes(key)) return "select:trailing,leading,linspace";
    if (["sampler", "sampler_name"].includes(key)) return "select:gradient_estimation,euler,euler_ancestral,dpmpp_2m,dpmpp_sde,res_multistep";
    if (["scheduler"].includes(key)) return "select:simple,linear_quadratic,beta,normal,karras,trailing";
    if (["minimax_conditioning_mode"].includes(key)) return "select:ref2va,fl2va";
    if (["minimax_unet_loader"].includes(key)) return "select:advanced,basic";
    if (["minimax_gguf_dequant_dtype", "minimax_gguf_patch_dtype"].includes(key)) return "select:default,target,float32,float16,bfloat16";
    if (["minimax_ref_image_size"].includes(key)) return "select:match,max";
    if (["hunyuan_conditioning_mode"].includes(key)) return "select:t2v,i2v";
    if (["hunyuan_unet_loader"].includes(key)) return "select:basic,advanced";
    if (["hunyuan_gguf_dequant_dtype", "hunyuan_gguf_patch_dtype"].includes(key)) return "select:default,target,float32,float16,bfloat16";
    if (["hunyuan_clip_type", "clip_type"].includes(key)) return "select:hunyuan_video_15,hunyuan_video";
    if (["hunyuan_i2v_source_fit_mode"].includes(key)) return "select:center,contain,cover";
    if (["hunyuan_upscale_method"].includes(key)) return "select:bilinear,bicubic,bislerp,area,nearest-exact";
    if (["hunyuan_upscale_crop"].includes(key)) return "select:center,disabled";
    if (["minimax_rtx_upscale_quality"].includes(key)) return "select:LOW,MEDIUM,HIGH,ULTRA";
    if (["minimax_rtx_upscale_mode"].includes(key)) return "select:off,scale by multiplier,scale to size";
    if (["output_ext"].includes(key)) return "select:png,jpg,jpeg,webp,mp4";
    return "text";
  }

  function appendModelNodeField(parent, labelText, value, onRead, options = {}) {
    const field = document.createElement("label");
    field.className = "model-node-field";
    const label = document.createElement("span");
    label.textContent = labelText;
    field.appendChild(label);
    const valueType = options.type || modelNodeValueType(String(options.key || labelText), value);
    let input;
    if (valueType === "bool") {
      input = document.createElement("input");
      input.type = "checkbox";
      input.checked = Boolean(value);
      onRead(() => Boolean(input.checked));
    } else if (valueType === "int" || valueType === "float") {
      input = document.createElement("input");
      input.type = "number";
      input.step = valueType === "int" ? "1" : "any";
      input.value = value ?? "";
      onRead(() => {
        const n = valueType === "int" ? parseInt(input.value, 10) : parseFloat(input.value);
        return Number.isFinite(n) ? n : value;
      });
    } else if (String(valueType).startsWith("select:")) {
      input = document.createElement("select");
      String(valueType).slice("select:".length).split(",").forEach((opt) => {
        const o = document.createElement("option");
        o.value = opt;
        o.textContent = opt;
        input.appendChild(o);
      });
      input.value = String(value ?? "");
      onRead(() => input.value);
    } else if (String(value ?? "").length > 120 || String(options.key || "").includes("prompt")) {
      input = document.createElement("textarea");
      input.rows = 3;
      input.value = String(value ?? "");
      onRead(() => input.value);
    } else {
      input = document.createElement("input");
      input.type = "text";
      input.value = String(value ?? "");
      onRead(() => input.value);
    }
    if (options.help) input.title = String(options.help);
    field.appendChild(input);
    parent.appendChild(field);
    return input;
  }

  function buildModelNodeSettingsEditor(mergedValues) {
    const values = mergedValues && typeof mergedValues === "object" ? JSON.parse(JSON.stringify(mergedValues)) : {};
    const toolConfig = values.tool_config && typeof values.tool_config === "object" ? values.tool_config : {};
    const params = toolConfig.params && typeof toolConfig.params === "object" ? toolConfig.params : {};
    const settings = params.settings && typeof params.settings === "object" ? params.settings : {};
    const assets = params.assets && typeof params.assets === "object" ? params.assets : {};
    let nodeType = inferModelNodeType(values);
    let def = MODEL_NODE_DEFS[nodeType] || MODEL_NODE_DEFS.asset_resolver;
    const readers = [];

    const wrap = document.createElement("div");
    wrap.className = "model-node-editor";
    const intro = document.createElement("div");
    intro.className = "muted";
    intro.textContent = "Typed model node: only this node's relevant assets/settings are shown. Advanced raw JSON is still available below.";
    wrap.appendChild(intro);
    const adapterInfo = document.createElement("div");
    adapterInfo.className = "muted";
    adapterInfo.style.fontSize = "12px";
    adapterInfo.style.marginTop = "4px";
    const boundToolForAdapter = String(toolConfig.tool || "").trim();
    const adapter = findModelAdapterForTool(boundToolForAdapter, values);
    if (adapter && typeof adapter === "object") {
      const adapterName = String(adapter.name || adapter.id || "Model adapter").trim();
      const adapterId = String(adapter.id || "").trim();
      const skills = adapter.skills && typeof adapter.skills === "object" ? adapter.skills : {};
      const stageNames = Object.keys(skills).slice(0, 8);
      adapterInfo.textContent = `${adapterName}${adapterId ? ` (${adapterId})` : ""} capability provider. This workflow node calls ${boundToolForAdapter}; the adapter does not auto-load workflows.`;
      if (stageNames.length) adapterInfo.title = `Declared adapter stages: ${stageNames.join(", ")}${Object.keys(skills).length > stageNames.length ? ", ..." : ""}`;
    } else if (boundToolForAdapter.startsWith("models.")) {
      adapterInfo.textContent = `This workflow node calls ${boundToolForAdapter}. No adapter manifest matched it yet, so it uses the built-in/static model node definition.`;
    }
    if (adapterInfo.textContent) wrap.appendChild(adapterInfo);

    const actionSection = document.createElement("div");
    actionSection.className = "model-node-section";
    const actionTitle = document.createElement("div");
    actionTitle.className = "model-node-section-title";
    actionTitle.textContent = "Node actions";
    actionSection.appendChild(actionTitle);
    const actionRow = document.createElement("div");
    actionRow.className = "button-row";
    const btnPrecache = document.createElement("button");
    btnPrecache.type = "button";
    btnPrecache.className = "secondary";
    btnPrecache.textContent = "Pre-run / warm prompt encoder";
    btnPrecache.title = "Warm the workflow prompt encoder cache with saved workflow inputs. This is reusable across runs with different source images.";
    const btnClearCache = document.createElement("button");
    btnClearCache.type = "button";
    btnClearCache.className = "secondary";
    btnClearCache.textContent = "Release cached worker";
    btnClearCache.title = "Stop the keyed workflow worker and release its cached prompt/model resources.";
    const actionStatus = document.createElement("div");
    actionStatus.className = "muted";
    actionStatus.style.fontSize = "12px";
    actionStatus.textContent = "Use this for cacheable prompt encoder nodes such as Wan or Hunyuan text encoders.";
    actionRow.appendChild(btnPrecache);
    actionRow.appendChild(btnClearCache);
    actionSection.appendChild(actionRow);
    actionSection.appendChild(actionStatus);
    wrap.appendChild(actionSection);

    async function runModelNodeAction(actionName) {
      const pid = String(ctx?.state?.ui?.activePid || "default").trim() || "default";
      const sid = String(ctx?.state?.ui?.activeSid || "").trim();
      if (!sid) {
        actionStatus.textContent = "No active session is selected.";
        return;
      }
      const afSettings = getAgentFlowSettings(ctx, sid) || {};
      const flowName = String(afSettings.agent_flow_active_flow || bottomBarButton?.dataset?.activeFlow || "").trim();
      if (!flowName) {
        actionStatus.textContent = "No active workflow is selected.";
        return;
      }
      if (!selectedNodeId) {
        actionStatus.textContent = "No workflow node is selected.";
        return;
      }
      let collected = values;
      try {
        if (typeof wrap._agentFlowCollectValue === "function") collected = wrap._agentFlowCollectValue();
      } catch (_err) {}
      const collectedToolConfig = collected?.tool_config && typeof collected.tool_config === "object" ? collected.tool_config : {};
      const collectedParams = collectedToolConfig.params && typeof collectedToolConfig.params === "object" ? collectedToolConfig.params : {};
      const previousText = actionStatus.textContent;
      const isClear = String(actionName || "").toLowerCase().includes("clear") || String(actionName || "").toLowerCase().includes("stop");
      const targetBtn = isClear ? btnClearCache : btnPrecache;
      targetBtn.disabled = true;
      actionStatus.textContent = isClear ? "Releasing cached workflow worker..." : "Warming workflow prompt encoder cache...";
      try {
        const body = {
          action: actionName,
          flow_name: flowName,
          params: collectedParams,
        };
        if (String(actionName || "").toLowerCase() !== "warm_prompt_encoder") {
          body.node_id = selectedNodeId;
        }
        const res = await ctx.apiJson(`/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/agent_flow/node_action`, {
          method: "POST",
          body,
        });
        const result = res?.result || {};
        const nested = result?.result || result;
        const source = nested?.source_conditioning || nested?.data?.source_conditioning || {};
        const reason = nested?.reason || result?.reason || nested?.error || res?.error || "";
        if (source && typeof source === "object" && (source.status || source.cache_mode)) {
          actionStatus.textContent = `Source conditioning ${source.status || "cached"} (${source.cache_mode || "cache"}).`;
        } else if (nested?.prompt_context || nested?.data?.prompt_context) {
          const promptCtx = nested.prompt_context || nested.data.prompt_context || {};
          actionStatus.textContent = `Prompt encoder ${promptCtx.status || "warmed"}.`;
        } else if (res?.released_cached_worker !== undefined || result?.removed_count !== undefined || nested?.removed_count !== undefined) {
          const released = res?.released_cached_worker ? "released" : "not running";
          actionStatus.textContent = `Cached worker ${released}; cleared ${Number(result.removed_count ?? nested.removed_count ?? 0)} stale cache resource(s).`;
        } else {
          actionStatus.textContent = reason ? String(reason) : "Node action completed.";
        }
      } catch (err) {
        actionStatus.textContent = `Node action failed: ${err?.message || err}`;
      } finally {
        targetBtn.disabled = false;
        if (!actionStatus.textContent) actionStatus.textContent = previousText;
      }
    }

    btnPrecache.addEventListener("click", (event) => {
      event.preventDefault();
      void runModelNodeAction("warm_prompt_encoder");
    });
    btnClearCache.addEventListener("click", (event) => {
      event.preventDefault();
      void runModelNodeAction("clear_model_workflow_cache");
    });

    const typeSection = document.createElement("div");
    typeSection.className = "model-node-section";
    const typeTitle = document.createElement("div");
    typeTitle.className = "model-node-section-title";
    typeTitle.textContent = "Model node type";
    typeSection.appendChild(typeTitle);
    const typeGrid = document.createElement("div");
    typeGrid.className = "model-node-grid";
    const typeLabel = document.createElement("label");
    typeLabel.className = "model-node-field";
    const typeSpan = document.createElement("span");
    typeSpan.textContent = "Asset / stage type";
    const typeSelect = document.createElement("select");
    Object.entries(MODEL_NODE_DEFS).forEach(([key, row]) => {
      const opt = document.createElement("option");
      opt.value = key;
      opt.textContent = row.label;
      typeSelect.appendChild(opt);
    });
    typeSelect.value = nodeType;
    typeLabel.appendChild(typeSpan);
    typeLabel.appendChild(typeSelect);
    const help = document.createElement("div");
    help.className = "muted";
    help.style.fontSize = "12px";
    help.textContent = def.help || "";
    typeGrid.appendChild(typeLabel);
    typeSection.appendChild(typeGrid);
    typeSection.appendChild(help);
    wrap.appendChild(typeSection);

    const assetSection = document.createElement("div");
    assetSection.className = "model-node-section";
    const assetTitle = document.createElement("div");
    assetTitle.className = "model-node-section-title";
    assetTitle.textContent = "Assets for this node";
    assetSection.appendChild(assetTitle);
    const assetGrid = document.createElement("div");
    assetGrid.className = "model-node-grid";
    assetSection.appendChild(assetGrid);
    wrap.appendChild(assetSection);

    const settingSection = document.createElement("div");
    settingSection.className = "model-node-section";
    const settingTitle = document.createElement("div");
    settingTitle.className = "model-node-section-title";
    settingTitle.textContent = "Node settings";
    settingSection.appendChild(settingTitle);
    const settingGrid = document.createElement("div");
    settingGrid.className = "model-node-grid";
    settingSection.appendChild(settingGrid);
    wrap.appendChild(settingSection);

    const paramSection = document.createElement("div");
    paramSection.className = "model-node-section";
    const paramTitle = document.createElement("div");
    paramTitle.className = "model-node-section-title";
    paramTitle.textContent = "Runtime params / inputs";
    paramSection.appendChild(paramTitle);
    const paramGrid = document.createElement("div");
    paramGrid.className = "model-node-grid";
    paramSection.appendChild(paramGrid);
    wrap.appendChild(paramSection);

    const advanced = document.createElement("details");
    advanced.className = "model-node-section model-node-advanced";
    const advSummary = document.createElement("summary");
    advSummary.textContent = "Advanced raw tool_config JSON";
    advanced.appendChild(advSummary);
    const raw = document.createElement("textarea");
    raw.rows = 12;
    raw.spellcheck = false;
    raw.style.fontFamily = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";
    raw.style.fontSize = "11px";
    raw.value = JSON.stringify(toolConfig, null, 2);
    advanced.appendChild(raw);
    const rawBtn = document.createElement("button");
    rawBtn.type = "button";
    rawBtn.className = "secondary";
    rawBtn.textContent = "Open parsed editor";
    rawBtn.addEventListener("click", (event) => {
      event.preventDefault();
      openJsonFormEditor({ title: "Edit model node raw tool_config", textarea: raw });
    });
    advanced.appendChild(rawBtn);
    wrap.appendChild(advanced);

    function addScopedFields() {
      readers.length = 0;
      assetGrid.innerHTML = "";
      settingGrid.innerHTML = "";
      paramGrid.innerHTML = "";
      nodeType = String(typeSelect.value || nodeType || "asset_resolver");
      def = MODEL_NODE_DEFS[nodeType] || MODEL_NODE_DEFS.asset_resolver;
      help.textContent = def.help || "";
      const scopedAssets = {};
      const scopedSettings = {};
      const scopedParams = {};
      (def.assetKeys || []).forEach((key) => {
        scopedAssets[key] = assets[key] ?? settings[key] ?? "";
        appendModelNodeField(assetGrid, key, scopedAssets[key], (reader) => readers.push(() => { scopedAssets[key] = reader(); }), { key });
      });
      if (!(def.assetKeys || []).length) {
        const empty = document.createElement("div");
        empty.className = "muted";
        empty.textContent = "No file assets needed for this node.";
        assetGrid.appendChild(empty);
      }
      (def.settingKeys || []).forEach((key) => {
        scopedSettings[key] = settings[key] ?? params[key] ?? "";
        appendModelNodeField(settingGrid, key, scopedSettings[key], (reader) => readers.push(() => { scopedSettings[key] = reader(); }), { key });
      });
      (def.paramKeys || []).forEach((key) => {
        scopedParams[key] = params[key] ?? settings[key] ?? "";
        appendModelNodeField(paramGrid, key, scopedParams[key], (reader) => readers.push(() => { scopedParams[key] = reader(); }), { key });
      });
      appendModelNodeField(paramGrid, "params_from_input", def.paramsFromInput || toolConfig.params_from_input || [], (reader) => readers.push(() => {
        const rawValue = reader();
        scopedParams.__params_from_input = Array.isArray(rawValue)
          ? rawValue
          : String(rawValue || "").split(",").map((item) => item.trim()).filter(Boolean);
      }), { key: "params_from_input", type: "text", help: "Comma-separated request/runtime keys copied into this node." });
      wrap._modelNodeScoped = { scopedAssets, scopedSettings, scopedParams };
    }

    typeSelect.addEventListener("change", addScopedFields);
    addScopedFields();

    wrap._agentFlowCollectValue = () => {
      readers.forEach((reader) => {
        try { reader(); } catch (_err) {}
      });
      let rawToolConfig = {};
      try {
        rawToolConfig = JSON.parse(String(raw.value || "{}"));
      } catch (_err) {
        rawToolConfig = toolConfig && typeof toolConfig === "object" ? JSON.parse(JSON.stringify(toolConfig)) : {};
      }
      const selectedType = String(typeSelect.value || nodeType || "asset_resolver");
      const selectedDef = MODEL_NODE_DEFS[selectedType] || MODEL_NODE_DEFS.asset_resolver;
      const scoped = wrap._modelNodeScoped || {};
      const nextParams = rawToolConfig.params && typeof rawToolConfig.params === "object" ? rawToolConfig.params : {};
      const nextAssets = nextParams.assets && typeof nextParams.assets === "object" ? nextParams.assets : {};
      const nextSettings = nextParams.settings && typeof nextParams.settings === "object" ? nextParams.settings : {};
      Object.entries(scoped.scopedAssets || {}).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== "") {
          nextAssets[key] = value;
          nextSettings[key] = value;
        }
      });
      Object.entries(scoped.scopedSettings || {}).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== "") nextSettings[key] = value;
      });
      Object.entries(scoped.scopedParams || {}).forEach(([key, value]) => {
        if (key === "__params_from_input") return;
        if (value !== undefined && value !== null && value !== "") nextParams[key] = value;
      });
      nextParams.assets = nextAssets;
      nextParams.settings = nextSettings;
      const existingAssetKeys = Array.isArray(nextParams.asset_keys) ? nextParams.asset_keys.map((item) => String(item || "").trim()).filter(Boolean) : [];
      const mergedAssetKeys = [];
      const seenAssetKeys = new Set();
      [...existingAssetKeys, ...(selectedDef.assetKeys || [])].forEach((key) => {
        if (!key || seenAssetKeys.has(key)) return;
        seenAssetKeys.add(key);
        mergedAssetKeys.push(key);
      });
      if (mergedAssetKeys.length) nextParams.asset_keys = mergedAssetKeys;
      rawToolConfig.tool = selectedDef.tool;
      rawToolConfig.params = nextParams;
      rawToolConfig.params_from_input = Array.isArray(scoped.scopedParams?.__params_from_input)
        ? scoped.scopedParams.__params_from_input
        : (selectedDef.paramsFromInput || rawToolConfig.params_from_input || []);
      const selectedSkills = normalizeSkillArray(values.action_skills);
      if (!selectedSkills.includes(selectedDef.tool)) selectedSkills.unshift(selectedDef.tool);
      return {
        ...values,
        node_type: "tool_node",
        role: values.role || "Model workflow node",
        model_node_type: selectedType,
        model_asset_type: selectedType,
        action_skills: selectedSkills,
        tool_config: rawToolConfig,
      };
    };
    return wrap;
  }

  function coerceJsonFormValue(rawValue, previousValue) {
    if (previousValue === true || previousValue === false) return Boolean(rawValue);
    if (typeof previousValue === "number") {
      const n = Number(rawValue);
      return Number.isFinite(n) ? n : previousValue;
    }
    if (Array.isArray(previousValue)) {
      if (Array.isArray(rawValue)) return rawValue;
      return String(rawValue || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
    }
    if (previousValue && typeof previousValue === "object") return rawValue && typeof rawValue === "object" ? rawValue : previousValue;
    return String(rawValue ?? "");
  }

  function appendJsonFormField(parent, labelText, value, onRead) {
    const field = document.createElement("label");
    field.className = "json-form-field";
    const label = document.createElement("span");
    label.textContent = labelText;
    field.appendChild(label);
    let input;
    if (value === true || value === false) {
      input = document.createElement("input");
      input.type = "checkbox";
      input.checked = Boolean(value);
      onRead(() => Boolean(input.checked));
    } else if (typeof value === "number") {
      input = document.createElement("input");
      input.type = "number";
      input.step = Number.isInteger(value) ? "1" : "any";
      input.value = String(value);
      onRead(() => coerceJsonFormValue(input.value, value));
    } else if (Array.isArray(value)) {
      input = document.createElement("input");
      input.type = "text";
      input.value = value.map((v) => String(v ?? "")).join(", ");
      onRead(() => coerceJsonFormValue(input.value, value));
    } else if (value && typeof value === "object") {
      input = document.createElement("textarea");
      input.rows = 5;
      input.spellcheck = false;
      input.style.fontFamily = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";
      input.value = JSON.stringify(value, null, 2);
      onRead(() => {
        try {
          const parsed = JSON.parse(String(input.value || "{}"));
          return parsed && typeof parsed === "object" ? parsed : value;
        } catch (_err) {
          return value;
        }
      });
    } else {
      input = document.createElement("input");
      input.type = "text";
      input.value = String(value ?? "");
      onRead(() => input.value);
    }
    field.appendChild(input);
    parent.appendChild(field);
  }

  function openJsonFormEditor({ title, textarea, onSave } = {}) {
    if (!(textarea instanceof HTMLTextAreaElement)) return;
    const original = parseJsonEditorValue(textarea);
    const draft = JSON.parse(JSON.stringify(original || {}));
    const readers = [];

    const overlay = document.createElement("div");
    overlay.className = "agent-flow-json-form-popover";
    const head = document.createElement("div");
    head.className = "json-form-head";
    const heading = document.createElement("div");
    heading.className = "json-form-title";
    heading.textContent = String(title || "Edit JSON");
    const closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "secondary";
    closeBtn.textContent = "Close";
    head.appendChild(heading);
    head.appendChild(closeBtn);

    const body = document.createElement("div");
    body.className = "json-form-body";

    const addSection = (sectionTitle) => {
      const section = document.createElement("div");
      section.className = "json-form-section";
      const st = document.createElement("div");
      st.className = "json-form-section-title";
      st.textContent = sectionTitle;
      section.appendChild(st);
      body.appendChild(section);
      return section;
    };

    const rootSection = addSection("Tool binding");
    ["tool"].forEach((key) => {
      appendJsonFormField(rootSection, key, draft[key] ?? "", (reader) => readers.push(() => { draft[key] = reader(); }));
    });
    appendJsonFormField(rootSection, "params_from_input", draft.params_from_input ?? [], (reader) => readers.push(() => { draft.params_from_input = reader(); }));

    const params = draft.params && typeof draft.params === "object" && !Array.isArray(draft.params) ? draft.params : {};
    draft.params = params;
    const simpleParamsSection = addSection("Node params");
    Object.keys(params).sort().forEach((key) => {
      if (key === "assets" || key === "settings") return;
      appendJsonFormField(simpleParamsSection, `params.${key}`, params[key], (reader) => readers.push(() => { params[key] = reader(); }));
    });

    const assets = params.assets && typeof params.assets === "object" && !Array.isArray(params.assets) ? params.assets : {};
    params.assets = assets;
    const assetsSection = addSection("Assets / paths");
    Object.keys(assets).sort().forEach((key) => {
      appendJsonFormField(assetsSection, `assets.${key}`, assets[key], (reader) => readers.push(() => { assets[key] = reader(); }));
    });

    const settings = params.settings && typeof params.settings === "object" && !Array.isArray(params.settings) ? params.settings : {};
    params.settings = settings;
    const settingsSection = addSection("Settings / runtime");
    Object.keys(settings).sort().forEach((key) => {
      appendJsonFormField(settingsSection, `settings.${key}`, settings[key], (reader) => readers.push(() => { settings[key] = reader(); }));
    });

    const actions = document.createElement("div");
    actions.className = "json-form-actions";
    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "secondary";
    cancelBtn.textContent = "Cancel";
    const saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.textContent = "Save to JSON";
    actions.appendChild(cancelBtn);
    actions.appendChild(saveBtn);

    const close = () => overlay.remove();
    closeBtn.addEventListener("click", close);
    cancelBtn.addEventListener("click", close);
    saveBtn.addEventListener("click", () => {
      readers.forEach((reader) => {
        try { reader(); } catch (_err) {}
      });
      textarea.value = JSON.stringify(draft, null, 2);
      if (typeof onSave === "function") onSave(draft);
      close();
    });

    overlay.appendChild(head);
    overlay.appendChild(body);
    overlay.appendChild(actions);
    document.body.appendChild(overlay);
  }

  function buildPluginSettingsForm(schema, values) {
    pluginSettingsBox.innerHTML = "";
    pluginSettingsInputs = [];
    const defaults = schemaDefaults(schema);
    const merged = { ...defaults, ...(values || {}) };
    if (isModelToolNodeValues(merged)) {
      const editor = buildModelNodeSettingsEditor(merged);
      pluginSettingsBox.appendChild(editor);
      pluginSettingsInputs.push({ key: "__model_node_editor", type: "custom", input: editor, wrapper: editor, field: { key: "__model_node_editor" } });
      return;
    }
    if (!schema || !schema.length) {
      const empty = document.createElement("div");
      empty.className = "muted";
      empty.textContent = "No schema for this plugin.";
      pluginSettingsBox.appendChild(empty);
      return;
    }
    schema.forEach((field) => {
      if (!field || typeof field !== "object") return;
      // const key = String(field.key || "").trim();
      // if (!key) return;
      const key = String(field.key || "").trim();
      if (!key) return;
      if (key === "action_skill_categories") return;
      const label = String(field.label || key);
      const type = String(field.type || "str").toLowerCase();
      const help = String(field.help || field.description || "");
      const value = merged[key];

      const isSkillsField = key === "action_skills";
      const wrapper = document.createElement(isSkillsField ? "details" : "label");
      wrapper.className = isSkillsField ? "flow-meta-card" : "field";
      if (isSkillsField) wrapper.open = false;
      const titleRow = document.createElement("div");
      titleRow.style.display = "flex";
      titleRow.style.alignItems = "center";
      titleRow.style.justifyContent = "space-between";
      titleRow.style.gap = "8px";
      const span = document.createElement("span");
      span.textContent = isSkillsField ? "Skills" : label;
      titleRow.appendChild(span);
      if (key === "action_skills") {
        const btnRefreshSkills = document.createElement("button");
        btnRefreshSkills.type = "button";
        btnRefreshSkills.className = "ghost";
        btnRefreshSkills.textContent = "Refresh skills";
        btnRefreshSkills.style.padding = "2px 8px";
        btnRefreshSkills.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          btnRefreshSkills.disabled = true;
          btnRefreshSkills.textContent = "Refreshing...";
          ctx.state.router = ctx.state.router || {};
          ctx.state.router.manifest = {};
          agentFlowSkillCatalog = null;

          Promise.all([
            ensureManifest(ctx),
            loadAgentFlowSkillCatalog(ctx, true),
          ])
            .then(([m]) => {
              manifest = m || {};
              if (selectedNodeId) {
                const node = getCurrentNodes()[selectedNodeId];
                if (node) {
                  const freshSchema = schemaForPlugin(node.plugin_id || "");
                  buildPluginSettingsForm(freshSchema, node.plugin_settings || {});
                }
              }
            })
            .catch((err) => {
              ctx.log?.(`[agent_flow] refresh skills failed: ${err?.message || err}`, "warn");
            })
            .finally(() => {
              btnRefreshSkills.disabled = false;
              btnRefreshSkills.textContent = "Refresh skills";
            });
        });
        titleRow.appendChild(btnRefreshSkills);
      }
      let contentHost = wrapper;
      if (isSkillsField) {
        const summary = document.createElement("summary");
        summary.appendChild(titleRow);
        wrapper.appendChild(summary);
        const body = document.createElement("div");
        body.className = "flow-meta-card-body";
        wrapper.appendChild(body);
        contentHost = body;
      } else {
        wrapper.appendChild(titleRow);
      }

      let input = null;
      if (type === "bool" || type === "boolean") {
        input = document.createElement("input");
        input.type = "checkbox";
        input.checked = Boolean(value);
      } else if (type === "int" || type === "integer") {
        input = document.createElement("input");
        input.type = "number";
        input.step = "1";
        input.value = value ?? "";
      } else if (type === "float" || type === "number") {
        input = document.createElement("input");
        input.type = "number";
        input.step = "any";
        input.value = value ?? "";
      } else if (type === "enum" || type === "select") {
        input = document.createElement("select");
        const opts = Array.isArray(field.options || field.choices) ? field.options || field.choices : [];
        opts.forEach((opt) => {
          const o = document.createElement("option");
          o.value = String(opt);
          o.textContent = String(opt);
          input.appendChild(o);
        });
        if (value !== undefined && value !== null) input.value = String(value);
      // } else if (type === "multiselect" || type === "multi_select" || type === "enum_multi") {
      //   input = document.createElement("div");
      //   input.className = "multi-check";
      //   const opts = Array.isArray(field.options || field.choices) ? field.options || field.choices : [];
      //   const selected = Array.isArray(value) ? value.map((v) => String(v)) : String(value || "").split(",").map((s) => s.trim()).filter(Boolean);
      //   opts.forEach((opt) => {
      //     const row = document.createElement("label");
      //     row.style.display = "flex";
      //     row.style.alignItems = "center";
      //     row.style.gap = "6px";
      //     const cb = document.createElement("input");
      //     cb.type = "checkbox";
      //     cb.value = String(opt);
      //     cb.checked = selected.includes(String(opt));
      //     const tx = document.createElement("span");
      //     tx.textContent = String(opt);
      //     row.appendChild(cb);
      //     row.appendChild(tx);
      //     input.appendChild(row);
      //   });
      } else if (type === "multiselect" || type === "multi_select" || type === "enum_multi") {
        if (key === "action_skills") {
          input = buildGroupedSkillPicker(field, merged);
        } else {
          input = document.createElement("div");
          input.className = "multi-check";
          const opts = Array.isArray(field.options || field.choices) ? field.options || field.choices : [];
          const selected = Array.isArray(value) ? value.map((v) => String(v)) : String(value || "").split(",").map((s) => s.trim()).filter(Boolean);
          opts.forEach((opt) => {
            const row = document.createElement("label");
            row.style.display = "flex";
            row.style.alignItems = "center";
            row.style.gap = "6px";
            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.value = String(opt);
            cb.checked = selected.includes(String(opt));
            const tx = document.createElement("span");
            tx.textContent = String(opt);
            row.appendChild(cb);
            row.appendChild(tx);
            input.appendChild(row);
          });
        }
      } else if (type === "json" || type === "object" || type === "array") {
        input = document.createElement("textarea");
        input.rows = key === "tool_config" ? 14 : 8;
        input.spellcheck = false;
        input.style.fontFamily = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";
        input.style.fontSize = "11px";
        input.value = value === undefined || value === null || value === ""
          ? ""
          : JSON.stringify(value, null, 2);
      } else {
        input = document.createElement("input");
        input.type = "text";
        input.value = value && typeof value === "object" ? JSON.stringify(value, null, 2) : value ?? "";
      }
      if (help) input.title = help;
      contentHost.appendChild(input);
      if (key === "tool_config" && input instanceof HTMLTextAreaElement) {
        const editBtn = document.createElement("button");
        editBtn.type = "button";
        editBtn.className = "secondary";
        editBtn.textContent = "Open parsed editor";
        editBtn.style.alignSelf = "flex-start";
        editBtn.addEventListener("click", (event) => {
          event.preventDefault();
          openJsonFormEditor({
            title: "Edit tool params",
            textarea: input,
            onSave: () => {
              input.dispatchEvent(new Event("input", { bubbles: true }));
              input.dispatchEvent(new Event("change", { bubbles: true }));
            },
          });
        });
        contentHost.appendChild(editBtn);
      }
      pluginSettingsBox.appendChild(wrapper);
      pluginSettingsInputs.push({ key, type, input, wrapper, field });
    });
    const readPluginFieldValue = (type, input) => {
      if (type === "bool" || type === "boolean") return Boolean(input.checked);
      if (type === "int" || type === "integer") {
        const parsed = parseInt(input.value, 10);
        return Number.isNaN(parsed) ? null : parsed;
      }
      if (type === "float" || type === "number") {
        const parsed = parseFloat(input.value);
        return Number.isNaN(parsed) ? null : parsed;
      }
      if (type === "multiselect" || type === "multi_select" || type === "enum_multi") {
        const checks = Array.from(input.querySelectorAll("input[type='checkbox']"));
        return checks.filter((c) => c.checked).map((c) => String(c.value || "").trim()).filter(Boolean);
      }
      if (type === "json" || type === "object" || type === "array") {
        const text = String(input.value || "").trim();
        if (!text) return type === "array" ? [] : {};
        try {
          return JSON.parse(text);
        } catch (_err) {
          return text;
        }
      }
      return input.value;
    };
    const shouldShowPluginField = (field, currentValues) => {
      const rule = field?.show_if;
      if (!rule || typeof rule !== "object") return true;
      const depKey = String(rule.key || "").trim();
      if (!depKey) return true;
      const currentValue = currentValues[depKey];
      if (Object.prototype.hasOwnProperty.call(rule, "equals")) return currentValue === rule.equals;
      if (Object.prototype.hasOwnProperty.call(rule, "not_equals")) return currentValue !== rule.not_equals;
      return Boolean(currentValue);
    };
    const refreshPluginFieldVisibility = () => {
      const currentValues = {};
      pluginSettingsInputs.forEach(({ key: itemKey, type: itemType, input: itemInput }) => {
        currentValues[itemKey] = readPluginFieldValue(itemType, itemInput);
      });
      pluginSettingsInputs.forEach(({ wrapper: itemWrapper, field: itemField }) => {
        itemWrapper.style.display = shouldShowPluginField(itemField, currentValues) ? "" : "none";
      });
    };
    pluginSettingsInputs.forEach(({ input }) => {
      const handler = () => refreshPluginFieldVisibility();
      input.addEventListener("change", handler);
      if ("value" in input) input.addEventListener("input", handler);
    });
    refreshPluginFieldVisibility();
  }

  // function collectPluginSettings() {
  //   const out = {};
  //   pluginSettingsInputs.forEach(({ key, type, input }) => {
  //     let value;
  //     if (type === "bool" || type === "boolean") {
  //       value = Boolean(input.checked);
  //     } else if (type === "int" || type === "integer") {
  //       const parsed = parseInt(input.value, 10);
  //       value = Number.isNaN(parsed) ? null : parsed;
  //     } else if (type === "float" || type === "number") {
  //       const parsed = parseFloat(input.value);
  //       value = Number.isNaN(parsed) ? null : parsed;
  //     } else if (type === "multiselect" || type === "multi_select" || type === "enum_multi") {
  //       const checks = Array.from(input.querySelectorAll("input[type='checkbox']"));
  //       value = checks.filter((c) => c.checked).map((c) => String(c.value || "").trim()).filter(Boolean);
  //     } else {
  //       value = input.value;
  //     }
  //     const keepArray = Array.isArray(value) && value.length > 0;
  //     if (keepArray || (value !== null && value !== undefined && value !== "")) {
  //       out[key] = value;
  //     }
  //   });
  //   return out;
  // }
  function collectPluginSettings() {
    const out = {};
    pluginSettingsInputs.forEach(({ key, type, input }) => {
      if (input && typeof input._agentFlowCollectValue === "function") {
        const custom = input._agentFlowCollectValue();
        Object.entries(custom || {}).forEach(([customKey, customValue]) => {
          const keepArray = Array.isArray(customValue) && customValue.length > 0;
          const keepObject =
            customValue &&
            typeof customValue === "object" &&
            !Array.isArray(customValue) &&
            Object.keys(customValue).length > 0;
          if (keepArray || keepObject || (customValue !== null && customValue !== undefined && customValue !== "" && typeof customValue !== "object")) {
            out[customKey] = customValue;
          }
        });
        return;
      }

      let value;
      if (type === "bool" || type === "boolean") {
        value = Boolean(input.checked);
      } else if (type === "int" || type === "integer") {
        const parsed = parseInt(input.value, 10);
        value = Number.isNaN(parsed) ? null : parsed;
      } else if (type === "float" || type === "number") {
        const parsed = parseFloat(input.value);
        value = Number.isNaN(parsed) ? null : parsed;
      } else if (type === "multiselect" || type === "multi_select" || type === "enum_multi") {
        const checks = Array.from(input.querySelectorAll("input[type='checkbox']"));
        value = checks.filter((c) => c.checked).map((c) => String(c.value || "").trim()).filter(Boolean);
      } else {
        value = input.value;
      }

      const keepArray = Array.isArray(value) && value.length > 0;
      if (keepArray || (value !== null && value !== undefined && value !== "")) {
        out[key] = value;
      }
    });
    if (Object.prototype.hasOwnProperty.call(out, "iteration_keys")) {
      const raw = out.iteration_keys;
      if (Array.isArray(raw)) {
        out.iteration_keys = raw.map((v) => String(v || "").trim()).filter(Boolean);
      } else {
        out.iteration_keys = String(raw || "")
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean);
      }
      if (!out.iteration_keys.length) delete out.iteration_keys;
    }
    if (Object.prototype.hasOwnProperty.call(out, "iteration_key")) {
      const raw = String(out.iteration_key || "").trim();
      if (raw) out.iteration_key = raw;
      else delete out.iteration_key;
    }
    ["subflow_input_map", "subflow_output_map"].forEach((mapKey) => {
      if (!Object.prototype.hasOwnProperty.call(out, mapKey)) return;
      const raw = String(out[mapKey] || "").trim();
      if (!raw) {
        delete out[mapKey];
        return;
      }
      try {
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) out[mapKey] = parsed;
        else delete out[mapKey];
      } catch (_) {
        delete out[mapKey];
      }
    });
    return out;
  }

  function renderTransitionEditor(nodeId, transitions) {
    transitionsBox.innerHTML = "";
    transitionInputs = [];
    const nodeIds = Object.keys(getCurrentNodes()).filter((id) => id !== nodeId).sort();
    const rows = Array.isArray(transitions) ? transitions : [];
    const conditionOptions = [
      ["always", "Always"],
      ["no_changed_files", "No changed files"],
      ["changed_files_present", "Changed files present"],
      ["bugs_present", "Bugs present"],
      ["no_bugs", "No bugs"],
      ["handoff_contains", "Handoff contains"],
      ["did_contains", "Did contains"],
      ["output_contains", "Output contains"],
      ["output_not_contains", "Output not contains"],
      ["test_failures_gte", "Test failures >="],
      ["test_failures_lte", "Test failures <="],
    ];
    if (!rows.length) {
      const empty = document.createElement("div");
      empty.className = "muted";
      empty.textContent = "No transitions for this node.";
      transitionsBox.appendChild(empty);
      return;
    }
    rows.forEach((row, idx) => {
      const item = document.createElement("div");
      item.className = "transition-item";
      const head = document.createElement("div");
      head.className = "transition-item-head";
      const headTitle = document.createElement("div");
      headTitle.className = "transition-item-title";
      headTitle.textContent = `Edge ${idx + 1}`;
      head.appendChild(headTitle);
      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "ghost";
      removeBtn.textContent = "Remove";
      removeBtn.addEventListener("click", () => {
        if (!selectedNodeId) return;
        const node = getCurrentNodes()[selectedNodeId];
        if (!node) return;
        const ts = Array.isArray(node.transitions) ? node.transitions.slice() : [];
        ts.splice(idx, 1);
        node.transitions = ts;
        renderTransitionEditor(selectedNodeId, node.transitions);
        renderEdges();
        scheduleSave();
      });
      head.appendChild(removeBtn);
      item.appendChild(head);

      const targetField = document.createElement("label");
      targetField.className = "field";
      targetField.innerHTML = "<span>Target node</span>";
      const targetSelect = document.createElement("select");
      nodeIds.forEach((tid) => {
        const opt = document.createElement("option");
        opt.value = tid;
        opt.textContent = tid;
        targetSelect.appendChild(opt);
      });
      targetSelect.value = String(row?.target || "");
      targetField.appendChild(targetSelect);
      item.appendChild(targetField);

      const normalized = normalizeTransitionCondition(row?.condition);
      const conditionModel = deepClone(normalized);
      const rerenderTransition = (nextConditionModel = conditionModel) => {
        const draftTransitions = collectTransitions();
        draftTransitions[idx] = {
          ...(draftTransitions[idx] || {}),
          target: String(targetSelect.value || ""),
          condition: deepClone(nextConditionModel),
          loop_max_passes: normalizeLoopMaxSetting(
            passesInput.value,
            normalizeLoopMaxSetting(getAgentFlowSettings(ctx, sid)?.agent_flow_loop_max_passes, 16)
          ),
          system_prompt: String(promptBox.value || ""),
          action_tool: String(actionToolInput.value || "").trim(),
          action_params_from_input: String(actionParamsFromInputInput.value || "")
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
          runtime_only: !!runtimeOnlyInput.checked,
        };
        const edgeParamsText = String(actionParamsInput.value || "").trim();
        if (edgeParamsText) {
          try {
            draftTransitions[idx].action_params = JSON.parse(edgeParamsText);
          } catch (_) {}
        }
        renderTransitionEditor(nodeId, draftTransitions);
      };

      const inline = document.createElement("div");
      inline.className = "transition-inline";
      const passesField = document.createElement("label");
      passesField.className = "field";
      passesField.innerHTML = "<span>Max loop passes</span>";
      const passesInput = document.createElement("input");
      passesInput.type = "number";
      passesInput.min = "0";
      passesInput.step = "1";
      passesInput.value = String(
        normalizeLoopMaxSetting(
          row?.loop_max_passes ?? row?.max_passes,
          normalizeLoopMaxSetting(getAgentFlowSettings(ctx, sid)?.agent_flow_loop_max_passes, 16)
        )
      );
      passesField.appendChild(passesInput);
      inline.appendChild(passesField);
      item.appendChild(inline);

      const rulesBox = document.createElement("div");
      rulesBox.className = "transition-rules";
      item.appendChild(rulesBox);
      const renderConditionNode = (nodeRef, parentRules, nodeIndex, host, depth = 0) => {
        if (nodeRef && (nodeRef.kind === "group" || Array.isArray(nodeRef.rules))) {
          const group = nodeRef.kind === "group" ? nodeRef : normalizeTransitionCondition(nodeRef);
          const groupWrap = document.createElement("div");
          groupWrap.className = "transition-group";
          groupWrap.style.marginLeft = depth ? `${Math.min(depth * 16, 48)}px` : "0";
          const groupHead = document.createElement("div");
          groupHead.className = "transition-item-head";
          const groupTitle = document.createElement("div");
          groupTitle.className = "transition-item-title";
          groupTitle.textContent = depth ? `Group ${depth}` : "Root group";
          groupHead.appendChild(groupTitle);
          if (parentRules && nodeIndex >= 0) {
            const removeGroupBtn = document.createElement("button");
            removeGroupBtn.type = "button";
            removeGroupBtn.className = "ghost";
            removeGroupBtn.textContent = "Remove group";
            removeGroupBtn.addEventListener("click", () => {
              parentRules.splice(nodeIndex, 1);
              if (!parentRules.length) parentRules.push(makeDefaultConditionRule());
              rerenderTransition(conditionModel);
            });
            groupHead.appendChild(removeGroupBtn);
          }
          groupWrap.appendChild(groupHead);

          const groupLogicField = document.createElement("label");
          groupLogicField.className = "field";
          groupLogicField.innerHTML = "<span>Condition logic</span>";
          const logicSelect = document.createElement("select");
          [["all", "All (AND)"], ["any", "Any (OR)"]].forEach(([value, label]) => {
            const opt = document.createElement("option");
            opt.value = value;
            opt.textContent = label;
            logicSelect.appendChild(opt);
          });
          logicSelect.value = String(group.operator || "all");
          logicSelect.addEventListener("change", () => {
            group.operator = String(logicSelect.value || "all") === "any" ? "any" : "all";
          });
          groupLogicField.appendChild(logicSelect);
          groupWrap.appendChild(groupLogicField);

          const childBox = document.createElement("div");
          childBox.className = "transition-rules";
          groupWrap.appendChild(childBox);
          (Array.isArray(group.rules) ? group.rules : []).forEach((child, childIdx) => {
            renderConditionNode(child, group.rules, childIdx, childBox, depth + 1);
          });

          const groupButtons = document.createElement("div");
          groupButtons.className = "button-row";
          const addClauseBtn = document.createElement("button");
          addClauseBtn.type = "button";
          addClauseBtn.className = "ghost";
          addClauseBtn.textContent = "Add clause";
          addClauseBtn.addEventListener("click", () => {
            group.rules.push(makeDefaultConditionRule());
            rerenderTransition(conditionModel);
          });
          groupButtons.appendChild(addClauseBtn);
          const addGroupBtn = document.createElement("button");
          addGroupBtn.type = "button";
          addGroupBtn.className = "ghost";
          addGroupBtn.textContent = "Add group";
          addGroupBtn.addEventListener("click", () => {
            group.rules.push(makeDefaultConditionGroup());
            rerenderTransition(conditionModel);
          });
          groupButtons.appendChild(addGroupBtn);
          groupWrap.appendChild(groupButtons);
          host.appendChild(groupWrap);
          return;
        }

        const clause = nodeRef && typeof nodeRef === "object" ? nodeRef : makeDefaultConditionRule();
        const clauseWrap = document.createElement("div");
        clauseWrap.className = "transition-rule";
        clauseWrap.style.marginLeft = depth ? `${Math.min(depth * 16, 48)}px` : "0";
        const clauseHead = document.createElement("div");
        clauseHead.className = "transition-item-head";
        const clauseTitle = document.createElement("div");
        clauseTitle.className = "transition-item-title";
        clauseTitle.textContent = "Clause";
        clauseHead.appendChild(clauseTitle);
        if (parentRules && nodeIndex >= 0) {
          const removeClauseBtn = document.createElement("button");
          removeClauseBtn.type = "button";
          removeClauseBtn.className = "ghost";
          removeClauseBtn.textContent = "Remove";
          removeClauseBtn.addEventListener("click", () => {
            parentRules.splice(nodeIndex, 1);
            if (!parentRules.length) parentRules.push(makeDefaultConditionRule());
            rerenderTransition(conditionModel);
          });
          clauseHead.appendChild(removeClauseBtn);
        }
        clauseWrap.appendChild(clauseHead);

        const clauseInline = document.createElement("div");
        clauseInline.className = "transition-inline single";
        const conditionField = document.createElement("label");
        conditionField.className = "field";
        conditionField.innerHTML = "<span>Condition</span>";
        const conditionSelect = document.createElement("select");
        conditionOptions.forEach(([value, label]) => {
          const opt = document.createElement("option");
          opt.value = value;
          opt.textContent = label;
          conditionSelect.appendChild(opt);
        });
        conditionSelect.value = String(clause.type || "always");
        conditionSelect.addEventListener("change", () => {
          clause.type = String(conditionSelect.value || "always");
          syncValueVisibility();
        });
        conditionField.appendChild(conditionSelect);
        clauseInline.appendChild(conditionField);

        const valueField = document.createElement("label");
        valueField.className = "field";
        valueField.innerHTML = "<span>Condition value</span>";
        const valueInput = document.createElement("input");
        valueInput.type = "text";
        valueInput.value = String(clause.value || "");
        valueInput.addEventListener("input", () => {
          clause.value = String(valueInput.value || "");
        });
        valueField.appendChild(valueInput);
        clauseInline.appendChild(valueField);
        clauseWrap.appendChild(clauseInline);

        const syncValueVisibility = () => {
          const needsValue = [
            "output_contains",
            "output_not_contains",
            "handoff_contains",
            "did_contains",
            "test_failures_gte",
            "test_failures_lte",
          ].includes(String(conditionSelect.value || ""));
          valueField.style.display = needsValue ? "" : "none";
        };
        syncValueVisibility();
        host.appendChild(clauseWrap);
      };
      renderConditionNode(conditionModel, null, -1, rulesBox, 0);

      const promptField = document.createElement("label");
      promptField.className = "field";
      promptField.innerHTML = "<span>Loopback system prompt</span>";
      const promptBox = document.createElement("textarea");
      promptBox.value = String(row?.system_prompt || "");
      promptField.appendChild(promptBox);
      item.appendChild(promptField);

      const edgeActionTitle = document.createElement("div");
      edgeActionTitle.className = "transition-item-title";
      edgeActionTitle.textContent = "Optional edge action";
      item.appendChild(edgeActionTitle);

      const actionToolField = document.createElement("label");
      actionToolField.className = "field";
      actionToolField.innerHTML = "<span>Edge action tool</span>";
      const actionToolInput = document.createElement("input");
      actionToolInput.type = "text";
      actionToolInput.placeholder = "workflow.tracker";
      actionToolInput.value = String(row?.action_tool || row?.edge_action?.tool || "");
      actionToolField.appendChild(actionToolInput);
      item.appendChild(actionToolField);

      const actionParamsFromInputField = document.createElement("label");
      actionParamsFromInputField.className = "field";
      actionParamsFromInputField.innerHTML = "<span>Edge params from input</span>";
      const actionParamsFromInputInput = document.createElement("input");
      actionParamsFromInputInput.type = "text";
      const paramsFromInputSeed = Array.isArray(row?.action_params_from_input)
        ? row.action_params_from_input
        : Array.isArray(row?.edge_action?.params_from_input)
          ? row.edge_action.params_from_input
          : [];
      actionParamsFromInputInput.placeholder = "planned_requests, tracker_state";
      actionParamsFromInputInput.value = paramsFromInputSeed.join(", ");
      actionParamsFromInputField.appendChild(actionParamsFromInputInput);
      item.appendChild(actionParamsFromInputField);

      const actionParamsField = document.createElement("label");
      actionParamsField.className = "field";
      actionParamsField.innerHTML = "<span>Edge action params (JSON)</span>";
      const actionParamsInput = document.createElement("textarea");
      const edgeParamsSeed = row?.action_params || row?.edge_action?.params || {};
      actionParamsInput.value = edgeParamsSeed && Object.keys(edgeParamsSeed).length ? JSON.stringify(edgeParamsSeed, null, 2) : "";
      actionParamsField.appendChild(actionParamsInput);
      item.appendChild(actionParamsField);

      const runtimeOnlyField = document.createElement("label");
      runtimeOnlyField.className = "field checkbox-field";
      const runtimeOnlyInput = document.createElement("input");
      runtimeOnlyInput.type = "checkbox";
      runtimeOnlyInput.checked = !!(row?.runtime_only || row?.edge_action?.runtime_only || row?.action_tool || row?.edge_action?.tool);
      const runtimeOnlyLabel = document.createElement("span");
      runtimeOnlyLabel.textContent = "Runtime-only edge";
      runtimeOnlyField.appendChild(runtimeOnlyInput);
      runtimeOnlyField.appendChild(runtimeOnlyLabel);
      item.appendChild(runtimeOnlyField);

      transitionsBox.appendChild(item);
      transitionInputs.push({
        targetSelect,
        conditionModel,
        passesInput,
        promptBox,
        actionToolInput,
        actionParamsFromInputInput,
        actionParamsInput,
        runtimeOnlyInput,
      });
    });
  }

  function collectTransitions() {
    const out = [];
    transitionInputs.forEach((row) => {
      const target = String(row?.targetSelect?.value || "").trim();
      if (!target) return;
      const loopMaxPasses = normalizeLoopMaxSetting(
        row?.passesInput?.value,
        normalizeLoopMaxSetting(getAgentFlowSettings(ctx, sid)?.agent_flow_loop_max_passes, 16)
      );
      const systemPrompt = String(row?.promptBox?.value || "").trim();
      const next = {
        target,
        condition: deepClone(row?.conditionModel || makeDefaultConditionGroup()),
        loop_max_passes: loopMaxPasses,
      };
      if (systemPrompt) next.system_prompt = systemPrompt;
      const actionTool = String(row?.actionToolInput?.value || "").trim();
      const actionParamsFromInput = String(row?.actionParamsFromInputInput?.value || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const actionParamsText = String(row?.actionParamsInput?.value || "").trim();
      const runtimeOnly = !!row?.runtimeOnlyInput?.checked;
      if (actionTool) next.action_tool = actionTool;
      if (actionParamsFromInput.length) next.action_params_from_input = actionParamsFromInput;
      if (runtimeOnly) next.runtime_only = true;
      if (actionParamsText) {
        try {
          const parsed = JSON.parse(actionParamsText);
          if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
            next.action_params = parsed;
          }
        } catch (_) {}
      }
      out.push(next);
    });
    return out;
  }

  function schemaForPlugin(pluginId) {
    if (String(pluginId || "").trim() === "agent_flow_subflow") {
      const flowNames = Object.keys(flows || {}).sort();
      return [
        {
          key: "node_type",
          label: "Subflow Mode",
          type: "enum",
          options: ["subflow_node", "fan_out_node"],
          default: "subflow_node",
          help: "Subflow runs one child workflow path. Fan-Out resolves an item list at runtime, runs the subflow once per item, then automatically joins the results before this node's outgoing edges continue.",
        },
        {
          key: "subflow_name",
          label: "Subflow Name",
          type: "enum",
          options: flowNames,
          default: flowNames[0] || "",
          help: "Referenced child flow to execute at runtime.",
        },
        {
          key: "loop_enabled",
          label: "Loop",
          type: "bool",
          default: false,
          help: "Legacy one-time static loop expansion. Prefer Fan-Out mode for true runtime iteration.",
        },
        {
          key: "loop_subflow_name",
          label: "Loop Subflow",
          type: "enum",
          options: flowNames,
          default: flowNames[0] || "",
          help: "Legacy loop target for the old static subflow behavior.",
          show_if: { key: "loop_enabled", equals: true },
        },
      ];
    }
    const meta = manifest[pluginId] || {};
    let schema = meta.schema || meta.config_schema || [];
    if (!Array.isArray(schema)) return [];
    if (String(pluginId || "").trim() === "agent_workflow_member") {
      schema = mergeAgentFlowSkillSchema(schema);
      if (!schema.some((field) => String(field?.key || "").trim() === "tool_config")) {
        schema.push({
          key: "tool_config",
          label: "Tool params JSON",
          type: "json",
          default: {},
          help: "For tool nodes, this controls the exact bound skill and node-specific params/assets/settings passed to that skill.",
        });
      }
      return schema.filter((field) => {
        const key = String(field?.key || "").trim();
        return !key.startsWith("agent_workflow_member_");
      });
    }
    return schema;
  }

  function applyNodeProperties() {
    if (!selectedNodeId) return;
    if (currentFlowIsReadOnly()) {
      ctx.log?.("This workflow is read-only.", "warn");
      return;
    }
    const nodes = getCurrentNodes();
    const node = nodes[selectedNodeId];
    if (!node) return;
    node.label = labelInput.value.trim() || selectedNodeId;
    node.plugin_id = pluginInputWrap.input.value.trim() || "chat";
    node.agent_kind = agentInput.value.trim();
    node.delay_ms = parseInt(delayInput.value || "0", 10) || 0;
    node.system_prompt = promptInput.value.trim();
    node.return_only_text = Boolean(returnOnlyInput.checked);
    const nextPluginSettings = collectPluginSettings();
    node.plugin_settings = String(node.plugin_id || "").trim() === "agent_flow_subflow"
      ? normalizeSubflowPluginSettings(
          mergeHiddenSubflowSettings(node.plugin_settings, nextPluginSettings),
          flows,
          getAgentFlowSettings(ctx, sid) || {}
        )
      : nextPluginSettings;
    node.transitions = collectTransitions();
    const el = nodeElements.get(selectedNodeId);
    if (el) {
      const main = el.querySelector(".node-main-label");
      if (main) main.textContent = node.label;
      const badge = el.querySelector(".node-sub-badge");
      const sf = String((node.plugin_settings || {}).subflow_name || "").trim();
      if (badge) {
        if (String(node.plugin_id || "").trim() === "agent_flow_subflow") {
          badge.textContent = subflowBadgeText(node);
          badge.style.display = "";
        } else {
          badge.style.display = "none";
        }
      }
    }
    renderEdges();
    scheduleSave();
  }

  function updateHint() {
    if (linkSourceId) {
      hint.textContent = `Linking from ${linkSourceId}. Click a target node.`;
    } else {
      hint.textContent = "";
    }
  }

  function createEdge(fromId, toId) {
    if (!fromId || !toId || fromId === toId) return;
    if (currentFlowIsReadOnly()) {
      ctx.log?.("This workflow is read-only.", "warn");
      return;
    }
    const nodes = getCurrentNodes();
    const node = nodes[fromId];
    if (!node) return;
    if (!Array.isArray(node.transitions)) node.transitions = [];
    if (node.transitions.some((t) => t?.target === toId)) return;
    node.transitions.push({
      condition: { type: "always" },
      target: toId,
      loop_max_passes: normalizeLoopMaxSetting(getAgentFlowSettings(ctx, sid)?.agent_flow_loop_max_passes, 16),
    });
    renderEdges();
    scheduleSave();
  }

  function getNodeClipboard() {
    const clip = ctx?.state?.agent_flow_node_clipboard;
    return clip && typeof clip === "object" ? clip : null;
  }

  function setNodeClipboard(clip) {
    if (clip && typeof clip === "object") {
      ctx.state.agent_flow_node_clipboard = clip;
    } else if (ctx?.state && Object.prototype.hasOwnProperty.call(ctx.state, "agent_flow_node_clipboard")) {
      delete ctx.state.agent_flow_node_clipboard;
    }
    ctx.saveState?.();
  }

  function selectedIdsList(preferredId = "") {
    const ids = Array.from(selectedNodeIds || []).filter((id) => getCurrentNodes()[id]);
    if (preferredId && !ids.includes(preferredId) && getCurrentNodes()[preferredId]) {
      ids.unshift(preferredId);
    }
    return ids.length ? ids : (preferredId && getCurrentNodes()[preferredId] ? [preferredId] : []);
  }

  function copySelectedNodes(preferredId = "") {
    const ids = selectedIdsList(preferredId);
    if (!ids.length) return false;
    const nodes = getCurrentNodes();
    const picked = {};
    ids.forEach((id) => {
      if (!nodes[id]) return;
      picked[id] = deepClone(nodes[id]);
    });
    const idSet = new Set(Object.keys(picked));
    Object.values(picked).forEach((node) => {
      const transitions = Array.isArray(node.transitions) ? node.transitions : [];
      node.transitions = transitions.filter((t) => idSet.has(String(t?.target || "")));
    });
    setNodeClipboard({
      type: "nodes",
      copiedAt: Date.now(),
      sourceFlow: String(currentFlow || ""),
      nodes: picked,
    });
    ctx.log?.(`[agent_flow] copied ${idSet.size} node${idSet.size === 1 ? "" : "s"}`, "info");
    return true;
  }

  function pasteClipboardAt(x, y) {
    const nodeClipboard = getNodeClipboard();
    if (!nodeClipboard?.nodes || typeof nodeClipboard.nodes !== "object") return false;
    if (!currentFlow) {
      ctx.log?.("Create or select a flow first.", "warn");
      return false;
    }
    if (currentFlowIsReadOnly()) {
      ctx.log?.("This workflow is read-only.", "warn");
      return false;
    }
    const sourceNodes = nodeClipboard.nodes;
    const sourceIds = Object.keys(sourceNodes);
    if (!sourceIds.length) return false;
    const nodes = getCurrentNodes();
    const ordered = sourceIds.slice().sort();
    let minX = Infinity;
    let minY = Infinity;
    ordered.forEach((id) => {
      const node = sourceNodes[id] || {};
      minX = Math.min(minX, Number(node.x) || 0);
      minY = Math.min(minY, Number(node.y) || 0);
    });
    const baseX = Number.isFinite(x) ? x : minX;
    const baseY = Number.isFinite(y) ? y : minY;
    const idMap = new Map();
    const newIds = [];
    ordered.forEach((oldId) => {
      const newId = nextNodeId(nodes);
      const original = deepClone(sourceNodes[oldId]);
      original.x = Math.max(0, Math.round(baseX + ((Number(original.x) || 0) - minX)));
      original.y = Math.max(0, Math.round(baseY + ((Number(original.y) || 0) - minY)));
      original.transitions = [];
      nodes[newId] = original;
      idMap.set(oldId, newId);
      newIds.push(newId);
    });
    ordered.forEach((oldId) => {
      const oldNode = sourceNodes[oldId] || {};
      const newNode = nodes[idMap.get(oldId)];
      const transitions = Array.isArray(oldNode.transitions) ? oldNode.transitions : [];
      newNode.transitions = transitions
        .filter((t) => idMap.has(String(t?.target || "")))
        .map((t) => ({ ...deepClone(t), target: idMap.get(String(t?.target || "")) }));
    });
    const flow = ensureFlow(currentFlow);
    if (!flow.start) flow.start = newIds[0] || flow.start;
    renderCanvas();
    setSelectedNodes(newIds, { primary: newIds[0] || "", openPanel: false });
    scheduleSave();
    ctx.log?.(`[agent_flow] pasted ${newIds.length} node${newIds.length === 1 ? "" : "s"}`, "info");
    return true;
  }

  function deleteSelectedNodes(preferredId = "") {
    if (!currentFlow) return;
    if (currentFlowIsReadOnly()) {
      ctx.log?.("This workflow is read-only.", "warn");
      return;
    }
    const ids = selectedIdsList(preferredId);
    if (!ids.length) return;
    const removeSet = new Set(ids);
    const nodes = getCurrentNodes();
    ids.forEach((id) => {
      delete nodes[id];
    });
    Object.values(nodes).forEach((node) => {
      const ts = Array.isArray(node.transitions) ? node.transitions : [];
      node.transitions = ts.filter((t) => !removeSet.has(String(t?.target || "")));
    });
    const flow = ensureFlow(currentFlow);
    if (flow.start && removeSet.has(flow.start)) {
      flow.start = Object.keys(nodes)[0] || null;
    }
    renderCanvas();
    clearProperties();
    scheduleSave();
  }

  function buildNodeContextMenuItems(nodeId, pt, readOnly) {
    const node = getCurrentNodes()[nodeId] || {};
    const isSub = String(node.plugin_id || "").trim() === "agent_flow_subflow";
    const sub = String((node.plugin_settings || {}).subflow_name || "").trim();
    const selectedCount = selectedIdsList(nodeId).length;
    const clipboard = getNodeClipboard();
    const canPaste = Boolean(clipboard?.nodes && Object.keys(clipboard.nodes).length);
    const items = [{ label: "Edit node", onClick: () => selectNode(nodeId, { openPanel: true }) }];
    if (!readOnly) {
      items.unshift({ label: "Add node here", onClick: () => addNodeAt(pt.x + 20, pt.y + 20) });
      items.push({ label: "Paste", disabled: !canPaste, onClick: () => pasteClipboardAt(pt.x + 20, pt.y + 20) });
      items.push({ label: selectedCount > 1 ? "Copy selected" : "Copy", onClick: () => { if (!selectedNodeIds.has(nodeId)) selectNode(nodeId); copySelectedNodes(nodeId); } });
      items.push({ label: selectedCount > 1 ? "Remove selected" : "Remove", onClick: () => { if (!selectedNodeIds.has(nodeId)) selectNode(nodeId); deleteSelectedNodes(nodeId); } });
      items.push({ label: "Start link from node", onClick: () => { selectNode(nodeId); linkSourceId = nodeId; updateHint(); } });
    }
    if (isSub && sub) items.push({ label: "Edit flow", onClick: () => { jumpToSubflowFromNode(nodeId); } });
    return items;
  }

  function renderEdges() {
    svg.innerHTML = "";
    const nodes = getCurrentNodes();
    const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
    const makeMarker = (id, fill) => {
      const marker = document.createElementNS("http://www.w3.org/2000/svg", "marker");
      marker.setAttribute("id", id);
      marker.setAttribute("markerWidth", "14");
      marker.setAttribute("markerHeight", "14");
      marker.setAttribute("refX", "11");
      marker.setAttribute("refY", "4");
      marker.setAttribute("orient", "auto");
      marker.setAttribute("markerUnits", "userSpaceOnUse");
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", "M0,0 L11,4 L0,8 Z");
      path.setAttribute("fill", fill);
      marker.appendChild(path);
      defs.appendChild(marker);
    };
    makeMarker("flow-arrow-normal", "rgba(20,20,20,0.66)");
    makeMarker("flow-arrow-conditional", "rgba(217,119,6,0.95)");
    makeMarker("flow-arrow-loop", "rgba(190,24,93,0.92)");
    svg.appendChild(defs);

    const edges = [];
    Object.keys(nodes).forEach((fromId) => {
      const node = nodes[fromId];
      const transitions = Array.isArray(node.transitions) ? node.transitions : [];
      transitions.forEach((t) => {
        const toId = t?.target;
        if (!toId || !nodes[toId]) return;
        edges.push({ fromId, toId, transition: t });
      });
    });

    const pairTotal = new Map();
    const pairSeen = new Map();
    const directedTotal = new Map();
    const edgeStrokeColor = (isAlways, isLoopback) => {
      if (isLoopback) return "rgba(190,24,93,0.92)";
      if (!isAlways) return "rgba(217,119,6,0.95)";
      return "rgba(20,20,20,0.66)";
    };
    // const addDirectionTracks = (pointsFn, tangentFn, isAlways, isLoopback, approxLen) => {
    //   const color = edgeStrokeColor(isAlways, isLoopback);
    //   const trackCount = 3;
    //   const ts = approxLen > 260 ? [0.14, 0.5, 0.86] : [0.18, 0.5, 0.82];
    //   ts.forEach((tVal) => {
    //     const p = pointsFn(tVal);
    //     const tv = tangentFn(tVal);
    //     const ang = Math.atan2(tv.y, tv.x);
    //     const size = 7.5;
    //     const x1 = p.x - Math.cos(ang) * size;
    //     const y1 = p.y - Math.sin(ang) * size;
    //     const lx = p.x - Math.cos(ang - Math.PI / 2) * (size * 0.8);
    //     const ly = p.y - Math.sin(ang - Math.PI / 2) * (size * 0.8);
    //     const rx = p.x - Math.cos(ang + Math.PI / 2) * (size * 0.8);
    //     const ry = p.y - Math.sin(ang + Math.PI / 2) * (size * 0.8);
    //     const tri = document.createElementNS("http://www.w3.org/2000/svg", "path");
    //     tri.setAttribute("d", `M ${p.x} ${p.y} L ${lx} ${ly} L ${x1} ${y1} L ${rx} ${ry} Z`);
    //     tri.setAttribute("fill", color);
    //     tri.setAttribute("opacity", "1");
    //     svg.appendChild(tri);
    //   });
    // };
    const edgePointAtNodeBoundary = (fromCenter, toCenter) => {
      const dx = toCenter.x - fromCenter.x;
      const dy = toCenter.y - fromCenter.y;
      const len = Math.max(1, Math.hypot(dx, dy));
      const ux = dx / len;
      const uy = dy / len;
      const pad = 6;
      const tx = ux ? (NODE_W / 2 + pad) / Math.abs(ux) : Infinity;
      const ty = uy ? (NODE_H / 2 + pad) / Math.abs(uy) : Infinity;
      const dist = Math.min(tx, ty, len / 2);
      return {
        x: fromCenter.x + ux * dist,
        y: fromCenter.y + uy * dist,
      };
    };

    // const addDirectionTracks = (pointsFn, tangentFn, isAlways, isLoopback, approxLen) => {
    //   const color = edgeStrokeColor(isAlways, isLoopback);
    //   const visibleLen = Math.max(1, approxLen);
    //   const nearDist = Math.min(32, Math.max(14, visibleLen * 0.18));
    //   let t1 = nearDist / visibleLen;
    //   let t2 = 1 - t1;
    //   if (t2 - t1 < 0.28) {
    //     t1 = 0.34;
    //     t2 = 0.66;
    //   }

    //   [t1, t2].forEach((tVal) => {
    //     const p = pointsFn(tVal);
    //     const tv = tangentFn(tVal);
    //     const tLen = Math.max(1, Math.hypot(tv.x, tv.y));
    //     const ux = tv.x / tLen;
    //     const uy = tv.y / tLen;
    //     const px = -uy;
    //     const py = ux;
    //     const size = 8;

    //     const tipX = p.x + ux * size * 0.7;
    //     const tipY = p.y + uy * size * 0.7;
    //     const backX = p.x - ux * size * 0.7;
    //     const backY = p.y - uy * size * 0.7;

    //     const tri = document.createElementNS("http://www.w3.org/2000/svg", "path");
    //     tri.setAttribute(
    //       "d",
    //       `M ${tipX} ${tipY} L ${backX + px * size * 0.62} ${backY + py * size * 0.62} L ${backX - px * size * 0.62} ${backY - py * size * 0.62} Z`
    //     );
    //     tri.setAttribute("fill", color);
    //     tri.setAttribute("opacity", "1");
    //     svg.appendChild(tri);
    //   });
    // };
    const addDirectionTracks = (pointsFn, tangentFn, isAlways, isLoopback, approxLen) => {
      const color = edgeStrokeColor(isAlways, isLoopback);
      const visibleLen = Math.max(1, approxLen);

      const nodeExitDist = Math.hypot(NODE_W / 2, NODE_H / 2) + 10;
      const inset = Math.min(34, Math.max(14, visibleLen * 0.12));

      let t1 = Math.min(0.42, (nodeExitDist + inset) / visibleLen);
      let t2 = Math.max(0.58, 1 - (nodeExitDist + inset) / visibleLen);

      if (t2 - t1 < 0.18) {
        t1 = 0.38;
        t2 = 0.62;
      }

      [t1, t2].forEach((tVal) => {
        const p = pointsFn(tVal);
        const tv = tangentFn(tVal);
        const tLen = Math.max(1, Math.hypot(tv.x, tv.y));
        const ux = tv.x / tLen;
        const uy = tv.y / tLen;
        const px = -uy;
        const py = ux;
        const size = 8;

        const tipX = p.x + ux * size * 0.7;
        const tipY = p.y + uy * size * 0.7;
        const backX = p.x - ux * size * 0.7;
        const backY = p.y - uy * size * 0.7;

        const tri = document.createElementNS("http://www.w3.org/2000/svg", "path");
        tri.setAttribute(
          "d",
          `M ${tipX} ${tipY} L ${backX + px * size * 0.62} ${backY + py * size * 0.62} L ${backX - px * size * 0.62} ${backY - py * size * 0.62} Z`
        );
        tri.setAttribute("fill", color);
        tri.setAttribute("opacity", "1");
        svg.appendChild(tri);
      });
    };
    edges.forEach((e) => {
      const key = [e.fromId, e.toId].sort().join("::");
      pairTotal.set(key, Number(pairTotal.get(key) || 0) + 1);
      const dKey = `${e.fromId}::${e.toId}`;
      directedTotal.set(dKey, Number(directedTotal.get(dKey) || 0) + 1);
    });

    edges.forEach(({ fromId, toId, transition: t }) => {
      const fromPos = nodePosition(fromId);
      const toPos = nodePosition(toId);
      const fromNode = nodes[fromId];
      const toNode = nodes[toId];
      const isLoopback = (toNode?.y ?? 0) <= (fromNode?.y ?? 0) || fromPos.x > toPos.x;
      const isAlways = isAlwaysConditionTree(t?.condition);
      const pairKey = [fromId, toId].sort().join("::");
      const totalInPair = Number(pairTotal.get(pairKey) || 1);
      const seenInPair = Number(pairSeen.get(pairKey) || 0);
      pairSeen.set(pairKey, seenInPair + 1);
      const spacing = 16;
      const laneOffset = (seenInPair - (totalInPair - 1) / 2) * spacing;
      const dx = toPos.x - fromPos.x;
      const dy = toPos.y - fromPos.y;
      const len = Math.max(1, Math.hypot(dx, dy));
      const nx = -dy / len;
      const ny = dx / len;
      const ox = nx * laneOffset;
      const oy = ny * laneOffset;

      // const sx = fromPos.x + ox;
      // const sy = fromPos.y + oy;
      // const ex = toPos.x + ox;
      // const ey = toPos.y + oy;
      const fromEdge = edgePointAtNodeBoundary(fromPos, toPos);
      const toEdge = edgePointAtNodeBoundary(toPos, fromPos);

      // const sx = fromEdge.x + ox;
      // const sy = fromEdge.y + oy;
      // const ex = toEdge.x + ox;
      // const ey = toEdge.y + oy;
      const sx = fromPos.x + ox;
      const sy = fromPos.y + oy;
      const ex = toPos.x + ox;
      const ey = toPos.y + oy;

      const reverseKey = `${toId}::${fromId}`;
      const reverseExists = fromId !== toId && Number(directedTotal.get(reverseKey) || 0) > 0;
      let midX = (sx + ex) / 2;
      let midY = (sy + ey) / 2 - 6;
      if (reverseExists) {
        const curveSign = fromId < toId ? 1 : -1;
        const curveMag = Math.max(22, Math.min(70, len * 0.22));
        const cx = (sx + ex) / 2 + curveSign * Math.max(10, Math.min(24, len * 0.08));
        const cy = (sy + ey) / 2 - curveMag;
        const edgePath = document.createElementNS("http://www.w3.org/2000/svg", "path");
        edgePath.classList.add("flow-edge");
        if (!isAlways) edgePath.classList.add("conditional");
        if (isLoopback) edgePath.classList.add("loopback");
        edgePath.setAttribute("fill", "none");
        edgePath.setAttribute("d", `M ${sx} ${sy} Q ${cx} ${cy} ${ex} ${ey}`);
        svg.appendChild(edgePath);
        addDirectionTracks(
          (tVal) => {
            const omt = 1 - tVal;
            return {
              x: omt * omt * sx + 2 * omt * tVal * cx + tVal * tVal * ex,
              y: omt * omt * sy + 2 * omt * tVal * cy + tVal * tVal * ey,
            };
          },
          (tVal) => ({
            x: 2 * (1 - tVal) * (cx - sx) + 2 * tVal * (ex - cx),
            y: 2 * (1 - tVal) * (cy - sy) + 2 * tVal * (ey - cy),
          }),
          isAlways,
          isLoopback,
          len
        );
        midX = 0.25 * sx + 0.5 * cx + 0.25 * ex;
        midY = 0.25 * sy + 0.5 * cy + 0.25 * ey - 6;
      } else {
        const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
        line.classList.add("flow-edge");
        if (!isAlways) line.classList.add("conditional");
        if (isLoopback) line.classList.add("loopback");
        line.setAttribute("x1", String(sx));
        line.setAttribute("y1", String(sy));
        line.setAttribute("x2", String(ex));
        line.setAttribute("y2", String(ey));
        svg.appendChild(line);
        addDirectionTracks(
          (tVal) => ({ x: sx + (ex - sx) * tVal, y: sy + (ey - sy) * tVal }),
          () => ({ x: ex - sx, y: ey - sy }),
          isAlways,
          isLoopback,
          len
        );
      }

      const labelText = `${transitionConditionLabel(t?.condition)}  ✎`;
      const chip = document.createElementNS("http://www.w3.org/2000/svg", "g");
      chip.classList.add("flow-edge-chip");
      chip.setAttribute("tabindex", "0");
      chip.setAttribute("role", "button");
      const bg = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      bg.classList.add("flow-edge-chip-bg");
      const approxW = Math.max(48, labelText.length * 6.2 + 12);
      bg.setAttribute("x", String(midX - approxW / 2));
      bg.setAttribute("y", String(midY - 11));
      bg.setAttribute("width", String(approxW));
      bg.setAttribute("height", "16");
      chip.appendChild(bg);
      const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
      label.classList.add("flow-edge-label");
      label.setAttribute("x", String(midX));
      label.setAttribute("y", String(midY));
      label.setAttribute("text-anchor", "middle");
      label.textContent = labelText;
      chip.appendChild(label);
      const tip = document.createElementNS("http://www.w3.org/2000/svg", "title");
      tip.textContent = `Edit transition ${fromId} -> ${toId}`;
      chip.appendChild(tip);
      const openEdgeEditor = (event) => {
        event?.preventDefault?.();
        event?.stopPropagation?.();
        selectNode(fromId, { openPanel: true });
        focusNodeInCanvas(fromId);
        hint.textContent = `Editing transition ${fromId} -> ${toId} in the right panel.`;
      };
      chip.addEventListener("click", openEdgeEditor);
      chip.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") openEdgeEditor(event);
      });
      svg.appendChild(chip);
    });
  }
  function nodePosition(nodeId) {
    const node = getCurrentNodes()[nodeId];
    const x = node?.x ?? 80;
    const y = node?.y ?? 80;
    return { x: x + NODE_W / 2, y: y + NODE_H / 2 };
  }

  function renderCanvas() {
    canvasInner.querySelectorAll(".flow-node").forEach((el) => el.remove());
    nodeElements.clear();
    svg.innerHTML = "";
    clearProperties();
    closeContextMenu();
    const nodes = getCurrentNodes();
    let maxX = 0;
    let maxY = 0;
    const nodeIds = Object.keys(nodes);
    nodeIds.forEach((nodeId) => {
      const node = nodes[nodeId];
      const readOnly = currentFlowIsReadOnly();
      if (typeof node.x !== "number") node.x = 80;
      if (typeof node.y !== "number") node.y = 80;
      maxX = Math.max(maxX, node.x + NODE_W + 40);
      maxY = Math.max(maxY, node.y + NODE_H + 40);
      const el = document.createElement("div");
      el.className = "flow-node";
      if (readOnly) el.classList.add("read-only");
      const main = document.createElement("span");
      main.className = "node-main-label";
      main.textContent = node.label || nodeId;
      el.appendChild(main);
      const badge = document.createElement("span");
      badge.className = "node-sub-badge";
      if (String(node.plugin_id || "").trim() === "agent_flow_subflow") {
        badge.textContent = subflowBadgeText(node);
      } else {
        badge.style.display = "none";
      }
      el.appendChild(badge);
      el.style.left = `${node.x}px`;
      el.style.top = `${node.y}px`;
      el.dataset.nodeId = nodeId;
      nodeElements.set(nodeId, el);
      canvasInner.appendChild(el);

      let drag = null;
      let longPress = null;
      let lastNodeTapAt = 0;
      el.addEventListener("pointerdown", (event) => {
        if (event.button !== 0) return;
        event.stopPropagation();
        closeContextMenu();
        if (readOnly) {
          suppressCanvasClick = true;
          selectNode(nodeId);
          return;
        }
        if (!selectedNodeIds.has(nodeId)) {
          suppressCanvasClick = true;
          selectNode(nodeId);
        }
        const pt = canvasPointFromEvent(event);
        longPress = startLongPress(event, () => {
          if (!drag) return;
          drag = null;
          el.classList.remove("dragging");
          openContextMenu(pt.x, pt.y, buildNodeContextMenuItems(nodeId, pt, readOnly));
        });
        drag = {
          id: nodeId,
          startX: event.clientX,
          startY: event.clientY,
          originX: node.x,
          originY: node.y,
          groupIds: selectedNodeIds.has(nodeId) && selectedNodeIds.size > 1
            ? Array.from(selectedNodeIds)
            : [nodeId],
          origins: new Map(),
          moved: false,
        };
        drag.groupIds.forEach((id) => {
          const n = getCurrentNodes()[id];
          if (!n) return;
          drag.origins.set(id, { x: Number(n.x) || 0, y: Number(n.y) || 0 });
        });
        el.classList.add("dragging");
        el.setPointerCapture(event.pointerId);
      });
      el.addEventListener("pointermove", (event) => {
        if (!drag) return;
        if (longPress) {
          longPress.move(event);
          if (longPress.isTriggered()) return;
        }
        const zoom = Number(canvasView.zoom) || 1;
        const dx = (event.clientX - drag.startX) / zoom;
        const dy = (event.clientY - drag.startY) / zoom;
        drag.moved = true;
        drag.groupIds.forEach((id) => {
          const targetNode = getCurrentNodes()[id];
          const origin = drag.origins.get(id);
          const targetEl = nodeElements.get(id);
          if (!targetNode || !origin || !targetEl) return;
          targetNode.x = Math.max(0, origin.x + dx);
          targetNode.y = Math.max(0, origin.y + dy);
          targetEl.style.left = `${targetNode.x}px`;
          targetEl.style.top = `${targetNode.y}px`;
        });
        renderEdges();
      });
      el.addEventListener("pointerup", (event) => {
        if (longPress) {
          const triggered = longPress.isTriggered();
          longPress.cancel();
          longPress = null;
          if (triggered) {
            drag = null;
            el.classList.remove("dragging");
            return;
          }
        }
        if (!drag) return;
        el.classList.remove("dragging");
        if (!drag.moved) {
          if (linkSourceId && linkSourceId !== nodeId) {
            createEdge(linkSourceId, nodeId);
            linkSourceId = "";
            updateHint();
          }
          suppressCanvasClick = true;
          if (event.pointerType === "touch") {
            const now = Date.now();
            if (lastNodeTapAt && now - lastNodeTapAt < 350) {
              lastNodeTapAt = 0;
              selectNode(nodeId);
              focusNodeInCanvas(nodeId);
              drag = null;
              scheduleSave();
              return;
            }
            lastNodeTapAt = now;
          }
          selectNode(nodeId);
        }
        drag = null;
        scheduleSave();
      });
      el.addEventListener("click", (event) => {
        event.stopPropagation();
      });
      el.addEventListener("pointercancel", () => {
        if (longPress) {
          longPress.cancel();
          longPress = null;
        }
        drag = null;
        el.classList.remove("dragging");
      });

      el.addEventListener("dblclick", (event) => {
        event.preventDefault();
        event.stopPropagation();
        selectNode(nodeId);
        focusNodeInCanvas(nodeId);
      });

      el.addEventListener("contextmenu", (event) => {
        event.preventDefault();
        event.stopPropagation();
        const pt = canvasPointFromEvent(event);
        if (!selectedNodeIds.has(nodeId)) {
          selectNode(nodeId);
        }
        openContextMenu(pt.x, pt.y, buildNodeContextMenuItems(nodeId, pt, readOnly));
      });
    });
    if (!nodeIds.length) {
      canvasWrap.style.minHeight = "260px";
      canvasWrap.style.height = "260px";
      canvasInner.style.width = "640px";
      canvasInner.style.height = "420px";
      canvasInner.style.minWidth = "640px";
      canvasInner.style.minHeight = "420px";
      canvas.style.height = "220px";
      canvasLogicalWidth = 640;
      canvasLogicalHeight = 420;
    } else {
      canvasWrap.style.minHeight = "";
      canvasWrap.style.height = "";
      canvas.style.height = "100%";
      canvasLogicalWidth = Math.max(Math.ceil(canvas.clientWidth / (Number(canvasView.zoom) || 1)), maxX, 900);
      canvasLogicalHeight = Math.max(Math.ceil(canvas.clientHeight / (Number(canvasView.zoom) || 1)), maxY, 620);
      canvasInner.style.width = `${canvasLogicalWidth}px`;
      canvasInner.style.height = `${canvasLogicalHeight}px`;
      canvasInner.style.minWidth = `${canvasLogicalWidth}px`;
      canvasInner.style.minHeight = `${canvasLogicalHeight}px`;
    }
    svg.setAttribute("width", canvasLogicalWidth);
    svg.setAttribute("height", canvasLogicalHeight);
    renderEdges();
  }

  function refreshPluginOptions() {
    const select = pluginInputWrap.select;
    select.innerHTML = "";
    pluginIds = resolvePluginIds(enabled, manifest);
    pluginIds.forEach((pid) => {
      const opt = document.createElement("option");
      opt.value = pid;
      opt.textContent = pid;
      select.appendChild(opt);
    });
  }

  function openFlowNameDialog(title, onSave) {
    const createModal = typeof window !== "undefined" ? window.createRouterModal : null;
    if (typeof createModal !== "function") {
      const name = prompt(title || "Flow name:");
      if (name == null) return;
      const trimmed = name.trim();
      if (!trimmed) return;
      onSave(trimmed);
      return;
    }
    const modal = createModal(title || "New flow");
    // Keep dialog above the flow designer overlay/layers.
    if (modal?.overlay?.style) modal.overlay.style.zIndex = "2147483647";
    if (modal?.card?.style) modal.card.style.zIndex = "2147483647";
    const body = modal.body;
    const label = document.createElement("div");
    label.className = "small";
    label.textContent = "Flow name";
    const input = document.createElement("input");
    input.type = "text";
    input.placeholder = "e.g. Sales Funnel";
    body.appendChild(label);
    body.appendChild(input);
    modal.overlay.onSave = () => {
      const trimmed = input.value.trim();
      if (!trimmed) {
        input.focus();
        return false;
      }
      onSave(trimmed);
      return true;
    };
  }

  function normalizeAgentFlowImport(rawText) {
    let obj = rawText;

    if (typeof obj === "string") {
      obj = JSON.parse(obj.trim());
    }

    if (typeof obj === "string") {
      obj = JSON.parse(obj.trim());
    }

    if (!obj || typeof obj !== "object" || Array.isArray(obj)) {
      throw new Error("Agent Flow import must be a JSON object.");
    }

    if (obj.agent_flow && typeof obj.agent_flow === "object") {
      obj = obj.agent_flow;
    }

    if (obj.agent_flow_settings && typeof obj.agent_flow_settings === "object") {
      obj = obj.agent_flow_settings;
    }

    const metadata = obj.metadata && typeof obj.metadata === "object" ? obj.metadata : {};
    const bundleManifest = metadata.bundle_manifest && typeof metadata.bundle_manifest === "object"
      ? metadata.bundle_manifest
      : {};
    const manifestSettings = bundleManifest.agent_flow_settings && typeof bundleManifest.agent_flow_settings === "object"
      ? bundleManifest.agent_flow_settings
      : {};

    const flows =
      obj.flows && typeof obj.flows === "object"
        ? obj.flows
        : obj.agent_flow_flows && typeof obj.agent_flow_flows === "object"
          ? obj.agent_flow_flows
          : null;

    if (!flows || !Object.keys(flows).length) {
      throw new Error("Import JSON must contain a non-empty flows object.");
    }

    const badFlowName = Object.keys(flows).find((name) => {
      const s = String(name || "").trim();
      return s.startsWith("{") || s.startsWith("[") || s.length > 160;
    });

    if (badFlowName) {
      throw new Error("Invalid flow name detected. The whole JSON was probably pasted/imported as a flow name.");
    }

    return {
      flows,
      flow_ids_by_name: normalizeFlowIdMap(obj.flow_ids_by_name || obj.agent_flow_flow_ids_by_name || {}),
      default_flow_ids_by_name: normalizeFlowIdMap(obj.default_flow_ids_by_name || obj.agent_flow_default_flow_ids_by_name || {}),
      root_flow: String(obj.root_flow || manifestSettings.root_flow || "").trim(),
      exported_workflow_id: String(obj.exported_workflow_id || manifestSettings.exported_workflow_id || "").trim(),
      default_flow: String(obj.default_flow || manifestSettings.default_flow || obj.agent_flow_default_flow || Object.keys(flows)[0] || "").trim(),
      active_flow: String(obj.active_flow || manifestSettings.active_flow || obj.agent_flow_active_flow || obj.default_flow || manifestSettings.default_flow || obj.agent_flow_default_flow || Object.keys(flows)[0] || "").trim(),
      mode: String(obj.mode || manifestSettings.mode || obj.agent_flow_mode || "execute").trim(),
      max_steps: Number(obj.max_steps || manifestSettings.max_steps || obj.agent_flow_max_steps || 32),
      loop_max_passes: normalizeLoopMaxSetting(obj.loop_max_passes ?? manifestSettings.loop_max_passes ?? obj.agent_flow_loop_max_passes, 16),
      force_loop_max_passes: normalizeBoolSetting(obj.force_loop_max_passes ?? manifestSettings.force_loop_max_passes ?? obj.agent_flow_force_loop_max_passes, false),
      request_timeout_s: normalizeTimeoutSetting(obj.request_timeout_s ?? manifestSettings.request_timeout_s ?? obj.agent_flow_request_timeout_s, 45),
      autobuild_sandbox_profile: normalizeSandboxProfileSetting(obj.autobuild_sandbox_profile ?? manifestSettings.autobuild_sandbox_profile ?? obj.agent_flow_autobuild_sandbox_profile, "lightweight"),
      autobuild_lightweight_max_requests: Math.max(1, Math.trunc(Number(obj.autobuild_lightweight_max_requests ?? manifestSettings.autobuild_lightweight_max_requests ?? obj.agent_flow_autobuild_lightweight_max_requests ?? 1) || 1)),
      autobuild_lightweight_wait_s: normalizeTimeoutSetting(obj.autobuild_lightweight_wait_s ?? manifestSettings.autobuild_lightweight_wait_s ?? obj.agent_flow_autobuild_lightweight_wait_s, 120),
      autobuild_lightweight_final_grace_s: normalizeTimeoutSetting(obj.autobuild_lightweight_final_grace_s ?? manifestSettings.autobuild_lightweight_final_grace_s ?? obj.agent_flow_autobuild_lightweight_final_grace_s, 10),
      autobuild_independent_max_requests: Math.max(1, Math.trunc(Number(obj.autobuild_independent_max_requests ?? manifestSettings.autobuild_independent_max_requests ?? obj.agent_flow_autobuild_independent_max_requests ?? 3) || 3)),
      autobuild_independent_wait_s: normalizeTimeoutSetting(obj.autobuild_independent_wait_s ?? manifestSettings.autobuild_independent_wait_s ?? obj.agent_flow_autobuild_independent_wait_s, 180),
      autobuild_independent_final_grace_s: normalizeTimeoutSetting(obj.autobuild_independent_final_grace_s ?? manifestSettings.autobuild_independent_final_grace_s ?? obj.agent_flow_autobuild_independent_final_grace_s, 20),
      metadata: obj.metadata || {},
    };
}

  async function importFlowsFromJsonText(rawText, options = {}) {
    const txt = String(rawText || "").trim();
    if (!txt) return;

    const importPayload = normalizeAgentFlowImport(txt);
    // Imports should add/update flows by name by default.  A full replace is dangerous
    // because shared import sources and pasted JSON can otherwise wipe flows that were
    // already present in the designer.  Pass { replace: true } only for an explicit
    // destructive import/reset flow.
    const replaceMode = Boolean(options && options.replace);
    const mergeMode = !replaceMode;
    const freshSettings = getAgentFlowSettings(ctx, sid) || {};
    const settingsFlows = freshSettings.agent_flow_flows && typeof freshSettings.agent_flow_flows === "object"
      ? freshSettings.agent_flow_flows
      : {};
    const existingFlows = deepClone({ ...(settingsFlows || {}), ...(flows || {}) });
    const existingSettings = freshSettings;
    const res = await ctx.apiJson(
      `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/agent_flow/flows/import`,
      {
        method: "POST",
        headers: {
          ...buildHeaders(ctx, pid, sid),
          "X-Gui-Enabled-Plugins": "collab_chat,agent_flow",
        },
        body: { import: importPayload, merge: mergeMode, replace: replaceMode },
      }
    );
    const importedFlows = (res && res.flows && typeof res.flows === "object") ? res.flows : {};
    const importedSettings = (res && res.agent_flow_settings && typeof res.agent_flow_settings === "object")
      ? res.agent_flow_settings
      : {};
    const importedFlowIds = normalizeFlowIdMap(res?.flow_ids_by_name);
    const payloadFlowIds = normalizeFlowIdMap(importPayload.flow_ids_by_name);
    const payloadDefaultFlowIds = normalizeFlowIdMap(importPayload.default_flow_ids_by_name);
    if (!Object.keys(payloadFlowIds).length && importPayload.exported_workflow_id) {
      const rootFlow = String(importPayload.root_flow || importPayload.active_flow || importPayload.default_flow || "").trim();
      if (rootFlow) payloadFlowIds[rootFlow] = String(importPayload.exported_workflow_id || "").trim();
    }
    const mergedFlowIds = mergeMode
      ? { ...getFlowIdMap(existingSettings), ...payloadFlowIds, ...importedFlowIds }
      : { ...payloadFlowIds, ...importedFlowIds };
    const mergedDefaultFlowIds = mergeMode
      ? { ...getDefaultFlowIdMap(existingSettings), ...payloadDefaultFlowIds }
      : { ...payloadDefaultFlowIds };
    flows = mergeMode ? { ...existingFlows, ...deepClone(importedFlows) } : deepClone(importedFlows);
    // Prevent imported nodes from stacking at (80,80) when x/y are missing.
    Object.keys(flows || {}).forEach((fname) => {
      const f = flows[fname];
      if (!f || typeof f !== "object" || !f.nodes || typeof f.nodes !== "object") return;
      const ids = Object.keys(f.nodes);
      ids.forEach((nid, i) => {
        const n = f.nodes[nid];
        if (!n || typeof n !== "object") return;
        if (typeof n.x !== "number") n.x = 80 + (i % 3) * 290;
        if (typeof n.y !== "number") n.y = 80 + Math.floor(i / 3) * 170;
      });
    });
    const merged = {
      ...existingSettings,
      agent_flow_mode: importPayload.mode || existingSettings.agent_flow_mode,
      agent_flow_max_steps: Number(importPayload.max_steps || existingSettings.agent_flow_max_steps || 32),
      agent_flow_loop_max_passes: normalizeLoopMaxSetting(importPayload.loop_max_passes, normalizeLoopMaxSetting(existingSettings.agent_flow_loop_max_passes, 16)),
      agent_flow_force_loop_max_passes: normalizeBoolSetting(importPayload.force_loop_max_passes, normalizeBoolSetting(existingSettings.agent_flow_force_loop_max_passes, false)),
      agent_flow_request_timeout_s: normalizeTimeoutSetting(importPayload.request_timeout_s, normalizeTimeoutSetting(existingSettings.agent_flow_request_timeout_s, 45)),
      agent_flow_autobuild_sandbox_profile: normalizeSandboxProfileSetting(importPayload.autobuild_sandbox_profile, normalizeSandboxProfileSetting(existingSettings.agent_flow_autobuild_sandbox_profile, "lightweight")),
      agent_flow_autobuild_lightweight_max_requests: Math.max(1, Math.trunc(Number(importPayload.autobuild_lightweight_max_requests ?? existingSettings.agent_flow_autobuild_lightweight_max_requests ?? 1) || 1)),
      agent_flow_autobuild_lightweight_wait_s: normalizeTimeoutSetting(importPayload.autobuild_lightweight_wait_s, normalizeTimeoutSetting(existingSettings.agent_flow_autobuild_lightweight_wait_s, 120)),
      agent_flow_autobuild_lightweight_final_grace_s: normalizeTimeoutSetting(importPayload.autobuild_lightweight_final_grace_s, normalizeTimeoutSetting(existingSettings.agent_flow_autobuild_lightweight_final_grace_s, 10)),
      agent_flow_autobuild_independent_max_requests: Math.max(1, Math.trunc(Number(importPayload.autobuild_independent_max_requests ?? existingSettings.agent_flow_autobuild_independent_max_requests ?? 3) || 3)),
      agent_flow_autobuild_independent_wait_s: normalizeTimeoutSetting(importPayload.autobuild_independent_wait_s, normalizeTimeoutSetting(existingSettings.agent_flow_autobuild_independent_wait_s, 180)),
      agent_flow_autobuild_independent_final_grace_s: normalizeTimeoutSetting(importPayload.autobuild_independent_final_grace_s, normalizeTimeoutSetting(existingSettings.agent_flow_autobuild_independent_final_grace_s, 20)),
      ...(importedSettings || {}),
      agent_flow_flows: flows,
      agent_flow_flow_ids_by_name: mergedFlowIds,
      agent_flow_default_flow_ids_by_name: mergedDefaultFlowIds,
    };
    const importedDefaultName = String(importPayload.default_flow || merged.agent_flow_default_flow || "").trim();
    const importedActiveName = String(importPayload.active_flow || merged.agent_flow_active_flow || "").trim();
    if (importedDefaultName) merged.agent_flow_default_workflow_id = String(mergedFlowIds[importedDefaultName] || merged.agent_flow_default_workflow_id || "").trim();
    if (importedActiveName && importedActiveName !== NO_FLOW_VALUE) merged.agent_flow_active_workflow_id = String(mergedFlowIds[importedActiveName] || merged.agent_flow_active_workflow_id || "").trim();
    setRouterSettings(ctx, sid, "agent_flow", merged);
    const requestedDefault = String(merged.agent_flow_default_flow || "").trim();
    const requestedActive = String(merged.agent_flow_active_flow || "").trim();
    defaultFlow = requestedDefault && flows[requestedDefault]
      ? requestedDefault
      : String(existingSettings.agent_flow_default_flow || "").trim();
    activeFlow = requestedActive && (requestedActive === NO_FLOW_VALUE || flows[requestedActive])
      ? requestedActive
      : String(existingSettings.agent_flow_active_flow || "").trim();
    if (!defaultFlow || !flows[defaultFlow]) defaultFlow = Object.keys(importedFlows)[0] || Object.keys(flows)[0] || "";
    if (!activeFlow || (activeFlow !== NO_FLOW_VALUE && !flows[activeFlow])) activeFlow = Object.keys(importedFlows)[0] || defaultFlow || "";
    currentFlow = activeFlow && activeFlow !== NO_FLOW_VALUE ? activeFlow : (Object.keys(flows)[0] || "");
    activeInput.value = currentFlow;
    refreshFlowList();
    updateDefaultLabel();
    updateActivePanel();
    renderCanvas();
    updateBottomBar(ctx);
    ctx.log?.(mergeMode ? "[agent_flow] merged imported flows JSON" : "[agent_flow] imported flows JSON", "info");
  }

  function closeImportPopover() {
    if (!importPopover) return;
    importPopover.remove();
    importPopover = null;
  }

  function setAwfLibraryLaunchLoading(loading) {
    awfLibraryLaunchLoading = Boolean(loading);
    const wrap = awfLibraryButtonNode && awfLibraryButtonNode.parentElement ? awfLibraryButtonNode.parentElement : null;
    const indicator = wrap ? wrap.querySelector(".agent-flow-awf-launch-indicator") : null;
    if (indicator) indicator.hidden = !awfLibraryLaunchLoading;
    if (awfLibraryButtonNode) awfLibraryButtonNode.setAttribute("aria-busy", awfLibraryLaunchLoading ? "true" : "false");
  }

  function closeAwfLibraryPopover() {
    if (!awfLibraryPopover) return;
    if (awfLibraryPopover._refreshTimer) clearTimeout(awfLibraryPopover._refreshTimer);
    if (awfLibrarySearchTimer) clearTimeout(awfLibrarySearchTimer);
    awfLibraryPopover.remove();
    awfLibraryPopover = null;
  }

  function triggerDownloadUrl(url) {
    let href = String(url || "").trim();
    if (!href) return;
    if (!/^https?:\/\//i.test(href) && href.startsWith("/")) {
      const base = String(ctx?.state?.remote?.serverUrl || window.location.origin || "").replace(/\/+$/, "");
      if (base) href = `${base}${href}`;
    }
    const a = document.createElement("a");
    a.href = href;
    a.target = "_blank";
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  async function importAwfBundleFile(file) {
    const upload = file instanceof Blob ? file : null;
    if (!upload) throw new Error("Bundle file is required.");
    const form = new FormData();
    form.append("file", upload, String(file?.name || "agent_flow_bundle.zip"));
    const res = await fetch(
      `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/agent_flow/temp_library/import_bundle`,
      {
        method: "POST",
        headers: {
          ...buildHeaders(ctx, pid, sid),
          "X-Gui-Enabled-Plugins": "collab_chat,agent_flow",
        },
        body: form,
      }
    );
    let data = null;
    try {
      data = await res.json();
    } catch (_) {
      data = null;
    }
    if (!res.ok || !data?.ok) {
      throw new Error(String(data?.detail || data?.error || `bundle import failed (${res.status})`));
    }
    return data;
  }

  async function fetchAwfLibraryRecords(options = {}) {
    const nextQuery = options.query !== undefined ? String(options.query || "") : String(awfLibraryState.query || "");
    const nextPageSize = Math.max(1, Number(options.pageSize || awfLibraryState.pageSize || 12));
    const nextPage = Math.max(1, Number(options.page || awfLibraryState.page || 1));
    const qs = new URLSearchParams({
      page: String(nextPage),
      page_size: String(nextPageSize),
    });
    if (nextQuery.trim()) qs.set("q", nextQuery.trim());
    const seq = ++awfLibraryFetchSeq;
    const res = await ctx.apiJson(
      `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/agent_flow/temp_library?${qs.toString()}`,
      {
        headers: {
          ...buildHeaders(ctx, pid, sid),
          "X-Gui-Enabled-Plugins": "collab_chat,agent_flow",
        },
      }
    );
    const records = Array.isArray(res?.records) ? res.records : [];
    const payload = {
      records,
      query: String(res?.query ?? nextQuery ?? ""),
      draftQuery: options.query !== undefined ? String(options.query || "") : String(awfLibraryState.draftQuery || res?.query || nextQuery || ""),
      page: Math.max(1, Number(res?.page || nextPage || 1)),
      pageSize: Math.max(1, Number(res?.page_size || nextPageSize || 12)),
      total: Math.max(0, Number(res?.total || records.length || 0)),
      totalPages: Math.max(1, Number(res?.total_pages || 1)),
      hiddenCount: Math.max(0, Number(res?.hidden_count || 0)),
    };
    if (seq === awfLibraryFetchSeq) {
      awfLibraryState = {
        query: payload.query,
        draftQuery: payload.draftQuery,
        page: payload.page,
        pageSize: payload.pageSize,
        total: payload.total,
        totalPages: payload.totalPages,
        hiddenCount: payload.hiddenCount,
        records: payload.records,
      };
    }
    return payload;
  }

  async function exportAwfLibraryRecord(recordId, kind) {
    const action = kind === "bundle" ? "export_bundle" : "export_workflow";
    const res = await ctx.apiJson(
      `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/agent_flow/temp_library/${encodeURIComponent(recordId)}/${action}`,
      {
        method: "POST",
        headers: {
          ...buildHeaders(ctx, pid, sid),
          "X-Gui-Enabled-Plugins": "collab_chat,agent_flow",
        },
      }
    );
    const url = String(res?.download_url || res?.file?.download_url || res?.zip?.download_url || "").trim();
    if (url) triggerDownloadUrl(url);
    return res;
  }

  async function exportCurrentFlowArtifact(kind) {
    const flowName = String(currentFlow || activeInput.value || "").trim();
    if (!flowName) throw new Error("Select a flow first.");
    const flowDoc = flows && typeof flows === "object" ? flows[flowName] : null;
    if (!flowDoc || typeof flowDoc !== "object") throw new Error(`Flow not found: ${flowName}`);
    const freshSettings = getAgentFlowSettings(ctx, sid) || {};
    const rawActive = String(freshSettings.agent_flow_active_flow || "").trim();
    const resolvedActive = rawActive === NO_FLOW_VALUE ? NO_FLOW_VALUE : (resolveActiveFlowName(freshSettings, flows) || "");
    const exportSettings = {
      default_flow: String(defaultFlow || freshSettings.agent_flow_default_flow || flowName).trim() || flowName,
      active_flow: resolvedActive || flowName,
      mode: String(freshSettings.agent_flow_mode || "execute").trim() || "execute",
      max_steps: Number(freshSettings.agent_flow_max_steps || 32),
      loop_max_passes: normalizeLoopMaxSetting(freshSettings.agent_flow_loop_max_passes, 16),
      force_loop_max_passes: normalizeBoolSetting(freshSettings.agent_flow_force_loop_max_passes, false),
      request_timeout_s: normalizeTimeoutSetting(freshSettings.agent_flow_request_timeout_s, 45),
      autobuild_sandbox_profile: normalizeSandboxProfileSetting(freshSettings.agent_flow_autobuild_sandbox_profile, "lightweight"),
      autobuild_lightweight_max_requests: Math.max(1, Math.trunc(Number(freshSettings.agent_flow_autobuild_lightweight_max_requests ?? 1) || 1)),
      autobuild_lightweight_wait_s: normalizeTimeoutSetting(freshSettings.agent_flow_autobuild_lightweight_wait_s, 120),
      autobuild_lightweight_final_grace_s: normalizeTimeoutSetting(freshSettings.agent_flow_autobuild_lightweight_final_grace_s, 10),
      autobuild_independent_max_requests: Math.max(1, Math.trunc(Number(freshSettings.agent_flow_autobuild_independent_max_requests ?? 3) || 3)),
      autobuild_independent_wait_s: normalizeTimeoutSetting(freshSettings.agent_flow_autobuild_independent_wait_s, 180),
      autobuild_independent_final_grace_s: normalizeTimeoutSetting(freshSettings.agent_flow_autobuild_independent_final_grace_s, 20),
    };
    const action = kind === "bundle" ? "export_bundle" : "export_workflow";
    const res = await ctx.apiJson(
      `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/agent_flow/flows/${action}`,
      {
        method: "POST",
        headers: {
          ...buildHeaders(ctx, pid, sid),
          "X-Gui-Enabled-Plugins": "collab_chat,agent_flow",
        },
        body: {
          flow_name: flowName,
          workflow_json: flowDoc,
          export_settings: exportSettings,
        },
      }
    );
    const url = String(res?.download_url || res?.file?.download_url || res?.zip?.download_url || "").trim();
    if (url) triggerDownloadUrl(url);
    return res;
  }

  async function deleteAwfLibraryRecord(recordId) {
    return await ctx.apiJson(
      `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/agent_flow/temp_library/${encodeURIComponent(recordId)}`,
      {
        method: "DELETE",
        headers: {
          ...buildHeaders(ctx, pid, sid),
          "X-Gui-Enabled-Plugins": "collab_chat,agent_flow",
        },
      }
    );
  }

  async function postAwfLibraryAction(recordId, action) {
    return await ctx.apiJson(
      `/v1/projects/${encodeURIComponent(pid)}/sessions/${encodeURIComponent(sid)}/agent_flow/temp_library/${encodeURIComponent(recordId)}/${action}`,
      {
        method: "POST",
        headers: {
          ...buildHeaders(ctx, pid, sid),
          "X-Gui-Enabled-Plugins": "collab_chat,agent_flow",
        },
      }
    );
  }

  async function validateAwfLibraryRecord(record) {
    const recordId = String(record?.id || "").trim();
    if (!recordId) return null;
    return await postAwfLibraryAction(recordId, "validate");
  }

  async function installAwfLibraryRecord(record) {
    const recordId = String(record?.id || "").trim();
    if (!recordId) return null;
    return await postAwfLibraryAction(recordId, "install");
  }

  async function uninstallAwfLibraryRecord(record) {
    const recordId = String(record?.id || "").trim();
    if (!recordId) return null;
    return await postAwfLibraryAction(recordId, "uninstall");
  }

  async function refreshAwfLibraryView(options = {}, behavior = {}) {
    const nextPayload = {
      records: Array.isArray(behavior.keepRecords ? awfLibraryState.records : []) ? (behavior.keepRecords ? awfLibraryState.records : []) : [],
      query: options.query !== undefined ? String(options.query || "") : String(awfLibraryState.query || ""),
      draftQuery: options.query !== undefined ? String(options.query || "") : String(awfLibraryState.draftQuery || awfLibraryState.query || ""),
      page: Math.max(1, Number(options.page || awfLibraryState.page || 1)),
      pageSize: Math.max(1, Number(options.pageSize || awfLibraryState.pageSize || 12)),
      total: awfLibraryState.total || 0,
      totalPages: awfLibraryState.totalPages || 1,
      hiddenCount: awfLibraryState.hiddenCount || 0,
      loading: true,
    };
    awfLibraryLoading = true;
    if (awfLibraryPopover) renderAwfLibraryPopover(nextPayload);
    try {
      const payload = await fetchAwfLibraryRecords(options);
      awfLibraryLoading = false;
      if (awfLibraryPopover) renderAwfLibraryPopover(payload);
      if ((payload.records || []).some((row) => Boolean(row?.validation_pending))) startAwfLibraryRefreshLoop();
      return payload;
    } catch (err) {
      awfLibraryLoading = false;
      if (awfLibraryPopover) renderAwfLibraryPopover({ ...awfLibraryState, loading: false });
      throw err;
    }
  }

  function startAwfLibraryRefreshLoop() {
    if (!awfLibraryPopover) return;
    if (awfLibraryPopover._refreshTimer) clearTimeout(awfLibraryPopover._refreshTimer);
    awfLibraryPopover._refreshTimer = setTimeout(async () => {
      if (!awfLibraryPopover) return;
      try {
        const payload = await fetchAwfLibraryRecords();
        renderAwfLibraryPopover(payload);
        if ((payload.records || []).some((row) => Boolean(row?.validation_pending))) {
          startAwfLibraryRefreshLoop();
        }
      } catch (err) {
        ctx.log?.(`[agent_flow] AWF library refresh loop failed: ${err?.message || err}`, "warn");
      }
    }, 2500);
  }

  function renderAwfLibraryPopover(payload) {
    if (!awfLibraryPopover) return;
    const data = Array.isArray(payload)
      ? { records: payload }
      : payload && typeof payload === "object"
        ? payload
        : {};
    const records = Array.isArray(data.records) ? data.records : [];
    const total = Math.max(0, Number(data.total ?? awfLibraryState.total ?? records.length ?? 0));
    const page = Math.max(1, Number(data.page ?? awfLibraryState.page ?? 1));
    const pageSize = Math.max(1, Number(data.pageSize ?? data.page_size ?? awfLibraryState.pageSize ?? 12));
    const totalPages = Math.max(1, Number(data.totalPages ?? data.total_pages ?? awfLibraryState.totalPages ?? 1));
    const hiddenCount = Math.max(0, Number(data.hiddenCount ?? data.hidden_count ?? awfLibraryState.hiddenCount ?? 0));
    const query = String(data.query ?? awfLibraryState.query ?? "");
    const draftQuery = String(data.draftQuery ?? awfLibraryState.draftQuery ?? query);
    const loading = Boolean(data.loading ?? awfLibraryLoading);
    const activeEl = document.activeElement;
    const restoreSearchFocus = Boolean(activeEl && awfLibraryPopover.contains(activeEl) && activeEl.getAttribute && activeEl.getAttribute("type") === "search");
    const restoreSelectionStart = restoreSearchFocus && typeof activeEl.selectionStart === "number" ? activeEl.selectionStart : null;
    const restoreSelectionEnd = restoreSearchFocus && typeof activeEl.selectionEnd === "number" ? activeEl.selectionEnd : null;
    awfLibraryState = { query, draftQuery, page, pageSize, total, totalPages, hiddenCount, records };

    awfLibraryPopover.innerHTML = "";
    const head = document.createElement("div");
    head.className = "agent-flow-awf-head";
    const titleWrap = document.createElement("div");
    titleWrap.className = "agent-flow-awf-title-wrap";
    const title = document.createElement("div");
    title.className = "agent-flow-awf-title";
    title.textContent = "Auto Workflow Library";
    titleWrap.appendChild(title);
    if (loading) {
      const loadingBadge = document.createElement("div");
      loadingBadge.className = "agent-flow-awf-loading-badge";
      const badgeSpinner = document.createElement("div");
      badgeSpinner.className = "agent-flow-awf-spinner";
      badgeSpinner.setAttribute("aria-hidden", "true");
      loadingBadge.appendChild(badgeSpinner);
      const badgeText = document.createElement("div");
      badgeText.textContent = "Loading";
      loadingBadge.appendChild(badgeText);
      titleWrap.appendChild(loadingBadge);
    }
    head.appendChild(titleWrap);
    const headActions = document.createElement("div");
    headActions.className = "agent-flow-awf-actions";
    const refreshBtn = document.createElement("button");
    refreshBtn.className = "ghost";
    refreshBtn.textContent = "Refresh";
    refreshBtn.addEventListener("click", async () => {
      try {
        await refreshAwfLibraryView({}, { keepRecords: true });
      } catch (err) {
        ctx.log?.(`[agent_flow] AWF library refresh failed: ${err?.message || err}`, "warn");
      }
    });
    headActions.appendChild(refreshBtn);
    const closeBtn = document.createElement("button");
    closeBtn.className = "ghost";
    closeBtn.textContent = "Close";
    closeBtn.addEventListener("click", () => closeAwfLibraryPopover());
    headActions.appendChild(closeBtn);
    head.appendChild(headActions);
    awfLibraryPopover.appendChild(head);

    const toolbar = document.createElement("div");
    toolbar.className = "agent-flow-awf-toolbar";
    const searchWrap = document.createElement("div");
    searchWrap.className = "agent-flow-awf-search";
    const searchInput = document.createElement("input");
    searchInput.type = "search";
    searchInput.className = "agent-flow-popover-search";
    searchInput.placeholder = "Search workflows";
    searchInput.value = draftQuery;
    const runSearch = async () => {
      const nextQuery = String(searchInput.value || "");
      awfLibraryState.draftQuery = nextQuery;
      if (nextQuery === awfLibraryState.query) return;
      try {
        await refreshAwfLibraryView({ query: nextQuery, page: 1 }, { keepRecords: true });
      } catch (err) {
        ctx.log?.(`[agent_flow] AWF library search failed: ${err?.message || err}`, "warn");
      }
    };
    searchInput.addEventListener("input", () => {
      awfLibraryState.draftQuery = String(searchInput.value || "");
      if (awfLibrarySearchTimer) clearTimeout(awfLibrarySearchTimer);
      awfLibrarySearchTimer = setTimeout(() => {
        void runSearch();
      }, 480);
    });
    searchInput.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      if (awfLibrarySearchTimer) clearTimeout(awfLibrarySearchTimer);
      void runSearch();
    });
    searchWrap.appendChild(searchInput);
    toolbar.appendChild(searchWrap);

    const createPager = (options = {}) => {
      const pager = document.createElement("div");
      pager.className = `agent-flow-awf-pager${options.bottom ? " agent-flow-awf-pager-bottom" : ""}`;
      if (!options.bottom) {
        const status = document.createElement("div");
        status.className = "agent-flow-awf-status";
        status.textContent = loading
          ? "Loading workflows..."
          : total
            ? `${total} workflow${total === 1 ? "" : "s"}${hiddenCount ? ` | ${hiddenCount} hidden` : ""}`
            : hiddenCount
              ? `0 workflows | ${hiddenCount} hidden`
              : "0 workflows";
        pager.appendChild(status);
      }
      const prevBtn = document.createElement("button");
      prevBtn.className = "ghost";
      prevBtn.textContent = "Prev";
      prevBtn.disabled = page <= 1;
      prevBtn.addEventListener("click", async () => {
        if (page <= 1) return;
        try {
          await refreshAwfLibraryView({ page: page - 1 }, { keepRecords: true });
        } catch (err) {
          ctx.log?.(`[agent_flow] AWF library pagination failed: ${err?.message || err}`, "warn");
        }
      });
      pager.appendChild(prevBtn);
      const pageLabel = document.createElement("div");
      pageLabel.className = "agent-flow-awf-page";
      pageLabel.textContent = `Page ${page} / ${Math.max(1, totalPages)}`;
      pager.appendChild(pageLabel);
      const nextBtn = document.createElement("button");
      nextBtn.className = "ghost";
      nextBtn.textContent = "Next";
      nextBtn.disabled = page >= totalPages;
      nextBtn.addEventListener("click", async () => {
        if (page >= totalPages) return;
        try {
          await refreshAwfLibraryView({ page: page + 1 }, { keepRecords: true });
        } catch (err) {
          ctx.log?.(`[agent_flow] AWF library pagination failed: ${err?.message || err}`, "warn");
        }
      });
      pager.appendChild(nextBtn);
      return pager;
    };
    toolbar.appendChild(createPager());
    awfLibraryPopover.appendChild(toolbar);
    if (restoreSearchFocus) {
      requestAnimationFrame(() => {
        if (!awfLibraryPopover || !searchInput.isConnected) return;
        searchInput.focus({ preventScroll: true });
        const start = restoreSelectionStart == null ? searchInput.value.length : Math.min(restoreSelectionStart, searchInput.value.length);
        const end = restoreSelectionEnd == null ? start : Math.min(restoreSelectionEnd, searchInput.value.length);
        try {
          searchInput.setSelectionRange(start, end);
        } catch {}
      });
    }

    const list = document.createElement("div");
    list.className = "agent-flow-awf-list";
    const formatAwfScore = (value) => {
      const num = Number(value);
      return Number.isFinite(num) ? num.toFixed(2) : "--";
    };
    const awfValidationScore = (record) => {
      const passCount = Number(record?.pass_count || 0);
      const failCount = Number(record?.fail_count || 0);
      const total = passCount + failCount;
      if (!Number.isFinite(total) || total <= 0) return "--";
      return formatAwfScore(passCount / total);
    };
    if (loading) {
      const loadingRow = document.createElement("div");
      loadingRow.className = "agent-flow-awf-loading";
      const spinner = document.createElement("div");
      spinner.className = "agent-flow-awf-spinner";
      spinner.setAttribute("aria-hidden", "true");
      loadingRow.appendChild(spinner);
      const label = document.createElement("div");
      label.textContent = "Loading Auto Workflow Library...";
      loadingRow.appendChild(label);
      list.appendChild(loadingRow);
    } else if (!records.length) {
      const empty = document.createElement("div");
      empty.className = "agent-flow-awf-empty";
      empty.textContent = query ? "No workflows matched your search." : "No temp workflows are currently stored.";
      list.appendChild(empty);
    } else {
      records.forEach((record) => {
        const recordId = String(record?.id || "").trim();
        const card = document.createElement("div");
        card.className = "agent-flow-awf-item";

        const rowTop = document.createElement("div");
        rowTop.className = "agent-flow-awf-row";
        const name = document.createElement("div");
        name.className = "agent-flow-awf-name";
        const flowName = String(record?.flow_name || recordId || "Workflow");
        const validated = Boolean(record?.validated);
        const validationPending = Boolean(record?.validation_pending);
        const installed = Boolean(record?.installed);
        name.textContent = `${validationPending ? "[...] " : validated ? "[ok] " : ""}${flowName}`;
        rowTop.appendChild(name);
        const stamp = document.createElement("div");
        stamp.className = "agent-flow-awf-sub";
        const updatedTs = Number(record?.updated_ts || 0);
        stamp.textContent = updatedTs ? `Updated ${new Date(updatedTs * 1000).toLocaleString()}` : "";
        rowTop.appendChild(stamp);
        card.appendChild(rowTop);

        const desc = document.createElement("div");
        desc.className = "agent-flow-awf-sub";
        desc.textContent = String(record?.description || record?.summary || record?.source_request || "").trim() || "No description.";
        card.appendChild(desc);

        const stateLine = document.createElement("div");
        stateLine.className = "agent-flow-awf-sub";
        const validationStatus = validationPending
          ? "Validation running"
          : validated
            ? "Validated"
            : String(record?.last_validation_status || "").trim()
              ? `Validation: ${String(record?.last_validation_status || "").trim()}`
              : "Not validated";
        const installStatus = installed ? "Installed" : "Not installed";
        stateLine.textContent = `${validationStatus} | ${installStatus}`;
        card.appendChild(stateLine);

        const latestUpdateStatus = String(record?.latest_update_status || "").trim();
        const latestUpdateReason = String(record?.latest_update_reason || "").trim();
        const latestKnowledgebaseSummary = String(record?.latest_knowledgebase_summary || "").trim();
        if (latestUpdateStatus || latestKnowledgebaseSummary) {
          const fixLine = document.createElement("div");
          fixLine.className = "agent-flow-awf-sub";
          const fixLabel = latestUpdateStatus && latestUpdateStatus !== "--"
            ? `Latest fix: ${latestUpdateStatus}${latestUpdateReason ? ` (${latestUpdateReason})` : ""}`
            : "Latest fix info available";
          fixLine.textContent = fixLabel;
          if (latestKnowledgebaseSummary) {
            fixLine.title = latestKnowledgebaseSummary;
          }
          card.appendChild(fixLine);
          if (latestKnowledgebaseSummary) {
            const kbLine = document.createElement("div");
            kbLine.className = "agent-flow-awf-sub";
            const kbCompact = latestKnowledgebaseSummary
              .split(/\r?\n/)
              .map((line) => String(line || "").trim())
              .filter(Boolean)
              .slice(0, 2)
              .join(" ");
            kbLine.textContent = kbCompact || "Knowledgebase summary available.";
            kbLine.title = latestKnowledgebaseSummary;
            card.appendChild(kbLine);
          }
        }

        const scoreLine = document.createElement("div");
        scoreLine.className = "agent-flow-awf-sub";
        const matchScore =
          record?.match_score ?? record?.record_score ?? record?.selection_score ?? record?.score;
        const userScore = record?.user_satisfaction_score;
        scoreLine.textContent = `Scores: match ${formatAwfScore(matchScore)} | validation ${awfValidationScore(record)} | user ${formatAwfScore(userScore)}`;
        card.appendChild(scoreLine);

        const path = document.createElement("div");
        path.className = "agent-flow-awf-sub";
        path.textContent = `Bundle: ${String(record?.bundle_dir || "").trim()}`;
        card.appendChild(path);

        const actionsRow = document.createElement("div");
        actionsRow.className = "agent-flow-awf-row";
        const actions = document.createElement("div");
        actions.className = "agent-flow-awf-actions";
        const mkBtn = (label, handler) => {
          const btn = document.createElement("button");
          btn.className = "ghost";
          btn.textContent = label;
          btn.addEventListener("click", handler);
          return btn;
        };
        actions.appendChild(mkBtn("Export JSON", async () => {
          try {
            await exportAwfLibraryRecord(recordId, "workflow");
          } catch (err) {
            ctx.log?.(`[agent_flow] AWF export JSON failed: ${err?.message || err}`, "warn");
          }
        }));
        actions.appendChild(mkBtn("Export Bundle", async () => {
          try {
            await exportAwfLibraryRecord(recordId, "bundle");
          } catch (err) {
            ctx.log?.(`[agent_flow] AWF export bundle failed: ${err?.message || err}`, "warn");
          }
        }));
        actions.appendChild(mkBtn("Validate", async () => {
          try {
            const res = await validateAwfLibraryRecord(record);
            if (res?.ok) {
              ctx.log?.(`[agent_flow] started validator for ${record?.flow_name || recordId}`, "info");
              renderAwfLibraryPopover(await fetchAwfLibraryRecords());
              startAwfLibraryRefreshLoop();
            }
          } catch (err) {
            ctx.log?.(`[agent_flow] AWF validate failed: ${err?.message || err}`, "warn");
          }
        }));
        actions.appendChild(mkBtn(installed ? "Uninstall" : "Install", async () => {
          try {
            if (installed) {
              await uninstallAwfLibraryRecord(record);
            } else {
              await installAwfLibraryRecord(record);
            }
            try {
              const serverPayload = await fetchProjectFlows(ctx, pid, sid);
              const serverFlows = serverPayload?.flows;
              if (serverFlows && typeof serverFlows === "object") {
                const settings = getAgentFlowSettings(ctx, sid);
                setRouterSettings(ctx, sid, "agent_flow", {
                  ...(settings || {}),
                  agent_flow_flows: deepClone(serverFlows),
                  agent_flow_flow_ids_by_name: normalizeFlowIdMap(serverPayload?.flowIdsByName),
                  agent_flow_default_flow_ids_by_name: normalizeFlowIdMap(serverPayload?.defaultFlowIdsByName),
                });
              }
            } catch (err2) {
              ctx.log?.(`[agent_flow] AWF flow refresh failed: ${err2?.message || err2}`, "warn");
            }
            renderAwfLibraryPopover(await fetchAwfLibraryRecords());
          } catch (err) {
            ctx.log?.(`[agent_flow] AWF ${installed ? "uninstall" : "install"} failed: ${err?.message || err}`, "warn");
          }
        }));
        actions.appendChild(mkBtn("Remove", async () => {
          if (!confirm(`Remove ${record?.flow_name || recordId} from the temp library?`)) return;
          try {
            await deleteAwfLibraryRecord(recordId);
            renderAwfLibraryPopover(await fetchAwfLibraryRecords());
          } catch (err) {
            ctx.log?.(`[agent_flow] AWF remove failed: ${err?.message || err}`, "warn");
          }
        }));
        actionsRow.appendChild(actions);
        card.appendChild(actionsRow);
        list.appendChild(card);
      });
    }
    awfLibraryPopover.appendChild(list);
    awfLibraryPopover.appendChild(createPager({ bottom: true }));
  }

  async function openAwfLibraryPopover(anchor) {
    setAwfLibraryLaunchLoading(true);
    try {
      closeAwfLibraryPopover();
      awfLibraryPopover = document.createElement("div");
      awfLibraryPopover.className = "agent-flow-awf-popover";
      document.body.appendChild(awfLibraryPopover);
      renderAwfLibraryPopover({ records: awfLibraryState.records || [], loading: true });
      const rect = anchor.getBoundingClientRect();
      const width = awfLibraryPopover.offsetWidth || 640;
      const height = awfLibraryPopover.offsetHeight || 360;
      const gutter = window.innerWidth <= 720 ? 8 : 12;
      const left = Math.max(gutter, Math.min(rect.right - width, window.innerWidth - width - gutter));
      const top = Math.max(gutter, Math.min(rect.bottom + 8, window.innerHeight - height - gutter));
      awfLibraryPopover.style.left = `${left}px`;
      awfLibraryPopover.style.top = `${top}px`;
      await refreshAwfLibraryView({ page: awfLibraryState.page || 1, query: awfLibraryState.query || "" }, { keepRecords: true });
    } finally {
      setAwfLibraryLaunchLoading(false);
    }
  }

  async function getImportEntries() {
    const entries = [
      {
        id: "json",
        title: "Import JSON",
        description: "Paste agent_flow JSON into the designer.",
        // render(node) {
        //   const row = document.createElement("div");
        //   row.className = "button-row";
        //   const btn = document.createElement("button");
        //   btn.className = "ghost";
        //   btn.textContent = "Paste JSON";
        //   btn.addEventListener("click", async () => {
        //     const raw = prompt("Paste agent_flow JSON (supports {flows,...} or {agent_flow:{...}}):");
        //     if (raw == null) return;
        //     try {
        //       await importFlowsFromJsonText(raw, { merge: true });
        //       closeImportPopover();
        //     } catch (err) {
        //       ctx.log?.(`[agent_flow] import JSON failed: ${err?.message || err}`, "warn");
        //     }
        //   });
        //   row.appendChild(btn);
        //   node.appendChild(row);
        // },

        render(node) {
          const field = document.createElement("label");
          field.className = "field";
          field.innerHTML = "<span>Paste Agent Flow JSON</span>";

          const box = document.createElement("textarea");
          box.placeholder = "Paste full Agent Flow import JSON here...";
          box.spellcheck = false;
          box.style.minHeight = "260px";
          box.style.width = "100%";
          box.style.resize = "vertical";
          box.style.fontFamily = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";
          box.style.fontSize = "12px";

          field.appendChild(box);
          node.appendChild(field);

          const row = document.createElement("div");
          row.className = "button-row";

          const btn = document.createElement("button");
          btn.className = "ghost";
          btn.textContent = "Import JSON";

          btn.addEventListener("click", async () => {
            const raw = String(box.value || "").trim();
            if (!raw) {
              ctx.log?.("[agent_flow] paste JSON before importing.", "warn");
              return;
            }

            try {
              await importFlowsFromJsonText(raw, { merge: true });
              closeImportPopover();
            } catch (err) {
              ctx.log?.(`[agent_flow] import JSON failed: ${err?.message || err}`, "warn");
            }
          });

          row.appendChild(btn);
          node.appendChild(row);
        },
      },
      {
        id: "bundle",
        title: "Import Bundle",
        description: "Upload an exported workflow bundle zip into Auto Workflow Library.",
        render(node) {
          const field = document.createElement("label");
          field.className = "field";
          field.innerHTML = "<span>Workflow bundle zip</span>";
          const input = document.createElement("input");
          input.type = "file";
          input.accept = ".zip,application/zip";
          field.appendChild(input);
          node.appendChild(field);

          const row = document.createElement("div");
          row.className = "button-row";
          const btn = document.createElement("button");
          btn.className = "ghost";
          btn.textContent = "Upload Bundle";
          btn.addEventListener("click", async () => {
            const file = input.files && input.files[0] ? input.files[0] : null;
            if (!file) {
              ctx.log?.("[agent_flow] choose a bundle zip before importing.", "warn");
              return;
            }
            try {
              btn.disabled = true;
              const out = await importAwfBundleFile(file);
              const names = Array.isArray(out?.flow_names) ? out.flow_names.filter(Boolean) : [];
              ctx.log?.(
                `[agent_flow] imported bundle to Auto Workflow Library${names.length ? `: ${names.join(", ")}` : ""}`,
                "info"
              );
              closeImportPopover();
              if (awfLibraryButtonNode) await openAwfLibraryPopover(awfLibraryButtonNode);
            } catch (err) {
              ctx.log?.(`[agent_flow] bundle import failed: ${err?.message || err}`, "warn");
            } finally {
              btn.disabled = false;
            }
          });
          row.appendChild(btn);
          node.appendChild(row);
        },
      },
      {
        id: "export-json",
        title: "Export JSON",
        description: "Download only the selected workflow as Agent Flow JSON.",
        render(node) {
          const row = document.createElement("div");
          row.className = "button-row";
          const btn = document.createElement("button");
          btn.className = "ghost";
          btn.textContent = "Export Selected JSON";
          btn.addEventListener("click", async () => {
            try {
              exportFlowsJson();
              closeImportPopover();
            } catch (err) {
              ctx.log?.(`[agent_flow] export failed: ${err?.message || err}`, "warn");
            }
          });
          row.appendChild(btn);
          node.appendChild(row);
        },
      },
      {
        id: "export-bundle",
        title: "Export Bundle",
        description: "Download the selected workflow as a portable bundle zip with nested subflows and skill files.",
        render(node) {
          const row = document.createElement("div");
          row.className = "button-row";
          const btn = document.createElement("button");
          btn.className = "ghost";
          btn.textContent = "Export Bundle";
          btn.addEventListener("click", async () => {
            try {
              await exportCurrentFlowArtifact("bundle");
              closeImportPopover();
            } catch (err) {
              ctx.log?.(`[agent_flow] export bundle failed: ${err?.message || err}`, "warn");
            }
          });
          row.appendChild(btn);
          node.appendChild(row);
        },
      },
      {
        id: "awf-library",
        title: "Auto Workflow Library",
        description: "Open the Auto Workflow Library for exported and generated bundles.",
        render(node) {
          const row = document.createElement("div");
          row.className = "button-row";
          const btn = document.createElement("button");
          btn.className = "ghost";
          btn.textContent = "Open AWF Library";
          btn.addEventListener("click", async () => {
            try {
              closeImportPopover();
              if (awfLibraryButtonNode) await openAwfLibraryPopover(awfLibraryButtonNode);
            } catch (err) {
              ctx.log?.(`[agent_flow] AWF library open failed: ${err?.message || err}`, "warn");
            }
          });
          row.appendChild(btn);
          node.appendChild(row);
        },
      },
    ];
    const shared = ctx.getSharedObjects?.({ type: "agent_flow_import_source" }) || [];
    for (const item of shared) {
      const getEntries = item && typeof item.getEntries === "function" ? item.getEntries : null;
      if (!getEntries) continue;
      try {
        const out = await getEntries(ctx, {
          importFlowsFromJsonText,
          buildHeaders: (useCtx = ctx) => buildHeaders(useCtx, pid, sid),
          pid,
          sid,
          closePopover: closeImportPopover,
        });
        if (Array.isArray(out)) entries.push(...out.filter(Boolean));
      } catch (err) {
        ctx.log?.(`[agent_flow] import source failed: ${err?.message || err}`, "warn");
      }
    }
    return entries;
  }

  async function openImportPopover(anchor) {
    closeImportPopover();
    importPopover = document.createElement("div");
    importPopover.className = "agent-flow-import-popover";
    const head = document.createElement("div");
    head.className = "agent-flow-import-head";
    head.textContent = "Flow Actions";
    importPopover.appendChild(head);
    const entries = await getImportEntries();
    if (!entries.length) {
      const empty = document.createElement("div");
      empty.className = "agent-flow-import-item-sub";
      empty.textContent = "No import sources available.";
      importPopover.appendChild(empty);
    } else {
      const field = document.createElement("label");
      field.className = "field";
      field.innerHTML = "<span>Import option</span>";
      const select = document.createElement("select");
      entries.forEach((entry, idx) => {
        const opt = document.createElement("option");
        opt.value = String(idx);
        opt.textContent = String(entry.title || entry.label || entry.id || "Import");
        select.appendChild(opt);
      });
      field.appendChild(select);
      importPopover.appendChild(field);

      const body = document.createElement("div");
      body.className = "agent-flow-import-item";
      importPopover.appendChild(body);

      const renderEntryAt = (idx) => {
        const entry = entries[idx] || entries[0];
        if (!entry) return;
        if (entry.id === "awf-library") {
          body.innerHTML = "";
          queueMicrotask(async () => {
            try {
              closeImportPopover();
              if (awfLibraryButtonNode) await openAwfLibraryPopover(awfLibraryButtonNode);
            } catch (err) {
              ctx.log?.(`[agent_flow] AWF library open failed: ${err?.message || err}`, "warn");
            }
          });
          return;
        }
        body.innerHTML = "";
        const title = document.createElement("div");
        title.className = "agent-flow-import-item-title";
        title.textContent = String(entry.title || entry.label || entry.id || "Import");
        body.appendChild(title);
        const desc = document.createElement("div");
        desc.className = "agent-flow-import-item-sub";
        desc.textContent = String(entry.description || "");
        if (desc.textContent) body.appendChild(desc);
        if (typeof entry.render === "function") entry.render(body);
      };

      select.addEventListener("change", () => {
        const idx = Math.max(0, Number(select.value || 0) || 0);
        renderEntryAt(idx);
      });
      renderEntryAt(0);
    }
    document.body.appendChild(importPopover);
    const rect = anchor?.getBoundingClientRect?.() || { left: 12, right: 12, bottom: 12, top: 12 };
    const width = importPopover.offsetWidth || 360;
    const height = importPopover.offsetHeight || 260;
    const left = Math.min(
      Math.max(12, rect.left),
      Math.max(12, window.innerWidth - width - 12)
    );
    const top = rect.bottom + 8 + height <= window.innerHeight
      ? rect.bottom + 8
      : Math.max(12, rect.top - height - 8);
    importPopover.style.left = `${left}px`;
    importPopover.style.top = `${top}px`;
  }

  btnNew.addEventListener("click", () => {
    syncActiveFlowFromState();
    openFlowNameDialog("New flow", (trimmed) => {
      if (flows[trimmed]) {
        ctx.log?.("Flow already exists.", "warn");
        return;
      }
      flows[trimmed] = { start: null, nodes: {} };
      currentFlow = trimmed;
      flowNavStack.length = 0;
      activeInput.value = trimmed;
      if (!activeFlow) activeFlow = trimmed;
      if (activeFlow === trimmed) {
        updateAgentFlowSettings(ctx, sid, buildFlowSelectionPatch(getAgentFlowSettings(ctx, sid), activeFlow, { mode: "active" }));
      }
      refreshFlowList();
      updateActivePanel();
      renderCanvas();
      updateBackButton();
      saveFlows(false);
      scheduleSave();
      updateBottomBar(ctx);
    });
  });

  btnRename.addEventListener("click", () => {
    syncActiveFlowFromState();
    if (!currentFlow) return;
    if (currentFlowIsReadOnly()) {
      ctx.log?.("This workflow is read-only.", "warn");
      return;
    }
    const newName = activeInput.value.trim();
    if (!newName) {
      alert("Flow name cannot be empty.");
      return;
    }
    if (newName !== currentFlow && flows[newName]) {
      alert("A flow with that name already exists.");
      return;
    }
    flows[newName] = flows[currentFlow];
    if (newName !== currentFlow) delete flows[currentFlow];
    if (defaultFlow === currentFlow) defaultFlow = newName;
    if (activeFlow === currentFlow) activeFlow = newName;
    if (activeFlow === newName) {
      const currentSettings = getAgentFlowSettings(ctx, sid) || {};
      updateAgentFlowSettings(ctx, sid, {
        ...buildFlowSelectionPatch(currentSettings, activeFlow, { mode: "active" }),
        ...buildFlowSelectionPatch(currentSettings, defaultFlow, { mode: "default" }),
      });
    }
    currentFlow = newName;
    refreshFlowList();
    updateDefaultLabel();
    saveFlows(false);
    scheduleSave();
    updateBottomBar(ctx);
  });

  btnDelete.addEventListener("click", () => {
    syncActiveFlowFromState();
    if (!currentFlow) return;
    if (currentFlowIsReadOnly()) {
      ctx.log?.("This workflow is read-only.", "warn");
      return;
    }
    const usage = findSubflowUsage(currentFlow);
    if (usage.length) {
      const details = usage
        .map((entry) => {
          const refs = entry.refs.map((ref) => `${ref.label} (${ref.nodeId})`).join(", ");
          return `- ${entry.flowName}: ${refs}`;
        })
        .join("\n");
      alert(
        `Cannot delete flow '${currentFlow}' because it is used as a subflow by:\n\n${details}`
      );
      return;
    }
    if (!confirm(`Delete flow '${currentFlow}'?`)) return;
    const removed = currentFlow;
    delete flows[currentFlow];
    if (defaultFlow === currentFlow) defaultFlow = "";
    if (activeFlow === currentFlow) {
      activeFlow = resolveActiveFlowName({ agent_flow_default_flow: defaultFlow }, flows);
    }
    currentFlow = "";
    flowNavStack.length = 0;
    activeInput.value = "";
    refreshFlowList();
    updateDefaultLabel();
    updateActivePanel();
    renderCanvas();
    updateBackButton();
    saveFlows(false);
    scheduleSave();
    if (removed && activeFlow !== agentSettings.agent_flow_active_flow) {
      const currentSettings = getAgentFlowSettings(ctx, sid) || {};
      updateAgentFlowSettings(ctx, sid, {
        ...buildFlowSelectionPatch(currentSettings, activeFlow || "", { mode: "active" }),
        ...buildFlowSelectionPatch(currentSettings, defaultFlow || "", { mode: "default" }),
      });
    }
    if (!Object.keys(flows).length) {
      setLeftOpen(true);
    }
    updateBottomBar(ctx);
  });

  btnImport.addEventListener("click", async (event) => {
    event.stopPropagation();
    if (importPopover) {
      closeImportPopover();
      return;
    }
    try {
      await openImportPopover(btnImport);
    } catch (err) {
      ctx.log?.(`[agent_flow] import menu failed: ${err?.message || err}`, "warn");
    }
  });
  flowInfoInput.addEventListener("input", () => {
    if (!currentFlow) return;
    if (currentFlowIsReadOnly()) return;
    const flow = ensureFlow(currentFlow);
    flow.description = String(flowInfoInput.value || "");
    refreshFlowList();
    scheduleSave();
  });
  flowReadOnlyInput.addEventListener("change", () => {
    if (!currentFlow) {
      flowReadOnlyInput.checked = false;
      return;
    }
    const flow = ensureFlow(currentFlow);
    flow.read_only = !!flowReadOnlyInput.checked;
    refreshFlowList();
    updateActivePanel();
    renderCanvas();
    scheduleSave();
  });
  loopSettingInput.addEventListener("change", () => {
    const value = normalizeLoopMaxSetting(loopSettingInput.value, 16);
    loopSettingInput.value = String(value);
    updateAgentFlowSettings(ctx, sid, { agent_flow_loop_max_passes: value });
    scheduleSave();
  });
  loopOverrideInput.addEventListener("change", () => {
    updateAgentFlowSettings(ctx, sid, { agent_flow_force_loop_max_passes: !!loopOverrideInput.checked });
    scheduleSave();
  });
  timeoutSettingInput.addEventListener("change", () => {
    const value = normalizeTimeoutSetting(timeoutSettingInput.value, 45);
    timeoutSettingInput.value = String(value);
    updateAgentFlowSettings(ctx, sid, { agent_flow_request_timeout_s: value });
    scheduleSave();
  });
  sandboxProfileInput.addEventListener("change", () => {
    const value = normalizeSandboxProfileSetting(sandboxProfileInput.value, "lightweight");
    sandboxProfileInput.value = value;
    updateWorkflowSettingsProfileUi();
    updateAgentFlowSettings(ctx, sid, { agent_flow_autobuild_sandbox_profile: value });
    scheduleSave();
  });
  quickSandboxProfileInput.addEventListener("change", () => {
    const value = normalizeSandboxProfileSetting(quickSandboxProfileInput.value, "lightweight");
    quickSandboxProfileInput.value = value;
    sandboxProfileInput.value = value;
    updateWorkflowSettingsProfileUi();
    updateAgentFlowSettings(ctx, sid, { agent_flow_autobuild_sandbox_profile: value });
    scheduleSave();
  });
  lightMaxRequestsInput.addEventListener("change", () => {
    const value = Math.max(1, Math.trunc(Number(lightMaxRequestsInput.value) || 1));
    lightMaxRequestsInput.value = String(value);
    updateAgentFlowSettings(ctx, sid, { agent_flow_autobuild_lightweight_max_requests: value });
    scheduleSave();
  });
  lightWaitInput.addEventListener("change", () => {
    const value = normalizeTimeoutSetting(lightWaitInput.value, 120);
    lightWaitInput.value = String(value);
    updateAgentFlowSettings(ctx, sid, { agent_flow_autobuild_lightweight_wait_s: value });
    scheduleSave();
  });
  lightGraceInput.addEventListener("change", () => {
    const value = normalizeTimeoutSetting(lightGraceInput.value, 10);
    lightGraceInput.value = String(value);
    updateAgentFlowSettings(ctx, sid, { agent_flow_autobuild_lightweight_final_grace_s: value });
    scheduleSave();
  });
  independentMaxRequestsInput.addEventListener("change", () => {
    const value = Math.max(1, Math.trunc(Number(independentMaxRequestsInput.value) || 3));
    independentMaxRequestsInput.value = String(value);
    updateAgentFlowSettings(ctx, sid, { agent_flow_autobuild_independent_max_requests: value });
    scheduleSave();
  });
  independentWaitInput.addEventListener("change", () => {
    const value = normalizeTimeoutSetting(independentWaitInput.value, 180);
    independentWaitInput.value = String(value);
    updateAgentFlowSettings(ctx, sid, { agent_flow_autobuild_independent_wait_s: value });
    scheduleSave();
  });
  independentGraceInput.addEventListener("change", () => {
    const value = normalizeTimeoutSetting(independentGraceInput.value, 20);
    independentGraceInput.value = String(value);
    updateAgentFlowSettings(ctx, sid, { agent_flow_autobuild_independent_final_grace_s: value });
    scheduleSave();
  });

  async function importDevelopmentPipeline() {
    try {
      const flowName = "workflow_dev_pipeline";
      const sharedImplementationContract = [
        "This workflow must create a coherent implementation bundle that matches the user request, not a narrow preset app shape.",
        "Treat prior handoffs as the source of truth for the implementation contract.",
        "The discovery/build/review chain must converge on one implementation contract with these fields:",
        "- solution_type",
        "- primary_stack",
        "- bundle_root",
        "- requested_deliverables",
        "- required_files",
        "- optional_support_files",
        "- run_instructions",
        "- acceptance_checks",
        "required_files must include every file that the user explicitly asked for and every additional file required to make the bundle runnable.",
        "Do not hardcode app.py, templates/index.html, requirements.txt, static/script.js, or any other specific filenames unless the user request or the agreed contract actually requires them.",
        "If a later node needs to add a file that was not named earlier, it must treat that as a manifest update and explain why the file is required for coherence.",
        "All implementation and review nodes must validate against the same manifest rather than inventing new expected files.",
        "Do not switch stacks mid-workflow. If discovery chooses a stack, build and release must stay on that stack unless a reviewer explicitly proves the stack is unworkable.",
        "The final result must describe the actual files created and how to run or inspect them.",
        "The implementation is not complete unless every path in required_files exists in the bundle root and matches the agreed stack.",
        "Missing smoke tests or runtime validation are release-blocking bugs, not informational notes.",
        "Reviewers must compare actual created files against required_files and emit bugs for every missing or substituted file.",
      ].join("\n");
      const taggedBuildProtocol = [
        "For create/build implementation tasks, prefer the TAGGED protocol instead of JSON tool_calls for large artifacts.",
        "Emit tagged sections exactly like this when writing a file:",
        "<<<AW_SUMMARY>>> ... <<<END_AW_SUMMARY>>>",
        "<<<AW_PLAN>>> ... <<<END_AW_PLAN>>>",
        "<<<AW_ANALYSIS>>> ... <<<END_AW_ANALYSIS>>>",
        "<<<AW_RESPONSE>>> ... <<<END_AW_RESPONSE>>>",
        "<<<AW_ACTIONS>>>",
        "- item",
        "<<<END_AW_ACTIONS>>>",
        "<<<AW_HANDOFF>>> ... <<<END_AW_HANDOFF>>>",
        "<<<AW_TOOL_CALL>>>",
        "skill: code.apply_patch",
        "reason: Create or update the artifact",
        "path: relative/file.html",
        "op: write",
        "<<<AW_CONTENT>>>",
        "raw file content here",
        "<<<END_AW_CONTENT>>>",
        "<<<END_AW_TOOL_CALL>>>",
        "For large files, emit additional <<<AW_TOOL_CALL>>> blocks with op: append for continuation chunks.",
        "Do not wrap tagged output in markdown fences.",
      ].join("\n");
      const rolePrompt = (rid, label) => {
        const base = `You are the ${label} (${rid}). Do your role and handoff clearly.`;
        const role = String(rid || "");
        if (role === "product") {
          return `${base}
${sharedImplementationContract}
Your job is to translate the user request into a strict implementation contract.
Produce a concrete requested_deliverables list and a required_files manifest that fits the actual request.
If the request is broad, define the smallest coherent runnable bundle that still satisfies it.
Do not overfit to previous runs or preset web-app filenames.`;
        }
        if (role === "gui_designer") {
          return `${base}
${sharedImplementationContract}
If the requested solution includes a user interface, refine the manifest and UX expectations without changing the chosen stack.
If no interface is needed, explicitly say so and do not invent frontend files.
Do not create placeholder files in this phase unless you are explicitly performing a repair pass on an existing frontend artifact.`;
        }
        if (role === "architect") {
          return `${base}
${sharedImplementationContract}
Consolidate the prior handoff into one stable implementation contract.
Resolve ambiguity before build starts.
If no artifact has been written yet, do not pretend to verify it. State that implementation must create it first.`;
        }
        if (["staff_engineer", "coder"].includes(role)) {
          return `${base}
${sharedImplementationContract}
Implement exactly one coherent bundle that satisfies the agreed contract.
Create the files in required_files plus any justified optional_support_files you explicitly add to the manifest.
Do not create multiple competing versions of the same app shape.
Do not silently swap frameworks, languages, or entrypoints.
If the user asked for a bundle of code, ensure the created files form a runnable or inspectable bundle rather than isolated fragments.
If you are the Staff Engineer and no implementation exists yet, do not write placeholder artifacts or artifact.txt files. Your job is to strengthen the contract and handoff so the Coding Engineer can create the real bundle.
If you are the Coding Engineer, you must create every file in required_files before claiming readiness.
Before handoff, list which required_files were created and which acceptance_checks still need execution.
${taggedBuildProtocol}`;
        }
        if (["qa", "security", "docs", "release"].includes(role)) {
          return `${base}
${sharedImplementationContract}
Review only against the agreed implementation contract and manifest.
Do not invent generic expected files that were never required by the contract.
If no artifact has been written yet, do not pretend to verify it. State that implementation must create it first.
When implementation files exist, you must verify that every required_files path exists.
If smoke tests or runtime validation were not executed, emit that as a bug requiring another pass.
If required_files and actual files differ, emit that as a bug requiring another pass.`;
        }
        return `${base}\n${sharedImplementationContract}`;
      };
      const roleCfg = {
        product: { label: "Product", skills: ["auth.project_context", "repo.context", "repo.read", "learning.get_hints"] },
        gui_designer: { label: "GUI Designer", skills: ["repo.context", "repo.read", "rag.search", "learning.get_hints"] },
        architect: { label: "Architect", skills: ["repo.tree", "repo.context", "repo.read", "rag.search"] },
        staff_engineer: { label: "Staff Engineer", skills: ["repo.tree", "repo.read", "rag.search", "tests.run_project", "tests.smoke"] },
        coder: { label: "Coding Engineer", skills: ["repo.tree", "repo.read", "repo.write", "rag.search", "code.generate_patch_candidates", "code.apply_patch"] },
        qa: { label: "QA Reviewer", skills: ["repo.tree", "repo.read", "tests.run_project", "tests.smoke", "debug.fix_from_errors"] },
        security: { label: "Security Reviewer", skills: ["repo.tree", "repo.read", "rag.search"] },
        docs: { label: "Docs Reviewer", skills: ["repo.context", "repo.read", "learning.get_hints"] },
        release: { label: "Release Reviewer", skills: ["repo.tree", "repo.read", "repo.write", "tests.run_project", "tests.smoke", "learning.list"] },
      };
      const teamSubflows = [
        { subflow: "workflow_team_discovery", label: "Discovery Team", members: ["product", "gui_designer", "architect"] },
        { subflow: "workflow_team_build", label: "Build Team", members: ["staff_engineer", "coder", "gui_designer"] },
        { subflow: "workflow_team_quality", label: "Quality Team", members: ["qa", "security", "docs"] },
        { subflow: "workflow_team_release", label: "Release Team", members: ["release", "staff_engineer", "qa", "docs"] },
      ];
      const subflowTransitions = (subflowName, rid, sidNext) => {
        if (subflowName === "workflow_team_release" && rid === "qa") {
          return [
            { condition: { type: "test_failures_gte", value: "1" }, target: "n2", loop_max_passes: 2, system_prompt: "Release QA found test failures. Repair the implementation before returning to QA." },
            ...(sidNext ? [{ condition: { type: "always" }, target: sidNext }] : []),
          ];
        }
        if (subflowName === "workflow_team_release" && rid === "docs" && !sidNext) {
          return [
            { condition: { type: "bugs_present" }, target: "n2", loop_max_passes: 2, system_prompt: "Release review found remaining issues. Fix them before closing release." },
            { condition: { type: "no_changed_files" }, target: "n2", loop_max_passes: 2, system_prompt: "Release review found that no files were actually changed. Make the required implementation edits now." },
          ];
        }
        if (subflowName === "workflow_team_quality" && rid === "docs" && !sidNext) {
          return [
            { condition: { type: "bugs_present" }, target: "n1", loop_max_passes: 1, system_prompt: "Quality review found unresolved issues. Re-run the quality pass with those issues addressed." },
          ];
        }
        return sidNext ? [{ condition: { type: "always" }, target: sidNext }] : [];
      };
      const topLevelTransitions = (team, nextTop) => {
        if (team.subflow === "workflow_team_quality") {
          return [
            {
              condition: { operator: "any", rules: [{ type: "bugs_present" }, { type: "test_failures_gte", value: "1" }] },
              target: "n2",
              loop_max_passes: 2,
              system_prompt: "Quality Team found bugs or test failures. Re-enter Build Team and repair the implementation before continuing.",
            },
            ...(nextTop ? [{ condition: { type: "always" }, target: nextTop }] : []),
          ];
        }
        if (team.subflow === "workflow_team_release") {
          return [
            {
              condition: { operator: "any", rules: [{ type: "bugs_present" }, { type: "test_failures_gte", value: "1" }] },
              target: "n2",
              loop_max_passes: 2,
              system_prompt: "Release Team found blockers or missing validation. Re-enter Build Team, create every required file, repair the reported bugs, add any missing dependency manifest or test file, and return only after a fresh validation pass is possible.",
            },
            ...(nextTop ? [{ condition: { type: "always" }, target: nextTop }] : []),
          ];
        }
        return nextTop ? [{ condition: { type: "always" }, target: nextTop }] : [];
      };
      const topNodes = {};
      const allFlows = {};
      for (let i = 0; i < teamSubflows.length; i += 1) {
        const t = teamSubflows[i];
        const topNodeId = `n${i + 1}`;
        const nextTop = i + 1 < teamSubflows.length ? `n${i + 2}` : "";
        const subNodes = {};
        for (let j = 0; j < t.members.length; j += 1) {
          const rid = String(t.members[j] || "").trim();
          const rc = roleCfg[rid];
          if (!rc) continue;
          const sidN = `n${j + 1}`;
          const sidNext = j + 1 < t.members.length ? `n${j + 2}` : "";
          subNodes[sidN] = {
            label: rc.label,
            plugin_id: "agent_workflow_member",
            agent_kind: rid,
            system_prompt: rolePrompt(rid, rc.label),
            x: 80 + (j % 3) * 290,
            y: 80 + Math.floor(j / 3) * 170,
            delay_ms: 0,
            return_only_text: true,
            transitions: subflowTransitions(t.subflow, rid, sidNext),
            plugin_settings: {
              member_role: rid,
              handoff_format: "plain",
              output_protocol: "tagged",
              member_token_stream: true,
              action_skills: rc.skills,
            },
          };
        }
        allFlows[t.subflow] = {
          start: "n1",
          nodes: subNodes,
        };
        topNodes[topNodeId] = {
          label: t.label,
          plugin_id: "agent_flow_subflow",
          agent_kind: "subflow",
          system_prompt: [
            sharedImplementationContract,
            `This is the ${t.label}.`,
            "Carry forward the current implementation contract and keep every member aligned to it.",
            "Do not allow later members to invent a new stack or a new required file set unless they explicitly update the manifest with justification.",
          ].join("\n"),
          x: 80 + (i % 3) * 290,
          y: 80 + Math.floor(i / 3) * 170,
          delay_ms: 0,
          return_only_text: true,
          transitions: topLevelTransitions(t, nextTop),
          plugin_settings: {
            subflow_name: t.subflow,
          },
        };
      }
      allFlows[flowName] = {
        start: "n1",
        nodes: topNodes,
      };
      const imp = {
        flows: allFlows,
        default_flow: flowName,
        active_flow: flowName,
        mode: "execute",
        max_steps: 24,
      };
      await importFlowsFromJsonText(JSON.stringify(imp), { merge: true });
      ctx.log?.("[agent_flow] imported development pipeline flows (orchestrator + team subflows)", "info");
    } catch (err) {
      ctx.log?.(`[agent_flow] import development pipeline failed: ${err?.message || err}`, "warn");
    }
  }

  btnBackFlow.addEventListener("click", () => goBackFlow());
  backTag.addEventListener("click", () => goBackFlow());

  btnDefault.addEventListener("click", () => {
    const name = activeInput.value.trim();
    if (!name || !flows[name]) {
      alert("Flow name must exist in the list.");
      return;
    }
    defaultFlow = name;
    updateDefaultLabel();
    saveFlows(true);
    updateBottomBar(ctx);
  });

  btnSave.addEventListener("click", () => saveFlows(true));

  btnApply.addEventListener("click", () => applyNodeProperties());
  btnAddTransition.addEventListener("click", () => {
    if (!selectedNodeId) return;
    if (currentFlowIsReadOnly()) {
      ctx.log?.("This workflow is read-only.", "warn");
      return;
    }
    const nodes = getCurrentNodes();
    const target = Object.keys(nodes).find((id) => id !== selectedNodeId);
    if (!target) {
      ctx.log?.("[agent_flow] add at least one more node before creating a transition", "warn");
      return;
    }
    const node = nodes[selectedNodeId];
    if (!node) return;
    if (!Array.isArray(node.transitions)) node.transitions = [];
    node.transitions.push({
      target,
      condition: { type: "always" },
      loop_max_passes: normalizeLoopMaxSetting(getAgentFlowSettings(ctx, sid)?.agent_flow_loop_max_passes, 16),
    });
    renderTransitionEditor(selectedNodeId, node.transitions);
    renderEdges();
    scheduleSave();
  });
  function deleteSelectedNode() {
    deleteSelectedNodes(selectedNodeId);
  }

  pluginInputWrap.input.addEventListener("change", () => {
    if (!selectedNodeId) return;
    const node = getCurrentNodes()[selectedNodeId];
    if (!node) return;
    const pid = pluginInputWrap.input.value.trim();
    const schema = schemaForPlugin(pid);
    buildPluginSettingsForm(schema, node.plugin_settings || {});
    loadModelSettings(node, schema);
  });

  let suppressCanvasClick = false;
  let canvasLongPress = null;
  let lastTapAt = 0;
  let lastTapPoint = null;
  let selectionDrag = null;
  canvas.addEventListener("pointerdown", (event) => {
    if (event.target?.closest?.(".context-menu")) return;
    if (event.button !== 0) return;
    const pt = canvasPointFromEvent(event);
    if (!currentFlowIsReadOnly() && event.pointerType !== "touch" && !event.target.closest?.(".flow-node")) {
      selectionDrag = {
        pointerId: event.pointerId,
        startX: pt.x,
        startY: pt.y,
        active: false,
      };
      canvas.setPointerCapture(event.pointerId);
    }
    canvasLongPress = startLongPress(event, () => {
      if (selectionDrag) selectionDrag = null;
      if (currentFlowIsReadOnly()) return;
      suppressCanvasClick = true;
      const clipboard = getNodeClipboard();
      const canPaste = Boolean(clipboard?.nodes && Object.keys(clipboard.nodes).length);
      const items = [
        { label: "Add node here", onClick: () => addNodeAt(pt.x, pt.y) },
        { label: "Paste", disabled: !canPaste, onClick: () => pasteClipboardAt(pt.x, pt.y) },
      ];
      if (selectedNodeIds.size) {
        items.push({ label: "Copy selected", onClick: () => copySelectedNodes(selectedNodeId) });
        items.push({ label: "Remove selected", onClick: () => deleteSelectedNodes(selectedNodeId) });
      }
      openContextMenu(pt.x, pt.y, items);
    });
    if (canvasLongPress) canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (event.target?.closest?.(".context-menu")) return;
    if (selectionDrag && selectionDrag.pointerId === event.pointerId) {
      const pt = canvasPointFromEvent(event);
      const left = Math.min(selectionDrag.startX, pt.x);
      const top = Math.min(selectionDrag.startY, pt.y);
      const width = Math.abs(pt.x - selectionDrag.startX);
      const height = Math.abs(pt.y - selectionDrag.startY);
      if (!selectionDrag.active && (width > 8 || height > 8)) {
        selectionDrag.active = true;
        suppressCanvasClick = true;
        if (canvasLongPress) {
          canvasLongPress.cancel();
          canvasLongPress = null;
        }
        selectionBox.style.display = "";
      }
      if (selectionDrag.active) {
        selectionBox.style.left = `${left}px`;
        selectionBox.style.top = `${top}px`;
        selectionBox.style.width = `${width}px`;
        selectionBox.style.height = `${height}px`;
      }
    }
    if (!canvasLongPress) return;
    canvasLongPress.move(event);
  });
  canvas.addEventListener("pointerup", (event) => {
    if (event.target?.closest?.(".context-menu")) return;
    if (selectionDrag && selectionDrag.pointerId === event.pointerId) {
      const pt = canvasPointFromEvent(event);
      const rect = {
        left: Math.min(selectionDrag.startX, pt.x),
        top: Math.min(selectionDrag.startY, pt.y),
        right: Math.max(selectionDrag.startX, pt.x),
        bottom: Math.max(selectionDrag.startY, pt.y),
      };
      const wasActive = selectionDrag.active;
      selectionDrag = null;
      selectionBox.style.display = "none";
      selectionBox.style.width = "0px";
      selectionBox.style.height = "0px";
      if (wasActive) {
        selectNodesInRect(rect, { openPanel: false });
        if (!selectedNodeId) {
          setRightOpen(false);
        }
        closeContextMenu();
      }
    }
    let longPressTriggered = false;
    if (!canvasLongPress) return;
    longPressTriggered = canvasLongPress.isTriggered();
    canvasLongPress.cancel();
    canvasLongPress = null;
    if (longPressTriggered) return;
    if (event.pointerType !== "touch") return;
    const now = Date.now();
    const pt = canvasPointFromEvent(event);
    if (lastTapAt && lastTapPoint && now - lastTapAt < 350) {
      const dx = pt.x - lastTapPoint.x;
      const dy = pt.y - lastTapPoint.y;
      if (Math.hypot(dx, dy) < 24) {
        suppressCanvasClick = true;
        restoreCanvasFocus();
        lastTapAt = 0;
        lastTapPoint = null;
        return;
      }
    }
    lastTapAt = now;
    lastTapPoint = pt;
  });
  canvas.addEventListener("pointercancel", () => {
    selectionDrag = null;
    selectionBox.style.display = "none";
    if (!canvasLongPress) return;
    canvasLongPress.cancel();
    canvasLongPress = null;
  });

  canvas.addEventListener("dblclick", (event) => {
    if (event.target?.closest?.(".context-menu")) return;
    if (event.target.closest?.(".flow-node")) return;
    event.preventDefault();
    suppressCanvasClick = true;
    restoreCanvasFocus();
  });

  canvas.addEventListener("click", (event) => {
    if (event?.target?.closest?.(".context-menu")) return;
    if (suppressCanvasClick) {
      suppressCanvasClick = false;
      return;
    }
    linkSourceId = "";
    updateHint();
    clearProperties();
    setRightOpen(false);
    setLeftOpen(false);
    closeContextMenu();
  });

  canvas.addEventListener("contextmenu", (event) => {
    if (event.target?.closest?.(".context-menu")) return;
    event.preventDefault();
    const pt = canvasPointFromEvent(event);
    if (currentFlowIsReadOnly()) return;
    const clipboard = getNodeClipboard();
    const canPaste = Boolean(clipboard?.nodes && Object.keys(clipboard.nodes).length);
    const items = [
      { label: "Add node here", onClick: () => addNodeAt(pt.x, pt.y) },
      { label: "Paste", disabled: !canPaste, onClick: () => pasteClipboardAt(pt.x, pt.y) },
    ];
    if (selectedNodeIds.size) {
      items.push({ label: "Copy selected", onClick: () => copySelectedNodes(selectedNodeId) });
      items.push({ label: "Remove selected", onClick: () => deleteSelectedNodes(selectedNodeId) });
    }
    openContextMenu(pt.x, pt.y, items);
  });

  updateDefaultLabel();
  updateWorkflowSettingsProfileUi();
  refreshFlowList();
  refreshPluginOptions();
  renderCanvas();
  if (currentFlow) loadFlow(currentFlow);
  updateBackButton();
  updateBottomBar(ctx);
  void syncFlowsFromServer();
  consumeFlowNavRequest();
  if (openTempLibraryRecordHandler) {
    window.removeEventListener(OPEN_TEMP_LIBRARY_EVENT, openTempLibraryRecordHandler);
    openTempLibraryRecordHandler = null;
  }
  openTempLibraryRecordHandler = (event) => {
    try {
      if (event?.detail && typeof event.detail === "object") {
        window[OPEN_TEMP_LIBRARY_PENDING_KEY] = event.detail;
      }
    } catch {}
    void consumeTempLibraryOpenRequest();
  };
  window.addEventListener(OPEN_TEMP_LIBRARY_EVENT, openTempLibraryRecordHandler);
  void consumeTempLibraryOpenRequest();

  Promise.all([
    ensureManifest(ctx),
    loadAgentFlowSkillCatalog(ctx, true),
  ]).then(([m]) => {
    manifest = m || {};
    refreshPluginOptions();
    if (selectedNodeId) {
      const node = getCurrentNodes()[selectedNodeId];
      if (node) {
        const schema = schemaForPlugin(node.plugin_id || "");
        buildPluginSettingsForm(schema, node.plugin_settings || {});
        loadModelSettings(node, schema);
      }
    }
  });
}

const plugin = {
  id: meta.plugin_id,
  name: meta.name,
  kind: meta.kind,
  description: meta.description,
  meta,
  register(host) {
    ensureStyles();
    host.requestLoadPriority?.({ position: "first" });
    host.addPanelTab({
      id: meta.plugin_id,
      title: "Agent Flow",
      windowType: "full",
      render: (container, ctx) => renderPanel(container, ctx),
    });
    host.addTopRightIconRow((ctx) => ensureFlowAlert(ctx));
    host.addTranscriptBottombar((ctx) => ensureBottomBar(ctx), "right");
    host.addSendHook(sendHook, { timeoutMs: 60000 });
    host.addEventHandler((event, data, ctx) => {
      if (event === "flow_status") {
        applyFlowStatus(ctx, data);
      }
    });
    host.addCompletionPayloadHook((payload, ctx) => {
      if (!payload || typeof payload !== "object") return payload;
      const sid = payload.sid || ctx.state.ui.activeSid;
      if (!sid) return payload;
      if (directChatBypassBySid.has(String(sid))) {
        directChatBypassBySid.delete(String(sid));
        const ext = payload.ext && typeof payload.ext === "object" ? { ...payload.ext } : {};
        delete ext.agent_flow_active_flow;
        delete ext.router_plugin_settings;
        return {
          ...payload,
          router_enabled_plugins: [],
          ext,
        };
      }
      const settings = getAgentFlowSettings(ctx, sid);
      if (hasNoFlowSelection(settings)) {
        const ext = payload.ext && typeof payload.ext === "object" ? payload.ext : {};
        if (ext.agent_flow_active_flow === NO_FLOW_VALUE) return payload;
        return { ...payload, ext: { ...ext, agent_flow_active_flow: NO_FLOW_VALUE } };
      }
      if (hasSpecialFlowSelection(settings)) {
        const activeSpecial = String(settings.agent_flow_active_flow || "").trim();
        const specialAllowed = (activeSpecial === LLM_AUTOFLOW_FLOW_VALUE && isLLMAutoFlowGuiAvailable(ctx))
          || (activeSpecial === LLM_SKILL_AUTOFLOW_FLOW_VALUE && isLLMSkillAutoFlowGuiAvailable(ctx));
        if (!specialAllowed) return payload;
        const ext = payload.ext && typeof payload.ext === "object" ? payload.ext : {};
        if (ext.agent_flow_active_flow === activeSpecial) return payload;
        return { ...payload, ext: { ...ext, agent_flow_active_flow: activeSpecial } };
      }
      const flows = settings.agent_flow_flows || {};
      const active = resolveActiveFlowName(settings, flows);
      if (!active) return payload;
      const flowDef = flows?.[active];
      if (!flowIsRunnable(flowDef)) return payload;
      const ext = payload.ext && typeof payload.ext === "object" ? payload.ext : {};
      if (ext.agent_flow_active_flow) return payload;
      return { ...payload, ext: { ...ext, agent_flow_active_flow: active } };
    });
  },
  dispose() {
    if (bottomBarPopoverSearchTimer) {
      clearTimeout(bottomBarPopoverSearchTimer);
      bottomBarPopoverSearchTimer = null;
    }
    if (flowListSearchTimer) {
      clearTimeout(flowListSearchTimer);
      flowListSearchTimer = null;
    }
    if (sessionChangeHandler) {
      document.removeEventListener(SESSION_CHANGE_EVENT, sessionChangeHandler);
      sessionChangeHandler = null;
    }
    if (bottomBarOutsideHandler) {
      document.removeEventListener("click", bottomBarOutsideHandler);
      window.removeEventListener("resize", positionBottomBarPopover);
      bottomBarOutsideHandler = null;
    }
    if (openTempLibraryRecordHandler) {
      window.removeEventListener(OPEN_TEMP_LIBRARY_EVENT, openTempLibraryRecordHandler);
      openTempLibraryRecordHandler = null;
    }
    bottomBarCtx = null;
    bottomBarNode = null;
    bottomBarButton = null;
    closeBottomBarPopover();
    closeImportPopover();
    closeAwfLibraryPopover();
  },
};

export default plugin;


