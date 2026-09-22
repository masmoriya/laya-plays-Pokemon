"""Rendering helpers for the compact live agent inspector."""

import json

import pygame

from .agent.notebook import text_lines
from .live_ui_colors import ACCENT, BG, GOOD, MUTED, PANEL, SURFACE, TEXT, WARN


BOX = pygame.Rect(342, 176, 640, 828)


def draw_inspector(ui, panel):
    ui.actions = {key: rect for key, rect in ui.actions.items() if not rect.colliderect(BOX)}
    pygame.draw.rect(ui.canvas, BG, BOX)
    ui.text("Agent", (BOX.x + 18, BOX.y + 18), ui.title)
    for index, view in enumerate(("Guide", "Context", "Vision", "Notes", "Steps")):
        ui.button("agent_view:" + view, view,
                  pygame.Rect(BOX.x + 18 + index * 94, BOX.y + 58, 86, 28),
                  TEXT if panel.view == view else MUTED)
    ui.button("notebook", "Close", pygame.Rect(BOX.right - 92, BOX.y + 58, 74, 28))
    if panel.view == "Guide":
        _guide(ui, panel)
    elif panel.view == "Context":
        _context(ui, panel)
    elif panel.view == "Vision":
        _vision(ui, panel)
    elif panel.view == "Steps":
        from .journey_checklist import checklist_lines
        lines = [line for entry in checklist_lines(panel.progress.get('strategy') or {})
                 for line in ui.wrap(entry, ui.small, BOX.width - 36)]
        _paged_lines(ui, panel, lines, BOX.y + 110, BOX.bottom - 58)
    else:
        _notes(ui, panel)


def _guide(ui, panel):
    strategy = panel.progress.get("strategy") or {}
    top = BOX.y + 112
    active = (strategy.get("operator_guidance") or {}).get("text")
    ui.text("Active guide", (BOX.x + 18, top), ui.tiny, MUTED)
    ui.text(active or "No guide for this Journey step", (BOX.x + 18, top + 22),
            ui.small, TEXT if active else MUTED, max_width=BOX.width - 36)
    top += 72
    ui.text("Tell Laya what to try or remember", (BOX.x + 18, top), ui.small, TEXT)
    input_box = pygame.Rect(BOX.x + 18, top + 30, BOX.width - 36, 92)
    pygame.draw.rect(ui.canvas, SURFACE, input_box, border_radius=6)
    value = panel.composer or "Type here…"
    color = TEXT if panel.composer else MUTED
    for index, line in enumerate(ui.wrap(value, ui.body, input_box.width - 24)[:3]):
        ui.text(line, (input_box.x + 12, input_box.y + 12 + index * 24), ui.body, color)
    ui.button("agent_guide", "Guide", pygame.Rect(BOX.x + 18, top + 136, 76, 30), GOOD)
    ui.button("agent_remember", "Remember", pygame.Rect(BOX.x + 104, top + 136, 96, 30))
    ui.text("Guide replans this Journey step. Remember stores a user note.",
            (BOX.x + 18, top + 182), ui.small, MUTED, max_width=BOX.width - 36)


