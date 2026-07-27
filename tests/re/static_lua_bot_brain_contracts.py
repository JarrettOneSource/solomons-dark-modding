"""Contracts for the autonomous synthetic-participant bot roster."""

from __future__ import annotations

import json
import re

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_bot_brain_is_rostered_native_routed_and_wave_five_gated() -> str:
    manifest = json.loads(_read("mods/bot-brain/manifest.json"))
    main = _read("mods/bot-brain/scripts/main.lua")
    roster = _read("mods/bot-brain/scripts/roster.lua")
    brain = _read("mods/bot-brain/scripts/brain.lua")
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

    entries = {
        entry["key"]: entry
        for entry in manifest["settings"]["entries"]
    }
    assert "persona_name" not in entries
    roster_entry = entries["roster"]
    assert roster_entry["type"] == "list"
    assert roster_entry["scope"] == "host"
    assert roster_entry["min_items"] == 0
    assert roster_entry["max_items"] == 3
    fields = {
        field["key"]: field
        for field in roster_entry["item"]["fields"]
    }
    assert set(fields) == {"name", "element", "discipline"}
    assert [choice["value"] for choice in fields["element"]["choices"]] == [
        "fire",
        "water",
        "earth",
        "air",
        "ether",
    ]
    assert [
        choice["value"]
        for choice in fields["discipline"]["choices"]
    ] == ["skirmisher", "guardian", "striker"]

    _require_in_order(
        main,
        'sd.settings.get("roster")',
        'sd.settings.on_changed(function(key, new_value, old_value)',
        'elseif key == "roster" then',
        "manager:apply(",
        'sd.events.on("runtime.tick"',
        "manager:tick(now_ms, authority)",
    )
    _require_in_order(
        roster,
        "rows_match(existing.row, normalized_row)",
        "self:retire_context(context)",
        "self.contexts = next_contexts",
        "self:ensure_context(",
    )
    _require_in_order(
        brain,
        "sd.bots.get_primary_attack_window",
        "context.steering.nearest_cast_target",
        "issue_movement(",
        "issue_primary_cast(context, now_ms, target)",
    )

    for token in (
        "sd.state.is_authority",
        'sd.settings.is_keybind_down("focus_bot_key")',
        'sd.settings.on_action("respawn_bot"',
        'rawset(_G, "bot_brain_debug"',
        "manager:reset_run(true)",
        "manager:reset_run(false)",
    ):
        assert token in main, f"bot roster wiring lacks: {token}"
    for token in (
        "sd.bots.spawn",
        "sd.bots.list",
        "context.bot:despawn()",
        "class = context.row.element",
        "roster entry ",
        "last_spawn_attempt_ms",
        "self.brain.new(",
    ):
        assert token in roster, f"bot roster reconciliation lacks: {token}"
    for token in (
        "cast_interval_ms = 500",
        "cast_interval_ms = 300",
        "flee_threshold = 0.35",
        "flee_threshold = 0.20",
        "leash_radius = 260.0",
        "engage_radius = 380.0",
        "engage_radius = 240.0",
        'controller_kind or "") == "Native"',
        "ward_distance < previous - 0.5",
        "movement_radius",
        "sd.nav.test_segment",
        "context.bot:move_to(target.x, target.y)",
        "context.bot:cast(",
        "sd.bots.get_skill_choices",
        "sd.bots.choose_skill",
        'context.row.element == "fire"',
        "priority[16] = 2",
        "priority[18] = 3",
        "priority[17] = 4",
    ):
        assert token in brain, f"bot discipline policy lacks: {token}"

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

    combined_lua = main + roster + brain + steering
    for forbidden in (
        r"sd\.bots\.(?:create|update|move_to|cast|destroy|clear)\s*\(",
        r"sd\.debug",
        r"actor_address",
        r"kLocalPlayerActorGlobal",
        r"HookMonsterPathfindingRefreshTarget",
        r"write_(?:float|ptr|u32|i32)",
        r"persona_name",
    ):
        assert re.search(forbidden, combined_lua) is None, (
            f"bot brain contains forbidden legacy path: {forbidden}"
        )

    for token in (
        "zero to three ordered rows",
        "a changed name",
        "`sd.nav.test_segment`",
        "`bot:cast(0, target.x, target.y, 80)`",
        "nearest living human",
        "260 world units",
        "faster 300 ms cadence",
        "flees only below 20% HP",
        "ms2-host",
        "49211/49212",
    ):
        assert token in docs, f"bot roster documentation lacks: {token}"

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
        "The opt-in ordered roster runs three native-routed disciplines on "
        "authority ticks while retaining the retail three-run wave-five gate"
    )
