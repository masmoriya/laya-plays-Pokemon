"""Headless runner for the shared Gold 97 controller."""

import json
import os
import time
from pathlib import Path

from ..checkpoints import CheckpointManager
from ..terrain_capture import overworld_ready, visible_entities, visible_prompt
from ..gold97_names import apply_requested_names
from ..gold97_collision import Gold97CollisionCache
from ..route_progress import RouteProgress
from .gold97_controller import Gold97Controller
from .gold97_input import renew_movement, press_action, release_restored_buttons



def play_gold97(emulator, adapter, policy, max_decisions, log_path=None,
                on_decision=None, on_frame=None, on_audio=None, *,
                run_id="headless-gold97", database="data/jev.sqlite",
                checkpoint_dir="data/checkpoints", vision=None, memory_state=None,
                memory_state_out=None):
    checkpoints = CheckpointManager(directory=checkpoint_dir)
    release_restored_buttons(emulator)
    collision_cache = Gold97CollisionCache()

    def save():
        path, _ = checkpoints.save(emulator, {"run_id": run_id}, "encounter")
        return path

    def restore(path):
        with Path(path).open("rb") as handle:
            emulator.load_state(handle)
        release_restored_buttons(emulator)
        adapter.reset_transition()
        collision_cache.reset()

    def restore_stuck():
        path = checkpoints.latest_reason(run_id, "snapshot")
        if path is None:
            return None
        safety, _ = checkpoints.save(emulator, {"run_id": run_id}, "before-restart")
        controller.memory.checkpoint(safety)
        restore(path)
        return path

    provider_name = getattr(getattr(policy, "provider", None), "usage_provider", "jev")
    laya_vision = os.environ.get("LAYA_VISION", "1").strip().lower() in {
        "1", "true", "yes", "on"
    }
    controller = Gold97Controller(
        run_id, database=database, policy=policy, vision=vision,
        vision_enabled=provider_name != "laya" or vision is not None or laya_vision,
        save_encounter=save, restore_encounter=restore,
        restore_stuck=restore_stuck,
    )
    if memory_state and not controller.memory.restore(memory_state):
        controller.memory.reset()
    controller.route = RouteProgress.from_dict(controller.memory.world.get("route"))
    controller.resume()
    records = []
    log = Path(log_path).open("a") if log_path else None
    frames = 0
    held_action = None
    try:
        while len(records) < max_decisions and frames < max_decisions * 120:
            apply_requested_names(emulator)
            snapshot = adapter.snapshot(emulator)
            state = snapshot.state
            terrain = collision_cache.update(emulator, state)
            frame = emulator.screen.ndarray
            entities = visible_entities(emulator, state)
            visible_overworld = overworld_ready(emulator, state)
            overworld = visible_overworld and collision_cache.ready
            action = controller.step(state, frame=frame, entities=entities,
                                     overworld=overworld, terrain=terrain,
                                     prompt_visible=(visible_prompt(emulator, state)
                                                     if collision_cache.ready and
                                                     not visible_overworld and not state.in_battle
                                                     else False))
            if controller.paused and controller.playback.status == "blocked":
                print(f"Gold 97 autonomous play paused: {controller.pause_reason}")
                break
            # Luna's map read is advisory: keep emulating and walking while it
            # runs. Only an unfinished tactical choice needs this brief wait.
            if (action is None and controller.decision_future and
                    not controller.decision_future.done()):
                held_action = renew_movement(
                    emulator, held_action, controller.held_action,
                    overworld=overworld, in_battle=state.in_battle)
                time.sleep(0.02)
                continue
            pressed = False
            if action:
                if held_action is not None and held_action != action:
                    emulator.button_release(held_action)
                if held_action != action:
                    held_action = action
                    press_action(emulator, action, menu=(state.in_battle or
                                 not overworld or controller.healing is not None))
                    pressed = True
            # Renew only the movement still owned by the controller.
            # An observed tile change ends the hold, including during cooldown.
            held_action = renew_movement(
                emulator, held_action, controller.held_action,
                overworld=overworld, in_battle=state.in_battle, pressed=pressed)
            if action:
                decision = controller.last_decision
                record = {"t": time.time(), "kind": "gold97", "state": {
                    "map": state.area_name, "x": state.x, "y": state.y,
                    "battle": state.battle.kind}, "choice": action,
                    "luna_enabled": controller.strategy.enabled,
                    "action_source": controller.action_source,
                    "journey_step": controller.route.now,
                    "probabilities": decision.probabilities if decision else {},
                    "confidence": decision.confidence if decision else None,
                    "input_tokens": decision.input_tokens if decision else 0,
                    "output_tokens": decision.output_tokens if decision else 0,
                    "total_tokens": decision.total_tokens if decision else 0,
                    "latency_ms": decision.latency_ms if decision else 0,
                    "actual_cost_usd": decision.actual_cost_usd if decision else None,
                    "fell_back": bool(decision.fell_back) if decision else False,
                    "reason": decision.reason if decision else controller.opening_goal}
                records.append(record)
                if log:
                    log.write(json.dumps(record) + "\n")
                    log.flush()
                if on_decision:
                    on_decision(record)
            emulator.tick(1)
            frames += 1
            if on_audio:
                on_audio(emulator)
            if on_frame:
                on_frame(emulator)
    finally:
        release_restored_buttons(emulator)
        if log:
            log.close()
        if memory_state_out:
            controller.memory.checkpoint(memory_state_out)
        controller.close()
    return records
