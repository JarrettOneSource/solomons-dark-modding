export type NativeRect = readonly [number, number, number, number];

export interface MenuElement {
  readonly id: string;
  readonly kind: string;
  readonly text: string;
  readonly actionId: string;
  readonly artId: string;
  readonly fontId: string;
  readonly textStyle: string;
  readonly visible: boolean;
  readonly interactive: boolean;
  readonly drawOrder: number;
  readonly rect: NativeRect;
  readonly unclippedRect: NativeRect;
  readonly color?: string;
  readonly colorTop?: string;
  readonly colorBottom?: string;
  readonly fontHeight?: number;
  readonly fontWeight?: number;
}

export interface MenuLayout {
  readonly id: string;
  readonly screenId: string;
  readonly title: string;
  readonly captureMethod: string;
  readonly fixture: string;
  readonly referenceCapture: string;
  readonly referenceSha256: string;
  readonly elements: readonly MenuElement[];
}

export interface NavigationEdge {
  readonly id: string;
  readonly source: string;
  readonly actionId: string;
  readonly destination: string;
}

export interface MenuCatalog {
  readonly layouts: ReadonlyMap<string, MenuLayout>;
  readonly screenCensus: readonly string[];
  readonly navigationEdges: readonly NavigationEdge[];
}

type JsonObject = Record<string, unknown>;

function object(value: unknown, label: string): JsonObject {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as JsonObject;
}

function string(value: unknown, label: string): string {
  if (typeof value !== "string") {
    throw new Error(`${label} must be a string`);
  }
  return value;
}

function boolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`${label} must be a boolean`);
  }
  return value;
}

function number(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${label} must be a finite number`);
  }
  return value;
}

function array(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`${label} must be an array`);
  }
  return value;
}

function rect(value: unknown, label: string): NativeRect {
  const values = array(value, label);
  if (values.length !== 4) {
    throw new Error(`${label} must be a native [left, top, right, bottom] rectangle`);
  }
  return [
    number(values[0], `${label}[0]`),
    number(values[1], `${label}[1]`),
    number(values[2], `${label}[2]`),
    number(values[3], `${label}[3]`),
  ];
}

function parseElement(value: unknown, layoutId: string, index: number): MenuElement {
  const source = object(value, `${layoutId}.elements[${index}]`);
  const element: MenuElement = {
    id: string(source.id, `${layoutId}.elements[${index}].id`),
    kind: string(source.kind, `${layoutId}.elements[${index}].kind`),
    text: string(source.text, `${layoutId}.elements[${index}].text`),
    actionId: string(source.action_id, `${layoutId}.elements[${index}].action_id`),
    artId: string(source.art_id, `${layoutId}.elements[${index}].art_id`),
    fontId: string(source.font_id, `${layoutId}.elements[${index}].font_id`),
    textStyle: string(source.text_style, `${layoutId}.elements[${index}].text_style`),
    visible: boolean(source.visible, `${layoutId}.elements[${index}].visible`),
    interactive: boolean(source.interactive, `${layoutId}.elements[${index}].interactive`),
    drawOrder: number(source.draw_order, `${layoutId}.elements[${index}].draw_order`),
    rect: rect(source.rect, `${layoutId}.elements[${index}].rect`),
    unclippedRect: rect(source.unclipped_rect, `${layoutId}.elements[${index}].unclipped_rect`),
  };
  return {
    ...element,
    ...(source.color === undefined
      ? {}
      : { color: string(source.color, `${layoutId}.elements[${index}].color`) }),
    ...(source.color_top === undefined
      ? {}
      : { colorTop: string(source.color_top, `${layoutId}.elements[${index}].color_top`) }),
    ...(source.color_bottom === undefined
      ? {}
      : { colorBottom: string(source.color_bottom, `${layoutId}.elements[${index}].color_bottom`) }),
    ...(source.font_height === undefined
      ? {}
      : { fontHeight: number(source.font_height, `${layoutId}.elements[${index}].font_height`) }),
    ...(source.font_weight === undefined
      ? {}
      : { fontWeight: number(source.font_weight, `${layoutId}.elements[${index}].font_weight`) }),
  };
}

function fixtureLayoutId(fixture: string): string {
  const match = /^menu-layouts\/([a-z0-9-]+)\.json$/.exec(fixture);
  if (match?.[1] === undefined) {
    throw new Error(`${fixture} is not a canonical G11 layout fixture path`);
  }
  return match[1];
}

/** Parse the one landed G11 golden; no browser-owned copy is accepted. */
export function parseMenuCatalog(value: unknown): MenuCatalog {
  const root = object(value, "G11 menu golden");
  const census = array(root.screen_census, "G11 screen census").map((entry, index) => (
    string(entry, `G11 screen census[${index}]`)
  ));
  if (census.length !== 28 || new Set(census).size !== census.length) {
    throw new Error("G11 screen census must name exactly 28 unique layouts");
  }
  const rawLayouts = array(root.layouts, "G11 layouts");
  const layouts = new Map<string, MenuLayout>();
  for (const [index, rawLayout] of rawLayouts.entries()) {
    const wrapper = object(rawLayout, `G11 layouts[${index}]`);
    const fixture = string(wrapper.fixture, `G11 layouts[${index}].fixture`);
    const id = fixtureLayoutId(fixture);
    if (layouts.has(id)) {
      throw new Error(`G11 menu golden ambiguously defines ${id} twice`);
    }
    const layout = object(wrapper.layout, `${id}.layout`);
    const elements = array(layout.elements, `${id}.elements`).map((element, elementIndex) => (
      parseElement(element, id, elementIndex)
    ));
    if (elements.length === 0) {
      throw new Error(`${id} has no drawable G11 layout content`);
    }
    layouts.set(id, {
      id,
      screenId: string(layout.screen_id, `${id}.screen_id`),
      title: string(layout.screen_title, `${id}.screen_title`),
      captureMethod: string(layout.capture_method, `${id}.capture_method`),
      fixture,
      referenceCapture: string(wrapper.reference_capture, `${id}.reference_capture`),
      referenceSha256: string(wrapper.reference_sha256, `${id}.reference_sha256`),
      elements,
    });
  }
  if (layouts.size !== census.length || census.some((layoutId) => !layouts.has(layoutId))) {
    throw new Error("G11 layout records must agree with the complete 28-screen census");
  }

  const navigation = object(root.navigation_graph, "G11 navigation graph");
  const navigationEdges = array(navigation.edges, "G11 navigation graph edges").map((edge, index) => {
    const source = object(edge, `G11 navigation graph edges[${index}]`);
    return {
      id: string(source.id, `G11 navigation graph edges[${index}].id`),
      source: string(source.screen, `G11 navigation graph edges[${index}].screen`),
      actionId: string(source.action_id, `G11 navigation graph edges[${index}].action_id`),
      destination: string(source.destination, `G11 navigation graph edges[${index}].destination`),
    };
  });
  if (navigationEdges.length !== 39 || new Set(navigationEdges.map((edge) => edge.id)).size !== 39) {
    throw new Error("G11 navigation graph must contain exactly 39 unique live edges");
  }
  return { layouts, screenCensus: census, navigationEdges };
}

export function nativeRectToBox(rectangle: NativeRect): {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
} {
  return {
    x: rectangle[0],
    y: rectangle[1],
    width: rectangle[2] - rectangle[0],
    height: rectangle[3] - rectangle[1],
  };
}
