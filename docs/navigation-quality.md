# Navigation quality

The shared controller now prioritizes observed collectibles, keeps a reachable
route committed while background advice arrives, and measures real movement and
collection outcomes. The real checkpoint replays below improved collection and
reduced retracing. They did **not** verify a new story milestone or a complete game.

## What changed

- Item and resource collection survives the travel-route filter. An active walk
  can stop for a reachable pickup and then resume its previous local target.
  Emergency recovery retains priority.
- Approaches use actual shortest walking distances through observed terrain,
  including walls and objects. The nearest reachable collectible is handled
  first; the model still resolves meaningful choices.
- Late planner advice cannot reverse a still-valid committed route. New pickups,
  safety needs, completion, and invalidated paths can still trigger replanning.
- Arrival memory distinguishes the doorway just used from other exits. An
  immediate return is deprioritized while useful alternatives remain.
- Missing prerequisites no longer make every unexplored viewpoint look like
  objective progress. An acquisition detour needs evidence of a useful location.
- A single available action requires no background planner request. Headless
  inference waits no longer re-observe the same frozen frame, advance interaction
  timers, and rebuild context every polling interval.
- Historical object classification initializes once per loaded world and updates
  when evidence changes. Profiling found over four million redundant
  classifications in a short replay. Restore and fresh reward evidence have
  regression coverage; no overall speed increase is claimed from this change.
- The cartridge adapter identifies fruit trees as generic resource objects.
  Harvesting requires observed reward text; a description or full bag is not a
  pickup. Verified empty trees are resolved, and trees remain solid after harvest.

