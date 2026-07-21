# Native projectiles and transient effects

## Scope and evidence

This document maps the retail executable's projectile, persistent spell,
summon, hazard, and short-lived presentation objects. It covers the native
object ABI behind the art: construction, update, rendering, target queries,
contact dispatch, status-modifier creation, child effects, and removal.

The machine-readable evidence is
[`native-projectile-method-index.json`](native-projectile-method-index.json).
It contains 197 decompiled methods (22,514 source lines), and every method is
joined back to a factory type, class, constructor, vtable slot, and direct
atlas use. The type and complete vtable source is
[`native-game-object-catalog.json`](native-game-object-catalog.json).

Addresses below are executable virtual addresses for the SHA-256-pinned retail
binary documented in [native-asset-system.md](native-asset-system.md). A class
name is an RTTI identity. Behavioral names are conservative labels derived
from the decompiled body and call sites; they are not debug symbols.

## Shared actor and render contract

All objects in this document derive from the `Puppet` actor layout built by
`0x006287D0`. Important base fields and virtuals are:

| Location | Recovered role |
| --- | --- |
| object `+0x04` | pending initialize byte used by `ActorWorld::Tick` |
| object `+0x05` | pending remove byte |
| object `+0x08` | native factory type ID |
| object `+0x14` | actor flags / collision groups |
| object `+0x18/+0x1C` | world position |
| object `+0x30` | collision radius |
| object `+0x58` | owning world/region pointer after registration |
| object `+0x5C/+0x5E` | actor group and world-slot identity |
| object `+0x6C` | native heading used by angle-to-vector helpers |
| object `+0x134` | render/cull scalar used by several missiles |
| vtable `+0x00` | deleting destructor |
| vtable `+0x04` | pending-initialize callback |
| vtable `+0x08` | per-tick update |
| vtable `+0x0C` | full render entry; often `Puppet_RenderDispatch (0x00624B40)` |
| vtable `+0x10` | inherited no-op/reserved callback (`0x0042E260` on `Puppet`) |
| vtable `+0x14` | object serialization/deserialization callback; base `Puppet` fields are handled by `0x00622DC0` |
| vtable `+0x18` | mark/remove callback used by projectile expiry and impact |
| vtable `+0x1C` | normal world draw when the common render dispatcher is used |
| vtable `+0x20` | alternate draw selected by Puppet render flags |
| vtable `+0x28` | auxiliary world/effect draw pass on classes that override it |
| vtable `+0x30` | world sprite/shadow pass using `0x0057FE40` on most effects |
| vtable `+0x64` and above | class-specific target, contact, impact, or teardown callbacks |

`Puppet_TickBase (0x00624AC0)` increments the actor age at `+0x134`, updates
base timers, and calls virtual `+0x50` when its armed countdown expires.
`Puppet_RenderDispatch (0x00624B40)` performs culling, visibility/fade state,
color modulation, and then selects virtual `+0x1C` or `+0x20`. Therefore a
class whose `+0x0C` is `0x00624B40` normally places its actual art renderer in
`+0x1C`; a class that overrides `+0x0C` owns the full draw itself.

Common native services used by these objects are:

| Address | Recovered role |
| ---: | --- |
| `0x00410500` | convert native clockwise heading to a unit vector |
| `0x00410C50` | produce a random unit vector |
| `0x00414EA0` | translated, uniformly scaled sprite draw |
| `0x0041FE50` | set the current multiplicative render color |
| `0x00524D70` | test a proposed movement segment against the world |
| `0x00525800` | apply a movement/impulse step to an actor |
| `0x0057FE40` | cull/draw/queue a world sprite through its render owner |
| `0x006246F0` | initialize the process-global contact/damage context |
| `0x0063E5B0` | attach a transient actor to the current world and set `+0x58` |
| `0x0063E5E0` | create/attach the common sprite-animation transient |
| `0x0063E7D0` | dispatch the prepared contact context to a target actor |
| `0x00641160` | find the nearest eligible actor in the world-side candidate list |
| `0x00641220` | return the first actor intersecting a tested point/radius |
| `0x00642090` | collect actors intersecting a circle for a group-mask query |
| `0x00642280` | collect actors intersecting a rectangle for a group-mask query |

