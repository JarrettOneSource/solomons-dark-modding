"""Native Hagatha charm and curse synchronization contracts."""

from __future__ import annotations

import json

from static_re_contract_support import (
    ROOT,
    StaticReTestFailure,
    read_mod_loader_header_source,
    read_source_unit,
    read_text,
)


EXPECTED_NAMES = (
    "LIFE CHARM",
    "MANA CHARM",
    "SPEED CHARM",
    "ITEM CHARM",
    "GOLD CHARM",
    "SEEKER'S CHARM",
    "REVELATION CHARM",
    "CHEAT DEATH CHARM",
    "PERKY CHARM",
    "SCATTER CURSE",
    "WAR CHARM",
    "CURING CHARM",
    "THE LAST WORD CHARM",
    "SPELLWELDER'S CHARM",
    "WEIRD CASTER CHARM",
    "DRINKER'S CHARM",
    "GLASS CANNON CURSE",
    "SORCEROR'S CHARM",
    "FOCUS CHARM",
    "DISFIGURING CURSE",
    "BARE HANDS CHARM",
    "SPLIT MIND CHARM",
    "CURSE BOSSES",
    "ARCANE ATTRACTOR CHARM",
    "SERENDIPITY CHARM",
    "REVERIE CHARM",
    "BRUTE'S CHARM",
    "TONIC",
)

EXPECTED_PRICES = (
    200,
    200,
    250,
    1000,
    500,
    200,
    800,
    5000,
    1500,
    150,
    800,
    250,
    500,
    2000,
    2500,
    1000,
    1000,
    3000,
    1000,
    3000,
    500,
    4000,
    2000,
    2000,
    1000,
    1000,
    3000,
    1000,
)

EXPECTED_TOOLTIP_LINES = (
    ("Maximum life is always increased by 25%.",),
    ("Maximum mana is always increased by 25%.",),
    ("Walking and casting speed is increased by 10%.",),
    ("Odds of finding useful items to equip is increased.",),
    ("Odds of finding gold is increased.", "Quantity of gold found is increased."),
    ("Lines of force indicate the locations of gold, items, and magic upgrades.",),
    ("New skills automatically become level 2 when you learn them.",),
    ("Survive one killing blow by recovering half of your health.",),
    ("Offers more skill choices when you level up, and decreases level requirements of all skills and items by two.",),
    ("Killed monsters scatter more and larger orbs",),
    ("All offensive spells cost 25% less to cast.",),
    ("Poison damage reduced by 50%.",),
    ("Explode on death, dealing massive damage to everything near and far.  Luthacus will scavenge any treasures dropped during the final conflagration.",),
    ("Welded spells recombine any time the compenent spells are improved.",),
    ("Grants a new secondary attack and biases skill choices toward secondary skills.",),
    ("Drink potions automatically when needed.",),
    ("Do double damage.  Take double damage.",),
    ("Allows the wizard to re-roll skills once at level-up, or save the skill point to spend on the next level.",),
    ("All spell cooldowns reduced by 25%.",),
    ("Tweaks your aura so that you can effectively use three rings.",),
    ("Improve damage and lower mana cost by 15% when casting bare-handed.",),
    ("Concentrate on two skills at once.",),
    ("Bosses take triple damage.",),
    ("Odds of finding magical upgrades is greatly increased.",),
    ("Until you are hurt, all spells do three times as much damage.",),
    ("Until you are hurt, all spells cost no mana.",),
    ("Increases wizard's physical strength.", "Melee damage increased 200%, pushing power increased 100%."),
    ("Loosens your mind enough to hold more charms or curses.  Limit two per customer.",),
)


def _require(label: str, text: str, tokens: tuple[str, ...], failures: list[str]) -> None:
    for token in tokens:
        if token not in text:
            failures.append(f"{label} is missing {token}")


