"""Compact game-state panels; renderer owns fonts, colors and hit targets."""

import pygame

from .live_ui_colors import ACCENT, BG, GOOD, MUTED, PANEL, SURFACE, TEXT, WARN
from .live_map import LiveMap


class LivePanels:
    def __init__(self, ui):
        self.ui = ui
        self.map_panel = LiveMap(ui)

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
        opponent = getattr(getattr(state, "battle", None), "opponent", None)
        own = getattr(getattr(state, "battle", None), "active", None)
        label = getattr(state, "opponent_label", None)
        trainer_class = getattr(state, "opponent_trainer_class", None)
        if own is None and label and label != "Wild":
            self._trainer_intro(label, trainer_class)
        else:
            self._opponent_entry(opponent, label, trainer_class)
        self._active_battle_mon(own)
        self._current_stage(journey)

    def _trainer_intro(self, label, trainer_class):
        box = pygame.Rect(994, 176, 422, 382)
        self._panel(box, "Trainer battle")
        self._trainer_sprite(trainer_class, pygame.Rect(box.x + 14, box.y + 48, 108, 108))
        self.ui.text(label, (box.x + 134, box.y + 52), self.ui.body_bold, TEXT, max_width=272)
        self.ui.text("Preparing their first Pokémon…", (box.x + 134, box.y + 80), self.ui.small, MUTED,
                     max_width=272)

    def _trainer_sprite(self, trainer_class, target):
        provider = self.ui.pokemon_sprites
        sprite = provider.trainer_frame(trainer_class) if provider and hasattr(provider, "trainer_frame") else None
        if sprite is not None:
            scaled = pygame.transform.scale(sprite, target.size)
            self.ui.canvas.blit(scaled, target)
        return sprite is not None

    def _opponent_entry(self, mon, label, trainer_class=None):
        box = pygame.Rect(994, 176, 422, 382)
        self._panel(box, "Pokédex")
        if mon is None:
            self.ui.text("Opponent data unavailable", (box.x + 14, box.y + 54), self.ui.small, MUTED)
            return
        sprite = self.ui.pokemon_sprites.frame(mon.species) if self.ui.pokemon_sprites else None
        has_trainer = trainer_class is not None
        icon = pygame.Rect(box.x + 14, box.y + 42, 98 if has_trainer else 116,
                           98 if has_trainer else 116)
        if sprite is not None:
            side = 94 if has_trainer else 108
            scaled = pygame.transform.scale(sprite, (side, side))
            self.ui.canvas.blit(scaled, scaled.get_rect(center=icon.center))
        if has_trainer:
            self._trainer_sprite(trainer_class, pygame.Rect(box.x + 112, box.y + 46, 88, 88))
            text_x, text_width = box.x + 210, 196
            self.ui.text(label or "Trainer", (text_x, box.y + 43), self.ui.small_bold, TEXT,
                         max_width=text_width)
            self.ui.text(mon.species, (text_x, box.y + 67), self.ui.body_bold, TEXT,
                         max_width=text_width)
        else:
            text_x, text_width = box.x + 140, 264
            self.ui.text(f"{label + ' · ' if label else ''}{mon.species}",
                         (text_x, box.y + 43), self.ui.body_bold, TEXT, max_width=text_width)
        hp, max_hp = getattr(mon, "hp", "?"), getattr(mon, "max_hp", "?")
        self.ui.text(f"Lv {mon.level}  ·  HP {hp}/{max_hp}",
                     (text_x, box.y + (91 if has_trainer else 68)), self.ui.small, TEXT,
                     max_width=text_width)
        status = getattr(mon, "status", "unknown")
        types = getattr(mon, "types", ())
        self.ui.text(f"Status · {str(status).title()}  ·  {', '.join(types) or 'Unavailable'}",
                     (text_x, box.y + (113 if has_trainer else 91)), self.ui.tiny, MUTED,
                     max_width=text_width)
        facts = getattr(mon, "species_data", None)
        if facts and facts.base_stats:
            labels = ("HP", "Atk", "Def", "Spd", "SpA", "SpD")
            values = "  ".join(f"{name} {value}" for name, value in zip(labels, facts.base_stats))
            self.ui.text("Species stats", (box.x + 14, box.y + 172), self.ui.tiny, MUTED)
            self.ui.text(values, (box.x + 14, box.y + 190), self.ui.tiny, TEXT, max_width=394)
        else:
            self.ui.text("Species stats · Unavailable", (box.x + 14, box.y + 180), self.ui.tiny, MUTED)
        if facts and facts.entry:
            measurement = f"{facts.category} · {facts.height // 100}'{facts.height % 100:02}\" · {facts.weight / 10:.1f} lb"
            self.ui.text(measurement, (box.x + 14, box.y + 218), self.ui.tiny, ACCENT, max_width=394)
            lines = self.ui.wrap(facts.entry, self.ui.small, 394)[:4]
            for index, line in enumerate(lines):
                self.ui.text(line, (box.x + 14, box.y + 240 + index * 19), self.ui.small, TEXT)
        else:
            self.ui.text("Pokédex entry · Unavailable", (box.x + 14, box.y + 222), self.ui.small, MUTED)
        self._moves(box, getattr(mon, "moves", ()), getattr(mon, "pp", ()), box.bottom - 50, self.ui.tiny)

    def _active_battle_mon(self, mon):
        box = pygame.Rect(994, 570, 422, 160)
        self._panel(box, "Your Pokémon")
        if mon is None:
            self.ui.text("Battle data unavailable", (box.x + 14, box.y + 47), self.ui.small, MUTED)
            return
        self.ui.text(f"{mon.species} · Lv {mon.level}", (box.x + 14, box.y + 39), self.ui.body_bold, TEXT)
        hp, max_hp = getattr(mon, "hp", "?"), getattr(mon, "max_hp", "?")
        self.ui.text(f"HP {hp}/{max_hp}  ·  {', '.join(getattr(mon, 'types', ())) or 'Unavailable'}",
                     (box.x + 14, box.y + 65), self.ui.small, MUTED)
        facts = getattr(mon, "species_data", None)
        if facts and facts.base_stats:
            labels = ("HP", "Atk", "Def", "Spd", "SpA", "SpD")
            values = "  ".join(f"{name} {value}" for name, value in zip(labels, facts.base_stats))
            self.ui.text("Species stats", (box.x + 14, box.y + 84), self.ui.tiny, MUTED)
            self.ui.text(values, (box.x + 14, box.y + 99), self.ui.tiny, TEXT, max_width=394)
            moves_top = box.y + 115
        else:
            moves_top = box.y + 98
        self._moves(box, mon.moves, mon.pp, moves_top, self.ui.small)

    def _moves(self, box, moves, pp_values, top, font):
        for index, move in enumerate(moves[:4]):
            column = pygame.Rect(box.x + 14 + index % 2 * 195, top + index // 2 * 24, 176, 20)
            pp = pp_values[index] if index < len(pp_values) else "?"
            self.ui.text(move.title(), column.topleft, font, TEXT, max_width=124)
            pp_label = f"{pp} PP"
            self.ui.text(pp_label, (column.right - font.size(pp_label)[0], column.y), font, TEXT)

    def _current_stage(self, journey):
        box = pygame.Rect(994, 742, 422, 78)
        self._panel(box, "Journey")
        item = (journey.route.display() if journey else {}).get("now")
        if not item:
            self.ui.text("Current step unavailable", (box.x + 14, box.y + 41), self.ui.small, MUTED)
            return
        for index, line in enumerate(self.ui.wrap(f"{item[0]}. {item[1]}", self.ui.small_bold, box.width - 28)[:2]):
            self.ui.text(line, (box.x + 14, box.y + 34 + index * self.ui.small_bold.get_linesize()), self.ui.small_bold, TEXT)
        self.ui.button("confirm_stage", "Confirm", pygame.Rect(box.right - 156, box.bottom - 28, 78, 22), GOOD)
        self.ui.button("undo_stage", "Undo", pygame.Rect(box.right - 70, box.bottom - 28, 56, 22), MUTED)
