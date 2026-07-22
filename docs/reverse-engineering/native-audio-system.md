# Native audio system

## Result

Solomon Dark does not discover gameplay sounds by enumerating the `sounds`
directory. `MyApp` owns a compiled, fixed-layout registry whose builder at
`0x004EE010` loads exactly **233 paths in native slot order**. Those slots are
171 `Sound` objects, 40 `SoundStream` objects, and 22 `SoundLoop` objects.

Three other asset paths sit outside that registry:

- dialogue constructs `voices\%s.wav` on demand and streams the result;
- the Polisher NPC embeds a loop loaded from
  `dynamic_sounds\wipeglass`;
- `Music` parses `music\music.txt` and loads `music.mo3`, with
  `music.it` as the compiled module fallback.

The retail tree therefore contains **304 WAV files**: 233 compiled sounds,
70 voices, and one dynamic sound. It also contains the MO3 music module and
its 12-song/19-track table. The exhaustive, address-bearing inventory is
[`native-audio-catalog.json`](native-audio-catalog.json).

This document covers the retail `SolomonDark.exe` whose SHA-256 is
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.

## Runtime class model

The native layer is built on BASS and distinguishes ownership, playback
policy, and lifetime by concrete class:

| Class | Vtable | Constructor / loader | Native behavior |
| --- | ---: | ---: | --- |
| `Audio` | `0x007DB6CC` | `0x00406DE0` | Global manager published at `DAT_00B401A0`; owns three pointer/object lists, two arrays, pause state, and volume controls. |
| `Sound` | `0x007DB784` | `0x00407530` / `0x004076D0` | One BASS sample plus a list of live channels; suitable for overlapping one-shots. |
| `SoundLoop` | `0x007DB78C` | `0x00408040` / `0x00408220` | Embeds `Sound`, owns one looping channel, and carries start/stop/fade state. |
| `SoundEcho` | `0x007DB7AC` | `0x004084A0` | Manager-ticked repeat object; replays a sound after a delay and multiplies gain for later repeats. |
| `SoundDelayed` | `0x007DB7CC` | `0x004085C0` | Manager-ticked countdown object that invokes its terminal action at zero. |
| `Music` | `0x007DB7F0` | `0x004086E0` / `0x004088A0` | Two module channels, parsed song/track definitions, channel envelopes, and crossfade state. |
| `SoundStream` | `0x007DB810` | `0x0040AC60` / `0x0040ACF0` | One BASS stream handle; used for long effects and voices. |
| `AmbientSound` | `0x007DB818` | tick `0x0040B120` | Global 0x10-byte wrapper over a registry `SoundLoop`; Region lifecycle services requested gain and zero-crossing start/stop behavior. |

`DAT_00B40239` is the initialized/enabled BASS gate used by load, play, pause,
attribute, and free paths. `Sound` construction registers with the manager and
destruction removes it after releasing active channels and the BASS sample.
`SoundLoop` performs the parallel manager registration for its ticking loop
state and tears down the channel before its embedded `Sound`.

### One-shot sample path

`Sound_Load (0x004076D0)` accepts an extensionless base path. Its confirmed
fallback sequence is `.ogg`, `.caf`, `.wav`, then `.mp3`; the retail registry
resolves every one of its 233 bases to a WAV. It calls `BASS_SampleLoad` and
stores the returned sample handle. The loader's final argument becomes stored
sample/playback state at object `+0x20`.

`0x00407DC0` is the low-level channel play path. It applies BASS attribute 2
for volume and attribute 1 for frequency/pitch, then calls
`BASS_ChannelPlay(channel, 1)`, restarting that channel. The `Sound` object
keeps a list so repeated effects can overlap rather than treating a sample as
a single global playback cursor.

### Loop, echo, delay, and ambient behavior

`SoundLoop_Load (0x00408220)` first loads its sample, obtains a channel, and
sets the BASS loop flag (`4`). The loop owns explicit gain and transition
state:

