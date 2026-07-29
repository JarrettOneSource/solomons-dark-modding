# ML Bot Policy v2 implementation plan

Status: Phase 1 audit and plan only. No Policy v2 behavior or native API
changes are implemented by this document.

Baseline audited:

- branch: `codex/ml-bot-20260729`
- commit: `519e6e3` (`Add headless ML bot training and player policy`)
- accelerated-simulation parent: `4b972bd`
- approved contract: `docs/ml-bot-policy-v2.md`

## A. Audit results

### 1. `sd.world.get_replicated_loot()`

The snapshot wrapper contains:

```text
authority_participant_id, received_ms, sequence, scene_epoch, run_nonce,
scene_kind, drop_count, drop_total_count, truncated, drops
```

It may also contain `last_pickup_result`, `last_pickup_feedback`, and
`last_gold_feedback`. Evidence:
`SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp:1621-1671`.

Every entry in `drops` has these exact fields:

```text
network_drop_id
object_type_id
native_type_id
kind_id
kind
active
presentation_state
amount
amount_tier
resource_kind
value
motion
progress
auxiliary
item_type_id
item_recipe_uid
item_color_state_valid
item_color_state
item_slot
stack_count
actor_slot
world_slot
lifetime
x
y
radius
position = {x, y}
materialized
presentation_actor_address
local_actor_address
presentation_last_seen_ms
```

Powerup rows additionally have `powerup_kind_id` and `powerup_kind`.
`object_type_id` and `native_type_id` are aliases of the same value;
`resource_kind` and `amount_tier` are also the same stored value. Evidence:
`SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp:377-463`.
The internal snapshot also carries `item_content_id`, but that field is not
marshalled to Lua
(`SolomonDarkModLoader/include/multiplayer_runtime_snapshot_state.inl:1-26`).

Answers:

- Health and mana orbs are distinguishable. Orb capture writes the native
  resource byte into `amount_tier`, and therefore Lua `resource_kind`;
  health is `0`, mana is `1`
  (`SolomonDarkModLoader/src/multiplayer_local_transport/loot_snapshot_capture.inl:113-166`;
  `SolomonDarkModLoader/src/multiplayer_local_transport.cpp:391-394`).
- `network_drop_id` is exposed.
- Position is exposed both as `x`/`y` and `position={x,y}`.
- Type is exposed at three levels: `kind_id`/`kind`, native object type, and
  item type. The drop-kind enum is Unknown, Gold, Item, Potion, Orb, Powerup
  (`SolomonDarkModLoader/include/multiplayer_runtime_protocol.h:164-171`).
- `amount` is exposed.

No loot seam is required for v2. Lua can map Gold directly, split Orb by
`resource_kind`, and collapse Item/Potion into the item-carrier observation.

### 2. Participant state and loadout visibility

#### `sd.bots.get_participant_state(participant_id)`

The binding reads a `BotSnapshot` and returns `nil` when unavailable
(`SolomonDarkModLoader/src/lua_engine_bindings_bots.cpp:292-306`). Its exact
top-level keys today are:

```text
available, id, name, participant_kind, controller_kind, profile, scene,
ready, in_run, runtime_valid, transform_valid, entity_materialized, run_nonce,
position, x, y, heading, hp, max_hp, mp, max_mp, mana_reserve_active,
replicated_persistent_status_flags, native_persistent_status_flags,
replicated_transient_status_flags, native_transient_status_flags,
replicated_poison_remaining_ticks, native_poison_remaining_ticks,
native_webbed_remaining_ticks, native_webbed_strength,
replicated_damage_x4_remaining_ticks, native_damage_x4_remaining_ticks,
replicated_magic_shield_absorb_remaining,
replicated_magic_shield_absorb_capacity,
replicated_magic_shield_explosion_fraction,
replicated_magic_shield_hit_flash,
actor_address, world_address, animation_state_ptr, render_frame_table,
hub_visual_attachment_ptr, hub_visual_source_profile_address,
hub_visual_descriptor_signature, hub_visual_proxy_address,
progression_handle_address, equip_handle_address,
progression_runtime_state_address, equip_runtime_state_address,
gameplay_slot, actor_slot, slot_anim_state_index,
resolved_animation_state_id, hub_visual_source_kind, render_drive_flags,
anim_drive_state, no_interrupt, active_cast_group, active_cast_slot,
render_variant_primary, render_variant_secondary, render_weapon_type,
render_selection_byte, render_variant_tertiary,
cast_pending, cast_active, cast_ready, cast_startup_in_progress,
cast_saw_activity, cast_skill_id, cast_ticks_waiting,
cast_target_actor_address, native_action_cooldown_ticks,
active_spell_object_readable, active_spell_object_address,
active_spell_object_type, active_spell_object_x, active_spell_object_y,
active_spell_object_radius, active_spell_object_charge,
walk_cycle_primary, walk_cycle_secondary, render_drive_stride,
render_advance_rate, render_advance_phase,
magic_shield_absorb_remaining, magic_shield_absorb_capacity,
magic_shield_explosion_fraction, magic_shield_hit_flash,
render_drive_overlay_alpha, render_drive_move_blend,
primary_visual_lane, secondary_visual_lane, attachment_visual_lane,
gameplay_attach_applied, state, moving, has_target, target_x, target_y,
distance_to_target, queued_cast_count, last_queued_cast_ms,
skill_choice_pending, skill_choice_generation, skill_choice_level,
skill_choice_experience, skill_choice_options
```

Evidence for the full marshal is
`SolomonDarkModLoader/src/lua_engine_parser_snapshots.cpp:43-316`.
`target_x` and `target_y` are present with `nil` values when there is no
target.

Nested shapes are:

```text
position = {x, y}

profile = {
  element_id, discipline_id, appearance_choice_ids,
  loadout = {
    primary_entry_index,
    primary_combo_entry_index,
    secondary_entry_indices
  },
  level, experience
}

scene = {kind, region_index, region_type_id}

*_visual_lane = {
  wrapper_address, holder_address, current_object_address, holder_kind,
  current_object_vtable, current_object_type_id, current_object_recipe_uid,
  current_object_color_state_valid, current_object_color_state
}

skill_choice_options[] = {id, apply_count}
```

Evidence:
`SolomonDarkModLoader/src/lua_engine_parser_helpers.cpp:266-282`,
`SolomonDarkModLoader/src/lua_engine_parser_helpers.cpp:535-558`, and
`SolomonDarkModLoader/src/lua_engine_parser_snapshots.cpp:17-39,297-315`.
The native `BotSnapshot` has concentration fields, but the Lua marshal omits
them (`SolomonDarkModLoader/include/bot_runtime.h:168-192`).

#### `sd.runtime.get_multiplayer_state().participants[]`

Each participant row has these exact top-level keys:

```text
participant_id, steam_id, name, kind, controller_kind, ready, is_owner,
transport_connected, transport_using_relay, last_packet_ms,
runtime_valid, in_run, run_nonce, level, wave, experience_current,
experience_next, scene_kind, life_current, life_max, mana_current, mana_max,
move_speed, anim_drive_state, presentation_flags, death_presentation_tick,
persistent_status_flags, transient_status_flags, poison_remaining_ticks,
damage_x4_remaining_ticks, x, y, heading, movement_intent_x,
movement_intent_y, equipment, owned_progression
```

Evidence:
`SolomonDarkModLoader/src/lua_engine_bindings_runtime.cpp:725-832`.

`equipment` is:

```text
{
  valid,
  revision,
  primary = {type_id, recipe_uid, color_state},
  secondary = {type_id, recipe_uid, color_state},
  attachment = {type_id, recipe_uid},
  hat = {type_id, recipe_uid},
  robe = {type_id, recipe_uid},
  weapon = {type_id, recipe_uid},
  rings[] = {type_id, recipe_uid},
  amulet = {type_id, recipe_uid}
}
```

Evidence:
`SolomonDarkModLoader/src/lua_engine_bindings_runtime/participant_equipment_state.inl:1-68`.

`owned_progression` has these exact keys, with the noted optional tables:

```text
initialized, gold, gold_revision, inventory_revision, equipment_revision,
spellbook_revision, statbook_revision, loadout_revision,
concentration_revision, concentration_selection_valid,
concentration_entry_a, concentration_entry_b, derived_stat_revision,
derived_stats?, hagatha_perk_revision, hagatha_perks?,
inventory_host_authoritative, inventory_item_total_count,
inventory_item_count, inventory_truncated, inventory_items, equipment,
progression_book_entry_total_count, progression_book_entry_count,
progression_book_truncated, progression_book_entries,
statbook_entry_count, statbook_entries,
skillbook_entry_total_count, skillbook_entry_count, skillbook_truncated,
skillbook_entries,
spellbook_entry_total_count, spellbook_entry_count, spellbook_truncated,
spellbook_entries,
ability_loadout?
```

Its nested shapes are:

```text
derived_stats = {
  cast_speed_multiplier, mana_recovery_multiplier,
  resist_magic_fraction, resist_poison_fraction, deflect_chance,
  staff_melee_damage_a, staff_melee_damage_b, pickup_range,
  secondary_recharge_multiplier, offensive_damage_multiplier,
  offensive_mana_multiplier, melee_damage_multiplier, push_strength,
  meditation_recovery_bonus, meditation_idle_ticks
}

hagatha_perks = {
  perk_count, perk_capacity, cheat_death_charges,
  serendipity_active, reverie_active, selectors, valid
}

inventory_items[] = {
  type_id, recipe_uid, slot, stack_count, parent_item_index, container_depth
}

owned_progression.equipment = {
  valid,
  hat = {type_id, recipe_uid},
  robe = {type_id, recipe_uid},
  weapon = {type_id, recipe_uid},
  rings[] = {type_id, recipe_uid},
  amulet = {type_id, recipe_uid}
}

*_book_entries[] = {
  entry_index, internal_id, active, visible, category, statbook_max_level
}

ability_loadout = {
  primary_entry_index, primary_combo_entry_index, secondary_entry_indices
}
```

Evidence:
`SolomonDarkModLoader/src/lua_engine_bindings_runtime.cpp:32-82,129-293`.

#### Answers about the missing state

- Per-secondary-slot readiness/recharge is not exposed anywhere. The bot row
  exposes only global `cast_ready` and `native_action_cooldown_ticks`; the
  runtime row exposes only the global derived
  `secondary_recharge_multiplier`. Global readiness is derived from life,
  any mana, the one action cooldown, and pending/active cast state
  (`SolomonDarkModLoader/src/bot_runtime/helpers/snapshot_builders.inl:76-100`).
  Cast admission checks the same global action cooldown
  (`SolomonDarkModLoader/src/bot_runtime/public_api/casting_api.inl:72-90`).
- The active primary build is not semantically exposed. Lua can see the
  profile/loadout entry pair and raw progression addresses, but it cannot see
  progression `+0x844` or a resolved weld build. The relevant native layout is
  current spell `+0x750`, primary stat vector `+0x774/+0x778`, and special
  choice/build argument `+0x844`
  (`config/binary-layout.ini:1711-1715`). A mod with `sd.debug` could perform a
  raw address read, but that is not a supported, address-free gameplay API.

### 3. `sd.bots.get_skill_choices()`

The exact return shape is:

```text
{
  pending,
  generation,
  level,
  experience,
  options[] = {id, apply_count}
}
```

Evidence:
`SolomonDarkModLoader/src/lua_engine_bindings_bots.cpp:358-395`.

Option 52 can surface. The native roll copier accepts every nonnegative option
ID and performs no filter that could remove 52
(`SolomonDarkModLoader/src/bot_runtime/helpers/skill_choices.inl:151-220`).
The configured special choice is `0x34` (52)
(`config/binary-layout.ini:1867-1870`), and applying that option invokes the
special activation and post-refresh paths
(`SolomonDarkModLoader/src/bot_runtime/helpers/skill_choices.inl:503-513,558-569`).

The rolled weld pair/build ID is not visible. `BotSkillChoiceSnapshot` stores
only the fields above
(`SolomonDarkModLoader/include/bot_runtime.h:116-128`). The application path
reads progression `+0x844` and passes it to the special native virtual without
publishing it
(`SolomonDarkModLoader/src/bot_runtime/helpers/skill_choices.inl:372-408`).
The RE proves that the roll writes one of builds 1000-1009 to `+0x844`
(`docs/reverse-engineering/spell-welding.md:34-45,62-82`).

### 4. Native skill catalog as a static property table

It is not a complete `entry_id -> {mana_cost, range, cooldown}` table.

The JSON top level has `schema`, `source`, `summary`, and `skills`. Each normal
skill entry has:

```text
id, name, family, skills_atlas_icon_record, config_path, config_sha256,
config, raw_values
```

Runtime-only IDs 80 and 81 omit `config_sha256` and `raw_values` and have
`config_path: null`, `config: null`
(`docs/reverse-engineering/native-skill-catalog.json:1-77,4008-4023`).

`config` contains a typed subset, and `raw_values` the corresponding source
text subset, of these 43 property names:

```text
mAbsorb, mArcs, mArmorPlus, mBonus, mCapLevel, mChance, mCharges,
mConcentration, mCooldown, mDamage, mDamage1, mDamage2, mDescription,
mDuration, mFlee, mFragments, mFreeze, mHP, mHoard, mLoss, mManaCost,
mMaxArmor, mMaxLevel, mPercent, mPierces, mPushback, mQDescription,
mQuantity, mRadius, mReflect, mSeconds, mSize, mSlow, mSlowdown, mSpeed,
mSpeedUp, mStats, mStrength, mStunAmount, mToHit, mValue, mWeaken, mWiden
```

