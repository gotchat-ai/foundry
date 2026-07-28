import argparse
import errno
import json
import os
import re
import hashlib
import urllib.error
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class ChatJsHandler(SimpleHTTPRequestHandler):
    CLIENT_PROXY_PATH = "/v1/client/"
    API_PROXY_PATH = "/v1/"
    BACKEND_PROXY_BASE = os.environ.get("LLMLOADER2_GUI_BACKEND_BASE", "http://127.0.0.1:8000")
    _BACKEND_HOST_ALIASES = {"127.0.0.1", "localhost", "host.docker.internal", "::1"}

    def end_headers(self):
        # Allow embedding across origins (embed.js fetches chat_js.htm + chat_js.css).
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization, X-Auth-Token, X-Gui-Enabled-Plugins",
        )
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Cross-Origin-Resource-Policy", "cross-origin")
        path = urllib.parse.urlsplit(self.path).path
        no_store = (
            path in {"/embed.js", "/chat_js.js", "/plugins/manifest.json"}
            or path.endswith("/embed.js")
            or path.endswith("/chat_js.js")
            or (
                path.startswith("/plugins/")
                and path.endswith((".js", ".mjs", ".json"))
            )
        )
        if no_store:
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        return super().end_headers()

    def list_directory(self, path):
        self.send_error(404, "Not Found")
        return None

    def _proxy_request(self, target_base: str):
        target = f"{target_base}{self.path}"
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length > 0 else None
        headers = {}
        for key in (
            "Accept",
            "Content-Type",
            "Authorization",
            "X-Auth-Token",
            "X-Gui-Enabled-Plugins",
            "X-User-Alias",
            "X-Project-Id",
            "X-Session-Id",
            "X-Guest-Id",
            "X-Events-Token",
        ):
            value = self.headers.get(key)
            if value:
                headers[key] = value
        req = urllib.request.Request(
            target,
            data=body,
            headers=headers,
            method=self.command,
        )
        path = urllib.parse.urlsplit(self.path).path
        expects_sse = path.endswith("/events") or str(self.headers.get("Accept") or "").lower().find("text/event-stream") >= 0
        try:
            with urllib.request.urlopen(req, timeout=None if expects_sse else 60) as resp:
                content_type = resp.headers.get("Content-Type", "application/json")
                is_sse = "text/event-stream" in str(content_type or "").lower()
                if is_sse:
                    self.send_response(resp.status)
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Content-Type", content_type)
                    self.send_header("Cache-Control", "no-cache, no-store, must-revalidate, no-transform")
                    self.send_header("Pragma", "no-cache")
                    self.send_header("X-Accel-Buffering", "no")
                    self.end_headers()
                    stream = getattr(resp, "fp", None) or resp
                    while True:
                        chunk = stream.readline()
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    return
                payload = resp.read()
                payload = self._rewrite_proxy_payload(payload, content_type)
                self.send_response(resp.status)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
        except urllib.error.HTTPError as exc:
            content_type = exc.headers.get("Content-Type", "text/plain")
            is_sse = "text/event-stream" in str(content_type or "").lower()
            if is_sse and exc.fp:
                self.send_response(exc.code)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate, no-transform")
                self.send_header("Pragma", "no-cache")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                stream = getattr(exc.fp, "fp", None) or exc.fp
                while True:
                    chunk = stream.readline()
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
                return
            payload = exc.read() if exc.fp else b""
            payload = self._rewrite_proxy_payload(payload, content_type)
            self.send_response(exc.code)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if payload:
                self.wfile.write(payload)
        except Exception as exc:
            msg = f"backend proxy failed for {target}: {exc}".encode("utf-8")
            self.send_response(502)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

    def _proxy_client_service(self):
        return self._proxy_request("http://127.0.0.1:8766")

    def _proxy_api_service(self):
        return self._proxy_request(self.BACKEND_PROXY_BASE)

    def _rewrite_proxy_payload(self, payload: bytes, content_type: str) -> bytes:
        if not payload:
            return payload
        if "application/json" not in str(content_type or "").lower():
            return payload
        try:
            data = json.loads(payload.decode("utf-8"))
        except Exception:
            return payload
        rewritten = self._rewrite_json_value(data)
        try:
            return json.dumps(rewritten, ensure_ascii=False).encode("utf-8")
        except Exception:
            return payload

    def _rewrite_json_value(self, value):
        if isinstance(value, dict):
            return {key: self._rewrite_json_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._rewrite_json_value(item) for item in value]
        if isinstance(value, str):
            return self._rewrite_json_string(value)
        return value

    def _rewrite_json_string(self, value: str) -> str:
        text = str(value or "")
        if not text:
            return text
        if text.startswith("/gui_js/plugins/"):
            return text[len("/gui_js") :]
        rewritten = self._rewrite_backend_url(text)
        if rewritten != text:
            return rewritten
        return re.sub(r'https?://[^\s"\')]+', lambda m: self._rewrite_backend_url(m.group(0)), text)

    def _rewrite_backend_url(self, value: str) -> str:
        text = str(value or "").strip()
        if not text.lower().startswith(("http://", "https://")):
            return text
        try:
            parsed = urllib.parse.urlsplit(text)
        except Exception:
            return text
        backend = urllib.parse.urlsplit(self.BACKEND_PROXY_BASE)
        host = str(parsed.hostname or "").strip().lower()
        if host not in self._BACKEND_HOST_ALIASES and host != str(backend.hostname or "").strip().lower():
            return text
        path = parsed.path or "/"
        if path.startswith("/gui_js/plugins/"):
            path = path[len("/gui_js") :]
        if path.startswith("/v1/") or path.startswith("/plugins/"):
            rewritten = path
            if parsed.query:
                rewritten = f"{rewritten}?{parsed.query}"
            if parsed.fragment:
                rewritten = f"{rewritten}#{parsed.fragment}"
            return rewritten
        return text

    def _rewrite_root(self):
        if self.path in ("", "/", "/index.html"):
            self.path = "/chat_js.htm"

    def _serve_plugin_manifest(self):
        def _plugin_rev(dir_path: str) -> str:
            try:
                h = hashlib.sha1()
                for root, dirs, files in os.walk(dir_path):
                    dirs.sort()
                    files.sort()
                    for name in files:
                        try:
                            full = os.path.join(root, name)
                            st = os.stat(full)
                            rel = os.path.relpath(full, dir_path).replace(os.sep, "/")
                            h.update(rel.encode("utf-8", "ignore"))
                            h.update(b"|")
                            h.update(str(int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000)))).encode("ascii"))
                            h.update(b"|")
                            h.update(str(int(st.st_size)).encode("ascii"))
                            h.update(b"\n")
                        except Exception:
                            continue
                return h.hexdigest()[:16]
            except Exception:
                return ""

        base_dir = os.path.abspath(getattr(self, "directory", "") or os.getcwd())
        plugins_dir = os.path.join(base_dir, "plugins")
        plugins = []
        if os.path.isdir(plugins_dir):
            for name in sorted(os.listdir(plugins_dir), key=str.lower):
                plugin_dir = os.path.join(plugins_dir, name)
                if not os.path.isdir(plugin_dir):
                    continue
                manifest = {}
                manifest_path = os.path.join(plugin_dir, "manifest.json")
                if os.path.isfile(manifest_path):
                    try:
                        with open(manifest_path, "r", encoding="utf-8") as handle:
                            loaded = json.load(handle)
                        if isinstance(loaded, dict):
                            manifest = loaded
                    except Exception:
                        manifest = {}
                entry = str(
                    manifest.get("entry")
                    or manifest.get("path")
                    or manifest.get("main")
                    or "plugin.js"
                ).strip()
                if not entry:
                    entry = "plugin.js"
                entry_path = os.path.join(plugin_dir, entry)
                if not os.path.isfile(entry_path):
                    entry = ""
                    for candidate in ("plugin.js", "plugin.mjs", "index.js", "index.mjs"):
                        if os.path.isfile(os.path.join(plugin_dir, candidate)):
                            entry = candidate
                            break
                if not entry:
                    continue
                item = {
                    "id": str(manifest.get("id") or name),
                    "name": str(manifest.get("name") or manifest.get("id") or name),
                    "kind": str(manifest.get("kind") or "gui"),
                    "description": str(manifest.get("description") or ""),
                    "path": f"./plugins/{name}/{entry.replace(os.sep, '/')}",
                }
                if manifest.get("category"):
                    item["category"] = str(manifest.get("category") or "").strip()
                rev = _plugin_rev(plugin_dir)
                if rev:
                    item["rev"] = rev
                plugins.append(item)
        payload = json.dumps({"plugins": plugins}, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path.startswith(self.CLIENT_PROXY_PATH):
            return self._proxy_client_service()
        if self.path.startswith(self.API_PROXY_PATH):
            return self._proxy_api_service()
        if urllib.parse.urlsplit(self.path).path == "/plugins/manifest.json":
            return self._serve_plugin_manifest()
        self._rewrite_root()
        return super().do_GET()

    def do_HEAD(self):
        if self.path.startswith(self.CLIENT_PROXY_PATH) or self.path.startswith(self.API_PROXY_PATH):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Auth-Token, X-Gui-Enabled-Plugins, X-User-Alias, X-Project-Id, X-Session-Id")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
            self.end_headers()
            return None
        self._rewrite_root()
        return super().do_HEAD()

    def do_POST(self):
        if self.path.startswith(self.CLIENT_PROXY_PATH):
            return self._proxy_client_service()
        if self.path.startswith(self.API_PROXY_PATH):
            return self._proxy_api_service()
        self.send_error(405, "Method Not Allowed")
        return None

    def do_PUT(self):
        if self.path.startswith(self.CLIENT_PROXY_PATH):
            return self._proxy_client_service()
        if self.path.startswith(self.API_PROXY_PATH):
            return self._proxy_api_service()
        self.send_error(405, "Method Not Allowed")
        return None

    def do_OPTIONS(self):
        if self.path.startswith(self.CLIENT_PROXY_PATH) or self.path.startswith(self.API_PROXY_PATH):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Auth-Token, X-Gui-Enabled-Plugins, X-User-Alias, X-Project-Id, X-Session-Id")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
            self.end_headers()
            return None
        self.send_error(405, "Method Not Allowed")
        return None


def main():
    parser = argparse.ArgumentParser(description="Serve chat_js.htm without directory listing.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--strict-port",
        action="store_true",
        help="Fail instead of trying the next port when the requested port is already in use.",
    )
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.abspath(__file__))

    def handler(*handler_args, **handler_kwargs):
        return ChatJsHandler(*handler_args, directory=base_dir, **handler_kwargs)

    port = args.port
    server = None
    while True:
        try:
            server = ThreadingHTTPServer((args.host, port), handler)
            break
        except OSError as exc:
            in_use_codes = {errno.EADDRINUSE}
            if hasattr(errno, "WSAEADDRINUSE"):
                in_use_codes.add(errno.WSAEADDRINUSE)
            if args.strict_port or exc.errno not in in_use_codes or port >= args.port + 20:
                raise
            print(f"Port {port} is already in use; trying {port + 1}...")
            port += 1
    print(f"Serving chat_js at http://{args.host}:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
