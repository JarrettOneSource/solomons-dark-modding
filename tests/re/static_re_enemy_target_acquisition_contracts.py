"""Native hostile target acquisition and invalidation contracts."""

from __future__ import annotations

from static_re_contract_support import (
    BINARY_LAYOUT,
    PATHFINDING_RE_DOC,
    ROOT,
    StaticReTestFailure,
    read_text,
)


TARGET_ACQUISITION_RE_DOC = (
    ROOT / "docs/reverse-engineering/native-enemy-target-acquisition.md"
)


def _require_tokens(source_name: str, text: str, tokens: tuple[str, ...]) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise StaticReTestFailure(
            f"{source_name} is missing hostile-target contract token(s): " +
            ", ".join(missing)
        )


def test_native_enemy_target_acquisition_is_recovered_and_layout_backed() -> str:
    acquisition_doc = read_text(TARGET_ACQUISITION_RE_DOC)
    pathfinding_doc = read_text(PATHFINDING_RE_DOC)
    layout = read_text(BINARY_LAYOUT)
    seam_header = read_text(ROOT / "SolomonDarkModLoader/src/gameplay_seams.h")
    seam_storage = read_text(
        ROOT / "SolomonDarkModLoader/src/gameplay_seams/address_storage.inl"
    )
    address_bindings = read_text(
        ROOT / "SolomonDarkModLoader/src/gameplay_seams/state_and_address_bindings.inl"
    )
    size_bindings = read_text(
        ROOT / "SolomonDarkModLoader/src/gameplay_seams/size_bindings.inl"
    )

    _require_tokens(
        "native enemy target acquisition RE note",
        acquisition_doc,
        (
            "MonsterPathfinding_SelectNearestTarget (0x00481A60)",
            "`gameplay + 0x1388`",
            "`gameplay + 0x1390`",
            "`gameplay + 0x139C`",
            "`candidate + 0x160 != 0`",
            "`gameplay_index_state_table[candidate_group] == actor_world + 0x78`",
            "ActorWorld_RelocateHostileToGroupZero (0x0063F7A0)",
            "Player_HostileCandidateRegister (0x0052A500)",
            "Player_HostileCandidateUnregister (0x00529410)",
            "Golem_HostileCandidateRegister (0x005F57E0)",
            "Golem_HostileCandidateUnregister (0x005F5A20)",
            "Player_DeathTransition (0x00534120)",
            "GoodImp (0x3ED)",
            "Leviathan (0x7F2)",
            "Golem (0x7F4)",
            "MonsterPathfinding_RefreshTarget (0x00483480)",
            "Badguy_CommonChaseTick (0x004835F0)",
            "Badguy_RefreshTargetThenDispatch (0x00484AA0)",
            "Badguy_RefreshTargetLongCadence (0x00487F60)",
            "Badguy_ContactTargetScan (0x004881A0)",
            "Badguy_ClearLinkedTargetAndNotifySlots",
            "clients must not independently choose a nearest target",
            "never relocate or",
            "promote the target actor",
        ),
    )
    _require_tokens(
        "pathfinding investigation",
        pathfinding_doc,
        (
            "docs/reverse-engineering/native-enemy-target-acquisition.md",
            "host-death asymmetry",
            "GoodImp (`0x3ED`)",
            "Leviathan (`0x7F2`)",
            "ActorWorld_RelocateHostileToGroupZero (0x0063F7A0)",
        ),
    )
    _require_tokens(
        "binary layout",
        layout,
        (
            "monster_pathfinding_select_nearest_target=0x00481A60",
            "monster_pathfinding_refresh_target=0x00483480",
            "badguy_common_chase_tick=0x004835F0",
            "badguy_refresh_target_then_dispatch=0x00484AA0",
            "badguy_clear_linked_target_and_notify_slots=0x00484B30",
            "badguy_refresh_target_long_cadence=0x00487F60",
            "badguy_contact_target_scan=0x004881A0",
            "gameplay_hostile_candidate_lists_ctor=0x005CC800",
            "player_hostile_candidate_register=0x0052A500",
            "player_hostile_candidate_unregister=0x00529410",
            "player_death_transition=0x00534120",
            "golem_hostile_candidate_register=0x005F57E0",
            "golem_hostile_candidate_unregister=0x005F5A20",
            "good_imp_ctor=0x00529FE0",
            "good_imp_initialize=0x0052A050",
            "leviathan_ctor=0x005E8FB0",
            "leviathan_dtor=0x005F4670",
            "actor_world_relocate_hostile_to_group_zero=0x0063F7A0",
            "gameplay_hostile_target_candidate_list=0x1388",
            "actor_world_region_index=0x78",
            "actor_hostile_target_ineligible_state=0x160",
            "actor_target_repath_phase=0x1DC",
            "actor_target_missing_state=0x1D8",
        ),
    )
    _require_tokens(
        "gameplay seam declarations",
        seam_header,
        (
            "kMonsterPathfindingSelectNearestTarget",
            "kGameplayHostileTargetCandidateListOffset",
            "kActorWorldRegionIndexOffset",
            "kActorHostileTargetIneligibleStateOffset",
            "kActorTargetRepathPhaseOffset",
            "kActorTargetMissingStateOffset",
        ),
    )
    _require_tokens(
        "gameplay seam storage",
        seam_storage,
        (
            "uintptr_t kMonsterPathfindingSelectNearestTarget = 0;",
            "std::size_t kGameplayHostileTargetCandidateListOffset = 0;",
            "std::size_t kActorWorldRegionIndexOffset = 0;",
            "std::size_t kActorHostileTargetIneligibleStateOffset = 0;",
            "std::size_t kActorTargetRepathPhaseOffset = 0;",
            "std::size_t kActorTargetMissingStateOffset = 0;",
        ),
    )
    _require_tokens(
        "gameplay address bindings",
        address_bindings,
        (
            '"monster_pathfinding_select_nearest_target", '
            "kMonsterPathfindingSelectNearestTarget",
        ),
    )
    _require_tokens(
        "gameplay size bindings",
        size_bindings,
        (
            '"gameplay_hostile_target_candidate_list", '
            "kGameplayHostileTargetCandidateListOffset",
            '"actor_world_region_index", kActorWorldRegionIndexOffset',
            '"actor_hostile_target_ineligible_state", '
            "kActorHostileTargetIneligibleStateOffset",
            '"actor_target_repath_phase", kActorTargetRepathPhaseOffset',
            '"actor_target_missing_state", kActorTargetMissingStateOffset',
        ),
    )

    return (
        "native hostile acquisition, candidate ownership, host-death "
        "invalidation, and unsafe relocation boundaries are layout-backed"
    )


