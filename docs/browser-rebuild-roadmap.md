# Solomon Dark — Browser Rebuild Roadmap

Status: ACTIVE (owner-approved 2026-08-04). Owner context: the game is abandonware and the
original developers have approved this project; before public launch the owner re-confirms
that blessing in writing for a full rebuild that redistributes assets from solomondarker.com.

This document is written to be executed by a single capable agent (or a fleet run phase-by-phase)
without re-deriving context. Every claim points at the repo artifact that carries it. Read the
**Execution guide** at the bottom before starting any phase.

---

## 1. Mission

Rebuild Solomon Dark as a game that runs in a browser, as a standalone app you own, and on a
dedicated server anyone can host:

- Faithful to the retail sim — same movement feel, damage numbers, wave pacing, content.
- Multiplayer-native from day one — server-authoritative, no retail-binary seam fighting.
- Playable on a controller and on a Steam Deck, not only mouse and keyboard (§4).
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

## 3. Distribution: one game, three shapes

There is exactly one sim and exactly one server implementation. The only thing that differs
between the three ways to play is **where the authoritative server runs**. This is not a
convenience — it is the load-bearing decision of the whole project. The moment "offline mode"
becomes a second code path, the two implementations stop agreeing and the conformance goldens
(§7) can only ever prove one of them right.

| Shape | Server location | Transport | Ships as |
| --- | --- | --- | --- |
| In the browser | a Web Worker in the tab | `postMessage` | solomondarker.com `/game` |
| Standalone offline | a Web Worker in the app shell | `postMessage` | desktop + Steam Deck app |
| Dedicated | a host someone runs | WebSocket | Node server package |

Consequences the implementing agent must honor:

- **Single-player is not a mode.** It is a one-participant session whose empty seats are filled
  with bots, which the framework already models as synthetic remote players
  (`docs/design/lua-bot-players-2026-07-26.md`, `docs/multiplayer-participant-model.md`).
  Solo, co-op, and dedicated run identical code paths.
- **The sim must be pure.** No DOM, no wall clock, no `Math.random`, no direct I/O — only the
  seeded RNG stream that G1 pins. Determinism requires this anyway; it is what makes the
  in-process server free.
- **The website is never a dependency of gameplay.** The standalone build must run with the
  network cable unplugged and solomondarker.com gone. Accounts/listings degrade; play does not.
- The seam is already declared on the website: `frontend/src/game/engine.ts` (the `Transport`
  union, `bootGame`, `ENGINE_STATUS`, `OFFLINE_BUILD_URL`) behind the unlisted `/game` page. The
  rebuild lands as an implementation of `bootGame` plus flipping `ENGINE_STATUS`; the page needs
  no other change.

### 3.1 Standalone shell

Chromium-based shell (Electron or a Chromium kiosk wrapper) rather than WebKitGTK, because the
renderer is WebGL2 and Deck-class performance is a gate, not a nice-to-have. Targets: Windows x64
and **Linux x86_64** — the Linux target is what makes the Steam Deck a real install rather than a
browser bookmark. The shell hosts the same bundle the website serves; it does not fork it.

## 4. Input model and platform targets (controller + Steam Deck are requirements)

**The sim never sees a device event.** Devices produce an abstract *intent stream*; the sim
consumes only that. Mouse+keyboard and gamepad are two producers of the same stream, and neither
is privileged.

This constraint is not stylistic — it falls out of conformance. T3 (§7) replays **native input
traces** recorded from the retail game. G14 corrected an earlier premise: retail movement is a
keyboard unit vector, not click-to-move; the mouse supplies aim, click-to-cast, and hold/channel
levels. The contract remains more expressive than retail so browser/controller producers can
also request a world movement target without changing the sim boundary:

```
Intent =
  | move({ target: WorldPoint } | { vector: Unit2 }, start | update | stop)
  | aim(WorldPoint)
  | cast(slot, press | hold | release)
  | interact(target, press | release)
  | menu-nav(command, press | release)
```

