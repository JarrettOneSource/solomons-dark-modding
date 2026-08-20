# Native projectiles and transient effects

## Scope and evidence

The secondary-ability correction in
[`native-secondary-parity-correction-2026-08-20.md`](native-secondary-parity-correction-2026-08-20.md)
supersedes the earlier closure for StormCloud composite ownership, Golem
articulation, Leviathan painter grouping, Ring-of-Fire Region/maximum-set
effects, and FreezeWave target modifiers. The catalog and formulas below remain
authoritative where that correction does not explicitly replace them.

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
| vtable `+0x24` | texture-geometry pass used by PlaneOrb and other classes that override it |
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

### Region-owned full-screen feedback lane

Right-click feedback is not a set of independent actor overlays. `Region`
owns one shared color, alpha, and alpha-loss lane:

| Field | Role |
| ---: | --- |
| `Region +0x8E14/+0x8E18/+0x8E1C` | red, green, and blue |
| `Region +0x8E20` | current alpha |
| `Region +0x8E24` | alpha loss per fixed update |

`0x00448600` overwrites all five values. Several actor factories and ticks
inline the same writes. `Region::Tick (0x0063EFC0)` performs one stored-float
subtraction per 100 Hz update and clamps alpha to zero. The main Region render
at `0x0046EC80` checks alpha after the world/effect passes, installs the stored
RGBA with `0x0041FE50`, draws one viewport-sized rectangle, then restores
white. The lane is ordinary alpha composition below the separate HUD, not an
additive world sprite. A later write replaces an earlier flash; concurrent
flashes are never accumulated or max-composited.

Most world-point flashes seed alpha from Region vtable slot `+0x100`. For a
point `P`, camera center `C`, and visible world width `W`, that callback returns
linear falloff from one at distance `0.25W` to zero at `1.1W`. It multiplies
the result by `0.1` while the local-player alternate/death byte at `+0x160` is
set. The RGB and per-tick loss remain unattenuated. Calls identified as fixed
below bypass that point gain and write alpha one directly.

The complete right-click membership is:

| ID / ability | Region-lane writes in native order |
| --- | --- |
| `11` Call Leviathan | first scale-in update: `(1, 0.5, 1, pointGain)`, loss `0.05` (`0x006145D0`) |
| `12` Planewalker | enable only: fixed `(1, 0, 1, 1)`, loss `0.1`; disable does not write (`0x00548700`) |
| `15` Phasing | accepted traversal: `(0, 1, 1, pointGain)`, loss `0.025` (`0x0052A220`, `0x00645B50`) |
| `21` Ring of Fire | creation: `(1, 0.5, 0, pointGain)`, loss `0.01` (`0x0063F920`) |
| `23` Firewalker | every on/off toggle, before the state flip: `(1, 0.5, 0, pointGain)`, loss `0.1` (`0x0054CDAB`) |
| `27` Magic Storm | no Region-lane write; StormCloud owns its separate render-target weather flash and float32 `0.1` decay (`0x006021A0`, `0x00602C30`) |
| `30` Prismatic | creation consumes `RandomInt(5)` and selects red, orange, yellow, green, or cyan; selected RGB plus `pointGain`, loss `0.05` (`0x00452C50`, `0x00645540`) |
| `35` Ring of Ice | creation: `(0.9, 1, 1, pointGain)`, loss `0.01` (`0x00644460`) |
| `41` Earthquake | accepted cast: fixed `(0.8, 1, 0.8, 1)`, loss `0.025` (`0x0054DF34..0x0054DF84`) |
| `45` Raise Golem | no Region-lane write; assembly, impact, shake, lighting, and death feedback are actor/world owned |
| `46` Stoneskin | accepted cast: fixed white `(1, 1, 1, 1)`, loss `0.1` (`0x0054D87B..0x0054D8B5`) |
| `48` Teleport | source fixed white/loss `0.025`, then destination white with `pointGain`/loss `0.025`; the destination write immediately replaces the source write (`0x0054D6AC..0x0054D723`, `0x00644A00`). Each call also registers one additive BadGuys-90 `Anim_FadeScale` at `point.y-15`, alpha `2`, loss `0.1`, and independent `RandomFloat(360)` rotation. The source starts at scale `(1,1)` and recurs by `*1.1`; the destination starts at `(8,8)` and recurs by `*0.96`. Both therefore retire after 20 ticks. |
| `49` Magic Circle | lifetime counter first reaches `1498`: `(0.75, 1, 1, pointGain)`, loss `0.1` (`0x006006E0`) |
| `50` Magic Trap | initialization writes selector RGB with fixed alpha one/loss `0.1`; one-shot trigger rewrites the same selector RGB with `pointGain`/loss `0.05` (`0x005E95D0`, `0x005F5C80`) |
| `51` Dampen | no Region-lane write; the named `flash.wav` and additive wave children are world feedback |
| `54` Magic Shield | apply/refresh: `(0.5, 1, 1, pointGain)`, loss `0.1`; Explosive Shield break: same color and point gain, loss `0.05` (`0x00529EE0`, `0x00648790`) |
| `72` Acid Rain | no Region-lane write |
| `73` Fire Wall | accepted cast: `(1, 0.5, 0, pointGain)`, loss `0.1` (`0x0054F6E0`) |
| `74` Ether Drain | first scale-in update: `(1, 0.5, 1, pointGain)`, loss `0.05` (`0x0061CF20`) |
| `76` Call Comet | impact: fixed white `(1, 1, 1, 1)`, loss `0.005`; removal does not own the lane (`0x0061E9C0`) |
| `77` Turn Undead | no Region-lane write |
| `78` Mindstar | every on/off toggle: `(0, 0.5, 1, pointGain)`, loss `0.1` (`0x0054FF5E`) |
| `79` Regenerate | every on/off toggle: `(1, 0.5, 0, pointGain)`, loss `0.1` (`0x0055002D`) |

The complete Mindstar and Regenerate dispatcher branches (`0x0054FF05` and
`0x0054FFD4`) contain no allocation or actor-registration call. These Region
writes are their entire visual program; adding a caster flash or world sprite
would introduce a non-native presentation owner.

Magic Trap indexes the process table at `0x0081CCA8 + selector*16`. Static
initialization `0x00782C70..0x00782DBA` establishes the complete table:

| Selector | RGBA | Contact addition |
| ---: | --- | --- |
| `0` | `(1, 0.1, 1, 1)` | direct contact only |
| `1` | `(1, 0.35, 0.1, 1)` | fire helper / `Mod_Burn` |
| `2` | `(0.1, 1, 1, 1)` | `Mod_ElectricBurn` |
| `3` | `(0.1, 0.5, 1, 1)` | `Mod_ColdSlow` |
| `4` | `(0.1, 1, 0.1, 1)` | direct contact only |
| `5` | `(1, 0.5, 0.1, 1)` | direct contact only |
| `6` | `(0.1, 0.5, 0.5, 1)` | direct contact only |
| `7` | `(0.75, 0.75, 0.75, 1)` | direct contact only |
| `8` | `(1, 1, 1, 1)` | direct contact only |

The final ordinary primary selectors are Magic `0`, Fire `1`, Lightning `2`,
Ice `3`, and Earth `4`. At `0x0054EB5C..0x0054ED04`, selector byte `7` is a
synthetic-build sentinel rather than a final trap element. The factory reads
the current build at wizard progression `+0x750`, subtracts `1000`, and uses
the complete 15-row jump table at `0x0055012C`. Rows `1000..1009` are the ten
welds: each consumes `RandomInt(2)` and resolves one of its two component
selectors. Rows `1010..1014` are the pure Ether, Fire, Water, Air, and Earth
builds and resolve fixed selectors `0,1,3,2,4` respectively. Planewalker's
Plane Orb cast override does not replace this selected-build source. The
resolved selector, not the wizard's character element or temporary sentinel,
owns trap color, contact kind, and additional modifier.

## Factory and lifecycle map

The retail factory contains the following 46 projectile/effect classes. The
art column lists records referenced directly by class-owned methods; child
animation objects can add art not visible as a literal in the parent method.

| Type | RTTI class | Constructor | Tick | Principal render / behavior callbacks | Direct art |
| ---: | --- | ---: | ---: | --- | --- |
| `0x7D3` | `MagicMissile` | `0x005E4990` | `0x005FD270` | draw `0x005E0460` -> Ether compositor `0x00535A30`; target/contact `0x005E4A80`, `0x005F1F00`, `0x005E4B80` | flight BadGuys 110..112; surviving-pierce contact BadGuys 53 |
| `0x7D4` | `Fireball` | `0x005E0970` | `0x005FDD90` | vtable `0x0079C5BC` render slot `+0x0C` directly draws at `0x006099C0` and bypasses common Region-light dispatcher `0x00624B40`; outbound light provider `0x005E50D0`; contact `0x005E5160` creates `Anim_FireBurst`; ordinary trail `ZAnim` slot `+0x0C` `0x005E01E0` also bypasses Region light | direct BadGuys 110, 255..266; child trail 267..270; impact 251..254 |
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
| `0x7EF` | `PlaneOrb` | `0x005E2180` | `0x005FB460` | draw `0x005E8720`; texture mesh `0x00601910`; birth helper `0x0052D360` | BadGuys 75 core; loose `etherplane`; child BadGuys 11/45 particles |
| `0x7F0` | `StormCloud` | `0x005E22E0` | `0x006021A0` | full draw `0x005E8970`; weather/overlay pass `0x00602C30` | child bolt/cloud animations |
| `0x7F1` | `Earthquake` | `0x005E8EA0` | `0x00613200` | draw `0x00613E10` | BadGuys 62, 2008..2010; DeadHawg 200..202 |
| `0x7F2` | `Leviathan` | `0x005E8FB0` | `0x006145D0` | draw `0x006151D0`; sprite pass `0x005E90C0` | BadGuys 11, 39, 343..372 |
| `0x7F3` | `EtherBolt` | `0x005E2950` | `0x006034F0` | full draw `0x005E29A0`; contact in tick | BadGuys 22; child Ether FadeMM |
| `0x7F4` | `Golem` | `0x005F57E0` | `0x00615CD0` | init `0x005F5B40`; articulated draw `0x00617820`; contact `0x00607F60`; death `0x00619730` | Golem 1..208; BadGuys 15, 62, 86, 238..245, 2008..2010; DeadHawg 78..87; UI 23 |
| `0x7F5` | `MagicTrap` | `0x005E2CC0` | `0x00603710` | draw `0x00619CD0`; auxiliary `0x005E9700`; terminal `0x005F5C80` | BadGuys 111,112,15,85,16,158..167,17,74; fire modifier 333..342 |
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
| `0x806` | `PoisonPool` | `0x005E3B00` | `0x005F8030` | auxiliary draw `0x005EDFA0`; poison contact in tick | DeadHawg 0, submitted twice |
| `0x807` | `EtherDrain` | `0x005F8360` | `0x0061CF20` | draw `0x005EE120`; point light `0x005EE780` | direct BadGuys 38, 75; child BadGuys 10, 11, 36 and DeadHawg 177..179 |
| `0x808` | `Silk` | `0x005F05D0` | `0x005F8B50` | full draw `0x00606A10`; inherited arrow draw `0x0060F590`; tether `0x005F92C0` | BadGuys 2, 27, 255..282; DeadHawg 14 |
| `0x80B` | `EvilEmber` | `0x005E0CC0` | `0x0060D7E0` | draw `0x0060DDD0`; hostile contact `0x005F2980` | BadGuys 15, 251..254, 267..270 |
| `0x80C` | `Comet` | `0x005F0C50` | `0x006220D0` | full draw `0x005E3CD0`; sprite pass `0x005F0DB0` | BadGuys 51; DeadHawg 5 |
| `0x80F` | `OffscreenMagic` | `0x005E4150` | `0x00607B60` | sprite pass `0x005F18A0` | selected sprite pointer |

The factory intentionally has no `0x803` type. This is not an extraction gap:
the switch proceeds from `0x802` to `0x804`.

## Animation-wrapper art and ownership ABI

The animation classes do not each own a private atlas record. They are generic
render/lifetime wrappers around a descriptor selected at the creation site.
This is why a parent method can have a final atlas selection while the child
class's render method has no atlas-singleton literal.

