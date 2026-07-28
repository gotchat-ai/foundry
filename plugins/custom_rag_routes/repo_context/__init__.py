
from __future__ import annotations
from typing import List
from ..base import BaseCustomRag, CustomRagCore
from .plugin import RepoContextRag


def build_custom_rags(core: CustomRagCore) -> List[BaseCustomRag]:
    return [RepoContextRag(core)]


def install_routes(app) -> None:
    from .plugin import install_routes as _install
    _install(app)


# from __future__ import annotations

# from typing import List

# from custom_rag_routes.base import CustomRagCore, BaseCustomRag

# from .plugin import RepoContextRag


# PLUGIN_ID = "repo_context"


# def build_custom_rags(core: CustomRagCore) -> List[BaseCustomRag]:
#     return [RepoContextRag(core)]
