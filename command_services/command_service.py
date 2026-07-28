from __future__ import annotations

import atexit
import json
import os
import base64
import io
import subprocess
import sys
import time
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
import urllib.error
import urllib.request

from .ui_actions import (
    is_ui_available,
    click_element_at,
    drag_element,
    scroll_at,
    type_text,
    press_keys,
)


STATE_DIR = os.path.abspath(os.path.dirname(__file__))
PID_PATH = os.path.join(STATE_DIR, "command_service.pid")
HOST_BIND = os.environ.get("LLMLOADER2_COMMAND_SERVICE_BIND", "127.0.0.1")
HOST_PORT = int(os.environ.get("LLMLOADER2_COMMAND_SERVICE_PORT", "8777") or "8777")
AUTH_ME_URL = os.environ.get("LLMLOADER2_COMMAND_SERVICE_AUTH_ME_URL", "http://localhost:8000/v1/auth/me")

_COLLAB_DB = None
_THREAD = threading.local()
_PW = None
_CTX = None
_CTX_HEADLESS = None
_CTX_LOCK = threading.Lock()
_BROWSER_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _write_json(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2)


def _token_from_headers(headers) -> str:
    auth = headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    tok = headers.get("X-Auth-Token") or ""
    return tok.strip()


def _auth_me(token: str) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    url = (AUTH_ME_URL or "").strip()
    if not url:
        return None
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        data = json.loads(raw) if raw else {}
        user = data.get("user") if isinstance(data, dict) else None
        if isinstance(user, dict):
            return user
    except Exception:
        return None
    return None


def _has_playwright() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


def _has_display() -> bool:
    if os.name == "nt" or sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _get_playwright():
    global _PW
    if _PW is None:
        from playwright.sync_api import sync_playwright
        _PW = sync_playwright().start()
    return _PW


def _get_context(headless: bool):
    global _CTX, _CTX_HEADLESS
    with _CTX_LOCK:
        if _CTX is not None and _CTX_HEADLESS == headless:
            return _CTX
        if _CTX is not None:
            try:
                _CTX.close()
            except Exception:
                pass
            _CTX = None
        p = _get_playwright()
        base_dir = os.path.join(os.environ.get("TEMP") or os.getcwd(), "llmloader2_playwright")
        user_data_dir = os.path.join(base_dir, "default")
        _CTX = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=headless,
            channel="chrome",
            args=["--no-first-run", "--no-default-browser-check"],
        )
        _CTX_HEADLESS = headless
        return _CTX


def _img_to_data_uri(image: Any) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return "data:image/png;base64," + b64


def _get_collab_db():
    global _COLLAB_DB
    if _COLLAB_DB is not None:
        return _COLLAB_DB
    try:
        from plugins.gui_helpers.collab_chat.routes import _DB, _default_db_path
    except Exception:
        return None
    path = os.environ.get("MODEL_LOADER_COLLAB_DB") or _default_db_path()
    try:
        _COLLAB_DB = _DB(path)
    except Exception:
        _COLLAB_DB = None
    return _COLLAB_DB


def _require_admin(headers) -> Optional[Dict[str, Any]]:
    token = _token_from_headers(headers)
    if token:
        user = _auth_me(token)
        if user and str(user.get("role") or "").lower() == "admin":
            return {"username": user.get("username", "admin"), "role": user.get("role", "admin")}
    db = _get_collab_db()
    if db is None:
        return None
    if not token:
        return None
    try:
        user = db.resolve_token(token)
    except Exception:
        user = None
    if not user or str(getattr(user, "role", "")).lower() != "admin":
        return None
    return {"username": getattr(user, "username", "admin"), "role": getattr(user, "role", "admin")}


def _split_allowlist(raw: Any) -> List[str]:
    if not raw:
        return []
    if isinstance(raw, (list, tuple, set)):
        return [str(item or "").strip().lower() for item in raw if str(item or "").strip()]
    return [p.strip().lower() for p in str(raw).split(",") if p.strip()]


