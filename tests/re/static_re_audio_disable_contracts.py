"""Stock audio bootstrap and launch-time disable contracts."""

from __future__ import annotations

import struct
from pathlib import Path

from static_re_contract_support import (
    ABANDONWARE_BINARY,
    BINARY_LAYOUT,
    ROOT,
    StaticReTestFailure,
    read_text,
    sha256,
)


EXPECTED_BINARY_SHA256 = (
    "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3"
)


def _read_pe_bytes(path: Path, virtual_address: int, size: int) -> bytes:
    data = path.read_bytes()
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise StaticReTestFailure(f"not a PE image: {path}")
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe_offset:pe_offset + 4] != b"PE\0\0":
        raise StaticReTestFailure(f"missing PE signature: {path}")

    number_of_sections = struct.unpack_from("<H", data, pe_offset + 6)[0]
    optional_header_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
    optional_header = pe_offset + 24
    image_base = struct.unpack_from("<I", data, optional_header + 28)[0]
    rva = virtual_address - image_base
    section_offset = optional_header + optional_header_size
    for section_index in range(number_of_sections):
        header = section_offset + section_index * 40
        virtual_size, section_rva, raw_size, raw_offset = struct.unpack_from(
            "<IIII",
            data,
            header + 8,
        )
        section_size = max(virtual_size, raw_size)
        if section_rva <= rva and rva + size <= section_rva + section_size:
            file_offset = raw_offset + (rva - section_rva)
            return data[file_offset:file_offset + size]
    raise StaticReTestFailure(
        f"virtual range 0x{virtual_address:X}+0x{size:X} is not mapped by {path}"
    )


def test_stock_audio_bootstrap_and_settings_are_layout_backed() -> str:
    if not ABANDONWARE_BINARY.is_file():
        raise StaticReTestFailure(
            f"missing analyzed SolomonDark.exe: {ABANDONWARE_BINARY}"
        )
    binary_hash = sha256(ABANDONWARE_BINARY)
    if binary_hash != EXPECTED_BINARY_SHA256:
        raise StaticReTestFailure(
            "audio RE binary identity mismatch: "
            f"expected={EXPECTED_BINARY_SHA256} actual={binary_hash}"
        )

    layout_text = read_text(BINARY_LAYOUT)
    documentation_text = read_text(
        ROOT / "docs/reverse-engineering/native-audio-system.md"
    )
    required_layout_tokens = (
        "[audio.hooks]",
        "startup_coordinator=0x00407080",
        "load_persisted_volumes=0x00407190",
        "engine_initialize=0x004450D0",
        "engine_free=0x006B0186",
        "settings_apply=0x005D8FC0",
        "set_music_volume=0x00407340",
        "set_sound_volume=0x004073A0",
        "[audio.globals]",
        "manager=0x00B401A0",
        "engine_enabled=0x00B40239",
    )
    missing_layout = [
        token for token in required_layout_tokens if token not in layout_text
    ]
    if missing_layout:
        raise StaticReTestFailure(
            "audio binary layout is missing: " + ", ".join(missing_layout)
        )

    required_documentation_tokens = (
        "`BASS_Init(-1, 44100, 0, window, 0)`",
        "`Audio.SoundVolume`",
        "`Audio.MusicVolume`",
        "`Audio +0x78`",
        "`Audio +0x7C`",
        "`DAT_00B40239`",
        "`BASS_Free`",
        "Per-source muting is neither necessary nor complete.",
    )
    missing_documentation = [
        token
        for token in required_documentation_tokens
        if token not in documentation_text
    ]
    if missing_documentation:
        raise StaticReTestFailure(
            "native audio documentation is missing: "
            + ", ".join(missing_documentation)
        )

    instruction_contracts = (
        (
            0x004070A1,
            bytes.fromhex("E82AE00300"),
            "startup coordinator -> BASS initializer",
        ),
        (
            0x004070AE,
            bytes.fromhex("803D3902B40000"),
            "startup coordinator enabled-gate check",
        ),
        (
            0x004450D0,
            bytes.fromhex("E8B7B02600"),
            "BASS version query",
        ),
        (
            0x00445119,
            bytes.fromhex("E89EB02600"),
            "default-device BASS_Init",
        ),
        (
            0x0044512B,
            bytes.fromhex("E88CB02600"),
            "no-sound-device BASS_Init fallback",
        ),
        (
            0x00445143,
            bytes.fromhex("E8FCAF2600C6053902B40001"),
            "BASS_Start and enabled-gate write",
        ),
        (
            0x006B0186,
            bytes.fromhex("FF2558407800"),
            "BASS_Free import thunk",
        ),
        (
            0x00407349,
            bytes.fromhex("803D3902B40000"),
            "music-volume enabled-gate check",
        ),
        (
            0x004073A6,
            bytes.fromhex("803D3902B40000"),
            "sound-volume enabled-gate check",
        ),
        (
            0x005D9045,
            bytes.fromhex("E856E3E2FF"),
            "settings sound-volume setter call",
        ),
        (
            0x005D910F,
            bytes.fromhex("E82CE2E2FF"),
            "settings music-volume setter call",
        ),
    )
    mismatches: list[str] = []
    for address, expected, label in instruction_contracts:
        actual = _read_pe_bytes(ABANDONWARE_BINARY, address, len(expected))
        if actual != expected:
            mismatches.append(
                f"{label}@0x{address:08X} "
                f"expected={expected.hex()} actual={actual.hex()}"
            )
    if mismatches:
        raise StaticReTestFailure(
            "stock audio instruction contract mismatch: "
            + "; ".join(mismatches)
        )

    return (
        "stock BASS startup, no-sound fallback, global enabled gate, shutdown "
        "thunk, and settings volume writers match the analyzed executable"
    )


