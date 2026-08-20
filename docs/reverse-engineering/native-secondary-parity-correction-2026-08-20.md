# Native secondary-ability parity correction (2026-08-20)

## Scope and supersession

This report reopens the secondary-ability closure after visual inspection of
Magic Storm, Raise Golem, Call Leviathan, Ring of Fire, and Ring of Ice. The
five reports are symptoms of shared native owners that the earlier pass either
collapsed into actor-local presentation or omitted: offscreen composite
ownership, articulated summon state, Region feedback, target-owned modifiers,
equipment-set feature bits, and painter grouping.

This document supersedes an `exact-ported` disposition for any secondary row
whose implementation depends on those owners. It does not discard the rank
tables, cast costs, actor identities, or unaffected lifecycle evidence already
recorded in
[`native-secondary-ability-catalog.json`](native-secondary-ability-catalog.json).

Evidence is from the 4,723,200-byte retail executable with SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3` and
preferred base `0x00400000`. The correction follows the dispatcher
`0x0054CC50`, creation helpers, object vtables, update callbacks, draw
callbacks, Region feedback fields, and complete-equipment feature mask at
wizard progression `+0x878`.

## Reopened evidence ledger

| Native owner | Recovered evidence | Port consequence |
| --- | --- | --- |
| Secondary dispatcher | `0x0054CC50`; feature tests at `+0x878` | Maximum-set branches are gameplay authority, not the Enhanced Effects graphics option. |
| Region feedback | Ring helper `0x0063F920`; Region tick `0x0063EFC0`; ice helper `0x00644460` | Screen color and camera magnitude are Region state. Ring of Fire writes camera magnitude `0.25`; trap and shield explosions write `1.25`. Magnitude recurs by `*0.94` and clears below `.001`. Earthquake remains the separate displacement-vector lane. |
| Magic Storm | constructor/update/draw `0x00602C30`, `0x00602E10`, `0x00619C60`; light callback `0x005EB5C0` | The cast point is an immutable world anchor. Three BadGuys-78 cloud passes render into one 256-by-256 target and are composited as one world owner, scale five, with the cloud root translated upward 175. Light is at the actor point with radius two and intensity `.5*alpha`, without shadows. No update branch follows the caster. |
| Golem assembly and gait | initializer/tick/draw `0x005E91D0`, `0x00615CD0`, `0x00617820` | Persistent left/right feet, interpolation progress, bob, limb modes, action heading, and rotations are authoritative summon state. Reconstructing a body around `actor.position + heading*-19` is not equivalent. |
| Leviathan compositor | tick/draw `0x006145D0`, `0x006151D0`; sprite pass `0x005E90C0` | The parent and every appendage render into one shared 256-by-256 target and enter the world painter as one owner. Appendages cannot interleave independently with enemies. Query radius 300, half-angle 25 degrees, socket-derived muzzle, and EtherBolt damage remain authoritative. |
| Shockwave | tick `0x005FF8C0`; Ring helper `0x0063F920` | Contact is unique per target and sampled every ten ticks. The maximum-fire flag is Shockwave `+0x170 bit 0x4`, not `+0x150`. |
| Shared explosion | `0x00642BF0`; maximum-fire call `0x005FFBAD..0x005FFC0B` | Each first Ring-of-Fire contact creates the complete shared explosion at the struck actor. Scale `1.5` makes the query radius `165`; every eligible actor receives an additional `0.5*waveDamage`. The call also requests three fire fragments and the common layered normal/additive burst. |
| FreezeWave | helper/tick `0x00644460`, `0x005FFDC0` | Targets with flag `0x40` receive ColdSlow `0x1B69`; ordinary enemies receive Frozen `0x1B6F`. `+0x174 bit 0x10` additionally attaches FrostBurn `0x1B78`. Ring of Ice and Call Comet share this owner. |
| Frozen | constructor/apply/tick/merge `0x00623550`, `0x006236E0`, `0x00623730`, `0x00626620` | Full freeze has time factor zero. During the final 200 ticks it adds exact float32 `.005` per update. Apply blends the target material halfway toward `(0.15,0.5,1,1)`; the final-200 state changes its internal scale by `*.985`, phase by `+.15`, red by `+.00425`, and green by `+.0025`. Merge keeps the greater duration and minimum time factor. |
| ColdSlow | constructor/apply `0x00623050`, `0x00623080` | Apply multiplies the target time factor, blends its material halfway toward `(0.5,1,1,1)`, and sets target material flag bit four. It is target-owned presentation, not a snow particle. |
| FrostBurn | constructor/tick/merge `0x00623AE0`, `0x006278B0`, `0x00627690` | Damage is exactly `1/100 = .01` per native tick. Duration is `freezeTicks*100`, so total damage equals the original freeze duration in native ticks. Every tick consumes the one-in-two flare gate; success creates one additive moving/fading BadGuys record 10 or 11 at the target, with the recovered color, position, velocity, damping, alpha, and loss program. Merge keeps the greater duration and greater per-tick damage. |
| Equipment masks | item applier plus dispatcher tests | Bug Master `0x1`, Tempest `0x2`, Burning Man `0x4`, Fete of Clay `0x8`, and Frostburn Jewels `0x10` are distinct complete-set effects. Iron Golem skill 75 is not the two-Golem cap. |
| World painter | Golem and Leviathan draw owners plus Region queue | Effective world Y, authored sort bias, and composite ownership must be consumed in every scene. A Hub-only depth calculation from raw `actor.position.y` loses these semantics. Target material is multiplied with Region lighting at the enemy's existing painter root. |

## Corrected ability contracts

### Magic Storm (`27`)

The StormCloud actor is born at the accepted aim point. Its position is never
rewritten from the caster after creation. The native cloud is not three normal
world sprites: `0x00602C30` allocates a 256-by-256 offscreen target,
`0x00619C60` draws three BadGuys record-78 passes around that target's center,
and the composite enters the world once. The composite root is translated up
175 units and scaled by five. The light callback uses the actor's unshifted
world point, radius two, intensity `.5*alpha`, and no shadows.

The existing radius-500 target query and authoritative lightning damage range
remain valid. The Tempest complete set tests feature bit `0x2` and doubles the
base 1,000-tick active countdown before Magic Tornado's duration bonus is
added. It does not double the terminal fade.

### Raise Golem (`45`)

Golem presentation is a sorted articulated assembly. The object stores current
feet at `+0x180..+0x18C`, previous/next paths at `+0x190..+0x1AC`, per-foot
progress at `+0x1B0/+0x1B4`, bobs at `+0x1B8..+0x1C4`, provoke connector
offsets at `+0x1C8..+0x1D4`, action heading at `+0x1DC`, action tick at
`+0x1E0`, pose selector at `+0x1E4`, limb modes at `+0x1E8/+0x1EC`, and
rotations at `+0x220/+0x224`.

Foot target helper `0x005E91D0` quantizes heading to 16 bins, applies local
left/right offsets of `-10/+10`, applies actor scale/facing/forward, adds the
world position, and collision-resolves with circle flag `0x20`. Initialization
uses forward `-19`. Assembly refreshes the feet and advances age by two, with
impacts at `0,50,100,200`. Active gait alternates foot paths 50 ticks apart;
progress recurs as `(progress + movementScalar*.015)*1.06`, clamped to one,
and the visible foot is the path interpolation plus a `-sin(globalPhase)*3`
bob. A completed step draws a signed Float(8) rotation.

Draw `0x00617820` builds 12 records and sorts them by effective Y. Connectors
precede bodies. Chassis banks `113/129/145/161` are always present; core,
limbs, and five bank-65 pieces appear from age 100; connectors appear from age
200. Native elevation is `0`, `-20`, then `-40` across assembly stages.
Attack limb mode one runs through impact tick 37, then mode two recovers;
heading offsets are signed 38 degrees in windup, zero at impact, and opposite
47 degrees in recovery. Provoke runs from 100 through -50 with limb mode
three and connector offset `(0,-12)`.

The Fete of Clay complete set (`+0x878 bit 0x8`) owns the one-versus-two summon
cap and lower-HP eviction. Iron Golem skill 75 separately owns reflection,
cost, and the iron byte. Those conditions must not be aliased.

#### Second visual reopen: exact articulated draw-record ABI

The first correction recovered the state fields and record membership but did
not drain the per-record draw-position/sort-position ABI. That omission caused
the Website to pass native sort Y as visible sprite Y for records 4..11.
Single-Golem browser captures disprove Fete overlap as the root cause, while
retained native-renderer captures show the stock compact upright silhouette.

For `Golem::Draw 0x00617820`, let `D=(sin(h),-cos(h))`,
`P=(D.y,-D.x)`, `C=(leftFoot+rightFoot)/2`, assembly elevation `E` be
`0/-20/-40`, facing be `f`, and opposite facing be `o`:

| Row | Atlas record | Visible offset from `C` | Internal sort Y | Rotation / scale |
| ---: | --- | --- | --- | --- |
| 0 | `113+f` | `D*15+(0,E)`, or `D*10+(0,E-5)` for limb mode 3 | draw Y | `0 / 1` |
| 1 | `129+f` | `D*-5+(0,E)` | draw Y | `0 / 1` |
| 2 | `145+f` | `D*-5+P*-30+(0,E+5)` | draw Y | `0 / 1`; Iron `177+f` overlay |
| 3 | `161+f` | `D*-5+P*30+(0,E+5)` | draw Y | `0 / 1`; Iron `193+f` overlay |
| 4 | two inline `BadGuys[15]` glows | `(0,E+10)`, second `+5Y` | first draw Y `-50` | `[2,2.25)` and `[1.5,1.75)` |
| 5 | `(mode>1?17:1)+f` | `D*-5+P*-38+(0,E+5)` | draw Y `-50` | field `+0x220`, forced `45` in mode 1 |
| 6 | `(mode>1?49:33)+f` | `D*-5+P*38+(0,E+5)` | draw Y `-50` | field `+0x224`, forced `-45` in mode 1 |
| 7 | `65+f` | `D*-20+P*12+(0,E+5)` | draw Y `-50` | `0 / 1` |
| 8 | `65+f` | `D*-20+P*-12+(0,E+8)` | draw Y `-50` | `10 / 1` |
| 9 | `65+f` | `D*-15+(0,E+15)` | draw Y `-70` | `0 / .8` |
| 10 | `65+o` | `D*1+P*12+(0,E+15)` | draw Y `-50` | `0 / 1` |
| 11 | `65+o` | `D*1+P*-12+(0,E+12)` | draw Y `-50` | `0 / 1` |

Atlas draw scale is `1.1109999418258667`; the half scale is
`0.5554999709129333`. The connector prepass is also exact state, not a line
between raw feet. With per-side offsets `OL/OR`, endpoints are `L+OL` and
`R+OR`. Joints are
`OL + .5*(L+C+P*-10) + (0,-15)` and
`OR + .5*(R+C+P*10) + (0,-15)`. Each glow is
`(endpoint+3*joint)/4`; bank-65 caps are at the joints. Endpoint bank
`97+f` is not rotated. Fields `+0x220/+0x224` rotate limb records 5/6 instead.
Endpoints, glows, and caps precede the internally sorted body.

This closes every row and branch consumed by the articulated draw owner:
assembly stages, 16 headings/opposite bank, idle/gait rotations, left/right
attack modes, provoke offsets, Iron overlays, one/two independent Fete actors,
and both Hub/Boneyard consumers. Golem death remains the separate
`0x00619730` presenter and is unaffected.

The corrected Website plan now preserves separate visible and sort coordinates,
routes `+0x220/+0x224` to limb rotations, and reconstructs the connector
endpoint/joint/glow formulas above. Its regression first failed on the former
`-50` visible-Y error, then passed with all sixteen headings and every draw
member. Single-Golem Hub captures across ages `2/50/100/200/400` and a live
Boneyard attack show the compact connected native silhouette; the canonical
Website gate, after native-loot integration, passes 140 focused prerequisite
tests, 40 loot tests, and 972 broad game tests. The
same implementation passed the complete Apple-M2 Mac gate and hardware
Chrome/WebGL2 Hub/Boneyard journeys with empty page/console errors. Receipt
SHA-256 values are
`dece65a04a315930a9dd0c647ca79dc983b3cfef5b5572e346b640ec12a3e19f` and
`3b84688d33001c2d4da42a51cb1400514b5cbc8648f4ba93eaf1874342d36858`.

### Call Leviathan (`11`)

The recovered combat contract remains radius 300, a strict 50-degree lane,
nearest visible target, and a socket-derived EtherBolt muzzle. Bug Master
doubles the Call Leviathan payload and forces authored maximum appendage
quantity. The correction is painter ownership: `0x006151D0` renders the parent
and all appendages to one shared 256-by-256 target, then submits one composite
at the parent effective Y. Per-appendage world containers may be useful state
holders, but they must not receive independent painter slots.

The firing transform in `0x006145D0` deliberately derives the muzzle from the
parent point, appendage local root, authored appendage scale/wobble, and atlas
socket, then adds the native projectile offset. It does not apply the portal's
visual scale-in a second time. Preserving that apparent mismatch is parity.

### Ring of Fire (`21`)

Cast helper `0x0063F920` writes the fire Region color/flash and camera magnitude
`0.25`, creates 30 MovingFire children, then creates Shockwave. Region tick
`0x0063EFC0` applies `magnitude*=.94` and clears below `.001`.

Ordinary Shockwave contact still supplies the configured wave payload,
Dazzle, learned Burn, and radial push once per target. With Burning Man's
complete-set bit `0x4`, helper code writes `Shockwave+0x170=4`. On every first
contact, `0x005FFBAD..0x005FFC0B` calls the common explosion at that target
with scale `1.5`, full wave damage, three fragments, and the fire branch.
`0x00642BF0` multiplies scale by its 110-unit base query, producing radius 165,
and dispatches half the supplied damage to each eligible actor. The struck
actor therefore receives the normal Ring payload plus the additional splash
when it is included in that query; nearby actors can be struck by overlapping
contact explosions.

### Ring of Ice (`35`) and Call Comet (`76`)

The ring's caster-centered burst and snow children are independent from the
target status. The expanding wave applies one target-owned modifier on first
contact. Ordinary Boneyard enemies do not carry flag `0x40`, so they receive
Frozen rather than ColdSlow. Frozen prevents behavior at time factor zero,
then exposes the exact 200-tick `.005` recovery ramp. Its material blend must
be applied at the enemy's existing painter root and multiplied with Region
lighting; creating free snow around an otherwise unchanged target is wrong.

Frostburn Jewels sets wave bit `0x10`, adding FrostBurn beside Frozen. The
modifier applies `.01` damage every tick for `freezeTicks*100`, records source
group `+0x20`, and owns its alternating record-10/11 additive flare. Call
Comet creates the same FreezeWave and must use the same target status,
material, timing, damage, and painter paths.

## Complete-set feature semantics

| Set | Recipes | Bit | Exact secondary consequence |
| --- | --- | ---: | --- |
| Pandimensional Bug Master | `11..15` | `0x1` | Force maximum Leviathan appendages; the set's separate one-spell modifier doubles Call Leviathan damage. |
| Tempest | `16..19` | `0x2` | Double Magic Storm's base active countdown before Tornado bonus. |
| Burning Man | `20,21` | `0x4` | Arm per-contact Ring-of-Fire explosions with radius 165 and half-wave splash damage. |
| Frostburn Jewels | `22..24` | `0x10` | Add target-owned FrostBurn to FreezeWave contacts. |
| Fete of Clay | `25..28` | `0x8` | Raise the Golem cap to two and evict the lower-HP summon when necessary. |

These are exact recipe-set predicates. Partial equipment never enables a bit.
Enhanced Effects only changes visual child counts and is not a substitute for
any feature bit.

## Full 23-member residual audit

| ID | Member | Correction disposition |
| ---: | --- | --- |
| 11 | Call Leviathan | Reopened: shared offscreen composite/painter owner and complete-set authority. Combat range, lane, muzzle, cadence, and damage formula reverified. |
| 12 | Planewalker | Reverified: no dependency on the five reopened native owners beyond the common scene depth regression. |
| 15 | Phasing | Reverified: source streak, successful relocation, no-fizzle failure, and teardown remain independent. |
| 21 | Ring of Fire | Reopened: missing Region camera lane and Burning Man contact explosion/damage branch. |
| 23 | Firewalker | Reverified: patch and target-owned Burn remain independent; shared target material/light composition must not disturb Burn light. |
| 27 | Magic Storm | Reopened: immutable world anchor, 256 target compositor, world offset/depth, and Tempest duration. Damage/range reverified. |
| 30 | Prismatic Shock | Reverified: caster-following presentation and target-owned modifier are intentional, unlike Storm. |
| 35 | Ring of Ice | Reopened: Frozen/ColdSlow material, thaw timing, Frostburn set branch, target VFX, and shared light composition. |
| 41 | Earthquake | Reverified: owns Region displacement vector, not the scalar camera lane. |
| 45 | Raise Golem | Reopened: foot/gait/limb/assembly state, 12-record sorted compositor, and Fete-of-Clay cap. Attack contact and reflection reverified. |
| 46 | Stoneskin | Reverified: target material owner remains separate and must compose with the same lighting path used by Frozen. |
| 48 | Teleport | Reverified: its two independent world bursts require the corrected shared depth semantics only. |
| 49 | Magic Circle | Reverified: world actor, light, slow, mana cadence, and inert HP defect unchanged. |
| 50 | Magic Trap | Reopened shared lane: camera magnitude must be explicit Region feedback at detonation, while ElectricBurn remains target-owned. |
| 51 | Dampen | Reverified: cast-spin and world children unchanged; shared depth semantics apply. |
| 54 | Magic Shield | Reopened shared lane: break camera magnitude must be explicit Region feedback; explosion/payload ownership unchanged. |
| 72 | Acid Rain | Reverified: field depth, direct damage, child count, splash gate, light/audio lifecycle unchanged. |
| 73 | Fire Wall | Reverified: eleven independently sorted persistent patches and Burn contacts unchanged. |
| 74 | Ether Drain | Reverified: parent-owned field/light and target/loot pressure remain unchanged. |
| 76 | Call Comet | Reopened transitively: impact-created FreezeWave must use corrected Frozen/FrostBurn target ownership and painter path. |
| 77 | Turn Undead | Reverified: target family filter, flee/weaken state, 35 children, and pitched audio unchanged. |
| 78 | Mindstar | Reverified: Region-only feedback and toggle authority unchanged. |
| 79 | Regenerate | Reverified: Region-only feedback and toggle authority unchanged. |

## Browser implementation boundary

The host must publish every state value that a peer cannot reconstruct from an
independent local clock: complete-set flags, Golem feet/gait/limb pose,
Frozen/FrostBurn clocks and material state, unique contact explosions, and
Region camera events. VFX-only child sampling can remain deterministic from a
published presentation seed where the existing contract already does so.

The shared renderer must consume one effective-Y/sort-bias plan in Hub and
Boneyard. Storm and Leviathan are one composite painter owner each. Golem owns
its sorted articulated children inside its summon root. Enemy status material
is multiplied with the existing Boneyard light tint at the enemy root; status
sprites do not get a second independent enemy depth.

## Website implementation receipt

The Website implementation following this record uses protocol 30. It
publishes the five complete-set predicates, explicit Region camera events,
Frozen/ColdSlow/FrostBurn state, and Golem articulation; composes target
material with Region light; uses the shared effective-Y/sort-bias path in Hub
and Boneyard; and gives Storm and Leviathan real transparent 256-by-256
offscreen owners. The reported white Storm field was the Pixi clear-color
contract: CSS `rgba(255,255,255,0)` became an opaque white RenderTexture on the
active WebGL backend. Explicit `[0,0,0,0]` clears both composites correctly.

Local verification passed the Website canonical gate, 136 focused secondary
tests, all 962 broad game tests, the closed 23-member Hub WebGL journey, and
focused live-enemy Boneyard
journeys for all six affected/shared paths. Those receipts include Leviathan
EtherBolt damage, Ring-of-Fire contact/splash damage and `.25` camera pulse,
Storm lightning damage and immutable aimed placement, live Frozen plus
FrostBurn clocks/damage/VFX, two fully assembled attacking Golems, and Call
Comet damage plus the maximum shared FreezeWave.

An isolated exact implementation checkout then passed the same canonical gate
on the arm64 Apple-M2 Mac mini. Hardware Chrome/WebGL2 completed all 23 Hub
receipts without page or console errors. The six-member Boneyard journey proved
live damage/status for Leviathan, Ring of Fire, Storm, Ring of Ice, both Golems,
and Call Comet, including every complete-set maximum above. Its first combined
run exposed only a proof-fixture timing bug: Golem cooldown plus assembly
outlived a 1,000-tick target movement hold. Extending that deterministic hold
to 100,000 ticks made the actual Golem attack/damage receipt stable without
changing runtime behavior.

## Publication and production receipt

The runtime-bearing Website commit `a4cf0299987336a37e58419eaf532f5c7b03e361`
and this repository's evidence commit
`82a55b2d6bde2bc84a67ffaf145fad75dd43bb48` reached their respective `main`
branches by fast-forward. GitHub's Website Validate run `32372421945` and Mod
Loader Lua/static-contract run `32372421178` both passed.

The isolated deploy worker independently validated Website `a4cf029`, built
artifact
`cc028104860a10a46c2f829c578ca430fbeecbc3478afd54fd6e5f5cab09b864`, and
completed its guarded NFO cutover. Production reported the exact SHA, both
services active with zero restarts, protocol 30, zero remaining sessions or
lobbies, `ok` live/backup database integrity, and no warning-level cutover
journal. The public `/game` document matched the validated build byte-for-byte.

A separate Apple-M2 Chrome/WebGL2 production journey then took three real
clients through Create, shared Hub, generated mode-2 Boneyard, gate crossing,
Solomon dialogue/taunt, the opening ten-enemy wave, audio, lighting, and painter
order with no page or console error. Receipt SHA-256:
`50475af7297dd775218bfd2c9b278de8de963cb5115a4dcba49f9ba515a2eaba`.
The only first-run failure was in the verifier asking production to serve a
Vite-only source-module path; authored-template comparison now remains in the
exact-checkout harness and does not alter shipped game behavior.