A gamepad producer synthesizes `aim` from the right stick (`player_pos + stick_dir × reach`) and
`move.vector` from the left stick. The native mouse producer emits cursor `aim` and cast phases,
but no move; a browser point-movement scheme may emit `move.target`. All land in the same union,
so native traces stay replayable and the controller is not a translation layer bolted on
afterwards. The normative contract and mapping are in
`docs/reverse-engineering/native-input-model.md` and
`webgame-contracts/intent-schema.json`.

**Decided (owner, 2026-08-04): twin-stick.** Not a virtual cursor. The intent contract above
still expresses both, because it has to — native traces are cursor-shaped and must stay
replayable — but twin-stick is what we build and what the phase gates test.

### 4.2 The twin-stick mapping (decided; implement exactly this)

| Control | Intent | Notes |
| --- | --- | --- |
| Left stick | `move.vector` | Radial deadzone, re-normalized between the inner and outer edge so slow walking is reachable. Mouse emits `move.target` instead; both are first-class |
| Right stick | `aim` = `aim_anchor + normalize(stick) × reach` | `reach` is derived, not chosen: compute it in P0 from the screen→world transform G14 documents, so the aim point lands inside the visible play area at default zoom. Record the number and its derivation alongside the input producer. **`aim_anchor` is not `player_pos`** — retail anchors mouse aim at `project(player) + (0, -25)` screen pixels (`0x007DE960`, see G14); the stick must use the same anchor or stick and mouse aim disagree by up to `1.9 deg` |
| Right stick released | aim **holds its last direction** | No auto-aim toward movement. Kiting — retreating while firing backwards — is core to the game, and snapping aim to the move vector makes it impossible |
| Right trigger | `cast{slot: primary, phase: press → hold → release}` | Maps one-to-one onto native click-hold: holding charges earth, releasing fires. No new semantics needed |
| Face buttons | `cast{slot: N, …}` | Slot binding follows the HUD's own slot order (G9) |
| South button | `interact` | Talk to NPCs, use the shop, enter a portal |
| D-pad / left stick | `menu-nav` | Both drive menu focus; the focus model is G11's |
| East button | menu back / cancel | Same verb everywhere, including modals |
| Start | pause | |

**Aim assist is a producer-side transform, never a sim rule.** A stick cannot match pixel-precise
mouse aim, so some magnetism is likely wanted — but it must be applied inside
`webgame/input/` while computing `aim`, *before* the intent reaches the sim. Put it in the sim
and it silently rewrites every golden and every replayed trace. Tune it as a client setting;
conformance never sees it.

Deck extras that cost us nothing: its trackpads can drive a mouse-shaped producer through Steam
Input if a player prefers that, and gyro fine-aim is a plausible later addition — both are Steam
Input configuration on top of the same two producers, not new code paths.
### 4.1 Steam Deck target (gates, measured — never assumed)

| Concern | Requirement |
| --- | --- |
| Build | Linux x86_64 standalone (§3.1), installable as a Steam or non-Steam title |
| Display | 1280×800, 16:10, 7" — UI scales by *readability*, not naive pixel scaling; minimum text sizes and safe areas declared in G11 and G9 |
| Controls | The Deck presents as a standard gamepad through Steam Input, and the browser Gamepad API sees it as such. No Deck-specific input code |
| Text entry | Server address, player name, chat MUST be real focusable `<input>` elements so the Deck on-screen keyboard appears. Canvas-drawn text fields are forbidden |
| Suspend/resume | Sessions survive suspend: local pauses cleanly, remote reconnects on resume. Not a crash, not a silent desync |
| Performance | 60 fps at 1280×800 on Deck-class hardware, measured on device. Frame budget is a gate at P0 and re-measured every phase |
| Haptics | Rumble via the Gamepad API `vibrationActuator` wherever the native game had feedback |

**Every menu is fully operable with a D-pad and face buttons, with no cursor.** That requires an
explicit focus model — focus order, default focus per screen, wrap behavior, back-button
semantics — which is why G11 (menus) is documented *before* anything is built. Retrofitting focus
navigation onto screens designed around a mouse is a rewrite, not a patch.

