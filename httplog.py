#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
httplog.py

A lightweight HTTP request logger server.

Features:
1. Accept any HTTP method
2. Log client IP, port, request line, headers, query, body
3. /echo returns full request info
4. Auto split log files by day, support strftime path patterns
5. Plugin mechanism for custom responses
6. --daemon for background service
7. --log-viewer for web-based log browsing
8. --health /healthz endpoint

Usage:
    python httplog.py
    python httplog.py --host 0.0.0.0 --port 8080 --log httplog.jsonl
    python httplog.py --daemon
    python httplog.py --log-viewer /logs
    python httplog.py --stop --pid httplog.pid
"""

import argparse
import base64
import collections
import os
import socket
import threading
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http import HTTPStatus
from urllib.parse import urlparse, parse_qs

# Use HTTPStatus for reason phrases
http_responses = {v.value: v.phrase for v in HTTPStatus}

from daemon import daemonize, stop_daemon, write_pid_file, remove_pid_file, check_existing_instance
from plugins import run_plugins
from utils import (
    DEFAULT_HOST, DEFAULT_PORT, DEFAULT_LOG_FILE, DEFAULT_PID_FILE,
    MAX_BODY_SIZE, MAX_STATS_ENTRIES,
    now_iso, format_daily_log_path, safe_decode_body, parse_json_body,
    json_dumps, json_dumps_line, normalize_headers, make_response,
)
from viewer import LogViewerHandler


# =========================
# Request Handler
# =========================
class HttpLogHandler(BaseHTTPRequestHandler):
    """
    Handle any HTTP request and log it.
    """

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
        self.send_error(405, "CONNECT method not supported")

    def handle_healthz(self, request_info):
        """Health check endpoint."""
        stats = self.server.stats
        return make_response(
            status=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            body={
                "ok": True,
                "uptime": stats.uptime_str(),
                "requests": stats.total,
                "errors": stats.errors,
            }
        )

    def build_request_info(self):
        """
        构建完整的请求信息字典。
        """
        # 解析 URL
        parsed = urlparse(self.path)

        # 读取 Body
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            content_length = 0
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
        Run registered plugins.
        """
        try:
            response_data = run_plugins(request_info)
            if response_data:
                self.send_json_response(response_data)
                return response_data
        except Exception as e:
            sys.stderr.write(f"[!] Plugin error: {e}\n")

    def send_json_response(self, response_data):
        """
        Send a JSON response.
        """
        status = response_data.get("status", 200)
        headers = response_data.get("headers", {})
        body = response_data.get("body")

        reason = http_responses.get(status, "Unknown")
        self.send_response(status, reason)

        # CORS headers
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, PATCH, OPTIONS, HEAD")
        self.send_header("Access-Control-Allow-Headers", "*")

        for key, value in headers.items():
            self.send_header(key, value)

        if body is not None:
            try:
                body_bytes = json_dumps(body).encode("utf-8")
            except (TypeError, ValueError) as e:
                body_bytes = json_dumps({"error": "Serialization failed", "detail": str(e)}).encode("utf-8")
                self.send_response(500, "Internal Server Error")
                self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)
        else:
            self.send_header("Content-Length", "0")
            self.end_headers()

    def handle_any_request(self):
        """
        Main handler for all HTTP requests.
        """
        request_info = self.build_request_info()
        parsed = urlparse(self.path)

        # Skip logging for internal endpoints (healthz, log viewer)
        is_internal = parsed.path in ("/healthz", "/favicon.ico")
        if not is_internal and self.server.log_viewer and parsed.path.startswith(self.server.log_viewer_path):
            is_internal = True

        if not is_internal:
            self.write_log(request_info)
        if self.run_plugins(request_info):
            return

        # Health check endpoint
        if parsed.path == "/healthz":
            response = self.handle_healthz(request_info)
            self.send_json_response(response)
            return

        # Log viewer
        if self.server.log_viewer and parsed.path.startswith(self.server.log_viewer_path):
            viewer = self.server.log_viewer
            viewer.handle_request(self, self.server.log_file, self.server.log_viewer_path)
            return

        # Echo endpoint
        if parsed.path == "/echo":
            response = make_response(
                status=200,
                headers={"Content-Type": "application/json; charset=utf-8"},
                body=request_info
            )
            self.send_json_response(response)
            return

        # Default: echo request info
        response = make_response(
            status=200,
            headers={"Content-Type": "application/json; charset=utf-8"},
            body=request_info
        )
        self.send_json_response(response)