- state 1 adds the fade-in increment until gain reaches 1;
- state 2 subtracts the fade-out increment until gain reaches 0, then stops;
- every tick writes `base volume * transition gain` to BASS attribute 2.

`SoundEcho_Tick (0x00408550)` counts down, plays the source sound, multiplies
the next repeat's gain, and self-terminates after its repeat count. A delayed
sound uses the narrower countdown at `0x00408690` and destroys itself when
the counter expires. These are transient manager-owned playback controllers,
not entries in the compiled asset registry.

### Global ambient loop mix

The Region constructor at `0x00652830` binds 13 global 0x10-byte
`AmbientSound` wrappers to existing `SoundLoop` objects in the compiled audio
registry. They are not embedded in, or owned by, each Region allocation.
Wrapper `+0x04` is the requested-gain accumulator, `+0x08` is the previous
applied gain, and `+0x0C` is the loop pointer.

`AmbientSound_Tick (0x0040B120)` implements a one-frame request contract:

1. start the loop when previous gain is zero and requested gain is positive;
2. stop it when previous gain is positive and requested gain is zero;
3. copy requested gain into the `SoundLoop` base-gain field and, when BASS is
   enabled, update the channel volume attribute;
4. copy requested gain to previous gain; and
5. clear requested gain to zero for the next gameplay frame.

Region base tick `0x0063EFC0` services all 13 wrappers. Gameplay producers
must therefore renew a nonzero request every frame; a producer becoming
inactive naturally produces the zero-crossing stop on the next tick.

| Wrapper | Requested gain | Loop pointer | Registry index | Compiled loop path |
| ---: | ---: | ---: | ---: | --- |
| `0x0081CB4C` | `0x0081CB50` | `0x0081CB58` | 163 | `sounds\\lowfire__loop` |
| `0x0081CB5C` | `0x0081CB60` | `0x0081CB68` | 152 | `sounds\\comet__loop` |
| `0x0081CB6C` | `0x0081CB70` | `0x0081CB78` | 154 | `sounds\\earthquake__loop` |
| `0x0081CB7C` | `0x0081CB80` | `0x0081CB88` | 156 | `sounds\\electric__loop` |
| `0x0081CB8C` | `0x0081CB90` | `0x0081CB98` | 158 | `sounds\\flyblown__loop` |
| `0x0081CB9C` | `0x0081CBA0` | `0x0081CBA8` | 170 | `sounds\\Soul__Loop` |
| `0x0081CBAC` | `0x0081CBB0` | `0x0081CBB8` | 151 | `sounds\\beam__loop` |
| `0x0081CBBC` | `0x0081CBC0` | `0x0081CBC8` | 155 | `sounds\\eerie__loop` |
| `0x0081CBCC` | `0x0081CBD0` | `0x0081CBD8` | 168 | `sounds\\rollingstoneloop__loop` |
| `0x0081CBDC` | `0x0081CBE0` | `0x0081CBE8` | 166 | `sounds\\PlaneCross__Loop` |
| `0x0081CBEC` | `0x0081CBF0` | `0x0081CBF8` | 167 | `sounds\\rainfall__loop` |
| `0x0081CBFC` | `0x0081CC00` | `0x0081CC08` | 164 | `sounds\\maggots__loop` |
| `0x0081CC0C` | `0x0081CC10` | `0x0081CC18` | 171 | `sounds\\steadywind__loop` |

The direct gameplay request producers are also finite:

| Loop | Functions that reach its requested-gain field |
| --- | --- |
| lowfire | `0x00460AB0`, `0x005FF050`, `0x00605C80` |
| comet | `0x006220D0` |
| earthquake | `0x00460AB0`, `0x004963C0`, `0x00613200` |
| electric | `0x00451DC0`, `0x00611EB0`, `0x00628F10` |
| flyblown | `0x004863A0` |
| Soul | `0x00460AB0`, `0x00486C30`, `0x0049D0D0` |
| beam | `0x0044FFE0`, `0x00460AB0`, `0x0049D0D0` |
| eerie | `0x00605920`, `0x00605C00`, `0x00605C80`, `0x0061C440` |
| rollingstone | `0x00460AB0`, `0x00620B60` |
| PlaneCross | `0x00548B00`, `0x005FB460`, `0x006145D0`, `0x0061CF20` |
| rainfall | `0x00468E50`, `0x006021A0`, `0x00604E90` |
| maggots | `0x004A2760` |
| steadywind | `0x00460AB0`, `0x0049D0D0`, `0x00548B00`, `0x005FD7A0`, `0x006021A0`, `0x0061CF20` |

Region destructor `0x0064A5D0` normalizes all 13 requested fields during
teardown, but the wrappers remain global and the underlying loops remain
owned by the audio registry. This distinction matters for region replacement:
retiring a room must stop renewing its requests, not free shared loop objects.

## Compiled `MyApp` sound registry

`0x005A8DD0` constructs the registry object, and `0x004EE010` fills it. The
object is embedded at `MyApp +0x319EC8` and exposed through
`DAT_008199D8`. Its first 0x18 bytes are pointer-list header state; concrete
audio objects then occupy a rigid 0x26FC-byte block:

| Indexes | Count | Class | Registry offsets | Stride | Meaning |
| ---: | ---: | --- | ---: | ---: | --- |
| 0..110 | 111 | `Sound` | `+0x0018..+0x1300` | `0x2C` | Individually named one-shot slots. |
| 111..150 | 40 | `SoundStream` | `+0x132C..+0x1464` | `0x08` | Individually named long-effect streams. |
| 151..172 | 22 | `SoundLoop` | `+0x146C..+0x1C4C` | `0x60` | Individually named persistent/fading loops. |
| 173..232 | 60 | `Sound` | `+0x1CAC..+0x26D0` | `0x2C` | Arrays of randomized variants. |

The last object ends immediately before loose-image fields beginning at
`MyApp +0x31C5C4`; audio and image ownership are adjacent but remain separate
native systems. The constructor explicitly invokes 111 `Sound` constructors,
40 `SoundStream` constructors, 22 `SoundLoop` constructors, and vector
constructors for the final variant groups. After each load, the builder calls
`MyApp` virtual slot `+0x10` as a progress notification.

The grouped tail contains these exact families:

| Family | Variants | Family | Variants |
| --- | ---: | --- | ---: |
| ArmorCrash | 3 | Bite | 3 |
| Chain | 2 | CoffinCreak | 2 |
| Crow | 2 | dropbag | 2 |
| hail | 4 | imp | 8 |
| MaggotSqueak | 2 | PortalGroan | 2 |
| Shock | 3 | Shootweb | 3 |
| shovel | 2 | Squish | 3 |
| Step | 2 | stepsplash | 4 |
| SwordStrike | 2 | throwdirt | 2 |
| throwlightning | 2 | Webbed | 2 |
| Wizard_Ouch | 3 | zombiewalk | 2 |

The catalog records, for every slot, its registry index, executable literal
and call addresses, loader/class, registry and absolute `MyApp` offsets,
extensionless native path, resolved retail file, byte size, and SHA-256. This
is the stable identity required to correlate the hundreds of gameplay xrefs
to files; basenames alone are ambiguous (`step1`, for example, exists in more
than one directory).

## Voice path

The dialogue path beginning at `0x004FCEC0` formats
`voices\%s.wav` from the requested voice ID. If that exact file exists, it
allocates an 8-byte `SoundStream`, loads it through `0x0040ACF0`, and starts it
through `0x0040AF70`. If it is absent, the code follows the text/dialogue path
through `data\dialogue\narration.txt`; missing recorded speech does not make
the dialogue record itself invalid.

