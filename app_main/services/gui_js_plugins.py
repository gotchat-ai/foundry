import json
import os
from typing import Any, Callable


class GuiJsPluginService:
    """Discover GUI JavaScript plugins and apply permission filtering."""

    def __init__(self, *, app_getter: Callable[[], Any], gui_js_dir_getter: Callable[[], str]) -> None:
        self._app_getter = app_getter
        self._gui_js_dir_getter = gui_js_dir_getter

    def plugin_rev(self, dir_path: str) -> str:
        try:
            import hashlib as _hashlib

            digest = _hashlib.sha1()
            for root, dirs, files in os.walk(dir_path):
                dirs.sort()
                files.sort()
                for name in files:
                    try:
                        full = os.path.join(root, name)
                        stat = os.stat(full)
                        rel = os.path.relpath(full, dir_path).replace(os.sep, "/")
                        digest.update(rel.encode("utf-8", "ignore"))
                        digest.update(b"|")
                        digest.update(
                            str(int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)))).encode("ascii")
                        )
                        digest.update(b"|")
                        digest.update(str(int(stat.st_size)).encode("ascii"))
                        digest.update(b"\n")
                    except Exception:
                        continue
            return digest.hexdigest()[:16]
        except Exception:
            return ""

    def list_gui_js_plugins(self, request: Any, *, plugin_rev: Callable[[str], str] | None = None) -> dict[str, Any]:
        gui_js_dir = self._gui_js_dir_getter()
        plugin_rev_fn = plugin_rev or self.plugin_rev
        plug_dir = os.path.join(gui_js_dir, "plugins")
        out = []
        if os.path.isdir(plug_dir):
            for entry in os.scandir(plug_dir):
                if entry.is_dir():
                    manifest = {}
                    manifest_path = os.path.join(entry.path, "manifest.json")
                    if os.path.isfile(manifest_path):
                        try:
                            with open(manifest_path, "r", encoding="utf-8") as handle:
                                manifest = json.load(handle) or {}
                        except Exception:
                            manifest = {}
                    entrypoint = None
                    entry_field = manifest.get("entry") or manifest.get("path") or manifest.get("main")
                    if isinstance(entry_field, str) and entry_field.strip():
                        entry_path = entry_field.strip()
                        if not os.path.isabs(entry_path):
                            entry_path = os.path.join(entry.path, entry_path)
                        if os.path.isfile(entry_path):
                            entrypoint = entry_path
                    if not entrypoint:
                        for candidate in ("plugin.js", "plugin.mjs", "index.js", "index.mjs"):
                            path = os.path.join(entry.path, candidate)
                            if os.path.isfile(path):
                                entrypoint = path
                                break
                    if entrypoint:
                        rel = os.path.relpath(entrypoint, gui_js_dir).replace(os.sep, "/")
                        plugin_id = str(manifest.get("id") or entry.name).strip() or entry.name
                        item = {"path": f"/gui_js/{rel}", "id": plugin_id}
                        rev = plugin_rev_fn(entry.path)
                        if rev:
                            item["rev"] = rev
                        if manifest.get("name"):
                            item["name"] = manifest.get("name")
                        if manifest.get("kind"):
                            item["kind"] = manifest.get("kind")
                        if manifest.get("description"):
                            item["description"] = manifest.get("description")
                        if manifest.get("category"):
                            item["category"] = str(manifest.get("category") or "").strip()
                        out.append(item)
                    continue
                if not entry.is_file():
                    continue
                name = entry.name
                low = name.lower()
                if not low.endswith((".js", ".mjs")):
                    continue
                if name.startswith(".") or name.startswith("_"):
                    continue
                rel = os.path.relpath(entry.path, gui_js_dir).replace(os.sep, "/")
                try:
                    stat = os.stat(entry.path)
                    rev = f"{int(getattr(stat, 'st_mtime_ns', int(stat.st_mtime * 1_000_000_000))):x}-{int(stat.st_size):x}"
                except Exception:
                    rev = ""
                item = {"path": f"/gui_js/{rel}", "id": os.path.splitext(name)[0]}
                if rev:
                    item["rev"] = rev
                out.append(item)
        try:
            from plugins.gui_helpers.permissions_manager.core import (
                can_access_plugin,
                compute_effective_permissions,
                get_request_user,
            )

            app = self._app_getter()
            summary = compute_effective_permissions(app, get_request_user(app, request))
            out = [item for item in out if can_access_plugin(summary, str(item.get("id") or ""), action="view")]
        except Exception:
            pass
        out.sort(key=lambda item: item["path"])
        return {"plugins": out}
