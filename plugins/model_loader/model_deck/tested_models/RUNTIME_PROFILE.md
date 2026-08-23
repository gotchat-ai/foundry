# Model Deck tested-model runtime profile structure

Use `runtime_profile` in each tested model `manifest.json` to describe how the backend should understand a model family.

## Supported runtime kinds

- `diffusers_components`
  - Built-in backend routing.
  - Use this when the backend can construct the model from declared diffusers components.
  - Typical cases:
    - pipeline + transformer
    - pipeline + transformer + optional VAE
    - pipeline + UNet + scheduler

- `custom_command`
  - Advanced/custom workflow routing.
  - Use this when the model needs a custom runner or a multi-file execution flow that does not fit the built-in diffusers component loader.
  - Typical cases:
    - GGUF + connectors + VAEs + text encoder + mmproj
    - external workflow runner with companion assets

- `internal_workflow`
  - Built-in backend routing for bounded non-diffusers workflows declared by a tested profile.
  - Use this when the workflow needs extra asset slots or special orchestration, but should still be treated like a first-class built-in route instead of exposing raw JSON by default.
  - Typical cases:
    - multi-asset GGUF workflows with connectors / VAEs / text encoders
    - future tested image or video families that need extra support files and a known backend orchestration path

## Internal workflow scenarios

Internal workflows should declare a bounded `scenario` so the backend can validate the workflow shape without allowing arbitrary execution logic.

Current scenarios:

- `video_gguf_multi_asset`
  - GGUF transformer plus companion support files
  - intended for tested video families such as Unsloth-style LTX workflows

## Recommended component roles

- `pipeline`
- `transformer_2d`
- `transformer_3d`
- `unet`
- `vae`
- `scheduler`
- `controlnet`
- `text_encoder`
- `text_encoder_2`
- `tokenizer`
- `mmproj`
- `audio_encoder`
- `audio_decoder`
- `latent_upscaler`
- `lora_adapter`

## Recommended asset roles

- `pipeline_repo`
- `model_repo`
- `video_transformer_gguf`
- `image_transformer_gguf`
- `embeddings_connectors`
- `video_vae`
- `audio_vae`
- `vae_subfolder`
- `vae_dtype`
- `enable_optional_vae`
- `text_encoder_gguf`
- `text_encoder_mmproj`
- `tokenizer_model`
- `scheduler_config`
- `optional_distilled_lora`
- `optional_spatial_upscaler`
- `optional_temporal_upscaler`

## Pattern examples

### Standard diffusers family

Use `diffusers_loader` and optionally also `runtime_profile.kind = "diffusers_components"` if the model needs multiple named components.

### Wan-style family

Declare:

- pipeline repo
- transformer component
- optional VAE component
- pipeline component with inject mapping

### Unsloth-style multi-asset family

Declare:

- `runtime_profile.kind = "internal_workflow"` for the built-in routed version, or `custom_command` for a raw user-authored workflow
- `runtime_profile.scenario = "video_gguf_multi_asset"`
- required asset slots for GGUF, connectors, VAEs, text encoder, and mmproj
- optional `template.json` / `assets.json` / `params.json` defaults for the tested profile
- a bounded `workflow_id` so the backend knows which internal executor to use
- `loader_steps` describing the bounded workflow assembly order

### Internal workflow step guidance

Each `loader_steps` item should declare:

- `id`
- `kind`
- role and/or source-setting information
- any known class/module defaults needed by the scenario

Example step kinds for `video_gguf_multi_asset`:

- `gguf_transformer`
- `gguf_text_encoder`
- `support_asset`
- `optional_support_asset`
- `optional_adapter`
- `pipeline_assembly`

## Goal

The tested-model folder should be the place where we describe:

- what model family this is
- what support files it needs
- what loader pattern it uses
- what Python symbols/packages are required

So adding a new image or video model becomes mostly manifest work instead of hardcoded backend branching.