def _first_token(cmd: str) -> str:
    if not cmd:
        return ""
    cmd = cmd.strip()
    if cmd.startswith('"'):
        parts = cmd.split('"', 2)
        if len(parts) > 1:
            return parts[1].lower()
    return cmd.split(" ", 1)[0].lower()


def _point_to_box(point: Any) -> Optional[Tuple[float, float, float, float]]:
    if not isinstance(point, (list, tuple)) or len(point) < 2:
        return None
    try:
        x = float(point[0])
        y = float(point[1])
    except Exception:
        return None
    eps = 0.01
    x0 = max(0.0, min(1.0, x - eps))
    y0 = max(0.0, min(1.0, y - eps))
    x1 = max(0.0, min(1.0, x + eps))
    y1 = max(0.0, min(1.0, y + eps))
    return (x0, y0, x1, y1)


def _box_from_payload(payload: Dict[str, Any], key: str = "box") -> Optional[Tuple[float, float, float, float]]:
    raw = payload.get(key)
    if isinstance(raw, (list, tuple)) and len(raw) >= 4:
        try:
            x0, y0, x1, y1 = [float(v) for v in raw[:4]]
            return (x0, y0, x1, y1)
        except Exception:
            return None
    return None


def _run_shell_command(cmd: str, shell: str, timeout_s: int) -> Dict[str, Any]:
    shell = (shell or "auto").strip().lower()
    if shell == "auto":
        shell = "powershell" if os.name == "nt" else "bash"
    try:
        if shell == "powershell":
            args = ["powershell", "-NoProfile", "-Command", cmd]
        elif shell == "cmd":
            args = ["cmd", "/c", cmd]
        else:
            args = ["bash", "-lc", cmd]
        proc = subprocess.run(args, capture_output=True, text=True, timeout=int(timeout_s))
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "")[:8000],
            "stderr": (proc.stderr or "")[:8000],
            "reason": None if proc.returncode == 0 else "command_failed",
        }
    except Exception as exc:
        return {"ok": False, "reason": f"command_error:{exc}"}


