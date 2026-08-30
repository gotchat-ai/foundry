from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import os, json
from runtime_cuda import cuda_runtime_enabled

DEFAULT_EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def _normalize_embed_model(value: str) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"none", "null", "undefined"}:
        return DEFAULT_EMBED_MODEL
    return text

def _patch_transformers_generation_mixin() -> None:
    """
    Compatibility shim for environments where `GenerationMixin` is not exposed at
    `transformers.generation` (seen on some transformers versions/builds).
    """
    try:
        import transformers.generation as _tg  # type: ignore
    except Exception:
        return
    if getattr(_tg, "GenerationMixin", None) is not None:
        return
    try:
        from transformers.generation.utils import GenerationMixin as _GM  # type: ignore
        setattr(_tg, "GenerationMixin", _GM)
    except Exception:
        # Leave untouched; downstream fallback paths will handle failures.
        return

def _hf_cache_root() -> str:
    return (
        os.environ.get("HUGGINGFACE_HUB_CACHE")
        or (os.path.join(os.environ.get("HF_HOME"), "hub") if os.environ.get("HF_HOME") else None)
        or os.path.expanduser("~/.cache/huggingface")
    )

def _try_local_snapshot(model_name: str, cache_dir: str) -> Optional[str]:
    try:
        from huggingface_hub import snapshot_download
        return snapshot_download(repo_id=model_name, cache_dir=cache_dir, local_files_only=True)
    except Exception:
        return None

class Embedder:
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        _patch_transformers_generation_mixin()
        self.model_name = _normalize_embed_model(model_name)
        model_name = self.model_name
        cache_dir = _hf_cache_root()
        local_snapshot = _try_local_snapshot(model_name, cache_dir) if cache_dir else None
        local_only = bool(local_snapshot)
        model_src = local_snapshot or model_name
        try:
            from sentence_transformers import SentenceTransformer
            try:
                model = SentenceTransformer(
                    model_src,
                    cache_folder=cache_dir,
                    local_files_only=local_only,
                )
            except Exception:
                if not local_only and cache_dir:
                    local_snapshot = _try_local_snapshot(model_name, cache_dir)
                    if local_snapshot:
                        model = SentenceTransformer(
                            local_snapshot,
                            cache_folder=cache_dir,
                            local_files_only=True,
                        )
                    else:
                        raise
                else:
                    raise
            self._validate_sentence_transformer(model)
            self.backend = "st"
            self.model = model
        except Exception:
            self._init_hf_backend(model_src, cache_dir=cache_dir, local_only=local_only)

    def _validate_sentence_transformer(self, model: Any) -> None:
        first = None
        try:
            first = model._first_module()
        except Exception:
            first = None
        tokenizer = getattr(first, "tokenizer", None) if first is not None else None
        if tokenizer is None:
            raise RuntimeError("sentence_transformer_tokenizer_missing")
        try:
            model.encode(["health check"], normalize_embeddings=True, show_progress_bar=False)
        except Exception as exc:
            if "tokenize" in str(exc):
                raise RuntimeError("sentence_transformer_tokenizer_broken") from exc
            raise

    def _init_hf_backend(self, model_src: str, *, cache_dir: str, local_only: bool) -> None:
        # Fallback to HF encoder with mean-pooling over last hidden state
        from transformers import AutoModel, AutoTokenizer
        self.backend = "hf"
        self.tok = AutoTokenizer.from_pretrained(
            model_src,
            cache_dir=cache_dir,
            local_files_only=local_only,
        )
        self.model = AutoModel.from_pretrained(
            model_src,
            cache_dir=cache_dir,
            local_files_only=local_only,
        )
        self.device = "cuda" if cuda_runtime_enabled() else "cpu"
        self.model.to(self.device)
        self.model.eval()

            

    # def encode(self, texts: List[str]) -> np.ndarray:
    #     if self.backend == "st":
    #         v = self.model.encode(texts, normalize_embeddings=True)
    #         return np.asarray(v, dtype="float32")
    #     # HF fallback
    #     import torch
    #     toks = self.tok(texts, return_tensors="pt", truncation=True, padding=True)
    #     toks = {k: v.to(self.device) for k, v in toks.items()}
    #     with torch.no_grad():
    #         out = self.model(**toks).last_hidden_state  # [B, T, H]
    #         mask = toks["attention_mask"].unsqueeze(-1)  # [B, T, 1]
    #         masked = out * mask
    #         sums = masked.sum(dim=1)  # [B, H]
    #         counts = mask.sum(dim=1).clamp(min=1)  # [B,1]
    #         mean = sums / counts
    #         mean = torch.nn.functional.normalize(mean, dim=-1)
    #     return mean.detach().cpu().numpy().astype("float32")
    
    def encode(self, texts):
        """
        Return L2-normalized embeddings for a list of texts.
        Uses SentenceTransformers if available; otherwise falls back to HF encoder with mean pooling.
        Batches in fallback to avoid OOM and long blocking.
        """
        if getattr(self, "backend", None) == "st":
            try:
                return self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
            except AttributeError as exc:
                if "tokenize" not in str(exc):
                    raise
                cache_dir = _hf_cache_root()
                local_snapshot = _try_local_snapshot(self.model_name, cache_dir) if cache_dir else None
                model_src = local_snapshot or self.model_name
                self._init_hf_backend(model_src, cache_dir=cache_dir, local_only=bool(local_snapshot))
            except Exception as exc:
                if "tokenize" not in str(exc):
                    raise
                cache_dir = _hf_cache_root()
                local_snapshot = _try_local_snapshot(self.model_name, cache_dir) if cache_dir else None
                model_src = local_snapshot or self.model_name
                self._init_hf_backend(model_src, cache_dir=cache_dir, local_only=bool(local_snapshot))
        # HF fallback
        import numpy as np
        import torch
        batch = getattr(self, "batch_size", 32)
        max_len = getattr(self, "max_length", 512)
        outs = []
        for i in range(0, len(texts), batch):
            chunk = texts[i:i+batch]
            toks = self.tok(chunk, return_tensors="pt", padding=True, truncation=True, max_length=max_len)
            with torch.no_grad():
                out = self.model(**toks).last_hidden_state
            mask = toks["attention_mask"].unsqueeze(-1)
            summed = (out * mask).sum(dim=1)
            counts = mask.sum(dim=1).clamp(min=1)
            mean = summed / counts
            mean = torch.nn.functional.normalize(mean, dim=-1)
            outs.append(mean.cpu().numpy().astype("float32"))
        return np.concatenate(outs, axis=0)
    


