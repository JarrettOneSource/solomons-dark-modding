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
| **Simulation** (mutates shared game state) | `sd.enemies.spawn`, `sd.items.grant`, `sd.world.spawn_reward`, filter outcomes | Executes where the affected entity is simulated (authority for run entities; owning peer for that peer's wizard, per the participant ownership rules). Called from a non-owning peer, the call transparently becomes a request to the owner — generalizing the existing `request_loot_pickup` pattern. Results replicate through the existing snapshot channels. Identical mod code on every peer. |
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

1. **Events are notify-only** — mods can watch the game but not veto or reshape it.
2. **No output channel** — no drawing, no audio, no UI creation from Lua.
3. **No content registration** — overlays retune existing skills/items/waves, but new
   content with *scripted behavior* is impossible without native code.
4. **No blessed persistence or cross-mod contract.** Replicated run state now has the
   `sd.state`/broadcast seam; profile persistence and local mod-to-mod contracts remain.

### Known sharp edges (fix as part of the relevant seam)

- `sd.world.spawn_enemy` freeze = call-shape mismatch in `Enemy_Create` (hardcoded
  `nullptr,0,0,0,0`) — the enemy-spawn seam must build the correct call, not work around it.
- Enemies only target gameplay-slot (1–3) actors; standalone bots are invisible to hostile
  AI. The `sd.ai` targeting seam is where this gets fixed foundationally.
- Promoting standalone bots via `HookMonsterPathfindingRefreshTarget` hangs the
  pathfinder — enemy AI needs its own seam, not that hook.

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
- `sd.spells.register{key, cfg, on_cast, on_tick, on_hit}` — allocate an ID, integrate the
  skill picker (`skill-picker-re.md` maps the UI), route cast dispatch into Lua, compose
  native effect primitives (`kFireEmberCtor`, `kSpellActionBuilder`/`kSpellBuilderReset`/
  `kSpellBuilderFinalize`, projectile-group gates already patched for bot casting).
  Data side is proven by `skill_shock_nova`; the missing piece is scripted behavior.
- `sd.enemies.spawn(key, {hp, speed, scale, loot})` — fix the `Enemy_Create` call shape;
  stat overrides on top.
- `sd.items.register` / `sd.items.grant(recipe_uid, color_state)` —
  `kInventoryInsertOrStackItem`, `kItemRecipeClone`, recipe table globals.
*Unlocks:* new-content packs — the ecosystem's lifeblood.
*Multiplayer:* content IDs from `hash(mod_id, key)`; spell behaviors run on the
simulation owner, effect transforms replicate. Work item: a **generic modded-effect
replication channel** (today's channels are per-native-type: ember, firewalker).

**5. `sd.ai` — enemy brain overrides.**
Per-enemy move goals (`kGameNpcSetMoveGoal`), target override (fixes the slot-1–3
targeting limitation foundationally, replacing the pathfinder-hang dead end), `on_think`
callbacks, formalized nav/collision queries.
*Unlocks:* scripted bosses, invasions, enemies that fight bots, encounter design.
*Multiplayer:* runs on the authority (enemies are authority-simulated); clients receive
replicated movement — mod AI code never runs on clients.

### Tier 2 — ecosystem infrastructure

**6. `sd.storage` — scoped persistence.** Per-mod, per-profile KV/JSON under
`.sdmod/storage/<mod-id>/`. Replaces ad-hoc `io.*`; prerequisite for sandboxed trust
tiers when distribution arrives. *MP:* local (per player). Shared-run state belongs in
`sd.state`; the API docs draw that line explicitly.

**7. `sd.audio` — BASS bindings.** The game ships `bass.dll`; bind sample/stream
play/stop/volume. *Unlocks:* stingers, custom music, voice packs. *MP:* presentation-local;
synchronized cues = replicated event + local playback.

**8. `sd.ui` authoring.** Create surfaces/panels/buttons/labels through the game's UI
engine (`ui-engine-system-map.md`); reuse the semantic action layer for input. *Unlocks:*
mod settings screens, dialogue choices, custom shops, quest logs. *MP:* presentation-local;
action handlers that mutate shared state are simulation-class and auto-route.

**9. `sd.timer` + coroutine scheduler.** `after(ms, fn)`, `every(ms, fn)`, `sequence{}`
sugar over `runtime.tick` (every mod hand-rolls this today). *MP:* local; docs steer
simulation decisions into filters/authority hooks.

**10. `sd.bus` — cross-mod contracts.** Publish/subscribe across loaded mods plus
`provides`/`requires` in `manifest.json`. *Unlocks:* framework mods (quest engine, UI kit)
that content mods build on — the compounding mechanism of a real ecosystem. *MP:* local
dispatch; a bus message that must reach all peers is just `sd.events.broadcast`.

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

### Tier 3 — nearly-free power-ups and polish

- **`sd.time.set_scale()`** — `kGameTimingScaleGlobal` is resolved; slow-mo, pause,
  frame-step. *MP:* shared-simulation variable → authority-gated + replicated (or
  refused in sessions).
- **`sd.rng.set_seed()`** — `kNativeRngInitialize` + `kNativeGlobalRngStateGlobal`;
  daily challenges, practice, replays. *MP:* authority seeds, seed replicates at run start.
- **`sd.nav`** — promote `get_nav_grid` + native `movement_collision_test_circle_placement`
  bridge out of `sd.debug` into a blessed pathfinding/LOS API (native collision test is
  already the required path — make it the easy one). *MP:* read-only, safe everywhere.
- **`sd.scene`** — region/level switching (`kGameplaySwitchRegion`, transition globals)
  paired with `.boneyard` overlays. *MP:* authority-routed; scene epochs already replicate.
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
| **Solomon's Trials** | Daily seeded challenge + leaderboard on the existing Website backend | ~55% | `sd.rng`, `sd.storage`, submit contract (offer control exists: `choose_level_up_option`) | Authority seeds the run; co-op daily boards become possible |
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
- **Generic modded-effect replication:** schema for effect transforms/lifecycle generic
  enough for arbitrary Lua spells (today's channels are per-native-type: ember, firewalker).
- **Determinism audit scope:** what native systems consume `kNativeGlobalRngStateGlobal`
  outside runs (menu shuffles?) — matters for Trials/Replay fidelity.
- **Trust tiers:** `has_capability` exists; when distribution arrives, which classes gate
  on capabilities (raw `sd.debug` memory writes vs. blessed simulation APIs), and does the
  full `luaL_openlibs` surface narrow for untrusted mods?
- **Presentation divergence policy:** may peers run different presentation-only mods in
  the same session (likely yes), and how does the parity handshake classify a mod as
  presentation-only (manifest declaration + API-class enforcement)?
