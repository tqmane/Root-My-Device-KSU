#!/usr/bin/env python3
from pathlib import Path
import subprocess


def sh(*args: str) -> None:
    subprocess.run(args, check=True)


def diff_to(path: str, *files: str) -> str:
    result = subprocess.run(
        ["git", "diff", "--", *files],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    Path(path).write_text(result.stdout)
    return result.stdout


# Baseline common + Asteroids 0001..0003 is the parent state for 0004.
sh("git", "add", "-A")

late = Path("userspace/ksud/src/late_load.rs")
src = late.read_text()


def once(old: str, new: str, label: str) -> None:
    global src
    count = src.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, got {count}")
    src = src.replace(old, new, 1)


once(
    "use std::time::Duration;",
    "use std::time::{Duration, Instant};",
    "time import",
)
once(
    'const VECTOR_SOCKET: &str = "/data/adb/lspd/.cli_sock";\n',
    'const VECTOR_SOCKET: &str = "/data/adb/lspd/.cli_sock";\n'
    'const VECTOR_MODULE_ID: &str = "zygisk_vector";\n',
    "Vector module constant",
)

start = src.index("fn stop_stale_vector_launcher() {")
end = src.index("\nfn prepare_vector_service_stage()", start)
src = src[:start] + '''fn stop_stale_vector_launcher() -> Result<()> {
    let Ok(entries) = fs::read_dir("/proc") else {
        return Ok(());
    };
    let mut stale_pids = Vec::new();
    for entry in entries.flatten() {
        let Some(pid) = entry
            .file_name()
            .to_str()
            .and_then(|s| s.parse::<u32>().ok())
        else {
            continue;
        };
        let cmdline = fs::read(entry.path().join("cmdline")).unwrap_or_default();
        let command = String::from_utf8_lossy(&cmdline);
        let comm = fs::read_to_string(entry.path().join("comm")).unwrap_or_default();
        let maps = fs::read_to_string(entry.path().join("maps")).unwrap_or_default();
        if !command.contains("/data/adb/modules/zygisk_vector/daemon")
            && !command.contains("org.matrix.vector.daemon.VectorDaemon")
            && comm.trim() != "vectord"
            && !maps.contains("/data/adb/modules/zygisk_vector/daemon.apk")
        {
            continue;
        }
        warn!("Asteroids late-load: stopping stale Vector launcher pid={pid}");
        match Command::new("/system/bin/kill")
            .args(["-9", &pid.to_string()])
            .status()
        {
            Ok(status) if status.success() => stale_pids.push(pid),
            Ok(status) => warn!("Asteroids late-load: kill pid={pid} exited {status}"),
            Err(err) => warn!("Asteroids late-load: kill pid={pid} failed: {err}"),
        }
    }
    if stale_pids.is_empty() {
        return Ok(());
    }
    let timeout = Duration::from_secs(5);
    let started = Instant::now();
    while started.elapsed() < timeout {
        stale_pids.retain(|pid| Path::new("/proc").join(pid.to_string()).exists());
        if stale_pids.is_empty() {
            info!("Asteroids late-load: stale Vector processes exited");
            return Ok(());
        }
        thread::sleep(Duration::from_millis(50));
    }
    anyhow::bail!(
        "stale Vector processes did not exit within {} seconds: {:?}",
        timeout.as_secs(),
        stale_pids
    )
}''' + src[end:]

once(
    "    stop_stale_vector_launcher();",
    "    stop_stale_vector_launcher()?;",
    "stale Vector cleanup call",
)

start = src.index("fn launch_vector_service_directly() -> Result<()> {")
end = src.index("\nfn verify_vector_framework_cli()", start)
src = src[:start] + '''fn launch_vector_service_directly() -> Result<()> {
    let service_path = Path::new(VECTOR_DIR).join("service.sh");
    info!(
        "Asteroids late-load: launching Vector directly with /system/bin/sh ({}) log={}",
        service_path.display(),
        VECTOR_SERVICE_LOG
    );
    let stdout = fs::File::create(VECTOR_SERVICE_LOG)
        .context("failed to create Vector service launcher log")?;
    let stderr = stdout
        .try_clone()
        .context("failed to clone Vector service launcher log")?;
    let mut child = Command::new("/system/bin/sh")
        .current_dir(VECTOR_DIR)
        .arg(&service_path)
        .envs(crate::module::get_common_script_envs(Some(VECTOR_MODULE_ID)))
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr))
        .spawn()
        .context("failed to spawn monitored Vector service launcher")?;

    let mut clean_exit = None;
    for _ in 0..150 {
        if vector_socket_registered() {
            info!(
                "Asteroids late-load: monitored Vector launcher registered {} (pid={})",
                VECTOR_SOCKET,
                child.id()
            );
            return Ok(());
        }
        if clean_exit.is_none() {
            if let Some(status) = child
                .try_wait()
                .context("failed to query monitored Vector service launcher")?
            {
                if !status.success() {
                    anyhow::bail!(
                        "Vector service launcher exited {status} before registering {VECTOR_SOCKET}; see {VECTOR_SERVICE_LOG}"
                    );
                }
                warn!(
                    "Asteroids late-load: Vector launcher exited cleanly before socket registration; waiting for a detached daemon"
                );
                clean_exit = Some(status);
            }
        }
        thread::sleep(Duration::from_millis(100));
    }
    if let Some(status) = clean_exit {
        anyhow::bail!(
            "Vector service launcher exited {status} but {VECTOR_SOCKET} was not registered within 15 seconds; see {VECTOR_SERVICE_LOG}"
        );
    }
    let pid = child.id();
    let inode_exists = Path::new(VECTOR_SOCKET).exists();
    let _ = child.kill();
    let _ = child.wait();
    anyhow::bail!(
        "Vector service launcher pid={} did not register {} within 15 seconds (inode_exists={}); launcher terminated; see {}",
        pid,
        VECTOR_SOCKET,
        inode_exists,
        VECTOR_SERVICE_LOG
    )
}''' + src[end:]
late.write_text(src)

patch4 = diff_to("/tmp/0004-vector-runtime-recovery.patch", str(late))
print("=== GENERATED 0004 ===")
print(patch4)
sh("git", "add", str(late))

# 0005 is generated relative to the staged 0004 state.
src = late.read_text()
marker = "fn activity_manager_ready() -> bool {"
if src.count(marker) != 1:
    raise SystemExit(f"activity manager marker count={src.count(marker)}")
helper = '''pub(crate) fn run_asteroids_soft_reboot_services() -> Result<()> {
    reset_module_lifecycle_log();
    let previous_system_server = process_id("system_server");
    append_module_lifecycle_log(&format!(
        "soft-reboot service lifecycle begin system_server={previous_system_server:?}"
    ));
    let vector_state = prepare_vector_service_stage()?;
    let verify_vector = match vector_state {
        VectorServiceState::Disabled => {
            init_event::run_stage("service", false);
            false
        }
        VectorServiceState::Running => {
            init_event::run_stage_excluding_module("service", false, VECTOR_MODULE_ID);
            true
        }
        VectorServiceState::NeedsLaunch => {
            init_event::run_stage_excluding_module("service", false, VECTOR_MODULE_ID);
            launch_vector_service_directly()?;
            anyhow::ensure!(
                wait_vector_root_daemon(1),
                "Vector socket disappeared after soft-reboot launch"
            );
            true
        }
    };
    ensure_zygote_boundary_after_services(previous_system_server.as_ref())?;
    if verify_vector {
        verify_vector_framework_cli()?;
    }
    append_module_lifecycle_log("soft-reboot service lifecycle verified");
    Ok(())
}

'''
src = src.replace(marker, helper + marker, 1)

signature = "fn write_module_completion_marker() -> Result<()> {"
if src.count(signature) != 1:
    raise SystemExit(f"write marker signature count={src.count(signature)}")
src = src.replace(
    signature,
    "pub(crate) fn write_module_completion_marker() -> Result<()> {",
    1,
)

dump_marker = "fn dump_process_info(label: &str) {"
if src.count(dump_marker) != 1:
    raise SystemExit(f"dump process marker count={src.count(dump_marker)}")
clear_fn = '''pub(crate) fn clear_asteroids_module_completion_marker() -> Result<()> {
    const MARKER: &str = "/data/local/tmp/.ksu-late-load-modules-ok";
    match fs::remove_file(MARKER) {
        Ok(()) => {
            info!("Asteroids soft-reboot: cleared stale module completion marker");
            Ok(())
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error).context("failed to clear Asteroids module completion marker"),
    }
}

'''
src = src.replace(dump_marker, clear_fn + dump_marker, 1)
late.write_text(src)

init = Path("userspace/ksud/src/init_event.rs")
text = init.read_text()
line = '    run_stage("emulated-soft-reboot", true);'
if text.count(line) != 1:
    raise SystemExit(f"emulated-soft-reboot line count={text.count(line)}")
text = text.replace(
    line,
    "    crate::late_load::clear_asteroids_module_completion_marker()?;\n" + line,
    1,
)
line = "    on_services();"
if text.count(line) != 1:
    raise SystemExit(f"on_services line count={text.count(line)}")
text = text.replace(
    line,
    '    crate::late_load::run_asteroids_soft_reboot_services()\n'
    '        .context("Asteroids module service recovery after soft reboot failed")?;',
    1,
)
line = "    on_boot_completed();"
if text.count(line) != 1:
    raise SystemExit(f"on_boot_completed line count={text.count(line)}")
text = text.replace(
    line,
    line + "\n    crate::late_load::write_module_completion_marker()?;",
    1,
)
init.write_text(text)

patch5 = diff_to(
    "/tmp/0005-soft-reboot-module-recovery.patch",
    str(late),
    str(init),
)
print("=== GENERATED 0005 ===")
print(patch5)
sh("git", "add", str(late), str(init))
sh("git", "diff", "--cached", "--check")
