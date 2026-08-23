from typing import Optional

def _load_llama_cpp_low_level():
    try:
        from llama_cpp import (
            llama_backend_init,
            llama_model_default_params,
            llama_model_load_from_file,
            llama_model_n_layer,
            llama_model_free,
        )
        return (
            llama_backend_init,
            llama_model_default_params,
            llama_model_load_from_file,
            llama_model_n_layer,
            llama_model_free,
        )
    except Exception:
        return (None, None, None, None, None)


def _gguf_get_n_layers_via_llama_cpp(model_path: str) -> Optional[int]:
    """
    Best-effort way to get the number of transformer blocks from a GGUF file
    using llama.cpp directly, instead of the Python gguf reader.

    Returns:
        int | None: layer count if successful, otherwise None.
    """
    (
        llama_backend_init,
        llama_model_default_params,
        llama_model_load_from_file,
        llama_model_n_layer,
        llama_model_free,
    ) = _load_llama_cpp_low_level()

    if (
        llama_backend_init is None
        or llama_model_default_params is None
        or llama_model_load_from_file is None
        or llama_model_n_layer is None
        or llama_model_free is None
    ):
        # llama-cpp-python not available / not correctly installed
        return None

    try:
        # Safe to call multiple times; no-op if already initialized
        llama_backend_init()

        params = llama_model_default_params()
        # Avoid GPU offload when probing metadata.
        try:
            if hasattr(params, "n_gpu_layers"):
                params.n_gpu_layers = 0
        except Exception:
            pass
        try:
            if hasattr(params, "main_gpu"):
                params.main_gpu = 0
        except Exception:
            pass
        # Load model *once* on CPU only – we are not creating a context,
        # just loading the weights so we can query metadata.
        model = llama_model_load_from_file(model_path.encode("utf-8"), params)
        if not model:
            return None

        try:
            n_layers = int(llama_model_n_layer(model))
        finally:
            # Important: free the model to release RAM
            llama_model_free(model)

        # sanity check
        if n_layers <= 0:
            return None

        return n_layers
    except Exception:
        # Any error here means we just fall back to "unknown layers"
        return None
