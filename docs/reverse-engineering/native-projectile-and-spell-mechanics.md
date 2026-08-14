# Native projectile and spell mechanics

- Status: **G2 closed by static RE plus live solo goldens**
- Campaign: `spellre-20260804`
- Live-capture source SHA: `1b9d454da60afefa2cb5f01a0f6e8ce829efebe6`
Canonical fixture: `tests/fixtures/webgame/projectile-goldens.json`

This document is the browser-rebuild contract for the five native primary
elements: Ether, Fire, Air, Water/Frost, and Earth. It separates gameplay
actors from transient render actors, and it treats a native tick as one
distinct `local_player_tick_count` observed from `runtime.tick`. Duplicate Lua
callbacks for the same native tick are discarded in the fixture.

The findings combine read-only headless Ghidra work in the campaign replica
with live `spr-*` solo sessions. No gameplay behavior changed and no new
runtime probe seam was needed. The captures used the existing Lua exec,
`sd.world`, `sd.debug`, `sd.input`, and manual-run enemy seams. An independent
Frost start/stop capture used real foreground Windows mouse input.

## Shared cast pipeline

The stock input-to-primary path is:

1. The player action ticks at `0x0044B370`, `0x0044B580`, or `0x0044B770`
   consume the held/released primary state.
2. They call the `PlayerWizard` virtual at slot `+0x58`, implemented at
   `0x00550180`.
3. Casting action modes `3`, `6`, and `9` enter the primary dispatcher at
   `0x0054CAF0`. That dispatcher invokes the equipped item virtual at `+0x68`
   and selects the handler by native skill id.
4. One-shot handlers create their gameplay actor through
   `GameObjectFactory_Create` at `0x005B7080`, set group/owner state, and
   register the actor through `0x0063F6D0`. Held handlers instead repeat their
   query and application work on every action tick.

| Element | Skill id | Primary handler | Gameplay representation |
| --- | ---: | --- | --- |
| Ether / Magic Missile | `8` | `0x0053CFE0` | factory type `0x7D3`, constructor `0x005E4990` |
| Fire / Fireball | `16` | `0x0053DC60` | factory type `0x7D4`, constructor `0x005E0970` |
| Air / Lightning | `24` | `0x0053F9C0` | retained-target hitscan; no projectile actor |
| Water / Frost Jet | `32` | `0x00543860` | held cone query; no projectile actor |
| Earth / Boulder | `40` | `0x00544C60` | factory type `0x7D5`, constructor `0x005FA270` |

The common emitter helper at `0x0053B830` takes its origin from the active
wizard cast glyph, not merely from the actor center. It chooses a directional
glyph from the current cast animation using integer frame selection equivalent
to `((animation_frame + 7) / 15) % 24`, scales the glyph-local point by the
wizard actor scale at `+0x74`, and adds the wizard world position. This is why
two otherwise identical Fire casts can occupy visibly different emitter lanes.
Browser parity must derive the emitter from the current directional cast frame
before applying the element-specific offsets below.

Three details of `0x0053B830` matter to a port and are not implied by the
sentence above.

First, the wrap is a **single conditional subtraction**, not a modulo: the
native code computes `index = (frame + 7) / 15` and then applies
`if (index > 23) index -= 24` exactly once. That agrees with `% 24` only while
the quotient stays below `48`; above it the native index leaves the `0..23`
range instead of wrapping again. Write the subtraction, not the modulo.

Second, the record actually indexed is `index + K * 24`, where `K` is a second
integer derived from a float by the same `0x00747360` truncation helper the
frame selection uses. The helper reads its operand off the x87 stack, so the
decompile does not name `K`; what is certain is that the emitter address space
is banked in groups of `24` directions and that the direction index alone does
not identify the glyph. The live fixtures agree: at one fixed facing, Ether and
Fire resolve to the same emitter-local point while Earth resolves to a
different one, which a direction-only formula cannot produce.

Third — and this is the part that blocks a port — **the glyph-local point is
loaded asset data, not a constant in the executable.** The helper walks a
record of stride `0xC4`, takes the point list at `+0xA8` (count at `+0xAC`,
asserted `>= 2`), and reads **point index 1** at `+8`/`+0xC`. Only then does it
apply `wizard_xy + scale(+0x74) * point`. A second path exists when the queried
object's `+8` field equals `0x1B5C`: it fetches the point through the virtual
at `+0x24` with the same `index + K * 24` and adds it to the wizard position
**without** the `+0x74` scale multiply. So there is no 24-entry constant table
to transcribe; a browser port must source these points from the same animation
assets the native game loads, or capture them per facing.

## Mechanics at a glance

| Element | Origin and initial motion | Contact shape and cadence | Lifetime / repeated-hit rule |
| --- | --- | --- | --- |
| Ether | cast glyph emitter plus local `(0,+10)`; aim probe `100` units forward; speed `3 * (1 + mSpeed/100)` | actor radius `15`; target proximity every tick with `6`-unit probe; terrain every fifth tick using a five-tick lookahead | no fixed timer found; contact consumes unless pierce remains; an age over `200` changes the candidate mask |
| Fire | cast glyph emitter plus local `(0,+10)`, then `20` units along aim; velocity is aim unit vector times `4.5` | actor radius `22.5`; candidate query radius `20` every tick in the current spatial cell; terrain every fifth tick with five-tick lookahead | no fixed timer found; first impact removes the Fireball; status/area work is dispatched before removal |
| Air | cast origin to retained target/aim line; instantaneous, so no velocity or spread | line/world clip at `0x00524D70`; target/chain query every held tick at `0x00641340` | exists only while the primary is held; each chained hop scales the next damage by `0.6`; a render-only fade lives `10` ticks |
| Water/Frost | cast origin and aim define a rank-scaled cone; instantaneous, so no velocity | rank-1 query reach is `205` world units; candidate cone `0x00641B10`, mask `0x1082`, then per-target LOS; contact every held tick | start/sustain/stop channel; render particles outlive their source tick for about `32`–`33` ticks |
| Earth | charged actor is held at the cast emitter, then released straight along aim at speed `3` | held radius `15`; release radius is charge-scaled; recursive collision/query `0x00620B60` runs every flight tick | held until release even after full charge; no fixed flight timer found; distinct-target ledger allows residual pool to hit more than one target |

None of the three materialized primary projectiles has ballistic gravity or a
vertical arc. Ether can steer toward a target; Fire and released Earth advance
in the horizontal world plane. Air and Frost are query volumes, not actors
whose paths should be integrated.

