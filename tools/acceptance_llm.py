
import os, json, requests

PROMPT = """You are an acceptance reviewer. Determine if the current repository satisfies the project requirements.
Return strict JSON: {"pass": bool, "reasons": [str], "missing": [str]}
Be conservative: only pass if core requirements and functionality are clearly implemented in the codebase."""

def evaluate(repo_id: str, data_dir: str, requirements: str, llm_route: str, model: str) -> dict:
    base = os.path.join(data_dir, "analysis", repo_id)
    notes_p = os.path.join(base, "notes_enriched.jsonl")
    if not os.path.exists(notes_p):
        notes_p = os.path.join(base, "notes.jsonl")
    issues_p = os.path.join(base, "issues.jsonl")
    notes = []
    if os.path.exists(notes_p):
        with open(notes_p,"r",encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i>1200: break
                try: notes.append(json.loads(line))
                except: pass
    issues = []
    if os.path.exists(issues_p):
        with open(issues_p,"r",encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i>2000: break
                try: issues.append(json.loads(line))
                except: pass
    messages = [
        {"role":"system","content":"You output only JSON. No prose."},
        {"role":"user","content": PROMPT},
        {"role":"user","content": json.dumps({"requirements": requirements, "notes": notes, "issues": issues})}
    ]
    try:
        r = requests.post(llm_route, json={"model": model, "messages": messages, "temperature": 0.0, "max_tokens": 800}, timeout=120)
        j = r.json()
        txt = j.get("choices",[{}])[0].get("message",{}).get("content","{}")
        data = json.loads(txt)
        if not isinstance(data, dict):
            data = {"pass": False, "reasons": ["bad_llm_output"], "missing": []}
    except Exception as e:
        data = {"pass": False, "reasons": [f"error:{e}"], "missing": []}
    return data
