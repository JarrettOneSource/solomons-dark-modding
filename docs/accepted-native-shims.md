# Accepted Native Shims

This file names the native-facing shims that are allowed to remain before
multiplayer work starts. These are not arbitrary memory hacks. Each one exists
because stock Solomon Dark code still owns a gameplay contract that the loader
has to enter, seed, or observe.

## Admission Rules

A native shim is acceptable only when it has:

1. a named binary-layout key, Ghidra note, or live probe identifying the native
   owner;
2. one narrow write/read responsibility instead of a general replacement state
   store;
3. no silent fallback table for native gameplay facts such as damage, mana,
   movement speed, or actor defaults;
4. static or live coverage proving the native path is still used;
5. high-volume diagnostics gated behind `kEnableWizardBotHotPathDiagnostics`
   when the log is not a lifecycle, warning, or error event.

## Current Inventory

| Shim | Why it is kept | Guardrail before multiplayer |
| --- | --- | --- |
| Cast gate patches and progression-slot owner context | Stock cast handlers still read slot-owned progression and startup state. Bot casts enter those handlers through scoped owner context instead of replacing stock cast admission. | Keep writes scoped to the active cast window. Network code should send cast intent and authoritative outcomes, not remote direct progression writes. |
| Active spell object lookup and Boulder release normalization | Charged Boulder damage is owned by the live spell object and native progression scale. The loader observes the active object, projects lethal release, and writes release fields only for the current held Boulder. | Re-run target lethality after target swaps using the same charged Boulder state. Do not serialize direct enemy HP edits as a multiplayer damage protocol. |
| Native spell stats and mana spend scaling | Primary damage/mana tables were removed. Runtime stats come from `Skills_Wizard::BuildPrimarySpell` and bot mana spend follows the stock delta path. | Multiplayer must treat native spell build output as local simulation evidence and must not introduce parallel stat tables. |
| Source-profile staging for wizard visuals | Stock clone and descriptor builders need a temporary source actor/profile. The loader derives the staging data from native Skills_Wizard color output, lets stock code build descriptors, then clears the staging pointer. | Keep the staged profile transient. Multiplayer character data should be a profile/loadout input, not copied raw source-profile bytes. |
| Movement and pathfinding bridge | Bot movement uses stock actor movement and the live speed envelope while Lua owns follow policy and arrival thresholds. | Multiplayer needs an authority/reconciliation rule for positions; the local path builder is not a remote truth source. |
| Participant collision and target cleanup | Native actor registration, collision overlap, dead-body drive state, and hostile target cleanup still belong to stock scene ownership. | Keep the cleanup local to scene membership and death transitions until multiplayer ownership rules exist. |
| Live memory/debug tooling | Lua `sd.debug` and probe helpers are for reverse-engineering evidence and regression checks. | Keep debug memory APIs out of the multiplayer gameplay protocol and off by default in release-facing flows. |
| Diagnostic logging gates | Detailed visual, dispatch, and sync pump logs are useful during RE but expensive with many bots. | Default builds keep hot-path dumps behind `kEnableWizardBotHotPathDiagnostics = false`; lifecycle/error logs stay available. |

## Multiplayer Checklist

Before implementing networked participants, check each new gameplay write
against this list:

1. Is this value owned by stock code, the loader, or the future network
   authority?
2. If stock code owns it, are we entering a known native path rather than
   duplicating the rule?
3. If the loader owns it, is it scoped to one bot, one cast, or one scene
   transition?
4. If multiplayer owns it, is the local native shim only producing or consuming
   explicit intent/result data?
5. Would enabling several bots spam logs or per-frame memory dumps with default
   settings?

If the answer is unclear, treat the code as not ready for multiplayer until the
owner is named and covered.
