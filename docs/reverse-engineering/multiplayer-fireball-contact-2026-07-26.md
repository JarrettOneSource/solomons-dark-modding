# Multiplayer Fireball client-contact investigation (2026-07-26)

## Scope and reproduction

Commit `f769538` made the scripted cast direction deterministic. Five
host-origin Fireballs then dealt exactly `4.0` each, while client-origin
Fireballs remained intermittent even though both peers always converged on the
same HP. The prior matrix result is:

- `/mnt/d/codex-evidence/element-damage-20260726/post-fix/fire/result.json`

The dedicated `fire` loopback pair on ports `48401` and `48402` reproduced the
residual as `0.0, 0.0, 0.0, 4.0, 0.0`. A second run with native Fireball tick,
candidate-query, impact, and damage-context traces reproduced the more
diagnostic `0.0, 4.0, 0.0, 8.0, 4.0` sequence:

- `/mnt/d/codex-evidence/fire-contact-20260726/baseline/fire-client-5/result.json`
- `/mnt/d/codex-evidence/fire-contact-20260726/investigation/fire-trace-visual/result.json`
- `/mnt/d/codex-evidence/fire-contact-20260726/investigation/fire-trace-visual/logs/`

All five traced outcomes converged exactly between peers. Crash logs were
empty.

## Native contact trace

Fresh read-only Ghidra output is under
`/mnt/d/codex-evidence/fire-contact-20260726/investigation/`. It establishes
the native path:

- `Fireball::Tick` at `0x005FDD90` advances the type-`0x7D4` object, then calls
  the candidate query at `0x00641220`.
- `0x00641220` converts the projectile's current `x/y` to one spatial cell
  through `0x00522E30`, iterates only that cell, and circle-tests its actors.
  It does not visit adjacent cells.
- A candidate calls Fireball impact at `0x005E5160`. Group `0` projectiles seed
  the stock damage context and dispatch `0x0063E7D0`; group `0xFF` remote
  presentation projectiles cannot damage.

The traced first client cast ran 128 Fireball ticks and 128 candidate queries
but never called `0x005E5160` or `0x0063E7D0`. Its trajectory started at
`(1684.5, 1799.5)`, passed the enemy's `x=1800` at `x=1801.5`, and continued
to `x=2710.5`. The enemy stayed at `(1800, 1800)`. Successful casts started at
`(1694, 1800)`, called impact and the damage-context dispatcher once, and
stopped at `x=1802`.

The half-unit lane is a controlled-fixture boundary, not an aim, damage, or
replication defect. A follow-up ten-cast trace continuously pinned the source
caster to `(1624, 1800)` and parked the non-casting participant 320 units off
the projectile lane. It still correlated every miss with native emitter output
`(1684.5, 1799.5)` and every contact with `(1694, 1800)`. Thus participant
overlap is excluded: stock Fireball birth can use either of two native emitter
positions at this animation boundary. Both have the pinned eastward velocity.

The fixture put the enemy exactly on spatial row boundary `y=1800`. The lower
emitter path stayed on row `1799`, while the target remained in row `1800`.
Because the stock candidate query visits only the projectile's current cell,
the circle test never saw the target. Moving the controlled target into the
cell interior at `y=1824`, while preserving the same 176-unit eastward lane,
produced ten consecutive client native impacts and exact `4.0` contacts.

## Claim cursor root cause

The successful native contacts expose a separate product defect in the exact
damage claim serializer introduced by `ceb5732`.

`ObservedLocalEnemyDamage::reference_hp` and
`last_enemy_claimed_hp_by_network_id` are paired absolute-HP cursors. The
reference cursor is intentionally held across delayed authority snapshots,
then released after `750` ms of quiescence. The release block clears only
`reference_hp`; it leaves `last_enemy_claimed_hp_by_network_id` at the prior
absolute after-HP.

The traced sequence proves the consequence:

1. Cast 2 made one native `4.0` transition. Claim 1 sent and was accepted as
   `5000 -> 4996`.
2. After the harness restored the authority baseline to `5000`, cast 3 again
   reached native impact and accumulated exactly `4.0`. The sender derived
   after-HP `4996`, matched the stale last-claimed cursor, and suppressed the
   packet. The exact `4.0` remained pending.
3. Cast 4 reached native impact once and added another exact `4.0`. The
   accumulator then sent the retained `8.0` as `5000 -> 4992`, which the host
   accepted. The apparent double contact was two serialized contacts, one
   deferred by the stale cursor.

Client and host logs record one damage-context call for each of casts 2
through 5, no claim after cast 3's threshold log, and the next accepted claim
as exactly `8.0`. This excludes duplicate Fireball impact and host remote
projectile damage.

## Fix boundary

The product fix belongs at the paired cursor lifecycle: when quiescence
releases `reference_hp`, release the matching last-claimed absolute HP cursor
for that network actor in the same block. Delayed snapshots remain protected
for the existing bounded hold, while a later genuine contact starts from the
current authority baseline. Pending exact native damage, retry behavior, host
validation, and every damage scalar remain unchanged.

The harness fix is separate and fixture-only: place the target in a spatial
cell interior (`y=1824`), continuously park the non-casting participant off
the projectile lane, and pin only the casting player to the controlled origin.
Independent matrix cells must also honor the serializer's bounded quiescence
before casting against a deliberately restored HP baseline.
