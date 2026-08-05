# Solomon Dark — Browser Rebuild Roadmap

Status: ACTIVE (owner-approved 2026-08-04). Owner context: the game is abandonware and the
original developers have approved this project; before public launch (P5) the owner re-confirms
that blessing in writing for a full rebuild that redistributes assets from solomondarker.com.

This document is written to be executed by a single capable agent (or a fleet run phase-by-phase)
without re-deriving context. Every claim points at the repo artifact that carries it. Read the
**Execution guide** at the bottom before starting any phase.

---

## 1. Mission

Rebuild Solomon Dark as a browser game served from solomondarker.com:

- Faithful to the retail sim — same movement feel, damage numbers, wave pacing, content.
- Multiplayer-native from day one — server-authoritative, no retail-binary seam fighting.
- Mods are first-class — the existing `sd.*` Lua seam contracts become the mod API of the
  rebuild, so today's mods (minimap, bot-brain, hud showcase) port with minimal change.
- Original assets and data, not recreations — sprites, boneyards, waves, recipes, scripts all
  load from the shipped formats we have already reversed.

## 2. Strategy (decided)

**Clean-room TypeScript engine + original data, conformance-driven.** We reimplement the sim in
TS against golden values and traces recorded from the native game, using our 335+ static RE
contracts and the docs below as the spec. Rendering is WebGL2; the authoritative server is Node
sharing the same sim core; transport is WebSocket.

**Rejected: Win32-in-WASM emulation** (Boxedwine-class). It would get pixels on screen sooner
but fights us on everything we actually care about: mod runtime, netcode authority, audio,
performance ceilings, and site integration. Keep as a last-resort fallback only.

**Determinism is the foundation.** The shared sim core runs a fixed tick with an explicit RNG;
client prediction and server authority replay the same code. Gap G1 pins the native tick graph
and RNG so our determinism matches the retail sim's observable behavior.

## 3. What we already have (verified paths)

### Content & data (complete, tooled)
| Capability | Artifacts |
| --- | --- |
| Sprite/art extraction (.bundle) | `tools/extract_bundles.py`, `tools/build_lua_sprite_bundle.py`, `docs/reverse-engineering/native-asset-system.md` |
| Boneyard format + scripting (byte-exact decode) | `tools/decode_boneyard_scripts.py`, `docs/reverse-engineering/boneyard-scripting.md`, `boneyard-authoring-format.md`, `boneyard-system.md`, `native-boneyards-and-world.md`, `native-default-boneyard-load-seed-and-decor.md` |
| Waves | `data/wave.txt` format + website wave editor/validator (already renders on canvas), `docs/wave-scaling-re.md` |
| Recipe stores (Monster 42-field, Item, NPC, ItemSet, UIDGroup) | byscript campaign: `docs/reverse-engineering/boneyard-scripting.md` + evidence `D:\codex-evidence\byscript-20260803\REPORT.md` |
| Native catalogs (classes, enemies, items, skills, audio, factories, methods, content) | `tools/build_native_*_catalog.py`, `tools/build_native_method_index.py` |
| Nav grids | `tools/export_nav_grid_overlay.py`, `tools/export_nav_grid_png.py`, `docs/pathfinding-investigation.md` |

