# Native animation and presentation state

## Result, scope, and evidence boundary

This is the G4 contract for choosing an actor's native art. It answers which
sprite state is visible, which fixed-tick event changes it, whether another
state can interrupt it, how heading selects a facing, and how equipped art is
attached. It does **not** duplicate either neighbouring campaign:

- enemy target selection, range control, cooldowns, and the decision to queue
  an action belong to G3's
  [`native-enemy-behavior.md`](native-enemy-behavior.md); this document begins
  at the action/state value that G3 produces;
- physical pass order, sort keys, quad construction, blend, fog, tint, and the
  final world-to-screen transform belong to G12's
  [`native-scene-composition.md`](native-scene-composition.md); this document
  supplies the sprite record and actor-local presentation values consumed by
  that compositor.

The executable is the configured retail 0.72.5 `SolomonDark.exe`. Static
claims came from a read-only headless Ghidra replica. The committed live
recording is
[`animation-goldens.json`](../../tests/fixtures/webgame/animation-goldens.json),
made by [`record_animation_goldens.py`](../../tools/record_animation_goldens.py)
through an isolated rendered solo instance. Raw contiguous frame captures and
lifecycle receipts are retained in `D:\codex-evidence\animre-20260805`.

## The clock: presentation is sampled, never render-driven

G1's [native tick graph](native-movement-and-tick.md#native-tick-graph) is the
only clock contract used here:

```text
fixed tick T (100 Hz)
  -> actor and action ticks write presentation fields
  -> zero or more further fixed ticks may run
  -> one render pass (at most 60 Hz) reads those fields
```

Animation therefore advances on **native fixed ticks**, not render frames and
not the loader's 67 ms motion or 250 ms mana publication cadences. A render can
sample the same native pose twice or skip one or more poses after scheduler
catch-up. The browser must update pose state in its 100 Hz deterministic core
and let rendering sample the latest completed tick. Advancing an animation by
one frame per `requestAnimationFrame` visibly slows it at low frame rate and
speeds it on high-refresh displays.

For every action-backed enemy animation, let `p` be the float action progress
at `action+0x30`. On each fixed actor tick:

```text
p_next = p + base_rate * actor.attack_speed(+0x17C) * marker_rate_multiplier
frame  = trunc(p_next)             // renderer samples; it does not increment p
done   = p_next > end_frame        // strict greater-than
```

The marker-rate multiplier can be rerolled by the action. Consequently the
frame **list** and the tick anchor are exact while wall duration can vary. The
fixture records `p`, the fixed tick, and the render observation for that
reason.

## Wizard state machine

The stock wizard does not have independent `hit` body art. Damage can add
knockback, tint/flash, and effects, but it leaves the current locomotion or
cast sprite selector intact. Treating `hit` as a mandatory body-state reset is
a port-only invention.

<!-- WIZARD_PRESENTATION_STATES_BEGIN -->
| State | Visible selector | Entry trigger | Exit / interruption |
| --- | --- | --- | --- |
| `absent` | no wizard draw | actor is not registered in the current Region | registration enters `idle`; respawn does not resume a prior pose |
| `idle` | locomotion body plus current 24-way facing; attachment pose `K=0` when no queued presentation action owns it | registered, alive, no displacement and no queued action | displacement -> `walk`; a queue insertion -> `action_tick_0`; terminal drive -> `death_delay` |
| `walk` | locomotion strip sampled from the fixed-tick walk phase; current 24-way facing | non-zero fixed-tick displacement and no higher-priority queued action | zero displacement -> `idle`; a queue insertion -> `action_tick_0`; terminal drive -> `death_delay` |
| `action_tick_0(mode,K_previous)` | the previous selector is retained on the insertion tick; the live Staff Cast 1 witness is `cast_pose_0` | action count becomes one before that action's first tick | first action tick selects `frames[trunc(p)]`; movement never cancels it; death interrupts immediately |
| `action_pose(mode,K)` | mode-specific body/equipment bank from the complete table below | the action fixed tick advances `p` or a custom phase and writes `K` | the same action may change `K`; strict completion returns to `idle`/`walk`, the next queued action may replace it, and death interrupts immediately |
| `cast_pose_1`, `cast_pose_8`, `cast_pose_7` | Staff Cast 1's observation-backed `action_pose(3,K)` substates | the selected RNG branch and `trunc(p)` choose the next table entry | only the table order is legal; input release does **not** rewind or cancel the already queued action |
| `hit_overlay(base)` | no body-bank change; damage feedback is composed over `base`; the exact actor-local case is the Magic Shield pulse at `+0x1D0` | accepted damage while `+0x1C4` shield capacity remains sets the pulse to `2.0`; unshielded hit actors likewise leave the body selector unchanged | Player fixed tick subtracts `0.05`, clamped at zero: exactly 40 ticks unless another hit refreshes it; it never interrupts `walk` or a queued cast by itself |
| `death_delay` | terminal body pose, death counter `D=0..150` | `actor+0x160 != 0`; counter `actor+0x1BC` starts at zero | cannot be interrupted by movement, cast, or hit; at `D=151` enters `death_frame_0` |
| `death_frame_0` | terminal frame `0` | `151 <= D <= 152` | two fixed ticks, then frame 1 |
| `death_frame_1` | terminal frame `1` | `153 <= D <= 155` | three-tick cadence advances to frame 2 |
| `death_frame_2` | terminal frame `2` | `156 <= D <= 158` | three-tick cadence advances to frame 3 |
| `death_frame_3` | terminal frame `3` | `D >= 159` | held until the owner flow retires/replaces the actor |
<!-- WIZARD_PRESENTATION_STATES_END -->

