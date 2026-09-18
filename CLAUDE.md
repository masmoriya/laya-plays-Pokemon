# jev-plays-pokemon

Pokemon Red on PyBoy: code decodes RAM into a symbolic state, owns the goal stack and
waypoint movement, Jev picks among legal actions at branches. Live probability overlay.
Read `../CLAUDE.md` for the monorepo rules, then `CONTEXT.md` here in full.

Verdict: check the newest `REVIEW-*.md`; round two fixed the starting map (Red's house 2F,
`$26`), the `wIsInBattle` values, the calibration target, and the decisions/sec method.

Project-specific rules:
- The ROM is never in the repo. `ROM_PATH` env, user supplied. Save states are gitignored.
  RAM fixtures are synthesized (`fixtures/make_ram.py`), never dumped from a running game.
- RAM addresses come from pret/pokered `ram/wram.asm` symbols, not hex from a wiki.
- HP fractions, type effectiveness, PP, and all arithmetic are computed in code and handed
  to Jev as labeled facts. Jev never plans more than one turn.
- `uv run measure` replays a recorded run; it prints the base rate and the constant
  predictor's Brier next to ours, always.
- Launch gate: a recorded run (stream or MP4) exists before anything is posted.
