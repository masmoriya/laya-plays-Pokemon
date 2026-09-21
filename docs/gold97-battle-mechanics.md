# Gold 97 battle decisions

The local battle planner owns trainer tactics. Laya availability does not gate it.
The existing wild encounter/capture policy and journey objectives are unchanged.

## Mechanics provenance

The reference is pinned to [SoupPotato/gold97 commit 976507f](https://github.com/SoupPotato/gold97/tree/976507f9e6e605050384e9ec12e9651988ae7c46).
`src/jpp/agent/gold97_mechanics.json` records the commit, source file digests,
cartridge digest, and move/type-table fingerprints. Its 255 move records match
the local v6.1c cartridge byte-for-byte. Type matchups were read from that
cartridge, anchored against the pinned source. There are no runtime web calls.

This hack uses a beta type chart. Dark and Dragon are physical; Ghost is special.
The reference includes each move's effect, power, type, encoded accuracy, PP and
secondary-effect probability. The initial battle item executor supports Potion
(20 HP); it confirms the visible item and waits for its inventory count to fall.

RAM facts follow `macros/wram.asm` and `wram.asm`: five combat stats, signed stat
stages, status, original move slots, and the zero-based active party index at
D0D4. Battle result is D0EE, not the shifted party-block address. Real saved-battle
replays verified active identity and victory decoding. The engine's
`EnemySwitch` loads the incoming enemy before `OfferSwitch`, so a verified
switch prompt may use that enemy context instead of the fainted opponent.

## Decision rules

- Favor reliable knockouts and useful damage; repeating a move has no penalty.
- Compare setup plus subsequent attacks against attacking immediately, including
  accuracy and the extra retaliation. Stage changes come from observed RAM.
- Distinguish free replacement offers, required replacements, and ordinary
  switches that concede an attack. Exclude the active party index, not species.
- Use a Potion only when it buys survival; prefer a safe finishing attack or a
  healthy replacement where appropriate.
- Recover at existing verified Center routes for health, status, or exhausted
  attacks. Finish the visit only after HP, status and decoded PP are restored.
- The executor verifies menus and targets, waits through animations, and retries
  an ignored tap after six unchanged observations. It attempts menu recovery at
  45 unchanged observations and pauses at 90 rather than looping indefinitely.

## Deliberate limits

Damage values are nominal tactical estimates, not a full battle simulator.
The initial estimator handles standard damage, accuracy/stages, STAB, the beta
chart, fixed and level damage, multi-hit ranges, charge/recharge cost, False Swipe,
and level-dependent OHKO eligibility. Complex variable-power/counter effects are
marked uncertain and do not justify guaranteed knockouts or setup. Critical hits,
weather, screens, held-item modifiers, and volatile effects are not fully modeled.
The source records preserve those move effects for later expansion. A different
cartridge digest or move/type table pauses trainer automation rather than silently applying
this profile. New cartridge layouts require independent RAM verification.

## Verification

Focused tests cover tactics, menu execution, decoding, recovery, and compatibility.
`tests/test_gold97_battle_replay.py` is opt-in with `GOLD97_BATTLE_STATE` and optional
`GOLD97_ROM`. It copies the ROM into pytest's temporary directory, loads the given
checkpoint read-only, runs without model calls, and disables cartridge save writes.
Do not interpret these bounded battle replays as proof of complete-game autonomy.