`0x0054BA80` is the live wizard presentation reader. The terminal selector at
`0x00538550` is exactly:

```text
if actor+0x160 == 0: not in terminal presentation
else if D <= 150: terminal delay pose
else: frame = min(trunc((D - 150) / 3), 3)
```

The legal edges are therefore:

<!-- WIZARD_PRESENTATION_TRANSITIONS_BEGIN -->
```text
absent -> idle
idle <-> walk
idle|walk -> action_tick_0(mode,K_previous) -> action_pose(mode,K) -> idle|walk
action_pose(mode,K) -> action_pose(mode,K_next)               (only its table order)
action_pose(mode,K) -> action_tick_0(next_mode,K)              (queued successor)
idle|walk|action_tick_0|action_pose -> hit_overlay(base) -> same underlying state
idle|walk|action_tick_0|action_pose|hit_overlay(base) -> death_delay
death_delay -> death_frame_0 -> death_frame_1 -> death_frame_2 -> death_frame_3
death_frame_3 -> absent
```
<!-- WIZARD_PRESENTATION_TRANSITIONS_END -->

Death has highest presentation priority. A queued action owns the body and
attachment selector even while locomotion continues underneath it; movement
and button release do not cancel that action. Hit presentation interrupts
neither action art nor locomotion. Respawn starts a new actor at `idle` rather
than traversing a reverse death edge.

### Wizard action pose programs

These are presentation programs, not spell behavior. The queue insertion is
the G4 entry trigger; the input/spell rule that chooses an action belongs to
its gameplay owner. `p` starts at zero, then the common tick at `0x004486E0`
adds `actor_delta(+0x120) * rate`. An array action writes
`K=frames[trunc(p)]`, fires its configured marker on a crossing, and completes
only when `p > end`.

| Mode / native constructor | Exact pose program | Rate and completion |
| --- | --- | --- |
| `1`, Staff melee `0x0044AE50` | alternates via `actor+0x240`: `[0,4,5,6,6,6,6,6,6]` or `[0,1,2,3,3,3,3,3,3]` | `rate = 0.1 + NativeRandomFloat(0.05,0)`; the native one-in-eight branch at constructor time multiplies that by `1.35`; marker `3`, end `8` |
| `2`, Staff spin `0x00448750` | `K=3`; heading changes by `20 * random_sign` each action tick | duration starts `360` and loses `20` per fixed tick: exactly 18 action ticks |
| `3`, Staff Cast 1 `0x0044B170` | RNG branch A `[1,8,7,7,7]`, branch B `[8,7,7,7,7]` | rate `0.075`, marker `1`, end `4`; the live golden covers insertion `K=0` then branch A `1 -> 8 -> 7` |
| `4`, Staff Cast 2 `0x0044B7E0` | `[9,9,9,9,9,9]` | rate `0.1`, marker `0`, end `5` |
| `5`, Staff one-shot | `[7]` | one fixed action tick: write, callback, complete (`0x0044C810`) |
| `6`, bare-hand Cast 1 `0x0044B400` | RNG branch `[3,1,2,2,2]` or `[0,1,2,2,2]` | rate `0.095`, marker `1`, end `4` |
| `7`, bare-hand Cast 2 `0x0044B5E0` | `[1,3,3,3,3,3,3]` | rate `0.095`, marker `1`, end `6` |
| `8`, bare-hand one-shot | `[2]` | one fixed action tick: write, callback, complete (`0x0044C810`) |
| `9`, Wand Cast 1 `0x0044DF60` | `[15,15,14,14,14,14]` | rate `0.1`, marker `1`, end `5` |
| `10`, Wand Cast 2 `0x0044E0D0` | `[15,16,16,16,16,16,16]` | rate `0.095`, marker `1`, end `6` |
| `11`, Wand one-shot | `[0]` | one fixed action tick: write, callback, complete (`0x0044C810`) |
| `21`, cast spin `0x00448860` | `K=3` without equipped art, otherwise `K=9`; custom heading path | phase adds `2.5` per fixed tick and completes on `phase > 180`: 73 ticks |
| `22`, sweep `0x004488F0` | `K=3` without equipped art, otherwise `K=9`; custom interpolated heading arc | phase adds `duration/72` per fixed tick and completes on strict `phase > duration`: 73 ticks |

