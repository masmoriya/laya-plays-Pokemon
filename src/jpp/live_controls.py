"""Keyboard bindings for the playable window."""

import pygame


KEYS = {pygame.K_UP: "up", pygame.K_DOWN: "down", pygame.K_LEFT: "left",
        pygame.K_RIGHT: "right", pygame.K_z: "a", pygame.K_x: "b",
        pygame.K_RETURN: "start", pygame.K_RSHIFT: "select"}
DIRECTION_KEYS = frozenset((pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT))
SPEEDS = (0.25, 0.5, 1.0, 2.0, 3.0, 4.0)
UI_KEYS = {pygame.K_F1: "shortcuts", pygame.K_m: "map_toggle",
           pygame.K_c: "confirm_stage", pygame.K_u: "undo_stage",
           pygame.K_o: "toggle_optional", pygame.K_v: "toggle_audio"}


def _adjust_speed(speed, delta):
    index = min(range(len(SPEEDS)), key=lambda i: abs(SPEEDS[i] - speed))
    return SPEEDS[max(0, min(len(SPEEDS) - 1, index + delta))]


def handle_keydown(event, emulator, held_buttons, action, speed):
    key = event.key
    if key in UI_KEYS:
        action(UI_KEYS[key])
        return speed
    button = KEYS.get(key)
    if key in DIRECTION_KEYS:
        held_buttons.add(button)
    elif button:
        emulator.button(button, 4)
    mods = pygame.key.get_mods()
    if key == pygame.K_s and mods & pygame.KMOD_CTRL:
        action("snapshot")
    elif key == pygame.K_r and mods & pygame.KMOD_CTRL:
        action("restore")
    if key in (pygame.K_MINUS, pygame.K_LEFTBRACKET):
        speed = _adjust_speed(speed, -1)
    elif key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_RIGHTBRACKET):
        speed = _adjust_speed(speed, 1)
    elif key in (pygame.K_0, pygame.K_1):
        speed = 1.0
    elif key == pygame.K_2:
        speed = 2.0
    emulator.set_emulation_speed(speed)
    return speed
