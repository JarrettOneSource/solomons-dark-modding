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
| Air | cast origin to retained target/aim line; instantaneous, so no velocity or spread | line/world clip at `0x00524D70`; target/chain query every held tick at `0x00641340` | exists only while the primary is held; each chained hop scales the next damage by `0.6`; bolt body lives `2` ticks and contact fade lives `5` ticks |
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

The flight body is **not** `BadGuys[53]`. Draw `0x005E0460` delegates the
whole in-flight presentation to Ether compositor `0x00535A30`, which consumes
registered `BadGuys[110..112]`. Record 53 belongs only to the surviving-pierce
contact fade described below. The 2026-08-14 presentation audit at the end of
this report records the exact compositor formula and corrects the older
one-sprite shorthand.

The initial point is the common glyph emitter with local `(0,+10)` applied.
Target acquisition probes `100` units ahead of the caster. Initial speed is

```text
speed = 3 * (1 + mSpeed / 100)
```

and the rank-1 and controlled rank-2 captures both retained `3.0` world units
per native tick. For quantity `N`, the angular step is `30` degrees below four
and `20` degrees otherwise. Let `base = aim + (N even ? step/2 : 0)` and
`tier(i) = ceil(i/2)`. Child `i=0..N-1` uses
`base + (i even ? +1 : -1)*tier(i)*step`. The zero-offset child is first, then
matched left/right tiers follow: `N=4` is `+10,-10,+30,-30`, and `N=5` is
`0,-20,+20,-40,+40`. The single cast-time damage roll is copied to every
child. Every visual scale remains `1`; speed is `3*smartFactor`, while homing
turn input is paired by tier as
`2*smartFactor*0.75^ceil(i/2)`. Homing then runs every tick.

The gameplay actor radius is `15`. The target-proximity pass runs every tick
with the native `6`-unit probe constant. Terrain is tested every fifth tick
against a five-tick forward segment. There is no recovered hard lifetime: both
rank fixture windows contain `604` consecutive native ticks. Once age exceeds
`200`, the candidate mask broadens from `2` to `6`; that is a search-policy
transition, not expiration.

Pierce is held in the actor byte at `+0x161`. A zero value makes the first
accepted contact remove the missile. A positive value is decremented; visual
magnitude and remaining damage are scaled, the actor is advanced beyond the contact,
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

The complete impact payload is constructed by `0x0053DC60`. It copies row 16
base damage, row 18 explosion damage/radius, row 17 Ember damage/count, the
mutually exclusive row 19 or 20 retirement mode and damage, a 300-tick GoodImp
lifetime for mode 2, and a private integer seed in `[0,1000000]`. Mana is the
sum of active rows 16-20; inactive mutually-exclusive rows contribute zero.
Accepted actor contact deals row-16 damage minus row-18 explosion damage when
Explode is active, otherwise the full row-16 damage. The projectile is removed
and `fireballhit` plus the common 16-tick impact presentation are requested
before the optional area/fragment work.

`0x00642BF0` owns that area/fragment work. For Explode it receives
`visual_scale=(radius-10)*0.18+1`, queries the native rectangular footprint
with dimension `visual_scale*110`, and gives every returned hostile fixed
damage `explode_damage*0.5`. The same path runs for actor and terrain impacts.
It then seeds a private RNG from the Fireball seed. For `N>0`, step is `360/N`,
the first base heading is uniform in `[0,360]`, and child `i` uses the current
base plus signed uniform jitter of magnitude at most `step/3` before the base
advances by one step. Horizontal speed is
`(1.5 + U[0,0.5])*0.75`, spawn position is impact plus ten times that velocity,
height is `-6`, and vertical velocity is `-(2 + U[0,3])`. Every child carries
the snapshotted Ember and retirement payload and is ticked exactly ten times
immediately after registration. Registration occurs before those ten calls, so
every cadence crossing executes the ordinary contact slot during the pre-age
loop. A browser implementation must publish all of those ordered queries,
consume the child on its first accepted contact, and suppress later pre-age
queries for that same child; retaining only the final cadence field loses real
stock damage and Burn ownership.

`Ember::Tick 0x0060D7E0` advances airborne motion by
`min(abs(vertical_velocity),1)`, adds gravity `0.15`, bounces with multiplier
`-0.5`, halves horizontal velocity on each bounce, and settles when rebound
magnitude is at most `0.5`. Grounded life falls by `0.015` per tick from its
initial `3`; animation phase advances by `0.25` and wraps at `4`. A normal
contact consumes the Ember after applying its damage and Burn helper and does
not execute a retirement mode. Only a naturally spent grounded Ember below
life `1` runs mode 1 or 2. Mode 1 re-enters the area helper at scale `1`, no
fragments, and fixed target damage `spent_damage*0.5`. Mode 2 creates GoodImp
with both attack endpoints `spent_damage*0.5`, lifetime `300`, and a sibling
`Fire 0x7E3` patch. Mode zero remains until life reaches zero.

Constructor `+0x15C` is a contact cadence counter, not a presentation variant.
It starts from `Integer(10)`. Every Ember tick increments it; values strictly
above three reset to zero and call contact slot `+0x64` (`0x005E5700`). After
the first randomized delay, contact therefore recurs every four fixed ticks.

Ember presentation is not a Fireball trail alias. Its draw path
`0x0060DDD0` uses BadGuys records `267..270` at actor position plus height,
BadGuys 15 for the orange glow, and `251..254` for contact. The main sprite is
source-alpha plus an additive phase layer; alpha is `min(life,1)`, while the
glow uses `min(life*0.2,1)` and `min(life,1)` scale. Its optional enhanced
airborne geometry is presentation-only.

### Shared Fire explosion and Ember presentation closure (2026-08-22)

A fresh read-only pass reopened the shared helper because the earlier browser
ledger called Explode presentation closed without preserving its child classes,
records, clocks, audio, light, or complete xref membership. The helper is
`0x00642BF0`; its six direct callers are scripted `DO EXPLOSION AT`
`0x00466BC0`, special enemy-death mode `0x00477020`, FireMissile contact
`0x005E4CA0`, Fireball contact `0x005E5160`, maximum-set Shockwave contact
`0x005FF8C0`, and naturally spent Immolate Ember `0x0060D7E0`. There is no
direct call from this helper or any of those Fireball/Ember owners to
`Region::ApplyCameraShake 0x0063EEB0`.

The shared explosion creates three independent presentation children in this
order:

| Child | Native class and records | Exact fixed-tick program |
| --- | --- | --- |
| orange core | `Anim_Fade 0x00452E20`, BadGuys 15 | root `(x,y-25)`; normal blend; scale `6*visualScale`; alpha starts `1`, loses float32 `0.1` per tick, and is visible at ages `0..9` |
| normal/additive array | `Anim_SpriteArray 0x00453410`, BadGuys `401..419` | root `(x,y)`; additive; scale `2*visualScale`; phase starts `0`, step starts float32 `0.75`, step multiplies by float32 `0.98` after every tick; positive truncation selects the record; it retires after tick 35 and is visible at ages `0..34` |
| rising lit array | `Anim_SpriteArray` wrapped by `ZAnimLit 0x005E03D0`, BadGuys `420..433` | additive; phase step starts float32 `0.625` and multiplies by float32 `0.97`; initial offset `(0,-15*visualScale)`, then Y loses `1.15*visualScale` per tick; it retires after tick 37 and is visible at ages `0..36` |

The lit array's local scale and light radius are twice the Region point gain
sampled at creation. `ZAnimLit` begins intensity `2`, loses float32 `0.02` per
tick, and submits `min(intensity,1)`; it therefore supplies intensity one for
the array's complete 37-tick life. Its directional-shadow flag is the native
Multiple Shadows setting. The helper also requests `fireballhit` at
`1+S[0,0.1]` and `throwfire` at exact pitch `0.8`, both at twice Region point
gain. Fireball contact has already requested its separate ordinary
`fireballhit`, so an Explode contact owns all three requests in order:
ordinary hit, shared-explosion hit, shared-explosion throw.

The same pass closes the Ember renderer rather than treating records
`267..270` as a conventional three-sprite stack. `Ember::Draw 0x0060DDD0`
first draws the selected record source-over at scale `0.5`. It then enables
additive blending and draws one copy with scale `0.75-U[0,0.5]` and rotation
`U[0,0.1]` degrees; Enhanced Effects draws a second independently sampled
copy. The final additive BadGuys-15 glow is tinted `(1,0.5,0)`, uses alpha
`min(life*0.2,1)`, scale `min(life,1)`, and Y offset `0.8*height`. The optional
airborne pass `0x005E5A20` exists only with Enhanced Effects and negative
height; it is separate from collision and lifetime. It is not another Ember
atlas copy. It draws the shared untextured quad at the actor's ground root.
Live stock memory pins that quad's four registered corners to
`(-19,-18.5)`, `(19,-18.5)`, `(-19,18.5)`, `(19,18.5)`. The pass scales them
by `(0.75, 0.6000000238)`, producing a `28.5 x 22.2000009` footprint, tints it
`(1,0.5,0.25)`, and stores alpha
`float32((1-height/-50*0.5)*0.25)`. Reusing record `267..270` here creates the
large duplicate sprite that made web Embers appear visually glitchy.

`Ember::Light 0x005E5960` supplies an actor-lane point light at the Ember root:
radius is `1-U[0,0.25]`, intensity is `min(life,1)*0.25`, and the directional
shadow flag is false. Normal mode-zero Embers remain alive through the whole
grounded fade interval `0 < life < 1`; modes one and two retire on the first
crossing below one to create the Immolate explosion or GoodImp/Fire pair.
Consequently a wire contract that rejects live mode-zero life below one is not
a native invariant.

The explosion and Ember visual draws consume presentation RNG in stock. A
deterministic multiplayer renderer may project those draws from stable effect
identity and display frame, but it must preserve the exact ranges, draw count,
order, blends, and clocks without advancing gameplay authority RNG. The
authoritative constructor stream still owns Ember phase, the deliberately
discarded initial vertical draw, contact cadence, private fan seed, and
all gameplay motion/contact state.

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

- atlas phase `+0x13C` is initialized by unsigned `RandomFloat(frame_count)`;
  tick `0x005FF050` adds the independent phase step at `+0x140` and subtracts
  the frame count once when the result reaches it. The Fire base constructor
  writes exact `0.25` to the step; `MovingFire` replaces it with float32
  `0.12`;
- lifetime `+0x144` starts at `2.0` and falls by `0.01` per tick, for `200`
  native ticks;
- scale-in `+0x148` rises by `0.05` per tick to `1.0`; constructor lane
  `+0x14C` is a separate `RandomSign(1)` horizontal mirror, so it is exactly
  `-1` or `+1` rather than a continuously sampled width;
- base scale is stored at `+0x150`, damage at `+0x158`, and draw alpha at
  `+0x15C` (initialized to one);
- while damage is positive, every tick divisible by three performs a strict
  circular `32 * scale` radius contact pass and dispatches through the same
  fire helper and contact lane. Every accepted target consumes one unsigned
  `RandomFloat(0.5)` response draw before damage is applied. A target that
  remains inside may therefore be hit on more than one pulse.

This is the positive-lifetime trail actor observed by the botmana campaign.
The corrected stock secondary dispatcher at `0x0054CC50` creates live damaged
`0x7EE` actors while Firewalker remains active; Fire Wall also creates them.
The earlier byte-toggle experiment described in
[`beta32-bot-mana-and-lone-target-handoff-2026-08-04.md`](../bugs/beta32-bot-mana-and-lone-target-handoff-2026-08-04.md)
did not reproduce that stock path. A browser implementation must preserve the
distinction between Fireball's cosmetic particles and these damaging residual
actors.

### Ring of Fire and Firewalker closure

The Ring helper `0x0063F920` does not give all of its children the authored
damage. It creates exactly 30 `MovingFire 0x7E6` presentation actors, then one
`Shockwave 0x7E7` gameplay actor. The MovingFire loop uses base headings
`0,12,...,348` degrees. Construction consumes the common Fire constructor's
`RandomFloat(frame_count)` phase and `RandomSign(1)` mirror first. Each child
then adds a signed `U[0,2]`-degree heading jitter, chooses a radial
`U[0,30]` spawn distance and an independent random-unit heading for that
offset (with the native `0.8` vertical projection), and adds 25 units of its
clockwise-from-up `(sin(theta),-cos(theta))` heading vector before
registration. The final construction draw is the movement-speed jitter. Its
initial movement is `2.5*(1-U[0,0.025])` along that heading and each component
is multiplied by `1.01` per tick. Scale is `2.75`; remaining life is `1.05`
and falls by `0.01` per tick. The helper never writes its damage field, so the
three-tick Fire contact branch remains dormant for these 30 children.

`MovingFire::Tick 0x005FF870` first runs the common Fire tick, then advances by
its velocity and multiplies the two velocity components by their stored
`1.01` factors. Common draw `0x00610F90` uses additive `DeadHawg[46..77]`, a
base `1.1*scale` transform, alpha
`min(draw_alpha*remaining_life,1)`, and local position `(actor_x, actor_y-20)`.
The scale-in lane scales both axes while the `+0x14C` sign mirrors the X axis,
so the final sprite scale is
`(1.1*scale*scale_in*mirror_sign, 1.1*scale*scale_in)`. The drawn atlas record is
`DeadHawg[46 + round_to_even(atlas_phase)]`; it does not derive from actor age
or the phase-step field. This is the visible expanding ring; it is not thirty
parallel damage sources.

The sibling Shockwave is initialized with radius `75`, radius growth `6` per
tick, push scalar `1`, remaining life `1.155`, fade threshold `0.12375`, and
the row-21 damage. Tick `0x005FF8C0` grows the radius before subtracting `0.01`
from remaining life. During the final fade band it multiplies the push scalar
by float32 `0.899999976` per tick. Every ten actor ticks it queries the expanding footprint,
retains each accepted actor only once, writes `mDamage*0.5` to each of the two
native damage lanes (the target sums them back to full `mDamage`), runs the
Fire/Burn helper, and attaches the fixed 400-tick Dazzle response. On the separate
two-tick lane it pushes each retained live actor radially through
`0x00525800`. Ring activation requests `bigfire` followed by `nuke`; the
MovingFire children do not own those one-shots.

Shockwave's `0x005E7AA0` draw slot is a light provider, not a hidden missile
sprite. It converts the actor point through Region vslot `+0xF4`, then submits
to the Arena light-field manager at `Region+0x8C44` through `0x0057FE40`.
That call draws DeadHawg record 18 into the raster light map and records the
matching analytic source with radius `wave_radius/140`, intensity equal to the
current push scalar, and shadow flag false. The light therefore expands with
the gameplay radius and fades under the same float32 `*0.899999976` recurrence;
it must not be approximated as a DOM/Pixi glow unrelated to Region lighting.
The retained-target lane does not normalize its delta. On every even actor
tick it adds `(target-waveOrigin)*pushScalar*radiusGrowth`, where the fixed
radius growth is `6`. Contact
query/insertion runs first, so a target discovered on tick 10 is already in the
list when tick 10 performs its push.

Fire Wall case `73` in `0x0054CC50` closes the sibling linear geometry. It
normalizes the aim-perpendicular vector, takes endpoints 150 units to either
side of the aimed point, and sets a 30-unit step. The inclusive loop therefore
creates eleven `Fire_Goodguy 0x7EE` patches at distances
`d=0,30,...,300`. Their constructor scale is multiplied by
`0.8+0.6*sin(pi*d/300)` and life is overwritten with scalar `7`. Because the
shared tick subtracts `0.01`, each wall patch owns 700 ticks rather than the
constructor's 200 ticks. After constructor
RNG, each birth consumes unsigned `RandomFloat(10)` plus the native random-unit
heading draw to offset the patch. The two creation cues are requested in fixed
order, `ignite` then `fireballhit`; each live patch uses the already recovered
DeadHawg 46..77 strip, damage/Burn cadence, and `lowfire__loop` renewal.

Turn Undead helper `0x00647EF0` uses a strict 500-diameter query (`250` radius,
mask `2`) centered at the caster. For eligible undead it writes the away angle
to `+0x6C` and `+0x19C`, then writes `round(mFlee*100)` to `+0x20C`; base
hostile tick `0x004835F0` decrements that positive field. This disproves the
older timestamp interpretation. Weakening occurs only when the pre-cast field
is the untouched `<=-9000` sentinel, so later casts refresh control without
compounding attack reduction. Its presentation creates 35 source-alpha
`Anim_FadeScale_Perspective` children over BadGuys record 48 at the cast point.
The first angle is `RandomFloat(360)`; subsequent angles add
`20+RandomFloat(40)`. Each child draws at `1+RandomFloat(1)` initial scale,
multiplies scale by `1.1` per tick, and loses `0.05` alpha/life per tick for a
20-tick lifetime.

Firewalker is owned by a different player-tick branch at
`0x0054B35C..0x0054B53C`. While progression byte `+0x8DC` is set, player mode
is not `2`, and the global tick is divisible by ten, it creates one
`Fire_Goodguy 0x7EE`. No nonzero-movement test guards this creation. Birth is
the player point plus signed `U[0,10]` times the perpendicular velocity vector
and unsigned `U[0,8]` times the velocity vector. The constructor scale is
multiplied by `1-U[0,0.5]`; damage is copied from progression `+0x894`; and
remaining life is progression `+0x898` multiplied by
`1.1-U[0,0.25]`. A global three-value counter marks exactly one of each three
children for the supplemental contact geometry.

The common Fire tick advances the independently initialized atlas phase by the
actor's phase step (`0.25` for Fire/Fire_Goodguy, float32 `0.12` for
MovingFire), subtracts `0.01` from remaining life, raises scale-in by `0.05`
to a ceiling of one, and invokes area contact
on global ticks divisible by three while damage is positive. Contact uses a
strict circular radius `32*scale`, consumes one unsigned `RandomFloat(0.5)`
response draw per accepted target, runs Burn when the actor mask enables it,
and feeds the authored damage through the native per-second normalization
`(damage / Game+0xC00) * 3 * 0.5` in each of two target damage lanes. `MyApp` construction
`0x0040BA23..0x0040BA30` is the sole exact `+0xC00` writer and copies the
float at `0x007DE9B8`, which is exactly `100.0`. Stock contact is therefore
`damage*0.015` in each lane, which the target sums to semantic
`damage*0.03` on every accepted three-tick pulse; it is not a flat authored
damage hit. Fire construction and contact RNG are also ordered: phase, mirror
sign, actor-specific construction draws, then one unsigned `RandomFloat(0.5)`
response draw for every accepted target.

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
contact queries immediately. Presentation is not one ten-tick fade object.
`0x00531640` creates a two-tick `Anim_LightningBolt`, a one-shot source
`Anim_SpellGlow`, and the world/split wrapper. `0x0053F9C0` separately creates
a five-tick `Anim_FadeLightning` contact corona whenever the clipped/target
endpoint is valid. The handler creates a fresh set on every sustained tick, so
a steady hold overlaps at most two bolt bodies and five endpoint coronas.

The fixture records the ray state on every native tick at rank 1 (`229` rows)
and controlled rank 2 (`259` rows), rather than inventing a projectile actor.

### Lightning presentation ownership

The complete normal player path in retail Beta 0.72.5 is:

```text
0x0053F9C0 player held-tick handler
  -> 0x00531640 Lightning presentation factory
     -> 0x0045B2C0 Anim_LightningBolt constructor
        -> 0x00534510 procedural ribbon tessellator, called twice
        -> 0x00453BD0 two-tick update
        -> 0x004575D0 additive two-layer render
     -> 0x00454AD0 Anim_SpellGlow constructor at the cast source
        -> 0x00459A00 render -> 0x00536380 corona painter
     -> ZAnimSplit vtable 0x00784664 / registration 0x0063F6D0
  -> 0x00452E20 Anim_Fade base construction at contact
     -> Anim_FadeLightning vtable 0x007865C8
     -> 0x00476230 update -> base fade update 0x00454000
     -> 0x004572C0 render -> 0x00536380 corona painter
     -> 0x005E03D0 ZAnimLit child
```

This corrects the former classification of `0x00536380`: that function is the
source/contact corona painter, not the lightning ribbon builder. The ribbon
builder is `0x00534510`.

