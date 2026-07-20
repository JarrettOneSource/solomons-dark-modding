# Networking Architecture

Solomon's Dark is a single-player retail ARPG. The networking design adds
4-player co-op as a DLL-level mod: trusted-host Steam sessions, not competitive
anti-cheat, not persistent-world infrastructure. Launch scope is 4 players, but
protocol and roster code should avoid hardcoding 4 where practical so 8-10
player private sessions can remain a later stretch target instead of a launch
promise.

## TL;DR

One player hosts a normal Solomon's Dark session and becomes the authoritative world. Every other player sends movement and gameplay intents to the host; the host broadcasts authoritative player / enemy / drop / run state at ~20 Hz plus reliable gameplay events (cast, damage, pickup, wave transition). Clients render their own input immediately for responsiveness and hard-snap when the host disagrees. Multiplayer mode disables the dev/debug mutation backdoors and refuses mismatched mod sets so peers cannot silently diverge. No rollback, no serious anti-cheat, no dedicated server, no persistent-world machinery in the first ship — just one trusted-host Steam session that keeps everyone in the same fight and the same run.

The implementation direction is client-predicted / authority-verified: clients
perform local movement and presentation immediately, then the host or dedicated
authority accepts, corrects, or rejects the claim. Clients never own canonical
HP, deaths, drops, XP, or wave state.

Protocol v64 distinguishes automatically observed native enemy-damage claims
from explicit damage requests. Native collision callbacks may report damage
without asserting target-transform authority because their local knockback can
precede the next world snapshot. The host still validates the participant, run,
damage bounds, caster distance, and enemy lifecycle, and it only accepts a
claimed target transform inside the normal drift guard. Explicit damage claims
remain position-strict.

## Implementation boundary

The current source has the multiplayer foundation, participant rail, and a
friends-only Steam development transport. See
[`steam-friend-playtest.md`](steam-friend-playtest.md) for the two-account
Spacewar playtest flow and the remaining external verification boundary.

- `multiplayer_runtime_state.h` defines the shared `ParticipantInfo`,
  `MultiplayerCharacterProfile`, `ParticipantSceneIntent`, and runtime snapshot
  model used by Lua bots and future remote participants.
- `multiplayer_service_loop.cpp` pumps Steam bootstrap/callback state every
  50 ms and mirrors readiness into runtime state. It also pumps the local UDP
  development transport when `SDMOD_MULTIPLAYER_TRANSPORT=local_udp`.
- `multiplayer_runtime_protocol.h` is a fixed-packet scaffold with
  `State`, `Launch`, `Cast`, `Progression`, `WorldSnapshot`, `LootSnapshot`,
  and `SpellEffectSnapshot` packets. The
  packet families below describe the target co-op protocol, not what the
  current header fully implements.