Contact is a two-stage ABI, not a direct `target->damage(amount)` call. A spell
first clears and seeds globals at `0x0081C6E0..0x0081C6F8` through
`0x006246F0`; fields select damage, flags, source, and optional modifier data.
It then calls `0x0063E7D0` for each target. That function verifies that the
target belongs to the same world and dispatches the target's virtual contact
handler. Several effects allocate a native modifier through
`GameObjectFactory_Create (0x005B7080)` and pass its reference in the contact
context. Modifier type IDs are documented with the factory map below.

## Factory and lifecycle map

The retail factory contains the following 46 projectile/effect classes. The
art column lists records referenced directly by class-owned methods; child
animation objects can add art not visible as a literal in the parent method.

| Type | RTTI class | Constructor | Tick | Principal render / behavior callbacks | Direct art |
| ---: | --- | ---: | ---: | --- | --- |
| `0x7D3` | `MagicMissile` | `0x005E4990` | `0x005FD270` | draw `0x005E0460`; target/contact `0x005E4A80`, `0x005F1F00`, `0x005E4B80` | BadGuys 53 |
| `0x7D4` | `Fireball` | `0x005E0970` | `0x005FDD90` | full draw `0x006099C0`; sprite pass `0x005E50D0` | BadGuys 110..112, 255..266 |
| `0x7D5` | `Boulder` | `0x005FA270` | `0x00609D30` | draw `0x0060AC40`; rock/contact `0x00620B60`, `0x005FE430`, `0x0060B700` | BadGuys 18, 86, 168..171, 2008..2010 |
| `0x7D6` | `Ember` | `0x005E0BD0` | `0x0060D7E0` | draw `0x0060DDD0`; contact `0x005E5700` | BadGuys 15, 251..254, 267..270 |
| `0x7DA` | `Arrow` | `0x005E1000` | `0x005FEA00` | draw `0x0060F590`; trail `0x005E5EC0` | BadGuys 2, 255..266, 271..282 |
| `0x7DE` | `FireMissile` | `0x005E4C50` | `0x005FD550` | draw `0x00608F80`; impact `0x005E4CA0` | BadGuys 110..112, 251..266 |
| `0x7DF` | `BallLightning` | `0x005E4F30` | `0x005FD720` | draw `0x005E0670`; impact `0x005F2360` | child/lightning art plus common missile art |
| `0x7E0` | `FrostMissile` | `0x005E4FB0` | `0x005FD7A0` | draw `0x006093B0`; impact `0x005F25B0` | BadGuys 110..112, 271..282 |
| `0x7E1` | `EBoulder` | `0x005FA670` | `0x00609D30` | draw `0x0060C540`; target/contact `0x00621450`, `0x00620B60`, `0x0060BED0` | BadGuys 86, 168..171, 2008..2010 |
| `0x7E2` | `Meteor` | `0x005E1540` | `0x00621590` | draw `0x005E16C0`; auxiliary passes `0x005E6DE0`, `0x005E7040` | render primitives / selected sprite pointer |
| `0x7E3` | `Fire` | `0x005E7130` | `0x005FF050` | draw `0x00610F90`; area contact `0x005FF1D0` | DeadHawg 46..77 |
| `0x7E4` | `Hailstones` | `0x005FAC20` | `0x005FF5D0` | draw `0x00611160`; rock/contact `0x00620B60`, `0x005F3090`, `0x005FAC70` | BadGuys 18, 168..171 |
| `0x7E5` | `GroundSpark` | `0x005E76F0` | `0x00611EB0` | draw `0x005E1B00`; sprite pass `0x005E7800` | BadGuys 71, 1836..1839 |
| `0x7E6` | `MovingFire` | `0x005E7890` | `0x005FF870` | draw `0x00610F90`; area contact `0x005FF1D0` | DeadHawg 46..77 |
| `0x7E7` | `Shockwave` | `0x005E7A20` | `0x005FF8C0` | sprite pass `0x005E7AA0`; radial contact in tick | child animation art |
| `0x7E8` | `FreezeWave` | `0x005E7B20` | `0x005FFDC0` | sprite pass `0x005E7AA0`; radial contact in tick | child animation art |
| `0x7E9` | `Knockback` | `0x005E7B50` | `0x00600220` | impulse/contact and removal are owned by tick | no direct atlas literal |
| `0x7EA` | `MagicCircle` | `0x005E1BA0` | `0x006006E0` | ring particles `0x005F3CA0`; actor query/effect `0x005FB020` | BadGuys 7, 48 |
| `0x7EB` | `Firebolt` | `0x005E1D00` | `0x00600880` | draw `0x00612760`; contact `0x005E7C20`; trail `0x006125B0` | BadGuys 251..266 |
| `0x7EC` | `GuidedMissile` | `0x005E7E00` | `0x00600B40` | draw `0x00612960`; target/contact `0x005F42C0`, `0x005F3EE0` | BadGuys 110..112, 381..382 |
| `0x7ED` | `Gravestone` | `0x005E5C30` | `0x00624AC0` | draw `0x0060F0F0`, `0x0060F260`; interaction `0x005F2EB0` | DeadHawg 97..113 |
| `0x7EE` | `Fire_Goodguy` | `0x005E76C0` | `0x005FF050` | draw `0x00610F90`; area contact `0x005FF1D0` | DeadHawg 46..77 |
| `0x7EF` | `PlaneOrb` | `0x005E2180` | `0x005FB460` | draw `0x005E8720`; special pass `0x00601910` | BadGuys 11 plus direct texture-page path |
| `0x7F0` | `StormCloud` | `0x005E22E0` | `0x006021A0` | full draw `0x005E8970`; weather/overlay pass `0x00602C30` | child bolt/cloud animations |
| `0x7F1` | `Earthquake` | `0x005E8EA0` | `0x00613200` | draw `0x00613E10` | BadGuys 62, 2008..2010; DeadHawg 200..202 |
| `0x7F2` | `Leviathan` | `0x005E8FB0` | `0x006145D0` | draw `0x006151D0`; sprite pass `0x005E90C0` | BadGuys 11, 39, 343..372 |
| `0x7F3` | `EtherBolt` | `0x005E2950` | `0x006034F0` | full draw `0x005E29A0`; contact in tick | child fade animation |
| `0x7F4` | `Golem` | `0x005F57E0` | `0x00615CD0` | init `0x005F5B40`; articulated draw `0x00617820`; contact `0x00607F60`; death `0x00619730` | Golem 1..208; BadGuys 15, 62, 86, 238..245, 2008..2010; DeadHawg 78..87; UI 23 |
| `0x7F5` | `MagicTrap` | `0x005E2CC0` | `0x00603710` | draw `0x00619CD0`; auxiliary `0x005E9700` | BadGuys 16, 110..112, 393..400 |
| `0x7F6` | `Bonus` | `0x005E2D90` | `0x006039C0` | draw `0x0061A260` | BadGuys 7, 61, 122..157 |
| `0x7F7` | `DemonBomb` | `0x005E2F00` | `0x00603CA0` | draw `0x0061A690`; auxiliary `0x005E9970` | BadGuys 267..270; DeadHawg 46..77 |
| `0x7FA` | `GreenFire` | `0x005EA4C0` | `0x005FF050` | draw `0x0061BBF0`; area contact `0x005FF1D0` | Unholy 9..40 |
| `0x7FB` | `UnholySpit` | `0x005E3470` | `0x0061BE10` | full draw `0x0061C0D0` | Unholy 5..40 |
| `0x7FE` | `AcidRain` | `0x005E3540` | `0x00604E90` | draw passes `0x005E3600`, `0x005EB290`, `0x005EB1D0` | BadGuys 10 plus child raindrops |
| `0x7FF` | `EyeLaser` | `0x005E36C0` | `0x006054F0` | full draw `0x005EB6C0` | Unholy 0..1 |
| `0x800` | `SkullMissile` | `0x005EB980` | `0x00605920` | draw `0x005EB9A0`; target/contact `0x005F42C0`, `0x005F6AC0` | BadGuys 10..11 plus child missile particles |
| `0x801` | `RainOfBones` | `0x005E3780` | `0x0061C440` | draw passes `0x005E37F0`, `0x005EBAD0` | BadGuys 10..11, 113..121, 1819..1822 |
| `0x802` | `TragicCircle` | `0x005E3840` | `0x00605C00` | ring particles `0x005EBE20`; actor query/effect `0x005F7010` | BadGuys 7, 10..11, 48 |
| `0x804` | `DarkFireball` | `0x005E3A10` | `0x00605C80` | draw `0x0061CB20`; trail `0x005ED940`; impact `0x005F76B0` | BadGuys 10..11, 251..266 |
| `0x805` | `DireFire` | `0x005EDC90` | `0x00605D30` | draw `0x0061CD40`; area contact `0x005FF1D0` | BadGuys 10..11; DeadHawg 46..77 |
| `0x806` | `PoisonPool` | `0x005E3B00` | `0x005F8030` | auxiliary draw `0x005EDFA0`; poison contact in tick | selected sprite / primitive draw |
| `0x807` | `EtherDrain` | `0x005F8360` | `0x0061CF20` | auxiliary draw `0x005EE120`; sprite pass `0x005EE780` | DeadHawg 177..179 |
| `0x808` | `Silk` | `0x005F05D0` | `0x005F8B50` | full draw `0x00606A10`; inherited arrow draw `0x0060F590`; tether `0x005F92C0` | BadGuys 2, 27, 255..282; DeadHawg 14 |
| `0x80B` | `EvilEmber` | `0x005E0CC0` | `0x0060D7E0` | draw `0x0060DDD0`; hostile contact `0x005F2980` | BadGuys 15, 251..254, 267..270 |
| `0x80C` | `Comet` | `0x005F0C50` | `0x006220D0` | full draw `0x005E3CD0`; sprite pass `0x005F0DB0` | BadGuys 51; DeadHawg 5 |
| `0x80F` | `OffscreenMagic` | `0x005E4150` | `0x00607B60` | sprite pass `0x005F18A0` | selected sprite pointer |

