# Native Lua framework to rebuilt-web runtime contract

Status: implementation boundary recovered for the Website `/game` port,
2026-08-20.

## Scope and evidence

This report separates the loader's Lua authoring contract from implementation
details that exist only because the native product is an injected x86/D3D9
process. The reusable source contract is Lua API `0.2.0`, the module inventory
in `docs/lua-seam-roadmap.md`, the root-reachable binding registry, runtime
bootstrap and per-mod state lifecycle, and the multiplayer authority taxonomy.
The stock executable has no Lua engine; the native evidence here is the current
Mod Loader source rather than a retail-binary claim.

The native implementation census at `190a1573631e75109ab2b22b2d2c1a05e7636dbb`
contains 144 Lua-named loader files and 45,279 lines. Its public boundary has
three ownership classes:

- simulation functions run on the simulation owner and replicate outcomes;
- presentation functions run locally on every peer and never author shared
  state;
- runtime/meta functions are local unless they name an explicit replicated
  channel.

The rebuilt web product instead has one portable Node authority for every
session and presentation-only browser clients. The web port must retain the
semantic classes, exact mod identity, bounds, and teardown rules without
recreating peer-owned native actors, memory pointers, D3D9, BASS, or Win32.

## Complete namespace disposition for the first web runtime

`exact-ported` means the first web runtime supplies the namespace member whose
underlying `/game` system already exists. `out-of-system` names a missing web
game system, not unfinished work hidden inside this implementation.

| Namespace/member family | First web disposition | Ownership consequence |
| --- | --- | --- |
| `sd.runtime` mod/frame/multiplayer/capabilities | `exact-ported` | One persistent `web.dev-console` VM reads the current authoritative frame and capability set. |
| `sd.state` get/default/set/delete/clear/snapshot/revision/authority | `web-adapted` | Native-shaped semantics use bounded session-authority state persistent for the VM lifetime. There are no client Lua states to checkpoint yet. |
| `sd.events.on` and built-in notifications | `web-adapted` | Fixed-tick run, wave, enemy, gold, and level events dispatch on the authority; callback failures retire only that callback. Custom broadcast/filter and three unowned built-in siblings are deferred. |
| `sd.timer` after/every/sequence/cancel/clear | `exact-ported` | Timers are quantized to the 100 Hz authority clock, sequence delays are relative, and every handle retires with the VM. |
| `sd.rng` selected/active run seed | `exact-ported` | The authority selects and immediately reads one bounded next-run seed, retains it through that run, and the scene view exposes the active web seed hex. |
| `sd.scene`, `sd.gameplay`, `sd.hub` semantic reads | `exact-ported` | Address-free projections of the existing Hub/Boneyard/run state. |
| `sd.player` list/state and current web resource mutations | `exact-ported` | The host may restore health/mana, set mana/gold, and grant XP through authoritative player components. |
| `sd.world` state/scene/actor census | `exact-ported` | Read-only semantic projections of current player and Boneyard enemy actors. |
| `sd.waves.get_state` | `exact-ported` | Reads the already implemented web wave director; custom schedule composition is separate. |
| stock `sd.enemies.get/list/spawn` subset | `web-adapted` | Eight web-owned stock descriptors use the native options shape; host-only spawn intents enter the existing enemy materializer and collision/light ownership on a fixed tick. |
| `sd.storage` | `out-of-system` | `/game` has no durable per-mod profile store yet. |
| `sd.settings` manifest settings | `out-of-system` | Library/package resolution is explicitly outside this slice; `Enable Cheats` is a browser product setting, not a mod manifest. |
| `sd.bus`, custom `sd.events.broadcast/filter` | `out-of-system` | Only the console VM is loaded; there is no multi-mod or participant-VM graph yet. |
| `sd.net` | `out-of-system` | Web Lua runs only on the authority; there are no participant-local Lua VMs. |
| `sd.time` | `out-of-system` | The rebuilt simulation has no shared time-scale/pause/frame-step owner. |
| `sd.nav` | `out-of-system` | Collision exists, but no stable cross-world semantic navigation API has been defined. |
| `sd.spells` registration and callbacks | `out-of-system` | The web has stock spells but no dynamic content registry. `spell.cast` also waits for one stable complete semantic payload. |
| `sd.items` registration/grants | `out-of-system` | The web has stock inventory/economy but no dynamic recipe catalog. |
| dynamic `sd.enemies.register` | `out-of-system` | The stock subset works; mod content identities and per-definition overrides wait for package resolution. |
| `drop.spawned` and `item.consumed` notifications | `out-of-system` | Adjacent web systems exist, but their complete stable Lua payload owners are not yet published. |
| `sd.ai` registered brains | `out-of-system` | Web enemies use fixed family brains; dynamic authority blackboards are absent. |
| `sd.draw` / `sd.hud` | `out-of-system` | Host Lua cannot paint a participant-local Pixi renderer; a bounded replicated/declarative client lane is required later. |
| `sd.audio` | `out-of-system` | Playback is browser-local Web Audio, not host-local BASS. |
| `sd.camera` | `out-of-system` | Cameras are client presentation state. |
| `sd.sprites` and world rendering | `out-of-system` | The browser asset registry does not yet ingest mod-root atlases. |
| `sd.ui` authored surfaces | `out-of-system` | The current React/Pixi UI lacks a mod-authored declarative protocol. |
| `sd.bots` | `out-of-system` | `/game` has no synthetic participant brain runtime. |
| `sd.input` | `out-of-system` | Browser input is a client intent producer and cannot be driven from host Lua. |
| low-level `sd.gameplay` test controls | `out-of-system` | Native manual-spawner/debug fields are not product APIs. |
| native `sd.player` inventory/equipment writers | `out-of-system` | Only mutations with an existing authoritative web owner are exposed. |
| native `sd.world` rewards/loot/effect internals | `out-of-system` | Dynamic web content/loot registration is absent. |
| `sd.debug` memory/call/trace/watch/backbuffer APIs | `blocked-by-platform` | The clean web rebuild has no retail address space, thiscall bridge, or D3D9 backbuffer. The browser console replaces only semantic code execution. |

