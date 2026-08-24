# Native lighting and shadow system

## Scope, binary identity, and method

This is the authoritative engine-wide lighting and projected-shadow chart for
the retail Windows executable. It supersedes earlier notes that treated a
preserved user profile as the shipped default, described the generic projected
edge as source-facing, or treated every visible glow as one rendering lane.

- Binary: `SolomonDark.exe`, 4,723,200 bytes, SHA-256
  `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
- Static evidence: read-only Ghidra 12.0.3 replicas of the pinned project,
  instruction dumps from the retail PE, vtables, xrefs, and recovered atlas
  records. No stock process was launched or modified for this pass.
- Confidence: high for settings defaults, manager layout, collection order,
  source formulas, falloff, containment, raster composition, analytic tint,
  directional-record construction, painter ownership, and the enumerated
  shadow programs. Presentation RNG sample identity remains global-stream
  dependent and is called out separately.

## The four lanes

Native lighting is not a single list of colored circles. A frame has four
related but distinct lanes:

1. **Persistent provider lane.** Arena walks the ordered provider pointer list
   at `Arena +0x8D80` (`count +0x8D8C`) and calls vtable slot `+0x30`.
2. **One-tick miscellaneous lane.** Fixed-tick effects append 0x1C-byte
   `MiscLight` records through `0x0044F4B0`. `Region::Tick 0x0063EFC0` clears
   their count at `0x0063F078`; Arena replays them after every provider.
3. **Raster lane.** Each accepted submission stamps DeadHawg record 18 into a
   quality-scaled offscreen target. `0x0057D670` then multiplies the already
   painted underlay by that target.
4. **Analytic lane.** The same accepted source is indexed into a spatial grid.
   World painters query the maximum local scalar for tint, and flagged sources
   additionally create class-owned directional-shadow records.

Collapsing these lanes loses observable order. In particular, a false-flag
provider can be suppressed by an earlier source, while a true-flag MiscLight
appended at the tail bypasses suppression without retroactively changing which
earlier false-flag providers survived.

### Persistent provider order and registration lifecycle

`Region::Tick 0x0063EFC0` clears provider count `+0x8D8C` at `0x0063F12D`,
then ticks the stable actor manager `+0x310` at
`0x0063F127..0x0063F139` before transient manager `+0x8B70` at
`0x0063F162..0x0063F168`. `ObjectManager::Tick 0x004022A0` walks backing slots
ascending and re-reads the count, so an object appended by an earlier actor may
itself tick later in the same pass. Provider append helper `0x00483430` stores
the owner pointer at `Arena+0x8D80[count]`; Arena render consumes that array
from index zero upward before the Misc array. Duplicate Archer/Mage enrollments
are duplicate adjacent calls of the same owner pointer, not separate source
objects.

Region activation realizes world actors before publishing players, then
registers gameplay player slots `0..3` through Arena vslot `+0xD0`
(`0x005CBCF5..0x005CBD2E -> 0x00641090`). The scripted Solomon_Dig opcode later
registers Dig and then Lantern (`0x00465AE4`, `0x00465B45`). Object-manager
removal stably compacts slots; spatial rebind `0x005217B0` does not touch this
order; a true detach/re-attach appends at the destination tail.

Due wave actors are earlier still within a fixed tick. Arena calls TimeLine at
`0x0046E641..0x0046E646`; TimeLine ticks its Spawner manager at
`0x0046E483..0x0046E493`; Spawner registers the enemy at
`0x0046D313..0x0046D31C`; `0x0063F6D0` appends it to `+0x310` at
`0x0063F714..0x0063F73A`. Only afterward does Region traverse that manager.
Player spell births occur at the earlier player slots, while enemy projectiles
born by later enemies append after them. A web authority must therefore retain
lane-local registration ordinals, allocate wave actors immediately, and defer
same-tick later-enemy projectile registrations until the earlier player births
have committed. Sorting grouped snapshot arrays is not equivalent.

## Settings, capability gate, and defaults

Initializer `0x005BAB60` first derives platform capability byte
`0x00B3BCAE`. It is one for platform strings `WIN`, `MAC`, and `LINUX`, and
zero otherwise. Missing config keys then use the following defaults:

| Setting | Global | Missing-key default on shipped Windows | Native consequence |
| --- | ---: | --- | --- |
| `Game.ComplexLighting` | `0x00B3BCA8` | true | analytic object tint, directional-record construction, and early raster composite |
| `Game.ComplexShadows` | `0x00B3BCA9` | true | class shadow painters consume directional records |
| `Game.MultipleShadows` | `0x00B3BCAA` | capability byte = true | providers that use this setting submit a true directional/containment-bypass flag |
| `Game.FastCPU` / Enhanced Effects | `0x00B3BCAD` | capability byte = true | higher effect density and, for Air path lights, a true directional flag |
| `Game.LightQuality` | `0x00B3BCA4` | `0.25f` when FastCPU is true; `0.05999999865889549f` otherwise | offscreen light-target resolution and manager query transform |

The relevant config branches are `0x005BAD9F..0x005BAE98`, the platform
capability is established at `0x005BABF9..0x005BAC9D`, FastCPU is loaded at
`0x005BB310..0x005BB34F`, and LightQuality at
`0x005BB542..0x005BB59D`.

The preserved `SolomonDarkAbandonware/sandbox/settings.txt` is a user profile,
not a missing-key oracle. It explicitly stores `MultipleShadows=false`,
`FastCPU=false`, and `LightQuality=0.060000` while keeping Complex Lighting and
Complex Shadows true. Any comparison must name whether it uses fresh Windows
defaults or that overridden profile.

## Manager construction and target quality

`Arena::Create 0x00470A90` calls light-manager initializer `0x0057DF20` with
logical Arena width and height, query/view values at `Arena +0x8BC4/+0x8BC8`,
and `Game.LightQuality`.

- The offscreen texture is square. Its side is integer conversion of
  `max(logicalWidth, logicalHeight) * LightQuality`.
- Manager field `+0xC4` initially stores quality, then is multiplied by exact
  `0.8` for query/raster transforms.
- The expanded query rectangle adds `350 * quality` to one retained extent.
- The source spatial grid uses float32 `150`-unit cells. Base constructor
  `0x0057DB90` fixes two padding cells at manager `+0xD8`. Initializer
  `0x0057DF20` computes each interior dimension as
  `ceil(float32(worldExtent / 150))`, then adds four cells. Consequently the
  valid logical cell range is `-2 .. ceil(worldExtent / 150) + 1` on each
  axis; this is a finite padded grid, not an unbounded hash plane.
- A browser implementation may expose logical dimensions while using render
  target resolution `deviceResolution * LightQuality`; rendering a full-DPR
  light field is not native and wastes fill rate and memory bandwidth.

Frame reset `0x0057D4E0` binds the target, clears it opaque black, installs the
target transform, and clears the accepted-source count. Restore
`0x0057D5E0` returns to the main target.

## Submission ABI and accepted-source record

Generic submitter `0x0057FE40` takes:

```text
(sourceX, sourceY, queryX, queryY, radius, intensity, castsDirectionalShadow)
```

The sibling player submitter is `0x00580130`. For an accepted source, the
0x1C-byte record is:

| Offset | Meaning |
| ---: | --- |
| `+0x00/+0x04` | source world point |
| `+0x08/+0x0C` | query/raster point |
| `+0x10` | radius scalar |
| `+0x14` | intensity |
| `+0x18` | directional/containment-bypass byte |

The source is culled against the manager view first. A false-flag source then
calls containment query `0x0057E2F0`. An earlier accepted source suppresses it
only when all of these hold:

```text
existing.intensity >= candidate.intensity
existing.radius >= candidate.radius
distance(existing, candidate)^2
  < ((existing.radius - candidate.radius) * 145)^2
