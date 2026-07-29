#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
    printf 'usage: %s <stage-root> <command> [args...]\n' "$0" >&2
    exit 2
fi

stage_root="$1"
command_name="$2"
shift 2

if [[ "$stage_root" != "/root/sd-netrepro-20260729" ]]; then
    printf 'error: unexpected stage root: %s\n' "$stage_root" >&2
    exit 3
fi

package_root="$stage_root/package"
game_root="$stage_root/game"
proton_root="$stage_root/proton"
runtime_root="$stage_root/runtime"
tools_root="$stage_root/tools"
process_root="$stage_root/processes"
logs_root="$stage_root/logs"
evidence_root="$stage_root/evidence"
prefix_root="$stage_root/prefix"
xdg_root="$stage_root/xdg"
tmp_root="$stage_root/tmp"
x11_root="$stage_root/x11"
display_number=97

windows_path() {
    local absolute
    absolute="$(realpath "$1")"
    printf 'Z:%s' "$absolute" | sed 's#/#\\#g'
}

validate_token() {
    [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$ ]] || {
        printf 'error: unsafe token: %s\n' "$1" >&2
        exit 4
    }
}

validate_port() {
    [[ "$1" =~ ^[0-9]+$ && "$1" -ge 1024 && "$1" -le 65535 ]] || {
        printf 'error: invalid port: %s\n' "$1" >&2
        exit 5
    }
}

pid_owned() {
    local pid="$1"
    [[ "$pid" =~ ^[0-9]+$ && -d "/proc/$pid" ]] || return 1
    local cmdline=""
    local executable=""
    local working_directory=""
    local windows_root="${stage_root//\//\\}"
    [[ -r "/proc/$pid/cmdline" ]] &&
        cmdline="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
    executable="$(readlink -f "/proc/$pid/exe" 2>/dev/null || true)"
    working_directory="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
    [[ "$cmdline" == *"$stage_root"* ||
       "$cmdline" == *"$windows_root"* ||
       "$executable" == "$stage_root/"* ||
       "$working_directory" == "$stage_root/"* ]]
}

refresh_ledger() {
    mkdir -p "$process_root"
    local temporary="$process_root/.owned-pids.$$"
    : >"$temporary"
    for proc_path in /proc/[0-9]*; do
        local pid="${proc_path#/proc/}"
        [[ "$pid" != "$$" && "$pid" != "$PPID" ]] || continue
        pid_owned "$pid" || continue
        printf '%s\n' "$pid" >>"$temporary"
    done
    sort -nu "$temporary" >"$process_root/owned-pids.txt"
    rm -f "$temporary"
}

x11_env() {
    export PATH="$x11_root/usr/bin:$PATH"
    export LD_LIBRARY_PATH="$x11_root/lib/x86_64-linux-gnu:$x11_root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    export XKB_CONFIG_ROOT="$x11_root/usr/share/X11/xkb"
    export DISPLAY=":$display_number"
}

bundle_binary() {
    local binary="$1"
    local resolved
    resolved="$(command -v "$binary")"
    cp --parents "$resolved" "$x11_root"
    while IFS= read -r library; do
        [[ -f "$library" ]] && cp --parents "$library" "$x11_root"
    done < <(
        ldd "$resolved" |
            sed -nE 's/.*=> (\/[^ ]+).*/\1/p; s/^[[:space:]]*(\/[^ ]+).*/\1/p'
    )
}

bundle_x11() {
    mkdir -p "$x11_root"
    bundle_binary Xvfb
    bundle_binary xdpyinfo
    bundle_binary xdotool
    bundle_binary xwd
    bundle_binary xkbcomp
    bundle_binary ffmpeg
    mkdir -p "$x11_root/usr/share/X11"
    cp -a /usr/share/X11/xkb "$x11_root/usr/share/X11/"
    find "$x11_root" -type f -print0 | sort -z |
        xargs -0 sha256sum >"$evidence_root/x11-bundle-sha256.txt"
}

start_xvfb() {
    x11_env
    local pid_file="$process_root/xvfb.pid"
    if [[ -f "$pid_file" ]] && pid_owned "$(<"$pid_file")"; then
        return
    fi
    mkdir -p "$stage_root/xvfb" "$logs_root" "$process_root"
    nohup "$x11_root/usr/bin/Xvfb" ":$display_number" \
        -screen 0 1600x900x24 \
        -nolisten tcp \
        -fbdir "$stage_root/xvfb" \
        >"$logs_root/xvfb.log" 2>&1 &
    printf '%s\n' "$!" >"$pid_file"
    for _ in {1..100}; do
        if "$x11_root/usr/bin/xdpyinfo" -display ":$display_number" \
            >/dev/null 2>&1; then
            return
        fi
        sleep 0.1
    done
    printf 'error: staged Xvfb did not become ready\n' >&2
    exit 7
}