## 5. What we already have (verified paths)

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
| Timing/tick scale | `docs/reverse-engineering/game-timing-scale.md`, `docs/reverse-engineering/native-movement-and-tick.md`; native 100 Hz fixed tick and render/service cadence graph pinned by live goldens and static contracts | HIGH (G1 closed) |
| Movement | `docs/reverse-engineering/native-movement-and-tick.md`, live `tests/fixtures/webgame/movement-goldens.json`, `movement_collision_test_circle_placement`, `tools/analyze_movement_speed_timeline.py`, `docs/bugs/player-speed-rush-accumulation-2026-08-01.md` | HIGH (G1 closed; live-verified) |
| Skills/disciplines | `docs/re/skills-concentration-discipline.md`, `docs/re/skillfix-discipline-and-concentration-2026-08-02.md`, `docs/skill-picker-re.md`, `tools/build_native_skill_catalog.py` | MEDIUM-HIGH → G6 for per-skill effects |
| Enemies & targeting | `docs/reverse-engineering/native-enemies.md`, `native-enemy-target-acquisition.md`, `docs/skeleton-death-effects-re.md`, botmana/botwaves bug docs under `docs/bugs/` | MEDIUM → G3 for behavior interpreter |
| Items/equipment/loot | `docs/reverse-engineering/native-items-equipment-and-loot.md` (definitions/layouts) plus `docs/reverse-engineering/native-loot-selector.md`, live `tests/fixtures/webgame/loot-goldens.json`, and registered static contracts (actor-private seed lifecycle, exact selector/amount tables, pickup physics/lifetimes, host authority) | HIGH (G7 closed; live-verified) |
| Rendering/animation | `docs/wizard-render-animation-deep-dive.md`, `docs/re/world-sprite-render-pipeline.md`, `docs/reverse-engineering/native-camera-control.md`, `docs/main-menu-solomon-visual-re.md`, `docs/ui-binary-map.md`, `docs/ui-engine-system-map.md`, `docs/overlay-visuals-review.md` | MEDIUM-HIGH → G4 for animation state, G12 for scene composition |
| Audio | `docs/reverse-engineering/native-audio-system.md`, `native-audio-engine-2026-07-26.md`, `tools/build_native_audio_catalog.py` | MEDIUM → G5 for event census |
| Menus & shell | `docs/reverse-engineering/native-menus-and-boot.md`, live `tests/fixtures/webgame/menu-goldens.json` and reference captures, `webgame-contracts/menu-focus-model.json`, plus the earlier picker/UI/uigate notes | HIGH — G11 closed with boot/loading evidence, a 28-layout census, a 39-edge live graph, and a designed controller focus model |
| Game flow (run intro, game over, hub) | `docs/solomon-run-intro-investigation.md`, `docs/reverse-engineering/native-game-over-session-semantics.md`, `docs/re/tutorial-mechanics.md`, `docs/re/map-picker.md`, dig: `docs/design/dig-npc-movement-lock-2026-07-28.md` | MEDIUM → G8, G13 |
| Multiplayer semantics (ours, reusable as-is) | `docs/networking/world-sync-authority-plan.md`, `session-lifecycle.md`, `netcode-review.md`, `docs/multiplayer-participant-model.md`, protocol v92 scene-epoch model (`docs/bugs/allyvis-player-visual-epoch-parity.md`) | HIGH (we designed it) |
| Mod API spec (the seam to preserve) | `docs/lua-*.md` suite at docs root (spells, waves, world-rendering, ui-authoring, settings, rng, scene, state-and-events, storage, time/timer, net, sprites, resource-filters…) + `docs/lua-seam-roadmap.md` | HIGH (it is our own contract) |
| Bots (port to server-side players) | `mods/bot-brain/`, `docs/design/lua-bot-players-2026-07-26.md`, `docs/design/ml-bot-policy-contract.md`, `docs/ml-bot*.md`, `models/` | HIGH |
| Input model | none — the loader drives native input, but it has never been censused as a contract | NONE → G14 |

### Infrastructure
- Website backend + listings + editors: `api/` (deployed as `solomon-dark-revived` on the NFO box;
  solomondarker.com). Mod publication protocol: `docs/bugs/modpipe-publication-contract-2026-08-01.md`.
- Website game seam: `frontend/src/game/engine.ts` plus the unlisted `/game` page.
- Test regime: `tests/re/` (static contracts — the conformance seed corpus), `tests/lua/`,
  `tests/native/`, `tests/launcher-contracts/`, `tests/fixtures/`.