def test_launch_audio_disable_is_engine_level_and_player_opt_in() -> str:
    native_header = read_text(
        ROOT / "SolomonDarkModLoader/include/launch_audio_disable.h"
    )
    native_source = read_text(
        ROOT / "SolomonDarkModLoader/src/launch_audio_disable.cpp"
    )
    loader_source = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader.cpp"
    )
    native_project = read_text(
        ROOT / "SolomonDarkModLoader/SolomonDarkModLoader.vcxproj"
    )
    native_filters = read_text(
        ROOT / "SolomonDarkModLoader/SolomonDarkModLoader.vcxproj.filters"
    )
    launch_policy = read_text(
        ROOT
        / "SolomonDarkModLauncher/src/Launch/AudioLaunchEnvironment.cs"
    )
    staged_launcher = read_text(
        ROOT
        / "SolomonDarkModLauncher/src/Launch/StagedGameLauncher.cs"
    )
    injector = read_text(
        ROOT / "SolomonDarkModLauncher/src/Launch/WindowsDllInjector.cs"
    )
    command = read_text(
        ROOT / "SolomonDarkModLauncher/src/Commands/LauncherCommand.cs"
    )
    parser = read_text(
        ROOT / "SolomonDarkModLauncher/src/Commands/LauncherCommandParser.cs"
    )
    executor = read_text(
        ROOT / "SolomonDarkModLauncher/src/App/LauncherCommandExecutor.cs"
    )
    output = read_text(
        ROOT / "SolomonDarkModLauncher/src/App/LauncherOutputFormatter.cs"
    )
    ui_settings = read_text(
        ROOT
        / "SolomonDarkModLauncher.UI/src/Infrastructure/"
        "LauncherUiSettingsStore.cs"
    )
    ui_client = read_text(
        ROOT
        / "SolomonDarkModLauncher.UI/src/Infrastructure/"
        "LauncherUiCommandClient.cs"
    )
    ui_view_model = read_text(
        ROOT
        / "SolomonDarkModLauncher.UI/src/ViewModels/MainWindowViewModel.cs"
    )
    ui_view = read_text(
        ROOT / "SolomonDarkModLauncher.UI/src/Views/MainWindow.xaml"
    )
    launcher_contracts = read_text(
        ROOT / "tests/launcher-contracts/Program.cs"
    )

    required_pairs = (
        (
            native_header,
            "bool InitializeLaunchAudioDisable(std::string* error_message);",
        ),
        (native_header, "void ShutdownLaunchAudioDisable();"),
        (native_source, '"SDMOD_DISABLE_AUDIO"'),
        (native_source, '"audio.hooks"'),
        (native_source, '"engine_initialize"'),
        (native_source, '"engine_free"'),
        (native_source, '"audio.globals"'),
        (native_source, '"engine_enabled"'),
        (native_source, "InstallSafeX86Hook("),
        (native_source, "bass_free() == FALSE"),
        (native_source, "memory.TryWriteValue("),
        (
            native_source,
            "Launch audio disable suppressed stock BASS device ",
        ),
        (
            native_source,
            "Launch audio disable closed the active stock BASS engine and ",
        ),
        (loader_source, '#include "launch_audio_disable.h"'),
        (loader_source, "InitializeLaunchAudioDisable("),
        (loader_source, '"audio-disable-failed"'),
        (loader_source, "&ShutdownLaunchAudioDisable"),
        (native_project, r'include\launch_audio_disable.h'),
        (native_project, r'src\launch_audio_disable.cpp'),
        (native_filters, r'include\launch_audio_disable.h'),
        (native_filters, r'src\launch_audio_disable.cpp'),
        (
            launch_policy,
            'public const string DisableAudioVariable = "SDMOD_DISABLE_AUDIO";',
        ),
        (launch_policy, "disableAudio ? \"1\" : string.Empty"),
        (staged_launcher, "bool disableAudio = false"),
        (staged_launcher, "AudioLaunchEnvironment.Apply("),
        (staged_launcher, "waitForInputIdle: !disableAudio"),
        (injector, "bool waitForInputIdle = true"),
        (command, "bool DisableAudio,"),
        (parser, "var disableAudio = false;"),
        (parser, 'if (arg == "--disable-audio")'),
        (executor, "command.DisableAudio,"),
        (output, "--disable-audio"),
        (ui_settings, "public bool LoadDisableAudio()"),
        (ui_settings, "public void SaveDisableAudio(bool disableAudio)"),
        (ui_client, "public bool DisableAudio => disableAudio_;"),
        (ui_client, 'arguments.Add("--disable-audio");'),
        (ui_view_model, "public bool DisableAudio"),
        (ui_view, 'Text="Disable all audio"'),
        (
            launcher_contracts,
            '("audio disable launch routing", '
            "TestAudioDisableLaunchRoutingAsync)",
        ),
        (
            launcher_contracts,
            "normal player launch unexpectedly disabled audio",
        ),
        (
            launcher_contracts,
            "normal player launch inherited the audio-disable signal",
        ),
    )
    missing = [
        token
        for text, token in required_pairs
        if token not in text
    ]
    if missing:
        raise StaticReTestFailure(
            "launch audio disable contract is missing: "
            + ", ".join(missing)
        )

    opt_in_guard = native_source.find("if (!IsAudioDisableRequested()")
    first_address_resolution = native_source.find(
        'ResolveAudioAddress(\n            "audio.hooks"'
    )
    if (
        opt_in_guard < 0
        or first_address_resolution < 0
        or opt_in_guard > first_address_resolution
    ):
        raise StaticReTestFailure(
            "normal game launch resolves or patches audio before checking "
            "the per-launch opt-in"
        )

    policy_index = staged_launcher.find("AudioLaunchEnvironment.Apply(")
    process_start_index = staged_launcher.find("Process.Start(startInfo)")
    if (
        policy_index < 0
        or process_start_index < 0
        or policy_index > process_start_index
    ):
        raise StaticReTestFailure(
            "staged launcher does not apply the audio policy before process "
            "creation"
        )

    forbidden_native_tokens = (
        "Audio.SoundVolume",
        "Audio.MusicVolume",
        "settings_apply",
        "set_music_volume",
        "set_sound_volume",
    )
    forbidden = [
        token for token in forbidden_native_tokens if token in native_source
    ]
    if forbidden:
        raise StaticReTestFailure(
            "launch audio disable writes persisted or per-source volume "
            "state: " + ", ".join(forbidden)
        )

    return (
        "per-launch audio disable guards and closes the stock BASS engine, "
        "normal player launches explicitly clear the signal, and CLI/UI "
        "defaults remain audio-on"
    )


