#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
client="$root/runtime/tools/win32_lua_exec_client.exe"
proton_root="${SDMOD_PROTON_ROOT:-$HOME/.local/share/Steam/compatibilitytools.d/GE-Proton11-1}"
compat_data="${SDMOD_STEAM_COMPAT_DATA:-$HOME/.local/share/Steam/steamapps/compatdata/480}"
pipe_name="${SDMOD_WSL_LUA_PIPE_NAME:-SolomonDarkModLoader_LuaExec}"

if [[ $# -gt 1 ]]; then
    printf 'usage: %s [lua-code|--daemon]\n' "$0" >&2
    exit 2
fi
if [[ $# -eq 1 ]]; then
    code="$1"
else
    code="$(</dev/stdin)"
fi
if [[ -z "$code" ]]; then
    exit 0
fi

if [[ ! -f "$client" ]]; then
    powershell.exe -NoProfile -ExecutionPolicy Bypass \
        -File "$root/scripts/Build-Win32LuaExecClient.ps1" >/dev/null
fi
wine="$proton_root/files/bin/wine"
if [[ ! -x "$wine" ]]; then
    printf 'error: Proton Wine executable not found: %s\n' "$wine" >&2
    exit 3
fi

client_win="$(printf 'Z:%s' "$(realpath "$client")" | sed 's#/#\\#g')"
export WINEPREFIX="$compat_data/pfx"
export WINEDEBUG=-all
exec "$wine" "$client_win" "$pipe_name" "$code"
