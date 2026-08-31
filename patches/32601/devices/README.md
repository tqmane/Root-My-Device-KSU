# KernelSU 32601 device patch sets

These device patch stacks are ports of the device-specific late-load work that
was validated on KernelSU 32525.  The common 32601 base follows the current
WitAqua-tools/Root-My-Device-KSU upstream series for KernelSU v3.3.0, then the
local Asteroids and OnePlus Pad 3 compatibility layers are applied on top.

The ports are intentionally kept separate from the 32525 sets.  Existing
exact-build device pipelines may remain pinned to 32525 until the 32601 build
is verified on hardware; this directory makes the newer KernelSU base
available without silently changing a device-verified runtime contract.

Patch order is lexical within each directory:

- `common/` first;
- then exactly one of `devices/asteroids/` or `devices/oneplus-pad3/`.
