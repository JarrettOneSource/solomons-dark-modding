"""Row-coherence audit + repair for dialog-layout.json, then regenerate the
measured table blocks in text-layout.ts.

Class of defect being closed: wide-y sweeps matched the SAME letter on the
NEXT text row (line pitch 17), recording a y one row down (and sometimes a
wrong x). Detector: per-line modal y by glyph class (caps/lower), deviation
> 4 flags the glyph; x-monotonicity violations flag the lower-scored glyph.
Repair: re-sweep inside the glyph's own row band and neighbor-bounded x
window. The script fails loudly if any line remains incoherent.
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, "/home/user/sd-menupreview/tools")
import extract_bundles  # noqa: E402

S = Path(__file__).parent
records, groups = extract_bundles.parse_bundle(S / "Fonts.bundle")
direct = len(records) - sum(g.glyph_count for g in groups)
atlas = np.asarray(Image.open("/home/user/sd-menupreview/assetpack-out/atlases/Fonts.png").convert("RGBA"))

beta_rgb = np.asarray(Image.open(S / "native-beta-notice.png").convert("RGB")).astype(float)
beta_bright = (beta_rgb @ [0.299, 0.587, 0.114]) > 120


def group_glyphs(gi):
    base = direct + sum(g.glyph_count for g in groups[:gi])
    return {chr(gid): records[base + k] for k, gid in enumerate(groups[gi].glyph_ids)}


FONT_BY_ID = {"Fonts.93-184": group_glyphs(1), "Fonts.216-307": group_glyphs(3)}


def ink_of(rec):
    x, y, w, h = int(rec.x), int(rec.y), int(rec.width), int(rec.height)
    return atlas[y:y + h, x:x + w, 3] > 128


def sweep(ink, bright, x0, x1, y0, y1):
    best = (-2.0, None, None)
    n = ink.sum()
    for py in range(int(y0), int(y1) + 1):
        for px in range(int(x0), int(x1) + 1):
            p = bright[py:py + ink.shape[0], px:px + ink.shape[1]]
            if p.shape != ink.shape:
                continue
            s = (ink & p).sum() / n - 0.5 * ((~ink) & p).sum() / n
            if s > best[0]:
                best = (s, px, py)
    return best


def glyph_class(ch):
    if ch.isupper() or ch.isdigit():
        return "caps"
    if ch.islower():
        return "lower"
    return "punct"


def modal(values):
    values = sorted(values)
    return values[len(values) // 2]


def audit(line):
    """Return indices of incoherent glyphs in a measured line."""
    glyphs = line["glyphs"]
    flagged = set()
    for cls in ("caps", "lower"):
        members = [(i, g) for i, g in enumerate(glyphs) if glyph_class(g["ch"]) == cls]
        if len(members) < 2:
            continue
        center = modal([g["y"] for _, g in members])
        for i, g in members:
            if abs(g["y"] - center) > 4:
                flagged.add(i)
    for i in range(1, len(glyphs)):
        prev, cur = glyphs[i - 1], glyphs[i]
        if cur["x"] < prev["x"] + 2:
            flagged.add(i if cur.get("score", 1) <= prev.get("score", 1) else i - 1)
    return sorted(flagged)


def row_band(line, ch):
    """The glyph's own row band from same-class same-line neighbors."""
    cls = glyph_class(ch)
    peers = [g["y"] for g in line["glyphs"] if glyph_class(g["ch"]) == cls]
    center = modal(peers) if peers else modal([g["y"] for g in line["glyphs"]])
    return center - 3, center + 3


