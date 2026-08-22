# Native Solomon Dig encounter and survival wave director

This note follows the retail survival Arena from the resident Solomon Dig
actor through first contact, dialogue, retreat, TimeLine activation, and
default-monster spawning. It is the implementation oracle for the Website
`/game` port. The surrounding serialized scripting ABI remains documented in
[`boneyard-scripting.md`](boneyard-scripting.md), and enemy behavior remains in
[`native-enemy-behavior.md`](native-enemy-behavior.md).

All image addresses below are preferred virtual addresses for the analyzed
retail executable:

- `SolomonDark.exe` version `0.72.5`
- image base `0x00400000`
- file size `4,723,200` bytes
- SHA-256
  `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`

The retail schedule source used by the generator is `data/wave.txt`, 29,147
bytes, SHA-256
`363a985d79dc3ca28fb5ce519f56c436f5269a9bea1bedc7d1a825e8139499fc`.
The generated graph inspected for this pass is
`Generated Boneyards/random seed.boneyard`, 266,811 bytes, SHA-256
`dda683d9f9e34649b3a510b2790650fc99103e51316d4b95eb6593fe98d7d448`.

## Result

The encounter is one Arena-owned state chain, not three presentation effects:

1. Boneyard generation promotes and reserves candidate Dig graves, emits a
   `START GAME` script whose placement mode is `10`, and compiles the retail
   wave schedule into a serialized TimeLine graph. The script runtime, not the
   geometry generator, constructs the opening `Solomon_Dig` actor.
2. The Arena tick owns Solomon proximity, control locking, queued voice, and
   the retreat transition.
3. Solomon's run-away transition trips `SOLOMON RUNS`, whose generated script
   keeps the camera locked for four seconds and then removes off-camera
   objects.
4. The Arena starts the generated TimeLine. TimeLine events create transient
   Spawners; Spawners exhaust their compiled budgets without a live-population
   cap.
5. TimeLine pause nodes read the authoritative live-monster and boss counts,
   plus the Arena's low-population timer at `+0x88` for mode 6.
   Enemy death is therefore a required input to progression but is not owned
   by Solomon, the renderer, or a wall-clock fallback.

The stock HUD does not draw a wave number, score, or remaining-enemy counter.
The only player-facing start signal is the Solomon voice/run set piece,
music, and the arrival of enemies.

## Generated Dig sites and opening placement

The geometry generator and script runtime form one causal chain:

1. Generator `0x006388B0` first creates ordinary type-`2029` Gravestones,
   then promotes a nominal `9..14` eligible interior graves by writing the
   last overlay selector, `8`, at `0x0063B6CF`.
2. The generator finds the first promoted grave with the strict-smallest
   squared Euclidean distance to authored player spawn at
   `0x0063B739..0x0063B826`. It clears overlapping Trees and gives that root
   special compact-decoration treatment. The complete promotion and clearing
   pass is documented in
   [`native-boneyards-and-world.md`](native-boneyards-and-world.md).
3. At `0x0063CAE0`, the same generator constructs action `0x418` (`1048`,
   `PLACE SOLOMON DIGGING`), obtains operand zero through `0x006837D0`, and
   writes mode `10`. The action is attached to the generated `START GAME`
   script. It is immediately followed by action `0x3EC` (`1004`,
   `START NEXT WAVE WHEN`) with operand `3`.
4. Script dispatcher `0x00689750` sends action `1048` to runtime owner
   `0x00467230`. That owner builds an eligible selector-8 grave list and calls
   resident builder `0x00465920`.

### Placement modes and candidate ownership

`0x00467230` is the candidate-policy owner. Its operand-zero jump table maps
the supported modes as follows:

| Mode | Candidate policy before `0x00465920` |
| ---: | --- |
| 2 | every live type-2029 Gravestone with overlay selector 8 |
| 3 | selector-8 graves whose roots are strictly inside the scripted rectangle |
| 4 | selector-8 graves accepted by the scripted point/radius test |
| 5 | selector-8 graves whose native rectangles overlap the scripted rectangle |
| 6..9 | no candidate-building branch; the empty list reaches the builder |
| 10 | one grave: the first strict-nearest selector-8 grave to the placement origin |

Mode 10 initializes its origin from local player slot zero at
`Gameplay +0x1358`; while `Arena +0x28 < 20`, it substitutes the authored
RegionLayout spawn at `Arena +0x88F4/+0x88F8`. Helper `0x00403B90` computes
plain `(dx * dx) + (dy * dy)` with no axis scaling or square root. The update
uses strict `<`, so equal-distance ties keep the first grave in live scenery
serialization order. At generated `START GAME` entry, the local player is at
the authored spawn, so both origin branches resolve to the same stock
placement contract.

Builder `0x00465920` receives that filtered list, rechecks type and overlay,
and uses native RNG `0x00401170` only to select within it. Mode 10 supplies a
singleton list, so the RNG call cannot change the chosen opening root. The
builder then anchors the set piece exactly as follows:

| Resident | Root from selected grave `(gx, gy)` |
| --- | --- |
| grave dirt, DeadHawg record 13 | `(gx, gy)` |
| Lantern type 5010 (`0x1392`) | `(gx - 55, gy + 73)` |
| `Solomon_Dig` type 5009 (`0x1391`) | `(gx + 10, gy + 113)` |

