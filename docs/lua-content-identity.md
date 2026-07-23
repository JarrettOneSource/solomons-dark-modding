# Lua content identity

Scripted spells, enemies, and items share one deterministic identity registry. Mod
authors supply a lowercase content `key`; they never choose a numeric network ID.

## Identity contract

The loader computes a positive 63-bit Lua integer from `(mod_id, key)`:

1. Start FNV-1a-64 with its standard offset basis.
2. Hash the ASCII domain `sd.content.v1`.
3. Hash each UTF-8 string as a little-endian 32-bit byte length followed by its bytes,
   first `mod_id`, then `key`.
4. Keep the low 62 hash bits and set bit 62. This reserves a non-zero positive numeric
   range that round-trips exactly through Lua's integer type.

The content kind is deliberately not part of the hash. A mod cannot reuse one key for a
spell and an item and accidentally give two meanings to the same replicated number.

Fixed vectors:

| Mod ID | Key | Network ID |
|---|---|---:|
| `sample.lua.items` | `golden_focus` | `8108516122269430198` |
| `sample.lua.spells` | `shock_nova` | `6415373166652859851` |
| `sample.lua.enemies` | `grave_tyrant` | `7260085584278011992` |

Both mod IDs and content keys are 1–128 characters. They use lowercase ASCII letters,
digits, `.`, `_`, or `-`, and cannot begin or end with a separator. The launcher rejects
non-canonical manifest IDs before staging. A duplicate key or the vanishingly unlikely
hash collision is a visible registration error; the loader never probes for a different
number because that would make load order affect multiplayer identity.

## Lifecycle

Registration is open only while that mod's entry script is loading. Runtime callbacks
cannot add content after peers have completed their parity handshake. If an
entry script fails, or a mod state closes, all identities owned by that mod are removed.
Engine initialization and shutdown reset the complete registry.

The existing multiplayer handshake already compares the exact enabled manifest/content hash
and loader protocol version. Peers therefore run the same registration code and the
same `sd.content.v1` algorithm before any content ID is carried by a gameplay channel.

The concrete `sd.spells.register`, `sd.enemies.*`, and `sd.items.*` APIs consume this
registry and return the derived ID in their semantic descriptors.

## Native contract check

The small native test compiles the real registry implementation and locks the vectors,
validation, duplicate rejection, cross-kind rejection, lookup, and unload behavior:

```bash
g++ -std=c++17 -pthread \
  -ISolomonDarkModLoader/include \
  SolomonDarkModLoader/src/lua_content_registry.cpp \
  tests/native/lua_content_registry_tests.cpp \
  -o /tmp/lua_content_registry_tests
/tmp/lua_content_registry_tests
```