def repair(line, index, font):
    glyphs = line["glyphs"]
    target = glyphs[index]
    rec = font[target["ch"]]
    ink = ink_of(rec)
    width = int(rec.content_width)
    prev_ok = next((g for g in reversed(glyphs[:index]) if index and g not in (target,)
                    and audit_ok(g, line)), None)
    next_ok = next((g for g in glyphs[index + 1:] if audit_ok(g, line)), None)
    x_lo = prev_ok["x"] + 3 if prev_ok else target["x"] - 12
    x_hi = next_ok["x"] + 3 - width if next_ok else target["x"] + 12
    if x_hi < x_lo:
        x_lo, x_hi = x_hi, x_lo
    y_lo, y_hi = row_band(line, target["ch"])
    score, px, py = sweep(ink, beta_bright, x_lo - 1, x_hi + 1, y_lo, y_hi)
    return {"ch": target["ch"], "x": px, "y": py, "score": round(float(score), 3)}


def audit_ok(g, line):
    y_lo, y_hi = row_band(line, g["ch"])
    return glyph_class(g["ch"]) == "punct" or y_lo <= g["y"] <= y_hi


layout = json.loads((S / "dialog-layout.json").read_text())

FONT_OF_LINE = {"heading": "Fonts.216-307", "ok": "Fonts.216-307"}
repairs = []
for lid, line in layout["lines"].items():
    font = FONT_BY_ID[FONT_OF_LINE.get(lid, "Fonts.93-184")]
    for index in audit(line):
        old = dict(line["glyphs"][index])
        fixed = repair(line, index, font)
        line["glyphs"][index] = fixed
        repairs.append((lid, old, fixed))
        print(f"{lid:8s} {old['ch']!r} {old['x']},{old['y']}(s{old.get('score')}) -> "
              f"{fixed['x']},{fixed['y']}(s{fixed['score']})")

print(f"\n{len(repairs)} glyphs repaired")

# Post-repair audit must be clean, and every repaired score acceptable.
failures = []
for lid, line in layout["lines"].items():
    residual = audit(line)
    if residual:
        failures.append(f"{lid}: still incoherent at indices {residual}: "
                        f"{[line['glyphs'][i] for i in residual]}")
for lid, _, fixed in repairs:
    if fixed["score"] < 0.6:
        failures.append(f"{lid}: repaired {fixed['ch']!r} weak at {fixed['score']}")
if failures:
    print("\nAUDIT FAILURES:")
    for failure in failures:
        print(" ", failure)
    sys.exit(1)

(S / "dialog-layout.json").write_text(json.dumps(layout, indent=1))
print("dialog-layout.json updated and coherent")

# ---- regenerate the measured blocks in text-layout.ts ----
ts_path = Path("/home/user/sd-menupreview/webgame/client/text-layout.ts")
ts = ts_path.read_text()


def entry(g):
    return f'    {{ ch: {json.dumps(g["ch"])}, x: {g["x"]}, y: {g["y"]} }},'


dialog_lines = []
for lid, line in layout["lines"].items():
    if lid in ("quit", "stamp"):
        continue
    dialog_lines.append(f'  "{lid}": [')
    dialog_lines.extend(entry(g) for g in line["glyphs"])
    dialog_lines.append("  ],")
dialog_lines.append('  "ok": [')
# ok already included above via layout["lines"]; guard against duplication
if dialog_lines[-1] == '  "ok": [':
    dialog_lines.pop()
dialog_block = "\n".join(dialog_lines)

stamp_lines = [entry(g)[2:] for g in layout["lines"]["stamp"]["glyphs"]]
stamp_block = "\n".join("  " + line.strip() for line in stamp_lines)

ts = re.sub(
    r"(DIALOG_LINE_GLYPHS: Readonly<Record<string, readonly GlyphPlacement\[\]>> = \{\n).*?(\n\};)",
    lambda m: m.group(1) + dialog_block + m.group(2),
    ts,
    flags=re.S,
)
ts = re.sub(
    r"(STAMP_GLYPHS: readonly GlyphPlacement\[\] = \[\n).*?(\n\];)",
    lambda m: m.group(1) + stamp_block + m.group(2),
    ts,
    flags=re.S,
)
ts_path.write_text(ts)
print("text-layout.ts measured blocks regenerated")
