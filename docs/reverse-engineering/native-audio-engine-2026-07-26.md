# Native audio engine lifecycle (2026-07-26)

## Scope and binary identity

This note maps the stock Solomon Dark audio-manager layer from asset creation
through BASS channel teardown. It covers the retail `SolomonDark.exe` with
SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
All addresses below are preferred-image virtual addresses for that binary.

The earlier [native audio system note](native-audio-system.md) remains the
asset inventory: it names every compiled sound, voice, dynamic sound, music
track, and ambient producer. This note is the lifecycle map used by loader
instrumentation. Fresh headless Ghidra output for this pass is retained under
`/mnt/d/codex-evidence/spell-fx-20260726/investigation/`:

- `ghidra-native-audio-classes-a.log`
- `ghidra-native-audio-classes-b.log`
- `ghidra-native-audio-classes-c.log`
- `ghidra-native-audio-shutdown-xrefs.log`
- `ghidra-native-audio-class-catalog-*.log`
- `ghidra-native-audio-spell-loop-calls.log`

The result verifies the premise in `binary-layout.ini`: the game uses BASS
2.4 beneath a stock `Audio` wrapper. The wrapper, rather than gameplay code,
owns sample/channel records, loop reference counts, persisted volume
application, pause state, and final teardown.

## Layer overview

The stock layer has four ownership levels:

1. `Audio` owns manager lists and publishes the singleton at
   `DAT_00B401A0`.
2. `Sound`, `SoundLoop`, `Music`, and `SoundStream` own BASS resources.
3. `Sound` owns heap-allocated 16-byte channel records; BASS owns the channel
   handles referenced by those records.
4. gameplay systems retain references to the stock wrapper objects and call
   their play/start/stop methods. They do not own or free BASS handles.

The enabled byte at `DAT_00B40239` gates every BASS load, play, attribute,
pause, query, and free operation. Wrapper state still advances when that byte
is clear. In particular, `SoundLoop_Start` and `SoundLoop_Stop` still update
the native reference count with audio disabled. That makes the logical loop
lifecycle observable in silent automated runs.

## Class and vtable map

The address-bearing entries are versioned in `[audio.vtables]` and
`[audio.lifecycle]` in `config/binary-layout.ini`.

| Class | Vtable | Construction / loading | Tick | Destruction |
| --- | ---: | ---: | ---: | ---: |
| `Audio` | `0x007DB6CC` | `0x00406DE0` | vtable thunk `0x00407460` | `0x00406F90` |
| `Sound` | `0x007DB784` | `0x00407530` / `0x004076D0` | none | `0x004075F0` |
| `SoundLoop` | `0x007DB78C` | `0x00408040` / `0x00408220` | `0x00408390` | `0x00408160` |
| `SoundEcho` | `0x007DB7AC` | `0x004084A0` | `0x00408550` | shared transient-object teardown |
| `SoundDelayed` | `0x007DB7CC` | `0x004085C0` | `0x00408690` | shared transient-object teardown |
| `Music` | `0x007DB7F0` | `0x004086E0` / `0x004088A0` | `0x00409610` | `0x00408790` |
| `SoundStream` | `0x007DB810` | `0x0040AC60` / `0x0040ACF0` | none | `0x0040AC70` (`0x0040ACC0` deleting) |
| `AmbientSound` | `0x007DB818` | `0x0040B060` | `0x0040B120` | `0x0040B080` |

`Audio` contains three pointer/object-manager lists beginning at `+0x8C`,
`+0xA4`, and `+0xBC`, plus two embedded manager objects at `+0xD4`.
`Sound` objects register with the list rooted at `Audio +0x8C`.
Ticked controllers (`SoundLoop`, echo, delay, and music helpers) register
through the object manager rooted at `Audio +0xBC`. Destructors unregister
from the same owner before freeing their private resources.

## Engine startup, volume, pause, and shutdown

### Startup

The application coordinator at `0x00407080` performs this exact sequence:

1. call `0x004450D0`;
2. call persisted-volume loader `0x00407190`;
3. apply effective sound gain with BASS configs 4 and 5; and
4. apply effective music gain with BASS config 6.

The initializer at `0x004450D0` verifies BASS version `0x0204`, then calls
`BASS_Init(-1, 44100, 0, window, 0)`. If the default output device fails, it
retries with device 0, BASS's no-sound device. Success calls `BASS_Start` and
writes 1 to `DAT_00B40239`.

