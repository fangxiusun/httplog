"""
daemon.py

Daemon process support: double-fork (Unix) / CREATE_NO_WINDOW (Windows).
"""

import atexit
import os
import signal
import sys
import subprocess


def daemonize(pid_file):
    """
    将当前进程转为后台守护进程。

    Linux/macOS: 经典 double-fork
    Windows: 通过 subprocess 重新启动自身并退出父进程
    """
    if sys.platform == "win32":
        _daemonize_windows(pid_file)
    else:
        _daemonize_unix(pid_file)


def _daemonize_unix(pid_file):
    """Unix/Linux/macOS 守护进程化（double-fork）。"""
    # 第一次 fork
    try:
        pid = os.fork()
        if pid > 0:
            # 父进程退出
            sys.exit(0)
    except OSError as e:
        sys.stderr.write(f"[!] fork #1 failed: {e}\n")
        sys.exit(1)

    # 脱离终端
    os.setsid()

    # 第二次 fork
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError as e:
        sys.stderr.write(f"[!] fork #2 failed: {e}\n")
        sys.exit(1)

    # 重定向标准文件描述符
    sys.stdout.flush()
    sys.stderr.flush()

    devnull = open(os.devnull, "r")
    os.dup2(devnull.fileno(), sys.stdin.fileno())
    devnull.close()

    # stdout/stderr 重定向到日志文件旁边的 daemon 输出文件
    daemon_log = pid_file + ".stdout"
    log_fd = open(daemon_log, "a", encoding="utf-8")
    os.dup2(log_fd.fileno(), sys.stdout.fileno())
    os.dup2(log_fd.fileno(), sys.stderr.fileno())
    log_fd.close()

    # 写入 PID 文件
    _write_pid_file(pid_file)

    # 注册退出时清理 PID 文件
    atexit.register(_remove_pid_file, pid_file)


def _daemonize_windows(pid_file):
    """
    Windows 守护进程化。

    通过 subprocess 以 CREATE_NO_WINDOW 重新启动自身，
    将输出重定向到文件，然后退出当前父进程。
    """

    # stdout/stderr 重定向到文件
    daemon_log = pid_file + ".stdout"
    log_fd = open(daemon_log, "a", encoding="utf-8")

    # 重新组装命令行参数，去掉 --daemon 和 --stop
    new_args = [a for a in sys.argv[1:] if a not in ("--daemon", "--stop")]

    # 构建新进程命令
    cmd = [sys.executable, os.path.abspath(sys.argv[0])] + new_args

    # CREATE_NO_WINDOW: 不弹出控制台窗口
    # DETACHED_PROCESS: 脱离当前控制台
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
        # 写入 PID 文件
        _write_pid_file(pid_file, proc.pid)
        print(f"[+] httplog started as daemon (PID: {proc.pid})")
        print(f"[+] Log output: {daemon_log}")
        print(f"[+] PID file: {pid_file}")
        print(f"[+] Stop with: python {sys.argv[0]} --stop --pid {pid_file}")
        log_fd.close()
        sys.exit(0)
    except Exception as e:
        sys.stderr.write(f"[!] Failed to start daemon: {e}\n")
        sys.exit(1)


def _write_pid_file(pid_file, pid=None):
    """写入 PID 文件。"""
    if pid is None:
        pid = os.getpid()
    with open(pid_file, "w") as f:
        f.write(str(pid))
    # 注册退出时清理
    atexit.register(_remove_pid_file, pid_file)


def _remove_pid_file(pid_file):
    """清理 PID 文件。"""
    try:
        if os.path.exists(pid_file):
            os.remove(pid_file)
    except OSError:
        pass


def stop_daemon(pid_file):
    """
    读取 PID 文件并停止对应的后台进程。
    """
    if not os.path.exists(pid_file):
        print(f"[!] PID file not found: {pid_file}")
        sys.exit(1)

    with open(pid_file, "r") as f:
        pid = int(f.read().strip())

    try:
        if sys.platform == "win32":
            # Windows 使用 taskkill
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
        print(f"[+] Sent stop signal to PID {pid}")
    except ProcessLookupError:
        print(f"[!] Process {pid} not found, cleaning up PID file")
        _remove_pid_file(pid_file)
    except Exception as e:
        print(f"[!] Failed to stop process {pid}: {e}")
        sys.exit(1)

    # 清理 PID 文件和 stdout 日志
    _remove_pid_file(pid_file)
    stdout_log = pid_file + ".stdout"
    if os.path.exists(stdout_log):
        print(f"[+] Daemon output log: {stdout_log}")
