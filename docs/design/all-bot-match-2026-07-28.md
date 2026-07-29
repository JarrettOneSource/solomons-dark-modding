# All-bot match foundation

Status: implementation and live acceptance complete.

This wave establishes a repeatable four-fighter bot match, fixes the native
fence-gate pathfinding class, and measures the current progression wall. It
does not add skill-choice intelligence or inventory management.

Evidence for this wave is rooted at
`/mnt/d/codex-evidence/botmatch-20260728/`. Production hosting and
`solomondarker.com` are outside this wave.

## Four fighters in four native slots

The game has four gameplay records, not four remote-participant records:

- `Gameplay` construction at `0x005CC800` initializes four slot records.
- Slot actor pointers are at `gameplay + 0x1358 + slot * 4`.
- Slot progression pointers are at `gameplay + 0x1654 + slot * 4`.
- Slot 0 is the locally controlled player actor. Synthetic participants occupy
  slots 1 through 3.
- Native enemies resolve and retain gameplay-slot actor targets. A fifth
  loader-only actor would not be a fifth native targetable fighter.

The foundation therefore maps "four bots" to one automated local player in
slot 0 plus three synthetic participant bots in slots 1 through 3. There is
one game process and no human input after launch. The local player is driven
through native movement/input and native casting paths; it is not replaced
with a fifth standalone clone. The three synthetic participants use the
existing native-slot bot materialization and bot-brain control paths.

Live run-entry evidence is captured in
`investigation/rootcause-retail-fourseat-run-entry.json`. It also exposed an
orchestration requirement: participant transforms from the hub cannot simply
remain attached to hub coordinates after the testrun world is created. The
runner must perform the normal scene-entry materialization/reanchor once, then
all route progress is physical movement. Scene entry is not a stuck recovery,
and no transit teleport is allowed.

## Fence-gate root cause

### Native class and collision mechanism

The visual opening in the hub route is a pair of native `Gate` objects:

- Native type `0xBC4` (3012), vtable `0x00799D9C`.
- Constructor/builder path `0x005A9C60` / `0x005F73C0`.
- Moving collision builder `0x005ED4D0`.
- Motion/contact tick `0x005ED5F0`.
- Serializer `0x005E3910`.

The collision builder calls the native segment-registration function at
`0x005213C0` with `0x64` as its first policy value and `0x100` as the
segment collision mask. The returned 24-byte record is stored at
`Gate + 0x1C8`; its mask is record field `+0x14`.

The extended placement query at `0x005238C0` has two different policies:

1. raw movement circles block when their mask intersects
   `circle_block_mask`;
2. shape and line-segment overlaps block when their mask does **not**
   intersect `overlap_allow_mask`.

`0x100` is not, by itself, an openable flag. `FenceGrate::Setup` at
`0x005E8650` registers fixed grate segments with the same mask. A mask-only
allow rule therefore opens every fixed grate to A*. A rejected live attempt
demonstrated the failure: three bots fanned out to `(1167, 2964)`,
`(1460, 2964)`, and `(1317, 3053)` around a Gate spanning approximately
`x=1289..1412`; all three ultimately used the 30-second failsafe. Those
teleports are diagnostic evidence, not acceptance.

The native class distinction is the virtual collision builder. At vtable slot
`+0x64`, a `Gate` resolves to `0x005ED4D0`; a fixed `FenceGrate` resolves to
`0x005E8650`. The planner scans the native scenery list, recognizes any object
whose collision-builder virtual is the openable builder, and reads that
object's current segment record from `+0x1C8`.

The movement controller's secondary overlap list is query scratch, not a
stable segment registry. Live reads showed `secondary_count=0` while idle;
calling the native placement query at the Gate populated exactly two
secondary entries, both the live `Gate + 0x1C8` records with mask `0x100`.
The segment mask is at record `+0x14`; record `+0x10` is the separate `0x64`
registration policy. Reusing the primary-overlap `+0x10` mask offset for
segments therefore misclassifies every Gate.
An intermediate implementation that snapshotted the secondary list before
the query therefore captured no openable records. Its path chose waypoint
`(1550, 350)`, made zero-displacement contact at approximately
`(1572, 336)`, and eventually invoked the 30-second failsafe. That run is
diagnostic rejection evidence.

