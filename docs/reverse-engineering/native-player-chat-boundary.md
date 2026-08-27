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

## 2026-08-23 transient world-speech extension

The request to show an authoritative chat message over its sending wizard does
not revise the negative native census. Fresh decompilation of `Chat` update and
render `0x004FFEE0` / `0x004F9380` and `ChatExtend` render `0x004F7BA0`
confirms that those classes remain merchant/book modal presentation. Neither
consumes a player actor, world transform, authenticated sender, or multiplayer
message. `PlayerWizard` world indicators and ExactText remain the closest
native presentation sibling, not a hidden speech system.

The Website extension is therefore bounded as follows:

| Member | Owner and disposition |
| --- | --- |
| Authoritative message receipt and transcript append | Existing protocol-52 client-session and `GameChat`; verified-already-at-requested-policy. The world presentation consumes the same delivered event and never presents an optimistic or rejected draft. |
| Global, Party, and Whisper visibility | Existing host recipient routing; exact-ported product policy. A bubble is only derivable on a client that received that channel event, so Party/Whisper content is not widened. |
| Sender/player binding | Host-authored `message.sender.playerId` joined to the active presented player map; exact-ported authority. The client cannot choose a different actor. |
| Local and remote wizard in the same active region | Website screen-space world-text layer; explicit product extension. Unlike the existing remote-only nameplate, the local sender is included. |
| Hub Courtyard and every private Hub room | Shared Hub renderer plus active-region predicate; explicit product extension. Actors in another Hub region stay absent. |
| Boneyard/Arena | Shared Boneyard renderer; explicit product extension. |
| Missing/disconnected/off-region/invalid actor | No world item; exact lifecycle boundary. Transcript history remains unchanged. |
| Replacement and ordering | At most the newest authoritative sequence per sender; explicit product policy. A newer line replaces the prior line instead of stacking an unbounded actor-local history. |
| Hold/fade/expiry | Client-local monotonic presentation time: 3,000 ms fully visible, then a linear 2,000 ms fade, absent at 5,000 ms; explicit product policy, not a stock constant. |
| Font and projection sibling | Existing native Fonts group 6 ExactText glyph/kerning atlas and post-world screen-space projection; verified-already-at-parity for the primitive. Panel, wrap width, speech-tail geometry, and timing remain declared Website styling. |
| Unsupported glyphs | Omitted without an operating-system-font fallback, matching the native ExactText failure boundary. The complete authoritative message remains in the HTML transcript. |
| Pause, level-up, scene replacement, and teardown | Presentation is nonauthoritative and does not tick simulation. It samples on the scene presentation clock, expires by monotonic wall time, is cleared with session replacement, and owns no save/Lua/snapshot state. |

The layer renders after the world and existing nameplates but before later
screen feedback/modal presentation. It is noninteractive and accessibility
silent because the existing HTML chat live region remains the sole semantic
announcement. No protocol field, server timer, persisted transcript, trader
`Chat` reuse, message-named native stream, or system-font fallback is added.

## 2026-08-27 Website dismissal-lifecycle recheck

Player reports that Escape did not close an open composer after focus left its
text input and that successful submission left the composer open do not reopen
the negative native census. Retail still has no player-authored chat widget,
send transition, or focus policy to extract. The reusable native constraint is
unchanged: the active application/modal owner consumes its control edge before
gameplay, Inventory, Skills, or Pause can also act.

The Website system boundary is nevertheless wider than the earlier input-local
contract. One session-scoped open owner must cover keyboard, touch/HUD, and
Player-Card Whisper entry; focus-independent Escape; Global/Party/Whisper
accepted submission; local and host rejection feedback; own-echo versus remote
unread classification; Hub/Boneyard input exclusion; disabled-state closure;
and session teardown. Escape therefore belongs to the open window at capture
priority, not only to the HTML input. A locally valid submit closes immediately
without creating an optimistic message; the later host-authored own echo still
drives transcript, audio, and world speech once and is not unread. A rejection
must make its status visible again. These are explicit Website product rules,
not recovered retail constants, and require no native address/catalog change.