- `multiplayer_local_transport.cpp` and its cohesive
  `multiplayer_local_transport/*.inl` implementation files provide the first
  replication slice: two local
  processes exchange `StatePacket` movement/heading/vital snapshots over UDP
  and materialize the peer as `RemoteParticipant + Native`. Remote player
  packets are kept in a short transform history; gameplay samples that history
  about 120 ms in the past and applies interpolated position/heading on the
  actor tick. HP/MP travel as native-float progression values on the same
  packet, are written into the materialized remote actor's progression runtime
  before death detection, and HP-zero uses the existing wizard corpse path so
  dead remote players stop moving and ignore later owner transform packets until
  a positive HP packet arrives. The gameplay sync queue is only for
  materialization/rematerialization, not continuous pose updates. The local host
  also sends passive
  `WorldSnapshot` packets for non-player shared-hub scene actors and run-world
  tracked enemies. Clients keep a short world-snapshot history, sample it about
  150 ms in the past, and expose the latest replicated snapshot through Lua for
  verification. Shared-hub actors are reconciled to the buffered host
  transform/heading snapshot on the gameplay thread; presentation state is
  overlaid from the latest same-timeline host snapshot so animation phase does
  not inherit the transform interpolation delay. Known phase-advancing named
  hub NPC families (`0x138B`, `0x138C`, `0x138D`, `0x138F`) advance the
  replicated drive word by the measured native phase rate while waiting for the
  next snapshot.
  Named hub NPC serializers use recovered per-family allocation sizes for
  bounds; the larger player/Student render window is not reused for those
  classes. Hub snapshots also carry a typed presentation payload: the host's
  full hub animation-drive word
  for factory-backed hub NPCs, plus Student-specific book/variant bytes and
  randomized color/state bytes. Missing known hub
  NPC families (`0x1389`, `0x138A`, `0x138B`, `0x138C`, `0x138D`, `0x138F`,
  `0x1390`) are created through the stock factory plus generic world-register
  path before being reconciled. Run-world enemy
  snapshots now bootstrap client wave activation through the existing gameplay
  action queue and reconcile stock-created tracked enemies to the host
  transform/heading/drive snapshot, plus live HP/max-HP for matched tracked
  enemies. The run enemy presentation probe confirms the current wave enemy
  family does not need the hub-style full drive-word serializer: the wider
  drive word stays zero and the existing drive byte converges. Run enemy
  snapshots now also carry the validated walk-cycle floats at
  `+0x220/+0x224` so matched client enemy actors use the host's
  walk-cycle phase instead of advancing a local-only phase. The native
  death-handled byte remains a separate unpromoted field because the current
  direct HP-zero probe does not prove it should be copied. Run enemy
  snapshots prefer a host lifecycle spawn serial captured by
  the native enemy-spawn hook and allocate a stable host-local supplemental ID for
  tracked run actors that do not expose that serial; clients bind their local
  stock-spawned pool actors to those host IDs before applying reconciliation.
  If a client has fewer stock wave enemies than the host
  snapshot, it accelerates its native wave-spawner timers to fill the local
  enemy pool through the stock path. Extra client-side hub NPCs from replicated
  factory-backed families are unregistered from the client world so the hub NPC
  set converges to the host snapshot. During native scene switch, replicated hub
  NPC bindings are abandoned, while remote participant wizard bindings stay
  tracked through native unregister so loader-owned clones can be identified,
  reset immediately after native unregister, and suppressed only for the known
  unsafe `remove_from_container=1` scene-churn path; stale participant bindings
  are abandoned after the switch returns.
  Host-authoritative
  run entry is driven by the host's `StatePacket` scene intent. Protocol v38
  carries an explicit `authority_participant_id`; the host stamps that identity
  onto relayed client state, and clients only accept scene/pause authority when
  the packet's participant and authority identities match. A second client's
  relayed `in_run` or pause fields therefore cannot drive another client's
  transition or overwrite the shared level-up wait state. Connected
  clients reject direct `sd.hub.start_testrun` calls and block direct arena
  `switch_region` attempts, then queue their local hub-to-run transition when
  the configured host reports `in_run`. The host stamps the run with a
  host-authored run generation seed, sends it as `run_nonce`, and both host and
  client call the stock native RNG initializer (`0x00401120`) on the RNG state
  referenced by the native global (`0x00818B08`) inside the
  `GameplaySwitchRegion` hook before stock arena generation runs. The seed
  aligns the static-generation shape set, but host snapshots still explicitly
  carry the recovered run-static prop families (`0x1391`, `0x1392`) so trees,
  tombstones, and their movement blockers converge to the host instead of
  depending on global-RNG lockstep.
  The stock Boneyard generator can produce an empty local candidate list for
  some seeds. Its original count check at `0x0063D78F` then synthesizes a null
  candidate and dereferences `candidate + 0x1C` at `0x0063D7C3`. The loader
  replaces that exact eight-byte count branch only when the supported stock
  bytes match; an empty list now jumps to the generator's existing cleanup and
  outer-loop continuation at `0x0063DA59`. The patch is restored on loader
  shutdown.
  `tools/verify_run_static_layout_sync.py` compares the resulting movement
  circle/shape/static-actor digests across the two local clients. The host also
  sends an empty Run
  `WorldSnapshot` before wave enemies exist so clients clear any stale hub
  world snapshot immediately; clients use that authority marker plus the
  host's current transform to apply a one-shot run-entry formation placement
  beside the host before normal movement replication resumes. Extra run enemies
  are still parked because the run enemy pool is stock-spawner owned. Run loot
  drops are not global-RNG lockstep state: they are host-owned lifecycle
  entities with reliable spawn/despawn, pickup-request, and pickup-confirm/deny
  events. The local UDP transport now sends a run-only `LootSnapshot`
  slice for host gold drops (`0x7DC`), health/mana orb drops (`0x7DB`), and
  item/potion carrier drops (`0x7DD`) with a stable host drop id, reward
  metadata, lifetime/radius/position, and held-item type/slot/stack metadata
  where applicable. Connected clients materialize host-authored gold and
  health/mana orb presentation actors from that snapshot; those client actors
  are pickup-suppressed and exist only as mirrors of host-owned lifecycle
  objects. The client view is exposed through
  `sd.world.get_replicated_loot()`, including the local presentation actor
  address when a drop is materialized. Protocol v28 carries loot presentation
  state for host-authored gold plus health/mana orb motion/progress. Protocol
  v27 introduced `LootPickupRequest` and `LootPickupResult`: a client can
  call `sd.world.request_loot_pickup(id)`, the host checks run nonce, distance,
  duplicate pickup state, and drop identity, then confirms or denies the
  credit. Gold availability is derived from amount plus lifetime, not the
  observed `+0x148` byte. Accepted gold pickups update only the requesting
  participant's owned gold ledger, increment `gold_revision`, zero the host gold
  actor amount, and suppress that drop id from later loot snapshots. Accepted
  health/mana orb pickups apply the host-authored resource result to the
  requesting participant's runtime vitals and to that client's local HP/MP
  presentation. Accepted item/potion carrier pickups clear the host carrier's
  held-item pointer and credit the requesting participant's replicated
  inventory state by exact recipe/type identity, color when applicable, slot,
  and stack count. The owning client materializes the held object through the
  stock item-recipe clone and `Inventory_InsertOrStackItem` paths, verifies the
  exact native inventory delta, and deduplicates the credit by run/drop
  identity. This is proven live for potion stacking and a recipe-backed hat.
  The loader now exposes `sd.player.get_inventory_state()` as a read-only
  audit surface for the stock scene-owned inventory root and visual sink helper
  items, and `tools/verify_multiplayer_inventory_audit.py` proves both local
  multiplayer clients can read their own native starter inventory shape.
  Protocol v30 introduced bounded full participant-owned inventory item rows,
  progression-book/statbook/skillbook/spellbook rows, and current ability loadout
  in `StatePacket`, so peers can inspect each other's starter potion rows,
  active/visible native book entries, and primary/secondary loadout. Protocol
  v60 carries exact hat, robe, staff, wand, three-ring-slot, and amulet equipment
  identity: recipe UIDs and wearable colors are owner-authored, visible lanes
  are applied to native remote participants and periodically self-corrected,
  and nonvisual ring/amulet identity remains inspectable on every peer. The
  owning client can equip an exact recipe-backed inventory item through
  `sd.player.equip_inventory_item`; the stock inventory, exact selected holder,
  prior-item return, dirty flag, and progression refresh paths remain
  authoritative. Observer processes still do not own a second native inventory
  root. This is intentional: the stock inventory, equip, storage, and merchant
  paths consume the one process-local scene inventory root without a participant
  parameter. Remote inventory therefore remains authoritative replicated rows,
  while remote equipment that affects presentation is materialized on the
  native remote actor. Protocol v60 also gives every gameplay process a fresh
  session nonce;
  a same-identity reconnect resets the old participant's packet-stream epochs
  before its new state is accepted, while packets from retired nonces are
  ignored. Host-authorized powerup pickup is verified for Random Skill,
  Damage x4, and Bonus Skill in both ownership directions. Luthacus storage,
  Fomentius purchases, and Hagatha purchases are owner-local stock UI paths whose
  resulting inventory, gold, equipment, stat, and status state replicates to
  observers. Non-shop quest/reward insertion and durable cross-session
  persistence remain incomplete.
  Protocol v30 also adds host-authored `LevelUpOffer`, `LevelUpChoice`, and
  `LevelUpChoiceResult` packets. The host advances shared XP/level, rolls each
  participant's native skill-picker options against that participant's
  materialized progression/book state, sends only that participant's offer, and
  applies a returned choice only if it matches the issued offer. Connected
  non-host clients suppress their local native level-up picker/event and expose
  the active offer through `sd.runtime.get_multiplayer_state()`.
  Protocol v54 groups every connected participant's offer into one revisioned
  host barrier. All peers pause together, resolved players see
  `Waiting on N players`, and no peer resumes until every participant has an
  accepted choice. The host auto-picks the first valid rolled option for any
  unresolved participant after 60 seconds, then repeats the accepted results
  and final resume state so packet loss cannot strand one client in the picker.
  Protocol v36 adds owner-authored transient spell-effect snapshots. Native
  Ether, Fireball, Water, and Ember objects still spawn through stock cast
  playback on every peer; the new lane binds those observer objects by owner
  actor slot and native type, then reconciles transform and motion. Ember
  snapshots additionally carry the recovered vertical motion, damage/config,
  lifetime, animation, variant/frame, and terminal status fields. Only the
  presentation/runtime state is copied: the existing nonlocal projectile-group
  gates continue to suppress observer-authored damage and claims. The current
  Lua audit surface is `sd.world.get_replicated_spell_effects()`.
  Protocol v37 adds owner-authored Air-chain snapshots. Each held Lightning
  frame carries the ordered network enemy IDs and source/target endpoints
  accepted by the owner's native Chaining loop. Observers substitute those
  local enemy objects at the stock nearest-target seam. The observer also
  applies the owner endpoint to the verified `SpellCast_018` caller-local
  source vector before the stock arc builder consumes it; the hook validates
  the return address and the original two floats before writing. Native arc
  creation therefore keeps its normal rendering path while target identity,
  both endpoints, and terminal cast state are directly auditable through
  `sd.world.get_replicated_air_chains()`.
  `StatePacket` carries each
  participant's current owned gold and progression revision counters for live
  verification of the participant ledger; stale state packets are
  revision-guarded so they cannot overwrite a newer host-authorized pickup
  result. The same fixed packet protocol now runs over authenticated Steam lobby
  peers through Steam Networking Messages; loopback UDP remains the explicit
  deterministic test backend.
