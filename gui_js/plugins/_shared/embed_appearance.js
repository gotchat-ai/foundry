const PRESETS = {
  warm: {
    accent: '#0f766e',
    accentInk: '#f0fffb',
    panelRgb: '255, 250, 241',
    bg0: '#f4efe6',
    bg1: '#eadfcd',
    bgGradA: '#fff9ee',
    bgGradB: '#f7e3cc',
    bgImage: '',
  },
  ocean: {
    accent: '#0f4c81',
    accentInk: '#f3fbff',
    panelRgb: '241, 248, 255',
    bg0: '#dceefd',
    bg1: '#b8d8f2',
    bgGradA: '#f6fbff',
    bgGradB: '#b8d8f2',
    bgImage: '',
  },
  graphite: {
    accent: '#d97706',
    accentInk: '#fff9f0',
    panelRgb: '34, 39, 46',
    bg0: '#1e232b',
    bg1: '#39414d',
    bgGradA: '#2e3540',
    bgGradB: '#4a5564',
    bgImage: '',
  },
  forest: {
    accent: '#2f6b3c',
    accentInk: '#f5fff6',
    panelRgb: '244, 251, 244',
    bg0: '#edf7ee',
    bg1: '#d1e7d3',
    bgGradA: '#fbfffb',
    bgGradB: '#c0dbbe',
    bgImage: '',
  },
};

const APPEARANCE_KEYS = ['accent', 'accentInk', 'panelRgb', 'bg0', 'bg1', 'bgGradA', 'bgGradB', 'bgImage'];

