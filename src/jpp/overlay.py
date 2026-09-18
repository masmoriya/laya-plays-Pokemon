"""The 1280x720 window: game feed left, what Jev was actually asked and answered right.

Runs live over PyBoy, or with `--replay <run.jsonl>` over a recorded run at about two
decisions a second, which is how the clip gets recorded before a ROM exists. Bars animate
from the previous probabilities to the new ones so the eye can follow which option moved.
"""

import json
import time
from pathlib import Path

import pygame

from . import measure
from .policy import cost_usd

W, H = 1280, 720
GAME_W, GAME_H = 160, 144
SCALE = 3
FEED = pygame.Rect(28, 92, GAME_W * SCALE, GAME_H * SCALE)
PANEL = pygame.Rect(544, 28, W - 544 - 28, H - 56)
BAR_TOP, BAR_H, BAR_GAP, BAR_MAX = 380, 24, 8, 7
ANIMATION_MS = 200

BG = (22, 22, 29)
CARD = (31, 31, 40)
EDGE = (42, 42, 54)
FG = (220, 215, 186)
MUTED = (114, 113, 140)
KEY = (126, 156, 216)
STRING = (152, 187, 108)
NUMBER = (210, 126, 153)
ACCENT = (255, 160, 102)
BAR = (76, 96, 140)
BAR_ON = (126, 156, 216)


def _font(size, bold=False):
    return pygame.font.SysFont("Menlo,Monaco,monospace", size, bold=bold)


def tint(token: str):
    stripped = token.strip().rstrip(",")
    if stripped.endswith(":"):
        return KEY
    if stripped.startswith('"'):
        return STRING
    try:
        float(stripped)
        return NUMBER
    except ValueError:
        return FG if stripped in "{}[]" else MUTED


def state_lines(state: dict, width: int, height: int) -> list[str]:
    """Pretty-printed and scrolled to fit: the tail is where the options live."""
    text = json.dumps(state, indent=1).splitlines()
    text = [line if len(line) <= width else line[: width - 3] + "..." for line in text]
    return text if len(text) <= height else text[:2] + ["  ..."] + text[-(height - 3) :]


def fit(font, text: str, width: int) -> str:
    while text and font.size(text)[0] > width:
        text = text[:-2] + "."
    return text


