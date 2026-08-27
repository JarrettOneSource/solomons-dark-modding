# Native Arena render pipeline

## Scope, source identity, and reopening boundary

This is the low-level pixel-production contract for retail Arena/Boneyard
frames. It begins when `Arena::Render 0x0046EC80` selects renderer state and
ends when that function restores the shared renderer before returning. Scene
membership, painter lanes, sort keys, and camera geometry remain owned by
[`native-scene-composition.md`](native-scene-composition.md); this report owns
what the selected texture, vertex color, primitive, and blend state do to the
pixel.

- Binary: retail `SolomonDark.exe` 0.72.5, 4,723,200 bytes, SHA-256
  `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
- Preferred image base: `0x00400000`.
- Static source: canonical Ghidra 12.0.3 project through the read-only replica
  wrapper. No runtime address or injected observation is used for the formulas
  below.
- Visual falsifier: clean stock Acid Rain capture SHA-256
  `607a697578d1548181e86c8fce82218804f7e99cfcc4bb00ffa06a80bb9227f7`
  against the retained labeled web comparison under
  `/home/user/.codex-artifacts/solomon-dark/acid-rain-comparison-20260826/`.

This reopens the previous G12 completion boundary. The earlier scene report
correctly recovered physical passes, queue order, lighting, transforms, tint,
and blend selectors, but it stopped at the fixed-function color account and
did not trace renderer field `+0x228` into the Direct3D pixel shader. The Acid
Rain correction then matched source records and requested tints while the web
port still brightened those records by `1.12` and never executed the stock
shader. The resulting tests proved the wrong pixel pipeline.

## Complete frame and pixel chart

```text
startup 0x0043FD80
  compile ps_2_0 saturation shader -> DAT_00B401F4
  compile ps_2_0 blur shader       -> DAT_00B401F8

Arena::Render 0x0046EC80
  renderer saturation request +0x228 = 0.65
  state dispatch 0x004208A0 -> c0=0.65, SetPixelShader(saturation)
  reset/paint Region light target
  restore main target
  paint direct underlay and gather shared queue
  multiply Region light target
  flush shared world queue
  paint players, late managers, proxies, foreground, world UI
  modes 1/2: additive player record-18 aperture and optional record-9 target
  paint screen feedback owned inside Arena
  renderer saturation request +0x228 = 1.0
  state dispatch -> SetPixelShader(NULL)
  return; later gameplay HUD/menu code is outside this shader interval

texture page
  PNG decode to unpremultiplied BGRA
  mode-0 A8R8G8B8 upload
  wrap addressing + linear min/mag at the 1:1 retail target ratio
  sprite record UVs / native page handle
  requested color * renderer multiplier -> packed vertex color
  primitive submitter -> saturation shader -> blend selector -> framebuffer
```

The shader is active before the Region target reset and remains active through
the final Arena-owned draw. Nested Arena render-target work therefore inherits
the same state unless a class explicitly replaces the pixel shader. Fixed
Regions, menus, and HUD work after Arena returns are not silently desaturated.

## Exact saturation shader

Initializer `0x0043FD80` compiles the following reachable HLSL as `ps_2_0` and
stores the pixel-shader object at `0x00B401F4`:

```hlsl
sampler DiffuseSampler;
float mSaturation : register(c0);