An empty eligible list creates neither resident. Before dispatching any
placement mode, `0x00467230` calls `0x00467160`; an existing `Solomon_Dig`
`0x1391` or `Solomon_DriveBy` `0x139C` suppresses the action. This is the
duplicate/lifecycle gate, not a render-side check.

### Serialized-stock reconciliation and later-wave exception

The inspected `Generated Boneyards/random seed.boneyard` contains fourteen
selector-8 graves. Its authored spawn is
`(1323.68310546875, 3310.110107421875)`, and the strict-nearest grave in
serialized order is index 12 at
`(1014.7630615234375, 2513.224609375)`. Static script decoding recovers both
placement owners:

- trigger UID `37451`, `on START GAME`, runs script UID `37450` and action
  `PLACE SOLOMON DIGGING(10)`;
- trigger UID `37398`, `Random Solomon`, is a one-trip `START WAVE` trigger
  guarded by `RANDOM ROLL(1, 0, 5)` and runs script UID `37397` with
  `PLACE SOLOMON DIGGING(2, 0)`.

The first encounter is therefore deterministic from generated geometry and
spawn, not a second seed-random choice. A later wave may place a replacement
at a uniformly selected eligible grave through mode 2, but only after the
duplicate gate finds neither resident Solomon type. A port implementing only
the opening survival encounter must not use that later-wave mode-2 randomness
for initial placement.

## `Solomon_Dig` construction and dispatch

`0x00481C20` constructs native type `0x1391` (`5009`) and installs the exact
29-entry dig program:

```text
0, 0, 0, 0, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13,
15, 17, 17, 17, 17, 16, 15, 13, 11, 9, 7, 5, 3, 1
```

The animation advances once per five simulation ticks. The constructor sets
the pre-retreat hold to 25 and the initial lifetime field to 9999. Dispatcher
`0x0048A8B0` selects these state bodies:

| State | Function | Recovered role |
| ---: | ---: | --- |
| 0 | `0x00481FC0` | dig, acquire the closest player, fire FIND SOLOMON, lock controls |
| 1 | `0x0047D0F0` | turn toward the acquired player, select the dialogue branch |
| 2 | `0x0047D450` | wait for the global voice/dialogue queue to drain |
| 3 | `0x0047D570` | retreat wind-up, laugh/taunt, accelerate away |
| 4 | `0x004857B0` | follow the clipped escape path and age out |

### First-contact geometry and ownership

State 0 enumerates the four Arena player slots, rejects actors in another
Arena, and chooses the closest qualifying player. The ordinary scan is armed
only after the fractional animation cursor is strictly greater than
`programLength - 10`. For the 29-entry retail program, Solomon therefore
ignores proximity through cursor `19.0` and tests it only during the final ten
program slots before the dig loop wraps. A player then qualifies when:

```text
((solomon.x - player.x) / 1.5)^2
+ ((solomon.y - 10 - player.y) / 1.25)^2 < 10000
```

This is a strict ellipse with horizontal radius 150 and vertical radius 125,
centered ten world units above Solomon's root. It is not a circular distance
check and equality at the boundary does not qualify.

For local player slot zero, acquisition dispatches trigger type 14,
`FIND SOLOMON`, and disables that player's movement and casting. State 0 then
seeds state 1 from the currently displayed dig frame:

| Dig frame at contact | Initial heading | Emergence Y offset |
| ---: | ---: | ---: |
| `< 6` | `180` | `15` |
| `6..15` | `225` | `6` |
| `>= 16` | `270` | `0` |

The emergence offset is multiplied by `0.9` on every state-1/state-2 tick.
A separately armed native path can advance without a target
when the larger gate
`(dx/1.5)^2 + dy^2 < 28900` succeeds or the actor's armed field is positive;
this is not the ordinary player walk-up path.

### State-0 digging audio and cursor recurrence — 2026-08-20 correction

The earlier encounter pass recovered the 29-entry program and summarized it
as one frame every five ticks, but it did not follow the two armed audio bytes
or the cursor perturbations in the same state body. That omission left the web
actor silent and made the simple five-tick presentation clock an incomplete
model. Fresh read-only Ghidra decompilation and instructions for constructor
`0x00481C20` and state body `0x00481FC0` close the complete state-0 recurrence.

The constructor records the current program count after the four leading
zeroes at actor `+0x23C` (`4`, the shovel gate) and after records `3..13` at
`+0x244` (`15`, the dirt gate). Bytes `+0x240` and `+0x248` begin armed. Each
state-0 tick then executes in this order:

1. add exact float32 `0.2` to the cursor at `+0x218`;
2. when `cursor > 4` and `+0x240` is armed, draw `Integer(2)`, request registry
   `209 + draw`, and disarm `+0x240`;
3. when `cursor > 15` and `+0x248` is armed, draw `Integer(2)`, request registry
   `222 + draw`, disarm `+0x248`, and construct one `Anim_Flydirt` child;
4. while `4 < cursor < 10` or `cursor > 15`, subtract unsigned
   `Float(0.09)` from the same active gameplay RNG;
5. while `cursor > programLength - 5` (`24`), additionally subtract exact
   float32 `0.05`;
