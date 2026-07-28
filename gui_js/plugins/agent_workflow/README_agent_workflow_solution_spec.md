
# README_agent_workflow_solution_spec

# Agent Workflow Solution Specification for Existing Infrastructure

## Purpose

This document consolidates the architecture blueprint and implementation strategy for evolving the current infrastructure into a unified workflow operating system that is comparable to gstack, but built around the existing plugin-based FastAPI + client/server architecture.

Goal:

```text
Build one workflow operating system plugin that orchestrates existing infrastructure instead of replacing it.
```

Core principles:

- preserve existing plugins
- avoid plugin explosion
- reuse current infrastructure
- centralize orchestration
- support streaming workflows
- support AI routing
- support human approval
- support learning feedback
- remain plugin-driven

---

# Existing Infrastructure Mapping

Current infrastructure already provides major building blocks.

## Existing components

```text
FastAPI server
AI router plugins
agent_flow plugin
repo_panel
repo_rag
user_rag
lib_rag
auth_projects
collab_chat
model_loader plugins
GUI helper plugins
chat clients
SSE streaming
plugin discovery
project/session context
```

Meaning the missing piece is orchestration, not raw capability.

---

# Final Architecture

```text
User
  ↓
agent_workflow
  ↓
workflow classifier
  ↓
workflow planner
  ↓
agent_flow graph execution
  ↓
node execution
  ↓
ai_router / tools / plugins
  ↓
streamed results
  ↓
learning feedback
```

Responsibility split:

## agent_workflow

Owns:

```text
workflow selection
workflow templates
stage sequencing
trace logging
approval control
learning capture
execution policies
```

## agent_flow

Owns:

```text
graph execution
node lifecycle
dependency execution
parallel execution
pause/resume
state propagation
node error handling
```

## ai_router

Owns:

```text
model selection
backend routing
reasoning strategy
tool-call capable models
coding models
VLM models
automation models
```

## existing plugins

Own:

```text
specialized capabilities
repo context
auth context
collaboration context
tool execution
model loading
testing
browser automation
memory persistence
```

---

# Why Not Rewrite Existing Plugins

Bad architecture:

```text
rewrite repo_panel
rewrite auth_projects
rewrite collab
rewrite model_loader
rewrite ai_router
```

Good architecture:

```text
adapter layer
```

Example:

```python
registry.register_tool("repo.context", repo_context_handler)
registry.register_tool("repo.tree", repo_tree_handler)
registry.register_tool("auth.project_context", auth_project_handler)
registry.register_tool("tests.smoke", smoke_test_handler)
```

Reuse existing endpoints internally through direct Python calls, not HTTP loopbacks.

Never do:

```python
await httpx.post("http://localhost:8000/v1/repo/context")
```

Do:

```python
await repo_plugin.get_repo_context(ctx, params)
```

---

# Server Plugin Layout

## agent_workflow plugin

```text
app/plugins/gui_helper/agent_workflow/
    plugin.py
    schemas.py
    registry.py
    workflows.py
    planner.py
    context.py
    executor.py
    reviewers.py
    approvals.py
    memory.py
    trace.py
```

## agent_flow extension

```text
app/plugins/gui_helper/agent_flow/
    plugin.py
    engine.py
    registry.py
    nodes/
        context.py
        planner.py
        ai_router.py
        tool.py
        review.py
        test.py
        approval.py
        memory.py
        output.py
```

---

# Workflow Request Contract

```json
{
  "pid": "project_id",
  "sid": "session_id",
  "intent": "auto",
  "input": "Fix login bug in chat_qt",
  "mode": "plan_only",
  "constraints": {
    "ast_patch_only": true,
    "preserve_plugin_boundaries": true
  }
}
```

Modes:

```text
plan_only
suggest_patch
apply_patch
review_only
qa_only
release_only
```

---

# Workflow Families

Keep only five families.

```text
feature
bugfix
review
qa_release
learning_feedback
```

Everything maps into these.

---

# Workflow Stages

Reusable stages:

```python
STAGES = {
    "classify": classify_request,
    "gather_context": gather_context,
    "plan": make_plan,
    "execute": execute_step,
    "review": review_output,
    "test": run_tests,
    "approval": await_approval,
    "learn": capture_feedback,
    "output": format_output,
}
```

---

# Agent Flow Node Types