class Overlay:
    def __init__(self, caption="jev-plays-pokemon"):
        pygame.init()
        pygame.display.set_caption(caption)
        self.screen = pygame.display.set_mode((W, H))
        self.clock = pygame.time.Clock()
        self.mono = _font(13)
        self.small = _font(12)
        self.head = _font(21, bold=True)
        self.label = _font(15)
        self.shown: dict[str, float] = {}
        self.target: dict[str, float] = {}
        self.changed_at = 0.0
        self.record = None
        self.latencies: list[float] = []
        self.started = None
        self.decisions = 0
        self.tokens = 0
        self.labelled: list[tuple[float, int]] = []

    def feed(self, record: dict, labelled=None):
        self.record = record
        self.target = dict(record.get("probabilities") or {})
        # keep only the options this decision offered: a move from a previous battle
        # would otherwise sit at zero in the bar list for the rest of the run
        self.shown = {k: self.shown.get(k, 0.0) for k in self.target}
        self.changed_at = time.monotonic()
        self.decisions += 1
        self.tokens += record.get("input_tokens") or 0
        self.latencies = (self.latencies + [record.get("latency_ms") or 0.0])[-60:]
        self.started = self.started or record.get("t") or time.time()
        if labelled is not None:
            self.labelled = labelled

    def draw(self, frame=None):
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (
                event.type == pygame.KEYDOWN
                and event.key in (pygame.K_ESCAPE, pygame.K_q)
            ):
                return False
        self.screen.fill(BG)
        self._draw_feed(frame)
        pygame.draw.rect(self.screen, CARD, PANEL, border_radius=8)
        pygame.draw.rect(self.screen, EDGE, PANEL, width=1, border_radius=8)
        if self.record:
            self._draw_goal()
            self._draw_state()
            self._draw_bars()
        self._draw_footer()
        pygame.display.flip()
        self.clock.tick(60)
        return True

    def _draw_feed(self, frame):
        title = self.head.render("jev plays pokemon", True, FG)
        self.screen.blit(title, (FEED.x, 40))
        pygame.draw.rect(self.screen, CARD, FEED.inflate(16, 16), border_radius=6)
        if frame is not None:
            surface = pygame.surfarray.make_surface(frame.swapaxes(0, 1)[:, :, :3])
            self.screen.blit(pygame.transform.scale(surface, FEED.size), FEED)
        else:
            pygame.draw.rect(self.screen, BG, FEED, border_radius=4)
            note = self.label.render("no ROM: replaying a recorded run", True, MUTED)
            self.screen.blit(note, note.get_rect(center=FEED.center))
        if self.record:
            kind = self.small.render(
                f"branch: {self.record['kind']}    goal: {self.record['goal']}",
                True,
                MUTED,
            )
            self.screen.blit(kind, (FEED.x, FEED.bottom + 22))

    def _draw_goal(self):
        goal = self.record["state"].get("goal", self.record["goal"])
        self.screen.blit(
            self.head.render(fit(self.head, goal, PANEL.width - 40), True, ACCENT),
            (PANEL.x + 20, PANEL.y + 18),
        )
        self.screen.blit(
            self.small.render("state sent to jev", True, MUTED),
            (PANEL.x + 20, PANEL.y + 54),
        )

    def _draw_state(self):
        top, left = PANEL.y + 76, PANEL.x + 20
        rows = (BAR_TOP - 40 - top) // 15
        columns = (PANEL.width - 40) // self.mono.size("0")[0]
        for i, line in enumerate(state_lines(self.record["state"], columns, rows)):
            self.screen.blit(
                self.mono.render(line, True, tint(line)), (left, top + i * 15)
            )

    def _draw_bars(self):
        now = time.monotonic()
        progress = min(1.0, (now - self.changed_at) * 1000 / ANIMATION_MS)
        for key in self.shown:
            self.shown[key] += (self.target.get(key, 0.0) - self.shown[key]) * progress
        left = PANEL.x + 20
        label_w, value_w = 210, 52
        track_x = left + label_w
        track_w = PANEL.width - 40 - label_w - value_w
        self.screen.blit(
            self.small.render("every option, sorted", True, MUTED), (left, BAR_TOP - 20)
        )
        chosen = self.record.get("choice")
        ordered = sorted(
            self.shown.items(), key=lambda kv: -self.target.get(kv[0], 0.0)
        )
        for i, (key, value) in enumerate(ordered[:BAR_MAX]):
            y = BAR_TOP + i * (BAR_H + BAR_GAP)
            picked = key == chosen
            name = fit(self.label, key, label_w - 12)
            self.screen.blit(
                self.label.render(name, True, FG if picked else MUTED), (left, y + 5)
            )
            pygame.draw.rect(
                self.screen, BG, (track_x, y, track_w, BAR_H), border_radius=4
            )
            filled = max(2, int(track_w * max(0.0, min(1.0, value))))
            pygame.draw.rect(
                self.screen,
                BAR_ON if picked else BAR,
                (track_x, y, filled, BAR_H),
                border_radius=4,
            )
            number = self.label.render(
                f"{self.target.get(key, 0.0):.2f}", True, FG if picked else MUTED
            )
            self.screen.blit(
                number, (track_x + track_w + value_w - number.get_width(), y + 5)
            )
        self._draw_nouls(
            left, BAR_TOP + len(ordered[:BAR_MAX]) * (BAR_H + BAR_GAP) + 14
        )

    def _draw_nouls(self, left, y):
        """The two nouls that rode along in the same request, for the same price."""
        nouls = self.record.get("nouls") or {}
        if not nouls:
            return
        text = "    ".join(f"{name} {value:.2f}" for name, value in nouls.items())
        self.screen.blit(
            self.small.render("side questions, same request", True, MUTED), (left, y)
        )
        self.screen.blit(self.label.render(text, True, FG), (left, y + 18))

    def _draw_footer(self):
        elapsed = max(1e-6, (time.time() - self.started)) if self.started else 0.0
        rate = self.decisions / elapsed if elapsed else 0.0
        per_hour = cost_usd(self.tokens) / elapsed * 3600 if elapsed else 0.0
        last = self.latencies[-1] if self.latencies else 0.0
        brier = (
            f"Brier {measure.brier(self.labelled):.3f} (n={len(self.labelled)})"
            if self.labelled
            else "Brier pending"
        )
        text = (
            f"{rate:.1f} decisions/sec    ${per_hour:.2f}/hour    "
            f"last call {last:.0f} ms    {brier}"
        )
        self.screen.blit(self.label.render(text, True, MUTED), (FEED.x, H - 44))
        self._draw_sparkline(pygame.Rect(FEED.x, H - 76, 460, 22))

    def _draw_sparkline(self, box):
        if len(self.latencies) < 2:
            return
        top = max(self.latencies) or 1.0
        step = box.width / (len(self.latencies) - 1)
        points = [
            (box.x + i * step, box.bottom - (v / top) * box.height)
            for i, v in enumerate(self.latencies)
        ]
        pygame.draw.lines(self.screen, ACCENT, False, points, 1)


def run_replay(path: Path, rate: float = 2.0):
    """Play a run file back so the clip can be recorded with no ROM in sight."""
    records = measure.load([path])[0]
    labelled = measure.pairs(records)
    overlay = Overlay(f"jev-plays-pokemon: {path.name}")
    overlay.started = time.time()
    index, next_at = 0, 0.0
    running = True
    while running:
        if index < len(records) and time.monotonic() >= next_at:
            overlay.feed(records[index], labelled=labelled[: max(0, index - 1)])
            overlay.started = (
                time.time() - index / rate
            )  # the ticker reads the replay clock
            index += 1
            next_at = time.monotonic() + 1.0 / rate
        running = overlay.draw()
        if index >= len(records) and time.monotonic() > next_at + 3:
            running = False
    pygame.quit()