### Persisted and effective volume

`0x00407190` reads `Audio.SoundVolume` into `Audio +0x7C` and
`Audio.MusicVolume` into `Audio +0x78`. The setters retain the distinction
between the user scalar and the manager's effective scalar:

| Path | User field | Effective field | Writer | BASS result |
| --- | ---: | ---: | ---: | --- |
| music | `Audio +0x78` | `Audio +0x80` | `0x00407340` | config 6 |
| sound | `Audio +0x7C` | `Audio +0x84` | `0x004073A0` | configs 4 and 5 |

Settings apply at `0x005D8FC0` calls those two writers. The audio-disable
launch seam correctly intercepts the BASS initializer instead of changing
either persisted scalar.

### Global pause

`Audio::Pause` at `0x00407400` uses a reference count at `Audio +0x88`.
The pause side increments the count; the resume side decrements and clamps it
to zero. When BASS is enabled and its separate global pause inhibit byte is
clear, the zero/nonzero transition calls `BASS_Start` or `BASS_Pause`.
Nested systems can therefore hold the engine paused without prematurely
resuming another owner's pause.

### Shutdown

The sole xref to the `BASS_Free` import thunk at `0x006B0186` is the
application run coordinator at `0x0040C690`. After the main loop and gameplay
teardown it writes zero to `DAT_00B40239`, calls `BASS_Free`, then continues
application-object cleanup. The `Audio` destructor at `0x00406F90` clears
`DAT_00B401A0` when it owns the singleton and destroys its manager lists.

Resource classes also have local teardown:

- `Sound` frees its channel-record allocations, pointer-list storage, and
  BASS sample, then unregisters from `Audio`.
- `SoundLoop` first forces the loop inactive and pauses its owned channel,
  unregisters its tick object, frees its optional secondary sample, and then
  runs the embedded `Sound` destructor.
- `SoundStream` pauses its handle and calls `BASS_StreamFree`.
- `Music` frees parsed song/track objects and calls `BASS_MusicFree` for its
  module handle.

The application-level `BASS_Free` remains the final device boundary; class
destructors are per-resource cleanup, not alternate device shutdown paths.

## `Sound`: samples, channel records, and one-shots

### Object layout and ownership

The 0x2C-byte `Sound` object has these confirmed fields:

| Offset | Meaning |
| ---: | --- |
| `+0x04` | BASS sample handle |
| `+0x08` | embedded channel-record pointer-list header |
| `+0x10` | channel-record count |
| `+0x1C` | pointer-list storage |
| `+0x20` | maximum simultaneous channels |
| `+0x24` | per-sound/base gain |
| `+0x28` | per-sound channel multiplier |

A channel record is 16 bytes:

| Offset | Meaning |
| ---: | --- |
| `+0x00` | BASS channel handle |
| `+0x04` | base frequency returned by `BASS_ChannelGetInfo` |
| `+0x08` | current gain |
| `+0x0C` | owner multiplier |

The wrapper owns the record allocation. BASS owns the handle produced from
the sample. No gameplay object frees either directly.

### Sample creation

`Sound_Load` at `0x004076D0` resolves an extensionless path in this order:
`.ogg`, `.caf`, `.wav`, `.mp3`. With BASS enabled it calls
`BASS_SampleLoad`, stores the sample handle at `+0x04`, and stores the
requested channel capacity at `+0x20`. With BASS disabled it stores a zero
handle but preserves the wrapper's logical configuration.

### Channel acquisition

`0x00407A20` scans the object's record list and returns the first channel for
which `BASS_ChannelIsActive(handle) != 1`. If every existing record is active
and count is below `+0x20`, it allocates a 16-byte record, calls
`BASS_SampleGetChannel(sample, 1)`, reads the base frequency with
`BASS_ChannelGetInfo`, initializes both gain factors, and appends the record.
If capacity is exhausted it returns null and the requested one-shot is
dropped.

When audio is disabled, an existing record is immediately reusable and a new
record receives handle zero. This is intentional wrapper behavior and is why
silent instrumentation must observe the wrapper call, not only BASS.

### Play and stop

The public one-shot wrappers are:

- `0x00407B70`: gain-only play;
- `0x00407CD0`: pitch plus gain play.

