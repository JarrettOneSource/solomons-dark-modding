# Native spell-welding system

## Result

Spell welding is implemented as a special level-up choice layered on the
ordinary 0x70-byte skill catalog. It does not concatenate two arbitrary spell
objects. The native game selects one of ten allowed cross-element primary
spell pairs, records a synthetic build ID from 1000 through 1009, and rebuilds
the wizard's active primary-spell stat vector from the learned levels and CFG
properties of six component skill rows.

This document covers the retail `SolomonDark.exe` whose SHA-256 is
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
Names are descriptive unless an exact CFG/property name is quoted.

## Relevant skill object layout

The wizard-specific skills object uses vtable `0x007A0CD4`; the base skills
vtable is `0x0079FEFC`. Important wizard overrides are:

| Slot | Function | Role |
| ---: | ---: | --- |
| `+0x74` | `0x0067CB70` | Build the level-up option set and possibly inject welding. |
| `+0x94` | `0x00665FF0` | Refresh the special weld entry's displayed icon/selector. |
| `+0x98` | `0x00665F10` | Map a skill choice to its displayed Skills-atlas ID. |
| `+0x9C` | `0x006566A0` | Activate the selected weld build. |
| `+0xA0` | `0x00666020` | Resolve component pairs and rebuild active primary stats. |

The skill catalog is created at `0x00674EE0`. It creates 80 entries and loads
`data\\wizardskills\\<resolved-name>.cfg`; entry stride is `0x70`. The name
resolver is `0x00657C00`. The special welding skill is ID `0x34` (52), backed
by `spell_welding.cfg`.

Relevant progression fields are:

| Offset | Meaning | Evidence |
| ---: | --- | --- |
| `+0x20` | pointer to 0x70-byte skill-entry array | Used by all level/prerequisite accesses. |
| `+0x24` | entry count | Bounds check before indexed access. |
| `+0x774` | active primary stat-vector pointer | Cleared/rebuilt by `0x00666020`. |
| `+0x778` | active primary stat-vector count/capacity state | Checked before vector growth. |
| `+0x844` | selected/current synthetic weld build ID | Set by option roll and consumed on activation/render. |
| `+0x870` | one exceptional skill/unlock ID | Used by general eligibility checks. |
| `+0x878` | feature/equipment-effect bit field | Bit `0x800` energizes unlearned weld components; bit `0x1000` biases level-up choices toward welding-related skills. |
| `+0x8E0` | weld-effect scalar | Modified by `FX_WELDEFFECT`. |

The finer names of nearby fields remain subject to the broader progression
layout pass; the offsets and accesses above are confirmed.

## Allowed primary pairs

The base primary skills are:

| Element | Skill ID | Native name |
| --- | ---: | --- |
| Ether | 8 | Magic Missile |
| Fire | 16 | Fireball |
| Air | 24 | Lightning |
| Water | 32 | Frost Jet |
| Earth | 40 | Boulder |

`0x0067CB70` excludes skill `0x34` from its ordinary candidate loops. Once the
weld-specific eligibility gates pass, it builds candidates only for pairs
whose two base primary skills are learned, chooses one randomly, and stores the
synthetic ID at `+0x844`. The ten possible pairs are:

| Build ID | Elements | Base primary IDs |
| ---: | --- | --- |
| 1000 / `0x3E8` | Ether + Fire | 8 + 16 |
| 1001 / `0x3E9` | Ether + Water | 8 + 32 |
| 1002 / `0x3EA` | Ether + Air | 8 + 24 |
| 1003 / `0x3EB` | Fire + Air | 16 + 24 |
| 1004 / `0x3EC` | Water + Air | 32 + 24 |
| 1005 / `0x3ED` | Fire + Water | 16 + 32 |
| 1006 / `0x3EE` | Ether + Earth | 8 + 40 |
| 1007 / `0x3EF` | Fire + Earth | 16 + 40 |
| 1008 / `0x3F0` | Water + Earth | 32 + 40 |
| 1009 / `0x3F1` | Air + Earth | 24 + 40 |

IDs are initialized in native code before filtering, but no same-element pair
is placed in this random candidate set. A flag-controlled path also prevents
the prior/current weld from being offered again.

## Activation and six-component recipes

Selecting the special level-up entry reaches `0x00671470`, which invokes
vtable slot `+0x9C` with the build at `+0x844`, refreshes skills, then invokes
slot `+0x94` to refresh presentation. `0x006566A0` expands the build into six
skill IDs and calls `0x00666020`:

| Build | Primary A | Primary B | Upgrade A1 | Upgrade B1 | Upgrade A2 | Upgrade B2 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1000 | 8 | 16 | 10 | 18 | 9 | 17 |
| 1001 | 8 | 32 | 10 | 34 | 9 | 33 |
| 1002 | 8 | 24 | 10 | 25 | 9 | 26 |
| 1003 | 16 | 24 | 18 | 25 | 17 | 26 |
| 1004 | 32 | 24 | 34 | 25 | 33 | 26 |
| 1005 | 16 | 32 | 18 | 34 | 17 | 33 |
| 1006 | 8 | 40 | 10 | 43 | 9 | 42 |
| 1007 | 16 | 40 | 18 | 43 | 17 | 42 |
| 1008 | 32 | 40 | 34 | 43 | 33 | 42 |
| 1009 | 24 | 40 | 25 | 43 | 26 | 42 |

The apparent floating-point signature produced by the decompiler is wrong for
the component arguments: these are integer skill IDs passed in registers and
stack slots.

## Stat reconstruction

`0x00666020` first maps the selected component pair to a build ID. Mixed pairs
map to 1000..1009. Same-element primaries map to five stock synthetic IDs:

| Build ID | Stock primary |
| ---: | --- |
| `0x3F2` | Ether |
| `0x3F3` | Fire |
| `0x3F4` | Water |
| `0x3F5` | Air |
| `0x3F6` | Earth |

It then clears/rebuilds the vector at `+0x774/+0x778`. For each build case it
queries named properties from component skill configs through `0x005290F0`.
Confirmed property names include:

```text
mDamage        mManaCost      mQuantity       mSpeed
mArcs          mStunAmount    mPushback       mWiden
mStrength      mSpeedUp
```

