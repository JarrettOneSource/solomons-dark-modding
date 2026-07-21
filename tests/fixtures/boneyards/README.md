# Multiplayer flat-arena fixture

`flat_multiplayer_test.boneyard` is a stock-game custom-boneyard save captured
from the native **Create New Boneyard** workflow and saved before placing any
editor prop. It is kept byte-for-byte so the multiplayer harness exercises the
retail boneyard loader instead of a loader-owned synthetic map format.

It contains a valid 7,721-chunk SyncBuffer with the 13-section Arena and
14-section RegionLayout envelopes. Its placed-object lists are empty, but its
single stock default TimeLine occupies 7,662 chunks. Zero bytes are therefore
not a valid stand-in for a blank Boneyard.

The retail run generator decorates even this empty editor source with trees,
gravestones, fence pieces, gates, roads, goodies, and sometimes buildings. Test
launches therefore opt into `SDMOD_TEST_BLANK_BONEYARD=1`. That explicit mode
removes only the generator-owned scenery, road, and fence pointer lists through
their native removal/destructor ABI, unregisters the corresponding static
movement circles, and retires the stock `Solomon_Dig` intro controller and its
lantern through the native actor lifecycle before their first tick. Ordinary
custom boneyards remain untouched.

The fixture is used only as an isolated-stage override for the survival level
and the stage-local custom-level source consumed by the multiplayer preset; it
must never overwrite the retail install or the player's custom-level folder.
`flat_multiplayer_test.sha256` pins its exact bytes. The live flat-arena
verifier is responsible for proving that the file loads on both peers, exposes
traversable flat test geometry, starts without replicated gameplay actors beyond
the two players, has zero remaining scenery/road/fence objects or static
movement circles, has no scripted intro setpiece or input gate, renders without
gravestones, trees, fences, gates, lanterns, or buildings, supports deterministic
target placement, and synchronizes between the host and clients.