The mode-3 live delta is `0.0562500022` because that run's captured
`actor_delta` is `0.75`: `0.75 * 0.075`. That is direct evidence against
turning the rate into “one sprite per render frame.”

## Enemy presentation state machines

G3 owns why an enemy chooses `approach`, `range_control`, an action ID, or a
special. G4 maps those decisions to visible states. Several G3 states collapse
to one visual state: `search`, `cooldown`, `range_control`, and stationary
waiting use `idle` unless position changed on that fixed tick; `approach`,
`retreat`, `orbit`, and repositioning use `walk`/motion art. A hit does not
select a separate body bank for any compiled family. Enemy death normally
retires the body immediately and spawns bouncer/unbind/death-effect actors;
`death_handoff` names that one-way body-to-effects edge, not a persistent dead
enemy sprite.

`action_windup`, `action_active`, and `action_recovery` are presentation
regions around the action progress markers. `action_active` is an edge (and
can occur more than once), not a promise that one unique sprite exists. Exact
decision predicates and gameplay output at the marker remain in G3.

<!-- ENEMY_PRESENTATION_STATE_LIST_BEGIN -->
| Family / type | Complete visible-state list | Sprite selector and distinct facings |
| --- | --- | --- |
| `Badguy 0x3E8` | `absent`, `invisible_alive`, `death_handoff` | base render slot is no-op `0x0055C300`; zero body facings |
| `Skeleton 0x3E9` | `idle`, `walk`, `claw_windup/active/recovery`, `weapon_windup/active/recovery`, `pike_windup/active/recovery`, `hit_overlay`, `death_handoff` | articulated BadGuys banks; 18 facings; renderer `0x0048DEE0` |
| `SkeletonArcher 0x3EA` | `idle`, `walk/range_control`, `shot_windup/active/recovery`, `hit_overlay`, `death_handoff` | articulated BadGuys banks; 18 facings; renderer `0x0048F450`; render raises the G3 `+0x248` presentation-ready latch |
| `SkeletonMage 0x3EB` | `idle`, `walk/range_control`, `cast_windup/active/recovery`, `shield_special`, `hit_overlay`, `death_handoff` | articulated BadGuys banks; 18 facings; renderer `0x00491720` |
| `Imp 0x3EC` | `airborne`, `fly`, `contact/cooldown`, `hit_overlay`, `death_handoff/split` | BadGuys `285..342`; `facing + 12*pose(+0x220)`; 12 facings; renderer `0x00492E10` |
| `GoodImp 0x3ED` | `airborne`, `fly`, `contact/cooldown`, `hit_overlay`, `ally_release` | same four 12-facing Imp body banks; terminal ally release does not enter hostile reward death |
| `GreenImp 0x7FC` | `airborne`, `fly`, `contact/cooldown`, `hit_overlay`, `death_handoff` | Unholy `41..98`; same 12-facing selector; renderer `0x004930D0` |
| `Zombie 0x3EE` | `idle`, `walk`, `punch_windup/active/recovery`, `hit_overlay`, `death_handoff/pool` | articulated BadGuys action banks; 18 facings plus actor-local angular offset; renderer `0x00493390` |
| `Wraith 0x3EF` | `idle/approach/orbit/retreat`, `attack/cooldown`, `fade`, `hit_overlay`, `death_handoff` | one facing-only BadGuys strip `2070..2087`; 18 facings; state changes alpha/overlays rather than body record; renderer `0x00496220` |
| `DemonSkull 0x3F0` | `idle/schedule`, `bite`, `eye`, `beam`, `spit`, `scream`, `flair`, `recovery`, `hit_overlay`, `death_handoff` | Unholy body banks `99..218`; `facing + 24*pose(+0x224)`; 24 facings; renderer `0x004974D0` |
| `Demon 0x3F1` | `idle/schedule`, `walk`, `bomb_windup/active/recovery`, `fire_special`, `hit_overlay`, `death_handoff/split` | Demon `1..115`; ordinary body is `facing + 18*pose(+0x2DC)`, six articulated point groups; 18 facings; seven-record terminal/special overlay is time-indexed, not a seventh facing set; renderer `0x00498BA0` |
| `DireFaculty 0x3F2` | `idle`, `walk/range_control`, `primary_windup/active/recovery`, `secondary_windup/active/recovery`, `cooldown`, `hit_overlay`, `death_handoff` | Faculty `1..522` = 29 banks x 18; normal `facing + 18*trunc(phase)`, special `+0x240` selects its alternate body/arm banks; renderer `0x0049DF30` |
| `Heartmonger 0x3F3` | `idle/orbit`, `crow_attack`, `summon`, `cooldown`, `hit_overlay`, `death_handoff/detach` | Heartmonger `110..379` = 15 banks x 18; two articulated phases (`+0x248`, `+0x250`) and variant `+0x2B8`; 18 facings; renderer `0x0049F870` |
| `Crow 0x3F4` | `orbit`, `scan`, `dive`, `strike`, `return`, `detached`, `death_handoff` | Heartmonger `2..109` = 6 banks x 18; `facing + 18*trunc(orbit/dive phase)`; 18 facings; renderer `0x004A1490` |
| `Coffin 0x3F5` | `closed`, `opening`, `transition_delay`, `open`, `hit_overlay`, `death_handoff` | no facing; direct lid/body phase selects BadGuys `175..187` and `383..392`; renderer `0x0049AC90` |
| `Maggot 0x7FD` | `ballistic_emerge`, `crawl`, `bite`, `death_handoff` | ballistic lane is `orientation(0..9) + 10*phase`; grounded lane is `facing + 18*pose(+0x238)` over BadGuys `202..237`; 10 airborne orientations, 18 grounded facings; renderer `0x0049C190` |
| `Spider 0x809` | `approach`, `hop/lunge`, `web_windup`, `grab/hold`, `suck`, `recovery`, `hit_overlay`, `death_handoff` | raw G3 states `0..5` feed `facing + 18*pose(+0x22C)`; BadGuys `1840..2001`; 18 facings; renderer `0x004A1670` |
| `Cocoon 0x80A` | `attach`, `hold`, `release/death_handoff` | no body renderer (`0x0055C300`); the visible web/cocoon art belongs to the target modifier/effect actors, so zero body facings |
| `Portal 0x139D` | `materialize`, `idle`, `spawn_flash`, `death_handoff` | no heading facing; first 10 fixed ticks use the materialization helper, then the procedural phase at `+0x214` selects the four BadGuys records `251..254`; renderer `0x004A1B30` |
<!-- ENEMY_PRESENTATION_STATE_LIST_END -->