Placement is a two-phase native query. The normal query keeps `0x100` blocked.
After that query builds its exact per-candidate secondary overlap list, the
planner compares each `0x100` record address with the openable records owned
by native scenery objects. It retries with `0x100` temporarily allowed only
when at least one overlapping record is openable and none is an unowned
same-mask record. A candidate that also overlaps a fixed grate therefore
remains blocked. Execution still calls the stock movement path and must
physically push the Gate.

The first class-correct planner attempt exposed a second, independent route
shape defect. A* reduced an otherwise clear straight approach to the cell
center `(950, 3750)`. The bot struck a hinged leaf obliquely, moved it by
`49.25` units, lodged at approximately `(1023, 3726)`, and was eventually
recovered by the forbidden 30-second failsafe. The class test was correct,
but that transit was rejected.

The path builder now preserves an exact requested destination as a single
waypoint whenever both its placement and the complete current-to-destination
native segment test pass. A* remains the fallback around real obstacles.
This is a general direct-route rule, not Gate knowledge: it avoids injecting
an artificial cell-center corner into any clear continuous approach and lets
stock movement maintain the contact direction needed by hinged obstacles.

The old policy did not identify this class. It special-cased type `0xBBE`,
radius 10 as a "gate." Native factory and live-object evidence identifies
`0xBBE` as `Fencepost`, a fixed endpoint object. The policy also put static
mask `0x4` into `overlap_allow_mask`, causing native static segments/shapes to
look traversable. A live bot planned through a fixed gravestone/fence cluster
near `(1628, 2445)` and remained there; that was not the hub Gate. The
per-cell and native placement trace is
`investigation/live/gate-native-collision-scan.txt`.

Live object inspection found the actual Gate pair near
`(1587.9, 3394.9)` and `(1524.7, 3400.6)`, including their live collision
records, endpoints, and motion fields. See
`investigation/live/gate-object-probe.txt`.

### Contact proof

A stock slot-0 movement-input drive crossed the closed Gate:

- 531 native input frames;
- maximum Gate velocity `1.9200002`;
- maximum moving-endpoint displacement `49.5022` world units;
- no position write and no stuck-failsafe teleport.

The status samples are in
`investigation/live/stock-gate-contact-status-01.txt`. This proves that the
native execution path already opens the obstacle on contact; only the planner
classification is wrong.

The final class-fix acceptance used a freshly closed Gate pair and a synthetic
slot actor:

- start `(1374, 240)`, destination `(1374, 360)`;
- final position `(1373.973389, 353.896637)`, `6.103421` units from target;
- both leaves moved, with peak measured endpoint displacement
  `67.281424` units;
- the bot stopped normally with 50/50 health; and
- no `stuck teleport`, failsafe-teleport, zero-displacement, or route-rebuild
  marker occurred in the acceptance window.

This is physical transit across 120 world units through a closed Gate, not a
position correction. The captured result is
`investigation/live/gate-classfix-accepted.txt`; the owned process ledger pins
the exact executable and PID used for the run.

### Class-level fix

The planner policy is:

- fixed static circles (`0x4` without `0x2000`) remain blocked;
- native pushable circles (`0x2000`) are planner-traversable;
- segments owned by the native openable collision-builder class are
  planner-traversable through the local two-phase query;
- fixed segments remain blocked even when they share mask `0x100`;
- fixed static shapes and segments remain blocked;
- physical movement executes every accepted route and supplies the real
  contact that moves the obstacle.

The policy does not contain Gate object types, radii, coordinates, or map
names. It identifies the behavior class by its native virtual collision
builder and live collision-record ownership. It therefore covers every object
using that openable builder while continuing to reject ordinary grates,
fences, walls, gravestones, and trees. Pushable circle objects remain
classed by their native `0x2000` physics bit.

Gate motion is serialized by the retail object serializer, but it is not a
field in the multiplayer runtime snapshot protocol. Run snapshots replicate
enemies, the two named run-static actors, loot, and native minions; type
`0xBC4` Gate state is not included. This all-bot acceptance uses one
authoritative process, so no new gate replication seam is required. A future
multi-process gate requirement must add an explicit motion-state contract
rather than infer replication from the retail serializer.

