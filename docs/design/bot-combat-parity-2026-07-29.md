# Bot combat parity

Date: 2026-07-29

Status: implemented and accepted live

## Scope

This wave closes only the two highest-ranked walls from
`all-bot-match-2026-07-28.md`:

1. Air primary casts apply no damage from a synthetic gameplay slot.
2. Synthetic participants do not consume the party's wave-respawn lifecycle.

Skill-choice policy, inventory/sustain behavior, and targeting/DPS changes are
deliberately excluded. Their priority will be set from the new three-run
all-bot measurement after these two class-level defects are fixed.

Combat acceptance is an authoritative enemy HP decrement attributed to a cast.
Accepted-cast counts are diagnostic only and cannot satisfy an acceptance gate.

## Baseline

The botmatch foundation produced accepted furthest waves of 35, 21, and 12,
for a mean of 22.67.

| Fighter | Element | Applied damage | Deaths | Respawns |
|---|---|---:|---:|---:|
| Aster | Fire, automated slot 0 | 134.0 | 8 | 6 |
| Ember | Fire, synthetic slot | 222.0 | 3 | 0 |
| Brook | Water, synthetic slot | 297.4 | 3 | 0 |
| Gale | Air, synthetic slot | 0.0 | 1 | 0 |

Gale recorded 1,466 accepted primary casts across the three runs without one
applied enemy HP edge. Synthetic fighters died seven times and never
respawned.

## Air primary root cause

### What the stock Air primary is

Air's equipped primary is the native Lightning spell, build spell ID 1013,
dispatched through primary entry `0x18` and handler `FUN_0053F9C0`. It is not a
utility-only action.

For a slot-0 PlayerWizard, the first acquired target enters this native path:

```text
FUN_0053F9C0
  -> FUN_0052BA80                 refresh primary target
  -> actor +0x5C == 0
  -> FUN_006246F0                 reset damage context
  -> seed source, flags, and Lightning damage
  -> FUN_0063E7D0                 apply damage to first target
```

Additional chain targets are selected through `FUN_00641340`. Each selected
target reaches a second copy of the same context-reset, context-seed, and
`FUN_0063E7D0` sequence for slot 0.

### Four-primary native audit

The four equipped elemental primaries all contain a native slot assumption,
but Fire and Earth defer damage until a projectile impact while Water and Air
apply damage directly inside their cast handlers.

| Element | Primary entry | Native handler | Nonzero-slot branch | Native role | Required policy |
|---|---:|---:|---:|---|---|
| Fire | `0x10` | `FUN_0053DC60` | `0x0053E4E8` | Skips projectile emission | Participant presentation; downstream host damage authority remains decisive |
| Water | `0x20` | `FUN_00543860` | `0x0054423A` | Skips direct Frost Jet damage-context construction | Host-owned synthetic authority only |
| Earth | `0x28` | `FUN_00544C60` | `0x00544C92` | Skips boulder emission | Participant presentation; downstream host damage authority remains decisive |
| Air, first target | `0x18` | `FUN_0053F9C0` | `0x0053FCD8` | Skips direct Lightning damage-context construction and apply | Host-owned synthetic authority only |
| Air, chain targets | `0x18` | `FUN_0053F9C0` | `0x00540767` | Skips each chained context construction and apply | Host-owned synthetic authority only |

The Air disassembly shows `CMP byte ptr [ESI+0x5C],0` immediately before both
branches. The first branch jumps from `0x0053FCD8` to `0x0053FF52`; the chain
branch jumps from `0x00540767` to `0x00540896`. Both jumps bypass the
damage-context reset, source/flag/damage seed, and `FUN_0063E7D0` call.

### Live synthetic-slot trace before the fix

The isolated retail-schedule trace used one Air/body/skirmisher Lua participant
in gameplay slot 1 on ports 50611/50612 with audio disabled.

The first cast established every upstream stage:

- Lua brain queued a primary cast for Gale.
- multiplayer cast sequence 1 was published with primary entry `0x18`;
- the gameplay-slot actor was prepared with build spell ID 1013;
- the stock dispatcher entered on actor slot 1;
- `FUN_0052BA80` returned the real wave enemy at `0x11C3BDC8`, native handle
  `0:E`;
- the damage context remained `source=0`, `flags=0`, `primary=0`, and
  `secondary=0` across the native Lightning handler.