### Legal transitions and interruptions

The following is the complete visible relation. A slash-delimited state in the
table above means several G3 decisions deliberately share one sprite state;
moving between those decisions creates no G4 edge.

<!-- ENEMY_PRESENTATION_TRANSITIONS_BEGIN -->
| Family | Legal visible edges | Interrupt rule |
| --- | --- | --- |
| Badguy | `absent -> invisible_alive -> death_handoff -> absent` | death is the only visible interrupt |
| Skeleton | `idle <-> walk`; either -> selected claw, weapon, or pike `windup -> active -> recovery`; recovery -> idle/walk; recovery -> active for a later marker; any alive -> `death_handoff -> absent` | queued action is presentation-atomic except its own later markers; death interrupts all |
| SkeletonArcher | `idle <-> walk/range_control -> shot_windup -> active -> recovery -> idle/walk/range_control`; any alive -> death handoff | target/range changes do not cancel a queued shot; death interrupts it |
| SkeletonMage | `idle <-> walk/range_control -> cast_windup -> active <-> recovery -> idle/walk/range_control`; `walk/range_control -> shield_special -> walk/range_control`; any alive -> death handoff | later configured markers may re-enter active; death interrupts cast/shield |
| Imp / GreenImp | `airborne -> fly -> contact/cooldown -> fly`; any alive -> death handoff, then hostile Imp may split | contact does not reset the flight pose; death interrupts all |
| GoodImp | `airborne -> fly -> contact/cooldown -> fly`; any alive -> ally release -> absent | lifetime release interrupts contact and never runs hostile death art/reward |
| Zombie | `idle <-> walk -> punch_windup -> active -> recovery -> idle/walk`; any alive -> death handoff/pool | queued punch completes unless death occurs |
| Wraith | `idle/approach/orbit/retreat <-> attack/cooldown`; either <-> fade; any alive/fade -> death handoff | fade is orthogonal alpha state; death interrupts it |
| DemonSkull | `idle/schedule -> bite, eye, beam, spit, scream, or flair -> recovery -> idle/schedule`; any alive -> death handoff | specials do not interrupt one another; death interrupts any special |
| Demon | `idle/schedule <-> walk`; either -> bomb windup -> active -> recovery -> idle/schedule; either -> fire special -> prior locomotion; any alive -> death handoff/split | death interrupts bomb/fire; movement never interrupts queued bomb |
| DireFaculty | `idle <-> walk/range_control`; range control -> primary or secondary windup -> active -> recovery -> cooldown -> range control; any alive -> death handoff | active action is atomic except death |
| Heartmonger | `idle/orbit -> crow_attack or summon -> cooldown -> idle/orbit`; any alive -> death handoff/detach | crow/summon effects are children; parent death interrupts body and detaches survivors |
| Crow | `orbit -> scan -> dive -> strike -> return -> orbit`; any owned state -> detached; any -> death handoff | parent invalidation interrupts the cycle and detaches/cleans up |
| Coffin | `closed -> opening -> transition_delay -> open`; open loops through spawn flashes; any state -> death handoff | opening is one-way; only death interrupts it |
| Maggot | `ballistic_emerge -> crawl -> bite -> death_handoff`; parent invalidation -> death handoff | bite is single-use and immediately terminal |
| Spider | `approach -> hop/lunge or web_windup -> grab/hold -> suck -> recovery -> approach`; target loss from any target-owned state -> approach; any alive -> death handoff | target loss cancels hold/suck; death interrupts every state |
| Cocoon | `attach -> hold -> release/death_handoff -> absent` | target loss/release is the only interrupt |
| Portal | `materialize -> idle`; idle -> spawn_flash -> idle; any -> death handoff | materialization is not attack-interruptible; death is terminal |
<!-- ENEMY_PRESENTATION_TRANSITIONS_END -->

