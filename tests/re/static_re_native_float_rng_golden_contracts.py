"""Static contracts for the live native float-RNG golden corpus."""

from __future__ import annotations

import json
import re
import struct
from pathlib import Path
from typing import Any

from static_re_contract_support import (
    ROOT,
    StaticReTestFailure,
    assert_recorded_hash_matches_file,
    read_text,
)


FIXTURE = ROOT / "tests/fixtures/webgame/float-rng-goldens.json"
CAPTURE_SOURCE = ROOT / "SolomonDarkModLoader/src/native_float_rng_capture.cpp"
CAPTURE_HEADER = ROOT / "SolomonDarkModLoader/include/native_float_rng_capture.h"
DEBUG_BINDINGS = ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_debug.cpp"
STARTUP = ROOT / "SolomonDarkModLoader/src/mod_loader/initialize.inl"
LAYOUT = ROOT / "config/binary-layout.ini"
PROJECT = ROOT / "SolomonDarkModLoader/SolomonDarkModLoader.vcxproj"
PROJECT_FILTERS = ROOT / "SolomonDarkModLoader/SolomonDarkModLoader.vcxproj.filters"
RECORDER = ROOT / "tools/record_native_float_rng_goldens.py"
LUA_API = ROOT / "api/lua/sd.lua"

FIXTURE_SHA256 = "04b13d45611ee2c67dac2a73ff8572e7f948516eb6c05411686b609b970d9665"
BASE_COMMIT_SHA = "04c02dc98086bc0687f1906ba644a19a059e9a45"
BASE_TREE_SHA = "495cec38cfb16fa0dfe5d4a80d0a58145a074bac"
GAME_SHA256 = "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3"
LOADER_SHA256 = "7d0133ed53c8bff286e254718993244e7bb9fd8d27e75823220ad9dae8664195"
RNG_MASK = 0x3FFFFFFF
RNG_WORD_COUNT = 55
RNG_DIVISOR = 100000


