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
uv run jpp notes --run-id run-001
uv run jpp notes --run-id run-001 --json
uv run jpp notes --run-id run-001 --output 'data/notes'
```

These commands open the database read-only. The output includes historical data;
it does not claim to describe the current running process.

## What survives a restore

- World facts, dialogue clues, maps, and route state follow the checkpoint.
- The experience journal and failed-attempt records survive restores and restarts.
- Failed attempts are scoped to the goal and observed dialogue/progress evidence.
  Normal planning excludes matching failures. The recovery policy can recheck
  old approaches when alternatives are exhausted; these rechecks are recorded.
  Manual Retry explicitly releases current failure constraints and logs that choice.
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
uv run jpp benchmark --rom 'Gold 97 Reforged v6.1c.gbc' \
  --state 'data/checkpoints/your-snapshot.state' --database 'data/jev.sqlite' \
  --run-id run-001 --provider executor --repeats 2 --output 'runs/baseline'

uv run jpp benchmark --rom 'Gold 97 Reforged v6.1c.gbc' \
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
