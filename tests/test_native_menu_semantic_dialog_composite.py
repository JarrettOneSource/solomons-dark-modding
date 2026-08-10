from __future__ import annotations

import copy
import unittest

from tools.native_menu_semantic_dialog_composite import (
    COMPOSITE_ID,
    COMPOSITE_SCHEMA,
    COMPOSITE_SETTLEMENT_SPEC,
    DECOMPOSITION_RESIDUE_REASON,
    DIALOG_REFERENCE_REASON,
    LEGACY_PROVENANCE_REASON,
    OVERLAY_HYGIENE_STOP,
    PAINT_ORDER_REASON,
    SURFACE_AGREEMENT_STOP,
    NativeMenuSemanticDialogCompositeError,
    canonical_sha256,
    classify_semantic_dialog_composite,
    counter_entries,
    semantic_counter,
    semantic_member,
    validate_composite_record,
    validate_qualified_beta_paint_order,
    validate_qualified_beta_supersession,
)


def _member(
    member_id: str,
    *,
    kind: str,
    text: str = "",
    action_id: str = "",
    art_id: str = "",
    interactive: bool = False,
    rect: list[float] | None = None,
) -> dict[str, object]:
    measured = rect or [10.0, 20.0, 30.0, 40.0]
    return {
        "id": member_id,
        "kind": kind,
        "text": text,
        "action_id": action_id,
        "art_id": art_id,
        "font_id": "Fonts.test" if kind == "text" else "",
        "text_style": "native" if kind == "text" else "position",
        "visible": True,
        "interactive": interactive,
        "draw_order": 1,
        "rect": measured,
        "unclipped_rect": list(measured),
    }


def _receipt(name: str, marker: str) -> dict[str, object]:
    return {
        "evidence_path": f"raw-v9/unit/{name}",
        "sha256": marker * 64,
        "bytes": 123,
    }


def _fixture(name: str, marker: str) -> dict[str, object]:
    return {"fixture": name, "sha256": marker * 64, "bytes": 456}