The run produced 13 accepted Air casts and zero authoritative enemy HP edges.
This rules out the queue, dispatcher, native handler selection, and primary
target query. It matches the two proven slot branches exactly: a valid target
is present, but the nonzero actor slot skips all damage delivery.

Evidence is under
`/mnt/d/codex-evidence/botcombat-20260729/investigation/`, including the four
handler decompilation, Air instructions, and the live before-fix logs/result.

### Class-closing implementation

The Frost-only scoped patch was replaced by one audited primary-gate registry.
Every branch in the table above is declared, opcode-validated, and restored by
the same mechanism.

The registry distinguishes native role rather than spell name:

- projectile-emission gates may open for an authoritative synthetic actor and
  packet-driven participant presentation because the established impact hooks
  still enforce host damage authority;
- direct-damage-context gates may open only while the host dispatches a
  host-owned Lua participant's matching primary;
- slot-0 actors require no patch and continue through the stock branch.

Each gate resolves through the versioned binary layout, and the patcher verifies
the native `JNZ` instruction before changing it. The exact branch targets are
bound independently by the staged retail binary identity and the RE evidence
above. A scope object restores every opened gate immediately after the matching
native dispatch. Failure to open a required branch rejects the synthetic
dispatch and logs the exact gate; it cannot silently fall back to an accepted
zero-damage cast.

The resulting execution policy is:

| Native gate role | Host-owned synthetic dispatch | Received participant presentation | Slot 0 |
|---|---|---|---|
| Projectile emission, Fire/Earth | open | open | stock path |
| Direct damage context, Water/Air | open | closed | stock path |

That division keeps the host authoritative for native direct damage while
letting every peer materialize Fire and Earth projectiles. Existing projectile
impact authority remains the decisive damage gate. Air now reaches both the
first-target and chained-target context/apply blocks.

## Synthetic participant respawn root cause

### Existing slot-0 contract

There is no separate retail multiplayer actor constructor for round respawn.
The existing participant framework derives one reliable command when the
host's validated wave summary reaches `Completed`. The command carries:

- a monotonically increasing wave-respawn epoch;
- the completed wave and run nonce;
- the Arena-authored effective Boneyard slot-0 spawn tuple.

Each process applies that command to its existing local PlayerWizard and
existing progression. The recovered same-actor primitive:

1. clears queued cast and movement input;
2. restores current HP and mana to the actor's native maxima;
3. writes the Arena spawn position;
4. clears terminal/death fields `+0x94`, `+0x98`, `+0x160`, and `+0x1BC`;
5. restores the native alive grid-member byte `+0x36` and render/sort bias
   `+0xA0`;
6. calls `WorldCellGrid_RebindActor` (`FUN_005217B0`) so the same actor leaves
   its corpse cell and enters the spawn cell;
7. preserves actor, progression, inventory, skill/stat books, and equipment.

The host retires pre-respawn vitals corrections before publishing the epoch.
On remote human owners, the received epoch is also a packet-sequence barrier
against an older zero-life correction.

### Why Lua participants stay dead

Host-owned Lua participants use real PlayerWizard actors and the same native
death tick. Their first terminal tick is allowed exactly once, their
participant runtime publishes the death-presentation epoch, and client B
materializes that death coherently.

The gap is at wave completion: `TryApplyWaveRespawnCommand` invokes the
same-actor primitive only for `FindLocalParticipant`, once per process. It
never enumerates host-owned Lua participants. Their actor and progression
therefore retain zero HP and native terminal/corpse state forever. The manual
Lua Bots settings action works by retiring and recreating the roster, which is
not a respawn contract and is not used by automated matches.

### Class-closing implementation

The local-only primitive is now factored around one same-actor Wizard respawn
operation. The existing slot-0 wrapper and the host-owned synthetic participant
wrapper both call it.

For each authenticated wave-respawn epoch, the host:

1. keeps every Lua participant ID, actor, progression, loadout, and transport
   session unchanged;
2. quiesces its transient cast/movement state;
3. applies the same HP/mana, Arena position, terminal/death, alive-registration,
   and grid-rebind operation;
4. clears that binding's death-presentation bookkeeping;
5. publishes the resulting participant snapshot before the next synthetic state
   frame;
6. remembers the epoch per binding so retries are idempotent.