void main(
    in float2 vTex : TEXCOORD0,
    in float4 vColor : COLOR0,
    out float4 oCol : COLOR0)
{
    oCol = tex2D(DiffuseSampler, vTex);
    float4 aRealCol = oCol * vColor;
    float aVGrey = (vColor.r + vColor.g + vColor.b) / 3;
    float aGrey = (oCol.r + oCol.g + oCol.b) / 3;
    oCol.rgb = aVGrey * aGrey;
    oCol.rgb = lerp(oCol.rgb, aRealCol.rgb, mSaturation);
    oCol.a = vColor.a * oCol.a;
}
```

`Arena::Render` loads float `0.65` from `0x00784DC0` at `0x0046EC9A`, writes
it to the renderer request at `0x0046ECA9`, and dispatches it at
`0x0046ECB7`. It writes `1.0` at `0x00470A6A` and dispatches the restore at
`0x00470A76` immediately before return.

For sampled unpremultiplied texture RGB `T`, vertex RGB `V`, and saturation
`s = 0.65`, the exact Arena RGB is:

```text
textureGrey = (T.r + T.g + T.b) / 3
vertexGrey  = (V.r + V.g + V.b) / 3
real        = T * V
grey        = textureGrey * vertexGrey
out.rgb     = grey * (1 - s) + real * s
out.a       = textureAlpha * vertexAlpha
```

This is not a post-composite CSS saturation filter. It runs once per submitted
fragment before source-alpha/additive/multiply composition, and its grey term
is the product of the two separate averages rather than the average of the
already tinted RGB. A correct web shader must retain texture RGB, vertex RGB,
and alpha as separate inputs until this formula has run.

The sibling blur shader at `0x00B401F8` is also compiled by `0x0043FD80`.
Renderer field `+0x230` would select it through `0x00442AF0`, supplying blur
amount at `c0` and reciprocal texture dimensions at `c1/c2`. The complete
game-wide census in
[`native-full-render-pipeline.md`](native-full-render-pipeline.md) proves the
request remains constructor-zero and has no retail writer. Its source loops
`aU=-3..2`, accumulates four samples per iteration, and divides the resulting
24 samples by 20; it is a dormant 1.2-gain cross-blur capability, not an active
Arena/Acid or other stock-scene pass.

## Texture, sampler, color, primitive, and blend contract

### Texture representation

Shared page loader `0x00420140` decodes the retail PNG page into ordinary
unpremultiplied BGRA and, with `Graphics.SaveVideoMemory=false` and no
preconverted page, uploads mode zero through `0x00440F70` as 32-bit
A8R8G8B8. It does not premultiply RGB by alpha. Atlas records retain UVs into
the original page; they are not independent clamp-to-edge textures.

Renderer reset `0x0041D000` selects wrap addressing on U/V and, when render
target/backbuffer ratios are both one, Direct3D linear minification and
magnification. Retail `1600 x 900` Acid comparison uses this 1:1 linear path.
Text-specific callers may temporarily select point filtering through
`0x00421560`; none of Acid Rain's parent, drop, splash, or residue painters do.

### Requested and effective color

`0x0041FE50` stores requested RGBA at renderer `+0x1EC..+0x1F8`, multiplies it
by the current global color at `+0x20C..+0x218`, and packs the effective value
at `+0x21C`. Textured sprite/mesh vertices consume the packed color.
`0x0041FF60` changes the global multiplier and rebuilds the effective color.

`Glyph_Draw 0x004143D0` and transformed painter `0x00414540` bind the sprite's
native page through `0x00420030`, emit its four UV/position pairs through
`TextQuad_Draw 0x0041E990`, then join the shared buffered draw. Arbitrary
textured quads use `0x00414710`. Solid and vertex-colored primitives use the
neighboring `0x0041DD70` and `0x0041DF10` paths.

`0x0041DF10` is a real four-vertex color quad, not a sampled gradient texture.
It writes the first RGBA to the top pair and the second RGBA to the bottom pair;
the rasterizer interpolates those vertex values before the Arena saturation
shader. Acid Rain and Magic Storm falling streaks are members of this path.

### Renderer selectors

State dispatcher `0x004208A0` flushes buffered primitives before changing a
requested state. Its exact blend table is:

| Selector | Direct3D source | Direct3D destination | RGB result |
| ---: | --- | --- | --- |
| `0` | `SRCALPHA` | `INVSRCALPHA` | ordinary source-over |
| `1` | `SRCALPHA` | `ONE` | additive |
| `2` | `ZERO` | `SRCCOLOR` | `destination * sourceColor` |

Selector `+0x223` controls the fixed-function texture-stage color/alpha
operation. The custom Arena pixel shader owns texture/color math while bound;
the fixed-function selector remains relevant to draws outside that interval or
to paths that explicitly replace the pixel shader. Requested texture address,
saturation, blur, and cached values are independently tracked; a state change
never retroactively changes already buffered vertices.

## Primitive xref closure

[`native-render-pipeline-callers.json`](native-render-pipeline-callers.json)
is the machine-complete preferred-address census generated from the canonical
project by
[`catalog_renderer_callers.py`](../../tools/ghidra-scripts/catalog_renderer_callers.py).
It contains every direct reference and exact callsite for all recovered shared
pipeline functions. Summary:

| Native member | Direct references | Containing callers |
| --- | ---: | ---: |
| `Glyph_Draw 0x004143D0` | 386 | 152 |
| transformed sprite `0x00414540` | 126 | 69 |
| scaled/positioned sprite `0x00414EA0` | 315 | 118 |
| arbitrary textured quad `0x00414710` | 18 | 13 |
| solid quad `0x0041DD70` | 152 | 74 |
| vertex-colored quad `0x0041DF10` | 57 | 21 |
| final textured quad `0x0041E990` | 35 | 26 |
| requested/effective color `0x0041FE50` | 1,287 | 300 |
| global color multiplier `0x0041FF60` | 134 | 70 |
| texture binder `0x00420030` | 56 | 50 |
| renderer state dispatcher `0x004208A0` | 439 | 160 |
| point/linear selector `0x00421560` | 78 | 34 |
| buffered flush `0x0041D8F0` | 98 | 46 |
| shader initializer `0x0043FD80` | 1 | 1 |
| `Arena::Render 0x0046EC80` | one Arena-vtable row | zero direct calls |
| Region multiply `0x0057D670` | 2 | Arena only |

The catalog preserves the Arena vtable reference at `0x00785940` as an orphan
data xref rather than inventing a direct caller. No xref or callsite is omitted
from the machine inventory.

## Arena membership and downstream consequence

| Arena pixel member | Native disposition | Web consequence |
| --- | --- | --- |
| direct underlay, terrain, compact scenery, fences, and ground effects | saturation shader, unpremultiplied page samples, linear filtering | remove the browser `brightness(1.12)` preprocessing and nearest runtime textures; run the exact shader |
| world-sorted players, enemies, loot, projectiles, spells, secondary abilities, and mod carriers | same shared pixel path after object-local tint | one Arena-owned shader/batcher must cover every ordinary/additive member; Acid-only color tuning is invalid |
| Acid/Storm falling rain | four interpolated vertex colors through `0x0041DF10` | retain true vertex colors or an algebraically identical linear program; do not use a color-picked texture substitute |
| custom Building surface mesh | texture plus per-vertex grayscale lighting under the same shader | extend the Building shader with the exact Arena formula |
| Region light stamps and multiply | shader-active but white/grayscale, so saturation is an identity; selector two performs exact framebuffer multiply | existing Region ownership/order remains; do not desaturate the completed framebuffer afterward |
| black complex-shadow meshes | shader-active but black, so saturation is an identity | existing geometry/alpha remains |
| weather streaks | grayscale vertex tint over a white alpha ramp, so saturation is an identity | existing particle batch remains; colored splashes still use the Arena pixel path |
| nested Storm/Leviathan and other Arena render targets | inherit the active shader unless their native path replaces it | web nested renders must use the Arena pixel program at the same render epoch |
| mode-1/2 direct player aperture | late additive grayscale record 18, native alpha `.2375..25` | remove the explicit Website `0.14` brightness scale; grayscale makes saturation an identity, not permission to dim it |
| Arena screen feedback before return | active shader | keep on the Arena canvas/program |
| gameplay HUD, fixed Regions/Hub, menus after Arena return | shader restored to identity | out of this Arena-saturation implementation; do not apply a canvas-wide CSS filter to them |
| blur shader | separate requested state, not selected by Arena entry/Acid | out of this correction; preserve as a distinct renderer capability |

There is no browser platform blocker: WebGL2 represents the stock formula,
unpremultiplied sampling, linear filtering, vertex colors, and all three blend
equations directly. The 2026-08-27 Website handoff now applies this contract
to its Arena batch, Graphics, Mesh, particle, Building, and nested-target
families; its authoritative ledger owns the separate Mac/browser receipts.

## Acid Rain prediction

Acid's parent requested tints and assets recovered in
[`native-projectiles-and-effects.md`](native-projectiles-and-effects.md) remain
correct inputs. They were never the final visible colors. For a white cloud
texel under first-pass tint `(0.41,0.55,0.32)`, the shader moves the RGB to
approximately `(0.416,0.507,0.357)` before source-over/additive composition.
For the falling bottom color `(0.7,0.95,0.75)`, it produces approximately
`(0.735,0.898,0.768)`. These desaturated results predict the softer, paler
stock capture and falsify the current bright green web output without a tuned
Acid constant.
