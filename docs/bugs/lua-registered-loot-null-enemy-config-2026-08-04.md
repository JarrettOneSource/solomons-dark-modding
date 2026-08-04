# Registered Lua loot never rolls when native enemy config is null

## Status

Confirmed on `v0.1.0-beta.31`; foundational fix pending.

## Investigation

Invincibility Potion 0.2.0 loaded successfully in isolated hosted
beta.31 sessions. On both peers, `sd.loot.list()` retained exactly one entry
for `canary.lua.invincibility_potion`, with `chance=0.5` and
`boss_chance=1.0`. The item resolved to content ID
`8068156596081641415` and native subtype `6`.

The live matrix accepted 50 normal enemy deaths and three stock-boss deaths.
It included natural waves as well as controlled exact-stock spawns. No potion
drop was authored on either peer. The boss cases remove random chance from the
result because the registered boss chance is 100%.

Natural-wave results reproduced the failure on both map paths:

- Stock `survival.boneyard`: eight live native enemies, eight accepted deaths,
  zero potion rows.
- Sample Boneyards `Alpha Arena.boneyard`: nine live native enemies, nine
  accepted deaths, zero potion rows. The host and client staged files both had
  SHA-256 `d596b4915140f5faa23fd1286e3d622c6189ecb00b9667f5e7b3444a84b8322b`,
  matching the shipped Alpha Arena source.

For every sampled natural enemy, `actor_owner` was readable and nonzero,
native type and position were valid, but `enemy_config` was readable and null.
The loader log then reported:

```text
[lua] drop.rolling skipped because the stock selector state could not be captured.
```

Evidence is under `/mnt/d/codex-evidence/potiondrop-20260804/`, especially:

- `diagnosis/natural-stock/live-result.json`
- `diagnosis/natural-custom/live-result.json`
- `diagnosis/filter-context/live-result.json`
- `baseline/stock/controlled/live-result.json`
- `baseline/custom/controlled/live-result.json`

## Root cause

The additive `sd.loot.register` pool was attached to `HookDropSelector`, the
native stock-loot mutation seam. Before the hook reaches `RollLuaLootPool`, it
requires `TryCaptureLuaDropRollFilterContext` to capture all state needed to
temporarily rewrite stock selectors: a nonzero enemy config pointer, six
selector bytes, and the arena disable mask.

Those fields are required for `drop.rolling` filters and registered enemy
`loot_policy`; they are not required to roll an additive Lua item. Normal
native wave enemies on both the stock and custom boneyards legitimately had a
null `enemy_config`. Context capture therefore failed, the hook called the
stock selector unchanged, and returned before `QueueLuaLootPoolDrops`. A 100%
boss entry was suppressed exactly like a 50% normal entry.

This coupling entered with the first additive loot-pool implementation in
commit `5dc8575` and was shipped by beta.31. It is not a later beta.31
regression from a previously working live drop path; the original canary
publication did not include a live enemy-drop acceptance test.

## Correct ownership

Additive loot must roll once from the authoritative enemy-death epoch. That
hook already captures the native enemy type and death position before calling
the stock death function, and it already rejects an already-handled death.
It therefore has every input the pool needs without depending on mutable stock
selector configuration.

`HookDropSelector` should continue to own stock drop filtering and registered
enemy `loot_policy`. The additive pool should be removed from that hook's
activation and rolled from `HookEnemyDeath` only when the local peer is Lua
simulation authority and the death is newly handled in an active combat arena.
This preserves stock behavior, prevents client-authored duplicates, and makes
stock and custom boneyard deaths follow the same additive-loot path.