- Fleet playbook: `~/codex-fleet/20260723/` (dispatch, verification bars, floors).

## 6. Gap register (RE campaigns; each lands docs + goldens + contracts on main)

Every gap campaign has the same deliverable shape, so its output is directly consumable by the
implementing agent:
1. A doc under `docs/reverse-engineering/` with exact semantics, constants, and address citations.
2. Machine-readable goldens under `tests/fixtures/webgame/` (JSON; live-recorded from the native
   game — never hand-typed).
3. New static RE contracts pinning the claims (floors only ever go up).

Gap IDs are stable and are never renumbered — dispatched campaigns cite them. The **tiers** below
are the execution order, set by the owner on 2026-08-04: menus first, then hub, then in-run. G1
and G2 were dispatched before that reordering; G1 remains in flight and G2 is now closed.
Everything else follows tier order.

### Tier A — shell and menus (first)

| Gap | Campaign | Scope | Status |
| --- | --- | --- | --- |
| G14 input contract | **inputre** | Census the native input model as a contract: what a click actually means at each surface (world move vs. cast vs. UI), hold/charge semantics and their thresholds, key bindings, modifier behavior, the input seal during loading (uigate), and how input routes between HUD, menus, and world. Deliver the abstract `Intent` schema of §4 plus a proof that it losslessly encodes a recorded native mouse session. Goldens: recorded native input traces and their intent-stream encodings, round-trip exact. | **DONE** — `docs/reverse-engineering/native-input-model.md`, `webgame-contracts/intent-schema.json`, and live `tests/fixtures/webgame/input-goldens.json` |
| G11 boot, splash, loading & menus | **menure** | The whole pre-gameplay shell: boot sequence and its ordering; splash/attract screens; loading screens (progress source, minimum display time, what is legal to do during them); title/main menu; every submenu reachable from it (options/settings, profile & save select, class/loadout, skill picker, map/boneyard picker, pause, game over); per-screen layout with exact art, fonts, and positions; transitions between screens; and the **focus/navigation model** §4 requires (focus order, default focus, wrap, back semantics) — the native game is mouse-driven, so where no focus order exists natively, define one and mark it designed-not-observed. Goldens: per-screen layout captures plus a navigation-graph fixture. | **DONE** — `docs/reverse-engineering/native-menus-and-boot.md`, live `tests/fixtures/webgame/menu-goldens.json` plus per-screen references, and `webgame-contracts/menu-focus-model.json` |

**Rule for G11 (splash).** The owner confirmed on 2026-08-04 that the original developers'
blessing covers the Raptisoft logo, so the splash is reversed **and shipped** — placement,
timing, and asset reproduced faithfully like any other screen. One consequence to carry through:
the website footer's "not affiliated with Raptisoft" disclaimer and the shipped logo now say
different things, so the site's wording gets revisited at launch (§11) rather than left to
contradict the game.

### Tier B — hub and world presentation (second)

