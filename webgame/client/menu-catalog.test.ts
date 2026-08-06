import menuGoldenJson from "../../tests/fixtures/webgame/menu-goldens.json" with { type: "json" };
import { describe, expect, it } from "vitest";

import { parseMenuCatalog } from "./menu-catalog.js";

describe("landed G11 menu catalog", () => {
  it("parses the one authoritative 28-screen, 39-edge recording", () => {
    const catalog = parseMenuCatalog(menuGoldenJson);
    expect(catalog.screenCensus).toHaveLength(28);
    expect(catalog.layouts).toHaveLength(28);
    expect(catalog.navigationEdges).toHaveLength(39);
    expect(catalog.layouts.get("native-loader")?.referenceCapture)
      .toBe("menu-reference-captures/native-loader.png");
    expect(catalog.layouts.get("main-menu-root")?.elements)
      .toContainEqual(expect.objectContaining({
        actionId: "main_menu.play",
        rect: [673.5, 421, 1026.5, 490],
      }));
  });

  it("refuses a screen census that no longer names exactly 28 unique layouts", () => {
    const value = structuredClone(menuGoldenJson) as Record<string, unknown>;
    value.screen_census = ["native-loader"];
    expect(() => parseMenuCatalog(value)).toThrow("exactly 28 unique layouts");
  });

  it("refuses duplicate layout fixture candidates", () => {
    const value = structuredClone(menuGoldenJson) as { layouts: unknown[] };
    value.layouts[1] = value.layouts[0];
    expect(() => parseMenuCatalog(value)).toThrow("ambiguously defines beta-notice twice");
  });

  it("refuses a graph that is no longer the complete 39-edge live recording", () => {
    const value = structuredClone(menuGoldenJson) as {
      navigation_graph: { edges: unknown[] };
    };
    value.navigation_graph.edges.pop();
    expect(() => parseMenuCatalog(value)).toThrow("exactly 39 unique live edges");
  });
});
