# Native multiplayer run-entry Arena lifecycle

This note records the native investigation performed after a reproducible
`0xC0000005` execute access violation during shared Boneyard run entry. The
first reports looked like an Arena use-after-free because the instruction
pointer was in `MEM_FREE` memory and a later retry used a different Arena
address. A first-chance crash dump, loader symbols, instruction-level
trampoline inspection, and headless Ghidra analysis show that interpretation
is wrong.

The analysis used the read-only Ghidra replica workflow against the 4,723,200
byte retail `SolomonDark.exe` with SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
Clean-main isolation used loader commit `44e1064`; the minimal failing variant
added only the runtime source from unpushed Boneyard decor commit `1a60985`
plus its required recovered layout values.

## Verdict

Clean `44e1064` is stable across repeated host-and-client run entry. The crash
is triggered by the Boneyard decor presentation hooks introduced in
`1a60985`, but the immediate defect is in the existing shared x86 instruction
decoder used to construct safe-hook trampolines:

1. A native `CALL rel32` (`E8`) is tagged with both `C_IMM_P66` and
   `C_REL32`.
2. `hde32_disasm` consumes that relative immediate once inside the
   `C_IMM_P66` block and a second time in the later `C_REL32` block.
3. The five-byte `CALL` is therefore reported as nine bytes.
4. `ResolveX86HookPatchSize` selects a 12-byte prologue for the affected
   constructors and ticks.
5. `RelocateCopiedInstructions` uses `decoded.len - 4` for the relative
   immediate offset. It rewrites bytes after the real displacement while
   leaving the original displacement unchanged.
6. From the newly allocated trampoline, the unchanged displacement points
   into unallocated memory. The process attempts to execute that address and
   raises `0xC0000005`.

The Arena itself is not stale when the bad call executes. The address change
seen on retry is the stock generator's candidate-Arena allocation/unwind
lifecycle, not proof that code called through a freed Arena.

## Isolation matrix

| Build under test | Runtime delta from `44e1064` | Result |
|---|---|---|
| Clean-main isolation | D3D late-subscriber harness enabler only; no decor runtime code | 11/11 shared run entries completed; 10-run gate produced 20 peer screenshots and zero AV signatures |
| Parked decor branch | Nine unpushed commits through `7202d74` | 0/2 first attempts; execute AV at `0x040C4A70`, then `0x047E4A70` |
| Minimal decor isolation | Five runtime files from `1a60985` plus required Boneyard layout values | 0/1 first attempt; execute AV at `0x048F4A70`; ProcDump captured first chance |

The changing high bits are allocation placement. In each failing process the
bad destination is exactly `trampoline + 0x44A70`, produced by preserving a
native `+0x44A68` relative displacement after moving the instruction.

The other eight parked commits do not cause the fault:

- six commits before `1a60985` add recovered documentation, layouts, and
  tooling but no decor presentation runtime;
- `eccc2f9` adds verifier timeouts;
- `7202d74` preserves late D3D frame subscribers and is needed only to make
  the repeated-entry harness launch reliably.

## Run-entry dispatch

The loader queues a hub start request and executes the actual region switch on
the game thread:

```text
Hub start request
  TryDispatchHubStartTestrunOnGameThread
    snapshot current Arena address for diagnostics
    Gameplay_SwitchRegion(5)                       0x005CDDD0
      leave old region through vtable +0xD4/+0xDC
      release the old region
      select target region
      enter target through vtable +0xE0
        Arena::Enter thunk                         0x004620C0
          region enter dispatcher                  0x0063F460
            create path: vtable +0xB4
              Arena_Create                         0x0046EA90
                stock Boneyard generation helpers
                  candidate wrapper                0x0046D7B0
                    Boneyard generator             0x006388B0
```

Arena vtable `0x00785934` establishes the relevant ownership:

| Slot | Target | Role |
|---:|---:|---|
| `+0xB4` | `0x0046EA90` | create/materialize Arena |
| `+0xE0` | `0x004620C0` | enter-region thunk to `0x0063F460` |
| `+0xE4` | native sync routine | synchronize an already-created region |

The dispatcher at `0x0063F460` chooses `+0xB4` for a region that must be
created and `+0xE4` for one that can be synchronized. `Arena_Create` selects
`play.boneyard` or `testrun.boneyard` and enters the native generation
pipeline.

## Candidate Arena ownership

`FUN_0046D7B0` is the key ownership wrapper inside that pipeline:

```text
saved_arena = DAT_00819844
candidate_storage = Object_Allocate(0x9068)
candidate = Arena::Arena(candidate_storage)        0x00464EE0
  DAT_00819844 = candidate
initialize candidate generation state
Boneyard_Generate(candidate, ...)                  0x006388B0
  return address after call = 0x0046D86A
DAT_00819844 = saved_arena
finish publication
```

The wrapper's exception state owns the candidate while generation is in
flight. If `Boneyard_Generate` raises, native unwind invokes the Arena
destructor/deallocator before control returns to the loader exception
boundary.

The constructor at `0x00464EE0` initializes the Arena vtable and publishes
the candidate through global `DAT_00819844`. The destructor at `0x0046C3F0`:

- clears `DAT_00819844` only if it still names the object being destroyed;
- releases the Arena's owned object lists and region resources;
- delegates the remaining base teardown;
- is followed by the deleting wrapper at `0x0046D790` when deallocation is
  required.

