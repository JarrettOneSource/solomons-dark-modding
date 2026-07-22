"""Native Hagatha charm and curse synchronization contracts."""

from __future__ import annotations

import json

from static_re_contract_support import ROOT, StaticReTestFailure, read_text


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
            "constexpr std::uint16_t kProtocolVersion = 72;",
            "kParticipantHagathaPerkMaxCount = 9",
            "struct ParticipantHagathaPerkPacketState",
            "std::uint32_t hagatha_perk_revision;",
            "ParticipantHagathaPerkPacketState hagatha_perks;",
            "static_assert(sizeof(ParticipantHagathaPerkPacketState) == 20",
            "static_assert(sizeof(StatePacket) == 4512",
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
    authority = read_text(
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
    authority = read_text(
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
