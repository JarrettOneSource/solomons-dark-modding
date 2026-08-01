# VISUALSWEEP root-cause audit

This audit closes the five presentation findings deferred from the accepted
BOTENDURE R25 run. Investigation was performed at
`a6eeb0502fcdfa95904d276a35aba6b971b9b171` before changing production code.
The read-only BOTENDURE source is
`/mnt/d/codex-evidence/botendure-20260731/runs/steam-r25-final`; the independent
VISUALSWEEP evidence root is
`/mnt/d/codex-evidence/visualsweep-20260801`.

## 1. Duplicate ally HUD row

### Mechanism

The duplicate is a native health-bar registry ownership error, not a label or
overlay draw error. Stock `PlayerControlBrain::Update` at `0x0052C910` appends
one record through `0x005CF480` to the gameplay health-bar array at
`gameplay +0x1C14`; its count is `gameplay +0x1C20`. A stock local slot-0 player
does not have a control brain. Bot Play installs one for local-player takeover,
so the stock control-brain update incorrectly registers slot 0 as an ally. The
real remote slot-1 control brain also registers its row. With one remote peer,
the native renderer therefore consumes two records.

`BuildGameplayAllyHudRows` still returns exactly one remote binding. The row
label hook restarts from that one-row binding set and labels both native rows
with the same peer name; it did not create either row. The recent primary-skill
selection priming also does not write gameplay slots or the health-bar list.

### Evidence

- `baseline/hud-duplicate-host-a6eeb05.png` and
  `baseline/hud-duplicate-client-a6eeb05.png` show two same-name ally rows with
  only slots 0 and 1 populated.
- `baseline/hud-duplicate-state-a6eeb05.json` records slot 0, active takeover,
  and the nonzero local control brain on both peers.
- `investigation/ghidra-hud-decompile.txt` records the `0x0052C910` writer and
  `0x005CF480` count increment.
- `docs/ally-healthbar-investigation.md` records the independently recovered
  registry and renderer path.

### Verdict and correction boundary

Defect. Correct the registry writer boundary: after the local slot-0 control
brain update, retire only the one health-bar record that call appended. Remote
control brains and the renderer remain unchanged. This removes invalid local
ownership rather than hiding a rendered row.

## 2. Premature client enemy-death presentation

### Mechanism

The client damage-claim sender treated a lethal claim as an accepted death.
`SendLocalEnemyDamageClaim` immediately called `TryTriggerRunEnemyDeath`,
marked replicated death presentation started, suppressed loot, and installed a
pending-lethal window. Positive authoritative HP was then forbidden from
reconciling while either presentation or the pending window was active.

That path drives the stock death presenter from speculative display damage; no
replicated death event is required. A rejected claim therefore leaves the host
enemy alive while the client has already played death VFX, marked the actor
handled, and removed its binding.

### Evidence

- `baseline/enemy-rejected-lethal-before-client-a6eeb05.png` and
  `baseline/enemy-rejected-lethal-premature-vfx-client-a6eeb05.png` are the
  before/after client frames for one deliberately invalid lethal claim.
- `baseline/enemy-rejected-lethal-state-a6eeb05.json` records client
  `death_handled=1` and no binding 200 ms after the claim while the host remains
  `hp=100`, `dead=0`, `death_handled=0`. The host log rejects the claim for
  `target_position_drift`; the client log records `local_death_called=1`.
- The source path is
  `multiplayer_local_transport/client_enemy_damage_sync.inl`; the positive-HP
  blocks are in
  `world_snapshot_reconciliation/run_enemy_health_and_status.inl` and
  `world_snapshot_reconciliation/run_lifecycle_and_materialization.inl`.

### Verdict and correction boundary

Defect. A client hit remains a claim until host authority accepts it. Remove
speculative lethal presentation and the pending-lethal state class. Gate an
organic local client death callback for a tracked replicated enemy while the
fresh authoritative snapshot says `dead=false` and `hp>0`; positive authority
then restores the damaged presentation through normal reconciliation. Accepted
death results and dead authority snapshots remain the only death presenters.

## 3. Reappearing level-up sparkles

### Mechanism

The owner-era unspent-skill-point hypothesis is false. Native level-up at
`0x0067C250` calls `0x005C88B0` only after a real local level transition.
`0x005C88B0` resolves the local player actor, and `0x00528A20` writes `180.0`
to `actor +0x168`. Player tick helper `0x00533520` decrements that timer by one
per native tick and emits additive sparkle particles while it is positive.
Player light submission at `0x005299A0` also adds randomized light while the
same timer is positive. The effect therefore clears after 180 player ticks and
legitimately starts again on the next level transition.

