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

## Required closure

Render the picker at the loader's established final D3D9 presentation
boundary, after the stock scene/HUD has been assembled, while preserving the
native ExactText and native untextured-quad primitives. Gate the presentation
by picker state rather than consuming a game-thread tick in an arbitrary HUD
sub-dispatch. Add a contract that pins the final-pass call site and bans the
picker from the gameplay HUD sub-dispatch. Then repeat the staged alpha/beta
selection over WAN and retain an actual visible-window capture.