Add node types inside agent_flow backend.

Not separate plugins.

## context_node

Purpose:

```text
collect repo/session/project/plugin context
```

Uses:

```text
repo_panel
repo_rag
auth_projects
collab_chat
session metadata
```

---

## planner_node

Purpose:

```text
convert request into execution plan
```

Uses:

```text
agent_workflow planner
ai_router planning profile
```

---

## ai_router_node

Purpose:

```text
reasoning execution
```

Uses:

```text
existing ai_router plugin
```

Profiles:

```text
planning
coding
review
security
product
qa
docs
release
vision
automation
```

---

## tool_node

Purpose:

```text
execute registered tools
```

Examples:

```text
repo.tree
repo.context
tests.smoke
browser.run
model.load
rag.search
```

---

## review_node

Purpose:

```text
review outputs
```

Reviewer profiles:

```text
staff_engineer
architect
security
qa
release
product
```

---

## test_node

Purpose:

```text
validation
```

Examples:

```text
smoke test
regression test
CI helper
integration test
```

---

## approval_node

Purpose:

```text
pause workflow until user/admin approval
```

Supports:

```text
approve
reject
revise
```

---

## memory_node

Purpose:

```text
store lessons and corrections
```

Uses:

```text
entity_memory
feedback system
learning plugin
workflow hints
```

---

## output_node

Purpose:

```text
final formatting
streaming output
patch generation
changelog
```

---

# Skill Reviewers

Internal reviewer profiles.

```python
SKILLS = {
    "product": ProductReviewer,
    "architect": ArchitectureReviewer,
    "staff_engineer": StaffEngineerReviewer,
    "security": SecurityReviewer,
    "qa": QAReviewer,
    "release": ReleaseReviewer,
    "docs": DocsReviewer,
}
```

---

# Tool Registry

Common registry:

```python
class WorkflowToolRegistry:
    def register_tool(self, name, handler, permissions=None):
        ...

    async def call_tool(self, name, ctx, params):
        ...
```

Plugin registration:

```python
def register_agent_workflow_tools(registry):
    registry.register_tool("repo.context", get_repo_context)
    registry.register_tool("repo.tree", get_repo_tree)
    registry.register_tool("tests.smoke", run_smoke_tests)
```

---

# Execution Example

Bug fix request:

```text
Fix auth_projects login in Qt
```

Execution:

```text
classify → bugfix
context_node → repo + auth + Qt files
planner_node → patch plan
ai_router_node → generate fix
review_node → staff engineer review
test_node → smoke tests
approval_node → optional human approval
output_node → patch + changelog
memory_node → capture correction
```

---

# Streaming Architecture

Use SSE.

Endpoints:

```text
POST /v1/agent_workflow/run
POST /v1/agent_workflow/stream
```

Events:

```text
workflow_start
stage_start
stage_progress
node_start
node_result
approval_required
approval_received
workflow_error
workflow_complete
```

---

# Migration Strategy

## Phase 1

Build skeleton.

Deliver:

```text
agent_workflow plugin
basic schemas
workflow registry
trace log
SSE endpoint
```

---

## Phase 2

Extend agent_flow.

Deliver:

```text
context_node
tool_node
ai_router_node
output_node
approval_node
```

---

## Phase 3

Add intelligence.

Deliver:

```text
planner_node
review_node
memory_node
test_node
```

---

## Phase 4

Repo integration.

Deliver:

```text
repo adapters
rag adapters
auth adapters
collab adapters
```

---

## Phase 5

Learning.

Deliver:

```text
feedback capture
routing hints
correction memory
workflow heuristics
```

---

# Design Rules

Always:

```text
plugin boundaries preserved
no hardcoded GUI logic in framework
direct Python calls internally
typed registries
structured traces
permission enforcement
project/session aware execution
```

Never:

```text
plugin spaghetti
HTTP loopback calls
AI router owning workflow orchestration
duplicated plugin logic
50 disconnected workflows
```

---

# Final Mental Model

This is not:

```text
another plugin
```

This is:

```text
workflow operating system
```

Stack:

```text
agent_workflow = orchestration brain
agent_flow = execution graph engine
ai_router = reasoning backend selector
plugins = capability providers
learning = continuous improvement
```

This architecture evolves the current platform into a true multi-agent workflow system.
