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
    engine_documentation_text = read_text(
        ROOT
        / "docs/reverse-engineering/native-audio-engine-2026-07-26.md"
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
        "compiled_registry=0x008199D8",
        "[audio.vtables]",
        "manager=0x007DB6CC",
        "sound=0x007DB784",
        "sound_loop=0x007DB78C",
        "sound_echo=0x007DB7AC",
        "sound_delayed=0x007DB7CC",
        "music=0x007DB7F0",
        "sound_stream=0x007DB810",
        "ambient_sound=0x007DB818",
        "[audio.lifecycle]",
        "manager_constructor=0x00406DE0",
        "manager_destructor=0x00406F90",
        "manager_pause=0x00407400",
        "manager_tick_thunk=0x00407460",
        "manager_stop_all=0x00407470",
        "sound_constructor=0x00407530",
        "sound_destructor=0x004075F0",
        "sound_load=0x004076D0",
        "sound_acquire_channel=0x00407A20",
        "sound_play=0x00407B70",
        "sound_play_with_pitch=0x00407CD0",
        "sound_stop=0x00407F90",
        "sound_loop_constructor=0x00408040",
        "sound_loop_destructor=0x00408160",
        "sound_loop_load=0x00408220",
        "sound_loop_start=0x00408320",
        "sound_loop_stop=0x00408350",
        "sound_loop_tick=0x00408390",
        "sound_echo_constructor=0x004084A0",
        "sound_echo_tick=0x00408550",
        "sound_delayed_constructor=0x004085C0",
        "sound_delayed_tick=0x00408690",
        "music_constructor=0x004086E0",
        "music_destructor=0x00408790",
        "music_load=0x004088A0",
        "music_tick=0x00409610",
        "music_stop=0x0040A3F0",
        "sound_stream_constructor=0x0040AC60",
        "sound_stream_destructor=0x0040AC70",
        "sound_stream_deleting_destructor=0x0040ACC0",
        "sound_stream_load=0x0040ACF0",
        "sound_stream_play=0x0040AF70",
        "sound_stream_pause=0x0040AFB0",
        "sound_stream_set_volume=0x0040AFD0",
        "sound_stream_is_active=0x0040B000",
        "sound_stream_get_level=0x0040B020",
        "ambient_sound_constructor=0x0040B060",
        "ambient_sound_destructor=0x0040B080",
        "ambient_sound_tick=0x0040B120",
        "application_audio_shutdown=0x0040C690",
        "[audio.registry]",
        "constructor=0x005A8DD0",
        "load_compiled_assets=0x004EE010",
        "entry_count=233",
        "sound_loop_first_index=151",
        "sound_loop_count=22",
        "sound_loop_first_offset=0x146C",
        "sound_loop_stride=0x60",
        "frost_loop_index=161",
        "frost_loop_offset=0x182C",
        "[audio.spell_calls]",
        "frost_loop_start=0x00549BB2",
        "frost_loop_stop=0x00549725",
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
    required_engine_documentation_tokens = (
        "`BASS_ChannelFlags(handle, 4, 4)`",
        "`SoundLoop_Start` at `0x00408320`",
        "`SoundLoop_Stop` at `0x00408350`",
        "`BASS_ChannelPause`",
        "`sounds\\iceloop__loop`",
        "`+0x182C`",
        "`0x00549BB2`",
        "`0x00549725`",
        "missing native release edge after an on-time snapshot",
    )
    missing_engine_documentation = [
        token
        for token in required_engine_documentation_tokens
        if token not in engine_documentation_text
    ]
    if missing_engine_documentation:
        raise StaticReTestFailure(
            "native audio engine lifecycle documentation is missing: "
            + ", ".join(missing_engine_documentation)
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
        (
            0x00406DE0,
            bytes.fromhex("558BEC6AFF68CAF5"),
            "Audio constructor",
        ),
        (
            0x00406F90,
            bytes.fromhex("558BEC6AFF6872F5"),
            "Audio destructor",
        ),
        (
            0x00407400,
            bytes.fromhex("558BEC8A550884D2"),
            "Audio pause reference-count path",
        ),
        (
            0x00407460,
            bytes.fromhex("81C1BC000000E935"),
            "Audio tick vtable this-adjustor",
        ),
        (
            0x00407470,
            bytes.fromhex("56578BF133FF39BE"),
            "Audio stop-all path",
        ),
        (
            0x00407530,
            bytes.fromhex("558BEC6AFF683BE9"),
            "Sound constructor",
        ),
        (
            0x004075F0,
            bytes.fromhex("558BEC6AFF68CBEE"),
            "Sound destructor",
        ),
        (
            0x004076D0,
            bytes.fromhex("558BEC6AFF6820FF"),
            "Sound sample loader",
        ),
        (
            0x00407A20,
            bytes.fromhex("558BEC83EC285657"),
            "Sound channel acquisition",
        ),
        (
            0x00407B70,
            bytes.fromhex("558BEC6AFF689BEE"),
            "Sound gain-only play wrapper",
        ),
        (
            0x00407CD0,
            bytes.fromhex("558BEC6AFF689BEE"),
            "Sound pitch-and-gain play wrapper",
        ),
        (
            0x00407F90,
            bytes.fromhex("56578BF933F63977"),
            "Sound stop path",
        ),
        (
            0x00408040,
            bytes.fromhex("558BEC6AFF6813F5"),
            "SoundLoop constructor",
        ),
        (
            0x00408160,
            bytes.fromhex("558BEC6AFF68E3F4"),
            "SoundLoop destructor",
        ),
        (
            0x00408220,
            bytes.fromhex("558BEC6AFF68581B"),
            "SoundLoop loader",
        ),
        (
            0x00408320,
            bytes.fromhex("568BF1837E4C0075"),
            "SoundLoop start",
        ),
        (
            0x00408350,
            bytes.fromhex("568BF1FF4E4C8B46"),
            "SoundLoop stop",
        ),
        (
            0x00408390,
            bytes.fromhex("558BEC51568BF18B"),
            "SoundLoop fade tick",
        ),
        (
            0x004084A0,
            bytes.fromhex("558BEC6AFF6838EE"),
            "SoundEcho constructor",
        ),
        (
            0x00408550,
            bytes.fromhex("558BEC51568BF1D9"),
            "SoundEcho tick",
        ),
        (
            0x004085C0,
            bytes.fromhex("558BEC6AFF6838EE"),
            "SoundDelayed constructor",
        ),
        (
            0x00408690,
            bytes.fromhex("FF4920837920007F"),
            "SoundDelayed tick",
        ),
        (
            0x004086E0,
            bytes.fromhex("8B159801B400D9E8"),
            "Music constructor",
        ),
        (
            0x00408790,
            bytes.fromhex("558BEC6AFF68AEF4"),
            "Music destructor",
        ),
        (
            0x004088A0,
            bytes.fromhex("558BEC6AFF68B90D"),
            "Music loader",
        ),
        (
            0x00409610,
            bytes.fromhex("558BEC83EC14568B"),
            "Music crossfade tick",
        ),
        (
            0x0040A3F0,
            bytes.fromhex("5356578BF98D7718"),
            "Music stop",
        ),
        (
            0x0040AC60,
            bytes.fromhex("8BC1C70010B87D00"),
            "SoundStream constructor",
        ),
        (
            0x0040AC70,
            bytes.fromhex("558BEC803D3902B4"),
            "SoundStream destructor",
        ),
        (
            0x0040ACC0,
            bytes.fromhex("803D3902B4000056"),
            "SoundStream deleting destructor",
        ),
        (
            0x0040ACF0,
            bytes.fromhex("558BEC6AFF6820FF"),
            "SoundStream loader",
        ),
        (
            0x0040AF70,
            bytes.fromhex("558BEC803D3902B4"),
            "SoundStream play",
        ),
        (
            0x0040AFB0,
            bytes.fromhex("803D3902B4000074"),
            "SoundStream pause",
        ),
        (
            0x0040AFD0,
            bytes.fromhex("558BEC803D3902B4"),
            "SoundStream volume writer",
        ),
        (
            0x0040B000,
            bytes.fromhex("803D3902B400008B"),
            "SoundStream active query",
        ),
        (
            0x0040B020,
            bytes.fromhex("558BEC51803D3902"),
            "SoundStream level query",
        ),
        (
            0x0040B060,
            bytes.fromhex("D9EE8BC1D95004C7"),
            "AmbientSound constructor",
        ),
        (
            0x0040B080,
            bytes.fromhex("558BEC56578BF98B"),
            "AmbientSound destructor",
        ),
        (
            0x0040B120,
            bytes.fromhex("558BEC51568BF18B"),
            "AmbientSound zero-crossing tick",
        ),
        (
            0x0040C690,
            bytes.fromhex("558BEC83E4F86AFF"),
            "application audio shutdown owner",
        ),
        (
            0x004EE010,
            bytes.fromhex("515356576A0A83EC"),
            "compiled audio registry loader",
        ),
        (
            0x005A8DD0,
            bytes.fromhex("6AFF688D1C770064"),
            "compiled audio registry constructor",
        ),
        (
            0x007DB6CC,
            bytes.fromhex("606F400000C35500"),
            "Audio vtable",
        ),
        (
            0x007DB784,
            bytes.fromhex("C075400054937E00"),
            "Sound vtable",
        ),
        (
            0x007DB78C,
            bytes.fromhex("3081400000C35500"),
            "SoundLoop vtable",
        ),
        (
            0x007DB7AC,
            bytes.fromhex("6086400000C35500"),
            "SoundEcho vtable",
        ),
        (
            0x007DB7CC,
            bytes.fromhex("6086400000C35500"),
            "SoundDelayed vtable",
        ),
        (
            0x007DB7F0,
            bytes.fromhex("6087400000C35500"),
            "Music vtable",
        ),
        (
            0x007DB810,
            bytes.fromhex("70AC400098917E00"),
            "SoundStream vtable",
        ),
        (
            0x007DB818,
            bytes.fromhex("80B0400077696E33"),
            "AmbientSound vtable",
        ),
        (
            0x004082BD,
            bytes.fromhex("6A046A0450E8EF7E2A00"),
            "SoundLoop BASS loop-flag application",
        ),
        (
            0x00408343,
            bytes.fromhex("D9E8FF464CD95E5C"),
            "SoundLoop start reference increment",
        ),
        (
            0x00408353,
            bytes.fromhex("FF4E4C8B464C85C07F24"),
            "SoundLoop stop reference decrement",
        ),
        (
            0x0040836D,
            bytes.fromhex("8B0050E8357E2A00D9EEC7464C00000000"),
            "SoundLoop pause and zero clamp",
        ),
        (
            0x00549BAC,
            bytes.fromhex("81C12C180000E869E7EBFF"),
            "Frost loop registry offset and start call",
        ),
        (
            0x0054971F,
            bytes.fromhex("81C12C180000E826ECEBFF"),
            "Frost loop registry offset and stop call",
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
    observability_header = read_text(
        ROOT
        / "SolomonDarkModLoader/include/native_audio_observability.h"
    )
    observability_source = read_text(
        ROOT
        / "SolomonDarkModLoader/src/native_audio_observability.cpp"
    )
    observability_lua = read_text(
        ROOT
        / "SolomonDarkModLoader/src/lua_engine_bindings_debug/"
        "functions_native_audio.inl"
    )
    frost_lifecycle_verifier = read_text(
        ROOT / "tools/verify_multiplayer_frost_loop_lifecycle.py"
    )
    debug_bindings = read_text(
        ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_debug.cpp"
    )
    player_tick = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "actor_tick/player_actor_tick_hook.inl"
    )
    loader_source = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader.cpp"
    ) + read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader/initialize.inl"
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
            observability_header,
            "struct NativeAudioChannelSnapshot",
        ),
        (
            observability_header,
            "class ScopedNativeAudioAttribution final",
        ),
        (
            observability_header,
            "SnapshotNativeAudioChannels(",
        ),
        (
            observability_source,
            '"audio.lifecycle"',
        ),
        (
            observability_source,
            '"sound_loop_start"',
        ),
        (
            observability_source,
            '"sound_loop_stop"',
        ),
        (
            observability_source,
            '"compiled_registry"',
        ),
        (
            observability_source,
            "InstallSafeX86Hook(",
        ),
        (
            observability_source,
            "kSoundLoopReferenceCountOffset = 0x4C",
        ),
        (
            observability_source,
            '"sounds\\\\iceloop__loop"',
        ),
        (
            observability_source,
            '"spell.frost_jet"',
        ),
        (
            observability_source,
            '"[native-audio] event=start monotonic_ms="',
        ),
        (
            observability_source,
            '"[native-audio] event=stop monotonic_ms="',
        ),
        (
            observability_source,
            "ClearInactiveNativeAudioChannelHistory()",
        ),
        (
            observability_lua,
            "SnapshotNativeAudioChannels(include_inactive)",
        ),
        (
            observability_lua,
            '"native_reference_count"',
        ),
        (
            observability_lua,
            '"participant_id_text"',
        ),
        (
            debug_bindings,
            '"get_native_audio_channels"',
        ),
        (
            debug_bindings,
            '"dump_native_audio_channels"',
        ),
        (
            debug_bindings,
            '"clear_native_audio_channel_history"',
        ),
        (
            player_tick,
            "ScopedNativeAudioAttribution native_audio_attribution(",
        ),
        (
            player_tick,
            "native_audio_attribution.SetParticipantCast(",
        ),
        (
            loader_source,
            "InitializeNativeAudioObservability(",
        ),
        (
            loader_source,
            "&ShutdownNativeAudioObservability",
        ),
        (
            native_project,
            r'include\native_audio_observability.h',
        ),
        (
            native_project,
            r'src\native_audio_observability.cpp',
        ),
        (
            native_project,
            r'functions_native_audio.inl',
        ),
        (
            native_filters,
            r'include\native_audio_observability.h',
        ),
        (
            native_filters,
            r'src\native_audio_observability.cpp',
        ),
        (
            native_filters,
            r'functions_native_audio.inl',
        ),
        (
            frost_lifecycle_verifier,
            'INSTANCE_PREFIX = "sfx"',
        ),
        (
            frost_lifecycle_verifier,
            "HOST_PORT = 48611",
        ),
        (
            frost_lifecycle_verifier,
            "CLIENT_PORT = 48612",
        ),
        (
            frost_lifecycle_verifier,
            "enable_audio=False",
        ),
        (
            frost_lifecycle_verifier,
            "sd.debug.get_native_audio_channels(false)",
        ),
        (
            frost_lifecycle_verifier,
            "no_outliving_owned_loop",
        ),
        (
            frost_lifecycle_verifier,
            "audio.stop_owned_processes(",
        ),
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
    forbidden_frost_tokens = (
        "trace_function",
        "enable_audio=True",
        "stop_games(",
    )
    leaked_frost_tokens = [
        token
        for token in forbidden_frost_tokens
        if token in frost_lifecycle_verifier
    ]
    if leaked_frost_tokens:
        raise StaticReTestFailure(
            "Frost loop verifier bypassed registry or process/audio "
            "guardrails: " + ", ".join(leaked_frost_tokens)
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
    hard_disabled_powershell = {
        "scripts/Launch-BotPublicationPair.ps1",
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
    hard_disabled_python = {
        "tools/verify_bot_capacity_membership.py",
        "tools/verify_bot_play_for_me_solo.py",
        "tools/verify_bot_polish.py",
        "tools/verify_bot_wave_respawn.py",
        "tools/verify_multiplayer_local_hit_feedback.py",
    }
    reference_only_python = {
        "tools/verify_bot_level_up_continuity.py",
        "tools/verify_lua_bot_brain.py",
        "tools/verify_lua_bot_players.py",
        "tools/verify_mod_settings_lifecycle.py",
        "tools/verify_multiplayer_organic_enemy_cast_timing.py",
        "tools/verify_multiplayer_replicated_audio_events.py",
        "tools/verify_remote_latency_wave5.py",
        "tools/verify_world_render_z_order.py",
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

    expected_scripts = direct_powershell | hard_disabled_powershell | direct_shell
    if discovered_scripts != expected_scripts:
        raise StaticReTestFailure(
            "automation launcher surface inventory changed without an audio "
            "policy update: expected="
            + ",".join(sorted(expected_scripts))
            + " discovered="
            + ",".join(sorted(discovered_scripts))
        )
    if discovered_python != (
        direct_python |
        hard_disabled_python |
        reference_only_python
    ):
        raise StaticReTestFailure(
            "Python launcher surface inventory changed without an audio "
            "policy update: expected="
            + ",".join(
                sorted(
                    direct_python |
                    hard_disabled_python |
                    reference_only_python
                )
            )
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
    for relative_path in sorted(hard_disabled_powershell):
        text = read_text(ROOT / relative_path)
        if (
            "--disable-audio" not in text
            or 'SDMOD_DISABLE_AUDIO = "1"' not in text
            or 'SDMOD_ENABLE_AUDIO = "0"' not in text
            or "EnableAudio" in text
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
    for relative_path in sorted(hard_disabled_python):
        text = read_text(ROOT / relative_path)
        if (
            'environment["SDMOD_DISABLE_AUDIO"] = "1"' not in text
            or 'environment["SDMOD_ENABLE_AUDIO"] = "0"' not in text
            or "-EnableAudio" in text
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
        "to --disable-audio, with general tools exposing an explicit "
        "audio-test opt-out and publication proof hard-disabled"
    )