def test_enemy_retarget_acceptance_gate_is_wired() -> str:
    verifier = read_text(
        ROOT / "tools/verify_multiplayer_enemy_retarget.py"
    )
    unit_tests = read_text(
        ROOT / "tests/test_multiplayer_enemy_retarget_verifier.py"
    )
    workflow = read_text(
        ROOT / ".github/workflows/lua-authoring-contracts.yml"
    )
    netcode_doc = read_text(
        ROOT / "docs/networking/netcode-review.md"
    )

    _require_tokens(
        "enemy retarget live verifier",
        verifier,
        (
            'choices=("host-death", "client-death", "ether-minion")',
            "MAX_HOST_REACQUIRE_LATENCY_MS = 1_500.0",
            "MAX_CLIENT_REACQUIRE_LATENCY_MS = 2_000.0",
            "MINIMUM_STABLE_MATCH_SAMPLES = 5",
            "target_ineligible_state",
            "target_participant_id",
            "target_native_type_id",
            "analyze_retarget_samples(",
            "_wait_for_death_transition(",
            "focus.cast_secondary_belt_slot(",
            "ETHER_MINION_NATIVE_TYPE_ID",
            "capture_game_backbuffer",
            "_stop_exact_owned_processes(",
            "pathMatched = $matches",
            "test_blank_boneyard=True",
            "_path_from_powershell(runtime_root_value)",
        ),
    )
    _require_tokens(
        "enemy retarget verifier unit tests",
        unit_tests,
        (
            "test_idle_enemy_fails_even_when_the_old_gate_has_no_mismatch",
            "test_dead_or_ineligible_player_never_satisfies_target_match",
            "test_native_minion_identity_must_converge_on_both_peers",
            "test_participant_reacquisition_requires_stable_host_and_client_match",
        ),
    )
    _require_tokens(
        "CI workflow",
        workflow,
        (
            "Test enemy retarget acceptance verifier",
            "tests.test_multiplayer_enemy_retarget_verifier",
        ),
    )
    _require_tokens(
        "netcode review",
        netcode_doc,
        (
            "Enemy-motion fidelity and enemy-target validity are a joint live acceptance",
            "tools/verify_multiplayer_enemy_retarget.py",
            "both live artifacts report `ok: true`",
            "The prior target-authority check could accept two matching zero targets",
        ),
    )

    return (
        "two-peer death/summon target convergence is a mandatory companion "
        "to the enemy authority-fidelity gate"
    )
