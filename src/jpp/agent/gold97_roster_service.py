"""Route to an observed Center PC and execute one justified transfer at a time."""
from ..decode import Mon
from .gold97_pc import PCTransfer
from .gold97_roster import roster_plan
from .gold97_services import is_center, fully_recovered
from .gold97_navigation import STEPS
from .journey_targets import paths


class RosterService:
    def __init__(self, owner):
        self.owner = owner
        self.transfer = PCTransfer()
        self.target = None
        self.faced = False
        self.attempted = set()
        self.signature = None

    def step(self, state, overworld):
        if self.transfer.phase:
            button = self.transfer.step(state, overworld)
            if self.transfer.phase is None:
                self.target = None
                self.owner._set_provider_event('PC roster updated' if self.transfer.completed else self.transfer.error)
            return True, button
        if self.target:
            cell, direction = self.target
            if not overworld:
                return True, None
            if (state.x, state.y) == cell:
                if not self.faced:
                    self.faced = True
                    return True, direction
                if not self.transfer.start(state, self.plan):
                    self.target = None
                    return False, None
                return True, 'a'
            return True, self.owner._service_route(state, cell, 'Update team at the PC')
        if (not overworld or state.in_battle or not is_center(state) or
                not fully_recovered(state) or self.owner.terrain is None):
            return False, None
        failed_foe = self.owner.training.data.get('readiness_failure')
        from .hm_preparation import preparation
        hm = (preparation(state, self.owner.route.now, self.owner.memory)
              if getattr(state, 'owned_hms', ()) and getattr(state, 'storage_verified', False) else {})
        required_move = hm.get('move') if hm.get('action') == 'withdraw' else None
        # Routine healing does not justify rotating the team at the PC.
        if (not failed_foe and not required_move) or self.owner.recovery is not None:
            return False, None
        plan = roster_plan(state, Mon(**failed_foe) if failed_foe else None, required_move)
        if plan is None:
            return False, None
        self.signature = (tuple(m.identity for m in state.party),
                          tuple((m.identity,m.storage_box) for m in state.box_roster),
                          self.owner.route.now, str(failed_foe), required_move)
        if self.signature in self.attempted:
            return False, None
        terrain = self.owner.terrain
        reachable = paths(state, self.owner.memory, terrain)
        approaches = []
        for y in range(terrain.height):
            for x in range(terrain.width):
                if terrain.tile((x,y)) != 0x93:
                    continue
                # COLL_PC interactions face north; other sides are not actionable.
                cell = (x,y+1)
                if cell in reachable:
                    approaches.append(cell)
        if not approaches:
            return False, None
        self.attempted.add(self.signature)
        self.target = (min(approaches, key=lambda cell: abs(cell[0]-state.x)+abs(cell[1]-state.y)), 'up')
        self.plan, self.faced = plan, False
        return self.step(state, overworld)
