# World Sync Authority Plan

Date: 2026-05-28

## Scope

This note covers multiplayer synchronization for hub and run-world actors that
are not player participants: roaming hub Students, named hub NPCs, run enemies,
drops, and future spawned world objects.

The immediate live target is the hub Student population because it already
shows the core problem: both local multiplayer clients enter the same hub scene,
but the native game creates and advances their NPC populations independently.

## Current Evidence

### Live multi-client probe

`tools/multiplayer_lua_probe.py` runs one Lua payload against more than one
local client pipe and compares structured `key=value` output. The default
endpoints are:

- `host=SolomonDarkModLoader_LuaExec_local-mp-host`
- `client=SolomonDarkModLoader_LuaExec_local-mp-client`

`tools/probe_hub_world_sync.py` builds on that runner and samples hub actor
state over time. It currently captures scene identity, actor counts, hub actor
counts, and `0x138A` Student fields including transform, heading, movement
drive, wander target, path/state blocks, and several Student-specific raw
fields.

The live result from the local host/client pair was divergent:

- both processes reported the `hub` scene
- total actor counts differed between processes
- `0x138A` Student counts differed between processes
- Student positions, slots, drive state, wander targets, path counts, and raw
  state fields did not line up between host and client

This is enough to reject "they will stay matched if both clients enter the hub"
as a baseline assumption.

`tools/probe_hub_npc_presentation_sync.py` is the focused presentation-state
probe for the same local host/client pair. It compares the host hub NPCs to the
client's bound replicated actors through authoritative snapshot positions, then
checks presentation fields that are not present in the current
`WorldSnapshotPacket`.

The current live run wrote `runtime/hub_npc_presentation_sync.json` and
returned:

- client had a valid, non-truncated `SharedHub` snapshot with `25` replicated
  actors
- `16` hub NPCs were compared against host actors
- all `11` compared Students had divergent `+0x190..+0x1AF` color/state blocks
- `4` of those `11` Students had divergent `+0x23C` primary variant bytes,
  matching the visible book/no-book mismatch
- all `5` compared named hub NPCs had divergent full animation/drive words or
  adjacent presentation fields, but those offsets are not generic across named
  NPC types and cannot be blindly copied as a common actor presentation block

This confirms the first world snapshot slice synchronizes lifecycle, transform,
heading, health, and the low animation-drive byte, but not the full visual
presentation state that the hub scene uses for Students and named NPCs.

`tools/verify_hub_student_seed_viability.py` is the focused seed viability
probe for this question. It launches the normal two local stage instances with
local multiplayer transport disabled, watches both Lua pipes, corrects a
private-region landing back to shared hub with `sd.debug.switch_region(0)`, and
then samples the hub Student population from both processes.

The current isolated run wrote `runtime/hub_student_seed_viability.json` and
returned:

- both clients were in `hub`
- host first sample: `10` Students, `26` replicated hub/world actors, RNG state
  `0x245C8850`
- client first sample: `6` Students, `21` replicated hub/world actors, RNG
  state `0x012C8B10`
- over six samples, host Student counts moved `10 -> 10` with count churn
  inside the window; client Student counts moved `6 -> 11`
- Student signatures diverged on position, drive state, path variant count, and
  wander target fields

This is the direct answer to the hub Student RNG question: the retail native
hub Student simulation is not lockstep-deterministic across local clients under
the current startup/runtime conditions.

`tools/verify_run_enemy_seed_viability.py` applies the same question to arena
wave enemies. It launches the normal two local stage instances with local
multiplayer transport disabled, starts `testrun` on both, dispatches
`sd.gameplay.start_waves()` on both clients through the parallel Lua runner,
and then samples the first wave enemy population.

The current isolated run wrote `runtime/run_enemy_seed_viability.json` and
returned:

- both clients were in `testrun`, wave `1`
- both clients created `10` live tracked enemies in the first sample
- host RNG state was `0x245C8850`; client RNG state was `0x012C8B10`
- the first enemy signatures diverged immediately by position/slot order
- the enemy count sequence later diverged: client `10 -> 11`, host `10 -> 12`

