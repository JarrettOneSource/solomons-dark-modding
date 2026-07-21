# Native class and object registry

## Scope

The retail executable contains Microsoft C++ RTTI for a large portion of its
native object model. An exhaustive scan of the analyzed executable recovered
598 unique named vtables, 2,699 code references to those vtables, and 13,010
vtable slots. The scan uses a 0x200-byte safety ceiling per table and stops at
the first non-code pointer; this preserves long tables such as
`Skills_Wizard`, whose meaningful overrides continue through `+0xA4`. The
deterministic result is
[`native-class-catalog.json`](native-class-catalog.json), generated from the
headless-Ghidra class scan by `tools/build_native_class_catalog.py`.

This registry is the finite checklist for the gameplay/art investigation. It
prevents a visually obvious class from being documented while a less visible
projectile, status modifier, editor recipe, loot object, or cleanup class is
missed. A vtable reference is evidence that a function touches or installs the
table; it is not automatically labeled a constructor until the function body
is checked. Likewise, slot `+0x08` is often the native tick/update method for
world objects, but that convention is confirmed per hierarchy rather than
assumed globally.

## Recovered families

| Catalog category | Classes | Contents |
| --- | ---: | --- |
| Concrete object or system | 325 | actors, enemies, projectiles, loot, world, boneyard, UI, audio, renderer, and application systems |
| Container specialization | 93 | native arrays, pointer lists, and stacks whose concrete instantiations reveal owned element types |
| Animation or transient effect | 85 | `Anim_*` effects plus the base animation types |
| Actor action | 33 | player cast/melee actions and enemy attack actions |
| Sprite bundle | 28 | one concrete class per shipped atlas |
| Status modifier | 18 | cold, stun, burn, poison, knockback, web, and related gameplay modifiers |
| Item | 16 | item base/definition/recipe/set plus equipment and consumable subclasses |

The 28 `Bundle_*` classes exactly match the 28 shipped atlases, providing an
independent completeness check on the disk inventory. The gameplay-bearing
families include all of the following named roots:

- enemies and enemy-owned world objects: `Badguy`, `Imp`, `Zombie`, `Wraith`,
  `DemonSkull`, `Demon`, `GreenImp`, `DireFaculty`, `Crow`, `Spider`,
  `Skeleton`, `SkeletonArcher`, `SkeletonMage`, `Heartmonger`, `Maggot`,
  `Coffin`, and `Cocoon`;
- player spell/projectile objects: `MagicMissile`, `Fireball`, `Ember`,
  `Meteor`, `MagicCircle`, `PlaneOrb`, `StormCloud`, `MagicTrap`, `AcidRain`,
  `Comet`, `FireMissile`, `BallLightning`, `FrostMissile`, `Fire`,
  `GroundSpark`, `MovingFire`, `Shockwave`, `FreezeWave`, `GuidedMissile`,
  `Earthquake`, `Leviathan`, `Golem`, `EtherDrain`, `Boulder`, `EBoulder`, and
  `Hailstones`;
- additional hostile/transient spell objects: `EvilEmber`, `Firebolt`,
  `EtherBolt`, `DemonBomb`, `UnholySpit`, `EyeLaser`, `RainOfBones`,
  `TragicCircle`, `DarkFireball`, `PoisonPool`, `Silk`, `OffscreenMagic`,
  `GreenFire`, `SkullMissile`, and `DireFire`;
- ground rewards: `Orb`, `Gold`, `Sack`, and `Bonus`;
- world construction: `BoneyardGenerator`, `MonsterRecipe`, `NPCRecipe`,
  `RegionLayout`, `Terrain`, `Road`, `Fence`, `Region`, `TimeLine`, `Trigger`,
  and `ScriptThread`;
- item data/runtime: `Item`, `ItemInfo`, `ItemRecipe`, `ItemSet`, `Item_Hat`,
  `Item_Robe`, `Item_Ring`, `Item_Amulet`, `Item_Staff`, `Item_Wand`,
  `Item_Sack`, `Item_Potion`, `Item_Misc`, `Item_Map`, and `Item_Perk`.

## Spell and projectile object anchors

The table below records the concrete vtable, a constructor/reference anchor,
and the hierarchy's `+0x08` tick/update slot. Destructor and impact/render
slots remain present in the JSON and are being assigned semantic names during
the per-class pass.