6. evaluate the late-cycle player-contact branch; and
7. absent contact, when `cursor >= 29`, subtract `29`, draw `Integer(2)` and
   replace the wrapped cursor with `4` when the result is one, rearm both audio
   bytes, then consume `Float(5) + 5` for the next dirt child's motion scalar.

The two sound calls are not pitch-and-gain calls. Instructions
`0x00482061..0x0048207A` and `0x004820E5..0x004820FE` end at gain-only
`Sound::Play 0x00407B70`; no float pitch draw exists. Both therefore play at
fixed pitch `1.0`. The virtual call through the actor's Arena pointer at
vtable slot `+0x104` resolves to Region hit-point gain `0x004622D0`, whose
falloff uses inner radius `0.1 * viewportWorldWidth` and outer radius
`0.5 * viewportWorldWidth`. The shovel request multiplies that result by exact
`0.5`; throw-dirt uses it unchanged. In the middle falloff band only, native
death/alternate presentation multiplies the gain by `0.1`; the strictly-inside
full-gain and strictly-outside zero-gain early returns retain their values.
Exact equality at the inner radius follows the interpolated branch and is
therefore death-damped. Stock sends no stereo pan.

The complete authored audio membership is four PCM WAV registry rows:

| Registry | Native path | Bytes | SHA-256 |
| ---: | --- | ---: | --- |
| 209 | `sounds\shovel\shovel1.wav` | 28,340 | `be06d2e6eaacf2e0b35aaf14293e41420a0efd5ae364894cda193398838ebce6` |
| 210 | `sounds\shovel\shovel2.wav` | 28,304 | `4697492d7f5e07a78613b60c44122c7e3193d17d898eccf8ffe62f229d4c0fdd` |
| 222 | `sounds\throwdirt\throwdirt1.wav` | 65,868 | `de233771aae5e806e4bdba0553729d1744605f512243fd30733e2e0dbd00a1ef` |
| 223 | `sounds\throwdirt\throwdirt2.wav` | 54,152 | `e527b1df105d2a2fabc65aa576d76fcf7379d3bf0d9f6a51fabb81011ffc947f` |

All four are 44.1 kHz, stereo, 16-bit PCM. An executable-wide immediate-offset
sweep finds the runtime play references only in `Solomon_Dig` state 0; the
other `+0x22DC/+0x2308/+0x2518/+0x2544` references are registry construction,
cleanup, or exception metadata. Every placement mode that constructs native
type `5009` therefore shares this one audio owner. States 1..4 make no shovel
or throw-dirt request. On contact, the armed recurrence ends immediately, but
an already started `Sound` record is not stopped and finishes naturally.

### Facing, hello selection, and voice ownership

State 1 recomputes the exact target heading as
`atan2(player.x - solomon.x, -(player.y - solomon.y))` in degrees. It applies
`trunc(turnRate) + 1` one-degree shortest-path turns each tick, then increases
`turnRate` by `0.5` up to `10`. Helper `0x00410D60` returns `-1`, `0`, or `1`;
the zero band is an absolute difference below one degree or at least 359
degrees. Heading normalization adds or subtracts 360 only for values strictly
outside the range, so exact `360` survives. State 1 then uses a separate raw
`abs(heading - target) <= 1` completion test without cyclic normalization.
Consequently, the rare native 359/0 boundary can remain in state 1 even when
the turn helper returns zero; this edge must not be silently repaired in a
parity port. State 2 calls the same state-1 body, so Solomon continues tracking
the acquired player throughout the line rather than freezing at the first
speaking heading.

Once the post-turn heading error is at most one degree state 1 enters state 2.
In the survival Arena branch
(`Arena + 0x1CD0 == 0`) it queues exactly one uniformly selected stock cue:

| Cue | PCM duration | SHA-256 |
| --- | ---: | --- |
| `SAY_SOLOMON_HELLO1.wav` | `7.826508 s` | `dd460115df4f6880d7e067fc1c8c93492413f103ea9b94855f11e955293a564d` |
| `SAY_SOLOMON_HELLO2.wav` | `5.695306 s` | `2e4702214f3aad252eb46e9000a8ef6bdec1dd95964d312cfbc1168a59a4bd94` |
| `SAY_SOLOMON_HELLO3.wav` | `5.539342 s` | `07693b871183c7d7d14fb4472aaa2ede983ebe5447bbcf031aee93649f909df2` |
| `SAY_SOLOMON_HELLO4.wav` | `7.343220 s` | `a2748ccc9fbe13c2ae80e238ea8dd5a170b1dd7e2b2c7fa050a0073470ce52a2` |

The alternate story branch is a five-line conversation and is not used by
the default survival run. The constructor initializes mouth pose `0`, its
countdown to `25`, and turn rate to `0`. While speech is active, state 2
decrements the mouth countdown; on expiry it uniformly chooses a different
pose from `0..2` and resets the countdown to
`40 + 2 * RandomInt(25)` (`40..88`, even). State 2 cannot advance merely
because a local timer expired: it waits
until both the global dialogue owner pointer and queued speech list are empty.
It then restores movement/casting, sets the Arena Solomon-found byte at
`+0x902A`, adds ten to the motion field, and enters state 3.

For a deterministic authoritative web host, the exact PCM duration is the
portable completion oracle. The host owns cue selection and a monotonically
identified semantic voice event; each client plays that event once. Clients
must not infer or replay voice from a repeatedly observed state value.