def _run_browser_dom(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from playwright.sync_api import Error as PlaywrightError
    except Exception as exc:
        return {"ok": False, "reason": f"playwright_import_failed:{exc}"}
    action = str(payload.get("action") or "").strip().lower()
    url = str(payload.get("url") or "").strip()
    selector = str(payload.get("selector") or "").strip()
    text = str(payload.get("text") or "").strip()
    alt_selectors = payload.get("alt_selectors") or []
    if not isinstance(alt_selectors, list):
        alt_selectors = []
    browser_name = str(payload.get("browser") or "chromium").strip().lower()
    channel = str(payload.get("channel") or "chrome").strip().lower()
    headless = payload.get("headless")
    timeout_s = int(payload.get("timeout_s") or 5)
    if timeout_s <= 0:
        timeout_s = 5
    post_goto_wait_ms = int(payload.get("post_goto_wait_ms") or 250)
    if post_goto_wait_ms < 0:
        post_goto_wait_ms = 0
    if headless is None:
        headless = not _has_display()
    else:
        headless = bool(headless)
    if action == "goto" and not url:
        return {"ok": False, "reason": "missing_url"}
    if url and url.lower().startswith("chrome://"):
        return {
            "ok": False,
            "reason": "chrome_url_not_supported",
            "hint": "Use regular https pages. For profile selection, launch Chrome with --profile-directory.",
        }
    if action in ("click", "type", "read") and not selector:
        return {"ok": False, "reason": "missing_selector"}
    try:
        with _BROWSER_LOCK:
            ctx = _get_context(headless)
            pages = list(ctx.pages) if hasattr(ctx, "pages") else []
            page = pages[0] if pages else ctx.new_page()
            if len(pages) > 1:
                for extra in pages[1:]:
                    try:
                        extra.close()
                    except Exception:
                        pass
            page.set_default_timeout(int(timeout_s * 1000))
            if url:
                page.goto(url, wait_until="domcontentloaded", timeout=int(timeout_s * 1000))
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=int(timeout_s * 1000))
                except Exception:
                    pass
                if post_goto_wait_ms:
                    page.wait_for_timeout(post_goto_wait_ms)
            elif action in ("click", "type", "read", "snapshot"):
                try:
                    current_url = page.url
                except Exception:
                    current_url = ""
                if not current_url or current_url == "about:blank":
                    return {"ok": False, "reason": "missing_url"}
            result: Dict[str, Any] = {"ok": True}
            if action == "click":
                ok = _try_click(page, selector, timeout_s)
                if not ok:
                    for alt in _build_alt_selectors(selector, alt_selectors):
                        if _try_click(page, alt, timeout_s):
                            ok = True
                            break
                if not ok:
                    return {"ok": False, "reason": "selector_not_found"}
            elif action == "type":
                ok = _try_type(page, selector, text, timeout_s)
                if not ok:
                    ok = _try_fill(page, selector, text, timeout_s)
                if not ok:
                    for alt in _build_alt_selectors(selector, alt_selectors):
                        if _try_type(page, alt, text, timeout_s) or _try_fill(page, alt, text, timeout_s):
                            ok = True
                            break
                if not ok and ("name='q'" in selector or "name=\"q\"" in selector):
                    ok = _try_fill_by_role(page, text, timeout_s)
                if not ok:
                    ok = _try_omnibox(page, text, timeout_s)
                if not ok:
                    return {"ok": False, "reason": "selector_not_found"}
                if payload.get("press"):
                    try:
                        page.keyboard.press(str(payload.get("press")))
                    except Exception:
                        pass
            elif action == "read":
                ok = _try_wait(page, selector, timeout_s)
                if not ok:
                    for alt in _build_alt_selectors(selector, alt_selectors):
                        if _try_wait(page, alt, timeout_s):
                            selector = alt
                            ok = True
                            break
                if not ok:
                    return {"ok": False, "reason": "selector_not_found"}
                result["content"] = page.inner_text(selector)
            elif action == "snapshot":
                result["accessibility"] = page.accessibility.snapshot()
            if _detect_recaptcha(page):
                return {"ok": False, "reason": "recaptcha_required"}
            return result
    except PlaywrightError as exc:
        return {"ok": False, "reason": f"playwright_error:{exc}"}
    except Exception as exc:
        return {"ok": False, "reason": f"playwright_error:{exc}"}


def _try_wait(page, selector: str, timeout_s: int) -> bool:
    try:
        loc = page.locator(selector)
        loc.wait_for(state="visible", timeout=int(timeout_s * 1000))
        return True
    except Exception:
        return False


def _try_click(page, selector: str, timeout_s: int) -> bool:
    try:
        loc = page.locator(selector)
        loc.wait_for(state="visible", timeout=int(timeout_s * 1000))
        loc.first.click()
        return True
    except Exception:
        return False


def _try_fill(page, selector: str, text: str, timeout_s: int) -> bool:
    try:
        loc = page.locator(selector)
        loc.wait_for(state="visible", timeout=int(timeout_s * 1000))
        loc.first.fill(text)
        return True
    except Exception:
        return False


def _try_type(page, selector: str, text: str, timeout_s: int) -> bool:
    try:
        loc = page.locator(selector)
        loc.wait_for(state="visible", timeout=int(timeout_s * 1000))
        try:
            loc.first.click()
        except Exception:
            pass
        try:
            loc.first.focus()
        except Exception:
            pass
        try:
            loc.first.fill("")
        except Exception:
            pass
        page.keyboard.type(text, delay=30)
        return True
    except Exception:
        return False


