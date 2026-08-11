# `devices`

One directory per build that needs a delta no other build does, named after the
`id` in the `kernelsu.json` that asks for it — `devices/<id>` — and selected as
`devices/<id>` in that file's `patchSets`.

Keyed by build id rather than by device, because that is what a module is: two
targets which load the same module share one id and one build, so a patch keyed
to only one of them could not be honoured. A delta that genuinely applies to one
of them and not the other means they are different modules and want different
ids.

There are currently two device sets, `quest3` and `asteroids`, and the list
should stay small. A patch here is one nothing else can use, so reach for it
only after `common` and the vendor sets have been ruled out. As with any set, a
`devices/<id>` with no patches in it fails the build that names it rather than
being quietly skipped.

`quest3` is upstream `953b403a` backported onto this version: it keeps the
tracepoint mark on `/system/bin/stub_zygote`, which is how Meta's Horizon OS
starts the zygote. Unmarking the stub unmarks the zygote and every application
forked from it, so no KernelSU hook fires for any of them. That survives a boot
-- the module marks the running processes as it loads -- and does not survive
`ksud soft-reboot`.

`asteroids` completes the explicit late module path for Nothing Phone (3).
After common has run each module's late-load-compatible pre-zygote script,
loaded `system.prop`, established the metamodule/OverlayFS view and completed
`post-mount`, this set recreates the missing zygote-start boundary by restarting
the zygote init service. It then waits for a **new** `system_server` before the
service stage is launched. The policy is tied to the explicit `--modules`
request rather than to one hard-coded Zygisk module ID, so NeoZygisk/Zygisk
provider names can change without silently disabling injection. A live zygote
restart is intentionally not a common late-load policy.

These live here rather than beside the target in the consuming repository for
the same reason the rest do: they are a derivative work of KernelSU and carry
its licence, which is not the licence of the repository that builds them.