The retail `voices` directory has 70 WAVs. Thirty-four IDs also appear as
literal `KEY=` definitions in the installed dialogue text; 36 do not. The
latter group includes hardcoded/event-selected Solomon lines, alternate
male/female lines, and ouch lines. Absence from the text definitions is not
evidence of dead audio: the executable can supply an ID directly. The catalog
therefore preserves the file inventory and any text references without
inventing reachability for unreferenced IDs.

Voice files are not `MyApp` registry members, do not consume one of its 233
slots, and are not preconstructed during the registry build. This is a real
data-driven filename seam, bounded by whatever IDs dialogue/gameplay code
actually requests.

## Dynamic sound path

The only installed dynamic sound is
`dynamic_sounds/wipeglass.wav`. `Polisher` construction at `0x0050B4F0`
embeds a `SoundLoop`, passes the extensionless path to `0x00408220`, and
starts the loop. No directory enumeration or general dynamic-sound registry
was recovered. The directory name therefore does not imply an open plugin
surface; it is one compiled consumer with a disk-backed path.

## Music table and crossfades

`Music_Load (0x004088A0)` looks for `<directory>\music.txt`, loads
`<directory>\music.mo3` when present, and otherwise tries
`<directory>\music.it`. It creates two BASS music handles so the runtime can
transition between module positions. The text parser recognizes `song` rows
and `track` rows scoped to the preceding song.

The stock table has these song names and module offsets:

| Song | Offset | Track sets |
| --- | ---: | --- |
| prelude | 0 | none |
| combatprelude | 5 | base, combat, heavycombat, danger, glory |
| combat | 6 | base, combat, heavycombat, danger, glory |
| boss_aggressive | 58 | base, combat, heavycombat |
| boss_squirmy | 70 | base, combat, heavycombat |
| boss_gargantuan | 82 | base, combat, heavycombat |
| solomondarktheme | 95 | none |
| academy | 101 | none |
| selection | 116 | none |
| death | 118 | none |
| deathguitar | 122 | none |
| academyold | 126 | none |

Track channel lists are preserved verbatim in the catalog, including the
stock `glory` list's repeated channel 31. `Music_Tick (0x00409610)` advances
the two handle gains, stops the faded-out handle, and walks per-channel target
envelopes using BASS music-channel attributes. A track does not start a second
audio file: it marks module channels silent or audible inside the current
song, exactly as the stock table's comments describe.

## Asset-mod implications

The native capabilities split into four different compatibility contracts:

1. A replacement for a compiled `sounds` slot can use the same extensionless
   path, but adding a file does not add a new registry member or gameplay
   trigger.
2. A voice is filename-addressable at runtime, but only an ID requested by
   dialogue or native/mod logic will be loaded.
3. The dynamic-sound directory has one confirmed hardcoded consumer, not a
   generic scanner.
4. Music is table-driven within the `Music` parser's song/track grammar, while
   the caller still decides which named song/track to request.

Consequently a mod manifest must not describe all audio as a flat file overlay.
It needs to distinguish replacement of a native registry slot, on-demand voice
content, specifically referenced dynamic audio, and a coherent music module
plus table. Loading new files is separate from creating new gameplay references
to them.

## Reproduction and verification

Recover the compiled registry from the analyzed executable with:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File scripts/Invoke-GhidraHeadless.ps1 `
  -ScriptPath tools/ghidra-scripts/catalog_audio_registry.py `
  -ScriptArguments 0x004EE010
```

Feed that log and a stock game tree to the deterministic catalog builder:

```bash
python3 tools/build_native_audio_catalog.py \
  --game-root /path/to/SolomonDarkAbandonware \
  --registry-log /path/to/ghidra-output.txt \
  --source-label stock/SolomonDarkAbandonware \
  --output docs/reverse-engineering/native-audio-catalog.json

python3 -m unittest tests.test_native_audio_tools -v
```

The builder rejects anything other than 233 contiguous rows, validates every
class/offset segment, resolves files case-insensitively while preserving their
actual spelling, errors on missing or ambiguous assets, hashes every resolved
file, parses voice-definition references, and preserves music channel order.
