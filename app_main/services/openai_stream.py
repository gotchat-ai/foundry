import json
import time
from typing import Any, Iterable


class OpenAIStreamFormatter:
    """Formats text chunks as OpenAI-compatible chat completion SSE bytes."""

    def stream_sse(self, chunks: Iterable[str], req_id: str, model_alias: str) -> Iterable[bytes]:
        first = True
        for piece in chunks:
            if piece is None:
                continue
            delta_obj: dict[str, Any] = {"content": piece}
            if first:
                delta_obj["role"] = "assistant"
                first = False
            payload = {
                "id": req_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model_alias,
                "choices": [
                    {
                        "index": 0,
                        "delta": delta_obj,
                        "finish_reason": None,
                    }
                ],
            }
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")

        payload = {
            "id": req_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model_alias,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
        }
        yield f"data: {json.dumps(payload)}\n\n".encode("utf-8")
        yield b"data: [DONE]\n\n"
