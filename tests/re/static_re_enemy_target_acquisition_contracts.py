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
            "`uint __fastcall(int* hostile)`",
            "six-byte instruction boundary",
            "`0x00483895`",
            "unconditionally writes zero to",
            "Badguy_RefreshTargetThenDispatch (0x00484AA0)",
            "Badguy_RefreshTargetLongCadence (0x00487F60)",
            "Badguy_ContactTargetScan (0x004881A0)",
            "Badguy_ClearLinkedTargetAndNotifySlots",
            "clients must not independently choose a nearest target",
            "Player-owned summon ActorWorld slots are peer-local",
            "owner participant plus the native ally type",
            "completion latch at `hostile + 0x68`",
            "ActorWorld registration tail to clear it",
            "successful extended selection",
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
            "actor_register_transient=0x68",
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
            "kBadguyCommonChaseTick",
            "kGameplayHostileTargetCandidateListOffset",
            "kActorWorldRegionIndexOffset",
            "kActorRegisterTransientOffset",
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
            "uintptr_t kBadguyCommonChaseTick = 0;",
            "std::size_t kGameplayHostileTargetCandidateListOffset = 0;",
            "std::size_t kActorWorldRegionIndexOffset = 0;",
            "std::size_t kActorRegisterTransientOffset = 0;",
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
            '"badguy_common_chase_tick", kBadguyCommonChaseTick',
        ),
    )
    _require_tokens(
        "gameplay size bindings",
        size_bindings,
        (
            '"gameplay_hostile_target_candidate_list", '
            "kGameplayHostileTargetCandidateListOffset",
            '"actor_world_region_index", kActorWorldRegionIndexOffset',
            '"actor_register_transient", kActorRegisterTransientOffset',
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


def test_extended_target_selection_completes_native_chase_latch() -> str:
    acquisition = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "hostile_target_acquisition.inl"
    )
    start = acquisition.index("bool ApplyHostileTargetSelection(")
    apply_target = acquisition[start:]

    _require_tokens(
        "extended hostile target completion",
        apply_target,
        (
            "selection.valid",
            "kActorCurrentTargetActorOffset",
            "kHostileTargetBucketDeltaOffset",
            "kActorRegisterTransientOffset",
            "TryWriteField<std::uint8_t>",
            "complete the same success contract",
        ),
    )
    target_write = apply_target.index("kActorCurrentTargetActorOffset")
    bucket_write = apply_target.index(
        "kHostileTargetBucketDeltaOffset",
        target_write,
    )
    valid_completion = apply_target.index(
        "if (selection.valid)",
        bucket_write,
    )
    latch_clear = apply_target.index(
        "kActorRegisterTransientOffset",
        valid_completion,
    )
    assert target_write < bucket_write < valid_completion < latch_clear
    assert ",\n                0)" in apply_target[latch_clear:latch_clear + 160]

    return (
        "a validated extended authority target releases the native selector "
        "latch only after target and bucket publication"
    )


def test_enemy_retarget_acceptance_gate_is_wired() -> str:
    verifier = read_text(
        ROOT / "tools/verify_multiplayer_enemy_retarget.py"
    )
    process_cleanup = read_text(
        ROOT / "tools/owned_process_ledger.py"
    )
    process_bridge = read_text(
        ROOT / "tools/verify_local_multiplayer_sync.py"
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
            "authority_target_participant_id",
            "authority_target_native_type_id",
            "analyze_retarget_samples(",
            "_wait_for_logical_death(",
            "_wait_for_stable_host_target(",
            "_wait_for_host_target_layout(",
            "TARGET_LAYOUT_STABLE_SAMPLES = 3",
            "focus.cast_secondary_belt_slot(",
            "ETHER_MINION_NATIVE_TYPE_ID",
            "capture_game_backbuffer",
            "stop_exact_game_processes(",
            "test_blank_boneyard=True",
            "_path_from_powershell(runtime_root_value)",
        ),
    )
    _require_tokens(
        "exact pair-process cleanup",
        process_cleanup,
        (
            "class OwnedProcessLedger:",
            "Get-CimInstance -ClassName Win32_Process",
            '-Filter "ProcessId = $processId"',
            "$process.ExecutablePath",
            "if (-not $refused)",
            "refused to stop launcher PIDs with different executables",
        ),
    )
    _require_tokens(
        "exact pair-process cleanup bridge",
        process_bridge,
        (
            "def stop_exact_game_processes(",
            "register_owned_launch(launch)",
            "return stop_owned_process_ids(",
        ),
    )
    _require_tokens(
        "enemy retarget verifier unit tests",
        unit_tests,
        (
            "test_idle_enemy_fails_even_when_the_old_gate_has_no_mismatch",
            "test_dead_or_ineligible_player_never_satisfies_target_match",
            "test_native_minion_identity_must_converge_on_both_peers",
            "test_native_minion_identity_rejects_the_wrong_owner",
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


def test_enemy_retarget_is_authoritative_nearest_and_event_driven() -> str:
    acquisition = "".join(
        read_text(
            ROOT
            / "SolomonDarkModLoader/src/mod_loader_gameplay/"
            / source_name
        )
        for source_name in (
            "hostile_target_acquisition.inl",
            "hostile_target_invalidation.inl",
        )
    )
    monster_hook = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "monster_pathfinding_hook.inl"
    )
    lifecycle_hook = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "dispatch_and_hooks_actor_lifecycle_hooks.inl"
    )
    installation = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_keyboard_injection.inl"
    )
    runtime_state = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/core/"
        "runtime_request_state.inl"
    )
    player_tick = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "actor_tick/player_actor_tick_hook.inl"
    )
    participant_scene_tick = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "bot_movement_tick/participant_scene_binding_ticks.inl"
    )
    resource_state = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/"
        "resource_state.inl"
    )
    world_target_reconciliation = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "world_snapshot_reconciliation/"
        "run_enemy_targeting_and_retirement.inl"
    )
    world_snapshot_capture = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "world_snapshot_capture.inl"
    )
    _require_tokens(
        "authoritative hostile target acquisition",
        acquisition,
        (
            "TryReadNativeHostileTargetCandidateList(",
            "AppendWizardParticipantTargetCandidates(",
            "TryResolvePlayerActorForSlot(",
            "multiplayer::GetLocalTransportParticipantId()",
            "multiplayer::kLocalParticipantId",
            "kGoodImpHostileTargetTypeId = 0x03ED",
            "kLeviathanHostileTargetTypeId = 0x07F2",
            "kGolemHostileTargetTypeId = 0x07F4",
            "kActorHostileTargetIneligibleStateOffset",
            "IsActorRuntimeDead(candidate_actor_address)",
            "IsDeadWizardParticipantActor(candidate_actor_address)",
            "bucket_actor_address != candidate_actor_address",
            "static_cast<uintptr_t>(bucket_index) * sizeof(uintptr_t)",
            "TryReadGameplayIndexStateValue(",
            "extended_slot_or_ally_candidate",
            "mapped_region_index != static_cast<int>(world_region_index) &&",
            "IsPreferredHostileTargetCandidate(",
            "ApplyNearestValidHostileTarget(",
            "ApplyHostileTargetSelection(",
            "IsParticipantRuntimeDeadForHostileTargeting(",
            "RefreshHostileTargetParticipantDeathLatches(",
            "kHostileTargetLocalDeathFallbackMs = 1500",
            "awaiting_local_native_death_transition",
            "HasLocalPlayerNativeDeathTransitionStarted(",
            "kActorHostileTargetIneligibleStateOffset",
            "ScheduleHostileTargetReacquisitionAfterNativeDeathTransition(",
            "DeferHostileTargetReacquisitionForLocalNativeDeath(",
            "IsHostileTargetReacquisitionDeferred(",
            "participant life-zero captured for native-transition-safe reacquisition",
            "MaintainInvalidatedHostileTargetAfterNativeTick(",
            "MaintainMissingOrInvalidHostileTargetAfterNativeTick(",
            '"participant_death_maintenance"',
            "MaintainInvalidatedHostileTargetsAfterLocalPlayerTick(",
            '"participant_death_post_player_tick"',
            "kHostileTargetNearestMaintenanceIntervalMs = 100",
            "MaintainNearestValidHostileTargets(",
            "ReplacePlayerOwnedHostileTargetSidecars(",
            "!actor.tracked_enemy",
            '"nearest_valid_maintenance"',
            "target_participant_id=",
            "target_native_type_id=",
            "g_last_logged_hostile_target_by_actor.try_emplace(",
            "semantic_target_change",
        ),
    )
    _require_tokens(
        "hostile target selector hook",
        monster_hook,
        (
            "ApplyHigherPriorityHostileTargetPolicy(",
            "HookMonsterPathfindingSelectNearestTarget(",
            "GetX86HookTrampoline<MonsterPathfindingSelectNearestTargetFn>",
            "original(self, nullptr);",
            '"native_selector"',
            '"native_refresh"',
            "HookBadguyCommonChaseTick(",
            "GetX86HookTrampoline<BadguyCommonChaseTickFn>",
            "MaintainInvalidatedHostileTargetAfterNativeTick(",
            "MaintainMissingOrInvalidHostileTargetAfterNativeTick(",
            "ClearHostileTargetsForDeadWizardActor(",
            "ScheduleHostileTargetReacquisitionAfterNativeDeathTransition(",
            "DeferHostileTargetReacquisitionForLocalNativeDeath(",
            "IsHostileTargetReacquisitionDeferred(",
            "ReacquireHostileTargetAfterInvalidation(",
            "ApplyLatestReplicatedRunEnemyTargetForLocalActor(",
        ),
    )
    selector = monster_hook[
        monster_hook.index("void __fastcall HookMonsterPathfindingSelectNearestTarget(") :
        monster_hook.index("void __fastcall HookMonsterPathfindingRefreshTarget(")
    ]
    priority_policy = selector.index(
        "ApplyHigherPriorityHostileTargetPolicy("
    )
    preselection = selector.index(
        "TrySelectNearestValidHostileTarget("
    )
    retail_guard = selector.index(
        "!selection.retail_selector_can_commit",
        preselection,
    )
    extended_commit = selector.index(
        "ApplyHostileTargetSelection(",
        retail_guard,
    )
    skip_retail = selector.index("return;", extended_commit)
    retail_selector = selector.index("original(self, nullptr);")
    assert '"native_selector")) {' in selector[
        extended_commit:skip_retail
    ]
    assert (
        priority_policy
        < preselection
        < retail_guard
        < extended_commit
        < skip_retail
        < retail_selector
    )
    assert "ApplyNearestValidHostileTarget(" not in selector

    diagnostic = acquisition[
        acquisition.index("void LogRejectedExtendedHostileTargetCandidate(") :
        acquisition.index("bool TrySelectNearestValidHostileTarget(")
    ]
    expected_exclusion = diagnostic.index(
        "if ((have_ineligible_state && ineligible_state != 0) ||"
    )
    diagnostic_rate_limit = diagnostic.index(
        "s_last_diagnostic_ms = now_ms;"
    )
    diagnostic_log = diagnostic.index(
        'Log(\n        std::string("[hostile_ai] rejected extended target candidate")'
    )
    assert expected_exclusion < diagnostic_rate_limit < diagnostic_log

    _require_tokens(
        "ActorWorld target-removal lifecycle",
        lifecycle_hook,
        (
            "CaptureLiveHostilesTargetingActor(",
            "hostiles_targeting_removed_actor",
            '"target_removal"',
            "ReacquireHostileTargetAfterInvalidation(",
            "g_last_logged_hostile_target_by_actor.erase(actor_address);",
        ),
    )
    capture = lifecycle_hook.index("CaptureLiveHostilesTargetingActor(")
    unregister = lifecycle_hook.index(
        "original(self, actor, remove_from_container);",
        capture,
    )
    reacquire = lifecycle_hook.index(
        "ReacquireHostileTargetAfterInvalidation(",
        unregister,
    )
    assert capture < unregister < reacquire

    _require_tokens(
        "participant target maintenance cadence",
        participant_scene_tick,
        ("MaintainNearestValidHostileTargets(now_ms);",),
    )
    _require_tokens(
        "local-player death-transition maintenance",
        player_tick,
        ("MaintainInvalidatedHostileTargetsAfterLocalPlayerTick();",),
    )
    chase_tick = monster_hook[
        monster_hook.index("std::uint32_t __fastcall HookBadguyCommonChaseTick(") :
    ]
    original_chase = chase_tick.index("const auto result = original(self, nullptr);")
    defer_local_death = chase_tick.index(
        "DeferHostileTargetReacquisitionForLocalNativeDeath(",
        original_chase,
    )
    restore_target = chase_tick.index(
        "kActorCurrentTargetActorOffset,",
        defer_local_death,
    )
    assert original_chase < defer_local_death < restore_target
    _require_tokens(
        "actor runtime-death type ownership",
        resource_state,
        (
            "if (IsArenaEnemyActorHealthType(object_type_id)) {",
            "kEnemyDeathHandledOffset",
            "object_type_id == 1 &&",
            "TryReadActorProgressionHealth(actor_address, &health)",
            "Other actors do not own the",
        ),
    )
    _require_tokens(
        "player-owned target snapshot identity",
        world_snapshot_capture,
        (
            "ResolvePlayerOwnedTargetParticipantId(",
            "kLeviathanTargetNativeTypeId = 0x07F2",
            "target_participant_id",
        ),
    )
    _require_tokens(
        "player-owned target peer-local resolution",
        world_target_reconciliation,
        (
            "ResolveReplicatedRunEnemyNativeTargetActor(",
            "owner_actor_group",
            "IsExplicitPlayerOwnedHostileTargetType(",
            "candidate_distance_squared",
        ),
    )

    _require_tokens(
        "nearest-target selector installation",
        installation,
        (
            "ResolveGameAddressOrZero(\n"
            "            kMonsterPathfindingSelectNearestTarget)",
            "HookMonsterPathfindingSelectNearestTarget",
            "kMonsterPathfindingSelectNearestTargetHookMinimumPatchSize",
            "monster_pathfinding_select_nearest_target_hook",
            "ResolveGameAddressOrZero(\n"
            "            kBadguyCommonChaseTick)",
            "HookBadguyCommonChaseTick",
            "kBadguyCommonChaseTickHookMinimumPatchSize",
            "badguy_common_chase_tick_hook",
        ),
    )
    assert (
        "X86Hook monster_pathfinding_select_nearest_target_hook;"
        in runtime_state
    )
    assert "X86Hook badguy_common_chase_tick_hook;" in runtime_state

    behavior = acquisition + monster_hook
    native_death_transition_predicate = acquisition[
        acquisition.index("bool HasLocalPlayerNativeDeathTransitionStarted("):
        acquisition.index(
            "bool IsHostileTargetReacquisitionDeferred(",
            acquisition.index(
                "bool HasLocalPlayerNativeDeathTransitionStarted("
            ),
        )
    ]
    assert (
        "kActorAnimationDriveStateByteOffset"
        not in native_death_transition_predicate
    ), (
        "ordinary animation-drive state must not release the local native "
        "death-transition grace period"
    )
    reacquisition_deferred_predicate = acquisition[
        acquisition.index("bool IsHostileTargetReacquisitionDeferred("):
        acquisition.index(
            "void ScheduleHostileTargetReacquisitionAfterNativeDeathTransition(",
            acquisition.index(
                "bool IsHostileTargetReacquisitionDeferred("
            ),
        )
    ]
    _require_tokens(
        "hostile death-transition maintenance membership",
        reacquisition_deferred_predicate,
        (
            "maintenance.hostile_actor_addresses.find(",
            "maintenance.hostile_actor_addresses.end()) {",
            "return true;",
        ),
    )
    assert (
        "maintenance.hostile_actor_addresses.find(\n"
        "                hostile_actor_address) ==\n"
        "            maintenance.hostile_actor_addresses.end()) {"
        in reacquisition_deferred_predicate
    ), (
        "the death-transition grace must be evaluated for affected hostiles, "
        "not skipped for them"
    )
    for forbidden in (
        "ActorWorld_RelocateHostileToGroupZero",
        "HookMonsterPathfindingRefreshTarget promotion",
        "CallActorWorldRegisterSafe",
        "CallActorWorldUnregisterSafe",
    ):
        assert forbidden not in behavior, (
            "nearest-target policy must never promote or relocate a target: "
            + forbidden
        )

    return (
        "host authority chooses the nearest live native, participant, or "
        "player-owned ally and death/removal edges force reacquisition "
        "without ActorWorld promotion"
    )
