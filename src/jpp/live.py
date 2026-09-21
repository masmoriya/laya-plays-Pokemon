"""Local playable window with keyboard controls and a compact run HUD."""

from pathlib import Path
import os
import time

import pygame

from .checkpoints import CheckpointManager
from .character.animation import Animation
from .character.character_state import CharacterState
from .audio import AudioSink, pre_init as pre_init_audio
from .game_adapter import adapter_for_rom
from .gold97_adapter import Gold97Adapter
from .gold97_names import apply_requested_names
from .gold97_collision import Gold97CollisionCache
from .frame_pacer import FramePacer
from .agent.gold97_controller import Gold97Controller
from .agent.gold97_input import renew_movement, press_action, release_restored_buttons
from .live_ui import SIZE, LiveUI
from .battle_progress import BattleProgress
from .journey import Journey
from .pokemon_sprites import PokemonSprites
from .journey_timeline import MILESTONES, VISIBLE, timeline_start
from .progress import ProgressTracker
from .terrain_capture import (WorldCamera, overworld_ready, visible_background,
                              visible_entities, visible_player, visible_prompt)
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
    provider_name=None,
):
    # Keep PyBoy and pygame on one SDL2 build on macOS. PyBoy otherwise loads
    # pysdl2-dll alongside pygame's bundled dylib and emits duplicate-class
    # warnings (and may crash when both touch Cocoa).
    pygame_dir = Path(pygame.__file__).resolve().parent / ".dylibs"
    if pygame_dir.is_dir():
        os.environ.setdefault("PYSDL2_DLL_PATH", str(pygame_dir))
    from pyboy import PyBoy

    pre_init_audio()
    pygame.init()
    screen = pygame.display.set_mode(SIZE, pygame.RESIZABLE)
    pygame.display.set_caption("Jev Plays Games")
    checkpoints = CheckpointManager()
    emu = PyBoy(str(rom), window="null")
    emu.set_emulation_speed(0)
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
    audio.set_muted(True)
    audio.set_speed(speed)
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
    autonomous = False
    controller = None
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
    pacer = FramePacer()
    last_save = time.monotonic()
    held_buttons = set()
    autonomous_action = None
    pokemon_sprites = PokemonSprites(rom) if isinstance(adapter, Gold97Adapter) else None
    ui = LiveUI(screen, pokemon_sprites)
    ui.audio_muted = audio.muted
    camera = WorldCamera()
    collision_cache = Gold97CollisionCache()
    provider_name = (provider_name or os.environ.get("AGENT_PROVIDER") or "laya").lower()
    if provider_name not in {"fake", "jev", "laya"}:
        raise ValueError(f"unsupported live tactical provider: {provider_name}")
    tactical_label = provider_name.title()
    laya_vision = os.environ.get("LAYA_VISION", "1").strip().lower() in {
        "1", "true", "yes", "on"
    }
    vision_enabled = provider_name != "laya" or laya_vision
    thoughts = {provider_name: [], "luna": []}
    # An explicit Laya launch is an autonomous launch; F2 still toggles it off/on.
    autonomous = provider_name == "laya"

    def add_thought(source, message):
        if not message:
            return
        entries = thoughts.setdefault(source, [])
        entries.append(message)
        del entries[:-500]

    skip_exit_checkpoint = False
    def save_agent(reason):
        path = _save(emu, checkpoints, tracker, reason, store, journey)
        if controller:
            controller.memory.checkpoint(path)
        return path

    def restore_latest():
        nonlocal last_save, battles, collision_cache, autonomous_action
        restored = checkpoints.latest(run_id)
        if restored is None:
            add_thought("jev", "No snapshot to restore yet.")
            return
        try:
            _load_state(emu, restored)
        except OSError:
            add_thought("jev", "That snapshot is no longer available.")
            return
        autonomous_action = None
        if isinstance(adapter, Gold97Adapter):
            adapter.reset_transition()
            camera.reset()
            collision_cache.reset()
            ui.map_state.reset()
        ui.timeline.player = None
        if not journey.restore_checkpoint(restored):
            journey.reset_view()
        if controller:
            if not controller.memory.restore(restored):
                controller.memory.reset()
            controller.resume()
        metadata = store.checkpoint_metadata(restored) or {}
        for field in ("battles", "wins", "losses", "saves"):
            setattr(tracker.progress, field, max(
                int(getattr(tracker.progress, field, 0)), int(metadata.get(field, 0) or 0)
            ))
        tracker.progress.map_history = list(metadata.get("map_history", ()))
        last_save = time.monotonic()
        audio.flush()
        pacer.reset()
        battles = BattleProgress(tracker.progress.battles, tracker.progress.wins, tracker.progress.losses)
        add_thought("jev", "Snapshot restored.")

    def action(name):
        nonlocal emu, audio, last_save, skip_exit_checkpoint, battles
        nonlocal autonomous, controller, collision_cache
        nonlocal autonomous_action
        if name == "snapshot":
            save_agent("snapshot")
            last_save = time.monotonic()
            add_thought("jev", "Snapshot saved.")
        elif name == "restore":
            restore_latest()
        elif name == "restart":
            if autonomous_action is not None:
                emu.button_release(autonomous_action)
                autonomous_action = None
            collision_cache.reset()
            ui.map_state.reset()
            # Preserve the return point before reboot. Never remove the cartridge RAM.
            save_agent("before-restart")
            audio.close()
            emu.stop(save=True)
            emu = PyBoy(str(rom), window="null")
            emu.set_emulation_speed(0)
            pacer.reset()
            camera.reset()
            if isinstance(adapter, Gold97Adapter):
                adapter.reset_transition()
            ui.timeline.player = None
            audio = AudioSink(getattr(emu.sound, "sample_rate", 48_000))
            audio.set_muted(ui.audio_muted)
            audio.set_speed(speed)
            battles = BattleProgress(tracker.progress.battles, tracker.progress.wins, tracker.progress.losses)
            last_save = time.monotonic()
            skip_exit_checkpoint = True
            add_thought("jev", "Restarted to title. Snapshot kept.")
        elif name == "game_save":
            add_thought("jev", "Use Start → Save in game. Your game save persists on quit.")
        elif name == "toggle_jev" and isinstance(adapter, Gold97Adapter):
            if controller is None:
                from .agent.factory import provider_from_env
                from .agent.policy_adapter import ProviderPolicy
                controller = Gold97Controller(
                    run_id, save_encounter=lambda: save_agent("encounter"),
                    restore_encounter=restore_encounter,
                    restore_stuck=restore_stuck,
                    policy=ProviderPolicy(provider_from_env(provider_name)),
                    vision_enabled=vision_enabled)
                if state_path:
                    if not controller.memory.restore(state_path):
                        controller.memory.reset()
            autonomous = not controller.playback.requested
            if autonomous:
                controller.resume()
            else:
                controller.manual_pause()
                if autonomous_action is not None:
                    emu.button_release(autonomous_action)
                    autonomous_action = None
                add_thought("jev", "Paused.")
        elif name == "toggle_luna" and controller:
            controller.strategy.toggle()
            if controller.strategy.enabled and controller.vision is None:
                from .agent.gold97_vision import LunaScreenReader
                controller.vision = LunaScreenReader()
            if autonomous_action is not None:
                emu.button_release(autonomous_action)
                autonomous_action = None
            if controller.paused and controller.pause_reason.startswith("Luna"):
                controller.resume()
                autonomous = True
        elif name == "retry_agent" and controller:
            controller.resume()
            autonomous = True
        elif name == "strategy_details":
            ui.strategy_details = not ui.strategy_details
        elif name == "model_input":
            ui.show_model_input = not ui.show_model_input
            ui.activity_scroll = 0
        elif name == "shortcuts":
            ui.show_shortcuts = not ui.show_shortcuts
        elif name == "toggle_audio":
            ui.audio_muted = audio.toggle_mute()
        elif name in ("map_grid", "map_artwork"):
            ui.map_mode = "grid" if name == "map_grid" else "artwork"
        elif name == "map_details":
            ui.map_details = not ui.map_details
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
    def restore_encounter(path):
        _load_state(emu, path)
        adapter.reset_transition()
        camera.reset()
        collision_cache.reset()
        ui.map_state.reset()
        pacer.reset()
        audio.flush()
        journey.restore_checkpoint(path)

    def restore_stuck():
        earlier = checkpoints.latest_reason(run_id, "snapshot")
        if earlier is None:
            return None
        save_agent("before-restart")
        restore_encounter(earlier)
        add_thought("jev", "Bedroom input stalled; restored a prior snapshot.")
        return earlier

    if isinstance(adapter, Gold97Adapter):
        from .agent.factory import provider_from_env
        from .agent.policy_adapter import ProviderPolicy
        controller = Gold97Controller(
            run_id, save_encounter=lambda: save_agent("encounter"),
            restore_encounter=restore_encounter,
            restore_stuck=restore_stuck,
            policy=ProviderPolicy(provider_from_env(provider_name)),
            vision_enabled=vision_enabled)
        if state_path and not controller.memory.restore(state_path):
            controller.memory.reset()
        autonomous = controller.playback.requested
        if autonomous:
            controller.resume()

    try:
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        return
                    previous_speed = speed
                    speed = handle_keydown(event, emu, held_buttons, action, speed)
                    if previous_speed != speed:
                        audio.set_speed(speed)
                        pacer.reset()
                if event.type == pygame.KEYUP and event.key in DIRECTION_KEYS:
                    held_buttons.discard(KEYS[event.key])
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    selected = ui.action_at(event.pos)
                    if selected:
                        action(selected)
                if event.type == pygame.MOUSEWHEEL:
                    ui.scroll_activity(pygame.mouse.get_pos(), event.y)
            if held_buttons and autonomous:
                autonomous = False
                controller.manual_pause()
                if autonomous_action is not None:
                    emu.button_release(autonomous_action)
                    autonomous_action = None
                add_thought("jev", "Paused for manual control.")
            _press_held_buttons(emu, held_buttons)
            emu.tick()
            audio.feed(emu)
            if isinstance(adapter, Gold97Adapter):
                names = apply_requested_names(emu)
                if names:
                    add_thought("jev", "Named " + " and ".join(names) + ".")
            snapshot = adapter.snapshot(emu)
            state = snapshot.state
            terrain = (collision_cache.update(emu, state)
                       if isinstance(adapter, Gold97Adapter) else None)
            world_origin = camera.position(emu, state) if isinstance(adapter, Gold97Adapter) else None
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
            progress["tactical_provider"] = provider_name
            progress["tactical_label"] = tactical_label
            # This reports whether the optional map reader is configured, not
            # whether a single asynchronous frame is in flight.
            progress["luna_connected"] = bool(controller and controller.strategy.enabled and controller.vision is not None)
            progress["tactical_auto"] = autonomous
            progress["tactical_available"] = isinstance(adapter, Gold97Adapter)
            if not snapshot.supports_ram_progress:
                progress["current_map"] = f"{snapshot.title} · RAM map pending"
            animation.state = CharacterState.BATTLE if state.in_battle else CharacterState.IDLE
            if update and update.new_badge_event:
                progress["badge_flash"] = update.new_badge_event
                animation.state = CharacterState.CELEBRATE
                add_thought("jev", f"Badge earned: {update.new_badge_event}")
                save_agent("badge")
                store.emit(Event(EventType.BADGE_EARNED, run_id, {"badge": update.new_badge_event}))
            if not skip_exit_checkpoint and time.monotonic() - last_save > CHECKPOINT_INTERVAL_SECONDS:
                save_agent("interval")
                last_save = time.monotonic()
            map_key = f"{state.map_group:02X}:{state.map_number:02X}"
            if (world_origin is not None and collision_cache.ready
                    and camera.map_frames >= 3
                    and (map_key, state.x, state.y) != journey._last_sample):
                observed = visible_background(emu, state, world_origin=world_origin)
                journey.observe_tiles(state, observed)
                # WRAM can retain the old area while the title/menu is open. Only
                # resume automatic snapshots after an actual overworld frame.
                if skip_exit_checkpoint and observed:
                    skip_exit_checkpoint = False
            frame = emu.screen.ndarray
            if world_origin is not None and collision_cache.ready:
                detections = visible_entities(emu, state, world_origin=world_origin)
                ui.map_entities = journey.track_entities(state, detections)
            else:
                ui.map_entities = ()
            if isinstance(adapter, Gold97Adapter):
                visible_overworld = (world_origin is not None or
                                     overworld_ready(emu, state))
                control_overworld = visible_overworld and collision_cache.ready
                if controller:
                    controller.route = journey.route
                if controller and not autonomous:
                    controller.observe(state, ui.map_entities, control_overworld, terrain)
                if autonomous and controller:
                    choice = controller.step(
                        state, frame=frame, entities=ui.map_entities,
                        overworld=control_overworld,
                        prompt_visible=(visible_prompt(emu, state)
                                        if collision_cache.ready and
                                        not visible_overworld and not state.in_battle
                                        else False),
                        terrain=terrain)
                    if choice:
                        if autonomous_action is not None and autonomous_action != choice:
                            emu.button_release(autonomous_action)
                        if autonomous_action != choice:
                            autonomous_action = choice
                            press_action(emu, choice, menu=(state.in_battle or
                                         not control_overworld or controller.healing is not None))
                            pressed = True
                        else:
                            pressed = False
                    else:
                        pressed = False
                    # Release as soon as the controller observes the tile change.
                    # Continuing through cooldown would drift past its origin.
                    autonomous_action = renew_movement(
                        emu, autonomous_action, controller.held_action,
                        overworld=control_overworld, in_battle=state.in_battle,
                        pressed=pressed)
                    while event := controller.pop_provider_event():
                        add_thought(provider_name, event)
                    if controller.paused:
                        if autonomous_action is not None:
                            emu.button_release(autonomous_action)
                            autonomous_action = None
                        if controller.pause_reason != getattr(controller, "displayed_pause", None):
                            add_thought(provider_name, controller.pause_reason)
                            controller.displayed_pause = controller.pause_reason
            if controller:
                controller._poll_provider_health()
                controller.strategy.poll_retired()
                progress["strategy"] = controller.strategy.summary()
                progress["play_requested"] = controller.playback.requested
                progress["playback_status"] = controller.playback.summary()["status"]
                progress["agent_paused"] = controller.paused
                progress["action_source"] = controller.action_source
                progress["model_input"] = controller.latest_model_input
                progress["tactical_auto"] = autonomous and not controller.paused
                ui.strategy_summary = progress["strategy"]
            health = controller.provider_health if controller else "offline"
            if health == "unavailable":
                tactical_status = "unavailable"
            elif autonomous and controller and not controller.paused:
                tactical_status = "checking" if health == "checking" else "live"
            elif health == "ready":
                tactical_status = "ready"
            else:
                tactical_status = "not_connected"
            progress["tactical_health"] = health
            progress["tactical_status"] = tactical_status
            progress["tactical_connected"] = tactical_status == "live"
            progress["tactical_detail"] = (controller.provider_health_error
                                             if controller else "")
            # Keep legacy keys for existing HUD consumers and recorded runs.
            progress["jev_connected"] = progress["tactical_connected"]
            progress["jev_auto"] = progress["tactical_auto"]
            progress["jev_available"] = progress["tactical_available"]
            progress["model_usage"] = (controller.usage_snapshot()
                                        if controller else {"jev": {}, "luna": {}})
            player = (visible_player(emu, state, world_origin=world_origin)
                      if world_origin is not None and collision_cache.ready else None)
            if player:
                ui.player_marker = player
            elif (ui.player_marker and getattr(state, "x", None) is not None
                  and getattr(state, "y", None) is not None
                  and ui.player_marker.map_key == f"{state.map_group:02X}:{state.map_number:02X}"):
                pass  # retain the last captured graphic through menus and partial frames
            else:
                ui.player_marker = None
            ui.navigation_target = (controller.navigation_target
                                    if autonomous and controller else None)
            if controller:
                ui.map_state = controller.map_state
            else:
                ui.map_state.update(
                    state, terrain, ready=collision_cache.ready,
                    overworld=world_origin is not None, entities=ui.map_entities,
                    destination=ui.navigation_target)
            ui.draw(frame, progress, state, animation, thoughts, journey, battles)
            pacer.wait(speed)
    finally:
        try:
            if not skip_exit_checkpoint:
                save_agent("exit")
        finally:
            try:
                audio.close()
            finally:
                if controller:
                    controller.close()
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
    return path


def _load_state(emu, path):
    """Load an emulator snapshot from disk without coupling callers to PyBoy I/O."""
    with Path(path).open("rb") as handle:
        emu.load_state(handle)
    release_restored_buttons(emu)
