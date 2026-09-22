"""Resolve asynchronous policy choices and execute committed menu answers."""

from .gold97_state import decision_state
from ..route_progress import MAIN
from .controller_constants import _MENU_COOLDOWN_FRAMES, _MOVE_HOLD_FRAMES, _STEPS
from .live_state import display_action, short_reason


class DecisionChoice:
    def _decide_step(self, state, entities, overworld, options, note, key,
                     position, strategy_active, *, frame=None):
        body = decision_state(state, self.memory, note, key, position)
        if overworld and not state.in_battle:
            body['screen_text'] = []  # Overworld tiles are graphics, not dialogue.
        if not overworld and not state.in_battle:
            body["decision_kind"] = "dialogue"
            from .gold97_choices import conversation_context
            body['conversation'] = conversation_context(self)
        body["journey"] = self.strategy.context(state)
        body["strategy"] = self.strategy.data.get("plan")
        body["luna_enabled"] = self.strategy.enabled
        step = self.route.now
        if step is not None:
            body["goal"] = f"Complete Journey step {step}: {MAIN[step]}"
            body["journey_step"] = step
        from .game_loop import GenericBranch
        decision_key = (key, position, state.battle.kind,
                        getattr(state.battle.opponent, "hp", None),
                        tuple(options), str(note), self.route.now, self.strategy.generation,
                        tuple(getattr(state, "screen_lines", ())) if not overworld else None,
                        getattr(state, "screen_cursor", None) if not overworld else None)
        if self.decision_future is None:
            branch = GenericBranch(body["decision_kind"], body, options)
            self.pending_options = dict(options)
            self.decision_key = decision_key
            if len(options) == 1:
                from concurrent.futures import Future
                from ..policy import Decision
                self.decision_future = Future()
                self.decision_future.set_result(Decision(option=next(iter(options)), request_made=False))
            else:
                self.decision_future = self.executor.submit(self.policy.decide, branch)
                return None
        if not self.decision_future.done():
            return None
        if self.decision_key != decision_key:
            self.decision_future = None
            return None
        try:
            decision = self.decision_future.result()
        except Exception as exc:
            self.pause(f"{self._provider_label()} unavailable: {type(exc).__name__}")
            self._set_provider_event(f"{self._provider_label()} error: {type(exc).__name__}")
            self.live.model_call(
                self._tactical_usage_provider(), status="error", error=str(exc),
                phase=body.get("decision_kind", "decision"),
            )
            return None
        finally:
            self.decision_future = None
        self.last_decision = decision
        if decision.fell_back:
            self.live.model_call(
                self._tactical_usage_provider(), status="fallback",
                error=decision.reason, fallback=display_action(decision.option),
                phase=body.get("decision_kind", "decision"),
            )
        if decision.request_made:
            if decision.model_input:
                self.latest_model_input = {
                    "provider": self._provider_label(),
                    **decision.model_input,
                }
                kind = body.get("decision_kind", "decision")
                self._set_provider_event(
                    f"{self._provider_label()} input · {kind} · "
                    f"{', '.join(options)}"
                )
            self.usage.record(
                self._tactical_usage_provider(),
                input_tokens=decision.input_tokens,
                output_tokens=decision.output_tokens,
                total_tokens=decision.total_tokens,
                latency_ms=decision.latency_ms,
                actual_cost_usd=decision.actual_cost_usd,
            )
            self.live.model_call(
                self._tactical_usage_provider(),
                {"input_tokens": decision.input_tokens,
                 "output_tokens": decision.output_tokens,
                 "latency_ms": decision.latency_ms},
                decision.model_input,
                confidence=decision.confidence,
                phase=body.get("decision_kind", "decision"),
            )
        if decision.option == "wait":
            # Waiting is not a gameplay objective. Older Laya sidecars can still
            # emit the retired token, so translate it to a legal forward input
            # instead of letting the agent idle forever or treating it as a fatal
            # policy error.
            action = next((name for name in
                           ("up", "down", "left", "right", "a", "b", "start")
                           if name in options), None)
            if action is None:
                action = next(iter(options), "a")
            self.wait_streak += 1
            self._set_provider_event(f"{self._provider_label()} wait replaced with {action}")
        elif decision.option not in options:
            self.pause(f"{self._provider_label()} returned an invalid choice")
            self._set_provider_event(f"{self._provider_label()} returned an invalid choice")
            return None
        else:
            action = decision.option
        if action in {"yes", "no"}:
            from .gold97_choices import answer_button, choice_key
            self.dialogue_choice = (choice_key(state), action)
            action = answer_button(state, action)
            if action is None:
                return None
        plan = self.strategy.data.get("plan") or {}
        if not decision.request_made:
            why = str(options.get(action) or "Only available action")
        elif plan.get("explanation"):
            why = plan["explanation"]
        elif decision.reason:
            why = short_reason(decision.reason)
        else:
            why = str(options.get(action) or "Best legal option")
        self.live.decide(
            kind=body.get("decision_kind", "decision"),
            source=self._provider_label() if decision.request_made else "Automatic",
            why=why,
            action=display_action(action, options.get(action)),
        )
        if (action == "a" and not overworld and not state.in_battle
                and getattr(state, "screen_cursor", None) is None):
            from .dialogue_capture import before_advance
            before_advance(self, state, frame)
            action = self.dialogue.advance(state, frame)
        if decision.fell_back:
            self.pause(f"{self._provider_label()} unavailable: {decision.reason}. Retry to reconnect.")
            self.provider_health = "unavailable"
            self.provider_health_error = decision.reason
            self._set_provider_event(self.pause_reason)
            return None
        elif decision.option != "wait":
            source = self._provider_label() if decision.request_made else "Executor (only legal action)"
            self._set_provider_event(f"{source} chose {action}")
        self.action_source = (self._provider_label() if decision.request_made
                              else "deterministic execution")
        if strategy_active:
            self.strategy.chosen(action)
        if action != "wait":
            self.wait_streak = 0
        if action == "a":
            self.interaction_positions.add(position)
        adjacent_sprite = any(
            abs(entity.pixel_x - state.x * 16) +
            abs(entity.pixel_y - state.y * 16) == 16 for entity in entities
        ) if state.x is not None and state.y is not None else False
        if action == "a" and adjacent_sprite and overworld and self.save_encounter:
            path = self.save_encounter()
            if path:
                self.memory.checkpoint(path)
                self.encounter = {"checkpoint": path, "species_id": None,
                                  "species": "", "map": key, "started": False}
                self.pending_frames = 90
        self.last = (key, position, action)
        self.held_action = None if action == "wait" else action
        self.cooldown = (_MOVE_HOLD_FRAMES if action in _STEPS
                         else _MENU_COOLDOWN_FRAMES)
        if state.in_battle or not overworld:
            self.screen_note = None
            self.vision_key = None
        return None if action == "wait" else action