def test_native_hagatha_perk_catalog_is_complete() -> str:
    """The recovered stock table must name and price every selectable outcome."""

    path = ROOT / "docs/reverse-engineering/native-hagatha-perk-catalog.json"
    if not path.is_file():
        raise StaticReTestFailure("native Hagatha perk catalog is missing")

    catalog = json.loads(read_text(path))
    failures: list[str] = []
    if catalog.get("schema_version") != 3:
        failures.append("catalog schema_version is not 3")
    if catalog.get("native_functions") != {
        "name": "0x00571DD0",
        "price_table": "0x005A7CA0",
        "description": "0x00573E90",
        "apply": "0x0066EF70",
        "refresh": "0x0067C360",
        "cache_refresh": "0x006623F0",
        "damage_player": "0x0052F540",
        "increase_skill": "0x00660320",
        "set_skill": "0x00660580",
        "build_skill_offer": "0x0067CB70",
        "render_seeker": "0x0052A640",
        "auto_health_potion": "0x005296A0",
        "auto_mana_potion": "0x00529710",
        "mutate_health": "0x0052AC80",
        "mutate_mana": "0x0052B150",
        "tick_player_death": "0x00533520",
        "common_mindblast": "0x00645B50",
        "archive_completed_run": "0x005C9670",
        "collect_completed_run": "0x005BE320",
    }:
        failures.append("catalog native function evidence is incomplete")
    if catalog.get("native_offsets") != {
        "selector_list": "0x7C0",
        "selector_count": "0x7C4",
        "flag_base": "0x7CC",
        "capacity": "0x800",
        "melee_damage_multiplier": "0x6F4",
        "push_strength": "0x818",
        "cheat_death_enabled": "0x81C",
        "cheat_death_charges": "0x820",
        "serendipity_active": "0x73C",
        "reverie_active": "0x73D",
    }:
        failures.append("catalog native field evidence is incomplete")
    tooltip = catalog.get("tooltip_contract")
    if not isinstance(tooltip, dict) or (
        tooltip.get("content_builder") != "0x00573E90"
        or tooltip.get("hover_box_constructor") != "0x005C38F0"
        or tooltip.get("hover_box_renderer") != "0x005C3A60"
        or tooltip.get("owned_grid_pointer_owner") != "0x0056FC90"
        or tooltip.get("owned_grid_current_index_offset") != "InventoryScreen+0x5CC"
        or tooltip.get("owned_grid_shape") != [3, 3]
        or tooltip.get("owned_grid_cell_size") != 60
        or tooltip.get("initial_delay_native_ticks") != 0
        or tooltip.get("audio") is not None
        or tooltip.get("cheat_death_dynamic_lines") != {
            "enabled_with_charges": "   Cheats remaining: %d",
            "enabled_without_charges": "   Used up!",
            "disabled": None,
        }
        or tooltip.get("perk_shop_suffix") != {
            "builder": "0x00554690",
            "bundle": "    Bulk discount: 50%",
            "first_mix": "    High price due to first mixing.",
        }
    ):
        failures.append("catalog native HoverBox contract is incomplete")
    if catalog.get("bundle") != {
        "selector": -1,
        "name": "BARGAIN BUNDLE",
        "native_tooltip_intro": "Get everything the last wizard got.",
        "member_line_format": "        %s",
        "member_source": "DAT_0081A390/DAT_0081A394",
    }:
        failures.append("catalog native bargain-bundle tooltip is incomplete")

    perks = catalog.get("perks")
    if not isinstance(perks, list) or len(perks) != len(EXPECTED_NAMES):
        failures.append("catalog does not contain exactly 28 perk rows")
    else:
        for selector, row in enumerate(perks):
            if row.get("selector") != selector:
                failures.append(f"perk row {selector} has the wrong selector")
            if row.get("name") != EXPECTED_NAMES[selector]:
                failures.append(f"perk row {selector} has the wrong stock name")
            if row.get("price") != EXPECTED_PRICES[selector]:
                failures.append(f"perk row {selector} has the wrong stock price")
            if not isinstance(row.get("description"), str) or not row["description"].strip():
                failures.append(f"perk row {selector} has no recovered behavior description")
            if tuple(row.get("native_tooltip_lines", ())) != EXPECTED_TOOLTIP_LINES[selector]:
                failures.append(f"perk row {selector} has the wrong native tooltip copy")
            if not isinstance(row.get("behavior_family"), str) or not row["behavior_family"]:
                failures.append(f"perk row {selector} has no behavior family")
            if not isinstance(row.get("network_scope"), str) or not row["network_scope"]:
                failures.append(f"perk row {selector} has no network ownership scope")

    if failures:
        raise StaticReTestFailure("; ".join(failures))
    return "all 28 stock Hagatha outcomes and the bundle have exact names, prices, tooltip copy, behavior, and native evidence"


