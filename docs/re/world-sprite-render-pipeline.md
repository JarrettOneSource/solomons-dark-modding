# Stock world-sprite render pipeline

This note recovers the stock 2.5D world draw path that a loader-owned sprite
must join to receive the same ordering, occlusion, and lighting as actors,
props, and item drops. It deliberately separates that path from the loader's
screen-space `EndScene` overlay. The analysis was completed before the native
world-render seam was implemented.

The addresses below are image-base virtual addresses for the analyzed retail
`SolomonDark.exe`:

- image base: `0x00400000`
- file size: `4,723,200` bytes
- SHA-256:
  `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`

The stock game under `C:\SolomonDarkAbandonware` was treated as read-only.
Headless Ghidra ran against the existing read-only project replica. Raw
instruction and decompiler captures for this campaign are under
`/mnt/d/codex-evidence/zorder-20260802/re/` and
`/mnt/d/codex-evidence/zorder-20260802/re-scope-addition/`.

## Result

Stock world draw order is not a D3D depth-buffer result. `Arena_Render` gathers
three native object lists into an Arena-owned render queue, using each object's
world Y and a per-object sort bias. The queue then invokes each object's common
world render dispatcher in ascending bucket order. Larger world-Y values draw
later and therefore cover smaller-Y objects. The common dispatcher performs
visibility and local-light queries, installs the resulting tint in the native
renderer, invokes the object's virtual draw routine, and restores the tint.

Stock potion drops already travel through that complete path. Their carrier is
queued with the other world objects; its virtual renderer chooses a potion
sprite and calls the stock `Glyph_Draw`, which appends the glyph to the native
texture batch under the current world tint. In contrast, the loader's former
custom-potion path projected a quad to screen coordinates and delayed it until
the D3D9 `EndScene` hook, where Z testing, Z writing, and lighting are disabled.
That path can never reproduce native actor/prop occlusion.

Stock has a second native idiom for content that is anchored to a world
position but semantically labels the scene. The tutorial loot arrow is not an
Arena render-queue object. Its `Tutorial` UI node projects a live world target
and draws the arrow from the native UI tree after the Arena scene has
completed. It is consequently post-scene, always above scene actors and props,
and is not multiplied by the target tile's local-light tint. Floating actor
names, actor health bars, and world-target markers belong in that native
world-indicator lane, matching the stock arrow rather than inventing a Y-sort
rule for labels.

The recovered native seams are:

1. At the intercepted stock potion `Glyph_Draw` call, substitute a native
   glyph backed by the mod atlas. This retains the stock drop carrier's exact
   queue position, visibility, and lighting.
2. For a general mod world sprite, insert a loader-owned render carrier through
   the stock queue insertion function before that queue is flushed. Give the
   carrier the requested world position and sort bias and let the stock common
   dispatcher call its virtual native-glyph renderer.
3. Keep stock animation actors, including `Anim_SpellGlow`, on their existing
   native animation lane. Do not mirror a world-anchored burst in `EndScene`.
4. For world-anchored indicators, draw with stock native UI primitives
   immediately after `Arena_Render` returns. This matches the tutorial arrow's
   post-scene ordering while keeping the later D3D9 overlay screen-only.

## Evidence map