- `docs/multiplayer-participant-model.md` is the implementation-facing model
  for profiles, scene intent, Lua bots, and future remote players.
- `docs/networking/world-sync-authority-plan.md` records the current hub NPC
  live/RE evidence and the decision to use host-authoritative world snapshots
  instead of global-RNG lockstep for non-player actors.

## Committed decisions

| Area | Decision |
|---|---|
| Authority | Host-authoritative-lite. Clients render local echo; hard-snap on host disagreement. |
| Transport | Steam friends-only lobbies + `ISteamNetworkingMessages` over the Steam Networking Sockets/SDR stack. |
| Local dev transport | UDP loopback can be enabled with `SDMOD_MULTIPLAYER_TRANSPORT=local_udp` so two local stage instances can test connection and pose sync without two Steam accounts. |
| Off-Steam transport | **Not in v1.** GameNetworkingSockets / ENet / direct-IP deferred. |
| Dedicated server | **Not in v1.** P2P-host only for first ship. |
| Identity | Connection-bound. Host ignores client-declared player / actor IDs. |
| Mod compatibility | **Exact** protocol version + mod-manifest hash. Mismatch refuses connect. |
| Anti-cheat | None in the serious sense. Baseline hygiene only (see below). |
| Loot | Synced host-owned run drops. Gold, health/mana orbs, item/potion carriers, and powerups have host-authorized request/result ownership. Accepted potions and exact recipe-backed items enter the owning client's stock native inventory and converge back into participant-owned rows. Hat/robe/staff/wand identity and wearable colors reconcile onto native remote actors; all three ring slots and the amulet are replicated as exact owner-authored equipment state. Stock storage and merchant actions remain owner-local and publish their resulting state. Observer processes intentionally retain replicated inventory rows instead of an unused second native root. |