The primary call gives `0x00531640` the staff cast point, a half-distance
direction-derived middle point, and the clipped or retained-target endpoint.
A contacted actor contributes a `-20` Y attachment offset. Primary segments
enable the source glow; chained segments disable it and perturb the middle
point by a random radial vector. `0x00531640` also walks both straight control
legs in `100`-unit steps, considers the exact endpoint of each leg, and emits
auxiliary Region lights only once a sample is at least `220` units from the
original source (`48400` squared-distance constant).

`Anim_LightningBolt` has vtable `0x0078556C`, object size `0x70`, integer
lifetime `+0x2C = 2`, tick `0x00453BD0`, and render `0x004575D0`. Its constructor
calls `0x00534510` twice over the same three points:

| layer | width / phase | color |
| --- | --- | --- |
| first | `1.0`, `-3 * native render tick` | RGBA `(1,1,1,1)` |
| second | first width times native double `0.75`, first phase plus native double `15` | RGBA `(0,1,1,0.5)` |

`0x00534510` appends all three points to `QuickSpline` through `0x0062BCA0`;
the coefficient builder is `0x0062A9E0`, evaluator is `0x0062B2F0`, and
tangent-normal helper is `0x00529010`. The middle point is therefore
native-significant. Cadence nevertheless measures only the first
source-to-middle leg at `0x0053461C..0x005346DA`. It uses the Quake fast
inverse-square-root seed `0x5F3759DF` at `0x0053462A`, one Newton refinement at
`0x005346C6..0x005346DA`, and float32 stores for the squared length, estimate,
recovered reciprocal distance, ratio, step, and loop accumulation. It divides
that recovered distance by native double `15` when Enhanced Effects byte
`0x00B3BCAD` is set (`0x005346F7`) or `30` when clear (`0x005346FF`), and
computes
`step = splineDuration / (firstLegDistance / spacing)` at
`0x00534735..0x0053473D`. Float `0.5` at `0x007DE870` caps the step at
`0x00534741..0x00534756`; the cap is not `1`. The strict loop condition is
`t < duration - step` at `0x00534AD8..0x00534AEB`, increment is at
`0x0053516D..0x00535182`, and the exact duration endpoint is appended after
the loop.

`0x00B3BCAD` is the literal `ENHANCED EFFECTS` Boolean persisted under the
misleading `Game.FastCPU` key. Settings loader `0x005BB310..0x005BB34F` uses
capability byte `0x00B3BCAE` as the missing-key fallback. The shipped defaults
block omits the key, and the recognized Windows path seeds the capability byte
to `1`, so a new shipped profile selects Enhanced Effects On / spacing `15`.
A preserved false-profile capture selects Off / spacing `30`; it proves the
branch remains user-selectable rather than defining the shipped default.

For the current rank-1 untargeted path, the collinear points are source `0`,
middle `102.5`, and endpoint `205`. Float32 squared length is `10506.25`; the
one-step inverse-square-root path yields effective distance
`102.67955780029297`, ratio `6.845304012298584`, and step `0x3E959773` /
`0.29217109084129333`. Float32 accumulation produces the exact parameter
samples
`[0, 0.29217109084129333, 0.5843421816825867, 0.8765132427215576, 1.1686843633651733, 1.460855484008789, 2]`.
The next candidate `1.7530266046524048` fails the strict loop threshold. Each
layer therefore has seven vertex pairs/fourteen vertices, six neighboring
segments, and thirty-six indices. This is not `ceil(205 / 15)`. The explicit
Off branch remains capped at step `0.5` and produces four pairs/eight
vertices/three segments/eighteen indices.

At each loop sample, envelope is `sin((t / 2) * pi)`. The center adds a normal
wave `envelope * sin(t * 360 degrees + phase) * 25`, a second normal wave
`envelope * sin(phase * 2.5 - t * 90 degrees) * 12`, and active-RNG radial
displacement with signed angle magnitude below `65` degrees and radius below
`30`, also multiplied by the envelope. Half-width is
`((1 - envelope) * 0.75 + 0.5) * width * 25 * 0.5`; the separately appended
endpoint uses untapered `width * 25 * 0.5`. `0x00529010` finite-differences
the spline with `0.001` before normalizing its perpendicular. Each sample
contributes two 24-byte textured vertices and each neighboring pair contributes
six indices. The two calls consume independent random samples, so they do not
produce geometrically identical nested ribbons. Geometry is fixed at
construction, not rerolled by render.

The renderer binds the texture pointer at BadGuys object `+0x21F0`, which is
inline BadGuys record `44` at object `+0x21E8`, submits both triangle lists
through `0x0041DA00`, and brackets them with the world renderer's additive/
special state byte at `+0x3F1`. The tessellator can append one textured
four-vertex flare/branch selected from the two-record BadGuys array at object
`+0x4818`; the choice and orientation consume the active RNG. Sibling
`Anim_DarkLightningBolt` uses vtable `0x00785598` and the same two-layer
tessellator/lifetime but intentionally omits the normal bolt's special-state
bracket, so it is not the player-primary style.

`Anim_SpellGlow` uses action `0x18`, source scale `1 + Random(0.5)`, and angle
`Random(360)`. Its render dispatches to `0x00536380`. The contact
`Anim_FadeLightning` starts at alpha/lifetime `1`, uses float32 decrement `0.2`
at `0x00784CE8`, advances its corona angle by `1` per tick, and dies after the
five renderable levels `1.0, 0.8, 0.6, 0.4, 0.2`. Its position is the endpoint
plus a random radial offset with magnitude `Random(10)` and its uniform scale
is `1 + Random(0.5)`. Chain contacts can use a `0.2` pre-scale and decrement
`0.4` in the low-detail/actor-flag branch.

`0x00536380` draws four additive cyan-white circular quads. Although the
registered BadGuys array has sibling records `110`, `111`, and `112`, all four
draw sites at `0x005364FB`, `0x005365DB`, `0x0053668C`, and `0x0053678B`
check the first entry and pass the same record-`110` pointer at BadGuys object
`+0x46BC` to `0x00414EA0`. Records `111` and `112` are used by
adjacent effects, not by this Air painter. The circle pulse is
`(abs(sin(angle * 15 degrees)) * 0.15 + 3.5) * objectScale`; relative scales
are `1`, `0.75`, `0.5`, and `Random(0.2) + 0.2`. RGB is
`(0.5,0.75,0.75)`; alphas before object fade are
`Random(0.25) + 0.2`, `0.5`, `0.5`, and `0.25`.

Record `110` is `27x26` with `(0,0)` registration. With object scale
`1..1.5`, its largest circle is `94.5..147.825` pixels wide and
`91..142.35` pixels high before the contact's sub-`10` jitter and five-object
held overlap. The large corona is therefore numerically stock-consistent even
though the clean source-only capture does not visually accept an endpoint.
The extracted record hashes are `44`
`a940b0b66118b81df6199bea4361558c3037d57630f1329ff780d1254adc4438`,
`110` `681388cc79153506329c762cb8d3ec0b5cd629d1e6098b86597d629a63ddd882`,
and forks `1836..1839`
`1cfac650a02c2bdee9575afd391b79535df2b3e7c64764016314ec11f218c1db`,
`e43e83ff7fd834aee563dd7a8fc3781a24ddb094cf34d49215cee2ab40444c10`,
`14ebfbe91ebf1c09d122d3f5274d96c72012e6ebdf16ad8fc49b56cee0e2c8c1`,
and `90723bedc696c964165ed6e06d32f9834118f04ab53821d047d48ee3826a99da`.
The painter then chooses two fork glyphs from exact records `1836..1839`; the
second index is `3 - first`, so record ids sum to `3675`, and its rotation is
the first plus `90` degrees. The attached `ZAnimLit` mapping is closed by the
Air constructor writes at `0x00540072..0x005400F8`, tick `0x005FD1D0`, and
provider `0x005E48E0`: field `+0x140` is radius
`1 + Random(0.75)`, `+0x144` is intensity starting at `1`, `+0x148` is the
float32 per-tick intensity delta `-0.05`, and local Multiple Shadows byte
`+0x14C` is `0`. The provider passes `min(intensity, 1)`, radius, the followed
child position, and `localMultipleShadows & DAT_00B3BCAA` to Region. Air's
source is therefore always `multipleShadows=false`, shares the contact
corona's sub-`10`-unit jittered position, and has radius on the inclusive native lattice `[1,1.75]`. Float
`50` at `0x00784CF8` is written to Puppet painter sort field `+0xA0`, not to a
light range. Region expands the radius with its existing inner `75` and outer
`145` distance constants; no separate Air decay or `50`-unit range exists.

These are three separate world registrations: `ZAnimSplit` owns the bolt body,
`Anim_SpellGlow` owns the source corona, and `Anim_FadeLightning` owns the
contact corona. A browser renderer must give them independent painter roots at
body midpoint Y, source Y, and jittered endpoint Y. One midpoint-sorted parent
changes stock occlusion whenever another world object lies between them.
They also bypass inbound Region tint: `ZAnimSplit` draw vcall `0x005E0230` and
the `ZAnim`/`ZAnimLit` child draw vcall `0x005E01E0` do not traverse the common
Puppet local-light dispatcher. The outbound contact `ZAnimLit` source is a
separate relationship and must be sampled at its jittered contact position.

A loader-free retail capture in an isolated Wine/Xvfb prefix used copied
`Game.FastCPU=false` settings, selecting the explicit Off / `30`-unit path
above rather than the shipped new-profile default. The
60-fps, 132-frame hold at
`/tmp/sdr-stock-vfx-probe.9l2URj/stock-air-held-v2.mp4` (SHA-256
`bd0fcc847fbc346cb4bd6b88cf602fcf1c679d24c68d91b065f0518da8907f10`)
shows the raised staff and sustained cyan-white source glow. It never acquires
or clips an endpoint that materializes a body/contact object, so it supports
source-glow ownership only and must not be cited as visual acceptance for the
ribbon or endpoint corona.

The adjacency sweep found five direct `0x00531640` calls: two Skeleton Mage
paths in `0x00490860`, the player primary and its chain branch in
`0x0053F9C0`, and `Mod_ElectricBurn` `0x00628F10`. `StormCloud` `0x006021A0`
constructs `Anim_LightningBolt` directly. `Anim_FadeLightning` is also reused
by Ball Lightning impacts, StormCloud, and ElectricBurn. Those xrefs establish
a reusable lightning presentation family; they do not turn the player primary
into a gameplay missile.

Focused read-only Ghidra transcripts are preserved at
`/tmp/sd-air-ghidra-tessellator-20260814.log` (SHA-256
`79d830e17beef1737aefe0eb9a9e22321c2d19a7ccb1337dc436ddb8c7e43f47`)
and `/tmp/sd-air-ghidra-corona-20260814.log` (SHA-256
`0896a025f6b3a200d0cf35409ef263e6930b41615685ed3af59ed39455d79854`).
The follow-up cadence/default and `ZAnimLit` field audit used the same exact
retail executable and read-only Ghidra 12.0.3 replica
`ghidra_project_replicas/slot-06`; its direct instruction ranges are listed
above so the field and float-store sequence can be reproduced without a live
runtime.

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

For each particle, query width and particle direction are distinct operands:

```text
queryWidth   = mWiden + 15                         // rank 1: 15 degrees
castSpeed    = effective Water-class cast speed    // neutral rank 1: 1 degree
phase        = worldTick + ordinal * float32(65 / count)
heading      = casterHeading + sin(phase * 65 deg) * castSpeed
spawn        = exact Staff socket
             + U[0,10] * unit(casterHeading +/- U[0,45 deg])
speed        = 4 * (1 + (mWiden / 2.5) * 0.05)    // rank 1: 4/tick
lifetime[0]  = 1.25 + U[0,0.05]
lifetime[n]  = lifetime[n-1] - 0.04
```

When a tick creates two particles, the handler advances the pre-multiply phase
accumulator by `65 / count` before the second sample. This oscillating stream is
independent of the rank-1 `205`-unit cone reach. Particles move only about
`128`-`132` world units before expiry; the native visual does not interpolate
to the gameplay endpoint.

The phase advance is explicit in the handler instructions:
`0x005439D0..0x005439DA` loads the particle count, divides constant double
`0x00784D90` (fresh raw value `65`) by it, and stores the local step. The Over
and Normal branches consume the mutable phase at `0x00543A86` and
`0x00543BA3`; loop tail `0x005440A2..0x005440AE` decrements the count and adds
the stored step before the next creation. The accumulator is multiplied by
`65` only after that addition. Enhanced Effects On therefore gives the second
particle `32.5` accumulator units, or `2112.5` degrees modulo the sine, rather
than a merely 32.5-degree-ahead sine input.

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
| `+0x40` core scale | `S = 0.5 + U[0,0.75]` | if lifetime `< 1`, add `0.009999999776482582` |
| `+0x44` glint scale | `Q = (2 + U[0,1]) * S` | if lifetime `< 1`, multiply `0.95` |
| `+0x48` color ramp | Normal `1 + U[0,0.10000000149011612]`; Over overrides it to `0` | subtract `0.07500000298023224`, clamp at zero |
| `+0x4C` opacity multiplier | `1` | unchanged |

These three non-round values were re-audited from instruction width and raw
bytes after the integrated browser receipt exposed a cyan full-screen wash.
`0x004537E6` is `DC 05 08 4D 78 00`, so its operand is the QWORD bytes
`00 00 00 40 E1 7A 84 3F` = `0.009999999776482582`, not the low-DWORD float
`2`. `0x004537B1` is the same QWORD form over bytes
`00 00 00 40 33 33 B3 3F` = `0.07500000298023224`. The constructor at
`0x00453622` uses `D9 05` and therefore correctly reads the DWORD bytes
`CD CC CC 3D` = `0.10000000149011612`. This operand-width correction
supersedes the earlier `+2`, `-2`, and `U[0,0.5]` transcription.

The complete presentation-constant width audit is:

| Address | Storage | Exact value | Native role |
| --- | --- | ---: | --- |
| `0x007849F0` | DWORD | `0.05000000074505806` | lifetime random bound; Normal phase step |
| `0x00784740` | QWORD | `1.25` | lifetime base |
| `0x007DE934` | DWORD | `0.75` | additive alpha; core-scale random bound |
| `0x00784E7C` | DWORD | `0.03999999910593033` | lifetime decrement |
| `0x007DE808` | QWORD | `0.5` | core base; Over phase factor; wall-splay speed factor |
| `0x007DE838` | QWORD | `2` | glint-scale base only |
| `0x007845E8` | DWORD | `0.10000000149011612` | color-ramp random bound |
| `0x007DE8A0` | QWORD | `0.05000000074505806` | additive-alpha decrement |
| `0x00784EA8` | QWORD | `0.07500000298023224` | color-ramp decrement |
| `0x00784E20` | QWORD | `0.949999988079071` | late-life glint shrink |
| `0x00784D08` | QWORD | `0.009999999776482582` | late-life core growth |
| `0x00784970` | QWORD | `0.8999999761581421` | Normal glint opacity gate |
| `0x007DE910` / `0x007DE8F0` | QWORD | `3` / `0.25` | glint offset/Over alpha; Over scale |

Every persistent field is rounded by its `fstp DWORD` store. Bounded random
results are therefore float32 before constructor addition/multiplication;
velocity and position are float32, position advances iteratively, the Normal
`L * L` alpha local is float32 before the minimum, and each glint-offset
multiply/add is stored through float32. A closed replay cannot replace these
steps with one `origin + velocity * age` expression.

The core tint is `(max(0, 1 - colorRamp), 1, 1)`: Normal starts cyan and
restores red gradually over roughly 14-15 updates; Over is white from
construction. Both renderers pass the native heading to the registered sprite
draw and restore ordinary blending/white afterward.

The rank-1 classes also share update ownership exactly. Normal vtable
`0x00784E84 + 0x08` and Over vtable `0x00784EB4 + 0x08` both contain
`0x00453670`. Nearby function `0x00453870` calls that updater and then
subtracts `0.01` from core scale, but its sole data xref is vtable slot
`0x00793D7C`; constructor vptr write `0x00541870` identifies that table as
`Anim_FrostJetEffect_Chaining`. It is not the Over updater. Importing its
post-update shrink into rank-1 Over would cross a learned-spell class boundary.

Normal render `0x00457720` submits three ordered draws:

1. ordinary alpha, `BadGuys[30]`, particle position, scale `S`, alpha
   `min(lifetime^2, phase)`, cyan-to-white tint;
2. while `+0x3C > 0`, additive `BadGuys[30]` at the same transform, scale
   `0.5*S`, alpha `+0x3C`; and
3. while opacity multiplier `M = +0x4C` is at least
   `0.8999999761581421`, additive `BadGuys[28]` at
   `position + 3*velocity`, scale `min(Q,1)`, alpha
   `M * min(10*lifetime,1)`.

Over render `0x00457A00` omits the half-core draw:

1. ordinary alpha, `BadGuys[30]`, scale `S`, alpha
   `0.5*min(lifetime,phase)`, white; then
2. additive `BadGuys[28]` at `position + 3*velocity`, scale `0.25*Q`, alpha
   `min(3*min(0.5*phase,lifetime),1)`.

The draw-state byte set to `1` resolves through `0x004208A0` to D3D
`SRCALPHA, ONE`; zero is ordinary `SRCALPHA, INVSRCALPHA`. Normal enters a
`ZAnim` transient Y-sort queue; Over enters a direct Region ObjectManager and
draws later. Both call the child renderer directly and bypass the common
local-light dispatcher. They are not screen overlays.
`Text_Draw` at `0x00415130` writes the submitted scale directly to all three
matrix diagonal entries; `0x00414540` then transforms the registered
pixel-space quad. There is no texture-dimension normalization. The renderer's
float local color uses the restored white multiplier before final byte
quantization. A web renderer must not pre-quantize the cyan-to-white float tint:
it must multiply first, then truncate each final channel rather than round it
when packing the submitted color.

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
motion, contact separation, audio, and teardown. The second pass below closes
the browser terrain-query seam for cosmetic Normal wall splay. Still open are
a clean-stock On/Off pixel receipt and the exact per-session RNG sample
sequence. Deterministic web samples
may preserve the recovered random distributions using authoritative spell
identity, but must not be presented as the retail RNG sequence. The born
direction is not identity-derived: authority must evaluate the native
world-tick phase plus the per-tick particle ordinal, while radial spawn jitter
remains relative to the caster's un-wiggled base heading.

### 2026-08-14 second-pass Water adjacency and ownership audit

The Website's fresh isolated `origin/main` baseline produced 65 healthy live
Water transients, the expected pose/facing, and balanced ice-loop ownership,
but rendered a broad cyan cone. A renewed handler pass identified the cause:
the first implementation treated `mWiden + 15` as particle-heading amplitude
and added the intra-tick step after converting world time to degrees. Neither
matches the executable.

At `0x00543895..0x005438AF`, the handler calls `0x00656580` with Water class
index `3` and saves its return at stack `+0x68`. The helper computes the
effective Water-class cast speed from progression fields:

```text
(progression[+0x6AC] * progression[+0x94] + progression[+0x6B0])
  * progression[+0x6B4 + class*4]
  + progression[+0x6D4 + class*4]
```

and clamps it at zero. The neutral rank-1 fixture has the already recovered
`progression[+0x94] == 1` and no equipment/skill modifiers, so the visual
amplitude is one degree. `mWiden + 15` is instead consumed by cone acquisition
and the particle-count expression.

The full heading sequence appears twice. Over
`0x00543A86..0x00543AD6` and Normal `0x00543BA3..0x00543C5C` load the mutable
phase, multiply QWORD `0x00784D90 == 65`, multiply runtime float pi at
`0x00B4027C`, divide QWORD `0x007DE888 == 180`, take sine, multiply the saved
effective cast speed, add caster heading, and call `0x00453800`.
`0x005439C9..0x005439CC` initializes phase from float32 world tick;
`0x005439D0..0x005439DA` computes/stores float32 `65 / count`; loop tail
`0x005440A2..0x005440AE` adds that step before the next particle. This closes
the neutral formula as:

```text
heading = casterHeading
  + sin((float32(worldTick) + ordinal * float32(65 / count)) * 65 degrees)
  * 1 degree
```

#### Range, target/obstruction ownership, and alternate branch

- `0x00641B10` builds a heading-centered angular wedge from half-width and
  squared reach, enumerates spatial candidates, excludes hidden/self/type
  failures, and keeps all eligible actors rather than a single nearest target.
  Rank-1 player Water supplies reach `205`, width `15`, and mask `0x1082`.
- Each candidate is independently checked by `0x00524D70`; only a clear
  line continues to push/status/damage. That helper returns the nearest line
  collision under its mask. Gameplay contact is immediate and independent of
  the visual object's motion or expiry.