```

The boundary is strict. True-flag sources bypass containment. Accepted records
are indexed by `0x0057FC00` across every 150-unit grid cell touched by their
145-radius-scaled AABB. Both single-cell lookup `0x0057D870` and insertion
store each float32 quotient before converting it with `0x00747360`, whose
ordinary path is signed truncation toward zero. The exact coordinate is
`trunc0(float32(float32(value) / 150)) + 2`; negative fractions therefore map
to logical cell zero rather than the preceding floor cell. Insertion clamps
the converted AABB endpoints to the finite allocation, whereas a point lookup
outside it returns no cell. Grid cell vectors use generation tags; the manager
does not linearly clear every cell each frame.

The provider-stage view cull is part of the submission ABI, not ordinary
resident visibility. Arena vslot `+0xF4 -> 0x004620D0` supplies
`query = source - (Arena[+0x8BCC], Arena[+0x8BD0])`. Submitters scale that point
and analytic reach by manager `+0xC4 = float32(LightQuality * 0.8)`, then call
circle/rectangle test `0x004637C0` against manager rectangle `+0xE8..+0xF4`.
The rectangle is `(0,0,targetSide,targetSide + LightQuality*350)`, where
`targetSide = max(logicalWidth,logicalHeight)*LightQuality`; exact tangency is
rejected. Equivalently, before the common LightQuality factor, the query-space
rectangle is `(0,0,maxDimension/0.8,(maxDimension+350)/0.8)` and the circle
radius is `145*analyticRadius`. A miss emits no raster stamp, accepted record,
or grid entry. This happens before containment even for true-flag sources.

Player provider `0x005299A0 -> 0x00580130` has a wider ABI than the generic
submitter. Its analytic radius and raster-glyph scale are independent:

```text
source = playerRoot + headingUnit*15
analyticRadius = (1 + overlayPhase) * 2.5999999046325684
               + (levelUpTicks > 0 ? sin(pi*levelUpTicks/180) : 0)
rasterGlyphScale = 2.5999999046325684 - U(0.2)
intensity = 1
directionalFlag = true
```

The raster draw uses `rasterGlyphScale`; analytic tint, containment, view-cull
reach, grid coverage, and directional records use `analyticRadius`. The random
glyph-scale draw occurs before the view cull, so an otherwise eligible but
offscreen player consumes it; a player suppressed by its earlier drive/local
gate consumes none. Generic sources use their one radius for both values.

`PlayerWizard 0x005299A0` submits only when animation drive `+0x160==0` or
player slot `+0x5C==0`. Slot zero is the process-local actor, not the authority
host. Thus a remote casting/dying/spectating actor is suppressed, while the
same browser's local actor remains eligible in those drive states. Overlay
phase `+0x268` is fixed-tick state: native action callback `0x00550180` writes
`0.15` for StaffCast1, `0.25` for StaffConstant, and `0.45` for the sibling
Cast2/constant modes; `PlayerWizard::Tick 0x00548B00` then stores
`float32(phase*0.8999999761581421)` before render. The level-up timer `+0x168`
is armed to 180 by a true level transition through
`0x0067C250 -> 0x005C88B0 -> 0x00528A20` and decrements on later actor ticks.
Neither field can be reconstructed exactly from visible pose, current level,
or render age after a join/resync.

A 2026-08-22 full offset-access recheck also closes the phase's adjacent visual
consumer. Equipped attachment compositor `0x00538B80` receives ordinary actor
scale and does not read `+0x268`. Element helper `0x0053B1D0` alone applies
`actorScale * (1 + 10*overlayPhase)` to the equipped element effect at reads
`0x0053B2DB`, `0x0053B3CD`, and `0x0053B62F`. The phase therefore enlarges the
element effect and analytic light, never the staff or wand raster.

## Raster product and scene boundary

The raster product binds DeadHawg record 18, the registered 336x305 crop of a
336x336 white alpha field with registration `(168,153)`. It is drawn at the
query point with sprite scale `radius` and alpha `intensity`. The target
transform supplies LightQuality; the sprite scale must not also be multiplied
by quality.

Compositor `0x0057D670` uses blend state 2. Dispatcher `0x004208A0` maps that
to source `ZERO`, destination `SRCCOLOR`, so the result is:

```text
mainFramebuffer = mainFramebuffer * lightTexture
```

`Arena::Render 0x0046EC80` performs this order when Complex Lighting is on:

```text
reset light target
provider vslot +0x30 calls in provider-list order
MiscLight replay in append order
restore main target
direct underlay/base/compact painting and shared-queue gather
multiply light target at 0x0046FAFF
shared painter queue flush at 0x0046FDAF
late world managers/proxies/foreground
screen feedback and HUD
```

When Complex Lighting is off, common world tint is forced to one and the
composite moves to `0x00470107`, after the shared queue. That is a real retail
low-cost branch, not permission to omit the raster target.

## Analytic falloff and object tint

Ordinary scalar query `0x0057F980` takes the maximum contribution, never a
sum. For query delta `(dx,dy)`, source radius `r`, and intensity `i`:

```text
d2 = (dx / r)^2 + (dy / (0.85*r))^2

