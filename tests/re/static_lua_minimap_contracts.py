"""Contracts for the bundled local minimap mod."""

from __future__ import annotations

import json

from static_multiplayer_contract_support import _read


def test_lua_minimap_is_local_live_configurable_and_semantic() -> str:
    manifest = json.loads(_read("mods/lua_minimap/manifest.json"))
    script = _read("mods/lua_minimap/scripts/main.lua")

    assert manifest["id"] == "generic.lua.minimap"
    assert manifest["name"] == "Minimap"
    assert manifest["version"] == "0.1.0"
    assert manifest["enabled"] is False

    runtime = manifest["runtime"]
    assert runtime["apiVersion"] == "0.2.0"
    assert runtime["entryScript"] == "scripts/main.lua"
    assert runtime["requiredCapabilities"] == [
        "events.runtime.tick",
        "draw.local.immediate",
        "draw.text",
        "draw.primitives",
        "settings.self",
    ]

    settings = manifest["settings"]
    assert settings["version"] == 1
    entries = settings["entries"]
    assert [entry["key"] for entry in entries] == [
        "radar_range",
        "show_players",
        "show_enemies",
        "show_orbs",
        "show_items",
        "show_gold",
        "show_dig",
    ]
    assert all(entry["scope"] == "local" for entry in entries)
    assert all(entry["group"] == "Minimap" for entry in entries)

    radar = entries[0]
    assert radar == {
        "key": "radar_range",
        "type": "number",
        "label": "Radar range",
        "description": (
            "World-unit radius the minimap covers. Lower zooms in; higher "
            "shows more of the arena. Applies live."
        ),
        "default": 520,
        "min": 200,
        "max": 1600,
        "step": 20,
        "integer": True,
        "scope": "local",
        "group": "Minimap",
    }
    assert all(entry["type"] == "toggle" for entry in entries[1:])
    assert all(entry["default"] is True for entry in entries[1:])

    for token in (
        "local PLAYER_OBJECT_TYPE = 0x1",
        "local ORB_OBJECT_TYPE = 0x7DB",
        "local player = sd.player.get_state()",
        "local actors = sd.world.list_actors()",
        "actor.object_type_id == PLAYER_OBJECT_TYPE",
        "actor.tracked_enemy and not actor.dead",
        "actor.object_type_id == ORB_OBJECT_TYPE",
        "local loot = sd.world.get_replicated_loot()",
        "if drop.active then",
        'Gold = "gold"',
        'Item = "item"',
        'Potion = "item"',
        'Powerup = "item"',
        "pcall(sd.hub.get_solomon_dig_state)",
        'sd.events.on("runtime.tick"',
        "sd.draw.get_viewport()",
        "sd.draw.rect(",
        "sd.draw.line(",
    ):
        assert token in script, f"minimap semantic render contract lacks: {token}"

    for key in (
        "radar_range",
        "show_players",
        "show_enemies",
        "show_orbs",
        "show_items",
        "show_gold",
        "show_dig",
    ):
        assert f'sd.settings.get("{key}")' in script or f'"{key}"' in script
    assert "sd.settings.on_changed(function(key, new_value)" in script
    assert "local scale = RADAR_RADIUS_PX / radar_range" in script

    assert "vtable_address" not in script
    assert "sd.net" not in script
    assert "sd.world.spawn_reward" not in script
    assert "sd.world.trigger_enemy_death" not in script

    return (
        "The Minimap package is disabled by default, owns seven local live "
        "settings, and renders semantic player, enemy, orb, replicated-loot, "
        "and Solomon Dig state without transport or static vtable coupling"
    )