**Heading convention.** Every `headingDegrees` column in the fixtures — wizard
and projectile alike — is measured clockwise from screen-up, not
counterclockwise from `+x`. The aim unit vector is

```text
aim = (cos(heading - 90 deg), sin(heading - 90 deg))   ==   (sin h, -cos h)
```

Applied to the captured wizard heading `287.59668`, that reproduces the stored
Fireball unit vector `(-0.953208208, -0.302314520)` to within `2.1e-8` — float32
serialization noise. Nothing else in this document restates the convention, and
using the ordinary `atan2` sense instead rotates every trajectory by 90 degrees
while still passing a magnitude check, so pin it in the port's first test.

**Reproduction status.** Integrating Fireball as
`p(t+1) = float32(p(t) + aim * 4.5)` from the fixture's first row reproduces
`trajectories.fire.rank1` and `.rank2` **bit-exactly on every compared tick**
(398 of 399 rows each; the final row repeats the previous position with a
frozen `ageTicks` because the actor is already gone). Ether's `baseSpeed *
movementScalar` likewise matches its measured per-tick displacement of `3.0`
world units. The flight model in this document is therefore portable as
written; the spawn point is not — see Not Yet Reversed.

## Ether: Magic Missile

`0x0053CFE0` asks `0x005B7080` for type `0x7D3`. The actor ticks at
`0x005FD270` and draws at `0x005E0460`.

The initial point is the common glyph emitter with local `(0,+10)` applied.
Target acquisition probes `100` units ahead of the caster. Initial speed is

```text
speed = 3 * (1 + mSpeed / 100)
```

and the rank-1 and controlled rank-2 captures both retained `3.0` world units
per native tick. When more than one missile is emitted, directions alternate
symmetrically around aim. The normal angular step is `20` degrees; when the
quantity is below four, the step is `30` degrees. This fan is the only initial
spread. Homing/turn work then runs on every tick.

The gameplay actor radius is `15`. The target-proximity pass runs every tick
with the native `6`-unit probe constant. Terrain is tested every fifth tick
against a five-tick forward segment. There is no recovered hard lifetime: both
rank fixture windows contain `604` consecutive native ticks. Once age exceeds
`200`, the candidate mask broadens from `2` to `6`; that is a search-policy
transition, not expiration.

Pierce is held in the actor byte at `+0x161`. A zero value makes the first
accepted contact remove the missile. A positive value is decremented; speed
and remaining damage are scaled, the actor is advanced beyond the contact,
and it retargets without selecting the same contact as though it were new.
Thus browser code must not model every Magic Missile as unconditionally
single-hit.

## Fire: Fireball and residual fire

`0x0053DC60` creates type `0x7D4`. The Fireball ticks at `0x005FDD90`, impacts
at `0x005E5160`, and uses the projectile draw paths at `0x006099C0` and
`0x005E50D0`.

The handler starts from the common cast glyph emitter plus local `(0,+10)`,
then advances the spawn point `20` world units along the normalized aim vector.
It stores that unit vector in the projectile and advances it by the native
double constant `4.5` each tick. There is no random angular spread.

The actor collision radius is `22.5`. Every tick it queries a `20`-unit target
probe, but the candidate enumeration is restricted to the projectile's current
spatial cell. Geometry is tested every fifth tick with a five-tick lookahead.
This cell restriction plus the directional glyph emitter explains the misses
documented in
[`multiplayer-fireball-contact-2026-07-26.md`](multiplayer-fireball-contact-2026-07-26.md):
the miss traveled for `128` ticks without entering impact, while successful
client casts reached one native impact and exactly `4.0` damage. The apparent
`8.0` sample there was two retained serialized `4.0` contacts, not a double
Fireball impact.

There is no fixed Fireball timer in the recovered tick. The live unobstructed
rank-1 and rank-2 paths each remain materialized for all `399` captured ticks.
An accepted actor or terrain impact calls `0x005E5160`, seeds the primary
contact, invokes the fire/status helper `0x00624300`, optionally performs the
area lane, dispatches through `0x0063E7D0`, and removes the Fireball. The
per-tick Fireball trail is transient `Anim_FireParticle`/`ZAnim` presentation;
it is not a persistent `Fire_Goodguy` gameplay actor.

The new contact golden observed one `4.0` HP transition at a projectile-to-
target-center distance of `30.5124151`. The target took no additional HP
damage during the following `499` observed ticks. That observation constrains
HP application only: the impact still calls the native fire/status helper, so
the browser must not erase non-HP status or area semantics merely because this
stationary skeleton fixture showed no later HP decrement.

### `Fire_Goodguy` (`0x7EE`) trail actors

`Fire_Goodguy` is a separate positive-lifetime gameplay actor. Factory type
`0x7EE` constructs at `0x005E76C0` on top of the Fire base constructor
`0x005E7130`; it ticks at `0x005FF050`, applies its area/contact pulse at
`0x005FF1D0`, and draws at `0x00610F90`.

Its native fields establish these semantics:

- animation phase `+0x140` advances by `0.25` per tick;
- lifetime `+0x144` starts at `2.0` and falls by `0.01` per tick, for `200`
  native ticks;
- alpha `+0x148` rises by `0.05` per tick to `1.0`;
- scale is stored at `+0x150`, damage at `+0x158`, and draw alpha at `+0x15C`;
- while damage is positive, every tick divisible by three performs a
  `32 * scale` radius contact pass and dispatches through the same fire helper
  and contact lane. A target that remains inside may therefore be hit on more
  than one pulse.

This is the positive-lifetime trail actor observed by the botmana campaign.
The corrected stock secondary dispatcher at `0x0054CC50` creates live damaged
`0x7EE` actors while Firewalker remains active; Fire Wall also creates them.
The earlier byte-toggle experiment described in
[`beta32-bot-mana-and-lone-target-handoff-2026-08-04.md`](../bugs/beta32-bot-mana-and-lone-target-handoff-2026-08-04.md)
did not reproduce that stock path. A browser implementation must preserve the
distinction between Fireball's cosmetic particles and these damaging residual
actors.

## Air: Lightning

`0x0053F9C0` performs the Air primary directly. It does not call the gameplay
object factory for a projectile. The caster retains a primary target, clips the
aim/target segment against the world through `0x00524D70`, queries chained
targets through `0x00641340`, and applies contact on every sustained handler
tick. There is consequently no spawn radius, velocity, projectile lifetime,
or ballistic spread to emulate.

The browser contract is a per-tick ordered ray/chain:

1. recompute the cast origin and the retained target/aim endpoint;
2. clip the primary line against world geometry;
3. apply the primary contact if eligible;
4. select eligible chained contacts in native order, excluding already-used
   targets; and
5. multiply the next hop's damage by native double `0.6`.

The channel exists while primary input remains held. Releasing it stops new
contact queries immediately. `Anim_FadeLightning` is render-only: its lifetime
and alpha start at `1.0`, fall by `0.1` per tick, and therefore persist for ten
ticks after emission. It increments its procedural angle by `1` per tick and
uses the mesh builder at `0x00536380`; it has no atlas sprite id.

The fixture records the ray state on every native tick at rank 1 (`229` rows)
and controlled rank 2 (`259` rows), rather than inventing a projectile actor.

## Water: Frost Jet channel

The Water primary is the Frost channel at `0x00543860`. Like Air, it is a held
query and creates no gameplay projectile. The handler derives a cast origin
and forward direction, builds its rank-scaled cone, enumerates candidates with
`0x00641B10`, and uses group mask `0x1082` for the normal player-owned path.
Rank 1 reaches `205` world units (`180` base plus the `25` rank contribution).
Each candidate then passes an individual line-of-sight check before contact.
The complete query and damage application repeat every held native tick.

The absence of a projectile radius is intentional. The parity equivalent is
the native cone reach/width plus per-target LOS, not a moving circle. There is
also no velocity, gravity, pierce counter, or independent gameplay lifetime.
Multiple targets can be contacted in the same tick because the handler walks
the eligible cone list.

### Start, sustain, and stop

The exact audio/selection state machine remains the one established in
[`multiplayer-frost-channel-stop-2026-07-26.md`](multiplayer-frost-channel-stop-2026-07-26.md):

- Water selection is `0x20`; the primary skill is `32`, with progression entry
  `1012`.
- Selecting Water first calls the stop routine harmlessly at zero refcount,
  then starts `sounds\iceloop__loop` at `0x00549BB2` in audio registry slot
  `+0x182C` (live registry index `161`).
- Sustained ticks leave primary id `32`, loop active, and refcount `1` while
  executing the cone/contact handler once per native tick.
- Release must publish the real `0x20 -> 0` transition. `0x00549725` stops the
  same loop, leaving active false and refcount zero. Current and previous
  selection live at player offsets `+0x270` and `+0x274`.

The previously accepted multiplayer stop latencies were `16`, `16`, `31`,
`16`, and `16` ms, all inside one `50` ms snapshot interval. This campaign's
deterministic 150-tick rank-1 timeline ran exactly `1500` ms from native start
to native stop and recorded one harmless pre-start stop plus one release stop.
The independent real-mouse run recorded primary `0 -> 32 -> 0`, one start, one
stop, active duration `110` ms, and final refcount zero.

`Anim_FrostJetEffect` and `Anim_FrostJetEffect_Over` are transient visual
actors emitted during sustain. Their initialized lifetime is about `1.25`
plus a small random term and drops by `0.04` per tick, yielding about `32`–`33`
ticks of visual persistence. Their lifetime must not extend contact: gameplay
ends on the input stop edge.

### 2026-08-14 Frost Jet presentation closure

This pass was performed read-only against the preserved retail
`SolomonDark.exe`, SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`,
in the analyzed Ghidra project `Decompiled Game/ghidra_project/SolomonDark`.
Fresh targets were the handler and its adjacent constructors/update/renderers:

| Owner | Address / native identity |
| --- | --- |
| held skill handler | `0x00543860` |
| shared emitter socket | `0x0053B830` |
| Normal constructor / vtable | `0x00453550` / `0x00784E84` |
| Over constructor / vtable | `0x00453840` / `0x00784EB4` |
| heading/velocity initializer | `0x00453800` |
| shared update | `0x00453670` |
| Normal render | `0x00457720` |
| Over render | `0x00457A00` |
| world obstruction clip | `0x00524D70` |
| uniform float / bounded integer / random sign | `0x00401310` / `0x00401170` / `0x004012C0` |
| heading unit vector | `0x00410500` |

The handler's bounded `Integer(4)` selection constructs Over only for result
`1`, so ordinary player casts produce 25% Over and 75% Normal particles. They
are separate world transients, not four animation frames of one object.

#### Rank-1 density, heading, spawn, and travel

The particle-count expression is option-sensitive:

```text
count = 1 - trunc((mWiden + 15) / (EnhancedEffects ? -10 : -20))
```

Neutral rank 1 has `mWiden == 0`, hence one particle per held tick when
Enhanced Effects is Off and two per held tick when it is On. This count does
not multiply the cone/contact query; it changes only presentation density.

For each particle:

```text
spread       = mWiden + 15                         // rank 1: 15 degrees
heading      = casterHeading + sin(worldTick * 65 deg) * spread
spawn        = exact Staff socket
             + U[0,10] * unit(casterHeading +/- U[0,45 deg])
speed        = 4 * (1 + (mWiden / 2.5) * 0.05)    // rank 1: 4/tick
lifetime[0]  = 1.25 + U[0,0.05]
lifetime[n]  = lifetime[n-1] - 0.04
```

When a tick creates two particles, the handler advances the input phase by
`65 / count` degrees before the second sample. This oscillating stream is
independent of the rank-1 `205`-unit cone reach. Particles move only about
`128`-`132` world units before expiry; the native visual does not interpolate
to the gameplay endpoint.

The phase advance is explicit in the handler instructions:
`0x005439D0..0x005439DA` loads the particle count, divides constant double
`0x00784D90` (fresh raw value `65`) by it, and stores the local step. The Over
and Normal branches consume the mutable phase at `0x00543A86` and
`0x00543BA3`; loop tail `0x005440A2..0x005440AE` decrements the count and adds
the stored step before the next creation. Enhanced Effects On therefore gives
the second particle a 32.5-degree-ahead sine input even though both particles
are born on the same world tick.

Only Normal creation computes a predicted path and calls `0x00524D70`.
Obstruction distance and point are stored at `+0x50` and `+0x54/+0x58`. When
update consumes the distance, it snaps to the stored point, chooses a randomly
signed perpendicular, halves velocity, and clears the pending contact. The
Over path skips that setup. This is cosmetic wall splay/ricochet and must not
be used as the Water damage owner.

#### Update fields and exact renderer passes

`Anim_FrostJetEffect` is `0x5C` bytes. Its presentation fields are:

| Offset | Initial value | Update |
| --- | --- | --- |
| `+0x1C` lifetime | `1.25 + U[0,0.05]` | subtract `0.04`; remove below zero |
| `+0x20` phase | `0` | Normal adds `0.05`; Over adds `0.025` |
| `+0x24/+0x28` velocity | heading unit times rank speed | position adds velocity; optional wall splay |
| `+0x2C/+0x30` heading | handler heading | unchanged by ordinary flight |
| `+0x3C` additive-core alpha | `0.75` | subtract `0.05` |
| `+0x40` core scale | `S = 0.5 + U[0,0.75]` | if lifetime `< 1`, add `2` |
| `+0x44` glint scale | `Q = (2 + U[0,1]) * S` | if lifetime `< 1`, multiply `0.95` |
| `+0x48` color ramp | Normal `1 + U[0,0.5]`; Over overrides it to `0` | subtract `2`, clamp at zero |
| `+0x4C` opacity multiplier | `1` | unchanged |

The core tint is `(max(0, 1 - colorRamp), 1, 1)`: Normal is cyan on
construction and white after the first completed update; Over is white from
construction. Both renderers pass the native heading to the registered sprite
draw and restore ordinary blending/white afterward.

Normal render `0x00457720` submits three ordered draws:

1. ordinary alpha, `BadGuys[30]`, particle position, scale `S`, alpha
   `min(lifetime^2, phase)`, cyan-to-white tint;
2. while `+0x3C > 0`, additive `BadGuys[30]` at the same transform, scale
   `0.5*S`, alpha `+0x3C`; and
3. additive `BadGuys[28]` at `position + 3*velocity`, scale `min(Q,1)`, alpha
   `min(10*lifetime,1)`.

Over render `0x00457A00` omits the half-core draw:

1. ordinary alpha, `BadGuys[30]`, scale `S`, alpha
   `0.5*min(lifetime,phase)`, white; then
2. additive `BadGuys[28]` at `position + 3*velocity`, scale `0.25*Q`, alpha
   `min(3*min(0.5*phase,lifetime),1)`.

The draw-state byte set to `1` resolves through `0x004208A0` to D3D
`SRCALPHA, ONE`; zero is ordinary `SRCALPHA, INVSRCALPHA`. These objects enter
the common transient/world lists and are culled, Y-sorted, camera-transformed,
and locally lit by the common world dispatcher. They are not screen overlays.

#### Exact atlas records and learned-branch separation

`BadGuys` inline records use header `0x38` and stride `0xC4`:

| Record | Inline address from `DAT_00819978` | Registered canvas / origin | Role |
| ---: | ---: | --- | --- |
| 30 | `+0x1730` | `93 x 145`, registered paste `(0,0)` | rank-1 Frost core, both classes |
| 28 | `+0x15A8` | `10 x 11`, registered paste `(0,2)` | rank-1 forward glint, both classes |
| 32 | `+0x18B8`, assigned at `0x00543F57` vicinity | `29 x 30`, paste `(5,4)` | learned Hail (`+0x8A8`), not Frost stream |
| 14 | `+0x0AF0`, assigned at `0x00544866..0x00544870` | `92 x 91`, paste `(11,3)` | learned Cold Aura (`+0x8B0`), not Frost stream |

The Website extractor's full registered canvases hash as record 30
`62aac46ed0f3436cf39023b2c93e8c02b8dee3c0611e74179cc5af92793470b5`
and record 28
`e118b2feb22c5ffd4c5f0981e20044b8df6181ead01c572965143ad959e24d60`.
Any rank-1 primary implementation cycling records 32 or 14 is mixing learned
branches into the base spell.

#### Enhanced Effects shipped default and browser policy

`0x00B3BCAD` is the literal `ENHANCED EFFECTS` Boolean bound by Settings at
`0x005DAD45` and Controls at `0x005DB5DB`. The setting is persisted under the
misleading key `Game.FastCPU`. At `0x005BB310..0x005BB34F`, the settings loader
uses capability byte `0x00B3BCAE` as the missing-key fallback. The executable's
embedded `DEFAULTS|...|ENDDEFAULTS` block does not contain `Game.FastCPU`; the
recognized shipped Windows path initializes the capability byte to `1`.
Therefore a new shipped Windows profile defaults Enhanced Effects On. A
preserved user sample with `Game.FastCPU=false` and Enhanced Effects Off proves
the value remains configurable after first load.

The current Website has no gameplay performance-settings owner for this byte.
Until such a system exists, its native-parity primary uses the shipped default
of two independent particles per held tick. That is a named product policy,
not a claim that stock cannot run the one-particle Off path.

#### Visual evidence and remaining limits

The preserved instrumented-stock frame
`D:\codex-evidence\beta28-release-20260731\acceptance\screenshots\client-b-water-bot-retail-wave.png`
is 1606 x 929 RGBA, SHA-256
`116eb2378541aef6c436f20fa03f7d62a5c83b6222b1e50ddffb35fe27f6eb3b`.
It corroborates a short blue-white layered spray, but foliage occludes part of
the cast and the run is not clean stock. A fresh direct-retail On/Off capture
was deferred after unrelated `SolomonDark.exe` PIDs `18792` and `23472` were
found in foreign staged runtimes; neither process was disturbed.

Closed facts are object ownership, density branches, sprite records,
registration, field recurrences, render order, blends, heading, unobstructed
motion, contact separation, audio, and teardown. Still open are a clean-stock
On/Off pixel receipt, the exact per-session RNG sample sequence, and a browser
terrain-query seam for cosmetic Normal wall splay. Deterministic web samples
may preserve the recovered random distributions using authoritative spell
identity, but must not be presented as the retail RNG sequence. The born
direction is not identity-derived: authority must evaluate the native
world-tick phase plus the per-tick particle ordinal, while radial spawn jitter
remains relative to the caster's un-wiggled base heading.

## Earth: Boulder

`0x00544C60` creates type `0x7D5`. Construction is at `0x005FA270`, the held
and flight tick is `0x00609D30`, release finalization is `0x005E5450`, recursive
collision/contact is `0x00620B60`, and drawing is at `0x0060AC40`.

The Boulder is created at the cast emitter and remains held there while charge
grows. Release gives it a normalized aim vector and constant speed `3.0`.
There is no random spread, gravity, or arc.

### Exact charge-time to magnitude curve

Charge is a float32 field at `Boulder + 0x74`. At construction:

```text
C[0]      = float32(0.18)
growth    = float32((wizard + 0x2A0) * 0.5 * cast_speed)
C[n + 1]  = min(1.0, float32(C[n] + float32(growth * 0.0025)))
```