For every family, `hit_overlay -> same underlying state` is legal and does not
restart its phase. It is omitted from each row only to avoid repeating the
same orthogonal edge nineteen times.

## Frame lists and exact cadence

The table below is an implementation table, not a catalog of every piece of
an articulated actor. A range `A..B = n x F` means bank `b`, facing `f` selects
`A + F*b + f`. G12 decides how all pieces selected for that pose are ordered
and transformed.

<!-- ANIMATION_FRAME_TIMING_BEGIN -->
| State/family | Frame list / selector | Fixed-tick cadence |
| --- | --- | --- |
| Wizard idle/walk | Clothes equipment lanes use the 24-facing locomotion selector; `K=0` for the staff attachment pose | walk phase is written by the Player fixed tick; renderer only samples it |
| Wizard queued actions | the complete arrays for modes `1..11,21,22` are in the action-program table above | common array modes use `p += actor_delta * rate`, `K=frames[trunc(p)]`, strict `p>end`; custom modes give their exact fixed-tick duration above |
| Wizard Staff Cast 1 | insertion retains `K=0`; branch A `[1,8,7,7,7]`, branch B `[8,7,7,7,7]` | rate `0.075 * actor_delta`; marker `1`, strict end `4`; live branch A transitions at ticks `7945/7946/7963/7981/8018` |
| Wizard hit overlay | body/equipment selector remains the underlying state; Magic Shield pulse is actor `+0x1D0` | accepted shield damage sets `2.0`; each Player fixed tick applies `max(value-0.05,0)`, so the pulse lasts exactly 40 ticks unless refreshed; render only samples it |
| Wizard death | delay pose through `D=150`; frames `[0,1,2,3]` from `min((D-150)/3,3)` | `D` increments once per fixed tick; frame 0 lasts 2 ticks (`151..152`), frames 1 and 2 last 3 ticks, and frame 3 holds |
| Skeleton claw `0x0E` | body-pose program is variant byte `+0x233==0`: `[4,5,6,7,8,9,10,11]`; `==1`: `[2,3,4,5,6,7,8,9]`; selector written to `+0x150` | `p += 0.125 * attack_speed * marker_multiplier`; callbacks on crossings `4` and `8`, wrap/finish boundary `7`; every array lookup uses `trunc(p)` |
| Skeleton weapon `0x0F` | `[1 x8, 2, 3 x8, 2 x4, 1 x4]` at progress indices `0..24`, written to `+0x150` | `p += 0.25 * attack_speed * marker_multiplier`; callbacks `9` and `20`, strict end `24` |
| Skeleton pike `0x10` | `[1, 2 x11, 1]` at indices `0..12`, written to `+0x150` | `p += 0.125 * attack_speed * marker_multiplier`; callback `2`, strict end `12` |
| Archer shot `0x11` | `[3,4,5,6,7,6,7,6,7,6,7,6,7,8,8,8,8]` at indices `0..16`, written to `+0x150` | `p += 0.0843750015 * attack_speed`; callback `13`, strict end `16` |
| Mage cast `0x12` | short branch `[2 x24,3,4 x13,3,0 x3]`; long branch `[2 x30,3,4 x13,3,0 x3]`, written to `+0x150` | `p += 0.253125012 * (1 + roll) * attack_speed`; callback `25`/`31`, strict paired end `41`/`47` |
| Skeleton family locomotion | articulated 18-facing banks: Skeleton `775..918` (8), `1045..1116` (4), `1333..1458` (7), `1585..1728` (8); Archer `451..612` (9) plus shared 8; Mage `1459..1476` (1), `1729..1818` (5), `1585..1728` (8) | renderer truncates fixed-tick locomotion/action phases at `+0x144/+0x150`; no render-side advance |
| Imp family | `facing + 12*pose(+0x220)` over four complete directional body banks; extra tail records are effects, not a fifth 12-way pose | flight tick writes integer pose and bob/alpha fields once per fixed tick |
| Zombie | 18-way articulated selectors over `2088..2220`, `2275..2310`, `2365..2508`; action progress chooses the attack bank | fixed Zombie/action tick; no render-side advance |
| Wraith | one list `[2070..2087]`, facing only | no body-frame cadence; fixed tick changes fade alpha/overlays |
| DemonSkull | five 24-way banks `[99..218]`, selected by `+0x224`; special effects use separate records | fixed boss/action tick writes pose; renderer samples it |
| Demon | six 18-way articulated banks plus seven time-indexed special records `[1..115]`; body bank is byte `+0x2DC` | fixed boss/action tick writes bank and `+0x140`; renderer samples `sin(+0x140 * 0.25)` for articulation but does not advance it |
| DireFaculty | 29 18-way banks `[1..522]`; ordinary phase plus explicit special-bank integer `+0x240` | fixed Faculty/action tick; action marker frames 15 (`0x1F`) and 20 (`0x20`) are sampled from action progress |
| Heartmonger | 15 18-way banks `[110..379]`; two phase selectors and `+0x2B8` variant | fixed Heartmonger tick writes `+0x248/+0x250`; renderer only samples |
| Crow | six 18-way banks `[2..109]` | orbit/dive phase is updated once per Crow fixed tick; render is read-only |
| Coffin | non-directional lists `[175..187]` and `[383..392]`; lid/body phase is direct, not multiplied by a facing count | Coffin fixed tick owns all four state transitions and phase writes |
| Maggot | grounded two 18-way banks `[202..237]`; ballistic list is `orientation + 10*phase` | Maggot fixed tick writes `+0x238` on ground and ballistic orientation/phase in emerge state |
| Spider | nine 18-way banks: `[1840..1911]`, `[1912..1929]`, `[1930..2001]`; selector `facing + 18*+0x22C` | Spider fixed tick maps raw states `0..5` to pose; renderer never changes `+0x22C` |
| Cocoon | no body frame list | target modifier/effect lifetime is fixed-tick owned |
| Portal | materialization helper for ticks `0..9`, then non-directional procedural records `[251,252,253,254]` from `trunc(+0x214)` | `Puppet_TickBase` and Portal tick run at 100 Hz; after materialization the phase/RNG draw occurs in that fixed tick, not render |
<!-- ANIMATION_FRAME_TIMING_END -->