## Recovered runtime and safety contract

- Lua is an author language, never a second game simulation. TypeScript remains
  authoritative and Lua queues semantic commands into existing fixed-tick
  owners.
- One Lua 5.4 VM is created lazily on the first accepted console request. A
  session that never enables/uses cheats pays no VM initialization, memory, or
  tick-dispatch cost.
- Console execution is host/solo-only at the server protocol boundary. A local
  browser setting is discoverability, not authorization; a guest-crafted packet
  must still be rejected.
- Global Hall eligibility is a separate server-owned policy. Initial and live
  cheat-mode state is carried to the host; enabling it permanently revokes the
  connection's global eligibility, and any accepted authoritative console
  request does the same even if a crafted client hid its local setting. Any
  affected party run remains eligible for local Hall history but receives no
  signed global score receipt.
- Code, request queue, prints, return values, state, callbacks, and timers are
  independently bounded. Every execution and callback is interrupted by the
  Lua instruction hook and the VM allocator has an explicit ceiling.
- `io`, `os`, `package`, `require`, `load`, `loadfile`, `dofile`, `debug`,
  `collectgarbage`, and coroutines are absent. Lua receives copied semantic
  tables and blessed functions, never Node, DOM, filesystem, network, or raw
  JavaScript objects.
- Console globals, event handlers, timers, queued commands, state, print
  capture, and the VM all retire on host teardown. Run transitions retain the
  console VM but events carry the new run identity.
- Console/timer/event commands apply at a fixed-tick boundary. Event callbacks
  generated after a simulation step may author only the following tick.

## Portable VM evidence

A disposable Node `22.17.0` prototype pinned `wasmoon 1.16.0` and its official
Lua 5.4 WASM. The standalone WASM is 266 KiB; bundling the JavaScript bridge
into an ESM Node host produced a 193 KiB bridge and ran from a different
directory when the WASM was kept beside it. The native addon count is zero.

The same prototype measured approximately 36 ms lazy initialization, 5.31 MiB
resident Lua allocation after sandbox/API bootstrap, and 0.103 ms per trivial
fresh console chunk across 1,000 executions. An infinite loop failed through
the instruction timeout, and an oversized table failed through the allocator
ceiling. Lua callbacks registered through JavaScript also inherited the
function timeout. These are WSL prototype numbers, not final Mac acceptance.

## Validation contract

- VM tests: Lua 5.4 identity, sandbox absences, persistent globals, prints,
  structured values, syntax/runtime errors, infinite-loop interruption, memory
  ceiling, callback retirement, timers, state bounds, and clean close.
- API tests: every exact-ported namespace member, authority checks, command
  validation, fixed-tick ordering, run/wave/enemy event membership, and every
  out-of-system namespace absence.
- Protocol/host/client tests: strict bounded request/results, guest rejection,
  host migration, queue bounds, disconnect cleanup, and no VM creation while
  unused.
- Browser proof: settings off exposes no console API; settings on exposes the
  documented DevTools API; host Lua reads and mutates real game state, registers
  a fixed-tick callback, prints/returns structured values, rejects runaway
  code, and disappears immediately when cheats are disabled.
- Performance: unchanged no-Lua host tick benchmark, bounded active callback
  p95/p99/max, one lazy VM initialization receipt, and no retained VM/process
  after teardown.

## Website implementation receipt

Website implementation `30be55ca77c6aff97ec44b07cffe5fc135e2ee15`
(tree `7d3c48e00ad9fd4fb186def3bba7cd3ea7bea073`) closed this first-runtime
boundary on top of the current loot, Golem, Dig-audio, and gameplay-pause
owners. The combination uses game protocol 32. The Mac canonical gate passed
24 backend contracts, 40 loot tests, 140 prerequisites, 1,002 broad
game/frontend tests, and every remaining build/UI/desktop gate.

