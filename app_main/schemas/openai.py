from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    user_assoc_persist: Optional[bool] = False
    user_assoc_scope: Optional[str] = "session"  # 'session'|'user'|'both'
    user_id: Optional[str] = None
    user_assoc_expand: Optional[bool] = True
    session_id: Optional[str] = None
    max_context_tokens: Optional[int] = None
    reserve_tokens: Optional[int] = None
    use_rag: bool = False
    rag_query: Optional[str] = None
    rag_top_k: int = 3
    rag_max_chars: int = 1200
    use_user_rag: bool = True
    urag_query: Optional[str] = None
    urag_top_k: int = 4
    urag_max_chars: int = 1200
    auto_user_rag: bool = True
    urag_policy: str = "auto"  # auto|latest_checkpoint|all_by_tag|all|unsure
    urag_min_hits: int = 2
    urag_fallback_k: int = 20
    urag_fallback_all_k: int = 50
    llm_unsure_hint: bool = False
    context_extender: bool = True
    extender_mode: str = "hybrid"  # digest|quotes|hybrid
    extender_top_k: int = 6
    extender_quote_chars: int = 240
    extender_digest_tokens: int = 180
    extender_max_tokens: int = 512
    extender_min_score: Optional[float] = None
    extender_recency_tau: Optional[float] = 1209600  # 14 days in seconds
    extender_recency_alpha: float = 0.35  # blend: 0=sim only, 1=recency only
    extender_dedupe_across_turns: bool = True
    # RepoRAG knobs
    use_repo_rag: bool = False
    repo_id: Optional[str] = None
    repo_scope: str = "cold"  # hot|cold|both
    repo_search_k: int = 8
    repo_min_score: Optional[float] = None
    repo_recency_alpha: float = 0.35
    repo_hot_first: bool = True
    is_revisit: Optional[bool] = None
    repo_only_on_revisit: bool = True

    summarize: bool = True
    summary_max_tokens: int = 196
    summary_min_tokens: int = 96
    summary_style: str = "bullets"   # compact|bullets|facts
    summary_adaptive: bool = True
    summary_mode: str = "auto"        # auto|always|off|hybrid_frag|tags_frag
    summary_trim_ratio: float = 0.75
    summary_frag_max_words: int = 220
    summary_frag_max_lines: int = 9
    sum_compression: float = 12.0
    quote_compression: float = 6.0
    model: str
    messages: List[ChatMessage]
    temperature: float = 0.7
    max_tokens: int = 256
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    stream: bool = False
    stop: Optional[List[str]] = None
    is_revisit: Optional[bool] = None


class ChoiceMessage(BaseModel):
    role: str
    content: str


class Choice(BaseModel):
    index: int
    message: ChoiceMessage
    finish_reason: Optional[str]


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[Choice]
    usage: Usage


class ChatCompletionExtRequestBase(BaseModel):
    user_assoc_persist: Optional[bool] = False
    user_assoc_scope: Optional[str] = "session"  # 'session'|'user'|'both'
    user_id: Optional[str] = None
    user_assoc_expand: Optional[bool] = True
    model: Optional[str] = None
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    temperature: Optional[float] = 0.2
    max_tokens: Optional[int] = 512
    use_lib_rag: Optional[bool] = False
    lib_ids: Optional[List[str]] = None
    lib_auto_enable_by_tags: Optional[bool] = True
    lib_preferred_tags: Optional[List[str]] = None
    lib_top_k: Optional[int] = 4
    lib_min_score: Optional[float] = 0.08
    lib_tags_any: Optional[List[str]] = None
    lib_tags_all: Optional[List[str]] = None
    # Backend + thinking model selection (per-session)
    backend_type: Optional[str] = None   # "hf" | "hf_assist" | "vllm"
    quant: Optional[str] = None          # main-model quant hint (e.g. "none","8bit")
    thinking_model: Optional[str] = None
    thinking_quant: Optional[str] = None
    attn_mode: Optional[str] = None
    # reserve_tokens: Optional[int] = 2048
    # max_context_tokens: Optional[int] = 100000
    gpu_vram_percent: Optional[int] = None
    sid: Optional[str] = None
    client_msg_id: Optional[str] = None

    # routing + OS-Atlas / VLM controls
    router_enabled_plugins: Optional[List[str]] = None
    route_id: Optional[str] = None

    # Generic extension dict (what chat_tk sends)
    ext: Optional[Dict[str, Any]] = None