This is the run-world version of the same answer: even when the stock wave
count lines up, the native spawn positions and RNG stream do not provide a
usable lockstep contract.

### Native RNG use

Ghidra confirms the Student constructor at `0x00501B80` seeds per-instance
state through the game's RNG helpers:

- `FUN_00401120` initializes the additive RNG state
- `FUN_00401170` advances the integer RNG
- `FUN_00401310` produces scaled float values
- the active RNG state used by the recovered Student and hub paths is at
  `0x00818B08`

The Student constructor randomizes fields that affect presentation and behavior:
position-adjacent values, heading, speed, Student-specific floats at
`+0x174/+0x178`, the path variant count at `+0x1C0`, path/state blocks, wander
target fields at `+0x1B8/+0x1BC`, and a flag at `+0x23C`.

The hub spawn/update path around `0x0050CD10` creates `0x138A` actors, registers
them into the actor world, writes Student-specific fields, and increments a hub
Student count. Later in the same recovered path, code around `0x0050CED6`
reseeds the global RNG from a scene/global value.

The refreshed artifact for this pass is
`runtime/ghidra_hub_student_rng_seed_paths_20260528.txt`. It confirms that:

- `FUN_00401170` advances the additive RNG state and returns bounded integers
- `FUN_00401310` calls `FUN_00401170` and scales/signs float output
- `Student` construction writes `Student::vftable`, type `0x138A`, then calls
  `FUN_00401170` and `FUN_00401310` repeatedly while filling Student movement
  and path-state fields
- the hub path around `0x0050CD10` also calls those RNG helpers while handling
  `0x138A` actor creation/update work

That means a late seed is not enough to reconcile a scene after native actors
have already been created.

## Decision

Use host-authoritative world snapshots as the canonical synchronization model.

For P2P, the host is the authority. For a later dedicated server, the dedicated
process becomes the same authority behind the same packet/state contract. The
transport changes, but the world state ownership rule does not.

Clients may still animate locally for presentation, but non-player actor truth
comes from the authority:

- actor lifecycle: spawn, despawn, scene epoch
- transform: position, radius, heading, collision participation
- behavior state: AI/wander state, path selector/count, current target, owner
- animation state: drive state plus family-specific animation selectors
- combat state: HP, dead/alive state, damage/death events
- reward state: drop identity, pickup pending/accepted/rejected

## RNG Seed Role

A global RNG seed is useful, but it should not be the primary sync mechanism for
this game.

Good uses:

- deterministic initial layout generation before any native actor is created
- cosmetic variation where a mismatch is harmless or can be corrected by a
  later snapshot
- host/server-generated run nonce, wave lineup seed, reward table seed, or
  scripted encounter seed
- bandwidth reduction when the deterministic contract is narrow and proven

Bad use:

- relying on one shared global seed to keep all native hub/run actors
  synchronized forever
- trying to fix an already-diverged scene by reseeding after actors exist
- depending on stock native update order, actor enumeration order, or incidental
  RNG draw counts to match across host and clients

The reason is practical rather than philosophical: native code consumes RNG in
constructors, spawn paths, and update paths. Any host/client difference in load
timing, actor count, remote participant materialization, Lua/debug calls, future
run enemies, drops, or visual-only behavior can shift the global RNG stream and
poison every later draw.

If we want seed-driven prediction for a specific system, we should own that
system's state machine explicitly. In other words, use a seed for a bounded
host-authored generator, then snapshot/reconcile the resulting actors. Do not
ask the retail game's global RNG to be the network protocol.

## Implementation Shape

### Phase 1: observe and identify

- Keep `tools/multiplayer_lua_probe.py` as the reusable multi-client Lua probe
  runner.
- Keep `tools/probe_hub_world_sync.py` as the hub-world divergence probe.
- Promote stable actor family maps into documentation before writing fields.
- Treat family layouts separately; do not assume `0x138A` Student offsets apply
  to named hub NPCs, hostile run enemies, or drops.