### Native visual dispatch and registered frame banks

Render dispatcher `0x004A2610` selects `0x004902C0` for state 0,
`0x00490420` for states 1 and 2, `0x00490640` for state 3, and
`0x00490790` for state 4. The Solomon asset-map singleton is `0x008199D0`;
builder `0x004ED980` registers 273 `Solomon.bundle` records. The survival
actor consumes these exact banks:

| Records | Count | Native use |
| ---: | ---: | --- |
| `2..19` | 18 | state-0 dig frames selected by the 29-entry program |
| `95..184` | 90 | six walk poses by fifteen directions |
| `213..227` | 15 | survival dialogue body |
| `228..272` | 45 | three mouth poses by fifteen directions |

Records `20..34` are the alternate body bank selected by byte `+0x229`; the
constructor writes that byte to zero, so normal survival uses records
`213..227`. Direction is
`trunc((normalizedHeading + 12) / 24) % 15`. States 1 and 2 draw the dialogue
body and the independent mouth overlay. Dig/dialogue also draw DeadHawg record
13 at `(x - 10, y - 113)`; that 46-by-10 registered shadow remains during the
state-3 hold and is absent from the accelerating/walk renders. States 1 and 2
place body and mouth at `actorY + emergenceOffset + motion`, then push the
fixed clip rectangle `(actorX - 1000, actorY - 1000, 2000, 1000)`. Its bottom
edge is the actor's grave-ground Y, so the dialogue art emerges above rather
than drawing through the ground. State 3 reuses that dialogue composition and
clip while its `+0x2B8` hold is positive; afterward it draws walk pose zero
with the vertical motion field added to Y and retains the same fixed-ground
clip only while acceleration is negative. State 4 draws
`trunc(walkCycle) * 15 + direction` from the walk bank.

The state-4 tick moves using the current escape speed, then adds `0.05` and
advances `walkCycle` by the updated speed divided by `30`; values above six
wrap by subtracting six. State-4 vertical motion starts with acceleration
`-3`. Each tick adds acceleration to the Y render offset, advances
acceleration by `0.25`, and, when the offset becomes positive, clamps it to
zero and resets acceleration to `-2` for the next hop. Renderer `0x00490790`
adds that offset to actor Y. The source `Solomon.png` is SHA-256
`057a3661340a3a099cf88c491d88c4268d82b8bb48ab29d214961ce701140126`;
`Solomon.bundle` is SHA-256
`a4d85b56f79486361a4ae18a6b4bc2bc1c0e28ba1a57f96ef68cc64e09e9cafa`.
Every selected record has a 200-by-200 logical registration; copying raw atlas
rectangles without each record's origin would shift the actor between poses.
The extracted DeadHawg record-13 crop is SHA-256
`f3542e9d1b3621fdecd6f68baedf2d4f3c80762bd21ca7aa9fbb66e530db309c`.

### Retreat timing and trigger order

State 3 first consumes the 25-tick hold. When it reaches zero it:

- reverses the heading and clamps the result into the native 45..315-degree
  escape sector;
- initializes acceleration to `-7`;
- queues `LAUGH1` followed by `GETHIMBOYS` for the survival branch;
- selects `combat` song, `combatprelude` track; and
- begins moving three world units per tick along the escape heading.

The reverse step adds 180, subtracts 360 only when the result is strictly
greater than 360, then clamps. This preserves the native discontinuity:
heading 180 becomes exact 360 and clamps to 315, while a value just above 180
wraps near zero and clamps to 45.

The exact stock follow-up cues are:

| Cue | PCM duration | SHA-256 |
| --- | ---: | --- |
| `SAY_SOLOMON_LAUGH1.wav` | `2.463016 s` | `26463c3f557378c5409fe8b37c49c9f5585dee26ffc16face1db0770a08d5716` |
| `SAY_GETHIMBOYS.wav` | `2.441088 s` | `c26e56af5c5036bdfdda8dee9c5ba8270a75156b45c0afe9f00c83b850b34541` |

Each subsequent state-3 tick adds `0.5` to acceleration and applies it to the
motion scalar. When the scalar becomes positive, Solomon samples one random
sign, deflects the clamped retreat heading by exactly `-15` or `+15` degrees,
initializes the state-4 path and hop, enters state 4, and fires trigger type
15, `SOLOMON RUNS`. The actor therefore does not start the wave at first
contact, at the end of the hello, or at the start of the 25-tick wind-up. The
run trigger is the transition boundary.

State 4 casts a 4096-unit escape ray and clips it through native Arena
geometry. Speed begins at 2 and increases by `0.05` each tick. The survival
lifetime is set to 515. On its final lifetime tick the actor still moves,
advances speed/gait/hop, then decrements the lifetime and is removed. The
generated `SOLOMON RUNS` script locks the camera, sleeps four seconds, and
destroys off-camera objects. Camera behavior is presentation-owned, but
trigger and lifetime are authoritative Arena state.

## Generated survival schedule

The retail `wave.txt` contains 42 `WAVE` records. Across those records it
declares 918 spawn-budget units, 205 `GROUP` blocks, and 680 enemy rows.
`SPAWN` ranges from 3 through 60 and `MAXENEMIES` from 40 through 80. The
source enemy-row counts are:

| Enemy | Rows |
| --- | ---: |
| Skeleton | 344 |
| Skeleton Archer | 140 |
| Imp | 63 |
| Skeleton Mage | 58 |
| Zombie | 41 |
| Coffin | 15 |
| Demon | 14 |
| Wraith | 5 |

`NEXT` values are signed relative schedule edges. Negative values are valid
in the retail file and form late-game loops; a reader which rejects negative
`NEXT` has changed the schedule grammar.

`WaveData_Parse` at `0x00632730` stores `SPAWN`, `SPAWNDELAY`, `WAVEDELAY`,
and `MAXENEMIES` in separate parsed fields. Full-function instruction tracing
shows that the generator consumes the first three, but the only later access
to the `MAXENEMIES` local is destruction of its parsed range. No TimeLine
event, Spawner field, or Arena gate receives it. `MAXENEMIES` is therefore a
retained/dead retail directive, not a simultaneous-enemy cap.

Retail rows also contain `FLAG_IGNITE` and `FLAG_IMMORTALIZE`, but
`WaveFlag_ParseModifiers` at `0x0062E070` has no matching branch for either
token. They reach the `Unknown Param` log and append no modifier code. An
editor may preserve the source tokens for lossless text round-trip, but a
runtime compiler must omit them from emitted enemy configuration.

Generator `0x006388B0` compiles one schedule row as follows:

1. Expand the raw `SPAWN` budget to
   `SPAWN + trunc(SPAWN / 2) + RandomInt(trunc(SPAWN / 2))`.
2. Consume the legacy `WAVEDELAY` draw and a singleton `SPAWN` draw. Neither
   sampled value becomes a delay, but both draws advance the seeded stream.
3. Select a whole `GROUP` uniformly. Its cost is the smaller of the remaining
   budget and row count. The emitted Spawner count is cost plus a seeded bonus,
   then receives the ordinal scaling at waves 4 and 9.
4. Sample `SPAWNDELAY` once per consumed group member. One half of each draw
   contributes to the compiled Spawner spread. Consecutive selections of the
   same group merge their count and spread.
5. Apply the stock family branches: early Zombies and Demons consume two extra
   budget units; Pike Skeletons reset the raw budget; pre-37 Imps either reset
   for split flags or consume two extra units; Coffins reset the raw budget,
   cap count by `trunc(waveOrdinal / 5)`, force 25 spread ticks per member, and
   use SPAWN LOCATING wrappers.

The default Spawner later selects a random record from the compiled event for
each actor. It does not walk ordinary GROUP rows sequentially. Sequential
membership is a distinct Spawner mode.

Generator `0x006388B0` does not consult `wave.txt` every tick. It parses the
file, consumes the seeded Boneyard RNG, and serializes the result into normal
trigger, recipe, and TimeLine objects. The inspected stock-generated file has:

- one enabled TimeLine, UID 36783, named `Main Time line`;
- 594 TimeLine events;
- 394 SPAWN, 14 SPAWN LOCATING, 87 PAUSE, 43 ADVANCE WAVE,
  42 LABEL, and 14 JUMP TO LABEL events;
- labels `Wave1` through `Wave42` and two terminal jumps after Wave42;
- 30 triggers/scripts and 15 custom monster recipes.

Default-monster rows embedded in that exact graph request these totals:

| Native type | Enemy | Count |
| ---: | --- | ---: |
| 1001 | Skeleton | 670 |
| 1002 | Skeleton Archer | 226 |
| 1003 | Skeleton Mage | 122 |
| 1004 | Imp | 121 |
| 1006 | Zombie | 66 |
| 1007 | Wraith | 2 |
| 1009 | Demon | 21 |
| 1013 | Coffin | 13 |

These totals describe the generated graph's candidate/default spawn records,
not the number simultaneously alive and not an assertion that one traversal
executes every branch.

The generated opening makes the ownership visible. It sets spawn locating,
spawns `8 + RandomInt(5)` Skeletons at graph time 0, schedules
`3 + RandomInt(3)` more across four seconds at graph time 5, pauses in
live-count mode 3 with threshold `1 + RandomInt(4)` at time 9, then sets the
next locating policy and enters label `Wave1`. The opening is already part of
the TimeLine; adding a separate browser-authored “wave one delay” would double
the stock sequence.

### Opening ambush variability and live execution — 2026-08-22 correction

The earlier `10 + 5`, threshold-4 statement described one generated file, not
the generator. Raw `WaveData_Parse 0x00632730` instructions close all three
authored draws:

- `0x0063298F..0x006329BA` calls `RandomInt(5)` and stores `8 + result` as the
  immediate event count;
- `0x00632AE4..0x00632B0F` calls `RandomInt(3)` and stores `3 + result` as the
  four-second event count; and
- `0x00632C70..0x00632C93` calls `RandomInt(4)` and stores `1 + result` as the
  following mode-3 population threshold.

Both spawn records are default Skeleton `1001` with modifier codes `4,2,7`
(`FLAG_WEAK`, `FLAG_HPDOWN`, `FLAG_XPBONUS`). The preceding `SPAWN LOCATING`
event is exactly integers `[0,0]`: location zero selects a player plus a
100-unit random vector, and position policy zero requests a dark point. This
is the stock opening “ambush”; there is no separate class, flag, animation, or
string named Ambush. At time 9, `[1,0]` restores anywhere plus dark placement.