def _build_alt_selectors(selector: str, extra: List[str]) -> List[str]:
    alts: List[str] = [s for s in extra if isinstance(s, str) and s.strip()]
    if (
        "Search Google" in selector
        or "Search query" in selector
        or "name='q'" in selector
        or "name=\"q\"" in selector
    ):
        alts.extend(
            [
                "textarea[name='q']",
                "input[name='q']",
                "textarea[title='Search']",
                "input[title='Search']",
                "textarea[aria-label='Search query']",
            ]
        )
    seen = set()
    out: List[str] = []
    for s in alts:
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _try_fill_by_role(page, text: str, timeout_s: int) -> bool:
    for role in ("combobox", "textbox", "searchbox"):
        try:
            loc = page.get_by_role(role)
            if loc.count() <= 0:
                continue
            loc.first.wait_for(state="visible", timeout=int(timeout_s * 1000))
            loc.first.fill(text)
            return True
        except Exception:
            continue
    return False


def _try_omnibox(page, text: str, timeout_s: int) -> bool:
    try:
        page.bring_to_front()
    except Exception:
        pass
    try:
        combo = "Meta+L" if sys.platform == "darwin" else "Control+L"
        page.keyboard.press(combo)
        page.keyboard.type(text, delay=30)
        page.keyboard.press("Enter")
        return True
    except Exception:
        return False


def _detect_recaptcha(page) -> bool:
    try:
        iframe = page.locator("iframe[src*='recaptcha'], iframe[title*='recaptcha' i]")
        if iframe.count() > 0:
            try:
                if iframe.first.is_visible():
                    return True
            except Exception:
                return True
        widget = page.locator(".g-recaptcha, [data-sitekey]")
        if widget.count() > 0:
            try:
                if widget.first.is_visible():
                    return True
            except Exception:
                return True
    except Exception:
        return False
    return False


def _write_pid() -> None:
    try:
        _write_json(PID_PATH, {"pid": os.getpid(), "startedAt": _now_iso()})
    except Exception:
        return


def _cleanup_pid() -> None:
    try:
        if os.path.isfile(PID_PATH):
            os.remove(PID_PATH)
    except Exception:
        pass


