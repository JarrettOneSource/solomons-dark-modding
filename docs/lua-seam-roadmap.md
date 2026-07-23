# Lua Seam Roadmap — Growing a Lua-Only Modding Ecosystem

Status: brainstorm / design record (2026-07-21)

Goal: Solomon Dark should live and thrive on Lua mods alone, with this framework as the
bootstrap. Mod authors should never need native code for gameplay, content, UI, or
multiplayer — and **mods must be multiplayer-native by default: the same script works in a
solo run and in a Steam session with zero netcode or special-casing by the mod author.**

This doc records: the current `sd.*` surface, the multiplayer-native design principle, a
tiered roadmap of new seams (each annotated with its multiplayer behavior), flagship mod
concepts with a supported-today assessment, and a suggested build order.

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
| **Simulation** (mutates shared game state) | `sd.enemies.spawn`, `sd.items.grant`, `sd.world.spawn_reward`, filter outcomes | Executes where the affected entity is simulated (authority for run entities; owning peer for that peer's wizard, per the participant ownership rules). Owner-routed seams transparently request the owner; authority command seams such as item grants reject client authorship and route the accepted command to the target owner. Results replicate through the existing snapshot channels. |
| **Presentation** (local output) | `sd.hud.*`, `sd.audio.*`, `sd.camera.*`, `sd.ui` authoring | Always local, never replicated. Inherently MP-safe. |
| **Meta** (mod runtime) | `sd.storage.*`, `sd.timer.*`, `sd.bus.*`, `sd.runtime.*` | Local, with defined sync points (see `sd.state`). |

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
5. **Mod parity handshake.** Session join exchanges the enabled mod set (`manifest.json`
   id + version). Mismatch → surfaced in the lobby card (the lobby browser already renders
   member state) and blocked or downgraded per-mod (presentation-only mods may be allowed
   to differ). Framework-level; authors do nothing.
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
- **`sd.events`** — `on` plus authority-only `broadcast` for mod-defined ordered events.
  Built-in notify events are `runtime.tick`, `run.started`, `run.ended`, `wave.started`,
  `wave.completed`, `enemy.death`, `enemy.spawned`, `spell.cast`, `gold.changed`,
  `drop.spawned`, `level.up`.
- **`sd.bots`** — full ally-bot runtime: `create/destroy/clear/update`, `move_to/stop/
  face/face_target`, `cast`, `get_state`, `get_participant_state`, `get_participants`,
  `get_nameplate`, `get_skill_choices/choose_skill`, primary-attack helpers. Per-entity
  stat pools; bots are participants.
- **`sd.ui`** — semantic read/automation middle layer: `get_state`, `get_snapshot`,
  `find_element/find_action`, `activate_action/activate_element`, `perform`.
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
- Full data-overlay surface: `data/wizardskills/*.cfg` (60+ skills), `data/wave.txt`,
  `data/items.cfg`, `data/levels/*.boneyard`, `data/dialogue/*`, `magenames.txt`,
  `images/*.bundle` sprite atlases (format reversed; extractor in `tools/`), sounds/music.
- Sample mods prove overlay + Lua patterns: `skill_shock_nova` (new data-driven skill),
  `wave_fast_start`, `story_custom_intro`, `item_gold_focus`, `lua_bots`,
  `lua_ui_sandbox_lab`, `lua_dark_cloud_sort_bootstrap`.
- Mods get the full Lua stdlib (`luaL_openlibs`) — raw `io.*` persistence is technically
  possible today, but unscoped.

### Structural gaps (why mods can't thrive yet)

1. **Scripted spell presentation remains** — deterministic spell metadata, owner-routed
   callback execution, bounded effects, and generic effect snapshots now join registered
   items and stock-archetype enemies, and direct primary/belt input is integrated; an
   authored picker still depends on the remaining UI-authoring seam.
2. **Authored UI remains incomplete** — Lua drawing and local custom audio exist, but
   mods still cannot build native-style surfaces and controls.
3. **Shared timing control is incomplete** — enemy brains and scene changes are now
   authority-owned, while coherent pause/slow-motion still needs its public seam.
4. **Author DX and presentation parity policy remain incomplete.** Cross-mod contracts now
   exist, but generated editor stubs, hot reload, and manifest-enforced classification of
   presentation-only mods remain.

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
D3D9 state. See `lua-draw.md` and the opt-in `sample.lua.hud_showcase` mod.

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

**3. `sd.state` + `sd.events.broadcast` — replicated mod state & events.**
Authority-writable KV bundled into the snapshot/apply stream (late joiners sync it), plus
mod-defined events delivered to all peers in stream order.
*Unlocks:* every multiplayer-aware mod without netcode; the backbone of the
multiplayer-native contract. Build it early so Tier-1 seams are born MP-native.
*Multiplayer:* this *is* the multiplayer story.

**Implemented 2026-07-22.** Protocol 72 provides a bounded, deterministic Lua value
codec; per-mod authority-owned state; ordered custom events; fragmented reliable Steam
delivery; periodic and first-peer state checkpoints; and a three-peer late-join
acceptance verifier. See `lua-state-and-events.md`.

**4. Content registration.**
- `sd.spells.register{key, cfg, on_cast, on_tick, on_hit}` — allocate an ID, integrate an
  authored runtime picker (`spell-picker-re.md` explains why the stock acquisition dialog
  is not that picker), route cast dispatch into Lua, compose
  native effect primitives (`kFireEmberCtor`, `kSpellActionBuilder`/`kSpellBuilderReset`/
  `kSpellBuilderFinalize`, projectile-group gates already patched for bot casting).
  Data side is proven by `skill_shock_nova`; the missing piece is scripted behavior.
- `sd.enemies.spawn(key, {hp, speed, scale, loot})` — fix the `Enemy_Create` call shape;
  stat overrides on top.
- `sd.items.register` / `sd.items.grant(key_or_content_id, options)` —
  `kInventoryInsertOrStackItem`, `kItemRecipeClone`, recipe table globals.
*Unlocks:* new-content packs — the ecosystem's lifeblood.
*Multiplayer:* content IDs from `hash(mod_id, key)`; spell behaviors run on the
simulation owner, while the implemented generic modded-effect channel fragments,
authenticates, relays, retires, and exposes semantic effect snapshots on every peer.

**Identity foundation implemented 2026-07-22.** All three content families share the
`sd.content.v1` FNV-1a-64 derivation over canonical `(mod_id, key)` strings, mapped into
a positive 63-bit Lua-integer namespace. Duplicate keys, cross-kind reuse, and hash
collisions fail instead of probing by load order. Registration is entry-script-only and
identities are removed with their owning Lua state. See `lua-content-identity.md`.

**Item registration and grants implemented 2026-07-22.** `sd.items.register`, `get`, and
`list` bind stable content keys to exact recipe name/type pairs in the effective item
catalog. `sd.items.grant` is authority-only, routes a stable content ID to a selected
participant over protocol 77, and lets that owner resolve its peer-local recipe UID just
before verified stock inventory insertion. Recipe UIDs and addresses never become wire
identity; reliable target authentication and request deduplication make the mutation
multiplayer-safe. See `lua-items.md`.

**Enemy registration and spawning implemented 2026-07-22.** `sd.enemies.register`,
`get`, and `list` bind deterministic identities to semantic hostile stock classes.
Authority-only `sd.enemies.spawn` queues the verified exact-group stock spawner with a
valid modifier array, transactionally composes per-spawn HP/speed/scale with ordered
spawn filters, and attaches per-actor loot policy without mutating shared config.
Protocol 77 carries the content ID and effective constructor values through world
snapshots and death tombstones; spawn/death notify events expose the same stable ID on
every peer. See `lua-enemies.md`.

**Spell catalog, input selection, owner runtime, and generic effect replication implemented
2026-07-22.** `sd.spells.register`, `get`, `list`, `select`, `clear_selection`,
`get_selection`, `cast`, and `get_effects` bind deterministic
identities to bounded immutable config and owner-state callbacks. Protocol 77 routes host
commands to the affected participant's owner, where `on_cast`, timed `on_tick`, and
once-per-actor `on_hit` callbacks drive a bounded address-free effect lifecycle. The same
protocol fragments and relays complete per-owner effect generations, including explicit
empty retirement snapshots. Selected primary and exact live belt inputs suppress stock
dispatch, charge native mana transactionally, enforce local cooldowns, and enter that same
owner route. The player-facing authored picker remains with `sd.ui`. See `lua-spells.md`.

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
cross-class call. Clients run no mod AI and receive the resulting protocol-77 world
snapshots. See `lua-ai.md` and the opt-in `sample.lua.ai_boss_lab` mod.

### Tier 2 — ecosystem infrastructure

**6. `sd.storage` — scoped persistence.** Per-mod, per-profile KV/JSON under
`.sdmod/storage/<mod-id>/`. Replaces ad-hoc `io.*`; prerequisite for sandboxed trust
tiers when distribution arrives. *MP:* local (per player). Shared-run state belongs in
`sd.state`; the API docs draw that line explicitly.

**Implemented 2026-07-22.** `sd.storage` provides bounded typed
`get/set/delete/clear/snapshot` operations over the launcher-isolated per-mod data root.
Writes encode a complete candidate and replace the durable file before changing the
live snapshot; malformed, oversized, cyclic, or foreign data fails visibly. The store is
strictly local and advertises `storage.profile.local`. See `lua-storage.md` and the
opt-in `sample.lua.storage_lab` mod.

**7. `sd.audio` — BASS bindings.** The game ships `bass.dll`; bind sample/stream
play/stop/volume. *Unlocks:* stingers, custom music, voice packs. *MP:* presentation-local;
synchronized cues = replicated event + local playback.

**Implemented 2026-07-23.** `sd.audio` dynamically binds the already-loaded,
game-owned `bass.dll` for mod-root-scoped samples and streams, opaque playback
handles, live volume, stop, semantic state, and per-mod cleanup. Canonical path
containment, four explicit formats, 64-playback per-mod and 256-playback global
limits, and a 512 MiB asset ceiling keep the local presentation surface bounded.
The loader neither loads nor initializes BASS. Audio never replicates; authority
code broadcasts a semantic custom event and every peer performs the cue locally.
See `lua-audio.md` and the opt-in `sample.lua.audio_lab` mod.

**8. `sd.ui` authoring.** Create surfaces/panels/buttons/labels through the game's UI
engine (`ui-engine-system-map.md`); reuse the semantic action layer for input. *Unlocks:*
mod settings screens, dialogue choices, custom shops, quest logs. *MP:* presentation-local;
action handlers that mutate shared state are simulation-class and auto-route.

**9. `sd.timer` + coroutine scheduler.** `after(ms, fn)`, `every(ms, fn)`, `sequence{}`
sugar over `runtime.tick` (every mod hand-rolls this today). *MP:* local; docs steer
simulation decisions into filters/authority hooks.

**Implemented 2026-07-22.** `sd.timer` provides cancelable one-shot and repeating
callbacks plus a single-handle ordered `sequence` scheduler. It uses the runtime's
monotonic game-thread tick, bounds retained callbacks and per-tick work, cancels failing
callbacks, and tears down every registry reference with the owning mod. It advertises
`timer.local.scheduler`; see `lua-timer.md` and the opt-in `sample.lua.timer_lab` mod.

**10. `sd.bus` — cross-mod contracts.** Publish/subscribe across loaded mods plus
`provides`/`requires` in `manifest.json`. *Unlocks:* framework mods (quest engine, UI kit)
that content mods build on — the compounding mechanism of a real ecosystem. *MP:* local
dispatch; a bus message that must reach all peers is just `sd.events.broadcast`.

**Implemented 2026-07-22.** `sd.bus` provides synchronous bounded
`publish/subscribe/unsubscribe` plus `has/providers` contract discovery. The launcher
rejects unresolved enabled sets; the loader orders consumers after successfully loaded
providers and skips them when a real provider is unavailable. Payloads cross isolated Lua
states through the bounded value codec, subscriptions are snapshot-dispatched and cleaned
up with their owner, and nested work is capped. It advertises `bus.local.contracts`; see
`lua-bus.md` and the opt-in provider/consumer lab pair.

**11. `sd.net` — escape hatch.** Raw mod-defined messages between participants for the
rare mod that outgrows `sd.state`/broadcast (e.g., streaming large payloads). Most mods
never touch it — its existence keeps the default path honest.

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
includes planned composition, and protocol 77 carries a bounded validated
summary in authenticated authority participant frames for identical peer reads.
See `lua-waves.md` and the read-only `tools/verify_lua_waves.py` probe.

### Tier 3 — nearly-free power-ups and polish

- **`sd.time.set_scale()`** — slow-mo, pause, frame-step. *MP:* shared-simulation variable
  → authority-gated + replicated (or refused in sessions).

  **Investigated 2026-07-22.** The previously proposed `kGameTimingScaleGlobal` shortcut
  is not a speed multiplier. Headless Ghidra found 136 xrefs that use its live value
  (`100.0`) as a ticks-per-second conversion, including divisions; zeroing it is unsafe
  and changing it cannot coherently pause existing counters. A correct seam must gate
  actor-world/player/wave ticks and compose with replicated multiplayer pause state. See
  `reverse-engineering/game-timing-scale.md`.
- **`sd.rng.set_seed()`** — `kNativeRngInitialize` + `kNativeGlobalRngStateGlobal`;
  daily challenges, practice, replays. *MP:* authority seeds, seed replicates at run start.

  **Implemented 2026-07-22.** `sd.rng` provides `get_seed/set_seed` and accepts an exact
  bounded seed only from the offline/host simulation authority before a run. The existing
  run-nonce path carries it to clients and every peer applies it through the stock initializer
  immediately before arena generation. See `lua-rng.md`.
- **`sd.nav`** — promote `get_nav_grid` + native `movement_collision_test_circle_placement`
  bridge out of `sd.debug` into a blessed pathfinding/LOS API (native collision test is
  already the required path — make it the easy one). *MP:* read-only, safe everywhere.

  **Implemented 2026-07-22.** `sd.nav` provides `get_grid/test_segment` with bounded
  subdivision sampling, asynchronous gameplay-thread snapshots, finite segment tests, and
  no raw process addresses. It reuses the native player-sized collision and path rules and
  advertises `nav.read`. See `lua-nav.md`.
- **`sd.scene`** — region/level switching (`kGameplaySwitchRegion`, transition globals)
  paired with `.boneyard` overlays. *MP:* authority-routed; scene epochs already replicate.

  **Implemented 2026-07-22.** `sd.scene` provides address-free `get_state/switch_region`.
  Only the offline/host simulation authority can switch; arena entry reuses the seeded
  shared-hub run path, while authenticated participant frames make clients follow host
  hub/private-region intent. Raw arena exits remain owned by the stock synchronized Leave
  Game flow. See `lua-scene.md`.
- **`sd.camera`** — cutscenes, boss intros, shake. Only major seam with **no RE done yet**.
  *MP:* presentation-local.
- **`sd.sprites`** — runtime sprite/frame registration using the reversed bundle format,
  so mods add art without clobbering whole atlases. *MP:* local; art parity comes from the
  mod-set handshake.
- **Author DX** — generate LuaLS/EmmyLua stubs from the binding registry in CI (the
  `RegisterFunction` tables make it mechanical); hot-reload a mod's `lua_State` on file
  change; in-game exec console (the named pipe already does this externally). Ecosystem
  growth is bounded by author iteration speed as much as API power.

---

## 4. Flagship mod concepts — support assessment

"Today" = with the current framework. "Needs" = the seams above that close the gap.
Multiplayer column = how it behaves once built on the MP-native contract.

| Mod | Concept | Today | Needs | Multiplayer story |
|---|---|---|---|---|
| **Balance Workshop** | Full numbers overhaul + conditional effects (glass cannon, thorns) | ~85% | damage filters for conditional parts | Filters run owner-side; identical rules for all peers via mod parity |
| **Streamer Mode** | Twitch chat spawns enemies / heals / curses via channel points (external bot → exec pipe works now) | ~70% | HUD toasts, audio stingers | Spawn calls auto-route to authority; toasts via broadcast → every peer sees chat chaos |
| **The Director** | L4D-style adaptive difficulty: watches DPS/health/economy, reshapes waves live | ~60% | `wave.spawning` filter, `sd.waves` reads, per-hit damage events, HUD | Runs entirely authority-side; intensity in `sd.state` for client HUDs |
| **Solomon's Trials** | Daily seeded challenge + leaderboard on the existing Website backend | ~80% | Website submit contract (offer control exists: `choose_level_up_option`) | Authority seeds the run; co-op daily boards become possible |
| **Cartographer** | Custom arena/campaign packs with narration | ~50% (static overlays work now) | level tooling, `sd.scene`, per-level hooks | Scene switches authority-routed; epochs already replicate |
| **Boneyard Together+** | Custom co-op modes: wave race, shared-fate, trading | ~45% | `sd.state`/broadcast, HUD, damage-share filters | The showcase — entire mod is `sd.state` + filters + HUD |
| **Boneyard Bosses** | Multi-phase scripted bosses, telegraphs, enrage, unique loot | ~40% | `sd.ai`, spawn fix, HUD telegraphs, audio, drop injection | Boss brain on authority; phase in `sd.state`; telegraphs drawn locally per peer |
| **Arcanum Forge** | 10 new Lua-behavior spells: gravity well, chrono field (time-scale global), mirror image (`WizardCloneFromSourceActor`), ember turret | ~35% (primitives provably drivable — bots cast, clone, spawn embers) | `sd.spells.register`, generic effect replication | Deterministic spell IDs; behavior on owner; effects replicate like native ones |
| **College Nights** | Hub quest campaign: NPC quests, dialogue, reputation, rewards | ~30% | UI authoring, `sd.items.grant`, `sd.storage`, NPC control | Quest state in `sd.state` for shared-hub sessions; progress in `sd.storage` per player |
| **Replay & Ghost** | Record runs, race your ghost | ~25% | determinism (rng + input capture), ghost puppet (clone seam helps), storage | Ghost is presentation-only — replays cleanly beside live MP |

---

## 5. Suggested build order

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

## 6. Open questions

- **Authority migration:** if the authority peer leaves mid-run, does mod simulation state
  (`sd.state`, filter ownership, AI brains) migrate? Punt (end run) vs. handoff protocol.
- **Determinism audit scope:** what native systems consume `kNativeGlobalRngStateGlobal`
  outside runs (menu shuffles?) — matters for Trials/Replay fidelity.
- **Trust tiers:** `has_capability` exists; when distribution arrives, which classes gate
  on capabilities (raw `sd.debug` memory writes vs. blessed simulation APIs), and does the
  full `luaL_openlibs` surface narrow for untrusted mods?
- **Presentation divergence policy:** may peers run different presentation-only mods in
  the same session (likely yes), and how does the parity handshake classify a mod as
  presentation-only (manifest declaration + API-class enforcement)?
