from __future__ import annotations

import importlib
import pkgutil
from typing import List

from .base import BaseCustomRag, CustomRagCore, CustomRagApplyInput
from .loader import load_custom_rags
from .manager import CustomRagManager

__all__ = ["BaseCustomRag", "CustomRagCore", "CustomRagApplyInput", "load_custom_rags", "CustomRagManager"]


# def load_custom_rags(core: CustomRagCore) -> List[BaseCustomRag]:
#     """Discover and instantiate all Custom-RAG plugins.

#     Each custom_rag_routes.<plugin> package may define:
#       - PLUGIN_ID: str (optional)
#       - build_custom_rags(core) -> list[BaseCustomRag]

#     Plugins are always discovered; enable/disable is per-request.
#     """
#     rags: List[BaseCustomRag] = []

#     import custom_rag_routes as _pkg

#     for info in pkgutil.iter_modules(_pkg.__path__):
#         if not info.ispkg:
#             continue
#         name = info.name
#         if name.startswith("_"):
#             continue

#         module_name = f"{_pkg.__name__}.{name}"
#         try:
#             module = importlib.import_module(module_name)
#         except Exception as exc:
#             print(f"[custom_rag] failed to import {module_name}: {exc}")
#             continue

#         build = getattr(module, "build_custom_rags", None)
#         if build is None:
#             continue

#         try:
#             built = build(core) or []
#         except Exception as exc:
#             print(f"[custom_rag] build_custom_rags failed for {module_name}: {exc}")
#             continue

#         for rag in built:
#             if isinstance(rag, BaseCustomRag):
#                 rags.append(rag)

#     return rags