The mixed cases combine the two primaries and their learned upgrade rows into
one normalized primary-spell description. The stock cases use the same output
path, which is why the cast system can consume a welded and unwelded primary
through one active-stat interface. Global balance constants are applied during
normalization, so the live vector is derived state, not a byte-for-byte copy of
CFG values.

The vector ABI is now closed. The fields consumed by the ten mixed handlers
are:

| Build | Exact vector order |
| ---: | --- |
| 1000 | damage minimum, damage maximum, mana, quantity, speed factor, explosion damage, explosion radius, Ember damage, Ember fragments |
| 1001 | damage minimum, damage maximum, mana, quantity, speed factor, push scalar, widen scalar |
| 1002 | damage minimum, damage maximum, mana, quantity, speed factor, arc count, movement factor after Stun |
| 1003 | damage, mana, arc count, movement factor after Stun, explosion damage, explosion radius, Ember damage, Ember fragments |
| 1004 | damage, mana, arc count, movement factor after Stun, reserved zero, push scalar, widen scalar |
| 1005 | damage, mana, widen scalar, push scalar, explosion damage, explosion radius, Ember damage, Ember fragments |
| 1006 | damage, mana, quantity, speed/lifetime factor, toughness, growth factor |
| 1007 | damage minimum, damage maximum, mana, growth factor, toughness, explosion damage, explosion radius, Ember damage, Ember fragments |
| 1008 | damage, mana, growth factor, toughness, push scalar, widen scalar |
| 1009 | damage, mana, arc count, movement factor after Stun, retained-contact count, rebuilt speed-up value |

The final 1009 value is reconstructed but not read by the compiled
`0x00545FC0` GroundSpark handler. GroundSpark motion is class-owned; it is not
scaled by that vector row. Component levels/config values remain authoritative
and the whole vector is regenerated when the selected build, effective skill
ranks, or Weld Effect scalar changes.

## Cast-time ownership and object membership

The synthetic build is consumed by the same player cast state machine as the
five ordinary primaries. One-shot builds are created from the Staff Cast
marker through `PlayerWizard_OneShotPrimary 0x0054CAF0`; channel and retained
builds are dispatched every active player tick through `0x00548A00`.

| Build | Handler | Native owner(s) | Principal lifecycle entry points |
| ---: | ---: | --- | --- |
| 1000 | `0x0053E6A0` | `FireMissile 0x7DE`, vtable `0x0079D5F4` | ctor `0x005E4C50`; tick `0x005FD550`; draw `0x00608F80`; contact `0x005E4CA0`; light `0x005E4AF0` |
| 1001 | `0x0053F3C0` | `FrostMissile 0x7E0`, vtable `0x0079D6E4` | ctor `0x005E4FB0`; tick `0x005FD7A0`; draw `0x006093B0`; contact `0x005F25B0`; light `0x005E4AF0` |
| 1002 | `0x0053EDB0` | `BallLightning 0x7DF`, vtable `0x0079D66C` | ctor `0x005E4F30`; tick `0x005FD720`; draw `0x005E0670`; contact `0x005F2360`; light `0x005E4AF0` |
| 1003 | `0x005408F0` | `Anim_FlameLash`, `Anim_FadeFlameLash`, chained lightning fades | ctors `0x0045B810` / `0x005292D0`; ticks `0x00453BD0` / `0x00476230`; draws `0x004583E0` / `0x00457370` |
| 1004 | `0x00541870` | `Anim_BlizzardBeam` plus Frost/Lightning chain children | ctor `0x00453BF0`; tick `0x00453CC0`; draw `0x00458470` |
| 1005 | `0x00542D20` | `Anim_SteamJetEffect` and `_Over`; target-owned `Mod_Steamed 0x1B6C` | ctor `0x00453CE0` / `0x00453E80`; tick `0x0045B940`; draw `0x00458550` / `0x00458750` |
| 1006 | `0x00545360` | retained `EBoulder 0x7E1`, vtable `0x0079E08C`, plus recursive EBoulder children | ctor `0x005FA670`; tick `0x00609D30`; draw `0x0060C540`; contact/split `0x00620B60`, `0x0060BED0`, `0x005FA6D0`; light `0x005E5670` |
| 1007 | `0x0052BB60` | channel-owned field plus periodic `Meteor 0x7E2`, vtable `0x0079C9F4` | ctor `0x005E1540`; tick `0x00621590`; impact `0x00610880`; draws `0x005E16C0` / `0x005E6DE0`; provider `0x005E7040` |
| 1008 | `0x00545C20` | retained `Hailstones 0x7E4`, vtable `0x0079E104`, and owned rock records | ctor `0x005FAC20`; tick `0x005FF5D0`; released flight/contact `0x005FBDE0`; draw `0x00611160`; rebuild/release `0x005F3090`, `0x005FAC70`; light `0x005E5670` |
| 1009 | `0x00545FC0` | one center and normally two side `GroundSpark 0x7E5`, vtable `0x0079D84C` | ctor `0x005E76F0`; init `0x005E1A80`; tick `0x00611EB0`; draw dispatch `0x005E1B00`; contact `0x005F34E0`; light `0x005E7800` |

The persistent Earth-derived builds use the caster's group/slot handle at
`+0x27C/+0x27E`. Cast release resolves that identity and invokes the concrete
release/split method; cancellation, death, scene removal, and replacement use
the common cleanup chain. A browser port therefore needs separately replicated
projectile, short-lived presentation, retained actor, released child, target
modifier, and light-provider identities. A single cast timer or element-colored
sprite cannot represent this membership.

## Exact one-shot construction, low-mana, and RNG order

Raw instructions around every `RandomFloat`, `RandomInt`, factory call, and
`Sound::Play(pitch,gain) 0x00407CD0` establish this order. The first floating
argument to `0x00407CD0` is pitch; the second is gain. Earlier notes that called
the low-mana `.75` value attenuation were incorrect.

