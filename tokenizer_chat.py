from typing import List, Dict

# Very simple templates; you can expand these as needed.
_TEMPLATES = {
    "default": "System: {system}\n\n{dialog}\nAssistant:",
    "alpaca": "Below is an instruction that describes a task. Write a response that appropriately completes the request.\n\n### Instruction:\n{system}\n\n{dialog}\n\n### Response:",
    "plain": "{dialog}\nAssistant:",
}


def build_prompt(messages: List[Dict], template: str = "default") -> str:
    system = """You are a helpful, concise assistant.
                If the user asks for downloadable files or a zip, include a fenced code block:
                attach
                {
                "files": [{"name":"README.txt","text":"..."}],
                "zip": "bundle.zip"
                }
                I (the server) will create the files/zip and show download links in the chat.
                Do not wrap the block in markdown other than the attach fence. Use valid JSON."""
    dialog_lines = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "system":
            system = content
        elif role == "user":
            dialog_lines.append(f"User: {content}")
        elif role == "assistant":
            dialog_lines.append(f"Assistant: {content}")
        else:
            dialog_lines.append(f"{role.capitalize()}: {content}")
    dialog = "\n".join(dialog_lines)
    fmt = _TEMPLATES.get(template, _TEMPLATES["default"])
    return fmt.format(system=system, dialog=dialog)


def estimate_tokens(tokenizer, text: str) -> int:
    return len(tokenizer.encode(text))


def pack_messages(messages: List[Dict], tokenizer, template: str, max_context_tokens: int, reserve_tokens: int = 256) -> List[Dict]:
    """
    Return a trimmed message list that fits within max_context_tokens (approx),
    keeping the most recent turns while preserving one system message if present.

    We approximate token length by re-building the prompt as we grow the window
    from the tail (newest messages). This is slower but simple and robust.
    """
    # Pull first system message (if any)
    system_msg = None
    rest = []
    for m in messages:
        if m.get("role") == "system" and system_msg is None:
            system_msg = m
        else:
            rest.append(m)

    # Start from the end, add messages until token budget exceeded
    kept = []
    budget = max(0, int(max_context_tokens) - int(reserve_tokens))
    def prompt_len(msgs):
        txt = build_prompt(([system_msg] if system_msg else []) + list(reversed(msgs)), template)
        return len(tokenizer.encode(txt))

    for m in reversed(rest):
        test = kept + [m]
        if prompt_len(test) <= budget:
            kept = test
        else:
            break

    trimmed = ([system_msg] if system_msg else []) + list(reversed(kept))
    return trimmed