The factory intentionally has no `0x803` type. This is not an extraction gap:
the switch proceeds from `0x802` to `0x804`.

## Proven inheritance and behavioral families

The vtables and constructor chains establish these native families:

- `FireMissile`, `BallLightning`, `FrostMissile`, `GuidedMissile`, and
  `SkullMissile` extend `MagicMissile`. They reuse its target identity fields,
  target search callbacks, and/or straight-missile motion, then replace impact
  and presentation behavior.
- `EBoulder` extends `Boulder`; `Hailstones` reuses the boulder rock/contact
  machinery but owns a separate constructor and update/render path.
- `MovingFire`, `Fire_Goodguy`, `GreenFire`, and `DireFire` extend or reuse the
  persistent `Fire` actor. They share the animated-fire list and area-contact
  callback while changing allegiance, movement, sprites, and effect state.
- `FreezeWave` extends `Shockwave`; both maintain a list so one expanding wave
  does not repeatedly apply its contact payload to the same actor.
- `TragicCircle` extends `MagicCircle` and keeps the base circle tick while
  replacing both its particle presentation and actor-side effect.
- `DarkFireball` extends `Firebolt`; `Silk` extends `Arrow`; `SkullMissile`
  extends `GuidedMissile`; `EvilEmber` extends `Ember`.