| Build | Construction and audio RNG before/inside actor creation |
| ---: | --- |
| 1000 | One damage draw for the whole fan when endpoints differ. Per actor: inherited `MagicMissile` `Float(360)` phase, then `Integer(100000)` private fire seed. Both `magicmissile` and `throwfire` play at pitch one/gain one. |
| 1001 | One shared damage draw; `Float(.1)` produces cast pitch `1+draw`; per actor: inherited `Float(360)`, Frost lane rotation `Float(360)`, then lane aspect `.5+Float(.25)`. Registry 38 `frostmissile` plays once. |
| 1002 | One shared damage draw; `Float(.25)` produces both pitch and the fan's initial turn multiplier; `Integer(2)` selects `throwlightning` 1/2; each actor then consumes inherited `Float(360)`. Stored base speed is `3 * vectorSpeed * .8500000238418579`; temporary acceleration starts at two, caps movement speed at six, and multiplies by `.8999999761581421` per tick. |
| 1009 | One shared damage draw; signed `Float(.05)` produces pitch `1+draw`; `Integer(3)` selects Shock 1/2/3. Each actor consumes constructor `Integer(1000000)` for its private motion stream, then initializer `Integer(360)` for native age/visual phase. Center speed begins at four; side speeds begin at three. |

All three Ether-derived missile families spawn at the current Staff emitter plus
local `(0,+10)`. GroundSpark spawns at `(0,+15)`. Fire/Frost/Ball quantity and
heading follow the alternating native fan; GroundSpark uses center and
`-30/+30` headings. Damage is rolled once and copied to every member.

The insufficient-mana path still consumes the normal pre-gate pitch draws and
creates an actor, but changes the payload:

| Build | Native low-mana actor |
| ---: | --- |
| 1000 | one missile; half damage; speed factor `.8`; all explosion/Ember fields zero; cast pitch `.75` |
| 1001 | one missile; half damage; speed factor `.8`; push/widen zero; cast pitch `.75` |
| 1002 | one missile; half damage; speed factor `.8`; arc count zero; movement factor one; turn multiplier `.75`; cast pitch `.75` |
| 1009 | center actor only; half damage; arc count and extra contacts zero; movement factor one; sampled pitch multiplied by `.800000011920929` |

The low-mana `fizzle` is a separate gain-one request before the cast sample.
The created missile's weak byte halves the native body treatment where its draw
tests that byte; it does not suppress the missile light provider.

GroundSpark's movement is private-state driven. On its first tick after moving,
and then whenever its 20-tick counter expires, the stored word runs three
successive `x ^= x<<21; x ^= x>>11; x = (x ^ x<<4) * 0x0A67CFCF`
steps with native signed absolute-value normalization. Word one selects a
`17..37` degree magnitude relative to the original cast heading, word two
selects its sign, and word three selects speed `1..4`. This is not the
process-global render RNG and must survive snapshots.

FrostMissile additionally owns two shrinking compositor lanes. Their scales
subtract `.01`; a lane below `.1` refreshes aspect `.5+Float(.25)`, scale
`.5+Float(.75)`, and rotation `Float(45)` in lane order. These refreshes occur
in actor tick `0x005FD7A0`, not in draw, so a network port must retain the two
lanes and advance the authoritative RNG. Its turn-presentation field decays by
`.949999988079071`, adds the current homing heading delta, and clamps to
`[-35,+35]`. Only per-render samples without actor-state consequences may use
a stable semantic renderer stream.

GroundSpark's actor draw `0x005E1B00` only dispatches its tick-owned animation
list. Every `0x00611EB0` update constructs record 71 at
`y - abs(sin(nativeAge*12deg))*15`, consumes `Float(360)` rotation and signed
`Float(.1)` scale around `.35`, and starts alpha/loss `.75/.1`. Weak state
halves both. A second child is created when the sine magnitude is below `.1`
or `Integer(6)==1`; `Integer(4)` selects 1836..1839, followed by
`Float(360)` and `Float(.25)`. Weak state halves this child's alpha but not its
loss. These animation objects survive projectile retirement.

Steam is not a two-tick beam. Handler `0x00542D20` reaches particle creation on
the even global-update lane, then consumes `Integer(7)`: value one selects
`Anim_SteamJetEffect_Over` unless the cast is weak, otherwise it selects the
normal class. The shared constructor consumes `Float(.05)`, `Float(.1)`,
`Float(.75)`, `Float(1)`, `Float(.1)`, and `Integer(10)`; handler placement then
consumes `Float(10)` and signed `Float(4.5)`. Tick `0x0045B940` owns life/loss,
position/velocity, `.15` phase gain (`.075` Over), `.25` tint loss, `.125`
secondary-color loss, `.95` stretch shrink, `.01` scale growth, and `.96/.88`
velocity decay. Birth starts 15 units behind the Staff emitter. Life loss is
`(Float(.1)+.01)*.5`. Speed is `5.4*(1+widen*.02)` Normal or
`6*(1+widen*.02)` Over; weak forces neutral widen and quarter alpha. A
birth-time caster-to-predicted-end terrain probe stores terminal point and
remaining distance, and tick snaps there when the accumulated velocity length
crosses that distance. Only one normal-or-Over record-76 actor is born per
eligible tick.

Normal non-weak particles alone retain the `Integer(10)` contact clock and the
full Steamed payload. Above life `.5`, clock expiry resets to ten and queries a
scale-derived area before installing `Mod_Steamed`; Over and weak particles do
not own this target-effect lane. The normal draw duplicates record 76 in the
additive pass while tint fade is positive; once it reaches zero one ordinary
pass remains. Over always draws one ordinary quarter-alpha pass.

## Enemy/world effects and status ownership