The recovered layouts and deleting destructors close that indirection:

| Wrapper family | Art/child field | Ownership and teardown |
| --- | ---: | --- |
| `Anim_Fade*`, `Anim_Bouncer*`, and related short-lived `Anim_*` objects | sprite descriptor at `+0x1C` | borrowed pointer into a resident bundle; `0x00448DD0` reaches `Object` teardown and never releases the descriptor |
| `AnimPointer` | sprite descriptor at `+0x13C` | borrowed pointer; `0x005061C0` performs `Puppet` teardown only |
| `ZAnim` / `ZAnimLit` | child animation object at `+0x13C` | owned object; `0x005E0100`/`0x005E47D0` invokes the child's deleting destructor, nulls the field, then tears down `Puppet` |
| `ZAnimGroup` | embedded child `ObjectManager` | manager-owned children; `0x005E4860` calls `0x00402190`, which destroys its two embedded manager records and frees the pointer-list allocation before `Puppet` teardown |
| `ZAnimSplit` / `ZAnimLitObject` | inherited `ZAnim` child | both deleting destructors route through `0x005E0100`; no second sprite or child owner is introduced |
| registered child effects | world actor/smart-pointer registration | creator relinquishes lifetime after `0x0063E5B0`/`0x0063E5E0`; the parent does not delete the registered child |

For the ordinary fade family, constructor `0x00452E20` initializes the
descriptor slot and presentation fields; creation sites then assign an exact
bundle pointer. Examples include `MagicMissile` impact assigning BadGuys
record 53, Leviathan assigning record 11, and recursive `EBoulder` debris
selecting the BadGuys `168..171` array. When a creation site indexes an array,
the runtime pointer is still constrained to that builder-defined record range.

Consequently the final art identity is the pair `(creation site, selected
atlas destination)`, not the RTTI animation name alone. The complete static
join is already represented by `native-atlas-consumers.json` and the parent
relation in `native-projectile-method-index.json`; the wrapper contributes no
additional filename, page, or hidden selector. This closes the former
"indirect child-animation" residual without inventing a false one-record-per-
class mapping.

### Recursive boulder collections

`Boulder` constructor `0x005FA270` creates two separate list owners:

- `+0x13C` is `PointerList<SmartPointer<Boulder::Rock>>`; its backing
  allocation is at `+0x150`;
- `+0x200` is `PointerList<void*>`; its backing allocation is at `+0x214`.

Shared destructor body `0x005FA3F0` is used by `Boulder` and `EBoulder` through
deleting destructor `0x005FBD90`; `Hailstones` uses `0x005FBDB0` and then the
same body. It frees the auxiliary pointer-list allocation, runs a four-byte
element destructor across every smart rock reference before freeing that
allocation, nulls both backing pointers, and finally invokes `Puppet`
teardown. Recursive `EBoulder` children are separately registered world
actors; they are not raw pointees recursively deleted by their parent. The
`Anim_BoulderBit` deleting destructor `0x00479F60` has no collection cleanup
because each fragment is itself a registered animation object.

The 2026-08-14 Earth presentation adjacency pass closes what those two lists
contain and how they reach the renderer. The durable scalar/address/art join is
[`earth-boulder-vfx-catalog.json`](earth-boulder-vfx-catalog.json).

- Each smart Rock is 0x3C bytes: local XYZ `+0x00..08`, transformed XYZ
  `+0x0C..14`, scale `+0x18`, and sprite variant `+0x1C`.
- Boulder initialization builds once at charge `0.18`; vslot `+0x68`
  (`0x005FE430`) then replaces the main collection only whenever old/new
  `floor(30*charge)` buckets differ. It installs a central variant-3
  `BadGuys[171]` rock scaled `4*charge`, then `ceil(30*charge)` Fibonacci-
  sphere points at radius `30*charge`. Shell variants `0..2` select
  `BadGuys[168..170]` and use a charge-scaled random factor `0.5..1.25`,
  capped at one.
- Draw vslot `+0x1C` (`0x0060AC40`) transforms those points by the matrix at
  `+0x154`, accepts only strict transformed `Z > -40`, sorts by transformed Z,
  and draws the collection. Because the rank-1 radius is at most `30` and the
  matrix is rotation-only, that plane cannot cull a valid rank-1 Rock.
  `0x0043A8A0` then copies transformed X/Y exactly; Z has no projection term
  and is used only for culling/order. Main draw scale is
  `max(stored_scale, float32(0.45))`. Persistent record 15 uses green-white
  `(0.9,1,0.9)`, alpha `random(0,0.25)+0.35`, and scale `4.1*charge` in held
  and flight phases. Record 86 is the separate additive opening flash: mix
  `+0x1EC` starts at one and decreases by `0.035`/tick; flash alpha is `mix`,
  scale is `2.5*mix`, rotation is global-render-tick times six degrees, and
  rock alpha is `1-mix`.
- The whole visual gets per-draw random displacement in radius `[0,3]` and
  local Y `-20-32.5*charge`. Its actor/Region-light point remains authoritative
  Boulder XY; painter bias is `(20+10*charge)*charge*1.5`.
- Held tick rotates `+0x154` by `0.75` degrees about normalized axis
  `(0,-0.8,1)` through `0x00403340`. Release preserves and stops that matrix;
  the flight body does not keep flat-spinning.
- Held tick `0x00609D30` separately registers `Anim_CalledRock` objects. Their
  `0x00457FF0` tick accelerates inward from `0.1` by `x1.1` to a cap of `5`,
  removing inside distance `5`; `0x0045E440` draws lit
  `BadGuys[2008..2010]`. Spawn radius is sampled below
  `clamp(50*charge,5,120)`. Optional `BadGuys[18]` dust is another sibling
  actor, not part of the main rock list.
- Impact vslot `+0x6C` (`0x0060B700`) emits
  `floor(max(8,30*charge))` `Anim_BoulderBit` fragments using the same lit
  `[2008..2010]` bank, registers each through `ZAnimLitObject`, and removes the
  Boulder. Subclass fade is float32 `0.025` every tick; the base adds float32
  `0.015` except active-motion global ticks divisible by three. Settled
  fragments receive both decrements even on divisible ticks.
- Normal flight `0x00620B60` writes the velocity-advanced actor position
  before contact queries. A terminal breakup therefore uses that advanced
  contact sample rather than the preceding clear position.

This also corrects the prior human summary: `BadGuys[86]` is neither a charge-
scaled body sprite nor the persistent aura. A renderer that draws only record
86 necessarily omits record 15 and the actual Boulder.

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
  does not repeatedly apply its contact payload to the same actor. The Ring
  factory `0x00644460` starts float32 life at `0.924` and radius at `75`.
  `0x005FFDC0` subtracts `0.01`, adds six radius units, queries only every
  tenth age tick, multiplies alpha by `0.9` below life `0.12375`, and retires on
  update 93. Its vtable light slot resolves to the same `0x005E7AA0` callback
  as Shockwave: radius is `waveRadius/140`, intensity is the current alpha, and
  shadows are disabled. The factory's presentation children are independent
  world actors. Three additive DeadHawg-114 fades start at life `4.5`, decay
  `0.05`, consume one `Float(360)` rotation each, scale by `1.02`, `1.015`, and
  `1.01`, and use perspective Y `0.8`. One normal DeadHawg-121 fade starts at
  life `1.75`, decay `0.01`, and scale `1.5`. It also constructs 100
  `Anim_WhirlSnow` children, or 200 with Enhanced Effects, all using
  `BadGuys[72]` rather than records 203..207. Constructor/tick/draw
  `0x004588E0/0x00453F70/0x00458A00` consumes angle `Float(360)`, angular
  velocity `10+Float(10)`, radius `20+Float(40)`, radial velocity
  `1+Float(4)`, height `50+Float(250)`, scale `1-Float(0.5)`, rotation
  `Float(360)`, and life `2+Float(1.5)`. Tick advances angle, multiplies angular
  velocity by `0.975^2`, multiplies height by `0.99`, expands radius by
  `radialVelocity*min(angularVelocity,1)`, advances rotation, and subtracts
  `0.02` life. The complete factory consumes `3+8*N` visual draws (803 normal
  or 1,603 enhanced), and these children persist for as many as 175 ticks,
  outliving the 93-tick gameplay wave. Records 16/17 are not this program.
- `TragicCircle` extends `MagicCircle` and keeps the base circle tick while
  replacing both its particle presentation and actor-side effect.
- `DarkFireball` extends `Firebolt`; `Silk` extends `Arrow`; `SkullMissile`
  extends `GuidedMissile`; `EvilEmber` extends `Ember`.
- `RainOfBones` begins with the `AcidRain` constructor, then replaces the type,
  duration, render passes, and tick payload.

## Missile behavior and lifecycle

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
| Silk tick `0x005F8B50` | `0x1B79` | attach/merge `Mod_Webbed`; full severity creates target-owned Cocoon |
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

### Spider Silk, Webbed modifier, and Cocoon

Spider's attack helper `0x00475AC0` creates `Silk 0x808`, not Cocoon. It
copies aim/team state and the configured Cocoon-strength value into Silk
`+0x22C`. Silk extends Arrow for movement/rendering, but its collision tick
`0x005F8B50` creates `Mod_Webbed 0x1B79`, copies `+0x22C` to modifier `+0x20`,
and applies the modifier to the struck actor.

`Mod_Webbed` is a real factory type with constructor `0x00623B10` and vtable
`0x0079E5E4`. It initializes severity `+0x1C` to one. Apply method
`0x00623B50` sets target flag `+0x138 bit 0x20` and scales target movement
field `+0x218` by `max(0, 1 - severity/nativeThreshold)`. Merge method
`0x00627BD0` increments the existing severity, retains the maximum payload at
modifier `+0x20`, and on the first transition to full severity invokes
`0x0052C680` with the struck target actor as `this`.

The target actor—not Silk—owns duplicate suppression. `0x0052C680` retains
the maximum web payload at target `+0x20C`, resolves the Cocoon identity at
target `+0x214/+0x216`, and returns if it is still live. Otherwise it creates
`Cocoon 0x80A` at the target position, writes target identity to Cocoon
`+0x210/+0x212`, registers the Cocoon, and stores the new Cocoon identity back
on the target. Cocoon snapshots its fixed position in `0x0047BB50` and
`0x00475D10` keeps it there while the full web state immobilizes the target.
Its contact/death callback `0x0048BCE0` resolves that target identity and owns
release/death presentation. Normal enemy drops explicitly exclude Cocoon.

## Expanding waves

`Shockwave`, `FreezeWave`, and `Knockback` are list-backed area effects rather
than drawable missile sprites:

- Shockwave expands its radius, fades near expiry, queries intersecting actors
  every ten ticks, applies `Dazzle (0x1B6E)` once per actor, and can also push
  tracked actors radially through `0x00525800`. Draw slot `0x005E7AA0` submits
  DeadHawg record 18 to the Region light field with radius `waveRadius/140`,
  intensity equal to the fading push scalar, and shadow flag false; there is no
  separate main-pass Shockwave missile sprite.
- FreezeWave uses the same expanding/list pattern and selects `ColdSlow
  (0x1B69)` or `Frozen (0x1B6F)` according to target flags. Object flag
  `+0x174 & 0x10` adds `FrostBurn (0x1B78)` before contact dispatch. The Ring
  of Ice item feature is the ordinary player-factory writer of that bit.
  FrostBurn duration is `round(FreezeWave+0x14C * 200)`, its per-tick damage is
  exactly `1/200`, and tick `0x006278B0` dispatches flags `0x18` while owning a
  separate randomized icy additive-particle branch.
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

### Prismatic Shock cast animation

`0x00645540` creates one `Anim_PrismaticSpray` through constructor
`0x004543B0`; the helper does not create a fixed triangle of atlas records.
Construction consumes one sign word for angular velocity `+/-1`, starts radius
scalar `2`, alpha `0`, and countdown `100`, and attaches the animation to the
caster. The helper then requests `prismaticspray__stream` at point gain and
`lightningstart` at pitch `0.8` with the same gain. Only after those requests
does `RandomInt(5)` select the Region color. The gameplay query is a
mask-`2`, radius-`350` circle centered on the caster; every returned target
receives `Mod_Prismatic (0x1B76)` immediately during the cast helper.

