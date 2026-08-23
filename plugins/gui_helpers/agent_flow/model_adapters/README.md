# Model adapter manifests

This folder is for drop-in model capability manifests.

The important rule is:

- Workflows call explicit `models.*` Agent Flow skills.
- Adapter manifests declare which skills, assets, sources, and setting groups a model family supports.
- Adapter manifests do not auto-load, auto-select, or replace a model's default workflow.

That keeps model folders portable without making a downloaded model folder secretly take over a user's workflow. A workflow may reference an adapter by setting `model_runtime_adapter`, `runtime_adapter`, or `workflow_adapter`, but the workflow graph remains the source of truth for node order and execution.

## Drop-in folder shape

Each adapter lives in a subfolder with an `adapter.json` file:

```text
model_adapters/
  wan22/
    adapter.json
  ltx23/
    adapter.json
```

The manifest should contain:

- `id`: stable adapter id, for example `wan22`
- `skills`: map of generic stage names to public `models.*` skill ids
- `asset_keys`: asset names, labels, accepted kinds, and optional source URLs
- `aliases` / `families`: compatibility ids used to resolve a workflow profile to this adapter
- `examples`: optional workflow JSON references for users to import manually

## Safety contract

The manifest is data only. Do not put executable Python in the model adapter folder and expect it to run automatically. If a new model architecture needs custom behavior, add a reviewed skill module under `plugins/gui_helpers/agent_flow/skills/models/`, then point the manifest's `skills` entries to that public `models.*` skill.