| Build | Direct/world result | Target-owned or child result |
| ---: | --- | --- |
| 1000 | Missile contact dispatches direct damage and retires; configured fire area helper runs at impact. | Explosion/Ember fields can create the same Fire-family burst, persistent Fire, and Ember children as their native helpers. |
| 1001 | Direct contact installs `Mod_ColdSlow 0x1B69`, then damages. Helper `0x00643920` performs the area pass. | Radius begins at float32 `pushScalar * 120`, then receives fifteen float32 multiplies by `1.024999976158142`; each still-live root in the area receives damage `projectileDamage / 20` and the same 150-tick `.5` ColdSlow. The directly hit root participates again if it survived. |
| 1002 | Direct damage plus `Mod_ElectricBurn 0x1B6B`; missile retires through `Anim_FadeLightning`. | ElectricBurn ticks the source and up to the configured nearest distinct roots inside 200, applies its per-tick damage, and installs 25-tick Stun at the stored movement factor. Stronger merged payload owns arc/stun/source fields; duration and damage retain their maxima. |
| 1003 | Lightning target retention/chaining and direct tick damage with Fire payload globals. | Each admitted root can receive Stun; explosion/Ember branches remain Fire-owned. Chain presentation is separately owned. |
| 1004 | Widened Frost cone plus Lightning chain selection and tick damage. | ColdSlow is installed before Stun; chain members and the cone are not renderer-inferred targets. |
| 1005 | Widened cone and normalized push. | `Anim_SteamJetEffect::Tick 0x0045B940` installs target-owned `Mod_Steamed`; its ten-tick payload repeatedly dispatches fire damage and can run the stored Fire detonation/Ember branch. |
| 1006 | Held EBoulder grows, follows the emitter, and on release creates up to four independently registered rocks with their own residual damage pools. | Contact consumes pool according to toughness without scaling outgoing target damage; recursive split children and BoulderBit/debris presentation are actor-owned. |
| 1007 | Periodic Meteors fall, impact, retain for the native impact clock, and pulse every ten ticks. Direct impact uses the native 45-unit point query and half damage. | The impact transition creates its own debris/fade program and Fire helper payload. Subsequent radial ticks use the impact-created scalar at object `+0x15C`, not the welded vector's toughness slot. |
| 1008 | Held Hailstones rebuilds its rock list at growth buckets; release moves one carrier and keeps distinct local, draw-decay, and collision offsets for every rock. Clear flight advances three ordered ten-unit substeps per tick. Positive widen expands the carrier query radius and every rock's local/collision XY once per substep. | Every accepted rock contact installs 250-tick `.5` `Mod_ColdSlow` before damage. Positive push requests `Mod_Knockback` with the cast unit direction for round-to-even `push * 20` one-unit, collision-aware ticks; the native modifier rejects a second Knockback while one is resident. Each rock owns its residual damage pool. Pool exhaustion retires only that rock and creates one 14-tick `Anim_Line` plus a ten-tick BadGuys-15 fade; surviving siblings remain. |
| 1009 | Each spark performs a 15-unit point query and can survive exactly `retainedContacts+1` accepted contacts. | Every accepted contact installs the GroundSpark form of ElectricBurn (50 ticks) before direct damage and creates FadeLightning presentation. |

Target queries preserve the native world/broadphase registration order. Ties in
ElectricBurn's nearest-root sort preserve returned registration order rather
than sorting by web IDs.

## VFX, painter, audio, and lighting inventory

The direct atlas and procedural presentation membership is:

| Owner | Native visual program |
| --- | --- |
| FireMissile | record 110 core; BadGuys 255..266 body at `(age/3)%12`, normal plus additive passes; per-tick moving fade/ZAnim trail; impact BadGuys 251..254 |
| FrostMissile | BadGuys 271..282 at `(age/4)%12`, scale `1.7`; additive BadGuys 5 and 110 helpers; two shrinking/refreshing BadGuys-16 lanes; a positive `+0x16C` adds two affine BadGuys-87 overlays; `Anim_FadeFrost` impact |
| BallLightning | draw `0x005E0670` applies weak parent alpha, calls `0x00536380` for four BadGuys-110 circles plus two BadGuys-1836..1839 forks, then draws a direct BadGuys-70 sibling at `(x,y-10)`, scale `1.25+Float(.1)` and `Float(1)` alpha; the welded handler leaves constructor byte `+0x168` zero, so the final `0x00535A30` Ether compositor is always present at `1+Float(.5)` scale, phase `+0x154`, and graphics-alpha multiplier `.1`; `Anim_FadeLightning` owns impact |
| GroundSpark | actor draw `0x005E1B00` renders its tick-owned animation list; each tick creates record 71 fade state and the optional BadGuys 1836..1839 fork branch |
| Flame Lash | two-tick textured vertex mesh from `0x004583E0`, using BadGuys record 44; constructor `0x0045B810` calls the same exact `0x0052E020` three-point QuickSpline/ribbon builder as Lightning. Normal width/alpha are `1/1`; weak width is `.75` and color alpha `.5`; phase is `-3*managerTick`. The shared Enhanced branch can append independently selected BadGuys 375/376 geometry and texture. Handler `0x005408F0` also registers endpoint/contact `Anim_FadeFlameLash` roots; draw `0x00457370` uses BadGuys 35 additively. |
| Blizzard Beam | two-tick `0x005308D0` beam path from `0x00458470`; this is not the ordinary Frost Jet particle class. Weld caller `0x00541870` passes source-glow flag one and endpoint/enhanced flag zero, so records 6/31 are unreachable here. The owned extras are exactly two one-frame source `Anim_SpellGlow` variant-24 actors. |
| Steam Jet | one even-lane-selected normal/Over moving actor using BadGuys record 76 through draws `0x00458550/0x00458750`; its constructor/tick state outlives the cast emission that created it |
| EBoulder | BadGuys 86 center/opening plus oriented, depth-sorted rocks 168..171; split children use 2008..2010, and each accepted shared-flight contact creates one independently retained 2008..2010 `Anim_BoulderBit` through `0x0060BC10` |
| Meteor | fall draw `0x005E16C0`; auxiliary `0x005E6DE0` draws DeadHawg 19 during final descent and BadGuys 67 during impact; impact constructor `0x00610880` owns the independent flash/debris; the channel also emits `Anim_Iceblast` at the aimed point |
| Hailstones | held Frost helper plus owned rocks 168..171; Enhanced rock creation emits independent record-18 fades, and release emits independent `Anim_FadeFrost`; held and released rock transforms are distinct. A depleted target-contact rock creates `Anim_Line` plus BadGuys 15. Static-line termination creates, per remaining rock, fifteen additive moving BadGuys-45 children and one BadGuys-32 bouncer. The visibility-residency exit instead creates one `Anim_Line` per remaining rock before carrier retirement. |

