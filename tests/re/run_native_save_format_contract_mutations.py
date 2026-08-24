#!/usr/bin/env python3
"""Mutation-audit every G10 native-save static contract."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
from typing import Callable
from unittest.mock import patch

import static_re_native_save_format_contracts as contracts


@dataclass(frozen=True)
class TextMutation:
    claim: str
    contract: str
    target: Path
    old: str
    new: str
    expected: str
    replace_all: bool = False


@dataclass(frozen=True)
class JsonMutation:
    claim: str
    contract: str
    target: Path
    mutate: Callable[[dict[str, object]], None]
    expected: str


@dataclass(frozen=True)
class SpecialMutation:
    claim: str
    contract: str
    activate: Callable[[], AbstractContextManager[None]]
    expected: str


@dataclass(frozen=True)
class MutationResult:
    claim: str
    contract: str
    expected_message: str
    observed_message: str
    baseline_before: str
    baseline_after: str


Mutation = TextMutation | JsonMutation | SpecialMutation


def clear_contract_bytecode() -> None:
    cache = Path(__file__).resolve().parent / "__pycache__"
    if not cache.is_dir():
        return
    children = list(cache.iterdir())
    for child in children:
        if not child.is_file() or child.suffix != ".pyc":
            raise RuntimeError(
                f"refusing to clear unexpected contract cache entry {child}"
            )
        child.unlink()
    cache.rmdir()


@contextmanager
def text_mutation(mutation: TextMutation) -> Iterator[None]:
    original_read = contracts._read_text  # noqa: SLF001 - intentional seam.
    target = mutation.target.resolve()
    applied = False

    def mutated_read(path: Path, consequence: str) -> str:
        nonlocal applied
        text = original_read(path, consequence)
        if path.resolve() != target:
            return text
        occurrences = text.count(mutation.old)
        if occurrences == 0:
            raise RuntimeError(
                f"mutation {mutation.claim} cannot find its source token in {path}"
            )
        applied = True
        count = occurrences if mutation.replace_all else 1
        return text.replace(mutation.old, mutation.new, count)

    with patch.object(contracts, "_read_text", mutated_read):
        yield
    if not applied:
        raise RuntimeError(f"mutation {mutation.claim} never reached {mutation.target}")


@contextmanager
def json_mutation(mutation: JsonMutation) -> Iterator[None]:
    original_read = contracts._read_json  # noqa: SLF001 - intentional seam.
    target = mutation.target.resolve()
    applied = False

    def mutated_read(path: Path, consequence: str) -> dict[str, object]:
        nonlocal applied
        document = original_read(path, consequence)
        if path.resolve() != target:
            return document
        applied = True
        result = deepcopy(document)
        mutation.mutate(result)
        return result

    with patch.object(contracts, "_read_json", mutated_read):
        yield
    if not applied:
        raise RuntimeError(f"mutation {mutation.claim} never reached {mutation.target}")


@contextmanager
def wrong_endianness() -> Iterator[None]:
    with patch.object(contracts, "SYNCBUFFER_ENDIANNESS", "big"):
        yield


@contextmanager
def wrong_xor_key() -> Iterator[None]:
    with patch.object(contracts, "DARKDATA_KEY", contracts.DARKDATA_KEY + b"x"):
        yield


@contextmanager
def duplicate_lookup_silently_wins() -> Iterator[None]:
    original = contracts.parse_syncbuffer
    empty = bytes.fromhex("000000000000000000000000")

    def mutant(data: bytes):  # type: ignore[no-untyped-def]
        if data.count(b"x\0") == 2:
            return original(empty)
        return original(data)

    with patch.object(contracts, "parse_syncbuffer", mutant):
        yield


@contextmanager
def shifted_gold_offset() -> Iterator[None]:
    fields = list(contracts.DARKDATA_CORE_FIELDS)
    fields[0] = replace(fields[0], file_offset=1)
    with patch.object(contracts, "DARKDATA_CORE_FIELDS", tuple(fields)):
        yield


@contextmanager
def recorder_cleanup_not_in_finally() -> Iterator[None]:
    original_read = contracts._read_text  # noqa: SLF001 - intentional seam.
    target = contracts.RECORDER.resolve()
    applied = False

    def mutated_read(path: Path, consequence: str) -> str:
        nonlocal applied
        text = original_read(path, consequence)
        if path.resolve() != target:
            return text
        old_header = (
            "def capture_scenario(spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:\n"
        )
        old_finally = "    finally:\n        cleanup = session.close()\n"
        if old_header not in text or old_finally not in text:
            raise RuntimeError("cleanup-finally mutation cannot locate recorder flow")
        applied = True
        return text.replace(
            old_header,
            old_header + "    if False:\n        session.close()\n",
            1,
        ).replace(
            old_finally,
            "    finally:\n        cleanup = []\n",
            1,
        )

    with patch.object(contracts, "_read_text", mutated_read):
        yield
    if not applied:
        raise RuntimeError("cleanup-finally mutation never reached recorder")


@contextmanager
def helper_sees_mismatched_committed_hash() -> Iterator[None]:
    original_read = contracts._read_text  # noqa: SLF001 - intentional seam.
    original_hash = contracts.EXPECTED_FIXTURE_SHA256
    mutant_hash = "f" + original_hash[1:]
    target = contracts.DOC.resolve()
    applied = False

    def mutated_read(path: Path, consequence: str) -> str:
        nonlocal applied
        text = original_read(path, consequence)
        if path.resolve() != target:
            return text
        if original_hash not in text:
            raise RuntimeError("fixture-hash helper mutation cannot locate recorded hash")
        applied = True
        return text.replace(original_hash, mutant_hash, 1)

    with (
        patch.object(contracts, "_read_text", mutated_read),
        patch.object(contracts, "EXPECTED_FIXTURE_SHA256", mutant_hash),
    ):
        yield
    if not applied:
        raise RuntimeError("fixture-hash helper mutation never reached documentation")


CONTAINER = "test_native_save_container_codec_and_layout_are_pinned"
ROUND_TRIP = "test_native_save_goldens_round_trip_all_committed_files"
DEFAULTS = "test_native_save_fresh_defaults_and_runtime_offsets_are_pinned"
RECORDER_CONTRACT = (
    "test_native_save_recorder_is_self_provenanced_settled_bounded_and_owned"
)
LIFECYCLE = "test_native_save_lifecycle_and_failure_semantics_are_pinned"
LAUNCHER = "test_launcher_save_layer_and_account_seam_are_pinned"
FIXTURE_HASH = "test_native_save_fixture_provenance_hashes_the_committed_recording"


def _capture(document: dict[str, object], index: int) -> dict[str, object]:
    return document["captures"][index]  # type: ignore[index,return-value]


def _file(document: dict[str, object], capture_index: int, file_index: int) -> dict[str, object]:
    return _capture(document, capture_index)["files"][file_index]  # type: ignore[index,return-value]


def _core_field(document: dict[str, object], capture_index: int, name: str) -> dict[str, object]:
    entry = _file(document, capture_index, 0)
    fields = entry["decoded_fields"]["core_fields"]  # type: ignore[index]
    return next(row for row in fields if row["name"] == name)  # type: ignore[no-any-return,index]


MUTATIONS: tuple[Mutation, ...] = (
    SpecialMutation(
        "container.endianness-and-no-header",
        CONTAINER,
        wrong_endianness,
        "native save container no longer pins little-endian and the absence of magic/version",
    ),
    SpecialMutation(
        "codec.full-xor-key",
        CONTAINER,
        wrong_xor_key,
        "darkdata repeating XOR key no longer matches the retail codec",
    ),
    SpecialMutation(
        "container.duplicate-name-refusal",
        CONTAINER,
        duplicate_lookup_silently_wins,
        "SyncBuffer parser can silently choose between duplicate named buffers",
    ),
    TextMutation(
        "codec.marker-tie-break",
        CONTAINER,
        contracts.TOOL,
        "marker = min(range(256), key=lambda value: (frequencies[value], value))",
        "marker = max(range(256), key=lambda value: (frequencies[value], value))",
        "native save codec no longer proves retail mechanism witness 'marker = min(range(256), key=lambda value: (frequencies[value], value))'",
    ),
    JsonMutation(
        "goldens.exact-scenario-census",
        ROUND_TRIP,
        contracts.FIXTURE,
        lambda value: _capture(value, 2).__setitem__("id", "post_unlock_mutant"),
        "native save fixture no longer has the exact fresh, mid-run, and post-unlock witnesses",
    ),
    JsonMutation(
        "goldens.file-witness-floor",
        ROUND_TRIP,
        contracts.FIXTURE,
        lambda value: _capture(value, 0)["files"].pop(1),  # type: ignore[index,union-attr]
        "save golden fresh_profile no longer contains darkdata, one Region cache, and settings",
    ),
    JsonMutation(
        "goldens.byte-round-trip",
        ROUND_TRIP,
        contracts.FIXTURE,
        lambda value: _file(value, 0, 0)["tree"]["root"]["children"][0].__setitem__(  # type: ignore[index,union-attr]
            "payload_hex",
            "f5" + _file(value, 0, 0)["tree"]["root"]["children"][0]["payload_hex"][2:],  # type: ignore[index,operator]
        ),
        "save golden fresh_profile/savegames/solomondark/darkdata.cfg no longer re-encodes to its raw SHA-256",
    ),
    JsonMutation(
        "goldens.mid-progression-semantics",
        ROUND_TRIP,
        contracts.FIXTURE,
        lambda value: _core_field(value, 1, "profile_gold").__setitem__("value", 874),
        "save golden mid_progression_after_scripted_run no longer proves its decoded progression checkpoint",
    ),
    JsonMutation(
        "goldens.unlock-semantics",
        ROUND_TRIP,
        contracts.FIXTURE,
        lambda value: _file(value, 2, 0)["decoded_fields"]["hagatha_first_mix_flags"].__setitem__(0, False),  # type: ignore[index,union-attr]
        "save golden post_unlock no longer proves its native unlock flags",
    ),
    JsonMutation(
        "defaults.retail-initializer",
        DEFAULTS,
        contracts.FIXTURE,
        lambda value: value["fresh_profile_defaults"].__setitem__("profile_gold", 499),  # type: ignore[index,union-attr]
        "embedded save defaults and the standalone format implementation disagree",
    ),
    SpecialMutation(
        "defaults.runtime-field-offsets",
        DEFAULTS,
        shifted_gold_offset,
        "native darkdata core no longer pins all 46 field offsets, types, and runtime mappings",
    ),
    JsonMutation(
        "defaults.byte-tree-offsets",
        DEFAULTS,
        contracts.FIXTURE,
        lambda value: _file(value, 0, 0)["tree"]["root"]["children"][0].__setitem__("offset", 9),  # type: ignore[index,union-attr]
        "fresh native profile no longer pins the byte-exact six-child SyncBuffer tree",
    ),
    JsonMutation(
        "defaults.serializer-flag-27",
        DEFAULTS,
        contracts.FIXTURE,
        lambda value: _file(value, 0, 0)["tree"]["root"]["children"][3].__setitem__(  # type: ignore[index,union-attr]
            "payload_hex",
            "00" * 30,
        ),
        "first persisted profile no longer distinguishes initializer flags from serializer-set index 27",
    ),
    JsonMutation(
        "defaults.encoded-file-size",
        DEFAULTS,
        contracts.FIXTURE,
        lambda value: _file(value, 0, 0).__setitem__("length", 212),
        "fresh profile no longer reifies the exact 220-byte tree as the 211-byte retail file",
    ),
    TextMutation(
        "recorder.no-provenance-overrides",
        RECORDER_CONTRACT,
        contracts.RECORDER,
        '    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)\n',
        '    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)\n'
        '    parser.add_argument("--source-revision")\n',
        "native save recorder exposes provenance, binary, instance, or port override arguments",
    ),
    TextMutation(
        "recorder.settle-flow-is-called",
        RECORDER_CONTRACT,
        contracts.RECORDER,
        "        settled = settle_persistence(session)\n",
        "        settled = bypass_settle_persistence(session)\n",
        "native save scenario no longer runs readiness, settle, copy, decode, cross-check, and cleanup end to end",
    ),
    SpecialMutation(
        "recorder.cleanup-in-finally",
        RECORDER_CONTRACT,
        recorder_cleanup_not_in_finally,
        "native save recorder no longer closes exact owned processes from a finally path",
    ),
    TextMutation(
        "recorder.broken-vs-busy",
        RECORDER_CONTRACT,
        contracts.RECORDER,
        "BROKEN: owned process disappeared",
        "BUSY: owned process disappeared",
        "native save recorder no longer proves broken-process stop condition",
    ),
    TextMutation(
        "recorder.forty-sample-floor",
        RECORDER_CONTRACT,
        contracts.RECORDER,
        "SETTLE_SAMPLE_COUNT = 40",
        "SETTLE_SAMPLE_COUNT = 39",
        "native save recorder no longer proves forty-sample settle floor",
    ),
    JsonMutation(
        "recorder.self-derived-source-revision",
        RECORDER_CONTRACT,
        contracts.FIXTURE,
        lambda value: value["provenance"].__setitem__("source_revision", "caller-supplied"),  # type: ignore[index,union-attr]
        "native save fixture no longer identifies its exact source and executable inputs",
    ),
    JsonMutation(
        "recorder.owner-saves-excluded",
        RECORDER_CONTRACT,
        contracts.FIXTURE,
        lambda value: value["provenance"]["capture_contract"].__setitem__("owner_saves_opened", True),  # type: ignore[index,union-attr]
        "native save fixture no longer proves isolated ownership and settle provenance",
    ),
    JsonMutation(
        "recorder.capture-settle-proof",
        RECORDER_CONTRACT,
        contracts.FIXTURE,
        lambda value: _capture(value, 0)["settle_gate"].__setitem__("sample_count", 39),  # type: ignore[index,union-attr]
        "native save capture fresh_profile no longer proves structural settle",
    ),
    TextMutation(
        "lifecycle.section-structure",
        LIFECYCLE,
        contracts.DOC,
        "## Lifecycle\n",
        "### Lifecycle\n",
        "native save document no longer presents files, bytes, semantics, lifecycle, failure, launcher, account, and residuals in reviewable order",
    ),
    TextMutation(
        "lifecycle.complete-file-census",
        LIFECYCLE,
        contracts.DOC,
        "`savegames\\solomondark\\halloffame.dat`",
        "`savegames\\solomondark\\scores.dat`",
        "native save file census no longer covers persistence path(s): ['`savegames\\\\solomondark\\\\halloffame.dat`']",
        True,
    ),
    TextMutation(
        "lifecycle.non-atomic-write",
        LIFECYCLE,
        contracts.DOC,
        "direct create/truncate and one write",
        "safe transactional replace",
        "native save lifecycle no longer documents non-atomic native overwrite",
    ),
    TextMutation(
        "lifecycle.truncated-zero-fill",
        LIFECYCLE,
        contracts.DOC,
        "normalized 135-byte save",
        "normalized 136-byte save",
        "native save failure contract no longer distinguishes truncated zero-fill from missing-profile defaults",
    ),
    TextMutation(
        "lifecycle.importer-fails-closed",
        LIFECYCLE,
        contracts.DOC,
        "and do not create or\nreplace a web save",
        "and create or\nreplace a web save",
        "native save migration boundary no longer refuses corrupt input without overwriting either save",
    ),
    TextMutation(
        "lifecycle.g8-persistence-citation",
        LIFECYCLE,
        contracts.HUB_DOC,
        "participant's gold, backpack, equipment, progression",
        "participant's presentation",
        "G10 lifecycle citation no longer resolves to G8's persistent state witness",
    ),
    TextMutation(
        "lifecycle.skill-serializer-citation",
        LIFECYCLE,
        contracts.SKILL_DOC,
        "progression serializer `0x0065EE80` stores ranks",
        "progression serializer stores unknown data",
        "G10 skill boundary no longer resolves to the landed progression serializer witness",
    ),
    TextMutation(
        "launcher.eight-local-slots",
        LAUNCHER,
        contracts.LOCAL_SAVE_CATALOG,
        "public const int SlotCount = 8;",
        "public const int SlotCount = 7;",
        "launcher Settings no longer owns exactly eight isolated native save roots",
    ),
    TextMutation(
        "launcher.import-root-guard",
        LAUNCHER,
        contracts.LOCAL_SAVE_CATALOG,
        'Path.Combine(sourceSavegamesRootPath, "solomondark")',
        'Path.Combine(sourceSavegamesRootPath, "maybe-solomondark")',
        "launcher import no longer requires one unambiguous savegames/solomondark source before replacement",
    ),
    TextMutation(
        "launcher.directory-swap-order",
        LAUNCHER,
        contracts.SAVE_DIRECTORY_MIRROR,
        "            Directory.Move(incomingPath, destinationPath);",
        "            Directory.Move(incomingPath, destinationPath + \".late\");",
        "launcher save replacement no longer stages incoming, preserves previous, swaps, then retires previous in order",
    ),
    TextMutation(
        "launcher.directory-swap-rollback",
        LAUNCHER,
        contracts.SAVE_DIRECTORY_MIRROR,
        "!Directory.Exists(destinationPath) && Directory.Exists(previousPath)",
        "Directory.Exists(destinationPath) && Directory.Exists(previousPath)",
        "launcher save directory swap no longer restores the previous tree when publication fails",
    ),
    TextMutation(
        "launcher.archive-version",
        LAUNCHER,
        contracts.CLOUD_SAVE_ARCHIVE,
        "public const int FormatVersion = 1;",
        "public const int FormatVersion = 2;",
        "launcher cloud archive no longer enforces archive schema version",
    ),
    TextMutation(
        "launcher.account-list-endpoint",
        LAUNCHER,
        contracts.CLOUD_SAVE_CLIENT,
        '"api/saves"',
        '"api/cloud-saves"',
        'launcher cloud account seam no longer exposes endpoint "api/saves"',
    ),
    TextMutation(
        "launcher.selected-slot-routing-gap",
        LAUNCHER,
        contracts.STAGE_LINKS,
        'var stageSavegamesPath = Path.Combine(stageRootPath, "savegames");',
        'var stageSavegamesPath = Path.Combine(stageRootPath, "sandbox", "savegames");',
        "launcher selected-slot source no longer matches the live-proven stage/savegames-only routing gap",
    ),
    TextMutation(
        "launcher.routing-gap-documented",
        LAUNCHER,
        contracts.DOC,
        "### Current selected-slot routing defect",
        "### Selected-slot routing",
        "G10 launcher/account documentation no longer pins live selected-slot defect",
    ),
    TextMutation(
        "launcher.no-website-scope",
        LAUNCHER,
        contracts.DOC,
        "not add website routes, database tables, or publication",
        "adds website routes and publication",
        "G10 launcher/account documentation no longer pins no-website scope boundary",
    ),
    TextMutation(
        "fixture-hash.reviewed-value",
        FIXTURE_HASH,
        contracts.DOC,
        contracts.EXPECTED_FIXTURE_SHA256,
        "0" + contracts.EXPECTED_FIXTURE_SHA256[1:],
        "native save document's fixture provenance no longer matches the reviewed G10 recording",
    ),
    SpecialMutation(
        "fixture-hash.shared-helper-compares-file",
        FIXTURE_HASH,
        helper_sees_mismatched_committed_hash,
        "G10 save-format fixture provenance does not match its file: recorded f6ab36abbde30b87, save-format-goldens.json hashes to 16ab36abbde30b87",
    ),
)


CONTRACTS: dict[str, Callable[[], str]] = {
    name: getattr(contracts, name)
    for name in (
        CONTAINER,
        ROUND_TRIP,
        DEFAULTS,
        RECORDER_CONTRACT,
        LIFECYCLE,
        LAUNCHER,
        FIXTURE_HASH,
    )
}


def activate(mutation: Mutation) -> AbstractContextManager[None]:
    if isinstance(mutation, TextMutation):
        return text_mutation(mutation)
    if isinstance(mutation, JsonMutation):
        return json_mutation(mutation)
    return mutation.activate()


def green(contract: str) -> str:
    try:
        return CONTRACTS[contract]()
    except Exception as error:  # pragma: no cover - audit failure reporting.
        raise RuntimeError(f"green baseline failed for {contract}: {error}") from error


def run_mutations() -> list[MutationResult]:
    results: list[MutationResult] = []
    for mutation in MUTATIONS:
        clear_contract_bytecode()
        baseline_before = green(mutation.contract)
        clear_contract_bytecode()
        try:
            with activate(mutation):
                CONTRACTS[mutation.contract]()
        except contracts.StaticReTestFailure as error:
            observed = str(error)
        else:
            raise RuntimeError(
                f"mutation {mutation.claim} did not trip {mutation.contract}"
            )
        if observed != mutation.expected:
            raise RuntimeError(
                f"mutation {mutation.claim} failed through the wrong claim:\n"
                f"expected: {mutation.expected}\n"
                f"observed: {observed}"
            )
        clear_contract_bytecode()
        baseline_after = green(mutation.contract)
        results.append(
            MutationResult(
                mutation.claim,
                mutation.contract,
                mutation.expected,
                observed,
                baseline_before,
                baseline_after,
            )
        )
    clear_contract_bytecode()
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    results = run_mutations()
    document = {
        "schema": "solomon-dark-native-save-contract-mutations-v1",
        "mutation_count": len(results),
        "contracts": sorted({result.contract for result in results}),
        "results": [asdict(result) for result in results],
    }
    rendered = json.dumps(document, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
