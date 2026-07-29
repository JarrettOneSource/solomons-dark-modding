#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
    printf 'usage: %s <remote-root> <launch|lua|lua-daemon|clock-stream|pack-artifacts|status|stop> [args...]\n' "$0" >&2
    exit 2
fi

remote_root="$1"
command_name="$2"
shift 2

case "$remote_root" in
    /root/sd-netlag-[A-Za-z0-9._-]*)
        ;;
    *)
        printf 'error: unsafe remote root: %s\n' "$remote_root" >&2
        exit 3
        ;;
esac

proton_root="$remote_root/proton"
package_root="$remote_root/package"
game_root="$remote_root/game"
runtime_root="$remote_root/runtime"
tools_root="$remote_root/tools"
process_root="$remote_root/processes"
logs_root="$remote_root/logs"
prefix_root="$remote_root/prefix"
xdg_root="$remote_root/xdg"
tmp_root="$remote_root/tmp"

proton_path() {
    local absolute
    absolute="$(realpath "$1")"
    printf 'Z:%s' "$absolute" | sed 's#/#\\#g'
}

validate_instance() {
    [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$ ]] || {
        printf 'error: invalid instance: %s\n' "$1" >&2
        exit 4
    }
}

pid_owned_by_root() {
    local pid="$1"
    [[ "$pid" =~ ^[0-9]+$ && -d "/proc/$pid" ]] || return 1
    local cmdline=""
    local executable=""
    local working_directory=""
    local windows_root="${remote_root//\//\\}"
    if [[ -r "/proc/$pid/cmdline" ]]; then
        cmdline="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
    fi
    executable="$(readlink -f "/proc/$pid/exe" 2>/dev/null || true)"
    working_directory="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
    [[ "$cmdline" == *"$remote_root"* ||
       "$cmdline" == *"$windows_root"* ||
       "$executable" == "$remote_root/"* ||
       "$working_directory" == "$remote_root/"* ]]
}

pid_start_time() {
    local pid="$1"
    [[ "$pid" =~ ^[0-9]+$ && -r "/proc/$pid/stat" ]] || return 1
    awk '{ print $22 }' "/proc/$pid/stat"
}

pid_matches_start_time() {
    local pid="$1"
    local expected_start_time="$2"
    local actual_start_time=""
    actual_start_time="$(pid_start_time "$pid" 2>/dev/null || true)"
    [[ -n "$actual_start_time" &&
       "$actual_start_time" == "$expected_start_time" ]]
}

record_game_identity() {
    local instance="$1"
    local pid="$2"
    local start_time=""
    start_time="$(pid_start_time "$pid")"
    printf '%s\t%s\n' "$pid" "$start_time" \
        >"$process_root/$instance-game.identity"
}

refresh_ledger() {
    local current_pid="$$"
    local parent_pid="$PPID"
    local ledger="$process_root/owned-pids.txt"
    local temporary="$process_root/.owned-pids.$$"
    : >"$temporary"
    for proc_path in /proc/[0-9]*; do
        local pid="${proc_path#/proc/}"
        [[ "$pid" != "$current_pid" && "$pid" != "$parent_pid" ]] || continue
        pid_owned_by_root "$pid" || continue
        printf '%s\n' "$pid" >>"$temporary"
    done
    sort -nu "$temporary" >"$ledger"
    rm -f "$temporary"
}

start_xvfb() {
    local display_number="$1"
    local pid_file="$process_root/xvfb.pid"
    local xvfb_pid=""
    if [[ -f "$pid_file" ]]; then
        xvfb_pid="$(<"$pid_file")"
        if [[ "$xvfb_pid" =~ ^[0-9]+$ ]] &&
            [[ -r "/proc/$xvfb_pid/cmdline" ]] &&
            tr '\0' ' ' <"/proc/$xvfb_pid/cmdline" |
                grep -Fq "$remote_root"; then
            :
        else
            xvfb_pid=""
        fi
    fi

    if [[ -z "$xvfb_pid" ]]; then
        mkdir -p "$remote_root/xvfb"
        nohup Xvfb ":$display_number" \
            -screen 0 1600x900x24 \
            -nolisten tcp \
            -fbdir "$remote_root/xvfb" \
            >"$logs_root/xvfb.log" 2>&1 &
        xvfb_pid="$!"
        printf '%s\n' "$xvfb_pid" >"$pid_file"
    fi

    for _ in {1..100}; do
        if DISPLAY=":$display_number" xdpyinfo >/dev/null 2>&1; then
            return
        fi
        kill -0 "$xvfb_pid" 2>/dev/null || break
        sleep 0.05
    done

    printf 'error: Xvfb display :%s did not become ready\n' "$display_number" >&2
    exit 8
}