## Match orchestration contract

`tools/run_bot_match.py` owns a fresh staged install and a config-driven run:

1. install the exact built loader, config, and selected mods into a
   wave-owned stage;
2. launch one game process with `SDMOD_DISABLE_AUDIO=1` and only ports
   50511/50512;
3. create a launcher-equivalent four-seat roster;
4. drive the retail menu into the hub and call `sd.hub.start_testrun`;
5. automate slot 0 and materialize slots 1 through 3 in the run scene;
6. route all four fighters through the Gate and regroup on the Dig side;
7. trigger Solomon Dig through the real proximity/conversation path;
8. observe waves using applied-damage edges, fighter health/death/respawn
   transitions, and wave/enemy state;
9. capture required screenshots and structured telemetry; and
10. stop only the exact process launched from the wave-owned stage.

The runner never calls `sd.gameplay.start_waves`. It never writes a fighter
position to cross the Gate, and it rejects any run containing a
stuck-failsafe teleport.

The four-fighter gate approach is a collision-spaced staging region, not four
exact parking points. Live failure evidence showed why that distinction
matters. Native wizard actors have radius 25, and the planner blocks a point
within the sum of two wizard radii plus 0.5. In one failed approach, an early
stopped fighter sat 30.5 units from Ember's nominal target; Ember consequently
stopped 60.7 units short. A second trace left otherwise safely gathered
fighters 34.2–42.9 units from their nominal points because native A* ended at
collision-safe cells.

The accepted approach band therefore includes one additional
collision-spaced row behind the nominal rear row while retaining a strict
gate-facing bound. The next stage aligns and moves fighters one at a time.
`gate-regression-28` proved all four fighters physically crossed: final signed
dig-side progress was 103.52–233.32 against a required 65, and the loader log
contained zero stuck-failsafe teleports.

Wave screenshots are armed directly from `wave.started`, rather than inferred
from the monitor's next 0.5-second sample. The monitor consumes every armed
file, including wave numbers skipped between samples. A blank or
low-information transition frame remains rejected and is retained as
diagnostic evidence; the runner retries the live backbuffer until a frame
passes the unchanged validator. Run 3 exercised this path at run end: the
first frame was 96.89% one color and was rejected, while the second contained
14,278 colors and was accepted.

## Acceptance runs

All values below come from applied native damage edges. `Furthest wave` means
the highest wave that started; it does not claim that wave was cleared.

| Run | Furthest wave | End condition | Damage limiter | Survivability limiter | Evidence |
| --- | ---: | --- | --- | --- | --- |
| 1 | 35 | No wave or applied-damage progress for 120 seconds | 417.400 total damage. Gale accepted 894 casts but produced 0 damage edges. The end snapshot retained 58 Skeletons and 4 Skeleton Archers. | Aster died 4 times and respawned 3; Ember died on wave 28; Brook died on wave 34; Gale survived at 40.775/50 but could not damage anything. | `runs/baseline-final-24/run-01/result.json` |
| 2 | 21 | Native `run.ended` after 490.001 seconds | 182.150 total damage. Gale accepted 281 casts but again produced 0 damage edges. The end snapshot retained 29 Skeletons and 2 Skeleton Archers. | Aster died twice and was observed respawning twice. Ember died on wave 11, Gale on wave 21, and Brook at native run end; no synthetic fighter respawned. Aster had only 0.091/50 HP when the native run ended. | `runs/baseline-final-25/run-01/result.json` |
| 3 | 12 | No wave or applied-damage progress for 120 seconds | 53.850 total damage. Gale was the only living attacker, with 291 accepted casts and 0 damage edges. The end snapshot retained 34 Skeletons. | Aster died twice and respawned once; Brook and Ember both died on wave 12; Gale survived at 34.625/50. | `runs/baseline-final-29/run-01/result.json` |

Run 1's wave-35 plan contained 2 Skeletons, 1 Skeleton Archer, 2 Skeleton
Mages, 1 Imp, 1 Zombie, and 1 Coffin. The live wave summary instead had eight
spawned Skeleton-family actors alive and zero kills; accumulated live-world
state was the 62-enemy backlog above. Every recorded lethal edge in the run
was from a type-1001 Skeleton: Aster on waves 9, 17, 26, and 28; Ember on wave
28; and Brook on wave 34.