| Recovered subject | Primary evidence |
| --- | --- |
| The three Arena object lists and their calls to queue insertion | `ghidra-arena-render-queue-calls.txt:69-95`, `:123-150`, `:177-205` |
| Queue insertion formula and normal/overflow selection | `ghidra-native-render-queue-assembly.txt:44-119` |
| Overflow insertion sorted by raw object Y | `ghidra-native-render-queue-assembly.txt:196-275` |
| Queue flush order | `ghidra-native-render-queue.txt:127-157` |
| Per-object virtual dispatch through vtable slot `+0x0C` | `ghidra-native-render-queue-assembly.txt:121-194` |
| Common world visibility, lighting, tint, and virtual draw | `ghidra-world-render-core.txt:1281-1439` |
| Base/PlayerWizard zero sort bias and Sack's `-25.0` override | `re-scope-addition/stock-puppet-player-sort-bias.txt:48-151`, `re-scope-addition/stock-sack-sort-bias.txt:47-76` |
| Stock potion/item carrier renderers | `ghidra-world-render-core.txt:1522-1563`, `:1611-1644` |
| Native `Glyph_Draw` | `ghidra-world-render-core.txt:1651-1670` |
| Native glyph batching and current packed tint | `ghidra-native-texture-batch.txt:196-265` |
| Native 32-bit texture-slot upload | `ghidra-native-texture-slots.txt:51-155` |
| Base world-render carrier constructor | `ghidra-native-render-carrier.txt:53-153` |
| Base carrier vtable and common dispatcher entries | `ghidra-puppet-vtable.txt:60-85` |
| Tutorial UI-node construction, vtable install, and native-tree attachment | `re-scope-addition/hud-arena-tutorial-decompile.txt:747-794` |
| Native UI-tree render, derived render call, then child traversal | `re-scope-addition/hud-arena-tutorial-decompile.txt:675-741` |
| Tutorial vtable: derived render and inherited tree-render slots | `re-scope-addition/tutorial-render-vtable.txt:57-72` |
| Tutorial stages 8 and 17 project a world target then draw the loot arrow | `re-scope-addition/hud-arena-tutorial-decompile.txt:1128-1185`, `:1614-1672` |
| Stock HUD health-bar path selects color and submits a native untextured quad | `re-scope-addition/stock-healthbar-render-decompile.txt:192-220` |
| Native untextured-quad geometry and current packed-color consumption | `re-scope-addition/stock-ui-primitives-decompile.txt:53-105` |

Line references in this table are to the immutable campaign captures in the
evidence directory above. The conclusions below distinguish instructions that
prove behavior from interface choices that the loader still has to validate at
runtime.

## Arena draw-pass structure

`Arena_Render` at `0x0046EC80` gathers these stock lists into the render queue
whose object begins at `Arena + 0x17C`:

| Arena fields | Recovered list |
| --- | --- |
| count `+0x318`, pointers `+0x324` | Main PuppetManager actors. |
| count `+0x87CC`, pointers `+0x87D8` | Arena scenery/prop actors. |
| count `+0x8B78`, pointers `+0x8B84` | Transient world actors. |

For each pointer the Arena loads `floor(local_player.world_y)`, passes render
pass `0`, and calls queue insertion at `0x0068C3B0`. The three call sites are
`0x0046EEB4`, `0x0046EF14`, and `0x0046EF7E`; the surrounding list loads and
loop bounds are captured in
`ghidra-arena-render-queue-calls.txt:69-95`, `:123-150`, and `:177-205`.
The Arena later flushes the populated queue at `0x0068C480`
(`ghidra-arena-render-queue-calls.txt:242-252`).

The gather order matters only as a tie breaker inside a normal bucket. The
three families otherwise share the same insertion formula and the same flush.
There is no separate "drop overlay" pass.

## Proven Z/order rule

The queue insertion routine at `0x0068C3B0` first skips an object whose
pending-removal byte at `+0x05` is nonzero. It then reads:

- object sort bias: `float` at `+0xA0`;
- object world Y: `float` at `+0x1C`;
- reference Y: the caller-provided `floor(local_player.world_y)`; and
- queue origin: the first integer in the render-queue object.

The instructions at `0x0068C3C2..0x0068C3E9` prove the bucket calculation:

```text
relative = floor(object.world_y) + floor(object.sort_bias)
           - floor(local_player.world_y)
bucket   = queue.origin + trunc_toward_zero(relative / 2)
```