### Sim knowledge (docs; confidence noted)
| Subsystem | Artifacts | Confidence |
| --- | --- | --- |
| Element damage (golden numbers, all four + frost) | `docs/reverse-engineering/multiplayer-element-damage-2026-07-26.md`, `earth-boulder-damage-formula-2026-07-27.md`, `multiplayer-fireball-contact-2026-07-26.md`, `multiplayer-frost-channel-stop-2026-07-26.md`, `multiplayer-earth-charge-baseline-2026-07-26.md`, `multiplayer-primary-projectile-materialization-2026-07-26.md` | HIGH (live-verified) |
| Timing/tick scale | `docs/reverse-engineering/game-timing-scale.md`; known cadences: 67 ms run-world motion (botmana), 250 ms mana regen (2.5 MP steps) | MEDIUM → G1 |
| Movement | actor speed scalar/vector model (speed at `actor+0x218` × direction `+0x158/+0x15C`), `movement_collision_test_circle_placement` native test, `tools/analyze_movement_speed_timeline.py`, `docs/bugs/player-speed-rush-accumulation-2026-08-01.md` | MEDIUM → G1 |
| Skills/disciplines | `docs/re/skills-concentration-discipline.md`, `docs/re/skillfix-discipline-and-concentration-2026-08-02.md`, `docs/skill-picker-re.md`, `tools/build_native_skill_catalog.py` | MEDIUM-HIGH → G6 for per-skill effects |
| Enemies & targeting | `docs/reverse-engineering/native-enemies.md`, `native-enemy-target-acquisition.md`, `docs/skeleton-death-effects-re.md`, botmana/botwaves bug docs under `docs/bugs/` | MEDIUM → G3 for behavior interpreter |
| Items/equipment/loot | `docs/reverse-engineering/native-items-equipment-and-loot.md` (orb/gold/item/powerup families, magnet behavior) | MEDIUM-HIGH → G7 for stock selector rates |
| Rendering/animation | `docs/wizard-render-animation-deep-dive.md`, `docs/re/world-sprite-render-pipeline.md`, `docs/reverse-engineering/native-camera-control.md`, `docs/main-menu-solomon-visual-re.md`, `docs/ui-binary-map.md`, `docs/ui-engine-system-map.md`, `docs/overlay-visuals-review.md` | MEDIUM-HIGH → G4 for full state machines |
| Audio | `docs/reverse-engineering/native-audio-system.md`, `native-audio-engine-2026-07-26.md`, `tools/build_native_audio_catalog.py` | MEDIUM → G5 for event census |
| Game flow (run intro, game over, hub) | `docs/solomon-run-intro-investigation.md`, `docs/reverse-engineering/native-game-over-session-semantics.md`, `docs/re/tutorial-mechanics.md`, `docs/re/map-picker.md`, dig: `docs/design/dig-npc-movement-lock-2026-07-28.md` | MEDIUM → G8 |
| Multiplayer semantics (ours, reusable as-is) | `docs/networking/world-sync-authority-plan.md`, `session-lifecycle.md`, `netcode-review.md`, `docs/multiplayer-participant-model.md`, protocol v92 scene-epoch model (`docs/bugs/allyvis-player-visual-epoch-parity.md`) | HIGH (we designed it) |
| Mod API spec (the seam to preserve) | `docs/lua-*.md` suite at docs root (spells, waves, world-rendering, ui-authoring, settings, rng, scene, state-and-events, storage, time/timer, net, sprites, resource-filters…) + `docs/lua-seam-roadmap.md` | HIGH (it is our own contract) |
| Bots (port to server-side players) | `mods/bot-brain/`, `docs/design/lua-bot-players-2026-07-26.md`, `docs/design/ml-bot-policy-contract.md`, `docs/ml-bot*.md`, `models/` | HIGH |

### Infrastructure
- Website backend + listings + editors: `api/` (deployed as `solomon-dark-revived` on the NFO box;
  solomondarker.com). Mod publication protocol: `docs/bugs/modpipe-publication-contract-2026-08-01.md`.
- Test regime: `tests/re/` (static contracts — the conformance seed corpus), `tests/lua/`,
  `tests/native/`, `tests/launcher-contracts/`, `tests/fixtures/`.
- Fleet playbook: `~/codex-fleet/20260723/` (dispatch, verification bars, floors).

## 4. Gap register (RE campaigns; each lands docs + goldens + contracts on main)

Every gap campaign has the same deliverable shape, so its output is directly consumable by the
implementing agent:
1. A doc under `docs/reverse-engineering/` with exact semantics, constants, and address citations.
2. Machine-readable goldens under `tests/fixtures/webgame/` (JSON; live-recorded from the native
   game — never hand-typed).
3. New static RE contracts pinning the claims (floors only ever go up).

