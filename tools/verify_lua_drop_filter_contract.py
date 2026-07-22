#!/usr/bin/env python3
"""Verify the static owner-side Lua drop-roll filter contract."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_SNIPPETS = (
    (
        "SolomonDarkModLoader/include/lua_event_filters.h",
        "kLuaDropRollingFilterMask = 1u << 3",
        "drop filter mask",
    ),
    (
        "SolomonDarkModLoader/src/lua_engine_filters.cpp",
        'filter_name == "drop.rolling"',
        "drop filter registration",
    ),
    (
        "SolomonDarkModLoader/src/lua_engine_drop_filters.cpp",
        "ApplyLuaDropRollFilters",
        "ordered Lua filter implementation",
    ),
    (
        "SolomonDarkModLoader/src/lua_engine.cpp",
        '"events.filters.drop_roll"',
        "runtime capability",
    ),
    (
        "SolomonDarkModLoader/src/gameplay_seams/state_and_address_bindings.inl",
        '"enemy_drop_selector", kEnemyDropSelector',
        "resolved native seam",
    ),
    (
        "config/binary-layout.ini",
        "enemy_drop_selector=0x0047C070",
        "retail selector address",
    ),
    (
        "SolomonDarkModLoader/src/run_lifecycle/state_and_targets.inl",
        "targets[kHookDropSelector] = {kEnemyDropSelector, 7}",
        "whole-instruction hook target",
    ),
    (
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/drop_roll_filter.inl",
        "multiplayer::IsLocalTransportClient()",
        "transport client authority gate",
    ),
    (
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/drop_roll_filter.inl",
        "RestoreLuaDropRollFilterState(original_filter_context)",
        "native transaction restore",
    ),
    (
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/drop_roll_filter.inl",
        "selectors->fill(kDropForcedSelectorValue)",
        "single-category force policy",
    ),
    (
        "SolomonDarkModLoader/SolomonDarkModLoader.vcxproj",
        'ClCompile Include="src\\lua_engine_drop_filters.cpp"',
        "project source membership",
    ),
    (
        "docs/lua-drop-roll-filter.md",
        "sd.events.filter(\"drop.rolling\", handler)",
        "public API documentation",
    ),
    (
        "mods/lua_drop_roll_filter_lab/manifest.json",
        '"events.filters.drop_roll"',
        "sample capability declaration",
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
