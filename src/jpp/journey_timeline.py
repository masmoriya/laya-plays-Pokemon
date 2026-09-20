"""A small set of confirmed story milestones above the playable dashboard."""

from dataclasses import dataclass

import pygame

from .live_ui_colors import ACCENT, GOOD, MUTED, PANEL, SURFACE, TEXT


@dataclass(frozen=True)
class Milestone:
    step: int
    label: str
    portrait: str | None = None
    badge: int | None = None


MILESTONES = (
    Milestone(1, "Silent Town"), Milestone(5, "Falkner", "Falkner", 0),
    Milestone(10, "Bugsy", "Bugsy", 1), Milestone(15, "Whitney", "Whitney", 2),
    Milestone(21, "Morty", "Morty", 3), Milestone(29, "Rocket ship"),
    Milestone(32, "Jasmine", "Jasmine", 4), Milestone(39, "Pryce", "Pryce", 5),
    Milestone(44, "Okera", "Okera", 6), Milestone(51, "Rocket machine"),
    Milestone(57, "Giovanni", "Giovanni"), Milestone(66, "Red", "Red", 7),
    Milestone(70, "Ho-Oh"), Milestone(76, "League"),
    Milestone(77, "Lorelei", "Lorelei"), Milestone(78, "Koga", "Koga"),
    Milestone(79, "Agatha", "Agatha"), Milestone(80, "Giovanni", "Giovanni"),
    Milestone(81, "Lance", "Lance"), Milestone(82, "Hall of Fame"),
    Milestone(94, "Amami"), Milestone(103, "Aqua repaired"),
    Milestone(110, "Lugia"), Milestone(126, "Blue", "Blue"),
    Milestone(127, "Credits"),
)
VISIBLE = 11


def timeline_start(completed, page=None):
    current = next((i for i, item in enumerate(MILESTONES) if item.step not in completed),
                   len(MILESTONES) - 1)
    return min(max(0, current - 3) if page is None else max(0, page), len(MILESTONES) - VISIBLE)


def player_stage(completed):
    """Return the latest completed route stage used for the player marker."""
    return max((step for step in completed if step <= MILESTONES[-1].step),
               default=MILESTONES[0].step)


class JourneyTimeline:
    def __init__(self, ui, art):
        self.ui = ui
        self.art = art
        self.page = None
        self.last_current = None
        self.player = None

    def draw(self, journey, progress):
        ui = self.ui
        box = pygame.Rect(24, 12, 1392, 148)
        pygame.draw.rect(ui.canvas, PANEL, box, border_radius=6)
        completed = journey.route.completed if journey else set()
        current = next((item.step for item in MILESTONES if item.step not in completed), None)
        if current != self.last_current:
            self.page = None
            self.last_current = current
        start = timeline_start(completed, self.page)
        ui.text("Journey", (box.x + 14, box.y + 10), ui.small_bold, TEXT)
        ui.text(
            f"{len(completed)}/127 stages   ·   {progress.get('badge_count', 0)}/8 badges"
            f"   ·   {progress.get('battles', 0)} battles   ·   {progress.get('wins', 0)} wins"
            f"   ·   {progress.get('losses', 0)} losses"
            f"   ·   Pokémon {progress.get('pokedex_caught', 0)} caught"
            f"   ·   {progress.get('pokedex_seen', 0)} seen",
            (box.x + 110, box.y + 11), ui.small, MUTED)
        if start:
            ui.button("timeline_prev", "‹", pygame.Rect(box.x + 8, box.y + 58, 24, 28))
        if start + VISIBLE < len(MILESTONES):
            ui.button("timeline_next", "›", pygame.Rect(box.right - 32, box.y + 58, 24, 28))
        left, width = box.x + 49, (box.width - 98) / (VISIBLE - 1)
        y = box.y + 91
        pygame.draw.line(ui.canvas, SURFACE, (left, y), (left + width * (VISIBLE - 1), y), 3)
        visible = MILESTONES[start:start + VISIBLE]
        for index, item in enumerate(visible):
            x = round(left + width * index)
            earned = item.step in completed
            active = item.step == current
            if index and earned:
                pygame.draw.line(ui.canvas, GOOD, (round(x - width), y), (x, y), 3)
            portrait = self.art.portrait(item.portrait) if item.portrait else None
            if portrait:
                face = pygame.transform.scale(portrait, (40, 40))
                face.set_alpha(255 if earned or active else 120)
                ui.canvas.blit(face, face.get_rect(center=(x, y - 32)))
            elif item.badge is not None:
                self._icon(self.art.badge(item.badge), (x, y - 32), 28)
            if item.badge is not None and portrait:
                self._icon(self.art.badge(item.badge), (x + 22, y - 15), 18)
            pygame.draw.circle(ui.canvas, GOOD if earned else ACCENT if active else MUTED,
                               (x, y), 5 if active else 4)
            ui.text(item.label, (x, y + 11), ui.tiny, TEXT if earned or active else MUTED,
                    center=True, max_width=round(width - 8))
        marker_stage = player_stage(completed) if journey else None
        if (self.player and marker_stage is not None
                and visible[0].step <= marker_stage <= visible[-1].step):
            previous = max((i for i, item in enumerate(visible)
                            if item.step <= marker_stage), default=0)
            following = min(previous + 1, len(visible) - 1)
            before, after = visible[previous].step, visible[following].step
            fraction = ((marker_stage - before) / (after - before)
                        if after > before else 0)
            x = round(left + width * (previous + fraction))
            sprite = pygame.transform.scale(self.player, (32, 32))
            ui.canvas.blit(sprite, sprite.get_rect(midbottom=(x, y - 4)))

    def _icon(self, image, center, size):
        if image:
            scaled = pygame.transform.scale(image, (size, size))
            self.ui.canvas.blit(scaled, scaled.get_rect(center=center))