- Normal visual birth separately calls `0x00524D70` with mask `0x380`. It
  predicts from the caster actor position, not the jittered Staff socket:
  `steps = float32(lifetime / 0.04 + jitterRadius)` and
  `end = caster + steps * velocity`. A hit is stored only if it is in front of
  the jittered born position. Shared update subtracts current speed from the
  remaining distance; after crossing zero it snaps to the point, replaces
  velocity with a randomly signed perpendicular at `0.5` magnitude, clears
  the pending hit with the large sentinel at `0x00784E78`, and advances once
  with that new velocity. The born heading field remains unchanged. Over never
  performs this visual obstruction setup.
- The distinct bot/alternate caller emits Normal only with cast speed `0.5`,
  zero widen/push, reduced density with a minimum of one, opacity multiplier
  `0.25`, and acquisition mask `2`. Those are caller-owned differences, not
  player rank-1 defaults.

#### Negative adjacency proof

Raw code/data xrefs close the apparent missing-effect family:

- `0x00453550` is reached by player Water, Water+Air, and the Over constructor;
  `0x00453840` is reached only by player Water. Heading initializer
  `0x00453800` is shared with Water+Air and Steam, but those callers own their
  own subclasses/records.
- Normal vtable `0x00784E84` and Over vtable `0x00784EB4` both point at shared
  update `0x00453670`; their render slots point at `0x00457720` and
  `0x00457A00`. `0x00453870` occurs only in vtable `0x00793D74`, whose
  constructor write at `0x00541870` belongs to `Anim_FrostJetEffect_Chaining`
  under Water+Air. It is not an Over update.
- Hail constructor `0x00454030` and record 32, and Cold Aura constructor
  `0x0045AF20` and record 14, are learned Water branches reached from their
  progression guards in the same handler. Record 31 at `+0x17F4` belongs to
  `Anim_BlizzardBeam` render `0x00458470`; adjacent record 29 belongs to
  Heartmonger. None is a rank-1 source/contact/terrain sprite.
- Player Water enters `0x00543860` only from sustained dispatcher
  `0x00548A00`; release simply stops subsequent query/emission. The common
  world transient queue owns Y order, local Region lighting, expiry, and
  teardown. Rank-1 has no point light and no hit sound beyond registry 44
  `icestart` plus owner-held registry 161 `iceloop`.

Implementation consequence: correct the heading recurrence at authoritative
birth and snapshot a nullable Normal obstruction point resolved against the
authoritative Hub/Boneyard static collision model. Presentation must replay the
snap/perpendicular/half-speed recurrence while keeping sprite rotation at the
born heading and the glint lead on current velocity. The base registered
record set remains exactly 30/28; adding an invented source, impact, or terrain
sprite would cross class ownership. Open items remain the exact retail RNG
sequence and clean-stock Enhanced Effects On/Off pixels.

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

### Exact actor-contact retention, shrink, and fragment program

The 2026-08-21 contact-lifecycle reopening corrects an incomplete earlier
closure. The prior pass recovered the target list and pool arithmetic but
stopped before the downstream instructions at `0x006212E5..0x00621365` and
therefore did not carry the surviving actor's shrink, retained-shell rewrite,
or one-fragment contact child into the Website. Fresh read-only Ghidra 12.0.3
decompilation and raw instructions against the same retail image establish the
complete sequence.

Release finalizer `0x005E5450` leaves the release-base damage `B` at `+0x1F8`,
writes the quadratic released pool `P` at `+0x1F4`, and replaces `+0x1FC` with
the actual released charge ceiling `C_release`. At the start of every flight
tick, `0x00609D30` copies the pre-contact charge to `+0x1F0`. The query then
uses the pre-contact radius `75*C`, mask `0x6`, and native candidate order.
For each eligible handle absent from the `+0x200` list:

```text
payload = min(target_current_hp, P)
spent   = payload                       when P < target_current_hp
        = payload / (2 * toughness)     otherwise
P'      = max(0, float32(P - spent))
C'      = float32(min(C_release,
                      C_release * (1 - (1 - P' / B) * 0.35)))
```

The division and `0.35` expression remain in x87 precision until the final
float32 store to `+0x74`. A zero release base with a positive residual produces
positive infinity and the following minimum retains `C_release`. A zero release
base whose contact also reaches zero pool instead produces x87 NaN; the
unordered compare takes the candidate branch and stores that NaN before the
terminal path restores the saved finite charge. Target insertion through the
`+0x200` list vslot occurs after contact dispatch. `0x0060BC10` then creates
exactly one independent `Anim_BoulderBit` from `BadGuys[2008..2010]` using
`C'`; this happens for every accepted actor contact, including the contact
which later exhausts the pool. A strict JSON replication layer cannot carry
the pathological NaN child's transforms; a web port can preserve the exact RNG
budget and finite full breakup while explicitly omitting that unrenderable
registered child, but must not label a finite clamp as native.

The double `0.001` at `0x0079E260` is only the same-tick traversal stop:
`P' <= 0.001` skips later candidates. It is not the retirement threshold.
Post-contact helper `0x005FA4B0` removes the actor only when `P' <= 0` and the
actor is not already pending removal. A positive sub-threshold pool therefore
survives and can meet another target on a later tick.

For a survivor, `0x005FA4B0` visits every retained Rock and calls vector-length
helper `0x004029A0` with `30*C'`. The existing rock count, record variants, and
stored scales remain unchanged, while every noncentral local XYZ vector is
renormalized to the smaller radius. The helper then writes body bounds
`500*C'` and collision radius `75*C'`. The aura, visual-root offset, painter
bias, outbound light range, next-tick roll divisor, and next-tick query radius
all consume the same reduced charge.

If the pool reaches zero, the virtual `+0x6C` terminal path restores the saved
pre-contact charge from `+0x1F0` before creating the full breakup. Ordinary
`Boulder` uses `0x0060B700`; `EBoulder` overrides it with `0x0060BED0`, which
adds its Ether fade and independently registered BoulderBit family before
removal. Thus a contact can visibly shed one rock and continue, or emit that
one contact rock followed by the full terminal breakup; actor contact is not
an unconditional pierce count or an unconditional first-hit explosion.

The complete shared-function membership is:

- ordinary `Boulder 0x7D5`: direct vtable data reference at `0x0079E078`;
- `EBoulder 0x7E1`: override `0x00621450` calls `0x00620B60`, then owns its
  target steering/countdown and terminal `0x0060BED0`;
- `Hailstones 0x7E4`: the inherited vtable contains the second direct data
  reference at `0x0079E168`, but released Hail dispatches its independently
  recovered per-rock substep/contact owner `0x005FBDE0`; it does not consume
  this whole-carrier residual-pool result in the reachable released path.

No authored contact table or setting-dependent gameplay branch exists here.
Enhanced Effects gates the airborne BoulderBit shadow draw, not pool damage,
target memory, shrink, or retirement. Contact emits no new one-shot audio;
the moving actor retains its rolling-loop owner until terminal removal. Both
ordinary `0x0060B700` and EBoulder `0x0060BED0` then play registry 77
`sounds\\rockhit` (`+0xD54`) at pitch `1 + 0.05/charge` with positional gain
multiplied by charge, followed by registry 89 `sounds\\stonebreak` (`+0xF64`)
at pitch `1 - 0.5*charge` with ordinary positional gain.

### Construction, called rocks, draw order, and breakup

The 2026-08-14 second two-pass presentation audit corrects one remaining
mistake in the first reconstruction: Boulder owns **two** center overlays, not
one. `BadGuys[15]` is the persistent green-white aura attached to the assembled
Boulder. `BadGuys[86]` is only the short additive opening flash. The visible
body is a native collection of individual `Boulder::Rock` records. The pass
used Ghidra decompilation of `0x005FA270`, `0x00609D30`, `0x005E5450`,
`0x005FE430`, and `0x0060AC40`, then independently checked the relevant PE
instructions around `0x00609D30`, `0x0060AC40`, and dispatcher `0x00544C60`.
The asset-object join independently maps object offset `0x0BB4` to record 15
and `0x4210` to record 86. This corrects the former single-overlay model rather
than layering a guessed extra effect onto it.

Dispatcher `0x00544C60` owns one cached Boulder actor. While held, it resamples
the current player world aim and staff socket on every tick; there is no enemy
target selection or projectile homing. Release freezes the last sampled
direction and assigns straight speed `3`. No fixed distance or flight lifetime
exists in the actor. Contact/removal, world teardown, or owner teardown end its
range. A web-only 500-tick containment must therefore not remove Earth.

Draw `0x0060AC40` first adds a shared-random displacement of magnitude
`random(0,3)` in a random unit direction to the complete visual assembly. Its
visual origin is
`actorY - (Boulder+0x1D4)*charge*0.75 + (Boulder+0x1E0)`. Constructor field
`+0x1D4` is `30`, while held tick writes `+0x1E0=-20-10*charge`, yielding exact
local Y `-20-32.5*charge`. The Boulder actor and Region-light sample remain at
the authoritative actor XY; only the composed visual moves. Tick instructions
`0x0060A548..0x0060A55E` set painter bias to
`-(+0x1E0)*charge*1.5 = (20+10*charge)*charge*1.5`.

The persistent record-15 pass at `0x0060ACD0..0x0060AE04` uses color
`(0.9,1.0,0.9)`, alpha `random(0,0.25)+0.35`, and scale
`4.099999904632568*charge`. It remains present in held and flight phases. The
record-86 pass at `0x0060B1BC..0x0060B2B3` is additive white, uses alpha
`opening_mix`, scale `2.5*opening_mix`, and rotation
`global_render_tick*6` degrees. The body alpha is `1-opening_mix`. Record 15 is
the missing stock "on-boulder" effect; assigning its `4.1*charge` scale to
record 86 is instruction-false.

Exact extracted record 15 is 38 x 37 pixels, SHA-256
`5abc42fa09f09a5fefe3df9281d2102e6b93a48249edb4e21f36f73e1a0011eb`.
Record 86 remains 94 x 94. Both are children of the Region-lit Boulder painter
root and inherit its sampled tint; neither is an independently registered
actor or outbound-light source.

The machine-readable address/field/constant/art join is
[`earth-boulder-vfx-catalog.json`](earth-boulder-vfx-catalog.json).

`Boulder + 0x13C` owns a
`PointerList<SmartPointer<Boulder::Rock>>`; backing storage is at `+0x150`.
Each 0x3C-byte Rock holds local XYZ at `+0x00..+0x08`, draw-transformed XYZ at
`+0x0C..+0x14`, scale at `+0x18`, and a sprite variant at `+0x1C`.
The constructor installs `Boulder::vftable` `0x0079E014` and initialization
dispatches vslot `+0x68` (`0x005FE430`) once at constructor charge `0.18`.
Tick `0x00609D30` compares `floor(30*old_charge)` with
`floor(30*new_charge)` and rebuilds only when that bucket changes. The native
Rock collection is consequently stable between rebuild ticks. Charge continues
to interpolate for the aura/root offset and gameplay radius, but body count,
local XYZ, variants, stored scales, and central scale use the last authoritative
assembly charge. Recomputing the shell from every interpolated charge is not a
native growth animation; it makes rocks breathe and drift between births.

`0x005FE430` replaces the collection as one cohesive shell:

1. It creates a central variant-3 Rock at local `(0,0,0)` with scale
   `4 * charge`. Variant 3 selects `BadGuys[171]`, the 17 x 17 center pebble.
2. It calls `0x00411400` with `n = 30 * charge` and radius
   `r = 30 * charge`. The loop emits `ceil(n)` points. Its algebra is the
   deterministic Fibonacci sphere
   `y = 2*i/n - 1 + 1/n`, `theta = i*pi*(3-sqrt(5))`, normalized and scaled to
   `r`; this is not random scatter.
3. Each shell point chooses native integer variant `0..2`, mapping to
   `BadGuys[168..170]`. Its scale is
   `min(1, (random(0,0.75)+0.5) * min(charge,1))`.

The initial charge `0.18` therefore produces six shell points plus the central
pebble; exactly `0.3` produces nine shell points plus center, while the observed
float32 release row `0.3012498915` produces ten plus center; full charge
produces 30 shell points plus center. Variant and scale samples use the shared
native RNG, but count, positions, radius, charge thresholds, and collection
replacement are deterministic.

Held orientation is also native state, not a flat sprite spin. Constructor
field `+0x70` is float `3`; `0x00609D30` multiplies it by double `0.25` and
passes `0.75` degrees per tick with axis `(0,-0.8,1)` to matrix helper
`0x00403340`. That helper normalizes the axis. The matrix advances only while
held and is preserved unchanged after release.

Construction also owns separate inward particles. While held and below full
charge, `0x00609D30` creates an `Anim_CalledRock` every tick below charge
`0.25`; at later charge it does so when `randInt(0,2) == 1`. The constructor is
`0x00453890`, vtable `0x00784EE4`; tick `0x00457FF0` and draw `0x0045E440`
are slots `+0x08/+0x0C`. A called rock:

- chooses lit variant `0..2` from `BadGuys[2008..2010]`, not the main body
  bank;
- starts at a random direction/radius around the live Boulder whose sampled
  upper radius is `clamp(50*charge,5,120)`, then homes toward the same actor
  identity;
- starts at speed `0.1`, multiplies speed by `1.1` per tick, caps at `5`, and
  self-removes inside five world units;
- uses scale `0.75 * min(charge,0.75)`, initial perspective height `-2`, and
  target height `boulder[+0x1E0] - 20 - 20*charge + random(0,5)`. Held tick
  sets Boulder `+0x1E0 = -20 - 10*charge`, so this simplifies to
  `-40 - 30*charge + random(0,5)`; height moves toward that target by exactly
  `1.5` per tick;
- adds a per-tick perpendicular vector after the homing step: `0x0074704A`
  converts the updated rock-to-parent vector to an angle, native radians-to-
  degrees conversion adds `90`, and the constructor's fixed `random(0,4)`
  magnitude is applied at that heading. It does not consume another RNG sample
  each tick. Initial rotation is `random(0,360)` and advances by the fixed
  constructor sample `random(-30,30)` each tick; and
- switches to its fall branch on the first tick that observes the parent is no
  longer held. In that branch perspective height adds fall velocity, velocity
  adds `1`, positive height forces velocity to `0.25`, and the actor removes
  only once height is greater than `10`. There is no twelve-tick fall, alpha
  fade, fixed travel lifetime, or renderer-reconstructed birth history.

The called-rock actor stores absolute world position and a pointer to the
same Boulder identity. It is inserted directly into the world's animation
collection at `Region + 0x278`; its vslot `+0x0C` is the full renderer
`0x0045E440`, not `Puppet_RenderDispatch (0x00624B40)` and not a
`ZAnimLitObject`. Its main sprite therefore does not sample inbound Region
light through the common dispatcher. The optional enhanced-effects auxiliary
sets black and then restores white before the main lit-bank sprite. Called
rocks are independent painter roots at their own absolute position, with no
outbound light role.

Optional adjacent branches emit `BadGuys[18]` fade/dust and loose
`Anim_BoulderBit` pieces. They are sibling cosmetic actors registered with the
world; they are not entries inserted into the persistent main shell.

Main draw vslot `+0x1C` at `0x0060AC40` transforms every Rock's local XYZ by
the Boulder matrix at `+0x154`, keeps only strict `transformed_z > -40.0`,
sorts survivors by transformed Z, and draws `BadGuys[168 + variant]`.
Constructor helper `0x00402CC0` initializes that matrix to identity, including
zero translation. Rank-1 local shell radius is at most `30`, and the held
update is a pure rotation, so its transformed Z stays in `[-30,+30]`: the
`-40` depth-plane branch cannot cull a valid rank-1 main Rock. The browser
still applies the predicate because it is part of the native draw contract.

Projection helper `0x0043A8A0` is only two float loads/stores: it copies the
transformed X and Y fields and never reads Z. Z therefore controls culling and
sort order only; it contributes no perspective displacement or registration
offset. The sprite is registered at the Boulder actor transform plus that
orthographic XY offset. Draw also clamps every main Rock's stored scale to a
minimum float32 `0.44999998807907104` (`0x00785370`; the comparison double at
`0x00786C88` has the same value). This preserves a rotating 3D pile rather
than a flat rotating bitmap or perspective projection. The opening mix at
`+0x1EC` starts at `1` and loses `0.035` per native tick: record 86 draws
additively with alpha `mix`, scale `2.5*mix`, and global-frame rotation `6`
degrees per render tick, while the rock collection draws with `1-mix`. Thus
the opening flash fades out as the assembled body fades in; it never becomes
the body. Record 15 remains behind the body at `4.1*charge` with its independent
`[0.35,0.60]` alpha sample. No direct
`BadGuys[67]` shadow reference exists in this draw method; generic world
lighting/tint remains a sibling renderer concern.

Release finalizer `0x005E5450` flips the adjacent held/flight bytes at
`+0x1DC/+0x1DD` and preserves actor identity, shell records, charge, matrix,
and direction. Flight remains straight at speed `3`; `0x00620B60` owns the
per-tick terrain/actor contact. At `0x00620C2D` it commits the velocity step to
the actor's `+0x18/+0x1C` position before issuing the world and actor contact
queries. A terminal breakup is consequently registered at that advanced
contact sample, not the prior clear position. Breakup vslot `+0x6C` at
`0x0060B700` restores the saved charge and emits
`floor(max(8, 30*charge))` randomized `Anim_BoulderBit` actors from the lit
`BadGuys[2008..2010]` bank. Let `q=min(charge,1)`,
`r=max(8,30*charge)`, and `step=360/r`. The first direction angle is
`random(0,360)`; each emitted fragment advances it by
`step + random(-step/3,+step/3)`. Direction Y is multiplied by `0.8` before
both placement and velocity. Each fragment then uses these exact independent
domains and recurrences:

- constructor perspective velocity and its retained bounce seed both start at
  `-(random(0,3)+2)`, then breakup multiplies both by
  `random(0,1.5)*q+0.75`; initial perspective height is
  `-random(0,50*q)`;
- radial placement is `random(0,45*charge)` along the flattened direction;
  velocity multiplies that direction by `random(0,1.5*charge)+1.5`;
- draw scale first compares `(random(0,0.75)+0.5)*charge` with exact float32
  `0.44999998807907104`. When it passes, native consumes a second independent
  `random(0,0.75)` for the selected value; otherwise it selects the floor. It
  then multiplies by `0.6499999761581421` and caps the result at `0.75`;
- initial rotation is `random(0,360)` and initial rotation step is
  `random(0,10)+1`. Base tick `0x00456720` tests perspective height `+0x38`
  before its global-tick modulus. While that motion lane is nonzero, ticks
  divisible by three skip motion, gravity, rotation, and the base alpha
  decrement. Other active-motion ticks add velocity to XY, perspective
  velocity to height, `0.4` to that velocity, and the current rotation step to
  rotation. Crossing height zero rerolls rotation step in `1..11`, multiplies
  both the current perspective velocity and retained bounce seed by `0.3`,
  applies a 50-percent horizontal velocity damping of `0.65`, and stops all
  motion/rotation when the new perspective velocity is greater than `-0.75`.
  That stop writes height zero, which bypasses the modulus branch thereafter;
- base alpha starts at `2`, or `10` when Enhanced Effects is enabled. The
  subclass subtracts float32 `0.025` after every completed base call. An
  active every-third tick therefore loses only `0.025`; other active ticks and
  every settled tick also lose the base float32 `0.015`, for a two-subtraction
  total of `0.04`. Removal occurs when the resulting alpha is no longer
  positive. Draw clamps visible alpha to `1`.

`Anim_BoulderBit` vslot `+0x0C` is its child draw `0x00457E40`, but the child
is wrapped in a separately registered `ZAnimLitObject` whose vslot `+0x0C`
`0x005E03A0` calls `Puppet_RenderDispatch`. The wrapper copies the fragment's
absolute XY and sets its painter/sort offset `+0xA0` to `-15`; it samples
inbound Region light at that position before calling the child. This wrapper
has no ZAnimLit intensity/range fields and emits no outbound light. The
Boulder body likewise enters `Puppet_RenderDispatch` through vslot `+0x0C`
and samples Region light at its own world position. After all fragment
wrappers are registered, the Boulder removes itself. The Boulder body also
owns a separate outbound provider:
vslot `+0x30` `0x005E5670` submits its actor root with radius
`max(1,2*charge)`, intensity `0.5`, and the retail Multiple-Shadows flag. The
inbound Puppet dispatcher and outbound provider are independent ownership
lanes; the wrapper observations above do not negate that provider.