Tick `0x00460360` follows the caster at `(x,y-25)`, adds float32 `0.025` to
alpha capped at one, advances heading by signed six degrees, grows the radius
by float32 `0.065` for the first 50 ticks, then shrinks it by float32 `0.075`
for the final 50. Each tick first consumes a discarded signed `RandomFloat(5)`
and then registers exactly three independently owned children:

- two additive `BadGuys[111]` `Anim_FadeAdditive` children. Each independently
  selects one of the five prismatic colors, applies
  `clamp(color*1.5,0,1)` and then a per-RGB floor of `0.5`, chooses radius
  `waveRadius*[30,90]`, rotation `[0,360]`, scale `[0.25,1]`, and life
  `[0.25,1.25]`; default loss `0.1` is multiplied by `0.25`, so loss is
  `0.025/tick`.
- one additive perspective `BadGuys[10]` or `[11]`
  `Anim_FadeMoveAdditive_Perspective`. It independently selects and brightens
  the same palette, chooses radius `waveRadius*[50,80]`, record by
  `RandomInt(2)`, rotation `[0,360]`, scale `[1,3]`, and outward velocity
  `[0.15,1]` along the current heading. Life is `[0.5,1]`, loss is
  `0.015/tick`, and draw applies the common `0.8` Y-perspective factor.

The parent draw `0x00459500` uses inline `BadGuys[58]` with additive blend,
not records 10/11. Its per-draw alpha is
`0.5*parentAlpha*(0.5+RandomFloat(0.5))`, rotation is
`heading*angularSign`, and scale is
`(angularSign*waveRadius*1.5, waveRadius*1.2)`. The tick consumes exactly 19
RNG words: two for the discarded signed float, five for each record-111
child, and seven for the moving record-10/11 child. The parent retires after
its hundredth update; all registered children finish their own fade/movement
lifetimes afterward.

### Magic Circle (`0x7EA`)

`MagicCircle` starts with a 1,500-tick lifetime at `+0x144`, fixed scale `4`,
footprint width `420`, Y-perspective `0.8` (half extents `210x168`), and RGBA
`(1,1,1,0.5)`. Its tick `0x006006E0` decrements that counter, writes a
shadow-casting Region light at the circle center with radius `scale*0.5 = 2`
and intensity `0.75+RandomFloat(0.25,signed=true)` (`0.5..1`), emits the
class's ring particles through virtual `+0x64` every tick, and invokes the
area-effect callback at virtual `+0x68` when the ten-tick counter is zero
before increment. The first actor update is therefore an effect pulse.
`0x005FB020` queries the circle footprint and has two separate effects:

- eligible non-player actors receive `Mod_CircleSlow (0x1B70)`; its value is
  copied from circle `+0x140`;
- the local player receives `mana_recovery * 2 / game_timing_scale` MP, capped
  at max MP; and
- the advertised HP boost is inert in stock. The callback computes
  `candidate = HP + health_regeneration * 2 / game_timing_scale`, compares that
  candidate with current HP instead of max HP, and for ordinary positive
  regeneration writes current HP unchanged.

When the local player is inside on an effect pulse, the callback also attaches
one additive `Anim_FadeScale` using `BadGuys[7]` to that player. It starts at
local `(0,-15)`, tint `(0.5,1,1)`, random rotation `[0,360]`, scale
`1+RandomFloat(1)*0.65` (`1..1.65`), life `[0.5,0.75]`, loss `0.05/tick`, and
multiplies both scale axes by `1.1` each tick. Record 7 is not a persistent
sprite at the circle center.

Ring emitter `0x005F3CA0` creates one `Anim_SpinAwayAdditive` child on even
global ticks and two on odd global ticks. Every child uses centered
`BadGuys[48]`; there is no 24-point ellipse. Base scale `(4,3.2)` is multiplied
by `0.975+RandomFloat(0.025)`, initial life is
`min(remaining/100,1)*(0.5+RandomFloat(0.5))`, loss is `0.05/tick`, rotation is
`RandomFloat(360)`, and signed angular velocity is
`+/-(0.5+RandomFloat(1))` degrees/tick. Each child consumes five RNG words.
The circle removes itself when lifetime reaches zero; its registered record-48
and record-7 animation actors finish independently.

### Magic Trap (`0x7F5`)

`MagicTrap` stores its derived element at `+0x13C`, the full-charge payload
`f32(selectedPrimaryBaseDamage * trap mDamage)` at `+0x140`, charge fraction at `+0x144`, charge
increment at `+0x148`, animation frame at `+0x14C`, age at `+0x150`, and the
decaying armed shimmer at `+0x154`. The increment is the float32 result of
`1 / (mFullChargeSeconds * 100)` and is added with one float32 rounding per
tick before the charge is clamped to one; the shipped eight-second
configuration reaches the clamp on update 800. `0x00603710` registers the
trap in the world's effect draw list each tick and, for the authoritative
local group, polls a 130-wide group-2 footprint on ages divisible by 25.

Dispatcher `0x0054CC50` finishes selector ownership before it computes that
payload. A welded build first consumes `Integer(2)` and chooses one component;
selector `0..4` then maps to primary skill `8,16,24,32,40` and looks up that
specific skill's effective rank. Ether loads `mDamage1` and `mDamage2` and
calls inclusive float-range wrapper `0x00448480`, consuming exactly one more
gameplay RNG word. Fire, air, water, and earth load their selected skill's
single `mDamage` and consume no damage draw. The resulting base is multiplied
by Magic Trap's ranked `mDamage` and rounded into `+0x140`. Consequently a
welded trap does not use the equipped synthetic spell's aggregate damage, and
an Ether trap does not deterministically use Magic Missile's maximum.

Initialization `0x005E95D0` writes the selector color to the Region lane,
plays `settrap__Stream`, and then plays the bound primary's start sample:
selector `0..4` maps to `magicmissile`, `throwfire`, `lightningstart`,
`icestart`, and `startboulder`. The armed presentation is not a generic
eight-frame trap sprite:

- draw `0x00619CD0` bobs by `5*sin(age degrees)-12`; its charge scale is
  `0.5+0.5*charge`, multiplied by `0.75` while charge is strictly below the
  float32 threshold `0.9900000095`. At that bobbed point it draws additive
  `BadGuys[111]` rotated by `+2*age` degrees and `BadGuys[112]` rotated by
  `-3*age`, both with perspective Y scale `0.8`, and alpha
  `0.5-0.125*sin(age degrees)` multiplied by the pre-full charge scale. It
  then draws additive selector-colored `BadGuys[15]` at the unbobbed trap
  point, scale two, alpha `0.375-0.125*sin(age degrees)` with the same
  pre-full multiplier. Finally it restores normal blending and draws opaque
  `BadGuys[85]` at the bobbed point with X scale
  `1-0.1*sin(2*age degrees)` and Y scale
  `1+0.1*cos(age degrees)`. The unused `+0x14C` quarter-frame accumulator
  still advances and wraps, but records `393..400` are not submitted by this
  shipped draw path.
- auxiliary slot `0x005E9700` draws normal `BadGuys[15]` in black at alpha
  `0.5` and scale `0.75` as the trap shadow.
- shimmer starts at float32 `3`, multiplies by
  `0.8999999761581421` before each emission, and is set to zero below
  `0.10000000149011612`. Updates 1 through 32 therefore each register one
  normal `BadGuys[16]` `Anim_Fade_Perspective`. Each consumes
  `Float(360)` rotation then `Float(0.25)` alpha jitter, uses the selector
  tint, scale `3*shimmer` with perspective Y `0.8`, starts alpha at
  `0.75+jitter`, and loses float32 `0.05` per tick. These children finish
  independently if the trap detonates.

`0x005F5C80` is the one-shot trigger. It emits the element-colored burst,
queries a separate 300-wide group-2 footprint, sets damage to
`f32(fullChargePayload * charge)` with no minimum clamp, dispatches to every
actor returned, and removes
the trap. Thus a hostile inside the 130-wide arming footprint triggers one
detonation that reaches every eligible target inside the wider 300-wide
payload footprint. The element payload is explicit:

| Trap element selector | Additional native effect |
| ---: | --- |
| `1` | common fire helper `0x00624210`, which creates `Mod_Burn (0x1B73)` |
| `2` | `Mod_ElectricBurn (0x1B6B)` |
| `3` | `Mod_ColdSlow (0x1B69)` |
| other | direct trap contact only |

The water branch constructs `Mod_ColdSlow` with slow factor
`f32(0.5 / permafrostSlowScale)` and lifetime
`max(50, trunc(tickRate * 4 * charge))`; at the retail 100 Hz tick rate this is
`max(50, trunc(400*charge))`. The conversion call at `0x005F6271` truncates
toward zero, so ordinary rounding is observably wrong after the minimum floor
stops dominating.

The air-selector branch is a target-owned modifier, not a lightning sprite.
Terminal helper `0x005F5C80` constructs `Mod_ElectricBurn` type `0x1B6B`,
writes duration `100` at `+0x14`, per-update damage
`trapContactDamage / 100.0` at `+0x1C`, chain count zero at `+0x20`, scalar one
at `+0x24`, and the trap group byte at `+0x28`; it then attaches the modifier
and clears the trap's direct-contact damage. Constructor `0x006231D0` and
merge callback `0x00625A70` establish one modifier per target: reattachment
keeps the greater remaining duration but replaces damage, chain count, scalar,
and group from the new payload rather than stacking a parallel actor.

`Mod_ElectricBurn::Tick` at `0x00628F10` consumes signed `Float(0.25)` every
live update and appends a target-position, non-shadow-casting Region misc light
with radius `0.5+jitter` and intensity one; the same live edge renews
`sounds\\electric__loop`. Its authoritative contact path supplies the stored
per-update damage and flags `0xA`, consumes `Integer(3)`, and only when that
draw equals one consumes another `Float(0.5)` for the native contact scalar
`0.25+jitter`. The trap writes chain count zero, so the later
`Anim_FadeLightning` direct/chain branch is never entered: the complete
100-update trap payload is damage, light, loop renewal, and exact RNG
consumption with no submitted lightning sprite.

The trigger presentation first registers one normal `BadGuys[15]` fade at
`(x,y-25)`, scale six, alpha one, loss `0.1`. It then replays two additive
`BadGuys[158..167]` sprite arrays and 100 additive `Anim_FuzzySpear` children
at `(x,y-35)`. The arrays consume `Float(360)` rotations, use scale six, and
advance by float32 `0.15` and `0.225` frames per tick. Each spear consumes
`Float(360)` heading, `Float(2)` speed jitter, `Integer(5)` double-speed gate,
`Float(1)` alpha jitter, and `Float(1.5)` scale jitter; it uses the same
record-17/record-74 two-pass draw, 75-unit start, velocity, `0.95` damping,
`0.035` alpha loss, and presentation-time horizontal sign as Explosive
Shield. Construction therefore consumes exactly `2+100*5 = 502` RNG words.
The trigger also plays `trap__stream`, writes selector-colored point-gain
Region feedback with loss `0.05`, and starts camera/world pulse `1.25`, which
the Region multiplies by `0.94` and clears below `0.001`.

The deleting destructor `0x005E95A0` delegates to the normal `Puppet`
teardown; the trigger's presentation objects are world-owned.

### Dampen helper (`0x00648DF0`)

The dispatcher passes sentinel `-1`, so the helper first consumes one
`RandomInt(100000)` action-identity word. It then resolves hostile magic,
including the per-shield `RandomInt(100) < 0x33` dispel rolls, before creating
the visual field. The visual program is 390 independently registered wrapper
objects, not one expanding ring:

- 360 source-over `Anim_MoveFade` children, one for every integer heading
  `0..359`. Each selects BadGuys record 10 or 11 with `RandomInt(2)`, starts at
  the caster, moves radially at `6+RandomFloat(4)` units per tick, and damps its
  velocity by `0.96`, except `RandomInt(6)==3` selects `0.93`. Rotation is an
  independent `RandomFloat(360)`, uniform scale is
  `1.5+RandomFloat(0.5)`, alpha starts at one and loses
  `0.01+RandomFloat(0.02)` per tick, and its grayscale tint is
  `RandomFloat(0.25)` in every RGB channel. A final `RandomInt(5)` chooses the
  native registration lane but does not change those parameters. Thus each
  child consumes exactly eight RNG words and follows its own 34-to-100-tick
  fade/movement lifetime.
