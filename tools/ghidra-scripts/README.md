# Ghidra Headless Replica Pool

The local `SolomonDark` Ghidra project is still a normal on-disk project, so it will lock under concurrent headless use. The supported way to run multiple scans in parallel in this repo is to use the pooled wrapper:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Invoke-GhidraHeadless.ps1 `
  -PreparePool `
  -ReplicaCount 4
```

That creates synchronized read-only replica projects under `Decompiled Game\ghidra_project_replicas\slot-XX`.

Run a scan through the wrapper instead of calling `analyzeHeadless.bat` directly:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Invoke-GhidraHeadless.ps1 `
  -ScriptPath .\tools\ghidra-scripts\decompile_targets.py `
  -ScriptArguments 0x00401000 0x00402000
```

The wrapper:

- acquires a free replica slot with a filesystem lock
- refreshes the replica from the source project when needed
- runs the requested headless script with `-readOnly -noanalysis`
- releases the slot when the scan finishes

Use `-RefreshReplica` after updating the source analyzed project, and `-ClearReplicaLocks` if a previous run crashed and left stale lock files behind.

## Script Hygiene

Keep reusable scripts in this folder with stable, descriptive names and enough
argument handling to run them again later. One-off address probes should use a
`*_tmp.py` suffix while they are still local scratch work; `.gitignore` excludes
that suffix so temporary probes do not become part of the durable tool surface by
accident.
