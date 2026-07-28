"""
model_loader_update.py

Experimental extension of HFChatModel that adds per-token "thinking" introspection
based on attention shifts while generating. This implements Option B from our
discussion: intermittent qualitative summaries at significant points during
generation, rather than every token.

Usage (conceptual):
    from model_loader import HFChatModel
    from model_loader_update import HFChatModelUpdate

    # Use HFChatModelUpdate instead of HFChatModel when you want introspection.
    model = HFChatModelUpdate(...)
    for piece in model.stream_chat_thinking(messages, ...):
        if piece["kind"] == "thinking":
            # show piece["summary"] in diag/log UI
        elif piece["kind"] == "token":
            # append piece["text"] to the streaming assistant message
"""

from __future__ import annotations

from typing import Generator, List, Optional, Dict, Any

import torch

try:
    # Re-use your existing HFChatModel implementation.
    from model_loader import HFChatModel
except Exception as _e:
    HFChatModel = object  # type: ignore

try:
    # Re-use your existing HFChatModel implementation.
    from model_loader_with_paging import HFChatModelWithPaging
except Exception as _e:
    HFChatModelWithPaging = object  # type: ignore


class ThinkingTracer:
    """
    Tracks attention patterns over time and emits a qualitative summary only
    when the model's focus has shifted significantly.

    Heuristic:
      - We look at the last-layer attention for the *current* token over the
        entire context (prompt + previously generated tokens).
      - We compare the new attention vector to the previous one (L1 distance).
      - If the change exceeds a threshold AND at least `min_step_gap` tokens
        have been generated since the last emission, we surface a new summary.
    """
    def __init__(
        self,
        tokenizer,
        threshold: float = 0.25,
        min_step_gap: int = 8,
    ) -> None:
        self.tokenizer = tokenizer
        self.threshold = float(threshold)
        self.min_step_gap = int(min_step_gap)
        self.prev_att: Optional[torch.Tensor] = None  # 1D tensor (seq,)
        self.step: int = 0
        self.last_emitted_step: int = -10

    def maybe_summarize(
        self,
        all_input_ids: torch.Tensor,  # shape: (1, seq_len)
        att_mean: torch.Tensor,       # shape: (seq_len,)
        max_segments: int = 5,
    ) -> Optional[Dict[str, Any]]:
        """
        Decide whether to emit a new "thinking" summary based on the attention
        shift. Returns a dict when there is a significant shift, else None.
        """
        # Defensive: ensure 1D vector
        if att_mean.dim() != 1:
            att_mean = att_mean.view(-1)

        self.step += 1

        # Rate limit: don't emit too frequently
        if self.step - self.last_emitted_step < self.min_step_gap:
            self.prev_att = att_mean
            return None

        # If we have a previous attention vector with same length, measure shift.
        if self.prev_att is not None and self.prev_att.shape == att_mean.shape:
            diff = (att_mean - self.prev_att).abs().mean().item()
            if diff < self.threshold:
                # Focus hasn't changed enough; skip.
                self.prev_att = att_mean
                return None

        # At this point we consider this a "significant" attention shift.
        self.last_emitted_step = self.step
        self.prev_att = att_mean

        scores = att_mean.tolist()
        token_seq = all_input_ids[0]  # (seq_len,)

        # Rank positions by attention strength.
        idx_scores = list(enumerate(scores))
        idx_scores.sort(key=lambda t: t[1], reverse=True)
        top = [i for i, _ in idx_scores[:max_segments]]

        segments: List[Dict[str, Any]] = []
        used_spans: List[tuple[int, int]] = []

        for pos in top:
            pos_int = int(pos)
            start = max(0, pos_int - 8)
            end = min(int(token_seq.shape[0]), pos_int + 9)
            span = (start, end)
            # Avoid overlapping spans to keep snippets diverse.
            if any(not (end <= s or start >= e) for s, e in used_spans):
                continue
            used_spans.append(span)

            seg_text = self.tokenizer.decode(
                token_seq[start:end],
                skip_special_tokens=True,
            ).strip()
            if seg_text:
                segments.append({"pos": pos_int, "text": seg_text})

        if not segments:
            return None

        summary_lines: List[str] = ["Model focus shifted; now emphasizing:"]
        for i, seg in enumerate(segments, start=1):
            summary_lines.append(f"{i}. {seg['text']}")

        return {
            "type": "attention_shift",
            "step": self.step,
            "segments": segments,
            "summary": "\n".join(summary_lines),
        }