def _inputs() -> tuple[
    list[dict[str, object]],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    underlay_elements = [
        _member(
            "control_scheme_picker.text.prompt.1",
            kind="text",
            text="SELECT A CONTROL SCHEME",
        )
    ]
    plate = _member(
        "control_scheme_picker.art.ui_101.1",
        kind="art",
        art_id="UI.101",
        rect=[702.0, 643.5, 898.0, 712.0],
    )
    dialog_text = _member(
        "control_scheme_picker.text.ok.1",
        kind="text",
        text="OK",
        rect=[782.0, 669.0, 823.0, 687.0],
    )
    full_elements = [*underlay_elements, plate, dialog_text]
    observations: list[dict[str, object]] = []
    for role, process_id in (("primary", 101), ("confirmation", 202)):
        observations.append(
            {
                "role": role,
                "instance": f"menufx-{role}",
                "process_id": process_id,
                "operator_tag": "beta_notice",
                "capture_surface": "dialog",
                "machine_classified_surface": "control_scheme_picker",
                "gate_result": SURFACE_AGREEMENT_STOP,
                "profile_state_identity_sha256": "a" * 64,
                "settled_sample_count": 40,
                "stable_span_milliseconds": 2500,
                "settled_payload": {
                    "screen_id": "control_scheme_picker",
                    "elements": copy.deepcopy(full_elements),
                },
                "recording": _receipt(f"{role}.json", "b"),
                "player_visible_dialog_frame": _receipt(
                    f"{role}.dialog.bmp", "c"
                ),
                "post_dismissal_underlay_frame": _receipt(
                    f"{role}.picker.bmp", "d"
                ),
                "pixel_delta": {
                    "bounding_box": [1, 2, 30, 40],
                    "differing_pixel_count": 99,
                },
            }
        )
    underlay = {
        "screen_id": "control_scheme_picker",
        "elements": underlay_elements,
    }
    overlay = {
        "overlay_semantic_draw_multiset": counter_entries(
            semantic_counter([plate])
        )
    }
    beta = {
        "screen_id": "beta_notice",
        "elements": [
            _member(
                "beta_notice.control.dialog_primary.1",
                kind="control",
                text="OK",
                action_id="dialog.primary",
                interactive=True,
                rect=[702.0, 643.5, 898.0, 712.5],
            )
        ],
    }
    return observations, underlay, overlay, beta


def _record() -> tuple[
    dict[str, object], dict[str, object], dict[str, object], dict[str, object]
]:
    observations, underlay, overlay, beta = _inputs()
    derived = classify_semantic_dialog_composite(
        observations, underlay, overlay, beta
    )
    entries = derived.pop("dialog_semantic_multiset")
    dismissal = derived.pop("dismissal")
    pixel_delta = derived.pop("pixel_delta")
    record: dict[str, object] = {
        "schema": COMPOSITE_SCHEMA,
        "settlement_spec": COMPOSITE_SETTLEMENT_SPEC,
        "composite_id": COMPOSITE_ID,
        "composite": {
            "classification": derived,
            "underlay_binding": {
                "layout_id": "control-scheme-picker",
                "screen_id": "control_scheme_picker",
                "member_count": 1,
                "fixture": _fixture(
                    "menu-layouts/control-scheme-picker.json", "e"
                ),
            },
            "derived_overlay_reference": {
                "fixture": _fixture("menu-overlay-reference.json", "f")
            },
            "qualified_beta_screen": {
                "fixture": _fixture("menu-layouts/beta-notice.json", "1")
            },
            "dialog_semantic_multiset": {
                "member_count": 2,
                "semantic_multiset_sha256": canonical_sha256(entries),
                "entries": entries,
            },
            "observations": observations,
            "dismissal": {**dismissal, "pixel_delta": pixel_delta},
        },
        "navigation": {
            "type": "dialog_composite",
            "entry_state_id": COMPOSITE_ID,
            "dismissal_edge_id": (
                "beta_notice_first_boot_to_control_scheme_picker"
            ),
            "action_id": "dialog.primary",
            "destination_layout_id": "control-scheme-picker",
            "destination_surface_id": "control_scheme_picker",
        },
    }
    return record, underlay, overlay, beta


class NativeMenuSemanticDialogCompositeTests(unittest.TestCase):
    def test_exact_pair_classifies_and_record_validates(self) -> None:
        record, underlay, overlay, beta = _record()
        result = validate_composite_record(record, underlay, overlay, beta)
        self.assertEqual(result["classification"], "semantic_dialog_composite")
        self.assertEqual(result["dialog_member_count"], 2)

    def test_dialog_multiset_difference_from_reference_stops(self) -> None:
        record, underlay, overlay, beta = _record()
        entries = record["composite"]["dialog_semantic_multiset"]["entries"]
        art = next(entry for entry in entries if entry["payload"]["kind"] == "art")
        art["payload"]["art_id"] = "UI.not_the_dialog"
        entries.sort(key=lambda entry: str(sorted(entry["payload"].items())))
        with self.assertRaisesRegex(
            NativeMenuSemanticDialogCompositeError, DIALOG_REFERENCE_REASON
        ):
            validate_composite_record(record, underlay, overlay, beta)

    def test_disabling_model_reproduces_both_production_stops(self) -> None:
        observations, underlay, overlay, beta = _inputs()
        with self.assertRaisesRegex(
            NativeMenuSemanticDialogCompositeError, SURFACE_AGREEMENT_STOP
        ):
            classify_semantic_dialog_composite(
                observations,
                underlay,
                overlay,
                beta,
                model_enabled=False,
                disabled_guard="surface_agreement",
            )
        with self.assertRaisesRegex(
            NativeMenuSemanticDialogCompositeError, OVERLAY_HYGIENE_STOP
        ):
            classify_semantic_dialog_composite(
                observations,
                underlay,
                overlay,
                beta,
                model_enabled=False,
                disabled_guard="overlay_hygiene",
            )

    def test_decomposition_residual_member_stops(self) -> None:
        record, underlay, overlay, beta = _record()
        extra = _member(
            "control_scheme_picker.text.residue.1",
            kind="text",
            text="RESIDUE",
        )
        for observation in record["composite"]["observations"]:
            observation["settled_payload"]["elements"].append(copy.deepcopy(extra))
        with self.assertRaisesRegex(
            NativeMenuSemanticDialogCompositeError,
            DECOMPOSITION_RESIDUE_REASON,
        ):
            validate_composite_record(record, underlay, overlay, beta)

    def test_rederived_paint_order_accepts_exact_core_and_rejects_tamper(
        self,
    ) -> None:
        elements = [
            _member(f"beta_notice.art.{index}.1", kind="art", art_id=f"UI.{index}")
            for index in range(4)
        ]
        layout = {"screen_id": "beta_notice", "elements": elements}
        hashes = [canonical_sha256(semantic_member(element)) for element in elements]
        contract = {
            "schema": "solomon-dark-native-menu-beta-notice-paint-order-v217",
            "layout_id": "beta-notice",
            "screen_id": "beta_notice",
            "core_member_count": 4,
            "ordered_semantic_sha256": hashes,
            "final_paint_group": [
                {"relative_core_index": index, "semantic_sha256": hashes[index]}
                for index in range(1, 4)
            ],
        }
        validate_qualified_beta_paint_order(layout, contract)
        mutated = copy.deepcopy(layout)
        mutated["elements"][0]["rect"][0] += 1.0
        with self.assertRaisesRegex(
            NativeMenuSemanticDialogCompositeError, PAINT_ORDER_REASON
        ):
            validate_qualified_beta_paint_order(mutated, contract)

    def test_unqualified_legacy_beta_core_is_rejected(self) -> None:
        candidate = {
            "header": {"source": {"profile_state_identity_sha256": "a" * 64}},
            "layout": {
                "screen_id": "beta_notice",
                "elements": [_member("beta_notice.art.legacy.1", kind="art", art_id="UI.1")],
            },
        }
        landed_receipt = _fixture("menu-layouts/beta-notice.json", "2")
        candidate_receipt = _fixture("menu-layouts/beta-notice.json", "3")
        contract = {
            "schema": "solomon-dark-native-menu-beta-notice-supersession-v217",
            "settlement_spec": "2.17",
            "layout_id": "beta-notice",
            "screen_id": "beta_notice",
            "retired_landed_fixture": landed_receipt,
            "superseding_qualified_fixture": candidate_receipt,
        }
        with self.assertRaisesRegex(
            NativeMenuSemanticDialogCompositeError, LEGACY_PROVENANCE_REASON
        ):
            validate_qualified_beta_supersession(
                contract,
                landed_fixture_receipt=landed_receipt,
                candidate_fixture_receipt=candidate_receipt,
                candidate_fixture=candidate,
            )


if __name__ == "__main__":
    unittest.main()
