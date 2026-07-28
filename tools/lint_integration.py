
import os, json, subprocess, shutil

def _append_jsonl(dst_path: str, items):
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    with open(dst_path, "a", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")

def run_tool(cmd, cwd):
    try:
        out = subprocess.check_output(cmd, cwd=cwd, stderr=subprocess.STDOUT, timeout=120).decode("utf-8", "ignore")
        return 0, out
    except subprocess.CalledProcessError as e:
        return e.returncode, e.output.decode("utf-8","ignore")
    except Exception as e:
        return -1, str(e)

def run_ruff(repo_root: str, out_jsonl: str):
    if not shutil.which("ruff"):
        return
    code, out = run_tool(["ruff","check","--format","json","."], cwd=repo_root)
    if out.strip():
        try:
            data = json.loads(out)
            items = []
            for it in data:
                items.append({"tool":"ruff","file":it.get("filename"),"line":it.get("location",{}).get("row",1),
                              "severity":"med","code":it.get("code"),"message":it.get("message")})
            _append_jsonl(out_jsonl, items)
        except Exception:
            pass

def run_mypy(repo_root: str, out_jsonl: str):
    if not shutil.which("mypy"):
        return
    code, out = run_tool(["mypy","--hide-error-context","--no-error-summary","--pretty","."], cwd=repo_root)
    items = []
    for line in out.splitlines():
        # file:line: col: error: message  [code]
        if ": error:" in line or ": note:" in line or ": warning:" in line:
            parts = line.split(":")
            if len(parts) >= 4:
                file = parts[0].strip()
                try:
                    line_no = int(parts[1].strip())
                except Exception:
                    line_no = 1
                msg = line.split(":",3)[-1].strip()
                items.append({"tool":"mypy","file":file,"line":line_no,"severity":"med","code":"type-check","message":msg})
    if items:
        _append_jsonl(out_jsonl, items)

def run_bandit(repo_root: str, out_jsonl: str):
    if not shutil.which("bandit"):
        return
    code, out = run_tool(["bandit","-q","-r",".","-f","json"], cwd=repo_root)
    try:
        data = json.loads(out)
        items = []
        for it in data.get("results", []):
            items.append({"tool":"bandit","file":it.get("filename"),"line":it.get("line_number",1),
                          "severity": it.get("issue_severity","med").lower(),
                          "code": it.get("test_id"), "message": it.get("issue_text")})
        if items:
            _append_jsonl(out_jsonl, items)
    except Exception:
        pass
