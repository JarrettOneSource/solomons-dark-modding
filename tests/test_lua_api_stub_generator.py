#!/usr/bin/env python3
"""Regression tests for the native-registration-derived Lua editor API."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import generate_lua_api_stubs as generator  # noqa: E402


class LuaApiStubGeneratorTests(unittest.TestCase):
    def test_cpp_comments_cannot_add_generated_bindings(self) -> None:
        source = """
        RegisterFunction(state, &LuaActive, "active");
        // RegisterFunction(state, &LuaLineComment, "line_comment");
        const char* url = "https://example.invalid/api";
        /* RegisterFunction(state, &LuaBlockComment, "block_comment"); */
        """
        stripped = generator._strip_cpp_comments(source)
        self.assertIn('RegisterFunction(state, &LuaActive, "active");', stripped)
        self.assertIn('"https://example.invalid/api"', stripped)
        self.assertNotIn("LuaLineComment", stripped)
        self.assertNotIn("LuaBlockComment", stripped)
        self.assertEqual(source.count("\n"), stripped.count("\n"))

    def test_inventory_follows_root_registration_order_and_nested_helpers(self) -> None:
        namespaces = generator.discover_bindings()
        by_name = {namespace.name: namespace for namespace in namespaces}

        self.assertEqual(namespaces[0].name, "runtime")
        self.assertEqual(namespaces[-1].name, "debug")
        self.assertEqual(len(by_name), len(namespaces))
        self.assertIn("create_surface", by_name["ui"].functions)
        self.assertIn("get_progression_book_state", by_name["player"].functions)
        self.assertIn("get_replicated_air_chains", by_name["world"].functions)

    def test_draw_and_hud_preserve_the_native_table_alias(self) -> None:
        by_name = {
            namespace.name: namespace
            for namespace in generator.discover_bindings()
        }
        self.assertEqual(by_name["draw"].table_id, by_name["hud"].table_id)
        self.assertEqual(by_name["draw"].functions, by_name["hud"].functions)

        rendered = generator.render_stub(list(by_name.values()))
        self.assertIn("---@field hud SdDrawApi", rendered)
        self.assertIn("hud = sd_draw,", rendered)
        self.assertIn("draw = sd_draw,", rendered)

    def test_checked_in_stub_is_current(self) -> None:
        rendered = generator.render_stub(generator.discover_bindings())
        self.assertEqual(
            (ROOT / "api" / "lua" / "sd.lua").read_text(encoding="utf-8"),
            rendered,
        )


if __name__ == "__main__":
    unittest.main()
