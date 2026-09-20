"""Local playable window with keyboard controls and a compact run HUD."""

from pathlib import Path
import time

import pygame

from .checkpoints import CheckpointManager
from .character.animation import Animation
from .character.character_state import CharacterState
from .audio import AudioSink, pre_init as pre_init_audio
from .game_adapter import adapter_for_rom
from .gold97_adapter import Gold97Adapter
from .live_ui import SIZE, LiveUI
from .battle_progress import BattleProgress
from .journey import Journey
from .pokemon_sprites import PokemonSprites
from .journey_timeline import MILESTONES, VISIBLE, timeline_start
from .progress import ProgressTracker
from .terrain_capture import visible_background, visible_entities, visible_player
from .live_controls import handle_keydown
from .live_cli import add_parser
from .rules import GameRules
from .telemetry import Event, EventType, RunStore


from .live_controls import DIRECTION_KEYS, KEYS, SPEEDS, _adjust_speed
CHECKPOINT_INTERVAL_SECONDS = 120


def _press_held_buttons(emulator, held_buttons):
    """Keep held controls down for the next emulator tick.

    PyBoy releases a button automatically unless it is pressed again before the next
    tick. Renewing with a one-frame delay makes movement follow the user's key hold
    instead of depending on the operating system's key-repeat interval.
    """
    for button in held_buttons:
        emulator.button(button, 1)


