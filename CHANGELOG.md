# Changelog

All notable changes to this project are documented here, following Keep a Changelog.

## [Unreleased]

### Added
- WRAM symbol table walked out of pret/pokered `ram/wram.asm`, and a decoder that turns
  raw bytes into a `GameState` anyone can import.
- Synthetic RAM fixtures (`fixtures/make_ram.py`), so the decoder is testable with no ROM.
- Goal stack, waypoint route, derived-facts layer, option enumeration, and the Jev policy
  with option validation and a code fallback on every failure path.
- Tick loop and `jpp probe`, both driven through a duck-typed emulator.
- 1280x720 pygame overlay with per-option probability bars, the state that was sent, and a
  running Brier; replays a run file with no ROM present.
- `uv run measure`, printing decisions/sec, $/hour and the Brier next to the base rate and
  a constant predictor.

### Recorded
- Four real Jev answers over the rival-battle fixture in `fixtures/recorded/`, replayed by
  the tests. The remaining fixtures hit the gateway's free-tier rate limit; the recorder is
  resumable and skips anything already on disk.

### Not yet run
- Everything that needs a cartridge: the ROM smoke test, `jpp probe`, `jpp play`. The code
  is written and unit-tested against a fake emulator; the README says how to run them.
