"""Build-flavor stamp and live-acceptance launcher contracts."""

from __future__ import annotations

from static_re_contract_support import ROOT, StaticReTestFailure, read_text


def _require_tokens(label: str, text: str, tokens: tuple[str, ...]) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise StaticReTestFailure(
            f"{label} is missing: " + ", ".join(missing)
        )


def test_native_loader_build_flavor_stamp_is_explicit_and_logged() -> str:
    loader = read_text(ROOT / "SolomonDarkModLoader/src/mod_loader.cpp")
    initialize = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader/initialize.inl"
    )
    design = read_text(
        ROOT / "docs/design/staged-release-loader-acceptance.md"
    )
    incident_addendum = read_text(
        ROOT / "docs/re/skillfix-discipline-and-concentration-2026-08-02.md"
    )

    _require_tokens(
        "native build-flavor stamp",
        loader,
        (
            "#if defined(NDEBUG)",
            '#define SDMOD_BUILD_FLAVOR "Release"',
            '#define SDMOD_BUILD_FLAVOR "Debug"',
            'extern "C" __declspec(dllexport)',
            "SolomonDarkModLoaderBuildFlavor()",
            'return "SDMOD_BUILD_FLAVOR=" SDMOD_BUILD_FLAVOR;',
        ),
    )
    _require_tokens(
        "loader startup flavor log",
        initialize,
        ('Log("Build flavor: " SDMOD_BUILD_FLAVOR ".");',),
    )
    _require_tokens(
        "Release-loader design note",
        design,
        (
            "SDMOD_BUILD_FLAVOR=Debug",
            "SDMOD_BUILD_FLAVOR=Release",
            "Refusal is the",
        ),
    )
    _require_tokens(
        "incident Release-loader addendum",
        incident_addendum,
        (
            "## Addendum: Release-loader acceptance guard",
            "scripts/Assert-StagedReleaseLoader.ps1",
            "they do not silently",
        ),
    )
    return "the DLL exports one configuration stamp and logs the same flavor"


def test_staged_release_loader_assertion_is_fail_closed() -> str:
    assertion = read_text(
        ROOT / "scripts/Assert-StagedReleaseLoader.ps1"
    )
    _require_tokens(
        "shared staged-loader assertion",
        assertion,
        (
            "function Get-StagedLoaderBuildFlavor",
            "function Assert-StagedReleaseLoader",
            "[System.IO.File]::ReadAllBytes",
            "$bytes[0] -ne 0x4D",
            "$bytes[1] -ne 0x5A",
            '"SDMOD_BUILD_FLAVOR=([A-Za-z]+)\\x00"',
            '$flavors[0] -notin @("Debug", "Release")',
            '$flavor -ne "Release"',
            "Live acceptance requires a Release SolomonDarkModLoader.dll",
            "Build-All.ps1 -Configuration Release",
        ),
    )
    return "the shared assertion rejects missing, ambiguous, invalid, and Debug loaders"


def test_live_acceptance_launchers_require_release_loader() -> str:
    shared_helper = read_text(
        ROOT / "scripts/LocalMultiplayerLauncher.Process.ps1"
    )
    _require_tokens(
        "shared launcher process helper",
        shared_helper,
        (
            'Join-Path $PSScriptRoot "Assert-StagedReleaseLoader.ps1"',
            '$Arguments -contains "launch"',
            '"SolomonDarkModLoader.dll"',
            "Assert-StagedReleaseLoader -Path $loaderPath",
        ),
    )

    direct_launchers = {
        "scripts/Crash-TestHubBotSession.ps1",
        "scripts/Launch-BotPublicationPair.ps1",
        "scripts/Launch-LocalMultiplayerAdditionalClient.ps1",
        "scripts/Launch-LocalMultiplayerPair.ps1",
        "scripts/Launch-LocalSoloSession.ps1",
        "scripts/Launch-RemoteLatencyPeer.ps1",
        "scripts/Launch-TestBotSession.ps1",
        "scripts/Replay-UiSandbox.ps1",
        "scripts/Verify-Workspace.ps1",
    }
    discovered = set()
    for path in sorted((ROOT / "scripts").glob("*.ps1")):
        if path.name == "LocalMultiplayerLauncher.Process.ps1":
            continue
        source = read_text(path)
        if '"launch"' in source and (
            "SolomonDarkModLauncher" in source
            or "Invoke-LauncherWithEnvironment" in source
        ):
            discovered.add(path.relative_to(ROOT).as_posix())
    if discovered != direct_launchers:
        raise StaticReTestFailure(
            "PowerShell live-launch inventory changed without Release-loader "
            "wiring: expected="
            + ",".join(sorted(direct_launchers))
            + " discovered="
            + ",".join(sorted(discovered))
        )

    for relative_path in sorted(direct_launchers):
        source = read_text(ROOT / relative_path)
        _require_tokens(
            relative_path,
            source,
            (
                "Assert-StagedReleaseLoader",
                "SolomonDarkModLoader.dll",
            ),
        )

    windows_ui_worker = read_text(
        ROOT / "scripts/Run-RealFlowWindowsSessionWorker.ps1"
    )
    _require_tokens(
        "real-flow Windows UI launcher",
        windows_ui_worker,
        (
            "Assert-StagedReleaseLoader",
            '"launcher\\SolomonDarkModLoader.dll"',
            'Invoke-UiButton -ProcessId $launcher.Id -Name "Launch Game"',
        ),
    )
    wsl_launcher = read_text(
        ROOT / "scripts/Launch-WslSteamMultiplayerClient.sh"
    )
    _require_tokens(
        "WSL Steam launcher",
        wsl_launcher,
        (
            "Assert-StagedReleaseLoader.ps1",
            '-LoaderPath "$loader_win"',
        ),
    )
    return "all PowerShell, UI-driven, and WSL live-acceptance launch paths refuse non-Release loaders"
