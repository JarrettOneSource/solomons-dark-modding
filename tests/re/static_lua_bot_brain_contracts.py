"""Contracts for the autonomous synthetic-participant bot brain."""

from __future__ import annotations

import json
import re

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_bot_brain_is_host_owned_native_routed_and_wave_five_gated() -> str:
    manifest_text = _read("mods/bot-brain/manifest.json")
    manifest = json.loads(manifest_text)
    main = _read("mods/bot-brain/scripts/main.lua")
    steering = _read("mods/bot-brain/scripts/steering.lua")
    docs = _read("docs/lua-bot-brain.md")
    verifier = _read("tools/verify_lua_bot_brain.py")

    assert manifest["id"] == "bot.brain"
    assert manifest["enabled"] is False
    assert manifest["runtime"]["entryScript"] == "scripts/main.lua"
    required_capabilities = set(
        manifest["runtime"]["requiredCapabilities"]
    )
    for capability in (
        "events.runtime.tick",
        "state.replicated.read",
        "nav.read",
        "waves.read",
        "bots.runtime",
        "bots.state.read",
        "bots.create",
        "bots.move",
        "bots.stop",
        "bots.cast",
    ):
        assert capability in required_capabilities, (
            f"bot brain manifest lacks {capability}"
        )

    _require_in_order(
        main,
        "sd.state.is_authority",
        "ensure_bot(now_ms)",
        "choose_pending_skill()",
        "steering.live_enemies",
        "steering.kite_direction",
        "steering.nearest_cast_target",
        "steering.nearest_enemy",
        "steering.approach_direction",
        "issue_movement(",
        "issue_primary_cast(",
    )
    for token in (
        'bot_name = "Ember"',
        'bot_class = "fire"',
        "think_interval_ms = 250",
        "approach_move_interval_ms = 1000",
        "kite_move_interval_ms = 250",
        "flee_move_interval_ms = 250",
        "threat_radius = 340.0",
        "flee_threat_radius = 900.0",
        "flee_threshold = 0.35",
        "flee_recovery_threshold = 0.45",
        "sd.bots.spawn",
        "sd.bots.list",
        "bot:participant_id()",
        "bot:position()",
        "bot:hp()",
        "bot:max_hp()",
        "bot:alive()",
        "sd.nav.test_segment",
        "bot:move_to(target.x, target.y)",
        "bot:cast(",
        "sd.bots.get_primary_attack_window",
        "sd.bots.get_skill_choices",
        "sd.bots.choose_skill",
        'sd.events.on("runtime.tick"',
        'sd.events.on("run.started"',
        'rawset(_G, "bot_brain_debug"',
    ):
        assert token in main, f"bot brain control policy lacks: {token}"

    for token in (
        "actor.tracked_enemy == true",
        "inverse_distance_weight",
        "arena.center_x - bot_x",
        "perimeter_bias",
        "center_alignment",
        "local tangent_x, tangent_y",
        "path_traversable == true",
        "movement_candidates",
        "nearest_cast_target",
        "nearest_enemy",
        "approach_direction",
    ):
        assert token in steering, f"bot steering policy lacks: {token}"

    combined_lua = main + steering
    for forbidden in (
        r"sd\.bots\.(?:create|update|move_to|cast|destroy|clear)\s*\(",
        r"sd\.debug",
        r"actor_address",
        r"kLocalPlayerActorGlobal",
        r"HookMonsterPathfindingRefreshTarget",
        r"write_(?:float|ptr|u32|i32)",
    ):
        assert re.search(forbidden, combined_lua) is None, (
            f"bot brain contains forbidden legacy control path: {forbidden}"
        )

    for token in (
        "inverse-distance-weighted",
        "arena center",
        "`sd.nav.test_segment`",
        "approaches the nearest enemy",
        "less than 35% HP",
        "above 45% HP",
        "bot:move_to",
        "bot:cast(0, target.x, target.y, 80)",
        "retail staged `data/wave.txt`",
        "Three consecutive",
    ):
        assert token in docs, f"bot brain documentation lacks: {token}"

    for token in (
        'INSTANCE_PREFIX = "bot"',
        "HOST_PORT = 48811",
        "CLIENT_PORT = 48812",
        'EXACT_MOD_ID = "bot.brain"',
        "DEFAULT_RUN_COUNT = 3",
        "enable_audio=False",
        'launch.get("testWaveOverride") not in ("", None)',
        "stop_exact_game_processes(launch)",
        '"highestWaveReached"',
        '"botAliveAtWaveFive"',
        '"timeline"',
        '"castsIssued"',
        '"castsAccepted"',
        '"kitePathDistance"',
        '"host-wave3-mid-fight.png"',
        '"client-wave3-mid-fight.png"',
        "sd.camera.set_focus",
        "sd.camera.clear_focus",
    ):
        assert token in verifier, f"wave-five acceptance lacks: {token}"
    assert "test_wave_override=" not in verifier
    assert "stop_game_processes(" not in verifier

    return (
        "The opt-in fire brain runs only on host ticks, steers synthetic "
        "participant handles through native movement/cast ingress, and requires "
        "three retail-schedule wave-five runs with telemetry and peer visuals"
    )
