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
  readonly ambientElements: readonly MenuElement[];
  readonly semanticDialogElements: readonly MenuElement[];
  readonly dialogElementIds: ReadonlySet<string>;
}

export interface NavigationEdge {
  readonly id: string;
  readonly source: string;
  readonly actionId: string;
  readonly destination: string;
  readonly destinationType: string;
  readonly destinationLayoutFixture: string;
  readonly destinationLayoutId: string | null;
  readonly destinationOverlayId: string | null;
}

export interface MenuOverlayRecord {
  readonly id: string;
  readonly fixture: string;
  readonly sha256: string;
  readonly bytes: number;
  readonly settlementSpec: string;
  readonly classification: string;
  readonly underlyingSurfaceId: string;
  readonly semanticMemberCount: number;
  readonly underlayScreenId: string;
  readonly underlayFixture: string;
  readonly underlaySha256: string;
  readonly underlayBytes: number;
  readonly destinationEdgeId: string;
  readonly sourceEdgeId: string;
}

export interface MenuDialogComposite {
  readonly id: string;
  readonly fixture: string;
  readonly sha256: string;
  readonly bytes: number;
  readonly settlementSpec: string;
  readonly referenceCapture: string;
  readonly referenceSha256: string;
  readonly underlayLayoutId: string;
  readonly underlayScreenId: string;
  readonly actionId: string;
  readonly actionRect: NativeRect;
  readonly destinationLayoutId: string;
  readonly dialogMemberCount: number;
  readonly residualMemberCount: number;
  readonly layout: MenuLayout;
}

export interface MenuCatalog {
  readonly layouts: ReadonlyMap<string, MenuLayout>;
  readonly standardLayoutIds: readonly string[];
  readonly transitionLayoutIds: readonly string[];
  readonly screenCensus: readonly string[];
  readonly overlayRecords: ReadonlyMap<string, MenuOverlayRecord>;
  readonly dialogComposites: ReadonlyMap<string, MenuDialogComposite>;
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

function integer(value: unknown, label: string): number {
  const parsed = number(value, label);
  if (!Number.isInteger(parsed)) {
    throw new Error(`${label} must be an integer`);
  }
  return parsed;
}

function array(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`${label} must be an array`);
  }
  return value;
}