For the neutral rank-1 fixture, `(wizard + 0x2A0) == 1` and
`cast_speed == 1`, so `growth == 0.5` and each recurrence adds float32
`0.00125`. The recurrence, rather than an algebraically simplified decimal,
is the exact browser contract because every addition rounds to float32.

| Requested input hold | Charge updates before release/full | Exact observed magnitude | Release/full timing |
| ---: | ---: | ---: | --- |
| `2` frames | `97` due to the stock minimum casting action | `0.30124989151955` (`0.301249892` serialized) | first flight at fixture row `97` |
| `170` frames | `170` | `0.39249980449677` (`0.392499804` serialized) | first flight at row `170` |
| full (`700`-frame held window) | `656` to clamp | `1.0` | first full row `655`, `6547` ms after the first sampled row; released at row `700` |

The prior live gate in
[`multiplayer-earth-charge-baseline-2026-07-26.md`](multiplayer-earth-charge-baseline-2026-07-26.md)
reported `charge == max_charge == 1.0` after `6.583` seconds. The small wall-
clock difference is input/sample-boundary timing; both observations pin the
same 656-update float32 curve. A controlled rank-2 170-frame capture reached
the identical `0.392499804` charge, confirming that rank changes spell
magnitude/damage inputs but not this neutral charge recurrence.

While held, actor collision radius stays `15`. Finalization scales body radii
to `500 * C`. The immediate release/contact lane uses `45 * C` (`50 * C`
times `0.9`); if the actor survives into its normal flight collision tick,
`0x00620B60` updates the collision radius to `75 * C`. Thus the three
unobstructed first-flight rows record radii `22.5937424`, `29.4374847`, and
`75.0`, while the full-charge immediate-contact golden records the earlier
release radius `45.0`.

Flight collision is evaluated every native tick. A per-Boulder target list at
`+0x200` prevents the same target from consuming the pool twice. A successful
contact reduces the reusable damage pool; if a positive pool remains, the
Boulder can continue and contact a different target. That is residual
multi-target behavior, not same-target periodic damage. There is no recovered
fixed flight expiration.

Damage scaling from charge is already derived bit-exactly in
[`earth-boulder-damage-formula-2026-07-27.md`](earth-boulder-damage-formula-2026-07-27.md).
This document deliberately does not derive it again. The accepted post-fix
host golden endpoints are `0.90625` for the two-frame input,
`1.5390625` for the 170-frame hold, and exactly `10.0` at full charge. The new
full-charge contact fixture independently observes exactly `10.0` at charge
`1.0`, release radius `45.0`, and projectile-to-target-center distance
`51.8984223`.

## Damage application path and accepted goldens

All spell-specific handlers converge on the existing native application ABI:

1. `0x006246F0` clears/seeds the shared contact globals at
   `0x0081C6E0..0x0081C6F8`.
2. The handler writes source, element flags, magnitude lanes, and effect
   metadata. Fire additionally calls `0x00624300`; Earth prepares its two
   contact lanes in `0x00620B60`.
3. `0x0063E7D0` validates same-world contact and invokes target virtual slot
   `+0x4C`.
4. A normal enemy receives that call in `Badguy::Contact` at `0x0048A290`,
   where resistances/status and HP application occur.

The multiplayer ownership/materialization boundary remains documented in
[`multiplayer-primary-projectile-materialization-2026-07-26.md`](multiplayer-primary-projectile-materialization-2026-07-26.md).
It is possible for observer presentation materialization and authoritative
damage convergence to have different outcomes; browser code must not use a
sprite's existence as proof that damage was or was not applied.

These are cited golden numbers, not new derivations:

| Element/window | Existing accepted golden | New solo contact cross-check |
| --- | --- | --- |
| Fire one-shot | exactly `4.0` in `multiplayer-fireball-contact-2026-07-26.md` | `4.0`, error `0`, epsilon `0.000001` |
| Ether window | host `1.2001953125`, client `1.1000976562` in `multiplayer-element-damage-2026-07-26.md` | `1.1999969`, error `0.0001984125`, epsilon `0.00025` |
| Air 170-tick window | host `4.2333984375`, client `4.18359375` in `multiplayer-element-damage-2026-07-26.md` | `4.2502594`, one-tick error `0.0168609625`, epsilon `0.026` |
| Water/Frost 170-tick window | host `4.2333984375`, client `4.2084960938` in `multiplayer-element-damage-2026-07-26.md` | `4.2502594`, one-tick error `0.0168609625`, epsilon `0.026` |
| Earth host contacts | `0.90625`, `1.5390625`, `10.0` in `earth-boulder-damage-formula-2026-07-27.md` | full `10.0`, error `0`, epsilon `0.000001` |

Air and Frost apply roughly `0.025` per native tick in these rank-1 sustained
windows. Their epsilon admits exactly one input-sampling tick because the old
multiplayer and new solo 170-frame windows straddle that boundary. It is not a
general damage tolerance. One-shot epsilon instead covers only float32 text
round-trip/HP storage.

## Presentation hooks for browser parity

The native projectile/effect draw paths ultimately submit `Puppet`/`ZAnim`
glyphs to the world queue. Browser ordering must therefore preserve actor
world position, Y/bias sort, culling, tint, alpha, and light behavior described
in [`world-sprite-render-pipeline.md`](../re/world-sprite-render-pipeline.md).
Drawing the following frames as a screen-space overlay is not equivalent.

| Mechanic | Native sprite/atlas hook | Frame cadence / ownership |
| --- | --- | --- |
| Ether missile | `BadGuys[53]` | gameplay actor position/heading; world-queued |
| Fireball | main `BadGuys[255..266]`; auxiliary `BadGuys[110..112]` | main frame `(age_ticks / 3) % 12`: 3 ticks/frame, 36 ticks/cycle; cosmetic particles are separate transients |
| Air lightning | no atlas entry | procedural mesh at `0x00536380`; fade lifetime/alpha `1.0`, minus `0.1` per tick |
| Frost Jet | `BadGuys[30]` core and `[28]` forward glint only; `[32]` Hail and `[14]` Cold Aura are learned branches | one transient/tick with Enhanced Effects Off or two/tick with it On; each moves at rank-1 speed `4` and remains about 32–33 ticks |
| Boulder | body `BadGuys[86]`; debris `[168..171]`; auxiliary `[18]`, `[2008..2010]` | body scale follows live charge; do not replace it with a fixed-size frame animation |
| `Fire_Goodguy` | `DeadHawg[46..77]` | phase `+0.25`/tick (four ticks per integer phase); alpha ramps independently |