Three Apple-M2 built-browser runs proved cold `lua: null`, the real Settings
toggle and DevTools API, Lua 5.4/sandbox identity, state/timer/events, host
resource commands, seed-42 run entry, stock enemy materialization and event,
runaway interruption, immediate cheats-off removal, and zero-player VM
teardown. Lazy initialization was `17.607..18.579 ms`; active callback p95 was
`0.527..0.806 ms`, p99 `0.860..1.760 ms`, and max `1.184..2.123 ms`, with zero
budget crossings or unexpected page/console/network errors. This does not
change the explicit package/library and participant-presentation deferrals in
the table above.

The final concurrent-main cutoff also includes the independently published
deployed-revision, Skeleton head-facing, and late-light systems. Their combined
schema with pause and Lua is protocol 33. Website cutoff
`b249af3ac293b85efbc405fd47f2a33197fa60ea` (tree
`05245cf420c521e36f72d26cd3245a457a1c19b5`) passed the Mac gate with 143
prerequisites and 1,009 broad tests, then repeated the complete built Lua
Boneyard journey with `19.063 ms` lazy init and callback p95/p99/max
`0.531/0.668/1.115 ms`. No budget crossing, unexpected error, retained player,
VM, or task process remained. The later Website receipt commit changes only
documentation.

## 2026-08-21 reopened boundary: Invincibility Potion web migration

The production Website failure exposed that the first-runtime disposition was
still authoritative after package loading had been added: the control plane
continued to accept only the web API-`0.1.0` manifest subset, while the retained
published package uses the native API-`0.2.0` contract. The Website cutover now
owns the exact Invincibility Potion call graph rather than merely accepting its
manifest.

Reusable native-source membership for that migration is:

| Member | Native owner and exact contract | Website consequence |
| --- | --- | --- |
| content identity | `lua_content_registry.cpp`; FNV-1a-64 over `sd.content.v1`, length-prefixed UTF-8 mod/key, low 62 bits plus bit 62 | Preserve the exact 63-bit value losslessly; JSON/JavaScript use its decimal text rather than an unsafe double. |
| sprites | `lua_sprite_runtime.*`; 32 per mod / 128 global, 4,096 frames per atlas, 4,096-pixel PNG dimensions, 45-byte unrotated frame prefix | Validate the immutable package sandbox and publish only bounded PNG bytes plus validated geometry to browser renderers. |
| custom potion | `lua_engine_bindings_consumables.cpp`, `lua_item_runtime.*`; subtype reservations start at 6, 256 global, duration 0..86,400,000 ms | Register during entrypoint only and carry stable content identity through loot, inventory, saves, consumption, and presentation. |
| additive loot | `lua_engine_bindings_loot.cpp`, `RollLuaLootPool`; one independent roll per entry and hostile death | Keep a mod-only deterministic RNG domain so native/stock Website loot draws are not perturbed. Demon is the only currently web-owned member of the native Demon Skull/Demon/Dire Faculty/Heartmonger boss set. |
| item consumption | `DispatchConsumableUseToLuaMods`; all mods receive `item.consumed`, then the owning `on_consume` runs only for the local owner | The single web authority dispatches once to every VM, sets the consuming participant as callback authority, then runs the owner callback once. |
| damage filter | `ApplyLuaDamageFilters`; mod order then registration order, transactional lanes, monotonic cancel, fail-open errors | The retained script's `damage.taken` maps the scalar web player-damage lane before direct and poison health mutation. `damage.dealing` is not used by this package. |
| mana filter | `ApplyLuaManaChangeFilters`; current/max/delta/result/source, bounded transactional rewrite, fail-open errors | Route gameplay debits, overload, recovery, orbs, and stock potions through the same ordered seam; owner restore and lifecycle reset stay beneath it to prevent re-entry. |
| activation flash | `Anim_SpellGlow` `0x00454AD0`, painter `0x00536380`, `BadGuys[110]`, layer 75 | One attached one-frame four-quad activation; no duration polling of a one-frame actor. |
| persistent VFX | `lua_world_renderer.cpp`; generated 128-pixel ring, radius `42 + 3*sin(elapsed/1200ms*2pi)`, opacity 0.8, authored RGBA, actor-attached Y-sort | Recreate the same procedural texture and fixed-tick duration in the Pixi world queue on every client; never replace it with a HUD badge or overlay orbit. |
| lifecycle | entrypoint lock, per-mod unload, run events, timer cancellation, registry reset | A failed entrypoint rolls back the whole party scope; expiry, run boundary, party mutation, disconnect, and host close retire owned state. |

The Website implementation remains a clean authority rebuild. Retail actor and
progression addresses stay absent, and the three native boss families not yet
implemented by the web Boneyard remain explicit `out-of-system` members. The
portable contract is otherwise the package's authored behavior, including
guest consumption, all-peer presentation, and host-enforced protection.
