Drop-in Agent Flow skills for this category go in this folder.

Each Python file should export either:

```python
TOOL_SPEC = {
    "id": "category.tool_name",
    "category": "category",
    "label": "Human label",
    "description": "What this skill does",
    "permissions": ["category.tool_name", "category.*"],
}

def run(ctx, params):
    return {"ok": True, "data": {}, "warnings": []}
```

or:

```python
def get_tool_spec(app):
    return {...}
```
