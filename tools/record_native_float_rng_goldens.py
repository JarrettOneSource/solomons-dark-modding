#!/usr/bin/env python3
"""Capture bit-exact native float RNG goldens from one disposable solo game.

The loader seam is present only when
``SDMOD_NATIVE_FLOAT_RNG_CAPTURE_DIRECTORY`` is set. Each request constructs a
private retail RNG object, records its complete state before and after every
call, and writes the raw recording outside the repository. This driver then
replays the recovered recurrence independently before it writes the committed
fixture.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import record_native_sim_goldens as native_sim  # noqa: E402
import verify_local_multiplayer_sync as local_sync  # noqa: E402


DEFAULT_INSTANCE = "gfx-goldfix-rng"
DEFAULT_PORTS = (52341, 52342)
DEFAULT_EVIDENCE_DIRECTORY = Path("D:/codex-evidence/goldfix-20260805")
DEFAULT_OUTPUT = ROOT / "tests/fixtures/webgame/float-rng-goldens.json"
RUNTIME_ROOT = ROOT / "runtime/goldfix-float-rng-live"
MOD_ID = "sample.lua.rng_lab"
MASK = 0x3FFFFFFF
WORD_COUNT = 55
DIVISOR = 100000
DIVISOR_OFFSET = "0xE4"
CONSTRUCTOR_ADDRESS = "0x00401110"
SCALED_ADDRESS = "0x00401310"
UNIT_ADDRESS = "0x004011F0"


CAPTURE_REQUESTS = (
    {
        "label": "scaled-magnitude-1-unsigned",
        "seed": 1,
        "primitive": "scaled",
        "magnitude": 1.0,
        "signed": False,
        "count": 256,
    },
    {
        "label": "scaled-magnitude-3-unsigned",
        "seed": 19088743,
        "primitive": "scaled",
        "magnitude": 3.0,
        "signed": False,
        "count": 256,
    },
    {
        "label": "scaled-magnitude-4_5-signed",
        "seed": MASK,
        "primitive": "scaled",
        "magnitude": 4.5,
        "signed": True,
        "count": 256,
    },
    {
        "label": "scaled-endpoint-zero",
        "seed": 20001,
        "primitive": "scaled",
        "magnitude": 3.0,
        "signed": False,
        "count": 1,
    },
    {
        "label": "scaled-endpoint-positive",
        "seed": 33700,
        "primitive": "scaled",
        "magnitude": 4.5,
        "signed": False,
        "count": 1,
    },
    {
        "label": "unit-unsigned",
        "seed": 1,
        "primitive": "unit",
        "magnitude": 1.0,
        "signed": False,
        "count": 256,
    },
    {
        "label": "unit-signed",
        "seed": 19088743,
        "primitive": "unit",
        "magnitude": 1.0,
        "signed": True,
        "count": 256,
    },
    {
        "label": "unit-endpoint-zero",
        "seed": 20001,
        "primitive": "unit",
        "magnitude": 1.0,
        "signed": False,
        "count": 1,
    },
    {
        "label": "unit-endpoint-positive",
        "seed": 33700,
        "primitive": "unit",
        "magnitude": 1.0,
        "signed": False,
        "count": 1,
    },
)


class CaptureFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CaptureFailure(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_text(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20.0,
        check=False,
    )
    require(
        completed.returncode == 0,
        f"git {' '.join(arguments)} failed: {completed.stderr.strip()}",
    )
    return completed.stdout.strip()


def f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def f32_bits(value: float) -> str:
    bits = struct.unpack("<I", struct.pack("<f", value))[0]
    return f"0x{bits:08X}"


def initial_state(seed: int) -> dict[str, Any]:
    words = [seed & MASK, 1]
    while len(words) < WORD_COUNT:
        words.append((words[-1] + words[-2]) & MASK)
    return {
        "index_a": 0,
        "index_b": 31,
        "state_words": words,
        "divisor": DIVISOR,
    }


def stream_word(state: dict[str, Any]) -> int:
    index_a = int(state["index_a"])
    index_b = int(state["index_b"])
    words = state["state_words"]
    value = (int(words[index_a]) + int(words[index_b])) & MASK
    words[index_a] = value
    state["index_a"] = (index_a + 1) % WORD_COUNT
    state["index_b"] = (index_b + 1) % WORD_COUNT
    return value


def bounded_integer(state: dict[str, Any], bound: int) -> int:
    power = 2
    while power < bound:
        power *= 2
    return ((stream_word(state) >> 6) & (power - 1)) % bound


def expected_float_bits(
    state: dict[str, Any],
    primitive: str,
    magnitude: float,
    signed_request: bool,
) -> tuple[str, int]:
    draw = bounded_integer(state, DIVISOR + 1)
    quotient = f32(f32(float(draw)) / DIVISOR)
    value = quotient if primitive == "unit" else f32(quotient * f32(magnitude))
    if signed_request and ((stream_word(state) >> 6) & 1) != 0:
        value = f32(-value)
    return f32_bits(value), draw


def normalized_state(value: Any, label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} is not an object")
    words = value.get("state_words")
    require(
        isinstance(words, list) and len(words) == WORD_COUNT,
        f"{label} does not contain exactly 55 state words",
    )
    state = {
        "index_a": int(value.get("index_a", -1)),
        "index_b": int(value.get("index_b", -1)),
        "state_words": [int(word) for word in words],
        "divisor": int(value.get("divisor", -1)),
    }
    require(
        0 <= state["index_a"] < WORD_COUNT and
        0 <= state["index_b"] < WORD_COUNT,
        f"{label} ring indices are outside the 55-word stream",
    )
    require(
        all(0 <= word <= MASK for word in state["state_words"]),
        f"{label} contains a state word outside the native 30-bit mask",
    )
    require(
        state["divisor"] == DIVISOR,
        f"{label} does not preserve the per-object divisor 100000",
    )
    return state


def verify_raw_recording(
    raw: Any,
    request: dict[str, Any],
    instance: str,
) -> dict[str, Any]:
    label = str(request["label"])
    require(isinstance(raw, dict), f"raw recording {label} is not an object")
    require(
        raw.get("schema") == "solomon-dark-native-float-rng-recording-v1",
        f"raw recording {label} has the wrong schema",
    )
    header = raw.get("header")
    require(isinstance(header, dict), f"raw recording {label} has no header")
    require(
        header.get("recorded_live") is True and header.get("instance") == instance,
        f"raw recording {label} is not tied to the requested live instance",
    )
    require(
        header.get("constructor_preferred_address") == CONSTRUCTOR_ADDRESS,
        f"raw recording {label} did not call the retail RNG constructor",
    )
    expected_primitive_address = (
        SCALED_ADDRESS if request["primitive"] == "scaled" else UNIT_ADDRESS
    )
    require(
        header.get("primitive_preferred_address") == expected_primitive_address,
        f"raw recording {label} called the wrong native float primitive",
    )
    require(
        header.get("state_size_bytes") == 0xE8 and
        header.get("divisor_offset") == "0x000000E4",
        f"raw recording {label} did not preserve the 0xE8 state and +0xE4 divisor",
    )

    raw_request = raw.get("request")
    require(isinstance(raw_request, dict), f"raw recording {label} has no request")
    expected_request = {
        "label": label,
        "seed": request["seed"],
        "primitive": request["primitive"],
        "magnitude_float32_bits": f32_bits(float(request["magnitude"])),
        "magnitude_source": (
            "request" if request["primitive"] == "scaled" else "implicit-unit"
        ),
        "signed": request["signed"],
        "count": request["count"],
    }
    require(
        raw_request == expected_request,
        f"raw recording {label} request differs from the capture plan",
    )

    draws = raw.get("draws")
    require(
        isinstance(draws, list) and len(draws) == request["count"],
        f"raw recording {label} did not return its requested draw count",
    )
    model_state = initial_state(int(request["seed"]))
    divergent_indices: list[int] = []
    sampled_integers: list[int] = []
    for index, item in enumerate(draws):
        require(isinstance(item, dict), f"{label} draw {index} is not an object")
        require(
            item.get("draw_index") == index,
            f"{label} draw order is not contiguous at index {index}",
        )
        pre_call = normalized_state(item.get("pre_call"), f"{label} draw {index} pre-call")
        require(
            pre_call == model_state,
            f"{label} draw {index} pre-call state does not continue the retail stream",
        )
        per_draw_request = item.get("request")
        require(
            per_draw_request == {
                "magnitude_float32_bits": expected_request["magnitude_float32_bits"],
                "signed": request["signed"],
            },
            f"{label} draw {index} request parameters changed mid-sequence",
        )
        expected_bits, sampled_integer = expected_float_bits(
            model_state,
            str(request["primitive"]),
            float(request["magnitude"]),
            bool(request["signed"]),
        )
        sampled_integers.append(sampled_integer)
        require(
            item.get("returned_float32_bits") == expected_bits,
            f"{label} draw {index} returned bits do not match native float32 rounding",
        )
        post_call = normalized_state(
            item.get("post_call"), f"{label} draw {index} post-call"
        )
        require(
            post_call == model_state,
            f"{label} draw {index} post-call state has the wrong stream-word cost",
        )
        if request["primitive"] == "scaled":
            naive = f32(sampled_integer / DIVISOR * float(request["magnitude"]))
            native = f32(
                f32(f32(float(sampled_integer)) / DIVISOR) *
                f32(float(request["magnitude"]))
            )
            if f32_bits(naive) != f32_bits(native):
                divergent_indices.append(index)

    return {
        "divergent_draw_indices": divergent_indices,
        "sampled_integers": sampled_integers,
    }


def process_is_running(process_id: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(process_id, 0)
            return True
        except OSError:
            return False

    process_query_limited_information = 0x1000
    still_active = 259
    error_invalid_parameter = 87
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint32,
    )
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetExitCodeProcess.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
    )
    kernel32.GetExitCodeProcess.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_int

    handle = kernel32.OpenProcess(
        process_query_limited_information,
        False,
        process_id,
    )
    if not handle:
        error = ctypes.get_last_error()
        if error == error_invalid_parameter:
            return False
        raise CaptureFailure(
            f"could not query owned process {process_id}: Windows error {error}"
        )
    try:
        exit_code = ctypes.c_uint32()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            raise CaptureFailure(
                f"could not read owned process {process_id} exit state: "
                f"Windows error {ctypes.get_last_error()}"
            )
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def wait_for_runnable_capture_pipe(
    session: native_sim.OwnedSoloSession,
    timeout: float = 60.0,
) -> None:
    status_path = session.stage_root / ".sdmod/startup-status.json"
    deadline = time.monotonic() + timeout
    last_busy = "startup status has not appeared"
    while time.monotonic() < deadline:
        for process_id in session.process_ids:
            require(
                process_is_running(process_id),
                f"capture process {process_id} exited before the Lua pipe became runnable",
            )
        if status_path.is_file():
            try:
                status = json.loads(status_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as error:
                last_busy = f"startup status is being published: {error}"
            else:
                if status.get("completed") is True and status.get("success") is not True:
                    raise CaptureFailure(
                        "loader startup is broken, not busy: "
                        f"{status.get('code')}: {status.get('message')}"
                    )
                last_busy = (
                    f"loader status {status.get('code')}: {status.get('message')}"
                )
        try:
            response = session.lua(
                "return type(sd.debug.capture_native_float_rng)", timeout=5.0
            ).strip()
        except (local_sync.VerifyFailure, subprocess.TimeoutExpired):
            time.sleep(0.2)
            continue
        require(
            response == "function",
            "Lua is runnable but the requested native float RNG capture function is absent",
        )
        return
    raise CaptureFailure(
        f"native float RNG capture remained busy for {timeout:.0f}s: {last_busy}"
    )


def invoke_capture(
    session: native_sim.OwnedSoloSession,
    request: dict[str, Any],
) -> Path:
    lua_arguments = ", ".join(
        (
            json.dumps(request["label"]),
            str(request["seed"]),
            json.dumps(request["primitive"]),
            repr(request["magnitude"]),
            "true" if request["signed"] else "false",
            str(request["count"]),
        )
    )
    values = session.values(
        f"""
