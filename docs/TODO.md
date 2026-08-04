# TODO — Polish & Feature Backlog

Owner-curated backlog, recorded 2026-08-04 so ideas aren't lost. Items graduate into a
design doc + campaign when the owner pulls the trigger. Active bug campaigns are tracked
on the fleet board, not in this file.

## 1. Lobby-mod presentation in the launcher (untriggered)

Session-scoped mods staged for a hosted lobby (host-transferred, website-downloaded, or
reused from cache) should surface at the top of the launcher mod list with a distinct
visual treatment showing they are lobby-specific: enabled for this session only and
dropped automatically when the lobby ends. The data layer is already session-scoped
(validated cache promotion + session-scoped catalog, `docs/design/mod-transfer-seam.md`);
the remaining work is launcher UI presentation.

## 2. Consent for cached lobby mods (untriggered; caching itself already shipped)

Verified in beta.32 code: host-transferred packages are promoted into the validated
launcher cache and reused without re-download —
`HostModTransferClient.DownloadAndInstallAsync` consults
`WebsiteModPackageInstaller.GetCachePath`/`TryLoadExact` before requesting a single
chunk, and join preview classifies such mods `Cached`. However, the join consent prompt
only opens when the preview's `DownloadCount > 0` (`MainWindowViewModel`), so a joiner
whose needed lobby mods are all cached is staged session-scoped with no consent surface
("Your mods already match the host."). Polish: always show the lobby-mods prompt when
session-scoped mods will be enabled — zero-download joins included — with wording like
"(from your cache)", folded into the item-1 lobby-specific presentation.

## 3. Website Boneyard editor: native scripting support (untriggered)

Expand the website Boneyard editor to author the newly recovered retail scripting layer
(`docs/reverse-engineering/boneyard-scripting.md`): triggers (15 types, 14 predicates,
92 unique actions), TimeLine graphs (event kinds 0–6, spawn records 3001–3003), and the
five recipe stores (MonsterRecipe / UIDGroup / ItemRecipe / NPCRecipe / ItemSet).
`tools/decode_boneyard_scripts.py` holds the proven grammar; the missing pieces are
round-trip encode plus editor UX.

## 4. Multiplayer security audit (owner-owned)

Prove players are safe in multiplayer: no memory-writing tools or exploits reachable
from a session. Surfaces to check when this runs: the `sd.debug` write/call primitives
(`docs/lua-memory-tooling.md`) and which capabilities a host-supplied,
consent-downloaded mod can obtain on a joiner (the trust-tier question,
`docs/lua-seam-roadmap.md` §6) — raw memory access must be ungrantable without explicit
local opt-in; the bounded native packet families and the transfer path's
size/path/digest bounds (`docs/design/mod-transfer-seam.md`); and the exact-parity
handshake as the mismatched-content backstop.