### Phase 2: protocol and runtime model

- Add a world snapshot packet family beside the existing local participant
  `StatePacket`.
- Allow mixed packet sizes/kinds in the local UDP transport before sending new
  packet types.
- Add runtime storage for authoritative non-player actor snapshots keyed by:
  scene id, scene epoch, network actor id, native type id, and host ordinal or
  stable spawn id.
- Keep host-generated IDs connection-bound. Clients never get to declare
  canonical actor IDs.

### Phase 3: hub mirror slice

- Start with passive hub actor mirroring.
- Host sends snapshots for `0x138A` Students and named hub actors.
- Client applies snapshots only on the gameplay thread, after stock native tick.
- For the first safe slice, reconcile existing local native actors by type and
  host ordinal, then move to explicit spawn/despawn once the native factory and
  destruction contracts are fully isolated.
- For moving Students, either disable local client-side Student wandering or
  apply authoritative snapshots late enough that stock wandering cannot visibly
  fight the host.

### Phase 4: native lifecycle control

- Wrap the recovered create/register path only after the allocation,
  registration, grid binding, owner fields, and destroy/unregister path are
  proven together.
- Use authoritative spawn/despawn events for actors that exist on the host but
  not on a client.
- Keep reliable lifecycle separate from unreliable transform/state snapshots.

### Phase 5: run-world extension

- Reuse the same snapshot/lifecycle contract for enemies, drops, projectiles,
  wave state, and interactables.
- Add family-specific state serializers only after each actor family has a
  validated field map.
- Make HP, death, drops, pickups, and wave transitions host-owned even if a
  client predicts local cast animation or movement.

## Open RE Gaps

- Recovery beyond the now-proven `Student::Tick (0x0050A4E0)` retirement
  branch, including the remaining steering and presentation branches.
- Safe native create/register/destroy wrappers for arbitrary world actors.
- Exact actor-world enumeration semantics; the current live API samples one
  visible pointer per scanned bucket and is sufficient for divergence probes,
  but lifecycle replication should use a stronger source of truth.
- Family-specific writable fields for animation/state. Current probes identify
  candidate fields; they do not yet prove every field is safe to write.
- Whether named hub NPCs have hidden interaction state that must be serialized
  beyond transform and animation drive.

## Current Recommendation

Do not implement global-RNG lockstep as the main world sync model.

Implement host-authoritative world snapshots first, and use seeds as a helper
for content generation where we own the deterministic contract. This is less
fragile for P2P now and maps cleanly to a dedicated server later.

For hub Students specifically, the recommended shape is:

- Keep the host/server authoritative for the Student population.
- Use seeds only for host-owned generation decisions or cosmetic choices whose
  mismatch can be corrected.
- Do not depend on the retail global RNG stream, stock actor enumeration order,
  or stock Student update cadence to remain aligned between clients.
- The local UDP `WorldSnapshot` packet now carries a typed hub presentation
  payload. Factory-backed hub NPCs include the authoritative full animation
  drive word at `+0x160`; Students additionally include the proven randomized
  `+0x190..+0x1AF` color/state bytes and the render variant bytes at
  `+0x23C..+0x240`, including the book/no-book primary variant byte.
- Add named-hub-NPC animation serializers only after each named family has a
  validated field map. The live presentation probe shows those actors store
  different type-specific data at nearby offsets.
- For the named hub actor families whose `+0x160` animation drive word is a
  live phase counter (`0x138B`, `0x138C`, `0x138D`, `0x138F`), clients advance
  only that replicated word at the measured stock rate between host snapshots.
  Static named NPCs and Students keep exact host snapshot values.
- `tools/probe_named_hub_npc_fields.py` is the bounded per-family field probe
  for named hub NPC presentation work. It uses the recovered factory allocation
  sizes instead of the larger player/Student render window:
  - `0x1389` witch / `FUN_005018d0` / `0x1C0`
  - `0x138B` Annalist / `FUN_00502120` / `0x174`
  - `0x138C` PotionGuy / `FUN_005023a0` / `0x180`
  - `0x138D` ItemsGuy / `FUN_005024c0` / `0x174`
  - `0x138F` Tyrannia / `FUN_00502450` / `0x180`
  - `0x1390` Teacher / `FUN_00502570` / `0x178`