| Gap | Campaign | Scope | Status |
| --- | --- | --- | --- |
| G12 scene composition | **rendre** | How the game builds a scene's visuals out of art: layer order and what occupies each layer, atlas/sprite selection, parallax and backdrop assembly, decor placement and seeding, the fog/lighting/tint model, sort rules (`world-sprite-render-pipeline.md` + `sort_bias`), and the camera's relationship to all of it. This is the spec the renderer is written against — G4 covers *animation state*, this covers *how a frame is assembled*. Goldens: scene composition dumps (ordered draw lists with sprite ids and transforms) for the hub and one boneyard. | **DONE 2026-08-05** — [composition contract](reverse-engineering/native-scene-composition.md), [live hub/Boneyard draw-list goldens](../tests/fixtures/webgame/scene-composition-goldens.json), and four registered static RE contracts. |
| G8 hub, traders & dig | **hubre** | Hub world contents and layout; every NPC and its talk flow; the **shop economy** (Useful Thyngs): inventory tables, pricing, what restocks and when, currency sinks, what persists across runs; dig mechanics and timers (`sd.hub.get_solomon_dig_state` semantics already exposed); run entry / portal flow. Goldens: shop inventory and price tables, dig timing traces. **Inherits the open G1 seeding-lifecycle residual:** any rolled inventory is only reproducible if the seed that drives it is, and that is currently unverified — capture the seed source per roll rather than assuming `sd.rng.set_seed` is authoritative. | **DONE 2026-08-05** — [hub and economy contract](reverse-engineering/native-hub-and-economy.md), [live hub/economy goldens](../tests/fixtures/webgame/hub-economy-goldens.json), and four registered static RE contracts. Rolled stock remains tick-seed dependent, so a port must carry the generator state explicitly. |
| G13 flow & room transitions | **flowre** | The application/room state machine end to end: boot → splash → menu → hub → run entry → room → room transition → run end → hub. Per transition: what tears down, what persists, load ordering, the barrier/handshake (the loading-Boneyard barrier semantics from lobby-lifecycle), fade/wipe presentation and its timing, and the failure/abort paths. Goldens: transition traces with timings and per-phase state assertions. | **DONE 2026-08-05** — [native session-flow contract](reverse-engineering/native-session-flow.md), [live full-session timeline and 23-edge graph](../tests/fixtures/webgame/session-flow-goldens.json), and four registered static RE contracts. |

### Tier C — in-run (third)