| Gap | Campaign | Scope | Status |
| --- | --- | --- | --- |
| G1 sim core: movement integrator, tick graph, RNG | **physre** | Input→intent→velocity→position pipeline with exact constants (base speeds, diagonal handling, knockback, wall response via `movement_collision_test_circle_placement`); the full tick graph (which systems at which cadence, in what order — reconcile 67 ms motion + 250 ms mana + render frames against `game-timing-scale.md`); native RNG algorithm, state, seeding, per-system streams, gameplay call-site census. Goldens: per-tick position traces for scripted inputs; RNG streams. | DISPATCHED 2026-08-04 |
| G2 projectile/spell mechanics | **spellre** | Per element (+frost channel): spawn origin/offset, velocity, collision radius, lifetime, contact cadence, pierce/residual semantics, earth charge curve, channel mechanics; damage APPLICATION path cross-referenced to the existing damage docs (do not re-derive numbers); presentation hooks (sprite ids/frame cadence) sufficient for visual parity. Goldens: per-tick projectile trajectories per element/rank incl. ≥3 earth charge levels; contact events. | DISPATCHED 2026-08-04 |
| G3 enemy behavior interpreter | monre | MonsterRecipe 42-field semantics → behavior state machine (approach, attack cadence, specials, spawners); skeleton family first, then full census via `build_native_enemy_catalog.py`. Goldens: enemy movement/attack traces vs a stationary and a moving target. | QUEUED (dispatch when a fleet slot frees) |
| G4 animation & presentation state machines | animre | Wizard + enemy sprite state transitions (idle/walk/cast/hit/death), frame timings, attachment points (staff orb type 7004), z/sort rules (`world-sprite-render-pipeline.md` + `sort_bias`), lighting/shadow model, camera constants (`native-camera-control.md`). Goldens: frame-by-frame animation captures with timestamps. | QUEUED |
| G5 audio event census | audiore | Trigger→sound mapping for gameplay events (cast, hit, death, pickup, waves, UI), asset format/loop points, building on `native-audio-system.md` + audio catalog. | QUEUED |
| G6 progression & per-skill effects | progre | XP/level curves, level-up offer pools, exact effect semantics per skill (incl. Firewalker hoard `+0x740` model from botmana), discipline modifiers. | QUEUED |
| G7 stock loot/reward selector | lootre | Drop-rate tables, gold amounts, potion selection, magnet physics constants; builds on `native-items-equipment-and-loot.md` + potiondrop findings. | QUEUED |
| G8 hub interactions & dig minigame | hubre | NPC talk flows, shop (Useful Thyngs), dig mechanics/timers (`sd.hub.get_solomon_dig_state` semantics already exposed), run entry/portal flow. | QUEUED |
| G9 retail HUD spec | uire | Pixel-accurate HUD layout/behavior census from `ui-binary-map.md`/`ui-engine-system-map.md` (healthbar append ABI already known from allyvis). | QUEUED |
| G10 saves/accounts | savere | Save format, account linkage (launcher Settings owns saves today). Needed only by P5. | QUEUED |

## 5. Conformance strategy (how we know the port is faithful)

Three tiers, all runnable in CI:

- **T1 — ported contracts.** The `tests/re/` static contracts that assert data/semantic facts
  (recipe fields, catalog shapes, formulas) get TS twins in `webgame/conformance/`. Same
  assertions, same numbers.
- **T2 — golden fixtures.** Every gap campaign lands JSON goldens in `tests/fixtures/webgame/`.
  The TS sim replays fixture inputs and must match outputs exactly (integers) or within epsilon
  (float trajectories; epsilon declared per fixture, justified in the fixture header).
- **T3 — native trace replay.** A loader-side **recorder** (P1 work item; rides the existing
  lua-exec/probe seams) captures full input+state timelines from real native runs: per-tick
  inputs, positions, HP/MP, spawns, RNG-visible outcomes. The browser sim replays the input
  track and diffs the state track. Gate: divergence budget per subsystem, tightening per phase.

Never weaken a conformance gate to make a port pass — that is the same rule as the existing
battery (`~/codex-fleet` playbook; material weakenings require an explicit owner QUESTION).

## 6. Architecture

New top-level `webgame/` (own npm workspace, own battery wired into `.github/` CI):

- `webgame/sim/` — deterministic shared core. Fixed tick per G1; explicit seeded RNG; no DOM, no
  wall clock. Entities mirror the native actor model (object_type_id families, tracked_enemy,
  the participant/slot model from `docs/multiplayer-participant-model.md`).
- `webgame/client/` — WebGL2 renderer (atlas batching per G4 z-rules), input, interpolation,
  prediction against server authority, HUD per G9.
- `webgame/server/` — Node authoritative rooms running the same sim core; WebSocket transport;
  scene-epoch lifecycle per the v92 model; lobby/accounts via existing `api/`.
