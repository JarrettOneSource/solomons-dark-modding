# menupreview handoff — 2026-08-07 (ATC → fleet)

Owner-visible task (#102): the deployed /game preview at solomondarker.com/game must
match the native menus. The owner reported rotated buttons/images and a beta-warning
dialog with no text or background; a second owner pass (2026-08-07, on the ATC stage
build) reported three more: OK un-clickable on the beta dialog, the dialog border
persisting after ESC, and a mangled Raptisoft loading bar. Most of the fix is landed
on this branch and verified; FIVE diagnosed defects remain (1a–1e below), then
conformance re-verification, landing, and redeploy. This document is the complete
state transfer: nothing below needs re-derivation, and every claim carries its
evidence.

Process (owner directive 2026-08-07): the owner is the acceptance tester and WANTS
the loop — fix what is diagnosed here, land + deploy, report DONE; the owner
re-checks and reports remaining or new defects; those come back to you as thread
resumes. Owner-reported defects are the task, not scope creep. Keep your work
resumable.

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

### 1c. Owner cannot click OK on the beta dialog (pipeline verified GOOD — fix the
### gate UX; most of the perception is 1d)
Verified live on the stage build (headless chrome, 2026-08-07) — do not re-derive:
- `KeyboardMouseProducer` listens for `mousedown`/`mouseup` on `window` (NOT
  pointer events, NOT `click`). Real-type MouseEvents at the OK center dismiss the
  dialog: beta-notice → main-menu-root. Controller path
  (`__webshell.dispatch({kind:'interact',target:'dialog.primary',phase:'press'})`)
  also dismisses. Fresh-boot flow end-to-end also dismisses once the input gate
  expires. `dialog.primary` is the only focus node, rect [702,643.5,898,712.5],
  enabled. The pipeline is NOT broken.
- The 2.0s boot input gate (`completeBoot`: `#inputGateUntil = clock()+2000`)
  swallows ALL input silently; it auto-clears by clock comparison (verified
  `inputGated:false` after expiry). The boot fade is 1.1s → a ~0.9s window where
  the dialog looks fully ready but eats clicks with zero feedback.
- Compounding: after a SUCCESSFUL dismiss, defect 1d repaints the dialog border +
  OK plate over the main menu — a working click looks like a no-op.
- FIX: check the 2000ms constant against the menure/flowre evidence; under the
  parity policy the gate must not outlive the native-visible readiness — at
  minimum, input must be accepted the moment the dialog is fully presented (gate
  tied to fade completion, not an independent longer timer). Then 1d does the rest.
- Acceptance: clean-profile fresh boot; a click on OK at fade-completion+50ms
  dismisses; owner confirms on their machine (iterate loop).

### 1d. Fixture contamination: beta dialog chrome baked into 21 of 27 non-beta
### layouts (owner's "border frame remains")
- Census (2026-08-07, against landed `tests/fixtures/webgame/menu-goldens.json`):
  all 15 overlay-reference members — UI.101 OK plate, UI.54 ×2 skulls, UI.18
  crest, UI.107–110 corner medallions, UI.17 ×4 filigree, UI.8 ×3 daggers
  (authoritative list: menufix evidence `candidate-v7/menu-overlay-reference.json`,
  sha256 5d331ef402a8bc4aadc30895cdc89578c022ba2a9907a0b1d0c580e953f68570) —
  appear at EXACT beta-notice rects in 21 non-beta layouts: main_menu (gen 14),
  create_element, create_discipline, profile_save_select, pause_menu,
  hall_of_fame, controls, performance, settings ×3, simple_menu, and all
  dark_cloud_* screens. Clean: native_loader, loading_screen,
  control_scheme_picker, skill_picker, map_picker, game_over.
- Mechanism: G11 capture-session bleed — the hook kept the dialog's members
  enumerated on screens captured after the session passed through the dialog
  (ascending generations corroborate).
- Player-visible effect: dismissing the dialog lands on main-menu-root, which
  repaints border/plate/daggers WITHOUT panel/scrim/text (the shell's
  reconstruction layer is beta-only) — the owner's "border frame remains", and
  the misperception feeding 1c.
- FIX (sequencing): menufix (#97) is landing a settled re-capture of ALL 28
  fixtures; its fresh captures are clean (its own overlay-reference derivation
  proves settled main_menu carries zero overlay members). Implement 1a/1b/1c/1e
  now; when menufix lands on main, REBASE onto main, re-run the census (below)
  expecting zero contaminated layouts, then run final §4 verification + deploy.
  If menufix has NOT landed when you are otherwise done: STOP and report — do NOT
  hand-edit fixtures, do NOT deploy with contaminated fixtures.
- Census procedure (make it a battery gate, §5): needles = the 15
  (art_id, rect) pairs from menu-overlay-reference.json; for each
  `layouts[].layout` in menu-goldens.json count kind=art visible=true members
  matching art_id + rect within ±0.5. FAIL if any non-beta_notice layout has ≥1
  hit. Mutation tests: inject one chrome member into a clean layout copy → trips;
  menufix's fixtures → passes.
- Re-attribution: the §4 structural-diff buckets at columns ~520/1040/1060 and
  rows ~100/600–780 are THESE members painting on main-menu-root (rects match
  UI.107–110/UI.17), not defects 1a/1b as previously written. They must clear
  after the rebase with no code change; 1a/1b acceptance regions are unchanged.

### 1e. Raptisoft loader bar mangled (owner: "loading bar is cooked now — before
### it was fine")
- Reproduced on the stage build (`__webshell.showLayout('native-loader')`): logo
  (Loader.2) and URL fine; the bar is a red smear over a squashed white frame
  with notches.
- Root cause (exact, third instance of the crest class): the orientation-as-data
  cutover removed aspect inference, which had been silently turning these; the
  native-loader screen never received declared turns. Atlas truth vs placement:
  - Loader.0 (bar fill): logical 18×192 portrait → placed [704,572,896,590] =
    192×18 landscape → REQUIRES a declared quarter-turn.
  - Loader.1 (bar frame): logical 54×230 portrait → placed [685,553,915,607] =
    230×54 landscape → REQUIRES a declared quarter-turn.
  - Loader.3 (244×18 → placed 244×18) and Loader.2 (388×227 as-is): no turn.
- FIX: add the two entries to `native-orientation.ts` (same mechanism as 1a).
  Verify turn DIRECTION visually (quarterTurn:true = source TL→dest TR = 90° CW;
  if the art reads wrong-way, it needs the opposite composition — check against a
  native boot screenshot / menure reference). CRITICAL: `withLoaderProgress`
  scales/clips the Loader.0 fill by progress fraction — under a quarter-turn the
  progress axis maps to the source's OTHER axis; verify at partial progress that
  the bar fills left→right on screen (cpu-throttled boot or a forced
  partial-progress render).
- CLASS CLOSE: run a transposition audit across ALL 28 layouts — every kind=art
  member whose atlas logicalSize aspect is transposed vs its placement rect
  (W/H ≈ rect H/W within tolerance) must have a declared orientation entry. Emit
  the audit table into evidence and wire it as a battery assertion (transposed
  placement with no declared turn = FAIL). Mutation: remove the Loader.1
  declaration → trips.
- Acceptance: bar-region conformance in (679,541,923,610) vs a native loader
  reference (menufix's re-capture includes reference captures; else screenshot
  the native game's boot), plus owner visual sign-off (iterate loop).

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
2. Fresh build + capture of ALL 28 screens via `__webshell.showLayout(id)` — the
   1e regression escaped because only beta-notice and main-menu-root were
   captured. Native refs exist for those two; for the rest, assert the structural
   gates (transposition audit, fixture hygiene, no-throw render, glyph-table
   coverage) and eyeball-diff against menufix reference captures once available.
3. Per-line ink IoU (template ink = atlas alpha>128; bright = luminance>120 lit /
   >40 dimmed; score = hit/n − 0.5·spill/n): every dialog line ≥ 0.95; expect the
   current 0.997+ on lines already passing — a regression below a line's current
   value is a defect even above 0.95.
4. Structural region diff over the panel + chrome: no >100-pixel diff mass buckets.
   The pre-existing buckets at columns ~520/1040/1060 and rows ~100/600–780 are
   defect 1d contamination painting on main-menu-root — they clear after the
   menufix rebase with no code change (see 1d re-attribution).
5. Crest and focus-ring region IoUs (§1 acceptances), quit dim check, loader
   bar-region check (1e acceptance).
6. Fixture-hygiene census green (1d) and transposition audit green (1e) — both
   wired as battery gates with archived mutation trips.
7. Ambient regions animate by design — mask them or capture at a pinned time; do
   NOT chase whole-frame equality across sessions.
8. Clean-profile fresh-boot click test (1c acceptance): OK dismisses at
   fade-completion+50ms.

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
   enumerated elements (e.g. beta_version_v_0_72.1); capture-session bleed —
   hook enumeration retains dialog members on screens captured after the dialog
   (21/27 landed layouts contaminated, defect 1d).
4. The battery gate list now includes the 1d fixture-hygiene census and the 1e
   transposition audit, each mutation-tested in BOTH directions (trip + pass)
   with trips archived in evidence.

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