They route to low-level bodies `0x00407C50` and `0x00407DC0`. A successful
body writes BASS attribute 2 (gain), attribute 1 (frequency, optionally
multiplied by pitch), and calls `BASS_ChannelPlay(handle, 1)`. Restart is
true because each selected channel record represents a fresh trigger.

`Sound::Stop` at `0x00407F90` pauses every channel record for that sample. It
also finds and terminates delayed controllers whose source points at the
same `Sound`. `Audio::StopAll` at `0x00407470` iterates the registered sound
list and calls that method.

## `SoundLoop`: persistent channel lifecycle

`SoundLoop` is a 0x60-byte object with an embedded `Sound` beginning at
`+0x18`. The loop-specific fields are:

| Offset | Meaning |
| ---: | --- |
| `+0x44` | owned `Sound` channel-record pointer |
| `+0x48` | base loop gain |
| `+0x4C` | logical start/stop reference count |
| `+0x50` | fade-in step |
| `+0x54` | fade-out step |
| `+0x58` | transition state: 0 steady, 1 in, 2 out |
| `+0x5C` | transition gain |

`SoundLoop_Load` at `0x00408220` calls `Sound_Load`, acquires one channel
record, stores it at `+0x44`, then calls
`BASS_ChannelFlags(handle, 4, 4)`. Bit 4 is the BASS loop flag; it is applied
to the channel rather than the sample.

`SoundLoop_Start` at `0x00408320` calls
`BASS_ChannelPlay(handle, 1)` only on the logical `0 -> 1` transition. It
always increments `+0x4C` and sets transition gain to 1.

`SoundLoop_Stop` at `0x00408350` decrements `+0x4C`. A result below 1 pauses
the BASS channel with `BASS_ChannelPause`, clamps the count to zero, and sets
transition gain to zero. It deliberately does not call `BASS_ChannelStop`;
the next `Start` restarts the paused looping channel from the beginning.

The tick at `0x00408390` applies fade state. Fade-in adds `+0x50` until gain
is 1. Fade-out subtracts `+0x54`; reaching zero unregisters the ticking
transition and calls `SoundLoop_Stop`. Every active transition writes
`base gain * transition gain` through BASS attribute 2.

The reference count is the authoritative leak signal. A BASS-only observer
cannot tell whether an inaudible or disabled wrapper still has an unmatched
owner. A durable loader registry must therefore capture wrapper start/stop
calls, caller return address, object identity, attribution context, age, and
the post-call `+0x4C` value.

## Echo and delayed controllers

`SoundEcho` (`0x004084A0`) and `SoundDelayed` (`0x004085C0`) are transient
manager-owned controllers, not BASS resource owners.

- Echo tick `0x00408550` decrements its delay, plays the source `Sound`, scales
  the next gain, decrements the repeat count, and self-terminates when the
  count is exhausted.
- Delayed tick `0x00408690` decrements its countdown and invokes its terminal
  virtual action at zero. That terminal path plays the retained source sound
  and destroys the controller.

`Sound::Stop` searches the manager's transient list for delayed objects that
refer to it, so stopping a sound cancels future deferred triggers as well as
pausing current channels.

## Music

`Music_Load` at `0x004088A0` parses `music\music.txt` and loads
`music\music.mo3`, falling back to `music\music.it`. The object owns parsed
song/track definitions, two module playback handles at `+0x18` and `+0x20`,
per-track envelopes, and crossfade state.

The tick at `0x00409610` advances the crossfade and applies module-channel
attributes using BASS attribute numbers `0x200 + channel`. When one side
reaches zero it calls `BASS_ChannelStop` for that module handle.
`0x0040A3F0` is the explicit stop path for both playback handles.
The destructor at `0x00408790` frees parsed definitions and calls
`BASS_MusicFree` for the owned module resource.

Music does not use `Sound` channel records or `SoundLoop` reference counts.
Its ownership unit is the module handle plus the object's two playback lanes.

## `SoundStream`

The 8-byte `SoundStream` owns one BASS stream handle at `+0x04`.
`SoundStream_Load` at `0x0040ACF0` uses the same extension fallback family
and calls `BASS_StreamCreateFile`. The runtime methods are:

| Address | Operation |
| ---: | --- |
| `0x0040AF70` | set volume, then `BASS_ChannelPlay(handle, 1)` |
| `0x0040AFB0` | `BASS_ChannelPause(handle)` |
| `0x0040AFD0` | set BASS attribute 2 |
| `0x0040B000` | return `BASS_ChannelIsActive(handle) == 1` |
| `0x0040B020` | read and combine the stereo level |

The destructor at `0x0040AC70` pauses, frees with `BASS_StreamFree`, and
zeros the handle. `0x0040ACC0` is the deleting-destructor entry.

Dialogue uses this class for `voices\%s.wav`; the compiled registry uses it
for 40 long effects. Stream activity is independent of the sample channel
pool and loop reference counts.

## Ambient wrappers

`AmbientSound` is a 0x10-byte non-owning wrapper:

| Offset | Meaning |
| ---: | --- |
| `+0x04` | requested gain for this frame |
| `+0x08` | previous applied gain |
| `+0x0C` | referenced `SoundLoop` |

`AmbientSound_Tick` at `0x0040B120` starts the referenced loop on the
`0 -> positive` gain transition, stops it on the `positive -> 0` transition,
applies volume, copies requested to previous, and clears requested gain.
Producers must renew gain every frame. The destructor at `0x0040B080`
balances any live loop reference but does not free the shared loop.

This distinction is critical for attribution: the channel owner remains the
compiled `SoundLoop`; the ambient wrapper and its gameplay caller are the
producer.

## Compiled registry and stable attribution

The registry constructor is `0x005A8DD0` and its fixed asset loader is
`0x004EE010`. The pointer published through `DAT_008199D8` addresses a rigid
233-object block:

| Indexes | Type | First offset | Stride |
| ---: | --- | ---: | ---: |
| 0..110 | `Sound` | `+0x0018` | `0x2C` |
| 111..150 | `SoundStream` | `+0x132C` | `0x08` |
| 151..172 | `SoundLoop` | `+0x146C` | `0x60` |
| 173..232 | `Sound` variants | `+0x1CAC` | `0x2C` |

Those offsets let runtime diagnostics turn a wrapper pointer into a stable
registry index even when ASLR changes the process base. The 22 loop names and
offsets are recorded in `native-audio-catalog.json`; unknown dynamic objects
remain attributable by object address, caller return address, and active
actor/cast context.

## Frost Jet lifecycle seam and pre-fix root cause

Frost Jet's loop is registry index 161,
`sounds\iceloop__loop`, at registry offset `+0x182C`.
Its exact wrapper calls are `0x00549BB2` for start and `0x00549725` for
stop.

The native start edge is:

```text
0x00549B81  Player control-brain selection
0x00549B86  compare selected skill with 0x20 (Frost)
0x00549BAC  add registry +0x182C
0x00549BB2  call SoundLoop_Start
0x00549BB7  return address
```

The common primary-transition stop fan-out is:

```text
0x005496E5  compare actor current skill +0x270 with previous +0x274
0x0054971F  add registry +0x182C
0x00549725  call SoundLoop_Stop
0x0054972A  return address
```

The loop is therefore not stopped by an effect timeout or by the cone effect
at `0x00641B10`. It stops only when `PlayerActorTick` observes the native
current/previous primary transition. WAN evidence showed the replicated
cast-release packet already arriving promptly, while the remote actor's
animation-drive byte, no-interrupt flag, and authored control-brain target
kept selecting Frost. The stop delay was a missing native release edge after an on-time snapshot,
not network lateness and not BASS decay.

The loader fix must preserve this ownership: release replication should make
the remote stock tick produce the transition, and stock should call
`SoundLoop_Stop`. Directly pausing BASS or decrementing the loop from the
network layer would hide an unbalanced native owner and would not repair the
cast/effect lifecycle.

## Static contracts

`tests/re/static_re_audio_disable_contracts.py` pins:

- every address added to `[audio.vtables]`, `[audio.lifecycle]`,
  `[audio.registry]`, and `[audio.spell_calls]`;
- the corresponding executable bytes or vtable entries;
- the 233-entry/22-loop fixed registry geometry;
- the BASS loop flag call and loop reference-count start/stop semantics; and
- the Frost registry offset and exact native start/stop call sites.

The contracts intentionally live in the existing audio RE test so the static
suite's registered-test count remains stable.