The visually adjacent Planewalker effect is a different lifecycle. Its
modifier owns `actor +0x138` bit `0x10`; controlled set/clear evidence is kept
only to falsify that alternative.

### Evidence

- `investigation/ghidra-level-up-decompile.txt` records the complete
  `0x0067C250 -> 0x005C88B0 -> 0x00528A20` chain, the `180.0` constant, and the
  `0x00533520` timer decrement/particle branch.
- BOTENDURE's client log records a genuine level transition to level 10 at
  `01:37:44.309`. The wave-115 client frame was triggered at approximately
  `01:37:47` and shows the expected trailing particles during the final timer
  tail.
- R25 records all level-up barriers resolving and all offered skill choices
  being consumed; there is no outstanding offer or unspent-choice state at the
  wave-115 capture.
- `baseline/sparkles-state-a6eeb05.json` plus the three Planewalker frames show
  that unspent points remain zero while the separate `+0x138` state is toggled.

### Verdict

Expected stock transient presentation; no fix. The apparent disappearance and
return is the 180-tick effect ending and a later, real level-up starting a new
timer. Suppressing or shortening it would change stock feedback rather than
correct a lifecycle defect.

## 4. Black remote player at distance

### Mechanism

Distance is a correlation, not the render predicate. Stock player light submit
at `0x005299A0` emits a light only when either `actor +0x160 == 0` or the
gameplay-slot actor's animation-drive byte at `actor +0x5C` is zero. A remote
participant has a nonzero slot, so any replicated nonzero animation-drive state
skips its light completely. Long-range Bot Play movement and casting keep that
drive state nonzero more often, making the failure appear distance-triggered.

The loader already bridges the same missing native-light case for remote
corpses, but only while a remote-death epoch is active. Living remote actors use
the same stock predicate and had no bridge.

### Evidence

- `baseline/remote-light-skipped-drive-nonzero-host-a6eeb05.png` and
  `baseline/remote-light-stock-drive-zero-control-host-a6eeb05.png` hold both
  players at the same 625-unit separation. The remote actor is black with drive
  1 and lit with drive 0.
- `baseline/remote-light-state-a6eeb05.json` records the exact positions,
  replicated and native drive values, slot 1, and the two captures.
- `investigation/ghidra-visual-lifecycle-decompile.txt` records the stock
  `0x005299A0` predicate and the arena light-list consumer at `0x0046EC80`.
- The existing corpse-only bridge is
  `mod_loader_gameplay/bot_movement/native_remote_vitals_and_playback.inl`.

### Verdict and correction boundary

Defect. Generalize the existing bridge to submit the missing native remote
participant light whenever the exact stock predicate skips it: nonzero gameplay
slot and nonzero animation drive, alive or dead. Do not bridge drive-zero actors,
which already submit their stock light.

## 5. Arena-edge skybox/void bleed

### Mechanism

Stock arena tick `0x0046E570` derives the view origin from the local player and
view scale, then writes the region view rectangle without clamping it to the
authored terrain or navigation bounds. At a traversable boundary, most of a
1600-by-900 viewport can therefore extend past the authored arena and expose
the black/bright effect backdrop. Multiplayer does not alter this camera path.

### Evidence

- `baseline/arena-edge-transport-on-a6eeb05.png` and its state JSON record a
  player settled at `x=3030.58` beside nav max `x=3050`, with view origin
  `x=1855.39` and width `1185.19`.
- `baseline/arena-edge-stock-transport-off-a6eeb05.png` and
  `baseline/arena-edge-stock-transport-off-state-a6eeb05.json` reproduce the
  same unbounded view in a separate stock, transport-disabled solo run. In that
  rotated arena the player settles at `x=2464.53` beside nav max `x=2450`, while
  the view begins at `x=1289.34` and remains `1185.19` units wide.
- `investigation/ghidra-visual-lifecycle-decompile.txt` records the native arena
  camera calculation. `baseline/stock-solo-launch.json` and
  `baseline/stock-solo-cleanup.json` establish transport-off launch and exact
  process cleanup.

### Verdict

Documented stock behavior; no fix. Camera clamping would be a game-design
change with map-shape and combat-visibility consequences, not a multiplayer
correction. The edge is normally outside ordinary player travel, but the
renderer behaves identically with transport disabled.
