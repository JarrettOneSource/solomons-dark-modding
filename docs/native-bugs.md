# Native (Stock Game) Bugs

Confirmed defects in the retail Solomon Dark 0.72.5 binary itself — not in the
loader, launcher, or any mod. Each entry was reverse-engineered to a mechanism
and left UNFIXED on purpose: changing stock gameplay behavior is an owner
decision, tracked here as a pick-list.

Ground rules when fixing one:

- Investigation docs land before the fix commit, and the fix must close the
  class, not the symptom.
- A stock-behavior change must be replication-safe: all peers must run the
  same rule or the fix must be authority-side only.
- Update this file's Status column in the same commit as the fix.

| # | Bug | Area | Status |
| - | --- | ---- | ------ |
| 1 | Deflect concentration bonus does nothing (adds 0 to poison resist) | Skills | Open |
| 2 | Creativity ignores slot B and Mind Chug | Skills | Open |
| 3 | Level-up sparkles re-arm and flicker on every level transition | VFX | Open (cosmetic) |
| 4 | Camera view unclamped at authored map edges (skybox bleed) | Camera | Open (cosmetic) |

## 1. Deflect concentration bonus does nothing

- **Mechanism:** the concentration dispatcher at `0x00661FD0` reaches the
  Deflect row-68 case at `0x006621E8`, reads the absent `mConcentration`
  member through `0x0065D540` (which returns zero), and adds that zero to the
  poison-resistance field at `+0xA8`. Deflect's actual reflection stat is
  never touched — the bonus is wired to the wrong stat AND always zero.
- **Observed live:** row 68 executed once per proc; Deflect and poison values
  both `0.0 -> 0.0`.
- **Discovered by:** SKILLRE (suspect) / SKILLFIX (confirmed, 2026-08-02).
- **Evidence:** `docs/re/skillfix-discipline-and-concentration-2026-08-02.md`,
  Ghidra excerpts under `codex-evidence/skillfix-20260802/ghidra`.
- **Fix sketch:** route the row-68 case to the Deflect reflection stat and
  source the real concentration value; both sides must agree in multiplayer.

## 2. Creativity ignores slot B and Mind Chug

- **Mechanism:** the skill-apply builder at `0x0066F920` pushes the fixed
  slot-A index `0x10` at `0x0066FB57` and compares Creativity at `0x0066FB63`.
  It never queries slot-B index `0x14` nor the Mind Chug timer at `+0x828`,
  so Creativity's advertised interactions with the second slot and Mind Chug
  simply never happen.
- **Observed live:** slot-B and Mind-Chug fixtures both traced index 16 with
  apply counts `1/1/1/1` — identical to the no-interaction baseline.
- **Discovered by:** SKILLRE (suspect) / SKILLFIX (confirmed, 2026-08-02).
- **Evidence:** same document and Ghidra directory as bug 1.
- **Fix sketch:** extend the builder to also evaluate slot B and the Mind
  Chug timer; replication-safe only if every peer applies the same rule.

## 3. Level-up sparkles re-arm and flicker

- **Mechanism:** each genuine level transition arms the native 180-tick
  sparkle/light timer on the actor. Rapid successive levels re-arm it, which
  reads as the effect "going away for a moment and coming back". Unspent
  skill points do not drive the timer.
- **Discovered by:** owner observation during BOTENDURE; VISUALSWEEP verdict
  "documented stock transient; no fix" (2026-08-01).
- **Evidence:** `codex-evidence/visualsweep-20260801/final/completion-summary.json`
  (finding 3) and its `stock-findings` directory.
- **Fix sketch:** cosmetic only — either extend/merge the timer window on
  re-arm or gate re-arm while the effect is active. Purely presentational,
  safe to fix client-side.

## 4. Camera view unclamped at authored map edges

- **Mechanism:** the stock camera is not clamped to authored terrain or nav
  bounds, so near map edges the view exposes out-of-world backdrop (skybox
  bleed / glitchy glow). Reproduces in single player with multiplayer
  transport disabled — purely stock.
- **Discovered by:** owner observation during BOTENDURE; VISUALSWEEP verdict
  "documented stock behavior; no fix" (2026-08-01).
- **Evidence:** `codex-evidence/visualsweep-20260801/final/completion-summary.json`
  (finding 5) and its `stock-findings` directory.
- **Fix sketch:** clamp the camera target to authored bounds (per-boneyard
  extents are already parsed by the loader); presentational, client-side.