The x87-to-integer helper calls, add/subtract, signed correction, arithmetic
shift, and queue-origin add are preserved in
`ghidra-native-render-queue-assembly.txt:52-65`. An in-range bucket is appended
through `0x0068C090` (`:98-114`). Underflow and overflow go through
`0x0068C0F0` (`:67-97`). That overflow helper compares the raw floats at object
`+0x1C` and insertion-sorts ascending by world Y
(`ghidra-native-render-queue-assembly.txt:207-275`).

`0x0068C480` flushes the leading overflow list, then every normal bucket from
index zero upward, then the trailing overflow list
(`ghidra-native-render-queue.txt:127-157`). Each list entry is rendered by
loading its vtable and calling slot `+0x0C`
(`ghidra-native-render-queue-assembly.txt:146-150`). Therefore:

- smaller world Y / sort bias renders earlier and appears behind;
- larger world Y / sort bias renders later and appears in front;
- objects in the same two-world-unit bucket retain insertion order; and
- sort bias is the stock way to shift an object's ordering without moving its
  visual anchor.

This is direct code proof of Y-derived 2.5D ordering, not a naming inference.
The comparison is between effective keys, not raw Y alone. The base Puppet
constructor writes `0.0` to `+0xA0`, which a live `PlayerWizard` retains, while
the `Sack` constructor overrides `+0xA0` with the stock constant `-25.0`
(`stock-puppet-player-sort-bias.txt:48-151` and
`stock-sack-sort-bias.txt:47-76`). A stock potion at `drop_y` therefore sorts
as `drop_y - 25`; an ordinary live actor is behind it only when the actor's
effective Y is smaller than that value. Acceptance positions must account for
this stock class bias rather than assuming equal raw Y means equal depth.

## Where stock item drops enter

The stock dropped-item carrier uses the same Puppet-derived queue path as the
other world objects. `Sack` construction at `0x005E1460` calls the base Puppet
constructor and then writes the `-25.0` stock constant to its `+0xA0` sort-bias
field (`stock-sack-sort-bias.txt:47-76`). Its renderer at `0x006105F0`
examines the native item at carrier `+0x148`, recognizes potion type `0x1B59`,
reads the potion subtype at
item `+0x1C`, and indexes the world-potion sprite array with a `0xC4`-byte
stride. It then calls `Glyph_Draw` at `0x004143D0` using the carrier world
position (`ghidra-world-render-core.txt:1522-1563`). The alternate stock item
renderer at `0x006104F0` follows the same glyph boundary with its own sprite
array (`ghidra-world-render-core.txt:1611-1644`).

`Glyph_Draw` checks sprite validity at `+0x04`, adds its world position to the
native render translation, binds the sprite texture handle at `+0x08`, and
passes geometry at `+0x2C` plus UVs at `+0x4C` to `TextQuad_Draw`
(`ghidra-world-render-core.txt:1651-1670`). `TextQuad_Draw` reads the renderer's
current packed color at its `+0x21C` and appends four vertices to the current
native batch (`ghidra-native-texture-batch.txt:200-265`). A stock drop thus
inherits both its carrier's queue slot and the common renderer's current tint.

The sprite object is `0xC4` bytes. Its native texture handle is not an
`IDirect3DTexture9*`; it indexes the stock texture-slot table. The stock upload
function at `0x00440F70` allocates a slot, locks it, and for mode `0` copies
`width * height * 4` bytes before recording its dimensions
(`ghidra-native-texture-slots.txt:51-155`). This is the appropriate upload path
for the loader's already-decoded 32-bit BGRA mod atlas.

## Lighting and tint

Queue flush invokes the common Puppet world-render dispatcher at `0x00624B40`
through vtable slot `+0x0C`. That dispatcher:

1. computes the screen bounds from world position `+0x18/+0x1C` and the bounds
   object referenced at `+0xC8`;
2. culls invisible objects;
3. obtains the local lighting scalar through `0x0057F980`, `0x0057F0E0`, or
   the transformed-light query `0x0057E490`;
4. stores the scalar at object `+0xCC` and multiplies it with the object's tint;
5. installs the resulting color in the native renderer;
6. calls virtual draw slot `+0x1C` or `+0x20`; and
7. restores the previous native color.

