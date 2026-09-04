# Learn GotChat Foundry

GotChat Foundry is a complete self-hosted AI chat application that can be used immediately and extended when a project needs custom behavior. This guide covers the recommended installation path and three small plugin examples:

1. A browser-side plugin that adds a label to the transcript toolbar.
2. A message renderer that adds a word count to assistant messages.
3. A full-stack plugin that calls a permission-gated Python endpoint.

You do not need to create a plugin to use GotChat. Plugin development is optional.

## 1. Install GotChat Foundry

### Prerequisites

- A current Windows, macOS, or Linux computer.
- Python 3.11 or 3.12 is recommended for the widest package compatibility.
- A modern web browser.
- Enough disk space for the application, Python environment, and any local models you download.
- Optional GPU drivers and tooling if you want GPU acceleration.

The setup wizard detects the operating system and hardware, creates a private Python virtual environment, and proposes the appropriate CPU or GPU packages. Avoid installing the entire `requirements.txt` into your system Python unless you are intentionally doing manual development.

### Download or clone the project

Download and extract the Foundry release, or clone its Git repository. Open a terminal in the directory containing these files:

```text
start_setup_wizard.ps1
start_setup_wizard.sh
setup_wizard_app.py
```

The public download page is <https://gotchat.ai/downloads.html>.

### Windows installation

Open PowerShell in the Foundry directory:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\start_setup_wizard.ps1
```

If `python` is not the correct command on your machine, pass the interpreter explicitly:

```powershell
.\start_setup_wizard.ps1 -Python py
```

The setup wizard opens at <http://127.0.0.1:8095/>.

Windows GPU builds may require Microsoft Visual Studio 2022 Build Tools with the **Desktop development with C++** workload. The wizard reports this before installing packages.

### macOS installation

Open Terminal in the Foundry directory:

```bash
bash start_setup_wizard.sh
```

If macOS reports that developer tools are missing or outdated, install or update them and rerun the system check:

```bash
xcode-select --install
```

Apple Silicon systems can use Metal for supported local-model runtimes. Intel Macs use the compatible CPU or Accelerate plan selected by the wizard.

### Linux installation

Open a terminal in the Foundry directory:

```bash
bash start_setup_wizard.sh
```

The script repairs its executable bit when possible. After the first run, this form should also work:

```bash
./start_setup_wizard.sh
```

The wizard detects missing Linux system packages. Depending on the desktop and account configuration, it may use `sudo`, open an administrator prompt, or print the packages that must be installed manually.

### Complete the setup wizard

The wizard has four pages:

1. **Welcome** — confirms that packages will be installed into a virtual environment.
2. **Install Path** — selects the installation root and Python environment directory.
3. **GPU** — selects the GPU brand and model, then runs **Check System**.
4. **Install** — optionally enables image/video generation helpers, installs packages, and starts the services.

On the final page:

1. Review the detected `llama-cpp-python` and PyTorch plans.
2. Select **Install image/video generation helpers** only if you need those optional runtimes.
3. Click **Install Packages**.
4. Wait until the progress log reports that installation is ready.
5. Click **Start Services**.

The chat opens automatically when the services are healthy.

### Local service addresses

| Service | Default address | Purpose |
| --- | --- | --- |
| Setup wizard | `http://127.0.0.1:8095/` | Detects hardware, installs packages, and starts services. |
| GotChat web interface | `http://127.0.0.1:8080/` | Main browser application. If 8080 is occupied, the wizard tries the next available port through 8089. |
| GotChat API | `http://127.0.0.1:8000/` | Chat, projects, plugins, workflows, and runtime APIs. |
| Llama host service | `http://127.0.0.1:8767/` | Controls supported local llama runtimes. |

### Stop GotChat

Windows:

```powershell
.\stop_setup_wizard.ps1
```

macOS or Linux:

```bash
bash stop_setup_wizard.sh
```

These scripts stop the services recorded by the setup wizard and then stop the wizard listener.

## 2. Understand the plugin layout

GotChat discovers plugins from two locations:

```text
gui_js/plugins/<plugin_id>/          Browser interface and render plugins
plugins/gui_helpers/<plugin_id>/    Python routes and server-side helpers
```

A GUI plugin normally contains:

```text
manifest.json
plugin.js
```

A backend helper normally contains:

```text
manifest.json
__init__.py
routes.py
```

GUI plugins are discovered from their folders at runtime. You do not need to edit the shared `gui_js/plugins/manifest.json` for a normal folder-based plugin. Backend helpers are auto-discovered when the API starts.

Use a stable lowercase identifier with underscores, such as `hello_topbar`. If a GUI plugin has a backend helper, use the same GUI plugin identifier in both layers so permission checks and request headers remain aligned.

## 3. Create a basic GUI plugin

