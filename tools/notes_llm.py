
import os, json, requests, concurrent.futures, time

SCHEMA = {
  "summary": "",
  "inputs": [],
  "outputs": [],
  "side_effects": [],
  "invariants": [],
  "exceptions": [],
  "concurrency": [],
  "risks": [],
  "suggestions": []
}

PROMPT_TMPL = """You are a senior code reviewer. Given a Python symbol (function/class/module) with its source code snippet, write a concise JSON with:
- summary (1-3 sentences, terse and precise)
- inputs (name/type/meaning)
- outputs (type/meaning)
- side_effects (filesystem, network, db, globals)
- invariants (pre/post-conditions that should hold)
- exceptions (which exceptions are raised and why)
- concurrency (threading/async pitfalls)
- risks (bugs or fragile logic)
- suggestions (specific, practical improvements)

Return ONLY valid JSON, with keys: summary, inputs, outputs, side_effects, invariants, exceptions, concurrency, risks, suggestions.
"""

def _make_msg(model: str, chunk: dict) -> dict:
    code = chunk.get("text","")
    header = f"{chunk.get('fqn')} {chunk.get('signature','')}\nFile: {chunk.get('file')}\nLines: {chunk.get('start_line')}-{chunk.get('end_line')}"
    content = f"{header}\n\n```python\n{code}\n```"
    return {
        "model": model,
        "messages": [
            {"role":"system","content": PROMPT_TMPL},
            {"role":"user","content": content}
        ],
        "temperature": 0.1,
        "max_tokens": 512
    }

def enrich_notes(settings: dict, notes_path: str, out_path: str) -> str:
    conf = (settings or {}).get("analysis", {})
    model = conf.get("llm_model", "gpt-local")
    route = conf.get("llm_route", "/v1/chat/completions")
    base = (settings or {}).get("base_url", "http://127.0.0.1:8000")
    parallel = int(conf.get("parallel_workers", 4) or 4)

    rows = []
    with open(notes_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                pass

    ses = requests.Session()

    def _one(row):
        try:
            body = _make_msg(model, row)
            r = ses.post(base + route, json=body, timeout=60)
            j = r.json()
            txt = j.get("choices",[{}])[0].get("message",{}).get("content","{}")
            try:
                data = json.loads(txt)
            except Exception:
                data = {"summary": txt.strip(), **{k:[] for k in ["inputs","outputs","side_effects","invariants","exceptions","concurrency","risks","suggestions"]}}
            return {"symbol": row, "analysis": data}
        except Exception as e:
            return {"symbol": row, "error": str(e)}

    out = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as ex:
        for res in ex.map(_one, rows):
            out.append(res)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for rec in out:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return out_path