The sprite ids identify native array entries, not standalone image filenames.
The browser asset bridge must map them through the recovered atlas/texture
registration data while retaining the world-queue semantics.

## Golden fixture contract

`tests/fixtures/webgame/projectile-goldens.json` records the live evidence in
columnar tick tables (`columns`, `rows`, `count`) to keep repeated field names
out of the large fixture. Its header pins:

- instance names `spr-fire-r1-world`, `spr-ether-r1`, `spr-earth-r1`,
  `spr-air-r1`, `spr-water-r1`, and the five `spr-*-contact` sessions;
- source SHA `1b9d454da60afefa2cb5f01a0f6e8ce829efebe6`;
- local UDP `52281`, unused peer port `52282`, and
  `SDMOD_DISABLE_AUDIO=1`;
- Lua-exec/runtime-tick capture plus deterministic existing input seams, with
  a separate real-mouse Frost run;
- `runtimeSourceSeamAdded: false`;
- the controlled live rank-entry write used only to reach rank 2; and
- epsilons: `0.0001` world unit for serialized float32 trajectories, `16` ms
  for Windows tick timestamps, element-specific contact values shown above.

It contains rank-1 and rank-2 tick series for Ether and Fire actors, Air rays,
and Frost channel state; three rank-1 Earth charge/release series plus a
rank-2 170-frame series; the independent Frost mouse timeline; and contact
events with world distances and resulting HP changes. These are browser
goldens, not runtime automation instructions: tests should compare the
reimplemented mechanics to the stored native tick sequence within the header's
explicit epsilon and should never silently widen it.

## The cast glyph emitter

The emitter is **asset data plus a fully determined index**. Nothing about it is
fitted to the goldens: the index arithmetic is read from the instruction stream
at `0x0053B830`, the element offsets are `double` constants read out of the PE,
and the point table is a block of the shipped `images/Clothes.bundle`. The
goldens are then used only to *check* the reconstruction, which they do exactly.

### Facing index

```text
facing = ((int)actor.heading_degrees + 7) / 15     // truncation happens BEFORE the +7
if (facing >= 24) facing -= 24                     // one conditional subtract, NOT a modulo
```

```asm
0053b838  fld   dword ptr [edi + 0x6c]   ; heading in DEGREES, float32
0053b83b  call  0x747360                 ; CRT float->int truncation
0053b840  lea   ecx, [eax + 7]
0053b843  mov   eax, 0x88888889          ; \ signed divide by 15
0053b848  imul  ecx                      ; |
0053b84c  sar   edx, 3                   ; /
0053b856  cmp   esi, 0x18
0053b859  jl    0x53b85e
0053b85b  sub   esi, 0x18
```

`0x00747360` is the **CRT float-to-int truncation helper**, not an animation
accessor. Because its operand arrives on the x87 stack, Ghidra renders every
call to it as an argument-less `FUN_00747360()`; that is why earlier passes
could see `(x + 7) / 15` and `K * 24` but could not name either input. Read the
disassembly, not the decompile, for this function.

At the fixture's heading: `(int)287.59668 = 287`, `287 + 7 = 294`,
`294 / 15 = 19`. Every projectile capture in `projectile-goldens.json` therefore
sits at facing `19`, which is what made the single-facing limitation below
invisible in the raw numbers.

### Bank index — three arrays, selected by the sprite set

The helper picks one of three point arrays. The selector is
`sprite_set = *(void**)(record->+0x30 ... ->+4)`, reached from `actor->+0x1FC`
or, when that is null, from the per-element record at
`*(DAT_0081c264) + 0x1410 + 0x64 * actor->element[+0x5C]`.

| Sprite set | Array base / count | Bank `K` | Result |
| --- | --- | --- | --- |
| null | `[g+0x5A0]` / `[g+0x5A4]` | none — index is `facing` | `wizard + scale * point` |
| `->+8 == 0x1B5C` | virtual call `vt+0x24` | `K = (int)actor->+0x238`, **unclamped** | `wizard + point` — **no scale** |
| otherwise | `[g+0x5D0]` / `[g+0x5D4]` | `K = (int)clamp(actor->+0x238 - 14.0, 0.0, 2.0)` | `wizard + scale * point` |

where `g = DAT_00819980`, `index = facing + 24 * K` (emitted as
`lea eax,[eax+eax*2]; lea esi,[esi+eax*8]`), and the clamp constants are
`14.0` at `0x0078C560` and `2.0` at `0x007DE838`.

The goldens resolve to `K = 7`, which the third row cannot produce, so the
fixture's wizard takes the **`0x1B5C` path**: index `facing + 24*K` with `K`
unclamped, and the point added to the wizard position with **no `+0x74` scale
multiply**. A port that applies the scale on this path is wrong at any scale
other than `1.0`, which is exactly the value the fixture's wizard has — so the
goldens cannot detect that mistake. Take it from the disassembly:

```asm
0053b8bc  fld   dword ptr [edi + 0x18]   ; wizard.x
0053b8bf  fadd  dword ptr [eax]          ; + point.x        (no scale)
0053b8c8  fld   dword ptr [edi + 0x1c]   ; wizard.y
0053b8cc  fadd  dword ptr [eax + 4]      ; + point.y
```

### The record

Common to all three paths: stride `0xC4`; point count at `+0xAC`, asserted
`> 1`; point-list pointer at `+0xA8`; the helper reads **point index 1**, i.e.
bytes `+8`/`+0xC` of the list.

### The asset

`images/Clothes.bundle`, parsed with the record grammar already implemented in
`tools/extract_bundles.py` (45-byte common header, `point_count` as `<I` at
`+0x29`, then `point_count` × `<2f`), yields 3724 records. The apparent first
five-bank run crosses a native-array boundary; G4 recovered the consumers:

| Records | Count | Banks | Points/record | Array |
| --- | --- | --- | --- | --- |
| `#460..#483` | 24 | 1 × 24 | 2 | `[g+0x590]`, the unarmed hand/socket reference bank used by wizard composition |
| `#484..#603` | 120 | 5 × 24 | first four banks have 2; final bank has no usable list | `[g+0x5A0]`, the bare-hand cast/attachment banks; the originally noted `#484..#579` portion is its first four banks |
| `#796..#867` | 72 | **3 × 24** | 2 | `[g+0x5D0]`, the wand hand-to-tip banks; point 1 is the cast emitter and `K` is clamped to `{0,1,2}` |
| `#3244..#3483` | 240 | **10 × 24** | 3 | the Staff type `7004`/`0x1B5C` socket banks; point 1 is the staff orb/emitter and `K` is unclamped |