Client B does not run a second respawn implementation. It receives the
host-authored alive frame on the same participant/transport epoch. Its existing
remote alive transition clears the matching remote death epoch, restores
alive registration, rebinds the actor, and resumes ordinary playback.

The completed-wave command intentionally applies the same resource and spawn
restoration to every party member, not just members observed dead. That is the
existing slot-0 rule and is now the synthetic rule as well. A reported respawn
is narrower: it counts only an observed dead-to-alive transition. This
distinction matters at Game Over because a final fractional slot-0 HP sample is
not a respawn once the native controller has ended the run.

### Run-end rule

The existing loss rule remains unchanged. During a clearing wave, the host
publishes Game Over only when every connected run member has terminal life and
has entered its native death drive. A respawn command exists only after the
wave summary becomes `Completed`. Bots therefore cannot respawn on a timer
while enemies remain and cannot prevent an all-dead loss.

The already-established immediate-completion rule is also preserved: if the
wave becomes `Completed` before the party reaches the all-terminal command,
the wave-respawn epoch retires the death state. This is the same ordering used
for human participants.

## Permanent acceptance gates

### Four-element applied-damage matrix

For Fire, Water, Earth, and Air:

- a host-owned synthetic gameplay-slot participant casts its equipped primary
  in an unmodified retail-schedule run and must produce at least one
  authoritative enemy HP edge;
- an automated slot-0 PlayerWizard casts the same element's equipped primary
  in an unmodified retail-schedule run and must produce at least one
  authoritative enemy HP edge.

The matrix reports applied-damage observations and target HP transitions.
Accepted casts cannot satisfy any cell.

The accepted retail-schedule matrix is:

| Element | Automated slot 0, edges / damage | Ember synthetic, edges / damage | Brook synthetic, edges / damage | Gale synthetic, edges / damage | Furthest wave |
|---|---:|---:|---:|---:|---:|
| Fire | 6 / 24.000 | 1 / 4.000 | 2 / 8.000 | 4 / 16.000 | 3 |
| Air | 9 / 0.225 | 40 / 1.000 | 19 / 0.475 | 21 / 0.525 | 1 |
| Water | 12 / 0.300 | 12 / 0.300 | 29 / 0.725 | 10 / 0.250 | 1 |
| Earth | 1 / 0.908 | 2 / 1.800 | 2 / 1.592 | 2 / 1.800 | 2 |

Every cell is backed by authoritative enemy HP transitions. All four runs used
the retail schedule, physically crossed the gate without a stuck-failsafe
teleport, and triggered real Solomon Dig. The matrix summary is
`runs/primary-matrix-live3/summary.json` in the evidence directory.

### Synthetic respawn

The lifecycle scenario must prove:

- a synthetic participant dies from native combat during a clearing wave;
- another fighter completes that wave;
- the dead participant consumes the new wave-respawn epoch on the same actor,
  progression, participant ID, and transport session;
- HP/mana, spawn placement, native terminal fields, and death-presentation
  state converge;
- the participant produces an authoritative enemy HP edge after respawn;
- client B shows the same participant alive, visible, targetable, and with the
  correct HP bar.

The accepted scenario killed synthetic Ember with a native magic hit during
wave 1. Host and client B both observed the same participant at zero HP in
native death state. Completed-wave epoch 1 then restored the existing actor and
progression on each peer to 50/50 HP and 100/100 mana, cleared its death state,
rebound it into a traversable Arena cell, and retained native movement scale
1.0. The full nameplate health ratio was 1.0.

After that transition, Ember's Air primary produced three authoritative enemy
HP edges totaling 0.075 damage. Host and client B agreed on the same targetable
network actors, including `281543696187408` and `281543696187410`. The
inspected client B frame shows Ember visible in the Arena with a full HP bar.
The result is
`runs/live36-air-direct-epoch-targetability/result.json`; its client B frame is
`screenshots/client-b-respawn.png` below that run.

The three accepted all-bot measurements still ended through native Game Over
with the whole party dead. The lifecycle therefore restores a party only after
a completed wave; it does not make the party unkillable or defer the native
all-dead loss.

### Full all-bot remeasurement

Three runs passed the complete botmatch protocol: four fighters, physical gate
transit with zero gate stuck-failsafe teleports, real Solomon Dig, retail wave
schedule, authoritative applied-damage accounting, native Game Over, and
requested-frame validation.