A read-only census of 40 distinct generated retail Boneyards found every
immediate count from 8 through 12 and every follow-up count from 3 through 5.
The observed pair set was
`(8,3) (8,4) (8,5) (9,3) (9,5) (10,3) (10,4) (10,5) (11,4) (12,3)`;
the instructions, rather than that finite sample, establish the complete
Cartesian ranges.

Two isolated generated-Arena checks used the unchanged 4,723,200-byte retail
executable named above, disabled audio, a temporary profile, and only
`sample.lua.ui_sandbox_lab`. They are loader-injected supporting diagnostics,
not clean-stock parity captures:

- In PID 21192, the live Spawner exposed `+0x3C=0` and `+0x40=0`, Arena
  `+0x8F00=0`, and ten entries through `SpawnPositionPolicy 0x00466200`.
  Every raw point was `99.99998..100.00004` units from player
  `(1522.3927001953125,150)`. The ten registered roots ended
  `228.309..462.691` units away after dark/collision search; three were outside
  full Arena `(0,0,2166.280029296875,3633.719970703125)`.
- The untraced control generated counts `8 + 3` and threshold 1. It registered
  all eleven Skeletons at the expected eight-at-once then three-over-four-
  seconds cadence. Their final roots were `271.084..413.887` units from player
  `(261.9573974609375,3034.199951171875)`; five were outside full Arena
  `(0,0,2615.800048828125,3184.199951171875)`.

The ambush therefore works end to end in stock: randomized records become
real near-player/dark Spawners and real enemy actors. “Near player” describes
the raw 100-unit proposal, not the final root. Dark-policy retries commonly
move the birth hundreds of units and may accept outside the full Arena, exactly
as the static policy-0 branch predicts.

### Provenance limitation in the Website geometry bank

The Website's twelve native geometry templates came from exact stock files,
but several of those runtime captures had test schedule overlays. For example,
the first bank source contains only seven TimeLine events, not the retail
594-event graph. Those files remain valid geometry oracles but cannot be
silently represented as twelve independent retail wave oracles.

The web implementation therefore uses the untouched retail `wave.txt` as its
authoritative default schedule and pins the 594-event generated file as the
semantic cross-check. It deterministically compiles/executes the schedule from
the run seed for every default geometry. A mod-authored Boneyard's opaque
TimeLine is not replaced by the retail schedule; general Bonedit scripting is
a separate compatibility surface.

## TimeLine and Spawner runtime

TimeLine tick `0x0046E390` advances by the native frame delta
`1 / DAT_00820230`, consumes every due event in sorted graph-X/graph-Y order,
and stops when an event requests a pause. Pause modes are:

| Mode | Resume condition |
| ---: | --- |
| 0 | running |
| 1 | fixed countdown reaches zero |
| 2 | authoritative live-monster count is zero |
| 3 | live-monster count is below the stored threshold |
| 4 | reserved/stalled in this evaluator |
| 5 | boss count and active boss actor are both zero |
| 6 | `Arena.lowPopulationTicks > storedTimer` or live monsters are below the stored threshold, with no active boss |

Spawn-event activation at `0x0046C9A0` creates a 0x44-byte Spawner. Spawner
tick `0x0046D000` owns two countdowns, remaining budget, record/group indexes,
location policy, and position/light policy. It computes steady interval as
`spread / max(remaining - 1, 1)`; chaotic scheduling adds a seeded random
integer bounded by half the interval. The event is finished only after its
Spawner exhausts its budget. The TimeLine stays alive at end-of-events while
any child Spawner remains.

For default/group selection the Spawner draws from the event records unless
group-total mode requires sequential membership. Location policy 1 chooses a
seeded point inside the Arena rectangle. The other default chooses one of the
four player slots and offsets the point by 100 along a seeded unit vector.
Placement helper `0x00466200` then applies one of the dark/light,
camera/off-screen, or Boneyard-edge policies and passes the result through
Arena collision/path adjustment at `0x00463D30`.

Spawner tick contains no global-live-count comparison and no
`MAXENEMIES` field. Once either countdown expires it keeps consuming the
compiled event budget according to the timer rules above, including same-tick
drain when the remaining-spread timer expires.

## Arena wave owner

`Arena_StartWaves` at `0x00465C00` initializes combat-active state, the wave
counter, wait/advance fields, and combat music, then dispatches the wave-start
trigger. It also resets `Arena + 0x88` to zero. Region tick `0x0063EFC0`
increments that field while the authoritative live-monster count is below 11
and no boss exists; after more than ten such ticks with zero live monsters it
latches the value to `999999999`. TimeLine pause mode 6 at `0x0046E390`
resumes on the strict expression
`storedTimer < Arena.lowPopulationTicks || liveMonsters < storedThreshold`,
provided no boss exists. The field historically called `wave_counter` by the
loader is therefore a low-population timer, not the schedule ordinal.

The automatic evaluator at `0x00465D70` reads Arena active state,
global run state, current wait/advance mode, live-enemy and Spawner counts,
boss state, and the completion latch. It does not require a living human
player. `START NEXT WAVE WHEN` action `0x004625F0` arms threshold or timed-lull
progression from script operands.

Wave advancement and enemy construction are separate owners:

- the director chooses the next schedule node, updates the wave counter, and
  activates TimeLine/script work;
- a Spawner creates an enemy actor;
- the enemy/combat system owns life, damage, death, and removal; and
- TimeLine/director pause gates observe the resulting live counts.

A web port may expose an `enemyDied/retireEnemy` input at this boundary before
full combat lands. It must not use a timer, renderer visibility, or maximum
age to pretend enemies died, because that changes every pause and later-wave
branch.

## Audio and HUD boundary

Arena entry owns `prelude`; Solomon's retreat owns `combatprelude`; wave start
owns combat music. The stock tracker modules for the latter two are not among
the Website's currently lifted music assets. Substituting Academy, Prelude, or
a browser-created track would be false parity. Exact Solomon PCM cues are
available and must be used without synthetic captions or replacement speech.

Fresh HUD tracing found no wave-number draw call and live mutation of the
native wave counter did not change the HUD. The Website must not add a wave
badge merely to expose director state. Test/diagnostic DOM data attributes are
acceptable as non-visual receipts.

## Validation and confidence

Evidence used in this pass:

- fresh headless Ghidra decompilation and instruction listings for
  `0x00481C20`, `0x00481FC0`, `0x0047D0F0`, `0x0047D450`, `0x0047D570`,
  `0x004857B0`, `0x0048A8B0`, `0x00410D60`, `0x004A2610`, `0x004902C0`,
  `0x00490420`, `0x00490640`, `0x00490790`, `0x004ED980`, `0x00465C00`,
  `0x00465D70`, `0x004625F0`,
  `0x0046C9A0`, `0x0046D000`, `0x0046E390`, `0x00632730`, `0x006388B0`,
  `0x0063EFC0`, `0x00466200`, and `0x00463D30`;
- lossless SyncBuffer decoding of the exact generated Boneyard named above;
- exact retail `wave.txt` parsing and counts;
- PCM headers and hashes for all six survival Solomon cues; and
- prior isolated native HUD and Boneyard runtime captures.

Confidence is high for actor state ownership, late-cycle contact gate,
contact-frame heading/emergence branches, contact ellipse, control lock,
raw 359/360 turn boundary, cue selection set, queue-drain boundary, fixed
dialogue/retreat clip geometry, retreat constants/order, TimeLine
event semantics, pause modes, Spawner budget/pacing, absence of a live-count
Spawner cap, low-population timer ownership, Solomon turn/mouth cadence,
registered visual banks and selection math, the signed 15-degree escape
deflection, state-4 hop recurrence and final-tick retirement order,
schedule grammar, and absence of a stock wave HUD. The following remain
explicitly unresolved rather than guessed:

- the exact tracker-module audio render for `combatprelude` and `combat` in a
  browser-supported format;
- browser projection of every native dark/light/off-screen placement query,
  because native camera/light managers have no one-to-one headless host view;
- custom boss scripts/recipe combat behavior attached to special generated
  waves; and
- enemy AI, attacks, damage, death visuals, drops, and experience, which are
  documented adjacent systems and not owned by the wave director.

The read-only Lua verification attempted on 2026-08-14 found the user's stock
process but could not connect to `SolomonDarkModLoader_LuaExec`; the loader Lua
runtime was not initialized. No process was restarted or mutated. Static and
serialized evidence above is independent of that unavailable check.

## Entrance retirement, camera region, and post-transition spawning — 2026-08-16

