
import os, json, requests
from tools.guidelines import compose_prompt_suffix

PROMPT = """You will generate a minimal unified diff patch for the target file based on the user's instruction.
Rules:
- Output only a unified diff (start with --- and +++) with correct paths (use the exact path given).
- Keep changes minimal and focused.
- Do not include commentary.
"""

def propose_patch(repo_id: str, file_path: str, instruction: str, llm_route: str, model: str, data_dir: str = None, project_id: str = None) -> dict:
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            src = f.read()
    except Exception as e:
        return {"ok": False, "error": f"read_error: {e}"}
    messages = [
        {"role":"system","content":"You output only a unified diff. No prose."},
        {"role":"user","content": PROMPT},
        {"role":"user","content": json.dumps({"repo_id": repo_id, "file": file_path, "instruction": instruction, "source": src})}
    ]
    r = requests.post(llm_route, json={"model": model, "messages": messages, "temperature": 0.0, "max_tokens": 1200}, timeout=180)
    j = r.json()
    diff = j.get("choices",[{}])[0].get("message",{}).get("content","")
    return {"ok": True, "diff": diff}