The priorities, commitment, path costs, and measurements operate on generic
targets and outcomes. No model was retrained and no route-specific button script
was added. The small resource adapter uses the pinned cartridge
[sprite definitions](https://github.com/SoupPotato/gold97/blob/976507f9e6e605050384e9ec12e9651988ae7c46/constants/sprite_constants.asm)
and [fruit-tree interaction outcomes](https://github.com/SoupPotato/gold97/blob/976507f9e6e605050384e9ec12e9651988ae7c46/engine/events/fruit_trees.asm).

## Real cartridge comparison

Both sides start from the same Route 117 checkpoint and frozen agent-memory
snapshot, with the real local Laya model and a 9,000-frame budget (about 151
emulated seconds). Background Qwen planning is disabled for this controlled
comparison. The baseline uses the pre-change control logic with the same new
measurement runner. This is one baseline run and two final-controller runs,
not a statistical estimate of full-game success.

| Measurement | Before | After, two final runs |
| --- | ---: | ---: |
| Walking steps | 150 | 165 / 174 |
| Unique observed positions | 97 | 163 / 173 |
| Repeated directed walking edges | 14 | 0 |
| Immediate reversals | 6 | 2 |
| Loop recoveries | 3 | 0 |
| New confirmed pickups, including harvests | 3 | 5 |
| Confirmed resource harvests | 0 | 2 |
| Newly verified story milestones | 0 | 0 |
| Measured overall speed | 2.52× | 2.37× / 1.63× |

Both final runs pass explicit requirements for five pickups, resolving observed
collectibles, and zero loop recoveries. Three preliminary replays also confirmed
five pickups, two harvests, and zero repeated directed edges. A separate real-cartridge executor test
collects three objects, including one resource, without model calls and stops at
the first choice requiring a model. It checks that the source checkpoint hash is
unchanged.

Final focused verification: **278 passed, 1 skipped**, including the real
cartridge collection replay, planner commitment, movement recovery, dialogue,
resource outcomes, checkpoint restore, and benchmark requirement checks. Scoped
Python syntax and diff checks also passed. No repository-wide type check or lint
was run. The two final model reports match the current Python-source hash.

More map transitions and more unique positions are not proof of story progress.
The new controller reaches additional previously visited areas and collects
resources; the missing capability and onward journey remain unverified. Its
observed-collection denominator also now recognizes trees that the old decoder
did not classify as collectibles. Neither denominator includes unseen or hidden
objects. Resource renewal on a later in-game day is not covered by these runs.

The raw reports are local, ignored run artifacts:

- `runs/navigation-laya-before-20260922/comparison.json`
- `runs/navigation-optimized-20260922/comparison.json` (two final runs, matching current source hash)
- `runs/navigation-laya-final-20260922/comparison.json` (two repeats)
- `runs/navigation-gated-20260922/comparison.json` (explicit success checks)
- `runs/navigation-collectibles-after-20260922/comparison.json` (executor repeats)

An earlier attempt using the shared live Qwen service experienced contention and
a long model wait. It is not used as evidence of full-stack improvement. The
asynchronous commitment behavior has focused regression coverage; an isolated
Qwen-enabled campaign is still needed.

## Reproduce and require success

Use a new output directory and a checkpoint with its matching agent-memory
database. The runner copies the ROM and run-owned database state into temporary
storage, loads the checkpoint, and stops the emulator without saving the ROM.
It records Python-source, ROM, checkpoint, and memory-snapshot hashes. The live
game and its checkpoint are not modified.

```sh
LAYA_BASE_URL='http://127.0.0.1:8865' LAYA_VISION='0' \
  '.venv/bin/python' -m jpp.cli benchmark \
  --rom 'Gold 97 Reforged v6.1c.gbc' \
  --state 'data/checkpoints/laya-tested-20260922T055211087034Z-encounter.state' \
  --database 'runs/navigation-source-20260922/baseline.sqlite' \
  --run-id 'laya-tested' --provider 'laya' --modes 'off' --repeats '3' \
  --frames '9000' --seconds '120' --speed '100' \
  --require-pickups '5' --require-observed-collection \
  --max-loop-recoveries '0' --output 'runs/navigation-next'
```

Port 8865 was a separate, real Laya sidecar for these tests. Start an isolated
sidecar there or change the URL to an available service. `--modes on` enables the
configured background planner; `off` retains real Laya decisions.

`--require-milestone '22'` requires milestone 22 to become newly verified during
the run. Existing completion and manual confirmations do not count. Combine
milestone, collection, and loop limits to define a scenario. Any failed
requirement exits with status 1. Without requirements the verdict is
`not_asserted`; merely reaching a frame or time budget does not mean success.

`--speed '100'` is an emulator ceiling, not a promise of 100× controller
throughput. Reports include measured speed and provider wait time. Preserve
one-frame action/outcome observations when optimizing; batching past dialogue,
warps, or interactions would invalidate the very coverage being tested.
Elapsed speed varies with local machine contention and inference. These runs
establish better observed navigation and collection, not faster whole-game play.

## What a complete-run claim still needs

1. **Entrance-aware world planning.** Route through observed connected areas and
   individual portals, not just map names. The current Route 117 walking area
   cannot reach its west edge, so a map-level route pointing west is insufficient.
   A tested speculative frontier ranking increased wandering and was removed.
2. **Explicit prerequisite plans.** Treat a missing traversal capability as an
   unresolved acquisition task with observed evidence, bounded attempts, and a
   verified outcome. Selecting another exploration point must not reset failure.
3. **A real checkpoint campaign.** Cover split maps, caves, doors, moving NPCs,
   blocked prerequisites, full inventory, resource renewal, interrupted dialogue,
   and planner latency. Require story progress as well as collection at each
   stage; repeat with the real planner enabled.
4. **A defined completion manifest.** Track expected mandatory milestones and
   optional collections separately. Hidden items require an explicit discovery
   policy and independently known coverage targets before claiming 100%.
5. **One uninterrupted, verified campaign.** Checkpoints isolate regressions;
   only a recorded full run can establish end-to-end completion for that run.

The general model can choose goals, interpret evidence, and resolve uncertainty.
Laya and deterministic tools can execute legal actions quickly, while observed
state verifies outcomes. This division does not require a Pokémon-specific model,
but it still needs a tested game adapter and explicit success criteria.