def test_hagatha_effect_contract_is_complete() -> str:
    """Every tooltip claim must have an exact downstream native contract."""

    catalog = json.loads(read_text(
        ROOT / "docs/reverse-engineering/native-hagatha-perk-catalog.json"
    ))
    report_path = ROOT / "docs/reverse-engineering/native-hagatha-perk-effects.md"
    report = read_text(report_path) if report_path.is_file() else ""
    failures: list[str] = []

    expected_constants = {
        "life_factor": 1.25,
        "mana_factor": 1.25,
        "speed_factor": 1.100000023841858,
        "item_candidate_bound_factor": 0.75,
        "gold_candidate_bound_factor": 0.75,
        "gold_amount_factor": 1.25,
        "seeker_minimum_distance_exclusive": 100,
        "seeker_distance_cap": 300,
        "seeker_inner_start": 35,
        "seeker_join": 50,
        "seeker_outer_factor": 0.5,
        "seeker_width": 3,
        "seeker_rgb": [0.85, 0.73, 0.44],
        "seeker_alpha_base": 0.75,
        "seeker_alpha_amplitude": 0.5,
        "seeker_tick_degrees": 2,
        "seeker_actor_phase_degrees": 35,
        "revelation_minimum_rank": 2,
        "cheat_death_recovery_factor": 0.5,
        "scatter_candidate_bound_factor": 0.5,
        "war_mana_factor": 0.75,
        "curing_poison_factor": 0.5,
        "last_word_death_tick": 200,
        "last_word_archive_tick": 300,
        "last_word_presentation_scale": 15,
        "last_word_query_scale": 55,
        "last_word_radius": 825,
        "last_word_raw_damage": 10000,
        "last_word_damage_factor": 0.5,
        "last_word_damage": 5000,
        "drinker_health_threshold_inclusive": -10,
        "glass_cannon_factor": 2.0,
        "focus_recharge_factor": 1.25,
        "bare_hands_damage_factor": 1.149999976158142,
        "bare_hands_mana_factor": 0.8500000238418579,
        "curse_bosses_factor": 3.0,
        "curse_boss_native_type_ids": [1008, 1009, 1010, 1011],
        "arcane_attractor_candidate_bound_factor": 0.800000011920929,
        "serendipity_damage_factor": 3.0,
        "brute_melee_factor": 3.0,
        "brute_push_factor": 2.0,
        "tonic_capacity_delta": 3,
        "tonic_purchase_limit": 2,
        "maximum_capacity": 9,
    }
    if catalog.get("effect_constants") != expected_constants:
        failures.append("catalog effect constants are incomplete or changed")

    _require(
        "native Hagatha effect report",
        report,
        (
            "# Native Hagatha perk gameplay effects",
            "0x0052A640",
            "0x00660320/0x00660580",
            "0x0052F540",
            "0x006623F0",
            "0x0067CB70",
            "0x0052AC80",
            "0x0052B150",
            "0x00533520",
            "0x00645B50",
            "0x005C9670 -> 0x005BE320",
            "distance strictly greater than 100",
            "radius 825 and damage 5000",
            "HP `<= -10`",
            "1008 DemonSkull, 1009 Demon, 1010 DireFaculty, and 1011 Heartmonger",
            "No member is blocked by the browser platform.",
        ),
        failures,
    )
    if failures:
        raise StaticReTestFailure("; ".join(failures))
    return "all 28 Hagatha rows have exact downstream constants, owners, lifecycle, and platform dispositions"