This plugin adds a small label to the right side of the upper transcript toolbar.

Create this directory:

```text
gui_js/plugins/hello_topbar/
```

Create `gui_js/plugins/hello_topbar/manifest.json`:

```json
{
  "id": "hello_topbar",
  "name": "Hello Topbar",
  "kind": "ui",
  "description": "Adds a small example label to the transcript topbar.",
  "entry": "plugin.js",
  "category": "Tools/Extensions"
}
```

Create `gui_js/plugins/hello_topbar/plugin.js`:

```javascript
const meta = {
  plugin_id: "hello_topbar",
  name: "Hello Topbar",
  kind: "ui",
  description: "Adds a small example label to the transcript topbar.",
};

function buildLabel() {
  const label = document.createElement("div");
  label.textContent = "Hello from your GotChat plugin";
  label.style.fontSize = "12px";
  label.style.fontWeight = "700";
  label.setAttribute("aria-label", "Hello Topbar plugin");
  return label;
}

export default {
  id: meta.plugin_id,
  name: meta.name,
  kind: meta.kind,
  description: meta.description,
  meta,
  register(host) {
    host.addTranscriptTopbar(() => buildLabel(), "right");
  },
};
```

Refresh the GotChat page. The backend-generated plugin list notices the new folder and the browser imports `plugin.js`. If the plugin is restricted by a deployment's permission policy, enable it for the current user or role in Permission Management.

### What the code does

- `manifest.json` supplies discovery and settings metadata.
- The default export identifies the plugin and exposes `register(host)`.
- `host.addTranscriptTopbar(...)` registers a UI factory.
- The factory returns a regular DOM node, so the plugin can use standard browser APIs.

Prefer `textContent` for user-controlled text. Avoid putting secrets or privileged logic in browser-side JavaScript.

## 4. Create a basic message-footer plugin

This example adds a word count beneath assistant messages.

Create this directory:

```text
gui_js/plugins/assistant_word_count/
```

Create `gui_js/plugins/assistant_word_count/manifest.json`:

```json
{
  "id": "assistant_word_count",
  "name": "Assistant Word Count",
  "kind": "render",
  "description": "Shows a word count in each assistant message footer.",
  "entry": "plugin.js",
  "category": "Renderer"
}
```

Create `gui_js/plugins/assistant_word_count/plugin.js`:

```javascript
const meta = {
  plugin_id: "assistant_word_count",
  name: "Assistant Word Count",
  kind: "render",
  description: "Shows a word count in each assistant message footer.",
};

function messageText(content) {
  if (Array.isArray(content)) {
    return content
      .filter((part) => part && part.type === "text")
      .map((part) => String(part.text || part.content || ""))
      .join(" ");
  }
  return String(content || "");
}

function renderWordCount(message) {
  const text = messageText(message?.content).trim();
  const count = text ? (text.match(/\S+/g) || []).length : 0;
  const badge = document.createElement("span");
  badge.textContent = `${count} word${count === 1 ? "" : "s"}`;
  badge.style.fontSize = "11px";
  badge.style.opacity = "0.75";
  return badge;
}

export default {
  id: meta.plugin_id,
  name: meta.name,
  kind: meta.kind,
  description: meta.description,
  meta,
  register(host) {
    host.addMessageFooterItem({
      align: "right",
      roles: ["assistant"],
      render: (message) => renderWordCount(message),
    });
  },
};
```

Refresh the chat and send a message. The footer appears after each assistant response.

## 5. Add a permission-gated backend helper

Use a backend helper when a plugin needs server-side storage, protected integrations, filesystem access, model control, or other capabilities that must not run in the browser.

This example extends `hello_topbar` with a backend status route.

Create this directory:

```text
plugins/gui_helpers/hello_topbar/
```

Create `plugins/gui_helpers/hello_topbar/manifest.json`:

```json
{
  "id": "hello_topbar_helper",
  "name": "Hello Topbar Helper",
  "type": "control",
  "gui_plugin_id": "hello_topbar",
  "description": "Supplies a permission-gated status route for Hello Topbar.",
  "routes": [
    "/v1/hello-topbar/status"
  ],
  "category": "Tools/Extensions"
}
```

Create `plugins/gui_helpers/hello_topbar/__init__.py`:

```python
from .routes import install

__all__ = ["install"]
```

Create `plugins/gui_helpers/hello_topbar/routes.py`:

```python
from fastapi import APIRouter, Request

from plugins.gui_helpers._framework.utils import require_gui_plugin_enabled


GUI_PLUGIN_ID = "hello_topbar"


def install(app) -> None:
    router = APIRouter()

    @router.get("/v1/hello-topbar/status")
    def hello_status(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        return {
            "ok": True,
            "plugin": GUI_PLUGIN_ID,
            "message": "Hello from the GotChat backend",
        }

    app.include_router(router)
```

