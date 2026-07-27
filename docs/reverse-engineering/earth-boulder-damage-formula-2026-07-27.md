# Earth Boulder damage formula (2026-07-27)

## Scope and phase-one status

Issue #52 asks where the client-cast Earth damage family near `3032.56`
comes from. This is an explanation-first investigation: changing a stock
damage value before tracing it would risk changing intended balance.

The 2026-07-25 suite audit first recorded converged client-origin Earth
damage of `3013.3374023438` while host-origin sustained damage was zero. A
2026-07-26 solo baseline then established that the stock level-one Boulder
charge curve produces `0.9072265625` for a two-frame click,
`1.541015625` for the fixed 170-frame hold, and exactly `10.0` at full
charge. The later five-cast client matrix recorded total HP deltas:

| Trial | Native HP transitions | Total delta |
| --- | --- | --- |
| 1 | `1.541015625`, then `3013.3374023438` | `3014.8784179688` |
| 2 | `2956.0327148438` | `2956.0327148438` |
| 3 | `1.541015625`, then `2956.0327148438` | `2957.5737304688` |
| 4 | `1.541015625` | `1.541015625` |
| 5 | `3013.3374023438` | `3013.3374023438` |

Both peers converged exactly in every trial. The unresolved finding is the
magnitude, not synchronization.

Phase one is a static trace against the retail executable with SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
It identifies a concrete client-only inflation mechanism in the loader. The
required controlled host/client experiments are intentionally still pending
at this commit, so the final issue verdict appears only after that evidence is
collected.

## Stock input and notation

The shipped `data/wizardskills/boulder.cfg` `mDamage` row is:

```text
0, 10, 30, 50, 75, 100, 130, 160, 200, 250, 300, 350, 400, 450, 500
```

For the formulas below:

- `s = 40` is the Boulder skill row;
- `c = 4` is its Earth spell class;
- `C` is the live Boulder charge at `Boulder + 0x74`;
- `P` is the caster's live progression/stat object;
- `M` is `mDamage` at the skill row's effective rank;
- `R` is the stock release-path multiplier: `0.5` for an early/manual
  release and `1.0` for automatic release at maximum charge;
- `B` is the live pre-release spell damage written to
  `PlayerActor + 0x298`; and
- `D` is the released Boulder damage pool at `Boulder + 0x1F4`.

There is no direct player-level multiplier. Level and upgrades affect the
effective skill rank used to choose `M`; equipment and passives affect named
fields in `P`.

## End-to-end stock formula

### 1. Resolve the configured rank value

`PlayerActor::Tick` at `0x00548B00` identifies selected skill `0x28` at
`0x00549F42`. It resolves the `mDamage` property through `0x005290F0`; that
property reader indexes the configured values with the skill row's effective
rank at row `+0x22`.

The call at `0x00549FD6` passes the resulting `M`, skill `40`, and flag `0`
to the stat calculator at `0x0065FFF0`. The result is stored at
`PlayerActor + 0x298` by `0x00549FEA`.

### 2. Apply caster damage stats

For Boulder, `0x0065FFF0` computes:

```text
A = P[+0x84]
  + M
  + P[+0xFC]
  + P[+0x288 + 4*s]
  + P[+0x120 + 4*c]

B = A
  * P[+0xF4]
  * P[+0x140 + 4*s]
  * P[+0x100 + 4*c]
  * P[+0xF8]

B = max(0, B)
```

The terms are:

| Term | Meaning |
| --- | --- |
| `P + 0x84` | Native base/global spell-damage additive accumulator. It is initialized to zero by the progression constructor at `0x006594E0`. |
| `M` | Rank-selected `boulder.cfg` `mDamage`; level-one Boulder supplies `10`. |
| `P + 0xFC` | Global spell-damage flat term from `FX_SPELLDAMAGE`. |
| `P + 0x288 + 4*s` | Per-spell flat term from `FX_ONESPELLDAMAGE`. |
| `P + 0x120 + 4*c` | Spell-class flat term from `FX_SPELLCLASSDAMAGE`. |
| `P + 0xF4` | Global spell-damage multiplier from `FX_SPELLDAMAGE`. |
| `P + 0x140 + 4*s` | Per-spell multiplier from `FX_ONESPELLDAMAGE`. |
| `P + 0x100 + 4*c` | Spell-class multiplier from `FX_SPELLCLASSDAMAGE`. |
| `P + 0xF8` | Siege Mage multiplier. `0x00661530` initializes it from `mValue`; `0x00661FD0` applies concentration; `0x0067C360` applies equipment/feature refresh changes. |

The progression refresh at `0x0065F5B0` supplies neutral defaults of zero for
flat terms and one for multiplier terms. A timed damage power-up can set the
global multiplier `P + 0xF4` to `4.0`.