- 30 additive perspective `Anim_FadeAdditive_Perspective` children using
  BadGuys record 48 at the caster. Each consumes rotation
  `RandomFloat(360)`, scale `0.75+RandomFloat(4.75)`, and initial alpha
  `0.5+RandomFloat(1)`; alpha loses `0.1` per tick and the draw applies the
  common `0.8` Y perspective.

The visual suffix therefore consumes exactly 2,970 RNG words after gameplay
resolution. `flash.wav` and `dampen__stream.wav` are the only presentation
audio, and Dampen writes no Region full-screen feedback lane. The separate
mode-21 CastSpin action remains a 73-update player animation and is not the
owner of these independently expiring world children.

### Magic Shield break and Explosive Shield (`0x00546650`, `0x00648790`)

Magic Shield is player-owned state, not a persistent world actor. Install or
refresh writes the absorb pool and Explosive Shield factor to the wizard; the
player renderer draws additive `BadGuys[49]` at `(x,y-30)`. Its base scale is
`1.5`. An absorbed hit starts a 40-tick pulse at scalar `2`, subtracts `0.05`
per tick, drives red brightness with
`0.5*(max(pulse,1)-1)+0.25`, and drives scale with
`1.5+0.1*sin(age*20 degrees)*min(pulse,1)`.

Break callback `0x00546650` plays `popshield` and registers exactly 20
additive `BadGuys[68]` `Anim_FadeAdditive` children at `(x,y-35)`. Each child
consumes, in order, `Float(360)` rotation, `Float(0.75)` alpha jitter, and
`Float(0.25)` scale jitter. Alpha starts at `0.5+jitter`, loses `0.05` per
tick, and is clamped to one only while drawing. Uniform scale is
`2+jitter`. The break prefix therefore consumes exactly 60 RNG words. It then
calls the Explosive Shield helper only when the installed factor is positive,
and clears the absorb/factor fields after that one terminal dispatch.

Explosive Shield helper `0x00648790` uses fixed radius scalar `2` and payload
`installed_absorb * mDamage/100`. Its presentation program is, in registration
order:

- one normal `BadGuys[15]` `Anim_Fade` at `(x,y-25)`, scale `2*6=12`, alpha
  `1`, loss `0.1`;
- one normal `DeadHawg[2]` `Anim_FadeScale` at `(x,y-35)`, scale `2.5`, scale
  factor `1.01`, alpha `1.5`, loss `0.05`;
- two additive `Anim_SpriteArray` children over `BadGuys[158..167]` at
  `(x,y-35)`, scale `6`, independently consuming `Float(360)` rotation. Their
  frame increments are `(0*0.1+0.2)*0.75 = 0.15` and
  `(1*0.1+0.2)*0.75 = 0.225` per tick; each removes itself when its float32
  frame reaches the ten-record array length;
- 100 additive `Anim_FuzzySpear` children. Each consumes `Float(360)` heading,
  `Float(2)` speed jitter, `Integer(5)` double-speed gate, `Float(1)` alpha
  jitter, and `Float(1.5)` scale jitter. It begins 75 units along the native
  clockwise heading, moves at `3+jitter` units per tick (doubled only when the
  integer result is `2`), multiplies velocity by `0.95`, starts alpha at
  `1+jitter`, loses `0.035` per tick, and uses scale `2+jitter`. Draw
  `0x00458B70` emits `BadGuys[17]` at authored scale with a fresh random
  horizontal sign and then `BadGuys[74]` at the child scale; both use the same
  position, rotation, clamped alpha, white color, and additive blend.

The helper's construction suffix consumes exactly `2 + 100*5 = 502` RNG
words; the per-draw FuzzySpear mirror is presentation-time RNG and is not part
of that construction count. It writes Region feedback `(0.5,1,1,pointGain)`
with loss `0.05` and directly writes camera/world pulse magnitude `1.25`.
Region tick subsequently multiplies that magnitude by `0.94` and zeros it
below `0.001`.

The immediate hostile query radius is `2*55 = 110`. The helper writes
`payload*0.5` to both contact lanes `0x0081C6E8` and `0x0081C6EC`; native
target contact sums those lanes, so the HP delta is the full payload, not half
or double. It also creates one light-only `Shockwave (0x7E7)` with radius `75`,
growth `6/tick`, push/alpha scalar `1`, life `0.35`, fade threshold `0.0375`,
and damage zero. That wave retains the standard ten-tick distinct-target
Dazzle/query and tracked radial push behavior while its `0x005E7AA0` callback
submits the expanding no-shadow Region light; it owns no main-pass sprite.

### Magic Storm / Storm Cloud (`0x7F0`)

`StormCloud` begins with a 1,000-tick active lifetime and a 50-tick first-strike
counter. `0x006021A0` starts scale at `0.01`, multiplies it by `1.2`, grows
alpha by `0.05`, emits two cloud particles per tick (five in the enhanced
presentation mode), and after active expiry subtracts float32 `0.01` until the
101st fade update retires it. On the authoritative group it queries a 500-unit
hostile footprint, chooses a random target, rolls damage between
`+0x178/+0x17C`, dispatches contact with flag `0x20`, and stores three points
used by the lightning presentation. After target selection the geometry draws
source distance/unit vector (height 175, radius 100), midpoint distance/unit
vector (height 90, radius 200), then damage; the target endpoint is 15 units
high. Its
short strike-energy counter drives `Anim_FadeLightning` and the generated
lightning mesh. The alternative moving-cloud mode is enabled at `+0x180` and
advances the cloud and its 15 presentation control points along its heading.
Magic Tornado initialization `0x005E2440` stores
`frequency_factor = 1 + mSpeed/100` at `+0x154` and adds
`trunc(mDuration * 100)` ticks to the base lifetime. In moving-cloud mode the
strike countdown resets to `trunc(numerator / frequency_factor)` for a uniform
integer `numerator` in `[30,120]`. Translation uses the cloud's separate fixed
motion path: the configured `mSpeed` property is strike frequency, not
translation speed. Constructor `0x005E22E0` first consumes signed `Float(1)`
for phase `+0x150`, then `Float(360)` and `Float(2)` for each of fifteen
control-point angle/speed pairs. Point `i` receives
`(1 - i/15 * 0.95) * (2 + draw) * 4`. Tornado initializer `0x005E2440`
multiplies phase by 15 before consuming its `Float(360)` heading, so every
cloud advances the authoritative stream by 31 visual draws and the moving
variant by a 32nd.

Tick creates child rain before movement and strike work: two
`Anim_Raindrop`s, five with Enhanced Effects, integer-halved to one or two for
Tornado. Each consumes `Float(200)` and one unit-vector draw. Constructor/tick/
draw `0x00454170/0x004541A0/0x00458F90` starts height at `-175`, adds 20 to it
and four to streak length until ground, then grows the ground mark from `0.1`
by `1.1` until scale exceeds one. The falling width-two streak grades from RGBA
`(0.8,0.95,1,0.5)` to `(0.4,0.95,1,0)` and the ground alpha is `1-scale^2`.

Moving Enhanced draw `0x005E8970` samples a QuickSpline through root, root plus
the unit vector at `globalTick*0.5` degrees times 30, and root minus 175 Y.
Fifteen iterations at `0.2` steps
draw `BadGuys[84]` at `t` and `t+0.1`; scale begins `0.2` and recurs as
`scale*1.1+0.1`, rotations are control angle and `angle*1.35`, perspective Y is
`0.8`, and tint is `(0.8,1,1)`. It finishes with `BadGuys[78]` at root minus
`50*scale`, scale `3.75*cloudScale`, and half alpha. Auxiliary painter
`0x00602C30` separately composites a shared weather render target in
moving/static branches and owns the strike flash; it is not one cloud sprite.
Light callback `0x005EB5C0` submits radius `2`, intensity `0.5*alpha`, and no
shadow. Tornado tick consumes `Float(2)` and translates itself and all fifteen
points by float32 `0.349999994`.

The auxiliary painter is now resolved completely. It shifts the painter root
up 175 units and always sources exact `BadGuys[78]`
(`DAT_00819978 + 0x3BF0`). A stationary cloud clears the shared transparent
render target, draws these three source-over passes around its midpoint, then
draws that target at the cloud root with scale five:

1. white, alpha `cloudAlpha*2`, rotation
   `age*0.0625*0.5*phase` degrees, scale
   `(cloudScale, cloudScale*0.8)`;
2. RGB `(0.8,1,1)`, alpha `cloudAlpha*0.75`, rotation
   `(age/24)*0.5*phase` degrees, scale
   `(cloudScale*0.75, cloudScale*0.8*0.75)`, and target-local Y
   `cloudScale*(-50)/5`;
3. RGB `(0.8,1,1)`, alpha
   `cloudAlpha*(0.5+sin(age*0.5 degrees)*0.5)*0.75`, rotation
   `age*0.125*phase` degrees, X scale `cloudScale*0.5`, Y scale
   `cloudScale*0.8*(0.5+sin(age/6 degrees)*0.25)`, and target-local Y
   `cloudScale*(-30)/5`.

The final scale-five composite therefore places the second and third pass at
world-local Y `-50*cloudScale` and `-30*cloudScale`, respectively, in addition
to the common `-175` painter-root shift. The moving branch skips the render
target and draws another additive `BadGuys[78]` at local Y
`-175-50*cloudScale`, RGB `(0.8,1,1)`, alpha `cloudAlpha*0.5`, rotation
`(age/24)*0.5*phase`, and uniform scale `cloudScale*3.75`.

Cloud field `+0x14C` is the strike/ambient-flash gate. A successful target
selection writes one, and the common tail subtracts float32 `0.1` during that
same update, so the first post-tick state is `0.9`. Independently, every tick
ends with `RandomInt(1000)`; result three restores the field to one after the
decay and emits its positioned weather sound. This draw is therefore part of
the authoritative RNG stream even while the cloud is fading; a winning roll
also consumes `Float(0.35)` for the Thunder stream's volume multiplier. While the field
is nonzero, `0x00602C30` selects diffuse color instead of texture RGB and draws
a white alpha-mask of `BadGuys[78]` at local Y `-175`, rotation
`age*0.0625*phase`, scale `(cloudScale*4, cloudScale*0.8*4)`. The native source
sets the renderer alpha from `+0x14C` and immediately overwrites it with
`cloudAlpha*0.75` before queuing the quad; consequently `+0x14C` gates the
ten-tick branch rather than continuously fading its opacity.

### Firewalker `Fire_Goodguy` birth and contact ownership (`0x7EE`)

Firewalker has no BadGuys-record-11 ember child. Fresh instruction ranges
`0x0054B39A..0x0054B53C` and `0x0054CDD1..0x0054CF48` create and register only
`Fire_Goodguy 0x7EE`; constructor `0x005E76C0` inherits `Fire 0x005E7130`, and
draw `0x00610F90` owns only the additive DeadHawg `46..77` strip. BadGuys 11
belongs to adjacent Ether presentation and must not be attributed to this
ability. A Burn learned on the target remains the separate modifier-owned
BadGuys `333..342` path below.

Toggle-on creates one patch immediately, sets its `+0x160` contact-geometry
byte to one, and leaves the process-global periodic counter at `0x00819E54`
unchanged. The active player tick creates another patch whenever the global
tick is divisible by ten and player mode is not two, even when velocity is
zero. Each periodic birth sets `+0x160` only when the counter's pre-increment
value is zero, then advances and wraps it as `0,1,2,0`; the resulting geometry
sequence is therefore `true,false,false`. Visually identical disabled patches
still tick, draw, fade, and renew `lowfire__loop`, but never build the collision
point list in `0x005FF1D0`.

