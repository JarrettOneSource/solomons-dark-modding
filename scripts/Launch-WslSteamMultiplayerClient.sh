#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
lobby_id="${1:-}"
instance="${SDMOD_WSL_STEAM_INSTANCE:-wsl-steam-client}"
game_dir="${SDMOD_GAME_DIR:-$root/../SolomonDarkAbandonware}"
steam_root="${SDMOD_LINUX_STEAM_ROOT:-$HOME/.steam/debian-installation}"
proton="${SDMOD_PROTON_PATH:-$HOME/.local/share/Steam/compatibilitytools.d/GE-Proton11-1/proton}"
compat_data="${SDMOD_STEAM_COMPAT_DATA:-$HOME/.local/share/Steam/steamapps/compatdata/480}"
steam_api="${SDMOD_STEAM_API_DLL:-/mnt/c/Program Files (x86)/Steam/steamapps/common/SteamVR/bin/win32/steam_api.dll}"
test_boneyard_override="${SDMOD_TEST_SURVIVAL_BONEYARD_OVERRIDE:-}"
publish_dir="$root/runtime/wsl-steam-launcher"
build_artifacts="$root/runtime/wsl-steam-build-artifacts"
launcher="$publish_dir/SolomonDarkModLauncher.exe"
loader="$root/bin/Release/Win32/SolomonDarkModLoader.dll"

fail() {
    printf 'error: %s\n' "$1" >&2
    exit 1
}

proton_path() {
    local absolute
    absolute="$(realpath "$1")"
    printf 'Z:%s' "$absolute" | sed 's#/#\\#g'
}

command -v dotnet >/dev/null || fail "dotnet is required in WSL"
[[ -x "$proton" ]] || fail "Proton launcher not found: $proton"
[[ -d "$steam_root" ]] || fail "Linux Steam root not found: $steam_root"
[[ -f "$steam_root/config/loginusers.vdf" ]] ||
    fail "the isolated Linux Steam client is not signed in"
pgrep -f "$steam_root/ubuntu12_32/steam" >/dev/null ||
    fail "the isolated Linux Steam client is not running"
[[ -d "$game_dir" ]] || fail "Solomon Dark game directory not found: $game_dir"
[[ -f "$loader" ]] ||
    fail "Release loader not found; run scripts/Build-All.ps1 -Configuration Release first"
[[ -f "$steam_api" ]] || fail "x86 steam_api.dll not found: $steam_api"

test_environment=()
if [[ -n "$test_boneyard_override" ]]; then
    [[ -f "$test_boneyard_override" ]] ||
        fail "test survival boneyard override not found: $test_boneyard_override"
    [[ "${test_boneyard_override,,}" == *.boneyard ]] ||
        fail "test survival boneyard override must be a .boneyard file"
    test_environment+=(
        "SDMOD_TEST_SURVIVAL_BONEYARD_OVERRIDE=$(proton_path "$test_boneyard_override")"
    )
fi
if [[ "${SDMOD_TEST_BLANK_BONEYARD:-}" == "1" ]]; then
    test_environment+=("SDMOD_TEST_BLANK_BONEYARD=1")
fi

mkdir -p "$build_artifacts"
dotnet publish "$root/SolomonDarkModLauncher/SolomonDarkModLauncher.csproj" \
    -c Release \
    -r win-x86 \
    --self-contained true \
    --artifacts-path "$build_artifacts" \
    -o "$publish_dir"
if ! cmp -s "$loader" "$publish_dir/SolomonDarkModLoader.dll"; then
    cp "$loader" "$publish_dir/SolomonDarkModLoader.dll"
fi

args=(
    "$(proton_path "$launcher")"
    launch
    --json
    --instance "$instance"
    --game-dir "$(proton_path "$game_dir")"
    --steam-appid 480
    --steam-api-dll "$(proton_path "$steam_api")"
    --multiplayer join
    --temporary-profile
)
if [[ -n "$lobby_id" ]]; then
    [[ "$lobby_id" =~ ^[0-9]+$ ]] || fail "lobby id must be numeric"
    args+=(--lobby-id "$lobby_id")
fi

mkdir -p "$compat_data"
exec env \
    LP_NUM_THREADS=4 \
    STEAM_COMPAT_CLIENT_INSTALL_PATH="$steam_root" \
    STEAM_COMPAT_DATA_PATH="$compat_data" \
    SteamAppId=480 \
    SteamGameId=480 \
    "${test_environment[@]}" \
    "$proton" run "${args[@]}"