- `RainOfBones` begins with the `AcidRain` constructor, then replaces the type,
  duration, render passes, and tick payload.

## Missile behavior recovered so far

`MagicMissile` stores target group/slot identity at `+0x140/+0x142`, heading at
`+0x13C`, speed/turn scalars in `+0x120..+0x154`, bounce count at `+0x161`, and
damage/effect scalars at `+0x158/+0x15C`. Its tick:

1. runs the base Puppet timers;
2. converts heading to a movement vector;
3. tests the next segment every fifth tick and calls `+0x68` on collision;
4. advances position and world-render-list membership;
5. resolves a live target and turns toward it without crossing the configured
   turn-rate bound;
6. invokes `+0x64` for proximity targeting each tick.

The `+0x68` contact method seeds the native damage context and dispatches it to
the hit actor. With no bounces left it creates an `Anim_FadeMM`, wraps it in the
common animation actor, and removes the missile. With bounces remaining it
reduces the configured speed/damage scalars, advances out of the current
target, emits BadGuys record 53 particles, searches for another intersecting
actor, and continues through `+0x6C`.

`FireMissile` runs the same motion and then creates a moving fade/ZAnim trail
every tick. Its impact seeds the same contact ABI, emits a fire fade using
BadGuys 251..254, can emit a configured secondary area payload, and removes the
missile.