local capture = sd.debug.capture_native_float_rng
if type(capture) ~= 'function' then
  print('state=broken')
  print('detail=capture_function_absent')
  return
end
local ok, detail = capture({lua_arguments})
print('state=' .. tostring(ok and 'complete' or 'broken'))
print('detail=' .. tostring(detail))
""",
        timeout=90.0,
    )
    require(
        values.get("state") == "complete",
        f"capture {request['label']} was broken: {values.get('detail', values)}",
    )
    detail = values.get("detail", "")
    require(detail != "", f"capture {request['label']} returned no output path")
    path = Path(detail)
    require(path.is_file(), f"capture {request['label']} output is not runnable: {path}")
    return path


def capture_fixture(
    evidence_directory: Path,
    output: Path,
    instance: str,
    ports: tuple[int, int],
) -> dict[str, Any]:
    require(instance.startswith("gfx-"), "capture instance must use the gfx-* namespace")
    require(
        all(52341 <= port <= 52348 for port in ports) and ports[0] != ports[1],
        "capture ports must be two distinct values in 52341-52348",
    )
    require(
        git_text("status", "--porcelain", "--untracked-files=no") == "",
        "tracked worktree must be clean before live capture",
    )
    require(native_sim.GAME_BINARY.is_file(), f"game executable missing: {native_sim.GAME_BINARY}")
    require(native_sim.LOADER.is_file(), f"Release loader missing: {native_sim.LOADER}")
    require(native_sim.STAGED_LOADER.is_file(), f"staged loader missing: {native_sim.STAGED_LOADER}")
    require(
        sha256_file(native_sim.LOADER) == sha256_file(native_sim.STAGED_LOADER),
        "staged loader differs from the Release capture build",
    )

    raw_directory = evidence_directory / "raw/float-rng"
    raw_directory.mkdir(parents=True, exist_ok=True)
    expected_paths = {
        str(request["label"]): raw_directory / f"{request['label']}.json"
        for request in CAPTURE_REQUESTS
    }
    collisions = [str(path) for path in expected_paths.values() if path.exists()]
    require(
        not collisions,
        "capture refuses ambiguous existing raw recordings: " + ", ".join(collisions),
    )

    source = {
        "base_commit_sha": git_text("rev-parse", "HEAD"),
        "base_tree_sha": git_text("rev-parse", "HEAD^{tree}"),
        "game_executable_sha256": sha256_file(native_sim.GAME_BINARY),
        "loader_dll_sha256": sha256_file(native_sim.STAGED_LOADER),
    }
    native_sim.RUNTIME_ROOT = RUNTIME_ROOT
    session = native_sim.OwnedSoloSession(
        instance=instance,
        ports=ports,
        mod_id=MOD_ID,
        participant_id="goldfix-float-rng",
        test_blank_boneyard=False,
    )
    previous_capture_directory = os.environ.get(
        "SDMOD_NATIVE_FLOAT_RNG_CAPTURE_DIRECTORY"
    )
    os.environ["SDMOD_NATIVE_FLOAT_RNG_CAPTURE_DIRECTORY"] = str(raw_directory)
    captured: list[dict[str, Any]] = []
    launched_process_ids: list[int] = []
    cleanup: list[dict[str, Any]] = []
    try:
        session.launch()
        launched_process_ids = list(session.process_ids)
        wait_for_runnable_capture_pipe(session)
        for request in CAPTURE_REQUESTS:
            raw_path = invoke_capture(session, request)
            expected_path = expected_paths[str(request["label"])]
            require(
                raw_path.resolve() == expected_path.resolve(),
                f"capture {request['label']} resolved to an unexpected output path",
            )
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            witnesses = verify_raw_recording(raw, request, instance)
            relative_raw = raw_path.relative_to(evidence_directory).as_posix()
            captured.append(
                {
                    "header": {
                        "recorded_live": True,
                        "instance": instance,
                        "captured_at_utc": time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                        ),
                        "source": source,
                        "capture_method": (
                            "opt-in loader seam calling the retail primitive on "
                            "an isolated constructor-initialized RNG object"
                        ),
                        "raw_recording": {
                            "evidence_path": relative_raw,
                            "sha256": sha256_file(raw_path),
                            "bytes": raw_path.stat().st_size,
                        },
                        "epsilon": {
                            "mode": "exact-float32-bit-patterns",
                            "value": 0,
                            "reason": "Returned binary32 bit patterns are exact; no epsilon is used.",
                        },
                    },
                    "request": raw["request"],
                    "draws": raw["draws"],
                    "witnesses": witnesses,
                }
            )
    finally:
        if session.process_ids:
            cleanup = session.close()
        if previous_capture_directory is None:
            os.environ.pop("SDMOD_NATIVE_FLOAT_RNG_CAPTURE_DIRECTORY", None)
        else:
            os.environ["SDMOD_NATIVE_FLOAT_RNG_CAPTURE_DIRECTORY"] = (
                previous_capture_directory
            )

    require(launched_process_ids, "capture launched no owned process")
    require(
        all(not process_is_running(process_id) for process_id in launched_process_ids),
        "an owned capture process remained runnable after exact-PID cleanup",
    )
    require(
        len(cleanup) == len(launched_process_ids),
        "owned-process cleanup did not account for every launched process",
    )

    by_label = {capture["request"]["label"]: capture for capture in captured}
    require(
        len(by_label) == len(CAPTURE_REQUESTS),
        "capture output labels are duplicated or missing",
    )
    require(
        by_label["scaled-magnitude-3-unsigned"]["witnesses"]["divergent_draw_indices"],
        "magnitude 3 capture contains no witness for the three-rounding schedule",
    )
    require(
        by_label["scaled-magnitude-4_5-signed"]["witnesses"]["divergent_draw_indices"],
        "magnitude 4.5 capture contains no witness for the three-rounding schedule",
    )
    require(
        by_label["scaled-endpoint-zero"]["witnesses"]["sampled_integers"] == [0] and
        by_label["unit-endpoint-zero"]["witnesses"]["sampled_integers"] == [0],
        "endpoint-zero capture seeds no longer reach k=0",
    )
    require(
        by_label["scaled-endpoint-positive"]["witnesses"]["sampled_integers"] == [DIVISOR] and
        by_label["unit-endpoint-positive"]["witnesses"]["sampled_integers"] == [DIVISOR],
        "positive-endpoint capture seeds no longer reach k=100000",
    )

    fixture = {
        "schema": "solomon-dark-float-rng-goldens-v1",
        "native_contract": {
            "constructor_preferred_address": CONSTRUCTOR_ADDRESS,
            "scaled_primitive_preferred_address": SCALED_ADDRESS,
            "unit_primitive_preferred_address": UNIT_ADDRESS,
            "state_size_bytes": 0xE8,
            "state_word_count": WORD_COUNT,
            "divisor_offset": DIVISOR_OFFSET,
            "stock_divisor": DIVISOR,
            "scaled_float32_rounding_points": 3,
            "unit_float32_rounding_points": 2,
            "unsigned_stream_word_cost": 1,
            "signed_stream_word_cost": 2,
        },
        "captures": captured,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    require(
        not output.exists() and not temporary.exists(),
        "fixture builder refuses to overwrite an existing output or temporary file",
    )
    temporary.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    return {
        "fixture": str(output),
        "fixture_sha256": sha256_file(output),
        "capture_count": len(captured),
        "draw_count": sum(len(item["draws"]) for item in captured),
        "owned_process_ids": launched_process_ids,
        "cleanup": cleanup,
        "source": source,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence-directory",
        type=Path,
        default=DEFAULT_EVIDENCE_DIRECTORY,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--instance", default=DEFAULT_INSTANCE)
    parser.add_argument("--local-port", type=int, default=DEFAULT_PORTS[0])
    parser.add_argument("--unused-remote-port", type=int, default=DEFAULT_PORTS[1])
    args = parser.parse_args()
    try:
        result = capture_fixture(
            args.evidence_directory.resolve(),
            args.output.resolve(),
            args.instance,
            (args.local_port, args.unused_remote_port),
        )
    except (CaptureFailure, native_sim.CaptureFailure) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
