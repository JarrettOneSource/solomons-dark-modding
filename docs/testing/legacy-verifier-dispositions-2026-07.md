# Legacy verifier dispositions — 2026-07 process-safety re-audit

- Re-audit date: 2026-07-26
- Migration base: `6081dcab45b987f88f94c12d3861c87e73ab73ab`
- Scope: the 58 entry points approved for exact owned-process migration in
  `suite-audit-2026-07.md`
- Removal authority: none; this change retains every verifier

The comparison threshold for “entirely duplicated” was strict: another current
entry point must exercise the same transport lane, setup, observed state,
positive assertions, and rejection paths. Similar Steam-friend, Hagatha,
run-entry, static-layout, and focused behavior harnesses were treated as
overlap, not duplication, when they changed the transport or acceptance
boundary.

No entry point met that entire-duplication threshold. All 58 therefore remain
working and retained. The owner can still approve a later removal after a
separate behavior-equivalence review; this table does not authorize one.

| Entry point | Distinct boundary retained | Closest current overlap | Entirely duplicated? | Disposition |
| --- | --- | --- | --- | --- |
| `tools/verify_enemy_damage_claim_sync.py` | Client damage claims, rejection rollback, accepted hit position, and lethal presentation | Steam/local combat gates exercise damage, not this claim/rollback sequence | No | Retain |
| `tools/verify_flat_multiplayer_boneyard.py` | Local-UDP flat-arena fixture, nav, render, spawn, and convergence | `verify_steam_friend_flat_boneyard.py` uses the Steam lane | No — transport boundary differs | Retain |
| `tools/verify_hub_student_seed_viability.py` | Independent-client stock Student determinism diagnostic | `verify_hub_student_population_sync.py` checks authoritative population convergence | No — determinism question differs | Retain |
| `tools/verify_local_multiplayer_sync.py` | Local-UDP participant visibility plus bidirectional movement convergence | Run-entry stability and HUD-name gates cover only subsets | No | Retain |
| `tools/verify_multiplayer_all_stat_sync.py` | Exhaustive per-participant native stat state and behavior | Hagatha derived/combat matrices are focused Steam-lane matrices | No | Retain |
| `tools/verify_multiplayer_all_upgrade_sync.py` | Every native upgrade through authoritative local multiplayer offers | Hagatha perk and active-pair progression gates split narrower Steam scopes | No | Retain |
| `tools/verify_multiplayer_animation_mana_elements.py` | Animation, low-mana rejection, and element casts in one local pair | Active-pair visuals/combat gates cover pieces on Steam | No | Retain |
| `tools/verify_multiplayer_battle_siege_behavior_sync.py` | Both-owner Battle Mage mana and Siege Mage damage behavior | Hagatha combat-modifier matrix uses a different lane and fixture | No | Retain |
| `tools/verify_multiplayer_concentration_behavior_context.py` | Per-player Concentrate context survival through remote replay | Active-pair stat behavior is broader but does not reproduce this context boundary | No | Retain |
| `tools/verify_multiplayer_defense_behavior_sync.py` | Exact Resist Magic, Resist Poison, and natural Deflect behavior | Steam stat/Hagatha defense gates use different sessions | No | Retain |
| `tools/verify_multiplayer_enemy_soft_reconciliation.py` | Local-UDP moderate-drift reconciliation without a visual snap | `verify_steam_friend_enemy_soft_reconciliation.py` uses Steam | No — transport boundary differs | Retain |
| `tools/verify_multiplayer_faster_caster_behavior_sync.py` | Both-owner primary-cast cadence change | Active-pair stat behavior uses Steam fixtures | No | Retain |
| `tools/verify_multiplayer_fireball_embers_effect_sync.py` | Native Embers fragment behavior for either local owner | Active-pair spell behavior covers Steam spell effects | No | Retain |
| `tools/verify_multiplayer_fireball_explode_effect_sync.py` | Native Fireball Explode owner/observer behavior | Active-pair spell behavior covers a different transport fixture | No | Retain |
| `tools/verify_multiplayer_firewalker_effect_sync.py` | Native Firewalker trail replication for either local owner | Active-pair persistent/spell behavior uses Steam | No | Retain |
| `tools/verify_multiplayer_focus_behavior_sync.py` | Both-owner secondary recharge cadence | Active-pair stat behavior uses Steam | No | Retain |
| `tools/verify_multiplayer_gold_pickup_authority.py` | Local request/result, one-credit, rejection, and despawn flow | Steam loot gates do not duplicate the local authority exchange | No | Retain |
| `tools/verify_multiplayer_host_owned_level_up_sync.py` | Host-owned choice across every native participant view | Active-pair progression uses a different lane and ownership matrix | No | Retain |
| `tools/verify_multiplayer_hub_inventory_shop_sync.py` | Local Luthacus storage participant boundaries | `verify_steam_friend_hub_inventory_storage.py` uses Steam | No — transport boundary differs | Retain |
| `tools/verify_multiplayer_hub_shop_ownership.py` | Local stock purchase ownership and replication | `verify_steam_friend_hub_shop_ownership.py` uses Steam | No — transport boundary differs | Retain |
| `tools/verify_multiplayer_inventory_audit.py` | Typed local inventory and equipped-item audit | Steam native-inventory gates do not reproduce the same typed audit | No | Retain |
| `tools/verify_multiplayer_late_join_owned_state.py` | Late join plus same-identity reconnect across inventory, equipment, vitals, status, position, and progression | Steam reconnect gates cover narrower run/session state | No | Retain |
| `tools/verify_multiplayer_late_join_upgrade_catchup.py` | Third-client upgraded native state and behavior catch-up | Active-run reconnect and progression gates use different participant topology | No | Retain |
| `tools/verify_multiplayer_level_up_barrier_sync.py` | All-player pause, waiting, resume, and timeout auto-pick | `verify_steam_friend_active_pair_level_up_barrier.py` uses Steam | No — transport boundary differs | Retain |
| `tools/verify_multiplayer_level_up_offer_sync.py` | Host-authored local offer and choice replication | Active-pair progression uses Steam and a broader workflow | No | Retain |
| `tools/verify_multiplayer_lightning_chaining_effect_sync.py` | Native Chaining owner/observer effect behavior | Active-pair spell behavior uses Steam fixtures | No | Retain |
| `tools/verify_multiplayer_loot_drop_materialization.py` | Client presentation actor materialization for host-authored loot | Steam loot soak focuses deactivation/authority rather than this local presentation boundary | No | Retain |
| `tools/verify_multiplayer_meditation_behavior_sync.py` | Native idle recovery and live replication for both owners | Active-pair stat behavior uses Steam | No | Retain |
| `tools/verify_multiplayer_mindstar_behavior_sync.py` | Mindstar rank increase and mana-hoard behavior for either owner | Active-pair stat/progression gates use Steam | No | Retain |
| `tools/verify_multiplayer_native_item_inventory_sync.py` | Exact recipe-backed remote item pickup into stock inventory | `verify_steam_friend_native_inventory_sync.py` uses Steam and a different item flow | No | Retain |
| `tools/verify_multiplayer_native_potion_inventory_sync.py` | Accepted remote potion pickup into client stock inventory | Steam native-inventory gate does not duplicate this local potion boundary | No | Retain |
| `tools/verify_multiplayer_orb_pickup_authority.py` | Local HP/MP orb request/result, one-credit, and duplicate rejection | Item/potion and Steam loot gates cover different resource types or lanes | No | Retain |
| `tools/verify_multiplayer_persistent_status_sync.py` | Native persistent-skill toggles for either local owner | `verify_steam_friend_active_pair_persistent_behavior.py` uses Steam | No — transport boundary differs | Retain |
| `tools/verify_multiplayer_player_visibility.py` | Native remote-body presentation capture in a shared local run | HUD-name and active-pair visual gates cover different presentation slices | No | Retain |
| `tools/verify_multiplayer_powerup_sync.py` | Stock powerup carriers and rewards for both local owners | `verify_steam_friend_powerup_sync.py` uses Steam | No — transport boundary differs | Retain |
| `tools/verify_multiplayer_primary_kill_stress.py` | Frozen-target real primary-cast kill stress on local UDP | `verify_steam_friend_primary_kill_stress.py` uses Steam | No — transport boundary differs | Retain |
| `tools/verify_multiplayer_progression_catalog.py` | Every native progression row on both local peers | Hagatha matrices test selected derived/perk behavior | No | Retain |
| `tools/verify_multiplayer_progression_ledger_sync.py` | Local-UDP participant progression-ledger replication | Active-pair state/progression uses Steam | No | Retain |
| `tools/verify_multiplayer_regenerate_behavior_sync.py` | Timed healing plus mana hoard for either owner | Active-pair stat behavior uses Steam | No | Retain |
| `tools/verify_multiplayer_ring_of_fire_multikill_stability.py` | Local client-owned Ring of Fire multi-kill crash reproduction | Secondary-behavior harness does not include this crash topology | No | Retain |
| `tools/verify_multiplayer_rush_behavior_sync.py` | Bidirectional native Rush movement and replicated position | `verify_steam_friend_active_pair_rush.py` uses Steam | No — transport boundary differs | Retain |
| `tools/verify_multiplayer_skill_picker_visual_identity.py` | Skill-picker visual identity from authoritative offer IDs | Progression gates validate choices/state, not this exact visual identity | No | Retain |
| `tools/verify_multiplayer_staff_stat_behavior_sync.py` | Enchant Staff and Fortunate Flailing behavior both ways | Active-pair stat behavior uses Steam | No | Retain |
| `tools/verify_multiplayer_targeted_spell_matrix.py` | Targeted enemy casts across every local player element | Element and active-pair spell matrices use different targets or lanes | No | Retain |
| `tools/verify_multiplayer_telekinesis_behavior_sync.py` | Stock Telekinesis pickup behavior and ownership both ways | Secondary-behavior gates use different fixtures and transport | No | Retain |
| `tools/verify_multiplayer_third_observer_upgrade_sync.py` | Three-player progression and Air Chaining parity | Active-pair progression is two-player Steam | No | Retain |
| `tools/verify_multiplayer_transient_status_sync.py` | Exact native transient Poisoned status both ways | Active-pair status behavior uses Steam | No | Retain |
| `tools/verify_multiplayer_webbed_status_sync.py` | Genuine Spider Webbed behavior for both local owners | `verify_steam_friend_active_pair_webbed.py` uses Steam | No — transport boundary differs | Retain |
| `tools/verify_native_enemy_death_and_loot_sync.py` | Native enemy death presentation plus host-authored loot | Organic-death and Steam loot gates split this combined local boundary | No | Retain |
| `tools/verify_player_damage_visual_sync.py` | Complete Magic Shield replication in both directions | Secondary-behavior gates do not duplicate this exact visual/state sequence | No | Retain |
| `tools/verify_player_health_death_sync.py` | HP, death presentation, inert corpse, and revive sync | Death/spectator gates cover different terminal and continuation behavior | No | Retain |
| `tools/verify_real_input_spell_cast_sync.py` | Real local mouse input and spell presentation | `verify_steam_friend_real_input_control.py` uses Steam | No — transport boundary differs | Retain |
| `tools/verify_run_enemy_materialization_catchup.py` | Live post-entry enemy-spawn catch-up without sustained gaps | Run-entry stability covers entry, not this continuing materialization boundary | No | Retain |
| `tools/verify_run_enemy_seed_viability.py` | Independent-client stock run-enemy determinism diagnostic | Static-layout/run-entry gates validate authoritative convergence instead | No — determinism question differs | Retain |
| `tools/verify_run_enemy_target_authority.py` | Host target-state propagation to local clients | Steam enemy-motion authority uses a different lane and motion scope | No | Retain |
| `tools/verify_run_world_snapshot.py` | Local run-enemy snapshot bootstrap and reconciliation | Steam stale-hold and run-entry gates cover different snapshot phases | No | Retain |
| `tools/verify_spell_cast_sync.py` | Local remote-cast presentation and cast-log convergence | Active-pair visuals/spell behavior uses Steam | No | Retain |
| `tools/verify_world_snapshot_reconciliation.py` | Client application of host world snapshots to local actors | Run snapshot and Steam stale-hold gates do not isolate this application seam | No | Retain |
