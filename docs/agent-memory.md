# Agent memory and progress

The live dashboard's **Notes** button opens a searchable notebook and pauses
autonomous play. Escape closes the notebook; Play resumes. Now shows the current
goal and plan. Learned shows checkpoint-owned observations and their sources.
Attempts shows failure reasons and the durable action/outcome journal. Refresh
loads a new snapshot. Export writes Markdown and JSON under `data/notes/`.

Summaries are also exported at observed milestone changes, pause, and exit.
They are deterministic projections of recorded evidence, not invented model
thoughts. Manual milestone confirmations are counted separately. A changed
screen, coordinate, or HP value is an observation, not proof of story completion.

Inspect memory without starting the emulator:

```sh
uv run lpp notes --run-id run-001
uv run lpp notes --run-id run-001 --json
uv run lpp notes --run-id run-001 --output 'data/notes'
```

These commands open the database read-only. The output includes historical data;
it does not claim to describe the current running process.

## What survives a restore

- World facts, dialogue clues, maps, and route state follow the checkpoint.
- The experience journal and failed-attempt records survive restores and restarts.
- Failed attempts are scoped to the goal and observed dialogue/progress evidence.
  Planning and recovery exclude matching failures. Relevant new evidence can
  release an approach; Manual Retry explicitly releases current failure
  constraints and logs that choice.
- Reward accounting remains separate and does not update model weights.

Laya receives a compact selection of failed attempts, the current objective, and
the plan. Packing uses the loaded model's actual tokenizer and context limit.
The Input view includes the retained payload, token budget, and omitted fields.
If essential screen/state fields cannot fit, the request fails visibly. Large
history is retrieved selectively; adding more stored notes cannot enlarge the
model's context window.

Restart the game process and its Laya sidecar to load these changes. Existing
sidecars lacking packing metadata are rejected for journey decisions, rather
than silently using their old truncation behavior. Saves are preserved.

Luna uses its provider deadline, currently 60 seconds, instead of a separate
five-second cutoff. Map/goal changes still invalidate pending plans. Retired
answers cannot take control. Requests, accepted plans, and timeouts are journaled.

## Measure changes using real checkpoints

```sh
uv run lpp benchmark --rom 'Gold 97 Reforged v6.1c.gbc' \
  --state 'data/checkpoints/your-snapshot.state' --database 'data/jev.sqlite' \
  --run-id run-001 --provider executor --repeats 2 --output 'runs/baseline'

uv run lpp benchmark --rom 'Gold 97 Reforged v6.1c.gbc' \
  --state 'data/checkpoints/your-snapshot.state' --database 'data/jev.sqlite' \
  --run-id run-001 --provider laya --modes off on --repeats 3 \
  --frames 18000 --seconds 120 --output 'runs/laya-comparison'
```

The runner copies the ROM and only relevant agent database rows into temporary
storage, restores the selected checkpoint, and never writes the player's save.
The database must contain matching checkpoint memory. Omit `--database` only for
an intentionally fresh-memory comparison. Use a new output directory per comparison.

The executor baseline stops at a choice requiring a model. It never substitutes
made-up model answers. Laya/Jev and Luna-enabled modes use real configured providers;
their normal account usage applies. `CODEX_MODEL` selects the planner model.

`comparison.json` records ROM/checkpoint hashes, budgets, mode, model configuration,
new verified milestones, event-count deltas, provider usage, and stop reason. Each
run has an action JSONL file. Historical milestones and reward points are not
counted as new benchmark progress. Frame and wall-clock budgets bound the play
loop; provider operations may finish after the loop's deadline while shutting down.

Compare repeated runs at equal budgets. A short checkpoint smoke check is not
evidence of full-game autonomy or superiority over another model.

## Battle confidence

The cartridge-specific move/type profile remains authoritative. Nominal damage
can rank attacks, but does not establish a safe knockout, profitable setup, or
deliberate sacrifice while weather, screens, and volatile effects are unverified.
Those strong decisions now require bounded estimates. Full modifier decoding
and cartridge differential coverage remain future mechanics work.


## Exploration and unresolved objects

The navigation grid and artwork now share checkpoint-owned discovery data.
Only coherent overworld viewport observations reveal terrain and objects. A
visible doorway is an unknown destination until a recorded traversal identifies
it. Previously verified movement edges remain usable without inventing terrain
imagery. Older saves start with unknown imagery outside newly observed cells.

Items, conversations, trainer victories, and obstacles have separate outcomes.
Manual dialogue is attached to the faced object when that identity is observable;
otherwise it remains a location-based clue. A cart's movement hint remains
unresolved after closing the text. Item collection requires pickup confirmation,
not disappearance from the viewport or an attempted button press.

