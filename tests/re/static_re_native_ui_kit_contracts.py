"""Static contract for the complete native UI building-block catalog."""

from __future__ import annotations

import json
import subprocess
import sys

from static_re_contract_support import ROOT, StaticReTestFailure


CATALOG = ROOT / "docs/reverse-engineering/native-ui-kit-catalog.json"
GENERATOR = ROOT / "tools/build_native_ui_kit_catalog.py"
EXPECTED_ATLASES = {
    "Bonedit": 84,
    "ControlPanel": 116,
    "Controls": 4,
    "Create": 24,
    "Fonts": 627,
    "GameOver": 3,
    "Inventory": 84,
    "LevelPicker": 8,
    "Loader": 5,
    "Skills": 166,
    "Title": 25,
    "UI": 113,
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise StaticReTestFailure(message)


def test_native_ui_kit_catalog_is_complete_and_regenerable() -> str:
    require(CATALOG.is_file(), "native UI kit catalog is absent")
    require(GENERATOR.is_file(), "native UI kit catalog generator is absent")
    try:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StaticReTestFailure(f"native UI kit catalog is unreadable: {exc}") from exc

    require(catalog.get("schema") == "solomon-dark-native-ui-kit-catalog-v1", "native UI kit schema drifted")
    require(
        (catalog.get("source") or {}).get("sha256")
        == "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3",
        "native UI kit lost the retail executable identity",
    )
    atlases = catalog.get("atlases")
    require(isinstance(atlases, list), "native UI kit atlas membership is not a list")
    by_name = {row.get("name"): row for row in atlases if isinstance(row, dict)}
    require(set(by_name) == set(EXPECTED_ATLASES), "native UI kit atlas membership drifted")
    for name, expected_count in EXPECTED_ATLASES.items():
        row = by_name[name]
        records = row.get("records")
        require(row.get("record_count") == expected_count, f"{name} record count drifted")
        require(isinstance(records, list) and len(records) == expected_count, f"{name} record inventory is incomplete")
        require(
            [record.get("record") for record in records if isinstance(record, dict)]
            == list(range(expected_count)),
            f"{name} record inventory is not exact and ordered",
        )
        require(
            row.get("disposition") == "exact-ported"
            and all(record.get("disposition") == "exact-ported" for record in records),
            f"{name} has an undispositioned UI record",
        )

    summary = catalog.get("summary") or {}
    require(summary.get("atlas_count") == 12, "native UI kit no longer covers 12 atlases")
    require(summary.get("record_count") == 1259, "native UI kit no longer covers all 1,259 records")
    wrappers = catalog.get("font_wrappers")
    require(isinstance(wrappers, list) and len(wrappers) == 10, "native UI kit lost a bitmap-font wrapper")
    require(sum(int(row.get("glyph_count", 0)) for row in wrappers) == 718, "native UI kit font glyph census drifted")
    require(all(row.get("disposition") == "exact-ported" for row in wrappers), "native UI font wrapper is undispositioned")

    primitives = catalog.get("primitives")
    require(isinstance(primitives, list) and len(primitives) == 8, "native UI primitive census drifted")
    require(all(row.get("disposition") == "exact-ported" for row in primitives), "native UI primitive is undispositioned")
    consumers = catalog.get("screen_consumers")
    require(isinstance(consumers, list) and len(consumers) == 32, "native UI screen-consumer census drifted")
    require(
        sum(row.get("kind") == "layout" for row in consumers) == 30
        and sum(row.get("kind") == "overlay" for row in consumers) == 1
        and sum(row.get("kind") == "composite" for row in consumers) == 1,
        "native UI screen-consumer kinds drifted",
    )
    require(
        all(str(row.get("disposition", "")).startswith("out-of-system:") for row in consumers),
        "native UI kit silently absorbed a screen state machine",
    )
    require(summary.get("blocked_by_platform_count") == 0, "native UI kit invented a browser blocker")
    require("not-yet-extracted" not in CATALOG.read_text(encoding="utf-8"), "native UI kit contains an unresolved disposition")

    check = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    require(check.returncode == 0, f"native UI kit catalog is stale: {check.stderr or check.stdout}")
    return "12 atlases, 1,259 records, 10 fonts, 8 primitives, and 32 consumers are exact and regenerable"
