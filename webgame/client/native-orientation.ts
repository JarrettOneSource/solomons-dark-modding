import type { RenderPlan, SpriteDraw } from "./render-plan.js";

// ATC-preview restoration of natively mirrored menu decorations (superseded by
// shellfix #101). The G11 payload schema has no orientation field, so every
// natively mirrored placement of a shared art captured as an identical
// un-flipped draw (schema gap, routed to the #96 architecture docs). The
// native reference captures establish three mirror rules:
//   - UI.54 slab end caps and UI.53 quit-slab caps: same-row pairs mirror the
//     right cap horizontally.
//   - UI.18 vine columns: side-by-side portrait pairs mirror the right column
//     horizontally. The landscape crest banner placement of the same art is
//     single-orientation and excluded by the portrait test.
//   - UI.17 corner filigree: each corner mirrors toward its group's centroid
//     (top-left is the source orientation).
// UI.8 ornaments and the pre-oriented corner stones UI.107-110 are verified
// single-orientation and deliberately untouched.

const ROW_PAIR_ARTS: ReadonlySet<string> = new Set(["UI.54", "UI.53"]);
const COLUMN_PAIR_ART = "UI.18";
const CORNER_ART = "UI.17";

interface Placement {
  readonly index: number;
  readonly command: SpriteDraw;
}

function centerOf(command: SpriteDraw): readonly [number, number] {
  const [left, top, right, bottom] = command.unclippedRect;
  return [(left + right) / 2, (top + bottom) / 2];
}

function isPortrait(command: SpriteDraw): boolean {
  const [left, top, right, bottom] = command.unclippedRect;
  return bottom - top > right - left;
}

function spanKey(command: SpriteDraw): string {
  return `${command.unclippedRect[1]}|${command.unclippedRect[3]}`;
}

function flipRightOfPairs(
  groups: ReadonlyMap<string, readonly Placement[]>,
  flips: Map<number, readonly [boolean, boolean]>,
): void {
  for (const group of groups.values()) {
    if (group.length !== 2) {
      continue;
    }
    const [first, second] = group;
    if (first === undefined || second === undefined
      || first.command.unclippedRect[0] === second.command.unclippedRect[0]) {
      continue;
    }
    const right = first.command.unclippedRect[0] > second.command.unclippedRect[0] ? first : second;
    flips.set(right.index, [true, false]);
  }
}

export function orientNativeChrome(plan: RenderPlan): RenderPlan {
  const rowGroups = new Map<string, Placement[]>();
  const columnGroups = new Map<string, Placement[]>();
  const corners: Placement[] = [];
  plan.commands.forEach((command, index) => {
    if (command.kind !== "sprite" || command.flip !== undefined) {
      return;
    }
    const art = command.asset.canonicalId;
    if (ROW_PAIR_ARTS.has(art)) {
      const key = `${art}|${spanKey(command)}`;
      const group = rowGroups.get(key) ?? [];
      group.push({ index, command });
      rowGroups.set(key, group);
    } else if (art === COLUMN_PAIR_ART && isPortrait(command)) {
      const group = columnGroups.get(spanKey(command)) ?? [];
      group.push({ index, command });
      columnGroups.set(spanKey(command), group);
    } else if (art === CORNER_ART) {
      corners.push({ index, command });
    }
  });

  const flips = new Map<number, readonly [boolean, boolean]>();
  flipRightOfPairs(rowGroups, flips);
  flipRightOfPairs(columnGroups, flips);
  if (corners.length >= 2) {
    let centroidX = 0;
    let centroidY = 0;
    for (const placement of corners) {
      const [x, y] = centerOf(placement.command);
      centroidX += x / corners.length;
      centroidY += y / corners.length;
    }
    for (const placement of corners) {
      const [x, y] = centerOf(placement.command);
      const flipX = x > centroidX + 0.5;
      const flipY = y > centroidY + 0.5;
      if (flipX || flipY) {
        flips.set(placement.index, [flipX, flipY]);
      }
    }
  }
  if (flips.size === 0) {
    return plan;
  }
  return {
    ...plan,
    commands: plan.commands.map((command, index) => {
      const flip = flips.get(index);
      return flip === undefined || command.kind !== "sprite" ? command : { ...command, flip };
    }),
  };
}