def test_hagatha_perks_replicate_as_participant_owned_native_state() -> str:
    """Each participant's ordered perk list must hydrate the matching native actor."""

    protocol = read_text(
        ROOT / "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h"
    )
    runtime_state = read_text(
        ROOT / "SolomonDarkModLoader/include/multiplayer_runtime_state.h"
    )
    seams = read_text(ROOT / "SolomonDarkModLoader/src/gameplay_seams.h")
    progression_offsets = read_text(
        ROOT
        / "SolomonDarkModLoader/src/gameplay_seams/progression_and_actor_offsets.inl"
    )
    address_storage = read_text(
        ROOT / "SolomonDarkModLoader/src/gameplay_seams/address_storage.inl"
    )
    address_bindings = read_text(
        ROOT / "SolomonDarkModLoader/src/gameplay_seams/state_and_address_bindings.inl"
    )
    size_bindings = read_text(
        ROOT / "SolomonDarkModLoader/src/gameplay_seams/size_bindings.inl"
    )
    binary_layout = read_text(ROOT / "config/binary-layout.ini")
    transport = read_text(
        ROOT / "SolomonDarkModLoader/src/multiplayer_local_transport.cpp"
    )
    local_sync = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/local_state_packet_sync.inl"
    )
    incoming_sync = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/incoming_participant_state_sync.inl"
    )
    native_sync = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/native_progression_sync.inl"
    )
    perk_state_path = (
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/hagatha_perk_state.inl"
    )
    perk_state = read_text(perk_state_path) if perk_state_path.is_file() else ""
    lua_runtime = read_text(
        ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_runtime.cpp"
    )
    verifier_path = ROOT / "tools/verify_steam_hagatha_perk_sync.py"

    failures: list[str] = []
    _require(
        "wire protocol",
        protocol,
        (
            "constexpr std::uint16_t kProtocolVersion = 92;",
            "kParticipantHagathaPerkMaxCount = 9",
            "struct ParticipantHagathaPerkPacketState",
            "std::uint32_t hagatha_perk_revision;",
            "ParticipantHagathaPerkPacketState hagatha_perks;",
            "static_assert(sizeof(ParticipantHagathaPerkPacketState) == 20",
            "static_assert(sizeof(StatePacket) == 709",
        ),
        failures,
    )
    _require(
        "runtime participant state",
        runtime_state,
        (
            "struct ParticipantHagathaPerkState",
            "std::uint32_t hagatha_perk_revision = 0;",
            "ParticipantHagathaPerkState hagatha_perks;",
            "cheat_death_charges",
            "serendipity_active",
            "reverie_active",
        ),
        failures,
    )
    _require(
        "native seam declarations",
        seams + progression_offsets,
        (
            "kActorProgressionApplyHagathaPerk",
            "kProgressionHagathaPerkListOffset",
            "kProgressionHagathaPerkCountOffset",
            "kProgressionHagathaPerkFlagBaseOffset",
            "kProgressionHagathaPerkCapacityOffset",
            "kProgressionCheatDeathEnabledOffset",
            "kProgressionCheatDeathChargesOffset",
            "kProgressionSerendipityActiveOffset",
            "kProgressionReverieActiveOffset",
        ),
        failures,
    )
    _require(
        "native seam storage and bindings",
        address_storage + address_bindings + size_bindings,
        (
            "kActorProgressionApplyHagathaPerk",
            '"actor_progression_apply_hagatha_perk"',
            '"progression_hagatha_perk_list"',
            '"progression_hagatha_perk_count"',
            '"progression_hagatha_perk_flag_base"',
            '"progression_hagatha_perk_capacity"',
            '"progression_cheat_death_enabled"',
            '"progression_cheat_death_charges"',
            '"progression_serendipity_active"',
            '"progression_reverie_active"',
        ),
        failures,
    )
    _require(
        "binary layout",
        binary_layout,
        (
            "actor_progression_apply_hagatha_perk=0x0066EF70",
            "progression_hagatha_perk_list=0x7C0",
            "progression_hagatha_perk_count=0x7C4",
            "progression_hagatha_perk_flag_base=0x7CC",
            "progression_hagatha_perk_capacity=0x800",
            "progression_cheat_death_enabled=0x81C",
            "progression_cheat_death_charges=0x820",
            "progression_serendipity_active=0x73C",
            "progression_reverie_active=0x73D",
        ),
        failures,
    )
    _require(
        "participant perk capture and validation",
        perk_state,
        (
            "RefreshOwnedHagathaPerks",
            "BuildHagathaPerkPacketState",
            "IsSaneHagathaPerkPacketState",
            "ApplyHagathaPerkPacketState",
            "kParticipantHagathaPerkMaxCount",
        ),
        failures,
    )
    _require(
        "transport composition",
        transport,
        ('#include "multiplayer_local_transport/hagatha_perk_state.inl"',),
        failures,
    )
    _require(
        "outgoing participant state",
        local_sync,
        (
            "RefreshOwnedHagathaPerks",
            "BuildHagathaPerkPacketState",
            "&packet->hagatha_perk_revision",
            "&packet->hagatha_perks",
        ),
        failures,
    )
    _require(
        "incoming participant state",
        incoming_sync,
        (
            "ApplyHagathaPerkPacketState",
            "packet.hagatha_perk_revision",
            "packet.hagatha_perks",
        ),
        failures,
    )
    _require(
        "remote native progression hydration",
        native_sync + perk_state,
        (
            "ReconcileRemoteHagathaPerks",
            "CallNativeActorProgressionApplyHagathaPerk",
            "kActorProgressionApplyHagathaPerk",
        ),
        failures,
    )
    _require(
        "Lua participant inspection",
        lua_runtime,
        (
            '"hagatha_perks"',
            '"cheat_death_charges"',
            '"serendipity_active"',
            '"reverie_active"',
        ),
        failures,
    )

    if not verifier_path.is_file():
        failures.append("two-owner Steam Hagatha verifier is missing")
    else:
        verifier = read_text(verifier_path)
        _require(
            "two-owner Steam Hagatha verifier",
            verifier,
            (
                "EXPECTED_PERK_COUNT",
                "owner_participant_id",
                "observer_participant_id",
                "hagatha_perks",
                "native_selector_list",
                "cheat_death_charges",
                "serendipity_active",
                "reverie_active",
                "host_to_client",
                "client_to_host",
                "sd.bots.get_participant_state",
            ),
            failures,
        )
        if "participant.progression_runtime_state_address" in verifier:
            failures.append(
                "Hagatha verifier reads an unexported runtime participant native address"
            )

    if failures:
        raise StaticReTestFailure("; ".join(failures))
    return "ordered Hagatha state is owner-authored, native-hydrated, observable, and covered in both directions"