The 2026-08-21 shared-contact reopening closes the retained `EBoulder` result
rather than treating its contact BoulderBit as presentation-only. Override
`0x00621450` calls common Boulder flight/contact `0x00620B60`. For every new
target, that method spends the actor-local pool with the ordinary toughness
rule, writes
`scale = releaseScale * (1 - (1 - remaining/baseDamage) * 0.35)`, emits one
`0x0060BC10` BoulderBit at the reduced scale, and rescales every retained shell
vector through `0x004029A0`. Pool `<= 0.001` stops only the current candidate
walk; only pool `<= 0` invokes EBoulder's terminal vslot `0x0060BED0`.

Release `0x005FA6D0 -> 0x005E5450` writes each split child's actual release
scale to `+0x1FC`, so the shrink ceiling is per child rather than the held
carrier's earlier maximum. Terminal `0x0060BED0` restores the saved pre-contact
scale, emits its Ether fade plus the full independently registered
`BadGuys[2008..2010]` BoulderBit breakup, balances the actor-owned loop, and
removes only that released child. Other split children retain independent
target lists, pools, scales, lights, audio ownership, and lifetimes.

`Hailstones` remains a neighboring but separate reachable contact system: its
released carrier executes `0x005FBDE0` and retires individual rock rows through
the documented Hail line/fade path. The inherited `0x00620B60` vtable pointer
does not authorize applying EBoulder whole-carrier shrink or terminal breakup
to Hail's per-rock state.

Native audio ownership is exact:

| Build | One-shot(s) | Loop owner(s) |
| ---: | --- | --- |
| 1000 | registry 57 `magicmissile`, 97 `throwfire` | none |
| 1001 | 38 `frostmissile` | none |
| 1002 | 224/225 `throwlightning` variant | none |
| 1003 | 33 `flamelashstart` | 157 `fire__loop` |
| 1004 | 44 `icestart` | 160 `icebeam__loop` |
| 1005 | none | 172 `steam__loop`, then 157 `fire__loop` |
| 1006 | 87 `startboulder` | 159 `gatherrocksloop__loop` |
| 1007 | none | 165 `meteor__loop` |
| 1008 | 87 `startboulder` | 160 `icebeam__loop`, then 159 `gatherrocksloop__loop` |
| 1009 | 203/204/205 Shock variant | none |

Every loop is player/cast-owned and must balance on release, cancellation,
death, player removal, scene replacement, and audio teardown. One-shot variant
and pitch are cast-authoritative; surviving projectiles are not a reliable
audio event source.

Contact/release one-shots add to that cast table. FrostMissile contact plays
registry 44 `icestart` at pitch `1.5`; BallLightning contact plays registry 224
`throwlightning1` at `1.5`; GroundSpark contact consumes `Float(.1)` for pitch
`1+draw`, then `Integer(3)` for Shock 1/2/3. Hail release plays registry 44
`icestart` and registry 77 `rockhit` at `1.5`, then registry 40 `hailshot` at
pitch one. Hail also writes Region camera magnitude `.1`.

## Retained presentation and release details

- Every `Anim_FadeFlameLash` constructor `0x005292D0` deliberately consumes
  two `Float(360)` words into the same retained rotation field. Tick
  `0x00476230` runs the ordinary Fade clock and adds one degree. Draw
  `0x00457370` uses BadGuys 35, additive blend, current alpha, and per-render
  scale multiplier `2+Float(.25)`. With shipped Enhanced Effects, alpha loss is
  `.2` (`.4` when Off). The primary endpoint child then consumes
  `Float(.5)` for color `(1,1-draw,0,1)`, `Float(10)` for its coupled
  angle/radial offset, `Float(.5)` for scale `.5..1`, and `Float(.75)` for its
  wrapper. Per-contact chain children use fixed color `(1,.75,0,1)`, multiply
  base scale by `.1`, and otherwise consume the same offset/scale/wrapper
  sequence. Each child is an independently registered, Region-lit painter
  root and has no outbound light.
- Blizzard factory `0x005328D0` computes beam width as
  `widen == 0 ? .75 : widen*3+1`; weak state halves it. Draw `0x005308D0`
  builds a record-43 source cap and record-44 strip from two explicit quads.
  Longitudinal half-length is `width*30`; perpendicular half-width is
  `width*25*.908955`. A private xorshift/multiply projection seeded by
  round-to-even `-3*managerTick` applies one coupled `[0,5)` radial/angle
  translation to both quads. Normal local tint is
  `(0.5435550212860107,1,1,1)`; weak is `(.5,.75,1,1)`. Each of the two source
  SpellGlows consumes `Float(.5)` scale and `Float(360)` rotation, dispatches
  procedural variant 24 once, and removes itself from draw. They are direct,
  self-lit roots with no outbound Region source.

- Ball Lightning draw `0x005E0670` has three consecutive painter owners. The
  first is the six-member Air corona at global render phase and random scale
  `.75+Float(.5)`; weak state supplies its `.5` graphics-color multiplier. The
  second is direct BadGuys 70 at local Y `-10`, uniform scale
  `1.25+Float(.1)`, and `Float(1)` alpha under the same weak multiplier. The
  third is not a turn-only branch: byte `+0x168` is initialized to zero by
  `0x005E4F30` and never written by welded handler `0x0053EDB0`, so the complete
  two-pass Ether painter `0x00535A30` always runs. It uses mutable inherited
  phase `+0x154`, scale `1+Float(.5)`, and replaces the graphics alpha
  multiplier with `Graphics+0x3E8*.1` (`Graphics+0x3E8` initializes to one).
  That compositor owns two differently sized BadGuys-110 cores, its
  deterministic BadGuys-111 spark, `2..11` additional BadGuys-111 particles,
  and one BadGuys-112 ray per pass.
- Frost Missile draw `0x006093B0` first renders the ordinary BadGuys 271..282
  body at `(age/4)%12`, age-degree rotation, scale `1.7`, and
  `.75+Float(.25)` alpha. In additive mode it then draws BadGuys 5 at random
  rotation with tint `(.5,.75,1)` and alpha `.2+Float(.25)`, followed by
  BadGuys 110 at scale `abs(sin(age*15deg))*2`, tint `(1,.5,1)`, and the same
  alpha domain. Its two mutable compositor lanes are BadGuys 16, not record
  110: each uses scale `(laneScale,laneScale*laneAspect)`, its retained
  rotation, tint `(.5,1,1)`, and alpha one. Weak state multiplies this complete
  stack by `.5`.
