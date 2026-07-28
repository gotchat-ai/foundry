from __future__ import annotations
import os, json, re, glob
def _proj_dir(data_dir: str, repo_id: str) -> str:
    p = os.path.join(data_dir, "projects", repo_id); os.makedirs(p, exist_ok=True); return p

def _load_triage(data_dir: str, repo_id: str) -> dict:
    path = os.path.join(_proj_dir(data_dir, repo_id), "triage.json")
    try: return json.load(open(path,"r",encoding="utf-8"))
    except Exception: return {"items":[]}

def capability_index(data_dir: str, repo_id: str) -> dict:
    root = os.path.join(data_dir, "repos", repo_id); caps = {"endpoints": [], "features": [], "cli": []}
    app_p = os.path.join(root, "app.py")
    if os.path.isfile(app_p):
        txt = open(app_p,"r",encoding="utf-8",errors="ignore").read()
        for m in re.finditer(r'@app\.(get|post|put|patch|delete)\("([^"]+)"\)', txt): caps["endpoints"].append(m.group(2))
    for p in glob.glob(os.path.join(root, "**","*.py"), recursive=True):
        t = open(p,"r",encoding="utf-8",errors="ignore").read().lower()
        if "rag" in t and "vector" in t and "repo-rag" not in caps["features"]: caps["features"].append("repo-rag")
        if "progress" in t and "emit" in t and "download progress" not in caps["features"]: caps["features"].append("download progress")
    return caps

def build_roadmap(repo_id: str, data_dir: str, rev_base: str = "HEAD") -> dict:
    tri = _load_triage(data_dir, repo_id); items = tri.get("items", [])
    groups = {}
    for it in items:
        comp = (it.get("classification",{})).get("component") or "general"; groups.setdefault(comp, []).append(it)
    epics = []; tid = 1; tasks_qa = {}
    for comp, arr in groups.items():
        epic = {"id": f"E-{len(epics)+1:03d}", "title": f"{comp} improvements", "items": [], "risks": [], "eta": "1d"}
        for it in arr:
            qa_id = it.get("qa_id")
            action = (it.get("acceptance") or [qa_id])[0]
            task = {"id": f"T-{tid:03d}", "kind": (it.get("classification",{})).get("type") or "task",
                    "qa_id": qa_id, "file":"", "action": action}
            epic["items"].append(task); tasks_qa[task["id"]] = qa_id; tid += 1
        epics.append(epic)
    revA = {"name":"Rev-A","scope":[t["id"] for e in epics for t in e["items"][:1]]}
    revB = {"name":"Rev-B","scope":[t["id"] for e in epics for t in e["items"][:min(3, len(e['items']))]]}
    roadmap = {"rev_base": rev_base, "epics": epics, "revisions":[revA, revB], "task_to_qa": tasks_qa}
    pdir = _proj_dir(data_dir, repo_id)
    open(os.path.join(pdir,"roadmap.json"),"w",encoding="utf-8").write(json.dumps(roadmap,ensure_ascii=False,indent=2))
    open(os.path.join(pdir,"capabilities.json"),"w",encoding="utf-8").write(json.dumps(capability_index(data_dir, repo_id),ensure_ascii=False,indent=2))
    return {"ok": True, "epics": len(epics), "revisions": [revA["name"], revB["name"]]}

def revision_requirements(repo_id: str, data_dir: str) -> dict:
    pdir = _proj_dir(data_dir, repo_id); path = os.path.join(pdir,"roadmap.json")
    if not os.path.isfile(path): return {"ok": False, "error": "roadmap_missing"}
    roadmap = json.load(open(path,"r",encoding="utf-8")); reqs = {}
    for rev in roadmap.get("revisions", []):
        lines = [f"Project {repo_id}: implement {rev.get('name')} tasks. Keep repo structure intact.",
                 "Acceptance: pass Ruff/Black/ESLint and keep endpoints runnable.","Tasks:"]
        for tid in rev.get("scope", []): lines.append(f"- Implement task {tid} per roadmap.json")
        reqs[rev.get("name")] = "\n".join(lines)
    return {"ok": True, "requirements": reqs}