# Native Arena world weather

## Scope and source identity

This report covers the Arena-owned world weather effect, not the local rain
children created by right-click Storm or Acid Rain. The static source is the
clean retail `SolomonDark.exe`, SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`, with the
preferred image base `0x00400000`.

## Environment mode boundary

The Boneyard header's byte `+518` is loaded into Arena `+0x8F20`. The authoring
format and procedural generator only produce values 0, 1, and 2. Arena tick
`0x0046E570` recomputes the current world bounds at `+0x8BCC..+0x8BD8`, then
calls the world-weather owner `0x00468E50` before the normal Region tick
`0x0046E390`.

| Mode | Native meaning | World weather |
| ---: | --- | --- |
| 0 | clear | no weather drops, splash children, or rainfall request |
| 1 | rainy | 3 procedural weather drops per Arena tick |
| 2 | stormy | 10 drops per tick, or 20 when Enhanced Effects is enabled |

The global settings/editor enum also contains Snowy and Foggy labels, but no
Boneyard authoring or generator path reaches those values. They are not
silently treated as Boneyard weather variants.

## `Anim_WeatherRaindrop`

The class catalog identifies `Anim_WeatherRaindrop` at vtable `0x00785180`:

| Method | Address | Recovered contract |
| --- | ---: | --- |
| constructor | `0x00454B60` | initializes height to `-App+0x1E0`, stores the current native float, and chooses streak length `20 + RandomFloat(10)` |
| tick | `0x00454C00` | adds the streak length to height and retires through vtable slot `+0x18` after height crosses zero |
| draw | `0x00459B60` | refreshes color/alpha through parent Arena slot `+0xF4`, then submits a procedural gradient streak from `y + height - length` to `y + height` through `0x00455840` |

The live object fields used by this class are:

| Offset | Meaning |
| ---: | --- |
| `+0x14/+0x18` | world position |
| `+0x1C` | falling height |
| `+0x20` | streak length |
| `+0x24` | cached alpha/color scalar |
| `+0x28` | Arena parent |

This is a procedural world-space line, not atlas `Anim_Raindrop` at draw
`0x00458F90` and not the `Anim_WhirlSnow` local Ring-of-Ice child.

## Spawn owner and splash child

`0x00468E50` gates on `Arena+0x8F20 != 0` and Arena state greater than 1. It
selects the count shown above, updates the shared rainfall requested-gain
field `0x0081CBF0`, and samples each candidate inside the current Arena bounds:

```text
x = bounds.left + RandomFloat(bounds.width)
y = bounds.top  + RandomFloat(bounds.height)
while FUN_005238C0(samplePoint) != 0: resample
```

`FUN_005238C0` performs the native point/collision validity query. Once a
point is accepted, the owner allocates a 0x2C-byte weather drop, writes its
position and Arena parent, and registers it with the Arena animation manager
at `Arena+0x1E0`.

The same spawn then allocates an `Anim_FadeScale` through `0x00452E20`, assigns
`DAT_00819994 + 0x1298`, and registers it with the second animation manager at
`Arena+0x2C4`. The asset map resolves that pointer to `DeadHawg` record 24.
The native constructor writes the initial scale/alpha, random scale and
rotation values, and the small scale recurrence used by the splash.

## Audio and lifecycle

The source registry entry is `sounds\\rainfall__loop` at requested-gain field
`0x0081CBF0`. The native audio report lists `0x00468E50` as its Arena weather
producer, separate from the StormCloud (`0x006021A0`) and Acid Rain
(`0x00604E90`) ability producers. Mode 1 uses the native rainy scalar
`0.4 * (1 - Arena+0x8E48)`; mode 2 uses `1 - Arena+0x8E48`.

The drops and splash children are peer-local presentation objects. They are
not serialized, replicated, collision actors, or authoritative RNG consumers.
Arena replacement/destruction stops renewing the rainfall request and retires
both local animation-manager families.

## Web-port handoff

The Website already carries `scene.environmentMode` and renders the authored
mode-specific compact scenery rows. The missing owner is a Boneyard renderer
weather layer that consumes the existing scene byte/bounds, uses a private
presentation RNG, renders the procedural streaks and exact `DeadHawg:24`
splashes in the post-main world lane, and synchronizes the existing
`rainfall-loop` asset with a distinct Boneyard owner key. It must not touch the
authoritative simulation RNG or the secondary-ability rain actors.
