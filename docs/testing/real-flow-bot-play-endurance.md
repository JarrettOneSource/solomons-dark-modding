# Real-network Bot Play endurance mode

`tools/verify_real_flow_e2e.py` supports an opt-in endurance mode for the real
Home PC-to-workstation20 Steam topology. It extends the existing desktop
launcher, lobby-ID join, native Start Match, and stock Solomon Dig flow. It
does not add a gameplay shortcut.

Set both `botPlayForMe` and `enduranceMode` to `true`. The controller stages
`mods/bot-brain` from the selected source checkout on both peers, enables the
local-player takeover through the mod's persisted settings and settings reload
path, and leaves the synthetic bot roster empty. Thus the two network
participants are the only fighters. `botPlayBehavior` selects the same
`skirmisher`, `guardian`, `striker`, or `learned` local setting on both peers
and defaults to `skirmisher`. `enduranceMaxSeconds` is bounded from 60
through 5,400 seconds; reaching the cap ends the owned staged processes
cleanly, while a mutually accepted native Game Over ends the run naturally.

For a workstation that cannot reach the directory service, set
`clientDirectoryUrl` to an explicit loopback URL so only the client-side
production offline-fallback path fails locally instead of contacting the
filtered website. The HomePC host retains `directoryUrl`. Join by Steam lobby
ID and keep the exact host mod set pre-staged; unpublished mods are never
downloaded.
`reuseWs20Prestage` may be set only for the workstation20 topology after the
stage has been hash-checked and contains `prestage/launcher` plus
`prestage/game`. The run still deletes that exact owned stage during cleanup.

The endurance evidence adds:

- `timeline.jsonl`, with both peers' wave, HP, position, actors, packet counts,
  Steam failure counters, death state, loading barrier, and terminal state;
- `endurance-events.jsonl`, with death/respawn transitions, screenshot
  milestones, and live anomaly findings;
- `endurance-damage.jsonl`, with authority-observed per-fighter damage edges;
- paired captures at waves 1, 2, 3, 5, and each fifth wave thereafter, plus a
  terminal or wall-clock capture;
- per-fighter damage, damage taken, deaths, respawns, distance, and furthest
  wave in `result.json`; and
- both peers' mandatory `SDMOD_NETWORK_TELEMETRY=1` streams, transport
  accounting, exact-process cleanup proof, and the evidence SHA-256 manifest.

The live anomaly monitor uses sustained thresholds for scene/wave divergence,
transport loss, packet stalls, client materialization loss, stopped takeover,
brain-think stalls, idle/stuck/oscillating movement, sustained accepted casts
without enemy HP progress, and any Steam send failure. Receive progress is
tracked independently in each direction, so continuing outbound traffic
cannot hide a one-way stall. Screenshot failures and missed milestones are findings rather than
silent omissions. Findings remain evidence; they do not authorize a blind
product patch. Diagnose them from the aligned timeline, loader logs, network
telemetry, bot probes, and captures, then rerun from a new evidence root after
any product fix.

The workstation controller accepts one new direct profile child matching
`%USERPROFILE%\sd-<token>-stage`. It copies evidence home, closes only exact
recorded PIDs beneath that stage, delists the owned lobby through the normal
launcher/game shutdown, and deletes the complete stage. A pre-existing stage,
unexpected process, scheduled task, or missing logged-in Steam process blocks
the run.

Use `tools/real_flow_e2e_endurance_ws20.example.json` as the template. Replace
all paths, SSH values, run names, and `expectedSourceSha`; keep each evidence
and staging root new.