- A positive Frost field `+0x16C` adds two BadGuys-87 affine draws under tint
  `(.75,1,1)` and alpha `.15`. Their matrices are respectively
  `R(turn)*S(1.4,1.12)*R(age*8deg)` with X offset
  `abs(sin(age deg))*3`, and
  `R(turn)*S(1.75,1.4)*R(age*-12deg)`. Handler `0x0053F3C0` writes `+0x16C`
  from the sixth welded vector lane and clears it when underpowered, so this
  is a learned-effect visual branch rather than generic missile decoration.
- `Anim_FadeFrost` draw `0x00457230` calls the complete Water compositor
  `0x005370D0`; `Anim_FadeLightning` draw `0x004572C0` calls the complete Air
  compositor `0x00536380` with its retained/incrementing phase. Frost and Ball
  contacts and the Hail release must reuse those painter families, wrapper
  scale, alpha clock, and independent world ownership rather than a generic
  three-sprite glow.
- Held Hail draw `0x00611160` does not call the Frost-Missile helper. Before
  its rock loop it draws ordinary BadGuys 15 at local zero, tint `(1,1,.9)`,
  alpha `.35+Float(.25)`, and scale `heldScale*4.099999904632568`; it then
  calls the complete Water compositor `0x005370D0` at fixed scale `1.75` and
  global render phase. Released Hail skips both held-only owners.
  Hail's inherited auxiliary vslot `0x005E5530` remains separate: held adds
  BadGuys 15 at actor XY, tint `(.85,1,.85)`, signed alpha
  `.5+Float(.25)`, scale `heldScale*2.5`; flight uses ordinary BadGuys 67 at
  actor XY and `flightScale*2.5`.
  Each retained rock then has two siblings. The record-168..170 body is opaque,
  uses `max(.45,storedScale)*.85` while held or `*.75` in flight, and the held
  opening color `(1-mix,1-mix,1-mix,1)`. A separate BadGuys-32 copy follows at
  the same projected XY, heading rotation, unit scale, white tint, and alpha
  `rockPhase*.8` held or `rockPhase` in flight. Rock phase does not replace the
  body alpha.
- EBoulder draw `0x0060C540` shares Boulder geometry but not its center or
  colors. Its main visual-root aura is BadGuys 15 at tint `(1,.9,1)`, alpha
  `.35+Float(.25)`, and scale `charge*4.099999904632568`. Opening BadGuys 86
  retains the ordinary additive `mix`, `2.5*mix`, and global six-degree phase.
  The remaining body color is `(1-mix,.75*(1-mix),1,1)`. Each transformed
  zero-XY center is replaced by the complete Ether compositor at scale
  `(1+Float(.1))*2*charge`; shell rocks use records 168..170 at
  `max(.25,storedScale*.75)`. Held quantity `1..4` repeats that center/shell
  body at the same depth-sorted `0`, perpendicular `+/-30`, forward `+30`, and
  rear `-15` templates used by release, sorted by projected Y; flight paints
  one body at the released actor root.
- EBoulder's auxiliary vslot `+0x28`, `0x005E5530`, is a separate sibling
  pass. Held state adds BadGuys 15 at actor XY, tint `(.85,1,.85)`, signed
  alpha `.5+Float(.25)`, and scale `charge*2.5`; flight replaces it with
  ordinary BadGuys 67 at actor XY and the same `charge*2.5` scale. Release
  `0x005FA6D0` multiplies angular field `+0x70` by `.75`; it does not shrink
  the body art. Its `.95/.9` per-child factors write gameplay field `+0x224`,
  not a renderer scale.

- Weak EBoulder tests the pre-growth scale. When its retained quantity exceeds
  one it creates `round(max(scale*30,8))` independent `Anim_BoulderBit`
  children before quantity collapses to one. Their construction uses the
  shared five-word Bouncer constructor plus record/vertical/height/distance,
  scale, motion, and signed angular-jitter draws. The retail `MAX` macro
  evaluates its randomized scale argument a second time when the first probe
  is at least `.45`; this conditional extra word is observable and required.
  Every emitted BoulderBit is a separate registered actor. Base Bouncer tick
  skips motion, gravity, rotation, and `.015` base fade on global ticks
  divisible by three while height is nonzero; subclass `.025` fade still runs.
  Other active ticks integrate planar/vertical motion, add `.4` gravity, then
  on ground crossing consume `Float(10)` spin and `Integer(2)` damping,
  multiply bounce velocity by `.3`, optionally multiply planar velocity by
  `.65`, and settle above `-.75`. Settled ticks lose `.015` then `.025` in
  float32 order. Meteor's five impact BoulderBits and weak/contact EBoulder
  children share this recurrence and each retains its own painter root,
  Region-light sample, sort bias `-15`, and retirement.
  The Enhanced Effects branch sets the actor alpha field to `10` after the
  base constructor's `2`; it is not merely a shadow Boolean. Non-enhanced
  children have an 80-update upper bound, while enhanced children are
  state-driven with a strict 400-update upper bound. The former Website
  fixed-80 retirement clipped every reachable enhanced BoulderBit and is
  superseded by the 2026-08-21 contact-family correction.
  Draw `0x00457E40` submits the enhanced airborne shadow through helper
  `0x00415020` before the lit sprite. Raw instructions show that helper receives
  the same fragment descriptor from actor `+0x24`: the shadow is the same atlas
  record, black, alpha `min(1,actorAlpha)`, at local Y `+2`, with the same
  rotation and scale `(fragmentScale,fragmentScale*.75)`. The main colored
  copy is at the dynamic height with uniform fragment scale. Ordinary
  BadGuys-32 Hail bouncers use the same inherited shadow geometry; their main
  copy remains normal-blended. `Anim_AdditiveBouncer` is a separate subclass
  and is not inferred here.