CAPTURE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "label": "scaled-magnitude-1-unsigned",
        "seed": 1,
        "primitive": "scaled",
        "magnitude_float32_bits": "0x3F800000",
        "magnitude_source": "request",
        "signed": False,
        "count": 256,
        "captured_at_utc": "2026-08-05T21:48:16Z",
        "raw_sha256": "3e67f27d3a4be20e5d49d17f312803466bcc30be9af9373a06bb141fa09912be",
        "raw_bytes": 413839,
        "divergences": 0,
    },
    {
        "label": "scaled-magnitude-3-unsigned",
        "seed": 19088743,
        "primitive": "scaled",
        "magnitude_float32_bits": "0x40400000",
        "magnitude_source": "request",
        "signed": False,
        "count": 256,
        "captured_at_utc": "2026-08-05T21:48:16Z",
        "raw_sha256": "4da8a7d8589114c1f20631bba46bee7b3394855ad8e629ec1cd01a40bda7124a",
        "raw_bytes": 420548,
        "divergences": 79,
    },
    {
        "label": "scaled-magnitude-4_5-signed",
        "seed": RNG_MASK,
        "primitive": "scaled",
        "magnitude_float32_bits": "0x40900000",
        "magnitude_source": "request",
        "signed": True,
        "count": 256,
        "captured_at_utc": "2026-08-05T21:48:16Z",
        "raw_sha256": "865f62c7032b61b244a050c0faa76e59774c1c11cc15bab127a317b0809d43a4",
        "raw_bytes": 415290,
        "divergences": 67,
    },
    {
        "label": "scaled-endpoint-zero",
        "seed": 20001,
        "primitive": "scaled",
        "magnitude_float32_bits": "0x40400000",
        "magnitude_source": "request",
        "signed": False,
        "count": 1,
        "captured_at_utc": "2026-08-05T21:48:17Z",
        "raw_sha256": "2e19c133f79e729b4f58d7b989f3c2a2e71840be1388b1c581f7e6768a29b335",
        "raw_bytes": 2390,
        "divergences": 0,
    },
    {
        "label": "scaled-endpoint-positive",
        "seed": 33700,
        "primitive": "scaled",
        "magnitude_float32_bits": "0x40900000",
        "magnitude_source": "request",
        "signed": False,
        "count": 1,
        "captured_at_utc": "2026-08-05T21:48:17Z",
        "raw_sha256": "29455704e0832afcd4e84dd74c290ffc750504fb4de36c6002e947c54706e1d0",
        "raw_bytes": 2406,
        "divergences": 0,
    },
    {
        "label": "unit-unsigned",
        "seed": 1,
        "primitive": "unit",
        "magnitude_float32_bits": "0x3F800000",
        "magnitude_source": "implicit-unit",
        "signed": False,
        "count": 256,
        "captured_at_utc": "2026-08-05T21:48:17Z",
        "raw_sha256": "9c188aa2f0c90133a5cf491818e222754c09477ca758cd8f561d117716cb6289",
        "raw_bytes": 413829,
        "divergences": 0,
    },
    {
        "label": "unit-signed",
        "seed": 19088743,
        "primitive": "unit",
        "magnitude_float32_bits": "0x3F800000",
        "magnitude_source": "implicit-unit",
        "signed": True,
        "count": 256,
        "captured_at_utc": "2026-08-05T21:48:17Z",
        "raw_sha256": "b368a41eccfe2ae48d6acf131d87166619e52dc8c411730010ca0f887c2da1c1",
        "raw_bytes": 420550,
        "divergences": 0,
    },
    {
        "label": "unit-endpoint-zero",
        "seed": 20001,
        "primitive": "unit",
        "magnitude_float32_bits": "0x3F800000",
        "magnitude_source": "implicit-unit",
        "signed": False,
        "count": 1,
        "captured_at_utc": "2026-08-05T21:48:17Z",
        "raw_sha256": "947c8e08600545aa6fcf882e12d187ae23c03db71dd3f4ef36d88d7cc12f2373",
        "raw_bytes": 2392,
        "divergences": 0,
    },
    {
        "label": "unit-endpoint-positive",
        "seed": 33700,
        "primitive": "unit",
        "magnitude_float32_bits": "0x3F800000",
        "magnitude_source": "implicit-unit",
        "signed": False,
        "count": 1,
        "captured_at_utc": "2026-08-05T21:48:17Z",
        "raw_sha256": "4be58901bd13c1af10a202fca159d07c61ffb1d5d4429aab08582499ecf7dfff",
        "raw_bytes": 2408,
        "divergences": 0,
    },
)


def _load_fixture() -> dict[str, Any]:
    try:
        document = json.loads(read_text(FIXTURE))
    except json.JSONDecodeError as error:
        raise StaticReTestFailure(
            f"float RNG golden corpus is not machine-readable JSON: {error}"
        ) from error
    if not isinstance(document, dict):
        raise StaticReTestFailure("float RNG golden corpus lost its top-level object")
    return document


