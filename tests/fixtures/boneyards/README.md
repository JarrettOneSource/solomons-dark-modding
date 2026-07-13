# Multiplayer flat-arena fixture

`flat_multiplayer_test.boneyard` is a stock-game custom-boneyard save captured
from the native **Create New Boneyard** workflow. It is kept byte-for-byte so
the multiplayer harness exercises the retail boneyard loader instead of a
loader-owned synthetic map format.

The fixture is used only as an isolated-stage override for the survival level
and the stage-local custom-level source consumed by the multiplayer preset; it
must never overwrite the retail install or the player's custom-level folder.
`flat_multiplayer_test.sha256` pins its exact bytes. The live flat-arena
verifier is responsible for proving that the file loads, exposes traversable
flat test geometry, supports deterministic target placement, and synchronizes
between the host and clients.
