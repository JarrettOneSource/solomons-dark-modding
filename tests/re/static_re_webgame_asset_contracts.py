"""Static contracts for the P0 native web asset pipeline."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from static_re_contract_support import (
    ROOT,
    StaticReTestFailure,
    assert_recorded_hash_matches_file,
)


FIXTURE_PATH = ROOT / "webgame/assets/fixtures/asset-manifest-goldens.json"
SCHEMA_PATH = ROOT / "webgame/assets/asset-manifest.schema.json"
README_PATH = ROOT / "webgame/assets/README.md"
PACKAGE_PATH = ROOT / "webgame/package.json"
LOCK_PATH = ROOT / "webgame/package-lock.json"
TSCONFIG_PATH = ROOT / "webgame/tsconfig.json"
FLOORS_PATH = ROOT / "webgame/quality-floors.json"
CI_PATH = ROOT / ".github/workflows/lua-authoring-contracts.yml"
INVENTORY_PATH = ROOT / "docs/reverse-engineering/native-content-inventory.json"
SCENE_GOLDEN_PATH = ROOT / "tests/fixtures/webgame/scene-composition-goldens.json"
MENU_GOLDEN_PATH = ROOT / "tests/fixtures/webgame/menu-goldens.json"

EXPECTED_COMMITTED_HASH_PATHS = {
    "SolomonDarkModLoader/src/native_scene_capture/generated_atlas_spans.inl",
    "assets/loading/Wizards_dire_BG.png",
    "docs/reverse-engineering/native-asset-object-map.json",
    "docs/reverse-engineering/native-content-inventory.json",
    "tests/fixtures/webgame/menu-goldens.json",
    "tests/fixtures/webgame/scene-composition-goldens.json",
    "webgame/assets/asset-manifest.schema.json",
}
EXPECTED_OUTPUT_TREE_SHA256 = (
    "3abd761d4047540d32bcf9b6f7a4c87404e0ac84417db2c708dbf346aa6409ea"
)
EXPECTED_MANIFEST_SHA256 = (
    "11e3d2041abb5117228064e73fcd02b9beb3b40dfeed735eafb7133ffd0c5fa3"
)
EXPECTED_FIXTURE_SHA256 = (
    "df6db22e0f549f6653c0f55dccb1b9264e10b1052f9fab0ab7cba77b834dbde2"
)
EXPECTED_COUNTS = {
    "atlasCount": 41,
    "bundleAtlasCount": 28,
    "looseAtlasCount": 13,
    "spriteCount": 10511,
    "aliasCount": 718,
    "fontGroupCount": 10,
}
EXPECTED_EMITTED_BYTES = {
    "atlases": 42744038,
    "boneyards": 5783538,
    "waves": 428544,
    "recipes": 52423,
    "total": 49008543,
}
EXPECTED_PACKS = {
    "boneyards": (
        "packs/boneyards.json",
        5783538,
        "ef3480941917d1337d943d5e016f448f1989575f6265327b524041c91722edda",
        4,
    ),
    "recipes": (
        "packs/recipes.json",
        52423,
        "87757abfa262a20baa2f29ca17675e2cfc593f249efe6858d58d4c60f7a01b58",
        31,
    ),
    "waves": (
        "packs/waves.json",
        428544,
        "fba1a0c2f68894d38914b1daf17fd5593b018fefe19309443b58c9aebfd118bb",
        42,
    ),
}


def _read_text(path: Path, consequence: str) -> str:
    if not path.is_file():
        raise StaticReTestFailure(consequence)
    return path.read_text(encoding="utf-8")


def _load_json(path: Path, consequence: str) -> dict[str, Any]:
    try:
        value = json.loads(_read_text(path, consequence))
    except json.JSONDecodeError as exc:
        raise StaticReTestFailure(f"{consequence}: {exc}") from exc
    if not isinstance(value, dict):
        raise StaticReTestFailure(consequence)
    return value


def _mapping(value: object, consequence: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StaticReTestFailure(consequence)
    return value


def _list(value: object, consequence: str) -> list[Any]:
    if not isinstance(value, list):
        raise StaticReTestFailure(consequence)
    return value


def _sha256(value: object, consequence: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise StaticReTestFailure(consequence)
    return value


def _walk(value: object) -> Iterator[Mapping[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _string_field_set(value: object, field: str) -> set[str]:
    return {
        item[field]
        for item in _walk(value)
        if isinstance(item.get(field), str) and item[field]
    }


def _scene_sprite_ids(golden: dict[str, Any]) -> set[str]:
    captures = _list(
        golden.get("captures"),
        "scene golden no longer has live captures for asset resolution",
    )
    if not captures:
        raise StaticReTestFailure(
            "scene golden has no live draw content for the asset resolver to check"
        )
    ids: set[str] = set()
    for item in _walk(captures):
        sprite = item.get("sprite")
        if isinstance(sprite, dict) and isinstance(sprite.get("id"), str):
            ids.add(sprite["id"])
    ids.update(_string_field_set(golden.get("cross_capture_observations"), "sprite_id"))
    if "DeadHawg.12" not in ids or "native.framebuffer-clear" not in ids:
        raise StaticReTestFailure(
            "scene asset sweep missed the named atlas and special-draw witnesses"
        )
    if len(ids) != 378:
        raise StaticReTestFailure(
            "scene asset sweep no longer reaches all 378 native sprite identifiers"
        )
    return ids


def _menu_ids(golden: dict[str, Any]) -> tuple[set[str], set[str]]:
    layouts = _list(
        golden.get("layouts"),
        "menu golden no longer has layouts for asset resolution",
    )
    if not layouts:
        raise StaticReTestFailure(
            "menu golden has no layout content for the asset resolver to check"
        )
    art_ids = _string_field_set(layouts, "art_id")
    font_ids = _string_field_set(layouts, "font_id")
    if "Wizards_dire_BG" not in art_ids or "Title.0" not in art_ids:
        raise StaticReTestFailure(
            "menu asset sweep missed the named loading and title art witnesses"
        )
    if "Fonts.93-184" not in font_ids or "Segoe UI" not in font_ids:
        raise StaticReTestFailure(
            "menu asset sweep missed the named native and system font witnesses"
        )
    if len(art_ids) != 104 or len(font_ids) != 4:
        raise StaticReTestFailure(
            "menu asset sweep no longer reaches all 104 art and four font identifiers"
        )
    return art_ids, font_ids


def test_webgame_asset_manifest_schema_and_provenance_are_pinned() -> str:
    fixture = _load_json(
        FIXTURE_PATH,
        "asset manifest fixture is absent or not reviewable JSON",
    )
    schema = _load_json(
        SCHEMA_PATH,
        "renderer asset manifest schema is absent or not reviewable JSON",
    )
    if fixture.get("schema") != "solomon-dark-web-asset-manifest-goldens-v1":
        raise StaticReTestFailure(
            "asset manifest fixture no longer has its reviewable golden schema"
        )
    if fixture.get("manifestSchema") != "solomon-dark-web-asset-manifest-v1":
        raise StaticReTestFailure(
            "asset manifest fixture no longer names the v1 renderer schema"
        )
    properties = _mapping(
        schema.get("properties"),
        "renderer manifest schema no longer declares its top-level lookup fields",
    )
    schema_property = _mapping(
        properties.get("schema"),
        "renderer manifest schema no longer pins a version field",
    )
    native_id_property = _mapping(
        properties.get("nativeIdFormat"),
        "renderer manifest schema no longer pins native sprite identifiers",
    )
    if schema_property.get("const") != fixture["manifestSchema"]:
        raise StaticReTestFailure(
            "renderer schema and committed manifest fixture disagree on their version"
        )
    if native_id_property.get("const") != "<Atlas>.<record-index>":
        raise StaticReTestFailure(
            "renderer lookup can no longer address native atlas record identifiers"
        )
    definitions = _mapping(
        schema.get("definitions"),
        "renderer manifest schema no longer defines reusable record contracts",
    )
    entry = _mapping(
        definitions.get("entry"),
        "renderer manifest schema no longer defines sprite entries",
    )
    required_entry_fields = {
        "kind",
        "atlas",
        "rect",
        "pivot",
        "logicalSize",
        "rotated",
        "points",
        "provenance",
    }
    if set(_list(entry.get("required"), "sprite entries no longer require renderer fields")) != required_entry_fields:
        raise StaticReTestFailure(
            "sprite entries no longer require atlas, rect, pivot, logical size, points, and provenance"
        )
    record_provenance = _mapping(
        definitions.get("recordProvenance"),
        "renderer manifest schema no longer defines record provenance",
    )
    required_provenance = {
        "sourceBundleFilename",
        "recordIndex",
        "sourceBytesSha256",
        "sourceOffset",
        "sourceLength",
    }
    if set(_list(record_provenance.get("required"), "record provenance has no required fields")) != required_provenance:
        raise StaticReTestFailure(
            "sprite provenance no longer requires source filename, record, bytes hash, offset, and length"
        )
    packs = _mapping(properties.get("packs"), "renderer manifest no longer declares data packs")
    if set(_list(packs.get("required"), "renderer data packs are no longer required")) != {
        "boneyards",
        "recipes",
        "waves",
    }:
        raise StaticReTestFailure(
            "renderer manifest no longer requires boneyard, recipe, and wave packs together"
        )

    recorded_hashes = _mapping(
        fixture.get("committedSourceHashes"),
        "manifest fixture no longer records hashes for its committed inputs",
    )
    if set(recorded_hashes) != EXPECTED_COMMITTED_HASH_PATHS:
        raise StaticReTestFailure(
            "manifest fixture no longer names exactly its seven committed source inputs"
        )
    if "tests/fixtures/webgame/scene-composition-goldens.json" not in recorded_hashes:
        raise StaticReTestFailure(
            "manifest provenance lost the scene-composition golden witness"
        )
    for relative_path in sorted(EXPECTED_COMMITTED_HASH_PATHS):
        assert_recorded_hash_matches_file(
            recorded_hashes.get(relative_path, ""),
            ROOT / relative_path,
            f"asset manifest committed source {relative_path}",
        )

    readme = _read_text(
        README_PATH,
        "asset build contract is undocumented for renderer consumers",
    )
    fixture_match = re.search(
        r"`webgame/assets/fixtures/asset-manifest-goldens\.json` SHA-256 is\s*"
        r"`([0-9a-f]{64})`\.",
        readme,
    )
    if fixture_match is None:
        raise StaticReTestFailure(
            "asset documentation no longer records the committed manifest fixture hash"
        )
    if fixture_match.group(1) != EXPECTED_FIXTURE_SHA256:
        raise StaticReTestFailure(
            "asset documentation no longer pins the reviewed manifest fixture revision"
        )
    assert_recorded_hash_matches_file(
        fixture_match.group(1), FIXTURE_PATH, "documented asset manifest fixture"
    )
    return "renderer schema requires native IDs, geometry, three packs, and byte-level provenance; all eight committed hashes match"


def test_webgame_asset_double_build_and_weight_report_are_pinned() -> str:
    fixture = _load_json(
        FIXTURE_PATH,
        "asset manifest fixture is absent or not reviewable JSON",
    )
    determinism = _mapping(
        fixture.get("determinism"),
        "asset fixture no longer records the double-build result",
    )
    first = _sha256(
        determinism.get("firstOutputTreeSha256"),
        "first asset build no longer records a complete tree hash",
    )
    second = _sha256(
        determinism.get("secondOutputTreeSha256"),
        "second asset build no longer records a complete tree hash",
    )
    if first != second:
        raise StaticReTestFailure(
            "double-build output tree hashes diverge, so asset emission is not deterministic"
        )
    if first != EXPECTED_OUTPUT_TREE_SHA256:
        raise StaticReTestFailure(
            "deterministic asset output tree no longer matches the reviewed production build"
        )
    output_files = _mapping(
        determinism.get("outputFiles"),
        "double-build proof no longer inventories emitted files",
    )
    if determinism.get("fileCount") != 46 or len(output_files) != 46:
        raise StaticReTestFailure(
            "double-build proof no longer compares all 46 emitted files"
        )
    for witness in (
        "asset-manifest.json",
        "atlases/BadGuys.png",
        "atlases/loading/Wizards_dire_BG.png",
        "packs/boneyards.json",
        "packs/recipes.json",
        "packs/waves.json",
    ):
        if witness not in output_files:
            raise StaticReTestFailure(
                f"double-build inventory no longer checks required artifact {witness}"
            )
    for filename, descriptor_value in output_files.items():
        descriptor = _mapping(
            descriptor_value,
            f"double-build inventory no longer describes emitted file {filename}",
        )
        if not isinstance(descriptor.get("bytes"), int) or descriptor["bytes"] <= 0:
            raise StaticReTestFailure(
                f"double-build inventory no longer pins positive byte weight for {filename}"
            )
        _sha256(
            descriptor.get("sha256"),
            f"double-build inventory no longer pins a full hash for {filename}",
        )
    manifest_output = _mapping(
        output_files["asset-manifest.json"],
        "double-build inventory lost the renderer manifest descriptor",
    )
    if (
        fixture.get("manifestSha256") != EXPECTED_MANIFEST_SHA256
        or manifest_output.get("sha256") != EXPECTED_MANIFEST_SHA256
    ):
        raise StaticReTestFailure(
            "fixture and output inventory no longer agree on the renderer manifest hash"
        )

    emitted = _mapping(
        fixture.get("emittedBytes"),
        "asset fixture no longer carries the static-hosting weight report",
    )
    if emitted != EXPECTED_EMITTED_BYTES:
        raise StaticReTestFailure(
            "asset weight report no longer pins atlas, boneyard, wave, recipe, and total bytes"
        )
    pack_descriptors = _mapping(
        fixture.get("packDescriptors"),
        "asset fixture no longer describes every decoded data pack",
    )
    if set(pack_descriptors) != set(EXPECTED_PACKS):
        raise StaticReTestFailure(
            "asset fixture no longer describes boneyard, recipe, and wave packs exactly once"
        )
    for category, (filename, byte_count, sha, entry_count) in EXPECTED_PACKS.items():
        descriptor = _mapping(
            pack_descriptors[category],
            f"asset fixture no longer describes the {category} pack",
        )
        expected_descriptor = {
            "file": filename,
            "bytes": byte_count,
            "sha256": sha,
            "entryCount": entry_count,
        }
        if descriptor != expected_descriptor:
            raise StaticReTestFailure(
                f"{category} pack no longer has its reviewed hash, weight, and entry count"
            )
        output_descriptor = _mapping(
            output_files[filename],
            f"double-build inventory lost the {category} pack",
        )
        if output_descriptor != {"bytes": byte_count, "sha256": sha}:
            raise StaticReTestFailure(
                f"{category} pack descriptor disagrees with the double-build inventory"
            )
    if fixture.get("ignoredNativeFlagTokens") != ["FLAG_IGNITE", "FLAG_IMMORTALIZE"]:
        raise StaticReTestFailure(
            "wave pack no longer confines the reviewed native log-and-ignore exception to two tokens"
        )
    return "two 46-file builds share the reviewed tree hash; 49,008,543 asset bytes and all three pack descriptors are pinned"


def test_webgame_asset_fixture_covers_native_families_and_golden_references() -> str:
    fixture = _load_json(
        FIXTURE_PATH,
        "asset manifest fixture is absent or not reviewable JSON",
    )
    if fixture.get("counts") != EXPECTED_COUNTS:
        raise StaticReTestFailure(
            "asset manifest counts no longer pin all native atlases, sprites, aliases, and font groups"
        )
    atlases = _list(
        fixture.get("atlases"),
        "asset fixture no longer carries per-atlas dimensions and hashes",
    )
    if len(atlases) != 41:
        raise StaticReTestFailure(
            "asset fixture no longer carries dimensions and hashes for all 41 atlases"
        )
    atlas_by_id: dict[str, dict[str, Any]] = {}
    for index, atlas_value in enumerate(atlases):
        atlas = _mapping(
            atlas_value,
            f"asset fixture atlas {index} is no longer a descriptor",
        )
        atlas_id = atlas.get("id")
        if not isinstance(atlas_id, str) or not atlas_id:
            raise StaticReTestFailure(
                f"asset fixture atlas {index} no longer has a renderer lookup id"
            )
        if atlas_id in atlas_by_id:
            raise StaticReTestFailure(
                f"renderer atlas lookup is ambiguous because {atlas_id} appears twice"
            )
        if not isinstance(atlas.get("width"), int) or atlas["width"] <= 0:
            raise StaticReTestFailure(f"atlas {atlas_id} no longer pins a positive width")
        if not isinstance(atlas.get("height"), int) or atlas["height"] <= 0:
            raise StaticReTestFailure(f"atlas {atlas_id} no longer pins a positive height")
        _sha256(atlas.get("sha256"), f"atlas {atlas_id} no longer pins its bytes")
        atlas_by_id[atlas_id] = atlas
    if "DeadHawg" not in atlas_by_id or "loading:Wizards_dire_BG" not in atlas_by_id:
        raise StaticReTestFailure(
            "per-atlas fixture sweep missed the native gameplay and loading-art witnesses"
        )

    inventory = _load_json(
        INVENTORY_PATH,
        "native content inventory is absent or not reviewable JSON",
    )
    inventory_atlases = _list(
        inventory.get("atlases"),
        "native content inventory no longer enumerates bundle families",
    )
    if len(inventory_atlases) != 28:
        raise StaticReTestFailure(
            "native bundle-family ground truth no longer contains all 28 atlases"
        )
    native_names = {
        atlas.get("name")
        for atlas in inventory_atlases
        if isinstance(atlas, dict) and isinstance(atlas.get("name"), str)
    }
    if len(native_names) != 28 or "BadGuys" not in native_names or "Unholy" not in native_names:
        raise StaticReTestFailure(
            "native bundle-family ground truth is missing named first/last witnesses or is ambiguous"
        )
    representatives = _mapping(
        fixture.get("bundleRepresentatives"),
        "asset fixture no longer selects one record from every native bundle family",
    )
    if set(representatives) != native_names:
        raise StaticReTestFailure(
            "asset fixture bundle families no longer match the native content inventory"
        )
    selected = _mapping(
        fixture.get("selected"),
        "asset fixture no longer carries selected renderer lookup records",
    )
    entry_hashes = _mapping(
        selected.get("entryHashes"),
        "asset fixture no longer carries selected per-entry hashes",
    )
    if len(entry_hashes) != 499 or "DeadHawg.12" not in entry_hashes:
        raise StaticReTestFailure(
            "asset fixture no longer pins all 499 representative and golden-referenced entries"
        )
    for family in sorted(native_names):
        expected_id = f"{family}.0"
        if representatives.get(family) != expected_id or expected_id not in entry_hashes:
            raise StaticReTestFailure(
                f"native bundle family {family} no longer has a hashed record-zero representative"
            )
    for entry_id, recorded_hash in entry_hashes.items():
        _sha256(
            recorded_hash,
            f"selected native entry {entry_id} no longer has a complete record hash",
        )

    scene = _load_json(
        SCENE_GOLDEN_PATH,
        "scene-composition golden is absent or not reviewable JSON",
    )
    menu = _load_json(
        MENU_GOLDEN_PATH,
        "menu golden is absent or not reviewable JSON",
    )
    scene_ids = _scene_sprite_ids(scene)
    menu_art_ids, menu_font_ids = _menu_ids(menu)
    references = _mapping(
        fixture.get("references"),
        "asset fixture no longer records the landed golden references",
    )
    expected_reference_lists = {
        "sceneSpriteIds": sorted(scene_ids),
        "menuArtIds": sorted(menu_art_ids),
        "menuFontIds": sorted(menu_font_ids),
    }
    for field, expected_ids in expected_reference_lists.items():
        if references.get(field) != expected_ids:
            raise StaticReTestFailure(
                f"asset fixture {field} no longer matches its landed native golden source"
            )
    if references.get("unresolved") != []:
        raise StaticReTestFailure(
            "asset manifest fixture reports unresolved scene or menu references"
        )
    all_ids = scene_ids | menu_art_ids | menu_font_ids
    if len(all_ids) != 485:
        raise StaticReTestFailure(
            "landed scene/menu sweep no longer yields the reviewed 485 unique renderer lookups"
        )
    resolutions = _mapping(
        references.get("resolutions"),
        "asset fixture no longer records renderer resolutions for golden references",
    )
    missing = sorted(all_ids - set(resolutions))
    if missing:
        raise StaticReTestFailure(
            f"asset manifest leaves golden reference unresolved: {missing[0]}"
        )
    unexpected = sorted(set(resolutions) - all_ids)
    if unexpected:
        raise StaticReTestFailure(
            f"asset fixture invents a resolution outside landed goldens: {unexpected[0]}"
        )
    alias_mappings = _mapping(
        selected.get("aliasMappings"),
        "asset fixture no longer carries native font-record aliases",
    )
    font_hashes = _mapping(
        selected.get("fontGroupHashes"),
        "asset fixture no longer carries native font-group hashes",
    )
    special_hashes = _mapping(
        selected.get("specialDrawHashes"),
        "asset fixture no longer carries special-draw hashes",
    )
    if "Fonts.93-184@0x35E4" not in alias_mappings:
        raise StaticReTestFailure("native font alias sweep lost its address-backed witness")
    if set(font_hashes) != {"Fonts.93-184", "Fonts.216-307", "Fonts.308-349"}:
        raise StaticReTestFailure("native menu font groups no longer resolve through the manifest")
    if set(special_hashes) != {
        "Segoe UI",
        "native.framebuffer-clear",
        "native.textured-quad@0x41474C",
    }:
        raise StaticReTestFailure("non-atlas native draws no longer resolve through the manifest")
    for asset_id in sorted(all_ids):
        resolution = _mapping(
            resolutions[asset_id],
            f"golden asset reference has no typed resolution: {asset_id}",
        )
        kind = resolution.get("kind")
        if kind == "entry":
            resolved = asset_id in entry_hashes
        elif kind == "alias":
            target = alias_mappings.get(asset_id)
            resolved = resolution.get("target") == target and target in entry_hashes
        elif kind == "font-group":
            resolved = asset_id in font_hashes
        elif kind == "special-draw":
            resolved = asset_id in special_hashes
        else:
            resolved = False
        if not resolved:
            raise StaticReTestFailure(
                f"asset manifest leaves golden reference unresolved: {asset_id}"
            )
    return "all 28 native bundle families have hashed representatives and all 485 landed scene/menu lookups resolve"


def test_webgame_workspace_battery_is_strict_ratcheted_and_ci_wired() -> str:
    package = _load_json(
        PACKAGE_PATH,
        "webgame npm workspace package is absent or not reviewable JSON",
    )
    lock = _load_json(
        LOCK_PATH,
        "webgame dependency lock is absent or not reviewable JSON",
    )
    tsconfig = _load_json(
        TSCONFIG_PATH,
        "webgame TypeScript configuration is absent or not reviewable JSON",
    )
    floors = _load_json(
        FLOORS_PATH,
        "webgame quality ratchet is absent or not reviewable JSON",
    )
    if package.get("name") != "@solomon-dark/webgame" or package.get("private") is not True:
        raise StaticReTestFailure(
            "top-level webgame is no longer an isolated private npm workspace"
        )
    scripts = _mapping(package.get("scripts"), "webgame workspace no longer declares its battery")
    expected_scripts = {
        "assets:build": "tsx assets/cli.ts",
        "assets:goldens": "tsx assets/generate-goldens.ts",
        "build": "vite build",
        "capture:evidence": "tsx scripts/capture-shell.ts",
        "conformance": "tsx conformance/run-layout-replay.ts",
        "controller-traversal": "tsx conformance/run-controller-traversal.ts",
        "dev": "vite",
        "lint": "eslint . --max-warnings 0 && node scripts/check-quality-floor.mjs lint",
        "typecheck": "tsc --noEmit && node scripts/check-quality-floor.mjs typecheck",
        "test": "node scripts/run-unit-tests.mjs",
    }
    if scripts != expected_scripts:
        raise StaticReTestFailure(
            "webgame workspace no longer exposes isolated build, golden, lint, typecheck, and test commands"
        )
    if lock.get("lockfileVersion") != 3:
        raise StaticReTestFailure(
            "webgame dependency installation is no longer locked by npm lockfile v3"
        )
    compiler = _mapping(
        tsconfig.get("compilerOptions"),
        "webgame TypeScript configuration no longer declares compiler options",
    )
    strict_options = {
        "strict": True,
        "noUncheckedIndexedAccess": True,
        "exactOptionalPropertyTypes": True,
        "noImplicitOverride": True,
        "noFallthroughCasesInSwitch": True,
        "noImplicitReturns": True,
        "noUnusedLocals": True,
        "noUnusedParameters": True,
        "useUnknownInCatchVariables": True,
        "verbatimModuleSyntax": True,
        "forceConsistentCasingInFileNames": True,
        "noEmit": True,
    }
    missing_strict = sorted(
        name for name, expected in strict_options.items() if compiler.get(name) is not expected
    )
    if missing_strict:
        raise StaticReTestFailure(
            "webgame TypeScript strictness lost required option(s): " + ", ".join(missing_strict)
        )
    expected_floors = {
        "lintFiles": 45,
        "typecheckedFiles": 42,
        "unitTestFiles": 12,
        "unitTests": 58,
    }
    if floors != expected_floors:
        raise StaticReTestFailure(
            "webgame lint, typecheck, and unit-test floors no longer match the landed battery"
        )

    workflow = _read_text(CI_PATH, "repository CI workflow is absent")
    ci_steps = (
        (
            r"^      - uses: actions/setup-node@v4\n"
            r"^        with:\n"
            r"^          node-version: \"22\.17\.0\"\n"
            r"^          cache: npm\n"
            r"^          cache-dependency-path: webgame/package-lock\.json$",
            "CI no longer provisions the pinned Node runtime and webgame lockfile cache",
        ),
        (
            r"^      - name: Install webgame workspace\n"
            r"^        run: npm --prefix webgame ci --ignore-scripts$",
            "CI no longer installs the locked webgame workspace without lifecycle scripts",
        ),
        (
            r"^      - name: Lint webgame workspace\n"
            r"^        run: npm --prefix webgame run lint$",
            "CI no longer runs the webgame lint ratchet as an isolated step",
        ),
        (
            r"^      - name: Typecheck webgame workspace\n"
            r"^        run: npm --prefix webgame run typecheck$",
            "CI no longer runs the webgame typecheck ratchet as an isolated step",
        ),
        (
            r"^      - name: Test webgame workspace\n"
            r"^        run: npm --prefix webgame test$",
            "CI no longer runs the webgame unit-test ratchet as an isolated step",
        ),
    )
    for pattern, consequence in ci_steps:
        if re.search(pattern, workflow, flags=re.MULTILINE) is None:
            raise StaticReTestFailure(consequence)
    pillow_step = re.search(
        r"^      - name: Install image test dependency\n"
        r"(?:^        #.*\n)+"
        r"^        run: python -m pip install Pillow==12\.2\.0$",
        workflow,
        flags=re.MULTILINE,
    )
    webgame_test_step = re.search(
        r"^      - name: Test webgame workspace\n"
        r"^        run: npm --prefix webgame test$",
        workflow,
        flags=re.MULTILINE,
    )
    if pillow_step is None:
        raise StaticReTestFailure(
            "CI no longer installs the pinned Pillow runtime needed by the real bundle decoder"
        )
    if webgame_test_step is None or pillow_step.start() > webgame_test_step.start():
        raise StaticReTestFailure(
            "CI runs the real webgame decoder test before installing its Pillow dependency"
        )
    return "strict TypeScript and locked npm tooling run with shell gates at floors 45/42/12/58"
