"""Static contracts for the four-fighter all-bot match foundation."""

from __future__ import annotations

from static_re_contract_support import (
    ROOT,
    StaticReTestFailure,
    read_text,
)


def require_tokens(
    text: str,
    label: str,
    tokens: tuple[str, ...],
) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise StaticReTestFailure(
            f"{label} lacks required token(s): {', '.join(missing)}"
        )


def test_all_bot_match_uses_native_slots_real_trigger_and_hp_edges() -> str:
    design = read_text(
        ROOT / "docs/design/all-bot-match-2026-07-28.md"
    )
    runner = read_text(ROOT / "tools/run_bot_match.py")
    hub_bindings = read_text(
        ROOT /
        "SolomonDarkModLoader/src/lua_engine_bindings_input.cpp"
    )
    state_getters = read_text(
        ROOT /
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_state_getters.inl"
    )
    enemy_hook = read_text(
        ROOT /
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "badguy_damage_hook.inl"
    )
    enemy_observer = read_text(
        ROOT /
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "match_enemy_damage_observation.inl"
    )
    player_hook = read_text(
        ROOT /
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "player_damage_authority_hook.inl"
    )
    player_resolver = read_text(
        ROOT /
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "player_hit_feedback_authority_hook.inl"
    )
    player_observer = read_text(
        ROOT /
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "match_player_damage_observation.inl"
    )
    brain = read_text(ROOT / "mods/bot-brain/scripts/brain.lua")
    motion = read_text(
        ROOT /
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "bot_pathfinding_motion_update.inl"
    )
    facing = read_text(
        ROOT /
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "scene_and_animation_drive_profiles.inl"
    )
    cast_processing = read_text(
        ROOT /
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/"
        "pending_cast_processing.inl"
    )

    require_tokens(
        design,
        "four-slot native decision",
        (
            "Gameplay` construction at `0x005CC800`",
            "Slot 0 is the locally controlled player actor",
            "slots 1 through 3",
            "Native enemies resolve and retain gameplay-slot actor targets",
            "one automated local player in",
        ),
    )
    require_tokens(
        runner,
        "all-bot runner",
        (
            "verify_remote_latency_wave5",
            "csp.drive_hub_flow",
            "sd.hub.start_testrun",
            "sd.hub.trigger_solomon_dig()",
            "list_openable_path_obstacles",
            "STUCK_TELEPORT_MARKER",
            "stuckTeleports\"] = 0",
            "reset_enemy_damage_observations",
            "take_enemy_damage_observations",
            "take_player_damage_observations",
            "waveScreenshots",
            "sceneEntryReanchors",
            "minimumSignedProgress",
            "signedProgressBand",
            "gateConvoy",
            "sd.nav.test_segment",
        ),
    )
    for forbidden in (
        "sd.gameplay.start_waves",
        "verify_local_multiplayer_sync",
        "50411",
        "50412",
    ):
        if forbidden in runner:
            raise StaticReTestFailure(
                f"all-bot runner contains forbidden path: {forbidden}"
            )
    if runner.count("sd.bots.update({{") != 1:
        raise StaticReTestFailure(
            "all-bot runner must contain exactly one scene-entry reanchor"
        )

    trigger_body = hub_bindings.split(
        "int LuaHubTriggerSolomonDig", 1
    )[1].split("int LuaHubOpenService", 1)[0]
    require_tokens(
        trigger_body,
        "Solomon trigger",
        (
            "TryGetSolomonDigState",
            "participant_acquired",
            "target_gameplay_slot",
            "interaction_state",
            "stock proximity/conversation transition",
        ),
    )
    for forbidden in ("TryWrite", "start_waves", "StartWaves"):
        if forbidden in trigger_body:
            raise StaticReTestFailure(
                f"Solomon trigger mutates native flow: {forbidden}"
            )

    solomon_getter = state_getters.split(
        "bool TryGetSolomonDigState", 1
    )[1]
    require_tokens(
        solomon_getter,
        "Solomon state reader",
        (
            "0x1391",
            "kSolomonDigInteractionStateOffset",
            "kSolomonDigParticipantAcquiredOffset",
            "kSolomonDigTargetGameplaySlotOffset",
            "TryReadField",
        ),
    )
    if "TryWrite" in solomon_getter:
        raise StaticReTestFailure(
            "Solomon state reader contains a native write"
        )

    require_tokens(
        enemy_hook,
        "enemy damage hook",
        (
            "CaptureEnemyDamageBeforeNativeCall",
            "ObserveEnemyDamageAfterNativeCall",
        ),
    )
    require_tokens(
        enemy_observer,
        "enemy HP observer",
        (
            "target_hp_before",
            "target_hp_after",
            "observation.hp_delta",
            "observation.hp_delta <= 0.0f",
            "source_participant_id",
        ),
    )
    require_tokens(
        player_resolver,
        "generic player damage resolver",
        (
            "HookPlayerActorDamageResolver",
            "CapturePlayerDamageBeforeNativeCall",
            "ObservePlayerDamageAfterNativeCall",
        ),
    )
    magic_body = player_hook.split(
        "HookPlayerActorMagicDamage", 1
    )[1]
    if "CapturePlayerDamageBeforeNativeCall" in magic_body:
        raise StaticReTestFailure(
            "player HP observations remain limited to the magic entrypoint"
        )
    require_tokens(
        player_observer,
        "player HP observer",
        (
            "target_hp_before",
            "target_hp_after",
            "observation.hp_delta",
            "observation.hp_delta <= 0.0f",
            "target_participant_id",
            "source_native_type_id",
        ),
    )
    require_tokens(
        brain,
        "pre-wave bot routing",
        (
            'context.debug.mode = "prewave"',
            "(tonumber(wave.wave) or 0) <= 0",
            "not manual_policy_run",
        ),
    )
    arrival = motion.index(
        "if (target_distance <= kWizardBotPathFinalArrivalThreshold)"
    )
    recovery = motion.index(
        "if (TryTeleportStuckWizardBot(",
        arrival,
    )
    if arrival >= recovery:
        raise StaticReTestFailure(
            "bot path recovery runs before exact-target arrival"
        )
    require_tokens(
        facing,
        "gameplay-slot Fire native heading",
        (
            "ResolveWizardBindingNativeFacingHeading",
            "ResolveNativePrimaryEntryForElement(0)",
            "!cast.remote_per_cast_projectile_observed",
            "90.0f - cast.aim_heading",
        ),
    )
    require_tokens(
        cast_processing,
        "ongoing cast native heading",
        (
            "binding->facing_heading_value = ongoing.aim_heading",
            "ApplyWizardBindingFacingState(binding, actor_address)",
        ),
    )
    return (
        "all-bot orchestration uses four native slots, stock Solomon "
        "conversation state, physical gate transit, native Fire heading, "
        "and applied HP edges"
    )
