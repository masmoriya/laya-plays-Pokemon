# Review 2: jev-plays-pokemon CONTEXT.md (post-revision)

## Resolution of Review 1 findings

| # | Finding | Status | Why |
|---|---|---|---|
| 1 | nav.py/BFS over-engineered | Resolved | §3 is now a hardcoded waypoint list + single-screen `game_area_collision()` sidestep, tie-only branch. No `test_nav.py`, no warp graph. |
| 2 | Speed differentiator vs wrong incumbents | Resolved | §1 item 3 frames speed against Claude Plays Pokemon by name, leads with items 1-2 (harness, calibration) as the real in-niche case. |
| 3 | Launch order silently overrides SHARED.md | Resolved | §8 states the deviation explicitly, routes it to open question 1 for sign-off. |
| 4 | `wBattleResult` union hazard | Partially resolved | Latch-on-transition design fixes the hazard (confirmed: `end_of_battle.asm` zeroes `wIsInBattle` unconditionally but never touches `wBattleResult`, so the latched read is safe). But §2's value list for `wIsInBattle` is factually wrong — new finding 4. |
| 5 | Brier target settled vs. open contradiction | Resolved | §5 states "settled" once; §9 no longer lists it. Whether it's settled *correctly* is new finding 2. |
| 6 | Legal section asserts, doesn't cite | Resolved | §2 now cites pret/pokered by name, verbatim per the suggested fix. |

## New findings, ranked

**1. BLOCKER — `get_starter` waypoints and the goal table have the wrong starting map.**
Pokemon Red starts the player in `REDS_HOUSE_2F` ($26); you walk downstairs before ever seeing `REDS_HOUSE_1F`. Confirmed: `RedsHouse2F.asm` has one warp, `(7,1) -> REDS_HOUSE_1F` index 3. §2's goal table says "start is `$25` REDS_HOUSE_1F," and §3's `get_starter` list opens directly at `REDS_HOUSE_1F`, skipping the 2F stage entirely. Task 2's check compounds it: "watch `map` go `$25` to `$00`" will actually observe `$26 -> $25 -> $00`. Fix: add `REDS_HOUSE_2F` as the real start/first waypoint hop; correct the goal table and task 2's check.

**2. CONCERN — `faints_this_turn`'s sample-size case doesn't hold for v0.1's actual scope.**
§5 rejects wipeout because a run yields "maybe fifteen labels," picking `faints_this_turn` because "n grows into the hundreds." But v0.1 (§2) has exactly one scripted battle (lab rival) plus, at most, one or two incidental Route 1 wild encounters on a short direct walk — order of magnitude 10-30 turns, not hundreds. §1's placeholder (`n=463`) isn't plausible at this scope. The same bar used against wipeout arguably applies here too. Recompute the real expected n, or mark v0.1's Brier as preliminary.

**3. CONCERN — decisions/sec still lacks a pinned measurement method.**
§5: "decisions/sec is decisions over wall clock." Undefined: PyBoy throttled or headless-fast while recording, and whether "wall clock" means the run's full duration or just summed decision latency. Either axis swings the number by an order of magnitude, and it's the number the whole pitch rests on.

**4. NIT — `wIsInBattle`'s stated value set is wrong.**
§2: the latch fires on the transition from "`1` wild, `2` trainer, `-1` lost" to `0`. `wram.asm` defines only 0/1/2; there's no `-1` — "lost" is `wBattleResult == 1`, a different variable. The transition-based latch still works (any nonzero-to-zero flip fires it), but a builder chasing `-1` in `wram.asm` finds nothing and burns time confirming it's a doc error, not a missed constant.

## Buildability

Every other task's check is self-contained and runnable without guessing. Task 2 is the exception: its stated check (`$25` to `$00`) won't match observed behavior, forcing the builder to stop and re-derive the actual start map before the task can pass.

## Verdict

**NOT YET** — fix finding 1 (wrong starting map breaks task 2's own check and the first leg of the route) before starting task 1.
