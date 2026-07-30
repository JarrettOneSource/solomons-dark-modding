# ML Bot Policy v3 — Requirements Charter

Owner direction, 2026-07-30. v2 (landed `ccef342`) gave the policy learned
targeting, spell semantics, obstacles, pickups, allies, and weld visibility.
v3's mandate: **give the agent everything it needs to actually become skilled
at the game** — high-fidelity perception, learned build-making, and real
inventory use. This charter defines requirements and the investigation
questions that must be answered before the v3 spec is frozen. v2's standing
principles carry forward unchanged: generality across boneyards,
egocentric/stationary representations, cap-agnosticism, native authority,
masks for legality not behavior, no fallbacks or shims.

## A. Obstacles — verify, then upgrade fidelity

The v2 patch/rays derive from the sampled nav grid (player-sized placement
tests at ~60-unit spacing). The native game holds exact obstacle geometry in
memory (static collision circles/shapes consumed by
`movement_collision_test_circle_placement`). Requirements:

1. **Verify v2 first.** Live-measure the current patch/ray fidelity against
   native collision truth: sample points along each ray and across the patch,
   compare grid-derived walkability vs the native placement test. Quantify
   error (small obstacles missed between samples, radius inflation at
   edges). If v2 detection is materially wrong anywhere, that is a bug to
   fix regardless of the rest of v3.
2. **Investigate exact-geometry exposure.** What obstacle primitives exist
   per scene in RAM (circles: center/radius; other shapes?), where do they
   live, and can an address-free seam enumerate them? Proposed target: a
   K-nearest-obstacles block (like enemies — dx, dy, distance,
   radius/extent per obstacle) alongside the retained patch/rays, giving
   the policy exact nearby geometry for tight kiting lines while the patch
   covers area awareness.
3. Investigation must answer: primitive inventory + evidence, seam shape,
   whether dynamic obstacles (destructibles, participant bodies) appear in
   the same structures, and recommended K/feature set.

## B. Enemies — perception strong enough for real skill

v2 gives 8 nearest enemies with kinematics. Missing for actual skill:

1. **Identity.** Enemy species (object_type_id catalog) as structured
   features or a compact embedding so the policy can learn per-species
   behavior (webbers, exploders, ranged, etc.). Must generalize: unknown
   species degrade gracefully, not crash.
2. **Combat state.** Per-enemy attack/cast/telegraph state (anim state,
   wind-up flags), active status effects on the enemy (slowed, frozen,
   poisoned, webbed), and facing/heading where readable. Investigation:
   what per-enemy runtime state is already replicated or natively readable
   address-free.
3. **Projectiles and hazards.** A K-nearest-hazards block: enemy
   projectiles and damaging areas (position, velocity, radius) so dodging
   is learnable. `sd.world.get_replicated_spell_effects` and
   `get_replicated_air_chains` exist — audit what they carry, what native
   projectile/hazard state exists beyond them, and whether a seam is
   needed.
4. Investigation must also assess **aim-point offset** for casts (leading
   moving targets): cost/benefit of a small continuous or discretized aim
   head vs aiming at current target position, given native homing/behavior
   per spell family.

## C. Learned skill choices — the agent builds itself

Owner ruling: seeing upgrade *results* on stats stays (v2 already does);
but the agent must **pick its own skills** to learn efficient builds. The
deterministic manager (including weld preference) is replaced by a learned
decision. Design constraints:

1. Skill choices are rare events (a handful per run) on a slow timescale;
   they must not be crammed into the 10 Hz action heads. Proposed shape: an
   **event-driven choice head** — invoked only when a choice is pending,
   consuming the full observation plus per-option descriptors, masked to
   offered options.
2. **Option descriptors** must be semantic and general: element/band/type,
   is-primary/is-weld (with the rolled weld pair from v2's seam), is-Health-Up
   and other utility classification, current level / apply_count, and the
   catalog-derived mechanical properties already used for spells. New
   species of option must degrade gracefully.
3. **Credit assignment** is the core design question: investigate and
   propose (a) same PPO stream with choice events as sparse actions under
   the existing composite log-prob, (b) a separate choice-event trajectory
   with episode-return targets, or (c) another justified scheme. The
   proposal must include how the weld decision folds in (it is just another
   option once descriptors exist) and how exploration across builds is
   maintained (entropy/temperature at choice events).
4. Retirement plan for the scripted manager, and a config escape hatch to
   force-scripted choices for A/B evaluation runs.

## D. Inventory, items, potions — deep dive, then real use

Owner direction: expose potion counts and what each potion does, item
identities, and land a good design for the bot to actually use them.
Existing groundwork: `native-item-catalog.json`,
`inventory-item-investigation.md`, `docs/lua-items.md`, replicated
`inventory_items[]` rows (type_id, recipe_uid, slot, stack_count), the Lua
consumable framework (custom potions landed 2026-07-23), and the glock
canary's weld-based ammo types.

Investigation must produce:

1. **System map.** How native inventory works end-to-end: item taxonomy
   (type_id/recipe_uid semantics), potion subtypes and their exact effects
   (heal/mana/buff amounts, durations), stacking, equipment slots,
   pickup→inventory flow, and the native entry points for *using* a
   consumable and *equipping* an item — for a synthetic participant on the
   simulation authority, replication-safe.
2. **Observation proposal.** Per-potion-subtype counts with effect
   semantics (structured descriptors from the item catalog, like spells —
   not bare counts); equipped-item descriptors (what the hat/robe/weapon
   /rings/amulet actually do — stat contributions are partly visible via
   derived_stats already; identify what per-item identity adds); inventory
   summary beyond potions where actionable.
3. **Action proposal.** Minimum viable item actions for v3 — expected:
   drink-potion (per subtype or per slot, masked by possession and
   usefulness-legality only, not behavior); equip/unequip likely deferred
   unless the dive shows it cheap and high-value. Every action through
   native paths with native validation.
4. What needs new seams vs existing replicated state, with evidence.

## E. Scope guards

- Recurrent memory stays out of v3 unless the enemy/projectile
  investigation demonstrates it is required; prefer widening the history
  block first.
- Cap-agnosticism, boneyard generality, and the no-fallback rule are
  unconditional.
- The v2 trainer/composition/seed machinery is the foundation; v3 must not
  regress it. Version bumps: observation/model/trajectory v3, no v2 shims.
- Existing scripted-bot behaviors must keep working for mixed-composition
  training.

## Process

Phase V3-1 (investigation): answer every numbered question above with
file/RE evidence; produce `docs/ml-bot-policy-v3-implementation.md` with
proposed observation/action/head deltas, seam list, and phase plan;
implement nothing. The orchestrator adjudicates before implementation
phases are dispatched.