The skill-row builder writes spell class `4` at `0x00677607` and sets row
flag `+0x27` at `0x00677745`. That flag is why `0x0065FFF0` includes the
Siege Mage term for Boulder. The optional cast-speed factor in
`0x0065FFF0` is not present here because the caller passes flag `0`.

No crit roll, random damage roll, or difficulty term exists in this call
chain. Bind Rocks and Hasten Rocks also do not add a damage multiplier:
Hasten Rocks changes the Boulder growth-rate field, and Bind Rocks changes
the toughness/pool-consumption field described below.

### 3. Materialize and grow the Boulder

The Earth dispatcher at `0x00544C60` creates native type `0x07D5`, registers
it at `0x00544CFB`, and copies `B` to both:

- `Boulder + 0x1F8`, the release-base damage; and
- `Boulder + 0x1F4`, the mutable damage pool.

It also copies the caster's growth-rate scalar from `PlayerActor + 0x2A0`
to `Boulder + 0x1D8`, and toughness from `PlayerActor + 0x29C` to
`Boulder + 0x1E8`.

While held, `0x00545122` advances growth from the Hasten Rocks rate and the
Earth cast-speed helper. When `C` is still below the maximum at
`Boulder + 0x1FC`, the stock manual-release branch at `0x00545155` uses
instructions `0x00545165` and `0x00545171` to multiply both damage fields
by the double constant `0.5` at `0x007DE808`. When charge exceeds `0.3`
(`0x0078567C`), the dispatcher also stops further growth.

When `C` has reached the maximum, the comparison at `0x00545100` skips the
manual-release block. The split/release path at `0x005FA6D0` then calls the
finalizer without halving the base.

Thus immediately before finalization:

```text
release_base = B * R
R = 0.5  when manually released before maximum charge
R = 1.0  when maximum charge causes automatic release
```

### 4. Convert charge to the released damage pool

The Boulder release virtual at `0x005E5450` computes:

```text
quadratic = (B * R) * C^2
cap       = (B * R) * 1.25
D         = max(0.25, min(quadratic, cap))
```

The instruction at `0x005E54DE` writes `D` to `Boulder + 0x1F4`, and the
finalizer copies `C` to `Boulder + 0x1FC`. The floor constant is the double
`0.25` at `0x007DE8F0`; the cap multiplier is the double `1.25` at
`0x00784740`.

For a neutral level-one caster, `B = 10`. The stock curve is therefore:

```text
early/manual: D = max(0.25, min(5  * C^2,  6.25))
maximum:      D = max(0.25, min(10 * C^2, 12.50))
```

The fixed-hold baseline `1.541015625` implies an early-release charge of
`sqrt(1.541015625 / 5) = 0.5551604498`; phase two records the underlying
single-precision charge rather than relying on decimal log rounding. A
maximum charge of `1.0` takes the unhalved automatic branch and produces
exactly `10.0`, matching the solo baseline without another term.

### 5. Apply contact damage

The recursive rock/contact tick at `0x00620B60` reads the remaining damage
pool from `Boulder + 0x1F4`. For an eligible hostile target it chooses:

```text
payload = min(target_current_hp, remaining_pool)
```

At `0x00621266` it multiplies `payload` by `0.5`, writes the half to both
global contact lanes `0x0081C6E8` and `0x0081C6EC` at
`0x0062127F..0x00621285`, then dispatches the contact through
`0x0063E7D0` at `0x0062128E`.

`Badguy::Contact` at `0x0048A290` subtracts those two lanes. Therefore:

```text
HP delta = payload/2 + payload/2 = payload
```

The Boulder path resets the global damage context at `0x0062125C` before
writing those lanes. It does not set the flag which could cause an additional
secondary subtraction, and it contains no crit or difficulty lookup.

After contact, the tick reduces the reusable pool at `0x006212A5`. If the
remaining pool is smaller than target HP it consumes the whole payload.
Otherwise it consumes `payload / (2 * toughness)`, where toughness is
`Boulder + 0x1E8`. This affects how many contacts the Boulder can survive; it
does not increase the first target's HP delta. Iteration stops below the
double threshold `0.001` at `0x0079E260`.

## The `1956` constant is not a stock Boulder damage term

The double at `0x007A03F0` is exactly `1956`. The retail executable has one
and only one reference to it: `0x0066B0E5` inside the primary spell
stat-vector builder at `0x00666020`.

In synthetic weld case `0x3F6`, that builder reads Boulder's configured
`mDamage` and writes this normalized output:

```text
primary_stat_output[0] = mDamage * 1956
```

