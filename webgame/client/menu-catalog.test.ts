import menuGoldenJson from "../../tests/fixtures/webgame/menufix-preview-overlay/menu-goldens.json" with { type: "json" };
import overlayManifestJson from "../../tests/fixtures/webgame/menufix-preview-overlay/overlay-manifest.json" with { type: "json" };
import { describe, expect, it } from "vitest";

import { parseMenuCatalog } from "./menu-catalog.js";

describe("menufix preview aggregate menu catalog", () => {
  it("parses every standard layout, transition endpoint, overlay, composite, and graph edge", () => {
    const catalog = parseMenuCatalog(menuGoldenJson);
    expect(catalog.standardLayoutIds).toHaveLength(27);
    expect(catalog.transitionLayoutIds).toEqual([
      "hub_new_game",
      "hub_pristine_second_new_game",
      "hub_resumed",
    ]);
    expect(catalog.screenCensus).toHaveLength(30);
    expect(catalog.layouts.size).toBe(catalog.screenCensus.length);
    expect(catalog.navigationEdges).toHaveLength(40);
    expect(catalog.layouts.get("native-loader")?.referenceCapture)
      .toBe("menu-reference-captures/native-loader.png");
    expect(catalog.layouts.get("main-menu-root")?.elements)
      .toContainEqual(expect.objectContaining({
        actionId: "main_menu.play",
        rect: [673.5, 421, 1026.5, 490],
      }));
    expect(catalog.layouts.get("profile-save-select")?.elements)
      .toContainEqual(expect.objectContaining({
        actionId: "main_menu.new_game",
        interactive: true,
        rect: [673.5, 497, 1026.5, 566],
      }));
    expect(catalog.layouts.get("main-menu-root")?.ambientElements).toHaveLength(19);
    expect(catalog.layouts.get("create-element")?.ambientElements)
      .toContainEqual(expect.objectContaining({ artId: "Create.7", visible: true }));
    expect(catalog.layouts.get("beta-notice")?.elements).toHaveLength(28);
    expect(catalog.layouts.get("beta-notice")?.semanticDialogElements).toHaveLength(13);
  });

  it("builds the measured first-boot dialog over its five-member picker underlay", () => {
    const catalog = parseMenuCatalog(menuGoldenJson);
    const composite = catalog.dialogComposites.get("beta_notice_first_boot");
    expect(composite).toEqual(expect.objectContaining({
      sha256: "c647f89672c158572054499879960f8afcd912653420cb0d75fed06edb40d97d",
      bytes: 81817,
      underlayLayoutId: "control-scheme-picker",
      destinationLayoutId: "control-scheme-picker",
      actionId: "dialog.primary",
      actionRect: [702, 643.5, 898, 712.5],
      dialogMemberCount: 28,
      residualMemberCount: 0,
    }));
    expect(composite?.layout.elements).toHaveLength(33);
    expect(composite?.layout.elements.slice(0, 5))
      .toEqual(catalog.layouts.get("control-scheme-picker")?.elements);
  });

  it("consumes the v2.15 zero-member overlay record as an overlay, not a screen", () => {
    const catalog = parseMenuCatalog(menuGoldenJson);
    expect(catalog.overlayRecords.get("dark_cloud_settings_credentials")).toEqual(
      expect.objectContaining({
        settlementSpec: "2.15",
        classification: "non_semantic_overlay",
        underlyingSurfaceId: "main_menu",
        semanticMemberCount: 0,
        underlayScreenId: "dark_cloud_settings",
      }),
    );
    expect(catalog.layouts.has("dark-cloud-settings")).toBe(false);
  });

  it("keeps the authorized aggregate pin in the adjacent provenance sidecar", () => {
    expect(overlayManifestJson).toEqual(expect.objectContaining({
      preview_overlay_of_menufix_evidence: true,
      authorized_artifact_sha: "574785f257a915777d3ef151a3c79ac704a5b3b096aa83ed446315a216bcfec3",
      authorized_artifact_bytes: 10143049,
    }));
    expect(overlayManifestJson.source_ledger_note).toContain("sole integrity gate");
  });

  it("refuses a census that disagrees with the combined layout records", () => {
    const value = structuredClone(menuGoldenJson) as Record<string, unknown>;
    value.screen_census = ["native-loader"];
    expect(() => parseMenuCatalog(value)).toThrow("complete screen census");
  });

  it("refuses duplicate layout fixture candidates", () => {
    const value = structuredClone(menuGoldenJson) as { layouts: unknown[] };
    value.layouts[1] = value.layouts[0];
    expect(() => parseMenuCatalog(value)).toThrow("ambiguously defines beta-notice twice");
  });

  it("refuses duplicate graph edge identities without pinning a graph count", () => {
    const value = structuredClone(menuGoldenJson) as {
      navigation_graph: { edges: unknown[] };
    };
    value.navigation_graph.edges[1] = value.navigation_graph.edges[0];
    expect(() => parseMenuCatalog(value)).toThrow("unique live edges");
  });

  it("requires every graph edge to carry a resolvable destination fixture binding", () => {
    const value = structuredClone(menuGoldenJson) as {
      navigation_graph: { edges: Array<Record<string, unknown>> };
    };
    const firstEdge = value.navigation_graph.edges[0];
    expect(firstEdge).toBeDefined();
    if (firstEdge === undefined) {
      throw new Error("aggregate graph unexpectedly contains no edges");
    }
    firstEdge.destination_layout_fixture = "menu-layouts/missing.json";
    expect(() => parseMenuCatalog(value)).toThrow("binds missing destination layout missing");
  });
});
