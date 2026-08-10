from __future__ import annotations

import copy
import unittest

from tools.native_menu_nonsemantic_overlay import (
    OVERLAY_SCHEMA,
    OVERLAY_SETTLEMENT_SPEC,
    SEMANTIC_MEMBER_REASON,
    TAG_AGREEMENT_CLASSIFICATION_REASON,
    TAG_DISAGREEMENT_REASON,
    NativeMenuNonSemanticOverlayError,
    classify_nonsemantic_overlay,
    validate_overlay_record,
)


def _receipt(name: str) -> dict[str, object]:
    return {
        "evidence_path": f"raw-v9/unit/{name}",
        "sha256": "a" * 64,
        "bytes": 123,
    }


def _observation(role: str, process_id: int) -> dict[str, object]:
    return {
        "role": role,
        "instance": f"menufx-{role}",
        "process_id": process_id,
        "operator_tag": "dark_cloud_settings",
        "machine_surface": "main_menu",
        "profile_state_identity_sha256": "b" * 64,
        "settled_sample_count": 40,
        "stable_span_milliseconds": 2500,
        "text_action_member_count": 11,
        "text_action_payload_sha256": "c" * 64,
        "recording": _receipt(f"{role}.recording.json"),
        "gate_transcript": _receipt(f"{role}.gate.log"),
        "player_visible_frame": {
            "overlay": _receipt(f"{role}.overlay.bmp"),
            "accepted_underlying_surface": _receipt(
                f"{role}.main-menu.bmp"
            ),
            "comparison_crop": [492, 92, 1108, 808],
            "crop_difference_bbox": [0, 0, 616, 716],
            "differing_pixel_count": 40000,
            "differs": True,
        },
    }


def _record() -> dict[str, object]:
    observations = [
        _observation("primary", 101),
        _observation("confirmation", 202),
    ]
    classification = classify_nonsemantic_overlay(
        {"observations": observations}
    )
    return {
        "schema": OVERLAY_SCHEMA,
        "settlement_spec": OVERLAY_SETTLEMENT_SPEC,
        "overlay_id": "dark_cloud_settings_credentials",
        "overlay": {
            "classification": classification,
            "members_semantically_observable": False,
            "semantic_member_count": 0,
            "semantic_members": [],
            "observations": observations,
            "activation": {
                "edge_id": "settings_to_dark_cloud_settings",
                "trigger": "login_info_modify_click",
                "route": "main menu -> title settings -> measured MODIFY -> credentials overlay",
                "measured_control": {
                    "source_layout_id": "game-settings-title",
                    "member_id": "settings.text.dark_cloud_settings.1",
                    "text": "DARK CLOUD SETTINGS",
                    "rect": [1043.0, 487.5, 1057.0, 502.5],
                    "click_point": [1050.0, 495.0],
                    "point_derivation": "center of the unique visible measured row member",
                },
                "source_frames": [
                    _receipt("primary.source.bmp"),
                    _receipt("confirmation.source.bmp"),
                ],
                "evidence_only": True,
                "typed_into_credentials": False,
                "durable_dark_cloud_state_mutated": False,
            },
            "semantic_underlay_binding": {
                "screen_id": "dark_cloud_settings",
                "operator_machine_tag_agreement": True,
                "route": "pause -> game settings -> measured MODIFY -> credentials overlay",
                "layout_fixture": "menu-overlay-underlays/dark-cloud-settings.json",
                "primary_fixture": _receipt("underlay.json"),
                "primary_trace": _receipt("underlay.trace.json"),
                "confirmation": _receipt("underlay.confirmation.json"),
                "route_receipts": [
                    _receipt("primary.route.log"),
                    _receipt("confirmation.route.log"),
                ],
                "bound_endpoints": [
                    "settings_to_dark_cloud_settings.after",
                    "dark_cloud_settings_to_settings.before",
                ],
                "primary_structural_sha256": "d" * 64,
                "confirmation_structural_sha256": "e" * 64,
            },
            "supersession": {
                "retired_landed_screen_fixture": _receipt(
                    "landed-dark-cloud-settings.json"
                ),
                "retired_element_count": 31,
                "replacement_kind": "overlay_record",
            },
            "motion_witness_disposition": {
                "element_id": "dark_cloud_settings.art.ui_28.1",
                "disposition": "retired_with_nonsemantic_screen_fixture",
            },
        },
    }


class NativeMenuNonSemanticOverlayTests(unittest.TestCase):
    def test_exact_pair_classifies_and_record_validates(self) -> None:
        record = _record()
        result = validate_overlay_record(record)
        self.assertEqual(result["classification"], "non_semantic_overlay")
        self.assertEqual(result["underlying_surface_id"], "main_menu")

    def test_tag_agreeing_screen_cannot_be_forced_through_overlay_seam(self) -> None:
        pair = {
            "observations": [
                _observation("primary", 101),
                _observation("confirmation", 202),
            ]
        }
        pair["observations"][0]["operator_tag"] = "main_menu"
        with self.assertRaisesRegex(
            NativeMenuNonSemanticOverlayError,
            TAG_AGREEMENT_CLASSIFICATION_REASON,
        ):
            classify_nonsemantic_overlay(pair)

    def test_disabling_overlay_seam_reproduces_exact_capture_stop(self) -> None:
        pair = {
            "observations": [
                _observation("primary", 101),
                _observation("confirmation", 202),
            ]
        }
        with self.assertRaisesRegex(
            NativeMenuNonSemanticOverlayError,
            TAG_DISAGREEMENT_REASON,
        ):
            classify_nonsemantic_overlay(pair, seam_enabled=False)

    def test_overlay_cannot_claim_semantic_members(self) -> None:
        record = copy.deepcopy(_record())
        record["overlay"]["members_semantically_observable"] = True
        record["overlay"]["semantic_member_count"] = 1
        record["overlay"]["semantic_members"] = [{"id": "forbidden"}]
        with self.assertRaisesRegex(
            NativeMenuNonSemanticOverlayError,
            SEMANTIC_MEMBER_REASON,
        ):
            validate_overlay_record(record)


if __name__ == "__main__":
    unittest.main()
