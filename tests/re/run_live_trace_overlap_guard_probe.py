#!/usr/bin/env python3
"""Live regression for safe runtime trace placement around loader detours."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import cast_state_probe as csp  # noqa: E402


OUTPUT_PATH = ROOT / "runtime" / "live_trace_overlap_guard_probe.json"
TRACE_DISPATCH_BODY_KEY = "trace_spell_cast_dispatcher_body"
TRACE_3EF_BODY_KEY = "trace_spell_cast_3ef_body"


class LiveTraceOverlapGuardProbeFailure(RuntimeError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print the full result payload.")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--keep-running", action="store_true")
    return parser


def int_value(values: dict[str, str], key: str, default: int = 0) -> int:
    raw = values.get(key)
    if raw is None or raw == "":
        return default
    try:
        if raw.lower().startswith("0x"):
            return int(raw, 16)
        return int(raw)
    except ValueError:
        return default


def bool_value(values: dict[str, str], key: str) -> bool:
    return values.get(key, "").lower() == "true"


def run_trace_overlap_probe(timeout_s: float) -> dict[str, Any]:
    result: dict[str, Any] = {
        "launcher_freshness": csp.ensure_launcher_bundle_fresh(),
        "dispatch_body_address": csp.read_runtime_layout_offset(TRACE_DISPATCH_BODY_KEY),
        "spell_3ef_body_address": csp.read_runtime_layout_offset(TRACE_3EF_BODY_KEY),
    }
    csp.stop_game()
    csp.clear_loader_log()
    csp.launch_game()
    csp.wait_for_lua_pipe(timeout_s=timeout_s)

    dispatch_body = int(result["dispatch_body_address"])
    spell_3ef_body = int(result["spell_3ef_body_address"])
    values = csp.parse_key_values(
        csp.run_lua(
            f"""
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end

local dispatch_body = {dispatch_body}
local spell_3ef_body = {spell_3ef_body}
local overlap_name = "live_trace_overlap_guard_dispatch"
local clean_name = "live_trace_overlap_guard_3ef"

pcall(sd.debug.untrace_function, dispatch_body)
pcall(sd.debug.untrace_function, spell_3ef_body)
sd.debug.clear_trace_hits(overlap_name)
sd.debug.clear_trace_hits(clean_name)

local overlap_ok = sd.debug.trace_function(dispatch_body, overlap_name, 6)
local overlap_error = sd.debug.get_last_error()
local clean_ok = sd.debug.trace_function(spell_3ef_body, clean_name, 5)
local clean_error = sd.debug.get_last_error()
pcall(sd.debug.untrace_function, spell_3ef_body)

local traces = sd.debug.list_traces() or {{}}
local active_overlap = 0
local active_clean = 0
local inactive_clean = 0
for _, trace in ipairs(traces) do
  if trace.name == overlap_name and trace.active == true then
    active_overlap = active_overlap + 1
  end
  if trace.name == clean_name and trace.active == true then
    active_clean = active_clean + 1
  end
  if trace.name == clean_name and trace.active ~= true then
    inactive_clean = inactive_clean + 1
  end
end

emit("overlap_ok", overlap_ok)
emit("overlap_error", overlap_error)
emit("clean_ok", clean_ok)
emit("clean_error", clean_error)
emit("active_overlap", active_overlap)
emit("active_clean_after_untrace", active_clean)
emit("inactive_clean_after_untrace", inactive_clean)
""".strip(),
            timeout_s=timeout_s,
        )
    )
    result["values"] = values

    overlap_rejected = not bool_value(values, "overlap_ok")
    overlap_error = values.get("overlap_error", "")
    clean_trace_armed = bool_value(values, "clean_ok")
    clean_trace_disarmed = int_value(values, "active_clean_after_untrace") == 0
    result["validation"] = {
        "overlap_rejected": overlap_rejected,
        "overlap_error_mentions_relative_jump": "relative jump patch" in overlap_error,
        "clean_trace_armed": clean_trace_armed,
        "clean_trace_disarmed_by_original_address": clean_trace_disarmed,
        "no_active_overlap_trace": int_value(values, "active_overlap") == 0,
    }
    result["ok"] = all(result["validation"].values())
    if not result["ok"]:
        raise LiveTraceOverlapGuardProbeFailure(json.dumps(result, indent=2, sort_keys=True))
    return result


def main() -> int:
    args = build_parser().parse_args()
    result: dict[str, Any]
    try:
        result = run_trace_overlap_probe(args.timeout)
    except Exception as exc:
        result = {"ok": False, "error": str(exc), "loader_log_tail": csp.tail_loader_log(160)}
    finally:
        if not args.keep_running:
            csp.stop_game()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "ok": result.get("ok"),
                    "validation": result.get("validation"),
                    "error": result.get("error"),
                    "output": str(args.output),
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
