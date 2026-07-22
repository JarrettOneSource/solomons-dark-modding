#!/usr/bin/env python3
"""Verify the static contract for owner-side Lua spell-cast filters."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_SNIPPETS = (
    (
        "SolomonDarkModLoader/include/lua_event_filters.h",
        "kLuaSpellCastingFilterMask",
        "filter registration mask",
    ),
    (
        "SolomonDarkModLoader/include/lua_event_filters.h",
        "struct LuaSpellCastFilterContext",
        "native payload",
    ),
    (
        "SolomonDarkModLoader/src/lua_engine_filters.cpp",
        'filter_name == "spell.casting"',
        "public filter name",
    ),
    (
        "SolomonDarkModLoader/src/lua_engine_spell_cast_filters.cpp",
        "ApplyLuaSpellCastFilters",
        "ordered Lua dispatcher",
    ),
    (
        "SolomonDarkModLoader/src/lua_engine_spell_cast_filters.cpp",
        "spell cast filters skipped because the Lua engine is busy",
        "fail-open reentrancy",
    ),
    (
        "SolomonDarkModLoader/src/lua_engine.cpp",
        '"events.filters.spell_cast"',
        "runtime capability",
    ),
    (
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "player_cast_hooks_effect_and_dispatch.inl",
        "!ApplyLocalPlayerPrimarySpellFilter(actor_address, skill_id)",
        "always-installed primary dispatcher gate",
    ),
    (
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "player_cast_hooks.inl",
        "mouse_edge_serial == edge_serial",
        "one decision per press",
    ),
    (
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "player_cast_hooks.inl",
        "TryResolveNativePrimarySelectionFromLiveProgression",
        "pure-primary selected skill resolution",
    ),
    (
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "player_cast_hooks.inl",
        "g_remote_secondary_spell_dispatch_depth == 0",
        "secondary remote-replay exclusion",
    ),
    (
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/"
        "pending_cast_preparation.inl",
        "!IsNativeRemoteParticipantBinding(binding)",
        "bot owner gate",
    ),
    (
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/"
        "pending_cast_preparation.inl",
        "return true;",
        "canceled request retirement",
    ),
    (
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "lua_spell_cast_filter.inl",
        "RetireCanceledOwnerBotSpellCast",
        "canceled owner-bot retirement helper",
    ),
    (
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "lua_spell_cast_filter.inl",
        "IsUsableSpellCastAimTarget",
        "native aim payload validation",
    ),
    (
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "lua_spell_cast_filter.inl",
        "kActorPrimaryActionLatchE4Offset",
        "primary action latch retirement",
    ),
    (
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "lua_spell_cast_filter.inl",
        "kActorPostGateActiveByteOffset",
        "post-gate retirement",
    ),
    (
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "lua_spell_cast_filter.inl",
        "ResetStandaloneWizardControlBrain(actor_address)",
        "control-brain retirement",
    ),
    (
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "lua_spell_cast_filter.inl",
        "multiplayer::FaceBotTarget(binding->bot_id, 0, false, 0.0f)",
        "cast-facing override retirement",
    ),
    (
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "lua_spell_cast_filter.inl",
        "suppress_next_stock_tick_after_spell_filter_cancel = true",
        "canceled stock-tick barrier arm",
    ),
    (
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/actor_tick/"
        "player_actor_tick_hook.inl",
        "if (binding->suppress_next_stock_tick_after_spell_filter_cancel)",
        "canceled stock-tick barrier consume",
    ),
    (
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/actor_tick/"
        "player_actor_tick_hook.inl",
        "!ApplyLocalPlayerPrimarySpellFilter(actor_address, skill_id)",
        "local primary pre-stock-tick gate",
    ),
    (
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/actor_tick/"
        "player_actor_tick_hook.inl",
        "if (cast_intent_masked)",
        "local primary input restoration",
    ),
    (
        "SolomonDarkModLoader/SolomonDarkModLoader.vcxproj",
        'ClCompile Include="src\\lua_engine_spell_cast_filters.cpp"',
        "project source membership",
    ),
    (
        "docs/lua-spell-cast-filter.md",
        'sd.events.filter("spell.casting", handler)',
        "public API documentation",
    ),
    (
        "mods/lua_spell_cast_filter_lab/manifest.json",
        '"events.filters.spell_cast"',
        "sample capability declaration",
    ),
    (
        "mods/lua_spell_cast_filter_lab/scripts/main.lua",
        'sd.events.filter("spell.casting"',
        "sample registration",
    ),
    (
        "tools/verify_lua_spell_cast_filters.py",
        '"native_fireball_observed": native_fireball_observed',
        "live cancel/allow acceptance verifier",
    ),
    (
        "tools/verify_lua_spell_cast_filters.py",
        "local_acceptance = _run_local_acceptance(",
        "live local-player acceptance verifier",
    ),
)


def main() -> int:
    failures: list[dict[str, str]] = []
    for relative_path, snippet, label in REQUIRED_SNIPPETS:
        path = ROOT / relative_path
        if not path.is_file():
            failures.append(
                {"label": label, "path": relative_path, "error": "missing file"}
            )
            continue
        text = path.read_text(encoding="utf-8")
        if snippet not in text:
            failures.append(
                {
                    "label": label,
                    "path": relative_path,
                    "error": f"missing snippet: {snippet}",
                }
            )

    result = {
        "ok": not failures,
        "checks": len(REQUIRED_SNIPPETS),
        "failures": failures,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
