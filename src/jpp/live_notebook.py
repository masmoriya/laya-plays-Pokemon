"""Agent inspector state and actions, isolated from emulator keyboard controls."""

import pygame

from .agent.notebook import notebook
from .live_inspector_views import draw_inspector


class NotebookPanel:
    """Backward-compatible name for the Guide/Context/Vision/Notes inspector."""

    def __init__(self):
        self.open = False
        self.view = "Notes"
        self.notes_view = "Now"
        self.query = ""
        self.composer = ""
        self.page = 0
        self.data = None
        self.progress = {}
        self.provider = "laya"
        self.raw_context = False
        self.call_index = -1

    def update(self, progress):
        self.progress = progress or {}

    def handle(self, event):
        if not self.open or event.type not in (pygame.KEYDOWN, pygame.KEYUP):
            return False
        if event.type == pygame.KEYUP:
            return True
        mods = getattr(event, "mod", None)
        if mods is None:
            mods = pygame.key.get_mods()
        if event.key == pygame.K_l and mods & pygame.KMOD_CTRL:
            return False
        if event.key == pygame.K_ESCAPE:
            self.open = False
            return True
        target = "composer" if self.view == "Guide" else "query" if self.view == "Notes" else None
        if target is None:
            return True
        value = getattr(self, target)
        if event.key == pygame.K_BACKSPACE:
            value = value[:-1]
        elif getattr(event, "unicode", "").isprintable():
            value = (value + event.unicode)[:500]
        setattr(self, target, value)
        self.page = 0
        return True

    def action(self, name, controller):
        if name.startswith("agent_open:"):
            self.view = name.split(":", 1)[1]
            self.open = True
            self.page = 0
            if controller:
                self.data = notebook(controller)
        elif name == "notebook":
            self.view = "Notes"
            self.open = not self.open
            if controller:
                self.data = notebook(controller)
            self.page = 0
        elif name.startswith("agent_view:"):
            self.view = name.split(":", 1)[1]
            self.page = 0
        elif name.startswith("agent_provider:"):
            self.provider = name.split(":", 1)[1]
            self.call_index = -1
            self.page = 0
        elif name == "agent_context_mode":
            self.raw_context = not self.raw_context
            self.page = 0
        elif name in {"agent_guide", "agent_remember"} and controller:
            kind = "guide" if name == "agent_guide" else "remember"
            if controller.add_operator_message(kind, self.composer):
                self.composer = ""
                self.data = notebook(controller)
        elif name == "agent_toggle_lean" and controller:
            controller.toggle_lean_context()
            self.data = notebook(controller)
        elif name == "agent_replan" and controller:
            controller.replan()
        elif name == "agent_call_previous":
            self.call_index -= 1
        elif name == "agent_call_next":
            self.call_index = min(-1, self.call_index + 1)
        elif name.startswith("notes_view:"):
            self.notes_view = name.split(":", 1)[1]
            self.page = 0
        elif name == "notes_next":
            self.page += 1
        elif name == "notes_previous":
            self.page = max(0, self.page - 1)
        elif name == "notes_refresh" and controller:
            self.data = notebook(controller)
        elif name == "notes_export" and controller:
            return controller.export_notes()

    def draw(self, ui):
        if self.open:
            draw_inspector(ui, self)
