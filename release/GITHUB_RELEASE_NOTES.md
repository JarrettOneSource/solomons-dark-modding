# Solomon Dark Multiplayer Beta v0.1.0-beta.33

- Connected clients no longer see or activate the start-run affordance or either boneyard picker. Run and boneyard selection stay with the host, while solo play keeps the same controls.
- Loading Boneyard now seals all gameplay input until the transition finishes, preventing movement, casts, clicks, and menu actions from leaking through the loading screen.
- Player presentation now follows scene epochs: ALLY bars persist across room changes, hub returns rebuild cleanly without detached effects, and local and remote health displays agree.
- Registered custom item icons now render through the native scaled-inventory path.
- Actor-attached visual effects now honor their registered durations instead of collapsing after one frame.
- Hostile target authority is published immediately when a target changes instead of waiting for the next motion interval.
- The loader's bot mana reserve now resumes against 80% of the attainable mana ceiling, including native hoarded-mana limits, rather than an unreachable nominal maximum.
- Multiplayer protocol is now v92.

Download the ZIP. Extract the ZIP. Start `SolomonDarkMultiplayerBeta.exe`.
