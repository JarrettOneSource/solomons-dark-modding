# Headless simulation

Launch an isolated single-player instance with:

```powershell
./dist/launcher/SolomonDarkModLauncher.exe launch --headless --multiplayer off
```

The desktop launcher exposes the same option under **Headless simulation**.
The setting applies only to its single-player launch button.

## Contract

Headless mode:

- starts the process hidden and keeps its top-level window hidden;
- disables the stock BASS audio device through the existing launch-audio seam;
- allows the hidden stock renderer to build menu and hub controls for automation,
  then sets MyApp's render-skip counter in simulation scenes so the render
  virtual at vtable offset `+0xE0` is not called there; and
- runs the stock fixed-step simulation virtual at vtable offset `+0xDC` in
  adaptive batches sized for roughly 250 ms of work.

The legacy game still creates its hidden Win32 window and D3D9 device because
other engine systems assume those objects exist. Menus and the hub render
off-screen so semantic UI automation remains usable; active simulation scenes
do not render. This is not a separate dedicated-server executable.

Headless mode is single-player only. The launcher rejects `--multiplayer host`
and `--multiplayer join`; those transports use real wall-clock cadence and
cannot remain deterministic while one peer runs ahead.

## Precision

MyApp's `FUN_0040D3C0` scheduler normally converts elapsed wall time into
100 fixed simulation steps per second. It also contains a stock batch field at
`MyApp+0xD9C`: after one due step, values above one call the same simulation
virtual repeatedly without changing its delta.

Before each headless app tick, the loader rebases only the scheduler-private
baseline and counter in active simulation scenes so exactly one stock due slot
is available, then writes the adaptive batch count. Menus, transitions, the hub,
and shops retain stock pacing. The stock function executes that many ordinary
fixed steps. The loader does not change:

- the 100 Hz timing/conversion globals;
- any gameplay delta or floating-point mode;
- RNG state or call order inside a simulation step; or
- the simulation virtual itself.

Batch size changes throughput, not the arithmetic performed by a step.

## Diagnostics

The loader startup status contains:

```json
{
  "headlessSimulationEnabled": true
}
```

The launcher repeats this as `launch.headlessSimulationEnabled`. The loader log
reports measured fixed steps per wall-clock second every two seconds:

```text
Headless simulation throughput=... fixed_steps_per_second batch=... stock_step_hz=100 precision=unchanged.
```
