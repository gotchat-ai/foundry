
import os, json, requests

def _load_jsonl(path):
    rows = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try: rows.append(json.loads(line))
                except Exception: pass
    return rows

PROMPT = """You are a senior reviewer. Given repository notes and static issues, propose concrete, high‑leverage improvements.
Return strict JSON with this schema:
{"suggestions":[{"title":str,"rationale":str,"files":[str],"risk":"low|med|high","benefit":"low|med|high","actions":[{"type":"refactor|bugfix|test|doc","target_file":str,"target_symbol":str|null,"instruction":str}]}]}
Keep it concise and technically actionable."""

def suggest(repo_id: str, data_dir: str, llm_route: str = "/v1/chat/completions", model: str = "gpt-local", limit: int = 12) -> dict:
    base = os.path.join(data_dir, "analysis", repo_id)
    notes = _load_jsonl(os.path.join(base, "notes_enriched.jsonl"))
    if not notes:
        notes = _load_jsonl(os.path.join(base, "notes.jsonl"))
    issues_path = os.path.join(base, "issues.jsonl")
    issues = _load_jsonl(issues_path)

    # trim
    notes = notes[:800]
    issues = issues[:1500]

    messages = [
        {"role":"system","content":"You output only JSON. No prose."},
        {"role":"user","content": PROMPT},
        {"role":"user","content": json.dumps({"repo_id":repo_id, "notes":notes, "issues":issues})}
    ]

    try:
        r = requests.post(llm_route, json={"model": model, "messages": messages, "temperature": 0.1, "max_tokens": 1200}, timeout=120)
        j = r.json()
        txt = j.get("choices",[{}])[0].get("message",{}).get("content","{}")
        data = json.loads(txt)
    except Exception as e:
        data = {"suggestions":[{"title":"LLM suggestion failed","rationale":str(e),"files":[],"risk":"med","benefit":"low","actions":[]}]} 

    # cap
    data["suggestions"] = data.get("suggestions", [])[:limit]
    # store
    out_path = os.path.join(base, "llm_suggestions.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"ok": True, "path": out_path, "count": len(data.get("suggestions",[]))}
