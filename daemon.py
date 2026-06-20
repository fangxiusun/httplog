"""
daemon.py

Daemon process support: double-fork (Unix) / CREATE_NO_WINDOW (Windows).
"""

import os
import signal
import sys
import subprocess


def daemonize(pid_file):
    """
    Convert current process to a background daemon.

    Linux/macOS: classic double-fork
    Windows: subprocess with CREATE_NO_WINDOW
    """
    if sys.platform == "win32":
        _daemonize_windows(pid_file)
    else:
        _daemonize_unix(pid_file)


def _daemonize_unix(pid_file):
    """Unix/Linux/macOS daemonization (double-fork)."""
    # First fork
    try:
        pid = os.fork()
        if pid > 0:
            # parent exits immediately (no atexit, no cleanup needed)
            os._exit(0)
    except OSError as e:
        sys.stderr.write(f"[!] fork #1 failed: {e}\n")
        sys.exit(1)

    # Become session leader
    os.setsid()

    # Second fork
    try:
        pid = os.fork()
        if pid > 0:
            # child1 exits immediately (no atexit)
            os._exit(0)
    except OSError as e:
        sys.stderr.write(f"[!] fork #2 failed: {e}\n")
        sys.exit(1)

    # child2 (final daemon process) continues here

    # Redirect standard file descriptors
    sys.stdout.flush()
    sys.stderr.flush()

    devnull = open(os.devnull, "r")
    os.dup2(devnull.fileno(), sys.stdin.fileno())
    devnull.close()

    # Redirect stdout/stderr to daemon log file
    daemon_log = pid_file + ".stdout"
    log_fd = open(daemon_log, "a", encoding="utf-8")
    os.dup2(log_fd.fileno(), sys.stdout.fileno())
    os.dup2(log_fd.fileno(), sys.stderr.fileno())
    log_fd.close()


def _daemonize_windows(pid_file):
    """
    Windows daemonization.

    Restart self via subprocess with CREATE_NO_WINDOW, then exit parent.
    """
    daemon_log = pid_file + ".stdout"
    log_fd = open(daemon_log, "a", encoding="utf-8")

    # Rebuild command line, replace --daemon with --_daemon-child, remove --stop
    new_args = []
    skip_next = False
    for i, a in enumerate(sys.argv[1:]):
        if skip_next:
            skip_next = False
            continue
        if a == "--stop":
            continue
        if a == "--daemon":
            new_args.append("--_daemon-child")
        else:
            new_args.append(a)
    cmd = [sys.executable, os.path.abspath(sys.argv[0])] + new_args

    CREATE_NO_WINDOW = 0x08000000
    DETACHED_PROCESS = 0x00000008

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=log_fd,
            stderr=log_fd,
            stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
        )
        print(f"[+] httplog starting as daemon (PID: {proc.pid})")
        print(f"[+] Log output: {daemon_log}")
        print(f"[+] PID file: {pid_file}")
        print(f"[+] Stop with: python {sys.argv[0]} --stop --pid {pid_file}")
        log_fd.close()
        sys.exit(0)
    except Exception as e:
        sys.stderr.write(f"[!] Failed to start daemon: {e}\n")
        sys.exit(1)



def check_existing_instance(pid_file):
    """
    Check if another instance is already running based on PID file.
    Returns True if safe to proceed, False if another instance is running.
    """
    if not os.path.exists(pid_file):
        return True

    try:
        with open(pid_file, "r") as f:
            pid = int(f.read().strip())
    except (ValueError, OSError):
        # Corrupted PID file, clean up
        try:
            os.remove(pid_file)
        except OSError:
            pass
        return True

    # Check if process is alive
    try:
        if sys.platform == "win32":
            # Windows: use tasklist to check
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True, text=True, timeout=5
            )
            alive = str(pid) in result.stdout
        else:
            # Unix: signal 0 checks existence without killing
            os.kill(pid, 0)
            alive = True
    except (ProcessLookupError, OSError):
        alive = False
    except subprocess.TimeoutExpired:
        alive = False

    if alive:
        print(f"[!] Another instance is already running (PID: {pid})")
        print(f"[!] Stop it first with: python {sys.argv[0]} --stop --pid {pid_file}")
        return False

    # Stale PID file, clean up
    print(f"[*] Found stale PID file (process {pid} not running), cleaning up")
    try:
        os.remove(pid_file)
    except OSError:
        pass
    stdout_log = pid_file + ".stdout"
    if os.path.exists(stdout_log):
        try:
            os.remove(stdout_log)
        except OSError:
            pass
    return True

def write_pid_file(pid_file, pid=None):
    """Write PID to file. No atexit registration."""
    if pid is None:
        pid = os.getpid()
    with open(pid_file, "w") as f:
        f.write(str(pid))


def remove_pid_file(pid_file):
    """Remove PID file if it exists."""
    try:
        if os.path.exists(pid_file):
            os.remove(pid_file)
    except OSError:
        pass


def stop_daemon(pid_file):
    """
    Read PID file and stop the corresponding daemon process.
    """
    if not os.path.exists(pid_file):
        print(f"[!] PID file not found: {pid_file}")
        sys.exit(1)

    with open(pid_file, "r") as f:
        pid = int(f.read().strip())

    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
        print(f"[+] Sent stop signal to PID {pid}")
    except ProcessLookupError:
        print(f"[!] Process {pid} not found, cleaning up PID file")
        remove_pid_file(pid_file)
    except Exception as e:
        print(f"[!] Failed to stop process {pid}: {e}")
        sys.exit(1)

    # Clean up PID file
    remove_pid_file(pid_file)
    stdout_log = pid_file + ".stdout"
    if os.path.exists(stdout_log):
        print(f"[+] Daemon output log: {stdout_log}")
