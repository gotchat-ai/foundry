const meta = {
  plugin_id: "permissions_manager",
  name: "Permissions",
  kind: "ui",
  description: "Manage roles, plugin access, and delegated enterprise permissions.",
  has_notebook_tab: false,
};

const STYLE_ID = "permissions-manager-style";
const state = {
  loading: false,
  loaded: false,
  tab: "roles",
  catalog: null,
  policy: null,
  users: [],
  selectedRole: "user",
  selectedUser: "",
  status: "",
  root: null,
  ctx: null,
};

function clone(value) {
  try {
    return JSON.parse(JSON.stringify(value));
  } catch (_err) {
    return value;
  }
}

function ensureStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
.pm-root { display: flex; flex-direction: column; gap: 12px; }
.pm-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.pm-title { font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--ui-muted); }
.pm-status { font-size: 12px; color: var(--ui-muted); min-height: 18px; }
.pm-tabs { display: inline-flex; gap: 6px; flex-wrap: wrap; }
.pm-tab { border: 1px solid var(--border); background: var(--ui-control-bg); color: var(--ui-ink); border-radius: 999px; padding: 6px 12px; cursor: pointer; }
.pm-tab.active { border-color: rgba(var(--accent-rgb, 37, 99, 235), 0.6); color: var(--accent); box-shadow: 0 0 0 1px rgba(var(--accent-rgb, 37, 99, 235), 0.16); }
.pm-grid { display: grid; grid-template-columns: 240px minmax(0, 1fr); gap: 12px; align-items: start; }
.pm-panel { border: 1px solid var(--border); border-radius: 14px; background: rgba(var(--panel-rgb), 0.72); padding: 12px; display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.pm-list { display: flex; flex-direction: column; gap: 6px; max-height: 62vh; overflow: auto; }
.pm-list-item { border: 1px solid var(--border); background: var(--ui-popover-item-bg); color: var(--ui-ink); border-radius: 10px; padding: 8px 10px; text-align: left; cursor: pointer; }
.pm-list-item.active { border-color: rgba(var(--accent-rgb, 37, 99, 235), 0.6); box-shadow: 0 0 0 1px rgba(var(--accent-rgb, 37, 99, 235), 0.16); }
.pm-list-sub { display: block; font-size: 11px; color: var(--ui-muted); margin-top: 2px; }
.pm-form { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.pm-field { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.pm-field > span { font-size: 11px; color: var(--ui-muted); text-transform: uppercase; letter-spacing: 0.06em; }
.pm-field input, .pm-field textarea, .pm-field select { width: 100%; min-width: 0; box-sizing: border-box; }
.pm-field textarea { min-height: 72px; resize: vertical; }
.pm-inline { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.pm-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.pm-section { border: 1px solid var(--border); border-radius: 12px; padding: 10px; display: flex; flex-direction: column; gap: 8px; }
.pm-section-title { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--ui-muted); }
.pm-checks { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 8px; }
.pm-check { display: flex; align-items: flex-start; gap: 8px; font-size: 12px; }
.pm-check input { margin-top: 2px; }
.pm-plugin-grid { display: grid; grid-template-columns: minmax(180px, 1fr) 72px 72px 80px; gap: 8px; align-items: center; }
.pm-plugin-grid.pm-head-row { font-size: 11px; color: var(--ui-muted); text-transform: uppercase; letter-spacing: 0.08em; }
.pm-plugin-grid label { display: inline-flex; justify-content: center; }
.pm-plugin-scroll { display: flex; flex-direction: column; gap: 8px; max-height: 320px; overflow-y: auto; padding-right: 4px; }
.pm-skill-category { display: flex; flex-direction: column; gap: 8px; }
.pm-skill-row { display: grid; grid-template-columns: minmax(0, 1fr) 56px; gap: 10px; align-items: start; border: 1px solid var(--border); border-radius: 10px; padding: 8px; background: var(--ui-popover-item-bg); }
.pm-skill-name { font-size: 12px; color: var(--ui-ink); }
.pm-skill-meta { display: block; font-size: 11px; color: var(--ui-muted); margin-top: 3px; white-space: pre-line; }
.pm-skill-toggle { display: inline-flex; justify-content: center; align-items: start; }
.pm-empty { font-size: 12px; color: var(--ui-muted); }
@media (max-width: 860px) {
  .pm-grid { grid-template-columns: 1fr; }
  .pm-plugin-grid { grid-template-columns: minmax(0, 1fr) 58px 58px 64px; }
}
  `;
  document.head.appendChild(style);
}

function roleIds(policy) {
  const roles = policy && typeof policy.roles === "object" ? policy.roles : {};
  return Object.keys(roles).sort((a, b) => a.localeCompare(b));
}

function selectedRole(policy) {
  const ids = roleIds(policy);
  if (!ids.length) return "";
  if (state.selectedRole && ids.includes(state.selectedRole)) return state.selectedRole;
  state.selectedRole = ids[0];
  return state.selectedRole;
}

function selectedUser() {
  if (state.selectedUser && state.users.some((user) => user.username === state.selectedUser)) return state.selectedUser;
  state.selectedUser = state.users[0]?.username || "";
  return state.selectedUser;
}

function setStatus(text) {
  state.status = String(text || "");
  render();
}

async function loadData(ctx, { force = false } = {}) {
  if (state.loading) return;
  if (state.loaded && !force) return;
  state.loading = true;
  state.ctx = ctx;
  setStatus("Loading permissions...");
  try {
    const [catalogRes, policyRes, usersRes] = await Promise.all([
      ctx.apiJson("/v1/permissions/catalog"),
      ctx.apiJson("/v1/permissions/policy"),
      ctx.apiJson("/v1/permissions/users"),
    ]);
    state.catalog = catalogRes || {};
    state.policy = clone(policyRes?.policy || {});
    state.users = Array.isArray(usersRes?.users) ? usersRes.users : [];
    selectedRole(state.policy);
    selectedUser();
    state.loaded = true;
    state.status = "";
  } catch (err) {
    state.status = `Load failed: ${err.message || err}`;
  } finally {
    state.loading = false;
    render();
  }
}

function ensureRole(policy, roleId) {
  const roles = policy.roles = policy.roles || {};
  if (!roles[roleId]) {
    roles[roleId] = {
      label: roleId,
      description: "",
      permissions: {},
      plugin_access: {},
      skill_access: {},
      builtin: false,
    };
  }
  return roles[roleId];
}

function permissionGroups() {
  return Array.isArray(state.catalog?.permission_groups) ? state.catalog.permission_groups : [];
}

function pluginCatalog() {
  return Array.isArray(state.catalog?.plugins) ? state.catalog.plugins : [];
}

function skillCatalog() {
  return Array.isArray(state.catalog?.skills) ? state.catalog.skills : [];
}

function roleAssignedToUser(username) {
  const map = state.policy?.user_roles || {};
  return Array.isArray(map[String(username || "").toLowerCase()]) ? map[String(username || "").toLowerCase()] : [];
}

async function savePolicy() {
  if (!state.ctx || !state.policy) return;
  setStatus("Saving...");
  try {
    const payload = await state.ctx.apiJson("/v1/permissions/policy", {
      method: "PUT",
      body: { policy: state.policy },
    });
    state.policy = clone(payload?.policy || state.policy);
    await state.ctx.refreshPermissions?.({ silent: true });
    setStatus("Saved.");
  } catch (err) {
    setStatus(`Save failed: ${err.message || err}`);
  }
}

function buildButton(label, onClick, className = "ghost") {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = className;
  btn.textContent = label;
  btn.addEventListener("click", onClick);
  return btn;
}

function renderRoleList(host) {
  const wrap = document.createElement("div");
  wrap.className = "pm-panel";
  const head = document.createElement("div");
  head.className = "pm-inline";
  head.appendChild(buildButton("New Role", () => {
    if (!state.policy) return;
    const base = "role_";
    let idx = 1;
    while ((state.policy.roles || {})[`${base}${idx}`]) idx += 1;
    const nextId = `${base}${idx}`;
    ensureRole(state.policy, nextId);
    state.selectedRole = nextId;
    render();
  }));
  wrap.appendChild(head);
  const list = document.createElement("div");
  list.className = "pm-list";
  for (const roleId of roleIds(state.policy || {})) {
    const role = state.policy.roles[roleId] || {};
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "pm-list-item" + (selectedRole(state.policy) === roleId ? " active" : "");
    btn.innerHTML = `${role.label || roleId}<span class="pm-list-sub">${role.description || roleId}</span>`;
    btn.addEventListener("click", () => {
      state.selectedRole = roleId;
      render();
    });
    list.appendChild(btn);
  }
  wrap.appendChild(list);
  return wrap;
}

function renderRoleEditor(host) {
  const roleId = selectedRole(state.policy);
  const role = ensureRole(state.policy, roleId);
  const wrap = document.createElement("div");
  wrap.className = "pm-panel pm-form";

  const roleIdField = document.createElement("input");
  roleIdField.value = roleId;
  roleIdField.disabled = Boolean(role.builtin);
  const roleIdWrap = document.createElement("label");
  roleIdWrap.className = "pm-field";
  roleIdWrap.innerHTML = "<span>Role ID</span>";
  roleIdWrap.appendChild(roleIdField);
  wrap.appendChild(roleIdWrap);

  roleIdField.addEventListener("change", () => {
    const nextId = String(roleIdField.value || "").trim();
    if (!nextId || nextId === roleId || (state.policy.roles || {})[nextId]) {
      roleIdField.value = roleId;
      return;
    }
    state.policy.roles[nextId] = clone(role);
    delete state.policy.roles[roleId];
    Object.keys(state.policy.user_roles || {}).forEach((username) => {
      const next = (state.policy.user_roles[username] || []).map((id) => id === roleId ? nextId : id);
      state.policy.user_roles[username] = Array.from(new Set(next));
    });
    state.selectedRole = nextId;
    render();
  });

  const labelField = document.createElement("input");
  labelField.value = role.label || roleId;
  labelField.addEventListener("input", () => {
    role.label = String(labelField.value || "");
  });
  const labelWrap = document.createElement("label");
  labelWrap.className = "pm-field";
  labelWrap.innerHTML = "<span>Label</span>";
  labelWrap.appendChild(labelField);
  wrap.appendChild(labelWrap);

  const descField = document.createElement("textarea");
  descField.value = role.description || "";
  descField.addEventListener("input", () => {
    role.description = String(descField.value || "");
  });
  const descWrap = document.createElement("label");
  descWrap.className = "pm-field";
  descWrap.innerHTML = "<span>Description</span>";
  descWrap.appendChild(descField);
  wrap.appendChild(descWrap);

  const defaultField = document.createElement("select");
  roleIds(state.policy).forEach((id) => {
    const opt = document.createElement("option");
    opt.value = id;
    opt.textContent = id;
    defaultField.appendChild(opt);
  });
  defaultField.value = roleId;
  defaultField.disabled = true;
  const defaultWrap = document.createElement("label");
  defaultWrap.className = "pm-field";
  defaultWrap.innerHTML = "<span>Default Role</span>";
  defaultWrap.appendChild(defaultField);
  wrap.appendChild(defaultWrap);

  permissionGroups().forEach((group) => {
    const section = document.createElement("div");
    section.className = "pm-section";
    section.innerHTML = `<div class="pm-section-title">${group.label || group.id}</div>`;
    const grid = document.createElement("div");
    grid.className = "pm-checks";
    (group.items || []).forEach((item) => {
      const row = document.createElement("label");
      row.className = "pm-check";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = Boolean(role.permissions?.[item.key]);
      input.addEventListener("change", () => {
        role.permissions = role.permissions || {};
        role.permissions[item.key] = Boolean(input.checked);
      });
      const text = document.createElement("span");
      text.textContent = item.label || item.key;
      row.appendChild(input);
      row.appendChild(text);
      grid.appendChild(row);
    });
    section.appendChild(grid);
    wrap.appendChild(section);
  });

  const pluginSection = document.createElement("div");
  pluginSection.className = "pm-section";
  pluginSection.innerHTML = '<div class="pm-section-title">Plugin Access</div>';
  const pluginScroll = document.createElement("div");
  pluginScroll.className = "pm-plugin-scroll";
  const header = document.createElement("div");
  header.className = "pm-plugin-grid pm-head-row";
  header.innerHTML = '<div>Plugin</div><div>View</div><div>Open</div><div>Set</div>';
  pluginScroll.appendChild(header);
  pluginCatalog().forEach((plugin) => {
    const row = document.createElement("div");
    row.className = "pm-plugin-grid";
    const name = document.createElement("div");
    name.textContent = plugin.name || plugin.id;
    row.appendChild(name);
    const access = ((role.plugin_access = role.plugin_access || {}), (role.plugin_access[plugin.id] = role.plugin_access[plugin.id] || { view: false, open: false, settings: false }), role.plugin_access[plugin.id]);
    ["view", "open", "settings"].forEach((key) => {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = Boolean(access[key]);
      input.addEventListener("change", () => {
        access[key] = Boolean(input.checked);
      });
      label.appendChild(input);
      row.appendChild(label);
    });
    pluginScroll.appendChild(row);
  });
  pluginSection.appendChild(pluginScroll);
  wrap.appendChild(pluginSection);

  const actions = document.createElement("div");
  actions.className = "pm-actions";
  actions.appendChild(buildButton("Save Policy", () => void savePolicy(), "primary"));
  if (!role.builtin) {
    actions.appendChild(buildButton("Delete Role", () => {
      delete state.policy.roles[roleId];
      Object.keys(state.policy.user_roles || {}).forEach((username) => {
        state.policy.user_roles[username] = (state.policy.user_roles[username] || []).filter((id) => id !== roleId);
      });
      state.selectedRole = roleIds(state.policy)[0] || "";
      render();
    }));
  }
  wrap.appendChild(actions);
  return wrap;
}

function renderSkillEditor() {
  const roleId = selectedRole(state.policy);
  const role = ensureRole(state.policy, roleId);
  role.skill_access = role.skill_access || {};
  const wrap = document.createElement("div");
  wrap.className = "pm-panel pm-form";

  const title = document.createElement("div");
  title.className = "pm-section-title";
  title.textContent = `Skill Permissions for ${role.label || roleId}`;
  wrap.appendChild(title);

  const skills = skillCatalog();
  if (!skills.length) {
    const empty = document.createElement("div");
    empty.className = "pm-empty";
    empty.textContent = "No Agent Flow skills were discovered.";
    wrap.appendChild(empty);
  } else {
    let currentCategory = "";
    let section = null;
    let skillList = null;
    for (const skill of skills) {
      const category = String(skill.category || "general");
      if (category !== currentCategory) {
        currentCategory = category;
        section = document.createElement("div");
        section.className = "pm-section pm-skill-category";
        section.innerHTML = `<div class="pm-section-title">${category}</div>`;
        skillList = document.createElement("div");
        skillList.className = "pm-plugin-scroll";
        const head = document.createElement("div");
        head.className = "pm-section-title";
        head.textContent = "Enable skill usage for this role";
        skillList.appendChild(head);
        section.appendChild(skillList);
        wrap.appendChild(section);
      }
      const row = document.createElement("div");
      row.className = "pm-skill-row";
      const info = document.createElement("div");
      info.className = "pm-skill-name";
      const metaParts = [skill.id];
      if (Array.isArray(skill.permissions) && skill.permissions.length) metaParts.push(`Permissions: ${skill.permissions.join(", ")}`);
      const description = String(skill.description || "").trim();
      info.innerHTML = `${skill.label || skill.id}<span class="pm-skill-meta">${metaParts.join(" | ")}${description ? `
${description}` : ""}</span>`;
      row.appendChild(info);
      const toggle = document.createElement("label");
      toggle.className = "pm-skill-toggle";
      const access = (role.skill_access[skill.id] = role.skill_access[skill.id] || { use: false });
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = Boolean(access.use);
      input.addEventListener("change", () => {
        access.use = Boolean(input.checked);
      });
      toggle.appendChild(input);
      row.appendChild(toggle);
      skillList.appendChild(row);
    }
  }

  const actions = document.createElement("div");
  actions.className = "pm-actions";
  actions.appendChild(buildButton("Save Policy", () => void savePolicy(), "primary"));
  wrap.appendChild(actions);
  return wrap;
}

function renderUserList() {
  const wrap = document.createElement("div");
  wrap.className = "pm-panel";
  const list = document.createElement("div");
  list.className = "pm-list";
  for (const user of state.users) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "pm-list-item" + (selectedUser() === user.username ? " active" : "");
    const assigned = roleAssignedToUser(user.username);
    btn.innerHTML = `${user.username}<span class="pm-list-sub">${assigned.length ? assigned.join(", ") : "default only"}</span>`;
    btn.addEventListener("click", () => {
      state.selectedUser = user.username;
      render();
    });
    list.appendChild(btn);
  }
  wrap.appendChild(list);
  return wrap;
}

function renderUserEditor() {
  const username = selectedUser();
  const wrap = document.createElement("div");
  wrap.className = "pm-panel pm-form";
  if (!username) {
    const empty = document.createElement("div");
    empty.className = "pm-empty";
    empty.textContent = "No users found.";
    wrap.appendChild(empty);
    return wrap;
  }
  const user = state.users.find((item) => item.username === username) || {};
  const title = document.createElement("div");
  title.className = "pm-section-title";
  title.textContent = `${username} (${user.role || "user"})`;
  wrap.appendChild(title);
  const section = document.createElement("div");
  section.className = "pm-section";
  const checks = document.createElement("div");
  checks.className = "pm-checks";
  const assigned = new Set(roleAssignedToUser(username));
  roleIds(state.policy || {}).forEach((roleId) => {
    if (roleId === "anonymous") return;
    const row = document.createElement("label");
    row.className = "pm-check";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = assigned.has(roleId);
    input.addEventListener("change", () => {
      const key = String(username || "").toLowerCase();
      const next = new Set(roleAssignedToUser(username));
      if (input.checked) next.add(roleId);
      else next.delete(roleId);
      state.policy.user_roles = state.policy.user_roles || {};
      state.policy.user_roles[key] = Array.from(next);
    });
    const text = document.createElement("span");
    const role = state.policy.roles?.[roleId] || {};
    text.textContent = role.label || roleId;
    row.appendChild(input);
    row.appendChild(text);
    checks.appendChild(row);
  });
  section.appendChild(checks);
  wrap.appendChild(section);
  const actions = document.createElement("div");
  actions.className = "pm-actions";
  actions.appendChild(buildButton("Save Policy", () => void savePolicy(), "primary"));
  wrap.appendChild(actions);
  return wrap;
}

function render() {
  if (!state.root) return;
  ensureStyles();
  const root = state.root;
  root.innerHTML = "";
  const frame = document.createElement("div");
  frame.className = "pm-root";
  const head = document.createElement("div");
  head.className = "pm-head";
  const title = document.createElement("div");
  title.className = "pm-title";
  title.textContent = "Enterprise Permissions";
  head.appendChild(title);
  const tabs = document.createElement("div");
  tabs.className = "pm-tabs";
  [["roles", "Roles"], ["skills", "Skills"], ["users", "Users"]].forEach(([id, label]) => {
    const btn = buildButton(label, () => {
      state.tab = id;
      render();
    });
    btn.className = "pm-tab" + (state.tab === id ? " active" : "");
    tabs.appendChild(btn);
  });
  head.appendChild(tabs);
  frame.appendChild(head);
  const status = document.createElement("div");
  status.className = "pm-status";
  status.textContent = state.status || "";
  frame.appendChild(status);

  if (!state.loaded) {
    const empty = document.createElement("div");
    empty.className = "pm-empty";
    empty.textContent = state.loading ? "Loading..." : "Permissions are unavailable.";
    frame.appendChild(empty);
    root.appendChild(frame);
    return;
  }

  const grid = document.createElement("div");
  grid.className = "pm-grid";
  if (state.tab === "roles") {
    grid.appendChild(renderRoleList());
    grid.appendChild(renderRoleEditor());
  } else if (state.tab === "skills") {
    grid.appendChild(renderRoleList());
    grid.appendChild(renderSkillEditor());
  } else {
    grid.appendChild(renderUserList());
    grid.appendChild(renderUserEditor());
  }
  frame.appendChild(grid);
  root.appendChild(frame);
}

function renderPanel(target, ctx) {
  state.root = target;
  state.ctx = ctx;
  render();
  void loadData(ctx);
}

const plugin = {
  meta,
  register(host) {
    host.addPanelTab({
      id: meta.plugin_id,
      title: meta.name,
      render: (target, ctx) => renderPanel(target, ctx),
    });
  },
};

export default plugin;
