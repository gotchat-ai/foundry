from __future__ import annotations
import os, json, time
from typing import List, Dict
def _proj_dir(data_dir: str, repo_id: str) -> str:
    p = os.path.join(data_dir, "projects", repo_id); os.makedirs(p, exist_ok=True); return p

def _qa_path(data_dir: str, repo_id: str) -> str: return os.path.join(_proj_dir(data_dir, repo_id), "qa.jsonl")

def append(data_dir: str, repo_id: str, payload: dict) -> dict:
    qa_id = payload.get("qa_id") or f"qa_{time.strftime('%Y-%m-%d_%H%M%S')}"
    row = {"qa_id": qa_id,"when": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),"actor": payload.get("actor") or "user",
           "type": (payload.get("type") or payload.get("kind") or "").lower(),"title": payload.get("title","").strip(),
           "body": payload.get("body","").strip(),"severity": (payload.get("severity") or "med").lower(),
           "labels": payload.get("labels") or payload.get("tags") or [],"attachments": payload.get("attachments") or [],
           "status": payload.get("status") or "new"}
    path = _qa_path(data_dir, repo_id); os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path,"a",encoding="utf-8").write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"ok": True, "qa_id": qa_id, "path": path}

def list(data_dir: str, repo_id: str, status: str = "", q: str = "", qtype: str = "") -> dict:
    path = _qa_path(data_dir, repo_id); rows: List[dict] = []
    if os.path.isfile(path):
        for line in open(path,"r",encoding="utf-8"): 
            try: rows.append(json.loads(line))
            except Exception: pass
    if status: rows = [r for r in rows if (r.get("status") or "") == status]
    if qtype: rows = [r for r in rows if (r.get("type") or "") == qtype.lower()]
    if q: rows = [r for r in rows if q.lower() in (r.get("title","")+r.get("body","")).lower()]
    return {"ok": True, "items": rows}

def update_status(data_dir: str, repo_id: str, qa_id: str, status: str) -> dict:
    path = _qa_path(data_dir, repo_id)
    if not os.path.isfile(path): return {"ok": False, "error": "qa_not_found"}
    rows: List[dict] = []; 
    for line in open(path,"r",encoding="utf-8"):
        try: rows.append(json.loads(line))
        except Exception: pass
    changed = False
    for r in rows:
        if r.get("qa_id") == qa_id: r["status"] = status; changed = True
    if not changed: return {"ok": False, "error": "qa_id_not_found"}
    tmp = path + ".tmp"; f=open(tmp,"w",encoding="utf-8")
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n"); f.close()
    os.replace(tmp, path); return {"ok": True, "qa_id": qa_id, "status": status}