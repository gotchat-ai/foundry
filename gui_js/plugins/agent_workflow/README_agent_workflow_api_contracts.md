
# README_agent_workflow_api_contracts

# Agent Workflow API Contracts & Implementation Interfaces

## Purpose

This document defines the implementation contracts required to build the Agent Workflow Operating System on top of the current infrastructure.

This is the direct implementation companion to:

- README_agent_workflow_blueprint.md
- README_agent_workflow_solution_spec.md

Goal:

```text
Move from architecture into implementation-ready interfaces.
```

---

# System Layers

```text
Client UI
    ↓
agent_workflow API
    ↓
workflow planner
    ↓
agent_flow graph engine
    ↓
node execution
    ↓
ai_router / plugins / tools
```

---

# FastAPI Endpoints

## 1. Run Workflow

Endpoint:

```text
POST /v1/agent_workflow/run
```

Purpose:

```text
synchronous workflow execution
short/medium workflows
plan generation
review tasks
patch suggestion
```

Response:

```json
WorkflowResult
```

---

## 2. Stream Workflow

Endpoint:

```text
POST /v1/agent_workflow/stream
```

Purpose:

```text
long-running workflows
multi-stage execution
repo analysis
test execution
interactive approvals
progress streaming
```

Response:

```text
SSE event stream
```

---

## 3. Approval Response

Endpoint:

```text
POST /v1/agent_workflow/approval
```

Purpose:

```text
resume paused workflow
human approval gates
```

---

## 4. Workflow Status

Endpoint:

```text
GET /v1/agent_workflow/status/{workflow_id}
```

Purpose:

```text
inspect current workflow state
```

---

## 5. Cancel Workflow

Endpoint:

```text
POST /v1/agent_workflow/cancel/{workflow_id}
```

Purpose:

```text
cancel execution
cleanup resources
```

---

# Pydantic Schemas

## WorkflowRunRequest

```python
class WorkflowRunRequest(BaseModel):
    pid: str
    sid: str
    intent: str = "auto"
    input: str
    mode: str = "plan_only"
    workflow_family: Optional[str] = None
    targets: dict = {}
    constraints: dict = {}
    options: dict = {}
```

---

## WorkflowResult

```python
class WorkflowResult(BaseModel):
    workflow_id: str
    ok: bool
    workflow_family: str
    mode: str
    summary: str
    outputs: list
    warnings: list
    errors: list
    trace_id: Optional[str]
```

---

## ApprovalRequest

```python
class ApprovalRequest(BaseModel):
    workflow_id: str
    node_id: str
    action: str
    notes: Optional[str] = None
```

Actions:

```text
approve
reject
revise
cancel
```

---

## WorkflowStatus

```python
class WorkflowStatus(BaseModel):
    workflow_id: str
    state: str
    current_stage: Optional[str]
    current_node: Optional[str]
    started_at: datetime
    updated_at: datetime
    progress: float
```

---

# Workflow State Object

Internal state:

```python
class WorkflowContext:
    workflow_id: str
    pid: str
    sid: str
    user_input: str
    workflow_family: str
    mode: str
    constraints: dict
    options: dict
    graph_state: dict
    memory_state: dict
    trace: list
    approvals: dict
    outputs: list
```

---

# Workflow Registry Contract

```python
class WorkflowRegistry:
    def register_workflow(self, name, definition):
        ...

    def get_workflow(self, name):
        ...

    def list_workflows(self):
        ...
```

Workflow definition:

```python
{
    "family": "bugfix",
    "stages": [...],
    "reviewers": [...],
    "approval_required": False,
}
```

---

# Stage Contract

```python
class WorkflowStage:
    async def run(self, ctx: WorkflowContext):
        ...
```

Stage result:

```python
{
    "ok": True,
    "data": {},
    "warnings": [],
    "errors": []
}
```

---

# Agent Flow Graph Schema

```json
{
  "flow_id": "bugfix_basic",
  "nodes": [],
  "edges": [],
  "metadata": {}
}
```

---

## Node Schema