## Tick rates

| Channel | Rate |
|---|---|
| Client → host input | 30 Hz |
| Player snapshots | 20 Hz |
| Enemy snapshots (baseline) | 20 Hz |
| Enemy snapshots (bosses / hot states) | 30 Hz |
| Reliable events | Immediate |

Sampling happens on the stock game thread after native updates — no extra sim thread.

## Player count / scaling

- v1 is designed, tested, and balanced around **4-player co-op**.
- Avoid hardcoding `4` into protocol, roster, or actor-plumbing decisions where the cost is low.
- `8-10` players is a plausible later private-session stretch target, but **not** a launch commitment.
- Above 4 players, the likely bottlenecks are host CPU and enemy / effect / drop replication fanout, plus combat readability, more than raw player-input traffic.

## Packet families

**Reliable channel**
- `hello / manifest` — protocol version + exact mod-manifest hash
- `join / bootstrap` — participant upsert + chunked full-state for fresh/reconnecting clients
- `spawn / despawn` — entity lifecycle
- `gameplay-event` — casts, damage, death, pickups, wave/boss transitions, run start/end
- `loot-drop` — host-owned drop spawn/despawn state for gold, item, potion,
  orb, and powerup carriers as each native pickup seam is proven
- `pickup-request / pickup-result` — client intent, host sanity check, and
  per-participant inventory/spellbook/statbook credit
