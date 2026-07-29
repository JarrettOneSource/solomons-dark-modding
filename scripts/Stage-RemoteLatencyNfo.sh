#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
    printf 'usage: %s /root/sd-netlag-<id> <loader-sha256>\n' "$0" >&2
    exit 2
fi

remote_root="$1"
expected_loader_sha256="$2"
case "$remote_root" in
    /root/sd-netlag-[A-Za-z0-9._-]*)
        ;;
    *)
        printf 'error: unsafe remote root: %s\n' "$remote_root" >&2
        exit 3
        ;;
esac

incoming="$remote_root/incoming"
package_archive="$incoming/SolomonDarkMultiplayerBeta-v0.1.0-beta.22.zip"
game_archive="$incoming/Solomons-Dark-0.72.5-Original-Game.zip"
proton_archive="$incoming/GE-Proton10-34.tar.gz"
proton_checksum="$incoming/GE-Proton10-34.sha512sum"

expected_package_sha256="c6242f84e3e7856cdc9f5c8fc03ceddc4483ec9b0d87f48b4ebac0f2cacedb81"
expected_game_sha256="4947e8e1a820e384e2811e5e4a018cda63e1d169734fe075acab0a50121a4177"
expected_testrun_boneyard_sha256="bd3c38468481b7337b1e7382e5503cc214356906571763a68188b23e821e73fb"
expected_proton_sha256="51c580b66a833c73998fe00f0717eeac57197654040a2f2ed5189e3ee68d773d"
[[ "$expected_loader_sha256" =~ ^[0-9a-f]{64}$ ]] || {
    printf 'error: invalid loader sha256\n' >&2
    exit 3
}

for path in \
    "$package_archive" \
    "$game_archive" \
    "$proton_archive" \
    "$proton_checksum" \
    "$incoming/SolomonDarkModLoader.dll" \
    "$incoming/play.boneyard" \
    "$incoming/bot-brain.tar.gz" \
    "$incoming/remote-latency-controller.tar.gz" \
    "$incoming/Run-RemoteLatencyPeer.sh" \
    "$incoming/bot-settings-host.json" \
    "$incoming/bot-settings-client.json" \
    "$incoming/win32_lua_exec_client.exe"; do
    [[ -f "$path" ]] || {
        printf 'error: missing staged input: %s\n' "$path" >&2
        exit 4
    }
done

check_sha256() {
    local expected="$1"
    local path="$2"
    local actual
    actual="$(sha256sum "$path" | awk '{print $1}')"
    [[ "$actual" == "$expected" ]] || {
        printf 'error: sha256 mismatch for %s: %s\n' "$path" "$actual" >&2
        exit 5
    }
}

check_sha256 "$expected_package_sha256" "$package_archive"
check_sha256 "$expected_game_sha256" "$game_archive"
check_sha256 \
    "$expected_testrun_boneyard_sha256" \
    "$incoming/play.boneyard"
check_sha256 "$expected_proton_sha256" "$proton_archive"
check_sha256 \
    "$expected_loader_sha256" \
    "$incoming/SolomonDarkModLoader.dll"
(
    cd "$incoming"
    sha512sum -c "$(basename "$proton_checksum")"
)

for output in \
    "$remote_root/package" \
    "$remote_root/game" \
    "$remote_root/proton" \
    "$remote_root/package-extract" \
    "$remote_root/game-extract" \
    "$remote_root/proton-extract"; do
    [[ ! -e "$output" ]] || {
        printf 'error: refusing to overwrite staged output: %s\n' "$output" >&2
        exit 6
    }
done

mkdir \
    "$remote_root/package-extract" \
    "$remote_root/game-extract" \
    "$remote_root/proton-extract"

extract_zip() {
    local archive="$1"
    local destination="$2"
    python3 - "$archive" "$destination" <<'PY'
import pathlib
import shutil
import sys
import zipfile

archive = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2]).resolve()
with zipfile.ZipFile(archive) as source:
    for entry in source.infolist():
        normalized = entry.filename.replace("\\", "/")
        relative = pathlib.PurePosixPath(normalized)
        if relative.is_absolute() or ".." in relative.parts:
            raise SystemExit(f"unsafe zip member: {entry.filename!r}")
        target = destination.joinpath(*relative.parts)
        if entry.is_dir() or normalized.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open(entry) as input_stream:
            with target.open("wb") as output_stream:
                shutil.copyfileobj(input_stream, output_stream)
PY
}

extract_zip "$package_archive" "$remote_root/package-extract"
extract_zip "$game_archive" "$remote_root/game-extract"
tar -xzf "$proton_archive" -C "$remote_root/proton-extract"

mv \
    "$remote_root/package-extract/SolomonDarkMultiplayerBeta-v0.1.0-beta.22" \
    "$remote_root/package"
mv \
    "$remote_root/game-extract/SolomonDarkAbandonware" \
    "$remote_root/game"
mkdir -p "$remote_root/game/sandbox"
cp \
    "$incoming/play.boneyard" \
    "$remote_root/game/sandbox/play.boneyard"
mv \
    "$remote_root/proton-extract/GE-Proton10-34" \
    "$remote_root/proton"
rmdir \
    "$remote_root/package-extract" \
    "$remote_root/game-extract" \
    "$remote_root/proton-extract"

mkdir -p "$remote_root/package/mods" "$remote_root/tools"
tar -xzf \
    "$incoming/bot-brain.tar.gz" \
    -C "$remote_root/package/mods"
tar -xzf \
    "$incoming/remote-latency-controller.tar.gz" \
    -C "$remote_root/package/mods"
cp \
    "$incoming/SolomonDarkModLoader.dll" \
    "$remote_root/package/launcher/SolomonDarkModLoader.dll"
cp \
    "$incoming/Run-RemoteLatencyPeer.sh" \
    "$incoming/bot-settings-host.json" \
    "$incoming/bot-settings-client.json" \
    "$incoming/win32_lua_exec_client.exe" \
    "$remote_root/tools/"
chmod 700 \
    "$remote_root/tools/Run-RemoteLatencyPeer.sh" \
    "$remote_root/proton/proton"

[[ -f "$remote_root/package/launcher/SolomonDarkModLauncher.exe" ]]
[[ -f "$remote_root/package/launcher/SolomonDarkModLoader.dll" ]]
[[ -f "$remote_root/package/mods/bot-brain/manifest.json" ]]
[[ -f "$remote_root/package/mods/remote-latency-controller/manifest.json" ]]
[[ -f "$remote_root/game/SolomonDark.exe" ]]
[[ -x "$remote_root/proton/proton" ]]
[[ -x "$remote_root/tools/Run-RemoteLatencyPeer.sh" ]]

sha256sum \
    "$remote_root/package/launcher/SolomonDarkModLauncher.exe" \
    "$remote_root/package/launcher/SolomonDarkModLoader.dll" \
    "$remote_root/package/mods/bot-brain/manifest.json" \
    "$remote_root/package/mods/remote-latency-controller/manifest.json" \
    "$remote_root/game/SolomonDark.exe" \
    "$remote_root/game/sandbox/play.boneyard" \
    "$remote_root/tools/Run-RemoteLatencyPeer.sh" \
    "$remote_root/tools/win32_lua_exec_client.exe"
