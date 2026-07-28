from __future__ import annotations
import os, json, re, time, hashlib, requests
from typing import List
TRIAGE_PROMPT = ("Normalize and triage each QA input.\n"
    "Return strict JSON: {\"items\":[{\"qa_id\":str,\"classification\":{\"type\":\"bug|feature|question|request\",\"priority\":\"p1|p2|p3\",\"component\":str},\"dedupe_key\":str,\"links\":{\"files\":[str],\"symbols\":[str]},\"acceptance\":[str]}]}")
def _proj_dir(data_dir: str, repo_id: str) -> str:
    p = os.path.join(data_dir, "projects", repo_id); os.makedirs(p, exist_ok=True); return p

def _read_jsonl(path: str) -> List[dict]:
    rows = []; 
    if not os.path.isfile(path): return rows
    for line in open(path,"r",encoding="utf-8"):
        try: rows.append(json.loads(line))
        except Exception: pass
    return rows

def _sha(s: str) -> str: return hashlib.sha256(s.encode("utf-8","ignore")).hexdigest()[:16]

def _link_symbols(data_dir: str, repo_id: str, items: List[dict]) -> None:
    # optional: link to analysis symbols if available
    sym_p = os.path.join(data_dir, "analysis", repo_id, "symbols.jsonl")
    if not os.path.isfile(sym_p): return
    syms = []
    for line in open(sym_p,"r",encoding="utf-8"):
        try: syms.append(json.loads(line))
        except Exception: pass
    for it in items:
        txt = (it.get("qa_id","") + " " + json.dumps(it,ensure_ascii=False)).lower()
        best = [s for s in syms if s.get("fqn") and s.get("file") and s.get("fqn","").split(".")[-1].lower() in txt]
        it.setdefault("links",{}).setdefault("symbols",[])
        for s in best[:5]:
            it["links"]["symbols"].append(s.get("fqn"))

def run_triage(repo_id: str, data_dir: str, llm_route: str, model: str) -> dict:
    pdir = _proj_dir(data_dir, repo_id); qa_path = os.path.join(pdir, "qa.jsonl"); rows = _read_jsonl(qa_path)
    items = []
    try:
        msgs = [{"role":"system","content":TRIAGE_PROMPT},{"role":"user","content":json.dumps(rows, ensure_ascii=False)}]
        j = requests.post(llm_route, json={"model": model, "messages": msgs, "temperature": 0.1, "max_tokens": 1500}, timeout=120).json()
        txt = j.get("choices",[{}])[0].get("message",{}).get("content","{}"); out = json.loads(txt)
        if isinstance(out, dict) and isinstance(out.get("items"), list): items = out["items"]
    except Exception: pass
    if not items:
        for r in rows:
            t = (r.get("type") or "").lower()
            if t not in ("bug","feature","question","request"):
                t = "question" if "?" in (r.get("title","")+r.get("body","")) else "request"
            pri = "p1" if r.get("severity") in ("critical","high") else "p2"
            comp = ""
            m = re.search(r"(/v1/\S+)", (r.get("body","")+r.get("title","")))
            if m: comp = m.group(1)
            items.append({"qa_id": r.get("qa_id"),"classification":{"type": t, "priority": pri, "component": comp},
                          "dedupe_key": _sha((r.get("title","")+t).lower()),"links":{"files": [], "symbols": []},
                          "acceptance":[f"Resolve: {r.get('title') or r.get('body')[:60]}"]})
    _link_symbols(data_dir, repo_id, items)
    triage = {"items": items}; out_path = os.path.join(pdir, "triage.json")
    open(out_path,"w",encoding="utf-8").write(json.dumps(triage, ensure_ascii=False, indent=2))
    return {"ok": True, "count": len(items), "path": out_path}