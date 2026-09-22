"""Gold97 controller provider responsibilities."""

from time import monotonic

class ProviderLifecycle:
    def _tactical_usage_provider(self):
        provider = getattr(self.policy, "provider", None)
        return getattr(provider, "usage_provider", "jev")


    def _provider_label(self):
        return self._tactical_usage_provider().title()


    def _start_provider_health_check(self):
        health = getattr(getattr(self.policy, "provider", None), "health", None)
        if not callable(health):
            self.provider_health = "ready"
            return
        if self.provider_health != "ready":
            self.provider_health = "checking"
        self.provider_health_error = ""
        self.provider_health_future = self.executor.submit(health)


    def _set_provider_event(self, message):
        self.provider_events.append(str(message)[:180])


    def pop_provider_event(self):
        return self.provider_events.popleft() if self.provider_events else None


    def _poll_provider_health(self):
        if (self.provider_health_future is None and self.provider_health == 'unavailable'
                and self.playback.requested and monotonic() >= self.playback.retry_at):
            self.playback.status = 'recovering'
            self._start_provider_health_check()
        if (self.provider_health_future is None and self.provider_health == "ready"
                and monotonic() - self.provider_health_checked_at >= 10):
            self.provider_health_checked_at = monotonic()
            self._start_provider_health_check()
        if self.provider_health_future is None or not self.provider_health_future.done():
            return
        future, self.provider_health_future = self.provider_health_future, None
        self.provider_health_checked_at = monotonic()
        try:
            result = future.result()
            if not isinstance(result, dict) or result.get("status") != "ok":
                raise RuntimeError("sidecar health response was not ok")
        except Exception as exc:
            self.provider_health = "unavailable"
            self.provider_health_error = f"{type(exc).__name__}: {exc}"
            if self.playback.status != 'blocked':
                self.playback.waiting(self.provider_health_error)
            self._set_provider_event(f"{self._provider_label()} unavailable: {self.provider_health_error}")
            # Verified opening goals and single-option dialogue do not require
            # the tactical sidecar. A later multi-option request will still fail
            # closed through the normal provider error path.
            return
        self.provider_health = "ready"
        self.provider_health_error = ""
        if self.playback.requested and self.playback.status in {'recovering', 'waiting for provider'}:
            self.paused = False
            self.pause_reason = ''
            self.strategy.invalidate()
            self.playback.ready()


    def _screen(self, state, frame):
        if self.vision is None or not self.strategy.use_luna:
            return None
        key = (state.map_group, state.map_number, state.x, state.y,
               state.battle.kind, getattr(state.battle.opponent, "hp", None))
        if self.vision_future:
            if not self.vision_future.done():
                return None
            vision_error = ""
            try:
                note = self.vision_future.result()
            except Exception as exc:
                vision_error = f"{type(exc).__name__}: {exc}"
                self.strategy.provider_failed(
                    f"{self.strategy.label} screen reader: {type(exc).__name__}")
                self.live.vision_finished(error=vision_error)
                self.live.model_call("luna", status="error", error=str(exc), phase="vision")
                note = {"mode": "unknown", "screen_text": [],
                        "uncertainty": type(exc).__name__}
            if note and not vision_error:
                self.usage.record("luna", **(note.get("usage") or {}))
                self.live.vision_finished(note)
                self.live.model_call(
                    "luna", note.get("usage"),
                    (self.live.vision or {}).get("model_input"), phase="vision",
                )
            if self.vision_key == key and note:
                expected = "battle" if state.in_battle else "overworld"
                if state.in_battle and note["mode"] != expected:
                    note = None
                self.screen_note = note
                if note and note["mode"] == "dialogue":
                    self.memory.remember("clue", " ".join(note["screen_text"]),
                                         f"{state.map_group:02X}:{state.map_number:02X}")
                if note:
                    visible = " ".join(note.get("screen_text") or []).strip()
                    self._set_provider_event(
                        f"{self.strategy.label} read {note['mode']}: {visible or '(no text)'}"
                    )
            self.vision_future = None
        if self.paused:
            return None
        if self.screen_note and self.vision_key == key:
            return self.screen_note
        if frame is None:
            self._set_provider_event("Screen unavailable; advancing")
            return {"mode": "unknown", "screen_text": [],
                    "uncertainty": "no frame"}
        self.vision_key = key
        self.screen_note = None
        model_input = getattr(self.vision, "model_input", None)
        if callable(model_input):
            payload = model_input(frame)
            self.latest_model_input = {"provider": self.strategy.label, **payload}
            self.live.vision_started(frame, payload)
            self._set_provider_event(f"{self.strategy.label} input · screen + image")
        self.vision_future = self.executor.submit(self.vision.describe, frame.copy())
        return None


    def pause(self, reason):
        self.memory.experience.interrupt(reason)
        self.live.result(reason)
        if 'unavailable' in reason and reason.startswith(('Laya', 'Jev')):
            self.provider_health = 'unavailable'
            self.playback.waiting(reason)
        else:
            self.playback.blocked(reason)
        self.strategy.invalidate()
        self.paused = True
        self.pause_reason = reason
        self.held_action = None

        self.export_notes('pause')


    def export_notes(self, reason='manual'):
        from .notebook import export_notebook
        try:
            return export_notebook(self, reason)
        except OSError as exc:
            self._set_provider_event(f'Notes export failed: {type(exc).__name__}')
            return None


    def resume(self):
        self.dialogue.reset()
        self.dialogue_choice = None
        self._battle_reset()
        self.capture = None
        self.playback.request(True)
        self.strategy.invalidate()
        self.strategy.observations.pending = None
        self.strategy.failures = 0
        self.strategy.excluded.clear()
        self.strategy.rechecked_positions.clear()
        self.paused = False
        self.pause_reason = ""
        self.stalls = 0
        self.cooldown = 0
        self.unknown_frames = 0
        if self.decision_future is not None:
            self.decision_future.cancel()
        self.decision_future = None
        self.decision_key = None
        self.title_bootstrap_done = False
        self.held_action = None
        self.interaction_positions.clear()
        self.interaction_map_key = None
        self.live.decide(
            kind="state",
            source="Observed game state",
            why="AI control resumed",
            action="Read current game state",
        )
        if self.provider_health == "unavailable":
            self._start_provider_health_check()