Every activation or periodic birth consumes exactly seven RNG words in this
order: inherited constructor `Float(32)` phase, constructor `Sign(1)` mirror,
signed `Float(10)` (magnitude plus sign), unsigned `Float(8)`, `Float(0.5)`,
and `Float(0.25)`. For player velocity `(vx,vy)`, the two offset draws produce
`position += (vy,-vx)*signed10 + (vx,vy)*unsigned8`. Scale is multiplied by
`1-Float(0.5)`. Cached rank duration is multiplied by
`1.1-Float(0.25)`, then tick `0x005FF050` subtracts float32 `0.01` until
removal. Cached rank damage is copied unchanged. Contact polling occurs only
on global ticks divisible by three; the strict center radius is
`32*patchScale`, and target radius does not widen it.

Fire Wall uses the same actor and contact method but not Firewalker's periodic
geometry cycle. Its creation loop `0x0054F759..0x0054F8EC` writes
`Fire_Goodguy +0x160=1` unconditionally at `0x0054F883` for every one of the
eleven patches. Consequently all wall patches build contact geometry and can
damage; `+0x160=false` is specific to two of every three periodic Firewalker
births.

### Embers to Imps and GoodImp (`0x7D6`, `0x3ED`)

`Ember::Tick 0x0060D7E0` checks the mode short at `+0x164`. Only a naturally
spent, grounded Ember with life below `1` enters the retirement branch; actor
contact consumes it without retirement. When an authoritative mode-2 Ember is
spent, it creates `GoodImp 0x3ED`, copies team/owner state, writes one half of
the snapshotted damage short to both Imp attack lanes `+0x1B4/+0x1B8`, copies
the lifetime short to Imp `+0x23C`, and registers the summon. The same branch
creates a `Fire 0x7E3` patch before removing the Ember. Mode 1 instead invokes
the common explosion helper with scale `1`, no fragments, and one-half of its
snapshotted Immolate damage per returned target.

GoodImp construction `0x00529FE0` defaults `+0x23C` to 300 ticks. Initialize
`0x0052A050` acquires the nearest eligible target for a locally authoritative
Imp. Tick `0x0052C1A0` owns pursuit and decrements the lifetime once per tick,
with an additional decrement while no target is available. Expiry creates a
`Fire 0x7E3` patch and removes the Imp.

### Fire Burn modifier (`0x1B73`)

The common fire helper `0x00624300` reads the attacker's cached Burn row at
`+0x89C` and calls `0x00624210`. A positive payload constructs
`Mod_Burn 0x1B73` with exactly `200` native ticks and stores damage per tick as
`payload/200`, so uninterrupted lifetime damage equals the authored row-22
value. `Mod_Burn::Tick 0x00629A40` applies that fixed amount on every tick with
damage flags `0x18`. Specialized merge `0x00627690` keeps the greater remaining
duration and greater per-tick damage; it does not stack parallel instances.

The modifier's presentation cycles BadGuys records `333..342` by
`(global_tick/3)%10`. Every modifier tick consumes `RandomFloat(0.25)` and
registers one additive `Anim_FadeAdditive` at `(target.x,target.y-15)`, with
uniform scale `(1+draw)*target.scale`, alpha `fade*0.125`, and alpha loss
`0.01` per tick. It then consumes `RandomFloat(0.1)` and appends a Region
misc-light at the unshifted target point with radius `0.1+draw`, intensity
`fade`, and shadow flag false. Here `fade` is one until the remaining duration
falls below 50 ticks, then `remaining/50`; this is a terminal fade, not an
initial ramp. The animation and misc-light therefore consume exactly two
active gameplay RNG words per modifier tick. This is target-owned modifier
presentation, not a new projectile or a caster-local skill timer.

### Lightning Stun modifier (`0x1B6A`)

Lightning `0x0053F9C0` creates `Mod_Stun 0x1B6A` only when the wizard's
resolved movement factor at `+0x288` is below one. It copies that factor to
modifier `+0x1C` and writes a fixed 25-tick lifetime at `+0x14`. Constructor
`0x00623180` defaults the factor to one; apply `0x006231B0` multiplies target
movement `+0x120`. Specialized merge `0x00625850` retains the maximum remaining
duration and minimum movement factor, so stronger reapplication wins without a
parallel modifier.

### Acid Rain (`0x7FE`)

`AcidRain` consumes `Float(1)` for its private presentation phase, starts at
scale `0.01`, and has a 1,500-tick active lifetime, a separate
fade/ground-residue scalar, and a 25-tick authoritative hit cadence after its
initial 50-tick delay.
`0x00604E90` emits two `Anim_AcidRaindrop` children every tick, or five while
the shipped Enhanced Effects byte is enabled. It queries the hostile area,
shuffles the candidate list through `0x005E41F0`, and damages exactly
`min(n, floor(n / 3) + 1)` returned actors on a pulse. The loop always consumes
the shuffled entry at index zero first, increments the damaged count, and
breaks when `floor(n / 3) < damaged`; this is why one or two candidates still
produce one contact. Its contact uses the damage written at
`+0x154`, divides it by the compiled double `6.0` at `0x007852E0`, stores the
result as float32 in the shared contact record, and sets flags `0x18`. This is
not the generic `/100` fire/contact normalizer.
The rain does not allocate a poison modifier; its damage is direct. Each drop
starts at height `-175`, advances by 20 while its streak velocity gains four,
then grows its ground sprite from `0.1` by float32 `1.100000023841858`.
Its falling width-three procedural streak grades from RGBA
`(0.7,0.95,0.75,1)` to `(0.4,0.95,1,0)`, with a quarter-alpha `BadGuys[0]`
head tinted `0xb3f2bf`; the ground sprite uses tint `0xccffcc` and alpha
`1-scale^2`. After the configured drops, a one-in-four gate may construct a
BadGuys-10 splash,
consuming the recovered discarded rotation, rotation, scale, distance, and
unit-vector draws; life is `0.25`, decay `0.0125`, and velocity damping `0.95`.
Parent painter `0x005EB290` owns two distinct BadGuys-10 passes. With field
scale `s`, ground/residue scalar `g`, age `a`, and constructor phase `p`, the
first is additive, tint `(0.41,0.55,0.32)`, alpha `0.75*g`, rotation
`a*0.03125*p` degrees, and scale `(5*s,4*s)`. The second is tint
`(0.25,0.45,0.15)`, source-over, alpha `g`, rotation `-0.5*a` degrees,
local Y `-50*s`,
and scale `(7.5*s*p,6*s)`. Auxiliary pass `0x005EB1D0`, while rain alpha is
positive, draws BadGuys-10 source-over at the field root with tint `(0.05,0.1,0.05)`,
that rain alpha, and uniform scale `4.5`; it is not a red quarter-scale sprite.
After activity, ground alpha takes 100 ticks to fade and remaining rain alpha
takes 2,000, yielding the 3,600-tick maximum ownership window. Light callback
`0x005EB5C0` submits radius `2`, intensity `0.5*alpha`, and no shadow.

### Earthquake (`0x7F1`)

Constructor `0x005E8EA0` installs duration at `+0x13C`, an initialized
`PointerList` at `+0x140`, scenery cursor zero at `+0x158`, intensity one at
`+0x15C`, `RandomFloat(360)` floor rotation at `+0x160`, birth flag one at
`+0x164`, green-overlay scalar two at `+0x168`, and floor phase `-5` at
`+0x16C`. Initializer `0x005F45A0` performs the group-`4` scenery query with a
1,024-unit supplied width. The underlying spatial query `0x00523140` halves
that width and accepts only strict center distance `< 512`; it appends every
returned scenery pointer and shuffles the complete list with `0x005E41F0`.
That shuffle consumes one `RandomInt(N)` for every index `0..N-1`, swapping
the current entry with the selected entry; it is not Fisher-Yates. Constructors
for Tree `2001`, Gravestone `2029`, and Building `2040` assign group `4`;
Goodie `2061` assigns `0x2004`, so every stock-generated scene object matches
the group-`4` mask. The stored per-scenery wobble field is consumed by Tree
drawing, while every matched entry remains eligible to own dust.

Tick `0x00613200` first advances floor phase by float32 `0.05` and drains the
green scalar by the same amount. Crossing `0.6` or `3.0` resets that scalar to
one; only the `3.0` crossing requests `QuakeCrackSmall__Stream`. The birth flag
requests `rockhit` and `QuakeCracks__Stream`, both at Region perspective gain,
then clears itself. The live actor renews `earthquake__loop` through global
maximum-intensity owner `DAT_0081CB70`. It writes
`+0x15C = min(pre-decrement remaining, 200) / 200`, consumes
`RandomFloat(3, signed=true)`, and submits camera candidate
`(randomX, sin(remaining * 20 degrees) * 10 * intensity)` to Region helper
`0x00448590`. That helper replaces Region `+0x8E0C/+0x8E10` only when the
candidate's squared magnitude exceeds the vector already stored there, so
simultaneous shake owners select the largest vector instead of summing. The
duration is then decremented; zero schedules removal, but the current update
continues.

The authoritative pulse tests **post-decrement** `remaining % 30 == 0`. It
queries group `2` at strict center distance `< 512`, applies the same
full-bound shuffle, and visits exactly `floor(N/2)` shuffled entries. For each
local selected hostile it cancels the current action unless that action is
already `Action_Badguy_Pause`, consumes `RandomInt(2)`, and on result one
constructs a pause whose constructor consumes `RandomInt(50)` and lasts
`round((50 + draw) / actor_time_scale)` ticks. It always then consumes
`RandomSign(15)` and adds the exact `-15` or `+15` result to heading.
Remote-entry rejection still
uses one of the half-list slots. Earthquake has no damage CFG property and
never enters the normal damage-contact ABI.

When pulse intensity is at least `0.99`, the actor also creates one registered
`Anim_Quake` using BadGuys record `62`: rotation consumes `RandomFloat(360)`,
scale selector consumes `RandomInt(4)` and produces
`(2 + selector, 0.8 * (2 + selector))`, and alpha magnitude is `intensity^3`.
`Anim_Quake::Tick 0x00454200` advances its sine phase by two degrees and scale
by float32 `0.005` per axis. At each `abs(sin(phase)) < 0.01` edge it consumes
`RandomFloat(0.75)`, adds `0.25 + draw` to both scales, and multiplies alpha by
float32 `0.95`. Draw `0x00459350` uses
`min(1, alpha * abs(sin(phase)))`; the child removes at 360 degrees after 180
updates.

Independently on every update, the shuffled scenery cursor advances one entry;
reaching the end resets it to zero and deliberately leaves a blank update. A
selected entry consumes `RandomSign(1)` for its exact `-1` or `+1` multiplier
(forced to one below rotation `-2` and to negative one above `2`) and adds
`RandomFloat(1.5) * multiplier` to its wobble. Enhanced Effects then tests
`RandomInt(30) == 1`. Success creates a BadGuys-`10`
`Anim_FadeSin_Move`: velocity X `(RandomFloat(0.25)+0.25)/3`, magnitude
`RandomFloat(0.5)+0.5`, tint `(30,17,0)`, rotation `RandomFloat(360)`, scale
`RandomFloat(2)+2`, and radial offset `RandomFloat(30)` along a one-word native
random unit vector. Its position advances by velocity, sine phase advances by
`0.5` degrees, alpha is `abs(sin(phase))*magnitude`, and it retires at 180
degrees after 360 updates.

Every update, with or without Enhanced Effects, also tests
`RandomInt(15) == 1` for a `ZAnimLitObject`-wrapped `Anim_BoulderBit`. A
successful birth consumes the native direction, four hidden `Anim_Bouncer`
constructor draws, BadGuys-record selector `2008..2010`, radius, bounce,
height, collision-radius offset, two-stage scale clamp, scale multiplier, and
speed draws in their constructor/caller order. Its bouncer state moves and
accelerates vertically on two of every three global ticks, reflects through
damping `0.3`, may damp planar velocity by `0.65`, spins, and loses alpha by
`0.015` plus subclass loss `0.025` until retirement. Enhanced Effects changes
initial alpha from two to ten and adds the dark `0.75`-scale underlay; the lit
wrapper supplies normal inbound Region lighting and depth ownership.