`BallLightning` temporarily accelerates the inherited motion scalar before
running the base missile tick, restores it afterward, and decays the added
acceleration. Its impact creates modifier type `0x1B6B` (`ElectricBurn`) with
native duration/value fields before dispatching contact, then creates an
`Anim_FadeLightning` presentation object and removes the missile.

`FrostMissile` runs the base missile motion and optionally applies a radial
movement field to actors returned by group-mask `0x82`. Its impact creates
modifier type `0x1B69` (`ColdSlow`) when configured, dispatches contact,
optionally invokes the freeze-area helper, creates `Anim_FadeFrost`, and
removes the missile.

`GuidedMissile` uses the common target group/slot identity but moves through
`0x00525800` with temporary world collision flags. It steers toward the live
target, checks the terrain segment every fifth tick, loses speed down to a
configured floor, expires on its range/lifetime scalar, and routes target or
terrain contact through `+0x68`. The impact supports two payload modes and
creates `Anim_FadeGM` plus a common animation wrapper.

`SkullMissile` reuses GuidedMissile motion and proximity targeting. It adds
orbiting/randomized dark particles on update; impact produces `Anim_FadeDM`,
dark burst particles, the normal contact payload for eligible targets, and
world color/flash state before removal.

### Exact factory payloads inside projectile methods

`trace_call_arguments.py` recovers the literal type pushed before every
`0x005B7080` call. Projectile-owned factory calls are:

| Owning method | Literal type | Meaning in that path |
| ---: | ---: | --- |
| BallLightning impact `0x005F2360` | `0x1B6B` | attach `ElectricBurn` |
| FrostMissile impact `0x005F25B0` | `0x1B69` | attach `ColdSlow` when its slow scalar is nonzero |
| GuidedMissile impact `0x005F3EE0` | `0x1B72` / `0x1B69` | payload mode selects `Poisoned` or `ColdSlow` |
| MagicCircle effect `0x005FB020` | `0x1B70` | attach `CircleSlow` |
| TragicCircle effect `0x005F7010` | `0x1B70` | attach `CircleSlow` while its separate logic drains mana |
| PoisonPool tick `0x005F8030` | `0x1B72` | attach `Poisoned` |
| Arrow tick `0x005FEA00` | `0x1B72` | optional `Poisoned` payload controlled by arrow state |
| Shockwave tick `0x005FF8C0` | `0x1B6E` | attach `Dazzle` |
| FreezeWave tick `0x005FFDC0` | `0x1B69`, `0x1B6F`, `0x1B78` | `ColdSlow` or `Frozen`, optionally `FrostBurn` |
| Knockback tick `0x00600220` | `0x1B6E` | attach `Dazzle` on final contact |
| DarkFireball impact `0x005F76B0` | `0x805` | spawn persistent `DireFire`, not a modifier |
| DemonBomb tick `0x00603CA0` | `0x7E3` | spawn persistent `Fire` patches |
| Ember/EvilEmber tick `0x0060D7E0` | `0x3ED`, `0x7E3` | GoodImp conversion branch and Fire patch spawn |
| Leviathan tick `0x006145D0` | `0x7F3` | spawn `EtherBolt` projectiles |
| Golem tick `0x00615CD0` | `0x7E9` | spawn the `Knockback` area actor in attack state `0x25` |
| EBoulder split `0x005FA6D0` | `0x7E1` | recursively spawn child `EBoulder` rocks |