def _context(ui, panel):
    state = panel.progress.get("agent_state") or {}
    calls = state.get("model_calls") or []
    enabled = bool((panel.progress.get("strategy") or {}).get("enabled"))
    providers = [panel.progress.get("tactical_provider", "laya")]
    if enabled or any(item.get("provider") == "luna" for item in calls):
        providers.append("luna")
    if panel.provider not in providers:
        panel.provider = providers[0]
    top = BOX.y + 106
    for index, provider in enumerate(providers):
        ui.button("agent_provider:" + provider, provider.title(),
                  pygame.Rect(BOX.x + 18 + index * 74, top, 66, 25),
                  TEXT if panel.provider == provider else MUTED)
    ui.button("agent_context_mode", "Compact" if panel.raw_context else "Raw",
              pygame.Rect(BOX.right - 92, top, 74, 25), MUTED)
    top += 42
    provider_calls = [item for item in calls if item.get("provider") == panel.provider]
    if provider_calls:
        panel.call_index = max(-len(provider_calls), min(-1, panel.call_index))
        selected = provider_calls[panel.call_index]
        selected_number = len(provider_calls) + panel.call_index + 1
        _metrics(ui, selected, top)
        ui.text(f"Call {selected_number}/{len(provider_calls)}",
                (BOX.x + 18, top + 52), ui.tiny, MUTED)
        if selected_number > 1:
            ui.button("agent_call_previous", "Prev",
                      pygame.Rect(BOX.right - 100, top + 45, 38, 22), MUTED)
        if selected_number < len(provider_calls):
            ui.button("agent_call_next", "Next",
                      pygame.Rect(BOX.right - 58, top + 45, 40, 22), MUTED)
        _graph(ui, provider_calls[-20:], pygame.Rect(BOX.x + 18, top + 76, BOX.width - 36, 80))
    else:
        ui.text("No calls yet", (BOX.x + 18, top), ui.small, MUTED)
    top += 176
    lean = bool((panel.progress.get("strategy") or {}).get("lean_context"))
    ui.button("agent_toggle_lean", "Lean on" if lean else "Lean off",
              pygame.Rect(BOX.x + 18, top, 82, 28), ACCENT if lean else MUTED)
    ui.button("agent_replan", "Replan", pygame.Rect(BOX.x + 110, top, 76, 28))
    top += 46
    model_input = (state.get("model_inputs") or {}).get(panel.provider) or {}
    if panel.raw_context:
        body = json.dumps(model_input, indent=2, sort_keys=True, default=str)
        lines = [line for paragraph in body.splitlines()
                 for line in ui.wrap(paragraph or " ", ui.small, BOX.width - 36)]
    else:
        lines = _compact_context(model_input)
    _paged_lines(ui, panel, lines, top, BOX.bottom - 58)


def _metrics(ui, sample, top):
    values = [str(sample.get("status") or "completed").title()]
    if sample.get("submitted_tokens") is not None:
        values.append(f"Submitted {sample['submitted_tokens']:,}")
    if sample.get("retained_tokens") is not None and sample.get("budget"):
        values.append(f"Retained {sample['retained_tokens']:,}/{sample['budget']:,}")
    elif sample.get("input_tokens"):
        values.append(f"Input {sample['input_tokens']:,} tokens")
    if sample.get("latency_ms"):
        values.append(f"{sample['latency_ms']:.0f} ms")
    if sample.get("confidence") is not None:
        values.append(f"{sample['confidence']:.0%} confidence")
    ui.text(" · ".join(values),
            (BOX.x + 18, top), ui.small, TEXT, max_width=BOX.width - 36)
    omitted = sample.get("omitted_fields") or []
    fallback = sample.get("fallback")
    detail = (("Fallback: " + str(fallback)) if fallback else
              ("Omitted " + ", ".join(omitted)) if omitted else
              sample.get("error") or "All reported fields retained")
    ui.text(detail, (BOX.x + 18, top + 27), ui.small,
            WARN if omitted or sample.get("error") else MUTED, max_width=BOX.width - 36)


def _graph(ui, samples, box):
    pygame.draw.rect(ui.canvas, PANEL, box, border_radius=5)
    values = [int(item.get("retained_tokens") or item.get("input_tokens") or 0)
              for item in samples]
    if len(values) < 2 or max(values) <= 0:
        return
    maximum = max(values)
    step = box.width / (len(values) - 1)
    points = [(box.x + index * step, box.bottom - 10 - value / maximum * (box.height - 20))
              for index, value in enumerate(values)]
    pygame.draw.lines(ui.canvas, ACCENT, False, points, 2)
    for index, item in enumerate(samples):
        if item.get("status") == "error":
            pygame.draw.circle(ui.canvas, WARN, (round(points[index][0]), round(points[index][1])), 4)


