# Earth charge baseline (2026-07-26)

## Measurement

The `fire-solo` instance on ports `48401` and `48402` used the matrix's stock
manual-spawner fixture: one frozen type-`1001` wave enemy at
`(1800, 1824)`, reset to `5000` raw HP before each cast.

Three owner-local hold points were measured:

- The loader's two-frame click produced `0.9072265625` damage.
- The prior matrix's fixed 170-frame hold lasted about 1.7 seconds and
  produced `1.541015625` damage.
- A live charge-gated hold reached the native Boulder object's
  `charge == max_charge == 1.0` after `6.583` seconds and produced exactly
  `10.0` damage.

Each result came from one native raw-HP transition with no monitor read errors.
The exact-PID launcher cleanup stopped only the staged `fire-solo` executable,
and the crash log was empty.

Evidence:

- `/mnt/d/codex-evidence/fire-contact-20260726/earth/solo-baseline/result.json`
- `/mnt/d/codex-evidence/fire-contact-20260726/earth/solo-baseline/result-fixed-170-frames.json`
- `/mnt/d/codex-evidence/fire-contact-20260726/earth/solo-baseline/logs/`

## Finding

The solo charge curve does not explain the audited multiplayer result of
`1.541015625` host-origin versus `3034.1020507812` client-origin. A genuine
full charge deals `10.0`, not approximately `3000`, so the client-origin value
cannot be classified as a scripted charge-duration artifact from this
measurement.

Per the investigation boundary, no Earth product code or matrix charge policy
is changed here. The existing directional values remain the regression
baseline until a separately authorized investigation identifies the
client-origin source of the additional `3032.5610351562` transition.

## Resolution

The 2026-07-27 issue-#52 follow-up proved that the extra transition came from
an observer replay whose release base was overwritten with
`mDamage * 1956`, not from the stock charge curve. See
[`earth-boulder-damage-formula-2026-07-27.md`](earth-boulder-damage-formula-2026-07-27.md)
for the complete formula, claim trace, correction, and exact post-fix matrix.
