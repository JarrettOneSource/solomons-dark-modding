#!/usr/bin/env python3
"""Regression contracts for Lua entry scripts beyond legacy MAX_PATH."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LuaLongPathContractTests(unittest.TestCase):
    def test_initial_load_and_hot_reload_use_the_wide_path_loader(self) -> None:
        engine = (
            ROOT / "SolomonDarkModLoader" / "src" / "lua_engine.cpp"
        ).read_text(encoding="utf-8")
        hot_reload = (
            ROOT / "SolomonDarkModLoader" / "src" / "lua_hot_reload.cpp"
        ).read_text(encoding="utf-8")

        for source in (engine, hot_reload):
            self.assertIn("LoadLuaSourceFile(", source)
            self.assertNotIn("luaL_loadfile", source)

    def test_wide_path_loader_preserves_lua_file_semantics(self) -> None:
        source = (
            ROOT / "SolomonDarkModLoader" / "src" / "lua_source_loader.cpp"
        ).read_text(encoding="utf-8")

        for token in (
            r'LR"(\\?\)"',
            r'LR"(\\?\UNC\)"',
            "CreateFileW(",
            "GetFileSizeEx(",
            "ReadFile(",
            "FILE_SHARE_DELETE",
            "luaL_loadbufferx(",
            "0xEF",
            "bytes[offset] == '#'",
        ):
            with self.subTest(token=token):
                self.assertIn(token, source)

    def test_native_project_builds_the_long_path_loader(self) -> None:
        project = (
            ROOT
            / "SolomonDarkModLoader"
            / "SolomonDarkModLoader.vcxproj"
        ).read_text(encoding="utf-8")
        self.assertIn(
            r'<ClInclude Include="src\lua_source_loader.h" />',
            project,
        )
        self.assertIn(
            r'<ClCompile Include="src\lua_source_loader.cpp" />',
            project,
        )


if __name__ == "__main__":
    unittest.main()