- Hail rock count is tie-to-even rounding of
  `max(1,scale^2*(widen*3+20))`. Each Enhanced new rock adds a `Float(20)`
  record-18 birth fade that lives 400 `.01` alpha-loss ticks independently.
  Release moves the carrier backward 20 along both direction axes, consumes
  `Float(.75)` for wrapper scale `.75..1.5`, and creates a 20-tick FadeFrost at
  `(carrier.x,carrier.y-20)`. Released rock Y is
  `localY + ((50-localZ*.8)-localY)*decay`; decay multiplies by `.95` per tick.
  That decaying Y is a draw field: collision retains the release-time offset
  and only adds widen displacement. `0x005FBDE0` first tests the complete
  30-unit static line, then performs three ten-unit movement/contact substeps.
  Candidate targets preserve the native query order; targets are the outer
  loop and the mutable rock list is the inner loop. The strict per-rock test is
  `distanceSquared < (targetRadius*1.5)^2`. A target that dies stops receiving
  later rocks in that substep. Damage is `min(targetHealth,rockPool)` while
  pool consumption alone divides by toughness unless the pool is smaller than
  health. No Hail branch calls shared Boulder contact child `0x0060BC10`.
  Static-line termination creates fifteen additive moving BadGuys-45 children
  and one BadGuys-32 bouncer per remaining rock. Each rock consumes 83 RNG
  words: five for each of the fifteen moving children and eight across the
  Bouncer constructor, scale/lead/speed, and next-sector angle. The moving
  children own `.125` alpha loss and `.92` velocity damping. The Bouncer owns
  the global-modulo-three pause, `.4` gravity, `.65` bounce/damping, rerolled
  spin, `-.75` settle threshold, and `.015` alpha loss.
- Meteor Swarm emits record-51 `Anim_Iceblast` before its gameplay draw every
  held tick. Cadence is selected-primary age modulo
  `max(5,trunc((weak?35:25)/round(castFactor)))`. Spawn consumes seven words
  normal and six weak. Impact consumes camera unit vector, rotation/radius,
  angle seed, five 13-word BoulderBit programs, then a two-word signed sound
  pitch. Object `+0x13C` is the falling-height scalar initialized in
  `[5,6.25)`, decremented by the stored fall step, and multiplied by `-768` for
  both BadGuys 15 and 50 fall glyphs. Object `+0x74` is the separate body scale
  in `[.75,1)`; it remains constant through fall, controls body geometry, and
  seeds impact radius `[bodyScale,bodyScale+.5)`. Direct radius is 45;
  recurrence uses impact field `+0x15C*45`. Impact constructor `0x00610880`
  separately registers an orange BadGuys-15 `Anim_FadeAdditive` at scale six,
  alpha two, and `.1` loss; it is not nested under the Meteor draw owner.
  Main fall draw `0x005E16C0` uses orange BadGuys 15 at
  `3+Float(.5)` scale, then BadGuys 50 with per-render signed X scale
  `+/-bodyScale`, Y scale `bodyScale*2`, and rotation
  `fallHeading*.5+180`. Auxiliary slot `+0x28`, `0x005E6DE0`, independently
  draws normal-blended DeadHawg 19 at the ground root with scale `(2,1.6)` and
  alpha `max(0,1-fallHeight)*.5`. After impact it instead draws additive
  BadGuys 67 at scale `(impactRadius,impactRadius*.8)`, retained impact
  rotation, and alpha `min(impactTicksRemaining,100)/100`. BadGuys 50 is not
  the impact disc.

The Region light-provider set is also closed:

| Owner | Lane | Submitted light |
| --- | --- | --- |
| FireMissile, FrostMissile, BallLightning | actor | intensity `.75`; radius `.75 + Float(.1)`; actor position; `Multiple Shadows` controls directional casting (`0x005E4AF0`) |
| GroundSpark | actor | intensity `.5 + Float(.5)`; radius `.4`; no directional shadow (`0x005E7800`) |
| EBoulder, Hailstones | actor | intensity `.5`; radius `max(.5, actorScale * .75)`; `Multiple Shadows` controls directional casting (`0x005E5670`) |
| Meteor | actor registration | `0x005E7040` submits only when falling height `+0x13C <= 1`. Intensity is `min(1, visibility * (1-fallHeight))`, with impact visibility `min(impactTicksRemaining,50)/50`; radius is impact scalar `+0x15C * .6`, and directional shadow is false. `+0x15C` begins at one and becomes `bodyScale+Float(.5)` on impact. The provider is silent during high fall, then contributes during final descent/impact; registration order is retained throughout. |
| Flame Lash, Blizzard Beam, Steam Jet and their short-lived wrappers | none found in their concrete vtables/draws | no standalone Region source; any contacted target or spawned child keeps its own independently documented light behavior |

Process-global per-render flicker cannot be sample-identical in a distributed
browser because the retail cursor and all intervening consumers do not exist.
The permitted translation is stable actor/frame sampling with the exact native
domain, formula, submission lane, ordering, and lifecycle. It is not permission
to add gradients, CSS glows, or unregistered lights.

## Welding item effects

If progression `+0x878` has bit `0x800`, `0x00666020` scans skill IDs 8..79.
An unlearned row is promoted to level 1 when its entry carries the native
component-eligible flag at `+0x29` and it is not a primary-kind row. Exact FX
application at `0x00576AA0` proves that this bit belongs to `FX_MAXWELD`, whose
native display name is **Energize Weld Components**. The earlier provisional
association with `FX_WELDCALLING` was incorrect.

The ten hard-coded recipe tables close the eligible non-primary membership to
`9,10,17,18,25,26,33,34,42,43`: the two component rows paired with each of the
five elemental primaries. Energizing changes only the effective rank when its
permanent/equipment-resolved rank is zero; it does not learn the row
permanently, alter the learned build, selected primary, or skill quickbar.

`FX_WELDCALLING` sets the separate `+0x878` bit `0x1000`. During ordinary
level-up candidate construction, `0x0067CB70` normally chooses from the general
eligible pool. With this bit set, one branch instead builds candidates related
to learned primary-kind rows through `0x00658450`, adds eligible related rows,
falls back to unlearned primary-related rows when the pool is small, and chooses
from that welding-oriented list. This is the native **+Bias Skills for
Welding** behavior; it does not auto-learn every weld component.

The native item-effect name table at `0x00571560` includes:

| Effect ID | Display/effect name |
| ---: | --- |
| `0x25` | Energize Weld Components |
| `0x26` | Enhance Weld Effect |
| `0x27` | +Bias Skills for Welding |

