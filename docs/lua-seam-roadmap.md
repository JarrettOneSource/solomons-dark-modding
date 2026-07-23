# Lua Seam Roadmap — Growing a Lua-Only Modding Ecosystem

Status: numbered seam roadmap implemented (2026-07-23). Section 6 retains
research and distribution follow-ups that are outside the executable seam list.

Goal: Solomon Dark should live and thrive on Lua mods alone, with this framework as the
bootstrap. Mod authors should never need native code for gameplay, content, UI, or
multiplayer — and **mods must be multiplayer-native by default: the same script works in a
solo run and in a Steam session with zero netcode or special-casing by the mod author.**

This doc records: the current `sd.*` surface, the multiplayer-native design principle, a
tiered roadmap of new seams (each annotated with its multiplayer behavior), flagship mod
concepts with a current support assessment, and the completed build order.

---

## 1. Design principle: multiplayer-native by default

The framework already has the hard parts: a participant model
(`multiplayer-participant-model.md`), authority-stamped replication snapshots for actors,
loot, spell effects, and air chains (`get_replicated_*`), request/result arbitration
(`request_loot_pickup` with `request_sequence` → result), scene epochs, and bots that are
full participants. The principle below turns those internals into a contract so mod authors
never see them.

### API taxonomy — every `sd.*` function declares one class

