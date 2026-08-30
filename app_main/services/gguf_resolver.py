import os
import threading
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from fastapi import HTTPException
from huggingface_hub import hf_hub_download

_INVALID_MODEL_ID_VALUES = {"", "none", "null", "undefined", "nan"}


def _clean_model_ref(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in _INVALID_MODEL_ID_VALUES else text


class GGUFResolverService:
    """Resolve GGUF references, cache metadata, and serve GGUF info responses."""

    def __init__(
        self,
        *,
        app_getter: Callable[[], Any],
        settings_getter: Callable[[], dict[str, Any]],
    ) -> None:
        self._app_getter = app_getter
        self._settings_getter = settings_getter
        app = self._app_getter()
        if not hasattr(app.state, "gguf_info_cache"):
            app.state.gguf_info_cache = {}
        if not hasattr(app.state, "gguf_path_cache"):
            app.state.gguf_path_cache = {}
        if not hasattr(app.state, "gguf_info_lock"):
            app.state.gguf_info_lock = threading.Lock()

    def settings(self) -> dict[str, Any]:
        return self._settings_getter() or {}

    def looks_like_gguf_id(self, value: str) -> bool:
        value = _clean_model_ref(value)
        if not value:
            return False
        return ".gguf" in value.lower()

    def parse_hf_url(self, url: str) -> tuple[str, str]:
        url = _clean_model_ref(url)
        if not url:
            raise ValueError("empty Hugging Face GGUF URL")
        parsed = urlparse(url)
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 3:
            if len(parts) >= 2:
                repo_id = "/".join(parts[0:2])
                filename = parts[-1]
                return repo_id, filename
            raise ValueError(f"Cannot parse Hugging Face GGUF URL: {url}")

        owner = parts[0]
        repo = parts[1]
        filename = parts[-1]
        repo_id = f"{owner}/{repo}"
        return repo_id, filename

    def hf_download_gguf_from_hf_url(self, url: str) -> str:
        repo_id, filename = self.parse_hf_url(url)
        settings = self.settings()
        models_dir = settings.get("models_dir") or settings.get("hf_cache_dir") or "./models"
        local_root = Path(models_dir).expanduser().resolve() / "gguf"
        local_root.mkdir(parents=True, exist_ok=True)

        local_path = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            local_dir=str(local_root),
            local_dir_use_symlinks=False,
        )

        path = Path(local_path).expanduser().resolve()
        if not path.is_file():
            raise RuntimeError(f"hf_hub_download returned non-file path: {path}")
        return str(path)

    def parse_hf_gguf_url_like_vllama(self, url: str) -> tuple[str, str]:
        url = _clean_model_ref(url)
        if not url:
            raise ValueError("empty Hugging Face GGUF URL")
        parsed = urlparse(url)
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 3:
            if len(parts) >= 2:
                repo_id = "/".join(parts[0:2])
                filename = parts[-1]
                return repo_id, filename
            raise ValueError(f"Cannot parse Hugging Face GGUF URL: {url}")

        owner = parts[0]
        repo = parts[1]
        filename = parts[-1]
        repo_id = f"{owner}/{repo}"
        return repo_id, filename

    def looks_like_hf_gguf_ref(self, value: str) -> bool:
        text = _clean_model_ref(value)
        if not text or ".gguf" not in text.lower():
            return False
        if text.startswith("http://") or text.startswith("https://"):
            parsed = urlparse(text)
            return parsed.netloc in ("huggingface.co", "www.huggingface.co")
        parts = [part for part in text.strip("/").split("/") if part]
        if len(parts) >= 5 and parts[2] in ("blob", "resolve"):
            return True
        if len(parts) >= 3 and parts[-1].lower().endswith(".gguf") and not os.path.isabs(text):
            return True
        return False

    def is_local_gguf_file(self, path: Path) -> bool:
        try:
            local_path = path.expanduser()
            if not local_path.is_file():
                return False
            if local_path.suffix.lower() == ".gguf":
                return True
            with local_path.open("rb") as handle:
                return handle.read(4) == b"GGUF"
        except Exception:
            return False

    def hf_cache_roots(self) -> list[str]:
        settings = self.settings()
        roots = []
        if settings.get("hf_cache_dir"):
            roots.append(settings.get("hf_cache_dir"))
        if os.getenv("HUGGINGFACE_HUB_CACHE"):
            roots.append(os.getenv("HUGGINGFACE_HUB_CACHE"))
        if os.getenv("HF_HOME"):
            roots.append(os.path.join(os.getenv("HF_HOME"), "hub"))
        if settings.get("models_dir"):
            roots.append(settings.get("models_dir"))
        return [os.path.abspath(root) for root in roots if root]

    def resolve_from_cache(self, repo_id: str, filename: str) -> Optional[str]:
        repo_id = _clean_model_ref(repo_id)
        filename = _clean_model_ref(filename)
        if not repo_id or not filename:
            return None
        model_dir = "models--" + repo_id.replace("/", "--")
        for root in self.hf_cache_roots():
            model_root = os.path.join(root, model_dir)
            if not os.path.isdir(model_root):
                try:
                    print(f"[gguf_info] cache miss root={root} model_dir={model_dir} (not found)")
                except Exception:
                    pass
                continue
            refs = os.path.join(model_root, "refs", "main")
            sha = None
            try:
                if os.path.isfile(refs):
                    with open(refs, "r", encoding="utf-8") as handle:
                        sha = handle.read().strip()
            except Exception:
                sha = None
            snaps_dir = os.path.join(model_root, "snapshots")
            if sha:
                candidate = os.path.join(snaps_dir, sha, filename)
                if os.path.isfile(candidate):
                    try:
                        print(f"[gguf_info] cache hit root={root} file={candidate}")
                    except Exception:
                        pass
                    return candidate
            if os.path.isdir(snaps_dir):
                try:
                    snapshots = [
                        item
                        for item in os.listdir(snaps_dir)
                        if os.path.isdir(os.path.join(snaps_dir, item))
                    ]
                except Exception:
                    snapshots = []
                snapshots.sort(
                    key=lambda item: os.path.getmtime(os.path.join(snaps_dir, item)),
                    reverse=True,
                )
                for snapshot in snapshots:
                    candidate = os.path.join(snaps_dir, snapshot, filename)
                    if os.path.isfile(candidate):
                        try:
                            print(f"[gguf_info] cache hit root={root} file={candidate}")
                        except Exception:
                            pass
                        return candidate
        try:
            print(f"[gguf_info] cache miss repo={repo_id} file={filename}")
        except Exception:
            pass
        return None

    def resolve_gguf_path(self, model_id: str) -> str:
        text = _clean_model_ref(model_id)
        if not text:
            raise RuntimeError("empty GGUF model id")

        path = Path(text).expanduser()
        if self.is_local_gguf_file(path):
            return str(path.resolve())
        if not self.looks_like_hf_gguf_ref(text):
            if os.path.isabs(text) or os.path.splitdrive(text)[0]:
                raise RuntimeError(f"GGUF local path not found: {text}")

        if text.startswith("http://") or text.startswith("https://"):
            parsed = urlparse(text)
            if parsed.netloc in ("huggingface.co", "www.huggingface.co"):
                repo_id, filename = self.parse_hf_gguf_url_like_vllama(text)
            else:
                raise RuntimeError(f"Non-HF GGUF URLs not supported yet: {text}")
        elif self.looks_like_hf_gguf_ref(text):
            fake_url = f"https://huggingface.co/{text.lstrip('/')}"
            repo_id, filename = self.parse_hf_gguf_url_like_vllama(fake_url)
        else:
            raise RuntimeError(f"Cannot resolve GGUF model id: {text!r}")

        cached = self.resolve_from_cache(repo_id, filename)
        if cached:
            return str(Path(cached).expanduser().resolve())

        from downloaders.hf_downloader import safe_hf_download

        settings = self.settings()
        cache_dir = settings.get("hf_cache_dir") or settings.get("models_dir")
        result = safe_hf_download(
            repo_id=repo_id,
            filename=filename,
            revision="main",
            cache_dir=cache_dir,
            local_files_only=True,
            force=False,
            etag_timeout=int(settings.get("hf_etag_timeout", 15)),
        )
        if not getattr(result, "ok", True):
            result = safe_hf_download(
                repo_id=repo_id,
                filename=filename,
                revision="main",
                cache_dir=cache_dir,
                local_files_only=False,
                force=False,
                etag_timeout=int(settings.get("hf_etag_timeout", 15)),
            )
        if not getattr(result, "ok", True):
            raise RuntimeError(getattr(result, "error", "failed to download GGUF"))
        resolved_path = getattr(result, "path", None) or getattr(result, "paths", [None])[0]
        if not resolved_path:
            raise RuntimeError("safe_hf_download did not return a path")
        path2 = Path(resolved_path).expanduser().resolve()
        if not path2.is_file():
            raise RuntimeError(f"GGUF local path missing: {path2}")
        return str(path2)

    def get_cached_gguf_info(self, model_id: str) -> tuple[int, int, Optional[str]]:
        key = (model_id or "").strip()
        if not key:
            raise HTTPException(400, "model_id required")
        app = self._app_getter()
        cache = getattr(app.state, "gguf_info_cache", None)
        lock = getattr(app.state, "gguf_info_lock", None)
        if isinstance(cache, dict):
            cached = cache.get(key)
            if cached:
                return (
                    int(cached.get("n_layers") or 0),
                    int(cached.get("file_size_bytes") or 0),
                    cached.get("warning"),
                )

        if lock:
            lock.acquire()
        try:
            if isinstance(cache, dict):
                cached = cache.get(key)
                if cached:
                    return (
                        int(cached.get("n_layers") or 0),
                        int(cached.get("file_size_bytes") or 0),
                        cached.get("warning"),
                    )
            local_path = self.resolve_gguf_path(key)
            path_cache = getattr(app.state, "gguf_path_cache", None)
            if isinstance(path_cache, dict) and local_path:
                path_cache[key] = local_path
            try:
                file_size = os.path.getsize(local_path)
            except Exception:
                file_size = 0

            try:
                from plugins.model_loader.model_deck.local_loaders.gguf_bridge import (
                    _first_meta_value,
                    _get_cached_gguf_meta,
                )

                meta = _get_cached_gguf_meta(app, key, local_path)
                arch = str(meta.get("general.architecture") or "").strip()
                keys = []
                if arch:
                    keys.extend([f"{arch}.block_count", f"{arch}.n_layer"])
                keys.extend(["llama.block_count", "llama.n_layer", "block_count", "n_layer"])
                value = _first_meta_value(meta, *keys)
                n_layers = int(value or 0)
                warning = None
            except Exception:
                n_layers = 0
                warning = None

            if n_layers is None:
                n_layers = 0
                warning = (
                    "Could not determine GGUF layer count; "
                    "this model may use a very new or unsupported format. "
                    "You can still run it, but GPU offload slider will be disabled."
                )

            info = {
                "n_layers": int(n_layers or 0),
                "file_size_bytes": int(file_size or 0),
                "warning": warning,
            }
            if isinstance(cache, dict):
                cache[key] = info
            return info["n_layers"], info["file_size_bytes"], info["warning"]
        finally:
            if lock:
                try:
                    lock.release()
                except Exception:
                    pass

    def model_gguf_info(self, req: Any, response_cls: Callable[..., Any]) -> Any:
        model_id = _clean_model_ref(getattr(req, "model_id", ""))
        if not model_id:
            raise HTTPException(400, "model_id required")
        n_layers, file_size, warning = self.get_cached_gguf_info(model_id)
        return response_cls(n_layers=n_layers, file_size_bytes=int(file_size), warning=warning)
