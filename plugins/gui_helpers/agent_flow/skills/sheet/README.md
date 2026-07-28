# Agent Flow Sheet Skills Drop-in

Install by copying `plugins/gui_helpers/agent_flow/skills/sheet/` into the matching repo path.

This layout matches the current Agent Flow loader: each skill is a direct `.py` file under one category folder and each exposes `TOOL_SPEC` plus synchronous `run(ctx, params)`.