This also proves that object IDs and modifier IDs share one native factory but
are not interchangeable. A projectile can create another world actor, a
status modifier, or a summon using the same entry point; the caller determines
how the returned object is registered or wrapped.

## Expanding waves

`Shockwave`, `FreezeWave`, and `Knockback` are list-backed area effects rather
than drawable missile sprites:

- Shockwave expands its radius, fades near expiry, queries intersecting actors
  every ten ticks, applies `Dazzle (0x1B6E)` once per actor, and can also push
  tracked actors radially through `0x00525800`.
- FreezeWave uses the same expanding/list pattern and selects `ColdSlow
  (0x1B69)` or `Frozen (0x1B6F)` according to target flags. Object flag
  `+0x174 & 0x10` adds `FrostBurn (0x1B78)` before contact dispatch.
- Knockback owns the affected-actor list from the start. Each tick it applies
  outward impulse while temporarily changing the target collision radius. On
  expiry it dispatches `Dazzle (0x1B6E)` once to each still-live actor and
  perturbs actor heading for the hit reaction.

These type IDs come from the literal `PUSH` immediately before the native
factory calls; they are not name-based guesses. Other omitted factory arguments
are being recovered with `tools/ghidra-scripts/trace_call_arguments.py`.

## Persistent secondary and advanced spell actors

The cast dispatcher only seeds these objects. Their actual cadence, target
selection, child effects, and expiry live in the actor ticks below.

### Magic Circle (`0x7EA`)

`MagicCircle` starts with a 1,500-tick lifetime at `+0x144`. Its tick
`0x006006E0` decrements that counter, emits the class's ring particles through
virtual `+0x64` every tick, and invokes the area-effect callback at virtual
`+0x68` every ten ticks. `0x005FB020` queries the circle footprint and has two
separate effects:

- eligible non-player actors receive `Mod_CircleSlow (0x1B70)`; its value is
  copied from circle `+0x140`;
- the local player receives the circle's advertised healing and mana-recovery
  boosts, bounded by the player's current maxima.

The ring renderer `0x005F3CA0` creates `Anim_SpinAwayAdditive` children using
the color stored at `+0x14C..+0x158`. The circle removes itself when the
lifetime reaches zero; the children are registered animation actors rather
than raw pointers owned by the circle.

### Magic Trap (`0x7F5`)

`MagicTrap` stores its derived element at `+0x13C`, primary base damage at
`+0x140`, trap multiplier at `+0x144`, fade-in rate at `+0x148`, animation
frame at `+0x14C`, age at `+0x150`, and the decaying armed shimmer at `+0x154`.
`0x00603710` registers it in the world's effect draw list each tick and, for
the authoritative local group, polls its trigger footprint every 25 ticks.

`0x005F5C80` is the one-shot trigger. It emits the element-colored burst,
queries group `2`, sets damage to `baseDamage * trapMultiplier`, dispatches to
every actor returned, and removes the trap. The element payload is explicit:

| Trap element selector | Additional native effect |
| ---: | --- |
| `1` | common fire helper `0x00624210`, which creates `Mod_Burn (0x1B73)` |
| `2` | `Mod_ElectricBurn (0x1B6B)` |
| `3` | `Mod_ColdSlow (0x1B69)` |
| other | direct trap contact only |

The deleting destructor `0x005E95A0` delegates to the normal `Puppet`
teardown; the trigger's presentation objects are world-owned.

### Magic Storm / Storm Cloud (`0x7F0`)

`StormCloud` begins with a 1,000-tick active lifetime. `0x006021A0` ramps its
scale and alpha in, emits two cloud particles per tick (five in the enhanced
presentation mode), and fades out after the active counter expires. On the
authoritative group it periodically queries the hostile footprint, chooses a
random target, rolls damage between `+0x178/+0x17C`, dispatches contact with
flag `0x20`, and stores three points used by the lightning presentation. Its
short strike-energy counter drives `Anim_FadeLightning` and the generated
lightning mesh. The alternative moving-cloud mode is enabled at `+0x180` and
advances the cloud and its 15 presentation control points along its heading.

### Acid Rain (`0x7FE`)

`AcidRain` has a 1,500-tick active lifetime, a separate fade/ground-residue
scalar, and a 25-tick authoritative hit cadence after its initial delay.
`0x00604E90` emits `Anim_AcidRaindrop` children every tick, queries the hostile
area, shuffles the candidate list, and damages at most roughly one third of
the returned actors on a pulse. Its contact uses the damage written at
`+0x154`, normalized by the native per-second tick divisor, with flags `0x18`.
The rain does not allocate a poison modifier; its damage is direct. It removes
itself only after both the active lifetime and residual fade have elapsed.

### Earthquake (`0x7F1`)

`Earthquake` owns a pointer list and a short duration counter at `+0x13C`.
`0x00613200` derives the shake/intensity ramp from the remaining counter,
updates global world-shake state, and removes the actor when the counter
reaches zero. Every 30 ticks it queries the hostile footprint, shuffles it,
and disrupts up to half of the returned actors: current action state is
cancelled or replaced by a pause action and heading/reaction state is
perturbed. Earthquake has no damage property in its CFG and does not seed the
normal damage contact ABI. Its other work is presentation and terrain debris:
it animates registered floor fragments and creates `Anim_BoulderBit`/lit
children around the epicenter.

### Call Leviathan and Ether Bolt (`0x7F2`, `0x7F3`)

`Leviathan` is a three-phase actor: scale-in, active appendages, then scale-out.
It owns a `PointerList` at `+0x15C`; each 0x34-byte appendage record keeps local
geometry, target group/slot identity, heading, a shot countdown, and sprite
selection. During `0x006145D0` an untargeted appendage searches locally; a live
target is then resolved by identity and tracked. When its countdown expires it
emits `Anim_FadeMM`, creates `EtherBolt (0x7F3)`, writes the selected target
heading, velocity, owner group, and configured damage, and registers the bolt.
The configured appendage quantity controls the list built for the Leviathan;
the configured damage is copied to child `+0x14C`.

`EtherBolt` is a deliberately small straight projectile. `0x006034F0` adds its
velocity at `+0x13C/+0x140` to position each tick, expires after 100 ticks plus
a fade, and uses `0x00641220` for point/radius actor intersection. On contact it
emits `Anim_FadeMM`, dispatches its `+0x14C` damage only on the authoritative
group, and removes itself. It does not perform the terrain-segment test used by
`MagicMissile`.

### Raise Golem and Iron Golem (`0x7F4`)

`Golem` is a summoned actor rather than a one-frame cast effect. Secondary
dispatcher `0x0054CC50` creates it at a collision-adjusted target point,
copies caster ownership, and writes:

| Field | Cast-time value |
| ---: | --- |
| `+0x170/+0x174` | current/max HP from Raise Golem `mHP` |
| `+0x1F0` | Raise Golem `mDamage1` |
| `+0x1F4` | Raise Golem `mDamage2` |
| `+0x210` | Iron Golem presentation/behavior byte |
| `+0x214` | Iron Golem `mReflect / 100` |