The exact parser/application mapping is:

| Token | Effect ID | Destination | Behavior |
| --- | ---: | --- | --- |
| `FX_MAXWELD` | `0x25` / 37 | `+0x878` bit `0x800` | Energize eligible unlearned weld components. |
| `FX_WELDEFFECT` | `0x26` / 38 | scalar `+0x8E0` | Flat adds magnitude, `*` multiplies, and percent adds `magnitude / 100`. |
| `FX_WELDCALLING` | `0x27` / 39 | `+0x878` bit `0x1000` | Bias level-up candidates toward welding-related skills. |

The full item parser, equipment pass, and all 39 FX destinations are in
[native-items-equipment-and-loot.md](native-items-equipment-and-loot.md).

## Eligibility and presentation

General skill eligibility is implemented by `0x0065E830` and `0x0065EBA0`.
It accounts for global unlock bytes for late catalog entries, already-learned
state, player level, at-least-one prerequisite groups, and all-required
skill/level pairs stored in the 0x70-byte entry. Welding adds its own learned
primary-pair and prior-offer filters in `0x0067CB70`.

The special row's help text path returns `TWO ATTACK SPELLS TO COMBINE`
(`0x0067BE60`). `0x00665F10` maps skill `0x34` to one of Skills-atlas display
IDs `0x51..0x5A` according to build 1000..1009; normal skills use their entry's
display selector at `+0x30`. `0x00665FF0` refreshes that selector after skill
state changes.

The level-up weld presentation is built at `0x00671810`. The common card path
first draws Skills record 13 in white at scale `1.15`. An ordinary skill then
draws Skills record 164 once in its root color. Welding replaces that ordinary
record-164 draw with one deterministic split-color mesh: triangle
`P0/P1/P2` uses the first component color and triangle `P1/P2/P3` uses the
second. Positions and UVs come from record 164, all positions are scaled by
`1.15`, renderer modulation is applied component-wise, and `0x00747360`
performs deterministic x87 float-to-integer rounding before ARGB packing. No
random number is consumed by this overlay path.

The normal Welding offer uses Skills frame record 14. Its ten display selectors
`0x51..0x5A` index the Skills subarray whose first entry is atlas record 27, so
the actual synthetic icon records are `108..117`, not `81..90`. `0x006720F0`
draws the synthetic icon twice (shadow then main). Progression vtable
`0x007A0CD4` slot `+0x84 -> 0x00663B30` maps row 52 and build 1000..1009 to one
synthetic name. The name is medium-font, root-tinted, and shadowed in the normal
name lane; exact `ARCANE ` (including its trailing space) occupies the family
lane. The `Welded ...` pair string is a
separate centered, white, unshadowed quick-description line. There are no six
component-name/learned-level rows in this renderer: the six IDs below are
stat-rebuild recipe data only.

| Build | Record | Synthetic name | White pair description | Stat recipe IDs |
| ---: | ---: | --- | --- | --- |
| 1000 | 108 | `Burning Bolt` | `Welded Magic Missile + Fireball` | 8, 16, 10, 18, 9, 17 |
| 1001 | 109 | `Frost Missile` | `Welded Magic Missile + Frost Jet` | 8, 32, 10, 34, 9, 33 |
| 1002 | 110 | `Ball Lightning` | `Welded Magic Missile + Lightning` | 8, 24, 10, 25, 9, 26 |
| 1003 | 111 | `Flame Lash` | `Welded Lighting + Fireball` | 16, 24, 18, 25, 17, 26 |
| 1004 | 112 | `Blizzard Beam` | `Welded Lightning + Frost Jet` | 32, 24, 34, 25, 33, 26 |
| 1005 | 113 | `Steam Jet` | `Welded Fireball + Frost Jet` | 16, 32, 18, 34, 17, 33 |
| 1006 | 114 | `Ethereal Boulder` | `Welded Magic Missile + Boulder` | 8, 40, 10, 43, 9, 42 |
| 1007 | 115 | `Meteor Swarm` | `Welded Fireball + Boulder` | 16, 40, 18, 43, 17, 42 |
| 1008 | 116 | `Hailstones` | `Welded Frost Jet + Boulder` | 32, 40, 34, 43, 33, 42 |
| 1009 | 117 | `Crawling Shock` | `Welded Lightning + Boulder` | 24, 40, 25, 43, 26, 42 |

The `Lighting` spelling in build 1003 is the retail string. The card-text
cluster in `0x006720F0` has seven calls to centered text wrapper `0x004A57C0`:
shadow/main for name, family, and classification, plus one white
quick-description call. An earlier conditional eighth call draws `casting` or
`concentrate`; it is not a component row. Neither the card cluster nor
split-mesh helper `0x00671810` contains a component-row text loop.

The exact card text ABI is:

- medium name, maximum width 140, source case preserved, at local Y 150;
- skill-font `ARCANE ` at local Y `150 + measured wrapped-name height`;
- body-font lowercase `primary cast` at local Y 280;
- medium white pair description, source case preserved, maximum width 140,
  vertically centered around local Y 230;
- black shadows at `(+1,+1)` only for the name, family, and classification.

The classification calls are an exact static card-function ABI, but their
pixels are not proved on the level-up offer surface. The same-SHA sealed
Ring-of-Fire offer capture has no classification pixels even though its row is
category 2 and the Wizard path constructs `secondary cast`. Website offer
parity therefore suppresses this lane, including Welding's `primary cast`,
until a targeted live call/clip-state capture resolves the runtime condition.

At the observed card top `302.5`, those fixed anchors are Y `452.5` and
`582.5`; medium line height is 16 with a 17-pixel line step. Synthetic names and
pair descriptions remain Title Case. This UI reads the current synthetic build
but does not own cast-time stats.

## Custom-content boundary discovered here

The stock system is closed over ten hard-coded pair cases and fixed native
skill IDs. New CFG files alone cannot add an eleventh weld recipe: selection,
six-component expansion, presentation-ID mapping, and stat reconstruction all
contain compiled switches/tables. Art replacement can change the ten existing
weld icons if the Skills bundle ABI is preserved. Arbitrary new welds require
a loader-owned registry and hooks at all four native decision points, or a
complete replacement of the welding layer.
