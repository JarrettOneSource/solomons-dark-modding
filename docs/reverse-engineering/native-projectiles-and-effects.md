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
| vtable `+0x14` | native type-ID accessor |
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
| `0x7F4` | `Golem` | `0x005F57E0` | `0x00615CD0` | articulated draw `0x00617820`; auxiliary `0x005E9530` | Golem 1..208; BadGuys 15, 36, 62, 238..245; UI 23 |
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

## Expanding waves

`Shockwave`, `FreezeWave`, and `Knockback` are list-backed area effects rather
than drawable missile sprites:

- Shockwave expands its radius, fades near expiry, queries intersecting actors
  every ten ticks, applies a contact payload once per actor, and can also push
  tracked actors radially through `0x00525800`.
- FreezeWave uses the same expanding/list pattern and creates cold/frozen
  modifiers according to target flags. An additional flag can attach a second
  modifier before the contact dispatch.
- Knockback owns the affected-actor list from the start. Each tick it applies
  outward impulse while temporarily changing the target collision radius. On
  expiry it dispatches the configured final contact/modifier payload once to
  each still-live actor and perturbs actor heading for the hit reaction.

Modifier constructor IDs at these call sites still require an instruction-level
argument recovery pass because the current decompiler omitted several pushed
constants from the prototypes. The modifier family itself is fully identified
in [`native-factory-catalog.json`](native-factory-catalog.json); the affected
call sites are retained in the method index and are not being guessed here.

## Remaining closure work for this subsystem

The object identities, full vtables, construction chains, class-owned art, and
update/render/contact roots are complete. Before this subsystem is marked
complete, the next pass must still:

1. recover omitted modifier/factory arguments at several x86 call sites;
2. map every skill/action handler to the exact object type and initialization
   fields it writes;
3. name all class-specific fields used by persistent area effects, boulders,
   Golem, Leviathan, and EtherDrain;
4. document destructor ownership for child lists and animation wrappers;
5. validate high-risk target, removal, and persistent-area contracts in an
   isolated live scene.
