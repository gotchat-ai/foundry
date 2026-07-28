from typing import List, Dict, Optional, Tuple, Any
import torch
import re
import traceback
import sys, json

SUMMARY_SYSTEM = (
    "You are a concise conversation summarizer. "
    "Write a compact, factual summary of the prior dialogue. "
    "Keep names, decisions, tasks, constraints, and any TODOs. "
    "Avoid fluff. Use short bullets or tight prose under 180-220 words."
)

def _format_dialog(messages: List[Dict[str, str]]) -> str:
    lines = []
    for m in messages:
        role = m.get("role","user")
        content = m.get("content","")
        lines.append(f"{role}: {content}")
    return "\n".join(lines)

def summarize_old_turns(model, tokenizer, old_messages: List[Dict[str,str]], existing_summary: Optional[str]=None, max_new_tokens: int = 196, temperature: float = 0.0, style: str = "compact") -> str:
    """
    Uses the same local model to summarize dropped turns.
    Returns a summary string (may include the existing summary folded in).
    """
    try:
        if not old_messages:
            return existing_summary or ""

        prior = _format_dialog(old_messages)
        STYLES = {
            'compact': SUMMARY_SYSTEM,
            'bullets': (
                'You are a concise conversation summarizer. Use 6-9 short bullets with bolded section tags: '
                'Entities, Goals, Constraints, Decisions, Numbers, TODO. Keep to ~180-220 tokens.'
            ),
            'facts': (
                'Summarize into terse, factual bullet points only. Preserve names, dates, amounts, IDs. 6-10 bullets.'
            ),
        }
        sys_prompt = STYLES.get(style, SUMMARY_SYSTEM)
        if existing_summary:
            prompt = (
                f"System: {sys_prompt}\n\n"
                f"Existing summary:\n{existing_summary}\n\n"
                f"New dialogue to merge:\n{prior}\n\n"
                f"Assistant:"
            )
        else:
            prompt = (
                f"System: {sys_prompt}\n\n"
                f"Dialogue:\n{prior}\n\n"
                f"Assistant:"
            )

        input_ids = tokenizer(prompt, return_tensors="pt").input_ids.to(model.device)
        with torch.no_grad():
            out = model.generate(
                input_ids=input_ids,
                do_sample=temperature > 0.0,
                temperature=max(0.01, float(temperature)),
                top_p=1.0,
                max_new_tokens=int(max_new_tokens),
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
        cont = out[0, input_ids.shape[-1]:]
        text = tokenizer.decode(cont, skip_special_tokens=True)
    except Exception as e:
        print(e)
        text = ""

    return text.strip()


def summarize_evidence(model, tokenizer, chunks: List[str], instruction: Optional[str] = None, max_new_tokens: int = 196, temperature: float = 0.0) -> str:
    """
    Compress multiple evidence texts into a terse, factual digest for recall.
    """
    if not chunks:
        return ""
    instr = instruction or ("Create a compact factual digest from the following notes. "
                            "Keep entities, numbers, constraints, and decisions. "
                            "Avoid fluff. Output 5-10 bullets.")
    joined = "\n\n".join(f"- {c.strip()}" for c in chunks if c.strip())
    prompt = (
        f"System: {instr}\n\n"
        f"Notes:\n{joined}\n\n"
        f"Assistant:"
    )
    input_ids = tokenizer(prompt, return_tensors="pt").input_ids.to(model.device)
    with torch.no_grad():
        out = model.generate(
            input_ids=input_ids,
            do_sample=temperature > 0.0,
            temperature=max(0.01, float(temperature)),
            top_p=1.0,
            max_new_tokens=int(max_new_tokens),
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )
    cont = out[0, input_ids.shape[-1]:]
    text = tokenizer.decode(cont, skip_special_tokens=True).strip()
    return text

from typing import Iterable

_DEFAULT_STOP = set("""a an the this that these those i you he she it we they me him her us them my your his her our their
is am are was were be been being do does did to for with at from into on by about as of and or but if then so because
than too very just not no nor only also either neither both each any all some such own same other more most much many few
over under again further once here there when where why how which who whom whose while during before after above below up down
out off in within without across between among per via until unless although though despite toward towards around
can could may might must shall should will would""".split())

def _word_tokenize(text: str) -> list:
    return re.findall(r"[A-Za-z0-9_'-]+", text)

def _sent_split(text: str) -> list:
    return re.split(r"(?<=[.!?])\s+", text.strip()) if text.strip() else []

def _keep_token(tok: str, tags: set, keep_numbers=True, keep_caps=True) -> bool:
    if not tok: return False
    low = tok.lower()
    if keep_numbers and re.fullmatch(r"[0-9][0-9,.\-]*", tok): return True
    if keep_caps and (tok[0].isupper() and not low in _DEFAULT_STOP): return True
    if low in tags: return True
    if low in _DEFAULT_STOP: return False
    # prefer longer/meaningful tokens
    return len(low) >= 4

def fragment_tags_summary(old_messages: List[Dict[str,str]], tags: List[str], trim_ratio: float = 0.75,
                          max_words: int = 220, max_lines: int = 9,
                          keep_numbers: bool = True, keep_caps: bool = True) -> str:
    """
    Hybrid 'tags + fragments' summary:
    - Builds a terse header with tags.
    - Emits sentence fragments keeping only important tokens (tags, CAPS, numbers, long words).
    - Reduces words by ~trim_ratio (e.g., 0.75 keeps ~25%).
    """
    tags = [t.strip().lower() for t in (tags or []) if t and t.strip()]
    tagset = set(tags)
    # Build raw text from dropped messages (user + assistant)
    text = "\n".join([m.get("content","") for m in old_messages if m.get("content")])
    if not text.strip():
        # nothing to summarize; still return tags header if any
        header = f"tags: {', '.join(tags)}" if tags else "tags: (none)"
        return header

    sents = _sent_split(text)
    # Token budget: keep ~ (1 - trim_ratio) words from original
    all_words = _word_tokenize(text)
    keep_words_target = max(32, int(len(all_words) * (1.0 - float(trim_ratio))))
    kept_total = 0
    lines = []

    for s in sents:
        toks = _word_tokenize(s)
        kept = [tok for tok in toks if _keep_token(tok, tagset, keep_numbers=keep_numbers, keep_caps=keep_caps)]
        if not kept:
            continue
        # Limit line to at most 1/3 of remaining budget to spread fragments
        remain = max(1, keep_words_target - kept_total)
        per_line_cap = max(4, int(remain / max(1, (max_lines - len(lines)))))
        kept = kept[:per_line_cap]
        kept_total += len(kept)
        lines.append(" ".join(kept))
        if kept_total >= keep_words_target or len(lines) >= max_lines:
            break

    header = f"tags: {', '.join(tags)}" if tags else "tags: (none)"
    if not lines:
        return header
    body = "\n- " + "\n- ".join(lines)
    return header + body



def classify_print_file_request(
    model,
    tokenizer,
    msgs: list[dict],
    max_new_tokens: int = 64,
) -> Dict[str, Any]:
    """
    Ask the model: is the user asking to print/show a code file?
    Return a dict like:
        {
          "print_file": bool,
          "repo_id": str or null,
          "path": str or null
        }
    """
    print("classify_print_file_request")
    if not msgs:
        return {"print_file": False, "repo_id": None, "path": None}

    try:
        # System + user prompt; adjust wording as you like
        system_prompt = (
            "You are a JSON-only intent classifier for a code assistant.\n"
            "Given the user's message, decide if they are asking to print or show "
            "the full contents of a source code file from a repository that was "
            "previously ingested.\n\n"
            "Rules:\n"
            "- If they are asking to see a file's contents (e.g., 'show me src/foo.py', "
            "  'print the file foo.py', 'dump main.py'), set print_file to true.\n"
            "- Otherwise, set print_file to false.\n"
            "- If possible, extract repo_id and path from the repo note value from system 'Path:' and 'Repo:' (path like 'foo.py').\n"
            "- If you don't know repo_id or path, set them to null.\n\n"
            "Respond with ONLY a single JSON object, no explanation, like:\n"
            "{\n"
            '  \"print_file\": true,\n'
            '  \"repo_id\": \"my-repo\",\n'
            '  \"path\": \"foo.py\"\n'
            "}\n"
        )

        #print("msgs for file sys:", msgs)
        
        sys_messages =  {"role": "system", "content": system_prompt}

        msgs.insert(0, sys_messages)

        #msgs = sys_messages + msgs[:-1] + [msgs[-1]]

        print("msgs for file sys:", msgs)

        # Simple chat-style prompt; adapt if you already use a chat template
        prompt = ""
        for m in msgs:
            if m.get("role") == "system":
                prompt += f"<|system|>\n{m.get('content')}\n"
            elif m["role"] == "user":
                prompt += f"<|user|>\n{m.get('content')}\n"
        prompt += "<|assistant|>\n"

        # inputs = tokenizer(prompt, return_tensors="pt")
        # inputs = {k: v.to(model.device) for k, v in inputs.items()}

        # with torch.no_grad():
        #     out = model.generate(
        #         **inputs,
        #         max_new_tokens=max_new_tokens,
        #         do_sample=False,
        #         temperature=0.0,
        #         pad_token_id=tokenizer.eos_token_id,
        #     )

        # text = tokenizer.decode(out[0], skip_special_tokens=True)

        input_ids = tokenizer(prompt, return_tensors="pt").input_ids.to(model.device)
        with torch.no_grad():
            out = model.generate(
                input_ids=input_ids,
                top_p=1.0,
                max_new_tokens=int(max_new_tokens),
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
        cont = out[0, input_ids.shape[-1]:]
        text = tokenizer.decode(cont, skip_special_tokens=True)

        # Extract JSON object from the model output
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {"print_file": False, "repo_id": None, "path": None}

        json_str = text[start : end + 1]
        print("json_str", json_str)
        try:
            data = json.loads(json_str)
        except Exception:
            return {"print_file": False, "repo_id": None, "path": None}

        # Normalize output
        print_file = bool(data.get("print_file"))
        repo_id = data.get("repo_id")
        path = data.get("path")

        if repo_id is not None and not isinstance(repo_id, str):
            repo_id = None
        if path is not None and not isinstance(path, str):
            path = None
    except Exception as e:
        print(e)
        # print(34234235325)
        repo_id = None
        path = None
        print_file = False
        exc_type, exc_value, exc_traceback = sys.exc_info()
        tb_list = traceback.extract_tb(exc_traceback)
        last_frame = tb_list[-1]  # Get the last frame where the error occurred

        print(f"Error occurred in file: {last_frame.filename}")
        print(f"On line: {last_frame.lineno}")
        print(f"In function: {last_frame.name}")
        print(f"Code line: {last_frame.line}")

    return {"print_file": print_file, "repo_id": repo_id, "path": path}
