"""Closure contract for the implemented Lua seam roadmap and exact parity policy."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_roadmap_is_closed_under_exact_mod_parity() -> str:
    roadmap = _read("docs/lua-seam-roadmap.md")
    spell_sample = _read("mods/lua_spells_registry_lab/scripts/main.lua")
    compatibility = _read(
        "SolomonDarkModLauncher/src/Staging/MultiplayerCompatibilityMaterializer.cs"
    )
    hasher = _read("SolomonDarkModLauncher/src/Mods/ModContentHasher.cs")
    steam_handshake = _read(
        "SolomonDarkModLoader/src/multiplayer_steam_session/"
        "lobby_event_handlers.inl"
    )
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    launcher_tests = _read("tests/launcher-contracts/Program.cs")

    for token in (
        "Status: numbered seam roadmap implemented",
        "No executable Lua seam gaps remain in this document.",
        "Exact mod parity handshake",
        "Presentation-only divergence is not accepted",
        "Resolved policy: exact multiplayer parity",
        "Peers may not run different presentation-only mods",
        "## 5. Completed build order",
        "## 6. Open research and distribution questions",
        "**Author DX**",
        "**12. `sd.waves`",
    ):
        assert token in roadmap, f"roadmap closure lacks: {token}"
    for stale in (
        "Authored UI remains incomplete",
        "Presentation parity policy remains incomplete",
        "does not yet render a player-facing catalog chooser",
        "raw `io.*` persistence is technically possible today",
    ):
        assert stale not in roadmap, f"roadmap retained stale gap: {stale}"

    for token in (
        'id = "spell_picker"',
        "sd.ui.create_button",
        "sd.spells.select(spell.id, 1)",
        'sd.spells.clear_selection("secondary", 1)',
    ):
        assert token in spell_sample, f"authored spell picker lacks: {token}"

    _require_in_order(
        compatibility,
        "enabledMods",
        ".OrderBy(mod => mod.Manifest.Id",
        ".Select(BuildModIdentity)",
        "SHA256.HashData(canonicalBytes)",
    )
    assert "ModContentHasher.HashDirectory(mod.RootPath)" in compatibility
    for token in (
        'Directory.EnumerateFiles(rootPath, "*", SearchOption.AllDirectories)',
        "OrderBy(file => file.RelativePath, StringComparer.Ordinal)",
    ):
        assert token in hasher, f"exact directory identity lacks: {token}"
    _require_in_order(
        steam_handshake,
        "std::memcmp(",
        "SessionHelloResultCode::ManifestMismatch",
        "if (result == SessionHelloResultCode::Accepted)",
    )

    for unsafe_global in (
        '"debug"',
        '"dofile"',
        '"io"',
        '"loadfile"',
        '"os"',
        '"package"',
        '"require"',
    ):
        assert unsafe_global in engine, f"Lua sandbox does not remove: {unsafe_global}"

    for token in (
        '"strict multiplayer mod parity"',
        "TestStrictMultiplayerModParityAsync",
        "presentation-intended mod content did not change exact session parity",
        "unchanged exact mod set produced a different session fingerprint",
    ):
        assert token in launcher_tests, f"exact parity launcher coverage lacks: {token}"

    return (
        "all numbered Lua seams are implemented, authored spell selection is composed "
        "through native UI, and every enabled mod remains under one exact handshake"
    )
