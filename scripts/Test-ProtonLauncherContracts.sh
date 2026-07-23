#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
work_root="${SDMOD_PROTON_TEST_ROOT:-$root/runtime/proton-launcher-contracts}"
timeout_seconds="${SDMOD_PROTON_TEST_TIMEOUT_SECONDS:-120}"
umu="${SDMOD_UMU_RUN:-umu-run}"

fail() {
    printf 'error: %s\n' "$1" >&2
    exit 1
}

if [[ $# -eq 0 ]]; then
    fail "pass at least one Proton root directory"
fi
if [[ ! "$timeout_seconds" =~ ^[1-9][0-9]*$ ]]; then
    fail "SDMOD_PROTON_TEST_TIMEOUT_SECONDS must be a positive integer"
fi

command -v dotnet >/dev/null || fail "dotnet is required"
command -v timeout >/dev/null || fail "timeout is required"
if [[ "$umu" == */* ]]; then
    [[ -x "$umu" ]] || fail "UMU launcher is not executable: $umu"
    umu="$(realpath "$umu")"
else
    umu="$(command -v "$umu")" || fail "UMU launcher was not found: $umu"
fi

steam_root="${SDMOD_LINUX_STEAM_ROOT:-}"
if [[ -z "$steam_root" ]]; then
    for candidate in \
        "$HOME/.steam/root" \
        "$HOME/.steam/debian-installation" \
        "$HOME/.local/share/Steam"; do
        if [[ -d "$candidate" ]]; then
            steam_root="$candidate"
            break
        fi
    done
fi
[[ -d "$steam_root" ]] || fail "Linux Steam root was not found"
steam_root="$(realpath "$steam_root")"

publish_dir="$work_root/publish"
artifacts_dir="$work_root/artifacts"
runtime_dir="$work_root/xdg-runtime"
mkdir -p "$publish_dir" "$artifacts_dir" "$runtime_dir"
chmod 700 "$runtime_dir"

dotnet publish \
    "$root/tests/launcher-contracts/SolomonDarkModLauncher.ContractTests.csproj" \
    -c Release \
    -r win-x86 \
    --self-contained true \
    -p:PublishSingleFile=false \
    --artifacts-path "$artifacts_dir" \
    -o "$publish_dir"

contract_executable="$publish_dir/SolomonDarkModLauncher.ContractTests.exe"
[[ -f "$contract_executable" ]] ||
    fail "launcher contract executable was not published: $contract_executable"

for requested_root in "$@"; do
    [[ -d "$requested_root" ]] || fail "Proton root was not found: $requested_root"
    proton_root="$(realpath "$requested_root")"
    proton="$proton_root/proton"
    [[ -x "$proton" ]] || fail "Proton launcher is not executable: $proton"

    label="$(basename "$proton_root")"
    [[ "$label" =~ ^[A-Za-z0-9._-]+$ ]] ||
        fail "Proton directory name is not safe for a test path: $label"
    compat_data="$work_root/compatdata/$label"
    bootstrap_log="$work_root/$label-bootstrap.log"
    contract_log="$work_root/$label-contracts.log"
    mkdir -p "$compat_data"

    if [[ ! -f "$compat_data/pfx/system.reg" ]]; then
        set +e
        env -u DBUS_SESSION_BUS_ADDRESS \
            XDG_RUNTIME_DIR="$runtime_dir" \
            STEAM_COMPAT_CLIENT_INSTALL_PATH="$steam_root" \
            STEAM_COMPAT_DATA_PATH="$compat_data" \
            PROTON_USE_XALIA="0" \
            WINEDEBUG=-all \
            timeout -k 5 "$timeout_seconds" \
            "$proton" run "C:\windows\system32\cmd.exe" /c exit 0 \
            2>&1 | tee "$bootstrap_log"
        bootstrap_exit=${PIPESTATUS[0]}
        set -e
        [[ $bootstrap_exit -eq 0 ]] ||
            fail "$label prefix bootstrap failed with exit $bootstrap_exit"
    fi

    set +e
    env -u DBUS_SESSION_BUS_ADDRESS \
        XDG_RUNTIME_DIR="$runtime_dir" \
        GAMEID=umu-default \
        PROTON_VERB="runinprefix" \
        PROTON_USE_XALIA="0" \
        WINEPREFIX="$compat_data" \
        PROTONPATH="$proton_root" \
        WINEDEBUG=-all \
        timeout -k 5 "$timeout_seconds" \
        "$umu" "$contract_executable" \
        2>&1 | tee "$contract_log"
    contract_exit=${PIPESTATUS[0]}
    set -e

    [[ $contract_exit -eq 0 ]] ||
        fail "$label launcher contracts failed with exit $contract_exit"
    if grep -Eq "^FAIL " "$contract_log"; then
        fail "$label launcher contracts reported a failure"
    fi
    if grep -Eq "Failed to load System.Private.CoreLib|Failed to create CoreCLR|Unhandled exception|FATAL UNHANDLED EXCEPTION|Traceback \(most recent call last\)|PermissionError" "$contract_log"; then
        fail "$label launcher contracts reported a runtime failure"
    fi
    pass_count="$(grep -Ec '^PASS ' "$contract_log" || true)"
    [[ $pass_count -gt 0 ]] || fail "$label launcher contracts reported no passes"
    printf 'PASS %s launcher contracts (%s assertions)\n' "$label" "$pass_count"
done
