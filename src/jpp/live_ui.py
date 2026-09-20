"""Readable, resizable local dashboard around the native Game Boy display."""

import pygame

from .character.sprites import JevSprites
from .journey_art import JourneyArt
from .journey_timeline import JourneyTimeline
from .live_panels import LivePanels
from .live_ui_colors import ACCENT, BG, GOOD, MUTED, PANEL, SURFACE, TEXT


SIZE = (1440, 1080)
LEFT = pygame.Rect(24, 176, 306, 828)
GAME_RECT = pygame.Rect(342, 176, 640, 576)
PARTY_RECT = pygame.Rect(342, 766, 640, 238)
RIGHT = pygame.Rect(994, 176, 422, 828)


def format_duration(seconds):
    total = max(0, int(seconds or 0))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{secs:02}" if hours else f"{minutes:02}:{secs:02}"


def starter_name(progress):
    party = progress.get("party") or ()
    species = party[0].get("species") if party else None
    return species if species and not str(species).startswith("MON_") else None


def format_tokens(value):
    value = int(value or 0)
    return f"{value:,}"


class LiveUI:
    def __init__(self, screen, pokemon_sprites=None):
        self.screen = screen
        self.canvas = pygame.Surface(SIZE)
        self.title = pygame.font.SysFont("Verdana,Inter,sans-serif", 24, bold=True)
        self.body = pygame.font.SysFont("Verdana,Inter,sans-serif", 16)
        self.body_bold = pygame.font.SysFont("Verdana,Inter,sans-serif", 16, bold=True)
        self.small = pygame.font.SysFont("Verdana,Inter,sans-serif", 13)
        self.small_bold = pygame.font.SysFont("Verdana,Inter,sans-serif", 14, bold=True)
        self.tiny = pygame.font.SysFont("Verdana,Inter,sans-serif", 11)
        self.jev_sprites = JevSprites()
        self.pokemon_sprites = pokemon_sprites
        self.timeline = JourneyTimeline(self, JourneyArt(getattr(pokemon_sprites, "rom", None)))
        self.player_marker = None
        self.panels = LivePanels(self)
        self.show_shortcuts = False
        self.audio_muted = False
        self.map_details = False
        self.map_entities = ()
        self.actions = {}
        self.selected_optional = None
        self._dest = pygame.Rect(0, 0, *SIZE)

    def draw(self, frame, progress, state, animation, thoughts, journey=None, battle=None):
        self.canvas.fill(BG)
        self.actions.clear()
        if self.player_marker:
            self.timeline.player = pygame.image.frombuffer(self.player_marker.rgba, (16, 16), "RGBA").copy()
        self.timeline.draw(journey, progress)
        self._game(frame)
        self._thoughts(thoughts, animation, progress)
        self.panels.party(progress.get("party") or ())
        if getattr(state, "in_battle", False):
            self.panels.battle_view(state, journey)
        else:
            self.panels.map(state, journey)
            self.panels.stages(journey)
        self._footer(progress, thoughts)
        if self.show_shortcuts:
            self._shortcuts()
        width, height = self.screen.get_size()
        scale = min(width / SIZE[0], height / SIZE[1])
        dest = pygame.Rect(0, 0, round(SIZE[0] * scale), round(SIZE[1] * scale))
        dest.center = (width // 2, height // 2)
        self._dest = dest
        self.screen.fill(BG)
        image = pygame.transform.scale(self.canvas, dest.size) if dest.size != SIZE else self.canvas
        self.screen.blit(image, dest)
        pygame.display.flip()

    def action_at(self, pos):
        if not self._dest.collidepoint(pos):
            return None
        x = (pos[0] - self._dest.x) * SIZE[0] / self._dest.width
        y = (pos[1] - self._dest.y) * SIZE[1] / self._dest.height
        return next((name for name, rect in self.actions.items() if rect.collidepoint(x, y)), None)

    def button(self, name, label, rect, color=TEXT):
        self.actions[name] = rect
        pygame.draw.rect(self.canvas, SURFACE, rect, border_radius=5)
        self.text(label, rect.center, self.small, color, center=True)

    def text(self, value, pos, font=None, color=TEXT, *, center=False, max_width=None):
        font = font or self.body
        value = str(value)
        if max_width is not None:
            while value and font.size(value)[0] > max_width:
                value = value[:-2].rstrip("…") + "…"
        image = font.render(value, True, color)
        rect = image.get_rect(center=pos) if center else image.get_rect(topleft=pos)
        self.canvas.blit(image, rect)

    def wrap(self, value, font, width):
        lines = []
        for paragraph in str(value).split("\n"):
            line = ""
            for word in paragraph.split():
                candidate = f"{line} {word}".strip()
                if font.size(candidate)[0] > width and line:
                    lines.append(line)
                    line = word
                else:
                    line = candidate
            lines.append(line)
        return lines

    def _game(self, frame):
        pygame.draw.rect(self.canvas, PANEL, GAME_RECT.inflate(12, 12), border_radius=6)
        if frame is None:
            self.text("Waiting for Game Boy…", GAME_RECT.center, color=MUTED, center=True)
            return
        image = pygame.surfarray.make_surface(frame.swapaxes(0, 1)[:, :, :3])
        self.canvas.blit(pygame.transform.scale(image, GAME_RECT.size), GAME_RECT)

    def _thoughts(self, thoughts, animation, progress):
        pygame.draw.rect(self.canvas, PANEL, LEFT, border_radius=6)
        self.text("Jev", (LEFT.x + 14, LEFT.y + 14), self.small, GOOD)
        self.text("Live" if progress.get("jev_connected") else "Not connected",
                  (LEFT.x + 75, LEFT.y + 14), self.small, GOOD if progress.get("jev_connected") else MUTED)
        self.text("Luna", (LEFT.x + 14, LEFT.y + 46), self.small, ACCENT)
        self.text("Live" if progress.get("luna_connected") else "Not connected",
                  (LEFT.x + 75, LEFT.y + 46), self.small,
                  GOOD if progress.get("luna_connected") else MUTED)
        self._usage(progress.get("model_usage"))
        self._entries(thoughts.get("luna"), LEFT.y + 194, LEFT.y + 290)
        # Snapshot confirmation belongs with the snapshot controls, not the Jev feed.
        jev_entries = [entry for entry in (thoughts.get("jev") or [])
                       if entry != "Snapshot saved."]
        self._entries(jev_entries, LEFT.y + 310, LEFT.bottom - 138)
        # Her avatar belongs to its own dock; it never steals commentary width.
        self.jev_sprites.draw(self.canvas, getattr(animation.state, "value", "idle"),
                              animation.frame(), pygame.Rect(LEFT.right - 104, LEFT.bottom - 124, 88, 108))

    def _usage(self, model_usage):
        self.text("Usage", (LEFT.x + 14, LEFT.y + 78), self.tiny, MUTED)
        for index, (name, color) in enumerate((("jev", GOOD), ("luna", ACCENT))):
            stats = (model_usage or {}).get(name) or {}
            top = LEFT.y + 96 + index * 48
            calls = stats.get("calls", 0)
            self.text(f"{name.title()} {calls} calls · "
                      f"{format_tokens(stats.get('input_tokens'))} in / "
                      f"{format_tokens(stats.get('output_tokens'))} out",
                      (LEFT.x + 14, top), self.tiny, color, max_width=LEFT.width - 28)
            total_rate = stats.get("tokens_per_second")
            input_rate = stats.get("input_tokens_per_second")
            output_rate = stats.get("output_tokens_per_second")
            rate = "—" if total_rate is None else f"{total_rate:g} tok/s"
            if input_rate is not None and output_rate is not None:
                rate += f" ({input_rate:g}/{output_rate:g})"
            actual = stats.get("actual_cost_usd")
            estimate = stats.get("estimated_cost_usd")
            if actual is not None:
                cost = f"${actual:.6f} actual"
            elif estimate is not None:
                cost = f"${estimate:.6f} est"
            else:
                cost = "cost —"
            self.text(f"      {rate} · {cost}", (LEFT.x + 14, top + 18),
                      self.tiny, MUTED, max_width=LEFT.width - 28)

    def _entries(self, entries, top, bottom):
        lines = []
        for entry in (entries or [])[-5:]:
            lines.extend(self.wrap(entry, self.body, LEFT.width - 28))
        for line in lines[-max(1, (bottom - top) // 23):]:
            self.text(line, (LEFT.x + 14, top), self.body, TEXT, max_width=LEFT.width - 28)
            top += 23

    def _footer(self, progress, thoughts=None):
        controls = (("shortcuts", "Keys", 24, 52),
                    ("snapshot", "Snapshot", 84, 90),
                    ("restore", "Restore", 182, 76),
                    ("restart", "Restart", 266, 76),
                    ("game_save", "Save help", 350, 84),
                    ("toggle_audio", "Unmute" if self.audio_muted else "Mute", 442, 72))
        if progress.get("jev_available"):
            controls += (("toggle_jev", "Pause Jev" if progress.get("jev_auto") else "Play Jev",
                          910, 94),)
        for action, label, x, width in controls:
            self.button(action, label, pygame.Rect(x, 1026, width, 30),
                        ACCENT if action == "snapshot" else TEXT)
        run = format_duration(progress.get("run_seconds", 0))
        stream = format_duration(progress.get("stream_seconds", 0))
        speed = progress.get("speed", 1)
        self.text(f"Run {run}   ·   Session {stream}   ·   {speed:g}×",
                  (558, 1032), self.small, MUTED)
        if "Snapshot saved." in ((thoughts or {}).get("jev") or []):
            self.text("Snapshot saved.", (1048, 1032), self.small, GOOD)
        self.text("Ctrl-S snapshot   Esc quit", (1204, 1032), self.small, MUTED)

    def _shortcuts(self):
        box = pygame.Rect(350, 794, 624, 194)
        pygame.draw.rect(self.canvas, BG, box, border_radius=6)
        lines = ("Keyboard", "Arrows move     Z A     X B     Enter Start     Shift Select",
                 "Ctrl-S snapshot     Ctrl-R restore     F1 close",
                 "V mute audio     C confirm stage     U undo stage     O side stop",
                 "- / + speed     0 reset speed     Esc quit")
        for index, line in enumerate(lines):
            self.text(line, (box.x + 18, box.y + 16 + index * 32),
                      self.body if index == 0 else self.small, ACCENT if index == 0 else TEXT)