- The bounded live field pass confirms the current runtime serializer should
  not expand to `+0x220..+0x240` for named hub NPCs. Those offsets are outside
  the named actor allocations and belonged to the larger player/Student render
  layout. The only common, presently validated named-NPC animation serializer is
  the existing `+0x160` drive word plus phase extrapolation for
  `0x138B/0x138C/0x138D/0x138F`.
- If we want low-bandwidth Student prediction later, first build an explicit
  loader-owned Student state machine and seed that bounded machine, then
  reconcile with periodic authoritative snapshots.

## Implemented First Slice

The local UDP development transport now has a `WorldSnapshot` packet family.
In the first slices:

- the host samples shared-hub non-player scene actors from `TryListSceneActors`
- the host samples run-world tracked enemies from `TryListSceneActors` after
  combat waves are active
- the host sends up to 64 actor states per snapshot at a lower rate than player
  pose packets, including total-count and truncation metadata
- clients accept world snapshots only from the host/authority side
- snapshots are stored in a short runtime history rather than immediately
  mutating native actors
- gameplay samples the world history about 150 ms in the past and interpolates
  replicated actor position/heading before applying the host snapshot; hub
  presentation state is copied from the latest same-timeline host snapshot so
  animation phases are not delayed with transform interpolation, and known
  moving named hub NPC drive words are phase-extrapolated between snapshots
- Lua exposes the latest replicated snapshot through
  `sd.world.get_replicated_actors()`

The shared-hub lifecycle/reconciliation slice now does the following:

- the client matches local actors by native type and type-local ordinal
- matched actors receive authoritative position, heading, and animation-drive
  byte updates on the gameplay thread
- matched hub actors receive authoritative presentation updates after stock
  native tick from the latest host snapshot: hub animation-drive words for
  factory-backed hub NPCs and
  Student-specific book/color/variant bytes for `0x138A`
- moved actors are rebound into the native world grid
- missing known factory-backed hub NPC families are created through the stock
  `GameObjectFactory_Create(type_id)` plus generic
  `ActorWorld_Register(world, group=0, slot=-1)` path before reconciliation
  (`0x1389`, `0x138B`, `0x138C`, `0x138D`, `0x138F`, `0x1390`)
- extra client-local actors from those replicated factory-backed hub NPC
  families are removed through `ActorWorld_Unregister(world, actor,
  remove_from_container=1)` so the client-owned hub NPC set converges to the
  host snapshot without parking hidden duplicates
- Students remain owned by the stock transient courtyard lifecycle. When the
  client has more active `0x138A` actors than the authoritative snapshot, it
  requests retirement through the Student actor's native vtable path and
  decrements the owner's stock Student count at `+0x9308`, matching
  `Student::Tick`. Retired authority IDs are unbound for reuse, and actors with
  the native pending-remove flag are excluded from later binding passes.
  Multiplayer never factory-creates or directly unregisters a Student.
- client-created replicated hub NPCs are also unregistered before native scene
  switches, preventing loader-owned hub actors from leaking into hub-to-run
  teardown
- `sd.world.get_replicated_actors()` reports apply counts so live probes can
  distinguish "received snapshot" from "applied snapshot"

Run-world snapshots are emitted for tracked enemies. On clients, the first
authoritative host wave state rides the existing `StatePacket`, and a later
run snapshot can also queue the existing stock `start_waves` gameplay action as
a fallback. This gives the local run native enemy actors to bind to host-owned
lifecycle identity. After those actors exist, clients reconcile matched tracked
enemies through the host lifecycle spawn serial and write host position,
heading, animation-drive state, and live HP/max-HP.