Evidence:
`docs/reverse-engineering/native-skill-catalog.json:13-62`.

There is no `mRange`. `mManaCost` appears in only 48 of 80 CFGs,
`mCooldown` in only 2, and `mRadius` in only 2. Values such as `mManaCost` and
`mCooldown` are generally rank-indexed arrays rather than one effective
runtime scalar. The two known cooldown CFGs are Phasing 15 and Teleport 48
(`docs/reverse-engineering/native-skill-catalog.json:628-659,2591-2635`).
The RE identifies the live native mana resolver and only those two proven
cooldown-state rows
(`docs/reverse-engineering/native-skills-and-spells.md:120-140,167-186,282-284`).
The secondary dispatcher enforces mana through native routines but does not
provide a general static range table
(`docs/reverse-engineering/native-skills-and-spells.md:608-640`).

Lua can load the JSON and build an ID-keyed index, but it cannot honestly fill
all three v2 properties from it. It is a partial fallback, not the primary
property source.

### 5. `sd.nav.get_grid()`

The public top-level shape is:

```text
{
  width, height, cell_width, cell_height, probe_x, probe_y,
  subdivisions, requested_subdivisions, refresh_pending,
  cells[] = {
    grid_x, grid_y, center_x, center_y, traversable, path_traversable,
    samples[] = {
      sample_x, sample_y, world_x, world_y, traversable
    }
  }
}
```

Subdivisions must be 1-4. The call schedules an asynchronous rebuild and can
return an older same-world snapshot with `refresh_pending=true`
(`SolomonDarkModLoader/src/lua_engine_bindings_foundations.cpp:88-181`).
Rebuilds are limited to once per 500 ms and the cache is cleared on scene
unload
(`SolomonDarkModLoader/src/mod_loader_gameplay/nav_grid_snapshot_service.inl:1-62`).

The exact coordinate convention is unusual but sufficient:

- `grid_x` iterates `0 .. width-1` and is the world-Y axis.
- `grid_y` iterates `0 .. height-1` and is the world-X axis.
- Flat cell index is `height * grid_x + grid_y`.
- The implicit origin is `(0,0)`.
- `center_x = (grid_y + 0.5) * cell_width`.
- `center_y = (grid_x + 0.5) * cell_height`.
- World X bounds are `[0, height * cell_width)`.
- World Y bounds are `[0, width * cell_height)`.
- `grid_x = floor(world_y / cell_height)`;
  `grid_y = floor(world_x / cell_width)`.
- Out-of-bounds is blocked.

Evidence:
`SolomonDarkModLoader/src/mod_loader_gameplay/bot_pathfinding_cell_math.inl:1-73`
and
`SolomonDarkModLoader/src/mod_loader_gameplay/public_api_debug_and_spawn.inl:337-420`.

For subdivision count `n`, each cell has `n*n` samples:

```text
world_x = grid_y * cell_width
        + ((sample_y + 0.5) / n) * cell_width
world_y = grid_x * cell_height
        + ((sample_x + 0.5) / n) * cell_height
```

`traversable` is a player-sized native placement test at the cell center;
`path_traversable` is the path-cell predicate; sample `traversable` is the
same placement test at the sample coordinate. All three are Lua booleans, not
bit flags. Grid dimensions and cell sizes are live values read from the
movement controller
(`SolomonDarkModLoader/src/mod_loader_gameplay/bot_pathfinding_grid_setup.inl:157-204`).

Conclusion: this is enough to compute both the 7x7 patch and eight rays in pure
Lua from one cached `get_grid(2)` snapshot. Lua should construct a direct
`grid_x/grid_y -> cell` index, map each requested world point to its containing
cell and nearest subdivision sample, and treat missing/out-of-bounds points as
blocked. It should wait for `refresh_pending=false` before freezing the
scene-epoch cache. The movement legality mask continues using
`sd.nav.test_segment`.

One caveat is material: the returned placement values include the live
player's radius/masks, static circles, and participant obstacles
(`docs/lua-nav.md:59-65`). The contract calls this grid “static per scene,” but
the current producer can encode dynamic participant occupancy at rebuild time.
That requires an owner decision in section E.

### 6. Headless training, launch, and boneyard rotation

The current live command is:

```powershell
py -3 tools/train_bot_policy.py live-ppo `
  --game-directory "C:\path\to\SolomonDarkAbandonware" `
  --iterations 10 `
  --rollout-steps 1024