function stringArray(value: unknown, label: string): string[] {
  return array(value, label).map((entry, index) => string(entry, `${label}[${index}]`));
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

function optionalElementFields(source: JsonObject, label: string): Partial<MenuElement> {
  return {
    ...(source.color === undefined ? {} : { color: string(source.color, `${label}.color`) }),
    ...(source.color_top === undefined
      ? {}
      : { colorTop: string(source.color_top, `${label}.color_top`) }),
    ...(source.color_bottom === undefined
      ? {}
      : { colorBottom: string(source.color_bottom, `${label}.color_bottom`) }),
    ...(source.font_height === undefined
      ? {}
      : { fontHeight: number(source.font_height, `${label}.font_height`) }),
    ...(source.font_weight === undefined
      ? {}
      : { fontWeight: number(source.font_weight, `${label}.font_weight`) }),
  };
}

function parseElement(value: unknown, layoutId: string, index: number): MenuElement {
  const label = `${layoutId}.elements[${index}]`;
  const source = object(value, label);
  return {
    id: string(source.id, `${label}.id`),
    kind: string(source.kind, `${label}.kind`),
    text: string(source.text, `${label}.text`),
    actionId: string(source.action_id, `${label}.action_id`),
    artId: string(source.art_id, `${label}.art_id`),
    fontId: string(source.font_id, `${label}.font_id`),
    textStyle: string(source.text_style, `${label}.text_style`),
    visible: boolean(source.visible, `${label}.visible`),
    interactive: boolean(source.interactive, `${label}.interactive`),
    drawOrder: number(source.draw_order, `${label}.draw_order`),
    rect: rect(source.rect, `${label}.rect`),
    unclippedRect: rect(source.unclipped_rect, `${label}.unclipped_rect`),
    ...optionalElementFields(source, label),
  };
}

function parseDialogElement(
  value: unknown,
  compositeId: string,
  index: number,
  drawOrder: number,
): MenuElement {
  const label = `${compositeId}.dialog_semantic_multiset.entries[${index}].payload`;
  const source = object(value, label);
  return {
    id: `${compositeId}.dialog.${String(index).padStart(2, "0")}`,
    kind: string(source.kind, `${label}.kind`),
    text: string(source.text, `${label}.text`),
    actionId: string(source.action_id, `${label}.action_id`),
    artId: string(source.art_id, `${label}.art_id`),
    fontId: string(source.font_id, `${label}.font_id`),
    textStyle: string(source.text_style, `${label}.text_style`),
    visible: boolean(source.visible, `${label}.visible`),
    interactive: boolean(source.interactive, `${label}.interactive`),
    drawOrder,
    rect: rect(source.rect, `${label}.rect`),
    unclippedRect: rect(source.unclipped_rect, `${label}.unclipped_rect`),
    ...optionalElementFields(source, label),
  };
}

function ambientDrawOrder(
  member: JsonObject,
  elements: readonly MenuElement[],
  label: string,
): number {
  const orders = new Map(elements.map((element) => [element.id, element.drawOrder]));
  const band = object(array(member.draw_bands, `${label}.draw_bands`)[0], `${label}.draw_bands[0]`);
  const below = string(band.below, `${label}.draw_bands[0].below`);
  const above = string(band.above, `${label}.draw_bands[0].above`);
  const belowOrder = orders.get(below);
  const aboveOrder = orders.get(above);
  if (belowOrder !== undefined && aboveOrder !== undefined) {
    return (belowOrder + aboveOrder) / 2;
  }
  if (belowOrder !== undefined && above === "top") {
    return Math.max(...elements.map((element) => element.drawOrder)) + 1;
  }
  if (aboveOrder !== undefined && below === "bottom") {
    return Math.min(...elements.map((element) => element.drawOrder)) - 1;
  }
  throw new Error(`${label} has an unresolvable aggregate draw band ${below}/${above}`);
}

function parseAmbientElements(
  layout: JsonObject,
  elements: readonly MenuElement[],
  layoutId: string,
): MenuElement[] {
  const priorities = ["ambient_persistent", "animated", "visibility_cycling", "ephemeral"];
  return array(layout.ambient_members, `${layoutId}.ambient_members`).map((value, index) => {
    const label = `${layoutId}.ambient_members[${index}]`;
    const member = object(value, label);
    const classes = array(member.class_members, `${label}.class_members`).map((entry, classIndex) => (
      object(entry, `${label}.class_members[${classIndex}]`)
    ));
    const selected = priorities
      .map((priority) => classes.find((entry) => entry.classification === priority))
      .find((entry): entry is JsonObject => entry !== undefined) ?? classes[0];
    if (selected === undefined) {
      throw new Error(`${label} has no aggregate ambient class payload`);
    }
    const payload = object(selected.dominant_phase_payload, `${label}.dominant_phase_payload`);
    return {
      id: string(member.id, `${label}.id`),
      kind: string(payload.kind, `${label}.kind`),
      text: string(payload.text, `${label}.text`),
      actionId: string(payload.action_id, `${label}.action_id`),
      artId: string(payload.art_id, `${label}.art_id`),
      fontId: string(payload.font_id, `${label}.font_id`),
      textStyle: string(payload.text_style, `${label}.text_style`),
      visible: boolean(payload.visible, `${label}.visible`),
      interactive: boolean(payload.interactive, `${label}.interactive`),
      drawOrder: ambientDrawOrder(member, elements, label),
      rect: rect(payload.rect, `${label}.rect`),
      unclippedRect: rect(payload.unclipped_rect, `${label}.unclipped_rect`),
      ...optionalElementFields(payload, label),
    };
  });
}

function fixtureLayoutId(fixture: string): string {
  const match = /^menu-(?:transition-)?layouts\/([a-z0-9_-]+)\.json$/.exec(fixture);
  if (match?.[1] === undefined) {
    throw new Error(`${fixture} is not a canonical aggregate layout fixture path`);
  }
  return match[1];
}

function parseLayoutWrapper(value: unknown, label: string): MenuLayout {
  const wrapper = object(value, label);
  const fixture = string(wrapper.fixture, `${label}.fixture`);
  const id = fixtureLayoutId(fixture);
  const layout = object(wrapper.layout, `${id}.layout`);
  const elements = array(layout.elements, `${id}.elements`).map((element, index) => (
    parseElement(element, id, index)
  ));
  if (elements.length === 0) {
    throw new Error(`${id} has no drawable aggregate layout content`);
  }
  return {
    id,
    screenId: string(layout.screen_id, `${id}.screen_id`),
    title: string(layout.screen_title, `${id}.screen_title`),
    captureMethod: string(layout.capture_method, `${id}.capture_method`),
    fixture,
    referenceCapture: string(wrapper.reference_capture, `${id}.reference_capture`),
    referenceSha256: string(wrapper.reference_sha256, `${id}.reference_sha256`),
    elements,
    ambientElements: parseAmbientElements(layout, elements, id),
    semanticDialogElements: [],
    dialogElementIds: new Set(),
  };
}

function addLayouts(
  target: Map<string, MenuLayout>,
  source: unknown,
  label: string,
): string[] {
  const ids: string[] = [];
  for (const [index, value] of array(source, label).entries()) {
    const layout = parseLayoutWrapper(value, `${label}[${index}]`);
    if (target.has(layout.id)) {
      throw new Error(`aggregate menu golden ambiguously defines ${layout.id} twice`);
    }
    target.set(layout.id, layout);
    ids.push(layout.id);
  }
  return ids;
}

function parseOverlayRecords(root: JsonObject): ReadonlyMap<string, MenuOverlayRecord> {
  const census = stringArray(root.overlay_census, "aggregate overlay census");
  const records = new Map<string, MenuOverlayRecord>();
  for (const [index, value] of array(root.overlay_records, "aggregate overlay records").entries()) {
    const label = `aggregate overlay records[${index}]`;
    const wrapper = object(value, label);
    const id = string(wrapper.overlay_id, `${label}.overlay_id`);
    const record = object(wrapper.record, `${label}.record`);
    const overlay = object(record.overlay, `${label}.record.overlay`);
    const classification = object(overlay.classification, `${label}.classification`);
    const binding = object(overlay.semantic_underlay_binding, `${label}.semantic_underlay_binding`);
    const navigation = object(overlay.navigation, `${label}.navigation`);
    if (records.has(id)) {
      throw new Error(`aggregate menu golden ambiguously defines overlay ${id} twice`);
    }
    records.set(id, {
      id,
      fixture: string(wrapper.fixture, `${label}.fixture`),
      sha256: string(wrapper.sha256, `${label}.sha256`),
      bytes: integer(wrapper.bytes, `${label}.bytes`),
      settlementSpec: string(record.settlement_spec, `${label}.settlement_spec`),
      classification: string(classification.classification, `${label}.classification.classification`),
      underlyingSurfaceId: string(
        classification.underlying_surface_id,
        `${label}.classification.underlying_surface_id`,
      ),
      semanticMemberCount: integer(overlay.semantic_member_count, `${label}.semantic_member_count`),
      underlayScreenId: string(binding.screen_id, `${label}.semantic_underlay_binding.screen_id`),
      underlayFixture: string(wrapper.underlay_fixture, `${label}.underlay_fixture`),
      underlaySha256: string(wrapper.underlay_sha256, `${label}.underlay_sha256`),
      underlayBytes: integer(wrapper.underlay_bytes, `${label}.underlay_bytes`),
      destinationEdgeId: string(navigation.destination_edge, `${label}.navigation.destination_edge`),
      sourceEdgeId: string(navigation.source_edge, `${label}.navigation.source_edge`),
    });
  }
  if (
    records.size !== census.length
    || new Set(census).size !== census.length
    || census.some((id) => !records.has(id))
  ) {
    throw new Error("aggregate overlay records must agree with the overlay census");
  }
  return records;
}

function parseDialogComposites(
  root: JsonObject,
  layouts: ReadonlyMap<string, MenuLayout>,
): ReadonlyMap<string, MenuDialogComposite> {
  const census = stringArray(
    root.semantic_dialog_composite_census,
    "aggregate semantic dialog composite census",
  );
  const records = new Map<string, MenuDialogComposite>();
  for (const [index, value] of array(
    root.semantic_dialog_composite_records,
    "aggregate semantic dialog composite records",
  ).entries()) {
    const label = `aggregate semantic dialog composite records[${index}]`;
    const wrapper = object(value, label);
    const id = string(wrapper.composite_id, `${label}.composite_id`);
    const record = object(wrapper.record, `${label}.record`);
    const composite = object(record.composite, `${label}.record.composite`);
    const classification = object(composite.classification, `${label}.classification`);
    const binding = object(composite.underlay_binding, `${label}.underlay_binding`);
    const multiset = object(composite.dialog_semantic_multiset, `${label}.dialog_semantic_multiset`);
    const decomposition = object(composite.decomposition, `${label}.decomposition`);
    const dismissal = object(composite.dismissal, `${label}.dismissal`);
    const action = object(dismissal.qualified_action_member, `${label}.qualified_action_member`);
    const navigation = object(record.navigation, `${label}.navigation`);
    const underlayLayoutId = string(binding.layout_id, `${label}.underlay_binding.layout_id`);
    const underlay = layouts.get(underlayLayoutId);
    if (underlay === undefined) {
      throw new Error(`${id} names missing underlay layout ${underlayLayoutId}`);
    }
    const dialogMemberCount = integer(multiset.member_count, `${label}.dialog_member_count`);
    const baseDrawOrder = Math.max(...underlay.elements.map((element) => element.drawOrder)) + 1;
    const dialogElements: MenuElement[] = [];
    for (const [entryIndex, entryValue] of array(multiset.entries, `${label}.entries`).entries()) {
      const entry = object(entryValue, `${label}.entries[${entryIndex}]`);
      const count = integer(entry.count, `${label}.entries[${entryIndex}].count`);
      if (count < 1) {
        throw new Error(`${label}.entries[${entryIndex}].count must be positive`);
      }
      for (let repeat = 0; repeat < count; repeat += 1) {
        dialogElements.push(parseDialogElement(
          entry.payload,
          id,
          dialogElements.length,
          baseDrawOrder + dialogElements.length,
        ));
      }
    }
    const residualMemberCount = integer(
      decomposition.residual_member_count,
      `${label}.decomposition.residual_member_count`,
    );
    if (dialogElements.length !== dialogMemberCount || residualMemberCount !== 0) {
      throw new Error(`${id} must decompose into its measured dialog multiset with zero residue`);
    }
    const compositeMemberCount = integer(
      classification.composite_member_count,
      `${label}.classification.composite_member_count`,
    );
    if (compositeMemberCount !== underlay.elements.length + dialogMemberCount) {
      throw new Error(`${id} composite count does not equal underlay plus dialog members`);
    }
    if (records.has(id)) {
      throw new Error(`aggregate menu golden ambiguously defines dialog composite ${id} twice`);
    }
    const fixture = string(wrapper.fixture, `${label}.fixture`);
    const referenceCapture = string(wrapper.reference_capture, `${label}.reference_capture`);
    const referenceSha256 = string(wrapper.reference_sha256, `${label}.reference_sha256`);
    records.set(id, {
      id,
      fixture,
      sha256: string(wrapper.sha256, `${label}.sha256`),
      bytes: integer(wrapper.bytes, `${label}.bytes`),
      settlementSpec: string(wrapper.settlement_spec, `${label}.settlement_spec`),
      referenceCapture,
      referenceSha256,
      underlayLayoutId,
      underlayScreenId: string(binding.screen_id, `${label}.underlay_binding.screen_id`),
      actionId: string(dismissal.action_id, `${label}.dismissal.action_id`),
      actionRect: rect(action.rect, `${label}.qualified_action_member.rect`),
      destinationLayoutId: string(
        navigation.destination_layout_id,
        `${label}.navigation.destination_layout_id`,
      ),
      dialogMemberCount,
      residualMemberCount,
      layout: {
        id,
        screenId: id,
        title: "Beta Notice First Boot",
        captureMethod: `Settlement ${string(wrapper.settlement_spec, `${label}.settlement_spec`)} semantic dialog composite`,
        fixture,
        referenceCapture,
        referenceSha256,
        elements: [...underlay.elements, ...dialogElements],
        ambientElements: underlay.ambientElements,
        semanticDialogElements: [],
        dialogElementIds: new Set(dialogElements.map((element) => element.id)),
      },
    });
  }
  if (
    records.size !== census.length
    || new Set(census).size !== census.length
    || census.some((id) => !records.has(id))
  ) {
    throw new Error("aggregate dialog composite records must agree with the composite census");
  }
  return records;
}

/** Parse the byte-pinned menufix aggregate without asserting instance-local generations. */
export function parseMenuCatalog(value: unknown): MenuCatalog {
  const root = object(value, "menufix aggregate menu golden");
  if (root.schema !== "solomon-dark-menu-goldens-v3") {
    throw new Error("menufix aggregate menu golden has the wrong schema");
  }
  const screenCensus = stringArray(root.screen_census, "aggregate screen census");
  if (screenCensus.length === 0 || new Set(screenCensus).size !== screenCensus.length) {
    throw new Error("aggregate screen census must name unique layouts");
  }

  const layouts = new Map<string, MenuLayout>();
  const standardLayoutIds = addLayouts(layouts, root.layouts, "aggregate layouts");
  const transitionLayoutIds = addLayouts(
    layouts,
    root.transition_endpoint_layouts,
    "aggregate transition endpoint layouts",
  );
  if (layouts.size !== screenCensus.length || screenCensus.some((layoutId) => !layouts.has(layoutId))) {
    throw new Error("aggregate layout records must agree with the complete screen census");
  }

  const overlayRecords = parseOverlayRecords(root);
  const dialogComposites = parseDialogComposites(root, layouts);
  const firstBootDialog = dialogComposites.get("beta_notice_first_boot");
  const betaNotice = layouts.get("beta-notice");
  if (firstBootDialog === undefined || betaNotice === undefined) {
    throw new Error("aggregate menu golden lost a measured beta-notice surface");
  }
  const firstBootUnderlay = layouts.get(firstBootDialog.underlayLayoutId);
  if (firstBootUnderlay === undefined) {
    throw new Error("aggregate menu golden lost the first-boot dialog underlay");
  }
  const dialogMembers = firstBootDialog.layout.elements.slice(firstBootUnderlay.elements.length);
  const dialogText = dialogMembers
    .filter((element) => element.kind === "text")
    .map((element, index) => ({
      ...element,
      id: `beta-notice.measured-dialog-text.${String(index).padStart(2, "0")}`,
      drawOrder: 100 + index,
    }));
  const sameDialogMember = (left: MenuElement, right: MenuElement): boolean => (
    left.kind === right.kind
    && left.text === right.text
    && left.artId === right.artId
    && left.fontId === right.fontId
    && left.rect.every((coordinate, index) => coordinate === right.rect[index])
    && left.unclippedRect.every((coordinate, index) => coordinate === right.unclippedRect[index])
  );
  const measuredDialogIds = [...betaNotice.elements, ...betaNotice.ambientElements]
    .filter((element) => dialogMembers.some((member) => sameDialogMember(element, member)))
    .map((element) => element.id);
  layouts.set("beta-notice", {
    ...betaNotice,
    semanticDialogElements: dialogText,
    dialogElementIds: new Set([...measuredDialogIds, ...dialogText.map((element) => element.id)]),
  });
  const navigation = object(root.navigation_graph, "aggregate navigation graph");
  const navigationEdges = array(navigation.edges, "aggregate navigation graph edges").map((value, index) => {
    const label = `aggregate navigation graph edges[${index}]`;
    const edge = object(value, label);
    const destinationLayoutFixture = string(
      edge.destination_layout_fixture,
      `${label}.destination_layout_fixture`,
    );
    const destinationType = string(edge.destination_type, `${label}.destination_type`);
    let destinationLayoutId: string | null = null;
    let destinationOverlayId: string | null = null;
    if (destinationType === "layout") {
      destinationLayoutId = fixtureLayoutId(destinationLayoutFixture);
      if (!layouts.has(destinationLayoutId)) {
        throw new Error(`${label} binds missing destination layout ${destinationLayoutId}`);
      }
    } else if (destinationType === "overlay") {
      destinationOverlayId = [...overlayRecords.values()]
        .find((record) => record.fixture === destinationLayoutFixture)?.id ?? null;
      if (destinationOverlayId === null) {
        throw new Error(`${label} binds missing destination overlay ${destinationLayoutFixture}`);
      }
    } else {
      throw new Error(`${label} has unsupported destination type ${destinationType}`);
    }
    return {
      id: string(edge.id, `${label}.id`),
      source: string(edge.screen, `${label}.screen`),
      actionId: string(edge.action_id, `${label}.action_id`),
      destination: string(edge.destination, `${label}.destination`),
      destinationType,
      destinationLayoutFixture,
      destinationLayoutId,
      destinationOverlayId,
    };
  });
  if (
    navigationEdges.length === 0
    || new Set(navigationEdges.map((edge) => edge.id)).size !== navigationEdges.length
  ) {
    throw new Error("aggregate navigation graph must contain unique live edges");
  }
  return {
    layouts,
    standardLayoutIds,
    transitionLayoutIds,
    screenCensus,
    overlayRecords,
    dialogComposites,
    navigationEdges,
  };
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
