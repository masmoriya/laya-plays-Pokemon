# Journey strategy

The dashboard and Gold 97 controller share the same Journey progress object.
Luna strategy is enabled by default for new runs. The footer toggle persists per
run and disables **both** planning and screen reading. Already-running responses
are ignored after toggling; confirmed usage from those requests is still counted.
Learned facts remain available in both modes: this is a same-run comparison.

Luna chooses among reachable investigations. Laya receives the Journey goal,
current text, clues from other maps, NPC coverage, recent outcomes, and legal
controls for the selected investigation. With Luna Off, Laya chooses among the
available local investigations directly. Opening, healing, and battle executors
retain their existing rules and are labeled as deterministic execution.
Single legal controls also execute without a model request and are labeled as
executor actions; they do not increase Laya's call or token totals. Health checks
continue during these sequences so a disconnected sidecar is not hidden by them.

Plans update on discoveries, goal changes, completion, or failure. Exploration
targets cover several tiles instead of requiring a planning request every step.
Reachable NPCs take priority over departure. An interaction attempt is pending
until stable dialogue has been observed and closed. After two unsuccessful
attempts it is deferred; story changes make it eligible again. Stable tracked
sprite keys are preferred; raw OAM detections use approximate position matching.
That matching cannot establish a character's identity or guarantee perfect coverage.

The panel shows the goal, observed knowledge, and next investigation. Details
include conversation coverage and recent events. Per-mode progress and recovery
counts are persisted in `journey_strategy.stats`; they are descriptive, not a
controlled benchmark. No model-generated explanation can complete a milestone.
The exact-build Cut event can confirm Bill's gift; ambiguous story steps retain
the existing manual confirmation control.

Transient Laya failures retain Play intent and retry automatically with capped backoff.
Luna failures continue with Laya/local choices while retrying; Luna Off stays off.
Failed route recovery keeps Play active and seeks fresh reachable leads. Once those
are exhausted, it rechecks the oldest failed approaches without erasing experience,
or revisits reachable ground for new observations. With no reachable movement it
rechecks every two seconds, preserving collision checks and the current milestone.
Manual Pause cancels Play intent and pending actions. Restore, manual milestone changes, and mode changes invalidate
pending tactical and strategic answers. Recovery never automatically rewinds saves.
See [progress and recovery](laya-progress.md) for the reward ledger and bounded replays.

## Curated guidance

Guide hints are revealed only after reachable local NPCs and unexplored terrain
have been exhausted, and only for the exact cartridge fingerprint verified by the
adapter. Initial story guidance covers Bill's house in Pagota. Verified tower
return geometry remains a known navigation capability. Other story locations are
discovered through play; there is no complete hardcoded walkthrough.

The operator-requested Westport correction also exposes the verified ferry
prerequisite during step 11, including in lean tactical context. After Bugsy,
return from Route 103 through its gate to Westport, enter the port passage, use
the stairs, and ask the dock sailor for Teknos City. Route 103 instead leads to
Birdon; its Slowpoke disappear on `EVENT_BEAT_WHITNEY` (bit 1221), not on a
Westport Rocket event. The adapter reads that flag only for the verified ROM.
Prerequisite candidates still require reachable cartridge geometry or a visible
sailor. Necessary backtracking is exempt from the immediate-return penalty.
Step 11 completes on arrival in Teknos City, never from talking or choosing a
plan. Existing step IDs and saved completion sets remain unchanged.

- [Route 103 Slowpoke scripts](https://github.com/SoupPotato/gold97/blob/976507f9e6e605050384e9ec12e9651988ae7c46/maps/Route103.asm)
- [Westport ferry script and badge requirement](https://github.com/SoupPotato/gold97/blob/976507f9e6e605050384e9ec12e9651988ae7c46/maps/WestportPort.asm)

Sources are pinned to the existing verified source revision:

- [Pagota map events](https://github.com/SoupPotato/gold97/blob/976507f9e6e605050384e9ec12e9651988ae7c46/maps/PagotaCity.asm)
- [Bill's house script](https://github.com/SoupPotato/gold97/blob/976507f9e6e605050384e9ec12e9651988ae7c46/maps/BillsFamilysHouse.asm)
- [Story event flags](https://github.com/SoupPotato/gold97/blob/976507f9e6e605050384e9ec12e9651988ae7c46/constants/event_flags.asm)

The architecture also draws on [Milan Boers's Jev agent](https://github.com/milanboers/jev-plays-pokemon):
continuity belongs in remembered observations and outcomes, while concrete
navigation remains bounded by the game state. Routes and mechanics from Pokémon
Red are not imported into Gold 97.

## Validation limits

Focused contract tests cover outage gating, toggle cancellation, persistence,
NPC interaction outcomes, plan validation, guide gating, and loop recovery.
Real-cartridge snapshot inspection checks decoded geometry without changing the
user's save. Neither establishes a completed autonomous playthrough; that requires
connected providers and a bounded live replay.
