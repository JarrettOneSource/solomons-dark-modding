# Sprite lab assets

Place a `lab.png` atlas here, then build its sibling metadata stream:

```bash
python3 tools/build_lua_sprite_bundle.py \
  mods/lua_sprites_lab/sprites/atlas.example.json \
  mods/lua_sprites_lab/sprites/lab.bundle
```

The example descriptor expects a 32 x 16 PNG containing two 16 x 16 frames.
The sample is disabled and does not ship placeholder art; this keeps authored
images attributable to the mod author instead of silently redistributing stock
game pixels.