The exact shared native RNG seed and interleaving with unrelated actors remain
unrecovered. Those visual choices must not become authoritative gameplay RNG
in the browser: stable spell/particle identities and independent sample lanes
must reproduce the instruction-backed domains and angle recurrence for all
observers. By contrast, called-rock absolute position/release/fall state and
impact birth tick are authoritative presentation state. The authority must
publish and retain them long enough for sparse snapshots and late observers;
a renderer must not recreate historical emissions from Boulder age or infer
breakup from disappearance.

The static source is the 4,723,200-byte preserved executable SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`,
reanalyzed read-only with Ghidra 12.0.3 from
`Decompiled Game/ghidra_project/SolomonDark.gpr`. Desktop ownership prevented a
new clean-stock run. Historical instrumented observer frame
`/mnt/d/codex-evidence/spell-fx-20260726/investigation/boulder-observer-trace/earth/client_casts/cast-01/chosen-host.png`
(SHA-256
`c0893564eb55353b02f28b9e70b97350f0ab1be6b6efa2b82df864ae99b5595b`)
corroborates the multi-rock cluster at the live staff/hand emitter with the
bright glimmer behind it. It is composition/attachment evidence, not a clean
timing or count oracle.

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
| Ether missile | compositor `0x00535A30`, `BadGuys[110..112]`; contact-only `BadGuys[53]` | radial two-pass gameplay-actor body at `(x,y-10)`, world-queued; record 53 is emitted only by a surviving-pierce contact |
| Fireball | core `BadGuys[110]`; main `BadGuys[255..266]`; cosmetic trail `BadGuys[267..270]` | main frame `(age_ticks / 3) % 12`: 3 ticks/frame, 36 ticks/cycle; one separately registered `Anim_FireParticle` transient is born per Fireball tick |
| Air lightning | ribbon texture `BadGuys[44]`; all four corona circles use `BadGuys[110]`; fork glyphs `[1836..1839]` | two independently tessellated additive ribbons at `0x00534510`, body lifetime `2`; separate source glow and endpoint fade lifetime `5`, alpha minus `0.2` per tick; three independent world painter roots |
| Frost Jet | `BadGuys[30]` and `[28]` (core and forward glint only); `[32]` Hail and `[14]` Cold Aura are learned branches | one transient/tick with Enhanced Effects Off or two/tick with it On; each moves at rank-1 speed `4` and remains about 32–33 ticks |
| Boulder | opening glimmer `BadGuys[86]`; main rock collection `[168..171]`; called-rock/breakup bank `[2008..2010]`; optional dust `[18]` | crossfade glimmer to a charge-sized, matrix-transformed, depth-sorted multi-rock shell; called rocks home inward; impact fragments are separate lit actors |
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
`0x0060AC40`), the Fire Missile render path (`0x006099C0`), the Lightning
factory (`0x00531640`), ribbon constructor/builder/render
(`0x0045B2C0`/`0x00534510`/`0x004575D0`), and corona path
(`0x00452E20`/`0x00476230`/`0x004572C0`/`0x00536380`). Their dispatch,
constants, actor ownership, and render families agree with the durable goldens
and tables above.

### Shared cast actions and emitter

- A world-surface left-button level enters the selected element's primary
  action. Ether and Fire consume its press edge once. Air, Water, and Earth
  consume the held level; Earth additionally consumes the release edge.
- Ether and Fire use `Staff Cast 1`, mode 3 action `0x0044B170`. Its observed
  fixed-tick pose branch is insertion `K=0`, then `1`, `8`, `7`, and reset
  `0`; the alternate RNG branch starts at `8` and then joins `7`. Movement does
  not cancel the queued action. Death does. Releasing a short click does not
  rewind it. The one-shot emission marker is action-progress crossing `1`. In
  the observed branch-A run this is insertion-relative update 18 (capture row
  19 when the preceding idle row is counted) and the `K=1 -> K=8` transition;
  branch B reaches the same progress marker while changing
  `K=8 -> K=7`.
- Air, Water, and Earth do **not** run that one-shot action program. The
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
| Ether / Magic Missile (`8`, type `0x7D3`) | one actor on each Staff action marker; a still-held primary queues the next action after the prior action ends | spawn at staff emitter plus `(0,+10)`; velocity `3` world units/tick; radius `15`; two-pass body compositor `0x00535A30` with `BadGuys[110..112]`; world queued; no fixed lifetime; record 53 is contact-only | registry 57 `sounds\\magicmissile` once at emission; flight is silent |
| Fire / Fire Missile (`16`, type `0x7D4`) | one actor on each Staff action marker; held input requeues after action end without a release edge | emitter plus `(0,+10)` plus `20` along aim; velocity `4.5`/tick; radius `22.5`; core `BadGuys[110]`; main strip `BadGuys[255..266]`, frame `(age/3)%12`; per-tick cosmetic trail `BadGuys[267..270]` | registry 97 `sounds\\throwfire` once at emission; flight is silent |
| Air / Lightning (`24`) | start on press, sustain once per held tick, stop on release; constant Staff action is `K=0` on insertion and `K=7` thereafter; no projectile actor | reach-205 rank-1 ray; each tick creates a two-tick dual ribbon using `BadGuys[44]`, a one-shot source corona, and a five-tick endpoint corona whose four circles all use `BadGuys[110]` plus paired forks `[1836..1839]` | registry 54 `sounds\\lightningstart` on the start edge; registry 162 `sounds\\lightningloop__loop` owned for the channel lifetime |
| Water / Frost Jet (`32`) | start on press, emit once per held tick, stop on release; constant Staff action is `K=0` on insertion and `K=7` thereafter; no persistent gameplay projectile | rank-1 cone reach `205` is immediate gameplay only; shipped Enhanced Effects default emits two speed-`4` visual transients/tick; 75% Normal / 25% Over, 32-33 ticks; `BadGuys[30]` core plus `[28]` glint only | registry 44 `sounds\\icestart` on the start edge; registry 161 `sounds\\iceloop__loop` owned for the channel lifetime |
| Earth / Boulder (`40`, type `0x7D5`) | create on the first active tick; charge while the selected primary remains latched; after input release, the player tick retains Earth while charge is strictly below `0.3`, then releases the same cached actor on the following eligible tick | constructor charge is float32 `0.18`; the first post-tick actor row is age `1` at `0.181250006`; add float32 `0.00125` per active tick and clamp at `1`; a two-frame request reaches update `97` at `0.301249892` while still held, then first flies at age `98`; held radius `15`; release speed `3`/tick; persistent aura record 15 surrounds the discretely rebuilt/depth-sorted `[168..171]` shell; additive opening record 86 fades in about 29 ticks; called rocks and breakup use `[2008..2010]`; held orientation composes `0.75` degrees/tick and released flight keeps rolling by stored-distance/charge before contact | actor creation plays registry 87 `sounds\\startboulder` once; registry 159 `sounds\\gatherrocksloop__loop` starts with Earth and stops on primary transition or charge cap; moving boulder owns registry 168 `sounds\\rollingstoneloop__loop` |

### Historical first-slice PoC boundary (superseded)

This paragraph records the boundary of the original presentation-only slice;
the targeting, contact, and impact closures later in this ledger supersede it.
That first slice intentionally omitted mana, damage/status, target acquisition,
homing, collision, and impact presentation while those owners were unrecovered.
It used a collision-free web containment policy for Ether and Fire. The
integrated implementation has removed that policy: Earth, Ether, and Fire have
no fixed native timer or range and remain live until contact or teardown.
Unrecovered HP/resistance/status/death and Earth damage-pool semantics remain
out of scope rather than being approximated.

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
marker or completion. Fire's marker is insertion-relative update 18, its last
occupied update is 72, and the next-ready/idle row is update 73. The historical
`19/74` labels counted the preceding idle capture row. Air, Water, and Earth renew the
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
## 2026-08-14 Ether primary presentation audit

### Scope and method

This audit closes the Magic Missile flight presentation rather than accepting
the earlier `BadGuys[53]` shorthand. The target is the preserved retail 0.72.5
`SolomonDark.exe`, 4,723,200 bytes, SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
Fresh read-only headless Ghidra replicas decompiled and instruction-dumped:

| Role | Native address |
| --- | ---: |
| Primary handler | `0x0053CFE0` |
| `MagicMissile` constructor / deleting destructor | `0x005E4990` / `0x005E4F80` |
| Fixed tick / draw | `0x005FD270` / `0x005E0460` |
| Target probe / contact / continuation | `0x005E4A80` / `0x005F1F00` / `0x005E4B80` |
| Shared Ether compositor | `0x00535A30` |
| `Anim_FadeMM` tick / draw | `0x00454000` / `0x00457110` |
| `Anim_FadeAdditive` tick / draw | `0x00454000` / `0x004560A0` |
| Contact `ZAnimLit` constructor / tick / draw / destructor | `0x005E03D0` / `0x005FD1D0` / `0x005E01E0` / `0x005E47D0` |

The causal pass followed Staff Cast 1 through construction, actor tick, draw,
contact, and deletion. The adjacency pass resolved the animation vtables,
registered texture range, contact-only record 53 path, audio calls, sibling
users of the compositor, and `ZAnimLit` wrapper. The existing machine catalogs
already distinguish `0x00535A30 -> BadGuys[110..112]` from
`0x005F1F00 -> BadGuys[53]`; this report now agrees with that catalog.

### Actor layout and lifetime

`MagicMissile` is factory type `0x7D3`, allocation size `0x168`, vtable
`0x0079C544`. Constructor `0x005E4990` initializes the presentation-relevant
tail as follows:

| Offset | Initial value | Meaning in this path |
| ---: | ---: | --- |
| `+0x13C` | `0` before handler write | scalar clockwise heading |
| `+0x140/+0x142` | `-1/-1` | target group/slot identity |
| `+0x144` | `3.0` | base movement speed |
| `+0x148` | `2.0` | turn input used by homing |
| `+0x14C` | `0.01` | turn accumulator input |
| `+0x150` | `0` | target-loss/contact policy byte |
| `+0x154` | `RandomFloat(360)` | independent visual phase, degrees |
| `+0x158` | `0` before handler write | damage payload |
| `+0x15C` | `1.0` | visual scale |
| `+0x160` | `0` | optional render-half-alpha flag |
| `+0x161` | `0` | pierce count |
| `+0x164` | `1.0` | post-pierce scale/loss factor |

Tick `0x005FD270` runs the inherited timers, converts `+0x13C` to a unit
vector, and advances by `movementScalar(+0x120) * speed(+0x144)`. Every fifth
tick it tests a five-tick terrain segment. After movement and world-list
publication it advances visual phase:

```text
phase_next = phase + movementScalar * speed * 3
```

Neutral rank 1 therefore moves 3 world units and advances presentation by 9
degrees per native tick. The remainder is homing/target validation and the
per-tick proximity callback; none of those paths constructs a flight-trail
animation. In particular, call `0x0045ADE0` is the group/slot target resolver,
not an effect constructor.

There is no native fixed flight lifetime. Terrain or actor contact enters
`0x005F1F00`; a missing owner also removes the actor. Deleting destructor
`0x005E4F80` restores `MagicMissile::vftable`, calls inherited teardown
`0x006289F0`, and frees when requested. The initial Website slice's
collision-free 500-tick containment horizon was therefore not a recovered
native duration and is removed in the integrated implementation.

### Exact flight compositor

Draw `0x005E0460` samples

```text
S = visualScale + RandomFloat(visualScale * 0.5)
root = (actor.x, actor.y - 10)
```

and calls `0x00535A30(root.x, root.y, S, phase)`. It applies a temporary white
alpha 0.5 only when byte `+0x160` is nonzero; the neutral rank-1 constructor
uses the normal branch. The actor is a radial composite. It is not one rigid
sprite rotated into heading.

The compositor performs **two complete outer passes**. Both reuse the same
phase and `S`; they consume independent global-RNG samples. Each pass submits
the following operations in order:

1. Normal purple `(1,0.5,1)` core `BadGuys[110]`:
   `scale = (2.5 + 0.15 * abs(sin_deg(15 * phase))) * S`,
   `alpha = 0.2 + U[0,0.25]`.
2. Normal purple core `BadGuys[110]`:
   `scale = (1.5 + 0.15 * abs(sin_deg(15 * phase))) * S`,
   `alpha = 0.35 + U[0,0.55]`.
3. Enable the additive lane, then draw white spark `BadGuys[111]`:
   `scale = (1 + U[0,0.1]) * S`,
   `alpha = 0.35 * abs(sin_deg(5 * phase))`,
   `rotation = 50 * S * sin_deg(phase)`.
4. Draw `Integer(10) + 2`, hence 2 through 11, more additive white
   `BadGuys[111]` particles. Each samples a random unit direction, radius
   `U[0,20*S]`, scale `(0.25 + U[0,0.2]) * S`, alpha `U[0,0.75]`, and
   rotation `U[0,360]`.
5. Draw additive white ray `BadGuys[112]`:
   `scale = (1 + U[0,0.3]) * S`,
   `alpha = 0.55 * abs(sin_deg(8 * phase))`,
   `rotation = 50 * S * sin_deg(0.5 * phase)`.
6. Disable the additive lane before the next outer pass or function return.

The two cores deliberately share the `15 * phase` wave. The ray alpha uses
`8 * phase`, not 11. Both details are confirmed by raw instructions and
correct older decompiler-derived approximations.

The app registration array at `+0x46BC` is three `0xC4` records:

| Record | Flight role | Extracted size | Website PNG SHA-256 |
| ---: | --- | ---: | --- |
| `110` | purple core | 27 x 26 | `dc85c8e39483f4256ec7b28240d33a15b6966c0e997554598f19091d7a4c189f` |
| `111` | white spark/cloud | 40 x 40 | `3b02db24cc4caaad26432e4bf3e480c71c1a99e9cc8fb4fb4703077af22180c0` |
| `112` | white ray | 40 x 40 | `d442af9ee058baceb7df36d682a4663cfd207818572fe77830833ef555802630` |

They come from `images/BadGuys.bundle`, SHA-256
`a7b13b464e035e2099081ce942db4aa231fc7c20de1ecacbd9d0a590132c88d3`.
The actor remains one world-queue participant at gameplay Y; its much larger
visible cloud does not alter radius 15, culling ownership, or painter key.

### Contact and impact adjacency

`BadGuys[53]` at app field `+0x28CC` is 28 x 58 and does not participate in
ordinary flight. `0x005F1F00` owns two distinct contact presentation paths:

- With no pierce left, construct `Anim_FadeMM` (vtable `0x007848C4`) at the
  missile position. Its fixed scale is `2 * missileVisualScale`; alpha scalar
  starts at 2. Shared tick `0x00454000` stores the float32 subtraction of 0.1
  before removal, and same-tick registration yields 19 drawable states.
  Render `0x00457110` calls the complete Ether compositor with `-9999`, which
  selects the global fixed-tick counter. `ZAnimLit` owns radius 0.75,
  intensity 1, delta -0.05, and painter bias 100; 100 is not a radius. The
  wrapper owns child deletion and disappears with the child.
- With pierce remaining, decrement it, scale damage and visual magnitude, and
  advance along heading in steps capped at 5 world units until the continuation
  predicate clears. Each step constructs additive `Anim_FadeAdditive` (vtable
  `0x007847F4`) using `BadGuys[53]`, heading-aligned, alpha 1. Its inherited
  0.1 decrement gives a ten-tick streak. This is the record-53 use previously
  misidentified as the Magic Missile body.

Normal contact requests registry 58 `sounds\\magicmissilehit` at
`0x005F1FF2`; projectile construction already requested registry 57
`sounds\\magicmissile` at `0x0053D9CA`. Flight itself requests no sound.
The Staff action/source lane supplies the cast pose and socket only; the
handler does not construct a separate source glow or launch trail.

### Web consumption and open boundary

The cohesive Website implementation should render only the instruction-backed
flight compositor for its current collision-free projectile actor. It must
remove record 53 from flight, keep all `110/111/112` operations inside the
actor's one world-painter container, and retain Boneyard world-light tinting.
Presentation RNG should be a deterministic projection of stable projectile id,
age tick, and draw channel. That intentionally preserves the stock distributions
without coupling browser cosmetics to authoritative gameplay RNG or browser
frame count.

Do not infer impact from containment expiry or disappearance. `Anim_FadeMM`,
its light, record-53 pierce streaks, and impact audio stay dormant until an
authoritative contact semantic exists. The higher-skill writer and exact name
of byte `+0x160` remain open; rank-1 uses zero. A fresh clean-stock pixel
capture remains desirable for final color-management comparison, but it cannot
change the recovered object ownership, records, ordering, phase recurrence, or
formulas above.

### Validation receipt

The registered focused static contract
`test_ether_flight_compositor_and_contact_ownership_are_pinned` passes. It
requires the exact binary identity, ownership addresses, actor fields, phase
recurrence, root, both complete pass facts, particle count, phase lanes,
registered records and sizes, bundle hash, contact classes, audio boundary,
absence of a source glow/trail, and the prohibition on inferred impacts.

`python3 tests/re/run_static_re_tests.py --ci` ran 465 repository-available
contracts: 463 passed, including the new registered Ether contract. The two
failures are pre-existing documentation drifts outside this change's files:
the native-animation attachment table is missing its 18- and 12-facing formula
strings, and the native-audio trigger table no longer enumerates exactly 64
reviewed rows. No animation or audio-census document is modified by this audit.

## 2026-08-14 Fireball presentation closure

This closure used read-only headless Ghidra replicas against the preserved
retail executable SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
It follows the Fire primary beyond the earlier body-frame lead and replaces the
incorrect implication that the whole `110..112` auxiliary family belongs to
the rank-1 Fireball.

### Causal ownership and fields

| Stage | Native owner | Recovered contract |
| --- | --- | --- |
| cast | handler `0x0053DC60` | creates factory type `0x7D4`, starts at Staff emitter plus `(0,+10)` plus `20*aim`, and registers the actor |
| construction | `0x005E0970` | establishes the Fireball vtable and rank/modifier fields; common heading setter `0x00529380` writes direction `+0x13C/+0x140` and clockwise-from-up degrees `+0x144`; scale `+0x148` and movement scalar `+0x14C` default to one |
| flight tick | `0x005FDD90` over common actor tick `0x00624AC0` | moves `4.5*direction`, performs actor contact each tick and terrain contact every fifth tick, and creates one cosmetic `Anim_FireParticle` child each tick |
| body draw | Fireball vtable `0x0079C5BC`, render slot `+0x0C` -> `0x006099C0` | direct self-lit queue draw: ordered core, additive body, then source-over half-alpha body passes; bypasses common Puppet Region-light dispatcher `0x00624B40` |
| light | vslot `+0x30`, `0x005E50D0` | actor-root point light radius `1+U(0.25)`, intensity `0.75`, flag from `Game.MultipleShadows` |
| contact | `0x005E5160` | dispatches contact/status/optional area work, creates a lit `Anim_FireBurst`, requests `fireballhit`, then removes the Fireball |
| teardown | deleting destructor `0x005E50A0` | tears down the projectile actor; independently registered ZAnim children retain their own owner/lifetime |

The Fireball has no fixed native lifetime. It is consumed by the first accepted
actor or terrain contact. The straight-flight actor uses radius `22.5`, a
20-unit actor probe in its current spatial cell every tick, and a five-tick
lookahead terrain segment every fifth tick. None of those contact semantics is
a render timeout.

### Registered record groups and exact body passes

The durable atlas catalog maps the relevant `BadGuys` array destinations:

| Singleton field | Records | Consumer in this thread |
| ---: | ---: | --- |
| `+0x478C` | `251..254` | Fireball contact `0x005E5160` supplies the impact descriptor |
| `+0x479C` | `255..266` | Fireball body draw `0x006099C0` indexes the 12-frame strip |
| `+0x47AC` | `267..270` | `Anim_FireParticle::Draw` `0x0045E1B0` indexes the four cosmetic trail records |

Record `110` is addressed separately as the shared white circular mask. Body
draw `0x006099C0` translates to actor `(x,y-10)` and applies stored rotation:

1. record `110`, color `(1,0.5,0)`, alpha `0.2+U(0.25)`, scale
   `(3.2*actorScale,4*actorScale)`, without setting the additive flag;
2. record `255 + floor(age/3)%12`, white alpha one, scale
   `(2*actorScale,2.5*actorScale)`, additive flag set;
3. the same selected record and transform, white alpha `0.5`, after clearing
   the additive flag;
4. restore render color and the optional `+0x168` alpha modifier state.

This is a 36-tick body cycle and a three-draw composite. Records `111` and
`112` are adjacent shared spark/ray masks, but this Fireball draw does not call
them. The record-110 alpha RNG is consumed on each body draw, not once per
simulation tick; a deterministic web projection must therefore key that
flicker to the accepted presentation frame rather than projectile age.

Constructor instructions at `0x005E097A` install vtable `0x0079C5BC`. Its
render-queue slot `+0x0C` is direct body draw `0x006099C0`, not common Puppet
Region-light dispatcher `0x00624B40`. The direct draw installs the orange and
white modulation above. Fireball is therefore self-lit on the inbound side;
its separate `+0x30` provider remains an outbound light source.

### `Anim_FireParticle` flight trail

Fireball tick allocates a 0x44-byte child constructed by `0x00453290`, wraps it
in a world-owned `ZAnim`, and registers it through `0x0063E5B0`. Its tick is
`0x004533A0`, draw is `0x0045E1B0`, and wrapper depth bias is `30`.

For Fireball position `P`, unit direction `D`, and actor scale `S`:

```text
birth = P + randomUnitVector()*U(10*S) + (0,-10) - D*10
velocity = D*2
rotation = U(360) degrees
rotationDelta = +1 degree/tick
scale = (U(1)+0.5)*1.25
scaleMultiplier = 0.95/tick
frame = RandomInt(4) -> BadGuys[267..270]
dBase = (U(0.1)+0.1)*0.5 -> inclusive [0.05,0.10]
d = dBase*0.5 with Enhanced Effects -> inclusive [0.025,0.05]
```

Initial modulation is white `(1,1,1,1)`. Each tick subtracts `d` from red and
alpha, subtracts `2d` from green and blue, and deletes the particle only after
the new red value is negative. Draw sets the additive flag for the chosen
record and restores blend/color afterward. `Game.EnhancedEffects` at
`0x00B3BCAD` halves `dBase` when enabled, changing the lifetime band from
roughly 10--20 ticks to 20--40 ticks without changing emission cadence or actor
class. The shipped Website-equivalent Windows capability/default policy has
Enhanced Effects on, so the browser uses inclusive `[0.025,0.05]`. An older inspected
performance-profile sample had the configurable off branch; it is supporting
alternate-state evidence, not the shipped-default policy.

Ordinary `ZAnim` also bypasses inbound Region light. Its render-queue vtable
slot `+0x0C`, `0x005E01E0`, loads the owned animation at `+0x13C` and
tail-jumps directly to the child's slot `+0x0C`; it does not call
`0x00624B40`. `Anim_FireParticle::Draw` `0x0045E1B0` clamps the child RGBA at
`+0x20..+0x2C`, installs that modulation through `0x0041FE50`, toggles the
additive flag around records `267..270`, and restores white. A web painter must
therefore use `regionLightPoint: null` for the trail, not sample its moving
position for inbound tint.

The RNG calls use process-global presentation state. A deterministic web
projection can preserve every distribution and recurrence from a stable child
identity, but it cannot claim the exact native sequence without also reproducing
all intervening global RNG consumers. The semantic birth still belongs to the
authoritative Fireball tick: sparse snapshots must carry stable particle
identity, immutable birth position/direction, variant, age, and lifetime rather
than asking a renderer to invent historical emissions.

### Light and impact replacement

The flight light provider `0x005E50D0` submits at the actor root with radius
`1+U(0.25)`, intensity `0.75`, and `DAT_00B3BCAA` Multiple Shadows. Retail's
fresh shipped-Windows missing-key default is on through capability byte
`0x00B3BCAE`; the preserved sandbox profile explicitly overrides it off. This
provider is not a sprite pass and does not imply reciprocal inbound lighting:
both Fireball and particle visuals are self-lit as established by their
render-queue slots.

On contact, `0x005E5160` builds `Anim_FireBurst` (`0x00453470`; tick
`0x004575B0`; draw `0x0045E2D0`) over records `251..254`. Phase advances
`0.25`/tick, selecting one frame per four ticks and ending after exactly 16
visible ticks (semantic ages `0..15`); position moves upward one unit/tick. Initial scale is `1+U(0.1)`,
rotation is `U(360)`, and signed angular speed has magnitude `0.5+U(1)`.
The burst first draws record `110` at `5*scale`, orange, with alpha
`0.5*(1-phase/4)`, then draws the 251--254 frame additively under tint
`(1,1,0.75,1)`.

The `ZAnimLit` builder `0x005E03D0` gives that burst depth bias `50`, light
radius `1.5`, intensity `1`, per-tick intensity delta `-0.04`, and Multiple
Shadows false. `0x005FD1D0` applies the delta and registers the wrapper for its
world tick; provider `0x005E48E0` caps submitted intensity at one. Impact sound
is `sounds\\fireballhit`; cast release remains registry 97
`sounds\\throwfire`, and flight itself is silent.

### Non-conflation boundary and remaining unknowns

`Anim_FireParticle` is not `Fire_Goodguy`. Type `0x7EE` constructs at
`0x005E76C0`, ticks at `0x005FF050`, draws `DeadHawg[46..77]` through
`0x00610F90`, lives 200 ticks, and owns damaging area contacts every third tick
through `0x005FF1D0`. Firewalker, Fire Wall, and certain upgrade dispatchers
create that gameplay actor. A rank-1 Fireball trail never does.

The special `+0x168` modifier and upgrade/status/area fields
`+0x150..+0x16E` are statically located but are not present in the rank-1 web
slice. Exact global-RNG sequencing remains bounded as described above. No new
clean-stock Fire capture was obtained; the existing loader-injected D3D9
backbuffer at
`D:\\codex-evidence\\spell-fx-20260726\\post-fix-other-elements\\fire-client-matrix\\fire\\client_casts\\cast-01\\chosen-client.png`
(SHA-256 `0f4cc770c2ae3f86dc72f772acc2345d8a805a2cc68bd5196788dc74882cda07`)
is supporting visual evidence only. Static ownership, records, constants, and
pass order come from the pinned retail image.

## 2026-08-14 targeting, range, homing, and one-shot cadence correction

This section supersedes the earlier Website rank-1 PoC assumptions that gave
Air a fixed 205-unit ray and advanced Ether as a direction-locked projectile.
The causal pass follows player handlers into the native spatial queries and
projectile actor. The adjacency pass covers target retention, Lightning chain
selection, terrain/contact queries, and the shared Staff action clock. Evidence
comes from the pinned retail `SolomonDark.exe` (4,723,200 bytes; SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`).

