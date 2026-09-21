"""Observed-menu execution of battle actions, independent of tactical scoring."""
from .gold97_battle import BattleAction


from .gold97_battle_menus import party_step, root_step, heal_step


class BattleExecutor:
    def __init__(self):
        self.reset()

    def reset(self):
        self.action = None
        self.confirmed = None
        self.snapshot = None
        self.repeats = 0
        self.recovered = False
        self.error = None
        self.cancel_party = False
        self.phase = None
        self.before = None
        self.unresolved_turns = 0

    @staticmethod
    def signature(state):
        active, foe = getattr(state.battle, "active", None), state.battle.opponent
        return (getattr(state, 'active_slot', None), getattr(active, 'hp', None),
                tuple(getattr(active, 'pp', ())), getattr(foe, 'hp', None),
                getattr(foe, 'species_id', None), getattr(state, 'potion_count', 0),
                tuple(getattr(active, 'stages', ())), tuple(getattr(foe, 'stages', ())),
                getattr(active, 'status', None), getattr(foe, 'status', None),
                getattr(state, 'poke_ball_count', None))

    def step(self, owner, state):
        if getattr(state, 'mechanics_verified', True) is False:
            owner.pause('Cartridge battle tables do not match the supported mechanics')
            return None
        active = getattr(state.battle, 'active', None)
        # The battle RAM struct is briefly unavailable during trainer send-out
        # and on some emulator frames.  That must not disable local execution:
        # the party/active-slot projection is sufficient to choose and confirm
        # a move, and does not depend on Luna's screen reader.
        if active is None:
            party = tuple(getattr(state, 'party', ()) or ())
            slot = getattr(state, 'active_slot', None)
            candidate = (party[slot] if slot is not None and 0 <= slot < len(party)
                         else next((mon for mon in party if getattr(mon, 'hp', 0) > 0), None)
                         if party else None)
            if candidate is not None:
                if getattr(candidate, 'hp', None) is not None:
                    active = candidate
        menu = getattr(state, 'battle_menu_kind', None)
        cursor = getattr(state, 'battle_menu_cursor', None)
        lines = tuple(getattr(state, 'screen_lines', ()) or ())
        text = ' '.join(' '.join(lines).upper().split())
        signature = self.signature(state)
        frame = (menu, cursor, getattr(state, 'screen_cursor', None), lines, signature)
        self.repeats = self.repeats + 1 if frame == self.snapshot else 0
        self.snapshot = frame
        if self.repeats > 90:
            owner.pause('Battle menu did not progress after recovery')
            return None
        if self.repeats > 45 and not self.recovered and menu in {'moves', 'party'}:
            self.recovered = True
            self.action = None
            self.confirmed = None
            return 'b' if active and active.hp > 0 else None
        # A freshly drawn menu may reject the first tap before input is ready.
        # Retry only after six unchanged observations, with a bounded deadline.
        if self.repeats and self.repeats % 6 == 0 and menu in {'command', 'moves', 'text', 'switch_prompt', 'forced_prompt', 'party_action', 'party'}:
            self.confirmed = None
            if menu == 'party':
                owner.battle_switch_phase = None
        resolved = self.before is not None and signature != self.before
        if self.action and self.action.kind == 'switch' and self.before is not None:
            resolved = (getattr(state, 'active_slot', None) == self.action.target
                        and menu != 'party')
        if self.action and self.action.kind == 'heal' and self.before is not None:
            resolved = getattr(state, 'potion_count', 0) < self.before[5]
        if self.action and self.action.kind == 'ball' and self.before is not None:
            resolved = menu == 'command' and signature[-1] != self.before[-1]
            if resolved:
                owner.battle_strategy.capture_attempts = getattr(owner.battle_strategy, 'capture_attempts', 0) + 1
        if resolved:
            self.unresolved_turns = 0
            self.confirmed = None
            self.before = None
            self.action = None
            self.phase = None
            self.recovered = False
            owner.battle_switch_phase = None
        if 'ALREADY OUT' in text or any(word in text for word in ('NO WILL', "CAN'T", 'CANNOT')):
            if self.error != text:
                self.error = text
                self.cancel_party = 'ALREADY OUT' in text or bool(active and active.hp > 0)
                self.action = None
                self.confirmed = None
                return 'a'
            return None
        self.error = None
        if self.cancel_party and menu == 'party':
            self.cancel_party = False
            self.action = None
            owner.battle_switch_phase = None
            return 'b'
        if active is None:
            # Trainer introductions must advance before the active battle struct
            # is populated. A visible text page is not an attack/menu choice.
            if menu == 'text' and text:
                if self.confirmed == frame:
                    return None
                self.confirmed = frame
                return 'a'
            owner._set_provider_event('Waiting for readable battle state')
            if self.repeats > 45:
                owner.pause('Battle state remains unreadable')
            return None
        if menu in {'switch_prompt', 'forced_prompt'}:
            if self.confirmed == frame:
                return None
            self.action = owner.battle_strategy.plan(state, optional=menu == 'switch_prompt',
                                                     forced=menu == 'forced_prompt')
            owner._set_provider_event(self.action.reason)
            answer = 'YES' if self.action.kind == 'switch' else 'NO'
            row = next((i for i, line in enumerate(lines) if line.strip().upper() == answer), None)
            screen_cursor = getattr(state, 'screen_cursor', None)
            if row is None or screen_cursor is None:
                return None
            if screen_cursor[1] != row:
                return 'down' if screen_cursor[1] < row else 'up'
            self.confirmed = frame
            return 'a'
        if menu == 'party_action':
            if cursor is None or self.confirmed == frame:
                return None
            if self.action is None or self.action.kind != 'switch':
                return 'b'
            row = next((i for i, line in enumerate(lines) if 'SWITCH' in line.upper()), None)
            if row is None:
                return None
            if cursor[1] != row:
                return 'down' if cursor[1] < row else 'up'
            self.confirmed, self.before = frame, signature
            return 'a'
        if menu == 'party':
            if self.confirmed == frame or owner.battle_switch_phase == 'wait':
                return None
            if self.action is None or self.action.kind not in {'switch', 'heal'}:
                if active.hp > 0:
                    return 'b'
                self.action = owner.battle_strategy.plan(state, forced=True)
            if self.action.target is None:
                owner.pause(self.action.reason)
                return None
            button = party_step(cursor, self.action.target)
            if button == 'a':
                self.confirmed, self.before = frame, signature
                owner.battle_switch_phase = 'wait'
            return button
        if menu == 'text':
            if self.action and self.action.kind == 'ball':
                from .gold97_capture import ball_step
                return ball_step(self, state, lines, frame, signature)
            if self.action and self.action.kind == 'heal':
                return heal_step(self, state, lines, frame, signature)
            if self.confirmed == frame:
                return None
            self.confirmed = frame
            return 'a'
        if menu == 'command':
            if self.confirmed == frame:
                return None
            if self.phase == 'resolve' and self.before == signature:
                # Returning to a command menu proves the prior turn ended,
                # including flinches, sleep and fully blocked moves.
                self.action = None
                self.before = None
                self.phase = None
                self.unresolved_turns += 1
                if self.unresolved_turns >= 8:
                    owner.pause('Repeated battle actions produced no observable progress')
                    return None
                if self.unresolved_turns == 4:
                    owner._set_provider_event('Re-reading battle after unresponsive actions')
                    return 'b'
            if self.action is None or self.phase == 'resolve':
                self.action = owner.battle_strategy.plan(state)
            owner._set_provider_event(self.action.reason)
            if self.action.kind == 'wait':
                return None
            target = {'switch': (2, 1), 'heal': (1, 2), 'ball': (1, 2), 'escape': (2, 2)}.get(self.action.kind, (1, 1))
            button = root_step(cursor, target)
            if button == 'a':
                self.phase = 'move' if self.action.kind in {'move', 'struggle'} else self.action.kind
                self.confirmed = frame
                if self.action.kind == 'escape':
                    self.before, self.phase = signature, 'resolve'
                owner.battle_target = self.action.target
            return button
        if menu == 'moves':
            if self.confirmed == frame:
                return None
            if self.action is None:
                self.action = owner.battle_strategy.attack(active, state.battle.opponent)
            if self.action.kind not in {'move', 'struggle'}:
                return 'b'
            if cursor is None:
                return None
            if self.action.target is not None and (
                    self.action.target >= len(active.pp) or active.pp[self.action.target] <= 0):
                self.action = owner.battle_strategy.attack(active, state.battle.opponent)
            slots = getattr(active, 'move_slots', ())
            target = self.action.target
            row = slots[target] if slots and target is not None else target
            if row is not None and cursor[1] - 1 != row:
                return 'down' if cursor[1] - 1 < row else 'up'
            self.confirmed, self.before, self.phase = frame, signature, 'resolve'
            owner.battle_target = target
            return 'a'
        # Older adapters without visible menus retain cursor navigation, but
        # never invent a button when neither a menu nor a cursor is available.
        if menu is None and cursor:
            if self.phase is None:
                self.action = owner.battle_strategy.attack(active, state.battle.opponent)
                button = root_step(cursor, (1, 1))
                if button == 'a':
                    self.phase = 'move'; owner.battle_target = self.action.target
                return button
            if self.phase == 'move':
                target = self.action.target
                if target is not None and cursor[1] - 1 != target:
                    return 'down' if cursor[1] - 1 < target else 'up'
                self.phase = 'resolve'
                return 'a'
        return None

