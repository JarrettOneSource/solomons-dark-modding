#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    printf 'usage: %s /root/sd-netrepro-20260729\n' "$0" >&2
    exit 2
fi

stage_root="$1"
if [[ "$stage_root" != "/root/sd-netrepro-20260729" ]]; then
    printf 'error: unexpected stage root: %s\n' "$stage_root" >&2
    exit 3
fi

incoming="$stage_root/incoming"
package_root="$stage_root/package"
game_root="$stage_root/game"
proton_extract="$stage_root/proton-extract"
proton_root="$stage_root/proton"
tools_root="$stage_root/tools"
observer_root="$package_root/mods/tool.real_flow_e2e_observer"

for path in \
    "$incoming/package.tar.gz" \
    "$incoming/game.tar.gz" \
    "$incoming/GE-Proton.tar.gz" \
    "$incoming/observer.tar.gz" \
    "$incoming/Run-RealFlowRemotePeer.sh" \
    "$incoming/win32_lua_exec_client.exe" \
    "$incoming/win32_real_input.exe" \
    "$incoming/input-sha256.txt"; do
    [[ -f "$path" ]] || {
        printf 'error: missing staged input: %s\n' "$path" >&2
        exit 4
    }
done

if find "$stage_root" -mindepth 1 -maxdepth 1 \
    ! -name incoming -print -quit | grep -q .; then
    printf 'error: refusing to overwrite an existing remote stage\n' >&2
    exit 5
fi

(
    cd "$incoming"
    sha256sum -c input-sha256.txt
)

mkdir \
    "$package_root" \
    "$game_root" \
    "$proton_extract" \
    "$tools_root"
tar -xzf "$incoming/package.tar.gz" -C "$package_root"
tar -xzf "$incoming/game.tar.gz" -C "$game_root"
tar -xzf "$incoming/GE-Proton.tar.gz" -C "$proton_extract"
mkdir -p "$observer_root"
tar -xzf "$incoming/observer.tar.gz" -C "$observer_root"

mapfile -t proton_launchers < <(
    find "$proton_extract" -mindepth 2 -maxdepth 2 \
        -type f -name proton -print
)
if [[ ${#proton_launchers[@]} -ne 1 ]]; then
    printf 'error: Proton archive contained %d launchers\n' \
        "${#proton_launchers[@]}" >&2
    exit 6
fi
mv "$(dirname "${proton_launchers[0]}")" "$proton_root"
rmdir "$proton_extract"

cp \
    "$incoming/Run-RealFlowRemotePeer.sh" \
    "$incoming/win32_lua_exec_client.exe" \
    "$incoming/win32_real_input.exe" \
    "$tools_root/"
chmod 700 \
    "$tools_root/Run-RealFlowRemotePeer.sh" \
    "$proton_root/proton"

[[ -f "$package_root/SolomonDarkMultiplayerBeta.exe" ]]
[[ -f "$package_root/launcher/SolomonDarkModLauncher.exe" ]]
[[ -f "$game_root/SolomonDark.exe" ]]
[[ -f "$observer_root/manifest.json" ]]
[[ -f "$observer_root/scripts/main.lua" ]]
[[ -x "$proton_root/proton" ]]

"$tools_root/Run-RealFlowRemotePeer.sh" \
    "$stage_root" \
    bundle-x11

sha256sum \
    "$package_root/SolomonDarkMultiplayerBeta.exe" \
    "$package_root/launcher/SolomonDarkModLauncher.exe" \
    "$game_root/SolomonDark.exe" \
    "$observer_root/manifest.json" \
    "$tools_root/Run-RealFlowRemotePeer.sh" \
    "$tools_root/win32_lua_exec_client.exe" \
    "$tools_root/win32_real_input.exe" \
    >"$stage_root/evidence/stage-outputs-sha256.txt"
printf 'prepared\n'
