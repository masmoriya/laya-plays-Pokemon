"""Compact journey evidence and provider controls for the live dashboard."""

import pygame

from .live_ui_colors import MUTED, TEXT


def draw_strategy(ui, box, top):
    data = getattr(ui, "strategy_summary", None)
    if not data:
        return
    ui.button("strategy_details", "Details" if not ui.strategy_details else "Less",
              pygame.Rect(box.right - 76, top, 62, 22))
    for label, value in (("Known", data["known"]), ("Next", data["next"])):
        ui.text(label, (box.x + 14, top), ui.tiny, MUTED)
        for line in ui.wrap(value, ui.small, box.width - 100)[:2]:
            ui.text(line, (box.x + 60, top + 24), ui.small, TEXT)
            top += 18
        top += 28
    rewards = data.get('rewards', {})
    ui.text(f"{rewards.get('points', 0)} points · {data.get('intent', 'Continue journey')}",
            (box.x + 14, top), ui.small, TEXT, max_width=box.width - 28)
    top += 22
    if ui.strategy_details:
        npcs = data.get("npcs", [])
        talked = sum(npc["status"] == "talked" for npc in npcs)
        deferred = sum(npc["status"] == "deferred" for npc in npcs)
        lines = [f"NPCs: {talked}/{len(npcs)} talked · {deferred} deferred",
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
    enabled = progress["strategy"]["enabled"]
    ui.button("toggle_luna", f"Luna strategy {'On' if enabled else 'Off'}",
              pygame.Rect(1012, 1026, 144, 30))
    if progress.get("agent_paused"):
        ui.button("retry_agent", "Retry", pygame.Rect(1164, 1026, 60, 30))