def test_hagatha_one_shot_runtime_state_is_host_authoritative() -> str:
    """Host-side damage must not be undone by stale owner snapshots."""

    protocol = read_text(
        ROOT / "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h"
    )
    authority = read_source_unit(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/participant_vitals_authority.inl"
    )
    perk_state_path = (
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/hagatha_perk_state.inl"
    )
    perk_state = read_text(perk_state_path) if perk_state_path.is_file() else ""

    failures: list[str] = []
    _require(
        "runtime correction wire state",
        protocol,
        (
            "ParticipantVitalsCorrectionFlagHagathaRuntimeState",
            "hagatha_cheat_death_charges",
            "hagatha_serendipity_active",
            "hagatha_reverie_active",
            "static_assert(sizeof(ParticipantVitalsCorrectionPacket) == 88",
        ),
        failures,
    )
    _require(
        "host runtime ownership",
        perk_state + authority,
        (
            "CaptureAuthoritativeHagathaRuntimeState",
            "ApplyAuthoritativeHagathaRuntimeCorrection",
            "ParticipantVitalsCorrectionFlagHagathaRuntimeState",
            "kProgressionCheatDeathChargesOffset",
            "kProgressionSerendipityActiveOffset",
            "kProgressionReverieActiveOffset",
        ),
        failures,
    )
    if failures:
        raise StaticReTestFailure("; ".join(failures))
    return "host-consumed Cheat Death and until-hurt flags reliably correct the owning client"


def test_hagatha_derived_stats_have_a_two_owner_steam_matrix() -> str:
    """Every stock derived-stat perk must be proven on both native actors."""

    verifier_path = ROOT / "tools/verify_steam_hagatha_derived_stat_matrix.py"
    fixture_path = ROOT / "tools/hagatha_bare_hands_fixture.py"
    failures: list[str] = []
    if not verifier_path.is_file():
        failures.append("two-owner Steam Hagatha derived-stat verifier is missing")
        verifier = ""
    else:
        verifier = read_text(verifier_path)
    if not fixture_path.is_file():
        failures.append("stock Bare Hands weapon fixture is missing")
        fixture = ""
    else:
        fixture = read_text(fixture_path)
    _require(
        "two-owner Steam Hagatha derived-stat verifier",
        verifier + fixture,
        (
            "LIFE_SELECTOR = 0",
            "MANA_SELECTOR = 1",
            "SPEED_SELECTOR = 2",
            "WAR_SELECTOR = 10",
            "FOCUS_SELECTOR = 18",
            "BARE_HANDS_SELECTOR = 20",
            "BRUTE_SELECTOR = 26",
            "TONIC_SELECTOR = 27",
            "query_progression_snapshot",
            "assert_relative_effect",
            "owner_native",
            "observer_native",
            "observer_ledger",
            "observer_owner_unchanged",
            "corrupt_observer_field",
            "self_corrected",
            "BARE_HANDS_REFRESH = 0x0065F9A0",
            "LOADOUT_TABLE = 0x0081C264",
            "loadout_table_address = sd.debug.resolve_game_address",
            "query_local_weapon_binding",
            "set_local_weapon_presence",
            "assert_bare_hands_armed_inactive",
            "verify_bare_hands_direction",
            '"armed_inactive"',
            '"unarmed_active"',
            '"restored_armed"',
            "sd.debug.write_ptr",
            "sd.debug.call_thiscall_ret_u32(refresh, progression)",
            "wait_for_native_release_after_hub_leave",
            "leave_endpoint_to_main_menu",
            "blocking_dialog_actions",
            "sd.ui.find_action('dialog.primary', 'dialog')",
            'last.get("surface") == "dialog"',
            'blocking_dialog_actions.append(\n                run_driver.local_sync.activate_native_ui_action(',
            "direction_error",
            "ONBOARDING_TIMEOUT = 90.0",
            '"host_to_client"',
            '"client_to_host"',
        ),
        failures,
    )
    if "SPELL_MANA = FieldExpectation" in verifier or (
        "BARE_HANDS_SPELL_MANA = FieldExpectation" in verifier
    ):
        failures.append(
            "Hagatha verifier treats raw spell-builder mana as final native cast spend"
        )
    if '"secondary_recharge",\n    1.25,' not in verifier:
        failures.append(
            "Hagatha Focus verifier does not use the stock recharge-rate multiplier"
        )

    protocol = read_text(
        ROOT / "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h"
    )
    runtime_state = read_text(
        ROOT / "SolomonDarkModLoader/include/multiplayer_runtime_state.h"
    )
    public_state = read_text(ROOT / "SolomonDarkModLoader/include/mod_loader.h")
    offsets = read_text(
        ROOT
        / "SolomonDarkModLoader/src/gameplay_seams/progression_and_actor_offsets.inl"
    )
    storage = read_text(
        ROOT / "SolomonDarkModLoader/src/gameplay_seams/address_storage.inl"
    )
    bindings = read_text(
        ROOT / "SolomonDarkModLoader/src/gameplay_seams/size_bindings.inl"
    )
    binary_layout = read_text(ROOT / "config/binary-layout.ini")
    capture = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"
    )
    state_sync = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/owned_progression_state.inl"
    )
    native_sync = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/native_progression_sync.inl"
    )
    _require(
        "Brute derived-state model",
        protocol + runtime_state + public_state,
        (
            "melee_damage_multiplier",
            "push_strength",
        ),
        failures,
    )
    _require(
        "Brute native offsets",
        offsets + storage + bindings + binary_layout,
        (
            "kProgressionMeleeDamageMultiplierOffset",
            "kProgressionPushStrengthOffset",
            '"progression_melee_damage_multiplier"',
            '"progression_push_strength"',
            "progression_melee_damage_multiplier=0x6F4",
            "progression_push_strength=0x818",
        ),
        failures,
    )
    _require(
        "Brute capture and correction",
        capture + state_sync + native_sync,
        (
            "melee_damage_multiplier",
            "push_strength",
            "kProgressionMeleeDamageMultiplierOffset",
            "kProgressionPushStrengthOffset",
        ),
        failures,
    )
    if failures:
        raise StaticReTestFailure("; ".join(failures))
    return "all stock Hagatha derived-stat outcomes have a two-owner Steam matrix"