class _CommandServiceHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Authorization, Content-Type, X-Auth-Token, X-Gui-Enabled-Plugins, X-User-Alias, X-Project-Id, X-Session-Id",
        )
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except Exception:
            length = 0
        if length <= 0:
            return {}
        data = self.rfile.read(length)
        try:
            payload = json.loads(data.decode("utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _admin_or_403(self) -> Optional[Dict[str, Any]]:
        user = _require_admin(self.headers)
        if not user:
            self._send_json(403, {"ok": False, "error": "Admin only"})
            return None
        return user

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Authorization, Content-Type, X-Auth-Token, X-Gui-Enabled-Plugins, X-User-Alias, X-Project-Id, X-Session-Id",
        )
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/health", "/v1/command_services/health"):
            self._send_json(200, {"ok": True, "service": "command_services"})
            return
        if path == "/v1/command_services/info":
            default_shell = "powershell" if os.name == "nt" else "bash"
            self._send_json(
                200,
                {
                    "ok": True,
                    "os": os.name,
                    "platform": sys.platform,
                    "default_shell": default_shell,
                    "playwright": _has_playwright(),
                },
            )
            return
        self._send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        payload = self._read_json()
        if path == "/v1/command_services/run_command":
            user = self._admin_or_403()
            if not user:
                return
            cmd = str(payload.get("command") or payload.get("cmd") or "").strip()
            if not cmd:
                self._send_json(400, {"ok": False, "error": "Missing command"})
                return
            allow_any = bool(payload.get("allow_any"))
            allowlist = _split_allowlist(payload.get("allowlist"))
            if not allow_any and allowlist:
                token = _first_token(cmd)
                if token not in allowlist:
                    self._send_json(403, {"ok": False, "error": f"Command blocked: {token}"})
                    return
            shell = str(payload.get("shell") or "auto")
            timeout_s = int(payload.get("timeout_s") or 30)
            result = _run_shell_command(cmd, shell, timeout_s)
            self._send_json(200, {"ok": True, "result": result})
            return
        if path == "/v1/command_services/screenshot":
            user = self._admin_or_403()
            if not user:
                return
            try:
                from .capture_screen import capture_screen
                image, monitor = capture_screen()
                uri = _img_to_data_uri(image)
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "image": uri,
                        "monitor": monitor or {},
                        "width": getattr(image, "width", None),
                        "height": getattr(image, "height", None),
                    },
                )
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": f"capture_failed:{exc}"})
            return
        if path == "/v1/command_services/browser":
            user = self._admin_or_403()
            if not user:
                return
            result = _run_browser_dom(payload)
            status = 200 if result.get("ok") else 400
            self._send_json(status, {"ok": bool(result.get("ok")), "result": result})
            return
        if path == "/v1/command_services/ui_action":
            user = self._admin_or_403()
            if not user:
                return
            if not is_ui_available():
                self._send_json(400, {"ok": False, "error": "ui_unavailable"})
                return
            action = str(payload.get("action") or payload.get("kind") or "").strip().lower()
            if not action:
                self._send_json(400, {"ok": False, "error": "missing_action"})
                return
            try:
                from .capture_screen import capture_screen
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": f"capture_import_failed:{exc}"})
                return
            monitor = payload.get("monitor") if isinstance(payload.get("monitor"), dict) else None
            if not monitor or not monitor.get("width") or not monitor.get("height"):
                try:
                    _img, monitor = capture_screen()
                except Exception as exc:
                    self._send_json(500, {"ok": False, "error": f"capture_failed:{exc}"})
                    return
            box = _box_from_payload(payload, "box")
            if box is None:
                point = payload.get("point")
                box = _point_to_box(point)
            try:
                if action in ("click", "left_click"):
                    if box is None:
                        raise RuntimeError("missing_box")
                    click_element_at(box, monitor, button="left", clicks=1)
                elif action in ("double_click", "left_double"):
                    if box is None:
                        raise RuntimeError("missing_box")
                    click_element_at(box, monitor, button="left", clicks=2)
                elif action in ("right_click", "right_single"):
                    if box is None:
                        raise RuntimeError("missing_box")
                    click_element_at(box, monitor, button="right", clicks=1)
                elif action == "drag":
                    start_box = _box_from_payload(payload, "start_box") or _point_to_box(payload.get("start_point"))
                    end_box = _box_from_payload(payload, "end_box") or _point_to_box(payload.get("end_point"))
                    if start_box is None or end_box is None:
                        raise RuntimeError("missing_drag_points")
                    drag_element(start_box, end_box, monitor)
                elif action == "scroll":
                    if box is None:
                        raise RuntimeError("missing_box")
                    direction = str(payload.get("direction") or "down").strip().lower()
                    amount = int(payload.get("amount") or 3)
                    scroll_at(box, monitor, direction=direction, amount=amount)
                elif action == "type":
                    text = str(payload.get("text") or "")
                    if box is not None:
                        click_element_at(box, monitor, button="left", clicks=1)
                    ok = type_text(text)
                    if not ok:
                        raise RuntimeError("type_failed")
                elif action in ("press", "hotkey"):
                    keys = payload.get("keys") or payload.get("key") or payload.get("button")
                    ok = press_keys(keys)
                    if not ok:
                        raise RuntimeError("press_failed")
                else:
                    self._send_json(400, {"ok": False, "error": "unsupported_action"})
                    return
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
                return
            self._send_json(200, {"ok": True, "result": {"ok": True}})
            return
        self._send_json(404, {"ok": False, "error": "not found"})


def main() -> None:
    _write_pid()
    atexit.register(_cleanup_pid)
    bind = os.environ.get("LLMLOADER2_COMMAND_SERVICE_BIND", HOST_BIND)
    port = int(os.environ.get("LLMLOADER2_COMMAND_SERVICE_PORT", HOST_PORT))
    try:
        server = ThreadingHTTPServer((bind, port), _CommandServiceHandler)
    except Exception as exc:
        print(f"[command_services] failed to bind {bind}:{port}: {exc}")
        return
    print(f"[command_services] listening on {bind}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
