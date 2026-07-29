# ML Bot Policy v2 — Specification

Owner-approved requirements, 2026-07-29. This document is the contract for the
v2 learned-bot upgrade. The v1 baseline is `mods/bot-brain/scripts/policy_spec.lua`
(87 observations, 9 movement actions, 10 cast actions, single 48-unit tanh
hidden layer, deterministic target selection in the Lua wrapper).

## Goals

1. **Generality.** Boneyards are randomly seeded and players ship custom
   boneyards. Nothing the policy sees may encode one specific map layout.
   All spatial perception must be egocentric (relative direction + distance,
   local walkability), derived from the live nav grid at runtime. Training
   must rotate boneyard seeds/layouts across episodes so geometry cannot be
   memorized.
2. **The policy decides, the wrapper perceives.** Target selection moves from
   the Lua wrapper into the network. The wrapper's job is building honest
   observations and enforcing legality masks — not choosing behavior.
   (The scripted skill-upgrade manager remains for now; see "Skill choices &
   welding".)
3. **Stationary representations.** No feature may change meaning when the
   character progresses. Mana is the proven offender: a ratio-only mana signal
   breaks when max mana grows via expansion upgrades while secondary costs
   stay absolute. Absolute values on fixed scales, plus explicit
   affordability, everywhere this applies.
4. **Dynamic loadouts are the norm.** Spells change per run: the bot may pull
   a different primary, gains secondaries as it progresses, and may activate
   a welded primary build (IDs 1000–1009). Spell observations are per-slot
   structured descriptors read from the live loadout each decision — never
   baked at spawn.
5. **Cap-agnostic by construction.** The native 4-participant cap is being
   virtualized to 50 in a separate mandated workstream (main-repo tasks
   #20/#72); party sizes may become absurd later. No bot-brain, policy, or
   trainer code may assume a maximum participant count: ally perception is
   K-nearest by construction, total-count features use fixed
   large-headroom scales, and roster/team sizes are configuration. This
   branch must be cap-ready; it does not implement the cap raise.
6. **Native game stays authoritative.** All actions still route through
   `bot:move_to` / `bot:stop` / `bot:cast` / `sd.bots.choose_skill` /
   `sd.world.request_loot_pickup`. The native game keeps enforcing mana,
   cooldowns, collision, replication. Masks exist to remove wasted actions,
   not to replace native validation.

## Observation v2 layout

Blocks below replace/extend v1. Exact ordering lives in `policy_spec.lua`
(`observation_version = 2`); sizes shown are the contract. Every scalar is
clamped to [-1, 1] with a **fixed** documented divisor (stationarity rule).

### Block A — Self (v1's 12 values, amended)

Keep all v1 self values. Add:

- `self_mana_current_scaled` — absolute current mana / MANA_SCALE.
- `self_mana_max_scaled` — absolute max mana / MANA_SCALE.
- `self_hp_max_scaled` — absolute max hp / HP_SCALE (same reasoning).

MANA_SCALE and HP_SCALE are fixed constants chosen once from the native
catalogs/RE evidence to cover realistic end-game values (document the choice
in the spec file). They must never be derived from the character.

### Block B — Active primary build (new)

The active primary is dynamic (element primaries 8/16/24/32/40 or weld builds
1000–1009 activated via progression `+0x844`; see
`docs/reverse-engineering/spell-welding.md`).

- `primary_element_*` — 5 values, element **multi-hot**: one element set for a
  base primary, two set for a welded build.
- `primary_welded` — boolean, active build is a weld (1000–1009).
- `primary_build_index_scaled` — weld pair index (build − 1000)/10 when
  welded, else skill-band identity scaled; exact encoding decided in
  implementation, must be documented in policy_spec.
- `primary_mana_cost_scaled`, `primary_range_min_scaled`,
  `primary_range_max_scaled` — live values for the active build.
- `primary_affordable` — current mana ≥ effective cost.

### Block C — Per-slot secondary descriptors (new; replaces the 8 bare
"slot occupied" booleans)

For each of the 8 secondary slots, a structured descriptor (order fixed):

- `occupied` — boolean.
- `element_*` — 5-value one-hot (zeros for unknown/custom).
- `band_index_scaled` — position within the element's 8-skill band, /8
  (identity signal that generalizes: same element+index ⇒ same spell).
- `mana_cost_scaled` — effective cost / MANA_SCALE (after native cost
  multipliers where readable).
- `range_scaled` — cast range / 1000 (0 if unknown).
- `cooldown_scaled` — recharge period / COOLDOWN_SCALE (0 if unknown).
- `ready` — per-slot readiness boolean (native recharge state) if readable;
  else fall back to the global cast-ready signal, and record the limitation.
- `affordable` — current mana ≥ effective cost.
- `in_range_of_target` — selected target (see Block E) within this slot's
  range window.

Data sources, in priority order: a native seam reading the live skill-catalog
rows / progression (preferred — composes with cost multipliers and per-run
upgrades); `docs/reverse-engineering/native-skill-catalog.json` as the static
property table where a live read is not feasible; the registered spell config
(`mana_cost`, `range`, `cooldown_ms`, …) for Lua-registered custom spells.
Descriptors must resolve from `secondary_entry_indices[slot]` → entry id at
observation time, every decision, so mid-run loadout changes are visible
immediately.

### Block D — K-nearest enemies (new; K = 8)

Per enemy slot, sorted nearest-first, zeros when absent:

- `present` — boolean.
- `dx`, `dy` — unit direction, egocentric.
- `distance_scaled` — /1000.
- `hp_ratio`.
- `radius_scaled` — /100.
- `velocity_dx`, `velocity_dy` — world-units-per-second direction+magnitude
  packed as (vx/VEL_SCALE, vy/VEL_SCALE), derived in Lua from per-actor-id
  position deltas across decision ticks (no seam required; native read
  optional later). Essential for kiting.
- `in_primary_range` — inside the active primary window (honest per-enemy
  computation, not the v1 `target ~= nil` degenerate).
- `is_current_target` — this slot is the persisted selected target.

Enemy rows come from the existing replicated-actor path
(`steering.live_enemies`). Track velocity by `network_actor_id`.

### Block E — Selected target summary (v1's 10 values, retained)

Keep the v1 target block, but it now describes the **policy-selected** target
(Block H target head), not a wrapper-chosen one. `target_in_primary_range`
must be computed honestly.

### Block F — Local geometry / obstacles (new)

Owner requirement: nearby obstacles must be visible so the bot can plan
ahead. Two complementary egocentric views, both derived from the cached
`sd.nav.get_grid` walkability grid (grid is static per scene; cache per scene
epoch, do NOT issue per-tick native segment tests for this):

- **Clearance rays** — 8 values, one per movement direction: distance to the
  first blocked cell along that ray, capped at RAY_RANGE (≈ 480 units),
  normalized. Computed by stepping grid cells in Lua.
- **Walkability patch** — 7×7 egocentric grid sample centered on the bot at
  fixed spacing (≈ 60 units), row-major, center cell omitted → 48 booleans
  (1 = walkable). Fixed spacing and orientation (world-axis-aligned) so the
  representation is identical across boneyards.

The 9-way movement mask keeps its existing `sd.nav.test_segment` checks
(authoritative, includes dynamic blockers if any).

### Block G — Pickups (new; K = 4)

From `sd.world.get_replicated_loot()` (host-owned gold `0x7DC`, health/mana
orbs `0x7DB`, item/potion carriers `0x7DD`). Per pickup slot, nearest-first:

- `present`, `dx`, `dy`, `distance_scaled` (/1000).
- `type_*` — one-hot over {gold, orb, item-carrier}; split orb into
  health/mana if the snapshot distinguishes them (audit in Phase 1).

Plus one aggregate: `pickup_count_scaled` (/8).

### Block H — Aggregates, arena, build config, history (v1 blocks, retained)

- Keep v1's enemy aggregates, threat direction, escape direction, suggested
  move (advisory feature only), arena block, element/discipline config
  one-hots, and the 11 history values.
- Add to history: `previous_target_action_scaled` and
  `previous_target_switched` (boolean, target changed last decision).
- Add `has_spell_welding_skill` (boolean) and `weld_offer_pending` (boolean —
  a pending skill choice includes option id 52).

### Block I — Allies / other players (new; K = 4; added 2026-07-29)

The policy must see teammates — human players and bots alike — for learned
team play. From `sd.runtime.get_multiplayer_state().participants[]`
(all fields already replicated; no seam), the K=4 nearest in-run
participants excluding self, nearest-first with deterministic
participant-id tiebreak, zeros when absent:

- `present` — row exists and participant is in-run.
- `dx`, `dy` — unit direction, egocentric.
- `distance_scaled` — /1000.
- `hp_ratio` — life_current / life_max.
- `mana_ratio` — mana_current / mana_max.
- `alive` — life_current > 0 (dead allies stay present: their position
  still matters).
- `is_human` — controller_kind is Native.
- `intent_dx`, `intent_dy` — replicated movement intent, normalized
  (verify semantics in Phase 3).

Plus one aggregate: `ally_count_scaled` — in-run allies / 50 (fixed scale
matching the mandated cap target so the feature stays stationary when
parties grow; small values today are fine).

41 values total. This supersedes the "ally features" entry under non-goals.
The implementation plan's §C layout must be recomputed in Phase 3
(354 → 395) with Block I placed after Block G's pickups and before the
Block H aggregates.

## Action space v2

Three heads, factored autoregressively per decision:

1. **Movement head — 9 actions** (unchanged: idle + 8 directions, 110-unit
   requests, nav-masked).
2. **Target head — 9 actions** (new): `keep_current` + select enemy slot 1–8.
   Mask: `keep_current` legal iff a live persisted target exists OR no enemy
   exists (no-op); slot k legal iff Block D slot k is present and alive.
   Selection persists by `network_actor_id` across decisions until the enemy
   dies, despawns, or the head switches. Slots re-sort every tick;
   persistence is by id, not slot.
3. **Cast head — 10 actions** (unchanged list: none/primary/secondary 1–8).
   Mask rebuilt from the **target chosen this decision**:
   - `none` always legal.
   - casting requires offense enabled, native cast-ready, no cast
     active/pending (as v1) — but **no global primary-window gate**: the v1
     rule that all casting (even long-range secondaries) required an enemy in
     the primary window is removed.
   - per-slot: slot occupied, affordable, per-slot ready (where readable), and
     selected target within that slot's range window when its range is known
     (unknown range ⇒ range check skipped, native validation decides).

Sampling order within one forward pass: movement and target sample from their
logits; the cast mask is then computed from the sampled target and the cast
head samples. Joint log-probability = sum of the three heads' log-probs;
PPO treats it as one composite action. Trajectory records all three masks and
actions (`trajectory_version = 2`).

Casts aim at the selected target's current position with the existing hold
duration. Aim-point offset/leading is out of scope for v2 (velocity features
let the network time casts; native behavior handles the rest).

### Loot pickup (scripted assist, not a head)

When a host-owned pickup is within native pickup range, the wrapper
auto-issues `sd.world.request_loot_pickup` (rate-limited, host arbitration
unchanged). The learned part is navigation: the policy sees pickups
(Block G) and learns to walk to them. No new action dimension.

### Skill choices & welding (scripted manager, weld-aware)

The deterministic upgrade manager remains in v2 but must become weld-capable:

- Recognize option id 52 (Spell Welding) in pending choices; expose
  `weld_offer_pending` to the observation.
- Config knob (`policy.weld_preference` or similar in the bot config):
  `prefer` (take weld offers when the rolled build's components are learned),
  `avoid`, `auto` (default: prefer once ≥2 base primaries are learned).
- After activation, Block B must reflect the welded primary on the next
  decision (verify the attack window refresh also tracks the rebuilt
  primary).
- A learned skill-choice head is explicitly deferred to v3: choices are rare
  events (a handful per run), far too sample-starved to learn jointly with
  10 Hz movement/combat. Document this in the spec file.

## Network & runtime

- Architecture v2: input = final observation count (compute in
  `policy_spec.lua`; expected ≈ 300), two tanh hidden layers (192, 96),
  four output groups: movement logits (9), target logits (9), cast logits
  (10), value (1). `architecture = "mlp-tanh-three-head-v2"`.
- `model_version = 2`, `observation_version = 2`, `trajectory_version = 2`.
  v1 weights are not migratable; training restarts from scratch.
- Update the hand-rolled Lua forward pass (`policy.lua`) for two hidden
  layers and three masked softmax heads. At ~300×192 + 192×96 + heads this
  remains ≪ 1 ms per decision at 10 Hz.
- `policy_weights.lua` / `models/bot-brain/policy-v2.json` carry the new
  shapes; weight hot-reload keeps working; loading a v1 file must fail with
  a clear version error, not silently misindex. (No compatibility shims —
  repo convention: no fallback paths.)

## Trainer

`tools/train_bot_policy.py` (+ `tools/ml_bot/`, headless harness):

- Three-head PPO: composite log-prob, per-head entropy bonuses (tune scales
  so the target head doesn't collapse to `keep_current`).
- Trajectory v2 ingestion (three masks/actions per step).
- **Boneyard rotation:** every training episode/run must start with a fresh
  boneyard seed, cycling layouts where multiple are available. The policy
  must never train repeatedly on one fixed geometry. Wire this through the
  headless run launcher; make the seed visible in run logs.
- Reward shaping: no new terms required by this spec, but audit that nothing
  in the existing reward references wrapper-chosen targets in a way that
  breaks with learned targeting.
- Export both weight artifacts; bump format/version fields everywhere
  consistently (spec, weights, trainer, trajectory writer, verifiers).
- **Team-composition rotation (added 2026-07-29):** training episodes must
  rotate compositions so the policy learns solo and team play:
  (a) solo — one learned bot; (b) mixed — the learned bot plus 1–3 scripted
  Lua bots (rotating skirmisher/guardian/striker behaviors) as teammates;
  (c) multi-learned — 2–4 learned bots sharing the current policy weights,
  every authority-side learned participant collecting trajectories (GAE
  already groups by episode_id + participant_id). Composition goes in the
  episode log next to the seed. Sizes are configuration, never hardcoded,
  so compositions scale when the cap-raise workstream lands.

## Native seams (loader C++) — implement as needed

Audit first (Phase 1), then implement the minimal set. Expected gaps:

1. **Per-slot spell data read** — for the participant's current loadout:
   entry id, element/band, effective mana cost (post-multiplier), range,
   cooldown/recharge state per secondary slot, active primary build id
   (progression `+0x844`) and its effective cost/range. Exposed via
   `sd.bots.get_participant_state` extension or a dedicated
   `sd.bots.get_loadout_details(participant_id)`.
2. **Weld visibility** — has-skill-52, current weld build id (covered by the
   same read), and whether a pending skill choice contains option 52 (the
   existing `get_skill_choices` options list likely already shows id 52 —
   verify, and expose the rolled pair at `+0x844` if cheaply readable).
3. **Loot orb subtype** — only if `get_replicated_loot` doesn't already
   distinguish health vs mana orbs.

Follow existing seam conventions (`gameplay_seams.h`, replication-safe,
authority-aware). Anything readable purely from already-replicated state
should be computed in Lua instead of adding native surface.

## Verification (definition of done)

- Extend `tools/verify_lua_bot_brain.py` and `tools/verify_ml_bot_live.py`
  for v2: observation vector length/version match, finiteness sweep, mask
  correctness (affordability, per-slot range, target-slot validity,
  clearance/patch sanity against the grid), target persistence by actor id,
  weld observation flip after a weld activates, pickup block populates when
  loot drops, auto-pickup credits once.
- Trainer smoke: short headless PPO run completes, loss finite, weights
  export/hot-reload, boneyard seed rotation observable in logs.
- Live smoke on the real game (existing harness): learned bot spawns, moves,
  targets, casts secondaries at range (v1 could not), walks to a pickup;
  verify via runtime logs before declaring done.
- All existing bot/test suites still pass.

## Adjudications — 2026-07-29 (post-Phase-1 audit)

Rulings on the open questions in `ml-bot-policy-v2-implementation.md` §E.
These amend the blocks above where they conflict.

1. **Layout = 354 values.** The audited 350-name list plus the four derived
   combat-stat multipliers (`offensive_damage_multiplier_scaled`,
   `offensive_mana_multiplier_scaled`, `cast_speed_multiplier_scaled`,
   `secondary_recharge_multiplier_scaled`) appended to Block H — they are
   combat-relevant and already replicated. The remaining v1
   inventory/equipment/progression summary fields stay dropped until
   inventory actions exist (v3). `primary_available` stays superseded by
   Block B.
2. **Scales.** Fixed constants chosen in Phase 3 from catalog/RE maxima and
   recorded in `policy_spec.lua` with evidence comments: clean round numbers
   at or above end-game maxima (MANA_SCALE/HP_SCALE from statbook/Health-Up
   evidence, VEL_SCALE from the fastest observed mover, COOLDOWN_SCALE from
   the Phasing/Teleport caps). No owner gate per constant.
3. **Secondary coverage limitation accepted.** Unresolved range ⇒ no range
   gate for that slot; unresolved cooldown ⇒ global-readiness fallback;
   explicit `*_resolved=false` everywhere. No broader secondary RE project
   for v2.
4. **`+0x844` policy.** Generation-scoped capture as planned;
   `build_id_resolved=false` during a pending weld is acceptable;
   loaded-save/post-refresh reconstruction from live primary state, verified
   by the Phase 2 live probe.
5. **Nav cache: no new native seam.** Per-scene cache with coarse periodic
   refresh (~2 s cadence; adopt only `refresh_pending=false` snapshots; the
   native 500 ms rebuild limiter is the backstop) so participant occupancy
   stays near-current rather than frozen at scene entry. Phase 3 must verify
   the grid's placement test excludes the observing bot itself; if that
   check fails, stop and investigate — do not ship a patch that marks the
   bot's own cell blocked.
6. **Seed rotation cost accepted.** Disposable solo session per environment
   episode for v2 training; stock Leave Game automation is a later
   throughput project.
7. **Layout corpus.** Phase 5 gates on fresh native seeds on the stock
   layout. Multi-layout cycling lands behind the validated
   `TestSurvivalBoneyardOverride` plumbing and activates when the owner
   supplies approved `.boneyard` fixtures (non-blocking).
8. **Bootstrap retained, rewritten.** The synthetic expert is rewritten
   target-aware per the Phase 4 plan (select enemy slot first, derive casts
   from it). No v1 weights, trajectories, or expert data are reused.

## Explicit non-goals for v2

- Learned skill-upgrade / weld-choice head (v3; scripted manager handles it).
- Aim-point offset or analog movement magnitude.
- Inventory actions (equip/use/drop) and per-item identity observations.
- Recurrent memory (GRU/LSTM).
- Implementing the participant cap raise itself (separate workstream,
  main-repo tasks #20/#72); this branch is cap-agnostic, not cap-raising.