function cssRgbFromHex(value) {
  const text = String(value || '').trim();
  const match = text.match(/^#?([0-9a-f]{6})$/i);
  if (!match) return '';
  const hex = match[1];
  return [0, 2, 4].map((idx) => parseInt(hex.slice(idx, idx + 2), 16)).join(', ');
}

function scopedMount() {
  const cfg = typeof window !== 'undefined' ? (window.__CHAT_JS_EMBED_CONFIG || {}) : {};
  return cfg.mount || window.__CHAT_JS_EMBED_MOUNT || document.getElementById('llm-chat-js-embed') || null;
}

function appearanceTargets() {
  const mount = scopedMount();
  const targets = new Set();
  if (mount) {
    targets.add(mount);
    const shell = mount.closest?.('.superadmin-chat-shell');
    if (shell) targets.add(shell);
    const superadminMount = mount.closest?.('.superadmin-chat-mount');
    if (superadminMount) targets.add(superadminMount);
  }
  const portal = document.getElementById('llm-chat-js-portal');
  if (portal) targets.add(portal);
  return Array.from(targets);
}

export function normalizeAppearanceSettings(settings) {
  const source = settings && typeof settings === 'object' ? settings : {};
  const appearance = source.appearance && typeof source.appearance === 'object' ? source.appearance : source;
  const normalized = {};
  for (const key of APPEARANCE_KEYS) {
    const value = String(appearance[key] || '').trim();
    if (value) normalized[key] = value;
  }
  const preset = String(appearance.preset || appearance.themeName || '').trim().toLowerCase();
  if (preset) normalized.preset = preset;
  return normalized;
}

export function applyScopedAppearanceSettings(settings) {
  const targets = appearanceTargets();
  if (!targets.length) return;
  const appearance = normalizeAppearanceSettings(settings);
  const vars = {
    '--accent': appearance.accent || '',
    '--accent-ink': appearance.accentInk || '',
    '--panel-rgb': appearance.panelRgb || '',
    '--bg-0': appearance.bg0 || '',
    '--bg-1': appearance.bg1 || '',
    '--bg-grad-a': appearance.bgGradA || '',
    '--bg-grad-b': appearance.bgGradB || '',
    '--bg-image': appearance.bgImage ? (/^url\(/i.test(appearance.bgImage) ? appearance.bgImage : `url("${appearance.bgImage}")`) : '',
  };
  const accentRgb = cssRgbFromHex(appearance.accent);
  if (accentRgb) vars['--accent-rgb'] = accentRgb;
  targets.forEach((target) => {
    Object.entries(vars).forEach(([key, value]) => {
      if (value) target.style.setProperty(key, value);
      else target.style.removeProperty(key);
    });
    if (appearance.preset) target.dataset.sassAppearancePreset = appearance.preset;
    else delete target.dataset.sassAppearancePreset;
  });
}

function buildField(labelText, name, type = 'text') {
  const label = document.createElement('label');
  label.textContent = labelText;
  const input = document.createElement('input');
  input.name = name;
  input.type = type;
  input.autocomplete = 'off';
  label.appendChild(input);
  return { label, input };
}

export function renderAppearanceEditor(options = {}) {
  const current = normalizeAppearanceSettings(options.initialSettings || {});
  const wrap = document.createElement('div');
  wrap.className = 'sass-auth-card';
  const title = document.createElement('div');
  title.className = 'sass-auth-title';
  title.textContent = options.title || 'Appearance Settings';
  const meta = document.createElement('div');
  meta.className = 'sass-auth-meta';
  meta.textContent = options.description || 'Applies scoped branding variables without changing the existing Chat JS framework.';
  const presetRow = document.createElement('div');
  presetRow.className = 'sass-auth-form';
  const presetLabel = document.createElement('label');
  presetLabel.textContent = 'Preset';
  const presetSelect = document.createElement('select');
  presetSelect.name = 'preset';
  for (const [value, label] of [['custom', 'custom'], ['warm', 'warm'], ['ocean', 'ocean'], ['graphite', 'graphite'], ['forest', 'forest']]) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = label;
    presetSelect.appendChild(option);
  }
  presetLabel.appendChild(presetSelect);
  presetRow.appendChild(presetLabel);
  const fieldsGrid = document.createElement('div');
  fieldsGrid.className = 'sass-auth-grid';
  const fields = {
    accent: buildField('Accent', 'accent', 'color'),
    accentInk: buildField('Accent Ink', 'accentInk', 'color'),
    panelRgb: buildField('Panel RGB', 'panelRgb', 'text'),
    bg0: buildField('Background 0', 'bg0', 'color'),
    bg1: buildField('Background 1', 'bg1', 'color'),
    bgGradA: buildField('Gradient A', 'bgGradA', 'color'),
    bgGradB: buildField('Gradient B', 'bgGradB', 'color'),
    bgImage: buildField('Background Image URL', 'bgImage', 'text'),
  };
  Object.values(fields).forEach((field) => fieldsGrid.appendChild(field.label));
  const actions = document.createElement('div');
  actions.className = 'sass-auth-actions';
  const save = document.createElement('button');
  save.type = 'button';
  save.className = 'primary';
  save.textContent = options.saveLabel || 'Apply Appearance';
  const reset = document.createElement('button');
  reset.type = 'button';
  reset.className = 'ghost';
  reset.textContent = 'Reset';
  actions.appendChild(save);
  actions.appendChild(reset);
  wrap.appendChild(title);
  wrap.appendChild(meta);
  wrap.appendChild(presetRow);
  wrap.appendChild(fieldsGrid);
  wrap.appendChild(actions);

  function writeValues(values) {
    const merged = values || {};
    fields.accent.input.value = merged.accent || PRESETS.warm.accent;
    fields.accentInk.input.value = merged.accentInk || PRESETS.warm.accentInk;
    fields.panelRgb.input.value = merged.panelRgb || '';
    fields.bg0.input.value = merged.bg0 || PRESETS.warm.bg0;
    fields.bg1.input.value = merged.bg1 || PRESETS.warm.bg1;
    fields.bgGradA.input.value = merged.bgGradA || PRESETS.warm.bgGradA;
    fields.bgGradB.input.value = merged.bgGradB || PRESETS.warm.bgGradB;
    fields.bgImage.input.value = merged.bgImage || '';
  }

  function readValues() {
    return normalizeAppearanceSettings({
      preset: presetSelect.value === 'custom' ? '' : presetSelect.value,
      accent: fields.accent.input.value,
      accentInk: fields.accentInk.input.value,
      panelRgb: fields.panelRgb.input.value,
      bg0: fields.bg0.input.value,
      bg1: fields.bg1.input.value,
      bgGradA: fields.bgGradA.input.value,
      bgGradB: fields.bgGradB.input.value,
      bgImage: fields.bgImage.input.value,
    });
  }

  const activePreset = current.preset && PRESETS[current.preset] ? current.preset : 'custom';
  presetSelect.value = activePreset;
  writeValues(activePreset === 'custom' ? current : { ...PRESETS[activePreset], ...current });

  presetSelect.addEventListener('change', () => {
    const selected = presetSelect.value;
    writeValues(selected === 'custom' ? current : PRESETS[selected] || current);
  });
  reset.addEventListener('click', () => {
    presetSelect.value = 'custom';
    writeValues({});
    options.onChange?.({ appearance: {} });
  });
  save.addEventListener('click', async () => {
    await options.onSave?.({ appearance: readValues() });
  });
  return wrap;
}

export function defaultAppearancePresets() {
  return { ...PRESETS };
}
