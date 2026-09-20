"""Headless runner for the shared Gold 97 controller."""

import json
import time
from pathlib import Path

from ..checkpoints import CheckpointManager
from ..terrain_capture import visible_background, visible_entities
from .gold97_controller import Gold97Controller


def play_gold97(emulator, adapter, policy, max_decisions, log_path=None,
                on_decision=None, on_frame=None, on_audio=None, *,
                run_id="headless-gold97", database="data/jev.sqlite",
                checkpoint_dir="data/checkpoints", vision=None, memory_state=None):
    checkpoints = CheckpointManager(directory=checkpoint_dir)

    def save():
        path, _ = checkpoints.save(emulator, {"run_id": run_id}, "encounter")
        return path

    def restore(path):
        with Path(path).open("rb") as handle:
            emulator.load_state(handle)
        adapter.reset_transition()

    controller = Gold97Controller(run_id, database=database, policy=policy,
                                  vision=vision, save_encounter=save,
                                  restore_encounter=restore)
    if memory_state and not controller.memory.restore(memory_state):
        controller.memory.reset()
    records = []
    log = Path(log_path).open("a") if log_path else None
    frames = 0
    try:
        while len(records) < max_decisions and frames < max_decisions * 120:
            snapshot = adapter.snapshot(emulator)
            state = snapshot.state
            frame = emulator.screen.ndarray
            entities = visible_entities(emulator, state)
            action = controller.step(state, frame=frame, entities=entities,
                                     overworld=bool(visible_background(emulator, state)))
            if controller.paused:
                print(f"Gold 97 autonomous play paused: {controller.pause_reason}")
                break
            if ((controller.vision_future and not controller.vision_future.done()) or
                    (controller.decision_future and not controller.decision_future.done())):
                time.sleep(0.02)
                continue
            if action:
                emulator.button(action, 4)
                decision = controller.last_decision
                record = {"t": time.time(), "kind": "gold97", "state": {
                    "map": state.area_name, "x": state.x, "y": state.y,
                    "battle": state.battle.kind}, "choice": action,
                    "probabilities": decision.probabilities if decision else {},
                    "confidence": decision.confidence if decision else None,
                    "input_tokens": decision.input_tokens if decision else 0,
                    "output_tokens": decision.output_tokens if decision else 0,
                    "total_tokens": decision.total_tokens if decision else 0,
                    "latency_ms": decision.latency_ms if decision else 0,
                    "actual_cost_usd": decision.actual_cost_usd if decision else None,
                    "fell_back": False}
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
        if log:
            log.close()
        controller.close()
    return records
