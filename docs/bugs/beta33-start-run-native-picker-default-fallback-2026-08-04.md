# beta.33 start-run native-picker fallback

## Scope and baseline

This investigation started from `c1724f51553bf45d58f40cc17c9600e71f902af4`
(`v0.1.0-beta.33`) before any production change. The owner observed that the
Courtyard start-run control still opened the retail `MapPicker`. The required
product behavior now supersedes the zero-custom-catalog stock trampoline kept
by the original Boneyard picker design and by the beta.32 interaction-gate
fix.

The correction is limited to the host/solo start-run decision, the loader
picker catalog, and selection dispatch. The beta.32 connected-client render
and activation suppression remains mandatory and independent of catalog
contents.

## Read-only stock analysis

The existing replicated Ghidra project was queried headlessly with analysis
disabled. The canonical project and retail executable were not modified.
The analyzed `SolomonDark.exe` has:

- image base `0x00400000`;
- file size `4,723,200` bytes; and
- SHA-256
  `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.

Fresh string/xref, decompiler, and instruction passes covered
`0x0058E8C0`, `0x005BB970`, `0x005CFA80`, `0x005CDDD0`, `0x0046EA90`,
`0x0046DC60`, `0x0050E5E0`, and `0x0050E320`.

### Verified Default identity

The stock generated/default run is not `story0.boneyard` and is not one of
the retail `MapPicker`'s story entries. Main-menu selection dispatch
`0x0058E8C0` case 3 performs both parts of the identity:

1. instruction `0x0058E8F6` writes `1` to `DAT_00B3BEDC`, the pending
   generated-Boneyard selector; and
2. the String literal referenced at `0x0058E97B` is
   `data\levels\survival.boneyard`, which is passed into the Gameplay loader
   at `0x005BB970`.

`survival.boneyard` is the selected Gameplay template. The generated working
Arena has a separate identity: `Arena_Create` at `0x0046EA90` selects
`play.boneyard` at `0x0046EAF4` for an ordinary run, or
`testrun.boneyard` at `0x0046EAED` only when Gameplay test-run mode is set,
then calls the structured loader at `0x0046DC60`.

The existing loader-owned default-run queue already preserves this stock
contract. `TryDispatchHubStartMatchOnGameThread()` writes pending level kind
`1` before the authorized `Gameplay_SwitchRegion` path. It must therefore be
the Default entry's dispatch seam; a stock `MapPicker` choice or fabricated
story index would be the wrong identity.

## Reproduction and root cause

The start affordance has one activation path:

```text
Courtyard control dispatcher 0x00514A20
  call at 0x00514AB9
    stock MapPicker start/toggle 0x0050E5E0
      loader HookMapPickerStart
```

The beta.32 gate correctly returns before the trampoline for a connected
client. For an authority, however, the current hook does this:

```cpp
if (!ShouldHijackHostBoneyardStart()) {
    original(courtyard);
    return;
}
```

`ShouldHijackHostBoneyardStart()` is true only when the staged custom catalog
has at least one entry. An empty catalog therefore invokes `0x0050E5E0` and
opens the retail story-map surface. This is not a missed hook or a second
native caller; it is the intentional old fallback.

The old fallback also survives in two adjacent paths:

- `QueueHubStartMatch()` chooses the loader picker only for a nonempty custom
  catalog, otherwise it uses the generated-run queue; unlike the native hook,
  this direct queue is already the desired empty-catalog behavior.
- canceling the loader picker clears its selection and invokes the stock
  start trampoline, deliberately opening the retail picker.

The owner mandate supersedes both uses of the interactive stock surface.

## Superseding design

### Catalog shape

`BoneyardPickerEntry` gains an explicit Default-versus-custom kind. The
immutable catalog always places exactly one built-in entry at index zero:

```text
Default                         built-in stock generated run
Alpha Arena                    custom mod entry
...
```

Default is a control-plane choice, not staged content. It has no fabricated
mod ID, file path, digest, preview values, or network content identity.
Custom descriptors retain all existing validation, digest, staging, and
replication rules. UI counts and source attribution exclude the built-in
entry.

The presence of the built-in catalog row does not decide whether a picker is
shown. A separate custom-entry count owns that decision:

- zero custom entries: do not install the full-HUD picker renderer and never
  open the loader picker;
- one or more custom entries: install the renderer and open the loader picker
  with Default pinned at index zero.

### Start activation

The hooked native activation is only an input seam; it is no longer a host or
solo fallback:

```text
connected client                         -> suppress
host or solo, zero custom entries         -> queue Default generated run
host or solo, one or more custom entries  -> open loader picker
```

The zero-custom branch calls the same loader-owned generated-run queue used by
`sd.hub.start_match`. It does not call the stock `MapPicker` trampoline and
does not construct either picker. Queue validation and the existing
game-thread dispatch remain authoritative for the run seed, pending level
kind, region switch, and client follow path.

The dedicated affordance-render hook remains unchanged: connected clients
return before the stock renderer, while host and solo call its trampoline.
Both authority hooks remain installed for every catalog size.

### Picker events

Selecting Default closes the loader picker, clears any custom digest/revision
state, and queues the same Default generated run. It does not pass through the
stock `MapPicker` start/toggle function.

Selecting a custom entry retains the existing content-digest publication,
peer-resolution barrier, and preselected stock launch handoff. That handoff
has no interactive retail choice state: the selected Gameplay String is
already populated, so the stock completion path proceeds directly into the
chosen content.

Cancel and a second start-control activation close the loader picker and stay
in the Courtyard. They no longer clear into or open the retail picker.

### Client invariant

The connected-client contract is not relaxed:

- the start affordance renderer still returns before its trampoline;
- activation still returns before every authority/default/catalog decision;
- the hooks are still installed with zero custom entries;
- `OpenHostBoneyardPicker` and picker input still reject the client; and
- no Default row, custom row, or native surface is rendered or activatable by
  a connected client.

## Regression contracts

The production change requires deterministic contracts for all owner
behaviors:

1. empty custom catalog: the host/solo activation hook queues the stock
   generated Default run, with no native trampoline and no loader picker;
2. populated custom catalog: one Default entry is pinned at index zero above
   all custom entries, selecting it uses the generated-run queue, and selecting
   a custom entry retains its digest-backed handoff;
3. connected client: render and activation return before any stock,
   Default, or custom path, including zero-custom initialization; and
4. cancel: the loader picker closes without opening the retail picker.

Focused live acceptance must pair visible captures with logs/semantic scene
state proving direct Default run entry, custom-list order, Default dispatch,
custom Alpha Arena dispatch, and the absence of a client-owned choice surface.
