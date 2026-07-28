import os, io, re, zipfile, shutil, time, hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from tools.repo_analyzer import analyze_repo, vector_persist

LANG_BY_EXT = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "tsx", ".jsx": "jsx",
    ".java": "java", ".go": "go", ".rs": "rust", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".c": "c", ".h": "c",
    ".cs": "csharp", ".rb": "ruby", ".php": "php", ".swift": "swift", ".kt": "kotlin",
    ".json": "json", ".yml": "yaml", ".yaml": "yaml", ".toml": "toml", ".md": "markdown", ".txt": "text"
}

FUNC_PATTERNS = {
    "python": re.compile(r'^(\s*)(def|class)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(?.*', re.M),
    "javascript": re.compile(r'^(\s*)(function\s+[A-Za-z_][A-Za-z0-9_]*|const\s+[A-Za-z_][A-Za-z0-9_]*\s*=\s*\([^)]*\)\s*=>|class\s+[A-Za-z_][A-Za-z0-9_]*)', re.M),
    "typescript": re.compile(r'^(\s*)(function\s+[A-Za-z_][A-Za-z0-9_]*|const\s+[A-Za-z_][A-Za-z0-9_]*\s*=\s*\([^)]*\)\s*=>|class\s+[A-Za-z_][A-Za-z0-9_]*)', re.M),
    "go": re.compile(r'^(\s*)(func\s+[A-Za-z_][A-Za-z0-9_]*|type\s+[A-Za-z_][A-Za-z0-9_]*\s+struct)', re.M),
    "java": re.compile(r'^(\s*)(class\s+[A-Za-z_][A-Za-z0-9_]*|public\s+.*\s+[A-Za-z_][A-Za-z0-9_]*\s*\()', re.M),
    "cpp": re.compile(r'^(\s*)(class\s+[A-Za-z_][A-Za-z0-9_]*|[A-Za-z_][A-Za-z0-9_:<>~*&\s]*\([^)]*\)\s*\{)', re.M),
    "c": re.compile(r'^(\s*)([A-Za-z_][A-Za-z0-9_\s\*]*\([^)]*\)\s*\{)', re.M),
    "csharp": re.compile(r'^(\s*)(class\s+[A-Za-z_][A-Za-z0-9_]*|[A-Za-z_][A-Za-z0-9_<>\s]*\([^)]*\)\s*\{)', re.M),
    "rust": re.compile(r'^(\s*)(fn\s+[A-Za-z_][A-Za-z0-9_]*|struct\s+[A-Za-z_][A-Za-z0-9_]*)', re.M),
    "php": re.compile(r'^(\s*)(function\s+[A-Za-z_][A-Za-z0-9_]*|class\s+[A-Za-z_][A-Za-z0-9_]*)', re.M),
}

def detect_lang(path: Path) -> str:
    return LANG_BY_EXT.get(path.suffix.lower(), "text")

def guess_language(path_or_rel) -> str:
    return detect_lang(Path(path_or_rel))

def chunk_code(text: str, lang: str, max_lines: int = 200) -> List[Dict[str, Any]]:
    lines = text.splitlines()
    if lang in FUNC_PATTERNS:
        pat = FUNC_PATTERNS[lang]
        indices = [m.start() for m in pat.finditer(text)]
        if indices:
            indices.append(len(text))
            chunks = []
            for i in range(len(indices)-1):
                seg = text[indices[i]:indices[i+1]]
                m = pat.search(seg)
                sym = None
                if m:
                    sx = m.group(3) if m.lastindex and m.lastindex >= 3 else None
                    sym = (sx or m.group(2)).strip() if m else None
                chunks.append({"symbol": sym, "kind": "symbol" if sym else "block", "text": seg})
            return chunks
    chunks = []
    for i in range(0, len(lines), max_lines):
        seg = "\n".join(lines[i:i+max_lines])
        chunks.append({"symbol": None, "kind": "block", "text": seg})
    return chunks

