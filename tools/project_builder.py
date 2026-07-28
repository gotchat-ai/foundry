
import os, json, requests, re

PLAN_PROMPT = """You generate a full, minimal repository that meets the user's project requirements.
Return strict JSON: {"files":[{"path":str,"content":str}]}.
Rules:
- Use only these file extensions when appropriate: {allowed_exts}.
- Keep it minimal but runnable; include README.md and requirements/config files if relevant.
- Do not include binary files or archives. No base64.
- Use Unix newlines.
"""

def _safe_relpath(p: str) -> str:
    p = p.replace("\\","/")
    p = re.sub(r"^/+","", p)
    p = re.sub(r"\.+/","", p)
    p = p.strip()
    # prevent traversal
    parts = []
    for q in p.split("/"):
        if q in ("", ".", ".."): continue
        parts.append(q)
    return "/".join(parts)

def llm_plan(requirements: str, allowed_exts: list[str], llm_route: str, model: str, max_tokens=3500) -> dict:
    messages = [
        {"role":"system","content":"You output only JSON. No prose."},
        {"role":"user","content": PLAN_PROMPT.format(allowed_exts=allowed_exts)},
        {"role":"user","content": requirements}
    ]
    r = requests.post(llm_route, json={"model": model, "messages": messages, "temperature": 0.1, "max_tokens": max_tokens}, timeout=180)
    j = r.json()
    txt = j.get("choices",[{}])[0].get("message",{}).get("content","{}")
    try:
        data = json.loads(txt)
    except Exception:
        data = {"files":[]}
    files = []
    for it in data.get("files", []):
        path = _safe_relpath(str(it.get("path",""))) or "README.md"
        ext = os.path.splitext(path)[1].lower()
        if allowed_exts and ext and ext not in allowed_exts:
            continue
        content = str(it.get("content",""))
        files.append({"path": path, "content": content})
    return {"files": files[:500]}