The stock Earth damage chain does not read that output. `PlayerActor::Tick`
calls `0x0065FFF0` directly and copies its result to actor `+0x298`. There
is no reference to `0x007A03F0` in the dispatcher `0x00544C60`, release
finalizer `0x005E5450`, contact tick `0x00620B60`, contact dispatcher
`0x0063E7D0`, or `Badguy::Contact` at `0x0048A290`.

This matters because beta.18's remote-Boulder replay currently reads
`0x007A03F0` as `earth_boulder_damage_output_scale`. When the live native
release base is `10`, `ResolveEarthBoulderScaledReleaseBaseDamage` changes it
to:

```text
10 * 1956 = 19560
```

`HoldBotBoulderAtReleaseCharge` then writes `19560` into both
`Boulder + 0x1F4` and `Boulder + 0x1F8`. That hold write is repeated at the
replay release boundary and overwrites the native early-release half. The
finalizer therefore sees `19560`, not the stock level-one early-release base
of `5`. This is a second use of a stat-vector normalization constant that
stock Boulder contact damage never uses.

The archived beta.18 loader log already records a replay with rounded live
charge `0.392500`, `release_scaled_base_damage=19560`, and
`projected_damage=3013.337402`. Its actual native path is:

```text
D_inflated = max(0.25, min(19560 * C^2, 19560 * 1.25))
           = 3013.3374023438
```

The same log's `ProjectEarthBoulderReleaseDamage` estimate incorrectly
applies another `0.5` and reports `1506.668701`; the real HP transition is
the unhalved `projected_damage` value. A nearby rounded charge `0.388750`
produces the `2956.0327148438` family. The occasional independent
`1.541015625` transition is the stock early-release path with `B=10` and
`R=0.5`. This static decomposition explains both modes and predicts a
direction-dependent remote replay defect; phase two must prove that
prediction under pinned host/client conditions and preserve the exact
single-precision operands.

## Client damage-claim serialization

The generic claim path preserves the damage produced by native contact; it
does not multiply it.

1. `HookBadguyDamage` captures client HP immediately before
   `Badguy::Contact` only when the damage source resolves to the local
   participant.
2. After the native call it records exactly
   `damage = hp_before - hp_after`.
3. `client_enemy_damage_sync.inl` sends a 72-byte
   `EnemyDamageClaimPacket` with:

   ```text
   claimed_damage  = authoritative_hp - local_hp
   client_before_hp = authoritative_hp
   client_after_hp  = local_hp
   ```

4. `ValidateEnemyDamageClaim` checks finite values, caps, run identity, and
   spatial sanity. It applies no damage scale.
5. `ApplyEnemyDamageClaimPacket` computes:

   ```text
   accepted_hp = min(current_host_hp, clamp(client_after_hp))
   ```

   and writes that endpoint directly.

Consequently, a client-native inflated contact is serialized as an inflated
HP endpoint and converges exactly on the host. The claim path explains the
zero peer difference, but not the magnitude's origin. The origin is upstream:
the remote-Boulder replay's write of `mDamage * 1956` into native damage
fields.

## Static evidence

Headless Ghidra output is archived under:

```text
/mnt/d/codex-evidence/earth-damage-20260727/static/
```

Key records are:

- `ghidra-stock-earth-stat-copy.log` — selected Earth branch, config lookup,
  `0x0065FFF0` call, and actor `+0x298` write;
- `ghidra-formula-helpers.log` — complete caster-stat, release-finalizer,
  contact-tick, dispatcher, and enemy-contact decompilations;
- `ghidra-boulder-damage-chain.log` — dispatcher, constructor, finalizer,
  recursive contact, and damage application chain;
- `ghidra-formula-instruction-context.log` — exact release/contact write and
  call sites;
- `ghidra-formula-global-refs.log` — the sole `0x007A03F0` reference;
- `ghidra-formula-constants.log` — decoded double/float constants;
- `ghidra-progression-modifiers.log` — Siege Mage and damage-modifier writers;
  and
- `ghidra-skill-row-flags.log` — Earth class and Siege Mage eligibility row
  construction.

## Phase-two decision rule

The static trace predicts **client-only inflation**, not stock-correct
balance. That is not yet the final verdict. The controlled matrix must
demonstrate all of the following before code changes:

- host and client use the same class, level, fixture, HP, and measured charge;
- an instant release and a pinned held release expose the stock and inflated
  families;
- every observed delta is reproduced from logged `M`, caster-stat terms,
  release multiplier, charge, floor/cap choice, contact payload, and claim
  endpoint; and
- the `1956` term appears only on the replayed client-origin path.

If those conditions hold, the required action is to remove the normalized
stat-output scalar and all damage-field overwrites from the remote replay
seam, leaving native Boulder code as the sole owner of `+0x1F4/+0x1F8`.
If host and client instead produce the same family from identical stock
terms, no gameplay number may change and the audit model must be corrected.