Thus `#460..#579` is wizard bare-hand composition, not an enemy attachment,
and `#796..#867` is the wand. The 3-bank clamp in the instruction stream and a
3 × 24 run in the asset are independent facts that agree. The 240-record block is bounded by records that
carry no usable point list (`#3243` has 0 points, `#3484` has 1), so its base is
pinned by the asset itself rather than by the fit — without that boundary,
goldens at a single facing would pin only `base + 24*K`, not `base` and `K`
separately.

Extraction recipe for a port: take record `#3244 + 24*K + facing` of the common
stream and read point index 1. The two records the goldens exercise are
`#3263` (`K=0`) → `(-45.5, -15.5)` and `#3431` (`K=7`) → `(-41.5, -34.5)`. The
full 10 × 24 table is not reproduced here; extract it from your own copy of the
asset with the recipe above.

### Element offsets, as PE constants

The spawn is `emitter + element_local`, and the locals are `double` constants,
not fits:

| Element | Local | Source |
| --- | --- | --- |
| Ether, Fire | `(0, +10)` | as documented in the flight model above |
| Earth | `(0.0, +15.0)` | `0x007DE840` = `0.0`, `0x00784D80` = `15.0` |

Fire additionally pushes `20` units along aim. The Earth path carries its own
conditional `20.0 * (cos θ, -sin θ)` push (`20.0` at `0x007DE920`, direction
built by `0x00410500`) gated on the same sprite-set selector being null; the
fixture never takes that branch, so it is documented but unexercised.

### Verification against the goldens

Replaying `projectile-goldens.json` through the reconstruction — undo the
elapsed first tick of travel, subtract the element local and Fire's along-aim
push, and look the residual up in the extracted table — resolves **every**
capture to a single `(bank, facing)` cell:

| Capture | Resolved | Error |
| --- | --- | --- |
| `ether.rank1`, `ether.rank2` | bank 7, facing 19 | `3.60e-05` |
| `fire.rank1`, `fire.rank2` | bank 7, facing 19 | `3.84e-05` |
| `earth.rank2` + 3 × `rank1ChargeCaptures` | 1137/1137 held samples exact | `0` |

All are inside the fixture's own `trajectoryWorldUnits` epsilon of `1e-4`.
G4's independent
[`animation-goldens.json`](../../tests/fixtures/webgame/animation-goldens.json)
then forces headings `0,15,...,345`, calls retail `0x0053B830` after each write,
and matches all 24 returned points to Staff bank 7 with residual at most
`1e-4`; every facing is now `observed`, not `derived_only`. Its heading-359
sample observes the one-subtract wrap to facing zero. The same fixture's
per-fixed-tick Player lane names `actor+0x238` as the equipment/body pose
selector and observes the complete Staff Cast 1 branch `0 -> 1 -> 8 -> 7 -> 0`.
The earlier Earth recorder samples only its callback/held lane: it resolves
bank `0` on the first sample and bank `7` thereafter, so it did not observe the
intervening action poses.

One trap worth naming, since it cost a full debugging cycle: Fire's
`velocityX`/`velocityY` columns store the aim **unit vector**, not the per-tick
step. The step is that vector times `4.5` (consistent with the flight model
above, where consecutive samples differ by `4.500010`). Integrating the stored
columns literally yields a fireball 4.5× too slow and an emitter that resolves
to nothing.

This mattered rather than being cosmetic: the spawn point decides contact, and
this document attributes the observed Fireball misses in
[`multiplayer-fireball-contact-2026-07-26.md`](multiplayer-fireball-contact-2026-07-26.md)
partly to the directional emitter.

## Not Yet Reversed

The directional Staff emitter is closed analytically and live for all 24
facings by G4. Still unexercised by a live emitter golden are the null/bare-hand
path (flat `[g+0x5A0]` array, no bank term), the clamped wand `[g+0x5D0]` path,
and the Earth conditional along-aim push described above. Their consumers and
index rules are statically identified; this is a live-coverage residual, not
an unnamed G4 attachment run.

## Evidence inventory

- Live raw captures and launch/cleanup records:
  `D:\codex-evidence\spellre-20260804\live\` and
  `D:\codex-evidence\spellre-20260804\lifecycle\`
- Read-only headless Ghidra transcripts:
  `D:\codex-evidence\spellre-20260804\static\ghidra-primary-dispatchers.log`,
  `ghidra-primary-constants.log`, `ghidra-projectile-lifecycles.log`,
  `ghidra-projectile-constants.log`, `ghidra-effects-and-application.log`, and
  `ghidra-remaining-ambiguities.log`
- Repository fixture:
  `tests/fixtures/webgame/projectile-goldens.json`

## 2026-08-14 web primary-cast PoC consumption contract

This section records the exact native boundary consumed by the Website's first
player-casting implementation. It does not reopen the closed G2/G4 campaigns.
The preserved retail executable was hashed again before implementation and
matched the fixture source exactly:
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
A fresh read-only headless Ghidra pass against that image decompiled the five
primary handlers (`0x0053CFE0`, `0x0053DC60`, `0x0053F9C0`, `0x00543860`,
`0x00544C60`), the Magic Missile and Boulder render paths (`0x005E0460`,
`0x0060AC40`), the Fire Missile render path (`0x006099C0`), and the procedural
Lightning builder (`0x00536380`). Their dispatch, constants, actor ownership,
and render families agree with the durable goldens and tables above.

### Shared cast actions and emitter

- A world-surface left-button level enters the selected element's primary
  action. Ether and Fire consume its press edge once. Air, Water, and Earth
  consume the held level; Earth additionally consumes the release edge.
- Ether and Fire use `Staff Cast 1`, mode 3 action `0x0044B170`. Its observed
  fixed-tick pose branch is insertion `K=0`, then `1`, `8`, `7`, and reset
  `0`; the alternate RNG branch starts at `8` and then joins `7`. Movement does
  not cancel the queued action. Death does. Releasing a short click does not
  rewind it. The one-shot emission marker is action-progress crossing `1`. In
  the observed branch-A run this is fixed action tick 19 and the `K=1 -> K=8`
  transition; branch B reaches the same progress marker while changing
  `K=8 -> K=7`.
- Air, Water, and Earth do **not** run that 74-tick action program. The
  sustained dispatcher `0x00548A00` calls the equipped-item resolver and then
  queues mode 5 `Action_PlayerWizard_StaffConstant` through `0x0044F5F0` at
  `0x00548A54..0x00548A66` on every active primary tick (mode 8 is the
  no-item path). The insertion tick still exposes the prior `K=0`; the
  one-tick constant action writes `K=7`, which is renewed while the primary
  remains active. The live Earth fixture independently observes the boulder at
  Staff emitter bank 0 on its first actor row and bank 7 on every later held
  row.
- Aim is derived from the world cursor relative to the torso anchor 25 screen
  pixels above the player's projected position. Heading is clockwise from
  screen-up, with direction `(sin(h), -cos(h))`.
- The staff socket is Clothes record
  `#3244 + 24*K + facing`, point 1, added to actor position without actor-scale
  multiplication. Facing is the native 24-way heading quantization. Spell art
  belongs in the world painter queue at its effective Y, never in the HUD or a
  player-local overlay.

