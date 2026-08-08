#!/usr/bin/env python3
"""Machine-derived durable-state provenance for the G11 menu campaign."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any


BASELINE_SCHEMA = "solomon-dark-native-menu-profile-state-baseline-v1"
RECEIPT_SCHEMA = "solomon-dark-native-menu-profile-state-v1"
IDENTITY_SCHEMA = "solomon-dark-native-menu-profile-state-input-v1"
BASELINE_REPO_PATH = Path(
    "tests/fixtures/webgame/native-menu-profile-state-baseline.json"
)
PROFILE_MISMATCH_REASON = "native-menu profile-state provenance mismatch"


class NativeMenuProfileStateError(RuntimeError):
    """A capture does not reproduce the pinned pristine durable state."""


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise NativeMenuProfileStateError(
            f"{label} is not readable JSON: {error}"
        ) from error
    if not isinstance(value, dict):
        raise NativeMenuProfileStateError(f"{label} is not a JSON object")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _lower_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise NativeMenuProfileStateError(
            f"{label} is not a lowercase SHA-256"
        )
    return value


def _identity_payload(profile_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": IDENTITY_SCHEMA,
        "baseline_mode": profile_state.get("baseline_mode"),
        "source_sandbox_excluded": profile_state.get(
            "source_sandbox_excluded"
        ),
        "retail_appdata_seeded": profile_state.get("retail_appdata_seeded"),
        "files": profile_state.get("files"),
    }


def compute_profile_state_identity(profile_state: dict[str, Any]) -> str:
    payload = json.dumps(
        _identity_payload(profile_state),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_profile_state_baseline(repo_root: Path) -> dict[str, Any]:
    path = (repo_root / BASELINE_REPO_PATH).resolve()
    if not path.is_file():
        raise NativeMenuProfileStateError(
            "pinned native-menu profile-state baseline is absent"
        )
    baseline = _read_object(path, "native-menu profile-state baseline")
    if baseline.get("schema") != BASELINE_SCHEMA:
        raise NativeMenuProfileStateError(
            "native-menu profile-state baseline schema is not recognized"
        )
    profile_state = baseline.get("profile_state")
    if not isinstance(profile_state, dict):
        raise NativeMenuProfileStateError(
            "native-menu profile-state baseline has no state payload"
        )
    identity = _lower_sha256(
        profile_state.get("profile_state_identity_sha256"),
        "native-menu profile-state baseline identity",
    )
    if (
        profile_state.get("identity_schema") != IDENTITY_SCHEMA
        or profile_state.get("baseline_mode") != "fresh_install"
        or profile_state.get("source_sandbox_excluded") is not True
        or profile_state.get("retail_appdata_seeded") is not False
        or profile_state.get("files") != []
    ):
        raise NativeMenuProfileStateError(
            "native-menu profile-state baseline is not the pristine fresh-install state"
        )
    if compute_profile_state_identity(profile_state) != identity:
        raise NativeMenuProfileStateError(
            "native-menu profile-state baseline records a false identity"
        )
    return {
        "path": path,
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "identity": identity,
        "profile_state": profile_state,
        "value": baseline,
    }


def materialize_capture_profile_state(
    *,
    repo_root: Path,
    launch_receipt_path: Path,
    evidence_path: Path,
    label: str,
) -> dict[str, Any]:
    baseline = load_profile_state_baseline(repo_root)
    receipt = _read_object(launch_receipt_path, f"{label} launch receipt")
    receipt_state = {
        "baseline_mode": receipt.get("baseline_mode"),
        "source_sandbox_excluded": receipt.get("source_sandbox_excluded"),
        "retail_appdata_seeded": receipt.get("retail_appdata_seeded"),
        "files": receipt.get("files"),
    }
    identity = _lower_sha256(
        receipt.get("profile_state_identity_sha256"),
        f"{label} launch receipt identity",
    )
    if (
        receipt.get("schema") != RECEIPT_SCHEMA
        or receipt_state
        != {
            "baseline_mode": "fresh_install",
            "source_sandbox_excluded": True,
            "retail_appdata_seeded": False,
            "files": [],
        }
        or compute_profile_state_identity(receipt_state) != identity
        or identity != baseline["identity"]
    ):
        raise NativeMenuProfileStateError(
            f"{PROFILE_MISMATCH_REASON}: {label} launch receipt does not "
            "reproduce the pinned pristine state"
        )
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    if evidence_path.exists():
        raise NativeMenuProfileStateError(
            f"{label} profile-state evidence path already exists"
        )
    temporary = evidence_path.with_name(evidence_path.name + ".menufix.tmp")
    try:
        shutil.copyfile(launch_receipt_path, temporary)
        temporary.replace(evidence_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "schema": RECEIPT_SCHEMA,
        "profile_state_identity_sha256": identity,
        "baseline_mode": "fresh_install",
        "source_sandbox_excluded": True,
        "retail_appdata_seeded": False,
        "durable_file_count": 0,
        "baseline_fixture": {
            "repo_relative_path": BASELINE_REPO_PATH.as_posix(),
            "sha256": baseline["sha256"],
            "bytes": baseline["bytes"],
        },
        "launch_receipt": {
            "evidence_filename": evidence_path.name,
            "sha256": sha256_file(evidence_path),
            "bytes": evidence_path.stat().st_size,
        },
    }


def _resolve_unique_receipt(
    evidence_root: Path, evidence_filename: str, label: str
) -> Path:
    if not evidence_filename or Path(evidence_filename).name != evidence_filename:
        raise NativeMenuProfileStateError(
            f"{label} launch receipt filename is unsafe or absent"
        )
    root = evidence_root.resolve()
    matches = sorted(
        path.resolve()
        for path in root.rglob(evidence_filename)
        if path.is_file()
    )
    if len(matches) != 1:
        raise NativeMenuProfileStateError(
            f"{label} launch receipt lookup is absent or ambiguous: {matches}"
        )
    if not matches[0].is_relative_to(root):
        raise NativeMenuProfileStateError(
            f"{label} launch receipt escapes the evidence root"
        )
    return matches[0]


def validate_capture_profile_state(
    *,
    repo_root: Path,
    header: dict[str, Any],
    label: str,
    evidence_root: Path | None,
) -> dict[str, Any]:
    baseline = load_profile_state_baseline(repo_root)
    source = header.get("source")
    profile_state = header.get("profile_state")
    if not isinstance(source, dict) or not isinstance(profile_state, dict):
        raise NativeMenuProfileStateError(
            f"{label} has no machine-derived profile-state provenance"
        )
    identity = _lower_sha256(
        profile_state.get("profile_state_identity_sha256"),
        f"{label} profile-state identity",
    )
    source_identity = _lower_sha256(
        source.get("profile_state_identity_sha256"),
        f"{label} source profile-state identity",
    )
    if identity != baseline["identity"] or source_identity != baseline["identity"]:
        raise NativeMenuProfileStateError(
            f"{PROFILE_MISMATCH_REASON}: {label} identity '{identity}' does not "
            f"equal pinned baseline '{baseline['identity']}'"
        )
    if (
        profile_state.get("schema") != RECEIPT_SCHEMA
        or profile_state.get("baseline_mode") != "fresh_install"
        or profile_state.get("source_sandbox_excluded") is not True
        or profile_state.get("retail_appdata_seeded") is not False
        or profile_state.get("durable_file_count") != 0
    ):
        raise NativeMenuProfileStateError(
            f"{label} does not prove the pristine fresh-install file state"
        )
    baseline_receipt = profile_state.get("baseline_fixture")
    if not isinstance(baseline_receipt, dict):
        raise NativeMenuProfileStateError(
            f"{label} has no committed profile-state baseline receipt"
        )
    if (
        baseline_receipt.get("repo_relative_path")
        != BASELINE_REPO_PATH.as_posix()
        or baseline_receipt.get("sha256") != baseline["sha256"]
        or baseline_receipt.get("bytes") != baseline["bytes"]
    ):
        raise NativeMenuProfileStateError(
            f"{label} records a false committed profile-state baseline receipt"
        )
    launch_receipt = profile_state.get("launch_receipt")
    if not isinstance(launch_receipt, dict):
        raise NativeMenuProfileStateError(
            f"{label} has no exact pre-launch profile-state receipt"
        )
    expected_sha256 = _lower_sha256(
        launch_receipt.get("sha256"), f"{label} launch receipt SHA-256"
    )
    expected_bytes = launch_receipt.get("bytes")
    if (
        isinstance(expected_bytes, bool)
        or not isinstance(expected_bytes, int)
        or expected_bytes <= 0
    ):
        raise NativeMenuProfileStateError(
            f"{label} launch receipt has no positive byte count"
        )
    if evidence_root is not None:
        filename = launch_receipt.get("evidence_filename")
        if not isinstance(filename, str):
            raise NativeMenuProfileStateError(
                f"{label} launch receipt has no evidence filename"
            )
        receipt_path = _resolve_unique_receipt(evidence_root, filename, label)
        if (
            receipt_path.stat().st_size != expected_bytes
            or sha256_file(receipt_path) != expected_sha256
        ):
            raise NativeMenuProfileStateError(
                f"{label} launch receipt byte/hash provenance is false"
            )
        receipt = _read_object(receipt_path, f"{label} launch receipt")
        receipt_state = {
            "baseline_mode": receipt.get("baseline_mode"),
            "source_sandbox_excluded": receipt.get("source_sandbox_excluded"),
            "retail_appdata_seeded": receipt.get("retail_appdata_seeded"),
            "files": receipt.get("files"),
        }
        receipt_identity = _lower_sha256(
            receipt.get("profile_state_identity_sha256"),
            f"{label} launch receipt identity",
        )
        if (
            receipt.get("schema") != RECEIPT_SCHEMA
            or receipt_state != {
                "baseline_mode": "fresh_install",
                "source_sandbox_excluded": True,
                "retail_appdata_seeded": False,
                "files": [],
            }
            or compute_profile_state_identity(receipt_state) != receipt_identity
            or receipt_identity != baseline["identity"]
        ):
            raise NativeMenuProfileStateError(
                f"{PROFILE_MISMATCH_REASON}: {label} launch receipt does not "
                "reproduce the pinned pristine state"
            )
    return {
        "identity": identity,
        "baseline_sha256": baseline["sha256"],
        "baseline_bytes": baseline["bytes"],
        "launch_receipt_sha256": expected_sha256,
        "launch_receipt_bytes": expected_bytes,
    }