In the captured failure, the diagnostic log's `arena=0x10E92168` is the
pre-switch snapshot, `EDI=0x10F09A30` is the candidate under construction,
and the stack contains return address `0x0046D86A`. The subsequent successful
log names `0x10F09A30` because a later generation completed and published
that candidate. None of those addresses is used as an executable target.

## Loader exception and retry boundary

`TryDispatchHubStartTestrunOnGameThread` calls the native switch through the
loader's safe invocation boundary. On an exception it:

1. logs the pre-switch Arena snapshot and native exception code;
2. returns failure without marking the start request complete;
3. applies the bounded hub-start retry cooldown;
4. lets the action pump retry the pending request on the game thread.

That is why the logs show an AV followed several seconds later by a completed
switch. The retry masks the first failed generation from a coarse
scene-transition assertion, but it does not make the first-chance execute AV
safe. Run-entry acceptance must reject first-chance execute AV signatures,
not merely wait for an eventual `testrun` scene.

## Exact failing native path

The Boneyard generator at `0x006388B0` allocates scenery and goodies. Its
type-`0x080D` path calls the native object factory at `0x005B7080`, which
reaches the Goodie constructor:

```text
Boneyard_Generate                            0x006388B0
  push type 0x080D                           0x0063A05B
  native object factory                      0x005B7080
    Goodie allocation/factory return         0x005B82E3
    Goodie constructor                       0x005E3D60
      push esi
      mov esi, ecx
      call base constructor                  0x006287D0
```

Decor commit `1a60985` installs `HookBoneyardGoodieCtor` with
`InstallSafeX86Hook`. In the captured process:

```text
native Goodie target                         0x005E3D60
loader detour                                0x6DAD80B0
allocated trampoline                         0x048B0000
trampoline CALL destination                  0x048F4A70
native base-constructor destination          0x006287D0
```

The dump contains:

```text
048B0000  56                push esi
048B0001  8BF1              mov esi, ecx
048B0003  E8 68 4A 04 00    call 048F4A70
```

`0x048B0000` is committed `PAGE_EXECUTE_READWRITE`; `0x048F4A70` is
`MEM_FREE/PAGE_NOACCESS`. The trampoline is alive. Its copied relative call is
wrong.

The correct relocated displacement from `0x048B0008` to `0x006287D0` is
`0xFBD787C8`, encoded `C8 87 D7 FB`. The copied bytes retained the native
displacement `68 4A 04 00`.

`HookBoneyardScrubTick` has the same latent fault:

```text
native Scrub tick                            0x005E40D0
native base-tick call                        0x00624AC0
allocated trampoline                         0x048A0000
malformed trampoline destination             0x048E09F0
```

The Goodie constructor happens to execute during the failing generation, so
it raises first. A layout without a Goodie can pass run entry and later fail
when a Scrub ticks. The other five new decor presentation trampolines examined
in the dump do not begin with an affected relative call.

## Shared decoder defect

The decoder's `C_REL32` handling appears twice:

```text
if (cflags & C_IMM_P66) {
    if (cflags & C_REL32) {
        ... p += 4;
    }
}
...
if (cflags & C_REL32) {
    ... p += 4;
}
```

An isolated decode probe reports:

```text
offset=0 length=1 opcode=56 flags=00000000
offset=1 length=2 opcode=8B flags=00000001
offset=3 length=9 opcode=E8 flags=00000110
```

The correct third length is five. Because the shared relocator trusts that
length, this one decode error both expands the selected patch and moves the
location at which it writes the corrected displacement.

## Required remediation and gates

The foundational correction belongs in the shared x86 decoder/relocator
contract, not in Arena lifetime management and not in the hub-start retry:

- consume a `C_REL32` immediate exactly once, preserving operand-size-prefix
  behavior;
- add decoder coverage proving unprefixed and prefixed relative branches have
  correct lengths and flags;
- add trampoline coverage proving a copied `CALL rel32` still reaches its
  original absolute destination;
- keep the Boneyard Goodie and Scrub hooks on the safe-hook path rather than
  introducing fixed-size/manual trampolines;
- require repeated host-and-client run entry to complete with zero first-
  chance execute AVs, even when a retry later reaches the scene.

Clean-main stability alone does not exercise the faulty prologues because
`44e1064` does not install the seven decor presentation hooks. The minimal
decor reproducer is therefore the required interaction test when that branch
is integrated.

## Evidence provenance

The first-chance full dump is 262,798,728 bytes with SHA-256
`80630142e8e712e6db23d6c22fc78c965386e778e7128faff78ad6a315b7e9e9`.
It was captured with x86 ProcDump 11.1 and analyzed with x86 CDB/WinDbg using
the loader's private PDB. Headless Ghidra was run read-only from an isolated
replica; the canonical project was not modified.

Confidence labels:

- **verified live:** clean-main entry count, minimal-decor reproduction,
  execute-AV classification, retry behavior, exact-PID cleanup;
- **verified dump:** hook/detour/trampoline addresses, trampoline bytes,
  memory protection, stack path, both malformed relative calls;
- **verified static:** Arena allocation/publication/destruction ownership,
  region dispatch slots, generator/factory call chain, decoder double consume;
- **inferred:** which generated layout first reaches Goodie versus Scrub. The
  inference is not needed for the root cause because both malformed
  trampolines are present in the dump.