### Element-by-element implementation slices

| Slice | Native press/hold/release contract | Native world visual contract | Native cast audio contract |
| --- | --- | --- | --- |
| Ether / Magic Missile (`8`, type `0x7D3`) | one actor on the press action marker; holding the same press does not duplicate that action | spawn at staff emitter plus `(0,+10)`; velocity `3` world units/tick; radius `15`; body `BadGuys[53]`; world queued; no fixed lifetime | registry 57 `sounds\\magicmissile` once at emission; flight is silent |
| Fire / Fire Missile (`16`, type `0x7D4`) | one actor on the press action marker | emitter plus `(0,+10)` plus `20` along aim; velocity `4.5`/tick; radius `22.5`; main strip `BadGuys[255..266]`, frame `(age/3)%12`; auxiliary family `[110..112]` | registry 97 `sounds\\throwfire` once at emission; flight is silent |
| Air / Lightning (`24`) | start on press, sustain once per held tick, stop on release; constant Staff action is `K=0` on insertion and `K=7` thereafter; no projectile actor | a reach-205 rank-1 ray from cast origin; each procedural bolt/fade survives 10 ticks with alpha `1 - 0.1*age`; no dedicated spell-atlas projectile | registry 54 `sounds\\lightningstart` on the start edge; registry 162 `sounds\\lightningloop__loop` owned for the channel lifetime |
| Water / Frost Jet (`32`) | start on press, emit once per held tick, stop on release; constant Staff action is `K=0` on insertion and `K=7` thereafter; no persistent gameplay projectile | rank-1 cone reach `205` is immediate gameplay only; shipped Enhanced Effects default emits two speed-`4` visual transients/tick; 75% Normal / 25% Over, 32-33 ticks; `BadGuys[30]` core plus `[28]` glint only | registry 44 `sounds\\icestart` on the start edge; registry 161 `sounds\\iceloop__loop` owned for the channel lifetime |
| Earth / Boulder (`40`, type `0x7D5`) | create on the first active tick; charge while the selected primary remains latched; after input release, the player tick retains Earth while charge is strictly below `0.3`, then releases the same cached actor on the following eligible tick | constructor charge is float32 `0.18`; the first post-tick actor row is age `1` at `0.181250006`; add float32 `0.00125` per active tick and clamp at `1`; a two-frame request reaches update `97` at `0.301249892` while still held, then first flies at age `98`; held radius `15`; release speed `3`/tick; body `BadGuys[86]` scaled by charge | actor creation plays registry 87 `sounds\\startboulder` once; registry 159 `sounds\\gatherrocksloop__loop` starts with Earth and stops on primary transition or charge cap; moving boulder owns registry 168 `sounds\\rollingstoneloop__loop` |

### Deliberate PoC boundary

The Website slice is authorized to implement only cast input, animation,
emission/channel lifecycle, replication, rendering, and the audio requests
listed above. It therefore must not consume mana, apply damage or status,
acquire or home toward targets, collide with actors or terrain, emit impact
audio/debris, or enforce the unrecovered gameplay cooldown/rank progression.
Without contact, Ether, Fire, and released Earth actors need a web containment
lifetime so they cannot grow the authoritative list forever. That lifetime is
an explicit web PoC policy, not a recovered native constant, and must be named
as such in the Website ledger and tests.

This boundary also forbids reconstructing one-shot audio from interpolated
positions. Authoritative player state must latch a monotonic emission sequence;
channel and rolling loops must be owner-keyed and balanced at release, actor
expiry, disconnect, and scene transition. Those lifecycle edges are part of
the native sound contract even while damage and collision remain absent.

### Cast-facing priority and lifetime

A fresh 2026-08-14 read-only decompile of retail `PlayerActor::Tick`
`0x00548B00` from Ghidra replica slot 2 closes the heading owner shared by all
five primaries. The analyzed `/SolomonDark.exe` is the 4,723,200-byte retail
image with SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.

`PlayerActor_UpdateControlBrainTargeting (0x0052C910)` supplies two independent
vectors to the player tick: movement and facing. When actor animation-drive
byte `+0x160` is zero, the player tick may convert movement through
`0x0042D280` and write actor heading `+0x6C`. If facing intent is present, the
same tick converts the facing vector through `0x0042D280` and writes `+0x6C`
again, after the movement write. Attack/cast facing therefore wins locomotion
on the acceptance tick. This is not a renderer transform.

The active action then preserves that heading. Staff Cast 1 remains queued
after a short Ether/Fire input release and keeps `+0x160` nonzero, so later
movement ticks cannot replace the accepted cast heading before the action's
marker or completion. Its marker is the fixed-tick progress crossing at tick
19 and its observed program ends at tick 74. Air, Water, and Earth renew the
one-tick Staff Constant action while their primary remains active, giving the
same facing priority for the channel lifetime. Earth retains the last cast
heading while its minimum-charge selection latch delays release.

The same state has several downstream consumers:

- Wizard body, held staff, and Staff socket composition all quantize actor
  `+0x6C` into the same 24-way facing.
- Cast emitter `0x0053B830` samples that facing at the fixed-tick emission.
- Fire handler `0x0053DC60` samples actor `+0x6C`, converts it through
  `0x00410500`, and writes `Fireball +0x13C/+0x140` at birth. Later actor
  heading changes do not steer the born projectile.
- Movement remains physically active during a queued action, but it neither
  cancels the action nor owns presentation facing until the action releases.

The port consequence is one authoritative action-level priority rule: capture
one-shot aim on accepted press and retain that heading through the queued
action; refresh sustained heading only from live held aim and otherwise retain
the last channel heading. Do not independently rotate robe, staff, emitter, or
VFX, and do not let snapshot interpolation infer a second facing owner.