def run(
    rom: Path,
    state: Path | None = None,
    run_id="run-001",
    rules_path="config/game_rules.json",
    player_name=None,
    starter=None,
    game_adapter="auto",
    speed=1.0,
    resume=True,
    native_save=False,
):
    from pyboy import PyBoy

    pre_init_audio()
    pygame.init()
    screen = pygame.display.set_mode(SIZE, pygame.RESIZABLE)
    pygame.display.set_caption("Jev Plays Games")
    checkpoints = CheckpointManager()
    emu = PyBoy(str(rom), window="null")
    emu.set_emulation_speed(speed)
    state_path = Path(state) if state else None
    if state_path is None and resume and not native_save:
        state_path = checkpoints.latest(run_id)
        if state_path:
            print(f"resuming from checkpoint: {state_path}")
        else:
            print(f"no checkpoint found for {run_id}; starting a new run")
    if state_path:
        _load_state(emu, state_path)
    audio = AudioSink(getattr(emu.sound, "sample_rate", 48_000))
    store = RunStore(run_id=run_id)
    journey = Journey(run_id)
    if state_path and not journey.restore_checkpoint(state_path):
        journey.reset_view()
    if not state_path and not resume and not native_save:
        journey.reset_view()
    stats = store.stats()
    initial = store.checkpoint_metadata(state_path) if state_path else None
    initial = initial if initial is not None else ({} if state_path or native_save else stats)
    # A checkpoint represents game state, not a rewind of the public run record.
    # Preserve the highest durable totals when reopening or manually restoring one.
    initial = {
        **initial,
        **{field: max(int(initial.get(field, 0) or 0), int(stats.get(field, 0) or 0))
           for field in ("battles", "wins", "losses", "saves")},
    }
    active_play_seconds = max(
        float(initial.get("active_play_seconds", initial.get("run_seconds", 0)) or 0),
        float(stats.get("active_play_seconds", stats.get("run_seconds", 0)) or 0),
    )
    rules = GameRules.load(rules_path).with_overrides(player_name, starter)
    adapter = adapter_for_rom(
        rom, getattr(emu, "cartridge_title", None), forced=game_adapter
    )
    tracker = ProgressTracker(
        run_id,
        # ``started_at`` in the run store is historical telemetry. The HUD clock is
        # for this launched session, so a fresh window always starts at zero.
        started_at=time.time(),
        player_name=rules.player_name,
        map_history=initial.get("map_history"),
        active_play_seconds=active_play_seconds,
    )
    for field in ("battles", "wins", "losses", "saves"):
        setattr(tracker.progress, field, int(initial.get(field, 0)))
    battles = BattleProgress(tracker.progress.battles, tracker.progress.wins, tracker.progress.losses)
    store.emit(Event(EventType.RUN_STARTED, run_id, {"mode": "human", **rules.public_context()}))
    animation = Animation()
    last_save = time.monotonic()
    held_buttons = set()
    pokemon_sprites = PokemonSprites(rom) if isinstance(adapter, Gold97Adapter) else None
    ui = LiveUI(screen, pokemon_sprites)
    thoughts = {"jev": [], "luna": []}

    def add_thought(source, message):
        if not message:
            return
        entries = thoughts[source]
        if not entries or entries[-1] != message:
            entries.append(message)
            del entries[:-8]

    skip_exit_checkpoint = False
    last_position = None
    frames_at_position = 0

    def restore_latest():
        nonlocal last_save, battles, last_position
        restored = checkpoints.latest(run_id)
        if restored is None:
            add_thought("jev", "No snapshot to restore yet.")
            return
        try:
            _load_state(emu, restored)
        except OSError:
            add_thought("jev", "That snapshot is no longer available.")
            return
        if isinstance(adapter, Gold97Adapter):
            adapter.reset_transition()
        ui.timeline.player = None
        if not journey.restore_checkpoint(restored):
            journey.reset_view()
        metadata = store.checkpoint_metadata(restored) or {}
        for field in ("battles", "wins", "losses", "saves"):
            setattr(tracker.progress, field, max(
                int(getattr(tracker.progress, field, 0)), int(metadata.get(field, 0) or 0)
            ))
        tracker.progress.map_history = list(metadata.get("map_history", ()))
        last_save = time.monotonic()
        last_position = None
        audio.close()
        battles = BattleProgress(tracker.progress.battles, tracker.progress.wins, tracker.progress.losses)
        add_thought("jev", "Snapshot restored.")

    def action(name):
        nonlocal emu, audio, last_save, skip_exit_checkpoint, battles, last_position
        if name == "snapshot":
            _save(emu, checkpoints, tracker, "snapshot", store, journey)
            last_save = time.monotonic()
            add_thought("jev", "Snapshot saved.")
        elif name == "restore":
            restore_latest()
        elif name == "restart":
            # Preserve the return point before reboot. Never remove the cartridge RAM.
            _save(emu, checkpoints, tracker, "before-restart", store, journey)
            audio.close()
            emu.stop(save=True)
            emu = PyBoy(str(rom), window="null")
            if isinstance(adapter, Gold97Adapter):
                adapter.reset_transition()
            ui.timeline.player = None
            emu.set_emulation_speed(speed)
            audio = AudioSink(getattr(emu.sound, "sample_rate", 48_000))
            audio.set_muted(ui.audio_muted)
            battles = BattleProgress(tracker.progress.battles, tracker.progress.wins, tracker.progress.losses)
            last_save = time.monotonic()
            last_position = None
            skip_exit_checkpoint = True
            add_thought("jev", "Restarted to title. Snapshot kept.")
        elif name == "game_save":
            add_thought("jev", "Use Start → Save in game. Your game save persists on quit.")
        elif name == "shortcuts":
            ui.show_shortcuts = not ui.show_shortcuts
        elif name == "toggle_audio":
            ui.audio_muted = audio.toggle_mute()
        elif name == "map_toggle":
            ui.map_mode = "paths" if ui.map_mode == "terrain" else "terrain"
        elif name == "map_details":
            ui.map_details = not ui.map_details
        elif name == "map_expand":
            ui.map_expanded = not ui.map_expanded
        elif name == "confirm_stage":
            if journey.route.confirm() is not None:
                journey.save_route()
        elif name == "undo_stage":
            if journey.route.correct() is not None:
                journey.save_route()
        elif name == "toggle_optional" and ui.selected_optional:
            if journey.route.toggle_optional(ui.selected_optional):
                journey.save_route()
        elif name == "timeline_prev":
            ui.timeline.page = max(0, timeline_start(journey.route.completed, ui.timeline.page) - 8)
        elif name == "timeline_next":
            ui.timeline.page = min(len(MILESTONES) - VISIBLE,
                                   timeline_start(journey.route.completed, ui.timeline.page) + 8)
    try:
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        if ui.map_expanded:
                            ui.map_expanded = False
                            continue
                        return
                    previous_speed = speed
                    speed = handle_keydown(event, emu, held_buttons, action, speed)
                    if previous_speed != speed:
                        audio.close()
                if event.type == pygame.KEYUP and event.key in DIRECTION_KEYS:
                    held_buttons.discard(KEYS[event.key])
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    selected = ui.action_at(event.pos)
                    if selected:
                        action(selected)
            _press_held_buttons(emu, held_buttons)
            emu.tick()
            audio.feed(emu)
            snapshot = adapter.snapshot(emu)
            state = snapshot.state
            update = snapshot.badge_update
            journey.observe_route(state)
            outcome = battles.update(state)
            if outcome:
                store.emit(Event(EventType.BATTLE_ENDED, run_id, {"result": outcome}))
                store.set_stats(battles=battles.battles, wins=battles.wins, losses=battles.losses)
            tracker.progress.battles = battles.battles
            tracker.progress.wins = battles.wins
            tracker.progress.losses = battles.losses
            progress = tracker.update(state, update).to_dict()
            progress["game_title"] = snapshot.title
            progress["player_name"] = rules.player_name
            progress["speed"] = speed
            progress["jev_connected"] = False
            progress["luna_connected"] = False
            if not snapshot.supports_ram_progress:
                progress["current_map"] = f"{snapshot.title} · RAM map pending"
            animation.state = CharacterState.BATTLE if state.in_battle else CharacterState.IDLE
            if update and update.new_badge_event:
                progress["badge_flash"] = update.new_badge_event
                animation.state = CharacterState.CELEBRATE
                add_thought("jev", f"Badge earned: {update.new_badge_event}")
                _save(emu, checkpoints, tracker, "badge", store, journey)
                store.emit(Event(EventType.BADGE_EARNED, run_id, {"badge": update.new_badge_event}))
            if not skip_exit_checkpoint and time.monotonic() - last_save > CHECKPOINT_INTERVAL_SECONDS:
                _save(emu, checkpoints, tracker, "interval", store, journey)
                last_save = time.monotonic()
            position = (getattr(state, "map_name", None), getattr(state, "x", None), getattr(state, "y", None))
            frames_at_position = frames_at_position + 1 if position == last_position else 0
            if position != last_position:
                last_position = position
                journey._last_sample = None
            if frames_at_position >= 3 and frames_at_position % 15 == 3 and isinstance(adapter, Gold97Adapter):
                observed = visible_background(emu, state)
                journey.observe_tiles(state, observed)
                # WRAM can retain the old area while the title/menu is open. Only
                # resume automatic snapshots after an actual overworld frame.
                if skip_exit_checkpoint and observed:
                    skip_exit_checkpoint = False
            frame = emu.screen.ndarray
            ui.map_entities = visible_entities(emu, state) if isinstance(adapter, Gold97Adapter) else ()
            ui.player_pixels = visible_player(emu, state) if isinstance(adapter, Gold97Adapter) else None
            ui.draw(frame, progress, state, animation, thoughts, journey, battles)
    finally:
        try:
            if not skip_exit_checkpoint:
                _save(emu, checkpoints, tracker, "exit", store, journey)
        finally:
            try:
                audio.close()
            finally:
                emu.stop(save=True)
                tracker.progress.seal_active_time()
                store.set_stats(**tracker.progress.to_dict())
                store.close()
                journey.close()
                pygame.quit()


def _save(emu, checkpoints, tracker, reason, store=None, journey=None):
    tracker.progress.seal_active_time()
    tracker.progress.saves += 1
    metadata = tracker.progress.to_dict()
    path, saved_metadata = checkpoints.save(emu, metadata, reason)
    if store:
        store.add_checkpoint(path, saved_metadata)
        store.set_stats(**metadata)
    if journey:
        journey.record_checkpoint(path)
    print(f"checkpoint saved: {path}")


def _load_state(emu, path):
    """Load an emulator snapshot from disk without coupling callers to PyBoy I/O."""
    with Path(path).open("rb") as handle:
        emu.load_state(handle)
