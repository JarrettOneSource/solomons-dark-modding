# beta.32 bot mana, flee, facing, and lone-target handoff

Date: 2026-08-04

Status: root causes confirmed before correction

## Scope and isolation

The beta.32 owner playtest exposed one enemy-authority handoff defect and three
connected bot-control defects:

- enemies visibly hesitate after the last human dies even though a Lua bot is
  still alive;
- low mana stops casts but does not make the bot disengage;
- the 80% resume decision assumes nominal maximum mana is attainable; and
- a low-mana bot moving away can keep facing its prior enemy target.

The investigation used the isolated clone `C:\sd-botmana-20260804` at
`b076478ac1698ff21e95facde5a46a6a4513cd65` (`v0.1.0-beta.32`). The game was a
copied install under `/mnt/d/codex-evidence/botmana-20260804/game-source`.
Every game launch used `SDMOD_DISABLE_AUDIO=1`, a `bmn-*` instance, and only
UDP ports 52191 through 52198. The owner install, owner profile, and primary
checkout were not used.

The preceding single-authority hostile-targeting correction and evidence are
recorded in `beta31-hostile-targeting-class-2026-08-04.md` and
`/mnt/d/codex-evidence/botlevel-20260804/REPORT.md`. That correction is sound;
this report concerns the later publication edge, not a return to two target
selectors.

## Last-human-death target trace

The canonical pre-fix pair trace is
`pre-fix/lone-bot-death-attempt9/result.json`. It used a hosted pair plus one
Lua bot and sampled the host's native hostile target pointer and the
host-published target participant on frame-tagged ticks around a native lethal
hit.

The host-side selector does not go idle:

- the human reaches logical death at sample 2;
- a second targetless hostile acquires the bot on that same tick;
- the hostile initially targeting the human keeps the human only until the
  native ineligible byte transitions, then selects the bot on the same tick;
- there are zero null-target frames after logical death; and
- the selector latch remains clear.

The published authority is stale after the local pointer has changed. The
primary hostile points to the bot at sample 3, while its replicated actor
snapshot continues to name the dead human until sample 8. In this trace that
is five ticks and 47 ms. Attempts 7 and 8 reproduce the same ordering.

### Root cause: cadence-gated target publication

`ApplyHostileTargetSelection` is already the host's one target authority and
correctly defers mutation until a dying native actor becomes ineligible. The
gap occurs after that decision. `BuildLocalWorldSnapshot` reads the new native
target pointer, but `SendWorldSnapshot` does not build or publish a run motion
snapshot until `kLocalTransportRunWorldMotionIntervalMs` (67 ms) has elapsed.
The motion packet contains `target_participant_id`, target slots, and the
target-authoritative flag, so the client continues applying the previous
human target during that cadence window.

The correction must preserve host-only target selection and request an
immediate run-world publication when the authoritative hostile target changes.
It must not let clients select targets or bypass normal cadence for unchanged
motion.

## Live mana recovery trace

`pre-fix/mana-recovery-live2/result.json` proves that beta.32 recovery is a
real native mana path, not a snapshot-only state change. A casting bot was
placed at exactly 10/100 MP in a live arena. The inclusive beta.32 boundary
entered reserve, and the native mana-delta trampoline produced 2.5-MP steps
at 250 ms intervals: 10.0, 12.5, 15.0, 17.5, and onward. Mana reached exactly
80/100, native reserve and the Lua hold cleared, accepted casts advanced from
17 to 19, and the bot caused native damage afterward.

The inclusive `ratio <= 0.10` entry and `ratio >= 0.80` nominal exit in
`UpdateBotManaReserveStateLocked` are established regression behavior and must
not be weakened.

## Firewalker and attainable maximum trace

The canonical native sustained-drain trace is
`pre-fix/firewalker-mana-facing-live5/result.json`. The fixture resolved the
bot's profile through the configured stock `ActorGetProfile` function and
armed the recovered Firewalker byte at profile offset `0x8DC`. The stock actor
tick owned the resulting drain; the fixture did not decrement MP itself.
Native persistent flags reported Firewalker for the full sample window.