### Lightning acquisition and segment geometry

`0x00529AD0` clears the wizard target handle at `+0x164/+0x166`, starts at the
wizard's actor position, obtains the Region reach scalar at `+0x8BE4`, doubles
it, and clips the resulting heading ray to the Region rectangle
`+0x8BCC..+0x8BD8`. It then calls the native cone query `0x00641500` with a
30-degree aperture, the clipped range, mask `6`, and no excluded actor. The
query accepts live actors other than type `0xBB9`, requires Region line of
sight through vslot `+0x124`, and orders matches lexicographically by the
actor's lower `+0xFC` priority first and squared distance second. Base actor
constructor `0x006287D0` writes zero at `0x00628986`; Gravestone constructor
`0x005E5C30` overwrites the field with `1000` at `0x005E5CBA`. Combat actors
therefore outrank graves, while equal-priority actors choose the nearest
candidate. Mask bits `0x180` also enroll
the Region special-scenery collection. A Gravestone (`2029`) is in that
collection, so an unobstructed grave in the aim cone is an intentional native
Lightning target rather than collision clutter.

`0x0052BA80` reacquires on every held Lightning tick. When the new query finds
nothing it restores the prior handle only while the old actor remains live and
its normalized caster-to-target vector has dot product at least `0.71` with
the current heading (about 44.8 degrees). A successful new query replaces the
old handle immediately.

Handler `0x0053F9C0` resolves a target's vslot `+0x34` attachment offset, adds
the actor position, clips caster-to-target through `0x00524D70` with mask
`0x380`, and moves the visual endpoint up 20 world units. Gravestone vtable
`0x0079C774` uses `0x00448D50` for `+0x34`; that function returns `(0,0)`, so
its Lightning endpoint is exactly `(grave.x, grave.y-20)` after clipping. With
no target, the handler obtains the Region vslot `+0x108` extent vector,
doubles it, extends along caster heading, and clips that segment. Air therefore
has no native fixed 205-unit reach; 205 belongs to Frost Jet.

For the first bolt, the handler measures the clipped source-to-endpoint
distance and places the QuickSpline middle control point half that distance
along the caster's original aim heading. This differs from the geometric
midpoint when a target lies off-axis and is the native targeting arc. The
existing `0x00531640`/`0x00534510` Lightning body then owns the two ribbon
layers and procedural waves. Chaining is adjacent, not rank-1 inference:
wizard `+0x284` controls hop count; `0x00641340` chooses the nearest unused
eligible actor within radius `200`; each hop multiplies damage by float32
`0.600000024`. Each hop owns another body and contact corona.

### Ether launch target and homing recurrence

`0x0053CFE0` creates rank-1 Magic Missile at the Staff socket plus `(0,+10)`.
It probes at `spawn + aimDirection*100` and calls `0x00641160`. That query walks
the Region actor collection, accepts actors whose flags contain bit `1`, and
chooses the actor nearest the probe while squared distance is below float32
`999999`. It performs no line-of-sight test. This is a broad acquisition
domain centered ahead of the caster, not a 100-unit maximum flight range.

The projectile constructor `0x005E4990` stores heading at `+0x13C`, target
handle at `+0x140/+0x142`, speed `3` at `+0x144`, turn input `2` at `+0x148`,
turn accumulator `0.01` at `+0x14C`, target-loss policy at `+0x150`, phase at
`+0x154`, scale at `+0x15C`, and pierce state at `+0x161/+0x164`. Tick
`0x005FD270` advances using the current heading first. It then asks shared
turn-direction helper `0x00410D60` for only `-1`, `0`, or `+1` and applies:

```text
heading += 2 * turnAccumulator * movementScalar * turnDirection
turnAccumulator += turnAccumulator > 1 ? 0.00200000009 : 0.0500000007
turnAccumulator = min(turnAccumulator, 10)
```

`turnDirection` follows the shortest cyclic path and is zero when the
normalized absolute gap is at most `1` degree or at least `359` degrees. The
stored float32 heading controls the following tick. Losing a target clears the
handle for rank 1 because the constructor's retarget policy is false.
Terrain lookahead runs every fifth age tick over five ticks of velocity before
movement; proximity contact runs every tick at radius `6`. There is no native
fixed flight lifetime. After age 199 or target loss, the proximity mask widens
from `2` to `6`; surviving-pierce retargeting at `0x005E4B80` is an adjacent
upgrade lane, not rank-1 behavior.

### Staff one-shot rate and held repeat

The Staff Cast1 constructor `0x0044B170` initializes progress `0`, float32 rate
`0.075` (`0x00784A1C`), actor movement scalar from `actor+0x120`, marker `1`,
and strict end `4`. Tick `0x004486E0` performs `progress += scalar*rate`, fires
the marker on crossing one, and completes only once progress is greater than
four. Dispatch `0x0052DA80` then changes the rate by element:

- Ether skill `8`: multiply by `0x00656580(0)`;
- Fire skill `16`: multiply by `0x00656580(1)` and double `0.75` at
  `0x007848B0`.

`0x00656580` is the cast-speed helper, not a damage helper. For class index
`i` it returns
`((equipmentMultiplier(+0x6AC) * FasterCaster(+0x94) + flat(+0x6B0)) *
classMultiplier(+0x6B4+i*4) + classFlat(+0x6D4+i*4))`, clamped to zero. Neutral
defaults are one/zero, so Ether retains rate `0.075` while Fire uses `0.05625`.
The player primary loop treats input as a held level: once the current Staff
action is gone, a still-held Ether or Fire primary immediately queues the next
action. A browser press-edge-only implementation is therefore both too slow
and behaviorally wrong for held one-shot casting.

### Implementation consequence and bounded unknowns

The authoritative simulation now acquires/retains Air targets, publishes explicit
source/midpoint/endpoint geometry for every bolt, and carries stable Ether target
identity plus heading/turn state. Renderers may consume those semantic facts;
they must not infer targets or rebuild homing history from snapshots. Boneyard
wave enemies and Gravestone `2029` are the presently materialized native
candidate families. Full stock actor-priority values for every future actor
class remain outside this Website slice; supported enemies retain base priority
zero and Gravestone uses its recovered priority `1000`. Exact
global collection insertion order only matters for an exact equal-priority,
equal-distance tie and remains unspecified.

The combined Website implementation uses distinct Region-bound range and
world-obstruction queries so a targetable Gravestone cannot incorrectly shorten
the acquisition ray. Protocol v13 carries the player's retained Air target,
each bolt's target/source/control/end geometry, and each Ether actor's target,
heading, and turn accumulator. Focused authority, protocol, interpolation, and
renderer regressions exercise combat-priority selection, Gravestone fallback,
off-axis QuickSpline control, Ether launch-probe selection, move-then-steer
ordering, target loss without rank-1 retargeting, terrain lookahead, and the
faster held-repeat Staff program. Browser and canonical receipts are recorded
in the Website parity ledger because they exercise the integrated asset and
renderer tree rather than this mechanics-only repository.

## 2026-08-14 Fireball contact, range, and recast closure

This second pass was prompted by the Website Fireball still crossing walls and
disappearing without the contact replacement described above. It used fresh,
read-only headless Ghidra replicas against the same 4,723,200-byte retail
`SolomonDark.exe`, SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
The handler, actor tick, contact routine, cast action, child animation, and
lit-wrapper instructions were re-read together instead of treating the body
draw as the complete Fire primary.

### Targeting, action cadence, and birth

- `Action_PlayerWizard_StaffCast1` constructor/tick `0x0044B170` /
  `0x0044B370` starts from float32 rate `0.075`. Helper `0x00656580` supplies
  the cast-speed scalar (neutral `1`), and Fire alone applies the adjacent
  double `0.75`, producing progress `0.05625`/tick, the observed marker at
  insertion-relative update `18`, strict-end crossing at update `72`, and
  action release/next-ready edge at update `73`. `PlayerWizard`
  callback `0x00550180` dispatches the mode-3 marker exactly once per action
  through `0x0054CAF0`. The occupied action rejects requeue, but a still-held
  primary level queues the next action after the prior one ends; release is not
  required for native Fire auto-repeat.
- Fireball skill row `16` contains `mDamage` and `mManaCost`, not `mCooldown`.
  No Fire-specific cooldown write, retained target, target query, homing turn,
  aim spread, or range comparison occurs in handler `0x0053DC60` or tick
  `0x005FDD90`. The action occupancy is the default recast gate. The projectile
  is straight and contact-bounded, not target- or distance-bounded.
- The handler samples wizard heading `+0x6C`, converts it with `0x00410500`,
  and `0x00529380` writes the immutable unit direction to Fireball
  `+0x13C/+0x140`. It creates type `0x7D4` at the Staff emitter plus `(0,+10)`,
  then pushes the actor `20` units along that direction. The tick multiplies
  direction by movement scalar `+0x14C` and the `4.5` Fireball speed global.
- After registration, the handler calls segment/polygon query `0x00524D70`
  from the wizard root to the spawned Fireball root with collision mask
  `0x700`. A blocked birth immediately calls `0x005E5160(NULL)` at the spawned
  root. It creates no flight particle because no Fireball tick has run.

### Flight/contact instruction order

`Fireball::Tick` `0x005FDD90` has this exact presentation-relevant order:

1. If actor age `+0x134` is divisible by five, query the segment from current
   root `P` to `P + 5*(4.5*D)`, again through `0x00524D70` and mask `0x700`.
   A blocked segment calls terrain contact at current `P` and returns before
   common movement and before cosmetic-particle allocation.
2. Run common actor tick `0x00624AC0`, then add `4.5*D` to the root.
3. Run the world-bounds retirement check, then query the current spatial cell
   through `0x00641220` with radius `20` and mask `6`. The candidate filters
   reject deleted/ineligible objects, preserve the native group/contact gates,
   and use the candidate geometry path before accepting contact.
4. An accepted candidate calls `0x005E5160(candidate)`. Unlike the terrain
   branch, execution then falls through and allocates one final
   `Anim_FireParticle`. This last cosmetic child is not residual damage.
5. Allocate/register the ordinary `ZAnim` particle and renew the Fireball in
   the world-owned actor list.

The constructor's collision category is `0x700`; its recovered actor radius is
`22.5`. The tick's `20`-unit current-cell query is broad-phase reach, not a
Fireball range limit. No hard flight timer exists. The legacy web-only
500-tick deletion must therefore remain removed and must never masquerade as
contact or play an impact.

### Contact replacement, light, and audio corrections

`0x005E5160` conditionally performs rank/upgrade damage and status dispatch for
a non-null eligible actor, then calls the Fireball removal vslot **before**
audio and presentation allocation. Null terrain contact skips actor damage but
owns the same replacement presentation and audio:

- point sound registry `30`, `sounds\\fireballhit`, is requested at the
  Fireball root with world point gain and pitch `1 + S(0.1)`, hence
  inclusive `[0.9,1.1]`; the exact stock WAV is 30,530 bytes, SHA-256
  `9bfad709cfb932b7e836c58f781a42ee78907a0211bac5d14a2583d721192738`;
- `Anim_FireBurst` constructor `0x00453470` receives singleton descriptor
  `+0x4788` for registered `BadGuys[251..254]` and starts at `(P.x,P.y-10)`;
- phase starts at zero and advances exactly `0.25` in base tick `0x00457540`.
  The child marks itself deleted when the new phase is greater than or equal to
  descriptor count four, so visible semantic ages are exactly `0..15`: frames
  `0..3` each last four ticks and there is no visible age-16 frame;
- specialized tick `0x004575B0` also moves `y -= 1` and adds signed angular
  velocity of magnitude `0.5+U(1)` degrees/tick. Scale is `1+U(0.1)` and
  initial rotation is `U(360)`;
- draw `0x0045E2D0` first submits record `110` source-over at `5*scale`, tint
  `(1,0.5,0)`, and alpha `0.5*(1-age/16)`, then submits the current impact frame
  additively with tint `(1,1,0.75)`;
- `ZAnimLit` vtable `0x0079C4DC` uses render slot `+0x0C = 0x005E01E0`, the
  same direct child draw trampoline as ordinary `ZAnim`. The burst is therefore
  self-lit for inbound Region tint. Independently, provider `0x005E48E0`
  publishes a moving child-position light: radius `1.5`, intensity
  `1 - 0.04*age`, Multiple Shadows false. The wrapper depth bias is `50`.

This corrects the earlier approximate “16--17 tick” wording: the instruction
boundary is an exact 16 visible ticks. It also clarifies contact ordering;
removal precedes, rather than follows, the independently owned burst and sound.

### Enhanced Effects and adjacency boundary

The contact burst has no Enhanced Effects branch. The flight child retains the
already recovered global `DAT_00B3BCAD` branch: shipped/default Enhanced
Effects on halves fade to inclusive `[0.025,0.05]` while off uses inclusive `[0.05,0.10]`; cadence
stays one child per successful Fireball tick. `Fire_Goodguy 0x7EE`, Embers,
Explode, status fields, and area damage remain separate actor/gameplay lanes.

The Website can now truthfully add terrain contact, a stable semantic
`fire-impact` replacement, exact registered frames, its outbound light, and
the hit cue. The current web wave-enemy snapshot has positions but no native
collision body/category/contact flags or health authority, so instruction-exact
actor damage/contact remains bounded rather than being guessed from a point
radius. A future combat slice must recover and publish that actor contract
before enabling the candidate branch.

### Static-contract receipt

Registered contract
`test_fireball_contact_range_and_recast_closure_is_pinned` passes through the
canonical static-RE registry. It requires the exact binary identity, Staff
rate/scalar/Fire multiplier and held requeue, absence of targeting/range/timer,
handler and fifth-age segment order, contact/removal ownership, exact 16-tick
two-pass burst, direct/self-lit wrapper, moving light, shipped Enhanced branch,
bounded actor-authority lane, and the corrected Fire impact row in
`native-audio-events.md`, including call site, stock WAV, pitch, and null-terrain
ownership. The touched Python contract modules also pass bytecode compilation.

