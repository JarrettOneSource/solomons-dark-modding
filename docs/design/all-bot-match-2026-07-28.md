# All-bot match foundation

Status: implementation and acceptance in progress.

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

## Acceptance runs

This section is populated from three fresh full-match results after the live
gate and wave-1 smoke gates pass.

| Run | Furthest wave | End condition | Damage limiter | Survivability limiter | Evidence |
| --- | ---: | --- | --- | --- | --- |
| 1 | Pending | Pending | Pending | Pending | Pending |
| 2 | Pending | Pending | Pending | Pending | Pending |
| 3 | Pending | Pending | Pending | Pending | Pending |

## Progression wall

This section is intentionally evidence-gated. The ranked, quantified wall is
written only after all three match runs so later skill and inventory waves are
scoped from observed failures rather than assumptions.
