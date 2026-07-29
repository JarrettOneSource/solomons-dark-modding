# Bot cast in range: root causes and design

Date: 2026-07-29  
Owner scope: `I guess you can fix the bot cast when in range just to make them slightly more useful.`

This wave is deliberately narrow. A bot uses its equipped primary spell on the
existing cadence when a target is inside that spell's native effective range.
When the target is outside that range, the bot closes distance through the
existing movement path. This work does not select a better skill, add a
rotation, redesign behavior profiles, or expand the Lua-bot product.

The owner-condition reproduction began from the `beta.22` source and runtime
baseline (`580cb938f179f3fe7f4a3b8361f87b41f4367c7f`). Later before-fix captures
added diagnostic-only instrumentation without changing the bot movement,
casting, progression, or damage behavior under test.

## Owner-condition reproduction

The before-fix evidence is under
`/mnt/d/codex-evidence/botcast-20260729/before/`. It used:

- a host and `client B` on isolated ports 50411 and 50412;
- the retail `data/wave.txt` staged without a wave override;
- only `bot.brain`, enabled through normal staged launcher mod settings;
- one Water bot configured under the old pre-Behavior roster shape;
- `SDMOD_DISABLE_AUDIO=1`; and
- authoritative enemy vitality changes as the combat acceptance metric.

The unmodified runs reproduced the owner's visible result: no bot damage or
effect application. Queue acceptance was recorded only to expose the old
false-positive boundary; it was never treated as combat success.

## Hypothesis verdicts

| Hypothesis | Verdict | Evidence |
| --- | --- | --- |
| Casts are issued outside Frost Jet's actual range | Disproved as stated | The old brain issued no casts in the pristine run. The real range failure was an approach dead band plus an AI-pursuit value being exposed as spell range. |
| The primary attack window never opens | Disproved | The window was available for all 9,342 brain-active ticks. |
| The Behavior migration leaves the roster brainless | Disproved | The old-key row migrated once, both peers reported an active brain, and the bot accumulated 9,342 active ticks. |
| Synthetic-participant casts do not reach native damage | Proven | The equipped primary rows were inactive before combat; after that was fixed, 67 accepted in-range Frost Jet casts with valid native damage still produced zero HP edges because the handler skipped its slot-zero damage-context branch. |

## Root causes

### 1. The short-range bot stops approaching before it can cast

`mods/bot-brain/scripts/brain.lua` asks
`sd.bots.get_primary_attack_window` for a range, filters cast targets through
that window, and approaches only while `threat_count == 0`. Once an enemy
enters the behavior's 340-unit threat radius, normal kite steering takes back
control even if no enemy is within the spell window.

The pristine 90-second sample is retained at
`before/attempt-3/pre-fix-repro.json`:

| Observation | Before-fix result |
| --- | ---: |
| Brain-active ticks | 9,342 |
| Ticks with retail-wave enemies | 9,151 |
| Attack-window available / unavailable | 9,342 / 0 |
| Approach / kite ticks | 7,375 / 1,967 |
| Nearest enemy contact distance | 269.457 minimum |
| Water window reported by the old seam | 170 |
| Casts issued / accepted | 0 / 0 |
| Enemy damage edges | 0 |

This disproves an attack-window cadence outage. It demonstrates the movement
dead band: the bot approaches from long distance, changes to kite steering
inside the broader threat radius, and never reaches its short spell window
unless the enemy happens to close the remaining distance.

The old Water seam was also not the required spell-range truth. It read the
stock control-brain global at `0x00786CE8` (`170.0`), an AI pursuit input
rather than the radius consumed by Frost Jet's damage query.

### 2. Synthetic progression leaves the equipped primary inactive

The controlled before-fix repro drove the Water bot to 23.499 units from a
real retail-wave enemy and queued four primary casts. All four queue calls
returned accepted. The watched target remained at 2.5 HP, no HP write fired,
and the trace at native cone query `FUN_00641B10` recorded zero calls.

The corresponding host log records the boundary:

```text
queued cast for bot
Multiplayer synthetic cast injected ... phase=pressed skill_id=32
[bot-brain] ... cast accepted
[bots] failed to resolve native spell mana ... skill_id=1012
       primary_entry=32 combo_entry=32 ... native_stat_cost=0
[bots] gameplay-slot cast prepare failed ... unknown mana cost for bot cast
```

The deeper pre-combat capture at
`before/attempt-4/short-water/result.json` shows why the native mana output is
zero: row 32 (`mDamage` and `mManaCost`) and row 34 (`mWiden`) all have
`active=0`, `visible=0`, and effective rank zero. Gameplay-slot materialization
had primed the base book and Discipline row but had never applied the equipped
primary choice to the synthetic participant's native progression.

The class-closing fix activates the profile's primary/combo rows through the
stock `PlayerAppearance::ApplyChoice` path before the native progression
refresh. It also preserves the profile-resolved entry pair through mana
preparation and brackets every `Skills_Wizard::BuildPrimarySpell` call with an
exact progression-flag snapshot/restore. It does not invent a mana value or
accept an unlevelled spell.

### 3. Frost Jet skips authoritative damage for nonzero gameplay slots

After the progression and range changes, the intermediate retail run at
`after/final/short-water/result.json` isolated the remaining damage failure:

| Observation | Intermediate result |
| --- | ---: |
| Water row 32 active / effective rank | 1 / 1 |
| Native `mDamage` / `mManaCost` | 2.5 / 12.5 |
| Native Frost Jet query range | 205 |
| Outside-range approach ticks | 11,258 |
| Casts, all at or inside native range | 67 |
| Enemy damage edges | 0 |

The live dispatcher trace reached `FUN_00543860` with normalized native damage
at actor `+0x28C = 0.025`. Ghidra then identified the exact per-target branch
at `0x0054423A`: a nonzero actor gameplay slot skips the block that seeds the
native damage context, including the `actor+0x28C` damage scalar. Synthetic
gameplay-slot bots therefore ran the query and presentation path but never
applied Frost Jet damage.

The loader now opens only that branch, only while the host is synchronously
dispatching an active Frost Jet cast for a Lua-brain participant, and restores
the original instruction immediately afterward. Client B and non-bot casts
retain the stock gate.

### 4. The one-time Behavior migration is not the failure

The reproduction wrote exactly the old row:

```json
{"name":"Brook","element":"water","discipline":"skirmisher"}
```

The shipped stage migration rewrote it to:

```json
{
  "name": "Brook",
  "element": "water",
  "behavior": "skirmisher",
  "discipline": "arcane"
}
```

Both peers reported `brain.active=1`; the host materialized Brook with
Behavior `skirmisher` and native Discipline `arcane`; and the brain accumulated
9,342 active ticks. Migration therefore does not explain the owner's brainless
appearance. The landed regression retains this old-key input and requires
applied bot damage after migration, so a future persistence regression cannot
hide behind a parser-only test.

## Native effective-range source

Headless retail decompilation establishes the Water damage-query path:

1. `PlayerActorTick` writes the rank-resolved `mWiden` contribution to actor
   `+0x290` immediately before dispatch. That cache is not initialized before
   the first Frost Jet dispatch.
2. `FUN_00543860` computes
   `(actor+0x290 / *0x00784750 * *0x007DE810) +
   *0x007DE888 + *0x007DE960`.
3. Retail values are `2.5`, `10`, `180`, and `25`, so rank-zero Frost Jet has
   an actual radial range of 205 while `mWiden` upgrades extend it.
4. `FUN_00641B10` receives that result as its radial query argument and
   selects actors eligible for Frost Jet damage/effects.

The attack-window API resolves `mWiden` from the participant's live native
progression StatBook before applying the recovered query formula. This avoids
reading the pre-dispatch actor cache while preserving progression-dependent
range.

The instruction, decompile, and numeric dumps are retained under
`/mnt/d/codex-evidence/botcast-20260729/investigation/`. The key point is
ownership, not a new constant: the bot brain receives the same
progression-derived effective range used by native query dispatch, including
the range-changing Frost Jet upgrade. It carries no per-spell range table.

The implementation exposes that value through the existing attack-window
surface. Non-Water primaries resolve from the stock selection's live native
pursuit range. An unresolved native range remains unresolved; it does not fall
back to a guessed distance.

## Minimal resolution

1. Activate the equipped primary/combo rows through the stock progression
   choice path, preserve the resolved pair through mana preparation, and
   preserve progression flags around native spell-builder reads.
2. Return the equipped spell's native effective damage/effect range through
   `sd.bots.get_primary_attack_window`, including progression-dependent Water
   range.
3. In `brain.lua`, when not fleeing, no target is inside the effective range,
   and a candidate enemy is outside it, choose the existing
   `approach_direction` path regardless of whether that enemy has entered the
   broader threat radius. Once a target is in range, leave existing kite,
   guardian, flee, cadence, and stuck-teleport behavior unchanged.
4. Open Frost Jet's recovered damage-context branch only around an
   authoritative host Lua-brain Frost Jet dispatch.
5. Make the live harness count enemy HP damage edges. Queue acceptance remains
   diagnostic only. Require:
   - a short-range Water bot to approach, cast at or inside its native range,
     and reduce enemy HP;
   - a long-range bot to cast and reduce enemy HP from farther away;
   - every recorded cast distance to be no greater than the native range at
     that cast; and
   - the old-key roster to migrate and reach the same applied-damage outcome.

## Final retail acceptance

The passing host/client B evidence is
`/mnt/d/codex-evidence/botcast-20260729/after/final-r4/bot-cast-in-range.json`.

| Scenario | Native range | Cast distances | Applied damage |
| --- | ---: | ---: | ---: |
| Short Water | 205 | 50.001-183.574 | 5 enemy HP edges; 2 linked to the aimed target |
| Long Fire | 381.330 | 366.690-374.627 | 2 enemy HP edges, each linked to the authorized bot projectile |

Water recorded 191 outside-range approach ticks. Fire cast beyond Water's
entire 205-unit window. Every cast was inside its own live native range. The
old roster key migrated to `behavior=skirmisher, discipline=arcane`, then the
migrated bot applied damage. Both peers materialized the bot in the run and
all four exact staged PIDs exited normally without forced termination.

Release acceptance later reproduced the same source with actor `+0x290`
containing an uninitialized negative float before the first cast. The window
correctly remained unresolved, but the bot could never choose an in-range
target. The release fix moved the `mWiden` input to the live native progression
StatBook described above; the actor cache remains dispatch-owned.

No website publication is part of this design. The resulting `lua-bots`
v1.0.2 package and listing update are evidence-only owner-gated artifacts.