| Gap | Campaign | Scope | Status |
| --- | --- | --- | --- |
| G1 sim core: movement integrator, tick graph, RNG | **physre** | Input→intent→velocity→position pipeline with exact constants (base speeds, diagonal handling, knockback, wall response via `movement_collision_test_circle_placement`); the full tick graph (which systems at which cadence, in what order — reconcile 67 ms motion + 250 ms mana + render frames against `game-timing-scale.md`); native RNG algorithm, state, seeding, per-system streams, gameplay call-site census. | **CLOSED 2026-08-04** — [movement, tick, and RNG mechanics](reverse-engineering/native-movement-and-tick.md), [live movement goldens](../tests/fixtures/webgame/movement-goldens.json), [live RNG goldens](../tests/fixtures/webgame/rng-goldens.json), [live float RNG goldens](../tests/fixtures/webgame/float-rng-goldens.json), [integer/mechanism contracts](../tests/re/static_re_native_sim_core_contracts.py), and [float golden contracts](../tests/re/static_re_native_float_rng_golden_contracts.py). **ATC re-audit 2026-08-05:** the generator itself is portable and re-derived bit-exactly from prose (352 outputs, 55/55 state words, 4 seed/range pairs). The **seeding lifecycle is now closed**: `seed = App[+0x28] * 0xEF3` at twelve byte-verified sites, `App+0x28` counts unpaused app ticks (`App::vftable` slot 8 = the inherited base tick `0x00427800`), and the recorded snapshot's `5683095` factors exactly as `1485 * 0xEF3`. **This is a portability constraint, not a solved problem:** native streams key off elapsed ticks at level construction, so a port cannot reproduce world generation, trader stock, or drops from game state alone and must carry the tick count as explicit state. **Float golden residual closed 2026-08-05:** the live corpus records 1,284 exact float32 draws from both retail primitives, including 256-draw scaled sequences at magnitudes `1`, `3`, and `4.5`, both unit-primitive sign modes, and both endpoints. Independent replay pins all three scaled rounding points, the signed two-word stream cost, and the per-object divisor at `this+0xE4`. The recorder-only residual is closed and no longer blocks rolled-system ports. |
| G2 projectile/spell mechanics | **spellre** | Per element (+frost channel): spawn origin/offset, velocity, collision radius, lifetime, contact cadence, pierce/residual semantics, earth charge curve, channel mechanics; damage APPLICATION path cross-referenced to the existing damage docs (do not re-derive numbers); presentation hooks (sprite ids/frame cadence) sufficient for visual parity. Goldens: per-tick projectile trajectories per element/rank incl. ≥3 earth charge levels; contact events. | **DONE 2026-08-04** — [mechanics](reverse-engineering/native-projectile-and-spell-mechanics.md), [live goldens](../tests/fixtures/webgame/projectile-goldens.json), and static RE contracts. **Emitter closed by ATC 2026-08-05:** the cast glyph origin is no longer a single back-solved facing. Index arithmetic is read from `0x0053B830` (`facing = ((int)heading + 7)/15` with one conditional `-24`; `index = facing + 24*K`), the point table is records `#3244..#3483` of `images/Clothes.bundle` (10 × 24, point index 1), and the element locals are PE `double` constants. Replay resolves all four projectile spawns and 1137/1137 held Earth samples exactly. All 24 facings are recoverable; only facing `19` is golden-confirmed. |
| G3 enemy behavior interpreter | monre | MonsterRecipe 42-field semantics → behavior state machine (approach, attack cadence, specials, spawners); skeleton family first, then full census via `build_native_enemy_catalog.py`. Goldens: enemy movement/attack traces vs a stationary and a moving target. | **DONE 2026-08-05** — [behavior interpreter](reverse-engineering/native-enemy-behavior.md), [eight live stationary/moving traces](../tests/fixtures/webgame/enemy-behavior-goldens.json), and three registered static RE contracts. |
| G4 animation & presentation state machines | animre | Wizard + enemy sprite state transitions (idle/walk/cast/hit/death), frame timings, attachment points (staff orb type 7004), lighting/shadow model, camera constants (`native-camera-control.md`). Consumes G12's composition spec. | **CLOSED 2026-08-05** — [animation/presentation contract](reverse-engineering/native-animation-state.md), [live fixed-tick/render animation and all-facing emitter goldens](../tests/fixtures/webgame/animation-goldens.json), and registered static RE contracts. `actor+0x238` is the wizard equipment/body pose selector; Staff Cast 1 is observed as insertion `0`, then RNG branch `1 -> 8 -> 7`, then reset. The apparent `#460..#579` run is wizard bare-hand composition split across the unarmed reference bank and bare-hand attachment array; `#796..#867` is the wand hand-to-tip array. Retail `0x0053B830` is independently observed at every facing `0..23`, plus the heading-359 wrap. |
| G9 retail HUD spec | **uire** | Pixel-accurate HUD layout/behavior census from `ui-binary-map.md`/`ui-engine-system-map.md` (healthbar append ABI already known from allyvis), plus the 16:10 / 1280×800 scaling rules §4.1 requires. | **CLOSED 2026-08-06** — [retail HUD contract](reverse-engineering/native-hud.md), [settle-gated live HUD goldens and reference-crop index](../tests/fixtures/webgame/hud-goldens.json), and registered mutation-tested static RE contracts. The 26-element census pins native geometry, assets, draw order, fills, cooldown/charge behavior, visibility, Deck readability floors, and multiplayer epoch constraints; the naturally configured featured-enemy panel remains explicitly Not Yet Reversed. |
| G5 audio event census | audiore | Trigger→sound mapping for gameplay events (cast, hit, death, pickup, waves, UI), asset format/loop points, building on `native-audio-system.md` + audio catalog. | **CLOSED 2026-08-06** — [audio event census](reverse-engineering/native-audio-events.md), [quiet dispatch-seam goldens](../tests/fixtures/webgame/audio-event-goldens.json), and [registered static contracts](../tests/re/static_re_native_audio_event_contracts.py); the tap is upstream of the disabled mixer/output boundary. |
| G6 progression & per-skill effects | progre | XP/level curves, level-up offer pools, exact effect semantics per skill (incl. the Firewalker hoard `+0x740` model from botmana), discipline modifiers. | QUEUED |
| G7 stock loot/reward selector | lootre | Drop-rate tables, gold amounts, potion selection, magnet physics constants; builds on `native-items-equipment-and-loot.md` + potiondrop findings. **Inherits the open G1 seeding-lifecycle residual** — drops run off an actor-seeded private stream (`0x0047C070`), so record that stream's seed source directly instead of relying on the shared-global determinism claim. | **CLOSED 2026-08-06** — [selector, private seed lifecycle, amounts, sources, physics, lifetimes, and authority](reverse-engineering/native-loot-selector.md), [100-kill/dig/trajectory/credit live goldens](../tests/fixtures/webgame/loot-goldens.json), and registered static RE contracts. Category rolls replay the fresh actor-seeded private stream bit-exactly; materializer draws remain on the active shared stream. |
| G10 saves/accounts | savere | Save format, account linkage (launcher Settings owns saves today). Needed only by launch. | QUEUED |

