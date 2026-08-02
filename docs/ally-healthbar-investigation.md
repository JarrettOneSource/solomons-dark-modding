# Multiplayer names and health bars

This note records the live-tested native render seams used for multiplayer
participant names. It supersedes the earlier `FUN_00500250`, HUD case-100, and
`DAT_008199B8` hypotheses.

## World nameplate

Remote `PlayerWizard` actors remain ordinary native scene actors. After the
complete `Arena_Render` call at `0x0046EC80` returns, the loader draws:

- the connected participant's display name with command-aware ExactText
  (`0x0043BCD0`) at half scale;
- a 7-pixel-tall health bar through the stock native renderer color setter
  (`0x0041FE50`) and untextured-quad primitive (`0x0041DD70`), spanning the
  estimated name width with a 64-pixel minimum.

The native name draw carries the participant identity and the participant's
authoritative replicated HP ratio into the native indicator draw. The ratio is
resolved from the multiplayer runtime snapshot at render time, not from the
materialized actor's progression memory: that memory is only rewritten by the
player-actor tick, which pauses (level-up barrier, death quiesce) while the
render pass keeps drawing, so it goes stale exactly when remote vitals change
the most. Runtime vitals refresh from 50 ms participant frames plus host
corrections, so the bar follows the authority promptly and any real
client/host divergence stays visible instead of being smoothed over. Name and
bar now share one native post-scene draw and never enter the D3D9 `EndScene`
overlay. This matches the stock tutorial loot-arrow idiom: the target is world
projected, the indicator stays above scene geometry, and tile light does not
tint it. There is no text, quad, or ASCII overlay fallback.

## Top-center ally rows

The stock `ALLY` label is `UI.bundle` record zero. In the retail bundle it is a
26-by-7 sprite:

- rectangle: `(-13, -3.5, 13, 3.5)`;
- UV: `(0.09423828125, 0.04833984375, 0.119384765625, 0.054931640625)`;
- bundle pointer global: `DAT_008199E4` (`0x008199E4`).

The recovered native data path is:

1. `FUN_0052C910` queues `(health ratio, UI.bundle + 0x38)` through
   `FUN_005CF480` into the `Game::HealthBar` list.
2. `FUN_005D2520` consumes that list and renders each row.
3. The row label calls the centered glyph renderer at `0x004142E0`; the exact
   return address after that call is `0x005D3521`.

The launcher expands that record to 128-by-7 and renders `ALLY` into it. The
native health-bar layout then reserves enough horizontal space for the full
multiplayer display-name limit instead of placing the red bar under the name.
Single-player retains the stock label.

The loader hooks only `0x004142E0` calls where both facts match: the caller is
`0x005D3521` and `self == *DAT_008199E4 + 0x38`. Other centered glyph draws are
passed through untouched.

For each matching call, connected remote wizard participants are sorted by
their local gameplay slot. The current row's stock `ALLY` sprite is replaced
with that participant's quarter-scale ExactText name inside the already-active
HUD transform. The name begins two HUD units after the bar and must end inside
the reserved 128-unit label slot. The protocol carries at most 31 display-name
bytes; even 31 widest glyphs consume 124 units at this scale, leaving the
required two-unit padding on both sides. The original `ALLY` sprite is
suppressed for multiplayer rows. A failed name draw is logged and does not
substitute a generic label.

## Rejected paths

- The five sprite calls in `FUN_00500250` are mixed UI assets, not five ally
  rows.
- HUD case `100` and the `PlayerWizard` vtable calls reached from it do not own
  the stacked label draw.
- `DAT_008199B8` is not the live bundle pointer used by this renderer; the
  verified global is `DAT_008199E4`.
- The screen wrapper at `0x004A57C0` does not parse `_s(0.5)` in this context;
  it visibly rendered the command as literal text. Direct ExactText rendering
  under the current HUD transform parses the command correctly.
- Rewriting `UI.bundle` record zero cannot provide per-row names because every
  stock row reuses the same sprite record.

## Verification

`tools/verify_multiplayer_hud_names.py` launches three independent instances,
waits for all six observer/participant relationships, changes one participant
to half health, and captures every D3D9 backbuffer. For each remote participant
on each observer it requires a successful native post-scene name/bar draw and
a successful ally-row name draw. The half-health case must produce a second
native draw at 50 percent, and captured pixels must contain the matching filled
and empty segments. The verifier separately parses the stock-HUD row geometry
and fails if a row name begins over its bar or extends beyond its reserved
label slot.
