# Launch copy

Nothing here goes out until a ROM run exists. Every number in this file is measured but
provisional: n=20 calls through the gateway shim over synthetic RAM with no emulator
attached, not the direct API and not a real playthrough.

## The measurement problem with the current hook

CONTEXT section 1 and section 8 both say the model "decides in about a hundred
milliseconds". Measured over 20 real calls, it does not:

```
1.25 decisions/sec, $0.1601/hour (n=20 Jev calls over 1 run, synthetic RAM,
  call latency only, no emulator)
Brier 0.1532 on faints_this_turn (n=10 turns, base 0.2, constant-predictor 0.16,
  95% CI 0.059-0.2474)
```

Per call that is about 800 ms, range 530 to 1236.

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

1.25 decisions/sec, $0.16/hour. Brier 0.153 on "will my Pokemon faint this
turn" (n=10, base rate 0.20, constant predictor 0.16).
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

Brier 0.153 on n=10 turns, 95% CI 0.059 to 0.247. The constant predictor scores
0.16. That interval straddles it, so I have not shown I beat "always guess the
base rate". n=10 is far too small to claim anything, and the README says so.

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
