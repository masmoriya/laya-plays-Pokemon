"""Compact game-state panels; renderer owns fonts, colors and hit targets."""

import pygame

from .live_ui_colors import ACCENT, BG, GOOD, MUTED, PANEL, SURFACE, TEXT, WARN
from .live_battle_panel import LiveBattlePanel
from .live_map import LiveMap


class LivePanels:
    def __init__(self, ui):
        self.ui = ui
        self.map_panel = LiveMap(ui)
        self.battle_panel = LiveBattlePanel(ui)

    def _panel(self, box, title):
        pygame.draw.rect(self.ui.canvas, PANEL, box, border_radius=6)
        self.ui.text(title, (box.x + 14, box.y + 12), self.ui.small, MUTED)

    def party(self, party):
        box = pygame.Rect(342, 766, 640, 238)
        self._panel(box, "Party")
        if not party:
            self.ui.text("No Pokémon yet", (box.x + 18, box.y + 65), color=MUTED)
            return
        for index in range(6):
            row, column = divmod(index, 2)
            cell = pygame.Rect(box.x + 12 + column * 313, box.y + 34 + row * 64, 303, 58)
            mon = party[index] if index < len(party) else None
            if mon:
                self._mon(cell, mon)

    def _mon(self, box, mon):
        pygame.draw.rect(self.ui.canvas, SURFACE, box, border_radius=5)
        species = str(mon.get("species") or "Unknown").replace("_", " ")
        sprite = self.ui.pokemon_sprites.frame(species) if self.ui.pokemon_sprites else None
        icon = pygame.Rect(box.x + 5, box.y + 3, 52, 52)
        if sprite is not None:
            scaled = pygame.transform.scale(sprite, (48, 48))
            self.ui.canvas.blit(scaled, scaled.get_rect(center=icon.center))
        else:
            # An honest silhouette is preferable to a misleading initials avatar.
            pygame.draw.circle(self.ui.canvas, MUTED, (icon.centerx, icon.centery - 8), 10)
            pygame.draw.ellipse(self.ui.canvas, MUTED, (icon.x + 10, icon.y + 27, 32, 17))
        self.ui.text(species.title(), (box.x + 60, box.y + 6), self.ui.small, TEXT, max_width=174)
        self.ui.text(f"Lv {mon.get('level', 0)}", (box.right - 56, box.y + 6), self.ui.small, ACCENT)
        hp, maximum = int(mon.get("hp") or 0), int(mon.get("max_hp") or 0)
        ratio = max(0, min(1, hp / maximum)) if maximum else 0
        track = pygame.Rect(box.x + 60, box.y + 32, 158, 7)
        pygame.draw.rect(self.ui.canvas, BG, track, border_radius=3)
        pygame.draw.rect(self.ui.canvas, GOOD if ratio > 0.5 else WARN,
                         (track.x, track.y, round(track.width * ratio), track.height), border_radius=3)
        held = mon.get("held_item")
        if held:
            self.ui.text(f"◆ {held}", (box.x + 60, box.y + 43), self.ui.tiny, MUTED, max_width=226)

    def map(self, state, journey):
        self.map_panel.draw(state, journey)

    def stages(self, journey):
        box = pygame.Rect(994, 570, 434, 434)
        self._panel(box, "Journey")
        self.ui.button("agent_open:Steps", "Steps", pygame.Rect(box.right - 76, box.y + 8, 62, 22))
        stages = journey.route.display() if journey else {}
        row_y = box.y + 35
        for key in ("now", "next", "later"):
            item = stages.get(key)
            if item:
                current = key == "now"
                font = self.ui.small_bold if current else self.ui.small
                color = TEXT if current else MUTED
                self.ui.text(key.title(), (box.x + 14, row_y + 4), self.ui.tiny,
                             ACCENT if current else MUTED)
                lines = self.ui.wrap(f"{item[0]}. {item[1]}", font, box.width - 80)
                for index, line in enumerate(lines):
                    self.ui.text(line, (box.x + 65, row_y + index * font.get_linesize()), font, color)
                row_y += max(42, len(lines) * font.get_linesize() + 8)
        from .live_strategy import draw_strategy
        draw_strategy(self.ui, box, row_y + 4)
        optional = stages.get("optional")
        self.ui.selected_optional = optional[0] if optional else None
        if optional:
            self.ui.text(f"Side · {optional[2]}", (box.x + 14, box.bottom - 76),
                         self.ui.small, MUTED, max_width=box.width - 88)
            self.ui.button("toggle_optional", "Done", pygame.Rect(box.right - 70, box.bottom - 80, 56, 24), MUTED)
        self.ui.button("confirm_stage", "Confirm", pygame.Rect(box.right - 156, box.bottom - 32, 78, 24), GOOD)
        self.ui.button("undo_stage", "Undo", pygame.Rect(box.right - 70, box.bottom - 32, 56, 24), MUTED)

    def progress(self, progress, tracker):
        box = pygame.Rect(994, 838, 422, 166)
        self._panel(box, "Progress")
        self.ui.text(f"Battles {progress.get('battles', 0)}  ·  Wins {progress.get('wins', 0)}  ·  Losses {progress.get('losses', 0)}",
                     (box.x + 14, box.y + 43), self.ui.small, TEXT)
        self.ui.text(f"Pokédex  Seen {progress.get('pokedex_seen', 0)}  ·  Caught {progress.get('pokedex_caught', 0)}",
                     (box.x + 14, box.y + 72), self.ui.small, TEXT)
        self.ui.text(f"Badges {progress.get('badge_count', 0)}/{progress.get('badge_total', 8)}",
                     (box.x + 14, box.y + 101), self.ui.small, MUTED)
        if tracker and getattr(tracker, "last_result", None):
            self.ui.text(f"Last · {tracker.last_result} vs {tracker.last_opponent}",
                         (box.x + 14, box.bottom - 27), self.ui.small, MUTED,
                         max_width=box.width - 28)

    def battle_view(self, state, journey):
        self.battle_panel.draw(state, journey)