def _capture_map(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    captures = document.get("captures")
    expected_labels = tuple(spec["label"] for spec in CAPTURE_SPECS)
    if not isinstance(captures, list) or len(captures) != len(expected_labels):
        raise StaticReTestFailure(
            "float RNG capture census no longer reaches all nine named live sequences"
        )
    actual_labels: list[str] = []
    result: dict[str, dict[str, Any]] = {}
    for capture in captures:
        if not isinstance(capture, dict) or not isinstance(capture.get("request"), dict):
            raise StaticReTestFailure(
                "float RNG capture census contains a sequence without a request identity"
            )
        label = capture["request"].get("label")
        if not isinstance(label, str):
            raise StaticReTestFailure(
                "float RNG capture census contains a sequence without a named label"
            )
        if label in result:
            raise StaticReTestFailure(
                f"float RNG lookup is ambiguous because capture {label!r} is duplicated"
            )
        actual_labels.append(label)
        result[label] = capture
    if tuple(actual_labels) != expected_labels:
        raise StaticReTestFailure(
            "float RNG capture order or named sequence census changed: "
            f"{tuple(actual_labels)!r}"
        )
    return result


def _request_for(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": spec["label"],
        "seed": spec["seed"],
        "primitive": spec["primitive"],
        "magnitude_float32_bits": spec["magnitude_float32_bits"],
        "magnitude_source": spec["magnitude_source"],
        "signed": spec["signed"],
        "count": spec["count"],
    }


def _unique_layout_numeric(key_name: str) -> int:
    candidates: list[tuple[int, str]] = []
    for line_number, raw_line in enumerate(read_text(LAYOUT).splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == key_name:
            candidates.append((line_number, value.strip()))
    if len(candidates) != 1:
        raise StaticReTestFailure(
            f"capture address lookup for {key_name} is ambiguous or absent: {candidates!r}"
        )
    line_number, value = candidates[0]
    try:
        return int(value, 0)
    except ValueError as error:
        raise StaticReTestFailure(
            f"capture address {key_name} at binary-layout line {line_number} is not numeric"
        ) from error


def _normalized_state(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "index_a",
        "index_b",
        "state_words",
        "divisor",
    }:
        raise StaticReTestFailure(f"{label} no longer records the complete native state")
    words = value["state_words"]
    if not isinstance(words, list) or len(words) != RNG_WORD_COUNT:
        raise StaticReTestFailure(f"{label} no longer records all 55 stream words")
    if any(type(word) is not int or not 0 <= word <= RNG_MASK for word in words):
        raise StaticReTestFailure(f"{label} contains a word outside the retail 30-bit state")
    index_a = value["index_a"]
    index_b = value["index_b"]
    if (
        type(index_a) is not int
        or type(index_b) is not int
        or not 0 <= index_a < RNG_WORD_COUNT
        or not 0 <= index_b < RNG_WORD_COUNT
    ):
        raise StaticReTestFailure(f"{label} no longer pins runnable ring indices")
    return {
        "index_a": index_a,
        "index_b": index_b,
        "state_words": list(words),
        "divisor": value["divisor"],
    }


def _initial_state(seed: int) -> dict[str, Any]:
    words = [seed & RNG_MASK, 1]
    while len(words) < RNG_WORD_COUNT:
        words.append((words[-1] + words[-2]) & RNG_MASK)
    return {
        "index_a": 0,
        "index_b": 31,
        "state_words": words,
        "divisor": RNG_DIVISOR,
    }


def _stream_word(state: dict[str, Any]) -> int:
    index_a = state["index_a"]
    index_b = state["index_b"]
    words = state["state_words"]
    result = (words[index_a] + words[index_b]) & RNG_MASK
    words[index_a] = result
    state["index_a"] = (index_a + 1) % RNG_WORD_COUNT
    state["index_b"] = (index_b + 1) % RNG_WORD_COUNT
    return result


def _bounded_integer(state: dict[str, Any], bound: int) -> int:
    mask = 1
    while mask + 1 < bound:
        mask = (mask << 1) | 1
    return ((_stream_word(state) >> 6) & mask) % bound


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _float_from_bits(bits: str) -> float:
    return struct.unpack("<f", struct.pack("<I", int(bits, 16)))[0]


def _float_bits(value: float) -> str:
    bits = struct.unpack("<I", struct.pack("<f", value))[0]
    return f"0x{bits:08X}"


def _expected_float_bits(
    state: dict[str, Any], primitive: str, magnitude: float, signed: bool
) -> tuple[str, int]:
    sampled_integer = _bounded_integer(state, RNG_DIVISOR + 1)
    quotient = _f32(_f32(float(sampled_integer)) / RNG_DIVISOR)
    result = quotient if primitive == "unit" else _f32(quotient * _f32(magnitude))
    if signed and ((_stream_word(state) >> 6) & 1) != 0:
        result = _f32(-result)
    return _float_bits(result), sampled_integer


def test_native_float_rng_golden_provenance_and_capture_census_are_pinned() -> str:
    assert_recorded_hash_matches_file(
        FIXTURE_SHA256, FIXTURE, "native float RNG golden corpus"
    )
    document = _load_fixture()
    if document.get("schema") != "solomon-dark-float-rng-goldens-v1":
        raise StaticReTestFailure(
            "float RNG provenance can no longer be interpreted under the captured schema"
        )
    expected_contract = {
        "constructor_preferred_address": "0x00401110",
        "scaled_primitive_preferred_address": "0x00401310",
        "unit_primitive_preferred_address": "0x004011F0",
        "state_size_bytes": 232,
        "state_word_count": 55,
        "divisor_offset": "0xE4",
        "stock_divisor": 100000,
        "scaled_float32_rounding_points": 3,
        "unit_float32_rounding_points": 2,
        "unsigned_stream_word_cost": 1,
        "signed_stream_word_cost": 2,
    }
    if document.get("native_contract") != expected_contract:
        raise StaticReTestFailure(
            "float RNG corpus no longer declares the captured addresses, rounding, and stream-cost contract"
        )

    captures = _capture_map(document)
    expected_source = {
        "base_commit_sha": BASE_COMMIT_SHA,
        "base_tree_sha": BASE_TREE_SHA,
        "game_executable_sha256": GAME_SHA256,
        "loader_dll_sha256": LOADER_SHA256,
    }
    expected_epsilon = {
        "mode": "exact-float32-bit-patterns",
        "value": 0,
        "reason": "Returned binary32 bit patterns are exact; no epsilon is used.",
    }
    total_draws = 0
    for spec in CAPTURE_SPECS:
        capture = captures[spec["label"]]
        if capture.get("request") != _request_for(spec):
            raise StaticReTestFailure(
                f"float RNG capture {spec['label']} no longer pins its exact live request"
            )
        draws = capture.get("draws")
        if not isinstance(draws, list) or len(draws) != spec["count"]:
            raise StaticReTestFailure(
                f"float RNG capture {spec['label']} no longer contains its complete draw sequence"
            )
        total_draws += len(draws)
        header = capture.get("header")
        if not isinstance(header, dict) or set(header) != {
            "recorded_live",
            "instance",
            "captured_at_utc",
            "source",
            "capture_method",
            "raw_recording",
            "epsilon",
        }:
            raise StaticReTestFailure(
                f"float RNG capture {spec['label']} lost its reviewable live-capture header"
            )
        if (
            header["recorded_live"] is not True
            or header["instance"] != "gfx-goldfix-rng"
            or header["captured_at_utc"] != spec["captured_at_utc"]
            or header["source"] != expected_source
            or header["capture_method"]
            != "opt-in loader seam calling the retail primitive on an isolated constructor-initialized RNG object"
            or header["epsilon"] != expected_epsilon
        ):
            raise StaticReTestFailure(
                f"float RNG capture {spec['label']} is no longer attributable to the exact live binary run"
            )
        expected_raw = {
            "evidence_path": f"raw/float-rng/{spec['label']}.json",
            "sha256": spec["raw_sha256"],
            "bytes": spec["raw_bytes"],
        }
        if header["raw_recording"] != expected_raw:
            raise StaticReTestFailure(
                f"float RNG capture {spec['label']} no longer cross-links its sealed raw evidence artifact"
            )

    if total_draws != 1284:
        raise StaticReTestFailure(
            f"float RNG live corpus no longer pins all 1,284 draws: found {total_draws}"
        )
    long_scaled = tuple(
        spec
        for spec in CAPTURE_SPECS
        if spec["primitive"] == "scaled" and spec["count"] >= 200
    )
    long_unit = tuple(
        spec
        for spec in CAPTURE_SPECS
        if spec["primitive"] == "unit" and spec["count"] >= 200
    )
    if (
        tuple(spec["magnitude_float32_bits"] for spec in long_scaled)
        != ("0x3F800000", "0x40400000", "0x40900000")
        or tuple(spec["signed"] for spec in long_unit) != (False, True)
    ):
        raise StaticReTestFailure(
            "float RNG coverage no longer has 256-draw scaled runs at three magnitudes and both unit sign modes"
        )
    return "nine live captures and 1,284 exact draws retain complete binary and raw-evidence provenance"


def test_native_float_rng_golden_outputs_replay_bit_exact() -> str:
    captures = _capture_map(_load_fixture())
    checked_draws = 0
    for spec in CAPTURE_SPECS:
        label = spec["label"]
        capture = captures[label]
        draws = capture.get("draws")
        if not isinstance(draws, list) or len(draws) != spec["count"]:
            raise StaticReTestFailure(
                f"bit-exact output replay cannot reach the complete {label} sequence"
            )
        state = _initial_state(spec["seed"])
        sampled_integers: list[int] = []
        divergent_indices: list[int] = []
        magnitude = _float_from_bits(spec["magnitude_float32_bits"])
        for index, draw in enumerate(draws):
            if not isinstance(draw, dict) or set(draw) != {
                "draw_index",
                "pre_call",
                "request",
                "returned_float32_bits",
                "post_call",
            }:
                raise StaticReTestFailure(
                    f"bit-exact output replay lost the complete recording at {label} draw {index}"
                )
            if draw["draw_index"] != index:
                raise StaticReTestFailure(
                    f"bit-exact output replay lost contiguous order at {label} draw {index}"
                )
            pre_call = _normalized_state(draw["pre_call"], f"{label} draw {index} pre-call")
            if pre_call != state:
                raise StaticReTestFailure(
                    f"bit-exact output replay cannot continue the retail stream at {label} draw {index}"
                )
            expected_draw_request = {
                "magnitude_float32_bits": spec["magnitude_float32_bits"],
                "signed": spec["signed"],
            }
            if draw["request"] != expected_draw_request:
                raise StaticReTestFailure(
                    f"bit-exact output replay found parameter drift at {label} draw {index}"
                )
            expected_bits, sampled_integer = _expected_float_bits(
                state, spec["primitive"], magnitude, spec["signed"]
            )
            if draw["returned_float32_bits"] != expected_bits:
                raise StaticReTestFailure(
                    "bit-exact float32 output claim failed at "
                    f"{label} draw {index}: {draw['returned_float32_bits']!r} != {expected_bits}"
                )
            post_call = _normalized_state(
                draw["post_call"], f"{label} draw {index} post-call"
            )
            if post_call != state:
                raise StaticReTestFailure(
                    f"bit-exact output replay found incompatible post-call state at {label} draw {index}"
                )
            sampled_integers.append(sampled_integer)
            if spec["primitive"] == "scaled":
                naive = _f32(sampled_integer / RNG_DIVISOR * magnitude)
                native = _f32(
                    _f32(_f32(float(sampled_integer)) / RNG_DIVISOR)
                    * _f32(magnitude)
                )
                if _float_bits(naive) != _float_bits(native):
                    divergent_indices.append(index)
            checked_draws += 1
        witnesses = capture.get("witnesses")
        if witnesses != {
            "divergent_draw_indices": divergent_indices,
            "sampled_integers": sampled_integers,
        }:
            raise StaticReTestFailure(
                f"three-rounding witness census no longer agrees with live sequence {label}"
            )
        if len(divergent_indices) != spec["divergences"]:
            raise StaticReTestFailure(
                f"three-rounding divergence count changed for {label}: {len(divergent_indices)}"
            )
    if checked_draws != 1284:
        raise StaticReTestFailure(
            f"bit-exact output replay did not examine all 1,284 recorded draws: {checked_draws}"
        )
    return "all 1,284 returned float32 bit patterns replay from independent retail stream and rounding models"


def test_native_float_rng_signed_draws_consume_two_stream_words() -> str:
    document = _load_fixture()
    contract = document.get("native_contract")
    if not isinstance(contract, dict) or (
        contract.get("unsigned_stream_word_cost") != 1
        or contract.get("signed_stream_word_cost") != 2
    ):
        raise StaticReTestFailure(
            "signed two-word stream-cost claim is no longer declared by the golden corpus"
        )
    captures = _capture_map(document)
    signed_draws = 0
    unsigned_draws = 0
    for spec in CAPTURE_SPECS:
        label = spec["label"]
        draws = captures[label].get("draws")
        if not isinstance(draws, list) or len(draws) != spec["count"]:
            raise StaticReTestFailure(
                f"stream-cost replay cannot reach the complete {label} sequence"
            )
        expected_cost = 2 if spec["signed"] else 1
        for index, draw in enumerate(draws):
            if not isinstance(draw, dict):
                raise StaticReTestFailure(
                    f"stream-cost replay lost {label} draw {index}"
                )
            pre_call = _normalized_state(draw.get("pre_call"), f"{label} draw {index} pre-call")
            post_call = _normalized_state(draw.get("post_call"), f"{label} draw {index} post-call")
            for _ in range(expected_cost):
                _stream_word(pre_call)
            if pre_call != post_call:
                claim = (
                    "signed two-word stream-cost claim"
                    if spec["signed"]
                    else "unsigned one-word stream-cost claim"
                )
                raise StaticReTestFailure(
                    f"{claim} failed at {label} draw {index}"
                )
            if spec["signed"]:
                signed_draws += 1
            else:
                unsigned_draws += 1
    if signed_draws != 512 or unsigned_draws != 772:
        raise StaticReTestFailure(
            "stream-cost replay did not examine the exact 512 signed and 772 unsigned live draws"
        )
    return "512 signed draws advance exactly two words and 772 unsigned draws advance exactly one"


def test_native_float_rng_divisor_is_object_local_at_e4() -> str:
    document = _load_fixture()
    contract = document.get("native_contract")
    if not isinstance(contract, dict) or (
        contract.get("state_size_bytes") != 0xE8
        or contract.get("divisor_offset") != "0xE4"
        or contract.get("stock_divisor") != RNG_DIVISOR
    ):
        raise StaticReTestFailure(
            "per-object divisor claim no longer pins 100000 at this+0xE4 in the 0xE8-byte state"
        )
    captures = _capture_map(document)
    checked_states = 0
    for spec in CAPTURE_SPECS:
        draws = captures[spec["label"]].get("draws")
        if not isinstance(draws, list) or len(draws) != spec["count"]:
            raise StaticReTestFailure(
                f"divisor replay cannot reach the complete {spec['label']} sequence"
            )
        for index, draw in enumerate(draws):
            if not isinstance(draw, dict):
                raise StaticReTestFailure(
                    f"divisor replay lost {spec['label']} draw {index}"
                )
            for phase in ("pre_call", "post_call"):
                state = _normalized_state(
                    draw.get(phase), f"{spec['label']} draw {index} {phase}"
                )
                if state["divisor"] != RNG_DIVISOR:
                    raise StaticReTestFailure(
                        "per-object divisor claim failed at "
                        f"{spec['label']} draw {index} {phase}: {state['divisor']!r}"
                    )
                checked_states += 1
    if checked_states != 2568:
        raise StaticReTestFailure(
            f"divisor replay did not examine all 2,568 pre/post states: {checked_states}"
        )

    source = read_text(CAPTURE_SOURCE)
    struct_pattern = re.compile(
        r"struct\s+NativeRngState\s*\{\s*"
        r"std::uint32_t\s+index_a\s*=\s*0;\s*"
        r"std::uint32_t\s+index_b\s*=\s*0;\s*"
        r"std::array<std::uint32_t,\s*kNativeRngWordCount>\s+words\s*=\s*\{\};\s*"
        r"std::uint32_t\s+divisor\s*=\s*0;\s*\};"
    )
    if struct_pattern.search(source) is None:
        raise StaticReTestFailure(
            "per-object divisor layout no longer places divisor immediately after the 55-word state"
        )
    offset_pattern = re.compile(
        r"static_assert\s*\(\s*offsetof\(NativeRngState,\s*divisor\)\s*==\s*"
        r"kNativeRngDivisorOffset\s*,\s*"
        r'"native RNG divisor must remain at this\+0xE4"\s*\);'
    )
    if offset_pattern.search(source) is None:
        raise StaticReTestFailure(
            "per-object divisor layout no longer compile-time asserts divisor at this+0xE4"
        )
    constants_pattern = re.compile(
        r"constexpr\s+std::size_t\s+kNativeRngStateSize\s*=\s*0xE8;\s*"
        r"constexpr\s+std::size_t\s+kNativeRngWordCount\s*=\s*55;\s*"
        r"constexpr\s+std::size_t\s+kNativeRngDivisorOffset\s*=\s*0xE4;\s*"
        r"constexpr\s+std::uint32_t\s+kNativeRngDivisor\s*=\s*100000;"
    )
    if constants_pattern.search(source) is None:
        raise StaticReTestFailure(
            "per-object divisor constants no longer bind the 0xE8 layout to this+0xE4 and 100000"
        )
    constructor_check = re.compile(
        r"InvokeNativeRngConstructor\([\s\S]*?\)\)\s*\{[\s\S]*?return false;\s*\}\s*"
        r"if\s*\(state\.divisor\s*!=\s*kNativeRngDivisor\)\s*\{[\s\S]*?"
        r"constructor did not initialize this\+0xE4 to 100000[\s\S]*?return false;\s*\}\s*"
        r"exception_code\s*=\s*0;\s*if\s*\(!InvokeNativeRngSeed\([\s\S]*?\)\)\s*\{"
        r"[\s\S]*?return false;\s*\}\s*if\s*\(state\.divisor\s*!=\s*kNativeRngDivisor\)"
    )
    if constructor_check.search(source) is None:
        raise StaticReTestFailure(
            "per-object divisor runtime guard no longer checks constructor initialization and seed preservation in order"
        )
    return "all 2,568 states and the recorder layout pin the per-object divisor to this+0xE4"


def test_native_float_rng_capture_seam_is_opt_in_runnable_and_fail_closed() -> str:
    source = read_text(CAPTURE_SOURCE)
    header = read_text(CAPTURE_HEADER)
    bindings = read_text(DEBUG_BINDINGS)
    startup = read_text(STARTUP)
    recorder = read_text(RECORDER)
    project = read_text(PROJECT)
    filters = read_text(PROJECT_FILTERS)
    lua_api = read_text(LUA_API)

    opt_in_pattern = re.compile(
        r"g_capture\.requested\s*=\s*IsNativeFloatRngCaptureRequested\(\);\s*"
        r"if\s*\(!g_capture\.requested\)\s*\{\s*return true;\s*\}\s*"
        r"if\s*\(error_message\s*==\s*nullptr\)"
    )
    if (
        '"SDMOD_NATIVE_FLOAT_RNG_CAPTURE_DIRECTORY"' not in source
        or opt_in_pattern.search(source) is None
    ):
        raise StaticReTestFailure(
            "opt-in seam claim failed: a normal launch can reach float capture initialization without the environment request"
        )
    registration_pattern = re.compile(
        r"if\s*\(IsNativeFloatRngCaptureInitialized\(\)\)\s*\{\s*"
        r"RegisterFunction\(\s*state,\s*&LuaDebugCaptureNativeFloatRng,\s*"
        r'"capture_native_float_rng"\s*\);\s*\}'
    )
    if registration_pattern.search(bindings) is None:
        raise StaticReTestFailure(
            "opt-in seam claim failed: capture_native_float_rng is no longer registered only after successful initialization"
        )
    startup_pattern = re.compile(
        r"if\s*\(IsNativeFloatRngCaptureRequested\(\)\)\s*\{[\s\S]*?"
        r'write_failed_status\(\s*"native-float-rng-capture-lua-disabled"[\s\S]*?'
        r"InitializeNativeFloatRngCapture\([\s\S]*?"
        r'write_failed_status\(\s*"native-float-rng-capture-failed"'
    )
    if startup_pattern.search(startup) is None:
        raise StaticReTestFailure(
            "fail-closed seam claim failed: requested Lua-disabled and initialization-broken launches are not distinct terminal failures"
        )
    probe_pattern = re.compile(
        r"create_directories\(g_capture\.directory\);[\s\S]*?"
        r"\.native-float-rng-capture-write-probe[\s\S]*?"
        r"std::ofstream\s+stream\([\s\S]*?if\s*\(!stream\)\s*\{[\s\S]*?return false;"
        r"[\s\S]*?std::filesystem::remove\(write_probe,\s*remove_error\)[\s\S]*?"
        r"could not remove its probe file[\s\S]*?return false;"
    )
    if probe_pattern.search(source) is None:
        raise StaticReTestFailure(
            "runnable-directory seam claim failed: requested capture no longer proves create, write, and remove end to end"
        )
    expected_layout = {
        "native_rng_construct": 0x00401110,
        "native_rng_initialize": 0x00401120,
        "native_rng_float": 0x00401310,
        "native_rng_unit_float": 0x004011F0,
    }
    actual_layout = {key: _unique_layout_numeric(key) for key in expected_layout}
    if actual_layout != expected_layout:
        raise StaticReTestFailure(
            f"capture address seam no longer resolves all four documented retail functions: {actual_layout!r}"
        )
    if (
        "bool IsNativeFloatRngCaptureRequested();" not in header
        or "bool IsNativeFloatRngCaptureInitialized();" not in header
        or "bool InitializeNativeFloatRngCapture(std::string* error_message);" not in header
    ):
        raise StaticReTestFailure(
            "capture seam lifecycle is no longer exposed as requested, initialized, and fallible states"
        )
    project_contracts = (
        (project, 'Include="include\\native_float_rng_capture.h"'),
        (project, 'Include="src\\native_float_rng_capture.cpp"'),
        (filters, 'Include="include\\native_float_rng_capture.h"'),
        (filters, 'Include="src\\native_float_rng_capture.cpp"'),
    )
    for project_text, include in project_contracts:
        if include not in project_text:
            raise StaticReTestFailure(
                f"capture seam build registration no longer compiles the exact artifact {include}"
            )
    if "function sd_debug.capture_native_float_rng(...) end" not in lua_api:
        raise StaticReTestFailure(
            "capture seam registration no longer reaches the generated Lua API inventory"
        )
    recorder_requirements = (
        "kernel32.OpenProcess",
        "kernel32.GetExitCodeProcess",
        '"loader startup is broken, not busy: "',
        '"native float RNG capture remained busy for',
        'response == "function"',
        '"Lua is runnable but the requested native float RNG capture function is absent"',
        'os.environ["SDMOD_NATIVE_FLOAT_RNG_CAPTURE_DIRECTORY"] = str(raw_directory)',
        "session.launch()",
        "all(not process_is_running(process_id) for process_id in launched_process_ids)",
        '"an owned capture process remained runnable after exact-PID cleanup"',
    )
    missing = tuple(token for token in recorder_requirements if token not in recorder)
    if missing:
        raise StaticReTestFailure(
            "runnable recorder claim failed: process liveness, broken/busy distinction, Lua execution, opt-in launch, or exact cleanup drifted: "
            f"{missing!r}"
        )
    environment_order = re.compile(
        r'os\.environ\["SDMOD_NATIVE_FLOAT_RNG_CAPTURE_DIRECTORY"\]\s*=\s*str\(raw_directory\)'
        r"[\s\S]*?try:\s*session\.launch\(\)[\s\S]*?finally:[\s\S]*?session\.close\(\)"
        r"[\s\S]*?os\.environ\.pop\(\"SDMOD_NATIVE_FLOAT_RNG_CAPTURE_DIRECTORY\",\s*None\)"
    )
    if environment_order.search(recorder) is None:
        raise StaticReTestFailure(
            "opt-in recorder claim failed: the capture environment is not installed only around launch and restored after exact cleanup"
        )
    return "the capture seam is opt-in, address-pinned, runnable-probed, fail-closed, and exact-PID cleaned"