## 7. Conformance strategy (how we know the port is faithful)

Three tiers, all runnable in CI:

- **T1 — ported contracts.** The `tests/re/` static contracts that assert data/semantic facts
  (recipe fields, catalog shapes, formulas) get TS twins in `webgame/conformance/`. Same
  assertions, same numbers.
- **T2 — golden fixtures.** Every gap campaign lands JSON goldens in `tests/fixtures/webgame/`.
  The TS sim replays fixture inputs and must match outputs exactly (integers) or within epsilon
  (float trajectories; epsilon declared per fixture, justified in the fixture header).
- **T3 — native trace replay.** A loader-side **recorder** (built in P2; rides the existing
  lua-exec/probe seams) captures full input+state timelines from real native runs: per-tick
  inputs, positions, HP/MP, spawns, RNG-visible outcomes. The browser sim replays the input track
  and diffs the state track. Gate: a divergence budget per subsystem, tightening per phase. The
  recorder emits the §4 `Intent` stream, not raw device events — G14 is its prerequisite.

Never weaken a conformance gate to make a port pass — same rule as the existing battery
(`~/codex-fleet` playbook; material weakenings require an explicit owner QUESTION).

## 8. Architecture

New top-level `webgame/` (own npm workspace, own battery wired into `.github/` CI):

- `webgame/sim/` — deterministic shared core. Fixed tick per G1; explicit seeded RNG; no DOM, no
  wall clock. Entities mirror the native actor model (object_type_id families, tracked_enemy, the
  participant/slot model from `docs/multiplayer-participant-model.md`).
- `webgame/input/` — device producers (mouse+keyboard, gamepad) emitting the §4 `Intent` stream,
  plus the focus/navigation model for menus. The only module allowed to know a device exists.
- `webgame/client/` — WebGL2 renderer (atlas batching per G12 composition and G4 z-rules), input
  binding, interpolation, prediction against server authority, HUD per G9.
- `webgame/server/` — Node authoritative rooms running the same sim core; a WebSocket transport
  **and** an in-process worker transport for solo/standalone (§3 — one implementation, two
  bindings); scene-epoch lifecycle per the v92 model; lobby/accounts via the existing `api/`.
- `webgame/shell/` — the standalone desktop/Deck app (§3.1). A packaging target, not a fork.
- `webgame/assets/` — build-time pipeline: `extract_bundles.py` output → atlases + manifest;
  boneyards/waves/recipes decoded via existing tools into JSON packs; served by `api/`.
- `webgame/modruntime/` — Lua via WASM (wasmoon) on the server (authoritative) with a
  presentation-class subset in the client, implementing the documented `sd.*` seams
  (`docs/lua-*.md` are the spec). Existing mods are the acceptance suite: minimap and bot-brain
  must run unmodified or with documented deltas.
- `webgame/conformance/` — T1/T2/T3 runners.

Bots: port `mods/bot-brain` server-side as synthetic players (they already speak participant
seams). ML policy (`models/`, `docs/ml-bot*.md`) follows later — same observation contract.

## 9. Phases (each = one fleet wave; land on main behind its gate)

Ordered as a vertical slice down the player's own path, per the owner's tier order: a navigable,
controller-driven shell before any sim exists, then a walkable hub, then the run.

- **P0 — shell, assets, menus.** Asset pipeline emits atlases/manifests from real bundles. Boot →
  splash → title → settings → picker screens, built per G11 and driven by the G14 intent stream.
  GATE: every menu fully operable with a gamepad and no cursor; side-by-side capture vs native
  judged pixel-plausible; assets 100% from original bundles; runs at 1280×800 on Deck-class
  hardware with the frame budget measured on device. No sim fidelity claims yet.
- **P1 — hub.** Scene composition (G12) renders the hub from real data; NPCs and the shop economy
  (G8); the room/flow state machine and its transitions (G13); run entry portal. GATE: walk the
  hub on a controller, talk to every NPC, complete a purchase, enter and leave a run shell, with
  all transitions matching G13's timing traces.
