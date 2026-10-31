"""A harmless example plugin proving that plugin discovery works."""


def register():
    return [{
        "definition": {
            "type": "function",
            "function": {
                "name": "jarvis_plugin_status",
                "description": "Check whether the example JARVIS plugin is loaded.",
                "parameters": {"type": "object", "properties": {}, "required": []}
            }
        },
        "handler": lambda arguments: "The JARVIS plugin system is working."
    }]