Run 2's wave-21 plan contained two Skeletons (and a zero-count Skeleton Mage
row). One Skeleton spawned and was killed before the native run ended, but 31
older live enemies remained. Every lethal edge was again type 1001: Aster on
waves 2 and 10, Ember on wave 11, Gale on wave 21, and Brook at the native
end transition.

Run 3's wave-12 plan contained five Skeletons and one Skeleton Archer. At the
wall, five current-wave Skeletons were alive, the Archer remained to spawn,
and the accumulated world held 34 live Skeletons. Skeleton edges killed Aster
on waves 2 and 9 and killed Brook and Ember on wave 12.

Across the three runs:

- furthest waves were 35, 21, and 12 (mean 22.67);
- applied damage was 653.400 dealt and 874.723 taken;
- Aster dealt 134 damage, died 8 times, and respawned 6 times;
- Ember dealt 222 damage over 209 accepted casts, died 3 times, and never
  respawned;
- Brook dealt 297.400 damage over 958 accepted casts and 11,896 damage
  ticks, died 3 times, and never respawned; and
- Gale accepted 1,466 casts but dealt exactly 0 damage over 0 applied edges,
  died once, and never respawned.

### Screenshot audit

Each accepted result contains `hubGather`, `gateTransit`, `digTrigger`, and
`runEnd`. Wave-plan and validated wave-screenshot counts match exactly:
35/35, 21/21, and 12/12. The actual images were inspected, including combat,
death-tint, and spectator frames; none of the accepted images is blank.

The contact sheets are beside each run's screenshots as
`wave-contact-sheet.png` and `milestone-contact-sheet.png`. Run 2's gather
frame has bodies partly hidden by foreground foliage, but fighter labels,
health bars, and the corresponding four-position arrival record remain
visible. Run 3 retains its rejected run-end transition BMP next to the
accepted retry.

## Progression wall

Ranked by immediate effect on current progression:

1. **The Air primary is a zero-damage slot.** Gale accepted 1,466 casts across
   the three runs and produced 0 applied damage edges. Gale was the final
   survivor in both no-progress endings, so those runs could not finish
   another enemy despite continued accepted casts. The next combat wave must
   determine whether Air's equipped primary needs a delivery fix or whether
   the bot must select a different damaging loadout; accepted-cast counts
   cannot be used as success.
2. **Synthetic death is permanent for the match.** The three synthetic
   fighters recorded 7 deaths and 0 respawns. By contrast, automated slot 0
   recorded 8 deaths and 6 respawns. Run 2 ended natively after all three
   synthetic fighters died; runs 1 and 3 lost the two functioning synthetic
   damage dealers and stalled with zero-damage Gale. A later wave needs an
   explicit synthetic respawn/life-cycle contract before build choices can
   produce durable progression.
3. **There is no sustain or inventory behavior.** The Lua brain has no
   inventory or consumable call. It entered flee mode 7 times in the accepted
   logs and recovered to normal mode 0 times. Because primary casting is
   disabled while fleeing, falling below the configured HP threshold removes
   offense without creating a healing path. Potion selection, timing, and
   stock-aware retreat/recovery should be scoped together.
4. **Progression choices never take effect.** The three synthetic fighters
   reported 0 accepted skill choices in all 9 fighter-runs. The current brain
   contains a small fixed priority list, but no live run consumed a pending
   choice; automated slot 0 has no skill-choice driver at all. The next skill
   wave must first prove that choice generations reach all four fighters,
   then rank choices by build and current wall rather than expanding the
   existing hard-coded list blindly.
5. **Offense is fixed to one nearest-target primary and falls behind spawn
   pressure.** The brain only calls `cast(0)` against the nearest in-range
   target. Brook's Frost primary generated 11,896 small applied ticks for
   297.400 total damage, Ember produced 222, Aster produced 134, and Gale
   produced 0. The final live backlogs were 62, 31, and 34 enemies. Later
   combat work should measure focus fire, secondary/combo choices, and
   damage-per-second against spawn pressure, not merely add more accepted
   cast attempts.

These are measurements and follow-up scopes, not implementations in this
foundation wave.
