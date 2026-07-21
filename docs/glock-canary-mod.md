# Solomon's Glock — Canary Stress-Test Mod

Status: design record (2026-07-21) · Mod id: `meme.solomons_glock`
Companion to: `lua-seam-roadmap.md` (seam numbers below reference its roadmap)

## 0. Why this mod exists

A deliberately absurd mod — a Glock 19 as the wizard's primary spell — chosen because it
is maximally *unlike* anything the game ships. If this mod can be built **entirely in Lua +
overlays + staged assets, with zero mod-specific native code**, the framework is ready for
awesome stuff. Every feature below is chosen to stress a specific seam; the traceability
matrix (§5) is the pass/fail scorecard. When a seam lands in the framework, the
corresponding milestone here (§7) is its acceptance test.

Core joke that makes it a great canary: **the ammo types are welds.** Welding the Glock
with the game's own spell schools (fire, air, water, earth, ether) converts what comes out
of the barrel. That forces the mod *through* the native weld system instead of around it.

---

## 1. Concept

Replace the starting primary bolt with a semi-automatic hitscan pistol: 15-round mag,
manual reload, dropped-mag decal, brass pickups from kills, an upgrade tree of gun-brain
skills, and five weld-derived ammo types. No mana cost on the trigger — ammo *is* the
resource — except where a weld says otherwise.

Pillars:
- **Feels like a gun** — instant hits, muzzle flash, tracers, casings, recoil, reload ritual.
- **Plays like Solomon** — picked in the skill picker, leveled on level-up, welded like any
  other skill, drops and economy through native systems.
- **Multiplayer-native** — a peer in your session sees and hears your glock with the mod
  doing nothing special (roadmap §1 contract).

---

## 2. Mechanics

### 2.1 The weapon (primary slot)

- Registered as a **primary-slot spell** via `sd.spells.register{slot = "primary"}` —
  plugs into the primary builder chain (`kSkillsWizardBuildPrimarySpell`, pure-primary
  gates, `kPurePrimaryAttackDispatch`).
- **Semi-auto:** one shot per trigger press, cadence governed by the primary attack
  window (same machinery `sd.bots.get_primary_attack_window` reads today).
- **Hitscan:** on fire, cast a ray from muzzle toward cursor with a spread cone
  (base 4°); first enemy actor intersecting the ray takes damage via
  `sd.combat.deal_damage(target, amount, {type, source, riders})`. LOS/blockers via the
  `sd.nav` collision query (native `movement_collision_test_circle_placement` bridge).
