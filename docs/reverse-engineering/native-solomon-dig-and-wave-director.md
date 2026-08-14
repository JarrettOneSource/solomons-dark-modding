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

1. Boneyard generation places a `Solomon_Dig` actor and compiles the retail
   wave schedule into a serialized TimeLine graph.
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
spawns ten Skeletons at graph time 0, schedules five more across four seconds
at graph time 5, pauses in live-count mode 3 with threshold 4 at time 9, then
sets the next locating policy and enters label `Wave1`. The opening is already
part of the TimeLine; adding a separate browser-authored “wave one delay”
would double the stock sequence.

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
