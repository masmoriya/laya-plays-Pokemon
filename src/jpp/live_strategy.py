"""Compact journey evidence and provider controls for the live dashboard."""

import pygame

from .live_ui_colors import MUTED, TEXT


def draw_strategy(ui, box, top):
    data = getattr(ui, "strategy_summary", None)
    if not data:
        return
    ui.button("agent_open:Steps", "Details",
              pygame.Rect(box.right - 76, top, 62, 22))
    for label, value in (("Known", data["known"]), ("Next", data["next"])):
        ui.text(label, (box.x + 14, top), ui.tiny, MUTED)
        top += 23
        lines = ui.wrap(value, ui.small, box.width - 28)
        limit = max(1, min(3, (box.bottom - 112 - top) // ui.small.get_linesize()))
        shown = lines[:limit]
        if len(lines) > limit:
            shown[-1] = shown[-1].rstrip() + '…'
        for line in shown:
            ui.text(line, (box.x + 14, top), ui.small, TEXT, max_width=box.width - 28)
            top += ui.small.get_linesize()
        top += 10
    rewards = data.get('rewards', {})
    ui.text(f"{rewards.get('points', 0)} points · {data.get('intent', 'Continue journey')}",
            (box.x + 14, top), ui.small, TEXT, max_width=box.width - 28)
    top += 22
    if ui.strategy_details:
        npcs = data.get("npcs", [])
        talked = sum(npc["status"] == "talked" for npc in npcs)
        deferred = sum(npc["status"] == "deferred" for npc in npcs)
        collected = sum(n.get('outcome') == 'collected' for n in npcs)
        unresolved = sum(n.get('outcome') == 'unresolved' for n in npcs)
        lines = [f"{talked} conversations · {collected} collected · {unresolved} unresolved",
                 data.get("playback", {}).get("status", "idle")]
        lines += [f"+{event['points']} {event['kind']} · {event['label']}"
                  for event in rewards.get("recent", [])[-3:]]
        lines += [event["detail"] for event in data.get("events", [])[-2:]]
        for value in lines:
            if top >= box.bottom - 90:
                break
            ui.text(value, (box.x + 14, top), ui.tiny, MUTED, max_width=box.width - 28)
            top += 17


def controls(ui, progress):
    if not progress.get("strategy"):
        return
    training = progress.get("training_enabled", False)
    ui.button("toggle_training", f"Training {'on' if training else 'off'}",
              pygame.Rect(1180, 1026, 120, 30), TEXT if training else MUTED)
    enabled = progress["strategy"]["enabled"]
    ui.button("agent_open:Guide", "Guide", pygame.Rect(910, 1026, 70, 30))
    ui.button("agent_open:Context", "Context", pygame.Rect(988, 1026, 82, 30))
    ui.button("toggle_luna", f"{progress['strategy'].get('planner', 'Luna')} {'on' if enabled else 'off'}",
              pygame.Rect(1078, 1026, 94, 30), TEXT if enabled else MUTED)