def test_cheat_death_health_increase_is_captured_as_authoritative_damage() -> str:
    """Cheat Death can raise native HP, so its consumed charge must trigger capture."""

    native_vitals = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement/native_remote_vitals_and_playback.inl"
    )
    perk_state = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/hagatha_perk_state.inl"
    )
    transport_header = read_text(
        ROOT / "SolomonDarkModLoader/include/multiplayer_local_transport.h"
    )
    public_transport = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/public_cast_loot_api.inl"
    )
    verifier_path = ROOT / "tools/verify_steam_hagatha_runtime_correction.py"

    failures: list[str] = []
    _require(
        "native remote vitals capture",
        native_vitals + perk_state,
        (
            "HasAuthoritativeHagathaRuntimeStateChanged",
            "native_hagatha_runtime_observed",
            "native_damage_observed ||",
            "(native_damage_observed || native_hagatha_runtime_observed)\n"
            "                ? native_hp",
        ),
        failures,
    )
    _require(
        "linked Hagatha vitals boundary",
        transport_header + public_transport,
        (
            "bool HasAuthoritativeHagathaRuntimeStateChanged(",
            "return HasAuthoritativeHagathaRuntimeStateChangedInternal(",
        ),
        failures,
    )
    authority = read_source_unit(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/participant_vitals_authority.inl"
    )
    _require(
        "Cheat Death correction ordering",
        authority + perk_state,
        (
            "correction_consumed_cheat_death",
            "previous_consumed_cheat_death",
            "pending_cheat_death_consumed",
            "const bool cheat_death_consumed",
            "cheat_death_consumed\n            ? authoritative_life",
            "pending_cheat_death_consumed\n"
            "                    ? pending.packet.life_current",
            "hagatha_perk_revision += 1",
            "cheat_death_consumed",
            "native_life_valid",
            "queued.life_current = hagatha_runtime.life_current",
            "queued.life_max = hagatha_runtime.life_max",
        ),
        failures,
    )
    capture_body = perk_state.split(
        "bool CaptureAuthoritativeHagathaRuntimeState(", 1
    )[-1].split("bool HasAuthoritativeHagathaRuntimeStateChanged", 1)[0]
    if "UpdateRuntimeState" in capture_body:
        failures.append(
            "Hagatha native capture mutates the ledger before correction ordering"
        )
    if not verifier_path.is_file():
        failures.append("Steam Hagatha runtime correction verifier is missing")
    else:
        verifier = read_text(verifier_path)
        _require(
            "Steam Hagatha runtime correction verifier",
            verifier,
            (
                "moderate_damage_clears_until_hurt",
                "lethal_damage_consumes_cheat_death",
                "host_to_client",
                "client_to_host",
                "cheat_death_charges",
                "serendipity_active",
                "reverie_active",
                "results: dict[str, Any] = {}",
                "results[direction.name] = verify_direction",
                "direction_error",
            ),
            failures,
        )
        if "results = {\n        direction.name: verify_direction" in verifier:
            failures.append(
                "Hagatha runtime verifier discards completed directions on failure"
            )

    if failures:
        raise StaticReTestFailure("; ".join(failures))
    return "Cheat Death HP recovery and one-shot runtime fields have a two-owner Steam regression"


