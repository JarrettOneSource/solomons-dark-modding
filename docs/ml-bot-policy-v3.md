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

## Adjudications — 2026-07-30 (post-V3-1 investigation)

Rulings on `ml-bot-policy-v3-implementation.md` §H. These freeze the v3
contract; implementation phases execute against them.

1. **Size approved as proposed**: 1279 observations, K-obstacles 8,
   K-hazards 12, potion slots 12, trunk 512/256, four main heads
   (movement 9 / target 9 / ability 22 / aim 9) + value, choice-event head
   with 56-value option descriptors.
2. **v2 fidelity fix is mandatory** and a Phase V3-2/V3-3 exit gate: patch
   and rays recomputed from exact primitives; the measured 4.5–5.9% error
   class must be eliminated, verified live against native placement tests.
3. **Destructibility**: type-backed `destructible_resolved` only; unknown
   types stay false/unresolved. No mask-guessing.
4. **Telegraph coverage**: launch with what is proven;
   `telegraph_known=0` for unmapped families while identity/facing/raw anim
   remain. Coverage grows post-launch; training does not block on all 19.
5. **Hazard registry rule**: damaging = hostile-sourced effects that apply
   damage/status by contact or area (projectile/area/beam). Excluded: pure
   presentation, friendly/self effects, and summons that are actors (enemy
   block's job). Codex freezes the concrete 46-class partition with
   evidence in the spec. **Unknown new hostile effect classes default to
   included with `type_known=0`** — an unclassified threat must be visible,
   never silently dropped.
6. **Aim head**: discrete center+8 at 60 world units with per-family masks,
   as proposed. Continuous aim deferred.
7. **Choice SMDP approved**: variable-duration GAE as specified, entropy
   0.05 normalized by log(valid options), temperature 1.25 annealing to 1.0
   once every offered family and weld pair has ≥20 selections across the
   training run set (tunable with documented rationale).
8. **Custom potions**: learned use requires the mod to declare
   synthetic-safe `policy_effects` metadata; undeclared custom potions are
   observed (possession) but action-masked off. Stock six unaffected.
9. **Synthetic native use proof is binding**: any stock subtype whose
   participant-scoped native effect path cannot be proven loses its action
   for v3 (observation remains); no offset emulation. Report which, if any.
10. **Equip/unequip deferred** to a future version, affirmed.
11. **Generated gear**: pickup-time effect-summary aggregates suffice for
    v3; a fuller FX grammar is deferred.
12. **Counts**: bounded log1p with saturation at 99; potion slots ranked by
    count descending; overflow beyond 12 types aggregates into the Block Q
    summary.
13. **No recurrence in v3**, affirmed — the ID-tracked history, hazard
    kinematics, and SMDP credit close the demonstrated gaps.

## Process

Phase V3-1 (investigation): answer every numbered question above with
file/RE evidence; produce `docs/ml-bot-policy-v3-implementation.md` with
proposed observation/action/head deltas, seam list, and phase plan;
implement nothing. The orchestrator adjudicates before implementation
phases are dispatched.

## V3-9 — drop-worth observation revision (schema v4)

Owner direction, 2026-08-02. This is a hard observation/model/trajectory
cut from schema 3 to schema 4. There is no compatibility shim, dual-version
runtime, or reused checkpoint. The four-head and choice-head architecture is
unchanged; the observation width becomes 1,333 and the checked-in seed is a
fresh drop-aware bootstrap.

### V3-9 adjudications

- Existing replicated loot and inventory identities are sufficient; no new
  native seam is authorized or required.
- Unknown item families are visible but never aliased to a known category.
- Powerup assist follows the measured collection owner and native range
  constant below.
- Reward semantics are frozen. No pickup shaping is permitted.

Block G keeps four distance-ranked pickup slots. Each slot adds
`type_powerup` and, for Item/Potion carriers, these ordered fields after the
existing eight values:

```text
type_powerup
item_identity_known
item_stock_health
item_stock_mana
item_stock_wizard_chug
item_stock_antidote
item_stock_mind_chug
item_stock_rejuvenation
item_custom
item_is_equipment
item_is_wizard_key
item_stack_count_scaled
item_amount_scaled
```

The six stock-potion categories are exactly the Block O vocabulary. Known
custom-potion subtypes 6 and above set only the aligned `item_custom` family
flag because ground snapshots do not expose their stable content ID. Known
stock equipment is identified as equipment, and Item_Misc type 7012 subtype 1
is identified as a Wizard Key. Unknown/unmapped item families set
`item_identity_known=0` and every categorical descriptor to zero; their
available stack/amount remains observable. An absent slot remains all zero.
Block Q appends `inventory_wizard_key_count_scaled` (log1p, saturation 99)
and `inventory_has_wizard_key`. Because keys are non-stacking, the count is
the number of type-7012/subtype-1 inventory rows, not their stack fields.

Powerup collection has two distinct surfaces. An owned live synthetic-bot
probe placed a Powerup at exact participant contact for two seconds: the drop
remained active and native/replicated Damage x4 ticks remained zero. The same
drop then went through `sd.world.request_loot_pickup`; the authority retired
it and both native and replicated timers became exactly 1,500 ticks. Thus
synthetic participants require the replicated request path. `Bonus_TickPickup`
at `0x006039C0` loads the progression pickup-range stat at `0x00603B46` and
multiplies it by the double `20.0` stored at `0x007DE920` before the squared
distance test. Powerups therefore enter both observation and assist with that
exact 20x multiplier.

Wizard Key possession is observable but crate interaction is not a synthetic
participant action in this revision. The stock Goodie unlock handler at
`0x00646D00` compares the contact actor with `gameplay+0x1358` (the slot-0
actor) before it accesses the slot-0 inventory root at `gameplay+0x13B8` and
calls key removal at `0x005601B0`. A live learned participant acquired a key
through the authority pickup path (`wizard_key_count 0 -> 1`), but direct
Goodie contact left its count at 1. The synthetic-participant design also
explicitly rejects a `local_player_actor`/slot-0 alias
(`docs/reverse-engineering/synthetic-participant-bots-2026-07-26.md`). A fresh
slot-0 probe found owner participant 1 and its live actor, while
`sd.bots.get_inventory_details(1)` returned `available=false`; consequently
the same observation path cannot witness the stock local-player `1 -> 0`
transition.

This is the third tracked stock hard-wired-slot-0 assumption, after XP routing
and enemy targeting. V3-9 ships the key observation and leaves the unreachable
native action explicit. Participant-scoped, host-authoritative, replicated
Goodie interaction belongs to the separate v4 crate-semantics item and
requires an owner decision; it is not authorized here.

No reward term changes. Drop value must be learned through the existing
vitals, damage, own-damage, and own-kill-XP channels. Existing replicated-loot
identity fields and inventory content identities are sufficient; V3-9 adds no
native seam.
