# Review 1: jev-plays-pokemon CONTEXT.md

## Findings, most severe first

**1. BLOCKER — nav.py (§3, §6 task 3) is a pathfinding engine v0.1 never earns.**
The occupancy map keyed by `(map_id, x, y)`, warp-edge learning, and BFS are built
to solve repeat traversal of a map that's being discovered. But v0.1's route is one
linear pass through five fixed maps whose connections are static and already public
(`map_constants.asm`) — the map never "fills in" because you don't revisit it. Worse,
the doc's own logic works against itself: BFS returns nothing until the local area is
explored, and "no path" is defined as a Jev branch. On a first-and-only playthrough
that means most overworld steps are unmapped frontier, so Jev steers constantly —
the opposite of the "calls per minute drop" claim in §3, and it inflates decision
count in a way that muddies the "speed" number the whole differentiator rests on.
Neither `02` §5 nor `03` §5 (the cited research) proposes this design; it's original
scaffolding nobody asked for. Fix: hardcode the four goals' waypoint sequence (already
half-specified in the §2 goal table as "a map id, optionally a tile") and use
`game_area_collision()` only for single-screen local dodging. Keep Jev only for a
tile-level tie that local collision data can't resolve. This is smaller, matches
"fewest files that work" (SHARED.md), and doesn't need `test_nav.py`'s hand-built
grids, stall detection, or warp-graph persistence at all.

**2. CONCERN — "Speed" differentiator (§1) isn't measured against the named incumbents.**
SHARED.md requires "the differentiator against the named incumbents" (its own §
"What each CONTEXT.md must contain," item 1). The two named Pokemon incumbents are
milanboers/jev-plays-pokemon and anxkhn/JevPlaysPokemon — both presumably also call
Jev at ~100ms, since that's the platform's latency, not this repo's achievement. The
actual comparison in §1 is against Claude Plays Pokemon, an unrelated Opus-based
product in a different niche. That's a fine marketing hook (people have heard of it)
but it is not a differentiator against the repos this project must actually beat.
Fix: say so plainly — lead the in-niche case with the RAM harness and calibration
(items 2 and 3, which do cite the real incumbents), and frame speed as "vs. the
famous version of this idea," not vs. the two GitHub competitors.

**3. CONCERN — launch order contradicts SHARED.md.**
SHARED.md's launch order: "...Pokemon when the stream is ready." §8 here launches
v0.1 without a stream (Twitch is explicitly a v0.2 non-goal per §2) and instead gates
on "once the run is stable." That's a reasonable call, but it silently overrides the
parent contract's stated gate rather than flagging the change. Fix: note the
deviation explicitly (one line) so the user signs off on launching without the
stream, rather than leaving it as an implicit reinterpretation.

**4. CONCERN — `wBattleResult` union hazard (§2 goal table) isn't handled, only address-verified.**
`00c` §E flags `wBattleResult` by name as sitting in a WRAM union: the same address
serves a different purpose depending on game state. §6 task 1 promises to verify
battle-block *addresses* against a generated `.sym`, which confirms the address is
right but not that reading it late is safe. The `win_lab_rival` predicate
(`EVENT_BATTLED_RIVAL_IN_OAKS_LAB` set and `wBattleResult == 0`) is evaluated every
tick per the goal-stack model in §3; if checked after the union slot gets reused post-battle
for an unrelated purpose, it can read garbage. Fix: latch `wBattleResult` once, on the
tick `wIsInBattle` transitions from a battle value to 0, not on every subsequent tick.

**5. CONCERN — the Brier target is presented as both settled and open.**
§1 states as fact "every turn we also ask a noul: does this action keep the party
alive" and §4's example JSON bakes in `avoids_wipeout` as the request shape. §9 Q1
then treats the same choice as unresolved and flags that a ~0.95 base rate makes the
headline look good for the wrong reason — the exact gaming risk the reviewer was
asked to check for. Since `policy.py` (task 6) and `measure` (task 9) are both built
around whichever noul wins, resolve Q1 before task 4, not after the request shape is
already fixed in the doc.

**6. NIT — legal section (§2) asserts rather than cites precedent.**
"Symbol tables and address lists are facts about the game, not the game" is the
correct position but reads as an assertion. `pret/pokered` itself has published
symbol tables and disassembly without ROM bytes for years without a takedown — one
clause citing that would move this from asserted to reasoned, for free.

## Verified against source
- Map ids: `PALLET_TOWN $00`, `VIRIDIAN_CITY $01`, `REDS_HOUSE_1F $25`, `OAKS_LAB $28`,
  `ROUTE_1 $0C` — all match `pret/pokered/constants/map_constants.asm` exactly.
- Event flags: `EVENT_GOT_STARTER`, `EVENT_BATTLED_RIVAL_IN_OAKS_LAB` both exist in
  `constants/event_constants.asm`.
- WRAM labels: `wCurMap`, `wYCoord`, `wXCoord`, `wPartyCount`, `wObtainedBadges`,
  `wEventFlags`, `wIsInBattle`, `wBattleResult`, `wCurrentMenuItem`, `wMaxMenuItem` all
  exist in `ram/wram.asm`, consistent with the addresses `03-prior-art.md` cites from
  `PokemonRedExperiments`.

## Keep as is
- Synthetic RAM fixture and its stated limit ("cannot catch a wrong address") — the
  right call given the legal constraint, and honestly disclosed in the README skeleton.
- Decoder-as-importable-package left as an open question (§9.3) rather than shipped as
  a separate package before anyone's asked — correct application of "no abstraction
  before a second concrete use."
- Escape hatches, code-owned arithmetic/type-effectiveness, single-turn-only questions,
  and the base-rate-next-to-Brier discipline in `measure` — all match SHARED.md's
  design rules and the jaggedness mitigations are concrete and testable.