## 2026-08-14 third-pass presentation and Region-shadow closure

This section supersedes the earlier claims that both rank-1 Frost classes use
the same locally lit Y queue, the Boulder orientation stops on release, the
Lightning factory samples path lights every 50 units, and a visible-alpha hull
is a native complex-shadow representation. Evidence is the preserved retail
`SolomonDark.exe`, 4,723,200 bytes, SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`,
inspected through read-only Ghidra replicas plus raw PE bytes. No live process
or desktop state was required.

### Frost Jet: two managers, same-tick birth update, and exact wire state

The two rank-1 classes keep the recovered record/passes and 75/25 class split,
but register into different owners:

| class | registration | update/draw placement | inbound Region light |
| --- | --- | --- | --- |
| Normal | `0x00543CF5..0x00543D03` calls `0x0063E5E0`; `ZAnim` in `Region+0x8B70`, bias zero | current child Y in the shared queue, submitted after ordinary actors and static/scenery on equal rows | none; `ZAnim` `0x005E01E0` tail-calls child `+0x0C` |
| Over | `0x00543B8A..0x00543B9C`; direct `Region+0x1E0` ObjectManager | insertion order in a post-world-queue pass | none; manager `0x004023F0` calls child `+0x0C` directly |

Arena flushes the shared queue at `0x0046FDA4`, then draws Over at
`0x0046FFB7..0x0046FFBD`, before screen/camera overlays. Courtyard flushes at
`0x0051FD21`, draws Over at `0x0051FE94`, then draws the late College and
southern foreground banks from `0x0051FEB7` onward. Mortuary, Library,
StoreRoom, and Office direct-manager calls are `0x0050F3A1`, `0x00511AD0`,
`0x00519C03`, and `0x0051A725`; later room effects/foreground still follow.
The browser seam must therefore distinguish `world-sorted` from
`post-world-queue`; Over must not be approximated with a fake Y or huge bias.
Within sorted roots, Normal's equal-row family follows ordinary dynamic and
static/scenery submissions.

Region tick order is player manager `0x0063F127..0x0063F139`, Normal manager
`0x0063F162..0x0063F168`, then Over `0x0063F16D..0x0063F173`. A player-created
Frost child is inserted before its destination manager updates, and
ObjectManager `0x004022A0` observes the live count. Both classes therefore
receive one complete update before first draw. First-visible age is one:

- Normal phase `0.05000000074505806`, additive alpha
  `0.699999988079071`, and position `origin+velocity`;
- Over phase `0.02500000037252903`, core alpha
  `0.012500000186264515`, glint alpha `0.03750000149011612`, and one advanced
  position.

Lifetime compare/delete `0x00453780..0x00453797` removes on newly stored
`lifetime <= 0`. The killing update is not drawn. Native visible ages are
`1..31` or `1..32`, not constructor age zero plus 32/33 frames. Every recurrence
consumes `floor(ageTicks)` completed updates; fractional presentation age must
not execute a premature extra iteration.

Normal obstruction is not point-only. Prediction begins at caster position,
uses mask `0x380`, and computes
`steps = lifetime/0.04 + jitterRadius` without a float store between division
and addition. `0x00403B40` stores float32 born-origin-to-hit distance in
particle `+0x50`; point is always copied to `+0x54/+0x58`. Handler
`0x00543E05..0x00543EBC` separately compares caster radial squares and sets
the distance to zero only when strict `originSq > hitSq`; equality does not.
The point remains. Update `0x004536B8..0x004536D1` subtracts float32 current
speed and triggers at `remaining <= 0`, snaps to the stored point, chooses the
global-RNG sign, sets
`velocity=(sign*oldVy*0.5, sign*-oldVx*0.5)`, writes sentinel `999999`, then
advances once with the new velocity. The semantic snapshot must carry coherent
`obstructionPoint` and `obstructionDistance`, including numeric zero.

Heading fields `+0x2C/+0x30` retain the born heading through splay. Core and
glint sprite rotations remain that heading even while glint lead follows the
changed velocity. The web needs an explicit born heading; reconstructing it
from post-splay direction is false. Handler float-store boundaries for the
phase/radian/sine/final heading are `0x00543A90/0x00543AA4/0x00543AB1/
0x00543ACB` for Over and `0x00543BAD/0x00543BC1/0x00543BCE/0x00543BEE`
for Normal.

Final local color packing is also native-visible. `0x0041FE50` stores float32
RGBA and multiplies it by the restored renderer multiplier. Code
`0x0041FEEB..0x0041FF45` multiplies by double 255 and helper `0x00747360`
uses `CVTTSD2SI`. In-range channels truncate toward zero: 0.5 becomes 127,
not 128, and effective alpha is `trunc(alpha*255)/255`. Neither Frost class
samples Region light.

### Boulder: continued flight roll and CalledRock auxiliary copy

Constructor `0x005FA270` initializes matrix `Boulder+0x154` through
`0x00402CC0`. Release `0x005E5450` only changes the held/flight bytes at
`+0x1DC/+0x1DD`; it preserves the matrix.

Tick `0x00609D84..0x00609E33` derives the normalized axis for heading `h`:

```text
(cos(h), sin(h)/sqrt(1.64), 0.8*sin(h)/sqrt(1.64))
```

The held branch at `0x00609E3D..0x00609E5D` postmultiplies the accumulated
matrix by a `0.75`-degree row-vector Rodrigues rotation around the current live
aim axis. Flight/contact vslot `0x00620B60` first stores
`position += speed*(sin(h),-cos(h))`, measures the actual float32 stored delta,
stores `theta=float32(hypot(delta)/charge)` degrees, and postmultiplies the
same matrix before collision begins at `0x00620CBA`. A terminal contact tick
moves and rotates; an early arena/range guard can delete before both.

Helper `0x00403340` constructs row-vector Rodrigues `R`; multiply helper
`0x00402D40` proves `Mnext=Mold*R`. Draw `0x0060AC40` evaluates local row vector
`[x y z 1]*M`, rejects strict `z<=-40`, sorts surviving rocks by ascending Z,
and passes only transformed X/Y to sprite drawing. Nine authoritative finite
float32 row-major matrix fields are required. Age/heading reconstruction,
component interpolation, and `R*M` all lose native state.

Golden held vectors are:

```text
h0 once:
[1,0,0, 0,0.9999143481,0.01308959536,
 0,-0.01308959536,0.9999143481]

h0 then h90 (R0*R90):
[0.9999143481,0.008177005686,-0.01022125687,
 -0.008042513393,0.9998814464,0.01313068997,
 0.01032741554,-0.01304737944,0.9998615980]
```

At speed three, full charge rolls three degrees per tick. Observed minimum
release charge `0.3012498915195465` rolls `9.95850944519043` degrees/tick.

`Anim_CalledRock::Render` `0x0045E440` owns the remaining gathering pass.
When Enhanced Effects is nonzero and perspective height `+0x20<0`, it first
draws the same selected lit-rock record `BadGuys[2008..2010]` at base XY and
`0.75*mainScale`, then draws the full-scale rotating main copy at `y+height`.
At nonnegative height or Enhanced Effects Off only the main copy draws. Both
are direct/self-lit. `BadGuys[18]` belongs neighboring dust/fade actors and is
not this auxiliary pass.

Boulder and Player are ordinary Puppet roots; same-row insertion puts the
later-created Boulder after Player. The Staff orb is nested inside the Player
draw and is not a separately queued native root. Stock can place the entire
Boulder behind or ahead of the entire Player according to its Y row. A web
requirement that the Boulder always cover its owner's orb is thus a deliberate
targeted presentation policy, not a stock invariant, and must not globally
promote other projectiles or scenery.

### Lightning branch mesh and one-shot MiscLights

Each of the two calls to tessellator `0x00534510` independently gates one
branch with `RandomInt(2)` at `0x00534A11`. If selected, four textured vertices
and six indices append to that same ribbon layer and inherit its draw state.
Attachment is `U(2)` along the exact QuickSpline. Registered branch records
are:

| record | crop/logical/origin | local geometry quad |
| ---: | --- | --- |
| 375 | `39x73` / `90x146` / `(-18.5,-27.5)` | `(-38,-64),(1,-64),(-38,9),(1,9)` |
| 376 | `40x185` / `96x372` / `(-20,-77.5)` | `(-40,-170),(0,-170),(-40,15),(0,15)` |

Scale is `0.25+U(0.5)` with a `1/30` exact-one override. X mirror,
geometry-record choice, and UV/image-record choice are independent. All four
geometry/texture pairings are valid. Angle uses the chosen geometry's first
coordinate pair with the second negated, converts through atan2, normalizes to
degrees, then adds `U(45)` before translation to the spline point.

Layer phases are construction-time `-3*managerTick` and `+15`, not transient
ID or redraw time. Native random displacement uses the unsigned mixer:

```text
u = x ^ (x << 21); u ^= u >>> 11
mixRaw(x) = imul(u ^ (u << 4), 0x0A67CFCF) >>> 0
abs32(v) = signed(v)>=0 ? v : (0x80000000-(v&0x7fffffff))>>>0
```

Per sample, angle magnitude comes from `s0%360000`, sign from
`abs32(mixRaw(s0))%2`, radius from the next mixed state modulo 360000, and the
following state is the third signed-absolute mix. A semantic seed may replace
the unrecovered process-global starting word, but the intra-layer recurrence
must not be substituted by xorshift.

Record 44 UV construction maps normalized top and bottom half-rectangles
through the registered atlas record. For `N` ribbon pairs, `v[0]=0`,
`v[N-1]=0`, and each interior `v[i]` is one for odd `i` and `0.5` for even
`i`; both vertices in a pair share V. The seven-pair rank-1 sequence is
`[0,1,0.5,1,0.5,1,0]`, not binary alternation.

Factory `0x00531640` walks source-to-middle and middle-to-end separately. It
advances by exactly 100 while the leg remainder is greater than 50, then also
considers the exact endpoint. A midpoint can therefore occur twice. It emits a
Region `MiscLight` only when squared distance from the original source is at
least 48400. Each source is `(sample.x,sample.y+35)`, radius
`0.75+U(0.25)`, with one factory-shared intensity `0.25+U(0.75)`.
Insufficient-mana parameter nine quarters that intensity; it is not target
mode. The directional-shadow flag is Enhanced Effects `DAT_00B3BCAD`, shipped
On, not Multiple Shadows.

MiscLights are constructed once and must enroll only at Air transient age
zero. Provider lights, including the false-flag five-age contact `ZAnimLit`,
are submitted first; Region replays MiscLights as a tail batch. One-way
containment makes that order observable. A false-flag contact never creates a
directional record, but every accepted source contributes to each record's
`behindScalar` and can remove its shadow tail. For source zero, midpoint 350,
and endpoint 650, emitted x positions are `[350,350,450,550,650]` at y+35.

### Region complex-shadow geometry

Shape close helper `0x00655570` stores each authored edge normal exactly as
`(dy,-dx)`. It performs no signed-area or winding normalization. Projector
`0x00655970` computes `normalize(edgeMidpoint-source)` and accepts strict
positive dot product. Mixed winding in the stock tables is intentional. For
the CCW square `(-1,-1),(1,-1),(1,1),(-1,1)` and source `(-10,0)`, top, right,
and bottom edges pass; the left/source-facing edge does not.

Each accepted edge becomes one four-vertex/six-index quad with alpha lanes
`[base,base,tip,tip]`, where
`tip=((1-behindScalar)*(1-distanceFraction))^3`. Repeated flat-alpha strips are
not native gradient geometry.

The exact Gravestone table `0x0081BE50`, selector short `+140`, is:

```text
0  [-19.5,-3.5; 19.5,-3.5; 19.5,12.5; -20.5,12.5]
1  [-6.5,0.5; 2.5,0.5; 2.5,6.5; -6.5,6.5]
2  [-19,23; -19,-7; 17,-7; 17,23]
3  [-9,14; -9,3; 6,3; 6,14]
4  [-13,14; -13,7; 10,7; 10,14]
5  [-14,5; -14,-3; 13,-3; 13,4]
6  [-15,7; -15,-14; 13,-14; 13,7]
7  [-15.5,6.5; -15.5,-8.5; 15.5,-8.5; 15.5,6.5]
8  [-12.5,16.5; -12.5,-3.5; 12.5,-3.5; 12.5,16.5]
9  [-18.5,10.5; -18.5,-0.5; 18.5,-0.5; 18.5,10.5]
10 [-19.5,13.5; -19.5,1.5; 19.5,1.5; 19.5,13.5]
11 [-15.5,13.5; -15.5,-7.5; 15.5,-7.5; 15.5,13.5]
12 [-16.5,15.5; -16.5,-5.5; 18.5,-5.5; 18.5,15.5]
13 [-14.5,8.5; -14.5,-4.5; 16.5,-4.5; 16.5,8.5]
14 [-19.5,8.5; -19.5,-5.5; 19.5,-5.5; 19.5,8.5]
15 [-17.5,11.5; -17.5,-4.5; 17.5,-4.5; 17.5,11.5]
16 [-15.5,7.5; -15.5,-4.5; 15.5,-4.5; 15.5,7.5]
```

Fencepost table `0x0081B0B8` indexes `selector+7*style`; base rows zero through
six are:

```text
0 [-11.5,9.5; -11.5,-8.5; 11.5,-8.5; 11.5,9.5]
1 [8.5,11.5; -14.5,7.5; -8.5,-10.5; 14.5,-6.5]
2 [5.5,13.5; -15.5,4.5; -5.5,-9.5; 14.5,-3.5]
3 [1.5,14.5; -16.5,1.5; -0.5,-10.5; 16.5,-0.5]
4 [-1.5,14.5; -16.5,-0.5; 2.5,-12.5; 16.5,1.5]
5 [-4.5,13.5; -15.5,-3.5; 2.5,-13.5; 15.5,4.5]
6 [-8.5,12.5; -14.5,-5.5; 7.5,-12.5; 14.5,7.5]
```

Style-one rows are the corresponding base row multiplied by `0.45`, then
translated by y `-1`.

Monument painter `0x0060E280` indexes 21 authored rows at `0x00819EE8`:

```text
0/1   [(-51,22),(-51,-27),(50,-27),(50,22)]
2/3   [(19,-29),(-27,-29),(-27,25),(19,25)]
4/5   [(-14,-32),(-14,30),(35,30),(35,-32)]
6     [(19,-21),(-17,-21),(-17,20),(19,20)]
7/8   [(21,-48),(-23,-48),(-23,49),(21,49)]
9     [(18,-23),(-20,-23),(-20,22),(18,22)]
10    [(-33.5,22.5),(-33.5,-11.5),(34.5,-11.5),(34.5,22.5)]
11/12 [(-68.5,-22.5),(71.5,-22.5),(71.5,33.5),(-68.5,33.5)]
13/14 [(-23,-15),(24,-15),(24,19),(-23,19)]
15/16 [(-26,-18),(28,-18),(28,17),(-26,17)]
17    [(-25,-16),(28,-16),(28,27),(-25,27)]
18    [(-11,-10),(11,-10),(11,10),(-11,10)]
19    [(-3.5,8.5),(-11.5,-5.5),(5.5,-14.5),(14.5,1.5)]
20    [(-2.5,14.5),(-14.5,1.5),(-1.5,-10.5),(12.5,3.5)]
```

Goodie painter `0x0061F180` indexes `0x0081B390` by subtype, not visible
phase. Static initialization closes row zero only:
`[(-33.5,22.5),(-33.5,-11.5),(34.5,-11.5),(34.5,22.5)]`.

Building painter `0x0060EDC0` indexes four authored rows at `0x0081B430`:

```text
0 [(92.5,140.5),(56.5,140.5),(54.5,161.5),(31.5,161.5),
   (31.5,155.5),(-31.5,155.5),(-32.5,161.5),(-57.5,161.5),
   (-56.5,139.5),(-93.5,139.5),(-93.5,-19.5),(92.5,-19.5)]
1 [(-60,103),(-60,116),(-82,132),(-103,117),(-103,77),(-91,77),
   (-91,-23),(-101,-23),(-102,-49),(101,-49),(101,-23),(90,-23),
   (90,77),(103,77),(103,108),(82,132),(59,108),(59,103)]
2 [(74,141),(-75,141),(-75,85),(-132,85),(-132,-61),(131,-61),
   (131,85),(74,85)]