The run lifecycle slice now treats the client's native wave spawner as a local
enemy pool. The host prefers a lifecycle spawn serial from the native
enemy-spawn hook and uses that serial as the authoritative run
`network_actor_id` in snapshots. If a live tracked run actor does not expose a
lifecycle serial, the host allocates a stable host-local supplemental ID for that
actor address instead of dropping it from the authoritative snapshot. Clients
keep a binding map from those host IDs to their local stock-spawned pool
actors, then apply host transform and HP state through that binding. Native
animation-drive and presentation fields are applied only when the bound local
actor has the same native object type as the authority actor; semantic
cross-variant bindings never copy class-specific animation memory. This
replaces type-local ordinal matching for run enemies, so host
enemy identity survives spawn/death order changes without losing serial-less
tracked actors.

`tools/probe_run_enemy_presentation_sync.py` is the focused run enemy
presentation/death probe for this boundary. The live pass against the current
wave enemy family (`0x03E9` / object type `1001`) showed:

- host/client matched run enemies had zero drive-byte mismatches
- the wider `+0x160` drive word stays zero on both sides, so the hub-style
  full drive-word serializer is not justified for this run enemy family
- visible run enemy walk timing still depends on the native walk-cycle floats
  at `+0x220/+0x224`, so the world snapshot carries those two fields behind
  `WorldActorPresentationFlagLocomotionFloats` for native type `1001` only;
  other enemy classes require their own live-validated presentation layout
- HP-zero death state converged through the existing HP/dead snapshot path
- the native death-handled byte stayed zero in this forced-HP probe, so there is
  no validated death-handled byte serializer yet

`tools/verify_player_health_death_sync.py` is the focused player vital/death
sync verifier. It runs a host/client pair in `testrun`, writes local native
progression HP/MP on each owner, and verifies the opposite process receives and
applies those values to the materialized remote player actor. The current
contract is:

- player `StatePacket` vitals are native-float HP/MP values, not rounded
  integer summaries
- remote player vitals are written before the actor tick classifies the remote
  participant as alive or dead
- HP-zero remote players enter the existing wizard corpse path, stop accepting
  owner transform playback, and clear hostile targeting through the same dead
  wizard cleanup path
- a later positive-HP packet revives the remote actor for replication purposes
  and normal transform playback resumes

When a complete host snapshot has more tracked enemies than the client, the
client zeroes the stock wave spawner's spawn-delay and long-delay countdowns so
the stock path can fill more local enemy actors. When the client has extra
local tracked enemies after authoritative matching, those extras are parked
outside the playable area and unbound from host identity. This is intentionally
different from the removed manual `sd.world.spawn_enemy` path: the client still
uses the stock wave-spawner placement, group-budget, config, and bookkeeping
path to create enemy actors.

Exact reliable pickups and wave transitions remain observed but are not yet
event-owned. Drops must be synced, but the safe boundary is host-owned lifecycle
plus host-confirmed pickup, not client-local pickup of mirrored stock actors.

## Run Loot Sync Boundary - 2026-05-29

`tools/probe_run_reward_sync.py` is the focused local UDP probe for the first
reward boundary. It launches a host/client run, disables Lua bots, starts host
waves, parks both players outside native pickup range, spawns a host gold
reward through `sd.world.spawn_reward`, and then captures
`sd.world.list_actors()`, `sd.world.get_replicated_actors()`, and
`sd.world.get_replicated_loot()` on both processes. The current local UDP slice
is:

- host gold reward actors are visible as native type `0x7DC`
- `+0x13C` carries the amount tier byte; amount `7` produced tier `2`
- `+0x140` carries the amount; the probe read back amount `7`
- `+0x148` is the active byte; the probe records it, but active/inactive is
  treated as observed stock state instead of the reward-sync pass/fail gate
- the host emits a run-only `LootSnapshot` with a stable host drop id, amount,
  amount tier, active byte, lifetime, position, actor slot, and world slot
- the client receives that metadata through `sd.world.get_replicated_loot()`
- the client still has zero local stock gold drops and zero world-snapshot gold
  actors, by design
- the client still had valid run enemy snapshots, so the gap is specific to
  reward pickup/lifecycle authority, not a broken world snapshot channel
