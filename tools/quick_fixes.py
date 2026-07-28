
import os, json
def _fix_mutable_default(file, line):
    return {"title":"Replace mutable default with None + init","details":"Use None in signature; init inside.","snippet":"def func(arg=None):\n    if arg is None:\n        arg = []","file":file,"line":line}
def _fix_broad_except(file, line):
    return {"title":"Narrow broad except; log + re-raise","details":"Catch specific exceptions; avoid bare pass.","snippet":"try:\n    ...\nexcept (ValueError, OSError) as e:\n    logger.exception('failed: %s', e)\n    raise","file":file,"line":line}
def _fix_inconsistent_returns(file, line):
    return {"title":"Unify return paths","details":"Return a consistent type/value on all paths.","snippet":"def func(...):\n    if cond:\n        return value\n    return default_value","file":file,"line":line}
MAP={"mutable-default":_fix_mutable_default,"broad-except-pass":_fix_broad_except,"inconsistent-returns":_fix_inconsistent_returns}
def generate_quick_fixes(issues_path: str, out_path: str) -> str:
    fixes=[]; 
    if os.path.exists(issues_path):
        for line in open(issues_path,"r",encoding="utf-8"):
            try: j=json.loads(line)
            except Exception: continue
            code=str(j.get("code",""))
            if code in MAP:
                fx=MAP[code](j.get("file"), j.get("line")); fx["tool"]=j.get("tool"); fx["code"]=code; fixes.append(fx)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path,"w",encoding="utf-8") as f:
        for fx in fixes: f.write(json.dumps(fx, ensure_ascii=False)+"\n")
    return out_path