# =========================
# Request Statistics
# =========================
class RequestStats:
    """
    Thread-safe request statistics tracker.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.start_time = time.time()
        self.total = 0
        self.methods = collections.Counter()
        self.paths = collections.Counter()
        self.status_codes = collections.Counter()
        self.ips = collections.Counter()
        self.errors = 0

    def record(self, request_info, status=200):
        with self._lock:
            self.total += 1
            self.methods[request_info["request"]["method"]] += 1
            self.paths[request_info["url"]["path"]] += 1
            self.status_codes[status] += 1
            self.ips[request_info["client"]["ip"]] += 1
            if status >= 500:
                self.errors += 1
            if len(self.paths) > MAX_STATS_ENTRIES:
                self.paths = collections.Counter(dict(self.paths.most_common(MAX_STATS_ENTRIES // 2)))
            if len(self.ips) > MAX_STATS_ENTRIES:
                self.ips = collections.Counter(dict(self.ips.most_common(MAX_STATS_ENTRIES // 2)))

    def uptime_str(self):
        secs = int(time.time() - self.start_time)
        if secs < 60:
            return '{}s'.format(secs)
        if secs < 3600:
            return '{}m {}s'.format(secs // 60, secs % 60)
        return '{}h {}m'.format(secs // 3600, (secs % 3600) // 60)


class HttpLogServer(ThreadingHTTPServer):
    def __init__(self, server_address, RequestHandlerClass, log_file, verbose=False, log_viewer_path=None):
        super().__init__(server_address, RequestHandlerClass)
        self._log_lock = threading.Lock()
        self.log_file = log_file
        self.verbose = verbose
        self.log_viewer_path = log_viewer_path
        self.log_viewer = LogViewerHandler() if log_viewer_path else None
        self.stats = RequestStats()


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
        help=f"log file path/pattern, default: {DEFAULT_LOG_FILE}. supports strftime: httplog-%%Y-%%m.jsonl"
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
        "--_daemon-child",
        action="store_true",
        help=argparse.SUPPRESS
    )

    parser.add_argument(
        "--stop",
        action="store_true",
        help="stop the running daemon process (requires --pid)"
    )

    args = parser.parse_args()

    # auto-prepend / to --log-viewer path
    if args.log_viewer and not args.log_viewer.startswith("/"):
        args.log_viewer = "/" + args.log_viewer

    # --stop: 停止守护进程
    if args.stop:
        stop_daemon(args.pid)
        return

    # --daemon: 后台运行
    if args.daemon:
        # Check for existing instance
        if not check_existing_instance(args.pid):
            sys.exit(1)

        # Pre-check: verify port is available before forking
        try:
            _sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            _sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            _sock.bind((args.host, args.port))
            _sock.close()
        except OSError as e:
            print("[!] Port {} is not available: {}".format(args.port, e))
            print("[!] Is another instance already running?")
            sys.exit(1)

        daemonize(args.pid)

    try:
        server = HttpLogServer(
            server_address=(args.host, args.port),
            RequestHandlerClass=HttpLogHandler,
            log_file=args.log,
            verbose=args.verbose,
            log_viewer_path=args.log_viewer,
        )
    except OSError as e:
        print("[!] Failed to start server: {}".format(e))
        sys.exit(1)

    # Write PID file only after server successfully binds the port
    if args.daemon or args._daemon_child:
        write_pid_file(args.pid)

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
        # Clean up PID file if running as daemon
        if args.daemon or args._daemon_child:
            remove_pid_file(args.pid)


if __name__ == "__main__":
    main()