launch_peer() {
    if [[ $# -ne 9 ]]; then
        printf 'error: launch requires role local-port remote-host remote-port participant-id player-name instance element discipline\n' >&2
        exit 5
    fi
    local role="$1"
    local local_port="$2"
    local remote_host="$3"
    local remote_port="$4"
    local participant_id="$5"
    local player_name="$6"
    local instance="$7"
    local element="$8"
    local discipline="$9"

    [[ "$role" == host || "$role" == client ]] || {
        printf 'error: invalid role: %s\n' "$role" >&2
        exit 6
    }
    [[ "$local_port" == 51511 || "$local_port" == 51512 ]] || {
        printf 'error: NFO local port must be 51511 or 51512\n' >&2
        exit 9
    }
    if [[ "$role" == client && "$player_name" != "client B" ]]; then
        printf 'error: the remote client must be named client B\n' >&2
        exit 10
    fi
    [[ "$local_port" =~ ^[0-9]+$ && "$local_port" -ge 1024 && "$local_port" -le 65535 ]]
    [[ "$remote_port" =~ ^[0-9]+$ && "$remote_port" -ge 1024 && "$remote_port" -le 65535 ]]
    validate_instance "$instance"
    refresh_ledger
    if [[ -s "$process_root/owned-pids.txt" ]]; then
        printf 'error: owned NFO processes are still running; refusing to replace an instance\n' >&2
        exit 14
    fi
    [[ -x "$proton_root/proton" ]]
    [[ -f "$package_root/launcher/SolomonDarkModLauncher.exe" ]]
    [[ -f "$game_root/SolomonDark.exe" ]]
    [[ -f "$tools_root/bot-settings-$role.json" ]]

    local instance_root="$runtime_root/instances/$instance"
    rm -rf -- "$instance_root"

    mkdir -p \
        "$process_root" \
        "$logs_root" \
        "$instance_root/stage/.sdmod/mod-settings" \
        "$prefix_root" \
        "$xdg_root/cache" \
        "$xdg_root/config" \
        "$xdg_root/data" \
        "$tmp_root" \
        "$remote_root/evidence" \
        "$remote_root/steam-client"
    cp \
        "$tools_root/bot-settings-$role.json" \
        "$instance_root/stage/.sdmod/mod-settings/bot.brain.json"
    python3 - "$instance_root/mod-manager-state.json" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(
    json.dumps(
        {
            "Mods": {
                "harness.remote_latency_controller": {
                    "Enabled": True
                },
                "bot.brain": {"Enabled": True},
            }
        },
        indent=2,
    ) + "\n",
    encoding="utf-8",
)
PY

    local display_number=97
    start_xvfb "$display_number"
    local launcher_log="$logs_root/$instance-launch.log"
    local launcher_pid_path="$process_root/$instance-launcher.pid"
    local launcher
    launcher="$(proton_path "$package_root/launcher/SolomonDarkModLauncher.exe")"
    local game
    game="$(proton_path "$game_root")"
    local runtime
    runtime="$(proton_path "$runtime_root")"

    nohup env \
        DISPLAY=":$display_number" \
        LIBGL_ALWAYS_SOFTWARE=1 \
        LP_NUM_THREADS=4 \
        STEAM_COMPAT_CLIENT_INSTALL_PATH="$remote_root/steam-client" \
        STEAM_COMPAT_DATA_PATH="$prefix_root" \
        XDG_CACHE_HOME="$xdg_root/cache" \
        XDG_CONFIG_HOME="$xdg_root/config" \
        XDG_DATA_HOME="$xdg_root/data" \
        TMPDIR="$tmp_root" \
        WINEDEBUG=-all \
        WINEFSYNC=1 \
        SDMOD_UI_SANDBOX_PRESET=idle \
        SDMOD_LUA_EXEC_PIPE_NAME="SolomonDarkModLoader_LuaExec_$instance" \
        SDMOD_LUA_EXEC_TARGET_MOD_ID=harness.remote_latency_controller \
        SDMOD_MULTIPLAYER_QUICK_START= \
        SDMOD_MULTIPLAYER_QUICK_START_ELEMENT= \
        SDMOD_MULTIPLAYER_QUICK_START_DISCIPLINE= \
        SDMOD_MULTIPLAYER_QUICK_START_RUN= \
        SDMOD_MULTIPLAYER_MAX_PARTICIPANTS=4 \
        SDMOD_MULTIPLAYER_TRANSPORT=local_udp \
        SDMOD_MULTIPLAYER_ROLE="$role" \
        SDMOD_MULTIPLAYER_LOCAL_PORT="$local_port" \
        SDMOD_MULTIPLAYER_REMOTE_HOST="$remote_host" \
        SDMOD_MULTIPLAYER_REMOTE_PORT="$remote_port" \
        SDMOD_MULTIPLAYER_PARTICIPANT_ID="$participant_id" \
        SDMOD_MULTIPLAYER_PLAYER_NAME="$player_name" \
        SDMOD_DISABLE_AUDIO=1 \
        SDMOD_ENABLE_AUDIO=0 \
        SDMOD_NETWORK_TELEMETRY=1 \
        "$proton_root/proton" run \
        "$launcher" \
        --json \
        launch \
        --instance "$instance" \
        --runtime-root "$runtime" \
        --game-dir "$game" \
        --runtime-flag multiplayer.steam_bootstrap=false \
        --temporary-profile \
        --disable-audio \
        >"$launcher_log" 2>&1 &
    printf '%s\n' "$!" >"$launcher_pid_path"

    local game_executable="$instance_root/stage/SolomonDark.exe"
    local game_pid=""
    for _ in {1..150}; do
        if [[ -f "$game_executable" ]]; then
            local game_windows_path
            game_windows_path="$(proton_path "$game_executable")"
            for proc_path in /proc/[0-9]*; do
                local candidate_pid="${proc_path#/proc/}"
                local candidate_cmdline=""
                [[ -r "/proc/$candidate_pid/cmdline" ]] || continue
                candidate_cmdline="$(
                    tr '\0' ' ' <"/proc/$candidate_pid/cmdline" \
                        2>/dev/null || true
                )"
                if [[ "$candidate_cmdline" == *"$game_windows_path"* ]]; then
                    game_pid="$candidate_pid"
                    break
                fi
            done
        fi
        [[ -n "$game_pid" ]] && break
        sleep 0.1
    done
    if [[ -z "$game_pid" ]]; then
        printf 'error: staged game process did not start\n' >&2
        tail -40 "$launcher_log" >&2 || true
        stop_owned >/dev/null || true
        exit 15
    fi

    record_game_identity "$instance" "$game_pid"
    local startup_status="$instance_root/stage/.sdmod/startup-status.json"
    local startup_ready=0
    for _ in {1..150}; do
        if ! kill -0 "$game_pid" 2>/dev/null; then
            printf 'error: staged game process exited during onboarding\n' >&2
            tail -80 "$launcher_log" >&2 || true
            stop_owned >/dev/null || true
            exit 16
        fi
        if find "$instance_root/stage/.sdmod/logs" \
            -maxdepth 1 \
            -type f \
            -iname '*crash*' \
            -size +0c \
            -print -quit 2>/dev/null |
            grep -q .; then
            printf 'error: staged game produced a crash artifact during onboarding\n' >&2
            tail -80 "$instance_root/stage/.sdmod/logs/solomondarkmodloader.crash.log" \
                >&2 2>/dev/null || true
            stop_owned >/dev/null || true
            exit 17
        fi
        if [[ -s "$startup_status" ]]; then
            if python3 - "$startup_status" "$role" <<'PY'
import json
import pathlib
import sys

status = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
role = sys.argv[2]
if status.get("completed") is not True:
    raise SystemExit(2)
ready = (
    status.get("success") is True
    and status.get("multiplayerFoundationReady") is True
    and status.get("botRuntimeInitialized") is True
    and status.get("luaEngineInitialized") is True
    and status.get("luaLoadedModCount", 0) >= 2
    and (
        role != "host"
        or status.get("runtimeTickServiceRunning") is True
    )
)
raise SystemExit(0 if ready else 1)
PY
            then
                startup_ready=1
                break
            else
                startup_result="$?"
                if [[ "$startup_result" -eq 2 ]]; then
                    sleep 0.1
                    continue
                fi
                printf 'error: loader startup completed without the required multiplayer runtime\n' >&2
                python3 - "$startup_status" <<'PY' >&2
import json
import pathlib
import sys

status = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
fields = (
    "completed",
    "success",
    "multiplayerFoundationReady",
    "botRuntimeInitialized",
    "luaEngineInitialized",
    "luaLoadedModCount",
    "runtimeTickServiceRunning",
    "message",
)
print(json.dumps({key: status.get(key) for key in fields}, sort_keys=True))
PY
                tail -80 \
                    "$instance_root/stage/.sdmod/logs/solomondarkmodloader.log" \
                    >&2 2>/dev/null || true
                stop_owned >/dev/null || true
                exit 18
            fi
        fi
        sleep 0.1
    done
    if [[ "$startup_ready" -ne 1 ]]; then
        printf 'error: loader startup status did not become ready\n' >&2
        tail -80 "$launcher_log" >&2 || true
        tail -80 \
            "$instance_root/stage/.sdmod/logs/solomondarkmodloader.log" \
            >&2 2>/dev/null || true
        stop_owned >/dev/null || true
        exit 19
    fi

    refresh_ledger
    printf '{"role":"%s","instance":"%s","launcherPid":%s,"gamePid":%s,"localPort":%s,"remotePort":%s,"runtimeReady":true}\n' \
        "$role" "$instance" "$(<"$launcher_pid_path")" "$game_pid" \
        "$local_port" "$remote_port"
}

invoke_lua() {
    if [[ $# -ne 2 ]]; then
        printf 'error: lua requires instance and base64 code\n' >&2
        exit 7
    fi
    local instance="$1"
    local encoded="$2"
    validate_instance "$instance"
    local code
    code="$(printf '%s' "$encoded" | base64 -d)"
    local client_win
    client_win="$(proton_path "$tools_root/win32_lua_exec_client.exe")"
    export WINEPREFIX="$prefix_root/pfx"
    export WINEDEBUG=-all
    export WINEFSYNC=1
    "$proton_root/files/bin/wine" \
        "$client_win" \
        "SolomonDarkModLoader_LuaExec_$instance" \
        "$code"
}

daemon_lua() {
    if [[ $# -ne 1 ]]; then
        printf 'error: lua-daemon requires instance\n' >&2
        exit 11
    fi
    local instance="$1"
    validate_instance "$instance"
    local client_win
    client_win="$(proton_path "$tools_root/win32_lua_exec_client.exe")"
    export WINEPREFIX="$prefix_root/pfx"
    export WINEDEBUG=-all
    export WINEFSYNC=1
    exec "$proton_root/files/bin/wine" \
        "$client_win" \
        "SolomonDarkModLoader_LuaExec_$instance" \
        --daemon
}

stream_clock() {
    local request=""
    while IFS= read -r request; do
        if [[ "$request" != "now" ]]; then
            printf 'ERROR\tunexpected clock request\n'
            continue
        fi
        printf 'OK\t%s\n' "$(date +%s%N)"
    done
}

pack_artifacts() {
    if [[ $# -ne 1 ]]; then
        printf 'error: pack-artifacts requires instance\n' >&2
        exit 12
    fi
    local instance="$1"
    validate_instance "$instance"
    local stage="$runtime_root/instances/$instance/stage"
    [[ -d "$stage" ]] || {
        printf 'error: staged instance was not found: %s\n' "$stage" >&2
        exit 13
    }
    local evidence_root="$remote_root/evidence"
    local archive="$evidence_root/$instance-artifacts.tar"
    mkdir -p "$evidence_root"
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
    while IFS= read -r -d '' crash_path; do
        members+=("${crash_path#"$stage/"}")
    done < <(
        find "$stage/.sdmod/logs" \
            -maxdepth 1 \
            -type f \
            -iname '*crash*' \
            -print0 2>/dev/null || true
    )
    while IFS= read -r -d '' screenshot_path; do
        members+=("${screenshot_path#"$stage/"}")
    done < <(
        find "$stage/.sdmod/logs" \
            -maxdepth 1 \
            -type f \
            -name 'netlag-wave-*.bmp' \
            -print0 2>/dev/null || true
    )
    if [[ ${#members[@]} -eq 0 ]]; then
        tar -C "$stage" -cf "$archive" --files-from /dev/null
    else
        tar -C "$stage" -cf "$archive" -- "${members[@]}"
    fi
    printf '%s\n' "$archive"
}

status_owned() {
    refresh_ledger
    local listed=" "
    while IFS= read -r pid; do
        pid_owned_by_root "$pid" || continue
        printf '%s\t' "$pid"
        tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true
        printf '\n'
        listed+="$pid "
    done <"$process_root/owned-pids.txt"
    local identity_file=""
    for identity_file in "$process_root"/*-game.identity; do
        [[ -f "$identity_file" ]] || continue
        local pid=""
        local start_time=""
        IFS=$'\t' read -r pid start_time <"$identity_file"
        if [[ "$listed" != *" $pid "* ]] &&
            pid_matches_start_time "$pid" "$start_time"; then
            printf '%s\trecorded-game:%s\n' \
                "$pid" "${identity_file##*/}"
        fi
    done
}

stop_owned() {
    refresh_ledger
    mapfile -t owned_pids <"$process_root/owned-pids.txt"
    local -A owned_start_times=()
    for pid in "${owned_pids[@]}"; do
        owned_start_times["$pid"]="$(pid_start_time "$pid")"
    done

    local -a game_pids=()
    local identity_file=""
    for identity_file in "$process_root"/*-game.identity; do
        [[ -f "$identity_file" ]] || continue
        local game_pid=""
        local game_start_time=""
        IFS=$'\t' read -r game_pid game_start_time <"$identity_file"
        if pid_matches_start_time "$game_pid" "$game_start_time"; then
            owned_start_times["$game_pid"]="$game_start_time"
            game_pids+=("$game_pid")
            kill -TERM "$game_pid" 2>/dev/null || true
        fi
    done
    for _ in {1..50}; do
        local live=0
        for pid in "${game_pids[@]}"; do
            if pid_matches_start_time \
                "$pid" "${owned_start_times[$pid]:-}"; then
                live=1
                break
            fi
        done
        [[ "$live" -eq 0 ]] && break
        sleep 0.1
    done
    for pid in "${game_pids[@]}"; do
        pid_matches_start_time \
            "$pid" "${owned_start_times[$pid]:-}" || continue
        kill -KILL "$pid" 2>/dev/null || true
    done

    env \
        WINEPREFIX="$prefix_root/pfx" \
        WINEDEBUG=-all \
        "$proton_root/files/bin/wineserver" -k \
        >/dev/null 2>&1 || true

    for pid in "${owned_pids[@]}"; do
        [[ " ${game_pids[*]} " == *" $pid "* ]] && continue
        pid_matches_start_time \
            "$pid" "${owned_start_times[$pid]}" || continue
        kill -TERM "$pid" 2>/dev/null || true
    done
    for _ in {1..50}; do
        local live=0
        for pid in "${owned_pids[@]}"; do
            if pid_matches_start_time \
                "$pid" "${owned_start_times[$pid]}"; then
                live=1
                break
            fi
        done
        [[ "$live" -eq 0 ]] && break
        sleep 0.1
    done
    for pid in "${owned_pids[@]}"; do
        pid_matches_start_time \
            "$pid" "${owned_start_times[$pid]}" || continue
        kill -KILL "$pid" 2>/dev/null || true
    done
    for _ in {1..50}; do
        local live=0
        for pid in "${owned_pids[@]}"; do
            if pid_matches_start_time \
                "$pid" "${owned_start_times[$pid]}"; then
                live=1
                break
            fi
        done
        [[ "$live" -eq 0 ]] && break
        sleep 0.1
    done
    for identity_file in "$process_root"/*-game.identity; do
        [[ -f "$identity_file" ]] || continue
        local game_pid=""
        local game_start_time=""
        IFS=$'\t' read -r game_pid game_start_time <"$identity_file"
        if ! pid_matches_start_time "$game_pid" "$game_start_time"; then
            rm -f -- "$identity_file"
        fi
    done
    refresh_ledger
    status_owned
}

mkdir -p "$process_root" "$logs_root"
case "$command_name" in
    launch)
        launch_peer "$@"
        ;;
    lua)
        invoke_lua "$@"
        ;;
    lua-daemon)
        daemon_lua "$@"
        ;;
    clock-stream)
        stream_clock
        ;;
    pack-artifacts)
        pack_artifacts "$@"
        ;;
    status)
        status_owned
        ;;
    stop)
        stop_owned
        ;;
    *)
        printf 'error: unsupported command: %s\n' "$command_name" >&2
        exit 8
        ;;
esac
