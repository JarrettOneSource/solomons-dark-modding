# Solomon Dark Multiplayer Beta v0.1.0-beta.23

- FIXED — Internet multiplayer no longer suffers client-side hard lag spikes from app-thread socket starvation and freeze-then-64-packet catch-up bursts. A dedicated bounded receiver queue now feeds a paced 16-packet/2ms apply budget.
- FIXED — Universal 1,200-byte packet framing and reassembly lets large packets survive real internet MTUs. A bounded cumulative-ACK hit-feedback window prevents retransmission amplification, and asynchronous logging removes synchronous flush stalls of up to 180ms. Set `SDMOD_NETWORK_TELEMETRY=1` to write `.sdmod/logs/network-telemetry.jsonl`.
- FIXED — Synthetic gameplay-slot participants now activate their equipped primary and combo progression rows through the stock choice path.
- FIXED — The equipped spell's native effective range, including progression-dependent range, is now exposed through the bot API.
- FIXED — Frost Jet range queries now resolve `mWiden` from live native progression before the first cast instead of reading a dispatch-only actor cache.
- FIXED — The native Frost Jet damage-context branch no longer skips authoritative damage for nonzero gameplay slots.
- The release contains no bundled mods or generated runtime residue.

Download the ZIP. Extract the ZIP. Start `SolomonDarkMultiplayerBeta.exe`.