The control flow and light-query branches are captured in
`ghidra-world-render-core.txt:1281-1413`; tint multiplication, install, virtual
draw, and restore are at `:1415-1439`. Because `Glyph_Draw` reads the same
native color during that virtual call, a mod glyph drawn there receives the
same local light treatment as a stock drop.

This also establishes the boundary with the remote-participant light repair.
That bridge changes the peer-local light inputs consumed by the common
dispatcher; it must remain upstream of this seam. The previously recovered
last-writer sites for object `+0xCC` are documented in
[`native-default-boneyard-load-seed-and-decor.md`](../reverse-engineering/native-default-boneyard-load-seed-and-decor.md#scenery-objects-and-derived-props).
The world-render seam must neither replace the common dispatcher nor force a
constant tint, because either change would bypass that bridge.

## Stock world-anchored indicator pass

The tutorial loot-drop arrow documented in
[`tutorial-mechanics.md`](tutorial-mechanics.md) is the stock discriminator
between a scene sprite and a world-anchored indicator. `Tutorial` construction
at `0x005D5CF0` first calls the base UI-node constructor `0x00427370`, installs
the vtable at `0x0079AFC4`, and attaches the new node through `0x004280E0`
(`re-scope-addition/hud-arena-tutorial-decompile.txt:747-794`). The vtable's
derived render slot `+0x0C` is `0x005D08C0`; its inherited tree-render slot
`+0x24` is `0x004278C0`
(`re-scope-addition/tutorial-render-vtable.txt:57-72`).

The inherited tree renderer calls the node's derived render slot and then
walks its child list (`re-scope-addition/hud-arena-tutorial-decompile.txt:
695-739`). Inside the derived Tutorial render, stages 8 and 17 resolve a live
world actor, subtract the camera origin, apply the camera scale, add the render
translation, and finally call the arrow renderer at `0x005C9BB0`
(`re-scope-addition/hud-arena-tutorial-decompile.txt:1128-1185`,
`:1614-1672`). There is no call to Arena queue insertion `0x0068C3B0`, no
Puppet common dispatcher, and no local-light query in either arrow branch.

This proves that the stock arrow is a dedicated post-scene,
world-projected native indicator rather than a Y-sorted scene object. The
loader's actor-attached labels must follow that behavior exactly: project and
draw after the Arena scene, remain above scene geometry regardless of target
Y, and do not inherit tile lighting. The selected loader seam is the return
edge of `Arena_Render` at `0x0046EC80`: call the complete original first, then
submit loader indicators through native text and untextured-quad primitives.
That point is later than all Arena queue flushes but remains in the game's
native render phase, before the D3D9 `EndScene` overlay.

The projection input must be the Region camera rectangle, not an arbitrary
D3D transform left behind by an actor draw. Stock subtracts the camera origin
from the live world point, multiplies both axes by the camera scale, and adds
the native render translation before clipping
(`re-scope-addition/hud-arena-tutorial-decompile.txt:1128-1185`). The loader's
semantic camera snapshot exposes the already translated visible-rectangle
origin and scale, so its indicator coordinate is
`(world - view_origin) * view_scale`. The native indicator lane deliberately
does not call the overlay compatibility helper `sd.draw.world_to_screen`.

Stock already supplies the health-bar primitive needed by this lane. The HUD
health-bar loop at `0x005D2520` sets the renderer color through `0x0041FE50`
and calls native untextured-quad submission `0x0041DD70`
(`re-scope-addition/stock-healthbar-render-decompile.txt:192-220`). The quad
function appends four vertices using the renderer's current packed color at
`+0x21C` (`re-scope-addition/stock-ui-primitives-decompile.txt:53-105`). Its
`this` is not the object stored directly in `0x00B401A8`: every stock call
loads that singleton and adds `0x1D0` before setting color or submitting the
quad (`re-scope-addition/stock-healthbar-draw-state-instructions.txt:996-1059`).
That embedded draw-state owns the native vertex batch and flush callback. A
loader health bar can therefore stay wholly inside the native batch without
capturing ExactText quads or replaying D3D primitives during `EndScene`, but
only when it addresses the same `singleton + 0x1D0` object as stock.

## Complete loader world-anchor inventory

The cutover inventory was taken across loader render entry points and all
in-repository Lua mods. It is class-complete for the current tree:

| Current content | Pre-cutover path | Stock-matched destination |
| --- | --- | --- |
| Registered custom-potion ground glyph | Stock carrier draw was replaced by a projected `EndScene` quad | Keep the stock drop carrier and replace only its native glyph in place. |
| Invincibility Potion active orbit/burst | World projection followed by consumable `EndScene` quads, alongside native `Anim_SpellGlow` | Delete the duplicate overlay quads; retain only native `Anim_SpellGlow`. |
| General `sd.world.sprite` content | No native public seam | Loader Puppet carrier in the Arena Y-sorted queue. |
| Replicated Dampen ring | Projected D3D9 `EndScene` line strip | Native textured world carrier in the Arena Y-sorted queue. |
| Remote-player floating name and health bar | Name rendered during actor animation advance, captured/reprojected, then name and bar replayed in `EndScene` | Native post-scene world-indicator lane using ExactText and stock untextured quads. |
| `lua_hud_showcase` actor marker and `YOU` label | `sd.draw.world_to_screen`, then overlay lines/text | Native post-scene world-indicator command anchored by world coordinates. |

No other loader or in-repository mod draw consumes a world position for
visual submission. Top-left ally rows, level-up status, `BOT PLAYING`,
Boneyard controls, loading/join surfaces, and ordinary `sd.draw`/`sd.hud`
commands are screen-owned and remain in the existing overlay. The
`sd.draw.world_to_screen` projection helper remains a compatibility API for
screen UI that deliberately tracks a world target, but using it does not
authorize a world-owned visual to enter `EndScene`.

## Why the current overlay path is not salvageable

The loader's `lua_sprite_runtime` and `lua_draw_*` path owns screen-space
sprites. A world coordinate may be projected before it is queued, but the
actual draw occurs from the D3D9 `EndScene` hook. That renderer explicitly
sets `D3DRS_ZENABLE = FALSE`, `D3DRS_ZWRITEENABLE = FALSE`, and
`D3DRS_LIGHTING = FALSE`. It therefore has neither the native Y queue nor the
native world tint when a projected quad is finally submitted.

Changing only the projected screen Y, or sorting mod quads among themselves,
cannot make an actor or prop interleave with them. Enabling the hardware Z
buffer also cannot reproduce a painter's-order queue whose sprites are
submitted as a native 2D batch. The world-space call must move to the native
queue; the overlay remains correct only for intentional screen UI.

## Candidate seams and selection

### Direct native draw from `EndScene`: rejected

Calling `DrawPrimitiveUP` or even `Glyph_Draw` during `EndScene` still occurs
after the world queue is complete. It would preserve neither inter-object
ordering nor the active common-dispatcher tint.

### Replace the custom potion glyph in place: selected

The loader already intercepts `Glyph_Draw` only when the current native
Inventory/World sprite-array entry corresponds to a registered custom potion
subtype. At that exact call, the stock drop carrier has already been sorted and
the common dispatcher has already installed its light-derived tint. Replacing
only the glyph record and texture handle at that boundary gives the mod potion
the stock carrier's semantics without adding a second actor or guessing its
sort bias.

### Loader-owned Puppet render carrier: selected for general world sprites

The base Puppet constructor at `0x006287D0` initializes the object state needed
by the common dispatcher, including position, world pointer, default sort bias,
bounds pointer, and render flags
(`ghidra-native-render-carrier.txt:53-153`). Its vtable at `0x0079E6C4` maps
slot `+0x0C` to the common dispatcher and exposes the final glyph-render slots
at `+0x1C/+0x20` (`ghidra-puppet-vtable.txt:60-85`).

A loader-owned carrier can therefore retain the stock common-dispatch entry
while overriding only its final virtual draw slot. Immediately before
`0x0068C480` flushes pass zero, the loader can update the carrier's world
position and sort bias and call stock insertion `0x0068C3B0`. The original
flush then interleaves it with every already-gathered actor/prop/drop. This seam
reuses the proven formula and lighting path rather than copying either one.

The queue's normal buckets preserve insertion order. Since loader carriers are
added after Arena's three stock lists, a carrier tied exactly with a stock
object occupies the late position within that two-unit bucket. That is a
verified consequence, not an exact-float total-order guarantee. Mods can use
the stock sort-bias field when a deliberate within-scene adjustment is needed.

### Stock animation carrier: retained for world VFX

The potion activation already creates native `Anim_SpellGlow` actors. Those
actors enter the native animation/world path and therefore already have stock
ordering and lighting semantics. The correct cutover is to retain that lane
and remove the extra orbiting icon quads formerly emitted through `EndScene`.
No overlay fallback is allowed for world-anchored VFX.

## World-versus-overlay boundary

| Content | Required render path | Reason |
| --- | --- | --- |
| Item drops, including registered custom potions | Native carrier and native glyph batch | Must interleave with actors and props and inherit local light. |
| World-anchored mod sprites | Loader carrier inserted into the native world queue | Needs stock Y/bias order, culling, and tint. |
| World-anchored VFX | Native animation actor or native world carrier | Must be occluded and lit in the scene. |
| Actor-attached names and health bars | Native post-scene world-indicator pass | Matches the stock tutorial arrow: world projected, above the scene, not tile-lit. |
| World-target marker labels | Native post-scene world-indicator pass | Same stock indicator semantics as the tutorial arrow. |
| Top-left ally rows and other screen HUD | Existing `EndScene` overlay or existing stock HUD | Position and ownership are screen-space. |
| Boneyard picker | Existing `EndScene` overlay | Intentional screen UI. |
| `BOT PLAYING` label | Existing `EndScene` overlay | Intentional screen UI. |
| Loading screens | Existing `EndScene` overlay | Intentional screen UI. |

Projection does not change ownership. A screen widget may deliberately follow
a projected point and remain overlay-owned. A world sprite or actor-attached
indicator must use its corresponding native lane even though both may start
from the same coordinates. A static contract must pin this distinction so new
item drops, world VFX, actor labels, or anchored markers cannot silently
reintroduce a projected EndScene draw.

## Verified facts and remaining runtime proof

Verified directly from stock instructions/decompilation:

- the three object-list gather sites, shared queue, pass number, and flush;
- the exact world-Y/sort-bias bucket calculation;
- leading/bucket/trailing flush order and overflow Y sort;
- stock potion subtype-to-sprite lookup and native glyph call;
- common visibility, lighting, tint, and virtual-render control flow;
- native texture upload and glyph batching boundaries;
- the base Puppet carrier constructor/vtable shape used by the proposed seam;
- the tutorial arrow's post-scene native UI-tree ownership and explicit world
  projection; and
- the stock native untextured-quad primitive used for HUD health bars.

The following are implementation hypotheses until live acceptance:

- that a loader-owned base carrier with only the final draw virtual replaced
  has no unobserved per-frame prerequisite;
- that inserting it immediately before the pass-zero flush is stable across
  all accepted scenes; and
- that the mod atlas's decoded BGRA orientation and alpha exactly match the
  native slot uploader's expectations.

Acceptance must therefore show a stock potion and custom potion together, with
an actor in front of both and behind both, under non-flat lighting, on both
local multiplayer peers. It must also show an actor-attached floating bar and
label on both peers in the same native post-scene relationship as the stock
tutorial indicator. Passing static or headless checks alone cannot close those
hypotheses.
