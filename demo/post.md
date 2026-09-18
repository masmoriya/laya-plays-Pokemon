# Launch copy

Nothing here goes out until a ROM run exists and the numbers below are re-measured. Every
number in this file is provisional: n=4 calls through the gateway shim, not the direct API.

## The measurement problem with the current hook

CONTEXT section 1 and section 8 both say the model "decides in about a hundred
milliseconds". Measured, it does not. Four fresh cassettes recorded 2026-09-18:

```
923.9 ms   885.8 ms   674.7 ms   861.1 ms
mean 836 ms   1.2 decisions/sec   $0.17/hour at 920 input tokens a call
```

That is through `tools/jev-proxy` to the Vercel gateway, so some of it is the shim. It is
still eight times slower than the claim. The direct API may well be faster, but until
someone measures it the post says "under a second", not "100 ms". The speed story does not
need the exaggeration: Claude Plays Pokemon deliberates for tens of seconds a move.

## X thread

**1, with clip a**

```
I gave Pokemon Red to a model that cannot write a sentence.

It picks from a menu in under a second, and I measured whether its confidence
means anything.

__ decisions/sec, $__/hour. Brier __ on "will my Pokemon faint this turn"
(n=__, base rate __, constant predictor __).
```

**2, with the payload still**

```
The bars are the whole point. Every battle turn, code reads WRAM into a typed
snapshot and hands the model a menu: four moves, a switch, an item. It returns a
probability for each one. That is the entire interface. It never plans a second
turn and it never writes prose.

Code owns everything that is not a branch: text boxes, waypoint steps, cursor
moves. The model only gets asked where the game actually forks.
```

**3, the caveat**

```
The calibration number is the part I would push back on if someone else posted it.

Brier __ on n=__ turns, 95% CI __ to __. The constant predictor scores __. If the
interval straddles that, I have not beaten "always guess the base rate" yet, and
the README says so.

Prior art: Claude Plays Pokemon is the famous one. milanboers/jev-plays-pokemon
got there first with Jev and plays more of the game than this does.

<repo link>
```

## Show HN

```
Show HN: Pokemon Red played by a model that only outputs probabilities, with a published Brier score
```

## Awesome list

For `~/Projects/mine/awesome-jev-typesafe`, under "Games, robotics and simulation", next to
the existing `JevPlaysPokemon` line:

```
- [<new name>](https://github.com/valentynkit/<new name>) - Pokémon Red on PyBoy where code owns the route and Jev is asked only at branches, with per-option probability bars and a published Brier score on "faints this turn".
```

The repo name is still open. `jev-plays-pokemon` is taken by milanboers.
