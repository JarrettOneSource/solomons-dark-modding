# Invincibility Potion Canary

This runtime Lua mod exercises custom sprite registration, consumable item
registration, the centralized loot pool, stock inventory pickup and use,
replicated consumption events, owner-side resource actions, synchronous damage
and mana filters, local timers, and native player VFX.

The potion is independently rolled for every supported enemy death. It drops
with a 50 percent chance from ordinary enemies and a 100 percent chance from
stock bosses. Drinking it restores the owner's mana, emits the native
`SpellGlow` effect, and grants invincibility plus zero mana spending for three
minutes.

`sprites/invincibility_potion.png` is a manually recolored derivative of the
stock mana-potion bottle. Its bottle geometry and transparency remain
unchanged; only the liquid and highlight palette are baked to bright green.