class RagStore:
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2", persist_dir: Optional[str] = None, autosave: bool = False):
        self.embedder = Embedder(model_name)
        self.docs: Dict[str, Dict[str, Any]] = {}
        self.matrix: Optional[np.ndarray] = None  # [N, D]
        self.ids: List[str] = []
        self.persist_dir = persist_dir
        self.autosave = autosave
        if self.persist_dir:
            # attempt load on init
            try:
                self.load(self.persist_dir)
            except Exception:
                pass

    def add(self, doc_id: Optional[str], text: str, metadata: Optional[Dict[str,Any]]=None) -> str:
        if doc_id is None:
            import uuid
            doc_id = uuid.uuid4().hex[:12]
        vec = self.embedder.encode([text])[0]
        self.docs[doc_id] = {"id": doc_id, "text": text, "meta": metadata or {}, "vec": vec}
        self._rebuild()
        if self.autosave and self.persist_dir:
            self.save(self.persist_dir)
        return doc_id

    def add_batch(self, items: List[Dict[str, Any]]) -> List[str]:
        texts = [it["text"] for it in items]
        ids = [it.get("id") for it in items]
        metas = [it.get("metadata") or {} for it in items]
        vecs = self.embedder.encode(texts)
        out_ids = []
        for i, text in enumerate(texts):
            did = ids[i] or __import__("uuid").uuid4().hex[:12]
            self.docs[did] = {"id": did, "text": text, "meta": metas[i], "vec": vecs[i]}
            out_ids.append(did)
        self._rebuild()
        if self.autosave and self.persist_dir:
            self.save(self.persist_dir)
        return out_ids

    def delete(self, doc_id: str):
        if doc_id in self.docs:
            del self.docs[doc_id]
            self._rebuild()
            if self.autosave and self.persist_dir:
                self.save(self.persist_dir)

    def clear(self):
        self.docs.clear()
        self.matrix = None
        self.ids = []
        if self.autosave and self.persist_dir:
            self.save(self.persist_dir)

    def _rebuild(self):
        if not self.docs:
            self.matrix = None
            self.ids = []
            return
        self.ids = list(self.docs.keys())
        valid_ids = []
        valid_vecs = []
        target_dim = None
        for did in self.ids:
            vec = self.docs.get(did, {}).get("vec")
            if vec is None:
                continue
            arr = np.asarray(vec, dtype=np.float32)
            if arr.ndim != 1:
                continue
            if target_dim is None:
                target_dim = int(arr.shape[0])
            if int(arr.shape[0]) != target_dim:
                continue
            valid_ids.append(did)
            valid_vecs.append(arr)
        self.ids = valid_ids
        if not valid_vecs:
            self.matrix = None
            return
        self.matrix = np.stack(valid_vecs, axis=0)  # [N, D]
    def set_embedder_model(self, model_name: str):
        """Reinitialize embedder to match a specific model (for pre-embedded cold->hot)."""
        if not model_name or getattr(self.embedder, "model_name", None) == model_name:
            return
        try:
            self.embedder = Embedder(model_name)
        except Exception:
            # Keep current embedder to avoid breaking queries
            pass

    def add_preembedded(self, ids: List[str], texts: List[str], metas: List[Dict[str,Any]], vectors):
        """
        Add docs with precomputed vectors without re-embedding.
        - ids: list of doc ids
        - texts: same length list of texts
        - metas: same length list of metadata dicts
        - vectors: numpy array [N, D] or list of lists
        """
        import numpy as _np
        if vectors is None:
            raise ValueError("vectors required")
        vecs = _np.asarray(vectors, dtype=_np.float32)
        if vecs.ndim != 2:
            raise ValueError("vectors must be rank-2 [N, D]")
        if not (len(ids) == len(texts) == len(metas) == vecs.shape[0]):
            raise ValueError("ids/texts/metas/vectors length mismatch")
        out_ids = []
        for i, did in enumerate(ids):
            self.docs[did] = {"id": did, "text": texts[i], "meta": metas[i] or {}, "vec": vecs[i]}
            out_ids.append(did)
        # ensure ids order includes new ids at the end in deterministic order
        for did in out_ids:
            if did not in self.ids:
                self.ids.append(did)
        self._rebuild()
        if self.autosave and self.persist_dir:
            self.save(self.persist_dir)
        return out_ids
    def search(self, query: str, top_k: int = 4) -> List[Dict[str, Any]]:
        # print("search query: ", query)
        # print("matrix ",  self.matrix)
        # print("matrix ",self.docs)
        if not self.docs or self.matrix is None:
            return []
        q = self.embedder.encode([query])[0]  # [D]
        # cosine similarity with normalized vectors
        sims = (self.matrix @ q)
        top_idx = np.argsort(-sims)[: int(top_k)]
        results = []
        for idx in top_idx:
            did = self.ids[int(idx)]
            d = self.docs[did]
            results.append({"id": did, "score": float(sims[int(idx)]), "text": d["text"], "metadata": d["meta"]})
        return results


    # --------------- Persistence ---------------
    # Persist embedder model_name to embed_meta.json
    def save(self, directory: str):
        os.makedirs(directory, exist_ok=True)
        # write docs.json
        docs_serial = []
        for did, d in self.docs.items():
            docs_serial.append({"id": did, "text": d["text"], "metadata": d["meta"]})
        with open(os.path.join(directory, "docs.json"), "w", encoding="utf-8") as f:
            json.dump({"docs": docs_serial}, f, ensure_ascii=False)
        # write embedder meta
        with open(os.path.join(directory, "embed_meta.json"), "w", encoding="utf-8") as f:
            json.dump({"model": getattr(self.embedder, "model_name", None)}, f)
        # write matrix.npy and ids.json
        if self.matrix is not None:
            np.save(os.path.join(directory, "matrix.npy"), self.matrix)
        with open(os.path.join(directory, "ids.json"), "w", encoding="utf-8") as f:
            json.dump({"ids": self.ids}, f)

    def load(self, directory: str):
        from pathlib import Path
        p = Path(directory)
        if not p.exists():
            return
        docs_fp = p / "docs.json"
        ids_fp = p / "ids.json"
        mat_fp = p / "matrix.npy"
        if not docs_fp.exists():
            return
        meta_fp = p / "embed_meta.json"
        if meta_fp.exists():
            try:
                meta = json.load(open(meta_fp, "r", encoding="utf-8"))
                model = meta.get("model")
                if model:
                    try:
                        self.embedder = Embedder(model)
                    except Exception:
                        pass
            except Exception:
                pass
        data = json.load(open(docs_fp, "r", encoding="utf-8"))
        docs_list = data.get("docs", [])
        self.docs = {}
        for item in docs_list:
            did = item["id"]
            self.docs[did] = {"id": did, "text": item.get("text",""), "meta": item.get("metadata", {}), "vec": None}
        # ids + matrix
        if ids_fp.exists():
            self.ids = json.load(open(ids_fp, "r"))["ids"]
        else:
            self.ids = list(self.docs.keys())
        if mat_fp.exists():
            self.matrix = np.load(mat_fp)
            # Ensure shape matches ids/docs count; otherwise rebuild from text
            if self.matrix.shape[0] != len(self.ids):
                self._reembed_all()
            else:
                # Reattach persisted vectors to their docs.  Without this,
                # a later add() calls _rebuild(), sees old docs with vec=None,
                # and silently drops the whole prior hot-memory set.
                for i, did in enumerate(self.ids):
                    if did in self.docs:
                        self.docs[did]["vec"] = self.matrix[i]
        else:
            self._reembed_all()

    def _reembed_all(self):
        if not self.docs:
            self.matrix = None
            self.ids = []
            return
        texts = [self.docs[i]["text"] for i in self.ids]
        vecs = self.embedder.encode(texts)
        for i, did in enumerate(self.ids):
            self.docs[did]["vec"] = vecs[i]
        self.matrix = np.stack([self.docs[i]["vec"] for i in self.ids], axis=0)