`require_gui_plugin_enabled` checks that the associated GUI plugin is enabled and that the current user has permission to open it. Apply additional role or resource authorization for routes that access sensitive data.

Now replace `gui_js/plugins/hello_topbar/plugin.js` with this full-stack version:

```javascript
const meta = {
  plugin_id: "hello_topbar",
  name: "Hello Topbar",
  kind: "ui",
  description: "Calls a small permission-gated backend helper.",
};

function buildButton(ctx) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "Check plugin";
  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "Checking...";
    try {
      const result = await ctx.apiJson("/v1/hello-topbar/status");
      button.textContent = result.message || "Plugin is ready";
    } catch (error) {
      button.textContent = "Plugin check failed";
      console.warn("hello_topbar status failed", error);
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

export default {
  id: meta.plugin_id,
  name: meta.name,
  kind: meta.kind,
  description: meta.description,
  meta,
  register(host) {
    host.addTranscriptTopbar((ctx) => buildButton(ctx), "right");
  },
};
```

Restart GotChat after adding or changing Python helper modules. Backend helpers are imported when the API starts:

Windows:

```powershell
.\stop_setup_wizard.ps1
.\start_setup_wizard.ps1
```

macOS or Linux:

```bash
bash stop_setup_wizard.sh
bash start_setup_wizard.sh
```

Start the services from the wizard, refresh the chat, and click **Check plugin**.

## 6. Package a full-stack plugin

During development, files live directly in the source folders described above. A distributable full-stack plugin archive can preserve the two layers like this:

```text
hello_topbar.zip
├── frontend/
│   └── gui_js/
│       └── hello_topbar/
│           ├── manifest.json
│           └── plugin.js
└── server/
    └── gui_helpers/
        └── hello_topbar/
            ├── manifest.json
            ├── __init__.py
            └── routes.py
```

Before publishing a plugin:

1. Keep the GUI plugin identifier stable.
2. Confirm the backend `gui_plugin_id` matches the GUI identifier.
3. List every backend route in the helper manifest.
4. Validate request payloads on the server.
5. Keep API keys and other secrets out of browser code and plugin archives.
6. Test with both an allowed user and a user who should be denied.
7. Restart the backend and hard-refresh the browser before concluding that discovery failed.
8. Include a README describing installation, permissions, routes, settings, and removal.

## 7. Useful plugin extension points

The examples use only two hooks. GotChat's browser plugin host also supports extension points for:

- Upper and lower transcript toolbars.
- Composer controls and context-menu items.
- Message footers, message attachments, and message renderers.
- Structured block transformers and block renderers.
- Settings panels and application panels.
- Event handlers, send hooks, and completion-payload hooks.
- Router bridges, roster actions, project actions, and session actions.
- Shared UI themes and localization bundles.

Study the bundled plugins in `gui_js/plugins/` for working examples. Useful starting points include:

- `code_card_render` for a compact block transformer.
- `tok_metric` for message footer rendering and stream events.
- `theme_demo` for UI settings and theme variables.
- `pin_messages` for a paired GUI and persistent backend helper.
- `agent_flow` for a large workflow-oriented full-stack plugin.

## 8. Troubleshooting

### The setup wizard does not open

Open <http://127.0.0.1:8095/> manually. To run without automatically opening a browser:

```powershell
.\start_setup_wizard.ps1 -NoOpen
```

```bash
python3 setup_wizard_app.py --no-open
```

### Port 8080 is already in use

The setup wizard checks ports 8080 through 8089 and reports the selected `chat_url`. Use the URL shown after **Start Services**.

### A GUI plugin does not appear

- Confirm the folder is directly under `gui_js/plugins/`.
- Confirm `manifest.json` is valid JSON.
- Confirm the entry file exists and exports a default plugin object.
- Confirm the manifest id and JavaScript `plugin_id` match.
- Check Permission Management for role restrictions.
- Hard-refresh the browser to discard an older module cache.

### A backend route returns 404

- Confirm the helper is directly under `plugins/gui_helpers/`.
- Confirm `__init__.py` exports `install`.
- Confirm `install(app)` includes the router.
- Restart the API after changing Python files.
- Confirm the paired GUI plugin is enabled for the current user.
- Confirm the GUI and backend identifiers match.

### A GPU package fails to install

Return to the GPU page, choose the exact hardware or select **No GPU / I don't know**, run **Check System**, and reinstall with the CPU plan. CPU mode is slower but is the simplest compatibility fallback.

## Next steps

- Explore the interactive tutorials at <https://gotchat.ai/tutorials.html>.
- Review platform capabilities at <https://gotchat.ai/platform.html>.
- Use the Build resources and starter packages at <https://gotchat.ai/build.html>.
- Keep each new plugin focused, permission-aware, and independently removable.
