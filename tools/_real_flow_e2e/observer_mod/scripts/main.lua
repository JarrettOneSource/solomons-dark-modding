-- Intentionally inert. Enabling this mod gives the harness one ordinary Lua
-- sandbox whose read-only semantic APIs can be queried through the exec pipe.
-- It installs no callbacks, publishes no state, and changes no gameplay.
_G.__real_flow_e2e_observer = true