3 [(-64.5,132),(-64.5,6),(65.5,6),(65.5,132)]
```

FenceGrate uses custom renderer `0x00600ED0`, shared by intact, broken, and
Gate. Builder `0x005E8100` insets endpoints by 12 and derives the shortened
line, count, and nominal `13.333333` step. For each directional record and bar
index, center is `shortStart+0.5*step+i*step`. Projection creates one tapered
quad with near half-width two/base alpha and far half-width eight/zero alpha.
A separate width-four rail shadow has alpha
`0.1*behindScalar+0.9*baseAlpha` and a one-eighth endpoint/source offset. Bar
gaps must remain transparent.

Rails `0x00607440`, Wall generated shape through `0x006561A0`, and Scrub's
transformed asset quad are other class-specific paths. The then-unrecovered
classes were an explicit interim boundary, not permission for a production
fallback. The later complete direct-reference census closes them: no
materialized native caster may be replaced by a convex alpha hull.

### Target/range/contact adjacency at the third-pass baseline

This subsection records Website `5d532e4` before the query/contact closure
that follows it; its “Website currently” statements are historical, not the
integrated status.

Read-only comparison of the native call chains to Website commit `5d532e4`
confirms that cast-facing, Air acquisition/Gravestone fallback and spline arc,
Ether acquisition/homing/default repeat rate, and Fire's registered body/trail/
light/burst sprite stack already match their recovered rank-1 contracts.

The remaining semantic boundary is actor contact, not visual targeting:

- Fire handles age-divisible-by-five terrain lookahead before movement, then
  moves `4.5`, queries the current spatial cell at `0x00641220` with broad
  radius `20` and mask `6`, runs native geometry/contact filters, calls
  `0x005E5160` on acceptance, and still creates one final flight particle. The
  Website currently has only terrain contact, so enemy contact never produces
  its otherwise-correct burst/light/registry-30 hit cue.
- Ether's web contact is an approximate center-distance-below-six deletion.
  Native mask/geometry contact owns `0x005F1F00`, whose normal rank-1 endpoint
  replaces the missile with the 19-drawable-frame `Anim_FadeMM`, the full Ether compositor,
  outbound light, and magic-missile hit audio.
- Water's 205-unit, 15-degree, mask-`0x1082` query at `0x00543860`/
  `0x00641B10` is immediate, multi-target, and per-target line-clipped; visual
  Frost children are not the damage projectiles.
- Earth `0x00620B60` owns actor geometry/contact and its distinct-target list
  separately from terrain breakup.
- Air's 30-degree Region-bound acquisition and visual ray are implemented, but
  the per-held-tick native contact/damage dispatch is a separate authoritative
  consequence.

None of these actor lanes may be replaced by an inferred circle-overlap across
every web `kind=enemy`. Exact modeled enemy collision/category/eligibility and
combat-authority fields must be published before enabling the contacts. Until
that adjacent trace is closed, geometry and VFX parity can be exact while the
gameplay-contact limitation remains explicit.

### Exact FenceGrate builder split and rank-one query ABI

All grate variants call custom shadow painter `0x00600ED0`, but their builders
produce distinct common fields:

| class | builder/update | stored segment and count |
| --- | --- | --- |
| intact FenceGrate | `0x005E8100` | inset full A/B by 12; step is normalized direction times float `13.333333015441895`; `trunc(shortLength/storedStepLength)+1` |
| FenceGrate_Broken | `0x005EC6E0` | side-owned randomized approximately-52-unit subsegment, inset 12 and working inset 6; step length 8; truncation-plus-one count |
| moving Gate | `0x005ED100`, called by builder `0x005F73C0` and moving tick `0x005ED5F0` | copy current leaf endpoints, inset 4, step from shortened length/4.5, truncation-plus-one count (normally five) |

Exact multiples add one bar because conversion helper `0x00747360` truncates
positive finite values before the explicit increment. Renderer centers remain
`shortStart + 0.5*step + i*step`. Broken pieces do not use the serialized full
post span, and Gate re-materializes from live leaf endpoints each movement
tick.

The common Puppet/query fields recovered from constructors and query helpers
are flags `+0x14`, body radius `+0x30` (base default 15), pending removal
`+0x05`, active/retention `+0xF9`, handle `+0x5C/+0x5E`, and native priority
`+0xFC`. Coffin `0x00479940` clears flags at `0x00479A34`; subsequent
registration can add only `0x40`, so Coffin is ineligible for every rank-one
primary mask discussed here. `+0xF9` is active world membership, not a Wraith
hidden-state bit.

Point query `0x00641220 -> 0x00522E30` divides each coordinate by the 100-unit
cell size, stores float32, and converts through `0x00747360` with truncation
toward zero, not floor. It searches only that cell's current pointer vector in
ascending slot order. Native `-0.25 / 100`, for example, selects cell zero.
Geometry helper `0x00410470` requires strict
`distance < queryRadius + candidateBodyRadius`; equality and overlaps whose
roots lie across the cell boundary miss. The first qualifying actor wins.

Rectangle/circle broadphases `0x00522F50` and `0x00523140` convert both
inclusive AABB endpoints through the same float32/truncation pipeline, then
visit cell X in the outer loop, cell Y in the inner loop, and live vector slots
ascending within each cell. This proves per-cell slot order, not a global actor
registration sort. The Website's persisted `registrationOrder` is a
deterministic projection until native rebind timing and exact cell-slot
identity are authoritative.

Fire `0x005FDD90` uses radius 20/mask 6 after its 4.5-unit move. Actor contact
`0x005E5160` removes, emits registry-30 hit audio and the 16-age burst/light,
then the actor-contact return path creates one final normal Fire particle;
terrain contact returns before it. Ether moves then uses radius 6, mask 2
while age `<200` and target `+0xF9` remains active, otherwise mask 6. Contact
`0x005F1F00` creates registry-58 hit audio and a construction-20-update full Ether
compositor/ZAnimLit before removal.

Water `0x00641B10` is a strict root-only reach-205/full-aperture-30-degree
multi-target query with LOS and mask `0x1082`; candidate radius does not enter
its final range test, and no target-local Frost burst exists. Earth gathers all
eligible roots strictly within `75*charge`, tracks handles already contacted,
and does not fracture merely because it touched an actor. Air visual fallback
may end on a Gravestone, but held damage dispatch applies only to bit-two
actors and rank one does not chain.

HP/resistance/status/death, exact recipe-scale/global-RNG samples, spatial
rebind timing, Earth's pool/toughness/shrink terminal decision, and mask-six
bit-four scenery shape acceptance remain outside the recovered web authority.

### Exact Rails/Wall painters and Ether FadeMM lifecycle

Rails builder `0x005F0EC0` stores `P=A+4u`, `P1=B-4u`,
`s=f32(u*13.333333015441895)`, and
`N=trunc(distance(P,P1)/length(s))+1`. Shadow renderer `0x00607440` uses
`Q=P+N*s` as its far baseline and emits exactly two width-10 black line quads
per current light record. Their endpoint pairs are projected from `P/Q` by
divisors `5` and `1.5`; alpha is
`f32(0.9*record.base+0.1*record.behind)`. There is no render-time RNG.

Wall builder `0x005EEBB0` extends each unconnected endpoint 15 units outward
and leaves connected endpoints untouched. Renderer `0x0061E780` calls segment
helper `0x006561A0` once per record. It emits vertices `[S0,S1,E0,E1]` and
indices `[0,1,2,2,1,3]`, where `E0/E1` are radially projected by record
`+0x1C`; near alpha is record `+0x10`, far alpha is exactly
`((1-record+0x14)*(1-record+0x18))^3`. Wrapper `0x00624B40` clears and rebuilds
the record array each render. Neither Rails nor Wall owns a retained shadow
lifetime. The generated random-seed Boneyard contains no segment code 3 or 4,
so exact tests require story/synthetic fixtures rather than claiming a shipped
browser observation.

Ether contact `0x005F1F00` initializes Anim_FadeMM scalar `F[0]=f32(2.0)`,
fixed XY scale `f32(2.0*missileVisualScale)`, and decrement `f32(0.1)`.
`0x00454000` stores `F[n+1]=f32(F[n]-f32(0.1))` before removing on `<=0`.
Immediate registration into Region `+0x8B70` means the child updates in its
birth tick: drawable frames are `F[1]..F[19]` (19 web-visible ages), and tick
20 removes before render. Fixed scale never decays; final pass alpha is
`f32(passAlpha*F)` with no FadeMM clamp.

FadeMM render passes exact sentinel `-9999.0f` to compositor `0x00535A30`.
The equality branch substitutes the active Arena/global 100-Hz fixed-tick
counter, so all impacts in one tick share phase and the phase advances one per
tick. ZAnimLit writes radius `0.75`, intensity `1.0`, delta `-0.05`, local
multiple-shadows false, and Puppet painter bias `100`; the last value is not a
light radius. Same-tick update makes first drawable intensity `0.95`.
Registry 58 `magicmissilehit` pitch is `f32(1+U(0.1))`.

### Integrated Website status and explicit authority boundary

The integrated Website projection now carries the recovered actor eligibility
fields, projected per-cell slot order, and discrete spell state over protocol
v18. Coffin is excluded from the
rank-one masks. Air target/Gravestone selection, Ether acquisition and homing,
Fire and Ether point-contact replacement, Earth orientation, Frost obstruction
state, and all presentation/light/painter owners above are authoritative rather
than reconstructed from renderer history. Fire record-110 flicker consumes the
presentation-frame sample; no primary actor uses the legacy 500-tick timeout.

Water's strict reach-205/half-aperture-15-degree/LOS query, Earth's strict
root-distance-below-`75*charge` distinct-contact query, and Air's selected
flags-bit-two endpoint are recovered, regression-tested, and connected to the
Website's existing authoritative enemy HP/lifecycle. Fire and Ether publish
the same projected damage edge after their point queries. This models the
observable rank-one contact and hit presentation without claiming exact native
resistance/status/push math, recipe-scale RNG, or Earth's pool/toughness/shrink
and terminal-fracture decision; actor contact never invents an Earth breakup.
Fire's bit-four scenery shape gate and exact
native global-RNG/recipe-scale sample identity are likewise explicit residuals.
Those are combat/RNG boundaries, not missing rank-one sprite passes, target
geometry, projectile timeouts, or permission to invent terminal impacts.

## 2026-08-15 low-mana presentation and damage consumers

Shared debit helper `0x0052B150` selects this branch from post-debit MP `<=0`.
The state is fixed and per emission; there is no interpolation by the fraction
of mana paid. The exact consumer paths are:

### Ether and Fire flight-only modifiers

Ether handler `0x0053CFE0` sets actor byte `+0x160`. Draw `0x005E0460`
temporarily applies white alpha `.5` around the complete `0x00535A30` flight
compositor, so both outer passes and every core/spark/ray draw are halved.
Phase advances from speed `2.4`, hence `7.2` degrees per tick instead of `9`.
The impact actor does not carry/read `+0x160`; impact art, light, and audio stay
normal. Gameplay direct damage is half, quantity is one, and homing moves at
`2.4` with effective turn input `1.2`.

Fire handler `0x0053DC60` sets actor byte `+0x168`. Draw `0x006099C0` wraps
the three Fireball body submissions in white alpha `.5`. Tick `0x005FDD90`
does not read the flag, so its separately registered Fire particles remain
full strength; impact `0x005E5160` and the outbound light are likewise normal.
Direct damage is half and the adjacent secondary/proc payloads are absent.

### Air factory parameter nine

Air handler `0x0053F9C0` passes the underpowered result as parameter nine to
factory `0x00531640`. The factory changes the outer ribbon constructor input
from width `1`, RGBA `(1,1,1,1)` to width `.75`, RGBA
`(.5,1,1,.5)`. Constructor `0x0045B2C0` still performs its native second pass:
at `0x0045B3F4` it halves the input alpha, reconstructs color
`(0,1,1,alpha/2)`, multiplies width by `.75`, and adds phase `15`. The weak
inner ribbon is therefore width `.5625`, RGBA `(0,1,1,.25)`. Both retain the
two-tick body lifetime and independent `0x00534510` tessellation.

The one-shot source corona is unchanged. The endpoint FadeLightning starts at
alpha `.5` rather than one and still subtracts `.2`, yielding visible levels
`.5,.3,.1`. Its ZAnimLit source starts at radius
`.5*(1+U[0,.75))` and intensity `.5`, then retains delta `-.05`. Factory path
MiscLights retain their sampled radii but multiply the one shared intensity by
`.25`. Air still creates the first body/contact; chains and learned status
branches are suppressed in the handler.

### Water forced-Normal quarter-opacity particles

Water handler `0x00543860` changes visual count to
`max(1,trunc(normalCount/4))`; shipped Enhanced Effects On changes two
particles per tick to one. The weak lane never constructs
`Anim_FrostJetEffect_Over`. After Normal construction it multiplies field
`+0x3C` (additive-core alpha) and `+0x4C` (whole-effect opacity multiplier) by
`.25`. Initial additive alpha is therefore `.1875`; the ordinary core's final
alpha is quartered, and opacity `.25` fails the glint gate `>=.899999976`.
Movement, lifetime, obstruction, and Normal tint recurrence otherwise remain
owned by the existing Normal actor.

Gameplay damage is half and the actor query mask narrows from `0x1082` to
`0x2`. Widen/push and the learned Over/Hail/Permafrost/Cold Aura/Harden paths
are absent; weak ColdSlow uses fixed scalar `.75`.

### Earth charge/damage presentation

Earth has no persistent weak render flag. The same Boulder is visible and the
weak branch is expressed through its charge and release bases. Every weak tick
below full charge halves both bases. A charge strictly above `.3` zeros growth;
a value below the edge still takes the `.00125` float32 actor update and only
freezes on the following handler tick. Zero MP can therefore materialize and
retain a Boulder near `0.30125` until release.

Release finalization stores
`max(.25,min((base*charge)*charge,base*1.25))` as the flight damage pool. This
supersedes the Website's former linear `base*charge` contact approximation.
The shell, opening glimmer, called rocks, orientation matrix, rolling loop, and
impact recipe consume the resulting ordinary Boulder state; no generic weak
alpha belongs on them.

## 2026-08-20 Ether Magic Missile tracking correction

### Reopened finding and method

The 2026-08-14 targeting pass stopped at the decompiler's untyped return from
`0x00410D60` and incorrectly promoted it to a normalized signed angular delta.
That made the Website multiply the turn rate by the full angular error. Fresh
read-only Ghidra 12.0.3 decompilation, raw instructions, constants, and xrefs
against the preserved retail `SolomonDark.exe` (4,723,200 bytes, SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`)
show that the helper is a three-valued direction gate instead.

The exact instruction thread is:

- `0x005FD2B5..0x005FD3C7` converts the current float32 heading to a unit
  vector, performs the movement step, stores the new position, and publishes
  it before homing;
- `0x005FD43D` resolves the stable group/slot handle through `0x0045ADE0`;
- `0x005FD44C..0x005FD474` subtracts the new missile position from the live
  target root and converts that delta to a normalized degree heading through
  `0x0042D280`;
- `0x005FD478..0x005FD491` passes current heading first and desired heading
  second to `0x00410D60`;
- `0x005FD49A..0x005FD4B6` multiplies the returned sign by turn input
  `+0x148`, accumulator `+0x14C`, and movement scalar `+0x120`, then adds only
  that step to heading `+0x13C`; and
- `0x005FD4BC..0x005FD502` advances the accumulator by the extracted double
  `0.05000000074505806` while it is at most one, otherwise
  `0.0020000000949949026`, and caps the stored float32 result at `10`.

Helper `0x00410CF0` normalizes each input into `[0,360)`. Raw branches in
`0x00410D60` establish the complete direction table:

```text
gap = abs(current - desired)
if gap <= 1 or gap >= 359: return 0
if desired <= current:
    return -1 if current - desired <= 180 else +1
return -1 if desired - current > 180 else +1
```

The asymmetry at exactly `180` degrees is deterministic: `current=0,
desired=180` returns `+1`, while `current=180, desired=0` returns `-1`.
This is not a proportional controller and it never snaps to the target
heading. For a neutral northbound missile whose post-move target heading is
about `88.28` degrees, the first native correction is exactly `+0.02` degrees
(`2 * 0.01 * 1`), not about `+1.77` degrees.

### Target lifetime and branch ordering

A resolved handle always supplies one steering sample before liveness is
tested. `0x005FD502` reads target byte `+0xF9`; zero clears the handle only
after that tick's heading and accumulator update, while nonzero retains it.
A retained handle does not rerun acquisition's actor-flag-bit test.
A handle that no longer resolves takes no steering sample and does not advance
the accumulator. The rank-one policy byte `+0x150 = 0` then clears the handle
without reacquisition. These orders matter when a target enters its dying
state: keeping only live actors in the Website query erases the native final
sample.

The low-mana branch changes speed from `3` to `2.4` and effective turn input
from `2` to `1.2`; it uses the same sign gate, deadband, accumulator, target
root, and loss ordering. Learned quantity/fan construction, paired
`0.75^ceil(i/2)` turn-input decay, and the non-rank-one retarget policy are
upstream writers of these same fields, not alternate steering formulas.

### Membership sweep

- `MagicMissile 0x7D3` owns the affected vtable tick at `0x005FD270`; its
  direct vtable reference is `0x0079C54C` and its constructor, handler,
  acquisition, resolver, contact, continuation, and destructor remain
  `0x005E4990`, `0x0053CFE0`, `0x00641160`, `0x0045ADE0`, `0x005F1F00`,
  `0x005E4B80`, and `0x005E4F80`.
- `FireMissile 0x7DE`, `BallLightning 0x7DF`, and `FrostMissile 0x7E0` call
  the base tick from `0x005FD550`, `0x005FD720`, and `0x005FD7A0`. They are
  class-owned non-primary-Ether systems; this correction does not change
  their constructors, payloads, painters, or contacts.
- `0x00410D60` has 26 callsites in 21 functions. The Magic Missile call is
  `0x005FD491`. The complete non-Magic set is `0x00449299`, `0x00449A47`,
  `0x0044A7FC`, `0x0045042C`, `0x004505AC`, `0x004768A4`, `0x0047694D`,
  `0x00476E31`, `0x00476E77`, `0x00479025`, `0x0047D1A7`, `0x0047EDCA`,
  `0x00485D00`, `0x00488651`, `0x00489C8A`, `0x0048B4C8`, `0x0050AAF2`,
  `0x005136DF`, `0x0052CCA0`, `0x0052D2DC`, `0x00600D1F`, `0x00608218`,
  `0x0061721E`, `0x00617280`, and `0x006214DB`. They belong to enemy actions,
  enemy/NPC facing, the player control brain, GuidedMissile, Golem, and
  EBoulder; none calls the Magic Missile web kernel.
- `0x00641160` has 11 callsites in nine functions. Only handler call
  `0x0053DB0C` and continuation calls `0x005E4BAD/0x005E4BFE` belong to this
  Magic Missile boundary; the other eight callsites are separate target-query
  consumers.

There is no authored steering table, asset, audio, rendering setting, or
platform-degraded branch in this subsystem. All consumed constants and every
shared-function xref are dispositioned above. Confidence is high from complete
instruction streams and static xrefs; no native tracking unknown remains.

## 2026-08-22 Magic Missile Shoot fan and skill-owned reacquisition correction

The earlier learned-Magic-Missile pass trusted the decompiler's collapsed loop
and did not inspect the branch at `0x0053DC20`. It therefore multiplied both
fan offset and turn decay by raw child index. That finding was false. The later
fixed-tick pass also documented final inactive-target steering correctly, but a
subsequent integration restored the web's pre-liveness filter. This pass
reopens the complete launch/tracking system instead of patching only the
visible More Missiles spread.

### Evidence and exact launch program

The target remains retail `SolomonDark.exe`, 4,723,200 bytes, SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
Fresh read-only Ghidra 12.0.3 decompilation and raw instructions cover
dispatcher `0x0054CAF0`, Magic Missile handler `0x0053CFE0`, its launch loop
`0x0053D9CF..0x0053DC43`, emitter `0x0053B830`, position writer `0x00622D90`,
target query `0x00641160`, base tick `0x005FD270`, resolver `0x0045ADE0`, and
continuation/reacquisition vslot `0x005E4B80`.

The launch loop initializes `sign=+1`, `offset=0`, and `turnScale=1`. For an
even quantity it first adds half of the chosen step (`30` below four missiles,
otherwise `20`) to the caster heading. Each child is then initialized as:

```text
tier(i)       = ceil(i / 2)
heading(i)    = base + (i even ? +1 : -1) * tier(i) * step
turnInput(i)  = 2 * smartSpeedFactor * 0.75^tier(i)
speed(i)      = 3 * smartSpeedFactor
spawn(i)      = StaffEmitter + (0, 10)
probe(i)      = spawn(i) + direction(heading(i)) * 100
```

Raw `NEG` at `0x0053DC1A` flips the sign every child, but
`0x0053DC20..0x0053DC3B` increments offset and multiplies turn scale by `0.75`
only after the positive member of a tier. Thus headings and turn inputs are
paired. For four missiles at neutral Smart Missiles factor one, headings are
`+10,-10,+30,-30` and turn inputs are `2,1.5,1.5,1.125`. Every child calls
`0x00641160` around its own fanned probe. All children share the one damage
roll; every constructor retains visual scale one. More Missiles' authored
`mQuantity` table drains completely to quantities `1..14` (ranks `0..13`),
and low mana forces the separate single-child `speed=2.4`, `turnInput=1.2`
branch.

The dispatcher calls the equipped-item virtual before selecting row 8. The
handler pays the summed row `8/9/10/13/14` mana cost once, plays one launch
cue, registers each actor, and then line-tests caster root to the born root
with mask `0x380`. A blocked birth enters the missile's contact/removal vslot;
it does not invent a different launch direction. Ether Blast's rounded pulse
executes before that shared damage roll and missile loop. Pierce payload and
underpowered suppression remain the previously recovered branches.

### Target retention and Smart Missiles

Initial acquisition and reacquisition are different native operations:

- Initial launch calls `0x00641160` at the 100-unit fanned probe. The helper
  iterates Region actor pointers in stored order, accepts actor flag `0x2`,
  rejects only the explicitly excluded pointer, and replaces the winner only
  on a strictly smaller squared distance below float32 `999999`. It does not
  inspect active byte `+0xF9`, pending-removal byte `+0x05`, actor kind, LOS,
  body radius, or spatial-cell order.
- A retained handle that still resolves always supplies the post-move target
  root to steering. Only afterward does `0x005FD502` read `+0xF9`; zero clears
  the handle after that final sample. Actor flags are not rechecked.
- An unresolvable handle supplies no steering and no accumulator step. If
  policy byte `+0x150` is clear, the handle simply clears. If it is set,
  `0x005FD528` calls `0x005E4B80`, which searches from the missile's current
  root, not a forward probe, and stores a replacement without steering toward
  it until the next tick. If neither query finds a target, the helper clears
  `+0x150`; a projectile born with no handle never begins a free-running
  reacquisition loop.
- A surviving Pierce contact calls `0x005E4B80` with the contacted actor as
  the first exclusion. If that search is empty, it retries with no exclusion;
  only an empty retry clears the policy. This is current-root continuation,
  not initial forward-probe selection.

For pure Ether, handler `0x0053DB93..0x0053DBA7` sets Smart Missiles policy
only when `smartSpeedFactor > 1.01`; authored positive ranks start at `1.10`.
The three derived base-tick siblings keep their class writers: FireMissile
tests its vector speed factor against `1.255`, FrostMissile against `1.0`, and
BallLightning tests its post-`0.85` factor against double `0.860000014`.
Underpowered `0.8` never enables the policy. All four classes then share the
same move, resolve, steer, liveness, and replacement ordering in
`0x005FD270`.

### Membership and dispositions