Reserve again recovered from exactly 10/100 to 80/100 in 2.5-MP steps. On
nominal exit, active Firewalker resumed draining mana and drove the bot down to
8/100, causing another reserve cycle. The sample ended in hold at 38/100.
This demonstrates both genuine recovery and the unstable threshold cycle that
occurs when a sustained drain constrains usable mana.

### Root cause: reserve stores only nominal ratio

`BotManaReserveState` stores only `bot_id`, `active`, and `last_ratio`.
`UpdateBotManaReserveStateLocked` compares current MP only with the nominal
maximum. It records neither recovery progress nor a live attainable ceiling,
so it cannot distinguish "still recovering toward nominal max" from "held at
the highest MP this active drain permits." Any effect whose net drain prevents
the nominal 80% edge can therefore leave reserve active forever.

The native state must retain the exact inclusive 10% entry, prefer the exact
nominal 80% exit whenever it is reachable, and derive a bounded attainable
maximum from observed reserve recovery when progress plateaus. The derived
resume threshold must be visible in the bot snapshot so Bot Brain mirrors one
native decision rather than recreating thresholds.

## Cast hold is not a disengage policy

The Firewalker trace shows `mana_cast_hold=true` while Bot Brain remains in
`mode=kite`; no mana-flee mode is observed. Accepted casts also advance across
the repeated hold cycles.

### Root cause: mana gates actions but not movement state

`update_mana_cast_hold` mirrors native reserve for roster bots, and cast/skill
selection checks that flag. The movement state is still driven only by the HP
flee thresholds and ordinary approach/kite policy. The learned-policy path can
also emit its ordinary movement while mana reserve is active. As a result,
low mana is a cast filter, not the requested disengagement state.

Bot Brain must treat that bot's native reserve as an independent flee reason,
force scripted away-from-threat steering while it is active (including when a
learned combat policy is selected), issue no casts, and return to ordinary
engagement only when the same native reserve state clears.

## Movement-facing trace

The Firewalker trace compares heading with consecutive position deltas and the
nearest-enemy vector. While low-mana hold is active, 97 moving samples are
measurable. Enemy-facing dot reaches `0.9999999999999988`, while
movement-facing dot falls to `-0.9999820111966932`: the actor can face almost
exactly toward the enemy while moving almost exactly backward.

### Root cause: stale action facing outranks path heading

`MoveBotTo` preserves the participant binding's prior desired heading and
face target. Several completed attack/cast cleanup paths intentionally retain
that face target. `SyncWizardBotMovementIntent` applies binding target-facing
before heading, and `ApplyWizardBindingFacingState` therefore wins over the
pathfinding motion update's actual movement heading. A reserve entry clears
an active cast but does not guarantee that a completed cast's target-facing
state is gone.

The loader must mark the participant's native reserve state, clear stale
attack/cast facing on reserve entry, and, while a reserved bot is moving, drive
facing from the pathfinding movement heading. Normal target-facing resumes
after reserve clears.

## Regression and acceptance contracts

The correction is not complete without contracts that pin all four seams:

1. a changed host hostile target requests immediate authoritative run motion
   publication while unchanged motion retains the 67 ms cadence;
2. exact 10% still enters reserve and exact nominal 80% still exits, while a
   stable sub-nominal recovery plateau produces a reachable threshold and
   cannot wait forever;
3. native reserve makes Bot Brain stop casting and use a distinct mana-flee
   policy until the native state clears; and
4. a moving reserved bot clears stale target-facing and applies its movement
   heading.

Live acceptance must repeat a hosted pair plus bot death edge with zero
post-transition idle/old-authority frames, then show the same bot cross below
10%, stop casting, move away with a positive movement-facing vector, and
resume after nominal 80% or a demonstrated attainable cap while native
Firewalker-style drain remains active.