prepare_client() {
    if [[ $# -ne 8 ]]; then
        printf 'error: prepare-client requires scope instance local-port remote-host remote-port participant-id element discipline\n' >&2
        exit 8
    fi
    local scope="$1"
    local instance="$2"
    local local_port="$3"
    local remote_host="$4"
    local remote_port="$5"
    local participant_id="$6"
    local element="$7"
    local discipline="$8"
    validate_token "$scope"
    validate_token "$instance"
    validate_port "$local_port"
    validate_port "$remote_port"
    [[ "$local_port" == 51611 || "$local_port" == 51612 ]] || {
        printf 'error: remote local port must be 51611 or 51612\n' >&2
        exit 9
    }
    [[ -x "$proton_root/proton" ]]
    [[ -f "$package_root/SolomonDarkMultiplayerBeta.exe" ]]
    [[ -f "$game_root/SolomonDark.exe" ]]
    [[ -d "$package_root/mods/tool.real_flow_e2e_observer" ]]

    local settings_root="$package_root/.sdmod-test-data/$scope/SolomonDarkMultiplayerBeta"
    local peer_runtime="$settings_root/runtime"
    local mod_state="$peer_runtime/instances/$instance/mod-manager-state.json"
    mkdir -p \
        "$settings_root" \
        "$(dirname "$mod_state")" \
        "$prefix_root" \
        "$xdg_root/cache" \
        "$xdg_root/config" \
        "$xdg_root/data" \
        "$tmp_root" \
        "$stage_root/steam-client"
    python3 - "$settings_root/settings.json" "$(windows_path "$game_root")" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
path.write_text(json.dumps({
    "gameDirectory": sys.argv[2],
    "directoryUrl": "https://solomondarker.com",
    "activeSaveSlot": 0,
    "showStockTutorial": False,
    "disableAudio": True,
}, indent=2) + "\n", encoding="utf-8")
PY
    python3 - "$mod_state" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
path.write_text(json.dumps({
    "Mods": {
        "tool.real_flow_e2e_observer": {"Enabled": True}
    }
}, indent=2) + "\n", encoding="utf-8")
PY
    python3 - "$process_root/client.json" \
        "$scope" "$instance" "$local_port" "$remote_host" "$remote_port" \
        "$participant_id" "$element" "$discipline" "$settings_root" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
keys = (
    "scope", "instance", "localPort", "remoteHost", "remotePort",
    "participantId", "element", "discipline", "settingsRoot",
)
path.write_text(json.dumps(dict(zip(keys, sys.argv[2:])), indent=2) + "\n")
PY
}

launch_ui() {
    [[ -f "$process_root/client.json" ]]
    start_xvfb
    x11_env
    eval "$(
        python3 - "$process_root/client.json" <<'PY'
import json
import pathlib
import shlex
import sys

row = json.loads(pathlib.Path(sys.argv[1]).read_text())
for key, value in row.items():
    print(f"{key}={shlex.quote(str(value))}")
PY
    )"
    local executable
    executable="$(windows_path "$package_root/SolomonDarkMultiplayerBeta.exe")"
    nohup env \
        DISPLAY=":$display_number" \
        LIBGL_ALWAYS_SOFTWARE=1 \
        LP_NUM_THREADS=2 \
        STEAM_COMPAT_CLIENT_INSTALL_PATH="$stage_root/steam-client" \
        STEAM_COMPAT_DATA_PATH="$prefix_root" \
        XDG_CACHE_HOME="$xdg_root/cache" \
        XDG_CONFIG_HOME="$xdg_root/config" \
        XDG_DATA_HOME="$xdg_root/data" \
        TMPDIR="$tmp_root" \
        WINEDEBUG=-all \
        WINEFSYNC=1 \
        SDMOD_NETWORK_TELEMETRY=1 \
        SDMOD_DISABLE_AUDIO=1 \
        SDMOD_ENABLE_AUDIO=0 \
        SDMOD_LUA_EXEC_PIPE_NAME="SolomonDarkModLoader_LuaExec_$instance" \
        SDMOD_LUA_EXEC_TARGET_MOD_ID=tool.real_flow_e2e_observer \
        SDMOD_MULTIPLAYER_PLAYER_NAME="client B" \
        SDMOD_MULTIPLAYER_QUICK_START_ELEMENT="$element" \
        SDMOD_MULTIPLAYER_QUICK_START_DISCIPLINE="$discipline" \
        SDMOD_MULTIPLAYER_QUICK_START_RUN= \
        SDMOD_MULTIPLAYER_TRANSPORT=local_udp \
        SDMOD_MULTIPLAYER_ROLE=client \
        SDMOD_MULTIPLAYER_LOCAL_PORT="$localPort" \
        SDMOD_MULTIPLAYER_REMOTE_HOST="$remoteHost" \
        SDMOD_MULTIPLAYER_REMOTE_PORT="$remotePort" \
        SDMOD_MULTIPLAYER_PARTICIPANT_ID="$participantId" \
        "$proton_root/proton" run \
        "$executable" \
        "--test-activation-scope=$scope" \
        >"$logs_root/launcher-ui.log" 2>&1 &
    printf '%s\n' "$!" >"$process_root/launcher-ui.pid"
    sleep 2
    refresh_ledger
}

windows_list() {
    x11_env
    local window=""
    while IFS= read -r window; do
        printf '%s\t' "$window"
        "$x11_root/usr/bin/xdotool" getwindowpid "$window" 2>/dev/null || true
        printf '\t'
        "$x11_root/usr/bin/xdotool" getwindowname "$window" 2>/dev/null || true
        printf '\t'
        "$x11_root/usr/bin/xdotool" getwindowgeometry --shell "$window" \
            2>/dev/null | tr '\n' ' '
        printf '\n'
    done < <("$x11_root/usr/bin/xdotool" search --onlyvisible --name '.*' || true)
    return 0
}

launcher_window() {
    x11_env
    "$x11_root/usr/bin/xdotool" search --onlyvisible \
        --name '^Solomon Dark Revived$' | tail -n 1
}

game_window() {
    x11_env
    "$x11_root/usr/bin/xdotool" search --onlyvisible \
        --name 'SolomonDark' | tail -n 1
}

launcher_click() {
    [[ $# -eq 2 ]]
    x11_env
    local window
    window="$(launcher_window)"
    "$x11_root/usr/bin/xdotool" windowfocus --sync "$window"
    "$x11_root/usr/bin/xdotool" mousemove --window "$window" "$1" "$2" click 1
}

launcher_type() {
    [[ $# -eq 3 ]]
    launcher_click "$1" "$2"
    x11_env
    "$x11_root/usr/bin/xdotool" key ctrl+a
    "$x11_root/usr/bin/xdotool" type --delay 20 -- "$3"
}

launcher_key() {
    [[ $# -eq 1 ]]
    x11_env
    local window
    window="$(launcher_window)"
    "$x11_root/usr/bin/xdotool" windowfocus --sync "$window"
    "$x11_root/usr/bin/xdotool" key --window "$window" "$1"
}

game_click() {
    [[ $# -eq 2 ]]
    [[ -f "$tools_root/win32_real_input.exe" ]]
    [[ -s "$process_root/client.json" ]]
    local helper
    local expected_game
    local expected_game_windows
    local scope
    local instance
    local -a peer_identity=()
    helper="$(windows_path "$tools_root/win32_real_input.exe")"
    mapfile -t peer_identity < <(
        python3 - "$process_root/client.json" <<'PY'
import json
import pathlib
import sys

row = json.loads(pathlib.Path(sys.argv[1]).read_text())
print(row["scope"])
print(row["instance"])
PY
    )
    [[ ${#peer_identity[@]} -eq 2 ]]
    scope="${peer_identity[0]}"
    instance="${peer_identity[1]}"
    validate_token "$scope"
    validate_token "$instance"
    expected_game="$package_root/.sdmod-test-data/$scope/SolomonDarkMultiplayerBeta/runtime/instances/$instance/stage/SolomonDark.exe"
    [[ -f "$expected_game" ]]
    expected_game_windows="$(windows_path "$expected_game")"
    export WINEPREFIX="$prefix_root/pfx"
    export WINEDEBUG=-all
    export WINEFSYNC=1
    "$proton_root/files/bin/wine" \
        "$helper" \
        click-path \
        "$expected_game_windows" \
        "$1" \
        "$2" \
        300
}

invoke_lua() {
    [[ $# -eq 2 ]]
    local instance="$1"
    local encoded="$2"
    validate_token "$instance"
    local code
    code="$(printf '%s' "$encoded" | base64 -d)"
    local client
    client="$(windows_path "$tools_root/win32_lua_exec_client.exe")"
    export WINEPREFIX="$prefix_root/pfx"
    export WINEDEBUG=-all
    export WINEFSYNC=1
    "$proton_root/files/bin/wine" \
        "$client" \
        "SolomonDarkModLoader_LuaExec_$instance" \
        "$code"
}

daemon_lua() {
    [[ $# -eq 1 ]]
    local instance="$1"
    validate_token "$instance"
    local client
    client="$(windows_path "$tools_root/win32_lua_exec_client.exe")"
    export WINEPREFIX="$prefix_root/pfx"
    export WINEDEBUG=-all
    export WINEFSYNC=1
    exec "$proton_root/files/bin/wine" \
        "$client" \
        "SolomonDarkModLoader_LuaExec_$instance" \
        --daemon
}

capture_root() {
    [[ $# -eq 1 ]]
    x11_env
    local name="$1"
    validate_token "$name"
    local target="$evidence_root/$name.xwd"
    "$x11_root/usr/bin/xwd" -root -silent -display ":$display_number" \
        -out "$target"
    printf '%s\t%s\n' "$(date +%s%N)" "$target"
}

capture_png() {
    [[ $# -eq 1 ]]
    local name="$1"
    validate_token "$name"
    local capture_line
    capture_line="$(capture_root "$name")"
    local capture_ns="${capture_line%%$'\t'*}"
    x11_env
    "$x11_root/usr/bin/ffmpeg" \
        -hide_banner \
        -loglevel error \
        -y \
        -i "$evidence_root/$name.xwd" \
        -frames:v 1 \
        "$evidence_root/$name.png"
    printf '%s\t%s\n' "$capture_ns" "$evidence_root/$name.png"
}

pack_artifacts() {
    [[ $# -eq 2 ]]
    local scope="$1"
    local instance="$2"
    validate_token "$scope"
    validate_token "$instance"
    local stage="$package_root/.sdmod-test-data/$scope/SolomonDarkMultiplayerBeta/runtime/instances/$instance/stage"
    local archive="$evidence_root/$instance-runtime.tar"
    local -a members=()
    local relative=""
    for relative in \
        .sdmod/logs/network-telemetry.jsonl \
        .sdmod/logs/solomondarkmodloader.log \
        .sdmod/loader-startup-status.json \
        .sdmod/startup-status.json \
        .sdmod/multiplayer-session-status.json \
        .sdmod/multiplayer-compatibility.json \
        .sdmod/stage-report.json; do
        [[ -f "$stage/$relative" ]] && members+=("$relative")
    done
    if [[ ${#members[@]} -eq 0 ]]; then
        tar -C "$stage" -cf "$archive" --files-from /dev/null
    else
        tar -C "$stage" -cf "$archive" -- "${members[@]}"
    fi
    printf '%s\n' "$archive"
}

session_status() {
    [[ $# -eq 2 ]]
    local scope="$1"
    local instance="$2"
    validate_token "$scope"
    validate_token "$instance"
    local status="$package_root/.sdmod-test-data/$scope/SolomonDarkMultiplayerBeta/runtime/instances/$instance/stage/.sdmod/multiplayer-session-status.json"
    [[ -s "$status" ]] || return 1
    cat "$status"
}

status_owned() {
    refresh_ledger
    while IFS= read -r pid; do
        pid_owned "$pid" || continue
        printf '%s\t' "$pid"
        tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true
        printf '\n'
    done <"$process_root/owned-pids.txt"
    return 0
}

stop_owned() {
    refresh_ledger
    mapfile -t pids <"$process_root/owned-pids.txt"
    for pid in "${pids[@]}"; do
        pid_owned "$pid" && kill -TERM "$pid" 2>/dev/null || true
    done
    for _ in {1..100}; do
        local live=0
        for pid in "${pids[@]}"; do
            pid_owned "$pid" && live=1 && break
        done
        [[ "$live" -eq 0 ]] && break
        sleep 0.1
    done
    for pid in "${pids[@]}"; do
        pid_owned "$pid" && kill -KILL "$pid" 2>/dev/null || true
    done
    sleep 1
    status_owned
    return 0
}

mkdir -p "$process_root" "$logs_root" "$evidence_root"
case "$command_name" in
    bundle-x11) bundle_x11 ;;
    prepare-client) prepare_client "$@" ;;
    launch-ui) launch_ui ;;
    windows) windows_list ;;
    launcher-click) launcher_click "$@" ;;
    launcher-type) launcher_type "$@" ;;
    launcher-key) launcher_key "$@" ;;
    game-click) game_click "$@" ;;
    lua) invoke_lua "$@" ;;
    lua-daemon) daemon_lua "$@" ;;
    capture) capture_root "$@" ;;
    capture-png) capture_png "$@" ;;
    pack-artifacts) pack_artifacts "$@" ;;
    session-status) session_status "$@" ;;
    status) status_owned ;;
    stop) stop_owned ;;
    *)
        printf 'error: unsupported command: %s\n' "$command_name" >&2
        exit 10
        ;;
esac