- **P2 — deterministic sim core.** Consume the physre + spellre landings: tick graph, integrator,
  RNG, fire projectile. Build the T3 recorder mod. GATE: T2 movement + fire goldens green; first
  T3 replay (solo, scripted 60 s run) within the divergence budget; determinism proof (same seed
  + inputs → identical state hash, 1000 ticks).
- **P3 — combat parity.** All elements incl. earth charge + frost channel; skeleton family AI
  (monre); waves (wave-scaling-re + the botwaves landing); loot (G7); progression (G6); potions
  incl. invincibility semantics (potionvfx/potiondrop docs); HUD (G9); animation (G4); audio
  (G5); death/spectate flow. GATE: T2 all-element damage goldens exact; T3 full-arena replays; a
  human plays it on both mouse and controller and the owner signs off on feel.
- **P4 — multiplayer.** Server rooms, prediction/reconciliation, scene-epoch lifecycle, ally HUD
  parity (allyvis semantics), bots as server-side players, the dedicated-server package and its
  hosting docs. GATE: a 2-human + 1-bot browser session passes the same acceptance battery style
  as the native MP campaigns (cross-peer HP parity, room transitions, hub returns).
- **P5 — standalone + mods + editors.** The `webgame/shell/` Windows and Linux builds, Deck
  install path verified on device; the wasmoon `sd.*` runtime; minimap + bot-brain run; site
  boneyard/wave editors round-trip into live webgame sessions; mod listings serve webgame
  packages alongside loader packages.
- **P6 — launch.** Accounts/saves (G10); perf budget re-measured (60 fps mid hardware and Deck —
  measure, don't guess); site integration, `ENGINE_STATUS` flipped and `/game` linked from the
  site's navigation; written dev blessing confirmed by owner; public beta.

## 10. Execution guide for the implementing agent

1. Read this file, then the Confidence table's HIGH rows, then the landed gap docs for the phase
   you are executing. Do not start a phase whose gap campaigns have not landed.
2. Conventions are non-negotiable and identical to the loader project: investigate → document →
   fix; class-closing fixes; no fallback code paths; contracts/goldens never weakened silently;
   every landing = full battery + exact-SHA CI green + an evidence dir with checksums; report
   DONE:/QUESTION: sentinels to ATC.
3. WSL-load rule: bulk filesystem work happens Windows-side (`powershell.exe`, `Get-FileHash`,
   `rg.exe`); never recursive scans over `/mnt/c` or `/mnt/d` from WSL.
4. Webgame battery = `webgame` unit tests + T1/T2/T3 conformance + lint/typecheck, wired into the
   same CI workflow; floors ratchet like the existing suite (`~/codex-fleet/20260723/` playbook
   has the current floors; they only go up).
5. Live native captures (goldens, T3 traces) use the standard harness
   (`scripts/Launch-LocalSoloSession.ps1` / `Launch-LocalMultiplayerPair.ps1`,
   `SDMOD_DISABLE_AUDIO=1`, isolated ports/instances, exact-PID disposal with proofs).
6. Release-note discipline: webgame ships via the website; loader release notes never mention it.
7. Controller parity is a per-phase gate, not a P6 task. A screen that cannot be operated without
   a cursor does not pass its phase, no matter how it looks.

## 11. Open items / to-confirm

- **Owner (blocks launch):** written re-confirmation of the original developers' blessing, on
  file. Scope is already settled verbally (2026-08-04): it covers redistributing the content
  **and** the Raptisoft logo. What remains is having it in writing before the public build ships.
- **At launch:** reword the site's "not affiliated with Raptisoft" footer so it does not
  contradict the shipped splash — see the G11 rule in §6.
- ~~Controller aim scheme~~ — decided 2026-08-04: twin-stick, mapping pinned in §4.2.
- Confirm the `api/` deployment mapping (repo → `solomon-dark-revived` on NFO) and where webgame
  static hosting slots in (same box; measure asset weight in P0).
- Steam Deck: confirm a physical device is available for the on-device gates in P0/P5/P6, or
  declare the substitute (1280×800 Linux Chromium + a standard gamepad) and its blind spots.
- Tier C campaigns dispatch as fleet slots free, after Tier A and Tier B have landed.