| Class | Vtable | Constructor/reference anchor | Tick/update `+0x08` |
| --- | ---: | ---: | ---: |
| MagicMissile | `0x0079C544` | `0x005E0450` | `0x005FD270` |
| Fireball | `0x0079C5BC` | `0x005E0970` | `0x005FDD90` |
| Ember | `0x0079C624` | `0x005E0BD0` | `0x0060D7E0` |
| Meteor | `0x0079C9F4` | `0x005E1540` | `0x00621590` |
| MagicCircle | `0x0079CA64` | `0x005E1BA0` | `0x006006E0` |
| PlaneOrb | `0x0079CC24` | `0x005E2180` | `0x005FB460` |
| StormCloud | `0x0079CC8C` | `0x005E22E0` | `0x006021A0` |
| MagicTrap | `0x0079CD84` | `0x005E2CC0` | `0x00603710` |
| AcidRain | `0x0079CF9C` | `0x005E3540` | `0x00604E90` |
| Comet | `0x0079D304` | `0x005F0C50` | `0x006220D0` |
| FireMissile | `0x0079D5F4` | `0x005E4C50` | `0x005FD550` |
| BallLightning | `0x0079D66C` | `0x005E4F30` | `0x005FD720` |
| FrostMissile | `0x0079D6E4` | `0x005E4FB0` | `0x005FD7A0` |
| Fire | `0x0079D76C` | `0x005E7130` | `0x005FF050` |
| GroundSpark | `0x0079D84C` | `0x005E76F0` | `0x00611EB0` |
| MovingFire | `0x0079D8BC` | `0x005E7890` | `0x005FF870` |
| Shockwave | `0x0079D92C` | `0x005E7A20` | `0x005FF8C0` |
| FreezeWave | `0x0079D994` | `0x005E7B20` | `0x005FFDC0` |
| GuidedMissile | `0x0079DA8C` | `0x005E7E00` | `0x00600B40` |
| Earthquake | `0x0079DB44` | `0x005E8EA0` | `0x00613200` |
| Leviathan | `0x0079DBAC` | `0x005E8FB0` | `0x006145D0` |
| Golem | `0x0079DE94` | `0x005F57E0` | `0x00615CD0` |
| EtherDrain | `0x0079DF1C` | `0x005F8360` | `0x0061CF20` |
| Boulder | `0x0079E014` | `0x005FA270` | `0x00609D30` |
| EBoulder | `0x0079E08C` | `0x005FA670` | `0x00609D30` |
| Hailstones | `0x0079E104` | `0x005FAC20` | `0x005FF5D0` |

The shared `+0x08` value for Boulder and EBoulder is direct evidence that the
ether variant reuses the boulder update implementation while supplying a
different concrete vtable/constructor path. Similar shared slots elsewhere are
inheritance or deliberate behavior reuse, not duplicate catalog entries.

## Enemy, loot, and world anchors

| Class | Vtable | Constructor/reference anchor | Tick/update or primary virtual |
| --- | ---: | ---: | ---: |
| Badguy | `0x00785DAC` | `0x00473390` | `0x004835F0` (`+0x08`) |
| Imp | `0x00785E5C` | `0x00473E30` | `0x00485DC0` (`+0x08`) |
| Zombie | `0x00785F0C` | `0x004740C0` | `0x004863A0` (`+0x08`) |
| Wraith | `0x00785FAC` | `0x00474470` | `0x00486C30` (`+0x08`) |
| DemonSkull | `0x00786074` | `0x00474660` | `0x004963C0` (`+0x08`) |
| Demon | `0x00786114` | `0x00474B40` | `0x00487300` (`+0x08`) |
| DireFaculty | `0x0078626C` | `0x00474E50` | `0x0049D0D0` (`+0x08`) |
| Spider | `0x0078643C` | `0x004759A0` | `0x00489610` (`+0x08`) |
| Skeleton | `0x00786604` | `0x004771B0` | `0x00484B90` (`+0x08`) |
| SkeletonArcher | `0x00786CF4` | `0x0048A6B0` | `0x00485200` (`+0x08`) |
| SkeletonMage | `0x00786DA4` | `0x0048ABB0` | `0x00490860` (`+0x08`) |
| Heartmonger | `0x00786E54` | `0x0048B970` | `0x00489000` (`+0x08`) |
| Orb | `0x0079C8BC` | `0x005E1150` | `0x005E62E0` (`+0x08`) |
| Gold | `0x0079C924` | `0x005E12C0` | `0x005E66B0` (`+0x08`) |
| Sack | `0x0079C98C` | `0x005E1460` | `0x005E6B50` (`+0x08`) |
| Bonus | `0x0079CDEC` | `0x005E2D90` | `0x006039C0` (`+0x08`) |
| BoneyardGenerator | `0x0079E814` | `0x0062DFC0` | `0x0062EF90` (`+0x00`) |
| MonsterRecipe | `0x0079F208` | `0x006400C0` | `0x00644BE0` (`+0x00`) |
| NPCRecipe | `0x0079F2E4` | `0x00640C20` | `0x00646A60` (`+0x00`) |
| RegionLayout | `0x0079F2A4` | `0x006405A0` | `0x0063EA80` (`+0x08`) |
| Terrain | `0x0079F388` | `0x00646A80` | `0x00649CF0` (`+0x00`) |
| Road | `0x0079F33C` | `0x00645470` | `0x006497F0` (`+0x00`) |
| Region | `0x0079F3E4` | `0x0064A5D0` | `0x0063EFC0` (`+0x08`) |

These anchors establish the worklist, not semantic completion. The subsequent
documents join each constructor and virtual method to config parsing, object
fields, atlas records, sounds, collisions, damage/status application, drop
logic, and teardown.

## Custom-content consequence

RTTI proves that native object identity is predominantly compiled into concrete
classes and vtables. Disk art replacement can change presentation, and parsed
CFG/boneyard data can parameterize or instantiate the compiled families, but a
new native projectile/enemy class cannot be introduced by adding an image or a
CFG alone. Lua can compose behavior around exposed factories; adding a truly
new native class would require executable code and registration. This boundary
will drive the later mod manifest and multiplayer compatibility model.