def summarize_file_map(path: Path, text: str, lang: str) -> str:
    lines = text.splitlines()
    pat = FUNC_PATTERNS.get(lang)
    entries = []
    if pat:
        for i, line in enumerate(lines, start=1):
            m = pat.match(line)
            if m:
                sym = m.group(3) if m.lastindex and m.lastindex >= 3 else m.group(2)
                entries.append(f"- {sym} @ L{i}")
    if not entries:
        preview = "\n".join([f"- L{i+1}: {l[:80]}" for i,l in enumerate(lines[:10])])
        return f"{path.name}:\n{preview}"
    return f"{path.name}:\n" + "\n".join(entries[:60])

def file_should_skip(path: Path, max_bytes: int, include_lang: Optional[List[str]] = None, exclude_globs: Optional[List[str]] = None) -> bool:
    if path.is_dir(): return True
    try: sz = path.stat().st_size
    except Exception: return True
    if sz <= 0 or sz > max_bytes: return True
    if include_lang:
        lang = detect_lang(path)
        print("path:", path)
        print("lang:", lang)
        print(include_lang)
        if lang not in include_lang and path.suffix.lower() not in include_lang:
            return True
    if exclude_globs:
        for g in exclude_globs:
            if path.match(g): return True
    if path.suffix.lower() in {'.png','.jpg','.jpeg','.gif','.bmp','.pdf','.zip','.jar','.bin','.exe','.dll'}: return True
    return False

