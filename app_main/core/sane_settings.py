from __future__ import annotations


class SaneSettingsService:
    def _compute_sane_settings_by_ctx(self, ctx_limit: int) -> dict:
        try:
            ctx = int(ctx_limit or 32000)
        except Exception:
            ctx = 32000

        # reply_max ~2% of ctx (1k..4k)
        reply_max = max(1024, min(4096, int(ctx * 0.02)))
        # reserve ~12% of ctx (2k..20k)
        reserve = max(2000, min(20000, int(ctx * 0.12)))

        # recent_turns scales sublinearly: 12 @32k, ~30 @100k, clamp [10,50]
        import math

        recent = max(10, min(50, int(round(12 * ((ctx / 32000.0) ** 0.65)))))

        # summary strategy
        if ctx <= 24000:
            sratio = 0.60
        elif ctx <= 64000:
            sratio = 0.75
        else:
            sratio = 0.80
        # hard cap for rolling summary: min(5% of ctx, 5000), floor 1200
        sc_cap = max(1200, min(5000, int(ctx * 0.05)))

        # RAG token budgets scale with ctx; clamp to practical ranges
        urag_budget = max(1000, min(6000, int(ctx * 0.035)))
        librag_budget = max(800, min(4000, int(ctx * 0.020)))

        # Cold rotation target
        if ctx <= 48000:
            target_cold = 0.30
        elif ctx <= 120000:
            target_cold = 0.35
        else:
            target_cold = 0.40

        # Compute sane LibRAG promotion settings based on model context.
        # Keeps a tiny 'working set' pinned hot to stabilize multi-turn reasoning.
        ctx = max(8192, int(ctx or 0))
        print("ctx: ", ctx)
        # Total rag budget (not enforced here; FYI only)
        _ = min(int(0.08 * ctx), 7000)

        # Promotion budget ~1.5% ctx, bounded
        promote_tokens_cap = max(900, min(int(0.015 * ctx), 2000))
        snippet_char_cap = 900 if ctx >= 64000 else 800
        top_k = 5 if ctx >= 64000 else 4
        min_score = 0.18 if ctx >= 64000 else 0.20

        sane = {
            "max_context_tokens": ctx,
            "max_tokens": reply_max,
            "reserve_tokens": reserve,
            "recent_turns": recent,
            "summary_trim_ratio": sratio,
            "summary_tokens_cap": sc_cap,
            "pressure_mode": True,
            "user_assoc_expand": True,
            "user_rag": {
                "top_k": 6,
                "min_score": 0.10,
                "recency_boost": 0.20,
                "assoc_k_each": 2,
                "snippet_char_cap": 900,
                "budget_tokens": urag_budget,
                "dedup_last_turns": 40,
            },
            "lib_rag": {
                "top_k": 3,
                "min_score": 0.14,
                "recency_boost": 0.15,
                "assoc_k_each": 2,
                "snippet_char_cap": 700,
                "budget_tokens": librag_budget,
            },
            "target_cold_pct": target_cold,
            "min_cold_rotate_pct": 0.05,
            "assoc_compaction": {"interval_sec": 21600, "decay": 0.98, "min_count": 0.5},
            "librag_refresh": {"interval_sec_default": 86400},
            "promote_librag_hits": True,
            "promote": {
                "min_score": float(min_score),
                "top_k": int(top_k),
                "snippet_char_cap": int(snippet_char_cap),
                "tokens_cap": int(promote_tokens_cap),
                "ttl_sec": 3600,
                "dedup_last_turns": 40,
            },
        }
        return sane
