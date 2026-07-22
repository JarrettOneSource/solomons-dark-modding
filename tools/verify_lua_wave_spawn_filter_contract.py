#!/usr/bin/env python3
"""Verify the static contract for owner-side Lua wave-spawn filters."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_SNIPPETS = (
    (
        "SolomonDarkModLoader/include/lua_event_filters.h",
        "kLuaWaveSpawningFilterMask",
        "filter registration mask",
    ),
    (
        "SolomonDarkModLoader/src/lua_engine_filters.cpp",
        'filter_name == "wave.spawning"',
        "public filter name",
    ),
    (
        "SolomonDarkModLoader/src/lua_engine_wave_spawn_filters.cpp",
        "ApplyLuaWaveSpawnFilters",
        "ordered Lua dispatcher",
    ),
    (
        "SolomonDarkModLoader/src/lua_engine_wave_spawn_filters.cpp",
        '"count"',
        "count rewrite parser",
    ),
    (
        "SolomonDarkModLoader/src/lua_engine.cpp",
        '"events.filters.wave_spawn"',
        "runtime capability",
    ),
    (
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/wave_spawn_filter.inl",
        "ClaimLuaWaveSpawnFilterInstance",
        "one dispatch per live action",
    ),
    (
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/wave_spawn_filter.inl",
        "FinishLuaWaveSpawnFilterTick",
        "post-tick identity cleanup",
    ),
    (
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/wave_spawn_filter.inl",
        "multiplayer::IsLocalTransportClient()",
        "transport client authority gate",
    ),
    (
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/wave_spawn_filter.inl",
        "RestoreLuaWaveSpawnFilterState(original)",
        "transaction rollback",
    ),
    (
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/wave_spawn_filter.inl",
        "context.count = 0",
        "stock retirement cancellation",
    ),
    (
        "SolomonDarkModLoader/SolomonDarkModLoader.vcxproj",
        'ClCompile Include="src\\lua_engine_wave_spawn_filters.cpp"',
        "project source membership",
    ),
    (
        "docs/lua-wave-spawn-filter.md",
        'sd.events.filter("wave.spawning", handler)',
        "public API documentation",
    ),
    (
        "mods/lua_wave_spawn_filter_lab/manifest.json",
        '"events.filters.wave_spawn"',
        "sample capability declaration",
    ),
    (
        "tests/fixtures/waves/lua_wave_filter_test.txt",
        "SPAWN:2",
        "deterministic live fixture",
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