def _compact_context(model_input):
    context = model_input.get("context") or {}
    state = model_input.get("state") or {}
    values = []
    for label, value in (
        ("Goal", state.get("goal")), ("Mode", state.get("decision_kind")),
        ("Map", state.get("map")), ("Position", state.get("position")),
        ("Guide", state.get("operator_guidance")), ("Strategy", state.get("strategy")),
    ):
        if value not in (None, "", [], {}):
            values.append(f"{label}: {value}")
    if context.get("retained_fields"):
        values.append("Retained: " + ", ".join(context["retained_fields"]))
    return values or ["No inspectable context for this provider yet"]


def _vision(ui, panel):
    vision = ((panel.progress.get("agent_state") or {}).get("vision"))
    if not vision:
        ui.text("No Luna vision call yet", (BOX.x + 18, BOX.y + 118), ui.small, MUTED)
        return
    ui.text(vision.get("status", "unknown").title(), (BOX.x + 18, BOX.y + 112),
            ui.small, GOOD if vision.get("status") == "completed" else WARN)
    frame = vision.get("frame")
    if frame is not None:
        image = pygame.surfarray.make_surface(frame.swapaxes(0, 1)[:, :, :3])
        target = pygame.Rect(BOX.x + 80, BOX.y + 150, 480, 432)
        ui.canvas.blit(pygame.transform.scale(image, target.size), target)
    result = vision.get("result") or {}
    mode = result.get("mode")
    if mode:
        ui.text("Mode: " + str(mode).title(), (BOX.x + 18, BOX.y + 608), ui.small, TEXT)
    screen_text = " / ".join(result.get("screen_text") or ())
    if screen_text:
        ui.text(screen_text, (BOX.x + 18, BOX.y + 632), ui.small, TEXT,
                max_width=BOX.width - 36)
    detail = result.get("uncertainty") or vision.get("error")
    if detail:
        ui.text(detail, (BOX.x + 18, BOX.y + 656), ui.small, WARN,
                max_width=BOX.width - 36)
    prompt = (vision.get("model_input") or {}).get("prompt")
    if prompt:
        ui.text("Prompt", (BOX.x + 18, BOX.y + 692), ui.tiny, MUTED)
        for index, line in enumerate(ui.wrap(prompt, ui.small, BOX.width - 36)[:4]):
            ui.text(line, (BOX.x + 18, BOX.y + 712 + index * 20), ui.small, TEXT,
                    max_width=BOX.width - 36)


def _notes(ui, panel):
    data = panel.data or {"goal": "Continue", "next": "No plan", "blocker": "",
                          "completed": [], "manual": [], "learned": [],
                          "attempts": [], "events": []}
    top = BOX.y + 106
    for index, view in enumerate(("Now", "Learned", "Attempts")):
        ui.button("notes_view:" + view, view, pygame.Rect(BOX.x + 18 + index * 96, top, 88, 28),
                  TEXT if view == panel.notes_view else MUTED)
    ui.button("notes_refresh", "Refresh", pygame.Rect(BOX.right - 180, top, 76, 28))
    ui.text("Search: " + (panel.query or "Type to filter"), (BOX.x + 18, top + 47),
            ui.body, MUTED, max_width=BOX.width - 36)
    lines = []
    for entry in text_lines(data, panel.notes_view, panel.query):
        lines.extend(ui.wrap(entry, ui.body, BOX.width - 36))
        lines.append("")
    _paged_lines(ui, panel, lines, top + 92, BOX.bottom - 58)
    ui.button("notes_export", "Export", pygame.Rect(BOX.right - 98, BOX.bottom - 50, 80, 28))


def _paged_lines(ui, panel, lines, top, bottom):
    capacity = max(1, (bottom - top) // 22)
    panel.page = min(panel.page, max(0, (len(lines) - 1) // capacity))
    visible = lines[panel.page * capacity:(panel.page + 1) * capacity]
    for index, line in enumerate(visible):
        ui.text(line, (BOX.x + 18, top + index * 22), ui.small, TEXT,
                max_width=BOX.width - 36)
    if panel.page:
        ui.button("notes_previous", "Previous", pygame.Rect(BOX.x + 18, BOX.bottom - 50, 84, 28))
    if (panel.page + 1) * capacity < len(lines):
        ui.button("notes_next", "Next", pygame.Rect(BOX.x + 114, BOX.bottom - 50, 68, 28))