- `webgame/assets/` — build-time pipeline: `extract_bundles.py` output → atlases + manifest;
  boneyards/waves/recipes decoded via existing tools into JSON packs; served by `api/`.
- `webgame/modruntime/` — Lua via WASM (wasmoon) on the server (authoritative) with a
  presentation-class subset in the client, implementing the documented `sd.*` seams
  (`docs/lua-*.md` are the spec). Existing mods are the acceptance suite: minimap and bot-brain
  must run unmodified or with documented deltas.
- `webgame/conformance/` — T1/T2/T3 runners.

Bots: port `mods/bot-brain` server-side as synthetic players (they already speak participant
seams). ML policy (`models/`, `docs/ml-bot*.md`) follows later — same observation contract.

## 7. Phases (each = one fleet wave; land on main behind its gate)

- **P0 — renderer + asset spike.** Asset pipeline emits atlases/manifests from real bundles; hub
  boneyard renders in-browser; camera per `native-camera-control.md`; wizard walks with
  placeholder physics. GATE: side-by-side capture vs native hub judged pixel-plausible; assets
  100% from original bundles. (No sim fidelity claims yet.)
- **P1 — deterministic sim core.** Consume physre+spellre landings: tick graph, integrator, RNG,
  fire projectile. Build the T3 recorder mod. GATE: T2 movement + fire goldens green; first T3
  replay (solo, scripted 60 s run) within divergence budget; determinism proof (same seed+inputs
  → identical state hash, 1000 ticks).
- **P2 — combat parity.** All elements incl. earth charge + frost channel; skeleton family AI
  (monre); waves (wave-scaling-re + botwaves landing); loot (G7); potions incl. invincibility
  semantics (potionvfx/potiondrop docs); death/spectate flow. GATE: T2 all-element damage
  goldens exact; T3 full-arena replays; a human plays it and the owner signs off on feel.
- **P3 — multiplayer.** Server rooms, prediction/reconciliation, scene-epoch lifecycle, ally
  HUD parity (allyvis semantics), bots as server-side players. GATE: 2-human+1-bot browser
  session passes the same acceptance battery style as the native MP campaigns (cross-peer HP
  parity, room transitions, hub returns).
- **P4 — mods + editors.** wasmoon `sd.*` runtime; minimap + bot-brain run; site boneyard/wave
  editors round-trip into live webgame sessions; mod listings serve webgame packages alongside
  loader packages.
- **P5 — launch.** Accounts/saves (G10), perf budget (60 fps mid hardware; measure, don't
  guess), site integration, written dev blessing confirmed by owner, public beta.

## 8. Execution guide for the implementing agent

1. Read this file, then the Confidence table's HIGH rows, then the landed gap docs for the phase
   you are executing. Do not start a phase whose gap campaigns have not landed.
2. Conventions are non-negotiable and identical to the loader project: investigate → document →
   fix; class-closing fixes; no fallback code paths; contracts/goldens never weakened silently;
   every landing = full battery + exact-SHA CI green + evidence dir with checksums; report
   DONE:/QUESTION: sentinels to ATC.
3. WSL-load rule: bulk filesystem work happens Windows-side (`powershell.exe`, `Get-FileHash`,
   `rg.exe`); never recursive scans over `/mnt/c` or `/mnt/d` from WSL.
4. Webgame battery = `webgame` unit tests + T1/T2/T3 conformance + lint/typecheck, wired into
   the same CI workflow; floors ratchet like the existing suite (`~/codex-fleet/20260723/`
   playbook has current floors; they only go up).
5. Live native captures (goldens, T3 traces) use the standard harness
   (`scripts/Launch-LocalSoloSession.ps1` / `Launch-LocalMultiplayerPair.ps1`,
   `SDMOD_DISABLE_AUDIO=1`, isolated ports/instances, exact-PID disposal with proofs).
6. Release-note discipline: webgame ships via the website; loader release notes never mention it.

## 9. Open items / to-confirm

- Owner: written re-confirmation of the original developers' blessing before P5.
- Confirm `api/` deployment mapping (repo → `solomon-dark-revived` on NFO) and where webgame
  static hosting slots in (same box; measure asset weight in P0).
- monre/animre dispatch when fleet slots free (after current bug campaigns land); remaining gap
  campaigns scheduled per phase entry criteria.
