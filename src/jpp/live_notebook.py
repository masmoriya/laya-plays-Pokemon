"""Searchable notebook overlay, isolated from emulator keyboard controls."""

import pygame

from .agent.notebook import notebook, text_lines
from .live_ui_colors import BG, MUTED, TEXT


class NotebookPanel:
    def __init__(self):
        self.open = False
        self.view = 'Now'
        self.query = ''
        self.page = 0
        self.data = None

    def handle(self, event):
        if not self.open or event.type not in (pygame.KEYDOWN, pygame.KEYUP):
            return False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.open = False
            elif event.key == pygame.K_BACKSPACE:
                self.query = self.query[:-1]
            elif getattr(event, 'unicode', '').isprintable():
                self.query = (self.query + event.unicode)[:120]
            self.page = 0
        return True

    def action(self, name, controller):
        if name == 'notebook':
            self.open = not self.open
            self.data = notebook(controller)
            self.page = 0
        elif name.startswith('notes_view:'):
            self.view = name.split(':', 1)[1]
            self.page = 0
        elif name == 'notes_next':
            self.page += 1
        elif name == 'notes_previous':
            self.page = max(0, self.page - 1)
        elif name == 'notes_refresh':
            self.data = notebook(controller)
        elif name == 'notes_export':
            return controller.export_notes()

    def draw(self, ui):
        if not self.open or not self.data:
            return
        box = pygame.Rect(342, 176, 640, 828)
        ui.actions = {key: rect for key, rect in ui.actions.items() if not rect.colliderect(box)}
        pygame.draw.rect(ui.canvas, BG, box)
        ui.text('Notebook', (box.x + 18, box.y + 18), ui.title)
        for index, view in enumerate(('Now', 'Learned', 'Attempts')):
            ui.button('notes_view:' + view, view, pygame.Rect(box.x + 18 + index * 96, box.y + 58, 88, 28),
                      TEXT if view == self.view else MUTED)
        ui.button('notes_refresh', 'Refresh', pygame.Rect(box.right - 180, box.y + 58, 76, 28))
        ui.button('notebook', 'Close', pygame.Rect(box.right - 92, box.y + 58, 74, 28))
        ui.text('Search: ' + (self.query or 'Type to filter'), (box.x + 18, box.y + 104),
                ui.body, MUTED, max_width=box.width - 36)
        lines = []
        for entry in text_lines(self.data, self.view, self.query):
            lines.extend(ui.wrap(entry, ui.body, box.width - 36))
            lines.append('')
        capacity = 24
        self.page = min(self.page, max(0, (len(lines) - 1) // capacity))
        for index, line in enumerate(lines[self.page * capacity:(self.page + 1) * capacity]):
            ui.text(line, (box.x + 18, box.y + 150 + index * 24), ui.body, TEXT,
                    max_width=box.width - 36)
        ui.button('notes_previous', 'Previous', pygame.Rect(box.x + 18, box.bottom - 50, 84, 28))
        ui.button('notes_next', 'Next', pygame.Rect(box.x + 114, box.bottom - 50, 68, 28))
        ui.button('notes_export', 'Export', pygame.Rect(box.right - 98, box.bottom - 50, 80, 28))
