# Laya progress and recovery

The verified Gold 97 adapter now supports purposeful wild battles. Ordinary species
are training opponents; wild capture is restricted to verified, uncaught hack-exclusive
species, with the existing static encounter exception. Health, usable attacks, and
conservative retaliation estimates constrain all choices. Capture preparation compares
status and safe weakening with throwing immediately. Ball use must be observed in
inventory, and capture results must be observed in the cartridge. No A/B animation trick
is used: this cartridge determines capture success before the animation.

Healthy trainees may lead and switch to a stronger partner. Known trainer opponents
inform later lead selection; otherwise gym preparation chooses a healthy strong lead.
Exp. Share and the cartridge participation mask determine who can earn verified XP
credit. Deliberate training has a five-encounter / 18,000-frame budget, whichever ends
first, and ends early when readiness, health, or attacks require returning to the journey.
Fresh journey evidence or a demonstrated trainer-battle loss permits another detour. Tactical sacrifices require known damage,
turn order, and a finishing line that a direct switch would lose; usable healing and safe
switching take precedence.

At a reachable observed Center PC, roster selection preserves a viable battler, current
field-move coverage, useful type coverage, and a trainee. Deposit/withdraw, box selection,
and party ordering are confirmed through visible menus and exact individual roster
changes. Unknown menus, duplicate identity evidence, full boxes, and stalled transfers
fail closed. Release is never an action. Box switching can invoke the game's native save
prompt; replay tests use copied ROM paths so those native saves remain isolated.

## Points

`config/gold97_policy.json` configures nonnegative integer reward weights. An alternative
file can be selected with `JPP_GOLD97_POLICY`. Defaults are one point per new tenth of a
level earned through observed battle XP, ten per new level, 25 per first eligible species
capture or first observed evolution into a species, 50 per newly discovered map,
and 100 per verified journey milestone.
The first observation establishes a baseline; it creates no historical earnings.
Discovery requires a verified overworld position. Starting and previously visited maps
form the baseline; revisits and checkpoint restores cannot earn discovery points again.
Reachable new destinations take priority over incidental exits back to known maps.
Verified story routes and healing can still require returning through familiar areas.

The versioned per-run ledger lives separately from checkpoint-owned world knowledge.
Cartridge OT ID, DVs, and caught metadata identify individuals across evolution and PC
transfers. Ambiguous identities receive no speculative rewards. Individual high-water
marks and unique achievement keys persist across restart and restore. Reordering,
healing, deposits, withdrawals, and button presses earn nothing. Points inform planning
context and show in Journey Details; they do not change model weights or override safety.

## Journey and playback

Navigation and its display share a validated map snapshot. Active object structs replace
noisy sprite-slot positions; only current entities block routes. Current-map geometry and
observed transitions establish exits. Visiting two maps alone does not create a connection.
Manual play and provider waiting still record transitions and verified progress.

Knowledge migration archives invalid battle/menu/garbage clues, reopens affected
conversations, and retires legacy obstacles while preserving valid clues and route progress.
Dialogue needs a committed interaction and stable text. Empty interaction messages such as
“There's nothing here” are not clues. Existing guide hints remain evidence-gated; model
assertions cannot complete milestones.

Play requested is persistent and separate from playing, recovering, waiting for provider,
blocked, and manually paused. Transient provider failures retry with backoff capped at
30 seconds. Luna failures fall back to Laya/local decisions; Luna Off stays off. Manual
Pause invalidates pending decisions and releases held controls. Automatic recovery does
not load saves. Unsupported mechanics or exhausted safe recovery remain visibly blocked.

## Bounded evidence

Isolated copies of real checkpoints verified a Tangtrip capture with ball consumption and
25 capture points, party reordering, PC deposit/withdraw, and switching to an offscreen box.
A local-Laya, Luna-Off replay from the reported Route 102 state completed two wild battles,
recorded Hoppip and Volbear XP, and retained reward high-water marks across replay. A prior
bounded replay also left the map through an observed transition. These are not proofs of
reaching Bill, acquiring Cut, completing every menu variant, or finishing the game.

Focused tests cover Luna On/Off and outage contracts, stale-action cancellation, recovery,
reward deduplication, dialogue filtering, capture safety, and verified roster changes.
The opt-in `tests/test_gold97_progress_replay.py` runs real capture and PC/order replays
using `GOLD97_WILD_STATE`, `GOLD97_PC_STATE`, and optional `GOLD97_ROM`. It copies the ROM,
uses temporary databases, and never writes the player's original save or run database.
A live remote Luna playthrough has not been established by these local replays.