- `level-up-offer / level-up-choice / level-up-result` — host-authored shared
  level-up options, client-selected offer item, and host sanity-check/apply
  result
- `progression-delta` — XP, gold, level, spellbook, statbook, and live loadout
  mutation
- `disconnect / reconnect`

**Unreliable channel**
- `input` — per-client input w/ sequence number
- `snapshot-delta` — variable-size entity state burst, carrying `last_processed_input_seq` per receiving client
- `state` — current fixed-packet development snapshot for local UDP movement /
  heading tests. Carries network `participant_id`, profile/loadout summary,
  vitals, position, and heading.

**Explicitly not in v1:** `clock-sync`, `save-provenance`, input-replay-for-rollback.

## Authority table

| Entity | Authority | Sync | Rate |
|---|---|---|---|
| Local player | Self (input) → host (sim) → broadcast | Input to host w/ seq; host pose broadcast; local echo; hard-snap on correction | Input 30 Hz · pose 20 Hz |
| Remote player | Their client's input → host → snapshot | Snapshot interpolation | 20 Hz |
| Enemies | Host | Snapshot burst (pos + vel + hp + state) | 20 Hz · 30 Hz for bosses / hot states |
| Drops | Host | Reliable spawn; reliable pickup-request + confirm/deny | Event-driven |
| Casts | Caster optimistic (plays anim); host broadcasts + confirms hit | Reliable event | Event-driven |

## Phase order

### Phase 0 — Gating (non-negotiable before *any* network traffic ships)

- Multiplayer runtime profile that disables:
  - Named-pipe Lua exec server (`lua_exec_pipe`)
  - `sd.debug` mutators (write_*, write_field_*, copy_bytes, call_*, nav-grid copy)
  - Debug-UI mutation paths (`activate_action`, `activate_element`, `perform`, `direct_write`)
  - `sd.hub.start_testrun`, `sd.gameplay.start_waves`, `sd.world.spawn_*`, `sd.input.*`
  - Native-DLL mod host arbitrary loading → manifest allowlist
  - On non-host clients: `sd.bots.*` and all gameplay-mutating Lua surface except host-intent RPCs
- Generic `ReadParticipantSnapshot` + controller-source interface keyed by `participant_id`
- `RemoteParticipant + Native` supported at actor creation (pre-materialization swap only; no hot-swap)
- Seed `run_nonce` for real — stop treating the schema field as scenery
- Packet sanitation: size / version / family + stale-sequence rejection

### Phase 1 — P2P host MVP

- Local UDP two-process development harness:
  `scripts/Launch-LocalMultiplayerPair.ps1` launches `local-mp-host` and
  `local-mp-client` with separate runtime/stage roots and ports `47770/47771`.
  The client launch uses `--temporary-profile`, which redirects APPDATA,
  LOCALAPPDATA, and the staged `savegames` compatibility path into a fresh
  runtime-local temporary profile so joining a multiplayer host cannot mutate
  the user's single-player save files.
  This validates participant connection plus movement/heading materialization
  without Steam identity constraints. The harness assigns
  `SDMOD_MULTIPLAYER_PLAYER_NAME` and unique `SDMOD_LUA_EXEC_PIPE_NAME` values
  so both copies can be probed without colliding on the default Lua exec pipe.
  `tools/verify_local_multiplayer_sync.py` is the live smoke test for hub/run
  participant visibility, host-authoritative run entry, connected-client
  run-start blocking, idle movement/heading convergence, player/player
  native-remote overlap stability without cross-instance push feedback, and
  remote nameplate resolution.
	  `tools/verify_multiplayer_progression_ledger_sync.py` verifies bidirectional
	  local UDP replication of participant-owned gold and gold revision state through
	  `StatePacket`.
	  `tools/verify_multiplayer_gold_pickup_authority.py` verifies the first
	  pickup authority slice: a client requests host-owned gold, the host credits
	  the requesting participant once, host global gold remains unchanged, the host
	  drop is consumed, client metadata despawns, and duplicate pickup returns
	  `AlreadyGone`.
	  `tools/verify_multiplayer_orb_pickup_authority.py` verifies host-owned
	  health and mana orbs: the client requests the replicated drop id, the host
	  accepts once, the host participant vitals and client local vitals converge to
	  the authority result, metadata despawns, and duplicate pickup returns
	  `AlreadyGone`.
	  `tools/verify_player_health_death_sync.py` is the focused live test for
	  host-to-client and client-to-host player HP/MP replication, HP-zero death
  presentation, corpse inertness, and revive/resumed transform playback in a
  shared run.
