"""Compact ownership, decision, usage, and controller visualization."""

import pygame

from .live_activity import collapse_repeated
from .live_ui_colors import ACCENT, BG, GOOD, MUTED, PANEL, SURFACE, TEXT, WARN


class LiveAgentPanel:
    def __init__(self, ui, box):
        self.ui = ui
        self.box = box
        self.feed_bounds = pygame.Rect(box.x + 14, box.y + 118,
                                       box.width - 28, box.height - 308)

    def draw(self, thoughts, animation, progress):
        ui, box = self.ui, self.box
        pygame.draw.rect(ui.canvas, PANEL, box, border_radius=6)
        self._header(progress)
        if ui.show_feed:
            key = progress.get("tactical_provider", "jev")
            entries = [entry for entry in (thoughts.get(key) or thoughts.get("jev") or [])
                       if entry != "Snapshot saved."]
            ui._entries(collapse_repeated(entries), self.feed_bounds.top,
                        self.feed_bounds.bottom)
        else:
            self._decision(progress)
        self._controller(progress)
        ui.jev_sprites.draw(
            ui.canvas, getattr(animation.state, "value", "idle"), animation.frame(),
            pygame.Rect(box.right - 104, box.bottom - 124, 88, 108),
        )

    def _header(self, progress):
        ui, box = self.ui, self.box
        label = "Decisions" if ui.show_feed else "Feed"
        ui.button("toggle_feed", label, pygame.Rect(box.right - 76, box.y + 12, 62, 22), MUTED)
        strategy = progress.get("strategy") or {}
        activity = (progress.get('agent_state') or {}).get('activity') or {}
        if activity.get('kind') == 'thinking':
            ui.text(f"{activity.get('provider', 'Model')} thinking…",
                    (box.x + 14, box.y + 15), ui.tiny, ACCENT,
                    max_width=box.width - 104)
        else:
            mode = progress.get("control_mode", "human")
            agent = progress.get("tactical_label", "Laya")
            agent_status = {"ai": "playing", "paused": "paused", "human": "manual"}[mode]
            planner = strategy.get("planner", "Luna")
            planner_status = strategy.get("status", "on") if strategy.get("enabled") else "off"
            ui.text(f"{agent} {agent_status} · {planner} {planner_status}",
                    (box.x + 14, box.y + 15), ui.tiny,
                    WARN if mode == "paused" else ACCENT,
                    max_width=box.width - 104)
        if activity and activity.get('kind') != 'thinking':
            ui.text(activity.get('phase', ''), (box.x + 14, box.y + 82),
                    ui.tiny, MUTED, max_width=box.width - 28)
        self._usage(progress.get("model_usage"), progress.get("tactical_provider", "jev"),
                    box.y + 43, strategy.get("planner", "Luna"))

    def _usage(self, usage, tactical_provider, top, planner="Luna"):
        ui, box = self.ui, self.box
        rendered = 0
        for provider in (tactical_provider, "luna"):
            stats = (usage or {}).get(provider) or {}
            calls = int(stats.get("calls") or 0)
            if calls <= 0:
                continue
            tokens = int(stats.get("total_tokens") or
                         (stats.get("input_tokens") or 0) + (stats.get("output_tokens") or 0))
            label = f"{planner if provider == 'luna' else provider.title()} · {calls} call{'s' if calls != 1 else ''}"
            if tokens:
                label += f" · {tokens:,} tokens"
            latency = float(stats.get("latency_ms") or 0)
            if latency:
                label += f" · {latency / calls:.0f} ms"
            ui.text(label, (box.x + 14, top + rendered * 18), ui.tiny,
                    GOOD if provider == tactical_provider else TEXT,
                    max_width=box.width - 28)
            rendered += 1

    def _decision(self, progress):
        ui, box = self.ui, self.box
        state = progress.get("agent_state") or {}
        decision = state.get("decision") or {}
        activity = state.get('activity') or {}
        thinking = activity.get('kind') == 'thinking'
        if thinking:
            decision = {'why': activity.get('goal'),
                        'action': ' / '.join(activity.get('options') or [activity.get('phase', '')]),
                        'result': f"{activity.get('provider', 'Model')} thinking · {activity.get('elapsed_seconds', 0):.1f}s"}
        top = box.y + 104
        for label, key, color, font in (
            ("Why", "why", MUTED, ui.small),
            ("Action", "action", GOOD, ui.body_bold),
            ("Result", "result", TEXT, ui.small),
        ):
            if thinking:
                label = {'Why': 'Considering', 'Action': 'Options', 'Result': 'Thinking'}.get(label, label)
            ui.text(label, (box.x + 14, top), ui.tiny, MUTED)
            value = decision.get(key) or ("Waiting for result" if key == "result" else "—")
            lines = ui.wrap(value, font, box.width - 28)[:2]
            for index, line in enumerate(lines):
                ui.text(line, (box.x + 14, top + 18 + index * 20), font, color,
                        max_width=box.width - 28)
            top += 64
        recent = [item for item in state.get("decisions", ())[1:]
                  if item.get("sequence") != decision.get("sequence")][:4]
        strategy = progress.get("strategy") or {}
        plan = strategy.get("plan") or strategy.get("last_response") or {}
        if strategy.get("enabled"):
            ui.text(f"{strategy.get('planner', 'Luna')} -> Laya" + (" (last reply)" if not strategy.get('plan') and plan else ""), (box.x + 14, top + 4), ui.tiny, ACCENT)
            summary = plan.get("explanation") or strategy.get("error") or strategy.get("status", "Awaiting plan")
            reply_lines = ui.wrap(summary, ui.small, box.width - 28)
            for index, line in enumerate(reply_lines):
                ui.text(line, (box.x + 14, top + 24 + index * 20), ui.small, TEXT)
            top += 30 + len(reply_lines) * 20
            recent = recent[:2]
        vision = state.get("vision") or {}
        frame = vision.get("frame")
        if frame is not None:
            surface = pygame.surfarray.make_surface(frame[:, :, :3].swapaxes(0, 1))
            ui.canvas.blit(pygame.transform.scale(surface, (64, 58)), (box.x + 14, top))
            ui.button("agent_open:Vision", "Vision " + vision.get("status", ""),
                      pygame.Rect(box.x + 84, top + 12, box.width - 98, 28), MUTED)
            top += 66
            recent = []
        if recent:
            ui.text("Recent", (box.x + 14, top + 4), ui.tiny, MUTED)
            top += 25
            for item in recent:
                value = item.get("action", "Decision")
                result = item.get("result")
                if result and result != "Waiting for result":
                    value += f" · {result}"
                ui.text(value, (box.x + 14, top), ui.small, MUTED,
                        max_width=box.width - 28)
                top += 24

    def _controller(self, progress):
        ui, box = self.ui, self.box
        active = progress.get("active_input")
        source = progress.get("input_source")
        highlight = GOOD if source == "ai" else ACCENT
        base_x, base_y = box.x + 26, box.bottom - 169
        size = 30
        directions = {
            "up": (base_x + size, base_y),
            "left": (base_x, base_y + size),
            "down": (base_x + size, base_y + size),
            "right": (base_x + size * 2, base_y + size),
        }
        for name, (x, y) in directions.items():
            rect = pygame.Rect(x, y, size - 2, size - 2)
            pygame.draw.rect(ui.canvas, highlight if active == name else SURFACE,
                             rect, border_radius=4)
            ui.text({"up": "^", "down": "v", "left": "<", "right": ">"}[name],
                    rect.center, ui.small_bold, BG if active == name else TEXT, center=True)
        for name, label, x, y in (
            ("b", "B", base_x + 112, base_y + 33),
            ("a", "A", base_x + 148, base_y + 18),
            ("select", "Select", base_x + 101, base_y + 72),
            ("start", "Start", base_x + 151, base_y + 72),
        ):
            width = 28 if len(label) == 1 else 44
            rect = pygame.Rect(x, y, width, 25)
            pygame.draw.rect(ui.canvas, highlight if active == name else SURFACE,
                             rect, border_radius=12)
            ui.text(label, rect.center, ui.tiny, BG if active == name else TEXT, center=True)
        self._mode(progress)

    def _mode(self, progress):
        ui, box = self.ui, self.box
        mode = progress.get("control_mode", "human")
        agent = progress.get("tactical_label", "Laya")
        labels = {"ai": f"{agent} playing", "paused": f"{agent} paused",
                  "human": "Human playing"}
        colors = {"ai": GOOD, "paused": WARN, "human": MUTED}
        rect = pygame.Rect(box.x + 14, box.bottom - 50, 176, 38)
        pygame.draw.rect(ui.canvas, colors[mode], rect, border_radius=6)
        ui.text(labels[mode], (rect.centerx, rect.y + 11), ui.small_bold, BG, center=True)
        ui.text("Ctrl-L", (rect.centerx, rect.y + 28), ui.tiny, BG, center=True)
        if progress.get("tactical_available", progress.get("jev_available")):
            ui.actions["retry_agent" if mode == "paused" else "toggle_jev"] = rect