| Class | Examples | Multiplayer behavior |
|---|---|---|
| **Simulation** (mutates shared game state) | `sd.enemies.spawn`, `sd.items.grant`, `sd.time.set_scale`, `sd.world.spawn_reward`, filter outcomes | Executes where the affected entity is simulated (authority for run entities; owning peer for that peer's wizard, per the participant ownership rules). Owner-routed seams transparently request the owner; authority command seams such as item grants reject client authorship and route the accepted command to the target owner. Results replicate through the existing snapshot channels. |
| **Presentation** (local output) | `sd.hud.*`, `sd.audio.*`, `sd.camera.*`, `sd.ui` authoring | Always local, never replicated. Inherently MP-safe. |
| **Meta** (mod runtime) | `sd.storage.*`, `sd.timer.*`, `sd.bus.*`, `sd.net.*`, `sd.runtime.*` | Local operations with explicit sync points; `sd.net` is the low-level authenticated participant transport escape hatch. |

### Rules that make "no shenanigans" true

1. **Filters run on the simulation owner only; notify events fire on every peer.**
   A `damage.dealing` filter executes once, where that entity is simulated; the modified
   outcome replicates as state. A `sd.on("enemy.death", ...)` handler fires on all peers —
   on the authority from live simulation, on clients from replication apply — with the same
   payload. A kill-counter mod is identical code as host or client.
2. **Replicated mod state: `sd.state`.** An authority-writable KV store bundled into the
   existing snapshot/apply stream. `sd.state.set("director_intensity", 0.8)` on the
   authority; every peer (and every late joiner, via join sync) reads the same value. No
   transport code in mods, ever.
3. **Replicated custom events: `sd.events.broadcast(name, payload)`.** Ordered with the
   snapshot stream, delivered to all peers. This is how a boss mod tells every client to
   play an enrage stinger (each client's *local* `sd.audio` reacts to a *replicated* event).
4. **Deterministic content IDs.** Registered content (spells, enemies, items) gets its
   network ID from `hash(mod_id, content_key)` — never author-chosen numerics — so
   replicated references resolve identically on every peer.
5. **Exact mod parity handshake.** Session join compares a fingerprint over the game,
   loader, binary layout, runtime flags, and every enabled mod's id, version, and complete
   directory hash. Any mismatch is rejected. Presentation-only divergence is not accepted:
   a self-declared class cannot prove that a script or overlay is simulation-inert, so the
   framework keeps one enforceable policy and authors do nothing.
6. **Every new seam ships with a multiplayer acceptance test.** The local transport
   (`multiplayer_local_transport`) enables two-instance testing on one machine; the kill
   stress harness is the template.

The single concept authors must learn: *decide in simulation hooks, display with
presentation calls.* The framework enforces the rest (presentation calls can't mutate
shared state; simulation calls auto-route to the owner).

---

## 2. Current state inventory (what exists today)

### `sd.*` modules

- **`sd.runtime`** — `get_mod`, `get_multiplayer_state`, `get_frame_state`,
  `choose_level_up_option`, `debug_publish_level_up_offer`, `has_capability`,
  `get_capabilities`, `get_environment_variable`, `get_mod_text_file`.
- **`sd.state`** — per-mod `get/set/delete/clear/snapshot`, global revision reads, and
  authority discovery. Host mutations replicate in order and late joiners receive a
  checkpoint.
- **`sd.storage`** — per-mod local profile `get/set/delete/clear/snapshot` with bounded,
  transactional persistence under the launcher's isolated mod data root.
- **`sd.timer`** — bounded per-mod `after/every/sequence/cancel/clear` scheduling on the
  monotonic runtime tick; callbacks and handles are released when the mod unloads.
- **`sd.bus`** — bounded synchronous local publish/subscribe with manifest-declared
  provider contracts and provider-first Lua load ordering.
- **`sd.net`** — bounded binary-safe unicast/broadcast between participants through an
  authenticated host relay, with per-mod subscriptions and game-thread delivery.
- **`sd.time`** — authority-owned fixed-point slow motion, pause, and frame-step over a
  coherent actor-world/player/wave gate, replicated to every participant.
- **`sd.rng`** — authority-owned exact seed selection for the next native arena-generation
  pass, carried to peers through the run nonce.
- **`sd.nav`** — bounded address-free native grid snapshots and player-sized path-segment
  tests.
- **`sd.scene`** — semantic address-free scene state plus authority-owned region switches;
  authenticated host intent moves connected clients and Lua-controlled participants.
- **`sd.waves`** — effective schedule plus authority-replicated wave state, composition,
  and spawn/death accounting.
- **`sd.spells`** — deterministic registration, local input selection, owner-routed
  casts and callbacks, and replicated generic effect state.
- **`sd.items`** — deterministic recipe-backed registration and authority-routed grants
  resolved against each recipient's peer-local native catalog.
- **`sd.enemies`** — deterministic semantic stock-archetype registration and
  authority-owned exact spawning with per-actor stats and loot policy.
- **`sd.ai`** — registered-enemy authority brains with bounded per-spawn
  blackboards, semantic participant targets, and collision-preserving point goals.
- **`sd.draw` / `sd.hud`** — bounded presentation-local text, primitives, stock
  sprites, viewport reads, and world projection on the D3D9 backbuffer.
- **`sd.audio`** — mod-root samples and streams through the game-owned BASS device,
  with opaque local handles, volume, state, stop, and deterministic cleanup.
- **`sd.camera`** — bounded local camera state, world-focus ownership, cleanup, and
  the stock shake path.
- **`sd.sprites`** — bounded mod-root PNG/bundle atlas registration consumed by
  `sd.draw`, with revisioned replacement and lifecycle cleanup.
- **`sd.events`** — `on` plus authority-only `broadcast` for mod-defined ordered events.
  Built-in notify events are `runtime.tick`, `run.started`, `run.ended`, `wave.started`,
  `wave.completed`, `enemy.death`, `enemy.spawned`, `spell.cast`, `gold.changed`,
  `drop.spawned`, `level.up`.
- **`sd.bots`** — full ally-bot runtime: `create/destroy/clear/update`, `move_to/stop/
  face/face_target`, `cast`, `get_state`, `get_participant_state`, `get_participants`,
  `get_nameplate`, `get_skill_choices/choose_skill`, primary-attack helpers. Per-entity
  stat pools; bots are participants.
- **`sd.ui`** — semantic read/automation plus bounded native-authored surfaces, panels,
  labels, buttons, local presentation callbacks, and authority-routed simulation actions.
- **`sd.input`** — key/scancode/binding press, normalized clicks, mouse holds, movement
  holds, `queue_local_spell_cast`, `queue_local_enemy_damage_claim`, manual target pin.
- **`sd.gameplay`** — `start_waves`, `enable_combat_prelude`, manual enemy spawner
  (`spawn_manual_run_enemy`, spawner state/test mode), `get_combat_state`,
  `get_selection_debug_state`, `set_run_enemy_health`.
- **`sd.player`** — `get_state` (hp/mp/xp/level/gold/position/status flags/intents),
  `get_inventory_state`, `equip_inventory_item`, `get_progression_book_state`.
- **`sd.world`** — `get_state`, `get_scene`, `list_actors`, `get_replicated_actors`,
  `get_replicated_loot`, `get_replicated_spell_effects`, `get_replicated_air_chains`,
  `get_run_enemy_by_network_id`, `request_loot_pickup`, `rebind_actor`, `spawn_reward`,
  `trigger_enemy_death`.
- **`sd.hub`** — `get_surface_state`, `start_testrun`, `open_service`.
- **`sd.debug`** — RE toolkit: function traces, write watches, struct/vtable dumps,
  pointer-chain snapshots/diffs, typed memory read/write, `call_thiscall_*`/`call_cdecl_*`
  bridges, nav grid, actor modifiers, `capture_backbuffer`, layout/anchor resolution.

### Supporting infrastructure

- ~150 resolved native seams in `gameplay_seams.h` (actors, movement, collision,
  pathfinding, spell builder chain, damage context globals, drops/orbs/powerups,
  inventory insert, item recipes, arena/waves, region switch, hub services, RNG, timing
  scale, glyph/text draw, keybinding globals, …).
- D3D9 EndScene hook + debug overlay + backbuffer capture.
- Named-pipe Lua exec server (external processes can run code in the live runtime).
- Generated LuaLS/EmmyLua API inventory, opt-in offline source hot reload, and a bounded
  in-game exec console over the same gameplay-safe queue.
- Full data-overlay surface: `data/wizardskills/*.cfg` (60+ skills), `data/wave.txt`,
  `data/items.cfg`, `data/levels/*.boneyard`, `data/dialogue/*`, `magenames.txt`,
  `images/*.bundle` sprite atlases (format reversed; extractor in `tools/`), sounds/music.
- Sample mods prove overlay + Lua patterns: `skill_shock_nova` (new data-driven skill),
  `wave_fast_start`, `story_custom_intro`, `item_gold_focus`, `lua_bots`,
  `lua_ui_sandbox_lab`, `lua_authoring_lab`, `lua_dark_cloud_sort_bootstrap`.
- Lua states begin with the standard libraries, then remove `debug`, `dofile`, `io`,
  `loadfile`, `os`, `package`, and `require`. Scoped persistence belongs in `sd.storage`.

### Roadmap closure

No executable Lua seam gaps remain in this document. Scripted spells have deterministic
owner-routed behavior, replicated semantic effects, direct primary/belt selection, and a
native-authored `sd.ui` picker example. Authored UI, local draw/audio/camera/sprites,
cross-mod contracts, and the author workflow are implemented. Multiplayer uses strict
exact parity for every enabled mod; there is no unverified presentation-only exception.
Every Lua pair/trio verifier explicitly disables window tiling, preserves pre-existing
game processes, refuses incomplete launch ledgers before contacting Lua pipes, and tears
down only the exact process IDs returned by its own launch.

The remaining partial flagship concepts need product-specific work outside this seam list,
such as Website leaderboard submission, level-authoring tools, specialized native effect
primitives, NPC quest control, or replay input capture. Section 6 records longer-horizon
runtime and distribution research.

### Resolved sharp edges

- The removed hand-built `Enemy_Create` path had an invalid call shape. Registered
  enemies now enter through the verified exact-group stock spawner.
- The stock selector's slot-0 assumption is widened with an exact cross-bucket target
  delta, and `sd.ai` can explicitly target every materialized wizard participant.
- Arbitrary `GameNpc` goal calls are not used for hostile actors; `sd.ai` steers the
  proven `Badguy_MoveStep` collision path instead.

---

## 3. Seam roadmap

### Tier 1 — force multipliers

**1. `sd.hud` / `sd.draw` — immediate-mode draw list.**
Lua submits per-frame commands: text, rects, lines, sprites (from existing atlases),
world-anchored markers via a `world_to_screen` helper. Loader renders them in the EndScene
hook (the debug overlay + glyph-draw seams are the proven substrate).
*Unlocks:* DPS meters, boss bars, damage numbers, quest trackers, ground telegraphs,
race HUDs, tutorial callouts.
*Multiplayer:* Presentation-class — purely local, MP-safe by construction. Pairs with
replicated events for synchronized displays.

**Implemented 2026-07-22.** Each mod owns a bounded immediate display list submitted
from `runtime.tick`; the EndScene renderer supports ASCII text, filled/outlined rects,
thick lines, all 28 stock sprite atlases, viewport queries, and gameplay
`world_to_screen`. `sd.hud` is an exact alias and the renderer preserves the caller's
D3D9 state. Exact two-peer acceptance proves independent tick handlers, command
submission, projection schemas, activation, and release; pixel-level backbuffer
acceptance remains the rendered-output gate. See `lua-draw.md` and the opt-in
`sample.lua.hud_showcase` mod.

**2. Mutable pre-events (filters).**
Cancellable/rewritable hooks at already-resolved seams:
- `damage.dealing` / `damage.taken` — `kPlayerActorMagicDamage` + `kDamageContext*` globals
- `enemy.spawning` / `wave.spawning` — `kSpawnEnemy`, `kSpawnExactEnemyGroup`, `kWaveSpawnerTick`
- `drop.rolling` — `kEnemyDropSelector` (`0x0047C070`, upstream of
  `kOrbRewardInitialize` and `kItemDropCarrierCtor`)
- `spell.casting` (pre, cancellable), `xp.gaining`, `gold.changing`
*Unlocks:* balance overhauls, difficulty directors, custom loot tables, conditional
effects — the shift from telemetry platform to rules engine.
*Multiplayer:* Filters execute only where the affected entity is simulated; outcomes
replicate through existing channels. Authors write them as if single-player.

**Implemented 2026-07-22.** `sd.events.filter` exposes
ordered, owner-side `damage.dealing` and `damage.taken` rewrites/cancellation at the
complete nine-float stock damage context. `enemy.spawning` intercepts the legal stock
constructor call, transactionally rewrites common config fields, and safely cancels
without reviving the removed hand-built `Enemy_Create` path. `drop.rolling` runs at
the owner-side selector before candidate construction, can force a stock reward
category or cancel the roll, and restores the shared native policy transactionally.
`wave.spawning` runs once per stock spawn action and can rewrite its remaining
count and pacing or retire it without bypassing native composition, placement,
construction, or bookkeeping. `spell.casting` runs once before an owner-simulated
primary or secondary cast and can cancel it before stock effects, mana use, or
replication. `xp.gaining` rewrites or cancels the input to the stock progression
gain routine, while `gold.changing` does the same at the global gold mutation
routine and at host-authoritative remote pickups. See
`lua-event-filters.md`, `lua-enemy-spawn-filter.md`,
`lua-drop-roll-filter.md`, `lua-wave-spawn-filter.md`,
`lua-spell-cast-filter.md`, `lua-resource-filters.md`, and the opt-in filter lab mods.
Exact two-peer registry acceptance registers all eight names on both peers and
uses separate zero-delta native XP probes to prove owner participant identity,
process-local callback isolation, and unchanged progression. The
family-specific live verifiers remain the native rewrite/cancel outcome gates.

**3. `sd.state` + `sd.events.broadcast` — replicated mod state & events.**
Authority-writable KV bundled into the snapshot/apply stream (late joiners sync it), plus
mod-defined events delivered to all peers in stream order.
*Unlocks:* every multiplayer-aware mod without netcode; the backbone of the
multiplayer-native contract. Build it early so Tier-1 seams are born MP-native.
*Multiplayer:* this *is* the multiplayer story.

**Implemented 2026-07-22.** Protocol 81 provides a bounded, deterministic Lua value
codec; per-mod authority-owned state; ordered custom events; fragmented reliable Steam
delivery; periodic and first-peer state checkpoints; and a three-peer late-join
acceptance verifier. See `lua-state-and-events.md`.

**4. Content registration.**
- `sd.spells.register{key, cfg, on_cast, on_tick, on_hit}` — allocate an ID, compose an
  authored runtime picker from `sd.ui` (`spell-picker-re.md` explains why the stock
  acquisition dialog is not that picker), route cast dispatch into Lua, compose
  native effect primitives (`kFireEmberCtor`, `kSpellActionBuilder`/`kSpellBuilderReset`/
  `kSpellBuilderFinalize`, projectile-group gates already patched for bot casting).
  At plan time, `skill_shock_nova` proved the data side and scripted behavior was the
  remaining piece.
- `sd.enemies.spawn(key, {hp, speed, scale, loot})` — fix the `Enemy_Create` call shape;
  stat overrides on top.
- `sd.items.register` / `sd.items.grant(key_or_content_id, options)` —
  `kInventoryInsertOrStackItem`, `kItemRecipeClone`, recipe table globals.
*Unlocks:* new-content packs — the ecosystem's lifeblood.
*Multiplayer:* content IDs from `hash(mod_id, key)`; spell behaviors run on the
simulation owner, while the implemented generic modded-effect channel fragments,
authenticates, relays, retires, and exposes semantic effect snapshots on every peer.

**Implemented 2026-07-22.** Content registration is complete across one shared identity
foundation and the item, enemy, and spell families described below.

**Identity foundation implemented 2026-07-22.** All three content families share the
`sd.content.v1` FNV-1a-64 derivation over canonical `(mod_id, key)` strings, mapped into
a positive 63-bit Lua-integer namespace. Duplicate keys, cross-kind reuse, and hash
collisions fail instead of probing by load order. Registration is entry-script-only and
identities are removed with their owning Lua state. See `lua-content-identity.md`.

**Item registration and grants implemented 2026-07-22.** `sd.items.register`, `get`, and
`list` bind stable content keys to exact recipe name/type pairs in the effective item
catalog. `sd.items.grant` is authority-only, routes a stable content ID to a selected
participant over protocol 81, and lets that owner resolve its peer-local recipe UID just
before verified stock inventory insertion. Recipe UIDs and addresses never become wire
identity; reliable target authentication and request deduplication make the mutation
multiplayer-safe. See `lua-items.md`.

**Enemy registration and spawning implemented 2026-07-22.** `sd.enemies.register`,
`get`, and `list` bind deterministic identities to semantic hostile stock classes.
Authority-only `sd.enemies.spawn` queues the verified exact-group stock spawner with a
valid modifier array, transactionally composes per-spawn HP/speed/scale with ordered
spawn filters, and attaches per-actor loot policy without mutating shared config.
Protocol 81 carries the content ID and effective constructor values through world
snapshots and death tombstones; spawn/death notify events expose the same stable ID on
every peer. The opt-in two-peer acceptance covers authority rejection, exact construction,
client materialization, lifecycle notifications, tombstone identity, and `none` loot
suppression. See `lua-enemies.md`.

**Spell catalog, input selection, owner runtime, and generic effect replication implemented
2026-07-22.** `sd.spells.register`, `get`, `list`, `select`, `clear_selection`,
`get_selection`, `cast`, and `get_effects` bind deterministic
identities to bounded immutable config and owner-state callbacks. Protocol 81 routes host
commands to the affected participant's owner, where `on_cast`, timed `on_tick`, and
once-per-actor `on_hit` callbacks drive a bounded address-free effect lifecycle. The same
protocol fragments and relays complete per-owner effect generations, including explicit
empty retirement snapshots. Selected primary and exact live belt inputs suppress stock
dispatch, charge native mana transactionally, enforce local cooldowns, and enter that same
owner route. The disabled spell lab composes a player-facing native-authored picker from
`sd.ui` and the local selection API. The opt-in two-peer acceptance covers local-selection
isolation, both owner directions, client route rejection, semantic effect convergence, and
explicit pre-expiry retirement. See `lua-spells.md`.

**5. `sd.ai` — enemy brain overrides.**
Per-enemy move goals (`kGameNpcSetMoveGoal`), target override (fixes the slot-1–3
targeting limitation foundationally, replacing the pathfinder-hang dead end), `on_think`
callbacks, formalized nav/collision queries.
*Unlocks:* scripted bosses, invasions, enemies that fight bots, encounter design.
*Multiplayer:* runs on the authority (enemies are authority-simulated); clients receive
replicated movement — mod AI code never runs on clients.

**Implemented 2026-07-23.** `sd.ai.register` attaches bounded per-spawn
blackboards and authority-only `on_think` callbacks to deterministic registered
enemies. Semantic target overrides support the local wizard and every materialized
participant, while point goals rotate the proven hostile move vector without
bypassing the stock collision executor. RE established that `kGameNpcSetMoveGoal`
belongs to a different actor class, so the implementation composes at
`MonsterPathfinding_RefreshTarget`/`Badguy_MoveStep` instead of making an invalid
cross-class call. Clients run no mod AI and receive the resulting protocol-81 world
snapshots. The opt-in two-peer acceptance covers host-only controller execution,
blackboard/target/move-goal decisions, collision-valid replicated motion, client mutation
rejection, and per-actor retirement. See `lua-ai.md` and the opt-in
`sample.lua.ai_boss_lab` mod.

### Tier 2 — ecosystem infrastructure

**6. `sd.storage` — scoped persistence.** Per-mod, per-profile KV/JSON under
`.sdmod/storage/<mod-id>/`. Replaces ad-hoc `io.*`; prerequisite for sandboxed trust
tiers when distribution arrives. *MP:* local (per player). Shared-run state belongs in
`sd.state`; the API docs draw that line explicitly.

**Implemented 2026-07-22.** `sd.storage` provides bounded typed
`get/set/delete/clear/snapshot` operations over the launcher-isolated per-mod data root.
Writes encode a complete candidate and replace the durable file before changing the
live snapshot; malformed, oversized, cyclic, or foreign data fails visibly. The store is
strictly local and advertises `storage.profile.local`. The opt-in two-peer acceptance
proves distinct host/client values, transactional rejection, process-restart durability,
delete/clear isolation, and exact restoration of pre-existing profile bytes. See
`lua-storage.md` and the opt-in `sample.lua.storage_lab` mod.

**7. `sd.audio` — BASS bindings.** The game ships `bass.dll`; bind sample/stream
play/stop/volume. *Unlocks:* stingers, custom music, voice packs. *MP:* presentation-local;
synchronized cues = replicated event + local playback.

**Implemented 2026-07-23.** `sd.audio` dynamically binds the already-loaded,
game-owned `bass.dll` for mod-root-scoped samples and streams, opaque playback
handles, live volume, stop, semantic state, and per-mod cleanup. Canonical path
containment, four explicit formats, 64-playback per-mod and 256-playback global
limits, and a 512 MiB asset ceiling keep the local presentation surface bounded.
The loader neither loads nor initializes BASS. Audio never replicates; authority
code broadcasts a semantic custom event and every peer performs the cue locally. The
opt-in two-peer acceptance stages deterministic silent PCM and proves independent
sample/stream state, volume, stop, capacity, and release behavior. See `lua-audio.md`
and the opt-in `sample.lua.audio_lab` mod.

**8. `sd.ui` authoring.** Create surfaces/panels/buttons/labels through the game's UI
engine (`ui-engine-system-map.md`); reuse the semantic action layer for input. *Unlocks:*
mod settings screens, dialogue choices, custom shops, quest logs. *MP:* presentation-local;
action handlers that mutate shared state are simulation-class and auto-route.

**Implemented 2026-07-23.** Authored `sd.ui` surfaces retain bounded mod-owned
panels, labels, and buttons while rendering them through the game's native
`UiPanel_Render` and exact-text helpers. Normalized layout, opaque ownership,
strict options, keyboard/mouse focus, and programmatic activation all feed one
semantic action queue; callbacks run only from the game-thread Lua pump.
Presentation actions remain local. Simulation-class buttons on clients become
reliable protocol-81 authority requests authenticated by endpoint, participant
session nonce, request order, and the host's matching enabled registration.
See `lua-ui-authoring.md` and the opt-in `sample.lua.ui_authoring_lab` mod.

**9. `sd.timer` + coroutine scheduler.** `after(ms, fn)`, `every(ms, fn)`, `sequence{}`
sugar over `runtime.tick` (every mod hand-rolls this today). *MP:* local; docs steer
simulation decisions into filters/authority hooks.

**Implemented 2026-07-22.** `sd.timer` provides cancelable one-shot and repeating
callbacks plus a single-handle ordered `sequence` scheduler. It uses the runtime's
monotonic game-thread tick, bounds retained callbacks and per-tick work, cancels failing
callbacks, and tears down every registry reference with the owning mod. It advertises
`timer.local.scheduler`. The opt-in two-peer acceptance proves independent callback
results, validation, cancellation, error retirement, full per-mod capacity, and release
isolation; see `lua-timer.md` and the opt-in `sample.lua.timer_lab` mod.

**10. `sd.bus` — cross-mod contracts.** Publish/subscribe across loaded mods plus
`provides`/`requires` in `manifest.json`. *Unlocks:* framework mods (quest engine, UI kit)
that content mods build on — the compounding mechanism of a real ecosystem. *MP:* local
dispatch; a bus message that must reach all peers is just `sd.events.broadcast`.

**Implemented 2026-07-22.** `sd.bus` provides synchronous bounded
`publish/subscribe/unsubscribe` plus `has/providers` contract discovery. The launcher
rejects unresolved enabled sets; the loader orders consumers after successfully loaded
providers and skips them when a real provider is unavailable. Payloads cross isolated Lua
states through the bounded value codec, subscriptions are snapshot-dispatched and cleaned
up with their owner, and nested work is capped. The exact two-peer acceptance proves
provider/consumer loading, nested cross-state dispatch, per-process isolation, capacity,
and release. It advertises `bus.local.contracts`; see `lua-bus.md` and the opt-in
provider/consumer lab pair.

**11. `sd.net` — escape hatch.** Raw mod-defined messages between participants for the
rare mod that outgrows `sd.state`/broadcast (e.g., streaming large payloads). Most mods
never touch it — its existence keeps the default path honest.

**Implemented 2026-07-23.** `sd.net.send/broadcast/on/off/get_limits` carries
binary-safe payloads through a bounded protocol-81 fragment envelope. Clients send only
to the host; the host authenticates endpoint, hop identity, source participant session,
target, envelope, and replay key before local delivery or relay. Per-mod subscriptions
dispatch only from the Lua game-thread pump, and disconnect cleanup removes assemblies,
replay memory, and queued relays. Steam uses reliable no-Nagle fragments; the local UDP
development backend retains datagram semantics. Transport identity is authenticated but
payload authority remains the mod's responsibility. See `lua-net.md` and the disabled
`sample.lua.net_lab` mod.

**12. `sd.waves` — wave intelligence.**
Consolidated read API over the spawner. `get_state()` returns wave number, spawner phase,
alive/spawned/killed/remaining-to-spawn counts, and per-type composition
(`{enemy_type, planned, spawned, alive, killed}`); `get_schedule(n)` previews upcoming
waves from the parsed `wave.txt` table; the `wave.started` event payload gains the
planned composition. Today's surface already exposes wave number, a live enemy count
(`kEnemyCountGlobal`), and spawner section/advance state — composition and pending-spawn
counts need one RE pass on the spawner structures behind `kWaveSpawnerTick`/`kArenaGlobal`
(start from `wave-scaling-re.md`).
*Unlocks:* wave-progress HUDs ("23/50 — 3 necromancers left"), The Director reading
before it rewrites (pairs with the seam-02 `wave.spawning` filter), boss-wave music cues,
spawn-aware bot tactics.
*Multiplayer:* read-only; waves are authority-simulated and the framework replicates the
wave summary, so `get_state()` answers identically on every peer.

**Implemented 2026-07-22.** `sd.waves.get_state()` now reports the authority's
phase, exact aggregate and per-type observed counts, and remaining native spawn
budget. `get_schedule(n)` parses the effective staged `wave.txt`; because random
group selection has no RNG-free exact future composition, planned rows use a
documented deterministic largest-remainder projection that sums to `SPAWN`.
Spawner identities attribute overlapping births and deaths, `wave.started`
includes planned composition, and protocol 81 carries a bounded validated
summary in authenticated authority participant frames for identical peer reads.
The opt-in two-peer acceptance covers exact schedule parity, clean idle state,
authority-only stock wave start, identical sorted live summaries, and matching
`wave.started` payloads. See `lua-waves.md`, the read-only
`tools/verify_lua_waves.py` probe, and the disabled `sample.lua.waves_lab` mod.

### Tier 3 — nearly-free power-ups and polish

- **`sd.time.set_scale()`** — slow-mo, pause, frame-step. *MP:* shared-simulation variable
  → authority-gated + replicated (or refused in sessions).

  **Investigated 2026-07-22.** The previously proposed `kGameTimingScaleGlobal` shortcut
  is not a speed multiplier. Headless Ghidra found 136 xrefs that use its live value
  (`100.0`) as a ticks-per-second conversion, including divisions; zeroing it is unsafe
  and changing it cannot coherently pause existing counters. A correct seam must gate
  actor-world/player/wave ticks and compose with replicated multiplayer pause state. See
  `reverse-engineering/game-timing-scale.md`.

  **Implemented 2026-07-23.** `sd.time` provides
  `get_scale/get_state/set_scale/step`, combines per-mod requests by their minimum
  fixed-point scale, bounds paused frame-step work, and releases requests on unload and
  run reset. One scoped actor-world frame decision gates nested player and wave ticks while
  the Lua/replication pump remains responsive. Only the offline or host authority may
  mutate time; protocol 81 repeats scale/revision state and sends prompt authenticated
  reliable control updates with deduplicated step sequences. Shared menu and level-up
  pauses take precedence, and values above native speed are rejected. See `lua-time.md`
  and the disabled `sample.lua.time_lab` mod.
- **`sd.rng.set_seed()`** — `kNativeRngInitialize` + `kNativeGlobalRngStateGlobal`;
  daily challenges, practice, replays. *MP:* authority seeds, seed replicates at run start.

  **Implemented 2026-07-22.** `sd.rng` provides `get_seed/set_seed` and accepts an exact
  bounded seed only from the offline/host simulation authority before a run. The existing
  run-nonce path carries it to clients and every peer applies it through the stock initializer
  immediately before arena generation. The opt-in two-peer acceptance covers fresh-state
  isolation, client rejection, authenticated host-row publication, Run-intent-gated client
  installation, native-gated arena entry, exact owner nonce state, and post-entry mutation
  rejection. See `lua-rng.md` and the disabled `sample.lua.rng_lab` mod.
- **`sd.nav`** — promote `get_nav_grid` + native `movement_collision_test_circle_placement`
  bridge out of `sd.debug` into a blessed pathfinding/LOS API (native collision test is
  already the required path — make it the easy one). *MP:* read-only, safe everywhere.

  **Implemented 2026-07-22.** `sd.nav` provides `get_grid/test_segment` with bounded
  subdivision sampling, asynchronous gameplay-thread snapshots, finite segment tests, and
  no raw process addresses. It reuses the native player-sized collision and path rules and
  advertises `nav.read`. The opt-in two-peer acceptance independently exercises the native
  grid and segment path on each peer, requires exact recursive address-free schemas, and
  compares the shared grid geometry without conflating presentation-local traversal
  counts. See `lua-nav.md` and the disabled `sample.lua.nav_lab` mod.
- **`sd.scene`** — region/level switching (`kGameplaySwitchRegion`, transition globals)
  paired with `.boneyard` overlays. *MP:* authority-routed; scene epochs already replicate.

  **Implemented 2026-07-22.** `sd.scene` provides address-free `get_state/switch_region`.
  Only the offline/host simulation authority can switch; arena entry reuses the seeded
  shared-hub run path, while authenticated participant frames make clients follow host
  hub/private-region intent. Raw arena exits remain owned by the stock synchronized Leave
  Game flow. The opt-in two-peer acceptance covers client rejection, private-region and
  shared-hub follow, `sd.scene` arena entry, participant-intent convergence, and the raw
  arena-exit guard. See `lua-scene.md` and the disabled `sample.lua.scene_lab` mod.
- **`sd.camera`** — cutscenes, boss intros, shake. *MP:* presentation-local.

  **Implemented 2026-07-22.** `sd.camera` provides bounded local view inspection,
  per-mod world-focus ownership, automatic lifecycle cleanup, and the stock native
  shake path. Six post-Region-tick hooks translate the primary, expanded, and culling
  view origins together without exposing pointers or changing simulation state. The
  opt-in two-peer acceptance proves independent native focus ownership, local shake
  feedback, exact schemas, and clean release on both peers. See `lua-camera.md` and
  `reverse-engineering/native-camera-control.md`.
- **`sd.sprites`** — runtime sprite/frame registration using the reversed bundle format,
  so mods add art without clobbering whole atlases. *MP:* local; art parity comes from the
  mod-set handshake.

  **Implemented 2026-07-22.** `sd.sprites` registers bounded mod-root PNG/bundle
  pairs as revisioned `mod_id:key` atlases consumed directly by `sd.draw`. Path
  canonicalization, PNG/IHDR and frame geometry validation, atomic replacement,
  unload cleanup, a JSON bundle builder, and a backbuffer verifier cover the full
  authoring/runtime lifecycle. Rendering remains presentation-local; the launcher's
  exact mod-directory hash supplies peer art parity. The opt-in two-peer acceptance
  stages deterministic real asset bytes and proves local registration, revision, draw
  lookup, and release isolation. See `lua-sprites.md`.
- **Author DX** — generate LuaLS/EmmyLua stubs from the binding registry in CI (the
  `RegisterFunction` tables make it mechanical); hot-reload a mod's `lua_State` on file
  change; in-game exec console (the named pipe already does this externally). Ecosystem
  growth is bounded by author iteration speed as much as API power.

  **Implemented 2026-07-23.** The checked-in `api/lua/sd.lua` inventory is generated
  directly from root-reachable `RegisterLua*Bindings`, preserves table aliases such as
  `sd.hud == sd.draw`, and is drift-checked with unit tests in CI. Lua/hybrid manifests
  may opt into stable, hashed source-entry hot reload; syntax failures preserve the
  running state, normal unload cleanup precedes replacement, and reload is disabled for
  multiplayer transport launches so the staged parity hash remains authoritative.
  `Ctrl+Backtick` opens a bounded draw-list console that submits to the same gameplay-safe
  async queue and result capture as the external named pipe. A disabled invisible lab and
  source-restoring verifier cover offline reload, syntax preservation, and whole-transport
  deferral without synthesizing desktop input. Exact two-peer acceptance applies one
  candidate while proving stable baseline code and native UI handles on both
  transport-enabled peers, then restores the source byte-for-byte. See `lua-authoring.md`.

---

## 4. Flagship mod concepts — support assessment

"Roadmap support" reflects the completed seams above. "Remaining product work" is not an
unimplemented item from section 3.

| Mod | Concept | Roadmap support | Remaining product work | Multiplayer story |
|---|---|---|---|---|
| **Balance Workshop** | Full numbers overhaul + conditional effects (glass cannon, thorns) | Ready | Author the balance rules and UX | Filters run owner-side; exact mod parity gives every peer identical rules |
| **Streamer Mode** | Twitch chat spawns enemies / heals / curses via channel points | Ready | Twitch integration and content design | Authority commands mutate simulation; broadcast events drive local HUD/audio |
| **The Director** | Adaptive difficulty that reads health/economy and reshapes waves | Ready | Director policy and tuning | Runs authority-side; intensity lives in `sd.state` for client HUDs |
| **Solomon's Trials** | Daily seeded challenge plus Website leaderboard | Partial | Website submission, authentication, and leaderboard product contract | Authority seeds the run; shared state can publish challenge progress |
| **Cartographer** | Custom arena/campaign packs with narration | Partial | Level-authoring tooling and richer per-level content hooks | Scene switches are authority-routed and epochs replicate |
| **Boneyard Together+** | Wave races, shared fate, and trading | Ready | Mode rules and trading UX | Composes `sd.state`, filters, items, UI, and HUD without custom transport |
| **Boneyard Bosses** | Multi-phase bosses, telegraphs, enrage, and unique loot | Ready | Encounter content and tuning | Boss brains run on authority; phase replicates; presentation renders locally |
| **Arcanum Forge** | New Lua-behavior spell pack | Partial | Specialized blessed primitives for clone, force, and native projectile variants | IDs and casts are owner-routed; generic semantic effects replicate |
| **College Nights** | Hub quests, dialogue, reputation, and rewards | Partial | NPC quest-control and campaign content | Shared quest state uses `sd.state`; profile progress uses `sd.storage` |
| **Replay & Ghost** | Record runs and race a ghost | Partial | Input capture, replay format, and a blessed ghost puppet | Exact seeds and local storage exist; ghost presentation stays local |

---

## 5. Completed build order

All items in this sequence are implemented; the ordering is retained as an execution
record and as guidance for future API families.

1. **`sd.state` + `sd.events.broadcast`** — the multiplayer-native backbone. Building it
   first means every subsequent seam is born MP-native instead of retrofitted.
2. **`sd.hud`** — appears in seven of ten flagship gap-lists; purely local so it has no MP
   risk; immediately makes every existing mod feel alive.
3. **Filters (damage → spawn → drop → wave)** — with the owner-side execution rule from
   day one. Together with 1–2, average flagship support jumps from ~45% to ~80%.
4. **`sd.storage`** — small, unblocks meta-progression and Trials.
5. **`sd.spells.register`** then **`sd.ai`** — the two deep seams; each unlocks a genre
   (content packs; encounter design). Includes the `Enemy_Create` call-shape fix and the
   generic modded-effect replication channel.
6. **Tier-3 quick wins opportunistically** (`sd.time`, `sd.rng`, `sd.nav` promotion) and
   **DX** (stub generation, hot reload) whenever a breather is needed — they're cheap and
   compound author velocity.

## 6. Open research and distribution questions

- **Authority migration:** if the authority peer leaves mid-run, does mod simulation state
  (`sd.state`, filter ownership, AI brains) migrate? Punt (end run) vs. handoff protocol.
- **Determinism audit scope:** what native systems consume `kNativeGlobalRngStateGlobal`
  outside runs (menu shuffles?) — matters for Trials/Replay fidelity.
- **Trust tiers:** `has_capability` exists and unsafe standard-library globals are removed;
  when distribution arrives, which capabilities gate raw `sd.debug` access versus blessed
  simulation APIs, and what review/signing policy grants them?

### Resolved policy: exact multiplayer parity

Peers may not run different presentation-only mods in the same session. The handshake
compares the exact enabled content fingerprint and rejects mismatch. A future relaxation
would require framework-enforced call and overlay classification; a manifest declaration
alone is not a trustworthy boundary.
