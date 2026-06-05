#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
httplog.py

一个简单的 HTTP 请求记录服务器。

功能：
1. 接收任意 HTTP 方法
2. 记录客户端 IP、端口、请求行、Header、Query、Body 等信息
3. /echo 返回请求信息
4. 自动按天分日志文件，支持 strftime 路径模板
5. 支持插件机制，可根据请求信息自定义返回

运行：
    python httplog.py
    python httplog.py --host 0.0.0.0 --port 8080 --log httplog.jsonl  # auto: httplog-2025-06-05.jsonl
    python httplog.py --daemon                      # 后台运行
    python httplog.py --daemon --pid httplog.pid
    python httplog.py --log-viewer /logs     # 后台运行并写入 PID 文件
    python httplog.py --stop --pid httplog.pid       # 停止后台进程

访问：
    curl http://127.0.0.1:8080/echo
    curl -X POST http://127.0.0.1:8080/test -H "Content-Type: application/json" -d '{"hello":"world"}'
"""

import argparse
import atexit
import base64
import datetime
import json
import os
import signal
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs


# =========================
# 全局配置
# =========================

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080
DEFAULT_LOG_FILE = "httplog.jsonl"  # auto split by day: httplog-2025-06-05.jsonl
DEFAULT_PID_FILE = "httplog.pid"

# 最大读取 Body 大小，防止超大请求撑爆内存
MAX_BODY_SIZE = 10 * 1024 * 1024  # 10MB


# =========================
# 守护进程支持
# =========================

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

    # stdout/stderr 重定向到日志文件旁边的 daemon 输出文件
    daemon_log = pid_file + ".stdout"
    log_fd = open(daemon_log, "a", encoding="utf-8")
    os.dup2(log_fd.fileno(), sys.stdout.fileno())
    os.dup2(log_fd.fileno(), sys.stderr.fileno())

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
    import subprocess

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
            os.system(f"taskkill /PID {pid} /F")
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


# =========================
# 插件机制
# =========================

PLUGINS = []


def plugin(func):
    """
    插件装饰器。

    插件函数接收 request_info，返回 None 或 response。

    返回 None：
        表示不处理，继续交给后续插件或默认逻辑。

    返回 dict：
        {
            "status": 200,
            "headers": {"Content-Type": "application/json"},
            "body": "hello"
        }

    body 可以是：
        - str
        - bytes
        - dict/list，会自动转 JSON
    """
    PLUGINS.append(func)
    return func


# =========================
# 示例插件
# =========================

@plugin
def example_block_ip_plugin(request_info):
    """
    示例：按 IP 拦截。

    如果要启用，把 127.0.0.1 改成你想拦截的 IP。
    当前示例默认不拦截任何 IP。
    """
    blocked_ips = {
        # "127.0.0.1",
    }

    client_ip = request_info["client"]["ip"]

    if client_ip in blocked_ips:
        return {
            "status": 403,
            "headers": {
                "Content-Type": "application/json; charset=utf-8"
            },
            "body": {
                "ok": False,
                "message": "Forbidden by IP plugin",
                "client_ip": client_ip,
            }
        }

    return None


@plugin
def example_custom_path_plugin(request_info):
    """
    示例：自定义路径返回。

    请求：
        GET /hello

    返回：
        {"message": "hello from plugin"}
    """
    path = request_info["url"]["path"]

    if path == "/hello":
        return {
            "status": 200,
            "headers": {
                "Content-Type": "application/json; charset=utf-8"
            },
            "body": {
                "ok": True,
                "message": "hello from plugin"
            }
        }

    return None


@plugin
def example_body_keyword_plugin(request_info):
    """
    示例：根据 Body 内容自定义返回。

    如果 Body 文本中包含 ping，则返回 pong。
    """
    body_text = request_info["body"].get("text", "")

    if "ping" in body_text.lower():
        return {
            "status": 200,
            "headers": {
                "Content-Type": "application/json; charset=utf-8"
            },
            "body": {
                "ok": True,
                "message": "pong"
            }
        }

    return None


# =========================
# 工具函数
# =========================

def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()


def format_daily_log_path(log_pattern):
    """
    daily log path with strftime support.

    1. pattern with strftime placeholders (%Y, %m, %d): format directly
    2. no placeholders: insert -YYYY-MM-DD before file extension

    examples:
        httplog.jsonl              -> httplog-2025-06-05.jsonl
        logs/httplog.jsonl         -> logs/httplog-2025-06-05.jsonl
        httplog-%Y%m.jsonl         -> httplog-202506.jsonl
    """
    now = datetime.datetime.now()

    # strftime placeholders present: format directly
    if '%Y' in log_pattern or '%m' in log_pattern or '%d' in log_pattern:
        return now.strftime(log_pattern)

    # no placeholders: insert date before extension
    date_str = now.strftime('%Y-%m-%d')
    dot_idx = log_pattern.rfind('.')
    if dot_idx > 0:
        return log_pattern[:dot_idx] + '-' + date_str + log_pattern[dot_idx:]
    return log_pattern + '-' + date_str




def discover_logs(log_pattern):
    """
    scan log directory and find all log files matching the pattern.
    returns list of dict sorted by date desc: [{name, path, size, mtime}]
    """
    import glob

    log_pattern = log_pattern.replace(chr(92), '/')

    # extract base dir from pattern
    parts = log_pattern.rsplit('/', 1)
    if len(parts) == 2:
        log_dir = parts[0]
        filename_pattern = parts[1]
    else:
        log_dir = '.'
        filename_pattern = log_pattern

    if not os.path.isdir(log_dir):
        return []

    # build a regex from the filename pattern to match date-based files
    has_strftime = '%Y' in filename_pattern or '%m' in filename_pattern or '%d' in filename_pattern

    if has_strftime:
        regex = re.escape(filename_pattern)
        regex = regex.replace(re.escape('%Y'), r'(\d{4})')
        regex = regex.replace(re.escape('%m'), r'(\d{2})')
        regex = regex.replace(re.escape('%d'), r'(\d{2})')
        regex = '^' + regex + '$'
    else:
        base, ext = os.path.splitext(filename_pattern)
        regex = '^' + re.escape(base) + r'-\d{4}-\d{2}-\d{2}' + re.escape(ext) + '$'

    results = []
    try:
        for entry in os.scandir(log_dir):
            if entry.is_file() and re.match(regex, entry.name):
                stat = entry.stat()
                results.append({
                    'name': entry.name,
                    'path': entry.path,
                    'size': stat.st_size,
                    'mtime': stat.st_mtime,
                    'mtime_str': datetime.datetime.fromtimestamp(
                        stat.st_mtime
                    ).strftime('%Y-%m-%d %H:%M:%S'),
                })
    except OSError:
        pass

    results.sort(key=lambda x: x['mtime'], reverse=True)
    return results


def safe_decode_body(body_bytes):
    """
    尝试把 body 解码为文本。
    如果失败，则返回 None。
    """
    if not body_bytes:
        return ""

    for encoding in ("utf-8", "gb18030", "latin-1"):
        try:
            return body_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue

    return None


def parse_json_body(body_text):
    """
    尝试将 body 文本解析为 JSON。
    """
    if not body_text:
        return None

    try:
        return json.loads(body_text)
    except Exception:
        return None


def json_dumps(data):
    return json.dumps(
        data,
        ensure_ascii=False,
        indent=2,
        sort_keys=False
    )


def json_dumps_line(data):
    return json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False
    )


def normalize_headers(headers):
    """
    将 HTTP Headers 转成普通 dict。
    """
    result = {}
    for k, v in headers.items():
        result[k] = v
    return result


def make_response(status=200, headers=None, body=None):
    """
    构造统一响应结构。
    """
    return {
        "status": status,
        "headers": headers or {},
        "body": body,
    }


# =========================
# Request Handler
# =========================



class LogViewerHandler:
    """
    built-in log viewer: file list, online browsing, download.
    """

    CSS = """
    <style>
      * { margin:0; padding:0; box-sizing:border-box; }
      body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
             background:#f0f2f5; color:#1a1a2e; line-height:1.6; }
      .header { background:linear-gradient(135deg,#1a1a2e,#16213e); color:#fff;
                padding:18px 24px; }
      .header h1 { font-size:20px; font-weight:600; }
      .header a { color:#8ecae6; text-decoration:none; margin-left:16px; font-size:14px; }
      .header a:hover { text-decoration:underline; }
      .container { max-width:1200px; margin:24px auto; padding:0 16px; }
      .card { background:#fff; border-radius:8px; box-shadow:0 1px 3px rgba(0,0,0,.08);
              overflow:hidden; margin-bottom:20px; }
      table { width:100%; border-collapse:collapse; }
      th { background:#f8f9fa; text-align:left; padding:10px 16px; font-size:13px;
           color:#666; border-bottom:1px solid #eee; }
      td { padding:10px 16px; border-bottom:1px solid #f0f0f0; font-size:14px; }
      tr:hover td { background:#f8fbff; }
      td.size { text-align:right; font-family:monospace; color:#555; }
      .btn { display:inline-block; padding:4px 12px; border-radius:4px; font-size:12px;
             text-decoration:none; border:none; cursor:pointer; }
      .btn-view { background:#e8f4f8; color:#0077b6; }
      .btn-view:hover { background:#d0ecf4; }
      .btn-dl { background:#e8f5e9; color:#2e7d32; margin-left:6px; }
      .btn-dl:hover { background:#c8e6c9; }
      .btn-nav { background:#1a1a2e; color:#fff; padding:6px 16px; font-size:13px; }
      .btn-nav:hover { background:#16213e; }
      .btn-nav.disabled { background:#aaa; cursor:default; pointer-events:none; opacity:0.5; }
      .log-box { background:#1a1a2e; color:#e0e0e0; padding:16px; font-family:"Cascadia Code",
                 "Fira Code",Consolas,monospace; font-size:13px; line-height:1.7;
                 overflow-x:auto; white-space:pre-wrap; word-break:break-all;
                 max-height:75vh; overflow-y:auto; }
      .log-box .ln { color:#555; user-select:none; margin-right:12px; }
      .log-box .jk { color:#8ecae6; }
      .log-box .js { color:#a7c957; }
      .log-box .jn { color:#f4a261; }
      .log-box .jb { color:#e76f51; }
      .log-box .jx { color:#999; }
      .nav-bar { display:flex; justify-content:space-between; align-items:center;
                 padding:12px 16px; background:#f8f9fa; border-bottom:1px solid #eee; }
      .nav-bar .info { font-size:13px; color:#666; }
      .empty { text-align:center; padding:60px 20px; color:#999; }
      .badge { display:inline-block; background:#e8f4f8; color:#0077b6; padding:2px 8px;
               border-radius:4px; font-size:12px; margin-left:8px; }
    </style>
    """

    @staticmethod
    def _hl(text):
        """simple JSON syntax highlighting."""
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = re.sub(r'"([^"]*?)"(\s*:)', r'<span class="jk">"\1"</span>\2', text)
        text = re.sub(r':\s*"(.*?)"', r': <span class="js">"\1"</span>', text)
        text = re.sub(r':\s*(\d+\.?\d*)', r': <span class="jn">\1</span>', text)
        text = re.sub(r':\s*(true|false)', r': <span class="jb">\1</span>', text)
        text = re.sub(r':\s*(null)', r': <span class="jx">\1</span>', text)
        return text

    @staticmethod
    def _fsize(size):
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return "{:.1f} {}".format(size, unit) if unit != "B" else "{} B".format(size)
            size /= 1024
        return "{:.1f} TB".format(size)

    def handle_list(self, handler, log_pattern):
        """file list page."""
        logs = discover_logs(log_pattern)
        bp = handler.server.log_viewer_path

        rows = ""
        for log in logs:
            rows += (
                "<tr>"
                '<td><a href="' + bp + '?file=' + log["name"] + '">' + log["name"] + '</a></td>'
                "<td>" + log["mtime_str"] + "</td>"
                '<td class="size">' + self._fsize(log["size"]) + "</td>"
                "<td>"
                '  <a class="btn btn-view" href="' + bp + '?file=' + log["name"] + '">View</a>'
                '  <a class="btn btn-dl" href="' + bp + '?file=' + log["name"] + '&download=1">Download</a>'
                "</td></tr>"
            )

        if not rows:
            body = '<div class="empty">No log files found.<br>Logs will appear here after requests are recorded.</div>'
        else:
            body = (
                '<div class="card"><table>'
                "<thead><tr><th>File</th><th>Last Modified</th><th>Size</th><th>Actions</th></tr></thead>"
                "<tbody>" + rows + "</tbody></table></div>"
            )

        html = (
            '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>HttpLog - Log Files</title>" + self.CSS + "</head><body>"
            '<div class="header"><h1>HttpLog <span class="badge">' + str(len(logs)) + ' file(s)</span></h1>'
            '<a href="' + bp + '">Refresh</a> <a href="/echo">Echo</a></div>'
            '<div class="container">' + body + '</div></body></html>'
        )
        return make_response(200, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}, html)

    def handle_view(self, handler, log_pattern, filename, query):
        """log viewer page with pagination."""
        bp = handler.server.log_viewer_path
        filepath = self._resolve(log_pattern, filename)

        if not filepath or not os.path.isfile(filepath):
            return make_response(404, {"Content-Type": "text/html; charset=utf-8"},
                                  self._err(bp, "Log file not found: " + filename))

        # pagination
        limit = min(int(query.get("limit", ["200"])[0]), 2000)
        offset = max(int(query.get("offset", ["0"])[0]), 0)

        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
        except Exception as e:
            return make_response(500, {"Content-Type": "text/html; charset=utf-8"},
                                  self._err(bp, "Error reading file: " + str(e)))

        total = len(all_lines)
        lines = all_lines[offset:offset + limit]

        rendered = ""
        for i, line in enumerate(lines):
            ln = offset + i + 1
            hl = self._hl(line.rstrip())
            rendered += '<span class="ln">' + str(ln).rjust(6) + '</span>' + hl + "\n"

        has_prev = offset > 0
        has_next = offset + limit < total
        prev_off = max(0, offset - limit)
        next_off = offset + limit
        last_off = max(0, total - limit)

        def nav_btn(label, off, disabled):
            cls = "btn btn-nav disabled" if disabled else "btn btn-nav"
            return '<a class="' + cls + '" href="' + bp + '?file=' + filename + '&offset=' + str(off) + '&limit=' + str(limit) + '">' + label + '</a>'

        showing_end = min(offset + limit, total)
        nav = (
            '<div class="nav-bar">'
            '<span class="info">Lines ' + str(offset+1) + '-' + str(showing_end) + ' of ' + str(total) + '</span>'
            "<div>"
            + nav_btn("First", 0, not has_prev)
            + nav_btn("Prev", prev_off, not has_prev)
            + nav_btn("Next", next_off, not has_next)
            + nav_btn("Last", last_off, not has_next)
            + ' <a class="btn btn-dl" href="' + bp + '?file=' + filename + '&download=1">Download</a>'
            + "</div></div>"
        )

        html = (
            '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>HttpLog - " + filename + "</title>" + self.CSS + "</head><body>"
            '<div class="header"><h1>' + filename + '</h1>'
            '<a href="' + bp + '">Back to list</a> <a href="/echo">Echo</a></div>'
            '<div class="container"><div class="card">' + nav + '<div class="log-box">' + rendered + '</div></div></div>'
            "</body></html>"
        )
        return make_response(200, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}, html)

    def handle_download(self, handler, log_pattern, filename):
        """download a log file."""
        filepath = self._resolve(log_pattern, filename)

        if not filepath or not os.path.isfile(filepath):
            return make_response(404, {"Content-Type": "application/json"},
                                  {"ok": False, "message": "file not found"})

        try:
            with open(filepath, "rb") as f:
                data = f.read()
            return make_response(200, {
                "Content-Type": "application/octet-stream",
                "Content-Disposition": 'attachment;filename="' + filename + '"',
                "Content-Length": str(len(data)),
            }, data)
        except Exception as e:
            return make_response(500, {"Content-Type": "application/json"},
                                  {"ok": False, "message": str(e)})

    def _resolve(self, log_pattern, filename):
        """resolve log file path, prevent path traversal."""
        if ".." in filename or "/" in filename or chr(92) in filename:
            return None
        parts = log_pattern.replace(chr(92), "/").rsplit("/", 1)
        log_dir = parts[0] if len(parts) == 2 else "."
        return os.path.normpath(os.path.join(log_dir, filename))

    def _err(self, bp, msg):
        return (
            '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Error</title>'
            + self.CSS + '</head><body>'
            '<div class="header"><h1>HttpLog</h1><a href="' + bp + '">Back</a></div>'
            '<div class="container"><div class="card"><div class="empty">' + msg + '</div></div></div>'
            "</body></html>"
        )


class HttpLogHandler(BaseHTTPRequestHandler):
    """
    处理任意 HTTP 请求并记录日志。
    """

    # 静默日志，不打印到 stderr（由 verbose 控制）
    def log_message(self, format, *args):
        if hasattr(self.server, "verbose") and self.server.verbose:
            super().log_message(format, *args)

    def do_GET(self):
        self.handle_any_request()

    def do_POST(self):
        self.handle_any_request()

    def do_PUT(self):
        self.handle_any_request()

    def do_DELETE(self):
        self.handle_any_request()

    def do_PATCH(self):
        self.handle_any_request()

    def do_HEAD(self):
        self.handle_any_request()

    def do_OPTIONS(self):
        self.handle_any_request()

    def do_TRACE(self):
        self.handle_any_request()

    def do_CONNECT(self):
        self.handle_any_request()

    def build_request_info(self):
        """
        构建完整的请求信息字典。
        """
        # 解析 URL
        parsed = urlparse(self.path)

        # 读取 Body
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = b""

        if content_length > 0:
            if content_length > MAX_BODY_SIZE:
                body_bytes = self.rfile.read(MAX_BODY_SIZE)
            else:
                body_bytes = self.rfile.read(content_length)

        body_text = safe_decode_body(body_bytes)
        body_json = parse_json_body(body_text)

        body_info = {}
        if body_text is not None:
            body_info["text"] = body_text
        if body_json is not None:
            body_info["json"] = body_json
        if body_text is None and body_bytes:
            body_info["base64"] = base64.b64encode(body_bytes).decode("ascii")
        body_info["content_type"] = self.headers.get("Content-Type", "")
        body_info["content_length"] = content_length

        # 构建完整信息
        request_info = {
            "timestamp": now_iso(),
            "client": {
                "ip": self.client_address[0],
                "port": self.client_address[1],
            },
            "request": {
                "method": self.command,
                "version": self.request_version,
            },
            "url": {
                "path": parsed.path,
                "query": parse_qs(parsed.query),
                "raw_query": parsed.query,
                "fragment": parsed.fragment,
            },
            "headers": normalize_headers(self.headers),
            "body": body_info,
        }

        return request_info

    def write_log(self, request_info):
        """
        将请求信息追加写入当日 JSONL 日志文件。
        """
        log_file = format_daily_log_path(self.server.log_file)
        try:
            log_dir = os.path.dirname(log_file)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json_dumps_line(request_info) + "\n")
        except Exception as e:
            sys.stderr.write(f"[!] Failed to write log: {e}\n")

    def run_plugins(self, request_info):
        """
        按顺序执行插件，返回第一个非 None 的响应。
        """
        for plugin_func in PLUGINS:
            try:
                result = plugin_func(request_info)
                if result is not None:
                    return result
            except Exception as e:
                sys.stderr.write(f"[!] Plugin {plugin_func.__name__} error: {e}\n")
                traceback.print_exc()

        return None

    def handle_echo(self, request_info):
        """
        /echo 接口：返回完整请求信息。
        """
        return make_response(
            status=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            body={
                "ok": True,
                "echo": request_info,
            }
        )

    def handle_default(self, request_info):
        """
        默认返回。
        """
        return make_response(
            status=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            body={
                "ok": True,
                "message": "request logged",
                "method": request_info["request"]["method"],
                "path": request_info["url"]["path"],
                "client": request_info["client"],
            }
        )

    def send_custom_response(self, response):
        """
        发送响应。
        """
        status = int(response.get("status", 200))
        headers = response.get("headers") or {}
        body = response.get("body", "")

        if isinstance(body, (dict, list)):
            body_bytes = json_dumps(body).encode("utf-8")
            headers.setdefault("Content-Type", "application/json; charset=utf-8")
        elif isinstance(body, bytes):
            body_bytes = body
        else:
            body_bytes = str(body).encode("utf-8")
            headers.setdefault("Content-Type", "text/plain; charset=utf-8")

        headers.setdefault("Content-Length", str(len(body_bytes)))
        headers.setdefault("Access-Control-Allow-Origin", "*")
        headers.setdefault("Access-Control-Allow-Methods", "*")
        headers.setdefault("Access-Control-Allow-Headers", "*")

        self.send_response(status)

        for k, v in headers.items():
            self.send_header(k, v)

        self.end_headers()

        if self.command != "HEAD":
            self.wfile.write(body_bytes)

    def handle_any_request(self):
        """
        处理任意请求。
        """
        try:
            request_info = self.build_request_info()

            # 先写日志
            self.write_log(request_info)

            path = request_info["url"]["path"]

            # 内置 /echo
            if path == "/echo":
                response = self.handle_echo(request_info)
                self.send_custom_response(response)
                return

            # 内置 log viewer
            if self.server.log_viewer and self.command == "GET" and path == self.server.log_viewer_path:
                viewer = self.server.log_viewer
                q = request_info["url"]["query"]
                filename = q.get("file", [None])[0]
                if filename and q.get("download"):
                    response = viewer.handle_download(self, self.server.log_file, filename)
                elif filename:
                    response = viewer.handle_view(self, self.server.log_file, filename, q)
                else:
                    response = viewer.handle_list(self, self.server.log_file)
                self.send_custom_response(response)
                return

            # 插件处理
            plugin_response = self.run_plugins(request_info)
            if plugin_response is not None:
                self.send_custom_response(plugin_response)
                return

            # 默认处理
            response = self.handle_default(request_info)
            self.send_custom_response(response)

        except Exception as e:
            traceback.print_exc()
            response = make_response(
                status=500,
                headers={
                    "Content-Type": "application/json; charset=utf-8"
                },
                body={
                    "ok": False,
                    "message": "internal server error",
                    "error": str(e),
                }
            )
            self.send_custom_response(response)


# =========================
# Server
# =========================

class HttpLogServer(ThreadingHTTPServer):
    def __init__(self, server_address, RequestHandlerClass, log_file, verbose=False, log_viewer_path=None):
        super().__init__(server_address, RequestHandlerClass)
        self.log_file = log_file
        self.verbose = verbose
        self.log_viewer_path = log_viewer_path
        self.log_viewer = LogViewerHandler() if log_viewer_path else None


def main():
    parser = argparse.ArgumentParser(
        description="HTTP request logger server"
    )

    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"listen host, default: {DEFAULT_HOST}"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"listen port, default: {DEFAULT_PORT}"
    )

    parser.add_argument(
        "--log",
        default=DEFAULT_LOG_FILE,
        help=f"log file path/pattern, default: {DEFAULT_LOG_FILE}. supports strftime: httplog-%Y-%m.jsonl"
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print access log to stderr"
    )

    parser.add_argument(
        "--daemon",
        action="store_true",
        help="run as background daemon process"
    )

    parser.add_argument(
        "--pid",
        default=DEFAULT_PID_FILE,
        help=f"PID file path (used with --daemon/--stop), default: {DEFAULT_PID_FILE}"
    )

    parser.add_argument(
        "--log-viewer",
        default=None,
        metavar="PATH",
        help="enable built-in log viewer at given path, e.g. /logs"
    )

    parser.add_argument(
        "--stop",
        action="store_true",
        help="stop the running daemon process (requires --pid)"
    )

    args = parser.parse_args()

    # --stop: 停止守护进程
    if args.stop:
        stop_daemon(args.pid)
        return

    # --daemon: 后台运行
    if args.daemon:
        daemonize(args.pid)

    server = HttpLogServer(
        server_address=(args.host, args.port),
        RequestHandlerClass=HttpLogHandler,
        log_file=args.log,
        verbose=args.verbose,
        log_viewer_path=args.log_viewer,
    )

    print(f"[+] HttpLog server listening on http://{args.host}:{args.port}")
    print(f"[+] Log file: {args.log}")
    print("[+] Echo URL: /echo")
    if args.log_viewer:
        print("[+] Log Viewer: http://{}:{}{}".format(args.host, args.port, args.log_viewer))
    print("[+] Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[+] Stopping server...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()