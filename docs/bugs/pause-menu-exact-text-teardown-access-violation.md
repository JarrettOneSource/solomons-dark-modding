# Pause-menu exact-text teardown access violation

## Status

Fixed on the unpublished `v0.1.0-beta.18` release candidate. The release gate
continues to use the stock pause-menu `LEAVE GAME` path.

## Reproduction

The beta.18 release gate launched an isolated two-peer loopback session, entered
a shared Boneyard, completed wave 1, opened the host pause menu, and dispatched
the stock `LEAVE GAME` action through `pause_menu.leave_game`.

The action was accepted at `2026-07-26 15:42:37.507`. The host then logged a
first-chance `0xC0000005` at `15:42:37.955`; its Lua state disappeared while
the client remained in `testrun`.

Evidence is under:

```text
/mnt/d/codex-evidence/beta18-publish-20260726/live/
```

The corrected gate result is `stability-gate-corrected.json`. The host log is
under
`runtime-corrected/instances/b18-r01-host/stage/.sdmod/logs/`.

## Failing stack

Release-PDB symbolication resolved the loader frames as:

1. `TryReadUiWidgetParentAtOffset`
2. `IsWidgetOwnedByRootAtOffset`
3. `IsWidgetOwnedByRoot`
4. `BeginExactTextRenderCapture`
5. `HookDarkCloudBrowserExactTextRender`

The faulting read was a four-byte parent field at the configured widget-parent
offset. `ProcessMemory::TryRead` caught the exception, so the process did not
produce a nonempty crash log, but the read still raised a real first-chance
access violation and fails the release requirement of zero access violations.

## Lifecycle model

The overlay has two different kinds of UI state:

- Active surface scopes, such as `SimpleMenu`, settings, and browser render
  hooks. Their `active_object_ptr` is usable only while the owning native hook
  has nonzero render or modal depth.
- Durable observations, such as `TrackedDialogState`. These cache an object
  pointer, geometry, labels, and a capture timestamp so a later frame can build
  a semantic snapshot.

Only the first kind proves native object lifetime.

`HookSimpleMenuModalLoop` correctly clears its active pointer when the native
modal call returns. During Leave Game, the SimpleMenu scope ended before a
later exact-text render call. That call did not match an active surface, then
fell through to the dialog fallback in `BeginExactTextRenderCapture`.

The dialog fallback calls `GetTrackedDialogObject()`, which returns the durable
dialog pointer without proving that a dialog render/build scope is active. It
then tries to associate arbitrary current draw-call candidates with that
historical root by walking parent pointers. A cached dialog observation can
therefore authorize new native reads after the dialog object and unrelated
widgets have entered teardown.

The same ownership mistake exists anywhere an exact-text capture uses a
recently tracked root instead of an active owner scope. A short timeout, null
check, vtable check, or caught access violation does not establish lifetime:
freed UI storage can remain committed and retain plausible values until a
later parent read crosses into invalid memory.

## Root cause

Exact-text ownership discovery conflates observation lifetime with native
widget lifetime. Historical surface snapshots are valid data, but they are not
leases on the native object graph. `BeginExactTextRenderCapture` is allowed to
walk widget parents after the owning surface scope has ended, so pause-menu
teardown can turn a diagnostic ownership probe into an invalid native read.

## Required fix boundary

The fix must enforce the lifetime rule at the capture/geometry seam:

- parent-tree traversal is permitted only under a currently active native
  surface scope;
- durable observations may supply cached semantic data, but must not authorize
  later widget-tree reads;
- tracked-dialog snapshot construction must not reread geometry through a
  historical native root;
- transition cleanup must invalidate observations and captures without
  depending on one failing pointer being null.

The regression contract should reject historical-root parent walks in exact
text capture. The original two-peer Leave Game path remains the live acceptance
test because it exercises the stock teardown ordering that exposed the defect.

## Follow-up evidence

The first lifecycle correction removed the historical-dialog fallback, but a
focused Leave Game reproduction exposed the same ownership error in the generic
text-draw observer. Release-PDB symbolication resolved the later first-chance
access violation as:

1. `TryResolveObjectLabel`
2. `ObserveUiDrawCall`
3. `HookTextDrawHelper`

That observer treated the caller's `ESI` value as a possible widget and scanned
the pointed-to object for strings. `ESI` was only a heuristic identity source,
not a lifetime-checked widget lease. During teardown it referenced retired
storage, so the generic label probe raised another `0xC0000005`.

The same focused run also showed why the client initially stayed in `testrun`
after the host left. The host's reliable run-exit nonce was correctly latched,
then `RefreshLocalParticipantFromGameState` immediately cleared it because an
invalid transition scene collapses to the default `SharedHub` intent. No
authenticated non-run packet with the old run nonce reached the client.

## Resolution

The fix closes the native-lifetime class at the capture seam:

- exact-text ownership and geometry readers use only native render or modal
  scopes whose depth is currently nonzero;
- durable dialog snapshots contain copied values only;
- dialog geometry is copied at the live primary layout/render routine
  `0x005AB2C0`;
- every semantic action retires native-backed capture state before invoking the
  stock handler that may begin teardown;
- the generic text observer uses labels already captured by live control hooks
  and no longer scans a heuristic caller pointer;
- the host run-exit latch is cleared only after a confirmed native hub scene,
  not during an invalid or transitional scene.

Static regression contracts pin both the capture-lifetime boundary and the
confirmed-hub run-exit rule. The focused two-peer reproduction at
`runtime-fix-repro-primary-render-v8` completed the real pause-menu Leave Game
path for both peers with zero access violations, zero crash artifacts, and two
clean process exits.
