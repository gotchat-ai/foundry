import json
import os
from pathlib import Path as _Path
from typing import Any, Dict, Optional

def _to_bool(v: Any) -> bool:
    if isinstance(v, bool): return v
    if v is None: return False
    return str(v).strip().lower() in ("1","true","yes","on","y")


def _to_int(v: Any) -> Optional[int]:
    if v is None or v == "": return None
    try: return int(v)
    except Exception: return None


def load_settings(path: str | None = None) -> Dict[str, Any]:
    #path = path or os.environ.get(SETTINGS_PATH_ENV, DEFAULT_SETTINGS_PATH)
    #path = path or _Path(__file__).parent.with_name("settings.json")
    path = path or _Path(__file__).with_name("settings.json")
    # sensible defaults for ALL create_app kwargs
    s: Dict[str, Any] = {
        "model_id": "distilgpt2",
        "device": "auto",
        "dtype": "auto",
        "chat_template": "default",
        "librag_headroom_frac": 0.20,
        "rag_preload_cold": False,
        "rag_preload_only": None,

        "schemes": True,
        "allow_http_scheme": False,
        "max_context_tokens": None,   # set an int if you want, e.g. 100_000
        "reserve_tokens": 0,

        "enable_summarize": True,
        "enable_rag": True,
        "embed_model": "sentence-transformers/all-MiniLM-L6-v2",

        "enable_user_rag": True,
        "rag_dir": None,
        "rag_autosave": True,
        "user_rag_dir": None,
        "user_rag_autosave": True,
        "use_fa2": True,
        "gen_workers": 4,
        "per_model_parallel": 1
    }

    # file overrides
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                # PROMOTE_LIB_RAG_PRELOAD: allow nested lib_rag keys in settings.json
                try:
                    _lib = data.get('lib_rag') or {}
                    if isinstance(_lib, dict):
                        if 'preload_cold' in _lib and 'rag_preload_cold' not in data:
                            data['rag_preload_cold'] = bool(_lib.get('preload_cold'))
                        if 'preload_only' in _lib and 'rag_preload_only' not in data:
                            data['rag_preload_only'] = _lib.get('preload_only')
                        if 'headroom_frac' in _lib and 'librag_headroom_frac' not in data:
                            data['librag_headroom_frac'] = _lib.get('headroom_frac')
                except Exception:
                    pass
                s.update({k: v for k, v in data.items() if v is not None})
                # print("s", s)
        except Exception as e:
            print(f"[settings] Warning: failed to read {path}: {e}")

    # env overrides (optional, short names)
    str_envs = [
        # ("librag_headroom_frac", "LIBRAG_HEADROOM_FRAC"),
        # ("rag_preload_only", "RAG_PRELOAD_ONLY"),
        # ("model_id", "MODEL"),
        # ("device", "DEVICE"),
        # ("dtype", "DTYPE"),
        # ("chat_template", "CHAT_TEMPLATE"),
        # ("embed_model", "EMBED_MODEL"),
        # ("rag_dir", "RAG_DIR"),
        # ("user_rag_dir", "USER_RAG_DIR"),
    ]
    for key, env in str_envs:
        v = os.environ.get(env)
        if v: s[key] = v

    bool_envs = [
        # ("rag_preload_cold", "RAG_PRELOAD_COLD"),
        # ("schemes", "SCHEMES"),
        # ("allow_http_scheme", "ALLOW_HTTP_SCHEME"),
        # ("enable_summarize", "ENABLE_SUMMARIZE"),
        # ("enable_rag", "ENABLE_RAG"),
        # ("enable_user_rag", "ENABLE_USER_RAG"),
        # ("rag_autosave", "RAG_AUTOSAVE"),
        # ("user_rag_autosave", "USER_RAG_AUTOSAVE"),
        # ("use_fa2", "USE_FA2"),
    ]
    for key, env in bool_envs:
        if env in os.environ:
            s[key] = _to_bool(os.environ[env])

    mct = _to_int(os.environ.get("MAX_CONTEXT_TOKENS"))
    if mct is not None: s["max_context_tokens"] = mct
    rt = _to_int(os.environ.get("RESERVE_TOKENS"))
    if rt is not None: s["reserve_tokens"] = rt

    return s
