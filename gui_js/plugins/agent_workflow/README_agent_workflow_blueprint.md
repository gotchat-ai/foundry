# Agent Workflow Architecture Blueprint

## Vision

Build one main plugin that behaves like a workflow operating system
rather than many isolated workflow plugins.

Core concept:

``` text
agent_workflow
```

This becomes the workflow brain instead of creating separate hardcoded
systems for repo review, bug fixing, QA, release, documentation, and
feature work.

------------------------------------------------------------------------

## Core Workflow Philosophy

Instead of separate workflows:

``` text
repo review workflow
bug fix workflow
feature workflow
QA workflow
release workflow
docs workflow
```

Build one reusable universal pipeline:

``` text
Intake
→ Classify
→ Gather Context
→ Plan
→ Execute
→ Review
→ Test
→ Summarize
→ Learn
```

Every request uses the same backbone, with stages enabled or skipped
depending on the request.

------------------------------------------------------------------------

## Plugin Structure

Server side:

``` text
app/plugins/gui_helper/agent_workflow/
    plugin.py
    registry.py
    schemas.py
    planner.py
    context.py
    executor.py
    reviewers.py
    workflows.py
    memory.py
    trace.py
```

Client side:

``` text
gui_js/plugins/agent_workflow/
    plugin.js
    panel.html
    panel.js
```

Endpoints:

``` text
POST /v1/agent_workflow/run
POST /v1/agent_workflow/stream
```

------------------------------------------------------------------------

## Universal Workflow Request Schema

``` json
{
  "pid": "project_id",
  "sid": "session_id",
  "intent": "auto",
  "input": "Fix the login bug in chat_qt",
  "targets": {
    "repo_ids": ["current"],
    "files": []
  },
  "mode": "plan_only | suggest_patch | apply_patch | review_only",
  "constraints": {
    "no_zip": true,
    "ast_patch_only": true,
    "preserve_plugin_boundaries": true
  }
}
```

Server execution flow:

``` text
1. classify request
2. select workflow template
3. gather repo/context
4. build plan
5. run tools
6. review result
7. produce patch/output
8. store trace/learning
```

------------------------------------------------------------------------

## Workflow Templates

### Template A: Feature Change

``` text
classify
→ gather repo context
→ architecture review
→ implementation plan
→ patch generation
→ code review
→ test suggestions
→ changelog
```

Use cases: - Add model schema wizard - Add plugin config tab - Add
dispatch endpoint - Add collaboration feature

### Template B: Bug Fix

``` text
classify
→ reproduce/trace
→ locate related code
→ root cause hypothesis
→ minimal patch
→ regression review
→ test case
→ changelog
```

Use cases: - login does nothing - Qt message overlaps - SSE stream
closes early - plugin toggle persistence bugs

### Template C: Repo Review

``` text
classify
→ scan repo structure
→ map key files
→ identify plugin boundaries
→ risk analysis
→ recommendations
```

### Template D: Release / QA

``` text
classify
→ gather changelog
→ compare changed files
→ run checklist
→ identify missing tests
→ release notes
```

### Template E: Learning / Feedback

``` text
classify
→ capture correction
→ map correction to entity/file/function/workflow
→ store feedback
→ update routing hints
```

Examples: - wrong function - wrong file - wrong entity id - bad patch
location - wrong workflow

------------------------------------------------------------------------

## Simplification Rule

Only allow these workflow families:

``` text
feature
bugfix
review
qa_release
learning_feedback
```

Everything else maps into these.

------------------------------------------------------------------------

## Stage Registry Architecture

``` python
STAGES = {
    "classify": classify_request,
    "gather_context": gather_context,
    "plan": make_plan,
    "execute": execute_step,
    "review": review_output,
    "test": suggest_or_run_tests,
    "changelog": generate_changelog,
    "learn": capture_learning,
}
```

``` python
WORKFLOWS = {
    "bugfix": [
        "classify",
        "gather_context",
        "plan",
        "execute",
        "review",
        "test",
        "changelog",
        "learn",
    ],
}
```

------------------------------------------------------------------------

## Internal Skill Reviewers

``` python
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

------------------------------------------------------------------------

## Why This Beats gstack

Advantages:

``` text
repo-aware
project-aware
session-aware
plugin-aware
model-loader-aware
multi-user
streaming
traceable
learning-enabled
```

The moat is infrastructure plus orchestration, not prompts.

------------------------------------------------------------------------

## Implementation Roadmap

### Phase 1: Workflow Skeleton

Build: - agent_workflow/run - agent_workflow/stream - WorkflowRun
schema - WorkflowResult schema - stage registry - workflow template
registry - trace log

### Phase 2: Repo Context Integration

Connect: - repo ids - file tree - selected files - function/class
chunks - session context - user constraints - RAG context

### Phase 3: Plan-Only Mode

Support:

``` text
mode: plan_only
```

Output: - intent - workflow selection - likely files - risk - step
plan - missing context

### Phase 4: Patch Suggestion Mode

Support:

``` text
mode: suggest_patch
```

Output: - file target - function/class target - patch code - where to
apply - why - suggested tests - changelog

### Phase 5: Learning Feedback

Capture: - wrong file - wrong function - wrong entity - wrong workflow -
bad patch - missing dependency

Example routing hint:

``` json
{
  "pattern": "auth_projects JS login",
  "preferred_files": [
    "gui_js/plugins/auth_projects/plugin.js",
    "gui_js/chat_js.js"
  ],
  "avoid": [
    "hardcoding plugin logic into framework"
  ]
}
```

------------------------------------------------------------------------

## Minimum Viable Version

Needs:

``` text
1 endpoint family
5 workflow templates
8 reusable stages
6 internal reviewers
trace log
repo context adapter
plan_only mode
suggest_patch mode
feedback capture
```

------------------------------------------------------------------------

## Target User Experience

Example request:

``` text
Fix the auth_projects login issue in Qt
```

System behavior:

``` text
classify as bugfix
identify auth_projects + chat_qt app context
load repo context
apply prior corrections
generate plan
review plugin boundaries
produce exact patch
generate changelog
capture feedback
```

------------------------------------------------------------------------

## Final Mental Model

Not:

``` text
30 separate plugins
```

Instead:

``` text
One workflow brain
Reusable execution stages
Internal role reviewers
Optional specialized tools underneath
Continuous learning feedback
```