The exact-build object decoder uses the supported ROM's map-object records at
`D6FC` and item-ball sprite `4E`. The hexadecimal comments in the pinned
[sprite constants](https://raw.githubusercontent.com/SoupPotato/gold97/976507f9e6e605050384e9ec12e9651988ae7c46/constants/sprite_constants.asm)
are stale; the sequential declarations and real checkpoint objects establish
these sprite values. Object IDs remain stable across item/NPC classification.

Reachable items and obstacles receive bounded investigation before ordinary
exits. Interaction, approach, and field-action attempts are tracked separately,
with two attempts per unchanged evidence state. Party moves, pickup evidence,
object position, or new local dialogue can reopen an experiment. Field moves
are selected through visible menus; selecting one is not proof of success.
Three repeated transitions without new evidence exhaust that exit's budget.
Necessary prerequisite and healing routes remain available. The notebook shows
object outcomes and attempts; exhausted exploration reports its blocker.

Restart the running game process to load these changes. Existing saves are
preserved. Focused regressions cover fog, independent pickups, manual cart clues,
trainer outcomes, field menus, retries, and transition budgets. Isolated real
mine replays confirmed an X Attack pickup and retention of the cart clue; they
do not establish a solved Strength puzzle or a completed missing-child rescue.


### Movement continuity and last-seen markers

Accepted routes execute their single legal next step locally. Directional input
stays held along a verified continuation, then releases for a turn, target,
object, warp, dialogue, or battle. New route choices still use the configured
policy. Exploration no longer depends on having recorded the opening milestones.

Each map retains a recent movement trail and directed-edge traversal counts.
Repeated edges become more expensive when no new evidence has appeared, but
remain traversable for necessary returns. Failed or exhausted exploration
targets retain their attempt budget across planner resets. The map draws the
trail and distinct NPC, item, obstacle, and unknown-object markers. Outlined
markers are last-seen positions, not claims that a moving NPC is still there.
Partially visible objects are remembered without revealing unseen terrain.

An explicitly restored checkpoint can recover its exact recorded notebook when
opened through a path alias or another run label. Conflicting or missing
checkpoint records do not import unrelated run history. A separately restored
Journey checkpoint keeps its route if the agent notebook has no matching record.


### Ladder landing and restart recovery

Observed portals are terminal nodes in route searches: walking to an item or
viewpoint cannot silently route through a ladder. Landing on a portal still
allows stepping off it. If local leads are exhausted, returning through that
portal explicitly steps off and re-enters, under the same transition budget.
Exploration considers camera viewpoints across walls. Target selection uses
trail costs; committed execution uses a stable shortest path so new traversal
penalties do not reverse an active route. Same-map stairs are recorded even
without an active autonomous target.

Live checkpoints synchronize the UI route before writing agent memory. The
exact Journey snapshot is authoritative on restore, including manual Undo;
normalized checkpoint paths and run-label aliases recover that same snapshot.
A blocked summary describes objects on the current map rather than a distant
cart.

The isolated `runs/ladder-stable-route-20260921` replay starts on B4F at (19,15).
It ran 12,000 frames, left the landing, observed new terrain, and did not repeat
the B4F/B3F ladder pair. Journey remained at step 12. It still recorded eight
route recoveries elsewhere; this bounded run does not prove all loops are
eliminated or that the girl was rescued. Player save files were not modified.

### Shared Qwen planning and navigation outcomes

Qwen plans in the background while Laya selects eligible local investigations or
continues a committed route. Replies are checked against the current map,
objective, relevant evidence, and reachability before controlling movement.
Retired, rejected, and accepted requests have journal entries. A single mapped
travel target executes locally without spending a Qwen request on an absent choice.

Navigation failures no longer expire after a minute or automatically reopen when
recovery runs out of alternatives. Adjacent entrances to the same gate share
cycle history; tile collision failures remain specific. Relevant objective or
capability evidence can reopen an attempt; explicit Retry clears its constraints.
Exhausted navigation reports the last local failure. Observed unknown exits retain
their destination after a recorded traversal, without treating planned travel as
proof of arrival.

Both models receive a protected compact navigation summary: objective, arrival,
current approach, local failures, recent action outcomes, and unresolved leads.
The notebook retains the full history. Context diagnostics report what was kept
and omitted. This changes retrieval and control, not model weights.

Recent executed moves remain visible below vision, with observed outcomes and
selection ownership. Qwen explanations remain attributed suggestions, separate
from learned facts. Restart the game and Laya sidecar to load this implementation;
the sidecar must report context packing version 2. Player saves are unchanged.

### General progress and HM preparation

Exit retry budgets now depend on completed milestones, field capabilities, and
verified object outcomes. Camera discoveries and dialogue fragments cannot reset
cave-entry budgets, and prerequisite labels cannot bypass exit or waypoint limits.
Exploration waypoints may reopen when new terrain is observed; safety retreats remain
available. The same rules apply across maps rather than identifying a particular route.

Both Qwen and Laya receive a compact progress contract: the current task, observable
completion condition, repeated exits, and the actual HM preparation blocker. Laya
retains Qwen's accepted strategy before optional history, within the loaded model's
native token budget. Overworld graphics are not submitted as dialogue or recorded as
completed movement outcomes.

HM preparation distinguishes a compatible party member, verified boxed learner,
missing badge, and missing eligible capture. A boxed learner can justify a Center PC
transfer without a previous battle loss, preserving existing field users. Compatible
eligible wild encounters are remembered as observed search locations; no species or
encounter location is invented. Capture safety and the existing collection policy
remain in force. These are explicit memory and execution rules, not model fine-tuning.