Draw callback `0x00613E10` renders the Earthquake floor record with alpha
`0.75 * intensity`, actor rotation `+0x160`, and scale `(1.5, 1.2)`. It always
draws one copy, adds a second at `rotation + 170 degrees` when scalar `+0x16C`
is greater than `0.6`, and adds a third at `rotation + 305 degrees` when that
scalar is greater than `3.0`. When green-overlay scalar `+0x168` is positive,
the same one/two/three-copy sequence is redrawn in `(0, 1, 0)` with alpha
`0.75 * intensity * min(+0x168, 1)`. The callback restores both color and
renderer state after the overlay.

### Call Leviathan and Ether Bolt (`0x7F2`, `0x7F3`)

`Leviathan` owns its entire effect. The actor has a `PointerList` at `+0x15C`;
each 0x34-byte appendage record stores base XY, an independent spin angle and
angular delta, deployment, aim heading, authored sprite scale, sprite bank,
depth key, target group/slot identity, recoil XY, and shot countdown. Cast
dispatcher `0x0054CC50` first lets constructor `0x005E8FB0` consume
`Float(360)` for actor rotation. Without `FX_MAXLEVIATHAN`, it then consumes one
integer draw and selects the appendage count uniformly from inclusive
`[1, round(mQuantity)]`. With that bit it skips the selector and uses the
configured maximum. The bit is granted by the complete five-piece
Pandimensional Bug-Master's Outfit; the same set separately applies
`FX_ONESPELLDAMAGE *2 "Call Leviathan"`, so maximum quantity and doubled child
damage are distinct native effects.

Initializer `0x005F4750` has five authored layouts, not a generated radial
distribution. Every appendage consumes exactly five gameplay-RNG words in
this order: base-Y range, `Float(360)` spin, `Float(2,3)` angular delta,
`Integer(2)` bank, and `Integer(100)` shot countdown.

| Chosen quantity | Portal maximum scale | Ordered `(baseX, baseY range, initial heading, sprite scale)` records |
| ---: | ---: | --- |
| 1 | `0.75` | `(0, -Float(20,40), 10, 2.1)` |
| 2 | `0.85` | `(-10, -Float(20,40), 10, 2.1)`; `(10, -Float(10,20), 135, 2)` |
| 3 | `0.95` | `(0, -Float(20,40), 10, 2.1)`; `(15, -Float(10,20), 135, 2)`; `(-15, -Float(10,20), 225, 2)` |
| 4 | `1` | `(-10, -Float(20,40), 10, 2.1)`; `(10, -Float(20,50), 10, 2)`; `(18, -Float(10,20), 135, 2)`; `(-18, -Float(10,20), 225, 2)` |
| 5 | `1` | `(0, -Float(40,50), 10, 2.25)`; `(-18, -Float(20,40), 10, 2.1)`; `(18, -Float(20,50), 10, 2)`; `(18, -Float(10,20), 135, 2)`; `(-18, -Float(10,20), 225, 2)` |

The parent starts at scale zero. Repeated stored-float32 `+0.025` leaves update
40 at `0.9999995827674866`; update 41 clamps to one, changes state, and also
executes active update one. Active ages `41..1640` are exactly 1,600 updates.
Age 1640 decrements the active counter to zero and the independent scale-out
branch immediately stores its first `-0.04`; age 1664 reaches zero and removes
the owner. Thus scale-in and active overlap on age 41, active and scale-out
overlap on age 1640, and the union is 1,664 live tick invocations.

On every active update and for every appendage, spin advances by its stored
delta, recoil XY recurs by float32 `*0.8999999761581421`, aim heading adds
`0.20000000298023224 + Float(5.800000190734863)`, and deployment either recurs
by float32 `*0.949999988079071` while the parent's pre-decrement remaining count
is greater than 15 or adds float32 `0.07000000029802322` for the final 15
active updates. The depth key is `round(nativeHeadingVector(heading).y*100)`.
Acquisition/firing is enabled only while deployment is strictly below
`0.05000000074505806`; from initial one, the first qualifying deployment is
active update 59.

An unset appendage asks `0x00641500` for the nearest visible hostile in a
50-degree lane of range 300. Acquiring writes only the target identity; heading
and countdown work begin on the next update. A retained identity is resolved
every update. A lost/dead identity is cleared without same-update reacquisition.
For a live target, heading is recomputed with native `atan2`, the countdown is
decremented, and a value below one fires. The reset is `75 + Integer(26)`.
After firing, a separate `Integer(2)` toggles the 0/1 sprite bank only when its
result equals one, and recoil becomes `nativeHeadingVector(heading)*10`.

The local appendage root is
`(baseX + recoilX + 2*spinUnitX,
  baseY + recoilY + 4*spinUnitY + 35 + deployment*100)`.
Presentation chooses 15-direction frame
`wrap15((round(heading)+12)/24)`, record
`BadGuys[343 + bank*15 + frame]`, sprite wobble
`sin(headingDegrees)*5 degrees`, and the authored scale above. The 30 atlas
records' first `extras` points are the native muzzle sockets; the shot position
is that socket transformed by the same scale/wobble matrix. Appendages are
depth-sorted by their stored key. The record-39 portal is drawn once normally
and once again at half alpha in the additive pass.

Each shot also registers an Ether `Anim_FadeMM` at the muzzle with scale `1.5`,
initial fade scalar one, and float32 decrement `0.05`, yielding 19 drawable
states. Enhanced Effects additionally consumes five RNG words on every parent
tick and emits one additive-perspective `BadGuys[11]` mote: random heading,
`parentScale*20` radial birth, `-Float(5)` Y jitter, uniform scale
`0.5+Float(0.5)`, velocity `Float(3)` along the heading, velocity damping
`0.95`, and fade decrement `0.1*(2+Float(0.15))`. The live actor renews
`PlaneCross__Loop`; cast creation owns `LeviathanRoar__Stream`.

`EtherBolt` constructor `0x005E2950` seeds a 100-count and alpha one. Tick
`0x006034F0` always adds velocity before decrementing the count. When the count
reaches zero on update 100, it starts stored-float32 subtraction of
`0.009999999776482582`. The 100th fade subtraction remains slightly positive;
the 101st crosses zero and removes the bolt. Point/radius-10 hostile collision
through `0x00641220` still runs on every fade update and there is no terrain
test. Contact registers the same 19-drawable-state Ether FadeMM at scale two,
wraps it in `ZAnimLit` with radius `0.75`, initial intensity one, delta `-0.05`,
and painter bias 100, dispatches `+0x14C` damage only for the authoritative
owner group, then removes the bolt. Draw `0x005E29A0` is additive
`BadGuys[22]`, not record 11, at actor-local `(0,-25)`, with stored heading and
a fresh `0.5+Float(0.5)` opacity sample each render frame.

### Plane Orb (`0x7EF`)

Planewalker's forced primary is a separate persistent actor, not a recolored
Magic Missile. Inline creator `0x0052D8C0` writes damage
`2 * progression[+0x8D0] / game_timing_scale`; `+0x8D0` is the sum of effective
Ether line ranks `8,10,9,13,14,15,12`. Initializer `0x005E2230` writes velocity
`aim * 1.75`, lifetime `1000`, visual scale `0.5`, and acceleration scalar `1`.
Constructor `0x005E2180` consumes one native float draw for maximum scale
`1 + RandomFloat(0,1.5)`.

`0x005FB460` advances position by `(acceleration+1)*velocity` before its
countdown branch on every update, including fade. Starting from countdown
`1000`, ages `1..999` grow scale by `0.01` to its random maximum and recur
acceleration by float32 `*0.980000019`; age `1000` enters the terminal branch
and shrinks scale by `0.02` until removal. Every sixth active authoritative
update a hostile query centered at
`(x,y-15)` with radius `2*scale` applies `stored_damage * 5` to every returned
target; this five-payload pulse after a six-tick counter is intentional stock
behavior. There is no terrain segment or placement collision.

Draw `0x005E8720` rotates the additive `BadGuys[75]` core by
`(global_tick % 360) * 1.5` degrees and scales it
`(-0.75*scale,0.6*scale)`. Slot-`+0x24` pass `0x00601910` is a separate
source-over textured mesh, not a second sprite. Bootstrap `0x005BBD90` proves
that `DAT_00B3BC0C` is the exact 128 by 128 loose asset
`images/etherplane.png` (SHA-256
`cd9aee555fecde2d4917e1776f6bff927c8957e813659dcf163798a2c9e398fb`).
The mesh starts with a center vertex and adds inner/outer pairs at radii
`25*scale` and `50*scale`, with Y multiplied by `0.8`. It has `N=7` angular
segments normally and `N=15` with Enhanced Effects, `1+2*N` vertices, and
exactly `3*N` triangles: one center-fan triangle and two annulus triangles per
segment including the closing sector. Heading starts at `global_tick % 360`
and advances by `360/N`. Every vertex samples the repeat-wrapped texture at
`world_xy / 192`, from the instruction-proved `/3 * 1/64` UV path.

Enhanced Effects also emits one `BadGuys[11]`
`Anim_FadeMoveAdditive_Perspective` after each active-branch parent update. It
consumes five RNG words in order: `Float(360)` heading, `Float(5)` upward
jitter, `Float(0.5,1)` scale, `Float(3)` speed, and `Float(0.15,0.3)` life-loss
factor. Initial position is the updated parent point plus
`20*updated_scale*unit(heading)`, then Y subtracts `15+Float(5)`; color is
`(1,0.5,1,1)`. Life starts at one and loses
`0.1*Float(0.15,0.3)` per tick; velocity recurs by float32 `*0.95` and the
perspective draw multiplies Y scale by `0.8`. Children remain independently
registered after parent fade/removal.

Creation also calls `0x0052D360(position,100,true,true)`. Its nine headings
`0,40,...,320` each create one `BadGuys[11]` and two `BadGuys[45]` perspective
particles: 27 children and exactly 180 RNG words. The record-11 child consumes
six words: radius, the magnitude and sign words for signed ten-degree jitter,
scale, inward speed, and life loss. Each record-45 child consumes seven,
adding its randomized green channel.
All move inward, damp velocity by `0.95`, and use the same perspective
lifecycle. Together with the PlaneOrb constructor's maximum-scale draw, a cast
consumes 181 RNG words before any enhanced update. The creator then requests
`distortreality` at Region point gain and `lightningstart` at exact pitch
`2.0` with the same gain (`0x0052D9B1..0x0052DA1F`). Finally
`0x0052DA24` writes Region alpha `0.1`; Planewalker's retained magenta Region
color makes this a low-alpha unattenuated magenta flash.

### Ether Blast and Ether Burn (`0x1B74`)

The charge state belongs to the wizard, not to each Missile. At
`0x0054B866..0x0054BA19`, `PlayerWizard::Tick` adds float32 `0.007` while the
wizard is idle from its firing state, Magic Missile is selected, its full
cached cost is affordable, the charge cap is nonzero, and plane flag `0x10` is
clear. It clamps to the cached cap and the Planewalker branch forcibly resets
it. At the head of `0x0053CFE0`, a positive round-to-nearest-even charge count
is consumed before the ordinary Missile creation. The pulse is centered 200
units down the cast heading with radius 350, flashes by `0.1` per charge, and
attaches one `Mod_EtherBurn` to each returned hostile target.

The modifier value is `min(charges*0.15,0.95) * target_max_hp`, with `0.001`
used for a nonpositive result, and lifetime is 300 ticks. Merge
`0x00627690` retains maximum remaining lifetime and maximum reduction. Apply
callback `0x00623950` invalidates the target's derived-health cache; the target
modifier lane therefore owns the temporary maximum-health reduction and
restores the maximum when the modifier expires without synthesizing healing.
Tick `0x00629CD0` emits one additive `Anim_FadeAdditive` per tick, selecting
`BadGuys[246 + (global_tick/6)%5]`, anchored at `(target.x,target.y-15)` with
target-scale-aware random size and modifier fade alpha.

### Raise Golem and Iron Golem (`0x7F4`)

`Golem` is a summoned actor rather than a one-frame cast effect. Secondary
dispatcher `0x0054CC50` does not use the cursor. It consumes
`RandomSign(45)`, adds the exact `-45` or `+45` result to the caster's current
heading, and builds an unadjusted point 100 units away on that heading. It
recomputes and commits caster facing from that pre-adjustment vector, then
passes the point to collision resolver `0x00645910` with radius `25`, scenery
mask `0x205`, and actor exclusion `0`. Because `0x205` omits flag `0x400`,
summon placement ignores live actor bodies.

