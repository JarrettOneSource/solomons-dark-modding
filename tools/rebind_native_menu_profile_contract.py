#!/usr/bin/env python3
"""Rebind derived menu candidates to the current profile binding contract.

This does not alter capture provenance.  It verifies each prior contract receipt
against repository history (or the byte-exact CRLF representation of the
current committed JSON), proves that the recorded profile identity is still a
member of the same baseline, and then updates only the derived candidate's
binding-contract receipt.  Raw recorder artifacts outside the candidate root
are never edited.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, BinaryIO

if __package__:
    from .native_menu_profile_state import (
        DERIVED_HUB_BASELINE_ID,
        FRESH_BASELINE_ID,
        HUB_BINDINGS_REPO_PATH,
        load_hub_binding_contract,
    )
else:
    from native_menu_profile_state import (
        DERIVED_HUB_BASELINE_ID,
        FRESH_BASELINE_ID,
        HUB_BINDINGS_REPO_PATH,
        load_hub_binding_contract,
    )


class ProfileContractRebindError(RuntimeError):
    """The candidate cannot be bound to the current exact contract."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def receipt(path: Path) -> dict[str, Any]:
    return {"sha256": sha256_file(path), "bytes": path.stat().st_size}


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256_bytes(payload)


def read_object_bytes(value: bytes, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProfileContractRebindError(
            f"{label} is not readable JSON: {error}"
        ) from error
    if not isinstance(parsed, dict):
        raise ProfileContractRebindError(f"{label} is not a JSON object")
    return parsed


def read_object(path: Path, label: str) -> dict[str, Any]:
    return read_object_bytes(path.read_bytes(), label)


def write_object_atomically(path: Path, value: Any) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def git_contract_versions(repo_root: Path) -> dict[tuple[str, int], dict[str, Any]]:
    relative = HUB_BINDINGS_REPO_PATH.as_posix()
    result = subprocess.run(
        ["git", "rev-list", "--all", "--", relative],
        cwd=repo_root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    commits = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not commits:
        raise ProfileContractRebindError(
            "profile binding contract history has no committed witness"
        )
    versions: dict[tuple[str, int], dict[str, Any]] = {}
    for commit in commits:
        blob = subprocess.run(
            ["git", "show", f"{commit}:{relative}"],
            cwd=repo_root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if blob.returncode != 0:
            continue
        value = read_object_bytes(blob.stdout, f"binding contract at {commit}")
        key = (sha256_bytes(blob.stdout), len(blob.stdout))
        versions.setdefault(
            key,
            {
                "kind": "committed_predecessor",
                "commit": commit,
                "semantic_sha256": canonical_sha256(value),
                "value": value,
            },
        )
    if not versions:
        raise ProfileContractRebindError(
            "profile binding contract history yielded no readable content"
        )
    return versions


def baseline_for_identity(contract: dict[str, Any], identity: str) -> str | None:
    baselines = contract.get("baselines")
    if not isinstance(baselines, dict):
        return None
    fresh = baselines.get(FRESH_BASELINE_ID)
    if (
        isinstance(fresh, dict)
        and fresh.get("profile_state_identity_sha256") == identity
    ):
        return FRESH_BASELINE_ID
    derived = baselines.get(DERIVED_HUB_BASELINE_ID)
    witnesses = derived.get("witnesses") if isinstance(derived, dict) else None
    if isinstance(witnesses, list) and any(
        isinstance(witness, dict)
        and witness.get("profile_state_identity_sha256") == identity
        for witness in witnesses
    ):
        return DERIVED_HUB_BASELINE_ID
    return None


def read_profile_state_block(
    first_line: bytes, source: BinaryIO, label: str
) -> bytes:
    block = bytearray(first_line)
    opening = first_line.find(b"{")
    if opening < 0:
        raise ProfileContractRebindError(
            f"{label} profile-state block has no opening object"
        )
    depth = first_line[opening:].count(b"{") - first_line[opening:].count(b"}")
    while depth > 0:
        line = source.readline()
        if not line:
            raise ProfileContractRebindError(
                f"{label} profile-state block is truncated"
            )
        block.extend(line)
        depth += line.count(b"{") - line.count(b"}")
    if depth != 0:
        raise ProfileContractRebindError(
            f"{label} profile-state braces are unbalanced"
        )
    return bytes(block)


def profile_object_from_block(block: bytes, label: str) -> dict[str, Any]:
    opening = block.find(b"{")
    depth = 0
    closing = -1
    for index in range(opening, len(block)):
        byte = block[index]
        if byte == ord("{"):
            depth += 1
        elif byte == ord("}"):
            depth -= 1
            if depth == 0:
                closing = index + 1
                break
    if opening < 0 or closing < 0:
        raise ProfileContractRebindError(
            f"{label} profile-state object boundaries are absent"
        )
    return read_object_bytes(block[opening:closing], f"{label} profile state")


def replace_receipt_in_block(
    block: bytes,
    old_receipt: dict[str, Any],
    current_receipt: dict[str, Any],
    label: str,
) -> bytes:
    old_hash = str(old_receipt["sha256"]).encode("ascii")
    new_hash = str(current_receipt["sha256"]).encode("ascii")
    old_bytes = str(old_receipt["bytes"]).encode("ascii")
    new_bytes = str(current_receipt["bytes"]).encode("ascii")
    if block.count(old_hash) != 1:
        raise ProfileContractRebindError(
            f"{label} binding-contract hash is not uniquely replaceable"
        )
    hash_replaced = block.replace(old_hash, new_hash, 1)
    marker = b'"bytes"'
    contract_at = hash_replaced.find(b'"binding_contract"')
    bytes_at = hash_replaced.find(marker, contract_at)
    if contract_at < 0 or bytes_at < 0:
        raise ProfileContractRebindError(
            f"{label} binding-contract byte receipt is absent"
        )
    value_at = hash_replaced.find(old_bytes, bytes_at)
    if value_at < 0:
        raise ProfileContractRebindError(
            f"{label} binding-contract byte count is not replaceable"
        )
    return (
        hash_replaced[:value_at]
        + new_bytes
        + hash_replaced[value_at + len(old_bytes) :]
    )


def rebind_file(
    path: Path,
    known_versions: dict[tuple[str, int], dict[str, Any]],
    current_contract: dict[str, Any],
    current_receipt: dict[str, Any],
    *,
    apply: bool,
) -> dict[str, Any]:
    before = receipt(path)
    temporary = path.with_name(path.name + ".profile-rebind.tmp")
    occurrence_count = 0
    changed_count = 0
    classifications: Counter[str] = Counter()
    identities: Counter[str] = Counter()
    current_key = (current_receipt["sha256"], current_receipt["bytes"])
    destination_path = temporary if apply else Path(os.devnull)
    try:
        with path.open("rb") as source, destination_path.open("wb") as destination:
            while True:
                line = source.readline()
                if not line:
                    break
                if re.search(rb'"profile_state"\s*:\s*\{', line) is None:
                    destination.write(line)
                    continue
                block = read_profile_state_block(line, source, str(path))
                profile_state = profile_object_from_block(block, str(path))
                identity = profile_state.get("profile_state_identity_sha256")
                recorded = profile_state.get("binding_contract")
                if not isinstance(identity, str) or not isinstance(recorded, dict):
                    raise ProfileContractRebindError(
                        f"{path} profile-state block lacks identity or binding receipt"
                    )
                if recorded.get("repo_relative_path") != HUB_BINDINGS_REPO_PATH.as_posix():
                    raise ProfileContractRebindError(
                        f"{path} profile-state block names a different binding contract"
                    )
                key = (recorded.get("sha256"), recorded.get("bytes"))
                if key == current_key:
                    version = {
                        "kind": "current_committed_contract",
                        "value": current_contract,
                    }
                else:
                    version = known_versions.get(key)
                if version is None:
                    raise ProfileContractRebindError(
                        f"{path} profile-state block records an unproven contract receipt {key}"
                    )
                prior_baseline = baseline_for_identity(version["value"], identity)
                current_baseline = baseline_for_identity(current_contract, identity)
                if prior_baseline is None or prior_baseline != current_baseline:
                    raise ProfileContractRebindError(
                        "profile binding contract rebind changed the capture's baseline "
                        f"identity for {path}: {identity}"
                    )
                recorded_baseline = profile_state.get("baseline_id")
                if recorded_baseline is not None and recorded_baseline != current_baseline:
                    raise ProfileContractRebindError(
                        f"{path} profile-state block records a false baseline id"
                    )
                occurrence_count += 1
                identities[identity] += 1
                classifications[version["kind"]] += 1
                if key != current_key:
                    changed_count += 1
                    block = replace_receipt_in_block(
                        block, recorded, current_receipt, str(path)
                    )
                destination.write(block)
        if occurrence_count == 0:
            raise ProfileContractRebindError(
                f"{path} profile-state sweep reached no real content"
            )
        if apply:
            os.replace(temporary, path)
    except Exception:
        if apply and temporary.exists():
            temporary.unlink()
        raise
    after = receipt(path) if apply else before
    return {
        "path": str(path),
        "profile_state_blocks": occurrence_count,
        "rebound_blocks": changed_count,
        "prior_contract_classes": dict(sorted(classifications.items())),
        "profile_state_identities": dict(sorted(identities.items())),
        "before": before,
        "after": after,
    }


def update_fixture_receipts(candidate_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    fixture_paths = sorted((candidate_root / "menu-layouts").glob("*.json"))
    fixture_paths += sorted(
        (candidate_root / "menu-transition-layouts").glob("*.json")
    )
    if len(fixture_paths) != 31:
        raise ProfileContractRebindError(
            "profile binding rebind did not reach the exact 31-layout fixture census"
        )
    for fixture_path in fixture_paths:
        value = read_object(fixture_path, str(fixture_path))
        header = value.get("header")
        if not isinstance(header, dict):
            raise ProfileContractRebindError(f"{fixture_path} has no header")
        trace_receipt = header.get("settlement_trace", header.get("raw_recording"))
        confirmation_receipt = header.get("animation_confirmation")
        if not isinstance(trace_receipt, dict) or not isinstance(
            confirmation_receipt, dict
        ):
            raise ProfileContractRebindError(
                f"{fixture_path} lacks trace or confirmation receipts"
            )
        trace_path = (
            candidate_root
            / "menu-settlement-traces"
            / str(trace_receipt.get("evidence_filename", ""))
        )
        confirmation_path = (
            candidate_root
            / "menu-animation-confirmations"
            / str(confirmation_receipt.get("evidence_filename", ""))
        )
        if not trace_path.is_file() or not confirmation_path.is_file():
            raise ProfileContractRebindError(
                f"{fixture_path} derived evidence is absent"
            )
        trace_receipt.update(receipt(trace_path))
        confirmation_receipt.update(receipt(confirmation_path))
        write_object_atomically(fixture_path, value)
        rows.append(
            {
                "fixture": str(fixture_path),
                "settlement_trace": {"path": str(trace_path), **receipt(trace_path)},
                "animation_confirmation": {
                    "path": str(confirmation_path),
                    **receipt(confirmation_path),
                },
                "fixture_receipt": receipt(fixture_path),
            }
        )
    return rows


def run(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = args.repo_root.resolve()
    candidate_root = args.candidate_root.resolve()
    contract = load_hub_binding_contract(repo_root)
    current_value = contract["value"]
    current_receipt = {
        "repo_relative_path": HUB_BINDINGS_REPO_PATH.as_posix(),
        "sha256": contract["sha256"],
        "bytes": contract["bytes"],
    }
    known = git_contract_versions(repo_root)
    current_bytes = contract["path"].read_bytes()
    if b"\r\n" in current_bytes:
        raise ProfileContractRebindError(
            "committed profile binding contract is not LF-normalized"
        )
    crlf_bytes = current_bytes.replace(b"\n", b"\r\n")
    known[(sha256_bytes(crlf_bytes), len(crlf_bytes))] = {
        "kind": "current_contract_crlf_worktree_equivalent",
        "commit": None,
        "semantic_sha256": canonical_sha256(current_value),
        "value": copy.deepcopy(current_value),
    }

    candidate_paths = sorted((candidate_root / "menu-layouts").glob("*.json"))
    candidate_paths += sorted(
        (candidate_root / "menu-transition-layouts").glob("*.json")
    )
    trace_paths = sorted(
        (candidate_root / "menu-settlement-traces").glob("*.settlement.json")
    )
    confirmation_paths = sorted(
        (candidate_root / "menu-animation-confirmations").glob(
            "*.confirmation.json"
        )
    )
    if not (
        len(candidate_paths) == len(trace_paths) == len(confirmation_paths) == 31
    ):
        raise ProfileContractRebindError(
            "profile binding rebind did not reach 31 fixtures, traces, and confirmations"
        )
    navigation_paths = [
        args.primary_navigation.resolve(),
        args.confirmation_navigation.resolve(),
    ]
    if not all(path.is_file() for path in navigation_paths):
        raise ProfileContractRebindError(
            "profile binding rebind did not reach both navigation recordings"
        )

    file_rows = [
        rebind_file(
            path,
            known,
            current_value,
            current_receipt,
            apply=args.apply,
        )
        for path in candidate_paths + trace_paths + confirmation_paths + navigation_paths
    ]
    navigation_counts = [
        row["profile_state_blocks"] for row in file_rows[-len(navigation_paths) :]
    ]
    if navigation_counts[0] != navigation_counts[1] or navigation_counts[0] < 39:
        raise ProfileContractRebindError(
            "profile binding rebind did not reach matching real content in both 39-edge recordings"
        )
    fixture_receipts = update_fixture_receipts(candidate_root) if args.apply else []
    if fixture_receipts:
        final_fixture_receipts = {
            row["fixture"]: row["fixture_receipt"] for row in fixture_receipts
        }
        for row in file_rows:
            final_receipt = final_fixture_receipts.get(row["path"])
            if final_receipt is not None:
                row["after"] = final_receipt
    if args.verify and any(row["rebound_blocks"] for row in file_rows):
        raise ProfileContractRebindError(
            "profile binding contract verification found an un-rebound candidate"
        )
    audit = {
        "schema": "solomon-dark-native-menu-profile-contract-rebind-v1",
        "current_contract": {
            "repo_relative_path": HUB_BINDINGS_REPO_PATH.as_posix(),
            "sha256": contract["sha256"],
            "bytes": contract["bytes"],
            "semantic_sha256": canonical_sha256(current_value),
        },
        "candidate_root": str(candidate_root),
        "apply": bool(args.apply),
        "verify": bool(args.verify),
        "layout_fixture_count": len(candidate_paths),
        "settlement_trace_count": len(trace_paths),
        "confirmation_count": len(confirmation_paths),
        "navigation_recording_count": len(navigation_paths),
        "profile_state_block_count": sum(
            row["profile_state_blocks"] for row in file_rows
        ),
        "rebound_block_count": sum(row["rebound_blocks"] for row in file_rows),
        "files": file_rows,
        "updated_fixture_receipts": fixture_receipts,
    }
    if args.audit_output is not None:
        write_object_atomically(args.audit_output.resolve(), audit)
    return audit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--primary-navigation", type=Path, required=True)
    parser.add_argument("--confirmation-navigation", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify", action="store_true")
    return parser.parse_args()


def main() -> int:
    try:
        result = run(parse_args())
    except (OSError, subprocess.SubprocessError, ProfileContractRebindError) as error:
        print(json.dumps({"success": False, "error": str(error)}))
        return 1
    print(json.dumps({"success": True, **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