The exact skeleton-family rates above are repeated from G3 only because they
are the clock-to-frame boundary. Damage callbacks, target rules, and action
selection remain G3 territory.

## Facing

The enemy renderers below add the half-step, divide, then call `0x00747360`;
its ordinary `FISTP` path uses the default x87 round-to-nearest-even mode.
Do not substitute JavaScript `Math.round`, truncation, floating modulo, or a
continuous sprite rotation. The independently recorded Wizard/DemonSkull path
retains its integer formula below.

<!-- ANIMATION_FACING_BEGIN -->
| Family | Mapping | Distinct rendered facings |
| --- | --- | ---: |
| Wizard, staff, wand, cast sockets; DemonSkull | `f=((int)heading+7)/15; if f>=24 f-=24` | 24 |
| Skeleton, Archer, Mage, Wraith, Demon, DireFaculty, Heartmonger, Crow, grounded Maggot, Spider | `f=roundEven((heading+10)/20); positiveMod(f,18)` | 18 |
| Zombie | same 18-way round-even formula after adding its fixed-tick actor-local angular offset `+0x21C` to heading | 18 |
| Imp, GoodImp, GreenImp | `f=roundEven((heading+15)/30); positiveMod(f,12)` | 12 |
| airborne Maggot | renderer truncates its ballistic orientation and wraps it into `[0,9]`; this is spin orientation, not world heading | 10 |
| Coffin, Cocoon, Portal | heading does not select body art | 1 / none |
<!-- ANIMATION_FACING_END -->