- **Damage model:** baseline tuned relative to the stock starting bolt (numbers live in
  the mod's cfg, not this doc). Crits supported (see Hollow Points).

### 2.2 Ammo & reload

- **Mag 15 / reserve cap 90.** Firing decrements mag; `spell.casting` pre-event filter
  cancels the shot at 0 and plays a dry-fire click.
- **Reload:** manual on a bound key (default `R`) or automatic on an empty-mag trigger
  pull, ~1.1 s, animated on the HUD. Mag drops on the ground (§2.3).
- **Brass drops:** kills roll a chance to drop a "Brass" pickup (+15 reserve) — injected
  via the `drop.rolling` filter, granted via the `drop.picked_up` filter, arbitrated in MP
  by the existing `request_loot_pickup` flow.
- **Ammo is a mod-local resource** — the documented custom-resource recipe (Lua state +
  cancellable cast filter + HUD). No framework resource API needed.

### 2.3 The dropped mag (and friends)

- On reload, an empty-mag sprite spawns at the wizard's feet and **fades out over ~4 s**
  via `sd.vfx.spawn(sprite, x, y, {lifetime_ms, fade_ms})` — a real game-side ephemeral
  visual (puppet/death-effect substrate, same system that fades corpses), so it
  depth-sorts correctly under actors walking over it.
- Each shot ejects a **shell casing** (tiny vfx, short fade). This is the volume stress
  test for `sd.vfx` — sustained fire must not leak puppets or tank the frame rate.
- Akimbo (capstone, §2.4) drops **two** mags. This is important.

### 2.4 Upgrade tree (registered skills, levels read from the progression book)

| Skill | Levels | Effect |
|---|---|---|
| Extended Mags | 3 | +5 mag size per level |
| Quickdraw | 3 | −15% reload time per level |
| Hollow Points | 3 | +5% crit chance per level, crits ×1.5 |
| Compensator | 3 | −1° spread per level |
| Laser Sight | 1 | Muzzle-to-blocker beam + endpoint dot (§2.7); −50% spread while stationary |
| Fire Selector | 1 | Hold-to-auto (cadence still bounded by attack window) |
| Akimbo | 1 (capstone) | Second glock: +100% fire rate, 2×15 mag, single reload, both mags drop |

Upgrades appear in the native level-up offer flow (`choose_level_up_option` /
`active_level_up_offer` already exist) with mod-supplied icons.

### 2.5 Welds = ammo types

Welding the Glock with an existing school skill unlocks an ammo type. Owned ammo types
are cycled with a bound key (default `Q`). One active at a time.

| Weld | Partner skill | Ammo type | Behavior | What it stresses |
|---|---|---|---|---|
| Dragon's Breath | Fireball | Incendiary | Burn DoT rider; impact spawns embers | Native projectile primitive (`kFireEmberCtor`) composed from Lua |
| Thunder Rounds | Chaining | Shock | Hit chains to nearby enemies | Native air-chain (`kAirLightningChainTarget`) — rides the **already-replicated** air-chain channel |
| Cryo Rounds | Chill Wind | Frost | Slow rider, stacks to freeze | Status/modifier riders on `deal_damage` |
| Earthshaker | Boulder | AP | Ray pierces up to N targets, knockback, screen shake | Multi-hit hitscan; `sd.camera` nudge (stretch) |
| Void Rounds | Ether Blast | Void | No ammo — drains mana per shot; pierces; damage ramps per consecutive hit | Mana writes (`kPlayerActorApplyManaDelta`); resource inversion |

Weld mechanics are the **largest RE dependency** in this mod: weld *products* look
data-driven (`wizardskills/` contains entries like `embers_to_imps.cfg`), but where the
*pairing rules* live (cfg-side vs hardcoded table) is unverified. `sd.spells.register`
must grow weld-pairing registration either way (roadmap seam 04 extension).

### 2.6 Fire modes

- Semi-auto default; Fire Selector upgrade enables hold-to-auto.

### 2.7 Gunfeel: flash, shake, crosshair, laser

- **Muzzle flash animation.** Every shot plays a 2–3 frame flash at the barrel via
  `sd.vfx.spawn` with the position sampled at fire time — short enough that no
  actor-attachment support is needed (a fixed-position flash cannot visibly lag on a
  2-frame lifetime). Akimbo alternates barrels.
- **Camera shake.** Slight per-shot shake, intensity scaled by ammo type (base = subtle;
  Earthshaker = heavy). Implementation approach: the game almost certainly has a native
  screenshake routine already (Earthquake and Boulder impacts are prime candidates) —
  `sd.debug.trace_function` those casts to find it, then `sd.camera.shake(intensity,
  duration_ms)` wraps the native call rather than reimplementing view-offset math.
  Degrades gracefully to a HUD-only kick until that RE lands. Config toggle for
  shake-sensitive players.
- **Crosshair.** In runs, a crosshair draws at the cursor (`kCursorScreenPositionGlobal`
  is already resolved) on the `sd.hud` screen layer, replacing the native cursor (small
  RE: cursor sprite/visibility control). The crosshair **blooms with current spread** —
  widens while firing, tightens with Compensator levels and while stationary — so the
  accuracy model is visible, not just numbers.
- **Laser Sight (upgrade).** Adds a beam from the muzzle toward the cursor, terminated at
  the first blocker via the `sd.nav` LOS query — the laser shows exactly where the shot
  will actually land, including walls — with a dot sprite at the endpoint. Drawn on the
  **world layer** (under HUD, over ground). While stationary the crosshair bloom
  collapses to the dot (−50% effective spread).

---

## 3. Presentation spec

### HUD (`sd.hud`, screen layer)
- Bottom-right ammo block: `15 / 90` (tabular figures), mag icon, active ammo-type icon.
- Crosshair at cursor with spread bloom (§2.7), replacing the native cursor during runs.
- Reload progress bar over the wizard while reloading.
- Hit markers on confirmed hits; low-ammo pulse under 25%; dry-fire flash at 0.
- Laser Sight beam + dot: **world layer** draw (under HUD, over ground) — exercises draw layers.

### Art (staged via atlas packer; runtime `sd.sprites` later)
Glock-in-hand attachment (weapon visual lane — `render_weapon_type` /
`attachment_visual_lane` path, same lanes staffs/wands use), muzzle flash frames, tracer,
shell casing, dropped mag, Brass pickup, crosshair set (bloom states), laser dot,
skill-picker icon, upgrade icons, five ammo-type icons, HUD glyphs. This is the shopping
list for the in-progress art asset system RE.

### Audio (`sd.audio`, mod-local files)
Gunshot (base + per-ammo-type variant), reload out/in/rack, dry click, brass pickup
clink, shell tinkle (optional). Requires `sd.audio` to load samples from the mod
directory, not just the game's `sounds/`.

---

## 4. Multiplayer behavior & acceptance checklist

Per the roadmap contract the mod ships identical code on every peer. Acceptance runs on
the local transport, two instances, one machine:

- [ ] Peer sees my glock in hand (weapon lane replicates through existing presentation fields)
- [ ] Peer sees my muzzle flashes, tracers, mag drops, casings, laser beam (reload/fire broadcast events → local `sd.vfx`/`sd.hud`)
- [ ] My camera shake and crosshair never affect the peer's view (strictly local presentation)
- [ ] Peer hears my gunshots (broadcast → local playback; distance-gated)
- [ ] My ammo/reload state renders only on my HUD; peer HUDs unaffected
- [ ] Hitscan kill attribution is correct — no double kills, no lost claims (formalized `queue_local_enemy_damage_claim` path under `sd.combat.deal_damage`)
- [ ] Thunder Rounds chains render on both peers via the existing replicated air-chain channel
- [ ] Brass drops replicate; pickup arbitration awards exactly one grant (`request_loot_pickup` flow)
- [ ] Late joiner sees my equipped glock, correct weld state (from `sd.state`), and no stale decals
- [ ] Solo run behaves byte-identically with the session layer absent
- [ ] Stretch: a `sd.bots` bot wields a glock (per-entity skill books already support independent loadouts)

---

## 5. Canary traceability matrix

Status legend: **works now** · **tier-N** (planned in roadmap) · **NEW** (gap this mod adds).

| Feature | Framework requirement | Roadmap ref | Status |
|---|---|---|---|
| Glock in picker, leveling, offers | Spell/skill registration, cfg overlay, `choose_level_up_option` | 04 | tier-1 (cfg side works now — `skill_shock_nova`) |
| Primary-slot fire + cadence | Primary builder chain + attack-window control in `sd.spells.register` | 04 ext. | NEW |
| Hitscan damage | `sd.combat.deal_damage` + riders (slow/burn/knockback) | — | NEW (seam; MP substrate exists: damage claims) |
| Ray/LOS query | `sd.nav` promoted from `sd.debug` | tier-3 | tier-3 |
| Block fire on empty / dry-fire | `spell.casting` cancellable pre-event | 02 | tier-1 |
| Ammo pool | Custom-resource recipe (docs, not API) | — | pattern — document |
| Brass drops | `drop.rolling` filter | 02 | tier-1 |
| Brass pickup grant | `drop.picked_up` filter | 02 ext. | NEW |
| Reload key `R`, ammo-cycle `Q` | Custom input listening / bindable mod actions | — | NEW (`sd.input` is inject-only today) |
| Ammo HUD, hit markers, reload bar | `sd.hud` screen layer | 01 | tier-1 |
| Laser sight under-HUD beam + dot | `sd.hud` draw layers (ground/world/screen) + `sd.nav` LOS | 01 ext. | NEW |
| Crosshair at cursor + spread bloom | `sd.hud` screen draw at `kCursorScreenPositionGlobal` (resolved); native cursor hide | 01 | tier-1 (+ small cursor-control RE) |
| Dropped mag + casings fade | `sd.vfx.spawn` ephemeral world visuals (puppet substrate) | 01 ext. | NEW |
| Muzzle flash animation | `sd.vfx.spawn` short-lived frames, position sampled at fire time (no attachment needed) | 01 ext. | NEW (same seam as vfx) |
| Welds as ammo types | Weld-pairing registration + pairing-rules RE | 04 ext. | NEW (RE item) |
| Ember impact (Dragon's Breath) | Native effect primitive composition | 04 | tier-1 (primitives provably drivable) |
| Chain hit (Thunder Rounds) | Native air-chain call + existing replication | 04 | tier-1 (channel already replicated) |
| Mana drain (Void Rounds) | Mana write via `kPlayerActorApplyManaDelta` | 04 | works now (seam resolved; bless it) |
| Weld/ammo state to peers | `sd.state` + `sd.events.broadcast` | 03 | tier-1 |
| Gun art in atlases | Stage-time atlas packer (extractor exists; packer missing) | sprites v1 | NEW (tooling) |
| Weapon-in-hand visual | Attachment/weapon visual lane binding | 04/art RE | RE in progress |
| Sounds from mod dir | `sd.audio` mod-local sample loading | 07 | tier-2 (+ requirement detail) |
| Per-shot camera shake | `sd.camera.shake` wrapping the game's native shake routine (RE: trace Earthquake/Boulder impacts) | tier-3 sharpened | NEW RE item (degrade to HUD kick until found) |
| Peer-visible bullets/decals | Broadcast events → local presentation (cheap path) or generic modded-effect channel (full path) | 03 / 04 | tier-1 |

**Roadmap deltas this mod introduces** (to fold into `lua-seam-roadmap.md`): primary-slot
registration + weld pairing under seam 04 · `sd.combat.deal_damage` with riders (new
seam) · `drop.picked_up` under seam 02 · draw layers + `sd.vfx.spawn` under seam 01 ·
custom input listening under `sd.input` · atlas packer as `sd.sprites` v1 · mod-local
audio loading under seam 07 · `sd.camera.shake` via native-shake RE (trace
Earthquake/Boulder) · native cursor sprite/visibility control · custom-resource recipe
in authoring docs.

---

## 6. Build milestones (each = acceptance test for a framework phase)

- **M0 — proof of loop (possible today, debug-grade).** Overlay a placeholder cfg skill;
  hitscan by hand: `list_actors` + geometry + `queue_local_enemy_damage_claim`; ammo in
  Lua; feedback via logs. Ugly, solo-only, proves the fire loop end to end.
- **M1 — after `sd.state` + `sd.hud` + filters (roadmap build steps 1–3).** Real ammo
  HUD, cast-blocking on empty, brass economy through drop filters, mag decal via
  world-anchored overlay fallback.
- **M2 — after `sd.spells.register` (primary) + `sd.combat.deal_damage` + input
  listening.** True primary registration in the picker, upgrade tree live, reload/cycle
  keys, correct damage attribution in MP. Ammo types stubbed as manual toggles.
- **M3 — after weld RE + pairing registration.** Real welds with the five school skills;
  ammo switching; per-type impact effects (embers, chains, riders, mana drain).
- **M4 — after `sd.vfx` + `sd.audio` + atlas packer.** Full presentation: casings, mag
  drops, sounds, real art, laser sight layer. Run the §4 MP checklist on local transport.
- **Done** = every box in §4 checked with **zero mod-specific native code**.

---

## 7. Open design questions

- **Hitscan vs. very-fast projectile** for base fire — hitscan is the better canary
  (forces `deal_damage`); projectile may *feel* better in a horde game. Decide at M2.
- **Ammo economy generosity** — brass drop rate vs. dry-spell frustration; does reserve
  cap scale with Extended Mags?
- **Weld acquisition flow** — native weld UI as-is, or does the mod need to inject
  its own offer/choice moments? Depends entirely on the pairing-rules RE.
- **Out-of-ammo fallback** — pure dry-fire (committed bit) vs. a pity "pistol whip" melee.
- **Bot glock** — stretch: proves per-entity loadouts + `sd.bots.cast` generalize to
  modded primaries.
- **Balance target** — meme mod, but it should be *viable*, not dominant; tune against
  the stock starting bolt's clear curve.
- **Cursor swap scope** — crosshair replaces the native cursor in runs only; hub/menus
  keep the stock cursor. Where exactly to gate the swap (combat state vs. scene kind).
- **Shake tuning** — per-ammo-type intensity table + global accessibility toggle;
  does Akimbo double-tap stack shake or clamp it?
