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
| draw | `0x00459B60` | on its sentinel value, converts the world point through parent Arena slot `+0xF4`, caches the Region analytic scalar from `Arena+0x8C44 -> 0x0057E490`, then submits a procedural gradient streak from `y + height - length` to `y + height` through `0x00455840` |

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

## Render boundary and Complex Lighting branches

The splash and streak are not merely ordered siblings in one late weather
layer. They straddle the Region light compositor:

```text
0x0046F6C0  draw Arena+0x2C4 Anim_FadeScale splash manager
0x0046FAFF  Complex Lighting on: multiply the painted underlay by the light map
0x0046FDAF  flush the shared world queue
0x0046FFB7  draw Arena+0x1E0 Anim_WeatherRaindrop streak manager
0x00470107  Complex Lighting off: multiply the completed shared/late lanes
```

`Anim_FadeScale::Draw 0x00455DF0` installs its authored RGB and life-clamped
alpha, selects renderer blend state `1`, transforms `DeadHawg:24`, and draws it
without an analytic Region-light query. Renderer dispatcher `0x004208A0` maps
state `1` to Direct3D `SRCBLEND=SRCALPHA` (`5`) and `DESTBLEND=ONE` (`2`), so
this splash is additive, not source-over. With `Game.ComplexLighting` enabled
(`0x00B3BCA8 != 0`), the additive result is darkened because it is already in
the framebuffer when compositor
`0x0057D670` runs at `0x0046FAFF`. The later streak cannot use that earlier
raster pass, so `Anim_WeatherRaindrop::Draw 0x00459B60` caches the analytic
scalar and writes it into both gradient endpoint RGB values; the endpoint
alphas remain `0` and `0.5`.

With Complex Lighting disabled, common analytic tint is forced to white. The
same raster compositor moves to `0x00470107`, after the streak manager, so both
the splash and the white streak are multiplied by the completed light map.
There is no stock branch in which either weather family stays globally bright
over zero-light pixels.

This is an observable ownership boundary. A browser port must use separate
render roots for the pre-composite splash lane and post-composite streak lane;
putting both under one late parent preserves their relative order but loses the
intervening native operation.

## Shared `Anim_FadeScale` painter census

The additive state above belongs to the concrete `Anim_FadeScale` vtable
`0x00785A84`, not only to Arena weather. The class catalog and exact constructor
reads close every vtable-install reference:

| Constructor/producer | Exact `Anim_FadeScale` member | Painter consequence |
| ---: | --- | --- |
| `0x00468E50` | Arena weather `DeadHawg[24]` splash | additive before the Region composite |
| `0x0047F8D0` | Wraith dissolve `BadGuys[20]` core | additive |
| `0x0050B390` | Courtyard fountain `College[38]` transient | additive |
| `0x005F7010` | Tragic Circle player pulse `BadGuys[7]` | additive |
| `0x005FB020` | Magic Circle player pulse `BadGuys[7]` | additive |
| `0x00644A00` | Teleport source/destination `BadGuys[90]` | additive |
| `0x00645B50` | three Mindblast `Clothes[2]` rings | additive |
| `0x00648790` | Explosive Shield `DeadHawg[2]` ring | additive; the separate `BadGuys[15]` `Anim_Fade` remains source-over |

`Anim_FadeScale_Perspective`, `Anim_FadeScaleAdditive_Perspective`, and
`Anim_FadeScale_Clipped` have different vtables and are outside this exact
class census. A renderer that relies on its framework's inherited/default
sprite blend for any row above is not mirroring the shared native painter.

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
mode-specific compact scenery rows. The Boneyard renderer weather owner must
consume the existing scene byte/bounds, use private presentation RNG, place
the exact `DeadHawg:24` splash root before the applicable Region light
composite, place the procedural streak root in its native late lane, and move
the Complex-Lighting-off composite after both. It must synchronize the
existing `rainfall-loop` asset with a distinct Boneyard owner key and must not
touch authoritative simulation RNG or the secondary-ability rain actors.