- Steam friends-only lobby → authenticated Steam Networking Messages handoff
- Protocol/build/capability `hello` + acknowledgement handshake
- Input stream + player pose snapshots at target rates
- Enemy snapshot burst (20/30 Hz)
- Cast / damage / death events
- Wave + run lifecycle sync
- Loot-drop spawn/despawn + gold/orb pickup-request/confirm/deny
- Progression-delta (XP / gold revision / level / spellbook / statbook / live
  loadout)

### Phase 2 — Hardening

- Stateful reconnect
- Admin tooling (kick / ban / adminlist)
- Latency simulation + stress test
- Soft reconciliation upgrade for hard-snap (interpolate to host pos over 100–200ms) if playtests show chatter
- Steam and local UDP share the same snapshot interpolation and gameplay
  authority boundary, so transport selection does not fork simulation rules.

### Phase 3+ — Post-ship

- Dedicated server: `SteamGameServer_Init`, headless D3D9 stub, `--server` loader flag, slot-0 decoupling, server browser + direct-IP
- Off-Steam transport: standalone GameNetworkingSockets or ENet
- Durable participant inventory/book persistence after the per-run ownership
  model is proven

## Latency characteristics (what input lag looks like)

For a non-host client on a typical Steam SDR connection (50–100ms RTT):

| Action | Client experience |
|---|---|
| Movement | **Zero lag** — local echo applies input the frame it's pressed. |
| Cast spell (animation) | **Zero lag** — animation plays optimistically on key-down. |
| See damage numbers / hit resolve | **RTT delay** (~50–100ms) — host resolves, broadcasts. |
| Pick up loot | **RTT delay** — pickup-request -> host confirm; the host credits the owning participant's inventory, gold, spellbook, or statbook state. |
| See enemies | **100–150ms in the past** — snapshot interpolation buffer. |
| Hard-snap / rubber-band | **Rare** — collision edge cases, desync after host correction. |

Host feels none of this; their sim is local.

The intended feel is native local movement with delayed authoritative
confirmation for hits, pickups, and other host-owned outcomes. Under normal
latency the correction path should be rare; if hard-snaps become visibly
disruptive in playtest, Phase 2 adds soft reconciliation by interpolating toward
host position over a short window.

## What we are explicitly NOT doing in v1

- Client-side prediction + reconciliation (rollback)
- Clock-sync packet family
- Client-side hit validation / lag compensation
- Save-file merging / migration between sessions
- Dedicated server
- Off-Steam transport
- Injected anti-cheat (EAC / BattleEye / VAC)
- Persistent-world machinery
- Hot-swap of participant controller on live actor

## Known gaps we accept in v1

- Host can cheat in their own session (trusted-peer model)
- Cross-region divergence (host sims one region; multi-region is later work)
- Durable inventory/book persistence beyond one run (Phase 3+)
- Nested sack browsing and ownership have not had a focused multiplayer pass.
- The remaining Hagatha charm/curse catalog needs a behavior matrix beyond the
  verified Life Charm purchase.
- Non-shop quest/reward insertion and durable participant inventory/book
  persistence remain incomplete.

## Run-identity object (replaces "save-provenance" from earlier drafts)

Minimal fields sent at join:

- `run_nonce` (seeded for real, not placeholder)
- host / session id
- region / mission seed or lineup
- participant roster
- per-participant character / loadout snapshot
- mod-manifest hash
- protocol version
- started-at tick

No backup / restore / migration / save-transfer in v1.
