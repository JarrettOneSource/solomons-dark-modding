# Native player-chat boundary

Status: **closed negative census**, 2026-08-21. The retail executable does not
own a player-to-player text-chat system. Website `/game` chat is therefore a
designed multiplayer extension, not a port of the native trader `Chat` class.

## Scope and provenance

The analyzed retail target is the unmodified 32-bit `SolomonDark.exe` with
SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`,
preferred image base `0x00400000`, PE timestamp `2016-11-02 11:53:23`. Static
evidence comes from the existing read-only `SolomonDark` Ghidra project and the
settled native input, class, Hub/economy, and audio catalogs. Addresses below
are preferred-image virtual addresses.

The parity question was deliberately wider than the `Chat` name: does retail
own any player-authored text ingress, multiplayer text transport, party/global
recipient policy, scrolling player-message presentation, notification sound,
or lifecycle that Website `/game` should reproduce?

## Evidence

| Evidence class | Exact source | Finding | Confidence |
| --- | --- | --- | --- |
| Native input | `GameWindowProc 0x00443440`, `Input::Refresh 0x00429820`, preset initializer `0x005A8790`, Skills binding global `0x00B3BCC8` | Win32 character messages enter the generic control queue, but gameplay action `T` / DirectInput `0x14` opens SkillScreen. No player-chat action or binding row exists. | high |
| Class/vtable census | `Chat` vtable `0x0079061C`, ctor `0x004F5D90`, update `0x004FFEE0`, render `0x004F9380`; `ChatExtend` vtable `0x00790284` | `Chat` is the trader-conversation modal already recovered in `native-hub-and-economy.md`. `ChatExtend` is installed by the `Boast`, `SellSpell`, and `BookReview` constructors at `0x004F7D20`, `0x004F82D0`, and `0x004FA090`; it is not a network UI. | high |
| String/xref census | read-only Ghidra searches for `chat`, `ChatExtend`, `friend`, `send message`, `receive message`, `lobby`, and `invite` | The only chat-named runtime family is the merchant/dialogue family. No player-chat label, prompt, command, sender/recipient formatter, or lobby-message string has a code owner. | medium-high |
| Steam loader seam | `steamworks_abi.h`, `steam_bootstrap.cpp`, `steam_bootstrap_api.cpp` | `LobbyChatUpdate_t` callback `506` reports lobby membership state changes. The loader imports neither `SteamAPI_ISteamMatchmaking_SendLobbyChatMsg` nor `SteamAPI_ISteamMatchmaking_GetLobbyChatEntry`; it has no lobby-text producer or consumer. | high |
| Audio registry | `native-audio-catalog.json` rows `131` and `150` | `MessageDone__Stream.wav` and `yougotamessage__stream.wav` are compiled streams, but their names and registration alone do not establish player chat and the recovered player-chat census has no consumer tying either asset to one. | high for registry membership; low for any chat interpretation |
| Clean stock controls | settled unmodified-retail SkillScreen capture recorded in `native-input-model.md` and `Website/docs/game-native-parity-re.md` | In both Hub and Boneyard, `T` opens the same SkillScreen; retail exposes no party/global chat surface to observe. | high |

## System boundary and complete membership

Native system queried: **player-authored multiplayer text communication**, from
text input through recipient selection, transport, presentation, and teardown.

| Member | Native source | Disposition | Reason |
| --- | --- | --- | --- |
| Player-authored text command/binding | complete preset/action census at `0x005A8790` | `out-of-system` | Retail has no player-chat action. |
| `T` / DirectInput `0x14` | Skills global `0x00B3BCC8` | `out-of-system` for web chat | It belongs to native SkillScreen. Reassigning it to Website chat is an explicit product override, not native parity. |
| Party/global recipient groups | complete retail and loader network-message census | `out-of-system` | Retail has neither the Website public Hub nor its party model. |
| Player-chat wire payload and history | complete retail and loader message census | `out-of-system` | No stock or loader text lane exists. |
| `Chat` | vtable `0x0079061C` and merchant dialogue call tree | `out-of-system` | Trader-authored question/answer presentation; no player input or network recipient. |
| `ChatExtend`, `Boast`, `SellSpell`, `BookReview` | vtable `0x00790284`; constructors above | `out-of-system` | Merchant/book narrative surfaces, not player chat. |
| `Notebox` | vtable `0x007906DC`, ctor `0x004F63D0`, render `0x004F6740` | `out-of-system` | Local authored-note presentation with no multiplayer text ownership. |
| `LobbyChatUpdate_t` and `chat_permissions` | loader Steam callback ABI | `out-of-system` | Steam's names describe lobby membership permissions/events; no text-message API is loaded. |
| `MessageDone__Stream` / `yougotamessage__stream` | audio registry `131` / `150` | `out-of-system` | Name-adjacent assets with no proved player-chat trigger. |
| Browser HTML `<input>` and IME/Deck text entry | browser platform | `out-of-system` native extension | Required by the accepted browser architecture for user-authored text; there is no native player-chat widget to port. |

No member is `blocked-by-platform`: the absence is in the retail product, not a
browser limitation.

## Recovered contract and implementation consequence

- Retail contributes the general input priority rule: an active text/modal
  surface must own its input so movement, cast, inventory, and menu hotkeys do
  not also fire.
- Retail contributes one conflicting default: `T` opens SkillScreen in both
  gameplay scenes. A Website build that makes `T` open chat must surface that
  visible deviation and keep SkillScreen reachable by its HUD control and a
  declared replacement keyboard key.
- Retail contributes no authority, routing, retention, fade, party/global,
  moderation, or rate-limit constants. Those must be owned by the Website
  protocol/host/UI and must not be presented as recovered stock behavior.
- The native trader `Chat`, its scrolling/timing rules, and the two
  message-named audio streams must not be reused merely because their names
  resemble the requested feature.

## Validation consequence

Website closure requires protocol bounds, authenticated sender identity,
host-owned party/global routing, recipient-isolation tests, local input
exclusion while composing, HTML input/keyboard acceptance, inactivity fading,
and a real multi-client browser journey. A stock-versus-web pixel comparison is
inapplicable because stock has no corresponding player-chat surface; the
stock comparison is instead the explicit `T`-binding deviation above.
