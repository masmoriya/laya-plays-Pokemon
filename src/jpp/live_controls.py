"""Keyboard bindings for the playable window."""

import pygame


KEYS = {pygame.K_UP: "up", pygame.K_DOWN: "down", pygame.K_LEFT: "left",
        pygame.K_RIGHT: "right", pygame.K_z: "a", pygame.K_x: "b",
        pygame.K_RETURN: "start", pygame.K_RSHIFT: "select"}
DIRECTION_KEYS = frozenset((pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT))
# Keep the live controls focused on useful playback modes.  The frame pacer
# applies this multiplier directly to the emulator's native frame rate.
SPEEDS = (1.0, 2.0, 4.0, 8.0)
UI_KEYS = {pygame.K_F1: "shortcuts",
           pygame.K_F2: "toggle_jev",
           pygame.K_c: "confirm_stage", pygame.K_u: "undo_stage",
           pygame.K_o: "toggle_optional", pygame.K_v: "toggle_audio"}


def takes_human_control(key, autonomous):
    return bool(autonomous and key in KEYS)


def player_control_mode(autonomous, paused=False, inspector_open=False):
    if not autonomous:
        return "human"
    return "paused" if paused or inspector_open else "ai"


def _adjust_speed(speed, delta):
    index = min(range(len(SPEEDS)), key=lambda i: abs(SPEEDS[i] - speed))
    return SPEEDS[max(0, min(len(SPEEDS) - 1, index + delta))]


def handle_keydown(event, emulator, held_buttons, action, speed):
    key = event.key
    mods = getattr(event, "mod", None)
    if mods is None:
        mods = pygame.key.get_mods()
    if key == pygame.K_l and mods & pygame.KMOD_CTRL:
        action("toggle_jev")
        return speed
    if key in UI_KEYS:
        action(UI_KEYS[key])
        return speed
    button = KEYS.get(key)
    if key in DIRECTION_KEYS:
        held_buttons.add(button)
    elif button:
        emulator.button(button, 4)
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
    elif key == pygame.K_4:
        speed = 4.0
    elif key == pygame.K_8:
        speed = 8.0
    return speed
