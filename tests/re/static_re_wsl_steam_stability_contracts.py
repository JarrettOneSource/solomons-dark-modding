"""WSL Steam runtime stability contracts."""

from __future__ import annotations

from static_re_contract_support import ROOT, StaticReTestFailure, read_text


def test_wsl_steam_runtime_uses_the_stable_proton_generation() -> str:
    launch_text = read_text(ROOT / "scripts/Launch-WslSteamMultiplayerClient.sh")
    lua_text = read_text(ROOT / "scripts/Invoke-WslLuaExec.sh")
    verifier_path = ROOT / "tools/verify_wsl_steam_session_stability.py"

    required_generation = "GE-Proton10-34"
    retired_generation = "GE-Proton11-1"
    failures: list[str] = []

    for label, text in (("game launch", launch_text), ("Lua bridge", lua_text)):
        if required_generation not in text:
            failures.append(f"{label} does not default to {required_generation}")
        if retired_generation in text:
            failures.append(
                f"{label} still defaults to the PulseAudio-crashing {retired_generation}"
            )

    if "export WINEFSYNC=1" not in lua_text:
        failures.append(
            "Lua bridge does not match the Proton game's Wine server FSYNC mode"
        )

    if not verifier_path.is_file():
        failures.append("timed WSL Steam stability verifier is missing")
    else:
        verifier_text = read_text(verifier_path)
        for token in (
            "pa_stream_get_time()",
            "authenticatedPeerCount",
            "process_start_ticks",
            "new_crash_artifacts",
            "--duration",
        ):
            if token not in verifier_text:
                failures.append(f"stability verifier does not enforce {token}")

    if failures:
        raise StaticReTestFailure("; ".join(failures))

    return (
        f"WSL game and Lua execution use {required_generation}, with a timed process, "
        "session, and PulseAudio-abort regression gate"
    )