The cast-emitter recording independently forces headings `0,15,...,345` and
calls retail `0x0053B830` after each write. Every facing `0..23` is marked
`observed`, `derived_only=false`, and matched to the corresponding shipped
point within `1e-4` world units. A separate heading-359 sample proves the
single conditional wrap to facing zero. None of those observations is a
replay of the formula: the formula is merely the assertion under test.

## Attachment points

<!-- ANIMATION_ATTACHMENT_BEGIN -->

### The three directional point families

The apparent single `#460..#579` run crosses two native arrays. Naming that
boundary matters to a port:

| Clothes records | Native source | Meaning / consumer |
| --- | --- | --- |
| `#460..#483` | `g+0x590` | 24-facing unarmed hand/socket reference bank used by wizard composition `0x00538B80` / `0x0061AF10` |
| `#484..#603` | `g+0x5A0` | five 24-facing bare-hand cast/attachment pose banks; `#484..#579` have the two-point shape and the last bank `#580..#603` has no usable point list; null-sprite-set emitter `0x0053B830` uses its facing bank |
| `#796..#867` | `g+0x5D0` | three 24-facing **wand** pose banks; points 0 and 1 form the hand-to-wand-tip segment passed to the Wand renderer (`vt+0x20`), and point 1 is the cast emitter |
| `#3244..#3483` | Staff type `7004` (`0x1B5C`) virtual point array | ten 24-facing **staff** pose banks; point 1 is the staff-orb/cast socket; `#3484..#3723` is the paired secondary staff-art array, not another emitter table |

Thus the inherited unnamed runs are not enemy sockets: `#460..#579` belongs
to the wizard's bare-hand composition and `#796..#867` belongs to the wand.

### Staff 7004 as the reference transform

`actor+0x238` is the wizard's **equipment/body render-pose selector**. Its
integer part is `K`; it is not wall time and not a projectile property. The
authoritative Staff Cast 1 branch-A trace is insertion `0`, then action poses
`1 -> 8 -> 7`, then reset `0`; branch B omits pose `1`. G2's Earth trace sees
`K=0` on its first held-emitter sample and `K=7` on later samples because that
projectile recorder samples the cast callback/held path, not every intervening
Player action tick. The G4 fixed-tick lane is the complete bank history.

For Staff object type 7004 (`0x1B5C`), the emitter is:

```text
f = facing24(actor.heading)
K = trunc(actor.render_pose_bank)          // actor+0x238, unclamped
record = Clothes[#3244 + 24*K + f]
local = record.point[1]
world_emitter = actor.position + local     // deliberately NO actor scale
```

The absence of scale is specific to the Staff virtual path in `0x0053B830`.
The null/bare-hand and wand paths add `actor.scale * point`. Wand bank is
`clamp(trunc(actor+0x238 - 14),0,2)`. The common record stride is `0xC4`, point
count is at `+0xAC`, point-list pointer at `+0xA8`, and the emitter reads point
index 1.

The attachment is evaluated twice for two different purposes:

1. `0x0061AF10` evaluates current facing and pose during each **render** and
   builds the attached visual transform. Heading changes can therefore change
   the staff/wand orientation on the next render even if no fixed tick ran.
2. `0x0053B830` evaluates the same current fields at the **fixed-tick cast
   event** to choose a gameplay spawn origin. That point remains the spawned
   projectile's origin; later facing changes do not drag the projectile.

G12 consumes the resulting matrix/point in its `world-sorted` actor draw; it
owns matrix-to-quad composition and draw order.
<!-- ANIMATION_ATTACHMENT_END -->

## Actor lighting and shadows

<!-- ANIMATION_LIGHTING_SHADOW_BEGIN -->

The ordinary actor path is `Puppet_RenderDispatch 0x00624B40`. With Complex
Lighting enabled (`0x00B3BCA8`), it samples the finalized Region light field
through `0x0057F980`, `0x0057F0E0`, or the transformed query `0x0057E490`,
stores the scalar at actor `+0xCC`, multiplies that scalar by the actor's base
RGBA lanes, calls the body render virtual, then restores renderer color. With
Complex Lighting disabled the scalar is `1`. The animation fixture records
both the submitted tint and `lighting_scalar`; an implementation must not bake
the sample into the atlas.

