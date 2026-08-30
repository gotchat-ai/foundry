# llmloader2 CrispASR compatibility patches

This vendor tree is used by the llmloader2 CrispASR runtime manager and the
Voice STT WebRTC / WeSpeaker plugin.

## WeSpeaker C API symbol export patch

The plugin calls the WeSpeaker runtime through `ctypes` when available. On
Windows, those functions must be exported from `crispasr.dll`; otherwise the
DLL may load but the WeSpeaker entry points are not visible.

The runtime manager applies an idempotent patch to:

```text
src/wespeaker.h
```

The patch adds `WESPEAKER_API` and annotates the public WeSpeaker functions:

- `wespeaker_context_default_params`
- `wespeaker_init_from_file`
- `wespeaker_free`
- `wespeaker_init_worker`
- `wespeaker_embed_dim`
- `wespeaker_sample_rate`
- `wespeaker_n_mels`
- `wespeaker_min_samples`
- `wespeaker_embed`
- `wespeaker_embed_windows`
- `wespeaker_compute_fbank`
- `wespeaker_embed_staged`

The patch is intentionally applied after clone/pull/submodule update and before
CMake configure/build so rebuilds, reinstalls, and platform-specific runtime
builds keep the WeSpeaker export surface.

On POSIX/macOS/Linux install scripts, the patch helper chooses Python in this
order:

1. `LLMLOADER2_PATCH_PYTHON` environment override
2. `python3`
3. `python`
4. the Python executable currently running llmloader2

If this vendor folder is replaced with a fresh upstream checkout, keep the
runtime-manager patch in:

```text
plugins/gui_helpers/crispasr_runtime_manager/routes.py
```

or upstream an equivalent export annotation into CrispASR.