This follow-up closes the generated survival transition that begins when
Solomon runs. It uses the same retail executable identified above (4,723,200
bytes, SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`)
and the generated reference Arena `Generated Boneyards/random seed.boneyard`
(266,811 bytes, SHA-256
`dda683d9f9e34649b3a510b2790650fc99103e51316d4b95eb6593fe98d7d448`).
The reference Arena is `(0,0,2339.889892578125,3460.110107421875)`, starts the
player at `(1323.68310546875,3310.110107421875)`, and places the entry Gate on
the horizontal segment from `(1227.173828125,3160.10986328125)` to
`(1377.173828125,3160.10986328125)`.

### Generated region construction

`BoneyardGenerator 0x006388B0` authors a 400-unit entrance extension and a
three-action `SOLOMON RUNS` script:

1. `LOCK/UNLOCK CAMERA` mode 0 (`1065`) with the combat rectangle;
2. `SLEEP(4.0)`; and
3. `DESTROY OFF-CAMERA OBJECTS` (`1066`).

The generated entrance has two realized vertical orientations. The combat
rectangle height is the final Arena height minus exactly `400.0` (qword
`0x0078E600`). For a south/bottom entry it starts at the Arena origin. For a
north/top entry its Y is shifted by exactly `375.0` (qword `0x00798FA8`) while
retaining that reduced height. The stock generator sets the corresponding
player facing to 0 or 180 degrees and builds the spawn inset with the recovered
150/300-unit constants. The reference file therefore locks to
`(0,0,2339.889892578125,3060.110107421875)`. A second authentic generated run
observed on 2026-08-16 used full bounds
`(0,0,3674.89013671875,2125.10986328125)`, a north spawn at
`(1258.9234619140625,150)`, a Gate at Y `300.00006103515625`, and the exact
target `(0,375,3674.89013671875,1725.10986328125)`.

### Camera and cleanup ownership

`LOCK/UNLOCK CAMERA 0x00464B20` mode 0 intersects the authored combat
rectangle with the full Arena and writes target endpoints at Arena
`+0x8E98..+0x8EA4`. It snapshots the current camera endpoints into
`+0x8EA8..+0x8EB4` and stores float32 blend `0.01` at `+0x8EB8`. Arena tick
`0x0046E570` recursively lerps each current endpoint toward its target, then
multiplies the float blend by exact double `1.01` (`0x00785C90`) and caps it at
one. The player-follow viewport at `+0x8BCC..+0x8BD8` is clipped to that
interpolated region. Unlock mode 1 restores the full Arena target and uses
float `0.001`; the generated script never invokes it.

`DESTROY OFF-CAMERA OBJECTS 0x004728B0` runs after the 4.0-second/400-fixed-tick
sleep. It removes scenery, roads, compact/decor records, bridges, and derived
spatial records outside `+0x8E98..+0x8EA4`, then rebuilds the affected caches.
It does **not** iterate the Fence manager at Arena `+0x885C`. The entry Gate is
therefore not destroyed or replaced. It becomes unreachable in ordinary play
because the active camera/encounter region retires its entrance side; treating
the transition as a Gate deletion is the wrong ownership model.

Player tick `0x00548B00` and its ordinary movement path do not read the camera
target rectangle. The executable does not establish a separate invisible
combat-wall write in this script. A browser port that hard-confines an
authoritative player to the sealed combat region is an explicit one-way safety
adaptation, not evidence that `1065` itself is collision.

### Exact Spawner placement search

`Spawner::Tick 0x0046D000` chooses a raw point before collision placement:

- location 1 is uniform over the original Arena rectangle;
- the other location path chooses one eligible player slot and adds a random
  unit vector of length 100, with camera-center fallback when no player is
  available; and
- `MAXENEMIES` is not consulted at runtime by Spawner.

The selected recipe supplies its collision radius to `0x00463D30`. That helper
first accepts the raw point if collision and the selected light/visibility
policy accept it. Otherwise it searches ellipse-compressed rings around the
raw point. Ring radius begins at one actor radius and grows by that radius.
For each ring, the angular sample count is derived from its circumference,
angle spacing is `360/count`, the starting angle is one inclusive native
`RandomFloat(360)`, and Y is multiplied by exact `0.8`. Each candidate must be
inside the current camera target reduced by the actor radius, except policy 0
(`dark`) bypasses that rectangle check. Dark search alone switches to direct
policy 3 after the radius reaches exact float `350.0`, resets to two actor
radii, and continues. Collision is checked again before returning.

`0x00466200` maps the generated position policy exactly as follows: 0 dark
(light scalar below zero), 1 light (above zero), 2 offscreen, 3 direct, and 4
outside the supplied rectangle/edge policy. These are placement predicates;
they are not alternate wave schedules.

### Exterior-birth conclusion and Website policy

Stock does not provide a mathematical no-exterior-birth guarantee for every
generated wave record. An `anywhere`/location-1 raw point is sampled from the
full Arena, and a collision-free point accepted by dark policy may return
before the camera-target containment branch. In the observed authentic run,
all 16 sampled first-wave births happened to lie inside the combat region, but
that observation does not override the reachable static branch.

The Website requirement is therefore sharper than the native accident: after
`SOLOMON RUNS`, every raw point and every retry candidate must be admitted only
inside the authoritative combat rectangle. It preserves the native wave graph,
near-player versus anywhere selection, player sampling, actor radius,
collision query, radial retry order, and deterministic Web RNG projection, but
intentionally removes the retired entrance strip from the spawn domain. This
same authoritative rectangle also makes the web transition one-way for
players after sealing. Custom/mod Boneyards do not own the generated
`SOLOMON RUNS` lifecycle and must retain their authored full bounds.

### Validation matrix

- generated south and north entrances recover their exact combat rectangles;
- opening counts cover `8..12` immediate plus `3..5` spread births, the pause
  threshold covers `1..4`, and all three draws retain native ordering;
- mode-0 interpolation begins at `0.01`, grows by `1.01`, caps at one, and the
  400-tick cleanup/seal boundary is distinct from camera interpolation;
- the two Gate leaves remain in replicated state while the camera and active
  region exclude the entry strip;
- player movement cannot cross back into the retired strip after sealing;
- near-player and anywhere bursts retain native schedule/RNG consumption and
  collision-radius-aware radial placement;
- every post-transition enemy root is inside the combat rectangle, including
  forced raw points in the retired entrance strip and dark-policy cases;
- default generated runs own this transition, while every mod/custom Arena is
  a negative member; and
- browser proof must physically cross the entry Gate, trigger Solomon, observe
  camera contraction, attempt a return, and inspect every enemy root against
  the authoritative combat rectangle.

### Web projection boundary

The authoritative Website server does not own the native Arena light raster
queried by placement policy 0. Its requested confined placement path therefore
uses the recovered collision/ring search but does not claim exact
dark-versus-light candidate identity or the native 350-unit fallback rerun.
The web's retained half-unit mobility probe compensates for collision shapes
that have not yet been recovered as exact native actor geometry. Both are
explicit boundaries; the native branches remain catalogued above rather than
being silently described as implemented parity.
