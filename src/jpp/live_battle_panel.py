"""Balanced battle cards for the active trainer and Pokémon matchup."""

import pygame

from .live_ui_colors import ACCENT, BG, GOOD, MUTED, PANEL, SURFACE, TEXT, WARN


class LiveBattlePanel:
    CARD_HEIGHT = 338

    def __init__(self, ui):
        self.ui = ui

    def draw(self, state, journey):
        battle = getattr(state, "battle", None)
        opponent = getattr(battle, "opponent", None)
        own = getattr(battle, "active", None)
        if own is None:
            party = getattr(state, "party", ()) or ()
            slot = getattr(state, "active_slot", 0)
            # ``active_slot`` is intentionally ``None`` whenever the adapter has
            # not confirmed an active battle mon (for example during the brief
            # transition into/out of battle).  The panel is still rendered in
            # that window, so validate the optional slot before comparing it.
            if isinstance(slot, int) and 0 <= slot < len(party):
                own = party[slot]
        label = getattr(state, "opponent_label", None)
        trainer_class = getattr(state, "opponent_trainer_class", None)
        self._combatant(pygame.Rect(994, 176, 422, self.CARD_HEIGHT), opponent,
                        side="opponent", trainer_label=label,
                        trainer_class=trainer_class)
        self._combatant(pygame.Rect(994, 524, 422, self.CARD_HEIGHT), own,
                        side="player")
        self._journey(journey)

    def _combatant(self, box, mon, *, side, trainer_label=None, trainer_class=None):
        pygame.draw.rect(self.ui.canvas, PANEL, box, border_radius=6)
        heading = "Opponent" if side == "opponent" else "Your Pokémon"
        self.ui.text(heading, (box.x + 14, box.y + 11), self.ui.small, MUTED)
        if mon is None:
            message = ("Preparing their first Pokémon…" if side == "opponent" and trainer_label
                       else "Battle data unavailable")
            self._identity_art(box, None, trainer_label, trainer_class)
            self.ui.text(message, (box.x + 210, box.y + 68), self.ui.small, MUTED,
                         max_width=194)
            return

        self._identity_art(box, mon, trainer_label, trainer_class)
        identity = trainer_label if side == "opponent" and trainer_label else heading
        self.ui.text(identity, (box.x + 210, box.y + 39), self.ui.small_bold, TEXT,
                     max_width=196)
        self.ui.text(f"{mon.species}  ·  Lv {mon.level}", (box.x + 210, box.y + 61),
                     self.ui.body_bold, TEXT, max_width=196)
        self._health(box, mon)
        self._stats(box, getattr(mon, "species_data", None))
        self._moves(box, getattr(mon, "moves", ()), getattr(mon, "pp", ()))
        self._pokedex_note(box, getattr(mon, "species_data", None))

    def _identity_art(self, box, mon, trainer_label, trainer_class):
        provider = self.ui.pokemon_sprites
        art = pygame.Rect(box.x + 14, box.y + 39, 182, 108)
        pygame.draw.rect(self.ui.canvas, SURFACE, art, border_radius=5)
        sprites = []
        if trainer_label:
            trainer = (provider.trainer_frame(trainer_class)
                       if provider and hasattr(provider, "trainer_frame") else None)
            sprites.append(trainer)
        if mon is not None:
            sprites.append(provider.frame(mon.species) if provider else None)
        visible = [sprite for sprite in sprites if sprite is not None]
        if not visible:
            pygame.draw.circle(self.ui.canvas, MUTED, art.center, 24)
            return
        side = 96
        centers = ([art.centerx] if len(visible) == 1
                   else [art.x + 48, art.right - 48])
        for sprite, center_x in zip(visible, centers):
            scaled = pygame.transform.scale(sprite, (side, side))
            self.ui.canvas.blit(scaled, scaled.get_rect(center=(center_x, art.centery)))

    def _health(self, box, mon):
        hp, maximum = getattr(mon, "hp", None), getattr(mon, "max_hp", None)
        types = " / ".join(getattr(mon, "types", ()) or ()) or "Type unavailable"
        hp_label = f"HP {hp}/{maximum}" if hp is not None and maximum is not None else "HP unavailable"
        self.ui.text(f"{hp_label}  ·  {types}", (box.x + 210, box.y + 87),
                     self.ui.tiny, MUTED, max_width=196)
        ratio = max(0, min(1, hp / maximum)) if isinstance(hp, int) and maximum else 0
        track = pygame.Rect(box.x + 210, box.y + 107, 196, 7)
        pygame.draw.rect(self.ui.canvas, BG, track, border_radius=3)
        pygame.draw.rect(self.ui.canvas, GOOD if ratio > .5 else WARN,
                         (track.x, track.y, round(track.width * ratio), track.height),
                         border_radius=3)

    def _stats(self, box, facts):
        self.ui.text("Stats", (box.x + 210, box.y + 132), self.ui.small, MUTED)
        values = getattr(facts, "base_stats", ()) if facts else ()
        labels = ("HP", "Atk", "Def", "Spd", "SpA", "SpD")
        for index, label in enumerate(labels):
            column, row = index % 3, index // 3
            cell = pygame.Rect(box.x + 210 + column * 66, box.y + 153 + row * 27, 60, 22)
            pygame.draw.rect(self.ui.canvas, SURFACE, cell, border_radius=4)
            value = values[index] if index < len(values) else "—"
            self.ui.text(f"{label} {value}", cell.center, self.ui.tiny, TEXT, center=True)

    def _moves(self, box, moves, pp_values):
        self.ui.text("Moves", (box.x + 14, box.y + 216), self.ui.small, MUTED)
        for index in range(4):
            column, row = index % 2, index // 2
            cell = pygame.Rect(box.x + 14 + column * 199, box.y + 236 + row * 28, 193, 23)
            pygame.draw.rect(self.ui.canvas, SURFACE, cell, border_radius=4)
            if index >= len(moves):
                continue
            move = str(moves[index]).replace("_", " ").title()
            pp = pp_values[index] if index < len(pp_values) else "?"
            self.ui.text(move, (cell.x + 7, cell.y + 4), self.ui.tiny, TEXT, max_width=130)
            pp_label = f"{pp} PP"
            self.ui.text(pp_label, (cell.right - self.ui.tiny.size(pp_label)[0] - 7, cell.y + 4),
                         self.ui.tiny, MUTED)

    def _pokedex_note(self, box, facts):
        pygame.draw.line(self.ui.canvas, SURFACE,
                         (box.x + 14, box.y + 296), (box.right - 14, box.y + 296))
        category = str(getattr(facts, "category", "") or "Entry unavailable").title()
        entry = getattr(facts, "entry", None)
        note = f"Pokédex · {category}"
        self.ui.text(note, (box.x + 14, box.y + 301), self.ui.small, ACCENT,
                     max_width=box.width - 28)
        if entry:
            lines = self.ui.wrap(entry, self.ui.tiny, box.width - 28)
            for index, line in enumerate(lines[:2]):
                self.ui.text(line, (box.x + 14, box.y + 316 + index * 12),
                             self.ui.tiny, TEXT)

    def _journey(self, journey):
        box = pygame.Rect(994, 872, 422, 132)
        pygame.draw.rect(self.ui.canvas, PANEL, box, border_radius=6)
        self.ui.text("Journey", (box.x + 14, box.y + 10), self.ui.small, MUTED)
        item = (journey.route.display() if journey else {}).get("now")
        if item:
            label = f"{item[0]}. {item[1]}"
            self.ui.text(label, (box.x + 14, box.y + 36), self.ui.small_bold, TEXT,
                         max_width=238)
        else:
            self.ui.text("Current step unavailable", (box.x + 14, box.y + 39),
                         self.ui.small, MUTED)
        self.ui.button("confirm_stage", "Confirm", pygame.Rect(box.right - 156, box.bottom - 28, 78, 22), GOOD)
        self.ui.button("undo_stage", "Undo", pygame.Rect(box.right - 70, box.bottom - 28, 56, 22), MUTED)
