# J.A.R.V.I.S. plugins

Place Python files ending in `.py` in this folder, then restart JARVIS.

Plugins are trusted local Python code and run with the same permissions as the assistant. Review every plugin before installing it. Do not put API keys, passwords or other secrets in plugin files.

## Minimal plugin

```python
def register():
    return [{
        "definition": {
            "type": "function",
            "function": {
                "name": "example_greeting",
                "description": "Return a short greeting from the example plugin.",
                "parameters": {"type": "object", "properties": {}, "required": []}
            }
        },
        "handler": lambda arguments: "The JARVIS plugin system is working."
    }]
```

Each plugin must expose `register()` and return a list of entries. Each entry contains an OpenAI-style function tool schema under `definition` and a Python callable under `handler`. The handler receives one dictionary of arguments.

Use unique tool names containing letters, numbers and underscores. Plugin exceptions are caught and reported in the JARVIS activity log.