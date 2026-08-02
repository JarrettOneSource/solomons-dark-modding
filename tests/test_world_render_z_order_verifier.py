#!/usr/bin/env python3
"""Regression tests for the native world-render acceptance harness."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_world_render_z_order as verifier  # noqa: E402


class WorldRenderZOrderVerifierTests(unittest.TestCase):
    def test_loot_rows_accepts_the_public_potion_kind_label(self) -> None:
        output = "281612415664129|6|390.0|310.0|25.0|true|287346288\n"

        with mock.patch.object(verifier.sync, "lua", return_value=output) as lua:
            rows = verifier.loot_rows("test-pipe")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["item_slot"], 6)
        self.assertTrue(rows[0]["materialized"])
        self.assertIn('row.kind == "Potion"', lua.call_args.args[1])

    def test_capture_projection_uses_the_stock_region_camera(self) -> None:
        projected = "".join(
            (
                "drop.x=310\n",
                "drop.y=418\n",
                "drop.visible=true\n",
                "drop.width=1600\n",
                "drop.height=900\n",
            )
        )

        with mock.patch.object(
            verifier,
            "parse_values",
            return_value=verifier.sync.parse_key_values(projected),
        ) as parse:
            result = verifier.projections("test-pipe", {"drop": (230, 310)})

        self.assertEqual(result["drop"]["x"], 310)
        code = parse.call_args.args[1]
        self.assertIn("sd.camera.get_state()", code)
        self.assertIn("(x - camera.origin_x) * camera.scale", code)
        self.assertNotIn("sd.draw.world_to_screen", code)

    def test_potion_template_ignores_same_color_actor_pixels_off_mask(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference_path = root / "reference.png"
            control_path = root / "control.png"
            occluded_path = root / "occluded.png"
            reference = Image.new("RGB", (80, 80), (20, 20, 20))
            for y in range(32, 48):
                for x in range(35, 45):
                    reference.putpixel((x, y), (180, 40, 35))
            reference.save(reference_path)
            reference.save(control_path)

            occluded = Image.new("RGB", (80, 80), (20, 20, 20))
            for y in range(50, 70):
                for x in range(20, 60):
                    occluded.putpixel((x, y), (220, 30, 25))
            occluded.save(occluded_path)
            point = {"x": 40, "y": 40}

            control = verifier.potion_template_stats(
                reference_path,
                point,
                control_path,
                point,
                color="red",
            )
            actor_front = verifier.potion_template_stats(
                reference_path,
                point,
                occluded_path,
                point,
                color="red",
            )

        self.assertEqual(control["remaining_ratio"], 1.0)
        self.assertEqual(actor_front["remaining_ratio"], 0.0)

    def test_potion_location_calibrates_vertical_capture_offset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            image_path = Path(temporary) / "capture.png"
            image = Image.new("RGB", (120, 120), (20, 20, 20))
            for y in range(25, 35):
                for x in range(55, 65):
                    image.putpixel((x, y), (30, 180, 20))
            image.save(image_path)

            location = verifier.locate_potion_color(
                image_path,
                {"x": 60, "y": 70},
                color="green",
            )

        self.assertEqual(location["matching_pixels"], 100)
        self.assertEqual(location["center_y"], 29.5)
        self.assertEqual(location["bounds"], [55, 25, 64, 34])

    def test_pickup_range_hold_writes_the_stock_derived_field(self) -> None:
        output = "".join(
            (
                "address=287310204\n",
                "previous=2.0\n",
                "wrote=true\n",
                "current=0.01\n",
            )
        )
        with mock.patch.object(
            verifier,
            "parse_values",
            return_value=verifier.sync.parse_key_values(output),
        ) as parse:
            result = verifier.set_local_pickup_range(
                "test-pipe",
                pickup_range=0.01,
            )

        self.assertEqual(result["previous"], "2.0")
        code = parse.call_args.args[1]
        self.assertIn("player.progression_address", code)
        self.assertIn("progression + 0xCC", code)
        self.assertIn("sd.debug.write_float(address, 0.01)", code)

    def test_generic_marker_uses_native_world_marker_api(self) -> None:
        output = "registered=true\nenabled=true\ncapability=true\n"
        with mock.patch.object(
            verifier,
            "parse_values",
            return_value=verifier.sync.parse_key_values(output),
        ) as parse:
            result = verifier.configure_generic_world_marker(
                "test-pipe",
                enabled=True,
                x=10.0,
                y=20.0,
            )

        self.assertEqual(result["enabled"], "true")
        code = parse.call_args.args[1]
        self.assertIn('sd.world.marker("ZRD MARKER"', code)
        self.assertNotIn("sd.draw.world_to_screen", code)

    def test_native_order_relations_use_stock_effective_keys(self) -> None:
        state = {
            "players": {
                "local": {
                    "actor_address": 100,
                    "x": 10.0,
                    "y": 68.0,
                    "sort_bias": 0.0,
                },
                "remote": {
                    "actor_address": 200,
                    "x": 30.0,
                    "y": 68.0,
                    "sort_bias": 0.0,
                },
            },
            "drops": {
                "stock": {
                    "actor_address": 300,
                    "x": 10.0,
                    "y": 100.0,
                    "sort_bias": -25.0,
                },
                "custom": {
                    "actor_address": 400,
                    "x": 30.0,
                    "y": 100.0,
                    "sort_bias": -25.0,
                },
            },
        }
        behind = verifier.verify_native_order_relation(
            state,
            relation="behind",
        )
        self.assertEqual(behind["stock"]["player_effective_key"], 68)
        self.assertEqual(behind["stock"]["drop_effective_key"], 75)

        state["players"]["local"]["y"] = 104.0
        state["players"]["remote"]["y"] = 104.0
        front = verifier.verify_native_order_relation(
            state,
            relation="front",
        )
        self.assertEqual(front["custom"]["relation"], ">")

    def test_native_marker_pixels_require_the_cyan_cross(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            image_path = Path(temporary) / "marker.png"
            image = Image.new("RGB", (80, 80), (20, 20, 20))
            for x in range(30, 51):
                image.putpixel((x, 40), (0, 255, 255))
                image.putpixel((x, 41), (0, 255, 255))
            image.save(image_path)
            result = verifier.verify_native_marker_pixels(
                image_path,
                {"x": 40, "y": 40},
            )
        self.assertGreaterEqual(result["cyan_pixels"], 24)

    def test_loaded_module_proof_uses_the_dll_self_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary) / "runtime"
            launch: dict[str, object] = {"hostProcessId": 101, "clientProcessId": 202}
            process_rows = []
            expected_loader = verifier.sync.path_for_powershell(
                verifier.ROOT / "dist/launcher/SolomonDarkModLoader.dll"
            )
            for role, process_id in (("host", 101), ("client", 202)):
                executable = verifier.sync.path_for_powershell(
                    runtime / f"instances/zrd-{role}/stage/SolomonDark.exe"
                )
                launch[f"{role}ExecutablePath"] = executable
                process_rows.append(
                    {"ProcessId": process_id, "ExecutablePath": executable}
                )
                log = (
                    runtime
                    / f"instances/zrd-{role}/stage/.sdmod/logs/solomondarkmodloader.log"
                )
                log.parent.mkdir(parents=True)
                log.write_text(
                    f"[test] Module path: {expected_loader}\n",
                    encoding="utf-8",
                )

            with mock.patch.object(
                verifier,
                "_powershell_json",
                return_value=process_rows,
            ):
                result = verifier.verify_launched_processes_and_modules(
                    launch,
                    runtime_root=runtime,
                    launcher_path=verifier.ROOT
                    / "dist/launcher/SolomonDarkModLauncher.exe",
                    instance_prefix="zrd",
                    loader_sha256="abc123",
                )

        self.assertEqual(result["host"]["loader_sha256"], "abc123")
        self.assertEqual(
            result["client"]["loader_path_source"],
            "GetModuleFileNameW(module_handle)",
        )

    def test_custom_potion_is_found_and_consumed_in_one_inventory_probe(self) -> None:
        output = "".join(
            (
                "root=287310204\n",
                "item_address=287955120\n",
                "uid=224723052\n",
                "stack=1\n",
                "found=287955120\n",
                "used=true\n",
            )
        )
        with mock.patch.object(
            verifier,
            "parse_values",
            return_value=verifier.sync.parse_key_values(output),
        ) as parse:
            result = verifier.wait_for_and_consume_custom_inventory_item(
                "test-pipe",
                native_subtype=6,
                timeout=1.0,
            )

        self.assertTrue(result["used"])
        self.assertEqual(result["found"], result["item_address"])
        code = parse.call_args.args[1]
        self.assertIn("item.slot == 6", code)
        self.assertIn("item.item_address + 20", code)
        self.assertEqual(verifier.ITEM_UID_OFFSET, 0x14)
        self.assertLess(
            code.index("call_thiscall_u32_ret_u32"),
            code.index("call_thiscall_u32(\n        use"),
        )

    def test_vfx_capture_waits_for_both_native_spellglow_views(self) -> None:
        baseline = {"host": {}, "client": {}}
        first_host = {"host": {"attempt": 1}}
        first_client = {"client": {"attempt": 1}}
        second_host = {"host": {"attempt": 2}}
        pixels = {"host": {"changed_pixels": 80}, "client": {"changed_pixels": 90}}
        with mock.patch.object(
            verifier,
            "capture_phase",
            side_effect=(first_host, first_client, second_host),
        ) as capture, mock.patch.object(
            verifier,
            "analyze_vfx_role_delta",
            side_effect=(
                verifier.sync.VerifyFailure("not visible"),
                pixels["client"],
                pixels["host"],
            ),
        ), mock.patch.object(verifier.time, "sleep"):
            active, analysis = verifier.wait_for_vfx_capture(
                Path("evidence"),
                baseline,
                {"host": "host-pipe", "client": "client-pipe"},
                {
                    "host": {"effect": (1.0, 2.0)},
                    "client": {"effect": (1.0, 2.0)},
                },
                timeout=1.0,
            )

        self.assertIs(active["host"], second_host["host"])
        self.assertIs(active["client"], first_client["client"])
        self.assertEqual(analysis, pixels)
        self.assertEqual(capture.call_count, 3)


if __name__ == "__main__":
    unittest.main()
