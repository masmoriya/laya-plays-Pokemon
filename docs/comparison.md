# Head to head

Read 2026-09-18 against a shallow clone of each repo. Numbers we did not measure are
written as "not run", never estimated.

## milanboers/jev-plays-pokemon

The only real head to head, and it is substantial work rather than a demo stub. MIT
licensed, 4,086 lines of Python outside its tests, of which 1,643 are vendored from
`NousResearch/pokemon-agent` (MIT, 175 stars) under `jev_plays_pokemon/vendor/`: a PyBoy
wrapper, a RAM walkability map, a Red/Blue memory reader and a structured-state builder.

What it does, from its README and its source:

- decodes dialog and menu text from the PyBoy tilemaps (`screen_text.py`)
- reads overworld object memory at `$C100`/`$C200` (`wSpriteStateData1`/`2`) to identify and
  locate nearby NPCs and items (`objects.py`)
- A* pathfinds over a live collision grid (`navigation.py`)
- plays the opening end to end: out of the house, to Oak, a starter, back into Pallet Town
- names its own weak spot: "battles are the current weak spot ... the first rival battle
  (and wild battles generally) are not reliable yet"

Question economy, the thing that actually differs:

| | when Jev is asked | questions per call | calls per turn |
|---|---|---|---|
| `milanboers/jev-plays-pokemon` | every turn | 1 goal choice + 8 action nouls + `menu_open` (`agent.py:208-242`), or the 9 nouls alone for a menu turn (`agent.py:244-258`) | 1, sometimes 2 |
| this repo | only at a branch | 1 choice over the legal options + 2 nouls (`src/jpp/policy.py`) | 1 |

Routine ticks here are pure code: a text box with no cursor, a step toward the next
waypoint, a cursor move inside a menu. That is the claim worth making, and it is a claim
about the shape of the question, not about who wrote more code.

It also flattens the goal distribution on purpose (temperature 2.0, floor 0.1) so a
confident pick fires 60-70% of the time. That is a deliberate anti-loop trade and it makes
its goal probabilities not directly comparable to a calibration number.

**Head to head on the same ROM: did not run.** No cartridge is available on this machine and
none will be downloaded. The command, for whoever has one:

```
uv run --directory /path/to/milanboers_jev-plays-pokemon python -m jev_plays_pokemon --rom red.gb
uv run jpp play --rom red.gb --headless --max-decisions 50 && uv run measure runs/run.jsonl
```

Both need a TypeSafe key. Compare decisions/sec only after writing down what a decision
means in each, since the two are not the same unit.

## anxkhn/JevPlaysPokemon

Gen 3, Pokemon Showdown, battles only, no overworld. Only battle decisions/sec is
comparable at all. Not run.

## Claude Plays Pokemon

Publishes no timing and no calibration. Seconds per action stays a stream observation, not
a measured comparison.

## Calibration

Neither incumbent publishes a Brier score, a reliability curve, or any accuracy number. As
of this writing neither do we: `uv run measure fixtures/runs/sample.jsonl` reports on
synthetic RAM and says so in its own output. The first real number needs a ROM.