d2 < 75^2:   scalar = i
d2 >=145^2:  scalar = 0
otherwise:   scalar = i * (1 - (d2 - 75^2) / 15400)
```

The transformed sibling query is `0x0057E490`. Common Puppet dispatcher
`0x00624B40` rebuilds the object's local light/shadow state for the current
render, stores the scalar at object `+0xCC`, applies it to the requested tint,
invokes class drawing, then restores renderer state. Direct self-luminous
wrappers that call child draw slots without this dispatcher do not inherit a
Region sample merely because their class name contains `Lit`.

Final RGBA packing follows `0x0041FE50 -> 0x0041FEEB..0x0041FF45` and helper
`0x00747360`: in-range channels multiply by double 255 and truncate toward zero.
A white object at scalar `0.5` therefore receives byte 127, not 128. Browser
analytic tint must use truncation; rounding introduces a systematic one-byte
brightness error across the scene.

### Building elevated-surface query and retained vertex grid

The generic root-scalar rule does not own Building art. A fresh complete
caller/callee pass on 2026-08-22 corrected the earlier inference that the late
Building upper sprite retained white caller color. `Building::Render
0x0060E940` replaces the generic color with a retained vertex-colored mesh
whenever `Game.ComplexLighting` is enabled. `Building::RenderUpper
0x0060EC50` later draws the upper/roof glyph with its own positions and UVs but
the exact same color array at Building `+0x168`. Base and roof therefore share
one current lighting result even though the roof remains in slot `+0x24` after
the shared queue.

Lazy mesh initializer `0x0060E5B0` calls glyph tessellator `0x00417510` for
both DeadHawg base rows `148..151` and upper rows `152..155`. The tessellator
clamps each dimension to at least two, emits row-major bilinear positions and
UVs over the complete glyph quad, and indexer `0x00416B80` emits two triangles
per cell in this order:

```text
(row,col), (row,col+1), (row+1,col)
(row,col+1), (row+1,col), (row+1,col+1)
```

`Game.FastCPU` / Enhanced Effects selects a `3 x 3` grid when true and a
`2 x 2` grid when false. Every Building selector is covered. Selectors `0`
and `1` shift only the lighting query positions in every row except the last
by `+135` and `+100` world Y respectively; selectors `2` and `3` use zero
offsets. The offsets never move raster geometry or UVs. Each base-grid point,
plus the Building root and that selector offset, is transformed through the
Arena and sampled by `0x0057E640`. The resulting grayscale scalar is packed
through the ordinary truncate-to-byte color path before interpolation.

The specialized query has exactly three direct xrefs: Building
`0x0060EA84` and the two endpoint samples inside shared Wall/ZFightHelper
painter `0x0061DF40` at `0x0061DF7E` and `0x0061DFBC`. For a query point `q`
and each locally indexed source `s`, let `c(q,s)` be the ordinary elliptical
contribution above. With the Region ambient scalar reset to zero by
`0x0057D4E0`, `0x0057E640` returns:

```text
radial   = max_s c(q,s)
height_s = 1                                      when q.y <= s.y
           max(0, 1 - (q.y - s.y) * 1.5 / 145)  when q.y >  s.y
