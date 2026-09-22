"""Readable, resizable local dashboard around the native Game Boy display."""

import pygame

from .character.sprites import JevSprites
from .journey_art import JourneyArt
from .journey_timeline import JourneyTimeline
from .live_panels import LivePanels
from .live_agent_panel import LiveAgentPanel
from .live_map_state import LiveMapState
from .live_strategy import controls as strategy_controls
from .live_notebook import NotebookPanel
from .live_ui_colors import ACCENT, BG, GOOD, MUTED, PANEL, SURFACE, TEXT


SIZE = (1440, 1080)
LEFT = pygame.Rect(24, 176, 306, 828)
GAME_RECT = pygame.Rect(342, 176, 640, 576)
PARTY_RECT = pygame.Rect(342, 766, 640, 238)
RIGHT = pygame.Rect(994, 176, 422, 828)


def _ui_font(size, *, bold=False):
    """Pick a real local UI font; Pygame does not parse CSS font stacks."""
    # Tahoma and Arial keep open counters and sturdy stems at the small sizes
    # used by the dashboard.  Keep the remaining entries as portable fallbacks.
    for family in ("Verdana", "Inter", "Tahoma", "Arial", "DejaVu Sans", "Liberation Sans"):
        path = pygame.font.match_font(family, bold=bold)
        if path:
            return pygame.font.Font(path, size)
    return pygame.font.Font(None, size)


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
        self.title = _ui_font(24, bold=True)
        self.body = _ui_font(16)
        self.body_bold = _ui_font(16, bold=True)
        self.small = _ui_font(13)
        self.small_bold = _ui_font(14, bold=True)
        self.tiny = _ui_font(11)
        self.jev_sprites = JevSprites()
        self.pokemon_sprites = pokemon_sprites
        self.timeline = JourneyTimeline(self, JourneyArt(getattr(pokemon_sprites, "rom", None)))
        self.player_marker = None
        self.panels = LivePanels(self)
        self.show_shortcuts = False
        self.audio_muted = False
        self.map_details = False
        self.strategy_details = False
        self.strategy_summary = None
        self.notebook = NotebookPanel()
        self.agent_panel = LiveAgentPanel(self, LEFT)
        self.map_mode = "grid"
        self.map_state = LiveMapState()
        self.map_entities = ()
        self.actions = {}
        self.selected_optional = None
        self.activity_scroll = 0
        self.show_feed = False
        self.activity_bounds = self.agent_panel.feed_bounds
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
        self.notebook.update(progress)
        self.notebook.draw(self)
        width, height = self.screen.get_size()
        scale = min(width / SIZE[0], height / SIZE[1])
        dest = pygame.Rect(0, 0, round(SIZE[0] * scale), round(SIZE[1] * scale))
        dest.center = (width // 2, height // 2)
        self._dest = dest
        self.screen.fill(BG)
        # Smooth scaling prevents nearest-neighbor reduction from dropping the
        # thin opening in glyphs such as G, V, and O at small window sizes.
        image = pygame.transform.smoothscale(self.canvas, dest.size) if dest.size != SIZE else self.canvas
        self.screen.blit(image, dest)
        pygame.display.flip()

    def action_at(self, pos):
        if not self._dest.collidepoint(pos):
            return None
        x = (pos[0] - self._dest.x) * SIZE[0] / self._dest.width
        y = (pos[1] - self._dest.y) * SIZE[1] / self._dest.height
        return next((name for name, rect in self.actions.items() if rect.collidepoint(x, y)), None)

    def scroll_activity(self, pos, steps):
        if not self._dest.collidepoint(pos):
            return
        x = (pos[0] - self._dest.x) * SIZE[0] / self._dest.width
        y = (pos[1] - self._dest.y) * SIZE[1] / self._dest.height
        if self.show_feed and self.activity_bounds.collidepoint(x, y):
            delta = steps * 3
            self.activity_scroll = max(0, self.activity_scroll + delta)

    def button(self, name, label, rect, color=TEXT):
        self.actions[name] = rect
        pygame.draw.rect(self.canvas, SURFACE, rect, border_radius=5)
        self.text(label, rect.center, self.small, color, center=True)

    def text(self, value, pos, font=None, color=TEXT, *, center=False, max_width=None):
        font = font or self.body
        value = str(value)
        if max_width is not None and font.size(value)[0] > max_width:
            suffix = "…"
            if font.size(suffix)[0] > max_width:
                value = ""
            else:
                # Shorten the source, not the ellipsis appended for display.
                # Binary search also bounds work for long provider messages.
                low, high = 0, len(value)
                while low < high:
                    middle = (low + high + 1) // 2
                    if font.size(value[:middle] + suffix)[0] <= max_width:
                        low = middle
                    else:
                        high = middle - 1
                value = value[:low] + suffix
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
        self.agent_panel.draw(thoughts, animation, progress)

    def _usage(self, model_usage, tactical_provider="jev", *, has_model_input=False):
        self.agent_panel._usage(model_usage, tactical_provider, LEFT.y + 43)

    def _entries(self, entries, top, bottom, *, from_top=False):
        lines = []
        for entry in entries or []:
            lines.extend(self.wrap(entry, self.body, LEFT.width - 28))
        line_height = max(23, self.body.get_linesize())
        capacity = max(1, (bottom - top) // line_height)
        max_scroll = max(0, len(lines) - capacity)
        self.activity_scroll = min(self.activity_scroll, max_scroll)
        if from_top:
            visible = lines[self.activity_scroll:self.activity_scroll + capacity]
        else:
            end = len(lines) - self.activity_scroll
            visible = lines[max(0, end - capacity):end]
        for line in visible:
            self.text(line, (LEFT.x + 14, top), self.body, TEXT, max_width=LEFT.width - 28)
            top += line_height

    def _footer(self, progress, thoughts=None):
        controls = (("shortcuts", "Keys", 24, 52),
                    ("snapshot", "Snapshot", 84, 90),
                    ("restore", "Restore", 182, 76),
                    ("restart", "Restart", 266, 76),
                    ("game_save", "Save help", 350, 84),
                    ("toggle_audio", "Unmute" if self.audio_muted else "Mute", 442, 72))
        for action, label, x, width in controls:
            self.button(action, label, pygame.Rect(x, 1026, width, 30),
                        ACCENT if action == "snapshot" else TEXT)
        run = format_duration(progress.get("run_seconds", 0))
        stream = format_duration(progress.get("stream_seconds", 0))
        speed = progress.get("speed", 1)
        self.text(f"Run {run}   ·   Session {stream}   ·   {speed:g}×",
                  (558, 1032), self.small, MUTED)
        strategy_controls(self, progress)
        if not progress.get("strategy") and "Snapshot saved." in ((thoughts or {}).get("jev") or []):
            self.text("Snapshot saved.", (1048, 1032), self.small, GOOD)
        self.text("Esc quit", (1314, 1032), self.small, MUTED)

    def _shortcuts(self):
        box = pygame.Rect(350, 794, 624, 194)
        pygame.draw.rect(self.canvas, BG, box, border_radius=6)
        lines = ("Keyboard", "Arrows move     Z A     X B     Enter Start     Shift Select",
                 "Ctrl-S snapshot     Ctrl-R restore     Ctrl-L play/pause Laya",
                 "V mute audio     C confirm stage     U undo stage     O side stop",
                 "- / + speed     1/2/4/8 select speed     0 reset     Esc quit")
        for index, line in enumerate(lines):
            self.text(line, (box.x + 18, box.y + 16 + index * 32),
                      self.body if index == 0 else self.small, ACCENT if index == 0 else TEXT)