The progression feature bit `+0x878 & 0x08` selects the native summon cap.
With the bit clear, casting expires every existing owned golem before spawning
the replacement. With it set, one owned golem can remain; if two already
exist, the lower-HP one is expired before the new summon is registered. The
resulting caps are one and two respectively.

Constructor `0x005F57E0` seeds the Puppet base and articulated part
collections; initialize method `0x005F5B40` binds world state. Tick
`0x00615CD0` runs the staged assembly/activation period, target acquisition,
movement, and attack state machine. Attack state `0x25` creates
`Knockback (0x7E9)` through the common factory. The summon retains its
owner/world identity throughout instead of storing a raw PlayerWizard pointer.

Contact callback `0x00607F60` is gated until age `+0x208` reaches 400.
After that assembly grace period it subtracts the contact ABI's primary and
secondary damage from `+0x170`. When `+0x214` is nonzero, a non-null,
nearby actor source with actor-flag bit `1` receives
`incomingPrimary * reflectRatio` through a fresh contact dispatch whose
source is the golem. Secondary incoming damage is not included in that
reflection formula. HP at or below zero marks the actor for removal and calls
death-effect method `0x00619730`.

Draw `0x00617820` composes the golem from the Golem atlas body-part arrays
rather than selecting one monolithic frame. Golem records `1..208` cover
those parts. Supplemental direct selections are BadGuys records
`15,62,86,238..245,2008..2010`, UI record `23`, and DeadHawg records
`78..87`. Iron byte `+0x210` changes the assembled tint/piece treatment
and the colors of the DeadHawg fragments emitted on death. Those death
fragments and other child animations are world-owned after registration.

### Ether Drain (`0x807`)

`EtherDrain` has explicit scale-in, 100-tick active, and scale-out states in
byte `+0x148`. It owns two `Array<PuppetRef>` collections plus pointer lists for
spatial cells and presentation children. `0x00606580` refreshes candidate
identities from the covered world cells; `0x005F8620` is the per-candidate
effect:

- actors within the pressure field are pulled toward the center through their
  virtual force callback; actors close enough receive contact damage using the
  configured per-second scalar at `+0x150` and flags `0x10A`;
- objects with actor flag `0x400` are also pulled inward. This includes ground
  loot; a captured object is removed at the center and routed through the
  world-item consumption effect. Nonempty `Gold (0x7DC)` and `Sack (0x7DD)`
  containers are explicitly exempted from premature removal.

The target arrays retain group/slot identities rather than raw actor pointers.
The deleting destructor `0x005FB980` delegates to `0x005F84F0`, which owns the
array/list cleanup; presentation children remain registered with the world.

### Call Comet (`0x80C`)

`Comet` stores configured damage at `+0x13C`, freeze duration at `+0x140`, and
its fall countdown at `+0x14C`. `0x006220D0` emits an ice-blast child each tick,
updates the world-impact intensity, and calls `0x0061E9C0` when the countdown
expires. The impact creates the large burst/debris presentation, invokes the
same FreezeWave creation helper used by Ring of Ice with the comet damage, and
then queries the impact area and dispatches the comet freeze scalar through
contact field `0x0081C6E8`. It finally restores the world-color state and
removes itself. The deleting destructor uses ordinary `Puppet` teardown.

## Remaining closure work for this subsystem

The static object identities, full vtables, construction chains, direct
class-owned art, factory/modifier arguments, cast-time payloads, and principal
update/render/contact roots are mapped. Remaining closure is deliberately
narrow:

1. join indirect child-animation selectors to their final atlas records where
   the parent stores only a runtime sprite pointer;
2. finish destructor ownership notes for the recursive boulder and animation
   wrapper collections;
3. validate high-risk target, reflection, removal, and persistent-area
   contracts in an isolated live scene.
