# Lua consumable world sprite never renders

## Investigation

Downloaded Invincibility Potion 0.2.0 was loaded through the released
beta.29 launcher and spawned as a native potion drop. The native actor was
present at the requested world coordinates with item type `7001` and custom
subtype `6`, while D3D9 backbuffer captures contained none of the green pixels
from the registered custom atlas. Moving a second drop away from the player
ruled out occlusion.

The live world sprite bundle contained seven records after the first custom
drop was rendered. Records `0` through `5` were active, but the newly grown
custom subtype record at index `6` had its native active byte clear.

Headless decompilation then found the load-bearing mismatch. Item-drop render
function `0x006105F0` grows the world sprite array and calls the positioned
glyph renderer at `0x004143D0`. Its active check is inside that renderer. The
loader instead hooked `0x00414EA0`, a different position-only helper with no
sprite receiver, using a `thiscall` signature that did not match that function.
The real item draw therefore never entered `HookSpriteDrawAtPosition`.

As a diagnostic only, setting the custom record active proved a second fault:
the hook copied the stock potion's active byte and geometry into an otherwise
uninitialized native sprite record and then passed that record to the stock
renderer. The stock renderer terminated through the Microsoft Visual C++
runtime before a custom quad could be captured.

Evidence is under
`/mnt/d/codex-evidence/modpipe-20260801/phase-c/solo-20260801-1756/`:

- `screenshots/diagnostic-custom-sprite-offset-converted.png` shows the
  unobstructed drop position without the green sprite.
- `screenshots/diagnostic-active-window.png` shows the runtime termination
  after activating the incomplete native record.
- `runtime-artifacts/host/stage-.sdmod/logs/solomondarkmodloader.log` records
  the native actor/subtype and the diagnostic memory reads.
- `runtime-artifacts/host/stage-.sdmod/logs/solomondarkmodloader.crash.log`
  records the renderer failure.

## Root cause

The Lua consumable presentation seam hooked the wrong native function and used
the wrong call shape. The actual world-item draw reaches `0x004143D0` with a
sprite receiver plus world `x` and `y`; `0x00414EA0` takes only position and a
render value. Custom subtype records are also inactive and do not contain a
complete stock `Sprite` object.

The loader must hook the real positioned glyph renderer. Once the receiver is
identified as a registered custom subtype, it can derive the screen quad from
the stock health-potion geometry and the framework camera snapshot, queue the
registered mod atlas, and suppress the incomplete native record. No native
active-byte mutation or client-authored synchronization is required.
