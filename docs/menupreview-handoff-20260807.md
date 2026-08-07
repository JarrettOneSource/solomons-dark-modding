# menupreview handoff — 2026-08-07 (ATC → fleet)

Owner-visible task (#102): the deployed /game preview at solomondarker.com/game must
match the native menus. The owner reported rotated buttons/images and a beta-warning
dialog with no text or background. Most of the fix is landed on this branch and
verified; TWO diagnosed defects remain, then conformance re-verification, landing,
and redeploy. This document is the complete state transfer: nothing below needs
re-derivation, and every claim carries its evidence.

Branch: `atc/menu-preview-20260807` (continue on it; land on main by rebase, never force).
Evidence dir for your run: `D:\codex-evidence\menupreview-20260807\` (create; SHA256SUMS
required, hashed Windows-side via powershell.exe Get-FileHash).
Sentinels: report `DONE:` / `QUESTION:` / `STOP:` exactly once, last line of your final
message. Material spec/test weakenings require `QUESTION:` first. No other weakenings
may ride along with anything authorized here.

## 1. The two remaining defects (both fully diagnosed — implement, don't re-investigate)

### 1a. UI.18 crest renders sideways on beta-notice
- The atlas stores UI.18 as a portrait 67x262 strip (`asset-manifest.json` entry:
  rect 543,205 67x262, rotated=false, logicalSize 86x262).
- beta-notice uses that ONE art at three placements: two portrait side columns
  (599.5,440,666.5,702) and (1033.5,440,1100.5,702) — correct today — and the
  top crest (669,51,931,118), which is the SAME art turned 90° CLOCKWISE.
- The renderer no longer infers orientation from aspect ratios (that inference WAS
  the owner-reported rotation bug; `webgl-renderer.ts` now composes
  `entry.rotated !== command.quarterTurn`). Placement turns must be declared by a
  plan layer that knows the native placement. `SpriteDraw.quarterTurn` exists for
  exactly this (`render-plan.ts`).
- Renderer turn semantics verified: `quarterTurn: true` maps source top-left →
  dest top-right = 90° CW. PIL `ROTATE_270` of the atlas strip matches the native
  crest (skull upright, vines up); see `tools/menu-preview-verify/refs/`.
- FIX: declare `quarterTurn: true` for the crest placement only, in
  `native-orientation.ts` (the orientation-data layer that already restores native
  mirrors). Key it by art + rect like the existing mirror table. Do NOT touch the
  two column placements (one of them is mirrored by the existing table).
- Acceptance: binary-ink IoU ≥ 0.95 vs `refs/native-beta-notice.png` in
  (669,51,931,118), and the two columns unchanged.

### 1b. Shell focus ring ≠ native focus chrome (beta-notice OK plate AND main-menu PLAY)
- Native draws focused controls with its own chrome: a gold frame hugging the
  control rect with two small top-edge tabs (see the OK plate in the beta ref, and
  PLAY on `refs/native-main-menu-root.png`). That chrome is NOT in the G11 element
  census — the native focus pass was invisible to the capture hooks. (Capture-gap:
  record it in the register, §5.)
- Our shell draws a placeholder instead: `buildRenderPlan` pushes a
  `kind:"focus"` command, bright gold [0.95,0.78,0.35,0.9], rendered as an
  oversized bracketed ring. That is the "random mismatch" the owner saw around
  buttons.
- FIX: measure the native focus presentation from the two refs (geometry relative
  to the control rect, thickness, tabs, color under both lit and scrim-dimmed
  conditions — the beta OK ring sits above the scrim and is NOT dimmed) and make
  the focus draw reproduce it. It must track the focused rect generically (it
  shows on every screen), not be hardcoded per screen.
- On beta-notice the focused control's rect is the OK plate (702,643.5,898,712);
  ring position is already correct — only the visual is wrong.
- Acceptance: binary-ink IoU ≥ 0.95 vs refs in (690,630,910,730) on beta-notice
  and in the PLAY row on main-menu-root; update `beta-dialog.test.ts` /
  render-plan tests to the new focus command shape without dropping floors.

### Closed false lead — do not chase
"HALL bleeding through the dialog" was a tooling artifact: a crop script selected
the capture by glob mtime and grabbed main-menu-root.png instead of
beta-notice.png. COVERED_MENU_TEXT removal works; the dialog's OK text is correct.
Lesson (apply it): name capture files explicitly; never select evidence by
glob-plus-mtime.

## 2. What is already fixed and verified on this branch (do not re-litigate)

- Renderer orientation-as-data: `#drawSprite` composes atlas packing rotation with
  declared placement turns only; aspect inference deleted.
- `#drawAtlasText` blits measured glyphs 1:1; stretch-to-rect deleted.
- Beta dialog reconstructed (`beta-dialog.ts`): the native panel/scrim/text draw
  path never reached the G11 capture (unhooked), so panel, scrim, and all 23 text
  lines are rebuilt pixel-measured from the native reference. Scrim model proven:
  solid black at 0.75 alpha; text outside the panel manually tinted ×0.25 (quit
  ink measures gold ×0.254 in the ref).
- Glyph placement tables (`text-layout.ts`): the Fonts bundle carries NO per-glyph
  placement (constant 32×32 g1 / 48×48 g3 source cells; placement is code-driven
  natively), so measured tables are the parity-policy route. Tables regenerated by
  `tools/menu-preview-verify/measure7.py` after repairing a measurement class
  (row-collision: sweeps matched the same letterform one 17px line-pitch down; 9
  glyphs repaired; detector = per-line modal-y by glyph class + x-monotonicity).
- Font attribution settled: Fonts.93-184 body face; Fonts.216-307 serif display
  (dialog heading, OK, menu labels); Fonts.308-349 large display, PLAY only, 1:1
  (PLAY is NOT focus-scaled).
- Verified numbers on the current build: per-line ink IoU vs native 0.997–1.000 on
  19/22 dialog lines; ok 0.941 and body.12 0.950 (two weakest glyphs, documented
  residual), body.11 0.985; quit-under-scrim 0.898 with ink RGB within 1 unit/channel.
  Gates: typecheck 49 (floor 42), lint 52 (floor 45), tests 15 files / 84 tests
  (floors 12/58). Floors are ratchets — never lower them.

Draw-order facts (load-bearing — keep):
- The fixture's `draw_order` on beta-notice is hook ENUMERATION order, not paint
  order. The sealed ambient trace (`ambient-title-data.json`, provenance-pinned,
  NEVER mutate) is the paint truth: dialog chrome paints at 88–102 (corner stones
  88–91, filigree 92–95, crest 96, daggers 97–99, OK plate group 100–102), menu
  underlay ≤87.
- The reconstructed dialog slots exactly into the 87→88 gap: scrim 87.1, panel
  87.3–87.7. Do not renumber.

## 3. Environment quickstart

Clone fresh from origin (GitHub `solomons-dark-modding`), check out this branch.
- `cd webgame && npm install`
- `npm run assets:build` regenerates `assetpack-out/` (generated — never commit it)
- Gates: `npm run typecheck` / `npm run lint` / `npm test` (each enforces its floor)
- `npm run build` → `dist/`
- Headless verification: stage `dist/` + an `assetpack` symlink next to it, serve
  with `python3 -m http.server <port>` (serve the STAGE DIR as cwd — URL is
  `/index.html`, not `/stage/…`), capture with
  `tools/menu-preview-verify/capture-screens.mjs` (headless chrome at
  /opt/google/chrome/chrome) or the repo's `capture:evidence` script.
- Dispose your own capture chrome + http.server by EXACT PID when done, every run.

`tools/menu-preview-verify/` kit (checksums in its SHA256SUMS):
- `refs/native-beta-notice.png` (3416…d01) and `refs/native-main-menu-root.png`
  (c298…387): native ground truth. These shas are cited in `text-layout.ts`
  provenance. The menufix evidence set holds an independent beta capture
  (a10f40d3…) — same settled screen, different session; whole-frame equality
  across sessions is impossible because the Title scene animates (see §4).
- `measure7.py`: glyph-table audit/repair/regenerator (also documents the
  row-collision defect class).
- `dialog-layout.json`: the measured glyph truth the tables were generated from.
- `capture-screens.mjs`: the capture harness the verified numbers came from.

## 4. Required verification before deploy (the bar the owner was promised)

Element-by-element against the refs, not eyeballing:
1. All gates green at floors.
2. Fresh build + capture of beta-notice and main-menu-root.
3. Per-line ink IoU (template ink = atlas alpha>128; bright = luminance>120 lit /
   >40 dimmed; score = hit/n − 0.5·spill/n): every dialog line ≥ 0.95; expect the
   current 0.997+ on lines already passing — a regression below a line's current
   value is a defect even above 0.95.
4. Structural region diff over the panel + chrome: no >100-pixel diff mass buckets
   (the current buckets at columns ~520/1040/1060 and rows ~100/600–780 must clear
   — they are defects 1a/1b).
5. Crest and focus-ring region IoUs (§1 acceptances), quit dim check.
6. Ambient regions animate by design — mask them or capture at a pinned time; do
   NOT chase whole-frame equality across sessions.

## 5. Class-closing mandate (owner: "get Codex fixed so you won't have to do this again")

1. Wire a **visual-conformance gate into the battery**: headless capture of the
   settled screens vs the refs with the §4 metrics, masks for ambient motion
   (or a deterministic-time parameter in the app), thresholds as above. Settled-
   capture discipline applies (assert settled states, never fixed-delay snapshots).
2. **Mutation-test the gate** (a gate that can't fail isn't a gate): e.g. shift one
   glyph table entry by one line-pitch → gate trips; drop the crest quarterTurn →
   gate trips. Archive both trips in evidence.
3. Add to the capture-gap register (feeds #96 architecture docs): dialog
   panel/scrim/text pass unhooked; native focus chrome unhooked; fixture
   draw_order = enumeration order, paint order lives in the trace; Fonts bundle
   carries no glyph placement; row-collision measurement class; non-painting
   enumerated elements (e.g. beta_version_v_0_72.1).

## 6. Landing + deploy (owner's /game override covers this publication — nothing else)

1. Land this branch on main by rebase; full battery + CI green on the exact landed
   SHA before anything ships.
2. Deploy per the standing NFO protocol (webdeploy precedent, task #100): build
   from a FRESH clone of origin/main; wire the game app the same way as the
   current bundle (`index-*.js` under /game); preserve the robots meta (line 6,
   noindex) — /game stays unlinked and unannounced; ENGINE_STATUS stays frozen.
3. NFO box rules are absolute: shared host with live tenants — touch nothing but
   the site; the `solomon-dark-revived` service is NEVER restarted (deploy =
   atomic wwwroot rotation only; verify NRestarts=0 before and after); take the
   timestamped wwwroot backup tarball first; stamp VERSION.json DEPLOY_SHA;
   ssh/scp via the `nfoservers-root` alias only; NEVER print/log/commit anything
   from nfo-profile.json.
4. Probe with real GETs (HEAD returns 404 on this box — known gotcha).
5. Archive before/after screenshots of the live page in the evidence dir — the
   owner is promised a before/after pair.
6. Record rollback: previous wwwroot tarball path + one-line swap-back command.

## 7. Standing rails (violations are STOP-worthy)

- Sealed, never modified: `ambient-title-data.json`,
  `tests/fixtures/webgame/float-rng-goldens.json`, the menufix evidence sets, the
  atc-landing archive, owner installs/saves.
- Never `git add -A`; never force-push; commit exact files.
- No recursive greps/finds/hashing over /mnt/c or /mnt/d from WSL (bounded
  single-file reads OK; hash Windows-side via powershell.exe).
- Kill only your own exact PIDs, with command-line verification first.
- The ATC reference clone `/home/user/sd-menupreview` is read-only to you; work in
  your own clone.
