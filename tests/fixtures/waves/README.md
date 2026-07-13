# Multiplayer stat-behavior wave fixtures

These deliberately tiny retail `wave.txt` inputs isolate one stock attack
family at a time for multiplayer stat verification:

- `physical_stat_test.txt`: one melee skeleton for Deflect.
- `magic_stat_test.txt`: one fire-casting ranged skeleton mage for Resist Magic.
- `poison_stat_test.txt`: one poison-casting skeleton mage for Resist Poison.

The launcher copies a requested fixture only into each isolated instance stage.
The retail install and normal staged `data/wave.txt` remain untouched.