Actor flash/hit color is an additional actor-local multiplier and does not
select another sprite state. Wraith fade and Imp alpha are likewise local
alpha values before the ordinary source-alpha blend. The exact fog/tint/blend
composition after those values are chosen is G12 territory; see
[`Fog, lighting, tint, alpha, and blend`](native-scene-composition.md#fog-lighting-tint-alpha-and-blend)
instead of adding a second fog equation here.

The common dispatcher invokes the actor's shadow/effect virtual only when its
shadow lane is non-zero. Complex Shadows and Multiple Shadows are the stock
globals `0x00B3BCA9` and `0x00B3BCAA`; they affect whether/how many native
shadow submissions are made, not the actor's frame phase. Ordinary shadow art
is submitted before/around the body by the actor virtual and remains subject
to G12's physical pass/sort rules. Death fragments are separate
`Anim_Bouncer` actors: with Enhanced Effects, their shadow is a black copy at
`(x,y+2)`, scale `(1,0.75)`, drawn before the colored fragment, as pinned in
[`skeleton-death-effects-re.md`](../skeleton-death-effects-re.md#bouncer-physics-and-rendering).

The normal wizard light source is presentation state but not visible sprite
art: while its stock predicate is true it submits a light 15 world units along
heading with radius `2.6`, intensity `1`, flag `1`. G12 owns how that source
affects later object samples.
<!-- ANIMATION_LIGHTING_SHADOW_END -->

## Camera constants consumed by animation

<!-- ANIMATION_CAMERA_BEGIN -->

The earlier [`native-camera-control.md`](native-camera-control.md) layout is
confirmed without correction:

| Region field / function | Animation-layer use |
| --- | --- |
| `+0x80` scale | uniform world-units-to-pixels scale applied after actor/attachment world transforms |
| `+0x8BCC/+0x8BD0` primary origin | subtract before scaling; the sole semantic projection origin |
| `+0x8BD4/+0x8BD8` primary size | viewport and focus clamp |
| `+0x8BDC/+0x8BE0` expanded origin | observation margin only, not an attachment origin |
| `+0x8BEC/+0x8BF0` culling origin | decides whether an actor is submitted, never which animation frame it advances to |
| `+0x8E04/+0x8E08` shake magnitude/accumulator | presentation-only displacement after semantic camera origin; never feeds heading or attachment points |
| `0x0063ED80` / `0x00462110` | `(world-origin)*scale` and `screen/scale+origin` |

Fixed-room camera interpolation remains `0.25` per camera update. Skeleton
death requests shake intensity `0.1`. Neither constant is an animation clock;
camera culling must not pause an actor's fixed-tick phase. Exact vertex
projection, culling margins, and composition are cited from G12 rather than
restated.
<!-- ANIMATION_CAMERA_END -->

## Live golden contract

Each capture header names instance, source commit/tree SHA, dirty-state flag,
retail EXE hash, built/staged loader hashes, process/executable, method,
10 ms tick anchor, and epsilon. Those values are derived by the recorder;
there is no CLI provenance override. Float tolerance is `1e-4` world units
for x87/float32 serialization and `0.001` screen pixels, both far below an
observed movement or art step.

Before each asynchronously populated actor surface is captured, the recorder
runs a structural settle gate made of two independent captures, each with at
least 40 byte-identical actor-set samples spanning at least two seconds. This
includes the real Skeleton target used to make the stock cast-input path
deterministic; that target is pinned only through the existing native-input
seam and is retired before family capture. The recorder refuses duplicate
actor-address candidates, output collisions, a missing pipe/process, and
partial frame sequences. The committed fixture contains:

- contiguous wizard `idle`, `idle -> walk -> idle`, a stock Skeleton-driven
  `idle -> hit_overlay -> idle` whose isolated hit decays without refresh,
  target-pinned native input producing
  `idle -> cast_pose_0 -> cast_pose_1 -> cast_pose_8 -> cast_pose_7 -> idle`,
  and full terminal-counter sequences;
- live Skeleton, Skeleton Archer, and Skeleton Mage action progress around
  windup/active/recovery plus the body-to-death-effects handoff;
- all 24 independently invoked native staff emitter facings, the 359-degree
  wrap, and a bank-zero reference;
- exact launch and exact-owned-PID cleanup receipts.

## Not Yet Reversed

No sprite-state, legal presentation edge, facing count, tick domain, or G4
attachment run is left unnamed. The live fixture intentionally gives exhaustive
transition coverage only for the wizard and Skeleton family, as required; the
remaining compiled families are static renderer/tick reconstructions and are
marked as such by their native addresses rather than presented as live
captures. G3 remains the authority for the behavior predicate that chooses
each listed action, and G12 remains the authority for assembling the selected
pieces into pixels.