```json
{
  "id": "context_1",
  "type": "context_node",
  "config": {},
  "inputs": [],
  "outputs": []
}
```

---

## Edge Schema

```json
{
  "from": "context_1",
  "to": "planner_1"
}
```

---

# Node Execution Contract

```python
class AgentFlowNode:
    async def run(self, ctx, node_config):
        ...
```

Result:

```python
{
    "ok": True,
    "data": {},
    "state_updates": {},
    "events": []
}
```

---

# Node Types

Supported:

```text
context_node
planner_node
ai_router_node
tool_node
review_node
test_node
approval_node
memory_node
output_node
```

---

# AI Router Contract

```python
class AIRouterAdapter:
    async def execute(
        self,
        route: str,
        prompt: str,
        context: dict,
        options: dict
    ):
        ...
```

Routes:

```text
planning
coding
review
security
qa
release
docs
vision
automation
```

---

# Tool Registry Contract

```python
class WorkflowToolRegistry:
    def register_tool(
        self,
        name,
        handler,
        permissions=None
    ):
        ...

    async def call_tool(
        self,
        name,
        ctx,
        params
    ):
        ...
```

Tool result:

```python
{
    "ok": True,
    "data": {},
    "warnings": []
}
```

---

# Plugin Adapter Contract

Existing plugins should expose adapters.

Example:

```python
def register_agent_workflow_tools(registry):
    registry.register_tool(
        "repo.context",
        get_repo_context
    )
```

Examples:

```text
repo.context
repo.tree
repo.search
rag.search
tests.smoke
browser.run
model.load
auth.project_context
collab.session_context
learning.capture_feedback
```

---

# Reviewer Contract

```python
class Reviewer:
    async def review(
        self,
        ctx,
        artifact
    ):
        ...
```

Profiles:

```text
product
architect
staff_engineer
security
qa
release
docs
```

---

# Approval Persistence Contract

```python
class ApprovalStore:
    async def create_request(...)
    async def get_request(...)
    async def resolve_request(...)
```

Approval states:

```text
pending
approved
rejected
revision_requested
cancelled
```

---

# Trace Contract

```python
class WorkflowTraceEntry(BaseModel):
    timestamp: datetime
    stage: str
    node_id: Optional[str]
    event_type: str
    message: str
    data: dict
```

Trace store:

```python
class TraceStore:
    async def append(...)
    async def get_trace(...)
```

---

# SSE Event Schema

Events:

## workflow_start

```json
{
  "workflow_id": "wf_123",
  "family": "bugfix"
}
```

## stage_start

```json
{
  "stage": "plan"
}
```

## stage_progress

```json
{
  "stage": "plan",
  "message": "Building patch strategy"
}
```

## node_start

```json
{
  "node_id": "planner_1",
  "node_type": "planner_node"
}
```

## node_result

```json
{
  "node_id": "planner_1",
  "ok": true
}
```

## approval_required

```json
{
  "workflow_id": "wf_123",
  "node_id": "approval_1"
}
```

## workflow_error

```json
{
  "message": "tool execution failed"
}
```

## workflow_complete

```json
{
  "workflow_id": "wf_123",
  "ok": true
}
```

---

# Permissions Contract

Every tool call should validate:

```python
pid
sid
user identity
project membership
plugin permission
workflow mode
approval state
```

---

# GUI Client Contract

GUI responsibilities:

```text
submit workflow request
render SSE progress
render approval UI
send approval response
show trace log
show workflow outputs
capture corrections
```

---

# Build Order

## First

Implement:

```text
schemas
workflow endpoints
workflow context
trace store
tool registry
```

## Second

Implement:

```text
agent_flow node contracts
node registry
core nodes
```

## Third

Implement:

```text
plugin adapters
ai_router adapter
reviewers
approval persistence
```

## Fourth

Implement:

```text
learning feedback
heuristics
workflow optimization
```

---

# Final Rule

The implementation must preserve:

```text
existing plugin ecosystem
existing endpoints
existing AI router
existing model loaders
existing RAG systems
existing project/session model
```

This is an orchestration layer, not a rewrite.
