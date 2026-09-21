"""Compact formatting for the live model activity panel."""

import json


def collapse_repeated(entries):
    """Collapse adjacent identical events while preserving their order."""
    collapsed = []
    for entry in entries or ():
        value = str(entry)
        if collapsed and collapsed[-1][0] == value:
            collapsed[-1] = (value, collapsed[-1][1] + 1)
        else:
            collapsed.append((value, 1))
    return [f"{value} ×{count}" if count > 1 else value
            for value, count in collapsed]


def format_model_input(payload):
    """Return the exact latest provider payload as readable JSON."""
    if not payload:
        return []
    provider = str(payload.get("provider") or "Model")
    body = {key: value for key, value in payload.items() if key != "provider"}
    return [f"{provider} input", json.dumps(body, indent=2, sort_keys=True, default=str)]