elevated = max_s (c(q,s) * height_s)
surface  = radial * elevated
```

The constants are retail doubles `0x007DE860 == 1.5` and
`0x00794E50 == 145`. This is a product of two independently maximized lanes,
not a root sample, an average, a sum, or the ordinary contribution squared per
source. Different sources may own the two maxima.

When Complex Lighting is off, both Building painters bypass the grid and draw
their glyphs with ordinary white caller color. Monument is the negative
control family: `Monument::Render 0x0060E210` has no call to `0x0057E640` and
draws all 21 DeadHawg rows `156..176` under the common dispatcher root scalar.
Its shadow painter `0x0060E280` changes no main-art color. Wall owns the other
`0x0057E640` consumer through its separate generated-mesh painter, while
ZFightHelper is an internal endpoint helper rather than Building/Monument art.

## Persistent provider census

The formulas below use `U(a)` for stock unsigned `RandomFloat(a)` on its
inclusive discrete `[0,a]` lattice, `S(a)=+/-U(a)` for the signed form selected
by the helper's second argument, `I(n)` for `RandomInt(n)`, and `MS` for the
current `Game.MultipleShadows` byte. Unless a separate query point is stated,
source and query are the object's current root.

That lattice is instruction-derived rather than interval shorthand. RNG
constructor `0x00401110` stores denominator `100000` at state `+0xE4`.
`RandomFloat 0x00401310` calls `RandomInt(100001,false)`, stores the integer as
float32, divides by 100000 and stores float32, multiplies by the float32 maximum,
and stores float32 again (`0x00401314..0x00401342`). Signed mode then consumes
an independent `RandomInt(2)` word and conditionally negates the magnitude
(`0x00401347..0x00401390`), including the possible negative-zero result.
`RandomInt` `0x00401170` masks through the next power of two and then applies
modulo, so `I(9)` is the native biased integer reduction over `0..8`, not a
scaled unit float.

The Website cannot reproduce the stock process-global sample identity without
replaying every intervening RNG consumer. Its bounded presentation policy feeds
a stable semantic 32-bit owner/frame word into the exact native mask/shift,
power-of-two reduction, inclusive 100,001-point lattice, independent sign draw,
and float32 store schedule. This preserves domain, endpoints, bias, and draw
arity while explicitly not claiming cross-owner stock-stream correlation.
Separately, both submission functions receive float32 stack arguments and
store float32 accepted records. A port must normalize source/query coordinates,
radius, intensity, and the player-only raster scale once at admission, then use
the normalized values consistently for cull, containment, raster, grid, scalar,
and directional-shadow work.

### Actor and world providers

| Provider | Owners | Radius | Intensity | Flag / gate |
| ---: | --- | --- | --- | --- |
| `0x00474970` | DemonSkull | `2 * actor[+0x74]` | actor `+0x210` | `MS`; only while class resource enabled; source/query include `+0x228/+0x22C` offset |
| `0x004779E0` | Skeleton | `0.5` | `+0x244 * (0.5 + U(0.5))` | `MS` |
| `0x00478180` | SkeletonArcher | charged lane: `+0x24C*(0.5+S(0.1))`; ordinary lane: `0.5` | charged: `0.75*+0x24C`; ordinary: `+0x244*(0.5+U(0.5))` | `MS`; charged lane gated by fields `+0x240/+0x150` |
| `0x004783E0` | SkeletonMage | same two lanes as Archer | same two lanes as Archer | `MS`; charged lane requires `+0x24C>0` |
| `0x00478CC0` | Imp, GreenImp, GoodImp | `0.25 + S(0.1)` | `+0x230 * (0.75 + U(0.25))` | false |
| `0x00478E00` | Wraith | `0.5` | `+0x230 * (0.5 + U(0.5))` | `MS` |
| `0x00479470` | Demon | `1.5 + S(0.25)` | `1`, or `0.5+U(0.5)` in its alternate byte-`+0x94` state | `MS`; resource gate |
| `0x00479EA0` | Coffin | `0.65` | `1 - 0.1*I(9)` | `MS` |
| `0x00479F80` | DireFaculty | `0.75 + U(0.1)` | `I(2) * +0x214` | `MS`; resource gate |
| `0x0047A040` | Heartmonger | `0.75` | `0.5 + U(0.100000024)` | `MS`; resource gate |
| `0x0047BED0` | Portal enemy/spawner | `+0x220 * (0.9 + U(0.350000024))` | `+0x220` | `MS` |
| `0x005299A0 -> 0x00580130` | Player | analytic `(1+overlay)*2.5999999046325684 + level sine`; raster `2.5999999046325684-U(0.2)` | `1` | true; point 15 units along heading; submit iff drive zero or process-local slot |
| `0x005EA110` | GameNPC | `0.75`, or `2.6` in state 3 | `0.9 + U(0.100000024)` | `MS` |

### Projectile, wrapper, and effect providers

| Provider | Owners | Radius | Intensity | Flag / gate |
| ---: | --- | --- | --- | --- |
| `0x005E48E0` | `ZAnimLit` | wrapper `+0x140` | `min(+0x144,1)` | local `+0x14C & MS`; child root |
| `0x005E4AF0` | MagicMissile, FireMissile, BallLightning, FrostMissile, GuidedMissile, SkullMissile | `0.75 + U(0.1)` | `0.75` | `MS` |
| `0x005E50D0` | Fireball | `1 + U(0.25)` | `0.75` | `MS` |
| `0x005E5670` | Boulder, EBoulder, Hailstones | `max(1, 2*charge)` | `0.5` | `MS` |
| `0x005E5960` | Ember, EvilEmber | `0.25*min(+0x150,1)` | `1-U(0.25)` | false |
| `0x005E6140` | Arrow, Firebolt, DarkFireball, Silk | `0.5+U(0.25)` | `0.85` | false |
| `0x005E6220` | Lantern | `0.65` | `0.55+U(0.2)` | `MS` |
| `0x005E7040` | Meteor | `2*+0x15C` | `min(1, gate*(1-+0x13C))`, gate ramps through age 50 in the alternate state | false; absent after fade `+0x13C>1` |
| `0x005E7420` | GreenFire | `1.2` | `min(1,3*+0x144)` | `MS`; only while `+0x144>0` |
| `0x005E7610` | Fire, Fire_Goodguy, MovingFire, DireFire | `0.6` | `min(1,3*+0x144)` | `MS`; only while `+0x144>0` |
| `0x005E7800` | GroundSpark | `0.4` | `0.5+U(0.5)` | false |
| `0x005E7AA0` | Shockwave, FreezeWave | `+0x30 / 140` | `+0x140` | false |
| `0x005E90C0` | Leviathan | `1` | `1` | `MS` |
| `0x005E9160` | EtherBolt, UnholySpit | `0.5` | `1` | `MS` |
| `0x005E94C0` | Golem | `1` | `0.75` | `MS` |
| `0x005E97A0` | MagicTrap | `0.25` | `1` | false |
| `0x005E9840` | Bonus | `1` | `+0x15C` | `MS` |
| `0x005E98E0` | DemonBomb | `0.6` | `1-U(0.25)` | false |
| `0x005EB5C0` | StormCloud, AcidRain | `2` | `0.5*+0x144` | false |
| `0x005EBD90` | RainOfBones | `2` | `U(0.5*+0x144)` | false |
| `0x005EE780` | EtherDrain | `2` | `min(+0x140,1)*(0.5+U(0.5))` | `MS` |
| `0x005F0DB0` | Comet | `2` | `0.5` | `MS` |
| `0x005F18A0` | OffscreenMagic | `3*+0x150` | `1` | `MS` |

These providers are present in the Arena owner list only while their actor or
wrapper lifecycle enrolls them. The table is a source adapter catalog, not a
request to synthesize dormant actors in the web port.

### Website-modeled right-click actor dispositions

The complete Website right-click actor union now activates the following
members of that provider catalog. Its replicated light registration is the
owner's native manager lane plus stable registration ordinal; actor ID or
snapshot-array position is not a substitute.

| Website member | Native manager lane | Light disposition |
| --- | --- | --- |
| MovingFire, Fire_Goodguy | actor `+0x310` | `0x005E7610`: root, radius `0.6`, intensity `min(1,3*alpha)`, `MS`, only while alpha is positive |
| Shockwave, FreezeWave | actor `+0x310` | `0x005E7AA0`: root, radius `waveRadius/140`, intensity wave alpha, false flag |
| Leviathan | actor `+0x310` | `0x005E90C0`: root, radius one, intensity one, `MS` |
| EtherBolt | actor `+0x310` | `0x005E9160`: root, radius `0.5`, intensity one, `MS` |
| Golem | actor `+0x310` | `0x005E94C0`: root, radius one, intensity `0.75`, `MS` |
| MagicTrap | actor `+0x310` | `0x005E97A0`: root, radius `0.25`, intensity one, false flag |
| StormCloud, AcidRain | actor `+0x310` | `0x005EB5C0`: root, radius two, intensity `0.5*alpha`, false flag |
| EtherDrain | actor `+0x310` | `0x005EE780`: root, radius two, intensity `min(scale,1)*(0.5+U(0.5))`, `MS` |
| Comet | actor `+0x310` | `0x005F0DB0`: root, radius two, intensity `0.5`, `MS` |
| EtherFade variant one | transient `+0x8B70` | borrowed `ZAnimLit 0x005E48E0`: root, radius wrapper scale, intensity `min(alpha,1)`, local `MS` flag |
| MagicCircle | actor `+0x310` | no persistent provider; its actor registration orders the one-tick MiscLight below |
| Mod_Burn, Mod_ElectricBurn | target's embedded Action manager | no persistent provider; the target registration and attachment order own the one-tick MiscLights below |

These rows are active membership, not optional presentation decoration. All
persistent rows join the provider pass before any MiscLight, even though a
modifier may have appended its one-tick record earlier during fixed-tick
execution.

### Website-modeled enemy projectile dispositions

The Website projectile union is a strict subset of that catalog. Its per-member
disposition is:

| Website member | Native manager lane | Light disposition |
| --- | --- | --- |
| Arrow, normal | transient `+0x8B70` | no source; Arrow tick enrolls only payload byte `+0x164 == 1` |
| Arrow, fire | transient `+0x8B70` | `0x005E6140`: root, radius `0.5+U(0.25)`, intensity `0.85`, false flag |
| Arrow, poison | transient `+0x8B70` | no source |
| Firebolt | transient `+0x8B70` | `0x005E6140`: root, radius `0.5+U(0.25)`, intensity `0.85`, false flag while common scalar `+0x120>=1`; the modeled default lifecycle starts at one |
| GuidedMissile, cold/poison | actor `+0x310` | `0x005E4AF0`: root, radius `0.75+U(0.1)`, intensity `0.75`, `MS` |
| DemonBomb | actor `+0x310` | `0x005E98E0`: root, radius `0.6`, intensity `1-U(0.25)`, false flag |
| PoisonPool | no provider lane | vslot `+0x30` is no-op `0x0055C300`; no source |

The enrollment gates are Arrow `0x005FECEB..0x005FED22`, Firebolt
`0x00600A08..0x00600A41`, GuidedMissile `0x00600C63..0x00600C8A`, and
DemonBomb `0x00603EAB..0x00603EDC`. Actor manager updates before transient
manager (`0x0063F127..0x0063F139`, then `0x0063F162..0x0063F168`), and each
manager preserves its stored pointer order. This is observable for the
false-flag families; grouping all projectile kinds together is not equivalent.
DarkFireball/Silk, the other missile siblings, and DemonBomb-created Fire
actors remain catalogued but dormant because they are not members of the
current Website projectile union.

### Website-modeled enemy actor dispositions

The eight Website enemy families require authoritative provider state; visible
pose, alpha, current health, and spawn age cannot reconstruct every reset and
double-enrollment branch. The minimal replicated state is native glow
(`+0x244` for Skeleton/Archer/Mage or `+0x230` for Imp/Wraith), charge
(`+0x24C` for Archer/Mage), and the actual post-gate provider-copy count.
Renderer-local reconstruction is invalid for mid-run join and resync.

| Website family | Fixed-tick writer / gate | Provider disposition |
| --- | --- | --- |
| Skeleton | active burning tick: glow `min(1,g+0.05)`, one copy | ordinary Skeleton formula; otherwise no source |
| SkeletonArcher | active charge `min(1,c+0.02)`; pose 9 then resets charge; fire-arrow and burning enqueue independently | burning copies always use the ordinary formula; non-burning fire-arrow uses the charged formula except pose 9; normal/poison has no source; fire+burn can produce two ordinary copies |
| SkeletonMage | Skeleton burning tick first, then Mage burning tick adds another `0.05`; charge adds `0.02` except pose 4; spell dispatch resets charge and lightning writes one | burning active Mage emits two ordinary copies and ramps glow by `0.10`; non-burning emits one charged copy only while charge is positive |
| Imp | alive tick glow `min(1,g+0.01)`; provider requires active class resource | one false-flag Imp source while enrolled |
| Zombie | no persistent provider in the complete census | no source |
| Wraith | burning tick glow `min(1,g+0.05)` | one ordinary source while burning; otherwise none |
| Demon | class resource gate; death latch is actor `+0x94` | one source while resource exists; intensity one alive, `0.5+U(0.5)` after the death latch |
| Coffin | delayed tick enrolls only for state `+0x210>0` | hidden/closed no source; opening, transition-delay, and open emit one source |

Archer arrow type must follow the native ordered flag reduction: the last
FireArrow/PoisonArrow writer wins. A simple `flags.includes(FIREARROW)` is not
equivalent. The current `burning-fire` visual role represents the family-owned
burning presentation, not `Mod_Burn`; it drives the actor provider branches
above but must not synthesize a modifier MiscLight.

### Other Website active and dormant dispositions

The modeled death-effect union `banish`, `bouncer`, `fade`, `move-fade`,
`sprite-array`, and `unbind` has no outbound provider in the complete compiled
census. The Bouncer's black squashed copy is a class-local flat presentation
shadow, not a Region source or directional caster. `Anim_UltraBanish` is a
different one-tick MiscLight owner and remains dormant; it must not be inferred
from Website `kind:'banish'`.

`Solomon_Dig` type 5009 is modeled and has no provider. Its paired Lantern type
5010 is the separate modeled source. Generic `GameNPC` type 5015 owns provider
`0x005EA110` but is not a current Boneyard snapshot member and remains dormant.
The player's tick-159 death burst is presentation-only and owns no provider in
this census.

## One-tick MiscLight census

Arena replays MiscLights after all persistent providers. These records are
never retained across `Region::Tick` clears.

| Producer | Append callsite(s) | Recovered light behavior |
| --- | --- | --- |
| `Action_Demonskull_MouthBeam 0x0044FFE0` | `0x00451576` | beam-owned point, radius 1, intensity 1, true flag |
| `Anim_UltraBanish 0x00460AB0` | `0x00460C44` | effect root, radius `1+U(1)`, intensity effect scalar, flag `MS` |
| Air `ZAnimSplit 0x00531640` | `0x00531D61`, `0x00531EBE` | straight-leg samples described below |
| dark-lightning sibling `0x00531F00` | `0x00532734`, `0x00532891` | same 100-unit/endpoint sampler and 220-unit source-distance gate |
| dark-lightning sibling `0x005328D0` | `0x005331B5`, `0x00533312` | same sampler; weak/fizzle parameter quarters shared intensity |
| `MagicCircle 0x006006E0` | `0x00600834` | root, radius `0.5*circle scale` (two for the shipped scale four), intensity `0.75+S(0.25)`, true flag |
| `EyeLaser 0x006054F0` | `0x00605742` | current laser point, radius 1, intensity 1, true flag |
| `Mod_ElectricBurn 0x00628F10` | `0x00628FE8` | owner root, radius `0.5+S(0.25)`, intensity 1, false flag |
| `Mod_Burn 0x00629A40` | `0x00629CAE` | owner root, radius `0.1+U(0.1)`, intensity `min(remainingTicks/50,1)`, false flag |
| `Mod_EtherBurn 0x00629CD0` | `0x00629ED8` | owner root, radius `0.1+U(0.1)`, intensity `min(remainingTicks/50,1)`, false flag |

`Mod_Burn` and `Mod_ElectricBurn` are active target-owned members of the
Website right-click system. `Mod_EtherBurn` remains catalogued but dormant.
The pre-existing `burning-fire` enemy role and Mage lightning endpoint sprites
are different actor/factory-owned presentations and must not stand in for any
modifier MiscLight.

The append order is recovered rather than inferred. Common actor tick
`0x00624AC0` calls `0x006247A0` before the owner's subclass body. That helper
walks the target's embedded Action manager at `actor+0x104` (count `+0x10C`)
in stable stored order and invokes each live action's tick slot `+0x08`.
`0x00625150`/`0x006243C0` attach globally created actions after their
applicability slot `+0x24` accepts the target. Consequently modifier lights
append in target registration order and attachment order, before that same
actor's subclass-owned MiscLights. For example, `SkeletonMage::Tick
0x00490860` completes the common/base tick through `0x00484B90` before it
creates its Air pulse. MagicCircle appends at its own actor-manager position;
Air transients then append during the later transient-manager pass. A web
authority must therefore serialize the creator registration and a tick-local
append ordinal for each synchronous batch, then preserve sample order within
that batch.

### Air path-source exact loop

Air factory `0x00531640` materializes ordered legs `[source,midpoint]` and
`[midpoint,endpoint]`. Each leg starts at its first point, computes a float32
100-unit step, emits before advancing while remaining distance is strictly
greater than 50, then snaps to and attempts the exact endpoint. A candidate is
accepted only when its squared distance from the original factory source is
at least 48,400, so the threshold is inclusive 220 units.

Each accepted point is shifted `(0,+35)`, receives independent radius
`0.75+U(0.25)`, and shares one factory-wide intensity `0.25+U(0.75)`. The
insufficient-mana/fizzle parameter quarters that intensity. Its directional
flag is Enhanced Effects `0x00B3BCAD`, not Multiple Shadows. With source 0,
midpoint 350, and endpoint 650 on one axis, append X order is exactly
`[350,350,450,550,650]`; the duplicate midpoint is intentional.

### SkeletonMage sustained lightning ownership

The Website's former four-tick BadGuys `381/382` approximation is disproven.
Those records belong to GuidedMissile. Mage dispatch `0x0047FDE0` writes
`+0x280 = trunc((100*0.5)/attackSpeed)`; the default scalar yields 50.
`SkeletonMage::Tick 0x00490860` invokes Air factory `0x00531640` once on every
tick while that counter is positive and then decrements it. One attack is
therefore a 100 Hz sequence of factory-owned pulses, not one retained effect.

Each pulse owns the common two-tick Air body, one-tick source glow, branch
geometry, and one age-zero Air path-MiscLight tail. The factory source is
attachment/extras slot zero of the current Mage body record
`1729 + clamp(pose,0,4)*18 + facing18`, transformed at the actor root and then
shifted `y-5`. The midpoint is `(mageRoot+targetBase)/2`; it does not use that
attachment point or the endpoint jitter. The body endpoint applies an
independent radial `U(10)` displacement to the target or clipped base.

The corona consumes a second independent radial `U(15)` displacement. A clear
actor target stores this as target-local attachment, scale `0.5+U(0.25)`, and
fade decrement `0.4*attackSpeed`. A blocked/world endpoint stores an absolute
point, scale `1+U(0.25)`, and fade decrement `0.2*attackSpeed`. Both contact
paths draw directly and have no ZAnimLit wrapper or outbound contact provider.
At the default speed their visible alpha sequences are respectively
`1,0.6,0.2` and `1,0.8,0.6,0.4,0.2`.

The target-local storage does not make the corona part of the target's main
sprite composite. Player constructor `0x0052A539` initializes the embedded
animation `ObjectManager` at `+0x16C`; Mage appends through that manager at
`0x004911B2..0x004911C4`. Arena flushes the complete shared world painter queue
at `0x0046FDAF`, then invokes player vslot `+0x24` at `0x0046FF00`.
`PlayerWizard +0x24 = 0x0052C2A0` reaches base `0x0052A640`, which installs the
target-root transform and draws `+0x16C` at `0x0052A884`. Thus target contact
is a target-following post-main overlay, not a child of the ordinary
world-sorted Player painter. Embedded-manager insertion order places newer
pulses above older pulses.

The exact Arena interval is closed by the surrounding calls. The shared
foreground/proxy queue finishes at `0x0046FDAA`; Arena's preceding `+0x1D0`
late-manager call finishes at `0x0046FED7`; player slots `0..3` invoke `+0x24`
at `0x0046FEFE` and return at `0x0046FF00`. The later `+0x8D90`, `+0x8DA4`,
and optional `+0x4B4` managers follow, and the Water Over direct `+0x1E0`
manager draws at `0x0046FFB7..0x0046FFBD`. Native painter order is therefore
`foreground/proxies < Mage target contact < post-world managers/Water Over`.
Within the Mage band, players retain slot order and each embedded manager
retains oldest-to-newest insertion order. A web depth mapping may place the
Mage band at foreground `+0.25` while retaining Water Over at `+0.5`; placing
both at the same depth or nesting contact below the player's main root is not
equivalent.

Mage actor-provider copies remain in the persistent actor-manager batch. Every
pulse's path lights are Region MiscLights and replay only after the complete
provider batch, in pulse/factory append order. A web port must preserve the
channel countdown and a recent semantic pulse ledger through snapshots and
protocol; action progress or one event cannot reconstruct all births at a
20 Hz snapshot cadence. The presentation timeline must admit each pulse at its
owned 100 Hz tick, without preplay, duplication, or snapshot-length stretching.

## Directional-record construction

Complex query `0x0057F0E0` first clears the object's record count and local
scalars. Every accepted source, including false-flag sources, contributes to
ordinary and one-unit-behind scalar queries. A directional record is appended
only when:

- the source flag is true;
- `Game.ComplexLighting` is true; and
- the object root is inside the source's elliptical 145-unit field.

The 0x24-byte directional record is:

| Offset | Meaning |
| ---: | --- |
| `+0x00/+0x04` | normalized source-to-object direction |
| `+0x08/+0x0C` | source world point |
| `+0x10` | base alpha, initialized to one |
| `+0x14` | scalar sampled one world unit behind the object |
| `+0x18` | normalized elliptical distance squared (`d2/145^2`) |
| `+0x1C` | projection distance `(145-U(1))*source.radius` |
| `+0x20` | source radius |

For multiple records, each base alpha is multiplied by
`max(dot(directionA,directionB), other.distanceFraction)` for every other
record. False-flag sources do not create records, but they remain in the scalar
query and can raise `behindScalar` enough to shorten or remove another source's
shadow tail.

## Generic projected geometry

Shape closer `0x00655570` stores every authored edge normal as
`(edge.dy,-edge.dx)` and never normalizes polygon winding. Projector
`0x00655970` computes `midpoint-source` and accepts strict positive dot:

```text
n = normalize(edge.dy, -edge.dx)
accept iff dot(n, edgeMidpoint - lightSource) > 0
```

This is not the web-standard single near/far silhouette choice. A CCW square
with a source to its left produces top, right, and bottom quads. Mixed-winding
native tables must retain authored order.

Each accepted edge emits one indexed two-triangle quad. Base vertices carry
record base alpha. Projected vertices carry:

```text
((1 - behindScalar) * (1 - distanceFraction))^3
```

Alpha is per vertex and linearly interpolated by the renderer. Replacing that
with stacked constant-alpha bands or allocating a gradient texture per edge is
neither visually nor operationally native.

## Caster programs and painter ownership

`Game.ComplexShadows` gates class painters, not source collection. The core
program families are:

| Class/program | Native painter | Geometry source | Output |
| --- | ---: | --- | --- |
| Tree | `0x00608AB0` | 15 authored shapes at `0x0081B910` | generic projected quads |
| Gravestone | `0x0060F260` | 17 authored shapes at `0x0081BE50` | generic projected quads |
| Monument | `0x0060E280` | 21 selector shapes at `0x00819EE8` | generic projected quads |
| Building | `0x0060EDC0` | 4 selector shapes at `0x0081B430`; variant 0 is concave | generic projected quads |
| Goodie | `0x0061F180` | subtype table at `0x0081B390` | generic projected quads |
| Fencepost | `0x00612DC0` | selector plus `7*style` at `0x0081B0B8` | generic projected quads |
| FenceGrate | `0x00600ED0` | builder-retained endpoints, step, count | one tapered bar quad per bar plus one rail quad |
| Broken grate | `0x00600ED0` | its randomized ~52-unit subsegment; step 8 | same grate program on each broken piece |
| moving Gate | `0x00600ED0` | live leaf endpoints rebuilt every motion tick; inset 4, step `length/4.5` | same grate program following the leaf |
| Rails | `0x00607440` | shortened endpoints and retained 13.333333 step/count | two width-10 projected line quads per record |
| Wall | `0x0061E780 -> 0x006561A0` | connection-adjusted live segment | one four-vertex projected quad per record |
| Scrub | `0x00620120` | transformed asset quad | class-owned asset-quad program |

FenceGrate bars use near half-width 2 at base alpha and far half-width 8 at
alpha zero, leaving transparent gaps. Its separate width-4 rail uses
`0.1*behindScalar + 0.9*baseAlpha`. A solid convex fence hull cannot reproduce
the stock bar silhouettes.

Every native object painter rebuilds its directional-record list for that
render, emits shadow geometry immediately before the owner's main art inside
the same painter invocation, then discards the records on the next rebuild.
The shadow has the owner's painter row and tie position; it does not own an
independent world-depth row. A web renderer should place a shadow mesh directly
before the exact owner at equal painter depth. A global `ownerDepth-epsilon`
can cross unrelated fractional painter slots and is not the native contract.

## Performance contract implied by ownership

The stock path has bounded retained resources:

- one quality-scaled light RenderTarget per Arena;
- one accepted-source array and spatial grid reused per frame;
- one small per-object directional-record array reused by the common painter;
- transient indexed vertices submitted by the class painter; and
- no per-edge canvas, texture, gradient object, or retained shadow lifetime.

For the browser, the closest operational mapping is a shared 256-entry alpha
ramp texture plus pooled indexed meshes for currently visible casters. Vertex
UV selects the packed alpha byte. Mesh buffers grow only when required and are
updated in place. Because a quad's six-index topology depends only on active
quad count and retained capacity, the index array and GPU index buffer change
only when that count or capacity changes; position and packed-alpha UV lanes
remain the per-frame updates. Invisible casters own no active GPU root. The
deterministic browser projection stream hashes one caster identity once per
caster evaluation and then mixes numeric source/frame fields, rather than
allocating a joined string for every caster/source pair. This preserves
per-vertex interpolation while eliminating per-frame texture construction,
redundant index uploads, and hundreds of inert shadow display objects.

The accepted-source grid is also part of the performance contract, not merely
an internal native optimization that may be replaced by repeated full scans.
The Website mapping retains 150-unit buckets across frames, advances a
generation tag instead of clearing every allocated bucket, and indexes each
accepted source through every bucket touched by its conservative
`145*radius` world AABB. A point query visits only its current bucket and then
applies the exact elliptical predicate, so conservative bucket coverage cannot
change light output. Ordered containment can use that same bucket safely: any
earlier source capable of containing a candidate necessarily covers the
candidate point with its own `145*radius` AABB. Directional-record construction
queries the caster bucket once, and its one-unit-behind scalar performs one
separate point lookup. This retains accepted-source order while replacing the
browser's former `casters * sources^2` evaluation with bounded local queries.

Scene membership must be bounded the same way. The generated Website document
contains thousands of authored caster layers, but native painters only rebuild
records and submit geometry for objects reached by the active view/painter
pass. The browser therefore derives a reused active caster/layer list from its
existing resident-visibility result, adds live moving-Gate owners, and runs
shadow projection plus painter sorting over that list only. Offscreen authored
layers retain their assets and source order but do not receive per-frame record
queries, geometry work, or sort entries.

The browser keeps its structured `__sdrBoneyardFrame` receipt, but does not
mirror the same changing diagnostics into dozens of DOM `data-*` attributes on
every frame. Attribute mutation participates in browser style/DOM bookkeeping
and has no native renderer owner; static capability markers remain attributes,
while dynamic counters stay in the single structured diagnostic object.

## Port boundary and remaining unknowns

The web port should implement sources only for actors/effects it actually
models, but its source type and collector must preserve provider order, a
separate MiscLight tail, radius, intensity, and the directional flag. Dormant
native providers remain catalogued here rather than invented into live scenes.

Global process RNG determines exact flicker and projection-distance samples.
A deterministic browser presentation stream can preserve domains, cadence,
and ownership, but is not the stock process-global sample identity unless the
whole native RNG interleaving is reproduced. Exact D3D9 texel-center behavior
at every LightQuality and the class-specific fallback painters used when
Complex Shadows is off remain outside the current WebGL parity target; neither
justifies changing the on/default path documented above.

## First-frame and run-reset presentation lifecycle

The Arena exposes no intermediate "world ready, lighting pending" frame.
`Arena::Create 0x00470A90 -> 0x0057DF20` owns the quality-scaled light target
before the Arena can render. Every later `Arena::Render 0x0046EC80` call forms
one complete presentation epoch:

1. `0x0057D4E0` binds and clears the Region light target and resets accepted
   sources;
2. persistent providers and the complete MiscLight tail submit their current
   records;
3. `0x0057D5E0` restores the main target;
4. the direct world bands paint, `0x0046FAFF` multiplies the Region target,
   and the shared main queue flushes at `0x0046FDAF`; and
5. environment modes 1 and 2 execute the player-owned record-18 direct light
   plus, only when either target-mask grid has members, the local record-9
   target light additively before screen feedback and HUD. Neither pass covers
   the full backbuffer.

That sequence applies to the first visible Arena frame, every ordinary frame,
and the first frame after a new Arena is constructed. The provider and
MiscLight arrays are rebuilt rather than inherited from a prior run. The
quality target is retained only within its owning Arena and is destroyed with
that Arena; it is never a process-global lighting result that a replacement
Arena may briefly reuse. A resize or target recreation likewise cannot be
presented between the clear and the complete current-frame source/composite
sequence.

The complete first-frame membership is therefore:

| Member | Native disposition at the first visible Arena frame |
| --- | --- |
| environment mode 0 | Region raster, analytic tint, and directional shadows; no later player environment-light pass |
| environment modes 1 and 2 | same Region products, then direct player light and any grid-backed local target in the same render epoch |
| every visible player | current provider submission plus the direct pass and an optional target-grid pass in modes 1/2 |
| persistent actor and transient providers | current manager order only; no previous-run carry-over |
| MiscLight producers | current fixed-tick tail only; the list was cleared by Region tick |
| Complex Lighting off | recovered late raster branch and white analytic tint; still one complete render epoch |
| Complex Shadows off | directional geometry suppressed while source collection/raster behavior remains current |
| Arena teardown and replacement | old target, records, and object-local shadow arrays retire before the replacement becomes visible |

This closes a port-side lifecycle ambiguity without changing any recovered
formula or setting default. A browser readiness barrier may resolve only after
the first complete Region plus environment composition. Publishing a scene
between WebGL world creation and its first environment light pass, or using a
second lazily decoded image owner for that pass after resident assets were
declared ready, has no native equivalent and can expose an incomplete startup
frame under scheduler or decode delay.

## Corrected environment-mode player-light composition

The 2026-08-20 report that a fresh web Boneyard could retain the player light
while later spell, Lantern, enemy, and effect lights appeared absent reopened
the interaction between the Region field and `Arena` environment mode. Fresh
raw-instruction review proves the earlier browser interpretation was inverted:
environment modes 1 and 2 do not add a fullscreen black layer with player
holes. They add two bounded player-owned light products after the completed
Region field. The Region field remains the only engine-wide darkness/light
product, so a later Lantern or spell source remains visible outside every
player target.

### Exact instruction chain

- `Arena::Render 0x0046EC80` still resets/submits/restores the Region manager,
  then uses blend mode 2 (`ZERO, SRCCOLOR`) for the Region target at
  `0x0046FAFF` before the shared queue.
- In `0x00470EE0`, each occupied player slot in environment mode 1 or 2 sets
  renderer byte `+0x221 = 1` at `0x0047128F`, applies alpha
  `0.25 * (0.95 + U(0.05))`, and draws DeadHawg record 18 at
  `0x004713FF`. Blend state 1 is `SRCALPHA, ONE`, so this is additive.
- The same player queries two spatial presentation grids over the exact
  `512 x 512` rectangle centered on the player (`Arena +0x8F84` and
  `+0x8F24`, calls `0x004714C8/0x004714EF`). If both are empty, the local
  target branch is skipped. Registered target-mask sprites include the
  environment/compact effect lane; for example `0x00461740` registers its
  born record-26..28 sprite into both grids.
- With at least one target-mask member, `0x004715C1..0x004715F3` binds the
  `256 x 256` player target and clears it to transparent white `(1,1,1,0)`.
  The two query results draw into that local target. At
  `0x00472577..0x004725B5`, blend mode 2 multiplies DeadHawg record 9 into
  the target at scale `2.009999990463257` around `(128,128)`.
- `0x004725DE` restores the main backbuffer. Only then does
  `0x004726B8..0x00472817` select blend mode 1, sample
  `0.95 + U(0.05)`, and draw that one local target at the player with scale
  `2.0250000953674316`. The target therefore spans about `518.4` world
  units. `0x00472828` restores ordinary blending.
- No instruction in either player branch draws a fullscreen quad, clears the
  main backbuffer to black, or inverts the player masks. Pixels outside each
  local target are not touched by `0x00470EE0`.

Constants were re-read from the pinned retail image: `0x00785D18` is
`2.0250000953674316f`, `0x00785D1C` is `128.0f`, `0x00785D20` is
`2.009999990463257f`, the qword at `0x00785D28` is `256.0`,
`0x00785D30` is `512.0f`, `0x00785D34` is `0.050000011920928955f`, and
the qword at `0x00784E20` is `0.949999988079071`.

### Port consequence and complete active membership

| Member | Native disposition for the current Website model |
| --- | --- |
| Region player, Lantern, enemy, projectile, spell, modifier, and secondary sources | remain the engine-wide accepted-source field; never clipped by a fullscreen environment mask |
| environment mode 0 | no extra player environment-light pass |
| environment modes 1 and 2 | always-valid record-18 direct light for each visible player; the current web model has no target-grid actor lane and therefore must not synthesize record 9 |
| multiple visible players | independent additive direct draws in slot order; native local-target contributions also add when their grids are populated |
| local target-mask grids `+0x8F24/+0x8F84` | class-owned compact/environment presentation masks within the 512-square query; `out-of-system` for the current web actor model, so the optional target branch is absent rather than approximated |
| HUD and screen feedback | remain after both world-light systems |

The Website's former transparent Canvas accumulated the two player masks and
then used `source-out` to fill the entire viewport with black at alpha `0.96`.
That operation has no native owner. It double-darkened the already completed
Region field and reduced every source outside the player aperture—including
sources born later—to an almost invisible calibration floor. Because generated
environment mode varies, this deterministic mode error looked like an
intermittent source-enrollment failure. The web correction keeps the direct
record-18 canvas transparent outside its bounded additive draws and leaves the
optional record-9 branch absent until its target-grid actors exist. It must not
feed Lanterns or spells into the player-only pass to hide the compositing bug.

The Website correction replaces the inverted fullscreen surface with one
transparent `plus-lighter` record-18 pass and keeps its existing first-frame
readiness barrier. Focused tests pin the direct `.2375..25` alpha domain and
forbid `source-out`, a viewport fill, or an unconditional record-9 radial.
Rebased Website validation passed, and an Apple-M2 mode-2 run reported player
center alpha `61`, white RGB `765`, and exact far alpha/RGB zero while holding
60 FPS. A separate mode-2 Air run retained seven provider candidates, native
Lantern flicker, visible endpoint illumination, and no browser errors. The
Loader portable suite passed 87/87 modules and 795 tests against this corrected
ledger.

## 2026-08-23 PlayerWizard `+0x268` event-writer correction

The shared equipped-element/light phase is one actor field with event writers,
not a collection of held-action booleans. Fresh read-only instructions and
supporting write watches close the writer cadence that the 2026-08-22 Website
port left implicit:

| Writer family | Callback/store | Exact value and recurrence |
| --- | --- | --- |
| Staff/Hand/Wand Cast 1 modes `3/6/9` | `0x00550180`, mode-3 Staff store `0x005502F6` | `0.15` once at the action-progress marker; no occupancy refresh |
| Staff/Hand/Wand Cast 2 modes `4/7/10` | same callback, mode-4 Staff store in the adjacent branch | `0.45` once at the Cast 2 marker |
| Staff/Hand/Wand Constant modes `5/8/11` | mode-5 Staff conditional store `0x00550317` | `0.25` once on the qualifying start edge; no held-level refresh |
| Ether Blast charge integer crossing | Player tick `0x0054B9C8` | `0.25` per crossed integer |
| fixed-tick decay | `0x00548FFC..0x00549012` | `float32(previous * 0.8999999761581421)` every tick without a writer |

The values were re-dumped from the pinned retail image:
`0x00784D64 = 0.15000000596046448f`,
`0x007DE978 = 0.25f`, and `0x00785370 = 0.44999998807907104f`.
The equipped-element helper still consumes the resulting single field as
`actorScale * (1 + 10*phase)`, and the player analytic light still consumes it
as `(1 + phase) * 2.5999999046325684`. Those consumers must see the same phase
sample. A web model that continuously rewrites the phase while Cast 1 or a
Constant action is occupied pins the orb/light above native size and is not an
equivalent approximation.

The complete writer membership is Cast 1, Cast 2, Constant, Ether Blast, and
decay across Staff, empty-hand, and Wand equipment branches. Dampen's separate
mode-21 CastSpin has no case in `0x00550180` and therefore contributes no
`+0x268` write. Toggle-off and actionless secondary branches likewise do not
inherit a Cast 2 pulse. Death, actor removal, world replacement, and
construction/reset retain the existing zero/teardown ownership. No member is
blocked by the browser platform.