- pickup authority is verified by
  `tools/verify_multiplayer_gold_pickup_authority.py`: accepted requests credit
  the owning participant ledger once, deactivate the host-native drop, leave the
  host local gold unchanged for remote pickup, and reject duplicate requests

The implementation target remains synced loot for all run drops, with each
player owning independent inventory, gold, spellbook, and statbook state. The
metadata snapshot is a bridge to that target, not the final pickup contract.
That means:

- the host owns drop spawn/despawn identity and emits reliable loot lifecycle
  events; snapshots can carry presentation for already-known drops, but they are
  not the authority for pickup credit
- clients may request a pickup, but the host resolves range/lineage sanity and
  sends confirm/deny
- credit applies to the owning participant's state, not to the stock global
  gold scalar or the local slot-0 inventory root
- gold uses `GoldActor_TickPickup (0x005E66B0)` because it still has actor,
  amount, and pickup context before `Gold_ChangeGlobal` loses participant
  identity
- item and potion pickup ownership should start from
  `ItemDropActor_TickPickup (0x005E6B50)` because it still has the drop carrier
  and held item pointer before `Inventory_InsertOrStackItem` receives the stock
  slot-0 inventory root
- orbs (`0x7DB`) and powerups (`0x7F6`) are reward actors rather than inventory
  roots; if they remain per-player rewards, they need their own pickup hooks and
  participant credit paths

This deliberately blocks visual-only drop mirroring as a final fix. Mirroring a
stock gold actor on the client before pickup ownership exists would allow a
client-local walk-over to mutate that client's local global gold and would not
prove the host-authoritative loot contract.

## Live Verification - 2026-07-23

`tools/verify_hub_student_population_sync.py` launches a uniquely named local
host/client pair on private UDP ports, records the exact two game PIDs, and
cleans up only those PIDs. It samples native `0x138A` actors, the owner
`+0x9308` courtyard count, pending-remove state, replicated bindings, and the
applied authoritative Student count.

The post-fix connected run wrote
`runtime/hub_student_population_sync.json` and passed:

- `10` total samples with `8` post-warmup samples
- client Student population converged in all `8` post-warmup samples
- maximum client surplus was `0`; the doubled-client regression would exceed
  the allowed transient surplus by a full local population
- temporary stale bindings converged from at most `3` unbound Students to `0`
- the native deferred-retirement total advanced to `2`, proving the surplus
  cleanup path executed
- the stock owner count equaled registered minus pending Students in every
  host and client sample
- no Student retirement failed

## Live Verification - 2026-05-29

Current verified gates:

- `python3 tools/verify_hub_student_seed_viability.py --json`
  - both isolated clients reached `hub`
  - stock Student lockstep was rejected
  - first sample diverged at `10` host Students versus `6` client Students
  - global RNG state diverged: host `0x245C8850`, client `0x012C8B10`
- `python3 tools/verify_run_enemy_seed_viability.py --json`
  - both isolated clients reached `testrun` and started wave `1`
  - stock run-enemy lockstep was rejected
  - first sample counts happened to match at `10` live tracked enemies on both
    clients, but enemy position signatures diverged immediately and the count
    sequence later diverged
  - global RNG state diverged: host `0x245C8850`, client `0x012C8B10`
- `python3 tools/verify_world_snapshot_reconciliation.py --launch-pair --json
  --attempts 20 --interval 0.25 --max-distance 8`
  - client received a non-truncated host `SharedHub` snapshot
  - latest persisted result is `runtime/world_snapshot_reconciliation.json`
  - verified missing known hub NPC families are filled on the client
  - current verifier rejects missing authoritative hub NPCs, failed hub NPC
    unregisters, and extra createable hub actors that remain after a complete
    host snapshot
- `python3 tools/probe_hub_npc_presentation_sync.py --json`
  - latest persisted result is `runtime/hub_npc_presentation_sync.json`
  - verified the hub snapshot is valid and non-truncated on the client
  - verified host-authored Student color/state blocks and primary
    book/no-book variants converge on the client
  - verified named hub NPC `+0x160` drive phases converge within the Lua
    cross-process sampling tolerance
