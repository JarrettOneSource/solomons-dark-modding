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
    if catalog.get("schema_version") != 1:
        failures.append("catalog schema_version is not 1")
    if catalog.get("native_functions") != {
        "name": "0x00571DD0",
        "price_table": "0x005A7CA0",
        "description": "0x00573E90",
        "apply": "0x0066EF70",
        "refresh": "0x0067C360",
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
            if not isinstance(row.get("behavior_family"), str) or not row["behavior_family"]:
                failures.append(f"perk row {selector} has no behavior family")
            if not isinstance(row.get("network_scope"), str) or not row["network_scope"]:
                failures.append(f"perk row {selector} has no network ownership scope")

    if failures:
        raise StaticReTestFailure("; ".join(failures))
    return "all 28 stock Hagatha outcomes have exact names, prices, behavior, and native evidence"


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
            "constexpr std::uint16_t kProtocolVersion = 81;",
            "kParticipantHagathaPerkMaxCount = 9",
            "struct ParticipantHagathaPerkPacketState",
            "std::uint32_t hagatha_perk_revision;",
            "ParticipantHagathaPerkPacketState hagatha_perks;",
            "static_assert(sizeof(ParticipantHagathaPerkPacketState) == 20",
            "static_assert(sizeof(StatePacket) == 4544",
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
            "packet.hagatha_perk_revision",
            "packet.hagatha_perks",
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
            "cheat_death_consumed\n            ? packet.life_current",
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
