# beta.31 Boneyard picker native pass is invisible

## Scope

WANVERIFY reproduced this on the exact beta.31 Release payload at
`8c1af63ac1d6997ff37d061f8ef4ba2bb387f7dc`, with the Home Windows peer as
the UDP authority and the NFO Linux/Proton peer connected over the public
Internet. Both `acceptance.mpk.boneyard.alpha` and
`acceptance.mpk.boneyard.beta` were staged.

## Reproduction

1. Launch both peers into the hub and let the transport reach one connected
   remote participant.
2. Ask the Home authority to start the match.
3. Observe that the picker state reports `open=true`, `phase=choosing` and the
   loader log reports `Boneyard picker opened. entries=2`.
4. Capture both the loader D3D9 backbuffer and the actual visible Windows
   window.

The hub remains fully visible with no picker backdrop, list, details, or input
hint. This is not a backbuffer-capture ordering artifact: the real window
capture is also blank. Evidence is under
`wan/beta31/postfix/alpha/run1/picker/`, notably
`home-picker-state.txt`, `alpha-picker-open-home.png`, and
`alpha-picker-open-home-screen.png`.

## Root cause

The v3 cutover moved the picker from the final Lua overlay pass to
`HookGameplayHudRenderDispatch`, which is a sub-dispatch invoked multiple
times while the stock frame is assembled. `PumpBoneyardPickerOnGameThread`
sets one `render_frame_pending` bit, and the first HUD sub-dispatch consumes it
with `exchange(false)` and draws the entire picker. Later stock dispatches in
the same frame then paint over that early draw. The bit prevents the picker
from drawing on the terminal sub-dispatch, so the composed frame presented to
the player contains no picker.

The static contract only proves that the hook calls the renderer and that an
atomic gate exists. It does not prove that the call occurs at a presentation
boundary or survives the rest of the stock frame.

## Final-D3D9 follow-up

`5cad9b0944a2306490ac51b81d6ccca205d88188` moved the native draws to the
loader's `EndScene` callback. That proved the original overwrite diagnosis but
exposed a second boundary violation:

- the loader backbuffer capture contains the complete picker;
- the simultaneously visible Windows game surface is black with an unpainted
  white rectangle; and
- canceling the picker immediately restores the stock map surface.

The paired evidence is
`wan/beta31/postfix/alpha/run2/picker/alpha2-picker-open-home.png` and
`alpha2-picker-open-home-screen.png`. The payload SHA, picker state, loader
logs, and clean peer teardown are retained beside those images.

Stock ExactText and the stock untextured-quad helper are engine renderer
operations, not self-contained D3D9 overlay primitives. Calling them after
the stock renderer has finished its HUD pass can alter the captured backbuffer
but does not preserve the engine's presentation/batch boundary. A D3D9 state
block cannot make an out-of-lifetime native renderer call valid. Consequently,
a correct loader backbuffer was not evidence that the swap-chain surface shown
to the player was valid.

The recovered whole-HUD function at `0x005D2520` is the appropriate native
boundary. Unlike `0x00512060`, it owns the complete stock HUD render and
returns only after the subordinate world/HUD dispatches have finished. A
local-only Release diagnostic detour drew after its trampoline. The actual
Windows window then showed the full stock-font picker with no white/black
presentation corruption. That probe and its visible-window capture are under
`diagnostics/picker-full-hud-hook-probe/`; the probe was removed before this
document was committed.

## Required closure

Add `0x005D2520` as a named, layout-validated whole-HUD render seam. Render
the picker once after that function's trampoline, while preserving the native
ExactText and native untextured-quad primitives. Remove the picker from
`EndScene` and from the intermediate `0x00512060` sub-dispatch. Contracts must
pin the new address, signature, hook lifecycle, and ordering. Then repeat the
staged alpha/beta selection over WAN and retain both actual-window and loader
backbuffer captures.
