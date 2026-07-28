
import os, json

def path_for(data_dir: str, project_id: str) -> str:
    return os.path.join(data_dir, "projects", project_id, "guidelines.json")

def load(data_dir: str, project_id: str) -> dict:
    p = path_for(data_dir, project_id)
    if not os.path.exists(p):
        return {"notes": [], "rules": []}
    try:
        return json.load(open(p,"r",encoding="utf-8"))
    except Exception:
        return {"notes": [], "rules": []}

def save(data_dir: str, project_id: str, gl: dict):
    os.makedirs(os.path.join(data_dir, "projects", project_id), exist_ok=True)
    with open(path_for(data_dir, project_id), "w", encoding="utf-8") as f:
        json.dump(gl, f, ensure_ascii=False, indent=2)

def add_rule(data_dir: str, project_id: str, rule: str):
    gl = load(data_dir, project_id)
    if rule and rule not in gl.get("rules", []):
        gl["rules"].append(rule)
        save(data_dir, project_id, gl)

def compose_prompt_suffix(data_dir: str, project_id: str) -> str:
    gl = load(data_dir, project_id)
    parts = []
    if gl.get("rules"):
        parts.append("ADDITIONAL RULES (learned from failures):\n- " + "\n- ".join(gl["rules"]))
    if gl.get("notes"):
        parts.append("CONTEXT NOTES:\n- " + "\n- ".join(gl["notes"]))
    return "\n\n".join(parts)
