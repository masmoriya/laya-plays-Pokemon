# jev-plays-pokemon

Pokemon Red on PyBoy: code decodes RAM into a symbolic state, owns the goal stack and
waypoint movement, Jev picks among legal actions at branches. Live probability overlay.
Read `../CLAUDE.md` for the monorepo rules, then `CONTEXT.md` here in full.

Verdict after three review rounds: **ready to build**. The run starts in Red's house 2F
(`$26`); the input-readiness predicate is discovered with `jpp probe` in task 2, not assumed.

## Build state (2026-09-18, first build session)

All nine CONTEXT.md tasks are coded. `uv run pytest -q` gives 58 passed, 5 skipped. The
skips are the ROM smoke test (2) and the three jaggedness assertions that need recorded real
answers. Nothing has been reviewed by a second pair of eyes yet; that is the next session.

What ran for real and what did not:
- Tasks 1, 3, 4, 5, 6, 8, 9: checks pass on synthetic RAM and the fake Jev.
- Tasks 2 and 7: coded (`loop.py`, readiness predicate, battle latch, `jpp probe`,
  `jpp play`), unit-tested against a fake emulator object. Never run on a cartridge. The ROM
  commands are written verbatim in README "Development".
- Real Jev: 6 cassettes in `fixtures/recorded/` (four rival-battle turns, two run branches)
  came from the gateway shim before its free tier rate-limited the rest. Padded-state,
  labels-vs-raw-numbers, and injection cases are NOT recorded. `fixtures/runs/sample.jsonl`
  is 40 rows, 5 real and 35 tagged `"source": "fake"`; measure excludes the fakes and says
  so. No row carries a latency, so decisions/sec prints "not measured". README headline
  stays `__`.
- Overlay: verified with `SDL_VIDEODRIVER=dummy uv run jpp overlay --replay
  fixtures/runs/sample.jsonl` (1280x720, feed panel, state JSON, animated bars, sparkline).

CONTEXT.md changes made by the build (all in the file already):
1. `wBattleResult` is a plain `db` at `$CF0B`, not a WRAM union; the latch stays.
2. `leave_house` is now "not in either house map", since `wCurMap == $00` un-completes
   itself when `get_starter` enters the lab.
3. Section 1 differentiator rewritten: milanboers/jev-plays-pokemon (MIT, 4k lines, vendors
   NousResearch/pokemon-agent's RAM reader) already plays the whole v0.1 route and already
   uses this name. Our claims are the branches-only question economy, the published
   calibration number, and the overlay. Same facts in `docs/comparison.md`. The user must
   pick a new repo name at launch.

Address table: derived by walking `ram/wram.asm` with struct and UNION handling; nine
independently published addresses matched byte-exact (`wCurMap $D35E`, `wPartyCount $D163`,
`wEventFlags $D747`, `wIsInBattle $D057`, party HP/level at `$D16C`/`$D18C`), which is the
evidence for the battle block (`wBattleMon $D014`, `wEnemyMon $CFE5`).

Three `ponytail:` markers, all settled only by `jpp probe` on a cartridge: battle-menu
cursor choreography (`options.py:109`), outdoor waypoints (`route.py:8`), the player's
cell in the collision grid (`route.py:44`).

Blocked on the user: a Pokemon Red ROM path (`--rom`), and Vercel AI Gateway paid credits
for the remaining recordings (see `../CLAUDE.md`, "Real Jev access").

## Next sessions

Two prompts are checked in: `sessions/01-review.md` (brutal review, fixes, the README,
repo hygiene, the new name) and `sessions/02-demo.md` (overlay tuned for the camera, shot
list, recording recipe, the X thread). Run them in that order, each in its own session.

### Review targets

Start with: `decode.py` against `wram.asm` for any address not in the nine verified ones;
the readiness predicate and latch in `loop.py` (never exercised on real frames);
`options.py` cursor choreography; `policy.py` option-id validation and the 40-decision cap;
`overlay.py` frame pacing; `measure.py` Brier and Wilson math. Then, with a ROM: task 2's
probe, waypoints, the smoke test, a 50-decision headless run, re-record with
`fixtures/record.py` once credits exist.

Project-specific rules:
- The ROM is never in the repo. `ROM_PATH` env, user supplied. Save states are gitignored.
  RAM fixtures are synthesized (`fixtures/make_ram.py`), never dumped from a running game.
- RAM addresses come from pret/pokered `ram/wram.asm` symbols, not hex from a wiki.
- HP fractions, type effectiveness, PP, and all arithmetic are computed in code and handed
  to Jev as labeled facts. Jev never plans more than one turn.
- `uv run measure` replays a recorded run; it prints the base rate and the constant
  predictor's Brier next to ours, always.
- Launch gate: a recorded run (stream or MP4) exists before anything is posted.