def test_hagatha_combat_modifiers_have_exact_two_owner_coverage() -> str:
    """Curing, Glass Cannon, and Curse Bosses must use their stock damage lanes."""

    seams = read_text(ROOT / "SolomonDarkModLoader/src/gameplay_seams.h")
    storage = read_text(
        ROOT / "SolomonDarkModLoader/src/gameplay_seams/address_storage.inl"
    )
    address_bindings = read_text(
        ROOT / "SolomonDarkModLoader/src/gameplay_seams/state_and_address_bindings.inl"
    )
    size_bindings = read_text(
        ROOT / "SolomonDarkModLoader/src/gameplay_seams/size_bindings.inl"
    )
    binary_layout = read_text(ROOT / "config/binary-layout.ini")
    constants = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/gameplay_constants.inl"
    )
    enemy_types = read_text(
        ROOT / "SolomonDarkModLoader/include/native_enemy_types.h"
    )
    native_types = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/native_function_types.inl"
    )
    request_state = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/runtime_request_state.inl"
    )
    hook_path = (
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/badguy_damage_hook.inl"
    )
    hook = read_text(hook_path) if hook_path.is_file() else ""
    player_damage_hook = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_damage_authority_hook.inl"
    )
    hook_registry = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_tick_and_render_hooks.inl"
    )
    hook_lifecycle = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_keyboard_injection.inl"
    )
    native_probe = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/native_defense_behavior_probes.inl"
    )
    public_api = read_mod_loader_header_source()
    action_queue = read_source_unit(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_gameplay_action_queues.inl"
    )
    lua_debug = read_text(
        ROOT
        / "SolomonDarkModLoader/src/lua_engine_bindings_debug/functions_native_calls.inl"
    )
    defense_harness = read_text(
        ROOT / "tools/multiplayer_defense_behavior_harness.py"
    )
    verifier_path = ROOT / "tools/verify_steam_hagatha_combat_modifier_matrix.py"
    verifier = read_text(verifier_path) if verifier_path.is_file() else ""

    failures: list[str] = []
    _require(
        "Badguy damage seams",
        seams + storage + address_bindings + size_bindings + binary_layout,
        (
            "kBadguyDamage",
            '"badguy_damage"',
            "badguy_damage=0x0048A290",
            "kDamageSourceGameplaySlotOffset",
            '"damage_source_gameplay_slot"',
            "damage_source_gameplay_slot=0x60",
        ),
        failures,
    )
    _require(
        "Curse Bosses native contract",
        constants
        + enemy_types
        + native_types
        + request_state
        + player_damage_hook
        + hook
        + hook_registry
        + hook_lifecycle,
        (
            "kHagathaCuringSelector = 11",
            "kHagathaGlassCannonSelector = 16",
            "kHagathaCurseBossesSelector = 22",
            "kHagathaCurseBossesDamageMultiplier = 3.0f",
            "kDemonSkullNativeTypeId = 0x3F0",
            "kDemonNativeTypeId = 0x3F1",
            "kDireFacultyNativeTypeId = 0x3F2",
            "kHeartmongerNativeTypeId = 0x3F3",
            "BadguyDamageFn",
            "badguy_damage_hook",
            'gameplay_hooks/badguy_damage_hook.inl',
            "HookBadguyDamage",
            "ResolveDamageSourceOwnerActorAddress",
            "ResolveDamageSourceParticipantId",
            "TryResolveDamageSourceProgressionAddress",
            "kProgressionHagathaPerkFlagBaseOffset",
            "TryApplyHagathaCurseBossesDamageMultiplier",
            "RestoreHagathaCurseBossesDamageLanes",
            "RemoveX86Hook(&g_gameplay_keyboard_injection.badguy_damage_hook)",
        ),
        failures,
    )
    if "context_target != actor_address" in hook:
        failures.append(
            "Curse Bosses enemy damage is incorrectly gated by the unrelated "
            "damage_context_target actor-tick global"
        )
    _require(
        "Curing poison-lane probe",
        request_state + native_probe + public_api + action_queue + lua_debug + defense_harness,
        (
            "float poison_damage = 0.0f;",
            "request.poison_damage",
            "float poison_damage,",
            "poison_damage: float = 0.0",
            "projectile_damage <= 0.0f && magic_damage <= 0.0f &&",
            "poison_damage <= 0.0f",
            "index == 2 ? request.poison_damage",
            "queue_native_magic_hit_behavior_probe(",
        ),
        failures,
    )
    if not verifier_path.is_file():
        failures.append("two-owner Steam Hagatha combat-modifier verifier is missing")
    _require(
        "two-owner Steam Hagatha combat-modifier verifier",
        verifier,
        (
            "CURING_SELECTOR = 11",
            "GLASS_CANNON_SELECTOR = 16",
            "CURSE_BOSSES_SELECTOR = 22",
            '"host_to_client"',
            '"client_to_host"',
            '"curing_poison_incoming"',
            '"glass_cannon_incoming"',
            '"glass_cannon_outgoing"',
            '"curse_bosses_boss_damage"',
            '"curse_bosses_nonboss_damage"',
            '"unrelated_owner_unchanged"',
            "invoke_native_magic_hit_trial",
            "run_cast_trial",
            "owner_participant_id",
            "observer_participant_id",
            "source_pids = {\"host\": 0, \"client\": 0}",
            'result["combat_bootstrap"] = primary.enable_manual_stock_spawner_combat()',
            'result["arena_reset"] = reset_quiet_arena()',
            "reset_life: bool = True",
            "if reset_life:",
            '"reset_life": reset_life',
            "reset_life=False",
            "instances = (HOST_INSTANCE, CLIENT_INSTANCE)",
            "new_crash_artifacts(started_at, instances)",
            "scoped_new_crash_artifacts",
            "windows_process_id(HOST_INSTANCE)",
            'f"SolomonDark.exe.{host_process_id}.dmp"',
        ),
        failures,
    )
    if "battle_siege.detect_instance_pids()" in verifier:
        failures.append(
            "active Steam Hagatha verifier uses the Windows-only local-pair PID resolver"
        )
    if "new_crash_artifacts(started_at)" in verifier:
        failures.append(
            "active Steam Hagatha verifier omits instance names from crash scanning"
        )
    run_entry_index = verifier.find('result["run_entry"] = run_driver.start_shared_run(')
    combat_bootstrap_index = verifier.find(
        'result["combat_bootstrap"] = primary.enable_manual_stock_spawner_combat()'
    )
    arena_reset_index = verifier.find('result["arena_reset"] = reset_quiet_arena()')
    if not (
        run_entry_index >= 0
        and combat_bootstrap_index > run_entry_index
        and arena_reset_index > combat_bootstrap_index
    ):
        failures.append(
            "active Steam Hagatha verifier does not bootstrap and reset the stock wave spawners after run entry"
        )

    if failures:
        raise StaticReTestFailure("; ".join(failures))
    return "Curing, Glass Cannon, and repaired Curse Bosses have exact two-owner native damage coverage"