| Accepted run | Furthest wave | Elapsed seconds | Aster damage, deaths / respawns | Ember damage, deaths / respawns | Brook damage, deaths / respawns | Gale damage, deaths / respawns |
|---|---:|---:|---:|---:|---:|---:|
| `remeasure-final-01/run-01` | 28 | 549.391 | 207.500, 4 / 3 | 190.000, 2 / 1 | 52.400, 1 / 0 | 58.150, 1 / 0 |
| `remeasure-final-04/run-01` | 9 | 189.997 | 32.000, 1 / 0 | 32.000, 1 / 0 | 17.900, 1 / 0 | 17.750, 1 / 0 |
| `remeasure-final-06/run-01` | 36 | 692.964 | 190.000, 3 / 2 | 48.000, 4 / 3 | 68.950, 2 / 1 | 104.425, 1 / 0 |
| **Total** |  | **1,432.352** | **429.500, 8 / 5** | **270.000, 7 / 4** | **139.250, 4 / 1** | **180.325, 3 / 0** |

The new furthest-wave mean is **24.33**, versus baseline **22.67**: +1.67
waves, or +7.35%. Aggregate applied damage rose from 653.4 to 1,019.075:
+365.675, or +55.97%. Every fighter and every element produced nonzero
authoritative applied damage.

Respawns in the table count observed dead-to-alive transitions only. Each raw
accepted result ended with one residual nonzero Aster HP sample after native
Game Over, formerly misclassified as a respawn; run 1's sample was 0.083 HP.
The analyzer now makes `runEnded` decisive, and a permanent test covers
fractional terminal HP. The corrections are Aster 4 to 3, 1 to 0, and 3 to 2
for the three runs. They do not change damage, deaths, or furthest wave.

Each accepted run has all four milestone frames plus one frame for every
reported wave: 28, 9, and 36 respectively. The frame validator accepted every
capture. Manual contact-sheet inspection confirmed that the wave frames show
live Arena combat and party state, while gate transit, gather, Dig, and native
terminal frames show their requested events. A diagnostic run that reached
wave 41 was excluded because the old harness had a fixed 40-frame filename
table and could not capture wave 41. The controller now uses an unbounded
`wave-%02d.bmp` pattern, with a permanent no-fixed-ceiling test.

## Updated ranked progression wall

### 1. Inventory and sustain

This is now the largest directly observed limiter. The accepted runs ended
with 22 party deaths and only 10 dead-to-alive completion transitions. They
contain 15 synthetic `mode=flee` entries, but only six returns to
`mode=normal`; every return followed completed-wave full-party restoration,
not an inventory heal. Nine flee episodes therefore had no recovery before
Game Over. All three runs remained natively losable and ended all-dead.

The next wave should measure and use stock consumable acquisition, selection,
and activation. Its acceptance metric should be native inventory consumption
followed by an attributable HP/mana recovery and later applied-damage edges,
not a longer run by itself.

### 2. Focused targeting and damage delivery

The fixes increased total applied damage by 55.97%, but mean progression moved
only 7.35%. At the three terminal frames, 90 enemies remained alive, mean 30
per run. Fifty-two of 90 (57.8%) still had full HP, 38 were partially damaged,
and only six were near death. The aggregate applied-damage rate was 0.712 HP/s
over 1,432.352 seconds.

That distribution shows a focus-fire problem rather than another accepted-cast
problem: nearest-target selection spreads thousands of small Air and Water
edges across a growing backlog. The next wave should compare target retention
and party focus against the current nearest-target policy, using kill
conversion, full-HP terminal backlog, and applied damage per second.

### 3. Skill-choice intelligence

The existing deterministic first-choice plumbing accepted a skill choice in
eight of twelve fighter-runs: six of nine synthetic fighter-runs and two of
three slot-0 runs. The wave-9 loss ended before any fighter chose a skill.
Runs 28 and 36 did reach choices, but the fixed policy does not evaluate
element, survivability, or the observed wave composition.

This remains a real progression lever, but it ranks behind sustain and target
focus because the current sample proves immediate all-dead losses and a large
partially engaged enemy backlog. The next wave should record the offered
options, chosen option, resulting stat/spell delta, and subsequent
applied-damage or survival delta for each choice.