def test_automation_launch_surfaces_default_to_disabled_audio() -> str:
    direct_powershell = {
        "scripts/Crash-TestHubBotSession.ps1",
        "scripts/Launch-LocalMultiplayerAdditionalClient.ps1",
        "scripts/Launch-LocalMultiplayerPair.ps1",
        "scripts/Launch-LocalSoloSession.ps1",
        "scripts/Launch-TestBotSession.ps1",
        "scripts/Replay-UiSandbox.ps1",
        "scripts/Verify-Workspace.ps1",
    }
    direct_shell = {
        "scripts/Launch-WslSteamMultiplayerClient.sh",
    }
    direct_python = {
        "tools/cast_state_probe.py",
        "tools/probe_shared_hub_actor_contract.py",
        "tools/prove_scene_split.py",
        "tools/sample_private_region_entrances.py",
        "tools/trace_rich_item_startup.py",
    }
    reference_only_python = {
        "tools/verify_multiplayer_organic_enemy_cast_timing.py",
    }

    discovered_scripts: set[str] = set()
    for path in sorted((ROOT / "scripts").iterdir()):
        if path.suffix.lower() not in {".ps1", ".sh"}:
            continue
        text = read_text(path)
        if (
            "SolomonDarkModLauncher" in text
            and (
                '"launch"' in text
                or "'launch'" in text
                or "\n    launch\n" in text
            )
        ):
            discovered_scripts.add(path.relative_to(ROOT).as_posix())

    discovered_python: set[str] = set()
    for path in sorted((ROOT / "tools").glob("*.py")):
        text = read_text(path)
        if (
            "SolomonDarkModLauncher.exe" in text
            and ('"launch"' in text or "'launch'" in text)
        ):
            discovered_python.add(path.relative_to(ROOT).as_posix())

    expected_scripts = direct_powershell | direct_shell
    if discovered_scripts != expected_scripts:
        raise StaticReTestFailure(
            "automation launcher surface inventory changed without an audio "
            "policy update: expected="
            + ",".join(sorted(expected_scripts))
            + " discovered="
            + ",".join(sorted(discovered_scripts))
        )
    if discovered_python != direct_python | reference_only_python:
        raise StaticReTestFailure(
            "Python launcher surface inventory changed without an audio "
            "policy update: expected="
            + ",".join(sorted(direct_python | reference_only_python))
            + " discovered="
            + ",".join(sorted(discovered_python))
        )

    failures: list[str] = []
    for relative_path in sorted(direct_powershell):
        text = read_text(ROOT / relative_path)
        if (
            "--disable-audio" not in text
            or "[switch]$EnableAudio" not in text
        ):
            failures.append(relative_path)
    for relative_path in sorted(direct_shell):
        text = read_text(ROOT / relative_path)
        if (
            "--disable-audio" not in text
            or "SDMOD_ENABLE_AUDIO" not in text
        ):
            failures.append(relative_path)
    for relative_path in sorted(direct_python):
        text = read_text(ROOT / relative_path)
        if (
            "--disable-audio" not in text
            or "--enable-audio" not in text
        ):
            failures.append(relative_path)
    if failures:
        raise StaticReTestFailure(
            "automation launch surface can start without the default "
            "audio-disable signal or lacks an explicit opt-out: "
            + ", ".join(failures)
        )

    delegated_contracts = {
        "scripts/Verify-FreshInstallMultiplayer.ps1": (
            "[switch]$EnableAudio",
            "-EnableAudio:$audioEnabled",
            "audioDisabled",
        ),
        "scripts/Drive-DarkCloudBrowser.ps1": (
            "[switch]$EnableAudio",
            "EnableAudio = $EnableAudio",
        ),
        "scripts/Inspect-SettingsCustomizeKeyboard.ps1": (
            "[switch]$EnableAudio",
            '$replayArguments += "-EnableAudio"',
        ),
        "tools/verify_local_multiplayer_sync.py": (
            "enable_audio: bool | None = None",
            'os.environ.get("SDMOD_ENABLE_AUDIO") == "1"',
            'args.append("-EnableAudio")',
        ),
    }
    missing_delegated: list[str] = []
    for relative_path, tokens in delegated_contracts.items():
        text = read_text(ROOT / relative_path)
        missing_tokens = [token for token in tokens if token not in text]
        if missing_tokens:
            missing_delegated.append(
                relative_path + ":" + "|".join(missing_tokens)
            )
    if missing_delegated:
        raise StaticReTestFailure(
            "delegated automation surface lost its audio opt-out routing: "
            + ", ".join(missing_delegated)
        )

    return (
        "all direct and delegated repo automation launch surfaces default "
        "to --disable-audio and expose an explicit audio-test opt-out"
    )