def test_hagatha_client_damage_ratio_allows_one_claim_quantum() -> str:
    """Client Air claims may round one 1/128 step away from a native multiplier."""

    import verify_steam_hagatha_combat_modifier_matrix as verifier

    claim_quantum = getattr(verifier, "CLIENT_DAMAGE_CLAIM_QUANTUM", None)
    if claim_quantum != 1.0 / 128.0:
        raise StaticReTestFailure(
            "Hagatha combat verification does not name the client damage-claim quantum"
        )

    baseline = 3.0 / 128.0
    observed = 10.0 / 128.0
    try:
        verifier.ratio_contract(
            "quantized client Air claim",
            baseline,
            observed,
            3.0,
        )
    except Exception:
        pass
    else:
        raise StaticReTestFailure(
            "strict relative tolerance unexpectedly accepts the rounded client claim"
        )

    try:
        contract = verifier.ratio_contract(
            "quantized client Air claim",
            baseline,
            observed,
            3.0,
            absolute_tolerance=claim_quantum,
        )
    except Exception as exc:
        raise StaticReTestFailure(
            "one exact client claim quantum must cover native multiplier rounding: "
            f"{exc}"
        ) from exc
    if not contract.get("ok") or contract.get("absolute_tolerance") != claim_quantum:
        raise StaticReTestFailure(
            "quantized client claim contract did not record its bounded tolerance"
        )

    return "client Air multiplier checks allow exactly one 1/128 damage-claim step"