| Member | Native source | Disposition |
| --- | --- | --- |
| Row 8 rank/damage, one debit, one launch cue, repeated held Staff actions | `0x0054CAF0`, `0x0053CFE0` | exact-ported |
| Row 9 Smart speed/turn and loss policy | `0x0053DB46..0x0053DBA7`, `0x005FD270`, `0x005E4B80` | exact-ported |
| Row 10 quantities `1..14`, odd/even fan, step threshold, paired turn tiers | `0x0053D9D8..0x0053DC43`; authored `mQuantity` table | exact-ported |
| Row 13 Pierce continuation and fallback retarget | `0x005F1F00`, `0x005E4B80` | exact-ported |
| Row 14 Ether Blast pre-launch order | `0x0053CFE0` head and existing Ether Blast report | verified-already-at-parity |
| Full-power and underpowered construction | `0x0053D95D..0x0053DBA7` | exact-ported |
| Initial obstruction, per-tick terrain/contact, impact, render, light, audio, teardown | handler tail, `0x005FD270`, `0x005F1F00`, established presentation report | verified-already-at-parity |
| Hub no-target and Boneyard actor collection | `0x00641160`, Website target projection | exact-ported |
| FireMissile, FrostMissile, BallLightning shared base tracking | `0x005FD550`, `0x005FD7A0`, `0x005FD720` | exact-ported shared state transitions; class payload/presentation verified-already-at-parity |
| Other `0x00410D60` and `0x00641160` consumers | complete prior xref sweeps | out-of-system: independent enemy, NPC, player-brain, Golem, GuidedMissile, EBoulder, and query owners |

There is no platform-blocked member, authored steering table, renderer-owned
homing branch, synchronized per-child RNG, or alternate multiplayer formula.
Authority owns each child identity and tracking state; presentation keeps one
complete radial Ether compositor per actor. No material native unknown remains.

## 2026-08-20 Fireball scenery and terrain-mask closure

The remaining Fire bit-four scenery boundary was reopened because the Website
used the player movement collision world for Fireball lookahead and exposed
only hostile actors to its per-tick point query. Fresh constructor and query
traces against the pinned retail image prove that these are two distinct
contact lanes.

### Per-tick actor/scenery contact

`Fireball::Tick 0x005FDD90` passes actor mask `6` to `0x00641220`. That query
accepts hostile flag `0x2` and scenery flag `0x4` members in the Fireball's
current spatial cell, then applies the strict normalized-circle test using
query radius 20 plus actor radius `+0x30`. A flag-`0x4` contact removes the
Fireball and runs the ordinary impact/audio presentation, but
`Fireball_Contact 0x005E5160` dispatches damage only when target flag `0x2` is
also present.

The complete Boneyard flag-`0x4` membership and constructor radii are:

| Type | Constructor | Actor radius | Fireball consequence |
| ---: | ---: | ---: | --- |
| Tree `2001` | `0x005E46D0` | `8` | contact at strict root distance below `28` |
| Monument `2009` | `0x005E0DB0` | `1` | contact below `21` |
| Gravestone `2029` | `0x005E5C30` | `0.01` | contact below `20.01` |
| Building `2040` | `0x005F2C30` | `1` | contact below `21` |
| Goodie `2061` | `0x005E3D60` | `20` | contact below `40`; Goodie's flags are `0x2004` |

Therefore a stock Fireball **does collide with a gravestone**, but only through
the grave actor's almost-point-sized root circle. It does not collide with the
grave's large promoted movement polygon. Fence posts and derived Fence
members retain actor flag zero and are not candidates under mask 6.

### Five-tick terrain lookahead

Every fifth Fireball update, line walker `0x00524D70` receives exclusion mask
`0x700` and ignores a line record whenever `(record.mask & 0x700) != 0`.
Recovered scenery construction assigns promoted Gravestone polygons mask
`0x600` and intact/broken/gate/rail Fence polygons mask `0x100`; all are
ignored by Fireball lookahead. Monument, Building, and Wall blocking shapes
use mask zero and stop the projectile. Tree, Goodie, and Fencepost are actor
or synthetic player-body colliders rather than Fireball terrain lines.

The implementation contract is consequently two-lane: mask-6 actor-root
contact runs after movement on every tick, while mask-`0x700` terrain
lookahead runs only on the established five-tick cadence. Reusing the full
player navigation polygon set would make graves, fences, trees, goodies, and
posts block at the wrong geometry and often on the wrong tick.

## 2026-08-22 Boulder solid-world collision correction

Fresh instructions for shared Boulder contact owner `0x00620B60` close the
solid-world half of the Earth collision system and correct the earlier
endpoint-only Website interpretation.

On every released flight update the native sequence is exact:

1. save the prior actor root;
2. commit `velocity * speed` to actor `+0x18/+0x1C` at
   `0x00620C2D`;
3. write collision radius `75 * charge` to `+0x30` using the double at
   `0x007845C0`;
4. call movement walker `0x00524180` at `0x00620E8E` over the capsule from the
   advanced root to `advanced root + velocity`, with all three mode bytes zero
   and exclusion mask zero; and
5. if blocked, clear the residual pool before the later mask-`6` actor query,
   then run the concrete terminal path at the already advanced root.

This is a positive-radius swept/capsule query, not point occupancy at the old
or advanced center and not the Fireball's point-sized five-tick line test.
Mask zero means no authored movement member is excluded. The complete stock
membership is Tree root circles, all Monument polygons, every Gravestone root
circle plus the promoted overlay-`>=7` grave polygon, all Building polygons,
Goodie circle/footprint, Fence endpoint posts and derived intact/broken/gate/
rail/wall shapes, dynamic Gate leaves, Terrain records, and the Arena boundary.
The collision result is therefore allowed to hit both the small Gravestone
root primitive and its separately authored promoted geometry.

Release finalizer `0x005E5450` does write the transitional radius
`45 * charge`, but its only trailing call is `0x00462010`, whose entire body is
`RET 0x10`. It performs no world query. Treating `45 * charge` as an immediate
release collision probe is a falsified inference; the first solid-world test
is the released flight path above at `75 * charge`.

The direct shared-function membership is ordinary `Boulder 0x7D5` and
`EBoulder 0x7E1` (`0x00621450 -> 0x00620B60`). Hasten Rocks, Bind Rocks, Rock
Surge, and Gargantuan change upstream charge/pool inputs but not this geometry.
`Hailstones 0x7E4` inherits a vtable address but its reachable released path
uses the separately recovered per-rock substeps at `0x005FBDE0`, so it is not
a whole-carrier member. Ordinary and Ethereal terrain retirement both own
their already-recovered full breakup/audio teardown; dropping an EBoulder
silently on solid contact is not native.

Evidence is the pinned retail image above, fresh Ghidra 12.0.3 read-only
decompilation of `0x00620B60`, `0x00524180`, and `0x005E5450`, instructions at
`0x00620E28..0x00620E9E` and `0x005E54DB..0x005E5522`, and the existing full
authored collision-primitive inventory. Confidence is high; there is no
unextracted table, collision mask, cadence, or sibling carrier branch in this
boundary.

## 2026-08-22 held one-shot Staff action handoff

A held Ether report reopened the boundary between repeated one-shot admission
and the wizard equipment-pose writer. Fresh read-only Ghidra 12.0.3 evidence
uses the pinned retail image above; this is instruction-derived native truth,
not a browser inference.

`PlayerActorTick` tests the held primary level and current action occupancy at
`0x0054961A..0x005496C6`. When the level remains held and the prior action is
gone, `0x005496C1` calls the existing one-shot startup path `0x0052DA80` in the
same player tick. Only the released/no-action branch at
`0x005496C8..0x005496D6` writes idle equipment pose `0` to actor `+0x238`.

`Action_PlayerWizard_StaffCast1` construction at `0x0044B170` initializes its
progress, marker, end, frame array, and actor link. It does not write
`actor+0x238`; its only adjacent actor presentation write is zeroing
`actor+0x23C`. The successor's insertion tick therefore retains the previous
action's last visible `K`. On its first fixed action tick,
`0x0044B370` selects `frames[trunc(progress)]` and writes the next `K` to
`actor+0x238`. Every later held one-shot action then runs the same complete
Staff Cast 1 program again: branch A `[1,8,7,7,7]` or branch B
`[8,7,7,7,7]`. Stock avoids an inserted idle-pose flash between actions, but
it does replay the cast program for every emitted shot.

The complete direct membership is pure Ether `8`, pure Fire `16`, and welded
one-shots `1000`, `1001`, `1002`, and `1009`; all route through
`0x0052DA80` and item-selected Cast 1 mode `3`, `6`, or `9`. Pure Air `24`,
Water `32`, Earth `40`, welded channels `1003..1005`, and welded persistent
casts `1006..1008` instead use renewed Constant actions and retain their
already recovered constant-pose lifecycle. Staff mode `3` is the reported
branch. Bare-hand mode `6` and Wand mode `9` are sibling pose programs, not
alternative Staff rows.

This finding corrects only the action-handoff wording. It does not change
projectile cadence, marker timing, mana, targeting, audio, or the previously
recovered pose arrays. A Website policy that holds one release pose across
successive one-shot actions is an explicit presentation override rather than
retail parity and must be identified as such in the web ledger.

## 2026-08-23 primary collision and target-priority reopening

The earlier Fireball scenery closure stopped at the first point-query result,
the Ether closure did not follow either line-query mask into the Website, and
the Lightning inventory promoted Gravestone alone even though four sibling
constructors write the same flags and priority. Those were extractable native
branches. This section supersedes the incomplete collision/priority wording in
the 2026-08-14 and 2026-08-20 sections.

Evidence is the retail 0.72.5 `SolomonDark.exe`, 4,723,200 bytes, SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`,
preferred image base `0x00400000`. Ghidra 12.0.3 read-only replicas supplied
the instruction facts below. A loader-injected read-only run on 2026-08-23 is
supporting runtime evidence: at a 1600-by-900 stock surface it read
`App+0x1D0/+0x1D4 = 1600/900`, `App+0x1DC/+0x1E0 = 1600/900`, and a live
player cell with one actor in slot zero. Its runtime cell vtable rebased to
preferred `0x00793A00`, the `PointerList<Object*>` table used below.

### Exact spatial order

Point query `0x00641220 -> 0x00522E30`, polygon query `0x00642940 ->
0x005235F0`, and cone query `0x00641500 -> 0x00522F50` consume each 100-unit
cell's `PointerList<Object*>` in ascending slot order. The complete order
lifecycle is now closed:

- actor registration `0x0063F6D0` reaches the actor attach vslot and
  `0x005212F0`, which appends to the resolved cell;
- `WorldCellGrid_RebindActor 0x005217B0` does nothing while the computed cell
  is unchanged; on a change it calls old-cell vslot `+0x1C`, then new-cell
  vslot `+0x10`, and writes actor `+0x54`;
- live cell vtable `0x00793A00` resolves `+0x10 -> 0x00402720 ->
  0x004013C0/0x004013E0`, which inserts at `count`, so destination insertion is
  a tail append;
- its `+0x1C -> 0x004014B0`, `+0x20 -> 0x00402770` removal finds the pointer,
  shifts every later pointer down by one, clears the old tail, and decrements
  count. Removal is stable compaction, not swap-with-last;
- actor death clears flags `+0x14` at `0x0063E7C0`, so a retained death actor
  no longer survives the mask filter even before final manager retirement.

Thus the exact web projection requires two distinct stable orders: manager
registration order for `0x00641160` Magic Missile acquisition, and cell-binding
order for cell broadphases. Same-cell movement preserves both. Cross-cell
movement preserves manager order but assigns a new destination-tail cell
order. Static authored objects bind before later wave actors; every later
targetable spawn appends at its actual registration edge.

### Fireball hostile-over-scenery precedence

After Fireball moves, `0x005FDD90` point-queries radius `20`, mask `6`. A
flags-`0x2` result contacts immediately. A first result without bit `0x2`
(therefore a flags-`0x4` scenery actor) enters the previously omitted branch at
`0x005FDFA4..0x005FE1F6`:

1. normalize Fireball velocity `D`;
2. form perpendicular `Q=(D.y*20,-D.x*20)`;
3. build polygon `[P+Q, P-Q, P+W*D-Q, P+W*D+Q]`, where `W` is the live integer
   at `App+0x1DC`;
4. `0x00642940` counts mask-`2` actor roots inside that polygon, excluding type
   `0xBB9`;
5. if at least one exists and squared root distance from Fireball to the first
   scenery candidate is greater than or equal to exact float `2.0`, skip
   contact for this tick. Strictly below `2.0`, contact still occurs.

The polygon point test is ray casting `0x00405160`: each edge toggles only when
`y < current.y` differs from `y < previous.y` and `x` is strictly below the
computed crossing. This branch gives a hostile in the forward 40-unit-wide,
live-viewport-length corridor precedence over an earlier cell-slot scenery
candidate. It deliberately does not rescan and contact the hostile in the same
tick. The existing final Fire particle still emits.

Fireball birth and age-divisible-by-five line checks remain mask `0x700`.
Tree, Monument, Gravestone, Building, and Goodie retain the previously
extracted radii and flags. The new finding changes precedence, not membership,
terrain masks, impact presentation, damage partition, or teardown.

### MagicMissile inheritance-family collision masks

Pure Magic Missile handler `0x0053CFE0` tests caster root to each born root
with exclusion mask `0x380` at `0x0053DBC2..0x0053DC14`. FireMissile
`0x0053E6A0`, BallLightning `0x0053EDB0`, and FrostMissile `0x0053F3C0`
perform the same initial class-family test. Constructors `0x005E4990`,
`0x005E4C50`, `0x005E4F30`, and `0x005E4FB0` all write `0x700` to actor
`+0x38`. Shared tick `0x005FD270` passes that field to line walker
`0x00524D70` on every age-divisible-by-five flight lookahead.

Shared contact probe `0x005E4A80` uses radius `6` and mask `2` while age is
strictly below `200` and target-handle byte `+0x140` is not `-1`. At age
`>=200`, or as soon as the handle is absent, it uses mask `6`. The first
qualifying current-cell slot wins. Consequently Tree, Monument, Gravestone,
Building, or Goodie can consume any of the four family members after widening;
the concrete contact callbacks dispatch gameplay only for bit-`2` actors but
always own their class impact and retirement. `GroundSpark 0x7E5` is not a
member: it has a distinct constructor, tick, contact geometry, and handler.

### Lightning priority membership

Cone query `0x00641500` first rejects pending actors, the excluded pointer, and
type `0xBB9`, then applies angle, Region LOS, and strict range. Selection is
lexicographic: a lower signed integer at actor `+0xFC` wins regardless of
distance; equal priority replaces only on a strictly smaller squared distance;
an exact tie preserves earlier cell traversal order.

Base Puppet constructor `0x006287D0` writes priority `0`. Constructors Tree
`0x005E46D0`, Monument `0x005E0DB0`, Gravestone `0x005E5C30`, Building
`0x005F2C30`, and Goodie `0x005E3D60` each write flags containing `0x4` and
priority `1000`. Their vtables all resolve attachment slot `+0x34` to
`0x00448D50`, returning `(0,0)`. All five are therefore native Lightning
fallback candidates. Coffin remains excluded because its constructor clears
the query flags. Chain query `0x00641340` remains mask `2`, nearest unused, and
does not inherit the scenery fallback.

Goodie's unlock/open timer does not retire its actor. Flags `0x2004` remain
query-visible after the tick-250 contents materialization, so an opened Goodie
continues to be a valid flags-`4`, priority-`1000` fallback.

### Membership disposition

| Member | Disposition | Contract |
| --- | --- | --- |
| Fireball `0x7D4` birth/flight masks, point query, corridor precedence | exact-ported | masks `0x700`, radius/mask `20/6`, live viewport polygon, strict `d2 < 2` exception |
| MagicMissile `0x7D3` | exact-ported | birth `0x380`, flight `0x700`, radius `6`, dynamic mask `2 -> 6` |
| FireMissile `0x7DE` | exact-ported | inherited masks/query; class Fire impact on scenery |
| BallLightning `0x7DF` | exact-ported | inherited masks/query; class Lightning fade on scenery |
| FrostMissile `0x7E0` | exact-ported | inherited masks/query; class Frost fade on scenery |
| GroundSpark `0x7E5` | out-of-system | distinct non-MagicMissile collision owner |
| Lightning primary acquisition | exact-ported | priority then distance; exact-tie cell order |
| Tree, Monument, Gravestone, Building, Goodie | exact-ported | complete flags-`4`, priority-1000, zero-attachment membership |
| living hostile actors and Maggots | exact-ported | priority zero, flags two, exact manager/cell order |
| Coffin | verified-already-at-parity | flags zero; never eligible |
| Water/Earth cell broadphase traversal | exact-ported shared order only | their class-specific contact consequences are separate owners |
| Hub primary collision | out-of-system | Website shared Hub is authoritatively noncombat |

No member is blocked by the browser platform. The caster's current logical
viewport width is ordinary authoritative input in the web architecture and can
drive the same Fireball polygon without client-side collision ownership.

## 2026-08-23 Staff Cast 1 phase edge and exact held cadence reopening

The equipped-effect phase and one-shot cadence were reopened after the Website
Staff orb again appeared oversized and held Ether was suspected of firing too
quickly. The prior reports correctly recovered the Staff Cast 1 rate and strict
end comparison, but they used absolute capture indices as web duration
constants and did not state that the `+0x268` write is marker-owned rather than
action-occupancy-owned.

Evidence uses the pinned retail 0.72.5 image, 4,723,200 bytes, SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`,
preferred base `0x00400000`. Fresh Ghidra 12.0.3 read-only replicas covered
`Action_PlayerWizard_StaffCast1` construction/tick
`0x0044B170`/`0x0044B370`, shared progress tick `0x004486E0`, player callback
`0x00550180`, one-shot admission `0x0052DA80`, and player decay
`0x00548FFC..0x00549012`.

### Marker ownership and phase recurrence

`0x0044B170` initializes progress `0`, rate float32
`0.07500000298023224`, marker `1`, and strict end `4`. The action tick calls the
player callback only when `0x004486E0` reports the marker crossing. For mode 3,
the callback dispatches the selected one-shot and the instruction at
`0x005502F6` writes float32 `0.15000000596046448` to PlayerWizard `+0x268`.
No mode-3 instruction writes that value merely because the action remains
occupied. Player tick `0x00549012` independently stores
`float32(phase * 0.8999999761581421)` once per fixed tick.

A supporting loader-injected read-only write watch on a staged byte-identical
Ether process (PID 2424, runtime image base `0x00960000`) observed runtime
`0x00AB02F6` write bytes `9A 99 19 3E` exactly once for a short cast, followed
only by runtime `0x00AA9012` decay writes. During a 1.4-second held burst the
same marker writer appeared at write-hit indices `69`, `125`, and `181`.
Because each marker adds one extra write beside the per-tick decay, both gaps
are exactly `55` native fixed ticks. This runtime trace supports the static
instructions; it is not clean-stock visual evidence.

The sibling Constant action is also edge-owned. Mode 5 tests
PlayerWizard `+0x26C`, then `0x00550317` writes float32 `0.25`. A supporting
held-Air write watch (PID 2088, runtime image base `0x00460000`) observed one
runtime `0x005B0317` write followed only by `0x005A9012` decay writes during
the sampled hold. It did not refresh `0.25` on every occupied primary tick.

### Exact neutral one-shot clocks

The action recurrence, rather than a cooldown, owns both families:

| Family | Native progress rate | Marker update | Completion update | Next held insertion / repeat |
| --- | ---: | ---: | ---: | ---: |
| Ether `8` | `float32(0.075)` | `14` | `54` (`4.050001621246338`) | `55` ticks / `0.55 s` |
| Fire `16` | `float32(float32(0.075) * 0.75)` | `18` | `72` (`4.050002574920654`) | `73` ticks / `0.73 s` |

The completion update still owns the action. On the following player tick the
slot is absent and held input queues the successor. The existing native Fire
golden independently records insertion at tick `15981`, marker/pose transition
at `15999`, last occupied action at `16053` with progress `4.05000257`, and
idle at `16054`. Thus insertion-relative values are `18`, `72`, and `73`; the
older labels `19` and `74` were capture indices relative to the preceding
idle sample, not action durations.

Faster Caster remains the multiplier returned by `0x00656580`. Applying the
authored factors to the float32 rate changes the first strict marker/end
crossings; it does not add a cooldown. The Website may retain a normalized
progress clock only if its crossing and one-tick teardown rules reproduce the
float32 recurrence for every authored factor.

### Complete direct membership

Pure Ether `8`, pure Fire `16`, and welded one-shots
`1000,1001,1002,1009` share Cast 1 modes `3` (Staff), `6` (empty hand), or `9`
(Wand), the single `0.15` callback edge, held re-admission, and exact rate
multiplier. Pure Air `24`, Water `32`, Earth `40`, and welded Constant builds
`1003..1008` share the one-time `0.25` start edge and subsequent decay.
Projectile creation, mana, target selection, sockets, audio, collision,
contact, and teardown remain owned by their already recovered concrete
handlers. No browser constraint prevents exact fixed-tick reproduction.