class HFChatModelUpdate(HFChatModel):  # type: ignore[misc]
    """
    Extension of HFChatModel that adds a per-token introspective stream:

      - stream_generate_thinking: low-level generator over tokens + "thinking" events.
      - stream_chat_thinking: chat-shaped wrapper around stream_generate_thinking.

    NOTE: This implementation uses a *naive* per-token loop without KV caching
    (use_cache=False) to keep the code straightforward. For large models or very
    long generations, you may want to optimize this by integrating past_key_values.
    """

    def _build_chat_inputs(self, messages: List[Dict[str, Any]]):
        """
        Rebuilds the chat prompt the same way as HFChatModel.stream_chat does,
        returning a dict of tensors suitable for passing to the model.
        """
        if getattr(self, "model", None) is None or getattr(self, "tokenizer", None) is None:
            raise RuntimeError("No model loaded. Call /v1/models/load first.")

        fattn_tokenizer_param = self._resolve_tokenizer_attn_mask()

        # Build input ids from messages using HF chat template if available
        if hasattr(self.tokenizer, "apply_chat_template"):
            # messages = [{"role":"user"/"assistant"/"system", "content":".."}...]
            text = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
            inputs = self.tokenizer(text, return_tensors="pt", **fattn_tokenizer_param)
        else:
            # Simple fallback: join messages with role headers.
            joined = ""
            for m in messages:
                role = m.get("role", "user")
                content = m.get("content", "")
                joined += f"[{role.upper()}]\n{content}\n"
            inputs = self.tokenizer(joined, return_tensors="pt", **fattn_tokenizer_param)

        # Move to the same device as model embeddings.
        dev = self.model.get_input_embeddings().weight.device
        nb = (dev.type == "cuda")
        inputs = {
            k: (v.to(dev, non_blocking=nb) if torch.is_tensor(v) else v)
            for k, v in inputs.items()
        }
        # Ensure attention_mask is bool and contiguous if present.
        if "attention_mask" in inputs:
            inputs["attention_mask"] = inputs["attention_mask"].to(
                dev, dtype=torch.bool, non_blocking=nb
            ).contiguous()
        return inputs

    def stream_generate_thinking(
        self,
        inputs: Dict[str, torch.Tensor],
        cancel_cb=None,
        temperature: float = 0.7,
        top_p: float = 0.95,
        max_new_tokens: int = 256,
        stop: Optional[List[str]] = None,
        threshold: float = 0.25,
        min_step_gap: int = 8,
    ) -> Generator[Dict[str, Any], None, None]:
        """
        Per-token generation loop with attention-based "thinking" summaries.

        Yields dicts of the form:
           {"kind": "thinking", "data": <thinking dict>}
           {"kind": "token", "text": "<token text>"}

        The "thinking" dict is what ThinkingTracer.maybe_summarize(...) returns.
        """
        if getattr(self, "model", None) is None or getattr(self, "tokenizer", None) is None:
            raise RuntimeError("No model loaded. Call /v1/models/load first.")

        device = self.model.get_input_embeddings().weight.device

        # Make a working copy of the full input ids (prompt + generated).
        all_ids = inputs["input_ids"].to(device)
        tracer = ThinkingTracer(
            tokenizer=self.tokenizer,
            threshold=threshold,
            min_step_gap=min_step_gap,
        )

        eos_id = getattr(self.tokenizer, "eos_token_id", None)

        def _check_cancel() -> bool:
            try:
                return bool(cancel_cb()) if cancel_cb else False
            except Exception:
                return False

        for _step in range(int(max_new_tokens)):
            if _check_cancel():
                break

            seq_len = all_ids.shape[1]
            attn_mask = torch.ones_like(all_ids, dtype=torch.bool, device=device)

            with torch.no_grad():
                outputs = self.model(
                    input_ids=all_ids,
                    attention_mask=attn_mask,
                    use_cache=False,
                    output_attentions=True,
                )

            # Extract last-layer attention for the final position.
            atts = getattr(outputs, "attentions", None)
            if atts:
                last_att = atts[-1][:, :, -1, :]        # (1, heads, seq_len)
                att_mean = last_att.mean(dim=1)[0]      # (seq_len,)
                thinking = tracer.maybe_summarize(all_ids, att_mean)
                if thinking is not None:
                    yield {"kind": "thinking", "data": thinking}

            logits = outputs.logits[:, -1, :]           # (1, vocab)
            # Apply temperature + top_p sampling
            logits = logits / max(float(temperature), 1e-5)
            probs = torch.softmax(logits, dim=-1)

            # Top-p filtering
            if float(top_p) < 1.0:
                sorted_probs, sorted_indices = torch.sort(probs, descending=True)
                cumulative = torch.cumsum(sorted_probs, dim=-1)
                mask = cumulative > float(top_p)
                # Shift mask right to always keep at least one token
                mask[..., 1:] = mask[..., :-1].clone()
                mask[..., 0] = False
                sorted_probs = sorted_probs.masked_fill(mask, 0.0)
                sorted_probs = sorted_probs / sorted_probs.sum(dim=-1, keepdim=True)
                next_token = torch.multinomial(sorted_probs, num_samples=1)
                next_token_id = sorted_indices.gather(-1, next_token)
            else:
                next_token_id = torch.multinomial(probs, num_samples=1)

            next_token_id = next_token_id[0, 0]

            # Stopping based on EOS
            if eos_id is not None and int(next_token_id.item()) == int(eos_id):
                break

            # Append new token to the full sequence and continue.
            next_token_tensor = next_token_id.view(1, 1).to(device)
            all_ids = torch.cat([all_ids, next_token_tensor], dim=1)

            # Decode token text; let the caller handle stop strings.
            piece_text = self.tokenizer.decode(
                [int(next_token_id.item())],
                skip_special_tokens=False,
            )
            if stop:
                # Apply simple stop truncation to the piece
                for s in stop:
                    idx = piece_text.find(s)
                    if idx != -1:
                        piece_text = piece_text[:idx]
                        # We stop generation if a stop sequence appears in this token span.
                        break
                if piece_text == "":
                    break

            yield {"kind": "token", "text": piece_text}

    def stream_chat_thinking(
        self,
        messages: List[Dict[str, Any]],
        max_new_tokens: int = 256,
        temperature: float | None = 0.7,
        top_p: float | None = 0.95,
        stop: Optional[List[str]] = None,
        cancel_cb=None,
        threshold: float = 0.25,
        min_step_gap: int = 8,
    ) -> Generator[Dict[str, Any], None, None]:
        """
        Chat-shaped wrapper around stream_generate_thinking.

        Parameters mirror stream_chat, but we yield dicts:
          - {"kind": "thinking", "data": {...}}
          - {"kind": "token", "text": "..."}

        The app layer (e.g., chat_completions_stream in app.py) can map:
          - "thinking" -> SSE "diag" event with data["summary"]
          - "token"    -> SSE "token" event with streaming text
        """
        inputs = self._build_chat_inputs(messages)
        for item in self.stream_generate_thinking(
            inputs=inputs,
            cancel_cb=cancel_cb,
            temperature=float(temperature or 0.7),
            top_p=float(top_p or 0.95),
            max_new_tokens=int(max_new_tokens or 0),
            stop=stop,
            threshold=threshold,
            min_step_gap=min_step_gap,
        ):
            yield item