- `python3 tools/probe_named_hub_npc_fields.py --samples 8 --interval 0.2`
  - latest persisted result is `runtime/named_hub_npc_field_probe.json`
  - confirmed the moving named drive-word families are `0x138B`, `0x138C`,
    `0x138D`, and `0x138F`
  - confirmed the other candidate generic render offsets previously inspected
    for named NPCs either fall outside the per-family allocation size or are
    type-specific/native-local state not safe for a generic serializer
- `python3 tools/verify_run_world_snapshot.py --require-complete-lifecycle`
  - latest persisted result is `runtime/run_world_snapshot_verification.json`
  - client received host `Run` enemy snapshots
  - client wave activation bootstrapped from host state
  - every accepted run snapshot actor was lifecycle-owned by a host spawn
    serial, and matched client actors were resolved through the binding table
  - the verifier reports `authoritative_actors_matched`,
    `lifecycle_owned_snapshot_actors`, `matched_binding_count`,
    `host_only_snapshot_actors`, `extra_client_tracked_enemies`,
    `parked_client_tracked_enemies`, and
    `extra_unparked_client_tracked_enemies` so pool catch-up and parking cannot
    masquerade as exact reliable lifecycle ownership
  - current strict run proof had `13` authoritative tracked enemies in the first
    accepted snapshot, all `13` were lifecycle-owned and bound to local actors,
    one client-only enemy was parked, `host_only_snapshot_actors=0`, and
    `extra_unparked_client_tracked_enemies=0`
  - after host-side HP mutation, the lifecycle proof matched all `14` expected
    live snapshot actors, had no client-only extras, and reported zero HP delta
- `python3 tools/probe_run_enemy_presentation_sync.py --samples 12 --interval
  0.2 --skip-death`
  - latest persisted result is `runtime/run_enemy_presentation_sync.json`
  - verified matched run enemy drive bytes converge with zero mismatches
  - verified the current run enemy drive word stays zero and should not be
    promoted to a generic serializer
  - verified host-authored run enemy walk-cycle floats are present and applied
    to matched client enemy actors within tolerance
  - death-state probing remains separate because direct HP-zero mutation does
    not reliably exercise the native death animation path
    over the network
- `python3 tools/probe_run_reward_sync.py --attempts 3`
  - latest persisted result is `runtime/run_reward_sync_probe.json`
  - verified host gold reward type `0x7DC`, amount `7`, tier `2`, and the
    active byte through live actor fields
  - verifies the client receives host-owned gold loot metadata through
    `sd.world.get_replicated_loot()` while still receiving zero local stock gold
    actors and zero world-snapshot gold actors
  - verified stock pickup still mutates host global gold by the drop amount,
    which is why synced loot needs host-confirmed pickup and participant-owned
    inventory/book state before visual drop mirroring is promoted
- `python3 tools/verify_local_multiplayer_sync.py`
  - hub and testrun participant materialization, movement/heading, nameplates,
    and player/player push still pass with the world snapshot path enabled
  - the verifier now retries scene polling across the temporary Lua pipe reset
    that can occur during hub-to-run scene switch
  - the verifier now places smoke-test actors on live traversable nav samples
    before checking exact remote convergence, avoiding false failures from raw
    non-walkable debug placement
- `python3 tests/re/run_static_re_tests.py`
  - `53/53` static tests pass for the snapshot protocol, runtime state, Lua
    exposure, docs, and regression gates
- `powershell.exe -NoProfile -ExecutionPolicy Bypass -File
  ./scripts/Build-All.ps1 -Configuration Release`
  - Release build passes

The verifiers intentionally prove the boundary of this slice too. Hub now fills
missing known NPC families through the stock factory/register path. Run-world
snapshots use hook-owned spawn serials for host identity, use the stock wave
spawner as a local actor pool, and park/unbind extras. Drops, pickups, and wave
transitions are the next lifecycle step; they are not something a global RNG
seed can solve after native spawn has already diverged.