def ingest_dir_to_user_rag_cold(user_rag, sid: str, repo_id: str, root_dir: str, tokenizer, max_file_bytes: int = 200000, include_lang: Optional[List[str]] = None, exclude_globs: Optional[List[str]] = None, include_glob: Optional[List[str]] = None, chunk_lines: int = 200, version: Optional[str] = None, parent_version: Optional[str] = None, tags: Optional[List[str]] = None, analyze_repo: Optional[bool] = True) -> Dict[str, Any]:
    # print(2342324)
    import sys
    import traceback
    from tools.repo_analyzer import scan_repo

    # proj_key = project_id or repo_id or sid

    try:
        root = Path(root_dir)
        n_files = 0; n_chunks = 0; n_tokens = 0; maps = 0
        import time; ts = int(time.time())

        # --- load previous meta and register new version
        ts = int(time.time())
        vrec = user_rag._register_version(sid, repo_id, version or f"v{ts}", parent_version, ts=ts)
        vrec["root_dir"] = str(root_dir)
        try:
            meta = user_rag._load_repo_meta(sid, repo_id)
            for v in meta.get("versions", []):
                if v.get("id") == vrec.get("id"):
                    v["root_dir"] = str(root_dir)
                    break
            meta["root_dir"] = str(root_dir)
            user_rag._save_repo_meta(sid, repo_id, meta)
        except Exception:
            pass
        #vrec = user_rag._register_version(proj_key, repo_id, version or f"v{ts}", parent_version, ts=ts)
        prev = user_rag._get_version_record(sid, repo_id, parent_version) if parent_version else user_rag._get_latest_version_record(sid, repo_id)
        # prev = (
        #     user_rag._get_version_record(proj_key, repo_id, parent_version)
        #     if parent_version
        #     else user_rag._get_latest_version_record(proj_key, repo_id)
        # )
                                    
        prev_files = (prev or {}).get("files", {})
        counts = {"new": 0, "modified": 0, "unchanged": 0, "deleted": 0}
        seen_paths = set()

        # print(23423284)

        for p in root.rglob('*'):
            print("filename:", p.name)
            if file_should_skip(p, max_file_bytes, include_lang, exclude_globs): print("skipped: ", p.name);continue
            try: text = p.read_text(encoding='utf-8', errors='ignore')
            except Exception: continue
            # write full file snapshot into version directory
            # print(3444)
            try:
                user_rag.write_version_file(sid, repo_id, version or f"v{ts}", str(p.relative_to(root)), text)
            except Exception as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                tb_list = traceback.extract_tb(exc_traceback)
                
                # The last element in tb_list corresponds to the point of the exception
                last_frame = tb_list[-1]
                line_number = last_frame.lineno
                filename = last_frame.filename
                function_name = last_frame.name
                
                print(f"An error occurred in file '{filename}', function '{function_name}', on line {line_number}.")
                
                print(e)
                pass
            lang = detect_lang(p)
            rel = str(p.relative_to(root))
            fmap = summarize_file_map(p, text, lang)
            # print(344334)
            try:
                user_rag.add_repo_map_to_hot(sid, repo_id, rel, fmap, lang, topics=[repo_id, lang] + list(p.parts[-3:]))
                maps += 1
            except Exception as e: 
                exc_type, exc_value, exc_traceback = sys.exc_info()
                tb_list = traceback.extract_tb(exc_traceback)
                
                # The last element in tb_list corresponds to the point of the exception
                last_frame = tb_list[-1]
                line_number = last_frame.lineno
                filename = last_frame.filename
                function_name = last_frame.name
                
                print(f"An error occurred in file '{filename}', function '{function_name}', on line {line_number}.")
                
                print(e)
                pass
            # print(34433334)
            # build prev hash set for this file
            prev_chunks = (prev_files.get(rel, {}) or {}).get('chunks', [])
            prev_hashes = {c.get('hash') for c in prev_chunks}
            file_manifest = {"map_id": None, "chunks": []}
            # add chunks (skip unchanged)
            for ch in chunk_code(text, lang, max_lines=chunk_lines):
                sym = ch.get('symbol'); kind = ch.get('kind'); ctext = ch.get('text','')
                # print(34442244)
                try: toks = len(tokenizer.encode(ctext))
                except Exception: toks = max(1, len(ctext)//4)
                h = hashlib.blake2s(ctext.encode('utf-8'), digest_size=16).hexdigest()
                if h in prev_hashes:
                    counts['unchanged'] += 1
                    file_manifest['chunks'].append({"id": None, "hash": h, "symbol": sym, "kind": kind, "lang": lang, "chars": len(ctext)})
                else:
                    version_id = vrec.get("id")
                    did = user_rag.add_repo_chunk_to_cold(sid, repo_id, rel, ctext, lang, symbol=sym, kind=kind, version=version_id, topics=[repo_id, lang, sym or '', *list(p.parts[-3:])], ts=ts)
                    # did = user_rag.add_repo_chunk_to_cold(
                    #     proj_key,
                    #     rel_path,
                    #     text=ctext,
                    #     lang=lang,
                    #     tags=tags or [],
                    #     topics=[repo_id, lang, sym or "", *list(p.parts[-3:])],
                    #     ts=ts,
                    # )

                    file_manifest['chunks'].append({"id": did, "hash": h, "symbol": sym, "kind": kind, "lang": lang, "chars": len(ctext)})
                    # modified vs new
                    prev_syms = {c.get('symbol') for c in prev_chunks}
                    if sym and sym in prev_syms:
                        counts['modified'] += 1
                    else:
                        counts['new'] += 1
                    n_chunks += 1; n_tokens += toks
                    # print(3448)
            # attach manifest for file
            vrec['files'][rel] = file_manifest
            seen_paths.add(rel)
            n_files += 1
        # count deleted paths relative to previous
        for pth, rec in (prev_files or {}).items():
            if pth not in seen_paths:
                counts['deleted'] += len(rec.get('chunks', []))
        # persist updated meta
        meta = user_rag._load_repo_meta(sid, repo_id)
        for i,v in enumerate(meta.get('versions', [])):
            if v.get('id') == vrec.get('id'):
                meta['versions'][i] = vrec
                break
        meta["root_dir"] = str(root_dir)
        user_rag._save_repo_meta(sid, repo_id, meta)
        #user_rag._save_repo_meta(proj_key, repo_id, meta)

        # --- NEW: repo analyzer integration ---
        try:
            # scan_repo signature: scan_repo(repo_id: str, root_dir: str)
            chunks = scan_repo(repo_id, str(root_dir))
        except Exception:
            chunks = []

        if chunks:
            cold = user_rag._get_cold_store(sid)
            now_ts = int(time.time())
            for ch in chunks:
                # ch.file is an absolute path under root_dir
                rel_path = os.path.relpath(ch.file, str(root_dir)).replace(os.sep, "/")
                meta = {
                    "repo_id": repo_id,
                    "path": rel_path,
                    "fqn": ch.fqn,
                    "kind": ch.kind,
                    "signature": ch.signature,
                    "docstring": ch.docstring,
                    "imports": ch.imports,
                    "calls": ch.calls,          # <-- call relationships live here
                    #"version": version,         # use local version, not ingest_res.get(...)
                    "version": vrec.get('id'),
                    "ts": now_ts,
                    "repo_analyzer": True,
                }
                doc_id = f"repo:{repo_id}:{rel_path}:{ch.start_line}-{ch.end_line}"
                cold.add(doc_id, ch.text, meta)

        # return {
        #     "repo_id": repo_id,
        #     "sid": sid,
        #     "root_dir": root_dir,
        #     "version": version,
        #     "files": files_ingested,
        #     "bytes": bytes_ingested,
        #     "analyzer_chunks": len(chunks),
        # }
        res = {
            "files": n_files, 
            "chunks": n_chunks, 
            "tokens": n_tokens, 
            "maps": maps, 
            "version": vrec.get('id'), 
            "parent": (prev or {}).get('id'), 
            "counts": counts,
            
            "repo_id": repo_id,
            "sid": sid,
            # "proj_key": proj_key,
            "root_dir": root_dir,
            "analyzer_chunks": len(chunks),

            }
        
        analyze_out= None
        if analyze_repo:
            # print(42832002)
            analyze_out = analyze_repo_dir(user_rag=user_rag, ingest_res=res)

        res["analyzer"] = analyze_out

         # --- IMPORTANT: persist populated vrec['files'] back into repo meta ---
        # try:
        #     meta = user_rag._load_repo_meta(sid, repo_id)
        #     vid = vrec.get("id")
        #     if vid and isinstance(meta, dict):
        #         vs = meta.get("versions", []) or []
        #         for vv in vs:
        #             if vv.get("id") == vid:
        #                 vv["files"] = vrec.get("files", {}) or {}
        #                 break
        #         user_rag._save_repo_meta(sid, repo_id, meta)
        # except Exception:
        #     pass

        return res
    

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        tb_list = traceback.extract_tb(exc_traceback)
        
        # The last element in tb_list corresponds to the point of the exception
        last_frame = tb_list[-1]
        line_number = last_frame.lineno
        filename = last_frame.filename
        function_name = last_frame.name
        
        print(f"An error occurred in file '{filename}', function '{function_name}', on line {line_number}.")
        
        
        print(e)

def ingest_dir_delta_to_user_rag_cold(
    user_rag,
    sid: str,
    repo_id: str,
    root_dir: str,
    tokenizer,
    *,
    changed_paths: Optional[List[str]] = None,
    deleted_paths: Optional[List[str]] = None,
    include_lang: Optional[List[str]] = None,
    exclude_globs: Optional[List[str]] = None,
    chunk_lines: int = 200,
    max_file_bytes: int = 200_000,
    version: Optional[str] = None,
    base_version: Optional[str] = None,
    keep_versions: int = 3,
) -> Dict[str, Any]:
    """
    Incremental ingest for large active repos:
      - Only re-ingest files in changed_paths
      - Remove files in deleted_paths from the new version record
      - Reuse unchanged chunk IDs from the base version (hash match)
      - Keep only the latest keep_versions versions and GC cold chunks not referenced
    """

    import os
    import time
    import hashlib
    from pathlib import Path

    def _norm_rel(p: str) -> str:
        p = (p or "").strip().replace("\\", "/")
        while p.startswith("./"):
            p = p[2:]
        if not p or os.path.isabs(p) or ".." in p.split("/"):
            return ""
        return p

    root = Path(root_dir)
    if not root_dir or not os.path.isdir(root_dir):
        raise ValueError("root_dir not found or not a directory")

    changed = [_norm_rel(p) for p in (changed_paths or [])]
    changed = [p for p in changed if p]
    deleted = [_norm_rel(p) for p in (deleted_paths or [])]
    deleted = [p for p in deleted if p]

    ts = int(time.time())
    meta = user_rag._load_repo_meta(sid, repo_id)
    versions = (meta.get("versions", []) or [])

    def _latest_vrec():
        if not versions:
            return None
        return max(versions, key=lambda x: int(x.get("seq", 0)))

    base_vrec = None
    if base_version:
        for v in versions:
            if v.get("id") == base_version:
                base_vrec = v
                break
    if base_vrec is None:
        base_vrec = _latest_vrec()

    parent_id = base_vrec.get("id") if base_vrec else None

    # register new version record
    vrec = user_rag._register_version(sid, repo_id, version or f"v{ts}", parent_id, ts=ts)

    # rebuild meta after _register_version saved it
    meta = user_rag._load_repo_meta(sid, repo_id)
    versions = (meta.get("versions", []) or [])
    # locate our version record inside meta list
    target_v = None
    for vv in versions:
        if vv.get("id") == vrec.get("id"):
            target_v = vv
            break
    if target_v is None:
        target_v = vrec  # fallback in-memory

    # start new_files as a copy of base (so unchanged files are carried forward)
    base_files = (base_vrec.get("files", {}) if base_vrec else {}) or {}
    # deep-ish copy via JSON roundtrip to avoid aliasing
    try:
        import json
        new_files = json.loads(json.dumps(base_files))
    except Exception:
        new_files = dict(base_files)

    counts = {"changed_files": 0, "deleted_files": 0, "new_chunks": 0, "reused_chunks": 0, "skipped_files": 0}

    # apply deletions to version record (does not delete chunks yet; GC handles)
    for rel in deleted:
        if rel in new_files:
            new_files.pop(rel, None)
            counts["deleted_files"] += 1

    # helper: reuse chunk id by hash from base manifest
    def _prev_hash_to_id(rel_path: str) -> Dict[str, str]:
        prev = (base_files.get(rel_path, {}) or {}).get("chunks", []) or []
        out = {}
        for c in prev:
            h = c.get("hash")
            cid = c.get("id")
            if h and cid:
                out[str(h)] = str(cid)
        return out

    # cold store for GC later
    cold = user_rag._get_cold_store(sid)

    # ingest changed files only
    for rel in changed:
        abs_path = root / rel
        if not abs_path.exists() or not abs_path.is_file():
            # treat missing as delete
            if rel in new_files:
                new_files.pop(rel, None)
                counts["deleted_files"] += 1
            continue

        try:
            sz = abs_path.stat().st_size
        except Exception:
            sz = 0
        if max_file_bytes and sz and sz > int(max_file_bytes):
            counts["skipped_files"] += 1
            continue

        try:
            txt = abs_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            counts["skipped_files"] += 1
            continue

        lang = guess_language(rel)
        if include_lang and lang not in set(include_lang):
            counts["skipped_files"] += 1
            continue

        # exclude globs check (same semantics as your full ingest)
        if exclude_globs:
            import fnmatch
            skip = False
            for g in exclude_globs:
                if g and fnmatch.fnmatch(rel, g):
                    skip = True
                    break
            if skip:
                counts["skipped_files"] += 1
                continue

        prev_map = _prev_hash_to_id(rel)

        file_manifest = {"map_id": None, "chunks": []}

        for ch in chunk_code(txt, lang, max_lines=chunk_lines):
            sym = ch.get("symbol")
            kind = ch.get("kind")
            ctext = ch.get("text", "") or ""

            # stable content hash for reuse matching
            h = hashlib.blake2s(ctext.encode("utf-8"), digest_size=16).hexdigest()

            # reuse chunk doc id if unchanged
            prev_id = prev_map.get(h)
            if prev_id:
                file_manifest["chunks"].append(
                    {"id": prev_id, "hash": h, "symbol": sym, "kind": kind, "lang": lang, "chars": len(ctext)}
                )
                counts["reused_chunks"] += 1
                continue

            did = user_rag.add_repo_chunk_to_cold(
                sid,
                repo_id,
                rel,
                ctext,
                lang,
                symbol=sym,
                kind=kind,
                version=target_v.get("id"),
                topics=[repo_id, lang, sym or "", *list(Path(rel).parts[-3:])],
                ts=ts,
            )
            file_manifest["chunks"].append(
                {"id": did, "hash": h, "symbol": sym, "kind": kind, "lang": lang, "chars": len(ctext)}
            )
            counts["new_chunks"] += 1

        new_files[rel] = file_manifest
        counts["changed_files"] += 1

    # write updated files manifest into version record and persist
    target_v["files"] = new_files
    user_rag._save_repo_meta(sid, repo_id, meta)

    # --- KEEP ONLY latest keep_versions and GC unreferenced docs ---
    try:
        keep_versions = max(1, int(keep_versions or 1))
        meta2 = user_rag._load_repo_meta(sid, repo_id)
        vs2 = (meta2.get("versions", []) or [])
        if len(vs2) > keep_versions:
            vs2_sorted = sorted(vs2, key=lambda x: int(x.get("seq", 0)))
            drop = vs2_sorted[: max(0, len(vs2_sorted) - keep_versions)]
            keep = vs2_sorted[len(drop):]

            # build referenced doc_id set for kept versions
            keep_ids = set()
            for vv in keep:
                files = (vv.get("files", {}) or {})
                for fmeta in files.values():
                    for c in (fmeta.get("chunks", []) or []):
                        cid = c.get("id")
                        if cid:
                            keep_ids.add(str(cid))

            # collect doc_ids from dropped versions and delete those not referenced anymore
            drop_ids = set()
            for vv in drop:
                files = (vv.get("files", {}) or {})
                for fmeta in files.values():
                    for c in (fmeta.get("chunks", []) or []):
                        cid = c.get("id")
                        if cid:
                            drop_ids.add(str(cid))

            # prune versions list
            meta2["versions"] = keep
            meta2["latest_seq"] = max([int(v.get("seq", 0)) for v in keep] or [0])
            user_rag._save_repo_meta(sid, repo_id, meta2)

            # GC cold store
            for did in (drop_ids - keep_ids):
                try:
                    cold.delete(did)
                except Exception:
                    pass
    except Exception:
        pass

    return {"ok": True, "repo_id": repo_id, "version": target_v.get("id"), "parent": parent_id, "stats": counts}

# def ingest_zip_to_user_rag_cold(user_rag, sid: str, repo_id: str, zip_path: str, tokenizer, **kwargs) -> Dict[str, Any]:
#     print(32242)
#     try:
#         tmp = Path(zip_path)
#         if not tmp.exists(): raise FileNotFoundError(f"zip not found: {zip_path}")
#         work = tmp.parent / f"_{tmp.stem}_extract"
#         if work.exists(): shutil.rmtree(work)
#         work.mkdir(parents=True, exist_ok=True)
#         with zipfile.ZipFile(str(tmp), 'r') as zf: zf.extractall(str(work))
#         try:
#             return ingest_dir_to_user_rag_cold(user_rag, sid, repo_id, str(work), tokenizer, **kwargs)
#         finally:
#             shutil.rmtree(work, ignore_errors=True)
#     except Exception as e:
#         print(e)

def analyze_repo_dir(
        user_rag,
        ingest_res: dict,
        **kwargs,
    ) -> Dict[str, Any]:
    try:
        tmp = Path(ingest_res.get("root_dir"))
        sid = ingest_res.get("sid")
        repo_id = ingest_res.get("repo_id")
        # proj_key = ingest_res.get("proj_key")

        if not tmp.exists():
            raise FileNotFoundError(f"zip not found: {tmp}")

        # Decide where to store analyzer outputs (notes.jsonl, map.json, summary.md, vectors/…)
        # We tuck them under the lib/cold dir, namespaced by sid/repo/version.
        try:
            # get version from ingest result if present
            version = ingest_res.get("version") or str(int(time.time()))
        except Exception:
            version = str(int(time.time()))

        analyzer_root = (
            user_rag.cold_base_dir
            / "_repo_index"
            / sid
            / repo_id
            / version
        )
        os.makedirs(analyzer_root, exist_ok=True)

        print("analyzer_root", analyzer_root)
        # Call analyze_repo(repo_id, root_dir, out_dir) -> {"notes":..., "map":..., "summary":...}
        analyzer_out = analyze_repo(
            repo_id=repo_id,
            root_dir=str(tmp),
            out_dir=str(analyzer_root),
        )

        # You can optionally stuff these paths into the repo meta so other tools can find them
        try:
            meta = user_rag._load_repo_meta(sid, repo_id)
            # find this version record (vrec) and attach analyzer info
            for v in meta.get("versions", []):
                if v.get("id") == ingest_res.get("version") or not ingest_res.get("version"):
                    v.setdefault("repo_analyzer", {})
                    v["repo_analyzer"].update(analyzer_out)
                    break
            user_rag._save_repo_meta(sid, repo_id, meta)
        except Exception as e:
            print(e)
            # print(25234543534)
        # try:
        #     meta = user_rag._load_repo_meta(proj_key, repo_id)
        #     for v in meta.get("versions", []):
        #         if v.get("id") == ingest_res.get("version") or not ingest_res.get("version"):
        #             v.setdefault("repo_analyzer", {})
        #             v["repo_analyzer"].update(analyzer_out)
        #             break
        #     user_rag._save_repo_meta(proj_key, repo_id, meta)
        # except Exception:
        #     # non-fatal; just ignore if meta wiring fails
        #     pass

        return analyzer_out
    except Exception as e:
        # print(234235252)
        print(e)
        return {}
    


def ingest_zip_to_user_rag_cold(
    user_rag,
    sid: str,
    repo_id: str,
    zip_path: str,
    tokenizer,
    **kwargs,
) -> Dict[str, Any]:
    tmp = Path(zip_path)
    if not tmp.exists():
        raise FileNotFoundError(f"zip not found: {zip_path}")

    # 1) Extract zip into a persistent working dir so watch can reuse root_dir.
    import time
    version = kwargs.get("version") or f"v{int(time.time())}"
    safe_version = re.sub(r"[^A-Za-z0-9._-]+", "_", str(version))
    base_dir = getattr(user_rag, "cold_base_dir", None)
    if base_dir:
        work = Path(base_dir) / "_repo_sources" / sid / repo_id / safe_version
    else:
        work = tmp.parent / f"_{tmp.stem}_extract_{safe_version}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(tmp), 'r') as zf:
        zf.extractall(str(work))
    
    try:
        # 2) Existing path: ingest into user_rag cold + repo meta
        ingest_res = ingest_dir_to_user_rag_cold(
            user_rag,
            sid,
            repo_id,
            str(work),
            tokenizer,
            **kwargs,
        )

        # # 3) NEW: Run repo_analyzer.analyze_repo with real signature
        # #
        # # Decide where to store analyzer outputs (notes.jsonl, map.json, summary.md, vectors/…)
        # # We tuck them under the lib/cold dir, namespaced by sid/repo/version.
        # try:
        #     # get version from ingest result if present
        #     version = ingest_res.get("version") or str(int(time.time()))
        # except Exception:
        #     version = str(int(time.time()))

        # analyzer_root = (
        #     user_rag.cold_base_dir
        #     / "_repo_index"
        #     / sid
        #     / repo_id
        #     / version
        # )
        # os.makedirs(analyzer_root, exist_ok=True)

        # # Call analyze_repo(repo_id, root_dir, out_dir) -> {"notes":..., "map":..., "summary":...}
        # analyzer_out = analyze_repo(
        #     repo_id=repo_id,
        #     root_dir=str(work),
        #     out_dir=str(analyzer_root),
        # )

        # # You can optionally stuff these paths into the repo meta so other tools can find them
        # try:
        #     meta = user_rag._load_repo_meta(sid, repo_id)
        #     # find this version record (vrec) and attach analyzer info
        #     for v in meta.get("versions", []):
        #         if v.get("id") == ingest_res.get("version") or not ingest_res.get("version"):
        #             v.setdefault("repo_analyzer", {})
        #             v["repo_analyzer"].update(analyzer_out)
        #             break
        #     user_rag._save_repo_meta(sid, repo_id, meta)
        # except Exception:
        #     # non-fatal; just ignore if meta wiring fails
        #     pass

        # 4) Return combined info so the caller can see both ingest + analyzer results
        # ingest_res["analyzer"] = analyzer_out

        return ingest_res

    finally:
        # Keep extracted files for watch; do not delete work.
        pass
