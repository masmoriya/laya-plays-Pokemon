# Review 3: jev-plays-pokemon CONTEXT.md (final pass)

## 1. REVIEW-2 items

- Starting map (BLOCKER): fixed. Goal table, route, and task 2's check now read
  `$26 -> $25 -> $00`.
- Sample size: fixed, n range ("low hundreds") matches the 10-30/run x 10-run corpus.
- Decisions/sec method: fixed, section 5 pins wall-clock span, headless/unthrottled mode, the
  $/hour formula.
- `wIsInBattle` pushback: **correct**. Verified against `pret/pokered/ram/wram.asm` directly:
  "lost battle, this is -1; no battle, this is 0; wild battle, this is 1; trainer battle, this
  is 2" — on the label itself, exactly as quoted. REVIEW-2's NIT was wrong to call `-1`
  fictional.
- Latch logic, regardless of the `-1` debate: **right**. It fires on any nonzero-to-zero
  transition; the prior value (1, 2, or -1) doesn't matter, only the flip to 0. REVIEW-2
  already confirmed `end_of_battle.asm` zeroes `wIsInBattle` without touching `wBattleResult`,
  so the latched read is safe under any predecessor.

## 2. Measure output consistency

Section 1 (`n=312` calls/10 runs, `n=187` turns), section 5's corpus (10 runs, 10-30
labels/run -> "low hundreds"), and the README/launch lines (unfilled placeholders) all agree.
No inconsistency found.

## 3. Buildability — one real gap

Task 2 calls input-readiness detection "the fiddly bit" but names no RAM flag or heuristic (no
candidate like `wJoyIgnore`, a frame-stable-position check, or an animation-in-progress flag).
Every other task's check is self-contained; this one requires the builder to invent the
predicate mid-session — not a blocker, but the one place a guess is unavoidable as written.

## Verdict

**READY TO BUILD** — note in task 2 that the input-readiness predicate is undiscovered and
must be found via `jpp probe`, not assumed known.