The collision resolver returns the requested point when clear. Otherwise it
starts `searchRadius=25` and `expansionMultiplier=1`. Each ring computes
`count = round-even(pi * (searchRadius + 25) / searchRadius)`, stores
`step=float32(360/count)`, consumes `RandomFloat(360)` for phase, and tests the
float32 ellipse
`point + (sin(heading)*searchRadius, -cos(heading)*searchRadius*0.8)` while the
float32 heading accumulator remains below 360. A failed ring performs
`searchRadius += expansionMultiplier*25`, then consumes `RandomFloat(1)` and
sets `expansionMultiplier *= 1+draw`. This is shared resolver behavior, not a
fixed six-heading or circular search. The Golem is created at the returned
point with initial body heading `casterFacing+180`, copies caster ownership,
and then its constructor consumes `RandomInt(2)` for limb selector `+0x1E4`.
It writes:

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

The summon has a separate, persistent articulation state rather than deriving
its pose from one animation frame:

| Field | Native use |
| ---: | --- |
| `+0x1D8` | action byte: `0` locomotion, `1` attack, `2` provoke |
| `+0x1DC` | temporary facing offset used by the attack wind-up/recovery |
| `+0x1E0` | attack tick |
| `+0x1E4` | alternating attacking-limb selector |
| `+0x1E8/+0x1EC` | left/right limb modes `0..3` |
| `+0x1F8` | post-impact turn lock |
| `+0x1FC` | attack end tick, seeded as `90 - RandomInt(20)` |
| `+0x200` | idle-provoke random bound; `0`, then `1200`, and `75` after an attack |
| `+0x204` | provoke countdown, seeded to `100` and retained through `-50` |
| `+0x208` | assembly/active age |
| `+0x218` | target-search countdown |
| `+0x220/+0x224` | independently randomized limb rotations in `[0,8)` |
| `+0x228` | owned list of sortable 0x1C-byte draw-part records |

Assembly advances `+0x208` by two per tick through age 200 and emits its
owned impact/debris presentation at ages `0, 50, 100, 200`; active ticks then
advance it by one. During attack, the selected limb uses mode 1 through tick
37. Tick 37 creates the 90-degree, range-50, impulse-120 Knockback actor; the
recovery changes the selected limb to mode 2 and the other limb to mode 1.
The facing offset is `+/-38` degrees before tick 25, zero through impact, and
the opposite `-/+47` degrees during recovery. The provoke branch reaches its
effect at countdown zero, then holds both limbs in mode 3 during the negative
countdown tail before returning to locomotion.

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

The draw path is now closed down to its authored geometry and bank switches:

- while age is below 200 it draws one textured assembly quad with local
  vertices `(-35,-200), (35,-200), (-40,25), (40,25)` and green-white-green
  color `(0.5,1,0.5)`; alpha is
  `sin(((200-age)/200) * pi) * 0.5`; the runtime `pi` global is initialized
  from static float `0x007DE8A8`, so the pulse is zero at both assembly ends
  and peaks at age 100;
- the body elevation is exactly `0` below age 100, `-20` for ages 100..199,
  and `-40` from age 200 onward;
- heading is normalized, native-rounded, then quantized with
  `(heading + 9) / 22` into sixteen directional records; a second index is
  calculated from heading plus 180 degrees;
- the four always-present chassis banks are `113..128`, `129..144`,
  `145..160`, and `161..176`. At age 100 the draw list adds the procedural
  center element, the two limb banks `1..16` and `33..48`, and five pieces
  from bank `65..80`, with the last two using the opposite-facing index;
- limb modes above one switch the limbs to banks `17..32` and `49..64`.
  Limb mode one instead keeps the base bank and forces rotations `+45` and
  `-45` degrees; the ordinary modes use `+0x220/+0x224`;
- the exact common sprite scale is `1.1109999418258667`. One central piece
  uses scale `0.8`; the remaining authored forward/lateral offsets use
  `-20, -15, -12, -5, 1, 8, 10, 12, 15, 30, 38, 50, 70` as recovered from
  the draw branch;
- Iron sets the base RGB scalar to `0.35` (`0x595959` at 8-bit precision).
  Chassis modes 2 and 3 then draw untinted overlay banks `177..192` and
  `193..208` over the two side pieces;
- the 0x1C-byte part records are sorted by their stored Y coordinate through
  `0x00428A60` before `Text_Draw`, so the web renderer must preserve
  per-part painter order rather than draw bank order.

Age 200 also enables a connector pass before the sorted body list. It uses
directional Golem banks `97..112` at the two articulated endpoints, two
quarter-point BadGuys-15 green joints between them, and half-scale Golem bank
`65..80` endpoint caps. The endpoint-Y comparison reverses the endpoint draw
order so this internal articulation preserves native depth. After the sorted
front chassis record, its mode-one branch temporarily enables additive blend
and draws directional Golem bank `81..96` at the same point with a per-frame
green scalar `0.5 + RandomFloat(0.3)`. These banks are real parts of the active
Golem painter, not unused rows in the atlas.

The null-sprite record in that sorted list is not an untextured placeholder.
Its branch binds `DAT_00819978 + 0xBB4`, which the BadGuys atlas registry maps
to exact record `15`, and draws the record twice at the center: scale
`2 + RandomFloat(0.25)` at center Y and scale
`1.5 + RandomFloat(0.25)` at center Y plus 5. Both copies use RGB
`(0.5 + RandomFloat(0.3), 1, 0.5)` and participate at the null record's sorted
Y position. Those draws are presentation-owned and must not consume the
authoritative simulation RNG on a client.

Death method `0x00619730` constructs 30 `DeadHawg 78..87` bouncers and one
short `BadGuys 86` additive star. Its construction consumes exactly 273 RNG
draws: 30 full-range shuffle draws, seven parameters for each rock, and three
star parameters. The runtime RNG advances immediately while presentation
retains the pre-consumption state so those world-owned children can replay the
same trajectories. The associated cue order is stone break, Flame Lash start,
Golem die, then rock hit.

### Ether Drain (`0x807`)

`EtherDrain` has nominal 40-tick scale-in, 1,000-tick active, and 20-tick
scale-out states in byte `+0x148`. The scale is stored as float32 after every
addition: 40 additions of the encoded `0.025` produce
`0.9999995827674866`, so the `scale >= 1` transition actually occurs on update
41. Constructor `0x005F8360` computes the active countdown as
`float32(0x00820230) * double(0x007DE810) = 100 * 10 = 1,000`, rounds it through
`0x00747360`, and stores the result at `+0x144`. It initializes presentation scale `+0x140`
and secondary intensity `+0x14C` to zero, seeds rotation from
`RandomFloat(0,360)`, and clears the capture pulse at `+0x19C`. Tick
`0x0061CF20` grows scale by `0.025` to one, grows intensity by `0.005` during
scale-in and `0.01` while active, then fades both by `0.05` after the active
countdown expires. At the end of each tick rotation advances by twice the
post-update scale. It owns two `Array<PuppetRef>` collections plus pointer
lists for spatial cells and presentation children.

Candidate refresh `0x00606580` is driven by countdown `+0x180`, which starts
at zero. Scale-in subtracts five before the common one-count decrement, active
subtracts only the common one, and scale-out subtracts ten before the common
one. Consequently the actor refreshes on ages `1`, `18`, and `35`, next on age
`105`, and then every 100 ticks through age `1005`; scale-out refreshes are
harmless because pressure is already gated off. Its broad cell collection is
the strict ellipse `dx^2 + (dy / float32(0.8))^2 < 1,048,576`, so its
horizontal and vertical semi-axes are 1,024 and 819.2. The retained candidates
are then filtered by the actual pressure radius in `0x005F8620`:

- actors at squared distance at most `262,144` (radius 512) are pulled toward
  the center through their virtual force callback. The radial strength is
  `intensity * 1.1 * max(0.1, 1 - distanceSquared / 262144)` along the
  normalized inward vector. Flag-`0x400` objects multiply by that falloff a
  second time. Actors at squared distance strictly below `400` (radius 20)
  receive contact damage using the configured `mDamage / 100` scalar at
  `+0x150` and flags `0x10A`. The scalar doubles below squared distance `225`
  (radius 15), doubles again below `100` (radius 10), and doubles once more for
  target flag bit `0x1`. Each dispatched hostile contact then consumes
  `RandomFloat(0.5)` for the native contact lane at `+0x18`;
- objects with actor flag `0x400` are also pulled inward. This includes ground
  loot; a captured object is removed at the center and routed through the
  world-item consumption effect. Nonempty `Gold (0x7DC)` and `Sack (0x7DD)`
  containers are explicitly exempted from premature removal.

The target arrays retain group/slot identities rather than raw actor pointers.
Gameplay pressure/contact is gated by the post-transition state and
`+0x144 > 50`, so it runs for ages `41..990` inclusive (950 ticks) and is
disabled for the final 50 active-countdown ticks and scale-out. Child creation
is inside the state-at-entry active branch and therefore runs for ages
`42..990` inclusive (949 ticks). It draws `Integer(5)` normally or `Integer(3)`
with enhanced effects; only result one creates `Anim_SuckCloud`. That spawned
branch consumes eight gameplay RNG words including the gate: constructor
`Float(1.5), Float(360), Float(0.15), Float(3), Integer(2)`, then radial
`Float(100)` and a unit heading. The selected BadGuys record is `10` or `11`.
It starts at that radial offset, flies toward the parent's snapshotted center
at half its constructor speed, advances a sine-fade phase toward 180 degrees,
and retires without a parent callback.

An independent `Integer(50)==1` branch creates free-floating
`Anim_SuckDebris` using DeadHawg records `177..179`. A successful spawn consumes
five words including the gate: two constructor `Float(360)` values, a unit
heading, and `Integer(3)` for the record. It starts 1,024 units from the parent,
moves inward as remaining distance falls by a speed beginning at one and
growing by `0.05`, and consumes `Float(17), Integer(100), Float(5)` every child
tick. Gate result three halves the speed. Its two rotations add respectively
`3+Float(17)` and `3+Float(5)`, and its perpendicular draw oscillation is
`sin(firstRotation)*remainingDistance/7`. Completion calls `0x005EE840` with
`0.5`: this writes capture pulse two but does not create a flare.

Draw `0x005EE120` composes the parent from four additive `BadGuys[75]` galaxy
layers. Given scale `s`, intensity `i`, and rotation `r`, they are:

| Layer | Tint | Y | Scale | Rotation | Alpha |
| ---: | ---: | ---: | --- | --- | --- |
| 1 | `0xFF80FF` | `0` | `(-0.8*s, 0.64*s)` | `1.5*r` | `1` |
| 2 | white | `-5` | `(-1.5, 1.2)` | `0.5*r` | `0.5*i` |
| 3 | white | `-10` | `(-2.5, 2)` | `0.25*r` | `0.25*i` |
| 4 | white | `-20` | `(-4.5, 3.6)` | `0.125*r` | `0.1*i` |

Every draw also emits source-over `BadGuys[38]` tinted `0xFF4080` at scale
`s*0.25*(0.980000019 + RandomFloat(0,0.06999993))`. A positive capture pulse
at `+0x19C` adds a second source-over, white `BadGuys[38]` layer whose alpha is
the pulse and whose scale is `pulse*s`. The pulse decrements by `0.1` per
parent tick. Callback `0x005EE840` always writes pulse `2`; a callback parameter
at least one also creates additive `BadGuys[36]`. Direct center capture calls
it with `1`, before the same-tick pulse decrement, so its first visible pulse
is `1.9` and its flare starts at scale/alpha `1`. `Anim_Sucked` destruction
calls it with `1.5`, producing the scale/alpha-`1.5` flare at the parent Y
offset. Free-floating `SuckDebris` calls it with `0.5` after the parent tick,
so its first visible pulse is `2` and it creates no flare. `SuckCloud` has no
callback. Every flare fades by `0.05` per tick.