```

Evidence: `docs/ml-bot.md:101-116`.

`live_ppo()` creates one `SoloSession`, launches one process, drives New Game to
the hub, installs one policy, enables god mode, starts one test run, constructs
the training arena, and then reuses that run for every PPO iteration. Each
iteration only clears/enables the trajectory recorder, collects steps, trains,
exports, and hot-loads weights
(`tools/train_bot_policy.py:350-567`). The seed passed at
`tools/train_bot_policy.py:426-431` reaches
`policy_training.lua`'s policy sampler RNG; it only starts a new trajectory
episode and does not seed arena generation
(`mods/bot-brain/scripts/policy.lua:225-232`;
`mods/bot-brain/scripts/policy_training.lua:161-174`).

`SoloSession.launch()` invokes `scripts/Launch-LocalSoloSession.ps1` through
PowerShell with a fixed hub preset, fresh install, multiplayer disabled,
exactly `bot.brain`, and headless mode by default
(`tools/ml_bot/bridge.py:517-692`). `start_test_run()` calls only
`sd.hub.start_testrun`
(`tools/ml_bot/bridge.py:1175-1204`). The solo launcher accepts a blank
boneyard and wave override, but no generation seed and no survival-boneyard
override (`scripts/Launch-LocalSoloSession.ps1:1-22,65-94`).

The native boneyard seed is controllable today, just not wired into this
harness. `sd.rng.set_seed(seed)` is authority-only, accepts
`1..0x3fffffff`, and must be called before entering a run
(`SolomonDarkModLoader/src/lua_engine_bindings_foundations.cpp:51-85`;
`docs/lua-rng.md:17-39`). Scene entry consumes the pending seed and initializes
the native RNG
(`SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_gameplay_thread_dispatch.inl:120-126`;
`SolomonDarkModLoader/src/mod_loader_gameplay/core/run_generation_seed_helpers.inl:137-166`).
The stock boneyard generator's first draw derives its six-digit logged seed
from that run seed
(`docs/reverse-engineering/native-default-boneyard-load-seed-and-decor.md:117-163`).

The seed hook belongs in `SoloSession` after reaching the hub and immediately
before `start_test_run()`:

```text
sd.rng.set_seed(run_seed)
assert(sd.rng.get_seed() == run_seed)
sd.hub.start_testrun()
```

The seed and resulting `run_nonce` must be included in the episode log. A PPO
iteration is not currently a new run, so merely adding this call once would
not satisfy the contract. Each training episode must tear down the prior run
and enter a newly seeded one.

For layout rotation, the existing multiplayer launchers already validate and
set `SDMOD_TEST_SURVIVAL_BONEYARD_OVERRIDE`
(`scripts/Launch-LocalMultiplayerPair.ps1:297-304,373-374`), but the solo
launcher and `SoloSession` do not. Add the same validated parameter at those
two layers, select the next layout before launching an episode, and log its
path/hash.

The safe initial implementation is a disposable `SoloSession` per environment
episode. The authored scene API cannot leave an arena directly; it requires
the stock Leave Game UI
(`docs/lua-scene.md:36-42`), and a prior raw arena-to-hub debug switch faulted
(`docs/npc-ally-investigation.md:614-621`). Reusing a process should be a later
throughput optimization only after reliable stock Leave Game automation is
verified.

### 7. Reward shaping and wrapper-selected targets

The current reward copies only self HP/mana, wave, alive, enemy count, and an
actor-ID-keyed map of all enemy health. It awards:

- `+0.002` survival per decision;
- self HP delta times `1.25`;
- any tracked enemy HP reduction times `0.65`;
- positive wave progress times `1.5`;
- `-2.0` for terminal death;
- final clamp to `[-4,4]`.

Evidence:
`mods/bot-brain/scripts/policy_training.lua:21-34,74-98`.

No reward term reads the wrapper's chosen target, target ID, target HP summary,
or cast target. The Python trainer only validates records, groups GAE by
`(episode_id, participant_id)`, and consumes recorded rewards
(`tools/train_bot_policy.py:201-306`);
the GAE implementation is target-agnostic
(`tools/ml_bot/model.py:608-643`). Existing reward shaping therefore does not
assume a wrapper-selected target and can remain unchanged.

The bootstrap expert is separate from reward shaping and does assume the v1
wrapper target. Its movement and cast rules read the single target block
(`tools/ml_bot/expert.py:65-133`), and its synthetic data builds that target
before making every secondary legal against it
(`tools/ml_bot/expert.py:190-225,351-355`). It cannot be reused unchanged for
v2.

## B. Minimal native seams

### Public seam: one deep, address-free loadout query

Add exactly one new public semantic query:

```lua
sd.bots.get_loadout_details(participant_id) -> table|nil
```

Proposed shape:

```lua
{
  participant_id = 0,

  primary = {
    entry_id = 0,
    combo_entry_id = 0,
    build_id = 0,                 -- base entry 8/16/24/32/40 or weld 1000-1009
    build_id_resolved = false,
    mana_cost = 0.0,              -- effective native spend cost
    mana_cost_resolved = false,
    mana_charge_kind = "per_cast", -- or "per_second"
    range_min = 0.0,
    range_max = 0.0,
    range_resolved = false,
    range_source = "unresolved",
  },

  secondaries = {
    {
      slot = 1,                   -- always eight rows, stable slot order
      entry_id = -1,
      mana_cost = 0.0,            -- effective native spend cost
      mana_cost_resolved = false,
      cooldown_seconds = 0.0,
      cooldown_remaining_seconds = 0.0,
      cooldown_resolved = false,
    },
    -- slots 2..8
  },

  pending_weld_build_id = 0,      -- 1000-1009 only while option 52 is pending
  pending_weld_build_id_resolved = false,
}
```

No process address, native vector address, or exception code crosses this API.
Unresolved semantic values use a value plus an explicit `*_resolved=false`;
Lua decides the contract fallback and derives `welded`/`ready` itself. The
interface is deliberately a deep loadout module: one read returns all
irreducibly native spell semantics atomically. Its implementation caches by
the already-replicated loadout, spellbook, statbook, and derived-stat revision
tuple; those revisions are not duplicated in the public result.

The native work behind this single public seam is:

1. **Active primary and pending weld build classification.**
   Read/capture progression `+0x844`, but do not expose it as an untyped raw
   integer. RE identifies it as the selected/current synthetic weld build
   consumed by roll, presentation, and activation
   (`docs/reverse-engineering/spell-welding.md:34-45,62-88`;
   `config/binary-layout.ini:1711-1715`). The option roll must capture
   `+0x844` into the pending choice record when option 52 is present; applying
   52 must promote that captured value to the participant's active weld state.
   With no pending choice, the live primary builder/current-spell state and
   active special row are used to reconstruct an already-loaded active weld.
   Base primaries are normalized back to entry IDs 8/16/24/32/40; the native
   same-element synthetic IDs are 0x3F2-0x3F6
   (`docs/reverse-engineering/spell-welding.md:108-136`).

2. **Effective primary cost.**
   Reuse `TryResolveNativePrimarySpellStats`, which already returns effective
   spend cost and continuous/per-cast classification
   (`SolomonDarkModLoader/include/native_spell_stats.h:11-36,68-72`;
   `SolomonDarkModLoader/src/native_spell_stats/primary_and_secondary_resolution.inl:222-359`).
   Its builder is native `0x00666020`
   (`config/binary-layout.ini:915`), whose output vector and multiplier-aware
   reconstruction are documented at
   `docs/reverse-engineering/spell-welding.md:108-141`.

3. **Effective secondary cost.**
   Reuse `TryResolveNativeSecondarySpellManaStats`
   (`SolomonDarkModLoader/include/native_spell_stats.h:38-45,73-77`;
   `SolomonDarkModLoader/src/native_spell_stats/primary_and_secondary_resolution.inl:362-459`).
   It composes `Skills_Wizard::GetSecondaryManaCost` at `0x0065E760` and the
   stat-book cost modifier at `0x006600F0`
   (`config/binary-layout.ini:849-850`;
   `docs/reverse-engineering/native-skills-and-spells.md:138-140,282-284`).

4. **The only proven per-slot cooldown/readiness state.**
   Add semantic row reads for Phasing 15 and Teleport 48. The progression skill
   table is at `+0x20`, has count at `+0x24`, and stride `0x70`
   (`config/binary-layout.ini:1264-1266`). RE proves current/cap fields at
   row-relative `+0x64/+0x68`: for ID 15 these become
   `+0x6F4/+0x6F8`; for ID 48, `+0x1564/+0x1568`
   (`docs/reverse-engineering/native-skills-and-spells.md:142-186`).
   Phase 2 must live-probe their units/types before converting to seconds.
   Every other native secondary returns `cooldown_resolved=false`; Lua derives
   readiness from resolved remaining cooldown where available and otherwise
   uses global `cast_ready`, exactly as the approved fallback requires. There
   is no evidence for a generic per-secondary recharge lane, so this plan does
   not invent one.

5. **Weld-aware primary range through the existing producer.**
   Fold the existing primary attack-window resolver into the new table and
   have `sd.bots.get_primary_attack_window` delegate to the same semantic
   producer. It currently reads either the actor selection state's pursuit
   range or the Water global
   (`SolomonDarkModLoader/src/lua_engine_bindings_bots.cpp:51-125,537-576`;
   `config/binary-layout.ini:1240,1596-1606`;
   `docs/lua-bot-constants-re.md:45-62`). It must select the Water special case
   from the active primary build, not merely the profile element, and be
   revalidated after a weld activates.

The primary-stat builder can modify `+0x750` and rebuild the vector at
`+0x774/+0x778`. The debug query currently exposes those effects directly
(`SolomonDarkModLoader/src/lua_engine_bindings_debug/functions_native_calls.inl:447-545`).
The gameplay seam must be side-effect-safe: preserve/restore affected
selection state or cache a previously refreshed result by the revision tuple.
It must not invoke a mutating native builder every 100 ms without that guard.

### Explicitly no new native seam

These values remain Lua-owned because the necessary state is already
replicated/public:

- element one-hot and band index from entry ID;
- primary multi-hot, welded flag, and scaled build index from build ID;
- affordability from mana and effective cost;
- target-relative range tests;
- `has_spell_welding_skill` from progression-book entry 52;
- `weld_offer_pending` from `get_skill_choices().options`;
- loot type, orb subtype, amount, identity, and position;
- enemy sorting and velocity deltas keyed by `network_actor_id`;
- navigation cache indexing, 7x7 patch, and clearance rays;
- pickup sorting/counting and auto-pickup policy;
- custom-spell range/cooldown/mana from the Lua registered-spell config.

There is no new loot seam, navigation seam, enemy-velocity seam, property-table
seam, or target-selection seam.

## C. Final v2 observation layout

The literal reading of the approved blocks gives:

| Block | Count |
| --- | ---: |
| A — self | 15 |
| B — active primary | 11 |
| C — 8 secondaries x 13 | 104 |
| D — 8 enemies x 10 | 80 |
| E — selected target | 10 |
| F — 8 rays + 48 patch cells | 56 |
| G — 4 pickups x 8 + count | 33 |
| I — 4 allies x 10 + count | 41 |
| H — aggregates/config/history/weld flags/multipliers | 45 |
| **Total** | **395** |

The adjudicated total is 395. Block I is placed after pickups and before
Block H. The health/mana orb split increases each pickup row from seven to
eight, and the four progression-derived combat multipliers are appended to
Block H. Block H otherwise retains only the categories explicitly named by
v2; the old inventory, equipment, progression, `primary_available`, and eight
bare secondary availability values are not silently retained.

The definitive order and names are:

```text
001 self_hp_ratio
002 self_mana_ratio
003 self_level_scaled
004 wave_scaled
005 self_move_speed_scaled
006 self_moving
007 self_cast_active
008 self_cast_ready
009 self_poisoned
010 self_webbed
011 self_damage_x4
012 self_status_active
013 self_mana_current_scaled
014 self_mana_max_scaled
015 self_hp_max_scaled
016 primary_element_fire
017 primary_element_water
018 primary_element_earth
019 primary_element_air
020 primary_element_ether
021 primary_welded
022 primary_build_index_scaled
023 primary_mana_cost_scaled
024 primary_range_min_scaled
025 primary_range_max_scaled
026 primary_affordable
027 secondary_1_occupied
028 secondary_1_element_fire
029 secondary_1_element_water
030 secondary_1_element_earth
031 secondary_1_element_air
032 secondary_1_element_ether
033 secondary_1_band_index_scaled
034 secondary_1_mana_cost_scaled
035 secondary_1_range_scaled
036 secondary_1_cooldown_scaled
037 secondary_1_ready
038 secondary_1_affordable
039 secondary_1_in_range_of_target
040 secondary_2_occupied
041 secondary_2_element_fire
042 secondary_2_element_water
043 secondary_2_element_earth
044 secondary_2_element_air
045 secondary_2_element_ether
046 secondary_2_band_index_scaled
047 secondary_2_mana_cost_scaled
048 secondary_2_range_scaled
049 secondary_2_cooldown_scaled
050 secondary_2_ready
051 secondary_2_affordable
052 secondary_2_in_range_of_target
053 secondary_3_occupied
054 secondary_3_element_fire
055 secondary_3_element_water
056 secondary_3_element_earth
057 secondary_3_element_air
058 secondary_3_element_ether
059 secondary_3_band_index_scaled
060 secondary_3_mana_cost_scaled
061 secondary_3_range_scaled
062 secondary_3_cooldown_scaled
063 secondary_3_ready
064 secondary_3_affordable
065 secondary_3_in_range_of_target
066 secondary_4_occupied
067 secondary_4_element_fire
068 secondary_4_element_water
069 secondary_4_element_earth
070 secondary_4_element_air
071 secondary_4_element_ether
072 secondary_4_band_index_scaled
073 secondary_4_mana_cost_scaled
074 secondary_4_range_scaled
075 secondary_4_cooldown_scaled
076 secondary_4_ready
077 secondary_4_affordable
078 secondary_4_in_range_of_target
079 secondary_5_occupied
080 secondary_5_element_fire
081 secondary_5_element_water
082 secondary_5_element_earth
083 secondary_5_element_air
084 secondary_5_element_ether
085 secondary_5_band_index_scaled
086 secondary_5_mana_cost_scaled
087 secondary_5_range_scaled
088 secondary_5_cooldown_scaled
089 secondary_5_ready
090 secondary_5_affordable
091 secondary_5_in_range_of_target
092 secondary_6_occupied
093 secondary_6_element_fire
094 secondary_6_element_water
095 secondary_6_element_earth
096 secondary_6_element_air
097 secondary_6_element_ether
098 secondary_6_band_index_scaled
099 secondary_6_mana_cost_scaled
100 secondary_6_range_scaled
101 secondary_6_cooldown_scaled
102 secondary_6_ready
103 secondary_6_affordable
104 secondary_6_in_range_of_target
105 secondary_7_occupied
106 secondary_7_element_fire
107 secondary_7_element_water
108 secondary_7_element_earth
109 secondary_7_element_air
110 secondary_7_element_ether
111 secondary_7_band_index_scaled
112 secondary_7_mana_cost_scaled
113 secondary_7_range_scaled
114 secondary_7_cooldown_scaled
115 secondary_7_ready
116 secondary_7_affordable
117 secondary_7_in_range_of_target
118 secondary_8_occupied
119 secondary_8_element_fire
120 secondary_8_element_water
121 secondary_8_element_earth
122 secondary_8_element_air
123 secondary_8_element_ether
124 secondary_8_band_index_scaled
125 secondary_8_mana_cost_scaled
126 secondary_8_range_scaled
127 secondary_8_cooldown_scaled
128 secondary_8_ready
129 secondary_8_affordable
130 secondary_8_in_range_of_target
131 enemy_1_present
132 enemy_1_dx
133 enemy_1_dy
134 enemy_1_distance_scaled
135 enemy_1_hp_ratio
136 enemy_1_radius_scaled
137 enemy_1_velocity_dx
138 enemy_1_velocity_dy
139 enemy_1_in_primary_range
140 enemy_1_is_current_target
141 enemy_2_present
142 enemy_2_dx
143 enemy_2_dy
144 enemy_2_distance_scaled
145 enemy_2_hp_ratio
146 enemy_2_radius_scaled
147 enemy_2_velocity_dx
148 enemy_2_velocity_dy
149 enemy_2_in_primary_range
150 enemy_2_is_current_target
151 enemy_3_present
152 enemy_3_dx
153 enemy_3_dy
154 enemy_3_distance_scaled
155 enemy_3_hp_ratio
156 enemy_3_radius_scaled
157 enemy_3_velocity_dx
158 enemy_3_velocity_dy
159 enemy_3_in_primary_range
160 enemy_3_is_current_target
161 enemy_4_present
162 enemy_4_dx
163 enemy_4_dy
164 enemy_4_distance_scaled
165 enemy_4_hp_ratio
166 enemy_4_radius_scaled
167 enemy_4_velocity_dx
168 enemy_4_velocity_dy
169 enemy_4_in_primary_range
170 enemy_4_is_current_target
171 enemy_5_present
172 enemy_5_dx
173 enemy_5_dy
174 enemy_5_distance_scaled
175 enemy_5_hp_ratio
176 enemy_5_radius_scaled
177 enemy_5_velocity_dx
178 enemy_5_velocity_dy
179 enemy_5_in_primary_range
180 enemy_5_is_current_target
181 enemy_6_present
182 enemy_6_dx
183 enemy_6_dy
184 enemy_6_distance_scaled
185 enemy_6_hp_ratio
186 enemy_6_radius_scaled
187 enemy_6_velocity_dx
188 enemy_6_velocity_dy
189 enemy_6_in_primary_range
190 enemy_6_is_current_target
191 enemy_7_present
192 enemy_7_dx
193 enemy_7_dy
194 enemy_7_distance_scaled
195 enemy_7_hp_ratio
196 enemy_7_radius_scaled
197 enemy_7_velocity_dx
198 enemy_7_velocity_dy
199 enemy_7_in_primary_range
200 enemy_7_is_current_target
201 enemy_8_present
202 enemy_8_dx
203 enemy_8_dy
204 enemy_8_distance_scaled
205 enemy_8_hp_ratio
206 enemy_8_radius_scaled
207 enemy_8_velocity_dx
208 enemy_8_velocity_dy
209 enemy_8_in_primary_range
210 enemy_8_is_current_target
211 target_present
212 target_dx
213 target_dy
214 target_distance_scaled
215 target_contact_distance_scaled
216 target_hp_ratio
217 target_radius_scaled
218 target_in_primary_range
219 primary_min_range_scaled
220 primary_max_range_scaled
221 clearance_east_scaled
222 clearance_southeast_scaled
223 clearance_south_scaled
224 clearance_southwest_scaled
225 clearance_west_scaled
226 clearance_northwest_scaled
227 clearance_north_scaled
228 clearance_northeast_scaled
229 walkability_patch_row_1_col_1
230 walkability_patch_row_1_col_2
231 walkability_patch_row_1_col_3
232 walkability_patch_row_1_col_4
233 walkability_patch_row_1_col_5
234 walkability_patch_row_1_col_6
235 walkability_patch_row_1_col_7
236 walkability_patch_row_2_col_1
237 walkability_patch_row_2_col_2
238 walkability_patch_row_2_col_3
239 walkability_patch_row_2_col_4
240 walkability_patch_row_2_col_5
241 walkability_patch_row_2_col_6
242 walkability_patch_row_2_col_7
243 walkability_patch_row_3_col_1
244 walkability_patch_row_3_col_2
245 walkability_patch_row_3_col_3
246 walkability_patch_row_3_col_4
247 walkability_patch_row_3_col_5
248 walkability_patch_row_3_col_6
249 walkability_patch_row_3_col_7
250 walkability_patch_row_4_col_1
251 walkability_patch_row_4_col_2
252 walkability_patch_row_4_col_3
253 walkability_patch_row_4_col_5
254 walkability_patch_row_4_col_6
255 walkability_patch_row_4_col_7
256 walkability_patch_row_5_col_1
257 walkability_patch_row_5_col_2
258 walkability_patch_row_5_col_3
259 walkability_patch_row_5_col_4
260 walkability_patch_row_5_col_5
261 walkability_patch_row_5_col_6
262 walkability_patch_row_5_col_7
263 walkability_patch_row_6_col_1
264 walkability_patch_row_6_col_2
265 walkability_patch_row_6_col_3
266 walkability_patch_row_6_col_4
267 walkability_patch_row_6_col_5
268 walkability_patch_row_6_col_6
269 walkability_patch_row_6_col_7
270 walkability_patch_row_7_col_1
271 walkability_patch_row_7_col_2
272 walkability_patch_row_7_col_3
273 walkability_patch_row_7_col_4
274 walkability_patch_row_7_col_5
275 walkability_patch_row_7_col_6
276 walkability_patch_row_7_col_7
277 pickup_1_present
278 pickup_1_dx
279 pickup_1_dy
280 pickup_1_distance_scaled
281 pickup_1_type_gold
282 pickup_1_type_health_orb
283 pickup_1_type_mana_orb
284 pickup_1_type_item_carrier
285 pickup_2_present
286 pickup_2_dx
287 pickup_2_dy
288 pickup_2_distance_scaled
289 pickup_2_type_gold
290 pickup_2_type_health_orb
291 pickup_2_type_mana_orb
292 pickup_2_type_item_carrier
293 pickup_3_present
294 pickup_3_dx
295 pickup_3_dy
296 pickup_3_distance_scaled
297 pickup_3_type_gold
298 pickup_3_type_health_orb
299 pickup_3_type_mana_orb
300 pickup_3_type_item_carrier
301 pickup_4_present
302 pickup_4_dx
303 pickup_4_dy
304 pickup_4_distance_scaled
305 pickup_4_type_gold
306 pickup_4_type_health_orb
307 pickup_4_type_mana_orb
308 pickup_4_type_item_carrier
309 pickup_count_scaled
310 ally_1_present
311 ally_1_dx
312 ally_1_dy
313 ally_1_distance_scaled
314 ally_1_hp_ratio
315 ally_1_mana_ratio
316 ally_1_alive
317 ally_1_is_human
318 ally_1_intent_dx
319 ally_1_intent_dy
320 ally_2_present
321 ally_2_dx
322 ally_2_dy
323 ally_2_distance_scaled
324 ally_2_hp_ratio
325 ally_2_mana_ratio
326 ally_2_alive
327 ally_2_is_human
328 ally_2_intent_dx
329 ally_2_intent_dy
330 ally_3_present
331 ally_3_dx
332 ally_3_dy
333 ally_3_distance_scaled
334 ally_3_hp_ratio
335 ally_3_mana_ratio
336 ally_3_alive
337 ally_3_is_human
338 ally_3_intent_dx
339 ally_3_intent_dy
340 ally_4_present
341 ally_4_dx
342 ally_4_dy
343 ally_4_distance_scaled
344 ally_4_hp_ratio
345 ally_4_mana_ratio
346 ally_4_alive
347 ally_4_is_human
348 ally_4_intent_dx
349 ally_4_intent_dy
350 ally_count_scaled
351 enemy_count_scaled
352 threat_count_scaled
353 nearest_enemy_dx
354 nearest_enemy_dy
355 nearest_enemy_distance_scaled
356 nearest_threat_dx
357 nearest_threat_dy
358 nearest_threat_distance_scaled
359 escape_dx
360 escape_dy
361 suggested_move_dx
362 suggested_move_dy
363 arena_center_dx
364 arena_center_dy
365 arena_center_distance_scaled
366 arena_x_normalized
367 arena_y_normalized
368 edge_pressure
369 element_fire
370 element_water
371 element_earth
372 element_air
373 element_ether
374 discipline_mind
375 discipline_body
376 discipline_arcane
377 hp_delta
378 mana_delta
379 target_hp_delta
380 enemy_count_delta
381 previous_move_dx
382 previous_move_dy
383 previous_cast_primary
384 previous_cast_secondary
385 time_since_damage_scaled
386 time_since_cast_scaled
387 time_since_move_scaled
388 previous_target_action_scaled
389 previous_target_switched
390 has_spell_welding_skill
391 weld_offer_pending
392 offensive_damage_multiplier_scaled
393 offensive_mana_multiplier_scaled
394 cast_speed_multiplier_scaled
395 secondary_recharge_multiplier_scaled
```

Ordering rules behind the literal list:

- enemies, pickups, and allies are nearest-first with deterministic
  actor/drop/participant-ID tiebreaks;
- patch rows are world-Y north-to-south and columns world-X west-to-east,
  row-major, with row 4/column 4 omitted;
- clearance direction order exactly matches movement actions 2-9;
- `primary_range_min_scaled`/`primary_range_max_scaled` in Block B describe the
  active build, while the legacy-named
  `primary_min_range_scaled`/`primary_max_range_scaled` remain in the retained
  target block. They currently carry the same live window but remain separate
  contract positions;
- `primary_build_index_scaled` maps base primaries in native skill-band order
  (Ether, Fire, Air, Water, Earth) to `0.0, 0.2, 0.4, 0.6, 0.8`; weld builds
  map exactly as `(build_id - 1000) / 10`, from `0.0` through `0.9`. The
  primary element multi-hot disambiguates the deliberate numeric overlap.

## D. File-by-file Phase 2-5 plan

### Phase 2 — native seams

- `config/binary-layout.ini`
  - Add named skill-row current/cap cooldown offsets `0x64/0x68` only after the
    live type/unit probe. Reuse the existing table base/count/stride, current
    spell, stat vector, special build argument, and native function addresses.
- `SolomonDarkModLoader/src/gameplay_seams/progression_and_actor_offsets.inl`,
  `SolomonDarkModLoader/src/gameplay_seams/address_storage.inl`, and
  `SolomonDarkModLoader/src/gameplay_seams/size_bindings.inl`
  - Bind only the two new row offsets if the probe confirms them. Do not add
    per-spell hard-coded addresses.
- `SolomonDarkModLoader/include/native_spell_stats.h`
  - Add address-free result records for active primary details, pending weld
    identity, and resolved cooldown state.
- `SolomonDarkModLoader/src/native_spell_stats.cpp` and
  `SolomonDarkModLoader/src/native_spell_stats/primary_and_secondary_resolution.inl`
  - Make primary resolution observation-safe, add normalized base/weld build
    classification, and add validated ID-15/48 cooldown reads.
- `SolomonDarkModLoader/include/bot_runtime.h`
  - Add the public loadout-detail snapshot and eight fixed secondary rows; add
    internal pending/active weld capture fields.
- `SolomonDarkModLoader/src/bot_runtime/helpers/skill_choices.inl`
  - Capture the rolled `+0x844` build when option 52 appears and promote the
    captured build only when that generation/option is successfully applied.
- `SolomonDarkModLoader/src/bot_runtime/public_api.inl` and new
  `SolomonDarkModLoader/src/bot_runtime/public_api/loadout_details_api.inl`
  - Implement participant lookup, revision-keyed caching, authority-safe live
    reads, and the single address-free `ReadLoadoutDetails` producer.
- `SolomonDarkModLoader/src/lua_engine_bindings_bots.cpp`
  - Register/marshal `sd.bots.get_loadout_details`; route the old primary-window
    call through the same weld-aware producer.
- `docs/lua-bots.md`
  - Document the exact table, resolution flags, caching/revision behavior, and
    global-readiness fallback.
- `tests/re/run_live_native_spell_stats_probe.py`
  - Extend the live probe to cover base primary, one weld, every occupied
    secondary cost, Phasing/Teleport current/cap transitions, no exposed
    addresses, and no mutation of the active primary.
- `tests/re/static_lua_bot_brain_contracts.py` and
  `tests/re/static_lua_ml_bot_contracts.py`
  - Pin registration, schema, resolution flags, and the absence of raw-address
    fields.

Phase 2 exit gate: the one public query is stable and verified live; unresolved
secondary range/cooldown data remains explicitly unresolved instead of being
guessed.

### Phase 3 — Lua observation, masks, and brain

- `mods/bot-brain/scripts/policy_spec.lua`
  - Replace v1 with the exact 395-name list; set all versions to 2; define
    hidden sizes 192/96, 9 target actions, fixed scales, ray/patch constants,
    and v2 trajectory fields.
- New `mods/bot-brain/scripts/policy_geometry.lua`
  - Own scene/run-epoch nav-cache acquisition, grid indexing, nearest-sample
    lookups, 48 patch values, and eight clearance rays. Keep
    `sd.nav.test_segment` exclusively in the movement mask.
- New `mods/bot-brain/scripts/policy_spell_descriptors.lua`
  - Join `get_loadout_details` with replicated loadout/progression state and
    custom-spell config. Compute element/band, affordability, range relation,
    fallback readiness, skill-52 ownership, and weld flags in Lua.
- `mods/bot-brain/scripts/policy_observation.lua`
  - Build Blocks A-G, I, and H in the exact order; keep per-participant
    history; track enemy velocities by `network_actor_id`; sort/pad eight
    enemies, four loot rows, and four nearest ally rows; count the full
    configured participant set without a Lua cap; split orb subtypes; expose a
    movement mask, target mask, and a function that builds the cast mask for a
    selected target.
- `mods/bot-brain/scripts/steering.lua`
  - Keep replicated enemy acquisition and advisory aggregate/escape features,
    but stop making the learned policy's authoritative target choice.
- `mods/bot-brain/scripts/brain.lua`
  - Persist target by actor ID; sample movement and target, then build/sample
    target-conditioned cast; aim and cast only at that choice. Add the
    rate-limited pickup assist and deterministic weld preference manager.
- `mods/bot-brain/scripts/main.lua`
  - Load the new cohesive modules and reset nav, target, velocity, and history
    state on run/scene lifecycle changes.
- `mods/bot-brain/manifest.json`
  - Add the `policy.weld_preference` enum (`prefer`, `avoid`, `auto`) and any
    already-existing capability declaration needed by the verified loot API;
    do not add debug capability. The loader manifest grammar does not permit
    dots in setting keys, so the concrete key is
    `policy_weld_preference`.
- `mods/bot-brain/scripts/policy_training.lua`
  - Record target mask/action and the target-conditioned cast mask/action in
    trajectory v2; update target history. Leave the audited reward formula
    unchanged.

Phase 3 exit gate: deterministic Lua fixtures prove 395 finite values, exact
ordering, mask legality, actor-ID target persistence, weld/pickup/ally
transitions, and zero per-observation nav-grid rebuilds.

### Phase 4 — policy runtime and trainer

- `mods/bot-brain/scripts/policy.lua`
  - Implement strict architecture `mlp-tanh-three-head-v2`: two tanh layers
    192/96, movement and target masked softmaxes, target-conditioned cast
    masked softmax, one value head, and composite log probability. Reject all
    v1 shapes/versions with no shim.
- `mods/bot-brain/scripts/policy_weights.lua`
  - Replace the artifact with v2 tensor names/shapes and metadata.
- New `models/bot-brain/policy-v2.json`
  - Store the trainer artifact. Retain `policy-v1.json` only as historical
    source control unless the owner requests its removal; runtime loading must
    reject it.
- `tools/ml_bot/spec.py`
  - Mirror the exact 395-name/action/version/architecture contract and expose
    both hidden sizes and all four output groups.
- `tools/ml_bot/model.py`
  - Implement the two-layer, three-head model, composite selected-action
    log-probability, per-head entropy/gradients, PPO update, serialization, and
    shape validation.
- `tools/ml_bot/bridge.py`
  - Parse and strictly validate trajectory v2's three masks/actions.
- `tools/ml_bot/expert.py`
  - Rewrite the synthetic curriculum to choose an enemy slot first and derive
    casts from that selected target. Do not feed the v1 wrapper-selected target
    as ground truth. If bootstrap is removed by owner decision, delete this
    path cleanly instead.
- `tools/train_bot_policy.py`
  - Train all three heads, expose per-head entropy coefficients/metrics, load
    and export only v2, and keep checkpoint/hot-reload atomic.
- `docs/ml-bot.md` and `docs/design/ml-bot-policy-contract.md`
  - Replace v1 model/trajectory documentation with v2 and record the fixed
    normalization constants and known native-data limitations.

Phase 4 exit gate: Python and Lua agree on names and tensor shapes; finite
bootstrap/PPO tests pass; v1 load fails clearly; JSON and Lua exports
round-trip identically.

### Phase 5 — verifiers, headless smoke, and seed rotation

- `tools/verify_lua_bot_brain.py`
  - Add v2 observation/version/finite checks, target persistence, masks,
    weld flip, loot block, and exactly-once pickup credit checks.
- `tools/verify_ml_bot_live.py`
  - Require live secondary casting at range, policy-selected targets, movement
    toward a pickup, seed/log evidence, v2 hot reload, and no v1 acceptance.
- `tests/lua/ml_bot_policy_contract.lua`
  - Replace v1 fixtures with exact 395-value and three-head fixtures.
- `tests/test_ml_bot_policy.py`
  - Cover v2 serialization, two hidden layers, masks, composite log-prob,
    per-head entropy, PPO finiteness, and version rejection.
- `tests/re/static_lua_ml_bot_contracts.py` and
  `tests/re/static_lua_bot_brain_contracts.py`
  - Pin the final Lua/native boundary, no wrapper target, no per-tick grid
    query, no fallback/shim, and exact artifact versions.
- `tools/ml_bot/bridge.py`
  - Add `set_run_seed`, seed round-trip verification, optional boneyard-layout
    selection, and a disposable-session-per-environment-episode lifecycle.
- `scripts/Launch-LocalSoloSession.ps1`
  - Add the same validated `TestSurvivalBoneyardOverride` parameter and
    environment wiring used by multiplayer launchers; include path/hash in its
    result metadata.
- `tools/train_bot_policy.py`
  - Separate PPO update batches from environment episodes; allocate a fresh
    run seed for every environment episode, cycle the approved layout list,
    create/close the session safely, and log requested seed, observed
    `run_nonce`, layout hash, and rollout episode IDs.
- `tests/test_headless_simulation_contract.py`
  - Pin solo-launch seed/layout argument plumbing and process ownership cleanup.
- `docs/ml-bot.md`
  - Document the seed/layout schedule, disposable-session cost, log evidence,
    and the exact smoke command.

Phase 5 exit gate: static suites pass; a short accelerated live PPO run spans
at least two fresh seeds (and two layouts when supplied), remains finite,
exports/hot-loads v2, and the live behavior checks in the approved contract
all pass.

## E. Adjudicated outcomes

The eight former owner questions are resolved by
`docs/ml-bot-policy-v2.md`'s 2026-07-29 Adjudications:

1. The final layout is 395 values: the audited 350, four derived combat
   multipliers, and Block I's 41 ally values. Inventory/equipment summaries
   and `primary_available` remain dropped.
2. Phase 3 freezes clean round scales from catalog/RE evidence. The chosen
   constants are `MANA_SCALE=2000`, `HP_SCALE=1000`, `VEL_SCALE=1000`, and
   `COOLDOWN_SCALE=60`; evidence is recorded beside them in
   `policy_spec.lua`.
3. Native secondary coverage remains intentionally partial: unknown range
   skips the range mask, and unknown cooldown uses global readiness.
4. Weld `+0x844` uses generation-scoped capture with
   `build_id_resolved=false` allowed during an unresolved pending offer.
5. Navigation uses a per-scene cache refreshed about every two seconds and
   adopts only `refresh_pending=false` snapshots. No static-grid seam is
   added.
6. Phase 5 uses one disposable solo session per environment episode.
7. Fresh native seeds on the stock layout gate Phase 5; an approved
   multi-layout corpus remains non-blocking.
8. Bootstrap remains, but Phase 4 rewrites it target-first and reuses no v1
   weights, trajectories, or expert data.
