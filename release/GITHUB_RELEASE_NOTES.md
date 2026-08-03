# Solomon Dark Multiplayer Beta v0.1.0-beta.31

- Hosts choosing a custom boneyard now get a picker drawn in the game's gold font that scales cleanly at any window size. The list stays at the top, with each boneyard's name, description, and updated date below; technical SHA and size details are gone, and the picker is rendered as part of the game frame.
- Ally skill loadouts now replicate completely to other players, so element and discipline choices no longer arrive partial.
- Fixed brief mid-match freezes online, sometimes lasting up to half a second, that were caused by session-status saves blocking the game. Status writes now happen off the game thread.
- Item drops, spell glows, ally health bars, and nametags now render inside the scene at true depth instead of as a screen overlay.
- Assorted launcher wording is cleaner and more concise.
- The release contains no bundled mods or generated runtime residue.

Download the ZIP. Extract the ZIP. Start `SolomonDarkMultiplayerBeta.exe`.