Point-light callback `0x005EE780` places a radius-2 light at the actor root
with intensity `min(s,1)*(0.5 + RandomFloat(0,0.5))`; the native
`Game.MultipleShadows` flag controls its shadow branch. These two random draws
are presentation cadence, not gameplay RNG. A deterministic web presentation
frame may sample the same ranges without advancing authority RNG.

The live parent renews `PlaneCross__Loop`. The stock binary also carries the
dedicated `sounds\crunchdrain` registry key for this effect, but no recovered
creation/tick callsite plays it. A `crunchdrain` birth one-shot therefore
remains an explicit bounded inference and must not be emitted as confirmed
parity audio.

The deleting destructor `0x005FB980` delegates to `0x005F84F0`, which owns the
array/list cleanup; presentation children remain registered with the world.

### Call Comet (`0x80C`)

`Comet` stores configured damage at `+0x140`, freeze duration at `+0x13C`, and
its fall countdown at `+0x14C`; this corrects the earlier swapped field labels.
Construction consumes `Float(1)` for heading. Each of the 400 updates in
`0x006220D0` consumes `Float(0.5), Float(360), Integer(2), Float(0.5)` and
registers a BadGuys-51 trail. The trail uses scale `2.5`, life
`0.5*(0.5+draw)` with `0.025` decay, and multiplies rotation by `0.99` or
`1.015`. The warning edge occurs when the post-update counter first falls below
175, leaving 174 ticks. At zero, `0x0061E9C0` creates the large burst/debris
presentation, invokes the same FreezeWave creation helper used by Ring of Ice
with the comet freeze field, queries the 400-unit impact area, and dispatches
damage through contact field `0x0081C6E8`. It finally restores world color and
removes itself. Fall painter `0x005F0DB0` submits radius-2 light at constant
intensity `0.5`.

Impact `0x0061E9C0` registers additive perspective `BadGuys[15]` at scale 10,
gray `0.75`, life 5 and decay `0.01`, plus normal `DeadHawg[6]` at scale 2,
life 10 and decay `0.01`. It next consumes one initial `Float(360)` and fills a
radial ring with independent `Anim_Bouncer` records selected by `RandomInt(5)`
from DeadHawg 203..207. Each bouncer consumes four constructor draws (vertical
velocity `-(2+Float(3))`, height `-Float(20)`, rotation `Float(360)`, rotation
speed `1+Float(10)`), then record selection, signed `Float(0.25)+0.8` scale,
`Float(10)+80` radial offset, `Float(2.5)+0.5` horizontal-speed factor, signed
`Float(1)+1` life factor, and signed `Float(3)+8` angular increment. X velocity
alone is multiplied by `1.5`.

`Anim_Bouncer` tick/draw `0x00456720/0x00456A60` returns before translation,
rotation, and life decay on global ticks divisible by three while height is
nonzero; otherwise it integrates horizontal motion and height with gravity
`0.4`. Ground contact consumes a fresh `Float(10)` rotation speed
and `Integer(2)` damping gate, applies bounce and optional horizontal damping
`0.65`, and settles when bounce velocity exceeds `-0.75`. Rotation advances
and life loses `0.015` on each non-skipped airborne update and every settled
update. These debris actors and impact fades are
world-owned after the Comet retires; DeadHawg-6 can persist for 1,000 ticks.
The deleting destructor uses ordinary `Puppet` teardown.

## Enemy-owned projectile presentation closure

The five projectile classes reachable from the Boneyard enemy graph use the
same fixed-tick actor lifetime described above, but their visible submission
is not interchangeable. The following reconstruction joins each constructor,
tick, draw, contact, and animation-wrapper handoff. Values called “random” are
drawn from the native shared stream; a deterministic network renderer may
project entity identity into the same finite domain, but must not claim the
retail RNG sequence.

### Arrow `0x7DA`

`Arrow_Draw 0x0060F590` always submits BadGuys record `2` as the shaft and
rotates it by the projectile heading at `+0x170`. Element state adds a separate
overlay instead of selecting a directional arrow bank:

- fire uses `255 + ((globalTick / 5) % 12)`;
- poison uses `271 + ((actorAge / 6) % 12)`, green-tinted and additive; and
- normal has no elemental overlay.

The overlay is planted at `(x, y + height)`, rotated by heading plus 180
degrees, and uses the native randomized scale domain. `0x005E5EC0` is the
Arrow's force-response slot, not a periodic trail callback: it accumulates the
incoming scalar at `+0x178` and, only after the total exceeds one, removes the
Arrow and hands record 2 to an `Anim_SpinAway` child with randomized
rotation/scale. Ordinary flight therefore has no record-2 trail actor. Fire
contact separately reaches `0x005E5D30` and creates the `251..254`
`Anim_FireBurst`; normal and poison contact do not invent that fire burst.
Thus `255..266` and `271..282` are elemental overlays, not twelve arrow
facings, and `Anim_SpinAway` must not be emitted on a timer.

### Firebolt `0x7EB`

Constructor `0x005E1D00` initializes a 400-tick lifetime. Tick
`0x00600880` increments and wraps the 12-step phase at `+0x148`; on each even
global fixed tick it calls trail creator `0x006125B0`. Draw `0x00612760`
uses alpha `min(remainingLifetime/100,1)`, so the projectile is fully opaque
at birth and fades only through its final 100 ticks. It draws the inline
BadGuys record-15 orange glow at scale 2 and submits
`BadGuys[255 + phase]` additively at local Y `-15`, rotated by heading plus
180 degrees, with a per-draw scale in `[1,1.5)`.

The even-tick trail creator takes the current `+0x148` phase, hence the same
`255..266` record as the parent on that tick. It creates a source-over
`Anim_Fade` at `(x,y-15)` plus a random radial displacement of magnitude
`[0,5)`, rotation `heading+180`, paired scale in `[0.75,1)`, alpha one, and
per-tick alpha loss `0.1 * [1.5,2)`, or `[0.15,0.2)`. Visible trail ages are
therefore `0..5` or `0..6`; there is no twelve-tick red/additive child.

Impact `0x005E7C20` creates `Anim_FireBurst` over records `251..254` at
`(x,y-1)`, then removes the projectile. Shared tick `0x00457540` advances the
four-frame selector by `0.25` and specialized tick `0x004575B0` moves it up
one unit/tick, so visible ages are exactly `0..15` and every record lasts four
ticks. Draw `0x0045E2D0` first submits record 110 source-over at five times
the burst scale, orange and fading as `0.5*(1-age/16)`, then submits the
current `251..254` frame additively under tint `(1,1,0.75)`. Its `ZAnimLit`
wrapper starts radius `1.5`, intensity `1`, intensity delta `-0.04`, depth
bias `50`, and Multiple Shadows false. Records `251..254` are therefore never
Firebolt flight frames.

### GuidedMissile `0x7EC`

Constructor `0x005E7E00` writes zero to active selector `+0x180`. Draw
`0x00612960` uses `min(remainingLifetime/100,1)`, so it too fades out only at
the end of its lifetime. Mage launch multiplies the constructor's 2000-tick
clock by `0.2`, yielding the exact 400-tick hostile lifetime. Tick
`0x00600B40` advances phase `p` at `6*speed`, reduces speed by `0.075` to the
constructor minimum `0.75 + RandomFloat(0.45)`, and begins at speed `3`.

The draw translates to local Y `-15` and keeps both submissions additive. It
draws selected main record `110 + selector` with white alpha `[0.5,1)` and
scale
`1.1 + abs(sin(p*15 degrees))*0.15*visualScale`, where constructor
`visualScale` is `[0.9,1.1)`. Cold retains selector zero and color
`(0.25,0.5,1,1)`; Mage poison helper `0x00473330` changes selector to one and
color to `(0.25,1,0.25,1)`. The sibling is always record `112`, with alpha
`abs(sin(p*6 degrees))*0.55`, rotation `p*0.5`, and scale
`[1,1.3)*visualScale`. Neither layer rotates to projectile heading, and the
main selector never cycles by age.
Impact `0x005F3EE0` transfers those fields into `Anim_FadeGM`, whose draw
`0x0045DC90` draws the selected main twice and adds records `111` and `112`.
The wrapper starts at scale and alpha two; common tick `0x00454000` subtracts
`0.1` alpha per tick, giving twenty visible states. Its one-time phase is
`RandomFloat(360)`; main scale uses the same 15-degree wave, while records 111
and 112 use three- and six-degree waves respectively.

### DemonBomb `0x7F7`

Constructor `0x005E2F00` chooses a lifetime in the inclusive 100..200-tick
settled domain and initializes vertical offset `+0x150` to `-35`, vertical
velocity `+0x154` to zero, and bounce velocity `+0x158` to `-3`. Demon event
`0x0049A270` launches it straight along the actor heading at speed `[2,3)`;
it is not homing. Tick `0x00603CA0` multiplies horizontal speed by `0.995`,
adds gravity `+0.1` to the vertical velocity, bounces with multiplier `0.85`,
and only decrements the 100..200 counter after horizontal speed falls below
one (or contact settles it). Draw `0x0061A690`
samples `RandomInt(4)` three times and submits three BadGuys layers from
`267..270` at the projectile plus the vertical offset; the latter two use
additive composition, with exact scales `2`, `2`, and `1.5` and no sprite
rotation. The same draw selects the secondary DeadHawg
`46 + ((globalTick / 2) % 32)` pass at local Y `-20`, scale `(1,0.5)`, only
while horizontal speed is at most two. Its alpha is one at speed at most one
and `1-speed*0.5` between one and two.
Auxiliary `0x005E9970` supplies the ground submission. Terminal tick creates
two independently owned Fire `0x7E3` gameplay/presentation actors: one at
`(x,y-10)` and one at `(x +/- [10,20),y+5)`. Each receives the Bomb damage,
starts on a random record in DeadHawg `46..77`, advances by `0.25` frame per
tick, and receives lifetime field five, which the Fire tick consumes at
`0.01/tick` for 500 ticks. This is not a synthetic 32-tick
`demon-bomb-impact` animation. It is a layered ballistic compositor followed
by two persistent Fire actors, not one homing, rotating four-frame sprite.

### PoisonPool `0x806`

Disassembly of `0x005EDFA0` proves the draw receiver is the DeadHawg singleton
record-zero slot (`singleton +0x38`), so both visible passes use **DeadHawg
record 0**. Raw constructor instructions `0x005E3B09..0x005E3B43` leave the
initial `FLD1` value on the x87 stack while converting
`tickRate(100)*30` to the integer damage clock. They therefore initialize
alpha `a=1`, scale `s=1`, and an exact 3000-tick damage lifetime; neither
start value is randomized. Tick `0x005F8030` applies:

```text
s = min(s + 0.025, 1.6)
if damage_lifetime_expired:
    a = a - 0.005
    remove when a <= 0
```

The draw submits:

```text
outer: alpha = 0.5*a, scale = s
inner: alpha = (sin(age degrees)*0.25 + 0.75)*a
       scale = max(s - 0.6, 0)*s*0.75
```

While sufficiently opaque, the tick has a one-in-twenty particle branch.
The damage/contact lifetime and the visual fade are consequently separate:
removing the pool at the damage expiry edge truncates native presentation.

### Network-port ownership consequence

Live projectile state and transient trail/impact state must be replicated as
different lifetimes. A client cannot infer an impact from disappearance,
because expiry, terrain contact, actor contact, and late subscription all
produce the same missing-parent observation. Additive blend belongs to the
individual native layer, and DeadHawg record 0 must be resident even though
the neighboring persistent Fire class uses records `46..77`.

## Closure result for this subsystem

The static object identities, full vtables, construction chains, direct and
caller-selected art, factory/modifier arguments, cast-time payloads,
update/render/contact roots, and destructor ownership are mapped. The isolated
runtime pass additionally confirmed world actor materialization and the
resident gameplay-atlas lifetime; see
[native-live-validation.md](native-live-validation.md).

The attempted optional player-cast sample did not produce a cast because that
resumed scene had no selected spell pointer. No runtime claim is based on that
attempt. Reflection, removal, and persistent-area formulas above instead rest
on their exact native branch and contact-context flows, which are sufficient
to close the native ABI. Future automated spell scenarios would be regression
tests of those recovered contracts, not missing decompilation work.
